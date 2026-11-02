"""Verified byte identity with bounded memory and cooperative cancellation."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from memento.media.metadata import MediaProbeCancelled


def hash_media(path: Path, cancel_token=None, on_bytes=None) -> str:
    digest = hashlib.sha256()
    read = 0
    with path.open("rb") as stream:
        initial = os.fstat(stream.fileno())
        while True:
            if cancel_token is not None and cancel_token.is_set():
                raise MediaProbeCancelled("Inhaltsprüfung wurde abgebrochen.")
            block = stream.read(4 * 1024 * 1024)
            if not block:
                break
            digest.update(block)
            read += len(block)
            if on_bytes:
                on_bytes(read, initial.st_size)
        final = os.fstat(stream.fileno())
        located = path.stat()
    def revision(stat):
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns
    if revision(initial) != revision(final) or revision(final) != revision(located) or read != final.st_size:
        raise OSError("Datei wurde während der Inhaltsprüfung verändert.")
    return digest.hexdigest()
