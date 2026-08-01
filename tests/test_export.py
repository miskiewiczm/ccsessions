from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from ccsessions.core.export import (
    MARKDOWN,
    RAW,
    ExportError,
    default_filename,
    export_session,
    normalize_markdown,
    resolve_destination,
)
from ccsessions.core.models import Session, TokenStats


def _session(tmp_path: Path) -> Session:
    jsonl = tmp_path / "sess.jsonl"
    events = [
        {"type": "user", "message": {"role": "user", "content": "how do I sort a list?"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Use `sorted()`:\n\n```python\nsorted(xs)\n```"},
                    {"type": "tool_use", "name": "Bash", "input": {"command": "python3 -c 1"}},
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": "<command-name>/exit</command-name>",
            },
        },
    ]
    jsonl.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return Session(
        session_id="abc-123",
        jsonl_path=jsonl,
        project_path="/tmp/proj",
        summary="Sorting lists in Python",
        message_count=3,
        modified=datetime(2026, 8, 1, 10, 30),
        git_branch="main",
        tokens=TokenStats(input=10, output=20),
    )


def test_default_filename_uses_date_and_slug(tmp_path):
    s = _session(tmp_path)
    assert default_filename(s, MARKDOWN) == "2026-08-01-sorting-lists-in-python.md"
    assert default_filename(s, RAW) == "2026-08-01-sorting-lists-in-python.jsonl"


def test_directory_input_gets_generated_filename(tmp_path):
    s = _session(tmp_path)
    dest = resolve_destination(str(tmp_path), s, MARKDOWN)
    assert dest.parent == tmp_path
    assert dest.name.endswith("-sorting-lists-in-python.md")


def test_explicit_filename_is_respected(tmp_path):
    s = _session(tmp_path)
    dest = resolve_destination(str(tmp_path / "notes.md"), s, MARKDOWN)
    assert dest == tmp_path / "notes.md"


def test_existing_files_are_never_overwritten(tmp_path):
    s = _session(tmp_path)
    (tmp_path / "notes.md").write_text("keep me", encoding="utf-8")
    dest = resolve_destination(str(tmp_path / "notes.md"), s, MARKDOWN)
    assert dest == tmp_path / "notes-1.md"
    assert (tmp_path / "notes.md").read_text(encoding="utf-8") == "keep me"


def test_missing_directory_raises(tmp_path):
    s = _session(tmp_path)
    with pytest.raises(ExportError):
        resolve_destination(str(tmp_path / "nope" / "x.md"), s, MARKDOWN)


def test_markdown_export_content(tmp_path):
    s = _session(tmp_path)
    dest = export_session(s, str(tmp_path / "out.md"), MARKDOWN)
    text = dest.read_text(encoding="utf-8")
    # front matter
    assert text.startswith("---\n")
    assert 'title: "Sorting lists in Python"' in text
    assert 'session_id: "abc-123"' in text
    assert 'git_branch: "main"' in text
    assert "  total: 30" in text
    # conversation
    assert "## You\n\nhow do I sort a list?" in text
    assert "## Claude" in text
    assert "```python\nsorted(xs)\n```" in text  # code fences survive verbatim
    assert "- ⚙ `Bash: python3 -c 1`" in text
    assert "- ⌘ `/exit`" in text


def test_raw_export_is_byte_identical(tmp_path):
    s = _session(tmp_path)
    dest = export_session(s, str(tmp_path / "copy.jsonl"), RAW)
    assert dest.read_bytes() == s.jsonl_path.read_bytes()


def test_headings_are_demoted_below_role_headings():
    out = normalize_markdown("## Section\ntext\n### Sub")
    assert "### Section" in out
    assert "#### Sub" in out


def test_headings_inside_code_fences_are_untouched():
    out = normalize_markdown("```\n## not a heading\n```")
    assert "## not a heading" in out


def test_bare_fences_get_txt_info_string():
    assert "```txt" in normalize_markdown("```\nplain output\n```")
    assert "```python" in normalize_markdown("```python\nx = 1\n```")


def test_blank_line_inserted_before_glued_list():
    out = normalize_markdown("**Lead in.** Two changes:\n- first\n- second")
    assert "Two changes:\n\n- first\n- second" in out


def test_insight_block_gets_inner_blank_lines():
    text = "`★ Insight ─────`\n- point\n`─────────────`"
    out = normalize_markdown(text)
    assert "`★ Insight ─────`\n\n- point\n\n`─────────────`" == out


def test_consecutive_tool_calls_form_a_tight_list(tmp_path):
    jsonl = tmp_path / "tools.jsonl"
    jsonl.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "name": "Edit", "input": {"file_path": "/a.py"}},
                        {"type": "tool_use", "name": "Edit", "input": {"file_path": "/b.py"}},
                    ],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    s = _session(tmp_path)
    s.jsonl_path = jsonl
    dest = export_session(s, str(tmp_path / "tools.md"), MARKDOWN)
    assert "- ⚙ `Edit: /a.py`\n- ⚙ `Edit: /b.py`\n" in dest.read_text(encoding="utf-8")


def test_command_output_is_fenced_as_txt(tmp_path):
    s = _session(tmp_path)
    dest = export_session(s, str(tmp_path / "out.md"), MARKDOWN)
    text = dest.read_text(encoding="utf-8")
    assert "- ⌘ `/exit`" in text


def test_export_missing_transcript_raises(tmp_path):
    s = _session(tmp_path)
    s.jsonl_path.unlink()
    with pytest.raises(ExportError):
        export_session(s, str(tmp_path), MARKDOWN)
