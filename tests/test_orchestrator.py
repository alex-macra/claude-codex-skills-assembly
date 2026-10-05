from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "skills/orchestrator"
SKILL_MD = SKILL_DIR / "SKILL.md"
SUPERVISE_MD = SKILL_DIR / "references/supervise.md"
CONDUCT_MD = SKILL_DIR / "references/conduct.md"
AGENTS_DIR = ROOT / "agents"
ORCHESTRATOR_AGENT = AGENTS_DIR / "orchestrator.md"
REVIEWER_AGENT = AGENTS_DIR / "reviewer.md"
U3_FILES = (SKILL_MD, SUPERVISE_MD, CONDUCT_MD, ORCHESTRATOR_AGENT, REVIEWER_AGENT)
DASHES_RE = re.compile("[" + chr(0x2013) + chr(0x2014) + "]")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def frontmatter(path: Path) -> dict[str, object]:
    lines = read(path).splitlines()
    assert lines and lines[0] == "---", f"{path} lacks frontmatter"
    end = lines.index("---", 1)
    fields: dict[str, object] = {}
    current: str | None = None
    for line in lines[1:end]:
        if not line:
            continue
        if line[0].isspace():
            if current is not None and line.strip().startswith("- "):
                fields.setdefault(current, [])
                fields[current].append(line.strip()[2:].strip())
            continue
        key, _, value = line.partition(":")
        current = key.strip()
        value = value.strip()
        if value and value[0] in {'"', "'"}:
            value = value[1:-1]
        fields[current] = value if value else []
    return fields


def ordered(haystack: str, *needles: str) -> list[int]:
    return [haystack.index(needle) for needle in needles]


class OrchestratorSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = read(SKILL_MD)
        self.lower = self.skill.lower()
        self.fields = frontmatter(SKILL_MD)

    def test_frontmatter_name_description_and_keys(self) -> None:
        self.assertEqual(self.fields["name"], "orchestrator")
        self.assertEqual(self.fields["license"], "MIT")
        self.assertLessEqual(set(self.fields) - {"metadata"}, {"name", "description", "license"})
        description = self.fields["description"]
        self.assertIsInstance(description, str)
        self.assertLessEqual(len(description), 250)
        for phrase in ("orchestrate", "supervise", "long loop", "keep the loop going"):
            self.assertIn(phrase, description)

    def test_codex_inline_role_sentence_is_in_the_first_lines(self) -> None:
        head = "\n".join(self.skill.splitlines()[:16])
        self.assertIn("On Codex the session takes the orchestrator role itself", head)
        self.assertIn("`SKILL.md`", head)

    def test_three_modes_are_named(self) -> None:
        for mode in ("In-session loop", "Whole session", "Other sessions"):
            self.assertIn(mode, self.skill)

    def test_cadence_names_one_and_five_minutes(self) -> None:
        self.assertIn("1 minute", self.skill)
        self.assertIn("5 minutes", self.skill)

    def test_stall_ladder_order(self) -> None:
        ladder = self.lower[self.lower.index("## stall ladder") :]
        positions = ordered(ladder, "nudge", "shrink", "replace", "block")
        self.assertEqual(positions, sorted(positions))

    def test_halt_inbox_and_state_files_are_named(self) -> None:
        for token in ("`HALT`", "`INBOX.md`", "`STATE.md`"):
            self.assertIn(token, self.skill)
        self.assertIn("~/.local/state/ai-skills/orchestrator/<run-id>/", self.skill)

    def test_never_edits_the_watched_tree(self) -> None:
        self.assertIn("never edit the watched session's tree", self.lower)

    def test_escalates_only_owner_decisions(self) -> None:
        self.assertIn("escalate only owner decisions", self.lower)

    def test_one_open_pr_and_never_merge(self) -> None:
        self.assertIn("one open pr", self.lower)
        self.assertIn("never merge", self.lower)

    def test_long_loop_uses_tracker_next(self) -> None:
        self.assertIn("tracker `next`", self.skill)
        self.assertIn("Never create or edit tracker rows", self.skill)

    def test_references_exist_and_are_linked(self) -> None:
        for path in (SUPERVISE_MD, CONDUCT_MD):
            self.assertTrue(path.is_file(), path)
            self.assertIn(f"(references/{path.name})", self.skill)

    def test_supervise_reference_carries_the_protocols(self) -> None:
        content = read(SUPERVISE_MD)
        for heading in (
            "## Discovery",
            "## Check-in probe",
            "## Cadence",
            "## Stall ladder",
            "## Unblock channels",
            "## INBOX protocol",
            "## Escalation",
            "## Orphan triage",
            "## Detached gates",
            "## Halt",
        ):
            self.assertIn(heading, content)
        self.assertIn("`N. <ISO time> <from>: <text>`", content)
        self.assertIn("`inbox: applied 1-3`", content)
        self.assertIn("`STOP`", content)
        self.assertIn("never approves anything", content)

    def test_conduct_reference_cites_the_tracker_contract(self) -> None:
        content = read(CONDUCT_MD)
        self.assertIn("skills/delivery-loop/references/tracker.md", content)
        self.assertIn("`next --product ROOT --landed <IDs landed this run>`", content)
        for token in ("`DONE <sha> <handoff>`", "`BUDGET <left>`", "`REFUSED <rule>`", "`REPIN ok <tip>`"):
            self.assertIn(token, content)
        self.assertIn("`git cherry-pick -x`", content)
        self.assertIn("## STATE.md", content)


class AgentTests(unittest.TestCase):
    def test_orchestrator_agent_preloads_exactly_orchestrator(self) -> None:
        fields = frontmatter(ORCHESTRATOR_AGENT)
        self.assertEqual(fields["name"], "orchestrator")
        self.assertEqual(fields["skills"], ["orchestrator"])
        self.assertIn("Skill", fields["tools"])
        self.assertIn("maxTurns", fields)
        self.assertLessEqual(len(fields["description"]), 250)
        content = read(ORCHESTRATOR_AGENT).lower()
        self.assertIn("run directory only", content)
        self.assertIn("never edit the watched session's tree", content)
        self.assertIn("never merge", content)

    def test_reviewer_agent_preloads_exactly_three_review_skills(self) -> None:
        fields = frontmatter(REVIEWER_AGENT)
        self.assertEqual(fields["name"], "reviewer")
        self.assertEqual(fields["skills"], ["architect-review", "security-review", "adversarial-review"])
        self.assertIn("Skill", fields["tools"])
        self.assertIn("maxTurns", fields)
        self.assertLessEqual(len(fields["description"]), 250)

    def test_reviewer_runs_architecture_before_adversarial_and_last(self) -> None:
        content = read(REVIEWER_AGENT).lower()
        self.assertLess(content.index("architecture pass"), content.index("adversarial pass"))
        self.assertIn("last", content[content.index("adversarial pass") :])
        self.assertIn("`web-dev` skill", read(REVIEWER_AGENT))

    def test_retired_agents_are_gone(self) -> None:
        self.assertFalse((AGENTS_DIR / "qa.md").exists())
        self.assertFalse((AGENTS_DIR / "shipper.md").exists())
        self.assertEqual(sorted(path.name for path in AGENTS_DIR.glob("*.md")), ["orchestrator.md", "reviewer.md"])

    def test_agents_describe_cross_host_skill_loading_truthfully(self) -> None:
        for path in (ORCHESTRATOR_AGENT, REVIEWER_AGENT):
            content = read(path)
            with self.subTest(path=path.name):
                self.assertIn("Claude Code", content)
                self.assertIn("Codex", content)
                self.assertIn("read", content.lower())
                self.assertNotIn("skills are already in your context", content)


class CapTests(unittest.TestCase):
    CAPS = {
        SKILL_MD: (60, 5_000),
        SUPERVISE_MD: (80, 6_000),
        CONDUCT_MD: (80, 6_000),
        ORCHESTRATOR_AGENT: (20, 2_000),
        REVIEWER_AGENT: (20, 2_000),
    }

    def test_files_stay_within_caps(self) -> None:
        for path, (max_lines, max_bytes) in self.CAPS.items():
            content = read(path)
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertLessEqual(len(content.splitlines()), max_lines)
                self.assertLessEqual(len(content.encode("utf-8")), max_bytes)

    def test_plain_hyphens_only(self) -> None:
        for path in U3_FILES:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIsNone(DASHES_RE.search(read(path)))

    def test_no_absolute_home_paths(self) -> None:
        for path in U3_FILES:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertNotRegex(read(path), r"/(?:home|Users)/")


if __name__ == "__main__":
    unittest.main()
