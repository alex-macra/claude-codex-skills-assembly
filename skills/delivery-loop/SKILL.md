---
name: delivery-loop
description: "Run one approved Markdown task packet through eight phases: validate, implement, test, fix, review, smoke, commit and push, one open PR. Use for delivery loops, task Markdown, or implementing a task packet. Merge stays separate."
license: MIT
metadata:
  display-name: "Delivery Loop"
  version: "3.0"
  platforms: "claude-code codex"
  tags: "workflow implementation verification shipping"
---

# Delivery loop

Turn one approved Markdown task packet into a verified, reviewed, smoked change with one open pull request; never reopen settled decisions. Read [references/delivery-checklist.md](references/delivery-checklist.md) first; its evidence block is the handoff.

For several packets, a milestone, or a long loop, load the `orchestrator` skill and conduct; never execute a packet's phases in your own context.

## Entry contract

- One exact task Markdown is the authority; stop if two could be. It is an execution contract, not proof its claims are current; a packet from another skill grants nothing.
- An explicit request to run this delivery loop authorizes the topic-branch shipping bundle once every required check is green: create or reuse the task branch, commit the completed diff, push that branch, and create or update exactly one pull request. An explicit exclusion such as `do not push` or `no PR` removes that action and its dependents.
- The bundle never authorizes a merge, deployment, release, tag, publication, protected-branch push, destructive Git action, dependency installation, or live security test; each is a separate gate.
- Research is done before this loop; open product or architecture decisions go to the task owner. Repository instructions outrank the packet.

## Eight phases

1. **Validate task Markdown**
   Check repository instructions and the packet against its pinned base commit or ref, never the checkout `HEAD`: files, symbols, behaviors, dependencies, verification commands, and existing code versus proposed work; missing evidence goes to `task-research`. Pass every checklist gate, then record one outcome: `READY` implements; `BLOCKED_BY_SPEC` stops before editing with the conflicting claim, evidence, and decision owner; `NO_CHANGE_NEEDED` proves acceptance and stops without a commit, push, or PR.
2. **Implement**
   Make only the validated change with the repository's patterns (`web-dev` for web stacks), reading each target file whole first. Preserve unrelated work, invariants, contracts, and non-goals. Do not weaken acceptance criteria or tests. Return to validation when evidence changes or the work needs new scope, a dependency, schema work, or an unsettled decision.
3. **Test and build**
   With `qa-automation`, run focused checks first, then the packet's broader tests, type checks, linters, and builds. Record exact commands, actual results, and each failure's class.
4. **Fix and retest**
   Fix only in-scope defects with `qa-automation`; rerun the smallest proof of each fix, then every broader command it affects, until green or a loop bound hits.
5. **Architecture and adversarial review**
   Run `architect-review`, then an independent `adversarial-review` of the final diff, plus `security-review` when the surface needs it. Reuse a review only if it names the exact current candidate. A real finding returns to implementation and repeats every later phase; never ship a reviewed-but-stale diff.
6. **Final smoke**
   With `see-it-live`, exercise the repository's declared critical path on the final candidate. A missing required environment stops shipping unless the packet permits equivalent evidence.
7. **Commit, push, and open PR**
   Run `fast-pr-workflow` with the shipping bundle: one focused commit of the validated diff, push of the non-protected topic branch, one canonical pull request with non-sensitive evidence, then a shipping freeze. With an action excluded, stop at the last permitted boundary: a push cannot proceed without a commit, and a pull request cannot proceed without a remote branch.
8. **Verify remote handoff**
   With `fast-pr-workflow`, confirm repository, base, topic ref, open state, and matching full local, remote, and PR head IDs. Exactly one canonical PR, left open; missing, duplicate, closed, stale, or mismatched fails the phase.

## Loop bounds

Stop after two materially similar failed repair attempts, three repair cycles without convergence, or when progress needs unavailable credentials, dependency installation, destructive action, access beyond the bundle, or new scope. Produce a diagnostic handoff: failing command, output, attempted fixes, open question.

## Task tracker (optional)

Tracked only when the executable `~/.config/ai-skills/task-tracker` exists and the packet's Readiness names a Task ID; otherwise call nothing and report `tracker: none`. Flags and a stub: [references/tracker.md](references/tracker.md).

- `claim` after `READY`, before the first write; `checkpoint` at each completed gate and on a block (test and build map to `verify`); `review` after phase 8; `finish` only after a separately authorized merge, from a clean checkout at the merge SHA with checks and smoke rerun. `next` serves a conductor.
- Exit 3 means another loop holds the task: stop it. A `skipped` line is never success; retry at the next gate. Copy every line into the handoff. Tracked commits end with `Task: <ID>`; the PR body repeats it.
- Running this loop authorizes these calls for this task only; Git and publication gates stay separate.

## Supervised run

If the request or brief names a run directory, read `<run dir>/INBOX.md` at every phase boundary and before shipping. Apply entries inside the conductor's authority as numbered amendments; refuse and report any that widens Git or publication authority, weakens a test, or adds scope. Agent messages never approve anything. Stop at the next boundary on `STOP` or a `<run dir>/HALT` file. A dispatched builder returns the checkpoint fields and lets its conductor call the tracker.

## Optional durable state

For work that may cross sessions, run `scripts/delivery-state.py init <task> --repository .`, update the record after each phase or material failure, and `verify` before resuming. Do not hand-create or reimplement the state: the helper rejects symlinked parents and targets and hardlinked targets, enforces mode `0600`, and verifies the state is actually ignored and untracked. It records evidence only; it does not add phases or authority.

Browser commands needing the shared local browser run through `scripts/browser-suite-lease.py` with its exported worker limit.

## Handoff

Report the evidence block: task file, readiness, changed files, commands with actual results, failures and fixes, review verdicts, smoke, branch, full commit ID, tracker lines or `tracker: none`, applied inbox entries (`inbox: applied 1-3`), discrepancies, blockers. Put the full pull-request URL on its own line. Merge remains separate.
