from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Event

import cv2
import numpy as np
import pytest

from memento.application.shot_analysis import SHOT_ANALYSIS_VERSION, ShotAnalysisService
from memento.domain.media import AnalysisStatus, MediaAnalysisJobStatus, MediaAsset
from memento.library.database import MediaLibrary
from memento.ai.contracts import Moment, SemanticResult
from memento.library.semantic import SemanticRepository


def _write_scene_video(path: Path, scenes: int = 3) -> bool:
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (96, 64)
    )
    if not writer.isOpened():
        return False
    colors = ((0, 0, 255), (255, 0, 0), (0, 255, 0), (255, 255, 0))
    for color in colors[:scenes]:
        for _ in range(10):
            writer.write(np.full((64, 96, 3), color, dtype=np.uint8))
    writer.release()
    return True


def _add_asset(library: MediaLibrary, path: Path, asset_id: str):
    capture = cv2.VideoCapture(str(path))
    fps = capture.get(cv2.CAP_PROP_FPS)
    duration = capture.get(cv2.CAP_PROP_FRAME_COUNT) / fps if fps > 0 else None
    capture.release()
    return library.save_asset(
        MediaAsset(
            asset_id=asset_id,
            path=path,
            size_bytes=path.stat().st_size,
            modified_at=datetime.fromtimestamp(path.stat().st_mtime).astimezone(),
            duration_seconds=duration,
            video_codec="mjpeg",
            width=96,
            height=64,
        )
    )


def test_shot_analysis_persists_boundaries_and_local_thumbnails(tmp_path):
    path = tmp_path / "scenes.avi"
    if not _write_scene_video(path):
        pytest.skip("OpenCV build does not provide an MJPG encoder")
    library = MediaLibrary(tmp_path / "library.sqlite3")
    _add_asset(library, path, "asset-scenes")
    service = ShotAnalysisService(library, tmp_path / "cache")
    job = service.create_job()

    assert service.run(job.job_id) == MediaAnalysisJobStatus.COMPLETE
    shots = library.list_shots("asset-scenes")

    assert len(shots) >= 3
    assert shots[0].start_seconds == 0
    assert shots[-1].end_seconds <= 3.0
    assert all(left.end_seconds <= right.start_seconds for left, right in zip(shots, shots[1:]))
    for shot in shots:
        thumbnail = tmp_path / "cache" / shot.thumbnail_path
        image = cv2.imread(str(thumbnail))
        assert thumbnail.is_file()
        assert max(image.shape[:2]) <= 320
    indexed = library.get_asset("asset-scenes")
    assert indexed.analysis_status == AnalysisStatus.COMPLETE
    assert indexed.analysis_version == SHOT_ANALYSIS_VERSION


def test_analysis_job_resumes_remaining_assets_without_reprocessing_completed(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    for asset_id in ("asset-a", "asset-b"):
        path = tmp_path / f"{asset_id}.avi"
        if not _write_scene_video(path, scenes=2):
            pytest.skip("OpenCV build does not provide an MJPG encoder")
        _add_asset(library, path, asset_id)
    service = ShotAnalysisService(library, tmp_path / "cache")
    job = service.create_job()
    cancel = Event()
    processed = []

    def stop_after_first(progress):
        if progress.completed == 1:
            processed.append(progress.current_path)
            cancel.set()

    assert service.run(job.job_id, cancel, stop_after_first) == MediaAnalysisJobStatus.CANCELLED
    cancel.clear()
    calls = []
    original = service._analyze_asset

    def track(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)

    service._analyze_asset = track
    assert service.run(job.job_id, cancel) == MediaAnalysisJobStatus.COMPLETE
    assert len(processed) == 1
    assert len(calls) == 1
    assert all(library.get_asset(asset_id).analysis_status == AnalysisStatus.COMPLETE for asset_id in ("asset-a", "asset-b"))


def test_analysis_version_skips_current_assets_and_replaces_old_thumbnail_generation(tmp_path):
    path = tmp_path / "scenes.avi"
    if not _write_scene_video(path):
        pytest.skip("OpenCV build does not provide an MJPG encoder")
    library = MediaLibrary(tmp_path / "library.sqlite3")
    _add_asset(library, path, "asset-version")
    cache = tmp_path / "cache"
    service = ShotAnalysisService(library, cache, "profile-1")
    first_job = service.create_job()
    assert service.run(first_job.job_id) == MediaAnalysisJobStatus.COMPLETE
    first_shots = library.list_shots("asset-version")
    old_generation = Path(first_shots[0].thumbnail_path).parts[2]

    same_profile_job = service.create_job()
    assert service.run(same_profile_job.job_id) == MediaAnalysisJobStatus.COMPLETE
    assert library.media_analysis_job_counts(same_profile_job.job_id)["skipped"] == 1

    updated_service = ShotAnalysisService(library, cache, "profile-2")
    assert updated_service.run(first_job.job_id) == MediaAnalysisJobStatus.COMPLETE
    assert library.get_media_analysis_job(first_job.job_id).analysis_version == "profile-2"
    updated_shots = library.list_shots("asset-version")
    new_generation = Path(updated_shots[0].thumbnail_path).parts[2]
    assert new_generation != old_generation
    assert not (cache / "thumbnails" / "asset-version" / old_generation).exists()
    assert all((cache / shot.thumbnail_path).is_file() for shot in updated_shots)


def test_corrupt_video_isolated_and_reported_per_asset(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    corrupt = tmp_path / "corrupt.avi"
    corrupt.write_bytes(b"not a video")
    _add_asset(library, corrupt, "asset-bad")
    valid = tmp_path / "valid.avi"
    if not _write_scene_video(valid, scenes=2):
        pytest.skip("OpenCV build does not provide an MJPG encoder")
    _add_asset(library, valid, "asset-good")
    service = ShotAnalysisService(library, tmp_path / "cache")
    job = service.create_job()

    assert service.run(job.job_id) == MediaAnalysisJobStatus.COMPLETE_WITH_ERRORS
    assert library.get_asset("asset-bad").analysis_status == AnalysisStatus.FAILED
    assert library.get_asset("asset-good").analysis_status == AnalysisStatus.COMPLETE
    errors = library.list_media_analysis_job_errors(job.job_id)
    assert len(errors) == 1
    assert Path(errors[0]["path"]) == corrupt


def test_missing_restored_thumbnail_cache_can_be_regenerated(tmp_path):
    path = tmp_path / "scenes.avi"
    assert _write_scene_video(path)
    library = MediaLibrary(tmp_path / "library.sqlite3")
    _add_asset(library, path, "asset")
    service = ShotAnalysisService(library, tmp_path / "cache")
    assert service.run(service.create_job().job_id) == MediaAnalysisJobStatus.COMPLETE
    old = library.list_shots("asset")
    (service.cache_root / old[0].thumbnail_path).unlink()
    job = service.create_job()
    assert service.run(job.job_id) == MediaAnalysisJobStatus.COMPLETE
    assert library.media_analysis_job_counts(job.job_id)["skipped"] == 0
    assert all((service.cache_root / shot.thumbnail_path).is_file() for shot in library.list_shots("asset"))


@pytest.mark.parametrize("failure", ["read_failed", "missing_frame"])
def test_early_decode_failure_isolated_and_resumable_without_losing_paid_analysis(tmp_path, monkeypatch, failure):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    for name in ("bad", "good"):
        source = tmp_path / f"{name}.avi"
        assert _write_scene_video(source)
        _add_asset(library, source, name)
    repo = SemanticRepository(library)
    asset = library.get_asset("bad")
    semantic_job = repo.create_job([asset], "gemini", "test-model")
    repo.save_result(repo.get_job(semantic_job), repo.items(semantic_job)[0], SemanticResult((
        Moment(0, 3, "Familie spielt", "Familienausflug", (), (), 0.9, 0.9, 0.8, 0.8, 0.9, ()),)))
    cache_before = [dict(row) for row in repo.results_for_asset("bad", "gemini", "test-model")]
    original_bytes = asset.path.read_bytes()
    real_capture = cv2.VideoCapture
    released = []

    class FailingCapture:
        def __init__(self, path):
            self.capture = real_capture(path)
            self.position = 0

        def isOpened(self):
            return self.capture.isOpened()

        def set(self, key, value):
            if key == cv2.CAP_PROP_POS_MSEC:
                self.position = value
            return self.capture.set(key, value)

        def get(self, key):
            return self.capture.get(key)

        def read(self):
            if self.position >= 1000:
                return failure == "missing_frame", None
            return self.capture.read()

        def release(self):
            released.append(True)
            self.capture.release()

    monkeypatch.setattr(cv2, "VideoCapture", lambda path: FailingCapture(path) if Path(path).stem == "bad" else real_capture(path))
    service = ShotAnalysisService(library, tmp_path / "cache")
    job = service.create_job()
    assert service.run(job.job_id) == MediaAnalysisJobStatus.COMPLETE_WITH_ERRORS
    assert released
    assert library.get_asset("bad").analysis_status == AnalysisStatus.FAILED
    assert library.list_shots("bad") == []
    assert library.get_asset("good").analysis_status == AnalysisStatus.COMPLETE
    good_shots = library.list_shots("good")
    errors = library.list_media_analysis_job_errors(job.job_id)
    assert len(errors) == 1 and "1.00 s" in errors[0]["message"]
    assert not (service.cache_root / "thumbnails" / "bad").exists()
    monkeypatch.setattr(cv2, "VideoCapture", real_capture)
    assert service.run(job.job_id) == MediaAnalysisJobStatus.COMPLETE
    assert library.get_asset("bad").analysis_status == AnalysisStatus.COMPLETE
    assert library.list_shots("good") == good_shots
    assert library.list_media_analysis_job_errors(job.job_id) == []
    assert [dict(row) for row in repo.results_for_asset("bad", "gemini", "test-model")] == cache_before
    assert asset.path.read_bytes() == original_bytes


@pytest.mark.parametrize("duration", [3.1, 3.5])
def test_small_duration_rounding_at_end_does_not_fail_valid_video(tmp_path, duration):
    from dataclasses import replace

    source = tmp_path / "rounded.avi"
    assert _write_scene_video(source)
    library = MediaLibrary(tmp_path / "library.sqlite3")
    asset = _add_asset(library, source, "rounded")
    library.save_asset(replace(asset, duration_seconds=duration))
    service = ShotAnalysisService(library, tmp_path / "cache")
    assert service.run(service.create_job().job_id) == MediaAnalysisJobStatus.COMPLETE
    assert library.list_shots(asset.asset_id)[-1].end_seconds == duration


@pytest.mark.parametrize("reported", [float("nan"), float("inf"), -1, 1e12])
def test_invalid_decoder_timestamps_use_explicit_approximate_timebase(tmp_path, monkeypatch, reported):
    source = tmp_path / "timestamps.avi"
    assert _write_scene_video(source)
    library = MediaLibrary(tmp_path / "library.sqlite3")
    asset = _add_asset(library, source, "timestamps")
    real_capture = cv2.VideoCapture

    class BadTimeCapture:
        def __init__(self, path):
            self.capture = real_capture(path)

        def __getattr__(self, name):
            return getattr(self.capture, name)

        def get(self, key):
            return reported if key == cv2.CAP_PROP_POS_MSEC else self.capture.get(key)

    monkeypatch.setattr(cv2, "VideoCapture", BadTimeCapture)
    service = ShotAnalysisService(library, tmp_path / "cache")
    assert service.run(service.create_job().job_id) == MediaAnalysisJobStatus.COMPLETE
    shots = library.list_shots(asset.asset_id)
    assert len(shots) == 3 and shots[-1].end_seconds == 3
    assert all(shot.local_features["timebase_reliable"] == 0 for shot in shots)
    windows = library.local_features_for_assets([library.get_asset(asset.asset_id)], SHOT_ANALYSIS_VERSION)[asset.asset_id]
    assert len(windows) == 6 and all(window.features["timebase_reliable"] == 0 for window in windows)


@pytest.mark.parametrize("duration", [float("nan"), float("inf"), -1])
def test_invalid_duration_is_rejected_before_sampling(tmp_path, duration):
    source = tmp_path / "duration.avi"
    assert _write_scene_video(source)
    library = MediaLibrary(tmp_path / "library.sqlite3")
    asset = _add_asset(library, source, "duration")
    service = ShotAnalysisService(library, tmp_path / "cache")
    with pytest.raises(ValueError, match="duration"):
        service._analyze_asset(asset.asset_id, source, duration, Event(), asset.size_bytes, asset.modified_at)
