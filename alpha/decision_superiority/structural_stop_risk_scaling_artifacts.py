"""Deterministic DSI-012 artifacts and public certificate verification."""

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

from alpha.decision_superiority.structural_stop_risk_scaling import governance_flags
from alpha.decision_superiority.structural_stop_risk_scaling_models import (
    DSI012_CONTRACT_VERSION,
    DSI012_RESEARCH_SCOPE,
    StructuralStopRiskScalingError,
    StructuralStopRiskScalingResult,
)

DSI012_CERTIFICATE = "dsi012_structural_stop_risk_scaling_certificate.json"
DSI012_REPORT = "dsi012_executive_report.md"
DSI012_ARTIFACTS: Final[dict[str, str]] = {
    "source_contract": "dsi012_source_contract_snapshot.csv",
    "rehydration_parity": "dsi012_rehydration_parity.csv",
    "base_daily_equity": "dsi012_base_structural_stop_daily_equity.csv",
    "scaled_daily_equity": "dsi012_scaled_daily_equity.csv",
    "stress_daily_equity": "dsi012_stress_financing_daily_equity.csv",
    "positions": "dsi012_scaled_position_notional_ledger.csv",
    "trades": "dsi012_scaled_trade_notional_ledger.csv",
    "transaction_costs": "dsi012_scaled_transaction_cost_ledger.csv",
    "financing": "dsi012_daily_financing_ledger.csv",
    "capacity": "dsi012_capacity_ledger.csv",
    "acceptance": "dsi012_acceptance_gates.csv",
}


def export_structural_stop_risk_scaling(
    result: StructuralStopRiskScalingResult,
    output: Path,
) -> tuple[Path, ...]:
    """Write the complete deterministic DSI-012 package."""

    output.mkdir(parents=True, exist_ok=True)
    support = [
        _write_csv(output / filename, result.rows[key])
        for key, filename in DSI012_ARTIFACTS.items()
    ]
    report = _write_text(output / DSI012_REPORT, _executive_report(result))
    support.append(report)
    manifest = {
        path.name: _sha256(path) for path in sorted(support, key=lambda item: item.name)
    }
    payload: dict[str, Any] = {
        "contract_version": DSI012_CONTRACT_VERSION,
        "research_scope": DSI012_RESEARCH_SCOPE,
        "source_commit": result.source_commit,
        "source_chain_hashes": {
            str(row["source_role"]): str(row["sha256"])
            for row in result.rows["source_contract"]
        },
        "readiness_decision": result.readiness,
        "blockers": list(result.blockers),
        "mechanism_id": result.summaries["mechanism_id"],
        "risk_multiplier": result.summaries["risk_multiplier"],
        "base_structural_stop": result.summaries["base_structural_stop"],
        "base_financing": result.summaries["base_financing"],
        "stress_financing": result.summaries["stress_financing"],
        "benchmark_cagr": result.summaries["benchmark_cagr"],
        "capacity_failure_count": result.summaries["capacity_failure_count"],
        "acceptance_passed": result.summaries["acceptance_passed"],
        "retrospective_target_match": result.summaries["retrospective_target_match"],
        "validated_strategy": result.summaries["validated_strategy"],
        "fresh_unused_holdout_available": result.summaries[
            "fresh_unused_holdout_available"
        ],
        "forward_paper_eligible": result.summaries["forward_paper_eligible"],
        "automatic_promotion": result.summaries["automatic_promotion"],
        "stress_used_for_selection": result.summaries["stress_used_for_selection"],
        "interpretation": result.summaries["interpretation"],
        "executive_report_sha256": _sha256(report),
        "support_artifact_manifest": dict(sorted(manifest.items())),
        "governance_flags": dict(result.governance),
    }
    payload["report_sha256"] = _canonical_payload_sha256(payload)
    certificate = _write_json(output / DSI012_CERTIFICATE, payload)
    return (certificate, *sorted(support, key=lambda item: item.name))


def validate_structural_stop_risk_scaling_certificate(
    certificate: Path,
    *,
    require_target_match: bool = False,
) -> dict[str, Any]:
    """Validate the DSI-012 certificate and every bound support artifact."""

    payload = _read_json(certificate)
    if payload.get("contract_version") != DSI012_CONTRACT_VERSION:
        raise StructuralStopRiskScalingError("UNSUPPORTED_DSI012_CONTRACT")
    if payload.get("research_scope") != DSI012_RESEARCH_SCOPE:
        raise StructuralStopRiskScalingError("DSI012_RESEARCH_SCOPE_MISMATCH")
    if payload.get("governance_flags") != governance_flags():
        raise StructuralStopRiskScalingError("DSI012_GOVERNANCE_FLAGS_INVALID")
    if payload.get("report_sha256") != _canonical_payload_sha256(payload):
        raise StructuralStopRiskScalingError("DSI012_CERTIFICATE_PAYLOAD_TAMPERED")
    manifest = payload.get("support_artifact_manifest")
    expected = frozenset((*DSI012_ARTIFACTS.values(), DSI012_REPORT))
    if not isinstance(manifest, dict) or frozenset(manifest) != expected:
        raise StructuralStopRiskScalingError("DSI012_SUPPORT_MANIFEST_INVALID")
    root = certificate.resolve().parent
    for name, digest in sorted(manifest.items()):
        path = (root / str(name)).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise StructuralStopRiskScalingError("DSI012_SUPPORT_PATH_UNSAFE")
        if _sha256(path) != str(digest):
            raise StructuralStopRiskScalingError(f"DSI012_ARTIFACT_TAMPERED:{name}")
        if b"/Users/" in path.read_bytes():
            raise StructuralStopRiskScalingError(
                f"DSI012_MACHINE_LOCAL_PATH_LEAK:{name}"
            )
    if payload.get("executive_report_sha256") != _sha256(root / DSI012_REPORT):
        raise StructuralStopRiskScalingError("DSI012_REPORT_HASH_MISMATCH")
    if payload.get("automatic_promotion") is not False:
        raise StructuralStopRiskScalingError("DSI012_AUTOMATIC_PROMOTION_INVALID")
    if payload.get("validated_strategy") is not False:
        raise StructuralStopRiskScalingError("DSI012_VALIDATION_OVERCLAIM")
    if payload.get("stress_used_for_selection") is not False:
        raise StructuralStopRiskScalingError("DSI012_STRESS_SELECTION_LEAKAGE")
    if require_target_match and not payload.get("acceptance_passed"):
        raise StructuralStopRiskScalingError("DSI012_TARGET_NOT_MATCHED")
    return payload


def _executive_report(result: StructuralStopRiskScalingResult) -> str:
    base = result.summaries["base_structural_stop"]
    scaled = result.summaries["base_financing"]
    stress = result.summaries["stress_financing"]
    lines = [
        "# DSI-012 Governed 1.50x Structural-Stop Risk Scaling",
        "",
        "## Decision",
        "",
        f"- Readiness: `{result.readiness}`",
        (
            "- Retrospective target match: "
            f"`{str(result.summaries['retrospective_target_match']).lower()}`"
        ),
        "- Validated strategy: `false`",
        "- Automatic promotion: `false`",
        "- Production influence: `false`",
        "",
        "## Frozen Base Mechanism",
        "",
        f"- Mechanism: `{result.summaries['mechanism_id']}`",
        f"- Base net CAGR: {_percent(base.get('net_cagr'))}",
        f"- Base maximum drawdown: {_percent(base.get('maximum_drawdown'))}",
        f"- Base Calmar: {_number(base.get('calmar'))}",
        f"- Base trades: {base.get('trade_count', 'UNKNOWN')}",
        "",
        "## Fixed 1.50x Overlay — Base Financing",
        "",
        f"- Net CAGR: {_percent(scaled.get('net_cagr'))}",
        f"- Maximum drawdown: {_percent(scaled.get('maximum_drawdown'))}",
        f"- Calmar: {_number(scaled.get('calmar'))}",
        f"- Daily profit factor: {_number(scaled.get('daily_profit_factor'))}",
        f"- Trade expectancy: {_percent(scaled.get('expectancy'))}",
        f"- Financing rate: {_percent(scaled.get('financing_rate'))}",
        f"- Financing costs: {_currency(scaled.get('total_financing_costs'))}",
        f"- Maximum gross exposure: {_percent(scaled.get('maximum_gross_exposure'))}",
        f"- Benchmark CAGR: {_percent(result.summaries['benchmark_cagr'])}",
        "",
        "## Higher-Rate Stress — Not Used for Selection",
        "",
        f"- Net CAGR: {_percent(stress.get('net_cagr'))}",
        f"- Maximum drawdown: {_percent(stress.get('maximum_drawdown'))}",
        f"- Financing rate: {_percent(stress.get('financing_rate'))}",
        "- Stress used for selection: `false`",
        "",
        "## Capacity and Acceptance",
        "",
        (f"- Capacity failures: {result.summaries['capacity_failure_count']}"),
    ]
    lines.extend(
        f"- {row['gate']}: `{'PASS' if row['passed'] else 'FAIL'}` "
        f"(actual={row['actual']}, threshold={row['threshold']})"
        for row in result.rows["acceptance"]
    )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            str(result.summaries["interpretation"]),
            "",
            "This is retrospective research on a previously inspected sample. "
            "It does not establish a validated 25% CAGR strategy.",
        ]
    )
    if result.blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- {blocker}" for blocker in result.blockers)
    return "\n".join(lines) + "\n"


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    materialized = [_normalize(dict(row)) for row in rows]
    headers = _headers(materialized)
    stream = StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=headers,
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(materialized)
    return _write_text(path, stream.getvalue())


def _headers(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    if not rows:
        return ["empty"]
    headers = sorted({str(key) for row in rows for key in row})
    return headers


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    return _write_text(
        path,
        json.dumps(_normalize(dict(payload)), indent=2, sort_keys=True) + "\n",
    )


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)
    return path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StructuralStopRiskScalingError("DSI012_CERTIFICATE_UNREADABLE") from exc
    if not isinstance(payload, dict):
        raise StructuralStopRiskScalingError("DSI012_CERTIFICATE_INVALID")
    return payload


def _canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    normalized = dict(payload)
    normalized.pop("report_sha256", None)
    encoded = json.dumps(
        _normalize(normalized),
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _percent(value: object) -> str:
    number = _numeric(value)
    return "UNKNOWN" if number is None else f"{number * 100:.2f}%"


def _number(value: object) -> str:
    number = _numeric(value)
    return "UNKNOWN" if number is None else f"{number:.2f}"


def _currency(value: object) -> str:
    number = _numeric(value)
    return "UNKNOWN" if number is None else f"{number:,.2f}"


def _numeric(value: object) -> float | None:
    if not isinstance(value, (str, int, float)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


__all__ = [
    "DSI012_ARTIFACTS",
    "DSI012_CERTIFICATE",
    "DSI012_REPORT",
    "export_structural_stop_risk_scaling",
    "validate_structural_stop_risk_scaling_certificate",
]
