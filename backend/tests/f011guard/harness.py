"""R19-A2-F011GUARD -- shared harness for the adversarial F-011 production-protection
regression.

NOTHING HERE DISPATCHES ANYTHING.  There is no queue write, no helper call, no bridge,
no game, no editor and no delete.  Every "dispatch" is a recording stub, and
``subprocess.run`` inside the imported server module is replaced with a function that
RAISES -- so a test that accidentally let a real child process start would fail loudly
instead of quietly touching the live session.

The suite imports the PRODUCTION modules by path (``backend/cleanup_ownership_legs.py``
and ``backend/entity_server.py``); it never edits them.  Mutation controls are produced by
compiling a mutated COPY OF THE SOURCE TEXT in memory with ``__file__`` pointed at the
real path, so ``ROOT``/repo-root resolution still works and the tree on disk is untouched.
"""
from __future__ import annotations

import copy
import atexit
import hashlib
import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE
while not (REPO / "tools/game-executor/cleanup_owned_entities.py").is_file():
    if REPO.parent == REPO:
        raise SystemExit("REPO_ROOT_NOT_FOUND from %s" % HERE)
    REPO = REPO.parent

LEGS_PATH = REPO / "backend/cleanup_ownership_legs.py"
SERVER_PATH = REPO / "backend/entity_server.py"

#: The real round materials produced by the execution layer (W18 fixed the producer's
#: destination directory to the same digest the consumer derives).
REAL_MATERIALS = (REPO / ".runtime/game-executor/mcp-business/cleanup"
                  / "f7755123978a1d8c29d42a94cf710a5b/round-materials.json")

LEVEL = 1073741839
OTHER_LEVEL = 1073741834
FROZEN = (1077936129, 1077936130, 1077936131)
#: The id the hand-off names as living in TWO levels at once.
DUAL_LEVEL_ID = 1077936135


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8",
                    newline="\n")
    return path


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_module_from_source(path, alias, rename=None):
    """Exec a module's source text as ``alias`` with ``__file__`` = the real path.

    ``rename`` is an optional ``(old, new)`` (or list of them) applied to the text first:
    that is how the mutation controls are built without touching the tree.
    """
    path = Path(path)
    source = path.read_text(encoding="utf-8")
    applied = []
    for old, new in ([rename] if isinstance(rename, tuple) else (rename or [])):
        if old not in source:
            raise AssertionError("MUTATION_ANCHOR_MISSING: %r" % old[:80])
        source = source.replace(old, new, 1)
        applied.append(old[:60].strip())
    module = types.ModuleType(alias)
    module.__file__ = str(path)
    module.__name__ = alias
    sys.modules[alias] = module
    exec(compile(source, str(path), "exec"), module.__dict__)
    module._MUTATIONS_APPLIED = applied
    return module


def load_legs(rename=None):
    return load_module_from_source(LEGS_PATH, "_r19_legs%s" % (_alias_suffix(rename)),
                                   rename=rename)


def load_server(rename=None, legs=None):
    module = load_module_from_source(SERVER_PATH, "_r19_server%s" % _alias_suffix(rename),
                                     rename=rename)
    if legs is not None:
        module._CLEANUP_LEGS = legs
    return module


def _alias_suffix(rename):
    if not rename:
        return ""
    pairs = [rename] if isinstance(rename, tuple) else list(rename)
    return "_" + hashlib.sha256("|".join(o for o, _ in pairs).encode()).hexdigest()[:8]


# --------------------------------------------------------------------------- #
# Fixtures built from the REAL round materials (read-only) plus small, declared
# deltas written under this work directory.
# --------------------------------------------------------------------------- #

def base_manifest():
    return copy.deepcopy(read_json(REAL_MATERIALS))


def real_receipt_ids(manifest):
    return [entry["entityId"] for entry in manifest["receipts"]]


def baseline_document():
    return read_json(manifest_paths()["preBaseline"])


def manifest_paths():
    manifest = base_manifest()
    return {"preBaseline": manifest["preBaseline"]["path"],
            "freshReadback": manifest["freshReadback"]["path"],
            "receiptsDir": str(Path(manifest["receipts"][0]["path"]).parent)}


def write_extra_receipt(name, source_path, transform):
    """Copy a real receipt, apply ``transform`` to the parsed body, write it here.

    Returns the index-entry fragment (path + recordedSha256) for the mutated file.
    """
    body = read_json(source_path)
    transform(body)
    target = HERE / "fixtures" / name
    write_json(target, body)
    return {"path": str(target), "recordedSha256": sha256_file(target)}


def write_baseline_with_extra(extra_ids):
    """The real pre-create baseline plus ``extra_ids``, as a pre-existing object."""
    document = baseline_document()
    entries = list(document["entities"])
    for entity_id in extra_ids:
        entries.append({"index": len(entries), "id": entity_id, "dictionaryKey": entity_id,
                        "configId": 20001034, "flags": {"value": 79, "names": ["id_read"]},
                        "position": None})
    document = dict(document, entities=entries)
    target = HERE / "fixtures" / ("baseline+%s.json"
                                  % "-".join(str(v) for v in extra_ids))
    write_json(target, document)
    return target


# --------------------------------------------------------------------------- #
# The dispatch sentinel -- proof that nothing real was dispatched
# --------------------------------------------------------------------------- #

class DispatchSentinel(object):
    """Records every call to the server's ``_run`` and every helper resolution."""

    def __init__(self):
        self.run_calls = []
        self.queue_calls = []
        self.handle_calls = []
        self.deleted_ids_payloads = []

    def run(self, argv, timeout=None, expect_json=True):
        self.run_calls.append(list(argv))
        if "--ids" in argv:
            self.deleted_ids_payloads.append([int(v) for v in argv[argv.index("--ids") + 1:]])
        return {"ok": True, "dryRun": True, "mapping": {}, "roundId": "stub"}

    def queue(self):
        self.queue_calls.append(True)
        return Path("Q:/not-a-real-queue"), {"helperPid": 0, "stub": True}

    def handle(self, handle):
        self.handle_calls.append(handle)
        return {"handle": handle, "run": "stub", "levelId": LEVEL, "entities": 1,
                "verifiedAtUtc": "2026-10-02T00:00:00Z", "sessionPath": "stub"}

    def bind(self, module, known_runs=("stub-run",)):
        module._run = self.run
        module.resolve_elevated_queue = self.queue
        module.load_handle = self.handle
        module._known_bridge_runs = lambda: list(known_runs)
        module.subprocess = types.SimpleNamespace(
            run=lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("REAL_SUBPROCESS_ATTEMPTED: %r" % (a[:1],))),
            DEVNULL=None, PIPE=None)
        return self

    # -- assertions ------------------------------------------------------- #
    def dispatched(self):
        return bool(self.run_calls)

    def summary(self):
        return {"runCalls": len(self.run_calls), "queueResolutions": len(self.queue_calls),
                "handleResolutions": len(self.handle_calls),
                "idsPayloads": self.deleted_ids_payloads,
                "ops": [argv[argv.index("--op") + 1] for argv in self.run_calls
                        if "--op" in argv]}


#: Every RUN gets its own evidence root, created once and removed at exit.
#:
#: This used to be ``HERE / "fixtures" / "route-evidence"`` -- a directory inside the tree
#: that the route only READ.  It now also WRITES: ``mw_scene_cleanup_owned`` records each
#: dispatch as an F-011 re-entry guard (claim before the send, outcome after).  With a
#: shared in-tree root that record leaked from one run of this suite into the next, and
#: the second run would see the first run's record and dispatch zero times -- measured
#: 2026-10-05, ``h-route-legit-dispatches-once`` runs once.  A suite you cannot run twice
#: is not a control, so the root is per-run and disposable.
#:
#: It stays STABLE within one run on purpose: the re-entry probe calls the route twice and
#: needs both calls to find the same record.  The two probes that reach the dispatch never
#: collide because they differ in ``dryRun``, which is part of the record key.
_ROUTE_EVIDENCE_ROOT = Path(tempfile.mkdtemp(prefix="f011guard-evidence-"))
atexit.register(shutil.rmtree, str(_ROUTE_EVIDENCE_ROOT), True)


def install_route_evidence(module, request_ids, manifest):
    """Put ``manifest`` where the route will look for it (this run's disposable root)."""
    root = _ROUTE_EVIDENCE_ROOT
    round_id = module._cleanup_round_id(request_ids)
    target = root / "cleanup" / round_id / "round-materials.json"
    write_json(target, manifest)
    module.EVIDENCE_ROOT = root
    return target


def tool_error(result):
    """The structured error body of a ``_fail`` CallToolResult, or None."""
    body = getattr(result, "structuredContent", None)
    if not isinstance(body, dict) or body.get("ok") is not False:
        return None
    return body.get("error") or {}


def tool_body(result):
    return getattr(result, "structuredContent", None) or {}
