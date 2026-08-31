from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "skills/delivery-loop/scripts/delivery-state.py"


def initialize_repository(path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)


def run_helper(repository: Path, command: str, task: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(HELPER),
            command,
            task,
            "--repository",
            str(repository),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def load_helper():
    spec = importlib.util.spec_from_file_location("delivery_state_helper", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DeliveryStateHelperTests(unittest.TestCase):
    def test_init_creates_private_ignored_untracked_state_and_verify_accepts_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repository"
            initialize_repository(repository)

            initialized = run_helper(repository, "init", "release-readiness")
            state = repository / ".codex/delivery-state/release-readiness.md"
            verified = run_helper(repository, "verify", "release-readiness")
            ignored = subprocess.run(
                ["git", "-C", str(repository), "check-ignore", "-q", "--", str(state.relative_to(repository))],
                check=False,
            )
            tracked = subprocess.run(
                ["git", "-C", str(repository), "ls-files", "--cached", "--", str(state.relative_to(repository))],
                capture_output=True,
                text=True,
                check=True,
            )
            status = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                    "--",
                    str(state.relative_to(repository)),
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            self.assertEqual(0, initialized.returncode, initialized.stderr)
            self.assertEqual(0, verified.returncode, verified.stderr)
            self.assertEqual(0, ignored.returncode)
            self.assertEqual("", tracked.stdout)
            self.assertEqual("", status.stdout)
            self.assertEqual(0o600, stat.S_IMODE(state.stat().st_mode))
            self.assertIn("- Task: release-readiness", state.read_text(encoding="utf-8"))

    def test_helper_is_directly_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repository"
            initialize_repository(repository)

            result = subprocess.run(
                [str(HELPER), "init", "direct-execution", "--repository", str(repository)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)

    def test_init_is_idempotent_without_overwriting_existing_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repository"
            initialize_repository(repository)
            self.assertEqual(0, run_helper(repository, "init", "resume-work").returncode)
            state = repository / ".codex/delivery-state/resume-work.md"
            original = state.read_text(encoding="utf-8") + "- Local note: preserved\n"
            state.write_text(original, encoding="utf-8")
            os.chmod(state, 0o600)

            repeated = run_helper(repository, "init", "resume-work")

            self.assertEqual(0, repeated.returncode, repeated.stderr)
            self.assertEqual(original, state.read_text(encoding="utf-8"))

    def test_rejects_absolute_traversal_and_oversized_task_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repository"
            initialize_repository(repository)
            cases = ("../escape", "/tmp/escape", "a" * 65, "UPPERCASE")

            for task in cases:
                with self.subTest(task=task):
                    result = run_helper(repository, "init", task)
                    self.assertEqual(2, result.returncode)

            self.assertFalse((Path(temporary) / "escape.md").exists())

    def test_rejects_symlinked_state_parents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for symlinked_part in (".codex", "delivery-state"):
                with self.subTest(symlinked_part=symlinked_part):
                    repository = root / f"repository-{symlinked_part.replace('.', 'dot')}"
                    outside = root / f"outside-{symlinked_part.replace('.', 'dot')}"
                    initialize_repository(repository)
                    outside.mkdir()
                    if symlinked_part == ".codex":
                        (repository / ".codex").symlink_to(outside, target_is_directory=True)
                    else:
                        (repository / ".codex").mkdir()
                        (repository / ".codex/delivery-state").symlink_to(
                            outside,
                            target_is_directory=True,
                        )

                    result = run_helper(repository, "init", "safe-task")

                    self.assertEqual(2, result.returncode)
                    self.assertFalse((outside / "safe-task.md").exists())

    def test_rejects_symlink_target_without_touching_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            initialize_repository(repository)
            state_directory = repository / ".codex/delivery-state"
            state_directory.mkdir(parents=True)
            destination = root / "destination.md"
            destination.write_text("unchanged\n", encoding="utf-8")
            (state_directory / "safe-task.md").symlink_to(destination)

            result = run_helper(repository, "init", "safe-task")

            self.assertEqual(2, result.returncode)
            self.assertEqual("unchanged\n", destination.read_text(encoding="utf-8"))

    def test_rejects_tracked_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repository"
            initialize_repository(repository)
            state = repository / ".codex/delivery-state/tracked-task.md"
            state.parent.mkdir(parents=True)
            state.write_text("tracked\n", encoding="utf-8")
            os.chmod(state, 0o600)
            subprocess.run(
                ["git", "-C", str(repository), "add", "-f", str(state.relative_to(repository))],
                check=True,
            )

            result = run_helper(repository, "verify", "tracked-task")

            self.assertEqual(2, result.returncode)
            self.assertEqual("tracked\n", state.read_text(encoding="utf-8"))

    def test_init_rejects_existing_hardlinked_state_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repository"
            initialize_repository(repository)
            state = repository / ".codex/delivery-state/hardlinked-task.md"
            state.parent.mkdir(parents=True)
            original = repository / "original.md"
            original.write_text("private note\n", encoding="utf-8")
            os.chmod(original, 0o600)
            os.link(original, state)

            result = run_helper(repository, "init", "hardlinked-task")

            self.assertEqual(2, result.returncode)
            self.assertEqual("private note\n", original.read_text(encoding="utf-8"))
            self.assertEqual(2, state.stat().st_nlink)

    def test_verify_rejects_hardlink_added_after_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repository"
            initialize_repository(repository)
            self.assertEqual(0, run_helper(repository, "init", "private-task").returncode)
            state = repository / ".codex/delivery-state/private-task.md"
            leak = repository / "tracked-leak.md"
            os.link(state, leak)
            subprocess.run(["git", "-C", str(repository), "add", "tracked-leak.md"], check=True)

            result = run_helper(repository, "verify", "private-task")

            self.assertEqual(2, result.returncode)
            self.assertEqual(2, state.stat().st_nlink)

    def test_verify_rejects_state_replaced_with_hardlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repository"
            initialize_repository(repository)
            self.assertEqual(0, run_helper(repository, "init", "replace-task").returncode)
            state = repository / ".codex/delivery-state/replace-task.md"
            replacement = repository / "replacement.md"
            replacement.write_text("replacement\n", encoding="utf-8")
            os.chmod(replacement, 0o600)
            state.unlink()
            os.link(replacement, state)

            result = run_helper(repository, "verify", "replace-task")

            self.assertEqual(2, result.returncode)
            self.assertEqual(2, replacement.stat().st_nlink)

    def test_verify_rejects_live_parent_replacement_during_git_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repository"
            initialize_repository(repository)
            self.assertEqual(0, run_helper(repository, "init", "race-task").returncode)
            original_codex = repository / ".codex"
            replacement_codex = repository / "replacement-codex"
            replacement_state = replacement_codex / "delivery-state/race-task.md"
            replacement_state.parent.mkdir(parents=True)
            leak = repository / "leak.md"
            leak.write_text("leaked state\n", encoding="utf-8")
            os.chmod(leak, 0o600)
            os.link(leak, replacement_state)
            helper = load_helper()
            original_git = helper.git
            replaced = False

            def interleaving_git(
                current_repository: Path,
                *arguments: str,
                identity=None,
            ):
                nonlocal replaced
                result = original_git(current_repository, *arguments, identity=identity)
                if not replaced and arguments[:1] == ("ls-files",):
                    original_codex.rename(repository / "original-codex")
                    replacement_codex.rename(original_codex)
                    replaced = True
                return result

            helper.git = interleaving_git

            with self.assertRaises(helper.StateError):
                helper.execute(helper.arguments(["verify", "race-task", "--repository", str(repository)]))

            self.assertTrue(replaced)
            self.assertEqual(
                2,
                (repository / ".codex/delivery-state/race-task.md").stat().st_nlink,
            )

    def test_verify_rejects_unignored_or_nonprivate_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repository"
            initialize_repository(repository)
            self.assertEqual(0, run_helper(repository, "init", "private-task").returncode)
            state = repository / ".codex/delivery-state/private-task.md"
            exclude = Path(
                subprocess.run(
                    ["git", "-C", str(repository), "rev-parse", "--git-path", "info/exclude"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
            )
            if not exclude.is_absolute():
                exclude = repository / exclude
            exclude.write_text("", encoding="utf-8")

            unignored = run_helper(repository, "verify", "private-task")
            exclude.write_text(".codex/delivery-state/\n", encoding="utf-8")
            os.chmod(state, 0o644)
            public_mode = run_helper(repository, "verify", "private-task")

            self.assertEqual(2, unignored.returncode)
            self.assertEqual(2, public_mode.returncode)


if __name__ == "__main__":
    unittest.main()
