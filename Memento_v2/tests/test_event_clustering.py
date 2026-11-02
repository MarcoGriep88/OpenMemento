from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from memento.application.movie_planning import cluster_events
from memento.domain.movie import CandidateSegment, MovieSource


@pytest.fixture
def candidate(tmp_path):
    def make(name, start, duration=10, label="Spielen im Garten"):
        timestamp = datetime(2026, 7, 12, 10) + timedelta(seconds=start)
        source = MovieSource(name, str((tmp_path / f"{name}.mp4").resolve()), 100,
                             "2026-07-12T10:00:00", 10000, True, 96, 64)
        return CandidateSegment(name, source, 0, duration, timestamp, label, label,
            (), (), 0.8, 0.8, 0.8, 0.8, 0.9, (), analysis_recorded_at=timestamp,
            analysis_end_at=timestamp + timedelta(seconds=duration))
    return make


@pytest.mark.parametrize("next_start,expected", [(5460, 1), (5460.001, 2)])
def test_long_gap_threshold_is_measured_after_previous_range_ends(candidate, next_start, expected):
    events = cluster_events([candidate("first", 0, 60), candidate("next", next_start)])
    assert len(events) == expected


@pytest.mark.parametrize("next_start,expected", [(660, 1), (660.001, 2)])
def test_semantic_change_threshold_uses_actual_uncovered_time(candidate, next_start, expected):
    events = cluster_events([candidate("first", 0, 60), candidate("next", next_start, label="Bootsfahrt auf See")])
    assert len(events) == expected


def test_overlapping_short_camera_angle_does_not_hide_longer_coverage(candidate):
    ranges = [candidate("long", 0, 60), candidate("short", 30, 10),
              candidate("next", 650, label="Bootsfahrt auf See")]
    events = cluster_events(list(reversed(ranges)))
    assert len(events) == 1
    assert events[0].candidate_ids == ("long", "short", "next")
    ranges.append(candidate("later", 1271, label="Geburtstagsfeier"))
    assert len(cluster_events(ranges)) == 2


def test_manual_edges_do_not_bridge_or_create_event_gaps(candidate):
    first = candidate("first", 0, 60)
    next_one = candidate("next", 661, label="Bootsfahrt auf See")
    original = cluster_events([first, next_one])
    assert len(original) == 2
    extended = replace(first, end_seconds=1200)
    assert cluster_events([extended, next_one]) == original
    moved = replace(first, start_seconds=50, end_seconds=52, recorded_at=first.recorded_at + timedelta(seconds=50))
    assert cluster_events([moved, next_one]) == original


def test_legacy_candidates_and_mixed_zones_follow_recorded_wall_time(candidate):
    first = candidate("first", 0, 60)
    first = replace(first, analysis_recorded_at=None, analysis_end_at=None,
                    recorded_at=first.recorded_at.replace(tzinfo=timezone.utc))
    second = candidate("next", 650, label="Bootsfahrt auf See")
    assert len(cluster_events([second, first])) == 1


def test_daily_grouping_remains_explicit_even_when_an_interval_crosses_midnight(candidate):
    first = candidate("first", 14 * 3600 - 30, 60)
    second = candidate("next", 14 * 3600 + 10)
    assert len(cluster_events([first, second])) == 2


def dense_activities(candidate):
    return [candidate("garden-1", 0), candidate("garden-2", 60),
            candidate("boat-1", 120, label="Bootsfahrt auf See"),
            candidate("boat-2", 180, label="Bootsfahrt auf See")]


def test_confirmed_dense_activity_change_gets_separate_event(candidate):
    ranges = dense_activities(candidate)
    events = cluster_events(list(reversed(ranges)))
    assert [event.candidate_ids for event in events] == [
        ("garden-1", "garden-2"), ("boat-1", "boat-2")]
    assert [event.title for event in events] == ["Spielen im Garten", "Bootsfahrt auf See"]
    # User edits must not affect context, event identity or subsequent weights.
    edited = [replace(item, start_seconds=2, end_seconds=3,
                      recorded_at=item.recorded_at + timedelta(seconds=2)) for item in ranges]
    assert cluster_events(edited) == events


@pytest.mark.parametrize("change", ["single", "uncertain", "same_source", "generic", "far_confirmation", "overlap", "brief_gap"])
def test_dense_boundary_requires_independent_local_nonoverlapping_confirmation(candidate, change):
    ranges = dense_activities(candidate)
    if change == "single":
        ranges.pop()
    elif change == "uncertain":
        ranges[-1] = replace(ranges[-1], confidence=0.4)
    elif change == "same_source":
        ranges[-1] = replace(ranges[-1], source=ranges[-2].source)
    elif change == "generic":
        ranges[-2:] = [replace(item, event_label="Familie") for item in ranges[-2:]]
    elif change == "far_confirmation":
        ranges[-1] = candidate("boat-2", 731, label="Bootsfahrt auf See")
    elif change == "overlap":
        ranges[0] = candidate("garden-1", 0, 160)
    elif change == "brief_gap":
        ranges[-2] = candidate("boat-1", 90, label="Bootsfahrt auf See")
    assert len(cluster_events(ranges)) == 1


def test_shared_activity_context_prevents_label_only_split(candidate):
    ranges = [replace(item, activities=("Sandburgen bauen",)) for item in dense_activities(candidate)]
    assert len(cluster_events(ranges)) == 1


def test_single_reaction_and_parallel_cameras_remain_in_event(candidate):
    ranges = [candidate("garden-1", 0), candidate("garden-2", 60),
              candidate("reaction", 120, label="Kind lacht laut"),
              candidate("garden-3", 180), candidate("garden-4", 240)]
    assert len(cluster_events(ranges)) == 1
    ranges = dense_activities(candidate)
    ranges[1] = candidate("garden-2", 60, 100)
    assert len(cluster_events(ranges)) == 1


def test_activity_wording_can_corroborate_different_free_form_labels(candidate):
    ranges = dense_activities(candidate)
    ranges[0] = replace(ranges[0], event_label="Garten", activities=("Ball spielen",))
    ranges[1] = replace(ranges[1], event_label="Ball", activities=("Garten spielen",))
    assert len(cluster_events(ranges)) == 2
