from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from memento.domain.media import (
    AnalysisStatus,
    AnalysisRecord,
    CaptureTime,
    IndexItemStatus,
    IndexJob,
    IndexJobStatus,
    MediaAnalysisJob,
    MediaAnalysisJobStatus,
    MediaAnalysisProgress,
    MediaAsset,
    LocalFeatureWindow,
    Shot,
    TimestampSource,
)


_SCHEMA_VERSION = 7


@dataclass(frozen=True, slots=True)
class FolderStats:
    video_count: int
    first_capture_date: str | None
    last_capture_date: str | None


@dataclass(frozen=True, slots=True)
class CaptureDatePage:
    assets: tuple[MediaAsset, ...]
    total: int
    unknown: int
    offset: int


def default_database_path() -> Path:
    """Return isolated v2 application data; never adopt the original library."""
    import os
    import sys

    configured = os.environ.get("MEMENTO_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve() / "library.sqlite3"
    if sys.platform != "win32":
        if sys.platform == "darwin":
            root = Path.home() / "Library" / "Application Support"
        else:
            configured_root = Path(os.environ.get("XDG_DATA_HOME", ""))
            root = configured_root if configured_root.is_absolute() else Path.home() / ".local" / "share"
        target = root / "Memento_v2" / "library.sqlite3"
        return target
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "Memento_v2" / "library.sqlite3"


class MediaLibrary:
    """Small SQLite repository. Connections are short-lived and safe per operation."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else default_database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        db = self._connect()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _initialize(self) -> None:
        with self._connection() as db:
            db.execute("PRAGMA journal_mode = WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > _SCHEMA_VERSION:
                raise RuntimeError(
                    f"Library schema {version} is newer than supported schema {_SCHEMA_VERSION}"
            )
            if 0 < version < _SCHEMA_VERSION:
                self._backup_before_migration(db, version)
            if version == 0:
                db.execute("BEGIN IMMEDIATE")
                for statement in (
                    """CREATE TABLE assets (
                        asset_id TEXT PRIMARY KEY,
                        capture_time TEXT,
                        capture_source TEXT,
                        capture_confidence REAL,
                        capture_raw_value TEXT,
                        duration_seconds REAL,
                        video_codec TEXT,
                        width INTEGER,
                        height INTEGER,
                        has_audio INTEGER,
                        analysis_status TEXT NOT NULL DEFAULT 'not_analyzed',
                        analysis_version TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )""",
                    """CREATE TABLE locations (
                        location_id TEXT PRIMARY KEY,
                        asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
                        path TEXT NOT NULL UNIQUE,
                        path_key TEXT NOT NULL UNIQUE,
                        size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                        modified_at TEXT NOT NULL,
                        last_seen_at TEXT NOT NULL
                    )""",
                    "CREATE INDEX idx_locations_asset ON locations(asset_id)",
                    """CREATE TABLE shots (
                        shot_id TEXT PRIMARY KEY,
                        asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
                        start_seconds REAL NOT NULL CHECK(start_seconds >= 0),
                        end_seconds REAL NOT NULL CHECK(end_seconds > start_seconds),
                        local_features_json TEXT NOT NULL DEFAULT '{}'
                    )""",
                    "CREATE INDEX idx_shots_asset_start ON shots(asset_id, start_seconds)",
                    """CREATE TABLE analysis_runs (
                        run_id TEXT PRIMARY KEY,
                        asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
                        stage TEXT NOT NULL,
                        version TEXT NOT NULL,
                        status TEXT NOT NULL,
                        provider TEXT,
                        model TEXT,
                        completed_at TEXT,
                        error TEXT,
                        UNIQUE(asset_id, stage, version)
                    )""",
                    """CREATE TABLE schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    )""",
                ):
                    db.execute(statement)
                now = _datetime_text(datetime.now().astimezone())
                db.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (1, now),
                )
                db.execute("PRAGMA user_version = 1")
                version = 1
            if version < 2:
                if not db.in_transaction:
                    db.execute("BEGIN IMMEDIATE")
                for statement in (
                    """CREATE TABLE index_jobs (
                        job_id TEXT PRIMARY KEY,
                        roots_json TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )""",
                    """CREATE TABLE index_job_items (
                        job_id TEXT NOT NULL REFERENCES index_jobs(job_id) ON DELETE CASCADE,
                        path TEXT NOT NULL,
                        path_key TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                        modified_at TEXT NOT NULL,
                        status TEXT NOT NULL,
                        error TEXT,
                        PRIMARY KEY(job_id, path_key)
                    )""",
                    "CREATE INDEX idx_index_job_items_status ON index_job_items(job_id, status)",
                    """CREATE TABLE index_job_errors (
                        error_id TEXT PRIMARY KEY,
                        job_id TEXT NOT NULL REFERENCES index_jobs(job_id) ON DELETE CASCADE,
                        path TEXT NOT NULL,
                        stage TEXT NOT NULL,
                        message TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )""",
                    "CREATE INDEX idx_index_job_errors_job ON index_job_errors(job_id)",
                ):
                    db.execute(statement)
                db.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (2, _datetime_text(datetime.now().astimezone())),
                )
                db.execute("PRAGMA user_version = 2")
                version = 2
            if version < 3:
                if not db.in_transaction:
                    db.execute("BEGIN IMMEDIATE")
                db.execute("ALTER TABLE shots ADD COLUMN thumbnail_path TEXT")
                for statement in (
                    """CREATE TABLE media_analysis_jobs (
                        job_id TEXT PRIMARY KEY,
                        analysis_version TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )""",
                    """CREATE TABLE media_analysis_job_items (
                        job_id TEXT NOT NULL REFERENCES media_analysis_jobs(job_id) ON DELETE CASCADE,
                        asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
                        path TEXT NOT NULL,
                        status TEXT NOT NULL,
                        error TEXT,
                        PRIMARY KEY(job_id, asset_id)
                    )""",
                    "CREATE INDEX idx_media_analysis_items_status ON media_analysis_job_items(job_id, status)",
                    """CREATE TABLE media_analysis_job_errors (
                        error_id TEXT PRIMARY KEY,
                        job_id TEXT NOT NULL REFERENCES media_analysis_jobs(job_id) ON DELETE CASCADE,
                        asset_id TEXT NOT NULL,
                        path TEXT NOT NULL,
                        message TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )""",
                    "CREATE INDEX idx_media_analysis_errors_job ON media_analysis_job_errors(job_id)",
                ):
                    db.execute(statement)
                db.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (3, _datetime_text(datetime.now().astimezone())),
                )
                db.execute("PRAGMA user_version = 3")
            if version < 4:
                if not db.in_transaction:
                    db.execute("BEGIN IMMEDIATE")
                for statement in (
                    """CREATE TABLE semantic_jobs (
                        job_id TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL,
                        version TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
                    )""",
                    """CREATE TABLE semantic_items (
                        job_id TEXT NOT NULL REFERENCES semantic_jobs(job_id) ON DELETE CASCADE,
                        cache_key TEXT NOT NULL,
                        asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
                        size_bytes INTEGER NOT NULL, modified_at TEXT NOT NULL,
                        start_seconds REAL NOT NULL, end_seconds REAL NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending', error TEXT,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY(job_id, cache_key)
                    )""",
                    "CREATE INDEX idx_semantic_items_job ON semantic_items(job_id, status)",
                    """CREATE TABLE semantic_cache (
                        cache_key TEXT PRIMARY KEY,
                        asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
                        provider TEXT NOT NULL, model TEXT NOT NULL, version TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL, modified_at TEXT NOT NULL,
                        start_seconds REAL NOT NULL, end_seconds REAL NOT NULL,
                        moments_json TEXT NOT NULL, input_tokens INTEGER NOT NULL,
                        output_tokens INTEGER NOT NULL, completed_at TEXT NOT NULL
                    )""",
                    "CREATE INDEX idx_semantic_cache_asset ON semantic_cache(asset_id, provider, model, version)",
                ):
                    db.execute(statement)
                db.execute("INSERT INTO schema_migrations VALUES (?, ?)", (4, _datetime_text(datetime.now().astimezone())))
                db.execute("PRAGMA user_version = 4")
            if version < 5:
                if not db.in_transaction:
                    db.execute("BEGIN IMMEDIATE")
                db.execute("""CREATE TABLE local_feature_windows (
                    asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
                    start_seconds REAL NOT NULL CHECK(start_seconds >= 0),
                    end_seconds REAL NOT NULL CHECK(end_seconds > start_seconds),
                    version TEXT NOT NULL, features_json TEXT NOT NULL,
                    PRIMARY KEY(asset_id, start_seconds)
                )""")
                db.execute("INSERT INTO schema_migrations VALUES (?, ?)", (5, _datetime_text(datetime.now().astimezone())))
                db.execute("PRAGMA user_version = 5")
            if version < 6:
                if not db.in_transaction:
                    db.execute("BEGIN IMMEDIATE")
                db.execute("ALTER TABLE assets ADD COLUMN content_sha256 TEXT")
                db.execute("CREATE UNIQUE INDEX idx_assets_content ON assets(content_sha256) WHERE content_sha256 IS NOT NULL")
                db.execute("ALTER TABLE locations ADD COLUMN available INTEGER NOT NULL DEFAULT 1")
                db.execute("ALTER TABLE index_jobs ADD COLUMN verify_contents INTEGER NOT NULL DEFAULT 0")
                db.execute("CREATE INDEX idx_locations_preferred ON locations(asset_id, available DESC, last_seen_at DESC, path)")
                db.execute("""CREATE TABLE asset_aliases (
                    alias_id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE
                )""")
                db.execute("INSERT INTO schema_migrations VALUES (?, ?)", (6, _datetime_text(datetime.now().astimezone())))
                db.execute("PRAGMA user_version = 6")
            if version < 7:
                if not db.in_transaction:
                    db.execute("BEGIN IMMEDIATE")
                db.execute("ALTER TABLE assets ADD COLUMN metadata_version TEXT")
                db.execute("INSERT INTO schema_migrations VALUES (?, ?)", (7, _datetime_text(datetime.now().astimezone())))
                db.execute("PRAGMA user_version = 7")

    def _backup_before_migration(self, source, version):
        """SQLite backup includes committed WAL data; never copy an open DB file."""
        directory = self.path.parent / "backups"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{self.path.stem}-schema-{version}-{uuid4().hex}.sqlite3"
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        except Exception:
            destination.close()
            target.unlink(missing_ok=True)
            raise
        finally:
            destination.close()

    def create_index_job(self, roots: list[Path], verify_contents: bool = False) -> IndexJob:
        normalized_roots = tuple(Path(os.path.abspath(root)) for root in roots)
        if not normalized_roots:
            raise ValueError("at least one media root is required")
        now = datetime.now().astimezone()
        job = IndexJob(
            job_id=str(uuid4()),
            roots=normalized_roots,
            status=IndexJobStatus.PENDING,
            created_at=now,
            updated_at=now,
            verify_contents=verify_contents,
        )
        with self._connection() as db:
            db.execute(
                "INSERT INTO index_jobs(job_id, roots_json, status, created_at, updated_at, verify_contents) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    job.job_id,
                    json.dumps([str(root) for root in normalized_roots]),
                    job.status.value,
                    _datetime_text(now),
                    _datetime_text(now),
                    int(verify_contents),
                ),
            )
        return job

    def get_index_job(self, job_id: str) -> IndexJob | None:
        with self._connection() as db:
            row = db.execute("SELECT * FROM index_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            return None
        return IndexJob(
            job_id=row["job_id"],
            roots=tuple(Path(item) for item in json.loads(row["roots_json"])),
            status=IndexJobStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            verify_contents=bool(row["verify_contents"]),
        )

    def list_resumable_index_jobs(self) -> list[IndexJob]:
        with self._connection() as db:
            rows = db.execute(
                """SELECT * FROM index_jobs WHERE status IN (?, ?, ?, ?)
                   ORDER BY updated_at DESC""",
                (
                    IndexJobStatus.PENDING.value,
                    IndexJobStatus.RUNNING.value,
                    IndexJobStatus.CANCELLED.value,
                    IndexJobStatus.COMPLETE_WITH_ERRORS.value,
                ),
            ).fetchall()
        return [
            IndexJob(
                job_id=row["job_id"],
                roots=tuple(Path(item) for item in json.loads(row["roots_json"])),
                status=IndexJobStatus(row["status"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                verify_contents=bool(row["verify_contents"]),
            )
            for row in rows
        ]

    def create_media_analysis_job(self, analysis_version: str, asset_ids=None) -> MediaAnalysisJob:
        if not analysis_version:
            raise ValueError("analysis version must not be empty")
        now = datetime.now().astimezone()
        job = MediaAnalysisJob(
            job_id=str(uuid4()),
            analysis_version=analysis_version,
            status=MediaAnalysisJobStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
        with self._connection() as db:
            db.execute(
                "INSERT INTO media_analysis_jobs VALUES (?, ?, ?, ?, ?)",
                (job.job_id, analysis_version, job.status.value, _datetime_text(now), _datetime_text(now)),
            )
            assets = db.execute(
                """SELECT a.asset_id, l.path FROM assets a JOIN locations l USING(asset_id)
                   WHERE l.location_id=(SELECT l2.location_id FROM locations l2 WHERE l2.asset_id=a.asset_id
                       ORDER BY l2.available DESC, l2.last_seen_at DESC, l2.path LIMIT 1)
                   ORDER BY a.capture_time, l.path"""
            ).fetchall()
            db.executemany(
                "INSERT INTO media_analysis_job_items(job_id, asset_id, path, status) VALUES (?, ?, ?, ?)",
                [(job.job_id, row["asset_id"], row["path"], IndexItemStatus.PENDING.value) for row in assets
                 if asset_ids is None or row["asset_id"] in asset_ids],
            )
        return job

    def get_media_analysis_job(self, job_id: str) -> MediaAnalysisJob | None:
        with self._connection() as db:
            row = db.execute("SELECT * FROM media_analysis_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            return None
        return MediaAnalysisJob(
            job_id=row["job_id"],
            analysis_version=row["analysis_version"],
            status=MediaAnalysisJobStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def list_resumable_media_analysis_jobs(self) -> list[MediaAnalysisJob]:
        statuses = (
            MediaAnalysisJobStatus.PENDING.value,
            MediaAnalysisJobStatus.RUNNING.value,
            MediaAnalysisJobStatus.CANCELLED.value,
            MediaAnalysisJobStatus.COMPLETE_WITH_ERRORS.value,
        )
        with self._connection() as db:
            rows = db.execute(
                "SELECT * FROM media_analysis_jobs WHERE status IN (?, ?, ?, ?) ORDER BY updated_at DESC",
                statuses,
            ).fetchall()
        return [
            MediaAnalysisJob(
                job_id=row["job_id"],
                analysis_version=row["analysis_version"],
                status=MediaAnalysisJobStatus(row["status"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
            for row in rows
        ]

    def set_media_analysis_job_status(self, job_id: str, status: MediaAnalysisJobStatus) -> None:
        with self._connection() as db:
            cursor = db.execute(
                "UPDATE media_analysis_jobs SET status=?, updated_at=? WHERE job_id=?",
                (status.value, _datetime_text(datetime.now().astimezone()), job_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown media analysis job: {job_id}")

    def reset_media_analysis_job_version(self, job_id: str, analysis_version: str) -> None:
        """Invalidate every queued result when resuming a job from an older profile."""
        with self._connection() as db:
            cursor = db.execute(
                "UPDATE media_analysis_jobs SET analysis_version=?, status=?, updated_at=? WHERE job_id=?",
                (
                    analysis_version,
                    MediaAnalysisJobStatus.PENDING.value,
                    _datetime_text(datetime.now().astimezone()),
                    job_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown media analysis job: {job_id}")
            db.execute(
                "UPDATE media_analysis_job_items SET status=?, error=NULL WHERE job_id=?",
                (IndexItemStatus.PENDING.value, job_id),
            )
            db.execute("DELETE FROM media_analysis_job_errors WHERE job_id=?", (job_id,))

    def list_media_analysis_job_items(self, job_id: str, status: IndexItemStatus | None = None):
        with self._connection() as db:
            if status is None:
                return db.execute(
                    "SELECT * FROM media_analysis_job_items WHERE job_id=? ORDER BY path", (job_id,)
                ).fetchall()
            return db.execute(
                "SELECT * FROM media_analysis_job_items WHERE job_id=? AND status=? ORDER BY path",
                (job_id, status.value),
            ).fetchall()

    def set_media_analysis_job_item(
        self, job_id: str, asset_id: str, status: IndexItemStatus, error: str | None = None
    ) -> None:
        with self._connection() as db:
            cursor = db.execute(
                "UPDATE media_analysis_job_items SET status=?, error=? WHERE job_id=? AND asset_id=?",
                (status.value, error, job_id, asset_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown asset in media analysis job {job_id}: {asset_id}")

    def add_media_analysis_job_error(self, job_id: str, asset_id: str, path: str, message: str) -> None:
        with self._connection() as db:
            db.execute(
                "INSERT INTO media_analysis_job_errors VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid4()), job_id, asset_id, path, message, _datetime_text(datetime.now().astimezone())),
            )

    def clear_media_analysis_job_errors(self, job_id: str, asset_id: str) -> None:
        with self._connection() as db:
            db.execute(
                "DELETE FROM media_analysis_job_errors WHERE job_id=? AND asset_id=?",
                (job_id, asset_id),
            )

    def list_media_analysis_job_errors(self, job_id: str):
        with self._connection() as db:
            return db.execute(
                "SELECT path, message, created_at FROM media_analysis_job_errors WHERE job_id=? ORDER BY created_at, path",
                (job_id,),
            ).fetchall()

    def media_analysis_job_counts(self, job_id: str) -> dict[str, int]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT status, COUNT(*) AS count FROM media_analysis_job_items WHERE job_id=? GROUP BY status",
                (job_id,),
            ).fetchall()
        counts = {status.value: 0 for status in IndexItemStatus}
        counts.update({row["status"]: row["count"] for row in rows})
        return counts

    def set_index_job_status(self, job_id: str, status: IndexJobStatus) -> None:
        with self._connection() as db:
            cursor = db.execute(
                "UPDATE index_jobs SET status=?, updated_at=? WHERE job_id=?",
                (status.value, _datetime_text(datetime.now().astimezone()), job_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown index job: {job_id}")

    def clear_index_job_errors(self, job_id: str) -> None:
        with self._connection() as db:
            db.execute("DELETE FROM index_job_errors WHERE job_id=?", (job_id,))

    def queue_index_job_item(
        self, job_id: str, path: Path, size_bytes: int, modified_at: datetime
    ) -> None:
        resolved = str(path.resolve())
        path_key = resolved.casefold()
        modified_text = _datetime_text(modified_at)
        with self._connection() as db:
            db.execute(
                """INSERT INTO index_job_items(job_id, path, path_key, size_bytes,
                    modified_at, status, error) VALUES (?, ?, ?, ?, ?, ?, NULL)
                    ON CONFLICT(job_id, path_key) DO UPDATE SET
                    path=excluded.path, size_bytes=excluded.size_bytes,
                    modified_at=excluded.modified_at,
                    status=CASE WHEN index_job_items.size_bytes=excluded.size_bytes
                        AND index_job_items.modified_at=excluded.modified_at
                        AND index_job_items.status IN ('complete', 'skipped')
                        THEN index_job_items.status ELSE 'pending' END,
                    error=CASE WHEN index_job_items.size_bytes=excluded.size_bytes
                        AND index_job_items.modified_at=excluded.modified_at
                        AND index_job_items.status IN ('complete', 'skipped')
                        THEN index_job_items.error ELSE NULL END""",
                (
                    job_id,
                    resolved,
                    path_key,
                    size_bytes,
                    modified_text,
                    IndexItemStatus.PENDING.value,
                ),
            )

    def list_index_job_items(self, job_id: str, status: IndexItemStatus | None = None):
        with self._connection() as db:
            if status is None:
                rows = db.execute(
                    "SELECT * FROM index_job_items WHERE job_id=? ORDER BY path",
                    (job_id,),
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT * FROM index_job_items WHERE job_id=? AND status=?
                       ORDER BY path""",
                    (job_id, status.value),
                ).fetchall()
        return rows

    def set_index_job_item(
        self,
        job_id: str,
        path: Path,
        status: IndexItemStatus,
        error: str | None = None,
    ) -> None:
        with self._connection() as db:
            cursor = db.execute(
                """UPDATE index_job_items SET status=?, error=?
                   WHERE job_id=? AND path_key=?""",
                (status.value, error, job_id, str(path.resolve()).casefold()),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown item in index job {job_id}: {path}")

    def add_index_job_error(self, job_id: str, path: str, stage: str, message: str) -> None:
        with self._connection() as db:
            db.execute(
                "INSERT INTO index_job_errors VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    job_id,
                    path,
                    stage,
                    message,
                    _datetime_text(datetime.now().astimezone()),
                ),
            )

    def index_job_counts(self, job_id: str) -> dict[str, int]:
        with self._connection() as db:
            rows = db.execute(
                """SELECT status, COUNT(*) AS count FROM index_job_items
                   WHERE job_id=? GROUP BY status""",
                (job_id,),
            ).fetchall()
            errors = db.execute(
                "SELECT COUNT(*) FROM index_job_errors WHERE job_id=?", (job_id,)
            ).fetchone()[0]
        counts = {status.value: 0 for status in IndexItemStatus}
        counts.update({row["status"]: row["count"] for row in rows})
        counts["discovery_errors"] = errors
        return counts

    def list_index_job_errors(self, job_id: str):
        with self._connection() as db:
            return db.execute(
                """SELECT path, stage, message, created_at FROM index_job_errors
                   WHERE job_id=? ORDER BY created_at, path""",
                (job_id,),
            ).fetchall()

    def save_asset(self, asset: MediaAsset) -> MediaAsset:
        """Insert or refresh a file location, preserving its local identity on rescans."""
        path = str(asset.path.resolve())
        path_key = path.casefold()
        now = _datetime_text(datetime.now().astimezone())
        with self._connection() as db:
            existing = db.execute(
                """SELECT l.asset_id, l.size_bytes, l.modified_at, a.*
                   FROM locations l JOIN assets a USING(asset_id)
                   WHERE l.path_key = ?""",
                (path_key,),
            ).fetchone()
            if existing:
                asset = replace(asset, asset_id=existing["asset_id"])
                unchanged = (
                    existing["size_bytes"] == asset.size_bytes
                    and existing["modified_at"] == _datetime_text(asset.modified_at)
                )
                if unchanged:
                    old_capture = _capture_from_row(existing)
                    asset = replace(
                        asset,
                        capture_time=(old_capture if old_capture and old_capture.source == TimestampSource.MANUAL
                                      else asset.capture_time or old_capture),
                        duration_seconds=(
                            asset.duration_seconds
                            if asset.duration_seconds is not None
                            else existing["duration_seconds"]
                        ),
                        video_codec=asset.video_codec or existing["video_codec"],
                        width=(asset.width if asset.width is not None else existing["width"]),
                        height=(asset.height if asset.height is not None else existing["height"]),
                        has_audio=(
                            asset.has_audio
                            if asset.has_audio is not None
                            else _optional_bool(existing["has_audio"])
                        ),
                        analysis_status=AnalysisStatus(existing["analysis_status"]),
                        analysis_version=asset.analysis_version or existing["analysis_version"],
                        content_sha256=asset.content_sha256 or existing["content_sha256"],
                        metadata_version=asset.metadata_version or existing["metadata_version"],
                    )
                else:
                    asset = replace(
                        asset,
                        analysis_status=AnalysisStatus.NOT_ANALYZED,
                        analysis_version=None,
                        content_sha256=asset.content_sha256,
                    )
                    db.execute("DELETE FROM shots WHERE asset_id=?", (asset.asset_id,))
                    db.execute("DELETE FROM analysis_runs WHERE asset_id=?", (asset.asset_id,))
                    db.execute("DELETE FROM semantic_cache WHERE asset_id=?", (asset.asset_id,))
                    db.execute("DELETE FROM local_feature_windows WHERE asset_id=?", (asset.asset_id,))
            db.execute(
                """INSERT INTO assets (
                    asset_id, capture_time, capture_source, capture_confidence,
                    capture_raw_value, duration_seconds, video_codec, width, height,
                    has_audio, analysis_status, analysis_version, created_at, updated_at, content_sha256, metadata_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    capture_time=excluded.capture_time,
                    capture_source=excluded.capture_source,
                    capture_confidence=excluded.capture_confidence,
                    capture_raw_value=excluded.capture_raw_value,
                    duration_seconds=excluded.duration_seconds,
                    video_codec=excluded.video_codec, width=excluded.width,
                    height=excluded.height, has_audio=excluded.has_audio,
                    analysis_status=excluded.analysis_status,
                    analysis_version=excluded.analysis_version, updated_at=excluded.updated_at,
                    content_sha256=excluded.content_sha256, metadata_version=excluded.metadata_version""",
                (
                    asset.asset_id,
                    _datetime_text(asset.capture_time.value) if asset.capture_time else None,
                    asset.capture_time.source.value if asset.capture_time else None,
                    asset.capture_time.confidence if asset.capture_time else None,
                    asset.capture_time.raw_value if asset.capture_time else None,
                    asset.duration_seconds,
                    asset.video_codec,
                    asset.width,
                    asset.height,
                    _bool_int(asset.has_audio),
                    asset.analysis_status.value,
                    asset.analysis_version,
                    now,
                    now,
                    asset.content_sha256,
                    asset.metadata_version,
                ),
            )
            db.execute(
                """INSERT INTO locations(location_id, asset_id, path, path_key,
                    size_bytes, modified_at, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(path_key) DO UPDATE SET asset_id=excluded.asset_id,
                    path=excluded.path, size_bytes=excluded.size_bytes,
                    modified_at=excluded.modified_at, last_seen_at=excluded.last_seen_at, available=1""",
                (
                    str(uuid4()),
                    asset.asset_id,
                    path,
                    path_key,
                    asset.size_bytes,
                    _datetime_text(asset.modified_at),
                    now,
                ),
            )
        return asset

    def get_asset(self, asset_id: str) -> MediaAsset | None:
        with self._connection() as db:
            alias = db.execute("SELECT asset_id FROM asset_aliases WHERE alias_id=?", (asset_id,)).fetchone()
            if alias:
                asset_id = alias[0]
            row = db.execute(
                """SELECT a.*, l.path, l.size_bytes, l.modified_at FROM assets a
                   JOIN locations l USING(asset_id) WHERE a.asset_id=?
                   ORDER BY l.available DESC, l.last_seen_at DESC, l.path LIMIT 1""",
                (asset_id,),
            ).fetchone()
        return _asset_from_row(row) if row else None

    def get_asset_for_path(self, path: Path) -> MediaAsset | None:
        with self._connection() as db:
            row = db.execute(
                """SELECT a.*, l.path, l.size_bytes, l.modified_at FROM assets a
                   JOIN locations l USING(asset_id) WHERE l.path_key=?
                   ORDER BY l.path LIMIT 1""",
                (str(path.resolve()).casefold(),),
            ).fetchone()
        return _asset_from_row(row) if row else None

    def review_capture_times(self, search="", mode="all", offset=0, limit=200):
        """Page canonical assets, including undated/offline sources, for correction."""
        if mode not in {"all", "uncertain", "missing"} or offset < 0 or not 1 <= limit <= 500:
            raise ValueError("Ungültige Auswahl für die Aufnahmezeiten.")
        where, parameters = [], []
        if mode == "missing":
            where.append("a.capture_time IS NULL")
        elif mode == "uncertain":
            where.append("(a.capture_time IS NULL OR a.capture_confidence < 0.8)")
        if search.strip():
            where.append("EXISTS(SELECT 1 FROM locations s WHERE s.asset_id=a.asset_id AND instr(casefold(s.path), ?) > 0)")
            parameters.append(search.strip().casefold())
        clause = " AND " + " AND ".join(where) if where else ""
        preferred = """FROM assets a JOIN locations l USING(asset_id)
            WHERE l.location_id=(SELECT l2.location_id FROM locations l2 WHERE l2.asset_id=a.asset_id
                ORDER BY l2.available DESC, l2.last_seen_at DESC, l2.path LIMIT 1)"""
        with self._connection() as db:
            db.create_function("casefold", 1, str.casefold, deterministic=True)
            total = db.execute("SELECT COUNT(*) " + preferred + clause, parameters).fetchone()[0]
            rows = db.execute("SELECT a.*, l.path, l.size_bytes, l.modified_at " + preferred + clause
                + " ORDER BY a.capture_time, a.asset_id LIMIT ? OFFSET ?", (*parameters, limit, offset)).fetchall()
        return [_asset_from_row(row) for row in rows], total

    def set_manual_capture_time(self, asset_id: str, value: datetime) -> None:
        """Change library chronology only; source revisions and analysis stay valid."""
        if not isinstance(value, datetime):
            raise ValueError("Aufnahmedatum und Uhrzeit erforderlich.")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            alias = db.execute("SELECT asset_id FROM asset_aliases WHERE alias_id=?", (asset_id,)).fetchone()
            if alias:
                asset_id = alias[0]
            cursor = db.execute("""UPDATE assets SET capture_time=?, capture_source='manual',
                capture_confidence=1.0, updated_at=? WHERE asset_id=?""",
                (_datetime_text(value), _datetime_text(datetime.now().astimezone()), asset_id))
            if cursor.rowcount != 1:
                raise KeyError("Die Aufnahme ist nicht mehr in der Bibliothek vorhanden.")

    def set_asset_analysis_state(
        self, asset_id: str, status: AnalysisStatus, version: str | None = None
    ) -> None:
        with self._connection() as db:
            cursor = db.execute(
                "UPDATE assets SET analysis_status=?, analysis_version=?, updated_at=? WHERE asset_id=?",
                (status.value, version, _datetime_text(datetime.now().astimezone()), asset_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown asset: {asset_id}")

    def touch_location(self, path: Path) -> None:
        with self._connection() as db:
            db.execute(
                "UPDATE locations SET last_seen_at=?, available=1 WHERE path_key=?",
                (_datetime_text(datetime.now().astimezone()), str(path.resolve()).casefold()),
            )

    def mark_unseen_locations(self, roots, discovered_paths):
        """Keep offline metadata, but prefer a location seen in the latest scan."""
        seen = {str(path.resolve()).casefold() for path in discovered_paths}
        prefixes = [os.path.abspath(root).casefold().rstrip("\\/") for root in roots]
        with self._connection() as db:
            paths = db.execute("SELECT path_key FROM locations WHERE available=1").fetchall()
            missing = [(row[0],) for row in paths if row[0] not in seen and any(
                row[0] == root or row[0].startswith(root + "\\") or row[0].startswith(root + "/") for root in prefixes)]
            db.executemany("UPDATE locations SET available=0 WHERE path_key=?", missing)

    def list_assets(self) -> list[MediaAsset]:
        with self._connection() as db:
            rows = db.execute(
                """SELECT a.*, l.path, l.size_bytes, l.modified_at FROM assets a
                   JOIN locations l USING(asset_id)
                   WHERE l.location_id = (SELECT l2.location_id FROM locations l2
                       WHERE l2.asset_id=a.asset_id ORDER BY l2.available DESC, l2.last_seen_at DESC, l2.path LIMIT 1)
                   ORDER BY a.capture_time, l.path"""
            ).fetchall()
        return [_asset_from_row(row) for row in rows]

    def list_assets_in_capture_date_range(self, start: date, end: date) -> list[MediaAsset]:
        """Return assets whose recorded calendar date is in the inclusive range.

        The date component is intentionally compared as recorded. Offsets remain
        available on CaptureTime for later instant-based operations; date-only
        selection must not silently convert footage into another calendar day.
        Assets without a known capture date are excluded.
        """
        if end < start:
            raise ValueError("end date must be on or after start date")
        with self._connection() as db:
            rows = db.execute(
                """SELECT a.*, l.path, l.size_bytes, l.modified_at FROM assets a
                   JOIN locations l USING(asset_id)
                   WHERE l.location_id = (SELECT l2.location_id FROM locations l2
                       WHERE l2.asset_id=a.asset_id ORDER BY l2.available DESC, l2.last_seen_at DESC, l2.path LIMIT 1)
                     AND a.capture_time IS NOT NULL
                     AND substr(a.capture_time, 1, 10) >= ?
                     AND substr(a.capture_time, 1, 10) <= ?
                   ORDER BY substr(a.capture_time, 1, 10), a.capture_time, l.path""",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [_asset_from_row(row) for row in rows]

    def capture_date_page(self, start: date, end: date, *, offset=0, limit=200) -> CaptureDatePage:
        """Bounded calendar-date inspection with counts and rows in one snapshot.

        Choose canonical assets before resolving preferred locations. Copies do
        not consume extra rows; offline locations remain inspectable. Offsets
        are deliberately not converted through SQLite's UTC date functions.
        """
        if (type(start) is not date or type(end) is not date or end < start
                or type(offset) is not int or offset < 0
                or type(limit) is not int or not 1 <= limit <= 500):
            raise ValueError("Ungültige Seitenauswahl für den Aufnahmezeitraum.")
        parameters = (start.isoformat(), end.isoformat())
        with self._connection() as db:
            db.execute("BEGIN")
            counts = db.execute("""SELECT
                COALESCE(SUM(CASE WHEN substr(a.capture_time, 1, 10) BETWEEN ? AND ? THEN 1 ELSE 0 END), 0) AS total,
                COALESCE(SUM(a.capture_time IS NULL), 0) AS unknown
                FROM assets a WHERE EXISTS(SELECT 1 FROM locations l WHERE l.asset_id=a.asset_id)""",
                parameters).fetchone()
            total = counts["total"]
            offset = min(offset, ((total - 1) // limit) * limit) if total else 0
            rows = db.execute("""SELECT a.*, l.path, l.size_bytes, l.modified_at
                FROM (SELECT a.* FROM assets a
                    WHERE substr(a.capture_time, 1, 10) BETWEEN ? AND ?
                    AND EXISTS(SELECT 1 FROM locations l WHERE l.asset_id=a.asset_id)
                    ORDER BY a.capture_time, a.asset_id LIMIT ? OFFSET ?) a
                JOIN locations l ON l.location_id=(SELECT l2.location_id FROM locations l2
                    WHERE l2.asset_id=a.asset_id
                    ORDER BY l2.available DESC, l2.last_seen_at DESC, l2.path LIMIT 1)
                ORDER BY a.capture_time, a.asset_id""", (*parameters, limit, offset)).fetchall()
        return CaptureDatePage(tuple(_asset_from_row(row) for row in rows), total, counts["unknown"], offset)

    def count_assets_without_capture_time(self) -> int:
        with self._connection() as db:
            return db.execute(
                "SELECT COUNT(*) FROM assets WHERE capture_time IS NULL AND EXISTS(SELECT 1 FROM locations WHERE locations.asset_id=assets.asset_id)"
            ).fetchone()[0]

    def count_assets(self) -> int:
        with self._connection() as db:
            return db.execute("SELECT COUNT(*) FROM assets WHERE EXISTS(SELECT 1 FROM locations WHERE locations.asset_id=assets.asset_id)").fetchone()[0]

    def get_folder_stats(self, root: Path) -> FolderStats:
        # Stored roots are already canonical. Reading cached statistics must not
        # contact an unavailable network share or resolve symlinks again.
        path_key = os.path.abspath(root).casefold()
        separator = "\\" if "\\" in path_key else "/"
        normalized_root = path_key.rstrip("\\/")
        prefix = normalized_root + separator
        with self._connection() as db:
            row = db.execute(
                """SELECT COUNT(DISTINCT a.asset_id) AS video_count,
                          MIN(substr(a.capture_time, 1, 10)) AS first_date,
                          MAX(substr(a.capture_time, 1, 10)) AS last_date
                   FROM assets a JOIN locations l USING(asset_id)
                   WHERE l.path_key=? OR substr(l.path_key, 1, ?) = ?""",
                (path_key, len(prefix), prefix),
            ).fetchone()
        return FolderStats(
            video_count=row["video_count"],
            first_capture_date=row["first_date"],
            last_capture_date=row["last_date"],
        )

    def save_shots(self, asset_id: str, shots: list[Shot], *,
                   windows: list[LocalFeatureWindow] | None = None,
                   analysis_version: str | None = None) -> None:
        """Optionally commit all local measurements and completion atomically."""
        if any(shot.asset_id != asset_id for shot in shots):
            raise ValueError("all shots must belong to the requested asset")
        if windows is not None:
            if not analysis_version or any(window.asset_id != asset_id for window in windows):
                raise ValueError("local windows require a version and matching asset")
            ordered = sorted(windows, key=lambda window: window.start_seconds)
            if any(left.end_seconds > right.start_seconds + 1e-6 for left, right in zip(ordered, ordered[1:])):
                raise ValueError("local windows must not overlap")
        with self._connection() as db:
            db.execute("DELETE FROM shots WHERE asset_id=?", (asset_id,))
            db.executemany(
                """INSERT INTO shots(shot_id, asset_id, start_seconds, end_seconds,
                   local_features_json, thumbnail_path) VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (
                        shot.shot_id,
                        shot.asset_id,
                        shot.start_seconds,
                        shot.end_seconds,
                        json.dumps(shot.local_features, sort_keys=True),
                        shot.thumbnail_path,
                    )
                    for shot in shots
                ],
            )
            if windows is not None:
                db.execute("DELETE FROM local_feature_windows WHERE asset_id=?", (asset_id,))
                db.executemany("INSERT INTO local_feature_windows VALUES (?, ?, ?, ?, ?)", [
                    (window.asset_id, window.start_seconds, window.end_seconds, analysis_version,
                     json.dumps(window.features, sort_keys=True, allow_nan=False)) for window in windows
                ])
                now = _datetime_text(datetime.now().astimezone())
                db.execute("UPDATE assets SET analysis_status='complete', analysis_version=?, updated_at=? WHERE asset_id=?",
                           (analysis_version, now, asset_id))
                db.execute("""INSERT INTO analysis_runs(run_id, asset_id, stage, version, status, completed_at)
                    VALUES (?, ?, 'shot_detection', ?, 'complete', ?)
                    ON CONFLICT(asset_id, stage, version) DO UPDATE SET status='complete', completed_at=excluded.completed_at, error=NULL""",
                    (str(uuid4()), asset_id, analysis_version, now))

    def local_features_for_assets(self, assets, version: str):
        """Convenience materialization for small selections and diagnostics."""
        result = {}
        for asset, windows in self.iter_assets_with_local_features(assets, version):
            if windows:
                result[asset.asset_id] = windows
        return result

    def iter_assets_with_local_features(self, assets, version: str, batch_size: int = 100):
        """Bound planning memory to one asset batch, not the entire frame index."""
        if batch_size < 1:
            raise ValueError("batch size must be positive")
        with self._connection() as db:
            for offset in range(0, len(assets), batch_size):
                batch = assets[offset:offset + batch_size]
                keys = [asset.asset_id for asset in batch if asset.analysis_status == AnalysisStatus.COMPLETE and asset.analysis_version == version]
                windows_by_asset = {}
                if keys:
                    placeholders = ",".join("?" for _ in keys)
                    rows = db.execute(f"""SELECT * FROM local_feature_windows WHERE version=?
                        AND asset_id IN ({placeholders}) ORDER BY asset_id, start_seconds""", (version, *keys)).fetchall()
                    for row in rows:
                        window = LocalFeatureWindow(row["asset_id"], row["start_seconds"], row["end_seconds"], json.loads(row["features_json"]))
                        windows_by_asset.setdefault(window.asset_id, []).append(window)
                for asset in batch:
                    yield asset, windows_by_asset.get(asset.asset_id, [])

    def list_shots(self, asset_id: str) -> list[Shot]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT * FROM shots WHERE asset_id=? ORDER BY start_seconds", (asset_id,)
            ).fetchall()
        return [
            Shot(
                shot_id=row["shot_id"],
                asset_id=row["asset_id"],
                start_seconds=row["start_seconds"],
                end_seconds=row["end_seconds"],
                local_features=json.loads(row["local_features_json"]),
                thumbnail_path=row["thumbnail_path"],
            )
            for row in rows
        ]

    def save_analysis_record(self, record: AnalysisRecord) -> None:
        if not record.stage or not record.version:
            raise ValueError("analysis stage and version must not be empty")
        with self._connection() as db:
            db.execute(
                """INSERT INTO analysis_runs(run_id, asset_id, stage, version, status,
                    provider, model, completed_at, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(asset_id, stage, version) DO UPDATE SET
                    status=excluded.status, provider=excluded.provider,
                    model=excluded.model, completed_at=excluded.completed_at,
                    error=excluded.error""",
                (
                    str(uuid4()),
                    record.asset_id,
                    record.stage,
                    record.version,
                    record.status.value,
                    record.provider,
                    record.model,
                    _datetime_text(record.completed_at) if record.completed_at else None,
                    record.error,
                ),
            )


def _datetime_text(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")


def _bool_int(value: bool | None) -> int | None:
    return None if value is None else int(value)


def _asset_from_row(row: sqlite3.Row) -> MediaAsset:
    capture = _capture_from_row(row)
    return MediaAsset(
        asset_id=row["asset_id"],
        path=Path(row["path"]),
        size_bytes=row["size_bytes"],
        modified_at=datetime.fromisoformat(row["modified_at"]),
        capture_time=capture,
        duration_seconds=row["duration_seconds"],
        video_codec=row["video_codec"],
        width=row["width"],
        height=row["height"],
        has_audio=_optional_bool(row["has_audio"]),
        analysis_status=AnalysisStatus(row["analysis_status"]),
        analysis_version=row["analysis_version"],
        content_sha256=row["content_sha256"],
        metadata_version=row["metadata_version"],
    )


def _capture_from_row(row: sqlite3.Row) -> CaptureTime | None:
    if row["capture_time"] is None:
        return None
    return CaptureTime(
        value=datetime.fromisoformat(row["capture_time"]),
        source=TimestampSource(row["capture_source"]),
        confidence=row["capture_confidence"],
        raw_value=row["capture_raw_value"],
    )


def _optional_bool(value: int | None) -> bool | None:
    return None if value is None else bool(value)
