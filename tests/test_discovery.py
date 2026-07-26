from __future__ import annotations

import json

from ccsessions.core.discovery import discover_projects
from ccsessions.core.manage import ARCHIVE_SUBDIR

from conftest import SID, write_transcript


def test_merges_index_metadata_with_jsonl(fake_base):
    projects = discover_projects(base=fake_base)
    assert len(projects) == 1
    p = projects[0]
    assert p.project_path == "/tmp/fake-project"
    s = p.sessions[0]
    assert s.summary == "Fake session"
    assert s.message_count == 4  # index value wins
    assert s.tokens.total == 30
    assert not s.is_archived and not s.is_missing


def test_jsonl_without_index(fake_base):
    proj = fake_base / "-tmp-fake-project"
    (proj / "sessions-index.json").unlink()
    projects = discover_projects(base=fake_base)
    s = projects[0].sessions[0]
    # metadata recovered from the transcript itself
    assert projects[0].project_path == "/tmp/fake-project"
    assert s.message_count == 4  # counted from the JSONL
    assert s.tokens.total == 30


def test_index_only_entry_is_missing(fake_base):
    proj = fake_base / "-tmp-fake-project"
    (proj / f"{SID}.jsonl").unlink()
    projects = discover_projects(base=fake_base)
    s = projects[0].sessions[0]
    assert s.is_missing
    assert not s.is_archived
    assert s.tokens.total == 0


def test_archived_subdir_is_scanned(fake_base):
    proj = fake_base / "-tmp-fake-project"
    arch = proj / ARCHIVE_SUBDIR
    arch.mkdir()
    sid2 = "22222222-aaaa-bbbb-cccc-000000000002"
    write_transcript(arch / f"{sid2}.jsonl")
    projects = discover_projects(base=fake_base)
    by_id = {s.session_id: s for s in projects[0].sessions}
    assert by_id[sid2].is_archived
    assert not by_id[sid2].is_missing
    assert by_id[sid2].tokens.total == 30
    assert not by_id[SID].is_archived


def test_empty_base_yields_no_projects(tmp_path):
    assert discover_projects(base=tmp_path / "nope") == []


def test_archived_projects_listed_after_active(fake_base, tmp_path):
    arch_base = tmp_path / "projects-archive"
    arch_proj = arch_base / "-tmp-old-project"
    arch_proj.mkdir(parents=True)
    sid2 = "33333333-aaaa-bbbb-cccc-000000000003"
    write_transcript(arch_proj / f"{sid2}.jsonl", cwd="/tmp/old-project")

    projects = discover_projects(base=fake_base, archive_base=arch_base)
    assert len(projects) == 2
    assert not projects[0].is_archived
    archived = projects[1]
    assert archived.is_archived
    # sessions of an archived project are flagged and never live
    assert all(s.is_archived and not s.is_live for s in archived.sessions)


def test_project_index_metadata(fake_base):
    # a second, newer project should sort first
    proj2 = fake_base / "-tmp-newer"
    proj2.mkdir()
    write_transcript(proj2 / f"{SID}.jsonl", cwd="/tmp/newer")
    (fake_base / "-tmp-fake-project" / "sessions-index.json").write_text(
        json.dumps({"version": 1, "originalPath": "/tmp/fake-project", "entries": []}),
        encoding="utf-8",
    )
    projects = discover_projects(base=fake_base)
    assert [p.project_path for p in projects][0] == "/tmp/newer"
