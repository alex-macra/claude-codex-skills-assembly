from __future__ import annotations

import importlib.util
import json
import os
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

    def test_delivery_phases_keep_review_and_smoke_before_shipping(self) -> None:
        phases = (
            "**Implementation**",
            "**Focused verification**",
            "**Architecture and security review**",
            "**Adversarial review**",
            "**Final smoke**",
            "**PR shipping**",
            "**Remote-head verification**",
            "**Await merge**",
        )

        positions = [self.skill.index(phase) for phase in phases]

        self.assertEqual(positions, sorted(positions))

    def test_delivery_contract_names_single_writer_and_repo_wide_discovery(self) -> None:
        combined = self.skill + self.checklist

        self.assertIn("sole writer", combined)
        self.assertIn("read-only", combined)
        self.assertIn("repository-wide", combined)
        self.assertIn("worktrees", combined)
        self.assertIn("all collaborators are idle", combined)

    def test_resume_contract_fetches_and_checks_drift_before_writing(self) -> None:
        combined = (self.skill + self.checklist).lower()
        resume_rule = combined[combined.index("on resume,") :].splitlines()[0]

        self.assertIn("pause", combined)
        self.assertIn("fetch", resume_rule)
        self.assertIn("drift", resume_rule)
        self.assertLess(resume_rule.index("fetch"), resume_rule.index("writing"))

    def test_delivery_state_template_has_required_fields(self) -> None:
        template = (
            ROOT / "skills/delivery-loop/references/delivery-state-template.md"
        ).read_text(encoding="utf-8")
        required = (
            "Repository",
            "Base",
            "Local head",
            "Remote head",
            "PR head",
            "Tree",
            "Canonical PR",
            "Writer",
            "Ownership epoch",
            "Agents",
            "Processes",
            "Browser policy",
            "Browser lease",
            "Checks",
            "Blockers",
            "Next gate",
        )

        for field in required:
            with self.subTest(field=field):
                self.assertIn(f"- {field}:", template)

        self.assertIn(".codex/delivery-state/<task>.md", self.checklist)
        self.assertIn("mirror", self.checklist.lower())
        self.assertIn(".codex/delivery-state/", (ROOT / ".gitignore").read_text())
        self.assertIn("allowed", self.checklist)
        self.assertIn("forbidden", self.checklist)
        self.assertIn("not-needed", self.checklist)
        self.assertIn("pending", self.checklist)
        self.assertIn("held", self.checklist)
        self.assertIn("contended", self.checklist)

    def test_pause_resume_same_pr_and_multi_agent_prompts_route_to_delivery_loop(self) -> None:
        entries = activation.registry()
        prompts = (
            "pause ongoing work and save the task state",
            "resume this task on the same PR",
            "continue the same pull request",
            "work on these tasks with multiple agents in parallel",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertIn("delivery-loop", activation.match_skills(prompt, entries))

        fixtures = json.loads(
            (ROOT / "routing/routing-expectations.json").read_text(encoding="utf-8")
        )
        for prompt in prompts:
            self.assertIn(prompt, fixtures["positive"])

        self.assertNotIn(
            "delivery-loop",
            activation.match_skills("continue solving the same problem", entries),
        )
        negatives = (
            "Explain multi-agent systems and their history",
            "Continue this branch of the mathematical proof",
            "Do not use multiple agents in parallel",
            "Can you define the phrase resume this task",
        )
        for prompt in negatives:
            with self.subTest(prompt=prompt):
                self.assertIn(prompt, fixtures["negative"])
                self.assertNotIn("delivery-loop", activation.match_skills(prompt, entries))

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

    def test_shipper_verifies_local_remote_and_pr_heads(self) -> None:
        content = (ROOT / "agents/shipper.md").read_text(encoding="utf-8")

        self.assertIn("repository-wide", content)
        self.assertIn("local `HEAD`", content)
        self.assertIn("remote branch head", content)
        self.assertIn("PR head", content)
        self.assertIn("sole-writer ownership", content)
        self.assertIn("ownership epoch", content)
        self.assertNotIn("already committed branch may be pushed", content)

    def test_remote_verification_requires_canonical_pr_identity_and_state(self) -> None:
        combined = self.skill + self.checklist

        self.assertIn("exact repository", combined)
        self.assertIn("exact base ref", combined)
        self.assertIn("exact head ref", combined)
        self.assertIn("OPEN", combined)
        self.assertIn("exactly one canonical PR", combined)
        self.assertIn("shipping freeze", combined)

    def test_helpers_are_directly_executable(self) -> None:
        for name in ("browser-suite-lease.py", "delivery-state.py"):
            path = ROOT / "skills/delivery-loop/scripts" / name
            with self.subTest(name=name):
                self.assertTrue(os.access(path, os.X_OK))
                self.assertTrue(path.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3\n"))

    def test_delivery_state_helper_is_mandatory_for_private_state(self) -> None:
        combined = self.skill + self.checklist

        self.assertIn("do not hand-create or reimplement", combined)
        self.assertIn("rejects symlinked parents and targets", combined)
        self.assertIn("mode `0600`", combined)
        self.assertIn("actually ignored and untracked", combined)


if __name__ == "__main__":
    unittest.main()
