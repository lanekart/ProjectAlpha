from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from alpha.__main__ import _historical_truth_app
from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.factor_transformation_bridge_forensics import (
    FactorTransformationBridgeForensicsEngine,
)


def _seed(
    warehouse: CanonicalPointInTimeWarehouse,
    rows: tuple[tuple[date, str, str, str, float, float, float, float, int], ...],
) -> None:
    warehouse.initialise()
    with warehouse._connect() as connection:
        connection.executemany(
            """
            INSERT OR REPLACE INTO daily_candle VALUES (
                ?, 'nse', ?, ?, ?, ?, ?, ?, ?, ?, 'fixture-sha'
            )
            """,
            rows,
        )


def _write_inputs(
    root: Path,
    cases: list[dict[str, object]],
    transitions: list[dict[str, object]],
) -> tuple[Path, Path]:
    b1d = root / "b1d"
    b = root / "b"
    b1d.mkdir()
    b.mkdir()
    (b1d / "htr010b1d_factor_transformation_cases.json").write_text(
        json.dumps(cases, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (b / "htr010b_identity_transitions.json").write_text(
        json.dumps(transitions, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return b, b1d


def _case(
    *,
    event_id: str,
    identity: str,
    symbol: str,
    isin: str,
    effective: str,
) -> dict[str, object]:
    return {
        "case_id": f"case:{event_id}",
        "event_id": event_id,
        "identity_key": identity,
        "symbol": symbol,
        "isin": isin,
        "action_type": "SPLIT",
        "effective_date": effective,
        "official_price_factor": 0.5,
        "forensic_classification": "UNRESOLVED_TRANSFORMATION_FORENSICS",
        "reported_adjusted_gap_atr": 3.0,
        "forensic_evidence": {"official_gap": None, "best_series_gap": None},
    }


def test_cross_series_pairing_is_classified_without_factor_mutation(
    tmp_path: Path,
) -> None:
    warehouse = CanonicalPointInTimeWarehouse(tmp_path / "truth.duckdb")
    _seed(
        warehouse,
        (
            (
                date(2025, 12, 30),
                "ALPHA",
                "BE",
                "INE000000001",
                100,
                105,
                95,
                100,
                1000,
            ),
            (date(2026, 1, 2), "ALPHA", "BE", "INE000000001", 102, 108, 98, 104, 1000),
            (date(2026, 1, 5), "ALPHA", "EQ", "INE000000001", 52, 55, 50, 53, 2000),
        ),
    )
    b, b1d = _write_inputs(
        tmp_path,
        [
            _case(
                event_id="event-cross-series",
                identity="nse:isin:INE000000001",
                symbol="ALPHA",
                isin="INE000000001",
                effective="2026-01-05",
            )
        ],
        [],
    )

    report = FactorTransformationBridgeForensicsEngine().run(
        database_path=tmp_path / "truth.duckdb",
        htr010b_output=b,
        htr010b1d_output=b1d,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )

    case = report["cases"][0]
    assert case["bridge_classification"] == "CROSS_SERIES_PAIRING_ARTIFACT"
    assert case["prior_series"] == "BE"
    assert case["current_series"] == "EQ"
    assert case["official_factor_retained"] is True
    assert case["admitted_to_replay"] is False


def test_governed_cross_isin_bridge_is_identified(tmp_path: Path) -> None:
    warehouse = CanonicalPointInTimeWarehouse(tmp_path / "truth.duckdb")
    _seed(
        warehouse,
        (
            (date(2025, 12, 30), "BETA", "EQ", "INE000000002", 100, 105, 95, 100, 1000),
            (date(2026, 1, 2), "BETA", "EQ", "INE000000002", 102, 108, 98, 104, 1000),
            (date(2026, 1, 5), "BETA", "EQ", "INE000000003", 52, 55, 50, 53, 2000),
        ),
    )
    transition = {
        "transition_id": "transition-1",
        "predecessor_identity": "nse:isin:INE000000002",
        "successor_identity": "nse:isin:INE000000003",
        "old_symbol": "BETA",
        "new_symbol": "BETA",
        "old_isin": "INE000000002",
        "new_isin": "INE000000003",
        "effective_date": "2026-01-05",
        "histories_may_be_linked": True,
        "price_comparison_valid": True,
        "new_identity_required": True,
    }
    b, b1d = _write_inputs(
        tmp_path,
        [
            _case(
                event_id="event-cross-isin",
                identity="nse:isin:INE000000003",
                symbol="BETA",
                isin="INE000000003",
                effective="2026-01-05",
            )
        ],
        [transition],
    )

    report = FactorTransformationBridgeForensicsEngine().run(
        database_path=tmp_path / "truth.duckdb",
        htr010b_output=b,
        htr010b1d_output=b1d,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )

    case = report["cases"][0]
    assert case["bridge_classification"] == "GOVERNED_CROSS_ISIN_BRIDGE_AVAILABLE"
    assert case["prior_isin"] == "INE000000002"
    assert case["current_isin"] == "INE000000003"
    assert case["selected_bridge"]["transition_evidence_available"] is True


def test_noncomparable_identity_transition_remains_quarantined(tmp_path: Path) -> None:
    warehouse = CanonicalPointInTimeWarehouse(tmp_path / "truth.duckdb")
    _seed(
        warehouse,
        (
            (
                date(2025, 12, 30),
                "GAMMA",
                "EQ",
                "INE000000004",
                100,
                105,
                95,
                100,
                1000,
            ),
            (date(2026, 1, 2), "GAMMA", "EQ", "INE000000004", 102, 108, 98, 104, 1000),
            (date(2026, 1, 5), "DELTA", "EQ", "INE000000005", 80, 85, 75, 82, 2000),
        ),
    )
    transition = {
        "transition_id": "transition-2",
        "predecessor_identity": "nse:isin:INE000000004",
        "successor_identity": "nse:isin:INE000000005",
        "old_symbol": "GAMMA",
        "new_symbol": "DELTA",
        "old_isin": "INE000000004",
        "new_isin": "INE000000005",
        "effective_date": "2026-01-05",
        "histories_may_be_linked": True,
        "price_comparison_valid": False,
        "new_identity_required": True,
    }
    b, b1d = _write_inputs(
        tmp_path,
        [
            _case(
                event_id="event-noncomparable",
                identity="nse:isin:INE000000005",
                symbol="DELTA",
                isin="INE000000005",
                effective="2026-01-05",
            )
        ],
        [transition],
    )

    report = FactorTransformationBridgeForensicsEngine().run(
        database_path=tmp_path / "truth.duckdb",
        htr010b_output=b,
        htr010b1d_output=b1d,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )

    case = report["cases"][0]
    assert case["bridge_classification"] == "IDENTITY_TRANSITION_NONCOMPARABLE"
    assert case["recommended_repair_action"] == (
        "KEEP_QUARANTINED_DO_NOT_APPLY_MULTIPLICATIVE_FACTOR"
    )


def test_missing_lineage_is_explicit_and_exports_are_deterministic(
    tmp_path: Path,
) -> None:
    warehouse = CanonicalPointInTimeWarehouse(tmp_path / "truth.duckdb")
    warehouse.initialise()
    b, b1d = _write_inputs(
        tmp_path,
        [
            _case(
                event_id="event-missing",
                identity="nse:isin:INE000000006",
                symbol="MISSING",
                isin="INE000000006",
                effective="2026-01-05",
            )
        ],
        [],
    )
    engine = FactorTransformationBridgeForensicsEngine()
    first = engine.run(
        database_path=tmp_path / "truth.duckdb",
        htr010b_output=b,
        htr010b1d_output=b1d,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )
    second = engine.run(
        database_path=tmp_path / "truth.duckdb",
        htr010b_output=b,
        htr010b1d_output=b1d,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )

    assert first == second
    assert first["cases"][0]["bridge_classification"] == (
        "CANDLE_LINEAGE_BRIDGE_MISSING"
    )
    paths = engine.export(first, tmp_path / "output")
    assert len(paths) == 4
    assert all(path.exists() for path in paths)


def test_bridge_forensics_command_registration_is_idempotent() -> None:
    first = _historical_truth_app()
    second = _historical_truth_app()
    command = "factor-transformation-bridge-forensics"
    assert sum(item.name == command for item in first.registered_commands) == 1
    assert sum(item.name == command for item in second.registered_commands) == 1
