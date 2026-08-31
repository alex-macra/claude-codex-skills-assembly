from __future__ import annotations

import argparse
import errno
import fcntl
import os
from pathlib import Path
import stat
import subprocess
import sys


EXIT_INVALID = 2
EXIT_FORBIDDEN = 3
EXIT_CONTENDED = 4
LOCK_SIGNATURE = b"ai-skills-browser-suite\n"
MAX_LOCK_BYTES = len(LOCK_SIGNATURE) + 32


def positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("workers must be a positive integer")
    return parsed


def default_lock_file() -> Path:
    return Path("/tmp") / f"ai-skills-browser-suite-{os.getuid()}.lock"


def arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one browser suite under a nonblocking host-wide lease."
    )
    parser.add_argument("--lock-file", type=Path, default=default_lock_file())
    parser.add_argument("--workers", type=positive_integer, default=1)
    parser.add_argument(
        "--policy",
        choices=("allowed", "forbidden"),
        default="allowed",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    parsed = parser.parse_args(argv)
    if parsed.command and parsed.command[0] == "--":
        parsed.command = parsed.command[1:]
    if not parsed.command:
        parser.error("a command is required after --")
    return parsed


def open_lock(path: Path) -> int:
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        os.close(descriptor)
        raise OSError(errno.EINVAL, "lock path is not a regular file", str(path))
    if metadata.st_uid != os.getuid() or metadata.st_nlink != 1:
        os.close(descriptor)
        raise OSError(errno.EPERM, "lock file ownership is unsafe", str(path))
    existing = os.read(descriptor, MAX_LOCK_BYTES + 1)
    payload = existing.removeprefix(LOCK_SIGNATURE)
    if existing and (
        len(existing) > MAX_LOCK_BYTES
        or not existing.startswith(LOCK_SIGNATURE)
        or not payload.endswith(b"\n")
        or not payload[:-1].isdigit()
    ):
        os.close(descriptor)
        raise OSError(errno.EINVAL, "lock file is not an ai-skills lease", str(path))
    os.fchmod(descriptor, 0o600)
    return descriptor


def acquire(descriptor: int) -> bool:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    os.ftruncate(descriptor, 0)
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.write(descriptor, LOCK_SIGNATURE + f"{os.getpid()}\n".encode("ascii"))
    os.fsync(descriptor)
    return True


def run(namespace: argparse.Namespace) -> int:
    if namespace.policy == "forbidden":
        print("browser execution is forbidden by policy", file=sys.stderr)
        return EXIT_FORBIDDEN

    try:
        descriptor = open_lock(namespace.lock_file)
    except OSError as error:
        print(f"browser lease refused: {error.strerror}", file=sys.stderr)
        return EXIT_INVALID

    try:
        try:
            acquired = acquire(descriptor)
        except OSError as error:
            print(f"browser lease failed: {error.strerror}", file=sys.stderr)
            return EXIT_INVALID
        if not acquired:
            print("browser suite lease is already held", file=sys.stderr)
            return EXIT_CONTENDED

        print("browser suite lease acquired", file=sys.stderr, flush=True)
        environment = os.environ.copy()
        environment["AI_SKILLS_BROWSER_WORKERS"] = str(namespace.workers)
        try:
            completed = subprocess.run(
                namespace.command,
                env=environment,
                pass_fds=(descriptor,),
                check=False,
            )
        except FileNotFoundError:
            print("browser command was not found", file=sys.stderr)
            return 127
        except PermissionError:
            print("browser command is not executable", file=sys.stderr)
            return 126
        except OSError as error:
            print(f"browser command failed to start: {error.strerror}", file=sys.stderr)
            return 126
        return completed.returncode
    finally:
        os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    return run(arguments(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
