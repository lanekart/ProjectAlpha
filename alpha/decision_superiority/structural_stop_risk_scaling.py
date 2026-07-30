"""Governed DSI-012 fixed 1.50x structural-stop risk-scaling research."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from alpha.decision_superiority.entry_stop_improvement_artifacts import (
    validate_entry_stop_improvement_certificate,
)
from alpha.decision_superiority.performance_improvement_artifacts import (
    validate_performance_improvement_certificate,
)
from alpha.decision_superiority.regime_strategy_artifacts import (
    validate_regime_strategy_tournament_certificate,
)
from alpha.decision_superiority.regime_strategy_models import TournamentPolicy
from alpha.decision_superiority.structural_stop_risk_scaling_models import (
    DSI012_MECHANISM_ID,
    StructuralStopRiskScalingError,
    StructuralStopRiskScalingPolicy,
    StructuralStopRiskScalingResult,
    StructuralStopRiskScalingSourcePaths,
)
from alpha.decision_superiority.structural_stop_risk_scaling_overlay import (
    _acceptance,
    _apply_daily_notional_overlay,
    _scaled_cost_ledger,
    _scaled_position_ledger,
    _scaled_trade_ledger,
)
from alpha.decision_superiority.structural_stop_risk_scaling_rehydration import (
    _capacity_ledger,
    _parity_rows,
    _rehydrate_structural_stop,
    _source_contract_rows,
    _validate_market_slice,
    _validate_source_chain,
)


def governance_flags() -> dict[str, bool]:
    """Return the immutable DSI-012 research-only boundary."""

    return {
        "RISK_MULTIPLIER_CHANGE_PERMITTED": False,
        "ENTRY_POLICY_CHANGE_PERMITTED": False,
        "STOP_POLICY_CHANGE_PERMITTED": False,
        "TARGET_POLICY_CHANGE_PERMITTED": False,
        "PORTFOLIO_POLICY_CHANGE_PERMITTED": False,
        "FINANCING_ASSUMPTION_SELECTION_PERMITTED": False,
        "AUTOMATIC_STRATEGY_PROMOTION_ENABLED": False,
        "FORWARD_PAPER_ACTIVATION_ENABLED": False,
        "LIVE_SCORING_ENABLED": False,
        "RECOMMENDATION_INFLUENCE": False,
        "PORTFOLIO_POLICY_INFLUENCE": False,
        "EXECUTION_INFLUENCE": False,
        "LEARNING_MUTATION_ENABLED": False,
        "ACTIVE_REPLAY_INTEGRATION": False,
        "PRODUCTION_INFLUENCE": False,
    }


class GovernedStructuralStopRiskScalingEngine:
    """Rehydrate DSI-009 structural-stop evidence and test one fixed overlay."""

    def run(
        self,
        *,
        sources: StructuralStopRiskScalingSourcePaths,
        policy: StructuralStopRiskScalingPolicy = StructuralStopRiskScalingPolicy(),
    ) -> StructuralStopRiskScalingResult:
        dsi009 = validate_entry_stop_improvement_certificate(
            sources.dsi009_certificate,
            require_ready=True,
        )
        dsi008 = validate_performance_improvement_certificate(
            sources.dsi008_certificate,
            require_ready=True,
        )
        dsi007 = validate_regime_strategy_tournament_certificate(
            sources.dsi007_certificate,
            require_ready=False,
        )
        _validate_source_chain(sources=sources, dsi009=dsi009)

        selected, simulation, base_metrics, market_hash = _rehydrate_structural_stop(
            sources=sources,
            dsi008=dsi008,
        )
        _validate_market_slice(
            actual_market_hash=market_hash,
            dsi009=dsi009,
        )
        parity_rows, parity_ok = _parity_rows(
            base_metrics=base_metrics,
            dsi009=dsi009,
        )
        if not parity_ok:
            raise StructuralStopRiskScalingError(
                "DSI012_STRUCTURAL_STOP_REHYDRATION_PARITY_DEFECT"
            )

        base_curve = cast(Sequence[Mapping[str, Any]], simulation["curve"])
        base_trades = cast(Sequence[Mapping[str, Any]], simulation["trades"])
        base_positions = cast(Sequence[Mapping[str, Any]], simulation["positions"])
        base_costs = cast(Sequence[Mapping[str, Any]], simulation["costs"])
        base_overlay = _apply_daily_notional_overlay(
            curve=base_curve,
            trades=base_trades,
            policy=policy,
            financing_rate=policy.base_financing_rate,
            scenario="BASE_FINANCING",
        )
        stress_overlay = _apply_daily_notional_overlay(
            curve=base_curve,
            trades=base_trades,
            policy=policy,
            financing_rate=policy.stress_financing_rate,
            scenario="STRESS_FINANCING",
        )
        capacity_rows = _capacity_ledger(
            selected=selected,
            trades=base_trades,
            policy=policy,
            tournament_policy=TournamentPolicy(),
        )
        position_rows = _scaled_position_ledger(
            base_positions=base_positions,
            scaled_curve=cast(Sequence[Mapping[str, Any]], base_overlay["curve"]),
            multiplier=policy.risk_multiplier,
        )
        trade_rows = _scaled_trade_ledger(
            base_trades,
            multiplier=policy.risk_multiplier,
        )
        cost_rows = _scaled_cost_ledger(
            base_costs,
            multiplier=policy.risk_multiplier,
        )
        benchmark_cagr = float(
            cast(Mapping[str, Any], dsi009["benchmark_summary"])["cagr"]
        )
        acceptance_rows, blockers = _acceptance(
            base_metrics=cast(Mapping[str, Any], base_overlay["metrics"]),
            benchmark_cagr=benchmark_cagr,
            capacity_rows=capacity_rows,
            position_rows=position_rows,
            parity_ok=parity_ok,
            policy=policy,
        )
        passed = all(bool(row["passed"]) for row in acceptance_rows)
        readiness = (
            "READY_FOR_GOVERNED_FORWARD_PAPER_RISK_SCALING_RESEARCH"
            if passed
            else "READY_WITH_STRUCTURAL_STOP_RISK_SCALING_REJECTED"
        )
        source_rows = _source_contract_rows(
            sources=sources,
            dsi009=dsi009,
            dsi007=dsi007,
            market_hash=market_hash,
        )
        summary = {
            "mechanism_id": DSI012_MECHANISM_ID,
            "risk_multiplier": policy.risk_multiplier,
            "base_structural_stop": dict(base_metrics),
            "base_financing": dict(cast(Mapping[str, Any], base_overlay["metrics"])),
            "stress_financing": dict(
                cast(Mapping[str, Any], stress_overlay["metrics"])
            ),
            "benchmark_cagr": benchmark_cagr,
            "capacity_failure_count": sum(
                not bool(row["capacity_passed"]) for row in capacity_rows
            ),
            "acceptance_passed": passed,
            "retrospective_target_match": passed,
            "validated_strategy": False,
            "fresh_unused_holdout_available": False,
            "forward_paper_eligible": passed,
            "automatic_promotion": False,
            "stress_used_for_selection": False,
            "interpretation": (
                "The frozen 1.50x daily-notional overlay clears every "
                "retrospective mechanical target and is eligible only for "
                "governed forward paper evaluation; it is not a validated or "
                "production strategy."
                if passed
                else "The frozen 1.50x structural-stop overlay failed one or "
                "more pre-registered performance, risk, capacity, or "
                "concentration gates."
            ),
        }
        base_financing = cast(Sequence[dict[str, Any]], base_overlay["financing"])
        stress_financing = cast(Sequence[dict[str, Any]], stress_overlay["financing"])
        rows: dict[str, tuple[dict[str, Any], ...]] = {
            "source_contract": tuple(source_rows),
            "rehydration_parity": tuple(parity_rows),
            "base_daily_equity": tuple(dict(row) for row in base_curve),
            "scaled_daily_equity": tuple(
                cast(Sequence[dict[str, Any]], base_overlay["curve"])
            ),
            "stress_daily_equity": tuple(
                cast(Sequence[dict[str, Any]], stress_overlay["curve"])
            ),
            "positions": tuple(position_rows),
            "trades": tuple(trade_rows),
            "transaction_costs": tuple(cost_rows),
            "financing": tuple((*base_financing, *stress_financing)),
            "capacity": tuple(capacity_rows),
            "acceptance": tuple(acceptance_rows),
        }
        return StructuralStopRiskScalingResult(
            source_commit=_source_commit(sources.project_root),
            readiness=readiness,
            blockers=tuple(blockers),
            rows=MappingProxyType(rows),
            summaries=MappingProxyType(summary),
            governance=MappingProxyType(governance_flags()),
        )


def _source_commit(project_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


__all__ = [
    "GovernedStructuralStopRiskScalingEngine",
    "governance_flags",
]
