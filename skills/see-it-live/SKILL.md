---
name: see-it-live
description: "Launch the app and confirm the specific change is visible and working: screenshot, curl, or run it. Doubles as the fast smoke pass. Use for run the app, start the server, see it live, smoke test, or post-deploy check."
license: MIT
metadata:
  display-name: "See It Live"
  version: "2.0"
  platforms: "claude-code codex"
  tags: "verification runtime evidence smoke"
---

# See it live

Green type-checks and tests do not prove the change works. Behavior lives in the running app: start it and observe the specific change before saying done.

## Launch path

The project knows its run command better than this table. Inventory the targets it declares first: build-file targets (`Makefile`, `justfile`), `package.json` scripts, CI job names, the README run and validate section. A named journey, playtest, E2E or smoke target outranks a generic launch, and its graphical variant outranks the headless one when the display allows. Headless-only proof shows absence of errors, not that the change is visible; say so when you fall back to it.

| Project type | Launch | Observe |
|---|---|---|
| Game engine | declared playtest or journey target; a headless quit run catches script errors fast | the scripted outcome passes and the changed behavior happens, not just "scene loads" |
| Web frontend | dev server, open the changed route | golden path and error state rendered; screenshot |
| Backend or API | start the server, `curl` the changed endpoint with a real payload | health returns 200; status and response shape match |
| CLI or library | run the binary with real args | stdout, stderr and exit code are correct |

## Confirm the specific change

- Before launching, write down the one signal that proves the change ("the Save button shows a spinner", "`/api/jobs` returns `status: queued`").
- Launch, reproduce the exact path that exercises it, and check for that signal. "It still boots" is necessary, not sufficient.

## Smoke mode

The same paths are the fast critical-path gate between built and shipped. Four checks, answered in seconds:

- The app boots with no fatal error.
- The core path works (the one thing the product must do).
- A key endpoint responds (health or the primary surface).
- No error spew in logs or console.

Run it after integrating a change and again after deploy or merge. A failed smoke pass is a hard stop for shipping. The post-deploy run hits the deployed URL, not localhost, and confirms the new build is live (version endpoint, build hash, or a marker from the change). A post-deploy failure is a rollback trigger: surface it loudly.

Keep it deterministic: no flaky waits, no giant fixtures, no unstubbed third parties, a clear pass or fail. The tenth assertion means you have drifted into `qa-automation`.

## Evidence and teardown

- UI: a screenshot of the changed state. API or CLI: the actual response body or stdout, pasted, with the command that produced it.
- Stop the server and spawned processes; revert seeded data or toggled flags.

Not automated testing: repeatable checks belong to `qa-automation`. This is the "I watched it happen" step.
