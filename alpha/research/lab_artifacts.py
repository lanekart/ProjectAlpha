"""Deterministic artifacts for completed or blocked research experiments."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from alpha.backtest.research_runner import ResearchBacktestResult
from alpha.research.lab_data_contract import ResearchDataContract
from alpha.research.lab_models import ResearchExperimentSpec

_DISCLOSURE = (
    "Results exclude brokerage, securities transaction tax, exchange charges, "
    "GST, stamp duty, bid-ask spread, slippage and market impact."
)


class ResearchArtifactExporter:
    def export_blocked(
        self,
        *,
        output: Path,
        spec: ResearchExperimentSpec,
        contract: ResearchDataContract,
    ) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        _write_json(output / "data_contract.json", contract.as_dict())
        _write_json(output / "spec.json", spec.as_dict())
        summary = {
            "experiment_id": spec.experiment_id,
            "status": "BLOCKED_BY_DATA_CONTRACT",
            "blockers": list(contract.blockers),
            "disclosure": _DISCLOSURE,
            "production_influence": False,
        }
        _write_json(output / "summary.json", summary)
        (output / "summary.md").write_text(_summary_markdown(summary))
        certificate = _certificate(output, spec, contract, ready=False)
        _write_json(output / "certificate.json", certificate)
        return tuple(sorted(output.iterdir()))

    def export_completed(
        self,
        *,
        output: Path,
        spec: ResearchExperimentSpec,
        contract: ResearchDataContract,
        result: ResearchBacktestResult,
    ) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        _write_json(output / "spec.json", spec.as_dict())
        _write_json(output / "data_contract.json", contract.as_dict())
        summary = {
            "experiment_id": spec.experiment_id,
            "status": "COMPLETED",
            **result.summary(),
            "data_start": spec.data_start.isoformat(),
            "data_end": spec.data_end.isoformat(),
            "disclosure": _DISCLOSURE,
            "production_influence": False,
        }
        _write_json(output / "summary.json", summary)
        (output / "summary.md").write_text(_summary_markdown(summary))
        trade_rows = [_jsonable(asdict(item)) for item in result.trades]
        _write_json(output / "trades.json", trade_rows)
        _write_csv(output / "trades.csv", trade_rows)
        curve_rows = [_jsonable(asdict(item)) for item in result.equity_curve]
        _write_csv(output / "equity_curve.csv", curve_rows)
        _write_csv(
            output / "drawdown.csv",
            [
                {
                    "trading_date": row["trading_date"],
                    "drawdown_percent": row["drawdown_percent"],
                }
                for row in curve_rows
            ],
        )
        rejected = [_jsonable(asdict(item)) for item in result.rejected_entries]
        _write_csv(output / "rejected_entries.csv", rejected)
        ambiguous = [row for row in trade_rows if bool(row.get("ambiguous_session"))]
        _write_csv(output / "ambiguous_sessions.csv", ambiguous)
        _write_period_returns(output / "annual_returns.csv", curve_rows, 4)
        _write_period_returns(output / "monthly_returns.csv", curve_rows, 7)
        for filename in (
            "regime_breakdown.csv",
            "sector_breakdown.csv",
            "signal_breakdown.csv",
            "indicator_breakdown.csv",
            "candle_pattern_breakdown.csv",
            "stop_breakdown.csv",
            "target_breakdown.csv",
        ):
            _write_csv(
                output / filename,
                [{"status": "NOT_AVAILABLE_IN_CERTIFIED_SOURCE"}],
            )
        manifest = {
            "experiment_id": spec.experiment_id,
            "specification_sha256": spec.specification_sha256,
            "data_contract_sha256": contract.contract_sha256,
            "engine_version": "alpha.backtest.research_runner-v1",
            "registry_version": "DSI-011-registry-v1.0.0",
            "transaction_cost_model": "NONE",
            "slippage_model": "NONE",
            "results_are_gross_of_costs": True,
            "production_influence": False,
        }
        _write_json(output / "run_manifest.json", manifest)
        (output / "report.html").write_text(
            _html_report(summary, curve_rows), encoding="utf-8"
        )
        _write_json(
            output / "certificate.json",
            _certificate(output, spec, contract, ready=True),
        )
        return tuple(sorted(output.iterdir()))


def _certificate(
    output: Path,
    spec: ResearchExperimentSpec,
    contract: ResearchDataContract,
    *,
    ready: bool,
) -> dict[str, Any]:
    hashes = {
        path.name: _sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file() and path.name != "certificate.json"
    }
    return {
        "experiment_id": spec.experiment_id,
        "specification_sha256": spec.specification_sha256,
        "data_contract_sha256": contract.contract_sha256,
        "artifact_hashes": hashes,
        "ready": ready,
        "automatic_strategy_promotion": False,
        "production_influence": False,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(
            _jsonable(payload),
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row}) or ["status"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _cell(row.get(field)) for field in fields})


def _write_period_returns(
    path: Path,
    rows: list[dict[str, Any]],
    length: int,
) -> None:
    grouped: dict[str, tuple[str, str]] = {}
    for row in rows:
        period = str(row["trading_date"])[:length]
        equity = str(row["equity"])
        if period not in grouped:
            grouped[period] = (equity, equity)
        else:
            grouped[period] = (grouped[period][0], equity)
    output = []
    for period, (first, last) in sorted(grouped.items()):
        opening = float(first)
        closing = float(last)
        output.append(
            {
                "period": period,
                "opening_equity": first,
                "closing_equity": last,
                "return_percent": (
                    "0" if opening == 0 else f"{(closing / opening - 1) * 100:.6f}"
                ),
            }
        )
    _write_csv(path, output)


def _summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        f"# Research Experiment {summary['experiment_id']}",
        "",
        f"Status: {summary['status']}",
        "",
    ]
    lines.extend(
        f"- {key.replace('_', ' ').title()}: {value}"
        for key, value in sorted(summary.items())
        if key not in {"experiment_id", "status", "disclosure"}
    )
    lines.extend(("", _DISCLOSURE, ""))
    return "\n".join(lines)


def _html_report(
    summary: dict[str, Any],
    curve: list[dict[str, Any]],
) -> str:
    initial_capital = max(1, float(summary["initial_capital"]))
    points = " ".join(
        f"{index},{_chart_y(float(row['equity']), initial_capital):.2f}"
        for index, row in enumerate(curve)
    )
    metrics = "".join(
        f"<tr><th>{key.replace('_', ' ').title()}</th><td>{value}</td></tr>"
        for key, value in sorted(summary.items())
        if key not in {"disclosure"}
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Alpha Research Lab</title><style>"
        "body{font:14px system-ui;margin:32px;color:#172026}"
        "table{border-collapse:collapse}th,td{padding:6px 12px;"
        "border-bottom:1px solid #ccd5da;text-align:left}"
        "svg{width:100%;height:220px;border:1px solid #ccd5da}"
        "</style></head><body><h1>Alpha Research Lab</h1>"
        f"<p>{_DISCLOSURE}</p><table>{metrics}</table>"
        "<h2>Equity Curve</h2><svg viewBox='0 0 100 100' "
        "preserveAspectRatio='none'><polyline fill='none' stroke='#137c5b' "
        f"stroke-width='1' points='{points}'/></svg></body></html>\n"
    )


def _cell(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return "" if value is None else str(value)


def _chart_y(equity: float, initial_capital: float) -> float:
    return 100 - min(95, max(0, equity / initial_capital * 50))


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value) if value.__class__.__name__ == "Decimal" else value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = ["ResearchArtifactExporter"]
