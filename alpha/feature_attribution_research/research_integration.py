"""Institutional Research Director integration for feature attribution."""

from __future__ import annotations

import csv
import json
from collections.abc import Set
from decimal import Decimal
from pathlib import Path

from alpha.feature_attribution_research.exports import (
    DEFAULT_FEATURE_ATTRIBUTION_OUTPUT,
)
from alpha.feature_attribution_research.models import RESEARCH_VERSION
from alpha.research.diagnostic_registry import CallableDiagnosticPlugin
from alpha.research.models import (
    BottleneckStatus,
    DiagnosticEvidence,
    DiagnosticState,
    EvidenceQuality,
    MetricAvailability,
    MetricProvenance,
    ResearchConfidence,
    ResearchMaturity,
    ResearchMetric,
    ResearchSubsystem,
)

DIAGNOSTIC_ID = "point-in-time-feature-attribution"


def research_diagnostic_plugins() -> tuple[CallableDiagnosticPlugin, ...]:
    return (
        CallableDiagnosticPlugin(
            diagnostic_id=DIAGNOSTIC_ID,
            title="Point-in-time feature attribution and orthogonal edge audit",
            subsystem=ResearchSubsystem.FEATURE_ATTRIBUTION,
            source_module="alpha.feature_attribution_research",
            collector=_collect,
        ),
    )


def _collect() -> DiagnosticEvidence:
    root = DEFAULT_FEATURE_ATTRIBUTION_OUTPUT
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return DiagnosticEvidence(
            diagnostic_id=DIAGNOSTIC_ID,
            title="Point-in-time feature attribution and orthogonal edge audit",
            subsystem=ResearchSubsystem.FEATURE_ATTRIBUTION,
            source_module="alpha.feature_attribution_research",
            source_version=RESEARCH_VERSION,
            state=DiagnosticState.UNAVAILABLE,
            maturity=ResearchMaturity.NASCENT,
            evidence_quality=EvidenceQuality.UNKNOWN,
            confidence=ResearchConfidence.UNKNOWN,
            bottleneck_status=BottleneckStatus.UNKNOWN,
            metrics=(),
            finding="No completed feature-attribution artifact is available.",
            recommended_action="Run `alpha feature-attribution report`.",
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stability = _csv_rows(root / "chronological_stability.csv")
    rankings = _csv_rows(root / "feature_rankings.csv")
    leakage = _csv_rows(root / "feature_leakage_audit.csv")
    outcome_coupled = {
        row["feature_id"]
        for row in leakage
        if row.get("outcome_definition_coupled", "").lower() == "true"
    }
    positive = _features(stability, "STABLE_POSITIVE", exclude=outcome_coupled)
    negative = _features(stability, "STABLE_NEGATIVE", exclude=outcome_coupled)
    holdout_failures = _features(stability, "HOLDOUT_FAILURE")
    orthogonal = tuple(
        row["feature_id"]
        for row in rankings
        if row.get("ranking_name") == "orthogonal_incremental_value"
        and row["feature_id"] not in outcome_coupled
    )[:10]
    summary = manifest.get("population_summary", {})
    provenance = MetricProvenance(
        source="FeatureAttributionResearchEngine.run",
        definition="Pre-association point-in-time feature attribution",
        population="ALL_MARKET_OPPORTUNITIES",
        version=RESEARCH_VERSION,
    )
    metrics = (
        _metric(
            "feature_attribution.population",
            "Research population size",
            int(summary.get("reconstructed_market_opportunities", 0)),
            "count",
            provenance,
        ),
        _metric(
            "feature_attribution.feature_count",
            "Registered features",
            int(manifest.get("feature_count", 0)),
            "count",
            provenance,
        ),
        _metric(
            "feature_attribution.safe_features",
            "Point-in-time safe features",
            int(manifest.get("point_in_time_safe_feature_count", 0)),
            "count",
            provenance,
        ),
        _metric(
            "feature_attribution.blocked_features",
            "Blocked features",
            int(manifest.get("blocked_feature_count", 0)),
            "count",
            provenance,
        ),
        _metric(
            "feature_attribution.primary_outcome",
            "Primary outcome",
            str(manifest.get("primary_outcome", "UNKNOWN")),
            "label",
            provenance,
        ),
        _metric(
            "feature_attribution.stable_positive",
            "Stable positive features",
            "|".join(positive) or "NONE",
            "feature_ids",
            provenance,
        ),
        _metric(
            "feature_attribution.stable_negative",
            "Stable negative features",
            "|".join(negative) or "NONE",
            "feature_ids",
            provenance,
        ),
        _metric(
            "feature_attribution.orthogonal",
            "Top orthogonal features",
            "|".join(orthogonal) or "NONE",
            "feature_ids",
            provenance,
        ),
        _metric(
            "feature_attribution.holdout_failures",
            "Holdout failures",
            "|".join(holdout_failures) or "NONE",
            "feature_ids",
            provenance,
        ),
        _metric(
            "feature_attribution.outcome_coupled_features",
            "Outcome-definition-coupled features",
            "|".join(sorted(outcome_coupled)) or "NONE",
            "feature_ids",
            provenance,
        ),
    )
    return DiagnosticEvidence(
        diagnostic_id=DIAGNOSTIC_ID,
        title="Point-in-time feature attribution and orthogonal edge audit",
        subsystem=ResearchSubsystem.FEATURE_ATTRIBUTION,
        source_module="alpha.feature_attribution_research",
        source_version=RESEARCH_VERSION,
        state=DiagnosticState.AVAILABLE,
        maturity=ResearchMaturity.PARTIAL,
        evidence_quality=EvidenceQuality.MEDIUM,
        confidence=ResearchConfidence.MEDIUM,
        bottleneck_status=(
            BottleneckStatus.PROVEN
            if int(manifest.get("blocked_feature_count", 0)) > 0
            else BottleneckStatus.NO_MATERIAL_GAP
        ),
        metrics=metrics,
        finding=(
            f"{len(positive)} stable positive, {len(negative)} stable negative, and "
            f"{len(holdout_failures)} holdout-failing features were identified."
        ),
        recommended_action=(
            "Review feature cards and missing-information priorities before choosing "
            "another diagnostic experiment; do not alter production weights."
        ),
        limitations=(
            "Legacy data is provisional.",
            "Market-regime and sector stability are unavailable across full history.",
            "Production influence is false.",
        ),
    )


def _metric(
    metric_id: str,
    label: str,
    value: int | str | Decimal | None,
    unit: str,
    provenance: MetricProvenance,
) -> ResearchMetric:
    return ResearchMetric(
        metric_id=metric_id,
        label=label,
        value=value,
        unit=unit,
        provenance=provenance,
        availability=(
            MetricAvailability.NOT_ESTIMABLE
            if value is None
            else MetricAvailability.AVAILABLE
        ),
    )


def _features(
    rows: tuple[dict[str, str], ...],
    classification: str,
    *,
    exclude: Set[str] = frozenset(),
) -> tuple[str, ...]:
    return tuple(
        row["feature_id"]
        for row in rows
        if row.get("classification") == classification
        and row["feature_id"] not in exclude
    )


def _csv_rows(path: Path) -> tuple[dict[str, str], ...]:
    if not path.exists():
        return ()
    with path.open(encoding="utf-8", newline="") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


__all__ = ["research_diagnostic_plugins"]
