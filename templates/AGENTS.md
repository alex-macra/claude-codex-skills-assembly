# Agent working rules

This is an optional starting point. Keep repository-specific conventions in the repository that owns them.

## Use relevant skills

- Check the installed skill list before inventing a workflow.
- Load a matching skill when the request names it or clearly falls within its description.
- Follow repository-local instructions when they are more specific than generic guidance.
- Claude Code can preload skills declared by an agent definition. Codex dispatch must explicitly tell each subagent which `SKILL.md` files to read completely before acting.

## Preserve repository state

- Inspect the branch, worktree, and diff before changing or staging files.
- Preserve unrelated changes and generated local state.
- Stage only reviewed files that belong to the current task.

## Protect release boundaries

- Do not push directly to a protected branch unless the current request explicitly names that branch and asks for the direct push.
- Do not merge a pull request unless the current request explicitly names the target branch and asks for the merge.
- Confirm before publishing, deploying, releasing, or creating tags.

## Comment sparingly

- Default to zero comments. Code and tests carry the meaning; a comment earns its place only by stating a non-obvious why.
- Never write comments that restate the code, reference a ticket or PR, note provenance, or narrate a change.
- See the `code-comments` skill for the full guidance.

## Report concisely

- Lead with the outcome. Add detail only when it changes what the reader does next.
- Skip the preamble, the recap of the request, and the closing summary of what was just said.
- Prefer a short list to a paragraph of narrative.

## Report evidence

- Run checks appropriate to the change and report their actual results.
- State failures, skipped checks, and remaining risks plainly.
