from __future__ import annotations

from memento.i18n import tr, display_message

from datetime import datetime
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout

from memento.library.recovery import BackupInfo, create_backup, finish_pending_restore, inspect_backup, restore_backup


class RecoveryWorker(QObject):
    result = Signal(object)
    failed = Signal(str)
    progress = Signal(object)

    def __init__(self, operation, token):
        super().__init__()
        self.operation, self.token = operation, token

    @Slot()
    def run(self):
        try:
            self.result.emit(self.operation(self.token, self.progress.emit))
        except Exception as exc:
            self.failed.emit(display_message(str(exc)) or tr("Der Vorgang ist fehlgeschlagen."))


class RecoveryDialog(QDialog):
    def __init__(self, database: Path, parent=None, library_lock=None, startup=False, initial_backup=None):
        super().__init__(parent)
        self.database, self.library_lock, self.startup = Path(database), library_lock, startup
        self.thread = self.worker = None
        self.token = Event()
        self.info: BackupInfo | None = None
        self.restored = False
        self.pending_finished = False
        self.recovery_result = None
        self.kind = None
        self._publishing = False
        self.setWindowTitle(tr("Bibliothek sichern und wiederherstellen"))
        self.resize(720, 420)
        layout = QVBoxLayout(self)
        note = QLabel(
            tr("Sicherungen enthalten Medienindex und Analyseergebnisse. Originalvideos, Filmprojekte, Vorschaubilder und API-Schlüssel werden nicht mitgesichert. Vor einer Wiederherstellung wird der aktuelle Bibliotheksstand separat erhalten. Die ausgewählte Sicherung ersetzt anschließend den Index; spätere Indexänderungen sind dann nur noch in der Sicherheitskopie vorhanden.")
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        actions = QHBoxLayout()
        self.backup_button = QPushButton(tr("Neue Sicherung erstellen"))
        self.backup_button.clicked.connect(self.backup)
        actions.addWidget(self.backup_button)
        self.choose_button = QPushButton(tr("Sicherung auswählen und prüfen"))
        self.choose_button.clicked.connect(self.choose)
        actions.addWidget(self.choose_button)
        layout.addLayout(actions)
        self.details = QLabel(tr("Noch keine Wiederherstellungsquelle ausgewählt."))
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.restore_button = QPushButton(tr("Geprüfte Sicherung wiederherstellen"))
        self.restore_button.setEnabled(False)
        self.restore_button.clicked.connect(self.restore)
        layout.addWidget(self.restore_button)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.status = QLabel(tr("Kein Vorgang gestartet."))
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        bottom = QHBoxLayout()
        self.cancel_button = QPushButton(tr("Vorgang abbrechen"))
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.token.set)
        bottom.addWidget(self.cancel_button)
        close = QPushButton(tr("Schließen"))
        close.clicked.connect(self.reject)
        bottom.addWidget(close)
        layout.addLayout(bottom)
        if initial_backup:
            QTimer.singleShot(0, lambda: self.inspect(Path(initial_backup)))

    def run_operation(self, kind, operation):
        if self.thread is not None:
            return
        self.kind = kind
        self._publishing = False
        self.token.clear()
        self.choose_button.setEnabled(False)
        self.backup_button.setEnabled(False)
        self.restore_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.thread = QThread(self)
        self.worker = RecoveryWorker(operation, self.token)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.result.connect(self.completed)
        self.worker.failed.connect(self.status.setText)
        for signal in (self.worker.result, self.worker.failed):
            signal.connect(self.thread.quit)
            signal.connect(self.worker.deleteLater)
        self.worker.progress.connect(self.on_progress)
        self.thread.finished.connect(self.stopped)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def stopped(self):
        self.thread = self.worker = None
        self.choose_button.setEnabled(True)
        self.backup_button.setEnabled(True)
        self.restore_button.setEnabled(self.info is not None)
        self.cancel_button.setEnabled(False)
        self.progress.setVisible(False)
        if self.startup and (self.restored or self.pending_finished):
            self.accept()

    def completed(self, value):
        if self.kind == "inspect":
            self.info = value
            self.details.setText(tr("{0}\nSchema {1} · {2} Medien · {3} gespeicherte KI-Bereiche", value.path, value.schema_version, value.assets, value.semantic_ranges))
            self.status.setText(tr("Basisprüfung abgeschlossen. Vollständige Prüfung und gegebenenfalls Migration folgen vor dem Austausch. Der Index wird erst nach deiner Bestätigung ersetzt."))
        elif self.kind == "backup":
            self.status.setText(tr("Sicherung erstellt: {0}", value.path))
        elif self.kind == "finish":
            self.pending_finished = bool(value)
            self.status.setText(tr("Unterbrochene Wiederherstellung abgeschlossen."))
        else:
            self.restored, self.recovery_result = True, value
            self.status.setText(tr("Bibliothek wiederhergestellt. Bisheriger Stand: {0}", value.safety_backup or tr("Keine vorherige Bibliothek vorhanden")))

    def on_progress(self, value):
        self.progress.setRange(0, max(1, value.total))
        self.progress.setValue(value.completed)
        self.status.setText(display_message(value.message))
        if value.phase == "publish":
            self._publishing = True
            self.cancel_button.setEnabled(False)

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Sicherung auswählen"), str(self.database.parent / "backups"), tr("SQLite-Sicherung (*.sqlite3)"))
        if path:
            self.inspect(Path(path))

    def finish_pending(self):
        self.status.setText(tr("Gespeicherter Bibliotheksaustausch wird sicher abgeschlossen …"))
        self.run_operation("finish", lambda token, progress: finish_pending_restore(self.database, self.library_lock))
        self.cancel_button.setEnabled(False)

    def inspect(self, path):
        self.info = None
        self.details.setText(str(path))
        self.status.setText(tr("Sicherung wird geprüft …"))
        self.run_operation("inspect", lambda token, progress: inspect_backup(path, token))

    def backup(self):
        name = f"library-{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
        path, _ = QFileDialog.getSaveFileName(self, tr("Neue Bibliothekssicherung"), str(self.database.parent / "backups" / name), tr("SQLite-Sicherung (*.sqlite3)"))
        if path:
            self.status.setText(tr("Bibliothek wird gesichert …"))
            self.run_operation("backup", lambda token, progress: create_backup(self.database, Path(path), token, progress, self.library_lock))

    def restore(self):
        if self.info is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle(tr("Bibliothek aus Sicherung übernehmen"))
        box.setText(tr("Die geprüfte Sicherung mit {0} Medien und {1} KI-Bereichen wird den aktuellen Index ersetzen.", self.info.assets, self.info.semantic_ranges))
        box.setInformativeText(tr("Der aktuelle Stand wird vorher separat gesichert. Originalvideos, Filmprojekte und Schlüssel bleiben unverändert. Ein älterer, noch offener Wiederherstellungsauftrag wird archiviert."))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText("Wiederherstellen")
        box.button(QMessageBox.StandardButton.No).setText(tr("Abbrechen"))
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        path = self.info.path
        self.run_operation("restore", lambda token, progress: restore_backup(path, self.database, token, progress,
                                                                            self.library_lock, replace_pending=True))

    def reject(self):
        if self.thread is not None:
            if self.kind == "finish" or self._publishing:
                self.status.setText(tr("Der gespeicherte Austausch wird zuerst sicher abgeschlossen …"))
            else:
                self.token.set()
                self.status.setText(tr("Abbruch angefordert; sicheren Abschluss abwarten …"))
            return
        super().reject()

    def closeEvent(self, event):
        if self.thread is not None:
            self.reject()
            event.ignore()
        else:
            event.accept()
