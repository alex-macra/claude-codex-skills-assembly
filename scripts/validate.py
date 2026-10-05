#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LISTING_WARN_CHARS = 2_500
LISTING_FAIL_CHARS = 3_000
DESCRIPTION_MAX_CHARS = 250
AGENT_PRELOAD_MAX = 3
CONTRACT_SKILLS = frozenset({"delivery-loop", "fast-pr-workflow"})
MD_CAPS = {
    "skill": (60, 5_000),
    "contract-skill": (80, 7_000),
    "reference": (80, 6_000),
    "agent": (20, 2_000),
    "global-rules": (40, 4_000),
    "output-style": (20, 1_500),
    "markdown": (80, None),
}
BARE_BASH_GRANTS = {"Bash", "Bash(*)"}
DANGLING_NAME_RE = re.compile(r"`([a-z0-9]+(?:-[a-z0-9]+)*)`\s*(?i:skills?|agents?)(?![\w-])")
BACKTICKED_NAME_RE = re.compile(r"`([a-z0-9]+(?:-[a-z0-9]+)*)`")
RETIRED_NAMES = frozenset(
    {
        "a11y-audit",
        "automation",
        "code-comments",
        "code-reuse",
        "e2e-qa",
        "qa",
        "shipper",
        "web-dev-backend",
        "web-dev-frontend",
    }
)
YAML_UNCERTAIN_STARTS = tuple(">|&*!%@`{?")
YAML_COMMENT_RE = re.compile(r"(?:^|\s)#")
DENYLIST_ENV = "AI_SKILLS_DENYLIST"
REQUIRED_GLOBAL_RULES = {"claude", "codex"}
REQUIRED_HOOKS = {"activation", "mergeGuard", "usage"}
CATALOG_NAME = "ai-skills-assembly"
CATALOG_DISPLAY_NAME = "AI Skills Assembly"
ABSOLUTE_HOME_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9_.-])/(?:home|Users|var/home)/[^/\\\s\"'`]+"),
    re.compile(r"/" + r"root" + r"/[^/\\\s\"'`]+"),
    re.compile(r"(?i)(?<![A-Za-z0-9])(?:[A-Z]:[\\/])Users[\\/][^\\/\s\"'`]+"),
)
UNSUPPORTED_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
ALLOWED_FRONTMATTER = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}
EXCLUDED_PARTS = {
    ".agents",
    ".claude",
    ".codex",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}

SECRET_PATTERNS = (
    (
        "private-key",
        re.compile(rb"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY(?: BLOCK)?-----"),
    ),
    ("aws-access-key", re.compile(rb"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")),
    (
        "github-token",
        re.compile(
            rb"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{30,255}|github_pat_[A-Za-z0-9_]{40,255})"
        ),
    ),
    ("gitlab-token", re.compile(rb"(?<![A-Za-z0-9_-])glpat-[A-Za-z0-9_-]{20,}")),
    ("npm-token", re.compile(rb"(?<![A-Za-z0-9_])npm_[A-Za-z0-9]{30,}")),
    ("slack-token", re.compile(rb"(?<![A-Za-z0-9-])xox[baprs]-[A-Za-z0-9-]{20,}")),
    ("stripe-live-key", re.compile(rb"(?<![A-Za-z0-9_])sk_live_[A-Za-z0-9]{16,}")),
    ("google-api-key", re.compile(rb"(?<![A-Za-z0-9])AIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])")),
    (
        "openai-key",
        re.compile(rb"(?<![A-Za-z0-9_-])sk-(?:proj-)?[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])"),
    ),
    (
        "anthropic-key",
        re.compile(rb"(?<![A-Za-z0-9_-])sk-ant-[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])"),
    ),
    (
        "jwt",
        re.compile(
            rb"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}(?![A-Za-z0-9_-])"
        ),
    ),
    ("credential-url", re.compile(rb"https?://[^\s/:@]+:[^\s/@]+@[^\s/]+")),
)


@dataclass(frozen=True, order=True)
class Finding:
    severity: str
    check: str
    path: str
    message: str


def finding(check: str, path: Path | str, message: str, severity: str = "error") -> Finding:
    return Finding(severity, check, str(path), message)


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def git_tracked_entries(root: Path) -> list[Path] | None:
    try:
        top_level = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if top_level.returncode != 0:
        return None
    try:
        if Path(top_level.stdout.strip()).resolve() != root.resolve():
            return None
    except OSError:
        return None
    try:
        tracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if tracked.returncode != 0:
        return None

    entries: list[Path] = []
    for raw in tracked.stdout.split(b"\0"):
        if not raw:
            continue
        relative = PurePosixPath(os.fsdecode(raw))
        if relative.is_absolute() or ".." in relative.parts:
            continue
        entries.append(root.joinpath(*relative.parts))
    return entries


def repo_entries(root: Path) -> list[Path]:
    tracked = git_tracked_entries(root)
    entries: set[Path] = set(tracked or [])
    excluded = EXCLUDED_PARTS if tracked is not None else {".git"}
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name
            for name in directories
            if name not in excluded and not name.startswith(".gitignore.bak")
        )
        for name in directories + sorted(files):
            if name.startswith(".gitignore.bak"):
                continue
            path = current_path / name
            if any(part in excluded for part in path.relative_to(root).parts):
                continue
            entries.add(path)
    return sorted(entries)


def regular_files(root: Path, entries: list[Path] | None = None) -> list[Path]:
    candidates = entries if entries is not None else repo_entries(root)
    return [path for path in candidates if path.is_file() and not path.is_symlink()]


def safe_catalog_path(root: Path, raw: object) -> tuple[Path | None, str | None]:
    if not isinstance(raw, str) or not raw.strip():
        return None, "must be a non-empty relative path"
    if "\\" in raw:
        return None, "must use POSIX separators"
    pure = PurePosixPath(raw)
    if pure.is_absolute() or ".." in pure.parts:
        return None, "must stay inside the repository"
    candidate = root.joinpath(*pure.parts)
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        return None, f"does not resolve: {exc}"
    if not is_within(resolved, root.resolve()):
        return None, "resolves outside the repository"
    return resolved, None


def load_json_object(path: Path, findings: list[Finding], check: str) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        findings.append(finding(check, path, f"invalid JSON: {exc}"))
        return None
    if not isinstance(data, dict):
        findings.append(finding(check, path, "top level must be an object"))
        return None
    return data


def yaml_scalar(value: str) -> object:
    stripped = value.strip()
    if not stripped:
        return None
    if stripped[0:1] in {"\"", "'"}:
        try:
            return ast.literal_eval(stripped)
        except (SyntaxError, ValueError):
            return stripped
    return stripped


def skill_frontmatter(path: Path, findings: list[Finding]) -> dict[str, object] | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        findings.append(finding("catalog", path, f"cannot read skill: {exc}"))
        return None
    if not lines or lines[0] != "---":
        findings.append(finding("catalog", path, "missing YAML frontmatter"))
        return None
    try:
        end = lines.index("---", 1)
    except ValueError:
        findings.append(finding("catalog", path, "unterminated YAML frontmatter"))
        return None

    fields: dict[str, object] = {}
    for line_number, line in enumerate(lines[1:end], start=2):
        if not line or line[0].isspace():
            continue
        key, separator, value = line.partition(":")
        if not separator or not key.strip():
            findings.append(finding("catalog", path, f"invalid frontmatter at line {line_number}"))
            continue
        if key.strip() in fields:
            findings.append(finding("catalog", path, f"repeated frontmatter key {key.strip()!r} at line {line_number}"))
        fields[key.strip()] = yaml_scalar(value)

    unknown = sorted(set(fields) - ALLOWED_FRONTMATTER)
    if unknown:
        findings.append(finding("catalog", path, "unsupported frontmatter keys: " + ", ".join(unknown)))
    return fields


def frontmatter_block(path: Path) -> list[str] | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    if not lines or lines[0] != "---":
        return None
    try:
        end = lines.index("---", 1)
    except ValueError:
        return None
    return lines[1:end]


def split_grants(value: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    depth = 0
    for character in value:
        if character == "(":
            depth += 1
        elif character == ")" and depth:
            depth -= 1
        if depth == 0 and (character == "," or character.isspace()):
            if current:
                items.append("".join(current))
                current = []
            continue
        current.append(character)
    if current:
        items.append("".join(current))
    return [item.strip("\"'") for item in items if item.strip("\"'")]


def frontmatter_key_line(block: list[str], key: str) -> int | None:
    for index, line in enumerate(block):
        if line[:1].isspace():
            continue
        name, separator, _ = line.partition(":")
        if separator and name.strip() == key:
            return index
    return None


def frontmatter_items(block: list[str], key: str) -> list[str]:
    index = frontmatter_key_line(block, key)
    if index is None:
        return []
    value = block[index].partition(":")[2].strip()
    if value.startswith("[") and value.endswith("]"):
        return split_grants(value[1:-1])
    if value:
        return split_grants(value)
    items: list[str] = []
    for line in block[index + 1 :]:
        if line and not line[0].isspace():
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip().strip("\"'"))
    return items


def strip_yaml_comment(value: str) -> str:
    match = YAML_COMMENT_RE.search(value)
    return value[: match.start()] if match else value


def top_level_key(line: str) -> str | None:
    if not line or line[0].isspace() or line.startswith(("#", "-")):
        return None
    name, separator, _ = line.partition(":")
    return name.strip() if separator else None


def allowed_tools(block: list[str]) -> tuple[list[str], str | None]:
    indexes = [index for index, line in enumerate(block) if top_level_key(line) == "allowed-tools"]
    if not indexes:
        return [], None
    if len(indexes) > 1:
        return [], "allowed-tools is repeated"
    value = strip_yaml_comment(block[indexes[0]].partition(":")[2]).strip()
    continuation: list[str] = []
    for line in block[indexes[0] + 1 :]:
        stripped = strip_yaml_comment(line).strip()
        if not stripped:
            continue
        if not line[0].isspace() and not line.startswith("-"):
            break
        continuation.append(stripped)
    if "\\" in value + "".join(continuation) and "\"" in value + "".join(continuation):
        return [], "allowed-tools has an escaped double-quoted value"
    if value:
        if continuation:
            return [], "allowed-tools spans several lines"
        if value.startswith("["):
            inner = value[1:-1]
            if not value.endswith("]") or "[" in inner or "]" in inner:
                return [], "allowed-tools has a flow list that does not close on its line"
            return split_grants(inner), None
        if value.startswith(YAML_UNCERTAIN_STARTS):
            return [], f"allowed-tools starts with {value[0]!r}, which this check cannot read"
        return split_grants(value), None
    items: list[str] = []
    for entry in continuation:
        item = entry[2:].strip() if entry.startswith("- ") else ""
        if not item or item.startswith(YAML_UNCERTAIN_STARTS + ("[", "-")):
            return [], "allowed-tools has a line this check cannot read"
        items.append(item.strip("\"'"))
    return items, None


def frontmatter_text(block: list[str], key: str) -> str | None:
    index = frontmatter_key_line(block, key)
    if index is None:
        return None
    value = block[index].partition(":")[2].strip()
    if value not in {">", ">-", "|", "|-"}:
        scalar = yaml_scalar(value)
        return scalar if isinstance(scalar, str) else None
    folded: list[str] = []
    for line in block[index + 1 :]:
        if line and not line[0].isspace():
            break
        folded.append(line.strip())
    return " ".join(part for part in folded if part)


def agent_declared_skills(path: Path) -> list[str]:
    block = frontmatter_block(path)
    return frontmatter_items(block, "skills") if block is not None else []


def check_python(root: Path, files: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in files:
        if path.suffix != ".py":
            continue
        try:
            compile(path.read_bytes(), str(path), "exec", dont_inherit=True)
        except (OSError, SyntaxError, ValueError) as exc:
            line = getattr(exc, "lineno", None)
            suffix = f" at line {line}" if line else ""
            findings.append(finding("python", path.relative_to(root), f"does not compile{suffix}: {exc}"))
    return findings


def check_symlinks(root: Path, entries: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    resolved_root = root.resolve()
    for path in entries:
        if not path.is_symlink():
            continue
        relative = path.relative_to(root)
        try:
            target = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            findings.append(finding("symlink", relative, f"broken or cyclic symlink: {exc}"))
            continue
        if not is_within(target, resolved_root):
            findings.append(finding("symlink", relative, "target escapes the repository"))
    return findings


def validate_named_paths(
    root: Path,
    section_name: str,
    section: object,
    findings: list[Finding],
) -> set[str]:
    if not isinstance(section, dict):
        findings.append(finding("catalog", "catalog.json", f"{section_name} must be an object"))
        return set()
    names: set[str] = set()
    for name, entry in section.items():
        if not isinstance(name, str) or not SKILL_NAME_RE.fullmatch(name):
            findings.append(finding("catalog", "catalog.json", f"invalid {section_name} key: {name!r}"))
            continue
        if not isinstance(entry, dict):
            findings.append(finding("catalog", "catalog.json", f"{section_name}.{name} must be an object"))
            continue
        path, error = safe_catalog_path(root, entry.get("path"))
        if error:
            findings.append(finding("catalog", "catalog.json", f"{section_name}.{name}.path {error}"))
            continue
        if path is None or not path.is_file():
            findings.append(finding("catalog", "catalog.json", f"{section_name}.{name}.path must be a file"))
            continue
        if path.stem != name:
            findings.append(finding("catalog", "catalog.json", f"{section_name}.{name}.path filename must match its key"))
            continue
        names.add(name)
    return names


def validate_path_map(
    root: Path,
    section_name: str,
    section: object,
    findings: list[Finding],
    required: set[str],
) -> set[Path]:
    if not isinstance(section, dict) or not section:
        findings.append(finding("catalog", "catalog.json", f"{section_name} must be a non-empty object"))
        return set()
    missing = sorted(required - set(section))
    if missing:
        findings.append(
            finding(
                "catalog",
                "catalog.json",
                f"{section_name} is missing required keys: {', '.join(missing)}",
            )
        )
    paths: set[Path] = set()
    for name, raw_path in section.items():
        if not isinstance(raw_path, str):
            findings.append(
                finding(
                    "catalog",
                    "catalog.json",
                    f"{section_name}.{name} must be a string path",
                )
            )
            continue
        path, error = safe_catalog_path(root, raw_path)
        if error:
            findings.append(finding("catalog", "catalog.json", f"{section_name}.{name} {error}"))
            continue
        if path is None or not path.is_file():
            findings.append(finding("catalog", "catalog.json", f"{section_name}.{name} must point to a file"))
            continue
        if path in paths:
            findings.append(finding("catalog", "catalog.json", f"{section_name} contains duplicate paths"))
            continue
        paths.add(path)
    return paths


def validate_profiles(
    profiles: object,
    catalog_names: set[str],
    agent_names: set[str],
    output_style_names: set[str],
    findings: list[Finding],
) -> set[str]:
    if not isinstance(profiles, dict):
        findings.append(finding("catalog", "catalog.json", "profiles must be an object"))
        return set()
    if "default" not in profiles:
        findings.append(finding("catalog", "catalog.json", "profiles.default must be an object"))

    default_skills: set[str] = set()
    for profile_name, profile in profiles.items():
        if not isinstance(profile_name, str) or not SKILL_NAME_RE.fullmatch(profile_name):
            findings.append(finding("catalog", "catalog.json", f"invalid profile key: {profile_name!r}"))
        if not isinstance(profile, dict):
            findings.append(finding("catalog", "catalog.json", f"profiles.{profile_name} must be an object"))
            continue

        for field, available in (
            ("skills", catalog_names),
            ("agents", agent_names),
            ("outputStyles", output_style_names),
        ):
            values = profile.get(field, [])
            if not string_list(values):
                findings.append(
                    finding(
                        "catalog",
                        "catalog.json",
                        f"profiles.{profile_name}.{field} must be an array of names",
                    )
                )
                continue
            if len(values) != len(set(values)):
                findings.append(
                    finding(
                        "catalog",
                        "catalog.json",
                        f"profiles.{profile_name}.{field} contains duplicates",
                    )
                )
            invalid = sorted(value for value in values if not SKILL_NAME_RE.fullmatch(value))
            if invalid:
                findings.append(
                    finding(
                        "catalog",
                        "catalog.json",
                        f"profiles.{profile_name}.{field} contains invalid names: {', '.join(invalid)}",
                    )
                )
            unknown = sorted(set(values) - available)
            if unknown:
                findings.append(
                    finding(
                        "catalog",
                        "catalog.json",
                        f"profiles.{profile_name}.{field} references unknown names: {', '.join(unknown)}",
                    )
                )
            if profile_name == "default" and field == "skills":
                default_skills = set(values)

    missing_default = sorted(catalog_names - default_skills)
    if missing_default:
        findings.append(
            finding(
                "catalog",
                "catalog.json",
                "default profile omits public skills: " + ", ".join(missing_default),
            )
        )
    return default_skills


def validate_catalog(root: Path) -> tuple[list[Finding], dict[str, str], set[str], Path | None, Path | None]:
    findings: list[Finding] = []
    descriptions: dict[str, str] = {}
    catalog_path = root / "catalog.json"
    data = load_json_object(catalog_path, findings, "catalog")
    if data is None:
        return findings, descriptions, set(), None, None
    if data.get("schemaVersion") != 1:
        findings.append(finding("catalog", "catalog.json", "schemaVersion must be 1"))
    catalog_name = data.get("name")
    if not isinstance(catalog_name, str):
        findings.append(finding("catalog", "catalog.json", "name must be a string"))
    elif catalog_name != CATALOG_NAME:
        findings.append(
            finding("catalog", "catalog.json", f"name must be {CATALOG_NAME!r}")
        )
    display_name = data.get("displayName")
    if not isinstance(display_name, str):
        findings.append(finding("catalog", "catalog.json", "displayName must be a string"))
    elif display_name != CATALOG_DISPLAY_NAME:
        findings.append(
            finding(
                "catalog",
                "catalog.json",
                f"displayName must be {CATALOG_DISPLAY_NAME!r}",
            )
        )

    surfaces = data.get("surfaces")
    if not isinstance(surfaces, dict) or not surfaces:
        findings.append(finding("catalog", "catalog.json", "surfaces must be a non-empty object"))
    else:
        for name, values in surfaces.items():
            if not string_list(values) or not values:
                findings.append(finding("catalog", "catalog.json", f"surfaces.{name} must be a non-empty array"))
            elif len(values) != len(set(values)):
                findings.append(finding("catalog", "catalog.json", f"surfaces.{name} contains duplicates"))

    skills = data.get("skills")
    catalog_names: set[str] = set()
    catalog_paths: set[Path] = set()
    if not isinstance(skills, dict) or not skills:
        findings.append(finding("catalog", "catalog.json", "skills must be a non-empty object"))
    else:
        for name, entry in skills.items():
            if not isinstance(name, str) or not SKILL_NAME_RE.fullmatch(name):
                findings.append(finding("catalog", "catalog.json", f"invalid skill key: {name!r}"))
                continue
            if not isinstance(entry, dict):
                findings.append(finding("catalog", "catalog.json", f"skills.{name} must be an object"))
                continue
            skill_dir, error = safe_catalog_path(root, entry.get("path"))
            if error:
                findings.append(finding("catalog", "catalog.json", f"skills.{name}.path {error}"))
                continue
            if skill_dir is None or not skill_dir.is_dir():
                findings.append(finding("catalog", "catalog.json", f"skills.{name}.path must be a directory"))
                continue
            expected_dir = (root / "skills" / name).resolve(strict=False)
            if skill_dir != expected_dir:
                findings.append(
                    finding(
                        "catalog",
                        "catalog.json",
                        f"skills.{name}.path must be skills/{name}",
                    )
                )
            if skill_dir in catalog_paths:
                findings.append(finding("catalog", "catalog.json", f"duplicate skill path: {entry.get('path')}"))
                continue
            catalog_paths.add(skill_dir)
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.is_file():
                findings.append(finding("catalog", skill_dir.relative_to(root), "missing SKILL.md"))
                continue
            fields = skill_frontmatter(skill_md, findings)
            if fields is None:
                continue
            if fields.get("name") != name:
                findings.append(finding("catalog", skill_md.relative_to(root), "frontmatter name must match catalog key"))
            description = fields.get("description")
            if not isinstance(description, str) or not 1 <= len(description) <= DESCRIPTION_MAX_CHARS:
                findings.append(
                    finding(
                        "catalog",
                        skill_md.relative_to(root),
                        f"description must be 1-{DESCRIPTION_MAX_CHARS} characters",
                    )
                )
            else:
                descriptions[name] = description
                declared = entry.get("description")
                if declared is not None and declared != description:
                    findings.append(finding("catalog", "catalog.json", f"skills.{name}.description differs from SKILL.md"))
            if fields.get("license") != "MIT":
                findings.append(finding("catalog", skill_md.relative_to(root), "license must be MIT"))
            catalog_names.add(name)

    skills_root = root / "skills"
    if not skills_root.is_dir():
        findings.append(finding("catalog", "skills", "skills directory is missing"))
    else:
        disk_names = {
            child.name
            for child in skills_root.iterdir()
            if child.is_dir()
        }
        missing = sorted(disk_names - catalog_names)
        if missing:
            findings.append(finding("catalog", "catalog.json", "uncataloged skill directories: " + ", ".join(missing)))

    agents = validate_named_paths(root, "agents", data.get("agents"), findings)
    agents_root = root / "agents"
    if agents_root.is_dir():
        disk_agents = {path.stem for path in agents_root.glob("*.md") if path.is_file()}
        missing_agents = sorted(disk_agents - agents)
        if missing_agents:
            findings.append(finding("catalog", "catalog.json", "uncataloged agents: " + ", ".join(missing_agents)))
    for name in sorted(agents):
        entry = (data.get("agents") or {}).get(name)
        agent_path, error = safe_catalog_path(root, entry.get("path") if isinstance(entry, dict) else None)
        if error or agent_path is None:
            continue
        relative_agent = agent_path.relative_to(root)
        declared = agent_declared_skills(agent_path)
        unknown = sorted(set(declared) - catalog_names)
        if unknown:
            findings.append(
                finding(
                    "catalog",
                    relative_agent,
                    "agent skills reference unknown catalog skills: " + ", ".join(unknown),
                )
            )
        if len(declared) > AGENT_PRELOAD_MAX:
            findings.append(
                finding(
                    "catalog",
                    relative_agent,
                    f"agent preloads {len(declared)} skills; maximum is {AGENT_PRELOAD_MAX}",
                )
            )
        block = frontmatter_block(agent_path)
        agent_description = frontmatter_text(block, "description") if block is not None else None
        if not agent_description or len(agent_description) > DESCRIPTION_MAX_CHARS:
            findings.append(
                finding(
                    "catalog",
                    relative_agent,
                    f"agent description must be 1-{DESCRIPTION_MAX_CHARS} characters",
                )
            )

    output_styles = validate_named_paths(root, "outputStyles", data.get("outputStyles"), findings)
    output_styles_root = root / "templates" / "output-styles"
    if output_styles_root.is_dir():
        disk_output_styles = {path.stem for path in output_styles_root.glob("*.md") if path.is_file()}
        missing_output_styles = sorted(disk_output_styles - output_styles)
        if missing_output_styles:
            findings.append(
                finding(
                    "catalog",
                    "catalog.json",
                    "uncataloged output styles: " + ", ".join(missing_output_styles),
                )
            )

    default_skills = validate_profiles(data.get("profiles"), catalog_names, agents, output_styles, findings)

    validate_path_map(
        root,
        "globalRules",
        data.get("globalRules"),
        findings,
        REQUIRED_GLOBAL_RULES,
    )
    validate_path_map(root, "hooks", data.get("hooks"), findings, REQUIRED_HOOKS)

    routing = data.get("routing")
    registry_path: Path | None = None
    fixtures_path: Path | None = None
    if not isinstance(routing, dict):
        findings.append(finding("catalog", "catalog.json", "routing must be an object"))
    else:
        registry_path, error = safe_catalog_path(root, routing.get("registry"))
        if error:
            findings.append(finding("catalog", "catalog.json", f"routing.registry {error}"))
            registry_path = None
        fixtures_path, error = safe_catalog_path(root, routing.get("fixtures"))
        if error:
            findings.append(finding("catalog", "catalog.json", f"routing.fixtures {error}"))
            fixtures_path = None

    return findings, descriptions, default_skills, registry_path, fixtures_path


def load_activation_hook(root: Path, findings: list[Finding]):
    path = root / "hooks" / "skill-activation.py"
    if not path.is_file():
        findings.append(finding("routing", path.relative_to(root), "activation hook is missing"))
        return None
    spec = importlib.util.spec_from_file_location("public_skill_activation", path)
    if spec is None or spec.loader is None:
        findings.append(finding("routing", path.relative_to(root), "activation hook cannot be imported"))
        return None
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:
        findings.append(finding("routing", path.relative_to(root), f"activation hook import failed: {exc}"))
        return None
    if not callable(getattr(module, "select", None)):
        findings.append(finding("routing", path.relative_to(root), "activation hook must expose select"))
        return None
    return module


def string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def validate_routing(
    root: Path,
    catalog_names: set[str],
    registry_path: Path | None,
    fixtures_path: Path | None,
) -> list[Finding]:
    findings: list[Finding] = []
    if registry_path is None or fixtures_path is None:
        return findings
    registry = load_json_object(registry_path, findings, "routing")
    fixtures = load_json_object(fixtures_path, findings, "routing")
    if registry is None or fixtures is None:
        return findings
    entries = registry.get("skills")
    if not isinstance(entries, dict) or not entries:
        findings.append(finding("routing", registry_path.relative_to(root), "skills must be a non-empty object"))
        return findings
    hook = load_activation_hook(root, findings)
    regex_safety = getattr(hook, "is_safe_intent_pattern", None) if hook is not None else None
    if hook is not None and not callable(regex_safety):
        findings.append(
            finding(
                "routing",
                Path("hooks/skill-activation.py"),
                "activation hook must expose is_safe_intent_pattern",
            )
        )
    missing_routes = sorted(catalog_names - set(entries))
    if missing_routes:
        findings.append(
            finding(
                "routing",
                registry_path.relative_to(root),
                "catalog skills lack routing rules: " + ", ".join(missing_routes),
            )
        )
    for name, config in entries.items():
        if name not in catalog_names:
            findings.append(finding("routing", registry_path.relative_to(root), f"unknown routed skill: {name}"))
        if not isinstance(config, dict):
            findings.append(finding("routing", registry_path.relative_to(root), f"skill {name} config must be an object"))
            continue
        if config.get("priority", "medium") not in {"high", "medium", "low"}:
            findings.append(finding("routing", registry_path.relative_to(root), f"skill {name} has invalid priority"))
        prompt = config.get("promptTriggers", {})
        files = config.get("fileTriggers", {})
        if (
            not isinstance(prompt, dict)
            or not string_list(prompt.get("keywords", []))
            or not string_list(prompt.get("intentPatterns", []))
            or not string_list(prompt.get("excludePatterns", []))
        ):
            findings.append(finding("routing", registry_path.relative_to(root), f"skill {name} has invalid prompt triggers"))
        else:
            pattern_groups = (
                ("intent", prompt.get("intentPatterns", [])),
                ("exclusion", prompt.get("excludePatterns", [])),
            )
            for pattern_kind, patterns in pattern_groups:
                for pattern in patterns:
                    try:
                        re.compile(pattern, re.IGNORECASE)
                    except re.error as exc:
                        findings.append(
                            finding(
                                "routing",
                                registry_path.relative_to(root),
                                f"skill {name} has invalid {pattern_kind} regex: {exc}",
                            )
                        )
                        continue
                    if callable(regex_safety) and not regex_safety(pattern):
                        findings.append(
                            finding(
                                "routing",
                                registry_path.relative_to(root),
                                f"skill {name} has unsafe {pattern_kind} regex",
                            )
                        )
        if not isinstance(files, dict) or not string_list(files.get("pathPatterns", [])) or not string_list(
            files.get("pathExclusions", [])
        ):
            findings.append(finding("routing", registry_path.relative_to(root), f"skill {name} has invalid file triggers"))

    positive = fixtures.get("positive")
    negative = fixtures.get("negative")
    if not isinstance(positive, dict) or not positive:
        findings.append(finding("routing", fixtures_path.relative_to(root), "positive must be a non-empty object"))
        return findings
    if not string_list(negative):
        findings.append(finding("routing", fixtures_path.relative_to(root), "negative must be an array of prompts"))
        return findings
    if hook is None:
        return findings

    covered: set[str] = set()
    for prompt, expectation in positive.items():
        if not isinstance(prompt, str):
            findings.append(finding("routing", fixtures_path.relative_to(root), "positive prompt keys must be strings"))
            continue
        available: set[str] | None = set(catalog_names)
        if string_list(expectation):
            expected = set(expectation)
        elif isinstance(expectation, dict) and string_list(expectation.get("expect")):
            expected = set(expectation["expect"])
            declared_available = expectation.get("available", [])
            if not string_list(declared_available):
                findings.append(finding("routing", fixtures_path.relative_to(root), f"fixture for {prompt!r} has invalid available list"))
                continue
            available = set(declared_available) | expected
        else:
            findings.append(finding("routing", fixtures_path.relative_to(root), f"fixture for {prompt!r} is invalid"))
            continue
        unknown = sorted(expected - set(entries))
        if unknown:
            findings.append(finding("routing", fixtures_path.relative_to(root), f"fixture for {prompt!r} expects unknown skills"))
            continue
        actual = set(hook.select(prompt, entries, available))
        if actual != expected:
            findings.append(
                finding(
                    "routing",
                    fixtures_path.relative_to(root),
                    f"fixture mismatch for {prompt!r}: expected {sorted(expected)}, got {sorted(actual)}",
                )
            )
        covered |= expected

    for prompt in negative:
        actual = hook.select(prompt, entries, None)
        if actual:
            findings.append(
                finding(
                    "routing",
                    fixtures_path.relative_to(root),
                    f"negative fixture {prompt!r} matched {sorted(actual)}",
                )
            )
    uncovered = sorted(set(entries) - covered)
    if uncovered:
        findings.append(finding("routing", fixtures_path.relative_to(root), "routed skills lack positive fixtures: " + ", ".join(uncovered)))
    return findings


def check_template_parity(root: Path) -> list[Finding]:
    claude_path = root / "templates" / "CLAUDE.md"
    codex_path = root / "templates" / "AGENTS.md"
    try:
        claude_text = claude_path.read_text(encoding="utf-8")
        codex_text = codex_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [finding("catalog", "templates", f"cannot read global rule templates: {exc}")]
    if claude_text != codex_text:
        return [
            finding(
                "catalog",
                "templates",
                "templates/CLAUDE.md and templates/AGENTS.md must stay identical",
            )
        ]
    return []


def check_listing(descriptions: dict[str, str], profile: set[str], label: str = "default profile") -> list[Finding]:
    total = sum(len(name) + len(descriptions.get(name, "")) for name in profile)
    if total > LISTING_FAIL_CHARS:
        return [finding("listing", "catalog.json", f"{label} costs {total} characters; maximum is {LISTING_FAIL_CHARS}")]
    if total > LISTING_WARN_CHARS:
        return [
            finding(
                "listing",
                "catalog.json",
                f"{label} costs {total} characters; warning threshold is {LISTING_WARN_CHARS}",
                severity="warning",
            )
        ]
    return []


def check_plain_hyphens(root: Path, entries: list[Path], files: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    forbidden = ("\u2013", "\u2014")
    for path in entries:
        relative = path.relative_to(root)
        if any(character in relative.as_posix() for character in forbidden):
            findings.append(finding("hyphens", relative, "non-ASCII dash in path"))
    for path in files:
        relative = path.relative_to(root)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if any(character in line for character in forbidden):
                findings.append(finding("hyphens", relative, f"non-ASCII dash at line {line_number}"))
    return findings


def check_privacy(root: Path, entries: list[Path], files: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in entries:
        relative = path.relative_to(root)
        if any(pattern.search(relative.as_posix()) for pattern in ABSOLUTE_HOME_PATTERNS):
            findings.append(finding("privacy", relative, "absolute home path in repository path"))
    for path in files:
        relative = path.relative_to(root)
        try:
            data = path.read_bytes()
        except OSError as exc:
            findings.append(finding("privacy", relative, f"cannot read file: {exc}"))
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            findings.append(finding("privacy", relative, "unsupported non-UTF-8 artifact"))
            continue
        control = UNSUPPORTED_CONTROL_RE.search(text)
        if control is not None:
            line_number = text.count("\n", 0, control.start()) + 1
            findings.append(
                finding(
                    "privacy",
                    relative,
                    f"unsupported binary control character at line {line_number}",
                )
            )
            continue
        lines = text.splitlines()
        for line_number, line in enumerate(lines, start=1):
            if any(pattern.search(line) for pattern in ABSOLUTE_HOME_PATTERNS):
                findings.append(finding("privacy", relative, f"absolute home path at line {line_number}"))
    return findings


def sensitive_filename(path: Path) -> bool:
    name = path.name.lower()
    if name.startswith(".env") and name not in {".env.example", ".env.sample", ".env.template"}:
        return True
    if name in {".netrc", ".npmrc", "credentials.json", "id_dsa", "id_ecdsa", "id_ed25519", "id_rsa"}:
        return True
    return path.suffix.lower() in {".jks", ".key", ".keystore", ".p12", ".pem", ".pfx"}


def check_secrets(root: Path, entries: list[Path], files: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in entries:
        relative = path.relative_to(root)
        if sensitive_filename(relative):
            findings.append(finding("secrets", relative, "sensitive credential filename is not allowed"))
    for path in files:
        relative = path.relative_to(root)
        try:
            data = path.read_bytes()
        except OSError as exc:
            findings.append(finding("secrets", relative, f"cannot read file: {exc}"))
            continue
        for label, pattern in SECRET_PATTERNS:
            match = pattern.search(data)
            if match is None:
                continue
            line_number = data.count(b"\n", 0, match.start()) + 1
            findings.append(finding("secrets", relative, f"possible {label} at line {line_number}"))
    return findings


@dataclass(frozen=True)
class CapRow:
    path: str
    lines: int
    size: int
    max_lines: int
    max_bytes: int | None

    @property
    def within(self) -> bool:
        return self.lines <= self.max_lines and (self.max_bytes is None or self.size <= self.max_bytes)


def md_cap_kind(relative: PurePosixPath, contract_skills: frozenset[str] = CONTRACT_SKILLS) -> str | None:
    if relative.suffix != ".md":
        return None
    parts = relative.parts
    if len(parts) == 3 and parts[0] == "skills" and parts[2] == "SKILL.md":
        return "contract-skill" if parts[1] in contract_skills else "skill"
    if len(parts) == 4 and parts[0] == "skills" and parts[2] == "references":
        return "reference"
    if len(parts) == 2 and parts[0] == "agents":
        return "agent"
    if relative.as_posix() in {"templates/CLAUDE.md", "templates/AGENTS.md"}:
        return "global-rules"
    if len(parts) == 3 and parts[:2] == ("templates", "output-styles"):
        return "output-style"
    return "markdown"


def nested_reference(relative: PurePosixPath) -> bool:
    parts = relative.parts
    return len(parts) > 4 and parts[0] == "skills" and parts[2] == "references"


def cap_row(path: Path, relative: PurePosixPath, kind: str) -> CapRow | None:
    try:
        data = path.read_bytes()
        text = data.decode("utf-8")
    except (OSError, UnicodeError):
        return None
    max_lines, max_bytes = MD_CAPS[kind]
    return CapRow(relative.as_posix(), len(text.splitlines()), len(data), max_lines, max_bytes)


def md_cap_rows(root: Path, files: list[Path]) -> list[CapRow]:
    rows: list[CapRow] = []
    for path in files:
        relative = PurePosixPath(path.relative_to(root).as_posix())
        kind = md_cap_kind(relative)
        if kind is None:
            continue
        row = cap_row(path, relative, kind)
        if row is not None:
            rows.append(row)
    return rows


def cap_message(row: CapRow) -> str:
    cap = f"{row.max_lines} lines" + (f" and {row.max_bytes} bytes" if row.max_bytes is not None else "")
    return f"{row.lines} lines and {row.size} bytes exceed the cap of {cap}"


def check_md_caps(root: Path, entries: list[Path], files: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in entries:
        relative = PurePosixPath(path.relative_to(root).as_posix())
        if path.is_file() and nested_reference(relative):
            findings.append(finding("caps", relative, "references must be one level deep"))
        if path.is_symlink() and md_cap_kind(relative) not in {None, "markdown"}:
            findings.append(finding("caps", relative, "must be a regular file, not a symlink"))
    for row in md_cap_rows(root, files):
        if not row.within:
            findings.append(finding("caps", row.path, cap_message(row)))
    return findings


def bash_grant_problems(skill_md: Path) -> list[str]:
    block = frontmatter_block(skill_md)
    if block is None:
        return []
    grants, problem = allowed_tools(block)
    if problem is not None:
        return [problem]
    return [
        f"allowed-tools grants unscoped {grant}"
        for grant in grants
        if "".join(grant.split()) in BARE_BASH_GRANTS
    ]


def check_no_bare_bash(root: Path, files: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in files:
        parts = path.relative_to(root).parts
        if len(parts) != 3 or parts[0] != "skills" or parts[2] != "SKILL.md":
            continue
        for problem in bash_grant_problems(path):
            findings.append(finding("permissions", path.relative_to(root), problem))
    return findings


def declared_names(root: Path) -> set[str]:
    try:
        data = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return set()
    names: set[str] = set()
    for section in ("skills", "agents"):
        values = data.get(section) if isinstance(data, dict) else None
        if isinstance(values, dict):
            names.update(name for name in values if isinstance(name, str))
    return names


def dangling_names(text: str, known: set[str]) -> list[tuple[int, str]]:
    found = {
        (text.count("\n", 0, match.start()) + 1, match.group(1))
        for match in DANGLING_NAME_RE.finditer(text)
        if match.group(1) not in known
    }
    found.update(
        (text.count("\n", 0, match.start()) + 1, match.group(1))
        for match in BACKTICKED_NAME_RE.finditer(text)
        if match.group(1) in RETIRED_NAMES and match.group(1) not in known
    )
    return sorted(found)


def names_prose(relative: PurePosixPath) -> bool:
    if relative.suffix != ".md":
        return False
    if relative.parts[0] in {"skills", "agents", "templates"}:
        return True
    return relative.as_posix() in {"README.md", "CONTRIBUTING.md"}


def check_dangling_names(root: Path, files: list[Path]) -> list[Finding]:
    known = declared_names(root)
    findings: list[Finding] = []
    for path in files:
        relative = PurePosixPath(path.relative_to(root).as_posix())
        if not names_prose(relative):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for line_number, token in dangling_names(text, known):
            findings.append(
                finding("names", relative, f"line {line_number} names unknown skill or agent {token!r}")
            )
    return findings


def load_denylist(root: Path, path: Path) -> tuple[list[tuple[int, str]], list[Finding]]:
    try:
        resolved = path.expanduser().resolve(strict=True)
        text = resolved.read_text(encoding="utf-8")
    except (OSError, RuntimeError, UnicodeError):
        return [], [finding("denylist", "denylist", "denylist file cannot be read")]
    if is_within(resolved, root.resolve()):
        return [], [finding("denylist", "denylist", "denylist file must live outside the repository")]
    terms = [
        (number, line.strip().lower())
        for number, line in enumerate(text.splitlines(), start=1)
        if line.strip() and not line.strip().startswith("#")
    ]
    return terms, []


def denylist_hits(text: str, terms: list[tuple[int, str]]) -> str:
    lowered = text.lower()
    return ", ".join(str(number) for number, term in terms if term in lowered)


def check_denylist(root: Path, entries: list[Path], files: list[Path], denylist: Path) -> list[Finding]:
    terms, findings = load_denylist(root, denylist)
    if not terms:
        return findings
    for path in entries:
        relative = path.relative_to(root)
        hits = denylist_hits(relative.as_posix(), terms)
        if hits:
            findings.append(finding("denylist", relative, f"denylisted term in path (entry {hits})"))
    for path in files:
        relative = path.relative_to(root)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            hits = denylist_hits(line, terms)
            if hits:
                findings.append(
                    finding("denylist", relative, f"denylisted term at line {line_number} (entry {hits})")
                )
    return findings


def check_extra_skill(
    path: Path,
    reserved: Iterable[str] = (),
    catalog_roots: Iterable[Path] = (),
) -> list[str]:
    name = path.name
    if path.is_symlink():
        return [f"{name}: skill directory must not be a symlink"]
    if not path.is_dir():
        return [f"{name}: skill path must be a directory"]
    resolved = path.resolve()
    problems: list[str] = []
    if not SKILL_NAME_RE.fullmatch(name):
        problems.append(f"{name}: directory name must be lowercase and hyphenated")
    if name in set(reserved):
        problems.append(f"{name}: name collides with a catalog skill")
    if any(is_within(resolved, Path(root).resolve()) for root in catalog_roots):
        problems.append(f"{name}: skill lives inside a catalog root")
    skill_md = path / "SKILL.md"
    if skill_md.is_symlink() or not skill_md.is_file():
        return [*problems, f"{name}: SKILL.md must be a regular file"]
    findings: list[Finding] = []
    fields = skill_frontmatter(skill_md, findings)
    problems.extend(f"{name}: {item.message}" for item in findings)
    if fields is not None:
        if fields.get("name") != name:
            problems.append(f"{name}: frontmatter name must match the directory name")
        description = fields.get("description")
        if not isinstance(description, str) or not 1 <= len(description) <= DESCRIPTION_MAX_CHARS:
            problems.append(f"{name}: description must be 1-{DESCRIPTION_MAX_CHARS} characters")
    problems.extend(f"{name}: {problem}" for problem in bash_grant_problems(skill_md))
    for current, directories, filenames in os.walk(path):
        directories.sort()
        for item in directories + sorted(filenames):
            candidate = Path(current) / item
            inner = PurePosixPath("skills", name, *candidate.relative_to(path).parts)
            if candidate.is_symlink():
                problems.append(f"{name}: {inner.as_posix()} is a symlink; extra skills hold regular files only")
                continue
            if candidate.is_file() and nested_reference(inner):
                problems.append(f"{name}: {inner.as_posix()} nests references more than one level deep")
            kind = md_cap_kind(inner, frozenset())
            if kind is None or not candidate.is_file():
                continue
            row = cap_row(candidate, inner, kind)
            if row is not None and not row.within:
                problems.append(f"{name}: {row.path} {cap_message(row)}")
    return problems


def validate(root: Path, denylist: Path | None = None) -> list[Finding]:
    root = root.resolve()
    entries = repo_entries(root)
    files = regular_files(root, entries)
    findings: list[Finding] = []
    findings.extend(check_symlinks(root, entries))
    findings.extend(check_python(root, files))
    catalog_findings, descriptions, profile, registry_path, fixtures_path = validate_catalog(root)
    findings.extend(catalog_findings)
    findings.extend(validate_routing(root, set(descriptions), registry_path, fixtures_path))
    findings.extend(check_listing(descriptions, profile))
    findings.extend(check_template_parity(root))
    findings.extend(check_md_caps(root, entries, files))
    findings.extend(check_no_bare_bash(root, files))
    findings.extend(check_dangling_names(root, files))
    findings.extend(check_plain_hyphens(root, entries, files))
    findings.extend(check_privacy(root, entries, files))
    findings.extend(check_secrets(root, entries, files))
    if denylist is not None:
        findings.extend(check_denylist(root, entries, files, denylist))
    return sorted(set(findings))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the AI Skills Assembly public repository.")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root")
    parser.add_argument(
        "--denylist",
        type=Path,
        help=f"uncommitted file of private terms, one per line (default: ${DENYLIST_ENV})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    denylist = args.denylist
    if denylist is None and os.environ.get(DENYLIST_ENV, "").strip():
        denylist = Path(os.environ[DENYLIST_ENV].strip())
    findings = validate(args.root, denylist)
    for item in findings:
        print(f"{item.severity.upper()} [{item.check}] {item.path}: {item.message}")
    errors = sum(item.severity == "error" for item in findings)
    warnings = sum(item.severity == "warning" for item in findings)
    if errors:
        print(f"validation failed: {errors} error(s), {warnings} warning(s)", file=sys.stderr)
        return 1
    print(f"validation passed: {warnings} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
