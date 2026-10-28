from __future__ import annotations

import json
from pathlib import Path

from .models import Project

DEFAULT_ALIASES_PATH = Path.home() / ".config" / "ccsessions" / "aliases.json"


class ProjectAliases:
    """Cosmetic display names for projects, keyed by project directory name.

    Purely a ccsessions-side overlay — nothing under ~/.claude is touched,
    so the default (path-derived) name is always recoverable by removing
    the alias.

    The key is the directory name under ~/.claude/projects rather than the
    project path, because a path does not identify a project: a Claude
    worktree gets a directory of its own while its sessions report the main
    checkout's cwd, so both show the same path and an alias set on one would
    name both. The directory name survives archiving (the directory moves,
    its name does not), which the full path would not.

    Stores written before this are keyed by path. They are still read, and
    rewritten to directory keys on the first scan where the path identifies
    exactly one project.
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

    @staticmethod
    def _key(project: Project) -> str:
        return project.encoded_dir.name

    def get(self, project: Project) -> str:
        own = self._data.get(self._key(project))
        if own is not None:
            return own
        # a store from before directory keys
        return self._data.get(project.project_path, "")

    def set(self, project: Project, alias: str) -> None:
        self._data[self._key(project)] = alias

    def remove(self, project: Project) -> None:
        self._data.pop(self._key(project), None)
        # also drop a legacy key, or clearing the alias would appear to do nothing
        self._data.pop(project.project_path, None)

    def _migrate_path_keys(self, projects: list[Project]) -> bool:
        """Move legacy path keys onto directory keys. True when anything moved.

        Only paths that identify exactly one project are moved: where two
        projects share a path there is no way to tell whose alias it was, so
        the legacy key stays and keeps naming both — as it already did.
        """
        by_path: dict[str, list[Project]] = {}
        for p in projects:
            by_path.setdefault(p.project_path, []).append(p)
        moved = False
        for path, group in by_path.items():
            alias = self._data.get(path)
            if alias is None or len(group) != 1:
                continue
            self._data.pop(path)
            self._data.setdefault(self._key(group[0]), alias)
            moved = True
        return moved

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
        if self._migrate_path_keys(projects):
            self.save()
        for p in projects:
            p.alias = self.get(p)
