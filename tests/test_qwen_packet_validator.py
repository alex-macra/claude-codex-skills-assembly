from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills/spark-task-planning/scripts/validate-packets.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("qwen_packet_validator", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = load_validator()


FIELDS = (
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
)
COMMIT = "a" * 40
VERIFY_ITEM = (
    "1. Run from `/repo`: `test -f package.json` - expected exit 0; "
    "proves the input exists."
)


def packet_field_value(field: str, outcome: str) -> str:
    if field == "Readiness":
        return (
            f"Packet status: {outcome}\n"
            f"Evidence checked at: {COMMIT}\n"
            "Revalidate when: the pinned revision, inputs, or worktree changes."
        )
    if field == "Starting point":
        return (
            "Repository inventory: sample repository.\n"
            "Canonical root and execution working directory: /repo.\n"
            "Worktree and collision state: clean and isolated.\n"
            "Exact read set: package.json.\n"
            "Exact write set: src/example.py."
        )
    if field == "Change required":
        return "1. Read the complete target file.\n2. Apply the bounded change."
    if field == "Contract":
        return (
            "Local or ignored input manifest: None - no local or ignored files are consumed.\n"
            "Input provenance and preflight: Validate tracked inputs at the pinned revision."
        )
    if field == "Acceptance":
        return (
            "Normal case: the requested behavior passes.\n"
            "Boundary or failure case: invalid input fails closed.\n"
            "Compatibility case: existing behavior is unchanged.\n"
            "Security or concurrency case: concurrent writes are refused."
        )
    if field == "Verify":
        return VERIFY_ITEM
    if field == "Handoff":
        return "Report starting and final revisions, changed files, checks, and risks."
    return "Value"


def standalone(fields: tuple[str, ...] = FIELDS, outcome: str = "READY") -> str:
    sections = []
    for field in fields:
        value = packet_field_value(field, outcome)
        sections.append(f"## {field}\n{value}")
    return "# Task: TEST-001 - Example\n\n" + "\n\n".join(sections)


def embedded() -> str:
    values = []
    for field in FIELDS:
        value = packet_field_value(field, "NO_CHANGE_NEEDED")
        values.append(f"- **{field}:** {value}")
    return "### TEST-002 - Embedded\n\n#### Qwen3-Coder-Next packet\n\n" + "\n".join(values)


def legacy() -> str:
    sections = []
    for field in FIELDS:
        value = packet_field_value(field, "BLOCKED_BY_SPEC")
        sections.append(f"**{field}**\n{value}")
    return (
        "### TEST-003 - Legacy embedded\n\n**Qwen3-Coder-Next packet**\n\n"
        + "\n\n".join(sections)
    )


class PacketValidatorTests(unittest.TestCase):
    def test_completed_reference_template_passes_its_validator(self) -> None:
        reference = (
            ROOT / "skills/spark-task-planning/references/qwen-task-packet.md"
        ).read_text(encoding="utf-8")
        template = reference.split("## Task packet", 1)[1]
        template = template.split("```markdown", 1)[1].split("```", 1)[0]
        rendered = template.replace("[ID]", "TEST-004")
        rendered = rendered.replace(
            "[full commit object ID for every repository]",
            COMMIT,
        )
        rendered = rendered.replace("[absolute path]", "/repo")
        rendered = rendered.replace("[working directory]", "/repo")
        rendered = re.sub(r"\[[^\]\n]+\]", "Value", rendered)
        rendered = rendered.replace(
            "Local or ignored input manifest: Value",
            "Local or ignored input manifest: None - no local or ignored files are consumed",
        )
        rendered = rendered.replace(
            "Input provenance and preflight: Value",
            "Input provenance and preflight: Validate tracked inputs at the pinned revision.",
        )

        findings, outcomes = validator.validate_text(rendered, "reference-template.md")

        self.assertEqual([], findings)
        self.assertEqual({"READY": 1}, dict(outcomes))

    def test_accepts_all_three_schema_renderings(self) -> None:
        text = standalone() + "\n\n" + embedded() + "\n\n" + legacy()
        findings, outcomes = validator.validate_text(text)

        self.assertEqual([], findings)
        self.assertEqual(
            {"READY": 1, "BLOCKED_BY_SPEC": 1, "NO_CHANGE_NEEDED": 1},
            dict(outcomes),
        )

    def test_embedded_renderings_require_their_packet_marker(self) -> None:
        cases = (
            embedded().replace("#### Qwen3-Coder-Next packet\n\n", ""),
            legacy().replace("**Qwen3-Coder-Next packet**\n\n", ""),
        )

        for text in cases:
            with self.subTest(text=text[:40]):
                findings, _ = validator.validate_text(text)
                self.assertTrue(any("preceding owned Qwen packet marker" in item for item in findings))

    def test_rejects_a_missing_field(self) -> None:
        fields = tuple(field for field in FIELDS if field != "Contract")
        findings, _ = validator.validate_text(standalone(fields))

        self.assertTrue(any("expected fields" in finding for finding in findings))

    def test_rejects_a_duplicate_field_after_handoff(self) -> None:
        findings, _ = validator.validate_text(standalone() + "\n\n## Scope\nDuplicate")

        self.assertTrue(any("expected fields" in finding for finding in findings))

    def test_embedded_packet_ends_before_legacy_task_fields(self) -> None:
        text = embedded() + "\n\n- **Scope:** Legacy task prose.\n- **Acceptance criteria:** Legacy acceptance."
        findings, outcomes = validator.validate_text(text)

        self.assertEqual([], findings)
        self.assertEqual({"NO_CHANGE_NEEDED": 1}, dict(outcomes))

    def test_rejects_packet_without_a_task_id_heading(self) -> None:
        findings, _ = validator.validate_text(
            standalone().replace("# Task: TEST-001 - Example\n\n", "")
        )

        self.assertTrue(any("no task ID heading" in finding for finding in findings))

    def test_rejects_an_earlier_task_heading_without_readiness(self) -> None:
        first = standalone(tuple(field for field in FIELDS if field != "Readiness"))
        second = standalone().replace("TEST-001", "TEST-002")
        findings, _ = validator.validate_text(first + "\n\n" + second)

        self.assertTrue(
            any(
                "TEST-001" in finding and "must own exactly one Readiness" in finding
                for finding in findings
            )
        )

    def test_rejects_a_short_or_missing_commit(self) -> None:
        findings, _ = validator.validate_text(standalone().replace(COMMIT, "abc1234"))

        self.assertTrue(any("no full commit object ID" in finding for finding in findings))

    def test_rejects_multiple_readiness_outcomes(self) -> None:
        text = standalone().replace("Packet status: READY", "Packet status: READY or BLOCKED_BY_SPEC")
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("expected one explicit packet status" in finding for finding in findings))

    def test_rejects_a_duplicate_status_token(self) -> None:
        text = standalone().replace("Packet status: READY", "Packet status: READY READY")
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("expected one explicit packet status" in finding for finding in findings))

    def test_rejects_status_prefix_embedded_in_another_word(self) -> None:
        text = standalone().replace("Packet status: READY", "Packet status: READY-made")
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("expected one explicit packet status" in finding for finding in findings))

    def test_rejects_status_declaration_with_trailing_prose(self) -> None:
        text = standalone().replace(
            "Packet status: READY",
            "Packet status: READY because the evidence is current.",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("expected one explicit packet status" in finding for finding in findings))

    def test_rejects_mixed_inline_and_packet_status_declarations(self) -> None:
        text = standalone().replace(
            "Packet status: READY",
            "READY\nPacket status: BLOCKED_BY_SPEC",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("expected one explicit packet status" in finding for finding in findings))

    def test_rejects_a_negated_outcome_without_status(self) -> None:
        text = standalone().replace("Packet status: READY", "This packet is not READY")
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("expected one explicit packet status" in finding for finding in findings))

    def test_requires_canonical_packet_status_label(self) -> None:
        declarations = ("Status: READY", "- Status: READY", "READY")

        for declaration in declarations:
            with self.subTest(declaration=declaration):
                text = standalone().replace("Packet status: READY", declaration)
                findings, outcomes = validator.validate_text(text)
                self.assertTrue(
                    any("expected one explicit packet status" in finding for finding in findings)
                )
                self.assertEqual({}, dict(outcomes))

    def test_accepts_canonical_status_that_differs_from_packet_status(self) -> None:
        text = standalone().replace(
            "Packet status: READY",
            "Packet status: READY\nCanonical tracker status: BLOCKED_BY_SPEC",
        )
        findings, outcomes = validator.validate_text(text)

        self.assertEqual([], findings)
        self.assertEqual({"READY": 1}, dict(outcomes))

    def test_accepts_outcome_vocabulary_in_readiness_reason(self) -> None:
        text = standalone().replace(
            "Packet status: READY",
            "Packet status: READY\nOutcome reason: READY is justified by the pinned evidence.",
        )
        findings, outcomes = validator.validate_text(text)

        self.assertEqual([], findings)
        self.assertEqual({"READY": 1}, dict(outcomes))

    def test_requires_commit_evidence_in_readiness_or_starting_point(self) -> None:
        text = standalone().replace(COMMIT, "main").replace(
            "## Handoff\nValue",
            f"## Handoff\nEvidence elsewhere: {COMMIT}",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("no full commit object ID" in finding for finding in findings))

    def test_does_not_treat_artifact_fingerprint_as_commit_evidence(self) -> None:
        text = standalone().replace(
            f"Evidence checked at: {COMMIT}",
            f"Base commit: unavailable.\nArtifact fingerprint: {COMMIT}",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("no full commit object ID" in finding for finding in findings))

    def test_does_not_treat_output_object_as_commit_evidence(self) -> None:
        text = standalone().replace(
            f"Evidence checked at: {COMMIT}",
            f"Base commit: unavailable.\nOutput object: {COMMIT}",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("no full commit object ID" in finding for finding in findings))

    def test_does_not_treat_a_negated_commit_as_commit_evidence(self) -> None:
        text = standalone().replace(
            f"Evidence checked at: {COMMIT}",
            f"Base commit: not a commit {COMMIT}",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("no full commit object ID" in finding for finding in findings))

    def test_does_not_treat_negated_or_historical_commit_prose_as_evidence(self) -> None:
        replacements = (
            f"Base commit is not {COMMIT}.",
            f"There is no commit at {COMMIT}.",
            f"The commit is unknown: {COMMIT}.",
            f"The old commit was {COMMIT}.",
            f"Do not use commit {COMMIT}.",
            f"Commit should not be {COMMIT}.",
            f"Forbidden commit: {COMMIT}.",
            f"Candidate commit: {COMMIT}.",
            f"Commit differs from {COMMIT}.",
            f"Rejected commit: {COMMIT}.",
        )

        for replacement in replacements:
            with self.subTest(replacement=replacement):
                text = standalone().replace(
                    f"Evidence checked at: {COMMIT}",
                    replacement,
                )
                findings, _ = validator.validate_text(text)
                self.assertTrue(
                    any("no full commit object ID" in finding for finding in findings)
                )

    def test_does_not_treat_xref_as_commit_evidence(self) -> None:
        text = standalone().replace(
            f"Evidence checked at: {COMMIT}",
            f"Base commit: unavailable.\nxref: {COMMIT}",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("no full commit object ID" in finding for finding in findings))

    def test_does_not_treat_recommit_prose_as_commit_evidence(self) -> None:
        text = standalone().replace(
            f"Evidence checked at: {COMMIT}",
            f"Base commit: unavailable.\nThe plan says to recommit {COMMIT}.",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("no full commit object ID" in finding for finding in findings))

    def test_does_not_treat_fenced_log_as_commit_evidence(self) -> None:
        text = standalone().replace(
            f"Evidence checked at: {COMMIT}",
            f"Base ref unresolved.\n```text\nBase commit: {COMMIT}\n```",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("no full commit object ID" in finding for finding in findings))

    def test_does_not_bind_wrapped_artifact_digest_to_a_ref(self) -> None:
        text = standalone().replace(
            f"Evidence checked at: {COMMIT}",
            f"`origin/main` has no resolved commit; artifact digest follows:\n{COMMIT}",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("no full commit object ID" in finding for finding in findings))

    def test_rejects_noncanonical_wrapped_commit_values(self) -> None:
        replacements = (
            f"Evidence checked at:\nnot a commit {COMMIT}",
            f"Base commit:\nArtifact digest: {COMMIT}",
            f"Base ref:\nCandidate commit: {COMMIT}",
            f"Evidence checked at: unavailable.\n`origin/main`\nArtifact digest: {COMMIT}",
        )

        for replacement in replacements:
            with self.subTest(replacement=replacement):
                findings, _ = validator.validate_text(
                    standalone().replace(f"Evidence checked at: {COMMIT}", replacement)
                )
                self.assertTrue(
                    any("no full commit object ID" in finding for finding in findings)
                )

    def test_accepts_exact_wrapped_object_and_ref_mapping(self) -> None:
        variants = (
            f"Evidence checked at:\n  {COMMIT}",
            f"Evidence checked at: unavailable.\norigin/main = {COMMIT}",
        )

        for replacement in variants:
            with self.subTest(replacement=replacement):
                findings, outcomes = validator.validate_text(
                    standalone().replace(f"Evidence checked at: {COMMIT}", replacement)
                )
                self.assertEqual([], findings)
                self.assertEqual({"READY": 1}, dict(outcomes))

    def test_accepts_sha256_git_object_ids(self) -> None:
        findings, outcomes = validator.validate_text(standalone().replace(COMMIT, "b" * 64))

        self.assertEqual([], findings)
        self.assertEqual({"READY": 1}, dict(outcomes))

    def test_accepts_blocked_packet_when_repository_is_not_applicable(self) -> None:
        text = standalone(outcome="BLOCKED_BY_SPEC").replace(
            COMMIT,
            "Not applicable - the owner has not selected or created a repository.",
        )
        findings, outcomes = validator.validate_text(text)

        self.assertEqual([], findings)
        self.assertEqual({"BLOCKED_BY_SPEC": 1}, dict(outcomes))

    def test_rejects_blocked_packet_without_object_or_not_applicable_reason(self) -> None:
        text = standalone(outcome="BLOCKED_BY_SPEC").replace(COMMIT, "repository pending")
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("blocked packet needs" in finding for finding in findings))

    def test_blocked_not_applicable_reason_must_belong_to_evidence_or_base(self) -> None:
        text = standalone(outcome="BLOCKED_BY_SPEC").replace(COMMIT, "unavailable").replace(
            "## Starting point\nValue",
            "## Starting point\nNot applicable - no prerequisite tasks exist.",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("blocked packet needs" in finding for finding in findings))

    def test_rejects_an_empty_field(self) -> None:
        findings, _ = validator.validate_text(standalone().replace("## Why\nValue", "## Why\n"))

        self.assertTrue(any("empty Why field" in finding for finding in findings))

    def test_rejects_not_applicable_without_a_reason(self) -> None:
        findings, _ = validator.validate_text(
            standalone().replace("## Why\nValue", "## Why\nNot applicable -")
        )

        self.assertTrue(any("nonblank reason" in finding for finding in findings))

    def test_rejects_nested_not_applicable_without_a_reason(self) -> None:
        findings, _ = validator.validate_text(
            standalone().replace("## Why\nValue", "## Why\n- Not applicable -")
        )

        self.assertTrue(any("nonblank reason" in finding for finding in findings))

    def test_requires_revalidation_trigger(self) -> None:
        text = standalone().replace(
            "Revalidate when: the pinned revision, inputs, or worktree changes.\n",
            "",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("Revalidate when" in finding for finding in findings))

    def test_requires_execution_boundary_details(self) -> None:
        text = standalone().replace("Exact write set:", "Writable paths:")
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("Exact write set" in finding for finding in findings))

    def test_requires_local_input_manifest_and_provenance_contract(self) -> None:
        replacements = (
            (
                "Local or ignored input manifest: None - no local or ignored files are consumed.\n",
                "",
            ),
            (
                "Input provenance and preflight: Validate tracked inputs at the pinned revision.",
                "",
            ),
        )

        for old, new in replacements:
            with self.subTest(label=old.split(":", 1)[0]):
                findings, _ = validator.validate_text(standalone().replace(old, new))
                self.assertTrue(any("Contract is missing critical detail" in item for item in findings))

    def test_rejects_empty_local_input_contract_labels(self) -> None:
        text = standalone().replace(
            "Local or ignored input manifest: None - no local or ignored files are consumed.",
            "Local or ignored input manifest:",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("Contract has empty critical detail" in item for item in findings))

    def test_rejects_placeholder_local_input_contract(self) -> None:
        text = standalone().replace(
            "Local or ignored input manifest: None - no local or ignored files are consumed.\n"
            "Input provenance and preflight: Validate tracked inputs at the pinned revision.",
            "Local or ignored input manifest: TBD\n"
            "Input provenance and preflight: TBD",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("manifest must be" in item for item in findings))
        self.assertTrue(any("must be decision-complete" in item for item in findings))

    def test_accepts_explicit_local_input_manifest_entry(self) -> None:
        text = standalone().replace(
            "Local or ignored input manifest: None - no local or ignored files are consumed.",
            "Local or ignored input manifest:\n"
            "  - `/repo/private input.json` | type: regular file | bytes: 17 | "
            f"sha256: {'b' * 64}",
        )
        findings, outcomes = validator.validate_text(text)

        self.assertEqual([], findings)
        self.assertEqual({"READY": 1}, dict(outcomes))

    def test_rejects_uppercase_local_input_digest(self) -> None:
        text = standalone().replace(
            "Local or ignored input manifest: None - no local or ignored files are consumed.",
            "Local or ignored input manifest:\n"
            "  - `/repo/private.json` | type: regular file | bytes: 17 | "
            f"sha256: {'B' * 64}",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("lowercase SHA-256" in item for item in findings))

    def test_rejects_noncanonical_or_duplicate_local_input_paths(self) -> None:
        declaration = (
            "Local or ignored input manifest: None - no local or ignored files are consumed."
        )
        invalid_manifests = (
            "Local or ignored input manifest:\n"
            f"  - `/repo/../secret.json` | type: regular file | bytes: 1 | sha256: {'b' * 64}",
            "Local or ignored input manifest:\n"
            f"  - `/repo//input.json` | type: regular file | bytes: 1 | sha256: {'b' * 64}",
            "Local or ignored input manifest:\n"
            f"  - `/repo/input.json` | type: regular file | bytes: 1 | sha256: {'b' * 64}\n"
            f"  - `/repo/input.json` | type: regular file | bytes: 1 | sha256: {'b' * 64}",
        )

        for manifest in invalid_manifests:
            with self.subTest(manifest=manifest):
                findings, _ = validator.validate_text(standalone().replace(declaration, manifest))
                self.assertTrue(any("manifest must be" in item for item in findings))

    def test_rejects_duplicate_critical_subfield_labels(self) -> None:
        cases = (
            (
                "Input provenance and preflight: Validate tracked inputs at the pinned revision.",
                "Input provenance and preflight: Validate tracked inputs at the pinned revision.\n"
                "Local or ignored input manifest: None - no local or ignored files are consumed.",
            ),
            (
                "Worktree and collision state: clean and isolated.",
                "Worktree and collision state: clean and isolated.\n"
                "Canonical root and execution working directory: /other.",
            ),
            (
                "Compatibility case: existing behavior is unchanged.",
                "Compatibility case: existing behavior is unchanged.\n"
                "Normal case: contradictory duplicate.",
            ),
        )

        for original, replacement in cases:
            with self.subTest(replacement=replacement):
                findings, _ = validator.validate_text(standalone().replace(original, replacement))
                self.assertTrue(any("duplicate critical detail" in item for item in findings))

    def test_rejects_an_empty_execution_boundary_label(self) -> None:
        text = standalone().replace(
            "Exact write set: src/example.py.",
            "Exact write set:",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("empty critical" in finding for finding in findings))

    def test_accepts_nested_content_for_a_critical_label(self) -> None:
        text = standalone().replace(
            "Repository inventory: sample repository.",
            "Repository inventory:\n  - sample repository at the pinned commit.",
        )
        findings, _ = validator.validate_text(text)

        self.assertEqual([], findings)

    def test_requires_absolute_starting_working_directory(self) -> None:
        text = standalone().replace(
            "Canonical root and execution working directory: /repo.",
            "Canonical root and execution working directory: repository pending.",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("absolute execution working directory" in finding for finding in findings))

    def test_rejects_a_negated_absolute_execution_root(self) -> None:
        text = standalone().replace(
            "Canonical root and execution working directory: /repo.",
            "Canonical root and execution working directory: It is forbidden to run from /repo.",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("absolute execution working directory" in finding for finding in findings))

    def test_execution_root_must_begin_with_the_canonical_absolute_path(self) -> None:
        values = (
            "This is not /repo; no checkout is selected.",
            "No checkout is selected; diagnostic log is /tmp/run.log.",
        )

        for value in values:
            with self.subTest(value=value):
                text = standalone().replace(
                    "Canonical root and execution working directory: /repo.",
                    f"Canonical root and execution working directory: {value}",
                )
                findings, _ = validator.validate_text(text)
                self.assertTrue(
                    any("absolute execution working directory" in finding for finding in findings)
                )

    def test_execution_root_accepts_path_first_with_detail(self) -> None:
        text = standalone().replace(
            "Canonical root and execution working directory: /repo.",
            "Canonical root and execution working directory: `/repo` - use this checkout only.",
        )
        findings, outcomes = validator.validate_text(text)

        self.assertEqual([], findings)
        self.assertEqual({"READY": 1}, dict(outcomes))

    def test_execution_root_rejects_noncanonical_path_aliases(self) -> None:
        aliases = ("/repo/../other.", "/repo//child.", "/repo/./child.")

        for alias in aliases:
            with self.subTest(alias=alias):
                text = standalone().replace(
                    "Canonical root and execution working directory: /repo.",
                    f"Canonical root and execution working directory: {alias}",
                )
                findings, _ = validator.validate_text(text)
                self.assertTrue(
                    any("absolute execution working directory" in finding for finding in findings)
                )

    def test_fenced_status_example_does_not_declare_readiness(self) -> None:
        text = standalone().replace(
            "Packet status: READY",
            "Example only:\n```text\nPacket status: READY\n```",
        )
        findings, outcomes = validator.validate_text(text)

        self.assertTrue(any("expected one explicit packet status" in finding for finding in findings))
        self.assertEqual({}, dict(outcomes))

    def test_rejects_packet_status_shadow_outside_readiness(self) -> None:
        text = standalone().replace(
            "## Why\nValue",
            "## Why\nValue\nPacket status: BLOCKED_BY_SPEC",
        )
        findings, outcomes = validator.validate_text(text)

        self.assertTrue(any("only in Readiness" in finding for finding in findings))
        self.assertEqual({"READY": 1}, dict(outcomes))

    def test_rejects_packet_status_shadow_before_readiness(self) -> None:
        text = standalone().replace(
            "# Task: TEST-001 - Example\n\n",
            "# Task: TEST-001 - Example\n\nPacket status: BLOCKED_BY_SPEC\n\n",
        )
        findings, outcomes = validator.validate_text(text)

        self.assertTrue(any("only in Readiness" in finding for finding in findings))
        self.assertEqual({"READY": 1}, dict(outcomes))

    def test_rejects_duplicate_packet_task_ids(self) -> None:
        findings, outcomes = validator.validate_text(standalone() + "\n\n" + standalone())

        self.assertTrue(any("duplicate packet task ID" in finding for finding in findings))
        self.assertEqual({"READY": 2}, dict(outcomes))

    def test_requires_numbered_change_steps(self) -> None:
        text = standalone().replace(
            "1. Read the complete target file.\n2. Apply the bounded change.",
            "Read the complete target file, then apply the bounded change.",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("Change required must use" in finding for finding in findings))

    def test_rejects_multiple_change_steps_compressed_onto_one_line(self) -> None:
        text = standalone().replace(
            "1. Read the complete target file.\n2. Apply the bounded change.",
            "1. Read the complete target file. 2. Apply the bounded change.",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("each numbered step" in finding for finding in findings))

    def test_requires_acceptance_case_matrix(self) -> None:
        text = standalone().replace("Boundary or failure case:", "Failure notes:")
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("Boundary or failure case" in finding for finding in findings))

    def test_requires_numbered_verify_items(self) -> None:
        text = standalone().replace("1. Run from", "Run from")
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("Verify must use" in finding for finding in findings))

    def test_rejects_multiple_verify_commands_compressed_onto_one_line(self) -> None:
        text = standalone().replace(
            VERIFY_ITEM,
            VERIFY_ITEM + " 2. Run from `/repo`: `true` - expected exit 0; proves success.",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("each numbered command" in finding for finding in findings))

    def test_requires_verify_expected_result_and_proof_claim(self) -> None:
        text = standalone().replace("expected exit 0; proves", "returns exit 0 and confirms")
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("expected result" in finding for finding in findings))
        self.assertTrue(any("proof claim" in finding for finding in findings))

    def test_requires_revision_bound_handoff(self) -> None:
        text = standalone().replace(
            "Report starting and final revisions, changed files, checks, and risks.",
            "Report changed files, checks, and risks.",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("starting and final revisions" in finding for finding in findings))

    def test_rejects_verify_without_working_directory(self) -> None:
        text = standalone().replace(
            VERIFY_ITEM,
            "`test -f package.json` - proves the input exists.",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("does not name a working directory" in finding for finding in findings))

    def test_rejects_ready_verify_marked_not_applicable(self) -> None:
        text = standalone().replace(
            VERIFY_ITEM,
            "Not applicable - tests were not identified.",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("does not name a working directory" in finding for finding in findings))

    def test_rejects_blocked_verify_not_applicable_without_a_reason(self) -> None:
        text = standalone(outcome="BLOCKED_BY_SPEC").replace(
            VERIFY_ITEM,
            "Not applicable -",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("nonblank reason" in finding for finding in findings))
        self.assertTrue(any("does not name a working directory" in finding for finding in findings))

    def test_accepts_blocked_nested_verify_not_applicable_with_reason(self) -> None:
        text = standalone(outcome="BLOCKED_BY_SPEC").replace(
            VERIFY_ITEM,
            "- Not applicable - no target repository exists.",
        )
        findings, outcomes = validator.validate_text(text)

        self.assertEqual([], findings)
        self.assertEqual({"BLOCKED_BY_SPEC": 1}, dict(outcomes))

    def test_accepts_tool_native_working_directory(self) -> None:
        text = standalone().replace(
            VERIFY_ITEM,
            "1. `git -C /repo status --short` - expected exit 0; proves the checkout state.",
        )
        findings, _ = validator.validate_text(text)

        self.assertEqual([], findings)

    def test_rejects_negated_working_directory_prose(self) -> None:
        text = standalone().replace(
            VERIFY_ITEM,
            "No working directory is `/repo`; the executor must choose one.",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("does not name a working directory" in finding for finding in findings))

    def test_rejects_negated_run_from_instruction(self) -> None:
        text = standalone().replace(
            VERIFY_ITEM,
            "Do not run from `/repo`; choose a working directory first.",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("does not name a working directory" in finding for finding in findings))

    def test_rejects_cannot_run_from_instruction(self) -> None:
        text = standalone().replace(
            VERIFY_ITEM,
            "Cannot run from `/repo`; choose a checkout first.",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("does not name a working directory" in finding for finding in findings))

    def test_rejects_no_need_or_no_action_working_directory_prose(self) -> None:
        instructions = (
            "1. There is no need to run from /repo: `true` - expected exit 0; proves success.",
            "1. No action requires running from /repo: `true` - expected exit 0; proves success.",
            "1. We need not run from /repo: `true` - expected exit 0; proves success.",
            "1. It is not necessary to run from /repo: `true` - expected exit 0; proves success.",
        )

        for instruction in instructions:
            with self.subTest(instruction=instruction):
                findings, _ = validator.validate_text(
                    standalone().replace(VERIFY_ITEM, instruction)
                )
                self.assertTrue(
                    any("does not name a working directory" in finding for finding in findings)
                )

    def test_rejects_documentation_working_directory_prose(self) -> None:
        text = standalone().replace(
            VERIFY_ITEM,
            "1. The documentation says run from /repo: `true` - expected exit 0; proves success.",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("does not name a working directory" in finding for finding in findings))

    def test_rejects_forbidden_or_discouraged_run_from_instruction(self) -> None:
        instructions = (
            "1. It is forbidden to run from /repo: `true` - expected exit 0; proves success.",
            "1. We should not run from /repo: `true` - expected exit 0; proves success.",
        )

        for instruction in instructions:
            with self.subTest(instruction=instruction):
                findings, _ = validator.validate_text(
                    standalone().replace(VERIFY_ITEM, instruction)
                )
                self.assertTrue(
                    any("does not name a working directory" in finding for finding in findings)
                )

    def test_rejects_historical_working_directory_prose(self) -> None:
        text = standalone().replace(
            VERIFY_ITEM,
            "The old documentation says run from `/repo`, but that path does not exist.",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("does not name a working directory" in finding for finding in findings))

    def test_does_not_treat_fenced_log_as_working_directory(self) -> None:
        text = standalone().replace(
            VERIFY_ITEM,
            "No executable checkout is selected.\n```text\nRun from /repo: failed\n```",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("does not name a working directory" in finding for finding in findings))

    def test_requires_a_working_directory_for_each_numbered_verify_command(self) -> None:
        text = standalone().replace(
            VERIFY_ITEM,
            "1. Run from `/repo`: `test -f package.json` - expected exit 0; "
            "proves the input exists.\n"
            "2. `python3 -m unittest` - expected exit 0; proves the suite passes.",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("Verify command 2" in finding for finding in findings))

    def test_rejects_install_prefix_as_working_directory(self) -> None:
        text = standalone().replace(
            VERIFY_ITEM,
            "`./configure --prefix=/usr/local` - selects the install destination.",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("does not name a working directory" in finding for finding in findings))

    def test_rejects_output_directory_as_working_directory(self) -> None:
        text = standalone().replace(
            VERIFY_ITEM,
            "`tool --directory /tmp/output` - selects an output directory.",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("does not name a working directory" in finding for finding in findings))

    def test_rejects_unexpanded_home_working_directory(self) -> None:
        text = standalone().replace(
            VERIFY_ITEM,
            "Run from `~/repo`: `test -f package.json` - proves the input exists.",
        )
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("does not name a working directory" in finding for finding in findings))

    def test_rejects_mixed_renderings(self) -> None:
        text = standalone().replace("## Objective\nValue", "- **Objective:** Value")
        findings, _ = validator.validate_text(text)

        self.assertTrue(any("mixed packet renderings" in finding for finding in findings))

    def test_ignores_field_examples_inside_fences(self) -> None:
        text = standalone().replace(
            "## Why\nValue",
            "## Why\nValue\n\n```markdown\n## Scope\nExample only.\n```",
        )
        findings, _ = validator.validate_text(text)

        self.assertEqual([], findings)

    def test_directory_sweep_skips_unrelated_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unrelated = root / "README.md"
            unrelated.write_text("# Project\n\n## Readiness\nGeneral notes.\n", encoding="utf-8")

            self.assertFalse(validator.has_packet_candidate(unrelated.read_text(encoding="utf-8")))
            self.assertEqual(
                [(unrelated, False, unrelated.read_text(encoding="utf-8"))],
                validator.markdown_paths([str(root)]),
            )

    def test_directory_sweep_discovers_standalone_packet_missing_readiness(self) -> None:
        text = standalone(tuple(field for field in FIELDS if field != "Readiness"))

        self.assertTrue(validator.has_packet_candidate(text))
        findings, _ = validator.validate_text(text)
        self.assertTrue(any("must own exactly one Readiness" in finding for finding in findings))

    def test_directory_sweep_discovers_all_standalone_task_heading_levels(self) -> None:
        for level in range(2, 7):
            with self.subTest(level=level):
                text = f"{'#' * level} Task: TEST-002 - Broken\n\nProse only.\n"
                self.assertTrue(validator.has_packet_candidate(text))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "broken.md").write_text(
                "###### Task: TEST-002 - Broken\n\nProse only.\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(root)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("must own exactly one Readiness", result.stderr)

    def test_every_standalone_task_heading_requires_its_own_packet(self) -> None:
        incomplete_packets = (
            "# Task: TEST-002 - Broken\n\nProse only.",
            "# Task: TEST-002 - Broken\n\n## Objective\nPartial packet.",
        )

        for incomplete in incomplete_packets:
            with self.subTest(incomplete=incomplete):
                findings, outcomes = validator.validate_text(standalone() + "\n\n" + incomplete)
                self.assertEqual({"READY": 1}, dict(outcomes))
                self.assertTrue(
                    any(
                        "TEST-002" in finding and "must own exactly one Readiness" in finding
                        for finding in findings
                    )
                )

    def test_malformed_packet_marker_is_not_skipped(self) -> None:
        self.assertTrue(validator.has_packet_candidate("#### Qwen task packet\n"))

    def test_malformed_marker_before_later_packet_is_reported(self) -> None:
        text = "#### Qwen task packet\n\nMissing schema.\n\n" + standalone()
        findings, outcomes = validator.validate_text(text)

        self.assertTrue(any("marker has no Readiness" in finding for finding in findings))
        self.assertEqual({"READY": 1}, dict(outcomes))

    def test_fenced_packet_examples_are_not_discovered(self) -> None:
        marker = "```markdown\n#### Qwen3-Coder-Next packet\n```\n"
        standalone_example = "```markdown\n# Task: TEST-001\n\n## Readiness\nREADY\n```\n"

        self.assertFalse(validator.has_packet_candidate(marker))
        self.assertFalse(validator.has_packet_candidate(standalone_example))

    def test_malformed_fence_closer_does_not_expose_packet(self) -> None:
        fences = (("```markdown", "```oops", "```"), ("~~~markdown", "~~~oops", "~~~"))

        for opening, malformed_closer, closing in fences:
            with self.subTest(opening=opening):
                text = "\n".join((opening, malformed_closer, standalone(), closing))
                findings, outcomes = validator.validate_text(text)
                self.assertEqual([], findings)
                self.assertEqual({}, dict(outcomes))

    def test_backtick_in_backtick_fence_info_cannot_hide_a_later_packet(self) -> None:
        text = (
            standalone()
            + "\n\n````invalid`info\n"
            + "# Task: TEST-002 - Broken\n\nProse only."
        )

        findings, outcomes = validator.validate_text(text)

        self.assertEqual({"READY": 1}, dict(outcomes))
        self.assertTrue(
            any(
                "TEST-002" in finding and "must own exactly one Readiness" in finding
                for finding in findings
            )
        )

    def test_directory_sweep_has_file_depth_and_aggregate_budgets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "a.md").write_text("aaaa", encoding="utf-8")
            (root / "b.md").write_text("bbbb", encoding="utf-8")
            with mock.patch.object(validator, "MAX_DIRECTORY_PACKET_FILES", 1):
                with self.assertRaisesRegex(ValueError, "Markdown-file limit"):
                    validator.markdown_paths([str(root)])
            with mock.patch.object(validator, "MAX_DIRECTORY_PACKET_BYTES", 7):
                with self.assertRaisesRegex(ValueError, "aggregate limit"):
                    validator.markdown_paths([str(root)])

            nested = root / "one" / "two"
            nested.mkdir(parents=True)
            with mock.patch.object(validator, "MAX_DIRECTORY_DEPTH", 1):
                with self.assertRaisesRegex(ValueError, "depth limit"):
                    validator.markdown_paths([str(root)])

    def test_directory_budgets_apply_across_all_input_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            (first / "a.md").write_text("aaaa", encoding="utf-8")
            (second / "b.md").write_text("bbbb", encoding="utf-8")

            with mock.patch.object(validator, "MAX_DIRECTORY_PACKET_FILES", 1):
                with self.assertRaisesRegex(ValueError, "Markdown-file limit"):
                    validator.markdown_paths([str(first), str(second)])
            with mock.patch.object(validator, "MAX_DIRECTORY_PACKET_BYTES", 7):
                with self.assertRaisesRegex(ValueError, "aggregate limit"):
                    validator.markdown_paths([str(first), str(second)])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support is required")
    def test_directory_sweep_does_not_follow_directory_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "root"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            hidden = outside / "hidden.md"
            hidden.write_text(standalone(), encoding="utf-8")
            (root / "linked").symlink_to(outside, target_is_directory=True)

            self.assertEqual([], validator.markdown_paths([str(root)]))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support is required")
    def test_directory_content_is_captured_before_an_ancestor_swap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "root"
            nested = root / "nested"
            outside = base / "outside"
            nested.mkdir(parents=True)
            outside.mkdir()
            expected = standalone()
            (nested / "packet.md").write_text(expected, encoding="utf-8")
            (outside / "packet.md").write_text("# Task: TEST-999 - Outside\n", encoding="utf-8")

            sources = validator.markdown_paths([str(root)])
            detached = root / "detached"
            nested.rename(detached)
            nested.symlink_to(outside, target_is_directory=True)

            self.assertEqual(expected, sources[0][2])
            with (
                mock.patch.object(validator, "markdown_paths", return_value=sources),
                mock.patch.object(
                    validator,
                    "read_packet_text",
                    side_effect=AssertionError("directory packet was reopened by lexical path"),
                ),
                mock.patch.object(sys, "argv", [str(SCRIPT), str(root)]),
                mock.patch("builtins.print"),
            ):
                self.assertEqual(0, validator.main())

    def test_html_commented_packet_is_not_discovered(self) -> None:
        text = "<!--\n" + standalone() + "\n-->"
        findings, outcomes = validator.validate_text(text)

        self.assertEqual([], findings)
        self.assertEqual({}, dict(outcomes))

    def test_raw_or_hidden_html_packet_is_not_discovered(self) -> None:
        wrappers = (
            ("<pre>", "</pre>"),
            ("<script>", "</script>"),
            ("<style>", "</style>"),
            ("<textarea>", "</textarea>"),
            ("<div hidden>", "</div>"),
        )

        for opening, closing in wrappers:
            with self.subTest(opening=opening):
                findings, outcomes = validator.validate_text(
                    opening + "\n" + standalone() + "\n" + closing
                )
                self.assertEqual([], findings)
                self.assertEqual({}, dict(outcomes))

    def test_commonmark_token_ended_html_blocks_hide_packet_syntax(self) -> None:
        wrappers = (
            ("<!--", "-->"),
            ("<?instruction", "?>"),
            ("<!DECLARATION", ">"),
            ("<![CDATA[", "]]>")
        )

        for opening, closing in wrappers:
            with self.subTest(opening=opening):
                findings, outcomes = validator.validate_text(
                    opening + "\n" + standalone() + "\n" + closing
                )
                self.assertEqual([], findings)
                self.assertEqual({}, dict(outcomes))

    def test_commonmark_type_6_html_block_ends_at_first_blank_line(self) -> None:
        openings = ("<div>", "</div>")

        for opening in openings:
            with self.subTest(opening=opening):
                findings, outcomes = validator.validate_text(
                    opening + "\nlegacy\n\n" + standalone()
                )
                self.assertEqual([], findings)
                self.assertEqual({"READY": 1}, dict(outcomes))

    def test_commonmark_type_7_html_block_hides_until_first_blank_line(self) -> None:
        findings, outcomes = validator.validate_text("<custom-element>\n" + standalone())

        self.assertTrue(any("no task ID heading" in finding for finding in findings))
        self.assertEqual({"READY": 1}, dict(outcomes))

    def test_explicit_nonpacket_file_fails_cli_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "notes.md"
            path.write_text("# Notes\n\nNothing here.\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(path)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("explicit file contains no visible Qwen task packet", result.stderr)

    def test_oversized_packet_fails_before_content_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "large.md"
            with path.open("wb") as handle:
                handle.truncate(validator.MAX_PACKET_BYTES + 1)

            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(path)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("packet exceeds", result.stderr)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO support is required")
    def test_file_to_fifo_open_races_fail_without_blocking(self) -> None:
        script = f"""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile

spec = importlib.util.spec_from_file_location("fifo_race_validator", {str(SCRIPT)!r})
validator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = validator
spec.loader.exec_module(validator)
original_open = os.open

def exercise(directory_mode):
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        packet = root / "packet.md"
        packet.write_text("# Task: TEST-001\\n", encoding="utf-8")
        swapped = [False]

        def racing_open(candidate, flags, *args, **kwargs):
            directory_match = (
                directory_mode
                and candidate == "packet.md"
                and kwargs.get("dir_fd") is not None
            )
            explicit_match = (
                not directory_mode
                and Path(candidate) == packet
                and kwargs.get("dir_fd") is None
            )
            if not swapped[0] and (directory_match or explicit_match):
                swapped[0] = True
                packet.unlink()
                os.mkfifo(packet)
            return original_open(candidate, flags, *args, **kwargs)

        validator.os.open = racing_open
        try:
            if directory_mode:
                validator.markdown_paths([str(root)])
            else:
                validator.read_packet_text(packet)
        except ValueError:
            return
        finally:
            validator.os.open = original_open
        raise AssertionError("FIFO replacement was accepted")

exercise(True)
exercise(False)
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)

    def test_indented_code_cannot_supply_packet_field_values(self) -> None:
        lines = standalone().splitlines()
        hidden = "\n".join(
            line
            if not line or line.startswith("#")
            else "    " + line
            for line in lines
        )
        findings, outcomes = validator.validate_text(hidden)

        self.assertTrue(any("explicit packet status" in item for item in findings))
        self.assertEqual({}, dict(outcomes))

    def test_standalone_bold_field_packet_is_discovered(self) -> None:
        packet = "\n\n".join(f"**{field}**\nValue" for field in FIELDS)

        self.assertTrue(validator.has_packet_candidate(packet))


if __name__ == "__main__":
    unittest.main()
