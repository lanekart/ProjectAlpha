from __future__ import annotations

from alpha.historical_truth_acquisition.models import HTAResult


def render_result(result: HTAResult) -> str:
    manifest = result.manifest
    candidate = result.warehouse_candidate
    lines = [
        "Historical Truth Acquisition (HTA v1.0)",
        f"Source Mode: {manifest.source_mode}",
        f"Historical Truth Score: {result.scorecard.overall_score}/100",
        f"Certification Target: {result.scorecard.target_score}/100",
        f"Warehouse v2 Candidate: {candidate.status.value}",
        "Stages:",
    ]
    for stage in result.certifications:
        active = sum(item.active for item in stage.dataset_certifications)
        lines.append(
            f"- {stage.stage.value}: {stage.status.value}; "
            f"ACTIVE datasets={active}/{len(stage.dataset_certifications)}"
        )
    lines.extend(
        (
            "Reconciliation:",
            f"- Compared Observations: {result.reconciliation.compared_observations}",
            f"- Classified Discrepancies: {len(result.reconciliation.findings)}",
            "- Automatic Overwrites: 0",
            f"Replay Migrated: {'YES' if candidate.replay_migrated else 'NO'}",
            "Production Influence: "
            f"{'TRUE' if candidate.production_influence else 'FALSE'}",
            f"Artifacts: {len(result.artifacts)}",
        )
    )
    return "\n".join(lines) + "\n"


def render_certification(result: HTAResult) -> str:
    lines = ["HTA Certification Report"]
    for stage in result.certifications:
        lines.append(f"\n{stage.stage.value}: {stage.status.value}")
        for dataset in stage.dataset_certifications:
            lines.append(
                f"- {dataset.dataset_id}: {dataset.status.value}; "
                f"score={dataset.overall_score}; "
                f"ACTIVE={'YES' if dataset.active else 'NO'}"
            )
            lines.extend(f"  Reason: {reason}" for reason in dataset.reasons)
    return "\n".join(lines) + "\n"


def render_reconciliation(result: HTAResult) -> str:
    summary = result.reconciliation
    lines = [
        "HTA Reconciliation",
        f"Compared: {summary.compared_observations}",
        f"Matching: {summary.matching_observations}",
        f"Findings: {len(summary.findings)}",
        "Automatic Overwrites: 0",
    ]
    for finding in summary.findings[:20]:
        lines.append(
            f"- {finding.discrepancy_type.value}: {finding.observation_key}; "
            f"{finding.explanation}"
        )
    return "\n".join(lines) + "\n"


def render_scorecard(result: HTAResult) -> str:
    lines = [
        "Historical Truth Scorecard",
        f"Overall: {result.scorecard.overall_score}/100",
        f"Target: {result.scorecard.target_score}/100",
        f"Target Met: {'YES' if result.scorecard.target_met else 'NO'}",
    ]
    lines.extend(
        f"- {item.stage.value}: {item.score}/100; {item.certification.value}"
        for item in result.scorecard.logical_datasets
    )
    return "\n".join(lines) + "\n"


def render_warehouse(result: HTAResult) -> str:
    candidate = result.warehouse_candidate
    lines = [
        "Warehouse v2 Candidate",
        f"Status: {candidate.status.value}",
        f"Historical Truth Score: {candidate.historical_truth_score}/100",
        f"ACTIVE Datasets: {len(candidate.active_dataset_ids)}",
        f"Blocked Datasets: {len(candidate.blocked_dataset_ids)}",
        "Activation Performed: NO",
        "Replay Migrated: NO",
        "Production Influence: FALSE",
    ]
    lines.extend(f"- {reason}" for reason in candidate.reasons)
    return "\n".join(lines) + "\n"


__all__ = [
    "render_certification",
    "render_reconciliation",
    "render_result",
    "render_scorecard",
    "render_warehouse",
]
