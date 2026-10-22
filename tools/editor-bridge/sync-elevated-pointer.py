#!/usr/bin/env python3
"""sync-elevated-pointer.py -- the writer the elevated-session pointer never had.

BACKGROUND
----------
``.runtime/editor-bridge/current-elevated-session.json`` is read by several
business tools (``backend/entity_server.py``,
``tools/game-executor/build_reopen_profile.py``,
``tools/entity-create/run_template_matrix.py``,
``tools/game-executor/run_live_crud_acceptance.py``) but had **no writer in this
tree**: it was edited by hand, so every cached field rotted silently.  MEASURED
2026-09-29: the file still said ``helperPid 45696 / status "active"`` for a
process that was long gone, and it carried a ``deadlineLocal`` that was 694
minutes *before* its own ``helperStartedUtc`` -- a self-contradiction nobody
noticed because nothing wrote the file and nothing cross-checked it.

WHAT THIS DOES
--------------
``register`` rebuilds the pointer **from the helper's own launch receipt and
nothing else**, then swaps it in atomically.  A "launch receipt" is the reply the
resident helper itself returns to ``{"kind": "status"}`` over its queue
(``tools/editor-bridge/elevated-request.py --queue-dir <Q> status``), cross-bound
to the live ``runner.heartbeat``:

    pid           <- receipt["pid"]            (must equal the heartbeat's pid)
    creation      <- receipt["startedUtc"]     (the helper's own session start)
    deadline      <- receipt["deadlineUtc"]    (must equal creation + lifetime)
    pinsDigest    <- receipt["nativeScene"]["pinsDigest"]
    projectRoot   <- receipt["nativeScene"]["projectRoot"]
    actions       <- receipt["nativeScene"]["actions"]

No field is inferred, defaulted, or carried over from the previous pointer.  A
receipt that is stale (expired, or from a dead helper whose heartbeat stopped),
conflicting (heartbeat pid != receipt pid; deadline != start + lifetime;
projectRoot elsewhere), or incomplete (any of schema/enabled/actions/pinsDigest/
projectRoot/startedUtc/deadlineUtc missing or malformed) is **refused**, and the
pointer is left untouched.

``verify`` re-reads an existing pointer against a fresh receipt and reports any
divergence, refusing loudly.  It exists because
``build_reopen_profile.py:149`` trusts ``pointer["deadlineUtc"]`` as the helper
authorization cutoff: a pointer that *over-states* the window lets a reopen run
past the real expiry, so a stale cache must be detectable rather than silent.

BOUNDARY
--------
This tool never starts a helper, never raises elevation, never dispatches a
native request, and never writes to the elevated queue.  ``register`` writes
exactly one document -- the pointer -- and (unless ``--no-backup``) copies the
previous document aside first.

OFFLINE USE
-----------
``--receipt-file`` supplies a receipt from disk instead of querying the helper,
and ``--queue-dir``/``--pointer`` may point anywhere.  Both together make the
whole tool exercisable offline against a synthetic queue directory + a stub
status receipt, with no helper, no game, and no bridge involved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POINTER = ROOT / ".runtime/editor-bridge/current-elevated-session.json"
DEFAULT_QUEUE = ROOT / ".runtime/editor-bridge/elevated-queue"
QUEUE_BOUNDARY = ROOT / ".runtime/editor-bridge"

# Must match backend/entity_server.py / elevated-request.py: the helper is only
# usable if its advertised action set is exactly this.
NATIVE_ACTIONS = ("inspect", "create", "save", "create-batch", "reopen-current", "creature-create")
PIN_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
HEARTBEAT_RE = re.compile(r"([^ ]+) pid=([0-9]+) handled=([0-9]+)\Z")
POINTER_SCHEMA = "elevated-session-pointer/1"

# The same liveness window the native client uses (elevated-request.py:374).  A
# heartbeat older than this is not proof of a live helper, so it is not proof of
# a launch either.
HEARTBEAT_MIN_AGE = -5.0
HEARTBEAT_MAX_AGE = 30.0
# Allow the helper clock and ours to disagree by a little without treating a
# fresh receipt as fabricated.  Generous enough for NTP skew, small enough that a
# receipt from "tomorrow" is still refused.
CLOCK_SKEW = timedelta(seconds=120)


class Refused(Exception):
    """A registration that must not be written.  Carries a stable code."""

    def __init__(self, code: str, message: str, **detail):
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.message = message
        self.detail = detail

    def as_json(self) -> dict:
        return {"ok": False, "refused": self.code, "message": self.message, "detail": self.detail}


# --------------------------------------------------------------------------- #
# Receipt acquisition
# --------------------------------------------------------------------------- #

def fetch_receipt(queue_dir: Path, *, timeout: float = 30.0) -> dict:
    """Obtain the helper's own status reply over its queue.

    This is the *only* legitimate launch receipt.  It is deliberately the same
    call ``backend/entity_server.py`` makes; this tool adds nothing to the wire
    and asks the helper for nothing but ``status``.
    """
    script = ROOT / "tools/editor-bridge/elevated-request.py"
    # MEASURED 2026-10-06, on the real tree with the helper ABSENT: this call used to
    # raise ``subprocess.TimeoutExpired`` straight out of ``main()``, so ``register``
    # printed a Python traceback (and hung 30 s) instead of refusing by name -- the one
    # path in this file that did not.  Every other acquisition failure below is a named
    # ``Refused``; a missing helper must not be a different kind of answer simply because
    # it fails on the clock rather than on the exit code.
    try:
        proc = subprocess.run(
            [sys.executable, "-B", str(script), "--queue-dir", str(queue_dir), "status"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise Refused(
            "RECEIPT_QUERY_TIMEOUT",
            "the helper did not answer a status request within %.0f s" % timeout,
            queue=str(queue_dir)) from None
    except OSError as exc:
        raise Refused(
            "RECEIPT_QUERY_FAILED",
            "the status query could not be run at all (is %s present?)" % script,
            error="%s: %s" % (type(exc).__name__, exc)) from None
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        raise Refused("RECEIPT_QUERY_FAILED", "the helper did not answer a status request",
                      returncode=proc.returncode, stderr=(proc.stderr or "")[-800:])
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        raise Refused("RECEIPT_QUERY_UNPARSEABLE", "the helper status reply is not JSON",
                      error=str(exc)) from None


def load_receipt_file(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise Refused("RECEIPT_FILE_UNREADABLE", str(path), error=str(exc)) from None
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise Refused("RECEIPT_FILE_UNPARSEABLE", str(path), error=str(exc)) from None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _iso_z(stamp: datetime) -> str:
    """Render our own timestamps in the repo pointer's ``...Z`` house style."""
    return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(text, code: str, field: str) -> datetime:
    if not isinstance(text, str) or not text.strip():
        raise Refused(code, "%s is missing" % field, field=field)
    try:
        stamp = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        raise Refused(code, "%s is not an ISO-8601 instant: %r" % (field, text),
                      field=field) from None
    if stamp.tzinfo is None:
        raise Refused(code, "%s carries no timezone: %r" % (field, text), field=field)
    return stamp.astimezone(timezone.utc)


def read_heartbeat(queue_dir: Path, *, now: datetime) -> tuple[str, int, float]:
    """Return (raw text, pid, age seconds) from runner.heartbeat, or refuse."""
    path = queue_dir / "runner.heartbeat"
    try:
        text = path.read_text(encoding="utf-8-sig").strip()
    except OSError:
        raise Refused("HEARTBEAT_MISSING",
                      "no runner.heartbeat; the helper is not running", queueDir=str(queue_dir)) from None
    match = HEARTBEAT_RE.match(text)
    if not match:
        raise Refused("HEARTBEAT_INVALID", "runner.heartbeat is malformed", heartbeat=text)
    stamp = parse_utc(match.group(1), "HEARTBEAT_INVALID", "runner.heartbeat timestamp")
    age = (now - stamp).total_seconds()
    if not HEARTBEAT_MIN_AGE <= age <= HEARTBEAT_MAX_AGE:
        raise Refused("HEARTBEAT_STALE",
                      "runner.heartbeat is %.1fs old; that is not a live helper" % age,
                      ageSeconds=round(age, 1), heartbeat=text)
    return text, int(match.group(2)), age


def canonical_identity(record: dict) -> str:
    """sha256 over the identity fields only, so a reader can spot a hand edit."""
    fields = ("queueDir", "helperPid", "helperStartedUtc", "deadlineUtc",
              "pinsDigest", "projectRoot", "actions")
    payload = {k: record.get(k) for k in fields}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


# --------------------------------------------------------------------------- #
# The registration decision
# --------------------------------------------------------------------------- #

def build_registration(queue_dir: Path, receipt: dict, *, now: datetime | None = None) -> dict:
    """Validate a launch receipt and return the document that may be written.

    Raises :class:`Refused` for a stale, conflicting or incomplete launch.  Every
    identity value in the returned document is copied byte-for-byte from
    ``receipt`` or from the live heartbeat; nothing is inferred.
    """
    now = now or datetime.now(timezone.utc)
    queue_dir = Path(queue_dir)

    # Queue must be the project's own bridge tree -- the pointer is a project
    # document and must never name a directory outside it.
    if not queue_dir.is_dir():
        raise Refused("QUEUE_MISSING", "the queue directory does not exist", queueDir=str(queue_dir))
    if _norm(queue_dir) == _norm(QUEUE_BOUNDARY) or \
            not _norm(queue_dir).startswith(_norm(QUEUE_BOUNDARY) + os.sep):
        raise Refused("QUEUE_OUTSIDE_PROJECT",
                      "the queue must be a subdirectory of .runtime/editor-bridge",
                      queueDir=str(queue_dir))

    if not isinstance(receipt, dict):
        raise Refused("RECEIPT_NOT_AN_OBJECT", "the receipt is not a JSON object")
    if receipt.get("kind") != "status":
        raise Refused("RECEIPT_NOT_A_STATUS_REPLY",
                      "a launch receipt must be the helper's own status reply",
                      kind=receipt.get("kind"))
    if receipt.get("elevated") is not True:
        raise Refused("RECEIPT_NOT_ELEVATED", "the receipt does not prove elevation",
                      elevated=receipt.get("elevated"))

    # --- pid, bound to the live heartbeat -> a dead helper's receipt is refused
    pid = receipt.get("pid")
    if type(pid) is not int or pid <= 0:
        raise Refused("RECEIPT_HELPER_PID_INVALID", "pid must be a positive integer", pid=pid)
    heartbeat_text, heartbeat_pid, age = read_heartbeat(queue_dir, now=now)
    if heartbeat_pid != pid:
        raise Refused("HEARTBEAT_PID_CONFLICT",
                      "the live heartbeat belongs to another process",
                      receiptPid=pid, heartbeatPid=heartbeat_pid, heartbeat=heartbeat_text)

    # --- capability: schema / enabled / actions / pinsDigest / projectRoot
    capability = receipt.get("nativeScene")
    if not isinstance(capability, dict):
        raise Refused("CAPABILITY_MISSING", "nativeScene capability is absent or not an object")
    if capability.get("schema") != 1:
        raise Refused("CAPABILITY_INCOMPLETE", "nativeScene.schema must be 1",
                      schema=capability.get("schema"))
    if capability.get("enabled") is not True:
        raise Refused("CAPABILITY_INCOMPLETE", "nativeScene.enabled must be true",
                      enabled=capability.get("enabled"))
    if set(capability.get("actions") or []) != set(NATIVE_ACTIONS):
        raise Refused("CAPABILITY_INCOMPLETE", "the advertised action set is not the known set",
                      actions=capability.get("actions"))
    digest = capability.get("pinsDigest")
    if not isinstance(digest, str) or not PIN_DIGEST_RE.match(digest):
        raise Refused("CAPABILITY_INCOMPLETE", "nativeScene.pinsDigest is not a sha256 hex digest",
                      pinsDigest=digest)
    project_root = capability.get("projectRoot")
    if _norm(project_root or "") != _norm(ROOT):
        raise Refused("CAPABILITY_PROJECT_ROOT_CONFLICT",
                      "the helper serves a different project root",
                      receiptProjectRoot=project_root, expected=str(ROOT))

    # --- creation (startedUtc) and deadline, with the internal consistency the
    #     real pointer famously lacked (deadlineLocal < helperStartedUtc).
    started = parse_utc(receipt.get("startedUtc"), "RECEIPT_STARTED_INVALID", "startedUtc")
    deadline = parse_utc(receipt.get("deadlineUtc"), "RECEIPT_DEADLINE_INVALID", "deadlineUtc")
    if started > now + CLOCK_SKEW:
        raise Refused("RECEIPT_STARTED_IN_FUTURE",
                      "startedUtc is in the future; the clock or the receipt is wrong",
                      startedUtc=started.isoformat(), nowUtc=now.isoformat())
    if deadline <= now:
        raise Refused("RECEIPT_EXPIRED",
                      "the helper's own deadline has passed; a human must start a new one",
                      deadlineUtc=deadline.isoformat(), nowUtc=now.isoformat())

    lifetime = receipt.get("lifetimeMinutes")
    if type(lifetime) is not int or lifetime <= 0:
        raise Refused("RECEIPT_LIFETIME_INVALID", "lifetimeMinutes must be a positive integer",
                      lifetimeMinutes=lifetime)
    if abs((deadline - started) - timedelta(minutes=lifetime)) > timedelta(seconds=1):
        raise Refused("RECEIPT_LIFETIME_INCONSISTENT",
                      "deadlineUtc - startedUtc does not equal lifetimeMinutes",
                      startedUtc=started.isoformat(), deadlineUtc=deadline.isoformat(),
                      lifetimeMinutes=lifetime,
                      deltaMinutes=(deadline - started).total_seconds() / 60.0)

    blocked = capability.get("blocked")
    if not isinstance(blocked, bool):
        raise Refused("CAPABILITY_INCOMPLETE", "nativeScene.blocked must be a boolean", blocked=blocked)

    # Creation stamp: the helper self-reports startedUtc and no kernel creation
    # stamp, so that is what gets recorded.  If a future helper *does* carry one
    # it is copied verbatim rather than guessed.
    creation = receipt.get("processCreation")
    creation_source = "receipt.startedUtc (helper self-reported session start)"

    document = {
        "schema": POINTER_SCHEMA,
        "queueDir": str(queue_dir.resolve()),
        "helperPid": pid,
        # Copied verbatim from the receipt, not re-serialized: the helper's own
        # rendering (``...Z``) is the thing readers such as
        # build_reopen_profile.py parse, so it is preserved byte-for-byte.
        "helperStartedUtc": receipt.get("startedUtc"),
        "deadlineUtc": receipt.get("deadlineUtc"),
        "lifetimeMinutes": lifetime,
        # Derived from a *proven* launch: the heartbeat is fresh and its pid is
        # this pid, so "active" is a measurement, not a guess.
        "status": "active",
        "statusIsActivelyMeasured": True,
        "statusEvidence": {
            "measuredUtc": _iso_z(now),
            "heartbeat": heartbeat_text,
            "heartbeatAgeSeconds": round(age, 1),
            "authoritativeStatusCommand": (
                "tools/editor-bridge/elevated-request.py --queue-dir %s status" % queue_dir.resolve()),
            "authoritativeStatus": {
                "pid": pid,
                "elevated": True,
                "startedUtc": receipt.get("startedUtc"),
                "deadlineUtc": receipt.get("deadlineUtc"),
                "lifetimeMinutes": lifetime,
                "handled": receipt.get("handled"),
                "nativeScene": {
                    "schema": capability.get("schema"),
                    "enabled": capability.get("enabled"),
                    "blocked": blocked,
                    "actions": list(capability.get("actions") or []),
                    "projectRoot": project_root,
                    "pinsDigest": digest,
                    "pinCount": capability.get("pinCount"),
                },
            },
        },
        "nativeScene": {
            "schema": capability.get("schema"),
            "enabled": capability.get("enabled"),
            "blocked": blocked,
            "actions": list(capability.get("actions") or []),
            "projectRoot": project_root,
            "pinsDigest": digest,
            "pinCount": capability.get("pinCount"),
        },
        "creationSource": creation_source,
        "pinnedFilesMustNotChangeWhileThisHelperLives": True,
        "writtenBy": "tools/editor-bridge/sync-elevated-pointer.py",
        "registrationSource": "helper status receipt + runner.heartbeat; no inferred field",
        "pointerUpdatedUtc": _iso_z(now),
    }
    if isinstance(creation, int):
        document["helperProcessCreation"] = creation
    document["registrationDigest"] = canonical_identity(document)
    return document


def find_pointer_conflict(pointer: Path, new_pid: int, *, now: datetime) -> dict | None:
    """Return the existing pointer's stale-vs-live record if it names a *live*
    different helper, else None.

    "Live" is judged only from the document plus the live heartbeat of the queue
    the previous pointer names -- never by starting anything.
    """
    if not pointer.is_file():
        return None
    try:
        previous = json.loads(pointer.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None  # a corrupt pointer is not a live conflicting helper
    if not isinstance(previous, dict):
        return None
    old_pid = previous.get("helperPid")
    if type(old_pid) is not int or old_pid == new_pid:
        return None
    if previous.get("status") != "active":
        return None
    deadline = previous.get("deadlineUtc")
    try:
        expires = datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    if expires <= now:
        return None  # its own window closed; nothing to conflict with
    return {"helperPid": old_pid, "deadlineUtc": previous.get("deadlineUtc"),
            "queueDir": previous.get("queueDir")}


# --------------------------------------------------------------------------- #
# Atomic swap
# --------------------------------------------------------------------------- #

def _fsync_path(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_pointer_atomically(pointer: Path, document: dict, *, backup: bool = True,
                             now: datetime | None = None) -> dict:
    """Write ``document`` to ``pointer`` via a same-directory temp + os.replace.

    ``os.replace`` is atomic on Windows and POSIX, so a reader either sees the
    whole old document or the whole new one -- never a half-written pointer.
    """
    now = now or datetime.now(timezone.utc)
    pointer = Path(pointer)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    backup_path = None
    if backup and pointer.is_file():
        stamp = now.strftime("%Y%m%d-%H%M%S")
        backup_path = pointer.with_name("%s.before-%s.json" % (pointer.stem, stamp))
        backup_path.write_bytes(pointer.read_bytes())

    fd, tmp_name = tempfile.mkstemp(prefix=pointer.name + ".tmp-", dir=str(pointer.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, str(pointer))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    # Durability of the rename itself; best effort, never fatal.
    try:
        _fsync_path(pointer.parent)
    except OSError:
        pass
    return {"pointer": str(pointer), "backup": str(backup_path) if backup_path else None,
            "bytes": len(payload.encode("utf-8")),
            "registrationDigest": document.get("registrationDigest")}


# --------------------------------------------------------------------------- #
# verify: reader consistency
# --------------------------------------------------------------------------- #

def compare_pointer_to_receipt(pointer_doc: dict, document: dict) -> list[dict]:
    """List the identity fields on which a stored pointer disagrees with a
    freshly measured launch.  Empty list == consistent."""
    wanted = {
        "helperPid": document["helperPid"],
        "helperStartedUtc": document["helperStartedUtc"],
        "deadlineUtc": document["deadlineUtc"],
        "queueDir": document["queueDir"],
    }
    native = document["nativeScene"]
    got_native = pointer_doc.get("nativeScene") if isinstance(pointer_doc.get("nativeScene"), dict) else {}
    wanted["pinsDigest"] = native["pinsDigest"]
    got = {k: pointer_doc.get(k) for k in ("helperPid", "helperStartedUtc", "deadlineUtc", "queueDir")}
    got["pinsDigest"] = got_native.get("pinsDigest")

    problems = []
    for field, expected in wanted.items():
        actual = got.get(field)
        if actual != expected:
            problems.append({"field": field, "pointer": actual, "receipt": expected})
    # A pointer whose cached deadline is LATER than the live one over-states the
    # window; build_reopen_profile.py:149 uses it as a cutoff, so this is the one
    # divergence that can let a run outlive its authorization.
    try:
        p_deadline = datetime.fromisoformat(str(pointer_doc.get("deadlineUtc")).replace("Z", "+00:00"))
        if p_deadline.tzinfo is None:
            p_deadline = p_deadline.replace(tzinfo=timezone.utc)
        r_deadline = datetime.fromisoformat(document["deadlineUtc"])
        if p_deadline > r_deadline:
            problems.append({"field": "deadlineUtc", "severity": "over-stated",
                             "pointer": pointer_doc.get("deadlineUtc"),
                             "receipt": document["deadlineUtc"]})
    except (ValueError, TypeError):
        pass
    return problems


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _emit(obj: dict, code: int) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    print(json.dumps(obj, ensure_ascii=False, indent=1))
    return code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--queue-dir", type=Path, default=DEFAULT_QUEUE,
                       help="the helper's queue (default: .runtime/editor-bridge/elevated-queue)")
        p.add_argument("--pointer", type=Path, default=DEFAULT_POINTER,
                       help="the pointer document to write/read")
        p.add_argument("--receipt-file", type=Path, default=None,
                       help="read the launch receipt from a file instead of the helper (offline)")

    p_reg = sub.add_parser("register", help="(re)write the pointer from a fresh launch receipt")
    common(p_reg)
    p_reg.add_argument("--supersede", action="store_true",
                       help="allow replacing a pointer that names a different, still-live helper")
    p_reg.add_argument("--dry-run", action="store_true", help="validate and print, write nothing")
    p_reg.add_argument("--no-backup", action="store_true", help="do not copy the previous pointer aside")

    p_ver = sub.add_parser("verify", help="check an existing pointer against a fresh receipt")
    common(p_ver)

    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)

    try:
        receipt = (load_receipt_file(args.receipt_file) if args.receipt_file
                   else fetch_receipt(args.queue_dir))
        document = build_registration(args.queue_dir, receipt, now=now)

        if args.command == "register":
            conflict = find_pointer_conflict(args.pointer, document["helperPid"], now=now)
            if conflict and not args.supersede:
                raise Refused("POINTER_CONFLICT_LIVE_HELPER",
                              "the pointer already names a different live helper; pass --supersede to replace it",
                              existing=conflict, incoming=document["helperPid"])
            if args.dry_run:
                return _emit({"ok": True, "action": "dry-run", "wouldWrite": str(args.pointer),
                              "document": document, "conflict": conflict}, 0)
            result = write_pointer_atomically(args.pointer, document,
                                              backup=not args.no_backup, now=now)
            return _emit({"ok": True, "action": "register", **result,
                          "supersededConflict": conflict}, 0)

        # verify
        if not args.pointer.is_file():
            raise Refused("POINTER_MISSING", str(args.pointer))
        stored = json.loads(args.pointer.read_text(encoding="utf-8-sig"))
        problems = compare_pointer_to_receipt(stored, document)
        if problems:
            return _emit({"ok": False, "refused": "POINTER_DIVERGENT_FROM_RECEIPT",
                          "message": "the stored pointer disagrees with the live helper",
                          "divergences": problems}, 2)
        return _emit({"ok": True, "action": "verify", "pointer": str(args.pointer),
                      "consistent": True, "registrationDigest": document["registrationDigest"]}, 0)

    except Refused as refused:
        return _emit(refused.as_json(), 3)


if __name__ == "__main__":
    raise SystemExit(main())
