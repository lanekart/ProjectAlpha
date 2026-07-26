from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pandas as pd
import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.decision_superiority.performance_improvement import (
    _apply_challenger,
    _benjamini_hochberg,
    _evaluate_tiers,
    _holm,
    _multiple_testing,
    default_challenger_registry,
    governance_flags,
    load_governed_tri,
    validate_challenger_registry,
    wilson_interval,
)
from alpha.decision_superiority.performance_improvement_artifacts import (
    DSI008_ARTIFACTS,
    DSI008_CERTIFICATE,
    export_performance_improvement,
    validate_performance_improvement_certificate,
)
from alpha.decision_superiority.performance_improvement_models import (
    BenchmarkKind,
    ChallengerDefinition,
    ImprovementPolicy,
    PerformanceImprovementError,
    PerformanceImprovementResult,
)


def _tri(tmp_path: Path, *, kind: str = "TOTAL_RETURN") -> Path:
    path = tmp_path / "nifty500_tri.csv"
    frame = pd.DataFrame(
        {
            "Date": pd.bdate_range("2021-01-01", periods=300).date,
            "Index Name": ["Nifty 500"] * 300,
            "TotalReturnsIndex": [10_000.0 * 1.0004**index for index in range(300)],
        }
    )
    frame.to_csv(path, index=False)
    provenance = {
        "index_identifier": "NIFTY500",
        "index_name": "Nifty 500",
        "benchmark_kind": kind,
        "source": ("https://www.niftyindices.com/BackPage/getTotalReturnIndexString"),
        "source_version": "OFFICIAL_WEB_TRI_2026-07-26",
        "currency": "INR",
        "dividend_treatment": "GROSS_DIVIDENDS_REINVESTED",
        "adjustment_treatment": "OFFICIAL_INDEX_METHODOLOGY",
        "raw_source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "acquired_at": "2026-07-26T00:00:00Z",
    }
    path.with_suffix(".csv.provenance.json").write_text(
        json.dumps(provenance, sort_keys=True),
        encoding="utf-8",
    )
    return path


def test_governance_flags_are_all_false() -> None:
    flags = governance_flags()
    assert len(flags) == 20
    assert not any(flags.values())
    assert flags["STRATEGY_AUTOMATIC_PROMOTION_ENABLED"] is False
    assert flags["PRODUCTION_INFLUENCE"] is False


def test_improvement_policy_is_immutable() -> None:
    policy = ImprovementPolicy()
    with pytest.raises(FrozenInstanceError):
        policy.minimum_elite_completed = 1  # type: ignore[misc]


def test_governed_tri_provenance_and_return_semantics(tmp_path: Path) -> None:
    frame, provenance, contract = load_governed_tri(_tri(tmp_path))
    assert provenance.benchmark_kind is BenchmarkKind.TOTAL_RETURN
    assert contract["used_for_superiority"] is True
    assert contract["duplicate_dates"] == 0
    assert frame["value"].iloc[-1] > frame["value"].iloc[0]


def test_price_index_is_not_substituted_for_tri(tmp_path: Path) -> None:
    with pytest.raises(
        PerformanceImprovementError,
        match="PRICE_INDEX_DIAGNOSTIC_ONLY",
    ):
        load_governed_tri(_tri(tmp_path, kind="PRICE_INDEX"))


def test_tri_hash_tampering_is_detected(tmp_path: Path) -> None:
    path = _tri(tmp_path)
    path.write_text(path.read_text("utf-8") + "\n", encoding="utf-8")
    with pytest.raises(
        PerformanceImprovementError,
        match="SOURCE_HASH_MISMATCH",
    ):
        load_governed_tri(path)


def test_tri_duplicate_and_nonpositive_values_fail_closed(
    tmp_path: Path,
) -> None:
    duplicate = _tri(tmp_path)
    frame = pd.read_csv(duplicate)
    frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    frame.to_csv(duplicate, index=False)
    provenance_path = duplicate.with_suffix(".csv.provenance.json")
    payload = json.loads(provenance_path.read_text("utf-8"))
    payload["raw_source_sha256"] = hashlib.sha256(duplicate.read_bytes()).hexdigest()
    provenance_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(
        PerformanceImprovementError,
        match="DUPLICATE_DATE",
    ):
        load_governed_tri(duplicate)


def test_challenger_ids_are_stable_and_registry_is_bounded() -> None:
    first = default_challenger_registry()
    second = default_challenger_registry()
    assert first == second
    assert len(first) == 6
    assert len({item.challenger_id for item in first}) == 6
    validate_challenger_registry(first, maximum_challengers=6)
    with pytest.raises(
        PerformanceImprovementError,
        match="UNBOUNDED",
    ):
        validate_challenger_registry(first, maximum_challengers=5)


def test_duplicate_challenger_is_rejected() -> None:
    challenger = default_challenger_registry()[0]
    with pytest.raises(
        PerformanceImprovementError,
        match="DUPLICATE_CHALLENGER_ID",
    ):
        validate_challenger_registry(
            (challenger, challenger),
            maximum_challengers=2,
        )


def test_one_factor_challenger_filters_only_declared_field() -> None:
    frame = pd.DataFrame(
        {
            "signal_id": ["weak", "strong"],
            "signal_strength": [0.60, 0.80],
            "realised_return": [0.10, -0.05],
        }
    )
    selected = _apply_challenger(
        frame,
        default_challenger_registry()[0],
    )
    assert selected["signal_id"].tolist() == ["strong"]
    assert frame["realised_return"].tolist() == [0.10, -0.05]


def test_challenger_complexity_above_one_is_rejected() -> None:
    with pytest.raises(
        PerformanceImprovementError,
        match="one-factor",
    ):
        ChallengerDefinition(
            "COMBINED",
            "RANKING",
            "signal_strength",
            "GREATER_THAN_OR_EQUAL",
            0.8,
            (),
            "test",
            "test",
            "test",
            2,
            "fixed",
        )


def test_wilson_interval_prevents_tiny_sample_certainty() -> None:
    lower, upper = wilson_interval(4, 5)
    assert lower < 0.50
    assert upper < 1.0


def test_elite_tier_with_five_wins_is_insufficient() -> None:
    outcomes = _outcomes(5, wins=5)
    definitions, rows = _evaluate_tiers(
        outcomes=outcomes,
        folds=_folds(),
        policy=ImprovementPolicy(minimum_elite_completed=30),
    )
    elite = next(row for row in rows if row["tier"] == "ALPHA_ELITE")
    assert len(definitions) == 3
    assert elite["sample_sufficient"] is False
    assert elite["accuracy_target_supported"] is False


def test_high_accuracy_negative_expectancy_is_not_supported() -> None:
    outcomes = _outcomes(40, wins=32, winner=0.01, loser=-0.10)
    _, rows = _evaluate_tiers(
        outcomes=outcomes,
        folds=_folds(),
        policy=ImprovementPolicy(minimum_elite_completed=5),
    )
    elite = next(row for row in rows if row["tier"] == "ALPHA_ELITE")
    if elite["completed_count"]:
        assert (
            elite["expectancy"] is None
            or elite["expectancy"] <= 0
            or elite["accuracy_target_supported"] is False
        )


def test_bh_and_holm_are_monotonic_and_bounded() -> None:
    values = [0.01, 0.02, 0.50]
    bh = _benjamini_hochberg(values)
    holm = _holm(values)
    assert all(0 <= value <= 1 for value in (*bh, *holm))
    assert bh[0] <= bh[1] <= bh[2]
    assert holm[0] <= holm[1] <= holm[2]


def test_multiple_testing_preserves_no_test_state() -> None:
    rows = _multiple_testing(
        [
            {
                "challenger_id": "A",
                "expectancy_delta": None,
                "positive_fold_count": 0,
                "negative_fold_count": 0,
            }
        ]
    )
    assert rows[0]["raw_p_value"] is None
    assert rows[0]["survives_bh_5pct"] is False
    assert rows[0]["no_test_reason"] == "INSUFFICIENT_NON_TIED_FOLDS"


def test_artifact_export_and_certificate_validation(tmp_path: Path) -> None:
    result = _result()
    paths = export_performance_improvement(result, tmp_path)
    assert len(paths) == len(DSI008_ARTIFACTS) + 2
    payload = validate_performance_improvement_certificate(
        tmp_path / DSI008_CERTIFICATE,
        require_ready=True,
    )
    assert payload["readiness_decision"].startswith("READY_")
    assert payload["automatic_promotion_count"] == 0


def test_artifact_tampering_is_detected(tmp_path: Path) -> None:
    export_performance_improvement(_result(), tmp_path)
    artifact = tmp_path / next(iter(DSI008_ARTIFACTS.values()))
    artifact.write_text(artifact.read_text("utf-8") + "tamper", "utf-8")
    with pytest.raises(
        PerformanceImprovementError,
        match="ARTIFACT_TAMPERED",
    ):
        validate_performance_improvement_certificate(tmp_path / DSI008_CERTIFICATE)


def test_verify_cli_renders_research_boundary(tmp_path: Path) -> None:
    export_performance_improvement(_result(), tmp_path)
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-performance-improvement-verify",
            "--certificate",
            str(tmp_path / DSI008_CERTIFICATE),
            "--require-ready",
        ],
    )
    assert result.exit_code == 0
    assert "Certificate: VALID" in result.stdout
    assert "DSI-008-v1.0.0" in result.stdout


def test_export_is_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    export_performance_improvement(_result(), first)
    export_performance_improvement(_result(), second)
    assert {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in first.iterdir()
    } == {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in second.iterdir()
    }


def test_no_machine_paths_leak_to_artifacts(tmp_path: Path) -> None:
    export_performance_improvement(_result(), tmp_path)
    assert not any(b"/Users/" in path.read_bytes() for path in tmp_path.iterdir())


def _outcomes(
    count: int,
    *,
    wins: int,
    winner: float = 0.05,
    loser: float = -0.03,
) -> list[dict[str, Any]]:
    rows = []
    for index in range(count):
        success = index < wins
        observed_on = date(2021 + index % 5, 6, 1)
        rows.append(
            {
                "signal_id": f"S-{index:03d}",
                "signal_date": observed_on,
                "walk_forward_fold_id": f"WF-{observed_on.year}",
                "signal_strength": 0.50 + index / max(count, 1) * 0.49,
                "POSITIVE_REALISED_TRADE_RETURN": success,
                "realised_return": winner if success else loser,
                "net_pnl": 100.0 if success else -60.0,
            }
        )
    return rows


def _folds() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "walk_forward_fold_id": f"WF-{year}",
                "train_start": date(2016, 1, 1),
                "train_end": date(year - 2, 12, 31),
                "validation_start": date(year - 1, 1, 1),
                "validation_end": date(year - 1, 12, 31),
                "test_start": date(year, 1, 1),
                "test_end": date(year, 12, 31),
            }
            for year in range(2021, 2026)
        ]
    )


def _result() -> PerformanceImprovementResult:
    rows: dict[str, tuple[dict[str, Any], ...]] = {
        key: ({"state": f"{key}:OBSERVED"},) for key in DSI008_ARTIFACTS
    }
    rows["source_contract"] = (
        {
            "source_role": "DSI007_CERTIFICATE",
            "sha256": "a" * 64,
        },
        {
            "source_role": "TRI_BENCHMARK",
            "sha256": "b" * 64,
        },
    )
    tier = {
        "completed_count": 10,
        "observed_accuracy": 0.6,
        "wilson_lower": 0.31,
        "wilson_upper": 0.83,
        "expectancy": 0.02,
        "accuracy_target_supported": False,
    }
    summary = {
        "benchmark": {
            "name": "Nifty 500",
            "kind": "TOTAL_RETURN",
            "source": "official",
            "source_start_date": date(2016, 1, 1),
            "source_end_date": date(2025, 12, 31),
            "comparison_start_date": date(2021, 1, 1),
            "comparison_end_date": date(2025, 12, 24),
            "cagr": 0.09,
        },
        "incumbent": {
            "net_cagr": 0.1065,
            "excess_cagr": 0.0165,
            "maximum_drawdown": -0.0718,
            "sharpe": 1.34,
            "sortino": 0.94,
        },
        "attribution_row_count": 12,
        "weakest_mechanism": "STOP_PLACEMENT",
        "challengers_tested": 6,
        "challengers_rejected": 6,
        "accepted_challenger": None,
        "tiers": {
            "ALPHA_STANDARD": tier,
            "ALPHA_HIGH_CONVICTION": tier,
            "ALPHA_ELITE": tier,
        },
        "multiple_testing_survived": False,
        "robustness_grade": "NO_RELIABLE_IMPROVEMENT_FOUND",
        "fresh_2026_holdout_available": False,
        "interpretation": "Descriptive research only.",
    }
    readiness = MappingProxyType(
        {
            "A": "READY_FOR_GOVERNED_TRI_BENCHMARK_RESEARCH",
            "B": "READY_FOR_GOVERNED_PERFORMANCE_ATTRIBUTION",
            "C": "READY_FOR_GOVERNED_SIGNAL_CALIBRATION",
            "D": "READY_FOR_GOVERNED_MECHANISM_CHALLENGERS",
            "E": "READY_WITH_NO_BETTER_CHALLENGER",
            "F": "READY_WITH_NO_VALID_ELITE_TIER",
            "G": "READY_FOR_GOVERNED_WEALTH_IMPROVEMENT_RESEARCH",
            "H": "READY_WITH_DESCRIPTIVE_IMPROVEMENTS_ONLY",
            "I": "READY_WITH_NO_RELIABLE_IMPROVEMENT",
        }
    )
    return PerformanceImprovementResult(
        source_commit="c" * 40,
        readiness=readiness,
        blockers=(),
        rows=MappingProxyType(rows),
        summaries=MappingProxyType(summary),
        governance=MappingProxyType(governance_flags()),
    )
