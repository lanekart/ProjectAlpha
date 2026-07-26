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
    DSI010_RESEARCH_SCOPE,
    Pre2016ExternalValidationError,
    Pre2016ExternalValidationResult,
)

DSI010_CERTIFICATE = "dsi010_pre2016_external_certificate.json"
DSI010_REPORT = "dsi010_executive_report.md"
DSI010_ARTIFACTS: Final[dict[str, str]] = {
    "source_contract": "dsi010_source_contract_snapshot.csv",
    "frozen_protocol": "dsi010_frozen_protocol.csv",
    "market_data_coverage": "dsi010_market_data_coverage.csv",
    "universe": "dsi010_universe_membership.csv",
    "corporate_actions": "dsi010_corporate_action_audit.csv",
    "benchmark": "dsi010_benchmark_contract.csv",
    "frozen_mapping": "dsi010_frozen_regime_strategy_mapping.csv",
    "incumbent_signals": "dsi010_frozen_incumbent_signals.csv",
    "challenger_signals": "dsi010_frozen_challenger_signals.csv",
    "incumbent_trades": "dsi010_frozen_incumbent_trades.csv",
    "challenger_trades": "dsi010_frozen_challenger_trades.csv",
    "stop_differences": "dsi010_stop_difference_ledger.csv",
    "external_daily_equity": "dsi010_external_daily_equity.csv",
    "walk_forward_folds": "dsi010_pre2016_walk_forward_folds.csv",
    "strategy_selections": "dsi010_pre2016_strategy_selection.csv",
    "comparison_portfolios": "dsi010_pre2016_comparison_portfolios.csv",
    "calendar_performance": "dsi010_calendar_year_performance.csv",
    "rolling_performance": "dsi010_rolling_performance.csv",
    "regime_performance": "dsi010_regime_performance.csv",
    "risk_metrics": "dsi010_cagr_and_risk_metrics.csv",
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
    support = [
        _write_csv(output / filename, result.rows[key])
        for key, filename in DSI010_ARTIFACTS.items()
    ]
    report = _write_text(output / DSI010_REPORT, _executive_report(result))
    support.append(report)
    manifest = {
        path.name: _sha256(path)
        for path in sorted(support, key=lambda item: item.name)
    }
    summary = result.summaries
    payload: dict[str, Any] = {
        "contract_version": DSI010_CONTRACT_VERSION,
        "research_scope": DSI010_RESEARCH_SCOPE,
        "source_commit": result.source_commit,
        "protocol": summary["protocol"],
        "source_coverage": summary["source_coverage"],
        "frozen_mapping": summary["frozen_mapping"],
        "test_a_incumbent": summary["test_a_incumbent"],
        "test_a_challenger": summary["test_a_challenger"],
        "benchmark": summary["benchmark"],
        "test_b_regime_aware": summary["test_b_regime_aware"],
        "test_b_fixed": summary["test_b_fixed"],
        "test_b_momentum": summary["test_b_momentum"],
        "test_b_trend": summary["test_b_trend"],
        "external_validation_classification": summary[
            "external_validation_classification"
        ],
        "forward_paper_eligible": summary["forward_paper_eligible"],
        "automatic_promotion_count": summary["automatic_promotion_count"],
        "readiness_by_slice": dict(result.readiness),
        "readiness_decision": result.readiness["I"],
        "blockers": list(result.blockers),
        "support_artifact_manifest": dict(sorted(manifest.items())),
        "executive_report_sha256": _sha256(report),
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
    """Validate a DSI-010 certificate and every bound support artifact."""

    payload = _read_json(certificate)
    if payload.get("contract_version") != DSI010_CONTRACT_VERSION:
        raise Pre2016ExternalValidationError("UNSUPPORTED_DSI010_CONTRACT")
    if payload.get("research_scope") != DSI010_RESEARCH_SCOPE:
        raise Pre2016ExternalValidationError("DSI010_RESEARCH_SCOPE_MISMATCH")
    if payload.get("governance_flags") != governance_flags():
        raise Pre2016ExternalValidationError("DSI010_GOVERNANCE_FLAGS_INVALID")
    if payload.get("report_sha256") != _canonical_payload_sha256(payload):
        raise Pre2016ExternalValidationError(
            "DSI010_CERTIFICATE_PAYLOAD_TAMPERED"
        )
    manifest = payload.get("support_artifact_manifest")
    expected = frozenset((*DSI010_ARTIFACTS.values(), DSI010_REPORT))
    if not isinstance(manifest, dict) or frozenset(manifest) != expected:
        raise Pre2016ExternalValidationError("DSI010_SUPPORT_MANIFEST_INVALID")
    root = certificate.resolve().parent
    for name, digest in sorted(manifest.items()):
        path = (root / str(name)).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise Pre2016ExternalValidationError("DSI010_SUPPORT_PATH_UNSAFE")
        if _sha256(path) != str(digest):
            raise Pre2016ExternalValidationError(
                f"DSI010_ARTIFACT_TAMPERED:{name}"
            )
        raw = path.read_bytes()
        if b"/Users/" in raw or b"C:\\Users\\" in raw:
            raise Pre2016ExternalValidationError(
                f"DSI010_MACHINE_LOCAL_PATH_LEAK:{name}"
            )
    report = root / DSI010_REPORT
    if payload.get("executive_report_sha256") != _sha256(report):
        raise Pre2016ExternalValidationError("DSI010_REPORT_HASH_MISMATCH")
    if payload.get("automatic_promotion_count") != 0:
        raise Pre2016ExternalValidationError("DSI010_AUTOMATIC_PROMOTION")
    valid_promotions = {
        "EXTERNAL_VALIDATION_PASSED",
        "CHALLENGER_BEATS_BENCHMARK",
    }
    if payload.get("forward_paper_eligible") and payload.get(
        "external_validation_classification"
    ) not in valid_promotions:
        raise Pre2016ExternalValidationError(
            "DSI010_UNSUPPORTED_FORWARD_ELIGIBILITY"
        )
    readiness = str(payload.get("readiness_decision") or "")
    if require_ready and not readiness.startswith("READY_"):
        raise Pre2016ExternalValidationError(f"DSI010_NOT_READY:{readiness}")
    return payload


def _executive_report(result: Pre2016ExternalValidationResult) -> str:
    summary = result.summaries
    incumbent = summary["test_a_incumbent"]
    challenger = summary["test_a_challenger"]
    benchmark = summary["benchmark"]
    test_b = summary["test_b_regime_aware"]
    incumbent_delta = _difference(
        challenger.get("net_cagr"),
        incumbent.get("net_cagr"),
    )
    benchmark_delta = _difference(
        challenger.get("net_cagr"),
        benchmark.get("net_cagr"),
    )
    lines = [
        "# DSI-010 Governed 2005-2015 External-Era Validation",
        "",
        "## Certification",
        "",
        f"- Final readiness: `{result.readiness['I']}`",
        (
            "- External validation classification: "
            f"`{summary['external_validation_classification']}`"
        ),
        (
            "- Extended forward-paper eligibility: "
            f"`{str(summary['forward_paper_eligible']).lower()}`"
        ),
        "- Automatic mechanism promotion: `false`",
        "- Production influence: `false`",
        "",
        "## Frozen Test A",
        "",
        f"- Incumbent net CAGR: {_percent(incumbent.get('net_cagr'))}",
        f"- Challenger net CAGR: {_percent(challenger.get('net_cagr'))}",
        f"- Benchmark CAGR: {_percent(benchmark.get('net_cagr'))}",
        f"- Challenger minus incumbent CAGR: {_percent(incumbent_delta)}",
        f"- Challenger minus benchmark CAGR: {_percent(benchmark_delta)}",
        (
            "- Incumbent drawdown: "
            f"{_percent(incumbent.get('maximum_drawdown'))}"
        ),
        (
            "- Challenger drawdown: "
            f"{_percent(challenger.get('maximum_drawdown'))}"
        ),
        f"- Incumbent trades: {incumbent.get('trade_count', 0)}",
        f"- Challenger trades: {challenger.get('trade_count', 0)}",
        f"- Challenger win rate: {_percent(challenger.get('win_rate'))}",
        f"- Challenger expectancy: {_percent(challenger.get('expectancy'))}",
        "",
        "## Independent Test B",
        "",
        f"- Regime-aware net CAGR: {_percent(test_b.get('net_cagr'))}",
        (
            "- Regime-aware drawdown: "
            f"{_percent(test_b.get('maximum_drawdown'))}"
        ),
        f"- Regime-aware trades: {test_b.get('trade_count', 0)}",
        "",
        "## Slice Readiness",
        "",
        *[
            f"- DSI-010{slice_id}: `{readiness}`"
            for slice_id, readiness in result.readiness.items()
        ],
        "",
        "## Interpretation Boundary",
        "",
        (
            "The 2005-2015 period was not used to tune STOP-STRUCTURAL-10D. "
            "Test A transports a frozen mapping and changes only the stop. "
            "Test B is a separate walk-forward replication. Neither result "
            "activates a live or production mechanism."
        ),
    ]
    if result.blockers:
        lines.extend(["", "## Remaining Limitations", ""])
        lines.extend(f"- {blocker}" for blocker in result.blockers)
    return "\n".join(lines) + "\n"


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    materialized = [dict(row) for row in rows]
    headers = _headers(materialized)
    stream = StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=headers,
        extrasaction="raise",
    )
    writer.writeheader()
    for row in materialized:
        writer.writerow({key: _csv_value(row.get(key)) for key in headers})
    _atomic_write(path, stream.getvalue().encode())
    return path


def _headers(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    keys: set[str] = set()
    for row in rows:
        keys.update(str(key) for key in row)
    return tuple(sorted(keys)) or ("empty",)


def _csv_value(value: Any) -> Any:
    if value is None:
        return "UNKNOWN"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(
            _jsonable(value),
            sort_keys=True,
            separators=(",", ":"),
        )
    return value


def _write_text(path: Path, content: str) -> Path:
    _atomic_write(path, content.encode())
    return path


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    content = json.dumps(_jsonable(payload), indent=2, sort_keys=True) + "\n"
    _atomic_write(path, content.encode())
    return path


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise Pre2016ExternalValidationError("DSI010_CERTIFICATE_UNAVAILABLE")
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise Pre2016ExternalValidationError("DSI010_CERTIFICATE_INVALID")
    return payload


def _canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    canonical = dict(payload)
    canonical.pop("report_sha256", None)
    raw = json.dumps(
        _jsonable(canonical),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(item)
            for key, item in sorted(value.items())
        }
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        return _jsonable(value.item())
    return str(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _difference(left: object, right: object) -> float | None:
    if left is None or right is None:
        return None
    try:
        return float(left) - float(right)
    except (TypeError, ValueError):
        return None


def _percent(value: object) -> str:
    if value is None:
        return "UNKNOWN"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "UNKNOWN"


__all__ = [
    "DSI010_ARTIFACTS",
    "DSI010_CERTIFICATE",
    "export_pre2016_external_validation",
    "validate_pre2016_external_validation_certificate",
]
