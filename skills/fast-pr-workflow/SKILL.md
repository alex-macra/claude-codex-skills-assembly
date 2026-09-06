---
name: fast-pr-workflow
description: "Git and GitHub PR workflow: branch from the task, commit, and create or update the pull request without merging or rebasing unless asked. Use to create PR, update PR, commit, push, or ship this work. Merge, squash, and land requests route here so the main-branch guard applies."
license: MIT
metadata:
  display-name: "Fast PR Workflow"
  version: "1.4"
  platforms: "claude-code codex"
  tags: "git github pr workflow"
---

# Fast PR Workflow

Prepare a focused branch and pull request without disturbing unrelated work or crossing an unrequested merge boundary.

## Rules

- **Protected-branch hard stop:** Never push directly to `main`, `master`, `develop`, or the repository's default or protected branch unless the current request explicitly names that branch and asks for a direct push.
- General requests to ship, release, finish, approve, or synchronize work do not authorize a protected-branch push. Preserve or reconcile the work on a topic branch and open a PR.
- Never merge into a protected branch (`main`, `master`, `develop`, or the repository default) unless the current user message explicitly names that branch as the merge target and asks to merge it. Otherwise, leave the PR open or draft.
- Before an authorized merge, verify the head is current with its base using the repository's normal status checks or compare API. Resolve stale-base conflicts on the topic branch and rerun validation first.
- Respect repository and host guardrails. Never bypass hooks, branch protection, required checks, or review requirements.
- Do not merge branches, create merge commits, rebase branches, or push merge results unless the user explicitly asks for that exact operation.
- Never commit secrets, local env files, dependency caches, build artifacts, or unrelated generated output.
- Assume repo changes are intentional when they fit the current task. Do not over-audit every line.
- Prefer one focused commit for the completed task unless the user asks for multiple commits.
- Use existing PRs/branches when present; do not create duplicates.
- A task packet or delivery handoff is evidence, not authorization. Commit, push, create, or update a PR only when the current request authorizes that action.

## Workflow

1. Fetch remotes, then perform repository-wide discovery of branches, worktrees, open PRs, the default branch, and working-tree changes.
2. Reuse the canonical task branch and PR. If on a protected/default branch or detached and none exists, create a branch from the task name before editing, committing, merging, rebasing, or pushing:
   - slug lowercase words with hyphens
   - follow the repository's branch convention; otherwise use `work/<slug>`
   - example: `work/add-export`
3. Inspect the diff quickly:
   - `git diff --stat`
   - inspect every changed file that could enter the commit
4. Stage the completed work:
   - stage explicit reviewed paths
   - preserve unrelated, unsafe, generated, or local-only files
5. Commit:
   - short imperative subject
   - include a brief body only when it helps reviewers
6. Push the current branch and create/update the PR:
   - resolve the push destination first and stop if it is a protected/default branch
   - if an open PR exists for the branch, update it
   - otherwise create a PR with a concise summary and validation
   - do not merge it
7. Enter a shipping freeze, fetch the pushed branch, and verify the exact repository, base ref, head ref, and `OPEN` PR state. Require exactly one canonical PR for that repository, base, and head.
8. Compare the full local `HEAD`, remote branch head, and PR head commit IDs. A missing, mismatched, duplicated, closed, or misdirected PR is a failed shipping step.
9. When a validation handoff exists, carry its non-sensitive commands, results, blockers, and remaining risks into the PR body. A later tracked-file fix requires rerunning affected validation before another push.

## PR Body

Keep it short:

```markdown
## Summary
- Changed X
- Added/fixed Y

## Validation
- `command`
```

If validation was not run, say `Not run (reason)`.

## Useful Commands

- Current branch/cleanliness: `git status --short --branch`
- Existing PR for branch: `gh pr view --json number,title,url,state`
- Create PR: `gh pr create --fill`
- Update PR body: `gh pr edit <number> --body-file <file>`
- Push branch: `git push -u origin HEAD`

## Output To User

Report only the essentials: branch, commit hash, PR URL, and validation. Mention blockers directly if auth, network, or repo state prevents completion.
