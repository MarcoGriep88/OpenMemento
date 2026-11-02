from __future__ import annotations

from memento.i18n import tr, display_message, format_date, date_pattern

from datetime import date
import os
from pathlib import Path
from threading import Event

from PySide6.QtCore import QDate, QSettings, Qt, QThread, QTimer, Slot
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCheckBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from memento.application.indexing import MediaIndexService
from memento.application.shot_analysis import ShotAnalysisService
from memento.domain.media import (
    IndexJob,
    IndexJobStatus,
    IndexProgress,
    MediaAnalysisJob,
    MediaAnalysisJobStatus,
    MediaAnalysisProgress,
)
from memento.library.database import MediaLibrary
from memento.ui.index_worker import IndexWorker
from memento.ui.analysis_worker import AnalysisWorker
from memento.ui.settings_dialog import DEFAULT_MODEL, SettingsDialog
from memento.ui.semantic_dialog import SemanticDialog
from memento.ui.movie_dialog import MovieDialog
from memento.ui.recovery_dialog import RecoveryDialog
from memento.ui.capture_time_dialog import CaptureTimeDialog
from memento.ui.date_range_dialog import DateRangeDialog
from memento.ui.folder_availability import FolderAvailabilityChecker


from memento.ui.theme import APP_STYLE, TEXT, WARNING, light_palette



def _card(title: str, value: str, detail: str) -> tuple[QFrame, QLabel]:
    card = QFrame()
    card.setObjectName("card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 14)
    label = QLabel(title)
    label.setObjectName("mutedLabel")
    number = QLabel(value)
    number.setObjectName("statValue")
    note = QLabel(detail)
    note.setObjectName("mutedLabel")
    layout.addWidget(label)
    layout.addWidget(number)
    layout.addWidget(note)
    return card, number


def _format_date_range(first: str | None, last: str | None) -> str:
    if not first or not last:
        return tr("Unbekannt")
    try:
        first_date = format_date(date.fromisoformat(first))
        last_date = format_date(date.fromisoformat(last))
    except ValueError:
        return tr("Unbekannt")
    return first_date if first_date == last_date else f"{first_date} – {last_date}"


def _job_label(job: IndexJob) -> str:
    folder_names = ", ".join(root.name or str(root) for root in job.roots)
    status_labels = {
        IndexJobStatus.PENDING: tr("Wartet"),
        IndexJobStatus.RUNNING: tr("Unterbrochen"),
        IndexJobStatus.CANCELLED: tr("Abgebrochen"),
        IndexJobStatus.COMPLETE_WITH_ERRORS: tr("Mit Fehlern"),
    }
    status = status_labels.get(job.status, job.status.value)
    return f"{status} · {folder_names} · {format_date(job.updated_at, with_time=True)}"


def _analysis_job_label(job: MediaAnalysisJob) -> str:
    status_labels = {
        MediaAnalysisJobStatus.PENDING: tr("Wartet"),
        MediaAnalysisJobStatus.RUNNING: tr("Unterbrochen"),
        MediaAnalysisJobStatus.CANCELLED: tr("Abgebrochen"),
        MediaAnalysisJobStatus.COMPLETE_WITH_ERRORS: tr("Mit Fehlern"),
    }
    status = status_labels.get(job.status, job.status.value)
    return f"{status} · {format_date(job.updated_at, with_time=True)} · {job.analysis_version}"


class MainWindow(QMainWindow):
    def __init__(
        self,
        library: MediaLibrary | None = None,
        index_service: MediaIndexService | None = None,
        parent=None,
        analysis_service: ShotAnalysisService | None = None,
        library_lock=None,
    ):
        super().__init__(parent)
        self.settings = QSettings()
        self._library_lock = library_lock
        self.library = library or MediaLibrary()
        self.index_service = index_service or MediaIndexService(self.library)
        self.analysis_service = analysis_service or ShotAnalysisService(self.library)
        self._thread: QThread | None = None
        self._worker: IndexWorker | None = None
        self._cancel_event: Event | None = None
        self._active_job_id: str | None = None
        self._active_kind: str | None = None
        self._active_roots: set[str] = set()
        self._close_when_stopped = False
        self._folder_availability = {}
        self._folder_checker = FolderAvailabilityChecker(self)
        self._folder_checker.checked.connect(self._on_folder_checked)
        self.setWindowTitle(tr("OpenMemento – Familienfilme"))
        self.resize(1360, 860)
        self.setMinimumSize(1080, 700)
        self.setPalette(light_palette())
        self.setStyleSheet(APP_STYLE)
        self._build_ui()
        self._restore_folders()

    def _build_ui(self):
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)
        root_layout.addWidget(self._build_sidebar())

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(30, 22, 30, 22)
        content_layout.setSpacing(18)
        root_layout.addWidget(content, 1)

        top = QHBoxLayout()
        intro = QVBoxLayout()
        eyebrow = QLabel(tr("DEINE MEDIENBIBLIOTHEK"))
        eyebrow.setObjectName("eyebrow")
        title = QLabel(tr("Guten Tag."))
        title.setObjectName("pageTitle")
        intro.addWidget(eyebrow)
        intro.addWidget(title)
        top.addLayout(intro)
        top.addStretch()
        self.semantic_button = QPushButton(tr("Erinnerungen analysieren"))
        self.semantic_button.clicked.connect(self.open_semantic_analysis)
        top.addWidget(self.semantic_button, alignment=Qt.AlignmentFlag.AlignTop)
        self.settings_button = QPushButton(tr("Einstellungen"))
        self.settings_button.clicked.connect(self.open_settings)
        top.addWidget(self.settings_button, alignment=Qt.AlignmentFlag.AlignTop)
        content_layout.addLayout(top)

        stats = QHBoxLayout()
        stats.setSpacing(12)
        video_card, self.video_stat = _card(tr("VIDEOS INDEXIERT"), "0", tr("Deine Originale bleiben lokal"))
        stats.addWidget(video_card)
        memories_card, _ = _card(tr("ERINNERUNGEN"), "0", tr("Noch keine Analyse vorhanden"))
        stats.addWidget(memories_card)
        library_card, self.library_stat = _card(
            tr("BIBLIOTHEKEN"), "0", tr("Füge deinen ersten Medienordner hinzu")
        )
        stats.addWidget(library_card)
        content_layout.addLayout(stats)

        hero = QFrame()
        hero.setObjectName("heroCard")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(22, 18, 22, 18)
        hero_text = QVBoxLayout()
        hero_title = QLabel(tr("Ein Film aus deinen schönsten Momenten."))
        hero_title.setStyleSheet("font-size: 16pt; font-weight: 650;")
        hero_description = QLabel(
            tr("Wähle einen Zeitraum und Memento hilft dir, daraus eine chronologische Geschichte zu machen.")
        )
        hero_description.setObjectName("mutedLabel")
        hero_description.setWordWrap(True)
        hero_text.addWidget(hero_title)
        hero_text.addWidget(hero_description)
        hero_layout.addLayout(hero_text, 1)
        self.create_movie_button = QPushButton(tr("Film erstellen  →"))
        self.create_movie_button.setObjectName("primaryButton")
        self.create_movie_button.clicked.connect(self.open_movie)
        self.create_movie_button.setToolTip(tr("Gespeicherte Erinnerungen auswählen, Filmplan bearbeiten und lokal exportieren."))
        hero_layout.addWidget(self.create_movie_button)
        content_layout.addWidget(hero)

        library_header = QHBoxLayout()
        library_title = QLabel(tr("Deine Bibliotheken"))
        library_title.setStyleSheet("font-size: 15pt; font-weight: 650;")
        library_header.addWidget(library_title)
        library_header.addStretch()
        self.add_folder_button = QPushButton(tr("Ordner hinzufügen"))
        self.add_folder_button.setObjectName("primaryButton")
        self.add_folder_button.clicked.connect(self.add_folder)
        library_header.addWidget(self.add_folder_button)
        self.check_folders_button = QPushButton(tr("Erreichbarkeit prüfen"))
        self.check_folders_button.clicked.connect(self._refresh_library_state)
        library_header.addWidget(self.check_folders_button)
        self.index_button = QPushButton(tr("Alle Ordner indexieren"))
        self.index_button.setObjectName("primaryButton")
        self.index_button.clicked.connect(self.start_indexing)
        library_header.addWidget(self.index_button)
        self.verify_contents = QCheckBox(tr("Inhalte erneut prüfen"))
        self.verify_contents.setToolTip(tr("Liest auch unveränderte Dateien vollständig. Erkennt Änderungen trotz gleicher Größe und Änderungszeit; vorhandene Analysen gleicher Inhalte bleiben erhalten."))
        library_header.addWidget(self.verify_contents)
        content_layout.addLayout(library_header)

        analysis_row = QHBoxLayout()
        analysis_title = QLabel(tr("Shots und lokale Bildmerkmale"))
        analysis_title.setObjectName("mutedLabel")
        analysis_row.addWidget(analysis_title)
        self.analyze_button = QPushButton(tr("Alle Videos lokal analysieren"))
        self.analyze_button.setToolTip(tr("Schnittgrenzen, Belichtung, Schärfe, Kamerabewegung und Bildsignaturen werden ohne Übertragung lokal gespeichert."))
        self.analyze_button.clicked.connect(self.start_analysis)
        analysis_row.addWidget(self.analyze_button)
        self.analysis_job_selector = QComboBox()
        self.analysis_job_selector.setMinimumWidth(300)
        self.analysis_job_selector.currentIndexChanged.connect(self._refresh_analysis_error_button)
        analysis_row.addWidget(self.analysis_job_selector, 1)
        self.resume_analysis_button = QPushButton(tr("Fortsetzen"))
        self.resume_analysis_button.clicked.connect(self.resume_selected_analysis)
        analysis_row.addWidget(self.resume_analysis_button)
        self.analysis_errors_button = QPushButton(tr("Fehler anzeigen"))
        self.analysis_errors_button.clicked.connect(self.show_selected_analysis_errors)
        analysis_row.addWidget(self.analysis_errors_button)
        content_layout.addLayout(analysis_row)

        job_row = QHBoxLayout()
        job_title = QLabel(tr("Offene Importaufträge"))
        job_title.setObjectName("mutedLabel")
        job_row.addWidget(job_title)
        self.job_selector = QComboBox()
        self.job_selector.setMinimumWidth(320)
        self.job_selector.currentIndexChanged.connect(self._refresh_error_button)
        job_row.addWidget(self.job_selector, 1)
        self.resume_button = QPushButton(tr("Fortsetzen"))
        self.resume_button.clicked.connect(self.resume_selected_job)
        job_row.addWidget(self.resume_button)
        self.errors_button = QPushButton(tr("Fehler anzeigen"))
        self.errors_button.clicked.connect(self.show_selected_job_errors)
        job_row.addWidget(self.errors_button)
        content_layout.addLayout(job_row)

        progress_row = QHBoxLayout()
        self.index_status_label = QLabel(tr("Keine Indexierung aktiv"))
        self.index_status_label.setObjectName("mutedLabel")
        self.index_status_label.setMinimumWidth(250)
        progress_row.addWidget(self.index_status_label)
        self.index_progress = QProgressBar()
        self.index_progress.setRange(0, 100)
        self.index_progress.setValue(0)
        self.index_progress.setVisible(False)
        progress_row.addWidget(self.index_progress, 1)
        self.cancel_button = QPushButton(tr("Abbrechen"))
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_indexing)
        progress_row.addWidget(self.cancel_button)
        content_layout.addLayout(progress_row)

        date_row = QHBoxLayout()
        date_note = QLabel(tr("Zeitraum"))
        date_note.setObjectName("mutedLabel")
        date_row.addWidget(date_note)
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat(date_pattern(qt=True))
        self.date_from.setDate(QDate.currentDate())
        date_row.addWidget(self.date_from)
        date_row.addWidget(QLabel(tr("bis")))
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat(date_pattern(qt=True))
        self.date_to.setDate(QDate.currentDate())
        date_row.addWidget(self.date_to)
        self.find_range_button = QPushButton(tr("Aufnahmen prüfen …"))
        self.find_range_button.setToolTip(tr("Öffnet nur die Liste der Videos im gewählten Zeitraum."))
        self.find_range_button.clicked.connect(self.find_in_date_range)
        date_row.addWidget(self.find_range_button)
        date_row.addSpacing(18)
        duration_label = QLabel(tr("Filmlänge"))
        duration_label.setObjectName("mutedLabel")
        date_row.addWidget(duration_label)
        self.target_duration = QSpinBox()
        self.target_duration.setRange(1, 180)
        self.target_duration.setValue(12)
        self.target_duration.setSuffix(tr(" Min."))
        date_row.addWidget(self.target_duration)
        self.analyze_period_button = QPushButton(tr("1  Erinnerungen analysieren"))
        self.analyze_period_button.setToolTip(
            tr("Nächster Schritt nach der lokalen Shotanalyse: Gemini bewertet die Momente im gewählten Zeitraum.")
        )
        self.analyze_period_button.clicked.connect(self.open_semantic_analysis)
        date_row.addWidget(self.analyze_period_button)
        self.range_movie_button = QPushButton(tr("2  Film erstellen"))
        self.range_movie_button.setObjectName("primaryButton")
        self.range_movie_button.setToolTip(
            tr("Filmplan aus den gespeicherten Analyseergebnissen erzeugen, prüfen und lokal exportieren.")
        )
        self.range_movie_button.clicked.connect(self.open_movie)
        date_row.addWidget(self.range_movie_button)
        date_row.addStretch()
        self.library_count = QLabel(tr("0 Ordner"))
        self.library_count.setObjectName("mutedLabel")
        date_row.addWidget(self.library_count)
        content_layout.addLayout(date_row)
        self.range_summary = QLabel(tr("Zeitraum wählen. „Aufnahmen prüfen“ zeigt nur die Treffer; die nummerierten Schaltflächen daneben führen zum Film."))
        self.range_summary.setObjectName("mutedLabel")
        content_layout.addWidget(self.range_summary)

        self.library_table = QTableWidget(0, 4)
        self.library_table.setHorizontalHeaderLabels(
            [tr("MEDIENORDNER"), tr("STATUS"), tr("VIDEOS"), tr("AUFNAHMEZEITRAUM")]
        )
        self.library_table.setAlternatingRowColors(True)
        self.library_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.library_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.library_table.verticalHeader().setVisible(False)
        header = self.library_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(False)
        self.library_table.setMinimumHeight(170)
        content_layout.addWidget(self.library_table, 1)

        self.empty_hint = QLabel(
            tr("Deine Bibliothek ist noch leer. Füge einen Ordner mit Familienvideos hinzu, um loszulegen.")
        )
        self.empty_hint.setObjectName("mutedLabel")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self.empty_hint)
        self.statusBar().showMessage(
            tr("Lokal auf diesem Gerät · Noch keine Medien werden verarbeitet")
        )
        self._add_settings_action()
        # Named sections let the guided v2 shell reuse the proven worker controls.
        self.workflow_sections = {
            "material": (library_header, job_row, self.library_table, self.empty_hint),
            "analysis": (analysis_row,),
            "progress": (progress_row,),
        }
        self.library_content_layout = content_layout

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(224)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 22, 16, 18)
        layout.setSpacing(8)
        brand = QLabel("OpenMemento")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        tagline = QLabel(tr("Deine Familiengeschichten"))
        tagline.setObjectName("mutedLabel")
        layout.addWidget(tagline)
        layout.addSpacing(28)
        for label, active in ((tr("Bibliothek"), True), (tr("Filme"), False)):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setChecked(active)
            button.setEnabled(True)
            if not active:
                button.clicked.connect(self.open_movie)
            layout.addWidget(button)
        self.capture_times_button = QPushButton(tr("Aufnahmezeiten prüfen"))
        self.capture_times_button.clicked.connect(self.open_capture_times)
        layout.addWidget(self.capture_times_button)
        layout.addStretch()
        self.recovery_button = QPushButton(tr("Sicherung und\nWiederherstellung"))
        self.recovery_button.clicked.connect(self.open_recovery)
        layout.addWidget(self.recovery_button)
        privacy = QLabel(tr(
            "DEINE PRIVATSPHÄRE\n\n"
            "Quelldateien werden lokal verwaltet und nie verändert.\n"
            "Eine Gemini-Analyse überträgt ausgewählte Medien direkt an Google."
        ))
        privacy.setObjectName("mutedLabel")
        privacy.setWordWrap(True)
        layout.addWidget(privacy)
        return sidebar

    def _add_settings_action(self):
        action = QAction(tr("Einstellungen"), self)
        action.setShortcut("Ctrl+,")
        action.triggered.connect(self.open_settings)
        self.addAction(action)

    def _restore_folders(self):
        folders = self.settings.value("library/folders", [], type=list)
        unique: list[str] = []
        seen: set[str] = set()
        for folder in folders:
            path = os.path.abspath(folder)
            if os.path.normcase(path) not in seen:
                unique.append(path)
                seen.add(os.path.normcase(path))
        if unique != folders:
            self.settings.setValue("library/folders", unique)
        self._refresh_library_state()
        self._refresh_job_choices()
        self._refresh_analysis_choices()

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Medienordner hinzufügen"))
        if not folder:
            return
        folder = os.path.abspath(folder)
        existing = self.settings.value("library/folders", [], type=list)
        normalized = {os.path.normcase(os.path.abspath(value)) for value in existing}
        if os.path.normcase(folder) not in normalized:
            existing.append(folder)
            self.settings.setValue("library/folders", existing)
            self._refresh_library_state()
            self.statusBar().showMessage(
                tr("Ordner vorgemerkt. Mit 'Alle Ordner indexieren' startest du den lokalen Import."),
                7000,
            )

    def _append_folder(self, folder: str):
        root = Path(folder)
        stats = self.library.get_folder_stats(root)
        is_active = os.path.normcase(os.path.abspath(root)) in self._active_roots
        status = tr("Indexierung läuft") if is_active else (
            tr("Indexiert") if stats.video_count else tr("Noch nicht indexiert")
        )
        row = self.library_table.rowCount()
        self.library_table.insertRow(row)
        name = QTableWidgetItem(root.name or folder)
        name.setToolTip(folder)
        name.setData(Qt.ItemDataRole.UserRole, folder)
        self.library_table.setItem(row, 0, name)
        self.library_table.setItem(row, 1, QTableWidgetItem(status))
        self._set_folder_status(row, folder)
        self.library_table.setItem(row, 2, QTableWidgetItem(str(stats.video_count)))
        self.library_table.setItem(
            row,
            3,
            QTableWidgetItem(_format_date_range(stats.first_capture_date, stats.last_capture_date)),
        )

    def _set_folder_status(self, row, folder):
        item = self.library_table.item(row, 1)
        # Keep the cached indexing status independent of current connectivity.
        if item.data(Qt.ItemDataRole.UserRole) is None:
            item.setData(Qt.ItemDataRole.UserRole, item.text())
        result = self._folder_availability.get(folder)
        if result is None:
            item.setText(tr("Zugriff wird geprüft …"))
        elif not result[0]:
            item.setText(tr("Derzeit nicht zugreifbar"))
        else:
            item.setText(item.data(Qt.ItemDataRole.UserRole))
        item.setToolTip(display_message(result[1]) if result else tr("Die Prüfung läuft im Hintergrund."))
        item.setForeground(QColor(WARNING if result and not result[0] else TEXT))

    @Slot(str, bool, str)
    def _on_folder_checked(self, folder, available, detail):
        self._folder_availability[folder] = (available, detail)
        for row in range(self.library_table.rowCount()):
            if self.library_table.item(row, 0).data(Qt.ItemDataRole.UserRole) == folder:
                self._set_folder_status(row, folder)

    def _refresh_library_state(self):
        folders = self.settings.value("library/folders", [], type=list)
        self.library_table.setRowCount(0)
        for folder in folders:
            self._append_folder(str(folder))
        self.library_count.setText(tr("{0} Ordner", len(folders)))
        self.library_stat.setText(str(len(folders)))
        self.empty_hint.setVisible(not folders)
        self.video_stat.setText(str(self.library.count_assets()))
        self.index_button.setEnabled(bool(folders) and self._thread is None)
        self.analyze_button.setEnabled(self.library.count_assets() > 0 and self._thread is None)
        # Let the window paint before starting any filesystem access.
        self._folder_checker.stop()
        QTimer.singleShot(0, self._check_folders)

    def _check_folders(self):
        if self.isVisible() or not self._close_when_stopped:
            self._folder_checker.check(self.settings.value("library/folders", [], type=list))

    def find_in_date_range(self):
        start = self.date_from.date().toPython()
        end = self.date_to.date().toPython()
        if end < start:
            QMessageBox.warning(self, tr("Ungültiger Zeitraum"), tr("Das Enddatum muss am oder nach dem Startdatum liegen."))
            return
        page = self.library.capture_date_page(start, end, limit=DateRangeDialog.PAGE_SIZE)
        unknown = page.unknown
        self.range_summary.setText(
            tr("{0} Aufnahmen im Zeitraum · {1} Videos ohne bekanntes Aufnahmedatum. Die Liste ist nur zur Prüfung; nutze die beiden nummerierten Schaltflächen daneben, um den Film zu erstellen.", page.total, unknown)
        )
        if not page.total:
            QMessageBox.information(
                self,
                tr("Keine Aufnahmen gefunden"),
                tr("Für {0} bis {1} wurden keine Aufnahmen mit bekanntem Datum gefunden.\n\n{2} Videos haben kein bekanntes Aufnahmedatum und können deshalb nicht sicher diesem Zeitraum zugeordnet werden.", format_date(start), format_date(end), unknown),
            )
            return
        self._show_range_results(page, start, end)

    def _show_range_results(self, page, start: date, end: date):
        DateRangeDialog(self.library, start, end, self, initial_page=page).exec()

    def _refresh_job_choices(self, selected_job_id: str | None = None):
        jobs = self.library.list_resumable_index_jobs()
        wanted = selected_job_id or self.job_selector.currentData()
        self.job_selector.blockSignals(True)
        self.job_selector.clear()
        for job in jobs:
            self.job_selector.addItem(_job_label(job), job.job_id)
        if wanted:
            index = self.job_selector.findData(wanted)
            if index >= 0:
                self.job_selector.setCurrentIndex(index)
        self.job_selector.blockSignals(False)
        idle = self._thread is None
        self.job_selector.setEnabled(bool(jobs) and idle)
        self.resume_button.setEnabled(bool(jobs) and idle)
        self._refresh_error_button()

    def _refresh_analysis_choices(self, selected_job_id: str | None = None):
        jobs = self.library.list_resumable_media_analysis_jobs()
        wanted = selected_job_id or self.analysis_job_selector.currentData()
        self.analysis_job_selector.blockSignals(True)
        self.analysis_job_selector.clear()
        for job in jobs:
            self.analysis_job_selector.addItem(_analysis_job_label(job), job.job_id)
        if wanted:
            index = self.analysis_job_selector.findData(wanted)
            if index >= 0:
                self.analysis_job_selector.setCurrentIndex(index)
        self.analysis_job_selector.blockSignals(False)
        idle = self._thread is None
        self.analysis_job_selector.setEnabled(bool(jobs) and idle)
        self.resume_analysis_button.setEnabled(bool(jobs) and idle)
        self._refresh_analysis_error_button()

    def _refresh_error_button(self, *_):
        job_id = self.job_selector.currentData()
        has_errors = bool(job_id and self.library.list_index_job_errors(job_id))
        self.errors_button.setEnabled(has_errors and self._thread is None)

    def _refresh_analysis_error_button(self, *_):
        job_id = self.analysis_job_selector.currentData()
        has_errors = bool(job_id and self.library.list_media_analysis_job_errors(job_id))
        self.analysis_errors_button.setEnabled(has_errors and self._thread is None)

    def start_indexing(self):
        roots = [
            Path(value)
            for value in self.settings.value("library/folders", [], type=list)
        ]
        if not roots:
            self.statusBar().showMessage(tr("Füge zuerst mindestens einen Medienordner hinzu."), 5000)
            return
        job = self.index_service.create_job(roots, verify_contents=self.verify_contents.isChecked())
        self._run_index_job(job.job_id)

    def start_analysis(self):
        if self._thread is not None:
            return
        if self.library.count_assets() == 0:
            self.statusBar().showMessage(tr("Indexiere zuerst mindestens einen Medienordner."), 5000)
            return
        incomplete = self.library.list_resumable_media_analysis_jobs()
        if incomplete:
            self.analysis_job_selector.setCurrentIndex(
                self.analysis_job_selector.findData(incomplete[0].job_id)
            )
            self.statusBar().showMessage(
                tr("Ein offener Analyseauftrag ist vorhanden. Wähle ihn aus und setze ihn fort."), 7000
            )
            return
        job = self.analysis_service.create_job()
        self._run_analysis_job(job.job_id)

    def resume_selected_job(self):
        job_id = self.job_selector.currentData()
        if job_id:
            self._run_index_job(job_id)

    def resume_selected_analysis(self):
        job_id = self.analysis_job_selector.currentData()
        if job_id:
            self._run_analysis_job(job_id)

    def _run_index_job(self, job_id: str):
        if self._thread is not None:
            return
        job = self.library.get_index_job(job_id)
        if job is None:
            self.statusBar().showMessage(tr("Der Importauftrag wurde nicht gefunden."), 5000)
            self._refresh_job_choices()
            return
        self._active_job_id = job_id
        self._active_kind = "index"
        self._active_roots = {os.path.normcase(os.path.abspath(root)) for root in job.roots}
        self._cancel_event = Event()
        thread = QThread(self)
        worker = IndexWorker(self.index_service, job_id, self._cancel_event)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_index_progress, Qt.ConnectionType.QueuedConnection)
        worker.completed.connect(self._on_index_completed, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._on_index_failed, Qt.ConnectionType.QueuedConnection)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_thread_stopped, Qt.ConnectionType.QueuedConnection)
        self._thread = thread
        self._worker = worker
        self.index_progress.setRange(0, 0)
        self.index_progress.setVisible(True)
        self.index_status_label.setText(tr("Import wird vorbereitet …"))
        self.cancel_button.setEnabled(True)
        self.add_folder_button.setEnabled(False)
        self.index_button.setEnabled(False)
        self._refresh_job_choices(job_id)
        self._refresh_analysis_choices()
        self._refresh_library_state()
        thread.start()

    def _run_analysis_job(self, job_id: str):
        if self._thread is not None:
            return
        job = self.library.get_media_analysis_job(job_id)
        if job is None:
            self.statusBar().showMessage(tr("Der Analyseauftrag wurde nicht gefunden."), 5000)
            self._refresh_analysis_choices()
            return
        self._active_job_id = job_id
        self._active_kind = "analysis"
        self._cancel_event = Event()
        thread = QThread(self)
        worker = AnalysisWorker(self.analysis_service, job_id, self._cancel_event)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_analysis_progress, Qt.ConnectionType.QueuedConnection)
        worker.completed.connect(self._on_analysis_completed, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._on_analysis_failed, Qt.ConnectionType.QueuedConnection)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_thread_stopped, Qt.ConnectionType.QueuedConnection)
        self._thread = thread
        self._worker = worker
        self.index_progress.setRange(0, 0)
        self.index_progress.setVisible(True)
        self.index_status_label.setText(tr("Lokale Shotanalyse wird vorbereitet …"))
        self.cancel_button.setEnabled(True)
        self.add_folder_button.setEnabled(False)
        self.index_button.setEnabled(False)
        self.analyze_button.setEnabled(False)
        self._refresh_job_choices()
        self._refresh_analysis_choices(job_id)
        thread.start()

    @Slot(object)
    def _on_index_progress(self, progress: IndexProgress):
        if progress.phase == "discovering":
            self.index_status_label.setText(
                tr("Ordner werden durchsucht: {0}", progress.current_path or '')
            )
            self.index_progress.setRange(0, 0)
            return
        total = progress.total or 0
        self.index_progress.setRange(0, max(total, 1))
        self.index_progress.setValue(progress.completed)
        current = progress.current_path.name if progress.current_path else ""
        if progress.phase == "hashing":
            volume = (f" · {progress.current_bytes / 1048576:.1f}/{progress.current_total_bytes / 1048576:.1f} MiB"
                      if progress.current_bytes is not None and progress.current_total_bytes is not None else "")
            self.index_status_label.setText(tr("Inhaltsprüfung {0}/{1} · {2}{3}", progress.completed, total, current, volume))
            return
        self.index_status_label.setText(
            tr("{0}/{1} Videos · {2} Fehler · {3}", progress.completed, total, progress.failed, current)
        )

    @Slot(str, str)
    def _on_index_completed(self, job_id: str, status: str):
        messages = {
            IndexJobStatus.COMPLETE.value: tr("Indexierung abgeschlossen."),
            IndexJobStatus.COMPLETE_WITH_ERRORS.value:
                tr("Indexierung abgeschlossen; einige Dateien brauchen Aufmerksamkeit."),
            IndexJobStatus.CANCELLED.value: tr("Indexierung abgebrochen. Du kannst sie fortsetzen."),
        }
        message = messages.get(status, tr("Indexierung beendet."))
        self.index_status_label.setText(message)
        self.statusBar().showMessage(message, 7000)

    @Slot(str, str)
    def _on_index_failed(self, job_id: str, message: str):
        self.index_status_label.setText(tr("Der Import wurde unterbrochen und kann fortgesetzt werden."))
        self.statusBar().showMessage(tr("Importfehler: {0}", message), 10000)

    @Slot(object)
    def _on_analysis_progress(self, progress: MediaAnalysisProgress):
        self.index_progress.setRange(0, max(progress.total, 1))
        self.index_progress.setValue(progress.completed)
        current = progress.current_path.name if progress.current_path else ""
        self.index_status_label.setText(
            tr("Shotanalyse {0}/{1} · {2} Fehler · {3} bereits aktuell · {4}", progress.completed, progress.total, progress.failed, progress.skipped, current)
        )

    @Slot(str, str)
    def _on_analysis_completed(self, job_id: str, status: str):
        messages = {
            MediaAnalysisJobStatus.COMPLETE.value: tr("Lokale Shotanalyse abgeschlossen."),
            MediaAnalysisJobStatus.COMPLETE_WITH_ERRORS.value:
                tr("Shotanalyse abgeschlossen; einige Videos brauchen Aufmerksamkeit."),
            MediaAnalysisJobStatus.CANCELLED.value: tr("Shotanalyse abgebrochen. Du kannst sie fortsetzen."),
        }
        message = messages.get(status, tr("Shotanalyse beendet."))
        self.index_status_label.setText(message)
        self.statusBar().showMessage(message, 7000)

    @Slot(str, str)
    def _on_analysis_failed(self, job_id: str, message: str):
        self.index_status_label.setText(tr("Die Shotanalyse wurde unterbrochen und kann fortgesetzt werden."))
        self.statusBar().showMessage(tr("Analysefehler: {0}", message), 10000)

    def show_selected_analysis_errors(self):
        job_id = self.analysis_job_selector.currentData()
        if not job_id:
            return
        errors = self.library.list_media_analysis_job_errors(job_id)
        if not errors:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Fehler der Shotanalyse"))
        dialog.resize(850, 480)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(len(errors), 2)
        table.setHorizontalHeaderLabels([tr("DATEI"), tr("FEHLER")])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for row, error in enumerate(errors):
            table.setItem(row, 0, QTableWidgetItem(error["path"]))
            table.setItem(row, 1, QTableWidgetItem(display_message(error["message"])))
        layout.addWidget(table)
        close_button = QPushButton(tr("Schließen"))
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)
        dialog.exec()

    @Slot()
    def _on_thread_stopped(self):
        job_id = self._active_job_id
        kind = self._active_kind
        thread = self._thread
        # finished is emitted before the worker thread completes deferred QObject
        # deletion. Join before releasing its Python wrapper to avoid concurrent
        # Shiboken/Qt destruction on Linux.
        if thread is not None:
            thread.wait()
        self._thread = None
        self._worker = None
        self._cancel_event = None
        self._active_job_id = None
        self._active_kind = None
        self._active_roots.clear()
        self.index_progress.setVisible(False)
        self.cancel_button.setEnabled(False)
        self.add_folder_button.setEnabled(True)
        self._refresh_library_state()
        if kind == "analysis":
            self._refresh_job_choices()
            self._refresh_analysis_choices(job_id)
        else:
            self._refresh_job_choices(job_id)
            self._refresh_analysis_choices()
        if self._close_when_stopped:
            QTimer.singleShot(0, self.close)
        if thread is not None:
            thread.deleteLater()

    def cancel_indexing(self):
        if self._cancel_event is not None:
            self._cancel_event.set()
            self.cancel_button.setEnabled(False)
            self.index_status_label.setText(tr("Abbruch wird ausgeführt …"))

    def show_selected_job_errors(self):
        job_id = self.job_selector.currentData()
        if not job_id:
            return
        errors = self.library.list_index_job_errors(job_id)
        if not errors:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Importfehler"))
        dialog.resize(850, 480)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(len(errors), 3)
        table.setHorizontalHeaderLabels([tr("DATEI / ORDNER"), tr("STUFE"), tr("FEHLER")])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for row, error in enumerate(errors):
            for column, value in enumerate((error["path"], error["stage"], error["message"])):
                table.setItem(row, column, QTableWidgetItem(display_message(str(value)) if column == 2 else str(value)))
        layout.addWidget(table)
        close_button = QPushButton(tr("Schließen"))
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)
        dialog.exec()

    def closeEvent(self, event):
        if self._thread is not None and self._thread.isRunning():
            self._close_when_stopped = True
            if self._cancel_event is not None:
                self._cancel_event.set()
            self.statusBar().showMessage(tr("Laufender Auftrag wird sicher beendet …"))
            event.ignore()
            return
        self._close_when_stopped = True
        self._folder_checker.stop()
        event.accept()

    def open_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec()

    def open_recovery(self):
        if self._thread is not None:
            QMessageBox.information(self, tr("Auftrag läuft"), tr("Bitte den laufenden Auftrag zuerst beenden."))
            return
        dialog = RecoveryDialog(self.library.path, self, self._library_lock)
        dialog.exec()
        if self.library.path.with_suffix(".restore.json").exists():
            QMessageBox.critical(self, tr("Neustart erforderlich"), tr("Der vorbereitete Austausch muss beim nächsten Start sicher abgeschlossen werden. Memento wird jetzt geschlossen; Sicherheitskopien bleiben erhalten."))
            self.close()
            return
        if dialog.restored:
            folders = self.settings.value("library/folders", [], type=list)
            self.settings.setValue("library/folders", list(dict.fromkeys(folders + list(dialog.recovery_result.roots))))
            self._restore_folders()

    def open_capture_times(self):
        if self._thread is not None:
            QMessageBox.information(self, tr("Auftrag läuft"), tr("Bitte den laufenden lokalen Auftrag zuerst beenden."))
            return
        dialog = CaptureTimeDialog(self.library, self)
        dialog.exec()
        if dialog.changed:
            self._refresh_library_state()
            self.range_summary.setText(tr("Aufnahmezeiten aktualisiert. Zeitraum erneut prüfen oder Film neu planen."))

    def open_movie(self):
        if self._thread is not None:
            QMessageBox.information(self, tr("Auftrag läuft"), tr("Bitte den laufenden lokalen Auftrag zuerst beenden."))
            return
        start, end = self.date_from.date().toPython(), self.date_to.date().toPython()
        if end < start:
            QMessageBox.warning(self, tr("Ungültiger Zeitraum"), tr("Das Enddatum muss am oder nach dem Startdatum liegen."))
            return
        dialog = MovieDialog(self.library, start, end, self.target_duration.value() * 60,
                             self.settings.value("ai/model", DEFAULT_MODEL, type=str), self)
        dialog.exec()

    def open_semantic_analysis(self):
        if self._thread is not None:
            QMessageBox.information(self, tr("Auftrag läuft"), tr("Bitte den laufenden lokalen Auftrag zuerst beenden."))
            return
        start, end = self.date_from.date().toPython(), self.date_to.date().toPython()
        if end < start:
            QMessageBox.warning(self, tr("Ungültiger Zeitraum"), tr("Das Enddatum muss am oder nach dem Startdatum liegen."))
            return
        assets = self.library.list_assets_in_capture_date_range(start, end)
        try:
            dialog = SemanticDialog(self.library, assets, self.settings.value("ai/model", DEFAULT_MODEL, type=str), self)
        except ValueError as exc:
            QMessageBox.information(self, tr("Keine analysierbare Auswahl"), display_message(str(exc)))
            return
        dialog.exec()
