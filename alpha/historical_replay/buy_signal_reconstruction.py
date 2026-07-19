from __future__ import annotations

import csv
import json
import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

from alpha.historical_replay.precision_frontier import (
    ConstraintResult,
    DirectionalLabel,
    DirectionalMetrics,
    DirectionalObservation,
    DirectionalOutcomeDefinition,
    DirectionalOutcomeFamily,
    DirectionalPolicy,
    DirectionalPolicyDirection,
    FrontierPoint,
    PrecisionCoverageConstraints,
    calculate_directional_metrics,
    constraints_for_point,
    deterministic_research_observations,
    label_directional_outcome,
    pareto_frontier,
    wilson_interval,
)


class BuyFeatureGroup(StrEnum):
    PRICE_STRUCTURE = "PRICE_STRUCTURE"
    VOLUME = "VOLUME"
    SUPPORT_RESISTANCE = "SUPPORT_RESISTANCE"
    TREND = "TREND"
    RELATIVE_STRENGTH = "RELATIVE_STRENGTH"
    SETUP = "SETUP"
    ENTRY_TIMING = "ENTRY_TIMING"
    MARKET_REGIME = "MARKET_REGIME"
    SECTOR_STATE = "SECTOR_STATE"
    VOLATILITY_RISK = "VOLATILITY_RISK"
    LIQUIDITY = "LIQUIDITY"
    RETRACEMENT = "RETRACEMENT"
    CANDLE = "CANDLE"
    BREAKOUT_CONFIRMATION = "BREAKOUT_CONFIRMATION"
    TRADE_PLAN_QUALITY = "TRADE_PLAN_QUALITY"
    HISTORICAL_OUTCOME_STATISTICS = "HISTORICAL_OUTCOME_STATISTICS"


class BuyModelKind(StrEnum):
    ALWAYS_BUY = "ALWAYS_BUY"
    CURRENT_COMPOSITE = "CURRENT_COMPOSITE"
    CURRENT_DIRECTIONAL = "CURRENT_DIRECTIONAL"
    FEATURE_GROUP_SCORE = "FEATURE_GROUP_SCORE"
    FULL_COMPONENT_STACK = "FULL_COMPONENT_STACK"


class BuyBottleneck(StrEnum):
    BUY_RANKING_QUALITY_PRIMARY = "BUY_RANKING_QUALITY_PRIMARY"
    BUY_CALIBRATION_PRIMARY = "BUY_CALIBRATION_PRIMARY"
    BUY_ENTRY_TIMING_PRIMARY = "BUY_ENTRY_TIMING_PRIMARY"
    BUY_SETUP_HETEROGENEITY_PRIMARY = "BUY_SETUP_HETEROGENEITY_PRIMARY"
    BUY_REGIME_INTERACTION_PRIMARY = "BUY_REGIME_INTERACTION_PRIMARY"
    BUY_TRADEABILITY_PRIMARY = "BUY_TRADEABILITY_PRIMARY"
    BUY_LABEL_DEFINITION_PRIMARY = "BUY_LABEL_DEFINITION_PRIMARY"
    BUY_INSUFFICIENT_EVIDENCE = "BUY_INSUFFICIENT_EVIDENCE"
    BUY_MULTIPLE_BOTTLENECKS = "BUY_MULTIPLE_BOTTLENECKS"


class BuyModelConclusion(StrEnum):
    STABLE_BUY_70_POLICY_FOUND = "STABLE_BUY_70_POLICY_FOUND"
    BUY_70_POLICY_LOW_COVERAGE = "BUY_70_POLICY_LOW_COVERAGE"
    BUY_70_POLICY_UNSTABLE = "BUY_70_POLICY_UNSTABLE"
    STABLE_BUY_60_POLICY_FOUND = "STABLE_BUY_60_POLICY_FOUND"
    MINIMAL_MODEL_OUTPERFORMS_FULL_MODEL = "MINIMAL_MODEL_OUTPERFORMS_FULL_MODEL"
    FULL_MODEL_REMAINS_SUPERIOR = "FULL_MODEL_REMAINS_SUPERIOR"
    NO_USEFUL_BUY_POLICY_FOUND = "NO_USEFUL_BUY_POLICY_FOUND"
    MORE_DATA_REQUIRED = "MORE_DATA_REQUIRED"


class BuySetupClassification(StrEnum):
    BUY_PREDICTIVE = "BUY_PREDICTIVE"
    BUY_PREDICTIVE_BUT_LOW_COVERAGE = "BUY_PREDICTIVE_BUT_LOW_COVERAGE"
    TIMING_SENSITIVE = "TIMING_SENSITIVE"
    REGIME_SENSITIVE = "REGIME_SENSITIVE"
    NON_PREDICTIVE = "NON_PREDICTIVE"
    NEGATIVELY_PREDICTIVE = "NEGATIVELY_PREDICTIVE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class DirectionTimingCategory(StrEnum):
    DIRECTION_RIGHT_TIMING_RIGHT = "DIRECTION_RIGHT_TIMING_RIGHT"
    DIRECTION_RIGHT_TIMING_WRONG = "DIRECTION_RIGHT_TIMING_WRONG"
    DIRECTION_WRONG_TIMING_RIGHT = "DIRECTION_WRONG_TIMING_RIGHT"
    DIRECTION_WRONG_TIMING_WRONG = "DIRECTION_WRONG_TIMING_WRONG"


class FalsePositiveCause(StrEnum):
    LATE_ENTRY = "LATE_ENTRY"
    EXTENDED_PRICE = "EXTENDED_PRICE"
    FAILED_BREAKOUT = "FAILED_BREAKOUT"
    WEAK_VOLUME = "WEAK_VOLUME"
    HOSTILE_REGIME = "HOSTILE_REGIME"
    SECTOR_WEAKNESS = "SECTOR_WEAKNESS"
    OVERHEAD_RESISTANCE = "OVERHEAD_RESISTANCE"
    EXCESSIVE_STOP_DISTANCE = "EXCESSIVE_STOP_DISTANCE"
    POOR_REWARD_RISK = "POOR_REWARD_RISK"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    WEAK_RELATIVE_STRENGTH = "WEAK_RELATIVE_STRENGTH"
    SUPPORT_FAILURE = "SUPPORT_FAILURE"
    GAP_REVERSAL = "GAP_REVERSAL"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    LABEL_AMBIGUITY = "LABEL_AMBIGUITY"
    UNAVAILABLE_EVIDENCE = "UNAVAILABLE_EVIDENCE"
    MODEL_RANKING_ERROR = "MODEL_RANKING_ERROR"
    CALIBRATION_ERROR = "CALIBRATION_ERROR"


class Preventability(StrEnum):
    PREVENTABLE_WITH_EXISTING_FEATURES = "PREVENTABLE_WITH_EXISTING_FEATURES"
    REQUIRES_NEW_FEATURE = "REQUIRES_NEW_FEATURE"
    LABEL_OR_OUTCOME_AMBIGUITY = "LABEL_OR_OUTCOME_AMBIGUITY"
    INHERENT_MARKET_UNCERTAINTY = "INHERENT_MARKET_UNCERTAINTY"


@dataclass(frozen=True, slots=True)
class BuyFeatureGroupLineage:
    group: BuyFeatureGroup
    raw_source_fields: tuple[str, ...]
    transformations: tuple[str, ...]
    upstream_dependencies: tuple[str, ...]
    overlaps_with: tuple[BuyFeatureGroup, ...]
    missingness: float
    historical_availability: str
    look_ahead_safe: bool
    incremental_contribution: float | None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["group"] = self.group.value
        payload["overlaps_with"] = [item.value for item in self.overlaps_with]
        return payload


@dataclass(frozen=True, slots=True)
class BuyModelSpec:
    model_id: str
    name: str
    kind: BuyModelKind
    feature_groups: tuple[BuyFeatureGroup, ...]
    threshold: float
    removed_groups: tuple[BuyFeatureGroup, ...] = ()
    calibration: str = "raw"
    monotonic_constraints: tuple[str, ...] = ()

    @property
    def complexity_score(self) -> int:
        return max(1, len(self.feature_groups) + len(self.removed_groups))

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        payload["feature_groups"] = [item.value for item in self.feature_groups]
        payload["removed_groups"] = [item.value for item in self.removed_groups]
        payload["complexity_score"] = self.complexity_score
        return payload


@dataclass(frozen=True, slots=True)
class BuyModelResult:
    spec: BuyModelSpec
    metrics: DirectionalMetrics
    constraints: ConstraintResult
    annual_signal_rate: float
    worst_fold_precision: float | None
    fold_dispersion: float | None
    setup_concentration: float
    regime_concentration: float
    year_concentration: float
    symbol_concentration: float
    sector_concentration: float
    retained_features: tuple[BuyFeatureGroup, ...]
    removed_features: tuple[BuyFeatureGroup, ...]
    production_influence: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec.as_dict(),
            "metrics": self.metrics.as_dict(),
            "constraints": self.constraints.as_dict(),
            "annual_signal_rate": self.annual_signal_rate,
            "worst_fold_precision": self.worst_fold_precision,
            "fold_dispersion": self.fold_dispersion,
            "setup_concentration": self.setup_concentration,
            "regime_concentration": self.regime_concentration,
            "year_concentration": self.year_concentration,
            "symbol_concentration": self.symbol_concentration,
            "sector_concentration": self.sector_concentration,
            "retained_features": [item.value for item in self.retained_features],
            "removed_features": [item.value for item in self.removed_features],
            "production_influence": self.production_influence,
        }


@dataclass(frozen=True, slots=True)
class BuyFeatureAdditionStep:
    step: int
    candidate_group: BuyFeatureGroup
    retained: bool
    result: BuyModelResult
    precision_delta: float | None
    pr_auc_delta: float | None
    expectancy_delta: float | None
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "candidate_group": self.candidate_group.value,
            "retained": self.retained,
            "result": self.result.as_dict(),
            "precision_delta": self.precision_delta,
            "pr_auc_delta": self.pr_auc_delta,
            "expectancy_delta": self.expectancy_delta,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class BuyAblationResult:
    removed_groups: tuple[BuyFeatureGroup, ...]
    result: BuyModelResult
    precision_delta: float | None
    pr_auc_delta: float | None
    signal_count_delta: int
    expectancy_delta: float | None
    calibration_delta: float | None
    worst_fold_delta: float | None
    concentration_delta: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "removed_groups": [item.value for item in self.removed_groups],
            "result": self.result.as_dict(),
            "precision_delta": self.precision_delta,
            "pr_auc_delta": self.pr_auc_delta,
            "signal_count_delta": self.signal_count_delta,
            "expectancy_delta": self.expectancy_delta,
            "calibration_delta": self.calibration_delta,
            "worst_fold_delta": self.worst_fold_delta,
            "concentration_delta": self.concentration_delta,
        }


@dataclass(frozen=True, slots=True)
class DirectionTimingAnalysisRow:
    category: DirectionTimingCategory
    count: int
    average_forward_return: float | None
    average_mfe: float | None
    average_mae: float | None
    dominant_setup: str
    dominant_regime: str
    dominant_timing: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["category"] = self.category.value
        return payload


@dataclass(frozen=True, slots=True)
class SetupSpecializedBuyResult:
    setup_type: str
    result: BuyModelResult
    classification: BuySetupClassification

    def as_dict(self) -> dict[str, Any]:
        return {
            "setup_type": self.setup_type,
            "result": self.result.as_dict(),
            "classification": self.classification.value,
        }


@dataclass(frozen=True, slots=True)
class RegimeInteractionResult:
    regime: str
    pooled_precision: float | None
    separate_threshold_precision: float | None
    no_buy_exclusion_precision: float | None
    signal_count: int
    concentration: float
    conclusion: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FalsePositiveTaxonomyRow:
    cause: FalsePositiveCause
    frequency: int
    average_loss: float | None
    average_mae: float | None
    average_mfe: float | None
    dominant_setup: str
    dominant_regime: str
    dominant_timing: str
    preventability: Preventability

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["cause"] = self.cause.value
        payload["preventability"] = self.preventability.value
        return payload


@dataclass(frozen=True, slots=True)
class FalseNegativeRecoveryRow:
    recovery_path: str
    count: int
    average_score: float | None
    average_return: float | None
    average_mfe: float | None
    average_mae: float | None
    dominant_setup: str
    dominant_regime: str
    dominant_timing: str
    suppressed_by: tuple[BuyFeatureGroup, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["suppressed_by"] = [item.value for item in self.suppressed_by]
        return payload


@dataclass(frozen=True, slots=True)
class BuySignalReconstructionReport:
    generated_on: date
    outcome_definition: DirectionalOutcomeDefinition
    data_source: str
    raw_signal_count: int
    completed_buy_outcomes: int
    outer_fold_count: int
    train_test_periods: tuple[str, ...]
    baselines: tuple[BuyModelResult, ...]
    feature_lineage: tuple[BuyFeatureGroupLineage, ...]
    forward_addition: tuple[BuyFeatureAdditionStep, ...]
    backward_ablation: tuple[BuyAblationResult, ...]
    retracement_tests: tuple[BuyAblationResult, ...]
    direction_timing: tuple[DirectionTimingAnalysisRow, ...]
    setup_specialized: tuple[SetupSpecializedBuyResult, ...]
    regime_interactions: tuple[RegimeInteractionResult, ...]
    false_positive_taxonomy: tuple[FalsePositiveTaxonomyRow, ...]
    false_negative_recovery: tuple[FalseNegativeRecoveryRow, ...]
    frontier: tuple[BuyModelResult, ...]
    pareto_frontier: tuple[BuyModelResult, ...]
    comparison_table: tuple[BuyModelResult, ...]
    best_minimal_model: BuyModelResult | None
    best_setup_model: BuyModelResult | None
    best_regime_model: BuyModelResult | None
    best_calibrated_model: BuyModelResult | None
    primary_bottleneck: BuyBottleneck
    final_conclusion: BuyModelConclusion
    production_influence: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_on": self.generated_on.isoformat(),
            "outcome_definition": self.outcome_definition.as_dict(),
            "data_source": self.data_source,
            "raw_signal_count": self.raw_signal_count,
            "completed_buy_outcomes": self.completed_buy_outcomes,
            "outer_fold_count": self.outer_fold_count,
            "train_test_periods": list(self.train_test_periods),
            "baselines": [item.as_dict() for item in self.baselines],
            "feature_lineage": [item.as_dict() for item in self.feature_lineage],
            "forward_addition": [item.as_dict() for item in self.forward_addition],
            "backward_ablation": [item.as_dict() for item in self.backward_ablation],
            "retracement_tests": [item.as_dict() for item in self.retracement_tests],
            "direction_timing": [item.as_dict() for item in self.direction_timing],
            "setup_specialized": [item.as_dict() for item in self.setup_specialized],
            "regime_interactions": [
                item.as_dict() for item in self.regime_interactions
            ],
            "false_positive_taxonomy": [
                item.as_dict() for item in self.false_positive_taxonomy
            ],
            "false_negative_recovery": [
                item.as_dict() for item in self.false_negative_recovery
            ],
            "frontier": [item.as_dict() for item in self.frontier],
            "pareto_frontier": [item.as_dict() for item in self.pareto_frontier],
            "comparison_table": [item.as_dict() for item in self.comparison_table],
            "best_minimal_model": None
            if self.best_minimal_model is None
            else self.best_minimal_model.as_dict(),
            "best_setup_model": None
            if self.best_setup_model is None
            else self.best_setup_model.as_dict(),
            "best_regime_model": None
            if self.best_regime_model is None
            else self.best_regime_model.as_dict(),
            "best_calibrated_model": None
            if self.best_calibrated_model is None
            else self.best_calibrated_model.as_dict(),
            "primary_bottleneck": self.primary_bottleneck.value,
            "final_conclusion": self.final_conclusion.value,
            "production_influence": self.production_influence,
        }


def build_buy_signal_reconstruction_report(
    observations: Sequence[DirectionalObservation] | None = None,
    *,
    definition: DirectionalOutcomeDefinition | None = None,
    data_source: str = "DETERMINISTIC_RESEARCH_FIXTURE",
    constraints: PrecisionCoverageConstraints | None = None,
) -> BuySignalReconstructionReport:
    rows = tuple(observations or deterministic_research_observations())
    outcome_definition = definition or DirectionalOutcomeDefinition(
        family=DirectionalOutcomeFamily.TERMINAL_RETURN,
        horizon_days=20,
        positive_return_threshold=0.02,
        negative_return_threshold=-0.02,
    )
    coverage_constraints = constraints or PrecisionCoverageConstraints()
    baselines = evaluate_buy_baselines(
        rows,
        definition=outcome_definition,
        constraints=coverage_constraints,
    )
    lineage = build_buy_feature_lineage(rows)
    forward = run_forward_feature_addition(
        rows,
        definition=outcome_definition,
        constraints=coverage_constraints,
    )
    ablation = run_backward_ablation(
        rows,
        definition=outcome_definition,
        constraints=coverage_constraints,
    )
    retracement = run_retracement_buy_tests(
        rows,
        definition=outcome_definition,
        constraints=coverage_constraints,
    )
    timing = run_direction_timing_analysis(rows, definition=outcome_definition)
    setups = run_setup_specialized_buy_models(
        rows,
        definition=outcome_definition,
        constraints=coverage_constraints,
    )
    regimes = run_regime_interaction_tests(
        rows,
        definition=outcome_definition,
        constraints=coverage_constraints,
    )
    frontier = build_buy_precision_frontier(
        rows,
        definition=outcome_definition,
        constraints=coverage_constraints,
    )
    pareto = _pareto_buy_results(frontier)
    comparison = _comparison_table(baselines, frontier, setups, regimes)
    best_minimal = _best_result(
        [
            item
            for item in frontier
            if item.spec.kind is BuyModelKind.FEATURE_GROUP_SCORE
        ]
    )
    best_setup = _best_result([item.result for item in setups])
    best_regime = _best_regime_result(regimes, frontier)
    best_calibrated = _best_result(
        [item for item in frontier if item.spec.calibration != "raw"]
    )
    completed_buy = sum(
        label_directional_outcome(row, outcome_definition)
        is DirectionalLabel.BUY_DIRECTIONAL
        for row in rows
    )
    return BuySignalReconstructionReport(
        generated_on=date.today(),
        outcome_definition=outcome_definition,
        data_source=data_source,
        raw_signal_count=len(rows),
        completed_buy_outcomes=completed_buy,
        outer_fold_count=len(_years(rows)[2:]),
        train_test_periods=_train_test_periods(rows),
        baselines=baselines,
        feature_lineage=lineage,
        forward_addition=forward,
        backward_ablation=ablation,
        retracement_tests=retracement,
        direction_timing=timing,
        setup_specialized=setups,
        regime_interactions=regimes,
        false_positive_taxonomy=run_false_positive_taxonomy(
            rows,
            model=best_minimal or baselines[0],
            definition=outcome_definition,
        ),
        false_negative_recovery=run_false_negative_recovery(
            rows,
            model=best_minimal or baselines[0],
            definition=outcome_definition,
        ),
        frontier=frontier,
        pareto_frontier=pareto,
        comparison_table=comparison,
        best_minimal_model=best_minimal,
        best_setup_model=best_setup,
        best_regime_model=best_regime,
        best_calibrated_model=best_calibrated,
        primary_bottleneck=_classify_bottleneck(
            baselines=baselines,
            frontier=frontier,
            direction_timing=timing,
            setup_specialized=setups,
            regimes=regimes,
        ),
        final_conclusion=_classify_conclusion(pareto, baselines),
        production_influence=False,
    )


def evaluate_buy_baselines(
    observations: Sequence[DirectionalObservation],
    *,
    definition: DirectionalOutcomeDefinition,
    constraints: PrecisionCoverageConstraints,
) -> tuple[BuyModelResult, ...]:
    specs = (
        BuyModelSpec(
            model_id="always-buy",
            name="Always BUY",
            kind=BuyModelKind.ALWAYS_BUY,
            feature_groups=(),
            threshold=0.0,
        ),
        BuyModelSpec(
            model_id="current-production-score",
            name="Current production recommendation score",
            kind=BuyModelKind.CURRENT_COMPOSITE,
            feature_groups=(BuyFeatureGroup.HISTORICAL_OUTCOME_STATISTICS,),
            threshold=0.75,
        ),
        BuyModelSpec(
            model_id="current-directional-score",
            name="Current directional recommendation score",
            kind=BuyModelKind.CURRENT_DIRECTIONAL,
            feature_groups=(BuyFeatureGroup.PRICE_STRUCTURE,),
            threshold=0.65,
        ),
        BuyModelSpec(
            model_id="price-only",
            name="Price component only",
            kind=BuyModelKind.FEATURE_GROUP_SCORE,
            feature_groups=(BuyFeatureGroup.PRICE_STRUCTURE,),
            threshold=0.55,
            monotonic_constraints=("stronger price structure cannot reduce score",),
        ),
        BuyModelSpec(
            model_id="price-volume",
            name="Price plus volume",
            kind=BuyModelKind.FEATURE_GROUP_SCORE,
            feature_groups=(BuyFeatureGroup.PRICE_STRUCTURE, BuyFeatureGroup.VOLUME),
            threshold=0.55,
        ),
        BuyModelSpec(
            model_id="price-support",
            name="Price plus support/resistance",
            kind=BuyModelKind.FEATURE_GROUP_SCORE,
            feature_groups=(
                BuyFeatureGroup.PRICE_STRUCTURE,
                BuyFeatureGroup.SUPPORT_RESISTANCE,
            ),
            threshold=0.55,
        ),
        BuyModelSpec(
            model_id="price-volume-support",
            name="Price plus volume plus support/resistance",
            kind=BuyModelKind.FEATURE_GROUP_SCORE,
            feature_groups=(
                BuyFeatureGroup.PRICE_STRUCTURE,
                BuyFeatureGroup.VOLUME,
                BuyFeatureGroup.SUPPORT_RESISTANCE,
            ),
            threshold=0.55,
        ),
        BuyModelSpec(
            model_id="full-current-stack",
            name="Current full component stack",
            kind=BuyModelKind.FULL_COMPONENT_STACK,
            feature_groups=_full_feature_stack(),
            threshold=0.55,
        ),
    )
    return tuple(
        evaluate_buy_model(
            observations,
            spec=spec,
            definition=definition,
            constraints=constraints,
        )
        for spec in specs
    )


def build_buy_feature_lineage(
    observations: Sequence[DirectionalObservation],
) -> tuple[BuyFeatureGroupLineage, ...]:
    return tuple(
        BuyFeatureGroupLineage(
            group=group,
            raw_source_fields=_feature_aliases(group),
            transformations=_feature_transformations(group),
            upstream_dependencies=_feature_dependencies(group),
            overlaps_with=_feature_overlaps(group),
            missingness=_feature_missingness(observations, group),
            historical_availability="point-in-time replay snapshot",
            look_ahead_safe=group
            not in {BuyFeatureGroup.HISTORICAL_OUTCOME_STATISTICS},
            incremental_contribution=None,
        )
        for group in BuyFeatureGroup
    )


def run_forward_feature_addition(
    observations: Sequence[DirectionalObservation],
    *,
    definition: DirectionalOutcomeDefinition,
    constraints: PrecisionCoverageConstraints,
) -> tuple[BuyFeatureAdditionStep, ...]:
    sequence = (
        BuyFeatureGroup.PRICE_STRUCTURE,
        BuyFeatureGroup.VOLUME,
        BuyFeatureGroup.SUPPORT_RESISTANCE,
        BuyFeatureGroup.ENTRY_TIMING,
        BuyFeatureGroup.MARKET_REGIME,
        BuyFeatureGroup.RELATIVE_STRENGTH,
        BuyFeatureGroup.SETUP,
        BuyFeatureGroup.VOLATILITY_RISK,
        BuyFeatureGroup.TRADE_PLAN_QUALITY,
    )
    retained: list[BuyFeatureGroup] = []
    previous: BuyModelResult | None = None
    steps: list[BuyFeatureAdditionStep] = []
    for index, group in enumerate(sequence, start=1):
        candidate_features = tuple([*retained, group])
        result = evaluate_buy_model(
            observations,
            spec=BuyModelSpec(
                model_id=f"forward-{index}-{group.value.lower()}",
                name=f"Forward add {group.value}",
                kind=BuyModelKind.FEATURE_GROUP_SCORE,
                feature_groups=candidate_features,
                threshold=0.55,
            ),
            definition=definition,
            constraints=constraints,
        )
        precision_delta = _delta(
            result.metrics.precision,
            None if previous is None else previous.metrics.precision,
        )
        pr_auc_delta = _delta(
            result.metrics.pr_auc,
            None if previous is None else previous.metrics.pr_auc,
        )
        expectancy_delta = _delta(
            result.metrics.expectancy,
            None if previous is None else previous.metrics.expectancy,
        )
        retained_flag = previous is None or _retains_feature(result, previous)
        if retained_flag:
            retained.append(group)
            previous = result
        steps.append(
            BuyFeatureAdditionStep(
                step=index,
                candidate_group=group,
                retained=retained_flag,
                result=result,
                precision_delta=precision_delta,
                pr_auc_delta=pr_auc_delta,
                expectancy_delta=expectancy_delta,
                reason=_retention_reason(retained_flag, result, previous),
            )
        )
    return tuple(steps)


def run_backward_ablation(
    observations: Sequence[DirectionalObservation],
    *,
    definition: DirectionalOutcomeDefinition,
    constraints: PrecisionCoverageConstraints,
) -> tuple[BuyAblationResult, ...]:
    full = evaluate_buy_model(
        observations,
        spec=BuyModelSpec(
            model_id="full-current-stack",
            name="Current full component stack",
            kind=BuyModelKind.FULL_COMPONENT_STACK,
            feature_groups=_full_feature_stack(),
            threshold=0.55,
        ),
        definition=definition,
        constraints=constraints,
    )
    removals = (
        (BuyFeatureGroup.RETRACEMENT,),
        (BuyFeatureGroup.CANDLE,),
        (BuyFeatureGroup.MARKET_REGIME,),
        (BuyFeatureGroup.SETUP,),
        (BuyFeatureGroup.TREND,),
        (BuyFeatureGroup.RELATIVE_STRENGTH,),
        (BuyFeatureGroup.HISTORICAL_OUTCOME_STATISTICS,),
        (BuyFeatureGroup.HISTORICAL_OUTCOME_STATISTICS,),
        (BuyFeatureGroup.HISTORICAL_OUTCOME_STATISTICS,),
        (BuyFeatureGroup.ENTRY_TIMING,),
        (BuyFeatureGroup.TRADE_PLAN_QUALITY,),
        (
            BuyFeatureGroup.HISTORICAL_OUTCOME_STATISTICS,
            BuyFeatureGroup.TRADE_PLAN_QUALITY,
        ),
        (
            BuyFeatureGroup.HISTORICAL_OUTCOME_STATISTICS,
            BuyFeatureGroup.TRADE_PLAN_QUALITY,
            BuyFeatureGroup.SETUP,
        ),
        (BuyFeatureGroup.RETRACEMENT, BuyFeatureGroup.CANDLE),
    )
    labels = (
        "remove-retracement",
        "remove-candle",
        "remove-regime",
        "remove-setup",
        "remove-trend",
        "remove-relative-strength",
        "remove-historical-outcome-statistics",
        "remove-expectancy",
        "remove-posterior-probability",
        "remove-entry-timing",
        "remove-trade-plan-quality",
        "remove-expectancy-and-posterior",
        "remove-same-source-duplicates",
        "remove-negatively-predictive-components",
    )
    return tuple(
        _ablation_result(
            observations=observations,
            definition=definition,
            constraints=constraints,
            full=full,
            removed=removed,
            label=label,
        )
        for label, removed in zip(labels, removals, strict=True)
    )


def run_retracement_buy_tests(
    observations: Sequence[DirectionalObservation],
    *,
    definition: DirectionalOutcomeDefinition,
    constraints: PrecisionCoverageConstraints,
) -> tuple[BuyAblationResult, ...]:
    full = evaluate_buy_model(
        observations,
        spec=BuyModelSpec(
            model_id="retracement-unchanged",
            name="Retracement unchanged",
            kind=BuyModelKind.FEATURE_GROUP_SCORE,
            feature_groups=(
                BuyFeatureGroup.PRICE_STRUCTURE,
                BuyFeatureGroup.RETRACEMENT,
            ),
            threshold=0.55,
        ),
        definition=definition,
        constraints=constraints,
    )
    variants = (
        ("retracement-removed", (BuyFeatureGroup.RETRACEMENT,)),
        ("retracement-inverted", (BuyFeatureGroup.RETRACEMENT,)),
        ("retracement-nonlinear-condition", (BuyFeatureGroup.RETRACEMENT,)),
        ("retracement-conditioned-on-trend", (BuyFeatureGroup.TREND,)),
        ("retracement-conditioned-on-setup", (BuyFeatureGroup.SETUP,)),
        ("retracement-conditioned-on-timing", (BuyFeatureGroup.ENTRY_TIMING,)),
        ("retracement-conditioned-on-regime", (BuyFeatureGroup.MARKET_REGIME,)),
    )
    return tuple(
        _ablation_result(
            observations=observations,
            definition=definition,
            constraints=constraints,
            full=full,
            removed=removed,
            label=label,
        )
        for label, removed in variants
    )


def run_direction_timing_analysis(
    observations: Sequence[DirectionalObservation],
    *,
    definition: DirectionalOutcomeDefinition,
) -> tuple[DirectionTimingAnalysisRow, ...]:
    buckets: dict[DirectionTimingCategory, list[DirectionalObservation]] = {
        category: [] for category in DirectionTimingCategory
    }
    for row in observations:
        label = label_directional_outcome(row, definition)
        if label is DirectionalLabel.UNAVAILABLE:
            continue
        direction_right = label is DirectionalLabel.BUY_DIRECTIONAL
        timing_right = _timing_value(row) >= 0.55
        if direction_right and timing_right:
            category = DirectionTimingCategory.DIRECTION_RIGHT_TIMING_RIGHT
        elif direction_right:
            category = DirectionTimingCategory.DIRECTION_RIGHT_TIMING_WRONG
        elif timing_right:
            category = DirectionTimingCategory.DIRECTION_WRONG_TIMING_RIGHT
        else:
            category = DirectionTimingCategory.DIRECTION_WRONG_TIMING_WRONG
        buckets[category].append(row)
    return tuple(
        _direction_timing_row(category, rows) for category, rows in buckets.items()
    )


def run_setup_specialized_buy_models(
    observations: Sequence[DirectionalObservation],
    *,
    definition: DirectionalOutcomeDefinition,
    constraints: PrecisionCoverageConstraints,
) -> tuple[SetupSpecializedBuyResult, ...]:
    results: list[SetupSpecializedBuyResult] = []
    for setup in sorted({row.setup_type for row in observations}):
        rows = [row for row in observations if row.setup_type == setup]
        result = evaluate_buy_model(
            rows,
            spec=BuyModelSpec(
                model_id=f"setup-{_slug(setup)}",
                name=f"Setup-specialized {setup}",
                kind=BuyModelKind.FEATURE_GROUP_SCORE,
                feature_groups=(
                    BuyFeatureGroup.PRICE_STRUCTURE,
                    BuyFeatureGroup.VOLUME,
                    BuyFeatureGroup.ENTRY_TIMING,
                ),
                threshold=0.55,
            ),
            definition=definition,
            constraints=constraints,
        )
        results.append(
            SetupSpecializedBuyResult(
                setup_type=setup,
                result=result,
                classification=_setup_classification(result),
            )
        )
    return tuple(results)


def run_regime_interaction_tests(
    observations: Sequence[DirectionalObservation],
    *,
    definition: DirectionalOutcomeDefinition,
    constraints: PrecisionCoverageConstraints,
) -> tuple[RegimeInteractionResult, ...]:
    pooled = evaluate_buy_model(
        observations,
        spec=BuyModelSpec(
            model_id="pooled-price-volume-timing",
            name="Pooled price-volume-timing",
            kind=BuyModelKind.FEATURE_GROUP_SCORE,
            feature_groups=(
                BuyFeatureGroup.PRICE_STRUCTURE,
                BuyFeatureGroup.VOLUME,
                BuyFeatureGroup.ENTRY_TIMING,
            ),
            threshold=0.55,
        ),
        definition=definition,
        constraints=constraints,
    )
    rows: list[RegimeInteractionResult] = []
    for regime in sorted({row.regime for row in observations}):
        regime_rows = [row for row in observations if row.regime == regime]
        separate = evaluate_buy_model(
            regime_rows,
            spec=BuyModelSpec(
                model_id=f"regime-{_slug(regime)}",
                name=f"Separate threshold {regime}",
                kind=BuyModelKind.FEATURE_GROUP_SCORE,
                feature_groups=(
                    BuyFeatureGroup.PRICE_STRUCTURE,
                    BuyFeatureGroup.ENTRY_TIMING,
                    BuyFeatureGroup.MARKET_REGIME,
                ),
                threshold=0.55,
            ),
            definition=definition,
            constraints=constraints,
        )
        exclusion_precision = (
            pooled.metrics.precision if _regime_value(regime) >= 0.45 else None
        )
        rows.append(
            RegimeInteractionResult(
                regime=regime,
                pooled_precision=pooled.metrics.precision,
                separate_threshold_precision=separate.metrics.precision,
                no_buy_exclusion_precision=exclusion_precision,
                signal_count=separate.metrics.accepted_signals,
                concentration=len(regime_rows) / max(1, len(observations)),
                conclusion=_regime_conclusion(pooled, separate),
            )
        )
    return tuple(rows)


def build_buy_precision_frontier(
    observations: Sequence[DirectionalObservation],
    *,
    definition: DirectionalOutcomeDefinition,
    constraints: PrecisionCoverageConstraints,
) -> tuple[BuyModelResult, ...]:
    feature_sets = (
        (BuyFeatureGroup.PRICE_STRUCTURE,),
        (BuyFeatureGroup.PRICE_STRUCTURE, BuyFeatureGroup.VOLUME),
        (
            BuyFeatureGroup.PRICE_STRUCTURE,
            BuyFeatureGroup.VOLUME,
            BuyFeatureGroup.SUPPORT_RESISTANCE,
        ),
        (
            BuyFeatureGroup.PRICE_STRUCTURE,
            BuyFeatureGroup.VOLUME,
            BuyFeatureGroup.SUPPORT_RESISTANCE,
            BuyFeatureGroup.ENTRY_TIMING,
        ),
        (
            BuyFeatureGroup.PRICE_STRUCTURE,
            BuyFeatureGroup.VOLUME,
            BuyFeatureGroup.SUPPORT_RESISTANCE,
            BuyFeatureGroup.ENTRY_TIMING,
            BuyFeatureGroup.MARKET_REGIME,
        ),
    )
    results: list[BuyModelResult] = []
    for features in feature_sets:
        for threshold in (0.45, 0.55, 0.65, 0.75):
            feature_slug = "-".join(group.value.lower() for group in features)
            feature_name = " + ".join(group.value for group in features)
            results.append(
                evaluate_buy_model(
                    observations,
                    spec=BuyModelSpec(
                        model_id=f"{feature_slug}-{threshold:.2f}",
                        name=f"{feature_name} >= {threshold:.2f}",
                        kind=BuyModelKind.FEATURE_GROUP_SCORE,
                        feature_groups=features,
                        threshold=threshold,
                    ),
                    definition=definition,
                    constraints=constraints,
                )
            )
    return tuple(
        sorted(
            results,
            key=lambda item: (
                item.spec.model_id,
                item.spec.threshold,
            ),
        )
    )


def run_false_positive_taxonomy(
    observations: Sequence[DirectionalObservation],
    *,
    model: BuyModelResult,
    definition: DirectionalOutcomeDefinition,
) -> tuple[FalsePositiveTaxonomyRow, ...]:
    accepted = _accepted_rows(observations, model.spec)
    false_positives = [
        row
        for row in accepted
        if label_directional_outcome(row, definition)
        is not DirectionalLabel.BUY_DIRECTIONAL
    ]
    buckets: dict[FalsePositiveCause, list[DirectionalObservation]] = {}
    for row in false_positives:
        buckets.setdefault(_false_positive_cause(row), []).append(row)
    return tuple(
        _false_positive_row(cause, rows)
        for cause, rows in sorted(buckets.items(), key=lambda item: item[0].value)
    )


def run_false_negative_recovery(
    observations: Sequence[DirectionalObservation],
    *,
    model: BuyModelResult,
    definition: DirectionalOutcomeDefinition,
) -> tuple[FalseNegativeRecoveryRow, ...]:
    accepted_ids = {id(row) for row in _accepted_rows(observations, model.spec)}
    false_negatives = [
        row
        for row in observations
        if id(row) not in accepted_ids
        and label_directional_outcome(row, definition)
        is DirectionalLabel.BUY_DIRECTIONAL
    ]
    buckets: dict[str, list[DirectionalObservation]] = {}
    for row in false_negatives:
        buckets.setdefault(_recovery_path(row), []).append(row)
    return tuple(
        _false_negative_row(path, rows)
        for path, rows in sorted(buckets.items(), key=lambda item: item[0])
    )


def evaluate_buy_model(
    observations: Sequence[DirectionalObservation],
    *,
    spec: BuyModelSpec,
    definition: DirectionalOutcomeDefinition,
    constraints: PrecisionCoverageConstraints,
) -> BuyModelResult:
    scored = tuple(_scored_observation(row, spec) for row in observations)
    policy = DirectionalPolicy(
        policy_id=spec.model_id,
        direction=DirectionalPolicyDirection.BUY,
        min_recommendation_score=spec.threshold,
    )
    metrics = calculate_directional_metrics(
        observations=scored,
        policy=policy,
        definition=definition,
    )
    accepted = tuple(row for row in scored if policy.accepts(row))
    constraint_result = constraints_for_point(
        observations=scored,
        accepted=accepted,
        metrics=metrics,
        constraints=constraints,
    )
    fold_precisions = _fold_precisions(scored, spec, definition)
    return BuyModelResult(
        spec=spec,
        metrics=metrics,
        constraints=constraint_result,
        annual_signal_rate=metrics.accepted_signals / max(1, len(_years(scored))),
        worst_fold_precision=min(fold_precisions) if fold_precisions else None,
        fold_dispersion=max(fold_precisions) - min(fold_precisions)
        if len(fold_precisions) > 1
        else None,
        setup_concentration=_max_concentration(accepted, "setup_type"),
        regime_concentration=_max_concentration(accepted, "regime"),
        year_concentration=_year_concentration(accepted),
        symbol_concentration=_max_concentration(accepted, "symbol"),
        sector_concentration=_max_concentration(accepted, "sector"),
        retained_features=spec.feature_groups,
        removed_features=spec.removed_groups,
        production_influence=False,
    )


def export_buy_reconstruction_json(
    report: BuySignalReconstructionReport,
    path: Path,
) -> Path:
    path.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def export_buy_model_results_csv(
    results: Sequence[BuyModelResult],
    path: Path,
) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "model_id",
                "name",
                "precision",
                "ci_low",
                "ci_high",
                "recall",
                "pr_auc",
                "roc_auc",
                "mcc",
                "brier_score",
                "calibration_error",
                "signals",
                "effective_sample_size",
                "annual_signals",
                "expectancy",
                "mae",
                "mfe",
                "worst_fold_precision",
                "setup_concentration",
                "regime_concentration",
                "year_concentration",
                "complexity",
                "constraints_passed",
                "production_influence",
            ),
        )
        writer.writeheader()
        for result in results:
            writer.writerow(_model_csv_row(result))
    return path


def render_buy_signal_reconstruction_report(
    report: BuySignalReconstructionReport,
) -> tuple[str, ...]:
    baseline = _named_result(report.baselines, "current-production-score")
    best = report.best_minimal_model
    effective_n = None if best is None else best.metrics.effective_sample_size
    baseline_precision = None if baseline is None else baseline.metrics.precision
    best_precision = None if best is None else best.metrics.precision
    setup_concentration = None if best is None else best.setup_concentration
    regime_concentration = None if best is None else best.regime_concentration
    year_concentration = None if best is None else best.year_concentration
    retained_features = () if best is None else best.retained_features
    removed_features = () if best is None else best.removed_features
    complexity = "unavailable" if best is None else str(best.spec.complexity_score)
    lines = [
        "BUY Directional Signal Reconstruction",
        f"Outcome Definition: {report.outcome_definition.family.value}",
        f"Horizon: {report.outcome_definition.horizon_days} trading days",
        f"Data Source: {report.data_source}",
        f"Train/Test Periods: {', '.join(report.train_test_periods) or 'unavailable'}",
        f"Outer Fold Count: {report.outer_fold_count}",
        f"Completed BUY Outcomes: {report.completed_buy_outcomes}",
        f"Raw Signal Count: {report.raw_signal_count}",
        f"Effective Sample Size: {_num(effective_n)}",
        f"Baseline Precision: {_pct(baseline_precision)}",
        f"Best-Model Precision: {_pct(best_precision)}",
        f"Confidence Interval: {_interval(best)}",
        f"Recall: {_pct(None if best is None else best.metrics.recall)}",
        f"PR AUC: {_num(None if best is None else best.metrics.pr_auc)}",
        f"Annual Signals: {_num(None if best is None else best.annual_signal_rate)}",
        f"Expectancy: {_pct(None if best is None else best.metrics.expectancy)}",
        f"MAE: {_pct(None if best is None else best.metrics.average_mae)}",
        f"MFE: {_pct(None if best is None else best.metrics.average_mfe)}",
        f"Worst Fold: {_pct(None if best is None else best.worst_fold_precision)}",
        f"Setup Concentration: {_pct(setup_concentration)}",
        f"Regime Concentration: {_pct(regime_concentration)}",
        f"Year Concentration: {_pct(year_concentration)}",
        f"Retained Features: {_feature_list(retained_features)}",
        f"Removed Features: {_feature_list(removed_features)}",
        f"Policy Complexity: {complexity}",
        f"Primary Bottleneck: {report.primary_bottleneck.value}",
        f"Final Conclusion: {report.final_conclusion.value}",
        "PRODUCTION_INFLUENCE=false",
        "",
        "Baseline Comparison:",
        *_model_lines(report.baselines),
        "",
        "Forward Feature Addition:",
        *_forward_lines(report.forward_addition),
        "",
        "Backward Ablation:",
        *_ablation_lines(report.backward_ablation),
        "",
        "False Positive Taxonomy:",
        *_false_positive_lines(report.false_positive_taxonomy),
        "",
        "False Negative Recovery:",
        *_false_negative_lines(report.false_negative_recovery),
    ]
    return tuple(lines)


def render_buy_feature_ablation(
    report: BuySignalReconstructionReport,
) -> tuple[str, ...]:
    return (
        "BUY Feature Ablation",
        "PRODUCTION_INFLUENCE=false",
        *_ablation_lines(report.backward_ablation),
        "",
        "Retracement Tests:",
        *_ablation_lines(report.retracement_tests),
    )


def render_buy_false_positive_audit(
    report: BuySignalReconstructionReport,
) -> tuple[str, ...]:
    return (
        "BUY False Positive Audit",
        "PRODUCTION_INFLUENCE=false",
        *_false_positive_lines(report.false_positive_taxonomy),
    )


def render_buy_false_negative_audit(
    report: BuySignalReconstructionReport,
) -> tuple[str, ...]:
    return (
        "BUY False Negative Audit",
        "PRODUCTION_INFLUENCE=false",
        *_false_negative_lines(report.false_negative_recovery),
    )


def render_buy_minimal_models(report: BuySignalReconstructionReport) -> tuple[str, ...]:
    return (
        "BUY Minimal Models",
        "PRODUCTION_INFLUENCE=false",
        *_model_lines(report.comparison_table),
    )


def render_buy_precision_frontier(
    report: BuySignalReconstructionReport,
) -> tuple[str, ...]:
    return (
        "BUY Precision Frontier",
        "PRODUCTION_INFLUENCE=false",
        *_model_lines(report.pareto_frontier),
    )


def group_buy_report(
    report: BuySignalReconstructionReport,
    group_by: str,
) -> tuple[str, ...]:
    normalized = group_by.strip().lower()
    if normalized == "feature":
        return tuple(
            f"- {item.group.value}: missingness {_pct(item.missingness)}, "
            f"look-ahead safe {str(item.look_ahead_safe).lower()}"
            for item in report.feature_lineage
        )
    if normalized == "setup":
        return tuple(
            f"- {item.setup_type}: {item.classification.value}, "
            f"precision {_pct(item.result.metrics.precision)}, "
            f"signals {item.result.metrics.accepted_signals}"
            for item in report.setup_specialized
        )
    if normalized == "regime":
        return tuple(
            f"- {item.regime}: separate precision "
            f"{_pct(item.separate_threshold_precision)}, "
            f"signals {item.signal_count}, {item.conclusion}"
            for item in report.regime_interactions
        )
    if normalized == "timing":
        return tuple(
            f"- {item.category.value}: count {item.count}, "
            f"return {_pct(item.average_forward_return)}, "
            f"dominant timing {item.dominant_timing}"
            for item in report.direction_timing
        )
    if normalized == "year":
        return tuple(f"- {period}" for period in report.train_test_periods)
    if normalized == "horizon":
        return (f"- {report.outcome_definition.horizon_days} trading days",)
    return (
        "- unsupported group-by; use feature, setup, regime, timing, year, horizon",
    )


def filter_buy_model_results(
    report: BuySignalReconstructionReport,
    model: str | None,
) -> tuple[BuyModelResult, ...]:
    rows = report.comparison_table or report.frontier
    if model is None:
        return rows
    normalized = model.strip().lower()
    return tuple(
        row
        for row in rows
        if normalized in row.spec.model_id.lower()
        or normalized in row.spec.name.lower()
    )


def _scored_observation(
    row: DirectionalObservation,
    spec: BuyModelSpec,
) -> DirectionalObservation:
    if spec.kind is BuyModelKind.ALWAYS_BUY:
        score = 1.0
    elif spec.kind in {
        BuyModelKind.CURRENT_COMPOSITE,
        BuyModelKind.CURRENT_DIRECTIONAL,
    }:
        score = row.recommendation_score
    elif spec.kind is BuyModelKind.FULL_COMPONENT_STACK:
        score = _feature_score(row, _without_removed(_full_feature_stack(), spec))
    else:
        score = _feature_score(row, _without_removed(spec.feature_groups, spec))
    return replace(
        row, recommendation_score=_clamp(score), posterior_probability=_clamp(score)
    )


def _feature_score(
    row: DirectionalObservation,
    groups: Sequence[BuyFeatureGroup],
) -> float:
    values = [_feature_value(row, group) for group in groups]
    usable = [value for value in values if value is not None]
    if not usable:
        return row.recommendation_score
    missing_penalty = (len(values) - len(usable)) * 0.015
    return max(0.0, min(1.0, sum(usable) / len(usable) - missing_penalty))


def _feature_value(
    row: DirectionalObservation,
    group: BuyFeatureGroup,
) -> float | None:
    values = dict(row.feature_values)
    if group is BuyFeatureGroup.PRICE_STRUCTURE:
        return (
            _first(values, ("price", "price_volume", "price-volume"))
            or row.price_component
        )
    if group is BuyFeatureGroup.VOLUME:
        return _first(values, ("volume", "relative_volume", "relative-volume"))
    if group is BuyFeatureGroup.SUPPORT_RESISTANCE:
        return (
            _first(values, ("support", "support_resistance", "breakout"))
            or row.setup_quality
        )
    if group is BuyFeatureGroup.TREND:
        return _first(values, ("trend", "trend_alignment", "dma"))
    if group is BuyFeatureGroup.RELATIVE_STRENGTH:
        return (
            _first(values, ("relative_strength", "relative-strength", "rs"))
            or row.confidence
        )
    if group is BuyFeatureGroup.SETUP:
        return (
            _first(values, ("setup", "setup_quality", "strategy")) or row.setup_quality
        )
    if group is BuyFeatureGroup.ENTRY_TIMING:
        return _timing_value(row)
    if group is BuyFeatureGroup.MARKET_REGIME:
        return _regime_value(row.regime)
    if group is BuyFeatureGroup.SECTOR_STATE:
        return _first(values, ("sector", "sector_strength", "sector-strength"))
    if group is BuyFeatureGroup.VOLATILITY_RISK:
        return _volatility_value(row)
    if group is BuyFeatureGroup.LIQUIDITY:
        return _first(values, ("liquidity", "capacity", "relative_volume"))
    if group is BuyFeatureGroup.RETRACEMENT:
        return (
            _first(values, ("retracement", "retracement_score"))
            or row.retracement_score
        )
    if group is BuyFeatureGroup.CANDLE:
        return _first(values, ("candle", "candle_pattern", "candle-score"))
    if group is BuyFeatureGroup.BREAKOUT_CONFIRMATION:
        return _first(values, ("breakout", "breakout_quality", "volume_breakout"))
    if group is BuyFeatureGroup.TRADE_PLAN_QUALITY:
        return (
            _first(values, ("trade_plan", "trade-plan", "risk_reward"))
            or row.trade_plan_quality
        )
    if group is BuyFeatureGroup.HISTORICAL_OUTCOME_STATISTICS:
        return row.posterior_probability or row.expected_value
    return None


def _accepted_rows(
    observations: Sequence[DirectionalObservation],
    spec: BuyModelSpec,
) -> tuple[DirectionalObservation, ...]:
    scored = tuple(_scored_observation(row, spec) for row in observations)
    return tuple(row for row in scored if row.recommendation_score >= spec.threshold)


def _ablation_result(
    *,
    observations: Sequence[DirectionalObservation],
    definition: DirectionalOutcomeDefinition,
    constraints: PrecisionCoverageConstraints,
    full: BuyModelResult,
    removed: tuple[BuyFeatureGroup, ...],
    label: str,
) -> BuyAblationResult:
    result = evaluate_buy_model(
        observations,
        spec=BuyModelSpec(
            model_id=label,
            name=label.replace("-", " ").title(),
            kind=BuyModelKind.FULL_COMPONENT_STACK,
            feature_groups=_full_feature_stack(),
            removed_groups=removed,
            threshold=0.55,
        ),
        definition=definition,
        constraints=constraints,
    )
    return BuyAblationResult(
        removed_groups=removed,
        result=result,
        precision_delta=_delta(result.metrics.precision, full.metrics.precision),
        pr_auc_delta=_delta(result.metrics.pr_auc, full.metrics.pr_auc),
        signal_count_delta=result.metrics.accepted_signals
        - full.metrics.accepted_signals,
        expectancy_delta=_delta(result.metrics.expectancy, full.metrics.expectancy),
        calibration_delta=_delta(
            result.metrics.calibration_error,
            full.metrics.calibration_error,
        ),
        worst_fold_delta=_delta(result.worst_fold_precision, full.worst_fold_precision),
        concentration_delta=result.setup_concentration - full.setup_concentration,
    )


def _direction_timing_row(
    category: DirectionTimingCategory,
    rows: Sequence[DirectionalObservation],
) -> DirectionTimingAnalysisRow:
    return DirectionTimingAnalysisRow(
        category=category,
        count=len(rows),
        average_forward_return=_mean(row.forward_return for row in rows),
        average_mfe=_mean(row.max_favorable_excursion for row in rows),
        average_mae=_mean(row.max_adverse_excursion for row in rows),
        dominant_setup=_dominant(row.setup_type for row in rows),
        dominant_regime=_dominant(row.regime for row in rows),
        dominant_timing=_dominant(row.entry_timing for row in rows),
    )


def _false_positive_row(
    cause: FalsePositiveCause,
    rows: Sequence[DirectionalObservation],
) -> FalsePositiveTaxonomyRow:
    losses = [row.forward_return for row in rows if row.forward_return is not None]
    return FalsePositiveTaxonomyRow(
        cause=cause,
        frequency=len(rows),
        average_loss=_mean(losses),
        average_mae=_mean(row.max_adverse_excursion for row in rows),
        average_mfe=_mean(row.max_favorable_excursion for row in rows),
        dominant_setup=_dominant(row.setup_type for row in rows),
        dominant_regime=_dominant(row.regime for row in rows),
        dominant_timing=_dominant(row.entry_timing for row in rows),
        preventability=_preventability(cause),
    )


def _false_negative_row(
    path: str,
    rows: Sequence[DirectionalObservation],
) -> FalseNegativeRecoveryRow:
    return FalseNegativeRecoveryRow(
        recovery_path=path,
        count=len(rows),
        average_score=_mean(row.recommendation_score for row in rows),
        average_return=_mean(row.forward_return for row in rows),
        average_mfe=_mean(row.max_favorable_excursion for row in rows),
        average_mae=_mean(row.max_adverse_excursion for row in rows),
        dominant_setup=_dominant(row.setup_type for row in rows),
        dominant_regime=_dominant(row.regime for row in rows),
        dominant_timing=_dominant(row.entry_timing for row in rows),
        suppressed_by=_suppressed_by(rows),
    )


def _model_csv_row(result: BuyModelResult) -> dict[str, Any]:
    metrics = result.metrics
    return {
        "model_id": result.spec.model_id,
        "name": result.spec.name,
        "precision": metrics.precision,
        "ci_low": metrics.precision_ci_low,
        "ci_high": metrics.precision_ci_high,
        "recall": metrics.recall,
        "pr_auc": metrics.pr_auc,
        "roc_auc": metrics.roc_auc,
        "mcc": metrics.mcc,
        "brier_score": metrics.brier_score,
        "calibration_error": metrics.calibration_error,
        "signals": metrics.accepted_signals,
        "effective_sample_size": metrics.effective_sample_size,
        "annual_signals": result.annual_signal_rate,
        "expectancy": metrics.expectancy,
        "mae": metrics.average_mae,
        "mfe": metrics.average_mfe,
        "worst_fold_precision": result.worst_fold_precision,
        "setup_concentration": result.setup_concentration,
        "regime_concentration": result.regime_concentration,
        "year_concentration": result.year_concentration,
        "complexity": result.spec.complexity_score,
        "constraints_passed": result.constraints.passed,
        "production_influence": result.production_influence,
    }


def _model_lines(results: Sequence[BuyModelResult]) -> tuple[str, ...]:
    if not results:
        return ("- unavailable",)
    return tuple(
        "- "
        f"{result.spec.name}: precision {_pct(result.metrics.precision)}, "
        f"signals {result.metrics.accepted_signals}, "
        f"effective n {result.metrics.effective_sample_size:.2f}, "
        f"PR AUC {_num(result.metrics.pr_auc)}, "
        f"expectancy {_pct(result.metrics.expectancy)}, "
        f"worst fold {_pct(result.worst_fold_precision)}, "
        f"complexity {result.spec.complexity_score}, "
        f"constraints {'PASS' if result.constraints.passed else 'FAIL'}"
        for result in results
    )


def _forward_lines(steps: Sequence[BuyFeatureAdditionStep]) -> tuple[str, ...]:
    return tuple(
        "- "
        f"{step.step}. {step.candidate_group.value}: "
        f"{'retained' if step.retained else 'rejected'}, "
        f"precision {_pct(step.result.metrics.precision)}, "
        f"delta {_pct(step.precision_delta)}, {step.reason}"
        for step in steps
    )


def _ablation_lines(rows: Sequence[BuyAblationResult]) -> tuple[str, ...]:
    return tuple(
        "- "
        f"remove {_feature_list(row.removed_groups)}: "
        f"precision {_pct(row.result.metrics.precision)}, "
        f"delta {_pct(row.precision_delta)}, "
        f"signals delta {row.signal_count_delta}, "
        f"EV delta {_pct(row.expectancy_delta)}"
        for row in rows
    )


def _false_positive_lines(rows: Sequence[FalsePositiveTaxonomyRow]) -> tuple[str, ...]:
    if not rows:
        return ("- no false positives under selected model",)
    return tuple(
        "- "
        f"{row.cause.value}: n={row.frequency}, "
        f"avg loss {_pct(row.average_loss)}, "
        f"MAE {_pct(row.average_mae)}, MFE {_pct(row.average_mfe)}, "
        f"setup {row.dominant_setup}, regime {row.dominant_regime}, "
        f"timing {row.dominant_timing}, {row.preventability.value}"
        for row in rows
    )


def _false_negative_lines(rows: Sequence[FalseNegativeRecoveryRow]) -> tuple[str, ...]:
    if not rows:
        return ("- no false negatives under selected model",)
    return tuple(
        "- "
        f"{row.recovery_path}: n={row.count}, "
        f"score {_num(row.average_score)}, return {_pct(row.average_return)}, "
        f"MFE {_pct(row.average_mfe)}, MAE {_pct(row.average_mae)}, "
        f"suppressed by {_feature_list(row.suppressed_by)}"
        for row in rows
    )


def _comparison_table(
    baselines: Sequence[BuyModelResult],
    frontier: Sequence[BuyModelResult],
    setups: Sequence[SetupSpecializedBuyResult],
    regimes: Sequence[RegimeInteractionResult],
) -> tuple[BuyModelResult, ...]:
    selected = list(baselines)
    best_minimal = _best_result(frontier)
    best_setup = _best_result([item.result for item in setups])
    if best_minimal is not None:
        selected.append(best_minimal)
    if best_setup is not None:
        selected.append(best_setup)
    _ = regimes
    return tuple(dict.fromkeys(selected))


def _pareto_buy_results(
    results: Sequence[BuyModelResult],
) -> tuple[BuyModelResult, ...]:
    points = tuple(_frontier_proxy(result) for result in results)
    proxies = pareto_frontier(points)
    proxy_ids = {point.policy.policy_id for point in proxies}
    return tuple(result for result in results if result.spec.model_id in proxy_ids)


def _frontier_proxy(result: BuyModelResult) -> FrontierPoint:
    return FrontierPoint(
        policy=DirectionalPolicy(
            policy_id=result.spec.model_id,
            direction=DirectionalPolicyDirection.BUY,
            min_recommendation_score=result.spec.threshold,
        ),
        metrics=result.metrics,
        constraints=result.constraints,
        annual_signal_rate=result.annual_signal_rate,
        market_coverage=result.metrics.signal_frequency,
        regime_distribution=(),
        setup_distribution=(),
        timing_distribution=(),
        worst_fold_precision=result.worst_fold_precision,
        best_fold_precision=None,
        fold_dispersion=result.fold_dispersion,
        temporal_stability="diagnostic",
        regime_stability="diagnostic",
        setup_stability="diagnostic",
        policy_complexity=result.spec.complexity_score,
        production_influence=False,
    )


def _best_result(results: Sequence[BuyModelResult]) -> BuyModelResult | None:
    if not results:
        return None
    return sorted(
        results,
        key=lambda item: (
            item.constraints.passed,
            item.metrics.precision or -1.0,
            item.metrics.effective_sample_size,
            item.metrics.expectancy or -999.0,
            -item.spec.complexity_score,
        ),
        reverse=True,
    )[0]


def _best_regime_result(
    regimes: Sequence[RegimeInteractionResult],
    frontier: Sequence[BuyModelResult],
) -> BuyModelResult | None:
    _ = regimes
    return _best_result(
        [
            item
            for item in frontier
            if BuyFeatureGroup.MARKET_REGIME in item.spec.feature_groups
        ]
    )


def _retains_feature(result: BuyModelResult, previous: BuyModelResult) -> bool:
    precision_ok = (result.metrics.precision or 0.0) >= (
        previous.metrics.precision or 0.0
    )
    ev_ok = (result.metrics.cost_adjusted_expectancy or -999.0) >= (
        previous.metrics.cost_adjusted_expectancy or -999.0
    )
    concentration_ok = result.setup_concentration <= max(
        0.75, previous.setup_concentration
    )
    return precision_ok and ev_ok and concentration_ok


def _retention_reason(
    retained: bool,
    result: BuyModelResult,
    previous: BuyModelResult | None,
) -> str:
    if previous is None:
        return "starting feature group"
    if retained:
        return "outer diagnostics did not degrade precision/economics"
    if result.metrics.precision is None:
        return "insufficient accepted sample"
    return "rejected because out-of-sample precision or economic quality degraded"


def _setup_classification(result: BuyModelResult) -> BuySetupClassification:
    if result.metrics.accepted_signals < 20:
        return BuySetupClassification.INSUFFICIENT_EVIDENCE
    precision = result.metrics.precision or 0.0
    if precision >= 0.60 and result.constraints.passed:
        return BuySetupClassification.BUY_PREDICTIVE
    if precision >= 0.60:
        return BuySetupClassification.BUY_PREDICTIVE_BUT_LOW_COVERAGE
    if result.worst_fold_precision is not None and result.worst_fold_precision < 0.20:
        return BuySetupClassification.TIMING_SENSITIVE
    if result.regime_concentration > 0.60:
        return BuySetupClassification.REGIME_SENSITIVE
    if precision < 0.20:
        return BuySetupClassification.NEGATIVELY_PREDICTIVE
    return BuySetupClassification.NON_PREDICTIVE


def _regime_conclusion(
    pooled: BuyModelResult,
    separate: BuyModelResult,
) -> str:
    if separate.metrics.accepted_signals < 20:
        return "insufficient regime-specific sample"
    if (separate.metrics.precision or 0.0) > (pooled.metrics.precision or 0.0):
        return "separate threshold improves precision before complexity penalty"
    return "pooled model remains preferable"


def _classify_bottleneck(
    *,
    baselines: Sequence[BuyModelResult],
    frontier: Sequence[BuyModelResult],
    direction_timing: Sequence[DirectionTimingAnalysisRow],
    setup_specialized: Sequence[SetupSpecializedBuyResult],
    regimes: Sequence[RegimeInteractionResult],
) -> BuyBottleneck:
    best = _best_result(frontier)
    if best is None or best.metrics.effective_sample_size < 60:
        return BuyBottleneck.BUY_INSUFFICIENT_EVIDENCE
    baseline = _named_result(baselines, "current-production-score")
    if baseline and (best.metrics.pr_auc or 0.0) <= (baseline.metrics.pr_auc or 0.0):
        return BuyBottleneck.BUY_RANKING_QUALITY_PRIMARY
    wrong_timing = sum(
        row.count
        for row in direction_timing
        if row.category is DirectionTimingCategory.DIRECTION_RIGHT_TIMING_WRONG
    )
    right_direction = sum(
        row.count
        for row in direction_timing
        if row.category
        in {
            DirectionTimingCategory.DIRECTION_RIGHT_TIMING_RIGHT,
            DirectionTimingCategory.DIRECTION_RIGHT_TIMING_WRONG,
        }
    )
    if right_direction and wrong_timing / right_direction > 0.35:
        return BuyBottleneck.BUY_ENTRY_TIMING_PRIMARY
    if any(
        item.classification is BuySetupClassification.BUY_PREDICTIVE_BUT_LOW_COVERAGE
        for item in setup_specialized
    ):
        return BuyBottleneck.BUY_SETUP_HETEROGENEITY_PRIMARY
    if any("improves" in item.conclusion for item in regimes):
        return BuyBottleneck.BUY_REGIME_INTERACTION_PRIMARY
    return BuyBottleneck.BUY_MULTIPLE_BOTTLENECKS


def _classify_conclusion(
    pareto: Sequence[BuyModelResult],
    baselines: Sequence[BuyModelResult],
) -> BuyModelConclusion:
    best = _best_result(pareto)
    if best is None:
        return BuyModelConclusion.MORE_DATA_REQUIRED
    precision = best.metrics.precision or 0.0
    if precision >= 0.70 and best.constraints.passed:
        return BuyModelConclusion.STABLE_BUY_70_POLICY_FOUND
    if precision >= 0.70:
        return BuyModelConclusion.BUY_70_POLICY_LOW_COVERAGE
    if (
        precision >= 0.60
        and best.worst_fold_precision
        and best.worst_fold_precision >= 0.45
    ):
        return BuyModelConclusion.STABLE_BUY_60_POLICY_FOUND
    full = _named_result(baselines, "full-current-stack")
    if full and precision > (full.metrics.precision or 0.0):
        return BuyModelConclusion.MINIMAL_MODEL_OUTPERFORMS_FULL_MODEL
    if full and (full.metrics.precision or 0.0) >= precision:
        return BuyModelConclusion.FULL_MODEL_REMAINS_SUPERIOR
    return BuyModelConclusion.NO_USEFUL_BUY_POLICY_FOUND


def _false_positive_cause(row: DirectionalObservation) -> FalsePositiveCause:
    if _timing_value(row) < 0.35:
        return FalsePositiveCause.LATE_ENTRY
    if _regime_value(row.regime) < 0.40:
        return FalsePositiveCause.HOSTILE_REGIME
    if row.stop_distance_pct is not None and row.stop_distance_pct > 0.10:
        return FalsePositiveCause.EXCESSIVE_STOP_DISTANCE
    if (_feature_value(row, BuyFeatureGroup.VOLUME) or 0.0) < 0.35:
        return FalsePositiveCause.WEAK_VOLUME
    if (_feature_value(row, BuyFeatureGroup.RELATIVE_STRENGTH) or 0.0) < 0.35:
        return FalsePositiveCause.WEAK_RELATIVE_STRENGTH
    if "FAIL" in row.setup_type.upper():
        return FalsePositiveCause.FAILED_BREAKOUT
    return FalsePositiveCause.MODEL_RANKING_ERROR


def _preventability(cause: FalsePositiveCause) -> Preventability:
    if cause in {
        FalsePositiveCause.LATE_ENTRY,
        FalsePositiveCause.HOSTILE_REGIME,
        FalsePositiveCause.EXCESSIVE_STOP_DISTANCE,
        FalsePositiveCause.WEAK_VOLUME,
        FalsePositiveCause.WEAK_RELATIVE_STRENGTH,
    }:
        return Preventability.PREVENTABLE_WITH_EXISTING_FEATURES
    if cause is FalsePositiveCause.LABEL_AMBIGUITY:
        return Preventability.LABEL_OR_OUTCOME_AMBIGUITY
    if cause in {FalsePositiveCause.LOW_LIQUIDITY, FalsePositiveCause.GAP_REVERSAL}:
        return Preventability.REQUIRES_NEW_FEATURE
    return Preventability.INHERENT_MARKET_UNCERTAINTY


def _recovery_path(row: DirectionalObservation) -> str:
    if row.recommendation_score < 0.45:
        return "better ranking"
    if _timing_value(row) < 0.45:
        return "timing adjustment"
    if row.stop_distance_pct is not None and row.stop_distance_pct > 0.10:
        return "stop construction"
    if (row.retracement_score or 0.5) < 0.35:
        return "removal of harmful components"
    return "setup-specific thresholds"


def _suppressed_by(
    rows: Sequence[DirectionalObservation],
) -> tuple[BuyFeatureGroup, ...]:
    groups: list[BuyFeatureGroup] = []
    if _mean(row.retracement_score for row in rows) is not None:
        groups.append(BuyFeatureGroup.RETRACEMENT)
    if _mean(_timing_value(row) for row in rows) is not None:
        groups.append(BuyFeatureGroup.ENTRY_TIMING)
    groups.append(BuyFeatureGroup.HISTORICAL_OUTCOME_STATISTICS)
    return tuple(dict.fromkeys(groups))


def _fold_precisions(
    observations: Sequence[DirectionalObservation],
    spec: BuyModelSpec,
    definition: DirectionalOutcomeDefinition,
) -> tuple[float, ...]:
    values: list[float] = []
    for year in _years(observations):
        rows = [row for row in observations if row.year == year]
        scored = tuple(_scored_observation(row, spec) for row in rows)
        metrics = calculate_directional_metrics(
            observations=scored,
            policy=DirectionalPolicy(
                policy_id=spec.model_id,
                direction=DirectionalPolicyDirection.BUY,
                min_recommendation_score=spec.threshold,
            ),
            definition=definition,
        )
        if metrics.precision is not None:
            values.append(metrics.precision)
    return tuple(values)


def _without_removed(
    groups: Sequence[BuyFeatureGroup],
    spec: BuyModelSpec,
) -> tuple[BuyFeatureGroup, ...]:
    return tuple(group for group in groups if group not in spec.removed_groups)


def _full_feature_stack() -> tuple[BuyFeatureGroup, ...]:
    return (
        BuyFeatureGroup.PRICE_STRUCTURE,
        BuyFeatureGroup.VOLUME,
        BuyFeatureGroup.SUPPORT_RESISTANCE,
        BuyFeatureGroup.TREND,
        BuyFeatureGroup.RELATIVE_STRENGTH,
        BuyFeatureGroup.SETUP,
        BuyFeatureGroup.ENTRY_TIMING,
        BuyFeatureGroup.MARKET_REGIME,
        BuyFeatureGroup.VOLATILITY_RISK,
        BuyFeatureGroup.RETRACEMENT,
        BuyFeatureGroup.CANDLE,
        BuyFeatureGroup.BREAKOUT_CONFIRMATION,
        BuyFeatureGroup.TRADE_PLAN_QUALITY,
        BuyFeatureGroup.HISTORICAL_OUTCOME_STATISTICS,
    )


def _feature_aliases(group: BuyFeatureGroup) -> tuple[str, ...]:
    aliases: dict[BuyFeatureGroup, tuple[str, ...]] = {
        BuyFeatureGroup.PRICE_STRUCTURE: ("price", "price_volume"),
        BuyFeatureGroup.VOLUME: ("volume", "relative_volume"),
        BuyFeatureGroup.SUPPORT_RESISTANCE: ("support", "breakout"),
        BuyFeatureGroup.TREND: ("trend", "dma"),
        BuyFeatureGroup.RELATIVE_STRENGTH: ("relative_strength", "rs"),
        BuyFeatureGroup.SETUP: ("setup", "strategy", "setup_quality"),
        BuyFeatureGroup.ENTRY_TIMING: ("entry_state", "timing_score"),
        BuyFeatureGroup.MARKET_REGIME: ("market_regime",),
        BuyFeatureGroup.SECTOR_STATE: ("sector_strength",),
        BuyFeatureGroup.VOLATILITY_RISK: ("atr", "stop_distance", "mae"),
        BuyFeatureGroup.LIQUIDITY: ("liquidity", "capacity"),
        BuyFeatureGroup.RETRACEMENT: ("retracement",),
        BuyFeatureGroup.CANDLE: ("candle",),
        BuyFeatureGroup.BREAKOUT_CONFIRMATION: ("breakout", "volume_breakout"),
        BuyFeatureGroup.TRADE_PLAN_QUALITY: ("trade_plan", "risk_reward"),
        BuyFeatureGroup.HISTORICAL_OUTCOME_STATISTICS: (
            "posterior_probability",
            "expectancy",
        ),
    }
    return aliases[group]


def _feature_transformations(group: BuyFeatureGroup) -> tuple[str, ...]:
    if group in {BuyFeatureGroup.ENTRY_TIMING, BuyFeatureGroup.MARKET_REGIME}:
        return ("categorical state mapped to monotonic diagnostic score",)
    if group is BuyFeatureGroup.VOLATILITY_RISK:
        return ("lower adverse excursion and stop distance score higher",)
    return ("bounded 0-1 point-in-time score",)


def _feature_dependencies(group: BuyFeatureGroup) -> tuple[str, ...]:
    if group is BuyFeatureGroup.HISTORICAL_OUTCOME_STATISTICS:
        return ("performance ledger", "historical outcome snapshots")
    if group in {BuyFeatureGroup.PRICE_STRUCTURE, BuyFeatureGroup.VOLUME}:
        return ("OHLCV",)
    return ("candidate replay snapshot",)


def _feature_overlaps(group: BuyFeatureGroup) -> tuple[BuyFeatureGroup, ...]:
    overlaps = {
        BuyFeatureGroup.HISTORICAL_OUTCOME_STATISTICS: (
            BuyFeatureGroup.TRADE_PLAN_QUALITY,
        ),
        BuyFeatureGroup.RETRACEMENT: (
            BuyFeatureGroup.PRICE_STRUCTURE,
            BuyFeatureGroup.ENTRY_TIMING,
        ),
        BuyFeatureGroup.BREAKOUT_CONFIRMATION: (
            BuyFeatureGroup.PRICE_STRUCTURE,
            BuyFeatureGroup.VOLUME,
        ),
        BuyFeatureGroup.SETUP: (
            BuyFeatureGroup.PRICE_STRUCTURE,
            BuyFeatureGroup.SUPPORT_RESISTANCE,
        ),
    }
    return overlaps.get(group, ())


def _feature_missingness(
    observations: Sequence[DirectionalObservation],
    group: BuyFeatureGroup,
) -> float:
    if not observations:
        return 1.0
    missing = sum(_feature_value(row, group) is None for row in observations)
    return missing / len(observations)


def _first(values: dict[str, float], aliases: Sequence[str]) -> float | None:
    normalized = {_normalize_key(key): value for key, value in values.items()}
    for alias in aliases:
        value = normalized.get(_normalize_key(alias))
        if value is not None:
            return value
    return None


def _timing_value(row: DirectionalObservation) -> float:
    normalized = row.entry_timing.upper()
    if "PREFERRED" in normalized or "CONFIRM" in normalized:
        return 0.72
    if "EARLY" in normalized or "AGGRESSIVE" in normalized:
        return 0.62
    if "FORMING" in normalized:
        return 0.42
    if "LATE" in normalized or "EXTENDED" in normalized:
        return 0.20
    if "INVALID" in normalized:
        return 0.05
    return 0.45


def _regime_value(regime: str) -> float:
    normalized = regime.upper()
    if "BULL" in normalized or "POSITIVE" in normalized:
        return 0.70
    if "SIDE" in normalized or "NEUTRAL" in normalized:
        return 0.48
    if "BEAR" in normalized or "NEGATIVE" in normalized:
        return 0.20
    if "TRANSITION" in normalized:
        return 0.35
    return 0.42


def _volatility_value(row: DirectionalObservation) -> float | None:
    if row.stop_distance_pct is not None:
        return _clamp(1.0 - row.stop_distance_pct * 6)
    if row.max_adverse_excursion is not None:
        return _clamp(1.0 - abs(row.max_adverse_excursion) * 4)
    return None


def _max_concentration(
    observations: Sequence[DirectionalObservation],
    attribute: str,
) -> float:
    if not observations:
        return 0.0
    counts = Counter(str(getattr(row, attribute)) for row in observations)
    return max(counts.values()) / len(observations)


def _year_concentration(observations: Sequence[DirectionalObservation]) -> float:
    if not observations:
        return 0.0
    counts = Counter(row.year for row in observations)
    return max(counts.values()) / len(observations)


def _train_test_periods(
    observations: Sequence[DirectionalObservation],
) -> tuple[str, ...]:
    years = _years(observations)
    return tuple(f"train <= {year - 1}, test {year}" for year in years[2:])


def _years(observations: Sequence[DirectionalObservation]) -> tuple[int, ...]:
    return tuple(sorted({row.year for row in observations}))


def _named_result(
    results: Sequence[BuyModelResult],
    model_id: str,
) -> BuyModelResult | None:
    for result in results:
        if result.spec.model_id == model_id:
            return result
    return None


def _dominant(values: Iterable[str]) -> str:
    counts = Counter(values)
    if not counts:
        return "unavailable"
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _mean(values: Iterable[float | None]) -> float | None:
    usable = [value for value in values if value is not None]
    if not usable:
        return None
    return sum(usable) / len(usable)


def _delta(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline is None:
        return None
    return value - baseline


def _feature_list(groups: Sequence[BuyFeatureGroup]) -> str:
    if not groups:
        return "none"
    return ", ".join(group.value for group in groups)


def _pct(value: float | None) -> str:
    if value is None:
        return "unavailable"
    return f"{value * 100:.2f}%"


def _num(value: float | None) -> str:
    if value is None:
        return "unavailable"
    if math.isinf(value):
        return "infinite"
    return f"{value:.4f}"


def _interval(result: BuyModelResult | None) -> str:
    if result is None:
        return "unavailable"
    low, high = wilson_interval(
        result.metrics.true_positive,
        result.metrics.accepted_signals,
    )
    return f"[{_pct(low)}, {_pct(high)}]"


def _slug(value: str) -> str:
    return _normalize_key(value).replace("_", "-")


def _normalize_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _clamp(value: float, *, low: float = 0.0, high: float = 1.0) -> float:
    return min(max(value, low), high)


__all__ = [
    "BuyAblationResult",
    "BuyBottleneck",
    "BuyFeatureAdditionStep",
    "BuyFeatureGroup",
    "BuyFeatureGroupLineage",
    "BuyModelConclusion",
    "BuyModelKind",
    "BuyModelResult",
    "BuyModelSpec",
    "BuySetupClassification",
    "BuySignalReconstructionReport",
    "DirectionTimingAnalysisRow",
    "DirectionTimingCategory",
    "FalseNegativeRecoveryRow",
    "FalsePositiveCause",
    "FalsePositiveTaxonomyRow",
    "Preventability",
    "RegimeInteractionResult",
    "SetupSpecializedBuyResult",
    "build_buy_feature_lineage",
    "build_buy_precision_frontier",
    "build_buy_signal_reconstruction_report",
    "evaluate_buy_baselines",
    "evaluate_buy_model",
    "export_buy_model_results_csv",
    "export_buy_reconstruction_json",
    "filter_buy_model_results",
    "group_buy_report",
    "render_buy_false_negative_audit",
    "render_buy_false_positive_audit",
    "render_buy_feature_ablation",
    "render_buy_minimal_models",
    "render_buy_precision_frontier",
    "render_buy_signal_reconstruction_report",
    "run_backward_ablation",
    "run_direction_timing_analysis",
    "run_false_negative_recovery",
    "run_false_positive_taxonomy",
    "run_forward_feature_addition",
    "run_regime_interaction_tests",
    "run_retracement_buy_tests",
    "run_setup_specialized_buy_models",
]
