"""One reusable offline fake of the editor bridge, for testing *whole sequences*.

Every other graph test builds its own throwaway runner.  That catches argv shape
bugs but not the things that actually bite in a live run:

* a **replayed** request (same id, same params) that must return the *cached*
  receipt without re-dispatching;
* a **request-id conflict** (same id, different params) that must refuse rather
  than silently duplicate -- the failure that has bitten this project in reality;
* a **lease expiring mid-sequence**, so the ops after it must fail closed;
* a **read-back that disagrees with the plan**, which must abort the build.

:class:`FakeBridge` models those, plus the exact wire shapes ``builder.py``
reads.  It is a Runner: ``GraphBuilder(plan, FakeBridge(), run_id=...)``.

Faithfulness is anchored, not invented
--------------------------------------

* **Status strings** are copied verbatim from ``AuthoringGraph.cs``:
  ``create-requested-readback-pending`` (:232),
  ``editor-model-readback`` (:259), ``plan-built-export-readback-pending`` (:270),
  ``binding-requested-readback-pending`` (:318), ``node-added-editor-model-readback``
  (:345), ``node-value-slots-read-only`` (:382, the read-only ``pin-slots`` reply);
  ``invoked-not-confirmed`` is the export reply (``EditorAdapter.cs:950``).
* **Refusal codes** are the ``InvalidOperationException`` texts the adapter
  throws, e.g. ``AUTHOR_NODE_COUNT_CONFLICT`` (``AuthoringGraph.cs:299``),
  ``AUTHOR_GRAPH_IDENTITY_MISMATCH`` (:235), ``AUTHOR_VALUE_TYPE_MISMATCH`` (:382),
  ``AUTHOR_BOUND_GRAPH_EDIT_REFUSED`` (:263).
* **Reply envelopes** match ``author.py``: a dispatch returns
  ``{ok, requestId, backend, replayed, retryAttempted}`` (``author.py:389-393``);
  a replay returns the cached receipt with ``replayed: true`` (:379); a
  request-id conflict is a *top-level* ``{ok: false, error: "REQUEST_ID_CONFLICT"}``
  raised before dispatch (:375, caught at :714); a dead lease is a ``backend``
  error ``ELEVATED_GRAPH_REFUSED`` (``elevated_graph_call`` -> ``result['backend']``).

This is a model, not a simulator: it answers only the fields the builder reads.
It never touches a process, the queue or the game.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

# -- documented status strings (AuthoringGraph.cs / EditorAdapter.cs) --------

STATUS_CREATE_PENDING = "create-requested-readback-pending"
STATUS_LOOKUP_PENDING = "lookup-pending"
STATUS_EDITOR_MODEL_READBACK = "editor-model-readback"
STATUS_ADDED = "node-added-editor-model-readback"
STATUS_WIRE_ACCEPTED = "link-accepted-export-readback-pending"
STATUS_VALUE_SET = "value-set-readback-verified"
STATUS_PRINT_SET = "print-value-set-export-readback-pending"
STATUS_BRANCH_SET = "branch-condition-set-export-readback-pending"
STATUS_PLAN_BUILT = "plan-built-export-readback-pending"
STATUS_BINDING_PENDING = "binding-requested-readback-pending"
STATUS_ALREADY_BOUND = "already-bound-editor-model-readback"
STATUS_EXPORT_INVOKED = "invoked-not-confirmed"
STATUS_SLOTS_READ_ONLY = "node-value-slots-read-only"  # AuthoringGraph.cs:382

#: The refusal codes exercised by the tests, all real adapter strings.
REFUSAL_NODE_COUNT_CONFLICT = "AUTHOR_NODE_COUNT_CONFLICT"
REFUSAL_GRAPH_IDENTITY_MISMATCH = "AUTHOR_GRAPH_IDENTITY_MISMATCH"
REFUSAL_VALUE_TYPE_MISMATCH = "AUTHOR_VALUE_TYPE_MISMATCH"
REFUSAL_BOUND_GRAPH_EDIT_REFUSED = "AUTHOR_BOUND_GRAPH_EDIT_REFUSED"
REFUSAL_NAME_ALREADY_EXISTS = "AUTHOR_NAME_ALREADY_EXISTS"
REFUSAL_SELF_LINK_REFUSED = "AUTHOR_SELF_LINK_REFUSED"
REFUSAL_PLAN_REQUIRES_EMPTY_GRAPH = "AUTHOR_PLAN_REQUIRES_EMPTY_GRAPH"

#: The lease is dead, not the request.  ``elevated_graph_call`` shape.
ERROR_LEASE_REFUSED = "ELEVATED_GRAPH_REFUSED"
ERROR_REQUEST_ID_CONFLICT = "REQUEST_ID_CONFLICT"

#: The actions the bound-graph gate PERMITS, as the CLI verbs this fake dispatches on.
#: Mirrors ``AuthoringGraph.cs``: the guard (``:285``) exempts ``bind`` on its own line
#: (``action!="bind"``) plus every action ``AuthorReadOnly(action)`` names -- and the bridge
#: names exactly one, ``"pin-slots"`` (``:227``).  ``pin-slots`` is this module's ``slots``
#: (``author.py`` ``GRAPH_ACTIONS``: ``'slots': 'pin-slots'``).  Every other action still
#: takes the refusal, and the read verbs (``inspect``/``lookup``/``export``) return before
#: the guard in the bridge and so never consult it here either.
#:
#: This set MUST stay IDENTICAL to the bridge's exemption:
#: ``test_bound_graph_gate_mirrors_bridge.py`` parses the predicate and pins the equality,
#: failing if this grows (more permissive than the bridge = defect) or shrinks.
BOUND_GRAPH_ALLOWED = frozenset({"bind", "slots"})


class FakeBridge:
    """A callable Runner that models one bridge scope.

    Knobs (all optional):

    ``graph_id``
        The id ``lookup``/``inspect`` report once ``create`` has settled.
    ``lease_ops``
        Dispatched (non-replayed) ops the scope allows before its lease expires.
        ``None`` = no lease limit.
    ``lookup_pending``
        How many ``lookup`` calls report ``lookup-pending`` (no ``graphId``)
        before the asynchronous ``create`` becomes visible.
    ``readback_definitions``
        When set, the definition ids the state read-backs *report*, sliced to
        the number actually built.  Models an editor that came back with a
        different node than the plan asked for.
    ``bound_entity_id``
        Bind the graph up front, so any non-read action is refused with
        ``AUTHOR_BOUND_GRAPH_EDIT_REFUSED``.
    ``refuse``
        ``{action: code}`` -- force that graph action to return ``code`` as a
        backend refusal, to exercise the four named refusals without staging the
        whole state that would naturally produce them.
    ``declared_value_type``
        ``(typeId, genericId)`` the "editor" declares for a value write's target
        pin; a request whose ``--expect-*`` differs is refused with
        ``AUTHOR_VALUE_TYPE_MISMATCH``.
    """

    def __init__(
        self,
        *,
        graph_id: int = 1073741900,
        lease_ops: int | None = None,
        lookup_pending: int = 0,
        readback_definitions: list[int] | None = None,
        bound_entity_id: int | None = None,
        refuse: dict[str, str] | None = None,
        declared_value_type: tuple[int, int] | None = None,
    ):
        self.graph_id = graph_id
        self.lease_ops = lease_ops
        self.lookup_pending = lookup_pending
        self.readback_definitions = readback_definitions
        self.refuse = dict(refuse or {})
        self.declared_value_type = declared_value_type

        # observable ledger
        self.calls: list[list[str]] = []           # every argv seen
        self.dispatched: list[str] = []            # actions actually executed (replays excluded)
        self.journal: dict[str, dict] = {}         # request id -> {fingerprint, receipt}

        # scope state
        self._ops = 0
        self._created = False
        self._lookups = 0
        self._defs: list[int] = []
        self._bound: int | None = bound_entity_id
        self.exported: list[dict] = []

    # -- argv parsing ------------------------------------------------------

    @staticmethod
    def action_of(argv: list[str]) -> str:
        """The ``graph`` subcommand name in an argv (what the builder dispatches)."""
        return argv[argv.index("graph") + 1]

    @staticmethod
    def _split(argv: list[str]) -> tuple[str, dict[str, str]]:
        index = argv.index("graph")
        action = argv[index + 1]
        rest = argv[index + 2:]
        opts: dict[str, str] = {}
        i = 0
        while i < len(rest):
            token = rest[i]
            if token.startswith("--"):
                opts[token[2:]] = rest[i + 1] if i + 1 < len(rest) else ""
                i += 2
            else:
                i += 1
        return action, opts

    @staticmethod
    def _plan_of(action: str, opts: dict[str, str]):
        """For ``build-plan`` the plan *content* is part of the request (author.py:591)."""
        if action != "build-plan":
            return None
        path = opts.get("plan-file")
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {"__unreadable__": str(path)}

    @staticmethod
    def _fingerprint(action: str, opts: dict[str, str], plan) -> str:
        # The request id is *not* part of the command author.py fingerprints
        # (author.py:368); everything else is.  Changing any other field under the
        # same id is a conflict, not a replay.
        material = {
            "action": action,
            "opts": {k: v for k, v in sorted(opts.items()) if k != "request-id"},
        }
        if plan is not None:
            material["plan"] = plan
        blob = json.dumps(material, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    # -- Runner protocol ---------------------------------------------------

    def __call__(self, argv: list[str]) -> dict:
        action, opts = self._split(argv)
        request_id = opts.get("request-id")
        plan = self._plan_of(action, opts)
        fingerprint = self._fingerprint(action, opts, plan)
        self.calls.append(list(argv))

        # 1. The journal is consulted BEFORE any dispatch (author.py:352-379).
        if request_id and request_id in self.journal:
            entry = self.journal[request_id]
            if entry["fingerprint"] != fingerprint:
                # Raised, never dispatched; reaches the caller as a top-level error.
                return {"ok": False, "error": ERROR_REQUEST_ID_CONFLICT, "retryAttempted": False}
            receipt = copy.deepcopy(entry["receipt"])
            receipt["replayed"] = True
            return receipt

        # 2. A dead lease refuses the dispatch (elevated_graph_call shape).
        if self.lease_ops is not None and self._ops >= self.lease_ops:
            return self._envelope(
                {"ok": False, "error": ERROR_LEASE_REFUSED, "outcomeUncertain": True,
                 "pending": False, "retryAttempted": False},
                request_id, mutating=True,
            )

        # 3. Execute.
        backend = self._dispatch(action, opts)
        self._ops += 1
        self.dispatched.append(action)

        receipt = self._envelope(backend, request_id, mutating=action not in ("inspect", "lookup", "slots"))
        if request_id:
            self.journal[request_id] = {"fingerprint": fingerprint, "receipt": copy.deepcopy(receipt)}
        return receipt

    @staticmethod
    def _envelope(backend: dict, request_id: str | None, *, mutating: bool) -> dict:
        """author.py's result envelope (author.py:389-393)."""
        result = {
            "ok": backend.get("ok") is True,
            "requestId": request_id,
            "backend": backend,
            "retryAttempted": False,
            "replayed": False,
            "persistenceVerified": False,
            "officialPlaytestVerified": False,
        }
        if backend.get("ok") is not True:
            result["outcomeUncertain"] = mutating and backend.get("outcomeUncertain", True)
        return result

    # -- dispatch ----------------------------------------------------------

    def _refusal(self, code: str) -> dict:
        # A refusal is an InvalidOperationException on the editor side; the runner
        # writes it to <id>.error.txt and the reply carries the text (elevated-runner.ps1:901).
        return {"ok": False, "error": f"System.InvalidOperationException: {code}", "code": code}

    def _dispatch(self, action: str, opts: dict[str, str]) -> dict:
        if action in self.refuse:
            return self._refusal(self.refuse[action])
        handler = getattr(self, "_act_" + action.replace("-", "_"), None)
        if handler is None:
            return {"ok": False, "error": "AUTHOR_ACTION_UNSUPPORTED", "code": "AUTHOR_ACTION_UNSUPPORTED"}
        return handler(opts)

    def _reported_defs(self) -> list[int]:
        if self.readback_definitions is None:
            return list(self._defs)
        return list(self.readback_definitions)[: len(self._defs)]

    def _state(self, status: str) -> dict:
        nodes = [{"nodeId": i + 1, "definitionId": d} for i, d in enumerate(self._reported_defs())]
        return {
            "ok": True,
            "status": status,
            "name": None,  # filled by callers that need it
            "graphId": self.graph_id,
            "nodeCount": len(nodes),
            "nodes": nodes,
            "boundEntityIds": [self._bound] if self._bound is not None else [],
            "boundToLevel": False,
            "persistentSaveVerified": False,
            "runtimeVerified": False,
        }

    def _graph_gate(self, opts: dict[str, str]) -> dict | None:
        gid = int(opts.get("graph-id", "0") or 0)
        if gid and gid != self.graph_id:
            return self._refusal(REFUSAL_GRAPH_IDENTITY_MISMATCH)
        return None

    def _edit_gate(self, action: str) -> dict | None:
        # Editing a bound graph could change live gameplay (AuthoringGraph.cs:285). The
        # bridge exempts `bind` (idempotent, its own guard line) and the AuthorReadOnly
        # allowlist (read-only), and refuses every OTHER action verbatim. `BOUND_GRAPH_ALLOWED`
        # is that exemption set; test_bound_graph_gate_mirrors_bridge.py pins it to the source.
        if self._bound is not None and action not in BOUND_GRAPH_ALLOWED:
            return self._refusal(REFUSAL_BOUND_GRAPH_EDIT_REFUSED)
        return None

    # -- per-action handlers ----------------------------------------------

    def _act_create(self, opts: dict[str, str]) -> dict:
        if self._created:
            return self._refusal(REFUSAL_NAME_ALREADY_EXISTS)
        self._created = True
        self._lookups = 0
        return {
            "ok": True,
            "status": STATUS_CREATE_PENDING,
            "name": opts.get("name"),
            "graphKind": int(opts.get("graph-kind", "20000") or 20000),
            "persistentSaveVerified": False,
            "runtimeVerified": False,
        }

    def _act_lookup(self, opts: dict[str, str]) -> dict:
        if not self._created:
            return {"ok": True, "status": STATUS_LOOKUP_PENDING, "name": opts.get("name"),
                    "persistentSaveVerified": False, "runtimeVerified": False}
        self._lookups += 1
        if self._lookups <= self.lookup_pending:
            return {"ok": True, "status": STATUS_LOOKUP_PENDING, "name": opts.get("name"),
                    "persistentSaveVerified": False, "runtimeVerified": False}
        state = self._state(STATUS_EDITOR_MODEL_READBACK)
        state["name"] = opts.get("name")
        return state

    def _act_add(self, opts: dict[str, str]) -> dict:
        if (gate := self._graph_gate(opts)) or (gate := self._edit_gate("add")):
            return gate
        expected = int(opts.get("expected-node-count", str(len(self._defs))) or 0)
        if expected != len(self._defs):
            return self._refusal(REFUSAL_NODE_COUNT_CONFLICT)
        self._defs.append(int(opts["definition-id"]))
        state = self._state(STATUS_ADDED)
        state["name"] = opts.get("name")
        return state

    def _act_wire(self, opts: dict[str, str]) -> dict:
        if (gate := self._graph_gate(opts)) or (gate := self._edit_gate("wire")):
            return gate
        if opts.get("from-node-id") == opts.get("to-node-id"):
            return self._refusal(REFUSAL_SELF_LINK_REFUSED)
        state = self._state(STATUS_WIRE_ACCEPTED)
        state["name"] = opts.get("name")
        return state

    def _act_value(self, opts: dict[str, str]) -> dict:
        if (gate := self._graph_gate(opts)) or (gate := self._edit_gate("value")):
            return gate
        if self.declared_value_type is not None:
            declared = self.declared_value_type
            asked = (int(opts.get("expect-server-param-type", "0") or 0),
                     int(opts.get("expect-generic-id", "0") or 0))
            if declared != asked:
                return self._refusal(REFUSAL_VALUE_TYPE_MISMATCH)
        return {
            "ok": True,
            "status": STATUS_VALUE_SET,
            "graphId": self.graph_id,
            "nodeId": int(opts.get("node-id", "0") or 0),
            "portKind": 3,
            "portIndex": int(opts.get("port-index", "0") or 0),
            "slot": opts.get("slot", "auto"),
            "persistentSaveVerified": False,
            "runtimeVerified": False,
        }

    def _act_set(self, opts: dict[str, str]) -> dict:
        if (gate := self._graph_gate(opts)) or (gate := self._edit_gate("set")):
            return gate
        state = self._state(STATUS_PRINT_SET)
        state["name"] = opts.get("name")
        return state

    def _act_condition(self, opts: dict[str, str]) -> dict:
        if (gate := self._graph_gate(opts)) or (gate := self._edit_gate("condition")):
            return gate
        state = self._state(STATUS_BRANCH_SET)
        state["name"] = opts.get("name")
        return state

    def _act_build_plan(self, opts: dict[str, str]) -> dict:
        if (gate := self._graph_gate(opts)) or (gate := self._edit_gate("build-plan")):
            return gate
        if self._defs:
            return self._refusal(REFUSAL_PLAN_REQUIRES_EMPTY_GRAPH)
        plan = self._plan_of("build-plan", opts) or {}
        self._defs = [int(n["definitionId"]) for n in plan.get("nodes", [])]
        state = self._state(STATUS_PLAN_BUILT)
        state["name"] = opts.get("name")
        return state

    def _act_inspect(self, opts: dict[str, str]) -> dict:
        if gate := self._graph_gate(opts):
            return gate
        state = self._state(STATUS_EDITOR_MODEL_READBACK)
        state["name"] = opts.get("name")
        return state

    def _act_export(self, opts: dict[str, str]) -> dict:
        if gate := self._graph_gate(opts):
            return gate
        reply = {
            "ok": True,
            "status": STATUS_EXPORT_INVOKED,
            "graphId": self.graph_id,
            "path": f"<export>/{opts.get('name')}.gia",
            "callbackWindowSeconds": 30,
            "persistentSaveVerified": False,
            "runtimeVerified": False,
        }
        self.exported.append(reply)
        return reply

    def _act_slots(self, opts: dict[str, str]) -> dict:
        # READ-ONLY (AuthoringGraph.cs:376-394, `node-value-slots-read-only`). Deliberately
        # does NOT consult `_edit_gate`: on a BOUND graph this read is the whole point, and the
        # bridge grants it through the AuthorReadOnly allowlist. It invokes no native
        # constructor/setter and reports `graphModified:false`. The fake carries no declared
        # pin schema, so `pins` is empty -- the shape, not a catalogue, is what the consumer reads.
        if gate := self._graph_gate(opts):
            return gate
        node_id = int(opts.get("node-id", "0") or 0)
        definition_id = self._defs[node_id - 1] if 1 <= node_id <= len(self._defs) else 0
        return {
            "ok": True,
            "status": STATUS_SLOTS_READ_ONLY,
            "graphId": self.graph_id,
            "nodeId": node_id,
            "definitionId": definition_id,
            "pins": [],
            "nativeConstructorsInvoked": False,
            "graphModified": False,
            "sentToGame": False,
            "persistentSaveVerified": False,
            "runtimeVerified": False,
        }

    def _act_bind(self, opts: dict[str, str]) -> dict:
        if gate := self._graph_gate(opts):
            return gate
        entity_id = int(opts.get("entity-id", "0") or 0)
        if self._bound == entity_id:
            state = self._state(STATUS_ALREADY_BOUND)
            state["name"] = opts.get("name")
            return state
        expected = int(opts.get("expected-node-count", str(len(self._defs))) or 0)
        if expected != len(self._defs):
            return self._refusal(REFUSAL_NODE_COUNT_CONFLICT)
        self._bound = entity_id
        return {
            "ok": True,
            "status": STATUS_BINDING_PENDING,
            "name": opts.get("name"),
            "graphId": self.graph_id,
            "entityId": entity_id,
            "persistentSaveVerified": False,
            "runtimeVerified": False,
        }
