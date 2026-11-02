"""Actual event coverage from an editable plan, independent of analysis and Qt."""
from __future__ import annotations

from dataclasses import dataclass

from memento.domain.movie import MoviePlan


@dataclass(frozen=True, slots=True)
class EventReview:
    event_id: str
    title: str
    duration_seconds: float
    share: float
    selected_moments: int
    known_moments: int
    excluded_moments: int
    forced_moments: int
    weight: float
    pending_forced: int
    pending_excluded: int
    pending_trims: int

    @property
    def pending(self):
        return self.pending_forced + self.pending_excluded + self.pending_trims


def review_events(plan: MoviePlan) -> tuple[EventReview, ...]:
    """Measure enabled output, not historic decisions or nominal planner budgets.

    A known candidate need not still exist in the library or be usable. Preference
    differences describe the present timeline; they do not claim that a future
    planning run can satisfy conflicting or missing constraints.
    """
    plan.validate()
    selected = {event.event_id: {} for event in plan.events}
    for segment in plan.segments:
        if segment.enabled:
            selected[segment.event_id][segment.candidate_id] = segment
    total = plan.duration
    result = []
    for event in plan.events:
        keys = set(event.candidate_ids)
        included = selected[event.event_id]
        seconds = sum(item.duration for item in included.values())
        preferences = plan.preferences
        forced = keys & preferences.forced
        excluded = keys & preferences.excluded
        pending_trims = sum(
            any(abs(left - right) > 1e-6 for left, right in zip(
                (included[key].start_seconds, included[key].end_seconds), preferences.trims[key]))
            for key in included.keys() & preferences.trims.keys()
        )
        result.append(EventReview(event.event_id, event.title, seconds, seconds / total if total else 0.0,
            len(included), len(keys), len(excluded), len(forced),
            preferences.event_weights.get(event.event_id, 1.0),
            len(forced - included.keys()), len(excluded & included.keys()), pending_trims))
    return tuple(result)
