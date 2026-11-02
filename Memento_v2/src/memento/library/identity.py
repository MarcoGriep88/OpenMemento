"""Transactional adoption of verified content into the existing asset/location model."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from memento.library.database import _datetime_text
from memento.media.local_features import LOCAL_ANALYSIS_VERSION


def save_verified_asset(library, asset):
    if not asset.content_sha256:
        raise ValueError("Verified import requires a content hash")
    path = str(asset.path.resolve())
    now = _datetime_text(datetime.now().astimezone())
    modified = _datetime_text(asset.modified_at)
    revision = "sha256:" + asset.content_sha256
    with library._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("""SELECT a.*, l.size_bytes, l.modified_at FROM locations l
            JOIN assets a USING(asset_id) WHERE l.path_key=?""", (path.casefold(),)).fetchone()
        target = db.execute("SELECT * FROM assets WHERE content_sha256=?", (asset.content_sha256,)).fetchone()
        legacy_unchanged = (old is not None and old["content_sha256"] is None
                            and old["size_bytes"] == asset.size_bytes
                            and datetime.fromisoformat(old["modified_at"]) == asset.modified_at)
        if target is None and legacy_unchanged:
            db.execute("UPDATE assets SET content_sha256=? WHERE asset_id=?", (asset.content_sha256, old["asset_id"]))
            _promote_cache(db, old["asset_id"], old["asset_id"], asset.size_bytes, old["modified_at"], revision)
            target = db.execute("SELECT * FROM assets WHERE asset_id=?", (old["asset_id"],)).fetchone()
        if target is None and old is not None and old["content_sha256"] is None and not legacy_unchanged:
            locations = db.execute("SELECT COUNT(*) FROM locations WHERE asset_id=?", (old["asset_id"],)).fetchone()[0]
            if locations == 1:
                # A legacy path-only ID has no verified previous byte identity.
                # Keep its historical API behavior while invalidating old data.
                for table in ("shots", "local_feature_windows", "semantic_cache", "analysis_runs"):
                    db.execute(f"DELETE FROM {table} WHERE asset_id=?", (old["asset_id"],))
                capture = asset.capture_time
                db.execute("""UPDATE assets SET content_sha256=?, analysis_status='not_analyzed', analysis_version=NULL,
                    capture_time=?, capture_source=?, capture_confidence=?, capture_raw_value=?, duration_seconds=?,
                    video_codec=?, width=?, height=?, has_audio=? WHERE asset_id=?""", (
                    asset.content_sha256, _datetime_text(capture.value) if capture else None, capture.source.value if capture else None,
                    capture.confidence if capture else None, capture.raw_value if capture else None, asset.duration_seconds,
                    asset.video_codec, asset.width, asset.height, None if asset.has_audio is None else int(asset.has_audio), old["asset_id"],
                ))
                target = db.execute("SELECT * FROM assets WHERE asset_id=?", (old["asset_id"],)).fetchone()
        if target is None:
            asset_id = str(uuid4())
            capture = asset.capture_time
            db.execute("""INSERT INTO assets(asset_id, content_sha256, capture_time, capture_source,
                capture_confidence, capture_raw_value, duration_seconds, video_codec, width, height,
                has_audio, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                asset_id, asset.content_sha256, _datetime_text(capture.value) if capture else None,
                capture.source.value if capture else None, capture.confidence if capture else None,
                capture.raw_value if capture else None, asset.duration_seconds, asset.video_codec,
                asset.width, asset.height, None if asset.has_audio is None else int(asset.has_audio), now, now,
            ))
            target = db.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
        asset_id = target["asset_id"]
        if legacy_unchanged and old["asset_id"] != asset_id:
            _merge_legacy(db, old, target, asset.size_bytes, old["modified_at"], revision)
            target = db.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
        capture = asset.capture_time
        # Preserve a manual timestamp and a better original recording timestamp
        # when a copied file offers only its filesystem time.
        if capture and target["capture_source"] != "manual" and (
            target["capture_time"] is None or capture.confidence > (target["capture_confidence"] or 0)
        ):
            db.execute("UPDATE assets SET capture_time=?, capture_source=?, capture_confidence=?, capture_raw_value=? WHERE asset_id=?",
                       (_datetime_text(capture.value), capture.source.value, capture.confidence, capture.raw_value, asset_id))
        db.execute("""UPDATE assets SET duration_seconds=COALESCE(duration_seconds, ?),
            video_codec=COALESCE(video_codec, ?), width=COALESCE(width, ?), height=COALESCE(height, ?),
            has_audio=COALESCE(has_audio, ?), updated_at=?, metadata_version=? WHERE asset_id=?""",
            (asset.duration_seconds, asset.video_codec, asset.width, asset.height,
             None if asset.has_audio is None else int(asset.has_audio), now, asset.metadata_version, asset_id))
        db.execute("""INSERT INTO locations(location_id, asset_id, path, path_key, size_bytes,
            modified_at, last_seen_at, available) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(path_key) DO UPDATE SET asset_id=excluded.asset_id, size_bytes=excluded.size_bytes,
            modified_at=excluded.modified_at, last_seen_at=excluded.last_seen_at, available=1""",
            (str(uuid4()), asset_id, path, path.casefold(), asset.size_bytes, modified, now))
    return library.get_asset_for_path(asset.path)


def _promote_cache(db, old_id, new_id, size, modified, revision):
    # Keep cache keys, candidate IDs and user corrections stable. The revision
    # field changes from legacy mtime to verified content identity.
    for table in ("semantic_cache", "semantic_items"):
        db.execute(f"UPDATE {table} SET modified_at=? WHERE asset_id=? AND size_bytes=? AND modified_at=?",
                   (revision, old_id, size, modified))
        if old_id != new_id:
            db.execute(f"UPDATE {table} SET asset_id=? WHERE asset_id=?", (new_id, old_id))


def _merge_legacy(db, old, target, size, modified, revision):
    old_id, new_id = old["asset_id"], target["asset_id"]
    _promote_cache(db, old_id, new_id, size, modified, revision)
    if old["capture_time"] and target["capture_source"] != "manual" and (
        old["capture_source"] == "manual" or (old["capture_confidence"] or 0) > (target["capture_confidence"] or 0)
    ):
        db.execute("UPDATE assets SET capture_time=?, capture_source=?, capture_confidence=?, capture_raw_value=? WHERE asset_id=?",
                   (old["capture_time"], old["capture_source"], old["capture_confidence"], old["capture_raw_value"], new_id))
    if old["analysis_status"] == "complete" and (target["analysis_status"] != "complete" or (
        old["analysis_version"] == LOCAL_ANALYSIS_VERSION and target["analysis_version"] != LOCAL_ANALYSIS_VERSION
    )):
        for table in ("shots", "local_feature_windows"):
            db.execute(f"DELETE FROM {table} WHERE asset_id=?", (new_id,))
            db.execute(f"UPDATE {table} SET asset_id=? WHERE asset_id=?", (new_id, old_id))
        db.execute("UPDATE assets SET analysis_status=?, analysis_version=? WHERE asset_id=?",
                   (old["analysis_status"], old["analysis_version"], new_id))
    db.execute("UPDATE OR IGNORE analysis_runs SET asset_id=? WHERE asset_id=?", (new_id, old_id))
    db.execute("UPDATE OR IGNORE media_analysis_job_items SET asset_id=? WHERE asset_id=?", (new_id, old_id))
    db.execute("UPDATE media_analysis_job_errors SET asset_id=? WHERE asset_id=?", (new_id, old_id))
    db.execute("UPDATE locations SET asset_id=? WHERE asset_id=?", (new_id, old_id))
    db.execute("UPDATE asset_aliases SET asset_id=? WHERE asset_id=?", (new_id, old_id))
    db.execute("INSERT OR REPLACE INTO asset_aliases VALUES (?, ?)", (old_id, new_id))
    db.execute("DELETE FROM assets WHERE asset_id=?", (old_id,))
