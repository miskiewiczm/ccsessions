from __future__ import annotations

import os
import shlex
import shutil
from dataclasses import dataclass


@dataclass
class ResumeRequest:
    session_id: str
    cwd: str


class ResumeError(RuntimeError):
    pass


def build_resume_command(req: ResumeRequest) -> str:
    """Shell command that resumes the session — for copy/paste into a terminal."""
    cmd = f"claude --resume {shlex.quote(req.session_id)}"
    if req.cwd and os.path.isdir(req.cwd):
        cmd = f"cd {shlex.quote(req.cwd)} && {cmd}"
    return cmd


def execute_resume(req: ResumeRequest) -> None:
    """Replace the current process with `claude --resume <id>` in the session cwd.

    Does not return on success (os.execvp replaces the process image).
    """
    claude_bin = shutil.which("claude")
    if not claude_bin:
        raise ResumeError("`claude` not found in PATH")
    if req.cwd and os.path.isdir(req.cwd):
        os.chdir(req.cwd)
    os.execvp(claude_bin, ["claude", "--resume", req.session_id])
