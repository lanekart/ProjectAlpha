from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import duckdb

from alpha.__main__ import _historical_truth_app
from alpha.historical_truth.factor_transformation_forensics import (
    FactorTransformationForensicsEngine,
    _classify,
    _official_term_factor,
)


def _database(path: Path) -> Path:
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            """
            CREATE TABLE daily_candle(
                trading_date DATE,
                exchange VARCHAR,
                symbol VARCHAR,
                series VARCHAR,
                isin VARCHAR,
                open_price DOUBLE,
                high_price DOUBLE,
                low_price DOUBLE,
                close_price DOUBLE,
                volume DOUBLE
            )
            """
        )
        start = date(2026, 1, 1)
        rows = []
        for offset in range(15):
            trading_date = start + timedelta(days=offset)
            rows.append(
                (
                    trading_date,
                    "nse",
                    "ALPHA",
                    "EQ",
                    "INE000000001",
                    100.0,
                    101.0,
                    99.0,
                    100.0,
                    10000.0,
                )
            )
        rows.append(
            (
                date(2026, 1, 20),
                "nse",
                "ALPHA",
                "EQ",
                "INE000000001",
                200.0,
                202.0,
                198.0,
                200.0,
                20000.0,
            )
        )
        connection.executemany(
            "INSERT INTO daily_candle VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    finally:
        connection.close()
    return path


def _inputs(root: Path) -> tuple[Path, Path]:
    htr010b = root / "htr010b"
    htr010b1c = root / "htr010b1c"
    htr010b.mkdir()
    htr010b1c.mkdir()
    event_id = "event-1"
    result = {
        "event_id": event_id,
        "identity_key": "nse:isin:INE000000001",
        "symbol": "ALPHA",
        "series": "EQ",
        "isin": "INE000000001",
        "action_type": "SPLIT",
        "effective_date": "2026-01-20",
        "factor_state": "FACTOR_DERIVED_OFFICIAL_TERMS",
        "price_factor": 0.5,
        "raw_gap_atr": 50.0,
        "adjusted_gap_atr": 150.0,
        "validation_outcome": "IMPLEMENTATION_DEFECT",
        "residual_attribution": "POSSIBLE_FACTOR_ORIENTATION_DEFECT",
    }
    event = {
        "canonical_event_id": event_id,
        "governed_identity_id": "nse:isin:INE000000001",
        "symbol": "ALPHA",
        "series_applicability": ["EQ"],
        "isin": "INE000000001",
        "action_type": "SPLIT",
        "raw_action_text": "Stock split from face value 10 to 5",
        "announcement_date": "2025-12-20",
        "record_date": "2026-01-21",
        "ex_date": "2026-01-20",
        "effective_date": "2026-01-20",
        "old_face_value": 10.0,
        "new_face_value": 5.0,
        "ratio_numerator": 2.0,
        "ratio_denominator": 1.0,
    }
    factor = {
        "factor_id": "factor-1",
        "canonical_event_id": event_id,
        "identity_key": "nse:isin:INE000000001",
        "effective_date": "2026-01-20",
        "price_factor": 0.5,
        "quantity_factor": 2.0,
        "factor_state": "FACTOR_DERIVED_OFFICIAL_TERMS",
    }
    cumulative = {
        "identity_key": "nse:isin:INE000000001",
        "effective_date": "2026-01-20",
        "backward_cumulative_price_factor": 0.5,
        "forward_cumulative_price_factor": 2.0,
        "cumulative_quantity_factor": 2.0,
        "factor_ids": ["factor-1"],
    }
    lineage = {
        "canonical_event_id": event_id,
        "source_ids": ["official-source"],
    }
    payloads = {
        htr010b1c / "htr010b1_factor_validation_results.json": [result],
        htr010b / "htr010b_canonical_events.json": [event],
        htr010b / "htr010b_adjustment_factors.json": [factor],
        htr010b / "htr010b_cumulative_factors.json": [cumulative],
        htr010b / "htr010b_duplicate_groups.json": [],
        htr010b / "htr010b_event_lineage.json": [lineage],
    }
    for path, payload in payloads.items():
        path.write_text(json.dumps(payload), encoding="utf-8")
    return htr010b, htr010b1c


def test_forensics_identifies_orientation_without_mutating_factor(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path / "truth.duckdb")
    htr010b, htr010b1c = _inputs(tmp_path)

    report = FactorTransformationForensicsEngine().run(
        database_path=database,
        htr010b_output=htr010b,
        htr010b1c_output=htr010b1c,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 20),
    )

    assert report["case_count"] == 1
    assert report["orientation_candidate_count"] == 1
    case = report["cases"][0]
    assert case["forensic_classification"] == "FACTOR_ORIENTATION_CONVENTION_MISMATCH"
    assert case["official_price_factor"] == 0.5
    assert case["inverse_factor_diagnostic"] == 2.0
    assert case["official_factor_retained"] is True
    assert case["market_derived_factor_autocorrection"] is False
    assert case["admitted_to_replay"] is False


def test_forensic_exports_are_deterministic(tmp_path: Path) -> None:
    database = _database(tmp_path / "truth.duckdb")
    htr010b, htr010b1c = _inputs(tmp_path)
    engine = FactorTransformationForensicsEngine()
    first = engine.run(
        database_path=database,
        htr010b_output=htr010b,
        htr010b1c_output=htr010b1c,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 20),
    )
    second = engine.run(
        database_path=database,
        htr010b_output=htr010b,
        htr010b1c_output=htr010b1c,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 20),
    )

    assert first == second
    assert first["report_sha256"] == second["report_sha256"]
    paths = engine.export(first, tmp_path / "output")
    assert len(paths) == 4
    assert all(path.exists() for path in paths)


def test_official_term_factor_arithmetic() -> None:
    split, split_formula = _official_term_factor(
        {"old_face_value": 10.0, "new_face_value": 2.0},
        "SPLIT",
    )
    bonus, bonus_formula = _official_term_factor(
        {"ratio_numerator": 1.0, "ratio_denominator": 2.0},
        "BONUS",
    )

    assert split == 0.2
    assert split_formula == "new_face_value / old_face_value"
    assert bonus == 2.0 / 3.0
    assert bonus_formula == (
        "ratio_denominator / (ratio_numerator + ratio_denominator)"
    )


def test_series_ambiguity_remains_quarantined() -> None:
    classification, recommendation, _ = _classify(
        result={},
        action_type="SPLIT",
        official_factor=0.5,
        term_factor=0.5,
        term_match=True,
        selected_series=None,
        selected_metrics=None,
        best_series={"series": "EQ", "open_adjusted_gap_atr": 0.5},
        close_basis=None,
        best_inverse=None,
        best_date=None,
        effective=date(2026, 1, 20),
        best_same_day=None,
        same_day_factor_count=1,
    )

    assert classification == "SERIES_SELECTION_AMBIGUITY"
    assert recommendation == "CERTIFY_SINGLE_EVENT_SERIES_BEFORE_FACTOR_VALIDATION"


def test_forensic_command_registration_is_idempotent() -> None:
    first = _historical_truth_app()
    second = _historical_truth_app()
    first_names = [command.name for command in first.registered_commands]
    second_names = [command.name for command in second.registered_commands]

    assert first_names.count("factor-transformation-forensics") == 1
    assert second_names.count("factor-transformation-forensics") == 1
