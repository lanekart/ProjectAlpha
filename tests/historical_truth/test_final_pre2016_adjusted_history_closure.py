from __future__ import annotations

import json
from pathlib import Path

from alpha.historical_truth.final_pre2016_adjusted_history_closure import (
    FinalPre2016AdjustedHistoryClosureEngine,
    FinalPre2016AdjustedHistoryClosureExporter,
)


def _write(path: Path, name: str, value: object) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    baseline_b1c = tmp_path / "baseline-b1c"
    final_b1c = tmp_path / "final-b1c"
    baseline_htr = tmp_path / "baseline-htr"
    final_htr = tmp_path / "final-htr"
    missing_action = {
        "event_id": "action",
        "symbol": "ALPHA",
        "action_type": "SPLIT",
        "validation_outcome": "FACTOR_INSUFFICIENT_EVIDENCE",
        "governed_continuity_context": {
            "decision": "ACTION_SESSION_MISSING",
        },
    }
    missing_transition = {
        "event_id": "transition",
        "symbol": "BETA",
        "action_type": "BONUS",
        "validation_outcome": "FACTOR_INSUFFICIENT_EVIDENCE",
        "governed_continuity_context": {
            "decision": "ACTION_SESSION_MISSING",
        },
    }
    _write(
        baseline_b1c,
        "htr010b1_factor_validation_results.json",
        [missing_action, missing_transition],
    )
    _write(
        final_b1c,
        "htr010b1_factor_validation_results.json",
        [
            {
                **missing_action,
                "validation_outcome": "FACTOR_CONFIRMED_CORRECT_MARKET_GAP",
                "governed_continuity_context": {
                    "decision": "COMPLETE_GOVERNED_CONTINUITY_CONTEXT",
                    "selected_prior_bars": [],
                    "action_bar": {"identity_state": "EXACT_ISIN_CANDLE"},
                },
            },
            {
                **missing_transition,
                "validation_outcome": "FACTOR_CONFIRMED_CORRECT_MARKET_GAP",
                "governed_continuity_context": {
                    "decision": "COMPLETE_GOVERNED_CONTINUITY_CONTEXT",
                    "selected_prior_bars": [],
                    "action_bar": {
                        "identity_state": ("CERTIFIED_OFFICIAL_ISIN_TRANSITION_CANDLE")
                    },
                },
            },
        ],
    )
    _write(final_b1c, "htr010b1_replay_admission_intervals.json", [])
    events = [
        {
            "canonical_event_id": "action",
            "symbol": "ALPHA",
            "action_type": "SPLIT",
        },
        {
            "canonical_event_id": "transition",
            "symbol": "BETA",
            "action_type": "RIGHTS",
        },
    ]
    factors = [
        {
            "canonical_event_id": "action",
            "factor_state": "FACTOR_DERIVED_OFFICIAL_TERMS",
        },
        {
            "canonical_event_id": "transition",
            "factor_state": "FACTOR_CERTIFIED_REFERENCE_PRICE",
        },
    ]
    for root in (baseline_htr, final_htr):
        _write(root, "htr010b_canonical_events.json", events)
        _write(root, "htr010b_adjustment_factors.json", factors)
        _write(
            root,
            "htr010b_adjusted_candle_summary.json",
            [
                {
                    "raw_rows": 10,
                    "adjusted_rows": 10,
                    "price_basis_state": "BACKWARD_ADJUSTED_CERTIFIED",
                }
            ],
        )
        _write(
            root,
            "htr010b_adjusted_replay_readiness.json",
            {"raw_candle_fingerprint": "a" * 64},
        )
    return baseline_b1c, final_b1c, baseline_htr, final_htr


def test_b4_attributes_action_and_transition_repairs(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)

    report = FinalPre2016AdjustedHistoryClosureEngine().run(
        baseline_b1c_output=inputs[0],
        final_b1c_output=inputs[1],
        baseline_htr010b_output=inputs[2],
        final_htr010b_output=inputs[3],
    )

    assert report.summary["starting_case_count"] == 2
    assert report.summary["resolved_case_count"] == 2
    assert report.summary["resolution_channel_counts"] == {
        "IDENTITY_TRANSITION_WIRING": 1,
        "SECURITY_SPECIFIC_ACTION_SESSION": 1,
    }
    assert report.summary["adjusted_replay_ready"] is True
    assert report.summary["raw_candles_unchanged"] is True
    assert report.rights_factor_states == {"FACTOR_CERTIFIED_REFERENCE_PRICE": 1}


def test_b4_exports_are_byte_deterministic(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    engine = FinalPre2016AdjustedHistoryClosureEngine()
    report = engine.run(
        baseline_b1c_output=inputs[0],
        final_b1c_output=inputs[1],
        baseline_htr010b_output=inputs[2],
        final_htr010b_output=inputs[3],
    )
    exporter = FinalPre2016AdjustedHistoryClosureExporter()

    first = exporter.export(report, tmp_path / "first")
    second = exporter.export(report, tmp_path / "second")

    assert [path.name for path in first] == [path.name for path in second]
    assert [path.read_bytes() for path in first] == [
        path.read_bytes() for path in second
    ]
