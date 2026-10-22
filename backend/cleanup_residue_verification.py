#!/usr/bin/env python3
"""D04.03.03 -- confirm, from evidence, that a cleanup left no residue.

WHY THIS FILE EXISTS
--------------------
The leaf is: *delete this round's own test copies, then save + reopen and confirm
no residue*.  In the tree today the two halves live in two places and are NOT
composed into one verdict:

  * the delete side is wired and guarded -- ``backend/entity_server.py``
    ``mw_scene_cleanup_owned`` proves ownership with legs A..G from
    ``backend/cleanup_ownership_legs.py`` before it dispatches anything, so only
    THIS round's proven-own entities can be deleted and an unauthorized id is
    refused by name (``CLEANUP_ID_NOT_OWNED_BY_THIS_RUN`` /
    ``CLEANUP_TARGET_UNATTRIBUTABLE``);

  * the "no residue" side is NOT wired.  The cleanup route hard-pins
    ``liveReadback=_stage('not-run', reason='run a read-back after the cleanup')``
    and ``persistence``/``reopen`` to ``not-run``.  No route compares *which ids the
    cleanup claimed it removed* against *what a later read-back actually shows*.

This module is that missing comparison, and nothing else.  It is a PURE function
library: it opens no socket, starts no process, sends no queue or native request,
and never deletes.  ``dispatchPerformed`` / ``deletionPerformed`` /
``reopenPerformed`` are pinned ``False`` in every report.  The read-back it consumes
must already have been produced by an independent native read (the same read-back the
read-back leg of the ownership guardrail consumes); this module merely judges it.

WHY WIRING IT INTO ``mw_scene_cleanup_residue`` IS NOT A SECOND COPY
-------------------------------------------------------------------
``backend/entity_server.py`` ``mw_scene_cleanup_residue`` is the caller.  It derives
the round's removed ids from the SAME per-request journal the delete route writes
(never from the model), derives the must-survive set from the round's own pre-create
baseline (never from the model), runs ONE read-only native inspection, and folds the
result through :func:`verify_cleanup_residue`.  The read-back reader it must agree
with is the ownership legs' own ``load_fresh_readback``; this module loads the legs
module (or is handed the instance the caller already loaded) rather than writing a
second, looser reader -- a second definition of "usable read-back" would be a hole in
the guardrail.

WHAT IT REFUSES TO DO
---------------------
  * It never reports ``pass`` without a USABLE read-back.  An absent, incomplete,
    truncated, wrong-level or timestamp-less read-back is ``blocked`` -- with the
    present-set unknown, "no residue" is not a conclusion that can be drawn.
  * It never treats "I could not read the read-back" as "the ids are gone".  That is
    the exact silent-pass this leaf exists to prevent.
  * It never lets an unauthorized object's disappearance pass: if an id that was NOT
    the cleanup's own is missing from the read-back, that is a ``fail``
    (``unauthorized-object-missing``), not a clean cleanup.
  * It refuses when the caller's own preflight already knows the round cannot be
    judged (``preflightRefusals``) -- e.g. a claimed delete whose outcome was never
    recorded.  An unobserved dispatch is never a "no residue" claim.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

MODULE_VERSION = 1

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_BLOCKED = "blocked"


def find_repo_root(start: Path | None = None) -> Path:
    """The repo root, found by the sibling module it reuses (merge-location proof).

    Works whether this file sits in ``<repo>/backend/`` after a merge or in a worker
    directory before one, so the same source can be dropped in without editing.
    """
    here = Path(start or __file__).resolve()
    for candidate in [here.parent, *here.parents]:
        if (candidate / "backend/cleanup_ownership_legs.py").is_file():
            return candidate
    raise RuntimeError("REPO_ROOT_NOT_FOUND from %s" % here)


REPO_ROOT = find_repo_root()

#: The legs module, loaded on first use (or supplied by the caller).  The caller that
#: already holds the production instance (``entity_server``) passes it in, so the two
#: never disagree about what "a complete read-back" means and the module is not
#: executed a second time.
_LEGS = None


def _load_module_by_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("MODULE_UNLOADABLE: %s" % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


def _load_legs():
    path = REPO_ROOT / "backend/cleanup_ownership_legs.py"
    if not path.is_file():
        raise RuntimeError("CLEANUP_LEGS_MODULE_MISSING: %s" % path)
    return _load_module_by_path("_d040303_cleanup_ownership_legs", path)


def _legs(legs=None):
    """The ownership-legs module, injected or lazily loaded.

    Import failure is fatal on purpose: a residue verdict that cannot share the
    ownership legs' definition of a "usable read-back" must not be able to publish one.
    """
    global _LEGS
    if legs is not None:
        return legs
    if _LEGS is None:
        _LEGS = _load_legs()
    return _LEGS


def _as_id_set(values, label, co):
    """(ids set, refusals) -- strict uint32, never a coerced/guessed id."""
    out = set()
    refusals = []
    for value in values or []:
        parsed = co.as_uint(value)
        if parsed is None:
            refusals.append(co.Refusal("ID_NOT_UINT32",
                                       "%r is not a nonzero uint32 id (%s)" % (value, label)))
            continue
        out.add(parsed)
    return out, refusals


def _after_from_inline(manifest, co):
    """A declared inline after-readback: {'ids': [...], 'complete': true, 'levelId': N}.

    Inline form is accepted only as a convenience for offline fixtures; the product
    path supplies a document path so the bytes can be hashed and bound.
    """
    spec = manifest.get("afterReadback") or {}
    ids, refusals = _as_id_set(spec.get("ids"), "afterReadback.ids", co)
    return ids, refusals, spec


def _blocked(report, reason, refusals):
    report["status"] = STATUS_BLOCKED
    report["reason"] = reason
    report["refusals"] = refusals
    return report


def verify_cleanup_residue(manifest, *, legs=None) -> dict:
    """Judge one cleanup's residue from a later read-back.  Never dispatches.

    Manifest keys:
      levelId            int          the level the cleanup ran in
      removedOwnedIds    [int]        the ids the ownership legs granted + the delete sent
      unauthorizedIds    [int]        ids that were NOT the cleanup's own and must survive
      preflightRefusals  [{code,message}] the caller's already-known blockers (e.g. a
                                      claimed delete whose outcome was never recorded);
                                      a non-empty list BLOCKS the verdict -- an
                                      unobserved dispatch is never "no residue"
      afterReadback      {path | ids, readAtUtc?, levelId?, complete?, entityCount?, sha256?}
                                     the read-back taken AFTER the delete (and, in the
                                     full loop, after save + reopen)

    ``legs`` is the ownership-legs module; the production caller passes the instance it
    already loaded so both share one definition of a usable read-back.
    """
    legs = _legs(legs)
    co = legs.co
    refusals = []
    report = {
        "tool": "cleanup_residue_verification",
        "schemaVersion": MODULE_VERSION,
        "levelId": co.as_uint(manifest.get("levelId")),
        "status": STATUS_BLOCKED,
        "reason": None,
        "removedOwnedIds": [],
        "residualRemovedIds": [],
        "unauthorizedIds": [],
        "missingUnauthorizedIds": [],
        "afterEntityCount": None,
        "evidence": {},
        "refusals": [],
        "dispatchPerformed": False,
        "deletionPerformed": False,
        "reopenPerformed": False,
        "note": "read-only residue verdict; this module cannot reach a delete, save or reopen route",
    }

    level_id = report["levelId"]
    if level_id is None:
        report["reason"] = "manifest.levelId must be a nonzero uint32"
        return report

    removed, removed_refusals = _as_id_set(manifest.get("removedOwnedIds"), "removedOwnedIds", co)
    unauthorized, unauth_refusals = _as_id_set(manifest.get("unauthorizedIds"), "unauthorizedIds", co)
    refusals.extend(removed_refusals)
    refusals.extend(unauth_refusals)
    report["removedOwnedIds"] = sorted(removed)
    report["unauthorizedIds"] = sorted(unauthorized)

    # The caller's preflight blockers: a claimed-but-unrecorded delete, an unavailable
    # pre-create baseline, ... With the removed set or the survive set unknown, no
    # residue conclusion may be published.
    preflight = list(manifest.get("preflightRefusals") or [])
    if preflight:
        return _blocked(report,
                        "the round's own materials do not permit a residue verdict: %s"
                        % ",".join(str(row.get("code")) for row in preflight),
                        [dict(row) for row in preflight])

    # An empty removed set confirms nothing: consistent with the ownership legs'
    # "an empty candidate list is not 'everything is owned'".
    if not removed:
        report["reason"] = ("removedOwnedIds is empty: there is no removal whose residue this "
                            "read-back could confirm, so 'no residue' is vacuous and refused")
        report["refusals"] = [r.as_json() for r in refusals] + [
            co.Refusal("NOTHING_REMOVED", report["reason"]).as_json()]
        return report

    spec = manifest.get("afterReadback") or {}
    after_ids = None
    if "path" in spec and spec.get("path"):
        readback, rb_refusals = legs.load_fresh_readback(
            legs._resolve(spec["path"]),
            read_at_utc=spec.get("readAtUtc"),
            level_id=co.as_uint(spec.get("levelId")),
            complete=spec.get("complete"),
            entity_count=co.as_uint(spec.get("entityCount")),
            sha256=spec.get("sha256"))
        if readback is None:
            refusals.extend(rb_refusals)
            return _blocked(report, "the after-readback is unavailable or unusable",
                            [r.as_json() for r in refusals])
        after_ids = readback.ids()
        report["afterEntityCount"] = len(after_ids)
        report["evidence"] = {"readbackPath": str(readback.path), "readbackSha256": readback.sha256,
                              "readAtUtc": readback.readAtUtc, "levelId": readback.levelId}
        if not readback.accepted:
            refusals.append(co.Refusal("READBACK_NOT_ACCEPTED",
                                       "the read-back's own acceptance record refused it (%s)"
                                       % readback.acceptance))
        if not readback.complete:
            refusals.append(co.Refusal("READBACK_INCOMPLETE",
                                       "the read-back cannot show it captured every entity"))
        if readback.levelId is None:
            refusals.append(co.Refusal("READBACK_LEVEL_UNKNOWN",
                                       "the read-back does not state which level it observed"))
        elif readback.levelId != level_id:
            refusals.append(co.Refusal("READBACK_LEVEL_MISMATCH",
                                       "the read-back observed level %s, the cleanup was level %s"
                                       % (readback.levelId, level_id)))
        if readback.entityCount is not None and readback.entityCount != len(readback.entries):
            refusals.append(co.Refusal("READBACK_TRUNCATED",
                                       "the read-back claims %s entities but carries %d"
                                       % (readback.entityCount, len(readback.entries))))
    else:
        after_ids, inline_refusals, spec = _after_from_inline(manifest, co)
        refusals.extend(inline_refusals)
        report["afterEntityCount"] = len(after_ids)
        report["evidence"] = {"inlineIds": sorted(after_ids),
                              "readAtUtc": spec.get("readAtUtc"), "levelId": spec.get("levelId")}
        if spec.get("complete") is not True:
            refusals.append(co.Refusal("READBACK_INCOMPLETE",
                                       "an inline after-readback must declare complete=true"))
        if co.as_uint(spec.get("levelId")) != level_id:
            refusals.append(co.Refusal("READBACK_LEVEL_MISMATCH",
                                       "the inline read-back names level %r, the cleanup was level %s"
                                       % (spec.get("levelId"), level_id)))

    if refusals:
        # With the present-set unknown or the evidence unusable, nothing can be concluded.
        return _blocked(report,
                        "the after-readback is not usable: %s" % ",".join(
                            dict.fromkeys(r.code for r in refusals)),
                        [r.as_json() for r in refusals])

    residual = sorted(removed & after_ids)
    missing = sorted(unauthorized - after_ids)
    report["residualRemovedIds"] = residual
    report["missingUnauthorizedIds"] = missing
    report["refusals"] = []

    if residual:
        report["status"] = STATUS_FAIL
        report["reason"] = "residue: removed ids still present in the read-back: %s" % residual
    elif missing:
        report["status"] = STATUS_FAIL
        report["reason"] = ("an unauthorized object disappeared: ids not removed by this cleanup "
                            "are absent from the read-back: %s" % missing)
    else:
        report["status"] = STATUS_PASS
        report["reason"] = ("every removed id is absent and every unauthorized id is present in "
                            "the read-back")
    return report


def cli(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Confirm a cleanup left no residue.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dump", action="store_true")
    args = parser.parse_args(argv)
    document = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    report = verify_cleanup_residue(document)
    print(json.dumps(report if args.dump else
                     {k: report[k] for k in ("status", "reason", "residualRemovedIds",
                                             "missingUnauthorizedIds", "dispatchPerformed")},
                     ensure_ascii=False, indent=1))
    return 0 if report["status"] == STATUS_PASS else 1


if __name__ == "__main__":
    raise SystemExit(cli())
