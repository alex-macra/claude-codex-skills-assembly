from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent


def load_installer():
    spec = importlib.util.spec_from_file_location("public_installer", ROOT / "install.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


installer = load_installer()


def init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)


class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.temp = Path(self.temporary.name)
        self.user_env = {
            "CLAUDE_CONFIG_DIR": str(self.temp / "user" / "claude"),
            "CODEX_HOME": str(self.temp / "user" / "codex"),
            "AGENTS_HOME": str(self.temp / "user" / "agents"),
        }

    def run_main(self, arguments: list[str], env: dict[str, str] | None = None) -> tuple[int, str, str]:
        stdout = StringIO()
        stderr = StringIO()
        with (
            patch.dict(os.environ, env or self.user_env, clear=False),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            result = installer.main(arguments)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_user_install_is_idempotent_and_uninstalls(self) -> None:
        arguments = ["user", "--catalog", str(ROOT / "catalog.json")]
        first = self.run_main(arguments)
        second = self.run_main(arguments)

        self.assertEqual(first[0], 0, first)
        self.assertEqual(second[0], 0, second)
        for home in self.user_env.values():
            skills = Path(home) / "skills"
            self.assertEqual(len(list(skills.iterdir())), 10)
        self.assertEqual(len(list((Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "agents").iterdir())), 2)
        self.assertFalse((Path(self.user_env["CODEX_HOME"]) / "agents").exists())
        self.assertFalse((Path(self.user_env["AGENTS_HOME"]) / "agents").exists())

        claude_styles = Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "output-styles"
        self.assertEqual([path.name for path in claude_styles.iterdir()], ["terse.md"])
        self.assertTrue(claude_styles.is_symlink() is False and (claude_styles / "terse.md").is_symlink())
        self.assertFalse((Path(self.user_env["CODEX_HOME"]) / "output-styles").exists())
        self.assertFalse((Path(self.user_env["AGENTS_HOME"]) / "output-styles").exists())

        removed = self.run_main([*arguments, "--uninstall"])
        self.assertEqual(removed[0], 0, removed)
        for home in self.user_env.values():
            skills = Path(home) / "skills"
            self.assertFalse(any(skills.iterdir()))
        self.assertFalse(any(claude_styles.iterdir()))

    def test_dry_run_writes_nothing(self) -> None:
        result = self.run_main(["user", "--dry-run"])
        self.assertEqual(result[0], 0, result)
        self.assertFalse((self.temp / "user").exists())
        self.assertIn("dry run", result[1])

    def test_project_install_covers_all_surfaces_and_routing(self) -> None:
        project = self.temp / "project"
        init_repo(project)
        arguments = ["project", str(project)]

        first = self.run_main(arguments)
        second = self.run_main(arguments)
        self.assertEqual(first[0], 0, first)
        self.assertEqual(second[0], 0, second)

        for surface in (".claude", ".codex", ".agents"):
            links = list((project / surface / "skills").glob("*/SKILL.md"))
            self.assertEqual(len(links), 10, surface)
            self.assertTrue(
                (
                    project
                    / surface
                    / "skills/delivery-loop/scripts/browser-suite-lease.py"
                ).is_file()
            )
        rules = json.loads((project / ".claude" / "skills" / "skill-rules.json").read_text())
        self.assertEqual(rules["_managedBy"], "ai-skills")
        self.assertEqual(set(rules["skills"]), set(installer.CatalogSet([ROOT / "catalog.json"]).skills))
        gitignore = (project / ".gitignore").read_text()
        self.assertIn(installer.IGNORE_START, gitignore)
        self.assertIn("AGENTS.md", gitignore)
        self.assertEqual(
            [path.name for path in (project / ".claude" / "output-styles").iterdir()],
            ["terse.md"],
        )
        self.assertFalse((project / ".codex" / "output-styles").exists())

        removed = self.run_main([*arguments, "--uninstall"])
        self.assertEqual(removed[0], 0, removed)
        self.assertFalse((project / ".claude" / "skills" / "skill-rules.json").exists())
        self.assertFalse((project / ".gitignore").exists())
        self.assertFalse((project / ".gitignore.bak").exists())
        self.assertFalse(any((project / ".claude" / "output-styles").iterdir()))

    def test_project_shared_state_follows_remaining_surfaces(self) -> None:
        project = self.temp / "partial-project"
        init_repo(project)
        arguments = ["project", str(project), "--surface", "agents"]
        self.assertEqual(self.run_main(arguments)[0], 0)
        self.assertTrue((project / ".claude" / "skills" / "skill-rules.json").is_file())

        removed = self.run_main([*arguments, "--uninstall"])

        self.assertEqual(removed[0], 0, removed)
        self.assertFalse((project / ".claude" / "skills" / "skill-rules.json").exists())
        self.assertFalse((project / ".gitignore").exists())

    def test_entries_already_ignored_are_not_repeated_in_the_block(self) -> None:
        project = self.temp / "partly-ignored"
        init_repo(project)
        (project / ".gitignore").write_text(
            "node_modules\n.codex/\nCLAUDE.md\nAGENTS.md\n", encoding="utf-8"
        )

        self.assertEqual(self.run_main(["project", str(project)])[0], 0)

        gitignore = (project / ".gitignore").read_text()
        self.assertEqual(gitignore.count(".codex/"), 1)
        self.assertEqual(gitignore.count("CLAUDE.md"), 1)
        self.assertEqual(gitignore.count("AGENTS.md"), 1)
        self.assertIn(".claude/", gitignore)
        self.assertIn(".agents/", gitignore)

    def test_a_fully_ignoring_gitignore_is_left_alone(self) -> None:
        project = self.temp / "fully-ignored"
        init_repo(project)
        original = "node_modules\n.agents/\n.claude/\n.codex/\nAGENTS.md\nCLAUDE.md\n"
        (project / ".gitignore").write_text(original, encoding="utf-8")

        self.assertEqual(self.run_main(["project", str(project)])[0], 0)

        self.assertEqual((project / ".gitignore").read_text(), original)
        self.assertNotIn(installer.IGNORE_START, (project / ".gitignore").read_text())
        self.assertFalse((project / ".gitignore.bak").exists())

    def test_a_commented_out_entry_does_not_count_as_ignored(self) -> None:
        project = self.temp / "commented-ignore"
        init_repo(project)
        (project / ".gitignore").write_text("# CLAUDE.md\n", encoding="utf-8")

        self.assertEqual(self.run_main(["project", str(project)])[0], 0)

        block = (project / ".gitignore").read_text().split(installer.IGNORE_START)[1]
        self.assertIn("CLAUDE.md", block)

    def test_unmanaged_file_is_refused(self) -> None:
        target = Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "skills" / "task-research"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("unmanaged\n", encoding="utf-8")

        result = self.run_main(["user", "--surface", "claude"])

        self.assertEqual(result[0], 2)
        self.assertIn("refusing to replace unmanaged path", result[2])
        self.assertEqual((target / "SKILL.md").read_text(), "unmanaged\n")

    def test_foreign_symlink_is_refused(self) -> None:
        foreign = self.temp / "foreign" / "task-research"
        foreign.mkdir(parents=True)
        target = Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "skills" / "task-research"
        target.parent.mkdir(parents=True)
        target.symlink_to(foreign)

        result = self.run_main(["user", "--surface", "claude"])

        self.assertEqual(result[0], 2)
        self.assertEqual(target.resolve(), foreign.resolve())

    def test_explicit_legacy_root_allows_symlink_migration(self) -> None:
        legacy = self.temp / "legacy"
        old_source = legacy / "skills" / "task-research"
        old_source.mkdir(parents=True)
        target = Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "skills" / "task-research"
        target.parent.mkdir(parents=True)
        target.symlink_to(old_source)

        result = self.run_main(
            ["user", "--surface", "claude", "--migrate-from", str(legacy)]
        )

        self.assertEqual(result[0], 0, result)
        self.assertEqual(target.resolve(), (ROOT / "skills" / "task-research").resolve())

    def test_hooks_are_additive_backed_up_and_migrate_legacy_entries(self) -> None:
        settings = Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "settings.json"
        settings.parent.mkdir(parents=True)
        legacy_root = self.temp / "legacy-hooks"
        legacy_hook = legacy_root / "hooks" / "skill-activation.py"
        legacy_hook.parent.mkdir(parents=True)
        legacy_hook.write_text("pass\n", encoding="utf-8")
        relay = {"matcher": "", "hooks": [{"type": "command", "command": "node relay.js"}]}
        legacy = {
            "matcher": "",
            "hooks": [{"type": "command", "command": f"python3 {legacy_hook}"}],
        }
        settings.write_text(
            json.dumps({"hooks": {"UserPromptSubmit": [relay, legacy]}}),
            encoding="utf-8",
        )

        arguments = [
            "user",
            "--surface",
            "claude",
            "--hooks",
            "--migrate-from",
            str(legacy_root),
        ]
        result = self.run_main(arguments)

        self.assertEqual(result[0], 0, result)
        self.assertTrue(settings.with_name("settings.json.bak").is_file())
        data = json.loads(settings.read_text())
        self.assertEqual(data["hooks"]["UserPromptSubmit"][0], relay)
        commands = [
            item["command"]
            for groups in data["hooks"].values()
            for group in groups
            for item in group.get("hooks", [])
        ]
        self.assertEqual(sum("skill-activation.py" in command for command in commands), 1)
        self.assertEqual(sum("skill-usage-log.py" in command for command in commands), 1)
        self.assertEqual(sum("merge-guard.py" in command for command in commands), 1)
        self.assertTrue(all("|| true" in command for command in commands if "skill-" in command))
        self.assertTrue(all("|| true" not in command for command in commands if "merge-guard" in command))

        second = settings.read_text()
        self.assertEqual(self.run_main(arguments)[0], 0)
        self.assertEqual(settings.read_text(), second)

    def test_foreign_hook_with_same_filename_is_preserved(self) -> None:
        settings = Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "settings.json"
        settings.parent.mkdir(parents=True)
        foreign = {
            "matcher": "",
            "hooks": [
                {"type": "command", "command": "python3 /custom/skill-activation.py"}
            ],
        }
        settings.write_text(
            json.dumps({"hooks": {"UserPromptSubmit": [foreign]}}), encoding="utf-8"
        )

        result = self.run_main(["user", "--surface", "claude", "--hooks"])

        self.assertEqual(result[0], 0, result)
        groups = json.loads(settings.read_text())["hooks"]["UserPromptSubmit"]
        self.assertIn(foreign, groups)

    def test_hook_migration_normalizes_symlinked_absolute_paths(self) -> None:
        settings = Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "settings.json"
        settings.parent.mkdir(parents=True)
        legacy_root = self.temp / "legacy-hooks"
        legacy_hook = legacy_root / "hooks" / "skill-activation.py"
        legacy_hook.parent.mkdir(parents=True)
        legacy_hook.write_text("pass\n", encoding="utf-8")
        legacy_alias = self.temp / "legacy-hooks-alias"
        legacy_alias.symlink_to(legacy_root, target_is_directory=True)
        alias_hook = legacy_alias / "hooks" / "skill-activation.py"
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "UserPromptSubmit": [
                            {
                                "matcher": "",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": f"python3 {alias_hook}",
                                    }
                                ],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        result = self.run_main(
            [
                "user",
                "--surface",
                "claude",
                "--hooks",
                "--migrate-from",
                str(legacy_alias),
            ]
        )

        self.assertEqual(result[0], 0, result)
        data = json.loads(settings.read_text())
        commands = [
            item["command"]
            for groups in data["hooks"].values()
            for group in groups
            for item in group.get("hooks", [])
        ]
        self.assertEqual(sum("skill-activation.py" in command for command in commands), 1)

    def test_foreign_hook_symlink_loop_is_preserved(self) -> None:
        settings = Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "settings.json"
        settings.parent.mkdir(parents=True)
        loop = self.temp / "loop"
        loop.symlink_to(loop, target_is_directory=True)
        foreign = {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": f"python3 {loop / 'skill-activation.py'}",
                }
            ],
        }
        settings.write_text(
            json.dumps({"hooks": {"UserPromptSubmit": [foreign]}}),
            encoding="utf-8",
        )

        result = self.run_main(["user", "--surface", "claude", "--hooks"])

        self.assertEqual(result[0], 0, result)
        groups = json.loads(settings.read_text())["hooks"]["UserPromptSubmit"]
        self.assertIn(foreign, groups)

    def test_foreign_wrapper_argument_referencing_managed_hook_is_preserved(self) -> None:
        settings = Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "settings.json"
        settings.parent.mkdir(parents=True)
        managed = ROOT / "hooks" / "skill-activation.py"
        foreign = {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": f"python3 /custom/wrapper.py {managed}",
                }
            ],
        }
        settings.write_text(
            json.dumps({"hooks": {"UserPromptSubmit": [foreign]}}),
            encoding="utf-8",
        )

        result = self.run_main(["user", "--surface", "claude", "--hooks"])

        self.assertEqual(result[0], 0, result)
        groups = json.loads(settings.read_text())["hooks"]["UserPromptSubmit"]
        self.assertIn(foreign, groups)

    def test_malformed_hook_items_are_refused_without_writing(self) -> None:
        settings = Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "settings.json"
        settings.parent.mkdir(parents=True)
        original = json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {"matcher": "", "hooks": "foreign-value"}
                    ]
                }
            }
        )
        settings.write_text(original, encoding="utf-8")

        result = self.run_main(["user", "--surface", "claude", "--hooks"])

        self.assertEqual(result[0], 2, result)
        self.assertIn("must be a list", result[2])
        self.assertEqual(settings.read_text(), original)
        self.assertFalse((settings.parent / "skills").exists())

    def test_global_rules_are_opt_in_and_unmanaged_rules_are_refused(self) -> None:
        self.assertEqual(self.run_main(["user", "--surface", "claude"])[0], 0)
        rule = Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "CLAUDE.md"
        self.assertFalse(rule.exists())

        rule.write_text("local rules\n", encoding="utf-8")
        result = self.run_main(["user", "--surface", "claude", "--global-rules"])
        self.assertEqual(result[0], 2)
        self.assertEqual(rule.read_text(), "local rules\n")

    def test_repeatable_catalogs_and_profiles_compose(self) -> None:
        overlay = self.temp / "overlay"
        skill = overlay / "skills" / "sample-overlay"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: sample-overlay\ndescription: Sample overlay.\nlicense: MIT\n---\n",
            encoding="utf-8",
        )
        (overlay / "routing").mkdir()
        (overlay / "routing" / "rules.json").write_text(
            json.dumps(
                {
                    "skills": {
                        "sample-overlay": {
                            "priority": "medium",
                            "promptTriggers": {"keywords": ["sample overlay"]},
                            "fileTriggers": {},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        catalog = overlay / "catalog.json"
        catalog.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "skills": {"sample-overlay": {"path": "skills/sample-overlay"}},
                    "profiles": {"sample": {"skills": ["sample-overlay"], "agents": []}},
                    "routing": {"registry": "routing/rules.json"},
                }
            ),
            encoding="utf-8",
        )
        project = self.temp / "composed"
        init_repo(project)

        result = self.run_main(
            [
                "project",
                str(project),
                "--catalog",
                str(ROOT / "catalog.json"),
                "--catalog",
                str(catalog),
                "--profile",
                "default",
                "--profile",
                "sample",
                "--surface",
                "codex",
            ]
        )

        self.assertEqual(result[0], 0, result)
        self.assertTrue((project / ".codex" / "skills" / "sample-overlay" / "SKILL.md").is_file())
        rules = json.loads((project / ".claude" / "skills" / "skill-rules.json").read_text())
        self.assertIn("sample-overlay", rules["skills"])

    def test_duplicate_skill_names_across_catalogs_fail(self) -> None:
        duplicate = self.temp / "duplicate.json"
        duplicate.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "skills": {"task-research": {"path": "skills/task-research"}},
                    "profiles": {},
                }
            ),
            encoding="utf-8",
        )

        result = self.run_main(
            [
                "user",
                "--catalog",
                str(ROOT / "catalog.json"),
                "--catalog",
                str(duplicate),
            ]
        )

        self.assertEqual(result[0], 2)
        self.assertIn("duplicate skill name", result[2])

    def test_merge_guard_is_idempotent_and_uninstalls_its_block(self) -> None:
        project = self.temp / "guarded"
        init_repo(project)
        hook = project / ".git" / "hooks" / "pre-push"
        hook.write_text("#!/usr/bin/env sh\necho existing\n", encoding="utf-8")

        arguments = ["merge-guard", str(project)]
        first = self.run_main(arguments)
        installed = hook.read_text()
        second = self.run_main(arguments)

        self.assertEqual(first[0], 0, first)
        self.assertEqual(second[0], 0, second)
        self.assertEqual(installed, hook.read_text())
        self.assertIn("echo existing", installed)
        self.assertEqual(installed.count(installer.MERGE_GUARD_START), 1)
        self.assertIn("merge guard is missing", installed)
        self.assertIn('--git-pre-push "$1"', installed)
        self.assertTrue(hook.with_name("pre-push.bak").is_file())

        removed = self.run_main([*arguments, "--uninstall"])
        self.assertEqual(removed[0], 0, removed)
        self.assertNotIn(installer.MERGE_GUARD_START, hook.read_text())
        self.assertIn("echo existing", hook.read_text())

    def test_install_preflights_all_surfaces_before_writing(self) -> None:
        collision = Path(self.user_env["AGENTS_HOME"]) / "skills" / "adversarial-review"
        collision.mkdir(parents=True)
        (collision / "SKILL.md").write_text("foreign\n", encoding="utf-8")

        result = self.run_main(["user"])

        self.assertEqual(result[0], 2, result)
        self.assertFalse(Path(self.user_env["CLAUDE_CONFIG_DIR"]).exists())
        self.assertFalse(Path(self.user_env["CODEX_HOME"]).exists())
        self.assertEqual((collision / "SKILL.md").read_text(), "foreign\n")

    def test_project_rejects_symlinked_surface_parent(self) -> None:
        project = self.temp / "parent-escape"
        outside = self.temp / "outside"
        init_repo(project)
        outside.mkdir()
        (project / ".claude").symlink_to(outside, target_is_directory=True)

        result = self.run_main(["project", str(project), "--surface", "claude"])

        self.assertEqual(result[0], 2, result)
        self.assertIn("outside its installation root", result[2])
        self.assertEqual(list(outside.iterdir()), [])

    def test_catalog_name_traversal_is_rejected(self) -> None:
        catalog = self.temp / "traversal.json"
        catalog.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "skills": {"../../escaped": {"path": "skills/placeholder"}},
                    "profiles": {"default": {"skills": ["../../escaped"], "agents": []}},
                }
            ),
            encoding="utf-8",
        )

        result = self.run_main(["user", "--catalog", str(catalog)])

        self.assertEqual(result[0], 2, result)
        self.assertFalse((self.temp / "escaped").exists())

    def test_nested_project_path_installs_at_git_root(self) -> None:
        project = self.temp / "nested-root"
        nested = project / "src" / "nested"
        init_repo(project)
        nested.mkdir(parents=True)

        result = self.run_main(["project", str(nested), "--surface", "agents"])

        self.assertEqual(result[0], 0, result)
        self.assertTrue((project / ".agents" / "skills" / "task-research").is_symlink())
        self.assertFalse((project / "src" / ".agents").exists())

    def test_backup_never_follows_existing_backup_symlink(self) -> None:
        project = self.temp / "safe-backup"
        init_repo(project)
        gitignore = project / ".gitignore"
        gitignore.write_text("local.txt\n", encoding="utf-8")
        victim = self.temp / "victim.txt"
        victim.write_text("keep\n", encoding="utf-8")
        gitignore.with_name(".gitignore.bak").symlink_to(victim)

        result = self.run_main(["project", str(project), "--surface", "agents"])

        self.assertEqual(result[0], 0, result)
        self.assertEqual(victim.read_text(), "keep\n")
        self.assertTrue((project / ".gitignore.bak.1").is_file())

    def test_plain_uninstall_removes_opt_in_hooks_and_rules(self) -> None:
        arguments = ["user", "--surface", "claude", "--hooks", "--global-rules"]
        self.assertEqual(self.run_main(arguments)[0], 0)
        root = Path(self.user_env["CLAUDE_CONFIG_DIR"])
        settings = root / "settings.json"
        self.assertTrue((root / "CLAUDE.md").is_symlink())
        self.assertIn("merge-guard.py", settings.read_text())

        result = self.run_main(["user", "--surface", "claude", "--uninstall"])

        self.assertEqual(result[0], 0, result)
        self.assertFalse((root / "CLAUDE.md").exists())
        self.assertNotIn("skill-activation.py", settings.read_text())
        self.assertNotIn("skill-usage-log.py", settings.read_text())
        self.assertNotIn("merge-guard.py", settings.read_text())

    def test_reinstall_prunes_entries_removed_from_catalog(self) -> None:
        self.assertEqual(self.run_main(["user", "--surface", "claude"])[0], 0)
        overlay = self.temp / "small-catalog"
        skill = overlay / "skills" / "sample-only"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: sample-only\ndescription: Sample only.\nlicense: MIT\n---\n",
            encoding="utf-8",
        )
        catalog = overlay / "catalog.json"
        catalog.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "skills": {"sample-only": {"path": "skills/sample-only"}},
                    "profiles": {"default": {"skills": ["sample-only"], "agents": []}},
                }
            ),
            encoding="utf-8",
        )

        result = self.run_main(
            ["user", "--surface", "claude", "--catalog", str(catalog)]
        )

        self.assertEqual(result[0], 0, result)
        names = {path.name for path in (Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "skills").iterdir()}
        self.assertEqual(names, {"sample-only"})

    def test_uninstall_works_after_managed_source_disappears(self) -> None:
        overlay = self.temp / "missing-source"
        skill = overlay / "skills" / "sample-only"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: sample-only\ndescription: Sample only.\nlicense: MIT\n---\n",
            encoding="utf-8",
        )
        catalog = overlay / "catalog.json"
        catalog.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "skills": {"sample-only": {"path": "skills/sample-only"}},
                    "profiles": {"default": {"skills": ["sample-only"], "agents": []}},
                }
            ),
            encoding="utf-8",
        )
        arguments = ["user", "--surface", "claude", "--catalog", str(catalog)]
        self.assertEqual(self.run_main(arguments)[0], 0)
        shutil.rmtree(skill)

        result = self.run_main([*arguments, "--uninstall"])

        self.assertEqual(result[0], 0, result)
        target = Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "skills" / "sample-only"
        self.assertFalse(target.exists())

    def test_reinstall_relinks_a_skill_after_its_catalog_moves(self) -> None:
        original = self.temp / "original-overlay"
        skill = original / "skills" / "sample-only"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: sample-only\ndescription: Sample only.\nlicense: MIT\n---\n",
            encoding="utf-8",
        )
        catalog = original / "catalog.json"
        catalog.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "skills": {"sample-only": {"path": "skills/sample-only"}},
                    "profiles": {"default": {"skills": ["sample-only"], "agents": []}},
                }
            ),
            encoding="utf-8",
        )
        arguments = ["user", "--surface", "claude", "--catalog", str(catalog)]
        self.assertEqual(self.run_main(arguments)[0], 0)
        target = Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "skills" / "sample-only"

        moved = self.temp / "moved-overlay"
        original.rename(moved)
        result = self.run_main(
            ["user", "--surface", "claude", "--catalog", str(moved / "catalog.json")]
        )

        self.assertEqual(result[0], 0, result)
        self.assertEqual(target.resolve(), (moved / "skills" / "sample-only").resolve())

    def test_project_routing_preserves_skills_on_unselected_surfaces(self) -> None:
        project = self.temp / "routing-union"
        init_repo(project)
        self.assertEqual(
            self.run_main(["project", str(project), "--surface", "codex"])[0],
            0,
        )
        overlay = self.temp / "routing-overlay"
        skill = overlay / "skills" / "sample-overlay"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: sample-overlay\ndescription: Sample.\nlicense: MIT\n---\n",
            encoding="utf-8",
        )
        (overlay / "rules.json").write_text(
            json.dumps(
                {
                    "skills": {
                        "sample-overlay": {
                            "priority": "medium",
                            "promptTriggers": {"keywords": ["sample"]},
                            "fileTriggers": {},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        catalog = overlay / "catalog.json"
        catalog.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "skills": {"sample-overlay": {"path": "skills/sample-overlay"}},
                    "profiles": {"default": {"skills": ["sample-overlay"], "agents": []}},
                    "routing": {"registry": "rules.json"},
                }
            ),
            encoding="utf-8",
        )

        result = self.run_main(
            [
                "project",
                str(project),
                "--surface",
                "agents",
                "--catalog",
                str(catalog),
            ]
        )

        self.assertEqual(result[0], 0, result)
        rules = json.loads(
            (project / ".claude" / "skills" / "skill-rules.json").read_text()
        )["skills"]
        self.assertEqual(len(rules), 11)
        self.assertIn("task-research", rules)
        self.assertIn("sample-overlay", rules)

    def test_public_only_uninstall_removes_overlay_hooks_and_global_rule(self) -> None:
        overlay = self.temp / "owned-overlay"
        skill = overlay / "skills" / "sample-only"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: sample-only\ndescription: Sample.\nlicense: MIT\n---\n",
            encoding="utf-8",
        )
        rules = overlay / "global.md"
        rules.write_text("overlay rules\n", encoding="utf-8")
        hooks = overlay / "hooks"
        hooks.mkdir()
        for filename in ("activate.py", "usage.py", "guard.py"):
            (hooks / filename).write_text("raise SystemExit(0)\n", encoding="utf-8")
        catalog = overlay / "catalog.json"
        catalog.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "skills": {"sample-only": {"path": "skills/sample-only"}},
                    "profiles": {"default": {"skills": ["sample-only"], "agents": []}},
                    "globalRules": {"claude": "global.md"},
                    "hooks": {
                        "activation": "hooks/activate.py",
                        "usage": "hooks/usage.py",
                        "mergeGuard": "hooks/guard.py",
                    },
                }
            ),
            encoding="utf-8",
        )
        installed = self.run_main(
            [
                "user",
                "--surface",
                "claude",
                "--catalog",
                str(catalog),
                "--hooks",
                "--global-rules",
            ]
        )
        self.assertEqual(installed[0], 0, installed)
        root = Path(self.user_env["CLAUDE_CONFIG_DIR"])
        self.assertEqual((root / "CLAUDE.md").resolve(), rules.resolve())
        self.assertIn(str(hooks), (root / "settings.json").read_text())

        removed = self.run_main(
            [
                "user",
                "--surface",
                "claude",
                "--catalog",
                str(ROOT / "catalog.json"),
                "--uninstall",
            ]
        )

        self.assertEqual(removed[0], 0, removed)
        self.assertFalse((root / "CLAUDE.md").exists())
        self.assertNotIn(str(hooks), (root / "settings.json").read_text())
        self.assertFalse((root / "skills" / "sample-only").exists())
        self.assertFalse((root / installer.STATE_FILE).exists())

    @unittest.skipIf(os.name == "nt", "permission mode test requires POSIX")
    def test_unwritable_later_surface_is_refused_before_any_write(self) -> None:
        agents_root = Path(self.user_env["AGENTS_HOME"])
        agents_root.mkdir(parents=True)
        agents_root.chmod(0o555)
        self.addCleanup(agents_root.chmod, 0o755)

        result = self.run_main(["user"])

        self.assertEqual(result[0], 2, result)
        self.assertIn("not writable", result[2])
        self.assertFalse(Path(self.user_env["CLAUDE_CONFIG_DIR"]).exists())
        self.assertFalse(Path(self.user_env["CODEX_HOME"]).exists())

    def test_hook_commands_use_current_interpreter_and_guard_timeout(self) -> None:
        result = self.run_main(["user", "--surface", "claude", "--hooks"])
        self.assertEqual(result[0], 0, result)
        settings = json.loads(
            (Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "settings.json").read_text()
        )
        installed = [
            item
            for groups in settings["hooks"].values()
            for group in groups
            for item in group.get("hooks", [])
        ]
        self.assertTrue(all(str(installer.PYTHON) in item["command"] for item in installed))
        self.assertTrue(all(" -I " in item["command"] for item in installed))
        timeouts = {
            Path(item["command"].split()[-1]).name: item["timeout"]
            for item in installed
            if "merge-guard.py" in item["command"]
        }
        self.assertEqual(list(timeouts.values()), [50])

    def guard_overlay(self) -> tuple[Path, Path]:
        catalog = self.overlay_catalog("guard-overlay")
        guard = catalog.parent / "hooks" / "merge-guard.py"
        guard.parent.mkdir()
        guard.write_text(
            (ROOT / "hooks" / "merge-guard.py").read_text(encoding="utf-8"), encoding="utf-8"
        )
        data = json.loads(catalog.read_text(encoding="utf-8"))
        data["hooks"] = {"mergeGuard": "hooks/merge-guard.py"}
        catalog.write_text(json.dumps(data), encoding="utf-8")
        return catalog, guard.resolve()

    def installed_guard_commands(self, catalog: Path) -> list[str]:
        result = self.run_main(
            ["user", "--surface", "claude", "--catalog", str(catalog), "--hooks"]
        )
        self.assertEqual(result[0], 0, result)
        settings = json.loads(
            (Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "settings.json").read_text()
        )
        return [
            item["command"]
            for group in settings["hooks"]["PreToolUse"]
            if group.get("matcher") == "Bash"
            for item in group["hooks"]
        ]

    def run_guard_hook(self, command: str, payload: str) -> subprocess.CompletedProcess:
        work = self.temp / "work"
        if not work.exists():
            init_repo(work)
        return subprocess.run(
            ["/bin/sh", "-c", command],
            input=payload,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(work),
            check=False,
        )

    @staticmethod
    def bash_payload(command: object, cwd: str = "/srv/work", description: str = "") -> str:
        return json.dumps(
            {
                "session_id": "sample",
                "cwd": cwd,
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": command, "description": description},
            }
        )

    @unittest.skipIf(os.name == "nt", "the hook command is POSIX shell")
    def test_merge_guard_hook_runs_the_guard_when_present(self) -> None:
        catalog, guard = self.guard_overlay()
        [command] = self.installed_guard_commands(catalog)

        denied = self.run_guard_hook(command, self.bash_payload("git push origin main"))
        allowed = self.run_guard_hook(command, self.bash_payload("git status --short"))

        self.assertIn(str(guard), command)
        self.assertEqual(denied.returncode, 0, denied.stderr)
        reason = json.loads(denied.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("protected branch 'main'", reason)
        self.assertEqual((0, "", ""), (allowed.returncode, allowed.stdout, allowed.stderr))

    @unittest.skipIf(os.name == "nt", "the hook command is POSIX shell")
    def test_missing_merge_guard_blocks_only_git_gh_and_curl(self) -> None:
        catalog, guard = self.guard_overlay()
        [command] = self.installed_guard_commands(catalog)
        guard.unlink()

        blocked = (
            self.bash_payload("git status"),
            self.bash_payload("gh pr list"),
            self.bash_payload("curl -X PUT https://api.example.invalid/pulls/1/merge"),
            self.bash_payload("cd repo\ngit push origin main"),
            self.bash_payload("echo ready && GIT push origin main"),
            self.bash_payload("/usr/bin/git push origin main"),
            self.bash_payload(["git", "push", "origin", "main"]),
            "not json: git push origin main",
        )
        allowed = (
            self.bash_payload("ls -la"),
            self.bash_payload("python3 install.py user --hooks"),
            self.bash_payload("cat .github/workflows/ci.yml && echo legit digits"),
            self.bash_payload("ls", cwd="/srv/git/project", description="List git hooks"),
            "not json at all",
        )
        for payload in blocked:
            with self.subTest(blocked=payload):
                result = self.run_guard_hook(command, payload)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(f"merge guard is missing: {guard}", result.stderr)
        for payload in allowed:
            with self.subTest(allowed=payload):
                result = self.run_guard_hook(command, payload)
                self.assertEqual((0, "", ""), (result.returncode, result.stdout, result.stderr))

    def test_previous_merge_guard_entry_is_replaced_once(self) -> None:
        settings = Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "settings.json"
        settings.parent.mkdir(parents=True)
        guard = ROOT / "hooks" / "merge-guard.py"
        previous = shlex.join([str(installer.PYTHON), "-I", str(guard)])
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [{"type": "command", "command": previous, "timeout": 50}],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        commands = self.installed_guard_commands(ROOT / "catalog.json")
        first = settings.read_text()
        again = self.installed_guard_commands(ROOT / "catalog.json")

        self.assertEqual(len(commands), 1, commands)
        self.assertTrue(commands[0].startswith("test -f "), commands[0])
        self.assertNotIn(previous, commands)
        self.assertEqual(commands, again)
        self.assertEqual(first, settings.read_text())

    def overlay_catalog(
        self,
        name: str,
        surfaces: dict | None = None,
        agents: bool = False,
        routing: bool = False,
    ) -> Path:
        root = self.temp / name
        skill = root / "skills" / "sample-only"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: sample-only\ndescription: Sample only.\nlicense: MIT\n---\n",
            encoding="utf-8",
        )
        data: dict = {
            "schemaVersion": 1,
            "skills": {"sample-only": {"path": "skills/sample-only"}},
            "profiles": {"default": {"skills": ["sample-only"], "agents": []}},
        }
        if agents:
            (root / "agents").mkdir()
            (root / "agents" / "helper.md").write_text(
                "---\nname: helper\ndescription: Helper.\n---\n", encoding="utf-8"
            )
            data["agents"] = {"helper": {"path": "agents/helper.md"}}
            data["profiles"]["default"]["agents"] = ["helper"]
        if surfaces is not None:
            data["surfaces"] = surfaces
        if routing:
            (root / "rules.json").write_text(
                json.dumps(
                    {
                        "skills": {
                            "sample-only": {
                                "priority": "medium",
                                "promptTriggers": {"keywords": ["sample only"]},
                                "fileTriggers": {},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            data["routing"] = {"registry": "rules.json"}
        catalog = root / "catalog.json"
        catalog.write_text(json.dumps(data), encoding="utf-8")
        return catalog

    def extra_dir(self, name: str = "extras", skill: str = "extra-sample", text: str | None = None) -> Path:
        directory = self.temp / name
        path = directory / skill
        path.mkdir(parents=True)
        body = text if text is not None else f"---\nname: {skill}\ndescription: Extra sample.\n---\n# Extra\n"
        (path / "SKILL.md").write_text(body, encoding="utf-8")
        return directory

    def test_public_catalog_declares_claude_only_agents(self) -> None:
        catalogs = installer.CatalogSet([ROOT / "catalog.json"], allow_missing_sources=True)

        self.assertEqual(("claude",), catalogs.agent_surfaces)
        self.assertEqual({"orchestrator", "reviewer"}, set(catalogs.agents))

    def test_catalog_agent_surfaces_are_honored_and_codex_agents_pruned(self) -> None:
        catalog = self.overlay_catalog("agent-surfaces", surfaces={"agents": ["claude", "codex"]}, agents=True)
        arguments = ["user", "--catalog", str(catalog)]
        self.assertEqual(self.run_main(arguments)[0], 0)
        claude_agent = Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "agents" / "helper.md"
        codex_agent = Path(self.user_env["CODEX_HOME"]) / "agents" / "helper.md"
        self.assertTrue(claude_agent.is_symlink())
        self.assertTrue(codex_agent.is_symlink())

        data = json.loads(catalog.read_text(encoding="utf-8"))
        data["surfaces"]["agents"] = ["claude"]
        catalog.write_text(json.dumps(data), encoding="utf-8")
        result = self.run_main(arguments)

        self.assertEqual(result[0], 0, result)
        self.assertTrue(claude_agent.is_symlink())
        self.assertFalse(codex_agent.exists() or codex_agent.is_symlink())
        state = json.loads((Path(self.user_env["CODEX_HOME"]) / installer.STATE_FILE).read_text())
        self.assertEqual({}, state["agents"])
        self.assertFalse((Path(self.user_env["AGENTS_HOME"]) / "agents").exists())

    def test_agents_default_to_claude_and_codex_without_declared_surfaces(self) -> None:
        catalog = self.overlay_catalog("default-surfaces", agents=True)

        result = self.run_main(["user", "--catalog", str(catalog)])

        self.assertEqual(result[0], 0, result)
        self.assertTrue((Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "agents" / "helper.md").is_symlink())
        self.assertTrue((Path(self.user_env["CODEX_HOME"]) / "agents" / "helper.md").is_symlink())
        self.assertFalse((Path(self.user_env["AGENTS_HOME"]) / "agents").exists())

    def test_empty_agent_surfaces_link_no_agents(self) -> None:
        catalog = self.overlay_catalog("no-agent-surfaces", surfaces={"agents": []}, agents=True)

        result = self.run_main(["user", "--catalog", str(catalog)])

        self.assertEqual(result[0], 0, result)
        for home in self.user_env.values():
            self.assertFalse((Path(home) / "agents").exists())

    def test_unknown_agent_surface_is_refused(self) -> None:
        catalog = self.overlay_catalog("bad-surfaces", surfaces={"agents": ["elsewhere"]}, agents=True)

        result = self.run_main(["user", "--catalog", str(catalog)])

        self.assertEqual(result[0], 2, result)
        self.assertIn("surfaces.agents", result[2])

    def test_extra_skills_are_linked_recorded_and_pruned_without_the_flag(self) -> None:
        catalog = self.overlay_catalog("extra-base")
        extras = self.extra_dir()
        arguments = ["user", "--surface", "claude", "--catalog", str(catalog)]
        root = Path(self.user_env["CLAUDE_CONFIG_DIR"])
        target = root / "skills" / "extra-sample"

        installed = self.run_main([*arguments, "--extra-skills", str(extras)])

        self.assertEqual(installed[0], 0, installed)
        self.assertIn("extra skill: extra-sample", installed[1])
        self.assertIn("installed 2 skill(s)", installed[1])
        self.assertEqual(target.resolve(), (extras / "extra-sample").resolve())
        state = json.loads((root / installer.STATE_FILE).read_text())
        self.assertIn("extra-sample", state["skills"])
        self.assertEqual(["extra-sample"], state["extraSkills"])

        pruned = self.run_main(arguments)

        self.assertEqual(pruned[0], 0, pruned)
        self.assertFalse(target.exists() or target.is_symlink())
        self.assertTrue((root / "skills" / "sample-only").is_symlink())
        self.assertEqual([], json.loads((root / installer.STATE_FILE).read_text())["extraSkills"])

    def test_extra_skills_dry_run_lists_them_and_writes_nothing(self) -> None:
        catalog = self.overlay_catalog("extra-dry")
        extras = self.extra_dir()

        result = self.run_main(["user", "--catalog", str(catalog), "--extra-skills", str(extras), "--dry-run"])

        self.assertEqual(result[0], 0, result)
        self.assertIn("extra skill: extra-sample", result[1])
        self.assertIn("skills/extra-sample (dry run)", result[1])
        self.assertFalse((self.temp / "user").exists())

    def many_extras(self, name: str, count: int, width: int = 16) -> Path:
        directory = self.temp / name
        for index in range(count):
            skill = f"extra-listing-{index:02d}".ljust(width, "x")
            (directory / skill).mkdir(parents=True)
            (directory / skill / "SKILL.md").write_text(
                f"---\nname: {skill}\ndescription: {'d' * 250}\n---\n", encoding="utf-8"
            )
        return directory

    def test_extra_skills_count_against_the_listing_budget(self) -> None:
        catalog = self.overlay_catalog("extra-listing")
        cases = ((10, 0, "warning: selected skills with extras costs 2683"), (12, 2, "maximum is 3000"))
        for count, code, expected in cases:
            with self.subTest(count=count):
                extras = self.many_extras(f"listing-{count}", count)
                result = self.run_main(["user", "--catalog", str(catalog), "--extra-skills", str(extras), "--dry-run"])
                self.assertEqual(result[0], code, result)
                self.assertIn(expected, result[2])

        public = self.run_main(
            [
                "user", "--surface", "claude", "--catalog", str(ROOT / "catalog.json"),
                "--extra-skills", str(self.many_extras("listing-public", 1, width=64)), "--dry-run",
            ]
        )
        self.assertEqual(public[0], 0, public)
        self.assertIn("warning: selected skills with extras costs", public[2])

    def test_extra_skill_colliding_with_a_catalog_skill_is_refused(self) -> None:
        catalog = self.overlay_catalog("extra-collision")
        extras = self.extra_dir(skill="sample-only")

        result = self.run_main(["user", "--catalog", str(catalog), "--extra-skills", str(extras)])

        self.assertEqual(result[0], 2, result)
        self.assertIn("collides", result[2])
        self.assertFalse((self.temp / "user").exists())

    def test_invalid_extra_skills_are_refused_before_writing(self) -> None:
        catalog = self.overlay_catalog("extra-invalid")
        cases = {
            "name": ("---\nname: other-name\ndescription: Extra.\n---\n", "frontmatter name"),
            "missing": ("no frontmatter\n", "missing YAML frontmatter"),
            "description": (f"---\nname: extra-sample\ndescription: {'d' * 251}\n---\n", "description must be 1-250"),
            "bash": ("---\nname: extra-sample\ndescription: Extra.\nallowed-tools: Bash\n---\n", "unscoped Bash"),
            "cap": ("---\nname: extra-sample\ndescription: Extra.\n---\n" + "x\n" * 60, "exceed the cap"),
        }
        for label, (text, expected) in cases.items():
            with self.subTest(case=label):
                extras = self.extra_dir(name=f"invalid-{label}", text=text)
                result = self.run_main(["user", "--catalog", str(catalog), "--extra-skills", str(extras)])
                self.assertEqual(result[0], 2, result)
                self.assertIn("invalid extra skill", result[2])
                self.assertIn(expected, result[2])
                self.assertFalse((self.temp / "user").exists())

    def test_symlinked_extra_skill_directory_is_refused(self) -> None:
        catalog = self.overlay_catalog("extra-symlink")
        real = self.extra_dir(name="real-extras")
        extras = self.temp / "linked-extras"
        extras.mkdir()
        (extras / "extra-sample").symlink_to(real / "extra-sample", target_is_directory=True)

        result = self.run_main(["user", "--catalog", str(catalog), "--extra-skills", str(extras)])

        self.assertEqual(result[0], 2, result)
        self.assertIn("must not be a symlink", result[2])

    def test_extra_skills_directory_inside_a_catalog_root_is_refused(self) -> None:
        catalog = self.overlay_catalog("extra-inside")

        result = self.run_main(
            ["user", "--catalog", str(catalog), "--extra-skills", str(catalog.parent / "skills")]
        )

        self.assertEqual(result[0], 2, result)
        self.assertIn("inside a catalog root", result[2])

    def test_missing_or_empty_extra_skills_directory_is_refused(self) -> None:
        catalog = self.overlay_catalog("extra-missing")
        empty = self.temp / "empty-extras"
        empty.mkdir()
        for directory, expected in ((self.temp / "absent", "not found"), (empty, "no skill directories")):
            with self.subTest(directory=directory.name):
                result = self.run_main(["user", "--catalog", str(catalog), "--extra-skills", str(directory)])
                self.assertEqual(result[0], 2, result)
                self.assertIn(expected, result[2])

    def test_extra_skills_stay_out_of_project_routing(self) -> None:
        catalog = self.overlay_catalog("extra-routing", routing=True)
        extras = self.extra_dir()
        project = self.temp / "extra-project"
        init_repo(project)

        result = self.run_main(["project", str(project), "--catalog", str(catalog), "--extra-skills", str(extras)])

        self.assertEqual(result[0], 0, result)
        self.assertTrue((project / ".claude" / "skills" / "extra-sample").is_symlink())
        rules = json.loads((project / ".claude" / "skills" / "skill-rules.json").read_text())["skills"]
        self.assertEqual({"sample-only"}, set(rules))

        narrowed = self.run_main(["project", str(project), "--catalog", str(catalog), "--surface", "codex"])

        self.assertEqual(narrowed[0], 0, narrowed)
        self.assertTrue((project / ".claude" / "skills" / "extra-sample").is_symlink())
        self.assertFalse((project / ".codex" / "skills" / "extra-sample").exists())

    def test_uninstall_removes_extra_skills(self) -> None:
        catalog = self.overlay_catalog("extra-uninstall")
        extras = self.extra_dir()
        arguments = ["user", "--surface", "claude", "--catalog", str(catalog), "--extra-skills", str(extras)]
        self.assertEqual(self.run_main(arguments)[0], 0)

        removed = self.run_main([*arguments, "--uninstall"])

        root = Path(self.user_env["CLAUDE_CONFIG_DIR"])
        self.assertEqual(removed[0], 0, removed)
        self.assertFalse((root / "skills" / "extra-sample").is_symlink())
        self.assertFalse((root / installer.STATE_FILE).exists())

    def test_duplicate_merge_guard_blocks_are_rejected(self) -> None:
        project = self.temp / "duplicate-guard"
        init_repo(project)
        hook = project / ".git" / "hooks" / "pre-push"
        block = f"{installer.MERGE_GUARD_START}\nx\n{installer.MERGE_GUARD_END}\n"
        hook.write_text("#!/bin/sh\n" + block + block, encoding="utf-8")

        result = self.run_main(["merge-guard", str(project), "--uninstall"])

        self.assertEqual(result[0], 2, result)
        self.assertEqual(hook.read_text().count(installer.MERGE_GUARD_START), 2)


if __name__ == "__main__":
    unittest.main()
