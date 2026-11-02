from __future__ import annotations

import math
import os
import shutil
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from uuid import uuid4

import cv2
import numpy as np

from memento.domain.media import (
    AnalysisRecord,
    AnalysisStatus,
    IndexItemStatus,
    MediaAnalysisJob,
    MediaAnalysisJobStatus,
    MediaAnalysisProgress,
    Shot,
    LocalFeatureWindow,
)
from memento.library.database import MediaLibrary, default_database_path
from memento.media.local_features import FrameFeatureAnalyzer, LOCAL_ANALYSIS_VERSION


SHOT_ANALYSIS_VERSION = LOCAL_ANALYSIS_VERSION
SAMPLE_INTERVAL_SECONDS = 0.5
CUT_THRESHOLD = 0.62
MIN_SHOT_SECONDS = 1.0
THUMBNAIL_MAX_EDGE = 320


class ShotAnalysisCancelled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LocalAnalysisResult:
    shots: list[Shot]
    windows: list[LocalFeatureWindow]


class ShotAnalysisService:
    """Find coarse shot boundaries and cache one local thumbnail per shot."""

    def __init__(
        self,
        library: MediaLibrary,
        cache_root: Path | None = None,
        analysis_version: str = SHOT_ANALYSIS_VERSION,
    ):
        self.library = library
        self.cache_root = cache_root or _default_cache_root()
        self.analysis_version = analysis_version

    def create_job(self, asset_ids=None) -> MediaAnalysisJob:
        return self.library.create_media_analysis_job(self.analysis_version, asset_ids)

    def run(self, job_id: str, cancel_token: Event | None = None, on_progress=None):
        job = self.library.get_media_analysis_job(job_id)
        if job is None:
            raise KeyError(f"unknown media analysis job: {job_id}")
        if job.analysis_version != self.analysis_version:
            self.library.reset_media_analysis_job_version(job_id, self.analysis_version)
        self.library.set_media_analysis_job_status(job_id, MediaAnalysisJobStatus.RUNNING)

        # Processing items from a previous process lifetime were interrupted.
        for item in self.library.list_media_analysis_job_items(job_id, IndexItemStatus.PROCESSING):
            self.library.set_media_analysis_job_item(job_id, item["asset_id"], IndexItemStatus.PENDING)
        for item in self.library.list_media_analysis_job_items(job_id, IndexItemStatus.FAILED):
            self.library.set_media_analysis_job_item(job_id, item["asset_id"], IndexItemStatus.PENDING)
            self.library.clear_media_analysis_job_errors(job_id, item["asset_id"])

        items = self.library.list_media_analysis_job_items(job_id, IndexItemStatus.PENDING)
        total = len(self.library.list_media_analysis_job_items(job_id))
        counts = self.library.media_analysis_job_counts(job_id)
        completed = counts["complete"] + counts["skipped"] + counts["failed"]
        self._emit(job_id, completed, total, counts, None, on_progress)

        for item in items:
            if _is_cancelled(cancel_token):
                self.library.set_media_analysis_job_status(job_id, MediaAnalysisJobStatus.CANCELLED)
                return MediaAnalysisJobStatus.CANCELLED
            asset_id = item["asset_id"]
            path = Path(item["path"])
            self.library.set_media_analysis_job_item(job_id, asset_id, IndexItemStatus.PROCESSING)
            try:
                asset = self.library.get_asset(asset_id)
                if asset is None:
                    raise FileNotFoundError("Indexed media asset no longer exists")
                path = asset.path
                current = path.stat()
                if current.st_size != asset.size_bytes or datetime.fromtimestamp(current.st_mtime).astimezone() != asset.modified_at:
                    raise OSError("Source file changed since it was indexed")
                cached = asset.analysis_status == AnalysisStatus.COMPLETE and asset.analysis_version == self.analysis_version
                if cached:
                    shots = self.library.list_shots(asset_id)
                    cache_root = self.cache_root.resolve()
                    cached = bool(shots) and all(
                        shot.thumbnail_path is not None
                        and (cache_root / shot.thumbnail_path).resolve().is_relative_to(cache_root)
                        and (cache_root / shot.thumbnail_path).is_file() for shot in shots
                    )
                if cached:
                    self.library.set_media_analysis_job_item(job_id, asset_id, IndexItemStatus.SKIPPED)
                else:
                    self.library.set_asset_analysis_state(asset_id, AnalysisStatus.PENDING, self.analysis_version)
                    result = self._analyze_asset(
                        asset_id,
                        path,
                        asset.duration_seconds,
                        cancel_token,
                        asset.size_bytes,
                        asset.modified_at,
                    )
                    self._commit_asset_shots(asset_id, result)
                    self.library.set_media_analysis_job_item(job_id, asset_id, IndexItemStatus.COMPLETE)
            except ShotAnalysisCancelled:
                self.library.set_asset_analysis_state(asset_id, AnalysisStatus.NOT_ANALYZED, None)
                self.library.set_media_analysis_job_item(job_id, asset_id, IndexItemStatus.PENDING)
                self.library.set_media_analysis_job_status(job_id, MediaAnalysisJobStatus.CANCELLED)
                return MediaAnalysisJobStatus.CANCELLED
            except Exception as exc:
                message = str(exc).strip() or type(exc).__name__
                self.library.set_asset_analysis_state(asset_id, AnalysisStatus.FAILED, self.analysis_version)
                self.library.save_analysis_record(
                    AnalysisRecord(
                        asset_id=asset_id,
                        stage="shot_detection",
                        version=self.analysis_version,
                        status=AnalysisStatus.FAILED,
                        error=message,
                    )
                )
                self.library.set_media_analysis_job_item(job_id, asset_id, IndexItemStatus.FAILED, message)
                self.library.add_media_analysis_job_error(job_id, asset_id, str(path), message)
            counts = self.library.media_analysis_job_counts(job_id)
            completed = counts["complete"] + counts["skipped"] + counts["failed"]
            self._emit(job_id, completed, total, counts, path, on_progress)

        counts = self.library.media_analysis_job_counts(job_id)
        status = (
            MediaAnalysisJobStatus.COMPLETE_WITH_ERRORS
            if counts["failed"]
            else MediaAnalysisJobStatus.COMPLETE
        )
        self.library.set_media_analysis_job_status(job_id, status)
        self._emit(job_id, total, total, counts, None, on_progress)
        return status

    def _analyze_asset(
        self,
        asset_id: str,
        path: Path,
        duration: float | None,
        cancel_token,
        expected_size: int,
        expected_modified_at: datetime,
    ):
        if not path.is_file():
            raise FileNotFoundError(f"Media file not found: {path}")
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            capture.release()
            raise ValueError("OpenCV could not open this video")
        try:
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
            frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            source_duration = duration or (frame_count / fps if fps > 0 and frame_count > 0 else None)
            if not source_duration or not math.isfinite(source_duration) or source_duration <= 0:
                raise ValueError("Video duration is unavailable")
            previous_sample: tuple[float, np.ndarray] | None = None
            cut_points: list[tuple[float, float]] = []
            target = 0.0
            last_position = -1.0
            last_cut = 0.0
            sample_count = 0
            measurements = []
            feature_analyzer = FrameFeatureAnalyzer()
            timebase_reliable = True
            while target < source_duration:
                if _is_cancelled(cancel_token):
                    raise ShotAnalysisCancelled("Analysis cancelled")
                capture.set(cv2.CAP_PROP_POS_MSEC, target * 1000.0)
                ok, frame = capture.read()
                if not ok or frame is None:
                    # Metadata and the final decodable frame can differ slightly.
                    # An earlier failure must not certify the unobserved tail as
                    # a successful analysis (or silently hide a damaged source).
                    if source_duration - target > SAMPLE_INTERVAL_SECONDS + 1e-6:
                        raise ValueError(f"Lokale Bildanalyse bei {target:.2f} s abgebrochen: "
                                         "Bild konnte nicht decodiert werden. Quelle oder Decoder prüfen und Analyse fortsetzen.")
                    break
                reported = float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
                if (not math.isfinite(reported) or reported < 0 or reported >= source_duration
                        or reported <= last_position or (reported == 0.0 and target > 0)):
                    position = target
                    timebase_reliable = False
                else:
                    position = reported
                if previous_sample is not None and position <= previous_sample[0]:
                    target += SAMPLE_INTERVAL_SECONDS
                    continue
                resized = cv2.resize(frame, (64, 36), interpolation=cv2.INTER_AREA)
                hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
                histogram = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256])
                cv2.normalize(histogram, histogram, alpha=1, norm_type=cv2.NORM_L1)
                position = min(position, source_duration)
                is_cut = False
                if previous_sample is not None:
                    distance = float(
                        cv2.compareHist(previous_sample[1], histogram, cv2.HISTCMP_BHATTACHARYYA)
                    )
                    # The current sample is the first observed frame from the new shot;
                    # use its presentation timestamp as a conservative cut boundary.
                    boundary = position
                    is_cut = distance >= CUT_THRESHOLD
                    if is_cut and boundary - last_cut >= MIN_SHOT_SECONDS - 1e-3:
                        cut_points.append((boundary, distance))
                        last_cut = boundary
                if position < source_duration:
                    measurements.append((position, feature_analyzer.measure(frame, reset_motion=is_cut)))
                previous_sample = (position, histogram)
                sample_count += 1
                last_position = position
                target += SAMPLE_INTERVAL_SECONDS
        finally:
            capture.release()

        if sample_count == 0:
            raise ValueError("No decodable video frames found")
        windows = []
        for index, (position, features) in enumerate(measurements):
            following = measurements[index + 1][0] if index + 1 < len(measurements) else source_duration
            end = min(following, position + SAMPLE_INTERVAL_SECONDS, source_duration)
            if end > position:
                features["timebase_reliable"] = 1.0 if timebase_reliable else 0.0
                windows.append(LocalFeatureWindow(asset_id, position, end, features))

        boundaries = [0.0] + [point for point, _ in cut_points] + [float(source_duration)]
        distances = [distance for _, distance in cut_points]
        generation = uuid4().hex
        pending_dir, final_dir = self._thumbnail_dirs(asset_id, generation)
        if pending_dir.exists():
            shutil.rmtree(pending_dir)
        pending_dir.mkdir(parents=True, exist_ok=True)
        shots: list[Shot] = []
        try:
            thumb_capture = cv2.VideoCapture(str(path))
            try:
                if not thumb_capture.isOpened():
                    raise ValueError("Could not reopen video for thumbnails")
                for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
                    if end - start < 0.05:
                        continue
                    if _is_cancelled(cancel_token):
                        raise ShotAnalysisCancelled("Analysis cancelled")
                    midpoint = (start + end) / 2
                    thumb_capture.set(cv2.CAP_PROP_POS_MSEC, midpoint * 1000.0)
                    ok, frame = thumb_capture.read()
                    if not ok:
                        raise ValueError(f"Could not decode representative frame for shot {index + 1}")
                    height, width = frame.shape[:2]
                    scale = min(1.0, THUMBNAIL_MAX_EDGE / max(height, width))
                    if scale < 1:
                        frame = cv2.resize(
                            frame,
                            (max(1, round(width * scale)), max(1, round(height * scale))),
                            interpolation=cv2.INTER_AREA,
                        )
                    filename = f"{index + 1:05d}.jpg"
                    if not cv2.imwrite(str(pending_dir / filename), frame, [cv2.IMWRITE_JPEG_QUALITY, 85]):
                        raise OSError("Could not write shot thumbnail")
                    features = {
                        "cut_detection_version": 1.0,
                        "timebase_reliable": 1.0 if timebase_reliable else 0.0,
                        "cut_strength": distances[index - 1] if 0 < index <= len(distances) else 0.0,
                    }
                    shots.append(
                        Shot(
                            shot_id=str(uuid4()),
                            asset_id=asset_id,
                            start_seconds=start,
                            end_seconds=end,
                            local_features=features,
                            thumbnail_path=(Path("thumbnails") / asset_id / generation / filename).as_posix(),
                        )
                    )
            finally:
                thumb_capture.release()
            current = path.stat()
            if (
                current.st_size != expected_size
                or datetime.fromtimestamp(current.st_mtime).astimezone() != expected_modified_at
            ):
                raise OSError("Source file changed during shot analysis")
            os.replace(pending_dir, final_dir)
            return LocalAnalysisResult(shots, windows)
        except Exception:
            if pending_dir.exists():
                shutil.rmtree(pending_dir, ignore_errors=True)
            raise

    def _thumbnail_dirs(self, asset_id: str, generation: str):
        root = self.cache_root / "thumbnails"
        root.mkdir(parents=True, exist_ok=True)
        return (
            root / asset_id / f".{generation}.pending",
            root / asset_id / generation,
        )

    def _commit_asset_shots(self, asset_id: str, result: LocalAnalysisResult):
        shots = result.shots
        relative = Path(shots[0].thumbnail_path) if shots else None
        generation = relative.parts[2] if relative is not None and len(relative.parts) >= 4 else None
        new_dir = self.cache_root / "thumbnails" / asset_id / generation if generation else None
        try:
            self.library.save_shots(asset_id, shots, windows=result.windows, analysis_version=self.analysis_version)
        except Exception:
            if new_dir is not None:
                shutil.rmtree(new_dir, ignore_errors=True)
            raise
        asset_dir = self.cache_root / "thumbnails" / asset_id
        if asset_dir.is_dir():
            for child in asset_dir.iterdir():
                if child.is_dir() and child.name != generation:
                    shutil.rmtree(child, ignore_errors=True)

    def _emit(self, job_id, completed, total, counts, path, callback):
        if callback:
            callback(
                MediaAnalysisProgress(
                    job_id=job_id,
                    completed=completed,
                    total=total,
                    failed=counts["failed"],
                    skipped=counts["skipped"],
                    current_path=path,
                )
            )


def _default_cache_root() -> Path:
    return default_database_path().parent / "cache"


def _is_cancelled(token) -> bool:
    return token is not None and token.is_set()
