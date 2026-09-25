"""`svrf replay`: reconstruct an already-merged pull request's head and the base it
merged onto from its own merge commit, and run admission and planning (optionally the
gate) against that historical snapshot with a local stand-in for GitHub. Nothing here
lands: replay never pushes, merges, or comments."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fakes import git

from svrf import replay
from svrf.config import from_dict
from svrf.git import RealGit


class FakeHub:
    """Only what `reconstruct` needs from a hub: a merge commit sha per number."""

    def __init__(self, merges):
        self.merges = dict(merges)

    def merge_commit(self, number):
        return self.merges.get(number)


class Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.origin = self.tmp / "origin.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.work = self.tmp / "work"
        self.work.mkdir()
        git(self.work, "init", "-q", "-b", "main")
        git(self.work, "remote", "add", "origin", str(self.origin))
        (self.work / "a.txt").write_text("0\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-qm", "base")
        git(self.work, "push", "-q", "origin", "HEAD:refs/heads/main")
        self.git = RealGit(self.work)

    def merge(self, number: int, path: str, text: str) -> tuple[str, str, str]:
        """A feature branch off the current main, merged with an ordinary (non-fast-forward)
        merge commit, pushed to origin -- exactly GitHub's "Create a merge commit" shape.
        Returns (base_sha, head_sha, merge_sha)."""
        base = git(self.work, "rev-parse", "main")
        git(self.work, "checkout", "-q", "-b", f"feature-{number}", "main")
        (self.work / path).write_text(text)
        git(self.work, "add", "-A")
        git(self.work, "commit", "-qm", f"feat: {number}")
        head = git(self.work, "rev-parse", "HEAD")
        git(self.work, "checkout", "-q", "main")
        git(self.work, "merge", "-q", "--no-ff", "--no-edit", f"feature-{number}")
        merged = git(self.work, "rev-parse", "HEAD")
        git(self.work, "push", "-q", "origin", "HEAD:refs/heads/main")
        return base, head, merged


class Reconstruct(Repo):
    def test_reconstructs_base_and_head_from_the_merge_commits_two_parents(self):
        base, head, merged = self.merge(101, "one.txt", "1\n")
        found, problems = replay.reconstruct(self.git, FakeHub({101: merged}).merge_commit, [101])
        self.assertEqual(problems, {})
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].number, found[0].base_sha, found[0].head_sha, found[0].merge_sha),
                         (101, base, head, merged))

    def test_a_number_never_merged_is_a_problem_not_a_guess(self):
        found, problems = replay.reconstruct(self.git, FakeHub({}).merge_commit, [202])
        self.assertEqual(found, [])
        self.assertEqual(problems, {202: "NOT_MERGED"})

    def test_a_commit_with_the_wrong_parent_count_is_reported_not_guessed(self):
        root = git(self.work, "rev-list", "--max-parents=0", "HEAD")
        found, problems = replay.reconstruct(self.git, FakeHub({303: root}).merge_commit, [303])
        self.assertEqual(found, [])
        self.assertIn("NOT_AN_ORDINARY_MERGE", problems[303])


def config(clone: Path, receipts: Path, *, gate_commands=None) -> object:
    return from_dict({
        "repo": "replay/local", "base": "main", "clone": str(clone), "state_dir": str(receipts),
        "gate": {"commands": gate_commands or ["true"]},
        "train": {"family_size": 8, "jobs": 1, "rate_floor": 0},
    })


class FullReplay(Repo):
    def test_stage_refuses_mismatched_bases_without_an_explicit_base(self):
        _, _, m1 = self.merge(401, "one.txt", "1\n")
        _, _, m2 = self.merge(402, "two.txt", "2\n")
        found, _ = replay.reconstruct(self.git, FakeHub({401: m1, 402: m2}).merge_commit, [401, 402])
        with self.assertRaises(replay.ReplayError):
            replay.run(config(self.work, self.tmp / "state"), found, base=None)

    def test_two_non_conflicting_replays_land_in_one_family_under_a_shared_base(self):
        base1, _, m1 = self.merge(501, "one.txt", "1\n")
        _, _, m2 = self.merge(502, "two.txt", "2\n")
        found, problems = replay.reconstruct(self.git, FakeHub({501: m1, 502: m2}).merge_commit, [501, 502])
        self.assertEqual(problems, {})
        report = replay.run(config(self.work, self.tmp / "state"), found, base=base1)
        self.assertEqual(report["admission"][501]["decision"], "ADMIT")
        self.assertEqual(report["admission"][502]["decision"], "ADMIT")
        self.assertEqual(report["out"], {})
        self.assertEqual(len(report["families"]), 1)
        self.assertEqual(sorted(report["families"][0]["prs"]), [501, 502])
        self.assertEqual(report["gates"], [])

    def test_a_conflicting_pair_is_left_out_by_planning(self):
        # Both branches from the same starting point, each with a synthetic (plumbing)
        # merge commit onto it -- exactly the two-parent shape a real merge commit has,
        # without needing git to actually reconcile them against each other, which their
        # own content, by construction, refuses.
        base1 = git(self.work, "rev-parse", "main")
        git(self.work, "checkout", "-q", "-b", "feature-601", "main")
        (self.work / "shared.txt").write_text("from 601\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-qm", "feat: 601")
        head1 = git(self.work, "rev-parse", "HEAD")
        git(self.work, "checkout", "-q", "-b", "feature-602", "main")
        (self.work / "shared.txt").write_text("from 602\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-qm", "feat: 602")
        head2 = git(self.work, "rev-parse", "HEAD")
        tree1 = git(self.work, "rev-parse", f"{head1}^{{tree}}")
        tree2 = git(self.work, "rev-parse", f"{head2}^{{tree}}")
        m1 = git(self.work, "commit-tree", tree1, "-p", base1, "-p", head1, "-m", "merge 601")
        m2 = git(self.work, "commit-tree", tree2, "-p", base1, "-p", head2, "-m", "merge 602")
        found, _ = replay.reconstruct(self.git, FakeHub({601: m1, 602: m2}).merge_commit, [601, 602])
        report = replay.run(config(self.work, self.tmp / "state"), found, base=base1)
        self.assertEqual(len(report["families"]), 1)
        kept = report["families"][0]["prs"]
        left_out = [n for n in (601, 602) if n not in kept]
        self.assertEqual(len(left_out), 1)
        self.assertIn(left_out[0], report["out"])

    def test_gate_flag_runs_the_configured_gate_command(self):
        base1, _, m1 = self.merge(701, "one.txt", "1\n")
        found, _ = replay.reconstruct(self.git, FakeHub({701: m1}).merge_commit, [701])
        report = replay.run(config(self.work, self.tmp / "state", gate_commands=["true"]), found, base=base1,
                            gate=True)
        self.assertEqual(len(report["gates"]), 1)
        self.assertTrue(report["gates"][0]["green"])

    def test_a_carried_head_reads_already_merged_not_admit(self):
        # Replay against a base that already contains the reconstructed head (as if this
        # round ran after some other path had already landed it): the admission check's
        # own ancestor read reports it LANDED, exactly the live daemon's CARRIED case.
        base1, head1, m1 = self.merge(801, "one.txt", "1\n")
        current_main = git(self.work, "rev-parse", "main")
        found, _ = replay.reconstruct(self.git, FakeHub({801: m1}).merge_commit, [801])
        report = replay.run(config(self.work, self.tmp / "state"), found, base=current_main)
        self.assertEqual(report["admission"][801]["decision"], "ALREADY_MERGED")


if __name__ == "__main__":
    unittest.main()
