"""Local upload ranges: preserve paid coverage and favor known shot boundaries."""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right

from memento.ai.contracts import CHUNK_SECONDS


MAX_CHUNK_SECONDS = 60.0
BOUNDARY_SEARCH_SECONDS = 10.0
MIN_TAIL_SECONDS = 6.0


def uncovered_ranges(duration, covered):
    """Union coverage, including empty semantic responses and legacy overlaps."""
    cursor = 0.0
    gaps = []
    for start, end in sorted(set(covered)):
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= duration):
            raise ValueError("Gespeicherter Analysebereich liegt außerhalb der Quelle.")
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration:
        gaps.append((cursor, duration))
    return gaps


def split_analysis_range(start, end, boundaries=()):
    """Keep the nominal request count; a nearby cut may shift a boundary ±10s.

    Unbroken shots can still exceed the maximum upload context. No claim of
    action/speech detection is made here; these are local visual shot changes.
    """
    if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
        raise ValueError("Ungültiger Analysebereich.")
    cuts = sorted({value for value in boundaries if math.isfinite(value) and start < value < end})
    remaining = math.ceil((end - start) / CHUNK_SECONDS)
    result = []
    while remaining > 1:
        desired = start + CHUNK_SECONDS
        minimum = max(start + MIN_TAIL_SECONDS, end - (remaining - 1) * MAX_CHUNK_SECONDS)
        maximum = min(start + MAX_CHUNK_SECONDS, end - (remaining - 1) * MIN_TAIL_SECONDS)
        nearby = cuts[bisect_left(cuts, max(minimum, desired - BOUNDARY_SEARCH_SECONDS)):
                      bisect_right(cuts, min(maximum, desired + BOUNDARY_SEARCH_SECONDS))]
        boundary = min(nearby, key=lambda value: (abs(value - desired), value)) if nearby else min(maximum, max(minimum, desired))
        result.append((start, boundary))
        start = boundary
        remaining -= 1
    result.append((start, end))
    return result
