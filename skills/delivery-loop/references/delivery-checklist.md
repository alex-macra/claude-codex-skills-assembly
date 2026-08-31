# Delivery checklist

Use this checklist as the execution record. Create `.codex/delivery-state/<task>.md` from `delivery-state-template.md` and keep it ignored. Mirror its non-sensitive contents into the canonical PR body when a PR is available.

## User-facing status block

```markdown
**Delivery Status**
- Phase:
- Goal:
- Current evidence:
- Checks run:
- Failures and fixes:
- Review findings:
- PR:
- Blockers:
- Next gate:
```

## Phase checklist

| Phase | Required input | Exit evidence | Stop condition | Next gate |
| --- | --- | --- | --- | --- |
| Intake | Goal, repository, constraints, accepted-plan state, browser policy. | Durable state names the repository, base, writer, policy, and goal. | Goal, repository, or authority is ambiguous. | Research or plan gate. |
| Research | Intake plus the uncertain question. | Local sources and prior art checked; facts and assumptions separated. | A material choice still needs the user. | Plan gate. |
| Plan gate | Goal and decision-complete evidence. | Approved plan recorded. | Current conversation contains no approval. | Implementation. |
| Implementation | Approved plan, sole writer, cleanly bounded files. | Scoped diff and affected checks recorded. | Work needs new scope, a dependency, credentials, or destructive action. | Focused verification. |
| Focused verification | Current diff and cheapest relevant checks. | Changed path proven, broader relevant suite green, failures classified. | Retry limit reached or required environment unavailable. | Architecture and security review. |
| Architecture and security review | Current diff and verification evidence. | Boundary, dependency, failure, and trust-surface findings recorded and fixed or dispositioned. | Finding requires scope or user decision. | Adversarial review. |
| Adversarial review | Reviewed diff without first-review framing. | Concrete falsification attempts and verdict recorded. | Real defect needs broader redesign or authority. | Final smoke. |
| Final smoke | Final reviewed tree and critical path. | Fast critical path passes without tracked changes. | Smoke fails or mutates tracked state. | PR shipping. |
| PR shipping | Authorization, green tree, idle collaborators, canonical branch and PR. | Commit pushed and one PR created or updated. | Authorization missing or repository-wide discovery is stale. | Remote-head verification. |
| Remote-head verification | Local commit, fetched remote, canonical PR. | Full local, remote, and PR commit IDs match. | Any head is missing or differs. | Await merge. |
| Await merge | Verified PR and handoff evidence. | PR remains open with next human gate stated. | Merge or release lacks current explicit authority. | User decision. |

## 1. Intake

- Confirm the current repository, default branch, worktree, user goal, constraints, and accepted plan.
- Name the sole writer. Other agents are read-only unless durable state records an explicit handoff.
- Set browser policy to `allowed`, `leased`, or `forbidden`; default local capacity is one suite and one worker.
- Fetch remotes and perform repository-wide discovery of branches, worktrees, open PRs, tracked changes, and running task processes before creating a branch.
- Reuse the canonical branch and PR. Stop on ambiguous or overlapping work.

## 2. Research

- Search local code and project instructions first.
- Read every selected skill completely, including required references.
- Use external sources only when local evidence cannot answer the question.
- Record verified facts separately from assumptions.

## 3. Plan gate

- Produce one decision-complete `<proposed_plan>` when approval is absent.
- Record approval from the current conversation before implementation.

## 4. Implementation

- Keep the primary agent as sole writer.
- Give parallel agents bounded read-only tasks and allowed paths.
- QA may write only after an explicit ownership handoff; the previous writer must stop first.
- Preserve unrelated files and update durable state after material changes.

## 5. Focused verification

- Run the cheapest focused check first and reproduce a defect before fixing it.
- Classify each failure as product, test, environment, or preexisting.
- Rerun the focused check after a fix, then the broader relevant suite once.
- Use `scripts/browser-suite-lease.py` for allowed browser work and pass its worker count to the runner. Respect `forbidden` without fallback.
- Capture actual pass counts, failures, timings, and skipped checks.

## 6. Architecture and security review

- Read the complete diff against the intended base.
- Review module boundaries, dependency direction, cohesion, failure paths, and testability.
- Review security for automation, filesystem, command, credential, dependency, publication, or untrusted-input surfaces.
- Apply only real scoped fixes, then return to focused verification.

## 7. Adversarial review

- Start from the required invariants, not the first review's conclusions.
- Attack malformed inputs, errors, ordering, concurrency, trust boundaries, and resource limits.
- Record a concrete failing scenario for every defect or name the attacks that did not break the claim.
- After any fix, repeat focused verification, architecture and security review, then adversarial review.

## 8. Final smoke

- Confirm all collaborators are idle and mutating processes are stopped.
- Run the fastest critical-path proof on the final reviewed tree.
- If the smoke mutates tracked state or fails, return to implementation.

## 9. PR shipping

- Refresh repository-wide branches, worktrees, PRs, writer, agents, processes, and diff.
- Stage only reviewed task files; keep delivery state ignored.
- Commit and push only with existing authorization.
- Create or update one canonical PR and mirror the non-sensitive state block into its body.
- Do not merge.

## 10. Remote-head verification

- Fetch the pushed branch without rebasing.
- Resolve full commit IDs for local `HEAD`, the remote branch, and the PR head.
- Require all three IDs to match. A stale PR, incomplete push, or local-only commit fails this phase.
- Update durable state and the PR body with the verified head and tree.

## 11. Await merge

- Report branch, commit, tree, PR URL, validation, review verdicts, browser policy, remaining risks, and next gate.
- Leave protected branches unmerged unless the current request explicitly names the target and requests the merge.

## Pause and resume

- On pause, update durable state with agents, processes, browser lease, checks, failures, blockers, and next gate. Stop or identify every live process.
- On resume, read durable state, fetch remotes, repeat repository-wide discovery, and compare base, local, remote, PR, worktrees, and tracked changes before writing.
- If drift is safe, record how it was reconciled. If ownership or scope is ambiguous, stop for direction.

## Retry limits

- Stop after two failed fixes for the same focused defect.
- Stop after three full quality cycles without convergence.
- Stop before new dependencies, credentials, destructive operations, external mutations, or expanded scope without authority.
