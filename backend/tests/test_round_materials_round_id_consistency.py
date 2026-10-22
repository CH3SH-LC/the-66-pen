#!/usr/bin/env python3
"""F-011 / W18 -- the cleanup round's DIRECTORY NAME is one contract, proved in one place.

``tools/game-executor/round_materials.py`` (producer) and ``backend/entity_server.py``
(consumer) must agree on where a round's materials live, because the consumer does not
search for them: ``mw_scene_cleanup_owned`` DERIVES the path from the requestIds

    EVIDENCE_ROOT / 'cleanup' / _cleanup_round_id(createdByRequestIds)
                  / 'round-materials.json'

and ``_cleanup_round_id`` is a security property (the model never supplies the directory,
so it cannot aim the lookup at another round's materials).  When the two derivations
drift, the materials exist on disk and the route still refuses them with
``CLEANUP_ROUND_MATERIALS_UNAVAILABLE`` -- a silent, total break of the chain.

MEASURED 2026-10-02 (W18): the producer named the directory after ``spec.roundId``
(``round-20261002-dslive5``) while the consumer derived
``f7755123978a1d8c29d42a94cf710a5b`` from the round's 51 create requestIds.  The round's
materials were on disk, complete, and invisible to the route.

THE CHAIN THIS ASSERTS (each link is falsifiable on its own)
    producer.round_id_digest(ids) == consumer._cleanup_round_id(ids)      [derivation]
    the producer CLI's target directory == round_id_digest(its own ids)   [wiring]
    the producer CLI's target directory == consumer._cleanup_round_id(ids)[end to end]

MUTATION CONTROL
    The derivation assertions run again against the producer with ``round_id_digest``
    replaced by the human slug, and MUST go red.  A green run on the real producer is only
    evidence if the test can tell the difference.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import types
import unittest
from pathlib import Path


def find_repo_root(start=None) -> Path:
    """Walk up to the tree that holds BOTH halves of the contract."""
    here = Path(start or __file__).resolve()
    for candidate in [here.parent, *here.parents]:
        if ((candidate / "backend/entity_server.py").is_file()
                and (candidate / "tools/game-executor/round_materials.py").is_file()):
            return candidate
    raise RuntimeError("REPO_ROOT_NOT_FOUND from %s" % here)


ROOT = find_repo_root()
PRODUCER_PATH = ROOT / "tools/game-executor/round_materials.py"
CONSUMER_PATH = ROOT / "backend/entity_server.py"
SPEC = ROOT / ".runtime/cordis-plan-work/W13-CLEANMAT-20261002/spec/round-spec.json"
MATERIALS = (ROOT / ".runtime/game-executor/mcp-business/cleanup/"
             "round-20261002-dslive5/round-materials.json")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def exec_source(source: str, as_path: Path, name: str):
    """Run the producer's source in a namespace that believes it lives at ``as_path``.

    ``__file__`` is the real producer path on purpose: the module's own
    ``find_repo_root()`` walks up from it, so a mutated copy needs no file on disk and
    the tree is never written to.
    """
    namespace = {"__file__": str(as_path), "__name__": name}
    exec(compile(source, str(as_path), "exec"), namespace)
    return types.SimpleNamespace(round_id_digest=namespace["round_id_digest"])


consumer = load_module("_w18_consumer_entity_server", CONSUMER_PATH)


def cli_dry_run(producer_path: Path) -> tuple:
    """(target directory name, createdByRequestIds) the CLI resolves without writing."""
    proc = subprocess.run(
        [sys.executable, "-B", str(producer_path), "--spec", str(SPEC), "--dry-run"],
        cwd=str(ROOT), capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError("the producer did not assemble (exit %d): %s"
                             % (proc.returncode, proc.stderr[-800:]))
    document = json.loads(proc.stdout)
    return Path(document["targetDir"]).name, document["createdByRequestIds"]


def id_sets() -> dict:
    """The id sets the two derivations are compared on."""
    request_ids = []
    if MATERIALS.is_file():
        document = json.loads(MATERIALS.read_text(encoding="utf-8-sig"))
        request_ids = [entry["requestId"] for entry in document.get("receipts") or []]
    if not request_ids:
        request_ids = ["%032x" % ((index + 1) * 0x9E3779B1) for index in range(1, 4)]
    return {
        "round-receipts": request_ids,
        "shuffled-round-receipts": list(reversed(request_ids)),
        "unrelated-ids": ["1" * 32, "2" * 32, "3" * 32],
        "single-id": [request_ids[0]],
    }


def derivation_failures(producer) -> list:
    """Empty when producer.round_id_digest agrees with the consumer on every id set."""
    failures = []
    for label, ids in id_sets().items():
        produced = producer.round_id_digest(ids)
        expected = consumer._cleanup_round_id(ids)
        if produced != expected:
            failures.append({"idSet": label, "producer": produced, "consumer": expected})
    return failures


def mutate_to_slug(source: str) -> str:
    """The producer with its derivation replaced by the human slug."""
    pattern = (r'    digest = hashlib\.sha256\("\\n"\.join\(sorted\(request_ids\)\)'
               r'\.encode\("utf-8"\)\)\.hexdigest\(\)\s*\n\s*return digest\[:32\]')
    mutated, count = re.subn(
        pattern,
        '    return "round-20261002-dslive5"  # MUTANT: slug instead of the digest\n',
        source)
    assert count == 1, "the mutation site was not found exactly once (found %d)" % count
    return mutated


class RoundIdConsistency(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PRODUCER_PATH.is_file(), PRODUCER_PATH)
        self.producer = load_module("_w18_producer_tree", PRODUCER_PATH)

    def test_producer_derivation_equals_the_consumer(self):
        self.assertEqual([], derivation_failures(self.producer))

    @unittest.skipUnless(SPEC.is_file(), "no round spec on disk for a CLI run")
    def test_cli_directory_stays_on_the_chain(self):
        dir_name, request_ids = cli_dry_run(PRODUCER_PATH)
        self.assertEqual(self.producer.round_id_digest(request_ids), dir_name,
                         "the CLI resolved a directory its own derivation does not name, "
                         "so the derivation is not what names the directory")
        derived = consumer._cleanup_round_id(request_ids)
        self.assertEqual(derived, dir_name,
                         "the producer would write cleanup/%s/ and the route would look "
                         "in cleanup/%s/" % (dir_name, derived))

    def test_slug_mutation_is_detected(self):
        """The control: with the derivation replaced by the slug, the check goes red."""
        mutant_source = mutate_to_slug(PRODUCER_PATH.read_text(encoding="utf-8"))
        mutant = exec_source(mutant_source, PRODUCER_PATH, "_w18_producer_slug_mutant")
        failures = derivation_failures(mutant)
        self.assertTrue(failures,
                        "the mutation was NOT detected: this test proves nothing")
        self.assertEqual({"round-receipts", "shuffled-round-receipts", "unrelated-ids",
                          "single-id"},
                         {item["idSet"] for item in failures})


if __name__ == "__main__":
    unittest.main(verbosity=2)
