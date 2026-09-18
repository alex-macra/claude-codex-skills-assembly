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


def public_registry() -> dict:
    return json.loads((ROOT / "routing/skill-rules.json").read_text(encoding="utf-8"))["skills"]


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

    def test_pr_workflow_scopes_each_mutating_action(self) -> None:
        workflow = self.fast_pr.lower()

        for action in (
            "local commit",
            "push",
            "pr creation",
            "pr update",
            "merge",
        ):
            with self.subTest(action=action):
                self.assertIn(f"authorized **{action}**", workflow)

        self.assertIn("authorization for one does not imply any later action", workflow)
        self.assertIn("do not authorize an unrequested commit", workflow)
        self.assertNotIn("and open a pr", workflow)
        self.assertIn("minimum push of the already-validated", workflow)
        self.assertIn("does not authorize creating another commit", workflow)
        self.assertIn("if no push or pr action is also authorized", workflow)
        self.assertIn("do not create or update a pr unless that separate action is authorized", workflow)
        self.assertIn("do not stage, commit, or push repository files", workflow)

    def test_optional_state_does_not_add_phases(self) -> None:
        combined = self.skill + self.checklist

        self.assertIn("Optional durable state", combined)
        self.assertIn("does not add phases", combined)
        self.assertIn(".codex/delivery-state/", (ROOT / ".gitignore").read_text())

    def test_pipeline_prompts_match_routing_fixtures(self) -> None:
        entries = public_registry()
        fixtures = json.loads(
            (ROOT / "routing/routing-expectations.json").read_text(encoding="utf-8")
        )
        prompts = (
            "execute this task markdown through the delivery loop",
            "validate TASK-123.md, implement it, run tests and build, fix failures, then retest",
            "run the delivery loop on TASK-123.md then open a PR",
            "research this task and compare approaches before we build",
            "create PR for this change",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertTrue(activation.match_skills(prompt, entries))
        for prompt, expected in fixtures["positive"].items():
            with self.subTest(prompt=prompt):
                self.assertEqual(set(expected), set(activation.match_skills(prompt, entries)))

    def test_non_execution_markdown_does_not_route_to_delivery(self) -> None:
        entries = public_registry()
        prompt = "summarize this Markdown task without implementing it"

        self.assertNotIn("delivery-loop", activation.match_skills(prompt, entries))

    def test_delivery_loop_rejects_direct_negation(self) -> None:
        entries = public_registry()
        prompts = (
            "Do not run the delivery loop on this task.",
            "Don’t run the delivery loop on this task.",
            "Never use the delivery loop; just explain it.",
            "Do not implement this task packet.",
            "Don’t implement TASK-123.md.",
            "Never execute this task markdown.",
            "Should not implement this task packet.",
            "Do not test, fix, and retest this change.",
            "The docs say implement task packet. Summarize them.",
            "Quote the phrase implement task packet.",
            "Run the delivery loop, but do not run it.",
            "Run the delivery loop. Actually never mind, explain it.",
            "Avoid running the delivery loop; just explain it.",
            "I would rather not implement this task packet.",
            "Before we run the delivery loop, explain what it does.",
            "If we run the delivery loop, explain what it does.",
            "Can you explain how the delivery loop works?",
            "The README contains `validate task markdown` as an example.",
            "Translate: run this through quality.",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertNotIn(
                    "delivery-loop",
                    activation.match_skills(prompt, entries),
                )

    def test_cancellation_only_discards_earlier_scopes(self) -> None:
        entries = public_registry()
        resumptions = {
            "Run the delivery loop on A. Never mind, cancel that. "
            "Run the delivery loop on B.": "delivery-loop",
            "Never mind, cancel that then research this task and compare "
            "approaches before we build.": "task-research",
            "Actually no, cancel that and run the delivery loop on B.": "delivery-loop",
        }
        terminal = (
            "Run the delivery loop. Actually never mind, explain it.",
            "Research this task. Actually never mind, explain it.",
            "Research this task and compare approaches. Actually no, cancel that.",
        )

        for prompt, expected in resumptions.items():
            with self.subTest(prompt=prompt):
                self.assertIn(expected, activation.match_skills(prompt, entries))
        for prompt in terminal:
            with self.subTest(prompt=prompt):
                self.assertEqual([], activation.match_skills(prompt, entries))

    def test_mixed_but_clauses_route_only_the_affirmative_action(self) -> None:
        entries = public_registry()
        cases = {
            "Do not research how this works, but compare approaches before we build.": {
                "task-research"
            },
            "Do not create a PR, but implement this task packet.": {
                "delivery-loop"
            },
            "Do not run the delivery loop but create a PR.": {
                "fast-pr-workflow"
            },
        }

        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(expected, set(activation.match_skills(prompt, entries)))

    def test_research_routing_scopes_negation_to_the_matching_clause(self) -> None:
        entries = public_registry()

        self.assertIn(
            "task-research",
            activation.match_skills(
                "Do not research how this library works. "
                "Research repo B and compare approaches.",
                entries,
            ),
        )
        self.assertNotIn(
            "task-research",
            activation.match_skills("Do not research how this would work.", entries),
        )
        self.assertNotIn(
            "task-research",
            activation.match_skills("I cannot look into the options before we build.", entries),
        )

    def test_research_coordinating_clauses_preserve_the_affirmative_scope(self) -> None:
        entries = public_registry()
        prompts = (
            "Do not research repo A, then research repo B and compare approaches.",
            "Don't forget to research the prior art before we build.",
            "Do not skip researching how this library works.",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertIn("task-research", activation.match_skills(prompt, entries))

    def test_research_negation_idioms_do_not_hide_real_negation(self) -> None:
        entries = public_registry()
        prompts = (
            "Don't research how this would work.",
            "I cannot look into the options before we build.",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertNotIn(
                    "task-research", activation.match_skills(prompt, entries)
                )

    def test_delivery_negation_and_meta_quotes_preserve_later_positive_clauses(self) -> None:
        entries = public_registry()
        prompts = (
            "Do not implement the legacy task packet. "
            "Implement the replacement task packet.",
            "The docs say implement task packet. Now implement this task packet.",
            "Quote the phrase implement task packet. Then implement this task packet.",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertIn(
                    "delivery-loop",
                    activation.match_skills(prompt, entries),
                )

    def test_preference_without_research_and_rejected_instruction_are_not_intents(self) -> None:
        entries = public_registry()

        self.assertEqual(
            [],
            activation.match_skills(
                "I would rather not research how this would work.",
                entries,
            ),
        )
        self.assertEqual(
            [],
            activation.match_skills(
                "Create the task packet without doing research.",
                entries,
            ),
        )
        self.assertEqual(
            [],
            activation.match_skills(
                "The instruction we rejected was: research this before building.",
                entries,
            ),
        )

    def test_pr_abbreviation_requires_a_word_boundary(self) -> None:
        entries = public_registry()
        fixtures = json.loads(
            (ROOT / "routing/routing-expectations.json").read_text(encoding="utf-8")
        )
        prompts = (
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

    def test_fast_pr_rejects_negated_and_meta_mentions(self) -> None:
        entries = public_registry()
        prompts = (
            "Do not create a PR.",
            "Do not open a pull request.",
            "Do not commit this change.",
            "Please do not push branch.",
            "Explain what a pull request is.",
            "The README says create PR for this.",
            "Please refrain from opening a pull request.",
            "Proceed without committing this change.",
            "No need to push branch.",
            "I would rather not create a PR.",
            "If we create a PR, what happens?",
            "Can you tell me whether to create a PR?",
            "Why would we create a PR?",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertNotIn(
                    "fast-pr-workflow",
                    activation.match_skills(prompt, entries),
                )

        for prompt in (
            "Create a PR for this.",
            "Raise a PR for this change.",
            "Submit a PR for this change.",
            "Reuse PR 12.",
        ):
            with self.subTest(prompt=prompt):
                self.assertIn(
                    "fast-pr-workflow",
                    activation.match_skills(prompt, entries),
                )

    def test_fast_pr_exclusions_preserve_other_positive_scopes(self) -> None:
        entries = public_registry()
        prompts = (
            "Do not create a PR for legacy. Create a PR for the replacement.",
            "Create a PR for the replacement. Do not create a PR for legacy.",
            "Explain what a pull request is. Create a PR for the actual change.",
            "The README says create PR for the example. "
            "Create a PR for the actual change.",
            "Create a PR for the actual change. "
            "The README says create PR for the example.",
            "Do not create a PR for legacy but create a PR for the replacement.",
            "Create a PR for the replacement but do not create a PR for legacy.",
            "Explain what a pull request is but create a PR for the actual change.",
            "Create a PR for the actual change but explain what a pull request is.",
            "Please refrain from opening a pull request for legacy. "
            "Create a PR for the actual change.",
            "Create a PR for the actual change but I would rather not create a PR for legacy.",
            "If we create a PR for legacy, what happens? Create a PR for the actual change.",
            "Create a PR for the actual change. Why would we create a PR for legacy?",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertIn(
                    "fast-pr-workflow",
                    activation.match_skills(prompt, entries),
                )

    def test_negative_pull_request_statements_do_not_route(self) -> None:
        entries = public_registry()
        prompts = (
            "I don't want a pull request.",
            "No pull request is needed.",
            "There should be no pull request.",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertNotIn("fast-pr-workflow", activation.match_skills(prompt, entries))

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

    def test_shipper_derives_action_scope_before_remote_work(self) -> None:
        content = (ROOT / "agents/shipper.md").read_text(encoding="utf-8")
        scope = content.index("exact authorized action set")
        remote = content.index("Fetch or query remote")

        self.assertLess(scope, remote)
        for action in ("`commit`", "`push`", "`PR create`", "`PR metadata update`", "`merge`"):
            with self.subTest(action=action):
                self.assertIn(action, content)
        self.assertIn("Authorization for one action does not authorize another", content)
        self.assertIn("only for an authorized push, PR create, PR metadata update, or merge", content)

    def test_shipper_bounds_commit_only_and_metadata_only_actions(self) -> None:
        content = (ROOT / "agents/shipper.md").read_text(encoding="utf-8")
        commit_only = content[
            content.index("For an authorized `commit`") : content.index("For an authorized `push`")
        ]
        metadata_only = content[
            content.index("For an authorized `PR metadata update`") : content.index("For an authorized `merge`")
        ]

        self.assertIn("If `commit` is the only authorized action", commit_only)
        self.assertIn("do not fetch or query remotes, push, create or update a PR, or merge", commit_only)
        self.assertIn("report the local branch and commit, then stop", commit_only)
        self.assertIn("change only the requested", metadata_only)
        self.assertIn("Do not stage, commit, or push repository files", metadata_only)

    def test_shipper_verifies_remote_identity_after_remote_actions(self) -> None:
        content = (ROOT / "agents/shipper.md").read_text(encoding="utf-8")

        self.assertIn("After any remote action", content)
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
