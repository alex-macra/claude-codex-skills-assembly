#!/usr/bin/env python3
"""Install AI Skills Assembly catalogs without third-party dependencies."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

ROOT = Path(__file__).resolve().parent
DEFAULT_CATALOG = ROOT / "catalog.json"
SURFACES = ("claude", "codex", "agents")
MANAGED_BY = "ai-skills"
IGNORE_START = "# ai-skills generated state"
IGNORE_END = "# /ai-skills generated state"
IGNORE_ENTRIES = (".agents/", ".claude/", ".codex/", "AGENTS.md", "CLAUDE.md")
MERGE_GUARD_START = "# ai-skills merge guard"
MERGE_GUARD_END = "# /ai-skills merge guard"
STATE_FILE = ".ai-skills-managed.json"
STATE_DIRS = {"skills": "skills", "agents": "agents", "outputStyles": "output-styles"}
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PYTHON = Path(sys.executable).resolve(strict=False)


class InstallError(RuntimeError):
    pass


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InstallError(f"missing JSON file: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallError(f"cannot read JSON file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise InstallError(f"JSON root must be an object: {path}")
    return data


def contained_path(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise InstallError(f"{label} must be a non-empty relative path")
    if "\\" in value:
        raise InstallError(f"{label} must use POSIX separators: {value}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts:
        raise InstallError(f"{label} must be relative: {value}")
    root = root.resolve(strict=False)
    resolved = root.joinpath(*pure.parts).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise InstallError(f"{label} escapes its catalog: {value}") from exc
    return resolved


def validate_name(value: object, label: str) -> str:
    if not isinstance(value, str) or not NAME_RE.fullmatch(value):
        raise InstallError(f"{label} must be a lowercase hyphenated name")
    return value


@dataclass(frozen=True)
class Catalog:
    path: Path
    root: Path
    data: dict


@dataclass(frozen=True)
class SourceEntry:
    name: str
    path: Path
    catalog: Catalog


@dataclass
class Selection:
    skills: list[SourceEntry]
    agents: list[SourceEntry]
    output_styles: list[SourceEntry]


class CatalogSet:
    def __init__(self, paths: Iterable[Path], allow_missing_sources: bool = False):
        self.catalogs: list[Catalog] = []
        self.skills: dict[str, SourceEntry] = {}
        self.agents: dict[str, SourceEntry] = {}
        self.output_styles: dict[str, SourceEntry] = {}
        self.profiles: dict[str, list[dict]] = {}
        self.routing_paths: list[Path] = []
        self.global_rules: dict[str, Path] = {}
        self.hooks: dict[str, Path] = {}
        self.allow_missing_sources = allow_missing_sources

        resolved_paths: set[Path] = set()
        for raw_path in paths:
            path = raw_path.expanduser().resolve(strict=False)
            if path in resolved_paths:
                continue
            resolved_paths.add(path)
            data = read_json(path)
            if data.get("schemaVersion") != 1:
                raise InstallError(f"unsupported catalog schemaVersion in {path}")
            catalog = Catalog(path=path, root=path.parent, data=data)
            self.catalogs.append(catalog)
            self._load_sources(catalog, "skills", self.skills)
            self._load_sources(catalog, "agents", self.agents)
            self._load_sources(catalog, "outputStyles", self.output_styles)
            self._load_profiles(catalog)
            self._load_routing(catalog)
            self._load_paths(catalog, "globalRules", self.global_rules)
            self._load_paths(catalog, "hooks", self.hooks)

        if not self.catalogs:
            raise InstallError("at least one catalog is required")
        self._validate_profile_references()

    def _load_sources(
        self,
        catalog: Catalog,
        key: str,
        destination: dict[str, SourceEntry],
    ) -> None:
        raw_entries = catalog.data.get(key, {})
        if not isinstance(raw_entries, dict):
            raise InstallError(f"{catalog.path}: {key} must be an object")
        for name, config in raw_entries.items():
            validate_name(name, f"{catalog.path}: {key} name")
            if name in destination:
                previous = destination[name].catalog.path
                raise InstallError(
                    f"duplicate {key[:-1]} name {name!r} in {previous} and {catalog.path}"
                )
            value = config.get("path") if isinstance(config, dict) else None
            source = contained_path(catalog.root, value, f"{key}.{name}.path")
            if (
                not self.allow_missing_sources
                and key == "skills"
                and (not source.is_dir() or not (source / "SKILL.md").is_file())
            ):
                raise InstallError(f"skill source is missing SKILL.md: {source}")
            if (
                not self.allow_missing_sources
                and key in ("agents", "outputStyles")
                and not source.is_file()
            ):
                raise InstallError(f"{key[:-1]} source is not a file: {source}")
            destination[name] = SourceEntry(name=name, path=source, catalog=catalog)

    def _load_profiles(self, catalog: Catalog) -> None:
        profiles = catalog.data.get("profiles", {})
        if not isinstance(profiles, dict):
            raise InstallError(f"{catalog.path}: profiles must be an object")
        for name, profile in profiles.items():
            if not isinstance(profile, dict):
                raise InstallError(f"{catalog.path}: invalid profile {name!r}")
            validate_name(name, f"{catalog.path}: profile name")
            self.profiles.setdefault(name, []).append(profile)

    def _load_routing(self, catalog: Catalog) -> None:
        routing = catalog.data.get("routing", {})
        if not isinstance(routing, dict):
            raise InstallError(f"{catalog.path}: routing must be an object")
        declared: list[str] = []
        registry = routing.get("registry")
        if isinstance(registry, str):
            declared.append(registry)
        elif isinstance(registry, list):
            declared.extend(item for item in registry if isinstance(item, str))
        registries = routing.get("registries")
        if isinstance(registries, list):
            declared.extend(item for item in registries if isinstance(item, str))
        for index, value in enumerate(declared):
            self.routing_paths.append(
                contained_path(catalog.root, value, f"routing.registry[{index}]")
            )

    def _load_paths(
        self,
        catalog: Catalog,
        key: str,
        destination: dict[str, Path],
    ) -> None:
        values = catalog.data.get(key, {})
        if not isinstance(values, dict):
            raise InstallError(f"{catalog.path}: {key} must be an object")
        for name, value in values.items():
            destination[name] = contained_path(catalog.root, value, f"{key}.{name}")

    def _validate_profile_references(self) -> None:
        for name, fragments in self.profiles.items():
            for fragment in fragments:
                for key, available in (
                    ("skills", self.skills),
                    ("agents", self.agents),
                    ("outputStyles", self.output_styles),
                ):
                    values = fragment.get(key, [])
                    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
                        raise InstallError(f"profile {name!r} has invalid {key}")
                    for value in values:
                        validate_name(value, f"profile {name!r} {key} entry")
                    if len(values) != len(set(values)):
                        raise InstallError(f"profile {name!r} has duplicate {key}")
                    missing = sorted(set(values) - set(available))
                    if missing:
                        raise InstallError(
                            f"profile {name!r} references missing {key}: {', '.join(missing)}"
                        )

    @property
    def paths(self) -> list[Path]:
        return [catalog.path for catalog in self.catalogs]

    def select(self, profile_names: list[str]) -> Selection:
        selected_skills: dict[str, SourceEntry] = {}
        selected_agents: dict[str, SourceEntry] = {}
        selected_output_styles: dict[str, SourceEntry] = {}
        for profile_name in profile_names:
            fragments = self.profiles.get(profile_name)
            if not fragments:
                raise InstallError(f"unknown profile: {profile_name}")
            for fragment in fragments:
                for name in fragment.get("skills", []):
                    selected_skills.setdefault(name, self.skills[name])
                for name in fragment.get("agents", []):
                    selected_agents.setdefault(name, self.agents[name])
                for name in fragment.get("outputStyles", []):
                    selected_output_styles.setdefault(name, self.output_styles[name])
        return Selection(
            list(selected_skills.values()),
            list(selected_agents.values()),
            list(selected_output_styles.values()),
        )

    def merged_rules(self, selected_names: set[str]) -> dict:
        merged: dict = {}
        owners: dict[str, Path] = {}
        for path in self.routing_paths:
            data = read_json(path)
            entries = data.get("skills")
            if not isinstance(entries, dict):
                raise InstallError(f"routing registry has no skills object: {path}")
            for name, config in entries.items():
                if name not in selected_names:
                    continue
                validate_name(name, f"routing name in {path}")
                if name in merged:
                    raise InstallError(
                        f"duplicate routing rule {name!r} in {owners[name]} and {path}"
                    )
                merged[name] = config
                owners[name] = path
        missing = sorted(selected_names - set(merged))
        if missing:
            raise InstallError(f"selected skills have no routing rules: {', '.join(missing)}")
        return merged


class Actions:
    def __init__(self, dry_run: bool):
        self.dry_run = dry_run

    def report(self, action: str, path: Path) -> None:
        suffix = " (dry run)" if self.dry_run else ""
        print(f"{action}: {path}{suffix}")

    def backup(self, path: Path) -> None:
        if not path.is_file() or path.is_symlink():
            return
        index = 0
        while True:
            suffix = ".bak" if index == 0 else f".bak.{index}"
            backup = path.with_name(path.name + suffix)
            if not backup.exists() and not backup.is_symlink():
                break
            index += 1
        self.report("backup", backup)
        if not self.dry_run:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            created = False
            try:
                descriptor = os.open(backup, flags, stat.S_IMODE(path.stat().st_mode))
                created = True
                with os.fdopen(descriptor, "wb") as target:
                    with path.open("rb") as source:
                        shutil.copyfileobj(source, target)
                shutil.copystat(path, backup, follow_symlinks=False)
            except OSError as exc:
                try:
                    if created and backup.is_file() and not backup.is_symlink():
                        backup.unlink()
                except OSError:
                    pass
                raise InstallError(f"cannot back up {path}: {exc}") from exc

    def write_text(
        self,
        path: Path,
        text: str,
        action: str = "write",
        backup_existing: bool = True,
    ) -> None:
        if path.is_symlink():
            raise InstallError(f"refusing to replace unmanaged symlink: {path}")
        if path.exists() and not path.is_file():
            raise InstallError(f"refusing to replace non-file path: {path}")
        current = None
        existing_mode = None
        if path.is_file() and not path.is_symlink():
            try:
                current = path.read_text(encoding="utf-8")
                existing_mode = stat.S_IMODE(path.stat().st_mode)
            except OSError as exc:
                raise InstallError(f"cannot read {path}: {exc}") from exc
        if current == text:
            self.report("unchanged", path)
            return
        if backup_existing and (path.exists() or path.is_symlink()):
            self.backup(path)
        self.report(action, path)
        if self.dry_run:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                delete=False,
            ) as handle:
                handle.write(text)
                temporary = Path(handle.name)
            temporary.replace(path)
        except OSError as exc:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            raise InstallError(f"cannot write {path}: {exc}") from exc
        if existing_mode is not None:
            path.chmod(existing_mode)

    def remove(self, path: Path) -> None:
        self.report("remove", path)
        if not self.dry_run:
            path.unlink()


def resolved_link(path: Path) -> Path | None:
    if not path.is_symlink():
        return None
    try:
        value = Path(os.readlink(path))
    except OSError:
        return None
    if not value.is_absolute():
        value = path.parent / value
    return value.resolve(strict=False)


def is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def require_target_parent(target: Path, installation_root: Path) -> None:
    """Reject lexical escapes and ancestor symlinks outside an install root."""
    target = target.absolute()
    installation_root = installation_root.absolute()
    try:
        target.relative_to(installation_root)
    except ValueError as exc:
        raise InstallError(f"target escapes its installation root: {target}") from exc
    resolved_root = installation_root.resolve(strict=False)
    resolved_parent = target.parent.resolve(strict=False)
    if not is_under(resolved_parent, resolved_root):
        raise InstallError(f"target parent resolves outside its installation root: {target}")


def require_writable_target_parent(target: Path) -> None:
    parent = target.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    if not parent.is_dir() or not os.access(parent, os.W_OK | os.X_OK):
        raise InstallError(f"target parent is not writable: {target}")


def preflight_link(
    source: Path,
    target: Path,
    installation_root: Path,
    migration_roots: list[Path],
    uninstall: bool,
    managed_sources: set[Path] | None = None,
) -> None:
    require_target_parent(target, installation_root)
    require_writable_target_parent(target)
    source = source.resolve(strict=False)
    if not uninstall and not source.exists():
        raise InstallError(f"missing source: {source}")
    current = resolved_link(target)
    recorded = {path.resolve(strict=False) for path in (managed_sources or set())}
    managed = (
        current == source
        or current in recorded
        or is_migratable_link(target, source, migration_roots)
    )
    if not uninstall and (target.exists() or target.is_symlink()) and not managed:
        raise InstallError(f"refusing to replace unmanaged path: {target}")


def is_migratable_link(path: Path, source: Path, migration_roots: list[Path]) -> bool:
    current = resolved_link(path)
    if current is None or current.name != source.name:
        return False
    allowed_parts = {"skills", "agents", "hooks", "global", "templates"}
    for root in migration_roots:
        root = root.resolve(strict=False)
        if not is_under(current, root):
            continue
        relative = current.relative_to(root)
        if relative.parts and relative.parts[0] in allowed_parts:
            return True
    return False


def ensure_link(
    actions: Actions,
    source: Path,
    target: Path,
    migration_roots: list[Path],
    uninstall: bool,
    installation_root: Path | None = None,
    managed_sources: set[Path] | None = None,
) -> None:
    if installation_root is not None:
        require_target_parent(target, installation_root)
    source = source.resolve(strict=False)
    if not uninstall and not source.exists():
        raise InstallError(f"missing source: {source}")
    current = resolved_link(target)
    recorded = {path.resolve(strict=False) for path in (managed_sources or set())}
    managed = (
        current == source
        or current in recorded
        or is_migratable_link(target, source, migration_roots)
    )

    if uninstall:
        if managed:
            actions.remove(target)
        elif target.exists() or target.is_symlink():
            actions.report("leave unmanaged", target)
        return

    if current == source:
        actions.report("unchanged", target)
        return
    if target.exists() or target.is_symlink():
        if not managed:
            raise InstallError(f"refusing to replace unmanaged path: {target}")
        actions.remove(target)
    actions.report("link", target)
    if not actions.dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source)


def surface_roots(scope: str, project: Path | None) -> dict[str, Path]:
    if scope == "project":
        assert project is not None
        return {
            "claude": project / ".claude",
            "codex": project / ".codex",
            "agents": project / ".agents",
        }
    return {
        "claude": Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")).expanduser(),
        "codex": Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser(),
        "agents": Path(os.environ.get("AGENTS_HOME", Path.home() / ".agents")).expanduser(),
    }


def empty_state() -> dict:
    return {
        "schemaVersion": 1,
        "managedBy": MANAGED_BY,
        "skills": {},
        "agents": {},
        "outputStyles": {},
        "globalRule": None,
        "hooks": {},
    }


def load_surface_state(root: Path) -> dict:
    path = root / STATE_FILE
    require_target_parent(path, root)
    if not path.exists() and not path.is_symlink():
        return empty_state()
    if path.is_symlink() or not path.is_file():
        raise InstallError(f"refusing unmanaged state path: {path}")
    data = read_json(path)
    if data.get("schemaVersion") != 1 or data.get("managedBy") != MANAGED_BY:
        raise InstallError(f"refusing unmanaged state file: {path}")
    for key in ("skills", "agents"):
        values = data.get(key)
        if not isinstance(values, dict):
            raise InstallError(f"invalid managed state in {path}: {key} must be an object")
        for name, source in values.items():
            validate_name(name, f"managed state {key} name")
            if not isinstance(source, str) or not Path(source).is_absolute():
                raise InstallError(f"invalid managed state source for {key}.{name} in {path}")
    output_styles = data.setdefault("outputStyles", {})
    if not isinstance(output_styles, dict):
        raise InstallError(f"invalid managed state in {path}: outputStyles must be an object")
    for name, source in output_styles.items():
        validate_name(name, "managed state outputStyles name")
        if not isinstance(source, str) or not Path(source).is_absolute():
            raise InstallError(f"invalid managed state source for outputStyles.{name} in {path}")
    global_rule = data.setdefault("globalRule", None)
    if global_rule is not None and (
        not isinstance(global_rule, str) or not Path(global_rule).is_absolute()
    ):
        raise InstallError(f"invalid managed global rule source in {path}")
    hook_sources = data.setdefault("hooks", {})
    if not isinstance(hook_sources, dict):
        raise InstallError(f"invalid managed hooks state in {path}")
    for name, source in hook_sources.items():
        if name not in {spec.key for spec in HOOK_SPECS}:
            raise InstallError(f"invalid managed hook name {name!r} in {path}")
        if not isinstance(source, str) or not Path(source).is_absolute():
            raise InstallError(f"invalid managed hook source for {name} in {path}")
    return data


def state_target(root: Path, kind: str, name: str) -> Path:
    suffix = name if kind == "skills" else f"{name}.md"
    return root / STATE_DIRS[kind] / suffix


def desired_surface_state(
    surface: str,
    selection: Selection,
    previous: dict,
    uninstall: bool,
) -> dict:
    if uninstall:
        return empty_state()
    return {
        "schemaVersion": 1,
        "managedBy": MANAGED_BY,
        "skills": {entry.name: str(entry.path.resolve(strict=False)) for entry in selection.skills},
        "agents": {
            entry.name: str(entry.path.resolve(strict=False))
            for entry in selection.agents
            if surface in {"claude", "codex"}
        },
        "outputStyles": {
            entry.name: str(entry.path.resolve(strict=False))
            for entry in selection.output_styles
            if surface == "claude"
        },
        "globalRule": previous.get("globalRule"),
        "hooks": dict(previous.get("hooks", {})),
    }


def surface_link_operations(
    surface: str,
    root: Path,
    selection: Selection,
    uninstall: bool,
) -> tuple[dict, dict, list[tuple[Path, Path, bool, set[Path]]]]:
    previous = load_surface_state(root)
    desired = desired_surface_state(surface, selection, previous, uninstall)
    operations: list[tuple[Path, Path, bool, set[Path]]] = []
    for kind in ("skills", "agents", "outputStyles"):
        prior_entries = previous[kind]
        desired_entries = desired[kind]
        for name, raw_source in prior_entries.items():
            if name not in desired_entries:
                operations.append((Path(raw_source), state_target(root, kind, name), True, set()))
        if kind == "skills":
            selected_entries = selection.skills
        elif kind == "agents":
            selected_entries = selection.agents
        else:
            selected_entries = selection.output_styles
        if kind == "agents" and surface == "agents":
            selected_entries = []
        if kind == "outputStyles" and surface != "claude":
            selected_entries = []
        if uninstall:
            # Legacy pre-state links are still removable when their catalog entry exists.
            for entry in selected_entries:
                if entry.name not in prior_entries:
                    operations.append((entry.path, state_target(root, kind, entry.name), True, set()))
        else:
            for entry in selected_entries:
                prior = prior_entries.get(entry.name)
                owned = {Path(prior)} if isinstance(prior, str) else set()
                operations.append((entry.path, state_target(root, kind, entry.name), False, owned))
    return previous, desired, operations


def write_surface_state(actions: Actions, root: Path, state_data: dict) -> None:
    path = root / STATE_FILE
    if (
        not state_data["skills"]
        and not state_data["agents"]
        and not state_data.get("outputStyles")
        and not state_data.get("globalRule")
        and not state_data.get("hooks")
    ):
        if path.is_file() and not path.is_symlink():
            actions.remove(path)
        return
    actions.write_text(
        path,
        json.dumps(state_data, indent=2, sort_keys=True) + "\n",
        "update managed state",
        backup_existing=False,
    )


def planned_gitignore(project: Path, uninstall: bool) -> tuple[Path, str, bool]:
    path = project / ".gitignore"
    require_target_parent(path, project)
    require_writable_target_parent(path)
    if path.is_symlink():
        raise InstallError(f"refusing to modify unmanaged symlink: {path}")
    if path.exists() and not path.is_file():
        raise InstallError(f"refusing to modify non-file path: {path}")
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if text.count(IGNORE_START) > 1 or text.count(IGNORE_END) > 1:
        raise InstallError(f"duplicate AI Skills Assembly blocks in {path}")
    start = text.find(IGNORE_START)
    end = text.find(IGNORE_END)
    if (start >= 0) != (end >= 0) or (start >= 0 and end < start):
        raise InstallError(f"malformed AI Skills Assembly block in {path}")

    if start >= 0:
        end += len(IGNORE_END)
        if end < len(text) and text[end] == "\n":
            end += 1
        before = text[:start].rstrip("\n")
        after = text[end:].lstrip("\n")
        without = "\n\n".join(part for part in (before, after) if part)
        if without:
            without += "\n"
    else:
        without = text

    if uninstall:
        return path, without, start >= 0 and without != text

    block = "\n".join((IGNORE_START, *IGNORE_ENTRIES, IGNORE_END)) + "\n"
    prefix = without.rstrip("\n")
    desired = f"{prefix}\n\n{block}" if prefix else block
    return path, desired, desired != text


def update_gitignore(actions: Actions, project: Path, uninstall: bool) -> None:
    path, desired, changed = planned_gitignore(project, uninstall)
    if changed:
        if uninstall and not desired:
            actions.remove(path)
        else:
            actions.write_text(path, desired, "update")
    else:
        actions.report("unchanged", path)


def routing_snapshot(
    project: Path,
    catalogs: CatalogSet,
    migration_roots: list[Path],
    removing: bool,
) -> tuple[Path, dict | None]:
    target = project / ".claude" / "skills" / "skill-rules.json"
    require_target_parent(target, project)
    require_writable_target_parent(target)
    declared_sources = {path.resolve(strict=False) for path in catalogs.routing_paths}
    current_link = resolved_link(target)
    migratable = current_link in declared_sources or any(
        current_link is not None and is_under(current_link, root) and current_link.name == "skill-rules.json"
        for root in migration_roots
    )

    if target.is_symlink():
        if not migratable:
            if removing:
                return target, None
            raise InstallError(f"refusing to replace unmanaged path: {target}")
        data = read_json(target) if target.is_file() else {}
    elif target.exists():
        if not target.is_file():
            raise InstallError(f"refusing to replace non-file path: {target}")
        data = read_json(target)
        if data.get("_managedBy") != MANAGED_BY:
            if removing:
                return target, None
            raise InstallError(f"refusing to replace unmanaged path: {target}")
    else:
        data = {}
    entries = data.get("skills", {})
    if not isinstance(entries, dict):
        raise InstallError(f"managed routing skills must be an object: {target}")
    return target, entries


def planned_routing_rules(
    project: Path,
    catalogs: CatalogSet,
    selected_names: set[str],
    active_names: set[str],
    migration_roots: list[Path],
    uninstall: bool,
) -> dict:
    _, existing = routing_snapshot(
        project,
        catalogs,
        migration_roots,
        removing=not active_names,
    )
    if not active_names:
        return {}
    current = {} if uninstall else catalogs.merged_rules(selected_names)
    existing = existing or {}
    rules = {
        name: current[name] if name in current else existing[name]
        for name in active_names
        if name in current or name in existing
    }
    missing = sorted(active_names - set(rules))
    if missing:
        raise InstallError(
            "active skills have no available routing rules: " + ", ".join(missing)
        )
    return rules


def install_routing(
    actions: Actions,
    project: Path,
    catalogs: CatalogSet,
    migration_roots: list[Path],
    rules: dict,
) -> None:
    target, existing = routing_snapshot(
        project,
        catalogs,
        migration_roots,
        removing=not rules,
    )
    if not rules:
        if existing is None:
            actions.report("leave unmanaged", target)
        elif target.exists() or target.is_symlink():
            actions.remove(target)
        return

    if target.is_symlink():
        actions.remove(target)

    payload = {
        "schemaVersion": 1,
        "_managedBy": MANAGED_BY,
        "skills": rules,
    }
    actions.write_text(target, json.dumps(payload, indent=2, sort_keys=True) + "\n")


@dataclass(frozen=True)
class HookSpec:
    key: str
    filename: str
    event: str
    matcher: str
    status: str
    timeout: int


HOOK_SPECS = (
    HookSpec(
        "activation",
        "skill-activation.py",
        "UserPromptSubmit",
        "",
        "Skill activation check",
        5,
    ),
    HookSpec(
        "usage",
        "skill-usage-log.py",
        "PreToolUse",
        "Skill",
        "Skill usage log",
        5,
    ),
    HookSpec(
        "mergeGuard",
        "merge-guard.py",
        "PreToolUse",
        "Bash",
        "Protected branch check",
        50,
    ),
)


def hook_source(catalogs: CatalogSet, spec: HookSpec) -> Path:
    return catalogs.hooks.get(spec.key, ROOT / "hooks" / spec.filename)


def hook_entry(catalogs: CatalogSet, spec: HookSpec) -> dict:
    source = hook_source(catalogs, spec)
    catalog_value = os.pathsep.join(str(path) for path in catalogs.paths)
    interpreter = shlex.quote(str(PYTHON))
    if spec.key == "mergeGuard":
        command = f"{interpreter} -I {shlex.quote(str(source))}"
    else:
        command = (
            f"test -f {shlex.quote(str(source))} && "
            f"env AI_SKILLS_CATALOGS={shlex.quote(catalog_value)} "
            f"{interpreter} -I {shlex.quote(str(source))} || true"
        )
    return {
        "matcher": spec.matcher,
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": spec.timeout,
                "statusMessage": spec.status,
            }
        ],
    }


def hook_command_managed(
    command: object,
    source: Path,
    spec: HookSpec,
    migration_roots: list[Path],
    owned_sources: set[Path] | None = None,
) -> bool:
    if not isinstance(command, str):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    expected = {str(source.resolve(strict=False))}
    expected.update(
        str((root / "hooks" / spec.filename).resolve(strict=False))
        for root in migration_roots
    )
    expected.update(
        str(path.resolve(strict=False)) for path in (owned_sources or set())
    )
    for index, token in enumerate(tokens):
        if index == 0:
            continue
        candidate = Path(token)
        if not candidate.is_absolute():
            continue
        try:
            normalized = str(candidate.resolve(strict=False))
        except (OSError, RuntimeError):
            continue
        if normalized not in expected:
            continue
        interpreter_index = index - 2 if index >= 2 and tokens[index - 1] == "-I" else index - 1
        interpreter = Path(tokens[interpreter_index]).name
        if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", interpreter):
            return True
    return False


def strip_hook(
    matchers: list,
    catalogs: CatalogSet,
    spec: HookSpec,
    migration_roots: list[Path],
    owned_sources: set[Path] | None = None,
) -> list:
    kept = []
    source = hook_source(catalogs, spec)
    for group in matchers:
        if not isinstance(group, dict):
            kept.append(group)
            continue
        if "hooks" not in group:
            kept.append(group)
            continue
        raw_hooks = group["hooks"]
        if not isinstance(raw_hooks, list):
            raise InstallError("settings hook group 'hooks' value must be a list")
        hooks = [
            item
            for item in raw_hooks
            if not (
                isinstance(item, dict)
                and hook_command_managed(
                    item.get("command"),
                    source,
                    spec,
                    migration_roots,
                    owned_sources,
                )
            )
        ]
        if hooks:
            kept.append(dict(group, hooks=hooks))
        elif not raw_hooks:
            kept.append(group)
    return kept


def apply_hooks_to_data(
    catalogs: CatalogSet,
    data: dict,
    migration_roots: list[Path],
    uninstall: bool,
    owned_sources: dict[str, set[Path]] | None = None,
) -> bool:
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise InstallError("settings 'hooks' value must be an object")
    changed = False
    for spec in HOOK_SPECS:
        if not uninstall and not hook_source(catalogs, spec).is_file():
            raise InstallError(f"missing hook source: {hook_source(catalogs, spec)}")
        groups = hooks.setdefault(spec.event, [])
        if not isinstance(groups, list):
            raise InstallError(f"settings hook event {spec.event!r} must be a list")
        stripped = strip_hook(
            groups,
            catalogs,
            spec,
            migration_roots,
            (owned_sources or {}).get(spec.key),
        )
        if uninstall:
            replacement = stripped
        else:
            replacement = [*stripped, hook_entry(catalogs, spec)]
        if replacement != groups:
            hooks[spec.event] = replacement
            changed = True
    return changed


def install_hooks(
    actions: Actions,
    catalogs: CatalogSet,
    settings_paths: list[Path],
    settings_roots: dict[Path, Path],
    migration_roots: list[Path],
    uninstall: bool,
    owned_by_path: dict[Path, dict[str, set[Path]]],
) -> None:
    for path in settings_paths:
        require_target_parent(path, settings_roots[path])
        require_writable_target_parent(path)
        if path.is_symlink():
            raise InstallError(f"refusing to modify unmanaged symlink: {path}")
        data = read_json(path) if path.is_file() else {}
        changed = apply_hooks_to_data(
            catalogs,
            data,
            migration_roots,
            uninstall,
            owned_by_path.get(path, {}),
        )
        if changed:
            actions.write_text(path, json.dumps(data, indent=2) + "\n", "update hooks")
        else:
            actions.report("unchanged", path)


def validate_project(path: Path) -> Path:
    path = path.expanduser().resolve(strict=False)
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise InstallError(f"not a Git worktree: {path}")
    return Path(result.stdout.strip()).resolve(strict=False)


def settings_roots(scope: str, project: Path | None, surfaces: list[str]) -> dict[Path, Path]:
    roots = surface_roots(scope, project)
    mapping: dict[Path, Path] = {}
    if "claude" in surfaces:
        mapping[roots["claude"] / "settings.json"] = roots["claude"]
    if "codex" in surfaces:
        mapping[roots["codex"] / "hooks.json"] = roots["codex"]
    return mapping


def preflight_hooks(
    catalogs: CatalogSet,
    roots_by_path: dict[Path, Path],
    migration_roots: list[Path],
    uninstall: bool,
    owned_by_path: dict[Path, dict[str, set[Path]]],
) -> None:
    for path, root in roots_by_path.items():
        require_target_parent(path, root)
        require_writable_target_parent(path)
        if path.is_symlink():
            raise InstallError(f"refusing to modify unmanaged symlink: {path}")
        if path.exists() and not path.is_file():
            raise InstallError(f"refusing to modify non-file path: {path}")
        data = read_json(path) if path.is_file() else {}
        apply_hooks_to_data(
            catalogs,
            copy.deepcopy(data),
            migration_roots,
            uninstall,
            owned_by_path.get(path, {}),
        )


def global_rule_target(
    scope: str,
    project: Path | None,
    roots: dict[str, Path],
    surface: str,
) -> tuple[Path, Path]:
    if scope == "project":
        assert project is not None
        name = "CLAUDE.md" if surface == "claude" else "AGENTS.md"
        return project / name, project
    name = "CLAUDE.md" if surface == "claude" else "AGENTS.md"
    return roots[surface] / name, roots[surface]


def run_install(args: argparse.Namespace) -> int:
    catalog_paths = [Path(path) for path in (args.catalog or [DEFAULT_CATALOG])]
    catalogs = CatalogSet(catalog_paths, allow_missing_sources=args.uninstall)
    profiles = args.profile or ["default"]
    selection = catalogs.select(profiles)
    actions = Actions(args.dry_run)
    migration_roots = [Path(path).expanduser().resolve(strict=False) for path in args.migrate_from]
    project = validate_project(Path(args.project)) if args.command == "project" else None
    roots = surface_roots(args.command, project)
    surfaces = args.surface or list(SURFACES)

    # Build and validate the complete mutation set before changing any target.
    surface_plans: dict[
        str,
        tuple[dict, dict, list[tuple[Path, Path, bool, set[Path]]]],
    ] = {}
    for surface in surfaces:
        root = roots[surface]
        plan = surface_link_operations(surface, root, selection, args.uninstall)
        surface_plans[surface] = plan
        state_path = root / STATE_FILE
        require_target_parent(state_path, root)
        require_writable_target_parent(state_path)
        for source, target, remove, owned in plan[2]:
            preflight_link(
                source,
                target,
                root,
                migration_roots,
                remove,
                owned,
            )

    rule_plans: list[tuple[Path, Path, Path, bool, set[Path]]] = []
    for surface in (item for item in surfaces if item in {"claude", "codex"}):
        previous, desired, _ = surface_plans[surface]
        previous_source = previous.get("globalRule")
        current_source = catalogs.global_rules.get(surface)
        if args.uninstall:
            source = Path(previous_source) if previous_source else current_source
            if source is None:
                continue
            remove = True
        elif args.global_rules:
            if current_source is None:
                raise InstallError(f"catalogs do not declare a global rule for: {surface}")
            source = current_source
            desired["globalRule"] = str(source.resolve(strict=False))
            remove = False
        else:
            continue
        owned = {Path(previous_source)} if previous_source else set()
        target, target_root = global_rule_target(
            args.command,
            project,
            roots,
            surface,
        )
        preflight_link(
            source,
            target,
            target_root,
            migration_roots,
            remove,
            owned,
        )
        rule_plans.append((source, target, target_root, remove, owned))

    manage_hooks = args.hooks or args.uninstall
    hook_roots = settings_roots(args.command, project, surfaces) if manage_hooks else {}
    if args.hooks and not hook_roots:
        raise InstallError("hooks require the claude or codex surface")
    hook_owned_by_path: dict[Path, dict[str, set[Path]]] = {}
    for surface in (item for item in surfaces if item in {"claude", "codex"}):
        if not manage_hooks:
            continue
        previous, desired, _ = surface_plans[surface]
        settings_name = "settings.json" if surface == "claude" else "hooks.json"
        settings_path = roots[surface] / settings_name
        hook_owned_by_path[settings_path] = {
            name: {Path(source)}
            for name, source in previous.get("hooks", {}).items()
        }
        if not args.uninstall:
            desired["hooks"] = {
                spec.key: str(hook_source(catalogs, spec).resolve(strict=False))
                for spec in HOOK_SPECS
            }
    if hook_roots:
        preflight_hooks(
            catalogs,
            hook_roots,
            migration_roots,
            args.uninstall,
            hook_owned_by_path,
        )

    routing_rules: dict = {}
    keep_project_state = False
    if project is not None:
        post_states = {
            surface: (
                surface_plans[surface][1]
                if surface in surface_plans
                else load_surface_state(roots[surface])
            )
            for surface in SURFACES
        }
        active_names = {
            name
            for state_data in post_states.values()
            for name in state_data["skills"]
        }
        keep_project_state = any(
            state_data["skills"]
            or state_data["agents"]
            or state_data.get("outputStyles")
            or state_data.get("globalRule")
            or state_data.get("hooks")
            for state_data in post_states.values()
        )
        routing_rules = planned_routing_rules(
            project,
            catalogs,
            {entry.name for entry in selection.skills},
            active_names,
            migration_roots,
            args.uninstall,
        )
        planned_gitignore(project, not keep_project_state)

    for surface in surfaces:
        root = roots[surface]
        for source, target, remove, owned in surface_plans[surface][2]:
            ensure_link(
                actions,
                source,
                target,
                migration_roots,
                remove,
                installation_root=root,
                managed_sources=owned,
            )

    for source, target, target_root, remove, owned in rule_plans:
        ensure_link(
            actions,
            source,
            target,
            migration_roots,
            remove,
            installation_root=target_root,
            managed_sources=owned,
        )

    if project is not None:
        update_gitignore(actions, project, not keep_project_state)
        install_routing(
            actions,
            project,
            catalogs,
            migration_roots,
            routing_rules,
        )

    if hook_roots:
        install_hooks(
            actions,
            catalogs,
            list(hook_roots),
            hook_roots,
            migration_roots,
            args.uninstall,
            hook_owned_by_path,
        )

    for surface in surfaces:
        write_surface_state(actions, roots[surface], surface_plans[surface][1])

    verb = "uninstalled" if args.uninstall else "installed"
    print(
        f"{verb} {len(selection.skills)} skill(s), {len(selection.agents)} agent(s), "
        f"and {len(selection.output_styles)} output style(s) for {', '.join(surfaces)}"
    )
    return 0


def git_common_dir(project: Path) -> Path:
    project = validate_project(project)
    result = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise InstallError(f"cannot find Git directory for {project}")
    value = Path(result.stdout.strip())
    return value.resolve(strict=False) if value.is_absolute() else (project / value).resolve(strict=False)


def replace_marked_block(text: str, start: str, end: str, replacement: str) -> tuple[str, bool]:
    if text.count(start) > 1 or text.count(end) > 1:
        raise InstallError(f"duplicate managed blocks beginning with {start!r}")
    start_index = text.find(start)
    end_index = text.find(end)
    if (start_index >= 0) != (end_index >= 0) or (start_index >= 0 and end_index < start_index):
        raise InstallError(f"malformed managed block beginning with {start!r}")
    if start_index < 0:
        if not replacement:
            return text, False
        prefix = text.rstrip("\n")
        combined = f"{prefix}\n\n{replacement}" if prefix else replacement
        return combined, True
    end_index += len(end)
    if end_index < len(text) and text[end_index] == "\n":
        end_index += 1
    prefix = text[:start_index].rstrip("\n")
    suffix = text[end_index:].lstrip("\n")
    pieces = [piece for piece in (prefix, replacement.rstrip("\n"), suffix) if piece]
    combined = "\n\n".join(pieces)
    if combined:
        combined += "\n"
    return combined, combined != text


def run_merge_guard(args: argparse.Namespace) -> int:
    actions = Actions(args.dry_run)
    guard = ROOT / "hooks" / "merge-guard.py"
    if not args.uninstall and not guard.is_file():
        raise InstallError(f"missing merge guard: {guard}")
    quoted = shlex.quote(str(guard))
    interpreter = shlex.quote(str(PYTHON))
    block = "\n".join(
        (
            MERGE_GUARD_START,
            f"if [ ! -f {quoted} ]; then echo 'Blocked: AI Skills Assembly merge guard is missing.' >&2; exit 1; fi",
            f"{interpreter} {quoted} --git-pre-push \"$1\" || exit $?",
            MERGE_GUARD_END,
            "",
        )
    )
    plans: list[tuple[Path, str, bool]] = []
    for raw_project in args.repositories:
        project = Path(raw_project).expanduser().resolve(strict=False)
        common = git_common_dir(project)
        hook = common / "hooks" / "pre-push"
        require_target_parent(hook, common)
        require_writable_target_parent(hook)
        if hook.is_symlink():
            raise InstallError(f"refusing to modify symlinked hook: {hook}")
        if hook.exists() and not hook.is_file():
            raise InstallError(f"refusing to modify non-file hook: {hook}")
        text = hook.read_text(encoding="utf-8") if hook.is_file() else "#!/usr/bin/env sh\n"
        desired, changed = replace_marked_block(
            text,
            MERGE_GUARD_START,
            MERGE_GUARD_END,
            "" if args.uninstall else block,
        )
        plans.append((hook, desired, changed))

    for hook, desired, changed in plans:
        if changed:
            actions.write_text(hook, desired, "update merge guard")
            if not actions.dry_run and hook.exists():
                hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        else:
            actions.report("unchanged", hook)
    return 0


def add_install_options(parser: argparse.ArgumentParser, project: bool) -> None:
    if project:
        parser.add_argument("project", help="target Git worktree")
    parser.add_argument("--catalog", action="append", help="catalog path; repeatable")
    parser.add_argument("--profile", action="append", help="profile name; repeatable")
    parser.add_argument("--surface", action="append", choices=SURFACES, help="skill surface; repeatable")
    parser.add_argument(
        "--hooks",
        action="store_true",
        help="install activation, usage, and protected-branch command hooks",
    )
    parser.add_argument("--global-rules", action="store_true", help="install opt-in rule templates")
    parser.add_argument("--migrate-from", action="append", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true", help="show changes without writing")
    parser.add_argument("--uninstall", action="store_true", help="remove managed entries")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    user = subparsers.add_parser("user", help="install into user configuration directories")
    add_install_options(user, project=False)
    project = subparsers.add_parser("project", help="install into a Git worktree")
    add_install_options(project, project=True)
    guard = subparsers.add_parser("merge-guard", help="manage pre-push guards in explicit repositories")
    guard.add_argument("repositories", nargs="+", help="target Git worktrees")
    guard.add_argument("--dry-run", action="store_true", help="show changes without writing")
    guard.add_argument("--uninstall", action="store_true", help="remove managed entries")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        if args.command == "merge-guard":
            return run_merge_guard(args)
        return run_install(args)
    except (InstallError, OSError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
