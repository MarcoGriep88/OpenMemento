"""Project-first shell around the existing indexing, analysis and movie editor."""
from __future__ import annotations

from memento.i18n import tr, display_message, language

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox,
    QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from memento.application.movie_planning import MoviePlanningService
from memento.application.music import music_prompt
from memento.domain.editing import EDITING_TEMPLATES, EditingStyle
from memento.domain.media import AnalysisStatus
from memento.domain.movie_history import MovieHistory
from memento.library.movies import load_movie
from memento.library.projects import FilmProject, ProjectStore, project_asset_ids
from memento.library.semantic import SemanticRepository
from memento.media.local_features import LOCAL_ANALYSIS_VERSION
from memento.ui.main_window import MainWindow
from memento.ui.movie_dialog import MovieDialog
from memento.ui.semantic_dialog import SemanticDialog
from memento.ui.settings_dialog import DEFAULT_MODEL


STEPS = ("Dashboard", "Film anlegen", "Material & Indexierung", "OpenCV & Gemini", "Schnitt & Musik", "Film & Export")


class WorkflowWindow(MainWindow):
    def __init__(self, *args, **kwargs):
        self.project = None
        self.movie_editor = None
        self._loading = False
        super().__init__(*args, **kwargs)
        self.store = ProjectStore(self.library.path.parent / "projects")
        self.settings.setValue("library/folders", [])
        self._refresh_library_state()
        self.setWindowTitle(tr("OpenMemento – Deine Filmprojekte"))
        self.resize(1480, 960)
        self.refresh_dashboard()
        self.show_step(0)

    def _build_ui(self):
        super()._build_ui()
        self._legacy = self.takeCentralWidget()
        self._legacy.setParent(self)
        self._legacy.hide()
        root = QWidget()
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.setCentralWidget(root)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(250)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(16, 24, 16, 18)
        brand = QLabel("OpenMemento")
        brand.setObjectName("brand")
        nav.addWidget(brand)
        self.project_label = QLabel(tr("Dein nächster Familienfilm"))
        self.project_label.setWordWrap(True)
        self.project_label.setTextFormat(Qt.TextFormat.PlainText)
        nav.addWidget(self.project_label)
        nav.addSpacing(24)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons = []
        for index, title in enumerate(STEPS):
            button = QPushButton(f"{index + 1}   {tr(title).replace(chr(38), chr(38) * 2)}")
            button.setObjectName("navButton")
            button.setCheckable(True)
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            nav.addWidget(button)
        self.nav_group.idClicked.connect(self.show_step)
        nav.addStretch()
        for title, callback in ((tr("Gemini-Einstellungen"), self.open_settings),
                                (tr("Aufnahmezeiten prüfen"), self.open_capture_times),
                                (tr("Sicherung / Wiederherstellung"), self.open_recovery)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            nav.addWidget(button)
        privacy = QLabel(tr("Originale bleiben unverändert.\nOpenCV und Export laufen lokal.\nGemini erhält nur die ausdrücklich\nfreigegebenen Analysevideos."))
        privacy.setObjectName("mutedLabel")
        privacy.setWordWrap(True)
        nav.addWidget(privacy)
        row.addWidget(sidebar)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(26, 20, 26, 16)
        self.page_title = QLabel()
        self.page_title.setObjectName("pageTitle")
        body_layout.addWidget(self.page_title)
        self.pages = QStackedWidget()
        body_layout.addWidget(self.pages, 1)
        self.page_layouts = []
        for _ in STEPS:
            page = QWidget()
            page.setObjectName("workflowPage")
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 8, 0, 8)
            layout.setSpacing(14)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(page)
            self.pages.addWidget(scroll)
            self.page_layouts.append(layout)
        row.addWidget(body, 1)
        self._build_dashboard()
        self._build_project_page()
        self._move_sections("material", self.page_layouts[2])
        self.index_button.setText(tr("Projektmaterial indexieren"))
        dates = QHBoxLayout()
        self.filter_dates = QCheckBox(tr("Zeitraum einschränken"))
        dates.addWidget(self.filter_dates)
        dates.addWidget(self.date_from)
        dates.addWidget(QLabel(tr("bis")))
        dates.addWidget(self.date_to)
        dates.addWidget(self.find_range_button)
        self.page_layouts[2].insertLayout(0, dates)
        self.material_hint = self._note(self.page_layouts[2], tr("Füge einen oder mehrere Medienordner hinzu. Die Indexierung verändert keine Quelldateien."))
        self._move_sections("analysis", self.page_layouts[3])
        self.analyze_button.setText(tr("1 · OpenCV lokal starten"))
        self.analysis_hint = self._note(self.page_layouts[3], tr("Erst lokale Bildanalyse, danach semantische Videoanalyse mit Gemini. Erfolgreiche Ergebnisse bleiben gespeichert."))
        self.gemini_button = QPushButton(tr("2 · Gemini-Analyse vorbereiten …"))
        self.gemini_button.setObjectName("primaryButton")
        self.gemini_button.clicked.connect(self.open_semantic_analysis)
        self.page_layouts[3].addWidget(self.gemini_button)
        self.page_layouts[3].addStretch()
        self._build_music_page()
        self.export_hint = self._note(self.page_layouts[5], tr("Hier wird aus dem gespeicherten Analysebestand ein editierbarer Filmplan erzeugt. Danach Vorschau prüfen und lokal als MP4 exportieren."))
        self.open_editor_button = QPushButton(tr("Filmplan erzeugen / bearbeiten"))
        self.open_editor_button.setObjectName("primaryButton")
        self.open_editor_button.clicked.connect(self.open_movie)
        self.page_layouts[5].addWidget(self.open_editor_button)
        self._move_sections("progress", body_layout)
        self.cancel_button.setMaximumWidth(140)
        footer = QHBoxLayout()
        self.back_button = QPushButton(tr("← Zurück"))
        self.next_button = QPushButton(tr("Weiter →"))
        self.next_button.setObjectName("primaryButton")
        self.back_button.clicked.connect(lambda: self.show_step(self.pages.currentIndex() - 1))
        self.next_button.clicked.connect(self.next_step)
        footer.addWidget(self.back_button)
        footer.addStretch()
        self.step_hint = QLabel()
        footer.addWidget(self.step_hint)
        footer.addWidget(self.next_button)
        body_layout.addLayout(footer)
        for control in (self.date_from, self.date_to):
            control.dateChanged.connect(self.save_project)
        self.filter_dates.toggled.connect(self.save_project)
        self.filter_dates.toggled.connect(self.date_from.setEnabled)
        self.filter_dates.toggled.connect(self.date_to.setEnabled)
        self.date_from.setEnabled(False)
        self.date_to.setEnabled(False)

    def _move_sections(self, name, destination):
        for section in self.workflow_sections[name]:
            for index in range(self.library_content_layout.count()):
                item = self.library_content_layout.itemAt(index)
                if item.widget() is section or item.layout() is section:
                    self.library_content_layout.takeAt(index)
                    break
            if isinstance(section, QWidget):
                destination.addWidget(section)
                section.show()
            else:
                destination.addLayout(section)

    @staticmethod
    def _note(layout, text):
        note = QLabel(text)
        note.setTextFormat(Qt.TextFormat.PlainText)
        note.setWordWrap(True)
        note.setObjectName("mutedLabel")
        layout.addWidget(note)
        return note

    def _build_dashboard(self):
        layout = self.page_layouts[0]
        self._note(layout, tr("Deine Filmprojekte – vom leeren Entwurf bis zum exportierten Familienfilm."))
        actions = QHBoxLayout()
        new = QPushButton(tr("+ Neuen Film anlegen"))
        new.setObjectName("primaryButton")
        new.clicked.connect(self.new_project)
        actions.addWidget(new)
        resume = QPushButton(tr("Gewähltes Projekt fortsetzen"))
        resume.clicked.connect(self.open_selected_project)
        actions.addWidget(resume)
        watch = QPushButton(tr("Exportierten Film ansehen"))
        watch.clicked.connect(self.watch_selected_project)
        actions.addWidget(watch)
        layout.addLayout(actions)
        self.projects_table = QTableWidget(0, 4)
        self.projects_table.setHorizontalHeaderLabels([tr("FILMPROJEKT"), tr("ZIELZEIT"), tr("STATUS"), tr("GEÄNDERT")])
        self.projects_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.projects_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.projects_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.projects_table.horizontalHeader().setStretchLastSection(True)
        self.projects_table.cellDoubleClicked.connect(self.open_selected_project)
        layout.addWidget(self.projects_table, 1)
        self.dashboard_hint = self._note(layout, "")

    def _build_project_page(self):
        layout = self.page_layouts[1]
        self._note(layout, tr("Lege zuerst den Film an. Material und Analyse kommen im nächsten Schritt hinzu."))
        form = QFormLayout()
        self.project_title = QLineEdit()
        self.project_title.setMaxLength(200)
        self.project_title.setPlaceholderText(tr("Zum Beispiel: Sommerurlaub am Meer"))
        form.addRow(tr("Filmname"), self.project_title)
        self.project_duration = QDoubleSpinBox()
        self.project_duration.setRange(0.1, 180)
        self.project_duration.setValue(12)
        self.project_duration.setSuffix(tr(" Minuten"))
        form.addRow(tr("Gewünschte Filmlänge"), self.project_duration)
        self.project_prompt = QPlainTextEdit()
        self.project_prompt.setPlaceholderText(tr("Optional für Gemini: Worauf soll die Analyse besonders achten?"))
        self.project_prompt.setMaximumHeight(150)
        form.addRow(tr("Zusätzlicher Gemini-Prompt"), self.project_prompt)
        layout.addLayout(form)
        self._note(layout, tr("Ein geänderter Gemini-Prompt verwendet einen eigenen Analyse-Cache. Unveränderte Projekte und ihre bezahlten Ergebnisse bleiben erhalten."))
        self.project_save_button = QPushButton(tr("Leeren Film anlegen und Material hinzufügen →"))
        self.project_save_button.setObjectName("primaryButton")
        self.project_save_button.clicked.connect(self.create_or_update_project)
        layout.addWidget(self.project_save_button)
        layout.addStretch()

    def _build_music_page(self):
        layout = self.page_layouts[4]
        form = QFormLayout()
        self.cut_style = QComboBox()
        for key, (label, _) in EDITING_TEMPLATES.items():
            self.cut_style.addItem(tr(label), key)
        form.addRow(tr("Schnittart"), self.cut_style)
        self.cut_seconds = QDoubleSpinBox()
        self.cut_seconds.setRange(0.1, 2)
        self.cut_seconds.setSingleStep(0.1)
        self.cut_seconds.setValue(0.6)
        self.cut_seconds.setSuffix(tr(" Sekunden"))
        form.addRow(tr("Übergangsdauer"), self.cut_seconds)
        self.use_music = QCheckBox(tr("Hintergrundmusik verwenden (optional)"))
        form.addRow(self.use_music)
        layout.addLayout(form)
        self._note(layout, tr("Standard: zufällige Übergänge. Ohne Hintergrundmusik bleibt der Originalton erhalten. Musik wird leise mit dem Originalton gemischt und bei Bedarf wiederholt."))
        actions = QHBoxLayout()
        self.prompt_button = QPushButton(tr("Suno-Prompt aus analysierten Clips erstellen"))
        self.prompt_button.clicked.connect(self.create_music_prompt)
        actions.addWidget(self.prompt_button)
        self.copy_prompt_button = QPushButton(tr("Prompt kopieren"))
        self.copy_prompt_button.clicked.connect(self.copy_music_prompt)
        actions.addWidget(self.copy_prompt_button)
        self.import_music_button = QPushButton(tr("Musikdatei auswählen …"))
        self.import_music_button.clicked.connect(self.import_music)
        actions.addWidget(self.import_music_button)
        layout.addLayout(actions)
        self.suno_text = QPlainTextEdit()
        self.suno_text.setPlaceholderText(tr("Der Suno-Prompt wird aus den gespeicherten Ereignissen und Momenten dieses Projekts vorbereitet und kann bearbeitet werden."))
        layout.addWidget(self.suno_text, 1)
        self.music_file_label = self._note(layout, tr("Keine Musik gewählt – Export mit Originalton."))
        self.suno_status = self._note(layout, tr("Prompt kopieren und in Suno verwenden. Lade das erzeugte Lied selbst herunter und wähle es hier als Musikdatei aus. Der Prompt entsteht lokal aus der gespeicherten Gemini-Analyse."))
        for signal in (self.cut_style.currentIndexChanged, self.cut_seconds.valueChanged,
                       self.use_music.toggled, self.suno_text.textChanged):
            signal.connect(self.save_project)

    def model(self):
        return self.settings.value("ai/model", DEFAULT_MODEL, type=str)

    def asset_ids(self):
        return project_asset_ids(self.library, self.project.roots) if self.project else set()

    def selected_assets(self, use_dates=True):
        ids = self.asset_ids()
        if not self.project:
            return []
        assets = (self.library.list_assets_in_capture_date_range(date.fromisoformat(self.project.date_from), date.fromisoformat(self.project.date_to))
                  if use_dates and self.filter_dates.isChecked() else self.library.list_assets())
        return [asset for asset in assets if asset.asset_id in ids]

    def busy(self):
        return self._thread is not None or (self.movie_editor is not None and self.movie_editor.thread is not None)

    def show_step(self, index):
        previous = self.pages.currentIndex()
        if self.busy():
            self.statusBar().showMessage(tr("Bitte den laufenden Auftrag beenden oder abbrechen, bevor du den Schritt wechselst."), 5000)
            self.nav_buttons[previous].setChecked(True)
            return
        if index >= 2 and self.project is None:
            index = 1
        if index < 0 or index >= len(STEPS):
            return
        if self.project is not None and not self.save_project():
            self.nav_buttons[previous].setChecked(True)
            return
        if self.movie_editor:
            self.movie_editor.stop_preview()
        self.pages.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        self.page_title.setText(f"{index + 1}. {tr(STEPS[index])}")
        self.back_button.setVisible(index > 0)
        self.next_button.setVisible(0 < index < 5)
        self.step_hint.setText(tr("Schritt {0} von 6", index + 1) if index else "")
        if self.project and index:
            self.project.step = index
            self.store.save(self.project)
        for step, button in enumerate(self.nav_buttons):
            button.setEnabled(step < 2 or self.project is not None)
        if index == 0:
            self.refresh_dashboard()
        if index == 3:
            self.refresh_analysis_status()

    def next_step(self):
        index = self.pages.currentIndex()
        if index == 1:
            self.create_or_update_project()
        elif index == 2 and not self.selected_assets(False):
            self.statusBar().showMessage(tr("Bitte zuerst Projektmaterial hinzufügen und indexieren."), 6000)
        else:
            self.show_step(index + 1)

    def new_project(self):
        if self.busy() or not self.save_project():
            return
        self.dispose_editor()
        self.project = None
        self._loading = True
        self.project_title.clear()
        self.project_prompt.clear()
        self.project_duration.setValue(12)
        self.filter_dates.setChecked(False)
        self.cut_style.setCurrentIndex(self.cut_style.findData("random"))
        self.cut_seconds.setValue(0.6)
        self.use_music.setChecked(False)
        self.suno_text.clear()
        self.music_file_label.setText(tr("Keine Musik gewählt – Export mit Originalton."))
        self._loading = False
        self.project_save_button.setText(tr("Leeren Film anlegen und Material hinzufügen →"))
        self.project_label.setText(tr("Neuer Film"))
        self.settings.setValue("library/folders", [])
        self._refresh_library_state()
        self._refresh_job_choices()
        self._refresh_analysis_choices()
        self.show_step(1)
        self.project_title.setFocus()

    def create_or_update_project(self):
        if self.project is None:
            self.project = FilmProject()
            if not self.save_project():
                self.project = None
                return
        elif not self.save_project():
            return
        self.project_save_button.setText(tr("Projektdaten speichern und weiter →"))
        self.show_step(2)

    def save_project(self, *_):
        if self._loading or self.project is None:
            return True
        from copy import deepcopy
        updated = deepcopy(self.project)
        updated.title = self.project_title.text().strip()
        updated.target_seconds = round(self.project_duration.value() * 60)
        updated.prompt = self.project_prompt.toPlainText().strip()
        updated.roots = self.settings.value("library/folders", [], type=list)
        updated.date_from = self.date_from.date().toString("yyyy-MM-dd") if self.filter_dates.isChecked() else "1900-01-01"
        updated.date_to = self.date_to.date().toString("yyyy-MM-dd") if self.filter_dates.isChecked() else "2100-12-31"
        updated.template = self.cut_style.currentData()
        updated.transition_seconds = self.cut_seconds.value()
        updated.music_enabled = self.use_music.isChecked()
        updated.suno_prompt = self.suno_text.toPlainText()
        if self.movie_editor and self.pages.currentIndex() == 5:
            editor = self.movie_editor
            updated.title = editor.title.text().strip()
            updated.target_seconds = round(editor.duration.value())
            style = editor.plan.editing_style if editor.plan else EditingStyle(editor.style_combo.currentData(), editor.transition_duration.value())
            updated.template, updated.transition_seconds = style.template, style.transition_seconds
            self._loading = True
            self.project_title.setText(updated.title)
            self.project_duration.setValue(updated.target_seconds / 60)
            self.cut_style.setCurrentIndex(self.cut_style.findData(updated.template))
            self.cut_seconds.setValue(updated.transition_seconds)
            self._loading = False
        try:
            self.store.save(updated)
        except (ValueError, OSError) as exc:
            self.statusBar().showMessage(display_message(str(exc)), 8000)
            return False
        changed = (updated.roots, updated.prompt, updated.date_from, updated.date_to) != (self.project.roots, self.project.prompt, self.project.date_from, self.project.date_to)
        self.project = updated
        self.project_label.setText(updated.title)
        if self.movie_editor:
            editor = self.movie_editor
            editor.title.setText(updated.title)
            editor.duration.setValue(updated.target_seconds)
            editor.music_path = updated.music_path if updated.music_enabled else ""
            editor.style_combo.setCurrentIndex(editor.style_combo.findData(updated.template))
            editor.transition_duration.setValue(updated.transition_seconds)
            editor.movie_preview_plan = None
            if changed:
                editor.planner = self.planner()
                editor.start_date, editor.end_date = date.fromisoformat(updated.date_from), date.fromisoformat(updated.date_to)
                editor.plan = None
                editor.history = MovieHistory()
                editor.update_history_controls()
                editor.candidates = []
                editor.candidate_warnings = []
                editor.table.setRowCount(0)
                editor.status.setText(tr("Projektmaterial, Zeitraum oder Gemini-Prompt geändert. Bitte die Auswahl neu erzeugen."))
                editor.candidates_loaded = False
            if editor.plan:
                editor.plan.target_seconds = updated.target_seconds
                editor.plan.editing_style = EditingStyle(updated.template, updated.transition_seconds)
                if not editor.persist():
                    return False
                editor.refresh()
        return True

    def refresh_dashboard(self):
        if not hasattr(self, "store"):
            return
        self.dashboard_projects, errors = self.store.list()
        self.projects_table.setRowCount(len(self.dashboard_projects))
        for row, project in enumerate(self.dashboard_projects):
            status = tr("Exportiert") if project.output else (tr("Filmplan vorhanden") if self.store.movie_path(project).exists() else tr(STEPS[project.step]))
            for column, value in enumerate((project.title, tr("{0} Min.", format(project.target_seconds / 60, f'g')), status, project.updated_at[:16].replace("T", " "))):
                self.projects_table.setItem(row, column, QTableWidgetItem(value))
        self.projects_table.resizeColumnsToContents()
        self.dashboard_hint.setText(tr("{0} Filmprojekte", len(self.dashboard_projects)) + (tr(" · {0} beschädigte Projektdateien übersprungen: {1}", len(errors), ', '.join(errors)) if errors else ""))

    def open_selected_project(self, *_):
        row = self.projects_table.currentRow()
        if 0 <= row < len(self.dashboard_projects):
            self.load_project(self.dashboard_projects[row])

    def watch_selected_project(self):
        row = self.projects_table.currentRow()
        if 0 <= row < len(self.dashboard_projects):
            output = self.dashboard_projects[row].output
            if output and Path(output).is_file():
                QDesktopServices.openUrl(QUrl.fromLocalFile(output))
            else:
                self.statusBar().showMessage(tr("Für dieses Projekt ist noch kein erreichbarer Export vorhanden."), 6000)

    def load_project(self, project):
        if self.busy() or not self.save_project():
            return
        if self.project and project.project_id == self.project.project_id:
            project = self.project
        self.dispose_editor()
        self.project = project
        self._loading = True
        self.project_title.setText(project.title)
        self.project_duration.setValue(project.target_seconds / 60)
        self.project_prompt.setPlainText(project.prompt)
        self.settings.setValue("library/folders", project.roots)
        self.filter_dates.setChecked(project.date_from != "1900-01-01" or project.date_to != "2100-12-31")
        self.date_from.setDate(QDate.fromString(project.date_from, "yyyy-MM-dd"))
        self.date_to.setDate(QDate.fromString(project.date_to, "yyyy-MM-dd"))
        self.cut_style.setCurrentIndex(self.cut_style.findData(project.template))
        self.cut_seconds.setValue(project.transition_seconds)
        self.use_music.setChecked(project.music_enabled)
        self.suno_text.setPlainText(project.suno_prompt)
        self.music_file_label.setText(project.music_path or tr("Keine Musik gewählt – Export mit Originalton."))
        self.project_label.setText(project.title)
        self._loading = False
        self._refresh_library_state()
        self._refresh_job_choices()
        self._refresh_analysis_choices()
        self.show_step(project.step)

    def add_folder(self):
        if self.project is None:
            return
        super().add_folder()
        self.save_project()
        self._refresh_job_choices()
        self._refresh_analysis_choices()

    def _refresh_job_choices(self, selected_job_id=None):
        super()._refresh_job_choices(selected_job_id)
        roots = set(self.project.roots) if self.project else set()
        for index in reversed(range(self.job_selector.count())):
            job = self.library.get_index_job(self.job_selector.itemData(index))
            if not job or not roots or not {str(root) for root in job.roots} <= roots:
                self.job_selector.removeItem(index)
        idle = not self.busy()
        self.job_selector.setEnabled(bool(self.job_selector.count()) and idle)
        self.resume_button.setEnabled(bool(self.job_selector.count()) and idle)
        self._refresh_error_button()

    def _refresh_analysis_choices(self, selected_job_id=None):
        super()._refresh_analysis_choices(selected_job_id)
        ids = self.asset_ids()
        for index in reversed(range(self.analysis_job_selector.count())):
            rows = self.library.list_media_analysis_job_items(self.analysis_job_selector.itemData(index))
            if not rows or not {row["asset_id"] for row in rows} <= ids:
                self.analysis_job_selector.removeItem(index)
        idle = not self.busy()
        self.analysis_job_selector.setEnabled(bool(self.analysis_job_selector.count()) and idle)
        self.resume_analysis_button.setEnabled(bool(self.analysis_job_selector.count()) and idle)
        self._refresh_analysis_error_button()

    def find_in_date_range(self):
        if self.project is None or not self.save_project():
            return
        assets = self.selected_assets()
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Projektmaterial im Zeitraum"))
        dialog.resize(850, 500)
        layout = QVBoxLayout(dialog)
        self._note(layout, tr("{0} Projektvideos · Anzeige der ersten 200. Videos ohne Aufnahmezeit bleiben bei einem Datumsfilter unberücksichtigt.", len(assets)))
        table = QTableWidget(min(len(assets), 200), 2)
        table.setHorizontalHeaderLabels([tr("QUELLE"), tr("AUFNAHMEZEIT")])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        for row, asset in enumerate(assets[:200]):
            table.setItem(row, 0, QTableWidgetItem(str(asset.path)))
            table.setItem(row, 1, QTableWidgetItem(str(asset.capture_time.value) if asset.capture_time else tr("Unbekannt")))
        layout.addWidget(table)
        done = QPushButton(tr("Schließen"))
        done.clicked.connect(dialog.accept)
        layout.addWidget(done)
        dialog.exec()

    def start_analysis(self):
        if self.busy() or not self.save_project():
            return
        assets = self.selected_assets()
        if not assets:
            self.statusBar().showMessage(tr("Bitte zuerst Projektmaterial indexieren und den Zeitraum prüfen."), 6000)
            return
        job = self.analysis_service.create_job({asset.asset_id for asset in assets})
        self._run_analysis_job(job.job_id)

    def refresh_analysis_status(self):
        assets = self.selected_assets()
        current = sum(asset.analysis_status == AnalysisStatus.COMPLETE and asset.analysis_version == LOCAL_ANALYSIS_VERSION for asset in assets)
        unknown = sum(asset.capture_time is None for asset in assets)
        self.analysis_hint.setText(tr("{0} Projektvideos · {1} lokal analysiert · {2} ohne Aufnahmezeit. Gemini verwendet nur erfolgreich lokal analysierte Videos. Einzelne Fehler sperren die übrigen Aufnahmen nicht. Ohne Aufnahmezeit bitte die Datumsprüfung verwenden.", len(assets), current, unknown))
        self.gemini_button.setEnabled(current > 0 and not self.busy())

    def open_semantic_analysis(self):
        if self.busy() or self.project is None or not self.save_project():
            return
        assets = self.selected_assets()
        assets = [asset for asset in assets if asset.analysis_status == AnalysisStatus.COMPLETE and asset.analysis_version == LOCAL_ANALYSIS_VERSION]
        if not assets:
            self.statusBar().showMessage(tr("Bitte zuerst die lokale OpenCV-Analyse für das Projekt abschließen."), 6000)
            return
        try:
            dialog = SemanticDialog(self.library, assets, self.model(), self,
                                    user_prompt=self.project.prompt, profile=self.project.analysis_profile)
            dialog.exec()
        except ValueError as exc:
            self.statusBar().showMessage(display_message(str(exc)), 8000)
        self.refresh_analysis_status()

    def planner(self):
        return MoviePlanningService(SemanticRepository(self.library, self.project.analysis_profile), self.asset_ids())

    def create_music_prompt(self):
        if self.project is None or not self.save_project():
            return
        try:
            candidates, _ = self.planner().candidates(date.fromisoformat(self.project.date_from), date.fromisoformat(self.project.date_to), "gemini", self.model())
            self.suno_text.setPlainText(music_prompt(candidates, self.project.title, self.project.target_seconds, language=language()))
            self.save_project()
        except (ValueError, OSError) as exc:
            self.statusBar().showMessage(display_message(str(exc)), 8000)

    def copy_music_prompt(self):
        prompt = self.suno_text.toPlainText().strip()
        if prompt:
            QApplication.clipboard().setText(prompt)
            self.statusBar().showMessage(tr("Suno-Prompt kopiert."), 4000)

    def import_music(self):
        if self.project is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, tr("Musik für diesen Film auswählen"), "", tr("Musik (*.mp3 *.wav *.m4a *.aac *.flac *.ogg)"))
        if path:
            self.project.music_path = str(Path(path).resolve())
            self.use_music.setChecked(True)
            self.music_file_label.setText(self.project.music_path)
            self.save_project()

    def open_movie(self):
        if self.busy() or self.project is None or not self.save_project():
            return
        self.show_step(5)
        if self.movie_editor is None:
            project = self.project
            editor = MovieDialog(self.library, date.fromisoformat(project.date_from), date.fromisoformat(project.date_to), project.target_seconds, self.model(), self)
            editor.setWindowFlags(Qt.WindowType.Widget)
            editor.setMinimumSize(0, 0)
            editor.project_path = self.store.movie_path(project)
            editor.status.setText(tr("Automatische Speicherung: {0}", editor.project_path))
            editor.planner = self.planner()
            editor.title.setText(project.title)
            editor.style_combo.setCurrentIndex(editor.style_combo.findData(project.template))
            editor.transition_duration.setValue(project.transition_seconds)
            editor.music_path = project.music_path if project.music_enabled else ""
            editor.output = Path(project.output) if project.output else None
            # Project identity and file location are managed by the dashboard.
            for button in editor.project_file_buttons[:2]:
                button.hide()
            if editor.project_path.exists():
                try:
                    plan = load_movie(editor.project_path)
                    if ({item.source.asset_id for item in plan.segments} <= self.asset_ids()
                            and (plan.date_from, plan.date_to, plan.analysis_profile) ==
                            (project.date_from, project.date_to, project.analysis_profile)):
                        editor.plan = plan
                        editor.history.record(editor.plan)
                        editor.refresh()
                    else:
                        editor.status.setText(tr("Projektvorgaben geändert. Bitte die Auswahl aus dem aktuellen Analysebestand neu erzeugen."))
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    QMessageBox.warning(self, tr("Filmplan konnte nicht geöffnet werden"), display_message(str(exc)))
                    editor.deleteLater()
                    return
            self.movie_editor = editor
            editor.plan_saved.connect(self.sync_movie_project)
            editor.movie_exported.connect(self.record_export)
            self.page_layouts[5].addWidget(editor, 1)
            editor.show()
            self.open_editor_button.hide()
            self.export_hint.hide()

    def sync_movie_project(self, plan):
        if self.project is None:
            return
        self._loading = True
        self.project.title = plan.title
        self.project.target_seconds = round(plan.target_seconds)
        self.project.template = plan.editing_style.template
        self.project.transition_seconds = plan.editing_style.transition_seconds
        self.project_title.setText(self.project.title)
        self.project_duration.setValue(self.project.target_seconds / 60)
        self.cut_style.setCurrentIndex(self.cut_style.findData(self.project.template))
        self.cut_seconds.setValue(self.project.transition_seconds)
        self.project_label.setText(self.project.title)
        self._loading = False
        try:
            self.store.save(self.project)
        except (ValueError, OSError) as exc:
            self.statusBar().showMessage(tr("Projektübersicht konnte nicht gespeichert werden: {0}", exc), 8000)

    def record_export(self, output):
        self.project.output = output
        try:
            self.store.save(self.project)
        except (ValueError, OSError) as exc:
            self.statusBar().showMessage(tr("Film exportiert; Projektübersicht konnte nicht gespeichert werden: {0}", exc), 8000)

    def dispose_editor(self):
        if self.movie_editor is not None:
            self.movie_editor.reject()
            self.page_layouts[5].removeWidget(self.movie_editor)
            self.movie_editor.deleteLater()
            self.movie_editor = None
        self.open_editor_button.show()
        self.export_hint.show()

    def open_recovery(self):
        if self.busy():
            self.statusBar().showMessage(tr("Bitte den laufenden Auftrag vor der Wiederherstellung beenden."), 6000)
            return
        super().open_recovery()

    @Slot()
    def _on_thread_stopped(self):
        super()._on_thread_stopped()
        if self.project:
            self.refresh_analysis_status()

    def closeEvent(self, event):
        if self.movie_editor and self.movie_editor.thread is not None:
            self.movie_editor.token.set()
            self.statusBar().showMessage(tr("Export wird sicher beendet. Bitte anschließend erneut schließen."))
            event.ignore()
            return
        if not self.save_project():
            event.ignore()
            return
        self.dispose_editor()
        super().closeEvent(event)
