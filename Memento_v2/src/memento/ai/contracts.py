from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event
from typing import Protocol


SEMANTIC_VERSION = "family-moments-v1"
PROXY_VERSION = "h264-640-12fps-aac-v1"
ANALYSIS_PROFILE = f"{SEMANTIC_VERSION}:{PROXY_VERSION}"
CHUNK_SECONDS = 45.0
MAX_PROXY_BYTES = 8 * 1024 * 1024


class AnalysisCancelled(RuntimeError):
    pass


class ProviderError(RuntimeError):
    """Only sanitized, user-facing messages may cross the provider boundary."""

    def __init__(self, message: str, retryable: bool = False, abort_job: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.abort_job = abort_job


@dataclass(frozen=True, slots=True)
class Moment:
    """A useful source range; scores are uncertain model assessments, not facts."""

    start_seconds: float
    end_seconds: float
    description: str
    event: str
    activities: tuple[str, ...]
    people: tuple[str, ...]
    importance: float
    emotion: float
    audio: float
    uniqueness: float
    confidence: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SemanticResult:
    moments: tuple[Moment, ...]
    input_tokens: int = 0
    output_tokens: int = 0


class AIProvider(Protocol):
    name: str
    model: str

    def analyze(self, video: Path, duration: float, cancel_token: Event) -> SemanticResult: ...


def check_cancelled(token: Event) -> None:
    if token.is_set():
        raise AnalysisCancelled("Analyse abgebrochen.")


def validate_moments(payload: object, duration: float) -> tuple[Moment, ...]:
    """Reject malformed, overlapping and out-of-bounds model ranges before caching."""
    if not isinstance(payload, dict) or set(payload) != {"moments"}:
        raise ValueError("Expected a moments object")
    entries = payload["moments"]
    if not isinstance(entries, list) or len(entries) > 100:
        raise ValueError("Invalid moments list")
    result = []
    fields = set(Moment.__dataclass_fields__)
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != fields:
            raise ValueError("Invalid moment fields")
        values = dict(entry)
        for key in ("start_seconds", "end_seconds", "importance", "emotion", "audio", "uniqueness", "confidence"):
            value = values[key]
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("Invalid number")
            values[key] = float(value)
        if not 0 <= values["start_seconds"] < values["end_seconds"] <= duration:
            raise ValueError("Moment outside video")
        if any(not 0 <= values[key] <= 1 for key in ("importance", "emotion", "audio", "uniqueness", "confidence")):
            raise ValueError("Invalid assessment")
        for key in ("description", "event"):
            if not isinstance(values[key], str) or not values[key].strip() or len(values[key]) > 2000:
                raise ValueError("Invalid description")
        for key in ("activities", "people", "reasons"):
            items = values[key]
            if not isinstance(items, (list, tuple)) or len(items) > 30:
                raise ValueError("Invalid labels")
            if any(not isinstance(item, str) or not item.strip() or len(item) > 500 for item in items):
                raise ValueError("Invalid label")
            values[key] = tuple(items)
        result.append(Moment(**values))
    result.sort(key=lambda item: item.start_seconds)
    if any(a.end_seconds > b.start_seconds for a, b in zip(result, result[1:])):
        raise ValueError("Overlapping moments")
    return tuple(result)


def response_schema() -> dict:
    properties = {
        key: {"type": "number"}
        for key in ("start_seconds", "end_seconds", "importance", "emotion", "audio", "uniqueness", "confidence")
    }
    properties.update({key: {"type": "string"} for key in ("description", "event")})
    properties.update({key: {"type": "array", "items": {"type": "string"}} for key in ("activities", "people", "reasons")})
    return {
        "type": "object", "required": ["moments"],
        "properties": {"moments": {"type": "array", "items": {
            "type": "object", "properties": properties, "required": list(properties),
        }}},
    }
