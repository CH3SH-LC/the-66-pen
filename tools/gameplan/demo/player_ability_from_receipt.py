"""Compile a character-created skill assembly graph from a revalidated skill run.

``python -m tools.gameplan.demo.player_ability_from_receipt --help``
Only ON_CREATE71 -> create809 -> bind806 is authored. This entry never dispatches,
casts, assigns input effects, creates skill notifications, or saves a level.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import struct
import sys

from ..builder import GraphBuilder
from ..modules import player_abilities as abilities
from ..nodes import Graph, ON_CREATE
from ..plan import PlanError

ROOT = Path(__file__).resolve().parents[3]
AUTHORING = ROOT / "tools/game-executor/template-authoring"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _runtime_path(value):
    path = Path(value)
    path = (path if path.is_absolute() else ROOT / path).resolve()
    _require(path.is_relative_to(ROOT / ".runtime") and path != ROOT / ".runtime",
             "ABILITY_EVIDENCE_OUTSIDE_PROJECT_RUNTIME")
    return path


def _acceptor():
    directory = str(AUTHORING)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    module = importlib.import_module("accept_skill")
    _require(Path(module.__file__).resolve() == AUTHORING / "accept_skill.py",
             "ABILITY_ACCEPTOR_MODULE_COLLISION")
    return module


def _unchanged(run, hashes):
    _require(type(hashes) is dict and {"prepared.json", "stdout.jsonl", "baseline-snapshot.bin"} <= hashes.keys(),
             "ABILITY_VALIDATED_INPUT_HASHES_REQUIRED")
    for name, digest in hashes.items():
        path = (run / name).resolve()
        _require(path.is_relative_to(run) and path != run and
                 hashlib.sha256(path.read_bytes()).hexdigest() == digest,
                 "ABILITY_RECEIPT_CHANGED:" + name)


def compile_from_receipt(*, skill_run, character_id: int, skill_id_slot: str,
                         skill_slot: int, replace_policy: int,
                         name: str = "MW_API_PLAYER_ABILITY") -> dict:
    """Compile one existing skill template into an explicit character graph.

    The character must appear in the receipt's verified scene. This is recorded
    identity evidence, not a fresh live identity or playable-role assignment.
    Slot enum values remain explicit and require native descriptor verification.
    """
    abilities.config_id(character_id, "character_id")
    abilities.config_slot(skill_id_slot)
    abilities.integer(skill_slot, "skill_slot")
    abilities.integer(replace_policy, "replace_policy")
    run = _runtime_path(skill_run)
    module = _acceptor()
    accepted = module.validate_run(run)  # Recompute raw ABI, transport and catalogues.
    _require(accepted.get("ok") is True and accepted.get("action") == "create-skill" and
             accepted.get("catalogRegisteredVerified") is True and
             Path(accepted["run"]).resolve() == run, "ABILITY_REGISTERED_SKILL_REQUIRED")
    _unchanged(run, accepted["inputHashes"])
    prepared = module.requests.read_json(run / "prepared.json")
    level = accepted["levelId"]
    _require(prepared["levelId"] == level, "ABILITY_VALIDATED_LEVEL_MISMATCH")
    session = {key: prepared["session"][key] for key in module.requests.SESSION_FIELDS}
    snapshot = module.scene((run / "baseline-snapshot.bin").read_bytes(), module.profiles.load_profile(), level)
    character = [e for e in snapshot["entities"] if e["id"] == character_id]
    _require(len(character) == 1 and character[0]["dictionaryKey"] == character_id,
             "ABILITY_CHARACTER_NOT_IN_RECORDED_SCENE")
    skill_id = abilities.config_id(accepted["createdId"], "created_skill_id")
    graph = Graph(name)
    created = graph.place(ON_CREATE, "on_character_create")
    abilities.create_and_bind(graph, created, character=(created, "entity"), skill_id=skill_id,
        skill_id_slot=skill_id_slot, skill_slot=skill_slot, replace_policy=replace_policy)
    graph.validate()

    def no_dispatch(_):
        raise AssertionError("ability receipt compiler cannot dispatch")

    builder = GraphBuilder(graph.plan, no_dispatch, run_id="compile-only", entity_id=character_id)
    plan = builder.batch_plan_json()
    _unchanged(run, accepted["inputHashes"])
    return {"ok": True, "mode": "compile", "buildMode": "batch",
            "scope": "character_created_skill_instance_assembly_plan_only",
            "deploymentReady": False, "editorDispatchAttempted": False,
            "rawReceiptRevalidated": True, "recordedCharacterIdentityVerified": True,
            "liveSessionRevalidated": False, "persistentSaveVerified": False,
            "gameRuntimeVerified": False, "farmingSkillTriggerVerified": False,
            "levelId": level, "session": session, "characterId": character_id,
            "recordedCharacterConfigId": character[0]["configId"],
            "graphName": name, "graphKind": graph.plan.graph_kind,
            "bindingTarget": {"entityId": character_id, "configured": True, "nativeBindingVerified": False},
            "createdSkillId": skill_id,
            "config": {"skill_id_slot": skill_id_slot, "skill_slot": skill_slot,
                       "replace_policy": replace_policy},
            "summary": {"nodes": len(graph.plan.nodes), "edges": len(graph.plan.edges),
                        "consts": len(graph.plan.consts)}, "plan": plan,
            "source": {"run": str(run), "action": accepted["action"],
                       "requestSha256": accepted["requestSha256"], "reviewSha256": accepted["reviewSha256"],
                       "rawStdoutSha256": accepted["inputHashes"]["stdout.jsonl"],
                       "acceptorSha256": accepted["acceptorSha256"], "decoderHashes": accepted["decoderHashes"]},
            "prerequisites": {
                "playableCharacterAssignment": {"verified": False, "entityId": character_id},
                "physicalSkillIdSlot": {"verified": False, "explicitValue": skill_id_slot},
                "skillSlotEnum": {"verified": False, "explicitValue": skill_slot},
                "replacePolicyEnum": {"verified": False, "explicitValue": replace_policy},
                "entityCreatedDelivery": {"verified": False, "eventDefinitionId": 71},
                "skillTemplateEffects": {"verified": False, "templateId": skill_id}},
            "note": "The graph targets the explicit character entity and uses event71's entity for 809/806. "
                    "No input binding, skill casting, effect configuration, or event392 farming notification is authored. "
                    "Raw registration acceptance supplies the ID only; native slots, save and play remain unverified."}


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-run", required=True)
    parser.add_argument("--character-id", type=int, required=True)
    parser.add_argument("--skill-id-slot", choices=("int", "uint", "enum"), required=True)
    parser.add_argument("--skill-slot", type=int, required=True, help="explicit native enum value; no inferred default")
    parser.add_argument("--replace-policy", type=int, required=True, help="explicit native enum value; no inferred default")
    parser.add_argument("--name", default="MW_API_PLAYER_ABILITY")
    return parser


def main(argv=None):
    options = vars(build_parser().parse_args(argv))
    try:
        result = compile_from_receipt(**options)
    except (OSError, ValueError, KeyError, TypeError, struct.error, PlanError) as error:
        print(json.dumps({"ok": False, "mode": "compile", "error": str(error),
                          "editorDispatchAttempted": False, "deploymentReady": False}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
