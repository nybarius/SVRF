"""The demo end to end: a local bare origin, a fake agent swarm, the real train code."""

from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

from fakes import ROOT

spec = importlib.util.spec_from_file_location("run_demo", ROOT / "demo" / "run_demo.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class Demo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="svrf-demo-test-"))
        cls.result = demo.run(cls.root)
        cls.rows = {r["number"]: r for r in cls.result["rows"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_ordinary_features_merge_in_the_first_round(self):
        for n in (1, 2, 3, 8):
            self.assertEqual((self.rows[n]["result"], self.rows[n]["detail"]), ("merged", "round 1"), n)

    def test_the_conflicting_setting_is_left_out_then_held_with_its_paths(self):
        self.assertIn(4, self.result["out"])
        self.assertEqual(self.rows[4]["result"], "held")
        self.assertIn("merge:CONFLICT:", self.rows[4]["detail"])

    def test_the_failing_feature_is_bisected_out_and_held_with_its_failure(self):
        self.assertEqual(self.rows[5]["result"], "held")
        self.assertIn("GATE_RED", self.rows[5]["detail"])
        self.assertIn("test_divide", self.rows[5]["detail"])

    def test_the_out_of_order_history_is_relanded_and_the_new_pr_merges(self):
        self.assertEqual(self.rows[6]["result"], "superseded")
        self.assertEqual(self.rows[9]["result"], "merged")
        self.assertEqual(self.rows[9]["author"], "svrf")

    def test_the_stacked_pr_is_retargeted_and_merges(self):
        self.assertIn(7, self.result["retargeted"])
        self.assertEqual(self.rows[7]["result"], "merged")

    def test_every_landed_tree_is_its_gated_tree_and_the_train_goes_idle(self):
        self.assertTrue(self.result["identity"])
        self.assertEqual(self.result["merges"], 6)
        self.assertLess(self.result["rounds"], 8)

    def test_the_table_renders(self):
        text = demo.table(self.result)
        self.assertIn("landed tree == gated tree for every merge: True", text)


if __name__ == "__main__":
    unittest.main()
