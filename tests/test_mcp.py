"""`svrf mcp`: the stdio JSON-RPC server, its three tools, and that `requeue` only ever
clears a local hold record (no merge, gate, or push)."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fakes import ROOT

from svrf import mcp
from svrf.config import from_dict


def config_for(tmp: Path):
    return from_dict({"repo": "owner/name", "state_dir": str(tmp / "state"), "gate": {"commands": ["true"]}})


class Handshake(unittest.TestCase):
    def test_initialize_reports_the_protocol_and_tools_capability(self):
        config = from_dict({"repo": "owner/name", "gate": {"commands": ["true"]}})
        reply = mcp.handle(config, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(reply["id"], 1)
        self.assertIn("protocolVersion", reply["result"])
        self.assertIn("tools", reply["result"]["capabilities"])

    def test_a_notification_gets_no_reply(self):
        config = from_dict({"repo": "owner/name", "gate": {"commands": ["true"]}})
        reply = mcp.handle(config, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertIsNone(reply)

    def test_tools_list_names_all_three_tools(self):
        config = from_dict({"repo": "owner/name", "gate": {"commands": ["true"]}})
        reply = mcp.handle(config, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in reply["result"]["tools"]}
        self.assertEqual(names, {"queue_status", "why_held", "requeue"})

    def test_an_unknown_method_is_a_json_rpc_error(self):
        config = from_dict({"repo": "owner/name", "gate": {"commands": ["true"]}})
        reply = mcp.handle(config, {"jsonrpc": "2.0", "id": 3, "method": "nonsense"})
        self.assertIn("error", reply)


class Tools(unittest.TestCase):
    def test_queue_status_reports_the_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = config_for(Path(tmp))
            reply = mcp.handle(config, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                        "params": {"name": "queue_status", "arguments": {}}})
            value = json.loads(reply["result"]["content"][0]["text"])
            self.assertEqual(value["repo"], "owner/name")

    def test_why_held_reports_unknown_for_an_unseen_pull_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = config_for(Path(tmp))
            reply = mcp.handle(config, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                        "params": {"name": "why_held", "arguments": {"pr": 5}}})
            value = json.loads(reply["result"]["content"][0]["text"])
            self.assertEqual(value["state"], "UNKNOWN")

    def test_requeue_clears_a_hold_and_only_a_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config = config_for(tmp)
            (tmp / "state").mkdir()
            (tmp / "state" / "state.json").write_text(json.dumps({
                "schema_version": "svrf.state/1", "held": {"7": {"reason": "GATE_RED"}}}))
            reply = mcp.handle(config, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                        "params": {"name": "requeue", "arguments": {"pr": 7}}})
            value = json.loads(reply["result"]["content"][0]["text"])
            self.assertEqual(value["forgot"], [7])
            state = json.loads((tmp / "state" / "state.json").read_text())
            self.assertNotIn("7", state["held"])

    def test_requeue_is_a_no_op_when_nothing_is_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = config_for(Path(tmp))
            reply = mcp.handle(config, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                        "params": {"name": "requeue", "arguments": {"pr": 99}}})
            value = json.loads(reply["result"]["content"][0]["text"])
            self.assertEqual(value["forgot"], [])

    def test_an_unknown_tool_is_reported_as_an_error_result_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = config_for(Path(tmp))
            reply = mcp.handle(config, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                        "params": {"name": "bogus", "arguments": {}}})
            self.assertTrue(reply["result"].get("isError"))


class Serve(unittest.TestCase):
    def test_serve_reads_newline_delimited_json_and_writes_replies(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = config_for(Path(tmp))
            request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
            stdin = io.StringIO(request)
            stdout = io.StringIO()
            mcp.serve(config, stdin=stdin, stdout=stdout)
            reply = json.loads(stdout.getvalue().strip())
            self.assertEqual(reply["id"], 1)
            self.assertIn("tools", reply["result"])

    def test_serve_skips_blank_and_unparseable_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = config_for(Path(tmp))
            stdin = io.StringIO("\nnot json\n" + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
            stdout = io.StringIO()
            mcp.serve(config, stdin=stdin, stdout=stdout)
            lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["id"], 2)


class CommandLine(unittest.TestCase):
    def test_svrf_mcp_serves_one_request_over_real_stdio(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config_path = tmp / "svrf.toml"
            config_path.write_text(f'repo = "a/b"\nstate_dir = "{tmp / "state"}"\n[gate]\ncommands = ["true"]\n')
            request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
            done = subprocess.run([sys.executable, "-m", "svrf", "--config", str(config_path), "mcp"],
                                  input=request, capture_output=True, text=True,
                                  env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
            self.assertEqual(done.returncode, 0, done.stderr)
            reply = json.loads(done.stdout.strip())
            self.assertEqual(reply["id"], 1)
            self.assertIn("tools", reply["result"])


if __name__ == "__main__":
    unittest.main()
