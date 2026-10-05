# Task tracker contract

An optional adapter lets a delivery loop record progress in any task tracker. This repository ships no adapter; the stub below shows the shape.

- Adapter: the executable `~/.config/ai-skills/task-tracker` (a symlink is fine); no environment variable is consulted. Call it as a program, `~/.config/ai-skills/task-tracker <verb> <flags>`, with no interpreter prefix, no output redirection, and a 360000 ms shell timeout.
- A loop is tracked only when the adapter exists and is executable and the packet's Readiness names a Task ID matching `[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+`. Otherwise it calls nothing and reports `tracker: none`.
- The request to run the loop authorizes calls for the packet's own task only. The adapter never runs Git writes in the product repository and never merges, rebases, tags, pushes the product branch, or publishes.
- Every write verb takes `--task ID --product ROOT --run-id RUN --executor claude-code|codex [--dry-run]`. Choose one run ID per task at `claim`, matching `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`, and reuse it on every later call and retry.

| Verb | When | Extra flags |
| --- | --- | --- |
| `next` (read-only) | a conductor picks the next task, or a loop is asked to continue | `--product ROOT [--landed ID,...] [--limit N]` |
| `claim` | after `READY`, before the first write | `[--packet FILE]` |
| `checkpoint` | each completed gate, and on a block | `--phase P --outcome O [--evidence REF]... [--next-gate G]` |
| `review` | after the canonical PR is verified | `--pr URL [--evidence REF]...` |
| `finish` | only after a separately authorized merge, from a clean checkout at the merge SHA with checks and smoke rerun | `--pr URL --evidence REF...` |

- `next` prints up to N lines `NEXT <ID> <title>` (N defaults to 5, at most 20), else exactly `NEXT none`, and exits 0. It is a hint; the packet's own `READY` gate decides.
- Phases: `intake`, `research`, `build`, `verify`, `review`, `shipping`, `complete`, `blocked`. Outcomes: `running`, `passed`, `failed`, `blocked`, `complete`. The test and build gate maps to `verify`; `finish` sets phase and outcome to `complete`.
- At most 8 evidence references, each one line of at most 500 characters, never logs. `--next-gate` is at most 240 characters. `--pr` is `https://github.com/OWNER/NAME/pull/N`.
- A write verb prints exactly one line on stdout and sends diagnostics to stderr; `--dry-run` prints the line it would record and writes nothing. The loop copies every line verbatim into its handoff.
- Exit 0 means recorded or skipped. A line containing `skipped` (any case) wrote nothing: never report it as success, and retry at the next gate.
- Exit 3 means another loop holds the task: stop that task; a conductor records it as blocked. Any other exit, or no line, counts as skipped.
- Every tracked commit message ends with the line `Task: <ID>`, and the PR body carries one `Task: <ID>` line per task. Adapters map PRs to tasks only through these lines, never by scanning prose.

Stub adapter: `next` prints `NEXT none`; every other verb prints `recorded <verb> <task> <run-id>` and exits 0, or `held <task>` with exit 3 while `task-tracker.held` exists beside it; each call's arguments are appended to `task-tracker.log`.

```sh
#!/bin/sh
d="$HOME/.config/ai-skills"
printf '%s\n' "$*" >> "$d/task-tracker.log"
verb=$1 task= run=
while [ $# -gt 0 ]; do
  case $1 in --task) task=$2 ;; --run-id) run=$2 ;; esac; shift
done
[ "$verb" = next ] && { echo "NEXT none"; exit 0; }
[ -e "$d/task-tracker.held" ] && { echo "held $task"; exit 3; }
echo "recorded $verb $task $run"
```
