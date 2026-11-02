from __future__ import annotations

from memento.i18n import tr, display_message

import json
from threading import Event

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from memento.ai.gemini import GeminiProvider
from memento.application.semantic_analysis import SemanticAnalysisService
from memento.library.semantic import SemanticRepository
from memento.security.credentials import get_gemini_key


class SemanticWorker(QObject):
    progress = Signal(object)
    finished = Signal(str)

    def __init__(self, repository, job_id, cancel_token, max_requests=25, user_prompt=""):
        super().__init__()
        self.repository, self.job_id, self.cancel_token = repository, job_id, cancel_token
        self.max_requests = max_requests
        self.user_prompt = user_prompt

    @Slot()
    def run(self):
        try:
            job = self.repository.get_job(self.job_id)
            secret = get_gemini_key()
            if not secret:
                self.finished.emit(tr("Kein Gemini-Schlüssel gespeichert. Bitte Einstellungen öffnen."))
                return
            provider = (GeminiProvider(secret, job["model"], user_prompt=self.user_prompt)
                        if self.user_prompt else GeminiProvider(secret, job["model"]))
            service = SemanticAnalysisService(self.repository, provider)
            status = service.run(self.job_id, self.cancel_token, self.progress.emit, max_requests=self.max_requests)
            self.finished.emit({
                "complete": tr("Analyse abgeschlossen."), "cancelled": tr("Analyse abgebrochen; fertige Ergebnisse bleiben gespeichert."),
                "complete_with_errors": tr("Analyse mit Fehlern abgeschlossen. Details stehen in der Tabelle; Fortsetzen versucht fehlgeschlagene Bereiche erneut."),
                "request_limit": tr("Anfragelimit für diesen Start erreicht; fertige Ergebnisse bleiben gespeichert. Erst erneutes Fortsetzen erlaubt weitere Aufrufe."),
            }[status])
        except Exception:
            self.finished.emit(tr("KI-Auftrag konnte nicht ausgeführt werden. Schlüssel, Modell und lokale Bibliothek prüfen."))


class SemanticDialog(QDialog):
    """Explicit upload scope, consent, progress and persistent results in one place."""

    def __init__(self, library, assets, model, parent=None, user_prompt="", profile=None):
        super().__init__(parent)
        self.repository = SemanticRepository(library) if profile is None else SemanticRepository(library, profile)
        self.user_prompt = user_prompt
        self.assets = assets
        self.thread = None
        self.worker = None
        self.cancel_token = Event()
        self.page_offset = 0
        self.page_size = 100
        self.setWindowTitle(tr("Erinnerungen mit Gemini analysieren"))
        self.resize(1000, 760)
        layout = QVBoxLayout(self)
        self.jobs = QComboBox()
        new_job = self.repository.create_job(assets, "gemini", model)
        video_count = tr("1 Video") if len(assets) == 1 else tr("{0} Videos", len(assets))
        self.jobs.addItem(tr("Neue Auswahl · {0} · {1}", video_count, model), new_job)
        for job in self.repository.resumable_jobs():
            if (job["job_id"] != new_job and job["version"] == self.repository.profile
                    and {row["asset_id"] for row in self.repository.items(job["job_id"])} <= {asset.asset_id for asset in assets}):
                self.jobs.addItem(tr("Fortsetzen · {0} · {1}", job['created_at'][:19], job['model']), job["job_id"])
        self.jobs.currentIndexChanged.connect(self.job_changed)
        layout.addWidget(self.jobs)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.notice)
        if user_prompt:
            prompt_notice = QLabel(tr("Zusätzlicher Prompt an Gemini: ") + user_prompt)
            prompt_notice.setTextFormat(Qt.TextFormat.PlainText)
            prompt_notice.setWordWrap(True)
            layout.addWidget(prompt_notice)
        privacy = QLabel(
            tr("Nach Klick auf „An Google senden“ werden noch nicht gespeicherte Bereiche des gesamten ausgewählten Auftrags (auch auf weiteren Tabellenseiten, bis zum eingestellten Aufruflimit) lokal in MP4 mit höchstens 640 px, 12 Bildern/s und Originalton umgewandelt und direkt an Google Gemini gesendet. Aufnahmedatum, Dateiname und Quellpfad werden nicht mitgesendet; sichtbare Personen und hörbare Inhalte schon. Die Originaldateien bleiben unverändert. Temporäre Analysevideos werden anschließend lokal entfernt. Es wird kein Google-Files-Speicher angelegt. Googles Verarbeitung und Aufbewahrung richten sich nach deinen Gemini-Kontobedingungen. Kosten entstehen in deinem Google-Konto. Vorübergehende HTTP-Fehler werden bis zu zweimal wiederholt. Ein laufender Netzwerkaufruf endet beim Abbruch erst nach Antwort oder Netzwerk-Timeout.")
        )
        privacy.setWordWrap(True)
        privacy.setObjectName("noticeCard")
        layout.addWidget(privacy)
        limits = QHBoxLayout()
        limits.addWidget(QLabel(tr("Maximale Anbieteraufrufe pro Start (inklusive Wiederholungen)")))
        self.request_limit = QSpinBox()
        self.request_limit.setRange(1, 10_000)
        self.request_limit.setValue(25)
        self.request_limit.setToolTip(tr("Jeder Klick auf „An Google senden / Fortsetzen“ erlaubt höchstens diese Anzahl Aufrufe. Fehler und Wiederholungen zählen mit; lokale Cachetreffer nicht. Kein Geldlimit."))
        limits.addWidget(self.request_limit)
        layout.addLayout(limits)
        self.request_limit.valueChanged.connect(self.update_notice)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([tr("QUELLE"), tr("BEREICH (s)"), tr("STATUS"), tr("ERINNERUNGEN / FEHLER")])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        pages = QHBoxLayout()
        self.previous_page = QPushButton(tr("Vorherige Bereiche"))
        self.next_page = QPushButton(tr("Nächste Bereiche"))
        self.page_label = QLabel()
        self.previous_page.clicked.connect(lambda: self.change_page(-1))
        self.next_page.clicked.connect(lambda: self.change_page(1))
        pages.addWidget(self.previous_page)
        pages.addWidget(self.page_label, 1)
        pages.addWidget(self.next_page)
        layout.addLayout(pages)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.status = QLabel(tr("Noch keine Übertragung gestartet."))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.start_button = QPushButton(tr("An Google senden / Fortsetzen"))
        self.start_button.clicked.connect(self.start)
        buttons.addWidget(self.start_button)
        self.cancel_button = QPushButton(tr("Analyse abbrechen"))
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        buttons.addWidget(self.cancel_button)
        close = QPushButton(tr("Schließen"))
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self):
        self.update_notice()
        self.refresh_page()

    def job_changed(self):
        self.page_offset = 0
        self.refresh()

    def change_page(self, direction):
        self.page_offset = max(0, self.page_offset + direction * self.page_size)
        self.refresh_page()

    def refresh_page(self):
        items, total, self.page_offset = self.repository.inspection_page(
            self.jobs.currentData(), offset=self.page_offset, limit=self.page_size)
        first = self.page_offset + 1 if total else 0
        self.page_label.setText(tr("Bereiche {0}–{1} von {2}", first, self.page_offset + len(items), total))
        self.previous_page.setEnabled(self.page_offset > 0)
        self.next_page.setEnabled(self.page_offset + len(items) < total)
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            cached = item["cached_key"] is not None
            detail = display_message(item["error"] or "")
            if cached:
                moments = json.loads(item["moments_json"])
                detail = "\n".join(
                    f"{item['start_seconds'] + moment['start_seconds']:.1f}–{item['start_seconds'] + moment['end_seconds']:.1f} s: "
                    f"{moment['description']} ({'; '.join(moment['reasons'])})" for moment in moments
                ) or tr("Keine erinnerungswürdigen Bereiche erkannt.")
            values = (item["source_path"] or tr("Quelle fehlt"), f"{item['start_seconds']:.1f}–{item['end_seconds']:.1f}",
                      tr("Gespeichert") if cached else {"pending": tr("Wartet"), "processing": tr("Unterbrochen"), "failed": tr("Fehler")}.get(item["status"], item["status"]), detail)
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                self.table.setItem(row, column, cell)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, 250)
        self.table.setColumnWidth(1, 130)
        self.table.setColumnWidth(2, 120)
        self.table.resizeRowsToContents()

    def update_notice(self):
        job_id = self.jobs.currentData()
        estimate = self.repository.estimate(job_id)
        job = self.repository.get_job(job_id)
        pending = estimate["pending"]
        cached = estimate["total"] - pending
        limit = self.request_limit.value()
        attempts = estimate["attempts"]
        self.notice.setText(
            tr("Anbieter: Google Gemini · Modell: {0}\nGesamter offener Auftrag: {1} {2} · {3} Minuten Video mit Ton · {4} {5} im lokalen Cache. Höchstens {6} MiB Video vor Base64-Kodierung ohne Wiederholungen (mit Wiederholungen bis zum Dreifachen). Die tatsächlichen Gebühren hängen vom Modell und dessen Tokenabrechnung ab; dies ist kein Geldbetrag.\nGespeicherte erfolgreiche Antworten: {7} Eingabe- und {8} Ausgabetokens. Abgebrochene oder fehlgeschlagene Anfragen können zusätzlich berechnet werden.\nDieser Start erlaubt höchstens {9} {10} einschließlich Wiederholungen (maximal {11} MiB vor Base64-Kodierung). Bisher {12} {13} in diesem Auftrag. Erneutes Fortsetzen erlaubt wieder die eingestellte Anzahl; dies ist kein Geldlimit.", job['model'], pending, tr("neuer Bereich") if pending == 1 else tr("neue Bereiche"), format(estimate['seconds'] / 60, f'.1f'), cached, tr("Bereich") if cached == 1 else tr("Bereiche"), estimate['pending'] * 8, estimate['input_tokens'], estimate['output_tokens'], limit, tr("Anbieteraufruf") if limit == 1 else tr("Anbieteraufrufe"), min(pending * 3, limit) * 8, attempts, tr("versuchter Aufruf") if attempts == 1 else tr("versuchte Aufrufe"))
        )

    def start(self):
        if self.thread is not None:
            return
        self.cancel_token.clear()
        self.thread = QThread(self)
        self.worker = SemanticWorker(self.repository, self.jobs.currentData(), self.cancel_token, self.request_limit.value(), self.user_prompt)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.status.setText)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.stopped)
        self.thread.finished.connect(self.thread.deleteLater)
        self.jobs.setEnabled(False)
        self.request_limit.setEnabled(False)
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status.setText(tr("Lokale Vorbereitung / Übertragung an Google läuft …"))
        self.thread.start()

    def on_progress(self, value):
        self.progress.setRange(0, value.total)
        self.progress.setValue(value.completed + value.failed)
        self.status.setText(tr("{0} verarbeitet · {1} aus Cache · {2} Fehler", value.completed, value.cached, value.failed))
        if value.request_limit is not None:
            self.status.setText(self.status.text() + tr(" · {0}/{1} Anbieteraufrufe", value.requests, value.request_limit))

    def stopped(self):
        self.thread = self.worker = None
        self.jobs.setEnabled(True)
        self.request_limit.setEnabled(True)
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.refresh()

    def cancel(self):
        self.cancel_token.set()
        self.cancel_button.setEnabled(False)
        self.status.setText(tr("Abbruch angefordert; laufenden Aufruf abwarten …"))

    def reject(self):
        if self.thread is not None:
            self.cancel()
            return
        super().reject()

    def closeEvent(self, event):
        if self.thread is not None:
            self.cancel()
            event.ignore()
        else:
            event.accept()
