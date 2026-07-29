from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb

from alpha.historical_truth.adjustment_replay_admission_continuity import (
    recompute_factor_validation,
    tier_a_quarantine_economic_weight,
)
from alpha.historical_truth.adjustment_replay_admission_continuity_validation import (
    _classify,
    _official_term_factor_matches,
)
from alpha.historical_truth.adjustment_replay_admission_models import (
    ValidationOutcome,
)


def _database(path: Path) -> None:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            "CREATE TABLE daily_candle("
            "trading_date DATE, exchange VARCHAR, symbol VARCHAR, series VARCHAR, "
            "isin VARCHAR, open_price DOUBLE, high_price DOUBLE, low_price DOUBLE, "
            "close_price DOUBLE, volume BIGINT)"
        )


def _insert_series(path: Path, isin: str, *, ex_open: float) -> None:
    start = date(2026, 1, 1)
    rows = []
    for offset in range(16):
        trading_date = start + timedelta(days=offset)
        close = 100.0
        open_price = ex_open if offset == 15 else 100.0
        rows.append(
            (
                trading_date,
                "nse",
                "TEST",
                "EQ",
                isin,
                open_price,
                max(open_price, close) + 1.0,
                min(open_price, close) - 1.0,
                open_price,
                1000,
            )
        )
    with duckdb.connect(str(path)) as connection:
        connection.executemany(
            "INSERT INTO daily_candle VALUES (?,?,?,?,?,?,?,?,?,?)", rows
        )


def _event(isin: str) -> dict[str, object]:
    return {
        "canonical_event_id": "event-1",
        "governed_identity_id": f"nse:isin:{isin}",
        "symbol": "TEST",
        "series_applicability": ["EQ"],
        "isin": isin,
        "action_type": "SPLIT",
        "effective_date": "2026-01-16",
    }


def test_recomputed_continuity_overrides_stale_legacy_metric(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    _insert_series(database, "INE000A01001", ex_open=50.0)

    cases, results, summary = recompute_factor_validation(
        database_path=database,
        events=(_event("INE000A01001"),),
        factors=(
            {
                "canonical_event_id": "event-1",
                "identity_key": "nse:isin:INE000A01001",
                "effective_date": "2026-01-16",
                "factor_state": "FACTOR_DERIVED_OFFICIAL_TERMS",
                "price_factor": 0.5,
            },
        ),
        legacy_continuity=(
            {
                "event_id": "event-1",
                "continuity_state": "FACTOR_LIKELY_INCORRECT",
                "raw_gap_atr": 3.0,
                "adjusted_gap_atr": 8.0,
            },
        ),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )

    assert len(cases) == 1
    assert results[0]["validation_outcome"] == (
        ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MARKET_GAP.value
    )
    assert results[0]["continuity_source"] == (
        "HTR010B_FACTOR_RECOMPUTED_FROM_CANONICAL_CANDLES"
    )
    assert summary["legacy_recomputed_state_disagreement_count"] == 1


def test_inverse_factor_is_diagnostic_not_autocorrection(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    _insert_series(database, "INE000A01001", ex_open=50.0)

    _, results, summary = recompute_factor_validation(
        database_path=database,
        events=(_event("INE000A01001"),),
        factors=(
            {
                "canonical_event_id": "event-1",
                "identity_key": "nse:isin:INE000A01001",
                "effective_date": "2026-01-16",
                "factor_state": "FACTOR_DERIVED_OFFICIAL_TERMS",
                "price_factor": 2.0,
            },
        ),
        legacy_continuity=(),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )

    assert (
        results[0]["validation_outcome"]
        == ValidationOutcome.IMPLEMENTATION_DEFECT.value
    )
    assert results[0]["implementation_defect_code"] == (
        "POSSIBLE_FACTOR_ORIENTATION_DEFECT"
    )
    assert results[0]["market_derived_factor_autocorrection"] is False
    assert summary["possible_factor_orientation_defect_count"] == 1


def test_composite_bonus_split_matches_product_of_official_terms() -> None:
    event = {
        "action_type": "BONUS",
        "ratio_numerator": 1.0,
        "ratio_denominator": 1.0,
        "old_face_value": 10.0,
        "new_face_value": 2.0,
    }

    assert _official_term_factor_matches(event, {"price_factor": 0.1}) is True
    assert _official_term_factor_matches(event, {"price_factor": 0.5}) is False


def test_exact_official_factor_across_stale_window_is_market_gap() -> None:
    result = _classify(
        {
            "action_type": "SPLIT",
            "factor_state": "FACTOR_DERIVED_OFFICIAL_TERMS",
            "price_factor": 0.2,
            "official_term_factor_matches": True,
            "reference_price_certified": False,
            "raw_gap_atr": 12.0,
            "adjusted_gap_atr": 16.0,
            "inverse_adjusted_gap_atr": 18.0,
            "governed_continuity_context": {
                "complete": True,
                "action_session_delay_market_sessions": 109,
                "pre_event_gap_market_sessions": 0,
            },
        }
    )

    assert result["validation_outcome"] == (
        ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MARKET_GAP.value
    )
    assert result["implementation_defect_code"] is None


def test_wrong_factor_remains_defect_across_stale_window() -> None:
    result = _classify(
        {
            "action_type": "BONUS",
            "factor_state": "FACTOR_DERIVED_OFFICIAL_TERMS",
            "price_factor": 0.4,
            "official_term_factor_matches": False,
            "reference_price_certified": False,
            "raw_gap_atr": 12.0,
            "adjusted_gap_atr": 16.0,
            "inverse_adjusted_gap_atr": 18.0,
            "governed_continuity_context": {
                "complete": True,
                "action_session_delay_market_sessions": 109,
                "pre_event_gap_market_sessions": 0,
            },
        }
    )

    assert result["validation_outcome"] == ValidationOutcome.IMPLEMENTATION_DEFECT.value


def _short_official_context_case(*, action_type: str = "BONUS") -> dict[str, object]:
    return {
        "action_type": action_type,
        "factor_state": "FACTOR_DERIVED_OFFICIAL_TERMS",
        "price_factor": 0.5,
        "official_term_factor_matches": True,
        "raw_gap_atr": None,
        "adjusted_gap_atr": None,
        "governed_continuity_context": {
            "decision": "INSUFFICIENT_ATR_HISTORY",
            "selected_prior_bars": [
                {
                    "source_sha256": "a" * 64,
                    "identity_state": "EXACT_ISIN_CANDLE",
                }
            ],
            "action_bar": {"source_sha256": "b" * 64},
            "rejected_bars": [],
        },
    }


def test_official_factor_with_genuine_short_history_is_terminal_and_admitted() -> None:
    result = _classify(_short_official_context_case())

    assert result["validation_outcome"] == (
        ValidationOutcome.FACTOR_CERTIFIED_OFFICIAL_TERMS_CONTINUITY_NOT_TESTABLE
    )
    assert result["admitted_to_replay"] is True
    assert result["requires_quarantine"] is False
    assert result["continuity_testable"] is False
    assert result["recomputed_continuity_state"] == (
        "OFFICIAL_FACTOR_CERTIFIED_CONTINUITY_NOT_TESTABLE"
    )
    assert result["replay_admission_basis"] == (
        "OFFICIAL_TERMS_WITH_NO_COMPLETE_ATR_WINDOW"
    )


def test_official_factor_with_zero_prior_sessions_is_terminal_and_admitted() -> None:
    case = _short_official_context_case()
    context = case["governed_continuity_context"]
    assert isinstance(context, dict)
    context["selected_prior_bars"] = []

    result = _classify(case)

    assert result["validation_outcome"] == (
        ValidationOutcome.FACTOR_CERTIFIED_OFFICIAL_TERMS_CONTINUITY_NOT_TESTABLE
    )
    assert result["continuity_testable"] is False


def test_short_history_exception_never_applies_to_rights() -> None:
    result = _classify(_short_official_context_case(action_type="RIGHTS"))

    assert result["validation_outcome"] == (
        ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE
    )
    assert result["admitted_to_replay"] is False


def test_short_history_with_rejected_identity_candidate_remains_insufficient() -> None:
    case = _short_official_context_case()
    context = case["governed_continuity_context"]
    assert isinstance(context, dict)
    context["rejected_bars"] = [{"reason": "EXPLICIT_ISIN_MISMATCH"}]

    result = _classify(case)

    assert result["validation_outcome"] == (
        ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE
    )
    assert result["admitted_to_replay"] is False


def test_weight_is_clipped_and_closed_to_tier_a(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    _database(database)
    _insert_series(database, "INE000A01001", ex_open=50.0)
    _insert_series(database, "INE000A01002", ex_open=100.0)

    population = {
        "by_identity": {
            "nse:isin:INE000A01001": {},
            "nse:isin:INE000A01002": {},
        },
        "observed_tier_a_candle_rows": 32,
        "observed_tier_a_identity_sessions": 32,
        "requested_window_fully_observed": True,
    }
    rows, summary = tier_a_quarantine_economic_weight(
        database_path=database,
        quarantine=(
            {
                "identity_key": "nse:isin:INE000A01001",
                "interval_start": "2025-01-01",
                "interval_end": "2027-01-01",
                "quarantine_reason": "TEST",
            },
            {
                "identity_key": "nse:isin:INE999A01001",
                "interval_start": "2026-01-01",
                "interval_end": "2026-01-31",
                "quarantine_reason": "OUTSIDE_TIER_A",
            },
        ),
        coverage=(
            {"identity_key": "nse:isin:INE000A01001"},
            {"identity_key": "nse:isin:INE000A01002"},
        ),
        population=population,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )

    assert len(rows) == 1
    assert rows[0]["affected_candle_rows"] == 16
    assert summary["pct_observed_tier_a_rows_quarantined"] == 50.0
    assert summary["pct_observed_tier_a_rows_quarantined"] <= 100.0
    assert summary["out_of_tier_a_evidence_identity_count"] == 1
    assert summary["quarantine_ranges_clipped_to_requested_window"] is True
