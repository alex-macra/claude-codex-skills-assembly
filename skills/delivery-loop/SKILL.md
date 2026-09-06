---
name: delivery-loop
description: "Execute an approved Markdown task packet through a bounded loop: validate it against the repository, implement it, run targeted tests and builds, fix failures, and retest. Use for delivery loops, executing task Markdown, implementing a task packet, or test-build-fix-retest work. Research and planning belong to the Spark task skills; PR work belongs to fast-pr-workflow."
license: MIT
metadata:
  display-name: "Delivery Loop"
  version: "2.0"
  platforms: "claude-code codex"
  tags: "workflow implementation verification repair"
---

# Delivery loop

Execute one approved Markdown task packet without reopening settled product or architecture decisions.

Read [references/delivery-checklist.md](references/delivery-checklist.md) at the start of the run and keep its concise evidence block current.

## Entry contract

- Identify the exact task Markdown named by the request. Stop if more than one file could be the authority.
- Treat the task as an execution contract, not proof that its repository claims are current.
- The current request must authorize implementation. A packet produced by another skill does not grant permission by itself.
- Research and decomposition are complete before this loop. Route missing evidence to `spark-task-research` and unresolved planning to `spark-task-planning` instead of solving them silently during implementation.
- Repository instructions and project workflow skills outrank the packet when they conflict.

## Four phases

1. **Validate task Markdown**
   - Read the packet and applicable repository instructions completely.
   - Verify the base commit or ref, prerequisite outputs, referenced files, symbols, behaviors, dependencies, and verification commands against the checkout.
   - Confirm every top-level packet section is present and mandatory: Readiness, Objective, Why, Scope, Starting point, Decisions already made, Decision authority, Contract, Change required, Invariants, Non-goals, Acceptance, Verify, Escalate, and Handoff. A section that truly does not apply must remain present and say `Not applicable - <reason>`.
   - Confirm the packet distinguishes existing code from proposed work.
   - Record exactly one outcome: `READY`, `BLOCKED_BY_SPEC`, or `NO_CHANGE_NEEDED`.
   - `READY` enters implementation. `BLOCKED_BY_SPEC` stops before editing with the conflicting claim, repository evidence, and decision needed. `NO_CHANGE_NEEDED` records no implementation change and runs the packet's verification commands before handoff.
2. **Implement**
   - Make only the changes required by the validated packet, using the repository's existing patterns and relevant stack skills.
   - Read each complete target file before editing. Never reconstruct a file from a snippet, search result, or partial transcript.
   - Preserve unrelated work and every stated invariant, public contract, compatibility rule, and non-goal.
   - Do not weaken acceptance criteria or tests to make the implementation pass.
   - Return to the validation gate if repository evidence changes or implementation appears to require new scope, a dependency, schema work, or another unsettled decision.
3. **Test and build**
   - Run the packet's focused checks first, then its broader relevant tests, type checks, linters, or build commands.
   - Add or update a regression test when the packet requires one and the repository has an established test location.
   - Record exact commands and actual results. Classify failures as product, test, environment, or preexisting.
4. **Fix and retest**
   - Fix only in-scope product or test defects.
   - Rerun the smallest check that proves each fix, then rerun every broader command affected by the change.
   - Repeat until the packet's acceptance and verification contract is green or a stop condition is reached.

## Loop bounds

Stop after two materially similar failed repair attempts, after three repair cycles without convergence, or when progress needs credentials, dependency installation, destructive action, external service access, or expanded scope. Produce a diagnostic handoff with the failing command, observed output, attempted fixes, and unresolved question.

## Optional durable state

Use durable state only for work likely to cross sessions or explicit pause/resume requests. Run `scripts/delivery-state.py init <task> --repository .`, then update the generated record after each phase or material failure. On resume, run `scripts/delivery-state.py verify <task> --repository .` before writing.

Do not hand-create or reimplement private state. The helper rejects symlinked parents and targets, rejects hardlinked targets, enforces mode `0600`, and verifies the state is actually ignored and untracked. State records evidence only; it does not add phases or authorize implementation, Git, or external actions.

When an allowed browser command needs the shared local browser resource, run it through `scripts/browser-suite-lease.py` and pass the exported worker limit to the runner. Browser coordination is part of test execution, not a separate phase.

## Optional PR handoff

PR work is not a delivery phase. After all required checks pass, invoke `fast-pr-workflow` only when the current request explicitly authorizes the relevant commit, push, or pull-request action. Otherwise stop with a local handoff that is ready for that workflow.

## Handoff

Report the task file, readiness outcome, changed files, commands and actual results, failures and fixes, reruns, discrepancies, blockers, and whether `fast-pr-workflow` was authorized. Keep it factual and concise.
