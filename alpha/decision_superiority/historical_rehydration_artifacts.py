"""Deterministic export and tamper verification for DSI-004."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Final

from alpha.decision_superiority.historical_rehydration import governance_flags
from alpha.decision_superiority.historical_rehydration_models import (
    DSI004_CONTRACT_VERSION,
    DSI004_RESEARCH_SCOPE,
    HistoricalRehydrationError,
    HistoricalRehydrationResult,
)

DSI004_CERTIFICATE = "dsi004_rehydration_certificate.json"
DSI004_REPORT = "dsi004_executive_report.md"
DSI004_ARTIFACTS: Final[dict[str, str]] = {
    "arm_comparison": "dsi004_raw_adjusted_comparison.csv",
    "candidate_inputs": "dsi004_candidate_input_sufficiency.csv",
    "complete_stack": "dsi004_complete_stack_baseline.csv",
    "complete_stack_stages": "dsi004_complete_stack_stage_ledger.csv",
    "dependence": "dsi004_dependence_and_overlap.csv",
    "downstream_parity": "dsi004_downstream_parity_ledger.csv",
    "downstream_transitions": "dsi004_downstream_shadow_transitions.csv",
    "exact_inventory": "dsi004_exact_serialised_object_inventory.csv",
    "exact_rehydration": "dsi004_exact_object_rehydration_ledger.csv",
    "exclusions": "dsi004_population_exclusion_ledger.csv",
    "fingerprint_parity": "dsi004_fingerprint_parity_ledger.csv",
    "gate_value": "dsi004_gate_economic_value.csv",
    "minimal_sets": "dsi004_minimal_remediation_sets.csv",
    "outcome_comparability": "dsi004_outcome_comparability_ledger.csv",
    "population": "dsi004_rehydrated_recommendation_population.csv",
    "probes": "dsi004_non_vacuity_probe_ledger.csv",
    "recommendation_contract": "dsi004_recommendation_object_contract.csv",
    "recommendation_parity": "dsi004_reconstruction_parity_ledger.csv",
    "reconciliation": "dsi004_population_reconciliation.csv",
    "reconstruction": "dsi004_canonical_reconstruction_ledger.csv",
    "reconstruction_inputs": "dsi004_reconstruction_input_manifest.csv",
    "remediation_search": "dsi004_remediation_search_ledger.csv",
    "required_inputs": "dsi004_required_input_inventory.csv",
    "schema_mapping": "dsi004_historical_schema_mapping.csv",
    "single_arms": "dsi004_single_gate_arms.csv",
    "source_contract": "dsi004_source_contract_snapshot.csv",
    "terminal_comparison": "dsi004_dsi003_terminal_comparison.csv",
    "uncertainty": "dsi004_uncertainty_and_robustness.csv",
}


def export_historical_rehydration(
    result: HistoricalRehydrationResult,
    output: Path,
) -> tuple[Path, ...]:
    """Write the complete deterministic DSI-004 bundle."""

    output.mkdir(parents=True, exist_ok=True)
    support: list[Path] = []
    for key, name in sorted(DSI004_ARTIFACTS.items()):
        support.append(_write_csv(output / name, result.rows[key]))
    report = _write_text(output / DSI004_REPORT, _executive_report(result))
    support.append(report)
    manifest = {path.name: _sha256(path) for path in support}
    payload: dict[str, object] = {
        "contract_version": DSI004_CONTRACT_VERSION,
        "research_scope": DSI004_RESEARCH_SCOPE,
        "source_commit": result.source_commit,
        "readiness_by_slice": dict(result.readiness),
        "readiness_decision": result.readiness["K"],
        "blockers": list(result.blockers),
        "recommendation_contract_summary": _subset(
            result,
            "contract_field_count",
            "nested_field_count",
            "fingerprint_field_count",
            "unresolved_contract_field_count",
        ),
        "input_sufficiency_summary": _subset(
            result,
            "dsi003_economic_candidate_count",
            "input_complete_candidate_count",
            "missing_input_candidate_count",
            "ambiguous_input_candidate_count",
            "point_in_time_exclusion_count",
        ),
        "exact_object_summary": _subset(
            result,
            "exact_frozen_object_count",
            "exact_serialised_object_count",
        ),
        "reconstruction_summary": _subset(
            result,
            "reconstruction_attempt_count",
            "reconstruction_success_count",
            "deterministic_reconstruction_count",
            "parity_proven_reconstruction_count",
            "nondeterministic_reconstruction_count",
        ),
        "parity_summary": _subset(
            result,
            "recommendation_parity_count",
            "fingerprint_parity_count",
            "downstream_parity_count",
        ),
        "admitted_population_summary": _subset(
            result,
            "candidate_arm_count",
            "admitted_candidate_arm_count",
            "admitted_economic_candidate_count",
            "excluded_object_count",
            "admitted_security_count",
            "admitted_unique_date_count",
        ),
        "complete_stack_summary": _subset(
            result,
            "batch_candidate_count",
            "approval_count",
            "allocation_count",
        ),
        "batch_gate_isolation_summary": _subset(
            result,
            "single_gate_arm_count",
            "remediation_subset_count",
            "shadow_approval_count",
        ),
        "outcome_summary": _subset(
            result,
            "comparable_outcome_count",
            "unique_comparable_outcome_count",
            "trade_count",
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
    certificate = output / DSI004_CERTIFICATE
    _write_json(certificate, payload)
    return (certificate, *sorted(support, key=lambda path: path.name))


def validate_historical_rehydration_certificate(
    certificate: Path,
    *,
    require_ready: bool = False,
    project_root: Path = Path("."),
) -> dict[str, object]:
    """Fail closed on certificate, source, governance, or artifact tampering."""

    payload = _read_json(certificate)
    if payload.get("contract_version") != DSI004_CONTRACT_VERSION:
        raise HistoricalRehydrationError("UNSUPPORTED_DSI004_CONTRACT")
    if payload.get("research_scope") != DSI004_RESEARCH_SCOPE:
        raise HistoricalRehydrationError("DSI004_RESEARCH_SCOPE_MISMATCH")
    if payload.get("governance_flags") != governance_flags():
        raise HistoricalRehydrationError("DSI004_GOVERNANCE_FLAGS_INVALID")
    if payload.get("report_sha256") != _report_sha256(payload):
        raise HistoricalRehydrationError("DSI004_REPORT_HASH_MISMATCH")
    manifest = payload.get("support_artifact_manifest")
    expected = frozenset((*DSI004_ARTIFACTS.values(), DSI004_REPORT))
    if not isinstance(manifest, dict) or frozenset(manifest) != expected:
        raise HistoricalRehydrationError("DSI004_SUPPORT_MANIFEST_INVALID")
    root = certificate.resolve().parent
    for name, digest in sorted(manifest.items()):
        path = (root / str(name)).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise HistoricalRehydrationError("DSI004_SUPPORT_PATH_UNSAFE")
        if _sha256(path) != str(digest):
            raise HistoricalRehydrationError(f"DSI004_ARTIFACT_TAMPERED:{name}")
    report = root / DSI004_REPORT
    if payload.get("executive_report_sha256") != _sha256(report):
        raise HistoricalRehydrationError("DSI004_EXECUTIVE_REPORT_HASH_MISMATCH")
    _validate_implementation_sources(
        root / DSI004_ARTIFACTS["source_contract"],
        project_root=project_root.resolve(),
    )
    readiness = str(payload.get("readiness_decision", ""))
    if require_ready and not readiness.startswith("READY_"):
        raise HistoricalRehydrationError(f"DSI004_NOT_READY:{readiness}")
    return payload


def _validate_implementation_sources(path: Path, *, project_root: Path) -> None:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = tuple(csv.DictReader(handle))
    for row in rows:
        if row["source_type"] != "IMPLEMENTATION_SOURCE":
            continue
        source_id = row["source_id"]
        candidate = (project_root / source_id).resolve()
        if not candidate.is_relative_to(project_root) or not candidate.is_file():
            raise HistoricalRehydrationError("DSI004_IMPLEMENTATION_SOURCE_UNSAFE")
        if _sha256(candidate) != row["certificate_sha256"]:
            raise HistoricalRehydrationError(
                f"DSI004_IMPLEMENTATION_SOURCE_DRIFT:{source_id}"
            )


def _subset(
    result: HistoricalRehydrationResult,
    *names: str,
) -> dict[str, object]:
    return {name: result.summaries[name] for name in names}


def _executive_report(result: HistoricalRehydrationResult) -> str:
    summary = result.summaries
    lines = [
        "# DSI-004 Historical Recommendation Rehydration",
        "",
        "## Certification",
        "",
        f"- Final readiness: `{result.readiness['K']}`",
        "- Permitted scope: mechanical rehydration and descriptive research only",
        "- Production influence: `false`",
        "",
        "## Recommendation Contract",
        "",
        f"- Contract fields: {summary['contract_field_count']}",
        f"- Nested fields: {summary['nested_field_count']}",
        f"- Fingerprint fields: {summary['fingerprint_field_count']}",
        (
            "- Fields with high historical ambiguity risk: "
            f"{summary['unresolved_contract_field_count']}"
        ),
        "",
        "## Input Sufficiency",
        "",
        (
            "- DSI-003 economic candidates: "
            f"{summary['dsi003_economic_candidate_count']}"
        ),
        f"- Complete frozen inputs: {summary['input_complete_candidate_count']}",
        f"- Missing complete inputs: {summary['missing_input_candidate_count']}",
        "- Present-day defaults were not used to fill historical gaps.",
        "",
        "## Rehydration",
        "",
        f"- Exact full serialised objects: {summary['exact_serialised_object_count']}",
        (
            "- Parity-proven canonical reconstructions: "
            f"{summary['parity_proven_reconstruction_count']}"
        ),
        (
            "- Final admitted economic candidates: "
            f"{summary['admitted_economic_candidate_count']}"
        ),
        f"- Excluded objects: {summary['excluded_object_count']}",
        "",
        "BEL is admitted through deterministic point-in-time reconstruction, exact "
        "recommendation fingerprint parity, and exact complete-stack downstream "
        "parity. The remaining DSI-003 summaries are not recommendation objects.",
        "",
        "## Batch DSI-002",
        "",
        f"- Candidates processed: {summary['batch_candidate_count']}",
        f"- Single-gate arms: {summary['single_gate_arm_count']}",
        f"- Remediation subsets tested: {summary['remediation_subset_count']}",
        f"- Shadow approvals: {summary['shadow_approval_count']}",
        f"- Comparable completed outcomes: {summary['comparable_outcome_count']}",
        "",
        "No unchanged-policy shadow trade formed, so opportunity cost, avoided-loss "
        "benefit, and net gate value remain UNKNOWN.",
        "",
        "## Interpretation",
        "",
        "The package proves mechanical transferability for one independent candidate. "
        "It does not establish broad gate value, economic superiority, or a policy "
        "recommendation. Expanding the result requires additional immutable historical "
        "recommendation inputs or exact serialised objects.",
        "",
        "PRODUCTION_INFLUENCE=false",
        "",
    ]
    return "\n".join(lines)


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
) -> Path:
    normalized = [dict(row) for row in rows]
    fieldnames = sorted({key for row in normalized for key in row}) or ["state"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            lineterminator="\n",
        )
        writer.writeheader()
        for row in sorted(normalized, key=_row_sort_key):
            writer.writerow({key: _csv_value(row.get(key, "")) for key in fieldnames})
    return path


def _write_json(path: Path, payload: Mapping[str, object]) -> Path:
    path.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoricalRehydrationError("DSI004_CERTIFICATE_INVALID") from exc
    if not isinstance(payload, dict):
        raise HistoricalRehydrationError("DSI004_CERTIFICATE_OBJECT_REQUIRED")
    return payload


def _report_sha256(payload: Mapping[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("report_sha256", None)
    encoded = json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row_sort_key(row: Mapping[str, object]) -> str:
    return json.dumps(row, sort_keys=True, default=_json_default)


def _csv_value(value: object) -> object:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(value, sort_keys=True, default=_json_default)
    return value


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


__all__ = [
    "DSI004_ARTIFACTS",
    "DSI004_CERTIFICATE",
    "DSI004_REPORT",
    "export_historical_rehydration",
    "validate_historical_rehydration_certificate",
]
