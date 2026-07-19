from __future__ import annotations

from collections import Counter
from decimal import Decimal

from alpha.market_dna.models import (
    DNADiscoveryReport,
    DNAHypothesis,
    FeatureDefinition,
    FeatureFinding,
    FeatureQuality,
    OutcomeCohortDefinition,
    StrategyLabHypothesisSpecification,
    TemporalStability,
)


def render_inventory(definitions: tuple[FeatureDefinition, ...]) -> tuple[str, ...]:
    qualities = Counter(item.base_quality.value for item in definitions)
    lines = [
        "Market DNA Point-in-Time Feature Inventory",
        f"Features Registered: {len(definitions)}",
        f"Usable: {qualities[FeatureQuality.USABLE.value]}",
        f"Usable With Caution: {qualities[FeatureQuality.USABLE_WITH_CAUTION.value]}",
        f"Quarantined: {qualities[FeatureQuality.QUARANTINED.value]}",
    ]
    for item in definitions:
        lines.append(
            f"- {item.feature_id}: {item.kind.value}; quality="
            f"{item.base_quality.value}; "
            f"unit={item.unit}; source={item.provenance}"
        )
        if item.known_defects:
            lines.append(f"  Limitation: {'; '.join(item.known_defects)}")
    lines.extend(
        (
            "Future outcomes are retained as labels only and cannot enter discovery "
            "features.",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return tuple(lines)


def render_cohort_definitions(
    definitions: tuple[OutcomeCohortDefinition, ...],
) -> tuple[str, ...]:
    lines = [
        "Market DNA Versioned Outcome Cohorts",
        f"Cohorts Registered: {len(definitions)}",
    ]
    for item in definitions:
        lines.extend(
            (
                f"- {item.cohort_id}: {item.title}",
                f"  Predicate: {item.predicate}",
                f"  Horizon: {item.horizon} | Cost Profile: {item.cost_profile_id}",
            )
        )
    lines.append("PRODUCTION_INFLUENCE=false")
    return tuple(lines)


def render_discovery(report: DNADiscoveryReport) -> tuple[str, ...]:
    statuses = Counter(item.status.value for item in report.patterns)
    lines = [
        "Market DNA Outcome-First Discovery",
        f"Report: {report.report_id}",
        f"Dataset: {report.dataset_version}",
        f"Evidence Class: {report.evidence_class.value}",
        f"Rows Analysed: {report.source_rows}",
        f"Outcome Cohorts: {len(report.cohorts)}",
        "Feature Conditions and Interactions Tested: "
        f"{report.multiple_testing.hypotheses_tested}",
        f"Findings Surviving FDR: {report.multiple_testing.surviving_findings}",
        "Pattern Statuses:",
    ]
    lines.extend(f"- {key}: {value}" for key, value in sorted(statuses.items()))
    lines.extend(
        (
            f"Strategy Hypotheses: {len(report.hypotheses)}",
            f"Conclusion: {report.final_conclusion}",
            "No holdout or causal claim is made from the discovery population.",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return tuple(lines)


def render_cohorts(report: DNADiscoveryReport) -> tuple[str, ...]:
    lines = [
        "Market DNA Cohort Population Report",
        f"Dataset: {report.dataset_version}",
    ]
    matched = {item.cohort_id: item for item in report.matched_cohorts}
    for cohort in report.cohorts:
        match = matched[cohort.definition.cohort_id]
        lines.append(
            f"- {cohort.definition.cohort_id}: sample={cohort.sample_size}; "
            f"symbols={cohort.symbol_count}; average net return="
            f"{_pct(cohort.average_net_return_pct)}; "
            f"matched pairs={match.matched_pairs}; unmatched={match.unmatched_cohort}"
        )
        lines.append(f"  Predicate: {cohort.definition.predicate}")
    lines.append("PRODUCTION_INFLUENCE=false")
    return tuple(lines)


def render_findings(
    report: DNADiscoveryReport,
    *,
    cohort_ids: frozenset[str],
    title: str,
    top: int,
) -> tuple[str, ...]:
    findings = _rank_findings(
        tuple(
            item
            for item in report.findings
            if item.cohort_id in cohort_ids
            and item.scope == "UNIVERSAL"
            and item.enrichment_ratio is not None
            and item.enrichment_ratio > Decimal("1")
        )
    )[:top]
    lines = [title]
    if not findings:
        lines.append("No estimable finding is available for this cohort selection.")
    for index, item in enumerate(findings, start=1):
        lines.extend(_finding_lines(index, item))
    lines.extend(
        (
            "Associations are not causal; reconstructed findings remain research-only.",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return tuple(lines)


def render_interactions(report: DNADiscoveryReport, *, top: int) -> tuple[str, ...]:
    ranked = sorted(
        report.interactions,
        key=lambda item: (
            item.adjusted_p_value
            if item.adjusted_p_value is not None
            else Decimal("1"),
            -(abs(item.effect_size) if item.effect_size is not None else Decimal("0")),
            item.interaction_id,
        ),
    )[:top]
    lines = [
        "Market DNA Bounded Interaction Discovery",
        f"Interactions Retained After Minimum-Cell Checks: {len(report.interactions)}",
    ]
    for item in ranked:
        lines.append(
            f"- {item.interaction_id}: "
            f"{', '.join(value.canonical_key for value in item.conditions)}"
        )
        lines.append(
            f"  Cohort={item.cohort_id}; sample={item.sample_size}; "
            f"enrichment={_number(item.enrichment_ratio)}; adjusted p="
            f"{_number(item.adjusted_p_value)}; fold consistency="
            f"{_pct(item.fold_consistency_pct)}; lineage penalty="
            f"{item.lineage_penalty}"
        )
    lines.extend(
        (
            "Search is bounded and deterministic; no unrestricted interaction mining "
            "occurred.",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return tuple(lines)


def render_hierarchy(report: DNADiscoveryReport, *, top: int) -> tuple[str, ...]:
    lines = ["Market DNA Hierarchical and Cluster Discovery"]
    for item in report.hierarchy[:top]:
        lines.append(
            f"- {item.scope}: population={item.population}; strongest="
            f"{item.strongest_finding_id or 'NOT_ESTIMABLE'}; enrichment="
            f"{_number(item.strongest_enrichment_ratio)}"
        )
        lines.append(f"  Limitation: {'; '.join(item.limitations)}")
    lines.append("Feature-Only Clusters:")
    if not report.clusters:
        lines.append("- NOT_ESTIMABLE: minimum stable cluster support was not met.")
    for cluster in report.clusters:
        lines.append(
            f"- {cluster.cluster_id}: sample={cluster.sample_size}; winner rate="
            f"{_pct(cluster.winner_rate_pct)}; average net return="
            f"{_pct(cluster.average_net_return_pct)}; "
            f"profile={', '.join(cluster.profile)}"
        )
    lines.extend(
        (
            "Clusters are descriptive profiles, not strategies.",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return tuple(lines)


def render_hypotheses(report: DNADiscoveryReport) -> tuple[str, ...]:
    lines = [
        "Market DNA Governed Strategy Hypotheses",
        f"Hypotheses Generated: {len(report.hypotheses)}",
    ]
    if not report.hypotheses:
        lines.append(
            "No pattern met the evidence, stability, concentration, and holdout "
            "requirements."
        )
    for item in report.hypotheses:
        lines.extend(_hypothesis_lines(item))
    lines.extend(
        (
            "Publication creates an inert Strategy Lab specification and never "
            "executes it.",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return tuple(lines)


def render_report(report: DNADiscoveryReport, *, top: int = 5) -> tuple[str, ...]:
    usable = sum(
        item.quality is FeatureQuality.USABLE for item in report.feature_audits
    )
    caution = sum(
        item.quality is FeatureQuality.USABLE_WITH_CAUTION
        for item in report.feature_audits
    )
    quarantined = sum(
        item.quality is FeatureQuality.QUARANTINED for item in report.feature_audits
    )
    stable = sum(
        item.robustness_classification is TemporalStability.STABLE
        for item in report.patterns
    )
    concentrated = sum(item.status.value == "CONCENTRATED" for item in report.patterns)
    lines = [
        "Project Alpha Market DNA Discovery Report",
        f"Report: {report.report_id}",
        f"Dataset / Evidence: {report.dataset_version} / {report.evidence_class.value}",
        f"Rows / Excluded: {report.source_rows} / {report.excluded_rows}",
        f"Outcome Cohorts Evaluated: {len(report.cohorts)}",
        f"Features: usable={usable}; cautious={caution}; quarantined={quarantined}",
        "Winner DNA:",
    ]
    lines.extend(_summary_findings(report, {"STRONG_WINNERS", "MODERATE_WINNERS"}, top))
    lines.append("Loser and Catastrophic-Loss DNA:")
    lines.extend(
        _summary_findings(report, {"LARGE_LOSERS", "CATASTROPHIC_LOSERS"}, top)
    )
    lines.append("Missed-Opportunity DNA:")
    lines.extend(_summary_findings(report, {"PROFITABLE_REJECTED"}, top))
    lines.extend(
        (
            "Statistical Control:",
            f"- {report.multiple_testing.procedure}: tested="
            f"{report.multiple_testing.hypotheses_tested}; surviving="
            f"{report.multiple_testing.surviving_findings}; rejected="
            f"{report.multiple_testing.rejected_findings}",
            f"Temporal Stability: stable patterns={stable}",
            f"Concentration / Fragility: concentrated patterns={concentrated}",
            f"Bounded Interactions Retained: {len(report.interactions)}",
            f"Descriptive Clusters: {len(report.clusters)}",
            f"Strategy Hypotheses Generated: {len(report.hypotheses)}",
            f"Final Conclusion: {report.final_conclusion}",
            f"Highest-Value Missing Evidence: {report.highest_value_evidence_gap}",
            "No DNA score was added to recommendations, approval, allocation, or "
            "execution.",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return tuple(lines)


def render_publication(
    specification: StrategyLabHypothesisSpecification,
) -> tuple[str, ...]:
    return (
        "Market DNA Strategy Lab Publication",
        f"Specification: {specification.specification_id}",
        f"Hypothesis: {specification.hypothesis_id}",
        "Conditions: "
        f"{', '.join(item.canonical_key for item in specification.conditions)}",
        f"Entry Logic: {specification.entry_logic}",
        f"Horizon: {specification.horizon}",
        "Execution: NOT_STARTED",
        "Required Next Steps: Strategy Lab, walk-forward, robustness, shadow "
        "validation.",
        "PRODUCTION_INFLUENCE=false",
    )


def _rank_findings(findings: tuple[FeatureFinding, ...]) -> tuple[FeatureFinding, ...]:
    return tuple(
        sorted(
            findings,
            key=lambda item: (
                item.adjusted_p_value
                if item.adjusted_p_value is not None
                else Decimal("1"),
                -(
                    abs(item.effect_size)
                    if item.effect_size is not None
                    else Decimal("0")
                ),
                -item.cohort_match_count,
                item.finding_id,
            ),
        )
    )


def _finding_lines(index: int, item: FeatureFinding) -> tuple[str, ...]:
    return (
        f"{index}. {item.condition.canonical_key}",
        f"   Cohort={item.cohort_id}; population={item.cohort_count}; "
        f"condition matches={item.cohort_match_count}; "
        f"prevalence={_pct(item.cohort_prevalence_pct)} vs "
        f"{_pct(item.baseline_prevalence_pct)}; enrichment="
        f"{_number(item.enrichment_ratio)}",
        f"   Effect={_number(item.effect_size)}; raw p={_number(item.raw_p_value)}; "
        f"adjusted p={_number(item.adjusted_p_value)}; stability="
        f"{item.temporal_stability.value}",
    )


def _summary_findings(
    report: DNADiscoveryReport, cohort_ids: set[str], top: int
) -> tuple[str, ...]:
    ranked = _rank_findings(
        tuple(
            item
            for item in report.findings
            if item.cohort_id in cohort_ids
            and item.scope == "UNIVERSAL"
            and item.enrichment_ratio is not None
            and item.enrichment_ratio > Decimal("1")
        )
    )[:top]
    if not ranked:
        return ("- NOT_ESTIMABLE",)
    return tuple(
        f"- {item.cohort_id}: {item.condition.canonical_key}; enrichment="
        f"{_number(item.enrichment_ratio)}; adjusted p="
        f"{_number(item.adjusted_p_value)}; "
        f"stability={item.temporal_stability.value}"
        for item in ranked
    )


def _hypothesis_lines(item: DNAHypothesis) -> tuple[str, ...]:
    return (
        f"- {item.hypothesis_id}",
        "  Conditions: "
        f"{', '.join(value.canonical_key for value in item.canonical_conditions)}",
        f"  Required Strategy Lab Test: {item.required_strategy_lab_test}",
        f"  Required Walk-Forward Test: {item.required_walk_forward_test}",
    )


def _number(value: Decimal | None) -> str:
    return "NOT_ESTIMABLE" if value is None else str(value)


def _pct(value: Decimal | None) -> str:
    return "NOT_ESTIMABLE" if value is None else f"{value}%"


__all__ = [
    "render_cohort_definitions",
    "render_cohorts",
    "render_discovery",
    "render_findings",
    "render_hierarchy",
    "render_hypotheses",
    "render_interactions",
    "render_inventory",
    "render_publication",
    "render_report",
]
