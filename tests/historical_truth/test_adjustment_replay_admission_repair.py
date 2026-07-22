from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb
import pytest

from alpha.historical_truth.adjustment_replay_admission_models import (
    AdmissionState,
    ValidationOutcome,
)
from alpha.historical_truth.adjustment_replay_admission_repair import (
    AdjustmentReplayAdmissionRepairEngine,
    HTR010BInputAdapter,
    InputContractError,
    classify_factor_case_repaired,
    segmented_replay_admission_intervals,
    session_based_lookback_safety,
)

IDENTITY_A = "nse:isin:INE000A01001"
IDENTITY_B = "nse:isin:INE000B01001"


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")


def _artifacts(root: Path, *, missing_summary_rows: bool = False) -> tuple[Path, Path]:
    htr010a3 = root / "htr010a3"
    htr010b = root / "htr010b"
    joins = [
        {
            "identity_key": IDENTITY_A,
            "symbol": "ALPHA",
            "admitted_to_certified_join": True,
        },
        {
            "identity_key": IDENTITY_B,
            "symbol": "BETA",
            "admitted_to_certified_join": True,
        },
    ]
    coverage = [
        {"identity_key": IDENTITY_A, "symbol": "ALPHA", "isin": "INE000A01001"},
        {"identity_key": IDENTITY_B, "symbol": "BETA", "isin": "INE000B01001"},
    ]
    events = [
        {
            "canonical_event_id": "event:beta",
            "governed_identity_id": IDENTITY_B,
            "symbol": "BETA",
            "series": "EQ",
            "isin": "INE000B01001",
            "action_type": "SPLIT",
            "effective_date": "2020-01-03",
            "ex_date": "2020-01-03",
            "series_applicability": ["EQ"],
            "source_ids": ["official:test"],
        }
    ]
    factors = [
        {
            "factor_id": "factor:beta",
            "canonical_event_id": "event:beta",
            "identity_key": IDENTITY_B,
            "effective_date": "2020-01-03",
            "factor_state": "FACTOR_DERIVED_OFFICIAL_TERMS",
            "price_factor": 0.5,
            "quantity_factor": 2.0,
        }
    ]
    continuity = [
        {
            "action_id": "event:beta",
            "identity_key": IDENTITY_B,
            "continuity_state": "FACTOR_LIKELY_INCORRECT",
            "raw_gap_atr": 1.0,
            "adjusted_gap_atr": 6.0,
            "factor_plausible": False,
        }
    ]
    summaries = [
        {
            "identity_key": IDENTITY_A,
            "symbol": "ALPHA",
            "raw_rows": 5,
            "adjusted_rows": 0,
            "price_basis_state": "RAW_NO_ACTION_EXPOSURE",
        },
        {
            "identity_key": IDENTITY_B,
            "symbol": "BETA",
            **({} if missing_summary_rows else {"raw_rows": 5}),
            "adjusted_rows": 5,
            "price_basis_state": "BACKWARD_ADJUSTED_CERTIFIED",
        },
    ]
    basis = [
        {
            "identity_key": IDENTITY_A,
            "valid_from": "2020-01-01",
            "valid_to": "2020-01-05",
            "price_basis_state": "RAW_NO_ACTION_EXPOSURE",
            "action_ids": [],
        },
        {
            "identity_key": IDENTITY_B,
            "valid_from": "2020-01-01",
            "valid_to": "2020-01-05",
            "price_basis_state": "BACKWARD_ADJUSTED_CERTIFIED",
            "action_ids": ["event:beta"],
        },
    ]
    _write(htr010a3 / "htr010a3_corporate_action_join_readiness.json", joins)
    _write(htr010b / "htr010b_canonical_events.json", events)
    _write(htr010b / "htr010b_adjustment_factors.json", factors)
    _write(htr010b / "htr010b_price_continuity.json", continuity)
    _write(htr010b / "htr010b_price_basis_intervals.json", basis)
    _write(htr010b / "htr010b_adjusted_candle_summary.json", summaries)
    _write(htr010b / "htr010b_identity_coverage_matrix.json", coverage)
    _write(htr010b / "htr010b_identity_transitions.json", [])
    return htr010a3, htr010b


def _database(path: Path) -> Path:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            "CREATE TABLE daily_candle("
            "trading_date DATE, exchange VARCHAR, symbol VARCHAR, series VARCHAR, "
            "isin VARCHAR, open_price DOUBLE, high_price DOUBLE, low_price DOUBLE, "
            "close_price DOUBLE, volume BIGINT, source_sha256 VARCHAR)"
        )
        rows = []
        for day in range(1, 6):
            trading_date = date(2020, 1, day)
            rows.extend(
                [
                    (
                        trading_date,
                        "nse",
                        "ALPHA",
                        "EQ",
                        "INE000A01001",
                        10.0,
                        11.0,
                        9.0,
                        10.0,
                        100,
                        "a",
                    ),
                    (
                        trading_date,
                        "nse",
                        "BETA",
                        "EQ",
                        "INE000B01001",
                        20.0,
                        21.0,
                        19.0,
                        20.0,
                        100,
                        "b",
                    ),
                ]
            )
        connection.executemany("INSERT INTO daily_candle VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    return path


def test_adapter_repairs_htr010b_aliases(tmp_path: Path) -> None:
    htr010a3, htr010b = _artifacts(tmp_path)

    result = HTR010BInputAdapter().load(htr010b, htr010a3)

    assert result["summaries"][0]["raw_row_count"] == 5
    assert result["summaries"][0]["adjusted_row_count"] == 0
    assert result["basis"][0]["interval_start"] == "2020-01-01"
    assert result["basis"][0]["interval_end"] == "2020-01-05"
    assert result["continuity"][0]["event_id"] == "event:beta"
    assert result["diagnostics"]["state"] == "INPUT_CONTRACT_VALID"
    assert result["diagnostics"]["alias_applications"]


def test_adapter_fails_closed_when_required_alias_is_absent(tmp_path: Path) -> None:
    htr010a3, htr010b = _artifacts(tmp_path, missing_summary_rows=True)

    with pytest.raises(InputContractError, match="SUMMARIES_MISSING_FIELDS"):
        HTR010BInputAdapter().load(htr010b, htr010a3)


def test_worsened_adjusted_atr_is_implementation_defect() -> None:
    result = classify_factor_case_repaired(
        {
            "event_id": "event:one",
            "identity_key": IDENTITY_A,
            "factor_state": "FACTOR_DERIVED_OFFICIAL_TERMS",
            "raw_gap_atr": 1.0,
            "adjusted_gap_atr": 6.0,
        }
    )

    assert result["validation_outcome"] == ValidationOutcome.IMPLEMENTATION_DEFECT.value
    assert result["requires_quarantine"] is True


def test_intervals_are_segmented_at_observed_sessions() -> None:
    sessions = tuple(date(2020, 1, day) for day in range(1, 6))
    coverage = ({"identity_key": IDENTITY_A, "symbol": "ALPHA"},)
    factors = (
        {
            "factor_id": "factor:one",
            "identity_key": IDENTITY_A,
            "effective_date": "2020-01-03",
            "factor_state": "FACTOR_UNKNOWN_MISSING_TERMS",
        },
    )

    rows = segmented_replay_admission_intervals(
        coverage=coverage,
        factors=factors,
        sessions=sessions,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 5),
    )

    assert [(row["start_date"], row["end_date"]) for row in rows] == [
        ("2020-01-01", "2020-01-02"),
        ("2020-01-03", "2020-01-05"),
    ]
    assert rows[0]["admission_state"] == AdmissionState.FACTOR_UNKNOWN_QUARANTINED.value
    assert rows[1]["admission_state"] == AdmissionState.RAW_REPLAY_CERTIFIED_POST_EVENT_SEGMENT.value
    assert rows[1]["reset_required"] is True


def test_lookback_uses_exchange_sessions_not_calendar_approximation() -> None:
    sessions = tuple(date(2020, 1, day) for day in (1, 2, 3, 6, 7))
    intervals = (
        {
            "identity_key": IDENTITY_A,
            "admission_interval_id": "interval:one",
            "start_date": "2020-01-03",
            "end_date": "2020-01-07",
            "admission_state": AdmissionState.RAW_REPLAY_CERTIFIED_POST_EVENT_SEGMENT.value,
            "reset_required": True,
        },
    )

    rows = session_based_lookback_safety(intervals, sessions, (2,))

    assert rows[0]["earliest_safe_date"] == "2020-01-06"
    assert rows[0]["calendar_day_approximation"] is False


def test_engine_measures_nonzero_weight_and_fails_readiness_closed(tmp_path: Path) -> None:
    htr010a3, htr010b = _artifacts(tmp_path)
    database = _database(tmp_path / "truth.duckdb")

    report = AdjustmentReplayAdmissionRepairEngine().run(
        database_path=database,
        htr010a3_output=htr010a3,
        htr010b_output=htr010b,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 5),
    )

    assert report.contract_version == "HTR-010B1A-v1.0.0"
    assert report.input_contract_diagnostics["state"] == "INPUT_CONTRACT_VALID"
    assert report.population_reconciliation["observed_tier_a_candle_rows"] == 10
    assert report.quarantine_population_reconciliation[
        "observed_quarantined_candle_rows"
    ] == 1
    assert report.quarantine_population_reconciliation[
        "pct_observed_tier_a_rows_quarantined"
    ] == pytest.approx(10.0)
    assert len(report.replay_admission_intervals) == 3
    assert report.replay_readiness["state"] == "NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION"
    assert "FACTOR_TRANSFORMATION_IMPLEMENTATION_DEFECTS" in report.replay_readiness[
        "blockers"
    ]
    assert report.replay_readiness["calendar_day_lookback_approximation"] is False
