# Delivery checklist

Use this checklist to execute one approved Markdown task packet. The four rows below are the complete delivery phase sequence.

## Evidence block

```markdown
**Delivery Status**
- Task file:
- Phase:
- Readiness outcome:
- Changed files:
- Commands and results:
- Failures:
- Fixes:
- Reruns:
- Discrepancies:
- Blockers:
- Next gate:
```

## Phase contract

| Phase | Required input | Exit evidence | Stop condition | Next gate |
| --- | --- | --- | --- | --- |
| Validate task Markdown | One approved task file and the target checkout. | Repository facts verified and one outcome recorded: `READY`, `BLOCKED_BY_SPEC`, or `NO_CHANGE_NEEDED`. | `BLOCKED_BY_SPEC`, ambiguous authority, or missing prerequisite. | Implement when `READY`; verify without edits when `NO_CHANGE_NEEDED`. |
| Implement | A validated packet with no unresolved design choice. | Scoped diff satisfies the required change while preserving invariants and non-goals. | New scope, dependency, schema work, credentials, or unsettled decision is required. | Test and build. |
| Test and build | Current diff and the packet's verification contract. | Exact focused and broader commands run; actual results and failure classes recorded. | Required environment or access is unavailable. | Fix and retest, or handoff when green. |
| Fix and retest | An in-scope product or test failure with a reproducer. | Fix recorded; focused proof and affected broader checks rerun. | Two similar repairs fail, three cycles do not converge, or the fix leaves packet scope. | Test and build until green, then handoff. |

## 1. Validate task Markdown

- Read repository instructions and the entire task file.
- Resolve the repository, branch, base commit or ref, prerequisite task outputs, and allowed scope.
- Record full commit IDs, upstream refs, worktree overlap, and which evidence is committed versus local or ignored.
- Inspect immutable evidence by object ID. Assert mutable refs resolve to their expected full commits before using them, and never substitute checkout `HEAD` for the packet base.
- Verify every referenced existing file, symbol, behavior, dependency, pattern, and command.
- Verify one writable repository and delivery history, exact read and write sets, predecessor artifact identities, and a collision-safe retry or recovery path.
- Classify each command as current-state or post-change proof; run safe preflight and record its expected and actual result.
- Bind tools, locks, CI-job setup, and any credential to explicit provenance and minimum scope. Reject unprovenanced ambient installs and implicit cross-job state.
- Confirm proposed files and symbols are labeled as proposed.
- Require every mandatory top-level section or equivalent embedded-ledger field: Readiness, Objective, Why, Scope, Starting point, Decisions already made, Decision authority, Contract, Change required, Invariants, Non-goals, Acceptance, Verify, Escalate, and Handoff. A field that truly does not apply remains present and says `Not applicable - <reason>`.
- Treat canonical tracker status as informational. Only the packet's fixed readiness outcome controls delivery.
- Record `READY` when the task is decision-complete and has a clean or isolated execution state, `BLOCKED_BY_SPEC` for material conflicts or missing decisions, or `NO_CHANGE_NEEDED` when acceptance is already satisfied from a pinned clean or isolated state.
- Stop before editing on `BLOCKED_BY_SPEC`. Do not silently replan the task.
- On `NO_CHANGE_NEEDED`, skip code edits and prove every acceptance case. Internal-only proof is insufficient when acceptance requires another repository, runtime, browser, artifact, or served response.

## 2. Implement

- Follow the validated contract and existing repository patterns.
- Preserve unrelated changes and declared invariants, interfaces, errors, compatibility, security, and concurrency behavior.
- Do not weaken acceptance criteria or tests to get green.
- Return to validation if the starting evidence changes materially.

## 3. Test and build

- Run the cheapest focused command first.
- Run broader tests, type checks, linters, and builds named by the packet when relevant.
- Capture commands and actual output, including pass counts, failures, timings, and skipped checks when available.
- Classify each failure as product, test, environment, or preexisting.
- For browser work, obey repository browser policy and use `scripts/browser-suite-lease.py` when the shared local lease is required.

## 4. Fix and retest

- Fix only in-scope product and test defects.
- Rerun the smallest proof after each fix.
- Rerun affected broader commands after focused checks pass.
- Stop after two materially similar failed repairs or three repair cycles without convergence.
- On stop, record the reproducer, observed failure, attempted fixes, and unresolved question.

## Optional state

For work that will cross sessions, use `scripts/delivery-state.py init <task> --repository .` and update the generated record after phases and material failures. Run `verify` before resuming. Do not hand-create or reimplement the state file. Optional state records the four-phase evidence; it does not add a workflow phase or grant authority.

## Optional PR handoff

- PR work starts only after the four-phase loop is green.
- Invoke `fast-pr-workflow` only when the current request authorizes the relevant Git or pull-request actions.
- Without that authorization, report a PR-ready local handoff and stop.
