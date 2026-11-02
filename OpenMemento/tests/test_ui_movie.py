from __future__ import annotations

import os
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from memento.ai.contracts import Moment, SemanticResult
from memento.application.rendering import MovieRenderService, RenderSettings
from memento.domain.media import CaptureTime, MediaAsset, TimestampSource
from memento.domain.movie import MovieEvent, MoviePlan, MovieSegment, MovieSource
from memento.domain.editing import EditingStyle
from memento.library.database import MediaLibrary
from memento.library.movies import load_movie
from memento.library.semantic import SemanticRepository
from memento.ui import movie_dialog


def wait_until(app, predicate, timeout=15000):
    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    poll.start(10)
    QTimer.singleShot(timeout, loop.quit)
    loop.exec()
    poll.stop()
    app.processEvents()
    return predicate()


def test_ui_planning_edit_save_reopen_and_real_local_export(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    library = MediaLibrary(tmp_path / "library.sqlite3")
    repo = SemanticRepository(library)
    for index in range(2):
        source = tmp_path / f"family-{index}.avi"
        writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"MJPG"), 12, (96, 64))
        assert writer.isOpened()
        for frame in range(48):
            writer.write(np.full((64, 96, 3), (index * 200, frame * 4, 100), dtype=np.uint8))
        writer.release()
        asset = library.save_asset(MediaAsset(str(index), source, source.stat().st_size,
            datetime.fromtimestamp(source.stat().st_mtime).astimezone(),
            CaptureTime(datetime(2026, 7, 12, 10 + index * 3), TimestampSource.QUICKTIME, 0.9),
            duration_seconds=4, has_audio=False, width=96, height=64))
        job = repo.create_job([asset], "gemini", "test-model")
        moment = Moment(0.5, 3.5, f"Familienmoment {index}", f"Ereignis {index}", (), (), 0.8, 0.8, 0.8, 0.9, 0.9, ("Gemeinsames Lachen",))
        repo.save_result(repo.get_job(job), repo.items(job)[0], SemanticResult((moment,)))
    cached_before = [dict(row) for asset in library.list_assets() for row in repo.results_for_asset(asset.asset_id, "gemini", "test-model")]
    day = date(2026, 7, 12)
    dialog = movie_dialog.MovieDialog(library, day, day, 6, "test-model")
    dialog.show()
    dialog.generate_button.click()
    assert wait_until(app, lambda: dialog.thread is None)
    assert dialog.plan is not None
    assert dialog.plan.duration == 6
    assert dialog.table.rowCount() == 2
    assert dialog.project_path.is_file()
    assert not dialog.undo_button.isEnabled()
    initial = deepcopy(dialog.plan)
    dialog.table.selectRow(0)
    dialog.trim_start.setValue(1)
    dialog.trim_end.setValue(3)
    dialog.apply_trim()
    assert dialog.plan.duration == 5
    assert load_movie(dialog.project_path).duration == 5
    trimmed = deepcopy(dialog.plan)
    # A failed save neither consumes undo nor leaves an unsaved edit active.
    messages = []
    with monkeypatch.context() as patch:
        def fail_save(*args):
            raise OSError("Datenträger voll")
        patch.setattr(movie_dialog, "save_movie", fail_save)
        patch.setattr(movie_dialog.QMessageBox, "warning", lambda *args: messages.append(args[-1]))
        dialog.restore_edit(-1)
        assert dialog.plan == trimmed == load_movie(dialog.project_path)
        assert dialog.history.can_undo and not dialog.history.can_redo
        dialog.table.selectRow(0)
        dialog.remove_segment()
        assert dialog.plan == trimmed == load_movie(dialog.project_path)
    assert len(messages) == 2
    # Invalid source ranges roll back as well, without creating a history entry.
    with monkeypatch.context() as patch:
        patch.setattr(movie_dialog.QMessageBox, "warning", lambda *args: None)
        dialog.table.selectRow(0)
        dialog.trim_end.setValue(100)
        dialog.apply_trim()
    assert dialog.plan == trimmed == load_movie(dialog.project_path)
    dialog.undo_button.click()
    assert dialog.plan == initial == load_movie(dialog.project_path)
    dialog.redo_button.click()
    assert dialog.plan == trimmed == load_movie(dialog.project_path)
    dialog.title.setText("Unser Urlaub")
    dialog.title.editingFinished.emit()
    assert load_movie(dialog.project_path).title == "Unser Urlaub"
    dialog.table.setFocus()
    app.processEvents()
    QTest.keyClick(dialog.table, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert dialog.plan.title == trimmed.title
    assert dialog.title.text() == trimmed.title
    dialog.table.selectRow(0)
    dialog.move_segment(1)
    assert dialog.plan.segments[0].source.asset_id == "1"
    moved = deepcopy(dialog.plan)
    dialog.table.selectRow(0)
    dialog.remove_segment()
    assert len(dialog.plan.segments) == 1
    assert dialog.plan.preferences.excluded
    dialog.undo_button.click()
    assert dialog.plan == moved
    assert not dialog.plan.preferences.excluded
    dialog.event_weight.setValue(3)
    dialog.apply_weight()
    weighted = deepcopy(dialog.plan)
    assert not dialog.redo_button.isEnabled()
    dialog.undo_button.click()
    assert dialog.plan == moved
    dialog.redo_button.click()
    assert dialog.plan == weighted
    dialog.duration.setValue(4)
    dialog.generate()
    assert not dialog.undo_shortcut.isEnabled()
    assert wait_until(app, lambda: dialog.thread is None)
    assert dialog.plan.target_seconds == 4
    dialog.undo_button.click()
    assert dialog.plan == weighted == load_movie(dialog.project_path)
    assert dialog.duration.value() == weighted.target_seconds
    saved_project = dialog.project_path
    monkeypatch.setattr(movie_dialog.QFileDialog, "getOpenFileName", lambda *args: (str(saved_project), ""))
    dialog.open_project()
    assert dialog.plan.duration == 5
    assert not dialog.undo_button.isEnabled() and not dialog.redo_button.isEnabled()
    before_preview = deepcopy(dialog.plan)
    frames = []
    dialog.video.videoSink().videoFrameChanged.connect(lambda frame: frames.append(frame.isValid()))
    dialog.movie_preview_button.click()
    assert wait_until(app, lambda: dialog.thread is None)
    assert dialog.movie_preview_path.is_file(), dialog.status.text()
    assert wait_until(app, lambda: any(frames) and dialog.player.duration() > 0)
    assert dialog.preview_kind == "movie"
    assert dialog.preview_segment is None  # Source-relative bounds cannot stop the movie.
    dialog.pause_preview()
    assert dialog.player.playbackState() == movie_dialog.QMediaPlayer.PlaybackState.PausedState
    assert dialog.preview_slider.isEnabled()
    dialog.seek_preview(3500)
    assert wait_until(app, lambda: abs(dialog.player.position() - 3500) < 150)
    dialog.pause_preview()
    assert wait_until(app, lambda: dialog.player.playbackState() == movie_dialog.QMediaPlayer.PlaybackState.PlayingState)
    dialog.stop_preview()
    dialog.media_status_changed(movie_dialog.QMediaPlayer.MediaStatus.LoadedMedia)
    assert dialog.player.playbackState() == movie_dialog.QMediaPlayer.PlaybackState.StoppedState
    assert dialog.plan == before_preview == load_movie(dialog.project_path)
    assert dialog.output is None
    preview_file = dialog.movie_preview_path
    # Inspect actual preview pixels: manual ordering puts the blue-heavy source first.
    capture = cv2.VideoCapture(str(preview_file))
    assert capture.get(cv2.CAP_PROP_FRAME_WIDTH) == 640
    assert abs(capture.get(cv2.CAP_PROP_FRAME_COUNT) / capture.get(cv2.CAP_PROP_FPS) - 5) < 0.2
    capture.set(cv2.CAP_PROP_POS_MSEC, 500)
    ok, first_frame = capture.read()
    assert ok and first_frame[180, 320, 0] > 150
    capture.set(cv2.CAP_PROP_POS_MSEC, 3500)
    ok, last_frame = capture.read()
    assert ok and last_frame[180, 320, 0] < 50
    capture.release()
    dialog.preview_movie()
    assert dialog.thread is None and dialog.movie_preview_path == preview_file
    dialog.stop_preview()
    dialog.table.selectRow(0)
    dialog.trim_start.setValue(1)
    dialog.trim_end.setValue(3)
    dialog.apply_trim()
    dialog.preview_movie()
    assert wait_until(app, lambda: dialog.thread is None)
    assert dialog.movie_preview_path != preview_file
    assert dialog.movie_preview_plan == dialog.plan
    preview_directory = Path(dialog.preview_directory.name)
    output = tmp_path / "family-movie.mp4"
    monkeypatch.setattr(movie_dialog.QFileDialog, "getSaveFileName", lambda *args: (str(output), ""))

    class SmallRender(MovieRenderService):
        def render(self, plan, output, token, progress):
            return super().render(plan, output, token, progress, RenderSettings(160, 90, 24))

    monkeypatch.setattr(movie_dialog, "MovieRenderService", SmallRender)
    dialog.export()
    assert wait_until(app, lambda: dialog.thread is None)
    assert output.is_file(), dialog.status.text()
    assert dialog.output == output
    cached_after = [dict(row) for asset in library.list_assets() for row in repo.results_for_asset(asset.asset_id, "gemini", "test-model")]
    assert cached_before == cached_after
    dialog.reject()
    assert not dialog.isVisible()
    assert not preview_directory.exists()


def test_closing_movie_dialog_cancels_worker_without_destroying_live_thread(tmp_path):
    app = QApplication.instance() or QApplication([])
    day = date(2026, 7, 12)
    dialog = movie_dialog.MovieDialog(MediaLibrary(tmp_path / "library.sqlite3"), day, day, 60, "test-model")
    dialog.show()

    def operation(token, progress):
        token.wait(5)
        return "stopped"

    dialog.run_operation(operation, lambda result: None)
    dialog.close()
    assert dialog.isVisible()
    assert wait_until(app, lambda: dialog.thread is None)
    dialog.close()
    assert not dialog.isVisible()


def preview_dialog(tmp_path):
    day = date(2026, 7, 12)
    library = MediaLibrary(tmp_path / "library.sqlite3")
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"source")
    source = MovieSource("asset", str(source_path.resolve()), 6,
        datetime.fromtimestamp(source_path.stat().st_mtime).astimezone().isoformat(), 10, True, 96, 64)
    plan = MoviePlan("plan", "Familienfilm", 4, day.isoformat(), day.isoformat(), "gemini", "test-model", "test",
        [MovieEvent("event", "Ausflug", ("moment",))],
        [MovieSegment("moment", "event", source, 2, 6, "Familie lacht", ())])
    dialog = movie_dialog.MovieDialog(library, day, day, 4, "test-model")
    dialog.planned((plan, []))
    return dialog


def test_cancelled_movie_preview_can_retry_without_changing_plan_or_export(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    dialog = preview_dialog(tmp_path)
    dialog.show()
    before = deepcopy(dialog.plan)
    calls, played = [], []

    class ControlledRender:
        def __init__(self, *args):
            pass

        def render(self, plan, output, token, progress, settings):
            calls.append(settings)
            if len(calls) == 1:
                token.wait(5)
                raise movie_dialog.RenderCancelled("Vorschau abgebrochen.")
            output.write_bytes(b"preview")

    monkeypatch.setattr(movie_dialog, "MovieRenderService", ControlledRender)
    monkeypatch.setattr(dialog, "play_preview", lambda path: played.append(path))
    dialog.preview_movie()
    assert wait_until(app, lambda: len(calls) == 1)
    dialog.reject()
    assert dialog.isVisible()
    assert wait_until(app, lambda: dialog.thread is None)
    assert dialog.movie_preview_path is None and not played
    assert not list(Path(dialog.preview_directory.name).glob("*.mp4"))
    assert dialog.plan == before == load_movie(dialog.project_path)
    dialog.preview_movie()
    assert wait_until(app, lambda: dialog.thread is None)
    assert played == [dialog.movie_preview_path]
    assert dialog.movie_preview_plan == before
    assert dialog.output is None
    assert calls[-1] == RenderSettings(640, 360, 30, 28)
    directory = Path(dialog.preview_directory.name)
    dialog.reject()
    assert not directory.exists()


def test_empty_movie_preview_does_not_start_worker_or_create_cache(tmp_path):
    app = QApplication.instance() or QApplication([])
    dialog = preview_dialog(tmp_path)
    dialog.plan.segments[0].enabled = False
    dialog.preview_movie()
    assert dialog.thread is None
    assert dialog.preview_directory is None
    assert "keine aktiven Segmente" in dialog.status.text()
    dialog.reject()


def test_editing_template_save_undo_reopen_and_preview_invalidation(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    dialog = preview_dialog(tmp_path)
    before = deepcopy(dialog.plan)
    dialog.movie_preview_plan = deepcopy(before)
    preview_path = tmp_path / "old-preview.mp4"
    preview_path.write_bytes(b"preview")
    dialog.movie_preview_path = preview_path
    dialog.style_combo.setCurrentIndex(dialog.style_combo.findData("crossfade"))
    dialog.transition_duration.setValue(0.8)
    dialog.apply_style_button.click()
    assert dialog.plan.editing_style == EditingStyle("crossfade", 0.8)
    assert dialog.plan.segments == before.segments
    assert load_movie(dialog.project_path) == dialog.plan
    assert dialog.movie_preview_plan != dialog.plan
    dialog.undo_button.click()
    assert dialog.plan == before
    assert dialog.style_combo.currentData() == "cut"
    dialog.redo_button.click()
    assert dialog.style_combo.currentData() == "crossfade"
    assert dialog.transition_duration.value() == 0.8
    # Regeneration preserves the selected style without inspecting private media.
    monkeypatch.setattr(dialog.planner, "build", lambda *args, **kwargs: deepcopy(before))
    monkeypatch.setattr(dialog.planner, "candidates", lambda *args, **kwargs: ([], []))
    dialog.generate()
    assert wait_until(app, lambda: dialog.thread is None)
    assert dialog.plan.editing_style == EditingStyle("crossfade", 0.8)
    project = dialog.project_path
    monkeypatch.setattr(movie_dialog.QFileDialog, "getOpenFileName", lambda *args: (str(project), ""))
    dialog.open_project()
    assert dialog.style_combo.currentData() == "crossfade"
    assert dialog.plan.segments == before.segments
    dialog.reject()
