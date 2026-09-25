"""The pull-request surface: a commit status and a living comment rendered from a plain
event dict, with no git or GitHub dependency. What Train actually posts is exercised in
test_train.py; this covers the rendering and its escaping on its own."""

from __future__ import annotations

import unittest

from svrf import pr_surface as ps


class StatusLines(unittest.TestCase):
    def test_queued_names_position_and_batch(self):
        state, desc = ps.status_line({"number": 12, "phase": "QUEUED", "position": 3, "batch": "F2"})
        self.assertEqual((state, desc), ("pending", "queued (position 3, batch F2)"))

    def test_gating_names_the_other_batch_members_not_itself(self):
        state, desc = ps.status_line({"number": 12, "phase": "GATING", "batch": "F2", "members": [12, 15, 16]})
        self.assertEqual((state, desc), ("pending", "gating batch F2 with #15 #16"))

    def test_gating_with_no_partners_names_none(self):
        state, desc = ps.status_line({"number": 12, "phase": "GATING", "batch": "F2", "members": [12]})
        self.assertEqual((state, desc), ("pending", "gating batch F2"))

    def test_landed_names_the_batch_and_the_gate_duration(self):
        state, desc = ps.status_line({"number": 12, "phase": "LANDED", "batch": "F2", "gate_seconds": 92})
        self.assertEqual((state, desc), ("success", "landed in batch F2 (gate 1m32s)"))

    def test_held_is_a_failure_with_the_one_line_reason(self):
        state, desc = ps.status_line({"number": 12, "phase": "HELD", "reason_line": "conflicts with #7 on x.py"})
        self.assertEqual((state, desc), ("failure", "held: conflicts with #7 on x.py"))

    def test_a_status_description_is_capped_at_140_bytes_and_one_line(self):
        reason = "line one\nline two " + "x" * 300
        _, desc = ps.status_line({"number": 1, "phase": "HELD", "reason_line": reason})
        self.assertNotIn("\n", desc)
        self.assertLessEqual(len(desc), 140)


class Comment(unittest.TestCase):
    def test_the_comment_carries_a_hidden_marker_with_its_own_hash(self):
        body = ps.render_comment({"number": 1, "phase": "QUEUED", "position": 1, "batch": "F1", "members": [1]})
        self.assertTrue(ps.is_surface_comment(body))
        digest = ps.comment_hash(body)
        self.assertIsNotNone(digest)
        self.assertRegex(digest, r"^[0-9a-f]{16}$")

    def test_identical_events_render_the_same_hash_different_ones_do_not(self):
        a = {"number": 1, "phase": "QUEUED", "position": 1, "batch": "F1", "members": [1]}
        b = {"number": 1, "phase": "QUEUED", "position": 2, "batch": "F1", "members": [1]}
        self.assertEqual(ps.comment_hash(ps.render_comment(a)), ps.comment_hash(ps.render_comment(dict(a))))
        self.assertNotEqual(ps.comment_hash(ps.render_comment(a)), ps.comment_hash(ps.render_comment(b)))

    def test_batch_members_and_queue_position_appear_queued(self):
        body = ps.render_comment({"number": 12, "phase": "QUEUED", "position": 4, "batch": "F2",
                                  "members": [12, 15, 16]})
        self.assertIn("Queue position **4**", body)
        self.assertIn("#15", body)
        self.assertIn("#16", body)
        self.assertNotIn("#12", body.split("\n")[0])  # not naming itself as a partner

    def test_the_timeline_marks_reached_phases_and_leaves_the_rest_open(self):
        body = ps.render_comment({"number": 1, "phase": "GATING", "batch": "F1", "history": ["QUEUED"]})
        self.assertIn("✅ queued → ✅ gating → ○ landed/held", body)

    def test_landing_carries_the_proof_badge_and_gate_duration(self):
        body = ps.render_comment({"number": 1, "phase": "LANDED", "batch": "F1", "gate_seconds": 5,
                                  "history": ["QUEUED", "GATING"]})
        self.assertIn("landed tree = gated tree", body)
        self.assertIn("Gate: 5s", body)
        self.assertIn("✅ landed", body)

    def test_held_shows_next_steps_and_a_collapsible_failing_block(self):
        body = ps.render_comment({"number": 1, "phase": "HELD", "failing": ["FAILED test_x", "FAILED test_y"],
                                  "history": ["QUEUED", "GATING"]})
        self.assertIn("**Next:** push a fix", body)
        self.assertIn("<details>", body)
        self.assertIn("</details>", body)
        self.assertIn("FAILED test_x", body)
        self.assertIn("✖️ held", body)

    def test_a_conflict_hold_names_the_partner_and_path(self):
        body = ps.render_comment({"number": 1, "phase": "HELD", "conflict_with": [7], "conflict_paths": ["x.py"],
                                  "reason_line": "conflicts with #7 on x.py"})
        self.assertIn("conflicts with #7 on x.py", body)

    def test_no_failing_lines_means_no_details_block(self):
        body = ps.render_comment({"number": 1, "phase": "HELD", "failing": []})
        self.assertNotIn("<details>", body)


class Escaping(unittest.TestCase):
    """A pull request's title, branch name, and a gate's output are attacker-controlled;
    none of it may open new Markdown structure or raw HTML."""

    def test_markdown_control_characters_are_escaped(self):
        self.assertEqual(ps.escape_md("a*b_c[d](e)|f~g"), r"a\*b\_c\[d\]\(e\)\|f\~g")

    def test_angle_brackets_and_ampersands_cannot_open_raw_html(self):
        escaped = ps.escape_md("<img src=x onerror=alert(1)>&")
        self.assertNotIn("<img", escaped)
        self.assertIn("&lt;img", escaped)
        self.assertIn("&amp;", escaped)

    def test_control_characters_are_stripped_but_ordinary_text_survives(self):
        cleaned = ps.escape_md("a\x1bb\x00c")
        self.assertNotIn("\x1b", cleaned)
        self.assertNotIn("\x00", cleaned)
        self.assertEqual(cleaned, "abc")

    def test_a_link_or_image_cannot_be_formed_from_a_malicious_path(self):
        body = ps.render_comment({"number": 1, "phase": "HELD", "conflict_with": [7],
                                  "conflict_paths": ["evil.py](https://evil.example)"],
                                  "reason_line": "conflicts with #7"})
        self.assertNotIn("](https://evil.example)", body)

    def test_a_conflicting_path_is_escaped_in_the_next_step_line(self):
        body = ps.render_comment({"number": 1, "phase": "HELD", "conflict_with": [7],
                                  "conflict_paths": ["<script>evil.py"],
                                  "reason_line": "conflicts with #7"})
        self.assertNotIn("<script>", body)

    def test_a_run_of_backticks_in_failing_output_cannot_escape_the_fence(self):
        body = ps.render_comment({"number": 1, "phase": "HELD", "failing": ["````injected fence````"]})
        # every fence delimiter is longer than any run of backticks already in the content
        for line in body.splitlines():
            if set(line.strip()) == {"`"}:
                self.assertGreater(len(line.strip()), 4)

    def test_a_held_status_description_has_no_control_characters_or_markdown_is_plain(self):
        _, desc = ps.status_line({"number": 1, "phase": "HELD", "reason_line": "line1\nline2\x1b[31m"})
        self.assertNotIn("\n", desc)
        self.assertNotIn("\x1b", desc)


if __name__ == "__main__":
    unittest.main()
