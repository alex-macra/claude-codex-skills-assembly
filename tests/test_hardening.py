from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from scripts import validate as validator


ROOT = Path(__file__).resolve().parent.parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


activation = load_module("hardening_activation", ROOT / "hooks/skill-activation.py")


class ActivationRegexHardeningTests(unittest.TestCase):
    def test_nested_and_ambiguous_repetition_is_rejected(self) -> None:
        patterns = [r"(a+)+$", r"(a|aa)+$", r"(?:.*)*$", r"a*a*a*a*a*b"]

        for pattern in patterns:
            with self.subTest(pattern=pattern):
                self.assertFalse(activation.is_safe_intent_pattern(pattern))

        self.assertFalse(activation.matches_intent("a" * 2_048 + "!", patterns))

    def test_unsafe_project_registry_pattern_cannot_block_the_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".git").mkdir()
            rules = root / ".claude/skills/skill-rules.json"
            rules.parent.mkdir(parents=True)
            rules.write_text(
                json.dumps(
                    {
                        "skills": {
                            "sample": {
                                "promptTriggers": {"keywords": [], "intentPatterns": [r"(a+)+$"]},
                                "fileTriggers": {"pathPatterns": [], "pathExclusions": []},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            skill = root / ".claude/skills/sample/SKILL.md"
            skill.parent.mkdir()
            skill.write_text("sample\n", encoding="utf-8")
            environment = os.environ.copy()
            environment["CLAUDE_CONFIG_DIR"] = str(root / "empty-claude")
            environment["CODEX_HOME"] = str(root / "empty-codex")
            environment["AGENTS_HOME"] = str(root / "empty-agents")

            result = subprocess.run(
                [sys.executable, str(ROOT / "hooks/skill-activation.py")],
                input=json.dumps({"prompt": "a" * 2_048 + "!"}),
                capture_output=True,
                text=True,
                cwd=root,
                env=environment,
                timeout=1,
                check=False,
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_separated_repeat_pattern_is_runtime_bounded(self) -> None:
        pattern = r"a*aa*aa*aa*aa*b"
        started = time.monotonic()

        matched = activation.bounded_intent_search(pattern, "a" * 100 + "!")

        self.assertFalse(matched)
        self.assertLess(time.monotonic() - started, 0.25)

    def test_shipped_intent_patterns_remain_accepted(self) -> None:
        registry = json.loads((ROOT / "routing/skill-rules.json").read_text(encoding="utf-8"))
        patterns = [
            pattern
            for config in registry["skills"].values()
            for key in ("intentPatterns", "excludePatterns")
            for pattern in config.get("promptTriggers", {}).get(key, [])
        ]

        self.assertTrue(patterns)
        self.assertTrue(all(activation.is_safe_intent_pattern(pattern) for pattern in patterns))

    def test_validator_reports_an_unsafe_catalog_regex(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hook = root / "hooks/skill-activation.py"
            hook.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / "hooks/skill-activation.py", hook)
            registry_path = root / "routing/skill-rules.json"
            fixtures_path = root / "routing/routing-expectations.json"
            registry_path.parent.mkdir(parents=True)
            registry_path.write_text(
                json.dumps(
                    {
                        "skills": {
                            "sample": {
                                "priority": "medium",
                                "promptTriggers": {
                                    "keywords": ["safe-keyword"],
                                    "intentPatterns": [r"(a+)+$"],
                                },
                                "fileTriggers": {"pathPatterns": [], "pathExclusions": []},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            fixtures_path.write_text(
                json.dumps({"positive": {"safe-keyword": ["sample"]}, "negative": []}),
                encoding="utf-8",
            )

            findings = validator.validate_routing(
                root,
                {"sample"},
                registry_path,
                fixtures_path,
            )

        self.assertTrue(any("unsafe intent regex" in item.message for item in findings))

    def test_validator_reports_an_unsafe_exclusion_regex(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hook = root / "hooks/skill-activation.py"
            hook.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / "hooks/skill-activation.py", hook)
            registry_path = root / "routing/skill-rules.json"
            fixtures_path = root / "routing/routing-expectations.json"
            registry_path.parent.mkdir(parents=True)
            registry_path.write_text(
                json.dumps(
                    {
                        "skills": {
                            "sample": {
                                "priority": "medium",
                                "promptTriggers": {
                                    "keywords": ["safe-keyword"],
                                    "intentPatterns": [],
                                    "excludePatterns": [r"(a+)+$"],
                                },
                                "fileTriggers": {"pathPatterns": [], "pathExclusions": []},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            fixtures_path.write_text(
                json.dumps({"positive": {"safe-keyword": ["sample"]}, "negative": []}),
                encoding="utf-8",
            )

            findings = validator.validate_routing(
                root,
                {"sample"},
                registry_path,
                fixtures_path,
            )

        self.assertTrue(any("unsafe exclusion regex" in item.message for item in findings))


@unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO support is required")
class UsageLogHardeningTests(unittest.TestCase):
    def test_existing_fifo_without_a_reader_fails_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fifo = Path(temporary) / "usage.jsonl"
            os.mkfifo(fifo)
            environment = os.environ.copy()
            environment["AI_SKILLS_USAGE_LOG"] = str(fifo)
            payload = json.dumps({"tool_input": {"skill": "qa-automation"}, "cwd": temporary})

            result = subprocess.run(
                [sys.executable, str(ROOT / "hooks/skill-usage-log.py")],
                input=payload,
                capture_output=True,
                text=True,
                env=environment,
                timeout=1,
                check=False,
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")


class ValidatorPrivacyHardeningTests(unittest.TestCase):
    def privacy_findings(self, root: Path) -> list[validator.Finding]:
        entries = validator.repo_entries(root)
        return validator.check_privacy(root, entries, validator.regular_files(root, entries))

    def test_var_home_path_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private_path = "/" + "var" + "/" + "home" + "/sample/private.txt"
            (root / "notes.txt").write_text(f"source: {private_path}\n", encoding="utf-8")

            findings = self.privacy_findings(root)

        self.assertTrue(any("absolute home path" in item.message for item in findings))

    def test_tracked_file_under_node_modules_is_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            leak = root / "node_modules/package/metadata.txt"
            leak.parent.mkdir(parents=True)
            private_path = "/" + "home" + "/sample/private.txt"
            leak.write_text(f"source: {private_path}\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "-f", "node_modules/package/metadata.txt"], check=True)

            entries = validator.repo_entries(root)
            findings = validator.check_privacy(root, entries, validator.regular_files(root, entries))

        self.assertIn(leak, entries)
        self.assertTrue(any(item.path == "node_modules/package/metadata.txt" for item in findings))

    def test_generated_state_is_skipped_unless_tracked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            private_path = "/" + "home" + "/sample/private.txt"
            ignored = root / ".codex/local.json"
            ignored.parent.mkdir(parents=True)
            ignored.write_text(f"source: {private_path}\n", encoding="utf-8")
            backup = root / ".gitignore.bak"
            backup.write_text(f"source: {private_path}\n", encoding="utf-8")
            numbered_backup = root / ".gitignore.bak.1"
            numbered_backup.write_text(f"source: {private_path}\n", encoding="utf-8")
            backup_directory_file = root / ".gitignore.bak.2/private.txt"
            backup_directory_file.parent.mkdir()
            backup_directory_file.write_text(f"source: {private_path}\n", encoding="utf-8")

            entries = validator.repo_entries(root)

            self.assertNotIn(ignored, entries)
            self.assertNotIn(backup, entries)
            self.assertNotIn(numbered_backup, entries)
            self.assertNotIn(backup_directory_file, entries)
            subprocess.run(["git", "-C", str(root), "add", "-f", ".codex/local.json"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "add", "-f", ".gitignore.bak.1"],
                check=True,
            )
            entries = validator.repo_entries(root)
            findings = validator.check_privacy(root, entries, validator.regular_files(root, entries))

        self.assertIn(ignored, entries)
        self.assertIn(numbered_backup, entries)
        self.assertTrue(any(item.path == ".codex/local.json" for item in findings))
        self.assertTrue(any(item.path == ".gitignore.bak.1" for item in findings))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support is required")
    def test_generated_surface_names_are_ignored_for_any_node_type(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            shutil.copyfile(ROOT / ".gitignore", root / ".gitignore")
            target = root / "target.txt"
            target.write_text("local\n", encoding="utf-8")
            (root / ".agents").symlink_to(target)
            (root / ".claude").write_text("local\n", encoding="utf-8")
            generated = root / ".codex/local.json"
            generated.parent.mkdir()
            generated.write_text("{}\n", encoding="utf-8")

            ignored = subprocess.run(
                ["git", "-C", str(root), "check-ignore", ".agents", ".claude", ".codex/local.json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(0, ignored.returncode, ignored.stderr)
        self.assertEqual(
            {".agents", ".claude", ".codex/local.json"},
            set(ignored.stdout.splitlines()),
        )


if __name__ == "__main__":
    unittest.main()
