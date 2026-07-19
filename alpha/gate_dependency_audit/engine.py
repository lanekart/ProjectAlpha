from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

from alpha.benchmark_replay.provenance import file_hash
from alpha.gate_dependency_audit.bottleneck import (
    bottleneck_summary,
    first_failure_statistics,
    gate_report_cards,
    path_statistics,
    sequential_survival,
)
from alpha.gate_dependency_audit.dependency_graph import dependency_matrix
from alpha.gate_dependency_audit.gate_order import evaluate_gate_order
from alpha.gate_dependency_audit.gate_sequence import gate_sequence_hash
from alpha.gate_dependency_audit.interaction_matrix import interaction_matrix
from alpha.gate_dependency_audit.lineage import DecisionLineageBuilder
from alpha.gate_dependency_audit.marginal_value import marginal_gate_values
from alpha.gate_dependency_audit.models import (
    BASELINE_ID,
    GDSBA_VERSION,
    GateDependencyAuditReport,
    GDSBAManifest,
)


class GateDependencyAuditEngine:
    """Explain sequential and interacting gate behavior without policy mutation."""

    def run(
        self,
        *,
        igta_output: Path | str,
        acu_output: Path | str,
        benchmark_output: Path | str,
        project_root: Path | str,
    ) -> GateDependencyAuditReport:
        evidence = DecisionLineageBuilder().build(
            igta_output=igta_output,
            acu_output=acu_output,
            project_root=project_root,
        )
        igta_manifest = dict(evidence.igta_manifest)
        baseline_path = Path(benchmark_output) / "manifest.json"
        candidate_statistics_path = Path(benchmark_output) / "candidate_statistics.csv"
        if not baseline_path.exists():
            raise FileNotFoundError("CABR manifest unavailable for GDSBA")
        if file_hash(baseline_path) != str(
            igta_manifest.get("baseline_manifest_hash", "")
        ):
            raise ValueError("CABR manifest checksum does not match IGTA")
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        if not isinstance(baseline, dict) or baseline.get("baseline_id") != BASELINE_ID:
            raise ValueError("GDSBA requires ALPHA_BASELINE_v1.0")
        policy = _mapping(baseline, "policy")
        artifacts = _mapping(baseline, "artifact_hashes")
        if file_hash(candidate_statistics_path) != str(
            artifacts.get("candidate_statistics.csv", "")
        ):
            raise ValueError("CABR candidate statistics checksum mismatch")
        technical_candidates, buy_candidates = _candidate_counts(
            candidate_statistics_path
        )
        initial_capital = Decimal(_text(policy, "initial_capital"))
        lineages = evidence.lineages
        first = first_failure_statistics(lineages)
        survival = sequential_survival(lineages)
        dependencies = dependency_matrix(lineages)
        interactions = interaction_matrix(lineages)
        marginal = marginal_gate_values(
            lineages,
            initial_capital=initial_capital,
        )
        cards = gate_report_cards(
            lineages,
            marginal_values=marginal,
            initial_capital=initial_capital,
        )
        order = evaluate_gate_order(lineages)
        bottleneck = bottleneck_summary(
            first_failures=first,
            report_cards=cards,
            interactions=interactions,
            marginal_values=marginal,
        )
        source_hashes = dict(evidence.source_hashes)
        source_hashes["baseline_manifest.json"] = file_hash(baseline_path)
        source_hashes["candidate_statistics.csv"] = file_hash(candidate_statistics_path)
        manifest = GDSBAManifest(
            audit_version=GDSBA_VERSION,
            baseline_id=BASELINE_ID,
            igta_manifest_hash=source_hashes["igta_manifest.json"],
            approval_policy_version=_text(igta_manifest, "approval_policy_version"),
            approval_policy_hash=_text(igta_manifest, "approval_policy_hash"),
            gate_sequence_hash=gate_sequence_hash(),
            source_hashes=MappingProxyType(source_hashes),
        )
        return GateDependencyAuditReport(
            manifest=manifest,
            technical_candidates=technical_candidates,
            buy_candidates=buy_candidates,
            lineages=lineages,
            first_failures=first,
            survival=survival,
            dependencies=dependencies,
            interactions=interactions,
            marginal_values=marginal,
            false_rejection_paths=path_statistics(
                lineages,
                outcome_classification="FALSE_REJECTION",
            ),
            correct_rejection_paths=path_statistics(
                lineages,
                outcome_classification="CORRECT_REJECTION",
            ),
            report_cards=cards,
            gate_order=order,
            bottleneck=bottleneck,
        )


def _mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"manifest field must be an object: {key}")
    return {str(item_key): item for item_key, item in value.items()}


def _text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if value is None or not str(value).strip():
        raise ValueError(f"manifest field is unavailable: {key}")
    return str(value)


def _candidate_counts(path: Path) -> tuple[int, int]:
    technical = 0
    buy = 0
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            technical += int(row["technical_candidates"])
            buy += int(row["buy_candidates"]) + int(row["strong_buy_candidates"])
    return technical, buy


__all__ = ["GateDependencyAuditEngine"]
