from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import importlib.util
import json
import os
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
            self.assertEqual(len(list(skills.iterdir())), 15)
        self.assertEqual(len(list((Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "agents").iterdir())), 3)
        self.assertEqual(len(list((Path(self.user_env["CODEX_HOME"]) / "agents").iterdir())), 3)

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
            self.assertEqual(len(links), 15, surface)
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

    def test_unmanaged_file_is_refused(self) -> None:
        target = Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "skills" / "a11y-audit"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("unmanaged\n", encoding="utf-8")

        result = self.run_main(["user", "--surface", "claude"])

        self.assertEqual(result[0], 2)
        self.assertIn("refusing to replace unmanaged path", result[2])
        self.assertEqual((target / "SKILL.md").read_text(), "unmanaged\n")

    def test_foreign_symlink_is_refused(self) -> None:
        foreign = self.temp / "foreign" / "a11y-audit"
        foreign.mkdir(parents=True)
        target = Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "skills" / "a11y-audit"
        target.parent.mkdir(parents=True)
        target.symlink_to(foreign)

        result = self.run_main(["user", "--surface", "claude"])

        self.assertEqual(result[0], 2)
        self.assertEqual(target.resolve(), foreign.resolve())

    def test_explicit_legacy_root_allows_symlink_migration(self) -> None:
        legacy = self.temp / "legacy"
        old_source = legacy / "skills" / "a11y-audit"
        old_source.mkdir(parents=True)
        target = Path(self.user_env["CLAUDE_CONFIG_DIR"]) / "skills" / "a11y-audit"
        target.parent.mkdir(parents=True)
        target.symlink_to(old_source)

        result = self.run_main(
            ["user", "--surface", "claude", "--migrate-from", str(legacy)]
        )

        self.assertEqual(result[0], 0, result)
        self.assertEqual(target.resolve(), (ROOT / "skills" / "a11y-audit").resolve())

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
                    "skills": {"a11y-audit": {"path": "skills/a11y-audit"}},
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
        self.assertTrue((project / ".agents" / "skills" / "a11y-audit").is_symlink())
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
        self.assertEqual(len(rules), 16)
        self.assertIn("a11y-audit", rules)
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
        timeouts = {
            Path(item["command"].split()[-1]).name: item["timeout"]
            for item in installed
            if "merge-guard.py" in item["command"]
        }
        self.assertEqual(list(timeouts.values()), [50])

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
