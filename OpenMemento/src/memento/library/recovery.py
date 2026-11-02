"""Validated library snapshots and journaled local recovery.

SQLite's backup API captures committed WAL data. A prepared, migrated snapshot
is checked before any live file is replaced. The durable publication intent is
finished before the desktop opens SQLite after a process crash.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
from contextlib import closing, nullcontext
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from uuid import uuid4

from memento.library.database import MediaLibrary, _SCHEMA_VERSION
from memento.library.locking import LibraryLock
from memento.media.identity import hash_media
from memento.media.metadata import MediaProbeCancelled


class RecoveryError(RuntimeError):
    pass


class RecoveryCancelled(RecoveryError):
    pass


@dataclass(frozen=True, slots=True)
class BackupInfo:
    path: Path
    schema_version: int
    assets: int
    semantic_ranges: int


@dataclass(frozen=True, slots=True)
class RecoveryProgress:
    phase: str
    completed: int
    total: int
    message: str


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    database: Path
    safety_backup: Path | None
    roots: tuple[str, ...]


def _check(token):
    if token is not None and token.is_set():
        raise RecoveryCancelled("Vorgang abgebrochen. Die bisherige Bibliothek bleibt erhalten.")


def _read_only(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.execute("PRAGMA trusted_schema=OFF")
    return connection


def _snapshot(source, destination, token, callback, message):
    _check(token)
    deadline = time.monotonic() + 30

    def progress(status, remaining, total):
        _check(token)
        if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) and time.monotonic() > deadline:
            raise RecoveryError("Die Datenbank wird von einem anderen Programm blockiert.")
        if callback:
            callback(RecoveryProgress("copy", total - remaining, total, message))

    with closing(_read_only(source)) as reader, closing(sqlite3.connect(destination)) as writer:
        reader.backup(writer, pages=256, progress=progress, sleep=0.05)


def inspect_backup(path: Path, token: Event | None = None) -> BackupInfo:
    path = Path(path).resolve()
    _check(token)
    try:
        with closing(_read_only(path)) as db:
            db.set_progress_handler(lambda: int(token is not None and token.is_set()), 1000)
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if not 1 <= version <= _SCHEMA_VERSION:
                raise RecoveryError("Die Sicherung hat eine nicht unterstützte Bibliotheksversion.")
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise RecoveryError("Die Sicherung hat die SQLite-Integritätsprüfung nicht bestanden.")
            if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise RecoveryError("Die Sicherung enthält beschädigte Datenbeziehungen.")
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"assets", "locations", "shots", "analysis_runs", "schema_migrations"} <= names:
                raise RecoveryError("Die Datei ist keine unterstützte Memento-Bibliothek.")
            if db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view') LIMIT 1").fetchone():
                raise RecoveryError("Die Sicherung enthält nicht unterstützte eigene Trigger oder Ansichten.")
            if db.execute("SELECT 1 FROM assets WHERE asset_id IN ('.','..') OR instr(asset_id,'/') OR instr(asset_id,char(92)) LIMIT 1").fetchone():
                raise RecoveryError("Die Sicherung enthält ungültige Medienkennungen.")
            assets = db.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
            ranges = db.execute("SELECT COUNT(*) FROM semantic_cache").fetchone()[0] if "semantic_cache" in names else 0
        return BackupInfo(path, version, assets, ranges)
    except (sqlite3.Error, OSError) as exc:
        _check(token)
        raise RecoveryError("Die Datei konnte nicht als gültige Memento-Sicherung gelesen werden.") from exc


def _validate_prepared(path, operation, token):
    inspect_backup(path, token)
    reference = MediaLibrary(operation / "reference.sqlite3")
    prepared = MediaLibrary(path)
    with closing(_read_only(reference.path)) as expected, closing(_read_only(path)) as actual:
        actual.set_progress_handler(lambda: int(token is not None and token.is_set()), 1000)
        for (name,) in expected.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            expected_columns = {row[1] for row in expected.execute(f'PRAGMA table_info("{name}")')}
            actual_columns = {row[1] for row in actual.execute(f'PRAGMA table_info("{name}")')}
            if not expected_columns <= actual_columns:
                raise RecoveryError("Die Sicherung enthält ein unvollständiges Bibliotheksschema.")
        for table, column in (("index_jobs", "roots_json"), ("shots", "local_features_json"),
                              ("semantic_cache", "moments_json"), ("local_feature_windows", "features_json")):
            if actual.execute(f"SELECT 1 FROM {table} WHERE NOT json_valid({column}) LIMIT 1").fetchone():
                raise RecoveryError("Die Sicherung enthält unlesbare Analyse- oder Auftragsdaten.")
        for (value,) in actual.execute("SELECT roots_json FROM index_jobs"):
            roots = json.loads(value)
            if not isinstance(roots, list) or any(not isinstance(root, str) or not Path(root).is_absolute() for root in roots):
                raise RecoveryError("Die Sicherung enthält ungültige Medienordner.")
    # Parse media dates and value objects too, rather than trusting SQL integrity alone.
    prepared.list_assets()
    _check(token)


def _atomic_json(path, value):
    descriptor, name = tempfile.mkstemp(prefix=".recovery-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _digest(path, token=None):
    try:
        return hash_media(path, token)
    except MediaProbeCancelled:
        raise RecoveryCancelled("Vorgang abgebrochen. Die bisherige Bibliothek bleibt erhalten.") from None


def _marker(database):
    return database.with_suffix(".restore.json")


def _lock_context(database, active_lock):
    if active_lock is None:
        return LibraryLock(database)
    if not active_lock.is_held or active_lock.path.resolve() != database.with_suffix(".lock").resolve():
        raise RecoveryError("Für die Wiederherstellung fehlt der exklusive Bibliothekszugriff.")
    return nullcontext(active_lock)


def _publish(database, intent):
    name = intent.get("operation", "")
    if intent.get("version") != 1 or intent.get("database") != database.name or not re.fullmatch(r"restore-[a-f0-9]{32}", name):
        raise RecoveryError("Ungültiger gespeicherter Wiederherstellungsauftrag.")
    operation = (database.parent / "backups" / name).resolve()
    if not operation.is_relative_to((database.parent / "backups").resolve()):
        raise RecoveryError("Ungültiger Wiederherstellungspfad.")
    prepared = operation / "prepared.sqlite3"
    if prepared.is_file():
        if _digest(prepared) != intent["sha256"]:
            raise RecoveryError("Die vorbereitete Sicherung wurde verändert. Bisherige Bibliothek bleibt erhalten.")
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(database) + suffix)
            if sidecar.exists():
                os.replace(sidecar, operation / ("quarantined" + suffix))
        os.replace(prepared, database)
    elif not database.is_file() or _digest(database) != intent["sha256"]:
        raise RecoveryError("Ein unterbrochener Austausch konnte nicht sicher abgeschlossen werden. Die Sicherheitskopie bleibt erhalten.")
    _atomic_json(operation / "receipt.json", {**intent, "status": "complete"})
    _marker(database).unlink(missing_ok=True)


def finish_pending_restore(database: Path, active_lock=None) -> bool:
    database = Path(database).resolve()
    if not _marker(database).exists():
        return False
    with _lock_context(database, active_lock):
        try:
            intent = json.loads(_marker(database).read_text(encoding="utf-8"))
            if not isinstance(intent, dict):
                raise RecoveryError("Der gespeicherte Wiederherstellungsauftrag ist unlesbar.")
            _publish(database, intent)
        except (ValueError, KeyError, TypeError) as exc:
            raise RecoveryError("Der gespeicherte Wiederherstellungsauftrag ist unlesbar.") from exc
    return True


def create_backup(database: Path, destination: Path, token=None, on_progress=None, active_lock=None) -> BackupInfo:
    database, destination = Path(database).resolve(), Path(destination).resolve()
    if destination == database or destination.exists():
        raise RecoveryError("Bitte eine neue Sicherungsdatei wählen; vorhandene Dateien werden nicht überschrieben.")
    if destination.suffix.lower() != ".sqlite3":
        raise RecoveryError("Eine Bibliothekssicherung benötigt die Dateiendung .sqlite3.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".memento-backup-", suffix=".sqlite3", dir=destination.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        with _lock_context(database, active_lock):
            _snapshot(database, temporary, token, on_progress, "Bibliothek wird gesichert")
            inspect_backup(temporary, token)
            _check(token)
            if os.name == "nt":
                os.rename(temporary, destination)
            else:
                os.link(temporary, destination)
                temporary.unlink()
        return inspect_backup(destination)
    finally:
        temporary.unlink(missing_ok=True)


def restore_backup(backup: Path, database: Path, token=None, on_progress=None, active_lock=None,
                   replace_pending: bool = False) -> RecoveryResult:
    backup, database = Path(backup).resolve(), Path(database).resolve()
    if backup == database:
        raise RecoveryError("Die aktive Bibliothek kann nicht ihre eigene Wiederherstellungsquelle sein.")
    inspect_backup(backup, token)
    with _lock_context(database, active_lock) as held_lock:
        if not replace_pending:
            finish_pending_restore(database, active_lock=held_lock)
        operation = database.parent / "backups" / ("restore-" + uuid4().hex)
        operation.mkdir(parents=True)
        if _marker(database).exists():
            shutil.copyfile(_marker(database), operation / "previous-intent.json")
        prepared = operation / "prepared.sqlite3"
        _snapshot(backup, prepared, token, on_progress, "Ausgewählte Sicherung wird vorbereitet")
        _validate_prepared(prepared, operation, token)
        # Publication must start from a self-contained file, without a WAL.
        with closing(sqlite3.connect(prepared)) as db:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            db.execute("PRAGMA journal_mode=DELETE")
        digest = _digest(prepared, token)
        safety = None
        if database.exists():
            safety = operation / "before.sqlite3"
            try:
                _snapshot(database, safety, token, on_progress, "Bisheriger Stand wird separat gesichert")
                with closing(sqlite3.connect(database, timeout=5)) as db:
                    if db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] != 0:
                        raise RecoveryError("Die aktive Bibliothek ist noch von einem anderen Programm geöffnet.")
                    db.execute("PRAGMA journal_mode=DELETE")
            except sqlite3.DatabaseError as exc:
                if (getattr(exc, "sqlite_errorcode", 0) & 0xFF) not in (sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_CORRUPT):
                    raise
                # Preserve even an unreadable original plus its sidecars as evidence.
                shutil.copyfile(database, safety)
                for suffix in ("-wal", "-shm", "-journal"):
                    sidecar = Path(str(database) + suffix)
                    if sidecar.exists():
                        shutil.copyfile(sidecar, operation / ("before.sqlite3" + suffix))
        _check(token)
        intent = {"version": 1, "database": database.name, "operation": operation.name, "sha256": digest,
                  "backup_name": backup.name, "safety_backup": safety.name if safety else None}
        _atomic_json(_marker(database), intent)
        if on_progress:
            on_progress(RecoveryProgress("publish", 1, 1, "Geprüfter Stand wird jetzt übernommen"))
        # After the durable intent is written, finish the tiny publication phase.
        # A late cancellation must not interrupt the multi-file handover.
        _publish(database, intent)
        with closing(_read_only(database)) as db:
            roots = []
            for (value,) in db.execute("SELECT roots_json FROM index_jobs ORDER BY created_at DESC"):
                roots.extend(json.loads(value))
        return RecoveryResult(database, safety, tuple(dict.fromkeys(roots)))
