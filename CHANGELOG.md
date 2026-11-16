# Changelog

Notable changes to AI Skills Assembly. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project has no tagged releases yet, so merged work is grouped by month.

## Unreleased

### Changed

- README names the full path of the delivery-state and browser lease helpers under `skills/delivery-loop/scripts/`.

## 2026-10

### Added

- `post-merge-cleanup` skill and `cleaner` agent: verify a merged PR against the fetched base and remove only its clean, idle task worktree; routed from "post-merge cleanup" and "cleanup worktrees" (#11).
- `hooks/merge-guard-check.py` adapter so other agent harnesses can ask the merge guard about one shell command (#9).
- Catalog v2: new `web-dev` and `orchestrator` skills and an `orchestrator` agent for supervising loops and sessions (#8).
- `scripts/validate.py` enforces hard line and byte caps on skills, references, agents, and templates, a 250-character description limit, and a listing budget that warns above 2,500 and fails above 3,000 characters (#8).

### Changed

- Catalog v2 trims the default profile from 15 skills to 10 and from 3 agents to 2, folding retired skills into `architect-review`, `qa-automation`, and `web-dev`; agents install on the Claude Code surface only (#8).
- The merge guard treats heredoc bodies as data in the unambiguous case, so quoted heredocs in commit messages and file writes are no longer denied (#10).

### Security

- The installed command hook fails closed when the merge guard is missing, unreadable, or broken: it blocks commands that use `git`, `gh`, or `curl` and lets other commands run (#9).

## 2026-09

### Added

- Executable delivery-state helper with symlink and hard link refusal, mode `0600`, and ignored and untracked verification (#3).
- Scoped, turn-local tool grants for `fast-pr-workflow` and a validated task packet format for delivery (#4).

### Changed

- `see-it-live` and end-to-end QA prefer the project's own declared journey targets before a generic launch command (#7).
- `install.py project` writes only the ignore entries `.gitignore` does not already cover, so a re-run leaves the tree clean (#7).
- README and catalog description name Claude Code and OpenAI Codex (#5).
- Browser suite coordination hardened against metadata and parent replacement (#3).

### Removed

- Hardware-specific task research and planning skills, added in #4, left the public default profile (#6).

## Earlier

Changes before September 2026 are in the [git history](https://github.com/alex-macra/claude-codex-skills-assembly/commits/main).
