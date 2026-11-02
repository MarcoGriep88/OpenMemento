"""Temporary analysis media; source files are always read only."""
from __future__ import annotations

import subprocess
from pathlib import Path
from threading import Event

import imageio_ffmpeg

from memento.ai.contracts import AnalysisCancelled, MAX_PROXY_BYTES, check_cancelled
from memento.media.metadata import MediaProbeCancelled, _run_command


def create_analysis_proxy(source: Path, start: float, end: float, target: Path, cancel_token: Event) -> Path:
    check_cancelled(cancel_token)
    if source.resolve() == target.resolve() or target.exists():
        raise ValueError("Analyseziel muss eine neue Datei sein.")
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-n", "-v", "error",
        "-ss", f"{start:.6f}", "-i", str(source), "-t", f"{end - start:.6f}",
        "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "-1", "-map_chapters", "-1",
        "-vf", "scale=640:640:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1,fps=12",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-maxrate", "900k", "-bufsize", "1800k",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "1", "-ar", "24000", "-b:a", "64k",
        "-movflags", "+faststart", str(target),
    ]
    try:
        result = _run_command(command, timeout=300, cancel_token=cancel_token)
    except MediaProbeCancelled:
        raise AnalysisCancelled("Analyse abgebrochen.") from None
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("Das lokale Analysevideo konnte nicht erstellt werden.") from None
    if result.returncode or not target.is_file() or not 0 < target.stat().st_size <= MAX_PROXY_BYTES:
        raise RuntimeError("Das lokale Analysevideo ist unlesbar oder zu groß.")
    return target
