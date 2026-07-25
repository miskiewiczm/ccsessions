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


def test_archive_project_moves_directory(fake_base, tmp_path):
    arch_base = tmp_path / "projects-archive"
    with patch.object(manage, "PROJECTS_ARCHIVE_DIR", arch_base):
        project = discover_projects(base=fake_base)[0]
        dest = archive_project(project)
    assert dest.is_dir()
    assert not (fake_base / "-tmp-fake-project").exists()
    assert discover_projects(base=fake_base) == []


def test_delete_project_removes_directory(fake_base):
    project = discover_projects(base=fake_base)[0]
    delete_project(project)
    assert not (fake_base / "-tmp-fake-project").exists()
