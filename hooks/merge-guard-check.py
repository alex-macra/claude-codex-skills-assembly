#!/usr/bin/env python3
"""Exit-code-only protected-branch check, shared by client hooks.

  merge-guard-check.py <command string>     shell-command checks (R1-R4)

Exit 0 allows. Exit 1 denies: protected-branch push, `gh pr merge --admin`,
behind-base `gh pr merge`, direct API/GraphQL PR merge. Any merge or push
that cannot be verified is denied -- the guard fails closed.

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


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        print("usage: merge-guard-check.py <command string>", file=sys.stderr)
        return 0

    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": sys.argv[1]}}
    )
    hidden = io.StringIO()
    sys.stdin = io.StringIO(payload)
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
    sys.exit(main())
