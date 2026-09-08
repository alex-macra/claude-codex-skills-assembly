from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "fast-pr-workflow" / "SKILL.md"


class FastPrPermissionTests(unittest.TestCase):
    def test_shipping_skill_preapproves_only_the_routine_pr_loop(self) -> None:
        frontmatter = SKILL.read_text(encoding="utf-8").split("---", 2)[1]
        tools_line = next(
            line for line in frontmatter.splitlines() if line.startswith("allowed-tools:")
        )
        tools = {item.strip() for item in tools_line.split(":", 1)[1].split(",")}

        required = {
            "Bash(git add:*)",
            "Bash(git commit -m:*)",
            "Bash(git fetch:*)",
            "Bash(git push -u origin HEAD)",
            "Bash(git push origin HEAD)",
            "Bash(gh pr checks:*)",
            "Bash(gh pr create:*)",
            "Bash(gh pr edit:*)",
            "Bash(gh pr view:*)",
        }
        self.assertTrue(required.issubset(tools))
        self.assertNotIn("Bash(git:*)", tools)
        self.assertNotIn("Bash(gh:*)", tools)
        self.assertNotIn("Bash(gh pr:*)", tools)
        self.assertFalse(any("--force" in tool for tool in tools))
        self.assertFalse(any("pr merge" in tool for tool in tools))
        self.assertFalse(any("pr close" in tool for tool in tools))

    def test_shipping_skill_documents_redirection_risk(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("Permission matching includes output redirections", text)
        self.assertIn("permission engine is not an argument sandbox", text)
        self.assertIn("disposable or independently backed-up controller", text)
        self.assertIn("Git does not protect uncommitted files or credentials", text)
        self.assertIn("Do not request or persist broader", text)


if __name__ == "__main__":
    unittest.main()
