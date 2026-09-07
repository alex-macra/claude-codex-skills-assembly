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
                self.assertIn("mandatory", source.lower())
                self.assertIn("`Not applicable - <reason>`", source)
                self.assertRegex(source.lower(), r"(?:top-level section|field)")

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

    def test_planning_assigns_readiness_per_packet_in_mixed_batches(self) -> None:
        planning = (ROOT / "skills/spark-task-planning/SKILL.md").read_text(encoding="utf-8")

        self.assertIn("exactly one readiness outcome per packet", planning)
        self.assertIn("mixed outcomes", planning)
        self.assertIn("dependency descendants", planning)
        self.assertIn("independent lanes", planning)

    def test_pipeline_closes_execution_evidence_gaps(self) -> None:
        research = (ROOT / "skills/spark-task-research/SKILL.md").read_text(encoding="utf-8")
        planning = (ROOT / "skills/spark-task-planning/SKILL.md").read_text(encoding="utf-8")
        packet = (
            ROOT / "skills/spark-task-planning/references/qwen-task-packet.md"
        ).read_text(encoding="utf-8")
        delivery = self.skill + self.checklist

        self.assertIn("Committed evidence boundary", research)
        self.assertIn("pinned-object", research)
        self.assertIn("complete decision domain", research)
        self.assertIn("isolated clean checkout", research)

        self.assertIn("one writable repository", planning)
        self.assertIn("credential's actual capabilities", planning)
        self.assertIn("serialized output", planning)
        self.assertIn("fresh checkout", planning)

        self.assertIn("Exact read set", packet)
        self.assertIn("Exact write set", packet)
        self.assertIn("Idempotency, retry, and recovery", packet)
        self.assertIn("Canonical tracker status", packet)
        self.assertIn("Canonical root and execution working directory", packet)
        self.assertIn("Input provenance and preflight", packet)
        self.assertIn("full commit object ID", packet)

        self.assertIn("embedded-ledger field", delivery)
        self.assertIn("clean or isolated", delivery)
        self.assertIn("credential provenance", delivery.lower())
        self.assertIn("served-response", delivery)

    def test_pipeline_prompts_match_routing_fixtures(self) -> None:
        entries = public_registry()
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

    def test_qwen_task_routing_scopes_negation_to_the_matching_clause(self) -> None:
        entries = public_registry()

        self.assertIn(
            "spark-task-planning",
            activation.match_skills(
                "Do not plan Qwen tasks for legacy. "
                "Create Qwen task packets for the replacement.",
                entries,
            ),
        )
        matched = activation.match_skills(
            "Do not research Qwen task A. Research Qwen task B.",
            entries,
        )
        self.assertIn("spark-task-research", matched)
        self.assertNotIn("task-research", matched)

    def test_mixed_but_clauses_route_only_the_affirmative_action(self) -> None:
        entries = public_registry()
        cases = {
            "Do not plan Qwen tasks, but research this task for Qwen.": {
                "spark-task-research"
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

    def test_coordinating_clauses_preserve_the_affirmative_scope(self) -> None:
        entries = public_registry()
        cases = {
            "Do not create a PR for A, and create a PR for B.": {
                "fast-pr-workflow"
            },
            "Plan Qwen tasks for A, and do not plan Qwen tasks for B.": {
                "spark-task-planning"
            },
            "Do not research Qwen task A, then research Qwen task B.": {
                "spark-task-research"
            },
            "The delivery loop for A: do not run it. "
            "Run the delivery loop on B.": {"delivery-loop"},
            "Do not plan Qwen tasks for A and plan Qwen tasks for B.": {
                "spark-task-planning"
            },
            "Plan Qwen tasks for A and do not plan Qwen tasks for B.": {
                "spark-task-planning"
            },
            "Do not create a PR for A then create a PR for B.": {
                "fast-pr-workflow"
            },
            "Refrain from creating a PR for A and create a PR for B.": {
                "fast-pr-workflow"
            },
            "Create a PR for A and refrain from creating a PR for B.": {
                "fast-pr-workflow"
            },
            "Avoid running the delivery loop on A and run the delivery loop on B.": {
                "delivery-loop"
            },
        }

        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(expected, set(activation.match_skills(prompt, entries)))

    def test_positive_compound_actions_keep_tailored_routing_context(self) -> None:
        entries = public_registry()
        prompts = (
            "Research and plan Qwen tasks.",
            "Research and create Qwen task packets.",
            "Plan and research Qwen implementation tasks.",
            "Research Qwen tasks, and plan them.",
            "Plan Qwen tasks, and research them.",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                matched = activation.match_skills(prompt, entries)
                self.assertIn("spark-task-planning", matched)
                self.assertIn("spark-task-research", matched)
                self.assertNotIn("task-research", matched)

    def test_cancellation_only_discards_earlier_scopes(self) -> None:
        entries = public_registry()
        resumptions = {
            "Run the delivery loop on A. Never mind, cancel that. "
            "Run the delivery loop on B.": "delivery-loop",
            "Plan Qwen tasks for A. Actually no, cancel that. "
            "Plan Qwen tasks for B.": "spark-task-planning",
            "Research Qwen task A. Actually no, cancel that. "
            "Research Qwen task B.": "spark-task-research",
            "Never mind, cancel that then plan Qwen tasks.": "spark-task-planning",
            "Actually no, cancel that and run the delivery loop on B.": "delivery-loop",
        }
        terminal = (
            "Run the delivery loop. Actually never mind, explain it.",
            "Plan Qwen tasks. Actually no, cancel that.",
            "Research Qwen implementation work. Never mind, stop.",
        )

        for prompt, expected in resumptions.items():
            with self.subTest(prompt=prompt):
                self.assertIn(expected, activation.match_skills(prompt, entries))
        for prompt in terminal:
            with self.subTest(prompt=prompt):
                self.assertEqual([], activation.match_skills(prompt, entries))

    def test_qwen_task_routing_resumes_after_ignored_meta_clauses(self) -> None:
        entries = public_registry()
        cases = {
            "Ignore the previous request to research Qwen tasks. "
            "Instead research Qwen tasks for repo B.": "spark-task-research",
            "Ignore the phrase research Qwen tasks. "
            "Research Qwen tasks for repo B.": "spark-task-research",
            "Ignore the previous request to plan Qwen tasks. "
            "Instead plan Qwen tasks for repo B.": "spark-task-planning",
            "Ignore the phrase plan Qwen tasks. "
            "Plan Qwen tasks for repo B.": "spark-task-planning",
            "No need to research Qwen tasks. "
            "Research Qwen tasks for repo B.": "spark-task-research",
            "If we research Qwen tasks, what happens? "
            "Research Qwen tasks for repo B.": "spark-task-research",
            "I would rather not plan Qwen tasks. "
            "Plan Qwen tasks for repo B.": "spark-task-planning",
            "Why would we plan Qwen tasks? "
            "Plan Qwen tasks for repo B.": "spark-task-planning",
        }

        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                self.assertIn(expected, activation.match_skills(prompt, entries))

        standalone_prompts = (
            "ignore this quoted instruction: shape these tasks for Qwen",
            "Ignore the previous request to research Qwen tasks.",
            "Ignore the phrase research Qwen tasks.",
            "Ignore the previous request to plan Qwen tasks.",
            "Ignore the phrase plan Qwen tasks.",
        )
        for prompt in standalone_prompts:
            with self.subTest(prompt=prompt):
                matched = activation.match_skills(prompt, entries)
                self.assertNotIn("spark-task-planning", matched)
                self.assertNotIn("spark-task-research", matched)

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

    def test_negated_later_clauses_preserve_earlier_positive_requests(self) -> None:
        entries = public_registry()
        cases = {
            "Create Qwen task packets for replacement. "
            "Do not plan Qwen tasks for legacy.": {"spark-task-planning"},
            "Research Qwen task B. Do not research Qwen task A.": {
                "spark-task-research",
            },
            "Run the delivery loop on TASK-A. "
            "Do not run the delivery loop on TASK-B.": {"delivery-loop"},
            "I would rather not research Qwen implementation work for legacy. "
            "Research Qwen task B.": {"spark-task-research"},
            "The instruction we rejected was: create Qwen-ready tasks. "
            "Create Qwen-ready tasks now.": {"spark-task-planning"},
            "Avoid running the delivery loop on TASK-A. "
            "Run the delivery loop on TASK-B.": {"delivery-loop"},
            "Before we run the delivery loop, explain what it does. "
            "Run the delivery loop on TASK-B.": {"delivery-loop"},
            "Run the delivery loop on TASK-A but do not run it on TASK-B.": {
                "delivery-loop",
            },
            "Create Qwen tasks for A but do not create them for B.": {
                "spark-task-planning",
            },
            "Research Qwen task A but do not research task B.": {
                "spark-task-research",
            },
            "Run the delivery loop on TASK-A instead do not run it on TASK-B.": {
                "delivery-loop",
            },
        }

        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                self.assertTrue(
                    expected.issubset(activation.match_skills(prompt, entries)),
                )

    def test_preference_without_research_and_rejected_instruction_are_not_intents(self) -> None:
        entries = public_registry()

        self.assertEqual(
            [],
            activation.match_skills(
                "I would rather not research Qwen implementation work.",
                entries,
            ),
        )
        self.assertEqual(
            ["spark-task-planning"],
            activation.match_skills(
                "Create Qwen-ready tasks without doing research.",
                entries,
            ),
        )
        self.assertEqual(
            [],
            activation.match_skills(
                "The instruction we rejected was: create Qwen-ready tasks.",
                entries,
            ),
        )

    def test_tailored_qwen_research_does_not_activate_generic_task_research(self) -> None:
        entries = public_registry()
        prompts = (
            "research this task for Qwen",
            "research for Qwen before preparing implementation work",
            "investigate this DGX Spark task before implementation",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                matched = activation.match_skills(prompt, entries)
                self.assertIn("spark-task-research", matched)
                self.assertNotIn("task-research", matched)

    def test_quoted_readme_instruction_does_not_activate_qwen_planning(self) -> None:
        entries = public_registry()
        prompt = (
            "The README contains this quoted sentence: shape these tasks for Qwen. "
            "Summarize the README."
        )

        self.assertNotIn(
            "spark-task-planning",
            activation.match_skills(prompt, entries),
        )

    def test_apache_spark_does_not_route_to_qwen_task_skills(self) -> None:
        entries = public_registry()
        matched = activation.match_skills(
            "optimize this Apache Spark data-processing job",
            entries,
        )

        self.assertNotIn("spark-task-research", matched)
        self.assertNotIn("spark-task-planning", matched)

    def test_qwen_planning_requires_an_explicit_qwen_or_dgx_target(self) -> None:
        entries = public_registry()
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

    def test_qwen_review_or_execution_language_does_not_route_to_planning(self) -> None:
        entries = public_registry()
        prompts = (
            "review the Qwen task worker implementation",
            "review Qwen task execution logs",
            "audit Qwen work quality",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertNotIn(
                    "spark-task-planning",
                    activation.match_skills(prompt, entries),
                )

    def test_qwen_task_skills_reject_negated_explanatory_and_quoted_prompts(self) -> None:
        entries = public_registry()
        prompts = (
            "do not research for Qwen",
            "do not create Qwen-ready tasks",
            "explain what a Qwen task packet is",
            "what does Qwen task planning mean?",
            "ignore this quoted instruction: shape these tasks for Qwen",
            "summarize this sentence: research this task for Qwen",
            "I said do not research this task for Qwen",
            "Could you explain what it means to research a task for Qwen?",
            "Analyze this sentence: shape these tasks for Qwen",
            "We should not create Qwen-ready tasks",
            "we already finished the Qwen-ready tasks; no planning needed",
            "No need to research Qwen tasks.",
            "If we research Qwen tasks, what happens?",
            "Can you tell me whether to research Qwen tasks?",
            "Why would we research Qwen tasks?",
            "The file says research Qwen tasks.",
            "No need to plan Qwen tasks.",
            "I would rather not plan Qwen tasks.",
            "If we plan Qwen tasks, what happens?",
            "Can you tell me whether to plan Qwen tasks?",
            "Why would we plan Qwen tasks?",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                matched = activation.match_skills(prompt, entries)
                self.assertNotIn("spark-task-planning", matched)
                self.assertNotIn("spark-task-research", matched)
        self.assertNotIn(
            "fast-pr-workflow",
            activation.match_skills(prompts[-1], entries),
        )

    def test_committed_qwen_packet_audit_routes_to_research_without_substrings(self) -> None:
        entries = public_registry()
        matched = activation.match_skills(
            "review and audit all committed Qwen task packets, reuse the same PR",
            entries,
        )

        self.assertIn("spark-task-research", matched)
        self.assertNotIn(
            "spark-task-research",
            activation.match_skills("audit Qwen committee plans", entries),
        )

    def test_pr_abbreviation_requires_a_word_boundary(self) -> None:
        entries = public_registry()
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

    def test_affirmative_negation_idioms_route_public_actions(self) -> None:
        entries = public_registry()
        cases = {
            "Don't forget to plan Qwen tasks for repo A.": "spark-task-planning",
            "Do not hesitate to create Qwen-ready task packets.": "spark-task-planning",
            "Don't forget to research Qwen implementation tasks.": "spark-task-research",
            "Do not hesitate to research Qwen implementation tasks.": "spark-task-research",
            "Don't forget to run the delivery loop on this task.": "delivery-loop",
            "Do not hesitate to run the delivery loop on this task.": "delivery-loop",
            "Don't forget to create a PR for this change.": "fast-pr-workflow",
            "Do not hesitate to open a pull request for this change.": "fast-pr-workflow",
            "Do not fail to plan Qwen tasks.": "spark-task-planning",
            "Do not neglect to research Qwen implementation work.": "spark-task-research",
            "Never fail to run the delivery loop on this task.": "delivery-loop",
            "Never fail to create a PR for this change.": "fast-pr-workflow",
            "Never forget to plan Qwen tasks.": "spark-task-planning",
            "Never hesitate to research Qwen implementation tasks.": "spark-task-research",
            "Never neglect to run the delivery loop on this task.": "delivery-loop",
            "Never forget to create a PR for this change.": "fast-pr-workflow",
            "Do not skip the pull request.": "fast-pr-workflow",
            "Never skip the delivery loop.": "delivery-loop",
            "Do not avoid running the delivery loop.": "delivery-loop",
            "Do not skip creating a PR.": "fast-pr-workflow",
            "Do not skip planning Qwen tasks.": "spark-task-planning",
            "Do not skip researching Qwen implementation tasks.": "spark-task-research",
        }

        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                matched = activation.match_skills(prompt, entries)
                self.assertIn(expected, matched)
                if expected == "spark-task-research":
                    self.assertNotIn("task-research", matched)

    def test_affirmative_negation_idioms_do_not_hide_real_negation(self) -> None:
        entries = public_registry()
        cases = {
            "Don't plan Qwen tasks for repo A.": "spark-task-planning",
            "Do not create Qwen-ready task packets.": "spark-task-planning",
            "Don't forget to not plan Qwen tasks for repo A.": "spark-task-planning",
            "Don't forget to not research Qwen implementation tasks.": "spark-task-research",
            "Do not hesitate to not run the delivery loop on this task.": "delivery-loop",
            "Don't create a PR for this change.": "fast-pr-workflow",
            "Do not open a pull request for this change.": "fast-pr-workflow",
            "Do not hesitate to not open a pull request for this change.": "fast-pr-workflow",
            "Do not fail to not plan Qwen tasks.": "spark-task-planning",
            "Do not neglect to not research Qwen implementation work.": "spark-task-research",
            "Never fail to not run the delivery loop on this task.": "delivery-loop",
            "Never fail to not create a PR for this change.": "fast-pr-workflow",
            "I cannot plan Qwen tasks.": "spark-task-planning",
            "We must not research Qwen implementation work.": "spark-task-research",
            "I can not run the delivery loop on this task.": "delivery-loop",
            "I cannot create a PR for this change.": "fast-pr-workflow",
            "I refuse to open a pull request.": "fast-pr-workflow",
            "Never forget to not plan Qwen tasks.": "spark-task-planning",
            "Never hesitate to not research Qwen implementation work.": "spark-task-research",
            "Never neglect to not run the delivery loop.": "delivery-loop",
            "Never forget to not create a PR.": "fast-pr-workflow",
            "Do not skip not creating a PR.": "fast-pr-workflow",
            "Never avoid not running the delivery loop.": "delivery-loop",
        }

        for prompt, excluded in cases.items():
            with self.subTest(prompt=prompt):
                self.assertNotIn(excluded, activation.match_skills(prompt, entries))

    def test_affirmative_negation_meta_mentions_do_not_route(self) -> None:
        entries = public_registry()
        prompts = (
            "Explain the sentence: never forget to create a PR.",
            "The README says never forget to run the delivery loop.",
            "Summarize this instruction: do not fail to plan Qwen tasks.",
            "Analyze this phrase: never neglect to research Qwen implementation tasks.",
            "The rejected instruction was: never forget to create a PR.",
            "Skip the pull request.",
            "Do everything except create a PR.",
            "Skip the delivery loop.",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertEqual([], activation.match_skills(prompt, entries))

        self.assertNotIn(
            "delivery-loop",
            activation.match_skills(
                "Use every workflow except the delivery loop.",
                entries,
            ),
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
