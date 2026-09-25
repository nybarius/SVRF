"""`svrf why <pr>`: local-state-only explanation of where one pull request sits, with a
plain next step, and `svrf status --json` accepting the flag agents are told to pass."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from svrf import cli
from svrf.config import from_dict


def config_for(tmp: Path):
    config = from_dict({"repo": "owner/name", "state_dir": str(tmp / "state"), "gate": {"commands": ["true"]}})
    return config


class Why(unittest.TestCase):
    def test_unknown_pull_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = config_for(Path(tmp))
            result = cli.why(config, 42)
            self.assertEqual(result["state"], "UNKNOWN")
            self.assertIn("next_step", result)

    def test_a_held_pull_request_reports_its_reason_and_a_next_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config = config_for(tmp)
            (tmp / "state").mkdir()
            (tmp / "state" / "state.json").write_text(json.dumps({
                "schema_version": "svrf.state/1",
                "held": {"7": {"reason": "GATE_RED", "head": "abcdef1234567890", "failing": ["FAILED x"],
                               "at": "2026-01-01T00:00:00Z"}}}))
            result = cli.why(config, 7)
            self.assertEqual(result["state"], "HELD")
            self.assertEqual(result["reason"], "GATE_RED")
            self.assertEqual(result["failing"], ["FAILED x"])
            self.assertIn("push", result["next_step"].lower())

    def test_a_pull_request_still_in_the_last_receipts_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config = config_for(tmp)
            receipts = tmp / "state" / "receipts"
            receipts.mkdir(parents=True)
            (receipts / "train-20260101T000000Z-1-0000.json").write_text(json.dumps({
                "schema_version": "svrf.receipt/1", "merges": [], "out": {},
                "families": [{"id": "F1", "prs": [5, 6], "status": "GATED"}]}))
            result = cli.why(config, 6)
            self.assertEqual(result["state"], "GATED")
            self.assertEqual(result["batch"], "F1")
            self.assertEqual(result["queue_position"], 2)
            self.assertEqual(result["batch_size"], 2)

    def test_a_merged_pull_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config = config_for(tmp)
            receipts = tmp / "state" / "receipts"
            receipts.mkdir(parents=True)
            (receipts / "train-20260101T000000Z-1-0000.json").write_text(json.dumps({
                "schema_version": "svrf.receipt/1", "merges": [{"number": 9, "identity": True}], "out": {},
                "families": []}))
            result = cli.why(config, 9)
            self.assertEqual(result["state"], "MERGED")

    def test_a_pull_request_left_out_of_the_last_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config = config_for(tmp)
            receipts = tmp / "state" / "receipts"
            receipts.mkdir(parents=True)
            (receipts / "train-20260101T000000Z-1-0000.json").write_text(json.dumps({
                "schema_version": "svrf.receipt/1", "merges": [], "families": [],
                "out": {"3": {"conflicts_with": [4], "paths": ["a.py"]}}}))
            result = cli.why(config, 3)
            self.assertEqual(result["state"], "OUT_THIS_ROUND")
            self.assertIn("conflicts_with", result["detail"])


class CommandLine(unittest.TestCase):
    def run_cli(self, *argv) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def config_file(self, tmp: Path) -> Path:
        path = tmp / "svrf.toml"
        path.write_text(f'repo = "a/b"\nclone = "{tmp / "clone"}"\nstate_dir = "{tmp / "state"}"\n'
                        '[gate]\ncommands = ["true"]\n')
        return path

    def test_svrf_why_from_the_command_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path = self.config_file(tmp)
            code, out = self.run_cli("--config", str(path), "why", "5")
            self.assertEqual(code, 0)
            value = json.loads(out)
            self.assertEqual(value["number"], 5)
            self.assertEqual(value["state"], "UNKNOWN")

    def test_status_accepts_the_json_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path = self.config_file(tmp)
            code, out = self.run_cli("--config", str(path), "status", "--json")
            self.assertEqual(code, 0)
            value = json.loads(out)
            self.assertEqual(value["repo"], "a/b")


if __name__ == "__main__":
    unittest.main()
