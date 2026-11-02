from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event
from collections.abc import Callable, Iterable


VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".mts", ".m2ts", ".webm"}
)


@dataclass(frozen=True, slots=True)
class FileCandidate:
    path: Path
    size_bytes: int
    modified_at: datetime


@dataclass(frozen=True, slots=True)
class DiscoveryIssue:
    path: Path
    message: str


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    files: tuple[FileCandidate, ...]
    issues: tuple[DiscoveryIssue, ...]
    cancelled: bool = False


def discover_videos(
    roots: Iterable[str | Path],
    cancel_token: Event | None = None,
    on_directory: Callable[[Path], None] | None = None,
) -> DiscoveryResult:
    """Recursively find supported files without following directory symlinks."""
    found: dict[str, FileCandidate] = {}
    issues: list[DiscoveryIssue] = []
    cancelled = False

    def report_error(exc: OSError) -> None:
        issues.append(DiscoveryIssue(Path(exc.filename or ""), str(exc)))

    for root_value in roots:
        if _cancelled(cancel_token):
            cancelled = True
            break
        root = Path(root_value)
        try:
            root = root.resolve()
            if not root.is_dir():
                issues.append(DiscoveryIssue(root, "Ordner ist nicht erreichbar oder kein Verzeichnis."))
                continue
        except (OSError, RuntimeError) as exc:
            issues.append(DiscoveryIssue(root, str(exc)))
            continue
        for current, directories, filenames in os.walk(
            root, topdown=True, onerror=report_error, followlinks=False
        ):
            if _cancelled(cancel_token):
                cancelled = True
                break
            current_path = Path(current)
            directories[:] = [
                name
                for name in sorted(directories, key=str.casefold)
                if not (current_path / name).is_symlink()
            ]
            if on_directory is not None:
                on_directory(current_path)
            for filename in sorted(filenames, key=str.casefold):
                if _cancelled(cancel_token):
                    cancelled = True
                    break
                path = current_path / filename
                if path.suffix.casefold() not in VIDEO_EXTENSIONS or path.is_symlink():
                    continue
                try:
                    stat = path.stat()
                    candidate = FileCandidate(
                        path=path.resolve(),
                        size_bytes=stat.st_size,
                        modified_at=datetime.fromtimestamp(stat.st_mtime).astimezone(),
                    )
                except OSError as exc:
                    issues.append(DiscoveryIssue(path, str(exc)))
                    continue
                found.setdefault(str(candidate.path).casefold(), candidate)
            if cancelled:
                break
        if cancelled:
            break
    return DiscoveryResult(
        files=tuple(sorted(found.values(), key=lambda item: str(item.path).casefold())),
        issues=tuple(issues),
        cancelled=cancelled,
    )


def _cancelled(token) -> bool:
    return bool(token is not None and token.is_set())
