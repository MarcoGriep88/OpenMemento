"""Cached media intelligence -> event-balanced, chronological first cut."""
from __future__ import annotations

import hashlib
import json
import re
from bisect import bisect_right
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
from threading import Event
from uuid import uuid4

from memento.ai.contracts import ANALYSIS_PROFILE, validate_moments
from memento.ai.segmentation import uncovered_ranges
from memento.domain.movie import (
    CandidateSegment, MovieEvent, MoviePlan, MoviePreferences, MovieSegment, MovieSource, finite_number,
)
from memento.library.semantic import SemanticRepository
from memento.media.local_features import LOCAL_ANALYSIS_VERSION, LocalFeatureIndex, visual_similarity


MIN_SEGMENT_SECONDS = 2.0
PLANNER_VERSION = "event-balanced-local-v10"
MAX_BOUNDARY_BORROW_SECONDS = 2.0
MAX_EVENT_BORROW_FRACTION = 0.25
MAX_MOVIE_BORROW_FRACTION = 0.15
_STOP_WORDS = frozenset("der die das ein eine einer einem einen und mit im in am an auf von zu bei ist sind wird es sich den des".split())


class PlanningCancelled(RuntimeError):
    pass


def _check_cancel(token):
    if token is not None and token.is_set():
        raise PlanningCancelled("Filmplanung abgebrochen; ein vorhandener Filmplan bleibt gespeichert.")


def _tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"\w+", text.casefold()) if len(word) > 2 and word not in _STOP_WORDS}


def _similarity(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left and right else 0.0


def _features(candidate):
    return _tokens(" ".join((candidate.event_label, candidate.description, *candidate.activities)))


def _value(candidate):
    # Technical imperfection may not erase an emotionally important moment.
    quality = candidate.technical_quality if candidate.technical_quality is not None else 0.5
    return (0.34 * candidate.importance + 0.28 * candidate.emotion + 0.17 * candidate.audio
            + 0.13 * candidate.uniqueness + 0.08 * quality) * (0.8 + 0.2 * candidate.confidence)


def _confirmed_event_change(left, right, features):
    """Require two independent, confident recordings on each side of a change.

    Labels/activities are evidence about events; people and moment descriptions
    are deliberately omitted (the same family can appear throughout a trip).
    This is a conservative lexical signal, not a semantic identity classifier.
    """
    if len(left) != 2 or len(right) != 2:
        return False
    context = (*left, *right)
    if len({item.source.asset_id for item in context}) != 4:
        return False
    if any(item.confidence < 0.65 or len(features[item.candidate_id]) < 2 for item in context):
        return False
    # Confirmation must be local. Tomorrow's similar activity cannot corroborate
    # a boundary today, nor can footage following a long recording break.
    for pair in (left, right):
        if (pair[0].event_chronology[0].date() != pair[1].event_chronology[0].date()
                or (pair[1].event_chronology[0] - pair[0].event_end_time).total_seconds() > 600):
            return False
        if _similarity(*(features[item.candidate_id] for item in pair)) < 0.5:
            return False
    return all(_similarity(features[a.candidate_id], features[b.candidate_id]) < 0.1
               for a in left for b in right)


def cluster_events(candidates: list[CandidateSegment]) -> list[MovieEvent]:
    """Infer contiguous events from recorded time and free-form semantic labels."""
    groups: list[list[CandidateSegment]] = []
    covered_end = None
    ordered = sorted(candidates, key=lambda value: value.event_chronology)
    features = {item.candidate_id: _tokens(" ".join((item.event_label, *item.activities))) for item in ordered}
    for index, candidate in enumerate(ordered):
        previous = groups[-1][-1] if groups else None
        split = previous is None
        if previous is not None:
            current_time = candidate.event_chronology[0]
            previous_time = previous.event_chronology[0]
            # Measure actual uncovered time, not spacing of segment starts.
            # An overlapping short camera angle must not erase longer coverage.
            gap = max(0.0, (current_time - covered_end).total_seconds())
            semantics = _similarity(_tokens(candidate.event_label), _tokens(previous.event_label))
            split = (current_time.date() != previous_time.date()
                     or gap > 90 * 60 or (gap > 10 * 60 and semantics < 0.15))
            if not split and gap >= 30:
                split = _confirmed_event_change(groups[-1][-2:], ordered[index:index + 2], features)
        if split:
            groups.append([])
            covered_end = candidate.event_end_time
        else:
            covered_end = max(covered_end, candidate.event_end_time)
        groups[-1].append(candidate)
    events = []
    for group in groups:
        representative = max(group, key=_value)
        identity = f"event:{group[0].candidate_id}"
        events.append(MovieEvent(hashlib.sha256(identity.encode()).hexdigest()[:24],
                                 representative.event_label, tuple(item.candidate_id for item in group)))
    return events


def _usable_duration(candidates):
    """Maximum duration of compatible whole ranges, grouped by source identity."""
    sources = {}
    for candidate in candidates:
        sources.setdefault(candidate.source.asset_id, []).append(candidate)
    total = 0.0
    for ranges in sources.values():
        ranges.sort(key=lambda candidate: candidate.end_seconds)
        ends = [candidate.end_seconds for candidate in ranges]
        best = [0.0]
        for index, candidate in enumerate(ranges):
            compatible = bisect_right(ends, candidate.start_seconds + 1e-6, hi=index)
            best.append(max(best[-1], best[compatible] + candidate.duration))
        total += best[-1]
    return total


def _event_value(candidates):
    """A strong memory must not be diluted by ordinary footage of its event.

    Use the most valuable eligible moment's multidimensional assessment. More
    recordings alone neither increase nor decrease this event importance; usable
    duration and user weights remain separate inputs to the budget allocator.
    """
    return max((_value(candidate) for candidate in candidates), default=0.0)


def allocate_event_budgets(events, candidates, target, preferences):
    """Capped weighted water filling: recording count alone never earns more time."""
    capacities, weights = {}, {}
    for event in events:
        pool = [candidates[key] for key in event.candidate_ids if key in candidates and key not in preferences.excluded
                and (key not in preferences.trims or candidates[key].duration <= target + 1e-6 or key in preferences.forced)]
        if not pool:
            continue
        capacities[event.event_id] = _usable_duration(pool)
        weights[event.event_id] = max(0.1, _event_value(pool)) * preferences.event_weights.get(event.event_id, 1.0)
    # A short movie cannot cover hundreds of events with watchable shot lengths.
    # Choose meaningful representatives from chronological bins rather than
    # allocating sub-second budgets (which would produce an empty first cut).
    max_events = max(1, int(target / 6.0))
    if len(capacities) > max_events:
        mandatory = {event.event_id for event in events if set(event.candidate_ids) & preferences.forced}
        slots = max(0, max_events - len(mandatory))
        optional = [event.event_id for event in events if event.event_id in capacities and event.event_id not in mandatory]
        chosen = mandatory.copy()
        for index in range(slots):
            group = optional[index * len(optional) // slots:(index + 1) * len(optional) // slots]
            if group:
                chosen.add(max(group, key=lambda key: weights[key]))
        # Short events may contain less than six seconds of useful footage.
        # Add more events when needed instead of unnecessarily underfilling.
        available_seconds = sum(capacities[key] for key in chosen if key in capacities)
        for key in sorted((key for key in optional if key not in chosen), key=lambda key: -weights[key]):
            if available_seconds >= target:
                break
            chosen.add(key)
            available_seconds += capacities[key]
        capacities = {key: value for key, value in capacities.items() if key in chosen}
        weights = {key: value for key, value in weights.items() if key in chosen}
    budgets = dict.fromkeys(capacities, 0.0)
    remaining = min(target, sum(capacities.values()))
    active = set(capacities)
    while active and remaining > 1e-6:
        total_weight = sum(weights[key] for key in active)
        shares = {key: remaining * weights[key] / total_weight for key in active}
        saturated = {key for key in active if shares[key] >= capacities[key] - budgets[key] - 1e-9}
        if not saturated:
            for key, share in shares.items():
                budgets[key] += share
            break
        for key in saturated:
            used = capacities[key] - budgets[key]
            budgets[key] += used
            remaining -= used
        active -= saturated
    return budgets


class MoviePlanningService:
    def __init__(self, repository: SemanticRepository, asset_ids=None):
        self.repository = repository
        self.asset_ids = asset_ids

    def candidates(self, start: date, end: date, provider: str, model: str, cancel_token: Event | None = None, trims=None):
        _check_cancel(cancel_token)
        candidates, warnings = [], []
        assets = self.repository.library.list_assets_in_capture_date_range(start, end)
        if self.asset_ids is not None:
            assets = [asset for asset in assets if asset.asset_id in self.asset_ids]
        cached = self.repository.results_for_assets(assets, provider, model)
        missing = uncertain = 0
        for asset, windows in self.repository.library.iter_assets_with_local_features(assets, LOCAL_ANALYSIS_VERSION):
            _check_cancel(cancel_token)
            rows = cached.get(asset.asset_id, [])
            gaps = uncovered_ranges(asset.duration_seconds, ((row["start_seconds"], row["end_seconds"]) for row in rows)) if asset.duration_seconds else []
            if not rows or sum(end - start for start, end in gaps) > 0.01:
                missing += 1
            if asset.capture_time.confidence < 0.8:
                uncertain += 1
            if not asset.duration_seconds:
                continue
            source = MovieSource(asset.asset_id, str(asset.path.resolve()), asset.size_bytes,
                                 asset.modified_at.isoformat(timespec="microseconds"), asset.duration_seconds,
                                 asset.has_audio, asset.width, asset.height, asset.content_sha256)
            feature_index = LocalFeatureIndex(windows)
            for row in rows:
                moments = validate_moments({"moments": json.loads(row["moments_json"])}, row["end_seconds"] - row["start_seconds"])
                for index, moment in enumerate(moments):
                    candidate_id = f"{row['cache_key']}:{index}"
                    absolute_start = row["start_seconds"] + moment.start_seconds
                    absolute_end = row["start_seconds"] + moment.end_seconds
                    analysis_recorded_at = asset.capture_time.value + timedelta(seconds=absolute_start)
                    analysis_end_at = asset.capture_time.value + timedelta(seconds=absolute_end)
                    edit_notes = ()
                    if trims and candidate_id in trims:
                        trim_start, trim_end = trims[candidate_id]
                        if trim_start < absolute_start or trim_end > absolute_end:
                            edit_notes = ("Manueller Schnitt reicht über den vorgeschlagenen Moment hinaus; Inhalt prüfen",)
                        absolute_start, absolute_end = trim_start, trim_end
                        if (not finite_number(absolute_start) or not finite_number(absolute_end)
                                or not absolute_start < absolute_end <= asset.duration_seconds):
                            raise ValueError("Manuelle Schnittgrenzen liegen außerhalb der Quelle.")
                    if absolute_end > asset.duration_seconds + 1e-6:
                        raise ValueError("Gespeicherter Analysebereich liegt außerhalb seiner Quelle.")
                    quality, signatures, local_notes = feature_index.summarize(absolute_start, absolute_end)
                    candidates.append(CandidateSegment(
                        candidate_id, source, absolute_start, min(absolute_end, asset.duration_seconds),
                        asset.capture_time.value + timedelta(seconds=absolute_start), moment.description, moment.event,
                        moment.activities, moment.people, moment.importance, moment.emotion, moment.audio,
                        moment.uniqueness, moment.confidence, moment.reasons + local_notes + edit_notes, quality, signatures,
                        analysis_recorded_at, analysis_end_at,
                    ))
        if missing:
            warnings.append(f"{missing} Aufnahmen sind nicht vollständig mit diesem Modell analysiert; nur vorhandene Momente werden verwendet.")
        if uncertain:
            warnings.append(f"{uncertain} Aufnahmen haben unsichere Aufnahmezeiten. Zeitstempelquellen in der Bibliothek prüfen.")
        warnings.append("Chronologie nach aufgezeichnetem Kalenderdatum und Ortszeit; unbekannte Zeitzonen werden nicht ergänzt.")
        return sorted(candidates, key=lambda value: value.chronology), warnings

    def build(self, start: date, end: date, target_seconds: float, provider: str, model: str,
              preferences: MoviePreferences | None = None, plan_id: str | None = None,
              cancel_token: Event | None = None) -> MoviePlan:
        if not finite_number(target_seconds, MIN_SEGMENT_SECONDS):
            raise ValueError("Die gewünschte Filmlänge muss mindestens zwei Sekunden betragen.")
        preferences = deepcopy(preferences) if preferences is not None else MoviePreferences()
        preferences.validate()
        all_candidates, warnings = self.candidates(start, end, provider, model, cancel_token, preferences.trims)
        if not all_candidates:
            raise ValueError("Keine gespeicherten Erinnerungen in diesem Zeitraum. Zuerst die Gemini-Analyse ausführen.")
        events = cluster_events(all_candidates)
        event_order = {event.event_id: index for index, event in enumerate(events)}
        by_id = {candidate.candidate_id: candidate for candidate in all_candidates}
        unknown_forced = preferences.forced - by_id.keys()
        if unknown_forced:
            raise ValueError("Erzwungene Momente fehlen im aktuellen Analysebestand. Vor dem Neuplanen die Vorgaben prüfen.")
        stale_trims = preferences.trims.keys() - by_id.keys()
        if stale_trims:
            warnings.append(f"{len(stale_trims)} manuelle Schnittvorgaben fehlen im aktuellen Analysebestand und konnten nicht angewendet werden.")
        unused_weights = preferences.event_weights.keys() - event_order.keys()
        if unused_weights:
            warnings.append(f"{len(unused_weights)} gespeicherte Ereignisgewichte sind keinem aktuellen Ereignis zugeordnet. "
                            "Die Ereignisbildung kann sich geändert haben; Gewichte vor weiterer Neuplanung prüfen.")
        budgets = allocate_event_budgets(events, by_id, target_seconds, preferences)
        if len(budgets) < len(events):
            warnings.append("Für diese Zielzeit und Vorgaben werden repräsentative Ereignisse ausgewählt; nicht jedes Ereignis passt in den Film.")
        event_for = {key: event.event_id for event in events for key in event.candidate_ids}
        selected: list[MovieSegment] = []
        selected_visuals: list[CandidateSegment] = []
        natural_borrowed = 0.0
        used = dict.fromkeys(budgets, 0.0)
        decisions = {key: "Nicht ausgewählt: begrenzte Filmlänge oder ähnliche Momente bereits vertreten." for key in by_id}

        def conflicts(candidate):
            return any(item.source.asset_id == candidate.source.asset_id
                       and item.start_seconds < candidate.end_seconds - 1e-6
                       and candidate.start_seconds < item.end_seconds - 1e-6 for item in selected)

        def visual_redundancy(candidate):
            if len(candidate.visual_samples) < 3:
                return 0.0
            return max((visual_similarity(candidate.visual_samples, item.visual_samples)
                        for item in selected_visuals
                        if min(candidate.duration, item.duration) / max(candidate.duration, item.duration) >= 0.8),
                       default=0.0)

        def append(candidate, duration, forced=False, borrowed=0.0):
            event_id = event_for[candidate.candidate_id]
            reasons = list(candidate.reasons)
            reasons.append("Auf Nutzerwunsch enthalten" if forced else "Ereignisabdeckung und Erinnerungswert")
            if candidate.candidate_id in preferences.trims:
                reasons.append("Manuelle Schnittgrenzen unverändert übernommen")
            if borrowed > 1e-6:
                reasons.append("Vollständiger vorgeschlagener Moment; Zeit zwischen Ereignissen umverteilt")
            if abs(duration - candidate.duration) <= 1e-6 and visual_redundancy(candidate) >= 0.85:
                reasons.append("Bildstichproben ähneln einem bereits gewählten Moment; Bedeutung und Ton bitte prüfen")
            if duration < candidate.duration - 0.01:
                reasons.append("Für die gewünschte Filmlänge gekürzt; Schnittgrenze bitte prüfen")
            segment = MovieSegment(candidate.candidate_id, event_id, candidate.source, candidate.start_seconds,
                                   min(candidate.end_seconds, candidate.start_seconds + duration), candidate.description, tuple(reasons))
            selected.append(segment)
            # The three signatures describe the full candidate. A shortened
            # selection cannot establish similarity using unseen tail frames.
            if abs(duration - candidate.duration) <= 1e-6 and len(candidate.visual_samples) >= 3:
                selected_visuals.append(candidate)
            used[event_id] = used.get(event_id, 0) + duration
            decisions[candidate.candidate_id] = "Ausgewählt: " + "; ".join(reasons)

        for candidate in sorted(by_id.values(), key=lambda value: value.chronology):
            if candidate.candidate_id in preferences.forced:
                if conflicts(candidate):
                    raise ValueError("Erzwungene Momente überlappen sich. Manuelle Schnittgrenzen prüfen.")
                append(candidate, candidate.duration, True)
        total = sum(item.duration for item in selected)
        if total > target_seconds:
            warnings.append("Erzwungene Momente überschreiten die gewünschte Filmlänge und wurden vollständig erhalten.")
        pools = {
            event.event_id: [by_id[key] for key in event.candidate_ids
                             if key not in preferences.excluded | preferences.forced]
            for event in events
        }
        features = {key: _features(candidate) for key, candidate in by_id.items()}
        for key in preferences.excluded & by_id.keys():
            decisions[key] = "Auf Nutzerwunsch ausgeschlossen."
        # Revisit the most underrepresented event after each selection. An event
        # with hundreds of recordings must not crowd out a smaller family moment.
        def eligible(pool, available, remaining):
            # A manual range is indivisible, but does not imply force-inclusion.
            # It may borrow from other event budgets while respecting the target.
            result = []
            for item in pool:
                if item.candidate_id in preferences.trims:
                    if item.duration > remaining + 1e-6:
                        continue
                    if item.duration <= available + 1e-6:
                        result.append(item)
                        continue
                if available >= min(MIN_SEGMENT_SECONDS, item.duration) - 1e-6:
                    result.append(item)
            return result

        while total < target_seconds - 1e-6:
            _check_cancel(cancel_token)
            available_events = []
            for key, pool in pools.items():
                if not pool or key not in budgets:
                    continue
                available = min(target_seconds - total, budgets[key] - used[key])
                if eligible(pool, available, target_seconds - total):
                    available_events.append(key)
            if not available_events:
                # An event may have exhausted its usable ranges before its
                # nominal budget (overlaps, manual exclusions or forced cuts).
                # Reuse that time only after the original balanced pass.
                for key, pool in pools.items():
                    _check_cancel(cancel_token)
                    usable = []
                    for candidate in pool:
                        if conflicts(candidate):
                            decisions[candidate.candidate_id] = "Nicht ausgewählt: überlappt einen bereits enthaltenen Quellbereich."
                        else:
                            usable.append(candidate)
                    pools[key] = usable
                remaining_events = [replace(event, candidate_ids=tuple(
                    candidate.candidate_id for candidate in pools[event.event_id])) for event in events]
                extra = allocate_event_budgets(remaining_events, by_id, target_seconds - total, preferences)
                budgets = {key: used.get(key, 0.0) + seconds for key, seconds in extra.items()}
                for key in budgets:
                    used.setdefault(key, 0.0)
                for key, pool in pools.items():
                    available = min(target_seconds - total, budgets.get(key, 0.0) - used.get(key, 0.0))
                    if eligible(pool, available, target_seconds - total):
                        available_events.append(key)
                if not available_events:
                    break
            event_id = min(available_events, key=lambda key: (used[key] / max(budgets[key], 0.001), event_order[key]))
            pool = pools[event_id]
            selected_here = [by_id[item.candidate_id] for item in selected if item.event_id == event_id]
            event_remaining = max(0.0, budgets[event_id] - used[event_id])
            remaining = target_seconds - total
            # Transfer soft budget, rather than spending other events' time
            # implicitly. Keep their first watchable range funded. Already
            # represented events can donate their entire unspent allocation.
            donors = {}
            for key in budgets:
                if key == event_id or not pools[key]:
                    continue
                available = max(0.0, budgets[key] - used[key])
                reserve = min(MIN_SEGMENT_SECONDS, available) if used[key] <= 1e-6 else 0.0
                if available > reserve:
                    donors[key] = available - reserve
            donor_room = sum(donors.values())
            allowance = max(0.0, min(MAX_BOUNDARY_BORROW_SECONDS,
                budgets[event_id] * MAX_EVENT_BORROW_FRACTION,
                target_seconds * MAX_MOVIE_BORROW_FRACTION - natural_borrowed,
                remaining - event_remaining, donor_room))
            intact_limit = min(remaining, event_remaining + allowance)

            def marginal(candidate):
                redundancy = max((_similarity(features[candidate.candidate_id], features[item.candidate_id])
                                  for item in selected_here), default=0)
                # Visual evidence is movie-wide; repeated activity descriptions
                # remain event-local so another day's family play stays valuable.
                intact = (candidate.candidate_id in preferences.trims
                          or candidate.duration <= intact_limit + 1e-6)
                visual = visual_redundancy(candidate) if intact else 0.0
                redundancy = max(redundancy, 0.9 * visual)
                activity_bonus = 0.08 if candidate.activities and not any(set(candidate.activities) & set(item.activities) for item in selected_here) else 0
                # Labels are visual descriptions only, never inferred identities.
                variety_bonus = 0.04 if candidate.people and not any(set(candidate.people) & set(item.people) for item in selected_here) else 0
                return _value(candidate) * (1 - 0.7 * redundancy) + activity_bonus + variety_bonus

            choices = eligible(pool, min(remaining, event_remaining), remaining)
            fitting = [item for item in choices if item.duration <= intact_limit + 1e-6
                       and (item.duration >= MIN_SEGMENT_SECONDS or item.candidate_id in preferences.trims)]
            # Prefer intact natural ranges when their semantic value is close.
            best = max(choices, key=lambda item: (marginal(item), -item.start_seconds, item.candidate_id))
            fitting_best = max(fitting, key=marginal) if fitting else None
            candidate = fitting_best if fitting_best and marginal(fitting_best) >= marginal(best) * 0.85 else best
            pool.remove(candidate)
            if conflicts(candidate):
                decisions[candidate.candidate_id] = "Nicht ausgewählt: überlappt einen bereits enthaltenen Quellbereich."
                continue
            duration = (candidate.duration if candidate.candidate_id in preferences.trims or candidate.duration <= intact_limit + 1e-6
                        else min(candidate.duration, remaining, event_remaining))
            if duration < min(MIN_SEGMENT_SECONDS, candidate.duration) - 1e-6 and candidate.candidate_id not in preferences.trims:
                decisions[candidate.candidate_id] = "Nicht ausgewählt: verbleibende Filmlänge oder Moment kürzer als zwei Sekunden."
                continue
            borrowed = max(0.0, duration - event_remaining) if candidate.candidate_id not in preferences.trims else 0.0
            if borrowed > 1e-6:
                budgets[event_id] += borrowed
                for key, room in donors.items():
                    budgets[key] -= borrowed * room / donor_room
                natural_borrowed += borrowed
            append(candidate, duration, borrowed=borrowed)
            total += duration
        selected.sort(key=lambda item: by_id[item.candidate_id].chronology)
        selected_ids = {item.candidate_id for item in selected}
        for candidate in by_id.values():
            _check_cancel(cancel_token)
            if candidate.candidate_id in selected_ids | preferences.excluded:
                continue
            if conflicts(candidate):
                decisions[candidate.candidate_id] = "Nicht ausgewählt: überlappt einen bereits enthaltenen Quellbereich."
                continue
            if decisions[candidate.candidate_id].startswith("Nicht ausgewählt: begrenzte"):
                if candidate.candidate_id in preferences.trims and candidate.duration > target_seconds - total + 1e-6:
                    decisions[candidate.candidate_id] = "Nicht ausgewählt: manuell festgelegter Bereich passt nicht vollständig in die verbleibende Filmlänge. Zum Erzwingen ausdrücklich einbeziehen."
                    continue
                similar = any(item.event_id == event_for[candidate.candidate_id]
                              and _similarity(features[candidate.candidate_id], features[item.candidate_id]) >= 0.65 for item in selected)
                visually_similar = visual_redundancy(candidate) >= 0.85
                decisions[candidate.candidate_id] = ("Nicht ausgewählt: lokale Bildstichproben ähneln stark einem enthaltenen Moment; kein sicherer Duplikatnachweis."
                                                    if visually_similar else "Nicht ausgewählt: ein inhaltlich ähnlicher Moment ist bereits enthalten."
                                                    if similar else "Nicht ausgewählt: Zeitbudget des Ereignisses ausgeschöpft; andere Ereignisse bleiben vertreten.")
        if total < target_seconds - 0.1:
            warnings.append(f"Der Film ist {total:.1f} statt {target_seconds:.1f} Sekunden lang; es werden keine Wiederholungen zum Auffüllen erzeugt.")
        plan = MoviePlan(plan_id or str(uuid4()), f"Familienfilm {start:%d.%m.%Y} – {end:%d.%m.%Y}",
                         target_seconds, start.isoformat(), end.isoformat(), provider, model, self.repository.profile,
                         events, selected, preferences, decisions, warnings,
                         planner_version=PLANNER_VERSION,
                         local_analysis_version=LOCAL_ANALYSIS_VERSION if any(candidate.technical_quality is not None for candidate in by_id.values()) else None)
        plan.validate()
        return plan
