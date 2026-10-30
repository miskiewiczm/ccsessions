from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .models import Entry, TokenStats

if TYPE_CHECKING:
    from .cache import TokenCache


def extract_cwd(jsonl_path: Path, max_lines: int = 20) -> str:
    """Read the first few events looking for a `cwd` field. Empty string if none."""
    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    cwd = obj.get("cwd")
                    if isinstance(cwd, str) and cwd:
                        return cwd
    except OSError:
        pass
    return ""


def _prompt_text(content: object) -> str:
    """Text the user typed, or "" for tool results and slash-command wrappers."""
    if isinstance(content, list):
        content = " ".join(
            c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"
        )
    if not isinstance(content, str) or content.lstrip().startswith("<"):
        return ""
    return content.strip()


def compute_token_stats(jsonl_path: Path) -> TokenStats:
    stats = TokenStats()
    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and obj.get("type") == "custom-title":
                    title = obj.get("customTitle")
                    if isinstance(title, str):
                        stats.custom_title = title.strip()
                    continue
                if isinstance(obj, dict) and obj.get("type") == "ai-title":
                    title = obj.get("aiTitle")
                    if isinstance(title, str):
                        stats.ai_title = title.strip()
                    continue
                msg = obj.get("message") if isinstance(obj, dict) else None
                if not isinstance(msg, dict):
                    continue
                if obj.get("type") in ("user", "assistant") and not obj.get("isMeta"):
                    stats.messages += 1
                if obj.get("type") == "user" and not obj.get("isMeta") and not stats.first_prompt:
                    stats.first_prompt = _prompt_text(msg.get("content"))
                usage = msg.get("usage")
                if not isinstance(usage, dict):
                    continue
                stats.input += int(usage.get("input_tokens") or 0)
                stats.output += int(usage.get("output_tokens") or 0)
                stats.cache_read += int(usage.get("cache_read_input_tokens") or 0)
                stats.cache_write += int(usage.get("cache_creation_input_tokens") or 0)
    except OSError:
        pass
    return stats


def get_token_stats(jsonl_path: Path, cache: "TokenCache | None" = None) -> TokenStats:
    """Like compute_token_stats, but skips the read when the cache is fresh."""
    if cache is None:
        return compute_token_stats(jsonl_path)
    try:
        stat = jsonl_path.stat()
    except OSError:
        return TokenStats()
    cached = cache.get(jsonl_path, stat)
    if cached is not None:
        return cached
    stats = compute_token_stats(jsonl_path)
    cache.put(jsonl_path, stats, stat)
    return stats


def _summarize_tool_use(name: str, tool_input: object) -> str:
    if not isinstance(tool_input, dict):
        return name
    for key in ("command", "description", "file_path", "pattern", "prompt", "query", "url", "skill"):
        val = tool_input.get(key)
        if isinstance(val, str) and val.strip():
            first = val.strip().splitlines()[0]
            if len(first) > 80:
                first = first[:77] + "..."
            return f"{name}: {first}"
    return name


_CMD_NAME = re.compile(r"<command-name>(.*?)</command-name>", re.S)
_CMD_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)
_CMD_STDOUT = re.compile(r"<local-command-stdout>(.*?)</local-command-stdout>", re.S)


def _classify_user_text(text: str) -> tuple[str, str] | None:
    """Turn raw slash-command records into readable entries.

    Returns (role, text) or None when the entry should be skipped.
    """
    m = _CMD_NAME.search(text)
    if m:
        label = m.group(1).strip()
        args = _CMD_ARGS.search(text)
        if args and args.group(1).strip():
            label += " " + args.group(1).strip()
        return ("command", label) if label else None
    m = _CMD_STDOUT.search(text)
    if m:
        out = m.group(1).strip()
        return ("command-output", out) if out else None
    return ("user", text)


def _parse_ts(value: object) -> "datetime | None":
    """Parse the ISO-8601 timestamp Claude Code writes on every record."""
    if not isinstance(value, str) or not value:
        return None
    try:
        # fromisoformat only learned to read the trailing "Z" in 3.11
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def entries_from_line(line: str) -> list[Entry]:
    """Parse one JSONL record into zero or more entries."""
    line = line.strip()
    if not line:
        return []
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return []
    if not isinstance(obj, dict) or obj.get("isMeta"):
        return []
    typ = obj.get("type")
    msg = obj.get("message")
    if typ not in ("user", "assistant") or not isinstance(msg, dict):
        return []
    ts = _parse_ts(obj.get("timestamp"))
    content = msg.get("content")

    if typ == "user":
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            text = "\n".join(
                b["text"].strip()
                for b in content
                if isinstance(b, dict)
                and b.get("type") == "text"
                and isinstance(b.get("text"), str)
                and b["text"].strip()
            )
        else:
            return []
        if not text:
            return []
        entry = _classify_user_text(text)
        return [Entry(*entry, ts)] if entry is not None else []

    if not isinstance(content, list):
        return []
    entries: list[Entry] = []
    for b in content:
        if not isinstance(b, dict):
            continue
        btype = b.get("type")
        if btype == "text" and isinstance(b.get("text"), str) and b["text"].strip():
            entries.append(Entry("assistant", b["text"].strip(), ts))
        elif btype == "tool_use":
            name = str(b.get("name") or "?")
            entries.append(Entry("tool", _summarize_tool_use(name, b.get("input")), ts))
    return entries


def read_conversation_tail(
    jsonl_path: Path,
    max_entries: int = 40,
    max_bytes: int = 512_000,
) -> list[Entry]:
    """Last conversation entries, newest last.

    Entry.role is 'user', 'assistant', 'tool' (tool call), 'command'
    (slash command) or 'command-output'. Only the tail of the file
    (max_bytes) is read, so this stays fast even for transcripts
    spanning many megabytes.
    """
    try:
        with open(jsonl_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            start = max(0, size - max_bytes)
            f.seek(start)
            data = f.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    if start > 0 and lines:
        lines = lines[1:]  # the first line is usually cut mid-record

    entries: list[Entry] = []
    for line in lines:
        entries.extend(entries_from_line(line))
    return entries[-max_entries:]


def iter_conversation(jsonl_path: Path) -> Iterator[Entry]:
    """Stream the whole conversation, one entry at a time.

    Reads line by line, so even multi-hundred-megabyte transcripts
    never land in memory at once.
    """
    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                yield from entries_from_line(line)
    except OSError:
        return
