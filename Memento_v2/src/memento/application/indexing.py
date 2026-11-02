from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Event
from collections.abc import Callable
from uuid import uuid4
import time

from memento.domain.media import (
    AnalysisStatus,
    CaptureTime,
    IndexItemStatus,
    IndexJob,
    IndexJobStatus,
    IndexProgress,
    MediaAsset,
    TimestampSource,
)
from memento.library.database import MediaLibrary
from memento.library.identity import save_verified_asset
from memento.media.identity import hash_media
from memento.media.discovery import discover_videos
from memento.media.metadata import METADATA_VERSION, MediaProbeCancelled, probe_media


class MediaIndexService:
    """Persistent, cancellable local folder indexing with per-file failure isolation."""

    def __init__(self, library: MediaLibrary, probe=probe_media):
        self.library = library
        self.probe = probe

    def create_job(self, roots: list[Path], verify_contents: bool = False) -> IndexJob:
        return self.library.create_index_job(roots, verify_contents)

    def run(
        self,
        job_id: str,
        on_progress: Callable[[IndexProgress], None] | None = None,
        cancel_token: Event | None = None,
    ) -> IndexJobStatus:
        job = self.library.get_index_job(job_id)
        if job is None:
            raise KeyError(f"unknown index job: {job_id}")
        if job.status == IndexJobStatus.COMPLETE:
            raise ValueError("completed index jobs cannot be resumed; create a new job")

        self.library.clear_index_job_errors(job_id)
        self.library.set_index_job_status(job_id, IndexJobStatus.RUNNING)
        self._reset_interrupted_items(job_id)
        try:
            directory_count = 0

            def report_directory(path: Path) -> None:
                nonlocal directory_count
                directory_count += 1
                if on_progress is not None and directory_count % 32 == 1:
                    on_progress(
                        IndexProgress(
                            job_id=job_id,
                            phase="discovering",
                            completed=0,
                            total=None,
                            failed=0,
                            skipped=0,
                            current_path=path,
                        )
                    )

            discovered = discover_videos(
                job.roots,
                cancel_token=cancel_token,
                on_directory=report_directory,
            )
            for issue in discovered.issues:
                self.library.add_index_job_error(
                    job_id, str(issue.path), "discovery", issue.message
                )
            for candidate in discovered.files:
                self.library.queue_index_job_item(
                    job_id,
                    candidate.path,
                    candidate.size_bytes,
                    candidate.modified_at,
                )

            if discovered.cancelled or _is_cancelled(cancel_token):
                self.library.set_index_job_status(job_id, IndexJobStatus.CANCELLED)
                self._emit(job_id, "cancelled", on_progress)
                return IndexJobStatus.CANCELLED

            pending = self.library.list_index_job_items(job_id, IndexItemStatus.PENDING)
            self.library.mark_unseen_locations(job.roots, [candidate.path for candidate in discovered.files])
            total = sum(
                counts
                for status, counts in self.library.index_job_counts(job_id).items()
                if status in {item.value for item in IndexItemStatus}
            )
            for row in pending:
                path = Path(row["path"])
                if _is_cancelled(cancel_token):
                    self.library.set_index_job_status(job_id, IndexJobStatus.CANCELLED)
                    self._emit(job_id, "cancelled", on_progress, total, path)
                    return IndexJobStatus.CANCELLED
                self.library.set_index_job_item(
                    job_id, path, IndexItemStatus.PROCESSING
                )
                try:
                    existing = self.library.get_asset_for_path(path)
                    unchanged = (existing is not None and existing.content_sha256 is not None
                                 and existing.size_bytes == row["size_bytes"]
                                 and existing.modified_at == datetime.fromisoformat(row["modified_at"]))
                    if unchanged and not job.verify_contents and existing.metadata_version == METADATA_VERSION:
                        self.library.touch_location(path)
                        self.library.set_index_job_item(job_id, path, IndexItemStatus.SKIPPED)
                    else:
                        last_report = 0.0

                        def report_hash(read, size):
                            nonlocal last_report
                            now = time.monotonic()
                            if now - last_report >= 0.25 or read == size:
                                last_report = now
                                self._emit(job_id, "hashing", on_progress, total, path, read, size)

                        if unchanged and not job.verify_contents:
                            digest = existing.content_sha256
                            self._emit(job_id, "metadata", on_progress, total, path)
                        else:
                            self._emit(job_id, "hashing", on_progress, total, path)
                            digest = hash_media(path, cancel_token=cancel_token, on_bytes=report_hash)
                        metadata = self.probe(path, cancel_token=cancel_token)
                        if _is_cancelled(cancel_token):
                            raise MediaProbeCancelled("Medienprüfung wurde abgebrochen.")
                        current = path.stat()
                        if (
                            current.st_size != row["size_bytes"]
                            or _datetime_text_from_timestamp(current.st_mtime)
                            != row["modified_at"]
                        ):
                            raise OSError("Datei wurde während des Imports verändert.")
                        capture = metadata.capture_time or CaptureTime(
                            value=_datetime_from_timestamp(current.st_mtime),
                            source=TimestampSource.FILESYSTEM,
                            confidence=0.3,
                            raw_value="filesystem mtime",
                        )
                        asset = MediaAsset(
                            asset_id=existing.asset_id if existing else str(uuid4()),
                            path=path,
                            size_bytes=current.st_size,
                            modified_at=_datetime_from_timestamp(current.st_mtime),
                            capture_time=capture,
                            duration_seconds=metadata.duration_seconds,
                            video_codec=metadata.video_codec,
                            width=metadata.width,
                            height=metadata.height,
                            has_audio=metadata.has_audio,
                            analysis_status=AnalysisStatus.NOT_ANALYZED,
                            content_sha256=digest,
                            metadata_version=METADATA_VERSION,
                        )
                        save_verified_asset(self.library, asset)
                        self.library.set_index_job_item(job_id, path, IndexItemStatus.COMPLETE)
                except MediaProbeCancelled:
                    self.library.set_index_job_item(job_id, path, IndexItemStatus.PENDING)
                    self.library.set_index_job_status(job_id, IndexJobStatus.CANCELLED)
                    self._emit(job_id, "cancelled", on_progress, total, path)
                    return IndexJobStatus.CANCELLED
                except Exception as exc:
                    message = str(exc).strip() or type(exc).__name__
                    self.library.set_index_job_item(
                        job_id, path, IndexItemStatus.FAILED, message
                    )
                    self.library.add_index_job_error(job_id, str(path), "metadata", message)
                self._emit(job_id, "indexing", on_progress, total, path)

            counts = self.library.index_job_counts(job_id)
            if _is_cancelled(cancel_token):
                self.library.set_index_job_status(job_id, IndexJobStatus.CANCELLED)
                self._emit(job_id, "cancelled", on_progress, total)
                return IndexJobStatus.CANCELLED
            has_errors = counts["failed"] > 0 or counts["discovery_errors"] > 0
            final_status = (
                IndexJobStatus.COMPLETE_WITH_ERRORS
                if has_errors
                else IndexJobStatus.COMPLETE
            )
            self.library.set_index_job_status(job_id, final_status)
            self._emit(job_id, "complete", on_progress, total)
            return final_status
        except Exception:
            # Leave a durable running state; the next caller can resume it.
            raise

    def _reset_interrupted_items(self, job_id: str) -> None:
        for row in self.library.list_index_job_items(job_id, IndexItemStatus.PROCESSING):
            self.library.set_index_job_item(
                job_id, Path(row["path"]), IndexItemStatus.PENDING
            )

    def _emit(self, job_id, phase, callback, total=None, current_path=None, current_bytes=None, current_total_bytes=None):
        if callback is None:
            return
        counts = self.library.index_job_counts(job_id)
        completed = counts["complete"] + counts["skipped"]
        callback(
            IndexProgress(
                job_id=job_id,
                phase=phase,
                completed=completed,
                total=total,
                failed=counts["failed"] + counts["discovery_errors"],
                skipped=counts["skipped"],
                current_path=current_path,
                current_bytes=current_bytes,
                current_total_bytes=current_total_bytes,
            )
        )


def _is_cancelled(token: Event | None) -> bool:
    return token is not None and token.is_set()


def _datetime_from_timestamp(timestamp: float):
    return datetime.fromtimestamp(timestamp).astimezone()


def _datetime_text_from_timestamp(timestamp: float) -> str:
    return _datetime_from_timestamp(timestamp).isoformat(timespec="microseconds")


def _datetime_text(value):
    return value.isoformat(timespec="microseconds")
