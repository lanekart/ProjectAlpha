from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from alpha.historical_replay.breakout_source_gap import BreakoutGapCause
from alpha.historical_replay.breakout_source_gap_service import (
    build_project_breakout_source_gap_audit,
)
from alpha.historical_replay.historical_source_evaluation import (
    HistoricalSourceEvaluationManifest,
    HistoricalSourceEvaluationManifestRecord,
    HistoricalSourceSampleManifest,
    deterministic_historical_source_sample,
    filter_historical_source_manifest,
)
from alpha.historical_replay.historical_source_evaluation_service import (
    build_project_historical_source_evaluation,
)
from alpha.historical_replay.upstox_historical_probe import (
    DEFAULT_UPSTOX_HISTORICAL_EVIDENCE_PATH,
    UPSTOX_HISTORICAL_EVIDENCE_VERSION,
    UPSTOX_HISTORICAL_PROBE_VERSION,
    UPSTOX_INSTRUMENT_SEARCH_DEFAULT_RECORDS,
    UpstoxAdjustmentAuditEngine,
    UpstoxAnalyticsTokenConfig,
    UpstoxAuthProbeResult,
    UpstoxAuthProbeStatus,
    UpstoxHistoricalCandleValidator,
    UpstoxHistoricalEvidenceDataset,
    UpstoxHistoricalEvidenceReport,
    UpstoxHistoricalEvidenceReportEngine,
    UpstoxHistoricalEvidenceRepository,
    UpstoxIdentityResolver,
    UpstoxOperationalMetrics,
    UpstoxProbeErrorCategory,
    UpstoxProbeHttpError,
    UpstoxProbeHttpResponse,
    UpstoxReadOnlyHistoricalClient,
    load_official_upstox_instruments,
)

_DEFAULT_SAMPLE_SIZE = 30


@dataclass(frozen=True, slots=True)
class UpstoxHistoricalTrialPlan:
    manifest: HistoricalSourceEvaluationManifest
    sample: HistoricalSourceSampleManifest
    targets: tuple[HistoricalSourceEvaluationManifestRecord, ...]
    entry_timing_by_candidate: tuple[tuple[str, str | None], ...]
    scope: str
    filters_applied: tuple[str, ...]
    production_influence: bool = False

    @property
    def entry_timing_index(self) -> dict[str, str | None]:
        return dict(self.entry_timing_by_candidate)


@dataclass(frozen=True, slots=True)
class UpstoxHistoricalProbeRun:
    plan: UpstoxHistoricalTrialPlan
    authentication: UpstoxAuthProbeResult
    dataset: UpstoxHistoricalEvidenceDataset | None
    report: UpstoxHistoricalEvidenceReport
    attempted_candidates: int
    resumed_candidates: int
    stopped_early: bool
    stop_reason: str | None
    network_enabled: bool
    operational_metrics: UpstoxOperationalMetrics
    production_influence: bool = False


class UpstoxHistoricalProbeService:
    def __init__(
        self,
        *,
        client: UpstoxReadOnlyHistoricalClient | None = None,
        repository: UpstoxHistoricalEvidenceRepository | None = None,
    ) -> None:
        self.client = client or UpstoxReadOnlyHistoricalClient()
        self.repository = repository or UpstoxHistoricalEvidenceRepository()
        self.identity_resolver = UpstoxIdentityResolver()
        self.validator = UpstoxHistoricalCandleValidator()
        self.adjustment_engine = UpstoxAdjustmentAuditEngine()
        self.report_engine = UpstoxHistoricalEvidenceReportEngine()

    def authentication_probe(self, *, live: bool) -> UpstoxAuthProbeResult:
        return self.client.authentication_probe(live=live)

    def plan(
        self,
        *,
        live: bool = False,
        sample: bool = True,
        full_population: bool = False,
        confirm_full_population: bool = False,
        candidate_id: str | None = None,
        symbol: str | None = None,
        year: int | None = None,
        gap_cause: BreakoutGapCause | None = None,
        limit: int | None = None,
    ) -> UpstoxHistoricalTrialPlan:
        if full_population and not live:
            raise ValueError("--full-population requires --live")
        if full_population and not confirm_full_population:
            raise ValueError("--full-population requires --confirm-full-population")
        if limit is not None and limit <= 0:
            raise ValueError("--limit must be positive")
        baseline = build_project_historical_source_evaluation(dry_run=True)
        manifest = baseline.manifest
        if full_population and (
            len(manifest.records) != 657
            or manifest.source_required_count != 608
            or manifest.recovery_uncertain_count != 49
        ):
            raise ValueError(
                "full-population manifest invariant failed; expected "
                "657 candidates, 608 source-required, and 49 recovery-uncertain"
            )
        filtered = filter_historical_source_manifest(
            manifest.records,
            symbol=symbol,
            candidate_id=candidate_id,
            year=year,
            gap_cause=gap_cause,
        )
        filtered_manifest = _filtered_manifest(manifest, filtered)
        trial_sample = deterministic_historical_source_sample(
            filtered_manifest,
            sample_size=min(_DEFAULT_SAMPLE_SIZE, max(1, len(filtered))),
        )
        targets = filtered if full_population else trial_sample.records
        if limit is not None:
            targets = targets[:limit]
        timing = _entry_timing_index()
        applied = tuple(
            item
            for item in (
                f"candidate_id={candidate_id}" if candidate_id else None,
                f"symbol={symbol.upper()}" if symbol else None,
                f"year={year}" if year else None,
                f"gap_cause={gap_cause.value}" if gap_cause else None,
                f"limit={limit}" if limit else None,
            )
            if item is not None
        )
        return UpstoxHistoricalTrialPlan(
            manifest=manifest,
            sample=trial_sample,
            targets=targets,
            entry_timing_by_candidate=tuple(
                (item.candidate_id, timing.get(item.candidate_id)) for item in targets
            ),
            scope="FULL_POPULATION" if full_population else "SAMPLE",
            filters_applied=applied,
        )

    def run(
        self,
        *,
        live: bool = False,
        sample: bool = True,
        full_population: bool = False,
        confirm_full_population: bool = False,
        candidate_id: str | None = None,
        symbol: str | None = None,
        year: int | None = None,
        gap_cause: BreakoutGapCause | None = None,
        limit: int | None = None,
        resume: bool = False,
        dry_run: bool = False,
    ) -> UpstoxHistoricalProbeRun:
        plan = self.plan(
            live=live,
            sample=sample,
            full_population=full_population,
            confirm_full_population=confirm_full_population,
            candidate_id=candidate_id,
            symbol=symbol,
            year=year,
            gap_cause=gap_cause,
            limit=limit,
        )
        existing = self.repository.load()
        if not live or dry_run:
            auth = self.client.authentication_probe(live=False)
            dataset = _persisted_dataset_for_report(existing, plan)
            report = self.report_engine.build(
                manifest=plan.manifest,
                sample=plan.sample,
                dataset=dataset,
                entry_timing_by_candidate=plan.entry_timing_index,
            )
            return UpstoxHistoricalProbeRun(
                plan=plan,
                authentication=auth,
                dataset=dataset,
                report=report,
                attempted_candidates=0,
                resumed_candidates=0,
                stopped_early=False,
                stop_reason=None,
                network_enabled=False,
                operational_metrics=(
                    dataset.operational_metrics
                    if dataset is not None
                    else UpstoxOperationalMetrics()
                ),
            )
        if full_population and not _full_population_prerequisite_satisfied(
            existing, plan
        ):
            raise ValueError(
                "full-population trial is blocked until a persisted sample has "
                "at least one successful historical observation"
            )
        auth = self.client.authentication_probe(live=True)
        if auth.status is not UpstoxAuthProbeStatus.TOKEN_ACCEPTED:
            report = self.report_engine.build(
                manifest=plan.manifest,
                sample=plan.sample,
                dataset=_empty_dataset(plan, self.client.config, auth.status),
                entry_timing_by_candidate=plan.entry_timing_index,
            )
            return UpstoxHistoricalProbeRun(
                plan=plan,
                authentication=auth,
                dataset=None,
                report=report,
                attempted_candidates=0,
                resumed_candidates=0,
                stopped_early=True,
                stop_reason=auth.reason,
                network_enabled=True,
                operational_metrics=self.client.operational_metrics(),
            )
        resumable = _resumable_dataset(existing, plan) if resume else None
        if resumable is not None:
            previous = resumable
        else:
            previous = _empty_dataset(plan, self.client.config, auth.status)
        records = {item.candidate_id: item for item in previous.records}
        resumed = len(records)
        attempted = 0
        stopped = False
        stop_reason: str | None = None
        official_path = os.environ.get("UPSTOX_INSTRUMENT_REGISTRY")
        official = load_official_upstox_instruments(official_path)
        timing = plan.entry_timing_index
        search_cache: dict[str, UpstoxProbeHttpResponse] = {}
        for target in plan.targets:
            if target.candidate_id in records:
                continue
            attempted += 1
            try:
                search = search_cache.get(target.historical_symbol)
                if search is None:
                    search = self.client.search_instruments(target.historical_symbol)
                    search_cache[target.historical_symbol] = search
                identity = self.identity_resolver.resolve(
                    target,
                    search_response=search.payload,
                    official_instruments=official,
                )
                identity = replace(
                    identity,
                    identity_search_query=target.historical_symbol,
                    identity_search_page_size=UPSTOX_INSTRUMENT_SEARCH_DEFAULT_RECORDS,
                )
                if identity.instrument_key is None:
                    evidence = self.validator.evaluate(
                        target,
                        identity,
                        entry_timing_state=timing.get(target.candidate_id),
                    )
                else:
                    batch = self.client.historical_candles(
                        identity.instrument_key,
                        from_date=target.required_start_date,
                        to_date=target.required_end_date,
                    )
                    adjustment = self.adjustment_engine.evaluate(batch.candles, ())
                    evidence = self.validator.evaluate(
                        target,
                        identity,
                        batch=batch,
                        adjustment=adjustment,
                        entry_timing_state=timing.get(target.candidate_id),
                    )
            except UpstoxProbeHttpError as exc:
                identity = self.identity_resolver.resolve(
                    target,
                    official_instruments=official,
                )
                evidence = self.validator.evaluate(
                    target,
                    identity,
                    error=exc,
                    entry_timing_state=timing.get(target.candidate_id),
                )
                if exc.category in {
                    UpstoxProbeErrorCategory.AUTHENTICATION_FAILED,
                    UpstoxProbeErrorCategory.TOKEN_EXPIRED,
                    UpstoxProbeErrorCategory.ENDPOINT_FORBIDDEN,
                }:
                    stopped = True
                    stop_reason = exc.sanitized_message
            records[target.candidate_id] = evidence
            dataset = replace(
                previous,
                records=tuple(records[key] for key in sorted(records)),
                operational_metrics=_combine_operational_metrics(
                    previous.operational_metrics,
                    self.client.operational_metrics(),
                ),
            )
            self.repository.save(dataset)
            if stopped:
                break
        dataset = replace(
            previous,
            records=tuple(records[key] for key in sorted(records)),
            operational_metrics=_combine_operational_metrics(
                previous.operational_metrics,
                self.client.operational_metrics(),
            ),
        )
        report = self.report_engine.build(
            manifest=plan.manifest,
            sample=plan.sample,
            dataset=dataset,
            entry_timing_by_candidate=plan.entry_timing_index,
        )
        return UpstoxHistoricalProbeRun(
            plan=plan,
            authentication=auth,
            dataset=dataset,
            report=report,
            attempted_candidates=attempted,
            resumed_candidates=resumed,
            stopped_early=stopped,
            stop_reason=stop_reason,
            network_enabled=True,
            operational_metrics=dataset.operational_metrics,
        )


def build_upstox_evidence_report(
    *,
    evidence_path: Path | str = DEFAULT_UPSTOX_HISTORICAL_EVIDENCE_PATH,
) -> UpstoxHistoricalEvidenceReport:
    service = UpstoxHistoricalProbeService(
        repository=UpstoxHistoricalEvidenceRepository(evidence_path)
    )
    run = service.run(live=False)
    return run.report


def _entry_timing_index() -> dict[str, str | None]:
    audit = build_project_breakout_source_gap_audit()
    return {
        item.candidate_id: item.context.entry_timing_state
        for item in audit.coverage.records
    }


def _filtered_manifest(
    manifest: HistoricalSourceEvaluationManifest,
    records: tuple[HistoricalSourceEvaluationManifestRecord, ...],
) -> HistoricalSourceEvaluationManifest:
    return replace(
        manifest,
        records=records,
        source_required_count=sum(
            item.recovery_population == "REQUIRES_NEW_EXTERNAL_SOURCE"
            for item in records
        ),
        recovery_uncertain_count=sum(
            item.recovery_population == "RECOVERY_UNCERTAIN" for item in records
        ),
        unique_symbols=len({item.historical_symbol for item in records}),
        earliest_required_date=min(
            (item.required_start_date for item in records), default=None
        ),
        latest_required_date=max(
            (item.required_end_date for item in records), default=None
        ),
    )


def _empty_dataset(
    plan: UpstoxHistoricalTrialPlan,
    config: UpstoxAnalyticsTokenConfig,
    authentication: UpstoxAuthProbeStatus,
) -> UpstoxHistoricalEvidenceDataset:
    return UpstoxHistoricalEvidenceDataset(
        dataset_version=UPSTOX_HISTORICAL_EVIDENCE_VERSION,
        probe_version=UPSTOX_HISTORICAL_PROBE_VERSION,
        source_manifest_version=plan.manifest.manifest_version,
        source_manifest_checksum=plan.manifest.checksum,
        sample_checksum=plan.sample.checksum,
        scope=plan.scope,
        credential_status=config.credential_status,
        authentication_status=authentication,
        records=(),
    )


def _dataset_matches(
    dataset: UpstoxHistoricalEvidenceDataset | None,
    plan: UpstoxHistoricalTrialPlan,
) -> bool:
    return (
        dataset is not None
        and dataset.dataset_version == UPSTOX_HISTORICAL_EVIDENCE_VERSION
        and dataset.source_manifest_checksum == plan.manifest.checksum
        and dataset.sample_checksum == plan.sample.checksum
        and dataset.scope == plan.scope
    )


def _sample_succeeded(dataset: UpstoxHistoricalEvidenceDataset | None) -> bool:
    return (
        dataset is not None
        and dataset.scope == "SAMPLE"
        and dataset.authentication_status is UpstoxAuthProbeStatus.TOKEN_ACCEPTED
        and any(item.returned_bar_count > 0 for item in dataset.records)
    )


def _full_population_prerequisite_satisfied(
    dataset: UpstoxHistoricalEvidenceDataset | None,
    plan: UpstoxHistoricalTrialPlan,
) -> bool:
    return _sample_succeeded(dataset) or (
        dataset is not None
        and dataset.scope == "FULL_POPULATION"
        and dataset.authentication_status is UpstoxAuthProbeStatus.TOKEN_ACCEPTED
        and dataset.source_manifest_checksum == plan.manifest.checksum
        and any(item.returned_bar_count > 0 for item in dataset.records)
    )


def _resumable_dataset(
    dataset: UpstoxHistoricalEvidenceDataset | None,
    plan: UpstoxHistoricalTrialPlan,
) -> UpstoxHistoricalEvidenceDataset | None:
    if _dataset_matches(dataset, plan):
        return dataset
    if (
        dataset is not None
        and plan.scope == "FULL_POPULATION"
        and dataset.scope == "SAMPLE"
        and dataset.source_manifest_checksum == plan.manifest.checksum
        and dataset.sample_checksum == plan.sample.checksum
        and dataset.authentication_status is UpstoxAuthProbeStatus.TOKEN_ACCEPTED
    ):
        return replace(dataset, scope="FULL_POPULATION")
    return None


def _persisted_dataset_for_report(
    dataset: UpstoxHistoricalEvidenceDataset | None,
    plan: UpstoxHistoricalTrialPlan,
) -> UpstoxHistoricalEvidenceDataset | None:
    if dataset is None or dataset.source_manifest_checksum != plan.manifest.checksum:
        return None
    if dataset.scope != "FULL_POPULATION" or not plan.filters_applied:
        return dataset
    target_ids = {item.candidate_id for item in plan.targets}
    return replace(
        dataset,
        records=tuple(
            item for item in dataset.records if item.candidate_id in target_ids
        ),
    )


def _combine_operational_metrics(
    previous: UpstoxOperationalMetrics,
    current: UpstoxOperationalMetrics,
) -> UpstoxOperationalMetrics:
    requests = previous.total_network_requests + current.total_network_requests
    elapsed = previous.elapsed_seconds + current.elapsed_seconds
    rate = requests / elapsed if elapsed > 0 else None
    return UpstoxOperationalMetrics(
        total_network_requests=requests,
        successful_requests=previous.successful_requests + current.successful_requests,
        authentication_failures=(
            previous.authentication_failures + current.authentication_failures
        ),
        rate_limit_responses=(
            previous.rate_limit_responses + current.rate_limit_responses
        ),
        transient_failures=previous.transient_failures + current.transient_failures,
        permanent_failures=previous.permanent_failures + current.permanent_failures,
        retries=previous.retries + current.retries,
        elapsed_seconds=elapsed,
        request_rate_per_second=rate,
        token_exposure_incidents=0,
        account_endpoint_calls=0,
        order_endpoint_calls=0,
    )


__all__ = [
    "UpstoxHistoricalProbeRun",
    "UpstoxHistoricalProbeService",
    "UpstoxHistoricalTrialPlan",
    "build_upstox_evidence_report",
]
