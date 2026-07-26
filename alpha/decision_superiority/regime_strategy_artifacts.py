"""Deterministic artifacts and public verification for DSI-007."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from datetime import date
from enum import Enum
from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Final

from alpha.decision_superiority.regime_strategy_models import (
    DSI007_CONTRACT_VERSION,
    DSI007_RESEARCH_SCOPE,
    TournamentError,
    TournamentResult,
)
from alpha.decision_superiority.regime_strategy_tournament import governance_flags

DSI007_CERTIFICATE = "dsi007_strategy_tournament_certificate.json"
DSI007_REPORT = "dsi007_executive_report.md"
DSI007_ARTIFACTS: Final[dict[str, str]] = {
    "source_contract": "dsi007_source_contract_snapshot.csv",
    "market_data_coverage": "dsi007_market_data_coverage.csv",
    "universe": "dsi007_universe_and_survivorship_audit.csv",
    "corporate_actions": "dsi007_corporate_action_audit.csv",
    "benchmark": "dsi007_benchmark_contract.csv",
    "regime_daily": "dsi007_regime_daily_ledger.csv",
    "regime_transitions": "dsi007_regime_transitions.csv",
    "strategy_registry": "dsi007_strategy_registry.csv",
    "strategy_parameters": "dsi007_strategy_variant_parameters.csv",
    "signals": "dsi007_signal_ledger.csv",
    "trade_plans": "dsi007_trade_plan_ledger.csv",
    "logical_trades": "dsi007_logical_trade_ledger.csv",
    "portfolio_equity": "dsi007_portfolio_daily_equity.csv",
    "portfolio_positions": "dsi007_portfolio_positions.csv",
    "transaction_costs": "dsi007_transaction_cost_ledger.csv",
    "walk_forward_folds": "dsi007_walk_forward_folds.csv",
    "strategy_selections": "dsi007_strategy_selection_ledger.csv",
    "regime_strategy_mapping": "dsi007_regime_strategy_mapping.csv",
    "comparison_portfolios": "dsi007_comparison_portfolios.csv",
    "calendar_performance": "dsi007_calendar_year_performance.csv",
    "rolling_performance": "dsi007_rolling_performance.csv",
    "risk_metrics": "dsi007_cagr_and_risk_metrics.csv",
    "benchmark_relative": "dsi007_benchmark_relative_metrics.csv",
    "multiple_testing": "dsi007_multiple_testing_results.csv",
    "parameter_stability": "dsi007_parameter_stability.csv",
    "robustness": "dsi007_robustness_sensitivity.csv",
    "concentration": "dsi007_concentration_diagnostics.csv",
    "population_reconciliation": "dsi007_population_reconciliation.csv",
    "non_vacuity": "dsi007_non_vacuity_probe_ledger.csv",
}

_HEADERS: Final[dict[str, tuple[str, ...]]] = {
    "source_contract": (
        "source_role",
        "availability",
        "sha256",
        "byte_size",
        "portable_locator",
        "used_for_decisions",
    ),
    "market_data_coverage": (
        "price_arm",
        "source_start",
        "source_end",
        "actual_start",
        "actual_end",
        "source_sessions",
        "admitted_sessions",
        "source_rows",
        "admitted_rows",
        "source_securities",
        "admitted_securities",
        "missing_identity_rows",
        "ambiguous_identity_rows",
        "duplicate_rows",
        "impossible_ohlc",
        "nonpositive_price",
        "invalid_volume",
    ),
    "universe": (
        "population",
        "rows",
        "securities",
        "identity_state",
        "admitted",
        "reason",
    ),
    "corporate_actions": (
        "event_population",
        "event_count",
        "admitted_count",
        "conflicting_count",
        "treatment",
    ),
    "benchmark": (
        "benchmark_name",
        "status",
        "start_date",
        "end_date",
        "observed_sessions",
        "required_sessions",
        "coverage_percent",
        "is_total_return",
        "used_for_excess_performance",
        "reason",
        "sha256",
    ),
    "regime_daily": (
        "regime_state_id",
        "observed_on",
        "applies_on",
        "regime_state",
        "market_level",
        "market_return",
        "market_ma50",
        "market_ma200",
        "market_volatility20",
        "breadth",
        "security_count",
        "future_data_used",
    ),
    "regime_transitions": (
        "transition_id",
        "observed_on",
        "from_regime",
        "to_regime",
    ),
    "strategy_registry": (
        "strategy_variant_id",
        "strategy_family",
        "components",
        "parameter_count",
        "complexity_score",
        "source_definition",
        "expected_regimes",
        "valid_price_arms",
        "prerequisites",
        "valid",
    ),
    "strategy_parameters": (
        "strategy_variant_id",
        "parameter_name",
        "parameter_value",
    ),
    "signals": (
        "signal_id",
        "security_session_id",
        "identity_key",
        "symbol",
        "isin",
        "signal_date",
        "data_cutoff_date",
        "entry_eligibility_date",
        "strategy_variant_id",
        "strategy_family",
        "regime_state",
        "signal_strength",
        "entry_state",
        "price_arm",
        "source_data_hash",
        "same_close_execution",
    ),
    "trade_plans": (
        "trade_plan_id",
        "signal_id",
        "identity_key",
        "symbol",
        "strategy_variant_id",
        "signal_date",
        "entry_eligibility_date",
        "entry_rule",
        "raw_entry_price",
        "entry_price",
        "initial_stop",
        "target_1",
        "target_2",
        "target_3",
        "trailing_stop_rule",
        "maximum_holding_sessions",
        "risk_per_share",
        "reward_risk_target_1",
        "average_traded_value20",
        "entry_state",
        "same_close_execution",
    ),
    "logical_trades": (
        "logical_trade_id",
        "portfolio_name",
        "identity_key",
        "symbol",
        "strategy_variant_id",
        "walk_forward_fold_id",
        "regime_state",
        "signal_date",
        "entry_date",
        "exit_date",
        "entry_price",
        "exit_price",
        "quantity",
        "gross_pnl",
        "net_pnl",
        "net_return",
        "exit_reason",
        "holding_sessions",
        "costs",
    ),
    "portfolio_equity": (
        "portfolio_day_id",
        "portfolio_name",
        "observed_on",
        "cash",
        "open_position_value",
        "gross_exposure",
        "net_exposure",
        "realised_pnl",
        "unrealised_pnl",
        "cumulative_costs",
        "portfolio_value",
        "daily_return",
        "drawdown",
        "open_positions",
    ),
    "portfolio_positions": (
        "portfolio_day_id",
        "portfolio_name",
        "observed_on",
        "logical_trade_id",
        "identity_key",
        "symbol",
        "quantity",
        "close",
        "market_value",
        "active_stop",
    ),
    "transaction_costs": (
        "cost_event_id",
        "logical_trade_id",
        "portfolio_name",
        "observed_on",
        "cost_type",
        "amount",
    ),
    "walk_forward_folds": (
        "walk_forward_fold_id",
        "train_start",
        "train_end",
        "validation_start",
        "validation_end",
        "test_start",
        "test_end",
        "periods_overlap",
        "outer_test_used_for_selection",
    ),
    "strategy_selections": (
        "selection_id",
        "walk_forward_fold_id",
        "selection_scope",
        "strategy_variant_id",
        "train_trade_count",
        "validation_trade_count",
        "validation_mean_return",
        "validation_volatility",
        "complexity_score",
        "eligible",
        "objective_score",
        "selected",
        "selected_strategy_variant_id",
        "selection_data_end",
        "test_start",
        "test_end",
        "outer_test_used_for_selection",
    ),
    "regime_strategy_mapping": (
        "walk_forward_fold_id",
        "regime_state",
        "selected_strategy_variant_id",
        "fallback_state",
        "selection_data_end",
        "test_start",
        "test_end",
        "holdout_used",
        "ensemble_strategy_variant_ids",
    ),
    "comparison_portfolios": (
        "portfolio_name",
        "availability",
        "starting_capital",
        "ending_capital",
        "net_cagr",
        "maximum_drawdown",
        "sharpe",
        "sortino",
        "trade_count",
        "total_costs",
    ),
    "calendar_performance": (
        "portfolio_name",
        "calendar_year",
        "start_value",
        "end_value",
        "return",
    ),
    "rolling_performance": (
        "portfolio_name",
        "observed_on",
        "metric",
        "value",
    ),
    "risk_metrics": (
        "portfolio_name",
        "start_date",
        "end_date",
        "years",
        "starting_capital",
        "ending_capital",
        "gross_cagr",
        "net_cagr",
        "cumulative_return",
        "annualised_volatility",
        "maximum_drawdown",
        "drawdown_duration_sessions",
        "sharpe",
        "sortino",
        "calmar",
        "turnover",
        "total_costs",
        "trade_count",
        "win_rate",
        "expectancy",
        "average_exposure",
        "time_in_market",
    ),
    "benchmark_relative": (
        "portfolio_name",
        "benchmark_name",
        "benchmark_available",
        "portfolio_cagr",
        "benchmark_cagr",
        "excess_cagr",
        "information_ratio",
        "tracking_error",
        "beta",
        "alpha",
        "upside_capture",
        "downside_capture",
        "reason",
    ),
    "multiple_testing": (
        "strategy_variant_id",
        "sample_count",
        "independent_time_blocks",
        "raw_p_value",
        "bh_adjusted_p_value",
        "holm_adjusted_p_value",
        "test_state",
    ),
    "parameter_stability": (
        "strategy_family",
        "variant_count",
        "variant_mean_returns",
        "directionally_stable",
        "state",
    ),
    "robustness": (
        "scenario",
        "parameter",
        "result_cagr",
        "result_maximum_drawdown",
        "result_trade_count",
        "state",
    ),
    "concentration": (
        "dimension",
        "member",
        "trade_count",
        "net_pnl",
        "share_of_positive_pnl",
    ),
    "population_reconciliation": (
        "unit",
        "source_count",
        "admitted_count",
        "excluded_count",
        "reconciles",
    ),
    "non_vacuity": (
        "probe_id",
        "probe_name",
        "accepted",
        "explanation",
        "empirical_population",
    ),
}


def export_regime_strategy_tournament(
    result: TournamentResult,
    output: Path,
) -> tuple[Path, ...]:
    """Write and hash-bind the complete deterministic DSI-007 package."""

    output.mkdir(parents=True, exist_ok=True)
    support: list[Path] = []
    for key, filename in DSI007_ARTIFACTS.items():
        support.append(
            _write_csv(
                output / filename,
                result.rows[key],
                headers=_HEADERS[key],
            )
        )
    report = _write_text(output / DSI007_REPORT, _executive_report(result))
    support.append(report)
    manifest = {path.name: _sha256(path) for path in support}
    payload: dict[str, Any] = {
        "contract_version": DSI007_CONTRACT_VERSION,
        "research_scope": DSI007_RESEARCH_SCOPE,
        "source_commit": result.source_commit,
        "source_chain_hashes": {
            str(row["source_role"]): str(row["sha256"])
            for row in result.rows["source_contract"]
        },
        "historical_coverage": _subset(
            result.summaries,
            "actual_start",
            "actual_end",
            "admitted_sessions",
            "admitted_securities",
            "admitted_rows",
        ),
        "benchmark_summary": _subset(
            result.summaries,
            "benchmark_status",
            "benchmark_metrics",
        ),
        "regime_summary": _subset(
            result.summaries,
            "regime_counts",
            "regime_transition_count",
            "unknown_regime_rate",
        ),
        "strategy_summary": _subset(
            result.summaries,
            "strategy_family_count",
            "generated_variant_count",
            "valid_variant_count",
            "rejected_variant_count",
            "signal_count",
            "trade_plan_count",
        ),
        "walk_forward_summary": _subset(
            result.summaries,
            "walk_forward_fold_count",
            "fixed_strategy_selections",
            "no_trade_selection_count",
        ),
        "portfolio_research_policy": dict(result.rows["policy"][0]),
        "portfolio_summary": result.summaries["regime_aware_metrics"],
        "overfitting_state": result.summaries["overfitting_state"],
        "readiness_by_slice": dict(result.readiness),
        "readiness_decision": result.readiness["J"],
        "blockers": list(result.blockers),
        "implementation_defect_count": result.summaries["implementation_defect_count"],
        "lookahead_leakage_count": result.summaries["lookahead_leakage_count"],
        "population_reconciliation_defect_count": result.summaries[
            "population_reconciliation_defect_count"
        ],
        "automatic_promotion_count": result.summaries["automatic_promotion_count"],
        "executive_report_sha256": _sha256(report),
        "support_artifact_manifest": dict(sorted(manifest.items())),
        "governance_flags": dict(result.governance),
    }
    payload["report_sha256"] = _canonical_payload_sha256(payload)
    certificate = _write_json(output / DSI007_CERTIFICATE, payload)
    return (certificate, *sorted(support, key=lambda path: path.name))


def validate_regime_strategy_tournament_certificate(
    certificate: Path,
    *,
    require_ready: bool = False,
    database: Path | None = None,
) -> dict[str, Any]:
    """Validate certificate, support artifacts, governance, and optional source."""

    payload = _read_json(certificate)
    if payload.get("contract_version") != DSI007_CONTRACT_VERSION:
        raise TournamentError("UNSUPPORTED_DSI007_CONTRACT")
    if payload.get("research_scope") != DSI007_RESEARCH_SCOPE:
        raise TournamentError("DSI007_RESEARCH_SCOPE_MISMATCH")
    if payload.get("governance_flags") != governance_flags():
        raise TournamentError("DSI007_GOVERNANCE_FLAGS_INVALID")
    if payload.get("report_sha256") != _canonical_payload_sha256(payload):
        raise TournamentError("DSI007_CERTIFICATE_PAYLOAD_TAMPERED")
    manifest = payload.get("support_artifact_manifest")
    expected = frozenset((*DSI007_ARTIFACTS.values(), DSI007_REPORT))
    if not isinstance(manifest, dict) or frozenset(manifest) != expected:
        raise TournamentError("DSI007_SUPPORT_MANIFEST_INVALID")
    root = certificate.resolve().parent
    for name, digest in sorted(manifest.items()):
        path = (root / str(name)).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise TournamentError("DSI007_SUPPORT_PATH_UNSAFE")
        if _sha256(path) != str(digest):
            raise TournamentError(f"DSI007_ARTIFACT_TAMPERED:{name}")
        if b"/Users/" in path.read_bytes():
            raise TournamentError(f"DSI007_MACHINE_LOCAL_PATH_LEAK:{name}")
    if payload.get("executive_report_sha256") != _sha256(root / DSI007_REPORT):
        raise TournamentError("DSI007_EXECUTIVE_REPORT_HASH_MISMATCH")
    if database is not None:
        if not database.is_file():
            raise TournamentError("DSI007_SOURCE_DATABASE_UNAVAILABLE")
        expected_hash = payload.get("source_chain_hashes", {}).get(
            "HISTORICAL_TRUTH_DATABASE"
        )
        if expected_hash != _sha256(database):
            raise TournamentError("DSI007_SOURCE_DATABASE_DRIFT")
    readiness = str(payload.get("readiness_decision") or "")
    if require_ready and not readiness.startswith("READY_"):
        raise TournamentError(f"DSI007_NOT_READY:{readiness}")
    return payload


def _executive_report(result: TournamentResult) -> str:
    summary = result.summaries
    portfolio = summary["regime_aware_metrics"]
    benchmark = summary["benchmark_metrics"]
    conclusion = _conclusion(result)
    regime_lines = [
        f"- {name}: {count} sessions"
        for name, count in summary["regime_counts"].items()
    ]
    selections = summary["fixed_strategy_selections"]
    return "\n".join(
        (
            "# DSI-007 Governed Regime-Aware Strategy Tournament",
            "",
            "## Certification",
            "",
            f"- Final readiness: `{result.readiness['J']}`",
            f"- Research conclusion: **{conclusion}**",
            "- Production influence: `false`",
            "- Automatic strategy promotion: `false`",
            "",
            "## Historical Data",
            "",
            f"- Actual period: {summary['actual_start']} to {summary['actual_end']}",
            f"- Sessions: {summary['admitted_sessions']}",
            f"- Securities: {summary['admitted_securities']}",
            f"- Security-session rows: {summary['admitted_rows']}",
            (
                "- Admission: observed activity, uniquely resolved effective-dated "
                "ISIN identity, and certified backward-adjusted price basis."
            ),
            "",
            "## Benchmark",
            "",
            f"- Status: `{summary['benchmark_status']}`",
            (f"- Benchmark CAGR: {_display(benchmark.get('net_cagr'), percent=True)}"),
            (
                "- Excess CAGR remains UNKNOWN unless a complete governed "
                "total-return index is supplied."
            ),
            "",
            "## Regimes",
            "",
            *regime_lines,
            f"- Transitions: {summary['regime_transition_count']}",
            f"- UNKNOWN rate: {_display(summary['unknown_regime_rate'], percent=True)}",
            "",
            "## Strategy Tournament",
            "",
            f"- Families: {summary['strategy_family_count']}",
            f"- Valid variants: {summary['valid_variant_count']}",
            f"- Signals: {summary['signal_count']}",
            f"- Frozen trade plans: {summary['trade_plan_count']}",
            f"- Walk-forward folds: {summary['walk_forward_fold_count']}",
            (
                "- Fixed fold selections: "
                f"{', '.join(selections) if selections else 'NO_TRADE'}"
            ),
            "",
            "## Out-of-Sample Portfolio",
            "",
            f"- Starting capital: {_display(portfolio.get('starting_capital'))}",
            f"- Ending capital: {_display(portfolio.get('ending_capital'))}",
            f"- Gross CAGR: {_display(portfolio.get('gross_cagr'), percent=True)}",
            f"- Net CAGR: {_display(portfolio.get('net_cagr'), percent=True)}",
            (
                "- Maximum drawdown: "
                f"{_display(portfolio.get('maximum_drawdown'), percent=True)}"
            ),
            f"- Sharpe: {_display(portfolio.get('sharpe'))}",
            f"- Sortino: {_display(portfolio.get('sortino'))}",
            f"- Calmar: {_display(portfolio.get('calmar'))}",
            f"- Trades: {portfolio.get('trade_count', 0)}",
            f"- Win rate: {_display(portfolio.get('win_rate'), percent=True)}",
            f"- Expectancy: {_display(portfolio.get('expectancy'), percent=True)}",
            f"- Costs: {_display(portfolio.get('total_costs'))}",
            f"- Turnover: {_display(portfolio.get('turnover'), percent=True)}",
            "",
            "## Overfitting Audit",
            "",
            f"- Classification: `{summary['overfitting_state']}`",
            (
                "- Parameter variants are treated as related hypotheses, "
                "not independent evidence."
            ),
            "- Holdout results never select the strategy used in that holdout.",
            "",
            "## Readiness A-J",
            "",
            *(
                f"- DSI-007{slice_id}: `{state}`"
                for slice_id, state in result.readiness.items()
            ),
            "",
            "## Governance",
            "",
            "- This package evaluates fresh historical strategy rules.",
            "- It does not claim these were Alpha's historical recommendations.",
            (
                "- It does not change thresholds, gates, scoring, allocation, "
                "or execution."
            ),
            "- No strategy is automatically promoted.",
            "- `PRODUCTION_INFLUENCE=false`",
            "",
        )
    )


def _conclusion(result: TournamentResult) -> str:
    summary = result.summaries
    if summary["benchmark_status"] != "AVAILABLE_TOTAL_RETURN":
        return "history or benchmark insufficient"
    if summary["overfitting_state"] == "NO_GENERALISABLE_STRATEGY_FOUND":
        return "no generalisable strategy found"
    portfolio = summary["regime_aware_metrics"]
    if not portfolio.get("trade_count"):
        return "no qualifying strategy found"
    comparisons = {
        row["portfolio_name"]: row for row in result.rows["comparison_portfolios"]
    }
    regime = comparisons.get("REGIME_AWARE_SELECTED", {}).get("net_cagr")
    fixed = comparisons.get("BEST_FIXED_STRATEGY", {}).get("net_cagr")
    if regime is not None and fixed is not None and float(regime) <= float(fixed):
        return "fixed strategy performs as well or better"
    return "regime-aware selection adds robust out-of-sample value"


def _display(value: Any, *, percent: bool = False) -> str:
    if value is None or value == "":
        return "UNKNOWN"
    parsed = float(value)
    if percent:
        return f"{parsed * 100:.2f}%"
    return f"{parsed:.4f}"


def _subset(mapping: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    return {key: mapping[key] for key in keys}


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    *,
    headers: Sequence[str],
) -> Path:
    stream = StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=tuple(headers),
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_value(row.get(key)) for key in headers})
    return _write_text(path, stream.getvalue())


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"))
    return value


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, Path)):
        return str(value)
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    return _write_text(
        path,
        json.dumps(_json_value(payload), indent=2, sort_keys=True) + "\n",
    )


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TournamentError("DSI007_CERTIFICATE_UNREADABLE") from exc
    if not isinstance(payload, dict):
        raise TournamentError("DSI007_CERTIFICATE_NOT_OBJECT")
    return payload


def _canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    body = dict(payload)
    body.pop("report_sha256", None)
    encoded = json.dumps(
        _json_value(body),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


__all__ = [
    "DSI007_ARTIFACTS",
    "DSI007_CERTIFICATE",
    "DSI007_REPORT",
    "export_regime_strategy_tournament",
    "validate_regime_strategy_tournament_certificate",
]
