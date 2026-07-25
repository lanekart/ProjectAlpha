"""Phase 4F reconciliation for observed versus isolated gate evidence."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from alpha.decision_superiority.gate_artifacts import (
    CONFIDENCE_SUMMARY_FIELDS,
    EVIDENCE_SUMMARY_FIELDS,
    GATE_CONCLUSION_FIELDS,
    GATE_RECOMMENDATION_FIELDS,
    build_gate_artifact_rows,
)
from alpha.decision_superiority.gate_pipeline import (
    GatePipelineInput,
    GatePipelineResult,
    run_gate_pipeline,
)
from alpha.decision_superiority.gate_value_audit import (
    DSI001Result,
    GovernedGateValueAudit,
)

_DIAGNOSTIC_FILES = {
    "dsi001_gate_conclusions.csv": GATE_CONCLUSION_FIELDS,
    "dsi001_evidence_summary.csv": EVIDENCE_SUMMARY_FIELDS,
    "dsi001_confidence_summary.csv": CONFIDENCE_SUMMARY_FIELDS,
    "dsi001_gate_recommendations.csv": GATE_RECOMMENDATION_FIELDS,
}
_VALUE_FIELDS = (
    "gate_code",
    "blocked_candidate_count",
    "unique_blocked_candidate_count",
    "co_blocked_candidate_count",
    "resolved_outcome_count",
    "positive_outcome_count",
    "negative_outcome_count",
    "flat_outcome_count",
    "average_return_pct",
    "avoided_loss_benefit",
    "profitable_rejection_cost",
    "net_gate_value",
    "conclusion",
)


class GovernedPhase4FGateValueAudit:
    """Run the legacy audit and reconcile its isolated-evidence publication."""

    def run(
        self,
        *,
        candidate_gate_forensics: Path,
        gate_event_ledger: Path,
        outcome_coverage_ledger: Path,
        output: Path,
    ) -> DSI001Result:
        result = GovernedGateValueAudit().run(
            candidate_gate_forensics=candidate_gate_forensics,
            gate_event_ledger=gate_event_ledger,
            outcome_coverage_ledger=outcome_coverage_ledger,
            output=output,
        )
        inventory = _read_rows(output / "dsi001_gate_inventory.csv")
        legacy_values = {
            row["gate_code"]: row
            for row in _read_rows(output / "dsi001_gate_value_summary.csv")
        }
        isolated_returns = _isolated_returns(
            output / "dsi001_single_gate_counterfactual_ledger.csv"
        )

        pipelines: dict[str, GatePipelineResult] = {}
        value_rows: list[dict[str, object]] = []
        for inventory_row in inventory:
            gate_code = inventory_row["gate_code"]
            legacy = legacy_values.get(gate_code, {})
            blocked = int(legacy.get("blocked_candidate_count") or 0)
            unique = int(legacy.get("unique_blocked_candidate_count") or 0)
            co_blocked = int(legacy.get("co_blocked_candidate_count") or 0)
            observed_resolved = int(legacy.get("resolved_outcome_count") or 0)
            returns = tuple(isolated_returns.get(gate_code, ()))
            empty_reason, isolation_status = _isolation_state(
                blocked=blocked,
                unique=unique,
                observed_resolved=observed_resolved,
                isolated_resolved=len(returns),
            )
            pipeline = run_gate_pipeline(
                GatePipelineInput(
                    gate_code=gate_code,
                    sample_count=unique,
                    returns_pct=returns,
                    minimum_required=0,
                    empty_reason=empty_reason,
                    observed_blocked_count=blocked,
                    observed_resolved_count=observed_resolved,
                    co_blocked_count=co_blocked,
                    isolation_status=isolation_status,
                )
            )
            pipelines[gate_code] = pipeline
            value_rows.append(
                _value_row(
                    gate_code=gate_code,
                    legacy=legacy,
                    pipeline=pipeline,
                )
            )

        projections = build_gate_artifact_rows(pipelines)
        projected_rows = {
            "dsi001_gate_conclusions.csv": list(projections.conclusions),
            "dsi001_evidence_summary.csv": list(projections.evidence),
            "dsi001_confidence_summary.csv": list(projections.confidence),
            "dsi001_gate_recommendations.csv": list(projections.recommendations),
        }
        for name, fields in _DIAGNOSTIC_FILES.items():
            _write_rows(output / name, projected_rows[name], fields)
        _write_rows(
            output / "dsi001_gate_value_summary.csv",
            value_rows,
            _VALUE_FIELDS,
        )

        report = dict(result.report)
        report["gate_value_summary"] = value_rows
        report["gate_conclusions"] = list(projections.conclusions)
        report["evidence_summary"] = list(projections.evidence)
        report["confidence_summary"] = list(projections.confidence)
        report["gate_recommendations"] = list(projections.recommendations)
        report["gate_population_reconciliation"] = {
            "observed_gate_count": len(inventory),
            "published_gate_count": len(pipelines),
            "recommendation_population": "UNIQUE_BLOCKER_ONLY",
            "co_blocked_outcomes_are_descriptive_only": True,
        }
        artifact_hashes = dict(report["artifact_hashes"])
        for name in (*_DIAGNOSTIC_FILES, "dsi001_gate_value_summary.csv"):
            artifact_hashes[name] = _sha256(output / name)
        report["artifact_hashes"] = dict(sorted(artifact_hashes.items()))
        report.pop("report_sha256", None)
        report["report_sha256"] = hashlib.sha256(
            json.dumps(report, sort_keys=True, default=str).encode()
        ).hexdigest()
        certificate = output / "dsi001_gate_value_audit_certificate.json"
        certificate.write_text(
            json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        return DSI001Result(report=report, paths=result.paths)


def _isolated_returns(path: Path) -> dict[str, list[Decimal]]:
    grouped: dict[str, list[Decimal]] = defaultdict(list)
    for row in _read_rows(path):
        if not _truthy(row.get("unique_blocker")):
            continue
        if not _truthy(row.get("resolved_outcome")):
            continue
        grouped[row["gate_code"]].append(Decimal(row["realized_return_pct"]))
    return grouped


def _isolation_state(
    *,
    blocked: int,
    unique: int,
    observed_resolved: int,
    isolated_resolved: int,
) -> tuple[str, str]:
    if blocked == 0:
        return "NO_OBSERVED_FAILURES", "NOT_OBSERVED_TO_FAIL"
    if unique == 0:
        return "NO_UNIQUE_BLOCKERS", "CONFOUNDED_CO_BLOCKED_ONLY"
    if isolated_resolved == 0:
        return "NO_ISOLATED_RESOLVED_OUTCOMES", "ISOLATED_OUTCOMES_UNAVAILABLE"
    if observed_resolved < isolated_resolved:
        raise ValueError("isolated resolved outcomes exceed observed resolved outcomes")
    return "NO_RESOLVED_OUTCOMES", "ISOLATED_POPULATION"


def _value_row(
    *,
    gate_code: str,
    legacy: dict[str, str],
    pipeline: GatePipelineResult,
) -> dict[str, object]:
    isolated_resolved = pipeline.distribution.resolved_count
    unavailable = isolated_resolved == 0
    conclusion = (
        "GATE_NOT_OBSERVED_TO_FAIL"
        if pipeline.observed_blocked_count == 0
        else "GATE_VALUE_UNAVAILABLE_CONFOUNDED"
        if pipeline.distribution.sample_count == 0
        else "INSUFFICIENT_ISOLATED_RESOLVED_OUTCOMES"
        if unavailable
        else "GATE_ADDS_MEASURABLE_VALUE"
        if pipeline.economic_value.net_gate_value > 0
        else "GATE_DESTROYS_MEASURABLE_VALUE"
        if pipeline.economic_value.net_gate_value < 0
        else "GATE_VALUE_INCONCLUSIVE"
    )
    return {
        "gate_code": gate_code,
        "blocked_candidate_count": pipeline.observed_blocked_count,
        "unique_blocked_candidate_count": pipeline.distribution.sample_count,
        "co_blocked_candidate_count": pipeline.co_blocked_count,
        "resolved_outcome_count": pipeline.observed_resolved_count,
        "positive_outcome_count": int(legacy.get("positive_outcome_count") or 0),
        "negative_outcome_count": int(legacy.get("negative_outcome_count") or 0),
        "flat_outcome_count": int(legacy.get("flat_outcome_count") or 0),
        "average_return_pct": legacy.get("average_return_pct") or "UNAVAILABLE",
        "avoided_loss_benefit": (
            pipeline.economic_value.avoided_loss_benefit
            if not unavailable
            else "UNAVAILABLE"
        ),
        "profitable_rejection_cost": (
            pipeline.economic_value.profitable_rejection_cost
            if not unavailable
            else "UNAVAILABLE"
        ),
        "net_gate_value": (
            pipeline.economic_value.net_gate_value if not unavailable else "UNAVAILABLE"
        ),
        "conclusion": conclusion,
    }


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_rows(
    path: Path,
    rows: list[dict[str, object]],
    fields: tuple[str, ...],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = ["GovernedPhase4FGateValueAudit"]
