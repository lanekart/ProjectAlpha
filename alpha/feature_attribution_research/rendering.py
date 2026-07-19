"""Investor-readable and research-governance rendering."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from alpha.feature_attribution_research.models import (
    FeatureAttributionReport,
    FeatureCard,
    FeatureConfidenceTier,
    StabilityClassification,
)


def render_population(report: FeatureAttributionReport) -> str:
    summary = report.population_summary
    lines = [
        "Point-in-Time Research Population",
        "",
        f"Primary Population: {report.manifest.primary_population.value}",
        "Reconstructed Market Opportunities: "
        f"{summary.reconstructed_market_opportunities:,}",
        f"Labelled Opportunities: {summary.labelled_market_opportunities:,}",
        f"Raw Linked Onsets: {summary.raw_linked_onsets:,}",
        f"Deduplicated Linked Onsets: {summary.deduplicated_linked_onsets:,}",
        f"Costs Used: {report.manifest.transaction_cost_policy.display_percent:.2f}%",
        f"Cost Policy: {report.manifest.transaction_cost_policy.policy_id}",
        "",
        f"Selection-Bias Warning: {summary.selection_bias_warning}",
    ]
    return "\n".join(lines) + "\n"


def render_feature_cards(cards: tuple[FeatureCard, ...]) -> str:
    lines = ["# Top 20 Feature Cards", ""]
    for index, card in enumerate(cards, start=1):
        lines.extend(
            (
                f"## {index}. {card.feature_name}",
                "",
                f"- Direction: {card.direction.value}",
                f"- Confidence Tier: {card.confidence_tier.value}",
                f"- Development AUC: {_value(card.development_auc)}",
                f"- Validation AUC: {_value(card.validation_auc)}",
                f"- Holdout AUC: {_value(card.holdout_auc)}",
                f"- Stability Score: {_value(card.stability_score)}",
                f"- Orthogonal Increment: {_value(card.orthogonal_incremental_auc)}",
                "- Information Decay: " + _decay(card),
                f"- Data Quality: {', '.join(card.data_quality_flags) or 'PASS'}",
                f"- Conclusion: {card.conclusion.value}",
                f"- Recommendation: {card.recommendation}",
                "",
                card.evidence_summary,
                "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def render_report(report: FeatureAttributionReport) -> str:
    stable = Counter(item.classification for item in report.stability)
    tiers_by_feature = {
        item.feature_id: item.confidence_tier
        for item in report.rankings
        if item.ranking_name == "operational_availability"
    }
    tier_counts = Counter(tiers_by_feature.values())
    coupled = {
        item.feature_id for item in report.leakage if item.outcome_definition_coupled
    }
    blocked = sum(not item.point_in_time_safe for item in report.feature_definitions)
    safe = len(report.feature_definitions) - blocked
    positive = tuple(
        item
        for item in report.stability
        if item.classification is StabilityClassification.STABLE_POSITIVE
    )
    negative = tuple(
        item
        for item in report.stability
        if item.classification is StabilityClassification.STABLE_NEGATIVE
    )
    lines = [
        "# Point-in-Time Feature Attribution & Orthogonal Edge Audit v1.0",
        "",
        "## Research Contract",
        "",
        f"- Production Influence: {str(report.manifest.production_influence).lower()}",
        f"- Canonical Policy: {report.manifest.canonical_policy_id}",
        f"- Dataset: {report.manifest.dataset_version}",
        f"- Primary Outcome: {report.manifest.primary_outcome}",
        f"- Costs Used: {report.manifest.transaction_cost_policy.display_percent:.2f}%",
        f"- Cost Policy: {report.manifest.transaction_cost_policy.policy_id}",
        "",
        "## Population",
        "",
        "- All Market Opportunities: "
        f"{report.population_summary.reconstructed_market_opportunities:,}",
        "- Labelled Opportunities: "
        f"{report.population_summary.labelled_market_opportunities:,}",
        f"- Raw Linked Onsets: {report.population_summary.raw_linked_onsets:,}",
        "- Deduplicated Linked Onsets: "
        f"{report.population_summary.deduplicated_linked_onsets:,}",
        f"- Warning: {report.population_summary.selection_bias_warning}",
        "",
        "## Feature Coverage",
        "",
        f"- Registered Features: {len(report.feature_definitions):,}",
        f"- Point-in-Time Safe Features: {safe:,}",
        f"- Blocked Features: {blocked:,}",
        f"- Stable Positive: {len(positive):,}",
        f"- Stable Negative: {len(negative):,}",
        f"- Holdout Failures: {stable[StabilityClassification.HOLDOUT_FAILURE]:,}",
        "",
        "## Confidence Tiers",
        "",
        *(f"- {tier.value}: {tier_counts[tier]:,}" for tier in FeatureConfidenceTier),
        "",
        "## Stable Positive Features",
        "",
        *(_feature_lines(positive, coupled) or ("- None established.",)),
        "",
        "## Stable Negative Features",
        "",
        *(_feature_lines(negative, coupled) or ("- None established.",)),
        "",
        "## Data Constraints",
        "",
        "- Relative strength is blocked because authoritative benchmark history is "
        "absent.",
        "- Regime and breadth are blocked outside the limited diagnostic snapshot "
        "dates.",
        "- Historical sector state is unavailable.",
        "- Canonical component attribution is sparse and candidate-selected.",
        "- Stop distance, target distance, and reward/risk are coupled to the "
        "primary outcome definition; their apparent edge is not orthogonal.",
        "- Legacy identity and corporate-action history remain provisional.",
        "",
        "## CTO Conclusion",
        "",
        "No production weights, thresholds, setups, approvals, or policies were "
        "changed. "
        "A strong feature is research evidence, not a new trading rule.",
        "",
        render_feature_cards(report.feature_cards),
    ]
    return "\n".join(lines).rstrip() + "\n"


def _feature_lines(
    values: tuple[object, ...], outcome_coupled: set[str]
) -> tuple[str, ...]:
    return tuple(
        f"- {getattr(item, 'feature_id')}: stability "
        f"{_value(getattr(item, 'overall_stability'))}"
        + (
            " (outcome-definition coupled; not orthogonal evidence)"
            if getattr(item, "feature_id") in outcome_coupled
            else ""
        )
        for item in values[:10]
    )


def _decay(card: FeatureCard) -> str:
    if not card.information_decay:
        return "unavailable"
    return ", ".join(
        f"{horizon}D AUC {_value(value)}" for horizon, value in card.information_decay
    )


def _value(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"{value:.4f}"


__all__ = ["render_feature_cards", "render_population", "render_report"]
