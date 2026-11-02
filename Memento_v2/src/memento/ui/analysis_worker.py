from __future__ import annotations

from memento.i18n import display_message

from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from memento.application.shot_analysis import ShotAnalysisService


class AnalysisWorker(QObject):
    progress = Signal(object)
    completed = Signal(str, str)
    failed = Signal(str, str)

    def __init__(self, service: ShotAnalysisService, job_id: str, cancel_token: Event):
        super().__init__()
        self.service = service
        self.job_id = job_id
        self.cancel_token = cancel_token

    @Slot()
    def run(self):
        try:
            status = self.service.run(self.job_id, self.cancel_token, self.progress.emit)
            self.completed.emit(self.job_id, status.value)
        except Exception as exc:
            self.failed.emit(self.job_id, display_message(str(exc)).strip() or type(exc).__name__)
