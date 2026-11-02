from copy import deepcopy

import pytest

from memento.domain.movie import MoviePlan
from memento.domain.movie_history import MovieHistory


def plan(title="Film"):
    return MoviePlan("film", title, 20, "2026-07-12", "2026-07-12",
                     "gemini", "test-model", "test", [], [])


def test_history_owns_snapshots_and_new_edits_discard_redo():
    history = MovieHistory()
    movie = plan()
    history.reset(movie)
    movie.title = "Neuer Titel"
    movie.preferences.forced.add("moment")
    history.record(movie)
    movie.preferences.forced.add("later")
    saved = []
    restored = history.restore(-1, lambda value: saved.append(deepcopy(value)))
    assert restored == saved[-1] == plan()
    assert not restored.preferences.forced
    restored.title = "Lokale Mutation"
    assert history.current.title == "Film"
    history.record(history.current)  # Autosave without changes retains redo.
    assert history.can_redo
    assert history.restore(1, lambda value: None).preferences.forced == {"moment"}
    history.restore(-1, lambda value: None)
    history.record(plan("Andere Änderung"))
    assert not history.can_redo


def test_history_is_bounded_and_disk_failure_keeps_cursor():
    history = MovieHistory(limit=2)
    for index in range(5):
        history.record(plan(str(index)))

    def failure(value):
        raise OSError("Datenträger voll")

    with pytest.raises(OSError):
        history.restore(-1, failure)
    assert history.current.title == "4"
    assert history.can_undo and not history.can_redo
    assert history.restore(-1, lambda value: None).title == "3"
    assert history.restore(-1, lambda value: None).title == "2"
    assert history.restore(-1, lambda value: None) is None
    history.reset(plan("Anderer Film"))
    assert not history.can_undo and not history.can_redo


def test_invalid_snapshot_cannot_erase_redo():
    history = MovieHistory()
    history.record(plan())
    history.record(plan("Titel"))
    history.restore(-1, lambda value: None)
    with pytest.raises(ValueError):
        history.record(plan(""))
    assert history.can_redo
