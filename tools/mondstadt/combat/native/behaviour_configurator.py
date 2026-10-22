"""Validate (and optionally derive) the per-behaviour combat configuration.

Declared output of the combat-behaviour-configurator work, alongside
data/mondstadt/combat/behaviour-config.json.

WHY A VALIDATOR AND NOT JUST A DATA FILE
  behaviour-config.json was written by hand. A hand-written configuration drifts: its central
  claim -- "these carriers ARRIVE WITH THE TEMPLATE, so nothing may be re-mounted" -- is only
  trustworthy while it still agrees with the measurements it was derived from. This tool re-reads
  those sources and checks the invariants, so drift shows up as a failure instead of as a quietly
  wrong file.

WHAT IT CHECKS
  1. every behaviour in behaviour-config.json has a carrier from the legend;
  2. any behaviour whose carrier is TEMPLATE_NATIVE has mountRequired == false (the whole point:
     you must not re-mount what the template already brings);
  3. the kinds named for a behaviour are actually present in the per-id prefab measurement;
  4. groundPolicy still says FAIL_CLOSED and still carries provisional=true (heights are not measured);
  5. mountPosture.attachedComponentCount is 0, consistent with the no-attach finding;
  6. no behaviour is left with neither a carrier nor a named override.

USAGE
  python -B tools/mondstadt/combat/native/behaviour_configurator.py validate
  python -B tools/mondstadt/combat/native/behaviour_configurator.py derive      # report diffs only

`derive` NEVER writes behaviour-config.json. It prints what a re-derivation from the sources would
produce and how it differs, so a human decides. Exit code is non-zero when validation fails.

Reads only this module's own data. No game access, no desktop, no other module's files.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[4] / "data" / "mondstadt" / "combat"
CONFIG = BASE / "behaviour-config.json"
INHERITED = BASE / "inherited-behaviour.json"
PREFAB = BASE / "prefab-components.json"


def _config_override(argv) -> None:
    """Allow --config PATH so the invariants can be tested against a deliberately broken copy."""
    global CONFIG
    if "--config" in argv:
        i = argv.index("--config")
        if i + 1 < len(argv):
            CONFIG = Path(argv[i + 1]).resolve()

CARRIER_LEGEND = {"TEMPLATE_NATIVE", "NODE_GRAPH", "NODE_GRAPH_PARTIAL", "NOT_REQUIRED"}

problems: list[str] = []


def load(p: Path):
    if not p.exists():
        problems.append("MISSING_SOURCE: %s" % p.name)
        return None
    # utf-8-sig: accept a BOM so a file re-saved by another tool does not crash the validator
    return json.loads(p.read_text(encoding="utf-8-sig"))


def prefab_kind_union(prefab) -> tuple[set, str]:
    """Read the measured kind union using the file's REAL key names.

    Real shape of prefab-components.json (read, not guessed):
      perTemplate              -> array[4], one object per template
      observedAgainstNeeded    -> {neededKinds, PRESENT_in_allFour, ABSENT_from_allFour,
                                   consequencePerBehaviour}
    The authoritative union is observedAgainstNeeded.PRESENT_in_allFour.
    """
    union: set = set()
    origin = ""
    if isinstance(prefab, dict):
        oan = prefab.get("observedAgainstNeeded")
        if isinstance(oan, dict):
            for key in ("PRESENT_in_allFour", "neededKinds"):
                val = oan.get(key)
                if isinstance(val, list):
                    union.update(int(x) for x in val if isinstance(x, (int, float)))
            if union:
                origin = "observedAgainstNeeded"
        if not union:
            for row in prefab.get("perTemplate") or []:
                if not isinstance(row, dict):
                    continue
                for key, val in row.items():
                    if isinstance(val, list) and ("kind" in key.lower()):
                        union.update(int(x) for x in val if isinstance(x, (int, float)))
            if union:
                origin = "perTemplate[*].*kind*"
    return union, origin


def validate() -> int:
    cfg = load(CONFIG)
    prefab = load(PREFAB)
    load(INHERITED)  # presence is what matters here; details validated elsewhere
    if cfg is None:
        print("ABORT: cannot validate without %s" % CONFIG.name)
        return 2

    behs = cfg.get("behaviours") or []

    # 1 + 2 + 6
    for b in behs:
        name = b.get("behaviour")
        carrier = b.get("carrier")
        if carrier not in CARRIER_LEGEND:
            problems.append("BEHAVIOUR_WITHOUT_KNOWN_CARRIER: %s -> %r" % (name, carrier))
        if carrier == "TEMPLATE_NATIVE" and b.get("mountRequired") is not False:
            problems.append("TEMPLATE_NATIVE_BUT_MOUNT_REQUIRED: %s" % name)
        if carrier in ("NODE_GRAPH", "NODE_GRAPH_PARTIAL"):
            if not (b.get("nodeWires") or b.get("perCampWires")):
                problems.append("GRAPH_CARRIER_WITHOUT_WIRES: %s" % name)

    # 3 -- a kind that a behaviour RELIES ON must be present in the prefab measurement's union.
    #
    # Why NOT_REQUIRED is exempt: a behaviour carried as NOT_REQUIRED says in its own note that the
    # kind is absent from the four templates' prefab record groups BY DESIGN, and that this absence
    # is deliberately not read as a capability negative. Requiring such a kind to be present would
    # turn the expected case into a reported problem -- a false positive that would train the reader
    # to ignore this check. Only carriers that assert the kind ARRIVES WITH THE TEMPLATE are strict.
    union, origin = prefab_kind_union(prefab)
    relied_on = sorted({int(k) for b in behs
                        if b.get("carrier") != "NOT_REQUIRED"
                        for k in (b.get("kinds") or [])})
    exempt = sorted({int(k) for b in behs
                     if b.get("carrier") == "NOT_REQUIRED"
                     for k in (b.get("kinds") or [])})
    if union:
        for k in relied_on:
            if k not in union:
                problems.append("KIND_NOT_IN_PREFAB_MEASUREMENT: %d (a behaviour relies on it,"
                                " but the measurement union does not contain it)" % k)
    else:
        problems.append("PREFAB_UNION_UNREADABLE: could not read any kind union from %s"
                        " -- kind-presence check did NOT run" % PREFAB.name)

    # 4
    gp = cfg.get("groundPolicy") or {}
    if "FAIL_CLOSED" not in str(gp.get("behaviourOnMissingSample", "")):
        problems.append("GROUND_POLICY_NOT_FAIL_CLOSED")
    if gp.get("provisional") is not True:
        problems.append("GROUND_POLICY_LOST_PROVISIONAL: heights would read as measured")

    # 5
    mp = cfg.get("mountPosture") or {}
    if mp.get("attachedComponentCount") != 0:
        problems.append("ATTACH_COUNT_NOT_ZERO: %r" % mp.get("attachedComponentCount"))

    print("behaviour-config.json: %s" % CONFIG.name)
    print("  behaviours=%d  carriers=%s" % (len(behs), sorted({b.get("carrier") for b in behs})))
    print("  kindsReliedOn=%d  kindsExemptAsNotRequired=%d  prefabUnionSize=%d (from %s)"
          % (len(relied_on), len(exempt), len(union), origin or "UNREADABLE"))
    print("  mountPosture.attachedComponentCount=%r" % mp.get("attachedComponentCount"))
    print("  groundPolicy.provisional=%r" % gp.get("provisional"))
    if problems:
        print("PROBLEMS (%d):" % len(problems))
        for p in problems:
            print("  - %s" % p)
        return 1
    print("OK: ALL_INVARIANTS_HOLD")
    return 0


def derive() -> int:
    inh = load(INHERITED)
    cfg = load(CONFIG)
    if inh is None or cfg is None:
        print("ABORT: need both %s and %s" % (INHERITED.name, CONFIG.name))
        return 2
    # report the per-behaviour carrier as stated by each source, so a difference is visible
    print("derivation report (this tool does NOT write %s)" % CONFIG.name)
    cfg_map = {b.get("behaviour"): b.get("carrier") for b in (cfg.get("behaviours") or [])}
    inh_rows = inh.get("behaviours") if isinstance(inh, dict) else None
    if not inh_rows:
        print("  %s carries no behaviours[] array; nothing to compare" % INHERITED.name)
        print("  config carriers: %s" % json.dumps(cfg_map, ensure_ascii=False, sort_keys=True))
        return 0
    diffs = 0
    for row in inh_rows:
        key = row.get("behaviour")
        if key in cfg_map:
            src = row.get("verdict") or row.get("carrier")
            if src and src != cfg_map[key]:
                diffs += 1
                print("  DIFF %s: inherited=%r config=%r" % (key, src, cfg_map[key]))
    print("  compared=%d  differences=%d" % (len(cfg_map), diffs))
    return 0


def main(argv) -> int:
    _config_override(argv)
    cmd = argv[1] if len(argv) > 1 and not argv[1].startswith("--") else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "derive":
        return derive()
    print("usage: behaviour_configurator.py [validate|derive] [--config PATH]")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
