from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from memento.application.evaluation import evaluate_movie
from memento.domain.movie import MovieEvent, MoviePlan, MovieSegment, MovieSource
from memento.evaluate import main
from memento.library.movies import save_movie


@pytest.fixture
def sample(tmp_path):
    first = MovieSource("a", str((tmp_path / "a.mp4").resolve()), 100, "2026-07-12T10:00:00+00:00", 20, True, 96, 64, "a" * 64)
    second = replace(first, asset_id="b", path=str((tmp_path / "b.mp4").resolve()), content_sha256="b" * 64)
    plan = MoviePlan("plan", "Familienfilm", 20, "2026-07-12", "2026-07-12", "gemini", "test-model", "test",
        [MovieEvent("event", "Familie", ("a1", "a2", "b1"))],
        [MovieSegment("a1", "event", first, 0, 5, "Spielen", ()),
         MovieSegment("a2", "event", first, 5, 8, "Lachen", ()),
         MovieSegment("b1", "event", second, 0, 5, "Boot", (), enabled=False)])

    def source(value):
        return {"source_id": value.asset_id, "asset_id": value.asset_id, "content_sha256": value.content_sha256,
                "size_bytes": value.size_bytes, "modified_at": value.modified_at, "duration_seconds": value.duration_seconds}

    reference = {"format_version": 1, "reference_id": "independent-family-reference",
        "request": {"date_from": plan.date_from, "date_to": plan.date_to, "target_seconds": 20},
        "sources": [source(first), source(second)],
        "moments": [
            {"moment_id": "laugh", "description": "Schlüsselmoment im Garten", "event": "Garten", "weight": 2,
             "alternatives": [{"source_id": "a", "start_seconds": 0, "end_seconds": 10}]},
            {"moment_id": "boat", "description": "Erste Bootsfahrt", "event": "Boot", "weight": 1,
             "alternatives": [{"source_id": "b", "start_seconds": 0, "end_seconds": 5}]},
        ]}
    return plan, reference


def test_union_coverage_weighted_recall_and_disabled_ranges(sample):
    plan, reference = sample
    before = deepcopy((plan, reference))
    report = evaluate_movie(plan, reference)
    assert report["moments"][0]["coverage"] == 0.8
    assert report["moments"][0]["retained"]
    assert report["moments"][1]["coverage"] == 0
    assert report["weighted_moment_coverage"] == pytest.approx(1.6 / 3)
    assert report["weighted_moment_recall"] == pytest.approx(2 / 3)
    assert report["event_coverage"] == 0.5 and report["missing_events"] == ["Boot"]
    assert report["annotated_unique_seconds"] == 8
    assert report["annotated_unique_fraction_of_output"] == 1
    assert report["duration_seconds"] == 8 and report["target_difference_seconds"] == -12
    assert (plan, reference) == before
    assert evaluate_movie(plan, reference) == report
    assert not evaluate_movie(plan, reference, retained_fraction=0.9)["moments"][0]["retained"]


def test_alternative_cameras_earn_at_most_one_moment_credit(sample):
    plan, reference = sample
    reference["moments"] = reference["moments"][:1]
    reference["moments"][0]["alternatives"].append({"source_id": "b", "start_seconds": 0, "end_seconds": 5})
    plan.segments[2].enabled = True
    report = evaluate_movie(plan, reference)
    assert report["weighted_moment_coverage"] == report["weighted_moment_recall"] == 1
    assert report["moments"][0]["best_alternative"] == 1


def test_hash_aliases_and_overlapping_annotations_do_not_double_count_source_time(sample):
    plan, reference = sample
    alias = replace(plan.segments[0].source, asset_id="alias", path=str(plan.segments[2].source.path))
    plan.segments[1].source = alias
    plan.segments[1].start_seconds, plan.segments[1].end_seconds = 2, 6
    reference["moments"].append({"moment_id": "reaction", "description": "Reaktion", "event": "Garten", "weight": 1,
        "alternatives": [{"source_id": "a", "start_seconds": 3, "end_seconds": 5}]})
    report = evaluate_movie(plan, reference)
    assert report["annotated_unique_seconds"] == 6
    assert report["exact_repeated_source_seconds"] == 3
    assert report["moments"][0]["coverage"] == 0.6


def test_reference_hash_does_not_match_replaced_contents_even_with_same_attributes(sample):
    plan, reference = sample
    for segment in plan.segments[:2]:
        segment.source = replace(segment.source, content_sha256="c" * 64)
    report = evaluate_movie(plan, reference)
    assert report["weighted_moment_coverage"] == 0
    assert len(report["notes"]) == 2


def test_unverified_reference_uses_exact_snapshot_and_reports_weaker_identity(sample):
    plan, reference = sample
    reference["sources"][0]["content_sha256"] = None
    report = evaluate_movie(plan, reference)
    assert report["moments"][0]["coverage"] == 0.8
    assert any("nur Dateistand" in text for text in report["notes"])
    reference["sources"][0]["modified_at"] = "2026-07-13T10:00:00+00:00"
    assert evaluate_movie(plan, reference)["moments"][0]["coverage"] == 0


def test_empty_output_reports_missing_events_without_nan(sample):
    plan, reference = sample
    plan.segments.clear()
    report = evaluate_movie(plan, reference)
    assert report["weighted_moment_coverage"] == report["event_coverage"] == 0
    assert report["annotated_unique_fraction_of_output"] is None
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("path,value", [
    (("format_version",), True), (("moments",), []), (("moments", 0, "weight"), True),
    (("moments", 0, "weight"), float("nan")), (("moments", 0, "alternatives"), []),
    (("moments", 0, "alternatives", 0, "end_seconds"), 21),
    (("moments", 0, "alternatives", 0, "source_id"), "missing"),
    (("sources", 0, "content_sha256"), "invalid"), (("request", "target_seconds"), 40),
])
def test_invalid_or_incomparable_reference_rejected(sample, path, value):
    plan, reference = sample
    parent = reference
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    with pytest.raises(ValueError):
        evaluate_movie(plan, reference)


@pytest.mark.parametrize("change", ["duplicate_source", "duplicate_moment", "unknown_field"])
def test_reference_identifiers_and_fields_are_unambiguous(sample, change):
    plan, reference = sample
    if change == "duplicate_source":
        reference["sources"].append(deepcopy(reference["sources"][0]))
    elif change == "duplicate_moment":
        reference["moments"].append(deepcopy(reference["moments"][0]))
    else:
        reference["moments"][0]["invented_score"] = 1
    with pytest.raises(ValueError):
        evaluate_movie(plan, reference)


def test_cli_writes_reproducible_report_without_overwriting_inputs(sample, tmp_path, capsys):
    plan, reference = sample
    project, annotations, output = (tmp_path / name for name in ("film.memento.json", "reference.json", "report.json"))
    save_movie(project, plan)
    annotations.write_text(json.dumps(reference), encoding="utf-8")
    before = {path: path.read_bytes() for path in (project, annotations)}
    assert main([str(project), str(annotations), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report == evaluate_movie(plan, reference)
    assert "path" not in json.dumps(report)
    for path in (project, annotations, output):
        content = path.read_bytes()
        with pytest.raises(SystemExit) as error:
            main([str(project), str(annotations), "--output", str(path)])
        assert error.value.code == 2 and path.read_bytes() == content
    assert {path: path.read_bytes() for path in before} == before
    annotations.write_text('{"format_version":1,"format_version":1}', encoding="utf-8")
    with pytest.raises(SystemExit):
        main([str(project), str(annotations)])
    assert "Doppelte JSON-Felder" in capsys.readouterr().err
