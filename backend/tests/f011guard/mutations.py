"""The mutation matrix: does every secure-expectation probe have discriminating power?

For each mutation we re-load the PRODUCTION module from a mutated copy of its own source
text (never the file on disk) and re-run the probe set.  A probe that was True at baseline
and False under the mutation is "mutation-proved".  A probe that stays True is either
redundantly protected (guard duplicated elsewhere) or the probe is toothless -- both are
reported rather than hidden.

Run:  .runtime/mcp-venv/Scripts/python.exe -B mutations.py
"""
from __future__ import annotations

import json
import sys

import harness as H
import probes as P

LEG_TEXT_MUTATIONS = [
    ("LEG-B-drop-baseline-difference", "if entity_id not in added:", "if False:",
     ["b-pre-baseline-member-refused"]),
    ("LEG-F-drop-receipt-provenance", 'if not info.get("sha256Verified"):', "if False:",
     ["f-receipt-tampered-refused"]),
    # 2026-10-06: this anchor was "if entity_id in PROTECTED_UNATTRIBUTABLE_IDS:" -- text that
    # no longer exists anywhere in the module. The guard was rewritten to test a UNION set
    # (``protected``) so that a caller can only ever TIGHTEN protection, and the matrix anchor
    # was never carried across with it. The effect was not "this mutation is weak": it was that
    # ``python mutations.py`` aborted on MUTATION_ANCHOR_MISSING before running ANY mutation,
    # so the whole matrix had silently stopped running. Re-anchored on the real refusal
    # (cleanup_ownership_legs.py:1016). The same test also appears at :1034, but that one only
    # labels a reported sub-state and is not the guard, so this anchor carries the following
    # ``refuse(...)`` line to stay unambiguous under replace(..., 1).
    ("LEG-G-drop-frozen-ids",
     '        if entity_id in protected:\n            refuse("CLEANUP_TARGET_UNATTRIBUTABLE",',
     '        if False:\n            refuse("CLEANUP_TARGET_UNATTRIBUTABLE",',
     ["a-frozen-id-with-full-receipt-refused"]),
    ("LEG-D-drop-truncation",
     "if fresh.entityCount is None or fresh.entityCount != len(fresh.entries):", "if False:",
     ["d-readback-truncated-refused"]),
    ("LEG-D-drop-acceptance", "if not fresh.accepted:", "if False:",
     ["d-readback-unaccepted-refused"]),
    ("LEG-D-drop-completeness", "if not fresh.complete:", "if False:",
     ["d-readback-incomplete-refused"]),
    ("LEG-C-drop-level-comparison", "if claim.level_id != level_id:", "if False:",
     ["f-cross-level-refused", "f-cross-level-dual-id-refused"]),
    ("LEG-E-drop-round-window", "if not window.contains(created):", "if False:",
     ["e-receipt-outside-window-refused"]),
    ("LEG-A-drop-create-declaration", 'if body_action != "create":', "if False:",
     ["a-receipt-not-a-create-refused"]),
]

SERVER_TEXT_MUTATIONS = [
    ("ROUTE-drop-per-id-unowned-guard", "unowned = sorted(set(entityIds) - allowed)",
     "unowned = []",
     ["a-route-frozen-no-dispatch", "route-unowned-no-dispatch",
      "route-run-refused-no-dispatch"]),
    ("ROUTE-drop-run-level-status-guard", "if legs.get('status') != 'judged':", "if False:",
     ["route-run-refused-no-dispatch"]),
    ("ROUTE-restore-B10-discarded-run-check", "if runId not in known_runs:", "if False:",
     ["e-route-unknown-bridge-no-dispatch", "e-route-shape-invalid-run-id-no-dispatch"]),
    ("ROUTE-drop-run-id-emptiness-check", "if not isinstance(runId, str) or not runId:",
     "if False:", ["e-route-shape-invalid-run-id-no-dispatch"]),
    ("ROUTE-drop-materials-existence-check", "if not materials_path.is_file():", "if False:",
     ["route-no-materials-no-dispatch"]),
    ("ROUTE-drop-legs-loadability-check", "if _CLEANUP_LEGS is None:", "if False:",
     []),
    # Added 2026-10-06 with the check itself. The route judged the round's materials but
    # never compared their level to the handle's, so ownership evidence written on one
    # level could authorise a delete on another -- and entity ids ARE reused across levels
    # (the legs matrix's own LEG-C mutation names the dual-level id 1077936135). Neutralise
    # the new binding and the probe must go False, i.e. the cross-level call dispatches.
    # Added 2026-10-06 with the check itself (R211). The entry handed the manifest straight
    # to the legs, which resolve a material path with `path if path.is_absolute() else
    # (ROOT / path)` and contain it nowhere -- so a materials document could name any
    # readable file as "what existed before" / "what is present now". Neutralise the guard
    # and the probe must go False, i.e. the out-of-runtime path is accepted.
    # Added 2026-10-06 with the check itself (R212). The re-entry guard is scoped to one
    # (roundId, requestId); a different id set is a different request by design, so without
    # a CROSS-REQUEST overlap check an id whose dispatch was attempted and never resolved
    # can be re-cited in a smaller batch and sent to the native delete twice. Neutralise it
    # and the probe must go False.
    # Added 2026-10-06 with the check itself (R213). The round selector was the one argument
    # the route never validated -- it went straight into `_cleanup_round_id`, which hashes
    # whatever it is handed. Neutralise the guard and the probe must go False.
    ("ROUTE-drop-round-selector-validation",
     "        if (not isinstance(createdByRequestIds, list) or not createdByRequestIds",
     "        if False and (not isinstance(createdByRequestIds, list) or not createdByRequestIds",
     ["route-round-selector-unvalidated-no-dispatch"]),
    ("ROUTE-drop-cross-request-unknown-outcome",
     "        if _unknown_overlap:", "        if False:",
     ["route-overlapping-unknown-outcome-no-dispatch"]),
    ("ROUTE-drop-material-path-containment",
     "        if escaped_material_paths:", "        if False:",
     ["route-material-path-outside-runtime-no-dispatch"]),
    ("ROUTE-drop-materials-level-binding",
     "        materials_level = manifest.get('levelId')\n"
     "        if materials_level is not None and materials_level != level['levelId']:",
     "        materials_level = manifest.get('levelId')\n"
     "        if False:",
     ["route-materials-wrong-level-no-dispatch"]),
]


def _patch_pre_baseline_rubber_stamp(legs):
    """PATCH mutation: the baseline leg accepts anything (returns an empty id set)."""
    legs.load_pre_baseline = lambda spec: (set(), [])
    return legs


def _patch_no_legs(server):
    """PATCH mutation: the ownership module never loads -> the route runs without legs."""
    server._CLEANUP_LEGS = type("RubberStamp", (), {
        "judge": staticmethod(lambda manifest: {
            "status": "judged", "legVersion": "1", "ownedIds": list(manifest["candidates"]),
            "perId": {}, "difference": None, "readback": None})})()
    return server


def _baseline_probe_results():
    legs = H.load_legs()
    leg_results = P.run(P.LEG_PROBES, lambda: legs)
    server = H.load_server(legs=legs)
    route_results = P.run(P.ROUTE_PROBES, lambda: server)
    return legs, leg_results, route_results


def main():
    legs, leg_baseline, route_baseline = _baseline_probe_results()

    report = {
        "baseline": {"legs": leg_baseline, "route": route_baseline},
        "mutations": [],
        "units": {"legsModule": str(H.LEGS_PATH), "serverModule": str(H.SERVER_PATH),
                  "legsSha256": H.sha256_file(H.LEGS_PATH),
                  "serverSha256": H.sha256_file(H.SERVER_PATH)},
    }

    for name, old, new, expected in LEG_TEXT_MUTATIONS:
        mutated = H.load_legs(rename=(old, new))
        observed = P.run(P.LEG_PROBES, lambda: mutated)
        flipped = sorted(k for k, v in observed.items()
                         if leg_baseline.get(k) is True and v is not True)
        report["mutations"].append({
            "id": name, "module": "backend/cleanup_ownership_legs.py", "kind": "text",
            "anchor": old, "replacement": new, "expectedFlips": expected,
            "flipped": flipped, "held": [k for k, v in observed.items() if v is True],
            "verdict": ("TURNS_RED" if flipped else "NO_EFFECT")})

    # PATCH mutation on the legs module
    mutated = _patch_pre_baseline_rubber_stamp(H.load_legs())
    observed = P.run(P.LEG_PROBES, lambda: mutated)
    flipped = sorted(k for k, v in observed.items()
                     if leg_baseline.get(k) is True and v is not True)
    report["mutations"].append({
        "id": "LEG-B-rubber-stamp-baseline", "module": "backend/cleanup_ownership_legs.py",
        "kind": "patch", "anchor": "legs.load_pre_baseline := lambda spec: (set(), [])",
        "replacement": "n/a",
        "expectedFlips": ["c-pre-baseline-absent-refused",
                          "c-pre-baseline-missing-file-refused"],
        "flipped": flipped, "held": [k for k, v in observed.items() if v is True],
        "verdict": ("TURNS_RED" if flipped else "NO_EFFECT")})

    for name, old, new, expected in SERVER_TEXT_MUTATIONS:
        mutated = H.load_server(rename=(old, new), legs=legs)
        observed = P.run(P.ROUTE_PROBES, lambda: mutated)
        flipped = sorted(k for k, v in observed.items()
                         if route_baseline.get(k) is True and v is not True)
        report["mutations"].append({
            "id": name, "module": "backend/entity_server.py", "kind": "text",
            "anchor": old, "replacement": new, "expectedFlips": expected,
            "flipped": flipped,
            "observed": observed,
            "verdict": ("TURNS_RED" if flipped else "NO_EFFECT")})

    mutated = _patch_no_legs(H.load_server(legs=H.load_legs()))
    observed = P.run(P.ROUTE_PROBES, lambda: mutated)
    flipped = sorted(k for k, v in observed.items()
                     if route_baseline.get(k) is True and v is not True)
    report["mutations"].append({
        "id": "ROUTE-rubber-stamp-ownership-module", "module": "backend/entity_server.py",
        "kind": "patch",
        "anchor": "server._CLEANUP_LEGS := module whose judge() owns every candidate",
        "replacement": "n/a",
        "expectedFlips": ["a-route-frozen-no-dispatch", "route-unowned-no-dispatch"],
        "flipped": flipped, "observed": observed,
        "verdict": ("TURNS_RED" if flipped else "NO_EFFECT")})

    print(json.dumps(report, ensure_ascii=False, indent=1))
    H.write_json(H.HERE / "mutations.json", report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
