---
name: delivery-loop
description: "Bounded task-delivery conductor: research, plan, implement, focused verification, architecture and security review, adversarial review, smoke test, PR shipping, remote-head verification, and merge handoff. Use for delivery loops, pause or resume work, same-PR continuation, multi-agent delivery, or any guarded end-to-end workflow."
license: MIT
metadata:
  display-name: "Delivery Loop"
  version: "1.2"
  platforms: "claude-code codex"
  tags: "workflow orchestration quality process"
---

# Delivery loop

Conductor for non-trivial task work. It selects the next phase, delegates read-only specialist work, records durable evidence, and stops at human gates.

Read `references/delivery-checklist.md` and `references/delivery-state-template.md` at the start of a run. Keep both the durable state and the concise user-facing status current.

## Core rules

- If no accepted plan exists, research as needed, draft a `<proposed_plan>`, and stop for approval before implementation.
- If the user explicitly approved a plan in the current conversation, continue into implementation and verification.
- The primary agent is the sole writer for a repository. Parallel agents are read-only by default. QA receives write ownership only through an explicit handoff recorded in delivery state, after the previous writer stops writing.
- Use one branch and one canonical PR per unit of work. Do not create stacked or duplicate PRs.
- Keep loops bounded. Stop with evidence, the blocker, and the next decision when the retry limits are reached.
- Never merge into a protected branch unless the current user message explicitly names that branch as the merge target and asks to merge it. A release, PR, approval, or general shipping request is not merge authorization.
- Do not commit, push, create or update a PR, merge, rebase, run destructive Git commands, install dependencies, or perform live security testing without explicit authorization.
- Repository-local instructions and project workflow skills outrank this generic guidance.

## Repository discovery and state

Before creating a branch or writing files:

1. Fetch the relevant remotes.
2. Perform repository-wide discovery of local and remote branches, worktrees, open PRs, the default branch, and working-tree changes.
3. Reuse the canonical branch, worktree, and PR when one already exists for the task.
4. Create `.codex/delivery-state/<task>.md` from the state template. Keep it ignored through a repository rule or the local `.git/info/exclude`; never commit it.

Update delivery state after every phase, writer handoff, failure, pause, resumed run, or material remote change. Do not store credentials, private denylist terms, or sensitive logs. When a PR exists, mirror the non-sensitive state block into its body.

On resume, fetch remotes and detect drift across the base, local branch, remote branch, PR head, worktrees, and tracked files before writing. Reconcile safe drift or stop with the exact conflict. A request to pause records active agents, processes, checks, blockers, and the next gate before work stops.

## Phase map

Per-phase inputs, exit evidence, and stop conditions live in the checklist.

1. **Intake** - Confirm the repository, goal, constraints, accepted-plan state, writer, and browser policy.
2. **Research** (`task-research`) - Resolve uncertain prior art, APIs, and feasibility from local sources first.
3. **Plan gate** - Produce a decision-complete plan and wait unless approval already exists.
4. **Implementation** - Apply the accepted plan through the sole writer.
5. **Focused verification** (`qa-automation`, `see-it-live`, and `e2e-qa` only when allowed) - Prove the changed path with the smallest checks, then run the broader relevant suite.
6. **Architecture and security review** (`architect-review`, then `security-review`) - Review boundaries, dependency direction, failure handling, and trust surfaces before falsification.
7. **Adversarial review** (`adversarial-review`) - Independently try to break the riskiest remaining claim with a concrete input or interleaving.
8. **Final smoke** (`see-it-live`, smoke mode) - Run the critical path after all review fixes and before shipping.
9. **PR shipping** (`fast-pr-workflow`) - Commit, push, and create or update the one canonical PR after authorization.
10. **Remote-head verification** - Fetch and prove local `HEAD`, remote branch head, and PR head are the same commit. Update the PR state block.
11. **Await merge** - Leave the PR open and report evidence, remaining risks, and the human gate.

If implementation changes after a review or smoke failure, return to focused verification and repeat every later phase. Do not ship a reviewed-but-stale diff.

## Collaboration contract

- Give each parallel agent a bounded read-only question, its allowed paths and commands, and the exact skills it must use.
- All collaborators are idle before shipping. Record their final state and terminate or wait for mutating processes before staging.
- The sole writer inspects the complete diff. A reviewer or QA agent does not edit, stage, commit, push, or update the PR unless the durable state names an explicit writer handoff.
- Claude Code can preload skills declared in an agent definition. Codex dispatch must explicitly instruct each subagent to read the named `SKILL.md` files completely before acting. Never assume cross-host preloading.

## Browser resource policy

- Record browser policy as `allowed`, `leased`, or `forbidden` before verification.
- Default to one browser suite and one worker. Run an allowed local suite through `scripts/browser-suite-lease.py`; the helper fails immediately when another suite owns the host-wide lease and exports `AI_SKILLS_BROWSER_WORKERS=1` by default.
- The invoked runner must consume `AI_SKILLS_BROWSER_WORKERS` or receive its equivalent explicit worker flag.
- A repository profile may forbid local browser execution. Do not bypass that policy; use its approved remote lane.
- Never use real Chromium in lease unit tests. Use bounded dummy commands.

## Quality and review policy

For each failed check, classify it as a product defect, test defect, environment issue, or out-of-scope preexisting failure. Fix scoped product or test defects, rerun the smallest affected check, then rerun the broader relevant suite.

Architecture review runs before the independent adversarial pass. Security review is required for automation, dependencies, credentials, untrusted inputs, filesystem behavior, or publication surfaces. Only fix findings that are real, scoped, and tied to the task; record broader follow-ups separately.

Stop when the same focused failure survives two fix attempts, three total quality cycles fail to converge, or the next action needs new scope, credentials, a destructive change, or an external human decision.

## Shipping invariants

Before staging, verify the base, branch, worktree, diff, canonical PR, writer, agent status, and relevant processes from durable state. After pushing:

- Fetch the remote branch without rebasing.
- Compare the full local, remote, and PR commit IDs, not abbreviated hashes.
- Treat a missing or mismatched remote or PR head as a failed shipping phase.
- Mirror checks, blockers, browser policy, and the next gate into the PR body without sensitive local data.

## Handoff

Report the phase, branch, commit, PR URL, checks and actual results, failures and fixes, review verdicts, browser policy, blockers, and next human gate. Never merge at handoff unless the current request explicitly authorizes the named protected target.

## Gotchas

- Chat memory is not delivery state. A pause, resume, handoff, or context reset must continue from the fetched repository and durable state, not from recalled prose.
- Routing changes require matching updates to `routing/skill-rules.json` and `routing/routing-expectations.json`.
