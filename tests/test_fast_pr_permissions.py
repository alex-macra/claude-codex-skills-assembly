from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "fast-pr-workflow" / "SKILL.md"


class FastPrPermissionTests(unittest.TestCase):
    def test_shipping_skill_has_no_bash_preapprovals(self) -> None:
        frontmatter = SKILL.read_text(encoding="utf-8").split("---", 2)[1]
        self.assertNotIn("allowed-tools:", frontmatter)

    def test_shipping_skill_documents_redirection_risk(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("strips output redirections", text)
        self.assertIn("Every Git and GitHub command uses the normal permission flow", text)
        self.assertIn("Do not persist an always-allow Bash rule", text)


if __name__ == "__main__":
    unittest.main()
