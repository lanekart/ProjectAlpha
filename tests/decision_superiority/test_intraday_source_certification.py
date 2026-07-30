from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from alpha.decision_superiority.intraday_execution_models import (
    IntradayBar,
    IntradayExecutionError,
    IntradayReadiness,
)
from alpha.decision_superiority.intraday_execution_population import (
    IntradayPopulationPlan,
    plan_intraday_population,
)
from alpha.decision_superiority.intraday_execution_reconciliation import (
    DailyCandleReference,
    IdentityResolutionState,
    InstrumentResolution,
    UpstoxInstrumentRecord,
)
from alpha.decision_superiority.intraday_source_artifacts import (
    DSI013_SOURCE_ARTIFACTS,
    DSI013_SOURCE_CERTIFICATE,
    export_intraday_source_certification,
    validate_intraday_source_certificate,
)
from alpha.decision_superiority.intraday_source_certification import (
    GovernedIntradaySourceCertificationEngine,
    IntradaySourceEvidence,
)

IST = timezone(timedelta(hours=5, minutes=30))
IDENTITY = "nse:isin:INE000A01000"
INSTRUMENT_KEY = "NSE_EQ|INE000A01000"
SESSION_DATE = date(2024, 1, 3)


def _population() -> IntradayPopulationPlan:
    result = plan_intraday_population(
        (
            {
                "mechanism_id": "ENTRY-INCUMBENT-NEXT-OPEN",
                "fill_state": "ENTERED",
                "signal_id": "SIG-1",
                "identity_key": IDENTITY,
                "symbol": "ALPHA",
                "strategy_variant_id": "STRATEGY-1",
                "walk_forward_fold_id": "WF-2024",
                "regime": "BULL",
                "signal_date": "2024-01-02",
                "entry_eligibility_date": SESSION_DATE.isoformat(),
                "signal_strength": "0.75",
                "raw_entry_price": "100.00",
                "entry_price_after_slippage": "100.10",
                "initial_stop": "95.00",
                "target_1": "110.00",
                "target_2": "115.00",
                "maximum_holding_sessions": "20",
                "average_traded_value20": "10000000",
            },
        )
    )
    return IntradayPopulationPlan(
        candidates=result.candidates,
        requests=result.requests,
        exclusions=result.exclusions,
        reconciliation=result.reconciliation,
        dsi009_certificate_sha256="d" * 64,
    )


def _resolution(
    *,
    state: IdentityResolutionState = IdentityResolutionState.RESOLVED,
) -> InstrumentResolution:
    instrument = (
        UpstoxInstrumentRecord(
            name="ALPHA LIMITED",
            exchange="NSE",
            segment="NSE_EQ",
            isin="INE000A01000",
            instrument_key=INSTRUMENT_KEY,
            exchange_token="123",
            trading_symbol="ALPHA",
            instrument_type="EQ",
        )
        if state is IdentityResolutionState.RESOLVED
        else None
    )
    return InstrumentResolution(
        governed_identity=IDENTITY,
        governed_isin="INE000A01000",
        state=state,
        instrument=instrument,
        source_sha256="a" * 64,
        resolved_at=datetime(2026, 7, 30, 16, 0, tzinfo=UTC),
        blocker=None if instrument is not None else "IDENTITY_BLOCKED",
    )


def _bars(*, close_adjustment: float = 0.0) -> tuple[IntradayBar, ...]:
    start = datetime(2024, 1, 3, 9, 15, tzinfo=IST)
    rows: list[IntradayBar] = []
    for index in range(75):
        price = 100.0 + index / 100
        close = price + 0.05
        if index == 74:
            close += close_adjustment
        rows.append(
            IntradayBar(
                governed_identity=IDENTITY,
                instrument_key=INSTRUMENT_KEY,
                timestamp=start + timedelta(minutes=index * 5),
                open=price,
                high=max(price + 0.20, close),
                low=min(price - 0.20, close),
                close=close,
                volume=1_000 + index,
            )
        )
    return tuple(rows)


def _daily() -> DailyCandleReference:
    return DailyCandleReference(
        governed_identity=IDENTITY,
        session_date=SESSION_DATE,
        open=100.0,
        high=100.94,
        low=99.8,
        close=100.79,
        volume=77_775,
        price_basis="RAW",
        source_sha256="b" * 64,
    )


def _evidence(
    *,
    resolution: InstrumentResolution | None = None,
    bars: tuple[IntradayBar, ...] | None = None,
    daily: DailyCandleReference | None = None,
) -> IntradaySourceEvidence:
    return IntradaySourceEvidence(
        source_commit="source-commit",
        population=_population(),
        identity_resolutions=(
            {} if resolution is None else {IDENTITY: resolution}
        ),
        bars_by_request=(
            {} if bars is None else {(IDENTITY, SESSION_DATE): bars}
        ),
        daily_by_request=(
            {} if daily is None else {(IDENTITY, SESSION_DATE): daily}
        ),
    )


def test_ready_source_certification_has_complete_evidence() -> None:
    result = GovernedIntradaySourceCertificationEngine().run(
        _evidence(
            resolution=_resolution(),
            bars=_bars(),
            daily=_daily(),
        )
    )

    assert result.readiness is IntradayReadiness.SOURCE_READY
    assert result.blockers == ()
    assert result.summaries["candidate_count"] == 1
    assert result.summaries["request_count"] == 1
    assert result.summaries["admitted_request_count"] == 1
    assert len(result.rows["bar_validation"]) == 75
    assert len(result.rows["daily_reconciliation"]) == 5
    assert result.governance["PRODUCTION_INFLUENCE"] is False


def test_identity_failure_has_highest_readiness_precedence() -> None:
    result = GovernedIntradaySourceCertificationEngine().run(
        _evidence(
            resolution=_resolution(
                state=IdentityResolutionState.SOURCE_RECORD_MISSING
            ),
            bars=_bars(),
            daily=_daily(),
        )
    )

    assert result.readiness is IntradayReadiness.IDENTITY_DEFECT
    assert result.summaries["identity_failure_count"] == 1


def test_missing_bars_is_source_unavailable() -> None:
    result = GovernedIntradaySourceCertificationEngine().run(
        _evidence(resolution=_resolution(), daily=_daily())
    )

    assert result.readiness is IntradayReadiness.SOURCE_UNAVAILABLE
    assert result.summaries["source_unavailable_count"] == 1


def test_daily_mismatch_blocks_source_readiness() -> None:
    result = GovernedIntradaySourceCertificationEngine().run(
        _evidence(
            resolution=_resolution(),
            bars=_bars(close_adjustment=0.10),
            daily=_daily(),
        )
    )

    assert result.readiness is IntradayReadiness.DAILY_RECONCILIATION_DEFECT
    assert result.summaries["reconciliation_failure_count"] == 1
    assert any("CLOSE_MISMATCH" in blocker for blocker in result.blockers)


def test_source_artifacts_round_trip_and_tamper_detection(tmp_path: Path) -> None:
    result = GovernedIntradaySourceCertificationEngine().run(
        _evidence(
            resolution=_resolution(),
            bars=_bars(),
            daily=_daily(),
        )
    )

    paths = export_intraday_source_certification(result, tmp_path)
    certificate = tmp_path / DSI013_SOURCE_CERTIFICATE
    payload = validate_intraday_source_certificate(certificate, require_ready=True)

    assert len(paths) == len(DSI013_SOURCE_ARTIFACTS) + 2
    assert payload["readiness_decision"] == (
        "READY_FOR_GOVERNED_INTRADAY_SOURCE_RESEARCH"
    )
    assert payload["summary"]["admitted_request_count"] == 1

    tampered = tmp_path / DSI013_SOURCE_ARTIFACTS["request_plan"]
    tampered.write_text(tampered.read_text(encoding="utf-8") + "tamper\n")
    with pytest.raises(
        IntradayExecutionError,
        match="DSI013_SOURCE_ARTIFACT_TAMPERED",
    ):
        validate_intraday_source_certificate(certificate)


def test_blocked_certificate_validates_without_require_ready(tmp_path: Path) -> None:
    result = GovernedIntradaySourceCertificationEngine().run(
        _evidence(resolution=_resolution(), daily=_daily())
    )
    export_intraday_source_certification(result, tmp_path)
    certificate = tmp_path / DSI013_SOURCE_CERTIFICATE

    payload = validate_intraday_source_certificate(certificate)
    assert payload["readiness_decision"] == "BLOCKED_BY_INTRADAY_SOURCE_UNAVAILABLE"
    with pytest.raises(
        IntradayExecutionError,
        match="DSI013_SOURCE_NOT_READY",
    ):
        validate_intraday_source_certificate(certificate, require_ready=True)
