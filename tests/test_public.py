import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pen
from tools.node_workbench.catalog import Catalog
from tools.node_workbench.recipes import compatible_edge, recipe, value_candidate
from tools.node_workbench.explain import describe_node


class PublicDistribution(unittest.TestCase):
    def test_catalog_every_source_and_tool_exists(self):
        for row in pen.load("catalog/interfaces.json")["interfaces"]:
            self.assertTrue((ROOT / row["source"]).is_file(), row["source"])
            self.assertTrue((ROOT / row["tool"]).is_file(), row["tool"])
            self.assertFalse(row["runtimeVerifiedThisRelease"])

    def test_node_domain_all_recipes(self):
        c = Catalog()
        self.assertEqual((len(c.nodes), len({x["definitionId"] for x in c.nodes})), (929, 810))
        self.assertEqual(sum(len(x["ports"]) for x in c.nodes), 4637)
        for node in c.nodes:
            result = recipe(c, node["graphKind"], node["definitionId"])
            self.assertEqual(len(result["ports"]), len(node["ports"]))
            self.assertFalse(result["runtimeVerified"])
            explanation = describe_node(c, node["graphKind"], node["definitionId"])
            self.assertEqual(explanation["ports"]["total"], len(node["ports"]))
        self.assertEqual(len(c.data["enumGroups"]), 103)

    def test_exact_type_checks(self):
        c = Catalog()
        self.assertEqual(value_candidate(c, 20000, 79, 2, {"uint": 1})["slot"], "enum")
        with self.assertRaises(ValueError):
            value_candidate(c, 20000, 79, 2, {"bool": True})
        with self.assertRaises(ValueError):
            value_candidate(c, 20000, 79, 2, {"uint": 999})
        with self.assertRaises(ValueError):
            compatible_edge(c, 20000, 307, "1:0", 259, "3:0")

    def test_synthetic_roundtrip_unknown_field_diff_no_overwrite(self):
        scratch = ROOT / ".runtime/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as d:
            result = pen.demo(d)
            self.assertEqual(result["diff"]["changedFields"], [102])
            self.assertTrue(result["files"][0]["byteRoundtrip"])
            self.assertIn(101, result["files"][0]["fieldCounts"])
            with self.assertRaises(FileExistsError):
                pen.demo(d)

    def test_malformed_container_rejected(self):
        gc, _ = pen.codecs()
        for malformed in [b"", b"\0" * 24, b"\x08\x80", b"\x00"]:
            with self.assertRaises(ValueError):
                gc.decode_container(malformed)

    def test_pagination_and_static_caveats(self):
        with self.assertRaises(ValueError):
            pen.catalog(limit=0)
        rows = pen.load("catalog/user-operations.json")["operations"]
        self.assertEqual(len(rows), 92)
        self.assertTrue(all(x["evidence"] == "static-candidate" and not x["callable"] for x in rows))
        self.assertEqual(pen.catalog(limit=2)["nextOffset"], 2)

    def test_mcp_transport_and_unknown_tool(self):
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "pen_nodes", "arguments": {"definition_id": 307, "graph_kind": 20000}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "arbitrary_shell", "arguments": {}}},
        ]
        run = subprocess.run([sys.executable, "-X", "utf8", "-B", str(ROOT / "pen.py"), "mcp"],
                             input="\n".join(json.dumps(x) for x in messages) + "\n",
                             text=True, encoding="utf-8", capture_output=True, cwd=ROOT.parent, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        replies = [json.loads(x) for x in run.stdout.splitlines()]
        self.assertEqual([x["id"] for x in replies], [1, 2, 3, 4])
        self.assertEqual(len(replies[1]["result"]["tools"]), 4)
        self.assertFalse(replies[2]["result"]["isError"])
        self.assertTrue(replies[3]["result"]["isError"])

    def test_core_cli_help_no_runtime(self):
        for name in pen.TOOLS:
            run = subprocess.run([sys.executable, "-X", "utf8", "-B", str(ROOT / "pen.py"),
                                  "tool", name, "--help"], capture_output=True, text=True,
                                  encoding="utf-8", cwd=ROOT.parent, timeout=30)
            self.assertEqual(run.returncode, 0, name + ": " + run.stderr[-3000:])


if __name__ == "__main__":
    unittest.main()
