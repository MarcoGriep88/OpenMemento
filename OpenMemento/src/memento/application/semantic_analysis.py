from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event

from memento.ai.contracts import (
    AIProvider, ANALYSIS_PROFILE, AnalysisCancelled, ProviderError,
    SemanticResult, check_cancelled, validate_moments,
)
from memento.library.semantic import SemanticRepository, fingerprint
from memento.media.analysis_proxy import create_analysis_proxy
from memento.media.identity import hash_media
from memento.media.metadata import MediaProbeCancelled


@dataclass(frozen=True, slots=True)
class SemanticProgress:
    completed: int
    total: int
    failed: int
    cached: int
    current_path: Path | None
    requests: int = 0
    request_limit: int | None = None


class RequestLimitReached(RuntimeError):
    """No further provider call is authorized in this explicit run."""


@dataclass
class _RequestBudget:
    limit: int | None
    used: int = 0

    def __post_init__(self):
        if self.limit is not None and (type(self.limit) is not int or self.limit < 0):
            raise ValueError("Das Anfragelimit muss eine nicht negative ganze Zahl sein.")

    def check(self):
        if self.limit is not None and self.used >= self.limit:
            raise RequestLimitReached("Anfragelimit erreicht.")


class SourceChangedError(RuntimeError):
    """Known local error whose message is safe to show and persist."""


class SemanticAnalysisService:
    """Analyze durable source ranges once; no movie-generation parameters enter here."""

    def __init__(self, repository: SemanticRepository, provider: AIProvider, proxy_factory=create_analysis_proxy):
        self.repository = repository
        self.provider = provider
        self.proxy_factory = proxy_factory

    def run(self, job_id: str, cancel_token: Event, on_progress=None, *, max_requests: int | None = None) -> str:
        # A fresh budget belongs to each explicit start, including every retry.
        budget = _RequestBudget(max_requests)
        repo = self.repository
        job = repo.get_job(job_id)
        if (job["provider"], job["model"], job["version"]) != (self.provider.name, self.provider.model, repo.profile):
            raise ValueError("Der Auftrag benötigt seinen ursprünglichen Anbieter, sein Modell und seine Analyseversion.")
        repo.set_job_status(job_id, "running")
        items = repo.items(job_id)
        completed = failed = cached = 0
        verified_sources = set()
        for item in items:
            asset = None
            try:
                check_cancelled(cancel_token)
                asset = repo.library.get_asset(item["asset_id"])
                if asset is None:
                    raise RuntimeError("Quelle fehlt.")
                if fingerprint(asset) != (item["size_bytes"], item["modified_at"]):
                    raise SourceChangedError("Die Quelle wurde neu indexiert. Bitte einen neuen KI-Auftrag anlegen.")
                self._check_source(asset)
                if repo.cached(item["cache_key"]) is not None:
                    repo.set_item_status(job_id, item["cache_key"], "skipped")
                    cached += 1
                else:
                    budget.check()
                    if asset.content_sha256 and asset.asset_id not in verified_sources:
                        if hash_media(asset.path, cancel_token) != asset.content_sha256:
                            raise SourceChangedError("Quellinhalt verändert. Bitte vor dem Upload neu indexieren und einen neuen Auftrag anlegen.")
                        verified_sources.add(asset.asset_id)
                    repo.set_item_status(job_id, item["cache_key"], "processing")
                    with tempfile.TemporaryDirectory(prefix="memento-analysis-") as directory:
                        proxy = self.proxy_factory(asset.path, item["start_seconds"], item["end_seconds"],
                                                   Path(directory) / "analysis.mp4", cancel_token)
                        self._check_source(asset)
                        duration = item["end_seconds"] - item["start_seconds"]
                        result = self._request(job_id, item, proxy, duration, cancel_token, budget)
                        # Validate even third-party/local providers at the application boundary.
                        moments = validate_moments({"moments": [moment.to_dict() for moment in result.moments]}, duration)
                        if any(type(value) is not int or value < 0 for value in (result.input_tokens, result.output_tokens)):
                            raise ValueError("Invalid provider usage")
                        self._check_source(asset)
                        repo.save_result(job, item, SemanticResult(moments, result.input_tokens, result.output_tokens))
                completed += 1
            except RequestLimitReached:
                repo.set_item_status(job_id, item["cache_key"], "pending")
                repo.set_job_status(job_id, "request_limit")
                if on_progress:
                    on_progress(SemanticProgress(completed, len(items), failed, cached, asset.path if asset else None,
                                                 budget.used, budget.limit))
                return "request_limit"
            except (AnalysisCancelled, MediaProbeCancelled):
                repo.set_item_status(job_id, item["cache_key"], "pending")
                repo.set_job_status(job_id, "cancelled")
                return "cancelled"
            except Exception as exc:
                # No raw adapter exception (possibly containing credentials/media) is persisted.
                message = str(exc) if isinstance(exc, (ProviderError, SourceChangedError)) else "Lokale Quelle oder Analyse ungültig. Quelle prüfen und Auftrag fortsetzen."
                repo.set_item_status(job_id, item["cache_key"], "failed", message)
                failed += 1
                if isinstance(exc, ProviderError) and exc.abort_job:
                    repo.set_job_status(job_id, "complete_with_errors")
                    if on_progress:
                        on_progress(SemanticProgress(completed, len(items), failed, cached, asset.path if asset else None,
                                                     budget.used, budget.limit))
                    return "complete_with_errors"
            if on_progress:
                on_progress(SemanticProgress(completed, len(items), failed, cached, asset.path if asset else None,
                                             budget.used, budget.limit))
        status = "complete_with_errors" if failed else "complete"
        repo.set_job_status(job_id, status)
        return status

    def _request(self, job_id, item, proxy, duration, token, budget):
        for attempt in range(3):
            check_cancelled(token)
            budget.check()
            self.repository.set_item_status(job_id, item["cache_key"], "processing", attempt=True)
            budget.used += 1
            try:
                return self.provider.analyze(proxy, duration, token)
            except ProviderError as exc:
                if not exc.retryable or attempt == 2:
                    raise
                check_cancelled(token)
                budget.check()
                if token.wait(2 ** attempt):
                    raise AnalysisCancelled("Analyse abgebrochen.") from None
        raise AssertionError("Unreachable")

    @staticmethod
    def _check_source(asset):
        stat = asset.path.stat()
        if (stat.st_size, datetime.fromtimestamp(stat.st_mtime).astimezone()) != (asset.size_bytes, asset.modified_at):
            raise SourceChangedError("Quelle wurde verändert; bitte neu indexieren und einen neuen KI-Auftrag anlegen.")
