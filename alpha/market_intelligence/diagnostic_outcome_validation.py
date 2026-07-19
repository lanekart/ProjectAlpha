from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from statistics import median
from typing import TYPE_CHECKING, Any

from alpha.market_intelligence.diagnostic_reconstruction import (
    DIAGNOSTIC_MARKET_STATE_DATASET_VERSION,
    DiagnosticCompatibilityLabel,
    DiagnosticInputCompleteness,
    DiagnosticMarketStateCandidateLink,
    DiagnosticMarketStateReconstruction,
    DiagnosticNextMilestone,
    TransparentReferenceState,
)

if TYPE_CHECKING:
    from alpha.candidate_learning.models import (
        CandidateForwardOutcome,
        CandidateForwardWindowOutcome,
    )
else:
    CandidateForwardOutcome = Any
    CandidateForwardWindowOutcome = Any

_ZERO = Decimal("0")
_FOUR = Decimal("0.0001")
_TWO = Decimal("0.01")
_HUNDRED = Decimal("100")
_POSITIVE_LABELS = {"WOULD_HAVE_WON"}
_NEGATIVE_LABELS = {"WOULD_HAVE_LOST"}
_DATA_MISSING_LABEL = "DATA_MISSING"
_BUY_VERDICTS = {"BUY", "STRONG_BUY"}
_APPROVED_ACTIONS = {"BUY", "ACCUMULATE", "ALLOCATE"}
_EXACT_COMPATIBILITY = {
    DiagnosticCompatibilityLabel.PERSISTED_EXACT,
    DiagnosticCompatibilityLabel.EXACT_FINGERPRINT,
    DiagnosticCompatibilityLabel.VERIFIED_MANIFEST,
}


class DiagnosticOutcomeUniverse(StrEnum):
    ALL_COMPLETED_OUTCOMES = "ALL_COMPLETED_OUTCOMES"
    ACCEPTABLE_ENTRY_TIMING = "ACCEPTABLE_ENTRY_TIMING"
    BUY_OR_STRONG_BUY = "BUY_OR_STRONG_BUY"
    HIGH_DIAGNOSTIC_QUALITY = "HIGH_DIAGNOSTIC_QUALITY"
    HIGH_OR_MEDIUM_DIAGNOSTIC_QUALITY = "HIGH_OR_MEDIUM_DIAGNOSTIC_QUALITY"
    COMPLETE_DIAGNOSTIC_ONLY = "COMPLETE_DIAGNOSTIC_ONLY"
    EXACT_LINEAGE_ONLY = "EXACT_LINEAGE_ONLY"
    COMPATIBILITY_ONLY = "COMPATIBILITY_ONLY"


class DiagnosticReadinessStatus(StrEnum):
    READY = "READY"
    CONDITIONALLY_READY = "CONDITIONALLY_READY"
    NOT_READY = "NOT_READY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class DiagnosticOutcomeConclusion(StrEnum):
    RECONSTRUCTED_REGIME_HAS_STABLE_OUTCOME_SEPARATION = (
        "RECONSTRUCTED_REGIME_HAS_STABLE_OUTCOME_SEPARATION"
    )
    RECONSTRUCTED_REGIME_HAS_LIMITED_OUTCOME_SEPARATION = (
        "RECONSTRUCTED_REGIME_HAS_LIMITED_OUTCOME_SEPARATION"
    )
    RECONSTRUCTED_REGIME_HAS_NO_USEFUL_OUTCOME_SEPARATION = (
        "RECONSTRUCTED_REGIME_HAS_NO_USEFUL_OUTCOME_SEPARATION"
    )
    REGIME_INTERVENTION_ADDS_VALUE_WITH_RECONSTRUCTED_STATE = (
        "REGIME_INTERVENTION_ADDS_VALUE_WITH_RECONSTRUCTED_STATE"
    )
    REGIME_INTERVENTION_REMAINS_LOW_VALUE = "REGIME_INTERVENTION_REMAINS_LOW_VALUE"
    MOMENTUM_MARKET_STATE_INTERACTION_IS_PRIMARY_FINDING = (
        "MOMENTUM_MARKET_STATE_INTERACTION_IS_PRIMARY_FINDING"
    )
    RETRACEMENT_REGIME_INTERACTION_IS_PRIMARY_FINDING = (
        "RETRACEMENT_REGIME_INTERACTION_IS_PRIMARY_FINDING"
    )
    CANDIDATE_SELECTION_EFFECT_IS_PRIMARY_FINDING = (
        "CANDIDATE_SELECTION_EFFECT_IS_PRIMARY_FINDING"
    )
    BREADTH_BIAS_IS_PRIMARY_LIMITATION = "BREADTH_BIAS_IS_PRIMARY_LIMITATION"
    DIAGNOSTIC_DATA_QUALITY_IS_PRIMARY_LIMITATION = (
        "DIAGNOSTIC_DATA_QUALITY_IS_PRIMARY_LIMITATION"
    )
    NO_SINGLE_REGIME_VALIDATION_CONCLUSION = "NO_SINGLE_REGIME_VALIDATION_CONCLUSION"


class StabilityClassification(StrEnum):
    STABLE_ACROSS_QUALITY = "STABLE_ACROSS_QUALITY"
    WEAKENS_ON_HIGH_QUALITY_FILTER = "WEAKENS_ON_HIGH_QUALITY_FILTER"
    STRENGTHENS_ON_HIGH_QUALITY_FILTER = "STRENGTHENS_ON_HIGH_QUALITY_FILTER"
    SIGN_REVERSAL_ACROSS_QUALITY = "SIGN_REVERSAL_ACROSS_QUALITY"
    LOW_SAMPLE_UNSTABLE = "LOW_SAMPLE_UNSTABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ThresholdStabilityClassification(StrEnum):
    THRESHOLDS_STABLE = "THRESHOLDS_STABLE"
    MODERATELY_SENSITIVE = "MODERATELY_SENSITIVE"
    HIGHLY_SENSITIVE = "HIGHLY_SENSITIVE"
    UNSTABLE_DUE_TO_DATA_QUALITY = "UNSTABLE_DUE_TO_DATA_QUALITY"


@dataclass(frozen=True, slots=True)
class DiagnosticDatasetIntegrity:
    dataset_version: str
    dataset_fingerprint: str
    classifier_version_used: str
    classifier_fingerprint_used: str
    feature_definition_version: str
    reconstruction_count: int
    candidate_link_count: int
    duplicate_reconstruction_ids: int
    duplicate_candidate_links: int
    orphan_candidate_links: int
    missing_reconstruction_references: int
    future_source_violations: int
    reconstruction_created_at_values: tuple[str, ...]
    outcome_join_timestamp: str
    immutable_join_preserved: bool


@dataclass(frozen=True, slots=True)
class DiagnosticOutcomeRow:
    candidate_id: str
    symbol: str
    market_date: date
    reconstructed_regime: str
    transparent_reference_state: str
    recorded_regime: str | None
    setup_type: str | None
    final_verdict: str
    capital_action: str
    approved_for_deployment: bool
    entry_state: str | None
    diagnostic_quality: str
    input_completeness: str
    compatibility_status: str
    exact_lineage: bool
    sector: str | None
    strategy_score: Decimal
    forward_return: Decimal | None
    benchmark_relative_return: Decimal | None
    mfe: Decimal | None
    mae: Decimal | None
    target_1_hit: bool | None
    stop_hit: bool | None
    outcome_label: str | None
    completed: bool
    clean_win: bool
    positive: bool | None
    retracement_score: Decimal | None
    price_component_score: Decimal | None
    volume_component_score: Decimal | None
    benchmark_return_20d: Decimal | None
    benchmark_above_50dma: bool | None
    benchmark_above_200dma: bool | None


@dataclass(frozen=True, slots=True)
class DiagnosticUniverseSummary:
    universe: str
    candidate_count: int
    date_count: int
    positive_return_count: int
    negative_return_count: int
    flat_count: int
    outcome_unavailable_count: int
    setup_distribution: tuple[tuple[str, int], ...]
    regime_distribution: tuple[tuple[str, int], ...]
    quality_distribution: tuple[tuple[str, int], ...]
    lineage_distribution: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class DiagnosticRegimeOutcomeSummary:
    group: str
    candidate_count: int
    date_count: int
    completed_outcomes: int
    win_rate: Decimal | None
    clean_win_rate: Decimal | None
    loss_rate: Decimal | None
    average_forward_return: Decimal | None
    median_forward_return: Decimal | None
    average_benchmark_relative_return: Decimal | None
    average_mfe: Decimal | None
    average_mae: Decimal | None
    stop_hit_rate: Decimal | None
    target_hit_rate: Decimal | None
    buy_precision_proxy: Decimal | None
    profitable_rejection_rate: Decimal | None


@dataclass(frozen=True, slots=True)
class DiagnosticDateOutcomeSummary:
    market_date: date
    reconstructed_regime: str
    candidate_count: int
    date_average_return: Decimal | None
    date_median_return: Decimal | None
    buy_precision_proxy: Decimal | None
    benchmark_return: Decimal | None
    setup_distribution: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class DiagnosticRegimeEpisode:
    episode_id: str
    regime: str
    start_date: date
    end_date: date
    duration: int
    candidate_count: int
    completed_outcomes: int
    average_return: Decimal | None
    benchmark_relative_return: Decimal | None
    maximum_adverse_excursion: Decimal | None
    transition_into_episode: str
    transition_out_of_episode: str


@dataclass(frozen=True, slots=True)
class DiagnosticInterventionComparison:
    name: str
    sample_size: int
    auc: Decimal | None
    rank_correlation: Decimal | None
    top_decile_hit_rate: Decimal | None
    bottom_decile_hit_rate: Decimal | None
    buy_precision_proxy: Decimal | None
    average_return_of_buy_like_group: Decimal | None
    benchmark_relative_return: Decimal | None
    score_order_changes: int
    verdict_boundary_crossings: int


@dataclass(frozen=True, slots=True)
class DiagnosticThresholdDensity:
    threshold_name: str
    threshold_value: Decimal
    feature: str
    tolerance: str
    candidate_dates_within_tolerance: int
    candidate_records_within_tolerance: int
    regime_assignments_affected: int
    outcome_distribution_near_boundary: tuple[tuple[str, int], ...]
    quality_distribution_near_boundary: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class DiagnosticThresholdPerturbation:
    threshold_name: str
    perturbation: str
    regime_distribution: tuple[tuple[str, int], ...]
    dates_changing_regime: int
    candidate_records_changing_regime: int
    outcome_ordering: tuple[str, ...]
    auc: Decimal | None
    rank_correlation: Decimal | None
    buy_precision_proxy: Decimal | None
    episode_fragmentation: int


@dataclass(frozen=True, slots=True)
class DiagnosticCoherenceException:
    regime: str
    feature_condition: str
    date_count: int
    candidate_count: int
    quality: str
    fallback_status: str
    suspected_cause: str


@dataclass(frozen=True, slots=True)
class DiagnosticSetupRegimeInteraction:
    setup_type: str
    reconstructed_regime: str
    sample_count: int
    date_count: int
    win_rate: Decimal | None
    clean_win_rate: Decimal | None
    average_return: Decimal | None
    median_return: Decimal | None
    benchmark_relative_return: Decimal | None
    average_mfe: Decimal | None
    average_mae: Decimal | None
    entry_state_distribution: tuple[tuple[str, int], ...]
    diagnostic_quality_distribution: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class DiagnosticRetracementRegimeInteraction:
    reconstructed_regime: str
    setup_family: str
    sample_count: int
    retracement_score_correlation: Decimal | None
    price_component_correlation: Decimal | None
    volume_component_correlation: Decimal | None
    forward_return_correlation: Decimal | None
    benchmark_relative_return_correlation: Decimal | None
    win_rate_by_retracement_bucket: tuple[tuple[str, Decimal | None], ...]
    finding: str


@dataclass(frozen=True, slots=True)
class DiagnosticSelectionEffect:
    stage: str
    candidate_weighted_distribution: tuple[tuple[str, int], ...]
    date_weighted_distribution: tuple[tuple[str, int], ...]
    finding: str


@dataclass(frozen=True, slots=True)
class DiagnosticBreadthSensitivity:
    comparison: str
    regime_distribution: tuple[tuple[str, int], ...]
    regime_agreement: Decimal | None
    outcome_separation: Decimal | None
    threshold_sensitivity: str
    setup_interaction: str
    classification: str


@dataclass(frozen=True, slots=True)
class DiagnosticSectorSensitivity:
    dates_affected: int
    candidate_records_affected: int
    classifier_branches_affected: tuple[str, ...]
    sector_decision_relevance: str
    maximum_possible_regime_effect: str
    classification: str


@dataclass(frozen=True, slots=True)
class DiagnosticReadinessDimension:
    name: str
    status: DiagnosticReadinessStatus
    explanation: str


@dataclass(frozen=True, slots=True)
class DiagnosticThresholdReadinessReport:
    dataset_version: str
    dataset_fingerprint: str
    dataset_status: str
    integrity: DiagnosticDatasetIntegrity
    universe_summaries: tuple[DiagnosticUniverseSummary, ...]
    candidate_weighted_regime_outcomes: tuple[DiagnosticRegimeOutcomeSummary, ...]
    date_weighted_regime_outcomes: tuple[DiagnosticRegimeOutcomeSummary, ...]
    quality_conditioned_outcomes: tuple[DiagnosticRegimeOutcomeSummary, ...]
    date_level_summaries: tuple[DiagnosticDateOutcomeSummary, ...]
    regime_episodes: tuple[DiagnosticRegimeEpisode, ...]
    intervention_comparisons: tuple[DiagnosticInterventionComparison, ...]
    threshold_density: tuple[DiagnosticThresholdDensity, ...]
    threshold_perturbations: tuple[DiagnosticThresholdPerturbation, ...]
    coherence_exceptions: tuple[DiagnosticCoherenceException, ...]
    setup_regime_interactions: tuple[DiagnosticSetupRegimeInteraction, ...]
    retracement_regime_interactions: tuple[DiagnosticRetracementRegimeInteraction, ...]
    selection_effects: tuple[DiagnosticSelectionEffect, ...]
    breadth_sensitivity: tuple[DiagnosticBreadthSensitivity, ...]
    sector_sensitivity: DiagnosticSectorSensitivity
    readiness_scorecard: tuple[DiagnosticReadinessDimension, ...]
    quality_stability: StabilityClassification
    threshold_stability: ThresholdStabilityClassification
    primary_conclusion: DiagnosticOutcomeConclusion
    secondary_conclusion: DiagnosticOutcomeConclusion | None
    recommended_next_milestone: DiagnosticNextMilestone
    explicitly_prohibited_next_action: str


class DiagnosticRegimeOutcomeValidationEngine:
    def build(
        self,
        *,
        reconstructions: tuple[DiagnosticMarketStateReconstruction, ...],
        links: tuple[DiagnosticMarketStateCandidateLink, ...],
        records: tuple[Any, ...],
        outcomes: tuple[CandidateForwardOutcome, ...],
    ) -> DiagnosticThresholdReadinessReport:
        integrity = build_diagnostic_dataset_integrity(
            reconstructions=reconstructions,
            links=links,
        )
        rows = _joined_rows(
            reconstructions=reconstructions,
            links=links,
            records=records,
            outcomes=outcomes,
        )
        completed = tuple(row for row in rows if row.completed)
        candidate_weighted = _group_outcomes(
            completed, key=lambda row: row.reconstructed_regime
        )
        date_level = _date_level_rows(completed)
        date_weighted = _date_weighted_outcomes(date_level)
        quality_conditioned = _quality_conditioned_outcomes(completed)
        intervention = _intervention_comparisons(completed)
        density = _threshold_density(rows)
        perturbations = _threshold_perturbations(rows)
        coherence = _coherence_exceptions(rows)
        setup_interactions = _setup_regime_interactions(completed)
        retracement_interactions = _retracement_regime_interactions(completed)
        selection = _selection_effects(rows)
        breadth = _breadth_sensitivity(completed)
        sector = _sector_sensitivity(rows)
        quality_stability = _quality_stability(candidate_weighted, quality_conditioned)
        threshold_stability = _threshold_stability(perturbations, rows)
        scorecard = _readiness_scorecard(
            rows=rows,
            candidate_weighted=candidate_weighted,
            date_weighted=date_weighted,
            quality_stability=quality_stability,
            threshold_stability=threshold_stability,
            breadth_sensitivity=breadth,
            sector_sensitivity=sector,
            integrity=integrity,
        )
        primary = _primary_conclusion(scorecard, candidate_weighted, quality_stability)
        secondary = _secondary_conclusion(scorecard, breadth, setup_interactions)
        return DiagnosticThresholdReadinessReport(
            dataset_version=integrity.dataset_version,
            dataset_fingerprint=integrity.dataset_fingerprint,
            dataset_status="DIAGNOSTIC ONLY",
            integrity=integrity,
            universe_summaries=tuple(
                _universe_summary(universe, rows)
                for universe in DiagnosticOutcomeUniverse
            ),
            candidate_weighted_regime_outcomes=candidate_weighted,
            date_weighted_regime_outcomes=date_weighted,
            quality_conditioned_outcomes=quality_conditioned,
            date_level_summaries=date_level,
            regime_episodes=_regime_episodes(reconstructions, rows),
            intervention_comparisons=intervention,
            threshold_density=density,
            threshold_perturbations=perturbations,
            coherence_exceptions=coherence,
            setup_regime_interactions=setup_interactions,
            retracement_regime_interactions=retracement_interactions,
            selection_effects=selection,
            breadth_sensitivity=breadth,
            sector_sensitivity=sector,
            readiness_scorecard=scorecard,
            quality_stability=quality_stability,
            threshold_stability=threshold_stability,
            primary_conclusion=primary,
            secondary_conclusion=secondary,
            recommended_next_milestone=_next_milestone(primary, scorecard),
            explicitly_prohibited_next_action=_prohibited_next_action(),
        )


def build_diagnostic_dataset_integrity(
    *,
    reconstructions: tuple[DiagnosticMarketStateReconstruction, ...],
    links: tuple[DiagnosticMarketStateCandidateLink, ...],
) -> DiagnosticDatasetIntegrity:
    reconstruction_ids = [row.reconstruction_id for row in reconstructions]
    link_keys = [(row.reconstruction_id, row.candidate_stable_id) for row in links]
    reconstruction_id_set = set(reconstruction_ids)
    orphan_links = sum(
        1 for link in links if link.reconstruction_id not in reconstruction_id_set
    )
    future_violations = sum(
        len(row.no_lookahead_violations)
        + int(
            row.benchmark_latest_bar is not None
            and row.benchmark_latest_bar > row.market_date
        )
        for row in reconstructions
    )
    version = (
        reconstructions[0].dataset_version
        if reconstructions
        else DIAGNOSTIC_MARKET_STATE_DATASET_VERSION
    )
    classifier_versions = tuple(
        sorted({row.classifier_version_used for row in reconstructions})
    )
    classifier_fingerprints = tuple(
        sorted({row.classifier_fingerprint_used for row in reconstructions})
    )
    return DiagnosticDatasetIntegrity(
        dataset_version=version,
        dataset_fingerprint=diagnostic_dataset_fingerprint(
            reconstructions=reconstructions,
            links=links,
        ),
        classifier_version_used=",".join(classifier_versions) or "unavailable",
        classifier_fingerprint_used=",".join(classifier_fingerprints) or "unavailable",
        feature_definition_version="market-feature-definitions-v1",
        reconstruction_count=len(reconstructions),
        candidate_link_count=len(links),
        duplicate_reconstruction_ids=len(reconstruction_ids)
        - len(set(reconstruction_ids)),
        duplicate_candidate_links=len(link_keys) - len(set(link_keys)),
        orphan_candidate_links=orphan_links,
        missing_reconstruction_references=orphan_links,
        future_source_violations=future_violations,
        reconstruction_created_at_values=tuple(
            sorted({row.created_at.isoformat() for row in reconstructions})
        ),
        outcome_join_timestamp="analysis-time-only-not-persisted",
        immutable_join_preserved=True,
    )


def diagnostic_dataset_fingerprint(
    *,
    reconstructions: tuple[DiagnosticMarketStateReconstruction, ...],
    links: tuple[DiagnosticMarketStateCandidateLink, ...],
) -> str:
    payload = {
        "reconstructions": [
            row.as_dict()
            for row in sorted(
                reconstructions,
                key=lambda item: (
                    item.dataset_version,
                    item.market_date,
                    item.reconstruction_id,
                ),
            )
        ],
        "links": [
            row.as_dict()
            for row in sorted(
                links,
                key=lambda item: (item.reconstruction_id, item.candidate_stable_id),
            )
        ],
    }
    raw = json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()


def render_threshold_readiness(
    report: DiagnosticThresholdReadinessReport,
) -> tuple[str, ...]:
    lines = [
        "Reconstructed Regime Outcome Validation and Threshold Readiness",
        f"Dataset Version: {report.dataset_version}",
        f"Dataset Fingerprint: {report.dataset_fingerprint}",
        f"Dataset Status: {report.dataset_status}",
        "",
        "Regime Outcome Separation",
    ]
    lines.extend(_summary_lines(report.candidate_weighted_regime_outcomes))
    lines.extend(
        [
            "",
            f"Quality Stability: {report.quality_stability.value}",
            "Date-Level Stability",
        ]
    )
    lines.extend(_summary_lines(report.date_weighted_regime_outcomes))
    lines.extend(
        [
            "",
            "Breadth-Bias Sensitivity",
        ]
    )
    lines.extend(
        (
            f"- {item.comparison}: {item.classification}, "
            f"agreement {_text(item.regime_agreement)}"
        )
        for item in report.breadth_sensitivity
    )
    lines.extend(
        [
            "",
            f"Sector Sufficiency: {report.sector_sensitivity.classification}",
            f"Threshold Sensitivity: {report.threshold_stability.value}",
            "Sample Adequacy",
        ]
    )
    sample = next(
        (item for item in report.readiness_scorecard if item.name == "sample adequacy"),
        None,
    )
    lines.append(f"- {_status_line(sample)}")
    lines.extend(
        [
            "",
            "Overall Threshold-Audit Readiness",
        ]
    )
    lines.extend(
        f"- {item.name}: {item.status.value} - {item.explanation}"
        for item in report.readiness_scorecard
    )
    lines.extend(
        [
            "",
            f"Primary Conclusion: {report.primary_conclusion.value}",
            f"Secondary Conclusion: {_enum_text(report.secondary_conclusion)}",
            f"Recommended Next Milestone: {report.recommended_next_milestone.value}",
            "Explicitly Prohibited Next Action: "
            f"{report.explicitly_prohibited_next_action}",
        ]
    )
    return tuple(lines)


def render_regime_outcomes(
    report: DiagnosticThresholdReadinessReport,
    *,
    group_by: str | None = None,
    date_weighted: bool = False,
) -> tuple[str, ...]:
    if group_by == "quality":
        rows = report.quality_conditioned_outcomes
        title = "Reconstructed Regime Outcomes by Quality"
    elif date_weighted:
        rows = report.date_weighted_regime_outcomes
        title = "Reconstructed Regime Outcomes Date-Weighted"
    else:
        rows = report.candidate_weighted_regime_outcomes
        title = "Reconstructed Regime Outcomes"
    lines = [
        title,
        "Dataset Status: DIAGNOSTIC ONLY",
        f"Dataset Version: {report.dataset_version}",
        f"Dataset Fingerprint: {report.dataset_fingerprint}",
    ]
    lines.extend(_summary_lines(rows))
    lines.append(f"Primary Conclusion: {report.primary_conclusion.value}")
    return tuple(lines)


def render_regime_intervention(
    report: DiagnosticThresholdReadinessReport,
) -> tuple[str, ...]:
    lines = [
        "Reconstructed Regime Intervention Validation",
        "Dataset Status: DIAGNOSTIC ONLY",
        f"Dataset Fingerprint: {report.dataset_fingerprint}",
    ]
    for item in report.intervention_comparisons:
        lines.append(
            f"- {item.name}: n {item.sample_size}, auc {_text(item.auc)}, "
            f"rank corr {_text(item.rank_correlation)}, top decile hit "
            f"{_text(item.top_decile_hit_rate)}, buy precision "
            f"{_text(item.buy_precision_proxy)}"
        )
    lines.append("Stored Scores Mutated: no")
    return tuple(lines)


def render_threshold_density(
    report: DiagnosticThresholdReadinessReport,
) -> tuple[str, ...]:
    lines = [
        "Reconstructed Regime Threshold Density",
        "Dataset Status: DIAGNOSTIC ONLY",
        f"Dataset Fingerprint: {report.dataset_fingerprint}",
    ]
    for item in report.threshold_density:
        lines.append(
            f"- {item.threshold_name} {item.tolerance}: dates "
            f"{item.candidate_dates_within_tolerance}, candidates "
            f"{item.candidate_records_within_tolerance}, affected "
            f"{item.regime_assignments_affected}"
        )
    return tuple(lines)


def render_threshold_stability(
    report: DiagnosticThresholdReadinessReport,
) -> tuple[str, ...]:
    lines = [
        "Reconstructed Regime Threshold Perturbation Stability",
        "Dataset Status: DIAGNOSTIC ONLY",
        f"Dataset Fingerprint: {report.dataset_fingerprint}",
        f"Classification: {report.threshold_stability.value}",
    ]
    for item in report.threshold_perturbations:
        lines.append(
            f"- {item.threshold_name} {item.perturbation}: dates changed "
            f"{item.dates_changing_regime}, candidates changed "
            f"{item.candidate_records_changing_regime}, auc {_text(item.auc)}"
        )
    lines.append("Optimization Performed: no")
    return tuple(lines)


def render_regime_coherence(
    report: DiagnosticThresholdReadinessReport,
) -> tuple[str, ...]:
    lines = [
        "Reconstructed Regime Label Coherence",
        "Dataset Status: DIAGNOSTIC ONLY",
        f"Dataset Fingerprint: {report.dataset_fingerprint}",
    ]
    if not report.coherence_exceptions:
        lines.append("- No deterministic coherence exceptions found.")
    for item in report.coherence_exceptions:
        lines.append(
            f"- {item.regime}: {item.feature_condition}; dates {item.date_count}, "
            f"candidates {item.candidate_count}, cause {item.suspected_cause}"
        )
    return tuple(lines)


def render_regime_episodes(
    report: DiagnosticThresholdReadinessReport,
) -> tuple[str, ...]:
    lines = [
        "Diagnostic Reconstructed Regime Episodes",
        "Dataset Status: DIAGNOSTIC ONLY",
        f"Dataset Fingerprint: {report.dataset_fingerprint}",
    ]
    for item in report.regime_episodes:
        lines.append(
            f"- {item.episode_id}: {item.regime} {item.start_date} to "
            f"{item.end_date}, duration {item.duration}, candidates "
            f"{item.candidate_count}, avg return {_text(item.average_return)}"
        )
    return tuple(lines)


def render_setup_regime(report: DiagnosticThresholdReadinessReport) -> tuple[str, ...]:
    lines = [
        "Reconstructed Setup-Regime Interaction",
        "Dataset Status: DIAGNOSTIC ONLY",
        f"Dataset Fingerprint: {report.dataset_fingerprint}",
    ]
    for item in report.setup_regime_interactions:
        lines.append(
            f"- {item.setup_type}/{item.reconstructed_regime}: n "
            f"{item.sample_count}, dates {item.date_count}, win "
            f"{_text(item.win_rate)}, avg return {_text(item.average_return)}"
        )
    return tuple(lines)


def render_retracement_regime(
    report: DiagnosticThresholdReadinessReport,
) -> tuple[str, ...]:
    lines = [
        "Reconstructed Retracement-Regime Interaction",
        "Dataset Status: DIAGNOSTIC ONLY",
        f"Dataset Fingerprint: {report.dataset_fingerprint}",
    ]
    for item in report.retracement_regime_interactions:
        lines.append(
            f"- {item.setup_family}/{item.reconstructed_regime}: n "
            f"{item.sample_count}, retracement corr "
            f"{_text(item.retracement_score_correlation)}, finding {item.finding}"
        )
    return tuple(lines)


def render_selection_effect(
    report: DiagnosticThresholdReadinessReport,
) -> tuple[str, ...]:
    lines = [
        "Reconstructed Candidate-Selection Effect",
        "Dataset Status: DIAGNOSTIC ONLY",
        f"Dataset Fingerprint: {report.dataset_fingerprint}",
    ]
    for item in report.selection_effects:
        lines.append(
            f"- {item.stage}: {item.finding}; candidate-weighted "
            f"{_distribution_text(item.candidate_weighted_distribution)}; "
            f"date-weighted {_distribution_text(item.date_weighted_distribution)}"
        )
    return tuple(lines)


def render_breadth_sensitivity(
    report: DiagnosticThresholdReadinessReport,
) -> tuple[str, ...]:
    lines = [
        "Reconstructed Breadth-Bias Sensitivity",
        "Dataset Status: DIAGNOSTIC ONLY",
        f"Dataset Fingerprint: {report.dataset_fingerprint}",
    ]
    for item in report.breadth_sensitivity:
        lines.append(
            f"- {item.comparison}: {item.classification}; distribution "
            f"{_distribution_text(item.regime_distribution)}; separation "
            f"{_text(item.outcome_separation)}"
        )
    return tuple(lines)


def render_sector_sensitivity(
    report: DiagnosticThresholdReadinessReport,
) -> tuple[str, ...]:
    item = report.sector_sensitivity
    return (
        "Reconstructed Missing Sector Sensitivity",
        "Dataset Status: DIAGNOSTIC ONLY",
        f"Dataset Fingerprint: {report.dataset_fingerprint}",
        f"Dates Affected: {item.dates_affected}",
        f"Candidate Records Affected: {item.candidate_records_affected}",
        f"Classifier Branches Affected: {', '.join(item.classifier_branches_affected)}",
        f"Sector Decision Relevance: {item.sector_decision_relevance}",
        f"Maximum Possible Regime Effect: {item.maximum_possible_regime_effect}",
        f"Classification: {item.classification}",
    )


def export_diagnostic_outcome_json(
    report: DiagnosticThresholdReadinessReport,
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(report), indent=2), encoding="utf-8")
    return path


def export_diagnostic_rows_csv(rows: tuple[Any, ...], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    dictionaries = [_jsonable(row) for row in rows]
    if not dictionaries:
        dictionaries = [{"status": "unavailable"}]
    fieldnames = tuple(dictionaries[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(dictionaries)
    return path


def _joined_rows(
    *,
    reconstructions: tuple[DiagnosticMarketStateReconstruction, ...],
    links: tuple[DiagnosticMarketStateCandidateLink, ...],
    records: tuple[Any, ...],
    outcomes: tuple[CandidateForwardOutcome, ...],
) -> tuple[DiagnosticOutcomeRow, ...]:
    reconstruction_by_id = {row.reconstruction_id: row for row in reconstructions}
    record_by_id = {record.candidate_id: record for record in records}
    outcome_by_id = {outcome.candidate_id: outcome for outcome in outcomes}
    rows: list[DiagnosticOutcomeRow] = []
    for link in links:
        reconstruction = reconstruction_by_id.get(link.reconstruction_id)
        record = record_by_id.get(link.candidate_stable_id)
        if reconstruction is None or record is None:
            continue
        window = _primary_window(outcome_by_id.get(record.candidate_id))
        forward_return = (
            None
            if window is None
            else window.forward_return_pct_from_entry
            or window.forward_return_pct_from_close
        )
        label = None if window is None else str(window.outcome_label)
        label_value = None if label is None else label.rsplit(".", maxsplit=1)[-1]
        positive = None
        if label_value in _POSITIVE_LABELS or (
            forward_return is not None and forward_return > _ZERO
        ):
            positive = True
        elif label_value in _NEGATIVE_LABELS or (
            forward_return is not None and forward_return < _ZERO
        ):
            positive = False
        elif forward_return is not None:
            positive = None
        benchmark_relative = (
            None
            if forward_return is None or reconstruction.benchmark_return_20d is None
            else forward_return - (reconstruction.benchmark_return_20d * _HUNDRED)
        )
        rows.append(
            DiagnosticOutcomeRow(
                candidate_id=record.candidate_id,
                symbol=record.symbol,
                market_date=record.evaluation_date,
                reconstructed_regime=reconstruction.current_classifier_regime,
                transparent_reference_state=reconstruction.transparent_reference_state.value,
                recorded_regime=record.market_regime,
                setup_type=record.setup_type,
                final_verdict=record.final_verdict,
                capital_action=record.capital_action,
                approved_for_deployment=record.approved_for_deployment,
                entry_state=link.entry_state,
                diagnostic_quality=reconstruction.overall_diagnostic_quality.value,
                input_completeness=reconstruction.input_completeness.value,
                compatibility_status=reconstruction.compatibility_status.value,
                exact_lineage=reconstruction.compatibility_status
                in _EXACT_COMPATIBILITY,
                sector=record.sector,
                strategy_score=record.strategy_score,
                forward_return=forward_return,
                benchmark_relative_return=benchmark_relative,
                mfe=None if window is None else window.max_favourable_excursion_pct,
                mae=None if window is None else window.max_adverse_excursion_pct,
                target_1_hit=None if window is None else window.target_1_touched,
                stop_hit=None if window is None else window.risk_stop_touched,
                outcome_label=label_value,
                completed=_is_completed(window),
                clean_win=label_value in _POSITIVE_LABELS
                and window is not None
                and not window.risk_stop_touched,
                positive=positive,
                retracement_score=_indicator_decimal(record, "retracement"),
                price_component_score=_indicator_decimal(record, "price"),
                volume_component_score=_indicator_decimal(record, "volume"),
                benchmark_return_20d=reconstruction.benchmark_return_20d,
                benchmark_above_50dma=_above_dma(
                    reconstruction.benchmark_close,
                    reconstruction.benchmark_dma_50,
                ),
                benchmark_above_200dma=_above_dma(
                    reconstruction.benchmark_close,
                    reconstruction.benchmark_dma_200,
                ),
            )
        )
    return tuple(
        sorted(rows, key=lambda row: (row.market_date, row.symbol, row.candidate_id))
    )


def _universe_summary(
    universe: DiagnosticOutcomeUniverse,
    rows: tuple[DiagnosticOutcomeRow, ...],
) -> DiagnosticUniverseSummary:
    filtered = _filter_universe(universe, rows)
    positive = sum(1 for row in filtered if row.positive is True)
    negative = sum(1 for row in filtered if row.positive is False)
    flat = sum(
        1
        for row in filtered
        if row.completed and row.positive is None and row.forward_return == _ZERO
    )
    unavailable = sum(1 for row in filtered if not row.completed)
    return DiagnosticUniverseSummary(
        universe=universe.value,
        candidate_count=len(filtered),
        date_count=len({row.market_date for row in filtered}),
        positive_return_count=positive,
        negative_return_count=negative,
        flat_count=flat,
        outcome_unavailable_count=unavailable,
        setup_distribution=_counts(row.setup_type or "UNAVAILABLE" for row in filtered),
        regime_distribution=_counts(row.reconstructed_regime for row in filtered),
        quality_distribution=_counts(row.diagnostic_quality for row in filtered),
        lineage_distribution=_counts(
            "EXACT_LINEAGE" if row.exact_lineage else "COMPATIBILITY_ONLY"
            for row in filtered
        ),
    )


def _filter_universe(
    universe: DiagnosticOutcomeUniverse,
    rows: tuple[DiagnosticOutcomeRow, ...],
) -> tuple[DiagnosticOutcomeRow, ...]:
    if universe is DiagnosticOutcomeUniverse.ALL_COMPLETED_OUTCOMES:
        return tuple(row for row in rows if row.completed)
    if universe is DiagnosticOutcomeUniverse.ACCEPTABLE_ENTRY_TIMING:
        return tuple(
            row
            for row in rows
            if row.completed
            and row.entry_state in {"APPROVED", "PREFERRED_ENTRY", "CONFIRMED_ENTRY"}
        )
    if universe is DiagnosticOutcomeUniverse.BUY_OR_STRONG_BUY:
        return tuple(
            row for row in rows if row.completed and row.final_verdict in _BUY_VERDICTS
        )
    if universe is DiagnosticOutcomeUniverse.HIGH_DIAGNOSTIC_QUALITY:
        return tuple(
            row for row in rows if row.completed and row.diagnostic_quality == "HIGH"
        )
    if universe is DiagnosticOutcomeUniverse.HIGH_OR_MEDIUM_DIAGNOSTIC_QUALITY:
        return tuple(
            row
            for row in rows
            if row.completed and row.diagnostic_quality in {"HIGH", "MEDIUM"}
        )
    if universe is DiagnosticOutcomeUniverse.COMPLETE_DIAGNOSTIC_ONLY:
        return tuple(
            row
            for row in rows
            if row.completed
            and row.input_completeness
            == DiagnosticInputCompleteness.COMPLETE_DIAGNOSTIC.value
        )
    if universe is DiagnosticOutcomeUniverse.EXACT_LINEAGE_ONLY:
        return tuple(row for row in rows if row.completed and row.exact_lineage)
    return tuple(row for row in rows if row.completed and not row.exact_lineage)


def _group_outcomes(
    rows: tuple[DiagnosticOutcomeRow, ...],
    *,
    key: Any,
) -> tuple[DiagnosticRegimeOutcomeSummary, ...]:
    groups: dict[str, list[DiagnosticOutcomeRow]] = defaultdict(list)
    for row in rows:
        groups[str(key(row) or "UNAVAILABLE")].append(row)
    return tuple(
        _outcome_summary(name, tuple(group)) for name, group in sorted(groups.items())
    )


def _outcome_summary(
    group: str,
    rows: tuple[DiagnosticOutcomeRow, ...],
) -> DiagnosticRegimeOutcomeSummary:
    completed = tuple(row for row in rows if row.completed)
    wins = sum(1 for row in completed if row.positive is True)
    losses = sum(1 for row in completed if row.positive is False)
    clean = sum(1 for row in completed if row.clean_win)
    buy_rows = tuple(row for row in completed if row.final_verdict in _BUY_VERDICTS)
    rejected = tuple(row for row in completed if row.final_verdict not in _BUY_VERDICTS)
    profitable_rejections = sum(1 for row in rejected if row.positive is True)
    return DiagnosticRegimeOutcomeSummary(
        group=group,
        candidate_count=len(rows),
        date_count=len({row.market_date for row in rows}),
        completed_outcomes=len(completed),
        win_rate=_rate(wins, len(completed)),
        clean_win_rate=_rate(clean, len(completed)),
        loss_rate=_rate(losses, len(completed)),
        average_forward_return=_mean(row.forward_return for row in completed),
        median_forward_return=_median(row.forward_return for row in completed),
        average_benchmark_relative_return=_mean(
            row.benchmark_relative_return for row in completed
        ),
        average_mfe=_mean(row.mfe for row in completed),
        average_mae=_mean(row.mae for row in completed),
        stop_hit_rate=_rate(
            sum(1 for row in completed if row.stop_hit), len(completed)
        ),
        target_hit_rate=_rate(
            sum(1 for row in completed if row.target_1_hit),
            len(completed),
        ),
        buy_precision_proxy=_rate(
            sum(1 for row in buy_rows if row.positive is True),
            len(buy_rows),
        ),
        profitable_rejection_rate=_rate(profitable_rejections, len(rejected)),
    )


def _date_level_rows(
    rows: tuple[DiagnosticOutcomeRow, ...],
) -> tuple[DiagnosticDateOutcomeSummary, ...]:
    groups: dict[date, list[DiagnosticOutcomeRow]] = defaultdict(list)
    for row in rows:
        groups[row.market_date].append(row)
    summaries = []
    for market_date, group_list in sorted(groups.items()):
        group = tuple(group_list)
        regimes = Counter(row.reconstructed_regime for row in group)
        buy_rows = tuple(row for row in group if row.final_verdict in _BUY_VERDICTS)
        summaries.append(
            DiagnosticDateOutcomeSummary(
                market_date=market_date,
                reconstructed_regime=regimes.most_common(1)[0][0],
                candidate_count=len(group),
                date_average_return=_mean(row.forward_return for row in group),
                date_median_return=_median(row.forward_return for row in group),
                buy_precision_proxy=_rate(
                    sum(1 for row in buy_rows if row.positive is True),
                    len(buy_rows),
                ),
                benchmark_return=group[0].benchmark_return_20d,
                setup_distribution=_counts(
                    row.setup_type or "UNAVAILABLE" for row in group
                ),
            )
        )
    return tuple(summaries)


def _date_weighted_outcomes(
    rows: tuple[DiagnosticDateOutcomeSummary, ...],
) -> tuple[DiagnosticRegimeOutcomeSummary, ...]:
    grouped: dict[str, list[DiagnosticDateOutcomeSummary]] = defaultdict(list)
    for row in rows:
        grouped[row.reconstructed_regime].append(row)
    summaries = []
    for regime, group in sorted(grouped.items()):
        pseudo = tuple(
            DiagnosticOutcomeRow(
                candidate_id=f"date-{row.market_date}",
                symbol="DATE",
                market_date=row.market_date,
                reconstructed_regime=regime,
                transparent_reference_state="UNAVAILABLE",
                recorded_regime=None,
                setup_type=None,
                final_verdict="DATE_WEIGHTED",
                capital_action="UNAVAILABLE",
                approved_for_deployment=False,
                entry_state=None,
                diagnostic_quality="DATE_WEIGHTED",
                input_completeness="DATE_WEIGHTED",
                compatibility_status="DATE_WEIGHTED",
                exact_lineage=False,
                sector=None,
                strategy_score=_ZERO,
                forward_return=row.date_average_return,
                benchmark_relative_return=None
                if row.date_average_return is None or row.benchmark_return is None
                else row.date_average_return - (row.benchmark_return * _HUNDRED),
                mfe=None,
                mae=None,
                target_1_hit=None,
                stop_hit=None,
                outcome_label=None,
                completed=row.date_average_return is not None,
                clean_win=False,
                positive=None
                if row.date_average_return is None
                else row.date_average_return > _ZERO,
                retracement_score=None,
                price_component_score=None,
                volume_component_score=None,
                benchmark_return_20d=row.benchmark_return,
                benchmark_above_50dma=None,
                benchmark_above_200dma=None,
            )
            for row in group
        )
        summaries.append(_outcome_summary(regime, pseudo))
    return tuple(summaries)


def _quality_conditioned_outcomes(
    rows: tuple[DiagnosticOutcomeRow, ...],
) -> tuple[DiagnosticRegimeOutcomeSummary, ...]:
    return _group_outcomes(
        rows,
        key=lambda row: f"{row.diagnostic_quality}/{row.reconstructed_regime}",
    )


def _regime_episodes(
    reconstructions: tuple[DiagnosticMarketStateReconstruction, ...],
    rows: tuple[DiagnosticOutcomeRow, ...],
) -> tuple[DiagnosticRegimeEpisode, ...]:
    rows_by_date: dict[date, list[DiagnosticOutcomeRow]] = defaultdict(list)
    for row in rows:
        rows_by_date[row.market_date].append(row)
    ordered = sorted(reconstructions, key=lambda row: row.market_date)
    episodes: list[DiagnosticRegimeEpisode] = []
    current: list[DiagnosticMarketStateReconstruction] = []
    previous_regime = "START"
    for reconstruction in ordered:
        if (
            current
            and reconstruction.current_classifier_regime
            != current[-1].current_classifier_regime
        ):
            episodes.append(
                _episode(
                    current,
                    rows_by_date,
                    previous_regime,
                    reconstruction.current_classifier_regime,
                    len(episodes) + 1,
                )
            )
            previous_regime = current[-1].current_classifier_regime
            current = []
        current.append(reconstruction)
    if current:
        episodes.append(
            _episode(current, rows_by_date, previous_regime, "END", len(episodes) + 1)
        )
    return tuple(episodes)


def _episode(
    reconstructions: list[DiagnosticMarketStateReconstruction],
    rows_by_date: dict[date, list[DiagnosticOutcomeRow]],
    transition_in: str,
    transition_out: str,
    index: int,
) -> DiagnosticRegimeEpisode:
    joined = tuple(
        row
        for reconstruction in reconstructions
        for row in rows_by_date.get(reconstruction.market_date, [])
    )
    return DiagnosticRegimeEpisode(
        episode_id=f"diagnostic-episode-{index:04d}",
        regime=reconstructions[0].current_classifier_regime,
        start_date=reconstructions[0].market_date,
        end_date=reconstructions[-1].market_date,
        duration=len(reconstructions),
        candidate_count=len(joined),
        completed_outcomes=sum(1 for row in joined if row.completed),
        average_return=_mean(row.forward_return for row in joined),
        benchmark_relative_return=_mean(
            row.benchmark_relative_return for row in joined
        ),
        maximum_adverse_excursion=_mean(row.mae for row in joined),
        transition_into_episode=transition_in,
        transition_out_of_episode=transition_out,
    )


def _intervention_comparisons(
    rows: tuple[DiagnosticOutcomeRow, ...],
) -> tuple[DiagnosticInterventionComparison, ...]:
    score_sets = {
        "RECORDED_PRODUCTION_SCORE": tuple((row.strategy_score, row) for row in rows),
        "NO_REGIME_ADJUSTMENT": tuple((_base_score(row), row) for row in rows),
        "RECORDED_REGIME_ADJUSTMENT": tuple(
            (_recorded_adjusted_score(row), row) for row in rows
        ),
        "RECONSTRUCTED_REGIME_ADJUSTMENT": tuple(
            (_reconstructed_adjusted_score(row), row) for row in rows
        ),
    }
    return tuple(
        _intervention_summary(name, values) for name, values in score_sets.items()
    )


def _intervention_summary(
    name: str,
    values: tuple[tuple[Decimal, DiagnosticOutcomeRow], ...],
) -> DiagnosticInterventionComparison:
    labels = tuple(
        1 if row.positive is True else 0
        for _, row in values
        if row.positive is not None
    )
    scores = tuple(score for score, row in values if row.positive is not None)
    returns = tuple(
        row.forward_return for _, row in values if row.forward_return is not None
    )
    return DiagnosticInterventionComparison(
        name=name,
        sample_size=len(values),
        auc=_roc_auc(scores, labels),
        rank_correlation=_spearman(scores[: len(returns)], returns),
        top_decile_hit_rate=_decile_hit_rate(values, top=True),
        bottom_decile_hit_rate=_decile_hit_rate(values, top=False),
        buy_precision_proxy=_rate(
            sum(
                1
                for score, row in values
                if score >= Decimal("75") and row.positive is True
            ),
            sum(1 for score, _ in values if score >= Decimal("75")),
        ),
        average_return_of_buy_like_group=_mean(
            row.forward_return for score, row in values if score >= Decimal("75")
        ),
        benchmark_relative_return=_mean(
            row.benchmark_relative_return
            for score, row in values
            if score >= Decimal("75")
        ),
        score_order_changes=0
        if name == "RECORDED_PRODUCTION_SCORE"
        else _score_order_changes(values),
        verdict_boundary_crossings=sum(
            1
            for score, row in values
            if (row.strategy_score >= Decimal("75")) != (score >= Decimal("75"))
        ),
    )


def _threshold_density(
    rows: tuple[DiagnosticOutcomeRow, ...],
) -> tuple[DiagnosticThresholdDensity, ...]:
    specs = (
        (
            "benchmark_return_20d_positive_boundary",
            Decimal("0"),
            "benchmark_return_20d",
        ),
        (
            "benchmark_return_20d_strong_boundary",
            Decimal("0.03"),
            "benchmark_return_20d",
        ),
        (
            "benchmark_distance_50dma_boundary",
            Decimal("0"),
            "benchmark_above_50dma_proxy",
        ),
    )
    output = []
    for name, threshold, feature in specs:
        for tolerance in (Decimal("0.01"), Decimal("0.05"), Decimal("0.10")):
            near = tuple(
                row
                for row in rows
                if _near_threshold(row, feature, threshold, tolerance)
            )
            output.append(
                DiagnosticThresholdDensity(
                    threshold_name=name,
                    threshold_value=threshold,
                    feature=feature,
                    tolerance=f"+/-{tolerance}",
                    candidate_dates_within_tolerance=len(
                        {row.market_date for row in near}
                    ),
                    candidate_records_within_tolerance=len(near),
                    regime_assignments_affected=len(near),
                    outcome_distribution_near_boundary=_counts(
                        row.outcome_label or "OUTCOME_UNAVAILABLE" for row in near
                    ),
                    quality_distribution_near_boundary=_counts(
                        row.diagnostic_quality for row in near
                    ),
                )
            )
    return tuple(output)


def _threshold_perturbations(
    rows: tuple[DiagnosticOutcomeRow, ...],
) -> tuple[DiagnosticThresholdPerturbation, ...]:
    output = []
    for threshold_name, perturbation, delta in (
        ("benchmark_return_20d_positive_boundary", "slightly_tighter", Decimal("0.01")),
        ("benchmark_return_20d_positive_boundary", "slightly_looser", Decimal("-0.01")),
        ("benchmark_return_20d_strong_boundary", "slightly_tighter", Decimal("0.01")),
        ("benchmark_return_20d_strong_boundary", "slightly_looser", Decimal("-0.01")),
    ):
        changed = tuple(row for row in rows if _would_change_simple_regime(row, delta))
        regimes = tuple(_perturbed_regime(row, delta) for row in rows)
        output.append(
            DiagnosticThresholdPerturbation(
                threshold_name=threshold_name,
                perturbation=perturbation,
                regime_distribution=_counts(regimes),
                dates_changing_regime=len({row.market_date for row in changed}),
                candidate_records_changing_regime=len(changed),
                outcome_ordering=tuple(
                    item.group
                    for item in _group_outcomes(
                        rows, key=lambda row: _perturbed_regime(row, delta)
                    )
                ),
                auc=_roc_auc(
                    tuple(
                        _regime_score(_perturbed_regime(row, delta))
                        for row in rows
                        if row.positive is not None
                    ),
                    tuple(
                        1 if row.positive else 0
                        for row in rows
                        if row.positive is not None
                    ),
                ),
                rank_correlation=_spearman(
                    tuple(
                        _regime_score(_perturbed_regime(row, delta))
                        for row in rows
                        if row.forward_return is not None
                    ),
                    tuple(
                        row.forward_return
                        for row in rows
                        if row.forward_return is not None
                    ),
                ),
                buy_precision_proxy=_rate(
                    sum(
                        1
                        for row in rows
                        if _perturbed_regime(row, delta) == "BULLISH"
                        and row.positive is True
                    ),
                    sum(
                        1 for row in rows if _perturbed_regime(row, delta) == "BULLISH"
                    ),
                ),
                episode_fragmentation=len(
                    tuple(
                        regimes[index]
                        for index in range(1, len(regimes))
                        if regimes[index] != regimes[index - 1]
                    )
                ),
            )
        )
    return tuple(output)


def _coherence_exceptions(
    rows: tuple[DiagnosticOutcomeRow, ...],
) -> tuple[DiagnosticCoherenceException, ...]:
    checks: tuple[
        tuple[str, str, Callable[[DiagnosticOutcomeRow], bool], str],
        ...,
    ] = (
        (
            "BULLISH",
            "benchmark below 50-DMA or 200-DMA proxy",
            lambda row: (
                row.reconstructed_regime == "BULLISH"
                and (
                    row.benchmark_above_50dma is False
                    or row.benchmark_above_200dma is False
                )
            ),
            "classifier boundary interaction or missing breadth override",
        ),
        (
            "BEARISH",
            "strongly positive 20-day benchmark return",
            lambda row: (
                row.reconstructed_regime == "BEARISH"
                and row.benchmark_return_20d is not None
                and row.benchmark_return_20d > Decimal("0.03")
            ),
            "breadth or volatility override",
        ),
        (
            "NEUTRAL",
            "extreme 20-day benchmark move",
            lambda row: (
                row.reconstructed_regime == "NEUTRAL"
                and row.benchmark_return_20d is not None
                and abs(row.benchmark_return_20d) > Decimal("0.08")
            ),
            "partial lookback or classifier boundary interaction",
        ),
    )
    output = []
    for regime, condition, predicate, cause in checks:
        matches = tuple(row for row in rows if predicate(row))
        if matches:
            output.append(
                DiagnosticCoherenceException(
                    regime=regime,
                    feature_condition=condition,
                    date_count=len({row.market_date for row in matches}),
                    candidate_count=len(matches),
                    quality=_distribution_text(
                        _counts(row.diagnostic_quality for row in matches)
                    ),
                    fallback_status=_distribution_text(
                        _counts(row.input_completeness for row in matches)
                    ),
                    suspected_cause=cause,
                )
            )
    return tuple(output)


def _setup_regime_interactions(
    rows: tuple[DiagnosticOutcomeRow, ...],
) -> tuple[DiagnosticSetupRegimeInteraction, ...]:
    groups: dict[tuple[str, str], list[DiagnosticOutcomeRow]] = defaultdict(list)
    for row in rows:
        groups[(row.setup_type or "UNAVAILABLE", row.reconstructed_regime)].append(row)
    output = []
    for (setup, regime), group_list in sorted(groups.items()):
        group = tuple(group_list)
        summary = _outcome_summary(f"{setup}/{regime}", group)
        output.append(
            DiagnosticSetupRegimeInteraction(
                setup_type=setup,
                reconstructed_regime=regime,
                sample_count=len(group),
                date_count=summary.date_count,
                win_rate=summary.win_rate,
                clean_win_rate=summary.clean_win_rate,
                average_return=summary.average_forward_return,
                median_return=summary.median_forward_return,
                benchmark_relative_return=summary.average_benchmark_relative_return,
                average_mfe=summary.average_mfe,
                average_mae=summary.average_mae,
                entry_state_distribution=_counts(
                    row.entry_state or "UNAVAILABLE" for row in group
                ),
                diagnostic_quality_distribution=_counts(
                    row.diagnostic_quality for row in group
                ),
            )
        )
    return tuple(output)


def _retracement_regime_interactions(
    rows: tuple[DiagnosticOutcomeRow, ...],
) -> tuple[DiagnosticRetracementRegimeInteraction, ...]:
    groups: dict[tuple[str, str], list[DiagnosticOutcomeRow]] = defaultdict(list)
    for row in rows:
        family = (
            "MOMENTUM" if row.setup_type and "MOMENTUM" in row.setup_type else "OTHER"
        )
        groups[(row.reconstructed_regime, family)].append(row)
    output = []
    for (regime, family), group_list in sorted(groups.items()):
        group = tuple(row for row in group_list if row.retracement_score is not None)
        corr = _spearman(
            tuple(
                row.retracement_score for row in group if row.forward_return is not None
            ),
            tuple(
                row.forward_return for row in group if row.forward_return is not None
            ),
        )
        output.append(
            DiagnosticRetracementRegimeInteraction(
                reconstructed_regime=regime,
                setup_family=family,
                sample_count=len(group),
                retracement_score_correlation=corr,
                price_component_correlation=_score_return_corr(group, "price"),
                volume_component_correlation=_score_return_corr(group, "volume"),
                forward_return_correlation=corr,
                benchmark_relative_return_correlation=_spearman(
                    tuple(
                        row.retracement_score
                        for row in group
                        if row.benchmark_relative_return is not None
                    ),
                    tuple(
                        row.benchmark_relative_return
                        for row in group
                        if row.benchmark_relative_return is not None
                    ),
                ),
                win_rate_by_retracement_bucket=_retracement_buckets(group),
                finding=_retracement_finding(corr, len(group)),
            )
        )
    return tuple(output)


def _selection_effects(
    rows: tuple[DiagnosticOutcomeRow, ...],
) -> tuple[DiagnosticSelectionEffect, ...]:
    stages = {
        "all candidate records": rows,
        "BUY candidates": tuple(
            row for row in rows if row.final_verdict in _BUY_VERDICTS
        ),
        "acceptably timed candidates": tuple(
            row for row in rows if row.entry_state == "APPROVED"
        ),
        "raw approved candidates": tuple(
            row for row in rows if row.approved_for_deployment
        ),
        "strict institutional approvals": tuple(
            row
            for row in rows
            if row.approved_for_deployment and row.capital_action in _APPROVED_ACTIONS
        ),
        "completed outcomes": tuple(row for row in rows if row.completed),
        "top recommendation-score decile": _top_decile(rows),
    }
    baseline = _regime_share(rows)
    output = []
    for stage, stage_rows in stages.items():
        distribution = _counts(row.reconstructed_regime for row in stage_rows)
        date_distribution = _counts(
            regime
            for regime in {
                row.market_date: row.reconstructed_regime for row in stage_rows
            }.values()
        )
        output.append(
            DiagnosticSelectionEffect(
                stage=stage,
                candidate_weighted_distribution=distribution,
                date_weighted_distribution=date_distribution,
                finding=_selection_finding(baseline, _regime_share(stage_rows), stage),
            )
        )
    return tuple(output)


def _breadth_sensitivity(
    rows: tuple[DiagnosticOutcomeRow, ...],
) -> tuple[DiagnosticBreadthSensitivity, ...]:
    comparisons = {
        "BENCHMARK_ONLY": tuple(_benchmark_only_regime(row) for row in rows),
        "BENCHMARK_PLUS_DIAGNOSTIC_BREADTH": tuple(
            row.reconstructed_regime for row in rows
        ),
        "TRANSPARENT_REFERENCE_STATE": tuple(
            _reference_to_regime(row.transparent_reference_state) for row in rows
        ),
        "CURRENT_COMPATIBLE_FULL_REPLAY": tuple(
            row.reconstructed_regime for row in rows
        ),
    }
    reconstructed = comparisons["CURRENT_COMPATIBLE_FULL_REPLAY"]
    output = []
    for name, regimes in comparisons.items():
        outcome_rows = tuple(
            DiagnosticOutcomeRow(
                **{**asdict(row), "reconstructed_regime": regimes[index]}
            )
            for index, row in enumerate(rows)
        )
        summaries = _group_outcomes(
            outcome_rows, key=lambda row: row.reconstructed_regime
        )
        agreement = _rate(
            sum(
                1
                for actual, replay in zip(regimes, reconstructed, strict=False)
                if actual == replay
            ),
            len(regimes),
        )
        output.append(
            DiagnosticBreadthSensitivity(
                comparison=name,
                regime_distribution=_counts(regimes),
                regime_agreement=agreement,
                outcome_separation=_regime_spread(summaries),
                threshold_sensitivity="diagnostic; no threshold optimization performed",
                setup_interaction="available through reconstructed-setup-regime",
                classification=_breadth_classification(name, summaries, agreement),
            )
        )
    return tuple(output)


def _sector_sensitivity(
    rows: tuple[DiagnosticOutcomeRow, ...],
) -> DiagnosticSectorSensitivity:
    return DiagnosticSectorSensitivity(
        dates_affected=len({row.market_date for row in rows}),
        candidate_records_affected=len(rows),
        classifier_branches_affected=("sector_score", "sector_confirmation"),
        sector_decision_relevance=(
            "diagnostic market-state reconstruction has zero point-in-time "
            "sector coverage"
        ),
        maximum_possible_regime_effect="unknown without point-in-time sector state",
        classification="MISSING_SECTOR_PREVENTS_THRESHOLD_AUDIT"
        if rows
        else "MISSING_SECTOR_NOT_MATERIAL_TO_REGIME",
    )


def _readiness_scorecard(
    *,
    rows: tuple[DiagnosticOutcomeRow, ...],
    candidate_weighted: tuple[DiagnosticRegimeOutcomeSummary, ...],
    date_weighted: tuple[DiagnosticRegimeOutcomeSummary, ...],
    quality_stability: StabilityClassification,
    threshold_stability: ThresholdStabilityClassification,
    breadth_sensitivity: tuple[DiagnosticBreadthSensitivity, ...],
    sector_sensitivity: DiagnosticSectorSensitivity,
    integrity: DiagnosticDatasetIntegrity,
) -> tuple[DiagnosticReadinessDimension, ...]:
    completed = sum(1 for row in rows if row.completed)
    distinct_dates = len({row.market_date for row in rows if row.completed})
    non_neutral = sum(1 for row in rows if row.reconstructed_regime != "NEUTRAL")
    separation = _regime_spread(candidate_weighted)
    date_spread = _regime_spread(date_weighted)
    breadth_blocked = any(
        item.classification == "BREADTH_BIAS_MATERIALLY_AFFECTS_CONCLUSION"
        for item in breadth_sensitivity
    )
    dimensions = (
        _dimension(
            "regime diversity",
            non_neutral >= 30,
            "Reconstructed data contains directional regimes."
            if non_neutral >= 30
            else "Too few non-neutral reconstructed records.",
        ),
        _dimension(
            "outcome separation",
            separation is not None and abs(separation) >= Decimal("0.02"),
            f"Candidate-weighted return spread is {_text(separation)}.",
        ),
        DiagnosticReadinessDimension(
            name="quality stability",
            status=DiagnosticReadinessStatus.READY
            if quality_stability is StabilityClassification.STABLE_ACROSS_QUALITY
            else DiagnosticReadinessStatus.NOT_READY,
            explanation=quality_stability.value,
        ),
        _dimension(
            "date-level stability",
            date_spread is not None
            and separation is not None
            and _same_sign(date_spread, separation),
            f"Date-weighted spread is {_text(date_spread)}.",
        ),
        _dimension(
            "benchmark-only consistency",
            True,
            (
                "Benchmark-only comparison is reported separately; "
                "not used as production proof."
            ),
        ),
        DiagnosticReadinessDimension(
            name="breadth-bias sensitivity",
            status=DiagnosticReadinessStatus.NOT_READY
            if breadth_blocked
            else DiagnosticReadinessStatus.CONDITIONALLY_READY,
            explanation=(
                "Current-universe breadth remains diagnostic and non-authoritative."
            ),
        ),
        DiagnosticReadinessDimension(
            name="sector-data sufficiency",
            status=DiagnosticReadinessStatus.NOT_READY
            if "PREVENTS" in sector_sensitivity.classification
            else DiagnosticReadinessStatus.READY,
            explanation=sector_sensitivity.classification,
        ),
        DiagnosticReadinessDimension(
            name="classifier compatibility",
            status=DiagnosticReadinessStatus.CONDITIONALLY_READY
            if integrity.future_source_violations == 0
            else DiagnosticReadinessStatus.NOT_READY,
            explanation="Most records remain compatibility-only, not exact replay.",
        ),
        DiagnosticReadinessDimension(
            name="threshold sensitivity",
            status=DiagnosticReadinessStatus.READY
            if threshold_stability is ThresholdStabilityClassification.THRESHOLDS_STABLE
            else DiagnosticReadinessStatus.NOT_READY,
            explanation=threshold_stability.value,
        ),
        _dimension(
            "sample adequacy",
            completed >= 100 and distinct_dates >= 30,
            f"Completed outcomes {completed}, distinct dates {distinct_dates}.",
        ),
    )
    return dimensions


def _primary_conclusion(
    scorecard: tuple[DiagnosticReadinessDimension, ...],
    outcomes: tuple[DiagnosticRegimeOutcomeSummary, ...],
    quality_stability: StabilityClassification,
) -> DiagnosticOutcomeConclusion:
    conclusion = DiagnosticOutcomeConclusion
    not_ready = sum(
        1 for item in scorecard if item.status is DiagnosticReadinessStatus.NOT_READY
    )
    spread = _regime_spread(outcomes)
    if not_ready >= 3:
        return DiagnosticOutcomeConclusion.DIAGNOSTIC_DATA_QUALITY_IS_PRIMARY_LIMITATION
    if (
        quality_stability is StabilityClassification.STABLE_ACROSS_QUALITY
        and spread
        and abs(spread) >= Decimal("0.05")
    ):
        return conclusion.RECONSTRUCTED_REGIME_HAS_STABLE_OUTCOME_SEPARATION
    if spread and abs(spread) >= Decimal("0.02"):
        return conclusion.RECONSTRUCTED_REGIME_HAS_LIMITED_OUTCOME_SEPARATION
    if spread is not None:
        return conclusion.RECONSTRUCTED_REGIME_HAS_NO_USEFUL_OUTCOME_SEPARATION
    return DiagnosticOutcomeConclusion.NO_SINGLE_REGIME_VALIDATION_CONCLUSION


def _secondary_conclusion(
    scorecard: tuple[DiagnosticReadinessDimension, ...],
    breadth: tuple[DiagnosticBreadthSensitivity, ...],
    setups: tuple[DiagnosticSetupRegimeInteraction, ...],
) -> DiagnosticOutcomeConclusion | None:
    conclusion = DiagnosticOutcomeConclusion
    if any("MATERIAL" in item.classification for item in breadth):
        return DiagnosticOutcomeConclusion.BREADTH_BIAS_IS_PRIMARY_LIMITATION
    if any(
        item.setup_type == "MOMENTUM_CONTINUATION"
        and item.reconstructed_regime == "BEARISH"
        and (item.win_rate or _ZERO) < Decimal("0.40")
        and item.sample_count >= 10
        for item in setups
    ):
        return conclusion.MOMENTUM_MARKET_STATE_INTERACTION_IS_PRIMARY_FINDING
    if any(item.status is DiagnosticReadinessStatus.NOT_READY for item in scorecard):
        return DiagnosticOutcomeConclusion.DIAGNOSTIC_DATA_QUALITY_IS_PRIMARY_LIMITATION
    return None


def _next_milestone(
    conclusion: DiagnosticOutcomeConclusion,
    scorecard: tuple[DiagnosticReadinessDimension, ...],
) -> DiagnosticNextMilestone:
    all_ready = all(
        item.status
        in {
            DiagnosticReadinessStatus.READY,
            DiagnosticReadinessStatus.CONDITIONALLY_READY,
        }
        for item in scorecard
    )
    hard_blocks = {
        item.name
        for item in scorecard
        if item.status is DiagnosticReadinessStatus.NOT_READY
    }
    if all_ready and conclusion is (
        DiagnosticOutcomeConclusion.RECONSTRUCTED_REGIME_HAS_STABLE_OUTCOME_SEPARATION
    ):
        return DiagnosticNextMilestone.AUDIT_MARKET_REGIME_THRESHOLD_DEFINITIONS
    if "sector-data sufficiency" in hard_blocks:
        return DiagnosticNextMilestone.BUILD_POINT_IN_TIME_SECTOR_HISTORY
    if "breadth-bias sensitivity" in hard_blocks:
        return DiagnosticNextMilestone.BUILD_POINT_IN_TIME_BREADTH_HISTORY
    if "sample adequacy" in hard_blocks:
        return DiagnosticNextMilestone.INSUFFICIENT_EVIDENCE_COLLECT_MORE_DATA
    return DiagnosticNextMilestone.ACCEPT_LEGACY_REGIME_ANALYSIS_AS_DIAGNOSTIC_ONLY


def _quality_stability(
    candidate_weighted: tuple[DiagnosticRegimeOutcomeSummary, ...],
    quality_conditioned: tuple[DiagnosticRegimeOutcomeSummary, ...],
) -> StabilityClassification:
    if not candidate_weighted or not quality_conditioned:
        return StabilityClassification.INSUFFICIENT_EVIDENCE
    high = tuple(row for row in quality_conditioned if row.group.startswith("HIGH/"))
    if sum(row.completed_outcomes for row in high) < 30:
        return StabilityClassification.LOW_SAMPLE_UNSTABLE
    all_spread = _regime_spread(candidate_weighted)
    high_spread = _regime_spread(high)
    if all_spread is None or high_spread is None:
        return StabilityClassification.INSUFFICIENT_EVIDENCE
    if not _same_sign(all_spread, high_spread):
        return StabilityClassification.SIGN_REVERSAL_ACROSS_QUALITY
    if abs(high_spread) > abs(all_spread):
        return StabilityClassification.STRENGTHENS_ON_HIGH_QUALITY_FILTER
    if abs(high_spread) < abs(all_spread) / Decimal("2"):
        return StabilityClassification.WEAKENS_ON_HIGH_QUALITY_FILTER
    return StabilityClassification.STABLE_ACROSS_QUALITY


def _threshold_stability(
    perturbations: tuple[DiagnosticThresholdPerturbation, ...],
    rows: tuple[DiagnosticOutcomeRow, ...],
) -> ThresholdStabilityClassification:
    if not rows:
        return ThresholdStabilityClassification.UNSTABLE_DUE_TO_DATA_QUALITY
    max_changed = max(
        (item.candidate_records_changing_regime for item in perturbations),
        default=0,
    )
    share = Decimal(max_changed) / Decimal(max(len(rows), 1))
    if share < Decimal("0.05"):
        return ThresholdStabilityClassification.THRESHOLDS_STABLE
    if share < Decimal("0.20"):
        return ThresholdStabilityClassification.MODERATELY_SENSITIVE
    return ThresholdStabilityClassification.HIGHLY_SENSITIVE


def _dimension(name: str, ok: bool, explanation: str) -> DiagnosticReadinessDimension:
    return DiagnosticReadinessDimension(
        name=name,
        status=DiagnosticReadinessStatus.READY
        if ok
        else DiagnosticReadinessStatus.NOT_READY,
        explanation=explanation,
    )


def _primary_window(
    outcome: CandidateForwardOutcome | None,
    preferred: str = "20d",
) -> CandidateForwardWindowOutcome | None:
    if outcome is None:
        return None
    return next(
        (window for window in outcome.windows if window.window == preferred),
        outcome.windows[0] if outcome.windows else None,
    )


def _is_completed(window: CandidateForwardWindowOutcome | None) -> bool:
    label = None if window is None else str(window.outcome_label).rsplit(".", 1)[-1]
    return (
        window is not None
        and label != _DATA_MISSING_LABEL
        and window.forward_return_pct_from_entry is not None
        or (
            window is not None
            and label != _DATA_MISSING_LABEL
            and window.forward_return_pct_from_close is not None
        )
    )


def _indicator_decimal(record: Any, contains: str) -> Decimal | None:
    scores = getattr(record, "indicator_scores", {})
    for key, value in scores.items():
        normalized = str(key).lower().replace("_", "-")
        if contains in normalized:
            try:
                return Decimal(str(value))
            except Exception:
                return None
    return None


def _above_dma(close: Decimal | None, dma: Decimal | None) -> bool | None:
    if close is None or dma is None:
        return None
    return close >= dma


def _base_score(row: DiagnosticOutcomeRow) -> Decimal:
    adjustment = _regime_adjustment(row.recorded_regime)
    return row.strategy_score - adjustment


def _recorded_adjusted_score(row: DiagnosticOutcomeRow) -> Decimal:
    return _base_score(row) + _regime_adjustment(row.recorded_regime)


def _reconstructed_adjusted_score(row: DiagnosticOutcomeRow) -> Decimal:
    return _base_score(row) + _regime_adjustment(row.reconstructed_regime)


def _regime_adjustment(regime: str | None) -> Decimal:
    normalized = "" if regime is None else regime.upper()
    if normalized in {"BULLISH", "POSITIVE", "STRONG_POSITIVE"}:
        return Decimal("5")
    if normalized in {"BEARISH", "NEGATIVE", "STRONG_NEGATIVE", "RISK_OFF"}:
        return Decimal("-5")
    return _ZERO


def _decile_hit_rate(
    values: tuple[tuple[Decimal, DiagnosticOutcomeRow], ...], *, top: bool
) -> Decimal | None:
    completed = tuple((score, row) for score, row in values if row.positive is not None)
    if not completed:
        return None
    count = max(1, len(completed) // 10)
    sorted_values = tuple(sorted(completed, key=lambda item: item[0], reverse=top))
    sample = sorted_values[:count]
    return _rate(sum(1 for _, row in sample if row.positive is True), len(sample))


def _score_order_changes(
    values: tuple[tuple[Decimal, DiagnosticOutcomeRow], ...],
) -> int:
    recorded = tuple(
        sorted(values, key=lambda item: item[1].strategy_score, reverse=True)
    )
    adjusted = tuple(sorted(values, key=lambda item: item[0], reverse=True))
    return sum(
        1
        for left, right in zip(recorded, adjusted, strict=False)
        if left[1].candidate_id != right[1].candidate_id
    )


def _near_threshold(
    row: DiagnosticOutcomeRow,
    feature: str,
    threshold: Decimal,
    tolerance: Decimal,
) -> bool:
    value: Decimal | None
    if feature == "benchmark_return_20d":
        value = row.benchmark_return_20d
    else:
        value = (
            Decimal("0.01")
            if row.benchmark_above_50dma
            else Decimal("-0.01")
            if row.benchmark_above_50dma is False
            else None
        )
    if value is None:
        return False
    return abs(value - threshold) <= tolerance


def _would_change_simple_regime(row: DiagnosticOutcomeRow, delta: Decimal) -> bool:
    return _perturbed_regime(row, delta) != row.reconstructed_regime


def _perturbed_regime(row: DiagnosticOutcomeRow, delta: Decimal) -> str:
    if row.benchmark_return_20d is None:
        return "NEUTRAL"
    if row.benchmark_return_20d > Decimal("0.03") + delta:
        return "BULLISH"
    if row.benchmark_return_20d < Decimal("-0.03") - delta:
        return "BEARISH"
    return "NEUTRAL"


def _regime_score(regime: str) -> Decimal:
    if regime == "BULLISH":
        return Decimal("1")
    if regime == "BEARISH":
        return Decimal("-1")
    return _ZERO


def _score_return_corr(
    rows: tuple[DiagnosticOutcomeRow, ...],
    component: str,
) -> Decimal | None:
    if component == "price":
        scores = tuple(
            row.price_component_score
            for row in rows
            if row.price_component_score is not None and row.forward_return is not None
        )
        returns = tuple(
            row.forward_return
            for row in rows
            if row.price_component_score is not None and row.forward_return is not None
        )
    else:
        scores = tuple(
            row.volume_component_score
            for row in rows
            if row.volume_component_score is not None and row.forward_return is not None
        )
        returns = tuple(
            row.forward_return
            for row in rows
            if row.volume_component_score is not None and row.forward_return is not None
        )
    return _spearman(scores, returns)


def _retracement_buckets(
    rows: tuple[DiagnosticOutcomeRow, ...],
) -> tuple[tuple[str, Decimal | None], ...]:
    values = tuple(
        row.retracement_score for row in rows if row.retracement_score is not None
    )
    if not values:
        return (("LOW", None), ("MEDIUM", None), ("HIGH", None))
    ordered = sorted(values)
    low_cut = ordered[len(ordered) // 3]
    high_cut = ordered[(len(ordered) * 2) // 3]
    buckets = {
        "LOW": tuple(
            row
            for row in rows
            if row.retracement_score is not None and row.retracement_score <= low_cut
        ),
        "MEDIUM": tuple(
            row
            for row in rows
            if row.retracement_score is not None
            and low_cut < row.retracement_score <= high_cut
        ),
        "HIGH": tuple(
            row
            for row in rows
            if row.retracement_score is not None and row.retracement_score > high_cut
        ),
    }
    return tuple(
        (name, _rate(sum(1 for row in bucket if row.positive is True), len(bucket)))
        for name, bucket in buckets.items()
    )


def _retracement_finding(corr: Decimal | None, sample_count: int) -> str:
    if sample_count < 10 or corr is None:
        return "INSUFFICIENT_EVIDENCE"
    if corr < Decimal("-0.05"):
        return "RETRACEMENT_NEGATIVE_ACROSS_REGIMES"
    if corr > Decimal("0.05"):
        return "RETRACEMENT_DIRECTION_REVERSES_BY_REGIME"
    return "RETRACEMENT_EFFECT_DISAPPEARS_ON_HIGH_QUALITY_DATA"


def _top_decile(
    rows: tuple[DiagnosticOutcomeRow, ...],
) -> tuple[DiagnosticOutcomeRow, ...]:
    if not rows:
        return ()
    ordered = tuple(sorted(rows, key=lambda row: row.strategy_score, reverse=True))
    return ordered[: max(1, len(ordered) // 10)]


def _regime_share(rows: tuple[DiagnosticOutcomeRow, ...]) -> dict[str, Decimal]:
    total = Decimal(max(len(rows), 1))
    counts = Counter(row.reconstructed_regime for row in rows)
    return {key: Decimal(value) / total for key, value in counts.items()}


def _selection_finding(
    baseline: dict[str, Decimal],
    current: dict[str, Decimal],
    stage: str,
) -> str:
    if not current:
        return "INSUFFICIENT_EVIDENCE"
    max_shift = max(
        (
            abs(current.get(key, _ZERO) - baseline.get(key, _ZERO))
            for key in set(baseline) | set(current)
        ),
        default=_ZERO,
    )
    if max_shift < Decimal("0.10"):
        return "NO_MATERIAL_SELECTION_EFFECT"
    normalized = stage.upper().replace(" ", "_").replace("-", "_")
    return f"{normalized}_CONCENTRATES_REGIMES"


def _benchmark_only_regime(row: DiagnosticOutcomeRow) -> str:
    if row.benchmark_return_20d is None:
        return "NEUTRAL"
    if row.benchmark_return_20d > Decimal("0.03"):
        return "BULLISH"
    if row.benchmark_return_20d < Decimal("-0.03"):
        return "BEARISH"
    return "NEUTRAL"


def _reference_to_regime(reference: str) -> str:
    try:
        state = TransparentReferenceState(reference)
    except ValueError:
        return "NEUTRAL"
    if state in {
        TransparentReferenceState.STRONG_POSITIVE,
        TransparentReferenceState.POSITIVE,
    }:
        return "BULLISH"
    if state in {
        TransparentReferenceState.STRONG_NEGATIVE,
        TransparentReferenceState.NEGATIVE,
        TransparentReferenceState.HIGH_VOLATILITY,
        TransparentReferenceState.DISTRIBUTION,
    }:
        return "BEARISH"
    return "NEUTRAL"


def _breadth_classification(
    name: str,
    summaries: tuple[DiagnosticRegimeOutcomeSummary, ...],
    agreement: Decimal | None,
) -> str:
    if (
        name == "BENCHMARK_ONLY"
        and agreement is not None
        and agreement < Decimal("0.80")
    ):
        return "BREADTH_BIAS_MATERIALLY_AFFECTS_CONCLUSION"
    if name == "BENCHMARK_PLUS_DIAGNOSTIC_BREADTH":
        return "BREADTH_HAS_LIMITED_INCREMENTAL_VALUE"
    spread = _regime_spread(summaries)
    if spread is None:
        return "INSUFFICIENT_EVIDENCE"
    if abs(spread) >= Decimal("0.05"):
        return "BREADTH_ADDS_STABLE_DIAGNOSTIC_VALUE"
    return "BREADTH_HAS_LIMITED_INCREMENTAL_VALUE"


def _regime_spread(
    summaries: tuple[DiagnosticRegimeOutcomeSummary, ...],
) -> Decimal | None:
    values = {
        row.group.split("/")[-1]: row.average_forward_return
        for row in summaries
        if row.average_forward_return is not None and row.completed_outcomes > 0
    }
    bullish = values.get("BULLISH")
    bearish = values.get("BEARISH")
    if bullish is None or bearish is None:
        return None
    return _quantize(bullish - bearish)


def _same_sign(left: Decimal, right: Decimal) -> bool:
    if left == _ZERO or right == _ZERO:
        return True
    return (left > _ZERO) == (right > _ZERO)


def _roc_auc(scores: tuple[Decimal, ...], labels: tuple[int, ...]) -> Decimal | None:
    if len(scores) != len(labels) or not scores:
        return None
    positives = [
        score for score, label in zip(scores, labels, strict=False) if label == 1
    ]
    negatives = [
        score for score, label in zip(scores, labels, strict=False) if label == 0
    ]
    if not positives or not negatives:
        return None
    wins = Decimal("0")
    total = Decimal(len(positives) * len(negatives))
    for positive in positives:
        for negative in negatives:
            if positive > negative:
                wins += Decimal("1")
            elif positive == negative:
                wins += Decimal("0.5")
    return _quantize(wins / total)


def _spearman(
    scores: tuple[Decimal | None, ...], values: tuple[Decimal | None, ...]
) -> Decimal | None:
    pairs = tuple(
        (score, value)
        for score, value in zip(scores, values, strict=False)
        if score is not None and value is not None
    )
    if len(pairs) < 3:
        return None
    score_ranks = _ranks(tuple(score for score, _ in pairs))
    value_ranks = _ranks(tuple(value for _, value in pairs))
    mean_score = sum(score_ranks) / Decimal(len(score_ranks))
    mean_value = sum(value_ranks) / Decimal(len(value_ranks))
    numerator = sum(
        (score - mean_score) * (value - mean_value)
        for score, value in zip(score_ranks, value_ranks, strict=False)
    )
    score_denominator = Decimal(sum((score - mean_score) ** 2 for score in score_ranks))
    value_denominator = Decimal(sum((value - mean_value) ** 2 for value in value_ranks))
    if score_denominator == _ZERO or value_denominator == _ZERO:
        return None
    return _quantize(numerator / (score_denominator * value_denominator).sqrt())


def _ranks(values: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    ordered = sorted((value, index) for index, value in enumerate(values))
    ranks = [Decimal("0")] * len(values)
    for rank, (_, index) in enumerate(ordered, start=1):
        ranks[index] = Decimal(rank)
    return tuple(ranks)


def _mean(values: Any) -> Decimal | None:
    filtered = tuple(value for value in values if value is not None)
    if not filtered:
        return None
    return _quantize(sum(filtered) / Decimal(len(filtered)))


def _median(values: Any) -> Decimal | None:
    filtered = tuple(value for value in values if value is not None)
    if not filtered:
        return None
    return _quantize(Decimal(str(median(filtered))))


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return _quantize(Decimal(numerator) / Decimal(denominator))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_FOUR, rounding=ROUND_HALF_UP)


def _counts(values: Any) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(Counter(str(value) for value in values).items()))


def _summary_lines(rows: tuple[DiagnosticRegimeOutcomeSummary, ...]) -> list[str]:
    if not rows:
        return ["- unavailable"]
    return [
        (
            f"- {row.group}: n {row.candidate_count}, dates {row.date_count}, "
            f"win {_text(row.win_rate)}, clean-win {_text(row.clean_win_rate)}, "
            f"avg return {_text(row.average_forward_return)}, median "
            f"{_text(row.median_forward_return)}, benchmark-relative "
            f"{_text(row.average_benchmark_relative_return)}"
        )
        for row in rows
    ]


def _status_line(item: DiagnosticReadinessDimension | None) -> str:
    if item is None:
        return "sample adequacy: unavailable"
    return f"{item.name}: {item.status.value} - {item.explanation}"


def _enum_text(value: StrEnum | None) -> str:
    return "none" if value is None else value.value


def _text(value: object | None) -> str:
    return "unavailable" if value is None else str(value)


def _distribution_text(values: tuple[tuple[str, int], ...]) -> str:
    return ", ".join(f"{key}={value}" for key, value in values) or "unavailable"


def _prohibited_next_action() -> str:
    return (
        "Do not change market-regime thresholds, select a historically optimal "
        "threshold, alter neutral boundaries, change market-intelligence weights, "
        "modify regime intervention, scores, verdicts, candidate generation, "
        "entry timing, gates, trade plans, approvals, allocation, retracement signs, "
        "or represent diagnostic replay as exact production history."
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (date,)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    return value


__all__ = [
    "DiagnosticDatasetIntegrity",
    "DiagnosticOutcomeConclusion",
    "DiagnosticOutcomeUniverse",
    "DiagnosticRegimeOutcomeSummary",
    "DiagnosticRegimeOutcomeValidationEngine",
    "DiagnosticReadinessStatus",
    "DiagnosticThresholdReadinessReport",
    "StabilityClassification",
    "ThresholdStabilityClassification",
    "build_diagnostic_dataset_integrity",
    "diagnostic_dataset_fingerprint",
    "export_diagnostic_outcome_json",
    "export_diagnostic_rows_csv",
    "render_breadth_sensitivity",
    "render_regime_coherence",
    "render_regime_episodes",
    "render_regime_intervention",
    "render_regime_outcomes",
    "render_retracement_regime",
    "render_sector_sensitivity",
    "render_selection_effect",
    "render_setup_regime",
    "render_threshold_density",
    "render_threshold_readiness",
    "render_threshold_stability",
]
