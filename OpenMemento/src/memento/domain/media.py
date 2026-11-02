from __future__ import annotations

from dataclasses import dataclass, field
import math
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class TimestampSource(StrEnum):
    QUICKTIME = "quicktime"
    CONTAINER = "container"
    EXIF = "exif"
    FILESYSTEM = "filesystem"
    MANUAL = "manual"


class AnalysisStatus(StrEnum):
    NOT_ANALYZED = "not_analyzed"
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


class IndexJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    CANCELLED = "cancelled"
    COMPLETE = "complete"
    COMPLETE_WITH_ERRORS = "complete_with_errors"


class IndexItemStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    SKIPPED = "skipped"
    FAILED = "failed"


class MediaAnalysisJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    CANCELLED = "cancelled"
    COMPLETE = "complete"
    COMPLETE_WITH_ERRORS = "complete_with_errors"


@dataclass(frozen=True, slots=True)
class IndexJob:
    job_id: str
    roots: tuple[Path, ...]
    status: IndexJobStatus
    created_at: datetime
    updated_at: datetime
    verify_contents: bool = False


@dataclass(frozen=True, slots=True)
class MediaAnalysisJob:
    job_id: str
    analysis_version: str
    status: MediaAnalysisJobStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MediaAnalysisProgress:
    job_id: str
    completed: int
    total: int
    failed: int
    skipped: int
    current_path: Path | None = None


@dataclass(frozen=True, slots=True)
class IndexProgress:
    job_id: str
    phase: str
    completed: int
    total: int | None
    failed: int
    skipped: int
    current_path: Path | None = None
    current_bytes: int | None = None
    current_total_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class CaptureTime:
    value: datetime
    source: TimestampSource
    confidence: float
    raw_value: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class MediaAsset:
    """A video and the metadata needed to index it; asset_id is an opaque UUID."""

    asset_id: str
    path: Path
    size_bytes: int
    modified_at: datetime
    capture_time: CaptureTime | None = None
    duration_seconds: float | None = None
    video_codec: str | None = None
    width: int | None = None
    height: int | None = None
    has_audio: bool | None = None
    analysis_status: AnalysisStatus = AnalysisStatus.NOT_ANALYZED
    analysis_version: str | None = None
    content_sha256: str | None = None
    metadata_version: str | None = None

    def __post_init__(self) -> None:
        if not self.asset_id:
            raise ValueError("asset_id must not be empty")
        if self.content_sha256 is not None and (len(self.content_sha256) != 64 or any(character not in "0123456789abcdef" for character in self.content_sha256)):
            raise ValueError("invalid SHA-256 identity")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must not be negative")
        if self.duration_seconds is not None and self.duration_seconds < 0:
            raise ValueError("duration_seconds must not be negative")
        if (self.width is not None and self.width < 0) or (
            self.height is not None and self.height < 0
        ):
            raise ValueError("video dimensions must not be negative")


@dataclass(frozen=True, slots=True)
class Shot:
    shot_id: str
    asset_id: str
    start_seconds: float
    end_seconds: float
    local_features: dict[str, float] = field(default_factory=dict)
    thumbnail_path: str | None = None

    def __post_init__(self) -> None:
        if not self.shot_id or not self.asset_id:
            raise ValueError("shot_id and asset_id must not be empty")
        if self.start_seconds < 0 or self.end_seconds <= self.start_seconds:
            raise ValueError("shot must have a positive range starting at zero or later")


@dataclass(frozen=True, slots=True)
class AnalysisRecord:
    asset_id: str
    stage: str
    version: str
    status: AnalysisStatus
    provider: str | None = None
    model: str | None = None
    completed_at: datetime | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class LocalFeatureWindow:
    asset_id: str
    start_seconds: float
    end_seconds: float
    features: dict[str, float]

    def __post_init__(self):
        if not self.asset_id or not math.isfinite(self.start_seconds) or not math.isfinite(self.end_seconds) or not 0 <= self.start_seconds < self.end_seconds:
            raise ValueError("Invalid local analysis range")
        if any(not isinstance(key, str) or type(value) not in (float, int) or not math.isfinite(value) for key, value in self.features.items()):
            raise ValueError("Invalid local feature value")
