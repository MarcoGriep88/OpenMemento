"""Language selection, catalogue integrity and real desktop localization."""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from string import Formatter
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QLocale, QSettings, Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QPushButton

from memento import i18n
from memento.library.database import MediaLibrary


@pytest.fixture
def locale_state():
    app = QApplication.instance() or QApplication([])
    previous_language, previous_locale = i18n.language(), QLocale()
    yield app
    translator = getattr(app, "_memento_translator", None)
    if translator is not None:
        app.removeTranslator(translator)
    i18n.set_language(previous_language)
    QLocale.setDefault(previous_locale)


@pytest.mark.parametrize("saved,system,expected", [
    ("en", "de_DE", "en"), ("de", "en_US", "de"),
    (None, "de_AT", "de"), ("", "de-DE", "de"),
    (None, "en_GB", "en"), (None, "fr_FR", "en"),
    ("invalid", "de_DE", "de"), ("invalid", "es_ES", "en"),
])
def test_language_resolution(saved, system, expected):
    assert i18n.resolve_language(saved, system) == expected


def test_catalog_placeholders_and_translated_source_coverage():
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            assert key not in result, f"Duplicate translation: {key}"
            result[key] = value
        return result

    root = Path(i18n.__file__).parent
    for path in root.joinpath("resources").glob("i18n*_en.json"):
        catalog = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        for source, target in catalog.items():
            assert target.strip()
            fields = lambda text: sorted(field for _, field, _, _ in Formatter().parse(text) if field is not None)
            assert fields(source) == fields(target), source
    for path in [*root.joinpath("ui").glob("*.py"), root / "app.py"]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr":
                if node.args and isinstance(node.args[0], ast.Constant):
                    assert node.args[0].value in i18n.english_catalog(), (path, node.lineno)


def test_language_preference_survives_new_settings_instance_and_override_is_temporary(locale_state, tmp_path):
    settings_path = str(tmp_path / "settings.ini")
    settings = QSettings(settings_path, QSettings.Format.IniFormat)
    settings.setValue(i18n.LANGUAGE_KEY, "en")
    settings.sync()
    assert i18n.configure(QSettings(settings_path, QSettings.Format.IniFormat), locale_state) == "en"
    assert i18n.tr("Einstellungen") == "Settings"
    assert i18n.configure(settings, locale_state, "de") == "de"
    assert settings.value(i18n.LANGUAGE_KEY) == "en"
    assert i18n.tr("Einstellungen") == "Einstellungen"
    assert QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel).button(
        QDialogButtonBox.StandardButton.Cancel).text().replace("&", "") == "Abbrechen"
    i18n.configure(settings, locale_state, "en")
    assert QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel).button(
        QDialogButtonBox.StandardButton.Cancel).text().replace("&", "") == "Cancel"


def test_dates_numbers_and_messages_do_not_change_recorded_time_or_user_data(locale_state):
    recorded = datetime(2026, 7, 12, 10, 30, tzinfo=timezone(timedelta(hours=2)))
    i18n.set_language("en")
    assert i18n.format_date(recorded, with_time=True) == "2026-07-12 10:30:00"
    assert i18n.format_number(1.25) == "1.25"
    assert i18n.display_message("Segment 3 von 8 vorbereitet") == "Segment 3 of 8 prepared"
    assert i18n.display_message("My family – Geburtstag.mp4") == "My family – Geburtstag.mp4"
    assert i18n.tr("{0} Ordner", 12) == "12 folders"
    i18n.set_language("de")
    assert i18n.format_date(recorded, with_time=True) == "12.07.2026 10:30:00"
    assert i18n.format_number(1.25) == "1,25"
    assert i18n.display_message("OpenCV could not open this video") == "OpenCV konnte dieses Video nicht öffnen."
    assert recorded.utcoffset() == timedelta(hours=2)


@pytest.mark.parametrize("code,expected_title,expected_next", [
    ("en", "OpenMemento – Your movie projects", "Next →"),
    ("de", "OpenMemento – Deine Filmprojekte", "Weiter →"),
])
def test_workflow_dialogs_and_headers_in_both_languages(locale_state, tmp_path, monkeypatch, code, expected_title, expected_next):
    from memento.ui import main_window, settings_dialog
    from memento.ui.capture_time_dialog import CaptureTimeDialog
    from memento.ui.date_range_dialog import DateRangeDialog
    from memento.ui.event_review_dialog import EventReviewModel
    from memento.ui.workflow_window import WorkflowWindow

    i18n.set_language(code)
    QLocale.setDefault(QLocale("en_GB" if code == "en" else "de_DE"))
    settings = QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_window, "QSettings", lambda: settings)
    monkeypatch.setattr(settings_dialog, "QSettings", lambda: settings)
    monkeypatch.setattr(settings_dialog, "has_gemini_key", lambda: False)
    library = MediaLibrary(tmp_path / "library.sqlite3")
    window = WorkflowWindow(library)
    dialogs = []
    try:
        assert window.windowTitle() == expected_title
        assert expected_next in [b.text() for b in window.findChildren(QPushButton)]
        assert window.nav_buttons[1].text().endswith(i18n.tr("Film anlegen"))
        assert window.projects_table.horizontalHeaderItem(0).text() == i18n.tr("FILMPROJEKT")
        assert window.cut_style.itemData(0) == "random"
        assert window.cut_style.itemText(0) == i18n.tr("Zufällige Übergänge")
        ranges = DateRangeDialog(library, date(2026, 7, 1), date(2026, 7, 31), window)
        capture = CaptureTimeDialog(library, window)
        settings_ui = settings_dialog.SettingsDialog(window)
        dialogs.extend([ranges, capture, settings_ui])
        assert ranges.windowTitle() == i18n.tr("Aufnahmen im Zeitraum")
        assert ranges.model.headerData(0, Qt.Orientation.Horizontal) == i18n.tr("AUFNAHMEZEIT")
        assert capture.day.displayFormat() == i18n.date_pattern(qt=True)
        assert settings_ui.windowTitle() == i18n.tr("Einstellungen")
        assert settings_ui.language_combo.count() == 2
        assert EventReviewModel.HEADERS[0] == "EREIGNIS"  # stable source, translated at display time
    finally:
        for dialog in dialogs:
            dialog.close()
        window.close()
        locale_state.processEvents()


def test_settings_save_and_cancel_do_not_change_active_language(locale_state, tmp_path, monkeypatch):
    from memento.ui import settings_dialog

    i18n.set_language("de")
    settings = QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings_dialog, "QSettings", lambda: settings)
    monkeypatch.setattr(settings_dialog, "has_gemini_key", lambda: False)
    dialog = settings_dialog.SettingsDialog()
    dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("en"))
    dialog.reject()
    assert settings.value(i18n.LANGUAGE_KEY) is None
    dialog = settings_dialog.SettingsDialog()
    dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("en"))
    dialog._save()
    assert settings.value(i18n.LANGUAGE_KEY) == "en"
    assert i18n.language() == "de"


def test_persisted_decisions_are_only_translated_for_display(locale_state):
    from memento.ui.candidate_dialog import CandidateTableModel

    original = "Auf Nutzerwunsch ausgeschlossen."
    plan = SimpleNamespace(preferences=SimpleNamespace(forced=set(), excluded=set(), trims={}),
                           decisions={"moment": original}, events=[], segments=[])
    i18n.set_language("en")
    model = CandidateTableModel(plan, [])
    assert model.data(model.index(0, 4)) == "Excluded by user preference."
    assert model.headerData(1, Qt.Orientation.Horizontal) == "SOURCE / RANGE"
    assert plan.decisions["moment"] == original


@pytest.mark.parametrize("code,title", [
    ("en", "OpenMemento – Your movie projects"),
    ("de", "OpenMemento – Deine Filmprojekte"),
])
def test_real_startup_uses_requested_language(tmp_path, code, title):
    script = '''
import json, sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import memento.app as entry
Base = entry.MainWindow
class CheckedWindow(Base):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        print(json.dumps({"title": self.windowTitle()}), flush=True)
        QTimer.singleShot(0, QApplication.instance().quit)
entry.MainWindow = CheckedWindow
sys.argv = ["memento", "--language", sys.argv[1]]
raise SystemExit(entry.main())
'''
    environment = dict(os.environ, MEMENTO_DATA_DIR=str(tmp_path / "data"), QT_QPA_PLATFORM="offscreen")
    result = subprocess.run([sys.executable, "-c", script, code], env=environment,
                            capture_output=True, text=True, timeout=25,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["title"] == title


def test_music_prompt_language_preserves_analyzed_content(locale_state):
    from memento.application.music import music_prompt

    candidate = SimpleNamespace(event_label="Familienausflug", description="Lachen am Meer")
    original = vars(candidate).copy()
    prompt = music_prompt([candidate], "Urlaub", 120, language="en")
    assert "Instrumental soundtrack" in prompt
    assert "Familienausflug" in prompt and "Lachen am Meer" in prompt
    assert vars(candidate) == original
