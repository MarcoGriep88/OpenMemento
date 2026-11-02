from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from threading import Event

import cv2
import imageio_ffmpeg
import numpy as np
import pytest

from memento.application.movie_planning import MoviePlanningService
from memento.application.rendering import MovieRenderService, RenderCancelled, RenderSettings, RenderValidationError
from memento.ai.contracts import Moment, SemanticResult
from memento.domain.media import CaptureTime, MediaAsset, TimestampSource
from memento.library.database import MediaLibrary
from memento.library.semantic import SemanticRepository
from memento.media.metadata import _run_command


def make_plan(tmp_path):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    repo = SemanticRepository(library)
    for index, (color, size, audio) in enumerate((("red", "96x64", True), ("blue", "64x96", False))):
        source = tmp_path / f"source-{index}.mp4"
        command = [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s={size}:r=24:d=3"]
        if audio:
            command += ["-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:a", "aac"]
        command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)]
        assert _run_command(command, 20, None).returncode == 0
        asset = library.save_asset(MediaAsset(str(index), source, source.stat().st_size,
            datetime.fromtimestamp(source.stat().st_mtime).astimezone(),
            CaptureTime(datetime(2026, 7, 12, 10 + index), TimestampSource.QUICKTIME, 0.9),
            duration_seconds=3, width=96 if index == 0 else 64, height=64 if index == 0 else 96,
            has_audio=audio))
        job = repo.create_job([asset], "gemini", "test-model")
        moment = Moment(0.5, 2.5, f"Moment {index}", "Familienausflug", (), (), 0.9, 0.9, 0.8, 1, 0.9, ("Erinnerung",))
        repo.save_result(repo.get_job(job), repo.items(job)[0], SemanticResult((moment,)))
    return MoviePlanningService(repo).build(date(2026, 7, 12), date(2026, 7, 12), 4, "gemini", "test-model")


def test_real_render_mixed_aspects_audio_order_duration_and_originals(tmp_path):
    plan = make_plan(tmp_path)
    before = {item.source.path: Path(item.source.path).read_bytes() for item in plan.segments}
    target = tmp_path / "family.mp4"
    progress = []
    service = MovieRenderService(tmp_path / "renders")
    assert service.render(plan, target, Event(), progress.append, RenderSettings(160, 90, 24)) == target
    capture = cv2.VideoCapture(str(target))
    try:
        duration = capture.get(cv2.CAP_PROP_FRAME_COUNT) / capture.get(cv2.CAP_PROP_FPS)
        assert duration == pytest.approx(4, abs=0.15)
        assert capture.get(cv2.CAP_PROP_FRAME_WIDTH) == 160
        capture.set(cv2.CAP_PROP_POS_MSEC, 500)
        ok, first = capture.read()
        assert ok and first[45, 80, 2] > first[45, 80, 0] + 100
        capture.set(cv2.CAP_PROP_POS_MSEC, 3000)
        ok, last = capture.read()
        assert ok and last[45, 80, 0] > last[45, 80, 2] + 100
    finally:
        capture.release()
    probe = _run_command([service.ffmpeg, "-hide_banner", "-i", str(target)], 15, None)
    assert "Audio: aac" in probe.stderr
    audio = subprocess.run([service.ffmpeg, "-v", "error", "-i", str(target), "-f", "f32le", "-ac", "1", "-ar", "8000", "pipe:1"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    samples = np.frombuffer(audio.stdout, dtype=np.float32)
    assert np.mean(np.abs(samples[4000:12000])) > 0.01
    assert np.mean(np.abs(samples[24000:30000])) < 0.001
    for path, original in before.items():
        with open(path, "rb") as stream:
            assert stream.read() == original
    assert progress[-1].completed == progress[-1].total
    assert not list(tmp_path.glob(".memento-render-*"))


def test_cancelled_render_resumes_cached_parts_after_new_service_instance(tmp_path):
    plan = make_plan(tmp_path)
    token = Event()
    service = MovieRenderService(tmp_path / "renders")
    target = tmp_path / "movie.mp4"
    settings = RenderSettings(160, 90, 24)
    with pytest.raises(RenderCancelled):
        service.render(plan, target, token, lambda progress: token.set(), settings)
    assert not target.exists()
    manifest = next((tmp_path / "renders").glob("*/job.json"))
    assert json.loads(manifest.read_text())["status"] == "cancelled"
    assert len(json.loads(manifest.read_text())["parts"]) == 1
    progress = []
    MovieRenderService(tmp_path / "renders").render(plan, target, Event(), progress.append, settings)
    assert progress[-1].cached == 1
    assert json.loads(manifest.read_text())["status"] == "complete"


def test_render_refuses_sources_existing_targets_and_changed_files(tmp_path):
    from pathlib import Path

    plan = make_plan(tmp_path)
    service = MovieRenderService(tmp_path / "renders")
    source = Path(plan.segments[0].source.path)
    original = source.read_bytes()
    with pytest.raises(ValueError, match="Quelldatei"):
        service.render(plan, source, Event())
    assert source.read_bytes() == original
    unrelated = tmp_path / "unrelated-original.mp4"
    unrelated.write_bytes(b"other original")
    with pytest.raises(ValueError, match="existiert"):
        service.render(plan, unrelated, Event())
    assert unrelated.read_bytes() == b"other original"
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="verändert"):
        service.render(plan, tmp_path / "new.mp4", Event())


def test_failure_keeps_originals_and_cleans_unpublished_output(tmp_path, monkeypatch):
    plan = make_plan(tmp_path)
    service = MovieRenderService(tmp_path / "renders")
    target = tmp_path / "movie.mp4"
    real_run = service._run

    def fail_concat(command, token):
        if "concat" in command:
            from pathlib import Path
            Path(command[-1]).write_bytes(b"incomplete output")
            raise RuntimeError("simulated disk failure")
        real_run(command, token)

    monkeypatch.setattr(service, "_run", fail_concat)
    with pytest.raises(RuntimeError, match="simulated"):
        service.render(plan, target, Event(), settings=RenderSettings(160, 90, 24))
    assert not target.exists()
    assert not list(tmp_path.glob(".memento-render-*"))
    manifest = next((tmp_path / "renders").glob("*/job.json"))
    assert json.loads(manifest.read_text())["status"] == "failed"


def test_destination_appearing_during_render_is_not_overwritten(tmp_path, monkeypatch):
    plan = make_plan(tmp_path)
    service = MovieRenderService(tmp_path / "renders")
    target = tmp_path / "movie.mp4"
    real_run = service._run

    def destination_race(command, token):
        real_run(command, token)
        if "concat" in command:
            target.write_bytes(b"original appeared during render")

    monkeypatch.setattr(service, "_run", destination_race)
    with pytest.raises(FileExistsError):
        service.render(plan, target, Event(), settings=RenderSettings(160, 90, 24))
    assert target.read_bytes() == b"original appeared during render"
    assert not list(tmp_path.glob(".memento-render-*"))


def test_early_source_end_exports_available_video_and_resumes(tmp_path):
    plan = make_plan(tmp_path)
    # A stale duration can claim more video than the unchanged source contains.
    # Export the available frames instead of enforcing stale duration metadata.
    plan.segments[0].source = replace(plan.segments[0].source, duration_seconds=5)
    plan.segments[0].end_seconds = 4.5
    plan.validate()
    source = Path(plan.segments[0].source.path)
    before = source.read_bytes()
    service = MovieRenderService(tmp_path / "renders")
    target = tmp_path / "too-short.mp4"
    settings = RenderSettings(160, 90, 24)
    progress = []
    service.render(plan, target, Event(), progress.append, settings)
    assert target.exists()
    assert any("kürzere" in item.message for item in progress)
    capture = cv2.VideoCapture(str(target))
    try:
        assert capture.get(cv2.CAP_PROP_FRAME_COUNT) == pytest.approx(108, abs=1)
    finally:
        capture.release()
    manifest = next((tmp_path / "renders").glob("*/job.json"))
    assert json.loads(manifest.read_text())["status"] == "complete"
    assert len(json.loads(manifest.read_text())["parts"]) == 2
    assert not list(manifest.parent.glob("*.pending.mp4"))
    assert not list(tmp_path.glob(".memento-render-*"))
    assert source.read_bytes() == before
    service.render(plan, tmp_path / "resumed-short.mp4", Event(), progress.append, settings)
    assert progress[-1].cached == 2


def test_same_stat_corrupt_cached_part_is_rebuilt_while_good_part_is_reused(tmp_path):
    plan = make_plan(tmp_path)
    settings = RenderSettings(160, 90, 24)
    service = MovieRenderService(tmp_path / "renders")
    service.render(plan, tmp_path / "first.mp4", Event(), settings=settings)
    manifest = next((tmp_path / "renders").glob("*/job.json"))
    damaged = manifest.parent / "part-000000.mp4"
    valid = manifest.parent / "part-000001.mp4"
    valid_stat = valid.stat()
    original_stat = damaged.stat()
    damaged.write_bytes(bytes(original_stat.st_size))
    os.utime(damaged, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert service._signature(damaged) == json.loads(manifest.read_text())["parts"]["0"]
    progress = []
    target = tmp_path / "recovered.mp4"
    MovieRenderService(tmp_path / "renders").render(plan, target, Event(), progress.append, settings)
    assert target.exists() and progress[-1].cached == 1
    assert valid.stat().st_mtime_ns == valid_stat.st_mtime_ns
    assert damaged.read_bytes() != bytes(original_stat.st_size)


def test_short_concat_output_is_not_published_and_valid_parts_resume(tmp_path, monkeypatch):
    plan = make_plan(tmp_path)
    service = MovieRenderService(tmp_path / "renders")
    target = tmp_path / "movie.mp4"
    settings = RenderSettings(160, 90, 24)
    real_run = service._run

    def shorten_concat(command, token):
        real_run(command, token)
        if "concat" in command:
            # A valid MP4 with only the first event still decodes successfully.
            part = next((tmp_path / "renders").glob("*/part-000000.mp4"))
            Path(command[-1]).write_bytes(part.read_bytes())

    monkeypatch.setattr(service, "_run", shorten_concat)
    with pytest.raises(RenderValidationError, match="Videolänge"):
        service.render(plan, target, Event(), settings=settings)
    assert not target.exists()
    assert not list(tmp_path.glob(".memento-render-*"))
    manifest = next((tmp_path / "renders").glob("*/job.json"))
    assert len(json.loads(manifest.read_text())["parts"]) == 2
    assert json.loads(manifest.read_text())["status"] == "failed"
    progress = []
    MovieRenderService(tmp_path / "renders").render(plan, target, Event(), progress.append, settings)
    assert target.exists() and progress[-1].cached == 2


def test_cancel_during_output_validation_leaves_no_unvalidated_cached_part(tmp_path, monkeypatch):
    plan = make_plan(tmp_path)
    service = MovieRenderService(tmp_path / "renders")
    token = Event()
    validate = service._validate_video

    def cancel_validation(path, expected_frames, cancel_token, **kwargs):
        cancel_token.set()
        return validate(path, expected_frames, cancel_token, **kwargs)

    monkeypatch.setattr(service, "_validate_video", cancel_validation)
    target = tmp_path / "cancelled.mp4"
    with pytest.raises(RenderCancelled):
        service.render(plan, target, token, settings=RenderSettings(160, 90, 24))
    manifest = next((tmp_path / "renders").glob("*/job.json"))
    assert json.loads(manifest.read_text())["status"] == "cancelled"
    assert json.loads(manifest.read_text())["parts"] == {}
    assert not list(manifest.parent.glob("*.pending.mp4"))
    assert not target.exists()


@pytest.mark.parametrize("duration", [0.05, 1.234])
def test_fractional_segment_lengths_allow_only_frame_rounding(tmp_path, duration):
    plan = make_plan(tmp_path)
    for segment in plan.segments:
        segment.end_seconds = segment.start_seconds + duration
    target = tmp_path / "fractional.mp4"
    settings = RenderSettings(160, 90, 24)
    service = MovieRenderService(tmp_path / "renders")
    assert service.render(plan, target, Event(), settings=settings) == target
    capture = cv2.VideoCapture(str(target))
    try:
        actual_frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        assert actual_frames > 0
        # Inspect a normalized part: concat may retain small audio/container gaps.
        part = next((tmp_path / "renders").glob("*/part-000000.mp4"))
        part_capture = cv2.VideoCapture(str(part))
        try:
            assert part_capture.get(cv2.CAP_PROP_FPS) == pytest.approx(settings.fps)
        finally:
            part_capture.release()
        assert abs(actual_frames / settings.fps - plan.duration) <= len(plan.segments) / settings.fps
    finally:
        capture.release()


@pytest.mark.parametrize("target", [4, 4.4, 600])
def test_real_export_does_not_require_matching_target_duration(tmp_path, target):
    plan = make_plan(tmp_path)
    plan.target_seconds = target
    service = MovieRenderService(tmp_path / "renders")
    output = tmp_path / "guideline.mp4"
    service.render(plan, output, Event(), settings=RenderSettings(160, 90, 30))
    capture = cv2.VideoCapture(str(output))
    try:
        assert capture.get(cv2.CAP_PROP_FRAME_COUNT) / capture.get(cv2.CAP_PROP_FPS) == pytest.approx(4, abs=0.1)
    finally:
        capture.release()
