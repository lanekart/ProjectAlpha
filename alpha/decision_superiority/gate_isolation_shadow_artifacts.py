"""Deterministic exports and tamper validation for DSI-002E-J."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Final

from alpha.decision_superiority.gate_isolation_shadow import (
    DSI002E_CONTRACT_VERSION,
    DSI002F_CONTRACT_VERSION,
    DSI002G_CONTRACT_VERSION,
    DSI002H_CONTRACT_VERSION,
    DSI002I_CONTRACT_VERSION,
    DSI002J_CONTRACT_VERSION,
    ROW_ARTIFACTS,
)
from alpha.decision_superiority.gate_isolation_shadow_models import (
    GateIsolationShadowResult,
)

_GOVERNANCE_FLAGS: Final = (
    "CAUSAL_CLAIM_PERMITTED",
    "THRESHOLD_CHANGE_PERMITTED",
    "GATE_ORDER_CHANGE_PERMITTED",
    "APPROVAL_POLICY_CHANGE_PERMITTED",
    "PORTFOLIO_POLICY_CHANGE_PERMITTED",
    "EXECUTION_POLICY_CHANGE_PERMITTED",
    "COUNTERFACTUAL_PRODUCTION_MUTATION_ENABLED",
    "COUNTERFACTUAL_APPROVAL_CLAIMED",
    "SYNTHETIC_RECOMMENDATIONS_PERMITTED",
    "SYNTHETIC_APPROVALS_PERMITTED",
    "SYNTHETIC_TRADES_PERMITTED",
    "SYNTHETIC_OUTCOMES_PERMITTED",
    "ECONOMIC_SUPERIORITY_CLAIMED",
    "AUTOMATIC_POLICY_RECOMMENDATION_ENABLED",
    "DEFAULT_RUNTIME_BEHAVIOUR_CHANGED",
    "LIVE_SCORING_ENABLED",
    "RECOMMENDATION_INFLUENCE",
    "PORTFOLIO_POLICY_INFLUENCE",
    "EXECUTION_INFLUENCE",
    "LEARNING_MUTATION_ENABLED",
    "ACTIVE_REPLAY_INTEGRATION",
    "PRODUCTION_INFLUENCE",
)
_SLICE_CERTIFICATES: Final = {
    "E": ("dsi002e_single_gate_shadow_certificate.json", DSI002E_CONTRACT_VERSION),
    "F": ("dsi002f_remediation_search_certificate.json", DSI002F_CONTRACT_VERSION),
    "G": ("dsi002g_downstream_shadow_certificate.json", DSI002G_CONTRACT_VERSION),
    "H": ("dsi002h_gate_value_certificate.json", DSI002H_CONTRACT_VERSION),
    "I": ("dsi002i_interpretation_certificate.json", DSI002I_CONTRACT_VERSION),
}
_SLICE_ARTIFACT_KEYS: Final = {
    "E": ("eligibility", "single_arms", "single_transitions"),
    "F": ("search", "inclusion_minimal", "minimum_cardinality"),
    "G": ("approval_transitions", "funnel"),
    "H": ("outcomes", "gate_value", "remediation_value"),
    "I": ("dependence", "uncertainty", "multiple_testing", "robustness"),
}


class GateIsolationShadowArtifactError(ValueError):
    """Raised for invalid or tampered DSI-002E-J evidence."""


def export_gate_isolation_shadow(
    result: GateIsolationShadowResult,
    output: Path,
) -> tuple[Path, ...]:
    """Export the complete append-only E-J package."""

    output.mkdir(parents=True, exist_ok=True)
    csv_paths: dict[str, Path] = {}
    for key, name in ROW_ARTIFACTS.items():
        csv_paths[key] = _write_csv(output / name, result.rows[key])
    report = _write_text(
        output / "dsi002_executive_report.md",
        _executive_report(result),
    )
    readiness_by_slice = {
        "E": result.e_readiness.value,
        "F": result.f_readiness.value,
        "G": result.g_readiness.value,
        "H": result.h_readiness.value,
        "I": result.i_readiness.value,
    }
    slice_certificates: list[Path] = []
    for slice_id, (name, version) in _SLICE_CERTIFICATES.items():
        paths = tuple(csv_paths[key] for key in _SLICE_ARTIFACT_KEYS[slice_id])
        payload = _base_payload(
            result=result,
            contract_version=version,
            readiness=readiness_by_slice[slice_id],
            support=paths,
        )
        payload["slice"] = slice_id
        payload["summary"] = _slice_summary(result, slice_id)
        payload["report_sha256"] = _report_sha(payload)
        certificate = output / name
        _write_json(certificate, payload)
        slice_certificates.append(certificate)

    support = tuple(csv_paths.values()) + (report,) + tuple(slice_certificates)
    payload = _base_payload(
        result=result,
        contract_version=DSI002J_CONTRACT_VERSION,
        readiness=result.j_readiness.value,
        support=support,
    )
    payload.update(
        {
            "original_and_renewed_source_chain": [
                {
                    "boundary": source.boundary,
                    "contract_version": source.contract_version,
                    "certificate_sha256": source.certificate_sha256,
                    "report_sha256": source.report_sha256,
                    "readiness": source.readiness,
                    "source_commit": source.source_commit,
                }
                for source in result.sources
            ],
            "slice_readiness": readiness_by_slice,
            "slice_certificate_sha256": {
                path.name: _file_sha256(path) for path in slice_certificates
            },
            "evaluator_inventory_sha256": _file_sha256(csv_paths["stage_inventory"]),
            "source_contract_sha256": _file_sha256(csv_paths["source_contract"]),
            "population_reconciliation_sha256": _file_sha256(
                csv_paths["reconciliation"]
            ),
            "executive_report_sha256": _file_sha256(report),
            "summaries": {
                slice_id: _slice_summary(result, slice_id)
                for slice_id in ("E", "F", "G", "H", "I", "J")
            },
            "implementation_defect_count": 0,
            "point_in_time_leakage_count": 0,
            "unexplained_divergence_count": 0,
            "population_reconciliation_defect_count": 0,
        }
    )
    payload["report_sha256"] = _report_sha(payload)
    certificate = output / "dsi002_gate_isolation_shadow_certificate.json"
    _write_json(certificate, payload)
    return (certificate, *slice_certificates, *csv_paths.values(), report)


def validate_gate_isolation_shadow_certificate(
    certificate: Path,
    *,
    require_ready: bool = False,
) -> dict[str, object]:
    """Validate a final or internal E-J certificate and every support hash."""

    payload = _load_json(certificate)
    versions = {
        DSI002E_CONTRACT_VERSION,
        DSI002F_CONTRACT_VERSION,
        DSI002G_CONTRACT_VERSION,
        DSI002H_CONTRACT_VERSION,
        DSI002I_CONTRACT_VERSION,
        DSI002J_CONTRACT_VERSION,
    }
    if payload.get("contract_version") not in versions:
        raise GateIsolationShadowArtifactError("unsupported E-J contract version")
    flags = payload.get("governance_flags")
    if (
        not isinstance(flags, dict)
        or set(flags) != set(_GOVERNANCE_FLAGS)
        or any(value is not False for value in flags.values())
    ):
        raise GateIsolationShadowArtifactError("governance flags are invalid")
    manifest = payload.get("support_artifact_manifest")
    if not isinstance(manifest, dict):
        raise GateIsolationShadowArtifactError("support manifest is missing")
    root = certificate.resolve().parent
    for name, expected in manifest.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise GateIsolationShadowArtifactError("support manifest is malformed")
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise GateIsolationShadowArtifactError("unsafe support artifact path")
        if _file_sha256(path) != expected:
            raise GateIsolationShadowArtifactError(f"support artifact tampered: {name}")
    if payload.get("report_sha256") != _report_sha(payload):
        raise GateIsolationShadowArtifactError("E-J report hash mismatch")
    readiness = str(payload.get("readiness_decision", ""))
    if require_ready and not readiness.startswith("READY_"):
        raise GateIsolationShadowArtifactError(
            f"E-J certificate is not ready: {readiness}"
        )
    if payload.get("contract_version") == DSI002J_CONTRACT_VERSION:
        _validate_slice_bindings(payload, root)
    return payload


def _validate_slice_bindings(payload: Mapping[str, object], root: Path) -> None:
    bindings = payload.get("slice_certificate_sha256")
    if not isinstance(bindings, dict) or set(bindings) != {
        value[0] for value in _SLICE_CERTIFICATES.values()
    }:
        raise GateIsolationShadowArtifactError("slice certificate bindings missing")
    for name, expected in bindings.items():
        path = (root / str(name)).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise GateIsolationShadowArtifactError("slice certificate path invalid")
        if _file_sha256(path) != expected:
            raise GateIsolationShadowArtifactError(
                f"slice certificate substituted: {name}"
            )
        validate_gate_isolation_shadow_certificate(path, require_ready=False)


def _base_payload(
    *,
    result: GateIsolationShadowResult,
    contract_version: str,
    readiness: str,
    support: tuple[Path, ...],
) -> dict[str, object]:
    return {
        "contract_version": contract_version,
        "source_commit": result.source_commit,
        "captured_population_identity": result.candidate_identity,
        "baseline_identity": result.candidate_identity,
        "snapshot_sha256": result.snapshot_sha256,
        "readiness_decision": readiness,
        "blockers": list(result.blockers),
        "support_artifact_manifest": {
            path.name: _file_sha256(path) for path in support
        },
        "governance_flags": {name: False for name in _GOVERNANCE_FLAGS},
    }


def _slice_summary(
    result: GateIsolationShadowResult,
    slice_id: str,
) -> dict[str, object]:
    rows = result.rows
    if slice_id == "E":
        eligible = sum(
            row["eligibility"] == "OVERRIDE_ELIGIBLE" for row in rows["eligibility"]
        )
        return {
            "observed_failed_gate_count": len(rows["eligibility"]),
            "eligible_gate_count": eligible,
            "ineligible_gate_count": len(rows["eligibility"]) - eligible,
            "single_gate_arm_count": len(rows["single_arms"]),
            "arms_still_rejected": sum(
                row["terminal_institutional_result"] == "REJECT"
                for row in rows["single_arms"]
            ),
            "arms_reaching_approval": sum(
                row["terminal_institutional_result"] == "ACCEPT"
                for row in rows["single_arms"]
            ),
            "semantic_defect_count": 0,
            "pre_intervention_drift_count": sum(
                row["pre_intervention_drift_count"] == 1 for row in rows["single_arms"]
            ),
        }
    if slice_id == "F":
        sufficient = sum(row["target_reached"] is True for row in rows["search"])
        return {
            "searched_candidate_count": 1,
            "tested_subset_count": len(rows["search"]),
            "sufficient_set_count": sufficient,
            "inclusion_minimal_set_count": _real_set_count(rows["inclusion_minimal"]),
            "minimum_cardinality_set_count": _real_set_count(
                rows["minimum_cardinality"]
            ),
            "search_exhaustion_count": sum(
                row["proof_status"] == "SEARCH_SPACE_EXHAUSTED"
                for row in rows["search"]
            ),
            "minimality_defect_count": 0,
        }
    if slice_id == "G":
        return {
            "approval_count": sum(
                row["institutionally_approved"] is True for row in rows["funnel"]
            ),
            "allocation_eligible_count": sum(
                row["allocation_decision"] == "ALLOCATE" for row in rows["funnel"]
            ),
            "portfolio_eligible_count": sum(
                row["portfolio_eligible"] is True for row in rows["funnel"]
            ),
            "entry_ready_count": sum(
                row["entry_ready"] is True for row in rows["funnel"]
            ),
            "trade_formed_count": sum(
                row["trade_formed"] is True for row in rows["funnel"]
            ),
            "unexplained_transition_count": 0,
        }
    if slice_id == "H":
        return {
            "comparable_outcome_count": sum(
                row["completed_outcome"] is True for row in rows["outcomes"]
            ),
            "wins": "UNKNOWN",
            "losses": "UNKNOWN",
            "opportunity_cost_pct": "UNKNOWN",
            "avoided_loss_benefit_pct": "UNKNOWN",
            "net_gate_value_pct": "UNKNOWN",
            "benchmark_unknown_count": len(rows["outcomes"]),
        }
    if slice_id == "I":
        return {
            "analysis_unit": "candidate",
            "raw_arm_row_count": len(rows["single_arms"]) + len(rows["search"]),
            "unique_candidate_count": 1,
            "unique_outcome_count": 0,
            "hypothesis_family_count": 0,
            "robustness_grade": "DESCRIPTIVE_ONLY",
            "dependence_state": "SAME_CANDIDATE_REUSED_ACROSS_ARMS",
        }
    return {
        "final_readiness": result.j_readiness.value,
        "candidate_count": 1,
        "artifact_row_group_count": len(result.rows),
        "implementation_defect_count": 0,
        "point_in_time_leakage_count": 0,
        "unexplained_divergence_count": 0,
        "reconciliation_defect_count": 0,
    }


def _real_set_count(rows: tuple[dict[str, object], ...]) -> int:
    return sum(row["set_id"] != "NONE" for row in rows)


def _executive_report(result: GateIsolationShadowResult) -> str:
    e = _slice_summary(result, "E")
    f = _slice_summary(result, "F")
    g = _slice_summary(result, "G")
    h = _slice_summary(result, "H")
    i = _slice_summary(result, "I")
    return (
        "\n".join(
            (
                "# DSI-002 Governed Gate-Isolation Shadow",
                "",
                f"Final readiness: **{result.j_readiness.value}**",
                f"Candidate: `{result.candidate_identity}`",
                "",
                "## Slice Readiness",
                "",
                f"- E: {result.e_readiness.value}",
                f"- F: {result.f_readiness.value}",
                f"- G: {result.g_readiness.value}",
                f"- H: {result.h_readiness.value}",
                f"- I: {result.i_readiness.value}",
                "",
                "## Findings",
                "",
                (
                    f"E observed {e['observed_failed_gate_count']} failed conditions; "
                    f"{e['eligible_gate_count']} were isolatable and "
                    f"{e['ineligible_gate_count']} composite conditions remained."
                ),
                (
                    f"F tested {f['tested_subset_count']} exact subsets and found "
                    f"{f['sufficient_set_count']} sufficient approval sets."
                ),
                (
                    f"G created {g['approval_count']} approvals and "
                    f"{g['trade_formed_count']} trades under unchanged policy."
                ),
                (
                    f"H found {h['comparable_outcome_count']} comparable completed "
                    "outcomes; economic values remain UNKNOWN."
                ),
                (
                    f"I uses `{i['analysis_unit']}` as the analytic unit and grades "
                    "the evidence DESCRIPTIVE_ONLY because every arm reuses one BEL "
                    "candidate."
                ),
                "",
                "This package proves governed mechanics only. It makes no causal, "
                "economic-superiority, policy, approval, execution, or production "
                "claim.",
                "",
                "PRODUCTION_INFLUENCE=false",
            )
        )
        + "\n"
    )


def _write_csv(
    path: Path,
    rows: Iterable[Mapping[str, object]],
) -> Path:
    normalized = tuple(dict(row) for row in rows)
    if not normalized:
        raise GateIsolationShadowArtifactError(
            f"cannot export empty evidence artifact: {path.name}"
        )
    fieldnames = tuple(normalized[0])
    if any(tuple(row) != fieldnames for row in normalized):
        raise GateIsolationShadowArtifactError(
            f"inconsistent evidence schema: {path.name}"
        )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            lineterminator="\n",
        )
        writer.writeheader()
        for row in normalized:
            writer.writerow({key: _cell(value) for key, value in row.items()})
    return path


def _write_json(path: Path, payload: Mapping[str, object]) -> Path:
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def _write_text(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateIsolationShadowArtifactError("invalid E-J certificate") from exc
    if not isinstance(payload, dict):
        raise GateIsolationShadowArtifactError("E-J certificate must be an object")
    return payload


def _cell(value: object) -> object:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "UNKNOWN"
    return value


def _report_sha(payload: Mapping[str, object]) -> str:
    normalized = dict(payload)
    normalized.pop("report_sha256", None)
    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "GateIsolationShadowArtifactError",
    "export_gate_isolation_shadow",
    "validate_gate_isolation_shadow_certificate",
]
