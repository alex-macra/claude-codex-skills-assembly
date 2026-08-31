from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LEASE = ROOT / "skills/delivery-loop/scripts/browser-suite-lease.py"


def run_lease(*arguments: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(LEASE), *arguments],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


class BrowserSuiteLeaseTests(unittest.TestCase):
    def test_defaults_to_one_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = run_lease(
                "--lock-file",
                str(Path(temporary) / "browser.lock"),
                "--",
                sys.executable,
                "-c",
                "import os; print(os.environ['AI_SKILLS_BROWSER_WORKERS'])",
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("1", result.stdout.strip())

    def test_explicit_worker_count_is_exported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = run_lease(
                "--workers",
                "2",
                "--lock-file",
                str(Path(temporary) / "browser.lock"),
                "--",
                sys.executable,
                "-c",
                "import os; print(os.environ['AI_SKILLS_BROWSER_WORKERS'])",
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("2", result.stdout.strip())

    def test_forbidden_policy_never_starts_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "started"
            result = run_lease(
                "--policy",
                "forbidden",
                "--lock-file",
                str(Path(temporary) / "browser.lock"),
                "--",
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(marker)!r}).touch()",
            )

            self.assertFalse(marker.exists())

        self.assertEqual(3, result.returncode)
        self.assertIn("forbidden", result.stderr.lower())

    def test_contention_fails_immediately_and_does_not_run_second_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = root / "browser.lock"
            marker = root / "contender-started"
            holder = subprocess.Popen(
                [
                    sys.executable,
                    str(LEASE),
                    "--lock-file",
                    str(lock),
                    "--",
                    sys.executable,
                    "-c",
                    "import sys; sys.stdin.read(1)",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.addCleanup(self._stop, holder)
            acquired = holder.stderr.readline()
            self.assertIn("acquired", acquired.lower())

            contender = run_lease(
                "--lock-file",
                str(lock),
                "--",
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(marker)!r}).touch()",
            )

            self.assertEqual(4, contender.returncode)
            self.assertFalse(marker.exists())
            self.assertIn("already held", contender.stderr.lower())
            assert holder.stdin
            holder.stdin.write("x")
            holder.stdin.flush()
            self.assertEqual(0, holder.wait(timeout=5))

    def test_child_keeps_lease_when_wrapper_is_terminated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock = Path(temporary) / "browser.lock"
            holder = subprocess.Popen(
                [
                    sys.executable,
                    str(LEASE),
                    "--lock-file",
                    str(lock),
                    "--",
                    sys.executable,
                    "-c",
                    "import os, sys; print(os.getpid(), flush=True); sys.stdin.read(1)",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.addCleanup(self._stop, holder)
            assert holder.stderr and holder.stdout and holder.stdin
            self.assertIn("acquired", holder.stderr.readline().lower())
            child_pid = int(holder.stdout.readline())
            self.addCleanup(self._kill, child_pid)

            holder.terminate()
            holder.wait(timeout=5)
            contender = run_lease(
                "--lock-file",
                str(lock),
                "--",
                sys.executable,
                "-c",
                "print('must not run')",
            )

            self.assertEqual(4, contender.returncode)
            holder.stdin.write("x")
            holder.stdin.flush()
            deadline = time.monotonic() + 5
            while True:
                retried = run_lease(
                    "--lock-file",
                    str(lock),
                    "--",
                    sys.executable,
                    "-c",
                    "print('released')",
                )
                if retried.returncode == 0 or time.monotonic() >= deadline:
                    break
                self.assertEqual(4, retried.returncode)
                time.sleep(0.01)

            self.assertEqual(0, retried.returncode, retried.stderr)
            self.assertEqual("released", retried.stdout.strip())

    def test_releases_lease_and_propagates_command_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock = str(Path(temporary) / "browser.lock")
            failed = run_lease(
                "--lock-file",
                lock,
                "--",
                sys.executable,
                "-c",
                "raise SystemExit(7)",
            )
            retried = run_lease(
                "--lock-file",
                lock,
                "--",
                sys.executable,
                "-c",
                "print('released')",
            )
            reused = run_lease(
                "--lock-file",
                lock,
                "--",
                sys.executable,
                "-c",
                "print('reused')",
            )

        self.assertEqual(7, failed.returncode)
        self.assertEqual(0, retried.returncode, retried.stderr)
        self.assertEqual("released", retried.stdout.strip())
        self.assertEqual(0, reused.returncode, reused.stderr)
        self.assertEqual("reused", reused.stdout.strip())

    def test_refuses_symlink_lock_file(self) -> None:
        if not hasattr(os, "O_NOFOLLOW"):
            self.skipTest("O_NOFOLLOW is required")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.write_text("unchanged", encoding="utf-8")
            link = root / "browser.lock"
            link.symlink_to(target)

            result = run_lease(
                "--lock-file",
                str(link),
                "--",
                sys.executable,
                "-c",
                "print('must not run')",
            )

            self.assertEqual("unchanged", target.read_text(encoding="utf-8"))

        self.assertEqual(2, result.returncode)

    def test_refuses_non_lock_file_without_modifying_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "notes.lock"
            path.write_text("important content\n", encoding="utf-8")

            result = run_lease(
                "--lock-file",
                str(path),
                "--",
                sys.executable,
                "-c",
                "print('must not run')",
            )

            self.assertEqual("important content\n", path.read_text(encoding="utf-8"))

        self.assertEqual(2, result.returncode)
        self.assertIn("not an ai-skills lease", result.stderr.lower())

    def test_missing_command_returns_shell_not_found_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = run_lease(
                "--lock-file",
                str(Path(temporary) / "browser.lock"),
                "--",
                "browser-command-that-does-not-exist",
            )

        self.assertEqual(127, result.returncode)
        self.assertIn("not found", result.stderr.lower())

    @staticmethod
    def _stop(process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream:
                stream.close()

    @staticmethod
    def _kill(process_id: int) -> None:
        try:
            os.kill(process_id, signal.SIGKILL)
        except ProcessLookupError:
            pass


if __name__ == "__main__":
    unittest.main()
