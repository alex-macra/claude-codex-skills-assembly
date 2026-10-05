# Delivery checklist

The eight rows below are the complete delivery phase sequence. Keep the evidence block current; it is the handoff.

## Evidence block

```markdown
**Delivery Status**
- Task file and Task ID:
- Phase and readiness outcome:
- Changed files:
- Commands and results:
- Failures, fixes, and reruns:
- Review verdicts:
- Final smoke:
- Branch and commit:
- Pull request:
- Tracker lines and inbox entries applied:
- Discrepancies and blockers:
- Next gate:
```

## Phase contract

| Phase | Skill when relevant | Exit evidence | Stop condition |
| --- | --- | --- | --- |
| Validate task Markdown | `task-research` | Facts verified at the pinned base; one readiness outcome. | Conflicting claim, ambiguous authority, or missing prerequisite. |
| Implement | `web-dev` | Scoped diff meets the change and keeps invariants and non-goals. | New scope, dependency, schema work, credentials, or an open decision. |
| Test and build | `qa-automation` | Focused, then broader commands run; results and failure classes recorded. | Required environment or access is unavailable. |
| Fix and retest | `qa-automation` | Each fix proven by the smallest check; affected broader checks rerun. | A loop bound is hit or the fix leaves scope. |
| Architecture and adversarial review | `architect-review`, `adversarial-review`, `security-review` | Architecture pass, then falsification of the exact diff; findings resolved or accepted. | A finding needs new scope or an owner decision. |
| Final smoke | `see-it-live` | Declared critical path passes on the reviewed candidate after the last fix. | Required runtime evidence is unavailable or fails. |
| Commit, push, and open PR | `fast-pr-workflow` | One focused commit, matching remote topic branch, one open canonical pull request. | Exclusion, missing credentials, protected destination, or ambiguous scope. |
| Verify remote handoff | `fast-pr-workflow` | Repository, base, topic, open state, and full local, remote, and PR head IDs match. | Missing, duplicate, closed, stale, or mismatched pull request. |

## 1. Validate task Markdown

- Read repository instructions and the whole packet. Record full `HEAD`, branch, upstream, worktree status, and which evidence is committed versus dirty or ignored.
- Inspect evidence by object ID at the pinned base commit or ref; assert a mutable ref's full ID first and never let checkout `HEAD` stand in for the base.
- Verify referenced files, symbols, behaviors, dependencies, prerequisite output identities and digests, and commands; proposed work must be labeled as proposed.
- Confirm one writable repository and delivery history, exact read and write sets, and a collision-safe retry path. Classify each command as current-state or post-change proof; run safe preflight.
- Bind tools and credentials to explicit provenance and least privilege; capability is not authorization. Reject unprovenanced ambient installs and implicit cross-job state.
- Require every section: Readiness, Objective, Why, Scope, Starting point, Decisions already made, Decision authority, Contract, Change required, Invariants, Non-goals, Acceptance, Verify, Escalate, Handoff; one that does not apply says `Not applicable - <reason>`. Run a validator named in Verify; structural green never replaces evidence checks.
- Only the packet's readiness controls the loop; tracker status is informational. `READY` needs a clean or isolated state. Stop before editing on `BLOCKED_BY_SPEC`. On `NO_CHANGE_NEEDED`, prove every acceptance case end to end and stop without an empty commit, push, or PR. A tracked task runs `claim` after `READY` unless its conductor claimed before dispatch.

## 2. Implement

- Follow the validated contract and existing patterns; read each whole target file before editing. Preserve unrelated changes and declared interfaces, errors, compatibility, security, and concurrency behavior.
- Do not weaken acceptance criteria or tests to get green. Return to validation if the starting evidence changes materially.

## 3. Test and build

- Run the cheapest focused command first, then the broader tests, type checks, linters, and builds the packet names.
- Capture commands and actual output with counts and skipped checks. Classify each failure as product, test, environment, or preexisting.
- Browser work obeys repository browser policy and uses `scripts/browser-suite-lease.py` when the shared lease is required. A tracked task checkpoints this gate as `verify`.

## 4. Fix and retest

- Fix only in-scope defects; rerun the smallest proof, then affected broader commands. Stop after two materially similar failed repairs or three repair cycles without convergence, with the reproducer, failure, attempts, and open question.

## 5. Architecture and adversarial review

- Architecture review before adversarial falsification; add security, accessibility, reuse, and comment checks when the surface needs them.
- A real finding returns to implementation and repeats every later phase.

## 6. Final smoke

- Run the repository-declared critical journey on the final reviewed candidate and record the exact command or served path and result; never substitute a narrower internal check.

## 7. Commit, push, and open PR

- An explicit delivery-loop request authorizes this topic-branch bundle unless the user excludes an action. Commit only the validated diff, push the non-protected branch, and create or update one canonical pull request carrying validation, review, smoke, risks, and one `Task: <ID>` line per tracked task.
- Enter a shipping freeze after the push; merge and release stay separate gates.

## 8. Verify remote handoff

- Require exactly one open pull request for the intended repository, base, and topic branch, with matching full local `HEAD`, remote branch head, and PR head IDs; any mismatch fails the phase.
- A tracked task runs `review` with the exact URL. Report the URL on its own line and stop before merge.
