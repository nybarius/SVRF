"""demo/anonymize_receipts.py keeps numbers and timings and drops every name."""

from __future__ import annotations

import importlib.util
import json
import unittest

from fakes import ROOT

spec = importlib.util.spec_from_file_location("anonymize_receipts", ROOT / "demo" / "anonymize_receipts.py")
anon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(anon)

A, B, C = "a" * 40, "b" * 40, "c" * 40
RAW = {
    "schema_version": "other/1", "started": "20260925T100000Z", "finished": "20260925T100500Z",
    "secret_field": "keep-out", "requested": [900, 902],
    "prs": {"900": {"number": 900, "head_sha": A, "head_ref": "team/feature-x", "title": "Secret title"}},
    "families": [{"id": "F1", "parent": None, "prs": [900, 902], "tree": B, "commit": C, "base": A,
                  "status": "LANDED", "gate": 0, "steps": [{"number": 900, "commit": C, "tree": B}]}],
    "gates": [{"family": "F1", "prs": [900, 902], "tree": B, "green": False, "seconds": 12.5, "started": 1.0,
               "logs": "/srv/logs/F1", "failing": ["FAILED tests/test_private.py::x", "FAILED tests/test_private.py::x"],
               "slot": "slot-3"}],
    "merges": [{"number": 902, "family": "F1", "gated_tree": B, "observed_tree": B, "identity": True, "at": 5.0,
                "parents": [A]}],
    "holds": [{"number": 900, "reason": "GATE_RED", "paths": ["src/private.py"], "failing": ["FAILED tests/test_private.py::x"]}],
    "unobserved": [{"number": 902, "read_failure": "LANDED_TREE_UNREAD:GIT_FAILED:rev-parse:128:fatal: /srv/x"}],
}


class Anonymize(unittest.TestCase):
    def setUp(self):
        self.out = anon.Anonymizer().receipt(RAW)
        self.text = json.dumps(self.out)

    def test_no_name_path_or_unknown_field_survives(self):
        for secret in ("team/feature", "Secret title", "/srv", "test_private", "src/private", "keep-out", A, B, C):
            self.assertNotIn(secret, self.text)
        self.assertEqual(self.out["schema_version"], "svrf.receipt/1")

    def test_numbers_timings_and_tree_identity_survive(self):
        self.assertEqual(self.out["requested"], [101, 102])
        self.assertEqual(self.out["gates"][0]["seconds"], 12.5)
        self.assertEqual(self.out["gates"][0]["failing"], ["FAILED case-1", "FAILED case-1"])
        m = self.out["merges"][0]
        self.assertEqual(m["gated_tree"], m["observed_tree"])
        self.assertEqual(m["gated_tree"], self.out["families"][0]["tree"])
        self.assertEqual(self.out["retry_later"], [{"number": 102, "reason": "LANDED_TREE_UNREAD:GIT_FAILED"}])
        self.assertEqual(self.out["holds"][0]["paths"], ["path-1"])


if __name__ == "__main__":
    unittest.main()
