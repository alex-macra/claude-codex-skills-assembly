# Qwen-ready task packet

Use this template for fresh-context execution by Qwen3-Coder-Next. Replace bracketed prompts with repository facts. Every top-level section under Task packet is mandatory. If a section truly does not apply, keep its heading and write `Not applicable - <reason>` instead of omitting it. Do not leave unresolved choices disguised as implementation steps.

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
- Status: READY
- Evidence checked at: [commit or ref]

## Objective
[One observable behavior to implement.]

## Why
[How this advances the epic and why this task is separate.]

## Scope
- In scope: [Exact repository, behavior, and write boundaries.]
- Out of scope: [Adjacent work that remains excluded.]

## Starting point
- Repository:
- Base commit or ref:
- Applicable repository instructions:
- Prerequisite tasks and required outputs:
- Existing files and symbols, with `path:line` evidence:
- Proposed files and symbols:
- Reference implementation or pattern, with `path:line` evidence:

## Decisions already made
- [Ownership, API shape, data shape, error semantics, compatibility, security, concurrency, or rollout decisions this task must preserve.]

## Decision authority
- The worker may decide: [local control flow, private naming, fixtures, or trivial compile repairs allowed within this contract.]
- The worker must not decide: [public API, architecture, ownership, persistence, schema, dependency, security, error, compatibility, or scope choices already fixed or requiring escalation.]

## Contract
- Inputs:
- Outputs:
- Errors:
- Compatibility:
- Security and trust boundaries:
- Concurrency or ordering:

## Change required
1. [Concrete change.]
2. [Concrete change.]
3. Read each complete target file before editing; never reconstruct a file from a snippet, search result, or partial transcript.

## Invariants
- [Behavior that must remain true.]

## Non-goals
- [Work excluded from this packet.]

## Acceptance
- [Specific case and expected result.]
- [Failure or boundary case and expected result.]

## Verify
1. `[focused command]` - proves [claim].
2. `[broader command]` - proves [claim].

## Escalate, do not assume, if
- [A referenced existing item is missing or materially different.]
- [The change requires an unresolved decision, new dependency, schema change, or scope expansion.]

## Handoff
Report changed files, commands actually run, results, discrepancies from this packet, and remaining risks.
```

## Packet readiness check

A packet is ready only when:

- Every top-level section is present; a non-applicable section uses `Not applicable - <reason>`.
- It contains no unresolved product or architecture choice.
- It closes every likely implementation assumption as fixed, locally decidable, or an escalation trigger.
- Its readiness status is `READY`.
- Its in-scope and out-of-scope boundaries are explicit.
- Existing and proposed code are unambiguous.
- Dependencies and parallel write boundaries are explicit.
- Acceptance covers the behavior and important failure paths.
- Verification commands exist at the stated starting point.
- The worker knows exactly when to stop and escalate.
