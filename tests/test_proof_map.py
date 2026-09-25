"""Every decision rule names the Lean theorem that states it and the code that enforces
it, and both exist; proofs/README.md lists every rule."""

from __future__ import annotations

import re
import unittest

from fakes import ROOT

from svrf import rules
from svrf.train import Train


class ProofMap(unittest.TestCase):
    def lean_text(self) -> str:
        return "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "proofs" / "BraidedTrain").glob("*.lean"))

    def test_every_rule_names_a_lean_statement_that_exists(self):
        text = self.lean_text()
        for name, rule in rules.RULES.items():
            pattern = rf"^(?:theorem|def)\s+{re.escape(rule['lean'])}\b"
            self.assertRegex(text, re.compile(pattern, re.MULTILINE), name)

    def test_every_rule_names_code_that_exists(self):
        for name, rule in rules.RULES.items():
            check = rule["check"]
            if check.startswith("Train."):
                self.assertTrue(callable(getattr(Train, check.split(".", 1)[1], None)), name)
            else:
                self.assertTrue(callable(getattr(rules, check, None)), name)

    def test_the_proofs_readme_maps_every_rule(self):
        readme = (ROOT / "proofs" / "README.md").read_text(encoding="utf-8")
        for name, rule in rules.RULES.items():
            self.assertIn(f"`{name}`", readme, name)
            self.assertIn(f"`{rule['lean']}`", readme, name)

    def test_no_proof_is_left_open(self):
        text = self.lean_text()
        self.assertNotRegex(text, r"\bsorry\b")
        self.assertNotIn("axiom ", text)


if __name__ == "__main__":
    unittest.main()
