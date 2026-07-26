from __future__ import annotations

from pathlib import Path

from ccsessions.core.aliases import ProjectAliases
from ccsessions.core.models import Project


def _project(path: str) -> Project:
    return Project(project_path=path, encoded_dir=Path("/tmp/enc"))


def test_display_name_prefers_alias():
    p = _project("/home/user/projekt_final")
    assert p.display_name == "projekt_final"
    p.alias = "PPSI 2026"
    assert p.display_name == "PPSI 2026"
    assert p.default_name == "projekt_final"


def test_set_save_load_roundtrip(tmp_path):
    store = tmp_path / "aliases.json"
    aliases = ProjectAliases(store)
    aliases.set("/home/user/projekt_final", "PPSI 2026")
    aliases.save()

    reloaded = ProjectAliases(store)
    assert reloaded.get("/home/user/projekt_final") == "PPSI 2026"
    assert reloaded.get("/home/user/other") == ""


def test_remove_restores_default(tmp_path):
    store = tmp_path / "aliases.json"
    aliases = ProjectAliases(store)
    aliases.set("/home/user/p", "Alias")
    aliases.remove("/home/user/p")
    aliases.save()

    p = _project("/home/user/p")
    ProjectAliases(store).apply([p])
    assert p.alias == ""
    assert p.display_name == "p"


def test_apply_sets_aliases_on_projects(tmp_path):
    store = tmp_path / "aliases.json"
    aliases = ProjectAliases(store)
    aliases.set("/a", "Alpha")
    projects = [_project("/a"), _project("/b")]
    aliases.apply(projects)
    assert projects[0].display_name == "Alpha"
    assert projects[1].display_name == "b"


def test_corrupted_store_is_tolerated(tmp_path):
    store = tmp_path / "aliases.json"
    store.write_text("{broken", encoding="utf-8")
    aliases = ProjectAliases(store)
    assert aliases.get("/a") == ""
    aliases.set("/a", "X")
    aliases.save()
    assert ProjectAliases(store).get("/a") == "X"
