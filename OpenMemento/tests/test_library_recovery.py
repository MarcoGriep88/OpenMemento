from __future__ import annotations

import json
import sqlite3
import os
import subprocess
import sys
from pathlib import Path
from contextlib import closing
from datetime import datetime
from threading import Event

import pytest

from memento.domain.media import MediaAsset
from memento.library.database import MediaLibrary
from memento.library.locking import LibraryAlreadyOpen, LibraryLock
from memento.library.recovery import (
    RecoveryCancelled, RecoveryError, create_backup, finish_pending_restore, inspect_backup, restore_backup,
)


def library_with_asset(path, name):
    library = MediaLibrary(path)
    video = path.parent / f"{name}.mp4"
    video.write_bytes(name.encode())
    library.save_asset(MediaAsset(name, video, video.stat().st_size,
        datetime.fromtimestamp(video.stat().st_mtime).astimezone(), duration_seconds=6))
    return library


def backup_and_current(tmp_path):
    original = library_with_asset(tmp_path / "source" / "library.sqlite3", "old")
    backup = tmp_path / "selected.sqlite3"
    create_backup(original.path, backup)
    current = library_with_asset(tmp_path / "active" / "library.sqlite3", "current")
    return backup, current


def ids(path):
    with closing(sqlite3.connect(path)) as db:
        return [row[0] for row in db.execute("SELECT asset_id FROM assets ORDER BY asset_id")]


def test_snapshot_includes_committed_wal_and_does_not_modify_source(tmp_path):
    library = library_with_asset(tmp_path / "library.sqlite3", "one")
    with closing(sqlite3.connect(library.path)) as writer:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("UPDATE assets SET duration_seconds=12 WHERE asset_id='one'")
        writer.commit()
        backup = tmp_path / "backup.sqlite3"
        info = create_backup(library.path, backup)
        assert info.assets == 1
        with closing(sqlite3.connect(backup)) as db:
            assert db.execute("SELECT duration_seconds FROM assets").fetchone()[0] == 12
        assert writer.execute("SELECT duration_seconds FROM assets").fetchone()[0] == 12


def test_restore_preserves_selected_backup_and_previous_library(tmp_path):
    backup, current = backup_and_current(tmp_path)
    original_bytes = backup.read_bytes()
    project = current.path.parent / "film.memento.json"
    project.write_text("independent movie project")
    media_bytes = (current.path.parent / "current.mp4").read_bytes()
    result = restore_backup(backup, current.path)
    assert ids(current.path) == ["old"]
    assert ids(result.safety_backup) == ["current"]
    assert backup.read_bytes() == original_bytes
    assert project.read_text() == "independent movie project"
    assert (current.path.parent / "current.mp4").read_bytes() == media_bytes
    assert not current.path.with_suffix(".restore.json").exists()


def test_corrupt_destination_and_sidecars_are_preserved_before_restore(tmp_path):
    backup, current = backup_and_current(tmp_path)
    current.path.write_bytes(b"broken library")
    wal = current.path.with_name(current.path.name + "-wal")
    wal.write_bytes(b"broken WAL evidence")
    result = restore_backup(backup, current.path)
    assert ids(current.path) == ["old"]
    assert result.safety_backup.read_bytes() == b"broken library"
    assert result.safety_backup.with_name(result.safety_backup.name + "-wal").read_bytes() == b"broken WAL evidence"


def test_invalid_and_future_backups_leave_current_library_untouched(tmp_path):
    backup, current = backup_and_current(tmp_path)
    bad = tmp_path / "broken.sqlite3"
    bad.write_bytes(b"not a database")
    with pytest.raises(RecoveryError):
        restore_backup(bad, current.path)
    with closing(sqlite3.connect(backup)) as db:
        db.execute("PRAGMA user_version=999")
    with pytest.raises(RecoveryError, match="version"):
        restore_backup(backup, current.path)
    assert ids(current.path) == ["current"]


def test_missing_schema_or_invalid_media_values_fail_before_exchange(tmp_path):
    backup, current = backup_and_current(tmp_path)
    with closing(sqlite3.connect(backup)) as db:
        db.execute("DROP TABLE semantic_cache")
    with pytest.raises(RecoveryError, match="schema"):
        restore_backup(backup, current.path)
    assert ids(current.path) == ["current"]


def test_cancel_during_preparation_or_safety_copy_keeps_current(tmp_path):
    backup, current = backup_and_current(tmp_path)
    for phase in ("Ausgewählte", "Bisheriger"):
        token = Event()

        def cancel(progress):
            if progress.message.startswith(phase):
                token.set()

        with pytest.raises(RecoveryCancelled):
            restore_backup(backup, current.path, token, cancel)
        assert ids(current.path) == ["current"]
        assert not current.path.with_suffix(".restore.json").exists()


def test_failed_safety_backup_does_not_replace_current(tmp_path, monkeypatch):
    import memento.library.recovery as module
    backup, current = backup_and_current(tmp_path)
    real_snapshot = module._snapshot

    def full_disk(source, destination, token, callback, message):
        if message.startswith("Bisheriger"):
            raise OSError("simulated full disk")
        return real_snapshot(source, destination, token, callback, message)

    monkeypatch.setattr(module, "_snapshot", full_disk)
    with pytest.raises(OSError, match="full disk"):
        restore_backup(backup, current.path)
    assert ids(current.path) == ["current"]


def test_pending_exchange_recovers_after_interruption_before_publication(tmp_path, monkeypatch):
    import memento.library.recovery as module
    backup, current = backup_and_current(tmp_path)
    real_publish = module._publish
    monkeypatch.setattr(module, "_publish", lambda *args: (_ for _ in ()).throw(RuntimeError("process interrupted")))
    with pytest.raises(RuntimeError):
        restore_backup(backup, current.path)
    assert ids(current.path) == ["current"]
    assert current.path.with_suffix(".restore.json").is_file()
    monkeypatch.setattr(module, "_publish", real_publish)
    assert finish_pending_restore(current.path)
    assert ids(current.path) == ["old"]
    assert not finish_pending_restore(current.path)


def test_pending_exchange_recovers_after_swap_before_receipt(tmp_path, monkeypatch):
    import memento.library.recovery as module
    backup, current = backup_and_current(tmp_path)
    real_json = module._atomic_json

    def interrupted_receipt(path, value):
        if path.name == "receipt.json":
            raise RuntimeError("process interrupted after swap")
        real_json(path, value)

    monkeypatch.setattr(module, "_atomic_json", interrupted_receipt)
    with pytest.raises(RuntimeError):
        restore_backup(backup, current.path)
    monkeypatch.setattr(module, "_atomic_json", real_json)
    assert finish_pending_restore(current.path)
    assert ids(current.path) == ["old"]


def test_recovery_requires_exclusive_lock_and_never_overwrites_backup_targets(tmp_path):
    backup, current = backup_and_current(tmp_path)
    with LibraryLock(current.path) as lock:
        with pytest.raises(LibraryAlreadyOpen):
            restore_backup(backup, current.path)
        result = restore_backup(backup, current.path, active_lock=lock)
        assert result.safety_backup
    existing = tmp_path / "existing.sqlite3"
    existing.write_bytes(b"preserve me")
    with pytest.raises(RecoveryError, match="neue"):
        create_backup(current.path, existing)
    assert existing.read_bytes() == b"preserve me"


def test_changed_prepared_snapshot_or_unsafe_intent_never_publishes(tmp_path, monkeypatch):
    import memento.library.recovery as module
    backup, current = backup_and_current(tmp_path)
    real_publish = module._publish
    monkeypatch.setattr(module, "_publish", lambda *args: (_ for _ in ()).throw(RuntimeError("interruption")))
    with pytest.raises(RuntimeError):
        restore_backup(backup, current.path)
    marker = current.path.with_suffix(".restore.json")
    intent = json.loads(marker.read_text())
    prepared = current.path.parent / "backups" / intent["operation"] / "prepared.sqlite3"
    prepared.write_bytes(b"tampered")
    monkeypatch.setattr(module, "_publish", real_publish)
    with pytest.raises(RecoveryError, match="verändert"):
        finish_pending_restore(current.path)
    assert ids(current.path) == ["current"]
    intent["operation"] = "../../outside"
    marker.write_text(json.dumps(intent))
    with pytest.raises(RecoveryError, match="Ungültig"):
        finish_pending_restore(current.path)
    assert ids(current.path) == ["current"]


def test_explicit_new_restore_can_replace_unreadable_pending_intent(tmp_path):
    backup, current = backup_and_current(tmp_path)
    marker = current.path.with_suffix(".restore.json")
    marker.write_text("broken recovery intent")
    result = restore_backup(backup, current.path, replace_pending=True)
    assert ids(current.path) == ["old"]
    assert (result.safety_backup.parent / "previous-intent.json").read_text() == "broken recovery intent"


def test_real_process_exit_after_intent_is_finished_before_desktop_opens_sqlite(tmp_path):
    backup, current = backup_and_current(tmp_path)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["MEMENTO_DATA_DIR"] = str(current.path.parent)
    crash = """
import os,sys
from pathlib import Path
import memento.library.recovery as recovery
recovery._publish=lambda *args: os._exit(23)
recovery.restore_backup(Path(sys.argv[1]), Path(sys.argv[2]))
"""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run([sys.executable, "-c", crash, str(backup), str(current.path)],
                            env=environment, capture_output=True, timeout=20, creationflags=flags)
    assert result.returncode == 23
    assert current.path.with_suffix(".restore.json").exists()
    startup = """
import sys,json
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import memento.app as app
Base=app.MainWindow
class CheckedWindow(Base):
 def __init__(self,*args,**kwargs):
  super().__init__(*args,**kwargs)
  print(json.dumps([asset.asset_id for asset in self.library.list_assets()]), flush=True)
  QTimer.singleShot(20, QApplication.instance().quit)
app.MainWindow=CheckedWindow
sys.argv=['memento']
raise SystemExit(app.main())
"""
    result = subprocess.run([sys.executable, "-c", startup], env=environment, capture_output=True,
                            text=True, timeout=20, creationflags=flags)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == ["old"]
    assert not current.path.with_suffix(".restore.json").exists()


def test_older_schema_is_migrated_only_in_prepared_copy(tmp_path):
    backup, current = backup_and_current(tmp_path)
    with closing(sqlite3.connect(backup)) as db:
        db.execute("ALTER TABLE assets DROP COLUMN metadata_version")
        db.execute("DELETE FROM schema_migrations WHERE version=7")
        db.execute("PRAGMA user_version=6")
        db.commit()
    source_bytes = backup.read_bytes()
    restore_backup(backup, current.path)
    assert backup.read_bytes() == source_bytes
    with closing(sqlite3.connect(current.path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 7
