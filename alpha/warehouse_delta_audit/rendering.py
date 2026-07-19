"""Investor-readable rendering for the Warehouse Delta Audit."""

# Report prose is kept as whole sentences so the exported Markdown remains readable.
# ruff: noqa: E501

from __future__ import annotations

from alpha.warehouse_delta_audit.models import WarehouseDeltaReport


def render_audit_summary(report: WarehouseDeltaReport) -> str:
    matched = sum(item.matched_observations for item in report.price_deltas)
    exact = sum(item.exact_observations for item in report.price_deltas)
    large = sum(item.large_difference_observations for item in report.price_deltas)
    invalid = sum(item.comparison_invalid_observations for item in report.price_deltas)
    indicator_material = sum(item.material_changes for item in report.indicator_deltas)
    candidate_only = sum(
        item.candidate_only_legacy + item.candidate_only_comparison
        for item in report.candidate_deltas
    )
    lines = [
        "Project Alpha - Warehouse Delta Audit",
        f"Status: {report.status.value}",
        "PRODUCTION_INFLUENCE=false",
        f"Source Lineage: {report.manifest.source_lineage.value}",
        f"Symbols Compared: {report.sample.symbols}",
        f"Historical Period: {report.sample.start} to {report.sample.end}",
        f"Common Replay Sessions: {report.sample.sessions}",
        "",
        "Measured Deltas",
        f"- Paired OHLCV observations: {matched}",
        f"- Exact OHLCV observations: {exact}",
        f"- Large OHLCV differences: {large}",
        f"- Invalid comparison observations excluded: {invalid}",
        f"- Material indicator differences: {indicator_material}",
        f"- Candidates present in only one warehouse: {candidate_only}",
        f"- Material decisions: {report.material_decisions}",
        f"- Critical decisions: {report.critical_decisions}",
        "",
        f"Estimated Alpha Improvement: {report.estimated_alpha_improvement}",
        f"Estimated Confidence: {report.confidence.value}",
        f"Purchase Recommendation: {report.purchase_recommendation.value}",
        f"Personal Decision: {report.personal_decision.value}",
        f"Reason: {report.recommendation_reason}",
    ]
    return _finish(lines)


def render_replay_summary(report: WarehouseDeltaReport) -> str:
    lines = [
        "Project Alpha - Warehouse Replay Delta",
        "PRODUCTION_INFLUENCE=false",
        "Identical settings: YES",
    ]
    for item in report.replay_deltas:
        lines.append(
            f"- {item.metric}: legacy={_value(item.legacy_value)}, "
            f"comparison={_value(item.comparison_value)}, "
            f"delta={_value(item.delta)} {item.unit}"
        )
    return _finish(lines)


def render_purchase_justification(report: WarehouseDeltaReport) -> str:
    lines = [
        "# Would I personally spend ₹315,000 of my own money after seeing these results?",
        "",
        f"## {report.personal_decision.value}",
        "",
        report.recommendation_reason,
        "",
        f"Formal recommendation: `{report.purchase_recommendation.value}`.",
        "",
        "## Evidence",
        "",
        f"- Source lineage: `{report.manifest.source_lineage.value}`.",
        f"- Symbols compared: {report.sample.symbols}.",
        f"- Period: {report.sample.start} to {report.sample.end}.",
        f"- Common replay sessions: {report.sample.sessions}.",
        f"- Material decisions: {report.material_decisions}.",
        f"- Critical decisions: {report.critical_decisions}.",
        f"- Estimated Alpha improvement: {report.estimated_alpha_improvement}",
        f"- Confidence: {report.confidence.value}.",
        "",
        "## What Would Change The Answer",
        "",
        "Supply a lawfully obtained, independently sourced NSE/BSE sample with written internal-research and retention rights, plus point-in-time corporate actions. Run the same frozen comparison and require measured risk-adjusted replay improvement before purchasing.",
        "",
        "**PRODUCTION_INFLUENCE=false**",
    ]
    return _finish(lines)


def render_executive_report(report: WarehouseDeltaReport) -> str:
    matched = sum(item.matched_observations for item in report.price_deltas)
    exact = sum(item.exact_observations for item in report.price_deltas)
    small = sum(item.small_difference_observations for item in report.price_deltas)
    large = sum(item.large_difference_observations for item in report.price_deltas)
    missing_comparison = sum(
        item.missing_from_comparison for item in report.price_deltas
    )
    missing_legacy = sum(item.missing_from_legacy for item in report.price_deltas)
    invalid_legacy = sum(
        item.legacy_invalid_observations for item in report.price_deltas
    )
    invalid_comparison = sum(
        item.comparison_invalid_observations for item in report.price_deltas
    )
    lines = [
        "# Warehouse Delta Audit v1.0",
        "",
        "**Classification:** Validation / Research  ",
        "**PRODUCTION_INFLUENCE=false**",
        "",
        "## Executive Answer",
        "",
        f"Purchase recommendation: **{report.purchase_recommendation.value}**.  ",
        f"Personal decision on INR 315,000: **{report.personal_decision.value}**.  ",
        f"Confidence: **{report.confidence.value}**.",
        "",
        report.recommendation_reason,
        "",
        "## Frozen Comparison",
        "",
        f"- Baseline: `{report.manifest.baseline_id}`.",
        f"- Data platform: `{report.manifest.data_platform_id}`.",
        f"- Warehouse: `{report.manifest.warehouse_version}` vs `{report.manifest.comparison_warehouse_version}`.",
        f"- Feature version: `{report.manifest.feature_version}`.",
        f"- Candidate version: `{report.manifest.candidate_version}`.",
        f"- Policy version: `{report.manifest.policy_version}`.",
        f"- Manifest hash: `{report.manifest.manifest_hash}`.",
        "",
        "No replay, gate, feature or weight setting changed.",
        "",
        "## Sample",
        "",
        f"- Symbols: {report.sample.symbols} of {report.sample.requested_symbols} requested.",
        f"- Period: {report.sample.start} to {report.sample.end}.",
        f"- Common sessions: {report.sample.sessions}.",
        f"- Source files: {report.sample.source_files}.",
        f"- Liquidity strata: high {report.sample.liquidity_high}, medium {report.sample.liquidity_medium}, low {report.sample.liquidity_low}.",
        f"- Sector coverage: {report.sample.sector_coverage}.",
        f"- Market-cap coverage: {report.sample.market_cap_coverage}.",
        "",
        "## Price Delta",
        "",
        f"- Matched observations: {matched}.",
        f"- Exact observations: {exact}.",
        f"- Small differences: {small}.",
        f"- Large differences: {large}.",
        f"- Missing from comparison: {missing_comparison}.",
        f"- Missing from legacy: {missing_legacy}.",
        f"- Invalid legacy observations: {invalid_legacy}.",
        f"- Invalid comparison observations excluded: {invalid_comparison}.",
        "",
        "## Indicator Delta",
        "",
        f"- Compared indicator points: {sum(item.compared_observations for item in report.indicator_deltas)}.",
        f"- Material indicator changes: {sum(item.material_changes for item in report.indicator_deltas)}.",
        f"- Technical signal changes: {sum(item.signal_changes for item in report.indicator_deltas)}.",
        "",
        "## Candidate And Decision Delta",
        "",
        f"- Candidate-only events: {sum(item.candidate_only_legacy + item.candidate_only_comparison for item in report.candidate_deltas)}.",
        f"- Timing shifts: {sum(item.timing_shifted for item in report.candidate_deltas)}.",
        f"- Score shifts: {sum(item.score_shifted for item in report.candidate_deltas)}.",
        f"- Material decisions: {report.material_decisions}.",
        f"- Critical decisions: {report.critical_decisions}.",
        "",
        "## Replay Delta",
        "",
    ]
    lines.extend(
        f"- {item.metric}: {_value(item.legacy_value)} to {_value(item.comparison_value)}; delta {_value(item.delta)} {item.unit}."
        for item in report.replay_deltas
    )
    lines.extend(
        (
            "",
            "## Value Attribution",
            "",
        )
    )
    lines.extend(
        f"- {item.source}: observable changes={_value(item.observable_changes)}; decision changes={_value(item.decision_changes)}; replay={item.replay_effect}; confidence={item.confidence.value}."
        for item in report.value_attribution
    )
    lines.extend(("", "## Limitations", ""))
    lines.extend(f"- {item}" for item in report.limitations)
    lines.extend(
        (
            "",
            "## Estimated Improvement",
            "",
            report.estimated_alpha_improvement,
            "",
            "Difference is not automatically improvement. A purchase requires independent source lineage and better realized replay outcomes under the frozen stack.",
        )
    )
    return _finish(lines)


def _value(value: object | None) -> str:
    return "UNKNOWN" if value is None else str(value)


def _finish(lines: list[str]) -> str:
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "render_audit_summary",
    "render_executive_report",
    "render_purchase_justification",
    "render_replay_summary",
]
