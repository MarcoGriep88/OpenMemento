"""Bounded asynchronous folder probes; never touch network paths on the UI thread."""
from __future__ import annotations

from memento.i18n import tr

import json
import sys
from collections import deque

from PySide6.QtCore import QObject, QProcess, QTimer, Signal


class FolderAvailabilityChecker(QObject):
    checked = Signal(str, bool, str)
    TIMEOUT_MS = 5000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pending = deque()
        self._process = None
        self._generation = 0

    def check(self, folders):
        self.stop()
        self._pending.extend(dict.fromkeys(folders))
        self._next()

    def stop(self):
        self._generation += 1
        self._pending.clear()
        if self._process is not None:
            self._process.kill()
            self._process = None

    def _next(self):
        if not self._pending:
            return
        folder = self._pending.popleft()
        generation = self._generation
        process = QProcess(self)
        self._process = process
        timer = QTimer(process)
        timer.setSingleShot(True)
        done = False

        def complete(available, detail):
            nonlocal done
            if done:
                return
            done = True
            timer.stop()
            if generation == self._generation:
                self._process = None
                self.checked.emit(folder, available, detail)
                QTimer.singleShot(0, self._next)

        def finished(exit_code, _status):
            if not done:
                try:
                    result = json.loads(bytes(process.readAllStandardOutput()))
                    if exit_code != 0 or type(result.get("available")) is not bool:
                        raise ValueError(tr("Ungültige Antwort"))
                    complete(result["available"], str(result.get("detail", "")))
                except (ValueError, TypeError, AttributeError):
                    complete(False, tr("Die Erreichbarkeit konnte nicht geprüft werden."))
            process.deleteLater()

        def timed_out():
            complete(False, tr("Zeitüberschreitung beim Zugriff. Netzwerkverbindung oder Einbindung prüfen."))
            process.kill()

        def failed(error):
            if error == QProcess.ProcessError.FailedToStart:
                complete(False, tr("Die Erreichbarkeitsprüfung konnte nicht gestartet werden."))
                process.deleteLater()

        process.finished.connect(finished)
        process.errorOccurred.connect(failed)
        timer.timeout.connect(timed_out)
        if getattr(sys, "frozen", False):
            arguments = ["--check-media-folder", folder]
        else:
            arguments = ["-m", "memento.media.availability", folder]
        process.start(sys.executable, arguments)
        timer.start(self.TIMEOUT_MS)
