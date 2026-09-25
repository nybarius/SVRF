"""The batched train: families folded and gated once, landed in order, the landed tree
checked against the gated tree. Every GitHub, git and gate effect is a fake except the
real-git tests at the end, which run the union step and the landing merge against a bare
origin."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from fakes import UNION, Clock, FakeGate, FakeGitHub, FakeRepo, git, is_union

from svrf import rules
from svrf.errors import RateLimited, ReadFailed, classify_gh_failure
from svrf.gate import MemoryGuard
from svrf.git import RealGit
from svrf.globs import PathSet
from svrf.train import SCHEMA, Train


def train(repo, gh, gate, tmp, clock=None, **kw):
    clock = clock or Clock()
    kw.setdefault("jobs", 1)
    kw.setdefault("family_size", 8)
    return Train(repo, gh, gate, receipts=Path(tmp), clock=clock, sleep=clock.sleep,
                 memory=kw.pop("memory", None), poll_seconds=0, is_union=is_union, **kw)


class PureReads(unittest.TestCase):
    def test_union_lines_keep_base_order_then_the_additions_once(self):
        base = "a\nb\nm\n"
        head = "a\nb\nl\n"
        self.assertEqual(rules.union_lines(theirs=base, ours=head), "a\nb\nm\nl\n")

    def test_a_rate_limit_is_a_read_failure_never_a_conflict(self):
        with self.assertRaises(RateLimited) as caught:
            classify_gh_failure(1, "GraphQL: API rate limit already exceeded for user ID 7.")
        self.assertIsInstance(caught.exception, ReadFailed)
        self.assertNotIn("CONFLICT", caught.exception.reason)
        with self.assertRaises(RateLimited):
            classify_gh_failure(1, "HTTP 403: You have exceeded a secondary rate limit")
        with self.assertRaises(ReadFailed) as other:
            classify_gh_failure(1, "HTTP 502: Bad Gateway")
        self.assertNotIsInstance(other.exception, RateLimited)
        self.assertTrue(other.exception.reason.startswith("GH_FAILED"))

    def test_union_only_conflicts_do_not_separate_and_the_largest_family_is_chosen(self):
        conflicts = [{"a": 1, "b": 2, "paths": [UNION]},
                     {"a": 3, "b": 4, "paths": ["src/x.py"]},
                     {"a": 3, "b": 5, "paths": ["tools/y.py", UNION]}]
        chosen, out = rules.choose_families([1, 2, 3, 4, 5], conflicts, [], is_union)
        self.assertEqual(chosen, [1, 2, 4, 5])
        self.assertEqual(out, {3: {"with": [4, 5], "paths": ["src/x.py", "tools/y.py"]}})

    def test_an_unreadable_pair_separates(self):
        chosen, out = rules.choose_families([1, 2], [], [{"a": 1, "b": 2, "reason": "X"}])
        self.assertEqual(chosen, [1])
        self.assertEqual(out[2]["paths"], ["UNREADABLE:X"])

    def test_families_are_maximal_and_largest_first(self):
        self.assertEqual(rules.families([1, 2, 3], [(1, 2)]), [[1, 3], [2, 3]])
        self.assertEqual(rules.families([], []), [])

    def test_chunks_keep_order(self):
        self.assertEqual(rules.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])

    def test_memory_guard_admits_while_the_budget_holds(self):
        guard = MemoryGuard(need_gb=10, reserve_gb=8, available_gb=lambda: 40, sleep=lambda s: None)
        self.assertTrue(guard.fits(running=0))
        self.assertTrue(guard.fits(running=2))
        self.assertFalse(guard.fits(running=3))


class TrainRuns(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_all_green_lands_every_family_with_one_gate_each(self):
        repo = FakeRepo([11, 12, 13, 14])
        gh, gate = FakeGitHub(repo), FakeGate(repo)
        receipt = train(repo, gh, gate, self.tmp, family_size=2).run([11, 12, 13, 14])
        self.assertEqual(gh.merged, [11, 12, 13, 14])
        self.assertEqual(len(gate.trees), 2)
        self.assertEqual(repo.tree(repo.main), "T0,11,12,13,14")
        self.assertTrue(all(m["identity"] for m in receipt["merges"]))
        self.assertEqual([f["status"] for f in receipt["families"]], ["LANDED", "LANDED"])
        self.assertEqual(receipt["families"][-1]["tree"], repo.tree(repo.main))
        self.assertEqual(receipt["holds"], [])
        self.assertEqual(receipt["alerts"], [])
        self.assertEqual([p[0] for p in repo.pushes], [f"pr-{n}" for n in (11, 12, 13, 14)])
        for n, row in zip((11, 12, 13, 14), receipt["merges"]):
            self.assertEqual(row["number"], n)
            self.assertEqual(len(repo.parents(row["merge"])), 2)

    def test_the_receipt_is_written_under_the_receipts_directory(self):
        repo = FakeRepo([21])
        receipt = train(repo, FakeGitHub(repo), FakeGate(repo), self.tmp).run([21])
        files = list(Path(self.tmp).glob("*.json"))
        self.assertEqual(len(files), 1)
        on_disk = json.loads(files[0].read_text())
        self.assertEqual(on_disk["schema_version"], SCHEMA)
        for key in ("prs", "families", "gates", "merges", "holds", "retry_later", "out", "alerts", "api_calls"):
            self.assertIn(key, on_disk)
        self.assertEqual(receipt["merges"], on_disk["merges"])

    def test_a_red_family_is_bisected_the_culprit_held_and_the_rest_landed_on_gated_trees(self):
        repo = FakeRepo([1, 2, 3, 4, 5, 6])
        gh, gate = FakeGitHub(repo), FakeGate(repo, bad={4})
        receipt = train(repo, gh, gate, self.tmp, family_size=8).run([1, 2, 3, 4, 5, 6])
        self.assertEqual(sorted(gh.merged), [1, 2, 3, 5, 6])
        self.assertEqual([h["number"] for h in receipt["holds"]], [4])
        self.assertEqual(receipt["holds"][0]["reason"], "GATE_RED")
        self.assertIn("FAILED tests/test_lane_4.py::test_it", receipt["holds"][0]["failing"])
        self.assertLess(len(gate.trees), 6 + 1)
        green = {g["tree"] for g in receipt["gates"] if g["green"]}
        for family in receipt["families"]:
            if family["status"] == "LANDED":
                self.assertIn(family["tree"], green)
        self.assertIn(repo.tree(repo.main), green)

    def test_a_rate_limited_snapshot_waits_for_the_reset_and_holds_nothing(self):
        clock = Clock()
        repo = FakeRepo([31, 32])
        gh = FakeGitHub(repo, rate_limited_first=1, clock=clock)
        receipt = train(repo, gh, FakeGate(repo), self.tmp, clock=clock).run([31, 32])
        self.assertEqual(gh.merged, [31, 32])
        self.assertEqual(receipt["holds"], [])
        self.assertGreaterEqual(sum(clock.slept), 60)
        self.assertEqual(receipt["api_calls"], gh.calls)
        self.assertTrue(receipt["rate_waits"][0]["reason"].startswith("RATE_LIMITED:"))

    def test_a_low_rate_budget_pauses_before_the_round(self):
        clock = Clock()
        repo = FakeRepo([33])
        gh = FakeGitHub(repo, clock=clock, remaining=10)

        def refill(seconds, _sleep=clock.sleep):
            _sleep(seconds)
            gh.remaining = 5000
        receipt = Train(repo, gh, FakeGate(repo), receipts=Path(self.tmp), clock=clock, sleep=refill,
                        rate_floor=200, poll_seconds=0).run([33])
        self.assertEqual(gh.merged, [33])
        self.assertEqual(receipt["rate_waits"][0]["reason"], "RATE_FLOOR:graphql:10<200")

    def test_a_failed_merge_read_is_retried_later_not_held(self):
        repo = FakeRepo([41, 42])
        gh = FakeGitHub(repo, merge_failures={41: ReadFailed("GH_FAILED:1:HTTP 502")})
        receipt = train(repo, gh, FakeGate(repo), self.tmp, max_rounds=1).run([41, 42])
        self.assertEqual(receipt["holds"], [])
        self.assertIn(41, [u["number"] for u in receipt["retry_later"]])
        self.assertNotIn(41, gh.merged)

    def test_an_outside_commit_mid_family_stops_the_landing_and_the_rest_is_regated(self):
        repo = FakeRepo([51, 52, 53])
        gh, gate = FakeGitHub(repo, outside_after=51), FakeGate(repo)
        receipt = train(repo, gh, gate, self.tmp).run([51, 52, 53])
        self.assertIn("BASE_MOVED_EXTERNALLY", [a["alert"] for a in receipt["alerts"]])
        self.assertEqual(gh.merged, [51, 52, 53])
        self.assertIn("T0,51,52,53,77", gate.trees)
        self.assertEqual(repo.tree(repo.main), "T0,51,52,53,77")
        self.assertTrue(any(f["status"] == "PREFIX_LANDED_UNGATED" for f in receipt["families"]))

    def test_a_landed_tree_that_is_not_the_gated_tree_alerts_and_stops(self):
        repo = FakeRepo([61, 62])
        gh = FakeGitHub(repo, mismatch_on=61)
        receipt = train(repo, gh, FakeGate(repo), self.tmp).run([61, 62])
        self.assertIn("TREE_MISMATCH", [a["alert"] for a in receipt["alerts"]])
        self.assertEqual(gh.merged, [61])
        self.assertFalse(receipt["merges"][0]["identity"])
        self.assertTrue(receipt["stopped"])

    def test_a_conflict_with_the_base_is_held_and_a_pairwise_conflict_is_out(self):
        repo = FakeRepo([71, 72, 73], conflicts=[((72, 73), ["tools/z.py"])],
                        main_conflicts={71: ["docs/a.md"]})
        gh = FakeGitHub(repo)
        receipt = train(repo, gh, FakeGate(repo), self.tmp).run([71, 72, 73])
        self.assertEqual(gh.merged, [72])
        self.assertEqual(receipt["holds"], [{"number": 71, "reason": "CONFLICT", "paths": ["docs/a.md"],
                                             "failing": []}])
        self.assertEqual(receipt["out"], {"73": {"with": [72], "paths": ["tools/z.py"]}})

    def test_independent_families_gate_in_parallel_within_jobs(self):
        repo = FakeRepo([81, 82, 83, 84])
        gate = FakeGate(repo, delay=0.2)
        train(repo, FakeGitHub(repo), gate, self.tmp, family_size=1, jobs=4).run([81, 82, 83, 84])
        self.assertGreaterEqual(gate.peak, 2)
        self.assertLessEqual(gate.peak, 4)

    def test_the_memory_guard_serializes_gates_when_only_one_fits(self):
        repo = FakeRepo([85, 86, 87])
        gate = FakeGate(repo, delay=0.1)
        guard = MemoryGuard(need_gb=10, reserve_gb=8, available_gb=lambda: 20, sleep=lambda s: time.sleep(0.01))
        train(repo, FakeGitHub(repo), gate, self.tmp, family_size=1, jobs=3, memory=guard).run([85, 86, 87])
        self.assertEqual(gate.peak, 1)

    def test_a_draft_is_marked_ready_before_its_merge(self):
        repo = FakeRepo([91])
        gh = FakeGitHub(repo, drafts={91})
        train(repo, gh, FakeGate(repo), self.tmp).run([91])
        self.assertEqual(gh.readied, [91])
        self.assertEqual(gh.merged, [91])

    def test_dry_run_gates_but_neither_pushes_nor_merges(self):
        repo = FakeRepo([95, 96])
        gh, gate = FakeGitHub(repo), FakeGate(repo)
        receipt = train(repo, gh, gate, self.tmp, dry_run=True).run([95, 96])
        self.assertEqual(gh.merged, [])
        self.assertEqual(repo.pushes, [])
        self.assertEqual(len(gate.trees), 1)
        self.assertEqual(receipt["families"][0]["status"], "GATED_DRY")

    def test_a_gate_that_could_not_run_is_retried_not_held(self):
        repo = FakeRepo([97])

        class Broken:
            def run(self, base, commit, label=""):
                raise OSError("disk gone")
        receipt = train(repo, FakeGitHub(repo), Broken(), self.tmp, max_rounds=1).run([97])
        self.assertEqual(receipt["holds"], [])
        self.assertTrue(receipt["retry_later"][0]["reason"].startswith("GATE_FAILED:OSError"))


class RealGitIdentity(unittest.TestCase):
    """The union step the train gates is the tree a GitHub-style merge commit lands."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.origin = self.tmp / "origin.git"
        self.work = self.tmp / "work"
        self.work.mkdir()
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(self.work, "init", "-q", "-b", "main")
        git(self.work, "remote", "add", "origin", str(self.origin))
        (self.work / UNION).write_text("a\n")
        git(self.work, "add", ".")
        git(self.work, "commit", "-qm", "base")
        git(self.work, "push", "-q", "origin", "HEAD:refs/heads/main")
        base = git(self.work, "rev-parse", "HEAD")
        for lane in ("l1", "l2"):
            git(self.work, "checkout", "-q", "-b", f"work/{lane}", base)
            (self.work / UNION).write_text(f"a\n{lane}\n")
            (self.work / f"{lane}.txt").write_text(lane)
            git(self.work, "add", ".")
            git(self.work, "commit", "-qm", lane)
            git(self.work, "push", "-q", "origin", f"HEAD:refs/heads/work/{lane}")
        git(self.work, "fetch", "-q", "origin")

    def _github_merge(self, branch):
        scratch = self.tmp / "gh"
        if not scratch.exists():
            git(self.tmp, "clone", "-q", str(self.origin), str(scratch))
        git(scratch, "fetch", "-q", "origin")
        git(scratch, "checkout", "-q", "-B", "main", "origin/main")
        git(scratch, "merge", "-q", "--no-ff", "--no-edit", f"origin/{branch}")
        git(scratch, "push", "-q", "origin", "main")
        return git(scratch, "rev-parse", "HEAD")

    def test_landing_by_merge_commits_lands_exactly_the_gated_fold(self):
        g = RealGit(self.work, union=PathSet([UNION]))
        main0 = g.main_sha()
        heads = [git(self.work, "rev-parse", f"origin/work/{lane}") for lane in ("l1", "l2")]
        acc, planned = main0, []
        for head in heads:
            step = g.union_step(acc, head, "preview")
            self.assertEqual(step.status, "CLEAN")
            planned.append(step.tree)
            acc = step.commit
        text = git(self.work, "cat-file", "-p", f"{acc}:{UNION}")
        self.assertEqual(sorted(text.splitlines()), ["a", "l1", "l2"])
        for lane, head, tree in zip(("l1", "l2"), heads, planned):
            prepared = g.union_step(g.main_sha(), head, "Merge main into lane")
            self.assertEqual(prepared.tree, tree)
            g.push_branch(prepared.commit, f"work/{lane}")
            merged = self._github_merge(f"work/{lane}")
            git(self.work, "fetch", "-q", "origin")
            self.assertEqual(g.tree(merged), tree)
            self.assertEqual(g.main_sha(), merged)

    def test_a_conflict_outside_the_union_paths_is_a_conflict(self):
        g = RealGit(self.work, union=PathSet([UNION]))
        base = g.main_sha()
        for lane, text in (("c1", "one"), ("c2", "two")):
            git(self.work, "checkout", "-q", "-b", f"work/{lane}", base)
            (self.work / "shared.txt").write_text(text)
            git(self.work, "add", ".")
            git(self.work, "commit", "-qm", lane)
        first = g.union_step(base, git(self.work, "rev-parse", "work/c1"), "preview")
        second = g.union_step(first.commit, git(self.work, "rev-parse", "work/c2"), "preview")
        self.assertEqual(second.status, "CONFLICT")
        self.assertEqual(second.conflicts, ["shared.txt"])

    def test_the_pair_read_names_conflicting_heads(self):
        g = RealGit(self.work, union=PathSet([UNION]))
        base = g.main_sha()
        heads = {n: git(self.work, "rev-parse", f"origin/work/l{n}") for n in (1, 2)}
        read = g.pairs([{"number": n, "head_sha": h} for n, h in heads.items()], base)
        self.assertEqual(read["read"], 1)
        # both heads append to the union file: git conflicts there, the train does not separate them
        self.assertEqual(read["conflicts"], [{"a": 1, "b": 2, "paths": [UNION]}])
        chosen, out = rules.choose_families([1, 2], read["conflicts"], read["unreadable"], PathSet([UNION]))
        self.assertEqual((chosen, out), ([1, 2], {}))


if __name__ == "__main__":
    unittest.main()
