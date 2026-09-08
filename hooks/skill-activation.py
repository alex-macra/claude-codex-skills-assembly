#!/usr/bin/env python3
"""UserPromptSubmit hook that emits matching skill names.

Routing registries are discovered from catalogs in ``AI_SKILLS_CATALOGS``.
The variable uses the operating system path separator. When it is unset, the
catalog beside this checkout is used. Project-local rules load last.

The hook is deliberately fail-open. It emits names only, caps its output, and
never blocks a prompt because a catalog, registry, or payload is malformed.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import signal
import sys
import time
from pathlib import Path, PurePosixPath

MAX_OUTPUT_CHARS = 300
MAX_NAMED_SKILLS = 4
MAX_INTENT_PATTERN_CHARS = 512
MAX_INTENT_PROMPT_CHARS = 8_192
MAX_PROMPT_SCOPES = 32
MAX_REGEX_REPEAT = 1_000
REGEX_TIMEOUT_SECONDS = 0.02

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = REPO_ROOT / "catalog.json"

PATH_TOKEN_RE = re.compile(
    r"[A-Za-z0-9_./-]*\.(?:json|yaml|yml|md|html|css|scss|js|jsx|ts|tsx|py|sh|cs|gd|tscn|tres|php|sql|toml)\b"
)
PROMPT_KEYS = ("prompt", "user_prompt", "userPrompt", "message", "text", "input")
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
BRACED_REPEAT_RE = re.compile(r"\{([0-9]+)(?:,([0-9]*))?\}")
LEADING_CLAUSE_SEPARATOR_RE = re.compile(
    r"^(?:[\s.!?;,:-]+|(?:but|instead)\b[\s,:-]*)+",
    re.IGNORECASE,
)
TRAILING_CLAUSE_SEPARATOR_RE = re.compile(
    r"(?:(?:[.!?;]+\s*|\n+\s*)|(?:but|instead)\b[\s,:-]*)\Z",
    re.IGNORECASE,
)
LOGICAL_CLAUSE_SEPARATOR_RE = re.compile(r"(?:but|instead)\b", re.IGNORECASE)
CLAUSE_SPLIT_RE = re.compile(
    r"(?:(?<=[.!?;])\s+|\n+|(?:,\s*)?\b(?:but|instead)\b[\s,:-]*)",
    re.IGNORECASE,
)
BARE_COORDINATOR_RE = re.compile(r"\s+\b(?:and|then|while|yet)\b\s+", re.IGNORECASE)
DIRECT_NEGATION_SIGNAL_RE = re.compile(
    r"\b(?:(?:do not|don't|never|should not|must not|cannot|can't|can not|"
    r"will not|won't)(?!\s+(?:(?:forget|hesitate|fail|neglect|wait)\s+to|"
    r"(?:skip|avoid|refrain)\b))"
    r"|would rather not|no need to|refuse(?:d|s)?\s+to|decline(?:d|s)?\s+to|"
    r"unable\s+to|refrain(?:ed|s|ing)?\s+from|avoid(?:ed|s|ing)?|"
    r"skip(?:ped|s|ping)?|except)\b",
    re.IGNORECASE,
)
APOSTROPHE_TRANSLATION = str.maketrans({"\u2018": "'", "\u2019": "'"})
RESUMABLE_EXCLUSION_RE = re.compile(
    r"\b(?:do not|don't|should not|must not|cannot|can't|can not|will not|won't|"
    r"would rather not|never(?!\s+mind\b))\b"
    r"|\b(?:refuse|refused|refuses|decline|declined|declines|unable)\s+to\b"
    r"|\b(?:avoid(?:ed|ing)?|skip(?:ped|ping)?|no need to|"
    r"refrain(?:ed|ing)?\s+from|except)\b"
    r"|\bwithout\s+(?:doing|running|performing|conducting|researching|planning|creating|opening|committing|staging|pushing)\b"
    r"|\b(?:if|whether|why)\b"
    r"|\b(?:instruction|request|prompt|command)\b[^.;\n]{0,100}\b(?:rejected|declined|discarded)\b"
    r"|\A\s*(?:before|if)\b[^.;\n]{0,180}\b(?:explain|describe|summarize|define)\b"
    r"|\b(?:readme|docs?|documentation|file|text)\b[^.;\n]{0,160}"
    r"\b(?:says?|contains?|includes?|quotes?|quoted?|example|sentence|instruction|phrase)\b"
    r"|\A\s*(?:(?:but|instead)\b[\s,:-]*)?"
    r"(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
    r"(?:explain|define|describe|translate|quote|repeat|analy[sz]e|parse|classify|summarize|ignore)\b",
    re.IGNORECASE,
)
NON_RESUMABLE_EXCLUSION_RE = re.compile(
    r"\b(?:delivery|quality)\s+loop\b[^.;\n]{0,80}"
    r"\b(?:do not|don't|should not|never)\b[^.;\n]{0,40}"
    r"\b(?:run|use|execute|invoke)\s+it\b"
    r"|(?:[.!?;]|\n)\s*(?:actually\s+)?(?:no|never mind)\b[^;\n]{0,120}"
    r"\b(?:explain|describe|summarize|stop|cancel)\b",
    re.IGNORECASE,
)
CANCELLATION_CLAUSE_RE = re.compile(
    r"\A\s*(?:actually\s+)?(?:no|never mind)\b[^;\n]{0,120}"
    r"\b(?:explain|describe|summarize|stop|cancel)\b",
    re.IGNORECASE,
)
ANAPHORIC_CANCELLATION_CLAUSE_RE = re.compile(
    r"\A\s*(?:do not|don't|never|should not|must not|cannot|can't|can not)"
    r"\s+(?:run|use|execute|invoke)\s+it\s*[.!?;]*\s*\Z",
    re.IGNORECASE,
)
REJECTED_META_CLAUSE_RE = re.compile(
    r"\A\s*(?:the\s+)?(?:(?:instruction|request|prompt|command)\b[^.;\n]{0,100}"
    r"\b(?:rejected|declined|discarded)\b|(?:rejected|declined|discarded)\s+"
    r"(?:instruction|request|prompt|command)\b)",
    re.IGNORECASE,
)
AFFIRMATIVE_OPT_OUT_RE = re.compile(
    r"\b(?:do not|don't|never|should not|must not|cannot|can't|can not|"
    r"will not|won't)\s+(?:skip|avoid|refrain)\b",
    re.IGNORECASE,
)
NESTED_OPT_OUT_NEGATION_RE = re.compile(r"^\s+(?:not|never)\b", re.IGNORECASE)


class IntentRegexTimeout(TimeoutError):
    pass


def raise_intent_regex_timeout(_signum: int, _frame: object) -> None:
    raise IntentRegexTimeout


def read_prompt() -> str:
    raw = sys.stdin.read()
    if not raw.strip():
        return ""
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw.strip()
    if isinstance(payload, str):
        return payload.strip()
    if not isinstance(payload, dict):
        return ""
    for key in PROMPT_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for value in payload.values():
        if not isinstance(value, dict):
            continue
        for key in PROMPT_KEYS:
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return ""


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def load_rules(path: Path) -> dict:
    data = load_json(path)
    skills = data.get("skills") if isinstance(data, dict) else None
    return skills if isinstance(skills, dict) else {}


def catalog_paths() -> list[Path]:
    raw = os.environ.get("AI_SKILLS_CATALOGS", "")
    if not raw.strip():
        return [DEFAULT_CATALOG]
    paths = []
    for item in raw.split(os.pathsep):
        if item.strip():
            paths.append(Path(item).expanduser().resolve(strict=False))
    return paths or [DEFAULT_CATALOG]


def catalog_registry_paths(catalog_path: Path) -> list[Path]:
    catalog_path = catalog_path.expanduser().resolve(strict=False)
    data = load_json(catalog_path)
    if not isinstance(data, dict):
        return []
    routing = data.get("routing")
    if not isinstance(routing, dict):
        return []

    declared: list[str] = []
    registry = routing.get("registry")
    if isinstance(registry, str):
        declared.append(registry)
    elif isinstance(registry, list):
        declared.extend(item for item in registry if isinstance(item, str))
    registries = routing.get("registries")
    if isinstance(registries, list):
        declared.extend(item for item in registries if isinstance(item, str))

    base = catalog_path.parent.resolve(strict=False)
    paths: list[Path] = []
    for item in declared:
        if not item.strip() or "\\" in item or re.match(r"^[A-Za-z]:", item):
            continue
        pure = PurePosixPath(item)
        if pure.is_absolute() or ".." in pure.parts:
            continue
        candidate = base.joinpath(*pure.parts).resolve(strict=False)
        try:
            candidate.relative_to(base)
        except ValueError:
            continue
        paths.append(candidate)
    return paths


def project_rule_paths(cwd: Path | None = None) -> list[Path]:
    current = (cwd or Path.cwd()).resolve(strict=False)
    directories = []
    for directory in (current, *current.parents):
        directories.append(directory)
        if (directory / ".git").exists():
            break
    candidates = [
        directory / ".claude" / "skills" / "skill-rules.json"
        for directory in reversed(directories)
    ]
    return [path for path in candidates if path.is_file()]


def registry() -> dict:
    entries: dict = {}
    for catalog in catalog_paths():
        for rules_path in catalog_registry_paths(catalog):
            entries.update(load_rules(rules_path))
    for rules_path in project_rule_paths():
        entries.update(load_rules(rules_path))
    return entries


def select(prompt: str, entries: dict, available: set[str] | None) -> list[str]:
    matched = match_skills(prompt, entries)
    if available is None:
        return matched
    return [name for name in matched if name in available]


def available_skills() -> set[str]:
    claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    agents_home = Path(os.environ.get("AGENTS_HOME", Path.home() / ".agents"))
    roots = [
        claude_home / "skills",
        codex_home / "skills",
        agents_home / "skills",
    ]
    cwd = Path.cwd()
    for directory in (cwd, *cwd.parents):
        for surface in (".claude", ".agents", ".codex"):
            roots.append(directory / surface / "skills")
        if (directory / ".git").exists():
            break

    names: set[str] = set()
    for root in roots:
        try:
            names.update(child.name for child in root.iterdir() if (child / "SKILL.md").is_file())
        except OSError:
            continue
    return names


def matches_keywords(prompt_lc: str, keywords: list) -> bool:
    return any(isinstance(keyword, str) and keyword.lower() in prompt_lc for keyword in keywords)


def is_safe_intent_pattern(pattern: str) -> bool:
    if not isinstance(pattern, str) or not pattern or len(pattern) > MAX_INTENT_PATTERN_CHARS:
        return False
    if "(?P=" in pattern:
        return False

    frames = [
        {
            "repeat": False,
            "alternation": False,
            "last_quantified": False,
            "follows_quantified": False,
            "quantified_run": 0,
        }
    ]
    last_group: tuple[bool, bool] | None = None
    in_character_class = False
    escaped = False
    previous_quantifier = False
    index = 0

    def begin_atom() -> None:
        frame = frames[-1]
        frame["follows_quantified"] = frame["last_quantified"]
        if not frame["last_quantified"]:
            frame["quantified_run"] = 0
        frame["last_quantified"] = False

    while index < len(pattern):
        character = pattern[index]
        if in_character_class:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == "]":
                in_character_class = False
            index += 1
            continue
        if escaped:
            if character in "123456789":
                return False
            escaped = False
            begin_atom()
            last_group = None
            previous_quantifier = False
            index += 1
            continue
        if character == "\\":
            escaped = True
            index += 1
            continue
        if character == "[":
            begin_atom()
            in_character_class = True
            last_group = None
            previous_quantifier = False
            index += 1
            continue
        if character == "(":
            frames.append(
                {
                    "repeat": False,
                    "alternation": False,
                    "last_quantified": False,
                    "follows_quantified": False,
                    "quantified_run": 0,
                }
            )
            last_group = None
            previous_quantifier = False
            index += 1
            continue
        if character == ")":
            if len(frames) == 1:
                return False
            closed = frames.pop()
            frames[-1]["repeat"] |= closed["repeat"]
            frames[-1]["alternation"] |= closed["alternation"]
            begin_atom()
            last_group = (closed["repeat"], closed["alternation"])
            previous_quantifier = False
            index += 1
            continue
        if character == "|":
            frames[-1]["alternation"] = True
            frames[-1]["last_quantified"] = False
            frames[-1]["follows_quantified"] = False
            frames[-1]["quantified_run"] = 0
            last_group = None
            previous_quantifier = False
            index += 1
            continue
        if character in "*+?":
            if character == "?" and (previous_quantifier or (index > 0 and pattern[index - 1] == "(")):
                previous_quantifier = False
                index += 1
                continue
            repeats_more_than_once = character in "*+"
            if repeats_more_than_once and last_group is not None and any(last_group):
                return False
            if frames[-1]["follows_quantified"] and (
                repeats_more_than_once or frames[-1]["quantified_run"] >= 2
            ):
                return False
            frames[-1]["repeat"] = True
            frames[-1]["quantified_run"] += 1
            frames[-1]["last_quantified"] = True
            frames[-1]["follows_quantified"] = False
            last_group = None
            previous_quantifier = True
            index += 1
            continue
        if character == "{":
            match = BRACED_REPEAT_RE.match(pattern, index)
            if match is not None:
                lower = int(match.group(1))
                upper_text = match.group(2)
                upper = lower if upper_text is None else (None if upper_text == "" else int(upper_text))
                if lower > MAX_REGEX_REPEAT or (upper is not None and upper > MAX_REGEX_REPEAT):
                    return False
                if (upper is None or upper > 1) and last_group is not None and any(last_group):
                    return False
                repeats_more_than_once = upper is None or upper > 1
                if frames[-1]["follows_quantified"] and (
                    repeats_more_than_once or frames[-1]["quantified_run"] >= 2
                ):
                    return False
                frames[-1]["repeat"] = True
                frames[-1]["quantified_run"] += 1
                frames[-1]["last_quantified"] = True
                frames[-1]["follows_quantified"] = False
                last_group = None
                previous_quantifier = True
                index = match.end()
                continue
        begin_atom()
        last_group = None
        previous_quantifier = False
        index += 1

    if escaped or in_character_class or len(frames) != 1:
        return False
    try:
        re.compile(pattern, re.IGNORECASE)
    except re.error:
        return False
    return True


def bounded_intent_span(pattern: str, prompt: str) -> tuple[int, int] | None:
    required = ("SIGALRM", "ITIMER_REAL", "getitimer", "setitimer")
    if not all(hasattr(signal, name) for name in required):
        return None

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = (0.0, 0.0)
    handler_installed = False
    started = time.monotonic()
    try:
        signal.signal(signal.SIGALRM, raise_intent_regex_timeout)
        handler_installed = True
        previous_timer = signal.setitimer(signal.ITIMER_REAL, REGEX_TIMEOUT_SECONDS)
        match = re.search(pattern, prompt, re.IGNORECASE)
        return match.span() if match is not None else None
    except (IntentRegexTimeout, OSError, re.error, ValueError):
        return None
    finally:
        if handler_installed:
            try:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, previous_handler)
                delay, interval = previous_timer
                if delay > 0:
                    elapsed = time.monotonic() - started
                    signal.setitimer(signal.ITIMER_REAL, max(0.000001, delay - elapsed), interval)
            except (OSError, ValueError):
                pass


def bounded_intent_search(pattern: str, prompt: str) -> bool:
    return bounded_intent_span(pattern, prompt) is not None


def matches_intent(prompt: str, patterns: list) -> bool:
    bounded_prompt = prompt[:MAX_INTENT_PROMPT_CHARS]
    for pattern in patterns:
        if not isinstance(pattern, str) or not is_safe_intent_pattern(pattern):
            continue
        if bounded_intent_search(pattern, bounded_prompt):
            return True
    return False


def exclusion_spans(prompt: str, patterns: list) -> list[tuple[int, int]]:
    bounded_prompt = prompt[:MAX_INTENT_PROMPT_CHARS]
    spans: set[tuple[int, int]] = set()
    for pattern in patterns:
        if not isinstance(pattern, str) or not is_safe_intent_pattern(pattern):
            continue
        span = bounded_intent_span(pattern, bounded_prompt)
        if span is not None:
            excluded_text = bounded_prompt[span[0] : span[1]]
            opt_out = AFFIRMATIVE_OPT_OUT_RE.search(excluded_text)
            direct_pattern = any(
                marker in pattern
                for marker in ("(?:do not|", "skip(?:", "avoid(?:", "refrain(?:")
            )
            if (
                opt_out is not None
                and direct_pattern
                and NESTED_OPT_OUT_NEGATION_RE.match(
                    excluded_text[opt_out.end() :]
                )
                is None
            ):
                continue
            spans.add(span)
    return sorted(spans)


def prompt_scopes(prompt: str) -> list[str]:
    pending = [
        scope.strip()
        for scope in CLAUSE_SPLIT_RE.split(prompt)
        if scope.strip()
    ][:MAX_PROMPT_SCOPES]
    scopes: list[str] = []
    while pending and len(scopes) < MAX_PROMPT_SCOPES:
        candidate = pending.pop(0)
        split = False
        for separator in BARE_COORDINATOR_RE.finditer(candidate):
            prefix = candidate[: separator.start()].strip()
            remainder = candidate[separator.end() :].strip()
            if not prefix or not remainder:
                continue
            if (
                DIRECT_NEGATION_SIGNAL_RE.search(prefix) is None
                and DIRECT_NEGATION_SIGNAL_RE.search(remainder) is None
                and CANCELLATION_CLAUSE_RE.search(prefix) is None
            ):
                continue
            if len(scopes) + len(pending) + 2 > MAX_PROMPT_SCOPES:
                break
            pending[0:0] = [prefix, remainder]
            split = True
            break
        if not split:
            scopes.append(candidate)
    return scopes[:MAX_PROMPT_SCOPES]


def matches_prompt_triggers(prompt: str, prompt_triggers: dict) -> bool:
    normalized = prompt.translate(APOSTROPHE_TRANSLATION)[:MAX_INTENT_PROMPT_CHARS]
    exclusions = prompt_triggers.get("excludePatterns") or []
    keywords = prompt_triggers.get("keywords") or []
    intents = prompt_triggers.get("intentPatterns") or []
    pending = prompt_scopes(normalized)
    for index in range(len(pending) - 1, -1, -1):
        if (
            CANCELLATION_CLAUSE_RE.search(pending[index]) is not None
            or ANAPHORIC_CANCELLATION_CLAUSE_RE.search(pending[index]) is not None
        ):
            pending = pending[index + 1 :]
            break
    seen: set[str] = set()

    while pending and len(seen) < MAX_PROMPT_SCOPES:
        candidate = pending.pop(0)
        if candidate in seen:
            continue
        seen.add(candidate)
        if REJECTED_META_CLAUSE_RE.search(candidate) is not None:
            continue

        excluded_spans = exclusion_spans(candidate, exclusions)
        if not excluded_spans:
            if matches_keywords(candidate.lower(), keywords) or matches_intent(candidate, intents):
                return True
            continue

        if any(
            NON_RESUMABLE_EXCLUSION_RE.search(candidate[start:end]) is not None
            or RESUMABLE_EXCLUSION_RE.search(candidate[start:end]) is None
            for start, end in excluded_spans
        ):
            continue

        for start, end in excluded_spans:
            prefix = candidate[:start]
            if start > 0 and (
                candidate[start] in ".!?;\n"
                or LOGICAL_CLAUSE_SEPARATOR_RE.match(candidate, start) is not None
            ):
                prefix = prefix.rstrip()
            else:
                separator = TRAILING_CLAUSE_SEPARATOR_RE.search(prefix)
                prefix = prefix[: separator.start()].rstrip() if separator else ""
            if prefix and prefix not in seen:
                pending.append(prefix)
            remainder = LEADING_CLAUSE_SEPARATOR_RE.sub("", candidate[end:], count=1)
            if remainder and remainder not in seen:
                pending.append(remainder)

    return False


def matches_paths(prompt_paths: list[str], patterns: list, exclusions: list) -> bool:
    for candidate in prompt_paths:
        if any(fnmatch.fnmatch(candidate, item) for item in exclusions if isinstance(item, str)):
            continue
        if any(fnmatch.fnmatch(candidate, item) for item in patterns if isinstance(item, str)):
            return True
    return False


def match_skills(prompt: str, entries: dict) -> list[str]:
    prompt_paths = PATH_TOKEN_RE.findall(prompt)
    matched: list[str] = []

    for name, config in entries.items():
        if not isinstance(config, dict):
            continue
        prompt_triggers = config.get("promptTriggers") or {}
        file_triggers = config.get("fileTriggers") or {}
        if matches_prompt_triggers(prompt, prompt_triggers):
            matched.append(name)
            continue
        patterns = file_triggers.get("pathPatterns") or []
        if patterns and matches_paths(
            prompt_paths,
            patterns,
            file_triggers.get("pathExclusions") or [],
        ):
            matched.append(name)

    rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(
        matched,
        key=lambda name: (rank.get((entries[name] or {}).get("priority", "medium"), 1), name),
    )


def render(matched: list[str]) -> str:
    if not matched:
        return ""
    tail = "Invoke the relevant one before improvising."
    names: list[str] = []
    for name in matched:
        if len(names) >= MAX_NAMED_SKILLS:
            break
        if not isinstance(name, str) or not SKILL_NAME_RE.fullmatch(name):
            continue
        candidate = [*names, name]
        block = f"Skills matching this request: {', '.join(candidate)}. {tail}"
        if len(block) <= MAX_OUTPUT_CHARS:
            names = candidate
    if not names:
        return ""
    return f"Skills matching this request: {', '.join(names)}. {tail}"


def main() -> int:
    if os.environ.get("AI_SKILLS_ACTIVATION_OFF"):
        return 0
    prompt = read_prompt()
    if not prompt:
        return 0
    block = render(select(prompt, registry(), available_skills()))
    if block:
        sys.stdout.write(block + "\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        raise SystemExit(0)
