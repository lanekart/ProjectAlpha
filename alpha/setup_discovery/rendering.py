# ruff: noqa: E501 - report prose remains readable as complete output lines.
from __future__ import annotations

import textwrap
from collections import Counter
from decimal import Decimal

from alpha.setup_discovery.models import (
    ResearchRecommendation,
    SetupDiscoveryReport,
    SetupRecommendationRecord,
)


def render_summary(report: SetupDiscoveryReport) -> str:
    summary = report.summary
    lines = [
        "Setup Discovery & Evidence Engine v1.0",
        f"Unsupported Cases: {summary.unsupported_cases}",
        f"Unsupported Cases Clustered: {summary.unsupported_cases_clustered}",
        f"Unsupported Cases Unclustered: {summary.unsupported_cases_unclustered}",
        f"Distinct Setup Families: {summary.clusters_selected}",
        f"Top Three Families: {', '.join(summary.top_three_clusters)}",
        f"Top Three Coverage: {summary.top_three_case_share:.2%}",
        f"Lookback Claims: {summary.lookback_cases_claimed}",
        f"Lookback Claims Proven: {summary.lookback_cases_confirmed}",
        f"Lookback Claims Rejected: {summary.lookback_cases_rejected}",
        f"Lookback Claims Data-Insufficient: {summary.lookback_cases_data_insufficient}",
        f"Strongest New Archetype: {summary.strongest_research_family}",
        f"Overall Evidence Confidence: {summary.overall_evidence_confidence}",
        "Production Influence: NONE",
        "PRODUCTION_INFLUENCE=false",
    ]
    return "\n".join(lines) + "\n"


def render_recommendations(report: SetupDiscoveryReport) -> str:
    lines = [
        "# Setup Discovery Recommendations",
        "",
        "This report recommends research actions only. No setup, threshold, or "
        "production policy is changed.",
        "",
        "`PRODUCTION_INFLUENCE=false`",
        "",
        "## Acceptance Questions",
        "",
        f"- Distinct unsupported families: {report.summary.clusters_selected}",
        f"- Unsupported cases clustered: {report.summary.unsupported_cases_clustered} of "
        f"{report.summary.unsupported_cases}",
        f"- Unclustered data gaps: {report.summary.unsupported_cases_unclustered}",
        f"- Three largest families: {', '.join(report.summary.top_three_clusters)}",
        f"- Share explained by those families: {report.summary.top_three_case_share:.2%}",
        f"- Lookback mismatch proven: {report.summary.lookback_cases_confirmed} of "
        f"{report.summary.lookback_cases_claimed}",
        f"- Lookback claims data-insufficient: {report.summary.lookback_cases_data_insufficient}",
        f"- Strongest new archetype for future research: {report.summary.strongest_research_family}",
        f"- Families not to add: {', '.join(report.summary.families_not_to_add) or 'None'}",
        "",
        "## Recommendation Matrix",
        "",
    ]
    recommendation_by_id = {item.cluster_id: item for item in report.recommendations}
    for catalog in report.catalog:
        item = recommendation_by_id[catalog.cluster_id]
        lines.extend(_recommendation_lines(catalog.family_name, catalog, item))
    lines.extend(
        (
            "## Method Guardrails",
            "",
            "- Clustering used point-in-time technical characteristics only.",
            "- Future returns were attached only after cluster labels were frozen.",
            "- Chronological development, validation, and holdout outcomes are reported separately.",
            "- Candidate explosion is an observed-population risk flag, not a fabricated estimate.",
            "- Every positive recommendation requires isolated Strategy Lab and walk-forward validation.",
            "",
        )
    )
    return "\n".join(lines)


def render_diagnostic_finding(report: SetupDiscoveryReport) -> str:
    return (
        f"{report.summary.clusters_selected} point-in-time setup archetypes explain "
        f"{report.summary.unsupported_cases} unsupported cases; the three largest "
        f"explain {report.summary.top_three_case_share:.2%}. Only "
        f"{report.summary.lookback_cases_confirmed} of "
        f"{report.summary.lookback_cases_claimed} claimed lookback mismatches survive proof."
    )


def recommendation_counts(
    recommendations: tuple[SetupRecommendationRecord, ...],
) -> Counter[ResearchRecommendation]:
    return Counter(item.recommendation for item in recommendations)


def _recommendation_lines(
    family_name: str, catalog: object, recommendation: SetupRecommendationRecord
) -> tuple[str, ...]:
    values = catalog
    return (
        f"### {family_name}",
        "",
        f"- Recommendation: {recommendation.recommendation.value.replace('_', ' ').title()}",
        f"- Vocabulary: {getattr(values, 'classification').value.replace('_', ' ').title()}",
        f"- Evidence: {recommendation.evidence_strength}",
        f"- Risk: {recommendation.risk}",
        f"- Occurrences explained: {getattr(values, 'occurrences_explained')}",
        f"- Unsupported-case share: {getattr(values, 'unsupported_case_share'):.2%}",
        f"- Average 60-session net outcome: {_percent(getattr(values, 'average_expectancy'))}",
        f"- Average prospective reward/risk: {getattr(values, 'average_reward_risk'):.2f}",
        f"- Chronological stability: {getattr(values, 'stability')}",
        f"- Candidate explosion risk: {getattr(values, 'candidate_explosion_risk')}",
        f"- Reason: {recommendation.reason}",
        "",
    )


def _percent(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"{value:.2%}"


def wrapped_lines(value: str, width: int) -> tuple[str, ...]:
    return tuple(textwrap.wrap(value, width=width, break_long_words=False)) or ("",)


__all__ = [
    "recommendation_counts",
    "render_diagnostic_finding",
    "render_recommendations",
    "render_summary",
    "wrapped_lines",
]
