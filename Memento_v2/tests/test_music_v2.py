from pathlib import Path
from threading import Event
import subprocess

import cv2
import imageio_ffmpeg
import numpy as np
import pytest

from memento.application.music import SoundtrackRenderService
from memento.application.rendering import RenderCancelled, RenderSettings
from memento.domain.editing import EditingStyle
from test_movie_rendering import make_plan


def test_soundtrack_is_mixed_into_real_export_and_originals_are_unchanged(tmp_path):
    plan = make_plan(tmp_path)
    plan.editing_style = EditingStyle("random", 0.5)
    originals = {item.source.path: Path(item.source.path).read_bytes() for item in plan.segments}
    music = tmp_path / "music.wav"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=880:duration=1", str(music)], check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    music_bytes = music.read_bytes()
    renderer = SoundtrackRenderService(tmp_path / "renders", str(music))
    output = tmp_path / "with-music.mp4"
    renderer.render(plan, output, Event(), settings=RenderSettings(160, 90, 24))
    capture = cv2.VideoCapture(str(output))
    assert capture.get(cv2.CAP_PROP_FRAME_COUNT) == 84
    capture.release()
    raw = subprocess.run([renderer.ffmpeg, "-v", "error", "-i", str(output), "-f", "f32le",
                          "-ac", "1", "-ar", "8000", "pipe:1"], capture_output=True, check=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    samples = np.frombuffer(raw.stdout, dtype=np.float32)
    # The second source is silent; the repeated soundtrack must still be audible.
    assert np.mean(np.abs(samples[17000:20000])) > 0.002
    assert music.read_bytes() == music_bytes
    assert all(Path(path).read_bytes() == value for path, value in originals.items())
    assert not list(tmp_path.glob("memento-music-*"))
    with pytest.raises(ValueError):
        renderer.render(plan, output, Event())
    token = Event()
    token.set()
    with pytest.raises(RenderCancelled):
        renderer.render(plan, tmp_path / "cancelled.mp4", token)
    assert not (tmp_path / "cancelled.mp4").exists()
