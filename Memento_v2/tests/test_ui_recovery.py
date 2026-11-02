from __future__ import annotations

import os
from contextlib import closing
from datetime import datetime
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from memento.domain.media import MediaAsset
from memento.library.database import MediaLibrary
from memento.library.recovery import create_backup
from memento.ui.recovery_dialog import RecoveryDialog


def wait_for(predicate):
    loop, timer = QEventLoop(), QTimer()
    timer.timeout.connect(lambda: loop.quit() if predicate() else None)
    timer.start(10)
    QTimer.singleShot(10000, loop.quit)
    loop.exec()
    timer.stop()
    return predicate()


def test_recovery_dialog_inspects_confirms_and_restores_in_worker(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    library = MediaLibrary(tmp_path / "library.sqlite3")
    source = tmp_path / "video.mp4"
    source.write_bytes(b"source")
    library.save_asset(MediaAsset("asset", source, 6, datetime.fromtimestamp(source.stat().st_mtime).astimezone(), duration_seconds=6))
    backup = tmp_path / "backup.sqlite3"
    create_backup(library.path, backup)
    with library._connection() as db:
        db.execute("UPDATE assets SET duration_seconds=12")
    dialog = RecoveryDialog(library.path)
    dialog.show()
    dialog.inspect(backup)
    assert wait_for(lambda: dialog.thread is None)
    assert dialog.info.assets == 1
    assert dialog.restore_button.isEnabled()
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.No)
    dialog.restore_button.click()
    assert not dialog.restored
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    dialog.restore_button.click()
    assert wait_for(lambda: dialog.thread is None)
    assert dialog.restored
    assert library.get_asset("asset").duration_seconds == 6
    with closing(sqlite3.connect(dialog.recovery_result.safety_backup)) as db:
        assert db.execute("SELECT duration_seconds FROM assets").fetchone()[0] == 12
    dialog.reject()
    app.processEvents()


def test_closing_recovery_dialog_waits_for_worker_to_stop(tmp_path):
    app = QApplication.instance() or QApplication([])
    dialog = RecoveryDialog(tmp_path / "library.sqlite3")
    dialog.show()
    dialog.run_operation("inspect", lambda token, progress: token.wait(2))
    dialog.close()
    assert dialog.isVisible()
    assert wait_for(lambda: dialog.thread is None)
    dialog.close()
    assert not dialog.isVisible()
    app.processEvents()
