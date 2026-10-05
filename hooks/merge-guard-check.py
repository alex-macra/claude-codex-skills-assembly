#!/usr/bin/env python3
"""Exit-code-only protected-branch check, shared by client hooks.

  merge-guard-check.py [--cwd DIR] <command string>

Exit 0 allows. Exit 1 denies: protected-branch push, `gh pr merge --admin`,
behind-base `gh pr merge`, and pull request merges through `gh api` (REST or
GraphQL). Merges sent by other HTTP clients, such as curl, are not inspected;
remote branch protection covers them. Any merge or push that cannot be
verified is denied, and so is any call that does not pass exactly one command
string -- the check fails closed. A single blank command is allowed.

DIR is the directory the shell tool runs the command in. Adapters must pass
it: the current branch, push remote, and remote default branch are resolved
there, and without it they are resolved in this process's directory.

merge-guard.py stays the hook for Claude Code, Codex, and git itself
(pre-push). This entry point exists so thin client adapters, such as an
OpenCode plugin, can reuse the exact same rules. It must sit beside
merge-guard.py. Defense in depth, not a security boundary: remote branch
protection stays authoritative.

Override with AI_SKILLS_ALLOW_PROTECTED=1 in the command itself.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import importlib

merge_guard = importlib.import_module("merge-guard")

USAGE = "usage: merge-guard-check.py [--cwd DIR] <command string>"


def main(argv: list[str]) -> int:
    cwd: str | None = None
    if len(argv) == 3 and argv[0] == "--cwd":
        if not argv[1] or not Path(argv[1]).is_dir():
            print(f"Blocked: --cwd is not a directory: {argv[1]!r}", file=sys.stderr)
            return 1
        cwd = str(Path(argv[1]).resolve())
        argv = argv[2:]
    if len(argv) != 1:
        print(USAGE, file=sys.stderr)
        return 1
    if not argv[0].strip():
        print(USAGE, file=sys.stderr)
        return 0

    request: dict = {"tool_name": "Bash", "tool_input": {"command": argv[0]}}
    if cwd is not None:
        request["cwd"] = cwd
    hidden = io.StringIO()
    sys.stdin = io.StringIO(json.dumps(request))
    try:
        with redirect_stdout(hidden):
            merge_guard.run_pretooluse()
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(f"Blocked: merge guard exited with {exc.code}", file=sys.stderr)
            return 1
    except Exception as exc:
        print(f"Blocked: merge guard crashed ({exc})", file=sys.stderr)
        return 1
    reason = hidden.getvalue().strip()
    if not reason:
        return 0
    try:
        decision = json.loads(reason)
        nested = decision.get("hookSpecificOutput", {})
        if nested.get("permissionDecision") == "deny":
            print(nested.get("permissionDecisionReason", "Blocked by merge guard."))
            return 1
    except (json.JSONDecodeError, AttributeError):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
