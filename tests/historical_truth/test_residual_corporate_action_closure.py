from __future__ import annotations

import json
from pathlib import Path

from alpha.historical_truth.residual_corporate_action_closure import (
    ClosureReadiness,
    ResidualCorporateActionClosureEngine,
    ResidualCorporateActionClosureExporter,
)


def _write(path: Path, name: str, rows: list[dict[str, object]]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(
        json.dumps(rows, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    baseline_b1c = tmp_path / "baseline-b1c"
    final_b1c = tmp_path / "final-b1c"
    baseline_htr = tmp_path / "baseline-htr"
    final_htr = tmp_path / "final-htr"
    old = [
        {
            "event_id": "one",
            "symbol": "ALPHA",
            "action_type": "RIGHTS",
            "validation_outcome": "FACTOR_REQUIRES_REFERENCE_PRICE",
        },
        {
            "event_id": "two",
            "symbol": "BETA",
            "action_type": "BONUS",
            "validation_outcome": "FACTOR_INSUFFICIENT_EVIDENCE",
        },
    ]
    new = [
        {
            "event_id": "one",
            "symbol": "ALPHA",
            "action_type": "RIGHTS",
            "validation_outcome": "FACTOR_CONFIRMED_CORRECT_MARKET_GAP",
        },
        {
            "event_id": "two",
            "symbol": "BETA",
            "action_type": "BONUS",
            "validation_outcome": "FACTOR_INSUFFICIENT_EVIDENCE",
            "governed_continuity_context": {
                "decision": "ACTION_SESSION_MISSING",
                "rejected_bars": [],
            },
        },
    ]
    old_factors = [
        {
            "canonical_event_id": "one",
            "factor_state": "FACTOR_PROVISIONAL_REFERENCE_PRICE",
        },
        {
            "canonical_event_id": "two",
            "factor_state": "FACTOR_DERIVED_OFFICIAL_TERMS",
        },
    ]
    new_factors = [
        {
            "canonical_event_id": "one",
            "factor_state": "FACTOR_CERTIFIED_REFERENCE_PRICE",
            "reference_price_provenance_state": (
                "CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE_PRIOR_CLOSE"
            ),
        },
        {
            "canonical_event_id": "two",
            "factor_state": "FACTOR_DERIVED_OFFICIAL_TERMS",
        },
    ]
    _write(baseline_b1c, "htr010b1_factor_validation_results.json", old)
    _write(final_b1c, "htr010b1_factor_validation_results.json", new)
    _write(
        final_b1c,
        "htr010b1_replay_admission_intervals.json",
        [{"admission_state": "UNRESOLVED"}],
    )
    _write(baseline_htr, "htr010b_adjustment_factors.json", old_factors)
    _write(final_htr, "htr010b_adjustment_factors.json", new_factors)
    _write(
        final_htr,
        "htr010b_canonical_events.json",
        [
            {
                "canonical_event_id": "one",
                "raw_action_text": "Rights 1:1 at Rs 10",
                "ratio_numerator": 1.0,
                "ratio_denominator": 1.0,
                "rights_price": 10.0,
            },
            {
                "canonical_event_id": "two",
                "raw_action_text": "Bonus 1:1",
            },
        ],
    )
    _write(
        final_htr,
        "htr010b_adjusted_candle_summary.json",
        [{"price_basis_state": "MIXED_PRICE_BASIS"}],
    )
    return baseline_b1c, final_b1c, baseline_htr, final_htr


def test_closure_attributes_resolution_and_retains_exact_blocker(
    tmp_path: Path,
) -> None:
    inputs = _fixture(tmp_path)

    report = ResidualCorporateActionClosureEngine().run(
        baseline_b1c_output=inputs[0],
        final_b1c_output=inputs[1],
        baseline_htr010b_output=inputs[2],
        final_htr010b_output=inputs[3],
    )

    assert report.summary["initial_residual_count"] == 2
    assert report.summary["final_residual_count"] == 1
    assert report.summary["gross_resolved_count"] == 1
    assert report.summary["regressed_to_fail_closed_count"] == 0
    assert report.summary["net_resolved_count"] == 1
    assert report.summary["readiness"] == (
        ClosureReadiness.RESIDUAL_OFFICIAL_EVIDENCE_REQUIRED.value
    )
    assert report.remaining_blockers[0]["missing_component"] == (
        "FIRST_GOVERNED_ACTION_SESSION_CANDLE"
    )
    assert report.summary["production_influence"] is False


def test_closure_separates_terms_identity_and_isin_transition(
    tmp_path: Path,
) -> None:
    inputs = _fixture(tmp_path)
    final_rows = [
        {
            "event_id": "one",
            "validation_outcome": "FACTOR_REQUIRES_REFERENCE_PRICE",
        },
        {
            "event_id": "two",
            "validation_outcome": "FACTOR_REQUIRES_REFERENCE_PRICE",
        },
    ]
    _write(inputs[1], "htr010b1_factor_validation_results.json", final_rows)
    factors = json.loads(
        (inputs[3] / "htr010b_adjustment_factors.json").read_text(encoding="utf-8")
    )
    factors[0]["reference_price_original_provenance_state"] = "PRIOR_ISIN_MISMATCH"
    _write(inputs[3], "htr010b_adjustment_factors.json", factors)

    report = ResidualCorporateActionClosureEngine().run(
        baseline_b1c_output=inputs[0],
        final_b1c_output=inputs[1],
        baseline_htr010b_output=inputs[2],
        final_htr010b_output=inputs[3],
    )

    blockers = {
        str(row["event_id"]): str(row["missing_component"])
        for row in report.remaining_blockers
    }
    assert blockers == {
        "one": "OFFICIAL_EFFECTIVE_DATED_ISIN_TRANSITION",
        "two": "COMPLETE_OFFICIAL_EQUITY_RIGHTS_TERMS",
    }


def test_closure_certifies_only_empty_queue_and_clean_basis(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    _write(
        inputs[1],
        "htr010b1_factor_validation_results.json",
        [
            {
                "event_id": "one",
                "validation_outcome": "FACTOR_CONFIRMED_CORRECT_MARKET_GAP",
            },
            {
                "event_id": "two",
                "validation_outcome": "FACTOR_CONFIRMED_CORRECT_MARKET_GAP",
            },
        ],
    )
    _write(inputs[1], "htr010b1_replay_admission_intervals.json", [])
    _write(inputs[3], "htr010b_adjusted_candle_summary.json", [])

    report = ResidualCorporateActionClosureEngine().run(
        baseline_b1c_output=inputs[0],
        final_b1c_output=inputs[1],
        baseline_htr010b_output=inputs[2],
        final_htr010b_output=inputs[3],
    )

    assert report.summary["readiness"] == (
        ClosureReadiness.ADJUSTED_REPLAY_CERTIFIED.value
    )
    assert report.summary["adjusted_replay_ready"] is True


def test_exports_are_deterministic(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    report = ResidualCorporateActionClosureEngine().run(
        baseline_b1c_output=inputs[0],
        final_b1c_output=inputs[1],
        baseline_htr010b_output=inputs[2],
        final_htr010b_output=inputs[3],
    )
    exporter = ResidualCorporateActionClosureExporter()
    first = exporter.export(report, tmp_path / "first")
    second = exporter.export(report, tmp_path / "second")

    assert [path.read_bytes() for path in first] == [
        path.read_bytes() for path in second
    ]
