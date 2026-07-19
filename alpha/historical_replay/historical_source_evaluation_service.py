from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path

from alpha.historical_replay.breakout_source_gap import (
    BreakoutGapAttributionRecord,
    BreakoutGapCause,
    BreakoutGapRecoveryClass,
)
from alpha.historical_replay.breakout_source_gap_service import (
    build_project_breakout_source_gap_audit,
)
from alpha.historical_replay.historical_source_evaluation import (
    HISTORICAL_SOURCE_MANIFEST_VERSION,
    HistoricalCredentialStatus,
    HistoricalSourceCandidate,
    HistoricalSourceEvaluationEngine,
    HistoricalSourceEvaluationManifest,
    HistoricalSourceEvaluationManifestRecord,
    HistoricalSourceObservation,
    HistoricalSourceRecommendationReport,
    build_historical_source_candidates,
    deterministic_historical_source_sample,
    filter_historical_source_manifest,
    parse_historical_source_provider,
)

_TARGET_RECOVERY_CLASSES = {
    BreakoutGapRecoveryClass.REQUIRES_NEW_EXTERNAL_SOURCE,
    BreakoutGapRecoveryClass.RECOVERY_UNCERTAIN,
}
_DEFAULT_SAMPLE_SIZE = 30
_EXCHANGE_HOLIDAY_BUFFER_DAYS = 30


def build_project_historical_source_evaluation(
    *,
    provider: str | None = None,
    sample_size: int = _DEFAULT_SAMPLE_SIZE,
    full_population: bool = False,
    symbol: str | None = None,
    candidate_id: str | None = None,
    year: int | None = None,
    gap_cause: BreakoutGapCause | None = None,
    credential_status: HistoricalCredentialStatus | None = None,
    dry_run: bool = False,
    observations: Sequence[HistoricalSourceObservation] = (),
    reference_path: Path | str | None = None,
    learning_path: Path | str | None = None,
    database_path: Path | str | None = None,
    raw_data_dir: Path | str | None = None,
    extracted_data_dir: Path | str | None = None,
    environment: Mapping[str, str] | None = None,
) -> HistoricalSourceRecommendationReport:
    """Build a read-only evaluation from the existing source-gap audit."""
    audit = build_project_breakout_source_gap_audit(
        reference_path=reference_path,
        learning_path=learning_path,
        database_path=database_path,
        raw_data_dir=raw_data_dir,
        extracted_data_dir=extracted_data_dir,
    )
    manifest = build_historical_source_manifest(audit.coverage.records)
    selected_records = filter_historical_source_manifest(
        manifest.records,
        symbol=symbol,
        candidate_id=candidate_id,
        year=year,
        gap_cause=gap_cause,
    )
    selected_manifest = _subset_manifest(manifest, selected_records)
    sample = deterministic_historical_source_sample(
        selected_manifest,
        sample_size=min(sample_size, max(1, len(selected_records))),
    )
    providers = build_historical_source_candidates()
    if provider is not None:
        provider_id = parse_historical_source_provider(provider, providers)
        providers = tuple(item for item in providers if item.provider_id == provider_id)
    statuses = historical_source_credential_statuses(
        providers,
        override=credential_status,
        environment=environment,
    )
    return HistoricalSourceEvaluationEngine().evaluate(
        manifest=selected_manifest,
        sample=sample,
        providers=providers,
        credential_statuses=statuses,
        observations=observations,
        full_population=full_population,
        dry_run=dry_run,
    )


def build_historical_source_manifest(
    records: Sequence[BreakoutGapAttributionRecord],
) -> HistoricalSourceEvaluationManifest:
    selected = tuple(
        sorted(
            (
                _manifest_record(record)
                for record in records
                if record.recovery_class in _TARGET_RECOVERY_CLASSES
            ),
            key=lambda item: (
                item.candidate_date,
                item.historical_symbol,
                item.candidate_id,
            ),
        )
    )
    return HistoricalSourceEvaluationManifest(
        manifest_version=HISTORICAL_SOURCE_MANIFEST_VERSION,
        records=selected,
        source_required_count=sum(
            item.recovery_population
            == BreakoutGapRecoveryClass.REQUIRES_NEW_EXTERNAL_SOURCE.value
            for item in selected
        ),
        recovery_uncertain_count=sum(
            item.recovery_population
            == BreakoutGapRecoveryClass.RECOVERY_UNCERTAIN.value
            for item in selected
        ),
        unique_symbols=len({item.historical_symbol for item in selected}),
        earliest_required_date=min(
            (item.required_start_date for item in selected),
            default=None,
        ),
        latest_required_date=max(
            (item.required_end_date for item in selected),
            default=None,
        ),
        checksum=_manifest_checksum(selected),
    )


def historical_source_credential_statuses(
    providers: Sequence[HistoricalSourceCandidate],
    *,
    override: HistoricalCredentialStatus | None = None,
    environment: Mapping[str, str] | None = None,
) -> dict[str, HistoricalCredentialStatus]:
    """Report credential presence without returning or logging credential values."""
    values = os.environ if environment is None else environment
    statuses: dict[str, HistoricalCredentialStatus] = {}
    for provider in providers:
        if not provider.requires_credentials:
            statuses[provider.provider_id] = HistoricalCredentialStatus.NOT_REQUIRED
            continue
        if override is not None:
            statuses[provider.provider_id] = override
            continue
        configured = _provider_credentials_configured(provider, values)
        statuses[provider.provider_id] = (
            HistoricalCredentialStatus.CONFIGURED
            if configured
            else HistoricalCredentialStatus.SUBSCRIPTION_REQUIRED
        )
    return statuses


def parse_historical_credential_status(
    value: str,
) -> HistoricalCredentialStatus | None:
    normalized = value.strip().upper().replace("-", "_")
    if normalized == "AUTO":
        return None
    try:
        parsed = HistoricalCredentialStatus(normalized)
    except ValueError as exc:
        allowed = ", ".join(
            ("AUTO", *(item.value for item in HistoricalCredentialStatus))
        )
        raise ValueError(
            f"unsupported credential status {value!r}; choose one of: {allowed}"
        ) from exc
    if parsed is HistoricalCredentialStatus.NOT_REQUIRED:
        raise ValueError("NOT_REQUIRED is determined by the provider")
    return parsed


def _manifest_record(
    record: BreakoutGapAttributionRecord,
) -> HistoricalSourceEvaluationManifestRecord:
    cause = record.primary_gap_cause
    recovery = record.recovery_class
    if cause is None or recovery not in _TARGET_RECOVERY_CLASSES:
        raise ValueError("manifest record requires an attributed target gap")
    source = record.context.source
    required_end = source.requested_end_date or _previous_weekday(record.candidate_date)
    required_start = _conservative_required_start(
        required_end,
        record.bars_requested,
    )
    identity_uncertainty = any(
        value.startswith("UNAVAILABLE")
        for value in (
            source.listing_date_evidence,
            source.delisting_date_evidence,
            source.symbol_change_status,
        )
    )
    return HistoricalSourceEvaluationManifestRecord(
        candidate_id=record.candidate_id,
        candidate_date=record.candidate_date,
        current_symbol=None,
        historical_symbol=record.historical_symbol,
        permanent_identifier=record.instrument_identifier,
        required_start_date=required_start,
        required_end_date=required_end,
        required_start_basis=(
            "121 weekday sessions including the cutoff, plus a deterministic "
            "30-calendar-day exchange-holiday buffer; providers must return "
            "the latest 121 valid completed sessions"
        ),
        minimum_bars_required=record.bars_requested,
        gap_cause=cause,
        corporate_action_requirement=(
            cause is BreakoutGapCause.CORPORATE_ACTION_AMBIGUITY
            or BreakoutGapCause.CORPORATE_ACTION_AMBIGUITY
            in record.secondary_gap_causes
        ),
        identity_uncertainty=identity_uncertainty,
        recovery_population=recovery.value,
        replay_year=record.candidate_date.year,
        sector=record.context.sector,
        market_regime=record.context.market_regime,
        setup_type=record.context.setup_type,
        liquidity_proxy=record.context.liquidity_proxy,
        continuity_status=record.context.inactive_or_delisted_status,
    )


def _conservative_required_start(required_end: date, bars: int) -> date:
    if bars <= 0:
        raise ValueError("minimum bars must be positive")
    cursor = required_end
    sessions = 1 if cursor.weekday() < 5 else 0
    while sessions < bars:
        cursor -= timedelta(days=1)
        if cursor.weekday() < 5:
            sessions += 1
    return cursor - timedelta(days=_EXCHANGE_HOLIDAY_BUFFER_DAYS)


def _previous_weekday(value: date) -> date:
    cursor = value - timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor


def _subset_manifest(
    manifest: HistoricalSourceEvaluationManifest,
    records: tuple[HistoricalSourceEvaluationManifestRecord, ...],
) -> HistoricalSourceEvaluationManifest:
    return HistoricalSourceEvaluationManifest(
        manifest_version=manifest.manifest_version,
        records=records,
        source_required_count=sum(
            item.recovery_population
            == BreakoutGapRecoveryClass.REQUIRES_NEW_EXTERNAL_SOURCE.value
            for item in records
        ),
        recovery_uncertain_count=sum(
            item.recovery_population
            == BreakoutGapRecoveryClass.RECOVERY_UNCERTAIN.value
            for item in records
        ),
        unique_symbols=len({item.historical_symbol for item in records}),
        earliest_required_date=min(
            (item.required_start_date for item in records),
            default=None,
        ),
        latest_required_date=max(
            (item.required_end_date for item in records),
            default=None,
        ),
        checksum=_manifest_checksum(records),
    )


def _manifest_checksum(
    records: Sequence[HistoricalSourceEvaluationManifestRecord],
) -> str:
    payload = json.dumps(
        tuple(asdict(item) for item in records),
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _provider_credentials_configured(
    provider: HistoricalSourceCandidate,
    environment: Mapping[str, str],
) -> bool:
    names = provider.credential_environment_names
    if provider.provider_id == "UPSTOX_HISTORICAL_V3":
        return any(bool(environment.get(name, "").strip()) for name in names)
    return all(bool(environment.get(name, "").strip()) for name in names)


__all__ = [
    "build_historical_source_manifest",
    "build_project_historical_source_evaluation",
    "historical_source_credential_statuses",
    "parse_historical_credential_status",
]
