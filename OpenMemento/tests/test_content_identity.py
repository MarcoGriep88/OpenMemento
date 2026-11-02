from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timezone
from threading import Event

import pytest
import cv2
import numpy as np

from memento.ai.contracts import Moment, SemanticResult
from memento.application.indexing import MediaIndexService
from memento.application.movie_planning import MoviePlanningService
from memento.application.rendering import MovieRenderService, RenderSettings
from memento.application.semantic_analysis import SemanticAnalysisService
from memento.application.source_relinking import relink_movie_sources
from memento.domain.media import CaptureTime, IndexJobStatus, LocalFeatureWindow, MediaAsset, Shot, TimestampSource
from memento.library.database import MediaLibrary
from memento.library.semantic import SemanticRepository
from memento.media.identity import hash_media
from memento.media.metadata import MediaMetadata, MediaProbeCancelled, probe_media
from memento.media.local_features import FrameFeatureAnalyzer, LOCAL_ANALYSIS_VERSION


def metadata(path, cancel_token=None):
    return MediaMetadata(6, "h264", 96, 64, False,
                         CaptureTime(datetime(2026, 7, 12, 10), TimestampSource.QUICKTIME, 0.9))


def index(library, roots, verify=False):
    service = MediaIndexService(library, metadata)
    job = service.create_job(roots, verify_contents=verify)
    assert service.run(job.job_id) == IndexJobStatus.COMPLETE
    return job


def cached_moment(library, asset):
    repo = SemanticRepository(library)
    job = repo.create_job([asset], "gemini", "test-model")
    moment = Moment(0, min(6, asset.duration_seconds), "Kind lacht", "Gemeinsames Spielen", (), (), 0.9, 0.9, 0.8, 1, 0.9, ("Lachen",))
    repo.save_result(repo.get_job(job), repo.items(job)[0], SemanticResult((moment,), 100, 20))
    return repo, job


class NoNetworkProvider:
    name = "gemini"
    model = "test-model"

    def analyze(self, *args):
        pytest.fail("An identical source must not cause another paid request")


def test_copies_and_rename_share_identity_cache_and_one_movie_source(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    original = root / "original.mp4"
    original.write_bytes(b"same video bytes")
    library = MediaLibrary(tmp_path / "library.sqlite3")
    index(library, [root])
    first = library.get_asset_for_path(original)
    assert first.content_sha256 == hashlib.sha256(original.read_bytes()).hexdigest()
    repo, first_job = cached_moment(library, first)
    day = date(2026, 7, 12)
    old_plan = MoviePlanningService(repo).build(day, day, 6, "gemini", "test-model")
    renamed = root / "renamed.mp4"
    shutil.copyfile(original, renamed)
    os.utime(renamed, (original.stat().st_mtime + 500, original.stat().st_mtime + 500))
    original.unlink()
    index(library, [root])
    current = library.get_asset(first.asset_id)
    assert current.path == renamed
    assert current.asset_id == first.asset_id
    assert library.count_assets() == 1
    new_job = repo.create_job(library.list_assets(), "gemini", "test-model")
    assert repo.estimate(new_job)["pending"] == 0
    assert SemanticAnalysisService(repo, NoNetworkProvider()).run(new_job, Event()) == "complete"
    assert SemanticAnalysisService(repo, NoNetworkProvider()).run(first_job, Event()) == "complete"
    plan = MoviePlanningService(repo).build(day, day, 6, "gemini", "test-model")
    assert len(plan.segments) == 1 and plan.segments[0].candidate_id == old_plan.segments[0].candidate_id
    relinked = relink_movie_sources(old_plan, library, Event())
    assert relinked.segments[0].source.path == str(renamed)
    assert relinked.segments[0].start_seconds == old_plan.segments[0].start_seconds
    assert old_plan.segments[0].source.path == str(original)


def test_modifying_one_copy_splits_contents_without_losing_original_analysis(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    first, second = root / "a.mp4", root / "b.mp4"
    first.write_bytes(b"original video")
    shutil.copyfile(first, second)
    library = MediaLibrary(tmp_path / "library.sqlite3")
    index(library, [root])
    original = library.get_asset_for_path(first)
    assert library.get_asset_for_path(second).asset_id == original.asset_id
    repo, _ = cached_moment(library, original)
    first.write_bytes(b"new video content")
    index(library, [root])
    changed = library.get_asset_for_path(first)
    assert changed.asset_id != original.asset_id
    assert library.get_asset_for_path(second).asset_id == original.asset_id
    assert len(library.list_assets()) == 2
    assert repo.results_for_asset(changed.asset_id, "gemini", "test-model") == []
    assert len(repo.results_for_asset(original.asset_id, "gemini", "test-model")) == 1


def test_first_hash_adoption_preserves_legacy_candidates_and_resumable_jobs(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    path = root / "legacy.mp4"
    path.write_bytes(b"legacy video")
    library = MediaLibrary(tmp_path / "library.sqlite3")
    legacy = library.save_asset(MediaAsset("legacy-id", path, path.stat().st_size,
        datetime.fromtimestamp(path.stat().st_mtime).astimezone(), metadata(path).capture_time, duration_seconds=6))
    repo, old_job = cached_moment(library, legacy)
    old_key = repo.items(old_job)[0]["cache_key"]
    index(library, [root])
    adopted = library.get_asset(legacy.asset_id)
    assert adopted.content_sha256
    assert repo.results_for_asset(legacy.asset_id, "gemini", "test-model")[0]["cache_key"] == old_key
    assert SemanticAnalysisService(repo, NoNetworkProvider()).run(old_job, Event()) == "complete"
    new_job = repo.create_job([adopted], "gemini", "test-model")
    assert repo.estimate(new_job)["pending"] == 0
    assert SemanticAnalysisService(repo, NoNetworkProvider()).run(new_job, Event()) == "complete"


def test_two_legacy_copies_merge_without_losing_cached_results(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    library = MediaLibrary(tmp_path / "library.sqlite3")
    old_jobs = []
    for name in ("a", "b"):
        path = root / f"{name}.mp4"
        path.write_bytes(b"identical legacy source")
        asset = library.save_asset(MediaAsset(name, path, path.stat().st_size,
            datetime.fromtimestamp(path.stat().st_mtime).astimezone(), metadata(path).capture_time, duration_seconds=6))
        repo, job = cached_moment(library, asset)
        old_jobs.append(job)
    index(library, [root])
    assert library.count_assets() == 1
    assert library.get_asset("a").asset_id == library.get_asset("b").asset_id
    for job in old_jobs:
        assert SemanticAnalysisService(repo, NoNetworkProvider()).run(job, Event()) == "complete"
    plan = MoviePlanningService(repo).build(date(2026, 7, 12), date(2026, 7, 12), 12, "gemini", "test-model")
    assert len(plan.segments) == 1 and plan.duration == 6
    assert len(plan.decisions) == 2  # Both historical answers remain inspectable.


def test_hash_cancellation_and_source_change_detection(tmp_path):
    path = tmp_path / "large.mp4"
    path.write_bytes(b"x" * (5 * 1024 * 1024))
    token = Event()
    with pytest.raises(MediaProbeCancelled):
        hash_media(path, token, lambda done, total: token.set())
    assert path.stat().st_size == 5 * 1024 * 1024
    assert hash_media(path) == hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(OSError, match="verändert"):
        hash_media(path, on_bytes=lambda done, total: path.write_bytes(b"changed externally"))


def test_cancelled_import_resumes_without_rehashing_completed_files(tmp_path, monkeypatch):
    import memento.application.indexing as module

    root = tmp_path / "media"
    root.mkdir()
    for name in ("a", "b"):
        (root / f"{name}.mp4").write_bytes(name.encode())
    library = MediaLibrary(tmp_path / "library.sqlite3")
    service = MediaIndexService(library, metadata)
    original_hash, calls = module.hash_media, []

    def track(path, **kwargs):
        calls.append(path)
        return original_hash(path, **kwargs)

    monkeypatch.setattr(module, "hash_media", track)
    token = Event()
    job = service.create_job([root])

    def cancel_after_first(progress):
        if progress.phase == "indexing" and progress.completed == 1:
            token.set()

    assert service.run(job.job_id, cancel_after_first, token) == IndexJobStatus.CANCELLED
    token.clear()
    assert service.run(job.job_id, cancel_token=token) == IndexJobStatus.COMPLETE
    assert len(calls) == 2 and len(set(calls)) == 2


def test_forced_content_verification_finds_same_size_same_mtime_changes(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    source = root / "clip.mp4"
    source.write_bytes(b"one-video")
    library = MediaLibrary(tmp_path / "library.sqlite3")
    index(library, [root])
    first = library.get_asset_for_path(source)
    old_stat = source.stat()
    source.write_bytes(b"two-video")
    os.utime(source, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    job = index(library, [root], verify=True)
    assert library.get_index_job(job.job_id).verify_contents
    current = library.get_asset_for_path(source)
    assert current.asset_id != first.asset_id
    assert current.content_sha256 != first.content_sha256


def test_render_rejects_content_change_even_when_size_and_mtime_match(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    source = root / "clip.mp4"
    source.write_bytes(b"one-video")
    library = MediaLibrary(tmp_path / "library.sqlite3")
    index(library, [root])
    repo, _ = cached_moment(library, library.get_asset_for_path(source))
    day = date(2026, 7, 12)
    plan = MoviePlanningService(repo).build(day, day, 6, "gemini", "test-model")
    stat = source.stat()
    source.write_bytes(b"two-video")
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(ValueError, match="Quellinhalt"):
        MovieRenderService(tmp_path / "renders").render(plan, tmp_path / "movie.mp4", Event())


def test_alias_metadata_preserves_recording_date_over_copy_mtime(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    first = root / "a.mp4"
    first.write_bytes(b"video")
    library = MediaLibrary(tmp_path / "library.sqlite3")
    index(library, [root])
    original = library.get_asset_for_path(first)
    copy = root / "b.mp4"
    shutil.copyfile(first, copy)
    service = MediaIndexService(library, lambda *args, **kwargs: replace(metadata(first), capture_time=None))
    assert service.run(service.create_job([root]).job_id) == IndexJobStatus.COMPLETE
    assert library.get_asset_for_path(copy).capture_time == original.capture_time


def test_local_cache_is_shared_and_preserved_when_legacy_assets_merge(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    library = MediaLibrary(tmp_path / "library.sqlite3")
    for name in ("a", "b"):
        path = root / f"{name}.mp4"
        path.write_bytes(b"duplicate")
        asset = library.save_asset(MediaAsset(name, path, path.stat().st_size,
            datetime.fromtimestamp(path.stat().st_mtime).astimezone(), metadata(path).capture_time, duration_seconds=6))
    features = FrameFeatureAnalyzer().measure(np.full((64, 96, 3), 50, dtype=np.uint8))
    library.save_shots("a", [Shot("outdated-shot", "a", 0, 6)], windows=[], analysis_version="old-local-version")
    library.save_shots("b", [Shot("legacy-shot", "b", 0, 6)], windows=[LocalFeatureWindow("b", 0, 6, features)],
                       analysis_version=LOCAL_ANALYSIS_VERSION)
    index(library, [root])
    canonical = library.get_asset("a")
    assert library.get_asset("b").asset_id == canonical.asset_id
    assert canonical.analysis_version == LOCAL_ANALYSIS_VERSION
    assert library.list_shots(canonical.asset_id)[0].shot_id == "legacy-shot"
    assert library.local_features_for_assets([canonical], LOCAL_ANALYSIS_VERSION)[canonical.asset_id]


def test_changed_path_can_relink_to_a_remaining_identical_copy(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    first, second = root / "a.mp4", root / "b.mp4"
    first.write_bytes(b"original video")
    shutil.copyfile(first, second)
    library = MediaLibrary(tmp_path / "library.sqlite3")
    index(library, [root])
    repo, _ = cached_moment(library, library.get_asset_for_path(first))
    day = date(2026, 7, 12)
    plan = MoviePlanningService(repo).build(day, day, 6, "gemini", "test-model")
    selected = plan.segments[0].source
    changed = first if str(first) == selected.path else second
    remaining = second if changed == first else first
    changed.write_bytes(b"new unrelated content")
    index(library, [root])
    resolved = relink_movie_sources(plan, library, Event())
    assert resolved.segments[0].source.path == str(remaining)
    assert resolved.segments[0].source.content_sha256 == selected.content_sha256


def test_no_upload_when_verified_source_content_changed_without_stat_change(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    source = root / "clip.mp4"
    source.write_bytes(b"one-video")
    library = MediaLibrary(tmp_path / "library.sqlite3")
    index(library, [root])
    repo = SemanticRepository(library)
    job = repo.create_job(library.list_assets(), "gemini", "test-model")
    stat = source.stat()
    source.write_bytes(b"two-video")
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert SemanticAnalysisService(repo, NoNetworkProvider()).run(job, Event()) == "complete_with_errors"
    assert "Quellinhalt" in repo.items(job)[0]["error"]


def test_real_renamed_video_plan_relinks_and_renders_without_new_analysis(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    source = root / "original.avi"
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"MJPG"), 12, (96, 64))
    assert writer.isOpened()
    for index_frame in range(24):
        writer.write(np.full((64, 96, 3), (index_frame * 8, 100, 80), dtype=np.uint8))
    writer.release()
    original_bytes = source.read_bytes()
    library = MediaLibrary(tmp_path / "library.sqlite3")

    def actual_metadata(path, cancel_token=None):
        return replace(probe_media(path, cancel_token=cancel_token), capture_time=metadata(path).capture_time)

    service = MediaIndexService(library, actual_metadata)
    assert service.run(service.create_job([root]).job_id) == IndexJobStatus.COMPLETE
    repo, _ = cached_moment(library, library.get_asset_for_path(source))
    day = date(2026, 7, 12)
    plan = MoviePlanningService(repo).build(day, day, 2, "gemini", "test-model")
    renamed = root / "moved.avi"
    source.rename(renamed)
    assert service.run(service.create_job([root]).job_id) == IndexJobStatus.COMPLETE
    resolved = relink_movie_sources(plan, library, Event())
    output = tmp_path / "movie.mp4"
    MovieRenderService(tmp_path / "renders").render(resolved, output, Event(), settings=RenderSettings(160, 90, 12))
    capture = cv2.VideoCapture(str(output))
    try:
        assert capture.isOpened()
        assert capture.get(cv2.CAP_PROP_FRAME_COUNT) / capture.get(cv2.CAP_PROP_FPS) == pytest.approx(2, abs=0.15)
    finally:
        capture.release()
    assert renamed.read_bytes() == original_bytes


def test_schema_five_upgrades_without_losing_legacy_cache(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    path = root / "old.mp4"
    path.write_bytes(b"legacy")
    library = MediaLibrary(tmp_path / "library.sqlite3")
    asset = library.save_asset(MediaAsset("old", path, 6, datetime.fromtimestamp(path.stat().st_mtime).astimezone(),
                                         metadata(path).capture_time, duration_seconds=6))
    repo, job = cached_moment(library, asset)
    key = repo.items(job)[0]["cache_key"]
    with sqlite3.connect(library.path) as db:
        db.execute("ALTER TABLE assets DROP COLUMN metadata_version")
        db.execute("DELETE FROM schema_migrations WHERE version=7")
        db.execute("DROP TABLE asset_aliases")
        db.execute("DROP INDEX idx_assets_content")
        db.execute("ALTER TABLE assets DROP COLUMN content_sha256")
        db.execute("DROP INDEX idx_locations_preferred")
        db.execute("ALTER TABLE locations DROP COLUMN available")
        db.execute("ALTER TABLE index_jobs DROP COLUMN verify_contents")
        db.execute("DELETE FROM schema_migrations WHERE version=6")
        db.execute("PRAGMA user_version=5")
    migrated = MediaLibrary(library.path)
    assert migrated.get_asset("old").content_sha256 is None
    assert SemanticRepository(migrated).cached(key)
    backups = list((tmp_path / "backups").glob("*-schema-5-*.sqlite3"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 5
    index(migrated, [root])
    assert SemanticRepository(migrated).results_for_asset("old", "gemini", "test-model")[0]["cache_key"] == key


def test_hash_adoption_preserves_cache_when_same_mtime_has_another_timezone(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    source = root / "clip.mp4"
    source.write_bytes(b"video")
    library = MediaLibrary(tmp_path / "library.sqlite3")
    legacy = library.save_asset(MediaAsset("old", source, 5, datetime.fromtimestamp(source.stat().st_mtime, timezone.utc),
        metadata(source).capture_time, duration_seconds=6))
    repo, job = cached_moment(library, legacy)
    index(library, [root])
    assert library.get_asset("old").content_sha256
    assert repo.estimate(job)["pending"] == 0
    assert SemanticAnalysisService(repo, NoNetworkProvider()).run(job, Event()) == "complete"


def test_changed_content_uses_current_filesystem_date_when_metadata_is_missing(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    source = root / "clip.mp4"
    source.write_bytes(b"first video")
    first_time = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()
    os.utime(source, (first_time, first_time))
    library = MediaLibrary(tmp_path / "library.sqlite3")
    service = MediaIndexService(library, lambda *args, **kwargs: replace(metadata(source), capture_time=None))
    assert service.run(service.create_job([root]).job_id) == IndexJobStatus.COMPLETE
    source.write_bytes(b"different replacement video")
    second_time = datetime(2026, 2, 3, tzinfo=timezone.utc).timestamp()
    os.utime(source, (second_time, second_time))
    assert service.run(service.create_job([root]).job_id) == IndexJobStatus.COMPLETE
    capture = library.get_asset_for_path(source).capture_time
    assert capture.source == TimestampSource.FILESYSTEM
    assert capture.value == datetime.fromtimestamp(second_time).astimezone()
    assert library.count_assets() == 1


def test_copy_does_not_replace_manual_recording_date(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    first = root / "a.mp4"
    first.write_bytes(b"same video")
    library = MediaLibrary(tmp_path / "library.sqlite3")
    index(library, [root])
    original = library.get_asset_for_path(first)
    manual = CaptureTime(datetime(2025, 12, 24, 18), TimestampSource.MANUAL, 1.0)
    library.save_asset(replace(original, capture_time=manual))
    shutil.copyfile(first, root / "b.mp4")
    index(library, [root])
    assert library.get_asset_for_path(root / "b.mp4").capture_time == manual
