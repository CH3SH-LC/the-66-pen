"""Restricted native-side candidate for the component layer, with receipts.

WHY THIS EXISTS
---------------
The user's directive: a missing setter must be answered with a RESTRICTED CANDIDATE and a
RECEIPT implemented by this module's owner under ``tools/mondstadt/combat/native/`` -- not
with a blocked list and not with a downgraded print.  This file is that candidate.

WHAT IT REFUSES TO DO, AND WHY THAT IS THE FEATURE
--------------------------------------------------
It does NOT invent a native call and it does NOT hard-code an address.  This project's own
doctrine is explicit that a native address is a FUNCTION OF THE BUILD (the delete chain was
re-derived once already: old anchors ``0xcb64140`` / ``[comp+0x30]`` / ``[entity+0x48]`` are
VOID, and re-derivation moved the dispatcher to ``0xcba3130`` with the predicate now at
``[comp+0x34]`` and the container at ``[entity+0x68]``).  An address written into source is
therefore a claim about ONE build, and copying a voided one would be fabrication -- the exact
error class the user rejected.  So this candidate is FAIL-CLOSED on ABI: it will only emit an
executable request when a per-build anchor set has been derived and recorded.

THE ROUTE THAT NEEDS NO ATTACH PRIMITIVE AT ALL (preferred)
-----------------------------------------------------------
Attaching a component to a bare entity is NOT the only way to get components onto a monster.
The prefab component census found that monster/animal prefabs SHIP WITH THE COMPONENTS
ALREADY PRESENT: ``docs/research/reverse-eng-20261010/PREFAB-COMPONENT-DEFAULTS.md:147``
records 32 monster/animal entries as ``baseline 6 items, minus Hitbox, plus Enmity,
MonsterAiComp``.  If an entity is created FROM such a prefab/template, the components arrive
with it and no attach primitive is required.

That is why ``prefab_carried_route()`` below exists and is ranked ABOVE the attach route:
it converts the open problem from "implement a component attach ABI" into "confirm which
components the chosen template already carries", which is a READ-ONLY question.

Its honest limit is already on record in this module and must not be dropped:
``data/mondstadt/combat/template-identity.json`` -- the 2729-entry census covers the
``OfficialPrefab`` 1000xxx/10005xxx range, NOT the 3xxxxxxx creature range, and
``30002002`` itself was NEVER component-read.  So "monster templates carry Enmity +
MonsterAiComp" is a BY-FAMILY inference today, not an observation on the id we use.

ZERO GAME WRITES
----------------
Nothing here executes.  ``plan_attach`` returns verdicts; ``receipt`` returns a JSON object.
No process is injected into, no memory is written, no save is touched.  Actual creation,
binding and saving remain the leader's exclusive serial stage.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Iterable, Sequence

#: The attach kinds this project has actually PROVEN an install path for.
#: ``tools/game-executor/template-authoring/component_attachment.h:41`` --
#: ``std::int32_t kind; // Native option cards 17, bag 33 or shop 35.``
PROVEN_ATTACH_KINDS = frozenset({17, 33, 35})

#: Component kinds this module needs, resolved from the 46-member enum at
#: ``.runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs:3-51``.
NEEDED_KINDS = {
    "hitbox": 19,
    "enmity": 26,
    "nameplate": 27,
    "monster_patrol": 30,
    "drop_stuff": 37,
    "monster_ai": 42,
}


class NativeCandidateError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True)
class BuildAnchors:
    """Per-build anchors.  Nothing here may be copied from another build."""

    build_sha256: str
    derived_utc: str
    anchors: dict = field(default_factory=dict)

    def require(self, name: str) -> int:
        if name not in self.anchors:
            raise NativeCandidateError(
                "ABI_ANCHOR_NOT_DERIVED",
                f"anchor {name!r} is absent for build {self.build_sha256[:12]}; "
                "re-derive it for THIS build before any request may be issued",
            )
        return int(self.anchors[name])


@dataclass(frozen=True)
class AttachRequest:
    entity_ref: str
    kind: int
    component: str


def plan_attach(requests: Iterable[AttachRequest], anchors: BuildAnchors | None) -> list[dict]:
    """Verdict per request.  Never performs anything."""
    out: list[dict] = []
    for req in requests:
        if req.kind in PROVEN_ATTACH_KINDS:
            out.append({
                "entity": req.entity_ref,
                "component": req.component,
                "kind": req.kind,
                "verdict": "EXECUTABLE",
                "route": "proven attach primitive (EnsureComponentAttached)",
                "note": "still requires the leader's serial native window; not executed here",
            })
            continue
        out.append({
            "entity": req.entity_ref,
            "component": req.component,
            "kind": req.kind,
            "verdict": "BLOCKED",
            "code": "COMPONENT_ATTACH_KIND_NOT_IN_PROVEN_SET",
            "detail": (
                f"kind {req.kind} is not in the proven attach set "
                f"{sorted(PROVEN_ATTACH_KINDS)}; the command face has DELETE only "
                "(DeleteComponentForEditObj / ...ForPrefab) and the entity's component "
                "collection is a DERIVED MIRROR that a later load clears"
            ),
            "unblockedBy": [
                "preferred: create the entity from a template that already carries this "
                "component (see prefab_carried_route) -- read-only question, no new ABI",
                "else: derive a per-build attach anchor set and record it in BuildAnchors",
            ],
            "nativeWritePerformed": False,
        })
    return out


def prefab_carried_route(template_id: int, template_components: Sequence[int] | None) -> dict:
    """Preferred route: components that arrive WITH the template.

    ``template_components`` is what a READ-BACK observed for that exact template id.  It is
    deliberately not defaulted from the by-family census -- see the module docstring.
    """
    if template_components is None:
        return {
            "templateId": template_id,
            "route": "prefab-carried",
            "verdict": "NEEDS_READBACK",
            "code": "TEMPLATE_COMPONENTS_NEVER_READ",
            "whatToRead": (
                "the component set actually carried by this exact template id. The 2729-entry "
                "census covers OfficialPrefab 1000xxx/10005xxx, NOT the 3xxxxxxx creature "
                "range, and this id was never component-read -- so any statement about it "
                "today would be by-family inference, not observation"
            ),
            "knownCensusAnchor": "docs/research/reverse-eng-20261010/PREFAB-COMPONENT-DEFAULTS.md:147",
            "nativeWritePerformed": False,
        }
    have = set(int(k) for k in template_components)
    wanted = set(NEEDED_KINDS.values())
    return {
        "templateId": template_id,
        "route": "prefab-carried",
        "verdict": "SATISFIED" if wanted <= have else "PARTIAL",
        "alreadyCarried": sorted(have),
        "stillMissing": sorted(wanted - have),
        "nativeWritePerformed": False,
    }


def receipt(mission: str, build: str, verdicts: Sequence[dict], writes: int = 0) -> str:
    """A receipt suitable for handing to the leader.  It states plainly that nothing ran."""
    return json.dumps(
        {
            "receiptVersion": 1,
            "module": "combat-encounters",
            "mission": mission,
            "build": build,
            "nativeWritePerformed": writes > 0,
            "writesAttempted": writes,
            "executedNothing": writes == 0,
            "verdicts": list(verdicts),
            "whyNoWrites": (
                "rework period: zero game writes. Creation, binding and saving are the "
                "leader's exclusive serial stage; this candidate only classifies."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


def _kind_names() -> dict:
    """kind number -> enum member name, from the 46-member enum.  ONLY kinds this module
    actually resolved are named; anything else stays unnamed rather than guessed."""
    return {
        17: "Tab", 18: "Combat", 19: "Hitbox", 26: "Enmity", 27: "Nameplate",
        30: "MonsterPatrol", 33: "StuffBag", 35: "Shop", 37: "DropStuff", 42: "MonsterAiComp",
    }


def names_or_kind(kind: int) -> str:
    return _kind_names().get(kind) or f"kind-{kind}"


def observe_record_kinds(source_file) -> dict:
    """Observe the repeated-record kinds DIRECTLY from a shared-source decoded prefab.

    This reads the wire tree itself rather than trusting any summary, so the result is
    independently re-derivable by a reviewer from the same file.

    Observed shape (see data/mondstadt/combat/prefab-components.json for the full record):
      fields[] -> root1 (varint) = registryId; root2 (submessage) holds
      root2.1 (varint), then two repeated groups root2.2 and root2.3 whose rows carry
      field1 = a small integer, plus root2.25.

    Returns the registryId, both groups' field1 values, and the file's own sha256 so the
    observation is pinned to bytes.
    """
    import hashlib
    import json as _json
    from pathlib import Path

    raw = Path(source_file).read_bytes()
    doc = _json.loads(raw.decode("utf-8"))

    def sub(fields, num):
        return [x for x in fields if x.get("f") == num]

    def var(fields, num):
        s = sub(fields, num)
        return s[0].get("v") if s and "v" in s[0] else None

    fields = doc.get("fields") or []
    root1 = var(fields, 1)
    g22: list = []
    g23: list = []
    g25: list = []
    for node in sub(fields, 2):
        m = node.get("m") or []
        for grp, sink in ((2, g22), (3, g23), (25, g25)):
            for row in sub(m, grp):
                rm = row.get("m") or []
                k = var(rm, 1)
                if isinstance(k, int):
                    sink.append(k)
    return {
        "file": Path(source_file).name,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "registryId": root1,
        "groupRoot2_2": sorted(g22),
        "groupRoot2_3": sorted(g23),
        "groupRoot2_25Count": len(g25),
    }


def component_verify_receipt(expect_path: str, checked_file: str | None = None,
                            shared_dir: str | None = None) -> dict:
    """READ-BACK VERIFY step, in the leader's fixed receipt shape (world contract v26).

    ``shared_dir`` points at the shared-source decoded prefabs.  When it is given, the
    observed kinds are read FROM THOSE FILES, not from this module's summary, and each
    observation is pinned by the file's own sha256 -- that is what makes the receipt
    independently re-derivable.  Without it the function falls back to the summary and says
    so in ``sourceOfObservations``.

    status MUST stay UNCONFIRMED until the path semantics are settled, so present/absent are
    reported as OBSERVED RECORD KINDS and never as a proven component inventory.
    Writes no game bytes.
    """
    import json as _json
    from pathlib import Path

    p = Path(expect_path)
    doc = _json.loads(p.read_text(encoding="utf-8"))
    names = _kind_names()

    observed: set = set()
    per_template: list = []
    obs_errors: list = []
    source_of_observations = "SUMMARY_IN_THIS_MODULE"

    for t in doc.get("perTemplate", []):
        rid = t.get("registryId")
        if shared_dir:
            fname = t.get("prefabFile")
            cand = Path(shared_dir) / f"{fname}.json"
            if not cand.exists():
                cand = Path(shared_dir) / str(fname)
            try:
                obs = observe_record_kinds(cand)
                kinds = sorted(set(obs["groupRoot2_2"]) | set(obs["groupRoot2_3"]))
                per_template.append({
                    "registryId": rid,
                    "observedRecordKinds": kinds,
                    "fromFile": obs["file"],
                    "sourceSha256": obs["source_sha256"],
                    "groupRoot2_2": obs["groupRoot2_2"],
                    "groupRoot2_3": obs["groupRoot2_3"],
                })
                observed.update(kinds)
                source_of_observations = "SHARED_SOURCE_FILES"
                continue
            except (OSError, ValueError) as exc:
                obs_errors.append({"registryId": rid, "file": str(cand),
                                   "error": f"{type(exc).__name__}"})
        kinds = sorted(set(int(k) for k in t.get("baselineRecordKinds", []))
                       | set(int(k) for k in t.get("extraRecordKinds", [])))
        per_template.append({"registryId": rid, "observedRecordKinds": kinds,
                             "fromFile": "SUMMARY (not the shared source)"})
        observed.update(kinds)

    wanted = sorted(set(NEEDED_KINDS.values()))
    present = [{"kind": k, "name": names.get(k)} for k in wanted if k in observed]
    absent = [{"kind": k, "name": names.get(k)} for k in wanted if k not in observed]

    return {
        "ok": False,
        "step": "component-verify",
        "sourceOfObservations": source_of_observations,
        "observationErrors": obs_errors,
        "checkedFile": str(checked_file or p),
        "contractVersion": 26,
        "present": present,
        "absent": absent,
        "status": "UNCONFIRMED",
        "blockedReason": (
            "Path semantics are NOT settled: it is unproven that the repeated records inside "
            "field 2 are the entity component table, so present/absent are OBSERVED RECORD "
            "KINDS, not a component inventory. Two further reasons: (1) the group is not one "
            "uniform schema across files -- 20002108 reports {3,6,14,1,19,18} where this "
            "module's four files report {1,3,6,14,18,26}; (2) the config-field arithmetic is "
            "NOT a rule -- 10007002 kind=36 carries its config at field 47, not 46, so kind+10 "
            "is REFUTED as a general rule even though it held for every row in these four files."
        ),
        "writesGameBytes": False,
        "observedRecordKindsUnion": sorted(observed),
        "observedKindsWithNoNameInThisModule": sorted(k for k in observed if k not in names),
        "perTemplate": per_template,
        "confidence": (
            "Reading these rows as component records rests on three independent facts (the "
            "6-row group matching the censused baseline count; a kind-slotted payload field; "
            "field1 values equal to component-kind numbers). It remains an INTERPRETATION of a "
            "wire schema, which is why status stays UNCONFIRMED."
        ),
        "notClaimed": [
            "No component was attached, installed or configured.",
            "No game byte was written.",
            "Kinds with no resolved name are reported as null and never guessed.",
        ],
    }


def main(argv=None) -> int:
    """Fixed entry point for the leader's runner: a component READ-BACK VERIFY step.

    --expect <prefab-components.json> [--emit-receipt <path>] [--print-attach-plan]
    The receipt always goes to stdout.  --emit-receipt additionally writes a file where the
    caller's permissions allow it; this module's own workspace denies shell writes, so in
    practice the runner lands it.
    """
    import argparse

    ap = argparse.ArgumentParser(
        description="component read-back verify step (writes no game bytes)")
    ap.add_argument("--expect", required=True, help="path to prefab-components.json")
    ap.add_argument("--shared-dir", default=None,
                    help="shared-source decoded prefabs; observations are then read FROM these "
                         "files (preferred) instead of from this module's summary")
    ap.add_argument("--emit-receipt", default=None, help="path to write the receipt JSON")
    ap.add_argument("--print-attach-plan", action="store_true",
                    help="also print the attach classification for the needed kinds")
    args = ap.parse_args(argv)

    rec = component_verify_receipt(args.expect, shared_dir=args.shared_dir)
    text = json.dumps(rec, ensure_ascii=False, indent=2)
    print(text)

    if args.print_attach_plan:
        reqs = [AttachRequest("<entity>", k, names_or_kind(k))
                for k in sorted(set(NEEDED_KINDS.values()))]
        print(json.dumps(plan_attach(reqs, None), ensure_ascii=False, indent=2))

    if args.emit_receipt:
        from pathlib import Path
        try:
            Path(args.emit_receipt).write_text(text, encoding="utf-8")
            print(f"[emit-receipt] wrote {args.emit_receipt}", file=sys.stderr)
        except OSError as exc:
            print(
                f"[emit-receipt] NOT WRITTEN ({type(exc).__name__}); receipt is on stdout "
                "and the runner must land it",
                file=sys.stderr,
            )
    return 0 if rec["ok"] else 1


if __name__ == "__main__":  # pragma: no cover - manual smoke only
    raise SystemExit(main())
