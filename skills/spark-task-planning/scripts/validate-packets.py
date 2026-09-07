#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import stat
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


FIELDS = (
    "Readiness",
    "Objective",
    "Why",
    "Scope",
    "Starting point",
    "Decisions already made",
    "Decision authority",
    "Contract",
    "Change required",
    "Invariants",
    "Non-goals",
    "Acceptance",
    "Verify",
    "Escalate, do not assume, if",
    "Handoff",
)
OUTCOMES = ("READY", "BLOCKED_BY_SPEC", "NO_CHANGE_NEEDED")
MAX_PACKET_BYTES = 8 * 1024 * 1024
MAX_DIRECTORY_ENTRIES = 16_384
MAX_DIRECTORY_PACKET_FILES = 4_096
MAX_DIRECTORY_DEPTH = 32
MAX_DIRECTORY_PACKET_BYTES = 64 * 1024 * 1024
PACKET_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
)
OBJECT_PATTERN = r"(?:[0-9a-f]{40}|[0-9a-f]{64})"
OBJECT_VALUE_RE = re.compile(
    rf"^\s*(?:[-*]\s+)?`?{OBJECT_PATTERN}`?\s*[.]?\s*$"
)
PREVIOUS_LINE_REF_RE = re.compile(
    r"^\s*(?:[-*]\s+)?`?"
    r"(?:refs/[A-Za-z0-9._/-]+|(?:origin|upstream)/[A-Za-z0-9._/-]+)"
    r"`?\s*[,:;]?\s*$"
)
CANONICAL_OBJECT_LABEL_RE = re.compile(
    r"^\s*(?:[-*]\s+)?(?:\*\*)?"
    r"(?:evidence\s+checked\s+at|base\s+(?:commit|ref)(?:\s+or\s+ref)?)"
    r"(?:\*\*)?\s*:\s*",
    re.IGNORECASE,
)
EXPLICIT_REF_OBJECT_RE = re.compile(
    r"^\s*(?:[-*]\s+)?`?"
    r"(?:refs/[A-Za-z0-9._/-]+|(?:origin|upstream)/[A-Za-z0-9._/-]+)"
    rf"`?\s*(?:at|is|=|:|->)\s*`?{OBJECT_PATTERN}`?\s*[.]?\s*$",
    re.IGNORECASE,
)
PREVIOUS_LINE_CANONICAL_OBJECT_RE = re.compile(
    r"^\s*(?:[-*]\s+)?(?:\*\*)?"
    r"(?:evidence\s+checked\s+at|base\s+(?:commit|ref)(?:\s+or\s+ref)?)"
    r"(?:\*\*)?\s*:\s*`?\s*$",
    re.IGNORECASE,
)
OUTCOME_RE = re.compile(
    r"(?<![A-Z_])(" + "|".join(OUTCOMES) + r")(?![A-Z_])"
)
STATUS_RE = re.compile(
    r"(?im)^\s*(?:-\s*)?packet\s+status:\s*`?("
    + "|".join(OUTCOMES)
    + r")`?\s*[.]?\s*$"
)
EXPLICIT_PACKET_STATUS_RE = re.compile(
    r"(?im)^\s*(?:-\s*)?packet\s+status:\s*`?("
    + "|".join(OUTCOMES)
    + r")`?\s*[.]?\s*$"
)
BARE_OUTCOME_RE = re.compile(
    r"^\s*`?(" + "|".join(OUTCOMES) + r")`?\s*[.]?\s*$"
)
WORKING_DIRECTORY_RE = re.compile(
    r"\b(?:cd|cwd)\s+`?/|\brun\s+from\s+`?/|"
    r"\bfrom\s+cwd\s+`?/|\bworking\s+directory\s*:\s*`?/|"
    r"(?:^|\s)--cwd(?:=|\s+)`?/",
    re.IGNORECASE,
)
GIT_C_WORKING_DIRECTORY_RE = re.compile(r"\bgit\s+-C\s+`?/")
NPM_PREFIX_WORKING_DIRECTORY_RE = re.compile(
    r"\bnpm\s+--prefix(?:=|\s+)`?/",
    re.IGNORECASE,
)
NEGATING_PREFIX_RE = re.compile(
    r"(?:\bdo\s+not|\bdon['’]t|\bnever|\bshould\s+not|\bmust\s+not|"
    r"\bcannot|\bcan['’]t|\bunable\s+to|\b(?:forbidden|prohibited)\s+to)"
    r"\s+(?:\w+\s+){0,3}$|\bno\s+need\s+to\s*$|"
    r"\bneed\s+not\s*$|\bnot\s+necessary\s+to\s*$|"
    r"\bno\s+(?:action|step|command|check)\s+"
    r"(?:needs?|requires?|uses?)\s+(?:\w+\s+){0,3}$",
    re.IGNORECASE,
)
ABSOLUTE_EXECUTION_ROOT_RE = re.compile(
    r"^\s*(?:[-*]\s+)?`?(?P<path>/[A-Za-z0-9._+-][^\s`;,)]*)`?"
    r"(?=\s|[.,;:]|$)"
)
HISTORICAL_PREFIX_RE = re.compile(
    r"(?:\b(?:old|stale|historical|obsolete|removed)\s+"
    r"(?:documentation|docs?|instructions?)\s+(?:says?|said)\s+|"
    r"\b(?:the\s+)?(?:documentation|docs?|instructions?|readme|file)\s+"
    r"(?:says?|said|mentions?|states?)\s+|"
    r"\b(?:example|sample|log)\s*:\s*)$",
    re.IGNORECASE,
)
TASK_HEADING_RE = re.compile(
    r"^#{1,6}\s+(?:Task:\s*)?`?([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)`?\b"
)
PACKET_MARKER_RE = re.compile(
    r"^#{1,6}\s+Qwen(?:3-Coder-Next)?(?: readiness| task)? packet(?:\s+-.*)?$",
    re.IGNORECASE,
)
BOLD_PACKET_MARKER_RE = re.compile(
    r"^\*\*Qwen(?:3-Coder-Next)?(?: readiness| task)? packet(?:\s+-.*?)?\*\*$",
    re.IGNORECASE,
)


@dataclass
class DirectoryBudget:
    entries: int = 0
    markdown_files: int = 0
    markdown_bytes: int = 0
NOT_APPLICABLE_EVIDENCE_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s+)?(?:evidence checked at|base(?: commit| ref)?)\s*:\s*"
    r"not applicable\s+-\s+\S.*$"
)
NOT_APPLICABLE_PREFIX_RE = re.compile(r"^not applicable\b", re.IGNORECASE)
VALID_NOT_APPLICABLE_RE = re.compile(r"^not applicable\s+-\s+\S.*", re.IGNORECASE)
EMPTY_LOCAL_INPUT_MANIFEST_RE = re.compile(
    r"^none\s+-\s+no local or ignored files are consumed[.]?$",
    re.IGNORECASE,
)
LOCAL_INPUT_ENTRY_RE = re.compile(
    r"^\s*[-*]\s+(?:`(?P<quoted_path>/[^`\n]+)`|(?P<plain_path>/[A-Za-z0-9._+-][^\s|]*))\s*\|\s*"
    r"type:\s*regular\s+file\s*\|\s*bytes:\s*[0-9]+\s*\|\s*"
    r"sha256:\s*(?P<digest>[0-9a-f]{64})\s*[.]?\s*$",
    re.IGNORECASE,
)
HTML_TYPE_1_RE = re.compile(
    r"<(?P<tag>pre|script|style|textarea)(?:\s|>|$)",
    re.IGNORECASE,
)
HTML_TYPE_6_RE = re.compile(
    r"</?(?:address|article|aside|blockquote|body|caption|center|colgroup|dd|details|"
    r"dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frameset|h[1-6]|head|"
    r"header|html|iframe|legend|li|main|menu|nav|noframes|ol|optgroup|option|p|pre|"
    r"script|search|section|style|summary|table|tbody|td|textarea|tfoot|th|thead|title|"
    r"tr|ul)(?=\s|/?>|$)",
    re.IGNORECASE,
)
HTML_TYPE_7_RE = re.compile(
    r"(?:"
    r"<[A-Za-z][A-Za-z0-9-]*"
    r"(?:\s+[A-Za-z_:][A-Za-z0-9_.:-]*"
    r"(?:\s*=\s*(?:[^\s\"'=<>`]+|'[^']*'|\"[^\"]*\"))?)*\s*/?>"
    r"|</[A-Za-z][A-Za-z0-9-]*\s*>"
    r")\s*$"
)
HIDDEN_HTML_CONTAINER_RE = re.compile(
    r"<(?P<tag>[A-Za-z][A-Za-z0-9-]*)\b[^>]*\bhidden\b(?:\s*=\s*"
    r"(?:[^\s\"'=<>`]+|'[^']*'|\"[^\"]*\"))?[^>]*>",
    re.IGNORECASE,
)
VAGUE_CONTRACT_VALUE_RE = re.compile(
    r"^(?:tbd|todo|unknown|pending|placeholder|value|not specified)\b",
    re.IGNORECASE,
)
CRITICAL_SUBFIELDS = {
    "Readiness": ("Revalidate when",),
    "Starting point": (
        "Repository inventory",
        "Canonical root and execution working directory",
        "Worktree and collision state",
        "Exact read set",
        "Exact write set",
    ),
    "Contract": (
        "Local or ignored input manifest",
        "Input provenance and preflight",
    ),
    "Acceptance": (
        "Normal case",
        "Boundary or failure case",
        "Compatibility case",
        "Security or concurrency case",
    ),
}


def field_info(line: str) -> tuple[str, str, str] | None:
    matches = (
        ("embedded bullet", re.match(r"^\s{0,3}-\s+\*\*([^*]+?):\*\*\s*(.*)$", line)),
        ("standalone label", re.match(r"^\*\*([^*]+?)\*\*\s*$", line)),
        ("standalone heading", re.match(r"^##\s+(.+?)\s*$", line)),
    )
    for rendering, match in matches:
        if match is None:
            continue
        label = match.group(1).strip()
        if label == "Acceptance criteria":
            label = "Acceptance"
        if label in FIELDS:
            inline = match.group(2).strip() if match.lastindex == 2 else ""
            return label, rendering, inline
    return None


def field_label(line: str) -> str | None:
    info = field_info(line)
    return info[0] if info else None


def field_inline_value(line: str) -> str:
    info = field_info(line)
    return info[2] if info else ""


def visible_line_indexes(lines: list[str]) -> list[int]:
    indexes: list[int] = []
    fence_character: str | None = None
    fence_length = 0
    html_end: re.Pattern[str] | None = None
    html_ends_at_blank = False
    paragraph_open = False
    for index, line in enumerate(lines):
        if html_end is not None:
            if html_end.search(line):
                html_end = None
            continue
        if html_ends_at_blank:
            if not line.strip():
                html_ends_at_blank = False
            continue
        fence = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
        if fence is not None and fence.group(1).startswith("`") and "`" in fence.group(2):
            fence = None
        if fence_character is not None:
            closing_fence = re.match(r"^\s{0,3}(`{3,}|~{3,})[ \t]*$", line)
            if (
                closing_fence
                and closing_fence.group(1)[0] == fence_character
                and len(closing_fence.group(1)) >= fence_length
            ):
                fence_character = None
                fence_length = 0
            continue
        if fence:
            marker = fence.group(1)
            fence_character = marker[0]
            fence_length = len(marker)
            paragraph_open = False
            continue
        if line.startswith("\t") or line.startswith("    "):
            continue

        indent = len(line) - len(line.lstrip(" "))
        html_line = line.lstrip(" ") if indent <= 3 else ""
        type_1 = HTML_TYPE_1_RE.match(html_line)
        if type_1 is not None:
            closing = re.compile(
                rf"</{re.escape(type_1.group('tag'))}\s*>",
                re.IGNORECASE,
            )
            if closing.search(html_line[type_1.end() :]) is None:
                html_end = closing
            paragraph_open = False
            continue

        hidden_tag = HIDDEN_HTML_CONTAINER_RE.match(html_line)
        if hidden_tag is not None:
            closing = re.compile(
                rf"</{re.escape(hidden_tag.group('tag'))}\s*>",
                re.IGNORECASE,
            )
            if closing.search(html_line[hidden_tag.end() :]) is None:
                html_end = closing
            paragraph_open = False
            continue

        token_ended_html = (
            ("<!--", "-->"),
            ("<?", r"\?>"),
            ("<![CDATA[", r"\]\]>"),
        )
        matched_html = False
        for opening, ending in token_ended_html:
            if not html_line.startswith(opening):
                continue
            end_pattern = re.compile(ending)
            if end_pattern.search(html_line[len(opening) :]) is None:
                html_end = end_pattern
            paragraph_open = False
            matched_html = True
            break
        if matched_html:
            continue

        if re.match(r"^<![A-Z]", html_line):
            end_pattern = re.compile(r">")
            if end_pattern.search(html_line[2:]) is None:
                html_end = end_pattern
            paragraph_open = False
            continue

        if HTML_TYPE_6_RE.match(html_line):
            html_ends_at_blank = True
            paragraph_open = False
            continue
        if not paragraph_open and HTML_TYPE_7_RE.fullmatch(html_line):
            html_ends_at_blank = True
            paragraph_open = False
            continue

        indexes.append(index)
        if not line.strip():
            paragraph_open = False
        elif re.match(r"^\s{0,3}#{1,6}(?:\s|$)", line):
            paragraph_open = False
        else:
            paragraph_open = True
    return indexes


def visible_text(text: str) -> str:
    lines = text.splitlines()
    return "\n".join(lines[index] for index in visible_line_indexes(lines))


def structural_fields(lines: list[str]) -> list[tuple[int, str, str]]:
    fields: list[tuple[int, str, str]] = []
    for index in visible_line_indexes(lines):
        line = lines[index]
        info = field_info(line)
        if info:
            fields.append((index, info[0], info[1]))
    return fields


def packet_marker_indexes(lines: list[str]) -> list[int]:
    return [
        index
        for index in visible_line_indexes(lines)
        if PACKET_MARKER_RE.match(lines[index].strip())
        or BOLD_PACKET_MARKER_RE.match(lines[index].strip())
    ]


def task_heading_indexes(lines: list[str]) -> list[int]:
    return [
        index
        for index in visible_line_indexes(lines)
        if TASK_HEADING_RE.match(lines[index])
    ]


def field_value(lines: list[str], start: int, stop: int) -> str:
    body = lines[start + 1 : stop]
    info = field_info(lines[start])
    if info is not None and info[1] == "embedded bullet":
        marker = re.match(r"^(\s*)-\s+", lines[start])
        content_indent = len(marker.group(1)) + 2 if marker else 0
        prefix = " " * content_indent
        body = [line[len(prefix) :] if line.startswith(prefix) else line for line in body]
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    return "\n".join(
        filter(
            None,
            (
                field_inline_value(lines[start]),
                "\n".join(body),
            ),
        )
    )


def normalized_field_value(value: str) -> str:
    return re.sub(r"^\s*[-*]\s+", "", value, count=1)


def has_subfield(text: str, label: str) -> bool:
    return bool(
        re.search(
            rf"(?im)^\s*(?:[-*]\s+)?(?:\*\*)?{re.escape(label)}(?:\*\*)?\s*:",
            visible_text(text),
        )
    )


def subfield_count(text: str, label: str) -> int:
    return len(
        re.findall(
            rf"(?im)^\s*(?:[-*]\s+)?(?:\*\*)?{re.escape(label)}(?:\*\*)?\s*:",
            visible_text(text),
        )
    )


def subfield_has_content(text: str, label: str) -> bool:
    lines = visible_text(text).splitlines()
    pattern = re.compile(
        rf"^(?P<indent>\s*)(?:[-*]\s+)?(?:\*\*)?{re.escape(label)}"
        r"(?:\*\*)?\s*:(?:\*\*)?\s*(?P<value>.*)$",
        re.IGNORECASE,
    )
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if match is None:
            continue
        if match.group("value").strip():
            return True
        base_indent = len(match.group("indent").expandtabs(4))
        for continuation in lines[index + 1 :]:
            if not continuation.strip():
                continue
            continuation_indent = len(continuation) - len(continuation.lstrip())
            if continuation_indent <= base_indent:
                break
            if re.sub(r"^\s*[-*]\s*", "", continuation).strip():
                return True
        return False
    return False


def subfield_value(text: str, label: str) -> str:
    lines = visible_text(text).splitlines()
    pattern = re.compile(
        rf"^(?P<indent>\s*)(?:[-*]\s+)?(?:\*\*)?{re.escape(label)}"
        r"(?:\*\*)?\s*:(?:\*\*)?\s*(?P<value>.*)$",
        re.IGNORECASE,
    )
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if match is None:
            continue
        values = [match.group("value").strip()]
        base_indent = len(match.group("indent").expandtabs(4))
        for continuation in lines[index + 1 :]:
            if not continuation.strip():
                continue
            continuation_indent = len(continuation) - len(continuation.lstrip())
            if continuation_indent <= base_indent:
                break
            values.append(continuation.strip())
        return "\n".join(value for value in values if value)
    return ""


def subfield_is_not_applicable(text: str, label: str) -> bool:
    return bool(
        re.search(
            rf"(?im)^\s*(?:[-*]\s+)?(?:\*\*)?{re.escape(label)}(?:\*\*)?\s*:"
            r"\s*not applicable\s+-\s+\S",
            visible_text(text),
        )
    )


def valid_local_input_manifest(value: str, allow_not_applicable: bool) -> bool:
    visible = visible_text(value).strip()
    if EMPTY_LOCAL_INPUT_MANIFEST_RE.fullmatch(visible):
        return True
    if allow_not_applicable and VALID_NOT_APPLICABLE_RE.fullmatch(visible):
        return True
    lines = [line for line in visible.splitlines() if line.strip()]
    if not lines:
        return False
    paths: set[str] = set()
    for line in lines:
        match = LOCAL_INPUT_ENTRY_RE.fullmatch(line)
        if match is None or match.group("digest") != match.group("digest").lower():
            return False
        path = match.group("quoted_path") or match.group("plain_path")
        parts = path.split("/")
        if (
            path == "/"
            or "//" in path
            or path.endswith("/")
            or any(part in (".", "..") for part in parts)
            or path in paths
        ):
            return False
        paths.add(path)
    return True


def task_id(lines: list[str], start: int) -> str:
    for index in reversed(task_heading_indexes(lines)):
        if index > start:
            continue
        match = TASK_HEADING_RE.match(lines[index])
        if match:
            return match.group(1)
    return f"line-{start + 1}"


def has_commit_evidence(text: str) -> bool:
    lines = visible_text(text).splitlines()
    for index, line in enumerate(lines):
        canonical_label = CANONICAL_OBJECT_LABEL_RE.match(line)
        if canonical_label is not None and OBJECT_VALUE_RE.fullmatch(
            line[canonical_label.end() :]
        ):
            return True
        if EXPLICIT_REF_OBJECT_RE.fullmatch(line):
            return True
        if index == 0 or not OBJECT_VALUE_RE.fullmatch(line):
            continue
        previous = lines[index - 1]
        if (
            PREVIOUS_LINE_REF_RE.fullmatch(previous)
            or PREVIOUS_LINE_CANONICAL_OBJECT_RE.fullmatch(previous)
        ):
            return True
    return False


def has_working_directory(text: str) -> bool:
    text = visible_text(text)
    for pattern in (
        WORKING_DIRECTORY_RE,
        GIT_C_WORKING_DIRECTORY_RE,
        NPM_PREFIX_WORKING_DIRECTORY_RE,
    ):
        for match in pattern.finditer(text):
            line_start = text.rfind("\n", 0, match.start()) + 1
            prefix = text[line_start : match.start()]
            if not NEGATING_PREFIX_RE.search(prefix) and not HISTORICAL_PREFIX_RE.search(prefix):
                return True
    return False


def has_absolute_execution_root(text: str) -> bool:
    match = ABSOLUTE_EXECUTION_ROOT_RE.match(visible_text(text))
    if match is None:
        return False
    return all(part not in ("", ".", "..") for part in match.group("path").split("/")[1:])


def numbered_items(text: str) -> list[str]:
    items: list[list[str]] = []
    current: list[str] | None = None
    for line in visible_text(text).splitlines():
        if re.match(r"^\s*\d+[.)]\s+", line):
            if current is not None:
                items.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        items.append(current)
    return ["\n".join(item) for item in items]


def numbered_verify_items(text: str) -> list[str]:
    return numbered_items(text)


def has_inline_numbered_continuation(item: str) -> bool:
    lines = visible_text(item).splitlines()
    if not lines:
        return False
    lines[0] = re.sub(r"^\s*\d+[.)]\s+", "", lines[0], count=1)
    return any(re.search(r"(?:^|\s)\d+[.)]\s+\S", line) for line in lines)


def has_packet_candidate(text: str) -> bool:
    lines = text.splitlines()
    visible = visible_line_indexes(lines)
    if packet_marker_indexes(lines):
        return True
    if any(
        re.match(r"^#{1,6}\s+Task:", lines[index])
        and TASK_HEADING_RE.match(lines[index])
        for index in visible
    ):
        return True
    labels = {label for _, label, _ in structural_fields(lines)}
    return {"Readiness", "Objective", "Decision authority", "Handoff"}.issubset(labels)


def validate_text(text: str, source: str = "<input>") -> tuple[list[str], Counter[str]]:
    lines = text.splitlines()
    fields = structural_fields(lines)
    starts = [index for index, label, _ in fields if label == "Readiness"]
    findings: list[str] = []
    outcomes: Counter[str] = Counter()
    markers = packet_marker_indexes(lines)
    task_headings = task_heading_indexes(lines)
    standalone_task_headings = [
        heading
        for heading in task_headings
        if re.match(r"^#{1,6}\s+Task:", lines[heading])
    ]
    if not fields and not markers and not task_headings:
        return findings, outcomes
    for heading in standalone_task_headings:
        boundary = next(
            (candidate for candidate in task_headings if candidate > heading),
            len(lines),
        )
        owned_starts = [start for start in starts if heading < start < boundary]
        if len(owned_starts) != 1:
            heading_id = TASK_HEADING_RE.match(lines[heading]).group(1)
            findings.append(
                f"{source}:{heading + 1} {heading_id}: standalone task heading must own "
                f"exactly one Readiness field before the next task; found {len(owned_starts)}"
            )
    for marker_position, marker in enumerate(markers):
        boundaries = [
            index
            for index in (
                markers[marker_position + 1] if marker_position + 1 < len(markers) else None,
                next((index for index in task_headings if index > marker), None),
            )
            if index is not None
        ]
        boundary = min(boundaries, default=len(lines))
        if not any(marker < start < boundary for start in starts):
            findings.append(
                f"{source}:{marker + 1}: packet marker has no Readiness field before the next packet or task"
            )
    if not starts:
        if not findings:
            findings.append(f"{source}: no packet Readiness field found")
        return findings, outcomes

    identities = [task_id(lines, start) for start in starts]
    duplicate_identities = {
        identity for identity, count in Counter(identities).items() if count > 1
    }
    duplicate_identity_seen: set[str] = set()

    for ordinal, start in enumerate(starts):
        identity = task_id(lines, start)
        if identity in duplicate_identities and identity not in duplicate_identity_seen:
            findings.append(
                f"{source}:{start + 1} {identity}: duplicate packet task ID"
            )
            duplicate_identity_seen.add(identity)
        previous_start = starts[ordinal - 1] if ordinal else -1
        owns_task_heading = any(
            previous_start < heading < start for heading in task_headings
        )
        owner_heading = max(
            (heading for heading in task_headings if previous_start < heading < start),
            default=-1,
        )
        if not owns_task_heading:
            findings.append(
                f"{source}:{start + 1} {identity}: no task ID heading belongs to this packet"
            )
        boundaries = [
            candidate
            for candidate in (
                starts[ordinal + 1] if ordinal + 1 < len(starts) else None,
                next((index for index in task_headings if index > start), None),
                next((index for index in markers if index > start), None),
            )
            if candidate is not None
        ]
        stop = min(boundaries, default=len(lines))
        labels = [entry for entry in fields if start <= entry[0] < stop]
        handoff = next((index for index, label, _ in labels if label == "Handoff"), None)
        if handoff is not None and labels and labels[0][2] == "embedded bullet":
            embedded_boundaries = [
                index
                for index in range(handoff + 1, stop)
                if field_info(lines[index]) is not None
                or re.match(r"^#{1,6}\s+", lines[index])
            ]
            if embedded_boundaries:
                stop = embedded_boundaries[0]
                labels = [entry for entry in labels if start <= entry[0] < stop]
                handoff = next(
                    (index for index, label, _ in labels if label == "Handoff"),
                    None,
                )
        if handoff is None:
            findings.append(f"{source}:{start + 1} {identity}: missing Handoff field")
            continue
        observed = tuple(label for _, label, _ in labels)
        if observed != FIELDS:
            findings.append(
                f"{source}:{start + 1} {identity}: expected fields {FIELDS}, found {observed}"
            )
        renderings = sorted({rendering for _, _, rendering in labels})
        if len(renderings) != 1:
            findings.append(
                f"{source}:{start + 1} {identity}: mixed packet renderings {renderings}"
            )
        elif renderings[0] in {"embedded bullet", "standalone label"}:
            owned_markers = [
                marker for marker in markers if owner_heading < marker < start
            ]
            if len(owned_markers) != 1:
                findings.append(
                    f"{source}:{start + 1} {identity}: {renderings[0]} packet must have "
                    "exactly one preceding owned Qwen packet marker"
                )

        next_task = next(
            (
                index
                for index in range(handoff + 1, stop)
                if TASK_HEADING_RE.match(lines[index])
            ),
            stop,
        )
        values: dict[str, str] = {}
        for position, (index, label, _) in enumerate(labels):
            field_stop = labels[position + 1][0] if position + 1 < len(labels) else next_task
            value = field_value(lines, index, field_stop)
            values[label] = value
            normalized_value = normalized_field_value(value)
            if not value:
                findings.append(f"{source}:{index + 1} {identity}: empty {label} field")
            elif NOT_APPLICABLE_PREFIX_RE.match(
                normalized_value
            ) and not VALID_NOT_APPLICABLE_RE.match(normalized_value):
                findings.append(
                    f"{source}:{index + 1} {identity}: {label} must use "
                    "'Not applicable - <reason>' with a nonblank reason"
                )

        next_field = labels[1][0] if len(labels) > 1 else handoff + 1
        readiness_text = field_value(lines, start, next_field)
        status_text = visible_text(readiness_text)
        packet_begin = owner_heading + 1 if owner_heading >= 0 else previous_start + 1
        shadowed_statuses = [
            (f"line {index + 1}", match.group(1))
            for index in visible_line_indexes(lines)
            if packet_begin <= index < stop and not start <= index < next_field
            for match in EXPLICIT_PACKET_STATUS_RE.finditer(lines[index])
        ]
        shadowed_statuses.extend(
            (field, match.group(1))
            for index, field, rendering in labels
            if field != "Readiness" and rendering == "embedded bullet"
            for match in EXPLICIT_PACKET_STATUS_RE.finditer(field_inline_value(lines[index]))
        )
        if shadowed_statuses:
            findings.append(
                f"{source}:{start + 1} {identity}: explicit packet status is allowed "
                f"only in Readiness, found {shadowed_statuses}"
            )
        declaration_matches = list(STATUS_RE.finditer(status_text))
        status_tokens: list[str] = []
        declarations = [match.group(1) for match in declaration_matches]
        first_line = status_text.splitlines()[0] if status_text else ""
        bare_outcomes = [
            match.group(1)
            for line in status_text.splitlines()
            if (match := BARE_OUTCOME_RE.fullmatch(line)) is not None
        ]
        if len(declaration_matches) == 1:
            declaration = declaration_matches[0]
            line_start = status_text.rfind("\n", 0, declaration.start()) + 1
            line_end = status_text.find("\n", declaration.end())
            if line_end == -1:
                line_end = len(status_text)
            status_tokens = OUTCOME_RE.findall(status_text[line_start:line_end])
        elif not declaration_matches:
            status_tokens = OUTCOME_RE.findall(first_line)
        if (
            len(declarations) != 1
            or len(status_tokens) != 1
            or declarations[0] != status_tokens[0]
            or bare_outcomes
        ):
            findings.append(
                f"{source}:{start + 1} {identity}: expected one explicit packet status, "
                f"found declarations={declarations}, status-line tokens={status_tokens}"
            )
            packet_outcome = None
        else:
            packet_outcome = declarations[0]
            outcomes[packet_outcome] += 1

        for field, subfields in CRITICAL_SUBFIELDS.items():
            value = values.get(field, "")
            counts = {label: subfield_count(value, label) for label in subfields}
            missing = [label for label in subfields if counts[label] == 0]
            duplicated = [label for label in subfields if counts[label] > 1]
            empty = [
                label
                for label in subfields
                if has_subfield(value, label) and not subfield_has_content(value, label)
            ]
            if missing:
                field_index = next(
                    (index for index, label, _ in labels if label == field),
                    start,
                )
                findings.append(
                    f"{source}:{field_index + 1} {identity}: {field} is missing critical "
                    f"detail labels {missing}"
                )
            if duplicated:
                field_index = next(
                    (index for index, label, _ in labels if label == field),
                    start,
                )
                findings.append(
                    f"{source}:{field_index + 1} {identity}: {field} has duplicate "
                    f"critical detail labels {duplicated}"
                )
            if empty:
                field_index = next(
                    (index for index, label, _ in labels if label == field),
                    start,
                )
                findings.append(
                    f"{source}:{field_index + 1} {identity}: {field} has empty critical "
                    f"detail labels {empty}"
                )

        contract = values.get("Contract", "")
        manifest = subfield_value(contract, "Local or ignored input manifest")
        provenance = subfield_value(contract, "Input provenance and preflight")
        contract_index = next(
            (index for index, label, _ in labels if label == "Contract"),
            start,
        )
        if manifest and not valid_local_input_manifest(
            manifest,
            allow_not_applicable=packet_outcome == "BLOCKED_BY_SPEC",
        ):
            findings.append(
                f"{source}:{contract_index + 1} {identity}: Local or ignored input "
                "manifest must be the exact empty declaration or line-separated "
                "absolute-path regular-file entries with bytes and lowercase SHA-256"
            )
        if (
            provenance
            and packet_outcome in ("READY", "NO_CHANGE_NEEDED")
            and VAGUE_CONTRACT_VALUE_RE.match(normalized_field_value(provenance))
        ):
            findings.append(
                f"{source}:{contract_index + 1} {identity}: Input provenance and "
                "preflight must be decision-complete, not a placeholder"
            )

        starting_point = values.get("Starting point", "")
        execution_root = subfield_value(
            starting_point,
            "Canonical root and execution working directory",
        )
        if (
            starting_point
            and not has_absolute_execution_root(execution_root)
            and not (
                packet_outcome == "BLOCKED_BY_SPEC"
                and subfield_is_not_applicable(
                    starting_point,
                    "Canonical root and execution working directory",
                )
            )
        ):
            starting_index = next(
                (index for index, label, _ in labels if label == "Starting point"),
                start,
            )
            findings.append(
                f"{source}:{starting_index + 1} {identity}: Starting point does not name "
                "an absolute execution working directory"
            )

        change_body = values.get("Change required", "")
        change_items = numbered_items(change_body)
        if any(has_inline_numbered_continuation(item) for item in change_items):
            change_index = next(
                (index for index, label, _ in labels if label == "Change required"),
                start,
            )
            findings.append(
                f"{source}:{change_index + 1} {identity}: Change required must put "
                "each numbered step on its own line"
            )
        elif change_body and len(change_items) < 2:
            change_index = next(
                (index for index, label, _ in labels if label == "Change required"),
                start,
            )
            findings.append(
                f"{source}:{change_index + 1} {identity}: Change required must use "
                "at least two line-separated numbered steps"
            )

        evidence_text = "\n\n".join((readiness_text, values.get("Starting point", "")))
        has_object = has_commit_evidence(evidence_text)
        has_not_applicable_evidence = bool(NOT_APPLICABLE_EVIDENCE_RE.search(evidence_text))
        if packet_outcome in ("READY", "NO_CHANGE_NEEDED") and not has_object:
            findings.append(
                f"{source}:{start + 1} {identity}: no full commit object ID bound to Readiness or Starting point"
            )
        elif packet_outcome == "BLOCKED_BY_SPEC" and not (
            has_object or has_not_applicable_evidence
        ):
            findings.append(
                f"{source}:{start + 1} {identity}: blocked packet needs a full commit object ID or "
                "an explicit 'Not applicable - <reason>' evidence/base value"
            )

        verify_index = next((index for index, label, _ in labels if label == "Verify"), None)
        verify_body = values.get("Verify", "")
        verify_is_not_applicable = bool(
            VALID_NOT_APPLICABLE_RE.match(normalized_field_value(verify_body))
        )
        names_working_directory = has_working_directory(verify_body)
        if verify_index is not None and verify_body and not names_working_directory:
            if not (verify_is_not_applicable and packet_outcome == "BLOCKED_BY_SPEC"):
                findings.append(
                    f"{source}:{verify_index + 1} {identity}: Verify does not name a working directory"
                )
        if verify_index is not None and not verify_is_not_applicable:
            verify_items = numbered_verify_items(verify_body)
            if not verify_items:
                findings.append(
                    f"{source}:{verify_index + 1} {identity}: Verify must use "
                    "line-separated numbered items"
                )
            elif any(has_inline_numbered_continuation(item) for item in verify_items):
                findings.append(
                    f"{source}:{verify_index + 1} {identity}: Verify must put each "
                    "numbered command on its own line"
                )
            for command_number, command in enumerate(verify_items, start=1):
                if not has_working_directory(command):
                    findings.append(
                        f"{source}:{verify_index + 1} {identity}: Verify command "
                        f"{command_number} does not name a working directory"
                    )
                if not re.search(r"\bexpected\b", visible_text(command), re.IGNORECASE):
                    findings.append(
                        f"{source}:{verify_index + 1} {identity}: Verify command "
                        f"{command_number} does not state its expected result"
                    )
                if not re.search(r"\bproves?\b", visible_text(command), re.IGNORECASE):
                    findings.append(
                        f"{source}:{verify_index + 1} {identity}: Verify command "
                        f"{command_number} does not state its proof claim"
                    )

        handoff_body = visible_text(values.get("Handoff", ""))
        if not (
            re.search(r"\bstarting\b.{0,40}\brevisions?\b", handoff_body, re.IGNORECASE)
            and re.search(r"\bfinal\b.{0,40}\brevisions?\b", handoff_body, re.IGNORECASE)
        ):
            handoff_index = next(
                (index for index, label, _ in labels if label == "Handoff"),
                start,
            )
            findings.append(
                f"{source}:{handoff_index + 1} {identity}: Handoff must report "
                "starting and final revisions"
            )

    return findings, outcomes


def filesystem_identity(item: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        item.st_dev,
        item.st_ino,
        item.st_mode,
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
    )


def validate_packet_file_stat(item: os.stat_result) -> None:
    if not stat.S_ISREG(item.st_mode) or item.st_nlink != 1:
        raise ValueError("packet must be a regular non-symlink file with one link")
    if item.st_size > MAX_PACKET_BYTES:
        raise ValueError(f"packet exceeds the {MAX_PACKET_BYTES}-byte limit")


def read_packet_descriptor(descriptor: int, expected: os.stat_result) -> str:
    if filesystem_identity(os.fstat(descriptor)) != filesystem_identity(expected):
        raise ValueError("packet changed while opening")
    chunks: list[bytes] = []
    remaining = MAX_PACKET_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    if remaining == 0:
        raise ValueError(f"packet exceeds the {MAX_PACKET_BYTES}-byte limit")
    if filesystem_identity(os.fstat(descriptor)) != filesystem_identity(expected):
        raise ValueError("packet changed while reading")
    try:
        return b"".join(chunks).decode("utf-8")
    except UnicodeError as exc:
        raise ValueError(str(exc)) from exc


def read_packet_at(
    directory_descriptor: int,
    name: str,
    path: Path,
    before: os.stat_result,
) -> str:
    validate_packet_file_stat(before)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name,
            PACKET_OPEN_FLAGS,
            dir_fd=directory_descriptor,
        )
        content = read_packet_descriptor(descriptor, before)
        after_path = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        if filesystem_identity(after_path) != filesystem_identity(before):
            raise ValueError("packet changed while reading")
        return content
    except OSError as exc:
        raise ValueError(f"cannot read packet {path}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def bounded_markdown_files(
    root: Path,
    budget: DirectoryBudget | None = None,
) -> list[tuple[Path, str]]:
    root_stat = root.lstat()
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError("directory argument must be a real non-symlink directory")

    discovered: list[tuple[Path, str]] = []
    shared_budget = budget or DirectoryBudget()
    open_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )

    def scan_directory(
        descriptor: int,
        current: Path,
        depth: int,
        expected: os.stat_result,
    ) -> None:
        expected_identity = filesystem_identity(expected)
        if filesystem_identity(os.fstat(descriptor)) != expected_identity:
            raise ValueError(f"directory changed while opening: {current}")
        try:
            with os.scandir(descriptor) as entries:
                for entry in entries:
                    shared_budget.entries += 1
                    if shared_budget.entries > MAX_DIRECTORY_ENTRIES:
                        raise ValueError(
                            f"directory exceeds the {MAX_DIRECTORY_ENTRIES}-entry traversal limit"
                        )
                    entry_path = current / entry.name
                    entry_stat = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(entry_stat.st_mode):
                        child_depth = depth + 1
                        if child_depth > MAX_DIRECTORY_DEPTH:
                            raise ValueError(
                                f"directory exceeds the {MAX_DIRECTORY_DEPTH}-level depth limit"
                            )
                        child_descriptor: int | None = None
                        try:
                            child_descriptor = os.open(
                                entry.name,
                                open_flags,
                                dir_fd=descriptor,
                            )
                            scan_directory(
                                child_descriptor,
                                entry_path,
                                child_depth,
                                entry_stat,
                            )
                            after_child = os.stat(
                                entry.name,
                                dir_fd=descriptor,
                                follow_symlinks=False,
                            )
                            if filesystem_identity(after_child) != filesystem_identity(entry_stat):
                                raise ValueError(
                                    f"directory changed while scanning: {entry_path}"
                                )
                        finally:
                            if child_descriptor is not None:
                                os.close(child_descriptor)
                        continue
                    if not entry.name.endswith(".md"):
                        continue
                    shared_budget.markdown_files += 1
                    if shared_budget.markdown_files > MAX_DIRECTORY_PACKET_FILES:
                        raise ValueError(
                            "directory exceeds the "
                            f"{MAX_DIRECTORY_PACKET_FILES}-Markdown-file limit"
                        )
                    shared_budget.markdown_bytes += entry_stat.st_size
                    if shared_budget.markdown_bytes > MAX_DIRECTORY_PACKET_BYTES:
                        raise ValueError(
                            "directory Markdown exceeds the "
                            f"{MAX_DIRECTORY_PACKET_BYTES}-byte aggregate limit"
                        )
                    discovered.append(
                        (
                            entry_path,
                            read_packet_at(descriptor, entry.name, entry_path, entry_stat),
                        )
                    )
            if filesystem_identity(os.fstat(descriptor)) != expected_identity:
                raise ValueError(f"directory changed while scanning: {current}")
        except OSError as exc:
            raise ValueError(f"cannot scan directory {current}: {exc}") from exc

    descriptor: int | None = None
    try:
        descriptor = os.open(root, open_flags)
        scan_directory(descriptor, root, 0, root_stat)
    except OSError as exc:
        raise ValueError(f"cannot scan directory {root}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)

    return sorted(discovered, key=lambda item: item[0])


def markdown_paths(arguments: list[str]) -> list[tuple[Path, bool, str | None]]:
    paths: list[tuple[Path, bool, str | None]] = []
    directory_budget = DirectoryBudget()
    for argument in arguments:
        path = Path(argument)
        try:
            path_stat = path.lstat()
        except OSError:
            paths.append((path, True, None))
            continue
        if stat.S_ISDIR(path_stat.st_mode):
            for nested, content in bounded_markdown_files(path, directory_budget):
                paths.append((nested, False, content))
        else:
            paths.append((path, True, None))
    return paths


def read_packet_text(path: Path) -> str:
    descriptor: int | None = None
    try:
        before = path.lstat()
        validate_packet_file_stat(before)
        descriptor = os.open(
            path,
            PACKET_OPEN_FLAGS,
        )
        content = read_packet_descriptor(descriptor, before)
        after_path = path.lstat()
        if filesystem_identity(after_path) != filesystem_identity(before):
            raise ValueError("packet changed while reading")
        return content
    except (OSError, UnicodeError) as exc:
        raise ValueError(str(exc)) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate standalone and embedded Qwen3-Coder-Next task packets."
    )
    parser.add_argument("paths", nargs="+", help="Markdown packet files or directories")
    args = parser.parse_args()

    total = Counter()
    findings: list[str] = []
    try:
        paths = markdown_paths(args.paths)
    except ValueError as exc:
        paths = []
        findings.append(f"directory traversal failed: {exc}")
    for path, require_packet, captured_content in paths:
        try:
            content = captured_content if captured_content is not None else read_packet_text(path)
        except ValueError as exc:
            findings.append(f"{path}: cannot read packet: {exc}")
            continue
        if not require_packet and not has_packet_candidate(content):
            continue
        file_findings, outcomes = validate_text(content, str(path))
        findings.extend(file_findings)
        if require_packet and not outcomes:
            findings.append(f"{path}: explicit file contains no visible Qwen task packet")
        total.update(outcomes)

    for finding in findings:
        print(finding, file=sys.stderr)
    packet_count = sum(total.values())
    print(
        f"Validated {packet_count} packet(s): "
        + ", ".join(f"{outcome}={total[outcome]}" for outcome in OUTCOMES)
    )
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
