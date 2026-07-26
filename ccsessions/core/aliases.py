from __future__ import annotations

import json
from pathlib import Path

from .models import Project

DEFAULT_ALIASES_PATH = Path.home() / ".config" / "ccsessions" / "aliases.json"


class ProjectAliases:
    """Cosmetic display names for projects, keyed by project path.

    Purely a ccsessions-side overlay — nothing under ~/.claude is touched,
    so the default (path-derived) name is always recoverable by removing
    the alias.
    """

    def __init__(self, path: Path = DEFAULT_ALIASES_PATH) -> None:
        self.path = path
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(data, dict):
            self._data = {
                k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)
            }

    def get(self, project_path: str) -> str:
        return self._data.get(project_path, "")

    def set(self, project_path: str, alias: str) -> None:
        self._data[project_path] = alias

    def remove(self, project_path: str) -> None:
        self._data.pop(project_path, None)

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            tmp.replace(self.path)
        except OSError:
            pass

    def apply(self, projects: list[Project]) -> None:
        for p in projects:
            p.alias = self.get(p.project_path)
