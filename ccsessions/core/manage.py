from __future__ import annotations

import json
import shutil
from pathlib import Path

from .models import Project, Session

ARCHIVE_SUBDIR = "archived"
PROJECTS_DIR = Path.home() / ".claude" / "projects"
PROJECTS_ARCHIVE_DIR = Path.home() / ".claude" / "projects-archive"


class ManageError(RuntimeError):
    pass


def archive_session(session: Session) -> Path:
    """Move the .jsonl into the archived/ subdirectory — it disappears from
    `claude --resume` but stays on disk and can be restored."""
    if not session.jsonl_path.is_file():
        raise ManageError("JSONL file not on this machine")
    dest_dir = session.jsonl_path.parent / ARCHIVE_SUBDIR
    try:
        dest_dir.mkdir(exist_ok=True)
        dest = dest_dir / session.jsonl_path.name
        session.jsonl_path.rename(dest)
    except OSError as e:
        raise ManageError(str(e)) from e
    return dest


def restore_session(session: Session) -> Path:
    """Move the .jsonl from archived/ back into the project directory."""
    if not session.jsonl_path.is_file():
        raise ManageError("file not found in the archive")
    if session.jsonl_path.parent.name != ARCHIVE_SUBDIR:
        raise ManageError("session is not archived")
    dest = session.jsonl_path.parent.parent / session.jsonl_path.name
    try:
        session.jsonl_path.rename(dest)
    except OSError as e:
        raise ManageError(str(e)) from e
    return dest


def _remove_index_entry(proj_dir: Path, session_id: str) -> None:
    index_path = proj_dir / "sessions-index.json"
    if not index_path.is_file():
        return
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    entries = data.get("entries")
    if not isinstance(entries, list):
        return
    kept = [e for e in entries if not (isinstance(e, dict) and e.get("sessionId") == session_id)]
    if len(kept) != len(entries):
        data["entries"] = kept
        try:
            index_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass


def delete_session(session: Session) -> None:
    """Delete the transcript file (if present) and its sessions-index.json entry."""
    try:
        if session.jsonl_path.is_file():
            session.jsonl_path.unlink()
    except OSError as e:
        raise ManageError(str(e)) from e
    proj_dir = session.jsonl_path.parent
    if proj_dir.name == ARCHIVE_SUBDIR:
        proj_dir = proj_dir.parent
    _remove_index_entry(proj_dir, session.session_id)


def archive_project(project: Project) -> Path:
    """Move the whole project directory into ~/.claude/projects-archive/."""
    try:
        PROJECTS_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ManageError(str(e)) from e
    dest = PROJECTS_ARCHIVE_DIR / project.encoded_dir.name
    if dest.exists():
        raise ManageError(f"archive already contains directory {dest.name}")
    try:
        shutil.move(str(project.encoded_dir), str(dest))
    except OSError as e:
        raise ManageError(str(e)) from e
    return dest


def restore_project(project: Project) -> Path:
    """Move an archived project directory back into ~/.claude/projects/."""
    if not project.encoded_dir.is_dir():
        raise ManageError("project directory not found")
    dest = PROJECTS_DIR / project.encoded_dir.name
    if dest.exists():
        raise ManageError(f"projects directory already contains {dest.name}")
    try:
        shutil.move(str(project.encoded_dir), str(dest))
    except OSError as e:
        raise ManageError(str(e)) from e
    return dest


def delete_project(project: Project) -> None:
    """Permanently delete the whole project directory from ~/.claude/projects/."""
    try:
        shutil.rmtree(project.encoded_dir)
    except OSError as e:
        raise ManageError(str(e)) from e
