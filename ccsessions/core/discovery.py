from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .cache import TokenCache
from .live import get_live_session_ids
from .manage import ARCHIVE_SUBDIR, PROJECTS_ARCHIVE_DIR
from .models import Project, Session, TokenStats
from .parser import extract_cwd, get_token_stats

DEFAULT_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # normalize to local-naive so we can sort against fileMtime-derived values
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _load_index(index_path: Path) -> tuple[str, dict[str, dict]]:
    if not index_path.is_file():
        return "", {}
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "", {}
    project_path = data.get("originalPath") or ""
    indexed: dict[str, dict] = {}
    for entry in data.get("entries", []) or []:
        sid = entry.get("sessionId")
        if isinstance(sid, str):
            indexed[sid] = entry
    return project_path, indexed


def _build_session(
    sid: str,
    jsonl: Path,
    entry: dict,
    live_ids: set[str],
    project_path_fallback: str,
    cache: TokenCache | None = None,
    archived: bool = False,
) -> Session:
    missing = not jsonl.is_file()
    tokens = get_token_stats(jsonl, cache) if not missing else TokenStats()
    mtime: datetime | None = None
    if not missing:
        try:
            mtime = datetime.fromtimestamp(jsonl.stat().st_mtime)
        except OSError:
            pass
    elif entry.get("fileMtime"):
        try:
            mtime = datetime.fromtimestamp(int(entry["fileMtime"]) / 1000)
        except (ValueError, TypeError):
            pass
    return Session(
        session_id=sid,
        jsonl_path=jsonl,
        project_path=entry.get("projectPath") or project_path_fallback,
        first_prompt=entry.get("firstPrompt") or "",
        summary=entry.get("summary") or "",
        message_count=int(entry.get("messageCount") or 0) or tokens.messages,
        created=_parse_iso(entry.get("created")),
        modified=_parse_iso(entry.get("modified")) or mtime,
        git_branch=entry.get("gitBranch") or "",
        is_sidechain=bool(entry.get("isSidechain", False)),
        is_live=(not missing and not archived) and sid in live_ids,
        is_archived=archived,
        is_missing=missing,
        tokens=tokens,
    )


def _decode_dir_name(name: str) -> str:
    # best-effort fallback when sessions-index.json is missing
    return "/" + name.lstrip("-").replace("-", "/")


def _load_project(
    proj_dir: Path, live_ids: set[str], cache: TokenCache | None = None
) -> Project:
    project_path, indexed = _load_index(proj_dir / "sessions-index.json")

    sessions: list[Session] = []
    seen: set[str] = set()

    for jsonl in proj_dir.glob("*.jsonl"):
        sid = jsonl.stem
        seen.add(sid)
        entry = indexed.get(sid, {})
        sessions.append(_build_session(sid, jsonl, entry, live_ids, project_path, cache))

    for jsonl in (proj_dir / ARCHIVE_SUBDIR).glob("*.jsonl"):
        sid = jsonl.stem
        if sid in seen:
            continue
        seen.add(sid)
        entry = indexed.get(sid, {})
        sessions.append(
            _build_session(sid, jsonl, entry, live_ids, project_path, cache, archived=True)
        )

    for sid, entry in indexed.items():
        if sid in seen:
            continue
        full = entry.get("fullPath")
        path = Path(full) if isinstance(full, str) else proj_dir / f"{sid}.jsonl"
        # include archived entries (no .jsonl on disk) — still useful as history
        sessions.append(_build_session(sid, path, entry, live_ids, project_path, cache))

    if not project_path:
        # try to recover real cwd from a JSONL event
        for s in sessions:
            cwd = extract_cwd(s.jsonl_path)
            if cwd:
                project_path = cwd
                break
        if not project_path:
            project_path = _decode_dir_name(proj_dir.name)
        # backfill sessions that fell back to the lossy decoded path
        for s in sessions:
            if not s.project_path or s.project_path.startswith("/"):
                if s.project_path == _decode_dir_name(proj_dir.name) or not s.project_path:
                    s.project_path = project_path

    sessions.sort(key=lambda s: s.modified or datetime.min, reverse=True)
    return Project(project_path=project_path, encoded_dir=proj_dir, sessions=sessions)


def _latest_modified(p: Project) -> datetime:
    return max((s.modified or datetime.min) for s in p.sessions)


def discover_projects(
    base: Path = DEFAULT_PROJECTS_DIR,
    cache: TokenCache | None = None,
    archive_base: Path | None = None,
) -> list[Project]:
    """Scan projects (and archived projects) under ~/.claude.

    When `archive_base` is None it defaults to PROJECTS_ARCHIVE_DIR, but only
    for the real base directory — callers passing a custom `base` (tests)
    never get the user's archive mixed in unless they ask for it.
    """
    if not base.is_dir():
        return []
    live_ids = get_live_session_ids()
    projects: list[Project] = []
    for proj_dir in sorted(base.iterdir()):
        if not proj_dir.is_dir():
            continue
        project = _load_project(proj_dir, live_ids, cache)
        if project.sessions:
            projects.append(project)
    # newest project first (by latest session modified)
    projects.sort(key=_latest_modified, reverse=True)

    if archive_base is None and base == DEFAULT_PROJECTS_DIR:
        archive_base = PROJECTS_ARCHIVE_DIR
    archived: list[Project] = []
    if archive_base is not None and archive_base.is_dir():
        for proj_dir in sorted(archive_base.iterdir()):
            if not proj_dir.is_dir():
                continue
            project = _load_project(proj_dir, live_ids, cache)
            if not project.sessions:
                continue
            project.is_archived = True
            for s in project.sessions:
                s.is_archived = True
                s.is_live = False
            archived.append(project)
        archived.sort(key=_latest_modified, reverse=True)
    # archived projects always come after active ones
    return projects + archived
