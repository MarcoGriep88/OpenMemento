"""Offline comparison of a movie plan with independently annotated memories."""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json

from memento.domain.movie import MoviePlan, finite_number


EVALUATION_VERSION = "reference-coverage-v1"


def _fields(value, required):
    if not isinstance(value, dict) or set(value) != set(required.split()):
        raise ValueError("Ungültige Felder in der Referenzdatei.")


def _label(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError("Ungültige Referenzkennung oder Beschreibung.")


def _union(ranges):
    result = []
    for start, end in sorted(ranges):
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def _length(ranges):
    return sum(end - start for start, end in _union(ranges))


def _overlap(left, right):
    first, second = _union(left), _union(right)
    i = j = 0
    total = 0.0
    while i < len(first) and j < len(second):
        total += max(0.0, min(first[i][1], second[j][1]) - max(first[i][0], second[j][0]))
        if first[i][1] <= second[j][1]:
            i += 1
        else:
            j += 1
    return total


def validate_reference(payload):
    """Strict, versioned human annotation schema; no automatic golden labels."""
    _fields(payload, "format_version reference_id request sources moments")
    if type(payload["format_version"]) is not int or payload["format_version"] != 1:
        raise ValueError("Nicht unterstützte Referenzversion.")
    _label(payload["reference_id"])
    request = payload["request"]
    _fields(request, "date_from date_to target_seconds")
    if date.fromisoformat(request["date_from"]) > date.fromisoformat(request["date_to"]):
        raise ValueError("Ungültiger Referenzzeitraum.")
    if not finite_number(request["target_seconds"], 2):
        raise ValueError("Ungültige Referenzzielzeit.")
    if not isinstance(payload["sources"], list) or not isinstance(payload["moments"], list) or not payload["moments"]:
        raise ValueError("Eine Referenz benötigt Quellen und mindestens einen menschlich markierten Moment.")
    sources = {}
    for source in payload["sources"]:
        _fields(source, "source_id asset_id content_sha256 size_bytes modified_at duration_seconds")
        _label(source["source_id"])
        _label(source["asset_id"])
        if source["source_id"] in sources:
            raise ValueError("Doppelte Referenzquelle.")
        if type(source["size_bytes"]) is not int or source["size_bytes"] < 0 or not finite_number(source["duration_seconds"], 0.001):
            raise ValueError("Ungültiger Referenzquellstand.")
        datetime.fromisoformat(source["modified_at"])
        digest = source["content_sha256"]
        if digest is not None and (not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest)):
            raise ValueError("Ungültige Referenzinhaltsidentität.")
        sources[source["source_id"]] = source
    keys = set()
    for moment in payload["moments"]:
        _fields(moment, "moment_id description event weight alternatives")
        for field in ("moment_id", "description", "event"):
            _label(moment[field])
        if moment["moment_id"] in keys:
            raise ValueError("Doppelter Referenzmoment.")
        keys.add(moment["moment_id"])
        if not finite_number(moment["weight"], 0.001) or moment["weight"] > 1000:
            raise ValueError("Ungültiges Referenzgewicht.")
        if not isinstance(moment["alternatives"], list) or not moment["alternatives"]:
            raise ValueError("Ein Referenzmoment benötigt mindestens einen Quellbereich.")
        for alternative in moment["alternatives"]:
            _fields(alternative, "source_id start_seconds end_seconds")
            _label(alternative["source_id"])
            source = sources.get(alternative["source_id"])
            if source is None or not all(finite_number(alternative[key]) for key in ("start_seconds", "end_seconds")):
                raise ValueError("Ungültiger Referenzbereich.")
            if not alternative["start_seconds"] < alternative["end_seconds"] <= source["duration_seconds"]:
                raise ValueError("Referenzbereich liegt außerhalb der Quelle.")
    return sources


def evaluate_movie(plan: MoviePlan, reference: dict, *, retained_fraction=0.8):
    """Compute source-time coverage; do not infer emotional or narrative quality.

    Each annotated moment receives its best alternative's fraction, so two cameras
    never earn double credit. Shares of output within annotations are descriptive:
    unannotated footage may still be valuable. Matching uses stored identities,
    never opens media, and never claims to verify current file contents.
    """
    plan.validate()
    if not finite_number(plan.duration):
        raise ValueError("Ungültige gesamte Filmdauer.")
    sources = validate_reference(reference)
    if not finite_number(retained_fraction, 0.001) or retained_fraction > 1:
        raise ValueError("Ungültige Mindestabdeckung.")
    request = reference["request"]
    if (plan.date_from, plan.date_to) != (request["date_from"], request["date_to"]) or abs(plan.target_seconds - request["target_seconds"]) > 1e-6:
        raise ValueError("Referenz und Filmplan benötigen denselben Zeitraum und dieselbe Zielzeit.")
    enabled = [item for item in plan.segments if item.enabled]

    def identity(source):
        return ("sha256", source.content_sha256) if source.content_sha256 else (
            "snapshot", source.asset_id, source.size_bytes, datetime.fromisoformat(source.modified_at))

    delivered = {}
    for segment in enabled:
        delivered.setdefault(identity(segment.source), []).append((segment.start_seconds, segment.end_seconds))
    matched, notes = {}, []
    for key, source in sources.items():
        digest = source["content_sha256"]
        ident = ("sha256", digest) if digest else (
            "snapshot", source["asset_id"], source["size_bytes"], datetime.fromisoformat(source["modified_at"]))
        # A plan may have gained a verified hash since an older annotation. An
        # unverified reference still matches only its exact recorded snapshot.
        matching = {identity(item.source) for item in enabled if identity(item.source) == ident or (
            digest is None and item.source.asset_id == source["asset_id"]
            and item.source.size_bytes == source["size_bytes"]
            and datetime.fromisoformat(item.source.modified_at) == datetime.fromisoformat(source["modified_at"]))}
        matched[key] = matching
        if not digest:
            notes.append(f"Quelle {key}: nur Dateistand statt verifizierter Inhaltsidentität als Referenz.")
        if not matching:
            notes.append(f"Quelle {key}: kein passender aktiver Quellstand im Filmplan; ausgelassen oder anderer Inhalt/Dateistand.")
    rows, annotated = [], {}
    for moment in reference["moments"]:
        fractions = []
        for alternative in moment["alternatives"]:
            bounds = (alternative["start_seconds"], alternative["end_seconds"])
            identities = matched[alternative["source_id"]]
            ranges = [span for ident in identities for span in delivered[ident]]
            seconds = _overlap([bounds], ranges)
            fractions.append(min(1.0, seconds / (bounds[1] - bounds[0])))
            for ident in identities:
                annotated.setdefault(ident, []).append(bounds)
        coverage = max(fractions)
        rows.append({"moment_id": moment["moment_id"], "description": moment["description"], "event": moment["event"],
                     "weight": moment["weight"], "coverage": coverage, "retained": coverage + 1e-9 >= retained_fraction,
                     "best_alternative": fractions.index(coverage) if coverage > 0 else None})
    weight = sum(row["weight"] for row in rows)
    events = sorted({row["event"] for row in rows})
    covered_events = sorted({row["event"] for row in rows if row["retained"]})
    annotated_seconds = sum(_overlap(delivered[ident], bounds) for ident, bounds in annotated.items())
    return {
        "evaluation_version": EVALUATION_VERSION, "reference_id": reference["reference_id"], "plan_id": plan.plan_id,
        "reference_sha256": hashlib.sha256(json.dumps(reference, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest(),
        "timeline_sha256": hashlib.sha256(json.dumps([
            [item.source.asset_id, item.source.content_sha256, item.source.size_bytes, item.source.modified_at,
             item.start_seconds, item.end_seconds] for item in enabled], ensure_ascii=False).encode()).hexdigest(),
        "planner_version": plan.planner_version, "provider": plan.provider, "model": plan.model,
        "analysis_profile": plan.analysis_profile, "local_analysis_version": plan.local_analysis_version,
        "request": dict(request), "retained_fraction": retained_fraction,
        "duration_seconds": plan.duration, "target_difference_seconds": plan.duration - plan.target_seconds,
        "weighted_moment_coverage": sum(row["weight"] * row["coverage"] for row in rows) / weight,
        "weighted_moment_recall": sum(row["weight"] for row in rows if row["retained"]) / weight,
        "event_coverage": len(covered_events) / len(events), "covered_events": covered_events,
        "missing_events": sorted(set(events) - set(covered_events)),
        "annotated_unique_seconds": annotated_seconds,
        "annotated_unique_fraction_of_output": annotated_seconds / plan.duration if plan.duration else None,
        "exact_repeated_source_seconds": max(0.0, plan.duration - sum(_length(spans) for spans in delivered.values())),
        "moments": rows, "notes": notes,
    }
