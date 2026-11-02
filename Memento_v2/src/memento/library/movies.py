"""Versioned, atomic movie project files; editing never writes analysis results."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from memento.domain.movie import MovieEvent, MoviePlan, MoviePreferences, MovieSegment, MovieSource
from memento.domain.editing import EditingStyle


MOVIE_FORMAT_VERSION = 4


def save_movie(path: Path, plan: MoviePlan):
    plan.validate()
    payload = asdict(plan)
    payload["preferences"]["excluded"] = sorted(plan.preferences.excluded)
    payload["preferences"]["forced"] = sorted(plan.preferences.forced)
    target = Path(path).resolve()
    if not target.name.endswith(".memento.json"):
        raise ValueError("Filmpläne müssen die Dateiendung .memento.json haben.")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Protect originals even when a caller supplies an unusual filename.
    if any(target == Path(item.source.path).resolve() for item in plan.segments):
        raise ValueError("Ein Filmplan darf keine Quelldatei überschreiben.")
    descriptor, name = tempfile.mkstemp(prefix=".memento-plan-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"format_version": MOVIE_FORMAT_VERSION, "movie": payload}, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)


def load_movie(path: Path) -> MoviePlan:
    with Path(path).open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict) or payload.get("format_version") not in (1, 2, 3, MOVIE_FORMAT_VERSION):
        raise ValueError("Dieses Filmprojekt hat eine nicht unterstützte Formatversion.")
    data = payload["movie"]
    values = dict(data["preferences"])
    values["excluded"] = set(values["excluded"])
    values["forced"] = set(values["forced"])
    values["trims"] = {key: tuple(bounds) for key, bounds in values["trims"].items()}
    events = [MovieEvent(item["event_id"], item["title"], tuple(item["candidate_ids"])) for item in data["events"]]
    segments = []
    for item in data["segments"]:
        item = dict(item)
        item["source"] = MovieSource(**item["source"])
        item["reasons"] = tuple(item["reasons"])
        segments.append(MovieSegment(**item))
    plan = MoviePlan(**{**data, "events": events, "segments": segments, "preferences": MoviePreferences(**values),
                        "editing_style": EditingStyle(**data.get("editing_style", {}))})
    plan.validate()
    return plan
