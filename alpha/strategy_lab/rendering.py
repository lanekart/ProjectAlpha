from __future__ import annotations

from collections import Counter
from decimal import Decimal

from alpha.strategy_lab.models import (
    LabStrategyResult,
    LeaderboardView,
    StrategyComparison,
    StrategyLabReport,
)
from alpha.strategy_lab.service import GeneratedLabStrategies, StrategyLabInventory


def render_inventory(inventory: StrategyLabInventory) -> tuple[str, ...]:
    usable = tuple(item for item in inventory.indicators if not item.quarantined)
    quarantined = tuple(item for item in inventory.indicators if item.quarantined)
    lines = [
        "Strategy Lab Indicator and Rule Inventory",
        f"Indicators Registered: {len(inventory.indicators)}",
        f"Usable Point-in-Time Indicators: {len(usable)}",
        f"Quarantined Indicators: {len(quarantined)}",
        "Usable Indicators:",
    ]
    lines.extend(
        f"- {item.canonical_id}: {item.category}; {item.unit}; "
        f"source={item.provenance}; evidence={item.evidence_class.value}"
        for item in usable
    )
    lines.append("Quarantined Indicators:")
    lines.extend(
        f"- {item.canonical_id}: {item.quarantine_reason}" for item in quarantined
    )
    lines.append(f"Strategy Templates: {len(inventory.templates)}")
    lines.extend(
        f"- {item.template_id}: {item.name}; max components={item.maximum_components}"
        for item in inventory.templates
    )
    lines.append("PRODUCTION_INFLUENCE=false")
    return tuple(lines)


def render_generation(generated: GeneratedLabStrategies) -> tuple[str, ...]:
    manifest = generated.search_space
    lines = [
        "Strategy Lab Bounded Search Space",
        f"Dataset: {generated.dataset.dataset_version}",
        f"Evidence Class: {generated.dataset.population_class.value}",
        f"Rows Available: {generated.dataset.row_count}",
        f"Strategies Generated: {manifest.generated_strategies}",
        f"Total Trials: {manifest.total_trials}",
        f"Maximum Components: {manifest.maximum_components}",
        f"Duplicate Rules Removed: {manifest.duplicate_rules_removed}",
        f"Impossible Rules Rejected: {manifest.impossible_rules_rejected}",
        f"Lineage Redundancy Flags: {manifest.lineage_redundancy_flags}",
        f"Search-Space Hash: {manifest.search_space_hash}",
        "Family Counts:",
    ]
    lines.extend(f"- {name}: {count}" for name, count in manifest.family_counts.items())
    lines.append("Execution Rules: " + ", ".join(manifest.rules_tested))
    lines.append("PRODUCTION_INFLUENCE=false")
    return tuple(lines)


def render_backtest(report: StrategyLabReport) -> tuple[str, ...]:
    counts = Counter(item.classification.value for item in report.results)
    lines = [
        "Strategy Lab Historical Backtest",
        f"Experiment: {report.experiment_id}",
        f"Dataset: {report.dataset_version}",
        f"Evidence Class: {report.evidence_class.value}",
        f"Source Rows: {report.source_rows}",
        f"Excluded Rows: {report.excluded_rows}",
        f"Strategies Tested: {len(report.results)}",
        f"Round-Trip Cost: {report.execution_profile.round_trip_cost_pct}%",
        "Classification Summary:",
    ]
    lines.extend(f"- {name}: {count}" for name, count in sorted(counts.items()))
    lines.extend(
        (
            "Simulation Mode: RECONSTRUCTED_OUTCOME_PROXY",
            "Bar-level fills and intraday stop/target ordering are not inferred from "
            "the reconstructed population.",
            f"Conclusion: {report.final_conclusion}",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return tuple(lines)


def render_leaderboard(
    results: tuple[LabStrategyResult, ...],
    *,
    view: LeaderboardView,
    top: int,
) -> tuple[str, ...]:
    lines = [f"Strategy Lab Leaderboard - {view.value}"]
    if not results:
        lines.append("- no strategies match the requested view")
    for rank, item in enumerate(results[:top], start=1):
        metrics = item.metrics
        lines.extend(
            (
                f"{rank}. {item.strategy.strategy_id} | {item.strategy.name}",
                f"   Family: {item.strategy.family}",
                f"   Trades: {metrics.completed_trades} | Precision: "
                f"{_number(metrics.precision_pct)}% | Net Expectancy: "
                f"{_number(metrics.expectancy_pct)}%",
                f"   Profit Factor: {_number(metrics.profit_factor)} | Payoff: "
                f"{_number(metrics.payoff_ratio)} | Max Drawdown: "
                f"{_number(metrics.maximum_drawdown_pct)}%",
                f"   Research Score: {_number(item.research_score)} | Evidence: "
                f"{item.evidence_label.value} | Classification: "
                f"{item.classification.value}",
            )
        )
    lines.append("Default ranking is composite, not precision-only.")
    lines.append("PRODUCTION_INFLUENCE=false")
    return tuple(lines)


def render_comparison(comparison: StrategyComparison) -> tuple[str, ...]:
    lines = [
        "Strategy Lab Side-by-Side Comparison",
        f"Shared Eligible Population: {comparison.shared_population}",
        f"Common Trades: {comparison.common_trade_count}",
    ]
    for strategy_id in comparison.strategy_ids:
        lines.append(
            f"- {strategy_id} Rules: "
            + "; ".join(comparison.rule_definitions[strategy_id])
        )
        lines.append(
            "  Results: unique trades="
            f"{comparison.unique_trade_counts[strategy_id]}, precision delta="
            f"{_number(comparison.precision_deltas[strategy_id])} pp, expectancy "
            f"delta={_number(comparison.expectancy_deltas[strategy_id])} pp, "
            f"drawdown delta={_number(comparison.drawdown_deltas[strategy_id])} pp, "
            f"capital-utilisation delta="
            f"{_number(comparison.capital_utilisation_deltas[strategy_id])} pp, "
            f"configured cost drag="
            f"{_number(comparison.cost_sensitivity_pct[strategy_id])}%"
        )
    lines.extend(
        (
            f"Evidence Confidence: {comparison.evidence_confidence}",
            f"Conclusion: {comparison.conclusion}",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return tuple(lines)


def render_attribution(report: StrategyLabReport, *, top: int) -> tuple[str, ...]:
    lines = [
        "Strategy Lab Indicator and Combination Attribution",
        "Marginal Indicator Comparisons:",
    ]
    lines.extend(
        f"- {item.component_id} in {item.strategy_id}: "
        f"{item.classification.value}; trades delta={item.trade_count_delta}; "
        f"expectancy delta={_number(item.expectancy_delta_pct)} pp; "
        f"precision delta={_number(item.precision_delta_pct)} pp"
        for item in report.component_attribution[:top]
    )
    lines.append("Combination Value Sources:")
    lines.extend(
        f"- {item.strategy_id}: {item.source}; {item.explanation}"
        for item in report.combination_attribution[:top]
    )
    lines.extend(
        (
            "Attribution is associative; lineage-confounded features are not "
            "called causal.",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return tuple(lines)


def render_timeline(result: LabStrategyResult) -> tuple[str, ...]:
    timeline = result.timeline
    lines = [
        "Strategy Lab Performance Timeline",
        f"Strategy: {result.strategy.strategy_id} | {result.strategy.name}",
        "Annual Performance:",
    ]
    lines.extend(
        f"- {item.period}: trades={item.completed_trades}, precision="
        f"{_number(item.precision_pct)}%, expectancy="
        f"{_number(item.expectancy_pct)}%, profit factor="
        f"{_number(item.profit_factor)}, drawdown="
        f"{_number(item.maximum_drawdown_pct)}%"
        for item in timeline.annual
    )
    lines.extend(
        (
            f"Quarterly Periods: {len(timeline.quarterly)}",
            f"Rolling 20-Trade Windows: {len(timeline.rolling_20)}",
            f"Rolling 50-Trade Windows: {len(timeline.rolling_50)}",
            f"Equity Curve Points: {len(timeline.equity_curve)}",
            f"Underwater Curve Points: {len(timeline.underwater_curve)}",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return tuple(lines)


def render_robustness(report: StrategyLabReport, *, top: int) -> tuple[str, ...]:
    lines = ["Strategy Lab Robustness and Multiple-Testing Audit"]
    for item in report.results[:top]:
        robust = item.robustness
        if robust is None:
            continue
        lines.extend(
            (
                f"- {item.strategy.strategy_id}: overfit={robust.overfit}; fold "
                f"consistency={_number(robust.fold_consistency_pct)}%; adjusted "
                f"p={_number(robust.adjusted_p_value)}; hypotheses="
                f"{robust.hypotheses_tested}",
                f"  Cost stress={robust.cost_stress_passed}; slippage stress="
                f"{robust.slippage_stress_passed}; CI="
                f"{_number(robust.bootstrap_expectancy_low_pct)} to "
                f"{_number(robust.bootstrap_expectancy_high_pct)}",
                "  Weaknesses: "
                + ("none" if not robust.weaknesses else "; ".join(robust.weaknesses)),
            )
        )
    lines.extend(
        (
            "Reconstructed winners remain research-only even when robustness "
            "checks pass.",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return tuple(lines)


def render_report(report: StrategyLabReport, *, top: int = 10) -> tuple[str, ...]:
    candidates = tuple(item for item in report.results if not item.strategy.benchmark)
    benchmarks = tuple(item for item in report.results if item.strategy.benchmark)
    precision = sorted(
        candidates,
        key=lambda item: (
            item.metrics.precision_pct or Decimal("-999"),
            item.metrics.completed_trades,
        ),
        reverse=True,
    )
    expectancy = sorted(
        candidates,
        key=lambda item: (
            item.metrics.expectancy_pct or Decimal("-999"),
            item.metrics.completed_trades,
        ),
        reverse=True,
    )
    payoff = sorted(
        candidates,
        key=lambda item: (
            item.metrics.payoff_ratio or Decimal("-999"),
            item.metrics.completed_trades,
        ),
        reverse=True,
    )
    drawdown = sorted(
        candidates,
        key=lambda item: (
            Decimal("999")
            if item.metrics.maximum_drawdown_pct is None
            else item.metrics.maximum_drawdown_pct,
            -item.metrics.completed_trades,
        ),
    )
    stability = sorted(
        candidates,
        key=lambda item: (
            item.metrics.positive_period_pct or Decimal("-999"),
            item.metrics.completed_trades,
        ),
        reverse=True,
    )
    positive_components = tuple(
        item
        for item in report.component_attribution
        if item.classification.value == "POSITIVE_MARGINAL_VALUE"
    )
    negative_components = tuple(
        item
        for item in report.component_attribution
        if item.classification.value == "NEGATIVE_MARGINAL_VALUE"
    )
    lines = [
        "Project Alpha Strategy and Indicator Combination Backtest Lab",
        f"Experiment: {report.experiment_id}",
        f"Evidence: {report.evidence_class.value}",
        f"Strategies Tested: {report.search_space.total_trials}",
        f"Strongest Research Strategy: {report.strongest_strategy_id or 'unavailable'}",
        "Top Composite Strategies:",
    ]
    lines.extend(
        f"- {item.strategy.strategy_id}: score={_number(item.research_score)}, "
        f"expectancy={_number(item.metrics.expectancy_pct)}%, precision="
        f"{_number(item.metrics.precision_pct)}%, trades="
        f"{item.metrics.completed_trades}"
        for item in candidates[:top]
    )
    lines.append("Highest Precision Strategies:")
    lines.extend(
        f"- {item.strategy.strategy_id}: precision="
        f"{_number(item.metrics.precision_pct)}%, trades="
        f"{item.metrics.completed_trades}"
        for item in precision[: min(5, top)]
    )
    lines.append("Highest Net Expectancy Strategies:")
    lines.extend(
        f"- {item.strategy.strategy_id}: expectancy="
        f"{_number(item.metrics.expectancy_pct)}%, drawdown="
        f"{_number(item.metrics.maximum_drawdown_pct)}%, trades="
        f"{item.metrics.completed_trades}"
        for item in expectancy[: min(5, top)]
    )
    lines.append("Best Payoff / Risk-Reward Strategies:")
    lines.extend(
        f"- {item.strategy.strategy_id}: payoff="
        f"{_number(item.metrics.payoff_ratio)}, average R="
        f"{_number(item.metrics.average_r_multiple)}, trades="
        f"{item.metrics.completed_trades}"
        for item in payoff[: min(5, top)]
    )
    lines.append("Lowest Drawdown Strategies:")
    lines.extend(
        f"- {item.strategy.strategy_id}: drawdown="
        f"{_number(item.metrics.maximum_drawdown_pct)}%, expectancy="
        f"{_number(item.metrics.expectancy_pct)}%, trades="
        f"{item.metrics.completed_trades}"
        for item in drawdown[: min(5, top)]
    )
    lines.append("Most Stable Strategies:")
    lines.extend(
        f"- {item.strategy.strategy_id}: positive years="
        f"{_number(item.metrics.positive_period_pct)}%, years="
        f"{item.metrics.years_represented}, adjusted p="
        f"{_number(_adjusted_p(item))}"
        for item in stability[: min(5, top)]
    )
    lines.append("Indicator Attribution Summary:")
    lines.append(
        "- Positive marginal associations: "
        + (
            "none"
            if not positive_components
            else ", ".join(sorted({item.component_id for item in positive_components}))
        )
    )
    lines.append(
        "- Negative marginal associations: "
        + (
            "none"
            if not negative_components
            else ", ".join(sorted({item.component_id for item in negative_components}))
        )
    )
    lines.append("Benchmark Summary:")
    lines.extend(
        f"- {item.strategy.family}: expectancy="
        f"{_number(item.metrics.expectancy_pct)}%, precision="
        f"{_number(item.metrics.precision_pct)}%, trades="
        f"{item.metrics.completed_trades}"
        for item in benchmarks
    )
    top_result = candidates[0] if candidates else None
    if top_result is not None:
        lines.extend(
            (
                "Top Strategy Time Stability: "
                f"{len(top_result.timeline.annual)} annual periods, "
                f"{len(top_result.timeline.rolling_20)} rolling 20-trade windows, "
                f"{len(top_result.timeline.rolling_50)} rolling 50-trade windows.",
                "Configured Cost Impact: gross expectancy "
                f"{_number(top_result.metrics.gross_expectancy_pct)}% versus net "
                f"{_number(top_result.metrics.expectancy_pct)}%.",
            )
        )
    lines.extend(
        (
            f"Final Conclusion: {report.final_conclusion}",
            f"Highest-Value Missing Evidence: {report.highest_value_evidence_gap}",
            "No strategy was promoted, no threshold changed, and no capital was "
            "allocated.",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return tuple(lines)


def _number(value: Decimal | None) -> str:
    return "NOT_ESTIMABLE" if value is None else str(value)


def _adjusted_p(item: LabStrategyResult) -> Decimal | None:
    return None if item.robustness is None else item.robustness.adjusted_p_value


__all__ = [
    "render_attribution",
    "render_backtest",
    "render_comparison",
    "render_generation",
    "render_inventory",
    "render_leaderboard",
    "render_report",
    "render_robustness",
    "render_timeline",
]
