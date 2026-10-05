# Conduct several packets

The in-session loop: you conduct, builders build. One builder per packet, one writer per repository at a time. You own landing, tracker calls, and the run ID per task. Never execute a packet's phases in your own context.

## Team by size

| Size | Signal | Team |
|---|---|---|
| quick | write bound of about 80 lines; no browser, engine or detached gate | one builder; you verify |
| medium | one packet, several files, a test or build gate | builder, then `reviewer` |
| large | write bound over about 400 lines, any such gate, or several packets | builders in series, `reviewer`, fresh-reviewer validation, milestone gate |

Roles: a builder runs `delivery-loop` with `no push, no PR`; `reviewer` reviews and validates; `task-research` researches. Readers run in parallel; one writer per repository.

## Brief and return

Brief: objective in one sentence; repository, worktree, base commit, write set; forbidden actions; the acceptance command; the output format; a turn or time cap; the run directory and the task's run ID. Codex: name the `SKILL.md` files to read. Claude Code: the agent definition preloads them.

Return, exactly one of:
- `DONE <sha> <handoff>`
- `BLOCKED <question> | <options> | <default> | <evidence path:line>`
- `BUDGET <left>`
- `REFUSED <rule>`

A write outside the write set, a weakened test, or a decision the packet fixes is always BLOCKED. Your rulings go into the next brief as numbered amendments that override the packet.

## Worktree and re-pin

Create the worktree yourself from the rolling tip: `git worktree add -b <task-branch> <path> <tip>`. The builder first asserts that `git rev-parse HEAD` equals the tip, else BLOCKED. Before dispatch, check that the packet base is an ancestor of the tip and that its anchors still match, then log `REPIN ok <tip>` or `REPIN blocked <claim>`. Drift re-pins; it never defers.

## Claim before dispatch

You claim a tracked task, never its builder: after `REPIN ok`, choose the run ID and run tracker `claim --packet <file>` before dispatch. Exit 3: do not dispatch; record the task `blocked` and move on. A `skipped` line: retry once, then block the task; never dispatch an unclaimed tracked task. A builder that returns `BLOCKED` gets `checkpoint --phase blocked --outcome blocked` from you.

## Landing

Builders stop at one commit plus the handoff. Under an explicit request to run `delivery-loop` or the orchestrator, you fast-forward the rolling branch to that commit, push, and create or update the PR through `fast-pr-workflow`; otherwise stop at the builder commit and report. One commit per task; a tracked task's commit message ends with `Task: <ID>`.

## Rolling PR

Per product repository: one topic branch, at most one open PR, one commit per task, fast-forward only.
- Never force-push, rebase a pushed commit, or merge the base in unless the owner asks.
- Merged mid-run: new branch from the updated base, `git cherry-pick -x` the in-flight commit, rerun its gates, open a new PR at the next landing.
- Remote head moved: fast-forward when it descends from your tip, else stop for the owner.
- A foreign open PR: keep landing on the pushed branch; open yours and run tracker `review` after theirs closes.

## Next task

After each landing run the tracker (contract: `skills/delivery-loop/references/tracker.md`): `next --product ROOT --landed <IDs landed this run>`, and take the first packet that validates `READY`. Without a tracker, or on `NEXT none`: the next `READY` packet in the request's list whose dependencies are closed or landed this run. When none remain: milestone gate, then stop with at most three proposed packets in the run directory. A `skipped` line is not an empty queue: use the request's list, retry `next` after the next landing, and when the list is done stop without the milestone gate and report the line. Never create or edit tracker rows.

## Milestone gate

Rerun the full gate suite on the rolling tip in a detached checkout. Then a fresh `reviewer` quotes or refutes each landed packet's Acceptance clauses at that tip. Gaps become owner questions before the next milestone.

## Shared resources

Readers never start engine or browser runs. Browser suites go through the `delivery-loop` lease helper (`skills/delivery-loop/scripts/browser-suite-lease.py`), one worker by default.

## Validate claims

Never trust a builder's own pass. A fresh `reviewer` reruns the acceptance command and quotes `path:line` at the named commit; findings without a quote are dropped.

## STATE.md

In the run directory, written after every change:
- Header: repository, `Worktree: <path>` lines, rolling branch, PR URL, tip, next action, halt.
- Queue table: `task | packet | state | run ID | commit | last tracker line`. States: `queued`, `ready`, `building`, `reviewing`, `landed`, `blocked`, `waiting-owner`, `done`.
- Dated log: `- <ISO time> <task> <state> <evidence>`.

Resume: read the header and `HALT`, run the probe, map repository evidence to each row, then continue.
