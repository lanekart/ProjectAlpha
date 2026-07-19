from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, replace
from decimal import Decimal
from hashlib import sha256

from alpha.forward_validation.validation_registry import ForwardValidationRegistry
from alpha.research.research_registry import ResearchExperimentRegistry
from alpha.strategy_discovery.candidate_strategy_generator import (
    CandidateStrategyGenerator,
)
from alpha.strategy_discovery.feature_manifest import FeatureManifest
from alpha.strategy_discovery.historical_signal_generator import (
    HistoricalSignalGenerator,
)
from alpha.strategy_discovery.models import (
    DiscoveryDataset,
    DiscoveryRunConfig,
    GeneralisationClassification,
    HistoricalTruthClass,
    MultipleTestingResult,
    RobustnessResult,
    SearchSpaceManifest,
    StrategyDiscoveryReport,
    StrategyEvaluation,
    StrategyLeaderboardEntry,
    StrategySpecification,
)
from alpha.strategy_discovery.multiple_testing_control import MultipleTestingControl
from alpha.strategy_discovery.research_integration import record_discovery_experiment
from alpha.strategy_discovery.robustness_engine import RobustnessEngine
from alpha.strategy_discovery.strategy_evaluator import StrategyEvaluator
from alpha.strategy_discovery.strategy_registry import (
    StrategyRegistry,
    dataset_payload,
)
from alpha.strategy_discovery.walk_forward_engine import (
    ChronologicalPartition,
    WalkForwardEngine,
)


@dataclass(frozen=True, slots=True)
class DiscoveryArtifacts:
    dataset: DiscoveryDataset
    strategies: tuple[StrategySpecification, ...]
    search_manifest: SearchSpaceManifest
    partition: ChronologicalPartition
    evaluations: tuple[StrategyEvaluation, ...]


class StrategyDiscoveryService:
    """Run bounded discovery without crossing the production policy boundary."""

    def __init__(
        self,
        *,
        signal_generator: HistoricalSignalGenerator | None = None,
        feature_manifest: FeatureManifest | None = None,
        candidate_generator: CandidateStrategyGenerator | None = None,
        walk_forward: WalkForwardEngine | None = None,
        evaluator: StrategyEvaluator | None = None,
        robustness: RobustnessEngine | None = None,
        multiple_testing: MultipleTestingControl | None = None,
        registry: StrategyRegistry | None = None,
        research_registry: ResearchExperimentRegistry | None = None,
        config: DiscoveryRunConfig | None = None,
    ) -> None:
        self.feature_manifest = feature_manifest or FeatureManifest()
        self.signal_generator = signal_generator or HistoricalSignalGenerator(
            feature_manifest=self.feature_manifest
        )
        self.candidate_generator = candidate_generator or CandidateStrategyGenerator(
            feature_manifest=self.feature_manifest
        )
        self.walk_forward = walk_forward or WalkForwardEngine()
        self.evaluator = evaluator or StrategyEvaluator()
        self.robustness = robustness or RobustnessEngine(evaluator=self.evaluator)
        self.multiple_testing = multiple_testing or MultipleTestingControl()
        self.registry = registry or StrategyRegistry()
        self.research_registry = research_registry or ResearchExperimentRegistry()
        self.config = config or DiscoveryRunConfig()

    def discover(self) -> DiscoveryArtifacts:
        dataset = self.signal_generator.discovery_dataset()
        strategies, manifest = self.candidate_generator.generate(
            dataset=dataset,
            config=self.config,
        )
        partition = self.walk_forward.partition(dataset=dataset, config=self.config)
        evaluations = self._evaluate_without_holdout(
            strategies=strategies,
            partition=partition,
            dataset=dataset,
        )
        self.registry.record_search(
            dataset_payload=dataset_payload(dataset),
            manifest=manifest,
            strategies=strategies,
        )
        return DiscoveryArtifacts(
            dataset=dataset,
            strategies=strategies,
            search_manifest=manifest,
            partition=partition,
            evaluations=evaluations,
        )

    def report(self) -> StrategyDiscoveryReport:
        artifacts = self.discover()
        shortlisted = _shortlist(artifacts.evaluations, self.config)
        evaluations = self._with_holdout(
            artifacts=artifacts,
            shortlisted=shortlisted,
        )
        hypotheses = len(
            tuple(item for item in evaluations if not item.strategy.benchmark)
        )
        entries: list[StrategyLeaderboardEntry] = []
        for evaluation in evaluations:
            robustness = self.robustness.evaluate(
                strategy=evaluation.strategy,
                evaluation=evaluation,
                partition=artifacts.partition,
                config=self.config,
            )
            test = self.multiple_testing.evaluate(
                strategy_version=evaluation.strategy.strategy_version,
                returns=self.evaluator.net_returns(
                    evaluation.strategy,
                    artifacts.partition.validation_rows,
                    self.config,
                ),
                hypotheses_tested=hypotheses,
            )
            classification, reasons = classify_strategy(
                dataset=artifacts.dataset,
                evaluation=evaluation,
                robustness=robustness,
                multiple_testing=test,
                config=self.config,
            )
            entries.append(
                StrategyLeaderboardEntry(
                    rank=0,
                    strategy=evaluation.strategy,
                    evaluation=evaluation,
                    robustness=robustness,
                    multiple_testing=test,
                    classification=classification,
                    classification_reasons=reasons,
                )
            )
        ordered = tuple(
            replace(entry, rank=index)
            for index, entry in enumerate(
                sorted(entries, key=_leaderboard_key, reverse=True),
                start=1,
            )
        )
        candidates = tuple(entry for entry in ordered if not entry.strategy.benchmark)
        benchmarks = tuple(entry for entry in ordered if entry.strategy.benchmark)
        qualified = tuple(
            entry
            for entry in candidates
            if entry.classification
            is GeneralisationClassification.SHADOW_VALIDATION_CANDIDATE
        )
        decision = (
            f"PUBLISH_{qualified[0].strategy.strategy_version}_TO_SHADOW_VALIDATION"
            if qualified
            else "NO_GENERALISABLE_STRATEGY_FOUND"
        )
        reason_counts = Counter(
            reason for entry in candidates for reason in entry.classification_reasons
        )
        dominant = tuple(
            reason
            for reason, _ in sorted(
                reason_counts.items(), key=lambda item: (-item[1], item[0])
            )[:5]
        )
        report = StrategyDiscoveryReport(
            generated_at=artifacts.dataset.generated_at,
            dataset=artifacts.dataset,
            feature_manifest=self.feature_manifest.definitions,
            search_manifest=artifacts.search_manifest,
            folds=artifacts.partition.folds,
            leaderboard=candidates,
            benchmark_entries=benchmarks,
            decision=decision,
            dominant_failure_reasons=dominant,
            highest_value_evidence_gap=_evidence_gap(artifacts.dataset),
            current_forward_evidence=_forward_evidence(),
        )
        self.registry.record_leaderboard(
            dataset_version=artifacts.dataset.dataset_version,
            entries=ordered,
            decision=decision,
        )
        record_discovery_experiment(report, registry=self.research_registry)
        return report

    def _evaluate_without_holdout(
        self,
        *,
        strategies: tuple[StrategySpecification, ...],
        partition: ChronologicalPartition,
        dataset: DiscoveryDataset,
    ) -> tuple[StrategyEvaluation, ...]:
        by_id = {row.candidate_id: row for row in dataset.rows}
        return tuple(
            self.evaluator.walk_forward_evaluation(
                strategy=strategy,
                partition=partition,
                rows_by_id=by_id,
                config=self.config,
            )
            for strategy in strategies
        )

    def _with_holdout(
        self,
        *,
        artifacts: DiscoveryArtifacts,
        shortlisted: tuple[StrategyEvaluation, ...],
    ) -> tuple[StrategyEvaluation, ...]:
        if not shortlisted:
            return artifacts.evaluations
        versions = tuple(item.strategy.strategy_version for item in shortlisted)
        access_id = sha256(
            f"{artifacts.dataset.dataset_version}|{'|'.join(sorted(versions))}|final-shortlist".encode()
        ).hexdigest()[:24]
        by_id = {row.candidate_id: row for row in artifacts.dataset.rows}
        shortlisted_by_version = {
            item.strategy.strategy_version for item in shortlisted
        }
        evaluated = tuple(
            self.evaluator.walk_forward_evaluation(
                strategy=item.strategy,
                partition=artifacts.partition,
                rows_by_id=by_id,
                config=self.config,
                holdout_access_id=(
                    access_id
                    if item.strategy.strategy_version in shortlisted_by_version
                    else None
                ),
            )
            for item in artifacts.evaluations
        )
        result_payload = [
            {
                "version": item.strategy.strategy_version,
                "holdout": (
                    None
                    if item.holdout_metrics is None
                    else {
                        "trades": item.holdout_metrics.completed_trades,
                        "expectancy": str(item.holdout_metrics.expectancy_pct),
                        "drawdown": str(item.holdout_metrics.maximum_drawdown_pct),
                    }
                ),
            }
            for item in evaluated
            if item.strategy.strategy_version in shortlisted_by_version
        ]
        result_hash = sha256(
            json.dumps(result_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.registry.record_holdout_access(
            dataset_version=artifacts.dataset.dataset_version,
            strategy_versions=versions,
            purpose="ONE_TIME_FINAL_SHORTLIST_EVALUATION",
            result_hash=result_hash,
            accessed_at=artifacts.dataset.generated_at,
        )
        return evaluated


def classify_strategy(
    *,
    dataset: DiscoveryDataset,
    evaluation: StrategyEvaluation,
    robustness: RobustnessResult,
    multiple_testing: MultipleTestingResult,
    config: DiscoveryRunConfig,
) -> tuple[GeneralisationClassification, tuple[str, ...]]:
    reasons: list[str] = []
    if dataset.population_class is not HistoricalTruthClass.AUTHORITATIVE:
        return (
            GeneralisationClassification.INVALID_DATA,
            (
                "historical evaluation uses a separately labelled reconstructed "
                "population",
                "authoritative identity and corporate-action coverage is insufficient",
            ),
        )
    training = evaluation.training_metrics
    validation = evaluation.validation_metrics
    holdout = evaluation.holdout_metrics
    if (
        training.completed_trades < config.constraints.minimum_total_completed_trades
        or validation.completed_trades
        < config.constraints.minimum_completed_trades_per_fold
    ):
        return (
            GeneralisationClassification.INSUFFICIENT_SAMPLE,
            (
                "completed-trade evidence does not meet the explicit research "
                "constraint",
            ),
        )
    fold_positive = sum(
        1
        for item in evaluation.fold_evaluations
        if item.stage.value == "VALIDATION"
        and item.metrics.expectancy_pct is not None
        and item.metrics.expectancy_pct > Decimal("0")
    )
    if fold_positive < config.constraints.minimum_positive_expectancy_folds:
        return (
            GeneralisationClassification.OVERFIT,
            ("too few chronological validation folds have positive expectancy",),
        )
    if training.expectancy_pct is None or training.expectancy_pct <= Decimal("0"):
        return (
            GeneralisationClassification.NEGATIVE_EXPECTANCY,
            ("training expectancy after explicit costs is not positive",),
        )
    if validation.expectancy_pct is None or validation.expectancy_pct <= Decimal("0"):
        return (
            GeneralisationClassification.OVERFIT,
            ("positive training edge does not persist in validation",),
        )
    if holdout is None:
        return (
            GeneralisationClassification.INSUFFICIENT_SAMPLE,
            ("strategy was not selected for one-time holdout evaluation",),
        )
    if holdout.expectancy_pct is None or holdout.expectancy_pct <= Decimal("0"):
        return (
            GeneralisationClassification.OVERFIT,
            ("validation edge materially fails on untouched holdout",),
        )
    if (
        _degradation(training.expectancy_pct, validation.expectancy_pct)
        > config.constraints.maximum_validation_degradation_pct
    ):
        reasons.append(
            "training-to-validation expectancy degradation exceeds constraint"
        )
    if (
        _degradation(validation.expectancy_pct, holdout.expectancy_pct)
        > config.constraints.maximum_validation_degradation_pct
    ):
        reasons.append(
            "validation-to-holdout expectancy degradation exceeds constraint"
        )
    for metrics in (validation, holdout):
        if (
            metrics.maximum_drawdown_pct is not None
            and metrics.maximum_drawdown_pct > config.constraints.maximum_drawdown_pct
        ):
            reasons.append("drawdown exceeds the explicit research constraint")
    if robustness.weaknesses:
        reasons.extend(robustness.weaknesses)
    if reasons:
        return GeneralisationClassification.UNSTABLE, tuple(sorted(set(reasons)))
    if not multiple_testing.statistically_significant:
        return (
            GeneralisationClassification.NO_MATERIAL_EDGE,
            ("validation edge does not survive multiple-testing adjustment",),
        )
    if (
        robustness.symbol_concentration_pct is not None
        and robustness.symbol_concentration_pct > Decimal("40")
    ):
        return (
            GeneralisationClassification.ROBUST_BUT_LOW_CAPACITY,
            ("strategy observations are highly concentrated in one symbol",),
        )
    return (
        GeneralisationClassification.SHADOW_VALIDATION_CANDIDATE,
        ("all chronological, robustness, evidence, and multiplicity gates passed",),
    )


def _shortlist(
    evaluations: tuple[StrategyEvaluation, ...],
    config: DiscoveryRunConfig,
) -> tuple[StrategyEvaluation, ...]:
    eligible = tuple(
        item
        for item in evaluations
        if not item.strategy.benchmark
        and item.training_metrics.completed_trades
        >= config.constraints.minimum_total_completed_trades
        and item.validation_metrics.completed_trades
        >= config.constraints.minimum_completed_trades_per_fold
        and item.training_metrics.expectancy_pct is not None
        and item.training_metrics.expectancy_pct > Decimal("0")
        and item.validation_metrics.expectancy_pct is not None
        and item.validation_metrics.expectancy_pct > Decimal("0")
    )
    return tuple(sorted(eligible, key=_evaluation_key, reverse=True)[:5])


def _evaluation_key(item: StrategyEvaluation) -> tuple[Decimal, Decimal, int]:
    metrics = item.validation_metrics
    return (
        metrics.expectancy_pct or Decimal("-Infinity"),
        metrics.profit_factor or Decimal("-Infinity"),
        metrics.completed_trades,
    )


def _leaderboard_key(
    item: StrategyLeaderboardEntry,
) -> tuple[int, Decimal, Decimal, int]:
    classification_rank = {
        GeneralisationClassification.SHADOW_VALIDATION_CANDIDATE: 8,
        GeneralisationClassification.ROBUST_BUT_LOW_CAPACITY: 7,
        GeneralisationClassification.NO_MATERIAL_EDGE: 6,
        GeneralisationClassification.UNSTABLE: 5,
        GeneralisationClassification.OVERFIT: 4,
        GeneralisationClassification.NEGATIVE_EXPECTANCY: 3,
        GeneralisationClassification.INSUFFICIENT_SAMPLE: 2,
        GeneralisationClassification.LEAKAGE_RISK: 1,
        GeneralisationClassification.INVALID_DATA: 0,
    }[item.classification]
    metrics = item.evaluation.validation_metrics
    return (
        classification_rank,
        metrics.expectancy_pct or Decimal("-Infinity"),
        metrics.profit_factor or Decimal("-Infinity"),
        metrics.completed_trades,
    )


def _degradation(prior: Decimal, current: Decimal) -> Decimal:
    if prior <= Decimal("0") or current >= prior:
        return Decimal("0")
    return (prior - current) / abs(prior) * Decimal("100")


def _evidence_gap(dataset: DiscoveryDataset) -> str:
    if dataset.population_class is HistoricalTruthClass.RECONSTRUCTED:
        return (
            "Expand authoritative point-in-time decision provenance, identity, and "
            "corporate-action coverage before strategy publication."
        )
    return "Collect immutable forward outcomes for any qualified shadow cohort."


def _forward_evidence() -> str:
    registry = ForwardValidationRegistry()
    snapshots = registry.load_snapshots()
    events = registry.load_events()
    completed = sum(
        1
        for event in events
        if event.event_type.value
        in {"STOP_HIT", "TARGET_3_HIT", "TRAILING_STOP_HIT", "TIME_EXIT"}
        or event.metadata.get("terminal") == "true"
    )
    return (
        f"APPROVAL_POLICY_V1 immutable snapshots={len(snapshots)}, "
        f"completed shadow positions={completed}; no strategy-discovery cohort mixed."
    )


__all__ = [
    "DiscoveryArtifacts",
    "StrategyDiscoveryService",
    "classify_strategy",
]
