from __future__ import annotations

import os
from dataclasses import replace
from datetime import date, datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import QApplication, QMessageBox

from memento.ai.contracts import Moment, SemanticResult
from memento.application.movie_planning import MoviePlanningService
from memento.application.indexing import MediaIndexService
from memento.domain.media import CaptureTime, MediaAsset, TimestampSource
from memento.library.database import MediaLibrary
from memento.library.movies import load_movie, save_movie
from memento.library.semantic import SemanticRepository
from memento.media.metadata import MediaMetadata
from memento.ui.capture_time_dialog import CaptureTimeDialog, parse_offset


def add_asset(library, root, name="holiday", capture=None):
    source = root / (name + ".mp4")
    source.write_bytes(b"unchanged source")
    return library.save_asset(MediaAsset(name, source, source.stat().st_size,
        datetime.fromtimestamp(source.stat().st_mtime).astimezone(), capture_time=capture, duration_seconds=10))


def test_manual_date_moves_cached_highlights_without_changing_media_or_saved_plan(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    capture = CaptureTime(datetime(2026, 7, 12, 10), TimestampSource.FILESYSTEM, 0.2, "original raw date")
    asset = add_asset(library, tmp_path, capture=capture)
    repo = SemanticRepository(library)
    job = repo.create_job([asset], "gemini", "test-model")
    moment = Moment(1, 8, "Lachen", "Gemeinsames Spielen", (), (), 0.9, 0.9, 0.8, 0.8, 0.9, ("Reaktion",))
    repo.save_result(repo.get_job(job), repo.items(job)[0], SemanticResult((moment,), 100, 10))
    service = MoviePlanningService(repo)
    original = service.build(date(2026, 7, 12), date(2026, 7, 12), 7, "gemini", "test-model")
    project = tmp_path / "movie.memento.json"
    save_movie(project, original)
    before = asset.path.stat()
    cached_before = [dict(row) for row in repo.results_for_asset(asset.asset_id, "gemini", "test-model")]
    corrected = datetime.fromisoformat("2026-08-03T00:10:00+14:00")
    library.set_manual_capture_time(asset.asset_id, corrected)
    refreshed = library.get_asset(asset.asset_id)
    assert refreshed.capture_time == CaptureTime(corrected, TimestampSource.MANUAL, 1.0, "original raw date")
    assert library.list_assets_in_capture_date_range(date(2026, 7, 12), date(2026, 7, 12)) == []
    candidates, _ = service.candidates(date(2026, 8, 3), date(2026, 8, 3), "gemini", "test-model")
    assert candidates[0].recorded_at == corrected + timedelta(seconds=1)
    assert candidates[0].candidate_id == original.segments[0].candidate_id
    assert repo.estimate(repo.create_job([refreshed], "gemini", "test-model"))["pending"] == 0
    assert [dict(row) for row in repo.results_for_asset(asset.asset_id, "gemini", "test-model")] == cached_before
    assert load_movie(project) == original
    assert asset.path.read_bytes() == b"unchanged source"
    assert asset.path.stat().st_mtime_ns == before.st_mtime_ns
    # Even legacy metadata refresh must retain the user's correction.
    library.save_asset(replace(asset, capture_time=capture))
    assert library.get_asset(asset.asset_id).capture_time.value == corrected


def test_capture_review_pages_missing_uncertain_and_literal_path_search(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    dated = CaptureTime(datetime(2026, 7, 12), TimestampSource.QUICKTIME, 0.9)
    missing = add_asset(library, tmp_path, "missing_%")
    uncertain = add_asset(library, tmp_path, "uncertain", replace(dated, confidence=0.2))
    add_asset(library, tmp_path, "known", dated)
    rows, total = library.review_capture_times(mode="missing")
    assert total == 1 and rows[0].asset_id == missing.asset_id
    assert library.review_capture_times(mode="uncertain")[1] == 2
    assert library.review_capture_times(search="_%")[1] == 1
    assert library.review_capture_times(search="KNOWN")[1] == 1
    first, total = library.review_capture_times(limit=2)
    second, _ = library.review_capture_times(limit=2, offset=2)
    assert total == 3 and len(second) == 1
    assert {item.asset_id for item in first}.isdisjoint(item.asset_id for item in second)
    library.set_manual_capture_time(missing.asset_id, datetime(2026, 8, 3))
    assert library.count_assets_without_capture_time() == 0
    assert library.review_capture_times(mode="uncertain")[1] == 1
    with library._connection() as db:
        db.execute("INSERT INTO asset_aliases VALUES (?, ?)", ("old-id", uncertain.asset_id))
    library.set_manual_capture_time("old-id", datetime(2026, 8, 4))
    assert library.get_asset(uncertain.asset_id).capture_time.source == TimestampSource.MANUAL
    with pytest.raises(KeyError):
        library.set_manual_capture_time("absent", datetime(2026, 1, 1))
    with pytest.raises(ValueError):
        library.set_manual_capture_time(missing.asset_id, date(2026, 1, 1))


def test_corrected_date_survives_verified_rescan_and_duplicate_import(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    source = root / "Sommerüberraschung.mp4"
    source.write_bytes(b"same source bytes")
    library = MediaLibrary(tmp_path / "library.sqlite3")
    capture = CaptureTime(datetime(2026, 7, 12), TimestampSource.QUICKTIME, 0.9)
    def probe(path, cancel_token=None):
        return MediaMetadata(10, "h264", 96, 64, False, capture)
    index = MediaIndexService(library, probe)
    index.run(index.create_job([root]).job_id)
    asset = library.get_asset_for_path(source)
    corrected = datetime.fromisoformat("2026-08-03T10:00:00+02:00")
    library.set_manual_capture_time(asset.asset_id, corrected)
    (root / "copy.mp4").write_bytes(source.read_bytes())
    index.run(index.create_job([root], verify_contents=True).job_id)
    assert library.count_assets() == 1
    assert library.get_asset_for_path(root / "copy.mp4").capture_time.value == corrected
    assert library.get_asset_for_path(source).capture_time.source == TimestampSource.MANUAL
    assert library.review_capture_times(search="SOMMERÜBERRASCHUNG")[1] == 1


@pytest.mark.parametrize("text,seconds", [("", None), ("UTC", 0), ("+14:00", 50400),
    ("-03:30", -12600), ("+05:30:12", 19812)])
def test_explicit_offsets_never_invent_workstation_timezone(text, seconds):
    parsed = parse_offset(text)
    assert (parsed.utcoffset(None).total_seconds() if parsed else None) == seconds


@pytest.mark.parametrize("text", ["Berlin", "+24:00", "+02:60", "02:00", "+2:00", "+01:00:60"])
def test_invalid_offsets_are_rejected(text):
    with pytest.raises(ValueError):
        parse_offset(text)


def test_dialog_corrects_missing_date_and_rejects_invalid_zone(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    library = MediaLibrary(tmp_path / "library.sqlite3")
    asset = add_asset(library, tmp_path)
    dialog = CaptureTimeDialog(library)
    dialog.show()
    assert not dialog.save_button.isEnabled()
    dialog.mode.setCurrentIndex(2)
    dialog.table.selectRow(0)
    dialog.day.setDate(QDate(2026, 8, 3))
    dialog.clock.setTime(QTime(9, 8, 7))
    dialog.zone.setText("+25:00")
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args))
    dialog.save_button.click()
    assert errors and library.get_asset(asset.asset_id).capture_time is None
    dialog.zone.setText("+02:00")
    dialog.save_button.click()
    capture = library.get_asset(asset.asset_id).capture_time
    assert capture.value.isoformat() == "2026-08-03T09:08:07+02:00"
    assert capture.source == TimestampSource.MANUAL and dialog.changed
    assert dialog.table.rowCount() == 0  # No longer matches the missing-date filter.
    dialog.accept()
    app.processEvents()
