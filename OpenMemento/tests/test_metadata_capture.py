from __future__ import annotations

import json
import subprocess
import sqlite3
from dataclasses import replace
from datetime import datetime

import imageio_ffmpeg
import pytest

from memento.ai.contracts import Moment, SemanticResult

from memento.application.indexing import MediaIndexService
from memento.domain.media import CaptureTime, IndexJobStatus, TimestampSource
from memento.library.database import MediaLibrary
from memento.library.semantic import SemanticRepository
from memento.media.metadata import (
    METADATA_VERSION, MediaMetadata, _capture_time, _parse_ffmetadata,
    _positive_float, _positive_int, _probe_with_ffmpeg, _probe_with_ffprobe,
    _run_command,
)


def test_invalid_preferred_time_does_not_hide_valid_container_or_stream_fallback(tmp_path):
    capture = _capture_time({"com.apple.quicktime.creationdate": "invalid", "creation_time": "bad"},
                            tmp_path / "clip.mov", {"creation_time": "2026-07-12T12:30:00Z"})
    assert capture.source == TimestampSource.CONTAINER
    assert capture.value == datetime.fromisoformat("2026-07-12T12:30:00+00:00")


@pytest.mark.parametrize("raw,offset,expected", [
    ("2026:07:12 14:30:15", "+02:00", "2026-07-12T14:30:15+02:00"),
    ("2026:07:12 14:30:15.123", "-0430", "2026-07-12T14:30:15.123-04:30"),
    ("2026:07:12 14:30:15", None, "2026-07-12T14:30:15"),
])
def test_exif_original_dates_keep_explicit_offset_and_unknown_timezone(raw, offset, expected, tmp_path):
    tags = {"EXIF:DateTimeOriginal": raw}
    if offset:
        tags["EXIF:OffsetTimeOriginal"] = offset
    capture = _capture_time(tags, tmp_path / "clip.mov")
    assert capture.source == TimestampSource.EXIF
    assert capture.value == datetime.fromisoformat(expected)
    assert capture.raw_value == raw
    assert capture.confidence == (0.85 if offset else 0.6)


def test_date_only_has_lower_confidence_and_quicktime_wins_over_generic_tags(tmp_path):
    capture = _capture_time({"creation_time": "2026-07-12"}, tmp_path / "clip.mp4")
    assert capture.confidence == 0.35
    capture = _capture_time({"creation_time": "2026-01-01T00:00:00Z"}, tmp_path / "clip.mov",
                            {"com.apple.quicktime.creationdate": "2026-07-12T15:00:00+0300"})
    assert capture.source == TimestampSource.QUICKTIME
    assert capture.value.utcoffset().total_seconds() == 10800


def test_ffmetadata_escaping_and_chapter_isolation():
    tags = _parse_ffmetadata(";FFMETADATA1\ncomment=private\\;text\\=value\\\\end\ncreation_time=2026-07-12T12:00:00Z\n"
                             "continued=first\\\nsecond\n[CHAPTER]\ncreation_time=2027-01-01\n")
    assert tags["comment"] == "private;text=value\\end"
    assert tags["continued"] == "first\nsecond"
    assert tags["creation_time"] == "2026-07-12T12:00:00Z"


def test_ffprobe_ignores_cover_image_and_uses_actual_video_tags(monkeypatch, tmp_path):
    payload = {"format": {"duration": "5", "tags": {"creation_time": "2026-01-01T00:00:00Z"}}, "streams": [
        {"codec_type": "video", "codec_name": "mjpeg", "width": 300, "disposition": {"attached_pic": 1}},
        {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080,
         "tags": {"creation_time": "2026-07-12T10:00:00Z"}},
    ]}
    monkeypatch.setattr("memento.media.metadata._run_command", lambda *args, **kwargs: subprocess.CompletedProcess([], 0, json.dumps(payload), ""))
    metadata = _probe_with_ffprobe(tmp_path / "clip.mp4", "ffprobe", 5, None)
    assert metadata.video_codec == "h264" and metadata.width == 1920
    assert metadata.capture_time.value.month == 7


def test_real_mov_ffmpeg_fallback_retains_quicktime_date_and_original(tmp_path):
    video = tmp_path / "phone.mov"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    result = _run_command([ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=96x64:r=12:d=1",
        "-c:v", "libx264", "-metadata", "creation_time=2026-07-12T12:30:00Z",
        "-metadata", "com.apple.quicktime.creationdate=2026-07-12T14:30:00+0200", "-movflags", "use_metadata_tags", str(video)], 15, None)
    assert result.returncode == 0
    original = video.read_bytes()
    actual = _probe_with_ffmpeg(video, 15, None)
    assert actual.capture_time is not None
    assert actual.capture_time.source == TimestampSource.QUICKTIME
    assert actual.capture_time.value == datetime.fromisoformat("2026-07-12T14:30:00+02:00")
    assert actual.duration_seconds == pytest.approx(1, abs=0.1)
    assert video.read_bytes() == original


def test_metadata_version_refresh_keeps_verified_hash_without_rereading_content(tmp_path, monkeypatch):
    root = tmp_path / "media"
    root.mkdir()
    source = root / "clip.mp4"
    source.write_bytes(b"video")
    library = MediaLibrary(tmp_path / "library.sqlite3")
    calls = []
    plain = MediaMetadata(6, "h264", 96, 64, False, None)
    service = MediaIndexService(library, lambda *args, **kwargs: plain)
    assert service.run(service.create_job([root]).job_id) == IndexJobStatus.COMPLETE
    asset = library.get_asset_for_path(source)
    repository = SemanticRepository(library)
    job = repository.create_job([asset], "gemini", "test-model")
    moment = Moment(0, 6, "Testmoment", "Testereignis", (), (), 0.8, 0.8, 0.8, 1, 1, ())
    repository.save_result(repository.get_job(job), repository.items(job)[0], SemanticResult((moment,)))
    cache_key = repository.items(job)[0]["cache_key"]
    library.save_asset(replace(asset, metadata_version="old-metadata"))
    monkeypatch.setattr("memento.application.indexing.hash_media", lambda *args, **kwargs: pytest.fail("An unchanged verified source must not be rehashed just to refresh metadata"))

    def better_probe(*args, **kwargs):
        calls.append(1)
        return replace(plain, capture_time=CaptureTime(datetime(2026, 7, 12, 10), TimestampSource.QUICKTIME, 0.9))

    service = MediaIndexService(library, better_probe)
    assert service.run(service.create_job([root]).job_id) == IndexJobStatus.COMPLETE
    current = library.get_asset_for_path(source)
    assert current.content_sha256 == asset.content_sha256
    assert current.metadata_version == METADATA_VERSION
    assert current.capture_time.source == TimestampSource.QUICKTIME
    assert repository.estimate(job)["pending"] == 0
    assert repository.results_for_asset(current.asset_id, "gemini", "test-model")[0]["cache_key"] == cache_key
    assert service.run(service.create_job([root]).job_id) == IndexJobStatus.COMPLETE
    assert len(calls) == 1


def test_nonfinite_technical_values_rejected():
    assert _positive_float("Infinity") is None
    assert _positive_float("NaN") is None
    assert _positive_int(float("inf")) is None


def test_invalid_exif_offset_keeps_uncertain_original_wall_time(tmp_path):
    capture = _capture_time({"DateTimeOriginal": "2026:07:12 14:30:00", "OffsetTimeOriginal": "+99:99"}, tmp_path / "clip.mov")
    assert capture.value == datetime(2026, 7, 12, 14, 30)
    assert capture.value.tzinfo is None
    assert capture.confidence == 0.6


def test_schema_six_metadata_upgrade_preserves_source_identity(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    source = root / "clip.mp4"
    source.write_bytes(b"video")
    library = MediaLibrary(tmp_path / "library.sqlite3")
    service = MediaIndexService(library, lambda *args, **kwargs: MediaMetadata(6, "h264", 96, 64, False, None))
    assert service.run(service.create_job([root]).job_id) == IndexJobStatus.COMPLETE
    asset = library.get_asset_for_path(source)
    with sqlite3.connect(library.path) as db:
        db.execute("ALTER TABLE assets DROP COLUMN metadata_version")
        db.execute("DELETE FROM schema_migrations WHERE version=7")
        db.execute("PRAGMA user_version=6")
    migrated = MediaLibrary(library.path)
    current = migrated.get_asset(asset.asset_id)
    assert current.content_sha256 == asset.content_sha256
    assert current.metadata_version is None
    backups = list((tmp_path / "backups").glob("*-schema-6-*.sqlite3"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 6
