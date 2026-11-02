from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import time
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from memento.domain.media import CaptureTime, TimestampSource


METADATA_VERSION = "ffprobe-ffmetadata-capture-v2"


class MediaProbeError(RuntimeError):
    """A media file could not be inspected by available local tools."""


class MediaProbeCancelled(MediaProbeError):
    """Metadata inspection was interrupted by the caller."""


@dataclass(frozen=True, slots=True)
class MediaMetadata:
    duration_seconds: float | None
    video_codec: str | None
    width: int | None
    height: int | None
    has_audio: bool | None
    capture_time: CaptureTime | None


def find_ffprobe() -> str | None:
    configured = os.environ.get("MEMENTO_FFPROBE", "").strip()
    if configured:
        path = Path(configured)
        return str(path) if path.is_file() else None
    return shutil.which("ffprobe")


def probe_media(
    path: Path,
    ffprobe_path: str | None = None,
    timeout: float = 45,
    cancel_token=None,
) -> MediaMetadata:
    probe = ffprobe_path if ffprobe_path is not None else find_ffprobe()
    if probe:
        try:
            return _probe_with_ffprobe(path, probe, timeout, cancel_token)
        except MediaProbeCancelled:
            raise
        except (
            MediaProbeError,
            OSError,
            subprocess.SubprocessError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
        ):
            # Fall back to the same local FFmpeg binary used by the prototype.
            pass
    try:
        ffmpeg_metadata = _probe_with_ffmpeg(path, timeout, cancel_token)
    except MediaProbeCancelled:
        raise
    except (MediaProbeError, OSError, subprocess.SubprocessError):
        return _probe_with_opencv(path)
    if (
        ffmpeg_metadata.duration_seconds is not None
        and ffmpeg_metadata.width is not None
        and ffmpeg_metadata.height is not None
    ):
        return ffmpeg_metadata
    try:
        opencv_metadata = _probe_with_opencv(path)
    except MediaProbeError:
        return ffmpeg_metadata
    return MediaMetadata(
        duration_seconds=ffmpeg_metadata.duration_seconds or opencv_metadata.duration_seconds,
        video_codec=ffmpeg_metadata.video_codec,
        width=ffmpeg_metadata.width or opencv_metadata.width,
        height=ffmpeg_metadata.height or opencv_metadata.height,
        has_audio=ffmpeg_metadata.has_audio,
        capture_time=ffmpeg_metadata.capture_time,
    )


def _probe_with_opencv(path: Path) -> MediaMetadata:
    try:
        import cv2
    except ImportError as exc:
        raise MediaProbeError("OpenCV ist nicht verfügbar.") from exc
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise MediaProbeError("Weder FFmpeg noch OpenCV konnten das Video öffnen.")
    try:
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = frame_count / fps if fps > 0 and frame_count > 0 else None
    finally:
        capture.release()
    return MediaMetadata(
        duration_seconds=duration,
        video_codec=None,
        width=width or None,
        height=height or None,
        has_audio=None,
        capture_time=None,
    )


def _probe_with_ffprobe(path: Path, executable: str, timeout: float, cancel_token) -> MediaMetadata:
    result = _run_command(
        [
            executable,
            "-v", "error",
            "-show_format",
            "-show_streams",
            "-of", "json",
            str(path),
        ],
        timeout=timeout,
        cancel_token=cancel_token,
    )
    if result.returncode != 0:
        raise MediaProbeError(result.stderr.strip() or "FFprobe konnte die Datei nicht lesen.")
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict) or not isinstance(payload.get("streams"), list):
        raise MediaProbeError("Ungültige FFprobe-Metadaten.")
    streams = payload.get("streams", [])
    streams = [item for item in streams if isinstance(item, dict)]
    video = next((item for item in streams if item.get("codec_type") == "video" and not item.get("disposition", {}).get("attached_pic")), None)
    if video is None:
        raise MediaProbeError("Keine Videospur gefunden.")
    durations = [
        _positive_float(value)
        for value in [payload.get("format", {}).get("duration"), video.get("duration")]
    ]
    duration = next((value for value in durations if value is not None), None)
    # Stream tags are usually closer to the recorded media than format-level
    # tags. Keep them when both levels contain a creation_time value.
    timestamp = _capture_time(video.get("tags", {}), path, payload.get("format", {}).get("tags", {}))
    return MediaMetadata(
        duration_seconds=duration,
        video_codec=video.get("codec_name"),
        width=_positive_int(video.get("width")),
        height=_positive_int(video.get("height")),
        has_audio=any(item.get("codec_type") == "audio" for item in streams),
        capture_time=timestamp,
    )


def _probe_with_ffmpeg(path: Path, timeout: float, cancel_token) -> MediaMetadata:
    try:
        import imageio_ffmpeg

        executable = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise MediaProbeError(
            "FFprobe ist nicht verfügbar und imageio-ffmpeg konnte nicht geladen werden."
        ) from exc
    try:
        with tempfile.TemporaryDirectory(prefix="memento-metadata-") as directory:
            stream_tags = Path(directory) / "stream.ffmetadata"
            result = _run_command(
                [executable, "-nostdin", "-hide_banner", "-n", "-i", str(path),
                 "-map_metadata", "0", "-f", "ffmetadata", "pipe:1",
                 "-map_metadata", "0:s:v:0", "-f", "ffmetadata", str(stream_tags)],
                timeout=timeout, cancel_token=cancel_token,
            )
            global_tags = _parse_ffmetadata(result.stdout)
            video_tags = _parse_ffmetadata(stream_tags.read_text(encoding="utf-8")) if stream_tags.is_file() else {}
    except (OSError, subprocess.SubprocessError) as exc:
        raise MediaProbeError(str(exc)) from exc
    text = result.stderr
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    duration = None
    if duration_match:
        hours, minutes, seconds = duration_match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    video_match = re.search(r"Video:\s*([^,\s]+).*?(\d{2,5})x(\d{2,5})", text)
    if video_match is None:
        raise MediaProbeError("FFmpeg hat keine lesbare Videospur gefunden.")
    return MediaMetadata(
        duration_seconds=duration,
        video_codec=video_match.group(1),
        width=int(video_match.group(2)),
        height=int(video_match.group(3)),
        has_audio="Audio:" in text,
        capture_time=_capture_time(video_tags, path, global_tags),
    )


def _run_command(args, timeout: float, cancel_token):
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    deadline = time.monotonic() + timeout
    while True:
        if cancel_token is not None and cancel_token.is_set():
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
            else:
                process.communicate()
            raise MediaProbeCancelled("Medienprüfung wurde abgebrochen.")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            process.kill()
            process.communicate()
            raise subprocess.TimeoutExpired(args, timeout)
        try:
            stdout, stderr = process.communicate(timeout=min(0.2, remaining))
            return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            continue


def _parse_ffmetadata(text: str) -> dict[str, str]:
    """Read global ffmetadata tags, respecting escaping and line continuations."""
    logical, pending = [], ""
    for line in text.splitlines():
        pending += line
        trailing = len(line) - len(line.rstrip("\\"))
        if trailing % 2:
            pending = pending[:-1] + "\n"
            continue
        logical.append(pending)
        pending = ""
    tags = {}
    for line in logical:
        if line.startswith("["):
            break
        if not line or line.startswith((";", "#")):
            continue
        match = re.search(r"(?<!\\)(?:\\\\)*=", line)
        if match is None:
            continue
        separator = match.end() - 1
        unescape = lambda value: re.sub(r"\\(.)", r"\1", value, flags=re.DOTALL)
        tags[unescape(line[:separator]).strip()] = unescape(line[separator + 1:])
    return tags


def _capture_time(tags: dict, path: Path, fallback_tags=None) -> CaptureTime | None:
    groups = [{str(key).casefold(): str(value).strip().rstrip("\0") for key, value in group.items()}
              for group in (tags, fallback_tags or {}) if isinstance(group, dict)]
    choices = (
        (("com.apple.quicktime.creationdate",), TimestampSource.QUICKTIME, 0.9, 0.62, None),
        (("datetimeoriginal", "exif:datetimeoriginal", "exif.datetimeoriginal"), TimestampSource.EXIF, 0.85, 0.6, "offsettimeoriginal"),
        (("creation_time",), TimestampSource.CONTAINER, 0.8, 0.55, None),
        (("datetimedigitized", "exif:datetimedigitized"), TimestampSource.EXIF, 0.75, 0.5, "offsettimedigitized"),
    )
    for keys, source, aware_confidence, naive_confidence, offset_key in choices:
        for group in groups:
            for key in keys:
                raw = group.get(key)
                if not raw:
                    continue
                value_text = re.sub(r"^(\d{4}):(\d{2}):(\d{2})", r"\1-\2-\3", raw)
                if value_text.endswith("Z"):
                    value_text = value_text[:-1] + "+00:00"
                try:
                    value = datetime.fromisoformat(value_text)
                    if offset_key and value.tzinfo is None:
                        offset = group.get(offset_key) or group.get("exif:" + offset_key)
                        if offset and re.fullmatch(r"[+-]\d{2}:?\d{2}", offset):
                            try:
                                value = datetime.fromisoformat(value_text + offset)
                            except ValueError:
                                # Preserve the uncertain recording wall time
                                # when only its separate UTC offset is broken.
                                pass
                except ValueError:
                    continue
                aware = value.tzinfo is not None and value.utcoffset() is not None
                confidence = aware_confidence if aware else naive_confidence
                if len(raw) <= 10:
                    confidence = min(confidence, 0.35)
                return CaptureTime(value, source, confidence, raw)
    return None


def _positive_float(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def _positive_int(value) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result > 0 else None
