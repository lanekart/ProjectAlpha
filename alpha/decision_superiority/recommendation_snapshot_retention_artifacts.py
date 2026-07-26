"""Deterministic export and validation for DSI-005 replay retention."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Final

from alpha.decision_superiority.recommendation_snapshot_retention import (
    governance_flags,
)
from alpha.decision_superiority.recommendation_snapshot_retention_models import (
    DSI005_CONTRACT_VERSION,
    DSI005_RESEARCH_SCOPE,
    ReplayRetentionError,
    ReplayRetentionResult,
)

DSI005_CERTIFICATE = "dsi005_replay_retention_certificate.json"
DSI005_REPORT = "dsi005_executive_report.md"
DSI005_JSONL = "dsi005_materialised_input_snapshots.jsonl"
DSI005_SNAPSHOT_PROBE = "dsi005_prospective_snapshot_probe.json"
DSI005_ARTIFACTS: Final[dict[str, str]] = {
    "algorithm_lineage": "dsi005_historical_algorithm_lineage.csv",
    "arm_comparison": "dsi005_raw_adjusted_comparison.csv",
    "capture": "dsi005_prospective_capture_ledger.csv",
    "deficit_signatures": "dsi005_candidate_deficit_signatures.csv",
    "deficits": "dsi005_input_deficit_ledger.csv",
    "derivability": "dsi005_field_derivability_ledger.csv",
    "growth": "dsi005_population_growth_summary.csv",
    "historical_provenance": "dsi005_materialised_field_provenance.csv",
    "materialisation_parity": "dsi005_materialisation_parity_ledger.csv",
    "pit_validation": "dsi005_point_in_time_validation.csv",
    "primitives": "dsi005_primitive_source_inventory.csv",
    "probes": "dsi005_non_vacuity_probe_ledger.csv",
    "prospective_contract": "dsi005_prospective_snapshot_contract.csv",
    "readiness": "dsi005_replay_readiness_assessment.csv",
    "reconciliation": "dsi005_population_reconciliation.csv",
    "renewed_complete_stack": "dsi005_renewed_complete_stack_results.csv",
    "renewed_dsi002": "dsi005_renewed_dsi002_transfer.csv",
    "renewed_exclusions": "dsi005_renewed_population_exclusions.csv",
    "renewed_population": "dsi005_renewed_recommendation_population.csv",
    "round_trip": "dsi005_snapshot_round_trip_ledger.csv",
    "snapshot_manifest": "dsi005_snapshot_manifest.csv",
    "source_contract": "dsi005_source_contract_snapshot.csv",
    "tamper": "dsi005_snapshot_tamper_probe_ledger.csv",
}


def export_replay_retention(
    result: ReplayRetentionResult,
    output: Path,
) -> tuple[Path, ...]:
    """Write the complete deterministic DSI-005 package."""

    output.mkdir(parents=True, exist_ok=True)
    support: list[Path] = []
    for key, name in sorted(DSI005_ARTIFACTS.items()):
        support.append(_write_csv(output / name, result.rows[key]))
    snapshots = _write_jsonl(output / DSI005_JSONL, result.jsonl_rows)
    support.append(snapshots)
    snapshot_probe = _write_json(
        output / DSI005_SNAPSHOT_PROBE,
        dict(result.prospective_snapshot),
    )
    support.append(snapshot_probe)
    report = _write_text(output / DSI005_REPORT, _executive_report(result))
    support.append(report)
    manifest = {path.name: _sha256(path) for path in support}
    payload: dict[str, object] = {
        "contract_version": DSI005_CONTRACT_VERSION,
        "research_scope": DSI005_RESEARCH_SCOPE,
        "source_commit": result.source_commit,
        "readiness_by_slice": dict(result.readiness),
        "readiness_decision": result.readiness["I"],
        "blockers": list(result.blockers),
        "input_deficit_summary": _subset(
            result,
            "dsi004_excluded_candidate_count",
            "missing_required_field_row_count",
            "deficit_signature_count",
            "fingerprint_critical_deficit_count",
            "semantic_critical_deficit_count",
        ),
        "derivability_summary": _subset(
            result,
            "retained_value_count",
            "exactly_derivable_value_count",
            "version_mapped_value_count",
            "ambiguous_value_count",
            "current_default_only_value_count",
            "future_only_value_count",
            "non_derivable_value_count",
        ),
        "historical_materialisation_summary": _subset(
            result,
            "candidates_assessed_count",
            "complete_historical_snapshot_count",
            "partial_historical_snapshot_count",
            "rejected_historical_snapshot_count",
            "newly_materialised_candidate_count",
        ),
        "parity_summary": _subset(
            result,
            "materialisation_method_count",
            "input_parity_count",
            "recommendation_parity_count",
            "fingerprint_parity_count",
            "complete_stack_parity_count",
            "point_in_time_failure_count",
        ),
        "renewed_admission_summary": _subset(
            result,
            "prior_admitted_candidate_count",
            "newly_admitted_candidate_count",
            "total_admitted_candidate_count",
            "renewed_complete_stack_approval_count",
            "renewed_shadow_approval_count",
            "newly_comparable_outcome_count",
        ),
        "prospective_capture_summary": _subset(
            result,
            "prospective_snapshot_contract_field_count",
            "prospective_required_field_coverage_percent",
            "prospective_fingerprint_coverage_percent",
            "prospective_stage_trace_coverage_percent",
            "prospective_plan_identity_coverage_percent",
            "prospective_capture_conflict_count",
            "prospective_secret_detection_passed",
            "default_snapshot_capture_enabled",
        ),
        "round_trip_summary": _subset(
            result,
            "round_trip_package_count",
            "round_trip_success_count",
            "tamper_probe_count",
            "tamper_detected_count",
        ),
        "implementation_defect_count": result.summaries["implementation_defect_count"],
        "point_in_time_leakage_count": result.summaries["point_in_time_leakage_count"],
        "unexplained_divergence_count": result.summaries[
            "unexplained_divergence_count"
        ],
        "executive_report_sha256": _sha256(report),
        "support_artifact_manifest": dict(sorted(manifest.items())),
        "governance_flags": governance_flags(),
    }
    payload["report_sha256"] = _report_sha256(payload)
    certificate = _write_json(output / DSI005_CERTIFICATE, payload)
    return (certificate, *sorted(support, key=lambda path: path.name))


def validate_replay_retention_certificate(
    certificate: Path,
    *,
    require_ready: bool = False,
    project_root: Path = Path("."),
) -> dict[str, object]:
    """Fail closed on certificate, artifact, source, or governance drift."""

    payload = _read_json(certificate)
    if payload.get("contract_version") != DSI005_CONTRACT_VERSION:
        raise ReplayRetentionError("UNSUPPORTED_DSI005_CONTRACT")
    if payload.get("research_scope") != DSI005_RESEARCH_SCOPE:
        raise ReplayRetentionError("DSI005_RESEARCH_SCOPE_MISMATCH")
    if payload.get("governance_flags") != governance_flags():
        raise ReplayRetentionError("DSI005_GOVERNANCE_FLAGS_INVALID")
    if payload.get("report_sha256") != _report_sha256(payload):
        raise ReplayRetentionError("DSI005_REPORT_HASH_MISMATCH")
    manifest = payload.get("support_artifact_manifest")
    expected = frozenset(
        (
            *DSI005_ARTIFACTS.values(),
            DSI005_JSONL,
            DSI005_REPORT,
            DSI005_SNAPSHOT_PROBE,
        )
    )
    if not isinstance(manifest, dict) or frozenset(manifest) != expected:
        raise ReplayRetentionError("DSI005_SUPPORT_MANIFEST_INVALID")
    root = certificate.resolve().parent
    for name, digest in sorted(manifest.items()):
        path = (root / str(name)).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ReplayRetentionError("DSI005_SUPPORT_PATH_UNSAFE")
        if _sha256(path) != str(digest):
            raise ReplayRetentionError(f"DSI005_ARTIFACT_TAMPERED:{name}")
    if payload.get("executive_report_sha256") != _sha256(root / DSI005_REPORT):
        raise ReplayRetentionError("DSI005_EXECUTIVE_REPORT_HASH_MISMATCH")
    _validate_sources(
        root / DSI005_ARTIFACTS["source_contract"],
        project_root.resolve(),
    )
    readiness = str(payload.get("readiness_decision") or "")
    if require_ready and not readiness.startswith("READY_"):
        raise ReplayRetentionError(f"DSI005_NOT_READY:{readiness}")
    return payload


def _validate_sources(path: Path, project_root: Path) -> None:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = tuple(csv.DictReader(handle))
    for row in rows:
        if row["source_type"] != "IMPLEMENTATION_SOURCE":
            continue
        source = (project_root / row["source_id"]).resolve()
        if not source.is_relative_to(project_root) or not source.is_file():
            raise ReplayRetentionError("DSI005_IMPLEMENTATION_SOURCE_UNSAFE")
        if _sha256(source) != row["source_sha256"]:
            raise ReplayRetentionError(
                f"DSI005_IMPLEMENTATION_SOURCE_DRIFT:{row['source_id']}"
            )


def _executive_report(result: ReplayRetentionResult) -> str:
    summary = result.summaries
    return "\n".join(
        (
            "# DSI-005 Recommendation Input Materialisation and Retention",
            "",
            "## Certification",
            "",
            f"- Final readiness: `{result.readiness['I']}`",
            "- Production influence: `false`",
            "- Snapshot capture enabled by default: `false`",
            "",
            "## Retrospective Boundary",
            "",
            (
                "- DSI-004 excluded candidates: "
                f"{summary['dsi004_excluded_candidate_count']}"
            ),
            (
                "- Missing required field rows: "
                f"{summary['missing_required_field_row_count']}"
            ),
            f"- Deficit signatures: {summary['deficit_signature_count']}",
            (
                "- Newly materialised candidates: "
                f"{summary['newly_materialised_candidate_count']}"
            ),
            (
                "- Total replayable historical candidates: "
                f"{summary['total_admitted_candidate_count']}"
            ),
            "",
            "No additional historical candidate was admitted. Candidate summaries "
            "do not prove the complete point-in-time input state, historical "
            "algorithm, policy, or serializer required by the 251-field contract.",
            "",
            "## Prospective Boundary",
            "",
            (
                "- Snapshot contract fields: "
                f"{summary['prospective_snapshot_contract_field_count']}"
            ),
            (
                "- Required-field coverage: "
                f"{summary['prospective_required_field_coverage_percent']}%"
            ),
            f"- Round-trip packages tested: {summary['round_trip_package_count']}",
            f"- Round-trip successes: {summary['round_trip_success_count']}",
            (
                "- Tamper probes detected: "
                f"{summary['tamper_detected_count']}/"
                f"{summary['tamper_probe_count']}"
            ),
            "",
            "The append-only recorder captures canonical inputs, recommendations, "
            "fingerprints, complete-stack state, plan identities, source hashes, "
            "and outcome-link identities only when explicitly enabled with a "
            "governed recorder.",
            "",
            "PRODUCTION_INFLUENCE=false",
            "",
        )
    )


def _subset(result: ReplayRetentionResult, *names: str) -> dict[str, object]:
    return {name: result.summaries[name] for name in names}


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
) -> Path:
    if not rows:
        raise ReplayRetentionError(f"DSI005_EMPTY_ARTIFACT:{path.name}")
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
    if not rows:
        raise ReplayRetentionError("DSI005_EMPTY_SNAPSHOT_JSONL")
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
        raise ReplayRetentionError("DSI005_CERTIFICATE_READ_FAILED") from exc
    if not isinstance(payload, dict):
        raise ReplayRetentionError("DSI005_CERTIFICATE_OBJECT_REQUIRED")
    return payload


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
    "DSI005_ARTIFACTS",
    "DSI005_CERTIFICATE",
    "DSI005_JSONL",
    "DSI005_REPORT",
    "DSI005_SNAPSHOT_PROBE",
    "export_replay_retention",
    "validate_replay_retention_certificate",
]
