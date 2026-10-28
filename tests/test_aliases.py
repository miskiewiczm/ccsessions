from __future__ import annotations

import json
from pathlib import Path

from ccsessions.core.aliases import ProjectAliases
from ccsessions.core.models import Project

ENCODED = Path("/tmp/projects")


def _project(path: str, dirname: str = "") -> Project:
    return Project(project_path=path, encoded_dir=ENCODED / (dirname or path.replace("/", "-")))


def test_display_name_prefers_alias():
    p = _project("/home/user/projekt_final")
    assert p.display_name == "projekt_final"
    p.alias = "PPSI 2026"
    assert p.display_name == "PPSI 2026"
    assert p.default_name == "projekt_final"


def test_worktree_shows_in_the_default_name():
    main = _project("/home/user/repo", "-home-user-repo")
    # a worktree reports the main checkout's cwd, so only the directory tells them apart
    wt = _project("/home/user/repo", "-home-user-repo--claude-worktrees-feature")
    assert main.worktree == ""
    assert wt.worktree == "feature"
    assert main.default_name == "repo"
    assert wt.default_name == "repo ⎇ feature"


def test_set_save_load_roundtrip(tmp_path):
    store = tmp_path / "aliases.json"
    p = _project("/home/user/projekt_final")
    aliases = ProjectAliases(store)
    aliases.set(p, "PPSI 2026")
    aliases.save()

    reloaded = ProjectAliases(store)
    assert reloaded.get(p) == "PPSI 2026"
    assert reloaded.get(_project("/home/user/other")) == ""


def test_remove_restores_default(tmp_path):
    store = tmp_path / "aliases.json"
    p = _project("/home/user/p")
    aliases = ProjectAliases(store)
    aliases.set(p, "Alias")
    aliases.remove(p)
    aliases.save()

    ProjectAliases(store).apply([p])
    assert p.alias == ""
    assert p.display_name == "p"


def test_apply_sets_aliases_on_projects(tmp_path):
    store = tmp_path / "aliases.json"
    projects = [_project("/a"), _project("/b")]
    aliases = ProjectAliases(store)
    aliases.set(projects[0], "Alpha")
    aliases.apply(projects)
    assert projects[0].display_name == "Alpha"
    assert projects[1].display_name == "b"


def test_alias_does_not_leak_to_a_worktree_sharing_the_path(tmp_path):
    store = tmp_path / "aliases.json"
    main = _project("/home/user/repo", "-home-user-repo")
    wt = _project("/home/user/repo", "-home-user-repo--claude-worktrees-feature")
    aliases = ProjectAliases(store)
    aliases.set(wt, "Feature")
    aliases.apply([main, wt])
    assert wt.display_name == "Feature"
    assert main.display_name == "repo"  # the other row keeps its own name


def test_legacy_path_key_is_read_then_migrated(tmp_path):
    store = tmp_path / "aliases.json"
    store.write_text(json.dumps({"/home/user/repo": "Repo"}), encoding="utf-8")
    main = _project("/home/user/repo", "-home-user-repo")

    aliases = ProjectAliases(store)
    assert aliases.get(main) == "Repo"  # a store written before directory keys
    aliases.apply([main])
    assert main.display_name == "Repo"
    assert json.loads(store.read_text(encoding="utf-8")) == {"-home-user-repo": "Repo"}

    # a worktree added later no longer inherits the name
    wt = _project("/home/user/repo", "-home-user-repo--claude-worktrees-feature")
    ProjectAliases(store).apply([main, wt])
    assert main.display_name == "Repo"
    assert wt.display_name == "repo ⎇ feature"


def test_legacy_path_key_kept_when_two_projects_share_it(tmp_path):
    store = tmp_path / "aliases.json"
    store.write_text(json.dumps({"/home/user/repo": "Repo"}), encoding="utf-8")
    main = _project("/home/user/repo", "-home-user-repo")
    wt = _project("/home/user/repo", "-home-user-repo--claude-worktrees-feature")

    # whose alias it was cannot be told, so it stays as it is and still names both
    ProjectAliases(store).apply([main, wt])
    assert main.display_name == "Repo" and wt.display_name == "Repo"
    assert json.loads(store.read_text(encoding="utf-8")) == {"/home/user/repo": "Repo"}

    # naming one of them resolves the ambiguity
    aliases = ProjectAliases(store)
    aliases.set(wt, "Feature")
    aliases.save()
    ProjectAliases(store).apply([main, wt])
    assert main.display_name == "Repo" and wt.display_name == "Feature"


def test_corrupted_store_is_tolerated(tmp_path):
    store = tmp_path / "aliases.json"
    store.write_text("{broken", encoding="utf-8")
    p = _project("/a")
    aliases = ProjectAliases(store)
    assert aliases.get(p) == ""
    aliases.set(p, "X")
    aliases.save()
    assert ProjectAliases(store).get(p) == "X"
