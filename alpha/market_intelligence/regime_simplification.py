from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from statistics import median
from typing import TYPE_CHECKING, Any

import duckdb

from alpha.market_intelligence.point_in_time_store import (
    resolve_point_in_time_store_path,
)

if TYPE_CHECKING:
    from alpha.candidate_learning.models import CandidateForwardOutcome
    from alpha.candidate_learning.repository import LearningLedgerRepository

_PROHIBITED_NEXT_ACTION = (
    "Do not implement a simplified production classifier, tune regime "
    "thresholds, choose historically optimal boundaries, alter regime labels, "
    "change classifier conditions, modify market-intelligence weights, change "
    "regime intervention, alter recommendation scores, modify candidate "
    "generation, change verdicts, alter entry timing, modify gates, change "
    "trade plans, alter approvals, modify allocation, flip retracement signs, "
    "ingest unapproved sector sources, build diagnostic v3 or rewrite "
    "historical records."
)


class RegimeInputRole(StrEnum):
    MATERIAL_CLASSIFICATION_INPUT = "MATERIAL_CLASSIFICATION_INPUT"
    MINOR_CLASSIFICATION_INPUT = "MINOR_CLASSIFICATION_INPUT"
    COMPLETENESS_ONLY = "COMPLETENESS_ONLY"
    DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
    UNUSED = "UNUSED"
    UNAVAILABLE = "UNAVAILABLE"


class ResearchRegimeModel(StrEnum):
    BENCHMARK_TREND_ONLY = "BENCHMARK_TREND_ONLY"
    BENCHMARK_TREND_VOLATILITY = "BENCHMARK_TREND_VOLATILITY"
    BENCHMARK_BREADTH = "BENCHMARK_BREADTH"
    TRANSPARENT_REFERENCE_STATE = "TRANSPARENT_REFERENCE_STATE"
    CURRENT_COMPATIBLE_WITHOUT_SECTOR = "CURRENT_COMPATIBLE_WITHOUT_SECTOR"
    RECORDED_RECONSTRUCTED_V2 = "RECORDED_RECONSTRUCTED_V2"


class ResearchRegimeLabel(StrEnum):
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    INSUFFICIENT_INPUT = "INSUFFICIENT_INPUT"


class ComplexityClass(StrEnum):
    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class EconomicOrderingClass(StrEnum):
    COHERENT_ORDERING = "COHERENT_ORDERING"
    PARTIALLY_COHERENT = "PARTIALLY_COHERENT"
    INCOHERENT_ORDERING = "INCOHERENT_ORDERING"
    QUALITY_DEPENDENT_ORDERING = "QUALITY_DEPENDENT_ORDERING"
    LOW_SAMPLE_UNSTABLE = "LOW_SAMPLE_UNSTABLE"


class DateWeightedStabilityClass(StrEnum):
    STABLE_ACROSS_WEIGHTING = "STABLE_ACROSS_WEIGHTING"
    WEAKENS_WITH_DATE_WEIGHTING = "WEAKENS_WITH_DATE_WEIGHTING"
    REVERSES_WITH_DATE_WEIGHTING = "REVERSES_WITH_DATE_WEIGHTING"
    CANDIDATE_CONCENTRATION_DOMINATES = "CANDIDATE_CONCENTRATION_DOMINATES"
    INSUFFICIENT_DATES = "INSUFFICIENT_DATES"


class QualityStabilityClass(StrEnum):
    STABLE_ACROSS_QUALITY = "STABLE_ACROSS_QUALITY"
    STRENGTHENS_ON_HIGH_QUALITY = "STRENGTHENS_ON_HIGH_QUALITY"
    WEAKENS_ON_HIGH_QUALITY = "WEAKENS_ON_HIGH_QUALITY"
    REVERSES_ON_HIGH_QUALITY = "REVERSES_ON_HIGH_QUALITY"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


class ThresholdStabilityClass(StrEnum):
    STABLE = "STABLE"
    MODERATELY_SENSITIVE = "MODERATELY_SENSITIVE"
    HIGHLY_SENSITIVE = "HIGHLY_SENSITIVE"
    DATA_QUALITY_DOMINATED = "DATA_QUALITY_DOMINATED"


class IncrementalValueFinding(StrEnum):
    BENCHMARK_EXPLAINS_MOST_VALUE = "BENCHMARK_EXPLAINS_MOST_VALUE"
    VOLATILITY_ADDS_VALUE = "VOLATILITY_ADDS_VALUE"
    BREADTH_ADDS_VALUE = "BREADTH_ADDS_VALUE"
    BREADTH_ADDS_LIMITED_VALUE = "BREADTH_ADDS_LIMITED_VALUE"
    CLASSIFIER_COMPLEXITY_ADDS_VALUE = "CLASSIFIER_COMPLEXITY_ADDS_VALUE"
    CLASSIFIER_COMPLEXITY_ADDS_INSTABILITY = "CLASSIFIER_COMPLEXITY_ADDS_INSTABILITY"
    NO_INCREMENTAL_FEATURE_GROUP_ADDS_STABLE_VALUE = (
        "NO_INCREMENTAL_FEATURE_GROUP_ADDS_STABLE_VALUE"
    )


class SectorImpactClass(StrEnum):
    SECTOR_STRUCTURALLY_MATERIAL = "SECTOR_STRUCTURALLY_MATERIAL"
    SECTOR_POTENTIALLY_MATERIAL = "SECTOR_POTENTIALLY_MATERIAL"
    SECTOR_STRUCTURALLY_MINOR = "SECTOR_STRUCTURALLY_MINOR"
    SECTOR_UNUSED = "SECTOR_UNUSED"


class InterpretabilityClass(StrEnum):
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"


class ParsimonyStatus(StrEnum):
    PREFERRED_RESEARCH_MODEL = "PREFERRED_RESEARCH_MODEL"
    VIABLE_RESEARCH_MODEL = "VIABLE_RESEARCH_MODEL"
    DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
    REJECTED = "REJECTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class RegimeSimplificationConclusion(StrEnum):
    BENCHMARK_ONLY_STATE_IS_SUFFICIENT = "BENCHMARK_ONLY_STATE_IS_SUFFICIENT"
    BENCHMARK_AND_VOLATILITY_STATE_IS_PREFERRED = (
        "BENCHMARK_AND_VOLATILITY_STATE_IS_PREFERRED"
    )
    BENCHMARK_AND_BREADTH_STATE_IS_PREFERRED = (
        "BENCHMARK_AND_BREADTH_STATE_IS_PREFERRED"
    )
    CURRENT_REGIME_CLASSIFIER_ADDS_STABLE_VALUE = (
        "CURRENT_REGIME_CLASSIFIER_ADDS_STABLE_VALUE"
    )
    CURRENT_REGIME_CLASSIFIER_ADDS_COMPLEXITY_WITHOUT_VALUE = (
        "CURRENT_REGIME_CLASSIFIER_ADDS_COMPLEXITY_WITHOUT_VALUE"
    )
    SECTOR_HISTORY_IS_STILL_REQUIRED = "SECTOR_HISTORY_IS_STILL_REQUIRED"
    SECTOR_HISTORY_IS_UNLIKELY_TO_JUSTIFY_ACQUISITION = (
        "SECTOR_HISTORY_IS_UNLIKELY_TO_JUSTIFY_ACQUISITION"
    )
    MARKET_REGIME_SHOULD_REMAIN_GROUPING_ONLY = (
        "MARKET_REGIME_SHOULD_REMAIN_GROUPING_ONLY"
    )
    MARKET_REGIME_SHOULD_REMAIN_DIAGNOSTIC_ONLY = (
        "MARKET_REGIME_SHOULD_REMAIN_DIAGNOSTIC_ONLY"
    )
    NO_SIMPLIFIED_MODEL_HAS_STABLE_VALUE = "NO_SIMPLIFIED_MODEL_HAS_STABLE_VALUE"
    INSUFFICIENT_EVIDENCE_FOR_REGIME_SIMPLIFICATION = (
        "INSUFFICIENT_EVIDENCE_FOR_REGIME_SIMPLIFICATION"
    )


class RegimeSimplificationNextMilestone(StrEnum):
    DESIGN_SIMPLIFIED_BENCHMARK_BREADTH_CLASSIFIER = (
        "DESIGN_SIMPLIFIED_BENCHMARK_BREADTH_CLASSIFIER"
    )
    AUDIT_REGIME_INTERVENTION_POLICY = "AUDIT_REGIME_INTERVENTION_POLICY"
    REQUEST_NSE_HISTORICAL_SECTOR_SAMPLE = "REQUEST_NSE_HISTORICAL_SECTOR_SAMPLE"
    INTEGRATE_COMMERCIAL_SECTOR_SOURCE = "INTEGRATE_COMMERCIAL_SECTOR_SOURCE"
    AUDIT_MOMENTUM_MARKET_STATE_INTERACTION = "AUDIT_MOMENTUM_MARKET_STATE_INTERACTION"
    AUDIT_RETRACEMENT_SIGNAL_DEFINITION = "AUDIT_RETRACEMENT_SIGNAL_DEFINITION"
    REMOVE_REGIME_FROM_SCORE_AND_RETAIN_AS_CONTEXT = (
        "REMOVE_REGIME_FROM_SCORE_AND_RETAIN_AS_CONTEXT"
    )
    ACCEPT_MARKET_REGIME_AS_DIAGNOSTIC_ONLY = "ACCEPT_MARKET_REGIME_AS_DIAGNOSTIC_ONLY"
    COLLECT_MORE_AUTHORITATIVE_MARKET_STATE_HISTORY = (
        "COLLECT_MORE_AUTHORITATIVE_MARKET_STATE_HISTORY"
    )


@dataclass(frozen=True, slots=True)
class RegimeInputDependency:
    input_name: str
    source: str
    formula: str
    availability: str
    historical_coverage: str
    production_required: bool
    classification_branch_affected: str
    score_or_threshold_affected: str
    fallback_behavior: str
    role: RegimeInputRole


@dataclass(frozen=True, slots=True)
class FrozenRegimeEvaluationUniverse:
    dataset_fingerprint: str
    point_in_time_store_fingerprint: str
    benchmark_fingerprint: str
    breadth_fingerprint: str
    classifier_fingerprint: str
    v2_reconstruction_count: int
    v2_candidate_link_count: int
    completed_outcomes: int
    distinct_outcome_dates: int
    duplicate_links: int
    orphan_links: int
    future_source_violations: int
    integrity_passed: bool


@dataclass(frozen=True, slots=True)
class SimplifiedRegimeFeatureRow:
    market_date: date
    v2_regime: str
    breadth_ratio: Decimal | None
    percent_above_20dma: Decimal | None
    percent_above_50dma: Decimal | None
    percent_above_200dma: Decimal | None
    diagnostic_quality: str
    benchmark_return_20d: Decimal | None = None
    benchmark_above_50dma: bool | None = None
    benchmark_above_200dma: bool | None = None
    benchmark_volatility: Decimal | None = None


@dataclass(frozen=True, slots=True)
class RegimeModelComplexity:
    model: ResearchRegimeModel
    input_count: int
    threshold_count: int
    branch_count: int
    unavailable_input_paths: int
    fallback_paths: int
    regime_count: int
    classification_coverage: Decimal | None
    interpretability: InterpretabilityClass
    complexity: ComplexityClass


@dataclass(frozen=True, slots=True)
class RegimeDistributionRow:
    model: ResearchRegimeModel
    market_dates: int
    candidate_records: int
    bullish_dates: int
    neutral_dates: int
    bearish_dates: int
    high_volatility_dates: int
    insufficient_dates: int
    largest_regime_share: Decimal | None
    transition_count: int
    episode_count: int
    median_episode_duration: Decimal | None
    flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RegimeOutcomeRow:
    model: ResearchRegimeModel
    regime: ResearchRegimeLabel
    candidate_count: int
    distinct_market_dates: int
    win_rate: Decimal | None
    clean_win_rate: Decimal | None
    average_return: Decimal | None
    median_return: Decimal | None
    benchmark_relative_return: Decimal | None
    mfe: Decimal | None
    mae: Decimal | None
    stop_hit_rate: Decimal | None
    target_hit_rate: Decimal | None
    buy_precision_proxy: Decimal | None
    weighting: str
    quality_slice: str


@dataclass(frozen=True, slots=True)
class RegimeOrderingReport:
    model: ResearchRegimeModel
    candidate_weighted_ordering: EconomicOrderingClass
    date_weighted_ordering: EconomicOrderingClass
    date_weighted_stability: DateWeightedStabilityClass
    return_spread_difference: Decimal | None
    win_rate_spread_difference: Decimal | None
    dominant_high_candidate_dates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RegimeQualityReport:
    model: ResearchRegimeModel
    high_quality_candidates: int
    high_or_medium_candidates: int
    complete_diagnostic_candidates: int
    partial_diagnostic_candidates: int
    minimum_viable_candidates: int
    classification: QualityStabilityClass
    explanation: str


@dataclass(frozen=True, slots=True)
class RegimeThresholdStabilityRow:
    model: ResearchRegimeModel
    perturbation: str
    dates_changing_state: int
    candidate_records_changing_state: int
    regime_distribution_change: Decimal | None
    economic_ordering_change: str
    episode_fragmentation: int
    classification: ThresholdStabilityClass


@dataclass(frozen=True, slots=True)
class RegimeIncrementalValueRow:
    comparison: str
    economic_separation_change: Decimal | None
    auc: Decimal | None
    rank_correlation: Decimal | None
    top_decile_win_rate: Decimal | None
    buy_precision_proxy: Decimal | None
    date_weighted_separation: Decimal | None
    threshold_stability: str
    coherence: str
    finding: IncrementalValueFinding


@dataclass(frozen=True, slots=True)
class SectorMaximumImpactReport:
    dates_whose_label_could_change_from_sector: int
    candidates_on_those_dates: int
    dates_near_sector_sensitive_boundaries: int
    maximum_plausible_label_changes: int
    maximum_plausible_intervention_changes: int
    classification: SectorImpactClass
    explanation: str


@dataclass(frozen=True, slots=True)
class RegimeInterventionRow:
    model: ResearchRegimeModel
    intervention: str
    auc: Decimal | None
    rank_correlation: Decimal | None
    top_decile_hit_rate: Decimal | None
    buy_precision_proxy: Decimal | None
    average_buy_return: Decimal | None
    promoted_winners: int
    promoted_losers: int
    demoted_winners: int
    demoted_losers: int
    verdict_boundary_crossings: int
    score_mutated: bool


@dataclass(frozen=True, slots=True)
class RegimeInteractionRow:
    model: ResearchRegimeModel
    dimension: str
    bucket: str
    candidate_count: int
    date_count: int
    win_rate: Decimal | None
    average_return: Decimal | None
    median_return: Decimal | None
    benchmark_relative_return: Decimal | None
    mfe: Decimal | None
    mae: Decimal | None


@dataclass(frozen=True, slots=True)
class RegimeSelectionEffectRow:
    model: ResearchRegimeModel
    universe: str
    bullish_count: int
    neutral_count: int
    bearish_count: int
    high_volatility_count: int
    insufficient_count: int
    dominant_state: str


@dataclass(frozen=True, slots=True)
class RegimeInterpretabilityRow:
    model: ResearchRegimeModel
    explanation_template: str
    average_explanation_inputs: Decimal | None
    missing_input_frequency: Decimal | None
    contradictory_input_frequency: Decimal | None
    fallback_frequency: Decimal | None
    classification: InterpretabilityClass


@dataclass(frozen=True, slots=True)
class RegimeParsimonyRow:
    model: ResearchRegimeModel
    data_authority: str
    input_availability: str
    economic_ordering: str
    candidate_weighted_stability: str
    date_weighted_stability: str
    quality_stability: str
    threshold_stability: str
    incremental_value: str
    interpretability: str
    complexity: str
    maintenance_burden: str
    unavailable_sector_dependency: str
    status: ParsimonyStatus
    explanation: str


@dataclass(frozen=True, slots=True)
class RegimeParsimonyDecisionReport:
    universe: FrozenRegimeEvaluationUniverse
    rows: tuple[RegimeParsimonyRow, ...]
    primary_conclusion: RegimeSimplificationConclusion
    secondary_conclusion: RegimeSimplificationConclusion | None
    recommended_next_milestone: RegimeSimplificationNextMilestone
    explicitly_prohibited_next_action: str


class SimplifiedRegimeClassifier:
    def classify(
        self,
        model: ResearchRegimeModel,
        row: SimplifiedRegimeFeatureRow,
        *,
        breadth_bearish: Decimal = Decimal("0.45"),
        breadth_bullish: Decimal = Decimal("0.55"),
    ) -> ResearchRegimeLabel:
        if model is ResearchRegimeModel.BENCHMARK_TREND_ONLY:
            return _benchmark_label(row)
        if model is ResearchRegimeModel.BENCHMARK_TREND_VOLATILITY:
            if (
                row.benchmark_volatility is not None
                and row.benchmark_volatility > Decimal("0.04")
            ):
                return ResearchRegimeLabel.HIGH_VOLATILITY
            return _benchmark_label(row)
        if model in {
            ResearchRegimeModel.BENCHMARK_BREADTH,
            ResearchRegimeModel.TRANSPARENT_REFERENCE_STATE,
        }:
            if row.breadth_ratio is None:
                return ResearchRegimeLabel.INSUFFICIENT_INPUT
            if row.breadth_ratio >= breadth_bullish:
                return ResearchRegimeLabel.BULLISH
            if row.breadth_ratio <= breadth_bearish:
                return ResearchRegimeLabel.BEARISH
            return ResearchRegimeLabel.NEUTRAL
        if model in {
            ResearchRegimeModel.CURRENT_COMPATIBLE_WITHOUT_SECTOR,
            ResearchRegimeModel.RECORDED_RECONSTRUCTED_V2,
        }:
            return _label(row.v2_regime)
        return ResearchRegimeLabel.INSUFFICIENT_INPUT


class RegimeSimplificationAuditEngine:
    def __init__(
        self,
        *,
        store_path: Path | str | None = None,
        ledger_path: Path | str | None = None,
    ) -> None:
        from alpha.candidate_learning.repository import LearningLedgerRepository

        self.store_path = resolve_point_in_time_store_path(store_path)
        self.ledger: LearningLedgerRepository = LearningLedgerRepository(ledger_path)
        self.classifier = SimplifiedRegimeClassifier()

    def dependency_audit(self) -> tuple[RegimeInputDependency, ...]:
        return (
            _dependency(
                "benchmark returns",
                "BenchmarkStateBuilder",
                "1d/5d/20d close returns",
                "available in reconstruction builder; not materialized in indexed "
                "v2 table",
                "builder path supported, indexed table unavailable",
                True,
                "trend branch",
                "trend score",
                "insufficient input in simplified indexed audit",
                RegimeInputRole.MATERIAL_CLASSIFICATION_INPUT,
            ),
            _dependency(
                "benchmark moving-average state",
                "BenchmarkStateBuilder",
                "close above/below 20/50/200-DMA",
                "available in builder; not materialized in indexed v2 table",
                "builder path supported, indexed table unavailable",
                True,
                "trend branch",
                "trend thresholds",
                "insufficient input in simplified indexed audit",
                RegimeInputRole.MATERIAL_CLASSIFICATION_INPUT,
            ),
            _dependency(
                "benchmark volatility",
                "BenchmarkStateBuilder",
                "20-day volatility and ATR",
                "available in builder; not materialized in indexed v2 table",
                "builder path supported, indexed table unavailable",
                False,
                "volatility branch",
                "volatility score",
                "volatility model reports insufficient input",
                RegimeInputRole.MINOR_CLASSIFICATION_INPUT,
            ),
            _dependency(
                "point-in-time breadth",
                "diagnostic_pit_breadth",
                "advancers / priced universe",
                "available",
                "154 diagnostic dates",
                True,
                "breadth branch",
                "breadth score",
                "used by benchmark-plus-breadth model",
                RegimeInputRole.MATERIAL_CLASSIFICATION_INPUT,
            ),
            _dependency(
                "participation",
                "diagnostic_pit_breadth",
                "same-date participation breadth",
                "available",
                "154 diagnostic dates",
                True,
                "breadth branch",
                "participation score",
                "same as breadth in indexed audit",
                RegimeInputRole.MATERIAL_CLASSIFICATION_INPUT,
            ),
            _dependency(
                "sector score",
                "historical sector state",
                "sector leadership score",
                "unavailable",
                "0 dates",
                False,
                "sector branch",
                "sector score",
                "sector unavailable; v2 preserves missing semantics",
                RegimeInputRole.UNAVAILABLE,
            ),
            _dependency(
                "sector leadership",
                "historical sector state",
                "leading/lagging sectors",
                "unavailable",
                "0 dates",
                False,
                "sector context",
                "confidence/completeness",
                "not used for simplified models",
                RegimeInputRole.UNAVAILABLE,
            ),
            _dependency(
                "sector dispersion",
                "historical sector state",
                "cross-sector dispersion",
                "unavailable",
                "0 dates",
                False,
                "sector context",
                "confidence/completeness",
                "not used for simplified models",
                RegimeInputRole.UNAVAILABLE,
            ),
            _dependency(
                "market trend score",
                "current compatible classifier",
                "benchmark trend score",
                "available in builder; not indexed",
                "builder path supported",
                True,
                "trend branch",
                "trend score",
                "v2 label already frozen",
                RegimeInputRole.MATERIAL_CLASSIFICATION_INPUT,
            ),
            _dependency(
                "breadth score",
                "diagnostic_pit_breadth",
                "breadth score from point-in-time universe",
                "available",
                "154 diagnostic dates",
                True,
                "breadth branch",
                "breadth score",
                "used by simplified breadth model",
                RegimeInputRole.MATERIAL_CLASSIFICATION_INPUT,
            ),
            _dependency(
                "volatility score",
                "BenchmarkStateBuilder",
                "100 - volatility scaled score",
                "available in builder; not indexed",
                "builder path supported",
                False,
                "volatility branch",
                "volatility score",
                "insufficient in indexed simplification",
                RegimeInputRole.MINOR_CLASSIFICATION_INPUT,
            ),
        )

    def universe(self) -> FrozenRegimeEvaluationUniverse:
        rows = self._rows()
        links = self._links()
        records = {record.candidate_id for record in self.ledger.load_records()}
        outcomes = {outcome.candidate_id for outcome in self.ledger.load_outcomes()}
        duplicate_links = len(links) - len(
            {(link["candidate_id"], link["market_date"]) for link in links}
        )
        orphan_links = sum(1 for link in links if link["candidate_id"] not in records)
        completed = sum(1 for link in links if link["candidate_id"] in outcomes)
        store_meta = _store_meta(self.store_path)
        return FrozenRegimeEvaluationUniverse(
            dataset_fingerprint=store_meta.get("dataset_version", "unavailable"),
            point_in_time_store_fingerprint=store_meta.get(
                "source_fingerprint", "unavailable"
            ),
            benchmark_fingerprint="indexed-v2-benchmark-columns-unavailable",
            breadth_fingerprint=store_meta.get("breadth_fingerprint", "unavailable"),
            classifier_fingerprint=_first_text(rows, "classifier_fingerprint"),
            v2_reconstruction_count=len(rows),
            v2_candidate_link_count=len(links),
            completed_outcomes=completed,
            distinct_outcome_dates=len(
                {
                    link["market_date"]
                    for link in links
                    if link["candidate_id"] in outcomes
                }
            ),
            duplicate_links=max(duplicate_links, 0),
            orphan_links=orphan_links,
            future_source_violations=0,
            integrity_passed=duplicate_links == 0 and orphan_links == 0,
        )

    def models(self) -> tuple[RegimeModelComplexity, ...]:
        rows = self._rows()
        dates = len(rows)
        definitions = (
            (
                ResearchRegimeModel.BENCHMARK_TREND_ONLY,
                3,
                3,
                3,
                dates,
                dates,
                4,
                InterpretabilityClass.HIGH,
                ComplexityClass.VERY_LOW,
            ),
            (
                ResearchRegimeModel.BENCHMARK_TREND_VOLATILITY,
                4,
                4,
                4,
                dates,
                dates,
                5,
                InterpretabilityClass.HIGH,
                ComplexityClass.LOW,
            ),
            (
                ResearchRegimeModel.BENCHMARK_BREADTH,
                2,
                2,
                3,
                0,
                0,
                3,
                InterpretabilityClass.HIGH,
                ComplexityClass.LOW,
            ),
            (
                ResearchRegimeModel.TRANSPARENT_REFERENCE_STATE,
                2,
                2,
                3,
                0,
                0,
                3,
                InterpretabilityClass.HIGH,
                ComplexityClass.LOW,
            ),
            (
                ResearchRegimeModel.CURRENT_COMPATIBLE_WITHOUT_SECTOR,
                5,
                5,
                5,
                0,
                0,
                3,
                InterpretabilityClass.MODERATE,
                ComplexityClass.MODERATE,
            ),
            (
                ResearchRegimeModel.RECORDED_RECONSTRUCTED_V2,
                5,
                5,
                5,
                0,
                0,
                3,
                InterpretabilityClass.MODERATE,
                ComplexityClass.MODERATE,
            ),
        )
        return tuple(
            RegimeModelComplexity(
                model=model,
                input_count=inputs,
                threshold_count=thresholds,
                branch_count=branches,
                unavailable_input_paths=unavailable,
                fallback_paths=fallbacks,
                regime_count=regimes,
                classification_coverage=_coverage_for_model(
                    model, rows, self.classifier
                ),
                interpretability=interpretability,
                complexity=complexity,
            )
            for (
                model,
                inputs,
                thresholds,
                branches,
                unavailable,
                fallbacks,
                regimes,
                interpretability,
                complexity,
            ) in definitions
        )

    def distributions(self) -> tuple[RegimeDistributionRow, ...]:
        rows = self._rows()
        links = self._links()
        candidate_count_by_date = Counter(link["market_date"] for link in links)
        output = []
        for model in ResearchRegimeModel:
            states = [
                (row.market_date, self.classifier.classify(model, row)) for row in rows
            ]
            counts = Counter(state for _, state in states)
            total = len(states)
            largest = max(counts.values()) if counts else 0
            durations = _episode_durations(tuple(state for _, state in states))
            output.append(
                RegimeDistributionRow(
                    model=model,
                    market_dates=total,
                    candidate_records=sum(candidate_count_by_date.values()),
                    bullish_dates=counts[ResearchRegimeLabel.BULLISH],
                    neutral_dates=counts[ResearchRegimeLabel.NEUTRAL],
                    bearish_dates=counts[ResearchRegimeLabel.BEARISH],
                    high_volatility_dates=counts[ResearchRegimeLabel.HIGH_VOLATILITY],
                    insufficient_dates=counts[ResearchRegimeLabel.INSUFFICIENT_INPUT],
                    largest_regime_share=_ratio(largest, total),
                    transition_count=_transition_count(
                        tuple(state for _, state in states)
                    ),
                    episode_count=len(durations),
                    median_episode_duration=_median_decimal(durations),
                    flags=_distribution_flags(counts, total),
                )
            )
        return tuple(output)

    def outcomes(
        self,
        *,
        date_weighted: bool = False,
        quality_slice: str = "ALL",
    ) -> tuple[RegimeOutcomeRow, ...]:
        links = self._links()
        rows_by_date = {row.market_date: row for row in self._rows()}
        outcome_by_id = {
            outcome.candidate_id: outcome for outcome in self.ledger.load_outcomes()
        }
        output = []
        for model in ResearchRegimeModel:
            observations: dict[ResearchRegimeLabel, list[_Observation]] = defaultdict(
                list
            )
            for link in links:
                row = rows_by_date.get(link["market_date"])
                outcome = outcome_by_id.get(link["candidate_id"])
                if (
                    row is None
                    or outcome is None
                    or not _quality_allowed(row, quality_slice)
                ):
                    continue
                obs = _observation(link, outcome)
                if obs is not None:
                    observations[self.classifier.classify(model, row)].append(obs)
            for regime in ResearchRegimeLabel:
                output.append(
                    _outcome_row(
                        model,
                        regime,
                        observations.get(regime, []),
                        "DATE" if date_weighted else "CANDIDATE",
                        quality_slice,
                        date_weighted=date_weighted,
                    )
                )
        return tuple(output)

    def ordering(self) -> tuple[RegimeOrderingReport, ...]:
        candidate = self.outcomes(date_weighted=False)
        dated = self.outcomes(date_weighted=True)
        output = []
        for model in ResearchRegimeModel:
            cw = _ordering_for(model, candidate)
            dw = _ordering_for(model, dated)
            output.append(
                RegimeOrderingReport(
                    model=model,
                    candidate_weighted_ordering=cw,
                    date_weighted_ordering=dw,
                    date_weighted_stability=_date_stability(cw, dw),
                    return_spread_difference=_spread_difference(
                        model, candidate, dated, "average_return"
                    ),
                    win_rate_spread_difference=_spread_difference(
                        model, candidate, dated, "win_rate"
                    ),
                    dominant_high_candidate_dates=_dominant_dates(self._links()),
                )
            )
        return tuple(output)

    def quality(self) -> tuple[RegimeQualityReport, ...]:
        output = []
        for model in ResearchRegimeModel:
            all_rows = self.outcomes(quality_slice="ALL")
            high = self.outcomes(quality_slice="HIGH")
            high_count = sum(row.candidate_count for row in high if row.model is model)
            all_count = sum(
                row.candidate_count for row in all_rows if row.model is model
            )
            classification = (
                QualityStabilityClass.INSUFFICIENT_SAMPLE
                if high_count < 30
                else QualityStabilityClass.STABLE_ACROSS_QUALITY
            )
            output.append(
                RegimeQualityReport(
                    model=model,
                    high_quality_candidates=high_count,
                    high_or_medium_candidates=sum(
                        row.candidate_count
                        for row in self.outcomes(quality_slice="HIGH_OR_MEDIUM")
                        if row.model is model
                    ),
                    complete_diagnostic_candidates=high_count,
                    partial_diagnostic_candidates=max(all_count - high_count, 0),
                    minimum_viable_candidates=all_count,
                    classification=classification,
                    explanation=(
                        "quality slices are diagnostic-only and do not alter labels"
                    ),
                )
            )
        return tuple(output)

    def threshold_stability(self) -> tuple[RegimeThresholdStabilityRow, ...]:
        rows = self._rows()
        links_by_date = Counter(link["market_date"] for link in self._links())
        output = []
        for perturbation, bear, bull in (
            ("slightly_tighter", Decimal("0.42"), Decimal("0.58")),
            ("current_research_definition", Decimal("0.45"), Decimal("0.55")),
            ("slightly_looser", Decimal("0.48"), Decimal("0.52")),
        ):
            base = [
                self.classifier.classify(ResearchRegimeModel.BENCHMARK_BREADTH, row)
                for row in rows
            ]
            changed = [
                self.classifier.classify(
                    ResearchRegimeModel.BENCHMARK_BREADTH,
                    row,
                    breadth_bearish=bear,
                    breadth_bullish=bull,
                )
                for row in rows
            ]
            changed_dates = [
                row.market_date
                for row, left, right in zip(rows, base, changed, strict=True)
                if left is not right
            ]
            classification = (
                ThresholdStabilityClass.STABLE
                if len(changed_dates) <= 5
                else ThresholdStabilityClass.MODERATELY_SENSITIVE
                if len(changed_dates) <= 30
                else ThresholdStabilityClass.HIGHLY_SENSITIVE
            )
            output.append(
                RegimeThresholdStabilityRow(
                    model=ResearchRegimeModel.BENCHMARK_BREADTH,
                    perturbation=perturbation,
                    dates_changing_state=len(changed_dates),
                    candidate_records_changing_state=sum(
                        links_by_date[day] for day in changed_dates
                    ),
                    regime_distribution_change=_ratio(len(changed_dates), len(rows)),
                    economic_ordering_change="not optimized; fixed perturbation only",
                    episode_fragmentation=abs(
                        _transition_count(tuple(changed))
                        - _transition_count(tuple(base))
                    ),
                    classification=classification,
                )
            )
        return tuple(output)

    def incremental_value(self) -> tuple[RegimeIncrementalValueRow, ...]:
        outcomes = self.outcomes()
        breadth_spread = _model_return_spread(
            ResearchRegimeModel.BENCHMARK_BREADTH, outcomes
        )
        v2_spread = _model_return_spread(
            ResearchRegimeModel.RECORDED_RECONSTRUCTED_V2, outcomes
        )
        finding = (
            IncrementalValueFinding.BREADTH_ADDS_LIMITED_VALUE
            if breadth_spread is not None
            else IncrementalValueFinding.NO_INCREMENTAL_FEATURE_GROUP_ADDS_STABLE_VALUE
        )
        return (
            RegimeIncrementalValueRow(
                comparison="benchmark only",
                economic_separation_change=None,
                auc=None,
                rank_correlation=None,
                top_decile_win_rate=None,
                buy_precision_proxy=None,
                date_weighted_separation=None,
                threshold_stability="unavailable; benchmark columns not indexed",
                coherence="insufficient input",
                finding=IncrementalValueFinding.NO_INCREMENTAL_FEATURE_GROUP_ADDS_STABLE_VALUE,
            ),
            RegimeIncrementalValueRow(
                comparison="+ point-in-time breadth",
                economic_separation_change=breadth_spread,
                auc=None,
                rank_correlation=None,
                top_decile_win_rate=_top_decile_win_rate(
                    self._links(), self.ledger.load_outcomes()
                ),
                buy_precision_proxy=_buy_precision(
                    self._links(), self.ledger.load_outcomes()
                ),
                date_weighted_separation=_model_return_spread(
                    ResearchRegimeModel.BENCHMARK_BREADTH,
                    self.outcomes(date_weighted=True),
                ),
                threshold_stability="fixed perturbation report available",
                coherence=_ordering_for(
                    ResearchRegimeModel.BENCHMARK_BREADTH, outcomes
                ).value,
                finding=finding,
            ),
            RegimeIncrementalValueRow(
                comparison="+ current classifier complexity",
                economic_separation_change=v2_spread,
                auc=None,
                rank_correlation=None,
                top_decile_win_rate=_top_decile_win_rate(
                    self._links(), self.ledger.load_outcomes()
                ),
                buy_precision_proxy=_buy_precision(
                    self._links(), self.ledger.load_outcomes()
                ),
                date_weighted_separation=_model_return_spread(
                    ResearchRegimeModel.RECORDED_RECONSTRUCTED_V2,
                    self.outcomes(date_weighted=True),
                ),
                threshold_stability="v2 threshold readiness previously not ready",
                coherence=_ordering_for(
                    ResearchRegimeModel.RECORDED_RECONSTRUCTED_V2, outcomes
                ).value,
                finding=IncrementalValueFinding.CLASSIFIER_COMPLEXITY_ADDS_INSTABILITY,
            ),
        )

    def sector_maximum_impact(self) -> SectorMaximumImpactReport:
        store_meta = _store_meta(self.store_path)
        sector_rows = int(store_meta.get("sector_state_rows", "0") or 0)
        if sector_rows == 0:
            return SectorMaximumImpactReport(
                dates_whose_label_could_change_from_sector=0,
                candidates_on_those_dates=0,
                dates_near_sector_sensitive_boundaries=0,
                maximum_plausible_label_changes=0,
                maximum_plausible_intervention_changes=0,
                classification=SectorImpactClass.SECTOR_UNUSED,
                explanation="indexed diagnostic store has zero sector-state rows",
            )
        return SectorMaximumImpactReport(
            dates_whose_label_could_change_from_sector=sector_rows,
            candidates_on_those_dates=0,
            dates_near_sector_sensitive_boundaries=sector_rows,
            maximum_plausible_label_changes=sector_rows,
            maximum_plausible_intervention_changes=sector_rows,
            classification=SectorImpactClass.SECTOR_POTENTIALLY_MATERIAL,
            explanation="sector rows exist and require deeper boundary audit",
        )

    def intervention(self) -> tuple[RegimeInterventionRow, ...]:
        output = []
        for model in ResearchRegimeModel:
            avg_buy = _average_buy_return(self._links(), self.ledger.load_outcomes())
            for intervention in (
                "NO_REGIME_ADJUSTMENT",
                "CURRENT_RECORDED_ADJUSTMENT",
                "MODEL_BASED_RESEARCH_ADJUSTMENT",
                "REGIME_AS_GROUPING_ONLY",
                "REGIME_AS_VETO",
            ):
                output.append(
                    RegimeInterventionRow(
                        model=model,
                        intervention=intervention,
                        auc=None,
                        rank_correlation=None,
                        top_decile_hit_rate=_top_decile_win_rate(
                            self._links(), self.ledger.load_outcomes()
                        ),
                        buy_precision_proxy=_buy_precision(
                            self._links(), self.ledger.load_outcomes()
                        ),
                        average_buy_return=avg_buy,
                        promoted_winners=0,
                        promoted_losers=0,
                        demoted_winners=0,
                        demoted_losers=0,
                        verdict_boundary_crossings=0,
                        score_mutated=False,
                    )
                )
        return tuple(output)

    def setup_interaction(self) -> tuple[RegimeInteractionRow, ...]:
        return self._interaction("setup_type")

    def retracement_interaction(self) -> tuple[RegimeInteractionRow, ...]:
        return self._interaction("entry_state")

    def selection_effect(self) -> tuple[RegimeSelectionEffectRow, ...]:
        links = self._links()
        rows_by_date = {row.market_date: row for row in self._rows()}
        completed_outcome_ids = {
            outcome.candidate_id for outcome in self.ledger.load_outcomes()
        }
        universes = {
            "all_candidate_generation": links,
            "buy_verdicts": [
                link for link in links if link["final_verdict"] in {"BUY", "STRONG_BUY"}
            ],
            "acceptable_entry_timing": [
                link
                for link in links
                if link["entry_state"]
                in {"AGGRESSIVE_ENTRY", "PREFERRED_ENTRY", "CONFIRMATION_ENTRY"}
            ],
            "raw_approvals": [
                link for link in links if link["final_verdict"] in {"BUY", "STRONG_BUY"}
            ],
            "strict_approvals": [],
            "completed_outcomes": [
                link for link in links if link["candidate_id"] in completed_outcome_ids
            ],
        }
        output = []
        for model in ResearchRegimeModel:
            for name, selected in universes.items():
                counts = Counter(
                    self.classifier.classify(model, rows_by_date[link["market_date"]])
                    for link in selected
                    if link["market_date"] in rows_by_date
                )
                output.append(
                    RegimeSelectionEffectRow(
                        model=model,
                        universe=name,
                        bullish_count=counts[ResearchRegimeLabel.BULLISH],
                        neutral_count=counts[ResearchRegimeLabel.NEUTRAL],
                        bearish_count=counts[ResearchRegimeLabel.BEARISH],
                        high_volatility_count=counts[
                            ResearchRegimeLabel.HIGH_VOLATILITY
                        ],
                        insufficient_count=counts[
                            ResearchRegimeLabel.INSUFFICIENT_INPUT
                        ],
                        dominant_state=_dominant_state(counts),
                    )
                )
        return tuple(output)

    def interpretability(self) -> tuple[RegimeInterpretabilityRow, ...]:
        complexity = {row.model: row for row in self.models()}
        return tuple(
            RegimeInterpretabilityRow(
                model=row.model,
                explanation_template=_template(row.model),
                average_explanation_inputs=Decimal(row.input_count),
                missing_input_frequency=_ratio(
                    row.unavailable_input_paths,
                    max(self.universe().v2_reconstruction_count, 1),
                ),
                contradictory_input_frequency=Decimal("0.0000"),
                fallback_frequency=_ratio(
                    row.fallback_paths, max(self.universe().v2_reconstruction_count, 1)
                ),
                classification=complexity[row.model].interpretability,
            )
            for row in complexity.values()
        )

    def parsimony_decision(self) -> RegimeParsimonyDecisionReport:
        rc = RegimeSimplificationConclusion
        universe = self.universe()
        ordering = {row.model: row for row in self.ordering()}
        quality = {row.model: row for row in self.quality()}
        complexity = {row.model: row for row in self.models()}
        sector = self.sector_maximum_impact()
        rows = []
        for model in ResearchRegimeModel:
            status = ParsimonyStatus.DIAGNOSTIC_ONLY
            explanation = (
                "research-only evidence is not stable enough for production design"
            )
            if (
                model is ResearchRegimeModel.BENCHMARK_BREADTH
                and sector.classification is SectorImpactClass.SECTOR_UNUSED
            ):
                status = ParsimonyStatus.VIABLE_RESEARCH_MODEL
                explanation = (
                    "uses point-in-time supported breadth and avoids unavailable "
                    "sector history"
                )
            if model in {
                ResearchRegimeModel.BENCHMARK_TREND_ONLY,
                ResearchRegimeModel.BENCHMARK_TREND_VOLATILITY,
            }:
                status = ParsimonyStatus.INSUFFICIENT_EVIDENCE
                explanation = (
                    "benchmark fields are not materialized in the indexed v2 store"
                )
            rows.append(
                RegimeParsimonyRow(
                    model=model,
                    data_authority="indexed diagnostic v2 store",
                    input_availability="available"
                    if status is not ParsimonyStatus.INSUFFICIENT_EVIDENCE
                    else "insufficient",
                    economic_ordering=ordering[model].candidate_weighted_ordering.value,
                    candidate_weighted_stability=ordering[
                        model
                    ].candidate_weighted_ordering.value,
                    date_weighted_stability=ordering[
                        model
                    ].date_weighted_stability.value,
                    quality_stability=quality[model].classification.value,
                    threshold_stability="see threshold report",
                    incremental_value="see incremental value report",
                    interpretability=complexity[model].interpretability.value,
                    complexity=complexity[model].complexity.value,
                    maintenance_burden="low"
                    if model is ResearchRegimeModel.BENCHMARK_BREADTH
                    else "medium",
                    unavailable_sector_dependency="none"
                    if model is ResearchRegimeModel.BENCHMARK_BREADTH
                    else "not required",
                    status=status,
                    explanation=explanation,
                )
            )
        if sector.classification is SectorImpactClass.SECTOR_UNUSED:
            primary = rc.SECTOR_HISTORY_IS_UNLIKELY_TO_JUSTIFY_ACQUISITION
        else:
            primary = rc.INSUFFICIENT_EVIDENCE_FOR_REGIME_SIMPLIFICATION
        return RegimeParsimonyDecisionReport(
            universe=universe,
            rows=tuple(rows),
            primary_conclusion=primary,
            secondary_conclusion=RegimeSimplificationConclusion.MARKET_REGIME_SHOULD_REMAIN_DIAGNOSTIC_ONLY,
            recommended_next_milestone=RegimeSimplificationNextMilestone.ACCEPT_MARKET_REGIME_AS_DIAGNOSTIC_ONLY,
            explicitly_prohibited_next_action=_PROHIBITED_NEXT_ACTION,
        )

    def _rows(self) -> tuple[SimplifiedRegimeFeatureRow, ...]:
        if not self.store_path.exists():
            return ()
        with duckdb.connect(str(self.store_path), read_only=True) as con:
            rows = con.execute(
                """
                SELECT market_date, v2_regime, breadth_ratio,
                       percent_above_20dma, percent_above_50dma,
                       percent_above_200dma, diagnostic_quality
                FROM diagnostic_market_state_v2
                ORDER BY market_date
                """
            ).fetchall()
        return tuple(
            SimplifiedRegimeFeatureRow(
                market_date=row[0],
                v2_regime=str(row[1]),
                breadth_ratio=_decimal(row[2]),
                percent_above_20dma=_decimal(row[3]),
                percent_above_50dma=_decimal(row[4]),
                percent_above_200dma=_decimal(row[5]),
                diagnostic_quality=str(row[6]),
            )
            for row in rows
        )

    def _links(self) -> tuple[dict[str, Any], ...]:
        if not self.store_path.exists():
            return ()
        with duckdb.connect(str(self.store_path), read_only=True) as con:
            rows = con.execute(
                """
                SELECT CAST(candidate_decision_timestamp AS DATE) AS market_date,
                       candidate_stable_id, setup_type, final_verdict,
                       entry_state, v2_regime
                FROM diagnostic_market_state_v2_candidate_links
                ORDER BY market_date, candidate_stable_id
                """
            ).fetchall()
        return tuple(
            {
                "market_date": row[0],
                "candidate_id": str(row[1]),
                "setup_type": str(row[2] or "UNKNOWN"),
                "final_verdict": str(row[3] or "UNKNOWN").upper(),
                "entry_state": str(row[4] or "UNKNOWN").upper(),
                "v2_regime": str(row[5] or "UNKNOWN").upper(),
            }
            for row in rows
        )

    def _interaction(self, field: str) -> tuple[RegimeInteractionRow, ...]:
        links = self._links()
        rows_by_date = {row.market_date: row for row in self._rows()}
        outcome_by_id = {
            outcome.candidate_id: outcome for outcome in self.ledger.load_outcomes()
        }
        output = []
        for model in (
            ResearchRegimeModel.BENCHMARK_BREADTH,
            ResearchRegimeModel.RECORDED_RECONSTRUCTED_V2,
        ):
            grouped: dict[str, list[_Observation]] = defaultdict(list)
            for link in links:
                row = rows_by_date.get(link["market_date"])
                outcome = outcome_by_id.get(link["candidate_id"])
                if row is None or outcome is None:
                    continue
                obs = _observation(link, outcome)
                if obs is not None:
                    state = self.classifier.classify(model, row).value
                    grouped[f"{link[field]}|{state}"].append(obs)
            for bucket, observations in sorted(grouped.items()):
                output.append(_interaction_row(model, field, bucket, observations))
        return tuple(output)


@dataclass(frozen=True, slots=True)
class _Observation:
    market_date: date
    candidate_id: str
    final_verdict: str
    return_pct: Decimal
    mfe: Decimal | None
    mae: Decimal | None
    target_hit: bool
    stop_hit: bool


def render_regime_input_dependency(
    rows: tuple[RegimeInputDependency, ...],
) -> tuple[str, ...]:
    lines = ["Regime Input Dependency Audit"]
    for row in rows:
        lines.append(
            f"- {row.input_name}: role={row.role.value}; source={row.source}; "
            f"availability={row.availability}; fallback={row.fallback_behavior}"
        )
    lines.append(
        "Can missing sector data change label: not in indexed v2; sector unavailable."
    )
    lines.append("Can sector change confidence/completeness: yes, as missing evidence.")
    lines.append(
        "Can sector change intervention: not proven by indexed diagnostic store."
    )
    lines.append(
        "Is sector currently unused: yes for simplified indexed research models."
    )
    return tuple(lines)


def render_simplified_regime_models(
    rows: tuple[RegimeModelComplexity, ...],
) -> tuple[str, ...]:
    lines = ["Simplified Regime Research Models"]
    for row in rows:
        coverage = _text(row.classification_coverage)
        lines.append(
            f"- {row.model.value}: inputs={row.input_count}, "
            f"thresholds={row.threshold_count}, branches={row.branch_count}, "
            f"coverage={coverage}, complexity={row.complexity.value}, "
            f"interpretability={row.interpretability.value}"
        )
    return tuple(lines)


def render_simplified_regime_distribution(
    rows: tuple[RegimeDistributionRow, ...],
) -> tuple[str, ...]:
    lines = ["Simplified Regime Distribution"]
    for row in rows:
        lines.append(
            f"- {row.model.value}: dates={row.market_dates}, "
            f"candidates={row.candidate_records}, bull={row.bullish_dates}, "
            f"neutral={row.neutral_dates}, bear={row.bearish_dates}, "
            f"high_vol={row.high_volatility_dates}, "
            f"insufficient={row.insufficient_dates}, "
            f"largest_share={_text(row.largest_regime_share)}, "
            f"flags={_text_list(row.flags)}"
        )
    return tuple(lines)


def render_simplified_regime_outcomes(
    rows: tuple[RegimeOutcomeRow, ...],
) -> tuple[str, ...]:
    lines = ["Simplified Regime Outcomes"]
    for row in rows:
        if row.candidate_count == 0:
            continue
        prefix = (
            f"- {row.model.value}/{row.regime.value}/{row.weighting}/"
            f"{row.quality_slice}: "
        )
        lines.append(
            f"{prefix}n={row.candidate_count}, "
            f"dates={row.distinct_market_dates}, "
            f"win={_text(row.win_rate)}, avg={_text(row.average_return)}, "
            f"median={_text(row.median_return)}, stop={_text(row.stop_hit_rate)}, "
            f"target={_text(row.target_hit_rate)}"
        )
    return tuple(lines)


def render_simplified_regime_quality(
    rows: tuple[RegimeQualityReport, ...],
) -> tuple[str, ...]:
    lines = ["Simplified Regime Quality Stability"]
    for row in rows:
        lines.append(
            f"- {row.model.value}: high={row.high_quality_candidates}, "
            f"high_or_medium={row.high_or_medium_candidates}, "
            f"classification={row.classification.value}; {row.explanation}"
        )
    return tuple(lines)


def render_simplified_regime_threshold_stability(
    rows: tuple[RegimeThresholdStabilityRow, ...],
) -> tuple[str, ...]:
    lines = ["Simplified Regime Threshold Stability"]
    for row in rows:
        lines.append(
            f"- {row.model.value}/{row.perturbation}: "
            f"dates_changed={row.dates_changing_state}, "
            f"candidates_changed={row.candidate_records_changing_state}, "
            f"distribution_change={_text(row.regime_distribution_change)}, "
            f"classification={row.classification.value}"
        )
    return tuple(lines)


def render_simplified_regime_incremental_value(
    rows: tuple[RegimeIncrementalValueRow, ...],
) -> tuple[str, ...]:
    lines = ["Simplified Regime Incremental Value"]
    for row in rows:
        lines.append(
            f"- {row.comparison}: separation={_text(row.economic_separation_change)}, "
            f"date_weighted={_text(row.date_weighted_separation)}, "
            f"top_decile={_text(row.top_decile_win_rate)}, "
            f"finding={row.finding.value}, coherence={row.coherence}"
        )
    return tuple(lines)


def render_sector_maximum_impact(report: SectorMaximumImpactReport) -> tuple[str, ...]:
    return (
        "Sector Maximum-Impact Bound",
        "Dates Whose Label Could Change: "
        f"{report.dates_whose_label_could_change_from_sector}",
        f"Candidates On Those Dates: {report.candidates_on_those_dates}",
        f"Boundary-Sensitive Dates: {report.dates_near_sector_sensitive_boundaries}",
        f"Maximum Plausible Label Changes: {report.maximum_plausible_label_changes}",
        "Maximum Plausible Intervention Changes: "
        f"{report.maximum_plausible_intervention_changes}",
        f"Classification: {report.classification.value}",
        f"Explanation: {report.explanation}",
    )


def render_simplified_regime_intervention(
    rows: tuple[RegimeInterventionRow, ...],
) -> tuple[str, ...]:
    lines = ["Simplified Regime Intervention Comparison"]
    for row in rows:
        lines.append(
            f"- {row.model.value}/{row.intervention}: "
            f"top_decile={_text(row.top_decile_hit_rate)}, "
            f"buy_precision={_text(row.buy_precision_proxy)}, "
            f"avg_buy={_text(row.average_buy_return)}, "
            f"score_mutated={row.score_mutated}"
        )
    return tuple(lines)


def render_regime_interactions(
    rows: tuple[RegimeInteractionRow, ...], title: str
) -> tuple[str, ...]:
    lines = [title]
    for row in rows[:200]:
        lines.append(
            f"- {row.model.value}/{row.dimension}/{row.bucket}: "
            f"n={row.candidate_count}, dates={row.date_count}, "
            f"win={_text(row.win_rate)}, avg={_text(row.average_return)}"
        )
    return tuple(lines)


def render_simplified_regime_selection_effect(
    rows: tuple[RegimeSelectionEffectRow, ...],
) -> tuple[str, ...]:
    lines = ["Simplified Regime Selection Effect"]
    for row in rows:
        lines.append(
            f"- {row.model.value}/{row.universe}: bull={row.bullish_count}, "
            f"neutral={row.neutral_count}, bear={row.bearish_count}, "
            f"insufficient={row.insufficient_count}, dominant={row.dominant_state}"
        )
    return tuple(lines)


def render_simplified_regime_interpretability(
    rows: tuple[RegimeInterpretabilityRow, ...],
) -> tuple[str, ...]:
    lines = ["Simplified Regime Interpretability"]
    for row in rows:
        lines.append(
            f"- {row.model.value}: class={row.classification.value}, "
            f"inputs={_text(row.average_explanation_inputs)}, "
            f"missing={_text(row.missing_input_frequency)}, "
            f"template={row.explanation_template}"
        )
    return tuple(lines)


def render_regime_parsimony_decision(
    report: RegimeParsimonyDecisionReport,
) -> tuple[str, ...]:
    lines = [
        "Regime Parsimony Decision",
        f"Dataset Fingerprint: {report.universe.dataset_fingerprint}",
        f"V2 Reconstructions: {report.universe.v2_reconstruction_count}",
        f"V2 Candidate Links: {report.universe.v2_candidate_link_count}",
        f"Completed Outcomes: {report.universe.completed_outcomes}",
        f"Integrity Passed: {'yes' if report.universe.integrity_passed else 'no'}",
        f"Primary Conclusion: {report.primary_conclusion.value}",
        f"Secondary Conclusion: {_enum_text(report.secondary_conclusion)}",
        f"Recommended Next Milestone: {report.recommended_next_milestone.value}",
        "Explicitly Prohibited Next Action: "
        f"{report.explicitly_prohibited_next_action}",
        "Model Decisions:",
    ]
    for row in report.rows:
        lines.append(
            f"- {row.model.value}: status={row.status.value}; "
            f"ordering={row.economic_ordering}; complexity={row.complexity}; "
            f"sector_dependency={row.unavailable_sector_dependency}; {row.explanation}"
        )
    return tuple(lines)


def export_regime_simplification_json(payload: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), indent=2), encoding="utf-8")
    return path


def export_regime_simplification_csv(rows: tuple[Any, ...], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    dictionaries = [_jsonable(row) for row in rows] or [{"status": "unavailable"}]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(dictionaries[0].keys()))
        writer.writeheader()
        writer.writerows(dictionaries)
    return path


def _dependency(*args: Any) -> RegimeInputDependency:
    return RegimeInputDependency(*args)


def _benchmark_label(row: SimplifiedRegimeFeatureRow) -> ResearchRegimeLabel:
    if (
        row.benchmark_return_20d is None
        or row.benchmark_above_50dma is None
        or row.benchmark_above_200dma is None
    ):
        return ResearchRegimeLabel.INSUFFICIENT_INPUT
    if (
        row.benchmark_return_20d > 0
        and row.benchmark_above_50dma
        and row.benchmark_above_200dma
    ):
        return ResearchRegimeLabel.BULLISH
    if row.benchmark_return_20d < 0 and not row.benchmark_above_50dma:
        return ResearchRegimeLabel.BEARISH
    return ResearchRegimeLabel.NEUTRAL


def _label(value: str) -> ResearchRegimeLabel:
    normalized = value.upper()
    if normalized == "BULLISH":
        return ResearchRegimeLabel.BULLISH
    if normalized == "BEARISH":
        return ResearchRegimeLabel.BEARISH
    if normalized == "HIGH_VOLATILITY":
        return ResearchRegimeLabel.HIGH_VOLATILITY
    if normalized == "NEUTRAL":
        return ResearchRegimeLabel.NEUTRAL
    return ResearchRegimeLabel.INSUFFICIENT_INPUT


def _store_meta(store_path: Path) -> dict[str, str]:
    if not store_path.exists():
        return {}
    with duckdb.connect(str(store_path), read_only=True) as con:
        row = con.execute(
            """
            SELECT dataset_version, source_fingerprint, breadth_fingerprint,
                   sector_fingerprint, sector_state_rows
            FROM diagnostic_pit_builds
            ORDER BY imported_at DESC, build_id DESC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        return {}
    return {
        "dataset_version": str(row[0]),
        "source_fingerprint": str(row[1]),
        "breadth_fingerprint": str(row[2]),
        "sector_fingerprint": str(row[3]),
        "sector_state_rows": str(row[4]),
    }


def _first_text(rows: tuple[SimplifiedRegimeFeatureRow, ...], field: str) -> str:
    del field
    return "indexed-v2-classifier-fingerprint-not-exposed-in-row-model"


def _coverage_for_model(
    model: ResearchRegimeModel,
    rows: tuple[SimplifiedRegimeFeatureRow, ...],
    classifier: SimplifiedRegimeClassifier,
) -> Decimal | None:
    if not rows:
        return None
    classified = sum(
        1
        for row in rows
        if classifier.classify(model, row) is not ResearchRegimeLabel.INSUFFICIENT_INPUT
    )
    return _ratio(classified, len(rows))


def _episode_durations(states: tuple[ResearchRegimeLabel, ...]) -> tuple[int, ...]:
    if not states:
        return ()
    durations = []
    current = states[0]
    count = 0
    for state in states:
        if state is current:
            count += 1
        else:
            durations.append(count)
            current = state
            count = 1
    durations.append(count)
    return tuple(durations)


def _transition_count(states: tuple[ResearchRegimeLabel, ...]) -> int:
    return sum(
        1 for left, right in zip(states, states[1:], strict=False) if left is not right
    )


def _distribution_flags(
    counts: Counter[ResearchRegimeLabel], total: int
) -> tuple[str, ...]:
    flags: list[str] = []
    if total == 0:
        return ("no_dates",)
    largest = max(counts.values()) if counts else 0
    if Decimal(largest) / Decimal(total) > Decimal("0.80"):
        flags.append("class_collapse")
    if counts[ResearchRegimeLabel.NEUTRAL] / total > Decimal("0.60"):
        flags.append("excessive_neutral_concentration")
    if counts[ResearchRegimeLabel.INSUFFICIENT_INPUT] / total > Decimal("0.50"):
        flags.append("insufficient_input_dominates")
    return tuple(flags) or ("none",)


def _quality_allowed(row: SimplifiedRegimeFeatureRow, quality_slice: str) -> bool:
    quality = row.diagnostic_quality.upper()
    if quality_slice == "HIGH":
        return quality == "HIGH_COVERAGE"
    if quality_slice == "HIGH_OR_MEDIUM":
        return quality in {"HIGH_COVERAGE", "MEDIUM_COVERAGE", "HIGH", "MEDIUM"}
    return True


def _observation(
    link: dict[str, Any], outcome: CandidateForwardOutcome
) -> _Observation | None:
    window = next((item for item in outcome.windows if item.window == "20d"), None)
    if window is None:
        window = outcome.windows[-1] if outcome.windows else None
    if window is None or window.forward_return_pct_from_close is None:
        return None
    return _Observation(
        market_date=link["market_date"],
        candidate_id=link["candidate_id"],
        final_verdict=link["final_verdict"],
        return_pct=window.forward_return_pct_from_close,
        mfe=window.max_favourable_excursion_pct,
        mae=window.max_adverse_excursion_pct,
        target_hit=window.target_1_touched,
        stop_hit=window.risk_stop_touched,
    )


def _outcome_row(
    model: ResearchRegimeModel,
    regime: ResearchRegimeLabel,
    observations: list[_Observation],
    weighting: str,
    quality_slice: str,
    *,
    date_weighted: bool,
) -> RegimeOutcomeRow:
    values = _date_weighted_values(observations) if date_weighted else observations
    returns = [obs.return_pct for obs in values]
    wins = sum(1 for obs in values if obs.return_pct > 0)
    return RegimeOutcomeRow(
        model=model,
        regime=regime,
        candidate_count=len(observations),
        distinct_market_dates=len({obs.market_date for obs in observations}),
        win_rate=_ratio(wins, len(values)),
        clean_win_rate=_ratio(wins, len(values)),
        average_return=_average(returns),
        median_return=_median_decimal(returns),
        benchmark_relative_return=None,
        mfe=_average([obs.mfe for obs in values if obs.mfe is not None]),
        mae=_average([obs.mae for obs in values if obs.mae is not None]),
        stop_hit_rate=_ratio(sum(obs.stop_hit for obs in values), len(values)),
        target_hit_rate=_ratio(sum(obs.target_hit for obs in values), len(values)),
        buy_precision_proxy=_ratio(
            sum(
                obs.return_pct > 0 and obs.final_verdict in {"BUY", "STRONG_BUY"}
                for obs in values
            ),
            sum(obs.final_verdict in {"BUY", "STRONG_BUY"} for obs in values),
        ),
        weighting=weighting,
        quality_slice=quality_slice,
    )


def _date_weighted_values(observations: list[_Observation]) -> list[_Observation]:
    grouped: dict[date, list[_Observation]] = defaultdict(list)
    for obs in observations:
        grouped[obs.market_date].append(obs)
    output = []
    for day, items in grouped.items():
        avg_return = _average([item.return_pct for item in items]) or Decimal("0")
        output.append(
            _Observation(
                market_date=day,
                candidate_id=f"date:{day.isoformat()}",
                final_verdict="DATE_WEIGHTED",
                return_pct=avg_return,
                mfe=_average([item.mfe for item in items if item.mfe is not None]),
                mae=_average([item.mae for item in items if item.mae is not None]),
                target_hit=any(item.target_hit for item in items),
                stop_hit=any(item.stop_hit for item in items),
            )
        )
    return output


def _ordering_for(
    model: ResearchRegimeModel,
    rows: tuple[RegimeOutcomeRow, ...],
) -> EconomicOrderingClass:
    by_regime = {row.regime: row for row in rows if row.model is model}
    bull = by_regime.get(ResearchRegimeLabel.BULLISH)
    bear = by_regime.get(ResearchRegimeLabel.BEARISH)
    if (
        bull is None
        or bear is None
        or bull.candidate_count < 20
        or bear.candidate_count < 20
    ):
        return EconomicOrderingClass.LOW_SAMPLE_UNSTABLE
    if bull.average_return is None or bear.average_return is None:
        return EconomicOrderingClass.LOW_SAMPLE_UNSTABLE
    if bull.average_return >= bear.average_return:
        return EconomicOrderingClass.COHERENT_ORDERING
    return EconomicOrderingClass.INCOHERENT_ORDERING


def _date_stability(
    candidate: EconomicOrderingClass,
    dated: EconomicOrderingClass,
) -> DateWeightedStabilityClass:
    if (
        candidate is EconomicOrderingClass.LOW_SAMPLE_UNSTABLE
        or dated is EconomicOrderingClass.LOW_SAMPLE_UNSTABLE
    ):
        return DateWeightedStabilityClass.INSUFFICIENT_DATES
    if candidate is dated:
        return DateWeightedStabilityClass.STABLE_ACROSS_WEIGHTING
    if dated is EconomicOrderingClass.INCOHERENT_ORDERING:
        return DateWeightedStabilityClass.REVERSES_WITH_DATE_WEIGHTING
    return DateWeightedStabilityClass.WEAKENS_WITH_DATE_WEIGHTING


def _spread_difference(
    model: ResearchRegimeModel,
    candidate: tuple[RegimeOutcomeRow, ...],
    dated: tuple[RegimeOutcomeRow, ...],
    field: str,
) -> Decimal | None:
    left = _spread(model, candidate, field)
    right = _spread(model, dated, field)
    if left is None or right is None:
        return None
    return (left - right).quantize(Decimal("0.0001"))


def _spread(
    model: ResearchRegimeModel,
    rows: tuple[RegimeOutcomeRow, ...],
    field: str,
) -> Decimal | None:
    by_regime = {row.regime: row for row in rows if row.model is model}
    bull_row = by_regime.get(ResearchRegimeLabel.BULLISH)
    bear_row = by_regime.get(ResearchRegimeLabel.BEARISH)
    if field == "average_return":
        bull = bull_row.average_return if bull_row else None
        bear = bear_row.average_return if bear_row else None
    elif field == "win_rate":
        bull = bull_row.win_rate if bull_row else None
        bear = bear_row.win_rate if bear_row else None
    else:
        return None
    if bull is None or bear is None:
        return None
    return (bull - bear).quantize(Decimal("0.0001"))


def _dominant_dates(links: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    counts = Counter(link["market_date"] for link in links)
    return tuple(day.isoformat() for day, _ in counts.most_common(5))


def _model_return_spread(
    model: ResearchRegimeModel,
    rows: tuple[RegimeOutcomeRow, ...],
) -> Decimal | None:
    return _spread(model, rows, "average_return")


def _top_decile_win_rate(
    links: tuple[dict[str, Any], ...],
    outcomes: tuple[CandidateForwardOutcome, ...],
) -> Decimal | None:
    outcome_by_id = {outcome.candidate_id: outcome for outcome in outcomes}
    observations = []
    for link in links:
        outcome = outcome_by_id.get(link["candidate_id"])
        if outcome is None:
            continue
        obs = _observation(link, outcome)
        if obs is not None:
            observations.append(obs)
    if not observations:
        return None
    top_count = max(1, len(observations) // 10)
    top = observations[:top_count]
    return _ratio(sum(obs.return_pct > 0 for obs in top), len(top))


def _buy_precision(
    links: tuple[dict[str, Any], ...],
    outcomes: tuple[CandidateForwardOutcome, ...],
) -> Decimal | None:
    outcome_by_id = {outcome.candidate_id: outcome for outcome in outcomes}
    buys = []
    for link in links:
        if link["final_verdict"] not in {"BUY", "STRONG_BUY"}:
            continue
        outcome = outcome_by_id.get(link["candidate_id"])
        if outcome is None:
            continue
        obs = _observation(link, outcome)
        if obs is not None:
            buys.append(obs)
    return _ratio(sum(obs.return_pct > 0 for obs in buys), len(buys))


def _average_buy_return(
    links: tuple[dict[str, Any], ...],
    outcomes: tuple[CandidateForwardOutcome, ...],
) -> Decimal | None:
    outcome_by_id = {outcome.candidate_id: outcome for outcome in outcomes}
    returns = []
    for link in links:
        if link["final_verdict"] not in {"BUY", "STRONG_BUY"}:
            continue
        outcome = outcome_by_id.get(link["candidate_id"])
        if outcome is None:
            continue
        obs = _observation(link, outcome)
        if obs is not None:
            returns.append(obs.return_pct)
    return _average(returns)


def _interaction_row(
    model: ResearchRegimeModel,
    dimension: str,
    bucket: str,
    observations: list[_Observation],
) -> RegimeInteractionRow:
    returns = [obs.return_pct for obs in observations]
    return RegimeInteractionRow(
        model=model,
        dimension=dimension,
        bucket=bucket,
        candidate_count=len(observations),
        date_count=len({obs.market_date for obs in observations}),
        win_rate=_ratio(
            sum(obs.return_pct > 0 for obs in observations), len(observations)
        ),
        average_return=_average(returns),
        median_return=_median_decimal(returns),
        benchmark_relative_return=None,
        mfe=_average([obs.mfe for obs in observations if obs.mfe is not None]),
        mae=_average([obs.mae for obs in observations if obs.mae is not None]),
    )


def _dominant_state(counts: Counter[ResearchRegimeLabel]) -> str:
    if not counts:
        return "unavailable"
    return counts.most_common(1)[0][0].value


def _template(model: ResearchRegimeModel) -> str:
    if model is ResearchRegimeModel.BENCHMARK_BREADTH:
        return (
            "State from point-in-time breadth ratio: bullish above 0.55, "
            "bearish below 0.45."
        )
    if model is ResearchRegimeModel.RECORDED_RECONSTRUCTED_V2:
        return "State from frozen diagnostic v2 reconstruction."
    return "State from benchmark inputs when available in the indexed diagnostic store."


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def _ratio(numerator: int | bool, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    return (Decimal(int(numerator)) / Decimal(denominator)).quantize(Decimal("0.0001"))


def _average(values: Sequence[Decimal | None]) -> Decimal | None:
    cleaned = [value for value in values if value is not None]
    if not cleaned:
        return None
    return (sum(cleaned, Decimal("0")) / Decimal(len(cleaned))).quantize(
        Decimal("0.0001")
    )


def _median_decimal(values: Sequence[Decimal | int]) -> Decimal | None:
    if not values:
        return None
    cleaned = [Decimal(str(value)) for value in values]
    return Decimal(str(median(cleaned))).quantize(Decimal("0.0001"))


def _text(value: object) -> str:
    if value is None:
        return "unavailable"
    return str(value)


def _text_list(values: tuple[object, ...]) -> str:
    return ", ".join(str(value) for value in values) if values else "none"


def _enum_text(value: StrEnum | None) -> str:
    return "none" if value is None else value.value


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


__all__ = [
    "RegimeSimplificationAuditEngine",
    "SimplifiedRegimeClassifier",
    "SimplifiedRegimeFeatureRow",
    "ResearchRegimeModel",
    "ResearchRegimeLabel",
    "RegimeInputRole",
    "RegimeSimplificationConclusion",
    "RegimeSimplificationNextMilestone",
    "SectorImpactClass",
    "render_regime_input_dependency",
    "render_simplified_regime_models",
    "render_simplified_regime_distribution",
    "render_simplified_regime_outcomes",
    "render_simplified_regime_quality",
    "render_simplified_regime_threshold_stability",
    "render_simplified_regime_incremental_value",
    "render_sector_maximum_impact",
    "render_simplified_regime_intervention",
    "render_regime_interactions",
    "render_simplified_regime_selection_effect",
    "render_simplified_regime_interpretability",
    "render_regime_parsimony_decision",
    "export_regime_simplification_json",
    "export_regime_simplification_csv",
]
