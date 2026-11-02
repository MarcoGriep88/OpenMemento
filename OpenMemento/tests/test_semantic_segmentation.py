from __future__ import annotations

import math
import random
from threading import Event

import pytest

from memento.ai.contracts import CHUNK_SECONDS, SemanticResult
from memento.ai.segmentation import MAX_CHUNK_SECONDS, split_analysis_range, uncovered_ranges
from memento.application.semantic_analysis import SemanticAnalysisService
from memento.domain.media import AnalysisStatus, Shot
from memento.media.local_features import LOCAL_ANALYSIS_VERSION
from test_semantic_analysis import FakeProvider, fake_proxy, setup_library


def save_cuts(library, asset, ends, version=LOCAL_ANALYSIS_VERSION):
    starts = [0, *ends[:-1]]
    library.save_shots(asset.asset_id, [Shot(f"shot-{index}", asset.asset_id, start, end)
                       for index, (start, end) in enumerate(zip(starts, ends))])
    library.set_asset_analysis_state(asset.asset_id, AnalysisStatus.COMPLETE, version)


def test_local_shot_boundary_preserves_action_context_without_extra_request(tmp_path):
    library, assets, repo = setup_library(tmp_path)
    save_cuts(library, assets[0], [50, 90])
    job = repo.create_job(assets, "gemini", "test-model")
    assert [(row["start_seconds"], row["end_seconds"]) for row in repo.items(job)] == [(0, 50), (50, 90)]
    calls = []
    def proxy(source, start, end, target, token):
        calls.append((start, end))
        return fake_proxy(source, start, end, target, token)
    provider = FakeProvider()
    assert SemanticAnalysisService(repo, provider, proxy).run(job, Event()) == "complete"
    assert calls == [(0, 50), (50, 90)]
    assert repo.estimate(job)["pending"] == 0


def test_partial_paid_coverage_survives_better_local_boundaries_and_restart(tmp_path):
    library, assets, repo = setup_library(tmp_path, duration=180)
    old = repo.create_job(assets, "gemini", "test-model")
    old_items = repo.items(old)
    # Empty answers are paid analysis too and must not be uploaded again.
    for item in (old_items[0], old_items[-1]):
        repo.save_result(repo.get_job(old), item, SemanticResult((), 100, 20))
    save_cuts(library, assets[0], [43, 88, 135, 180])
    new = repo.create_job(assets, "gemini", "test-model")
    assert [(row["start_seconds"], row["end_seconds"]) for row in repo.items(new)] == [
        (0, 45), (45, 88), (88, 135), (135, 180)]
    assert repo.estimate(new)["pending"] == 2
    assert repo.estimate(new)["seconds"] == 90
    provider = FakeProvider()
    assert SemanticAnalysisService(repo, provider, fake_proxy).run(new, Event()) == "complete"
    assert len(provider.calls) == 2
    save_cuts(library, assets[0], [41, 81, 130, 180])
    reopened = type(repo)(type(library)(library.path))
    repeat = reopened.create_job(assets, "gemini", "test-model")
    assert reopened.estimate(repeat)["pending"] == 0
    assert SemanticAnalysisService(reopened, provider, fake_proxy).run(repeat, Event()) == "complete"
    assert len(provider.calls) == 2
    assert [row["cache_key"] for row in reopened.results_for_asset(assets[0].asset_id, "gemini", "test-model")][:1] == [old_items[0]["cache_key"]]


def test_stale_local_analysis_is_not_used_to_choose_boundaries(tmp_path):
    library, assets, repo = setup_library(tmp_path)
    save_cuts(library, assets[0], [50, 90], version="older-local-analysis")
    job = repo.create_job(assets, "gemini", "test-model")
    assert [row["end_seconds"] for row in repo.items(job)] == [45, 90]


def test_legacy_overlap_is_cached_once_and_only_union_gap_is_sent(tmp_path):
    _, assets, repo = setup_library(tmp_path)
    job = repo.create_job(assets, "gemini", "test-model")
    first = dict(repo.items(job)[0])
    repo.save_result(repo.get_job(job), first, SemanticResult(()))
    overlap = dict(first, cache_key="historical-overlap", start_seconds=30, end_seconds=60)
    repo.save_result(repo.get_job(job), overlap, SemanticResult(()))
    new = repo.create_job(assets, "gemini", "test-model")
    assert [(row["start_seconds"], row["end_seconds"]) for row in repo.items(new)] == [(0, 45), (30, 60), (60, 90)]
    assert repo.estimate(new)["pending"] == 1
    assert repo.estimate(new)["seconds"] == 30
    provider = FakeProvider()
    assert SemanticAnalysisService(repo, provider, fake_proxy).run(new, Event()) == "complete"
    assert len(provider.calls) == 1


def test_ranges_cover_exactly_once_and_keep_nominal_request_count():
    rng = random.Random(42)
    for _ in range(200):
        start = rng.uniform(0, 100)
        end = start + rng.uniform(0.001, 5000)
        cuts = [rng.uniform(start, end) for _ in range(100)]
        ranges = split_analysis_range(start, end, cuts)
        assert len(ranges) == math.ceil((end - start) / CHUNK_SECONDS)
        assert ranges[0][0] == start and ranges[-1][1] == end
        assert all(0 < right - left <= MAX_CHUNK_SECONDS + 1e-6 for left, right in ranges)
        assert all(left[1] == right[0] for left, right in zip(ranges, ranges[1:]))
    assert split_analysis_range(0, 46) == [(0, 40), (40, 46)]
    assert split_analysis_range(0, 90, [5, 70]) == [(0, 45), (45, 90)]


def test_union_coverage_keeps_real_gaps_visible():
    assert uncovered_ranges(100, [(0, 45), (30, 60), (0, 45), (80, 100)]) == [(60, 80)]
    with pytest.raises(ValueError):
        uncovered_ranges(100, [(0, 110)])
