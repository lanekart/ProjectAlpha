"""Governed exhaustive stop-target matrix for the frozen DSI-011A entry set."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from alpha.backtest.research_runner import ResearchBacktestResult, ResearchTrade
from alpha.research.lab_data_contract import ResearchDataContractAuditor
from alpha.research.lab_models import (
    AlphaSignalSource,
    ComparisonOperator,
    Condition,
    ConditionGroup,
    LogicOperator,
    ResearchExperimentSpec,
    RuleKind,
    StopPolicy,
    StopRule,
    StrategyMode,
    TargetPolicy,
    TargetRule,
)
from alpha.research.lab_service import ConversationalResearchLab

MATRIX_VERSION = "DSI-011B-stop-target-matrix-v1.0.0"
PRODUCTION_INFLUENCE = False


@dataclass(frozen=True, slots=True)
class StopChoice:
    policy_id: str
    label: str
    policy: StopPolicy


@dataclass(frozen=True, slots=True)
class TargetChoice:
    policy_id: str
    label: str
    policy: TargetPolicy


@dataclass(frozen=True, slots=True)
class ExecutionLevelAudit:
    status: str
    missing_stop_count: int
    invalid_stop_count: int
    missing_target_count: int
    invalid_target_count: int
    samples: tuple[dict[str, str], ...]

    @property
    def valid(self) -> bool:
        return self.status == "VALID"

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "missing_stop_count": self.missing_stop_count,
            "invalid_stop_count": self.invalid_stop_count,
            "missing_target_count": self.missing_target_count,
            "invalid_target_count": self.invalid_target_count,
            "samples": list(self.samples),
        }


def stop_choices() -> tuple[StopChoice, ...]:
    return (
        StopChoice(
            "STOP_FIXED_5",
            "5% fixed stop",
            StopPolicy(rules=(StopRule("FIXED_PERCENT", Decimal("5")),)),
        ),
        StopChoice(
            "STOP_FIXED_8",
            "8% fixed stop",
            StopPolicy(rules=(StopRule("FIXED_PERCENT", Decimal("8")),)),
        ),
        StopChoice(
            "STOP_FIXED_10",
            "10% fixed stop",
            StopPolicy(rules=(StopRule("FIXED_PERCENT", Decimal("10")),)),
        ),
        StopChoice(
            "STOP_ATR_2",
            "2 ATR stop",
            StopPolicy(rules=(StopRule("ATR", Decimal("2")),)),
        ),
        StopChoice(
            "STOP_STRUCTURAL_10D",
            "STOP-STRUCTURAL-10D",
            StopPolicy(rules=(StopRule("STOP-STRUCTURAL-10D"),)),
        ),
    )


def target_choices() -> tuple[TargetChoice, ...]:
    return (
        TargetChoice(
            "TARGET_FIXED_10",
            "10% fixed target",
            TargetPolicy(rules=(TargetRule("FIXED_PERCENT", Decimal("10")),)),
        ),
        TargetChoice(
            "TARGET_FIXED_20",
            "20% fixed target",
            TargetPolicy(rules=(TargetRule("FIXED_PERCENT", Decimal("20")),)),
        ),
        TargetChoice(
            "TARGET_R_2",
            "2R target",
            TargetPolicy(rules=(TargetRule("R_MULTIPLE", Decimal("2")),)),
        ),
        TargetChoice(
            "TARGET_R_3",
            "3R target",
            TargetPolicy(rules=(TargetRule("R_MULTIPLE", Decimal("3")),)),
        ),
        TargetChoice("TARGET_NONE", "No fixed target", TargetPolicy()),
    )


def matrix_size() -> int:
    return len(stop_choices()) * len(target_choices())


def build_frozen_parent(
    *,
    start_date: date,
    end_date: date,
) -> ResearchExperimentSpec:
    """Reproduce the fixed entry population used by DSI-011A experiments E/F."""

    return ResearchExperimentSpec(
        experiment_id="DSI011B-PARENT",
        research_session_id="DSI011B-STOP-TARGET-MATRIX",
        experiment_name=(
            "Frozen filtered retrospective Alpha BUY/STRONG_BUY entry population "
            "for exhaustive stop-target matrix"
        ),
        parent_experiment_id=None,
        strategy_mode=StrategyMode.HYBRID,
        data_start=start_date,
        data_end=end_date,
        base_signal_source=("BUY", "STRONG_BUY"),
        entry_conditions=ConditionGroup(
            operator=LogicOperator.ALL,
            conditions=(
                Condition(
                    condition_id="RSI_14_ABOVE_50",
                    kind=RuleKind.INDICATOR,
                    name="RSI",
                    operator=ComparisonOperator.ABOVE,
                    value=Decimal("50"),
                    period=14,
                ),
                Condition(
                    condition_id="CLOSE_ABOVE_SMA_200",
                    kind=RuleKind.INDICATOR,
                    name="SMA",
                    operator=ComparisonOperator.ABOVE,
                    period=200,
                    reference="CLOSE",
                ),
                Condition(
                    condition_id="VOLUME_RATIO_1.5_20",
                    kind=RuleKind.INDICATOR,
                    name="VOLUME_RATIO",
                    operator=ComparisonOperator.AT_LEAST,
                    value=Decimal("1.5"),
                    period=20,
                ),
            ),
        ),
        stop_policy=StopPolicy(rules=(StopRule("FIXED_PERCENT", Decimal("8")),)),
        target_policy=TargetPolicy(),
        maximum_holding_sessions=20,
        maximum_concurrent_positions=10,
        alpha_signal_source=AlphaSignalSource.RETROSPECTIVE_FROZEN_ALPHA_REPLAY,
        production_influence=False,
    )


def audit_execution_levels(
    result: ResearchBacktestResult,
    spec: ResearchExperimentSpec,
) -> ExecutionLevelAudit:
    """Fail closed when requested execution levels are absent or nonsensical."""

    requires_stop = bool(spec.stop_policy.rules)
    requires_target = bool(spec.target_policy.rules)
    missing_stop = 0
    invalid_stop = 0
    missing_target = 0
    invalid_target = 0
    samples: list[dict[str, str]] = []

    for trade in result.trades:
        stop_reason: str | None = None
        target_reason: str | None = None
        if requires_stop:
            if trade.stop_price is None:
                missing_stop += 1
                stop_reason = "MISSING_STOP"
            elif trade.stop_price <= 0 or trade.stop_price >= trade.entry_price:
                invalid_stop += 1
                stop_reason = "INVALID_STOP_NOT_BELOW_ENTRY"
        if requires_target:
            if trade.target_price is None:
                missing_target += 1
                target_reason = "MISSING_TARGET"
            elif trade.target_price <= trade.entry_price:
                invalid_target += 1
                target_reason = "INVALID_TARGET_NOT_ABOVE_ENTRY"
        if (stop_reason or target_reason) and len(samples) < 25:
            samples.append(
                _level_sample(
                    trade,
                    stop_reason=stop_reason,
                    target_reason=target_reason,
                )
            )

    valid = not any((missing_stop, invalid_stop, missing_target, invalid_target))
    return ExecutionLevelAudit(
        status="VALID" if valid else "INVALID_EXECUTION_LEVELS",
        missing_stop_count=missing_stop,
        invalid_stop_count=invalid_stop,
        missing_target_count=missing_target,
        invalid_target_count=invalid_target,
        samples=tuple(samples),
    )


def _level_sample(
    trade: ResearchTrade,
    *,
    stop_reason: str | None,
    target_reason: str | None,
) -> dict[str, str]:
    return {
        "trade_id": trade.trade_id,
        "symbol": trade.symbol,
        "entry_price": str(trade.entry_price),
        "stop_price": "" if trade.stop_price is None else str(trade.stop_price),
        "target_price": "" if trade.target_price is None else str(trade.target_price),
        "stop_reason": stop_reason or "",
        "target_reason": target_reason or "",
    }


def run_matrix(*, database: Path, output: Path) -> dict[str, object]:
    """Execute and persist the exact governed 5-by-5 policy cross-product."""

    if not database.is_file():
        raise FileNotFoundError(f"Historical Truth database not found: {database}")
    output.mkdir(parents=True, exist_ok=True)

    contract = ResearchDataContractAuditor().audit(database)
    if not contract.ready:
        raise RuntimeError(
            "research data contract is not ready: " + ", ".join(contract.blockers)
        )
    signal_source = AlphaSignalSource.RETROSPECTIVE_FROZEN_ALPHA_REPLAY
    if not contract.signal_source_ready(signal_source):
        raise RuntimeError("retrospective frozen Alpha signal population is not ready")
    if contract.actual_start is None or contract.actual_end is None:
        raise RuntimeError("certified research boundary is unavailable")

    lab = ConversationalResearchLab(database=database, root=output)
    parent = build_frozen_parent(
        start_date=contract.actual_start,
        end_date=contract.actual_end,
    )
    frame = lab._load_frame(parent)
    featured = lab.feature_engine.build(frame, parent)

    rows: list[dict[str, object]] = []
    for stop_index, stop in enumerate(stop_choices(), start=1):
        for target_index, target in enumerate(target_choices(), start=1):
            experiment_id = f"DSI011B-S{stop_index:02d}-T{target_index:02d}"
            spec = replace(
                parent,
                experiment_id=experiment_id,
                parent_experiment_id=parent.experiment_id,
                stop_policy=stop.policy,
                target_policy=target.policy,
            )
            result = lab.runner.run(featured, spec)
            summary = result.summary()
            level_audit = audit_execution_levels(result, spec)
            row: dict[str, object] = {
                "experiment_id": experiment_id,
                "stop_id": stop.policy_id,
                "stop_label": stop.label,
                "target_id": target.policy_id,
                "target_label": target.label,
                "execution_status": level_audit.status,
                **summary,
                "missing_stop_count": level_audit.missing_stop_count,
                "invalid_stop_count": level_audit.invalid_stop_count,
                "missing_target_count": level_audit.missing_target_count,
                "invalid_target_count": level_audit.invalid_target_count,
            }
            rows.append(row)
            combo_root = output / "runs" / experiment_id
            combo_root.mkdir(parents=True, exist_ok=True)
            _write_json(combo_root / "spec.json", spec.as_dict())
            _write_json(combo_root / "summary.json", row)
            _write_json(
                combo_root / "execution_level_audit.json",
                level_audit.as_dict(),
            )
            print(
                f"{experiment_id} {stop.label} × {target.label}: "
                f"{level_audit.status}; CAGR={summary.get('gross_cagr_percent')}; "
                f"MDD={summary.get('maximum_drawdown_percent')}",
                flush=True,
            )

    ranked_valid = sorted(
        (row for row in rows if row["execution_status"] == "VALID"),
        key=_ranking_key,
    )
    invalid = [row for row in rows if row["execution_status"] != "VALID"]
    source_commit = _source_commit()
    result_payload: dict[str, object] = {
        "matrix_version": MATRIX_VERSION,
        "source_commit": source_commit,
        "parent_specification_sha256": parent.specification_sha256,
        "data_start": contract.actual_start.isoformat(),
        "data_end": contract.actual_end.isoformat(),
        "matrix_size": matrix_size(),
        "valid_combination_count": len(ranked_valid),
        "invalid_combination_count": len(invalid),
        "same_session_policy": parent.same_session_policy.value,
        "maximum_holding_sessions": parent.maximum_holding_sessions,
        "maximum_concurrent_positions": parent.maximum_concurrent_positions,
        "transaction_cost_model": parent.transaction_cost_model,
        "slippage_model": parent.slippage_model,
        "results_are_gross_of_costs": True,
        "production_influence": PRODUCTION_INFLUENCE,
        "ranked_valid_results": ranked_valid,
        "invalid_results": invalid,
        "all_results": rows,
    }
    logical_hash = hashlib.sha256(
        json.dumps(
            result_payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()
    result_payload["artifact_logical_sha256"] = logical_hash

    _write_json(output / "stop_target_matrix.json", result_payload)
    _write_csv(output / "stop_target_matrix.csv", rows)
    _write_markdown(output / "stop_target_matrix.md", result_payload)
    _write_json(
        output / "matrix_manifest.json",
        {
            "matrix_version": MATRIX_VERSION,
            "source_commit": source_commit,
            "parent_specification_sha256": parent.specification_sha256,
            "artifact_logical_sha256": logical_hash,
            "matrix_size": matrix_size(),
            "production_influence": False,
        },
    )
    print(f"Matrix complete: {matrix_size()} combinations", flush=True)
    print(f"Valid combinations: {len(ranked_valid)}", flush=True)
    print(f"Invalid combinations: {len(invalid)}", flush=True)
    print(f"Artifact logical SHA-256: {logical_hash}", flush=True)
    print(f"Results: {output / 'stop_target_matrix.csv'}", flush=True)
    return result_payload


def _ranking_key(row: dict[str, object]) -> tuple[Decimal, Decimal, str]:
    cagr = _decimal_or(row.get("gross_cagr_percent"), Decimal("-Infinity"))
    drawdown = _decimal_or(
        row.get("maximum_drawdown_percent"),
        Decimal("-Infinity"),
    )
    return (-cagr, -drawdown, str(row["experiment_id"]))


def _decimal_or(value: object, fallback: Decimal) -> Decimal:
    if value is None or value == "":
        return fallback
    return Decimal(str(value))


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(path: Path, payload: dict[str, object]) -> None:
    ranked = payload["ranked_valid_results"]
    assert isinstance(ranked, list)
    lines = [
        "# DSI-011B Stop × Target Matrix",
        "",
        f"- Matrix size: {payload['matrix_size']}",
        f"- Valid combinations: {payload['valid_combination_count']}",
        f"- Invalid combinations: {payload['invalid_combination_count']}",
        f"- Data range: {payload['data_start']} to {payload['data_end']}",
        "- Results are gross of transaction costs and slippage.",
        "- PRODUCTION_INFLUENCE=false",
        "",
        "## Ranked valid combinations",
        "",
        (
            "| Rank | Stop | Target | CAGR % | Max drawdown % | Trades | "
            "Win rate % | Expectancy % |"
        ),
        "|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for rank, row in enumerate(ranked, start=1):
        assert isinstance(row, dict)
        lines.append(
            "| "
            + " | ".join(
                (
                    str(rank),
                    str(row["stop_label"]),
                    str(row["target_label"]),
                    str(row.get("gross_cagr_percent")),
                    str(row.get("maximum_drawdown_percent")),
                    str(row.get("trade_count")),
                    str(row.get("win_rate_percent")),
                    str(row.get("expectancy_percent")),
                )
            )
            + " |"
        )
    lines.extend(
        (
            "",
            "## Governance",
            "",
            f"- Artifact logical SHA-256: `{payload['artifact_logical_sha256']}`",
            "- Invalid execution-level combinations are excluded from ranking.",
            "- No automatic strategy or stop-policy promotion.",
            "- PRODUCTION_INFLUENCE=false",
            "",
        )
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _source_commit() -> str:
    try:
        return subprocess.check_output(
            ("git", "rev-parse", "HEAD"),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the governed DSI-011B 5×5 stop-target matrix."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("alpha_data/warehouse/historical_truth.duckdb"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".alpha/research/dsi011b_stop_target_matrix"),
    )
    args = parser.parse_args()
    run_matrix(database=args.database, output=args.output)


if __name__ == "__main__":
    main()


__all__ = [
    "ExecutionLevelAudit",
    "MATRIX_VERSION",
    "StopChoice",
    "TargetChoice",
    "audit_execution_levels",
    "build_frozen_parent",
    "matrix_size",
    "run_matrix",
    "stop_choices",
    "target_choices",
]
