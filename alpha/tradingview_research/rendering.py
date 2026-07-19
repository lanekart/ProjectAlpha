"""Investor-readable rendering for TRL evidence and governance."""

from __future__ import annotations

from decimal import Decimal

from alpha.tradingview_research.models import (
    ComparisonReport,
    DistributionStatistic,
    PromotionAssessment,
    RankedCandidate,
    SectorResearchSummary,
    TradingViewExperiment,
    UniverseDistribution,
)


def render_experiment_report(
    experiment: TradingViewExperiment,
    comparison: ComparisonReport,
    promotion: PromotionAssessment,
) -> str:
    enabled_indicators = tuple(
        item.indicator.value for item in experiment.treatment.indicators if item.enabled
    )
    enabled_strategies = tuple(
        item.strategy.value for item in experiment.treatment.strategies if item.enabled
    )
    lines = [
        "TradingView Research Laboratory Report",
        f"Experiment ID: {experiment.experiment_id}",
        f"Title: {experiment.title}",
        f"Purpose: {experiment.purpose}",
        f"Alpha Baseline: {experiment.baseline.configuration_id}",
        f"Treatment: {experiment.treatment.configuration_id}",
        f"Indicators Enabled: {_joined(enabled_indicators)}",
        f"Strategies Enabled: {_joined(enabled_strategies)}",
        f"Combination: {experiment.treatment.combination_mode.value}",
        f"Stop: {experiment.treatment.stop_model}",
        f"Exit: {experiment.treatment.exit_model}",
        "Timeframes: "
        f"{experiment.treatment.trend_timeframe} / "
        f"{experiment.treatment.setup_timeframe} / "
        f"{experiment.treatment.entry_timeframe}",
        "",
        "Measured Comparison",
        f"Matched Cohorts: {len(comparison.cohorts)}",
        f"Improved: {comparison.improved_cohorts}",
        f"Unchanged: {comparison.unchanged_cohorts}",
        f"Worse: {comparison.worse_cohorts}",
        f"Insufficient: {comparison.insufficient_cohorts}",
        "Weighted Expectancy Improvement: "
        f"{_number(comparison.weighted_expectancy_improvement)}",
        "Weighted Drawdown Improvement: "
        f"{_number(comparison.weighted_drawdown_improvement)}",
    ]
    for cohort in comparison.cohorts:
        expectancy = cohort.delta("expectancy")
        drawdown = cohort.delta("maximum_drawdown_pct")
        profit_factor = cohort.delta("profit_factor")
        lines.append(
            "Cohort: "
            + " / ".join(cohort.population_key[:3])
            + f" | Trades {cohort.baseline_trades}->{cohort.treatment_trades}"
            + " | Expectancy Δ "
            + _number(expectancy.improvement if expectancy else None)
            + " | Drawdown improvement "
            + _number(drawdown.improvement if drawdown else None)
            + " | Profit factor delta "
            + _number(profit_factor.improvement if profit_factor else None)
            + f" | {cohort.outcome.value}"
        )
    lines.extend(
        (
            "",
            "Candidate Promotion",
            f"Decision: {promotion.decision.value}",
            f"Promote: {'YES' if promotion.promote else 'NO'}",
            "Failed Gates: "
            + _joined(tuple(item.value for item in promotion.failed_reasons)),
            f"Reason: {promotion.explanation}",
            "Next Stage: Alpha replay, walk-forward, and warehouse validation only.",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return "\n".join(lines) + "\n"


def render_ranking(rows: tuple[RankedCandidate, ...]) -> str:
    lines = [
        "TRL Candidate Improvement Ranking",
        f"Experiments: {len(rows)}",
    ]
    if not rows:
        lines.append("No measured TradingView experiments are registered.")
    for row in rows:
        lines.append(
            f"{row.rank}. {row.experiment_id} | {row.promotion_decision.value} | "
            f"cohorts={row.matched_cohorts} | improved={row.improved_cohorts} | "
            f"expectancy_delta={_number(row.weighted_expectancy_improvement)} | "
            f"drawdown_improvement={_number(row.weighted_drawdown_improvement)} | "
            f"primary_rejection="
            f"{row.primary_rejection.value if row.primary_rejection else 'none'}"
        )
    lines.append("PRODUCTION_INFLUENCE=false")
    return "\n".join(lines) + "\n"


def render_sector_summaries(rows: tuple[SectorResearchSummary, ...]) -> str:
    lines = ["TRL Sector Laboratory", f"Sector Cohorts: {len(rows)}"]
    if not rows:
        lines.append("No matched sector evidence is available.")
    for row in rows:
        lines.append(
            f"{row.partition.value} | {row.sector} | "
            f"symbols={len(row.symbols)} | trades={row.treatment_trades} | "
            f"win_rate={_number(row.win_rate_pct)} | "
            f"profit_factor={_number(row.profit_factor)} | "
            f"expectancy={_number(row.expectancy)} | "
            f"recommendation={row.recommendation.value}"
        )
    lines.append("PRODUCTION_INFLUENCE=false")
    return "\n".join(lines) + "\n"


def render_universe_distribution(row: UniverseDistribution) -> str:
    lines = [
        "TRL Symbol Laboratory",
        f"Partition: {row.partition.value}",
        f"Observation Role: {row.role.value}",
        f"Symbols: {len(row.symbols)}",
        f"Observations: {row.observations}",
        f"Trades: {row.trade_count}",
        _distribution_line("Win Rate", row.win_rate_pct),
        _distribution_line("Profit Factor", row.profit_factor),
        _distribution_line("Expectancy", row.expectancy),
        "PRODUCTION_INFLUENCE=false",
    ]
    return "\n".join(lines) + "\n"


def comparison_as_dict(
    experiment: TradingViewExperiment,
    comparison: ComparisonReport,
    promotion: PromotionAssessment,
) -> dict[str, object]:
    return {
        "baseline_configuration_id": experiment.baseline.configuration_id,
        "cohorts": [
            {
                "baseline_trades": cohort.baseline_trades,
                "deltas": [
                    {
                        "baseline": _json_number(delta.baseline),
                        "higher_is_better": delta.higher_is_better,
                        "improvement": _json_number(delta.improvement),
                        "metric": delta.metric,
                        "treatment": _json_number(delta.treatment),
                    }
                    for delta in cohort.deltas
                ],
                "outcome": cohort.outcome.value,
                "population_key": list(cohort.population_key),
                "treatment_trades": cohort.treatment_trades,
            }
            for cohort in comparison.cohorts
        ],
        "experiment_id": experiment.experiment_id,
        "promote": promotion.promote,
        "promotion_decision": promotion.decision.value,
        "promotion_failed_reasons": [item.value for item in promotion.failed_reasons],
        "production_influence": False,
        "treatment_configuration_id": experiment.treatment.configuration_id,
        "weighted_drawdown_improvement": _json_number(
            comparison.weighted_drawdown_improvement
        ),
        "weighted_expectancy_improvement": _json_number(
            comparison.weighted_expectancy_improvement
        ),
    }


def _number(value: Decimal | int | None) -> str:
    return "unavailable" if value is None else str(value)


def _json_number(value: Decimal | int | None) -> str | int | None:
    return str(value) if isinstance(value, Decimal) else value


def _joined(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "none"


def _distribution_line(label: str, row: DistributionStatistic) -> str:
    return (
        f"{label}: min={_number(row.minimum)} | median={_number(row.median)} | "
        f"max={_number(row.maximum)} | available={row.available_count} | "
        f"missing={row.missing_count}"
    )
