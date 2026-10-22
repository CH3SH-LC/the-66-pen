"""Candidate-only source/ABI generation. Never opens a game process or compiles."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import terrain_native as native

class CandidateTests(unittest.TestCase):
    def test_both_snapshot_abis_and_private_action(self):
        for size in (33208,262584):
            with self.subTest(size=size),tempfile.TemporaryDirectory(dir=native.ROOT/'.runtime') as temp:
                run=Path(temp);hashes=native.sources(run)
                plan={'terrainId':1001,'before':[[123,1,0,2,3,4]],'expected':[[123,2,0,2,3,4]],
                      'changes':[{'after':[123,2,0,2,3,4],'op':'set'}]}
                native.request_header(run,plan,bytes(size),1073741900,False)
                header=(run/'candidate-source/map-terrain/terrain_request.h').read_text()
                self.assertIn('static_assert(sizeof(kTerrainExpectedScene)==sizeof(GameContextSnapshot)',header)
                protocol=(run/'candidate-source/native/hook_receipt_protocol.h').read_text()
                self.assertIn('HR_ACTION == 14 ? 18',protocol)
                self.assertIn('TerrainReceipt terrain;',protocol)
                probe=(run/'candidate-source/native/hook_receipt_probe.cpp').read_text()
                self.assertIn('receiptPrefixHex',probe)
                self.assertIn('std::memset(receipt, 0, sizeof(*receipt));',probe)
                self.assertNotIn('*receipt = {};',probe)
                self.assertIn('ExecuteTerrainAction',(run/'candidate-source/native/hook_receipt.cpp').read_text())
                self.assertTrue(hashes)

    def test_candidate_mutation_refuses_changed_shared_contract(self):
        with self.assertRaises(ValueError):native.replace('different source','known anchor','replacement')

if __name__=='__main__':unittest.main()
