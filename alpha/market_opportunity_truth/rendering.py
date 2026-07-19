from __future__ import annotations

from decimal import Decimal

from alpha.market_opportunity_truth.models import MarketOpportunityTruthReport


def render_executive_report(report: MarketOpportunityTruthReport) -> str:
    supply = report.supply_summary
    capture = report.capture_statistics
    lines = [
        "# Market Opportunity Truth Audit",
        "",
        f"Audit: {report.manifest.audit_version}",
        f"Baseline: {report.manifest.baseline_id}",
        "Classification: RESEARCH / DIAGNOSTIC",
        "Production Influence: NONE",
        "",
        "## Executive Answer",
        "",
        f"The frozen observed market produced **{supply.total_opportunities:,}** "
        "point-in-time tradable onsets under MOTA's versioned research definition.",
        f"Of these, **{supply.institutional_quality_opportunities:,}** received "
        "provisional A+ or A grades using no future outcome information.",
        f"There were {_number(supply.average_institutional_opportunities_per_month)} "
        "provisional A+/A opportunities per observed month on average and "
        f"{_number(supply.median_institutional_opportunities_per_month)} at the "
        "median.",
        "This is an empirical denominator under a frozen definition, not a claim "
        "that market opportunity has a unique model-free ground truth.",
        f"Grouped expectancy validation: {supply.institutional_quality_status}; "
        f"A+/A averaged {_r(supply.institutional_average_realized_r)} versus "
        f"{_r(supply.other_average_realized_r)} for B/C. The grade tiers were "
        f"{'monotonic' if supply.quality_tier_monotonic else 'not monotonic'}.",
        "",
        "## Market Supply",
        "",
        f"- Total opportunities: {supply.total_opportunities:,}",
        "- Provisional A+/A opportunities: "
        f"{supply.institutional_quality_opportunities:,}",
        f"- Mature 120-session outcomes: {supply.mature_outcomes:,}",
        f"- Months observed: {supply.months_observed:,}",
        f"- Average opportunities/month: "
        f"{_number(supply.average_opportunities_per_month)}",
        f"- Median opportunities/month: "
        f"{_number(supply.median_opportunities_per_month)}",
        f"- Best month: {supply.best_month} ({supply.best_month_opportunities:,})",
        f"- Worst month: {supply.worst_month} ({supply.worst_month_opportunities:,})",
        "- Authoritative market-regime history: unavailable; no regime attribution "
        "was asserted.",
        "",
        "## Quality Distribution",
        "",
        "| Quality | Opportunities | Population | Mature | Target Before Stop | "
        "Stop First | Average R | Average MFE | Average MAE |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(
        f"| {item.quality.value} | {item.opportunities:,} | "
        f"{_percent(item.population_percent)} | {item.mature_outcomes:,} | "
        f"{_percent(item.target_before_stop_rate)} | "
        f"{_percent(item.stop_hit_rate)} | {_r(item.average_realized_r)} | "
        f"{_percent(item.average_mfe_percent)} | "
        f"{_percent(item.average_mae_percent)} |"
        for item in report.quality_distribution
    )
    lines.extend(
        [
            "",
            "## Alpha Comparison",
            "",
            f"- Detection proxy recall, provisional A+/A opportunities: "
            f"{_percent(capture.institutional_detection_recall_percent)}",
            f"- Candidate recall, provisional A+/A opportunities: "
            f"{_percent(capture.institutional_candidate_recall_percent)}",
            f"- Approval recall: "
            f"{_percent(capture.institutional_approval_recall_percent)}",
            f"- Execution recall: "
            f"{_percent(capture.institutional_execution_recall_percent)}",
            f"- Opportunity capture rate: "
            f"{_percent(capture.opportunity_capture_rate_percent)}",
            f"- Move capture: {_percent(capture.move_capture_percent)}",
            f"- Capital capture: {_percent(capture.capital_capture_percent)}",
            "",
            capture.explanation,
            "",
            "## Natural Opportunity Families",
            "",
            "| Cluster | Opportunities | Provisional A+/A | Population | "
            "Target Before Stop | Average R | Average MFE |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    lines.extend(
        f"| {item.cluster_id} | {item.opportunities:,} | "
        f"{item.institutional_quality:,} | {_percent(item.population_percent)} | "
        f"{_percent(item.target_before_stop_rate)} | "
        f"{_r(item.average_realized_r)} | "
        f"{_percent(item.average_mfe_percent)} |"
        for item in report.clusters
    )
    lines.extend(
        [
            "",
            "## Methodological Controls",
            "",
            "- The 133,185-row pre-association population is the denominator; the "
            "55,014 hindsight-linked rows are not.",
            "- Quality and natural-cluster hashes are frozen before outcome labels "
            "are attached.",
            "- Market regime remains unavailable because authoritative historical "
            "market-state evidence is not present.",
            "- Detection is a technical-ranking proxy; complete pre-candidate setup "
            "detection history was not persisted.",
            "- Legacy warehouse data remains provisional.",
            "- A+/A is provisional rather than certified institutional quality; "
            "group expectancy separates from B/C, but individual grade tiers are "
            "not monotonic and require forward validation.",
            "",
            "PRODUCTION_INFLUENCE=false",
            "NO_FEATURE_CHANGES=true",
            "NO_GATE_CHANGES=true",
            "NO_APPROVAL_CHANGES=true",
            "NO_WEIGHT_CHANGES=true",
            "NO_SETUP_CHANGES=true",
            "POINT_IN_TIME_ONLY=true",
            "",
        ]
    )
    return "\n".join(lines)


def render_audit_summary(report: MarketOpportunityTruthReport) -> str:
    supply = report.supply_summary
    capture = report.capture_statistics
    return "\n".join(
        (
            "Market Opportunity Truth Audit",
            f"Total Market Opportunities: {supply.total_opportunities}",
            "Provisional A+/A Opportunities: "
            f"{supply.institutional_quality_opportunities}",
            "Average Provisional A+/A Opportunities / Month: "
            f"{_number(supply.average_institutional_opportunities_per_month)}",
            f"Best Month: {supply.best_month} ({supply.best_month_opportunities})",
            f"Worst Month: {supply.worst_month} ({supply.worst_month_opportunities})",
            "Alpha Candidate Recall: "
            f"{_percent(capture.institutional_candidate_recall_percent)}",
            "Alpha Approval Recall: "
            f"{_percent(capture.institutional_approval_recall_percent)}",
            "Alpha Execution Recall: "
            f"{_percent(capture.institutional_execution_recall_percent)}",
            "PRODUCTION_INFLUENCE=false",
            "",
        )
    )


def _percent(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"{value}%"


def _number(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"{value:,.2f}"


def _r(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"{value}R"


__all__ = ["render_audit_summary", "render_executive_report"]
