"""Local, resumable movie rendering, adapted from UltraCut's FFmpeg stages.

Normalized per-segment H.264/AAC files, a concat pass and atomic publication
preserve the prototype's reliable path. Optional templates render bounded pairs
of neighboring clips. Successful parts survive cancellation and process restarts.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from threading import Event

import imageio_ffmpeg

from memento.domain.movie import MoviePlan
from memento.domain.editing import EDITING_TEMPLATES
from memento.media.metadata import MediaProbeCancelled, _run_command, probe_media
from memento.media.identity import hash_media


RENDER_VERSION = "hard-cut-h264-aac-v3"


class RenderCancelled(RuntimeError):
    pass


class RenderValidationError(RuntimeError):
    """Generated output is undecodable or does not contain the planned frames."""


@dataclass(frozen=True, slots=True)
class RenderSettings:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    crf: int = 20

    def validate(self):
        if any(type(value) is not int for value in (self.width, self.height, self.fps, self.crf)):
            raise ValueError("Ungültige Exporteinstellungen.")
        if not (16 <= self.width <= 3840 and 16 <= self.height <= 3840 and self.width % 2 == self.height % 2 == 0
                and 1 <= self.fps <= 60 and 16 <= self.crf <= 30):
            raise ValueError("Ungültige Exporteinstellungen.")


@dataclass(frozen=True, slots=True)
class RenderProgress:
    completed: int
    total: int
    cached: int
    message: str


class MovieRenderService:
    def __init__(self, cache_root: Path, executable: str | None = None):
        self.cache_root = Path(cache_root)
        if os.name == "nt":
            # FFmpeg can create paths beyond MAX_PATH even when Python's normal
            # Win32 file operations cannot reopen/rename them. Keep every cache
            # operation on an absolute extended-length path, including cleanup
            # and resume. This requires no machine-wide long-path policy.
            cache = str(self.cache_root.resolve())
            if not cache.startswith("\\\\?\\"):
                cache = "\\\\?\\UNC\\" + cache[2:] if cache.startswith("\\\\") else "\\\\?\\" + cache
            self.cache_root = Path(cache)
        self.ffmpeg = executable or imageio_ffmpeg.get_ffmpeg_exe()

    def render(self, plan: MoviePlan, output: Path, token: Event, on_progress=None,
               settings: RenderSettings | None = None):
        plan.validate()
        settings = settings or RenderSettings()
        settings.validate()
        enabled = [segment for segment in plan.segments if segment.enabled]
        if not enabled:
            raise ValueError("Der Film enthält keine aktiven Segmente.")
        target = Path(output).resolve()
        if target.suffix.casefold() != ".mp4":
            raise ValueError("Das Exportziel muss eine MP4-Datei sein.")
        # Protect every referenced original, including currently disabled clips.
        if any(target == Path(item.source.path).resolve() for item in plan.segments):
            raise ValueError("Das Exportziel darf keine Quelldatei sein.")
        if target.exists():
            raise ValueError("Die Zieldatei existiert bereits. Bitte einen neuen Dateinamen wählen; vorhandene Videos werden nicht überschrieben.")
        for segment in enabled:
            self._source_unchanged(segment.source)
        identity = {"version": RENDER_VERSION, "settings": asdict(settings),
                    "segments": [asdict(segment) for segment in enabled]}
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        work = self.cache_root / key
        work.mkdir(parents=True, exist_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        manifest_path = work / "job.json"
        manifest = {"status": "running", "output": str(target), "parts": {}}
        if manifest_path.is_file():
            try:
                old = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(old.get("parts"), dict):
                    manifest["parts"] = old["parts"]
            except (ValueError, OSError):
                pass
        self._write_json(manifest_path, manifest)
        cached = 0
        movie_frames = 0
        part_frames = []
        verified_sources = set()
        temporary_output = None
        try:
            for index, segment in enumerate(enabled):
                self._check_cancel(token)
                self._source_unchanged(segment.source)
                if segment.source.content_sha256 and segment.source.asset_id not in verified_sources:
                    if on_progress:
                        on_progress(RenderProgress(index, len(enabled) + 1, cached, "Prüfe den vollständigen Quellinhalt"))
                    if hash_media(Path(segment.source.path), token) != segment.source.content_sha256:
                        raise ValueError("Der Quellinhalt stimmt nicht mit dem Filmplan überein. Bitte neu indexieren und die Quelle prüfen.")
                    verified_sources.add(segment.source.asset_id)
                part = work / f"part-{index:06d}.mp4"
                signature = self._signature(part) if part.is_file() else None
                expected_frames = max(1, math.ceil(segment.duration * settings.fps - 1e-6))
                reusable = signature is not None and manifest["parts"].get(str(index)) == signature
                if reusable:
                    try:
                        frames = self._validate_video(part, expected_frames, token, allow_shorter=True)
                    except RenderValidationError:
                        # A matching file stat is not proof of intact contents.
                        # Rebuild this generated part; keep other completed work.
                        reusable = False
                        manifest["parts"].pop(str(index), None)
                if reusable:
                    cached += 1
                else:
                    pending = work / f"part-{index:06d}.pending.mp4"
                    # Probe actual audio presence even when indexing used a
                    # limited fallback; never invent/mute a source audio track.
                    metadata = probe_media(Path(segment.source.path), cancel_token=token)
                    if metadata.has_audio is None:
                        raise ValueError("Die Audiospur der Quelle konnte nicht sicher geprüft werden.")
                    command = self._segment_command(segment, pending, settings, metadata.has_audio)
                    self._run(command, token)
                    frames = self._validate_video(pending, expected_frames, token, allow_shorter=True)
                    self._source_unchanged(segment.source)
                    os.replace(pending, part)
                    manifest["parts"][str(index)] = self._signature(part)
                    self._write_json(manifest_path, manifest)
                movie_frames += frames
                part_frames.append(frames)
                if on_progress:
                    on_progress(RenderProgress(index + 1, len(enabled) + 1, cached,
                                               f"Segment {index + 1} von {len(enabled)} vorbereitet"
                                               + (" · kürzere verfügbare Videolänge übernommen"
                                                  if frames < expected_frames - 1 else "")))
            self._check_cancel(token)
            concat = work / "concat.txt"
            # Paths in the concat file are generated relative names, so quotes
            # and Unicode in source paths never become concat directives.
            parts = [f"part-{index:06d}.mp4" for index in range(len(enabled))]
            if plan.editing_style.template != "cut" and len(enabled) > 1:
                parts, movie_frames = self._styled_parts(work, plan.editing_style, part_frames,
                                                        settings, token, on_progress, cached)
            concat.write_text("".join(f"file '{name}'\n" for name in parts), encoding="utf-8")
            descriptor, name = tempfile.mkstemp(prefix=".memento-render-", suffix=".mp4", dir=target.parent)
            os.close(descriptor)
            temporary_output = Path(name)
            # The concat demuxer resolves relative entries as URLs and cannot
            # resolve them against a Win32 device-path prefix. FFmpeg supports
            # ordinary long Windows paths itself; only Python needs the prefix.
            concat_input = str(concat)
            if concat_input.startswith("\\\\?\\UNC\\"):
                concat_input = "\\\\" + concat_input[8:]
            elif concat_input.startswith("\\\\?\\"):
                concat_input = concat_input[4:]
            self._run([self.ffmpeg, "-nostdin", "-y", "-v", "error", "-f", "concat", "-safe", "1", "-i", concat_input,
                       "-c", "copy", "-map_metadata", "-1", "-movflags", "+faststart", str(temporary_output)], token)
            if on_progress:
                on_progress(RenderProgress(len(enabled), len(enabled) + 1, cached, "Prüfe den zusammengesetzten Film"))
            self._validate_video(temporary_output, movie_frames, token, tolerance=0)
            for segment in enabled:
                self._source_unchanged(segment.source)
            self._check_cancel(token)
            # Publish atomically without clobbering an original that might have
            # appeared at the destination while rendering was in progress.
            if os.name == "nt":
                # Windows rename is atomic and refuses an existing destination;
                # unlike hard links it also works on common exFAT export drives.
                os.rename(temporary_output, target)
            else:
                os.link(temporary_output, target)
                temporary_output.unlink()
            manifest["status"] = "complete"
            self._write_json(manifest_path, manifest)
            if on_progress:
                on_progress(RenderProgress(len(enabled) + 1, len(enabled) + 1, cached, "Film exportiert"))
            return target
        except (RenderCancelled, MediaProbeCancelled):
            manifest["status"] = "cancelled"
            self._write_json(manifest_path, manifest)
            raise RenderCancelled("Export abgebrochen; fertige Segmente bleiben für die Wiederaufnahme gespeichert.") from None
        except Exception:
            manifest["status"] = "failed"
            self._write_json(manifest_path, manifest)
            raise
        finally:
            if temporary_output is not None:
                temporary_output.unlink(missing_ok=True)
            # Pending files are never reusable. Constrain deletion to this job.
            for pending in work.glob("part-*.pending.mp4"):
                pending.unlink(missing_ok=True)

    def _styled_parts(self, work, style, frames, settings, token, on_progress, cached):
        """Render bodies and two-input boundaries, keeping memory bounded for long films.

        Only neighboring tails/heads enter xfade, rather than decoding every full
        clip simultaneously. Completed styled pieces are independently resumable;
        normalized originals remain shared across template changes.
        """
        overlaps = style.overlap_frames(frames, settings.fps)
        identity = {"version": "editing-pieces-v1", "style": asdict(style), "frames": frames}
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
        directory = work / f"style-{key}"
        directory.mkdir(exist_ok=True)
        parts = []
        total_frames = 0
        fps = settings.fps

        def piece(name, count, command):
            nonlocal total_frames
            self._check_cancel(token)
            path = directory / f"{name}.mp4"
            try:
                self._validate_video(path, count, token, tolerance=0)
            except RenderValidationError:
                pending = directory / f"{name}.pending.mp4"
                try:
                    self._run(command + self._encoding_settings(settings) + [str(pending)], token)
                    self._validate_video(pending, count, token, tolerance=0)
                    os.replace(pending, path)
                finally:
                    pending.unlink(missing_ok=True)
            parts.append(f"{directory.name}/{path.name}")
            total_frames += count

        for index, count in enumerate(frames):
            incoming = overlaps[index - 1] if index else 0
            outgoing = overlaps[index] if index < len(overlaps) else 0
            source = work / f"part-{index:06d}.mp4"
            prefix = [self.ffmpeg, "-nostdin", "-y", "-v", "error", "-filter_complex_threads", "1"]
            if count > incoming + outgoing:
                graph = (f"[0:v]trim=start_frame={incoming}:end_frame={count-outgoing},setpts=PTS-STARTPTS[v];"
                         f"[0:a]atrim=start={incoming/fps:.9f}:end={(count-outgoing)/fps:.9f},"
                         "asetpts=PTS-STARTPTS[a]")
                piece(f"body-{index:06d}", count - incoming - outgoing,
                      prefix + ["-i", str(source), "-filter_complex", graph, "-map", "[v]", "-map", "[a]"])
            if outgoing:
                duration = outgoing / fps
                transition = style.transition(index)
                # Explicit timebase and frame trimming avoid accumulated rounding.
                graph = (
                    f"[0:v]trim=start_frame={count-outgoing}:end_frame={count},setpts=PTS-STARTPTS,fps={fps},settb=1/{fps}[left];"
                    f"[1:v]trim=end_frame={outgoing},setpts=PTS-STARTPTS,fps={fps},settb=1/{fps}[right];"
                    f"[left][right]xfade=transition={transition}:duration={duration:.9f}:offset=0,"
                    f"trim=end_frame={outgoing},format=yuv420p[v];"
                    f"[0:a]apad,atrim=start={(count-outgoing)/fps:.9f}:end={count/fps:.9f},asetpts=PTS-STARTPTS[al];"
                    f"[1:a]apad,atrim=end={duration:.9f},asetpts=PTS-STARTPTS[ar];"
                    f"[al][ar]acrossfade=d={duration:.9f}:c1=tri:c2=tri[a]")
                piece(f"transition-{index:06d}", outgoing,
                      prefix + ["-i", str(source), "-i", str(work / f"part-{index+1:06d}.mp4"),
                                "-filter_complex", graph, "-map", "[v]", "-map", "[a]"])
            if on_progress:
                on_progress(RenderProgress(index + 1, len(frames) + 1, cached,
                                           f"Schnittvorlage: Clipwechsel {index + 1} von {len(frames)} vorbereitet"))
        return parts, total_frames

    @staticmethod
    def _encoding_settings(settings):
        return ["-r", str(settings.fps), "-fps_mode", "cfr", "-c:v", "libx264", "-preset", "medium",
                "-crf", str(settings.crf), "-c:a", "aac", "-ar", "48000", "-ac", "2",
                "-map_metadata", "-1", "-map_chapters", "-1", "-movflags", "+faststart"]

    def _segment_command(self, segment, output, settings, has_audio):
        duration = segment.duration
        video = (f"scale={settings.width}:{settings.height}:force_original_aspect_ratio=decrease,"
                 f"pad={settings.width}:{settings.height}:(ow-iw)/2:(oh-ih)/2:black,"
                 f"setsar=1,setpts=PTS-STARTPTS,fps={settings.fps},format=yuv420p")
        command = [self.ffmpeg, "-nostdin", "-y", "-v", "error", "-ss", f"{segment.start_seconds:.6f}",
                   "-i", segment.source.path]
        if has_audio:
            command += ["-filter_complex", f"[0:v:0]{video}[v];[0:a:0]aresample=48000,apad,atrim=0:{duration:.6f},asetpts=PTS-STARTPTS[a]",
                        "-map", "[v]", "-map", "[a]"]
        else:
            command += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                        "-filter_complex", f"[0:v:0]{video}[v]", "-map", "[v]", "-map", "1:a:0"]
        command += ["-t", f"{duration:.6f}", "-shortest", "-r", str(settings.fps), "-fps_mode", "cfr",
                    "-c:v", "libx264", "-preset", "medium", "-crf", str(settings.crf),
                    "-c:a", "aac", "-ar", "48000", "-ac", "2", "-map_metadata", "-1", "-map_chapters", "-1",
                    "-movflags", "+faststart", str(output)]
        return command

    def _run(self, command, token):
        self._check_cancel(token)
        try:
            result = _run_command(command, timeout=12 * 60 * 60, cancel_token=token)
        except MediaProbeCancelled:
            raise RenderCancelled("Export abgebrochen.") from None
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError("FFmpeg konnte den Export nicht ausführen.") from None
        if result.returncode:
            raise RuntimeError("FFmpeg konnte einen Exportabschnitt nicht erstellen. Quelldatei und freien Speicher prüfen.")

    def _validate_video(self, path, expected_frames, token, *, tolerance=1, allow_shorter=False):
        """Decode generated video/audio, then check CFR frame coverage.

        Counting decoded frames avoids container duration inflated by padded
        audio. Source duration metadata may overestimate available video, so
        normalized segments may be shorter. Concat must preserve their actual
        frame sum. Empty or undecodable output is never published.
        """
        self._check_cancel(token)
        try:
            result = _run_command([self.ffmpeg, "-nostdin", "-v", "error", "-xerror", "-err_detect", "explode",
                "-i", str(path), "-map", "0:v:0", "-map", "0:a:0", "-fps_mode", "passthrough",
                "-progress", "pipe:1", "-stats_period", "60", "-nostats", "-f", "null", "-"],
                timeout=12 * 60 * 60, cancel_token=token)
        except MediaProbeCancelled:
            raise RenderCancelled("Exportprüfung abgebrochen.") from None
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError("FFmpeg konnte die Exportprüfung nicht ausführen.") from None
        values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        try:
            frames = int(values.get("frame", "0"))
        except ValueError:
            frames = 0
        if result.returncode or values.get("progress") != "end" or frames <= 0:
            raise RenderValidationError("Die Exportdatei konnte nicht vollständig mit Bild und Ton gelesen werden.")
        if frames > expected_frames + tolerance or (not allow_shorter and frames < expected_frames - tolerance):
            raise RenderValidationError("Die Exportdatei enthält nicht die geplante Videolänge. Quelle und Schnittgrenzen prüfen.")
        return frames

    @staticmethod
    def _check_cancel(token):
        if token.is_set():
            raise RenderCancelled("Export abgebrochen.")

    @staticmethod
    def _source_unchanged(source):
        stat = Path(source.path).stat()
        modified = datetime.fromtimestamp(stat.st_mtime).astimezone()
        if stat.st_size != source.size_bytes or modified != datetime.fromisoformat(source.modified_at):
            raise ValueError("Eine Quelle wurde seit der Planung verändert. Neu indexieren und den Filmplan prüfen.")

    @staticmethod
    def _signature(path):
        stat = path.stat()
        return [stat.st_size, stat.st_mtime_ns] if stat.st_size > 0 else None

    @staticmethod
    def _write_json(path, payload):
        descriptor, name = tempfile.mkstemp(prefix=".job-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)
