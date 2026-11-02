"""Relink reviewed ranges only when a full verified content identity matches."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from datetime import datetime

from memento.media.identity import hash_media


def relink_movie_sources(plan, library, cancel_token):
    result = deepcopy(plan)
    replacements = {}
    for segment in result.segments:
        source = segment.source
        if source in replacements:
            segment.source = replacements[source]
            continue
        if not source.content_sha256:
            continue
        if Path(source.path).is_file():
            stat = Path(source.path).stat()
            location = library.get_asset_for_path(Path(source.path))
            modified = datetime.fromtimestamp(stat.st_mtime).astimezone()
            if (stat.st_size == source.size_bytes and modified == datetime.fromisoformat(source.modified_at)
                    and (location is None or location.content_sha256 == source.content_sha256)):
                continue
        asset = library.get_asset(source.asset_id)
        if asset is None or asset.content_sha256 != source.content_sha256 or not asset.path.is_file():
            continue
        if hash_media(asset.path, cancel_token) != source.content_sha256:
            raise ValueError("Die Ersatzdatei stimmt nicht mit dem Filmplan überein. Bitte neu indexieren.")
        replacement = replace(source, asset_id=asset.asset_id, path=str(asset.path.resolve()), size_bytes=asset.size_bytes,
                              modified_at=asset.modified_at.isoformat(timespec="microseconds"))
        replacements[source] = replacement
        segment.source = replacement
    result.validate()
    return result
