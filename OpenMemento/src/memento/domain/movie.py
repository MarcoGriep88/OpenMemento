"""Source snapshots and editable movie plans, independent of Qt and AI providers."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from memento.domain.editing import EditingStyle


def finite_number(value, minimum=0.0) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= minimum


@dataclass(frozen=True, slots=True)
class MovieSource:
    asset_id: str
    path: str
    size_bytes: int
    modified_at: str
    duration_seconds: float
    has_audio: bool | None
    width: int | None
    height: int | None
    content_sha256: str | None = None

    def validate(self):
        if not isinstance(self.asset_id, str) or not self.asset_id or not isinstance(self.path, str) or not self.path or not Path(self.path).is_absolute():
            raise ValueError("Ungültige Filmquelle.")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ValueError("Ungültiger Dateistand.")
        datetime.fromisoformat(self.modified_at)
        if self.content_sha256 is not None and (len(self.content_sha256) != 64 or any(value not in "0123456789abcdef" for value in self.content_sha256)):
            raise ValueError("Ungültige Inhaltsidentität.")
        if not finite_number(self.duration_seconds, 0.001):
            raise ValueError("Ungültige Quelldauer.")
        if self.has_audio is not None and type(self.has_audio) is not bool:
            raise ValueError("Ungültige Audioangabe.")
        for value in (self.width, self.height):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError("Ungültige Bildgröße.")


@dataclass(frozen=True, slots=True)
class CandidateSegment:
    candidate_id: str
    source: MovieSource
    start_seconds: float
    end_seconds: float
    recorded_at: datetime
    description: str
    event_label: str
    activities: tuple[str, ...]
    people: tuple[str, ...]
    importance: float
    emotion: float
    audio: float
    uniqueness: float
    confidence: float
    reasons: tuple[str, ...]
    technical_quality: float | None = None
    visual_samples: tuple[tuple[int, tuple[float, ...]], ...] = ()
    # Keep event identity tied to intelligence, independently of timeline edits.
    analysis_recorded_at: datetime | None = None
    analysis_end_at: datetime | None = None

    @property
    def event_chronology(self):
        return ((self.analysis_recorded_at or self.recorded_at).replace(tzinfo=None),
                self.source.asset_id, self.candidate_id)

    @property
    def event_end_time(self):
        # Transient candidates retain their original analyzed interval even if
        # timeline edits move either edge. Legacy/direct candidates use duration.
        end = self.analysis_end_at or (self.analysis_recorded_at or self.recorded_at) + timedelta(seconds=self.duration)
        return end.replace(tzinfo=None)

    @property
    def duration(self):
        return self.end_seconds - self.start_seconds

    @property
    def chronology(self):
        # Date-range selection uses recorded calendar time too. Unknown zones
        # must not be invented; the plan explicitly warns about this convention.
        return self.recorded_at.replace(tzinfo=None), self.source.asset_id, self.start_seconds


@dataclass(frozen=True, slots=True)
class MovieEvent:
    event_id: str
    title: str
    candidate_ids: tuple[str, ...]


@dataclass(slots=True)
class MovieSegment:
    candidate_id: str
    event_id: str
    source: MovieSource
    start_seconds: float
    end_seconds: float
    description: str
    reasons: tuple[str, ...]
    enabled: bool = True

    @property
    def duration(self):
        return self.end_seconds - self.start_seconds

    def validate(self):
        self.source.validate()
        if not isinstance(self.candidate_id, str) or not self.candidate_id or not isinstance(self.event_id, str) or not self.event_id or type(self.enabled) is not bool:
            raise ValueError("Ungültiges Filmelement.")
        if not isinstance(self.description, str) or not isinstance(self.reasons, (tuple, list)) or any(not isinstance(value, str) for value in self.reasons):
            raise ValueError("Ungültige Segmentbeschreibung.")
        if not finite_number(self.start_seconds) or not finite_number(self.end_seconds):
            raise ValueError("Ungültige Schnittgrenzen.")
        if not self.start_seconds < self.end_seconds <= self.source.duration_seconds:
            raise ValueError("Schnittgrenzen liegen außerhalb der Quelle.")


@dataclass(slots=True)
class MoviePreferences:
    excluded: set[str] = field(default_factory=set)
    forced: set[str] = field(default_factory=set)
    event_weights: dict[str, float] = field(default_factory=dict)
    trims: dict[str, tuple[float, float]] = field(default_factory=dict)

    def validate(self):
        if not isinstance(self.excluded, set) or not isinstance(self.forced, set) or any(not isinstance(value, str) for value in self.excluded | self.forced):
            raise ValueError("Ungültige Segmentvorgaben.")
        if self.excluded & self.forced:
            raise ValueError("Ein Segment kann nicht gleichzeitig ausgeschlossen und erzwungen sein.")
        if any(not finite_number(weight, 0.1) or weight > 5 for weight in self.event_weights.values()):
            raise ValueError("Ereignisgewicht muss zwischen 0,1 und 5 liegen.")
        if any(len(bounds) != 2 or not all(finite_number(value) for value in bounds) or bounds[0] >= bounds[1]
               for bounds in self.trims.values()):
            raise ValueError("Ungültige manuelle Schnittgrenzen.")


@dataclass(slots=True)
class MoviePlan:
    plan_id: str
    title: str
    target_seconds: float
    date_from: str
    date_to: str
    provider: str
    model: str
    analysis_profile: str
    events: list[MovieEvent]
    segments: list[MovieSegment]
    preferences: MoviePreferences = field(default_factory=MoviePreferences)
    decisions: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    planner_version: str = "legacy-unspecified"
    local_analysis_version: str | None = None
    editing_style: EditingStyle = field(default_factory=EditingStyle)

    @property
    def playback_duration(self):
        durations = [segment.duration for segment in self.segments if segment.enabled]
        return sum(durations) - sum(self.editing_style.overlaps(durations))

    @property
    def duration(self):
        return sum(segment.duration for segment in self.segments if segment.enabled)

    def validate(self):
        from datetime import date

        if not isinstance(self.plan_id, str) or not self.plan_id or not isinstance(self.title, str) or not self.title.strip() or not finite_number(self.target_seconds, 0.1):
            raise ValueError("Ungültiger Filmplan.")
        if date.fromisoformat(self.date_to) < date.fromisoformat(self.date_from):
            raise ValueError("Ungültiger Filmzeitraum.")
        self.preferences.validate()
        self.editing_style.validate()
        events = {event.event_id: event for event in self.events}
        if len(events) != len(self.events):
            raise ValueError("Doppelte Ereignisse.")
        for event in self.events:
            if (not isinstance(event.event_id, str) or not event.event_id or not isinstance(event.title, str)
                    or not isinstance(event.candidate_ids, (tuple, list))
                    or any(not isinstance(value, str) for value in event.candidate_ids)):
                raise ValueError("Ungültiges Ereignis.")
        if not isinstance(self.warnings, list) or any(not isinstance(value, str) for value in self.warnings):
            raise ValueError("Ungültige Filmhinweise.")
        candidate_ids = set()
        sources = {}
        ranges: dict[str, list[tuple[float, float]]] = {}
        for segment in self.segments:
            segment.validate()
            if segment.candidate_id in candidate_ids:
                raise ValueError("Doppeltes Filmelement.")
            candidate_ids.add(segment.candidate_id)
            if segment.event_id not in events or segment.candidate_id not in events[segment.event_id].candidate_ids:
                raise ValueError("Filmelement gehört zu keinem Ereignis.")
            asset_id = segment.source.asset_id
            if asset_id in sources and sources[asset_id] != segment.source:
                raise ValueError("Widersprüchliche Quellstände im Filmplan.")
            sources[asset_id] = segment.source
            if segment.enabled:
                ranges.setdefault(asset_id, []).append((segment.start_seconds, segment.end_seconds))
        for entries in ranges.values():
            entries.sort()
            if any(left[1] > right[0] + 1e-6 for left, right in zip(entries, entries[1:])):
                raise ValueError("Überlappende Quellbereiche im Filmplan.")
