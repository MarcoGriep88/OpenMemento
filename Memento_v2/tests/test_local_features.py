from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import date, datetime

import cv2
import numpy as np
import pytest

from memento.ai.contracts import Moment, SemanticResult
from memento.application.movie_planning import MoviePlanningService
from memento.application.shot_analysis import ShotAnalysisService
from memento.domain.media import AnalysisStatus, CaptureTime, LocalFeatureWindow, MediaAnalysisJobStatus, MediaAsset, Shot, TimestampSource
from memento.domain.movie import MoviePreferences
from memento.library.database import MediaLibrary
from memento.library.semantic import SemanticRepository
from memento.media.local_features import (
    FrameFeatureAnalyzer, LOCAL_ANALYSIS_VERSION, LocalFeatureIndex,
    technical_quality, visual_signature, visual_similarity,
)


def pattern(seed=1):
    rng = np.random.default_rng(seed)
    coarse = rng.integers(30, 220, (18, 32, 3), dtype=np.uint8)
    return cv2.resize(coarse, (320, 180), interpolation=cv2.INTER_NEAREST)


def test_sharpness_exposure_and_texture_measurements():
    sharp = pattern()
    blurry = cv2.GaussianBlur(sharp, (21, 21), 5)
    original = FrameFeatureAnalyzer().measure(sharp)
    blurred = FrameFeatureAnalyzer().measure(blurry)
    dark = FrameFeatureAnalyzer().measure(np.zeros_like(sharp))
    bright = FrameFeatureAnalyzer().measure(np.full_like(sharp, 255))
    assert original["sharpness"] > blurred["sharpness"] * 10
    assert technical_quality(original) > technical_quality(blurred)
    assert dark["dark_fraction"] == 1 and bright["bright_fraction"] == 1
    assert dark["blur_confidence"] == 0
    assert visual_signature(dark) is None and visual_signature(bright) is None


def test_motion_distinguishes_steady_pan_from_alternating_shake_and_resets_at_cuts():
    image = pattern()

    def analyze(shifts):
        analyzer = FrameFeatureAnalyzer()
        return [analyzer.measure(cv2.warpAffine(image, np.float32([[1, 0, shift], [0, 1, 0]]), (320, 180),
                                               borderMode=cv2.BORDER_REFLECT)) for shift in shifts]

    pan, shake = analyze(range(8)), analyze([0, 10, -10, 10, -10, 10, -10, 10])
    assert np.mean([value["jitter"] for value in shake[2:]]) > np.mean([value["jitter"] for value in pan[2:]]) * 3
    analyzer = FrameFeatureAnalyzer()
    analyzer.measure(image)
    assert analyzer.measure(pattern(2), reset_motion=True)["motion_confidence"] == 0


def test_similar_sequences_detected_but_uniform_images_and_different_content_not_duplicates():
    original = [visual_signature(FrameFeatureAnalyzer().measure(pattern(seed))) for seed in (1, 2, 3)]
    brighter = [visual_signature(FrameFeatureAnalyzer().measure(cv2.add(pattern(seed), np.full_like(pattern(seed), 5)))) for seed in (1, 2, 3)]
    unrelated = [visual_signature(FrameFeatureAnalyzer().measure(pattern(seed))) for seed in (4, 5, 6)]
    assert visual_similarity(original, brighter) > 0.9
    assert visual_similarity(original, unrelated) == 0
    assert visual_similarity(original[:1], brighter[:1]) == 0


def test_range_quality_uses_overlap_and_requires_coverage():
    sharp = FrameFeatureAnalyzer().measure(pattern())
    dark = FrameFeatureAnalyzer().measure(np.zeros((180, 320, 3), dtype=np.uint8))
    windows = [LocalFeatureWindow("asset", float(index), index + 1.0, dark if index < 3 else sharp) for index in range(6)]
    features = LocalFeatureIndex(windows)
    assert features.summarize(0, 3)[0] < features.summarize(3, 6)[0]
    assert features.summarize(3, 6)[1]
    assert features.summarize(0, 3)[1] == ()
    assert features.summarize(7, 10) == (None, (), ())
    expected = (technical_quality(dark) * 0.5 + technical_quality(sharp) * 1.5) / 2
    assert features.summarize(2.5, 4.5)[0] == pytest.approx(expected)


def add_asset(library, tmp_path, name, duration=6):
    path = tmp_path / f"{name}.mp4"
    path.write_bytes(b"source")
    return library.save_asset(MediaAsset(name, path, path.stat().st_size,
        datetime.fromtimestamp(path.stat().st_mtime).astimezone(),
        CaptureTime(datetime(2026, 7, 12, 10), TimestampSource.QUICKTIME, 0.9), duration_seconds=duration))


def test_local_features_and_shots_commit_together_and_invalidate_with_source(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    asset = add_asset(library, tmp_path, "asset")
    old = Shot("old", "asset", 0, 6)
    window = LocalFeatureWindow("asset", 0, 0.5, FrameFeatureAnalyzer().measure(pattern()))
    library.save_shots("asset", [old], windows=[window], analysis_version=LOCAL_ANALYSIS_VERSION)
    with library._connection() as db:
        db.execute("CREATE TRIGGER fail_local BEFORE INSERT ON local_feature_windows BEGIN SELECT RAISE(ABORT, 'simulate disk failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        library.save_shots("asset", [Shot("new", "asset", 0, 3)], windows=[window], analysis_version=LOCAL_ANALYSIS_VERSION)
    assert library.list_shots("asset")[0].shot_id == "old"
    assert len(library.local_features_for_assets([library.get_asset("asset")], LOCAL_ANALYSIS_VERSION)["asset"]) == 1
    with library._connection() as db:
        db.execute("DROP TRIGGER fail_local")
    library.save_asset(replace(asset, size_bytes=100))
    assert library.local_features_for_assets([library.get_asset("asset")], LOCAL_ANALYSIS_VERSION) == {}
    with library._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM local_feature_windows").fetchone()[0] == 0


def test_migration_backup_preserves_old_schema_and_committed_wal(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    add_asset(library, tmp_path, "asset")
    with sqlite3.connect(library.path) as writer:
        _remove_identity_schema(writer)
        writer.execute("DROP TABLE local_feature_windows")
        writer.execute("DELETE FROM schema_migrations WHERE version=5")
        writer.execute("PRAGMA user_version=4")
        writer.execute("UPDATE assets SET duration_seconds=12 WHERE asset_id='asset'")
        writer.commit()
        migrated = MediaLibrary(library.path)
        backups = list((tmp_path / "backups").glob("*-schema-4-*.sqlite3"))
        assert len(backups) == 1
        with sqlite3.connect(backups[0]) as backup:
            assert backup.execute("PRAGMA user_version").fetchone()[0] == 4
            assert backup.execute("SELECT duration_seconds FROM assets").fetchone()[0] == 12
            assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert migrated.get_asset("asset").duration_seconds == 12


def test_failed_backup_prevents_schema_changes(tmp_path, monkeypatch):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    add_asset(library, tmp_path, "asset")
    with sqlite3.connect(library.path) as db:
        _remove_identity_schema(db)
        db.execute("DROP TABLE local_feature_windows")
        db.execute("DELETE FROM schema_migrations WHERE version=5")
        db.execute("PRAGMA user_version=4")

    def fail_backup(*args):
        raise OSError("simulated full backup disk")

    monkeypatch.setattr(MediaLibrary, "_backup_before_migration", fail_backup)
    with pytest.raises(OSError, match="simulated"):
        MediaLibrary(library.path)
    with sqlite3.connect(library.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert db.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1
        assert db.execute("SELECT name FROM sqlite_master WHERE name='local_feature_windows'").fetchone() is None


def _remove_identity_schema(db):
    db.execute("ALTER TABLE assets DROP COLUMN metadata_version")
    db.execute("DELETE FROM schema_migrations WHERE version=7")
    db.execute("DROP TABLE asset_aliases")
    db.execute("DROP INDEX idx_assets_content")
    db.execute("ALTER TABLE assets DROP COLUMN content_sha256")
    db.execute("DROP INDEX idx_locations_preferred")
    db.execute("ALTER TABLE locations DROP COLUMN available")
    db.execute("ALTER TABLE index_jobs DROP COLUMN verify_contents")
    db.execute("DELETE FROM schema_migrations WHERE version=6")


def test_real_shot_analysis_stores_segment_level_features_and_keeps_original(tmp_path):
    source = tmp_path / "source.avi"
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 180))
    assert writer.isOpened()
    for index in range(60):
        writer.write(pattern() if index >= 30 else np.zeros((180, 320, 3), dtype=np.uint8))
    writer.release()
    before = source.read_bytes()
    library = MediaLibrary(tmp_path / "library.sqlite3")
    asset = library.save_asset(MediaAsset("real", source, source.stat().st_size,
        datetime.fromtimestamp(source.stat().st_mtime).astimezone(), duration_seconds=6))
    repo = SemanticRepository(library)
    store_semantics(repo, asset)
    semantic_before = [dict(row) for row in repo.results_for_asset("real", "gemini", "test-model")]
    service = ShotAnalysisService(library, tmp_path / "cache")
    job = service.create_job()
    service.run(job.job_id)
    windows = library.local_features_for_assets([library.get_asset("real")], LOCAL_ANALYSIS_VERSION)["real"]
    assert len(windows) >= 10
    assert LocalFeatureIndex(windows).summarize(0, 2)[0] < LocalFeatureIndex(windows).summarize(4, 6)[0]
    assert source.read_bytes() == before
    assert [dict(row) for row in repo.results_for_asset("real", "gemini", "test-model")] == semantic_before


def store_semantics(repo, asset, importance=0.8, emotion=0.8, description="Familie", end=6):
    job = repo.create_job([asset], "gemini", "test-model")
    moment = Moment(0, end, description, "Familienausflug", (), (), importance, emotion, 0.8, 0.8, 0.9, ("Menschlicher Moment",))
    repo.save_result(repo.get_job(job), repo.items(job)[0], SemanticResult((moment,)))


def store_features(library, asset, images):
    analyzer = FrameFeatureAnalyzer()
    windows = [LocalFeatureWindow(asset.asset_id, index * 0.5, (index + 1) * 0.5, analyzer.measure(image)) for index, image in enumerate(images)]
    library.save_shots(asset.asset_id, [], windows=windows, analysis_version=LOCAL_ANALYSIS_VERSION)


def test_quality_influences_ties_but_emotional_memory_survives_bad_picture(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    repo = SemanticRepository(library)
    for name, image, importance, emotion in (("dark", np.zeros((180, 320, 3), dtype=np.uint8), 0.8, 0.8),
                                            ("sharp", pattern(), 0.8, 0.8)):
        asset = add_asset(library, tmp_path, name)
        store_semantics(repo, asset, importance, emotion)
        store_features(library, asset, [image] * 12)
    service = MoviePlanningService(repo)
    day = date(2026, 7, 12)
    plan = service.build(day, day, 6, "gemini", "test-model")
    assert plan.segments[0].source.asset_id == "sharp"
    assert plan.local_analysis_version == LOCAL_ANALYSIS_VERSION
    # Emotion and human importance dominate technical perfection.
    store_semantics(repo, library.get_asset("dark"), 1.0, 1.0)
    store_semantics(repo, library.get_asset("sharp"), 0.1, 0.1)
    plan = service.build(day, day, 6, "gemini", "test-model")
    assert plan.segments[0].source.asset_id == "dark"
    assert any("dunkle" in reason for reason in plan.segments[0].reasons)


def test_visual_repetition_affects_selection_and_forced_moment_is_still_available(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    repo = SemanticRepository(library)
    for name, seed, description, importance in (("first", 1, "Person winkt am Wasser", 1.0),
                                               ("copy", 1, "Sonnenlicht am Ufer", 0.9),
                                               ("other", 8, "Hund springt zum Ball", 0.8)):
        asset = add_asset(library, tmp_path, name)
        store_semantics(repo, asset, importance, 0.8, description)
        store_features(library, asset, [pattern(seed)] * 12)
    service = MoviePlanningService(repo)
    day = date(2026, 7, 12)
    plan = service.build(day, day, 12, "gemini", "test-model")
    assert {item.source.asset_id for item in plan.segments} == {"first", "other"}
    candidates, _ = service.candidates(day, day, "gemini", "test-model")
    copied = next(item for item in candidates if item.source.asset_id == "copy")
    assert "Bildstichproben" in plan.decisions[copied.candidate_id]
    forced = service.build(day, day, 6, "gemini", "test-model", MoviePreferences(forced={copied.candidate_id}))
    assert forced.segments[0].source.asset_id == "copy"


def test_manual_boundaries_recalculate_local_quality_and_old_versions_are_ignored(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    repo = SemanticRepository(library)
    asset = add_asset(library, tmp_path, "asset")
    store_semantics(repo, asset)
    store_features(library, asset, [np.zeros((180, 320, 3), dtype=np.uint8)] * 6 + [pattern()] * 6)
    service = MoviePlanningService(repo)
    day = date(2026, 7, 12)
    original = service.candidates(day, day, "gemini", "test-model")[0][0]
    trimmed = service.candidates(day, day, "gemini", "test-model", trims={original.candidate_id: (3, 6)})[0][0]
    assert trimmed.technical_quality > original.technical_quality
    assert trimmed.start_seconds == 3
    assert not any("dunkle" in note for note in trimmed.reasons)
    library.set_asset_analysis_state(asset.asset_id, AnalysisStatus.COMPLETE, "old-version")
    stale = service.candidates(day, day, "gemini", "test-model")[0][0]
    assert stale.technical_quality is None and stale.visual_samples == ()


def test_feature_stream_reads_only_one_batch_at_a_time(tmp_path, monkeypatch):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    features = FrameFeatureAnalyzer().measure(pattern())
    for index in range(5):
        asset = add_asset(library, tmp_path, str(index))
        library.save_shots(asset.asset_id, [], windows=[LocalFeatureWindow(asset.asset_id, 0, 6, features)], analysis_version=LOCAL_ANALYSIS_VERSION)
    assets = library.list_assets()
    reads = []
    original_connect = library._connect

    def connect():
        connection = original_connect()
        connection.set_trace_callback(lambda sql: reads.append(sql) if "SELECT * FROM local_feature_windows" in sql else None)
        return connection

    monkeypatch.setattr(library, "_connect", connect)
    iterator = library.iter_assets_with_local_features(assets, LOCAL_ANALYSIS_VERSION, batch_size=2)
    first, windows = next(iterator)
    assert first.asset_id == "0" and len(windows) == 1
    assert len(reads) == 1
    next(iterator)
    assert len(reads) == 1
    next(iterator)
    assert len(reads) == 2
    assert len(list(iterator)) == 2
    assert len(reads) == 3


def test_changed_source_is_not_skipped_even_when_local_cache_is_complete(tmp_path, monkeypatch):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    asset = add_asset(library, tmp_path, "asset")
    store_features(library, asset, [pattern()] * 12)
    asset.path.write_bytes(b"changed source data")
    service = ShotAnalysisService(library, tmp_path / "cache")
    monkeypatch.setattr(service, "_analyze_asset", lambda *args: pytest.fail("Changed source must be rejected before decoding"))
    job = service.create_job()
    assert service.run(job.job_id) == MediaAnalysisJobStatus.COMPLETE_WITH_ERRORS
    assert library.get_asset(asset.asset_id).analysis_status == AnalysisStatus.FAILED


def library_with_cross_event_repetition(tmp_path, uniform=False):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    repo = SemanticRepository(library)
    for name, hour, seed, importance in (("reference", 10, 1, 1.0), ("repeat", 13, 1, 0.9), ("variety", 13, 8, 0.8)):
        asset = add_asset(library, tmp_path, name)
        asset = library.save_asset(replace(asset, capture_time=CaptureTime(
            datetime(2026, 7, 12, hour), TimestampSource.QUICKTIME, 0.9)))
        store_semantics(repo, asset, importance, 0.8, description=f"Moment {name}")
        image = np.zeros((180, 320, 3), dtype=np.uint8) if uniform else pattern(seed)
        store_features(library, asset, [image] * 12)
    return library, repo, MoviePlanningService(repo)


def test_visual_variety_considers_the_complete_movie_not_only_current_event(tmp_path):
    library, repo, service = library_with_cross_event_repetition(tmp_path)
    before = [dict(row) for asset in library.list_assets() for row in repo.results_for_asset(asset.asset_id, "gemini", "test-model")]
    day = date(2026, 7, 12)
    plan = service.build(day, day, 12, "gemini", "test-model")
    assert len(plan.events) == 2
    assert [item.source.asset_id for item in plan.segments] == ["reference", "variety"]
    candidates, _ = service.candidates(day, day, "gemini", "test-model")
    repeat = next(item for item in candidates if item.source.asset_id == "repeat")
    assert "Bildstichproben" in plan.decisions[repeat.candidate_id]
    assert [dict(row) for asset in library.list_assets() for row in repo.results_for_asset(asset.asset_id, "gemini", "test-model")] == before


def test_repeated_looking_moments_can_be_forced_and_are_not_hard_rejected(tmp_path):
    _, _, service = library_with_cross_event_repetition(tmp_path)
    day = date(2026, 7, 12)
    candidates, _ = service.candidates(day, day, "gemini", "test-model")
    required = {item.candidate_id for item in candidates if item.source.asset_id in ("reference", "repeat")}
    plan = service.build(day, day, 12, "gemini", "test-model", MoviePreferences(forced=required))
    assert {item.candidate_id for item in plan.segments} == required
    assert any("Bedeutung und Ton bitte prüfen" in reason for item in plan.segments for reason in item.reasons)
    full = service.build(day, day, 18, "gemini", "test-model")
    assert len(full.segments) == 3 and full.duration == 18


def test_uniform_images_cannot_establish_cross_event_repetition(tmp_path):
    _, _, service = library_with_cross_event_repetition(tmp_path, uniform=True)
    day = date(2026, 7, 12)
    plan = service.build(day, day, 12, "gemini", "test-model")
    assert [item.source.asset_id for item in plan.segments] == ["reference", "repeat"]
    assert not any("Bildstichproben" in reason for item in plan.segments for reason in item.reasons)


def test_shortened_selection_does_not_claim_visual_evidence_from_its_unused_tail(tmp_path):
    _, _, service = library_with_cross_event_repetition(tmp_path)
    day = date(2026, 7, 12)
    initial = service.build(day, day, 12, "gemini", "test-model")
    preferences = MoviePreferences(event_weights={initial.events[0].event_id: 1,
                                                 initial.events[1].event_id: 3})
    shorter = service.build(day, day, 12, "gemini", "test-model", preferences)
    durations = {item.source.asset_id: item.duration for item in shorter.segments}
    assert durations["reference"] < 6  # Its full signature includes unused frames.
    assert durations["repeat"] == 6  # No unsupported penalty against this intact range.
    assert not any("Bedeutung und Ton bitte prüfen" in reason for item in shorter.segments for reason in item.reasons)


def test_cross_event_similarity_remains_a_soft_preference_for_meaningful_audio(tmp_path):
    library, repo, service = library_with_cross_event_repetition(tmp_path)
    asset = library.get_asset("variety")
    job = repo.create_job([asset], "gemini", "test-model")
    irrelevant = Moment(0, 6, "Leere Wand ohne Handlung", "Familienausflug", (), (),
                        0, 0, 0, 0, 1, ("Kein erkennbarer Erinnerungsmoment",))
    # Replace the original fixture result, rather than add a legacy-equivalent
    # range under another key (integer/float JSON identities may differ).
    original = repo.results_for_asset(asset.asset_id, "gemini", "test-model")[0]
    item = dict(repo.items(job)[0], cache_key=original["cache_key"])
    repo.save_result(repo.get_job(job), item, SemanticResult((irrelevant,)))
    day = date(2026, 7, 12)
    plan = service.build(day, day, 12, "gemini", "test-model")
    assert [item.source.asset_id for item in plan.segments] == ["reference", "repeat"]
    assert any("Bedeutung und Ton bitte prüfen" in reason for item in plan.segments for reason in item.reasons)
