from __future__ import annotations

from memento.i18n import configure, tr, display_message

import sys
import os
import argparse
import json
import sqlite3
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from memento.ui.workflow_window import WorkflowWindow as MainWindow
from memento.library.database import MediaLibrary, default_database_path
from memento.library.locking import LibraryAlreadyOpen, LibraryLock
from memento.library.recovery import RecoveryError, finish_pending_restore
from memento.ui.recovery_dialog import RecoveryDialog


def main() -> int:
    parser = argparse.ArgumentParser(description=tr("Memento – lokaler Familienvideo-Editor"))
    parser.add_argument("--smoke-test", type=Path, help=tr("Offline-Funktionstest in MEMENTO_DATA_DIR; JSON-Bericht als Zieldatei"))
    parser.add_argument("--restore-backup", type=Path, help=tr("Wiederherstellungsdialog mit dieser Sicherung öffnen"))
    parser.add_argument("--check-media-folder", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--language", choices=("en", "de"), help="Interface language / Sprache (en, de); overrides the saved choice for this run")
    options = parser.parse_args()
    if options.check_media_folder is not None:
        from memento.media.availability import check_folder
        print(json.dumps(check_folder(options.check_media_folder)))
        return 0
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Memento_v2")
    app.setOrganizationName("Memento_v2")
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "resources" / "memento.ico")))
    app.setStyle("Fusion")
    if os.environ.get("MEMENTO_DATA_DIR"):
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(default_database_path().parent))
    configure(QSettings(), app, options.language)
    windows_font = Path("C:/Windows/Fonts/segoeui.ttf")
    if windows_font.is_file():
        QFontDatabase.addApplicationFont(str(windows_font))
        app.setFont(QFont("Segoe UI", 10))
    lock = LibraryLock(default_database_path())
    try:
        if options.smoke_test and not os.environ.get("MEMENTO_DATA_DIR"):
            raise ValueError(tr("Der Funktionstest benötigt einen separaten MEMENTO_DATA_DIR."))
        if options.smoke_test and default_database_path().exists():
            raise ValueError(tr("Der Funktionstest benötigt ein unbenutztes Datenverzeichnis."))
        lock.acquire()
        library = None
        try:
            if not options.restore_backup:
                if default_database_path().with_suffix(".restore.json").exists():
                    pending = RecoveryDialog(default_database_path(), library_lock=lock, startup=True)
                    pending.finish_pending()
                    pending.exec()
                    if not pending.pending_finished and not pending.restored:
                        return 1
                library = MediaLibrary()
        except (sqlite3.Error, RuntimeError, ValueError) as exc:
            if options.smoke_test:
                raise
            box = QMessageBox()
            box.setWindowTitle(tr("Bibliothek konnte nicht geöffnet werden"))
            box.setText(display_message(str(exc)))
            box.setInformativeText(tr("Die vorhandenen Daten bleiben erhalten. Möchtest du eine Bibliothekssicherung auswählen?"))
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            box.button(QMessageBox.StandardButton.Yes).setText(tr("Sicherung auswählen"))
            box.button(QMessageBox.StandardButton.No).setText(tr("Beenden"))
            if box.exec() != QMessageBox.StandardButton.Yes:
                return 1
        if library is None:
            if options.smoke_test:
                raise ValueError(tr("Funktionstest und Wiederherstellung können nicht kombiniert werden."))
            recovery = RecoveryDialog(default_database_path(), library_lock=lock, startup=True, initial_backup=options.restore_backup)
            recovery.exec()
            if not recovery.restored:
                return 1
            library = MediaLibrary()
            if recovery.recovery_result.roots:
                settings = QSettings()
                folders = settings.value("library/folders", [], type=list)
                settings.setValue("library/folders", list(dict.fromkeys(folders + list(recovery.recovery_result.roots))))
        window = MainWindow(library, library_lock=lock)
        window.show()
        app.setQuitOnLastWindowClosed(True)
        if options.smoke_test:
            def run_smoke():
                try:
                    from memento.smoke import check_installed_app
                    report = {"status": "complete", **check_installed_app(window.library, window)}
                except Exception as exc:
                    report = {"status": "failed", "error": display_message(str(exc))}
                options.smoke_test.parent.mkdir(parents=True, exist_ok=True)
                options.smoke_test.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                app.exit(0 if report["status"] == "complete" else 1)
            QTimer.singleShot(0, run_smoke)
        return app.exec()
    except Exception as exc:
        if options.smoke_test:
            options.smoke_test.parent.mkdir(parents=True, exist_ok=True)
            options.smoke_test.write_text(json.dumps({"status": "failed", "error": display_message(str(exc))}), encoding="utf-8")
        else:
            title = tr("Memento läuft bereits") if isinstance(exc, LibraryAlreadyOpen) else tr("Memento konnte nicht starten")
            QMessageBox.critical(None, title, display_message(str(exc)))
        return 1
    finally:
        lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
