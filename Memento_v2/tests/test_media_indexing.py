from __future__ import annotations

import sqlite3
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from threading import Event, Timer

import pytest

from memento.application.indexing import MediaIndexService
from memento.domain.media import (
    IndexJobStatus,
    IndexItemStatus,
    AnalysisRecord,
    AnalysisStatus,
    CaptureTime,
    MediaAsset,
    Shot,
    TimestampSource,
)
from memento.library.database import MediaLibrary
from memento.media.discovery import VIDEO_EXTENSIONS, discover_videos
from memento.media.metadata import (
    MediaMetadata,
    MediaProbeError,
    MediaProbeCancelled,
    _probe_with_ffprobe,
    _run_command,
    probe_media,
)


def _metadata(capture=None):
    return MediaMetadata(
        duration_seconds=4.2,
        video_codec="h264",
        width=640,
        height=360,
        has_audio=True,
        capture_time=capture,
    )


def test_discovery_is_recursive_deduplicated_and_filters_extensions(tmp_path):
    root = tmp_path / "media"
    nested = root / "trip"
    nested.mkdir(parents=True)
    (root / "one.MP4").write_bytes(b"one")
    (nested / "two.webm").write_bytes(b"two")
    (nested / "notes.txt").write_text("ignore")

    result = discover_videos([root, nested])

    assert {item.path.name for item in result.files} == {"one.MP4", "two.webm"}
    assert len(result.files) == 2
    assert {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".mts", ".m2ts", ".webm"} == VIDEO_EXTENSIONS
    assert not result.issues


def test_discovery_reports_missing_root_without_aborting_other_roots(tmp_path):
    good = tmp_path / "good"
    good.mkdir()
    (good / "clip.mp4").write_bytes(b"video")

    result = discover_videos([tmp_path / "missing", good])

    assert [item.path.name for item in result.files] == ["clip.mp4"]
    assert len(result.issues) == 1


def test_schema_one_database_migrates_and_keeps_assets(tmp_path):
    db_path = tmp_path / "library.sqlite3"
    library = MediaLibrary(db_path)
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")
    library.save_asset(
        MediaAsset(
            asset_id="asset-1",
            path=media,
            size_bytes=5,
            modified_at=datetime.now(timezone.utc),
        )
    )
    library.save_shots("asset-1", [Shot("old-shot", "asset-1", 0.0, 1.0, {"sharpness": 0.8})])
    with sqlite3.connect(db_path) as db:
        db.execute("ALTER TABLE assets DROP COLUMN metadata_version")
        db.execute("DELETE FROM schema_migrations WHERE version=7")
        db.execute("DROP TABLE asset_aliases")
        db.execute("DROP INDEX idx_assets_content")
        db.execute("ALTER TABLE assets DROP COLUMN content_sha256")
        db.execute("DROP INDEX idx_locations_preferred")
        db.execute("ALTER TABLE locations DROP COLUMN available")
        db.execute("ALTER TABLE index_jobs DROP COLUMN verify_contents")
        db.execute("DELETE FROM schema_migrations WHERE version=6")
        db.execute("DROP TABLE local_feature_windows")
        db.execute("DELETE FROM schema_migrations WHERE version=5")
        db.execute("DROP TABLE semantic_cache")
        db.execute("DROP TABLE semantic_items")
        db.execute("DROP TABLE semantic_jobs")
        db.execute("DELETE FROM schema_migrations WHERE version=4")
        db.execute("DROP TABLE index_job_errors")
        db.execute("DROP TABLE index_job_items")
        db.execute("DROP TABLE index_jobs")
        db.execute("DROP TABLE media_analysis_job_errors")
        db.execute("DROP TABLE media_analysis_job_items")
        db.execute("DROP TABLE media_analysis_jobs")
        db.execute("ALTER TABLE shots DROP COLUMN thumbnail_path")
        db.execute("DELETE FROM schema_migrations WHERE version=2")
        db.execute("DELETE FROM schema_migrations WHERE version=3")
        db.execute("PRAGMA user_version=1")

    migrated = MediaLibrary(db_path)

    assert migrated.get_asset("asset-1") is not None
    assert migrated.list_shots("asset-1")[0].thumbnail_path is None
    job = migrated.create_index_job([tmp_path])
    assert migrated.get_index_job(job.job_id).status == IndexJobStatus.PENDING
    with sqlite3.connect(db_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 7


def test_capture_date_range_is_inclusive_sorted_and_excludes_unknown_dates(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    entries = [
        ("late", datetime.fromisoformat("2024-07-12T23:55:00-07:00")),
        ("early", datetime.fromisoformat("2024-07-12T01:00:00+12:00")),
        ("outside", datetime.fromisoformat("2024-07-13T00:00:00+00:00")),
        ("unknown", None),
    ]
    for name, capture_value in entries:
        media = tmp_path / f"{name}.mp4"
        media.write_bytes(name.encode())
        capture = (
            CaptureTime(capture_value, TimestampSource.CONTAINER, 0.8, capture_value.isoformat())
            if capture_value
            else None
        )
        library.save_asset(
            MediaAsset(
                name,
                media,
                media.stat().st_size,
                datetime.now(timezone.utc),
                capture_time=capture,
            )
        )

    result = library.list_assets_in_capture_date_range(date(2024, 7, 12), date(2024, 7, 12))

    assert [asset.asset_id for asset in result] == ["early", "late"]
    assert library.count_assets_without_capture_time() == 1
    with pytest.raises(ValueError, match="end date"):
        library.list_assets_in_capture_date_range(date(2024, 7, 13), date(2024, 7, 12))


def test_index_job_indexes_and_rescan_skips_unchanged_file(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    video = root / "clip.mp4"
    video.write_bytes(b"sample")
    library = MediaLibrary(tmp_path / "library.sqlite3")
    calls = []

    def probe(path, cancel_token=None):
        calls.append(path)
        return _metadata()

    service = MediaIndexService(library, probe)
    first = service.create_job([root])
    events = []

    assert service.run(first.job_id, events.append) == IndexJobStatus.COMPLETE
    asset = library.list_assets()[0]
    assert asset.duration_seconds == 4.2
    assert asset.capture_time.source == TimestampSource.FILESYSTEM
    assert len(calls) == 1
    assert events[-1].phase == "complete"
    assert {event.phase for event in events} >= {"discovering", "indexing", "complete"}

    second = service.create_job([root])
    assert service.run(second.job_id) == IndexJobStatus.COMPLETE
    assert len(calls) == 1
    assert library.index_job_counts(second.job_id)["skipped"] == 1


def test_file_failure_isolated_and_failed_item_can_resume(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "bad.mp4").write_bytes(b"bad")
    (root / "good.mp4").write_bytes(b"good")
    library = MediaLibrary(tmp_path / "library.sqlite3")
    fail = True

    def probe(path, cancel_token=None):
        if path.name == "bad.mp4" and fail:
            raise MediaProbeError("corrupt video")
        return _metadata()

    service = MediaIndexService(library, probe)
    job = service.create_job([root])

    assert service.run(job.job_id) == IndexJobStatus.COMPLETE_WITH_ERRORS
    assert {asset.path.name for asset in library.list_assets()} == {"good.mp4"}
    assert library.index_job_counts(job.job_id)["failed"] == 1

    fail = False
    assert service.run(job.job_id) == IndexJobStatus.COMPLETE
    assert {asset.path.name for asset in library.list_assets()} == {"bad.mp4", "good.mp4"}
    assert library.index_job_counts(job.job_id)["failed"] == 0


def test_changed_file_invalidates_stale_analysis_and_shots(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    video = root / "clip.mp4"
    video.write_bytes(b"first")
    original_stat = video.stat()
    library = MediaLibrary(tmp_path / "library.sqlite3")
    saved = library.save_asset(
        MediaAsset(
            asset_id="known-asset",
            path=video,
            size_bytes=original_stat.st_size,
            modified_at=datetime.fromtimestamp(original_stat.st_mtime).astimezone(),
            analysis_status=AnalysisStatus.COMPLETE,
            analysis_version="local-v1",
        )
    )
    library.save_shots(
        saved.asset_id,
        [Shot("shot-1", saved.asset_id, 0.0, 1.0, {"sharpness": 0.8})],
    )
    library.save_analysis_record(
        AnalysisRecord(
            asset_id=saved.asset_id,
            stage="local",
            version="local-v1",
            status=AnalysisStatus.COMPLETE,
        )
    )
    video.write_bytes(b"changed content")
    changed_time = original_stat.st_mtime + 3
    import os

    os.utime(video, (changed_time, changed_time))

    service = MediaIndexService(library, lambda path, cancel_token=None: _metadata())
    job = service.create_job([root])
    assert service.run(job.job_id) == IndexJobStatus.COMPLETE

    refreshed = library.get_asset(saved.asset_id)
    assert refreshed.analysis_status == AnalysisStatus.NOT_ANALYZED
    assert refreshed.analysis_version is None
    assert library.list_shots(saved.asset_id) == []
    assert library.list_index_job_errors(job.job_id) == []


def test_cancelled_probe_is_left_pending_and_resumable(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "clip.mp4").write_bytes(b"video")
    library = MediaLibrary(tmp_path / "library.sqlite3")
    cancel = Event()

    def probe(path, cancel_token=None):
        cancel.set()
        return _metadata()

    service = MediaIndexService(library, probe)
    job = service.create_job([root])
    database_path = library.path

    assert service.run(job.job_id, cancel_token=cancel) == IndexJobStatus.CANCELLED
    assert library.list_index_job_items(job.job_id, IndexItemStatus.PENDING)

    restarted_library = MediaLibrary(database_path)
    assert restarted_library.list_resumable_index_jobs()[0].job_id == job.job_id
    restarted_service = MediaIndexService(
        restarted_library, lambda path, cancel_token=None: _metadata()
    )
    assert restarted_service.run(job.job_id) == IndexJobStatus.COMPLETE
    assert len(restarted_library.list_assets()) == 1


def test_ffprobe_response_keeps_offset_and_capture_source(monkeypatch, tmp_path):
    class Result:
        returncode = 0
        stderr = ""
        stdout = (
            '{"format":{"duration":"2.5","tags":{"creation_time":'
            '"2025-03-01T12:30:00+02:00"}},"streams":[{"codec_type":"video",'
            '"codec_name":"h264","width":1280,"height":720}]}'
        )

    monkeypatch.setattr("memento.media.metadata._run_command", lambda *a, **kw: Result())
    metadata = _probe_with_ffprobe(tmp_path / "clip.mp4", "ffprobe", 5, None)

    assert metadata.duration_seconds == 2.5
    assert metadata.has_audio is False
    assert metadata.capture_time.source == TimestampSource.CONTAINER
    assert metadata.capture_time.value.utcoffset().total_seconds() == 7200


def test_container_time_without_timezone_is_marked_uncertain(tmp_path):
    from memento.media.metadata import _capture_time

    capture = _capture_time({"creation_time": "2024-11-03T01:30:00"}, tmp_path / "clip.mp4")

    assert capture is not None
    assert capture.source == TimestampSource.CONTAINER
    assert capture.value.tzinfo is None
    assert capture.confidence == 0.55


def test_ffprobe_failure_falls_back_to_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.setattr("memento.media.metadata.find_ffprobe", lambda: "ffprobe")
    monkeypatch.setattr(
        "memento.media.metadata._probe_with_ffprobe",
        lambda *a, **kw: (_ for _ in ()).throw(MediaProbeError("probe unavailable")),
    )
    expected = _metadata()
    monkeypatch.setattr("memento.media.metadata._probe_with_ffmpeg", lambda *a, **kw: expected)

    assert probe_media(tmp_path / "clip.mp4") == expected


def test_cancel_token_terminates_metadata_subprocess():
    cancel = Event()
    timer = Timer(0.15, cancel.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(MediaProbeCancelled):
            _run_command(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                timeout=5,
                cancel_token=cancel,
            )
    finally:
        timer.cancel()
    assert time.monotonic() - started < 3


def test_network_resolution_error_is_isolated_and_job_creation_stays_local(tmp_path, monkeypatch):
    offline = tmp_path / "network-share"
    good = tmp_path / "local"
    good.mkdir()
    (good / "clip.mp4").write_bytes(b"local-video")
    library = MediaLibrary(tmp_path / "library.sqlite3")
    resolve = Path.resolve

    def network_error(path, *args, **kwargs):
        if path == offline:
            raise OSError("network is unreachable")
        return resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", network_error)
    service = MediaIndexService(library, lambda path, cancel_token=None: _metadata())
    job = service.create_job([offline, good])
    assert service.run(job.job_id) == IndexJobStatus.COMPLETE_WITH_ERRORS
    assert library.count_assets() == 1
    errors = library.list_index_job_errors(job.job_id)
    assert len(errors) == 1 and errors[0]["path"] == str(offline)
    assert library.get_folder_stats(good).video_count == 1
    assert library.get_folder_stats(offline).video_count == 0
