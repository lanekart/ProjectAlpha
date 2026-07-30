"""Governed DSI-011E Alpha eligibility-window sweep.

This research-only audit separates Alpha's selection date from the technical
20-DMA reclaim trigger.  It does not modify production recommendation,
portfolio, approval, or risk policy.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pandas as pd

from alpha.research.reclaim_portfolio_challenger import (
    ChallengerConfig,
    ChallengerResult,
    engineer_signals,
    load_research_frame,
    simulate_challenger,
)

SWEEP_VERSION = "DSI-011E-ALPHA-ELIGIBILITY-WINDOW-v1.0.0"
PRODUCTION_INFLUENCE = False
WINDOWS: tuple[int, ...] = (1, 3, 5, 10, 20)
_ZERO = Decimal("0")
_PARITY_TOLERANCE = Decimal("0.0001")
_TECHNICAL_GATES: tuple[str, ...] = (
    "long_term_trend_ok",
    "rising_sma20_ok",
    "reclaim_ok",
    "momentum_ok",
    "volume_contraction_ok",
    "volume_expansion_ok",
)


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    policy_id: str
    full_risk_fraction: Decimal
    throttled_risk_fraction: Decimal

    def as_dict(self) -> dict[str, object]:
        return cast(dict[str, object], _jsonable(asdict(self)))


RISK_POLICIES: tuple[RiskPolicy, ...] = (
    RiskPolicy("FLAT_1PCT", Decimal("0.01"), Decimal("0.005")),
    RiskPolicy("UNIFORM_1_5PCT", Decimal("0.015"), Decimal("0.0075")),
)


@dataclass(frozen=True, slots=True)
class ActiveEligibility:
    security_id: str
    symbol: str
    origin_date: date
    final_signal: str
    recommendation_score: Decimal
    origin_regime: str
    remaining_sessions: int
    age_sessions: int = 0


@dataclass(frozen=True, slots=True)
class EligibilityAudit:
    window_sessions: int
    alpha_signal_count: int
    eligibility_issued_count: int
    eligibility_superseded_count: int
    eligibility_expired_count: int
    boundary_untriggered_count: int
    technical_trigger_count: int
    trigger_origin_regime_counts: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return cast(dict[str, object], _jsonable(asdict(self)))


def build_window_signals(
    featured: pd.DataFrame,
    *,
    window_sessions: int,
) -> tuple[pd.DataFrame, list[dict[str, object]], EligibilityAudit]:
    """Create point-in-time technical triggers from bounded Alpha eligibility."""

    if window_sessions < 1:
        raise ValueError("eligibility window must be at least one session")
    required = {
        "trading_date",
        "security_id",
        "symbol",
        "final_signal",
        "regime",
        "recommendation_score",
        "alpha_signal_ok",
        *_TECHNICAL_GATES,
    }
    missing = required - set(featured.columns)
    if missing:
        raise ValueError(f"eligibility frame missing columns: {sorted(missing)}")

    result = featured.copy().reset_index(drop=True)
    result["trading_date"] = pd.to_datetime(result["trading_date"])
    result = result.sort_values(["security_id", "trading_date"], kind="stable")
    result["research_signal"] = False
    result["eligibility_origin_date"] = None
    result["eligibility_origin_regime"] = None
    result["eligibility_age_sessions"] = None

    ledger: list[dict[str, object]] = []
    issued_count = 0
    superseded_count = 0
    expired_count = 0
    boundary_count = 0
    trigger_count = 0
    regime_counts: dict[str, int] = {}

    for _, security_rows in result.groupby("security_id", sort=False):
        active: ActiveEligibility | None = None
        for index, row in security_rows.iterrows():
            trading_date = cast(pd.Timestamp, row["trading_date"]).date()
            has_alpha_signal = bool(row["alpha_signal_ok"])
            if has_alpha_signal:
                if active is not None:
                    superseded_count += 1
                issued_count += 1
                active = ActiveEligibility(
                    security_id=str(row["security_id"]),
                    symbol=str(row["symbol"]),
                    origin_date=trading_date,
                    final_signal=str(row["final_signal"]),
                    recommendation_score=_decimal(row["recommendation_score"]),
                    origin_regime=_normalise_regime(row["regime"]),
                    remaining_sessions=window_sessions,
                )

            technical_ok = all(bool(row[gate]) for gate in _TECHNICAL_GATES)
            if active is not None and technical_ok:
                result.at[index, "research_signal"] = True
                result.at[index, "final_signal"] = active.final_signal
                result.at[index, "recommendation_score"] = float(
                    active.recommendation_score
                )
                result.at[index, "eligibility_origin_date"] = (
                    active.origin_date.isoformat()
                )
                result.at[index, "eligibility_origin_regime"] = active.origin_regime
                result.at[index, "eligibility_age_sessions"] = active.age_sessions
                ledger.append(
                    {
                        "security_id": active.security_id,
                        "symbol": active.symbol,
                        "alpha_signal_date": active.origin_date.isoformat(),
                        "technical_trigger_date": trading_date.isoformat(),
                        "eligibility_age_sessions": active.age_sessions,
                        "window_sessions": window_sessions,
                        "final_signal": active.final_signal,
                        "recommendation_score": str(active.recommendation_score),
                        "origin_regime": active.origin_regime,
                    }
                )
                trigger_count += 1
                regime_counts[active.origin_regime] = (
                    regime_counts.get(active.origin_regime, 0) + 1
                )
                active = None
                continue

            if active is not None:
                remaining = active.remaining_sessions - 1
                if remaining <= 0:
                    expired_count += 1
                    active = None
                else:
                    active = ActiveEligibility(
                        security_id=active.security_id,
                        symbol=active.symbol,
                        origin_date=active.origin_date,
                        final_signal=active.final_signal,
                        recommendation_score=active.recommendation_score,
                        origin_regime=active.origin_regime,
                        remaining_sessions=remaining,
                        age_sessions=active.age_sessions + 1,
                    )
        if active is not None:
            boundary_count += 1

    result = result.sort_values(["trading_date", "security_id"], kind="stable")
    audit = EligibilityAudit(
        window_sessions=window_sessions,
        alpha_signal_count=int(result["alpha_signal_ok"].fillna(False).sum()),
        eligibility_issued_count=issued_count,
        eligibility_superseded_count=superseded_count,
        eligibility_expired_count=expired_count,
        boundary_untriggered_count=boundary_count,
        technical_trigger_count=trigger_count,
        trigger_origin_regime_counts=dict(sorted(regime_counts.items())),
    )
    return result, ledger, audit


def build_sweep_contract() -> tuple[tuple[int, RiskPolicy], ...]:
    """Return the exact pre-registered 5-by-2 sweep contract."""

    return tuple((window, policy) for window in WINDOWS for policy in RISK_POLICIES)


def run_sweep(
    *,
    database: Path,
    reference_challenger_output: Path,
    output: Path,
) -> dict[str, object]:
    """Run all governed eligibility-window and risk-policy cells."""

    reference = _load_reference(reference_challenger_output)
    data_start = date.fromisoformat(str(reference["data_start"]))
    data_end = date.fromisoformat(str(reference["data_end"]))
    expected_run_id = str(reference["retrospective_alpha_replay_run_id"])

    frame, replay_run_id, loaded_start, loaded_end = load_research_frame(database)
    if replay_run_id != expected_run_id:
        raise RuntimeError(
            "frozen replay run mismatch: "
            f"expected {expected_run_id}, observed {replay_run_id}"
        )
    if loaded_start > data_start or loaded_end < data_end:
        raise RuntimeError("certified research frame does not cover reference boundary")

    frame_dates = pd.to_datetime(frame["trading_date"]).dt.date
    frame = frame.loc[(frame_dates >= data_start) & (frame_dates <= data_end)].copy()
    base_config = replace(ChallengerConfig(), positive_regime="ATTRIBUTION_ONLY")
    featured = engineer_signals(frame, base_config)

    output.mkdir(parents=True, exist_ok=True)
    cells_root = output / "cells"
    cells_root.mkdir(parents=True, exist_ok=True)
    aggregate_rows: list[dict[str, object]] = []
    cell_payloads: list[dict[str, object]] = []
    same_session_reference: ChallengerResult | None = None

    window_cache: dict[
        int, tuple[pd.DataFrame, list[dict[str, object]], EligibilityAudit]
    ] = {}
    for window_sessions, policy in build_sweep_contract():
        if window_sessions not in window_cache:
            window_cache[window_sessions] = build_window_signals(
                featured,
                window_sessions=window_sessions,
            )
        windowed, ledger, eligibility_audit = window_cache[window_sessions]
        config = replace(
            base_config,
            full_risk_fraction=policy.full_risk_fraction,
            throttled_risk_fraction=policy.throttled_risk_fraction,
        )
        result = simulate_challenger(windowed, config)
        if window_sessions == 1 and policy.policy_id == "FLAT_1PCT":
            same_session_reference = result

        cell_id = f"DSI011E-W{window_sessions:02d}-{policy.policy_id}"
        cell_directory = cells_root / cell_id
        cell_directory.mkdir(parents=True, exist_ok=True)
        summary = result.summary()
        row = {
            "cell_id": cell_id,
            "window_sessions": window_sessions,
            "risk_policy": policy.policy_id,
            "full_risk_percent": str(policy.full_risk_fraction * Decimal("100")),
            "throttled_risk_percent": str(
                policy.throttled_risk_fraction * Decimal("100")
            ),
            **summary,
            "eligibility_issued_count": eligibility_audit.eligibility_issued_count,
            "eligibility_superseded_count": (
                eligibility_audit.eligibility_superseded_count
            ),
            "eligibility_expired_count": eligibility_audit.eligibility_expired_count,
            "boundary_untriggered_count": (
                eligibility_audit.boundary_untriggered_count
            ),
            "technical_trigger_count": eligibility_audit.technical_trigger_count,
            "trigger_origin_regime_counts": json.dumps(
                eligibility_audit.trigger_origin_regime_counts,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        aggregate_rows.append(row)
        cell_payload = {
            "cell_id": cell_id,
            "window_sessions": window_sessions,
            "risk_policy": policy.as_dict(),
            "config": config.as_dict(),
            "eligibility_audit": eligibility_audit.as_dict(),
            "summary": summary,
            "production_influence": False,
            "automatic_strategy_promotion": False,
        }
        cell_payloads.append(cell_payload)
        _write_json(cell_directory / "cell_result.json", cell_payload)
        _write_json(cell_directory / "eligibility_audit.json", eligibility_audit)
        _write_json(cell_directory / "trigger_ledger.json", ledger)
        _write_csv(cell_directory / "trigger_ledger.csv", ledger)
        trade_rows = [item.as_dict() for item in result.trades]
        equity_rows = [item.as_dict() for item in result.equity_curve]
        _write_json(cell_directory / "trades.json", trade_rows)
        _write_csv(cell_directory / "trades.csv", trade_rows)
        _write_json(cell_directory / "equity_curve.json", equity_rows)
        _write_csv(cell_directory / "equity_curve.csv", equity_rows)
        _write_json(
            cell_directory / "rejected_entries.json",
            [item.as_dict() for item in result.rejected_entries],
        )
        print(
            f"{cell_id}: signals={summary['signal_count']}; "
            f"entries={summary['entry_count']}; "
            f"CAGR={summary['gross_cagr_percent']}; "
            f"MDD={summary['maximum_drawdown_percent']}"
        )

    if same_session_reference is None:
        raise RuntimeError("same-session flat-risk reference cell was not executed")
    parity = _reference_parity(reference, same_session_reference.summary())
    if not bool(parity["passed"]):
        raise RuntimeError("same-session 1% parity failed: " + json.dumps(parity))

    ranked = sorted(
        aggregate_rows,
        key=lambda row: (
            -_optional_number(row.get("gross_cagr_percent")),
            -_optional_number(row.get("maximum_drawdown_percent")),
            int(row["window_sessions"]),
            str(row["risk_policy"]),
        ),
    )
    for rank, row in enumerate(ranked, start=1):
        row["descriptive_rank"] = rank

    payload: dict[str, object] = {
        "sweep_version": SWEEP_VERSION,
        "source_commit": _source_commit(),
        "retrospective_alpha_replay_run_id": replay_run_id,
        "data_start": data_start.isoformat(),
        "data_end": data_end.isoformat(),
        "strategy_population": (
            "Alpha BUY/STRONG BUY eligibility in all regimes; unchanged governed "
            "20-DMA reclaim technical trigger"
        ),
        "windows": list(WINDOWS),
        "risk_policies": [item.as_dict() for item in RISK_POLICIES],
        "cell_count": len(cell_payloads),
        "reference_parity": parity,
        "ranking_basis": "gross CAGR, then less-negative maximum drawdown",
        "cells": cell_payloads,
        "ranked_results": ranked,
        "results_are_gross_of_costs": True,
        "transaction_cost_model": "NONE",
        "slippage_model": "NONE",
        "production_influence": False,
        "automatic_strategy_promotion": False,
    }
    logical_hash = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()
    payload["artifact_logical_sha256"] = logical_hash

    _write_json(output / "eligibility_window_sweep.json", payload)
    _write_csv(output / "eligibility_window_sweep.csv", ranked)
    _write_markdown(output / "eligibility_window_sweep.md", payload)
    _write_json(
        output / "manifest.json",
        {
            "sweep_version": SWEEP_VERSION,
            "source_commit": payload["source_commit"],
            "retrospective_alpha_replay_run_id": replay_run_id,
            "artifact_logical_sha256": logical_hash,
            "cell_count": len(cell_payloads),
            "production_influence": False,
            "automatic_strategy_promotion": False,
        },
    )

    print("DSI-011E eligibility-window sweep complete")
    print(f"Cells: {len(cell_payloads)}")
    print(f"Reference parity: {parity['passed']}")
    print(f"Artifact logical SHA-256: {logical_hash}")
    print(f"Results: {output / 'eligibility_window_sweep.json'}")
    return payload


def _load_reference(path: Path) -> dict[str, object]:
    result_path = path / "challenger_result.json"
    if not result_path.is_file():
        raise FileNotFoundError(f"DSI-011C reference not found: {result_path}")
    return cast(
        dict[str, object],
        json.loads(result_path.read_text(encoding="utf-8")),
    )


def _reference_parity(
    reference: dict[str, object],
    observed: dict[str, object],
) -> dict[str, object]:
    reference_summary = cast(dict[str, object], reference["summary"])
    exact_keys = ("signal_count", "entry_count", "completed_trade_count")
    numeric_keys = (
        "gross_total_return_percent",
        "gross_cagr_percent",
        "maximum_drawdown_percent",
    )
    differences: dict[str, object] = {}
    passed = True
    for key in exact_keys:
        expected = int(cast(Any, reference_summary[key]))
        actual = int(cast(Any, observed[key]))
        match = expected == actual
        passed &= match
        differences[key] = {
            "expected": expected,
            "observed": actual,
            "match": match,
        }
    for key in numeric_keys:
        expected = _decimal(reference_summary[key])
        actual = _decimal(observed[key])
        delta = abs(actual - expected)
        match = delta <= _PARITY_TOLERANCE
        passed &= match
        differences[key] = {
            "expected": str(expected),
            "observed": str(actual),
            "absolute_delta": str(delta),
            "tolerance": str(_PARITY_TOLERANCE),
            "match": match,
        }
    return {"passed": passed, "differences": differences}


def _normalise_regime(value: object) -> str:
    if value is None or pd.isna(value):
        return "UNKNOWN"
    text = str(value).strip().upper()
    return text or "UNKNOWN"


def _decimal(value: object) -> Decimal:
    if value is None:
        return _ZERO
    return Decimal(str(value))


def _optional_number(value: object) -> float:
    if value is None:
        return float("-inf")
    if isinstance(value, (str, int, float, Decimal)):
        return float(value)
    raise TypeError(f"unsupported numeric value: {type(value).__name__}")


def _jsonable(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(_jsonable(payload), indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = [key for key in rows[0] if key != "exit_legs"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(row.get(key), sort_keys=True)
                    if isinstance(row.get(key), (dict, list, tuple))
                    else row.get(key)
                    for key in fieldnames
                }
            )


def _write_markdown(path: Path, payload: dict[str, object]) -> None:
    parity = cast(dict[str, object], payload["reference_parity"])
    rows = cast(list[dict[str, object]], payload["ranked_results"])
    lines = [
        "# DSI-011E Alpha Eligibility-Window Sweep",
        "",
        f"- Data range: {payload['data_start']} to {payload['data_end']}",
        f"- Cells: {payload['cell_count']}",
        f"- Same-session 1% parity: {parity['passed']}",
        f"- Production influence: {payload['production_influence']}",
        "",
        "| Rank | Window | Risk policy | CAGR % | MDD % | Trades | Exposure % |",
        "|---:|---:|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {rank} | {window} | {policy} | {cagr} | {mdd} | {trades} | "
            "{exposure} |".format(
                rank=row.get("descriptive_rank"),
                window=row.get("window_sessions"),
                policy=row.get("risk_policy"),
                cagr=row.get("gross_cagr_percent"),
                mdd=row.get("maximum_drawdown_percent"),
                trades=row.get("completed_trade_count"),
                exposure=row.get("average_exposure_percent"),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _source_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--reference-challenger-output", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    run_sweep(
        database=arguments.database,
        reference_challenger_output=arguments.reference_challenger_output,
        output=arguments.output,
    )


if __name__ == "__main__":
    main()
