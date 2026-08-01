from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from .models import Session
from .parser import iter_conversation

MARKDOWN = "markdown"
RAW = "raw"

_SLUG_STRIP = re.compile(r"[^\w\s-]", re.UNICODE)
_SLUG_SPACE = re.compile(r"[\s_]+")

_HEADING = re.compile(r"^(#{1,6})(\s+\S)")
_FENCE_OPEN = re.compile(r"^(`{3,}|~{3,})")
_LIST_ITEM = re.compile(r"^\s*([-*+]|\d+[.)])\s+\S")
_INSIGHT_OPEN = re.compile(r"^`?\s*★\s*Insight[\s─—-]*`?$")
_RULE_ONLY = re.compile(r"^`?\s*[─—-]{5,}\s*`?$")


class ExportError(RuntimeError):
    pass


def _slug(text: str, max_len: int = 40) -> str:
    text = _SLUG_STRIP.sub("", text.strip().lower())
    text = _SLUG_SPACE.sub("-", text).strip("-")
    if len(text) > max_len:
        text = text[:max_len].rstrip("-")
    return text


def default_filename(session: Session, fmt: str) -> str:
    stamp = (session.modified or session.created or datetime.now()).strftime("%Y-%m-%d")
    slug = _slug(session.summary or session.first_prompt) or session.session_id[:8]
    suffix = ".md" if fmt == MARKDOWN else ".jsonl"
    return f"{stamp}-{slug}{suffix}"


def resolve_destination(path_str: str, session: Session, fmt: str) -> Path:
    """Turn user input into a concrete file path.

    A directory (or empty input) gets an auto-generated filename inside it;
    anything with a suffix is used as the filename. Existing files are never
    overwritten — a -1, -2, … suffix is appended instead.
    """
    raw = (path_str or ".").strip() or "."
    path = Path(raw).expanduser()
    if path.is_dir() or raw.endswith("/") or not path.suffix:
        target = path / default_filename(session, fmt)
    else:
        target = path
    parent = target.parent
    if not parent.is_dir():
        raise ExportError(f"directory does not exist: {parent}")
    stem, suffix = target.stem, target.suffix
    counter = 1
    while target.exists():
        target = parent / f"{stem}-{counter}{suffix}"
        counter += 1
    return target


def _min_heading_level(lines: list[str]) -> int:
    """Shallowest ATX heading level outside fenced code blocks (7 if none)."""
    fence: str | None = None
    level = 7
    for line in lines:
        stripped = line.lstrip()
        if fence is None:
            m = _FENCE_OPEN.match(stripped)
            if m:
                fence = m.group(1)[:3]
                continue
            h = _HEADING.match(line)
            if h:
                level = min(level, len(h.group(1)))
        elif stripped.startswith(fence):
            fence = None
    return level


def normalize_markdown(text: str) -> str:
    """Make message text safe to embed under `## You` / `## Claude`.

    - headings are demoted so the shallowest one is `###` (role headings stay
      the top level of the document)
    - bare code fences get a `txt` info string (Pandoc/Quarto prefer one)
    - a list directly after a paragraph line gets a blank line before it,
      otherwise strict parsers glue them together
    - the `★ Insight` marker lines get breathing room on the inside
    """
    lines = text.split("\n")
    shift = max(0, 3 - _min_heading_level(lines))

    out: list[str] = []
    fence: str | None = None
    prev_blank = True
    prev_list = False

    for line in lines:
        stripped = line.lstrip()

        if fence is not None:  # inside a code block — copy verbatim
            out.append(line)
            if stripped.startswith(fence):
                fence = None
            prev_blank = prev_list = False
            continue

        opening = _FENCE_OPEN.match(stripped)
        if opening:
            marker = opening.group(1)
            fence = marker[:3]
            info = stripped[len(marker) :].strip()
            out.append(line.rstrip() + "txt" if not info else line)
            prev_blank = prev_list = False
            continue

        heading = _HEADING.match(line)
        if heading and shift:
            line = "#" * min(6, len(heading.group(1)) + shift) + line[len(heading.group(1)) :]

        is_list = bool(_LIST_ITEM.match(line))
        bare = line.strip()

        if is_list and not prev_blank and not prev_list:
            out.append("")
        elif _RULE_ONLY.match(bare) and not prev_blank:
            out.append("")

        out.append(line)

        if _INSIGHT_OPEN.match(bare):
            out.append("")
            prev_blank, prev_list = True, False
            continue

        prev_blank = not bare
        if is_list:
            prev_list = True
        elif bare and not line[:1].isspace():
            prev_list = False

    return "\n".join(out)


def _front_matter(session: Session) -> str:
    def q(value: object) -> str:
        return json.dumps(str(value), ensure_ascii=False)

    t = session.tokens
    lines = [
        "---",
        f"title: {q(session.summary or session.first_prompt.strip() or session.session_id)}",
        f"session_id: {q(session.session_id)}",
        f"project: {q(session.project_path)}",
    ]
    if session.git_branch:
        lines.append(f"git_branch: {q(session.git_branch)}")
    if session.created:
        lines.append(f"created: {session.created.isoformat(timespec='seconds')}")
    if session.modified:
        lines.append(f"modified: {session.modified.isoformat(timespec='seconds')}")
    lines += [
        f"messages: {session.message_count}",
        "tokens:",
        f"  input: {t.input}",
        f"  output: {t.output}",
        f"  cache_read: {t.cache_read}",
        f"  cache_write: {t.cache_write}",
        f"  total: {t.total}",
        "exported_by: ccsessions",
        "---",
        "",
    ]
    return "\n".join(lines)


def export_markdown(session: Session, dest: Path) -> Path:
    """Write the whole conversation as Markdown with YAML front matter."""
    bullets = {"tool": "⚙", "command": "⌘"}
    try:
        with open(dest, "w", encoding="utf-8") as out:
            out.write(_front_matter(session))
            prev_role = ""
            for role, text in iter_conversation(session.jsonl_path):
                if role in bullets:
                    # keep a run of tool calls as one tight list
                    if prev_role not in bullets:
                        out.write("\n")
                    out.write(f"- {bullets[role]} `{text.replace('`', '')}`\n")
                elif role == "command-output":
                    out.write(f"\n```txt\n{text}\n```\n")
                else:
                    speaker = "You" if role == "user" else "Claude"
                    out.write(f"\n## {speaker}\n\n{normalize_markdown(text)}\n")
                prev_role = role
    except OSError as e:
        raise ExportError(str(e)) from e
    return dest


def export_raw(session: Session, dest: Path) -> Path:
    """Copy the transcript verbatim (full fidelity, including tool results)."""
    if not session.jsonl_path.is_file():
        raise ExportError("transcript file not available on this machine")
    try:
        shutil.copy2(session.jsonl_path, dest)
    except OSError as e:
        raise ExportError(str(e)) from e
    return dest


def export_session(session: Session, path_str: str, fmt: str) -> Path:
    if session.is_missing or not session.jsonl_path.is_file():
        raise ExportError("transcript file not available on this machine")
    dest = resolve_destination(path_str, session, fmt)
    if fmt == RAW:
        return export_raw(session, dest)
    return export_markdown(session, dest)
