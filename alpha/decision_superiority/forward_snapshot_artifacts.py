"""Deterministic artifact export and validation for DSI-006."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Final

from alpha.decision_superiority.forward_snapshot_accrual import governance_flags
from alpha.decision_superiority.forward_snapshot_models import (
    DSI006_CONTRACT_VERSION,
    DSI006_RESEARCH_SCOPE,
    ForwardSnapshotError,
    ForwardSnapshotResult,
)

DSI006_CERTIFICATE = "dsi006_forward_capture_certificate.json"
DSI006_REPORT = "dsi006_executive_report.md"
DSI006_EVENTS = "dsi006_outcome_event_ledger.jsonl"
DSI006_ARTIFACTS: Final[dict[str, str]] = {
    "activation": "dsi006_capture_activation_contract.csv",
    "capture_sessions": "dsi006_capture_session_ledger.csv",
    "concentration": "dsi006_independence_and_concentration.csv",
    "dsi002_transfer": "dsi006_dsi002_transfer_ledger.csv",
    "duplicates": "dsi006_duplicate_and_conflict_ledger.csv",
    "identities": "dsi006_economic_candidate_identity.csv",
    "manifests": "dsi006_snapshot_manifest_ledger.csv",
    "non_vacuity": "dsi006_non_vacuity_probe_ledger.csv",
    "operational": "dsi006_operational_recovery_probes.csv",
    "outcome_reconciliation": "dsi006_outcome_event_reconciliation.csv",
    "package_index": "dsi006_snapshot_package_index.csv",
    "pairing": "dsi006_raw_adjusted_pairing.csv",
    "parity": "dsi006_round_trip_parity.csv",
    "plans": "dsi006_plan_identity_ledger.csv",
    "population": "dsi006_population_accrual.csv",
    "readiness": "dsi006_research_readiness.csv",
    "reconciliation": "dsi006_population_reconciliation.csv",
    "replay": "dsi006_snapshot_replay_ledger.csv",
    "retention": "dsi006_retention_contract.csv",
    "safety": "dsi006_secret_and_path_safety.csv",
    "source_contract": "dsi006_source_contract_snapshot.csv",
    "write_integrity": "dsi006_capture_write_integrity.csv",
}


def export_forward_snapshot_accrual(
    result: ForwardSnapshotResult,
    output: Path,
) -> tuple[Path, ...]:
    """Write the complete deterministic DSI-006 evidence package."""

    output.mkdir(parents=True, exist_ok=True)
    support: list[Path] = []
    for key, name in sorted(DSI006_ARTIFACTS.items()):
        support.append(_write_csv(output / name, result.rows[key]))
    events = _write_jsonl(output / DSI006_EVENTS, result.jsonl_rows)
    support.append(events)
    report = _write_text(output / DSI006_REPORT, _executive_report(result))
    support.append(report)
    manifest = {path.name: _sha256(path) for path in support}
    summary = result.summaries
    payload: dict[str, object] = {
        "contract_version": DSI006_CONTRACT_VERSION,
        "research_scope": DSI006_RESEARCH_SCOPE,
        "source_commit": result.source_commit,
        "dsi005_certificate_hashes": _dsi005_hashes(result),
        "readiness_by_slice": dict(result.readiness),
        "readiness_decision": result.readiness["I"],
        "blockers": list(result.blockers),
        "activation_summary": _subset(
            summary,
            "default_snapshot_capture_enabled",
            "production_snapshot_writes_enabled",
        ),
        "capture_session_summary": _subset(
            summary,
            "capture_session_count",
            "zero_recommendation_session_count",
            "unavailable_session_count",
            "failed_session_count",
            "recommendation_count",
            "verdict_counts",
        ),
        "snapshot_package_summary": _subset(
            summary,
            "package_count",
            "candidate_arm_package_count",
            "economic_candidate_count",
            "raw_adjusted_pair_count",
            "package_verification_rate_percent",
        ),
        "append_only_repository_summary": _subset(
            summary,
            "index_reconciled",
            "capture_conflict_count",
            "event_reused_count",
        ),
        "outcome_event_summary": _subset(
            summary,
            "event_count",
            "entry_pending_count",
            "entry_count",
            "not_entered_count",
            "open_position_count",
            "pending_outcome_count",
            "completed_outcome_count",
            "comparable_outcome_count",
            "conflicting_outcome_count",
        ),
        "replay_summary": _subset(
            summary,
            "replay_package_count",
            "dsi002_replayable_candidate_count",
            "shadow_approval_count",
            "shadow_trade_count",
        ),
        "population_readiness_summary": _subset(
            summary,
            "economic_candidate_count",
            "completed_outcome_count",
            "top_security_share",
            "top_date_share",
            "top_month_share",
            "unique_setup_count",
            "known_setup_count",
            "unique_regime_count",
            "known_regime_count",
            "unique_sector_count",
            "known_sector_count",
            "setup_concentration",
            "regime_concentration",
            "sector_concentration",
        ),
        "implementation_defect_count": summary["implementation_defect_count"],
        "point_in_time_leakage_count": summary["point_in_time_leakage_count"],
        "unexplained_divergence_count": summary["unexplained_divergence_count"],
        "default_runtime_invariance": True,
        "executive_report_sha256": _sha256(report),
        "support_artifact_manifest": dict(sorted(manifest.items())),
        "governance_flags": governance_flags(),
    }
    payload["report_sha256"] = _report_sha256(payload)
    certificate = _write_json(output / DSI006_CERTIFICATE, payload)
    return (certificate, *sorted(support, key=lambda path: path.name))


def validate_forward_snapshot_certificate(
    certificate: Path,
    *,
    require_ready: bool = False,
    project_root: Path = Path("."),
) -> dict[str, object]:
    """Validate certificate, artifacts, source files, and governance flags."""

    payload = _read_json(certificate)
    if payload.get("contract_version") != DSI006_CONTRACT_VERSION:
        raise ForwardSnapshotError("UNSUPPORTED_DSI006_CONTRACT")
    if payload.get("research_scope") != DSI006_RESEARCH_SCOPE:
        raise ForwardSnapshotError("DSI006_RESEARCH_SCOPE_MISMATCH")
    if payload.get("governance_flags") != governance_flags():
        raise ForwardSnapshotError("DSI006_GOVERNANCE_FLAGS_INVALID")
    if payload.get("report_sha256") != _report_sha256(payload):
        raise ForwardSnapshotError("DSI006_REPORT_HASH_MISMATCH")
    manifest = payload.get("support_artifact_manifest")
    expected = frozenset((*DSI006_ARTIFACTS.values(), DSI006_EVENTS, DSI006_REPORT))
    if not isinstance(manifest, dict) or frozenset(manifest) != expected:
        raise ForwardSnapshotError("DSI006_SUPPORT_MANIFEST_INVALID")
    root = certificate.resolve().parent
    for name, digest in sorted(manifest.items()):
        path = (root / str(name)).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ForwardSnapshotError("DSI006_SUPPORT_PATH_UNSAFE")
        if _sha256(path) != str(digest):
            raise ForwardSnapshotError(f"DSI006_ARTIFACT_TAMPERED:{name}")
    if payload.get("executive_report_sha256") != _sha256(root / DSI006_REPORT):
        raise ForwardSnapshotError("DSI006_EXECUTIVE_REPORT_HASH_MISMATCH")
    _validate_sources(
        root / DSI006_ARTIFACTS["source_contract"],
        project_root.resolve(),
    )
    readiness = str(payload.get("readiness_decision") or "")
    if require_ready and not readiness.startswith("READY_"):
        raise ForwardSnapshotError(f"DSI006_NOT_READY:{readiness}")
    return payload


def _dsi005_hashes(result: ForwardSnapshotResult) -> dict[str, str]:
    rows = result.rows["activation"]
    return {
        "report_sha256": str(result.summaries["dsi005_executive_report_sha256"]),
        "certificate_file_sha256": str(
            result.summaries["dsi005_certificate_file_sha256"]
        ),
        "activation_contract_sha256": hashlib.sha256(
            _canonical_json(rows).encode("utf-8")
        ).hexdigest(),
    }


def _executive_report(result: ForwardSnapshotResult) -> str:
    summary = result.summaries
    return "\n".join(
        (
            "# DSI-006 Forward Snapshot Accrual",
            "",
            "## Certification",
            "",
            f"- Final readiness: `{result.readiness['I']}`",
            "- Production influence: `false`",
            "- Default capture enabled: `false`",
            "- Production snapshot writes enabled: `false`",
            "",
            "## Forward Population",
            "",
            f"- Captured sessions: {summary['capture_session_count']}",
            f"- Recommendation arms: {summary['candidate_arm_package_count']}",
            f"- Independent candidates: {summary['economic_candidate_count']}",
            f"- Unique setups: {summary['unique_setup_count']}",
            (
                "- Unique regimes: "
                f"{summary['unique_regime_count']} "
                f"({summary['known_regime_count']} known)"
            ),
            (
                "- Unique sectors: "
                f"{summary['unique_sector_count']} "
                f"({summary['known_sector_count']} known)"
            ),
            f"- Immutable packages: {summary['package_count']}",
            f"- Recorded plans: {summary['plan_count']}",
            "",
            "## Outcome Maturity",
            "",
            f"- Entry events: {summary['entry_count']}",
            f"- Pending entries: {summary['entry_pending_count']}",
            f"- Not entered: {summary['not_entered_count']}",
            f"- Open positions: {summary['open_position_count']}",
            f"- Pending outcomes: {summary['pending_outcome_count']}",
            f"- Completed outcomes: {summary['completed_outcome_count']}",
            f"- Comparable outcomes: {summary['comparable_outcome_count']}",
            (
                "- Permitted conclusion: forward population accrual and mechanical "
                "replay only; profitability is not established."
            ),
            "",
            "## Replay Integrity",
            "",
            f"- Packages replayed with full parity: {summary['replay_package_count']}",
            (
                "- Package verification rate: "
                f"{summary['package_verification_rate_percent']}%"
            ),
            f"- Point-in-time leakage: {summary['point_in_time_leakage_count']}",
            f"- Unexplained divergence: {summary['unexplained_divergence_count']}",
            "",
            "PRODUCTION_INFLUENCE=false",
            "",
        )
    )


def _subset(summary: Mapping[str, object], *names: str) -> dict[str, object]:
    return {name: summary[name] for name in names}


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
) -> Path:
    if not rows:
        raise ForwardSnapshotError(f"DSI006_EMPTY_ARTIFACT:{path.name}")
    fieldnames = tuple(sorted({key for row in rows for key in row}))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})
    return path


def _write_jsonl(
    path: Path,
    rows: Sequence[Mapping[str, object]],
) -> Path:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(_canonical_json(row))
            handle.write("\n")
    return path


def _write_json(path: Path, payload: Mapping[str, object]) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_text(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    return path


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ForwardSnapshotError("DSI006_CERTIFICATE_READ_FAILED") from exc
    if not isinstance(payload, dict):
        raise ForwardSnapshotError("DSI006_CERTIFICATE_OBJECT_REQUIRED")
    return payload


def _validate_sources(path: Path, project_root: Path) -> None:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = tuple(csv.DictReader(handle))
    for row in rows:
        if row["source_type"] != "IMPLEMENTATION_SOURCE":
            continue
        source = (project_root / row["source_id"]).resolve()
        if not source.is_relative_to(project_root) or not source.is_file():
            raise ForwardSnapshotError("DSI006_IMPLEMENTATION_SOURCE_UNSAFE")
        if _sha256(source) != row["source_sha256"]:
            raise ForwardSnapshotError(
                f"DSI006_IMPLEMENTATION_SOURCE_DRIFT:{row['source_id']}"
            )


def _report_sha256(payload: Mapping[str, object]) -> str:
    body = dict(payload)
    body.pop("report_sha256", None)
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_json_default,
    )


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (dict, list, tuple)):
        return _canonical_json(value)
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "DSI006_ARTIFACTS",
    "DSI006_CERTIFICATE",
    "DSI006_EVENTS",
    "DSI006_REPORT",
    "export_forward_snapshot_accrual",
    "validate_forward_snapshot_certificate",
]
