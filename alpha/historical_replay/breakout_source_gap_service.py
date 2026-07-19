from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from alpha.candidate_learning.entry_timing import build_entry_timing_replay_report
from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
)
from alpha.candidate_learning.raw_universe import (
    RawCandidateForwardOutcome,
    RawCandidateRecord,
    RawForwardWindowOutcome,
)
from alpha.candidate_learning.repository import LearningLedgerRepository
from alpha.config.settings import settings
from alpha.historical_replay.breakout_reference import (
    BreakoutReferenceReadinessStatus,
    BreakoutReferenceReconstructionRecord,
    BreakoutReferenceRepository,
)
from alpha.historical_replay.breakout_source_gap import (
    BreakoutCandidateDiagnosticContext,
    BreakoutGapCause,
    BreakoutGapRecoveryClass,
    BreakoutSourceGapAuditEngine,
    BreakoutSourceGapAuditReport,
    BreakoutSourceProbe,
    filter_breakout_gap_records,
)
from alpha.market_intelligence.point_in_time_store import (
    PointInTimeAnalyticalRepository,
)
from alpha.market_truth.consumer_repository import MarketTruthPriceRepository

_LEGACY_ARCHIVE = re.compile(
    r"^cm(?P<day>\d{2})(?P<month>[A-Z]{3})(?P<year>\d{4})bhav\.csv$"
)
_UDIFF_ARCHIVE = re.compile(r"^BhavCopy_NSE_CM_0_0_0_(?P<date>\d{8})_F_0000\.csv$")
_RAW_ARCHIVE = re.compile(r"^bhavcopy_(?P<date>\d{4}-\d{2}-\d{2})\.zip$")


@dataclass(frozen=True, slots=True)
class _SourceInventory:
    global_start: date | None
    global_end: date | None
    global_sessions: int
    symbol_ranges: dict[str, tuple[date, date, int]]
    raw_archive_dates: frozenset[date]
    extracted_cache_dates: frozenset[date]


def build_project_breakout_source_gap_audit(
    *,
    group_cause: BreakoutGapCause | None = None,
    recovery_class: BreakoutGapRecoveryClass | None = None,
    provider: str | None = None,
    symbol: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    year: int | None = None,
    minimum_sample: int = 10,
    limit: int | None = None,
    reference_path: Path | str | None = None,
    learning_path: Path | str | None = None,
    database_path: Path | str | None = None,
    raw_data_dir: Path | str | None = None,
    extracted_data_dir: Path | str | None = None,
) -> BreakoutSourceGapAuditReport:
    records = BreakoutReferenceRepository(reference_path).load_dataset().records
    ledger = LearningLedgerRepository(learning_path)
    contexts = build_breakout_gap_contexts(
        records=records,
        raw_candidates=ledger.load_raw_records(),
        decisions=ledger.load_records(),
        raw_outcomes=ledger.load_raw_outcomes(),
        outcomes=ledger.load_outcomes(),
        database_path=database_path,
        raw_data_dir=raw_data_dir,
        extracted_data_dir=extracted_data_dir,
    )
    engine = BreakoutSourceGapAuditEngine()
    full = engine.analyze(
        records=records,
        contexts=contexts,
        minimum_sample=minimum_sample,
    )
    selected = filter_breakout_gap_records(
        full.coverage.records,
        cause=group_cause,
        recovery_class=recovery_class,
        provider=provider,
        symbol=symbol,
        from_date=from_date,
        to_date=to_date,
        year=year,
        limit=limit,
    )
    if len(selected) == len(full.coverage.records):
        return full
    record_index = {item.candidate_id: item for item in records}
    context_index = {item.candidate_id: item for item in contexts}
    return engine.analyze(
        records=tuple(record_index[item.candidate_id] for item in selected),
        contexts=tuple(context_index[item.candidate_id] for item in selected),
        minimum_sample=minimum_sample,
    )


def build_breakout_gap_contexts(
    *,
    records: tuple[BreakoutReferenceReconstructionRecord, ...],
    raw_candidates: tuple[RawCandidateRecord, ...],
    decisions: tuple[CandidateDecisionRecord, ...],
    raw_outcomes: tuple[RawCandidateForwardOutcome, ...],
    outcomes: tuple[CandidateForwardOutcome, ...],
    database_path: Path | str | None = None,
    raw_data_dir: Path | str | None = None,
    extracted_data_dir: Path | str | None = None,
) -> tuple[BreakoutCandidateDiagnosticContext, ...]:
    raw_index = {item.raw_candidate_id: item for item in raw_candidates}
    decision_index = {(item.run_id, item.symbol): item for item in decisions}
    raw_outcome_index = {item.raw_candidate_id: item for item in raw_outcomes}
    timing_index = _entry_timing_index(decisions, outcomes)
    breadth_index = _breadth_index()
    inventory = _source_inventory(
        database_path=database_path,
        raw_data_dir=raw_data_dir,
        extracted_data_dir=extracted_data_dir,
    )
    contexts: list[BreakoutCandidateDiagnosticContext] = []
    for record in sorted(records, key=_record_sort_key):
        raw = raw_index.get(record.candidate_id)
        if raw is None:
            raise ValueError(
                f"raw candidate missing for reconstruction record {record.candidate_id}"
            )
        decision = decision_index.get((record.replay_run_id, record.historical_symbol))
        outcome = raw_outcome_index.get(record.candidate_id)
        primary_window = _primary_raw_window(outcome)
        timing_state = (
            timing_index.get(decision.candidate_id) if decision is not None else None
        )
        symbol_range = inventory.symbol_ranges.get(record.historical_symbol)
        source = _source_probe(record, raw, inventory, symbol_range)
        contexts.append(
            BreakoutCandidateDiagnosticContext(
                candidate_id=record.candidate_id,
                replay_run_id=record.replay_run_id,
                symbol=record.historical_symbol,
                candidate_date=record.candidate_observation_date,
                source=source,
                sector=raw.sector or (decision.sector if decision else None),
                liquidity_proxy=raw.liquidity_score,
                listing_age_days=None,
                setup_type=decision.setup_type
                if decision
                else _setup_from_indicators(raw),
                recommendation_verdict=(
                    decision.final_verdict if decision else raw.emitted_verdict
                ),
                recommendation_score=(
                    decision.strategy_score
                    if decision
                    else raw.final_strategy_score or raw.preliminary_score
                ),
                price_component=_decision_score(decision, "price"),
                volume_component=(
                    raw.volume_score or _decision_score(decision, "volume")
                ),
                trend_component=raw.trend_score,
                entry_timing_state=timing_state,
                market_regime=(
                    decision.market_regime if decision else raw.market_regime
                ),
                regime_confidence=raw.regime_score,
                breadth_state=breadth_index.get(record.candidate_observation_date),
                candidate_rank=raw.raw_rank,
                replay_version=(
                    decision.classifier_version
                    if decision and decision.classifier_version
                    else "LEGACY_UNVERSIONED_REPLAY"
                ),
                known_symbol_change_status="UNAVAILABLE_NO_EFFECTIVE_DATED_ALIAS",
                inactive_or_delisted_status=_survival_status(
                    symbol_range, inventory.global_end
                ),
                completed_outcome=(
                    primary_window is not None
                    and primary_window.forward_return_pct_from_close is not None
                    and primary_window.outcome_label.value != "DATA_MISSING"
                ),
                forward_return=(
                    primary_window.forward_return_pct_from_close
                    if primary_window is not None
                    else None
                ),
                stop_hit=(
                    primary_window.risk_stop_touched
                    if primary_window is not None
                    else None
                ),
                target_1_hit=(
                    primary_window.target_1_touched
                    if primary_window is not None
                    else None
                ),
            )
        )
    return tuple(contexts)


def _source_probe(
    record: BreakoutReferenceReconstructionRecord,
    raw: RawCandidateRecord,
    inventory: _SourceInventory,
    symbol_range: tuple[date, date, int] | None,
) -> BreakoutSourceProbe:
    timestamps = record.provenance.source_bar_timestamps
    available_start = timestamps[0].date() if timestamps else None
    available_end = timestamps[-1].date() if timestamps else None
    requested_end = (
        record.last_bar_timestamp_allowed.date()
        if record.last_bar_timestamp_allowed is not None
        else None
    )
    status = record.readiness_status
    valid_rejection = status in {
        BreakoutReferenceReadinessStatus.MISSING_BARS,
        BreakoutReferenceReadinessStatus.INVALID_PRICE_SERIES,
        BreakoutReferenceReadinessStatus.TIMEZONE_MISMATCH,
        BreakoutReferenceReadinessStatus.CORPORATE_ACTION_AMBIGUITY,
        BreakoutReferenceReadinessStatus.ADJUSTMENT_MODE_MISMATCH,
        BreakoutReferenceReadinessStatus.PROVENANCE_INCOMPLETE,
    }
    return BreakoutSourceProbe(
        source_provider=record.provenance.source_provider,
        source_dataset=record.provenance.source_dataset,
        source_query_attempted=(
            f"historical_symbol={record.historical_symbol};"
            f"end_date={requested_end or 'unavailable'};"
            f"limit={record.historical_bars_requested}"
        ),
        requested_start_date=None,
        requested_end_date=requested_end,
        available_start_date=available_start,
        available_end_date=available_end,
        global_source_start_date=inventory.global_start,
        global_source_end_date=inventory.global_end,
        symbol_first_source_date=symbol_range[0] if symbol_range else None,
        symbol_last_source_date=symbol_range[1] if symbol_range else None,
        raw_archive_start_date=min(inventory.raw_archive_dates, default=None),
        raw_archive_end_date=max(inventory.raw_archive_dates, default=None),
        extracted_cache_start_date=min(inventory.extracted_cache_dates, default=None),
        extracted_cache_end_date=max(inventory.extracted_cache_dates, default=None),
        raw_archive_count=len(inventory.raw_archive_dates),
        extracted_cache_count=len(inventory.extracted_cache_dates),
        candidate_date_bar_present=raw.close_price is not None,
        historical_symbol_query_used=True,
        current_symbol_only_query=False,
        fallback_source_has_data=False,
        source_cache_has_additional_data=False,
        off_by_one_boundary=False,
        valid_data_filtered_incorrectly=False,
        valid_data_rejected_correctly=valid_rejection,
        source_retrieval_error=None,
        identity_resolution_status=(
            "RESOLVED_POINT_IN_TIME" if record.instrument_identifier else "UNRESOLVED"
        ),
        listing_date=None,
        listing_date_evidence="UNAVAILABLE_OFFICIAL_DATE",
        delisting_date=None,
        delisting_date_evidence="UNAVAILABLE_OFFICIAL_DATE",
        symbol_change_status="UNAVAILABLE_NO_EFFECTIVE_DATED_ALIAS",
        corporate_action_status=(
            "AMBIGUOUS_METADATA_NOT_JOINED"
            if status is BreakoutReferenceReadinessStatus.CORPORATE_ACTION_AMBIGUITY
            else "NO_AMBIGUITY_DETECTED"
        ),
        normalization_status=(
            "REJECTED_CORRECTLY" if valid_rejection else "VALIDATED_OR_NOT_REACHED"
        ),
        cutoff_status=record.cutoff_semantics.value,
        provenance_status=("COMPLETE" if record.provenance.complete else "INCOMPLETE"),
        survival_status=_survival_status(symbol_range, inventory.global_end),
    )


def _source_inventory(
    *,
    database_path: Path | str | None,
    raw_data_dir: Path | str | None,
    extracted_data_dir: Path | str | None,
) -> _SourceInventory:
    path = Path(database_path) if database_path is not None else settings.database_path
    market_inventory = MarketTruthPriceRepository(database_path=path).inventory()
    raw_dir = Path(raw_data_dir) if raw_data_dir is not None else settings.raw_data_dir
    extracted_dir = (
        Path(extracted_data_dir)
        if extracted_data_dir is not None
        else settings.extracted_data_dir
    )
    return _SourceInventory(
        global_start=market_inventory.global_start,
        global_end=market_inventory.global_end,
        global_sessions=market_inventory.global_sessions,
        symbol_ranges=market_inventory.symbol_ranges,
        raw_archive_dates=frozenset(
            item
            for path_item in raw_dir.glob("*")
            if (item := _archive_date(path_item.name)) is not None
        ),
        extracted_cache_dates=frozenset(
            item
            for path_item in extracted_dir.glob("*")
            if (item := _archive_date(path_item.name)) is not None
        ),
    )


def _archive_date(name: str) -> date | None:
    raw_match = _RAW_ARCHIVE.match(name)
    if raw_match:
        return date.fromisoformat(raw_match.group("date"))
    udiff_match = _UDIFF_ARCHIVE.match(name)
    if udiff_match:
        return datetime.strptime(udiff_match.group("date"), "%Y%m%d").date()
    legacy_match = _LEGACY_ARCHIVE.match(name)
    if legacy_match:
        return datetime.strptime(
            "".join(
                (
                    legacy_match.group("day"),
                    legacy_match.group("month"),
                    legacy_match.group("year"),
                )
            ),
            "%d%b%Y",
        ).date()
    return None


def _entry_timing_index(
    records: tuple[CandidateDecisionRecord, ...],
    outcomes: tuple[CandidateForwardOutcome, ...],
) -> dict[str, str]:
    if not records:
        return {}
    report = build_entry_timing_replay_report(records=records, outcomes=outcomes)
    return {row.candidate_id: row.assessment.entry_state.value for row in report.rows}


def _breadth_index() -> dict[date, str]:
    repository = PointInTimeAnalyticalRepository()
    status = repository.status()
    if not status.exists or status.build_id is None:
        return {}
    return {
        row.market_date: _breadth_state(row.breadth_ratio)
        for row in repository.breadth_snapshots(build_id=status.build_id)
    }


def _breadth_state(value: Decimal | None) -> str:
    if value is None:
        return "UNAVAILABLE"
    if value >= Decimal("0.60"):
        return "BROAD_PARTICIPATION"
    if value >= Decimal("0.40"):
        return "MIXED_PARTICIPATION"
    return "WEAK_PARTICIPATION"


def _primary_raw_window(
    outcome: RawCandidateForwardOutcome | None,
) -> RawForwardWindowOutcome | None:
    if outcome is None:
        return None
    by_window = {item.window: item for item in outcome.windows}
    return by_window.get("20d")


def _decision_score(
    decision: CandidateDecisionRecord | None,
    key: str,
) -> Decimal | None:
    if decision is None:
        return None
    value = decision.indicator_scores.get(key)
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _setup_from_indicators(raw: RawCandidateRecord) -> str | None:
    for indicator in raw.indicators_active:
        if indicator.startswith("setup-"):
            return indicator.removeprefix("setup-").replace("-", " ").upper()
    return None


def _survival_status(
    symbol_range: tuple[date, date, int] | None,
    global_end: date | None,
) -> str:
    if symbol_range is None or global_end is None:
        return "UNAVAILABLE"
    if symbol_range[1] >= global_end - timedelta(days=45):
        return "ACTIVE_TO_SOURCE_END"
    return "SOURCE_CONTINUITY_ENDED_BEFORE_SOURCE_END"


def _record_sort_key(
    record: BreakoutReferenceReconstructionRecord,
) -> tuple[date, str, str]:
    return (
        record.candidate_observation_date,
        record.historical_symbol,
        record.candidate_id,
    )


__all__ = [
    "build_breakout_gap_contexts",
    "build_project_breakout_source_gap_audit",
]
