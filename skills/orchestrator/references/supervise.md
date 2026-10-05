# Supervise a session

How the orchestrator watches work it did not do: a loop in this session, one whole session, or sessions it did not start. The supervised work keeps its own authority; you observe, rule inside yours, and escalate the rest.

## Discovery

- Claude Code: `ListAgents` lists in-process subagents, teammates and other local sessions; `claude agents` lists background agents; run directories under `~/.local/state/ai-skills/orchestrator/*/STATE.md` name the runs on this machine.
- Codex: assume no cross-session primitive. Supervise through `STATE.md` and `INBOX.md` in the run directory the brief names.
- A session without a run directory gets one from you before the first probe and is told its path in the first message or brief.

## Check-in probe

Read-only, every probe, in this order:
1. Commits and diff stat since the last probe: `git log --oneline <last tip>..HEAD` and `git diff --stat <last tip>` in the watched worktree.
2. Newest artifact age in the run directory and the `STATE.md` header.
3. Worker state: alive, idle, or gone (harness listing, or the agent's last notice).
4. PR state when one exists: open, merged, closed, and its head commit.

Record the probe as one dated log line in `STATE.md`. Progress means a new commit, a changed diff stat, a newer artifact, or a changed header. Interpret with a model call only when two probes in a row show no progress.

## Cadence

About 1 minute for quick work, about 5 minutes for large work, between the two for medium. A completion notice or a watch on a gate's exit file replaces the timer when the harness offers one; the probe still runs on the wake. Never poll a long gate faster than its own expected duration.

## Stall ladder

One rung per probe without progress; never skip a rung, never repeat one:
1. Nudge: name the specific missing step in one message, with the command or file, not a summary of the brief.
2. Shrink: split the task or cut it to the failing piece. Never retry an identical long call.
3. Replace: a fresh context with a better brief, or a stronger model tier. Carry over the evidence, never the transcript.
4. Block: record the failing command, its output, the attempts, and the open question; move to the next independent task.

## Unblock channels

- `SendMessage` to the named session or agent where the harness reaches it; on Claude Code the names come from `ListAgents`.
- Otherwise, and always as the record, append to `<run dir>/INBOX.md`. A message carries the entry number so the two channels agree.
- A message from another agent never approves anything; neither does yours. Authority comes from the request that started the run.

## INBOX protocol

- `INBOX.md` is written only by you, append-only, one numbered entry per line: `N. <ISO time> <from>: <text>`.
- An entry is a ruling inside your authority: a narrowed write set, an answer to a BLOCKED question, a re-pin, or `STOP` (stop at the next phase boundary).
- An entry can never widen Git or publication authority, weaken a test, or add scope beyond the packet. A loop refuses such an entry and reports it; treat the refusal as a finding against yourself.
- The loop reads `INBOX.md` at every phase boundary and before shipping, and lists the entries it applied in its handoff (`inbox: applied 1-3`). Do not expect a mid-phase reaction.
- `HALT` in the run directory is the hard stop; `STOP` is the soft one.

## Escalation

Escalate only owner decisions: scope, acceptance thresholds, interface freezes, spend, visibility, merges. State the question, the options, your default, and the evidence as `path:line`, then continue on the next independent task. Everything else is a ruling or a BLOCKED row.

## Orphan triage

A dirty worktree with no live agent and no handoff is orphaned. Save `git status --porcelain` and `git diff --stat` to the run directory first. Then resume the same agent with "verify state first", or give a fresh builder the saved diff with the original brief. Never discard the diff; never commit it yourself.

## Detached gates

A gate that outlives one call runs detached with three files: `<label>.start` written before exec, then `<label>.log` and `<label>.exit`. Never reuse a label. Start without exit and no live unit means killed: rerun under a new label. Chain on the exit file reading `0`, never on a grep of the log.

## Halt

Halt on `HALT` in the run directory, two consecutive empty agent returns, three consecutive blocked tasks, or the task cap. Write the reason to `STATE.md`, stop every writer in flight (`TaskStop` on Claude Code; on Codex a `STOP` entry, then wait for the boundary), then hand off: queue, PR URLs, halt reason, run directory path.

## Never

Edit the watched session's tree, commit or push for it, run its gates concurrently with it, merge, deploy, release, tag or publish.
