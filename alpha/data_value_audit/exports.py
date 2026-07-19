"""Deterministic CSV and Markdown exports for DVRA."""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from alpha.data_value_audit.models import (
    DataValueAuditReport,
    DecisionDimension,
    ReplayMetric,
)
from alpha.data_value_audit.rendering import (
    render_budget_page,
    render_procurement_strategy,
    render_report,
)

DEFAULT_DVRA_OUTPUT = Path("docs/data_value_audit")


class DataValueAuditExporter:
    """Write the required, stable DVRA artifact bundle atomically."""

    def export(
        self,
        report: DataValueAuditReport,
        output_directory: Path | str = DEFAULT_DVRA_OUTPUT,
    ) -> tuple[Path, ...]:
        output = Path(output_directory)
        artifacts = {
            "dataset_report_cards.csv": _report_cards_csv(report),
            "information_gain.csv": _information_csv(report),
            "decision_gain.csv": _decision_csv(report),
            "dependency_graph.csv": _dependencies_csv(report),
            "cost_model.csv": _cost_csv(report),
            "roi_matrix.csv": _roi_csv(report),
            "procurement_strategy.md": render_procurement_strategy(report),
            "executive_report.md": render_report(report),
        }
        plans = {plan.budget_id: plan for plan in report.budgets}
        for budget_id in ("budget_0", "budget_1L", "budget_5L", "budget_unlimited"):
            artifacts[f"{budget_id}.md"] = render_budget_page(report, plans[budget_id])
        paths = []
        for filename, content in sorted(artifacts.items()):
            destination = output / filename
            _write_text(destination, content)
            paths.append(destination)
        return tuple(paths)


def _report_cards_csv(report: DataValueAuditReport) -> str:
    rows: list[dict[str, object]] = []
    for card in report.cards:
        replay = {item.metric: item.impact.value for item in card.replay.impacts}
        row: dict[str, object] = {
            "dataset_id": card.candidate.dataset_id,
            "dataset": card.candidate.name,
            "domain": card.candidate.domain.value,
            "information_gain": card.information.score,
            "decision_gain": card.decision.score,
            "infrastructure_gain": card.infrastructure.score,
            "infrastructure_subsystem_count": card.infrastructure.subsystem_count,
            "subsystems": "|".join(
                item.value for item in card.infrastructure.subsystems
            ),
            "replay_gain": card.replay.overall.value,
            "engineering_cost": card.cost.engineering_cost.value,
            "maintenance_cost": card.cost.maintenance_cost.value,
            "cost_status": card.cost.status.value,
            "annual_cost_inr": _optional_number(card.cost.annual_cost_inr),
            "confidence": card.roi_confidence.value,
            "overall_roi": card.roi_class.value,
            "priority_index": _optional_number(card.priority_index),
            "production_influence": "false",
        }
        row.update(
            {
                f"replay_{metric.value.lower()}": replay[metric]
                for metric in ReplayMetric
            }
        )
        rows.append(row)
    return _csv(rows)


def _information_csv(report: DataValueAuditReport) -> str:
    return _csv(
        [
            {
                "dataset_id": card.candidate.dataset_id,
                "score": card.information.score,
                "novelty_points": card.information.novelty_points,
                "bias_control_points": card.information.bias_control_points,
                "authority_points": card.information.authority_points,
                "point_in_time_points": card.information.point_in_time_points,
                "evidence_points": card.information.evidence_points,
                "confidence": card.information.confidence.value,
                "feature_gap": card.feature_gap.gap,
                "evidence_sources": "|".join(card.candidate.evidence_sources),
            }
            for card in report.cards
        ]
    )


def _decision_csv(report: DataValueAuditReport) -> str:
    dimensions = tuple(DecisionDimension)
    rows = []
    for card in report.cards:
        impacts = {item.dimension: item.impact.value for item in card.decision.impacts}
        row: dict[str, object] = {
            "dataset_id": card.candidate.dataset_id,
            "score": card.decision.score,
            "primary_gain": card.decision.primary_gain,
            "confidence": card.decision.confidence.value,
        }
        row.update(
            {item.value.lower(): impacts.get(item, "UNKNOWN") for item in dimensions}
        )
        rows.append(row)
    return _csv(rows)


def _dependencies_csv(report: DataValueAuditReport) -> str:
    return _csv(
        [
            {
                "source_dataset_id": edge.source_dataset_id,
                "relationship": edge.relationship,
                "target": edge.target,
            }
            for edge in report.dependencies
        ]
    )


def _cost_csv(report: DataValueAuditReport) -> str:
    return _csv(
        [
            {
                "dataset_id": card.candidate.dataset_id,
                "status": card.cost.status.value,
                "initial_cost_inr": _optional_number(card.cost.initial_cost_inr),
                "annual_cost_inr": _optional_number(card.cost.annual_cost_inr),
                "engineering_cost": card.cost.engineering_cost.value,
                "maintenance_cost": card.cost.maintenance_cost.value,
                "licensing_risk": card.cost.licensing_risk.value,
                "legal_risk": card.cost.legal_risk.value,
                "source": card.cost.source,
                "notes": card.cost.notes,
            }
            for card in report.cards
        ]
    )


def _roi_csv(report: DataValueAuditReport) -> str:
    sensitivity = {item.dataset_id: item for item in report.sensitivity}
    return _csv(
        [
            {
                "dataset_id": card.candidate.dataset_id,
                "gross_value_score": card.gross_value_score,
                "priority_index": _optional_number(card.priority_index),
                "overall_roi": card.roi_class.value,
                "confidence": card.roi_confidence.value,
                "cost_status": card.cost.status.value,
                "replay_gain": card.replay.overall.value,
                "unavailable_value_score": sensitivity[
                    card.candidate.dataset_id
                ].value_score_lost,
                "dependent_unlocks_lost": sensitivity[
                    card.candidate.dataset_id
                ].dependent_unlocks_lost,
                "rationale": card.overall_rationale,
            }
            for card in report.cards
        ]
    )


def _csv(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=tuple(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _optional_number(value: int | None) -> int | str:
    return "UNKNOWN" if value is None else value


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


__all__ = ["DEFAULT_DVRA_OUTPUT", "DataValueAuditExporter"]
