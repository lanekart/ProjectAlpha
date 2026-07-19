from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from alpha.historical_replay.breakout_intelligence import (
    BreakoutClass,
    build_breakout_intelligence_report,
)
from alpha.historical_replay.breakout_reference import (
    BREAKOUT_REFERENCE_ALGORITHM_VERSION,
    BREAKOUT_REFERENCE_DATASET_VERSION,
    BreakoutCutoffSemantics,
    BreakoutIntegrityStatus,
    BreakoutReconstructionCandidate,
    BreakoutReferenceConfiguration,
    BreakoutReferenceMethod,
    BreakoutReferenceReadinessStatus,
    BreakoutReferenceRepository,
    CorporateActionEvent,
    HistoricalSecurityIdentity,
    LegacyDateCutoffPolicy,
    PointInTimeBreakoutReferenceEngine,
    PriceAdjustmentMode,
    apply_reconstructed_breakout_references,
    audit_breakout_reference_integrity,
    build_breakout_historical_readiness_report,
    export_breakout_reference_csv,
    export_breakout_reference_json,
    source_bar_from_values,
)
from alpha.historical_replay.precision_frontier import DirectionalObservation

_IST = ZoneInfo("Asia/Kolkata")


def _sessions(start: date, count: int) -> tuple[date, ...]:
    rows: list[date] = []
    current = start
    while len(rows) < count:
        if current.weekday() < 5:
            rows.append(current)
        current += timedelta(days=1)
    return tuple(rows)


def _bars(
    sessions: tuple[date, ...],
    *,
    pivot_index: int | None = 12,
    observation_close: Decimal = Decimal("121"),
    adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.RAW_UNADJUSTED,
) -> tuple[object, ...]:
    rows = []
    for index, session in enumerate(sessions):
        base = Decimal("100") + Decimal(index) / Decimal("10")
        high = base + Decimal("1")
        if pivot_index is not None and index == pivot_index:
            high = Decimal("120")
        close = min(base + Decimal("0.5"), high)
        if index == len(sessions) - 1:
            close = observation_close
            high = max(high, observation_close + Decimal("1"))
            base = min(base, close)
        rows.append(
            source_bar_from_values(
                observed_on=session,
                open_price=base,
                high_price=high,
                low_price=base - Decimal("1"),
                close_price=close,
                volume=1000 + index * 10,
                adjustment_mode=adjustment_mode,
            )
        )
    return tuple(rows)


def _candidate(
    observation_date: date,
    *,
    decision_at: datetime | None = None,
    proven: bool = False,
    symbol: str = "TEST",
) -> BreakoutReconstructionCandidate:
    return BreakoutReconstructionCandidate(
        replay_run_id=f"historical_replay|{observation_date}",
        candidate_id=f"candidate-{observation_date}",
        historical_symbol=symbol,
        observation_date=observation_date,
        decision_at=decision_at,
        timestamp_is_proven=proven,
    )


def _identity(
    *,
    symbol: str = "TEST",
    resolved: bool = True,
    listing_date: date | None = None,
    delisting_date: date | None = None,
) -> HistoricalSecurityIdentity:
    return HistoricalSecurityIdentity(
        instrument_identifier="NSE-EQ-TEST" if resolved else None,
        historical_symbol=symbol,
        exchange="NSE",
        security_master_version="pit-security-v1",
        evidence_reference="store#security=NSE-EQ-TEST",
        resolved=resolved,
        listing_date=listing_date,
        delisting_date=delisting_date,
    )


def _engine(
    *,
    method: BreakoutReferenceMethod = BreakoutReferenceMethod.PRIOR_SWING_HIGH,
    legacy_policy: LegacyDateCutoffPolicy = (
        LegacyDateCutoffPolicy.PREVIOUS_COMPLETED_SESSION
    ),
    algorithm_version: str = BREAKOUT_REFERENCE_ALGORITHM_VERSION,
) -> PointInTimeBreakoutReferenceEngine:
    return PointInTimeBreakoutReferenceEngine(
        BreakoutReferenceConfiguration(
            reference_method=method,
            minimum_lookback=10,
            reference_lookback=20,
            legacy_date_policy=legacy_policy,
            algorithm_version=algorithm_version,
        ),
        clock=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _record(
    *,
    method: BreakoutReferenceMethod = BreakoutReferenceMethod.PRIOR_SWING_HIGH,
    bars: tuple[object, ...] | None = None,
    sessions: tuple[date, ...] | None = None,
    candidate: BreakoutReconstructionCandidate | None = None,
    identity: HistoricalSecurityIdentity | None = None,
    engine: PointInTimeBreakoutReferenceEngine | None = None,
    corporate_actions: tuple[CorporateActionEvent, ...] = (),
):  # type: ignore[no-untyped-def]
    sessions = sessions or _sessions(date(2024, 1, 2), 24)
    source = bars or _bars(sessions[:-1])
    candidate = candidate or _candidate(sessions[-1])
    return (engine or _engine(method=method)).reconstruct(
        candidate=candidate,
        bars=source,  # type: ignore[arg-type]
        identity=identity or _identity(),
        exchange_sessions=sessions,
        corporate_actions=corporate_actions,
    )


def test_cutoff_semantics_exclude_unavailable_candidate_and_future_bars() -> None:
    sessions = _sessions(date(2024, 1, 2), 26)
    source = _bars(sessions)

    record = _record(sessions=sessions, bars=source, candidate=_candidate(sessions[-1]))

    assert record.cutoff_semantics is (
        BreakoutCutoffSemantics.LEGACY_DATE_ONLY_PREVIOUS_SESSION
    )
    assert record.last_bar_timestamp_used is not None
    assert record.last_bar_timestamp_used.date() == sessions[-2]
    assert all(
        timestamp.date() <= sessions[-2]
        for timestamp in record.provenance.source_bar_timestamps
    )


def test_proven_after_close_uses_candidate_session_but_not_as_reference_bar() -> None:
    sessions = _sessions(date(2024, 2, 1), 25)
    source = _bars(sessions, observation_close=Decimal("123"))
    decision = datetime.combine(sessions[-1], time(16, 15), tzinfo=_IST)

    record = _record(
        sessions=sessions,
        bars=source,
        candidate=_candidate(sessions[-1], decision_at=decision, proven=True),
    )

    assert record.cutoff_semantics is (
        BreakoutCutoffSemantics.AFTER_CLOSE_CANDIDATE_SESSION
    )
    assert record.evidence.candidate_session_price == Decimal("123")
    assert record.evidence.confirmation_end < record.evidence.observation_bar_timestamp  # type: ignore[operator]


def test_pre_market_intraday_ambiguous_and_weekend_cutoffs_are_explicit() -> None:
    sessions = _sessions(date(2024, 3, 1), 25)
    source = _bars(sessions)
    candidate_day = sessions[-1]
    pre_market = datetime.combine(candidate_day, time(8), tzinfo=_IST)
    intraday = datetime.combine(candidate_day, time(11), tzinfo=_IST)
    pre = _record(
        sessions=sessions,
        bars=source,
        candidate=_candidate(candidate_day, decision_at=pre_market, proven=True),
    )
    intra = _record(
        sessions=sessions,
        bars=source,
        candidate=_candidate(candidate_day, decision_at=intraday, proven=True),
    )
    ambiguous = _record(
        sessions=sessions,
        bars=source,
        candidate=_candidate(candidate_day),
        engine=_engine(legacy_policy=LegacyDateCutoffPolicy.AMBIGUOUS),
    )
    weekend = candidate_day + timedelta(days=(5 - candidate_day.weekday()) % 7)
    if weekend == candidate_day:
        weekend += timedelta(days=1)
    weekend_record = _record(
        sessions=sessions,
        bars=source,
        candidate=_candidate(weekend),
    )

    assert pre.cutoff_semantics is BreakoutCutoffSemantics.PRE_MARKET_PREVIOUS_SESSION
    assert intra.cutoff_semantics is BreakoutCutoffSemantics.INTRADAY_PREVIOUS_SESSION
    assert ambiguous.readiness_status is (
        BreakoutReferenceReadinessStatus.AMBIGUOUS_DECISION_CUTOFF
    )
    assert weekend_record.cutoff_semantics is (
        BreakoutCutoffSemantics.NON_TRADING_DATE_PREVIOUS_SESSION
    )


def test_reference_methods_construct_exact_levels_without_future_confirmation() -> None:
    sessions = _sessions(date(2024, 4, 1), 27)
    source = list(_bars(sessions[:-1], pivot_index=10))
    future = source_bar_from_values(
        observed_on=sessions[-1],
        open_price=129,
        high_price=150,
        low_price=128,
        close_price=149,
        volume=9000,
    )
    source.append(future)

    swing = _record(sessions=sessions, bars=tuple(source))
    rolling = _record(
        sessions=sessions,
        bars=tuple(source),
        method=BreakoutReferenceMethod.ROLLING_HIGH,
    )

    assert swing.evidence.primary_reference_level == Decimal("120")
    assert rolling.evidence.primary_reference_level == Decimal("120")
    assert sessions[-1] not in {
        timestamp.date() for timestamp in swing.provenance.source_bar_timestamps
    }
    assert swing.evidence.touch_count >= 1


def test_range_resistance_requires_multiple_touches_and_no_reference_is_valid() -> None:
    sessions = _sessions(date(2024, 5, 1), 25)
    source = list(_bars(sessions[:-1], pivot_index=None))
    for index in (8, 15):
        source[index] = replace(source[index], high_price=Decimal("115"))
    range_record = _record(
        sessions=sessions,
        bars=tuple(source),
        method=BreakoutReferenceMethod.RANGE_RESISTANCE,
    )
    no_reference = _record(
        sessions=sessions,
        bars=_bars(sessions[:-1], pivot_index=None),
    )

    assert range_record.readiness_status is BreakoutReferenceReadinessStatus.READY
    assert range_record.evidence.primary_reference_level == Decimal("115")
    assert range_record.evidence.touch_count == 2
    assert no_reference.readiness_status is (
        BreakoutReferenceReadinessStatus.REFERENCE_NOT_FORMED
    )
    assert no_reference.is_historically_usable is True


def test_distance_states_cover_below_at_and_above_reference() -> None:
    sessions = _sessions(date(2024, 6, 3), 26)
    formation = _bars(sessions[:-2], observation_close=Decimal("110"))
    observation_day = sessions[-2]

    def with_close(value: Decimal):  # type: ignore[no-untyped-def]
        observation = source_bar_from_values(
            observed_on=observation_day,
            open_price=min(value, Decimal("119")),
            high_price=max(value, Decimal("120")),
            low_price=min(value - Decimal("1"), Decimal("118")),
            close_price=value,
            volume=5000,
        )
        return _record(sessions=sessions, bars=(*formation, observation))

    below = with_close(Decimal("115"))
    at = with_close(Decimal("120"))
    above = with_close(Decimal("123"))

    assert below.evidence.distance_to_reference < 0  # type: ignore[operator]
    assert at.evidence.distance_to_reference == 0
    assert above.evidence.distance_to_reference > 0  # type: ignore[operator]
    assert above.evidence.breakout_attempt_evidence == "CLOSE_ABOVE_REFERENCE"


def test_reconstruction_is_deterministic_across_operational_timestamps() -> None:
    first = _record(engine=_engine())
    later_engine = PointInTimeBreakoutReferenceEngine(
        _engine().configuration,
        clock=datetime(2026, 7, 1, tzinfo=UTC),
    )
    second = _record(engine=later_engine)

    assert first.semantic_hash == second.semantic_hash
    assert first.evidence == second.evidence
    assert first.provenance.reconstruction_timestamp != (
        second.provenance.reconstruction_timestamp
    )


def test_invalid_series_and_insufficient_lookback_are_excluded() -> None:
    sessions = _sessions(date(2024, 7, 1), 25)
    valid = _bars(sessions[:-1])
    duplicate = (*valid[:5], valid[4], *valid[5:])
    unordered = tuple(reversed(valid))
    missing_volume = (replace(valid[0], volume=None), *valid[1:])
    invalid_ohlc = (replace(valid[0], high_price=Decimal("1")), *valid[1:])
    non_positive = (replace(valid[0], close_price=Decimal("0")), *valid[1:])
    short = valid[:5]

    for bars in (duplicate, unordered, missing_volume, invalid_ohlc, non_positive):
        assert _record(sessions=sessions, bars=bars).readiness_status is (
            BreakoutReferenceReadinessStatus.INVALID_PRICE_SERIES
        )
    assert _record(sessions=sessions, bars=short).readiness_status is (
        BreakoutReferenceReadinessStatus.INSUFFICIENT_LOOKBACK
    )


def test_timezone_identity_listing_delisting_and_adjustment_validation() -> None:
    sessions = _sessions(date(2024, 8, 1), 25)
    valid = _bars(sessions[:-1])
    utc_bars = tuple(
        replace(bar, observed_at=bar.observed_at.astimezone(UTC)) for bar in valid
    )
    adjusted = _bars(sessions[:-1], adjustment_mode=PriceAdjustmentMode.SPLIT_ADJUSTED)
    candidate = _candidate(sessions[-1], symbol="OLDNAME")

    assert _record(sessions=sessions, bars=utc_bars).readiness_status is (
        BreakoutReferenceReadinessStatus.TIMEZONE_MISMATCH
    )
    assert _record(identity=_identity(resolved=False)).readiness_status is (
        BreakoutReferenceReadinessStatus.SYMBOL_IDENTITY_UNRESOLVED
    )
    assert (
        _record(
            candidate=candidate,
            identity=_identity(
                symbol="OLDNAME", listing_date=sessions[-1] + timedelta(days=1)
            ),
            sessions=sessions,
            bars=valid,
        ).readiness_status
        is BreakoutReferenceReadinessStatus.LISTING_DATE_VIOLATION
    )
    assert (
        _record(
            candidate=candidate,
            identity=_identity(symbol="OLDNAME", delisting_date=sessions[-2]),
            sessions=sessions,
            bars=valid,
        ).readiness_status
        is BreakoutReferenceReadinessStatus.DELISTING_DATE_VIOLATION
    )
    migrated_identity = replace(
        _identity(symbol="OLDNAME"),
        successor_symbol="NEWNAME",
    )
    assert _record(
        candidate=candidate,
        identity=migrated_identity,
        sessions=sessions,
        bars=valid,
    ).readiness_status in {
        BreakoutReferenceReadinessStatus.READY,
        BreakoutReferenceReadinessStatus.REFERENCE_NOT_FORMED,
    }
    assert _record(sessions=sessions, bars=adjusted).readiness_status is (
        BreakoutReferenceReadinessStatus.ADJUSTMENT_MODE_MISMATCH
    )


def test_split_before_cutoff_trims_raw_history_and_split_after_cutoff_is_ignored() -> (
    None
):
    sessions = _sessions(date(2024, 9, 2), 36)
    source = list(_bars(sessions[:-1], pivot_index=4))
    split_date = sessions[12]
    for index in range(12, len(source)):
        bar = source[index]
        source[index] = replace(
            bar,
            open_price=bar.open_price / 2,
            high_price=bar.high_price / 2,
            low_price=bar.low_price / 2,
            close_price=bar.close_price / 2,
        )
    before = CorporateActionEvent(
        symbol="TEST",
        effective_date=split_date,
        action_type="STOCK_SPLIT",
        source="official-test-fixture",
        adjustment_mode=PriceAdjustmentMode.RAW_UNADJUSTED,
    )
    after = replace(before, effective_date=sessions[-1] + timedelta(days=10))

    trimmed = _record(
        sessions=sessions,
        bars=tuple(source),
        corporate_actions=(before,),
    )
    ignored = _record(
        sessions=sessions,
        bars=_bars(sessions[:-1]),
        corporate_actions=(after,),
    )

    assert any(
        "HISTORY_TRIMMED_AFTER_SPLIT" in item for item in trimmed.provenance.warnings
    )
    assert trimmed.last_bar_timestamp_used.date() >= split_date  # type: ignore[union-attr]
    assert not any(
        "HISTORY_TRIMMED_AFTER_SPLIT" in item for item in ignored.provenance.warnings
    )


def test_unexplained_large_discontinuity_is_corporate_action_ambiguity() -> None:
    sessions = _sessions(date(2024, 10, 1), 30)
    source = list(_bars(sessions[:-1]))
    source[15] = replace(
        source[15],
        open_price=Decimal("25"),
        high_price=Decimal("27"),
        low_price=Decimal("24"),
        close_price=Decimal("26"),
    )

    record = _record(sessions=sessions, bars=tuple(source))

    assert record.readiness_status is (
        BreakoutReferenceReadinessStatus.CORPORATE_ACTION_AMBIGUITY
    )


def test_persistence_is_versioned_idempotent_and_preserves_semantic_lineage(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "breakout-reference.json"
    repository = BreakoutReferenceRepository(path)
    first = _record()

    initial = repository.save_records((first,))
    repeated = repository.save_records((first,))
    changed_algorithm = _record(
        engine=_engine(algorithm_version="point-in-time-breakout-reference-v2")
    )
    upgraded = repository.save_records((changed_algorithm,))
    payload = json.loads(path.read_text())

    assert initial.created == 1
    assert repeated.reused == 1
    assert upgraded.created == 1
    assert len(repository.load_dataset().records) == 2
    assert payload["manifest"]["dataset_version"] == BREAKOUT_REFERENCE_DATASET_VERSION
    assert first.provenance.raw_series_checksum
    assert first.provenance.configuration_hash
    assert first.provenance.algorithm_version == BREAKOUT_REFERENCE_ALGORITHM_VERSION


def test_dry_run_does_not_write_and_integrity_detects_tampering(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "dry-run.json"
    repository = BreakoutReferenceRepository(path)
    record = _record()

    result = repository.save_records((record,), dry_run=True)
    tampered = replace(record, semantic_hash="wrong")
    audit = audit_breakout_reference_integrity((tampered,))

    assert result.dry_run is True
    assert not path.exists()
    assert audit.determinism_status is BreakoutIntegrityStatus.FAIL


def test_readiness_distinguishes_valid_no_reference_from_unreconstructable() -> None:
    ready = _record()
    no_reference = _record(
        bars=_bars(_sessions(date(2024, 1, 2), 23), pivot_index=None)
    )
    unresolved = _record(identity=_identity(resolved=False))

    report = build_breakout_historical_readiness_report(
        records=(ready, no_reference, unresolved),
        total_replay_candidates=3,
    )

    assert report.ready_records == 1
    assert report.reference_not_formed_records == 1
    assert report.unreconstructable_records == 1
    assert report.readiness_percentage == Decimal("66.67")
    assert report.unresolved_symbol_count == 1


def test_adapter_supplies_only_ready_point_in_time_levels_to_breakout_engine() -> None:
    record = _record()
    observation = DirectionalObservation(
        symbol="TEST",
        observed_at=record.candidate_observation_date,
        horizon_days=20,
        forward_return=0.05,
        max_favorable_excursion=0.08,
        max_adverse_excursion=-0.03,
        recommendation_score=0.75,
        source="directional-audit",
        feature_values=(("target_1", 999.0),),
    )

    enriched = apply_reconstructed_breakout_references((observation,), (record,))[0]

    features = dict(enriched.feature_values)
    assert features["resistance"] == float(record.evidence.primary_reference_level)  # type: ignore[arg-type]
    assert features["price"] == float(record.evidence.candidate_session_price)  # type: ignore[arg-type]
    assert "target_1" not in features
    assert "breakout_reference_dataset_v1" in enriched.source


def test_breakout_engine_consumes_typed_reference_and_preserves_missing_semantics() -> (
    None
):
    ready = _record()
    observation = DirectionalObservation(
        symbol="TEST",
        observed_at=ready.candidate_observation_date,
        horizon_days=20,
        forward_return=0.05,
        max_favorable_excursion=0.08,
        max_adverse_excursion=-0.03,
        recommendation_score=0.75,
        price_component=0.75,
        setup_quality=0.75,
        entry_timing="CONFIRMATION",
        trade_plan_quality=0.75,
        stop_distance_pct=0.03,
        confidence=0.75,
        feature_values=(("volume", 0.75), ("relative_strength", 0.75)),
    )
    report = build_breakout_intelligence_report(
        (observation,),
        reference_records=(ready,),
    )
    unavailable = replace(
        ready,
        readiness_status=BreakoutReferenceReadinessStatus.SOURCE_UNAVAILABLE,
        evidence=replace(ready.evidence, primary_reference_level=None),
        semantic_hash="",
    )
    unavailable = replace(
        unavailable,
        semantic_hash=unavailable.calculated_semantic_hash(),
    )
    missing_report = build_breakout_intelligence_report(
        (observation,),
        reference_records=(unavailable,),
    )

    assert report.observations[0].breakout_reference_level == float(
        ready.evidence.primary_reference_level  # type: ignore[arg-type]
    )
    assert missing_report.observations[0].classification.ex_ante_class is (
        BreakoutClass.INSUFFICIENT_EVIDENCE
    )


def test_exports_are_sorted_and_production_influence_remains_false(tmp_path) -> None:  # type: ignore[no-untyped-def]
    first = _record()
    second = replace(
        first,
        candidate_id="candidate-z",
        historical_symbol="ZZZ",
        semantic_hash="",
    )
    second = replace(second, semantic_hash=second.calculated_semantic_hash())
    json_path = tmp_path / "records.json"
    csv_path = tmp_path / "records.csv"

    export_breakout_reference_json((second, first), json_path)
    export_breakout_reference_csv((second, first), csv_path)

    assert first.production_influence is False
    assert "production_influence" in csv_path.read_text()
    assert json.loads(json_path.read_text())[0]["production_influence"] is False
