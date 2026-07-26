"""Deterministic artifacts and public verification for DSI-009."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from enum import Enum
from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Final

from alpha.decision_superiority.entry_stop_improvement import governance_flags
from alpha.decision_superiority.entry_stop_improvement_models import (
    DSI009_CONTRACT_VERSION,
    DSI009_RESEARCH_SCOPE,
    EntryStopImprovementError,
    EntryStopImprovementResult,
)

DSI009_CERTIFICATE = "dsi009_entry_stop_certificate.json"
DSI009_REPORT = "dsi009_executive_report.md"
DSI009_ARTIFACTS: Final[dict[str, str]] = {
    "source_contract": "dsi009_source_contract_snapshot.csv",
    "incumbent_trade_path": "dsi009_incumbent_trade_path.csv",
    "signal_path": "dsi009_signal_path_ledger.csv",
    "trade_excursions": "dsi009_trade_excursion_metrics.csv",
    "entry_stop_attribution": "dsi009_entry_stop_attribution.csv",
    "entry_registry": "dsi009_entry_challenger_registry.csv",
    "entry_fills": "dsi009_entry_fill_ledger.csv",
    "entry_folds": "dsi009_entry_champion_challenger_folds.csv",
    "entry_results": "dsi009_entry_challenger_results.csv",
    "stop_value": "dsi009_stop_value_counterfactuals.csv",
    "stop_registry": "dsi009_stop_challenger_registry.csv",
    "stop_folds": "dsi009_stop_champion_challenger_folds.csv",
    "stop_results": "dsi009_stop_challenger_results.csv",
    "sequential_portfolio": "dsi009_sequential_champion_portfolio.csv",
    "daily_equity": "dsi009_daily_equity_curves.csv",
    "benchmark_relative": "dsi009_benchmark_relative_performance.csv",
    "tier_definitions": "dsi009_signal_tier_definitions.csv",
    "tier_outcomes": "dsi009_signal_tier_outcomes.csv",
    "accuracy_wealth_tradeoff": "dsi009_accuracy_wealth_tradeoff.csv",
    "multiple_testing": "dsi009_multiple_testing_results.csv",
    "robustness": "dsi009_robustness_sensitivity.csv",
    "concentration": "dsi009_concentration_diagnostics.csv",
    "population_reconciliation": "dsi009_population_reconciliation.csv",
    "non_vacuity": "dsi009_non_vacuity_probe_ledger.csv",
}


def export_entry_stop_improvement(
    result: EntryStopImprovementResult,
    output: Path,
) -> tuple[Path, ...]:
    """Write and hash-bind the complete deterministic DSI-009 package."""

    output.mkdir(parents=True, exist_ok=True)
    support: list[Path] = []
    for key, filename in DSI009_ARTIFACTS.items():
        try:
            support.append(_write_csv(output / filename, result.rows[key]))
        except EntryStopImprovementError as exc:
            raise EntryStopImprovementError(f"{exc}:{key}") from exc
    report = _write_text(output / DSI009_REPORT, _executive_report(result))
    support.append(report)
    manifest = {
        path.name: _sha256(path) for path in sorted(support, key=lambda item: item.name)
    }
    source_hashes = {
        str(row["source_role"]): str(row["sha256"])
        for row in result.rows["source_contract"]
    }
    payload: dict[str, Any] = {
        "contract_version": DSI009_CONTRACT_VERSION,
        "research_scope": DSI009_RESEARCH_SCOPE,
        "source_commit": result.source_commit,
        "source_chain_hashes": source_hashes,
        "incumbent_summary": result.summaries["incumbent"],
        "incumbent_replay_summary": result.summaries["incumbent_replay"],
        "benchmark_summary": result.summaries["benchmark"],
        "trade_path_summary": {
            "trade_count": len(result.rows["incumbent_trade_path"]),
            "signal_count": len(result.rows["signal_path"]),
        },
        "entry_stop_attribution": result.summaries["loss_attribution"],
        "entry_challenger_summary": {
            "tested": result.summaries["entry_challengers_tested"],
            "accepted": result.summaries["entry_champion"],
        },
        "stop_value_summary": result.summaries["stop_value"],
        "stop_challenger_summary": {
            "tested": result.summaries["stop_challengers_tested"],
            "accepted": result.summaries["stop_champion"],
        },
        "sequential_champion": result.summaries["sequential_champion"],
        "improved_portfolio": result.summaries["improved_portfolio"],
        "benchmark_gap_closed": result.summaries["benchmark_gap_closed"],
        "best_descriptive_result": result.summaries["best_descriptive_result"],
        "descriptive_benchmark_gap_closed": result.summaries[
            "descriptive_benchmark_gap_closed"
        ],
        "descriptive_remaining_benchmark_gap": result.summaries[
            "descriptive_remaining_benchmark_gap"
        ],
        "signal_tiers": result.summaries["tiers"],
        "multiple_testing_survived": result.summaries["multiple_testing_survived"],
        "robustness_grade": result.summaries["robustness_grade"],
        "forward_paper_eligible": result.summaries["forward_paper_eligible"],
        "fresh_holdout_available": result.summaries["fresh_holdout_available"],
        "readiness_by_slice": dict(result.readiness),
        "readiness_decision": result.readiness["I"],
        "blockers": list(result.blockers),
        "automatic_promotion_count": 0,
        "executive_report_sha256": _sha256(report),
        "support_artifact_manifest": dict(sorted(manifest.items())),
        "governance_flags": dict(result.governance),
    }
    payload["report_sha256"] = _canonical_payload_sha256(payload)
    certificate = _write_json(output / DSI009_CERTIFICATE, payload)
    return (certificate, *sorted(support, key=lambda path: path.name))


def validate_entry_stop_improvement_certificate(
    certificate: Path,
    *,
    require_ready: bool = False,
) -> dict[str, Any]:
    """Validate the DSI-009 certificate and every support artifact."""

    payload = _read_json(certificate)
    if payload.get("contract_version") != DSI009_CONTRACT_VERSION:
        raise EntryStopImprovementError("UNSUPPORTED_DSI009_CONTRACT")
    if payload.get("research_scope") != DSI009_RESEARCH_SCOPE:
        raise EntryStopImprovementError("DSI009_RESEARCH_SCOPE_MISMATCH")
    if payload.get("governance_flags") != governance_flags():
        raise EntryStopImprovementError("DSI009_GOVERNANCE_FLAGS_INVALID")
    if payload.get("report_sha256") != _canonical_payload_sha256(payload):
        raise EntryStopImprovementError("DSI009_CERTIFICATE_PAYLOAD_TAMPERED")
    manifest = payload.get("support_artifact_manifest")
    expected = frozenset((*DSI009_ARTIFACTS.values(), DSI009_REPORT))
    if not isinstance(manifest, dict) or frozenset(manifest) != expected:
        raise EntryStopImprovementError("DSI009_SUPPORT_MANIFEST_INVALID")
    root = certificate.resolve().parent
    for name, digest in sorted(manifest.items()):
        path = (root / str(name)).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise EntryStopImprovementError("DSI009_SUPPORT_PATH_UNSAFE")
        if _sha256(path) != str(digest):
            raise EntryStopImprovementError(f"DSI009_ARTIFACT_TAMPERED:{name}")
        if b"/Users/" in path.read_bytes():
            raise EntryStopImprovementError(f"DSI009_MACHINE_LOCAL_PATH_LEAK:{name}")
    if payload.get("executive_report_sha256") != _sha256(root / DSI009_REPORT):
        raise EntryStopImprovementError("DSI009_EXECUTIVE_REPORT_HASH_MISMATCH")
    if payload.get("automatic_promotion_count") != 0:
        raise EntryStopImprovementError("DSI009_AUTOMATIC_PROMOTION")
    if payload.get("forward_paper_eligible") and not payload.get(
        "multiple_testing_survived"
    ):
        raise EntryStopImprovementError("DSI009_UNSUPPORTED_FORWARD_ELIGIBILITY")
    readiness = str(payload.get("readiness_decision") or "")
    if require_ready and not readiness.startswith("READY_"):
        raise EntryStopImprovementError(f"DSI009_NOT_READY:{readiness}")
    return payload


def _executive_report(result: EntryStopImprovementResult) -> str:
    summary = result.summaries
    incumbent = summary["incumbent"]
    incumbent_replay = summary["incumbent_replay"]
    benchmark = summary["benchmark"]
    tiers = summary["tiers"]
    lines = [
        "# DSI-009 Governed Entry Timing and Stop-Loss Improvement",
        "",
        "## Certification",
        "",
        f"- Final readiness: `{result.readiness['I']}`",
        f"- Robustness grade: `{summary['robustness_grade']}`",
        (
            "- Forward paper eligibility: "
            f"`{str(summary['forward_paper_eligible']).lower()}`"
        ),
        "- Production influence: `false`",
        "- Automatic mechanism promotion: `false`",
        "",
        "## Frozen DSI-008 Incumbent",
        "",
        f"- Starting capital: {_currency(incumbent['starting_capital'])}",
        f"- Ending capital: {_currency(incumbent['ending_capital'])}",
        f"- Net CAGR: {_percent(incumbent['net_cagr'])}",
        f"- Nifty 500 TRI CAGR: {_percent(benchmark['cagr'])}",
        f"- Excess CAGR: {_percent(incumbent['excess_cagr'])}",
        f"- Maximum drawdown: {_percent(incumbent['maximum_drawdown'])}",
        f"- Sharpe: {_number(incumbent['sharpe'])}",
        f"- Sortino: {_number(incumbent['sortino'])}",
        f"- Calmar: {_number(incumbent['calmar'])}",
        f"- Completed trades: {incumbent['trade_count']}",
        f"- Win rate: {_percent(incumbent_replay['win_rate'])}",
        f"- Expectancy: {_percent(incumbent_replay['expectancy'])}",
        f"- Costs: {_currency(incumbent['costs'])}",
        f"- Turnover: {_percent(incumbent['turnover'])}",
        "",
        "## Entry and Stop Attribution",
        "",
        f"- Early-entry diagnostics: {summary['early_entry_count']}",
        f"- Extended-entry diagnostics: {summary['extended_entry_count']}",
    ]
    lines.extend(
        f"- {name}: {count}"
        for name, count in sorted(summary["loss_attribution"].items())
    )
    lines.extend(["", "### Stop value", ""])
    lines.extend(
        f"- {name}: {count}" for name, count in sorted(summary["stop_value"].items())
    )
    lines.extend(
        [
            "",
            "## Champion-Challenger Result",
            "",
            (f"- Entry challengers tested: {summary['entry_challengers_tested']}"),
            f"- Entry champion: {summary['entry_champion'] or 'NONE'}",
            (f"- Stop challengers tested: {summary['stop_challengers_tested']}"),
            f"- Stop champion: {summary['stop_champion'] or 'NONE'}",
            (f"- Sequential champion: {summary['sequential_champion'] or 'NONE'}"),
            (
                "- Multiple-testing controls survived: "
                f"{str(summary['multiple_testing_survived']).lower()}"
            ),
            (
                "- Best descriptive result: "
                f"{_descriptive_result(summary['best_descriptive_result'])}"
            ),
            (
                "- Descriptive incumbent gap closed: "
                f"{_percent(summary['descriptive_benchmark_gap_closed'])}"
            ),
            (
                "- Remaining descriptive benchmark gap: "
                f"{_percent(summary['descriptive_remaining_benchmark_gap'])}"
            ),
            "",
            "## Signal Tiers",
            "",
        ]
    )
    for tier_name in (
        "ALPHA_STANDARD",
        "ALPHA_HIGH_CONVICTION",
        "ALPHA_ELITE",
    ):
        tier = tiers[tier_name]
        lines.extend(
            [
                f"### {tier_name}",
                "",
                f"- Completed sample: {tier['completed_trades']}",
                f"- Observed accuracy: {_percent(tier['observed_accuracy'])}",
                (
                    "- Wilson interval: "
                    f"{_percent(tier['wilson_lower'])} to "
                    f"{_percent(tier['wilson_upper'])}"
                ),
                f"- Expectancy: {_percent(tier['expectancy'])}",
                f"- Status: `{tier['target_status']}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Slice Readiness",
            "",
            *[
                f"- DSI-009{slice_id}: `{readiness}`"
                for slice_id, readiness in result.readiness.items()
            ],
            "",
            "## Research Conclusion",
            "",
            str(summary["interpretation"]),
            "",
            "No entry rule, stop rule, or confidence tier was activated. "
            "This package is offline research evidence only.",
        ]
    )
    if result.blockers:
        lines.extend(
            ["", "## Remaining Limitations", ""]
            + [f"- {blocker}" for blocker in result.blockers]
        )
    return "\n".join(lines) + "\n"


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    materialized = [dict(row) for row in rows]
    headers = _headers(materialized)
    stream = StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=headers,
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in materialized:
        writer.writerow({key: _csv_value(row.get(key)) for key in headers})
    return _write_text(path, stream.getvalue())


def _headers(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    if not rows:
        return ("state",)
    first = tuple(rows[0])
    observed = set(first)
    for row in rows[1:]:
        if set(row) != observed:
            raise EntryStopImprovementError("DSI009_ARTIFACT_SCHEMA_INCONSISTENT")
    return first


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)
    return path


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    return _write_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n",
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EntryStopImprovementError("DSI009_CERTIFICATE_UNREADABLE") from exc
    if not isinstance(payload, dict):
        raise EntryStopImprovementError("DSI009_CERTIFICATE_INVALID")
    return payload


def _canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    normalized = dict(payload)
    normalized.pop("report_sha256", None)
    body = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    return hashlib.sha256(body.encode()).hexdigest()


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return str(value.value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _percent(value: object) -> str:
    if value is None or not isinstance(value, (str, int, float)):
        return "UNKNOWN"
    return f"{float(value) * 100:.2f}%"


def _number(value: object) -> str:
    if value is None or not isinstance(value, (str, int, float)):
        return "UNKNOWN"
    return f"{float(value):.2f}"


def _currency(value: object) -> str:
    if value is None or not isinstance(value, (str, int, float)):
        return "UNKNOWN"
    return f"INR {float(value):,.2f}"


def _descriptive_result(value: object) -> str:
    if not isinstance(value, dict):
        return "NONE"
    mechanism = value.get("mechanism_id", "UNKNOWN")
    family = value.get("family", "UNKNOWN")
    cagr = _percent(value.get("net_cagr"))
    drawdown = _percent(value.get("maximum_drawdown"))
    return f"{family}/{mechanism}; CAGR {cagr}; drawdown {drawdown}"


__all__ = [
    "DSI009_ARTIFACTS",
    "DSI009_CERTIFICATE",
    "DSI009_REPORT",
    "export_entry_stop_improvement",
    "validate_entry_stop_improvement_certificate",
]
