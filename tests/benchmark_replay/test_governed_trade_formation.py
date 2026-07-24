"""Tests for HTR-010B4 governed trade-formation certification."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.benchmark_replay.governed_adjusted import HTR010B2_CONTRACT_VERSION
from alpha.benchmark_replay.governed_adjusted_stability import (
    B3_READY,
    HTR010B3_ACTIVATION_CONTRACT_VERSION,
    HTR010B3_CONTRACT_VERSION,
)
from alpha.benchmark_replay.governed_trade_formation import (
    B4_BLOCKED_ZERO,
    B4_READY,
    GovernedTradeFormationEngine,
    validate_governed_trade_formation_certificate,
)

_CANDIDATE_FIELDS = (
    "observed_on",
    "period_week",
    "period_month",
    "period_year",
    "eligible_securities",
    "technical_candidates",
    "buy_candidates",
    "strong_buy_candidates",
    "institutional_approvals",
    "portfolio_entries",
    "rejected_ranking",
    "rejected_capital",
    "rejected_liquidity",
    "runtime_status",
)
_APPROVAL_FIELDS = (
    "observed_on",
    "symbol",
    "approved",
    "opportunity_score",
    "opportunity_grade",
    "final_signal",
    "primary_reason_code",
    "rejection_category",
    "explanation",
)
_TRADE_FIELDS = (
    "trade_id",
    "symbol",
    "sector",
    "decision_date",
    "entry_date",
    "exit_date",
    "entry_price",
    "exit_price",
    "initial_stop",
    "target_1",
    "target_2",
    "target_3",
    "quantity",
    "gross_profit_loss",
    "net_profit_loss",
    "gross_return_percent",
    "net_return_percent",
    "realised_r",
    "holding_sessions",
    "holding_days",
    "exit_reason",
    "targets_hit",
    "transaction_cost",
    "slippage_cost",
    "ambiguity_count",
)
_CAPITAL_FIELDS = (
    "observed_on",
    "cash",
    "invested_capital",
    "portfolio_value",
    "idle_cash",
    "capital_utilisation_percent",
    "daily_return_percent",
    "drawdown_percent",
    "open_positions",
    "pending_orders",
)
_POSITION_FIELDS = (
    "observed_on",
    "trade_id",
    "symbol",
    "status",
    "quantity",
    "average_cost",
    "close_price",
    "stop_price",
    "market_value",
    "unrealized_profit_loss",
    "highest_close",
    "holding_sessions",
)


def _dates(count: int) -> tuple[date, ...]:
    start = date(2026, 1, 1)
    return tuple(start + timedelta(days=index) for index in range(count))


def _digest(payload: Mapping[str, object]) -> str:
    value = dict(payload)
    value.pop("report_sha256", None)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, payload: Mapping[str, object]) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_csv(
    path: Path,
    rows: list[dict[str, object]],
    fields: tuple[str, ...],
) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle(
    root: Path,
    dates: tuple[date, ...],
    *,
    price_view: str,
    with_trades: bool,
) -> dict[str, int]:
    root.mkdir(parents=True)
    candidate_rows: list[dict[str, object]] = []
    approval_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    capital_rows: list[dict[str, object]] = []
    position_rows: list[dict[str, object]] = []
    for index, observed_on in enumerate(dates, start=1):
        symbol = f"ALPHA{index:03d}"
        approved = with_trades
        signal = "BUY" if with_trades else "HOLD"
        candidate_rows.append(
            {
                "observed_on": observed_on,
                "period_week": f"{observed_on.year}-W01",
                "period_month": observed_on.strftime("%Y-%m"),
                "period_year": observed_on.year,
                "eligible_securities": 100,
                "technical_candidates": 1,
                "buy_candidates": int(signal == "BUY"),
                "strong_buy_candidates": 0,
                "institutional_approvals": int(approved),
                "portfolio_entries": int(with_trades),
                "rejected_ranking": 0,
                "rejected_capital": 0,
                "rejected_liquidity": 0,
                "runtime_status": "SUCCESS",
            }
        )
        approval_rows.append(
            {
                "observed_on": observed_on,
                "symbol": symbol,
                "approved": str(approved).lower(),
                "opportunity_score": 80 + index / 100,
                "opportunity_grade": "ACCEPTED" if approved else "REJECT",
                "final_signal": signal,
                "primary_reason_code": "ACCEPTED" if approved else "SIGNAL_HOLD",
                "rejection_category": "Unknown" if approved else "No Candidate",
                "explanation": (
                    "All unchanged institutional gates passed."
                    if approved
                    else "Frozen signal was not approvable."
                ),
            }
        )
        portfolio_value = 1_000_000 + (index * 100 if with_trades else 0)
        capital_rows.append(
            {
                "observed_on": observed_on,
                "cash": portfolio_value,
                "invested_capital": 0,
                "portfolio_value": portfolio_value,
                "idle_cash": portfolio_value,
                "capital_utilisation_percent": 0,
                "daily_return_percent": 0,
                "drawdown_percent": 0,
                "open_positions": 0,
                "pending_orders": 0,
            }
        )
        if with_trades:
            trade_id = f"{price_view}-{index:03d}"
            trade_rows.append(
                {
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "sector": "TEST",
                    "decision_date": observed_on,
                    "entry_date": observed_on,
                    "exit_date": observed_on,
                    "entry_price": 100,
                    "exit_price": 101,
                    "initial_stop": 95,
                    "target_1": 105,
                    "target_2": "",
                    "target_3": "",
                    "quantity": 10,
                    "gross_profit_loss": 10,
                    "net_profit_loss": 8,
                    "gross_return_percent": 1,
                    "net_return_percent": 0.8,
                    "realised_r": 0.2,
                    "holding_sessions": 1,
                    "holding_days": 0,
                    "exit_reason": "FORCED_BOUNDARY_EXIT",
                    "targets_hit": "",
                    "transaction_cost": 1,
                    "slippage_cost": 1,
                    "ambiguity_count": 0,
                }
            )
            position_rows.append(
                {
                    "observed_on": observed_on,
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "status": "CLOSED",
                    "quantity": 0,
                    "average_cost": 100,
                    "close_price": 101,
                    "stop_price": 95,
                    "market_value": 0,
                    "unrealized_profit_loss": 0,
                    "highest_close": 101,
                    "holding_sessions": 1,
                }
            )

    files = {
        "candidate_statistics.csv": _write_csv(
            root / "candidate_statistics.csv", candidate_rows, _CANDIDATE_FIELDS
        ),
        "approval_statistics.csv": _write_csv(
            root / "approval_statistics.csv", approval_rows, _APPROVAL_FIELDS
        ),
        "trade_log.csv": _write_csv(root / "trade_log.csv", trade_rows, _TRADE_FIELDS),
        "position_history.csv": _write_csv(
            root / "position_history.csv", position_rows, _POSITION_FIELDS
        ),
        "capital_curve.csv": _write_csv(
            root / "capital_curve.csv", capital_rows, _CAPITAL_FIELDS
        ),
        "portfolio_statistics.csv": _write_csv(
            root / "portfolio_statistics.csv",
            [
                {
                    "starting_capital": 1_000_000,
                    "ending_capital": 1_000_000
                    + (len(dates) * 100 if with_trades else 0),
                    "maximum_drawdown_percent": 0,
                    "average_capital_utilisation_percent": 0,
                }
            ],
            (
                "starting_capital",
                "ending_capital",
                "maximum_drawdown_percent",
                "average_capital_utilisation_percent",
            ),
        ),
        "decision_eligibility.csv": _write_csv(
            root / "decision_eligibility.csv",
            [
                {
                    "status": "ELIGIBLE_POPULATION_AVAILABLE",
                    "minimum_complete_history_sessions": 200,
                    "replay_sessions": len(dates),
                    "eligible_securities": 100,
                    "eligible_security_days": len(dates) * 100,
                    "raw_technical_candidates": len(dates),
                    "raw_buy_or_strong_buy_signals": len(dates) if with_trades else 0,
                    "institutional_approvals": len(dates) if with_trades else 0,
                    "production_influence": "false",
                }
            ],
            (
                "status",
                "minimum_complete_history_sessions",
                "replay_sessions",
                "eligible_securities",
                "eligible_security_days",
                "raw_technical_candidates",
                "raw_buy_or_strong_buy_signals",
                "institutional_approvals",
                "production_influence",
            ),
        ),
        "top_rejection_reasons.csv": _write_csv(
            root / "top_rejection_reasons.csv",
            (
                []
                if with_trades
                else [{"reason_code": "SIGNAL_HOLD", "rejected_candidates": len(dates)}]
            ),
            ("reason_code", "rejected_candidates"),
        ),
    }
    manifest: dict[str, Any] = {
        "baseline_id": f"TEST-{price_view}",
        "benchmark_version": "CABR_v1.0",
        "replay_classification": "OBSERVED_MARKET_REPLAY",
        "run_id": f"TEST-{price_view}",
        "replay_start": dates[0].isoformat(),
        "replay_end": dates[-1].isoformat(),
        "sessions": len(dates),
        "point_in_time_enforced": True,
        "no_future_leakage": True,
        "artifact_hashes": {
            name: _sha256(path) for name, path in sorted(files.items())
        },
        "production_influence": False,
    }
    _write_json(root / "manifest.json", manifest)
    return {
        "sessions": len(dates),
        "candidates": len(dates),
        "approvals": len(dates) if with_trades else 0,
        "trades": len(dates) if with_trades else 0,
        "eligible_securities": 100,
        "eligible_observations": len(dates) * 100,
    }


def _signed_inputs(
    root: Path,
    dates: tuple[date, ...],
    *,
    with_trades: bool,
) -> tuple[Path, Path, Path, Path, Path, Path]:
    raw_root = root / "raw"
    adjusted_root = root / "adjusted"
    raw = _bundle(raw_root, dates, price_view="RAW", with_trades=with_trades)
    adjusted = _bundle(
        adjusted_root,
        dates,
        price_view="ADJUSTED",
        with_trades=with_trades,
    )
    b2: dict[str, Any] = {
        "contract_version": HTR010B2_CONTRACT_VERSION,
        "readiness_decision": "READY_FOR_GOVERNED_ADJUSTED_BENCHMARK_RESEARCH",
        "decision_metrics_evaluated": True,
        "governed_adjusted_benchmark_enabled": True,
        "raw_summary": {
            "session_count": raw["sessions"],
            "technical_candidate_count": raw["candidates"],
            "institutional_approval_count": raw["approvals"],
            "trade_count": raw["trades"],
            "eligible_security_count": raw["eligible_securities"],
            "eligible_security_observation_count": raw["eligible_observations"],
        },
        "adjusted_summary": {
            "session_count": adjusted["sessions"],
            "technical_candidate_count": adjusted["candidates"],
            "institutional_approval_count": adjusted["approvals"],
            "trade_count": adjusted["trades"],
            "eligible_security_count": adjusted["eligible_securities"],
            "eligible_security_observation_count": adjusted["eligible_observations"],
        },
        "comparison": {
            "benchmark_population_nonempty": True,
            "unexplained_divergence_count": 0,
            "readiness_blockers": [],
        },
        "active_replay_integration": False,
        "production_influence": False,
    }
    b2["report_sha256"] = _digest(b2)
    b2_path = _write_json(root / "b2.json", b2)

    windows = []
    base, remainder = divmod(len(dates), 4)
    offset = 0
    for index in range(4):
        size = base + (1 if index < remainder else 0)
        subset = dates[offset : offset + size]
        offset += size
        windows.append(
            {
                "window_index": index + 1,
                "start_date": subset[0].isoformat(),
                "end_date": subset[-1].isoformat(),
                "sessions": len(subset),
                "paired_decisions": len(subset),
            }
        )
    b3: dict[str, Any] = {
        "contract_version": HTR010B3_CONTRACT_VERSION,
        "b2_report_sha256": b2["report_sha256"],
        "session_count": len(dates),
        "window_stability": windows,
        "evidence_summary": {
            "raw_decision_count": len(dates),
            "adjusted_decision_count": len(dates),
            "paired_decision_count": len(dates),
            "raw_trade_count": raw["trades"],
            "adjusted_trade_count": adjusted["trades"],
        },
        "readiness_decision": B3_READY,
        "governed_adjusted_research_enabled": True,
        "research_scope": "GOVERNED_BENCHMARK_RESEARCH_ONLY",
        "live_scoring_enabled": False,
        "recommendation_influence": False,
        "portfolio_policy_influence": False,
        "execution_influence": False,
        "learning_mutation_enabled": False,
        "active_replay_integration": False,
        "production_influence": False,
    }
    b3["report_sha256"] = _digest(b3)
    b3_path = _write_json(root / "b3.json", b3)
    activation: dict[str, Any] = {
        "contract_version": HTR010B3_ACTIVATION_CONTRACT_VERSION,
        "stability_certificate_sha256": b3["report_sha256"],
        "b2_report_sha256": b2["report_sha256"],
        "activation_decision": B3_READY,
        "governed_adjusted_research_enabled": True,
        "research_scope": "GOVERNED_BENCHMARK_RESEARCH_ONLY",
        "allowed_consumers": ["BENCHMARK_RESEARCH"],
        "live_scoring_enabled": False,
        "recommendation_influence": False,
        "portfolio_policy_influence": False,
        "execution_influence": False,
        "learning_mutation_enabled": False,
        "active_replay_integration": False,
        "production_influence": False,
    }
    activation["report_sha256"] = _digest(activation)
    activation_path = _write_json(root / "activation.json", activation)
    action_path = _write_json(
        root / "actions.json",
        {
            "records": [
                {
                    "status": "RESOLVED",
                    "action_type": "SPLIT",
                    "effective_date": dates[-1].isoformat(),
                    "symbol": "ALPHA001",
                }
            ]
        },
    )
    return b2_path, b3_path, activation_path, raw_root, adjusted_root, action_path


def test_zero_trade_population_is_explained_and_blocked(tmp_path: Path) -> None:
    inputs = _signed_inputs(tmp_path, _dates(8), with_trades=False)
    output = tmp_path / "output"

    result = GovernedTradeFormationEngine().run(
        b2_report=inputs[0],
        b3_certificate=inputs[1],
        b3_activation_contract=inputs[2],
        raw_benchmark=inputs[3],
        adjusted_benchmark=inputs[4],
        corporate_action_artifact=inputs[5],
        output=output,
    )

    assert result.report["readiness_decision"] == B4_BLOCKED_ZERO
    assert result.report["zero_trade_policy_consistent"] is True
    assert result.report["implementation_defect_count"] == 0
    assert result.report["unexplained_trade_divergence_count"] == 0
    assert result.report["governed_adjusted_trade_research_enabled"] is False
    assert len(result.paths) == 8
    assert len(result.funnel_rows) == 16
    certificate = validate_governed_trade_formation_certificate(result.paths[0])
    assert certificate["report_sha256"] == result.report["report_sha256"]
    with pytest.raises(ValueError, match="does not permit"):
        validate_governed_trade_formation_certificate(
            result.paths[0],
            require_ready=True,
        )


def test_nonvacuous_paired_trade_population_can_be_ready(tmp_path: Path) -> None:
    inputs = _signed_inputs(tmp_path, _dates(20), with_trades=True)

    result = GovernedTradeFormationEngine().run(
        b2_report=inputs[0],
        b3_certificate=inputs[1],
        b3_activation_contract=inputs[2],
        raw_benchmark=inputs[3],
        adjusted_benchmark=inputs[4],
        corporate_action_artifact=inputs[5],
        output=tmp_path / "output",
    )

    assert result.report["readiness_decision"] == B4_READY
    assert result.report["trade_pairing_summary"]["paired_trade_count"] == 20
    assert result.report["economic_metrics_evaluated"] is True
    assert result.report["governed_adjusted_trade_research_enabled"] is True
    validate_governed_trade_formation_certificate(
        result.paths[0],
        require_ready=True,
    )


def test_tampered_benchmark_artifact_fails_closed(tmp_path: Path) -> None:
    inputs = _signed_inputs(tmp_path, _dates(8), with_trades=False)
    approval_path = inputs[3] / "approval_statistics.csv"
    approval_path.write_text(
        approval_path.read_text(encoding="utf-8") + "tampered\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="digest mismatch"):
        GovernedTradeFormationEngine().run(
            b2_report=inputs[0],
            b3_certificate=inputs[1],
            b3_activation_contract=inputs[2],
            raw_benchmark=inputs[3],
            adjusted_benchmark=inputs[4],
            corporate_action_artifact=inputs[5],
            output=tmp_path / "output",
        )


def test_public_command_is_registered() -> None:
    result = CliRunner().invoke(benchmark_app, ["--help"])

    assert result.exit_code == 0
    assert "governed-trade-formation" in result.stdout
