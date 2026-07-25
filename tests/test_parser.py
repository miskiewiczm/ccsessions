from __future__ import annotations

import json

from ccsessions.core.parser import (
    compute_token_stats,
    extract_cwd,
    read_conversation_tail,
)

from conftest import write_transcript


def test_token_stats_and_message_count(tmp_path):
    f = tmp_path / "s.jsonl"
    write_transcript(f, exchanges=3)
    stats = compute_token_stats(f)
    assert stats.input == 30
    assert stats.output == 15
    assert stats.total == 45
    assert stats.messages == 6


def test_extract_cwd(tmp_path):
    f = tmp_path / "s.jsonl"
    write_transcript(f, cwd="/home/user/proj")
    assert extract_cwd(f) == "/home/user/proj"


def test_malformed_lines_are_ignored(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text('not json\n{"type":"user"}\n{"broken\n', encoding="utf-8")
    stats = compute_token_stats(f)
    assert stats.total == 0
    assert read_conversation_tail(f) == []


def test_conversation_tail_roles(tmp_path):
    f = tmp_path / "s.jsonl"
    events = [
        {"type": "user", "message": {"role": "user", "content": "hello"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "hi!"},
                    {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}},
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": "<command-name>/exit</command-name>"
                "<command-message>exit</command-message>",
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": "<local-command-stdout>Bye!</local-command-stdout>",
            },
        },
        # meta entries must be skipped
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "meta"}},
    ]
    f.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    tail = read_conversation_tail(f)
    assert tail == [
        ("user", "hello"),
        ("assistant", "hi!"),
        ("tool", "Bash: ls -la"),
        ("command", "/exit"),
        ("command-output", "Bye!"),
    ]


def test_tail_reads_only_end_of_file(tmp_path):
    f = tmp_path / "s.jsonl"
    write_transcript(f, exchanges=200)
    tail = read_conversation_tail(f, max_entries=5, max_bytes=2000)
    assert len(tail) == 5
    # the freshest entries win
    assert tail[-1][1].endswith("199")
