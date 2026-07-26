"""Deterministic export and tamper verification for DSI-003."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Final

from alpha.decision_superiority.population_expansion import governance_flags
from alpha.decision_superiority.population_expansion_models import (
    DSI003_CONTRACT_VERSION,
    DSI003_RESEARCH_SCOPE,
    PopulationExpansionError,
    PopulationExpansionResult,
)

DSI003_CERTIFICATE = "dsi003_population_expansion_certificate.json"
DSI003_ARTIFACTS: Final[dict[str, str]] = {
    "arm_comparison": "dsi003_raw_adjusted_population_comparison.csv",
    "candidate_reconstruction": "dsi003_candidate_reconstruction_ledger.csv",
    "complete_stack_stages": "dsi003_complete_stack_stage_ledger.csv",
    "coverage_distribution": "dsi003_coverage_distribution.csv",
    "dsi002_transferability": "dsi003_dsi002_transferability_ledger.csv",
    "duplicate_conflicts": "dsi003_duplicate_and_conflict_ledger.csv",
    "economic_identity": "dsi003_economic_candidate_identity.csv",
    "effective_sample": "dsi003_effective_sample_assessment.csv",
    "external_validity": "dsi003_external_validity_metrics.csv",
    "funnel": "dsi003_population_funnel.csv",
    "gate_isolation_summary": "dsi003_gate_isolation_population_summary.csv",
    "independence": "dsi003_independence_diagnostics.csv",
    "loss_attribution": "dsi003_population_loss_attribution.csv",
    "outcome_readiness": "dsi003_outcome_readiness_ledger.csv",
    "outcome_summary": "dsi003_outcome_coverage_summary.csv",
    "probes": "dsi003_non_vacuity_probe_ledger.csv",
    "reconciliation": "dsi003_population_reconciliation.csv",
    "source_contract": "dsi003_source_contract_snapshot.csv",
    "source_inventory": "dsi003_population_source_inventory.csv",
}
DSI003_REPORT = "dsi003_executive_report.md"


def export_population_expansion(
    result: PopulationExpansionResult,
    output: Path,
) -> tuple[Path, ...]:
    """Write all 21 deterministic DSI-003 artifacts."""

    output.mkdir(parents=True, exist_ok=True)
    support: list[Path] = []
    for key, name in sorted(DSI003_ARTIFACTS.items()):
        support.append(_write_csv(output / name, result.rows[key]))
    report = _write_text(output / DSI003_REPORT, _executive_report(result))
    support.append(report)
    manifest = {path.name: _sha256(path) for path in support}
    source_contract = result.rows["source_contract"]
    payload: dict[str, object] = {
        "contract_version": DSI003_CONTRACT_VERSION,
        "research_scope": DSI003_RESEARCH_SCOPE,
        "source_commit": result.source_commit,
        "readiness_by_slice": dict(result.readiness),
        "readiness_decision": result.readiness["I"],
        "permitted_research_scope": (
            "DESCRIPTIVE_POPULATION_AND_OUTCOME_RESEARCH; "
            "EXACT_DSI002_TRANSFERABILITY_REMAINS SINGLE_CANDIDATE"
        ),
        "blockers": list(result.blockers),
        "source_certificates": {
            str(row["source_id"]): {
                "contract_version": row["contract_version"],
                "certificate_sha256": row["certificate_sha256"],
                "report_sha256": row["report_sha256"],
                "readiness": row["readiness"],
            }
            for row in source_contract
        },
        "source_inventory_summary": _summary_subset(
            result,
            "source_count",
            "source_row_count",
            "admissible_source_count",
            "incompatible_source_count",
            "missing_lineage_count",
        ),
        "candidate_reconstruction_summary": _summary_subset(
            result,
            "candidate_arm_count",
            "unique_economic_candidate_count",
            "security_count",
            "unique_date_count",
            "setup_count",
        ),
        "population_loss_summary": {
            "duplicate_rows_removed": result.summaries["duplicate_rows_removed"],
            "policy_rejections_are_population_loss": False,
        },
        "independence_summary": _summary_subset(
            result,
            "candidate_arm_count",
            "unique_economic_candidate_count",
            "top_security_share",
            "top_date_share",
            "effective_security_count",
            "effective_date_count",
        ),
        "deduplication_summary": _summary_subset(
            result,
            "duplicate_rows_removed",
            "conflicting_record_count",
        ),
        "external_validity_summary": _summary_subset(
            result,
            "coverage_grade",
            "security_count",
            "unique_date_count",
            "setup_count",
            "unique_regime_count",
            "sector_count",
        ),
        "outcome_readiness_summary": _summary_subset(
            result,
            "plan_count",
            "completed_outcome_count",
            "win_count",
            "loss_count",
            "flat_count",
            "pending_outcome_count",
        ),
        "dsi002_transferability_summary": _summary_subset(
            result,
            "exact_dsi002_candidate_count",
            "recorded_stage_candidate_count",
            "approval_count",
            "allocation_count",
        ),
        "sufficiency_grade": result.summaries["research_sufficiency_tier"],
        "implementation_defect_count": result.summaries["implementation_defect_count"],
        "point_in_time_leakage_count": result.summaries["leakage_count"],
        "unexplained_divergence_count": result.summaries[
            "unexplained_divergence_count"
        ],
        "executive_report_sha256": _sha256(report),
        "support_artifact_manifest": dict(sorted(manifest.items())),
        "governance_flags": governance_flags(),
    }
    payload["report_sha256"] = _report_sha256(payload)
    certificate = output / DSI003_CERTIFICATE
    _write_json(certificate, payload)
    return (certificate, *sorted(support, key=lambda path: path.name))


def validate_population_expansion_certificate(
    certificate: Path,
    *,
    require_ready: bool = False,
) -> dict[str, object]:
    """Fail closed on certificate, governance, report, or artifact tampering."""

    payload = _read_json(certificate)
    if payload.get("contract_version") != DSI003_CONTRACT_VERSION:
        raise PopulationExpansionError("UNSUPPORTED_DSI003_CONTRACT")
    if payload.get("research_scope") != DSI003_RESEARCH_SCOPE:
        raise PopulationExpansionError("DSI003_RESEARCH_SCOPE_MISMATCH")
    flags = payload.get("governance_flags")
    if flags != governance_flags():
        raise PopulationExpansionError("DSI003_GOVERNANCE_FLAGS_INVALID")
    if payload.get("report_sha256") != _report_sha256(payload):
        raise PopulationExpansionError("DSI003_REPORT_HASH_MISMATCH")
    manifest = payload.get("support_artifact_manifest")
    expected = frozenset((*DSI003_ARTIFACTS.values(), DSI003_REPORT))
    if not isinstance(manifest, dict) or frozenset(manifest) != expected:
        raise PopulationExpansionError("DSI003_SUPPORT_MANIFEST_INVALID")
    root = certificate.resolve().parent
    for name, digest in sorted(manifest.items()):
        path = (root / str(name)).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise PopulationExpansionError("DSI003_SUPPORT_PATH_UNSAFE")
        if _sha256(path) != str(digest):
            raise PopulationExpansionError(f"DSI003_ARTIFACT_TAMPERED:{name}")
    report = root / DSI003_REPORT
    if payload.get("executive_report_sha256") != _sha256(report):
        raise PopulationExpansionError("DSI003_EXECUTIVE_REPORT_HASH_MISMATCH")
    readiness = str(payload.get("readiness_decision", ""))
    if require_ready and not readiness.startswith("READY_"):
        raise PopulationExpansionError(f"DSI003_NOT_READY:{readiness}")
    return payload


def _summary_subset(
    result: PopulationExpansionResult,
    *names: str,
) -> dict[str, object]:
    return {name: result.summaries[name] for name in names}


def _executive_report(result: PopulationExpansionResult) -> str:
    summary = result.summaries
    lines = [
        "# DSI-003 Governed Population Expansion",
        "",
        "## Certification",
        "",
        f"- Final readiness: `{result.readiness['I']}`",
        f"- Research sufficiency: `{summary['research_sufficiency_tier']}`",
        f"- External validity: `{summary['coverage_grade']}`",
        "- Independent unit: `economic_candidate_id`",
        "- Production influence: `false`",
        "",
        "## Population",
        "",
        f"- Candidate-arm rows: {summary['candidate_arm_count']}",
        (f"- Unique economic candidates: {summary['unique_economic_candidate_count']}"),
        f"- Securities: {summary['security_count']}",
        f"- Recommendation dates: {summary['unique_date_count']}",
        f"- Known setups: {summary['setup_count']}",
        f"- Known regimes: {summary['unique_regime_count']}",
        f"- Known sectors: {summary['sector_count']}",
        "",
        "RAW and ADJUSTED records are paired analytical arms. They contribute one "
        "economic candidate, never two independent observations.",
        "",
        "## Outcomes",
        "",
        f"- Candidates with recorded plans: {summary['plan_count']}",
        f"- Completed comparable outcomes: {summary['completed_outcome_count']}",
        f"- Wins: {summary['win_count']}",
        f"- Losses: {summary['loss_count']}",
        f"- Flats: {summary['flat_count']}",
        f"- Pending end-of-data: {summary['pending_outcome_count']}",
        "",
        "Outcomes come only from the signed B7 outcome ledger. No rejected "
        "candidate is inferred to have traded.",
        "",
        "## DSI-002 Transferability",
        "",
        (
            "- Exact signed DSI-002 candidates: "
            f"{summary['exact_dsi002_candidate_count']}"
        ),
        (
            "- Broad recorded-stage candidates: "
            f"{summary['recorded_stage_candidate_count']}"
        ),
        "- Shadow approvals: 0",
        "- Shadow allocations: 0",
        "",
        "The complete-stack population is broad, but only BEL retains the frozen "
        "recommendation object required by the exact DSI-002 condition-pass seam. "
        "Historical B5/DSI-001 candidates support descriptive stage and outcome "
        "research, not a fabricated exact override replay.",
        "",
        "## Interpretation",
        "",
        "The one-candidate DSI-002 result was a narrow signed-capture boundary, "
        "not the full complete-stack population. B5 proves a materially larger "
        "recorded complete-stack population. External validity remains limited "
        "because governed regime and sector metadata are mostly unavailable, and "
        "DSI-002 exact evaluator transferability remains unproven beyond BEL.",
        "",
        "## Governance",
        "",
        "- No threshold or gate-order changes.",
        "- No synthetic candidates, approvals, trades, or outcomes.",
        "- No production, recommendation, portfolio, execution, or learning influence.",
        "- Structural probes are excluded from empirical counts.",
        "",
    ]
    return "\n".join(lines)


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
) -> Path:
    materialized = tuple(rows)
    if not materialized:
        raise PopulationExpansionError(f"DSI003_EMPTY_ARTIFACT:{path.name}")
    fieldnames = tuple(sorted({str(field) for row in materialized for field in row}))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            lineterminator="\n",
            extrasaction="raise",
        )
        writer.writeheader()
        for row in materialized:
            writer.writerow(
                {field: _scalar(row.get(field, "")) for field in fieldnames}
            )
    return path


def _scalar(value: object) -> object:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, Decimal):
        return format(value, "f")
    if value is None:
        return "UNKNOWN"
    return value


def _write_text(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    return path


def _write_json(path: Path, payload: Mapping[str, object]) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    return path


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PopulationExpansionError("DSI003_CERTIFICATE_JSON_INVALID") from exc
    if not isinstance(payload, dict):
        raise PopulationExpansionError("DSI003_CERTIFICATE_OBJECT_REQUIRED")
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


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "DSI003_ARTIFACTS",
    "DSI003_CERTIFICATE",
    "DSI003_REPORT",
    "export_population_expansion",
    "validate_population_expansion_certificate",
]
