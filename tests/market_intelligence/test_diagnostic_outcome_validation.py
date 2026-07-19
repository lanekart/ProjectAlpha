from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from alpha.candidate_learning.models import (
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
)
from alpha.market_intelligence import (
    DIAGNOSTIC_MARKET_STATE_DATASET_VERSION,
    DiagnosticAuthoritativeStatus,
    DiagnosticBreadthSourceType,
    DiagnosticCompatibilityLabel,
    DiagnosticInputCompleteness,
    DiagnosticMarketBreadth,
    DiagnosticMarketStateCandidateLink,
    DiagnosticMarketStateReconstruction,
    DiagnosticNextMilestone,
    DiagnosticReconstructionQuality,
    DiagnosticRegimeOutcomeValidationEngine,
    DiagnosticSectorAvailability,
    TransparentReferenceState,
    build_diagnostic_dataset_integrity,
    diagnostic_dataset_fingerprint,
    export_diagnostic_outcome_json,
    export_diagnostic_rows_csv,
    render_regime_outcomes,
    render_threshold_readiness,
)


def test_frozen_dataset_fingerprint_changes_when_dataset_changes() -> None:
    reconstructions = (_reconstruction(date(2026, 1, 1), "BULLISH"),)
    links = (_link(reconstructions[0].reconstruction_id, "AAA-2026-01-01"),)

    first = diagnostic_dataset_fingerprint(
        reconstructions=reconstructions,
        links=links,
    )
    changed = diagnostic_dataset_fingerprint(
        reconstructions=(_reconstruction(date(2026, 1, 2), "BULLISH"),),
        links=links,
    )

    assert first != changed


def test_integrity_detects_duplicate_and_orphan_links() -> None:
    reconstruction = _reconstruction(date(2026, 1, 1), "BULLISH")
    duplicate = (reconstruction, reconstruction)
    links = (
        _link(reconstruction.reconstruction_id, "AAA-2026-01-01"),
        _link(reconstruction.reconstruction_id, "AAA-2026-01-01"),
        _link("missing", "BBB-2026-01-01"),
    )

    integrity = build_diagnostic_dataset_integrity(
        reconstructions=duplicate,
        links=links,
    )

    assert integrity.duplicate_reconstruction_ids == 1
    assert integrity.duplicate_candidate_links == 1
    assert integrity.orphan_candidate_links == 1
    assert integrity.immutable_join_preserved is True


def test_regime_outcome_validation_separates_bullish_and_bearish_fixture() -> None:
    report = DiagnosticRegimeOutcomeValidationEngine().build(
        reconstructions=(
            _reconstruction(date(2026, 1, 1), "BULLISH"),
            _reconstruction(date(2026, 1, 2), "BEARISH"),
        ),
        links=(
            _link("recon-2026-01-01-BULLISH", "AAA-2026-01-01"),
            _link("recon-2026-01-02-BEARISH", "BBB-2026-01-02"),
        ),
        records=(
            _record("AAA", date(2026, 1, 1), "BUY"),
            _record("BBB", date(2026, 1, 2), "AVOID"),
        ),
        outcomes=(
            _outcome("AAA-2026-01-01", Decimal("8")),
            _outcome("BBB-2026-01-02", Decimal("-6")),
        ),
    )

    outcomes = {
        item.group: item.average_forward_return
        for item in report.candidate_weighted_regime_outcomes
    }

    assert outcomes["BULLISH"] == Decimal("8.0000")
    assert outcomes["BEARISH"] == Decimal("-6.0000")
    assert "Dataset Fingerprint:" in "\n".join(render_regime_outcomes(report))


def test_date_weighted_analysis_prevents_large_date_domination() -> None:
    reconstructions = (
        _reconstruction(date(2026, 1, 1), "BULLISH"),
        _reconstruction(date(2026, 1, 2), "BULLISH"),
    )
    records = tuple(
        _record(f"WIN{index}", date(2026, 1, 1), "BUY") for index in range(5)
    ) + (_record("LOSS", date(2026, 1, 2), "BUY"),)
    links = tuple(
        _link("recon-2026-01-01-BULLISH", record.candidate_id)
        if record.evaluation_date == date(2026, 1, 1)
        else _link("recon-2026-01-02-BULLISH", record.candidate_id)
        for record in records
    )
    outcomes = tuple(
        _outcome(record.candidate_id, Decimal("10"))
        if record.symbol.startswith("WIN")
        else _outcome(record.candidate_id, Decimal("-10"))
        for record in records
    )

    report = DiagnosticRegimeOutcomeValidationEngine().build(
        reconstructions=reconstructions,
        links=links,
        records=records,
        outcomes=outcomes,
    )

    candidate = report.candidate_weighted_regime_outcomes[0]
    date_weighted = report.date_weighted_regime_outcomes[0]

    assert candidate.average_forward_return == Decimal("6.6667")
    assert date_weighted.average_forward_return == Decimal("0.0000")


def test_readiness_is_conservative_when_sector_is_missing() -> None:
    report = DiagnosticRegimeOutcomeValidationEngine().build(
        reconstructions=(
            _reconstruction(date(2026, 1, 1), "BULLISH"),
            _reconstruction(date(2026, 1, 2), "BEARISH"),
        ),
        links=(
            _link("recon-2026-01-01-BULLISH", "AAA-2026-01-01"),
            _link("recon-2026-01-02-BEARISH", "BBB-2026-01-02"),
        ),
        records=(
            _record("AAA", date(2026, 1, 1), "BUY"),
            _record("BBB", date(2026, 1, 2), "AVOID"),
        ),
        outcomes=(
            _outcome("AAA-2026-01-01", Decimal("8")),
            _outcome("BBB-2026-01-02", Decimal("-6")),
        ),
    )

    assert report.recommended_next_milestone in {
        DiagnosticNextMilestone.BUILD_POINT_IN_TIME_SECTOR_HISTORY,
        DiagnosticNextMilestone.INSUFFICIENT_EVIDENCE_COLLECT_MORE_DATA,
    }
    assert "Explicitly Prohibited Next Action" in "\n".join(
        render_threshold_readiness(report)
    )


def test_json_and_csv_exports_are_deterministic(tmp_path: Path) -> None:
    report = DiagnosticRegimeOutcomeValidationEngine().build(
        reconstructions=(_reconstruction(date(2026, 1, 1), "BULLISH"),),
        links=(_link("recon-2026-01-01-BULLISH", "AAA-2026-01-01"),),
        records=(_record("AAA", date(2026, 1, 1), "BUY"),),
        outcomes=(_outcome("AAA-2026-01-01", Decimal("8")),),
    )

    json_path = export_diagnostic_outcome_json(report, tmp_path / "report.json")
    csv_path = export_diagnostic_rows_csv(
        report.candidate_weighted_regime_outcomes,
        tmp_path / "outcomes.csv",
    )

    assert json_path.read_text(encoding="utf-8").startswith("{")
    assert "dataset_fingerprint" in json_path.read_text(encoding="utf-8")
    assert "group,candidate_count" in csv_path.read_text(encoding="utf-8")


class _Record:
    def __init__(self, symbol: str, evaluation_date: date, verdict: str) -> None:
        self.candidate_id = f"{symbol}-{evaluation_date.isoformat()}"
        self.symbol = symbol
        self.evaluation_date = evaluation_date
        self.market_regime = "NEUTRAL"
        self.setup_type = "MOMENTUM_CONTINUATION"
        self.final_verdict = verdict
        self.capital_action = "BUY" if verdict == "BUY" else "AVOID"
        self.approved_for_deployment = verdict == "BUY"
        self.sector = None
        self.strategy_score = Decimal("80") if verdict == "BUY" else Decimal("40")
        self.indicator_scores = {
            "retracement": "50",
            "price": "60",
            "volume": "55",
        }


def _record(symbol: str, evaluation_date: date, verdict: str) -> _Record:
    return _Record(symbol, evaluation_date, verdict)


def _outcome(candidate_id: str, forward_return: Decimal) -> CandidateForwardOutcome:
    return CandidateForwardOutcome(
        candidate_id=candidate_id,
        symbol=candidate_id.split("-")[0],
        evaluated_at=datetime(2026, 2, 1, tzinfo=UTC),
        windows=(
            CandidateForwardWindowOutcome(
                window="20d",
                forward_open=None,
                forward_high=None,
                forward_low=None,
                forward_close=None,
                forward_return_pct_from_close=forward_return,
                forward_return_pct_from_entry=forward_return,
                max_favourable_excursion_pct=max(forward_return, Decimal("0")),
                max_adverse_excursion_pct=min(forward_return, Decimal("0")),
                target_1_touched=forward_return > Decimal("0"),
                risk_stop_touched=forward_return < Decimal("0"),
                outcome_label=CandidateOutcomeLabel.WOULD_HAVE_WON
                if forward_return > Decimal("0")
                else CandidateOutcomeLabel.WOULD_HAVE_LOST,
            ),
        ),
    )


def _link(
    reconstruction_id: str,
    candidate_id: str,
) -> DiagnosticMarketStateCandidateLink:
    market_date = date.fromisoformat(candidate_id[-10:])
    return DiagnosticMarketStateCandidateLink(
        reconstruction_id=reconstruction_id,
        candidate_stable_id=candidate_id,
        link_status="DIAGNOSTIC_LINK_ONLY",
        candidate_decision_timestamp=datetime.combine(
            market_date,
            datetime.min.time(),
            tzinfo=UTC,
        ),
        timestamp_difference="0s",
        recorded_candidate_regime="NEUTRAL",
        setup_type="MOMENTUM_CONTINUATION",
        final_verdict="BUY",
        entry_state="APPROVED",
        outcome_available=True,
    )


def _reconstruction(
    market_date: date,
    regime: str,
) -> DiagnosticMarketStateReconstruction:
    return DiagnosticMarketStateReconstruction(
        reconstruction_id=f"recon-{market_date.isoformat()}-{regime}",
        market_date=market_date,
        decision_cutoff=datetime.combine(market_date, datetime.max.time(), tzinfo=UTC),
        candidate_date=market_date,
        candidate_count=1,
        source_type="CURRENT_COMPATIBLE_CLASSIFIER_REPLAY",
        authoritative_status=DiagnosticAuthoritativeStatus.DIAGNOSTIC_RECONSTRUCTED,
        benchmark_symbol="NIFTYBEES",
        benchmark_latest_bar=market_date,
        benchmark_alignment="EXACT",
        benchmark_close=Decimal("100"),
        benchmark_return_1d=Decimal("0.01"),
        benchmark_return_5d=Decimal("0.02"),
        benchmark_return_20d=Decimal("0.05")
        if regime == "BULLISH"
        else Decimal("-0.05")
        if regime == "BEARISH"
        else Decimal("0"),
        benchmark_dma_20=Decimal("95"),
        benchmark_dma_50=Decimal("96"),
        benchmark_dma_200=Decimal("97"),
        benchmark_distance_20dma=Decimal("0.05"),
        benchmark_distance_50dma=Decimal("0.04"),
        benchmark_distance_200dma=Decimal("0.03"),
        benchmark_atr=Decimal("2"),
        benchmark_volatility=Decimal("0.02"),
        breadth_score=Decimal("60"),
        participation_score=Decimal("60"),
        sector_score=None,
        market_trend_score=Decimal("70"),
        market_volatility_score=Decimal("80"),
        current_classifier_regime=regime,
        transparent_reference_state=TransparentReferenceState.POSITIVE
        if regime == "BULLISH"
        else TransparentReferenceState.NEGATIVE
        if regime == "BEARISH"
        else TransparentReferenceState.NEUTRAL,
        classifier_version_used="test-classifier",
        classifier_fingerprint_used="test-fingerprint",
        compatibility_status=DiagnosticCompatibilityLabel.SEMANTIC_COMPATIBILITY_ONLY,
        manifest_era_status="test",
        input_completeness=DiagnosticInputCompleteness.COMPLETE_DIAGNOSTIC,
        reconstruction_quality=DiagnosticReconstructionQuality.HIGH,
        benchmark_quality=DiagnosticReconstructionQuality.HIGH,
        breadth_quality=DiagnosticReconstructionQuality.MEDIUM,
        sector_quality=DiagnosticReconstructionQuality.UNUSABLE,
        timestamp_quality=DiagnosticReconstructionQuality.HIGH,
        classifier_compatibility_quality=DiagnosticReconstructionQuality.LOW,
        source_lineage_quality=DiagnosticReconstructionQuality.MEDIUM,
        overall_diagnostic_quality=DiagnosticReconstructionQuality.HIGH,
        fallback_applied=False,
        fallback_reason=None,
        source_lineage=("test",),
        missing_fields=("sector_state",),
        created_at=datetime(1970, 1, 1, tzinfo=UTC),
        dataset_version=DIAGNOSTIC_MARKET_STATE_DATASET_VERSION,
        breadth=DiagnosticMarketBreadth(
            source_type=DiagnosticBreadthSourceType.DIAGNOSTIC_CURRENT_UNIVERSE_RECONSTRUCTION,
            universe_definition="test",
            universe_size=100,
            eligible_universe_size=100,
            advancers=60,
            decliners=40,
            unchanged=0,
            breadth_ratio=Decimal("0.60"),
            percent_above_20dma=None,
            percent_above_50dma=None,
            percent_above_200dma=None,
            new_20_day_highs=None,
            new_20_day_lows=None,
            breadth_score=Decimal("60"),
            coverage_ratio=Decimal("1"),
            warnings=("diagnostic",),
        ),
        sector_availability=DiagnosticSectorAvailability.SECTOR_STATE_UNAVAILABLE,
        exact_historical_reproduction=False,
        no_lookahead_violations=(),
    )
