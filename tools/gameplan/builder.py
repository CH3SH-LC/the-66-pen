"""Turn a validated :class:`GraphPlan` into the ordered native calls.

This is the only module in the package that talks to the bridge, and it does so
strictly through ``tools/authoring/author.py graph …`` — never by writing a queue
file itself.  The runner is injected, so the whole sequence is testable offline
with a fake and the *real* runner is a thin subprocess wrapper.

Dispatch discipline the builder inherits from ``author.py``:

* ``--elevated-queue`` is a **global** argument and must precede the ``graph``
  subcommand (``tools/authoring/README.md:53``).
* Graph work needs a **live run/lease** — ``graph_call`` calls ``lease(runId)``
  first (``author.py:255``), so the bridge must already be loaded into the editor.
* Every step carries its own ``--request-id``; the builder derives each id as a
  function of *that request*, so a rerun of the same request is a replay (returns
  the cached receipt) and a changed request is a refusal — never a silent
  duplicate (``author.py:349-379``).

Nothing here claims persistence.  Only a native ``save`` (a scene op, not a graph
op) plus an independent ``.gil`` readback proves that — see ``docs/gameplan/``.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from . import contracts
from .contracts import DATA_INPUT, ContractStore
from .plan import GraphPlan, validate_container_payload

#: A runner takes a full argv (already including the python executable and any
#: global flags) and returns the parsed JSON object that ``author.py`` printed.
Runner = Callable[[list[str]], dict]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AUTHOR_PY = _REPO_ROOT / "tools" / "authoring" / "author.py"
_DEFAULT_QUEUE = _REPO_ROOT / ".runtime" / "editor-bridge" / "elevated-queue"
#: ``author.py``'s request journal: one directory per request id, each holding the
#: ``claim.json`` written *before* the dispatch (``author.py:376-378``) and the
#: ``result.json`` written *after* it (``author.py:396``).  It is the only durable
#: record of a build that survived a crashed process -- the adapter's own
#: ``Spend``/``Spent`` set is in-memory and dies with the bridge scope
#: (``EditorAdapter.cs:31-32``).
DEFAULT_JOURNAL_DIR = _REPO_ROOT / ".runtime" / "authoring" / "requests"

#: Named refusal for a build whose ``build-plan`` step was recorded but never
#: reached its success status.  The graph may be half-built and there is no
#: working graph delete, so the builder must not silently dispatch again.
PRIOR_ATTEMPT_INCOMPLETE = "BUILD_PRIOR_ATTEMPT_INCOMPLETE"


class BuildError(Exception):
    """A build step returned ``ok != true``."""

    def __init__(self, step: str, result: dict):
        self.step = step
        self.result = result
        super().__init__(f"step {step!r} failed: {result.get('error') or result}")


def request_id(*parts: object) -> str:
    """A 32-hex id that is a pure function of the request it names."""
    raw = "\x1f".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _tagged(slot: str, value: object) -> str:
    """Encode a constant in ``author.py graph value --value-json`` shape."""
    if slot == "vector3" or isinstance(value, dict) and "vector3" in value:
        from tools.authoring.author import validate_scalar_payload
        payload = {"vector3": value} if isinstance(value, list) else value
        validate_scalar_payload(payload)
        if slot not in ("auto", "vector3") or not isinstance(payload, dict) or set(payload) != {"vector3"}:
            raise ValueError("vector3 slot/payload mismatch")
        return json.dumps(payload, allow_nan=False)
    if isinstance(value, (dict, list)):
        validate_container_payload(value)
        if slot != "auto":
            raise ValueError("container constants require slot='auto'")
        return json.dumps(value, ensure_ascii=True, allow_nan=False)
    if slot in ("int",):
        return json.dumps({"int": int(value)})  # type: ignore[arg-type]
    if slot in ("uint", "enum"):
        return json.dumps({"uint": int(value)})  # type: ignore[arg-type]
    if slot == "float":
        return json.dumps({"float": float(value)})  # type: ignore[arg-type]
    if slot == "bool":
        return json.dumps({"bool": bool(value)})
    if slot == "string":
        return json.dumps({"string": str(value)})
    if slot == "auto":
        # Explicit containers were handled above; infer the remaining scalars.
        if isinstance(value, bool):
            return json.dumps({"bool": value})
        if isinstance(value, int):
            return json.dumps({"int": value})
        if isinstance(value, float):
            return json.dumps({"float": value})
        return json.dumps({"string": str(value)})
    raise ValueError(f"unsupported slot {slot!r}")


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def prior_build_plan_attempts(journal_dir: Path, name: str) -> list[dict]:
    """Every journalled ``build-plan`` attempt for graph ``name``, oldest entry first.

    A batched build is recorded in two halves against the SAME request id: the claim
    (before the dispatch, ``author.py:376-378``) and the result (after it,
    ``author.py:396``).  The adapter mirrors that split for the native work itself --
    ``Spend("author-plan", …)`` is taken *before* the first native mutation
    (``AuthoringGraph.cs:756``) and ``Spend("author-plan-ready", …)`` only once every
    node, edge and value has landed (``AuthoringGraph.cs:819``).  So:

    * claim present + ``result.json`` missing  -> the dispatch outcome is UNKNOWN
      (``author.py:380``, ``REQUEST_OUTCOME_UNKNOWN``): the graph may be half-built.
    * claim present + ``result.json.ok is not True`` -> the step FAILED outright and,
      because the attempt was spent, ``AUTHOR_PLAN_ALREADY_ATTEMPTED`` blocks a retry
      while the scope survives.
    * claim present + ``result.json.ok is True`` -> the graph was built and the run is
      replay-safe.

    Only a ``build-plan`` claim whose payload ``name`` matches is considered, so an
    unrelated graph sharing the journal never makes this one look spoiled.
    """
    attempts: list[dict] = []
    if not journal_dir.is_dir():
        return attempts
    for entry in sorted(journal_dir.iterdir()):
        if not entry.is_dir():
            continue
        claim = _read_json(entry / "claim.json")
        command = claim.get("command") if claim else None
        payload = command.get("payload") if isinstance(command, dict) else None
        if not isinstance(payload, dict) or payload.get("action") != "build-plan":
            continue
        if payload.get("name") != name:
            continue
        result = _read_json(entry / "result.json")
        attempts.append({
            "requestId": entry.name,
            "journal": str(entry),
            "graphId": payload.get("graphId"),
            "outcomeKnown": result is not None,
            "ok": bool(result is not None and result.get("ok") is True),
            "error": (result or {}).get("error"),
        })
    return attempts


@dataclass
class Step:
    name: str
    request_id: str
    argv: list[str]
    result: dict

    @property
    def ok(self) -> bool:
        return self.result.get("ok") is True

    @property
    def backend(self) -> dict:
        value = self.result.get("backend")
        return value if isinstance(value, dict) else {}

    def summary(self) -> dict:
        backend = self.backend
        return {
            "step": self.name,
            "requestId": self.request_id,
            "ok": self.ok,
            "status": backend.get("status"),
            "error": self.result.get("error"),
            "nodeCount": backend.get("nodeCount"),
        }


@dataclass
class BuildResult:
    ok: bool
    graph_id: int | None = None
    node_ids: dict[str, int] = field(default_factory=dict)
    steps: list[Step] = field(default_factory=list)
    error: str | None = None
    partial: bool = False          # stopped early (op budget), not a failure
    #: True when a prior ``build-plan`` for this graph already SUCCEEDED, so a
    #: re-dispatch replays the journalled receipt instead of re-mutating.
    replay_safe: bool = False
    #: Every journalled ``build-plan`` attempt seen for this graph name, oldest first.
    prior_attempts: list[dict] = field(default_factory=list)

    def evidence(self) -> dict:
        return {
            "ok": self.ok,
            "partial": self.partial,
            "replaySafe": self.replay_safe,
            "priorAttempts": self.prior_attempts,
            "graphId": self.graph_id,
            "nodeIds": dict(sorted(self.node_ids.items())),
            "steps": [s.summary() for s in self.steps],
            "error": self.error,
        }


class GraphBuilder:
    """Execute a plan against the bridge via ``author.py``."""

    def __init__(
        self,
        plan: GraphPlan,
        runner: Runner,
        *,
        run_id: str,
        store: ContractStore | None = None,
        entity_id: int | None = None,
        expected_node_count: int | None = None,
        name_override: str | None = None,
        author_py: Path | None = None,
        queue_dir: Path | None = None,
        journal_dir: Path | None = None,
        python: str = "python",
        max_ops: int | None = None,
    ):
        self.plan = plan
        self.runner = runner
        self.run_id = run_id
        self.store = store
        self.entity_id = entity_id
        self.expected_node_count = expected_node_count
        self.name = name_override or plan.name
        self.author_py = author_py or _AUTHOR_PY
        self.queue_dir = queue_dir or _DEFAULT_QUEUE
        self.journal_dir = journal_dir or DEFAULT_JOURNAL_DIR
        self.python = python
        # The bridge scope's lease is five minutes and every graph dispatch re-hashes
        # the whole pin set on the runner, so a fixed ops budget keeps one run inside a
        # lease.  Completed requests replay from the journal on the next run, so a
        # budgeted run is resumable: reload the scope, run again, and it continues.
        self.max_ops = max_ops
        self._executed = 0
        self._steps: list[Step] = []

    def _budget_exhausted(self) -> bool:
        return self.max_ops is not None and self._executed >= self.max_ops

    # -- invocation --------------------------------------------------------

    def _argv(self, *graph_argv: str) -> list[str]:
        # --elevated-queue is GLOBAL: it must come before the `graph` subcommand.
        return [
            self.python, "-B", str(self.author_py),
            "--elevated-queue", str(self.queue_dir),
            "graph", *graph_argv,
        ]

    def _call(self, name: str, *graph_argv: str) -> Step:
        argv = self._argv(*graph_argv)
        result = self.runner(argv)
        if not isinstance(result, dict):
            raise BuildError(name, {"error": f"runner returned {type(result).__name__}"})
        step = Step(name=name, request_id=graph_argv[graph_argv.index("--request-id") + 1], argv=argv, result=result)
        self._steps.append(step)
        if result.get("replayed") is not True:
            self._executed += 1
        return step

    # -- expectation resolution -------------------------------------------

    def _expect(self, alias: str, port_index: int, override_type, override_generic):
        definition_id = {n.alias: n.definition_id for n in self.plan.nodes}[alias]
        store = self.store or contracts.default_store()
        port = store.require(definition_id).port(DATA_INPUT, port_index)
        if port is None:
            raise BuildError("value", {"error": f"no data-input pin 3:{port_index} on {definition_id}"})
        typ = port.server_param_type if override_type is None else int(override_type)
        gen = port.generic_id if override_generic is None else int(override_generic)
        return typ, gen

    # -- build -------------------------------------------------------------

    def build(self) -> BuildResult:
        store = self.store or contracts.default_store()
        try:
            self.plan.validate(store)
        except Exception as error:  # noqa: BLE001 - surfaced as an error field
            return BuildResult(ok=False, error=f"plan invalid: {error}")

        node_ids: dict[str, int] = {}
        graph_id: int | None = None

        # 1. create the graph.
        create = self._call(
            "create",
            "create",
            "--request-id", request_id(self.name, "create"),
            "--run-id", self.run_id,
            "--name", self.name,
            "--graph-kind", str(self.plan.graph_kind),
        )

        # 2. find its id (create is asynchronous: it returns a pending status).
        lookup = self._call(
            "lookup",
            "lookup",
            "--request-id", request_id(self.name, "lookup"),
            "--run-id", self.run_id,
            "--name", self.name,
        )
        graph_id = lookup.backend.get("graphId") or create.backend.get("graphId")
        if not isinstance(graph_id, int) or graph_id <= 0:
            # Fall back to inspect-by-name is not available; report honestly.
            return BuildResult(
                ok=False, steps=self._steps, error="no graphId after create/lookup",
                node_ids=node_ids,
            )

        # 3. add nodes one at a time; the editor assigns the instance ids.
        for index, node in enumerate(self.plan.nodes):
            if self._budget_exhausted():
                return BuildResult(ok=False, partial=True, graph_id=graph_id, node_ids=node_ids,
                                   steps=self._steps, error=f"op budget reached ({self._executed} ops); reload the scope and run again")
            step = self._call(
                f"add:{node.alias}",
                "add",
                "--request-id", request_id(self.name, "add", node.alias, node.definition_id, index),
                "--run-id", self.run_id,
                "--name", self.name,
                "--graph-id", str(graph_id),
                "--expected-node-count", str(index),
                "--definition-id", str(node.definition_id),
                "--x", str(node.x),
                "--y", str(node.y),
            )
            if not step.ok:
                return BuildResult(ok=False, graph_id=graph_id, node_ids=node_ids,
                                   steps=self._steps, error=f"add {node.alias} failed")
            added = step.backend.get("nodes")
            if not isinstance(added, list) or len(added) != index + 1:
                return BuildResult(ok=False, graph_id=graph_id, node_ids=node_ids,
                                   steps=self._steps,
                                   error=f"add {node.alias}: readback has {len(added) if isinstance(added, list) else '?'} nodes")
            # The adapter returns the whole graph's nodes in instance-id order, which
            # is insertion order. Verify rather than assume, then map alias -> nodeId.
            for i, planned in enumerate(self.plan.nodes[: index + 1]):
                if added[i].get("definitionId") != planned.definition_id:
                    return BuildResult(ok=False, graph_id=graph_id, node_ids=node_ids, steps=self._steps,
                                       error=f"node {i} read back as definitionId "
                                             f"{added[i].get('definitionId')}, expected {planned.definition_id}")
                node_ids[planned.alias] = added[i]["nodeId"]

        # 4. constants (before edges: a value write targets a declared pin, which
        #    exists as soon as the node does).
        for const in self.plan.consts:
            if self._budget_exhausted():
                return BuildResult(ok=False, partial=True, graph_id=graph_id, node_ids=node_ids,
                                   steps=self._steps, error=f"op budget reached ({self._executed} ops); reload the scope and run again")
            step = self._write_const(const, graph_id, node_ids)
            if step is not None and not step.ok:
                return BuildResult(ok=False, graph_id=graph_id, node_ids=node_ids,
                                   steps=self._steps, error=f"const {const.alias} failed")

        # 5. edges.
        for edge in self.plan.edges:
            if self._budget_exhausted():
                return BuildResult(ok=False, partial=True, graph_id=graph_id, node_ids=node_ids,
                                   steps=self._steps, error=f"op budget reached ({self._executed} ops); reload the scope and run again")
            src = node_ids.get(edge.src)
            dst = node_ids.get(edge.dst)
            if src is None or dst is None:
                return BuildResult(ok=False, graph_id=graph_id, node_ids=node_ids,
                                   steps=self._steps, error=f"unresolved edge {edge.src}->{edge.dst}")
            step = self._call(
                f"wire:{edge.src}->{edge.dst}",
                "wire",
                "--request-id", request_id(self.name, "wire", graph_id, src, edge.src_kind, edge.src_index,
                                           dst, edge.dst_kind, edge.dst_index),
                "--run-id", self.run_id,
                "--name", self.name,
                "--graph-id", str(graph_id),
                "--from-node-id", str(src),
                "--to-node-id", str(dst),
                "--from-port-kind", str(edge.src_kind),
                "--from-port-index", str(edge.src_index),
                "--to-port-kind", str(edge.dst_kind),
                "--to-port-index", str(edge.dst_index),
            )
            if not step.ok:
                return BuildResult(ok=False, graph_id=graph_id, node_ids=node_ids,
                                   steps=self._steps, error=f"wire {edge.src}->{edge.dst} failed")

        # 6. export (writes a .gia; still not persistence).
        export = self._call(
            "export",
            "export",
            "--request-id", request_id(self.name, "export", graph_id),
            "--run-id", self.run_id,
            "--name", self.name,
            "--graph-id", str(graph_id),
        )
        if not export.ok:
            return BuildResult(ok=False, graph_id=graph_id, node_ids=node_ids,
                               steps=self._steps, error="export failed")

        # 7. bind, if an entity was supplied.
        if self.entity_id is not None:
            count = self.expected_node_count if self.expected_node_count is not None else len(self.plan.nodes)
            bind = self._call(
                "bind",
                "bind",
                "--request-id", request_id(self.name, "bind", graph_id, self.entity_id),
                "--run-id", self.run_id,
                "--name", self.name,
                "--graph-id", str(graph_id),
                "--expected-node-count", str(count),
                "--entity-id", str(self.entity_id),
            )
            if not bind.ok:
                return BuildResult(ok=False, graph_id=graph_id, node_ids=node_ids,
                                   steps=self._steps, error="bind failed")

        return BuildResult(ok=True, graph_id=graph_id, node_ids=node_ids, steps=self._steps)

    # -- batched build -----------------------------------------------------

    def batch_plan_json(self) -> dict:
        """The plan in the adapter's ``build-plan`` shape (node refs are indices)."""
        index = {n.alias: i for i, n in enumerate(self.plan.nodes)}
        return {
            "nodes": [{"definitionId": n.definition_id, "x": n.x, "y": n.y} for n in self.plan.nodes],
            "edges": [
                {"from": index[e.src], "to": index[e.dst],
                 "fromKind": e.src_kind, "fromIndex": e.src_index,
                 "toKind": e.dst_kind, "toIndex": e.dst_index}
                for e in self.plan.edges
            ],
            "values": [
                {"node": index[c.alias], "portIndex": c.port_index, "slot": c.slot,
                 "value": json.loads(_tagged(c.slot, c.value))}
                for c in self.plan.consts
            ],
        }

    def build_batch(self, plan_path: Path | None = None) -> BuildResult:
        """Build the whole graph in ONE dispatch (``build-plan``).

        The runner re-hashes the entire pin set on every dispatch, so the per-op path
        costs ~16 s per node and a 40-op graph cannot fit the five-minute bridge scope.
        The adapter's ``build-plan`` action does the same native add/link/value work in
        one call, so the whole graph lands well inside one lease.

        Crash safety: before the first dispatch the journal is consulted for a previous
        ``build-plan`` against the SAME graph name.  A prior attempt that never reached
        success (missing or non-ok result) means the graph may be half-built and there is
        no working graph delete, so the build REFUSES with ``PRIOR_ATTEMPT_INCOMPLETE``
        rather than risk a second, partial graph.  A prior SUCCESS is replay-safe: it is
        reported (``replay_safe``) and the same request id replays from the journal.
        """
        store = self.store or contracts.default_store()
        try:
            self.plan.validate(store)
        except Exception as error:  # noqa: BLE001
            return BuildResult(ok=False, error=f"plan invalid: {error}")

        prior = prior_build_plan_attempts(self.journal_dir, self.name)
        spoiled = [a for a in prior if not a["ok"]]
        if spoiled:
            names = ", ".join(a["requestId"] for a in spoiled)
            return BuildResult(
                ok=False, prior_attempts=prior,
                error=(f"{PRIOR_ATTEMPT_INCOMPLETE}: a previous build-plan for {self.name!r} "
                       f"did not reach success ({names}); the graph may be half-built and "
                       f"there is no working graph delete -- refusing to dispatch again"),
            )
        replay_safe = bool(prior)

        path = plan_path or (_REPO_ROOT / ".runtime" / "scratch" / f"{self.name}-plan.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.batch_plan_json(), ensure_ascii=False, indent=1), encoding="utf-8")

        create = self._call("create", "create",
                            "--request-id", request_id(self.name, "create"),
                            "--run-id", self.run_id, "--name", self.name,
                            "--graph-kind", str(self.plan.graph_kind))
        lookup = self._call("lookup", "lookup",
                            "--request-id", request_id(self.name, "lookup"),
                            "--run-id", self.run_id, "--name", self.name)
        graph_id = lookup.backend.get("graphId") or create.backend.get("graphId")
        if not isinstance(graph_id, int) or graph_id <= 0:
            return BuildResult(ok=False, steps=self._steps, replay_safe=replay_safe, prior_attempts=prior,
                               error="no graphId after create/lookup")

        build = self._call("build-plan", "build-plan",
                           "--request-id", request_id(self.name, "build-plan", graph_id),
                           "--run-id", self.run_id, "--name", self.name,
                           "--graph-id", str(graph_id), "--expected-node-count", "0",
                           "--plan-file", str(path))
        if not build.ok:
            return BuildResult(ok=False, graph_id=graph_id, steps=self._steps, replay_safe=replay_safe,
                               prior_attempts=prior, error="build-plan failed")
        node_ids = {f"node{e['nodeId']}": e["nodeId"] for e in build.backend.get("nodes", [])}

        # An INDEPENDENT read-back: a second dispatch that only reads. The build call's own
        # reply is already a model read-back, but a separate inspect is the evidence rule
        # this project uses, and it fits in the same lease (one dispatch, ~16 s).
        inspect = self._call("inspect", "inspect",
                             "--request-id", request_id(self.name, "inspect", graph_id),
                             "--run-id", self.run_id, "--name", self.name, "--graph-id", str(graph_id))
        readback = [n.get("definitionId") for n in (inspect.backend.get("nodes") or [])]
        expected = [n.definition_id for n in self.plan.nodes]
        if inspect.ok and readback != expected:
            return BuildResult(ok=False, graph_id=graph_id, node_ids=node_ids, steps=self._steps,
                               replay_safe=replay_safe, prior_attempts=prior,
                               error=f"readback mismatch: {readback} != {expected}")

        export = self._call("export", "export",
                            "--request-id", request_id(self.name, "export", graph_id),
                            "--run-id", self.run_id, "--name", self.name, "--graph-id", str(graph_id))
        if not export.ok:
            return BuildResult(ok=False, graph_id=graph_id, node_ids=node_ids, steps=self._steps,
                               replay_safe=replay_safe, prior_attempts=prior,
                               error="export failed")

        if self.entity_id is not None:
            count = self.expected_node_count if self.expected_node_count is not None else len(self.plan.nodes)
            bind = self._call("bind", "bind",
                              "--request-id", request_id(self.name, "bind", graph_id, self.entity_id),
                              "--run-id", self.run_id, "--name", self.name,
                              "--graph-id", str(graph_id),
                              "--expected-node-count", str(count), "--entity-id", str(self.entity_id))
            if not bind.ok:
                return BuildResult(ok=False, graph_id=graph_id, node_ids=node_ids, steps=self._steps,
                                   replay_safe=replay_safe, prior_attempts=prior,
                                   error="bind failed")

        return BuildResult(ok=True, graph_id=graph_id, node_ids=node_ids, steps=self._steps,
                           replay_safe=replay_safe, prior_attempts=prior)

    def _write_const(self, const, graph_id: int, node_ids: dict[str, int]) -> Step | None:
        if const.alias not in node_ids:
            return None
        node_id = node_ids[const.alias]
        definition_id = {n.alias: n.definition_id for n in self.plan.nodes}[const.alias]
        base = ["--run-id", self.run_id, "--name", self.name, "--graph-id", str(graph_id), "--node-id", str(node_id)]
        # Proven dedicated ops first (README:92-93 / AuthoringGraph.cs:442,451).
        if definition_id == 1 and const.slot == "string":
            return self._call(
                f"set:{const.alias}",
                "set", "--request-id", request_id(self.name, "set", node_id, const.value),
                *base, "--text", str(const.value),
            )
        if definition_id == 2 and const.slot == "bool":
            return self._call(
                f"condition:{const.alias}",
                "condition", "--request-id", request_id(self.name, "condition", node_id, const.value),
                *base, "--value", "true" if const.value else "false",
            )
        typ, gen = self._expect(const.alias, const.port_index,
                                const.expect_server_param_type, const.expect_generic_id)
        return self._call(
            f"value:{const.alias}",
            "value",
            "--request-id", request_id(self.name, "value", node_id, const.port_index, const.value, const.slot),
            *base,
            "--port-index", str(const.port_index),
            "--expect-server-param-type", str(typ),
            "--expect-generic-id", str(gen),
            "--value-json", _tagged(const.slot, const.value),
            "--slot", const.slot,
        )


def subprocess_runner(python: str = "python") -> Runner:
    """The production runner: shell out to ``author.py`` and parse its JSON line."""

    def run(argv: list[str]) -> dict:
        completed = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8")
        stdout = (completed.stdout or "").strip()
        if not stdout:
            return {
                "ok": False,
                "error": f"no output (exit {completed.returncode})",
                "stderr": (completed.stderr or "").strip()[-2000:],
            }
        try:
            return json.loads(stdout.splitlines()[-1])
        except json.JSONDecodeError:
            return {"ok": False, "error": "unparseable author.py output", "stdout": stdout[-2000:]}

    return run


def simulated_runner(graph_id: int = 1) -> Runner:
    """A runner that answers like a cooperative editor, for dry runs.

    It invents a graph id and node instance ids the way the adapter would
    (1-based, in insertion order) and echoes the read-back shapes documented in
    ``AuthoringGraph.cs``.  It never touches the bridge; it exists so a caller can
    see the exact argv a plan would produce before spending a real call.
    """

    state = {"defs": []}

    def run(argv: list[str]) -> dict:
        action = argv[argv.index("graph") + 1]
        if action == "create":
            return {"ok": True, "backend": {"status": "create-requested-readback-pending"}}
        if action == "lookup":
            return {"ok": True, "backend": {"graphId": graph_id, "status": "editor-model-readback"}}
        if action == "add":
            state["defs"].append(int(argv[argv.index("--definition-id") + 1]))
            nodes = [{"nodeId": i + 1, "definitionId": d} for i, d in enumerate(state["defs"])]
            return {"ok": True, "backend": {"nodeCount": len(nodes), "nodes": nodes,
                                            "status": "node-added-editor-model-readback"}}
        return {"ok": True, "backend": {"status": f"{action}-simulated"}}

    return run
