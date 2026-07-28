from __future__ import annotations

import os
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from alpha.historical_truth.adjustment_replay_admission_continuity import (
    recompute_factor_validation,
)
from alpha.historical_truth.adjustment_replay_admission_models import (
    ValidationOutcome,
)
from alpha.historical_truth.bridge_aware_continuity_artifacts import (
    BridgeAwareContinuityCertificationEngine,
)
from alpha.historical_truth.bridge_aware_continuity_context import (
    PRODUCTION_INFLUENCE,
    BridgeAwareContinuityContextProvider,
    ContinuityContextDecision,
    GovernedCandleIdentityState,
    RawCanonicalCandle,
)
from alpha.historical_truth.bridge_aware_factor_validation_repair import (
    _repair_case,
)
from alpha.historical_truth.factor_transformation_bridge_forensics import (
    _governed_selected_bridge,
)
from alpha.historical_truth.legacy_isin_reference_bridge import (
    LegacyIsinReferenceBridge,
)
from tests.historical_truth.legacy_bridge_test_support import (
    IDENTITY,
    ISIN,
    write_bridge_fixture,
)

EVENT_ID = "event-1"
FACTOR_ID = "factor-1"
SOURCE_SHA = "c" * 64
EFFECTIVE = date(2015, 1, 16)


def _database(path: Path) -> None:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            "CREATE TABLE daily_candle("
            "trading_date DATE, exchange VARCHAR, symbol VARCHAR, series VARCHAR, "
            "isin VARCHAR, open_price DOUBLE, high_price DOUBLE, low_price DOUBLE, "
            "close_price DOUBLE, volume BIGINT, source_sha256 VARCHAR)"
        )


def _insert(
    path: Path,
    *,
    count: int = 16,
    isin: str | None = None,
    symbol: str = "ALPHA",
    series: str = "EQ",
    source_sha256: str | None = SOURCE_SHA,
    action_open: float = 50.0,
) -> None:
    rows = []
    start = date(2015, 1, 1)
    for offset in range(count):
        session = start + timedelta(days=offset)
        open_price = action_open if session == EFFECTIVE else 100.0
        rows.append(
            (
                session,
                "NSE",
                symbol,
                series,
                isin,
                open_price,
                max(open_price, 100.0) + 1.0,
                min(open_price, 100.0) - 1.0,
                open_price if session == EFFECTIVE else 100.0,
                1_000,
                source_sha256,
            )
        )
    with duckdb.connect(str(path)) as connection:
        connection.executemany(
            "INSERT INTO daily_candle VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )


def _bridge(tmp_path: Path, **changes: object) -> LegacyIsinReferenceBridge:
    htr009a2, htr010a3 = write_bridge_fixture(tmp_path, **changes)
    return LegacyIsinReferenceBridge.from_fixture_output(
        htr009a2,
        htr010a3_output=htr010a3,
    )


def _case(event_id: str = EVENT_ID) -> dict[str, object]:
    return {
        "event_id": event_id,
        "factor_id": FACTOR_ID if event_id == EVENT_ID else f"factor-{event_id}",
        "identity_key": IDENTITY,
        "symbol": "ALPHA",
        "series": "EQ",
        "event_isin": ISIN,
        "effective_date": EFFECTIVE.isoformat(),
        "prior_candle_date": "2015-01-15",
        "prior_close": 100.0,
        "prior_candle_source_sha256": SOURCE_SHA,
        "bridge_decision": "CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE",
        "bridge_certified": True,
        "original_candle_isin_remained_missing": True,
        "final_validation_outcomes": ["FACTOR_INSUFFICIENT_EVIDENCE"],
    }


def _provider(
    tmp_path: Path,
    *,
    bridge_changes: dict[str, object] | None = None,
) -> BridgeAwareContinuityContextProvider:
    bridge = _bridge(tmp_path, **(bridge_changes or {}))
    cases = (_case(), *(_case(f"dummy-{index}") for index in range(17)))
    return BridgeAwareContinuityContextProvider.from_fixture(
        bridge=bridge,
        cases=cases,
    )


def _event() -> dict[str, object]:
    return {
        "canonical_event_id": EVENT_ID,
        "governed_identity_id": IDENTITY,
        "symbol": "ALPHA",
        "series_applicability": ["EQ"],
        "isin": ISIN,
        "action_type": "RIGHTS",
        "effective_date": EFFECTIVE.isoformat(),
    }


def _factor(
    provider: BridgeAwareContinuityContextProvider,
    **changes: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "factor_id": FACTOR_ID,
        "canonical_event_id": EVENT_ID,
        "identity_key": IDENTITY,
        "factor_state": "FACTOR_CERTIFIED_REFERENCE_PRICE",
        "price_factor": 0.5,
        "reference_price": 100.0,
        "reference_price_date": "2015-01-15",
        "reference_price_source_sha256": SOURCE_SHA,
        "reference_price_bridge_contract_version": (
            "HTR-010B1-LEGACY-ISIN-REFERENCE-BRIDGE-v1.0.0"
        ),
        "reference_price_bridge_source_contract_id": (
            provider.bridge.source_contract.contract_id
        ),
        "reference_price_bridge_source_report_sha256": (
            provider.bridge.source_report_sha256
        ),
    }
    payload.update(changes)
    return payload


def _context(
    path: Path,
    provider: BridgeAwareContinuityContextProvider,
    factor: dict[str, object] | None = None,
):
    with duckdb.connect(str(path), read_only=True) as connection:
        return provider.build(
            connection,
            event=_event(),
            factor=factor or _factor(provider),
            series="EQ",
            effective_date=EFFECTIVE,
        )


def _raw(
    *,
    isin: str | None = None,
    symbol: str = "ALPHA",
    series: str = "EQ",
    source_sha256: str | None = SOURCE_SHA,
    trading_date: date = date(2015, 1, 15),
) -> RawCanonicalCandle:
    return RawCanonicalCandle(
        trading_date=trading_date,
        symbol=symbol,
        series=series,
        isin=isin,
        open_price=100.0,
        high_price=101.0,
        low_price=99.0,
        close_price=100.0,
        volume=1_000,
        source_sha256=source_sha256,
    )


def test_existing_exact_isin_continuity_is_unchanged_without_provider(
    tmp_path: Path,
) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    _insert(database, isin=ISIN)
    factor = {
        "canonical_event_id": EVENT_ID,
        "identity_key": IDENTITY,
        "factor_state": "FACTOR_DERIVED_OFFICIAL_TERMS",
        "price_factor": 0.5,
    }

    _, baseline, _ = recompute_factor_validation(
        database_path=database,
        events=(_event(),),
        factors=(factor,),
        legacy_continuity=(),
        start_date=date(2015, 1, 1),
        end_date=date(2015, 1, 31),
    )
    _, repeated, _ = recompute_factor_validation(
        database_path=database,
        events=(_event(),),
        factors=(factor,),
        legacy_continuity=(),
        start_date=date(2015, 1, 1),
        end_date=date(2015, 1, 31),
        continuity_context_provider=None,
    )

    assert baseline == repeated


def test_certified_missing_isin_window_and_action_are_admitted(
    tmp_path: Path,
) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    _insert(database)
    provider = _provider(tmp_path / "evidence")

    context = _context(database, provider)

    assert context.complete is True
    assert len(context.prior_window.selected_prior_bars) == 15
    assert len(context.prior_window.atr_bars) == 14
    assert context.action_bar is not None
    assert all(
        row.identity_state is GovernedCandleIdentityState.CERTIFIED_DATED_BRIDGE_CANDLE
        for row in (
            *context.prior_window.selected_prior_bars,
            context.action_bar,
        )
    )


@pytest.mark.parametrize(
    ("raw", "bridge_changes", "expected"),
    [
        (
            _raw(trading_date=date(2016, 1, 1)),
            {},
            GovernedCandleIdentityState.DATE_OUTSIDE_CERTIFIED_INTERVAL,
        ),
        (
            _raw(isin="INE999A01010"),
            {},
            GovernedCandleIdentityState.EXPLICIT_ISIN_MISMATCH,
        ),
        (
            _raw(symbol="OTHER"),
            {},
            GovernedCandleIdentityState.SYMBOL_CONFLICT,
        ),
        (
            _raw(series="BE"),
            {},
            GovernedCandleIdentityState.SERIES_CONFLICT,
        ),
        (
            _raw(),
            {"overlap": True},
            GovernedCandleIdentityState.IDENTITY_CONFLICT,
        ),
        (
            _raw(),
            {"symbol_reuse": True},
            GovernedCandleIdentityState.IDENTITY_CONFLICT,
        ),
        (
            _raw(),
            {"symbol_change": True},
            GovernedCandleIdentityState.IDENTITY_CONFLICT,
        ),
        (
            _raw(trading_date=date(2015, 1, 2)),
            {"series_transition": True},
            GovernedCandleIdentityState.IDENTITY_CONFLICT,
        ),
        (
            _raw(source_sha256=None),
            {},
            GovernedCandleIdentityState.SOURCE_HASH_MISSING,
        ),
    ],
)
def test_candle_identity_rejections_fail_closed(
    tmp_path: Path,
    raw: RawCanonicalCandle,
    bridge_changes: dict[str, object],
    expected: GovernedCandleIdentityState,
) -> None:
    provider = _provider(tmp_path, bridge_changes=bridge_changes)

    accepted, rejected = provider.govern_candle(
        raw,
        identity=IDENTITY,
        symbol="ALPHA",
        series="EQ",
        isin=ISIN,
        role="PRIOR",
    )

    assert accepted is None
    assert rejected is not None
    assert rejected.reason is expected


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (
            {"reference_price_date": "2015-01-14"},
            ContinuityContextDecision.REFERENCE_SESSION_MISMATCH,
        ),
        (
            {"reference_price": 99.0},
            ContinuityContextDecision.REFERENCE_PRICE_MISMATCH,
        ),
        (
            {"reference_price_source_sha256": "d" * 64},
            ContinuityContextDecision.REFERENCE_SOURCE_HASH_MISMATCH,
        ),
        (
            {"reference_price_bridge_source_contract_id": "wrong"},
            None,
        ),
    ],
)
def test_reference_provenance_mismatches_fail_closed(
    tmp_path: Path,
    changes: dict[str, object],
    expected: ContinuityContextDecision | None,
) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    _insert(database)
    provider = _provider(tmp_path / "evidence")
    factor = _factor(provider, **changes)

    if expected is None:
        with pytest.raises(ValueError, match="source contract mismatch"):
            _context(database, provider, factor)
    else:
        assert _context(database, provider, factor).decision is expected


def test_mixed_exact_and_bridged_atr_history_is_supported(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    _insert(database)
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "UPDATE daily_candle SET isin=? WHERE trading_date<?",
            [ISIN, date(2015, 1, 8)],
        )
    provider = _provider(tmp_path / "evidence")

    context = _context(database, provider)
    states = {row.identity_state for row in context.prior_window.atr_bars}

    assert context.complete is True
    assert states == {
        GovernedCandleIdentityState.EXACT_ISIN_CANDLE,
        GovernedCandleIdentityState.CERTIFIED_DATED_BRIDGE_CANDLE,
    }


def test_identity_mismatch_and_non_positive_price_fail_closed(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)
    accepted, rejected = provider.govern_candle(
        _raw(),
        identity="nse:isin:INE999A01010",
        symbol="ALPHA",
        series="EQ",
        isin=ISIN,
        role="PRIOR",
    )
    invalid_price = replace(_raw(), close_price=0.0)
    price_accepted, price_rejected = provider.govern_candle(
        invalid_price,
        identity=IDENTITY,
        symbol="ALPHA",
        series="EQ",
        isin=ISIN,
        role="PRIOR",
    )

    assert accepted is None
    assert rejected is not None
    assert rejected.reason is GovernedCandleIdentityState.IDENTITY_CONFLICT
    assert price_accepted is None
    assert price_rejected is not None
    assert price_rejected.reason is GovernedCandleIdentityState.NON_POSITIVE_PRICE


def test_one_bridged_reference_does_not_certify_adjacent_bars(
    tmp_path: Path,
) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    _insert(database, count=15)
    provider = _provider(
        tmp_path / "evidence",
        bridge_changes={"valid_from": "2015-01-15"},
    )

    context = _context(database, provider)

    assert context.decision is ContinuityContextDecision.ACTION_SESSION_MISSING
    assert len(context.prior_window.selected_prior_bars) == 1
    assert context.rejected_bars


def test_duplicate_candle_date_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    _insert(database)
    with duckdb.connect(str(database)) as connection:
        row = connection.execute(
            "SELECT * FROM daily_candle WHERE trading_date='2015-01-15'"
        ).fetchone()
        connection.execute(
            "INSERT INTO daily_candle VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            row,
        )
    provider = _provider(tmp_path / "evidence")

    context = _context(database, provider)

    assert context.decision is ContinuityContextDecision.DUPLICATE_CANONICAL_CANDLE
    assert any(
        row.reason is GovernedCandleIdentityState.DUPLICATE_CANONICAL_CANDLE
        for row in context.rejected_bars
    )


def test_first_valid_action_session_is_selected_without_performance_search(
    tmp_path: Path,
) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    _insert(database, source_sha256=SOURCE_SHA)
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "UPDATE daily_candle SET source_sha256=NULL WHERE trading_date='2015-01-16'"
        )
        connection.execute(
            "INSERT INTO daily_candle VALUES "
            "('2015-01-17','NSE','ALPHA','EQ',NULL,50,101,49,50,1000,?)",
            [SOURCE_SHA],
        )
        connection.execute(
            "INSERT INTO daily_candle VALUES "
            "('2015-01-18','NSE','ALPHA','EQ',NULL,100,101,99,100,1000,?)",
            [SOURCE_SHA],
        )
    provider = _provider(tmp_path / "evidence")

    context = _context(database, provider)

    assert context.first_candidate_action_date == date(2015, 1, 16)
    assert context.action_bar is not None
    assert context.action_bar.candle.trading_date == date(2015, 1, 17)
    assert context.metrics.action_open == 50.0


def test_future_and_post_event_bars_never_enter_atr(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    _insert(database, count=20)
    provider = _provider(tmp_path / "evidence")

    context = _context(database, provider)

    assert all(
        row.candle.trading_date < EFFECTIVE for row in context.prior_window.atr_bars
    )
    assert context.action_bar is not None
    assert context.action_bar.candle.trading_date == EFFECTIVE


def test_insufficient_atr_history_remains_insufficient(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    _insert(database)
    with duckdb.connect(str(database)) as connection:
        connection.execute("DELETE FROM daily_candle WHERE trading_date<'2015-01-15'")
    provider = _provider(tmp_path / "evidence")

    context = _context(database, provider)

    assert context.decision is ContinuityContextDecision.INSUFFICIENT_ATR_HISTORY


@pytest.mark.parametrize(
    ("action_open", "factor", "expected"),
    [
        (
            50.0,
            0.5,
            ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MARKET_GAP.value,
        ),
        (
            50.0,
            2.0,
            ValidationOutcome.IMPLEMENTATION_DEFECT.value,
        ),
        (
            80.0,
            0.5,
            ValidationOutcome.IMPLEMENTATION_DEFECT.value,
        ),
    ],
)
def test_complete_context_uses_existing_validation_thresholds(
    tmp_path: Path,
    action_open: float,
    factor: float,
    expected: str,
) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    _insert(database, action_open=action_open)
    provider = _provider(tmp_path / "evidence")
    factor_row = _factor(provider, price_factor=factor)

    _, results, _ = recompute_factor_validation(
        database_path=database,
        events=(_event(),),
        factors=(factor_row,),
        legacy_continuity=(),
        start_date=date(2015, 1, 1),
        end_date=date(2015, 1, 31),
        continuity_context_provider=provider,
    )

    assert results[0]["validation_outcome"] == expected
    assert results[0]["price_factor"] == factor


def test_rejected_bars_do_not_influence_atr(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    _insert(database)
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "INSERT INTO daily_candle VALUES "
            "('2014-12-31','NSE','ALPHA','EQ','INE999A01010',"
            "1000,1200,1,1000,1000,?)",
            [SOURCE_SHA],
        )
    provider = _provider(tmp_path / "evidence")

    context = _context(database, provider)

    assert context.metrics.atr_before == 2.0
    assert any(
        row.reason is GovernedCandleIdentityState.EXPLICIT_ISIN_MISMATCH
        for row in context.rejected_bars
    )


def test_canonical_candles_and_factor_are_not_mutated(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    _insert(database)
    provider = _provider(tmp_path / "evidence")
    factor = _factor(provider)
    with duckdb.connect(str(database), read_only=True) as connection:
        before = connection.execute(
            "SELECT * FROM daily_candle ORDER BY trading_date"
        ).fetchall()
    factor_before = dict(factor)

    _context(database, provider, factor)

    with duckdb.connect(str(database), read_only=True) as connection:
        after = connection.execute(
            "SELECT * FROM daily_candle ORDER BY trading_date"
        ).fetchall()
    assert before == after
    assert factor == factor_before


def test_downstream_repair_retains_governed_context_outcome() -> None:
    context = {
        "context_id": "context-1",
        "selected_prior_bars": [{"trading_date": "2015-01-15"}],
        "action_bar": {"trading_date": "2015-01-16"},
        "metrics": {
            "atr_before": 2.0,
            "raw_gap_atr": 1.0,
            "adjusted_gap_atr": 3.0,
        },
    }
    selected = _governed_selected_bridge(
        {"governed_continuity_context_id": "context-1"},
        context,
    )
    row = {
        "bridge_type": "GOVERNED_DATED_IDENTITY_CONTEXT",
        "bridge_classification": "GOVERNED_CONTINUITY_CONTEXT_RETAINED",
        "governed_continuity_context_id": "context-1",
        "governed_continuity_validation_outcome": "IMPLEMENTATION_DEFECT",
        "bridge_raw_gap_atr": 1.0,
        "bridge_adjusted_gap_atr": 3.0,
    }

    repaired = _repair_case(row, {"factor_count": 1})

    assert selected["governed_continuity_context_id"] == "context-1"
    assert repaired["proposed_validation_outcome"] == "IMPLEMENTATION_DEFECT"
    assert repaired["factor_quality_confirmed"] is False


def test_context_is_deterministic(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    _insert(database)
    provider = _provider(tmp_path / "evidence")

    first = _context(database, provider).as_dict()
    second = _context(database, provider).as_dict()

    assert first == second


def test_production_influence_is_false() -> None:
    assert PRODUCTION_INFLUENCE is False


def test_genuine_signed_population_acceptance_when_configured() -> None:
    root_value = os.environ.get("DSI010B2_ACCEPTANCE_ROOT")
    if not root_value:
        pytest.skip("genuine signed DSI-010B2 acceptance root is not configured")
    root = Path(root_value)
    report = BridgeAwareContinuityCertificationEngine().run(
        database_path=root / "work/alpha_data/warehouse/historical_truth.duckdb",
        htr009a2_output=root / "artifacts/htr009a2_event_sourced_universe",
        htr010a3_output=root / "artifacts/htr010a3_tier_a_foundation_readiness",
        htr010b_output=root / "artifacts/htr010b_complete_corporate_action_dataset",
        htr010b1c_output=root / "artifacts/htr010b1_adjustment_replay_admission_b2",
        htr010b1e2_output=root
        / "artifacts/htr010b1e2_final_admission_state_propagation_b2",
        dsi010b1_output=root / "artifacts/dsi010b1_legacy_rights_reference_bridge",
    )

    assert report.summary["event_count"] == 18
    assert (
        sum(
            report.summary[key]
            for key in (
                "K_confirmed_correct",
                "D_implementation_defect",
                "U_insufficient_evidence",
                "C_conflicting_official_evidence",
            )
        )
        == 18
    )
    assert report.production_influence is False
