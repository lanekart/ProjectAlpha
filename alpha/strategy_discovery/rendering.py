from __future__ import annotations

from collections import Counter
from decimal import Decimal

from alpha.strategy_discovery.models import (
    DiscoveryDataset,
    FeatureDefinition,
    RobustnessResult,
    SearchSpaceManifest,
    StrategyDiscoveryReport,
    StrategyEvaluation,
    StrategyLeaderboardEntry,
    WalkForwardFold,
)


def render_discovery(
    dataset: DiscoveryDataset,
    features: tuple[FeatureDefinition, ...],
    manifest: SearchSpaceManifest,
) -> tuple[str, ...]:
    quarantined = tuple(item for item in features if not item.usable_for_discovery)
    lines = [
        "Strategy Discovery",
        f"Dataset: {dataset.dataset_version}",
        f"Historical Truth: {dataset.population_class.value}",
        f"Included Rows: {dataset.row_count}",
        f"Excluded Rows: {len(dataset.exclusions)}",
        f"Strategies Generated: {manifest.total_variants}",
        f"Search-Space Hash: {manifest.search_space_hash}",
        "Feature Manifest:",
    ]
    lines.extend(
        f"- {item.name}: {'USABLE' if item.usable_for_discovery else 'QUARANTINED'}"
        for item in features
    )
    lines.append("Quarantined Features:")
    lines.extend(
        f"- {item.name}: {item.quarantine_reason or item.validity.value}"
        for item in quarantined
    )
    lines.append("Strategy Families:")
    lines.extend(
        f"- {family}: {count} variants"
        for family, count in manifest.family_variant_counts.items()
    )
    lines.append("PRODUCTION_INFLUENCE=false")
    return tuple(lines)


def render_walk_forward(
    dataset: DiscoveryDataset,
    folds: tuple[WalkForwardFold, ...],
    evaluations: tuple[StrategyEvaluation, ...],
) -> tuple[str, ...]:
    lines = [
        "Chronological Walk-Forward Validation",
        f"Dataset: {dataset.dataset_version}",
        f"Historical Truth: {dataset.population_class.value}",
        f"Walk-Forward Folds: {len(folds)}",
    ]
    for fold in folds:
        lines.append(
            f"- {fold.fold_id}: train {fold.training_start} to {fold.training_end}; "
            f"validate {fold.validation_start} to {fold.validation_end}; "
            f"purge {fold.purge_gap_days} days"
        )
    best = sorted(evaluations, key=_evaluation_key, reverse=True)[:5]
    lines.append("Validation Leaders Before Holdout:")
    lines.extend(_evaluation_line(item) for item in best)
    lines.extend(("Holdout: untouched by this command", "PRODUCTION_INFLUENCE=false"))
    return tuple(lines)


def render_evaluation(report: StrategyDiscoveryReport) -> tuple[str, ...]:
    lines = [
        "Strategy Evaluation",
        f"Dataset: {report.dataset.dataset_version}",
        f"Historical Truth: {report.dataset.population_class.value}",
        "Objective: expectancy after explicit transaction costs and slippage",
        "Top Evaluations:",
    ]
    lines.extend(_leaderboard_line(item) for item in report.leaderboard[:10])
    lines.append("Benchmarks:")
    lines.extend(_leaderboard_line(item) for item in report.benchmark_entries)
    lines.extend(
        (
            "Broad-Market Benchmark: unavailable; the candidate ledger has no "
            "valid point-in-time aligned benchmark-return series.",
            f"Holdout Accesses Evaluated: {_holdout_count(report)} strategies",
            f"Final Decision: {report.decision}",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return tuple(lines)


def render_robustness(report: StrategyDiscoveryReport) -> tuple[str, ...]:
    lines = ["Strategy Robustness", f"Dataset: {report.dataset.dataset_version}"]
    for entry in report.leaderboard[:10]:
        lines.extend(
            _robustness_lines(entry.strategy.strategy_version, entry.robustness)
        )
    lines.extend(
        (
            "Unavailable stress tests are reported, never inferred.",
            f"Final Decision: {report.decision}",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return tuple(lines)


def render_leaderboard(report: StrategyDiscoveryReport) -> tuple[str, ...]:
    lines = [
        "Strategy Generalisation Leaderboard",
        f"Dataset: {report.dataset.dataset_version}",
        f"Population: {report.dataset.population_class.value}",
    ]
    lines.extend(_leaderboard_line(item) for item in report.leaderboard[:20])
    lines.append("Benchmark Comparison:")
    lines.extend(_leaderboard_line(item) for item in report.benchmark_entries)
    lines.extend((f"Final Decision: {report.decision}", "PRODUCTION_INFLUENCE=false"))
    return tuple(lines)


def render_publication(
    report: StrategyDiscoveryReport,
    *,
    published_cohort: str | None,
) -> tuple[str, ...]:
    if published_cohort is None:
        return (
            "Shadow Strategy Publication",
            report.decision,
            "No strategy specification was published.",
            "APPROVAL_POLICY_V1 and existing forward cohorts are unchanged.",
            "PRODUCTION_INFLUENCE=false",
        )
    return (
        "Shadow Strategy Publication",
        report.decision,
        f"Published Cohort: {published_cohort}",
        "Mode: immutable shadow validation only; no capital or broker execution.",
        "APPROVAL_POLICY_V1 and existing forward cohorts are unchanged.",
        "PRODUCTION_INFLUENCE=false",
    )


def render_discovery_report(report: StrategyDiscoveryReport) -> tuple[str, ...]:
    counts = Counter(item.classification.value for item in report.leaderboard)
    lines = [
        "Walk-Forward Strategy Discovery Report",
        f"Generated At: {report.generated_at.isoformat()}",
        f"Dataset: {report.dataset.dataset_version}",
        f"Historical Truth: {report.dataset.population_class.value}",
        f"Discovery Population: {report.dataset.row_count}",
        f"Excluded Population: {len(report.dataset.exclusions)}",
        f"Strategies Tested: {report.search_manifest.total_variants}",
        f"Chronological Folds: {len(report.folds)}",
        "Classification Summary:",
    ]
    lines.extend(f"- {name}: {count}" for name, count in sorted(counts.items()))
    lines.append("Top Candidate Leaderboard:")
    lines.extend(_leaderboard_line(item) for item in report.leaderboard[:10])
    lines.append("Dominant Failure Reasons:")
    lines.extend(f"- {reason}" for reason in report.dominant_failure_reasons)
    lines.extend(
        (
            "Current Forward Evidence:",
            f"- {report.current_forward_evidence}",
            "Broad-Market Benchmark:",
            "- Unavailable; no valid point-in-time benchmark return is aligned to "
            "the candidate outcomes.",
            "Highest-Value Evidence Gap:",
            f"- {report.highest_value_evidence_gap}",
            f"Final Strategy Decision: {report.decision}",
            "APPROVAL_POLICY_V1 remains unchanged.",
            "PRODUCTION_INFLUENCE=false",
        )
    )
    return tuple(lines)


def _evaluation_line(item: StrategyEvaluation) -> str:
    metrics = item.validation_metrics
    return (
        f"- {item.strategy.strategy_version} {item.strategy.name}: "
        f"trades={metrics.completed_trades}; "
        f"expectancy={_number(metrics.expectancy_pct)}%; "
        f"profit factor={_number(metrics.profit_factor)}"
    )


def _leaderboard_line(item: StrategyLeaderboardEntry) -> str:
    validation = item.evaluation.validation_metrics
    holdout = item.evaluation.holdout_metrics
    return (
        f"{item.rank}. {item.strategy.strategy_version} | {item.strategy.name} | "
        f"{item.classification.value} | validation trades="
        f"{validation.completed_trades}, "
        f"expectancy={_number(validation.expectancy_pct)}%, holdout expectancy="
        f"{_number(None if holdout is None else holdout.expectancy_pct)}% | "
        f"conditions={_conditions(item)}"
    )


def _robustness_lines(version: str, item: RobustnessResult) -> tuple[str, ...]:
    weaknesses = "; ".join(item.weaknesses) if item.weaknesses else "none observed"
    return (
        f"- {version}: perturbation={_yes(item.parameter_perturbation_passed)}, "
        f"ablation={_yes(item.feature_ablation_passed)}, "
        f"cost stress={_yes(item.cost_stress_passed)}",
        f"  delayed entry={item.delayed_entry_status}; "
        f"stop gap={item.stop_gap_status}; "
        f"weaknesses={weaknesses}",
    )


def _evaluation_key(item: StrategyEvaluation) -> tuple[Decimal, int]:
    return (
        item.validation_metrics.expectancy_pct or Decimal("-Infinity"),
        item.validation_metrics.completed_trades,
    )


def _holdout_count(report: StrategyDiscoveryReport) -> int:
    return sum(1 for item in report.leaderboard if item.evaluation.holdout_metrics)


def _conditions(item: StrategyLeaderboardEntry) -> str:
    conditions = item.strategy.conditions
    if not conditions:
        return "frozen benchmark semantics"
    return " and ".join(
        f"{condition.feature_name} {condition.operator.value.lower()} {condition.value}"
        for condition in conditions
    )


def _number(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _yes(value: bool) -> str:
    return "PASS" if value else "FAIL"


__all__ = [
    "render_discovery",
    "render_discovery_report",
    "render_evaluation",
    "render_leaderboard",
    "render_publication",
    "render_robustness",
    "render_walk_forward",
]
