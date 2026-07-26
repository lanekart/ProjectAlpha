"""Deterministic artifact export and public validation for DSI-002D."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Final

from alpha.decision_superiority.gate_isolation_stage_attribution import (
    DSI002D_CONTRACT_VERSION,
    DSI002DReadiness,
    DSI002DResult,
)

CERTIFICATE_NAME: Final = "dsi002d_stage_attribution_certificate.json"
SUPPORT_NAMES: Final = (
    "dsi002d_stage_inventory.csv",
    "dsi002d_candidate_stage_event_ledger.csv",
    "dsi002d_candidate_rejection_attribution.csv",
    "dsi002d_stage_reachability_and_omission.csv",
    "dsi002d_candidate_flow_reconciliation.csv",
    "dsi002d_raw_adjusted_stage_comparison.csv",
    "dsi002d_evaluator_invocation_integrity.csv",
    "dsi002d_non_vacuity_probe_ledger.csv",
    "dsi002d_source_contract_snapshot.csv",
    "dsi002d_executive_report.md",
)
GOVERNANCE_FLAGS: Final = (
    "CAUSAL_CLAIM_PERMITTED",
    "THRESHOLD_CHANGE_PERMITTED",
    "GATE_ORDER_CHANGE_PERMITTED",
    "APPROVAL_POLICY_CHANGE_PERMITTED",
    "PORTFOLIO_POLICY_CHANGE_PERMITTED",
    "EXECUTION_POLICY_CHANGE_PERMITTED",
    "COUNTERFACTUAL_GATE_OVERRIDE_ENABLED",
    "COUNTERFACTUAL_APPROVAL_CLAIMED",
    "SYNTHETIC_RECOMMENDATIONS_PERMITTED",
    "SYNTHETIC_APPROVALS_PERMITTED",
    "SYNTHETIC_TRADES_PERMITTED",
    "SYNTHETIC_OUTCOMES_PERMITTED",
    "ECONOMIC_SUPERIORITY_CLAIMED",
    "LIVE_SCORING_ENABLED",
    "RECOMMENDATION_INFLUENCE",
    "PORTFOLIO_POLICY_INFLUENCE",
    "EXECUTION_INFLUENCE",
    "LEARNING_MUTATION_ENABLED",
    "ACTIVE_REPLAY_INTEGRATION",
    "PRODUCTION_INFLUENCE",
)


class DSI002DArtifactError(ValueError):
    """Raised when a DSI-002D artifact bundle is incomplete or tampered."""


def export_dsi002d(
    result: DSI002DResult,
    output: Path,
) -> tuple[Path, ...]:
    """Write the complete deterministic DSI-002D bundle."""

    output.mkdir(parents=True, exist_ok=True)
    paths = (
        _write_csv(
            output / SUPPORT_NAMES[0],
            (asdict(item) for item in result.stage_inventory),
        ),
        _write_csv(
            output / SUPPORT_NAMES[1],
            (asdict(item) for item in result.events),
        ),
        _write_csv(
            output / SUPPORT_NAMES[2],
            (asdict(item) for item in result.attributions),
        ),
        _write_csv(
            output / SUPPORT_NAMES[3],
            (asdict(item) for item in result.omissions),
        ),
        _write_csv(output / SUPPORT_NAMES[4], result.flow_rows),
        _write_csv(output / SUPPORT_NAMES[5], result.arm_rows),
        _write_csv(output / SUPPORT_NAMES[6], result.invocation_rows),
        _write_csv(output / SUPPORT_NAMES[7], result.probe_rows),
        _write_csv(output / SUPPORT_NAMES[8], result.source_rows),
        _write_text(output / SUPPORT_NAMES[9], _render_report(result)),
    )
    manifest = {path.name: _file_sha256(path) for path in paths}
    report_sha256 = _hash_payload(_certificate_report_payload(result, manifest))
    certificate_payload = _certificate_payload(
        result=result,
        manifest=manifest,
        report_sha256=report_sha256,
    )
    certificate = output / CERTIFICATE_NAME
    certificate.write_text(
        json.dumps(certificate_payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return (certificate, *paths)


def validate_dsi002d_certificate(
    certificate: Path,
    *,
    require_ready: bool = False,
    verify_current_sources: bool = True,
) -> dict[str, object]:
    """Validate every hash-bound output in one public DSI-002D bundle."""

    try:
        payload = json.loads(certificate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DSI002DArtifactError("invalid DSI-002D certificate") from exc
    if not isinstance(payload, dict):
        raise DSI002DArtifactError("DSI-002D certificate must contain an object")
    if payload.get("contract_version") != DSI002D_CONTRACT_VERSION:
        raise DSI002DArtifactError("unsupported DSI-002D contract version")
    flags = payload.get("governance_flags")
    if not isinstance(flags, dict) or set(flags) != set(GOVERNANCE_FLAGS):
        raise DSI002DArtifactError("governance flag set is incomplete")
    if any(value is not False for value in flags.values()):
        raise DSI002DArtifactError("a governance influence flag is enabled")
    manifest = payload.get("support_artifact_manifest")
    if not isinstance(manifest, dict) or set(manifest) != set(SUPPORT_NAMES):
        raise DSI002DArtifactError("support artifact manifest is incomplete")
    root = certificate.resolve().parent
    for name, expected in manifest.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise DSI002DArtifactError("malformed support artifact manifest")
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise DSI002DArtifactError("support artifact path is invalid")
        if _file_sha256(path) != expected:
            raise DSI002DArtifactError(f"support artifact tampered: {name}")
    if verify_current_sources:
        _validate_evaluator_sources(root / "dsi002d_stage_inventory.csv")
    report_payload = dict(payload)
    report_payload.pop("report_sha256", None)
    report_payload.pop("support_artifact_manifest", None)
    report_payload["support_artifact_manifest"] = manifest
    expected_report = payload.get("report_sha256")
    if _hash_payload(report_payload) != expected_report:
        raise DSI002DArtifactError("DSI-002D report hash mismatch")
    readiness = payload.get("readiness_decision")
    if require_ready and readiness != DSI002DReadiness.READY.value:
        raise DSI002DArtifactError(f"DSI-002D is not ready: {readiness}")
    return payload


def _certificate_payload(
    *,
    result: DSI002DResult,
    manifest: Mapping[str, str],
    report_sha256: str,
) -> dict[str, object]:
    payload = _certificate_report_payload(result, manifest)
    payload["report_sha256"] = report_sha256
    return payload


def _certificate_report_payload(
    result: DSI002DResult,
    manifest: Mapping[str, str],
) -> dict[str, object]:
    failures = tuple(
        event for event in result.events if str(event.result_state) == "FAIL"
    )
    missing = tuple(
        omission
        for omission in result.omissions
        if str(omission.omission_state) == "MISSING_EVALUATOR_WIRING"
    )
    duplicate_count = sum(
        _as_int(row["duplicate_invocation_count"]) for row in result.invocation_rows
    )
    return {
        "contract_version": DSI002D_CONTRACT_VERSION,
        "prerequisite_contract_versions": {
            source.bundle: source.contract_version for source in result.sources
        },
        "prerequisite_certificate_hashes": {
            source.bundle: source.certificate_file_sha256 for source in result.sources
        },
        "prerequisite_internal_report_hashes": {
            source.bundle: source.internal_report_sha256 for source in result.sources
        },
        "prerequisite_support_hashes": {
            source.bundle: source.support_artifact_sha256 for source in result.sources
        },
        "source_commit": result.source_commit,
        "captured_population_identity": (
            result.sources[0].candidate_identity if result.sources else ""
        ),
        "snapshot_sha256": (
            result.sources[0].snapshot_sha256 if result.sources else ""
        ),
        "stage_inventory_hash": _hash_payload(
            [asdict(item) for item in result.stage_inventory]
        ),
        "frozen_policy_and_evaluator_hashes": {
            item.stage_id: {
                "configuration_sha256": item.configuration_sha256,
                "source_sha256": item.source_sha256,
            }
            for item in result.stage_inventory
        },
        "raw_summary": _arm_summary(result, "RAW"),
        "adjusted_summary": _arm_summary(result, "ADJUSTED"),
        "candidate_flow_summary": {
            "input_count": len(result.attributions),
            "candidate_count": len(result.attributions),
            "stage_event_count": len(result.events),
            "terminal_state_count": len(result.attributions),
            "unexplained_drop_count": sum(
                not item.decision_parity for item in result.attributions
            ),
        },
        "attribution_summary": {
            "complete_count": sum(
                item.attribution_complete for item in result.attributions
            ),
            "incomplete_count": sum(
                not item.attribution_complete for item in result.attributions
            ),
            "observed_failure_count": len(failures),
            "unexplained_terminal_decision_count": sum(
                item.unexplained_terminal_decision for item in result.attributions
            ),
        },
        "omission_summary": {
            "missing_evaluator_wiring_count": len(missing),
            "unexplained_stage_omission_count": sum(
                str(item.omission_state) == "UNEXPLAINED_STAGE_OMISSION"
                for item in result.omissions
            ),
        },
        "invocation_integrity_summary": {
            "duplicate_invocation_count": duplicate_count,
            "implementation_defect_count": sum(
                str(item.result_state) == "IMPLEMENTATION_ERROR"
                for item in result.events
            ),
        },
        "probe_summary": {
            "probe_count": len(result.probe_rows),
            "passed_count": sum(bool(row["passed"]) for row in result.probe_rows),
            "empirical_count_contamination": sum(
                bool(row["included_in_empirical_counts"]) for row in result.probe_rows
            ),
        },
        "readiness_decision": result.readiness.value,
        "blockers": list(result.blockers),
        "support_artifact_manifest": dict(sorted(manifest.items())),
        "governance_flags": {name: False for name in GOVERNANCE_FLAGS},
    }


def _arm_summary(result: DSI002DResult, arm: str) -> dict[str, object]:
    events = tuple(event for event in result.events if event.price_arm == arm)
    candidates = {event.candidate_key for event in events}
    return {
        "candidate_count": len(candidates),
        "stage_event_count": len(events),
        "pass_count": sum(str(event.result_state) == "PASS" for event in events),
        "fail_count": sum(str(event.result_state) == "FAIL" for event in events),
        "unknown_count": sum(str(event.result_state) == "UNKNOWN" for event in events),
    }


def _render_report(result: DSI002DResult) -> str:
    attribution = result.attributions[0] if result.attributions else None
    lines = [
        "# DSI-002D Governed Stage Attribution",
        "",
        f"Readiness: **{result.readiness.value}**",
        f"Source commit: `{result.source_commit}`",
        f"Candidates: {len(result.attributions)}",
        f"Stage inventory entries: {len(result.stage_inventory)}",
        f"Canonical stage events: {len(result.events)}",
        "",
        "## Finding",
        "",
        (
            "The signed baseline invokes recommendation and portfolio engines, "
            "but does not invoke the separate InstitutionalDecisionEngine base, "
            "stress, or optimization stages. Those stages are recorded as "
            "MISSING_EVALUATOR_WIRING and no result is inferred."
        ),
    ]
    if attribution is not None:
        lines.extend(
            (
                "",
                "## Candidate Attribution",
                "",
                f"Candidate: `{attribution.candidate_key}`",
                f"Recorded decision: {attribution.recorded_terminal_decision}",
                f"First observed blocker: {attribution.first_blocking_stage}",
                f"All observed blockers: {attribution.all_observed_blocking_stages}",
                f"Decision parity: {attribution.decision_parity}",
                f"Attribution complete: {attribution.attribution_complete}",
            )
        )
    lines.extend(
        (
            "",
            "## Governance",
            "",
            "This bundle is observational only. It makes no causal, economic, "
            "counterfactual, approval, execution, or production claim.",
            "",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return "\n".join(lines) + "\n"


def _write_csv(path: Path, rows: Iterable[Mapping[str, object]]) -> Path:
    normalized = tuple(dict(row) for row in rows)
    fieldnames: tuple[str, ...]
    if normalized:
        fieldnames = tuple(normalized[0])
    else:
        fieldnames = ("empty",)
        normalized = ({"empty": ""},)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            lineterminator="\n",
        )
        writer.writeheader()
        for row in normalized:
            writer.writerow({key: _csv_value(value) for key, value in row.items()})
    return path


def _write_text(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    return path


def _validate_evaluator_sources(inventory: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    with inventory.open("r", encoding="utf-8", newline="") as handle:
        rows = tuple(csv.DictReader(handle))
    for row in rows:
        source = (project_root / row["source_file"]).resolve()
        if not source.is_relative_to(project_root) or not source.is_file():
            raise DSI002DArtifactError("evaluator source path is invalid")
        if _file_sha256(source) != row["source_sha256"]:
            raise DSI002DArtifactError(f"evaluator source drift: {row['stage_id']}")


def _csv_value(value: object) -> object:
    if isinstance(value, bool):
        return str(value).lower()
    if hasattr(value, "value"):
        return getattr(value, "value")
    return value


def _as_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise DSI002DArtifactError("expected an integer artifact value")


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "CERTIFICATE_NAME",
    "DSI002DArtifactError",
    "GOVERNANCE_FLAGS",
    "SUPPORT_NAMES",
    "export_dsi002d",
    "validate_dsi002d_certificate",
]
