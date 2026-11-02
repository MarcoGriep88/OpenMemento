"""Local soundtrack mixing; no media is sent to a music service."""
from __future__ import annotations

from pathlib import Path
from threading import Event
import os
import tempfile

from memento.application.rendering import MovieRenderService, RenderSettings


def music_prompt(candidates, title, target_seconds, *, language="de"):
    events = list(dict.fromkeys(item.event_label for item in candidates if item.event_label))[:12]
    descriptions = list(dict.fromkeys(item.description for item in candidates if item.description))[:12]
    if not descriptions:
        raise ValueError("Bitte zuerst die Gemini-Analyse für dieses Projekt ausführen.")
    if language == "en":
        return (f'Instrumental soundtrack for the family movie “{title}”, approx. {target_seconds / 60:g} minutes. '
                "Warm, personal and melodic; a calm opening, lively middle and gentle ending. "
                "No vocals; leave room for original audio and conversations. "
                + "Events: " + "; ".join(events) + ". Moments: " + "; ".join(descriptions))[:3500]
    return (f"Instrumentaler Soundtrack für den Familienfilm „{title}“, ca. {target_seconds / 60:g} Minuten. "
            "Warm, persönlich, melodisch; ruhiger Beginn, lebendiger Mittelteil, sanfter Abschluss. "
            "Keine Vocals, Raum für Originalton und Gespräche. "
            + "Ereignisse: " + "; ".join(events) + ". Momente: " + "; ".join(descriptions))[:3500]


class SoundtrackRenderService(MovieRenderService):
    def __init__(self, cache_root, music_path="", executable=None):
        super().__init__(cache_root, executable)
        self.music_path = music_path

    def render(self, plan, output, token, on_progress=None, settings=None):
        if not self.music_path:
            return super().render(plan, output, token, on_progress, settings)
        music = Path(self.music_path).resolve()
        if not music.is_file():
            raise ValueError("Die ausgewählte Musikdatei ist nicht mehr erreichbar.")
        target = Path(output).resolve()
        if target == music or target.exists():
            raise ValueError("Das Exportziel existiert bereits oder ist die Musikquelle.")
        if any(target == Path(item.source.path).resolve() for item in plan.segments):
            raise ValueError("Das Exportziel darf keine Quelldatei sein.")
        target.parent.mkdir(parents=True, exist_ok=True)
        settings = settings or RenderSettings()
        # The normal render remains resumable; soundtrack publication is atomic too.
        with tempfile.TemporaryDirectory(prefix="memento-music-", dir=target.parent) as directory:
            movie = Path(directory) / "movie.mp4"
            mixed = Path(directory) / "mixed.mp4"
            super().render(plan, movie, token, on_progress, settings)
            from memento.media.metadata import probe_media
            duration = probe_media(movie, cancel_token=token).duration_seconds
            if not duration:
                raise ValueError("Die gerenderte Filmlänge konnte nicht bestimmt werden.")
            graph = (f"[1:a]aresample=48000,volume=0.22,apad,atrim=duration={duration:.9f},"
                     f"afade=t=out:st={max(0, duration-2):.9f}:d={min(2,duration):.9f}[music];"
                     "[0:a][music]amix=inputs=2:duration=first:normalize=0:dropout_transition=0,alimiter=limit=0.95[a]")
            self._run([self.ffmpeg, "-nostdin", "-y", "-v", "error", "-i", str(movie),
                       "-stream_loop", "-1", "-i", str(music), "-filter_complex", graph,
                       "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
                       "-ar", "48000", "-ac", "2", "-t", f"{duration:.9f}",
                       "-map_metadata", "-1", "-movflags", "+faststart", str(mixed)], token)
            self._validate_video(mixed, round(duration * settings.fps), token)
            self._check_cancel(token)
            if os.name == "nt":
                os.rename(mixed, target)
            else:
                os.link(mixed, target)
            return target
