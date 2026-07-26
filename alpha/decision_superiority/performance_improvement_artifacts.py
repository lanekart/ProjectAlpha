"""Deterministic artifacts and public verification for DSI-008."""

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

from alpha.decision_superiority.performance_improvement import (
    governance_flags,
)
from alpha.decision_superiority.performance_improvement_models import (
    DSI008_CONTRACT_VERSION,
    DSI008_RESEARCH_SCOPE,
    PerformanceImprovementError,
    PerformanceImprovementResult,
)

DSI008_CERTIFICATE = "dsi008_improvement_certificate.json"
DSI008_REPORT = "dsi008_executive_report.md"
DSI008_ARTIFACTS: Final[dict[str, str]] = {
    "source_contract": "dsi008_source_contract_snapshot.csv",
    "tri_contract": "dsi008_tri_benchmark_contract.csv",
    "tri_daily": "dsi008_tri_daily_ledger.csv",
    "baseline_attribution": "dsi008_baseline_performance_attribution.csv",
    "trade_excursions": "dsi008_trade_excursion_diagnostics.csv",
    "wealth_contribution": "dsi008_wealth_contribution.csv",
    "mechanism_bottlenecks": "dsi008_mechanism_bottleneck_attribution.csv",
    "signal_outcomes": "dsi008_signal_outcome_ledger.csv",
    "confidence_calibration": "dsi008_confidence_calibration.csv",
    "challenger_registry": "dsi008_challenger_registry.csv",
    "challenger_changes": "dsi008_challenger_change_ledger.csv",
    "champion_challenger_folds": "dsi008_champion_challenger_folds.csv",
    "challenger_results": "dsi008_challenger_results.csv",
    "tier_definitions": "dsi008_signal_tier_definitions.csv",
    "tier_outcomes": "dsi008_signal_tier_outcomes.csv",
    "portfolio_comparison": "dsi008_portfolio_comparison.csv",
    "daily_equity": "dsi008_daily_equity_curves.csv",
    "accuracy_wealth_tradeoff": "dsi008_accuracy_wealth_tradeoff.csv",
    "calendar_year": "dsi008_calendar_year_performance.csv",
    "rolling_relative": "dsi008_rolling_benchmark_relative_performance.csv",
    "multiple_testing": "dsi008_multiple_testing_results.csv",
    "robustness": "dsi008_robustness_sensitivity.csv",
    "concentration": "dsi008_concentration_diagnostics.csv",
    "population_reconciliation": "dsi008_population_reconciliation.csv",
    "non_vacuity": "dsi008_non_vacuity_probe_ledger.csv",
}


def export_performance_improvement(
    result: PerformanceImprovementResult,
    output: Path,
) -> tuple[Path, ...]:
    """Write and hash-bind the complete deterministic DSI-008 package."""

    output.mkdir(parents=True, exist_ok=True)
    support: list[Path] = []
    for key, filename in DSI008_ARTIFACTS.items():
        try:
            support.append(_write_csv(output / filename, result.rows[key]))
        except PerformanceImprovementError as exc:
            raise PerformanceImprovementError(f"{exc}:{key}") from exc
    report = _write_text(output / DSI008_REPORT, _executive_report(result))
    support.append(report)
    manifest = {
        path.name: _sha256(path) for path in sorted(support, key=lambda item: item.name)
    }
    payload: dict[str, Any] = {
        "contract_version": DSI008_CONTRACT_VERSION,
        "research_scope": DSI008_RESEARCH_SCOPE,
        "source_commit": result.source_commit,
        "source_chain_hashes": {
            str(row["source_role"]): str(row["sha256"])
            for row in result.rows["source_contract"]
        },
        "benchmark_summary": result.summaries["benchmark"],
        "incumbent_summary": result.summaries["incumbent"],
        "performance_attribution": {
            "row_count": result.summaries["attribution_row_count"],
            "weakest_mechanism": result.summaries["weakest_mechanism"],
        },
        "challenger_summary": {
            "tested": result.summaries["challengers_tested"],
            "rejected": result.summaries["challengers_rejected"],
            "accepted": result.summaries["accepted_challenger"],
        },
        "signal_tiers": result.summaries["tiers"],
        "multiple_testing_survived": result.summaries["multiple_testing_survived"],
        "robustness_grade": result.summaries["robustness_grade"],
        "fresh_2026_holdout_available": result.summaries[
            "fresh_2026_holdout_available"
        ],
        "readiness_by_slice": dict(result.readiness),
        "readiness_decision": result.readiness["I"],
        "blockers": list(result.blockers),
        "automatic_promotion_count": 0,
        "executive_report_sha256": _sha256(report),
        "support_artifact_manifest": dict(sorted(manifest.items())),
        "governance_flags": dict(result.governance),
    }
    payload["report_sha256"] = _canonical_payload_sha256(payload)
    certificate = _write_json(output / DSI008_CERTIFICATE, payload)
    return (certificate, *sorted(support, key=lambda path: path.name))


def validate_performance_improvement_certificate(
    certificate: Path,
    *,
    require_ready: bool = False,
) -> dict[str, Any]:
    """Validate the DSI-008 certificate and every support artifact."""

    payload = _read_json(certificate)
    if payload.get("contract_version") != DSI008_CONTRACT_VERSION:
        raise PerformanceImprovementError("UNSUPPORTED_DSI008_CONTRACT")
    if payload.get("research_scope") != DSI008_RESEARCH_SCOPE:
        raise PerformanceImprovementError("DSI008_RESEARCH_SCOPE_MISMATCH")
    if payload.get("governance_flags") != governance_flags():
        raise PerformanceImprovementError("DSI008_GOVERNANCE_FLAGS_INVALID")
    if payload.get("report_sha256") != _canonical_payload_sha256(payload):
        raise PerformanceImprovementError("DSI008_CERTIFICATE_PAYLOAD_TAMPERED")
    manifest = payload.get("support_artifact_manifest")
    expected = frozenset((*DSI008_ARTIFACTS.values(), DSI008_REPORT))
    if not isinstance(manifest, dict) or frozenset(manifest) != expected:
        raise PerformanceImprovementError("DSI008_SUPPORT_MANIFEST_INVALID")
    root = certificate.resolve().parent
    for name, digest in sorted(manifest.items()):
        path = (root / str(name)).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise PerformanceImprovementError("DSI008_SUPPORT_PATH_UNSAFE")
        if _sha256(path) != str(digest):
            raise PerformanceImprovementError(f"DSI008_ARTIFACT_TAMPERED:{name}")
        if b"/Users/" in path.read_bytes():
            raise PerformanceImprovementError(f"DSI008_MACHINE_LOCAL_PATH_LEAK:{name}")
    if payload.get("executive_report_sha256") != _sha256(root / DSI008_REPORT):
        raise PerformanceImprovementError("DSI008_EXECUTIVE_REPORT_HASH_MISMATCH")
    if payload.get("automatic_promotion_count") != 0:
        raise PerformanceImprovementError("DSI008_AUTOMATIC_PROMOTION")
    readiness = str(payload.get("readiness_decision") or "")
    if require_ready and not readiness.startswith("READY_"):
        raise PerformanceImprovementError(f"DSI008_NOT_READY:{readiness}")
    return payload


def _executive_report(result: PerformanceImprovementResult) -> str:
    summary = result.summaries
    benchmark = summary["benchmark"]
    incumbent = summary["incumbent"]
    tiers = summary["tiers"]
    lines = [
        "# DSI-008 Governed Performance Improvement",
        "",
        "## Certification",
        "",
        f"- Final readiness: `{result.readiness['I']}`",
        f"- Robustness grade: `{summary['robustness_grade']}`",
        "- Production influence: `false`",
        "- Automatic strategy promotion: `false`",
        "",
        "## Governed Benchmark",
        "",
        f"- Benchmark: {benchmark['name']} ({benchmark['kind']})",
        f"- Source: {benchmark['source']}",
        f"- Period: {benchmark['start_date']} to {benchmark['end_date']}",
        f"- CAGR: {_percent(benchmark['cagr'])}",
        "",
        "## Frozen DSI-007 Incumbent",
        "",
        f"- Net CAGR: {_percent(incumbent['net_cagr'])}",
        f"- Excess CAGR: {_percent(incumbent['excess_cagr'])}",
        f"- Maximum drawdown: {_percent(incumbent['maximum_drawdown'])}",
        f"- Sharpe: {_number(incumbent['sharpe'])}",
        f"- Sortino: {_number(incumbent['sortino'])}",
        "",
        "## Performance Attribution",
        "",
        f"- Attribution rows: {summary['attribution_row_count']}",
        f"- Weakest observed mechanism: {summary['weakest_mechanism']}",
        "",
        "## Bounded Mechanism Research",
        "",
        f"- Challengers tested: {summary['challengers_tested']}",
        f"- Challengers rejected: {summary['challengers_rejected']}",
        (f"- Accepted challenger: {summary['accepted_challenger'] or 'NONE'}"),
        (
            "- Multiple-testing controls survived: "
            f"{str(summary['multiple_testing_survived']).lower()}"
        ),
        "",
        "## Signal Tiers",
        "",
    ]
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
                f"- Completed sample: {tier['completed_count']}",
                f"- Observed accuracy: {_percent(tier['observed_accuracy'])}",
                (
                    "- Wilson interval: "
                    f"{_percent(tier['wilson_lower'])} to "
                    f"{_percent(tier['wilson_upper'])}"
                ),
                f"- Expectancy: {_percent(tier['expectancy'])}",
                (
                    "- Accuracy target supported: "
                    f"{str(tier['accuracy_target_supported']).lower()}"
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Research Boundary",
            "",
            f"{summary['interpretation']}",
            "",
            "No challenger or signal tier was activated. DSI-008 is an "
            "offline research package only.",
            "",
            "## Slice Readiness",
            "",
        ]
    )
    lines.extend(
        f"- DSI-008{slice_id}: `{readiness}`"
        for slice_id, readiness in result.readiness.items()
    )
    if result.blockers:
        lines.extend(
            ["", "## Remaining Limitations", ""]
            + [f"- {blocker}" for blocker in result.blockers]
        )
    return "\n".join(lines) + "\n"


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> Path:
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
            raise PerformanceImprovementError("DSI008_ARTIFACT_SCHEMA_INCONSISTENT")
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
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        + "\n",
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PerformanceImprovementError("DSI008_CERTIFICATE_UNREADABLE") from exc
    if not isinstance(payload, dict):
        raise PerformanceImprovementError("DSI008_CERTIFICATE_INVALID")
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
    if value is None:
        return "UNKNOWN"
    if not isinstance(value, (str, int, float)):
        return "UNKNOWN"
    return f"{float(value) * 100:.2f}%"


def _number(value: object) -> str:
    if value is None:
        return "UNKNOWN"
    if not isinstance(value, (str, int, float)):
        return "UNKNOWN"
    return f"{float(value):.2f}"


__all__ = [
    "DSI008_ARTIFACTS",
    "DSI008_CERTIFICATE",
    "DSI008_REPORT",
    "export_performance_improvement",
    "validate_performance_improvement_certificate",
]
