"""`svrf dashboard`: a static site generated from round receipts."""

from __future__ import annotations

import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from svrf import cli, dashboard

H = 1790330400.0  # 2026-09-25T10:00:00Z


def fam(ident, prs, status, gate=None, parent=None):
    return {"id": ident, "parent": parent, "prs": prs, "status": status, "gate": gate, "tree": f"t-{ident}",
            "commit": f"c-{ident}", "base": "b", "steps": []}


def gate(family, prs, green, started, seconds, **extra):
    return {"family": family, "prs": prs, "green": green, "started": started, "seconds": seconds,
            "failing": [] if green else ["FAILED case-1"], **extra}


def merge(number, family, at, gated="t", observed="t"):
    return {"number": number, "family": family, "at": at, "gated_tree": gated, "observed_tree": observed,
            "identity": observed == gated if observed is not None else False}


def receipt(started, finished, **fields):
    base = {"schema_version": "svrf.receipt/1", "started": started, "finished": finished,
            "config": {"jobs": 1, "family_size": 8}, "requested": [], "prs": {}, "rounds": [], "families": [],
            "gates": [], "merges": [], "holds": [], "retry_later": [], "pending": [], "alerts": [], "out": {}}
    base.update(fields)
    return base


def sample() -> list[dict]:
    bisected = receipt(
        "20260925T100000Z", "20260925T100500Z", requested=[1, 2, 3, 4],
        families=[fam("F1", [1, 2, 3, 4], "BISECTED", 0), fam("F2", [1, 2], "LANDED", 1, "F1"),
                  fam("F3", [3, 4], "BISECTED", 2, "F1"), fam("F4", [3], "LANDED", 3, "F3"),
                  fam("F5", [4], "HELD", 4, "F3")],
        gates=[gate("F1", [1, 2, 3, 4], False, H + 5, 100), gate("F2", [1, 2], True, H + 110, 50),
               gate("F3", [3, 4], False, H + 170, 40), gate("F4", [3], True, H + 215, 30),
               gate("F5", [4], False, H + 170, 0.0, reused=2)],
        merges=[merge(1, "F2", H + 170), merge(2, "F2", H + 175), merge(3, "F4", H + 250)],
        holds=[{"number": 4, "reason": "GATE_RED", "paths": [], "failing": ["FAILED case-1"]}])
    mixed = receipt(
        "20260925T110000Z", "20260925T110100Z", requested=[5, 6],
        families=[fam("F1", [5, 6], "TREE_MISMATCH", 0)],
        gates=[gate("F1", [5, 6], True, H + 3605, 20)],
        merges=[merge(5, "F1", H + 3630, observed=None), merge(6, "F1", H + 3640, observed="other")],
        alerts=[{"alert": "TREE_MISMATCH", "family": "F1", "number": 6, "planned": "t", "observed": "other"}])
    live = receipt(
        "20260925T120000Z", None, requested=[7, 8, 9, 10], config={"jobs": 1, "family_size": 2},
        families=[fam("F1", [7, 8], "PLANNED"), fam("F2", [9], "PLANNED")],
        retry_later=[{"number": 10, "reason": "NOT_OPEN_IN_SNAPSHOT"}])
    return [live, bisected, mixed]  # out of order on purpose


class Summary(unittest.TestCase):
    def setUp(self):
        self.s = dashboard.summarize(sample())

    def test_rounds_are_ordered_by_start_and_totals_count_merges_and_fresh_gates(self):
        self.assertEqual([r["started"] for r in self.s["rounds"]],
                         ["20260925T100000Z", "20260925T110000Z", "20260925T120000Z"])
        t = self.s["totals"]
        self.assertEqual((t["rounds"], t["merged"], t["gates"], t["holds"]), (3, 5, 5, 1))
        self.assertEqual(t["gates_per_pr"], 1.0)          # a reused red result is not a gate run
        self.assertEqual(t["wall_seconds"], 360)          # finished rounds only
        self.assertEqual(t["wall_per_pr"], 72.0)

    def test_per_round_gates_and_wall_per_merged_pr(self):
        first = self.s["rounds"][0]
        self.assertEqual((first["merged"], first["gates"], first["wall"]), (3, 4, 300))
        self.assertAlmostEqual(first["gates_per_pr"], 4 / 3, places=3)
        self.assertEqual(first["wall_per_pr"], 100.0)
        self.assertIsNone(self.s["rounds"][2]["wall_per_pr"])   # nothing merged yet

    def test_throughput_is_merges_per_utc_hour_with_empty_hours_kept(self):
        self.assertEqual(self.s["throughput"], [{"hour": "2026-09-25T10:00Z", "merged": 3},
                                                {"hour": "2026-09-25T11:00Z", "merged": 2},
                                                {"hour": "2026-09-25T12:00Z", "merged": 0}])

    def test_the_tally_separates_verified_mismatched_and_unread_landings(self):
        self.assertEqual(self.s["tally"], {"verified": 3, "mismatched": 1, "unread": 1})

    def test_the_bisection_tree_follows_family_parents(self):
        trees = self.s["trees"]
        self.assertEqual([t["round"] for t in trees], ["20260925T100000Z"])
        root = trees[0]["roots"][0]
        self.assertEqual((root["id"], root["status"], root["green"]), ("F1", "BISECTED", False))
        self.assertEqual([c["id"] for c in root["children"]], ["F2", "F3"])
        f3 = root["children"][1]
        self.assertEqual([(c["id"], c["status"], c["prs"]) for c in f3["children"]],
                         [("F4", "LANDED", [3]), ("F5", "HELD", [4])])
        self.assertTrue(f3["children"][1]["reused"])

    def test_the_live_queue_reads_the_latest_receipt(self):
        live = self.s["live"]
        self.assertTrue(live["running"])
        self.assertEqual(live["started"], "20260925T120000Z")
        self.assertEqual([(q["position"], q["number"], q["family"], q["state"]) for q in live["queue"]],
                         [(1, 7, "F1", "GATING"), (2, 8, "F1", "GATING"), (3, 9, "F2", "QUEUED"),
                          (4, 10, None, "RETRY")])

    def test_a_finished_latest_receipt_shows_landed_and_held(self):
        live = dashboard.summarize(sample()[1:])["live"]
        self.assertFalse(live["running"])
        self.assertEqual({q["number"]: q["state"] for q in live["queue"]}, {5: "LANDED", 6: "LANDED"})
        live = dashboard.summarize(sample()[1:2])["live"]
        self.assertEqual({q["number"]: (q["state"], q["family"]) for q in live["queue"]},
                         {1: ("LANDED", "F2"), 2: ("LANDED", "F2"), 3: ("LANDED", "F4"), 4: ("HELD", "F5")})

    def test_holds_and_alerts_are_listed_with_their_round(self):
        self.assertEqual(self.s["holds"], [{"number": 4, "reason": "GATE_RED", "detail": "FAILED case-1",
                                            "round": "20260925T100000Z"}])
        self.assertEqual([(a["alert"], a["number"], a["round"]) for a in self.s["alerts"]],
                         [("TREE_MISMATCH", 6, "20260925T110000Z")])

    def test_the_timeline_has_one_bar_per_gate_run(self):
        bars = [b for b in self.s["timeline"] if b["round"] == "20260925T100000Z"]
        self.assertEqual([(b["family"], b["status"]) for b in bars],
                         [("F1", "BISECTED"), ("F2", "LANDED"), ("F3", "BISECTED"), ("F4", "LANDED")])
        f2 = bars[1]
        self.assertEqual((f2["start"], f2["end"], f2["landed"]), (H + 110, H + 160, H + 175))
        self.assertIsNone(bars[0]["landed"])

    def test_a_bisected_half_waits_from_when_its_parent_went_red_not_from_the_round_start(self):
        bars = {b["family"]: b for b in self.s["timeline"] if b["round"] == "20260925T100000Z"}
        self.assertEqual(bars["F1"]["queued"], H)
        self.assertEqual(bars["F3"]["queued"], H + 105)      # F1 gated H+5 .. H+105
        self.assertEqual(bars["F4"]["queued"], H + 210)      # F3 gated H+170 .. H+210

    def test_a_landing_whose_tree_was_never_read_is_shown_unread_not_mismatched(self):
        r = sample()[1]
        r["families"][3]["status"] = "TREE_MISMATCH"
        r["merges"][2]["observed_tree"] = None
        f4 = dashboard.summarize([r])["trees"][0]["roots"][0]["children"][1]["children"][0]
        self.assertEqual((f4["id"], f4["status"]), ("F4", "LANDED_TREE_UNREAD"))

    def test_no_receipts_is_an_empty_summary_not_an_error(self):
        s = dashboard.summarize([])
        self.assertEqual(s["totals"]["rounds"], 0)
        self.assertIsNone(s["totals"]["gates_per_pr"])
        self.assertIsNone(s["live"])


class Site(unittest.TestCase):
    def test_render_is_one_self_contained_page(self):
        page = dashboard.render(dashboard.summarize(sample()))
        self.assertTrue(page.lower().startswith("<!doctype html>"))
        self.assertIsNone(re.search(r"""(src|href)\s*=\s*["']?(https?:)?//""", page))
        self.assertNotIn("@import", page)
        self.assertIn("prefers-color-scheme: dark", page)
        for section in ("queue", "throughput", "gates", "wall", "bisection", "timeline", "holds", "tally"):
            self.assertIn(f'id="{section}"', page)

    def test_embedded_data_cannot_close_the_script(self):
        s = dashboard.summarize(sample())
        s["holds"][0]["detail"] = "</script><img src=x onerror=alert(1)>"
        page = dashboard.render(s)
        self.assertNotIn("</script><img", page)
        match = re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.S)
        self.assertEqual(json.loads(match.group(1))["holds"][0]["detail"], "</script><img src=x onerror=alert(1)>")

    def test_build_reads_a_directory_and_skips_unreadable_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "receipts", Path(tmp) / "site"
            src.mkdir()
            for i, r in enumerate(sample()):
                (src / f"train-{i}.json").write_text(json.dumps(r))
            (src / "train-broken.json").write_text("{not json")
            (src / "train-x.json.tmp").write_text("{}")
            index = dashboard.build(src, out)
            self.assertEqual(index, out / "index.html")
            data = re.search(r'id="data">(.*?)</script>', index.read_text(), re.S).group(1)
            self.assertEqual(json.loads(data)["totals"]["rounds"], 3)
            self.assertEqual(json.loads(data)["skipped"], 1)

    def test_the_cli_needs_no_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "r"
            src.mkdir()
            (src / "train-1.json").write_text(json.dumps(sample()[1]))
            out = io.StringIO()
            with redirect_stdout(out):
                code = cli.main(["--config", str(Path(tmp) / "missing.toml"), "dashboard", "--receipts", str(src),
                                 "--out", str(Path(tmp) / "site")])
            self.assertEqual(code, 0)
            self.assertTrue((Path(tmp) / "site" / "index.html").is_file())
            self.assertIn("index.html", out.getvalue())


if __name__ == "__main__":
    unittest.main()
