from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PHASES = (
    "Validate task Markdown",
    "Implement",
    "Test and build",
    "Fix and retest",
    "Architecture and adversarial review",
    "Final smoke",
    "Commit, push, and open PR",
    "Verify remote handoff",
)
PHASE_SKILLS = {
    "Validate task Markdown": ("task-research",),
    "Implement": ("web-dev",),
    "Test and build": ("qa-automation",),
    "Fix and retest": ("qa-automation",),
    "Architecture and adversarial review": (
        "architect-review",
        "adversarial-review",
        "security-review",
    ),
    "Final smoke": ("see-it-live",),
    "Commit, push, and open PR": ("fast-pr-workflow",),
    "Verify remote handoff": ("fast-pr-workflow",),
}
TRACKER_VERBS = ("next", "claim", "checkpoint", "review", "finish")
REMOVED_NAMES = (
    "a11y-audit",
    "automation",
    "code-comments",
    "code-reuse",
    "e2e-qa",
    "web-dev-backend",
    "web-dev-frontend",
    "shipper",
    "qa",
)


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


def phase_blocks(skill: str) -> dict[str, str]:
    body = skill[skill.index("## Eight phases") :]
    body = body[: body.index("\n## ", 1)]
    matches = list(re.finditer(r"^\d+\. \*\*(.+?)\*\*", body, flags=re.MULTILINE))
    return {
        match.group(1): body[match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(body)]
        for index, match in enumerate(matches)
    }


def section(text: str, heading: str) -> str:
    start = text.index(f"\n## {heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else len(text)]


def frontmatter_description(text: str) -> str:
    line = next(line for line in text.splitlines() if line.startswith("description:"))
    return ast.literal_eval(line.split(":", 1)[1].strip())


def tracker_stub(reference: str) -> str:
    start = reference.rindex("```sh\n") + len("```sh\n")
    return reference[start : reference.index("```", start)]


class DeliveryLoopContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = (ROOT / "skills/delivery-loop/SKILL.md").read_text(encoding="utf-8")
        self.checklist = (
            ROOT / "skills/delivery-loop/references/delivery-checklist.md"
        ).read_text(encoding="utf-8")
        self.fast_pr = (ROOT / "skills/fast-pr-workflow/SKILL.md").read_text(encoding="utf-8")
        self.tracker = (ROOT / "skills/delivery-loop/references/tracker.md").read_text(
            encoding="utf-8"
        )

    def test_delivery_has_exact_eight_phase_order(self) -> None:
        phases = re.findall(r"^\d+\. \*\*(.+?)\*\*", self.skill, flags=re.MULTILINE)

        self.assertEqual(list(PHASES), phases)

    def test_checklist_has_exact_eight_phase_order(self) -> None:
        rows = [
            line.split("|")[1].strip()
            for line in self.checklist.splitlines()
            if line.startswith("| ") and not line.startswith("| ---")
        ]
        sections = re.findall(r"^## \d+\. (.+)$", self.checklist, flags=re.MULTILINE)

        self.assertEqual(["Phase", *PHASES], rows)
        self.assertEqual(list(PHASES), sections)

    def test_checklist_evidence_block_covers_shipping_and_tracking(self) -> None:
        block = self.checklist[self.checklist.index("```markdown") : self.checklist.index("## Phase contract")]

        for field in (
            "Review verdicts:",
            "Final smoke:",
            "Branch and commit:",
            "Pull request:",
            "Tracker lines",
        ):
            with self.subTest(field=field):
                self.assertIn(field, block)

    def test_each_phase_names_its_sibling_skill(self) -> None:
        blocks = phase_blocks(self.skill)
        rows = {
            line.split("|")[1].strip(): line.split("|")[2]
            for line in self.checklist.splitlines()
            if line.startswith("| ") and not line.startswith("| ---")
        }

        self.assertEqual(set(PHASES), set(PHASE_SKILLS))
        for phase, names in PHASE_SKILLS.items():
            for name in names:
                with self.subTest(phase=phase, name=name):
                    self.assertIn(f"`{name}`", blocks[phase])
                    self.assertIn(f"`{name}`", rows[phase])
        review = blocks["Architecture and adversarial review"]
        self.assertLess(review.index("`architect-review`"), review.index("`adversarial-review`"))

    def test_named_sibling_skills_exist_in_the_catalog(self) -> None:
        catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
        names = {name for names in PHASE_SKILLS.values() for name in names} | {"orchestrator"}

        for name in sorted(names):
            with self.subTest(name=name):
                self.assertTrue((ROOT / "skills" / name / "SKILL.md").is_file())
                self.assertIn(name, catalog["skills"])

    def test_contract_skills_name_no_removed_skill_or_agent(self) -> None:
        combined = self.skill + self.checklist + self.tracker + self.fast_pr

        for name in REMOVED_NAMES:
            with self.subTest(name=name):
                self.assertNotIn(f"`{name}`", combined)
        self.assertNotIn("shipper", combined.lower())

    def test_contract_files_fit_their_caps(self) -> None:
        caps = {
            "skills/delivery-loop/SKILL.md": (80, 7_000),
            "skills/fast-pr-workflow/SKILL.md": (80, 7_000),
            "skills/delivery-loop/references/delivery-checklist.md": (80, 6_000),
            "skills/delivery-loop/references/tracker.md": (40, 6_000),
        }

        for relative, (max_lines, max_bytes) in caps.items():
            path = ROOT / relative
            with self.subTest(path=relative):
                self.assertLessEqual(len(path.read_text(encoding="utf-8").splitlines()), max_lines)
                self.assertLessEqual(path.stat().st_size, max_bytes)
        for text in (self.skill, self.fast_pr):
            with self.subTest(description=frontmatter_description(text)[:40]):
                self.assertLessEqual(len(frontmatter_description(text)), 250)

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

    def test_delivery_loop_owns_the_shipping_bundle(self) -> None:
        skill = self.skill.lower()
        workflow = self.fast_pr.lower()

        self.assertIn("**commit, push, and open pr**", skill)
        self.assertIn("explicit request to run this delivery loop", skill)
        self.assertIn("commit the completed diff", skill)
        self.assertIn("create or update exactly one pull request", skill)
        self.assertIn("never authorizes a merge", skill)
        self.assertIn("explicit request to run `delivery-loop`", workflow)
        self.assertIn("one topic-branch commit, push, and canonical pr", workflow)
        self.assertIn("bundle never includes merge", workflow)
        self.assertNotIn("PR work belongs to", frontmatter_description(self.skill))

    def test_orchestrator_bundle_needs_an_explicit_run_request(self) -> None:
        orchestrator = (ROOT / "skills/orchestrator/SKILL.md").read_text(encoding="utf-8")
        conduct = (ROOT / "skills/orchestrator/references/conduct.md").read_text(encoding="utf-8")

        self.assertIn(
            "An explicit request to run `delivery-loop` or the orchestrator on named packets or a tracker queue "
            "authorizes the shipping bundle per task",
            orchestrator,
        )
        self.assertIn("stops each task at the builder commit and reports", orchestrator)
        self.assertNotIn("The request that starts the run authorizes", orchestrator)
        self.assertIn("otherwise stop at the builder commit and report", section(conduct, "Landing"))
        self.assertIn("a conductor landing a builder commit under that request uses it too", self.fast_pr)
        self.assertIn("General requests to ship, release, finish", self.fast_pr)

    def test_delivery_bundle_can_be_explicitly_narrowed(self) -> None:
        combined = (self.skill + self.checklist + self.fast_pr).lower()

        self.assertIn("do not push", combined)
        self.assertIn("no pr", combined)
        self.assertIn("explicit exclusion", combined)
        self.assertIn("a pull request cannot proceed without a remote branch", combined)

    def test_handoff_puts_the_pr_url_on_its_own_line(self) -> None:
        handoff = section(self.skill, "Handoff")

        self.assertIn("full pull-request URL on its own line", handoff)
        self.assertIn("Merge remains separate", handoff)
        self.assertIn("`tracker: none`", handoff)
        self.assertIn("inbox: applied", handoff)

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

    def test_skill_names_the_tracker_contract(self) -> None:
        tracker_section = section(self.skill, "Task tracker (optional)")

        for verb in TRACKER_VERBS:
            with self.subTest(verb=verb):
                self.assertIn(f"`{verb}`", tracker_section)
        self.assertIn("~/.config/ai-skills/task-tracker", tracker_section)
        self.assertIn("exit 3", tracker_section.lower())
        self.assertIn("`tracker: none`", tracker_section)
        self.assertIn("`Task: <ID>`", tracker_section)
        self.assertIn("`skipped`", tracker_section)
        self.assertIn("separately authorized merge", tracker_section)
        self.assertIn("[references/tracker.md](references/tracker.md)", tracker_section)

    def test_tracker_reference_documents_the_contract(self) -> None:
        for verb in TRACKER_VERBS:
            with self.subTest(verb=verb):
                self.assertIn(f"| `{verb}`", self.tracker)
        for flag in (
            "--task ID",
            "--product ROOT",
            "--run-id RUN",
            "--executor claude-code|codex",
            "--dry-run",
            "--landed",
            "--limit",
            "--packet",
            "--phase",
            "--outcome",
            "--evidence",
            "--next-gate",
            "--pr",
        ):
            with self.subTest(flag=flag):
                self.assertIn(flag, self.tracker)
        for word in (
            "`intake`",
            "`research`",
            "`build`",
            "`verify`",
            "`shipping`",
            "`complete`",
            "`blocked`",
            "`running`",
            "`passed`",
            "`failed`",
            "`NEXT none`",
            "`tracker: none`",
            "`Task: <ID>`",
            "Exit 3",
            "`skipped`",
            "360000",
            "no interpreter prefix",
            "`[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+`",
            "`^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`",
            "never runs Git writes",
        ):
            with self.subTest(word=word):
                self.assertIn(word, self.tracker)

    def test_tracker_stub_answers_every_documented_call_shape(self) -> None:
        stub = tracker_stub(self.tracker)
        self.assertEqual(11, len(stub.splitlines()))
        self.assertTrue(stub.startswith("#!/bin/sh\n"))

        with tempfile.TemporaryDirectory() as home:
            config = Path(home) / ".config/ai-skills"
            config.mkdir(parents=True)
            adapter = config / "task-tracker"
            adapter.write_text(stub, encoding="utf-8")
            adapter.chmod(0o755)
            product = str(Path(home) / "product")
            url = "https://github.com/OWNER/NAME/pull/7"
            common = [
                "--task", "ABC-12", "--product", product,
                "--run-id", "run-1", "--executor", "claude-code",
            ]
            environment = {"HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin")}

            def call(*arguments: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [str(adapter), *arguments],
                    capture_output=True,
                    text=True,
                    env=environment,
                    timeout=30,
                    check=False,
                )

            listed = call("next", "--product", product, "--landed", "ABC-11", "--limit", "5")
            self.assertEqual((0, "NEXT none\n"), (listed.returncode, listed.stdout))

            writes = {
                "claim": ["--packet", str(Path(home) / "packet.md")],
                "checkpoint": [
                    "--phase", "verify", "--outcome", "passed",
                    "--evidence", "tests: 12 passed", "--next-gate", "review",
                ],
                "review": ["--pr", url, "--evidence", "head abc123"],
                "finish": ["--pr", url, "--evidence", "merge abc123"],
            }
            for verb, extra in writes.items():
                for dry_run in ([], ["--dry-run"]):
                    with self.subTest(verb=verb, dry_run=bool(dry_run)):
                        result = call(verb, *common, *extra, *dry_run)
                        self.assertEqual(0, result.returncode)
                        prefix = "dry-run" if dry_run else "recorded"
                        self.assertEqual([f"{prefix} {verb} ABC-12 run-1"], result.stdout.splitlines())

            (config / "task-tracker.held").touch()
            held = call("claim", *common)
            self.assertEqual((3, "held ABC-12\n"), (held.returncode, held.stdout))
            listed_while_held = call("next", "--product", product)
            self.assertEqual((0, "NEXT none\n"), (listed_while_held.returncode, listed_while_held.stdout))

            log = (config / "task-tracker.log").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(writes) + 1, len(log))
            self.assertFalse(any(line.startswith("next") or "--dry-run" in line for line in log))
            self.assertTrue(log[0].startswith("claim --task ABC-12"))
            self.assertIn("--run-id run-1", log[0])

    def test_delivery_loop_points_several_packets_at_the_orchestrator(self) -> None:
        self.assertIn("`orchestrator`", self.skill)
        self.assertIn("never execute a packet's phases in your own context", self.skill)

    def test_supervised_run_reads_inbox_and_halt(self) -> None:
        supervised = section(self.skill, "Supervised run")

        for phrase in (
            "`<run dir>/INBOX.md`",
            "every phase boundary",
            "before shipping",
            "numbered amendments",
            "refuse and report",
            "widens Git or publication authority",
            "weakens a test",
            "`STOP`",
            "`<run dir>/HALT`",
            "returns the checkpoint fields",
            "conductor call the tracker",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, supervised)

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

    def test_fast_pr_treats_handoffs_as_evidence(self) -> None:
        self.assertNotIn("ownership epoch", self.fast_pr)
        self.assertNotIn("sole-writer ownership", self.fast_pr)
        self.assertIn("evidence, not authorization", self.fast_pr)

    def test_fast_pr_derives_action_scope_before_remote_work(self) -> None:
        scope = self.fast_pr.index("exact authorized action set")
        remote = self.fast_pr.index("Fetch or query remote")

        self.assertLess(scope, remote)
        for action in ("`commit`", "`push`", "`PR create`", "`PR metadata update`", "`merge`"):
            with self.subTest(action=action):
                self.assertIn(action, self.fast_pr)
        self.assertIn("Authorization for one does not imply any later action", self.fast_pr)
        self.assertIn("only for an authorized push, PR create, PR metadata update, or merge", self.fast_pr)

    def test_fast_pr_bounds_commit_only_and_metadata_only_actions(self) -> None:
        commit_only = self.fast_pr[
            self.fast_pr.index("For an authorized **local commit**") : self.fast_pr.index("For an authorized **push**")
        ]
        metadata_only = self.fast_pr[
            self.fast_pr.index("For an authorized **PR update**") : self.fast_pr.index("For an authorized **merge**")
        ]

        self.assertIn("If `commit` is the only authorized action", commit_only)
        self.assertIn("do not fetch or query remotes, push, create or update a PR, or merge", commit_only)
        self.assertIn("report the local branch and commit, then stop", commit_only)
        self.assertIn("change only the requested", metadata_only)
        self.assertIn("Do not stage, commit, or push repository files", metadata_only)

    def test_fast_pr_verifies_remote_identity_after_remote_actions(self) -> None:
        self.assertIn("After any remote action", self.fast_pr)
        self.assertIn("local `HEAD`", self.fast_pr)
        self.assertIn("remote branch head", self.fast_pr)
        self.assertIn("PR head", self.fast_pr)

    def test_fast_pr_stops_and_reports_a_stale_base(self) -> None:
        self.assertIn(
            "`gh api repos/{owner}/{repo}/compare/{base}...{headSha} --jq .behind_by`",
            self.fast_pr,
        )
        self.assertIn("stop and report it", self.fast_pr)
        self.assertIn("Syncing the branch is a separately authorized action", self.fast_pr)
        self.assertNotIn("origin/<base>` into the head", self.fast_pr)

    def test_fast_pr_keeps_the_protected_set_and_guard_override(self) -> None:
        self.assertEqual(2, self.fast_pr.count("`main`, `master`, `develop`"))
        self.assertNotIn("ordinary integration branches", self.fast_pr)
        self.assertIn("mechanically enforced when the guard hooks are installed", self.fast_pr)
        self.assertIn("`AI_SKILLS_ALLOW_PROTECTED=1`", self.fast_pr)
        self.assertIn("`hooks/merge-guard.py`", self.fast_pr)
        self.assertTrue((ROOT / "hooks/merge-guard.py").is_file())

    def test_fast_pr_reports_the_pr_url_on_its_own_line(self) -> None:
        output = section(self.fast_pr, "Output to user")

        self.assertIn("full PR URL on its own line", output)
        self.assertIn("until merged", output)

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
