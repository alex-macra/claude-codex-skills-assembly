---
name: fast-pr-workflow
description: "Git and GitHub PR mechanics: commit, push, create or update one pull request, merge only on explicit request. Use to create PR, update PR, commit, push, or ship work. Merge, squash, and land requests route here for the guard."
license: MIT
allowed-tools: Bash(gh auth status:*), Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git show:*), Bash(git rev-parse:*), Bash(git rev-list:*), Bash(git merge-base:*), Bash(git branch --show-current), Bash(git remote -v), Bash(git ls-files:*), Bash(git add:*), Bash(git commit -m:*), Bash(git fetch:*), Bash(git switch -c:*), Bash(git switch --create:*), Bash(git checkout -b:*), Bash(git push -u origin HEAD), Bash(git push --set-upstream origin HEAD), Bash(git push origin HEAD), Bash(gh pr list:*), Bash(gh pr view:*), Bash(gh pr checks:*), Bash(gh pr status:*), Bash(gh pr diff:*), Bash(gh pr create:*), Bash(gh pr edit:*)
metadata:
  display-name: "Fast PR Workflow"
  version: "2.0"
  platforms: "claude-code codex"
  tags: "git github pr workflow"
---

# Fast PR Workflow

Perform only the authorized Git and PR mechanics, without disturbing unrelated work.

## Authorization

- The only shipping actions are `commit`, `push`, `PR create`, `PR metadata update`, and `merge`. Resolve the exact authorized action set from the current request before inspecting or mutating anything, and stop after the last one: `commit these changes locally` is not a push, and `update the PR body` is not a commit.
- General requests to ship, release, finish, approve, or synchronize work do not authorize an unrequested commit, push, PR creation or update, protected-branch action, or merge.
- A task packet or delivery handoff is evidence, not authorization. An explicit request to run `delivery-loop`, or the `orchestrator` on named packets or a tracker queue, is the narrow exception: after its checks, reviews, and smoke pass, it authorizes one topic-branch commit, push, and canonical PR create or update per task unless the user excludes an action; a conductor landing a builder commit under that request uses it too. The bundle never includes merge.
- Outside that bundle, commit, push, PR create, PR update, and merge are separate actions. Authorization for one does not imply any later action.
- Creating a PR includes the minimum push of the already-validated, non-protected topic-branch `HEAD` needed to make that PR exist. It does not authorize creating another commit. Updating PR metadata does not authorize any new commit or push.

## Guards

- **Protected-branch hard stop:** Never push directly to `main`, `master`, `develop`, or the repository's default or protected branch unless the current request explicitly names that branch and asks for a direct push.
- Never merge into a protected branch (`main`, `master`, `develop`, or the repository default) unless the current user message explicitly names that branch as the merge target and asks to merge it. Otherwise, leave the PR open or draft.
- Merge only a head current with its base: if `gh api repos/{owner}/{repo}/compare/{base}...{headSha} --jq .behind_by` is non-zero, a stale first parent can silently drop content, so stop and report it. Syncing the branch is a separately authorized action.
- These rules are mechanically enforced when the guard hooks are installed (`hooks/merge-guard.py`): a protected-branch push, a stale-base merge, or `gh pr merge --admin` fails. Never bypass the guard, branch protection, or required checks; if the user truly asked for it, prefix the command with `AI_SKILLS_ALLOW_PROTECTED=1` so the decision is visible.
- Do not merge branches, create merge commits, rebase, squash, or push merge results unless the user explicitly asks for that exact operation.
- Never commit secrets, env files, caches, build artifacts, or unrelated generated output; prefer one focused commit per task.
- The scoped `allowed-tools` inventory is approved for branch-to-PR loops on a disposable or independently backed-up controller. Permission matching includes output redirections, so even an allowed inspection command can overwrite a local file. Git does not protect uncommitted files or credentials.
- Action-prefix grants can accept later flags, so the permission engine is not an argument sandbox. Use only the listed command shapes without force-push flags, hook-bypass flags, cross-repository flags, non-`HEAD` push refspecs, reset, clean, branch deletion, PR merge, close, or review. Do not request or persist broader Git, GitHub CLI, or Bash grants.

## Workflow

1. Inspect the local branch, worktree, and candidate changes. Fetch or query remote and hosting state only for an authorized push, PR create, PR metadata update, or merge.
2. Reuse the canonical task branch and PR. Before committing from a protected, default, or detached `HEAD`, create a task branch (repository convention, else `work/<slug>`).
3. For an authorized **local commit**: stage only reviewed paths, keeping unrelated, generated, or local-only files out; validate the staged candidate; end a tracked task's message with `Task: <ID>`; after committing, confirm the validated files match `HEAD`. Pre-commit results are candidate-tree validation, not pushed-head proof. If `commit` is the only authorized action, that is, if no push or PR action is also authorized, do not fetch or query remotes, push, create or update a PR, or merge; report the local branch and commit, then stop.
4. For an authorized **push**: fetch only the refs needed for destination and ancestry, stop on a protected or default destination, and push only authorized local commits. Do not create or update a PR unless that separate action is authorized.
5. For an authorized **PR creation**: reuse a matching open PR, else push the validated topic-branch `HEAD` if needed and create one whose short body carries the handoff's non-sensitive validation (or `Not run (reason)`), risks, and one `Task: <ID>` line per tracked task. Enter a shipping freeze. Exactly one canonical PR for the repository, base, and head; missing, mismatched, duplicated, closed, or misdirected fails the action.
6. For an authorized **PR update**: resolve the one intended open PR and change only the requested metadata. Do not stage, commit, or push repository files unless those actions are separately authorized.
7. For an authorized **merge**: the request names the target branch and the merge, and every guard above passes, including a zero `behind_by`.
8. After any remote action, verify repository, base and head refs, requested metadata, and `OPEN` state, and require local `HEAD`, remote branch head, and PR head to match as full commit IDs where touched. Only that verified match makes validation pushed-head proof.

## Output to user

Report the branch, full commit ID, and validation, with the full PR URL on its own line as a Markdown link, repeated in every later status until merged. Name blockers; ask one concise question when the branch, PR, or scope is ambiguous.
