"""Durable semantic work and reusable results, separate from shot analysis and movies."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from uuid import uuid4

from memento.ai.contracts import ANALYSIS_PROFILE, SemanticResult
from memento.ai.segmentation import split_analysis_range, uncovered_ranges
from memento.library.database import MediaLibrary
from memento.media.local_features import LOCAL_ANALYSIS_VERSION


def fingerprint(asset) -> tuple[int, str]:
    return asset.size_bytes, ("sha256:" + asset.content_sha256 if asset.content_sha256 else asset.modified_at.isoformat(timespec="microseconds"))


class SemanticRepository:
    """Shares the library's transactional connection policy and migrations."""

    def __init__(self, library: MediaLibrary, profile=None):
        self.library = library
        self._profile = profile

    @property
    def profile(self):
        return self._profile or ANALYSIS_PROFILE

    def create_job(self, assets, provider: str, model: str) -> str:
        job_id = str(uuid4())
        rows = []
        assets = list({asset.asset_id: asset for asset in assets}.values())
        cached_ranges, boundaries = {}, {}
        # Read only range metadata, never all semantic JSON or sampled frames.
        with self.library._connection() as db:
            for offset in range(0, len(assets), 500):
                batch = assets[offset:offset + 500]
                current = {asset.asset_id: fingerprint(asset) for asset in batch}
                placeholders = ",".join("?" for _ in batch)
                cached = db.execute(f"""SELECT asset_id, size_bytes, modified_at, start_seconds, end_seconds
                    FROM semantic_cache WHERE provider=? AND model=? AND version=?
                    AND asset_id IN ({placeholders})""", (provider, model, self.profile, *current)).fetchall()
                for row in cached:
                    if (row["size_bytes"], row["modified_at"]) == current[row["asset_id"]]:
                        cached_ranges.setdefault(row["asset_id"], set()).add((row["start_seconds"], row["end_seconds"]))
                shots = db.execute(f"""SELECT s.asset_id, s.end_seconds FROM shots s JOIN assets a USING(asset_id)
                    WHERE a.analysis_status='complete' AND a.analysis_version=?
                    AND s.asset_id IN ({placeholders})""", (LOCAL_ANALYSIS_VERSION, *current)).fetchall()
                for row in shots:
                    boundaries.setdefault(row["asset_id"], []).append(row["end_seconds"])
        for asset in assets:
            duration = asset.duration_seconds
            if duration is None or not math.isfinite(duration) or duration <= 0:
                raise ValueError("Für alle ausgewählten Videos muss eine gültige Dauer vorliegen.")
            size, modified = fingerprint(asset)
            ranges = cached_ranges.get(asset.asset_id, set()).copy()
            for start, end in uncovered_ranges(duration, ranges):
                ranges.update(split_analysis_range(start, end, boundaries.get(asset.asset_id, ())))
            for start, end in sorted(ranges):
                identity = [asset.asset_id, size, modified, start, end, provider, model, self.profile]
                key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
                rows.append((job_id, key, asset.asset_id, size, modified, start, end))
        if not rows:
            raise ValueError("Keine Videos für die KI-Analyse ausgewählt.")
        with self.library._connection() as db:
            db.execute("INSERT INTO semantic_jobs VALUES (?, ?, ?, ?, 'pending', ?)",
                       (job_id, provider, model, self.profile, datetime.now().astimezone().isoformat()))
            db.executemany("""INSERT INTO semantic_items(job_id, cache_key, asset_id, size_bytes,
                              modified_at, start_seconds, end_seconds) VALUES (?, ?, ?, ?, ?, ?, ?)""", rows)
        return job_id

    def get_job(self, job_id):
        with self.library._connection() as db:
            row = db.execute("SELECT * FROM semantic_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError("Unbekannter KI-Auftrag.")
        return row

    def resumable_jobs(self):
        with self.library._connection() as db:
            return db.execute("SELECT * FROM semantic_jobs WHERE status <> 'complete' ORDER BY created_at DESC").fetchall()

    def items(self, job_id):
        with self.library._connection() as db:
            return db.execute("SELECT * FROM semantic_items WHERE job_id=? ORDER BY asset_id, start_seconds", (job_id,)).fetchall()

    def inspection_page(self, job_id, *, offset=0, limit=100):
        """Bounded UI read, resolving current source locations and paid cache in SQL."""
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("Ungültige Seitenauswahl für den Analyseauftrag.")
        with self.library._connection() as db:
            # One read snapshot keeps page bounds and contents consistent.
            db.execute("BEGIN")
            total = db.execute("SELECT COUNT(*) FROM semantic_items WHERE job_id=?", (job_id,)).fetchone()[0]
            offset = min(offset, ((total - 1) // limit) * limit) if total else 0
            rows = db.execute("""SELECT i.*, l.path AS source_path,
                    c.cache_key AS cached_key, c.moments_json
                FROM (SELECT * FROM semantic_items WHERE job_id=?
                    ORDER BY asset_id, start_seconds, cache_key LIMIT ? OFFSET ?) i
                JOIN semantic_jobs j USING(job_id)
                LEFT JOIN locations l ON l.location_id=(SELECT l2.location_id FROM locations l2
                    WHERE l2.asset_id=i.asset_id
                    ORDER BY l2.available DESC, l2.last_seen_at DESC, l2.path LIMIT 1)
                LEFT JOIN semantic_cache c ON c.cache_key=COALESCE(
                    (SELECT direct.cache_key FROM semantic_cache direct WHERE direct.cache_key=i.cache_key),
                    (SELECT c2.cache_key FROM semantic_cache c2
                    WHERE c2.asset_id=i.asset_id AND c2.size_bytes=i.size_bytes AND c2.modified_at=i.modified_at
                    AND c2.start_seconds=i.start_seconds AND c2.end_seconds=i.end_seconds
                    AND c2.provider=j.provider AND c2.model=j.model AND c2.version=j.version
                    ORDER BY c2.completed_at, c2.cache_key LIMIT 1))
                ORDER BY i.asset_id, i.start_seconds, i.cache_key""", (job_id, limit, offset)).fetchall()
        return rows, total, offset

    def estimate(self, job_id):
        with self.library._connection() as db:
            row = db.execute("""SELECT COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN c.cache_key IS NULL THEN 1 ELSE 0 END), 0) AS pending,
                COALESCE(SUM(CASE WHEN c.cache_key IS NULL THEN i.end_seconds-i.start_seconds ELSE 0 END), 0) AS seconds,
                COALESCE(SUM(c.input_tokens), 0) AS input_tokens,
                COALESCE(SUM(c.output_tokens), 0) AS output_tokens
                FROM semantic_items i JOIN semantic_jobs j USING(job_id)
                LEFT JOIN semantic_cache c ON c.cache_key=(SELECT c2.cache_key FROM semantic_cache c2
                    WHERE c2.asset_id=i.asset_id AND c2.size_bytes=i.size_bytes AND c2.modified_at=i.modified_at
                    AND c2.start_seconds=i.start_seconds AND c2.end_seconds=i.end_seconds
                    AND c2.provider=j.provider AND c2.model=j.model AND c2.version=j.version
                    ORDER BY c2.completed_at, c2.cache_key LIMIT 1)
                WHERE i.job_id=?""", (job_id,)).fetchone()
            attempts = db.execute("SELECT COALESCE(SUM(attempts), 0) FROM semantic_items WHERE job_id=?", (job_id,)).fetchone()[0]
        return {**dict(row), "attempts": attempts}

    def set_job_status(self, job_id, status):
        with self.library._connection() as db:
            db.execute("UPDATE semantic_jobs SET status=? WHERE job_id=?", (status, job_id))

    def set_item_status(self, job_id, key, status, error=None, attempt=False):
        with self.library._connection() as db:
            db.execute("""UPDATE semantic_items SET status=?, error=?, attempts=attempts+?
                          WHERE job_id=? AND cache_key=?""", (status, error, int(attempt), job_id, key))

    def cached(self, key):
        with self.library._connection() as db:
            direct = db.execute("SELECT * FROM semantic_cache WHERE cache_key=?", (key,)).fetchone()
            if direct:
                return direct
            return db.execute("""SELECT c.* FROM semantic_items i JOIN semantic_jobs j USING(job_id)
                JOIN semantic_cache c ON c.asset_id=i.asset_id AND c.size_bytes=i.size_bytes AND c.modified_at=i.modified_at
                AND c.start_seconds=i.start_seconds AND c.end_seconds=i.end_seconds
                AND c.provider=j.provider AND c.model=j.model AND c.version=j.version
                WHERE i.cache_key=? ORDER BY c.completed_at, c.cache_key LIMIT 1""", (key,)).fetchone()

    def save_result(self, job, item, result: SemanticResult):
        with self.library._connection() as db:
            # A successful response and work completion commit together.
            db.execute("""INSERT OR REPLACE INTO semantic_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                item["cache_key"], item["asset_id"], job["provider"], job["model"], job["version"],
                item["size_bytes"], item["modified_at"], item["start_seconds"], item["end_seconds"],
                json.dumps([moment.to_dict() for moment in result.moments], ensure_ascii=False),
                result.input_tokens, result.output_tokens, datetime.now().astimezone().isoformat(),
            ))
            db.execute("UPDATE semantic_items SET status='complete', error=NULL WHERE job_id=? AND cache_key=?",
                       (job["job_id"], item["cache_key"]))

    def results_for_asset(self, asset_id, provider, model):
        asset = self.library.get_asset(asset_id)
        if asset is None:
            return []
        return self.results_for_assets([asset], provider, model).get(asset.asset_id, [])

    def results_for_assets(self, assets, provider, model):
        """Read a large selection in bounded batches, instead of one connection per clip."""
        current = {asset.asset_id: fingerprint(asset) for asset in assets}
        keys = list(current)
        result = {}
        with self.library._connection() as db:
            for offset in range(0, len(keys), 500):
                batch = keys[offset:offset + 500]
                placeholders = ",".join("?" for _ in batch)
                rows = db.execute(f"""SELECT * FROM semantic_cache WHERE provider=? AND model=?
                    AND version=? AND asset_id IN ({placeholders}) ORDER BY asset_id, start_seconds""",
                    (provider, model, self.profile, *batch)).fetchall()
                for row in rows:
                    if (row["size_bytes"], row["modified_at"]) == current[row["asset_id"]]:
                        result.setdefault(row["asset_id"], []).append(row)
        return result
