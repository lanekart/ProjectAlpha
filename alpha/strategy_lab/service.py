from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from alpha.research.research_registry import ResearchExperimentRegistry
from alpha.strategy_discovery.historical_signal_generator import (
    HistoricalSignalGenerator,
)
from alpha.strategy_discovery.models import DiscoveryDataset, HistoricalTruthClass
from alpha.strategy_lab.backtest_engine import (
    BacktestRequest,
    StrategyLabBacktestEngine,
)
from alpha.strategy_lab.combination_attribution import CombinationAttributionEngine
from alpha.strategy_lab.combination_generator import (
    CombinationGenerator,
    GenerationRequest,
)
from alpha.strategy_lab.component_attribution import ComponentAttributionEngine
from alpha.strategy_lab.execution_assumptions import default_execution_profile
from alpha.strategy_lab.experiment_registry import StrategyLabExperimentRegistry
from alpha.strategy_lab.indicator_registry import IndicatorRegistry
from alpha.strategy_lab.leaderboard import StrategyLeaderboard
from alpha.strategy_lab.models import (
    STRATEGY_LAB_SCHEMA_VERSION,
    ExecutionAssumptionProfile,
    IndicatorDefinition,
    LabEvidenceClass,
    LabStrategySpecification,
    SearchSpaceSummary,
    StrategyClassification,
    StrategyLabReport,
    StrategyTemplate,
)
from alpha.strategy_lab.research_integration import record_lab_experiment
from alpha.strategy_lab.strategy_template_registry import StrategyTemplateRegistry


@dataclass(frozen=True, slots=True)
class StrategyLabInventory:
    indicators: tuple[IndicatorDefinition, ...]
    templates: tuple[StrategyTemplate, ...]


@dataclass(frozen=True, slots=True)
class GeneratedLabStrategies:
    dataset: DiscoveryDataset
    strategies: tuple[LabStrategySpecification, ...]
    search_space: SearchSpaceSummary
    execution_profile: ExecutionAssumptionProfile


class StrategyLabService:
    """Coordinate bounded strategy research without modifying production policy."""

    def __init__(
        self,
        *,
        signal_generator: HistoricalSignalGenerator | None = None,
        indicator_registry: IndicatorRegistry | None = None,
        template_registry: StrategyTemplateRegistry | None = None,
        combination_generator: CombinationGenerator | None = None,
        backtest_engine: StrategyLabBacktestEngine | None = None,
        experiment_registry: StrategyLabExperimentRegistry | None = None,
        research_registry: ResearchExperimentRegistry | None = None,
    ) -> None:
        self.signal_generator = signal_generator or HistoricalSignalGenerator()
        self.indicators = indicator_registry or IndicatorRegistry()
        self.templates = template_registry or StrategyTemplateRegistry()
        self.generator = combination_generator or CombinationGenerator(
            indicators=self.indicators
        )
        self.backtest_engine = backtest_engine or StrategyLabBacktestEngine()
        self.experiment_registry = (
            experiment_registry or StrategyLabExperimentRegistry()
        )
        self.research_registry = research_registry or ResearchExperimentRegistry()
        self.component_attribution = ComponentAttributionEngine(self.indicators)
        self.combination_attribution = CombinationAttributionEngine()
        self.leaderboard = StrategyLeaderboard()

    def inventory(self) -> StrategyLabInventory:
        return StrategyLabInventory(
            indicators=self.indicators.definitions,
            templates=self.templates.templates,
        )

    def generate(
        self,
        *,
        request: GenerationRequest | None = None,
        execution_profile: ExecutionAssumptionProfile | None = None,
    ) -> GeneratedLabStrategies:
        settings = request or GenerationRequest()
        profile = execution_profile or default_execution_profile()
        dataset = self.signal_generator.discovery_dataset()
        strategies, search_space = self.generator.generate(
            dataset=dataset,
            request=settings,
            execution_profile=profile,
        )
        return GeneratedLabStrategies(
            dataset=dataset,
            strategies=strategies,
            search_space=search_space,
            execution_profile=profile,
        )

    def report(
        self,
        *,
        generation_request: GenerationRequest | None = None,
        backtest_request: BacktestRequest | None = None,
        execution_profile: ExecutionAssumptionProfile | None = None,
        persist: bool = True,
    ) -> StrategyLabReport:
        generated = self.generate(
            request=generation_request,
            execution_profile=execution_profile,
        )
        run = self.backtest_engine.run(
            dataset=generated.dataset,
            strategies=generated.strategies,
            profile=generated.execution_profile,
            request=backtest_request,
        )
        ordered = self.leaderboard.rank(run.results)
        component = self.component_attribution.analyze(run.results)
        combination = self.combination_attribution.analyze(
            run.results,
            population_count=len(run.eligible_rows),
        )
        strongest = next(
            (
                item
                for item in ordered
                if not item.strategy.benchmark and item.research_score is not None
            ),
            None,
        )
        qualified = tuple(
            item
            for item in ordered
            if item.classification
            in {
                StrategyClassification.WALK_FORWARD_CANDIDATE,
                StrategyClassification.SHADOW_VALIDATION_CANDIDATE,
            }
        )
        conclusion = _conclusion(qualified)
        experiment_id = (
            "strategy-lab-"
            + sha256(
                (
                    generated.dataset.dataset_version
                    + "|"
                    + generated.search_space.search_space_hash
                    + "|"
                    + STRATEGY_LAB_SCHEMA_VERSION
                ).encode()
            ).hexdigest()[:20]
        )
        report = StrategyLabReport(
            generated_at=generated.dataset.generated_at,
            experiment_id=experiment_id,
            dataset_version=generated.dataset.dataset_version,
            evidence_class=_evidence_class(generated.dataset),
            source_rows=run.source_rows,
            excluded_rows=len(generated.dataset.exclusions),
            indicators=self.indicators.definitions,
            templates=self.templates.templates,
            search_space=generated.search_space,
            execution_profile=generated.execution_profile,
            results=ordered,
            component_attribution=component,
            combination_attribution=combination,
            final_conclusion=conclusion,
            strongest_strategy_id=(
                None if strongest is None else strongest.strategy.strategy_id
            ),
            highest_value_evidence_gap=(
                "Authoritative completed outcomes with corporate-action-complete "
                "bar histories are required for fill, stop, target, and holdout "
                "validation."
            ),
        )
        if persist:
            self.experiment_registry.record(report)
            record_lab_experiment(report, registry=self.research_registry)
        return report


def _evidence_class(dataset: DiscoveryDataset) -> LabEvidenceClass:
    if dataset.population_class is HistoricalTruthClass.AUTHORITATIVE:
        return LabEvidenceClass.AUTHORITATIVE
    return LabEvidenceClass.RECONSTRUCTED


def _conclusion(results: tuple[object, ...]) -> str:
    from alpha.strategy_lab.models import LabStrategyResult

    candidates = tuple(item for item in results if isinstance(item, LabStrategyResult))
    if not candidates:
        return "NO_RELIABLE_STRATEGY_FOUND"
    top = candidates[0]
    if top.classification is StrategyClassification.SHADOW_VALIDATION_CANDIDATE:
        return f"RECOMMEND_{top.strategy.strategy_id}_FOR_SHADOW_VALIDATION"
    return f"RECOMMEND_{top.strategy.strategy_id}_FOR_WALK_FORWARD_VALIDATION"


__all__ = [
    "GeneratedLabStrategies",
    "StrategyLabInventory",
    "StrategyLabService",
]
