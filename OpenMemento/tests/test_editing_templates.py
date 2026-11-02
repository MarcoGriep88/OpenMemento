"""Real FFmpeg checks of template pictures, duration, audio and saved projects."""
from copy import deepcopy
import json
import os
import subprocess
from pathlib import Path
from threading import Event

import cv2
import numpy as np
import pytest

from memento.application.rendering import MovieRenderService, RenderCancelled, RenderSettings
from memento.domain.editing import EDITING_TEMPLATES, EditingStyle
from memento.domain.movie import MovieEvent
from memento.library.movies import load_movie, save_movie
from test_movie_rendering import make_plan


@pytest.mark.parametrize("template", list(EDITING_TEMPLATES))
def test_templates_real_render_and_cache(tmp_path, template):
    plan = make_plan(tmp_path)
    original = deepcopy(plan.segments)
    source_bytes = {item.source.path: Path(item.source.path).read_bytes() for item in original}
    plan.editing_style = EditingStyle(template, 0.5)
    output = tmp_path / "edited.mp4"
    renderer = MovieRenderService(tmp_path / "renders")
    settings = RenderSettings(160, 90, 24)
    renderer.render(plan, output, Event(), settings=settings)
    capture = cv2.VideoCapture(str(output))
    frames = []
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frames.append(frame[45, 80].astype(float))
        assert capture.get(cv2.CAP_PROP_FPS) == 24
    finally:
        capture.release()
    assert len(frames) == (96 if template == "cut" else 84)
    assert frames[0][2] > 200 and frames[-1][0] > 200
    if template == "crossfade":
        assert frames[42][0] > 60 and frames[42][2] > 60
    if template == "black":
        assert min(max(frame) for frame in frames[36:48]) < 35
    assert plan.playback_duration == pytest.approx(len(frames) / 24)
    assert plan.segments == original
    assert all(Path(path).read_bytes() == value for path, value in source_bytes.items())
    audio = subprocess.run(
        [renderer.ffmpeg, "-v", "error", "-i", str(output), "-f", "f32le", "-ac", "1", "-ar", "8000", "pipe:1"],
        capture_output=True, check=True, timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    samples = np.frombuffer(audio.stdout, dtype=np.float32)
    assert np.mean(np.abs(samples[2000:8000])) > 0.01
    assert np.mean(np.abs(samples[-4000:])) < 0.001
    # An unchanged retry reuses both normalized sources and completed style pieces.
    progress = []
    before = {p: p.stat().st_mtime_ns for p in (tmp_path / "renders").rglob("*.mp4")}
    renderer.render(plan, tmp_path / "again.mp4", Event(), progress.append, settings)
    assert progress[-1].cached == 2
    assert all(path.stat().st_mtime_ns == stamp for path, stamp in before.items())


def test_style_project_roundtrip_and_old_projects(tmp_path):
    plan = make_plan(tmp_path)
    plan.editing_style = EditingStyle("blurfade", 1.2)
    path = tmp_path / "test.memento.json"
    save_movie(path, plan)
    assert load_movie(path) == plan
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["format_version"] = 3
    del payload["movie"]["editing_style"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_movie(path).editing_style == EditingStyle()


@pytest.mark.parametrize("style", [EditingStyle("unknown"), EditingStyle("cut", float("nan")),
                                  EditingStyle("zoom", 0), EditingStyle("black", 3)])
def test_invalid_styles_rejected(style):
    with pytest.raises(ValueError):
        style.validate()


def test_short_disabled_single_and_many_segments(tmp_path):
    plan = make_plan(tmp_path)
    # Adjacent overlaps never consume more than either short clip can supply.
    style = EditingStyle("crossfade", 2)
    assert style.overlap_frames([1, 2, 3, 100], 24) == [0, 1, 1]
    assert sum(style.overlap_frames([2] * 25, 24)) == 24
    plan.editing_style = style
    plan.segments[1].enabled = False
    plan.segments[0].end_seconds = plan.segments[0].start_seconds + 1 / 24
    output = tmp_path / "single.mp4"
    MovieRenderService(tmp_path / "renders").render(plan, output, Event(), settings=RenderSettings(160, 90, 24))
    assert plan.playback_duration == pytest.approx(1 / 24)


def test_style_cancel_and_change_share_normalized_parts(tmp_path):
    plan = make_plan(tmp_path)
    plan.editing_style = EditingStyle("crossfade", 0.5)
    token = Event()
    renderer = MovieRenderService(tmp_path / "renders")
    settings = RenderSettings(160, 90, 24)
    def cancel(progress):
        if "Schnittvorlage" in progress.message:
            token.set()
    with pytest.raises(RenderCancelled):
        renderer.render(plan, tmp_path / "cancelled.mp4", token, cancel, settings)
    assert not (tmp_path / "cancelled.mp4").exists()
    assert not list((tmp_path / "renders").rglob("*.pending.mp4"))
    token.clear()
    plan.editing_style = EditingStyle("zoom", 0.8)
    progress = []
    renderer.render(plan, tmp_path / "zoom.mp4", token, progress.append, settings)
    assert progress[-1].cached == 2


@pytest.mark.skipif(os.name != "nt", reason="Windows MAX_PATH regression")
def test_long_windows_cache_render_cancel_and_resume(tmp_path):
    plan = make_plan(tmp_path)
    plan.editing_style = EditingStyle("crossfade", 0.5)
    # Installer smoke nests the cache enough that a transition pending file
    # exceeds 260 characters. Exercise even longer paths without changing OS
    # policy, while source media and exported movies remain at ordinary paths.
    cache = tmp_path / ("cache-" + "a" * 70) / ("nested-" + "b" * 70)
    renderer = MovieRenderService(cache)
    settings = RenderSettings(160, 90, 24)
    token = Event()

    def cancel(progress):
        if "Schnittvorlage" in progress.message:
            token.set()

    with pytest.raises(RenderCancelled):
        renderer.render(plan, tmp_path / "cancelled.mp4", token, cancel, settings)
    assert not (tmp_path / "cancelled.mp4").exists()
    assert not list(renderer.cache_root.rglob("*.pending.mp4"))
    pieces = list(renderer.cache_root.rglob("style-*/*.mp4"))
    assert pieces and all(len(str(path)) > 260 for path in pieces)
    before = {path: path.stat().st_mtime_ns for path in pieces}
    token.clear()
    # A new service instance must reopen and reuse the same long cache paths.
    renderer = MovieRenderService(cache)
    progress = []
    output = tmp_path / "resumed.mp4"
    renderer.render(plan, output, token, progress.append, settings)
    assert renderer._validate_video(output, 84, token, tolerance=0) == 84
    assert progress[-1].cached == 2
    assert all(path.stat().st_mtime_ns == stamp for path, stamp in before.items())
    assert not list(renderer.cache_root.rglob("*.pending.mp4"))


def test_25_short_clips_keep_all_prepared_frames_except_overlaps(tmp_path):
    plan = make_plan(tmp_path)
    first = plan.segments[0]
    plan.segments = []
    for index in range(25):
        segment = deepcopy(first)
        segment.candidate_id = str(index)
        segment.start_seconds = index * 0.12
        segment.end_seconds = (index + 1) * 0.12
        plan.segments.append(segment)
    plan.events = [MovieEvent(first.event_id, "Kurze Momente", tuple(str(i) for i in range(25)))]
    plan.editing_style = EditingStyle("crossfade", 0.6)
    renderer = MovieRenderService(tmp_path / "renders")
    output = tmp_path / "short-movie.mp4"
    renderer.render(plan, output, Event(), settings=RenderSettings(160, 90, 24))
    counts = []
    for part in sorted((tmp_path / "renders").glob("*/part-*.mp4")):
        capture = cv2.VideoCapture(str(part))
        try:
            counts.append(int(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        finally:
            capture.release()
    assert len(counts) == 25
    expected = sum(counts) - sum(plan.editing_style.overlap_frames(counts, 24))
    assert renderer._validate_video(output, expected, Event(), tolerance=0) == expected
    capture = cv2.VideoCapture(str(output))
    try:
        assert capture.get(cv2.CAP_PROP_FPS) == 24
    finally:
        capture.release()
