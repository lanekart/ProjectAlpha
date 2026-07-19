from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from alpha.strategy_discovery.models import (
    DiscoveryDataset,
    DiscoveryRow,
    HistoricalTruthClass,
)
from alpha.strategy_lab.models import (
    EvidenceLabel,
    ExecutionAssumptionProfile,
    LabEvidenceClass,
    LabStrategyResult,
    LabStrategySpecification,
    StrategyClassification,
)
from alpha.strategy_lab.performance_metrics import PerformanceMetricsEngine
from alpha.strategy_lab.robustness_analysis import LabRobustnessAnalyzer
from alpha.strategy_lab.time_series_analysis import TimeSeriesAnalysis


@dataclass(frozen=True, slots=True)
class BacktestRequest:
    start_date: date | None = None
    end_date: date | None = None
    symbols: tuple[str, ...] = ()
    setups: tuple[str, ...] = ()
    evidence_class: LabEvidenceClass | None = None


@dataclass(frozen=True, slots=True)
class BacktestRun:
    source_rows: int
    eligible_rows: tuple[DiscoveryRow, ...]
    results: tuple[LabStrategyResult, ...]


class StrategyLabBacktestEngine:
    """Evaluate bounded strategies on one shared point-in-time population."""

    def __init__(
        self,
        *,
        metrics: PerformanceMetricsEngine | None = None,
        timeline: TimeSeriesAnalysis | None = None,
        robustness: LabRobustnessAnalyzer | None = None,
    ) -> None:
        self.metrics = metrics or PerformanceMetricsEngine()
        self.timeline = timeline or TimeSeriesAnalysis(self.metrics)
        self.robustness = robustness or LabRobustnessAnalyzer()

    def run(
        self,
        *,
        dataset: DiscoveryDataset,
        strategies: tuple[LabStrategySpecification, ...],
        profile: ExecutionAssumptionProfile,
        request: BacktestRequest | None = None,
    ) -> BacktestRun:
        settings = request or BacktestRequest()
        rows = _filter_rows(dataset.rows, settings)
        initial: list[LabStrategyResult] = []
        for strategy in strategies:
            metrics = self.metrics.evaluate(
                strategy=strategy,
                rows=rows,
                profile=profile,
            )
            selected = self.metrics.selected_rows(strategy, rows)
            timeline = self.timeline.analyze(
                strategy=strategy,
                rows=rows,
                profile=profile,
            )
            score, breakdown = _research_score(metrics)
            evidence_label = _evidence_label(dataset, metrics.completed_trades)
            classification, reasons = _initial_classification(
                dataset=dataset,
                result_count=metrics.completed_trades,
                expectancy=metrics.expectancy_pct,
            )
            initial.append(
                LabStrategyResult(
                    strategy=strategy,
                    metrics=metrics,
                    evidence_label=evidence_label,
                    classification=classification,
                    classification_reasons=reasons,
                    research_score=score,
                    score_breakdown=breakdown,
                    selected_candidate_ids=tuple(
                        item.candidate_id for item in selected
                    ),
                    timeline=timeline,
                )
            )
        by_id = {item.candidate_id: item for item in rows}
        final: list[LabStrategyResult] = []
        for item in initial:
            robustness = self.robustness.analyze(
                result=item,
                rows_by_id=by_id,
                profile=profile,
                hypotheses_tested=sum(
                    1 for result in initial if not result.strategy.benchmark
                ),
            )
            classification = item.classification
            reason_list = list(item.classification_reasons)
            if (
                classification
                in {
                    StrategyClassification.RECONSTRUCTED_RESEARCH_ONLY,
                    StrategyClassification.WALK_FORWARD_CANDIDATE,
                }
                and robustness.overfit
            ):
                classification = StrategyClassification.OVERFIT
                reason_list.extend(robustness.weaknesses)
            final.append(
                replace(
                    item,
                    robustness=robustness,
                    classification=classification,
                    classification_reasons=tuple(dict.fromkeys(reason_list)),
                )
            )
        return BacktestRun(
            source_rows=len(dataset.rows),
            eligible_rows=rows,
            results=tuple(final),
        )


def _filter_rows(
    rows: tuple[DiscoveryRow, ...], request: BacktestRequest
) -> tuple[DiscoveryRow, ...]:
    symbols = {item.strip().upper() for item in request.symbols}
    setups = {item.strip().upper() for item in request.setups}
    return tuple(
        item
        for item in rows
        if (
            request.start_date is None
            or item.candidate_timestamp.date() >= request.start_date
        )
        and (
            request.end_date is None
            or item.candidate_timestamp.date() <= request.end_date
        )
        and (not symbols or item.symbol in symbols)
        and (not setups or (item.setup or "UNAVAILABLE").upper() in setups)
        and (
            request.evidence_class is None
            or request.evidence_class is LabEvidenceClass.RECONSTRUCTED
        )
    )


def _evidence_label(dataset: DiscoveryDataset, completed: int) -> EvidenceLabel:
    if completed < 30:
        return EvidenceLabel.INSUFFICIENT_SAMPLE
    if dataset.population_class is HistoricalTruthClass.RECONSTRUCTED:
        return EvidenceLabel.RECONSTRUCTED_RESEARCH_ONLY
    if dataset.population_class is HistoricalTruthClass.AUTHORITATIVE:
        return EvidenceLabel.AUTHORITATIVE
    return EvidenceLabel.PROVISIONAL


def _initial_classification(
    *,
    dataset: DiscoveryDataset,
    result_count: int,
    expectancy: Decimal | None,
) -> tuple[StrategyClassification, tuple[str, ...]]:
    if result_count < 30:
        return (
            StrategyClassification.INSUFFICIENT_SAMPLE,
            ("Fewer than 30 completed trades satisfy the strategy.",),
        )
    if expectancy is None or expectancy < Decimal("0"):
        return (
            StrategyClassification.NEGATIVE_EXPECTANCY,
            ("Net expectancy after configured costs is negative or unavailable.",),
        )
    if expectancy <= Decimal("0.10"):
        return (
            StrategyClassification.NO_MATERIAL_EDGE,
            (
                "Net expectancy does not exceed the explicit 0.10% research "
                "materiality band.",
            ),
        )
    if dataset.population_class is HistoricalTruthClass.RECONSTRUCTED:
        return (
            StrategyClassification.RECONSTRUCTED_RESEARCH_ONLY,
            (
                "The source population is reconstructed rather than authoritative.",
                "The strategy cannot be promoted from this evidence class.",
            ),
        )
    return (
        StrategyClassification.WALK_FORWARD_CANDIDATE,
        ("Positive material expectancy passed initial sample checks.",),
    )


def _research_score(
    metrics: object,
) -> tuple[Decimal | None, dict[str, Decimal | None]]:
    from alpha.strategy_lab.models import StrategyPerformanceMetrics

    if not isinstance(metrics, StrategyPerformanceMetrics):
        raise TypeError("strategy metrics required")
    if metrics.completed_trades == 0:
        return None, {
            "expectancy": None,
            "profit_factor": None,
            "drawdown": None,
            "stability": None,
            "sample": Decimal("0"),
            "cost_robustness": None,
            "concentration_penalty": None,
        }
    expectancy = _clamp(
        (metrics.expectancy_pct or Decimal("-5")) / Decimal("5") * Decimal("25"),
        Decimal("0"),
        Decimal("25"),
    )
    profit_factor = _clamp(
        (metrics.profit_factor or Decimal("0")) / Decimal("2") * Decimal("15"),
        Decimal("0"),
        Decimal("15"),
    )
    drawdown = (
        None
        if metrics.maximum_drawdown_pct is None
        else _clamp(
            Decimal("15")
            * (Decimal("1") - metrics.maximum_drawdown_pct / Decimal("25")),
            Decimal("0"),
            Decimal("15"),
        )
    )
    stability = (
        None
        if metrics.positive_period_pct is None
        else metrics.positive_period_pct / Decimal("100") * Decimal("20")
    )
    sample = min(
        Decimal("15"),
        Decimal(metrics.completed_trades) / Decimal("100") * Decimal("15"),
    )
    cost_robustness = (
        Decimal("10")
        if metrics.expectancy_pct is not None and metrics.expectancy_pct > Decimal("0")
        else Decimal("0")
    )
    concentration = max(
        metrics.symbol_concentration_pct or Decimal("0"),
        metrics.largest_winner_contribution_pct or Decimal("0"),
    )
    penalty = _clamp(
        (concentration - Decimal("25")) / Decimal("75") * Decimal("20"),
        Decimal("0"),
        Decimal("20"),
    )
    components = {
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "drawdown": drawdown,
        "stability": stability,
        "sample": sample,
        "cost_robustness": cost_robustness,
        "concentration_penalty": penalty,
        "sample_sufficiency_multiplier": min(
            Decimal("1"), Decimal(metrics.completed_trades) / Decimal("30")
        ),
    }
    positive = sum(
        (
            value
            for key, value in components.items()
            if value is not None
            and key not in {"concentration_penalty", "sample_sufficiency_multiplier"}
        ),
        start=Decimal("0"),
    )
    multiplier = components["sample_sufficiency_multiplier"] or Decimal("0")
    return ((positive - penalty) * multiplier).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    ), components


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return max(low, min(high, value))


__all__ = ["BacktestRequest", "BacktestRun", "StrategyLabBacktestEngine"]
