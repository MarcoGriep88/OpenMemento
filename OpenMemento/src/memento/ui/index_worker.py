from __future__ import annotations

from memento.i18n import display_message

from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from memento.application.indexing import MediaIndexService


class IndexWorker(QObject):
    progress = Signal(object)
    completed = Signal(str, str)
    failed = Signal(str, str)

    def __init__(
        self,
        service: MediaIndexService,
        job_id: str,
        cancel_token: Event,
    ) -> None:
        super().__init__()
        self.service = service
        self.job_id = job_id
        self.cancel_token = cancel_token

    @Slot()
    def run(self) -> None:
        try:
            status = self.service.run(
                self.job_id,
                on_progress=self.progress.emit,
                cancel_token=self.cancel_token,
            )
        except Exception as exc:
            self.failed.emit(self.job_id, display_message(str(exc)) or type(exc).__name__)
        else:
            self.completed.emit(self.job_id, status.value)
