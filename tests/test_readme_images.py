"""The README images: generated from docs/BENCHMARK.md and docs/demo.cast, committed, and kept fresh."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from fakes import ROOT


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "demo" / f"{name}.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


images = module("readme_images")
cast = module("cast_to_svg")


class Benchmark(unittest.TestCase):
    def test_the_numbers_are_read_from_the_benchmark_document(self):
        numbers = images.benchmark_numbers((ROOT / "docs" / "BENCHMARK.md").read_text(encoding="utf-8"))
        self.assertEqual(numbers, {"before_per_hour": 5.8, "after_per_hour": 16.3, "before_wall_min": 2.5,
                                   "before_wall_max": 3.5, "after_wall_seconds": 47, "gates_per_pr": 0.79,
                                   "rounds": 17, "merged": 39, "gate_runs": 31, "best_prs": 13, "best_gates": 2,
                                   "best_seconds": 4 * 60 + 46})

    def test_a_changed_benchmark_changes_the_numbers(self):
        text = (ROOT / "docs" / "BENCHMARK.md").read_text(encoding="utf-8").replace("16.3 merged", "17.1 merged")
        self.assertEqual(images.benchmark_numbers(text)["after_per_hour"], 17.1)

    def test_a_benchmark_missing_a_number_is_refused(self):
        with self.assertRaises(ValueError):
            images.benchmark_numbers("nothing here")

    def test_every_image_is_well_formed_and_the_committed_copies_are_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            written = images.main(Path(tmp))
            self.assertGreaterEqual(len(written), 5)
            for path in written:
                ET.fromstring(path.read_text(encoding="utf-8"))
                committed = ROOT / "docs" / "img" / path.name
                self.assertTrue(committed.is_file(), path.name)
                self.assertEqual(committed.read_text(encoding="utf-8"), path.read_text(encoding="utf-8"),
                                 f"docs/img/{path.name} is stale: run `make images`")


class Cast(unittest.TestCase):
    CAST = ('{"version": 2, "width": 40, "height": 5}\n'
            '[0.0, "o", "$ run\\r\\n"]\n'
            '[0.5, "o", "\\u001b[1mbold\\u001b[0m & <more>\\r\\npartial"]\n'
            '[1.0, "o", " line\\r\\n"]\n'
            '[1.2, "i", "ignored"]\n')

    def test_lines_are_timed_by_when_they_finish_and_escapes_are_stripped(self):
        header, lines = cast.parse(self.CAST)
        self.assertEqual(header["width"], 40)
        self.assertEqual(lines, [(0.0, "$ run"), (0.5, "bold & <more>"), (1.0, "partial line")])

    def test_the_svg_is_well_formed_animated_and_escaped(self):
        svg = cast.render(self.CAST)
        root = ET.fromstring(svg)
        self.assertTrue(root.tag.endswith("svg"))
        self.assertIn("@keyframes", svg)
        self.assertIn("bold &amp; &lt;more&gt;", svg)

    def test_the_committed_demo_animation_is_fresh(self):
        text = (ROOT / "docs" / "demo.cast").read_text(encoding="utf-8")
        self.assertEqual((ROOT / "docs" / "img" / "demo.svg").read_text(encoding="utf-8"), cast.render(text))


if __name__ == "__main__":
    unittest.main()
