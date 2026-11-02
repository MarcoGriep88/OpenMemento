from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from datetime import date, datetime, timedelta
from threading import Event

import pytest

from memento.ai.contracts import Moment, SemanticResult
from memento.application.movie_planning import MoviePlanningService, PlanningCancelled, cluster_events
from memento.application.evaluation import evaluate_movie
from memento.application import movie_planning
from memento.domain.media import CaptureTime, MediaAsset, TimestampSource
from memento.domain.movie import MoviePreferences
from memento.library.database import MediaLibrary
from memento.library.movies import load_movie, save_movie
from memento.library.semantic import SemanticRepository


DAY = date(2026, 7, 12)


@pytest.mark.parametrize("target", [454.40, 454, 600, 120])
def test_target_is_a_guideline_for_454_40_seconds_of_material(tmp_path, target):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    repo = SemanticRepository(library)
    for index, duration in enumerate((100, 154.40, 200)):
        asset = add_asset(library, tmp_path, f"clip-{index}", datetime(2026, 7, 12, 9 + index), duration)
        store_moments(repo, asset)
    service = MoviePlanningService(repo)
    plan = service.build(DAY, DAY, target, "gemini", "test-model")
    plan.validate()
    assert plan.segments
    assert plan.target_seconds == target
    assert plan.duration == pytest.approx(min(target, 454.40), abs=2)
    if target >= 454.40:
        candidates, _ = service.candidates(DAY, DAY, "gemini", "test-model")
        assert {item.candidate_id for item in plan.segments} == {item.candidate_id for item in candidates}
        assert plan.duration == pytest.approx(454.40)


def test_only_sub_two_second_moments_still_produce_a_movie(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    repo = SemanticRepository(library)
    for index in range(3):
        asset = add_asset(library, tmp_path, f"short-{index}", datetime(2026, 7, 12, 9 + index), 0.8)
        store_moments(repo, asset)
    plan = MoviePlanningService(repo).build(DAY, DAY, 600, "gemini", "test-model")
    assert len(plan.segments) == 3
    assert plan.duration == pytest.approx(2.4)
    plan.validate()


def add_asset(library, root, name, capture, duration=10):
    path = root / f"{name}.mp4"
    path.write_bytes(b"source")
    return library.save_asset(MediaAsset(name, path, path.stat().st_size,
        datetime.fromtimestamp(path.stat().st_mtime).astimezone(),
        capture_time=CaptureTime(capture, TimestampSource.QUICKTIME, 0.9), duration_seconds=duration))


def store_moments(repo, asset, description="Kind lacht mit den Eltern", event="Spielen im Garten", importance=0.8,
                  activities=("Spielen",), moments=None):
    job = repo.create_job([asset], "gemini", "test-model")
    for item in repo.items(job):
        duration = item["end_seconds"] - item["start_seconds"]
        values = moments if moments is not None else (Moment(0, duration, description, event, activities,
            ("Kind mit Hut",), importance, 0.9, 0.8, 0.8, 0.9, ("Menschliche Interaktion",)),)
        repo.save_result(repo.get_job(job), item, SemanticResult(values))


def library_with_events(tmp_path, counts=(3, 3)):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    repo = SemanticRepository(library)
    for event, count in enumerate(counts):
        for index in range(count):
            asset = add_asset(library, tmp_path, f"event-{event}-{index}", datetime(2026, 7, 12, 9 + event * 3) + timedelta(seconds=index * 15))
            store_moments(repo, asset, event=("Spielen im Garten", "Bootsfahrt auf dem See")[event])
    return library, repo, MoviePlanningService(repo)


def test_many_recordings_do_not_crowd_out_small_event_and_order_is_chronological(tmp_path):
    _, _, service = library_with_events(tmp_path, counts=(25, 1))
    plan = service.build(DAY, DAY, 20, "gemini", "test-model")
    assert len(plan.events) == 2
    assert len(plan.segments) == 2
    assert [segment.event_id for segment in plan.segments] == [event.event_id for event in plan.events]
    assert plan.duration == pytest.approx(20)
    assert plan.segments[0].source.asset_id.startswith("event-0")
    assert plan.segments[1].source.asset_id.startswith("event-1")
    # Planning from the cache may never trigger another provider call.
    assert service.build(DAY, DAY, 20, "gemini", "test-model").segments == plan.segments


def test_dense_activity_change_receives_independent_movie_time_from_unchanged_cache(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    repo = SemanticRepository(library)
    base = datetime(2026, 7, 12, 10)
    for index in range(10):
        garden = index < 8
        asset = add_asset(library, tmp_path, f"clip-{index:02}", base + timedelta(seconds=60 * index))
        store_moments(repo, asset, event="Spielen im Garten" if garden else "Bootsfahrt auf See",
                      activities=("Ball spielen",) if garden else ("Boot fahren",),
                      importance=0.95 if garden else 0.55)
    with library._connection() as db:
        cached_before = [tuple(row) for row in db.execute("SELECT * FROM semantic_cache ORDER BY cache_key")]
    service = MoviePlanningService(repo)
    plan = service.build(DAY, DAY, 20, "gemini", "test-model")
    assert len(plan.events) == 2
    assert [sum(item.duration for item in plan.segments if item.event_id == event.event_id)
            for event in plan.events] == pytest.approx([10, 10])
    assert plan.segments[0].source.asset_id < "clip-08"
    assert plan.segments[1].source.asset_id >= "clip-08"
    project = tmp_path / "dense-events.memento.json"
    save_movie(project, plan)
    reopened = load_movie(project)
    weighted = service.build(DAY, DAY, 30, "gemini", "test-model",
                             MoviePreferences(event_weights={reopened.events[1].event_id: 3}))
    assert weighted.events == reopened.events
    assert sum(item.duration for item in weighted.segments if item.event_id == weighted.events[1].event_id) == 20
    with library._connection() as db:
        assert [tuple(row) for row in db.execute("SELECT * FROM semantic_cache ORDER BY cache_key")] == cached_before
    plan.validate()
    weighted.validate()


def test_event_weights_change_time_allocation_and_exclusion_survives_regeneration(tmp_path):
    _, _, service = library_with_events(tmp_path)
    initial = service.build(DAY, DAY, 20, "gemini", "test-model")
    preferences = MoviePreferences(event_weights={initial.events[0].event_id: 3})
    plan = service.build(DAY, DAY, 20, "gemini", "test-model", preferences)
    durations = [sum(item.duration for item in plan.segments if item.event_id == event.event_id) for event in plan.events]
    assert durations == pytest.approx([15, 5])
    preferences.excluded.add(plan.segments[0].candidate_id)
    regenerated = service.build(DAY, DAY, 20, "gemini", "test-model", preferences)
    assert not preferences.excluded & {item.candidate_id for item in regenerated.segments}
    assert "Nutzerwunsch" in regenerated.decisions[next(iter(preferences.excluded))]


def test_emotion_matters_and_similar_moments_are_downweighted(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    repo = SemanticRepository(library)
    for index, (description, importance, activities) in enumerate((
        ("Kind lacht mit den Eltern", 1.0, ("Spielen",)),
        ("Kind lacht mit den Eltern", 0.9, ("Spielen",)),
        ("Hund springt durch einen Reifen", 0.75, ("Hundetraining",)),
    )):
        asset = add_asset(library, tmp_path, f"clip-{index}", datetime(2026, 7, 12, 9) + timedelta(minutes=index))
        store_moments(repo, asset, description=description, importance=importance, activities=activities)
    plan = MoviePlanningService(repo).build(DAY, DAY, 20, "gemini", "test-model")
    assert [item.source.asset_id for item in plan.segments] == ["clip-0", "clip-2"]


def test_absolute_ranges_from_chunks_and_mixed_timezones_are_preserved(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    repo = SemanticRepository(library)
    asset = add_asset(library, tmp_path, "long", datetime.fromisoformat("2026-07-12T10:00:00+02:00"), duration=90)
    store_moments(repo, asset, moments=(Moment(5, 9, "Lachen", "Im Garten", (), (), 0.8, 0.9, 1, 0.7, 0.9, ("Lachen",)),))
    asset2 = add_asset(library, tmp_path, "naive", datetime(2026, 7, 12, 11))
    store_moments(repo, asset2)
    candidates, _ = MoviePlanningService(repo).candidates(DAY, DAY, "gemini", "test-model")
    assert [(item.start_seconds, item.end_seconds) for item in candidates[:2]] == [(5, 9), (50, 54)]
    assert candidates[1].recorded_at == asset.capture_time.value + timedelta(seconds=50)
    plan = MoviePlanningService(repo).build(DAY, DAY, 30, "gemini", "test-model")
    assert [item.source.asset_id for item in plan.segments] == ["long", "long", "naive"]


def test_forced_moments_survive_short_target_and_manual_trims_roundtrip(tmp_path):
    _, _, service = library_with_events(tmp_path)
    first = service.build(DAY, DAY, 20, "gemini", "test-model")
    key = first.segments[0].candidate_id
    preferences = MoviePreferences(forced={key}, trims={key: (1, 9)})
    plan = service.build(DAY, DAY, 4, "gemini", "test-model", preferences)
    assert plan.duration == 8
    assert any("überschreiten" in warning for warning in plan.warnings)
    original = deepcopy(plan)
    project = tmp_path / "holiday.memento.json"
    save_movie(project, plan)
    loaded = load_movie(project)
    assert loaded == original
    loaded.segments[0].end_seconds = 7
    save_movie(project, loaded)
    assert load_movie(project).duration == 6
    assert plan.duration == 8


def test_overlap_and_invalid_plan_rejected_without_destroying_saved_project(tmp_path):
    _, _, service = library_with_events(tmp_path)
    plan = service.build(DAY, DAY, 20, "gemini", "test-model")
    project = tmp_path / "movie.memento.json"
    save_movie(project, plan)
    before = project.read_bytes()
    plan.segments[0].end_seconds = float("nan")
    with pytest.raises(ValueError):
        save_movie(project, plan)
    assert project.read_bytes() == before
    assert not list(tmp_path.glob(".memento-plan-*"))


def test_unknown_forced_and_conflicting_preferences_reported(tmp_path):
    _, _, service = library_with_events(tmp_path)
    with pytest.raises(ValueError, match="fehlen"):
        service.build(DAY, DAY, 20, "gemini", "test-model", MoviePreferences(forced={"missing"}))
    with pytest.raises(ValueError, match="gleichzeitig"):
        service.build(DAY, DAY, 20, "gemini", "test-model", MoviePreferences(excluded={"x"}, forced={"x"}))
    with pytest.raises(ValueError, match="Ereignisgewicht"):
        service.build(DAY, DAY, 20, "gemini", "test-model", MoviePreferences(event_weights={"x": float("nan")}))


def test_missing_and_empty_semantic_results_do_not_become_invented_highlights(tmp_path):
    library, repo, service = library_with_events(tmp_path, counts=(1, 0))
    asset = add_asset(library, tmp_path, "unanalyzed", datetime(2026, 7, 12, 13))
    plan = service.build(DAY, DAY, 60, "gemini", "test-model")
    assert all(item.source.asset_id != asset.asset_id for item in plan.segments)
    assert plan.duration == 10
    assert any("nicht vollständig" in warning for warning in plan.warnings)
    with pytest.raises(ValueError, match="Keine gespeicherten Erinnerungen"):
        service.build(DAY, DAY, 60, "gemini", "other-model")


def test_movie_saving_cannot_overwrite_a_video(tmp_path):
    _, _, service = library_with_events(tmp_path)
    plan = service.build(DAY, DAY, 20, "gemini", "test-model")
    target = tmp_path / "other-original.mp4"
    target.write_bytes(b"unrelated original")
    with pytest.raises(ValueError):
        save_movie(target, plan)
    assert target.read_bytes() == b"unrelated original"


def test_planning_can_be_cancelled_without_touching_analysis(tmp_path):
    _, repo, service = library_with_events(tmp_path)
    token = Event()
    token.set()
    with pytest.raises(PlanningCancelled):
        service.build(DAY, DAY, 20, "gemini", "test-model", cancel_token=token)
    assert len(repo.results_for_asset("event-0-0", "gemini", "test-model")) == 1


def test_short_movie_from_many_days_selects_temporal_representatives_not_empty_plan(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    repo = SemanticRepository(library)
    for index in range(20):
        asset = add_asset(library, tmp_path, f"day-{index:02d}", datetime(2026, 7, 12, 10) + timedelta(days=index))
        store_moments(repo, asset, importance=0.5 + index / 40)
    plan = MoviePlanningService(repo).build(DAY, DAY + timedelta(days=19), 12, "gemini", "test-model")
    assert plan.duration == pytest.approx(12)
    assert len(plan.segments) == 2
    chosen = [int(item.source.asset_id.split("-")[1]) for item in plan.segments]
    assert chosen[0] < 10 <= chosen[1]
    assert any("repräsentative Ereignisse" in warning for warning in plan.warnings)


def test_legacy_movie_plan_loads_without_claiming_current_selection_version(tmp_path):
    _, _, service = library_with_events(tmp_path)
    plan = service.build(DAY, DAY, 20, "gemini", "test-model")
    project = tmp_path / "old.memento.json"
    save_movie(project, plan)
    payload = json.loads(project.read_text(encoding="utf-8"))
    payload["format_version"] = 1
    payload["movie"].pop("planner_version")
    payload["movie"].pop("local_analysis_version")
    project.write_text(json.dumps(payload), encoding="utf-8")
    old = load_movie(project)
    assert old.segments == plan.segments
    assert old.planner_version == "legacy-unspecified"
    assert old.local_analysis_version is None
    save_movie(project, old)
    assert json.loads(project.read_text(encoding="utf-8"))["format_version"] == 4


@pytest.mark.parametrize("target,expected", [(30, 30), (50, 50), (80, 50)])
def test_unused_overlap_budget_flows_to_other_events_without_repeating_sources(tmp_path, target, expected):
    library, repo, service = library_with_events(tmp_path, counts=(0, 3))
    asset = add_asset(library, tmp_path, "overlap", datetime(2026, 7, 12, 9), duration=30)
    moments = tuple(Moment(start, start + 10, "Gemeinsam spielen", "Spielen im Garten", (), (),
                           0.8, 0.9, 0.8, 0.8, 0.9, ("Interaktion",)) for start in (0, 10, 20))
    store_moments(repo, asset, moments=moments)
    candidates, _ = service.candidates(DAY, DAY, "gemini", "test-model")
    overlapping = next(item for item in candidates if item.source.asset_id == "overlap" and item.start_seconds == 10)
    preferences = MoviePreferences(trims={overlapping.candidate_id: (0, 10)})
    cached_before = [dict(row) for row in repo.results_for_asset(asset.asset_id, "gemini", "test-model")]

    plan = service.build(DAY, DAY, target, "gemini", "test-model", preferences)

    assert plan.duration == pytest.approx(expected)
    assert len({item.event_id for item in plan.segments}) == 2
    plan.validate()  # Includes source overlap and maximum range validation.
    assert any("überlappt" in decision for decision in plan.decisions.values())
    if target == 80:
        assert any("keine Wiederholungen" in warning for warning in plan.warnings)
    assert [dict(row) for row in repo.results_for_asset(asset.asset_id, "gemini", "test-model")] == cached_before


def test_budget_is_redistributed_after_valuable_overlapping_moment_wins(tmp_path):
    library, repo, service = library_with_events(tmp_path, counts=(0, 3))
    asset = add_asset(library, tmp_path, "reaction", datetime(2026, 7, 12, 9), duration=30)
    moments = tuple(Moment(start, start + 10, "Familienmoment", "Spielen im Garten", (), (),
                           score, score, score, score, 1, ("Reaktion",))
                    for start, score in ((0, 0.2), (10, 0.2), (20, 1.0)))
    store_moments(repo, asset, moments=moments)
    candidates, _ = service.candidates(DAY, DAY, "gemini", "test-model")
    reaction = next(item for item in candidates if item.source.asset_id == "reaction" and item.start_seconds == 20)
    event = next(item for item in cluster_events(candidates) if reaction.candidate_id in item.candidate_ids)
    plan = service.build(DAY, DAY, 40, "gemini", "test-model",
                         MoviePreferences(trims={reaction.candidate_id: (0, 15)}, event_weights={event.event_id: 2}))
    assert plan.duration == pytest.approx(40)
    assert sum(item.duration for item in plan.segments if item.source.asset_id == "reaction") == 15
    assert sum(item.duration for item in plan.segments if item.source.asset_id != "reaction") == 25
    assert sum("überlappt" in decision for decision in plan.decisions.values()) == 2
    plan.validate()


def test_overlapping_cached_ranges_do_not_hide_unanalyzed_source_tail(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    repo = SemanticRepository(library)
    asset = add_asset(library, tmp_path, "partial", datetime(2026, 7, 12, 9), duration=90)
    job = repo.create_job([asset], "gemini", "test-model")
    item = dict(repo.items(job)[0])
    moment = Moment(1, 4, "Familie lacht", "Spielen", (), (), 0.9, 0.9, 0.9, 1, 1, ("Lachen",))
    repo.save_result(repo.get_job(job), item, SemanticResult((moment,)))
    repo.save_result(repo.get_job(job), dict(item, cache_key="legacy-overlap", start_seconds=30, end_seconds=75),
                     SemanticResult((moment,)))
    plan = MoviePlanningService(repo).build(DAY, DAY, 10, "gemini", "test-model")
    assert any("nicht vollständig" in warning for warning in plan.warnings)
    assert all(segment.end_seconds <= 75 for segment in plan.segments)


@pytest.mark.parametrize("base", [datetime(2026, 7, 12, 9), datetime(2026, 7, 12, 23, 59)])
def test_manual_trim_does_not_recluster_events_or_lose_event_weights(tmp_path, base):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    repo = SemanticRepository(library)
    long = add_asset(library, tmp_path, "long", base, duration=1000)
    job = repo.create_job([long], "gemini", "test-model")
    for item in repo.items(job):
        moments = (Moment(0, 10, "Familie spielt", "Spielen", (), (),
            0.8, 0.9, 0.8, 0.8, 0.9, ("Interaktion",)),) if item["start_seconds"] == 900 else ()
        repo.save_result(repo.get_job(job), item, SemanticResult(moments))
    other = add_asset(library, tmp_path, "other", base + timedelta(minutes=10))
    store_moments(repo, other, event="Spielen")
    service = MoviePlanningService(repo)
    end = (base + timedelta(minutes=20)).date()
    first = service.build(DAY, end, 20, "gemini", "test-model")
    assert len(first.events) == 1
    key = next(item.candidate_id for item in first.segments if item.source.asset_id == "long")
    event_id = first.events[0].event_id
    preferences = MoviePreferences(trims={key: (0, 8)}, event_weights={event_id: 3})
    plan = service.build(DAY, end, 20, "gemini", "test-model", preferences)
    assert plan.events == first.events
    assert plan.preferences.event_weights == {event_id: 3}
    assert [item.source.asset_id for item in plan.segments] == ["long", "other"]
    assert (plan.segments[0].start_seconds, plan.segments[0].end_seconds) == (0, 8)
    assert any("über den vorgeschlagenen Moment" in reason for reason in plan.segments[0].reasons)
    preferences.trims[key] = (2, 4)
    assert plan.preferences.trims[key] == (0, 8)  # Plan owns its constraints.


def test_manual_ranges_remain_intact_and_can_borrow_event_budget(tmp_path):
    _, _, service = library_with_events(tmp_path, counts=(1, 1))
    first = service.build(DAY, DAY, 20, "gemini", "test-model")
    keys = [item.candidate_id for item in first.segments]
    preferences = MoviePreferences(trims={key: (1, 9) for key in keys})
    plan = service.build(DAY, DAY, 10, "gemini", "test-model", preferences)
    assert plan.duration == 8  # Neither range is silently cut to its five-second budget.
    assert len(plan.segments) == 1
    assert (plan.segments[0].start_seconds, plan.segments[0].end_seconds) == (1, 9)
    assert any("Manuelle Schnittgrenzen" in reason for reason in plan.segments[0].reasons)
    omitted = (set(keys) - {item.candidate_id for item in plan.segments}).pop()
    assert "nicht vollständig" in plan.decisions[omitted]
    forced = deepcopy(preferences)
    forced.forced = set(keys)
    assert service.build(DAY, DAY, 10, "gemini", "test-model", forced).duration == 16


def test_manual_range_too_long_does_not_block_other_usable_material(tmp_path):
    _, _, service = library_with_events(tmp_path, counts=(1, 1))
    first = service.build(DAY, DAY, 20, "gemini", "test-model")
    key = first.segments[0].candidate_id
    plan = service.build(DAY, DAY, 4, "gemini", "test-model", MoviePreferences(trims={key: (1, 9)}))
    assert plan.duration == 4
    assert all(item.candidate_id != key for item in plan.segments)
    assert "nicht vollständig" in plan.decisions[key]


def test_missing_manual_ranges_are_reported_and_invalid_bounds_rejected(tmp_path):
    _, _, service = library_with_events(tmp_path, counts=(1, 0))
    plan = service.build(DAY, DAY, 10, "gemini", "test-model", MoviePreferences(trims={"stale": (1, 3)}))
    assert any("Schnittvorgaben fehlen" in warning for warning in plan.warnings)
    key = plan.segments[0].candidate_id
    with pytest.raises(ValueError, match="außerhalb"):
        service.build(DAY, DAY, 10, "gemini", "test-model", MoviePreferences(trims={key: (0, 11)}))


def test_explicit_short_manual_ranges_can_fill_a_short_movie(tmp_path):
    _, _, service = library_with_events(tmp_path, counts=(1, 1))
    first = service.build(DAY, DAY, 20, "gemini", "test-model")
    preferences = MoviePreferences(trims={item.candidate_id: (2, 3) for item in first.segments})
    plan = service.build(DAY, DAY, 2, "gemini", "test-model", preferences)
    assert plan.duration == 2
    assert len(plan.segments) == 2
    assert all((item.start_seconds, item.end_seconds) == (2, 3) for item in plan.segments)


def boundary_library(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    repo = SemanticRepository(library)
    for event, duration in ((0, 10), (1, 6)):
        for index, importance in enumerate((0.9, 0.7)):
            asset = add_asset(library, tmp_path, f"event-{event}-{index}",
                datetime(2026, 7, 12, 9 + event * 3) + timedelta(seconds=index * 30), duration)
            store_moments(repo, asset, event=f"Ausflug {event}", importance=importance)
    return library, repo, MoviePlanningService(repo)


def test_small_budget_transfer_preserves_complete_moments_and_improves_reference_coverage(tmp_path):
    library, repo, service = boundary_library(tmp_path)
    cached_before = [dict(row) for asset in library.list_assets() for row in repo.results_for_asset(asset.asset_id, "gemini", "test-model")]
    plan = service.build(DAY, DAY, 16, "gemini", "test-model")
    assert [(item.source.asset_id, item.duration) for item in plan.segments] == [("event-0-0", 10), ("event-1-0", 6)]
    assert any("Zeit zwischen Ereignissen umverteilt" in reason for item in plan.segments for reason in item.reasons)
    assert not any("gekürzt" in reason for item in plan.segments for reason in item.reasons)
    # Independent fixture annotations identify the two required full ranges,
    # including their ends. They are not inferred from the planner's selection.
    expected = [("event-0-0", "Erstes Ereignis", 10), ("event-1-0", "Zweites Ereignis", 6)]
    assets = [library.get_asset(key) for key, _, _ in expected]
    sources = [{"source_id": asset.asset_id, "asset_id": asset.asset_id,
        "content_sha256": asset.content_sha256, "size_bytes": asset.size_bytes,
        "modified_at": asset.modified_at.isoformat(timespec="microseconds"), "duration_seconds": asset.duration_seconds} for asset in assets]
    reference = {"format_version": 1, "reference_id": "synthetic-intact-actions",
        "request": {"date_from": DAY.isoformat(), "date_to": DAY.isoformat(), "target_seconds": 16},
        "sources": sources, "moments": [
            {"moment_id": key, "description": "Vollständiger synthetischer Schlüsselmoment",
             "event": event, "weight": 1, "alternatives": [{"source_id": key,
             "start_seconds": 0, "end_seconds": duration}]} for key, event, duration in expected]}
    report = evaluate_movie(plan, reference, retained_fraction=0.95)
    assert report["weighted_moment_coverage"] == report["weighted_moment_recall"] == 1
    # The former hard-budget selection cut the ten-second action at eight
    # seconds. Keep the same sixteen-second target for the comparison.
    hard_budget = deepcopy(plan)
    hard_budget.planner_version = "synthetic-hard-budget-baseline"
    hard_budget.segments[0].end_seconds = 8
    extra = next(item for item in service.candidates(DAY, DAY, "gemini", "test-model")[0]
                 if item.source.asset_id == "event-1-1")
    hard_budget.segments.append(replace(plan.segments[1], candidate_id=extra.candidate_id,
                                       source=extra.source, end_seconds=2))
    old_report = evaluate_movie(hard_budget, reference, retained_fraction=0.95)
    assert hard_budget.duration == plan.duration == 16
    assert old_report["weighted_moment_coverage"] == pytest.approx(0.9)
    assert old_report["weighted_moment_recall"] == 0.5
    assert [dict(row) for asset in library.list_assets() for row in repo.results_for_asset(asset.asset_id, "gemini", "test-model")] == cached_before


def test_boundary_transfer_does_not_take_large_borrow_or_exceed_target(tmp_path):
    _, _, service = boundary_library(tmp_path)
    short = service.build(DAY, DAY, 12, "gemini", "test-model")
    assert short.duration == 12
    assert len({item.event_id for item in short.segments}) == 2
    assert not any("Zeit zwischen Ereignissen umverteilt" in reason for item in short.segments for reason in item.reasons)
    for target in (8, 14, 16, 18, 20, 24, 30):
        plan = service.build(DAY, DAY, target, "gemini", "test-model")
        assert plan.duration <= target + 1e-6
        plan.validate()


def test_boundary_transfer_keeps_other_events_represented(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    repo = SemanticRepository(library)
    for event in range(10):
        for index in range(2):
            capture = datetime(2026, 7, 12, 9) + timedelta(days=event, seconds=index * 30)
            asset = add_asset(library, tmp_path, f"event-{event}-{index}", capture)
            store_moments(repo, asset, event=f"Ausflug {event}")
    plan = MoviePlanningService(repo).build(DAY, DAY + timedelta(days=9), 80, "gemini", "test-model")
    assert len({item.event_id for item in plan.segments}) == len(plan.events) == 10
    assert all(item.duration >= 2 for item in plan.segments)
    assert plan.duration <= 80 + 1e-6


def test_boundary_transfer_respects_global_allowance(tmp_path, monkeypatch):
    _, _, service = boundary_library(tmp_path)
    monkeypatch.setattr(movie_planning, "MAX_MOVIE_BORROW_FRACTION", 0)
    plan = service.build(DAY, DAY, 16, "gemini", "test-model")
    assert plan.duration == 16
    assert plan.segments[0].duration == 8
    assert not any("Zeit zwischen Ereignissen umverteilt" in reason for item in plan.segments for reason in item.reasons)


def test_boundary_transfer_does_not_exceed_quarter_of_event_budget(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    repo = SemanticRepository(library)
    for event, duration in ((0, 7.6), (1, 6)):
        for index in range(2):
            asset = add_asset(library, tmp_path, f"event-{event}-{index}",
                datetime(2026, 7, 12, 9 + event * 3) + timedelta(seconds=index * 30), duration)
            store_moments(repo, asset, event=f"Ausflug {event}")
    plan = MoviePlanningService(repo).build(DAY, DAY, 12, "gemini", "test-model")
    # The required 1.6s is below the absolute/global ceilings but above 25%
    # of the six-second event allocation. Keep event balance in that case.
    assert plan.duration == 12
    assert plan.segments[0].duration == 6
    assert not any("Zeit zwischen Ereignissen umverteilt" in reason for item in plan.segments for reason in item.reasons)


def test_ordinary_recordings_do_not_dilute_key_memory_and_reference_coverage(tmp_path, monkeypatch):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    repo = SemanticRepository(library)
    service = MoviePlanningService(repo)
    important = []
    for name, hour, description, event in (
        ("birthday-key", 9, "Kind pustet Kerzen aus und die Familie jubelt", "Geburtstagsfeier"),
        ("trip-key", 12, "Gemeinsamer Sprung ins Wasser mit anschließender Reaktion", "Ausflug zum See"),
        ("trip-other", 12, "Weitere Aussicht über den See", "Ausflug zum See"),
    ):
        asset = add_asset(library, tmp_path, name, datetime(2026, 7, 12, hour) + timedelta(seconds=30 if name == "trip-other" else 0))
        store_moments(repo, asset, moments=(Moment(0, 10, description, event, (), (), 1, 1, 1, 1, 1, ()),))
        if name != "trip-other":
            important.append(asset)
    # Independent expected source intervals, fixed before either selection.
    reference = {"format_version": 1, "reference_id": "synthetic-event-dilution",
        "request": {"date_from": DAY.isoformat(), "date_to": DAY.isoformat(), "target_seconds": 20},
        "sources": [{"source_id": asset.asset_id, "asset_id": asset.asset_id,
            "content_sha256": asset.content_sha256, "size_bytes": asset.size_bytes,
            "modified_at": asset.modified_at.isoformat(timespec="microseconds"), "duration_seconds": 10}
            for asset in important],
        "moments": [{"moment_id": asset.asset_id, "description": "Vollständiger unabhängiger Schlüsselmoment",
            "event": event, "weight": 1, "alternatives": [{"source_id": asset.asset_id, "start_seconds": 0, "end_seconds": 10}]}
            for asset, event in zip(important, ("Geburtstag", "Ausflug"))]}
    before = service.build(DAY, DAY, 20, "gemini", "test-model")
    candidates, _ = service.candidates(DAY, DAY, "gemini", "test-model")
    original_budgets = movie_planning.allocate_event_budgets(before.events,
        {item.candidate_id: item for item in candidates}, 20, MoviePreferences())
    for index in range(99):
        asset = add_asset(library, tmp_path, f"ordinary-{index:03}", datetime(2026, 7, 12, 9) + timedelta(seconds=10 + index * 5))
        store_moments(repo, asset, moments=(Moment(0, 10, "Tisch ohne besondere Handlung", "Geburtstagsfeier",
            (), (), 0.02, 0.02, 0.02, 0.02, 1, ()),))
    with library._connection() as db:
        cache_before = [tuple(row) for row in db.execute("SELECT * FROM semantic_cache ORDER BY cache_key")]
    candidates, _ = service.candidates(DAY, DAY, "gemini", "test-model")
    plan = service.build(DAY, DAY, 20, "gemini", "test-model")
    assert [event.event_id for event in plan.events] == [event.event_id for event in before.events]
    new_budgets = movie_planning.allocate_event_budgets(plan.events,
        {item.candidate_id: item for item in candidates}, 20, MoviePreferences())
    assert new_budgets == pytest.approx(original_budgets)
    assert [(item.source.asset_id, item.duration) for item in plan.segments] == [("birthday-key", 10), ("trip-key", 10)]
    report = evaluate_movie(plan, reference, retained_fraction=0.95)
    assert report["weighted_moment_coverage"] == report["weighted_moment_recall"] == report["event_coverage"] == 1
    # Re-run the actual previous averaging rule with the same library and target.
    monkeypatch.setattr(movie_planning, "_event_value", lambda pool: sum(movie_planning._value(item) for item in pool) / len(pool))
    baseline = service.build(DAY, DAY, 20, "gemini", "test-model")
    old_report = evaluate_movie(baseline, reference, retained_fraction=0.95)
    assert old_report["weighted_moment_coverage"] < report["weighted_moment_coverage"]
    assert old_report["weighted_moment_recall"] < 1
    assert baseline.target_seconds == plan.target_seconds == 20
    assert baseline.duration <= 20 and plan.duration == 20
    with library._connection() as db:
        assert [tuple(row) for row in db.execute("SELECT * FROM semantic_cache ORDER BY cache_key")] == cache_before


@pytest.mark.parametrize("kind", ["weak", "duplicate", "excluded_high"])
def test_event_importance_ignores_ineligible_or_redundant_extra_candidates(tmp_path, kind):
    _, _, service = library_with_events(tmp_path)
    candidates, _ = service.candidates(DAY, DAY, "gemini", "test-model")
    events = cluster_events(candidates)
    by_id = {item.candidate_id: item for item in candidates}
    baseline = movie_planning.allocate_event_budgets(events, by_id, 20, MoviePreferences())
    original = candidates[0]
    extra = replace(original, candidate_id="extra-candidate")
    if kind != "duplicate":
        value = 0.01 if kind == "weak" else 1.0
        extra = replace(extra, importance=value, emotion=value, audio=value, uniqueness=value, confidence=value)
    by_id[extra.candidate_id] = extra
    expanded = [replace(events[0], candidate_ids=events[0].candidate_ids + (extra.candidate_id,)), *events[1:]]
    preferences = MoviePreferences(excluded={extra.candidate_id} if kind == "excluded_high" else set())
    assert movie_planning.allocate_event_budgets(expanded, by_id, 20, preferences) == pytest.approx(baseline)
    preferences.event_weights[events[0].event_id] = 2
    weighted = movie_planning.allocate_event_budgets(expanded, by_id, 20, preferences)
    assert weighted[events[0].event_id] == pytest.approx(20 * 2 / 3)
    assert sum(weighted.values()) == pytest.approx(20)
