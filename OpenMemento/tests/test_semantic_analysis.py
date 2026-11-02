from __future__ import annotations

import io
import json
import sqlite3
import urllib.error
from dataclasses import replace
from datetime import datetime
from threading import Event

import cv2
import numpy as np
import pytest
import imageio_ffmpeg

from memento.ai.contracts import (
    AnalysisCancelled, Moment, ProviderError, SemanticResult, validate_moments,
)
from memento.ai.gemini import GeminiProvider, _NoRedirect
from memento.application.semantic_analysis import SemanticAnalysisService
from memento.domain.media import MediaAsset
from memento.library.database import MediaLibrary
from memento.library.semantic import SemanticRepository
from memento.media.analysis_proxy import create_analysis_proxy
from memento.media.metadata import _run_command


def moment(start=1.0, end=4.0):
    return Moment(start, end, "Gemeinsames Lachen", "Spielen im Garten", ("Spielen",), ("Kind mit rotem Hut",),
                  0.9, 0.8, 0.9, 0.7, 0.8, ("Lachen und Reaktion",))


def setup_library(tmp_path, count=1, duration=90):
    library = MediaLibrary(tmp_path / "library.sqlite3")
    assets = []
    for index in range(count):
        path = tmp_path / f"{index}.mp4"
        path.write_bytes(b"source-video")
        assets.append(library.save_asset(MediaAsset(str(index), path, path.stat().st_size,
            datetime.fromtimestamp(path.stat().st_mtime).astimezone(), duration_seconds=duration)))
    return library, assets, SemanticRepository(library)


class FakeProvider:
    name = "gemini"
    model = "test-model"

    def __init__(self):
        self.calls = []

    def analyze(self, video, duration, token):
        self.calls.append(video)
        return SemanticResult((moment(),), 120, 30)


def fake_proxy(source, start, end, target, token):
    target.write_bytes(b"small-mp4")
    return target


def test_cache_survives_restart_and_movie_settings_do_not_exist_in_analysis(tmp_path):
    library, assets, repo = setup_library(tmp_path)
    provider = FakeProvider()
    service = SemanticAnalysisService(repo, provider, fake_proxy)
    job = repo.create_job(assets, provider.name, provider.model)
    assert repo.estimate(job)["pending"] == 2
    assert service.run(job, Event()) == "complete"
    assert len(provider.calls) == 2
    assert all(not path.exists() for path in provider.calls)
    reopened = SemanticRepository(MediaLibrary(library.path))
    new_job = reopened.create_job(assets, provider.name, provider.model)
    assert reopened.estimate(new_job)["pending"] == 0
    assert reopened.estimate(new_job)["input_tokens"] == 240
    assert SemanticAnalysisService(reopened, provider, fake_proxy).run(new_job, Event()) == "complete"
    assert len(provider.calls) == 2
    assert [row["start_seconds"] for row in reopened.results_for_asset("0", provider.name, provider.model)] == [0, 45]
    other_model = reopened.create_job(assets, provider.name, "another-model")
    assert reopened.estimate(other_model)["pending"] == 2


def test_cancel_and_interrupted_work_resume_only_uncached_ranges(tmp_path):
    _, assets, repo = setup_library(tmp_path)
    provider = FakeProvider()
    service = SemanticAnalysisService(repo, provider, fake_proxy)
    job = repo.create_job(assets, provider.name, provider.model)
    token = Event()
    assert service.run(job, token, lambda progress: token.set()) == "cancelled"
    assert len(provider.calls) == 1
    token.clear()
    # Simulate a process dying after claiming the second range.
    item = repo.items(job)[1]
    repo.set_item_status(job, item["cache_key"], "processing")
    assert service.run(job, token) == "complete"
    assert len(provider.calls) == 2


def test_failures_isolated_and_untrusted_exception_not_persisted(tmp_path):
    _, assets, repo = setup_library(tmp_path, count=2, duration=10)
    provider = FakeProvider()
    original = provider.analyze

    def fail_once(video, duration, token):
        if not provider.calls:
            provider.calls.append(video)
            raise RuntimeError("SECRET media body")
        return original(video, duration, token)

    provider.analyze = fail_once
    service = SemanticAnalysisService(repo, provider, fake_proxy)
    job = repo.create_job(assets, provider.name, provider.model)
    assert service.run(job, Event()) == "complete_with_errors"
    assert "SECRET" not in str([dict(row) for row in repo.items(job)])
    provider.analyze = original
    assert service.run(job, Event()) == "complete"
    assert len(provider.calls) == 3


def test_changed_source_not_sent_and_reindex_invalidates_cache(tmp_path):
    library, assets, repo = setup_library(tmp_path, duration=10)
    provider = FakeProvider()
    service = SemanticAnalysisService(repo, provider, fake_proxy)
    job = repo.create_job(assets, provider.name, provider.model)
    assert service.run(job, Event()) == "complete"
    asset = assets[0]
    asset.path.write_bytes(b"changed-source-video")
    assert service.run(job, Event()) == "complete_with_errors"
    assert len(provider.calls) == 1
    assert "neu indexieren" in repo.items(job)[0]["error"]
    library.save_asset(replace(asset, size_bytes=asset.path.stat().st_size,
        modified_at=datetime.fromtimestamp(asset.path.stat().st_mtime).astimezone()))
    assert repo.results_for_asset(asset.asset_id, provider.name, provider.model) == []
    assert service.run(job, Event()) == "complete_with_errors"
    assert len(provider.calls) == 1


def test_analysis_profile_change_requires_new_job_and_hides_old_results(tmp_path, monkeypatch):
    import memento.library.semantic as storage
    import memento.application.semantic_analysis as application

    _, assets, repo = setup_library(tmp_path, duration=10)
    provider = FakeProvider()
    service = SemanticAnalysisService(repo, provider, fake_proxy)
    old_job = repo.create_job(assets, provider.name, provider.model)
    assert service.run(old_job, Event()) == "complete"
    monkeypatch.setattr(storage, "ANALYSIS_PROFILE", "new-prompt-and-proxy")
    monkeypatch.setattr(application, "ANALYSIS_PROFILE", "new-prompt-and-proxy")
    assert repo.results_for_asset("0", provider.name, provider.model) == []
    with pytest.raises(ValueError):
        service.run(old_job, Event())
    new_job = repo.create_job(assets, provider.name, provider.model)
    assert repo.estimate(new_job)["pending"] == 1
    assert service.run(new_job, Event()) == "complete"
    assert len(provider.calls) == 2


def test_empty_result_cached_and_not_retried(tmp_path):
    _, assets, repo = setup_library(tmp_path, duration=10)
    provider = FakeProvider()
    provider.analyze = lambda *args: SemanticResult(())
    service = SemanticAnalysisService(repo, provider, fake_proxy)
    job = repo.create_job(assets, provider.name, provider.model)
    assert service.run(job, Event()) == "complete"
    assert repo.estimate(job)["pending"] == 0


def test_global_provider_failure_stops_uploading_the_rest_of_library(tmp_path):
    _, assets, repo = setup_library(tmp_path, count=4)
    provider = FakeProvider()

    def denied(video, duration, token):
        provider.calls.append(video)
        raise ProviderError("Gemini-Anfrage fehlgeschlagen (HTTP 403).", abort_job=True)

    provider.analyze = denied
    job = repo.create_job(assets, provider.name, provider.model)
    assert SemanticAnalysisService(repo, provider, fake_proxy).run(job, Event()) == "complete_with_errors"
    assert len(provider.calls) == 1
    assert sum(item["status"] == "pending" for item in repo.items(job)) == 7


def test_retries_bounded_and_attempts_persisted(tmp_path):
    _, assets, repo = setup_library(tmp_path, duration=10)
    provider = FakeProvider()

    def overloaded(video, duration, token):
        provider.calls.append(video)
        raise ProviderError("Gemini-Anfrage fehlgeschlagen (HTTP 503).", retryable=True, abort_job=True)

    class FastToken:
        def __init__(self):
            self.delays = []

        def is_set(self):
            return False

        def wait(self, seconds):
            self.delays.append(seconds)
            return False

    provider.analyze = overloaded
    job = repo.create_job(assets, provider.name, provider.model)
    token = FastToken()
    assert SemanticAnalysisService(repo, provider, fake_proxy).run(job, token) == "complete_with_errors"
    assert len(provider.calls) == 3
    assert token.delays == [1, 2]
    assert repo.items(job)[0]["attempts"] == 3


def test_cancel_during_successful_request_preserves_paid_response(tmp_path):
    _, assets, repo = setup_library(tmp_path)
    provider = FakeProvider()
    original = provider.analyze
    token = Event()

    def cancel_in_flight(video, duration, cancel_token):
        result = original(video, duration, cancel_token)
        token.set()
        return result

    provider.analyze = cancel_in_flight
    job = repo.create_job(assets, provider.name, provider.model)
    assert SemanticAnalysisService(repo, provider, fake_proxy).run(job, token) == "cancelled"
    assert repo.estimate(job)["pending"] == 1
    assert len(provider.calls) == 1


def test_request_limit_resumes_across_restarts_without_charging_cache_hits(tmp_path):
    library, assets, repo = setup_library(tmp_path, duration=135)
    provider = FakeProvider()
    job = repo.create_job(assets, provider.name, provider.model)
    progress, proxies = [], []

    def proxy(*args):
        proxies.append(args[1:3])
        return fake_proxy(*args)

    assert SemanticAnalysisService(repo, provider, proxy).run(job, Event(), progress.append, max_requests=1) == "request_limit"
    assert len(provider.calls) == len(proxies) == 1
    assert progress[-1].requests == progress[-1].request_limit == 1
    assert repo.get_job(job)["status"] == "request_limit"
    assert [item["attempts"] for item in repo.items(job)] == [1, 0, 0]
    assert job in {item["job_id"] for item in repo.resumable_jobs()}
    reopened = SemanticRepository(MediaLibrary(library.path))
    service = SemanticAnalysisService(reopened, provider, proxy)
    assert service.run(job, Event(), progress.append, max_requests=1) == "request_limit"
    assert progress[-1].cached == 1 and progress[-1].requests == 1
    assert service.run(job, Event(), progress.append, max_requests=1) == "complete"
    assert progress[-1].cached == 2 and progress[-1].requests == 1
    assert len(provider.calls) == len(proxies) == 3
    assert reopened.estimate(job)["attempts"] == 3
    assert service.run(job, Event(), progress.append, max_requests=0) == "complete"
    assert progress[-1].cached == 3 and progress[-1].requests == 0
    assert len(provider.calls) == 3


def test_request_limit_includes_retries_and_stops_before_backoff_or_another_call(tmp_path):
    _, assets, repo = setup_library(tmp_path, duration=10)
    provider = FakeProvider()

    def overloaded(video, duration, token):
        provider.calls.append(video)
        raise ProviderError("HTTP 503", retryable=True, abort_job=True)

    class FastToken:
        delays = []

        def is_set(self):
            return False

        def wait(self, seconds):
            self.delays.append(seconds)
            return False

    provider.analyze = overloaded
    token = FastToken()
    job = repo.create_job(assets, provider.name, provider.model)
    service = SemanticAnalysisService(repo, provider, fake_proxy)
    assert service.run(job, token, max_requests=2) == "request_limit"
    assert len(provider.calls) == 2 and token.delays == [1]
    assert repo.items(job)[0]["status"] == "pending"
    assert repo.items(job)[0]["attempts"] == 2
    provider.analyze = lambda *args: FakeProvider.analyze(provider, *args)
    assert service.run(job, Event(), max_requests=1) == "complete"
    assert repo.estimate(job)["attempts"] == 3


@pytest.mark.parametrize("limit", [-1, 1.5, True, "1"])
def test_invalid_request_limit_does_not_start_job(tmp_path, limit):
    _, assets, repo = setup_library(tmp_path, duration=10)
    provider = FakeProvider()
    job = repo.create_job(assets, provider.name, provider.model)
    with pytest.raises(ValueError, match="Anfragelimit"):
        SemanticAnalysisService(repo, provider, fake_proxy).run(job, Event(), max_requests=limit)
    assert repo.get_job(job)["status"] == "pending" and not provider.calls


def test_zero_request_limit_stops_before_proxy_creation(tmp_path):
    _, assets, repo = setup_library(tmp_path, duration=10)
    provider = FakeProvider()
    job = repo.create_job(assets, provider.name, provider.model)
    service = SemanticAnalysisService(repo, provider, lambda *args: pytest.fail("No proxy should be needed"))
    assert service.run(job, Event(), max_requests=0) == "request_limit"
    assert not provider.calls
    assert repo.estimate(job)["attempts"] == 0


def test_inspection_pages_resolve_direct_and_equivalent_cache_without_per_item_reads(tmp_path, monkeypatch):
    library, assets, repo = setup_library(tmp_path, duration=135)
    job = repo.create_job(assets, "gemini", "test-model")
    item = repo.items(job)[0]
    repo.save_result(repo.get_job(job), item, SemanticResult((moment(),)))
    legacy = dict(item, cache_key="equivalent-legacy-key")
    repo.save_result(repo.get_job(job), legacy, SemanticResult((replace(moment(), description="Legacy"),)))
    reads = []
    original = library._connect

    def connect():
        reads.append(True)
        return original()

    monkeypatch.setattr(library, "_connect", connect)
    rows, total, offset = repo.inspection_page(job, limit=2)
    assert len(reads) == 1 and total == 3 and offset == 0
    assert len(rows) == 2
    assert rows[0]["source_path"] == str(assets[0].path)
    assert rows[0]["cached_key"] == item["cache_key"]
    assert rows[1]["cached_key"] is None
    with library._connection() as db:
        db.execute("DELETE FROM semantic_cache WHERE cache_key=?", (item["cache_key"],))
    assert repo.inspection_page(job, limit=2)[0][0]["cached_key"] == "equivalent-legacy-key"
    last, total, offset = repo.inspection_page(job, limit=2, offset=999)
    assert len(last) == 1 and offset == 2
    assert last[0]["start_seconds"] == 90
    empty, total, offset = repo.inspection_page("missing")
    assert not empty and total == offset == 0


@pytest.mark.parametrize("arguments", [{"offset": -1}, {"offset": True}, {"limit": 0}, {"limit": 501}])
def test_inspection_pages_reject_unbounded_or_invalid_requests(tmp_path, arguments):
    _, assets, repo = setup_library(tmp_path, duration=10)
    job = repo.create_job(assets, "gemini", "test-model")
    with pytest.raises(ValueError, match="Seitenauswahl"):
        repo.inspection_page(job, **arguments)


def test_cancellation_takes_precedence_when_retry_and_request_limit_coincide(tmp_path):
    _, assets, repo = setup_library(tmp_path, duration=10)
    provider = FakeProvider()
    token = Event()

    def cancel_and_fail(video, duration, cancel_token):
        cancel_token.set()
        raise ProviderError("HTTP 503", retryable=True)

    provider.analyze = cancel_and_fail
    job = repo.create_job(assets, provider.name, provider.model)
    assert SemanticAnalysisService(repo, provider, fake_proxy).run(job, token, max_requests=1) == "cancelled"
    assert repo.items(job)[0]["attempts"] == 1


@pytest.mark.parametrize("field,value", [
    ("start_seconds", -1), ("end_seconds", 46), ("importance", 1.1),
    ("emotion", float("nan")), ("audio", True), ("confidence", "0.8"),
    ("people", "a person"), ("event", ""), ("description", None),
])
def test_invalid_model_answers_rejected(field, value):
    entry = moment().to_dict()
    entry[field] = value
    with pytest.raises(ValueError):
        validate_moments({"moments": [entry]}, 45)


def test_overlapping_and_unknown_fields_rejected():
    with pytest.raises(ValueError):
        validate_moments({"moments": [moment().to_dict(), moment(3, 6).to_dict()]}, 45)
    with pytest.raises(ValueError):
        validate_moments({"moments": [dict(moment().to_dict(), invented=True)]}, 45)


class Opener:
    def __init__(self, data=None, error=None):
        self.data, self.error, self.requests = data, error, []

    def open(self, request, timeout):
        self.requests.append(request)
        if self.error:
            raise self.error
        return io.BytesIO(json.dumps(self.data).encode())


def test_gemini_wire_format_is_video_audio_no_path_and_secret_only_in_header(tmp_path):
    video = tmp_path / "sensitive-name.mp4"
    video.write_bytes(b"mp4")
    answer = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps({"moments": [moment().to_dict()]})}]}}],
              "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 8}}
    opener = Opener(answer)
    result = GeminiProvider("private-key", "test-model", opener).analyze(video, 45, Event())
    assert result.input_tokens == 5 and result.output_tokens == 8
    req = opener.requests[0]
    assert req.get_header("X-goog-api-key") == "private-key"
    assert "private-key" not in req.full_url
    assert b"sensitive-name" not in req.data and b"private-key" not in req.data
    payload = json.loads(req.data)
    assert payload["contents"][0]["parts"][0]["inlineData"]["mimeType"] == "video/mp4"
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    assert _NoRedirect().redirect_request(req, None, 302, "", {}, "https://example.org") is None


def test_http_errors_sanitized_and_cancel_before_network(tmp_path):
    video = tmp_path / "proxy.mp4"
    video.write_bytes(b"mp4")
    opener = Opener(error=urllib.error.HTTPError("https://secret", 429, "API-KEY", {}, io.BytesIO(b"SECRET")))
    provider = GeminiProvider("private-key", "test-model", opener)
    with pytest.raises(ProviderError) as info:
        provider.analyze(video, 45, Event())
    assert info.value.retryable
    assert str(info.value) == "Gemini-Anfrage fehlgeschlagen (HTTP 429)."
    token = Event()
    token.set()
    with pytest.raises(AnalysisCancelled):
        provider.analyze(video, 45, token)
    assert len(opener.requests) == 1


def test_proxy_generated_locally_and_original_unchanged(tmp_path):
    source = tmp_path / "source.avi"
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"MJPG"), 12, (96, 64))
    assert writer.isOpened()
    for index in range(24):
        writer.write(np.full((64, 96, 3), (index * 10, 30, 100), dtype=np.uint8))
    writer.release()
    before = source.read_bytes()
    target = tmp_path / "analysis.mp4"
    create_analysis_proxy(source, 0.25, 1.25, target, Event())
    capture = cv2.VideoCapture(str(target))
    try:
        assert capture.isOpened()
        assert capture.get(cv2.CAP_PROP_FRAME_COUNT) / capture.get(cv2.CAP_PROP_FPS) == pytest.approx(1, abs=0.15)
        assert max(capture.get(cv2.CAP_PROP_FRAME_WIDTH), capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) <= 640
    finally:
        capture.release()
    assert source.read_bytes() == before


def test_schema_three_migrates_with_assets_preserved(tmp_path):
    library, assets, _ = setup_library(tmp_path)
    with sqlite3.connect(library.path) as db:
        db.execute("ALTER TABLE assets DROP COLUMN metadata_version")
        db.execute("DELETE FROM schema_migrations WHERE version=7")
        db.execute("DROP TABLE asset_aliases")
        db.execute("DROP INDEX idx_assets_content")
        db.execute("ALTER TABLE assets DROP COLUMN content_sha256")
        db.execute("DROP INDEX idx_locations_preferred")
        db.execute("ALTER TABLE locations DROP COLUMN available")
        db.execute("ALTER TABLE index_jobs DROP COLUMN verify_contents")
        db.execute("DELETE FROM schema_migrations WHERE version=6")
        db.execute("DROP TABLE local_feature_windows")
        db.execute("DELETE FROM schema_migrations WHERE version=5")
        db.execute("DROP TABLE semantic_cache")
        db.execute("DROP TABLE semantic_items")
        db.execute("DROP TABLE semantic_jobs")
        db.execute("DELETE FROM schema_migrations WHERE version=4")
        db.execute("PRAGMA user_version=3")
    migrated = MediaLibrary(library.path)
    assert migrated.get_asset(assets[0].asset_id)
    with sqlite3.connect(library.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 7


@pytest.mark.parametrize("duration", [1, 60])
def test_proxy_retains_audio_and_removes_container_metadata(tmp_path, duration):
    source, target = tmp_path / "recording.mp4", tmp_path / "proxy.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    result = _run_command([
        ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i", f"color=c=red:s=96x64:r=12:d={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}", "-c:v", "libx264", "-c:a", "aac",
        "-metadata", "comment=private-device-name", "-metadata", "creation_time=2025-01-02T03:04:05Z", str(source),
    ], timeout=15, cancel_token=None)
    assert result.returncode == 0
    create_analysis_proxy(source, 0, duration, target, Event())
    probe = _run_command([ffmpeg, "-hide_banner", "-i", str(target)], timeout=15, cancel_token=None)
    assert "Audio: aac" in probe.stderr
    assert "private-device-name" not in probe.stderr
    assert "creation_time" not in probe.stderr
    capture = cv2.VideoCapture(str(target))
    try:
        assert capture.get(cv2.CAP_PROP_FRAME_COUNT) / capture.get(cv2.CAP_PROP_FPS) == pytest.approx(duration, abs=0.15)
    finally:
        capture.release()
    assert target.stat().st_size <= 8 * 1024 * 1024
