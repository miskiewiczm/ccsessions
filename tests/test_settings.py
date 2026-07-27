from __future__ import annotations

from ccsessions.core.settings import load_settings, save_settings
from ccsessions.ui.app import code_theme_for


def test_settings_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    assert load_settings(path) == {}
    save_settings({"theme": "gruvbox"}, path)
    assert load_settings(path) == {"theme": "gruvbox"}


def test_corrupted_settings_are_tolerated(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{oops", encoding="utf-8")
    assert load_settings(path) == {}


def test_code_theme_override_wins():
    assert code_theme_for("nord", dark=True, override="monokai") == "monokai"


def test_code_theme_follows_app_theme():
    assert code_theme_for("nord", dark=True) == "nord"
    assert code_theme_for("gruvbox", dark=True) == "gruvbox-dark"
    assert code_theme_for("dracula", dark=True) == "dracula"
    assert code_theme_for("textual-light", dark=False) == "default"


def test_code_theme_fallback_by_darkness():
    assert code_theme_for("ansi-dark", dark=True) == "nord"
    assert code_theme_for("some-light-theme", dark=False) == "default"
