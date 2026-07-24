from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.benchmark_replay.governed_adjusted_stability import (
    B3_BLOCKED,
    B3_READY,
    GovernedAdjustedStabilityEngine,
    validate_governed_adjusted_research_activation,
)


def _digest(payload: dict[str, object]) -> str:
    value = dict(payload)
    value.pop("report_sha256", None)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def _write_csv(path: Path, rows: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = tuple(rows[0]) if rows else ("record",)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _dates(count: int) -> tuple[date, ...]:
    first = date(2026, 1, 1)
    return tuple(first + timedelta(days=index) for index in range(count))


def _bundle(
    root: Path,
    *,
    dates: tuple[date, ...],
    adjusted: bool,
) -> dict[str, object]:
    candidates: list[dict[str, object]] = []
    approvals: list[dict[str, object]] = []
    capital: list[dict[str, object]] = []
    for index, observed_on in enumerate(dates):
        adjusted_flip = adjusted and index in {5, 25, 45, 65}
        candidates.append(
            {
                "observed_on": observed_on,
                "period_week": observed_on.strftime("%Y-W%W"),
                "period_month": observed_on.strftime("%Y-%m"),
                "period_year": str(observed_on.year),
                "eligible_securities": 2,
                "technical_candidates": 2,
                "buy_candidates": 1 + int(adjusted_flip),
                "strong_buy_candidates": 0,
                "institutional_approvals": 1 + int(adjusted_flip),
                "portfolio_entries": int(index % 20 == 0),
                "rejected_ranking": 0,
                "rejected_capital": 0,
                "rejected_liquidity": 0,
                "runtime_status": "SUCCESS",
            }
        )
        approvals.extend(
            [
                {
                    "observed_on": observed_on,
                    "symbol": "ALPHA",
                    "approved": adjusted_flip,
                    "opportunity_score": 71 if adjusted else 70,
                    "opportunity_grade": "ACCEPTED" if adjusted_flip else "REJECT",
                    "final_signal": "BUY" if adjusted_flip else "HOLD",
                    "primary_reason_code": (
                        "ACCEPTED" if adjusted_flip else "WEAK_VERDICT"
                    ),
                    "rejection_category": (
                        "Unknown" if adjusted_flip else "No Candidate"
                    ),
                    "explanation": "synthetic",
                },
                {
                    "observed_on": observed_on,
                    "symbol": "BETA",
                    "approved": True,
                    "opportunity_score": 80,
                    "opportunity_grade": "ACCEPTED",
                    "final_signal": "BUY",
                    "primary_reason_code": "ACCEPTED",
                    "rejection_category": "Unknown",
                    "explanation": "synthetic",
                },
            ]
        )
        capital.append(
            {
                "observed_on": observed_on,
                "cash": 900000,
                "invested_capital": 100000,
                "portfolio_value": 1000000 + index * (110 if adjusted else 100),
                "idle_cash": 900000,
                "capital_utilisation_percent": 10,
                "daily_return_percent": 0,
                "drawdown_percent": 0,
                "open_positions": 1,
                "pending_orders": 0,
            }
        )

    trade_return = "6" if adjusted else "5"
    trades = [
        {
            "trade_id": "trade-1",
            "symbol": "ALPHA",
            "decision_date": dates[0],
            "entry_date": dates[1],
            "exit_date": dates[10],
            "net_return_percent": trade_return,
            "exit_reason": "TARGET",
        }
    ]
    eligibility = [
        {
            "status": "ELIGIBLE_POPULATION_AVAILABLE",
            "minimum_complete_history_sessions": 200,
            "replay_sessions": len(dates),
            "eligible_securities": 2,
            "eligible_security_days": len(dates) * 2,
            "raw_technical_candidates": len(dates) * 2,
            "raw_buy_or_strong_buy_signals": len(dates),
            "institutional_approvals": sum(
                int(row["institutional_approvals"]) for row in candidates
            ),
            "production_influence": False,
        }
    ]

    files = {
        "candidate_statistics.csv": candidates,
        "approval_statistics.csv": approvals,
        "trade_log.csv": trades,
        "capital_curve.csv": capital,
        "decision_eligibility.csv": eligibility,
    }
    hashes: dict[str, str] = {}
    for name, rows in files.items():
        path = _write_csv(root / name, rows)
        hashes[name] = _file_hash(path)

    manifest = {
        "baseline_id": "CABR_RESEARCH_TEST",
        "benchmark_version": "CABR_v1.0",
        "replay_classification": "OBSERVED_MARKET_REPLAY",
        "run_id": "ADJUSTED" if adjusted else "RAW",
        "replay_start": dates[0].isoformat(),
        "replay_end": dates[-1].isoformat(),
        "sessions": len(dates),
        "universe_label": "TEST",
        "historical_index_membership": "UNKNOWN / NOT USED",
        "historical_sector_membership": "UNKNOWN / NOT ASSERTED",
        "point_in_time_enforced": True,
        "no_future_leakage": True,
        "policy": {},
        "versions": {},
        "input_hash": "adjusted" if adjusted else "raw",
        "artifact_hashes": hashes,
        "notes": [],
        "production_influence": False,
    }
    _write_json(root / "manifest.json", manifest)
    return {
        "session_count": len(dates),
        "eligible_security_count": 2,
        "eligible_security_observation_count": len(dates) * 2,
        "technical_candidate_count": len(dates) * 2,
        "institutional_approval_count": sum(
            int(row["institutional_approvals"]) for row in candidates
        ),
        "trade_count": 1,
        "cagr_percent": "0",
        "maximum_drawdown_percent": "0",
        "expectancy_percent": trade_return,
    }


def _evidence(tmp_path: Path, *, sessions: int = 80) -> dict[str, Path]:
    dates = _dates(sessions)
    raw_summary = _bundle(tmp_path / "raw", dates=dates, adjusted=False)
    adjusted_summary = _bundle(tmp_path / "adjusted", dates=dates, adjusted=True)
    b2: dict[str, object] = {
        "contract_version": "HTR-010B2-v1.0.0",
        "raw_summary": raw_summary,
        "adjusted_summary": adjusted_summary,
        "comparison": {
            "benchmark_population_nonempty": True,
            "readiness_blockers": [],
            "unexplained_divergence_count": 0,
            "production_influence": False,
        },
        "readiness_decision": "READY_FOR_GOVERNED_ADJUSTED_BENCHMARK_RESEARCH",
        "governed_adjusted_benchmark_enabled": True,
        "decision_metrics_evaluated": True,
        "active_replay_integration": False,
        "production_influence": False,
    }
    b2["report_sha256"] = _digest(b2)
    b2_path = _write_json(tmp_path / "b2.json", b2)
    action = _write_json(
        tmp_path / "actions.json",
        {
            "records": [
                {
                    "event_id": "ALPHA:SPLIT",
                    "security_id": "SEC-ALPHA",
                    "symbol": "ALPHA",
                    "action_type": "SPLIT",
                    "effective_date": dates[60].isoformat(),
                    "announced_at": dates[40].isoformat(),
                    "status": "RESOLVED",
                }
            ]
        },
    )
    return {
        "b2": b2_path,
        "raw": tmp_path / "raw",
        "adjusted": tmp_path / "adjusted",
        "actions": action,
    }


def test_b3_command_is_registered() -> None:
    result = CliRunner().invoke(benchmark_app, ["--help"])

    assert result.exit_code == 0, result.output
    assert "governed-adjusted-stability" in result.output


def test_b3_certifies_balanced_windows_and_research_activation(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    output = tmp_path / "b3"

    result = GovernedAdjustedStabilityEngine().run(
        b2_report=evidence["b2"],
        raw_benchmark=evidence["raw"],
        adjusted_benchmark=evidence["adjusted"],
        corporate_action_artifact=evidence["actions"],
        output=output,
    )

    assert result.report["readiness_decision"] == B3_READY
    assert result.report["governed_adjusted_research_enabled"] is True
    assert len(result.windows) == 4
    assert {item.sessions for item in result.windows} == {20}
    summary = result.report["evidence_summary"]
    assert summary["paired_decision_count"] == 160
    assert summary["action_affected_paired_decision_count"] > 0
    assert summary["unaffected_paired_decision_count"] > 0
    assert summary["approval_flip_count"] == 4
    activation = validate_governed_adjusted_research_activation(
        stability_certificate=output / "htr010b3_stability_certificate.json",
        activation_contract=output / "htr010b3_research_activation_contract.json",
    )
    assert activation["research_scope"] == "GOVERNED_BENCHMARK_RESEARCH_ONLY"
    assert activation["production_influence"] is False


def test_b3_blocks_insufficient_window_evidence(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path, sessions=60)
    output = tmp_path / "b3"

    result = GovernedAdjustedStabilityEngine().run(
        b2_report=evidence["b2"],
        raw_benchmark=evidence["raw"],
        adjusted_benchmark=evidence["adjusted"],
        corporate_action_artifact=evidence["actions"],
        output=output,
    )

    assert result.report["readiness_decision"] == B3_BLOCKED
    assert result.report["governed_adjusted_research_enabled"] is False
    assert "INSUFFICIENT_REPLAY_SESSIONS" in result.report["readiness_blockers"]
    with pytest.raises(ValueError, match="not ready"):
        validate_governed_adjusted_research_activation(
            stability_certificate=output / "htr010b3_stability_certificate.json",
            activation_contract=output
            / "htr010b3_research_activation_contract.json",
        )


def test_b3_rejects_tampered_benchmark_artifact(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    candidate_path = evidence["raw"] / "candidate_statistics.csv"
    candidate_path.write_text(candidate_path.read_text() + "tampered\n")

    with pytest.raises(ValueError, match="digest mismatch"):
        GovernedAdjustedStabilityEngine().run(
            b2_report=evidence["b2"],
            raw_benchmark=evidence["raw"],
            adjusted_benchmark=evidence["adjusted"],
            corporate_action_artifact=evidence["actions"],
            output=tmp_path / "b3",
        )


def test_activation_gate_rejects_restamped_production_influence(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    output = tmp_path / "b3"
    GovernedAdjustedStabilityEngine().run(
        b2_report=evidence["b2"],
        raw_benchmark=evidence["raw"],
        adjusted_benchmark=evidence["adjusted"],
        corporate_action_artifact=evidence["actions"],
        output=output,
    )
    contract_path = output / "htr010b3_research_activation_contract.json"
    contract = json.loads(contract_path.read_text())
    contract["production_influence"] = True
    contract["report_sha256"] = _digest(contract)
    _write_json(contract_path, contract)

    with pytest.raises(ValueError, match="production_influence"):
        validate_governed_adjusted_research_activation(
            stability_certificate=output / "htr010b3_stability_certificate.json",
            activation_contract=contract_path,
        )
