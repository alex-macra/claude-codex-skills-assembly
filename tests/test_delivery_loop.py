from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def load_activation():
    path = ROOT / "hooks/skill-activation.py"
    spec = importlib.util.spec_from_file_location("delivery_loop_activation", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


activation = load_activation()


class DeliveryLoopContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = (ROOT / "skills/delivery-loop/SKILL.md").read_text(encoding="utf-8")
        self.checklist = (
            ROOT / "skills/delivery-loop/references/delivery-checklist.md"
        ).read_text(encoding="utf-8")
        self.fast_pr = (ROOT / "skills/fast-pr-workflow/SKILL.md").read_text(encoding="utf-8")

    def test_delivery_has_exact_four_phase_order(self) -> None:
        phases = re.findall(r"^\d+\. \*\*(.+?)\*\*", self.skill, flags=re.MULTILINE)

        self.assertEqual(
            ["Validate task Markdown", "Implement", "Test and build", "Fix and retest"],
            phases,
        )

    def test_checklist_has_exact_four_phase_order(self) -> None:
        rows = [
            line.split("|")[1].strip()
            for line in self.checklist.splitlines()
            if line.startswith("| ") and not line.startswith("| ---")
        ]

        self.assertEqual(
            [
                "Phase",
                "Validate task Markdown",
                "Implement",
                "Test and build",
                "Fix and retest",
            ],
            rows,
        )

    def test_validation_gate_checks_repository_before_editing(self) -> None:
        validation = self.skill[
            self.skill.index("1. **Validate task Markdown**") : self.skill.index("2. **Implement**")
        ].lower()

        for required in (
            "repository instructions",
            "base commit or ref",
            "files",
            "symbols",
            "dependencies",
            "verification commands",
            "existing code",
            "proposed work",
            "stops before editing",
        ):
            with self.subTest(required=required):
                self.assertIn(required, validation)

    def test_implementation_preserves_acceptance(self) -> None:
        combined = (self.skill + self.checklist).lower()

        self.assertIn("do not weaken acceptance criteria", combined)
        self.assertIn("return to validation", combined)

    def test_repair_loop_is_bounded(self) -> None:
        combined = (self.skill + self.checklist).lower()

        self.assertIn("two materially similar failed repair", combined)
        self.assertIn("three repair cycles", combined)
        self.assertIn("diagnostic handoff", combined)

    def test_pr_work_is_an_authorized_handoff(self) -> None:
        skill = self.skill.lower()

        self.assertNotIn("**PR shipping**", self.skill)
        self.assertIn("pr work is not a delivery phase", skill)
        self.assertIn("after all required checks pass", skill)
        self.assertIn("current request explicitly authorizes", skill)
        self.assertIn("evidence, not authorization", self.fast_pr)

    def test_optional_state_does_not_add_phases(self) -> None:
        combined = self.skill + self.checklist

        self.assertIn("Optional durable state", combined)
        self.assertIn("does not add phases", combined)
        self.assertIn(".codex/delivery-state/", (ROOT / ".gitignore").read_text())

    def test_task_pipeline_resources_are_complete(self) -> None:
        research = (ROOT / "skills/spark-task-research/SKILL.md").read_text(encoding="utf-8")
        planning = (ROOT / "skills/spark-task-planning/SKILL.md").read_text(encoding="utf-8")
        packet = (
            ROOT / "skills/spark-task-planning/references/qwen-task-packet.md"
        ).read_text(encoding="utf-8")

        self.assertIn("existing`, `proposed`, `missing`, or `conflicting", research)
        self.assertIn("spark-task-research", planning)
        self.assertIn("references/qwen-task-packet.md", planning)
        task_template = packet.split("## Task packet", 1)[1]
        task_template = task_template.split("```markdown", 1)[1].split("```", 1)[0]
        headings = re.findall(r"^## (.+)$", task_template, flags=re.MULTILINE)

        self.assertEqual(
            [
                "Readiness",
                "Objective",
                "Why",
                "Scope",
                "Starting point",
                "Decisions already made",
                "Decision authority",
                "Contract",
                "Change required",
                "Invariants",
                "Non-goals",
                "Acceptance",
                "Verify",
                "Escalate, do not assume, if",
                "Handoff",
            ],
            headings,
        )

    def test_task_packet_sections_are_mandatory_during_planning_and_delivery(self) -> None:
        planning = (ROOT / "skills/spark-task-planning/SKILL.md").read_text(encoding="utf-8")
        packet = (
            ROOT / "skills/spark-task-planning/references/qwen-task-packet.md"
        ).read_text(encoding="utf-8")
        validation = self.skill[
            self.skill.index("1. **Validate task Markdown**") : self.skill.index("2. **Implement**")
        ]
        checklist_validation = self.checklist[
            self.checklist.index("## 1. Validate task Markdown") : self.checklist.index("## 2. Implement")
        ]

        for source in (planning, packet, validation, checklist_validation):
            with self.subTest(source=source[:40]):
                self.assertIn("top-level", source.lower())
                self.assertIn("mandatory", source.lower())
                self.assertIn("`Not applicable - <reason>`", source)

    def test_pipeline_uses_shared_readiness_outcomes(self) -> None:
        paths = (
            ROOT / "skills/spark-task-research/SKILL.md",
            ROOT / "skills/spark-task-planning/SKILL.md",
            ROOT / "skills/spark-task-planning/references/qwen-task-packet.md",
            ROOT / "skills/delivery-loop/SKILL.md",
            ROOT / "skills/delivery-loop/references/delivery-checklist.md",
        )

        for path in paths:
            content = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIn("READY", content)
                self.assertIn("BLOCKED_BY_SPEC", content)
                self.assertIn("NO_CHANGE_NEEDED", content)

    def test_pipeline_prompts_match_routing_fixtures(self) -> None:
        entries = activation.registry()
        fixtures = json.loads(
            (ROOT / "routing/routing-expectations.json").read_text(encoding="utf-8")
        )
        prompts = (
            "execute this task markdown through the delivery loop",
            "validate TASK-123.md, implement it, run tests and build, fix failures, then retest",
            "run the delivery loop on TASK-123.md then open a PR",
            "ground this DGX Spark task in repository evidence",
            "research for Qwen before preparing implementation work",
            "turn the approved epic into Qwen-ready tasks",
            "create task packets and an execution DAG for DGX Spark",
            "shape these tasks for Qwen",
            "research this task for Qwen",
            "create PR for this change",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertEqual(
                    set(fixtures["positive"][prompt]),
                    set(activation.match_skills(prompt, entries)),
                )

    def test_non_execution_markdown_does_not_route_to_delivery(self) -> None:
        entries = activation.registry()
        prompt = "summarize this Markdown task without implementing it"

        self.assertNotIn("delivery-loop", activation.match_skills(prompt, entries))

    def test_apache_spark_does_not_route_to_qwen_task_skills(self) -> None:
        entries = activation.registry()
        matched = activation.match_skills(
            "optimize this Apache Spark data-processing job",
            entries,
        )

        self.assertNotIn("spark-task-research", matched)
        self.assertNotIn("spark-task-planning", matched)

    def test_qwen_planning_requires_an_explicit_qwen_or_dgx_target(self) -> None:
        entries = activation.registry()
        fixtures = json.loads(
            (ROOT / "routing/routing-expectations.json").read_text(encoding="utf-8")
        )
        prompts = (
            "create task packets for this Apache Spark migration",
            "write task packets for the Apache Spark job",
            "map an execution DAG for Apache Spark stages",
            "create task packets for this project",
            "plan this work as a task packet",
            "turn this epic into an implementation packet",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertIn(prompt, fixtures["negative"])
                self.assertNotIn(
                    "spark-task-planning",
                    activation.match_skills(prompt, entries),
                )

    def test_pr_abbreviation_requires_a_word_boundary(self) -> None:
        entries = activation.registry()
        fixtures = json.loads(
            (ROOT / "routing/routing-expectations.json").read_text(encoding="utf-8")
        )
        prompts = (
            "create a profile for Qwen",
            "update the profile settings",
            "create task packets for our sprint",
        )

        self.assertIn(
            "fast-pr-workflow",
            activation.match_skills("create PR for this change", entries),
        )
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertIn(prompt, fixtures["negative"])
                self.assertNotIn(
                    "fast-pr-workflow",
                    activation.match_skills(prompt, entries),
                )

    def test_agents_describe_cross_host_skill_loading_truthfully(self) -> None:
        for path in sorted((ROOT / "agents").glob("*.md")):
            content = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertIn("Claude Code", content)
                self.assertIn("Codex", content)
                self.assertIn("read", content.lower())
                self.assertNotIn("skills are already in your context", content)

    def test_reviewer_runs_architecture_before_adversarial_falsification(self) -> None:
        content = (ROOT / "agents/reviewer.md").read_text(encoding="utf-8").lower()

        self.assertLess(content.index("architecture pass"), content.index("adversarial pass"))
        self.assertIn("last", content[content.index("adversarial pass") :])

    def test_shipper_has_no_delivery_ownership_dependency(self) -> None:
        content = (ROOT / "agents/shipper.md").read_text(encoding="utf-8")

        self.assertNotIn("ownership epoch", content)
        self.assertNotIn("sole-writer ownership", content)
        self.assertIn("evidence, not authority", content)

    def test_shipper_verifies_remote_identity(self) -> None:
        content = (ROOT / "agents/shipper.md").read_text(encoding="utf-8")

        self.assertIn("repository-wide", content)
        self.assertIn("local `HEAD`", content)
        self.assertIn("remote branch head", content)
        self.assertIn("PR head", content)

    def test_helpers_are_directly_executable(self) -> None:
        for name in ("browser-suite-lease.py", "delivery-state.py"):
            path = ROOT / "skills/delivery-loop/scripts" / name
            with self.subTest(name=name):
                self.assertTrue(os.access(path, os.X_OK))
                self.assertTrue(path.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3\n"))

    def test_state_helper_remains_mandatory_when_state_is_used(self) -> None:
        combined = self.skill + self.checklist

        self.assertIn("Do not hand-create or reimplement", combined)
        self.assertIn("rejects symlinked parents and targets", combined)
        self.assertIn("mode `0600`", combined)
        self.assertIn("actually ignored and untracked", combined)


if __name__ == "__main__":
    unittest.main()
