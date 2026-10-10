#!/usr/bin/env python3
"""Block protected-branch pushes and unsafe pull request merges.

Two advisory entry points cover the normal Claude Code, Codex, and Git paths:

  merge-guard.py                 PreToolUse hook on Bash (reads hook JSON)
  merge-guard.py --git-pre-push  git pre-push hook (reads git's stdin format)

These checks are defense in depth, not a security boundary. Disabled hooks,
alternate clients, and runtime-generated commands can bypass local tooling;
remote branch protection and restricted credentials remain authoritative.

A heredoc body is data, not shell, only when the case is unambiguous: a plain
delimiter word, no shell interpreter anywhere in the command, and, for an
unquoted delimiter, no expansion in the body. Every other heredoc is lexed as
shell, exactly as without this rule.

Rules
  R1  direct push to a protected branch
  R2  `gh pr merge` whose head is behind its base
  R3  `gh pr merge --admin`, which bypasses repository protection
  R4  direct GitHub API pull request merges

Override with AI_SKILLS_ALLOW_PROTECTED=1 in the command itself. That is a
deliberate speed bump for a human who means it, not an agent's own escape
hatch: it has to appear in the command the user can see.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from urllib.parse import quote, urlparse

PROTECTED = {
    name.strip()
    for name in os.environ.get(
        "AI_SKILLS_PROTECTED_BRANCHES", "main,master,develop"
    ).split(",")
    if name.strip()
}
OVERRIDE = "AI_SKILLS_ALLOW_PROTECTED"
TIMEOUT = 15


def _run(args: list[str], cwd: str | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(
            args, capture_output=True, text=True, timeout=TIMEOUT, cwd=cwd or None
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, NotADirectoryError) as exc:
        return 1, str(exc)
    return p.returncode, (p.stdout or p.stderr).strip()


def _deny(reason: str) -> None:
    """Emit a PreToolUse deny. Exit 0 -- the hook succeeded at saying no."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
REDIRECTION_RE = re.compile(r"^\d*(?:<>|>>?|<<?|>&|<&)")
# Programs that run another command, so what follows them is still a command.
COMMAND_WRAPPERS = {
    "builtin",
    "command",
    "doas",
    "env",
    "exec",
    "ionice",
    "nice",
    "nohup",
    "setsid",
    "stdbuf",
    "sudo",
    "time",
    "xargs",
}
SHELL_PREFIXES = {"!", "do", "elif", "if", "then", "until", "while"}
SHELL_PROGRAMS = {"ash", "bash", "dash", "ksh", "sh", "zsh"}
STDIN_INTERPRETERS = SHELL_PROGRAMS | {
    "at",
    "batch",
    "busybox",
    "csh",
    "doas",
    "fish",
    "ksh93",
    "mksh",
    "oksh",
    "pdksh",
    "posh",
    "rbash",
    "rksh",
    "rzsh",
    "ssh",
    "su",
    "sudo",
    "tcsh",
    "toybox",
    "yash",
}
HEREDOC_DELIMITER_RE = re.compile(
    r"(?:'([A-Za-z0-9_]+)'|\"([A-Za-z0-9_]+)\"|(\\?)([A-Za-z0-9_]+))(?=[ \t\n;&|()<>]|$)"
)
GLOB_CHARACTERS = "*?["
SHELL_PUNCTUATION = ";&|(){}\n"
SHELL_BOUNDARY_CHARS = frozenset(SHELL_PUNCTUATION)
MAX_SHELL_DEPTH = 32
MAX_SHELL_CHARS = 65_536
MAX_SHELL_EXPANSIONS = 256
SUBSTITUTION_PLACEHOLDER = "__ai_skills_command_substitution__"


class CommandParseError(ValueError):
    pass


def _backtick_contents(command: str, start: int) -> tuple[str, int]:
    contents: list[str] = []
    index = start + 1
    while index < len(command):
        character = command[index]
        if character == "\\" and index + 1 < len(command):
            escaped = command[index + 1]
            if escaped == "`":
                contents.append("`")
            else:
                contents.extend((character, escaped))
            index += 2
            continue
        if character == "`":
            return "".join(contents), index + 1
        contents.append(character)
        index += 1
    raise CommandParseError("unterminated backtick command substitution")


def _dollar_substitution_contents(command: str, start: int) -> tuple[str, int]:
    quotes: list[str | None] = [None]
    index = start + 2
    while index < len(command):
        character = command[index]
        quote = quotes[-1]
        if quote == "single":
            if character == "'":
                quotes[-1] = None
            index += 1
            continue
        if character == "\\":
            index += 2
            continue
        if quote == "double":
            if character == '"':
                quotes[-1] = None
                index += 1
                continue
            if character == "`":
                _, index = _backtick_contents(command, index)
                continue
            if command.startswith("$(", index):
                opened = 2 if command.startswith("$((", index) else 1
                quotes.extend([None] * opened)
                index += opened + 1
                continue
            index += 1
            continue
        if character == "'":
            quotes[-1] = "single"
            index += 1
            continue
        if character == '"':
            quotes[-1] = "double"
            index += 1
            continue
        if character == "`":
            _, index = _backtick_contents(command, index)
            continue
        if character == "(":
            quotes.append(None)
            index += 1
            continue
        if character == ")":
            quotes.pop()
            if not quotes:
                return command[start + 2:index], index + 1
        index += 1
    raise CommandParseError("unterminated command substitution")


def _mask_command_substitutions(command: str) -> tuple[str, list[str]]:
    masked: list[str] = []
    nested: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(command):
        character = command[index]
        if quote == "single":
            masked.append(character)
            if character == "'":
                quote = None
            index += 1
            continue
        if character == "\\" and index + 1 < len(command):
            masked.extend((character, command[index + 1]))
            index += 2
            continue
        if character == "'" and quote is None:
            quote = "single"
            masked.append(character)
            index += 1
            continue
        if character == '"':
            quote = None if quote == "double" else "double"
            masked.append(character)
            index += 1
            continue
        if command.startswith("$(", index) and not command.startswith("$((", index):
            contents, index = _dollar_substitution_contents(command, index)
            nested.append(contents)
            masked.append(SUBSTITUTION_PLACEHOLDER)
        elif character == "`":
            contents, index = _backtick_contents(command, index)
            nested.append(contents)
            masked.append(SUBSTITUTION_PLACEHOLDER)
        else:
            masked.append(character)
            index += 1
        if len(nested) > MAX_SHELL_EXPANSIONS:
            raise CommandParseError("too many command substitutions")
    return "".join(masked), nested


def _heredoc_body_end(
    command: str, index: int, delimiter: str, strip_tabs: bool, expands: bool
) -> int | None:
    while index < len(command):
        end = command.find("\n", index)
        line_end = len(command) if end == -1 else end
        line = command[index:line_end]
        index = min(line_end + 1, len(command))
        candidate = line.lstrip("\t") if strip_tabs else line
        if candidate == delimiter:
            return index
        if candidate.startswith(delimiter + ")"):
            return None
        if expands and (line.endswith("\\") or "$" in line or "`" in line):
            return None
    return index


def _strip_heredoc_bodies(command: str) -> str:
    if "<<" not in command:
        return command
    pieces: list[str] = []
    pending: list[tuple[str, bool, bool]] = []
    pending_depth = 0
    quotes: list[str | None] = [None]
    copied = 0
    index = 0
    while index < len(command):
        character = command[index]
        quote = quotes[-1]
        width = 1
        if character == "\\" and quote != "'":
            width = 2
        elif quote == "'":
            if character == "'":
                quotes[-1] = None
        elif character == "'" and quote is None:
            quotes[-1] = "'"
        elif character == '"':
            quotes[-1] = None if quote == '"' else '"'
        elif (
            character == "`"
            or command.startswith(("$((", "${", "$["), index)
            or (quote is None and command.startswith(("$'", '$"'), index))
        ):
            return command
        elif command.startswith("$(", index):
            quotes.append(None)
            width = 2
        elif quote is not None:
            pass
        elif character == "(":
            if command.startswith("((", index) or len(quotes) > 1:
                return command
        elif character == ")":
            if len(quotes) > 1:
                quotes.pop()
                if pending and len(quotes) < pending_depth:
                    return command
        elif character == "[":
            return command
        elif character == "#" and (index == 0 or command[index - 1] in " \t\n;&|()"):
            return command
        elif command.startswith("<<<", index):
            width = 3
        elif command.startswith("<<", index):
            cursor = index + 2
            strip_tabs = command.startswith("-", cursor)
            cursor += strip_tabs
            while cursor < len(command) and command[cursor] in " \t":
                cursor += 1
            match = HEREDOC_DELIMITER_RE.match(command, cursor)
            if match is None or (pending and pending_depth != len(quotes)):
                return command
            single, double, backslash, word = match.groups()
            quoted = bool(single or double or backslash)
            pending.append((single or double or word, strip_tabs, quoted))
            pending_depth = len(quotes)
            width = match.end() - index
        elif character == "\n" and pending:
            if len(quotes) != pending_depth:
                return command
            index += 1
            pieces.append(command[copied:index])
            for delimiter, strip_tabs, quoted in pending:
                end = _heredoc_body_end(command, index, delimiter, strip_tabs, not quoted)
                if end is None:
                    return command
                index = end
            copied = index
            pending = []
            continue
        index += width
    pieces.append(command[copied:])
    return "".join(pieces)


def _program_name(token: str) -> str:
    return token.rsplit("/", 1)[-1]


def _in_command_position(tokens: list[str], index: int) -> bool:
    """Is tokens[index] the program being run, rather than an argument?

    Matching on `tokens[0]` alone was bypassable by anything sitting in front of
    the real command -- `FOO=1 git push origin main`, `env git push ...`,
    `nice -n 10 git push ...` all walked past the check. Scanning for `git`
    anywhere fixed that but then flagged prose: `gh pr create --body "...git
    push origin main..."` reads as a push.

    So: everything before the program must be an env assignment, a wrapper, or a
    wrapper's own flag or flag value. `gh pr create --body <prose>` fails that --
    `create` is neither -- while every wrapper form above still passes.
    """
    previous_was_flag = False
    previous_was_redirection = False
    for position in range(index):
        token = tokens[position]
        name = _program_name(token)
        if previous_was_redirection:
            previous_was_redirection = False
            continue
        if ENV_ASSIGNMENT_RE.match(token) or name in COMMAND_WRAPPERS or token in SHELL_PREFIXES:
            previous_was_flag = False
            continue
        if REDIRECTION_RE.match(token):
            previous_was_redirection = token in {"<", ">", "<<", ">>"}
            previous_was_flag = False
            continue
        if token.startswith("-"):
            previous_was_flag = True
            continue
        if previous_was_flag:  # a value belonging to the flag before it
            previous_was_flag = False
            continue
        return False
    return True


def _command_slices(tokens: list[str], program: str) -> list[list[str]]:
    """Every invocation of `program` in a segment, sliced from the program on."""
    slices = []
    for index, token in enumerate(tokens):
        if _program_name(token) != program:
            continue
        if _in_command_position(tokens, index):
            slices.append(tokens[index:])
    return slices


def _command_positions(tokens: list[str], programs: set[str]) -> list[int]:
    return [
        index
        for index, token in enumerate(tokens)
        if _program_name(token) in programs and _in_command_position(tokens, index)
    ]


def _invocation_override(tokens: list[str], program_index: int, inherited: bool) -> bool:
    overridden = inherited
    for token in tokens[:program_index]:
        if not token.startswith(f"{OVERRIDE}="):
            continue
        key, value = token.split("=", 1)
        if key == OVERRIDE:
            overridden = value == "1"
    return overridden


def _shell_tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=SHELL_PUNCTUATION)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError as exc:
        raise CommandParseError(f"invalid shell syntax: {exc}") from exc


def _shell_segments(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token and all(character in SHELL_BOUNDARY_CHARS for character in token):
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _nested_shell_command(tokens: list[str], shell_index: int) -> str | None:
    option_values = {"-O", "+O", "--init-file", "--rcfile"}
    index = shell_index + 1
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return None
        if token in option_values:
            index += 2
            continue
        if token == "-c" or (
            token.startswith("-")
            and not token.startswith("--")
            and "c" in token[1:]
        ):
            return tokens[index + 1] if index + 1 < len(tokens) else None
        if token.startswith("-") or token.startswith("+"):
            index += 1
            continue
        return None
    return None


def _nested_eval_command(tokens: list[str], eval_index: int) -> str | None:
    values = tokens[eval_index + 1:]
    if values and values[0] == "--":
        values = values[1:]
    if not values:
        return None
    nested = " ".join(values)
    if SUBSTITUTION_PLACEHOLDER in nested or "$" in nested or "`" in nested:
        raise CommandParseError("eval command contains dynamic expansion")
    return nested


def _names_interpreter(token: str) -> bool:
    if "$" in token or "/proc/" in token:
        return True
    if "/" in token and any(character in token for character in GLOB_CHARACTERS):
        return True
    for piece in re.split(r"[\s=]+", token):
        if piece.startswith("-S"):
            piece = piece[2:]
        if _program_name(piece) in STDIN_INTERPRETERS:
            return True
    return False


def _runs_interpreter(segment: list[str]) -> bool:
    for index, token in enumerate(segment):
        if _names_interpreter(token):
            return True
        if not _in_command_position(segment, index):
            continue
        if token in {"eval", "source", "."}:
            return True
        if (
            SUBSTITUTION_PLACEHOLDER in token
            or "/" in token
            or any(character in token for character in GLOB_CHARACTERS)
        ):
            return True
    return False


class _Inspection:
    __slots__ = ("interpreter_seen",)

    def __init__(self) -> None:
        self.interpreter_seen = False


def _command_invocations(
    command: str,
    inherited_override: bool = False,
    depth: int = 0,
    inspection: _Inspection | None = None,
) -> list[tuple[str, list[str], bool]]:
    if depth > MAX_SHELL_DEPTH:
        raise CommandParseError("nested shell command exceeds parser depth")
    if len(command) > MAX_SHELL_CHARS:
        raise CommandParseError("nested shell command exceeds parser size")

    if inspection is None:
        stripped = _strip_heredoc_bodies(command)
        if stripped != command:
            stripped_inspection = _Inspection()
            try:
                invocations = _command_invocations(
                    stripped, inherited_override, depth, stripped_inspection
                )
                if not stripped_inspection.interpreter_seen:
                    return invocations
            except CommandParseError:
                pass
        inspection = _Inspection()

    invocations: list[tuple[str, list[str], bool]] = []
    masked, substitutions = _mask_command_substitutions(command)
    for substitution in substitutions:
        invocations.extend(
            _command_invocations(substitution, inherited_override, depth + 1, inspection)
        )
    programs = {"eval", "git", "gh"} | SHELL_PROGRAMS
    for segment in _shell_segments(_shell_tokens(masked)):
        if _runs_interpreter(segment):
            inspection.interpreter_seen = True
        for index in _command_positions(segment, programs):
            program = _program_name(segment[index])
            overridden = _invocation_override(segment, index, inherited_override)
            if program in {"git", "gh"}:
                invocations.append((program, segment[index:], overridden))
                continue
            nested = (
                _nested_eval_command(segment, index)
                if program == "eval"
                else _nested_shell_command(segment, index)
            )
            if nested is not None:
                invocations.extend(
                    _command_invocations(nested, overridden, depth + 1, inspection)
                )
    return invocations


# --------------------------------------------------------------------------
# R1: pushes


GIT_GLOBAL_OPTIONS_WITH_VALUES = {
    "-C",
    "-c",
    "--config-env",
    "--git-dir",
    "--namespace",
    "--super-prefix",
    "--work-tree",
}
PUSH_OPTIONS_WITH_VALUES = {
    "-o",
    "-r",
    "--exec",
    "--push-option",
    "--receive-pack",
    "--repo",
    "--server-option",
}
GIT_CONFIG_OPTIONS_WITH_VALUES = {
    "-f",
    "--blob",
    "--comment",
    "--default",
    "--file",
    "--type",
}
GIT_CONFIG_READ_ONLY_MODES = {
    "-e",
    "-l",
    "--edit",
    "--get",
    "--get-all",
    "--get-color",
    "--get-colorbool",
    "--get-regexp",
    "--get-urlmatch",
    "--list",
    "--name-only",
    "--show-origin",
    "--show-scope",
    "--unset",
    "--unset-all",
}


def _git_subcommand_index(tokens: list[str]) -> int | None:
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in {"-h", "--help", "--version"}:
            return None
        if token == "--":
            return index + 1 if index + 1 < len(tokens) else None
        if token in GIT_GLOBAL_OPTIONS_WITH_VALUES:
            index += 2
            continue
        if token.startswith("-C") and token != "-C":
            index += 1
            continue
        if any(token.startswith(f"{option}=") for option in GIT_GLOBAL_OPTIONS_WITH_VALUES if option.startswith("--")):
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        return index
    return None


def _git_effective_cwd(tokens: list[str], subcommand_index: int, cwd: str | None) -> str:
    base = Path(cwd or os.getcwd()).expanduser().resolve(strict=False)
    index = 1
    while index < subcommand_index:
        token = tokens[index]
        value: str | None = None
        if token == "-C" and index + 1 < subcommand_index:
            value = tokens[index + 1]
            index += 2
        elif token.startswith("-C") and token != "-C":
            value = token[2:]
            index += 1
        else:
            index += 1
        if value:
            declared = Path(value).expanduser()
            base = (
                declared if declared.is_absolute() else base / declared
            ).resolve(strict=False)
    return str(base)


def _current_branch(cwd: str | None = None) -> str:
    code, out = _run(
        ["git", "-C", cwd or ".", "symbolic-ref", "--quiet", "--short", "HEAD"]
    )
    return out.removeprefix("refs/heads/") if code == 0 else ""


def _default_remote(cwd: str | None) -> str:
    branch = _current_branch(cwd)
    keys = []
    if branch:
        keys.append(f"branch.{branch}.pushRemote")
    keys.append("remote.pushDefault")
    if branch:
        keys.append(f"branch.{branch}.remote")
    for key in keys:
        code, out = _run(["git", "-C", cwd or ".", "config", "--get", key])
        if code == 0 and out:
            return out
    return "origin"


def _remote_default_branch(remote: str | None, cwd: str | None) -> str | None:
    if not remote:
        return None
    code, out = _run(
        [
            "git",
            "-C",
            cwd or ".",
            "symbolic-ref",
            "--quiet",
            f"refs/remotes/{remote}/HEAD",
        ]
    )
    prefix = f"refs/remotes/{remote}/"
    if code == 0 and out.startswith(prefix) and len(out) > len(prefix):
        return out[len(prefix):]

    code, out = _run(
        ["git", "-C", cwd or ".", "ls-remote", "--symref", remote, "HEAD"]
    )
    if code == 0:
        for line in out.splitlines():
            match = re.fullmatch(r"ref:\s+refs/heads/(.+)\s+HEAD", line)
            if match:
                return match.group(1)
    return None


def _default_push_target(remote: str | None, cwd: str | None) -> str:
    code, out = _run(
        [
            "git",
            "-C",
            cwd or ".",
            "rev-parse",
            "--symbolic-full-name",
            "@{push}",
        ]
    )
    if code == 0 and out.startswith("refs/remotes/"):
        remainder = out.removeprefix("refs/remotes/")
        prefix = f"{remote}/" if remote else ""
        if prefix and remainder.startswith(prefix):
            return remainder[len(prefix):]
        if "/" in remainder:
            return remainder.split("/", 1)[1]
    return _current_branch(cwd)


def _push_arguments(
    tokens: list[str], subcommand_index: int, cwd: str | None
) -> tuple[str | None, list[str], str | None, bool]:
    explicit_remote: str | None = None
    positionals: list[str] = []
    broad_mode: str | None = None
    tags = False
    literal = False
    index = subcommand_index + 1
    while index < len(tokens):
        token = tokens[index]
        if literal:
            positionals.append(token)
            index += 1
            continue
        if token == "--":
            literal = True
            index += 1
            continue
        if token in {"--all", "--mirror"}:
            broad_mode = token
            index += 1
            continue
        if token == "--tags":
            tags = True
            index += 1
            continue
        if token in {"--repo", "-r"}:
            if index + 1 < len(tokens):
                explicit_remote = tokens[index + 1]
            index += 2
            continue
        if token.startswith("--repo="):
            explicit_remote = token.split("=", 1)[1]
            index += 1
            continue
        if token.startswith("-r") and token != "-r":
            explicit_remote = token[2:]
            index += 1
            continue
        if token in PUSH_OPTIONS_WITH_VALUES:
            index += 2
            continue
        if any(token.startswith(f"{option}=") for option in PUSH_OPTIONS_WITH_VALUES if option.startswith("--")):
            index += 1
            continue
        if token.startswith("-o") and token != "-o":
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        positionals.append(token)
        index += 1

    if explicit_remote is not None:
        return explicit_remote, positionals, broad_mode, tags
    if positionals:
        return positionals[0], positionals[1:], broad_mode, tags
    return _default_remote(cwd), [], broad_mode, tags


def _push_target(
    refspec: str,
    cwd: str | None,
    remote_default: str | None,
) -> str | None:
    value = refspec[1:] if refspec.startswith("+") else refspec
    if value == ":":
        return "*"
    source, separator, destination = value.partition(":")
    target = destination if separator else source
    if separator and not destination:
        return None
    if target in {"HEAD", "@"}:
        return remote_default if separator else _current_branch(cwd)
    if target == "":
        return None
    if target.startswith("refs/tags/") or (
        target.startswith("refs/") and not target.startswith("refs/heads/")
    ):
        return None
    return target.removeprefix("refs/heads/")


def _deny_broad_push(mode: str) -> None:
    _deny(
        f"Blocked: `git push {mode}` can update protected branches without "
        "naming them explicitly.\n\nPush one topic branch instead, or re-run "
        f"with {OVERRIDE}=1 prefixed if the user authorized this exact broad push."
    )


def _one_shot_alias(
    tokens: list[str], subcommand_index: int
) -> tuple[bool, str | None]:
    aliases: dict[str, str | None] = {}
    index = 1
    while index < subcommand_index:
        token = tokens[index]
        config: str | None = None
        config_environment: str | None = None
        if token == "-c" and index + 1 < subcommand_index:
            config = tokens[index + 1]
            index += 2
        elif token.startswith("-c") and token != "-c":
            config = token[2:]
            index += 1
        elif token == "--config-env" and index + 1 < subcommand_index:
            config_environment = tokens[index + 1]
            index += 2
        elif token.startswith("--config-env="):
            config_environment = token.split("=", 1)[1]
            index += 1
        else:
            index += 1
        if config is not None and "=" in config:
            key, value = config.split("=", 1)
            key = key.strip().lower()
            if key.startswith("alias.") and len(key) > len("alias."):
                aliases[key.removeprefix("alias.")] = value.strip()
        if config_environment is not None and "=" in config_environment:
            key = config_environment.split("=", 1)[0].strip().lower()
            if key.startswith("alias.") and len(key) > len("alias."):
                aliases[key.removeprefix("alias.")] = None
    name = tokens[subcommand_index].lower()
    return (name in aliases, aliases.get(name))


def _configured_alias(name: str, cwd: str | None) -> tuple[bool, str | None]:
    code, out = _run(
        ["git", "-C", cwd or ".", "config", "--get", f"alias.{name}"]
    )
    return (code == 0, out if code == 0 else None)


def _alias_for_invocation(
    tokens: list[str], subcommand_index: int, cwd: str | None
) -> tuple[bool, str | None]:
    found, value = _one_shot_alias(tokens, subcommand_index)
    if found:
        return found, value
    return _configured_alias(tokens[subcommand_index], cwd)


def _alias_definition(
    tokens: list[str], subcommand_index: int
) -> tuple[str, str] | None:
    positionals: list[str] = []
    index = subcommand_index + 1
    while index < len(tokens):
        token = tokens[index]
        if token in GIT_CONFIG_READ_ONLY_MODES:
            return None
        if token in GIT_CONFIG_OPTIONS_WITH_VALUES:
            index += 2
            continue
        if any(
            token.startswith(f"{option}=")
            for option in GIT_CONFIG_OPTIONS_WITH_VALUES
            if option.startswith("--")
        ):
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        positionals.append(token)
        index += 1
    if positionals and positionals[0] == "set":
        positionals = positionals[1:]
    if len(positionals) < 2:
        return None
    name, value = positionals[0].lower(), positionals[1]
    if not name.startswith("alias.") or len(name) == len("alias."):
        return None
    return name.removeprefix("alias."), value


def _alias_value_is_push_capable(
    value: str,
    cwd: str | None,
    depth: int = 0,
) -> bool:
    if depth >= MAX_SHELL_DEPTH or value.startswith("!"):
        return True
    try:
        expansion = shlex.split(value)
    except ValueError:
        return True
    if not expansion:
        return False
    tokens = ["git", *expansion]
    subcommand_index = _git_subcommand_index(tokens)
    if subcommand_index is None:
        return False
    if tokens[subcommand_index] == "push":
        return True
    effective_cwd = _git_effective_cwd(tokens, subcommand_index, cwd)
    found, nested = _alias_for_invocation(tokens, subcommand_index, effective_cwd)
    if not found:
        return False
    if nested is None:
        return True
    return _alias_value_is_push_capable(nested, effective_cwd, depth + 1)


def _check_alias_definition(
    tokens: list[str], subcommand_index: int, cwd: str | None
) -> None:
    definition = _alias_definition(tokens, subcommand_index)
    if definition is None:
        return
    name, value = definition
    if _alias_value_is_push_capable(value, cwd):
        _deny(
            f"Blocked: Git alias '{name}' can perform a push that bypasses "
            "protected-branch inspection. Use the underlying Git command directly."
        )


def _check_push(
    command: str,
    tokens: list[str],
    cwd: str | None,
    alias_depth: int = 0,
) -> None:
    subcommand_index = _git_subcommand_index(tokens)
    if subcommand_index is None:
        return
    effective_cwd = _git_effective_cwd(tokens, subcommand_index, cwd)
    subcommand = tokens[subcommand_index]
    if subcommand == "config":
        _check_alias_definition(tokens, subcommand_index, effective_cwd)
        return
    if subcommand != "push":
        found, alias = _alias_for_invocation(tokens, subcommand_index, effective_cwd)
        if not found:
            return
        if alias_depth >= MAX_SHELL_DEPTH:
            _deny("Blocked: Git alias expansion exceeds parser depth.")
        if alias is None:
            _deny("Blocked: a dynamic Git alias cannot be safely inspected.")
        if alias.startswith("!"):
            _deny(
                "Blocked: a shell Git alias can bypass protected-branch "
                "inspection. Use the underlying Git command directly."
            )
        try:
            expansion = shlex.split(alias)
        except ValueError:
            _deny("Blocked: could not safely inspect a Git alias.")
        if not expansion:
            return
        expanded = [
            "git",
            *tokens[1:subcommand_index],
            *expansion,
            *tokens[subcommand_index + 1:],
        ]
        _check_push(command, expanded, cwd, alias_depth + 1)
        return
    ambiguous_context = {"--git-dir", "--work-tree"}
    if any(
        token in ambiguous_context
        or any(token.startswith(f"{option}=") for option in ambiguous_context)
        for token in tokens[1:subcommand_index]
    ):
        _deny(
            "Blocked: cannot safely resolve a protected-branch push that uses "
            "--git-dir or --work-tree. Use `git -C <worktree> push`, or apply "
            f"{OVERRIDE}=1 only when the user authorized this exact push."
        )
    remote, refspecs, broad_mode, tags = _push_arguments(
        tokens, subcommand_index, effective_cwd
    )
    if broad_mode is not None:
        _deny_broad_push(broad_mode)

    remote_default = _remote_default_branch(remote, effective_cwd)
    protected = set(PROTECTED)
    if remote_default:
        protected.add(remote_default)

    targets = [
        target
        for target in (
            _push_target(refspec, effective_cwd, remote_default)
            for refspec in refspecs
        )
        if target
    ]
    if not refspecs and not tags:
        default_target = _default_push_target(remote, effective_cwd)
        if default_target:
            targets.append(default_target)

    hits = sorted(
        {
            branch
            for branch in protected
            if any(
                target == branch
                or (
                    "*" in target
                    and re.fullmatch(
                        re.escape(target).replace(r"\*", ".*"), branch
                    )
                )
                for target in targets
            )
        }
    )
    if not hits:
        return

    _deny(
        f"Blocked: direct push to protected branch '{hits[0]}'.\n\n"
        "Open a pull request instead. Only an explicit request to push directly "
        "to this exact branch authorizes an override.\n\n"
        f"If the user asked for it, re-run with {OVERRIDE}=1 prefixed."
    )


# --------------------------------------------------------------------------
# R2/R3: gh pr merge


GH_OPTIONS_WITH_VALUES = {
    "-F",
    "-R",
    "-b",
    "-s",
    "--body",
    "--body-file",
    "--hostname",
    "--match-head-commit",
    "--repo",
    "--subject",
}
GH_API_OPTIONS_WITH_VALUES = {
    "-F",
    "-H",
    "-f",
    "--cache",
    "--field",
    "--header",
    "--hostname",
    "--input",
    "--preview",
    "--raw-field",
}


def _option_value(tokens: list[str], index: int, names: set[str]) -> tuple[str | None, int]:
    token = tokens[index]
    if token in names:
        return (tokens[index + 1], 2) if index + 1 < len(tokens) else (None, 1)
    for name in names:
        if name.startswith("--") and token.startswith(f"{name}="):
            return token.split("=", 1)[1], 1
        if name.startswith("-") and not name.startswith("--") and token.startswith(name) and token != name:
            return token[len(name):], 1
    return None, 0


def _repo_selector(tokens: list[str]) -> str | None:
    selected: str | None = None
    index = 1
    while index < len(tokens):
        if tokens[index] == "--":
            break
        value, consumed = _option_value(tokens, index, {"-R", "--repo"})
        if consumed:
            if value:
                selected = value
            index += consumed
            continue
        index += 1
    return selected


def _hostname_selector(tokens: list[str]) -> str | None:
    selected: str | None = None
    index = 1
    while index < len(tokens):
        value, consumed = _option_value(tokens, index, {"--hostname"})
        if consumed:
            if value:
                selected = value
            index += consumed
            continue
        index += 1
    return selected


def _selector_hostname(selector: str | None) -> str | None:
    if not selector:
        return None
    parsed = urlparse(selector)
    if parsed.scheme and parsed.netloc:
        return parsed.netloc
    parts = [part for part in selector.split("/") if part]
    return parts[0] if len(parts) == 3 else None


def _qualified_repo(selector: str | None, hostname: str | None) -> str | None:
    if not selector or not hostname or _selector_hostname(selector):
        return selector
    return f"{hostname}/{selector}"


def _repo_from_pr_url(selector: str | None) -> str | None:
    if not selector:
        return None
    parsed = urlparse(selector)
    if not parsed.scheme or not parsed.netloc:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 4 or parts[2] != "pull" or not parts[3].isdigit():
        return None
    repository = parts[1].removesuffix(".git")
    return f"{parts[0]}/{repository}" if parts[0] and repository else None


def _gh_pr_merge_index(tokens: list[str]) -> int | None:
    index = 1
    while index < len(tokens):
        _, consumed = _option_value(tokens, index, {"-R", "--repo", "--hostname"})
        if consumed:
            index += consumed
            continue
        if tokens[index].startswith("-"):
            index += 1
            continue
        break
    if index >= len(tokens) or tokens[index] != "pr":
        return None
    index += 1
    while index < len(tokens):
        _, consumed = _option_value(tokens, index, {"-R", "--repo"})
        if consumed:
            index += consumed
            continue
        if tokens[index].startswith("-"):
            index += 1
            continue
        break
    return index if index < len(tokens) and tokens[index] == "merge" else None


def _gh_api_index(tokens: list[str]) -> int | None:
    index = 1
    while index < len(tokens):
        _, consumed = _option_value(tokens, index, {"-R", "--repo", "--hostname"})
        if consumed:
            index += consumed
            continue
        if tokens[index].startswith("-"):
            index += 1
            continue
        return index if tokens[index] == "api" else None
    return None


def _check_api_merge(tokens: list[str]) -> None:
    api_index = _gh_api_index(tokens)
    if api_index is None:
        return
    method = "GET"
    endpoint: str | None = None
    literal = False
    index = api_index + 1
    while index < len(tokens):
        token = tokens[index]
        if not literal and token == "--":
            literal = True
            index += 1
            continue
        if not literal:
            value, consumed = _option_value(tokens, index, {"-X", "--method"})
            if consumed:
                if value:
                    method = value
                index += consumed
                continue
            _, consumed = _option_value(tokens, index, GH_API_OPTIONS_WITH_VALUES)
            if consumed:
                index += consumed
                continue
            if token.startswith("-"):
                index += 1
                continue
        if endpoint is None:
            endpoint = token
        index += 1

    if endpoint is None:
        return
    if endpoint.strip("/") == "graphql" and any(
        "mergePullRequest" in token for token in tokens[api_index + 1:]
    ):
        _deny(
            "Blocked: direct pull request merge through the GitHub GraphQL API "
            "bypasses the up-to-date and authorization checks. Use `gh pr merge` "
            f"instead, or re-run with {OVERRIDE}=1 if the user authorized this exact API merge."
        )
    if method.upper() != "PUT":
        return
    parsed = urlparse(endpoint)
    path = parsed.path if parsed.scheme else endpoint.split("?", 1)[0]
    if not re.search(r"(?:^|/)repos/[^/]+/[^/]+/pulls/[0-9]+/merge/?$", path):
        return
    _deny(
        "Blocked: direct pull request merge through the GitHub API bypasses "
        "the up-to-date and authorization checks. Use `gh pr merge` instead, "
        f"or re-run with {OVERRIDE}=1 if the user authorized this exact API merge."
    )


def _merge_selector(tokens: list[str], merge_index: int) -> str | None:
    index = merge_index + 1
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return tokens[index + 1] if index + 1 < len(tokens) else None
        _, consumed = _option_value(tokens, index, GH_OPTIONS_WITH_VALUES)
        if consumed:
            index += consumed
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token
    return None


def _admin_requested(tokens: list[str], merge_index: int) -> bool:
    for token in tokens[merge_index + 1:]:
        if token == "--":
            return False
        if token == "--admin" or token.startswith("--admin="):
            return True
    return False


def _check_merge(command: str, tokens: list[str], cwd: str | None) -> None:
    merge_index = _gh_pr_merge_index(tokens)
    if merge_index is None:
        return
    if _admin_requested(tokens, merge_index):
        _deny(
            "Blocked: `gh pr merge --admin` bypasses branch protection and "
            "merges without the up-to-date check.\n\n"
            f"Drop --admin, or re-run with {OVERRIDE}=1 if the user asked for it."
        )

    selector = _merge_selector(tokens, merge_index)
    declared_repo = _repo_selector(tokens)
    repo_selector = declared_repo or _repo_from_pr_url(selector)
    hostname = (
        _hostname_selector(tokens)
        or _selector_hostname(declared_repo)
        or _selector_hostname(selector)
    )
    qualified_repo = _qualified_repo(repo_selector, hostname)
    repo_args = ["--repo", qualified_repo] if qualified_repo else []
    view = ["gh", "pr", "view"] + ([selector] if selector else []) + repo_args
    view += ["--json", "baseRefName,headRefOid,number,state"]

    code, out = _run(view, cwd)
    if code != 0:
        _deny(
            "Blocked: could not verify the PR is up to date with its base "
            f"(`gh pr view` failed: {out[:200]}).\n\n"
            "This guard fails closed -- a merge that cannot be checked is not "
            f"a merge that is safe. Re-run with {OVERRIDE}=1 to proceed anyway."
        )

    try:
        meta = json.loads(out)
        if not isinstance(meta, dict):
            raise ValueError("metadata is not an object")
        base, head, num = meta["baseRefName"], meta["headRefOid"], meta["number"]
        if not isinstance(base, str) or not base or not isinstance(head, str) or not head:
            raise ValueError("metadata fields are incomplete")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        _deny(f"Blocked: unparseable or incomplete `gh pr view` output.\n\n{out[:200]}")

    repo = _repo(cwd, repo_selector, hostname)
    if not repo:
        _deny(
            "Blocked: could not resolve the repository identity needed to "
            "verify the pull request base.\n\n"
            f"Re-run with {OVERRIDE}=1 only if the user explicitly authorized "
            "this unverifiable merge."
        )

    compare = ["gh", "api"]
    if hostname:
        compare += ["--hostname", hostname]
    compare += [
        f"repos/{repo}/compare/{quote(base, safe='')}...{quote(head, safe='')}",
        "--jq",
        ".behind_by",
    ]
    code, out = _run(compare, cwd)
    if code != 0 or not out.isdigit():
        _deny(
            f"Blocked: could not compare PR #{num} against '{base}' "
            f"({out[:200]}).\n\nThis guard fails closed. "
            f"Re-run with {OVERRIDE}=1 to proceed anyway."
        )

    behind = int(out)
    if behind:
        _deny(
            f"Blocked: PR #{num} is {behind} commit(s) behind '{base}'.\n\n"
            "Update the pull request branch before merging so the merge is "
            "based on the current target branch.\n\n"
            f"Fix: `git merge origin/{base}` into the head branch and push, "
            "then merge.\n\n"
            "The pull request can be merged after the comparison reports zero "
            "commits behind."
        )


def _repo(
    cwd: str | None,
    selected: str | None = None,
    hostname: str | None = None,
) -> str | None:
    args = ["gh", "repo", "view"]
    qualified = _qualified_repo(selected, hostname)
    if qualified:
        args.append(qualified)
    args += ["--json", "nameWithOwner", "--jq", ".nameWithOwner"]
    code, out = _run(args, cwd)
    return out if code == 0 and "/" in out else None


# --------------------------------------------------------------------------
# entry points


def run_pretooluse() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed input is not the guard's business

    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return 0

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    command = tool_input.get("command", "")
    if not isinstance(command, str) or not command:
        return 0

    raw_cwd = payload.get("cwd")
    cwd = raw_cwd if isinstance(raw_cwd, str) and raw_cwd else None

    try:
        invocations = _command_invocations(command)
    except CommandParseError as exc:
        _deny(f"Blocked: could not safely inspect nested shell command ({exc}).")

    for program, tokens, overridden in invocations:
        if overridden:
            continue
        if program == "git":
            _check_push(command, tokens, cwd)
        elif program == "gh":
            _check_merge(command, tokens, cwd)
            _check_api_merge(tokens)

    return 0


def run_git_pre_push(remote: str | None = None) -> int:
    """git pre-push: stdin is `<localref> <localsha> <remoteref> <remotesha>`."""
    if os.environ.get(OVERRIDE) == "1":
        return 0

    protected = set(PROTECTED)
    default_branch = _remote_default_branch(remote, None)
    if default_branch:
        protected.add(default_branch)

    for line in sys.stdin:
        parts = line.split()
        if len(parts) < 3:
            continue
        branch = re.sub(r"^refs/heads/", "", parts[2])
        if branch in protected:
            sys.stderr.write(
                f"\nBlocked: direct push to protected branch '{branch}'.\n"
                "Open a PR instead.\n\n"
                f"If the user asked for a direct push: {OVERRIDE}=1 git push ...\n\n"
            )
            return 1
    return 0


if __name__ == "__main__":
    if "--git-pre-push" in sys.argv:
        index = sys.argv.index("--git-pre-push")
        remote = sys.argv[index + 1] if index + 1 < len(sys.argv) else None
        sys.exit(run_git_pre_push(remote))
    sys.exit(run_pretooluse())
