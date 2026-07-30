from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pandas as pd
import pytest
import typer

from alpha.application.decision_superiority_structural_stop_risk_scaling_cli import (
    register_decision_superiority_structural_stop_risk_scaling_command,
)
from alpha.decision_superiority.entry_stop_improvement import _stable_id
from alpha.decision_superiority.regime_strategy_models import TournamentPolicy
from alpha.decision_superiority.structural_stop_risk_scaling import (
    _acceptance,
    _apply_daily_notional_overlay,
    _capacity_ledger,
    _scaled_trade_ledger,
    governance_flags,
)
from alpha.decision_superiority.structural_stop_risk_scaling_artifacts import (
    DSI012_ARTIFACTS,
    export_structural_stop_risk_scaling,
    validate_structural_stop_risk_scaling_certificate,
)
from alpha.decision_superiority.structural_stop_risk_scaling_models import (
    StructuralStopRiskScalingError,
    StructuralStopRiskScalingPolicy,
    StructuralStopRiskScalingResult,
)


def _curve() -> tuple[dict[str, object], ...]:
    start = date(2021, 1, 4)
    returns = (0.01, -0.005, 0.02, -0.004, 0.012)
    value = 1_000_000.0
    peak = value
    rows: list[dict[str, object]] = []
    cumulative_costs = 0.0
    for index, daily_return in enumerate(returns):
        value *= 1.0 + daily_return
        peak = max(peak, value)
        cumulative_costs += 10.0
        rows.append(
            {
                "portfolio_day_id": f"DAY-{index}",
                "portfolio_name": "STOP-STRUCTURAL-10D",
                "observed_on": start + timedelta(days=index),
                "cash": value * 0.25,
                "open_position_value": value * 0.75,
                "gross_exposure": 0.75,
                "net_exposure": 0.75,
                "realised_pnl": 0.0,
                "unrealised_pnl": value - 1_000_000.0,
                "cumulative_costs": cumulative_costs,
                "portfolio_value": value,
                "daily_return": daily_return,
                "drawdown": value / peak - 1.0,
                "open_positions": 1,
            }
        )
    return tuple(rows)


def _trades() -> tuple[dict[str, object], ...]:
    return (
        {
            "logical_trade_id": "TRADE-1",
            "symbol": "TEST",
            "entry_date": date(2021, 1, 4),
            "quantity": 100.0,
            "gross_pnl": 12_000.0,
            "net_pnl": 11_500.0,
            "costs": 500.0,
            "net_return": 0.115,
        },
        {
            "logical_trade_id": "TRADE-2",
            "symbol": "TEST2",
            "entry_date": date(2021, 1, 5),
            "quantity": 50.0,
            "gross_pnl": -2_000.0,
            "net_pnl": -2_300.0,
            "costs": 300.0,
            "net_return": -0.046,
        },
    )


def test_policy_freezes_exact_multiplier_and_financing_order() -> None:
    assert StructuralStopRiskScalingPolicy().risk_multiplier == 1.5
    with pytest.raises(
        StructuralStopRiskScalingError,
        match="DSI012_RISK_MULTIPLIER_NOT_FROZEN",
    ):
        StructuralStopRiskScalingPolicy(risk_multiplier=1.49)
    with pytest.raises(
        StructuralStopRiskScalingError,
        match="DSI012_FINANCING_ASSUMPTIONS_INVALID",
    ):
        StructuralStopRiskScalingPolicy(
            base_financing_rate=0.20,
            stress_financing_rate=0.18,
        )


def test_governance_is_research_only() -> None:
    flags = governance_flags()
    assert flags
    assert flags["PRODUCTION_INFLUENCE"] is False
    assert flags["AUTOMATIC_STRATEGY_PROMOTION_ENABLED"] is False
    assert flags["FORWARD_PAPER_ACTIVATION_ENABLED"] is False
    assert not any(flags.values())


def test_overlay_scales_path_and_charges_only_borrowed_exposure() -> None:
    policy = StructuralStopRiskScalingPolicy()
    base = _apply_daily_notional_overlay(
        curve=_curve(),
        trades=_trades(),
        policy=policy,
        financing_rate=policy.base_financing_rate,
        scenario="BASE_FINANCING",
    )
    stress = _apply_daily_notional_overlay(
        curve=_curve(),
        trades=_trades(),
        policy=policy,
        financing_rate=policy.stress_financing_rate,
        scenario="STRESS_FINANCING",
    )

    first = base["curve"][0]
    assert first["gross_exposure"] == pytest.approx(1.125)
    assert first["borrowed_fraction"] == pytest.approx(0.125)
    assert first["daily_financing_cost"] > 0
    assert base["metrics"]["ending_capital"] > stress["metrics"]["ending_capital"]
    assert base["metrics"]["total_costs"] > base["metrics"]["scaled_transaction_costs"]
    assert base["metrics"]["trade_count"] == 2
    assert base["metrics"]["expectancy"] == pytest.approx((0.115 - 0.046) / 2)


def test_scaled_trade_ledger_replaces_accounting_fields() -> None:
    rows = _scaled_trade_ledger(_trades(), multiplier=1.5)
    assert rows[0]["base_quantity"] == 100.0
    assert rows[0]["quantity"] == 150.0
    assert rows[0]["net_pnl"] == 17_250.0
    assert rows[0]["costs"] == 750.0
    assert rows[0]["net_return"] == 0.115


def test_capacity_ledger_fails_closed_when_scaled_notional_exceeds_adv_cap() -> None:
    plan_id = "PLAN-1"
    trade_id = _stable_id("PORTFOLIO_TRADE", "STOP-STRUCTURAL-10D", plan_id)
    selected = pd.DataFrame(
        [{"trade_plan_id": plan_id, "average_traded_value20": 10_000_000.0}]
    )
    rows = _capacity_ledger(
        selected=selected,
        trades=(
            {
                "logical_trade_id": trade_id,
                "symbol": "TEST",
                "entry_date": date(2021, 1, 4),
                "quantity": 1_000.0,
                "entry_price": 100.0,
            },
        ),
        policy=StructuralStopRiskScalingPolicy(),
        tournament_policy=TournamentPolicy(),
    )
    assert rows[0]["capacity_limit"] == 100_000.0
    assert rows[0]["scaled_entry_notional"] == 150_000.0
    assert rows[0]["capacity_passed"] is False


def test_acceptance_uses_exact_preregistered_thresholds_and_zero_is_not_missing(
) -> None:
    policy = StructuralStopRiskScalingPolicy()
    passing = {
        "net_cagr": 0.26,
        "maximum_drawdown": -0.10,
        "calmar": 2.6,
        "daily_profit_factor": 1.6,
        "expectancy": 0.01,
        "maximum_gross_exposure": 1.125,
    }
    rows, blockers = _acceptance(
        base_metrics=passing,
        benchmark_cagr=0.18,
        capacity_rows=({"capacity_passed": True},),
        position_rows=({"scaled_portfolio_fraction": 0.22},),
        parity_ok=True,
        policy=policy,
    )
    assert all(row["passed"] for row in rows)
    assert blockers == []

    failing = dict(passing)
    failing["expectancy"] = 0.0
    rows, blockers = _acceptance(
        base_metrics=failing,
        benchmark_cagr=0.18,
        capacity_rows=({"capacity_passed": True},),
        position_rows=({"scaled_portfolio_fraction": 0.22},),
        parity_ok=True,
        policy=policy,
    )
    expectation = next(row for row in rows if row["gate"] == "TRADE_EXPECTANCY")
    assert expectation["actual"] == 0.0
    assert expectation["passed"] is False
    assert "TRADE_EXPECTANCY_FAILED" in blockers


def _artifact_result(
    *, acceptance_passed: bool = True
) -> StructuralStopRiskScalingResult:
    rows: dict[str, tuple[dict[str, Any], ...]] = {
        key: ({"artifact": key, "value": 1},) for key in DSI012_ARTIFACTS
    }
    rows["source_contract"] = (
        {"source_role": "DSI009_CERTIFICATE", "sha256": "abc", "path": "source"},
    )
    rows["acceptance"] = (
        {
            "gate": "NET_CAGR",
            "actual": 0.26,
            "threshold": 0.25,
            "passed": acceptance_passed,
            "pre_registered": True,
        },
    )
    metrics = {
        "net_cagr": 0.26,
        "maximum_drawdown": -0.10,
        "calmar": 2.6,
        "daily_profit_factor": 1.6,
        "expectancy": 0.01,
        "financing_rate": 0.12,
        "total_financing_costs": 100.0,
        "maximum_gross_exposure": 1.125,
        "trade_count": 51,
    }
    return StructuralStopRiskScalingResult(
        source_commit="abc123",
        readiness=(
            "READY_FOR_GOVERNED_FORWARD_PAPER_RISK_SCALING_RESEARCH"
            if acceptance_passed
            else "READY_WITH_STRUCTURAL_STOP_RISK_SCALING_REJECTED"
        ),
        blockers=() if acceptance_passed else ("NET_CAGR_FAILED",),
        rows=MappingProxyType(rows),
        summaries=MappingProxyType(
            {
                "mechanism_id": "STOP-STRUCTURAL-10D",
                "risk_multiplier": 1.5,
                "base_structural_stop": metrics,
                "base_financing": metrics,
                "stress_financing": {**metrics, "financing_rate": 0.18},
                "benchmark_cagr": 0.168,
                "capacity_failure_count": 0,
                "acceptance_passed": acceptance_passed,
                "retrospective_target_match": acceptance_passed,
                "validated_strategy": False,
                "fresh_unused_holdout_available": False,
                "forward_paper_eligible": acceptance_passed,
                "automatic_promotion": False,
                "stress_used_for_selection": False,
                "interpretation": "Research only.",
            }
        ),
        governance=MappingProxyType(governance_flags()),
    )


def test_artifact_export_validation_and_tamper_detection(tmp_path: Path) -> None:
    output = tmp_path / "dsi012"
    paths = export_structural_stop_risk_scaling(_artifact_result(), output)
    certificate = paths[0]
    payload = validate_structural_stop_risk_scaling_certificate(
        certificate,
        require_target_match=True,
    )
    assert payload["acceptance_passed"] is True
    assert payload["validated_strategy"] is False
    assert payload["source_chain_hashes"] == {"DSI009_CERTIFICATE": "abc"}

    support = output / DSI012_ARTIFACTS["acceptance"]
    support.write_text(
        support.read_text(encoding="utf-8") + "tampered\n",
        encoding="utf-8",
    )
    with pytest.raises(
        StructuralStopRiskScalingError,
        match="DSI012_ARTIFACT_TAMPERED",
    ):
        validate_structural_stop_risk_scaling_certificate(certificate)


def test_target_match_requirement_fails_closed(tmp_path: Path) -> None:
    paths = export_structural_stop_risk_scaling(
        _artifact_result(acceptance_passed=False),
        tmp_path / "rejected",
    )
    with pytest.raises(
        StructuralStopRiskScalingError,
        match="DSI012_TARGET_NOT_MATCHED",
    ):
        validate_structural_stop_risk_scaling_certificate(
            paths[0],
            require_target_match=True,
        )


def test_cli_registers_runner_and_verifier() -> None:
    app = typer.Typer()
    register_decision_superiority_structural_stop_risk_scaling_command(app)
    names = {command.name for command in app.registered_commands}
    assert names == {
        "decision-superiority-structural-stop-risk-scaling",
        "decision-superiority-structural-stop-risk-scaling-verify",
    }
