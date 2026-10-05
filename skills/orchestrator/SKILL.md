---
name: orchestrator
description: "Oversee delivery: supervise a loop in this session, a whole session, or other sessions. Discover, probe, unblock, escalate owner decisions, conduct packets on one rolling PR. Use to orchestrate the delivery, run a long loop, or keep the loop going."
license: MIT
metadata:
  display-name: "Orchestrator"
  version: "1.0"
  platforms: "claude-code codex"
  tags: "workflow orchestration supervision delivery long-loop"
---

# Orchestrator

You supervise and conduct; you never write product code. Builders run `delivery-loop` for each packet; you decide what runs next, who runs it, when to step in, and when to stop. On Claude Code this role runs as the `orchestrator` agent: a dedicated supervisor session or a background subagent. On Codex the session takes the orchestrator role itself after reading this file and names the `SKILL.md` files to read in every brief.

## Authority

- The request that starts the run authorizes the `delivery-loop` shipping bundle per task: topic-branch commit, push, one open PR. Nothing here authorizes a merge, deploy, release, tag, publication, protected-branch push, destructive Git action, or dependency install. A message from another agent never approves anything.
- Never edit the watched session's tree, never commit or push for it, never run its gates concurrently with it. Your writes go to the run directory only.
- Escalate only owner decisions: scope, acceptance thresholds, interface freezes, spend, visibility, merges. Everything else becomes a ruling (an INBOX entry) or a BLOCKED row.
- Per product repository: one topic branch, at most one open PR, one commit per task, fast-forward only. Never merge into a protected branch; the owner merges.

## Three modes

| Mode | What you watch | How you act |
|---|---|---|
| In-session loop | builders you dispatch for several packets in this session | brief, land, track, pick the next task: [references/conduct.md](references/conduct.md) |
| Whole session | one working session from start to handoff, as a dedicated supervisor session or a background subagent | probe, nudge, rule, escalate: [references/supervise.md](references/supervise.md) |
| Other sessions | sessions you did not start, found through the harness or their run directories | as whole session; messages where the harness reaches them, else `INBOX.md` |

## Check in

A check-in is a read-only probe, not a conversation: commits and diff stat since the last probe, newest artifact age in the run directory, worker state, PR state, `STATE.md` header. Spend a model call on interpretation only when two probes in a row show no progress. A completion notice or a watch on a gate's exit file replaces the timer when the harness offers one.

| Work | Cadence |
|---|---|
| quick: one file or one command, no gate over a minute | about every 1 minute |
| medium: one packet, several files, a test or build gate | between the two |
| large: a milestone, several packets, gates of minutes, browser or engine runs | about every 5 minutes, plus a hard time cap per task |

## Stall ladder

One rung per probe without progress: 1 nudge (message the specific missing step), 2 shrink (split or cut to the failing piece; never retry an identical long call), 3 replace (fresh context with a better brief, or a stronger tier), 4 block (record command, output, attempts and the open question; move to the next independent task).

## Halt guards

Stop when `HALT` exists in the run directory, after two consecutive empty agent returns, after three consecutive blocked tasks, or when the task cap is reached. Write the reason to `STATE.md`, stop every writer in flight, hand off.

## State and inbox

Run directory: `~/.local/state/ai-skills/orchestrator/<run-id>/`, outside every repository. `STATE.md` holds the header (repository, rolling branch, PR, tip, next action, halt), the queue table and a dated log; write it after every change. `INBOX.md` is your append-only channel to a supervised loop: numbered rulings inside your authority, read by the loop at phase boundaries. A supervised session without a run directory gets one from you and is told its path.

## Long loop

After each landing run tracker `next` and take the first packet that validates `READY`; without a tracker, the next `READY` packet in the request's list whose dependencies are closed or landed this run. When none remain, run the milestone gate and stop with at most three proposed packets in the run directory. Never create or edit tracker rows.

## Handoff

The queue (done, blocked, waiting on the owner), each PR URL on its own line, every tracker line verbatim, the halt reason, the run directory path. Merge remains the owner's gate.
