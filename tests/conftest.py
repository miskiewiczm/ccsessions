from __future__ import annotations

import json
from pathlib import Path

import pytest

SID = "11111111-aaaa-bbbb-cccc-000000000001"


def write_transcript(
    path: Path,
    cwd: str = "/tmp/fake-project",
    exchanges: int = 2,
    usage_per_reply: dict | None = None,
) -> None:
    """Write a minimal but realistic session transcript."""
    usage = usage_per_reply or {"input_tokens": 10, "output_tokens": 5}
    lines = []
    for i in range(exchanges):
        lines.append(
            {
                "type": "user",
                "cwd": cwd,
                "message": {"role": "user", "content": f"question {i}"},
            }
        )
        lines.append(
            {
                "type": "assistant",
                "cwd": cwd,
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": f"**answer** {i}"}],
                    "usage": usage,
                },
            }
        )
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


@pytest.fixture
def fake_base(tmp_path: Path) -> Path:
    """A fake ~/.claude/projects base with one project and one session."""
    base = tmp_path / "projects"
    proj = base / "-tmp-fake-project"
    proj.mkdir(parents=True)
    write_transcript(proj / f"{SID}.jsonl")
    (proj / "sessions-index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "originalPath": "/tmp/fake-project",
                "entries": [
                    {
                        "sessionId": SID,
                        "firstPrompt": "question 0",
                        "summary": "Fake session",
                        "messageCount": 4,
                        "projectPath": "/tmp/fake-project",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return base
