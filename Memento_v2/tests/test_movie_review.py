from __future__ import annotations

import os
from copy import deepcopy
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from memento.domain.movie import MovieEvent, MoviePlan, MoviePreferences, MovieSegment, MovieSource
from memento.domain.movie_review import review_events
from memento.library.database import MediaLibrary
from memento.ui import movie_dialog
from memento.ui.event_review_dialog import EventReviewDialog


@pytest.fixture
def plan(tmp_path):
    source = MovieSource("source", str((tmp_path / "source.mp4").resolve()), 100,
                         "2026-07-12T10:00:00", 30, True, 96, 64)
    return MoviePlan("movie", "Familienfilm", 20, "2026-07-12", "2026-07-12", "gemini", "test-model", "test",
        [MovieEvent("garden", "Garten", ("a", "b")), MovieEvent("boat", "Bootsfahrt", ("c",)),
         MovieEvent("unused", "Abreise", ("d",))],
        [MovieSegment("a", "garden", source, 0, 8, "Kind lacht", ()),
         MovieSegment("b", "garden", source, 8, 10, "Hund spielt", (), enabled=False),
         MovieSegment("c", "boat", source, 10, 14, "Gemeinsam im Boot", ())],
        MoviePreferences(forced={"b"}, excluded={"a"}, trims={"a": (1, 4)}, event_weights={"garden": 3}),
        {"a": "Alte Auswahlentscheidung"})


def test_event_review_measures_actual_timeline_and_unapplied_preferences(plan):
    before = deepcopy(plan)
    garden, boat, unused = review_events(plan)
    assert garden.duration_seconds == 8 and garden.share == pytest.approx(2 / 3)
    assert garden.selected_moments == 1 and garden.known_moments == 2
    assert garden.excluded_moments == garden.forced_moments == 1
    assert garden.weight == 3
    assert garden.pending_forced == garden.pending_excluded == garden.pending_trims == 1
    assert garden.pending == 3
    assert boat.duration_seconds == 4 and boat.share == pytest.approx(1 / 3)
    assert boat.pending == 0 and boat.weight == 1
    assert unused.duration_seconds == unused.share == unused.selected_moments == 0
    assert unused.known_moments == 1
    assert sum(item.duration_seconds for item in (garden, boat, unused)) == plan.duration
    assert plan == before  # No rewrite of historical decisions or editing state.


def test_empty_output_review_has_no_division_error_and_disabled_ranges_do_not_count(plan):
    for segment in plan.segments:
        segment.enabled = False
    rows = review_events(plan)
    assert all(item.duration_seconds == item.share == item.selected_moments == 0 for item in rows)
    assert rows[0].pending_forced == 1
    assert rows[0].pending_excluded == rows[0].pending_trims == 0
    plan.segments.clear()
    assert len(review_events(plan)) == 3  # Omitted events remain inspectable.


def test_event_overview_is_read_only_and_exposes_selected_event_details(plan, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    day = date(2026, 7, 12)
    library = MediaLibrary(tmp_path / "library.sqlite3")
    dialog = movie_dialog.MovieDialog(library, day, day, 20, "test-model")
    dialog.planned((plan, []))
    dialog.persist()
    original = dialog.project_path.read_bytes()
    before = deepcopy(dialog.plan)
    inspected = []

    def inspect(overview):
        inspected.append(True)
        assert overview.model.rowCount() == 3
        assert overview.model.data(overview.model.index(0, 1)) == "8,0"
        assert overview.model.data(overview.model.index(0, 2)) == "66,7 %"
        assert overview.model.data(overview.model.index(0, 3)) == "1 / 2"
        overview.table.selectRow(0)
        assert "Erzwungen, aber nicht enthalten: 1" in overview.details.text()
        assert "Abweichende manuelle Schnittvorgaben: 1" in overview.details.text()
        return 0

    monkeypatch.setattr(EventReviewDialog, "exec", inspect)
    monkeypatch.setattr(library, "_connect", lambda: pytest.fail("Review must only read the plan snapshot"))
    dialog.review_events()
    assert inspected and dialog.plan == before
    assert dialog.project_path.read_bytes() == original
    assert not dialog.history.can_undo
    # Normal dialog cleanup writes only the project, not the library.
    dialog.reject()


def test_overview_reports_constraints_outside_saved_events(plan):
    app = QApplication.instance() or QApplication([])
    plan.preferences.forced.add("historical-missing-id")
    overview = EventReviewDialog(plan)
    assert "Eine Momentvorgabe ist keinem gespeicherten Ereignis zugeordnet" in overview.unassigned_notice.text()
    assert "historical-missing-id" in plan.preferences.forced  # Inspection never silently drops constraints.
    overview.reject()
