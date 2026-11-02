"""First-cut inspection, explicit corrections and local export."""
from __future__ import annotations

from memento.i18n import tr, display_message

from copy import deepcopy
from datetime import date
from pathlib import Path
from threading import Event
from tempfile import TemporaryDirectory
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QSlider,
)

from memento.application.movie_planning import MoviePlanningService
from memento.application.rendering import MovieRenderService, RenderCancelled, RenderSettings
from memento.application.source_relinking import relink_movie_sources
from memento.domain.movie import MoviePreferences
from memento.domain.editing import EDITING_TEMPLATES, EditingStyle
from memento.domain.movie_history import MovieHistory
from memento.library.movies import load_movie, save_movie
from memento.library.semantic import SemanticRepository
from memento.ui.candidate_dialog import CandidateDialog
from memento.ui.event_review_dialog import EventReviewDialog


class MovieWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(object)

    def __init__(self, operation, token):
        super().__init__()
        self.operation, self.token = operation, token

    @Slot()
    def run(self):
        try:
            if self.token.is_set():
                raise RenderCancelled(tr("Auftrag abgebrochen."))
            result = self.operation(self.token, self.progress.emit)
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(display_message(str(exc)) or tr("Der Auftrag konnte nicht abgeschlossen werden."))


class MovieDialog(QDialog):
    plan_saved = Signal(object)
    movie_exported = Signal(str)

    def __init__(self, library, start, end, target_seconds, model, parent=None):
        super().__init__(parent)
        self.library = library
        self.planner = MoviePlanningService(SemanticRepository(library))
        self.start_date, self.end_date, self.model = start, end, model
        self.target_seconds = target_seconds
        self.plan = None
        self.history = MovieHistory()
        self.candidates = []
        self.candidates_loaded = False
        self.candidate_warnings = []
        self.open_candidates_after_load = False
        self.thread = self.worker = None
        self.token = Event()
        self.output = None
        self.music_path = ""
        self.preview_directory = None
        self.movie_preview_path = self.movie_preview_plan = None
        self.preview_url = QUrl()
        self.preview_kind = None
        self.preview_pending = False
        self.project_path = library.path.parent / "movies" / f"{uuid4()}.memento.json"
        self.setWindowTitle(tr("Familienfilm planen und prüfen"))
        self.resize(1180, 800)
        self.setMinimumSize(950, 650)
        layout = QVBoxLayout(self)
        self.editor = QWidget()
        edit = QVBoxLayout(self.editor)
        edit.setContentsMargins(0, 0, 0, 0)
        heading = QHBoxLayout()
        self.title = QLineEdit(tr("Neuer Familienfilm"))
        self.title.setPlaceholderText(tr("Filmtitel"))
        self.title.editingFinished.connect(self.persist)
        heading.addWidget(self.title, 1)
        self.duration = QDoubleSpinBox()
        self.duration.setRange(2, 10800)
        self.duration.setValue(target_seconds)
        self.duration.setSuffix(tr(" s Zielzeit (ca.)"))
        self.duration.setToolTip(tr("Richtwert: Bei weniger verfügbarem Material wird der Film kürzer; längeres Material wird passend ausgewählt und gekürzt."))
        heading.addWidget(self.duration)
        self.generate_button = QPushButton(tr("Auswahl erzeugen / neu planen"))
        self.generate_button.clicked.connect(self.generate)
        heading.addWidget(self.generate_button)
        edit.addLayout(heading)
        style_row = QHBoxLayout()
        style_row.addWidget(QLabel(tr("Schnittvorlage")))
        self.style_combo = QComboBox()
        for key, (label, _) in EDITING_TEMPLATES.items():
            self.style_combo.addItem(tr(label), key)
        self.style_combo.setCurrentIndex(self.style_combo.findData("cut"))
        style_row.addWidget(self.style_combo, 1)
        self.transition_duration = QDoubleSpinBox()
        self.transition_duration.setRange(0.1, 2)
        self.transition_duration.setSingleStep(0.1)
        self.transition_duration.setValue(0.6)
        self.transition_duration.setSuffix(tr(" s Übergang"))
        style_row.addWidget(self.transition_duration)
        self.apply_style_button = QPushButton(tr("Vorlage übernehmen"))
        self.apply_style_button.clicked.connect(self.apply_style)
        style_row.addWidget(self.apply_style_button)
        edit.addLayout(style_row)
        self.style_hint = QLabel(tr("Gilt für alle Clipwechsel in Filmvorschau und Export. Die Auswahl und deine Schnitte bleiben erhalten."))
        self.style_hint.setWordWrap(True)
        edit.addWidget(self.style_hint)
        self.summary = QLabel(tr("Der erste Schnitt nutzt gespeicherte Analyseergebnisse. Es werden keine Medien übertragen."))
        self.summary.setWordWrap(True)
        edit.addWidget(self.summary)
        file_buttons = QHBoxLayout()
        self.project_file_buttons = []
        for label, callback in ((tr("Filmplan öffnen"), self.open_project), (tr("Filmplan speichern unter …"), self.save_project),
                                (tr("Momente ein-/ausschließen"), self.edit_candidates),
                                (tr("Ereignisse und Zeitverteilung"), self.review_events)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            file_buttons.addWidget(button)
            self.project_file_buttons.append(button)
        edit.addLayout(file_buttons)
        history_buttons = QHBoxLayout()
        self.undo_button = QPushButton(tr("Rückgängig"))
        self.redo_button = QPushButton(tr("Wiederholen"))
        self.undo_button.clicked.connect(lambda: self.restore_edit(-1))
        self.redo_button.clicked.connect(lambda: self.restore_edit(1))
        history_buttons.addWidget(self.undo_button)
        history_buttons.addWidget(self.redo_button)
        history_buttons.addStretch()
        edit.addLayout(history_buttons)
        self.undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self.redo_shortcut = QShortcut(QKeySequence.StandardKey.Redo, self)
        self.undo_shortcut.activated.connect(lambda: self.restore_edit(-1))
        self.redo_shortcut.activated.connect(lambda: self.restore_edit(1))
        splitter = QSplitter()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([tr("EREIGNIS"), tr("QUELLE"), tr("START (s)"), tr("ENDE (s)"), tr("AUSWAHLGRÜNDE")])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self.selected)
        self.table.horizontalHeader().setStretchLastSection(True)
        splitter.addWidget(self.table)
        preview = QWidget()
        preview_layout = QVBoxLayout(preview)
        self.video = QVideoWidget()
        self.video.setMinimumSize(280, 160)
        preview_layout.addWidget(self.video, 1)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.mediaStatusChanged.connect(self.media_status_changed)
        self.player.positionChanged.connect(self.preview_position)
        self.player.durationChanged.connect(self.preview_duration)
        self.player.errorOccurred.connect(self.preview_error)
        self.preview_segment = None
        play_button = QPushButton(tr("Gewähltes Segment abspielen"))
        play_button.clicked.connect(self.preview)
        preview_layout.addWidget(play_button)
        self.movie_preview_button = QPushButton(tr("Gesamten Film als Vorschau ansehen"))
        self.movie_preview_button.clicked.connect(self.preview_movie)
        preview_layout.addWidget(self.movie_preview_button)
        self.pause_button = QPushButton(tr("Pause / weiter"))
        self.pause_button.clicked.connect(self.pause_preview)
        preview_layout.addWidget(self.pause_button)
        self.preview_slider = QSlider(Qt.Orientation.Horizontal)
        self.preview_slider.setEnabled(False)
        self.preview_slider.sliderMoved.connect(self.seek_preview)
        preview_layout.addWidget(self.preview_slider)
        self.preview_clock = QLabel(tr("Filmvorschau: noch nicht erstellt"))
        preview_layout.addWidget(self.preview_clock)
        stop_button = QPushButton(tr("Vorschau stoppen"))
        stop_button.clicked.connect(self.stop_preview)
        preview_layout.addWidget(stop_button)
        splitter.addWidget(preview)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        edit.addWidget(splitter, 1)
        trim = QHBoxLayout()
        self.trim_start, self.trim_end = QDoubleSpinBox(), QDoubleSpinBox()
        for spin in (self.trim_start, self.trim_end):
            spin.setDecimals(3)
            spin.setRange(0, 1e7)
            spin.setSuffix(" s")
        trim.addWidget(QLabel(tr("Quelle von")))
        trim.addWidget(self.trim_start)
        trim.addWidget(QLabel(tr("bis")))
        trim.addWidget(self.trim_end)
        for label, callback in ((tr("Schnitt übernehmen"), self.apply_trim), (tr("Entfernen"), self.remove_segment),
                                ("↑", lambda: self.move_segment(-1)), ("↓", lambda: self.move_segment(1))):
            button = QPushButton(label)
            button.clicked.connect(callback)
            trim.addWidget(button)
        edit.addLayout(trim)
        event_row = QHBoxLayout()
        self.event_combo = QComboBox()
        self.event_combo.currentIndexChanged.connect(self.event_selected)
        event_row.addWidget(self.event_combo, 1)
        self.event_weight = QDoubleSpinBox()
        self.event_weight.setRange(0.1, 5)
        self.event_weight.setSingleStep(0.25)
        self.event_weight.setValue(1)
        event_row.addWidget(QLabel(tr("Relative Bedeutung")))
        event_row.addWidget(self.event_weight)
        weight_button = QPushButton(tr("Gewicht übernehmen"))
        weight_button.clicked.connect(self.apply_weight)
        event_row.addWidget(weight_button)
        edit.addLayout(event_row)
        self.warnings = QLabel()
        self.warnings.setWordWrap(True)
        edit.addWidget(self.warnings)
        render_row = QHBoxLayout()
        render_button = QPushButton(tr("Film lokal als MP4 exportieren"))
        render_button.clicked.connect(self.export)
        render_row.addWidget(render_button)
        watch_button = QPushButton(tr("Exportierten Film öffnen"))
        watch_button.clicked.connect(self.watch)
        render_row.addWidget(watch_button)
        edit.addLayout(render_row)
        layout.addWidget(self.editor, 1)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.status = QLabel(tr("Automatische Speicherung: {0}", self.project_path))
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.cancel_button = QPushButton(tr("Laufenden Auftrag abbrechen"))
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.token.set)
        layout.addWidget(self.cancel_button)
        self.update_history_controls()

    def update_history_controls(self):
        for control in (self.undo_button, self.undo_shortcut):
            control.setEnabled(self.thread is None and self.history.can_undo)
        for control in (self.redo_button, self.redo_shortcut):
            control.setEnabled(self.thread is None and self.history.can_redo)

    def restore_edit(self, direction):
        if self.thread is not None or self.plan is None:
            return
        # Finish pending title edits before undo; do not fold them into another step.
        if not self.persist():
            return
        try:
            plan = self.history.restore(direction, lambda value: save_movie(self.project_path, value))
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, tr("Filmplan nicht gespeichert"), display_message(str(exc)))
            return
        if plan is not None:
            self.plan = plan
            self.output = None
            self.title.setText(plan.title)
            self.duration.setValue(plan.target_seconds)
            self.refresh()
            self.status.setText(tr("Änderung rückgängig gemacht und gespeichert.") if direction == -1
                                else tr("Änderung wiederholt und gespeichert."))
            self.plan_saved.emit(self.plan)
        self.update_history_controls()

    def run_operation(self, operation, done):
        if self.thread is not None:
            return
        self.stop_preview()
        self.token.clear()
        self.editor.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self.thread = QThread(self)
        self.update_history_controls()
        self.worker = MovieWorker(operation, self.token)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(done)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.status.setText)
        self.worker.failed.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.failed.connect(self.worker.deleteLater)
        self.worker.progress.connect(self.on_progress)
        self.thread.finished.connect(self.stopped)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def stopped(self):
        self.thread = self.worker = None
        self.editor.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress.setVisible(False)
        self.update_history_controls()
        if self.open_candidates_after_load:
            self.open_candidates_after_load = False
            if not self.token.is_set():
                self.show_candidates()

    def on_progress(self, value):
        self.progress.setRange(0, value.total)
        self.progress.setValue(value.completed)
        self.status.setText(tr("{0} · {1} Segmente aus Rendercache", display_message(value.message), value.cached))

    def generate(self):
        if self.thread is not None or (self.plan is not None and not self.persist()):
            return
        preferences = deepcopy(self.plan.preferences) if self.plan else MoviePreferences()
        plan_id = self.plan.plan_id if self.plan else None
        start = self.start_date if self.plan is None else date.fromisoformat(self.plan.date_from)
        end = self.end_date if self.plan is None else date.fromisoformat(self.plan.date_to)
        provider = self.plan.provider if self.plan else "gemini"
        model = self.plan.model if self.plan else self.model
        target = self.duration.value()
        title = self.title.text().strip()
        style = self.plan.editing_style if self.plan else EditingStyle(self.style_combo.currentData(), self.transition_duration.value())

        def operation(token, progress):
            plan = self.planner.build(start, end, target, provider, model, preferences, plan_id, cancel_token=token)
            plan.editing_style = style
            candidates, _ = self.planner.candidates(start, end, provider, model, cancel_token=token)
            if token.is_set():
                raise RenderCancelled(tr("Planung abgebrochen."))
            if title:
                plan.title = title
            save_movie(self.project_path, plan)
            return plan, candidates

        self.status.setText(tr("Filmplan aus dem lokalen Analysebestand erzeugen …"))
        self.run_operation(operation, self.planned)

    def planned(self, result):
        self.plan, self.candidates = result
        self.candidates_loaded = True
        self.candidate_warnings = []
        self.history.record(self.plan)
        self.update_history_controls()
        self.output = None
        self.title.setText(self.plan.title)
        self.refresh()
        self.status.setText(tr("Filmplan gespeichert: {0}", self.project_path))
        self.plan_saved.emit(self.plan)

    def refresh(self):
        if self.plan is None:
            return
        self.stop_preview()
        self.style_combo.setCurrentIndex(self.style_combo.findData(self.plan.editing_style.template))
        self.transition_duration.setValue(self.plan.editing_style.transition_seconds)
        titles = {event.event_id: event.title for event in self.plan.events}
        self.table.setRowCount(0)
        for index, item in enumerate(self.plan.segments):
            self.table.insertRow(index)
            for column, value in enumerate((titles[item.event_id], Path(item.source.path).name,
                                             f"{item.start_seconds:.3f}", f"{item.end_seconds:.3f}", "; ".join(display_message(reason) for reason in item.reasons))):
                cell = QTableWidgetItem(value)
                cell.setToolTip(f"{item.description}\n{value}")
                self.table.setItem(index, column, cell)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(4, 250)
        self.event_combo.blockSignals(True)
        self.event_combo.clear()
        for event in self.plan.events:
            self.event_combo.addItem(event.title, event.event_id)
        self.event_combo.blockSignals(False)
        self.event_selected()
        self.summary.setText(tr("ca. {0} Minuten mit Übergängen · {1} Segmente · {2} Ereignisse · Ziel {3} Minuten", format(self.plan.playback_duration / 60, f'.2f'), len(self.plan.segments), len(self.plan.events), format(self.plan.target_seconds / 60, f'.2f')))
        self.warnings.setText("\n".join(display_message(warning) for warning in self.plan.warnings))

    def apply_style(self):
        if self.plan is None or self.thread is not None:
            self.status.setText(tr("Die gewählte Vorlage wird beim Erzeugen der ersten Auswahl übernommen."))
            return
        self.plan.editing_style = EditingStyle(self.style_combo.currentData(), self.transition_duration.value())
        if self.persist():
            self.refresh()
            self.status.setText(tr("Schnittvorlage gespeichert. Filmvorschau neu erstellen oder MP4 exportieren; keine neue KI-Analyse nötig."))

    def persist(self):
        if self.plan is not None:
            self.plan.title = self.title.text().strip() or self.plan.title
            try:
                save_movie(self.project_path, self.plan)
            except (ValueError, OSError) as exc:
                # An unsuccessful edit must not leave the live plan ahead of disk.
                self.plan = self.history.current or self.plan
                self.title.setText(self.plan.title)
                self.refresh()
                QMessageBox.warning(self, tr("Filmplan nicht gespeichert"), display_message(str(exc)))
                return False
            if self.history.current != self.plan:
                self.output = None
            self.history.record(self.plan)
            self.update_history_controls()
            self.status.setText(tr("Filmplan gespeichert: {0}", self.project_path))
            self.plan_saved.emit(self.plan)
        return True

    def selected(self):
        row = self.table.currentRow()
        if self.plan is not None and 0 <= row < len(self.plan.segments):
            item = self.plan.segments[row]
            self.trim_start.setValue(item.start_seconds)
            self.trim_end.setValue(item.end_seconds)

    def apply_trim(self):
        row = self.table.currentRow()
        if self.plan is None or row < 0:
            return
        item = self.plan.segments[row]
        item.start_seconds, item.end_seconds = self.trim_start.value(), self.trim_end.value()
        self.plan.preferences.trims[item.candidate_id] = (item.start_seconds, item.end_seconds)
        saved = self.persist()
        self.refresh()
        if saved:
            self.status.setText(tr("Schnitt gespeichert. Neuplanen erhält diese Grenzen, wenn der Moment ausgewählt wird. Zum zwingenden Einbeziehen den Moment erzwingen."))

    def remove_segment(self):
        row = self.table.currentRow()
        if self.plan is None or row < 0:
            return
        item = self.plan.segments.pop(row)
        self.plan.preferences.forced.discard(item.candidate_id)
        self.plan.preferences.excluded.add(item.candidate_id)
        self.persist()
        self.refresh()

    def move_segment(self, direction):
        row = self.table.currentRow()
        if self.plan is None or not 0 <= row + direction < len(self.plan.segments) or row < 0:
            return
        items = self.plan.segments
        items[row], items[row + direction] = items[row + direction], items[row]
        warning = tr("Die Segmentreihenfolge wurde manuell geändert. Neuplanen stellt die chronologische Reihenfolge wieder her.")
        if warning not in self.plan.warnings:
            self.plan.warnings.append(warning)
        self.persist()
        self.refresh()
        self.table.selectRow(row + direction)

    def event_selected(self):
        if self.plan:
            self.event_weight.setValue(self.plan.preferences.event_weights.get(self.event_combo.currentData(), 1))

    def review_events(self):
        if self.plan is not None and self.thread is None:
            self.stop_preview()
            EventReviewDialog(self.plan, self).exec()

    def apply_weight(self):
        if self.plan and self.event_combo.currentData():
            self.plan.preferences.event_weights[self.event_combo.currentData()] = self.event_weight.value()
            if self.persist():
                self.status.setText(tr("Ereignisgewicht gespeichert. Mit „Neu planen“ wird die Auswahl angepasst."))

    def edit_candidates(self):
        if self.plan is None or self.thread is not None:
            return
        if self.candidates_loaded:
            self.show_candidates()
            return
        start, end = date.fromisoformat(self.plan.date_from), date.fromisoformat(self.plan.date_to)
        provider, model = self.plan.provider, self.plan.model

        def operation(token, progress):
            result = self.planner.candidates(start, end, provider, model, cancel_token=token)
            if token.is_set():
                raise RenderCancelled(tr("Laden der Momente abgebrochen."))
            return result

        def loaded(result):
            self.candidates, self.candidate_warnings = result
            self.candidates_loaded = True
            self.open_candidates_after_load = True
            count = len(self.candidates)
            self.status.setText(tr("{0} {1} lokal geladen. Der Filmplan bleibt unverändert.", count, tr("Moment") if count == 1 else tr("Momente")))

        self.status.setText(tr("Momente aus dem lokalen Analysebestand laden; der Filmplan bleibt erhalten …"))
        self.run_operation(operation, loaded)

    def show_candidates(self):
        if self.plan is None:
            return
        self.stop_preview()
        dialog = CandidateDialog(self.plan, self.candidates, self.candidate_warnings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.plan.preferences = deepcopy(dialog.model.preferences)
            if not self.persist():
                return
            self.status.setText(tr("Vorgaben gespeichert. Mit „Neu planen“ wird die Auswahl angepasst."))

    def preview(self):
        row = self.table.currentRow()
        if self.plan is None or row < 0:
            return
        self.play_preview(self.plan.segments[row].source.path, self.plan.segments[row])

    def stop_preview(self):
        # Clear intent first: late decoder signals must never restart playback.
        self.preview_pending = False
        self.preview_kind = None
        self.preview_segment = None
        self.player.stop()
        self.preview_slider.setEnabled(False)

    def play_preview(self, path, segment=None):
        self.stop_preview()
        self.preview_segment = segment
        self.preview_kind = "segment" if segment is not None else "movie"
        self.preview_url = QUrl.fromLocalFile(str(path))
        self.preview_pending = True
        if self.player.source() == self.preview_url and self.player.mediaStatus() not in (
                QMediaPlayer.MediaStatus.LoadingMedia, QMediaPlayer.MediaStatus.NoMedia,
                QMediaPlayer.MediaStatus.InvalidMedia):
            self.start_preview()
        else:
            self.player.setSource(self.preview_url)

    def preview_movie(self):
        if self.plan is None or self.thread is not None:
            return
        if not any(item.enabled for item in self.plan.segments):
            self.status.setText(tr("Der Film enthält keine aktiven Segmente für eine Vorschau."))
            return
        if not self.persist():
            return
        if self.movie_preview_plan == self.plan and self.movie_preview_path and self.movie_preview_path.is_file():
            self.play_preview(self.movie_preview_path)
            self.status.setText(tr("Gespeicherte lokale Vorschau dieses Filmplans · 640 × 360 · Originalton"))
            return
        if self.preview_directory is None:
            root = self.library.path.parent / "cache" / "previews"
            try:
                root.mkdir(parents=True, exist_ok=True)
                self.preview_directory = TemporaryDirectory(prefix="session-", dir=root, ignore_cleanup_errors=True)
            except OSError as exc:
                self.status.setText(tr("Die Filmvorschau konnte nicht vorbereitet werden: {0}", exc))
                return
        output = Path(self.preview_directory.name) / f"{uuid4()}.mp4"
        plan = deepcopy(self.plan)
        service = self.render_service()

        def operation(token, progress):
            resolved = relink_movie_sources(plan, self.library, token)
            service.render(resolved, output, token, progress, RenderSettings(640, 360, 30, 28))
            return output, plan

        self.status.setText(tr("Filmvorschau mit Ton wird lokal in 640 × 360 vorbereitet …"))
        self.run_operation(operation, self.movie_preview_ready)

    def movie_preview_ready(self, result):
        self.movie_preview_path, self.movie_preview_plan = result
        self.play_preview(self.movie_preview_path)
        self.status.setText(tr("Lokale Filmvorschau · 640 × 360 · Originalton · keine Medienübertragung"))

    def media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.LoadedMedia and self.preview_pending:
            self.start_preview()

    def preview_error(self, *_):
        if self.preview_kind is None:
            return
        self.stop_preview()
        self.status.setText(tr("Die integrierte Vorschau kann diese Datei nicht wiedergeben."))

    def start_preview(self):
        if not self.preview_pending or self.player.source() != self.preview_url:
            return
        self.player.setPosition(round(self.preview_segment.start_seconds * 1000) if self.preview_segment else 0)
        self.preview_pending = False
        self.preview_duration(self.player.duration())
        self.player.play()

    def preview_duration(self, duration):
        if self.preview_kind == "movie":
            self.preview_slider.setRange(0, max(0, duration))
            self.preview_slider.setEnabled(duration > 0)

    def seek_preview(self, position):
        if self.preview_kind == "movie":
            self.player.setPosition(position)

    def pause_preview(self):
        if self.preview_kind is None or self.preview_pending:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            if self.preview_segment and self.player.position() >= round(self.preview_segment.end_seconds * 1000):
                self.player.setPosition(round(self.preview_segment.start_seconds * 1000))
            self.player.play()

    def preview_position(self, position):
        if self.preview_kind == "movie":
            if not self.preview_slider.isSliderDown():
                self.preview_slider.setValue(position)
            self.preview_clock.setText(tr("Filmvorschau: {0} / {1} s", format(position / 1000, f'.1f'), format(self.player.duration() / 1000, f'.1f')))
        if self.preview_segment and not self.preview_pending and position >= round(self.preview_segment.end_seconds * 1000):
            self.player.pause()

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Filmplan öffnen"), str(self.project_path.parent), tr("Memento-Filmplan (*.memento.json)"))
        if not path:
            return
        try:
            plan = load_movie(Path(path))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, tr("Filmplan nicht geöffnet"), display_message(str(exc)))
            return
        self.plan, self.project_path, self.candidates, self.output = plan, Path(path), [], None
        self.candidates_loaded = False
        self.candidate_warnings = []
        self.history.reset(plan)
        self.update_history_controls()
        self.duration.setValue(plan.target_seconds)
        self.title.setText(plan.title)
        self.refresh()

    def save_project(self):
        if self.plan is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("Filmplan speichern"), str(self.project_path), tr("Memento-Filmplan (*.memento.json)"))
        if path:
            target = Path(path)
            if not target.name.endswith(".memento.json"):
                target = target.with_name(target.name + ".memento.json")
            plan = deepcopy(self.plan)
            plan.title = self.title.text().strip() or plan.title
            try:
                save_movie(target, plan)
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self, tr("Filmplan nicht gespeichert"), display_message(str(exc)))
                return
            self.project_path = target
            self.plan = plan
            self.history.record(plan)
            self.update_history_controls()
            self.status.setText(tr("Filmplan gespeichert: {0}", self.project_path))

    def export(self):
        if self.plan is None:
            return
        if not self.persist():
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("Film lokal exportieren"), str(self.project_path.with_suffix(".mp4")), tr("MP4-Video (*.mp4)"))
        if not path:
            return
        output = Path(path)
        if output.suffix.casefold() != ".mp4":
            output = output.with_suffix(".mp4")
        plan = deepcopy(self.plan)
        service = self.render_service()
        self.status.setText(tr("Film wird lokal gerendert. Ein erneuter Export setzt fertige Abschnitte aus dem Cache fort."))
        def operation(token, progress):
            resolved = relink_movie_sources(plan, self.library, token)
            save_movie(self.project_path, resolved)
            service.render(resolved, output, token, progress)
            return output, resolved

        self.run_operation(operation, self.rendered)

    def rendered(self, result):
        self.output, self.plan = result
        self.history.record(self.plan)
        self.refresh()
        self.status.setText(tr("Film exportiert: {0}", self.output))
        self.movie_exported.emit(str(self.output))

    def render_service(self):
        if self.music_path:
            from memento.application.music import SoundtrackRenderService
            return SoundtrackRenderService(self.library.path.parent / "cache" / "renders", self.music_path)
        return MovieRenderService(self.library.path.parent / "cache" / "renders")

    def watch(self):
        if self.output is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output)))

    def reject(self):
        if self.thread is not None:
            self.token.set()
            self.status.setText(tr("Abbruch angefordert; laufenden Auftrag abwarten …"))
            return
        self.stop_preview()
        if self.plan is not None:
            if not self.persist():
                return
        self.player.setSource(QUrl())
        if self.preview_directory is not None:
            self.preview_directory.cleanup()
            self.preview_directory = None
        self.movie_preview_path = self.movie_preview_plan = None
        super().reject()

    def closeEvent(self, event):
        if self.thread is not None:
            self.token.set()
            event.ignore()
        else:
            self.reject()
            event.ignore() if self.isVisible() else event.accept()
