"""Deterministic artifacts and public verification for DSI-010."""

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

from alpha.decision_superiority.pre2016_external_validation import governance_flags
from alpha.decision_superiority.pre2016_external_validation_models import (
    DSI010_CONTRACT_VERSION,
    DSI010_EXTERNAL_END,
    DSI010_EXTERNAL_START,
    DSI010_RESEARCH_SCOPE,
    Pre2016ExternalValidationError,
    Pre2016ExternalValidationResult,
)

DSI010_CERTIFICATE = "dsi010_pre2016_external_certificate.json"
DSI010_REPORT = "dsi010_executive_report.md"
DSI010_ARTIFACTS: Final[dict[str, str]] = {
    "protocol": "dsi010_frozen_protocol.csv",
    "frozen_contract": "dsi010_frozen_challenger_contract.csv",
    "source_contract": "dsi010_source_contract_snapshot.csv",
    "market_data_coverage": "dsi010_market_data_coverage.csv",
    "universe": "dsi010_universe_membership.csv",
    "corporate_actions": "dsi010_corporate_action_audit.csv",
    "benchmark_contract": "dsi010_benchmark_contract.csv",
    "regime_daily": "dsi010_regime_daily_ledger.csv",
    "regime_transitions": "dsi010_regime_transitions.csv",
    "frozen_policy_mapping": "dsi010_frozen_policy_mapping.csv",
    "frozen_incumbent_signals": "dsi010_frozen_incumbent_signals.csv",
    "frozen_challenger_signals": "dsi010_frozen_challenger_signals.csv",
    "frozen_incumbent_trades": "dsi010_frozen_incumbent_trades.csv",
    "frozen_challenger_trades": "dsi010_frozen_challenger_trades.csv",
    "stop_differences": "dsi010_stop_difference_ledger.csv",
    "external_daily_equity": "dsi010_external_daily_equity.csv",
    "replication_folds": "dsi010_pre2016_walk_forward_folds.csv",
    "replication_selection": "dsi010_pre2016_strategy_selection.csv",
    "replication_portfolios": "dsi010_pre2016_comparison_portfolios.csv",
    "calendar_performance": "dsi010_calendar_year_performance.csv",
    "rolling_performance": "dsi010_rolling_performance.csv",
    "regime_performance": "dsi010_regime_performance.csv",
    "metrics": "dsi010_cagr_and_risk_metrics.csv",
    "benchmark_relative": "dsi010_benchmark_relative_metrics.csv",
    "robustness": "dsi010_robustness_sensitivity.csv",
    "concentration": "dsi010_concentration_diagnostics.csv",
    "population_reconciliation": "dsi010_population_reconciliation.csv",
    "non_vacuity": "dsi010_non_vacuity_probe_ledger.csv",
}


def export_pre2016_external_validation(
    result: Pre2016ExternalValidationResult,
    output: Path,
) -> tuple[Path, ...]:
    """Write and hash-bind the complete deterministic DSI-010 package."""

    output.mkdir(parents=True, exist_ok=True)
    support: list[Path] = []
    for key, filename in DSI010_ARTIFACTS.items():
        rows = result.rows.get(key)
        if rows is None:
            raise Pre2016ExternalValidationError(f"DSI010_RESULT_ROWS_MISSING:{key}")
        support.append(_write_csv(output / filename, rows))
    report = _write_text(output / DSI010_REPORT, _executive_report(result))
    support.append(report)
    manifest = {
        path.name: _sha256(path) for path in sorted(support, key=lambda item: item.name)
    }
    payload: dict[str, Any] = {
        "contract_version": DSI010_CONTRACT_VERSION,
        "research_scope": DSI010_RESEARCH_SCOPE,
        "source_commit": result.source_commit,
        "external_period": {
            "start": DSI010_EXTERNAL_START,
            "end": DSI010_EXTERNAL_END,
        },
        "frozen_challenger_id": result.summaries["frozen_challenger_id"],
        "actual_transport_period": {
            "start": result.summaries["actual_transport_start"],
            "end": result.summaries["actual_transport_end"],
        },
        "market_population": {
            "sessions": result.summaries["market_sessions"],
            "securities": result.summaries["market_securities"],
            "rows": result.summaries["market_rows"],
        },
        "incumbent_summary": result.summaries["incumbent"],
        "challenger_summary": result.summaries["challenger"],
        "benchmark_summary": result.summaries["benchmark"],
        "benchmark_gap_closed": result.summaries["benchmark_gap_closed"],
        "independent_replication_summary": {
            "regime_aware": result.summaries["replication_regime_aware"],
            "benchmark": result.summaries["replication_benchmark"],
        },
        "external_validation_classification": result.summaries["classification"],
        "top_five_positive_profit_share": result.summaries[
            "top_five_positive_profit_share"
        ],
        "external_tuning_performed": result.summaries["external_tuning_performed"],
        "challenger_contract_changed": result.summaries["challenger_contract_changed"],
        "forward_paper_eligible": result.summaries["forward_paper_eligible"],
        "readiness_by_slice": dict(result.readiness),
        "readiness_decision": result.readiness["I"],
        "blockers": list(result.blockers),
        "automatic_promotion_count": 0,
        "executive_report_sha256": _sha256(report),
        "support_artifact_manifest": dict(sorted(manifest.items())),
        "governance_flags": dict(result.governance),
    }
    payload["report_sha256"] = _canonical_payload_sha256(payload)
    certificate = _write_json(output / DSI010_CERTIFICATE, payload)
    return (certificate, *sorted(support, key=lambda path: path.name))


def validate_pre2016_external_validation_certificate(
    certificate: Path,
    *,
    require_ready: bool = False,
) -> dict[str, Any]:
    """Validate the DSI-010 certificate and every bound support artifact."""

    payload = _read_json(certificate)
    if payload.get("contract_version") != DSI010_CONTRACT_VERSION:
        raise Pre2016ExternalValidationError("UNSUPPORTED_DSI010_CONTRACT")
    if payload.get("research_scope") != DSI010_RESEARCH_SCOPE:
        raise Pre2016ExternalValidationError("DSI010_RESEARCH_SCOPE_MISMATCH")
    if payload.get("governance_flags") != governance_flags():
        raise Pre2016ExternalValidationError("DSI010_GOVERNANCE_FLAGS_INVALID")
    if payload.get("report_sha256") != _canonical_payload_sha256(payload):
        raise Pre2016ExternalValidationError("DSI010_CERTIFICATE_PAYLOAD_TAMPERED")
    period = payload.get("external_period")
    if not isinstance(period, Mapping):
        raise Pre2016ExternalValidationError("DSI010_EXTERNAL_PERIOD_MISSING")
    if period.get("start") != DSI010_EXTERNAL_START.isoformat():
        raise Pre2016ExternalValidationError("DSI010_EXTERNAL_START_DRIFT")
    if period.get("end") != DSI010_EXTERNAL_END.isoformat():
        raise Pre2016ExternalValidationError("DSI010_EXTERNAL_END_DRIFT")
    if date.fromisoformat(str(period["end"])) >= date(2016, 1, 1):
        raise Pre2016ExternalValidationError("DSI010_EXTERNAL_PERIOD_OVERLAPS_2016")
    if payload.get("external_tuning_performed") is not False:
        raise Pre2016ExternalValidationError("DSI010_EXTERNAL_TUNING_DETECTED")
    if payload.get("challenger_contract_changed") is not False:
        raise Pre2016ExternalValidationError("DSI010_CHALLENGER_CONTRACT_DRIFT")
    if payload.get("automatic_promotion_count") != 0:
        raise Pre2016ExternalValidationError("DSI010_AUTOMATIC_PROMOTION_DETECTED")
    manifest = payload.get("support_artifact_manifest")
    expected = frozenset((*DSI010_ARTIFACTS.values(), DSI010_REPORT))
    if not isinstance(manifest, Mapping) or frozenset(manifest) != expected:
        raise Pre2016ExternalValidationError("DSI010_SUPPORT_MANIFEST_INVALID")
    root = certificate.resolve().parent
    for name, digest in sorted(manifest.items()):
        path = (root / str(name)).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise Pre2016ExternalValidationError("DSI010_SUPPORT_PATH_UNSAFE")
        if _sha256(path) != str(digest):
            raise Pre2016ExternalValidationError(f"DSI010_ARTIFACT_TAMPERED:{name}")
        if b"/Users/" in path.read_bytes():
            raise Pre2016ExternalValidationError(
                f"DSI010_MACHINE_LOCAL_PATH_LEAK:{name}"
            )
    if payload.get("executive_report_sha256") != _sha256(root / DSI010_REPORT):
        raise Pre2016ExternalValidationError("DSI010_EXECUTIVE_REPORT_HASH_MISMATCH")
    readiness = str(payload.get("readiness_decision") or "")
    if require_ready and not readiness.startswith("READY_"):
        raise Pre2016ExternalValidationError(f"DSI010_NOT_READY:{readiness}")
    return payload


def _executive_report(result: Pre2016ExternalValidationResult) -> str:
    summary = result.summaries
    incumbent = cast_mapping(summary["incumbent"])
    challenger = cast_mapping(summary["challenger"])
    benchmark = cast_mapping(summary["benchmark"])
    replication = summary.get("replication_regime_aware")
    replication_metric = (
        cast_mapping(replication) if isinstance(replication, Mapping) else {}
    )
    readiness_lines = tuple(
        f"- DSI-010{slice_id}: `{decision}`"
        for slice_id, decision in result.readiness.items()
    )
    return "\n".join(
        (
            "# DSI-010 Governed Pre-2016 External-Era Validation",
            "",
            "## Certification",
            "",
            f"- Final readiness: `{result.readiness['I']}`",
            (f"- External classification: `{summary['classification']}`"),
            "- External tuning performed: `false`",
            "- Challenger contract changed: `false`",
            "- Production influence: `false`",
            "",
            "## External Era",
            "",
            (
                f"- Protocol period: {summary['external_start']} to "
                f"{summary['external_end']}"
            ),
            (
                f"- Actual frozen-policy transport period: "
                f"{summary['actual_transport_start']} to "
                f"{summary['actual_transport_end']}"
            ),
            f"- Sessions: {summary['market_sessions']}",
            f"- Securities: {summary['market_securities']}",
            f"- Security-session rows: {summary['market_rows']}",
            "",
            "## Frozen Policy Transport",
            "",
            f"- Candidate: `{summary['frozen_challenger_id']}`",
            (
                "- Incumbent net CAGR: "
                f"{_display(incumbent.get('net_cagr'), percent=True)}"
            ),
            (
                "- Challenger net CAGR: "
                f"{_display(challenger.get('net_cagr'), percent=True)}"
            ),
            (
                "- Benchmark net CAGR: "
                f"{_display(benchmark.get('net_cagr'), percent=True)}"
            ),
            (
                "- Incumbent maximum drawdown: "
                f"{_display(incumbent.get('maximum_drawdown'), percent=True)}"
            ),
            (
                "- Challenger maximum drawdown: "
                f"{_display(challenger.get('maximum_drawdown'), percent=True)}"
            ),
            f"- Incumbent trades: {incumbent.get('trade_count', 0)}",
            f"- Challenger trades: {challenger.get('trade_count', 0)}",
            (
                "- Challenger win rate: "
                f"{_display(challenger.get('win_rate'), percent=True)}"
            ),
            (
                "- Challenger expectancy: "
                f"{_display(challenger.get('expectancy'), percent=True)}"
            ),
            (
                "- Benchmark gap closed: "
                f"{_display(summary.get('benchmark_gap_closed'), percent=True)}"
            ),
            "",
            "## Independent-Era Walk-Forward Replication",
            "",
            (
                "- Regime-aware net CAGR: "
                f"{_display(replication_metric.get('net_cagr'), percent=True)}"
            ),
            (
                "- Regime-aware maximum drawdown: "
                f"{_display(replication_metric.get('maximum_drawdown'), percent=True)}"
            ),
            (f"- Regime-aware trades: {replication_metric.get('trade_count', 0)}"),
            "",
            "## Readiness A-I",
            "",
            *readiness_lines,
            "",
            "## Interpretation Boundary",
            "",
            (
                "The 2005-2015 prices evaluate rules frozen before this run. "
                "They do not select entries, stops, exits, regimes, or parameters."
            ),
            (
                "The frozen-policy transport result and the independent-era "
                "walk-forward replication remain separate evidence populations."
            ),
            "No strategy or stop policy was automatically promoted.",
            "",
        )
    )


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    normalized = [
        {str(key): _normalise(value) for key, value in row.items()} for row in rows
    ]
    headers = sorted({key for row in normalized for key in row})
    stream = StringIO(newline="")
    if headers:
        writer = csv.DictWriter(
            stream,
            fieldnames=headers,
            extrasaction="raise",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in normalized:
            writer.writerow({key: row.get(key, "") for key in headers})
    return _write_text(path, stream.getvalue())


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    text = (
        json.dumps(
            _normalise(dict(payload)),
            indent=2,
            sort_keys=True,
            separators=(",", ": "),
        )
        + "\n"
    )
    return _write_text(path, text)


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)
    return path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise Pre2016ExternalValidationError("DSI010_CERTIFICATE_UNAVAILABLE")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Pre2016ExternalValidationError("DSI010_CERTIFICATE_INVALID_JSON") from exc
    if not isinstance(payload, dict):
        raise Pre2016ExternalValidationError("DSI010_CERTIFICATE_NOT_OBJECT")
    return payload


def _canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    canonical = dict(payload)
    canonical.pop("report_sha256", None)
    raw = json.dumps(
        _normalise(canonical),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.name
    if isinstance(value, Mapping):
        return {
            str(key): _normalise(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _display(value: object, *, percent: bool = False) -> str:
    if value is None:
        return "UNKNOWN"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number * 100:.2f}%" if percent else f"{number:.4f}"


def cast_mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Pre2016ExternalValidationError("DSI010_SUMMARY_MAPPING_INVALID")
    return {str(key): item for key, item in value.items()}


__all__ = [
    "DSI010_ARTIFACTS",
    "DSI010_CERTIFICATE",
    "DSI010_REPORT",
    "export_pre2016_external_validation",
    "validate_pre2016_external_validation_certificate",
]
