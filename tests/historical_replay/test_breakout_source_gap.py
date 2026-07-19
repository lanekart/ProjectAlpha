from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

import pytest
from typer.testing import CliRunner

import alpha.cli as cli_module
from alpha.cli import app
from alpha.historical_replay.breakout_reference import (
    BreakoutReconstructionCandidate,
    BreakoutReferenceConfiguration,
    BreakoutReferenceReadinessStatus,
    HistoricalSecurityIdentity,
    PointInTimeBreakoutReferenceEngine,
    source_bar_from_values,
)
from alpha.historical_replay.breakout_source_gap import (
    PRODUCTION_INFLUENCE,
    BreakoutCandidateDiagnosticContext,
    BreakoutGapCause,
    BreakoutGapRecoveryClass,
    BreakoutReadySampleBiasConclusion,
    BreakoutSourceGapAuditEngine,
    BreakoutSourcePathDisposition,
    BreakoutSourceProbe,
    export_breakout_gap_csv,
    export_breakout_gap_json,
    filter_breakout_gap_records,
    group_breakout_gap_records,
)


def _sessions(start: date, count: int) -> tuple[date, ...]:
    rows: list[date] = []
    current = start
    while len(rows) < count:
        if current.weekday() < 5:
            rows.append(current)
        current += timedelta(days=1)
    return tuple(rows)


def _base_record():  # type: ignore[no-untyped-def]
    sessions = _sessions(date(2024, 1, 2), 30)
    bars = tuple(
        source_bar_from_values(
            observed_on=day,
            open_price=100 + index,
            high_price=102 + index,
            low_price=99 + index,
            close_price=101 + index,
            volume=1000 + index,
        )
        for index, day in enumerate(sessions[:-1])
    )
    return PointInTimeBreakoutReferenceEngine(
        BreakoutReferenceConfiguration(minimum_lookback=10, reference_lookback=20),
        clock=datetime(2026, 1, 1, tzinfo=UTC),
    ).reconstruct(
        candidate=BreakoutReconstructionCandidate(
            replay_run_id="historical_replay|2024-02-12",
            candidate_id="gap-base",
            historical_symbol="GAP",
            observation_date=sessions[-1],
        ),
        bars=bars,
        identity=HistoricalSecurityIdentity(
            instrument_identifier="NSE-GAP",
            historical_symbol="GAP",
            exchange="NSE",
            security_master_version="pit-v1",
            evidence_reference="store#NSE-GAP",
            resolved=True,
        ),
        exchange_sessions=sessions,
    )


def _record(
    status: object,
    *,
    candidate_id: str = "gap-base",
    symbol: str = "GAP",
    candidate_date: date | None = None,
    usable_bars: int | None = None,
    exclusions: tuple[str, ...] = (),
):  # type: ignore[no-untyped-def]
    base = _base_record()
    observed_on = candidate_date or base.candidate_observation_date
    provenance = replace(base.provenance, exclusion_reasons=exclusions)
    return replace(
        base,
        candidate_id=candidate_id,
        replay_run_id=f"historical_replay|{observed_on.isoformat()}",
        historical_symbol=symbol,
        candidate_observation_date=observed_on,
        readiness_status=cast(Any, status),
        usable_bars=base.usable_bars if usable_bars is None else usable_bars,
        historical_bars_available=(
            base.historical_bars_available if usable_bars is None else usable_bars
        ),
        provenance=provenance,
    )


def _probe(**overrides: object) -> BreakoutSourceProbe:
    defaults: dict[str, object] = {
        "source_query_attempted": "historical_symbol=GAP;end_date=2024-02-09",
        "available_start_date": date(2024, 1, 2),
        "available_end_date": date(2024, 2, 9),
        "global_source_start_date": date(2016, 7, 8),
        "global_source_end_date": date(2026, 7, 10),
        "symbol_first_source_date": date(2024, 1, 2),
        "symbol_last_source_date": date(2024, 2, 12),
        "candidate_date_bar_present": True,
        "identity_resolution_status": "RESOLVED_POINT_IN_TIME",
        "normalization_status": "VALIDATED",
        "cutoff_status": "PREVIOUS_COMPLETED_SESSION",
        "provenance_status": "COMPLETE",
    }
    defaults.update(overrides)
    return BreakoutSourceProbe(**defaults)  # type: ignore[arg-type]


def _context(
    *,
    candidate_id: str = "gap-base",
    symbol: str = "GAP",
    candidate_date: date | None = None,
    source: BreakoutSourceProbe | None = None,
    **overrides: object,
) -> BreakoutCandidateDiagnosticContext:
    observed_on = candidate_date or _base_record().candidate_observation_date
    defaults: dict[str, object] = {
        "candidate_id": candidate_id,
        "replay_run_id": f"historical_replay|{observed_on.isoformat()}",
        "symbol": symbol,
        "candidate_date": observed_on,
        "source": source or _probe(),
        "sector": "Industrials",
        "liquidity_proxy": Decimal("0.50"),
        "listing_age_days": 1000,
        "setup_type": "MOMENTUM_CONTINUATION",
        "recommendation_verdict": "BUY",
        "recommendation_score": Decimal("70"),
        "price_component": Decimal("0.70"),
        "volume_component": Decimal("0.60"),
        "trend_component": Decimal("0.75"),
        "entry_timing_state": "READY",
        "market_regime": "POSITIVE",
        "regime_confidence": Decimal("0.70"),
        "breadth_state": "BROAD_PARTICIPATION",
        "candidate_rank": 1,
        "replay_version": "replay-v1",
        "known_symbol_change_status": "NO_KNOWN_CHANGE",
        "inactive_or_delisted_status": "ACTIVE_AT_SOURCE_END",
    }
    defaults.update(overrides)
    return BreakoutCandidateDiagnosticContext(**defaults)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("status", "probe", "context_overrides", "exclusions", "expected", "secondary"),
    (
        (
            BreakoutReferenceReadinessStatus.SOURCE_UNAVAILABLE,
            _probe(global_source_start_date=None, global_source_end_date=None),
            {},
            (),
            BreakoutGapCause.NO_ARCHIVE_RECORD,
            (),
        ),
        (
            BreakoutReferenceReadinessStatus.SOURCE_UNAVAILABLE,
            _probe(candidate_date_bar_present=False),
            {},
            (),
            BreakoutGapCause.ARCHIVE_RECORD_INCOMPLETE,
            (BreakoutGapCause.CANDIDATE_DATE_BAR_MISSING,),
        ),
        (
            BreakoutReferenceReadinessStatus.INSUFFICIENT_LOOKBACK,
            _probe(
                available_start_date=date(2016, 7, 8),
                global_source_start_date=date(2016, 7, 8),
            ),
            {},
            (),
            BreakoutGapCause.INSUFFICIENT_PRE_CANDIDATE_LOOKBACK,
            (
                BreakoutGapCause.NO_ARCHIVE_RECORD,
                BreakoutGapCause.PARTIAL_LOOKBACK_AVAILABLE,
            ),
        ),
        (
            BreakoutReferenceReadinessStatus.INSUFFICIENT_LOOKBACK,
            _probe(),
            {},
            (),
            BreakoutGapCause.PARTIAL_LOOKBACK_AVAILABLE,
            (),
        ),
        (
            BreakoutReferenceReadinessStatus.MISSING_BARS,
            _probe(),
            {},
            (),
            BreakoutGapCause.MULTI_SESSION_GAP,
            (BreakoutGapCause.ARCHIVE_RECORD_INCOMPLETE,),
        ),
        (
            BreakoutReferenceReadinessStatus.INVALID_PRICE_SERIES,
            _probe(),
            {},
            (),
            BreakoutGapCause.INVALID_OHLCV_SERIES,
            (),
        ),
        (
            BreakoutReferenceReadinessStatus.INVALID_PRICE_SERIES,
            _probe(),
            {},
            ("DUPLICATE_BAR_TIMESTAMPS",),
            BreakoutGapCause.DUPLICATE_OR_CONFLICTING_BARS,
            (),
        ),
        (
            BreakoutReferenceReadinessStatus.TIMEZONE_MISMATCH,
            _probe(),
            {},
            (),
            BreakoutGapCause.TIMEZONE_OR_SESSION_MISMATCH,
            (),
        ),
        (
            BreakoutReferenceReadinessStatus.SYMBOL_IDENTITY_UNRESOLVED,
            _probe(),
            {},
            (),
            BreakoutGapCause.SYMBOL_IDENTITY_UNRESOLVED,
            (),
        ),
        (
            BreakoutReferenceReadinessStatus.SYMBOL_IDENTITY_UNRESOLVED,
            _probe(),
            {"known_symbol_change_status": "KNOWN_CHANGE_UNRESOLVED"},
            (),
            BreakoutGapCause.SYMBOL_CHANGE_UNRESOLVED,
            (),
        ),
        (
            BreakoutReferenceReadinessStatus.LISTING_DATE_VIOLATION,
            _probe(),
            {},
            (),
            BreakoutGapCause.LISTING_DATE_CONFLICT,
            (),
        ),
        (
            BreakoutReferenceReadinessStatus.DELISTING_DATE_VIOLATION,
            _probe(),
            {},
            (),
            BreakoutGapCause.DELISTING_DATE_CONFLICT,
            (),
        ),
        (
            BreakoutReferenceReadinessStatus.CORPORATE_ACTION_AMBIGUITY,
            _probe(),
            {},
            (),
            BreakoutGapCause.CORPORATE_ACTION_AMBIGUITY,
            (),
        ),
        (
            BreakoutReferenceReadinessStatus.ADJUSTMENT_MODE_MISMATCH,
            _probe(),
            {},
            (),
            BreakoutGapCause.ADJUSTMENT_MODE_CONFLICT,
            (),
        ),
        (
            BreakoutReferenceReadinessStatus.AMBIGUOUS_DECISION_CUTOFF,
            _probe(),
            {},
            (),
            BreakoutGapCause.AMBIGUOUS_DECISION_CUTOFF,
            (),
        ),
        (
            BreakoutReferenceReadinessStatus.UNSUPPORTED_REFERENCE_METHOD,
            _probe(),
            {},
            (),
            BreakoutGapCause.REFERENCE_METHOD_UNSUPPORTED,
            (),
        ),
        (
            BreakoutReferenceReadinessStatus.PROVENANCE_INCOMPLETE,
            _probe(),
            {},
            (),
            BreakoutGapCause.PROVENANCE_INCOMPLETE,
            (),
        ),
        (
            BreakoutReferenceReadinessStatus.RECONSTRUCTION_ERROR,
            _probe(),
            {},
            (),
            BreakoutGapCause.IMPLEMENTATION_PATH_GAP,
            (),
        ),
    ),
)
def test_gap_attribution_is_specific_and_deterministic(
    status: BreakoutReferenceReadinessStatus,
    probe: BreakoutSourceProbe,
    context_overrides: dict[str, object],
    exclusions: tuple[str, ...],
    expected: BreakoutGapCause,
    secondary: tuple[BreakoutGapCause, ...],
) -> None:
    record = _record(status, usable_bars=5, exclusions=exclusions)
    context = _context(source=probe, **context_overrides)

    first = BreakoutSourceGapAuditEngine().attribute(record, context)
    second = BreakoutSourceGapAuditEngine().attribute(record, context)

    assert first == second
    assert first.primary_gap_cause is expected
    assert first.secondary_gap_causes == secondary


def test_legitimate_short_history_requires_local_first_bar_evidence() -> None:
    candidate_date = _base_record().candidate_observation_date
    source = _probe(
        candidate_date_bar_present=True,
        symbol_first_source_date=candidate_date,
        listing_date=None,
        listing_date_evidence="UNAVAILABLE_OFFICIAL_DATE",
    )
    attributed = BreakoutSourceGapAuditEngine().attribute(
        _record(BreakoutReferenceReadinessStatus.SOURCE_UNAVAILABLE, usable_bars=0),
        _context(source=source),
    )

    assert attributed.primary_gap_cause is (
        BreakoutGapCause.LEGITIMATELY_INSUFFICIENT_TRADING_HISTORY
    )
    assert attributed.recovery_class is BreakoutGapRecoveryClass.RECOVERY_UNCERTAIN


class _FutureStatus(StrEnum):
    FUTURE_STATUS = "FUTURE_STATUS"


def test_unknown_cause_is_retained_for_future_unmapped_status() -> None:
    attributed = BreakoutSourceGapAuditEngine().attribute(
        _record(_FutureStatus.FUTURE_STATUS),
        _context(),
    )

    assert attributed.primary_gap_cause is BreakoutGapCause.UNKNOWN_GAP_CAUSE


def test_primary_cause_precedence_keeps_retrieval_failure_first() -> None:
    attributed = BreakoutSourceGapAuditEngine().attribute(
        _record(BreakoutReferenceReadinessStatus.AMBIGUOUS_DECISION_CUTOFF),
        _context(
            source=_probe(
                source_retrieval_error="provider timeout",
                fallback_source_has_data=True,
                off_by_one_boundary=True,
            )
        ),
    )

    assert attributed.primary_gap_cause is BreakoutGapCause.SOURCE_RETRIEVAL_ERROR
    assert attributed.recovery_class is BreakoutGapRecoveryClass.RECOVERY_UNCERTAIN


@pytest.mark.parametrize(
    ("status", "probe", "context_overrides", "expected"),
    (
        (
            BreakoutReferenceReadinessStatus.RECONSTRUCTION_ERROR,
            _probe(fallback_source_has_data=True),
            {},
            BreakoutGapRecoveryClass.RECOVERABLE_EXISTING_SOURCE,
        ),
        (
            BreakoutReferenceReadinessStatus.SYMBOL_IDENTITY_UNRESOLVED,
            _probe(fallback_source_has_data=True),
            {"known_symbol_change_status": "KNOWN_CHANGE_UNRESOLVED"},
            BreakoutGapRecoveryClass.RECOVERABLE_EXISTING_SOURCE_WITH_IDENTITY_REPAIR,
        ),
        (
            BreakoutReferenceReadinessStatus.INVALID_PRICE_SERIES,
            _probe(source_cache_has_additional_data=True),
            {},
            BreakoutGapRecoveryClass.RECOVERABLE_EXISTING_SOURCE_WITH_NORMALIZATION_REPAIR,
        ),
        (
            BreakoutReferenceReadinessStatus.AMBIGUOUS_DECISION_CUTOFF,
            _probe(),
            {},
            BreakoutGapRecoveryClass.RECOVERABLE_EXISTING_SOURCE_WITH_CUTOFF_RESOLUTION,
        ),
        (
            BreakoutReferenceReadinessStatus.SOURCE_UNAVAILABLE,
            _probe(global_source_start_date=None, global_source_end_date=None),
            {},
            BreakoutGapRecoveryClass.REQUIRES_NEW_EXTERNAL_SOURCE,
        ),
        (
            BreakoutReferenceReadinessStatus.MISSING_BARS,
            _probe(),
            {},
            BreakoutGapRecoveryClass.RECOVERY_UNCERTAIN,
        ),
    ),
)
def test_recovery_classes_follow_source_evidence(
    status: BreakoutReferenceReadinessStatus,
    probe: BreakoutSourceProbe,
    context_overrides: dict[str, object],
    expected: BreakoutGapRecoveryClass,
) -> None:
    attributed = BreakoutSourceGapAuditEngine().attribute(
        _record(status),
        _context(source=probe, **context_overrides),
    )

    assert attributed.recovery_class is expected


def test_authoritative_listing_date_can_prove_legitimate_unrecoverability() -> None:
    candidate_date = _base_record().candidate_observation_date
    source = _probe(
        candidate_date_bar_present=True,
        symbol_first_source_date=candidate_date,
        listing_date=candidate_date,
        listing_date_evidence="OFFICIAL_EFFECTIVE_DATE",
    )
    attributed = BreakoutSourceGapAuditEngine().attribute(
        _record(BreakoutReferenceReadinessStatus.SOURCE_UNAVAILABLE, usable_bars=0),
        _context(source=source),
    )

    assert attributed.recovery_class is (
        BreakoutGapRecoveryClass.LEGITIMATELY_UNRECOVERABLE
    )


@pytest.mark.parametrize(
    ("probe", "status", "cause", "disposition"),
    (
        (
            _probe(historical_symbol_query_used=True),
            BreakoutReferenceReadinessStatus.READY,
            None,
            BreakoutSourcePathDisposition.READY,
        ),
        (
            _probe(current_symbol_only_query=True),
            BreakoutReferenceReadinessStatus.SOURCE_UNAVAILABLE,
            BreakoutGapCause.IMPLEMENTATION_PATH_GAP,
            BreakoutSourcePathDisposition.AVAILABLE_SOURCE_NOT_REACHED,
        ),
        (
            _probe(fallback_source_has_data=True),
            BreakoutReferenceReadinessStatus.SOURCE_UNAVAILABLE,
            BreakoutGapCause.IMPLEMENTATION_PATH_GAP,
            BreakoutSourcePathDisposition.AVAILABLE_SOURCE_NOT_REACHED,
        ),
        (
            _probe(source_cache_has_additional_data=True),
            BreakoutReferenceReadinessStatus.SOURCE_UNAVAILABLE,
            BreakoutGapCause.IMPLEMENTATION_PATH_GAP,
            BreakoutSourcePathDisposition.AVAILABLE_SOURCE_NOT_REACHED,
        ),
        (
            _probe(off_by_one_boundary=True),
            BreakoutReferenceReadinessStatus.SOURCE_UNAVAILABLE,
            BreakoutGapCause.IMPLEMENTATION_PATH_GAP,
            BreakoutSourcePathDisposition.AVAILABLE_SOURCE_NOT_REACHED,
        ),
        (
            _probe(valid_data_filtered_incorrectly=True),
            BreakoutReferenceReadinessStatus.SOURCE_UNAVAILABLE,
            BreakoutGapCause.IMPLEMENTATION_PATH_GAP,
            BreakoutSourcePathDisposition.AVAILABLE_SOURCE_REJECTED_INCORRECTLY,
        ),
        (
            _probe(valid_data_rejected_correctly=True),
            BreakoutReferenceReadinessStatus.MISSING_BARS,
            BreakoutGapCause.MULTI_SESSION_GAP,
            BreakoutSourcePathDisposition.AVAILABLE_SOURCE_REJECTED_CORRECTLY,
        ),
        (
            _probe(global_source_start_date=None, global_source_end_date=None),
            BreakoutReferenceReadinessStatus.SOURCE_UNAVAILABLE,
            BreakoutGapCause.NO_ARCHIVE_RECORD,
            BreakoutSourcePathDisposition.TRUE_SOURCE_ABSENCE,
        ),
    ),
)
def test_source_path_audit_distinguishes_absence_and_pipeline_failures(
    probe: BreakoutSourceProbe,
    status: BreakoutReferenceReadinessStatus,
    cause: BreakoutGapCause | None,
    disposition: BreakoutSourcePathDisposition,
) -> None:
    attributed = BreakoutSourceGapAuditEngine().attribute(
        _record(status),
        _context(source=probe),
    )

    assert attributed.primary_gap_cause is cause
    assert attributed.source_path_disposition is disposition


def _population(
    *,
    ready_overrides: dict[str, object] | None = None,
    unavailable_overrides: dict[str, object] | None = None,
    ready_year: int = 2024,
    unavailable_year: int = 2024,
    size: int = 12,
    same_symbol: bool = False,
) -> tuple[tuple[object, ...], tuple[BreakoutCandidateDiagnosticContext, ...]]:
    records: list[object] = []
    contexts: list[BreakoutCandidateDiagnosticContext] = []
    for ready in (True, False):
        year = ready_year if ready else unavailable_year
        overrides = ready_overrides if ready else unavailable_overrides
        for index in range(size):
            candidate_id = f"{'ready' if ready else 'gap'}-{index}"
            symbol = "CLUSTER" if same_symbol else f"SYM{index % 4}"
            observed_on = date(year, 6, 1) + timedelta(days=index)
            status = (
                BreakoutReferenceReadinessStatus.READY
                if ready
                else BreakoutReferenceReadinessStatus.MISSING_BARS
            )
            records.append(
                _record(
                    status,
                    candidate_id=candidate_id,
                    symbol=symbol,
                    candidate_date=observed_on,
                )
            )
            contexts.append(
                _context(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    candidate_date=observed_on,
                    **(overrides or {}),
                )
            )
    return tuple(records), tuple(contexts)


def _bias_report(**kwargs: object):  # type: ignore[no-untyped-def]
    records, contexts = _population(**kwargs)
    return (
        BreakoutSourceGapAuditEngine()
        .analyze(
            records=records,  # type: ignore[arg-type]
            contexts=contexts,
            minimum_sample=5,
        )
        .selection_bias
    )


def test_representative_population_remains_representative() -> None:
    report = _bias_report()

    assert report.bias_conclusion is (
        BreakoutReadySampleBiasConclusion.READY_SAMPLE_APPEARS_REPRESENTATIVE
    )


@pytest.mark.parametrize(
    "kwargs",
    (
        {"ready_year": 2024, "unavailable_year": 2017},
        {
            "ready_overrides": {"market_regime": "POSITIVE"},
            "unavailable_overrides": {"market_regime": "NEGATIVE"},
        },
        {
            "ready_overrides": {"setup_type": "BREAKOUT"},
            "unavailable_overrides": {"setup_type": "TREND_FAILURE"},
        },
        {
            "ready_overrides": {"recommendation_score": Decimal("85")},
            "unavailable_overrides": {"recommendation_score": Decimal("25")},
        },
    ),
)
def test_structured_missingness_is_material(kwargs: dict[str, object]) -> None:
    report = _bias_report(**kwargs)

    assert report.bias_conclusion is (
        BreakoutReadySampleBiasConclusion.READY_SAMPLE_HAS_MATERIAL_OBSERVED_BIAS
    )


def test_symbol_survival_concentration_is_severe() -> None:
    report = _bias_report(
        ready_overrides={"inactive_or_delisted_status": "ACTIVE"},
        unavailable_overrides={"inactive_or_delisted_status": "DELISTED"},
    )

    assert report.bias_conclusion is (
        BreakoutReadySampleBiasConclusion.READY_SAMPLE_HAS_SEVERE_SURVIVORSHIP_RISK
    )


def test_outcome_only_divergence_does_not_drive_pre_outcome_bias() -> None:
    report = _bias_report(
        ready_overrides={
            "completed_outcome": True,
            "forward_return": Decimal("10"),
            "target_1_hit": True,
            "stop_hit": False,
        },
        unavailable_overrides={
            "completed_outcome": True,
            "forward_return": Decimal("-10"),
            "target_1_hit": False,
            "stop_hit": True,
        },
    )

    assert report.bias_conclusion is (
        BreakoutReadySampleBiasConclusion.READY_SAMPLE_APPEARS_REPRESENTATIVE
    )
    assert all(
        item.dimension != "completed_outcome_availability"
        for item in report.distribution_differences
    )
    assert any(
        item.metric == "completed_outcome_availability"
        for item in report.outcome_differences
    )
    forward = next(
        item
        for item in report.outcome_differences
        if item.metric == "average_20d_forward_return"
    )
    assert forward.absolute_difference == Decimal("20.0000")


def test_pre_outcome_and_outcome_divergence_remain_separate() -> None:
    report = _bias_report(
        ready_overrides={
            "recommendation_score": Decimal("85"),
            "completed_outcome": True,
            "forward_return": Decimal("10"),
        },
        unavailable_overrides={
            "recommendation_score": Decimal("25"),
            "completed_outcome": True,
            "forward_return": Decimal("-10"),
        },
    )

    assert report.bias_conclusion is (
        BreakoutReadySampleBiasConclusion.READY_SAMPLE_HAS_MATERIAL_OBSERVED_BIAS
    )
    assert any(item.absolute_difference for item in report.outcome_differences)


def test_insufficient_samples_are_not_compared() -> None:
    records, contexts = _population(size=1)
    report = (
        BreakoutSourceGapAuditEngine()
        .analyze(
            records=records,  # type: ignore[arg-type]
            contexts=contexts,
            minimum_sample=5,
        )
        .selection_bias
    )

    assert report.bias_conclusion is (
        BreakoutReadySampleBiasConclusion.READY_SAMPLE_BIAS_CANNOT_BE_ASSESSED
    )
    assert all(not item.sufficient_sample for item in report.numeric_differences)


def test_repeated_symbols_report_concentration_and_are_deterministic() -> None:
    records, contexts = _population(same_symbol=True)
    engine = BreakoutSourceGapAuditEngine()

    first = engine.analyze(
        records=records,  # type: ignore[arg-type]
        contexts=contexts,
        minimum_sample=5,
    )
    second = engine.analyze(
        records=tuple(reversed(records)),  # type: ignore[arg-type]
        contexts=tuple(reversed(contexts)),
        minimum_sample=5,
    )

    assert first == second
    assert first.selection_bias.ready_symbol_hhi == Decimal("1.0000")
    assert "clustered by symbol" in first.selection_bias.repeated_symbol_warning


def test_filters_grouping_and_exports_are_deterministic(tmp_path: Path) -> None:
    records, contexts = _population(size=6)
    report = BreakoutSourceGapAuditEngine().analyze(
        records=records,  # type: ignore[arg-type]
        contexts=contexts,
        minimum_sample=2,
    )
    filtered = filter_breakout_gap_records(
        report.coverage.records,
        cause=BreakoutGapCause.MULTI_SESSION_GAP,
        symbol="sym0",
        from_date=date(2024, 6, 1),
        to_date=date(2024, 6, 30),
        year=2024,
        limit=2,
    )
    grouped = group_breakout_gap_records(report.coverage.records, "setup-type")
    first_json = tmp_path / "first.json"
    second_json = tmp_path / "second.json"
    first_csv = tmp_path / "first.csv"
    second_csv = tmp_path / "second.csv"

    export_breakout_gap_json(report, first_json)
    export_breakout_gap_json(report, second_json)
    export_breakout_gap_csv(report.coverage.records, first_csv)
    export_breakout_gap_csv(report.coverage.records, second_csv)

    assert len(filtered) == 2
    assert grouped[0].key == "MOMENTUM_CONTINUATION"
    assert first_json.read_bytes() == second_json.read_bytes()
    assert first_csv.read_bytes() == second_csv.read_bytes()
    assert "earliest_usable_bar" in first_csv.read_text(encoding="utf-8")
    assert not PRODUCTION_INFLUENCE


@pytest.mark.parametrize(
    "group_by",
    (
        "year",
        "symbol",
        "sector",
        "provider",
        "primary-cause",
        "secondary-cause",
        "recovery-class",
        "market-regime",
        "setup-type",
        "entry-timing-state",
        "replay-version",
    ),
)
def test_all_supported_groupings_produce_rows(group_by: str) -> None:
    records, contexts = _population(size=2)
    report = BreakoutSourceGapAuditEngine().analyze(
        records=records,  # type: ignore[arg-type]
        contexts=contexts,
        minimum_sample=2,
    )

    assert group_breakout_gap_records(report.coverage.records, group_by)


def test_invalid_grouping_and_date_range_fail_clearly() -> None:
    records, contexts = _population(size=2)
    report = BreakoutSourceGapAuditEngine().analyze(
        records=records,  # type: ignore[arg-type]
        contexts=contexts,
        minimum_sample=2,
    )

    with pytest.raises(ValueError, match="unsupported grouping"):
        group_breakout_gap_records(report.coverage.records, "future-outcome")
    with pytest.raises(ValueError, match="to_date must be on or after"):
        filter_breakout_gap_records(
            report.coverage.records,
            from_date=date(2024, 7, 1),
            to_date=date(2024, 6, 1),
        )


def _cli_report():  # type: ignore[no-untyped-def]
    records, contexts = _population(size=6)
    return BreakoutSourceGapAuditEngine().analyze(
        records=records,  # type: ignore[arg-type]
        contexts=contexts,
        minimum_sample=2,
    )


def test_all_source_gap_cli_commands_render(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _cli_report()
    monkeypatch.setattr(
        cli_module,
        "build_project_breakout_source_gap_audit",
        lambda **_: report,
    )
    runner = CliRunner()
    expected = {
        "breakout-source-gap-audit": "Breakout Source-Gap Attribution Audit",
        "breakout-selection-bias": "Breakout Ready-vs-Unavailable",
        "breakout-source-coverage": "Breakout Source Coverage Matrix",
        "breakout-recovery-readiness": "Breakout Recovery Readiness Audit",
        "breakout-gap-sample": "Breakout Gap Attribution Sample",
    }

    for command, heading in expected.items():
        result = runner.invoke(app, ["replay", command])
        assert result.exit_code == 0, result.output
        assert heading in result.output
        assert "PRODUCTION_INFLUENCE=false" in result.output


def test_cli_groupings_and_invalid_grouping(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _cli_report()
    monkeypatch.setattr(
        cli_module,
        "build_project_breakout_source_gap_audit",
        lambda **_: report,
    )
    runner = CliRunner()

    market = runner.invoke(
        app,
        ["replay", "breakout-selection-bias", "--group-by", "market-regime"],
    )
    setup = runner.invoke(
        app,
        ["replay", "breakout-selection-bias", "--group-by", "setup-type"],
    )
    invalid = runner.invoke(
        app,
        ["replay", "breakout-source-gap-audit", "--group-by", "outcome"],
    )

    assert market.exit_code == 0, market.output
    assert "POSITIVE" in market.output
    assert setup.exit_code == 0, setup.output
    assert "MOMENTUM_CONTINUATION" in setup.output
    assert invalid.exit_code != 0
    assert "unsupported grouping" in invalid.output


def test_cli_passes_all_gap_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _cli_report()
    received: dict[str, object] = {}

    def _build(**kwargs: object):  # type: ignore[no-untyped-def]
        received.update(kwargs)
        return report

    monkeypatch.setattr(
        cli_module,
        "build_project_breakout_source_gap_audit",
        _build,
    )
    result = CliRunner().invoke(
        app,
        [
            "replay",
            "breakout-gap-sample",
            "--cause",
            "multi-session-gap",
            "--recovery-class",
            "recovery-uncertain",
            "--provider",
            "PROJECT_ALPHA_CANONICAL_DAILY_PRICES",
            "--symbol",
            "SYM0",
            "--from-date",
            "2024-06-01",
            "--to-date",
            "2024-06-30",
            "--year",
            "2024",
            "--minimum-sample",
            "2",
            "--limit",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert received["group_cause"] is BreakoutGapCause.MULTI_SESSION_GAP
    assert received["recovery_class"] is BreakoutGapRecoveryClass.RECOVERY_UNCERTAIN
    assert received["provider"] == "PROJECT_ALPHA_CANONICAL_DAILY_PRICES"
    assert received["symbol"] == "SYM0"
    assert received["from_date"] == date(2024, 6, 1)
    assert received["to_date"] == date(2024, 6, 30)
    assert received["year"] == 2024
    assert "Records Shown: 1" in result.output


def test_cli_json_and_csv_exports_are_deterministic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = _cli_report()
    monkeypatch.setattr(
        cli_module,
        "build_project_breakout_source_gap_audit",
        lambda **_: report,
    )
    runner = CliRunner()
    json_a = tmp_path / "a.json"
    json_b = tmp_path / "b.json"
    csv_a = tmp_path / "a.csv"
    csv_b = tmp_path / "b.csv"

    for output in (json_a, json_b):
        result = runner.invoke(
            app,
            [
                "replay",
                "breakout-source-gap-audit",
                "--format",
                "json",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0, result.output
    for output in (csv_a, csv_b):
        result = runner.invoke(
            app,
            [
                "replay",
                "breakout-source-coverage",
                "--format",
                "csv",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0, result.output

    assert json_a.read_bytes() == json_b.read_bytes()
    assert csv_a.read_bytes() == csv_b.read_bytes()


def test_policy_integrity_boundary_is_explicit() -> None:
    report = _cli_report()

    assert not report.production_influence
    assert all(not row.production_influence for row in report.coverage.records)
