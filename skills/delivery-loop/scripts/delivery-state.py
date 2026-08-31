#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import os
from pathlib import Path
import re
import stat
import subprocess
import sys


EXIT_INVALID = 2
IGNORE_RULE = ".codex/delivery-state/"
MAX_EXCLUDE_BYTES = 1_048_576
TASK_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


class StateError(Exception):
    pass


def arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or verify private delivery-loop state."
    )
    parser.add_argument("command", choices=("init", "verify"))
    parser.add_argument("task")
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    return parser.parse_args(argv)


def git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def repository_root(candidate: Path) -> Path:
    result = git(candidate, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        raise StateError("repository is not a Git worktree")
    try:
        root = Path(result.stdout.strip()).resolve(strict=True)
    except OSError as error:
        raise StateError("repository root cannot be resolved") from error
    if not root.is_dir():
        raise StateError("repository root is not a directory")
    return root


def validate_task(task: str) -> str:
    if len(task) > 64 or not TASK_PATTERN.fullmatch(task):
        raise StateError("task must be a 1-64 character lowercase hyphenated slug")
    return task


def directory_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def open_directory(parent: int, name: str) -> int:
    try:
        os.mkdir(name, 0o700, dir_fd=parent)
    except FileExistsError:
        pass
    try:
        descriptor = os.open(name, directory_flags(), dir_fd=parent)
    except OSError as error:
        raise StateError("delivery-state parent is missing, symlinked, or not a directory") from error
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        raise StateError("delivery-state parent is not a directory")
    return descriptor


def open_state_directory(root: Path) -> tuple[int, int, int]:
    root_descriptor = os.open(root, directory_flags())
    try:
        codex_descriptor = open_directory(root_descriptor, ".codex")
        try:
            state_descriptor = open_directory(codex_descriptor, "delivery-state")
        except Exception:
            os.close(codex_descriptor)
            raise
    except Exception:
        os.close(root_descriptor)
        raise
    return root_descriptor, codex_descriptor, state_descriptor


def relative_state(task: str) -> Path:
    return Path(".codex") / "delivery-state" / f"{task}.md"


def tracked(repository: Path, relative: Path) -> bool:
    result = git(repository, "ls-files", "--cached", "--", relative.as_posix())
    if result.returncode != 0:
        raise StateError("tracked-state check failed")
    return bool(result.stdout)


def ignored(repository: Path, relative: Path) -> bool:
    result = git(repository, "check-ignore", "-q", "--", relative.as_posix())
    return result.returncode == 0


def git_exclude_path(repository: Path) -> Path:
    result = git(repository, "rev-parse", "--git-path", "info/exclude")
    if result.returncode != 0 or not result.stdout.strip():
        raise StateError("Git exclude path cannot be resolved")
    path = Path(result.stdout.strip())
    return path if path.is_absolute() else repository / path


def append_local_ignore(repository: Path) -> None:
    path = git_exclude_path(repository)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise StateError("Git exclude file is missing, symlinked, or inaccessible") from error
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_size > MAX_EXCLUDE_BYTES
        ):
            raise StateError("Git exclude file is not a safe regular file")
        content = os.read(descriptor, MAX_EXCLUDE_BYTES + 1)
        lines = content.decode("utf-8").splitlines()
        if IGNORE_RULE not in lines:
            addition = (b"" if not content or content.endswith(b"\n") else b"\n")
            addition += f"{IGNORE_RULE}\n".encode("utf-8")
            os.lseek(descriptor, 0, os.SEEK_END)
            written = os.write(descriptor, addition)
            if written != len(addition):
                raise OSError(errno.EIO, "short write")
            os.fsync(descriptor)
    except UnicodeDecodeError as error:
        raise StateError("Git exclude file is not UTF-8") from error
    finally:
        os.close(descriptor)


def ensure_ignored(repository: Path, relative: Path) -> None:
    if ignored(repository, relative):
        return
    append_local_ignore(repository)
    if not ignored(repository, relative):
        raise StateError("delivery state is not ignored")


def state_metadata(directory: int, filename: str) -> os.stat_result | None:
    try:
        return os.stat(filename, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return None


def verify_file(directory: int, filename: str) -> None:
    metadata = state_metadata(directory, filename)
    if metadata is None:
        raise StateError("delivery state does not exist")
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise StateError("delivery state is symlinked or not an owned regular file")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise StateError("delivery state mode must be 0600")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(filename, flags, dir_fd=directory)
    except OSError as error:
        raise StateError("delivery state cannot be opened safely") from error
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise StateError("delivery state changed during verification")
    finally:
        os.close(descriptor)


def verify_git_state(repository: Path, relative: Path) -> None:
    if tracked(repository, relative):
        raise StateError("delivery state must remain untracked")
    if not ignored(repository, relative):
        raise StateError("delivery state must be ignored")
    status = git(
        repository,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        relative.as_posix(),
    )
    if status.returncode != 0 or status.stdout:
        raise StateError("delivery state is visible to Git status")


def template(task: str) -> bytes:
    path = Path(__file__).resolve().parent.parent / "references/delivery-state-template.md"
    content = path.read_text(encoding="utf-8")
    return content.replace("- Task:\n", f"- Task: {task}\n", 1).encode("utf-8")


def create_file(directory: int, filename: str, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(filename, flags, 0o600, dir_fd=directory)
    except OSError as error:
        raise StateError("delivery state target already exists or is unsafe") from error
    try:
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written < 1:
                raise OSError(errno.EIO, "short write")
            offset += written
        os.fsync(descriptor)
    except Exception:
        os.close(descriptor)
        os.unlink(filename, dir_fd=directory)
        raise
    os.close(descriptor)


def execute(namespace: argparse.Namespace) -> int:
    task = validate_task(namespace.task)
    repository = repository_root(namespace.repository)
    relative = relative_state(task)
    if relative.is_absolute() or ".." in relative.parts:
        raise StateError("delivery state escaped repository containment")
    root_fd, codex_fd, state_fd = open_state_directory(repository)
    try:
        filename = relative.name
        metadata = state_metadata(state_fd, filename)
        if metadata is not None and not stat.S_ISREG(metadata.st_mode):
            raise StateError("delivery state target is symlinked or not regular")
        if tracked(repository, relative):
            raise StateError("delivery state must remain untracked")
        if namespace.command == "init":
            ensure_ignored(repository, relative)
            if metadata is None:
                create_file(state_fd, filename, template(task))
        verify_file(state_fd, filename)
        verify_git_state(repository, relative)
    finally:
        os.close(state_fd)
        os.close(codex_fd)
        os.close(root_fd)
    print(relative.as_posix())
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return execute(arguments(sys.argv[1:] if argv is None else argv))
    except (OSError, StateError, UnicodeError) as error:
        print(f"delivery state refused: {error}", file=sys.stderr)
        return EXIT_INVALID


if __name__ == "__main__":
    raise SystemExit(main())
