from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import ccsessions.core.manage as manage
from ccsessions.core.discovery import discover_projects
from ccsessions.core.manage import (
    ManageError,
    archive_project,
    archive_session,
    delete_project,
    delete_session,
    restore_session,
)

from conftest import SID


def _session(base):
    return discover_projects(base=base)[0].sessions[0]


def test_archive_and_restore_session(fake_base):
    s = _session(fake_base)
    dest = archive_session(s)
    assert dest.parent.name == manage.ARCHIVE_SUBDIR
    assert dest.is_file()

    s = _session(fake_base)
    assert s.is_archived
    restored = restore_session(s)
    assert restored.parent.name == "-tmp-fake-project"
    assert not _session(fake_base).is_archived


def test_restore_requires_archived_session(fake_base):
    s = _session(fake_base)
    with pytest.raises(ManageError):
        restore_session(s)


def test_delete_session_removes_file_and_index_entry(fake_base):
    s = _session(fake_base)
    delete_session(s)
    assert not s.jsonl_path.exists()
    index = json.loads(
        (fake_base / "-tmp-fake-project" / "sessions-index.json").read_text()
    )
    assert index["entries"] == []


def test_delete_missing_session_removes_index_entry_only(fake_base):
    (fake_base / "-tmp-fake-project" / f"{SID}.jsonl").unlink()
    s = _session(fake_base)
    assert s.is_missing
    delete_session(s)
    index = json.loads(
        (fake_base / "-tmp-fake-project" / "sessions-index.json").read_text()
    )
    assert index["entries"] == []


def test_delete_missing_session_with_foreign_full_path(fake_base):
    # index synced from another machine whose home directory differs
    proj = fake_base / "-tmp-fake-project"
    (proj / f"{SID}.jsonl").unlink()
    index_path = proj / "sessions-index.json"
    index = json.loads(index_path.read_text())
    index["entries"][0]["fullPath"] = f"/Users/elsewhere/.claude/projects/-tmp-fake-project/{SID}.jsonl"
    index_path.write_text(json.dumps(index))
    s = _session(fake_base)
    assert s.is_missing
    delete_session(s)
    assert json.loads(index_path.read_text())["entries"] == []


def test_delete_session_reports_index_write_failure(fake_base):
    index_path = fake_base / "-tmp-fake-project" / "sessions-index.json"
    before = index_path.read_text()
    s = _session(fake_base)
    with patch.object(type(index_path), "replace", side_effect=OSError("disk full")):
        with pytest.raises(ManageError):
            delete_session(s)
    assert index_path.read_text() == before


def test_archive_project_moves_directory(fake_base, tmp_path):
    arch_base = tmp_path / "projects-archive"
    with patch.object(manage, "PROJECTS_ARCHIVE_DIR", arch_base):
        project = discover_projects(base=fake_base)[0]
        dest = archive_project(project)
    assert dest.is_dir()
    assert not (fake_base / "-tmp-fake-project").exists()
    assert discover_projects(base=fake_base) == []


def test_restore_project_moves_directory_back(fake_base, tmp_path):
    arch_base = tmp_path / "projects-archive"
    with patch.object(manage, "PROJECTS_ARCHIVE_DIR", arch_base), patch.object(
        manage, "PROJECTS_DIR", fake_base
    ):
        project = discover_projects(base=fake_base)[0]
        archive_project(project)
        archived = discover_projects(base=fake_base, archive_base=arch_base)[0]
        assert archived.is_archived
        manage.restore_project(archived)
    assert (fake_base / "-tmp-fake-project").is_dir()
    assert not (arch_base / "-tmp-fake-project").exists()
    restored = discover_projects(base=fake_base, archive_base=arch_base)
    assert len(restored) == 1 and not restored[0].is_archived


def test_delete_project_removes_directory(fake_base):
    project = discover_projects(base=fake_base)[0]
    delete_project(project)
    assert not (fake_base / "-tmp-fake-project").exists()
