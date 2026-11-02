from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtTest import QTest

from memento.application.movie_planning import PlanningCancelled
from memento.domain.movie import CandidateSegment, MovieEvent, MoviePlan, MoviePreferences, MovieSegment, MovieSource
from memento.library.database import MediaLibrary
from memento.library.movies import load_movie, save_movie
from memento.ui.candidate_dialog import CandidateDialog, CandidateTableModel
from memento.ui.movie_dialog import MovieDialog


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def movie(tmp_path):
    source = MovieSource("asset", str((tmp_path / "source.mp4").resolve()), 10,
                         "2026-07-12T10:00:00", 20, True, 96, 64)
    candidates = [CandidateSegment("moment", source, 2, 8, datetime(2026, 7, 12, 10),
        "Kind lacht", "Ausflug", (), (), 0.9, 0.9, 0.9, 0.9, 1, ("Interaktion",))]
    plan = MoviePlan("plan", "Mein bearbeiteter Film", 12, "2026-07-12", "2026-07-12", "gemini", "test-model", "test",
        [MovieEvent("event", "Ausflug", ("moment", "missing"))],
        [MovieSegment("moment", "event", source, 3, 7, "Kind lacht", ("Manuell bearbeitet",))],
        MoviePreferences(forced={"missing"}, trims={"missing": (1, 3), "moment": (3, 7)}),
        {"moment": "Ausgewählt", "missing": "Ausgewählt im früheren Bestand"})
    return plan, candidates


def wait_until(app, predicate):
    loop, timer = QEventLoop(), QTimer()
    timer.timeout.connect(lambda: loop.quit() if predicate() else None)
    timer.start(10)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    timer.stop()
    app.processEvents()
    assert predicate()


def test_model_isolated_constraints_and_missing_forced_range_can_be_cleared(app, movie):
    plan, candidates = movie
    before = deepcopy(plan)
    model = CandidateTableModel(plan, candidates)
    assert model.rowCount() == 2
    assert "Nicht im aktuellen" in model.data(model.index(1, 0))
    assert "3.000–7.000" in model.data(model.index(0, 1))
    assert model.setData(model.index(0, 2), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert model.setData(model.index(0, 3), Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole)
    assert "moment" not in model.preferences.excluded
    assert "moment" in model.preferences.forced
    assert model.setData(model.index(1, 3), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert "missing" not in model.preferences.forced
    assert not model.setData(model.index(1, 3), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    model.clear_trim(1)
    model.clear_trim(0)
    assert not model.preferences.trims
    assert "2.000–8.000" in model.data(model.index(0, 1))
    model.preferences.validate()
    assert plan == before


def test_candidate_table_reads_large_collections_on_demand(app, movie):
    plan, candidates = movie
    many = [replace(candidates[0], candidate_id=f"candidate-{index}") for index in range(20_000)]
    model = CandidateTableModel(plan, many)
    assert model.rowCount() == 20_002  # Includes both saved historical IDs.
    assert model.data(model.index(19_999, 0)).endswith("Kind lacht")
    assert model.data(model.index(19_999, 2), Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked


def test_dialog_checkboxes_are_interactive_and_cancel_preserves_constraints(app, movie):
    plan, candidates = movie
    before = deepcopy(plan)
    dialog = CandidateDialog(plan, candidates)
    dialog.show()
    app.processEvents()
    index = dialog.model.index(0, 2)
    dialog.table.setCurrentIndex(index)
    dialog.table.setFocus()
    QTest.keyClick(dialog.table, Qt.Key.Key_Space)
    assert "moment" in dialog.model.preferences.excluded
    dialog.table.setCurrentIndex(dialog.model.index(0, 3))
    QTest.keyClick(dialog.table, Qt.Key.Key_Space)
    assert "moment" in dialog.model.preferences.forced
    assert "moment" not in dialog.model.preferences.excluded
    dialog.reject()
    assert plan == before


def test_reopened_movie_loads_candidates_without_replanning_and_edits_are_undoable(app, movie, tmp_path, monkeypatch):
    plan, candidates = movie
    project = tmp_path / "edited.memento.json"
    save_movie(project, plan)
    before_bytes = project.read_bytes()
    library = MediaLibrary(tmp_path / "library.sqlite3")
    day = date(2026, 7, 12)
    dialog = MovieDialog(library, day, day, 12, "test-model")
    monkeypatch.setattr("memento.ui.movie_dialog.QFileDialog.getOpenFileName", lambda *args: (str(project), ""))
    dialog.open_project()
    dialog.show()
    loads, inspections = [], []

    def load(start, end, provider, model, cancel_token):
        loads.append((start, end, provider, model))
        return candidates, ["Teilweise fehlender Analysebestand"]

    monkeypatch.setattr(dialog.planner, "candidates", load)
    monkeypatch.setattr(dialog.planner, "build", lambda *args, **kwargs: pytest.fail("Inspection must not regenerate the plan"))

    def inspect(child):
        assert dialog.thread is None
        assert dialog.plan == plan
        inspections.append(child.model)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(CandidateDialog, "exec", inspect)
    dialog.edit_candidates()
    wait_until(app, lambda: dialog.thread is None and bool(inspections))
    assert project.read_bytes() == before_bytes
    assert dialog.plan == plan and not dialog.history.can_undo
    assert len(loads) == 1

    def edit(child):
        model = child.model
        missing_row = model.keys.index("missing")
        model.setData(model.index(missing_row, 3), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
        model.clear_trim(missing_row)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(CandidateDialog, "exec", edit)
    dialog.edit_candidates()
    assert len(loads) == 1  # Reuse this successful local load.
    assert not dialog.plan.preferences.forced
    assert "missing" not in dialog.plan.preferences.trims
    assert dialog.plan.segments == plan.segments
    assert load_movie(project) == dialog.plan
    dialog.restore_edit(-1)
    assert dialog.plan == plan == load_movie(project)
    dialog.reject()


def test_cancelled_candidate_loading_keeps_project_and_allows_retry(app, movie, tmp_path, monkeypatch):
    plan, candidates = movie
    dialog = MovieDialog(MediaLibrary(tmp_path / "library.sqlite3"), date(2026, 7, 12), date(2026, 7, 12), 12, "test-model")
    dialog.plan = deepcopy(plan)
    dialog.history.reset(plan)
    dialog.title.setText(plan.title)
    dialog.persist()
    original = dialog.project_path.read_bytes()
    dialog.show()
    started, opened = [], []

    def load(*args, cancel_token):
        started.append(True)
        cancel_token.wait(5)
        raise PlanningCancelled("Laden abgebrochen")

    monkeypatch.setattr(dialog.planner, "candidates", load)
    monkeypatch.setattr(dialog, "show_candidates", lambda: opened.append(True))
    dialog.edit_candidates()
    wait_until(app, lambda: bool(started))
    dialog.token.set()
    wait_until(app, lambda: dialog.thread is None)
    assert not opened and not dialog.candidates_loaded
    assert dialog.project_path.read_bytes() == original
    assert dialog.plan == plan
    monkeypatch.setattr(dialog.planner, "candidates", lambda *args, **kwargs: (candidates, []))
    dialog.edit_candidates()
    wait_until(app, lambda: dialog.thread is None and bool(opened))
    assert dialog.candidates_loaded
    dialog.reject()
