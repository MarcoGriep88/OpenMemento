"""A 20,000-entry library check; decoding load is intentionally tested separately."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from memento.ai.contracts import ANALYSIS_PROFILE, Moment
from memento.application.movie_planning import MoviePlanningService
from memento.library.database import MediaLibrary
from memento.library.semantic import SemanticRepository


def test_twenty_thousand_cached_assets_plan_with_bounded_database_connections(tmp_path, monkeypatch):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    count = 20_000
    base = datetime(2026, 1, 1, 0, 0)
    modified = "2026-01-01T00:00:00.000000+00:00"
    moment = Moment(0, 10, "Familie spielt miteinander", "Spielen im Garten", ("Spielen",), (), 0.8, 0.9, 0.8, 0.8, 0.9, ("Interaktion",))
    moments_json = json.dumps([moment.to_dict()])
    asset_rows, location_rows, cache_rows = [], [], []
    for index in range(count):
        asset_id = f"asset-{index:05d}"
        path = str(tmp_path / "media" / f"{index:05d}.mp4")
        capture = (base + timedelta(seconds=index * 120)).isoformat()
        asset_rows.append((asset_id, capture, "quicktime", 0.9, 10, modified, modified))
        location_rows.append((asset_id, asset_id, path, path.casefold(), 100, modified, modified))
        cache_rows.append((asset_id, asset_id, "gemini", "test-model", ANALYSIS_PROFILE, 100, modified,
                           0, 10, moments_json, 100, 20, modified))
    with library._connection() as db:
        db.executemany("""INSERT INTO assets(asset_id, capture_time, capture_source, capture_confidence,
            duration_seconds, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)""", asset_rows)
        db.executemany("INSERT INTO locations(location_id, asset_id, path, path_key, size_bytes, modified_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?)", location_rows)
        db.executemany("INSERT INTO semantic_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", cache_rows)
    connections = []
    original_connect = library._connect

    def tracked_connect():
        connections.append(1)
        return original_connect()

    monkeypatch.setattr(library, "_connect", tracked_connect)
    plan = MoviePlanningService(SemanticRepository(library)).build(date(2026, 1, 1), date(2026, 1, 31),
                                                                 600, "gemini", "test-model")
    assert len(plan.decisions) == count
    assert len(plan.events) == 28
    assert len({segment.event_id for segment in plan.segments}) == 28
    assert 560 <= plan.duration <= 600.001
    assert len(connections) <= 3
    plan.validate()
