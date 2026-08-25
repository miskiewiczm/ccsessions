from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from ccsessions.core.models import Session
from ccsessions.core.watch import (
    LiveDoc,
    WatchError,
    gitignore_hint,
    has_live_doc,
    live_doc_path,
)


def _event(role: str, text: str) -> str:
    if role == "user":
        obj = {"type": "user", "message": {"role": "user", "content": text}}
    else:
        obj = {
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
        }
    return json.dumps(obj) + "\n"


@pytest.fixture
def session(tmp_path: Path) -> Session:
    jsonl = tmp_path / "transcript.jsonl"
    jsonl.write_text(_event("user", "first question"), encoding="utf-8")
    return Session(
        session_id="abc-123",
        jsonl_path=jsonl,
        project_path=str(tmp_path),
        summary="Live session",
        modified=datetime(2026, 8, 25, 20, 0),
        is_live=True,
    )


def append(session: Session, role: str, text: str) -> None:
    with open(session.jsonl_path, "a", encoding="utf-8") as f:
        f.write(_event(role, text))


def test_document_path_is_in_the_project_directory(session, tmp_path):
    assert live_doc_path(session) == tmp_path / "_session_abc-123.md"
    assert not has_live_doc(session)


def test_first_write_contains_front_matter_and_conversation(session):
    doc = LiveDoc(session)
    doc.poll(session, force=True)
    text = doc.out_path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert 'session_id: "abc-123"' in text
    assert 'live: "yes"' in text
    assert "window: 30" in text
    assert "## You\n\nfirst question" in text
    assert has_live_doc(session)


def test_appended_lines_are_picked_up_incrementally(session):
    doc = LiveDoc(session)
    doc.poll(session, force=True)
    offset_after_first = doc._offset

    append(session, "assistant", "the answer is 42")
    doc.poll(session, force=True)

    text = doc.out_path.read_text(encoding="utf-8")
    assert "the answer is 42" in text
    assert doc._offset > offset_after_first


def test_partial_trailing_line_is_buffered(session):
    doc = LiveDoc(session)
    doc.poll(session, force=True)
    # a record still being written: no trailing newline yet
    with open(session.jsonl_path, "a", encoding="utf-8") as f:
        f.write(_event("assistant", "complete")[:-1])
    doc.poll(session, force=True)
    assert "complete" not in doc.out_path.read_text(encoding="utf-8")
    with open(session.jsonl_path, "a", encoding="utf-8") as f:
        f.write("\n")
    doc.poll(session, force=True)
    assert "complete" in doc.out_path.read_text(encoding="utf-8")


def test_window_keeps_only_the_last_entries(session):
    doc = LiveDoc(session, window=3)
    for i in range(10):
        append(session, "user", f"message {i}")
    doc.poll(session, force=True)
    text = doc.out_path.read_text(encoding="utf-8")
    assert "message 9" in text
    assert "message 5" not in text
    assert "window: 3" in text


def test_truncated_transcript_resets_the_reader(session):
    doc = LiveDoc(session)
    append(session, "user", "before truncation")
    doc.poll(session, force=True)
    session.jsonl_path.write_text(_event("user", "after truncation"), encoding="utf-8")
    doc.poll(session, force=True)
    text = doc.out_path.read_text(encoding="utf-8")
    assert "after truncation" in text
    assert "before truncation" not in text


def test_debounce_skips_rapid_rewrites(session):
    doc = LiveDoc(session)
    assert doc.poll(session, force=True)
    append(session, "user", "quick follow-up")
    assert doc.poll(session) is False  # too soon after the previous write
    assert doc.poll(session, force=True) is True


def test_stopped_session_is_marked_in_the_document(session):
    doc = LiveDoc(session)
    session.is_live = False
    doc.poll(session, force=True)
    text = doc.out_path.read_text(encoding="utf-8")
    assert 'live: "no"' in text
    assert "_Session is not running._" in text


def test_missing_project_directory_raises(session, tmp_path):
    session.project_path = str(tmp_path / "gone")
    with pytest.raises(WatchError):
        LiveDoc(session)


def test_gitignore_hint_only_for_unprepared_repos(session, tmp_path):
    assert gitignore_hint(session) == ""  # not a git repo
    (tmp_path / ".git").mkdir()
    assert "gitignore" in gitignore_hint(session)
    (tmp_path / ".gitignore").write_text("_session_*.md\n", encoding="utf-8")
    assert gitignore_hint(session) == ""


def test_live_dir_override_redirects_documents(session, tmp_path, monkeypatch):
    elsewhere = tmp_path / "live" / "docs"
    monkeypatch.setenv("CCSESSIONS_LIVE_DIR", str(elsewhere))
    doc = LiveDoc(session)  # the directory is created on demand
    doc.poll(session, force=True)
    assert doc.out_path == elsewhere / "_session_abc-123.md"
    assert doc.out_path.is_file()
    assert not (tmp_path / "_session_abc-123.md").exists()
