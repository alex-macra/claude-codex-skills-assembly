from __future__ import annotations

import importlib.util
from contextlib import redirect_stdout
from io import StringIO
import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HOOKS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


activation = load("public_skill_activation", "skill-activation.py")
merge_guard = load("public_merge_guard", "merge-guard.py")
usage = load("public_skill_usage", "skill-usage-log.py")


def run_hook(filename: str, payload: str, args: list[str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOKS / filename), *(args or [])],
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(ROOT),
        check=False,
    )


class ActivationTests(unittest.TestCase):
    def test_default_catalog_routes_a_generic_prompt(self) -> None:
        with patch.object(activation, "project_rule_paths", return_value=[]):
            entries = activation.registry()
        self.assertIn("fast-pr-workflow", activation.match_skills("create PR for this", entries))

    def test_catalog_environment_is_ordered_and_repeatable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "rules.json").write_text(
                json.dumps(
                    {
                        "skills": {
                            "sample-overlay": {
                                "priority": "high",
                                "promptTriggers": {"keywords": ["overlay route"]},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            catalog = root / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "routing": {"registry": "rules.json"},
                    }
                ),
                encoding="utf-8",
            )
            value = os.pathsep.join((str(ROOT / "catalog.json"), str(catalog)))
            with (
                patch.dict(os.environ, {"AI_SKILLS_CATALOGS": value}),
                patch.object(activation, "project_rule_paths", return_value=[]),
            ):
                entries = activation.registry()

        self.assertIn("fast-pr-workflow", entries)
        self.assertIn("sample-overlay", entries)

    def test_catalog_registry_paths_cannot_escape_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside-rules.json"
            outside.write_text(json.dumps({"skills": {"outside-skill": {}}}), encoding="utf-8")
            catalog_root = root / "catalog"
            catalog_root.mkdir()
            catalog = catalog_root / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "routing": {
                            "registry": [
                                "../outside-rules.json",
                                str(outside),
                                "C:/outside-rules.json",
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual([], activation.catalog_registry_paths(catalog))

    def test_project_rules_load_from_git_root_and_win(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".git").mkdir()
            nested = root / "src" / "nested"
            nested.mkdir(parents=True)
            rules = root / ".claude" / "skills" / "skill-rules.json"
            rules.parent.mkdir(parents=True)
            rules.write_text(
                json.dumps(
                    {
                        "skills": {
                            "fast-pr-workflow": {
                                "priority": "high",
                                "promptTriggers": {"keywords": ["local-only-route"]},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch("pathlib.Path.cwd", return_value=nested):
                entries = activation.registry()

        self.assertIn("fast-pr-workflow", activation.match_skills("local-only-route", entries))

    def test_output_is_names_only_and_bounded(self) -> None:
        block = activation.render(["a" * 200, "b" * 200, "c" * 200])
        self.assertLessEqual(len(block), activation.MAX_OUTPUT_CHARS)
        self.assertNotIn("\n", block)

    def test_render_skips_overlong_name_and_keeps_later_match(self) -> None:
        block = activation.render(["a" * 400, "short-skill"])

        self.assertIn("short-skill", block)
        self.assertNotIn("a" * 400, block)

    def test_empty_availability_filters_every_match(self) -> None:
        entries = {
            "sample-skill": {
                "promptTriggers": {"keywords": ["sample route"]},
            }
        }

        self.assertEqual([], activation.select("sample route", entries, set()))

    def test_prompt_exclusion_suppresses_keyword_and_intent_activation(self) -> None:
        entries = {
            "sample-skill": {
                "promptTriggers": {
                    "keywords": ["sample route"],
                    "intentPatterns": [r"run.*sample"],
                    "excludePatterns": [r"do not.*sample"],
                },
            }
        }

        self.assertEqual(
            [],
            activation.match_skills("Do not run the sample route", entries),
        )

    def test_prompt_matching_uses_one_bounded_scope_for_all_trigger_kinds(self) -> None:
        entries = {
            "sample-skill": {
                "promptTriggers": {
                    "keywords": ["sample route"],
                    "intentPatterns": [r"run.*sample"],
                    "excludePatterns": [r"do not.*sample"],
                },
            }
        }
        prefix = "x" * (activation.MAX_INTENT_PROMPT_CHARS + 8)

        self.assertEqual(
            [],
            activation.match_skills(prefix + " Do not run the sample route", entries),
        )
        self.assertEqual(
            [],
            activation.match_skills(prefix + " Run the sample route", entries),
        )

    def test_prompt_exclusion_allows_a_later_positive_clause(self) -> None:
        entries = {
            "sample-skill": {
                "promptTriggers": {
                    "keywords": ["sample route"],
                    "intentPatterns": [r"run.*sample"],
                    "excludePatterns": [r"do not[^.]*sample[^.]*"],
                },
            }
        }

        self.assertEqual(
            ["sample-skill"],
            activation.match_skills(
                "Do not run the sample route for legacy. Run the sample route for replacement.",
                entries,
            ),
        )

    def test_apostrophe_normalization_applies_to_exclusions(self) -> None:
        entries = {
            "sample-skill": {
                "promptTriggers": {
                    "keywords": ["sample route"],
                    "excludePatterns": [r"don't run.*sample"],
                },
            }
        }

        self.assertEqual(
            [],
            activation.match_skills("Don’t run the sample route", entries),
        )

    def test_prompt_exclusion_does_not_disable_file_activation(self) -> None:
        entries = {
            "sample-skill": {
                "promptTriggers": {
                    "keywords": ["sample route"],
                    "excludePatterns": [r"do not.*sample"],
                },
                "fileTriggers": {"pathPatterns": ["*.md"]},
            }
        }

        self.assertEqual(
            ["sample-skill"],
            activation.match_skills("Do not run sample route; inspect input.md", entries),
        )

    def test_agents_home_is_included_in_available_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "agents-home" / "skills" / "sample-skill"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("sample\n", encoding="utf-8")
            worktree = root / "worktree"
            (worktree / ".git").mkdir(parents=True)
            environment = {
                "AGENTS_HOME": str(root / "agents-home"),
                "CLAUDE_CONFIG_DIR": str(root / "claude-home"),
                "CODEX_HOME": str(root / "codex-home"),
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("pathlib.Path.cwd", return_value=worktree),
            ):
                available = activation.available_skills()

        self.assertIn("sample-skill", available)

    def test_malformed_inputs_fail_open(self) -> None:
        for payload in ("", "{{{", "[]", "null", "\x00\x01"):
            with self.subTest(payload=payload):
                result = run_hook("skill-activation.py", payload)
                self.assertEqual(result.returncode, 0)


class UsageLogTests(unittest.TestCase):
    def run_usage(self, payload: object, environment: dict[str, str]) -> int:
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(usage.sys, "stdin", StringIO(json.dumps(payload))),
        ):
            return usage.main()

    def test_default_log_uses_private_directory_and_file_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(usage.Path, "home", return_value=root),
                patch.object(
                    usage.sys,
                    "stdin",
                    StringIO(json.dumps({"tool_input": {"skill": "sample-skill"}, "cwd": "project"})),
                ),
            ):
                result = usage.main()

            log = root / ".ai-skills" / "skill-usage.jsonl"
            self.assertEqual(0, result)
            self.assertEqual(0o700, stat.S_IMODE(log.parent.stat().st_mode))
            self.assertEqual(0o600, stat.S_IMODE(log.stat().st_mode))
            self.assertEqual("sample-skill", json.loads(log.read_text())["skill"])

    def test_environment_override_selects_log_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "private-log" / "events.jsonl"
            result = self.run_usage(
                {"tool_input": {"skill": "sample-skill"}},
                {"AI_SKILLS_USAGE_LOG": str(log)},
            )

            self.assertEqual(0, result)
            self.assertTrue(log.is_file())
            self.assertEqual(0o700, stat.S_IMODE(log.parent.stat().st_mode))
            self.assertEqual(0o600, stat.S_IMODE(log.stat().st_mode))

    def test_symlink_log_target_fails_open_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.jsonl"
            target.write_text("unchanged\n", encoding="utf-8")
            link = root / "usage.jsonl"
            link.symlink_to(target)

            result = self.run_usage(
                {"tool_input": {"skill": "sample-skill"}},
                {"AI_SKILLS_USAGE_LOG": str(link)},
            )

            self.assertEqual(0, result)
            self.assertEqual("unchanged\n", target.read_text(encoding="utf-8"))

    def test_malformed_input_fails_open(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(usage.sys, "stdin", StringIO("not-json")),
        ):
            self.assertEqual(0, usage.main())


class MergeGuardTests(unittest.TestCase):
    def deny_reason(self, command: str, cwd: Path = ROOT) -> str | None:
        result = run_hook(
            "merge-guard.py",
            json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                    "cwd": str(cwd),
                }
            ),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        if not result.stdout.strip():
            return None
        return json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]

    def test_protected_push_is_denied(self) -> None:
        self.assertIn("protected branch 'main'", self.deny_reason("git push origin main") or "")

    def test_feature_push_is_allowed(self) -> None:
        self.assertIsNone(self.deny_reason("git push origin topic/example"))

    def test_wrapper_does_not_bypass_guard(self) -> None:
        self.assertIsNotNone(self.deny_reason("env git push origin main"))

    def test_one_shot_git_push_alias_is_denied(self) -> None:
        commands = (
            "git -c 'alias.ship=push --no-verify' ship origin main",
            "git -calias.ship='push --no-verify' ship origin main",
            "git -c 'alias.ship=!git push --no-verify origin main' ship",
            "git --config-env=alias.ship=AI_SKILLS_TEST_ALIAS ship origin main",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertIsNotNone(self.deny_reason(command))

        self.assertIsNone(
            self.deny_reason("git -c 'alias.ship=push --no-verify' ship origin topic")
        )

    def test_push_capable_git_alias_definition_is_denied(self) -> None:
        commands = (
            "git config alias.ship 'push --no-verify'",
            "git config --global alias.ship '!git push --no-verify origin main'",
            "git config set alias.ship 'push --no-verify'",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertIn("alias", self.deny_reason(command) or "")

        self.assertIsNone(self.deny_reason("git config alias.summary 'log --oneline'"))

    def test_existing_git_aliases_are_resolved_recursively(self) -> None:
        aliases = {"ship": "deliver", "deliver": "push --no-verify"}

        def configured(name: str, cwd: str | None) -> tuple[bool, str | None]:
            return (name in aliases, aliases.get(name))

        with (
            patch.object(merge_guard, "_configured_alias", side_effect=configured),
            patch.object(merge_guard, "_remote_default_branch", return_value=None),
            redirect_stdout(StringIO()),
            self.assertRaises(SystemExit),
        ):
            merge_guard._check_push(
                "git ship origin main", ["git", "ship", "origin", "main"], None
            )

    def test_visible_override_is_allowed(self) -> None:
        self.assertIsNone(self.deny_reason("AI_SKILLS_ALLOW_PROTECTED=1 git push origin main"))

    def test_override_applies_only_to_the_prefixed_invocation(self) -> None:
        commands = (
            "echo AI_SKILLS_ALLOW_PROTECTED=1 && git push origin main",
            "NOTE=AI_SKILLS_ALLOW_PROTECTED=1 git push origin main",
            "AI_SKILLS_ALLOW_PROTECTED=1 AI_SKILLS_ALLOW_PROTECTED=0 git push origin main",
            "AI_SKILLS_ALLOW_PROTECTED=1 git push origin topic && git push origin main",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertIsNotNone(self.deny_reason(command))

        self.assertIsNone(
            self.deny_reason(
                "AI_SKILLS_ALLOW_PROTECTED=0 AI_SKILLS_ALLOW_PROTECTED=1 git push origin main"
            )
        )
        self.assertIsNone(
            self.deny_reason(
                "env AI_SKILLS_ALLOW_PROTECTED=1 sh -c 'gh pr merge 12 --admin'"
            )
        )

    def test_shell_syntax_does_not_hide_admin_merge(self) -> None:
        commands = (
            "echo ready\ngh pr merge 12 --admin",
            "echo ready & gh pr merge 12 --admin",
            "(gh pr merge 12 --admin)",
            "sh -c 'gh pr merge 12 --admin'",
            "sh -c 'echo AI_SKILLS_ALLOW_PROTECTED=1 && gh pr merge 12 --admin'",
            "bash -lc 'gh pr merge 12 --admin'",
            "echo $(gh pr merge 12 --admin)",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertIn("--admin", self.deny_reason(command) or "")

    def test_double_quoted_command_substitution_does_not_hide_admin_merge(self) -> None:
        commands = (
            'echo "$(gh pr merge 12 --admin)"',
            'echo "prefix $(gh pr merge 12 --admin) suffix"',
            'echo "$(printf %s "$(gh pr merge 12 --admin)")"',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertIn("--admin", self.deny_reason(command) or "")

    def test_backticks_do_not_hide_admin_merge(self) -> None:
        commands = (
            "echo `gh pr merge 12 --admin`",
            'echo "`gh pr merge 12 --admin`"',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertIn("--admin", self.deny_reason(command) or "")

    def test_command_position_eval_does_not_hide_admin_merge(self) -> None:
        commands = (
            "eval 'gh pr merge 12 --admin'",
            'eval "gh pr merge 12 --admin"',
            "command eval 'gh pr merge 12 --admin'",
            "sh -c \"eval 'gh pr merge 12 --admin'\"",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertIn("--admin", self.deny_reason(command) or "")

    def test_dynamic_eval_fails_closed(self) -> None:
        commands = (
            "MERGE='gh pr merge 12 --admin'; eval \"$MERGE\"",
            "eval \"$(printf %s 'gh pr merge 12 --admin')\"",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertIn("could not safely inspect", self.deny_reason(command) or "")

    def test_shell_indirection_depth_limit_fails_closed(self) -> None:
        command = "eval " * (merge_guard.MAX_SHELL_DEPTH + 2) + "'echo ready'"

        self.assertIn("could not safely inspect", self.deny_reason(command) or "")

    def test_quoted_prose_is_not_treated_as_an_invocation(self) -> None:
        self.assertIsNone(self.deny_reason("echo 'gh pr merge 12 --admin'"))
        self.assertIsNone(
            self.deny_reason(
                "echo '$(gh pr merge 12 --admin) `gh pr merge 12 --admin` eval gh'"
            )
        )
        self.assertIsNone(
            self.deny_reason("gh pr create --body 'run gh pr merge 12 --admin later'")
        )

    def test_force_and_symbolic_push_refspecs_are_denied(self) -> None:
        self.assertIsNotNone(self.deny_reason("git push origin +main"))
        for refspec in ("HEAD", "@", "+HEAD"):
            with (
                self.subTest(refspec=refspec),
                patch.object(merge_guard, "_current_branch", return_value="main"),
                patch.object(merge_guard, "_remote_default_branch", return_value=None),
                redirect_stdout(StringIO()),
                self.assertRaises(SystemExit),
            ):
                merge_guard._check_push(
                    "git push", ["git", "push", "origin", refspec], None
                )

        with (
            patch.object(merge_guard, "_remote_default_branch", return_value="main"),
            redirect_stdout(StringIO()),
            self.assertRaises(SystemExit),
        ):
            merge_guard._check_push(
                "git push", ["git", "push", "origin", "HEAD:HEAD"], None
            )

    def test_broad_push_modes_are_denied(self) -> None:
        commands = ("git push --all origin", "git push --mirror origin", "git push origin :")
        for command in commands:
            with self.subTest(command=command):
                self.assertIsNotNone(self.deny_reason(command))

    def test_git_dash_c_uses_the_target_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            subprocess.run(
                ["git", "init", "-q", "-b", "main", str(repo)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIsNotNone(self.deny_reason(f"git -C {shlex.quote(str(repo))} push"))

    def test_ambiguous_git_directory_context_fails_closed(self) -> None:
        for option in ("--git-dir=/tmp/example.git", "--work-tree /tmp/example"):
            with self.subTest(option=option):
                self.assertIn(
                    "cannot safely resolve",
                    self.deny_reason(f"git {option} push origin topic") or "",
                )

    def test_custom_remote_default_branch_is_protected(self) -> None:
        with (
            patch.object(merge_guard, "_remote_default_branch", return_value="trunk"),
            redirect_stdout(StringIO()),
            self.assertRaises(SystemExit),
        ):
            merge_guard._check_push(
                "git push", ["git", "push", "upstream", "trunk"], None
            )

        with (
            patch.object(merge_guard, "_remote_default_branch", return_value="trunk"),
            patch.object(merge_guard, "_default_push_target", return_value="trunk"),
            redirect_stdout(StringIO()),
            self.assertRaises(SystemExit),
        ):
            merge_guard._check_push("git push", ["git", "push", "upstream"], None)

    def test_remote_default_branch_falls_back_to_remote_head_query(self) -> None:
        with patch.object(
            merge_guard,
            "_run",
            side_effect=[
                (1, "missing local remote HEAD"),
                (0, "ref: refs/heads/trunk\tHEAD\nabc123\tHEAD"),
            ],
        ):
            branch = merge_guard._remote_default_branch("origin", str(ROOT))

        self.assertEqual("trunk", branch)

    def test_git_pre_push_blocks_protected_ref(self) -> None:
        result = run_hook(
            "merge-guard.py",
            "refs/heads/topic deadbeef refs/heads/main 0000000\n",
            ["--git-pre-push"],
        )
        self.assertEqual(result.returncode, 1)

    def test_git_pre_push_discovers_remote_default_branch(self) -> None:
        payload = "refs/heads/topic deadbeef refs/heads/trunk 0000000\n"
        with (
            patch.object(merge_guard, "_remote_default_branch", return_value="trunk"),
            patch.object(merge_guard.sys, "stdin", StringIO(payload)),
            patch.object(merge_guard.sys, "stderr", StringIO()),
        ):
            result = merge_guard.run_git_pre_push("upstream")

        self.assertEqual(result, 1)

    def test_pr_selector_and_repository_are_forwarded_to_checks(self) -> None:
        metadata = json.dumps(
            {
                "baseRefName": "main",
                "headRefOid": "abc123",
                "number": 12,
                "state": "OPEN",
            }
        )
        cases = (
            (
                "gh -R example/widgets pr merge https://example.invalid/example/widgets/pull/12",
                "https://example.invalid/example/widgets/pull/12",
                "example.invalid/example/widgets",
            ),
            (
                "gh pr merge https://example.invalid/example/widgets/pull/12",
                "https://example.invalid/example/widgets/pull/12",
                "example.invalid/example/widgets",
            ),
            (
                "gh pr merge topic/example --repo=example/widgets",
                "topic/example",
                "example/widgets",
            ),
        )
        for command, selector, expected_repo in cases:
            calls: list[list[str]] = []

            def fake_run(args: list[str], cwd: str | None = None) -> tuple[int, str]:
                calls.append(args)
                if args[:3] == ["gh", "pr", "view"]:
                    return 0, metadata
                if args[:3] == ["gh", "repo", "view"]:
                    return 0, "example/widgets"
                return 0, "0"

            with self.subTest(command=command), patch.object(merge_guard, "_run", fake_run):
                merge_guard._check_merge(command, shlex.split(command), None)

            self.assertIn(selector, calls[0])
            self.assertEqual(calls[0].count("--repo"), 1)
            self.assertEqual(calls[0][calls[0].index("--repo") + 1], expected_repo)
            self.assertIn(expected_repo, calls[1])

    def test_last_duplicate_repository_selector_wins(self) -> None:
        metadata = json.dumps(
            {
                "baseRefName": "main",
                "headRefOid": "abc123",
                "number": 12,
                "state": "OPEN",
            }
        )
        calls: list[list[str]] = []

        def fake_run(args: list[str], cwd: str | None = None) -> tuple[int, str]:
            calls.append(args)
            if args[:3] == ["gh", "pr", "view"]:
                return 0, metadata
            if args[:3] == ["gh", "repo", "view"]:
                return 0, "second/widgets"
            return 0, "0"

        command = "gh -R first/widgets pr merge 12 --repo second/widgets"
        with patch.object(merge_guard, "_run", fake_run):
            merge_guard._check_merge(command, shlex.split(command), None)

        self.assertEqual(calls[0].count("--repo"), 1)
        self.assertEqual(calls[0][calls[0].index("--repo") + 1], "second/widgets")

    def test_direct_pull_request_merge_api_is_denied(self) -> None:
        commands = (
            "gh api -X PUT repos/example/widgets/pulls/12/merge",
            "gh api repos/example/widgets/pulls/12/merge --method=put",
            "gh --hostname ghe.example.invalid api --method PUT /repos/o/r/pulls/9/merge",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertIn("API", self.deny_reason(command) or "")

    def test_graphql_pull_request_merge_mutation_is_denied(self) -> None:
        command = (
            "gh api graphql -f "
            "'query=mutation { mergePullRequest(input: {pullRequestId: \"PR_1\"}) { clientMutationId } }'"
        )

        self.assertIn("API", self.deny_reason(command) or "")

    def test_pull_request_merge_status_api_get_is_allowed(self) -> None:
        self.assertIsNone(
            self.deny_reason("gh api repos/example/widgets/pulls/12/merge")
        )

    def test_enterprise_host_is_forwarded_to_merge_checks(self) -> None:
        metadata = json.dumps(
            {
                "baseRefName": "main",
                "headRefOid": "abc123",
                "number": 12,
                "state": "OPEN",
            }
        )
        calls: list[list[str]] = []

        def fake_run(args: list[str], cwd: str | None = None) -> tuple[int, str]:
            calls.append(args)
            if "pr" in args and "view" in args:
                return 0, metadata
            if "repo" in args and "view" in args:
                return 0, "example/widgets"
            return 0, "0"

        command = "gh pr merge https://ghe.example.invalid/example/widgets/pull/12"
        with patch.object(merge_guard, "_run", fake_run):
            merge_guard._check_merge(command, shlex.split(command), None)

        compare = next(args for args in calls if "api" in args)
        identity = next(args for args in calls if "repo" in args and "view" in args)
        self.assertEqual(
            "ghe.example.invalid",
            compare[compare.index("--hostname") + 1],
        )
        self.assertIn("ghe.example.invalid/example/widgets", identity)

    def test_unresolved_repository_blocks_merge(self) -> None:
        metadata = json.dumps(
            {
                "baseRefName": "main",
                "headRefOid": "abc123",
                "number": 12,
                "state": "OPEN",
            }
        )
        with (
            patch.object(merge_guard, "_run", side_effect=[(0, metadata), (1, "not found")]),
            redirect_stdout(StringIO()) as output,
            self.assertRaises(SystemExit) as stopped,
        ):
            merge_guard._check_merge("gh pr merge 12", ["gh", "pr", "merge", "12"], None)

        self.assertEqual(stopped.exception.code, 0)
        self.assertIn("could not resolve the repository identity", output.getvalue())

    def test_incomplete_merge_metadata_fails_closed(self) -> None:
        with (
            patch.object(merge_guard, "_run", return_value=(0, json.dumps({"number": 12}))),
            redirect_stdout(StringIO()) as output,
            self.assertRaises(SystemExit) as stopped,
        ):
            merge_guard._check_merge("gh pr merge 12", ["gh", "pr", "merge", "12"], None)

        self.assertEqual(stopped.exception.code, 0)
        self.assertIn("unparseable", output.getvalue())

    def test_malformed_pretool_payloads_do_not_crash(self) -> None:
        payloads = (
            "[]",
            json.dumps({"tool_name": "Bash", "tool_input": ["not", "an", "object"]}),
            json.dumps({"tool_name": "Bash", "tool_input": {"command": ["not", "text"]}}),
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                result = run_hook("merge-guard.py", payload)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
