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


class KeywordBoundaryTests(unittest.TestCase):
    def routes(self, keyword: str, prompt: str) -> bool:
        entries = {"sample-skill": {"promptTriggers": {"keywords": [keyword]}}}
        return activation.match_skills(prompt, entries) == ["sample-skill"]

    def test_short_keywords_match_whole_words_only(self) -> None:
        cases = {
            "CI": (("set up CI for this repo", "fix the CI/CD job"), ("read the specification", "decide later")),
            "RCE": (("is this an RCE?", "rce via the upload form"), ("check the source", "force the update")),
            "API": (("the API is slow", "api-first design"), ("a rapid capital plan", "therapist notes")),
            "E2E": (("write E2E tests", "run the e2e suite"), ("build be2e7 now", "the e2ex tool")),
            "DRY": (("keep it DRY", "dry run first"), ("the laundry dryer", "a sundry list")),
        }
        for keyword, (positives, negatives) in cases.items():
            for prompt in positives:
                with self.subTest(keyword=keyword, prompt=prompt):
                    self.assertTrue(self.routes(keyword, prompt))
            for prompt in negatives:
                with self.subTest(keyword=keyword, prompt=prompt):
                    self.assertFalse(self.routes(keyword, prompt))

    def test_boundaries_apply_only_at_alphanumeric_keyword_edges(self) -> None:
        self.assertTrue(self.routes("it(", "it('works', () => {})"))
        self.assertFalse(self.routes("it(", "split(value)"))

    def test_every_keyword_needs_a_word_start_and_allows_common_suffixes(self) -> None:
        cases = {
            "deploy": (("deploying the service", "two deploys today", "deployed"), ("redeploying the service",)),
            "tests": (("unit tests pass",), ("pytests pass", "summarize the latest contests")),
            "secret": (("add secrets scanning", "a leaked secret"), ("the secretary emailed me",)),
            "solid": (("keep it SOLID",), ("consolidate the two config files",)),
            "express": (("an Express server",), ("fix this regular expression",)),
            "mock": (("the mocks are stale",), ("hammock time", "mockery")),
            "vuln": (("check these vulns",), ("vulnerable",)),
        }
        for keyword, (positives, negatives) in cases.items():
            for prompt in positives:
                with self.subTest(keyword=keyword, prompt=prompt):
                    self.assertTrue(self.routes(keyword, prompt))
            for prompt in negatives:
                with self.subTest(keyword=keyword, prompt=prompt):
                    self.assertFalse(self.routes(keyword, prompt))

    def test_empty_keyword_never_matches(self) -> None:
        self.assertFalse(self.routes("", "any prompt at all"))

    def test_public_registry_ignores_short_keyword_substrings(self) -> None:
        entries = activation.load_rules(ROOT / "routing" / "skill-rules.json")

        self.assertNotIn("security-review", activation.match_skills("find the source of the force", entries))
        self.assertEqual([], activation.match_skills("summarize the specification", entries))
        self.assertIn("security-review", activation.match_skills("is this an RCE", entries))
        self.assertEqual(["web-dev"], activation.match_skills("fix my crontab entry", entries))
        self.assertEqual(["security-review"], activation.match_skills("check these vulns", entries))
        self.assertEqual([], activation.match_skills("the secretary emailed me", entries))

    def test_every_routed_skill_has_three_positive_fixtures(self) -> None:
        rules = json.loads((ROOT / "routing" / "skill-rules.json").read_text(encoding="utf-8"))["skills"]
        fixtures = json.loads((ROOT / "routing" / "routing-expectations.json").read_text(encoding="utf-8"))
        counts = {name: 0 for name in rules}
        for expected in fixtures["positive"].values():
            for name in expected:
                counts[name] = counts.get(name, 0) + 1

        self.assertEqual({}, {name: count for name, count in counts.items() if count < 3})


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


class MergeGuardCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.temp = Path(temporary.name)
        self.work = self.temp / "work"
        self.work.mkdir()
        subprocess.run(["git", "init", "-q", str(self.work)], check=True)

    def check(self, *args: str, hooks: Path = HOOKS) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-I", "-B", "-S", str(hooks / "merge-guard-check.py"), *args],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(self.work),
            check=False,
        )

    def hooks_with_policy(self, policy: str | None) -> Path:
        hooks = self.temp / "hooks"
        hooks.mkdir()
        adapter = (HOOKS / "merge-guard-check.py").read_text(encoding="utf-8")
        (hooks / "merge-guard-check.py").write_text(adapter, encoding="utf-8")
        if policy is not None:
            (hooks / "merge-guard.py").write_text(policy, encoding="utf-8")
        return hooks

    def test_allowed_commands_exit_zero_without_output(self) -> None:
        for command in ("git status --short", "git push origin topic/example", "ls -la"):
            with self.subTest(command=command):
                result = self.check(command)
                self.assertEqual((0, "", ""), (result.returncode, result.stdout, result.stderr))

    def test_protected_push_is_denied_with_the_reason_on_stdout(self) -> None:
        result = self.check("git push origin HEAD:refs/heads/main")

        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("protected branch 'main'", result.stdout)
        self.assertEqual("", result.stderr)

    def test_decisions_and_reasons_match_the_pretooluse_hook(self) -> None:
        commands = (
            "git push origin main",
            "git push origin topic/example",
            "env git push origin main",
            "AI_SKILLS_ALLOW_PROTECTED=1 git push origin main",
            "echo ready\ngh pr merge 12 --admin",
            "gh api -X PUT repos/example/widgets/pulls/12/merge",
            "gh api repos/example/widgets/pulls/12/merge",
            "MERGE='gh pr merge 12 --admin'; eval \"$MERGE\"",
            "git config alias.ship 'push --no-verify'",
            "echo 'git push origin main'",
        )
        for command in commands:
            with self.subTest(command=command):
                expected = self.hook_reason(command, self.work)
                result = self.check("--cwd", str(self.work), command)
                self.assertEqual((1 if expected else 0, expected), (result.returncode, result.stdout.strip()))

    def hook_reason(self, command: str, cwd: Path) -> str:
        hook = subprocess.run(
            [sys.executable, str(HOOKS / "merge-guard.py")],
            input=json.dumps(
                {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
            ),
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(self.work),
            check=False,
        )
        self.assertEqual(0, hook.returncode, hook.stderr)
        if not hook.stdout.strip():
            return ""
        return json.loads(hook.stdout)["hookSpecificOutput"]["permissionDecisionReason"]

    def test_cwd_resolves_implicit_push_targets_in_the_shell_directory(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.work), "symbolic-ref", "HEAD", "refs/heads/topic/example"],
            check=True,
        )
        main_checkout = self.temp / "main-checkout"
        subprocess.run(["git", "init", "-q", "-b", "main", str(main_checkout)], check=True)

        expected = self.hook_reason("git push", main_checkout)
        scoped = self.check("--cwd", str(main_checkout), "git push")
        unscoped = self.check("git push")

        self.assertIn("protected branch 'main'", expected)
        self.assertEqual((1, expected), (scoped.returncode, scoped.stdout.strip()))
        self.assertEqual((0, ""), (unscoped.returncode, unscoped.stdout))

    def test_blank_command_prints_usage_and_allows(self) -> None:
        result = self.check("  ")

        self.assertEqual(0, result.returncode)
        self.assertIn("usage:", result.stderr)

    def test_any_other_argument_shape_prints_usage_and_denies(self) -> None:
        shapes = (
            (),
            ("git status", "extra"),
            ("gh", "pr", "merge", "12", "--admin"),
            ("--cwd", str(self.work)),
            ("--cwd", str(self.work), "git", "push"),
        )
        for args in shapes:
            with self.subTest(args=args):
                result = self.check(*args)
                self.assertEqual((1, ""), (result.returncode, result.stdout))
                self.assertIn("usage:", result.stderr)

    def test_cwd_that_is_not_a_directory_denies(self) -> None:
        for cwd in ("", str(self.temp / "missing")):
            with self.subTest(cwd=cwd):
                result = self.check("--cwd", cwd, "ls")
                self.assertEqual(1, result.returncode)
                self.assertIn("--cwd is not a directory", result.stderr)

    def test_policy_crash_fails_closed(self) -> None:
        hooks = self.hooks_with_policy("def run_pretooluse():\n    raise RuntimeError('boom')\n")

        result = self.check("ls", hooks=hooks)

        self.assertEqual(1, result.returncode)
        self.assertIn("merge guard crashed (boom)", result.stderr)

    def test_policy_nonzero_exit_fails_closed(self) -> None:
        hooks = self.hooks_with_policy("import sys\n\ndef run_pretooluse():\n    sys.exit(2)\n")

        result = self.check("ls", hooks=hooks)

        self.assertEqual(1, result.returncode)
        self.assertIn("merge guard exited with 2", result.stderr)

    def test_missing_policy_fails_closed(self) -> None:
        hooks = self.hooks_with_policy(None)

        result = self.check("ls", hooks=hooks)

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)


if __name__ == "__main__":
    unittest.main()
