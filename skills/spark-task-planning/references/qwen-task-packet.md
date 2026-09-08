# Qwen-ready task packet

Use this template for fresh-context execution by Qwen3-Coder-Next. Replace bracketed prompts with repository facts. Every one of the 15 task-packet fields is mandatory. If a field truly does not apply, keep its heading or label and write `Not applicable - <reason>` instead of omitting it. Do not leave unresolved choices disguised as implementation steps.

The validator treats the revalidation trigger, repository inventory, absolute execution root, worktree/collision state, exact read and write sets, numbered change and verification steps, acceptance case matrix, and starting/final revision handoff as execution-critical. Give every critical label a nonblank inline or indented value, use at least two change steps, and begin every numbered change or verification item on its own line. Do not compress those details into unlabeled prose. An explicit packet file must contain a visible packet and must be a regular non-symlink Markdown file no larger than 8 MiB. Directory sweeps do not follow directory symlinks and stop after 16,384 entries, 4,096 Markdown files, 32 levels, or 64 MiB of Markdown.

Task IDs use uppercase hyphen-separated segments, such as `TEAM-123` or `RBE-024`. Keep explanatory readiness prose outside the status declaration: the declaration line is exactly `Packet status: READY`, `Packet status: BLOCKED_BY_SPEC`, or `Packet status: NO_CHANGE_NEEDED`.

The schema has two preferred Markdown renderings and one legacy-compatible rendering:

- Standalone packet: use the `##` headings in the template below.
- Embedded ledger packet: begin with `#### Qwen3-Coder-Next packet`, then render each of the same 15 labels in the same order as `- **Readiness:**`, `- **Objective:**`, through `- **Handoff:**`. Indent each label's list content beneath it. `Acceptance criteria` is an allowed display alias for `Acceptance`.
- Legacy embedded ledger packet: a validator may accept a bold `**Qwen3-Coder-Next packet**` marker followed by the same labels as standalone bold lines such as `**Readiness**`. Preserve this rendering when validating an existing ledger, but do not emit it for a new packet.

Do not mix renderings inside one packet. The representation changes; the required information does not. In an embedded ledger packet, `Handoff` is terminal: any following labeled prose belongs to the surrounding legacy task detail, and no packet field may be appended after it.

Readiness outcomes are fixed:

- `READY` - execute the packet.
- `BLOCKED_BY_SPEC` - stop and resolve the named specification or evidence gap.
- `NO_CHANGE_NEEDED` - do not queue implementation; retain the proof that acceptance already holds.

## Epic dossier

```markdown
# Epic: [name]

## Desired end state
[Observable system outcome.]

## Architecture contract
- Ownership and system boundaries:
- Decisions already made:
- Public API and data contracts:
- Error and compatibility behavior:
- Security and concurrency requirements:
- Rollout and rollback constraints:

## Non-goals
- [Explicitly excluded work.]

## Execution DAG
- [TASK-01] -> [TASK-02]
- [TASK-01] -> [TASK-03]
- [TASK-02, TASK-03] -> [INTEGRATION-01]
```

## Task packet

```markdown
# Task: [ID] - [title]

## Readiness
- Packet status: READY
- Canonical tracker status: [roadmap or ledger status, informational only]
- Evidence checked at: [full commit object ID for every repository]
- Execution unit: [one writable repository, branch lineage, and delivery history]
- Outcome reason: [facts that justify READY, BLOCKED_BY_SPEC, or NO_CHANGE_NEEDED]
- Revalidate when: [ref, prerequisite, input, instruction, or worktree condition that invalidates this packet]

## Objective
[One observable behavior to implement.]

## Why
[How this advances the epic and why this task is separate.]

## Scope
- In scope: [Exact repository, behavior, and write boundaries.]
- Out of scope: [Adjacent work that remains excluded.]

## Starting point
- Repository inventory:
  - Repeat the following fields for every repository.
  - Repository identity: [repo-id]
  - Canonical root and execution working directory: [absolute path]
  - Role: [the one writable repository, or read-only evidence/input]
  - Base commit: [immutable full commit object ID]
  - Informational branch or ref: [not a substitute for the commit]
  - Tracked and untracked state: [exact status or isolated-checkout precondition]
- Committed evidence boundary: [what was verified with the pinned commit and what local state, if any, is explicitly outside it]
- Worktree and collision state: [clean or isolated checkout requirement, tracked and untracked status command, overlapping changes, locks, output paths, retry identity]
- Applicable repository instructions:
- Prerequisite tasks and required outputs:
- Exact read set: [Every file, generated artifact, local input, and instruction source the worker may read.]
- Exact write set: [Every file or artifact the worker may create, edit, move, or remove.]
- Existing files and symbols, with `repo-id:path:line @ <full-commit-object-id>` evidence:
- Proposed files and symbols:
- Reference implementation or pattern, with `path:line` evidence:

## Decisions already made
- [Ownership, API shape, data shape, error semantics, compatibility, security, concurrency, or rollout decisions this task must preserve.]

## Decision authority
- The worker may decide: [local control flow, private naming, fixtures, or trivial compile repairs allowed within this contract.]
- The worker must not decide: [public API, architecture, ownership, persistence, schema, dependency, security, error, compatibility, or scope choices already fixed or requiring escalation.]

## Contract
- Inputs: [Every committed, generated, local, or ignored input the worker may consume.]
- Local or ignored input manifest: [Write exactly `None - no local or ignored files are consumed`, or use one line per file as ``- `/canonical/absolute/path` | type: regular file | bytes: 123 | sha256: <64 lowercase hex>``. A directory input requires a deterministic manifest file plus one entry for that file and every consumed member.]
- Input provenance and preflight: [producer task/revision, digest, byte length, schema, path resolution, and consumer usability]
- Outputs:
- Errors:
- Compatibility:
- Security and trust boundaries:
- Credential and toolchain provenance: [actual capability, preferred minimum scope, injection point, lockfile or image identity, and forbidden ambient credentials or installs]
- Concurrency or ordering:
- Idempotency, retry, and recovery:

## Change required
1. [Runnable preflight that proves the starting state and detects overlap or stale inputs.]
2. [Reproducer or failing test, with expected failure when applicable.]
3. [Concrete implementation action with exact input and observable output.]
4. [Follow-up action needed to complete the bounded behavior.]
5. Read each complete target file before editing; never reconstruct a file from a snippet, search result, or partial transcript.

## Invariants
- [Behavior that must remain true.]

## Non-goals
- [Work excluded from this packet.]

## Acceptance
- Normal case: [input/state] -> [observable result] -> [proof].
- Boundary or failure case: [input/state] -> [observable result] -> [proof].
- Compatibility case: [existing consumer/state] -> [unchanged result] -> [proof].
- Security or concurrency case: [when applicable; otherwise `Not applicable - <reason>`].

## Verify
1. Run from `[working directory]`: `[assert mutable refs resolve to the pinned full commit, then run the current-state preflight or blocker reproducer against that object]` - expected [result]; proves [claim].
2. Run from `[working directory]`: `[post-change focused command]` - expected [result]; proves [one acceptance case].
3. Run from `[working directory]`: `[broader test, typecheck, lint, or build command]` - expected [result]; proves [regression boundary].
4. Run from `[working directory]`: `[live, artifact, or cross-repository command when required]` - expected [result]; proves [external acceptance claim].
- CI proof rule: prove every job from its own clean checkout and independently declared setup; do not reuse unstated local install state.

## Escalate, do not assume, if
- [A referenced existing item is missing or materially different.]
- [The change requires an unresolved decision, new dependency, schema change, or scope expansion.]

## Handoff
Report starting and final revisions, changed files, acceptance cases, commands actually run with results, retained artifact identities and digests, discrepancies from this packet, remaining risks, and whether a separate PR action is authorized.
```

## Packet completeness and outcome check

A packet is complete only when:

- Every field is present in the documented order and one rendering; a non-applicable field uses `Not applicable - <reason>`.
- Its readiness status is exactly one of `READY`, `BLOCKED_BY_SPEC`, or `NO_CHANGE_NEEDED`.
- Its in-scope and out-of-scope boundaries are explicit.
- Existing and proposed code are unambiguous.
- Committed evidence and local or dirty evidence are explicitly separated.
- Dependencies identify producer outputs; parallel and cross-repository write boundaries are explicit.
- The contract enumerates every local or ignored file the worker may consume, including a deterministic member manifest for a directory or compound input; an empty manifest is explicit.
- A `READY` packet has no unresolved consequential choice, closes every implementation assumption as fixed, locally decidable, or an escalation trigger, and maps each acceptance case to proof.
- A `READY` packet has usable inputs, non-colliding output identities, safe retry or recovery, a runnable current-state preflight, and clearly labeled post-change proof commands available through the planned change.
- A `BLOCKED_BY_SPEC` packet names each missing or conflicting fact or decision, its owner, the exact output that unlocks replanning, and a safe current-state reproducer when one exists. If no repository or safe reproducer exists, Verify says `Not applicable - <reason>`.
- A `NO_CHANGE_NEEDED` packet has no unresolved consequential choice and runs current-state proof for every acceptance case from its pinned clean or isolated state, including required runtime, artifact, browser, served-response, or cross-repository claims.
- The worker knows exactly when to stop and escalate.
