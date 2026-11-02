from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QApplication

from memento.application.indexing import MediaIndexService
from memento.application.shot_analysis import ShotAnalysisService
from memento.domain.media import (
    CaptureTime,
    IndexJobStatus,
    IndexItemStatus,
    MediaAnalysisJobStatus,
    MediaAnalysisProgress,
    MediaAsset,
    TimestampSource,
)
from memento.library.database import MediaLibrary
from memento.media.metadata import MediaMetadata
from memento.ui.main_window import MainWindow


def _application():
    return QApplication.instance() or QApplication([])


def _settings_for_test():
    app = QApplication.instance()
    app.setOrganizationName("MementoUITests")
    app.setApplicationName(f"case-{uuid4()}")
    settings = QSettings()
    settings.clear()
    return settings


def _metadata():
    return MediaMetadata(3.0, "h264", 320, 180, False, None)


def _wait_for(app, predicate, timeout_ms=5000):
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: loop.quit() if predicate() else None)
    timer.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    timer.stop()
    app.processEvents()
    return predicate()


def test_window_shows_database_folder_stats_and_resumable_jobs(tmp_path):
    app = _application()
    settings = _settings_for_test()
    root = tmp_path / "family"
    root.mkdir()
    settings.setValue("library/folders", [str(root)])
    library = MediaLibrary(tmp_path / "library.sqlite3")
    path = root / "clip.mp4"
    path.write_bytes(b"video")
    library.save_asset(
        MediaAsset(
            "asset-ui",
            path,
            path.stat().st_size,
            datetime.now(timezone.utc),
            capture_time=CaptureTime(
                datetime(2025, 5, 1, tzinfo=timezone.utc),
                TimestampSource.QUICKTIME,
                0.9,
            ),
        )
    )
    job = library.create_index_job([root])
    library.set_index_job_status(job.job_id, IndexJobStatus.COMPLETE_WITH_ERRORS)
    library.add_index_job_error(job.job_id, str(path), "metadata", "test error")

    window = MainWindow(library, MediaIndexService(library))

    assert _wait_for(app, lambda: str(root) in window._folder_availability)
    assert window.video_stat.text() == "1"
    assert window.library_table.rowCount() == 1
    assert window.library_table.item(0, 1).text() == "Indexiert"
    assert window.library_table.item(0, 2).text() == "1"
    assert window.library_table.item(0, 3).text() == "01.05.2025"
    assert window.job_selector.currentData() == job.job_id
    assert window.resume_button.isEnabled()
    assert window.errors_button.isEnabled()
    assert window.library_stat.text() == "1"
    window.close()
    app.processEvents()


def test_date_range_controls_query_and_report_timestamp_uncertainty(tmp_path):
    app = _application()
    root = tmp_path / "family"
    root.mkdir()
    path = root / "clip.mp4"
    path.write_bytes(b"video")
    library = MediaLibrary(tmp_path / "library.sqlite3")
    library.save_asset(
        MediaAsset(
            "range-ui",
            path,
            path.stat().st_size,
            datetime.now(timezone.utc),
            capture_time=CaptureTime(
                datetime(2025, 5, 1, 10, 30), TimestampSource.CONTAINER, 0.55, "2025-05-01T10:30:00"
            ),
        )
    )
    _settings_for_test()
    window = MainWindow(library, MediaIndexService(library))
    window.date_from.setDate(QDate(2025, 5, 1))
    window.date_to.setDate(QDate(2025, 5, 1))
    shown = []
    window._show_range_results = lambda page, start, end: shown.append(
        (page.assets, start, end, page.unknown)
    )

    window.find_range_button.click()

    assert len(shown) == 1
    assert [asset.asset_id for asset in shown[0][0]] == ["range-ui"]
    assert shown[0][1:] == (datetime(2025, 5, 1).date(), datetime(2025, 5, 1).date(), 0)
    assert "1 Aufnahmen im Zeitraum" in window.range_summary.text()
    window.close()
    app.processEvents()


def test_analysis_action_runs_in_worker_and_refreshes_resumable_jobs(tmp_path):
    app = _application()
    _settings_for_test()
    library = MediaLibrary(tmp_path / "library.sqlite3")
    path = tmp_path / "already-indexed.mp4"
    path.write_bytes(b"indexed")
    library.save_asset(
        MediaAsset("analysis-ui", path, path.stat().st_size, datetime.now(timezone.utc))
    )

    class FinishedService:
        def __init__(self):
            self.repository_service = ShotAnalysisService(library, tmp_path / "cache")
            self.job = None

        def create_job(self):
            self.job = self.repository_service.create_job()
            return self.job

        def run(self, job_id, cancel_token, on_progress):
            library.set_media_analysis_job_status(job_id, MediaAnalysisJobStatus.RUNNING)
            library.set_media_analysis_job_item(job_id, "analysis-ui", IndexItemStatus.COMPLETE)
            library.set_media_analysis_job_status(job_id, MediaAnalysisJobStatus.COMPLETE)
            on_progress(MediaAnalysisProgress(job_id, 1, 1, 0, 0, path))
            return MediaAnalysisJobStatus.COMPLETE

    fake_service = FinishedService()
    window = MainWindow(library, MediaIndexService(library), analysis_service=fake_service)

    window.analyze_button.click()

    assert _wait_for(app, lambda: window._thread is None)
    assert fake_service.job is not None
    assert library.get_media_analysis_job(fake_service.job.job_id).status == MediaAnalysisJobStatus.COMPLETE
    assert "Shotanalyse abgeschlossen" in window.index_status_label.text()
    assert window.analyze_button.isEnabled()
    window.close()
    app.processEvents()


def test_index_worker_keeps_ui_responsive_and_reports_progress(tmp_path):
    app = _application()
    settings = _settings_for_test()
    root = tmp_path / "family"
    root.mkdir()
    (root / "clip.mp4").write_bytes(b"video")
    settings.setValue("library/folders", [str(root)])
    library = MediaLibrary(tmp_path / "library.sqlite3")
    entered_probe = Event()
    release_probe = Event()

    def slow_probe(path, cancel_token=None):
        entered_probe.set()
        release_probe.wait(2)
        return _metadata()

    window = MainWindow(library, MediaIndexService(library, slow_probe))
    ui_timer_fired = Event()
    QTimer.singleShot(25, ui_timer_fired.set)

    window.start_indexing()

    assert _wait_for(app, lambda: entered_probe.is_set() and ui_timer_fired.is_set())
    try:
        assert window.cancel_button.isEnabled()
    finally:
        release_probe.set()
    assert _wait_for(app, lambda: window._thread is None)
    assert window.video_stat.text() == "1"
    assert "abgeschlossen" in window.index_status_label.text().lower()
    window.close()
    app.processEvents()


def test_cancelled_job_is_offered_after_window_restart_and_can_resume(tmp_path):
    app = _application()
    settings = _settings_for_test()
    root = tmp_path / "family"
    root.mkdir()
    (root / "clip.mp4").write_bytes(b"video")
    settings.setValue("library/folders", [str(root)])
    library = MediaLibrary(tmp_path / "library.sqlite3")
    entered_probe = Event()

    def waiting_probe(path, cancel_token=None):
        entered_probe.set()
        cancel_token.wait(2)
        return _metadata()

    first_window = MainWindow(library, MediaIndexService(library, waiting_probe))
    first_window.start_indexing()
    assert entered_probe.wait(2)
    QTimer.singleShot(20, first_window.cancel_indexing)
    assert _wait_for(app, lambda: first_window._thread is None)
    job_id = library.list_resumable_index_jobs()[0].job_id
    first_window.close()

    second_window = MainWindow(
        library,
        MediaIndexService(library, lambda path, cancel_token=None: _metadata()),
    )
    assert second_window.job_selector.currentData() == job_id
    second_window.resume_selected_job()

    assert _wait_for(app, lambda: second_window._thread is None)
    assert len(library.list_assets()) == 1
    assert "abgeschlossen" in second_window.index_status_label.text().lower()
    second_window.close()
    app.processEvents()


def test_closing_window_cancels_worker_before_destroying_thread(tmp_path):
    app = _application()
    settings = _settings_for_test()
    root = tmp_path / "family"
    root.mkdir()
    (root / "clip.mp4").write_bytes(b"video")
    settings.setValue("library/folders", [str(root)])
    library = MediaLibrary(tmp_path / "library.sqlite3")
    entered_probe = Event()

    def waiting_probe(path, cancel_token=None):
        entered_probe.set()
        cancel_token.wait(2)
        return _metadata()

    window = MainWindow(library, MediaIndexService(library, waiting_probe))
    window.show()
    window.start_indexing()
    assert _wait_for(app, entered_probe.is_set)

    closed_immediately = window.close()

    assert not closed_immediately
    assert _wait_for(app, lambda: window._thread is None and not window.isVisible())
    assert library.list_resumable_index_jobs()[0].status == IndexJobStatus.CANCELLED


def test_offline_start_preserves_cached_material_and_recovers_without_restart(tmp_path, monkeypatch):
    app = _application()
    settings = _settings_for_test()
    root = tmp_path / "network-share"
    root.mkdir()
    source = root / "family.mp4"
    source.write_bytes(b"original")
    library = MediaLibrary(tmp_path / "library.sqlite3")
    library.save_asset(MediaAsset("offline", source, 8, datetime.now(timezone.utc),
        capture_time=CaptureTime(datetime(2025, 5, 1), TimestampSource.QUICKTIME, 0.9)))
    settings.setValue("library/folders", [str(root)])
    source.unlink()
    root.rmdir()
    original_resolve = Path.resolve

    def no_network_resolution(path, *args, **kwargs):
        if path == root:
            raise OSError("network is unreachable")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", no_network_resolution)
    window = MainWindow(library)
    window.show()
    assert window.isVisible()
    assert _wait_for(app, lambda: str(root) in window._folder_availability)
    assert window.library_table.item(0, 1).text() == "Derzeit nicht zugreifbar"
    assert window.library_table.item(0, 1).toolTip()
    assert window.library_table.item(0, 2).text() == "1"
    assert window.library_table.item(0, 3).text() == "01.05.2025"
    assert settings.value("library/folders", [], type=list) == [str(root)]
    assert library.count_assets() == 1
    # The same window must recover when the mount becomes available again.
    root.mkdir()
    window.check_folders_button.click()
    assert _wait_for(app, lambda: window.library_table.item(0, 1).text() == "Indexiert")
    window.close()
    app.processEvents()


def test_hanging_network_probe_times_out_while_ui_remains_responsive(tmp_path, monkeypatch):
    from PySide6.QtCore import QProcess
    from memento.ui.folder_availability import FolderAvailabilityChecker

    app = _application()
    settings = _settings_for_test()
    settings.setValue("library/folders", [str(tmp_path / "offline")])
    start = QProcess.start

    def hanging_start(process, program, arguments):
        start(process, program, ["-c", "import time; time.sleep(30)"])

    monkeypatch.setattr(QProcess, "start", hanging_start)
    monkeypatch.setattr(FolderAvailabilityChecker, "TIMEOUT_MS", 100)
    window = MainWindow(MediaLibrary(tmp_path / "library.sqlite3"))
    window.show()
    heartbeat = []
    QTimer.singleShot(10, lambda: heartbeat.append(True))
    assert _wait_for(app, lambda: window.library_table.item(0, 1).text() == "Derzeit nicht zugreifbar")
    assert heartbeat and window.isVisible()
    assert "Zeitüberschreitung" in window.library_table.item(0, 1).toolTip()
    assert _wait_for(app, lambda: all(process.state() == QProcess.ProcessState.NotRunning
                                   for process in window.findChildren(QProcess)))
    window.close()
    app.processEvents()
