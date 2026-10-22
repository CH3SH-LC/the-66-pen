"""Offline client tests: fake send, temporary ROOT, no elevated helper or editor."""
from pathlib import Path
import base64
import contextlib
import importlib.util
import io
import json
import stat
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "elevated-request.py"
spec = importlib.util.spec_from_file_location("elevated_request_node_tests", SOURCE)
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)
RUN = "11111111-1111-1111-1111-111111111111"

class NodeQueryTests(unittest.TestCase):
    def run_cli(self, argv, response=None):
        with patch.object(sys, "argv", [str(SOURCE), *argv]), patch.object(client, "send", return_value=response or {"ok": True}) as send, patch.object(client, "latest_run_id", side_effect=AssertionError("unexpected scope scan")), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = client.main()
            return result, send.call_args

    def refuse_cli(self, argv):
        with patch.object(sys, "argv", [str(SOURCE), *argv]), patch.object(client, "send") as send, patch.object(client, "latest_run_id") as latest, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit): client.main()
            send.assert_not_called()
            latest.assert_not_called()

    def test_ids_forward_exact_numbers_and_order(self):
        result, call = self.run_cli(["call", "--op", "node-definitions", "--run-id", RUN, "--ids", "71", "1", "4294967295"])
        self.assertEqual(result, 0)
        self.assertEqual(call.args[0], {"kind":"call", "runId":RUN, "op":"node-definitions", "ids":[71,1,4294967295]})
        self.assertEqual(json.loads(json.dumps(call.args[0]))["ids"], [71,1,4294967295])

    def test_variant_query_is_bounded_and_exact(self):
        result, call = self.run_cli(["call", "--op", "node-definition-variants", "--run-id", RUN, "--ids", "200301", "300005"])
        self.assertEqual(result, 0)
        self.assertEqual(call.args[0]["ids"], [200301, 300005])
        self.assertEqual(call.args[0]["op"], "node-definition-variants")
        for values in ([], ["0"], ["1"]*65):
            self.refuse_cli(["call", "--op", "node-definition-variants", "--ids", *values])
        self.refuse_cli(["call", "--op", "NODE-DEFINITION-VARIANTS", "--ids", "1"])
        self.refuse_cli(["call", "--op", "node-definition-variants"])

    def test_ids_boundary_64(self):
        result, call = self.run_cli(["call", "--op", "node-definitions", "--run-id", RUN, "--ids", *["71"]*64])
        self.assertEqual(result, 0); self.assertEqual(len(call.args[0]["ids"]), 64)

    def test_missing_ids_rejects_before_scope_or_send(self):
        self.refuse_cli(["call", "--op", "node-definitions"])

    def test_invalid_cli_ids_never_send(self):
        for values in (["0"], ["-1"], ["4294967296"], ["1.0"], ["true"], ["x"], [], ["1"]*65):
            with self.subTest(values=values[:2]):
                self.refuse_cli(["call", "--op", "node-definitions", "--ids", *values])

    def test_other_op_cannot_receive_ids(self):
        self.refuse_cli(["call", "--op", "ping", "--ids", "71"])
        self.refuse_cli(["call", "--op", "NODE-DEFINITIONS"])
        self.refuse_cli(["status", "--ids", "71"])

    def test_validator_rejects_json_coercions(self):
        for ids in ([], [True], [False], [1.0], [None], ["71"], [[71]], {"id":71}, "71", [0], [-1], [4294967296]):
            with self.subTest(ids=ids):
                with self.assertRaises(SystemExit): client.validate_call_ids("node-definitions", ids)

    def test_other_call_unchanged_and_business_failure_obeyed(self):
        result, call = self.run_cli(["call", "--op", "ping", "--run-id", RUN], {"ok":False})
        self.assertEqual(result, 1)
        self.assertEqual(call.args[0], {"kind":"call", "runId":RUN, "op":"ping"})

class ReadOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bridge-output-offline-")
        self.root = Path(self.temp.name) / "project"
        self.output_dir = self.root / ".runtime" / "candidates"
        self.output_dir.mkdir(parents=True)
        self.root_patch = patch.object(client, "ROOT", self.root)
        self.root_patch.start()
    def tearDown(self):
        self.root_patch.stop(); self.temp.cleanup()
    def cli(self, out, op="read"):
        payload = {"op":"read", "encoding":"base64", "data":base64.b64encode(b"candidate").decode()}
        with patch.object(sys, "argv", [str(SOURCE), "fs", "--op", op, "--path", str(self.root/"backup.bin"), "--out", str(out)]), patch.object(client, "send", return_value=payload) as send, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return client.main(), send
    def refuse(self, out, op="read"):
        with patch.object(sys, "argv", [str(SOURCE), "fs", "--op", op, "--path", str(self.root/"backup.bin"), "--out", str(out)]), patch.object(client, "send") as send, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit): client.main()
            send.assert_not_called()
    def test_new_candidate_output(self):
        out=self.output_dir/"candidate.gil"
        result,send=self.cli(out)
        self.assertEqual(result,0); self.assertEqual(out.read_bytes(),b"candidate"); send.assert_called_once()
    def test_formal_save_outside_runtime_rejected_without_send(self):
        formal=Path(self.temp.name)/"game"/"BeyondLocalData"/"UserData"/"save.gil"
        formal.parent.mkdir(parents=True); formal.write_bytes(b"protected")
        self.refuse(formal); self.assertEqual(formal.read_bytes(),b"protected")
    def test_existing_runtime_output_never_overwritten(self):
        out=self.output_dir/"existing.gil"; out.write_bytes(b"keep")
        self.refuse(out); self.assertEqual(out.read_bytes(),b"keep")
    def test_path_escape_missing_parent_and_runtime_root(self):
        for out in (self.root/".runtime-neighbor"/"copy.gil", self.output_dir/".."/".."/".."/"escape.gil", self.output_dir/"missing"/"copy.gil", self.root/".runtime"):
            with self.subTest(out=out): self.refuse(out)
    def test_devices_ads_and_trailing_aliases_rejected(self):
        for name in ("CON", "NUL.gil", "LPT1.gil", "COM9", "candidate:stream", "candidate.", "candidate "):
            with self.subTest(name=name): self.refuse(self.output_dir/name)
    def test_non_read_out_rejected(self): self.refuse(self.output_dir/"copy.gil", "write")
    def test_reparse_parent_rejected(self):
        original=Path.lstat
        def flagged(path,*a,**kw):
            if path == self.output_dir:
                return SimpleNamespace(st_mode=stat.S_IFDIR,st_file_attributes=0x400)
            return original(path,*a,**kw)
        with patch.object(Path,"lstat",flagged): self.refuse(self.output_dir/"copy.gil")
    def test_symlink_parent_rejected(self):
        original=Path.lstat
        def flagged(path,*a,**kw):
            if path == self.output_dir:
                return SimpleNamespace(st_mode=stat.S_IFLNK,st_file_attributes=0)
            return original(path,*a,**kw)
        with patch.object(Path,"lstat",flagged): self.refuse(self.output_dir/"copy.gil")
    def test_output_appears_between_checks_is_not_overwritten(self):
        out=self.output_dir/"raced.gil"
        original=Path.open
        def racing(path,mode="r",*a,**kw):
            if path == out and mode == "xb":
                with original(path,"wb") as f: f.write(b"other writer")
            return original(path,mode,*a,**kw)
        with patch.object(Path,"open",racing):
            with self.assertRaisesRegex(SystemExit,"READ_OUT_ALREADY_EXISTS"): client.write_read_output(out,b"overwrite")
        self.assertEqual(out.read_bytes(),b"other writer")

if __name__ == "__main__": unittest.main(verbosity=2)
