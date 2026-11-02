from pathlib import Path

from memento.library import database


def setup_home(monkeypatch, tmp_path, platform="linux"):
    import sys
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("MEMENTO_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    return tmp_path


def test_linux_uses_xdg_and_ignores_windows_environment(monkeypatch, tmp_path):
    setup_home(monkeypatch, tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "windows"))
    assert database.default_database_path() == tmp_path / ".local/share/Memento_v2/library.sqlite3"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert database.default_database_path() == tmp_path / "data/Memento_v2/library.sqlite3"
    monkeypatch.setenv("XDG_DATA_HOME", "relative")
    assert database.default_database_path() == tmp_path / ".local/share/Memento_v2/library.sqlite3"


def test_linux_retains_existing_legacy_library_without_moving_it(monkeypatch, tmp_path):
    setup_home(monkeypatch, tmp_path)
    legacy = tmp_path / "AppData/Local/Memento/library.sqlite3"
    database.MediaLibrary(legacy)
    assert database.default_database_path() == tmp_path / ".local/share/Memento_v2/library.sqlite3"
    target = tmp_path / ".local/share/Memento_v2/library.sqlite3"
    database.MediaLibrary(target)
    assert database.default_database_path() == target
    assert legacy.is_file()


def test_explicit_data_dir_takes_precedence(monkeypatch, tmp_path):
    setup_home(monkeypatch, tmp_path)
    monkeypatch.setenv("MEMENTO_DATA_DIR", str(tmp_path / "custom"))
    assert database.default_database_path() == tmp_path / "custom/library.sqlite3"


def test_windows_keeps_existing_path(monkeypatch, tmp_path):
    setup_home(monkeypatch, tmp_path, "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert database.default_database_path() == tmp_path / "local/Memento_v2/library.sqlite3"
