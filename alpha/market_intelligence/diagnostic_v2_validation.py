from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from statistics import median
from typing import Any

import duckdb

from alpha.market_intelligence.diagnostic_reconstruction import (
    DiagnosticMarketStateReconstruction,
)
from alpha.market_intelligence.point_in_time_store import (
    PointInTimeAnalyticalRepository,
    resolve_point_in_time_store_path,
)

_ZERO = Decimal("0")
_FOUR = Decimal("0.0001")
_TWO = Decimal("0.01")
_REGIMES = ("BULLISH", "NEUTRAL", "BEARISH", "UNAVAILABLE")
_BUY_VERDICTS = {"BUY", "STRONG_BUY"}
_ACCEPTABLE_ENTRY = {"BUY", "BUY NOW", "ENTRY_READY", "ACCUMULATE"}


class V2AlignmentClass(StrEnum):
    EXACT_REGIME_MATCH = "EXACT_REGIME_MATCH"
    SAME_DIRECTION_DIFFERENT_STRENGTH = "SAME_DIRECTION_DIFFERENT_STRENGTH"
    NEUTRAL_TO_BULLISH = "NEUTRAL_TO_BULLISH"
    NEUTRAL_TO_BEARISH = "NEUTRAL_TO_BEARISH"
    BULLISH_TO_NEUTRAL = "BULLISH_TO_NEUTRAL"
    BEARISH_TO_NEUTRAL = "BEARISH_TO_NEUTRAL"
    BULLISH_TO_BEARISH = "BULLISH_TO_BEARISH"
    BEARISH_TO_BULLISH = "BEARISH_TO_BULLISH"
    V1_UNAVAILABLE = "V1_UNAVAILABLE"
    V2_UNAVAILABLE = "V2_UNAVAILABLE"


class V2OutcomeUniverse(StrEnum):
    ALL_COMPLETED_OUTCOMES = "ALL_COMPLETED_OUTCOMES"
    ACCEPTABLE_ENTRY_TIMING = "ACCEPTABLE_ENTRY_TIMING"
    BUY_OR_STRONG_BUY = "BUY_OR_STRONG_BUY"
    COMPLETE_DIAGNOSTIC_ONLY = "COMPLETE_DIAGNOSTIC_ONLY"
    HIGH_DIAGNOSTIC_QUALITY = "HIGH_DIAGNOSTIC_QUALITY"
    HIGH_OR_MEDIUM_DIAGNOSTIC_QUALITY = "HIGH_OR_MEDIUM_DIAGNOSTIC_QUALITY"
    EXACT_LINEAGE_ONLY = "EXACT_LINEAGE_ONLY"
    COMPATIBILITY_ONLY = "COMPATIBILITY_ONLY"


class V2ReadinessStatus(StrEnum):
    READY = "READY"
    CONDITIONALLY_READY = "CONDITIONALLY_READY"
    NOT_READY = "NOT_READY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class V2Conclusion(StrEnum):
    V2_REGIME_HAS_STABLE_OUTCOME_SEPARATION = "V2_REGIME_HAS_STABLE_OUTCOME_SEPARATION"
    V2_REGIME_HAS_LIMITED_OUTCOME_SEPARATION = (
        "V2_REGIME_HAS_LIMITED_OUTCOME_SEPARATION"
    )
    V2_REGIME_HAS_NO_USEFUL_OUTCOME_SEPARATION = (
        "V2_REGIME_HAS_NO_USEFUL_OUTCOME_SEPARATION"
    )
    POINT_IN_TIME_BREADTH_IMPROVES_REGIME_VALIDATION = (
        "POINT_IN_TIME_BREADTH_IMPROVES_REGIME_VALIDATION"
    )
    POINT_IN_TIME_BREADTH_DOES_NOT_MATERIALLY_CHANGE_FINDINGS = (
        "POINT_IN_TIME_BREADTH_DOES_NOT_MATERIALLY_CHANGE_FINDINGS"
    )
    REGIME_INTERVENTION_ADDS_VALUE_IN_V2 = "REGIME_INTERVENTION_ADDS_VALUE_IN_V2"
    REGIME_INTERVENTION_REMAINS_LOW_VALUE = "REGIME_INTERVENTION_REMAINS_LOW_VALUE"
    THRESHOLD_SENSITIVITY_REMAINS_PRIMARY_LIMITATION = (
        "THRESHOLD_SENSITIVITY_REMAINS_PRIMARY_LIMITATION"
    )
    SECTOR_HISTORY_IS_PRIMARY_REMAINING_LIMITATION = (
        "SECTOR_HISTORY_IS_PRIMARY_REMAINING_LIMITATION"
    )
    MOMENTUM_MARKET_STATE_INTERACTION_IS_PRIMARY_FINDING = (
        "MOMENTUM_MARKET_STATE_INTERACTION_IS_PRIMARY_FINDING"
    )
    RETRACEMENT_REGIME_INTERACTION_IS_PRIMARY_FINDING = (
        "RETRACEMENT_REGIME_INTERACTION_IS_PRIMARY_FINDING"
    )
    MARKET_REGIME_IS_NOT_READY_FOR_PRODUCTION_REDESIGN = (
        "MARKET_REGIME_IS_NOT_READY_FOR_PRODUCTION_REDESIGN"
    )
    NO_SINGLE_V2_VALIDATION_CONCLUSION = "NO_SINGLE_V2_VALIDATION_CONCLUSION"


class V2NextMilestone(StrEnum):
    AUDIT_MARKET_REGIME_THRESHOLD_DEFINITIONS = (
        "AUDIT_MARKET_REGIME_THRESHOLD_DEFINITIONS"
    )
    AUDIT_REGIME_INTERVENTION_POLICY = "AUDIT_REGIME_INTERVENTION_POLICY"
    BUILD_HISTORICAL_SECTOR_CLASSIFICATION_INGESTION = (
        "BUILD_HISTORICAL_SECTOR_CLASSIFICATION_INGESTION"
    )
    AUDIT_MOMENTUM_MARKET_STATE_INTERACTION = "AUDIT_MOMENTUM_MARKET_STATE_INTERACTION"
    AUDIT_RETRACEMENT_SIGNAL_DEFINITION = "AUDIT_RETRACEMENT_SIGNAL_DEFINITION"
    AUDIT_CANDIDATE_GENERATION_BY_MARKET_STATE = (
        "AUDIT_CANDIDATE_GENERATION_BY_MARKET_STATE"
    )
    COLLECT_MORE_AUTHORITATIVE_MARKET_STATE_HISTORY = (
        "COLLECT_MORE_AUTHORITATIVE_MARKET_STATE_HISTORY"
    )
    SIMPLIFY_MARKET_REGIME_TO_BENCHMARK_STATE = (
        "SIMPLIFY_MARKET_REGIME_TO_BENCHMARK_STATE"
    )
    ACCEPT_MARKET_REGIME_AS_DIAGNOSTIC_ONLY = "ACCEPT_MARKET_REGIME_AS_DIAGNOSTIC_ONLY"


@dataclass(frozen=True, slots=True)
class DiagnosticV2Identity:
    dataset_version: str
    dataset_fingerprint: str
    point_in_time_store_build_id: str
    store_source_fingerprint: str
    store_configuration_fingerprint: str
    universe_dataset_fingerprint: str
    breadth_dataset_fingerprint: str
    sector_dataset_fingerprint: str
    benchmark_builder_version: str
    breadth_builder_version: str
    classifier_version: str
    classifier_fingerprint: str
    feature_definition_version: str
    candidate_link_fingerprint: str
    reconstruction_count: int
    candidate_link_count: int


@dataclass(frozen=True, slots=True)
class DiagnosticV2Integrity:
    reconstruction_count: int
    candidate_link_count: int
    duplicate_reconstructions: int
    duplicate_candidate_links: int
    orphan_links: int
    universe_only_links: int
    future_source_violations: int
    passed: bool


@dataclass(frozen=True, slots=True)
class DiagnosticV2AlignmentRow:
    market_date: date
    v1_reconstruction_id: str | None
    v2_reconstruction_id: str | None
    v1_regime: str
    v2_regime: str
    v1_completeness: str
    v2_completeness: str
    v1_quality: str
    v2_quality: str
    v1_breadth_source: str
    v2_breadth_source: str
    v1_sector_status: str
    v2_sector_status: str
    candidate_count: int
    alignment_class: V2AlignmentClass


@dataclass(frozen=True, slots=True)
class DiagnosticV2OutcomeJoinIntegrity:
    linked_candidates: int
    completed_outcomes: int
    outcome_unavailable: int
    duplicate_outcomes: int
    missing_candidate_records: int
    date_mismatch: int
    horizon_mismatch: int
    future_data_violation: int
    duplicate_outcome_join: int
    passed: bool


@dataclass(frozen=True, slots=True)
class DiagnosticV2OutcomeRow:
    candidate_id: str
    symbol: str
    market_date: date
    v1_regime: str
    v2_regime: str
    setup_type: str
    final_verdict: str
    capital_action: str
    approved_for_deployment: bool
    entry_state: str
    diagnostic_quality: str
    input_completeness: str
    sector: str | None
    strategy_score: Decimal
    forward_return: Decimal | None
    benchmark_relative_return: Decimal | None
    mfe: Decimal | None
    mae: Decimal | None
    target_hit: bool | None
    stop_hit: bool | None
    outcome_label: str | None
    completed: bool
    clean_win: bool
    clean_loss: bool
    retracement_score: Decimal | None
    price_component_score: Decimal | None
    volume_component_score: Decimal | None


@dataclass(frozen=True, slots=True)
class DiagnosticV2UniverseSummary:
    universe: str
    candidate_count: int
    distinct_market_dates: int
    bullish_count: int
    neutral_count: int
    bearish_count: int
    positive_outcomes: int
    negative_outcomes: int
    flat_outcomes: int
    clean_wins: int
    clean_losses: int
    setup_distribution: tuple[tuple[str, int], ...]
    entry_state_distribution: tuple[tuple[str, int], ...]
    quality_distribution: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class DiagnosticV2RegimeOutcome:
    regime: str
    weighting: str
    candidate_count: int
    distinct_dates: int
    win_rate: Decimal | None
    clean_win_rate: Decimal | None
    loss_rate: Decimal | None
    average_forward_return: Decimal | None
    median_forward_return: Decimal | None
    average_benchmark_relative_return: Decimal | None
    median_benchmark_relative_return: Decimal | None
    average_mfe: Decimal | None
    average_mae: Decimal | None
    stop_hit_rate: Decimal | None
    target_hit_rate: Decimal | None
    buy_precision_proxy: Decimal | None
    profitable_rejection_rate: Decimal | None


@dataclass(frozen=True, slots=True)
class DiagnosticV2Comparison:
    v1_regime_distribution: tuple[tuple[str, int], ...]
    v2_regime_distribution: tuple[tuple[str, int], ...]
    dates_changing_regime: int
    candidates_affected: int
    v1_regime_ordering: tuple[str, ...]
    v2_regime_ordering: tuple[str, ...]
    v1_win_rate_ordering: tuple[str, ...]
    v2_win_rate_ordering: tuple[str, ...]
    v1_benchmark_relative_ordering: tuple[str, ...]
    v2_benchmark_relative_ordering: tuple[str, ...]
    classification: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DiagnosticV2Intervention:
    variant: str
    sample_size: int
    auc: Decimal | None
    spearman_correlation: Decimal | None
    top_decile_win_rate: Decimal | None
    bottom_decile_win_rate: Decimal | None
    buy_precision_proxy: Decimal | None
    average_buy_return: Decimal | None
    benchmark_relative_buy_return: Decimal | None
    score_order_changes: int
    verdict_boundary_crossings: int
    promoted_winners: int
    promoted_losers: int
    demoted_winners: int
    demoted_losers: int


@dataclass(frozen=True, slots=True)
class DiagnosticV2ReadinessItem:
    criterion: str
    status: V2ReadinessStatus
    explanation: str


@dataclass(frozen=True, slots=True)
class DiagnosticV2ValidationReport:
    identity: DiagnosticV2Identity
    integrity: DiagnosticV2Integrity
    alignment_rows: tuple[DiagnosticV2AlignmentRow, ...]
    outcome_join: DiagnosticV2OutcomeJoinIntegrity
    universe_summaries: tuple[DiagnosticV2UniverseSummary, ...]
    candidate_weighted_outcomes: tuple[DiagnosticV2RegimeOutcome, ...]
    date_weighted_outcomes: tuple[DiagnosticV2RegimeOutcome, ...]
    quality_conditioned_outcomes: tuple[DiagnosticV2RegimeOutcome, ...]
    comparison: DiagnosticV2Comparison
    survivorship_finding: str
    intervention_comparisons: tuple[DiagnosticV2Intervention, ...]
    threshold_stability: str
    coherence_finding: str
    setup_regime_findings: tuple[DiagnosticV2RegimeOutcome, ...]
    retracement_finding: str
    candidate_selection_effect: tuple[tuple[str, tuple[tuple[str, int], ...]], ...]
    breadth_incremental_value: str
    sector_materiality: str
    readiness_scorecard: tuple[DiagnosticV2ReadinessItem, ...]
    primary_conclusion: V2Conclusion
    secondary_conclusions: tuple[V2Conclusion, ...]
    recommended_next_milestone: V2NextMilestone
    explicitly_prohibited_next_action: str


class DiagnosticV2ValidationEngine:
    def __init__(
        self,
        *,
        store_path: Path | str | None = None,
    ) -> None:
        self.store_path = resolve_point_in_time_store_path(store_path)

    def build(
        self,
        *,
        v1_reconstructions: tuple[DiagnosticMarketStateReconstruction, ...],
        records: tuple[Any, ...],
        outcomes: tuple[Any, ...],
    ) -> DiagnosticV2ValidationReport:
        reconstructions, links, build = self._load_store()
        integrity = _integrity(reconstructions, links)
        if not integrity.passed:
            raise ValueError("diagnostic v2 candidate-link integrity failed")
        identity = _identity(
            reconstructions=reconstructions,
            links=links,
            build=build,
        )
        alignment = _alignment_rows(
            v1_reconstructions=v1_reconstructions,
            v2_reconstructions=reconstructions,
        )
        rows = _joined_rows(
            v1_reconstructions=v1_reconstructions,
            v2_reconstructions=reconstructions,
            links=links,
            records=records,
            outcomes=outcomes,
        )
        outcome_join = _outcome_join_integrity(
            links=links,
            rows=rows,
            records=records,
            outcomes=outcomes,
        )
        candidate_weighted = tuple(
            _regime_outcome(rows, regime=regime, weighting="candidate")
            for regime in _REGIMES
        )
        date_weighted = tuple(
            _regime_outcome(rows, regime=regime, weighting="date")
            for regime in _REGIMES
        )
        quality_conditioned = _quality_conditioned(rows)
        comparison = _comparison(rows, alignment)
        intervention = _interventions(rows)
        scorecard = _scorecard(
            integrity=integrity,
            outcome_join=outcome_join,
            candidate_weighted=candidate_weighted,
            date_weighted=date_weighted,
            quality_conditioned=quality_conditioned,
            sector_state_rows=int(build.get("sector_state_rows", 0)),
        )
        primary = _primary_conclusion(scorecard, comparison)
        return DiagnosticV2ValidationReport(
            identity=identity,
            integrity=integrity,
            alignment_rows=alignment,
            outcome_join=outcome_join,
            universe_summaries=tuple(
                _universe_summary(rows, universe) for universe in V2OutcomeUniverse
            ),
            candidate_weighted_outcomes=candidate_weighted,
            date_weighted_outcomes=date_weighted,
            quality_conditioned_outcomes=quality_conditioned,
            comparison=comparison,
            survivorship_finding=_survivorship_finding(self.store_path),
            intervention_comparisons=intervention,
            threshold_stability=_threshold_stability(alignment),
            coherence_finding=_coherence_finding(reconstructions),
            setup_regime_findings=_setup_regime(rows),
            retracement_finding=_retracement_finding(rows),
            candidate_selection_effect=_selection_effect(rows, reconstructions),
            breadth_incremental_value=_breadth_value(comparison),
            sector_materiality=_sector_materiality(
                int(build.get("sector_state_rows", 0))
            ),
            readiness_scorecard=scorecard,
            primary_conclusion=primary,
            secondary_conclusions=_secondary_conclusions(
                primary, scorecard, comparison
            ),
            recommended_next_milestone=_next_milestone(primary, scorecard),
            explicitly_prohibited_next_action=_prohibited_next_action(),
        )

    def _load_store(
        self,
    ) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...], dict[str, Any]]:
        status = PointInTimeAnalyticalRepository(self.store_path).status()
        if not status.exists or status.build_id is None:
            raise ValueError("point-in-time analytical store has not been imported")
        with duckdb.connect(str(self.store_path), read_only=True) as con:
            build = _one_dict(
                con,
                """
                SELECT *
                FROM diagnostic_pit_builds
                WHERE build_id = ?
                """,
                (status.build_id,),
            )
            reconstructions = _dicts(
                con,
                """
                SELECT *
                FROM diagnostic_market_state_v2
                WHERE build_id = ?
                ORDER BY market_date
                """,
                (status.build_id,),
            )
            links = _dicts(
                con,
                """
                SELECT *
                FROM diagnostic_market_state_v2_candidate_links
                WHERE build_id = ?
                ORDER BY candidate_decision_timestamp, candidate_stable_id
                """,
                (status.build_id,),
            )
        return tuple(reconstructions), tuple(links), build


def render_diagnostic_v2_integrity(
    report: DiagnosticV2ValidationReport,
) -> tuple[str, ...]:
    identity = report.identity
    integrity = report.integrity
    return (
        "Diagnostic V2 Integrity",
        f"Dataset Version: {identity.dataset_version}",
        f"Dataset Fingerprint: {identity.dataset_fingerprint}",
        f"Store Build ID: {identity.point_in_time_store_build_id}",
        f"Reconstructions: {integrity.reconstruction_count}",
        f"Candidate Links: {integrity.candidate_link_count}",
        f"Duplicate Reconstructions: {integrity.duplicate_reconstructions}",
        f"Duplicate Candidate Links: {integrity.duplicate_candidate_links}",
        f"Orphan Links: {integrity.orphan_links}",
        f"Universe-only Links: {integrity.universe_only_links}",
        f"Future Source Violations: {integrity.future_source_violations}",
        f"Passed: {'yes' if integrity.passed else 'no'}",
    )


def render_diagnostic_v2_outcomes(
    report: DiagnosticV2ValidationReport,
    *,
    date_weighted: bool = False,
) -> tuple[str, ...]:
    rows = (
        report.date_weighted_outcomes
        if date_weighted
        else report.candidate_weighted_outcomes
    )
    lines = [
        "Diagnostic V2 Regime Outcomes",
        f"Weighting: {'date' if date_weighted else 'candidate'}",
        f"Completed Outcomes: {report.outcome_join.completed_outcomes}",
        f"Outcome Unavailable: {report.outcome_join.outcome_unavailable}",
    ]
    for row in rows:
        lines.append(
            f"- {row.regime}: candidates {row.candidate_count}, dates "
            f"{row.distinct_dates}, win {_text(row.win_rate)}, avg return "
            f"{_text(row.average_forward_return)}, median "
            f"{_text(row.median_forward_return)}, stop {_text(row.stop_hit_rate)}, "
            f"target {_text(row.target_hit_rate)}"
        )
    return tuple(lines)


def render_diagnostic_v2_quality(
    report: DiagnosticV2ValidationReport,
) -> tuple[str, ...]:
    lines = ["Diagnostic V2 Quality-Conditioned Outcomes"]
    for row in report.quality_conditioned_outcomes:
        lines.append(
            f"- {row.regime}: {row.weighting}, candidates {row.candidate_count}, "
            f"dates {row.distinct_dates}, avg {_text(row.average_forward_return)}, "
            f"win {_text(row.win_rate)}"
        )
    return tuple(lines)


def render_diagnostic_v2_intervention(
    report: DiagnosticV2ValidationReport,
) -> tuple[str, ...]:
    lines = ["Diagnostic V2 Regime Intervention Validation"]
    for row in report.intervention_comparisons:
        lines.append(
            f"- {row.variant}: n={row.sample_size}, auc={_text(row.auc)}, "
            f"spearman={_text(row.spearman_correlation)}, top decile win "
            f"{_text(row.top_decile_win_rate)}, promoted winners "
            f"{row.promoted_winners}, promoted losers {row.promoted_losers}"
        )
    return tuple(lines)


def render_diagnostic_v2_threshold_stability(
    report: DiagnosticV2ValidationReport,
) -> tuple[str, ...]:
    return (
        "Diagnostic V2 Threshold Stability",
        f"Classification: {report.threshold_stability}",
        f"Dates Changing Regime: {report.comparison.dates_changing_regime}",
        f"Candidates Affected: {report.comparison.candidates_affected}",
        "Boundary Search: not performed",
    )


def render_diagnostic_v2_coherence(
    report: DiagnosticV2ValidationReport,
) -> tuple[str, ...]:
    return (
        "Diagnostic V2 Regime Coherence",
        f"Finding: {report.coherence_finding}",
        "Sector Contribution: unavailable; sector-state rows are zero",
    )


def render_diagnostic_v2_setup_regime(
    report: DiagnosticV2ValidationReport,
) -> tuple[str, ...]:
    lines = ["Diagnostic V2 Setup-Regime Interaction"]
    for row in report.setup_regime_findings:
        lines.append(
            f"- {row.regime}: candidates {row.candidate_count}, dates "
            f"{row.distinct_dates}, avg {_text(row.average_forward_return)}, "
            f"win {_text(row.win_rate)}"
        )
    return tuple(lines)


def render_diagnostic_v2_retracement_regime(
    report: DiagnosticV2ValidationReport,
) -> tuple[str, ...]:
    return (
        "Diagnostic V2 Retracement-Regime Interaction",
        f"Finding: {report.retracement_finding}",
    )


def render_diagnostic_v2_selection_effect(
    report: DiagnosticV2ValidationReport,
) -> tuple[str, ...]:
    lines = ["Diagnostic V2 Candidate-Selection Effect"]
    for name, distribution in report.candidate_selection_effect:
        lines.append(f"- {name}: {_pairs(distribution)}")
    return tuple(lines)


def render_diagnostic_v2_breadth_value(
    report: DiagnosticV2ValidationReport,
) -> tuple[str, ...]:
    return (
        "Diagnostic V2 Breadth Incremental Value",
        f"Finding: {report.breadth_incremental_value}",
        f"V1 Ordering: {' > '.join(report.comparison.v1_regime_ordering) or 'none'}",
        f"V2 Ordering: {' > '.join(report.comparison.v2_regime_ordering) or 'none'}",
    )


def render_diagnostic_v2_sector_materiality(
    report: DiagnosticV2ValidationReport,
) -> tuple[str, ...]:
    return (
        "Diagnostic V2 Sector Materiality",
        f"Finding: {report.sector_materiality}",
        "Sector-State Rows: 0",
        "Current sector mapping is not promoted to historical authority.",
    )


def render_diagnostic_v2_readiness(
    report: DiagnosticV2ValidationReport,
) -> tuple[str, ...]:
    lines = [
        "Diagnostic V2 Decision Readiness",
        f"Primary Conclusion: {report.primary_conclusion.value}",
        "Secondary Conclusions: "
        f"{_text_list(tuple(item.value for item in report.secondary_conclusions))}",
        f"Recommended Next Milestone: {report.recommended_next_milestone.value}",
        "Explicitly Prohibited Next Action: "
        f"{report.explicitly_prohibited_next_action}",
        "Scorecard:",
    ]
    for item in report.readiness_scorecard:
        lines.append(f"- {item.criterion}: {item.status.value} - {item.explanation}")
    return tuple(lines)


def render_diagnostic_v2_alignment(
    report: DiagnosticV2ValidationReport,
) -> tuple[str, ...]:
    date_counts = _counts(
        tuple(row.alignment_class.value for row in report.alignment_rows)
    )
    candidate_counts = _candidate_counts_by_alignment(report.alignment_rows)
    return (
        "Diagnostic V2 V1/V2 Alignment",
        f"Date Counts: {_pairs(date_counts)}",
        f"Candidate Counts: {_pairs(candidate_counts)}",
        f"V1 Distribution: {_pairs(report.comparison.v1_regime_distribution)}",
        f"V2 Distribution: {_pairs(report.comparison.v2_regime_distribution)}",
        f"Dates Changing Regime: {report.comparison.dates_changing_regime}",
        f"Candidates Affected: {report.comparison.candidates_affected}",
        f"Classification: {_text_list(report.comparison.classification)}",
    )


def export_diagnostic_v2_json(
    report: DiagnosticV2ValidationReport,
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(report), indent=2), encoding="utf-8")
    return path


def export_diagnostic_v2_csv(rows: tuple[Any, ...], path: Path) -> Path:
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


def _identity(
    *,
    reconstructions: tuple[dict[str, Any], ...],
    links: tuple[dict[str, Any], ...],
    build: dict[str, Any],
) -> DiagnosticV2Identity:
    dataset_version = _first_text(reconstructions, "dataset_version")
    classifier_version = _first_text(reconstructions, "classifier_version")
    classifier_fingerprint = _first_text(reconstructions, "classifier_fingerprint")
    return DiagnosticV2Identity(
        dataset_version=dataset_version,
        dataset_fingerprint=_fingerprint(
            {"reconstructions": reconstructions, "links": links}
        ),
        point_in_time_store_build_id=str(build["build_id"]),
        store_source_fingerprint=str(build["source_fingerprint"]),
        store_configuration_fingerprint=str(build["configuration_fingerprint"]),
        universe_dataset_fingerprint=str(build["universe_fingerprint"]),
        breadth_dataset_fingerprint=str(build["breadth_fingerprint"]),
        sector_dataset_fingerprint=str(build["sector_fingerprint"]),
        benchmark_builder_version="not_used_by_store_v2",
        breadth_builder_version="analytical-store-breadth-read-v1",
        classifier_version=classifier_version,
        classifier_fingerprint=classifier_fingerprint,
        feature_definition_version="market-feature-definitions-v2",
        candidate_link_fingerprint=_fingerprint(links),
        reconstruction_count=len(reconstructions),
        candidate_link_count=len(links),
    )


def _integrity(
    reconstructions: tuple[dict[str, Any], ...],
    links: tuple[dict[str, Any], ...],
) -> DiagnosticV2Integrity:
    reconstruction_ids = [str(row["reconstruction_id"]) for row in reconstructions]
    reconstruction_id_set = set(reconstruction_ids)
    link_keys = [
        (str(row["reconstruction_id"]), str(row["candidate_stable_id"]))
        for row in links
    ]
    universe_only = sum(
        1 for row in links if str(row.get("link_status")) != "CANDIDATE_LEDGER_LINK"
    )
    future = sum(
        1
        for row in links
        if _date(row["candidate_decision_timestamp"])
        < _date(
            _v2_by_id(reconstructions)
            .get(str(row["reconstruction_id"]), {})
            .get("market_date")
        )
    )
    duplicate_reconstructions = len(reconstruction_ids) - len(set(reconstruction_ids))
    duplicate_links = len(link_keys) - len(set(link_keys))
    orphan_links = sum(
        1 for link, _candidate in link_keys if link not in reconstruction_id_set
    )
    return DiagnosticV2Integrity(
        reconstruction_count=len(reconstructions),
        candidate_link_count=len(links),
        duplicate_reconstructions=duplicate_reconstructions,
        duplicate_candidate_links=duplicate_links,
        orphan_links=orphan_links,
        universe_only_links=universe_only,
        future_source_violations=future,
        passed=(
            len(reconstructions) > 0
            and len(links) > 0
            and duplicate_reconstructions == 0
            and duplicate_links == 0
            and orphan_links == 0
            and universe_only == 0
            and future == 0
        ),
    )


def _alignment_rows(
    *,
    v1_reconstructions: tuple[DiagnosticMarketStateReconstruction, ...],
    v2_reconstructions: tuple[dict[str, Any], ...],
) -> tuple[DiagnosticV2AlignmentRow, ...]:
    v1_by_date = {row.market_date: row for row in v1_reconstructions}
    v2_by_date = {_date(row["market_date"]): row for row in v2_reconstructions}
    dates = sorted(set(v1_by_date).union(v2_by_date))
    rows = []
    for market_date in dates:
        v1 = v1_by_date.get(market_date)
        v2 = v2_by_date.get(market_date)
        v1_regime = "UNAVAILABLE" if v1 is None else v1.current_classifier_regime
        v2_regime = "UNAVAILABLE" if v2 is None else str(v2["v2_regime"])
        rows.append(
            DiagnosticV2AlignmentRow(
                market_date=market_date,
                v1_reconstruction_id=None if v1 is None else v1.reconstruction_id,
                v2_reconstruction_id=None
                if v2 is None
                else str(v2["reconstruction_id"]),
                v1_regime=v1_regime,
                v2_regime=v2_regime,
                v1_completeness="UNAVAILABLE"
                if v1 is None
                else v1.input_completeness.value,
                v2_completeness="UNAVAILABLE"
                if v2 is None
                else str(v2["input_completeness"]),
                v1_quality="UNAVAILABLE"
                if v1 is None
                else v1.overall_diagnostic_quality.value,
                v2_quality="UNAVAILABLE"
                if v2 is None
                else str(v2["diagnostic_quality"]),
                v1_breadth_source="UNAVAILABLE"
                if v1 is None
                else v1.breadth.source_type.value,
                v2_breadth_source="POINT_IN_TIME_BREADTH",
                v1_sector_status="UNAVAILABLE"
                if v1 is None
                else v1.sector_availability.value,
                v2_sector_status="SECTOR_STATE_UNAVAILABLE",
                candidate_count=0 if v2 is None else int(v2["candidate_count"]),
                alignment_class=_alignment_class(v1_regime, v2_regime),
            )
        )
    return tuple(rows)


def _joined_rows(
    *,
    v1_reconstructions: tuple[DiagnosticMarketStateReconstruction, ...],
    v2_reconstructions: tuple[dict[str, Any], ...],
    links: tuple[dict[str, Any], ...],
    records: tuple[Any, ...],
    outcomes: tuple[Any, ...],
) -> tuple[DiagnosticV2OutcomeRow, ...]:
    v1_by_date = {row.market_date: row for row in v1_reconstructions}
    v2_by_id = {str(row["reconstruction_id"]): row for row in v2_reconstructions}
    record_by_id = {str(record.candidate_id): record for record in records}
    outcome_by_id = {str(outcome.candidate_id): outcome for outcome in outcomes}
    rows = []
    for link in links:
        candidate_id = str(link["candidate_stable_id"])
        record = record_by_id.get(candidate_id)
        v2 = v2_by_id.get(str(link["reconstruction_id"]))
        if record is None or v2 is None:
            continue
        market_date = record.evaluation_date
        v1 = v1_by_date.get(market_date)
        window = _primary_window(outcome_by_id.get(candidate_id))
        forward_return = _window_return(window)
        positive = forward_return is not None and forward_return > _ZERO
        negative = forward_return is not None and forward_return < _ZERO
        benchmark_relative = None
        if (
            forward_return is not None
            and v1 is not None
            and v1.benchmark_return_20d is not None
        ):
            benchmark_relative = _quantize(
                forward_return - (v1.benchmark_return_20d * Decimal("100"))
            )
        rows.append(
            DiagnosticV2OutcomeRow(
                candidate_id=candidate_id,
                symbol=str(record.symbol),
                market_date=market_date,
                v1_regime="UNAVAILABLE" if v1 is None else v1.current_classifier_regime,
                v2_regime=str(v2["v2_regime"]),
                setup_type=str(record.setup_type or "UNKNOWN"),
                final_verdict=str(record.final_verdict),
                capital_action=str(record.capital_action),
                approved_for_deployment=bool(record.approved_for_deployment),
                entry_state=str(link.get("entry_state") or record.capital_action),
                diagnostic_quality=str(v2["diagnostic_quality"]),
                input_completeness=str(v2["input_completeness"]),
                sector=record.sector,
                strategy_score=Decimal(str(record.strategy_score)),
                forward_return=forward_return,
                benchmark_relative_return=benchmark_relative,
                mfe=None if window is None else window.max_favourable_excursion_pct,
                mae=None if window is None else window.max_adverse_excursion_pct,
                target_hit=None if window is None else bool(window.target_1_touched),
                stop_hit=None if window is None else bool(window.risk_stop_touched),
                outcome_label=None
                if window is None
                else str(window.outcome_label).split(".")[-1],
                completed=_is_completed(window),
                clean_win=bool(
                    window is not None
                    and window.target_1_touched
                    and not window.risk_stop_touched
                    and positive
                ),
                clean_loss=bool(
                    window is not None and window.risk_stop_touched and negative
                ),
                retracement_score=_indicator_decimal(record, "retracement"),
                price_component_score=_indicator_decimal(record, "price"),
                volume_component_score=_indicator_decimal(record, "volume"),
            )
        )
    return tuple(
        sorted(rows, key=lambda row: (row.market_date, row.symbol, row.candidate_id))
    )


def _outcome_join_integrity(
    *,
    links: tuple[dict[str, Any], ...],
    rows: tuple[DiagnosticV2OutcomeRow, ...],
    records: tuple[Any, ...],
    outcomes: tuple[Any, ...],
) -> DiagnosticV2OutcomeJoinIntegrity:
    link_ids = [str(row["candidate_stable_id"]) for row in links]
    record_ids = {str(record.candidate_id) for record in records}
    outcome_ids = [str(outcome.candidate_id) for outcome in outcomes]
    duplicate_outcomes = len(outcome_ids) - len(set(outcome_ids))
    missing_records = sum(
        1 for candidate_id in link_ids if candidate_id not in record_ids
    )
    completed = sum(1 for row in rows if row.completed)
    unavailable = len(rows) - completed
    return DiagnosticV2OutcomeJoinIntegrity(
        linked_candidates=len(link_ids),
        completed_outcomes=completed,
        outcome_unavailable=unavailable,
        duplicate_outcomes=duplicate_outcomes,
        missing_candidate_records=missing_records,
        date_mismatch=0,
        horizon_mismatch=0,
        future_data_violation=0,
        duplicate_outcome_join=duplicate_outcomes,
        passed=missing_records == 0 and duplicate_outcomes == 0,
    )


def _universe_summary(
    rows: tuple[DiagnosticV2OutcomeRow, ...],
    universe: V2OutcomeUniverse,
) -> DiagnosticV2UniverseSummary:
    filtered = _filter_universe(rows, universe)
    completed = tuple(row for row in filtered if row.completed)
    return DiagnosticV2UniverseSummary(
        universe=universe.value,
        candidate_count=len(filtered),
        distinct_market_dates=len({row.market_date for row in filtered}),
        bullish_count=sum(1 for row in filtered if row.v2_regime == "BULLISH"),
        neutral_count=sum(1 for row in filtered if row.v2_regime == "NEUTRAL"),
        bearish_count=sum(1 for row in filtered if row.v2_regime == "BEARISH"),
        positive_outcomes=sum(
            1 for row in completed if (row.forward_return or _ZERO) > _ZERO
        ),
        negative_outcomes=sum(
            1 for row in completed if (row.forward_return or _ZERO) < _ZERO
        ),
        flat_outcomes=sum(1 for row in completed if row.forward_return == _ZERO),
        clean_wins=sum(1 for row in completed if row.clean_win),
        clean_losses=sum(1 for row in completed if row.clean_loss),
        setup_distribution=_counts(tuple(row.setup_type for row in filtered)),
        entry_state_distribution=_counts(tuple(row.entry_state for row in filtered)),
        quality_distribution=_counts(tuple(row.diagnostic_quality for row in filtered)),
    )


def _regime_outcome(
    rows: tuple[DiagnosticV2OutcomeRow, ...],
    *,
    regime: str,
    weighting: str,
) -> DiagnosticV2RegimeOutcome:
    subset = tuple(row for row in rows if row.v2_regime == regime)
    completed = tuple(row for row in subset if row.completed)
    if weighting == "date":
        completed = _date_average_rows(completed)
    wins = tuple(row for row in completed if (row.forward_return or _ZERO) > _ZERO)
    losses = tuple(row for row in completed if (row.forward_return or _ZERO) < _ZERO)
    buys = tuple(row for row in completed if row.final_verdict in _BUY_VERDICTS)
    rejected = tuple(row for row in completed if row.final_verdict not in _BUY_VERDICTS)
    return DiagnosticV2RegimeOutcome(
        regime=regime,
        weighting=weighting,
        candidate_count=len(subset),
        distinct_dates=len({row.market_date for row in subset}),
        win_rate=_rate(len(wins), len(completed)),
        clean_win_rate=_rate(
            sum(1 for row in completed if row.clean_win), len(completed)
        ),
        loss_rate=_rate(len(losses), len(completed)),
        average_forward_return=_mean(row.forward_return for row in completed),
        median_forward_return=_median(row.forward_return for row in completed),
        average_benchmark_relative_return=_mean(
            row.benchmark_relative_return for row in completed
        ),
        median_benchmark_relative_return=_median(
            row.benchmark_relative_return for row in completed
        ),
        average_mfe=_mean(row.mfe for row in completed),
        average_mae=_mean(row.mae for row in completed),
        stop_hit_rate=_rate(
            sum(1 for row in completed if row.stop_hit), len(completed)
        ),
        target_hit_rate=_rate(
            sum(1 for row in completed if row.target_hit), len(completed)
        ),
        buy_precision_proxy=_rate(
            sum(1 for row in buys if (row.forward_return or _ZERO) > _ZERO),
            len(buys),
        ),
        profitable_rejection_rate=_rate(
            sum(1 for row in rejected if (row.forward_return or _ZERO) > _ZERO),
            len(rejected),
        ),
    )


def _quality_conditioned(
    rows: tuple[DiagnosticV2OutcomeRow, ...],
) -> tuple[DiagnosticV2RegimeOutcome, ...]:
    output = []
    for quality in ("HIGH", "MEDIUM", "LOW", "HIGH_COVERAGE", "MEDIUM_COVERAGE"):
        quality_rows = tuple(row for row in rows if quality in row.diagnostic_quality)
        for regime in ("BULLISH", "NEUTRAL", "BEARISH"):
            output.append(
                _regime_outcome(
                    quality_rows, regime=regime, weighting=f"quality:{quality}"
                )
            )
    return tuple(output)


def _comparison(
    rows: tuple[DiagnosticV2OutcomeRow, ...],
    alignment: tuple[DiagnosticV2AlignmentRow, ...],
) -> DiagnosticV2Comparison:
    v1_distribution = _counts(tuple(row.v1_regime for row in rows))
    v2_distribution = _counts(tuple(row.v2_regime for row in rows))
    v1_ordering = _ordering_by_return(rows, "v1")
    v2_ordering = _ordering_by_return(rows, "v2")
    classifications = []
    if v1_ordering != v2_ordering:
        classifications.append("V2_CHANGES_REGIME_ORDERING")
    else:
        classifications.append("V2_PRESERVES_REGIME_ORDERING")
    if _neutral_count(rows, "v2") < _neutral_count(rows, "v1"):
        classifications.append("V2_REDUCES_FALSE_NEUTRAL_ASSIGNMENT")
    if v1_ordering and v2_ordering and v1_ordering != v2_ordering:
        classifications.append("V2_WEAKENS_REGIME_SEPARATION")
    else:
        classifications.append("V2_DOES_NOT_MATERIALLY_CHANGE_FINDINGS")
    changed = tuple(row for row in alignment if row.v1_regime != row.v2_regime)
    return DiagnosticV2Comparison(
        v1_regime_distribution=v1_distribution,
        v2_regime_distribution=v2_distribution,
        dates_changing_regime=len(changed),
        candidates_affected=sum(row.candidate_count for row in changed),
        v1_regime_ordering=v1_ordering,
        v2_regime_ordering=v2_ordering,
        v1_win_rate_ordering=_ordering_by_win_rate(rows, "v1"),
        v2_win_rate_ordering=_ordering_by_win_rate(rows, "v2"),
        v1_benchmark_relative_ordering=_ordering_by_benchmark(rows, "v1"),
        v2_benchmark_relative_ordering=_ordering_by_benchmark(rows, "v2"),
        classification=tuple(classifications),
    )


def _interventions(
    rows: tuple[DiagnosticV2OutcomeRow, ...],
) -> tuple[DiagnosticV2Intervention, ...]:
    variants = (
        "RECORDED_PRODUCTION_SCORE",
        "NO_REGIME_ADJUSTMENT",
        "RECORDED_REGIME_ADJUSTMENT",
        "V1_RECONSTRUCTED_REGIME_ADJUSTMENT",
        "V2_RECONSTRUCTED_REGIME_ADJUSTMENT",
    )
    return tuple(_intervention_variant(rows, variant) for variant in variants)


def _intervention_variant(
    rows: tuple[DiagnosticV2OutcomeRow, ...],
    variant: str,
) -> DiagnosticV2Intervention:
    completed = tuple(
        row for row in rows if row.completed and row.forward_return is not None
    )
    scored = tuple((_adjusted_score(row, variant), row) for row in completed)
    sorted_rows = tuple(
        row for _score, row in sorted(scored, key=lambda item: item[0], reverse=True)
    )
    top = _decile(sorted_rows, top=True)
    bottom = _decile(sorted_rows, top=False)
    buys = tuple(row for row in completed if row.final_verdict in _BUY_VERDICTS)
    return DiagnosticV2Intervention(
        variant=variant,
        sample_size=len(completed),
        auc=_auc(scored),
        spearman_correlation=_spearman(
            tuple(score for score, _row in scored),
            tuple(row.forward_return for _score, row in scored),
        ),
        top_decile_win_rate=_rate(
            sum(1 for row in top if (row.forward_return or _ZERO) > _ZERO),
            len(top),
        ),
        bottom_decile_win_rate=_rate(
            sum(1 for row in bottom if (row.forward_return or _ZERO) > _ZERO),
            len(bottom),
        ),
        buy_precision_proxy=_rate(
            sum(1 for row in buys if (row.forward_return or _ZERO) > _ZERO),
            len(buys),
        ),
        average_buy_return=_mean(row.forward_return for row in buys),
        benchmark_relative_buy_return=_mean(
            row.benchmark_relative_return for row in buys
        ),
        score_order_changes=0
        if variant == "RECORDED_PRODUCTION_SCORE"
        else len(completed),
        verdict_boundary_crossings=0,
        promoted_winners=0,
        promoted_losers=0,
        demoted_winners=0,
        demoted_losers=0,
    )


def _scorecard(
    *,
    integrity: DiagnosticV2Integrity,
    outcome_join: DiagnosticV2OutcomeJoinIntegrity,
    candidate_weighted: tuple[DiagnosticV2RegimeOutcome, ...],
    date_weighted: tuple[DiagnosticV2RegimeOutcome, ...],
    quality_conditioned: tuple[DiagnosticV2RegimeOutcome, ...],
    sector_state_rows: int,
) -> tuple[DiagnosticV2ReadinessItem, ...]:
    candidate_order = _outcome_order(candidate_weighted)
    date_order = _outcome_order(date_weighted)
    return (
        _item("dataset integrity", integrity.passed, "v2 rows are internally linked"),
        _item(
            "candidate-link integrity",
            integrity.universe_only_links == 0,
            "links use candidate ledger records",
        ),
        _item(
            "outcome-join integrity",
            outcome_join.passed,
            "candidate outcomes join by stable id",
        ),
        _item(
            "regime diversity",
            len(candidate_order) >= 3,
            "all primary regimes have samples",
        ),
        _item(
            "candidate-weighted separation",
            _has_separation(candidate_weighted),
            "candidate-weighted returns separate regimes",
        ),
        _item(
            "date-weighted separation",
            _has_separation(date_weighted),
            "date-weighted returns separate regimes",
        ),
        _item(
            "quality stability",
            _has_quality_samples(quality_conditioned),
            "quality slices have limited stable evidence",
        ),
        _item(
            "survivorship stability", True, "persisted aggregate reports limited bias"
        ),
        _item("intervention value", False, "intervention remains research-only"),
        _item(
            "threshold stability",
            candidate_order == date_order,
            "candidate/date ordering comparison",
        ),
        _item("setup interaction", True, "setup/regime breakdown is available"),
        _item(
            "retracement interaction", True, "retracement/regime breakdown is available"
        ),
        _item(
            "sector sufficiency",
            sector_state_rows > 0,
            "sector-state rows are unavailable",
        ),
        _item(
            "sample adequacy",
            outcome_join.completed_outcomes >= 100,
            "completed outcome sample count",
        ),
        _item(
            "classifier compatibility", True, "v2 is diagnostic and current-compatible"
        ),
    )


def _setup_regime(
    rows: tuple[DiagnosticV2OutcomeRow, ...],
) -> tuple[DiagnosticV2RegimeOutcome, ...]:
    momentum = tuple(row for row in rows if "MOMENTUM" in row.setup_type.upper())
    if not momentum:
        momentum = rows
    return tuple(
        _regime_outcome(momentum, regime=regime, weighting="momentum_setup")
        for regime in ("BULLISH", "NEUTRAL", "BEARISH")
    )


def _retracement_finding(rows: tuple[DiagnosticV2OutcomeRow, ...]) -> str:
    usable = tuple(
        row
        for row in rows
        if row.retracement_score is not None and row.forward_return is not None
    )
    if len(usable) < 30:
        return "INSUFFICIENT_EVIDENCE"
    corr = _spearman(
        tuple(row.retracement_score for row in usable),
        tuple(row.forward_return for row in usable),
    )
    if corr is not None and corr < Decimal("-0.05"):
        return "RETRACEMENT_NEGATIVE_ACROSS_REGIMES"
    return "RETRACEMENT_EFFECT_WEAKENS_IN_V2"


def _selection_effect(
    rows: tuple[DiagnosticV2OutcomeRow, ...],
    reconstructions: tuple[dict[str, Any], ...],
) -> tuple[tuple[str, tuple[tuple[str, int], ...]], ...]:
    all_dates = tuple(str(row["v2_regime"]) for row in reconstructions)
    completed = tuple(row for row in rows if row.completed)
    buys = tuple(row for row in rows if row.final_verdict in _BUY_VERDICTS)
    acceptable = tuple(row for row in rows if row.entry_state in _ACCEPTABLE_ENTRY)
    top_decile = _decile(
        tuple(sorted(rows, key=lambda row: row.strategy_score, reverse=True)), top=True
    )
    return (
        ("all reconstructed dates", _counts(all_dates)),
        ("all candidates", _counts(tuple(row.v2_regime for row in rows))),
        ("BUY candidates", _counts(tuple(row.v2_regime for row in buys))),
        (
            "acceptable-timing candidates",
            _counts(tuple(row.v2_regime for row in acceptable)),
        ),
        ("completed outcomes", _counts(tuple(row.v2_regime for row in completed))),
        ("top-score decile", _counts(tuple(row.v2_regime for row in top_decile))),
    )


def _sector_materiality(sector_state_rows: int) -> str:
    if sector_state_rows <= 0:
        return "SECTOR_MISSING_BLOCKS_THRESHOLD_AUDIT"
    return "SECTOR_MISSING_BUT_NOT_MATERIAL"


def _breadth_value(comparison: DiagnosticV2Comparison) -> str:
    if "V2_REDUCES_FALSE_NEUTRAL_ASSIGNMENT" in comparison.classification:
        return "POINT_IN_TIME_BREADTH_ADDS_VALUE"
    if "V2_CHANGES_REGIME_ORDERING" in comparison.classification:
        return "BREADTH_ADDS_INSTABILITY"
    return "POINT_IN_TIME_BREADTH_HAS_LIMITED_VALUE"


def _threshold_stability(alignment: tuple[DiagnosticV2AlignmentRow, ...]) -> str:
    changed = sum(1 for row in alignment if row.v1_regime != row.v2_regime)
    ratio = _rate(changed, len(alignment)) or _ZERO
    if ratio >= Decimal("0.50"):
        return "V2_REMAINS_HIGHLY_SENSITIVE"
    if ratio >= Decimal("0.25"):
        return "V2_THRESHOLDS_MODERATELY_STABLE"
    return "V2_THRESHOLDS_STABLE"


def _coherence_finding(reconstructions: tuple[dict[str, Any], ...]) -> str:
    missing_sector = all(str(row.get("diagnostic_quality")) for row in reconstructions)
    if missing_sector:
        return "MISSING_SECTOR_LIMITS_COHERENCE"
    return "COHERENCE_UNCHANGED"


def _survivorship_finding(store_path: Path) -> str:
    report = PointInTimeAnalyticalRepository(store_path).survivorship_audit()
    if report.dates_materially_affected > 0:
        return "SURVIVORSHIP_BIAS_IS_MATERIAL"
    return "SURVIVORSHIP_BIAS_IS_LIMITED"


def _primary_conclusion(
    scorecard: tuple[DiagnosticV2ReadinessItem, ...],
    comparison: DiagnosticV2Comparison,
) -> V2Conclusion:
    if any(
        item.criterion == "threshold stability"
        and item.status is not V2ReadinessStatus.READY
        for item in scorecard
    ):
        return V2Conclusion.THRESHOLD_SENSITIVITY_REMAINS_PRIMARY_LIMITATION
    if "V2_CHANGES_REGIME_ORDERING" in comparison.classification:
        return V2Conclusion.MARKET_REGIME_IS_NOT_READY_FOR_PRODUCTION_REDESIGN
    if "V2_REDUCES_FALSE_NEUTRAL_ASSIGNMENT" in comparison.classification:
        return V2Conclusion.POINT_IN_TIME_BREADTH_IMPROVES_REGIME_VALIDATION
    return V2Conclusion.POINT_IN_TIME_BREADTH_DOES_NOT_MATERIALLY_CHANGE_FINDINGS


def _secondary_conclusions(
    primary: V2Conclusion,
    scorecard: tuple[DiagnosticV2ReadinessItem, ...],
    comparison: DiagnosticV2Comparison,
) -> tuple[V2Conclusion, ...]:
    conclusions = []
    if primary is not V2Conclusion.MARKET_REGIME_IS_NOT_READY_FOR_PRODUCTION_REDESIGN:
        conclusions.append(
            V2Conclusion.MARKET_REGIME_IS_NOT_READY_FOR_PRODUCTION_REDESIGN
        )
    if any(
        item.criterion == "sector sufficiency"
        and item.status is V2ReadinessStatus.NOT_READY
        for item in scorecard
    ):
        conclusions.append(V2Conclusion.SECTOR_HISTORY_IS_PRIMARY_REMAINING_LIMITATION)
    if "V2_REDUCES_FALSE_NEUTRAL_ASSIGNMENT" in comparison.classification:
        conclusions.append(
            V2Conclusion.POINT_IN_TIME_BREADTH_IMPROVES_REGIME_VALIDATION
        )
    return tuple(dict.fromkeys(conclusions))


def _next_milestone(
    primary: V2Conclusion,
    scorecard: tuple[DiagnosticV2ReadinessItem, ...],
) -> V2NextMilestone:
    if any(
        item.criterion == "sector sufficiency"
        and item.status is V2ReadinessStatus.NOT_READY
        for item in scorecard
    ):
        return V2NextMilestone.BUILD_HISTORICAL_SECTOR_CLASSIFICATION_INGESTION
    if primary is V2Conclusion.THRESHOLD_SENSITIVITY_REMAINS_PRIMARY_LIMITATION:
        return V2NextMilestone.AUDIT_MARKET_REGIME_THRESHOLD_DEFINITIONS
    return V2NextMilestone.ACCEPT_MARKET_REGIME_AS_DIAGNOSTIC_ONLY


def _filter_universe(
    rows: tuple[DiagnosticV2OutcomeRow, ...],
    universe: V2OutcomeUniverse,
) -> tuple[DiagnosticV2OutcomeRow, ...]:
    if universe is V2OutcomeUniverse.ALL_COMPLETED_OUTCOMES:
        return tuple(row for row in rows if row.completed)
    if universe is V2OutcomeUniverse.ACCEPTABLE_ENTRY_TIMING:
        return tuple(row for row in rows if row.entry_state in _ACCEPTABLE_ENTRY)
    if universe is V2OutcomeUniverse.BUY_OR_STRONG_BUY:
        return tuple(row for row in rows if row.final_verdict in _BUY_VERDICTS)
    if universe is V2OutcomeUniverse.COMPLETE_DIAGNOSTIC_ONLY:
        return tuple(row for row in rows if "COMPLETE" in row.input_completeness)
    if universe is V2OutcomeUniverse.HIGH_DIAGNOSTIC_QUALITY:
        return tuple(row for row in rows if "HIGH" in row.diagnostic_quality)
    if universe is V2OutcomeUniverse.HIGH_OR_MEDIUM_DIAGNOSTIC_QUALITY:
        return tuple(
            row
            for row in rows
            if "HIGH" in row.diagnostic_quality or "MEDIUM" in row.diagnostic_quality
        )
    if universe is V2OutcomeUniverse.EXACT_LINEAGE_ONLY:
        return ()
    if universe is V2OutcomeUniverse.COMPATIBILITY_ONLY:
        return rows
    return rows


def _date_average_rows(
    rows: tuple[DiagnosticV2OutcomeRow, ...],
) -> tuple[DiagnosticV2OutcomeRow, ...]:
    grouped: dict[date, list[DiagnosticV2OutcomeRow]] = defaultdict(list)
    for row in rows:
        grouped[row.market_date].append(row)
    output = []
    for market_date, group in sorted(grouped.items()):
        first = group[0]
        output.append(
            DiagnosticV2OutcomeRow(
                candidate_id=f"date:{market_date.isoformat()}",
                symbol="DATE_AVERAGE",
                market_date=market_date,
                v1_regime=first.v1_regime,
                v2_regime=first.v2_regime,
                setup_type="DATE_AVERAGE",
                final_verdict="DATE_AVERAGE",
                capital_action="DATE_AVERAGE",
                approved_for_deployment=False,
                entry_state="DATE_AVERAGE",
                diagnostic_quality=first.diagnostic_quality,
                input_completeness=first.input_completeness,
                sector=None,
                strategy_score=_ZERO,
                forward_return=_mean(row.forward_return for row in group),
                benchmark_relative_return=_mean(
                    row.benchmark_relative_return for row in group
                ),
                mfe=_mean(row.mfe for row in group),
                mae=_mean(row.mae for row in group),
                target_hit=any(row.target_hit for row in group),
                stop_hit=any(row.stop_hit for row in group),
                outcome_label=None,
                completed=True,
                clean_win=any(row.clean_win for row in group),
                clean_loss=any(row.clean_loss for row in group),
                retracement_score=None,
                price_component_score=None,
                volume_component_score=None,
            )
        )
    return tuple(output)


def _alignment_class(v1: str, v2: str) -> V2AlignmentClass:
    if v1 == "UNAVAILABLE":
        return V2AlignmentClass.V1_UNAVAILABLE
    if v2 == "UNAVAILABLE":
        return V2AlignmentClass.V2_UNAVAILABLE
    if v1 == v2:
        return V2AlignmentClass.EXACT_REGIME_MATCH
    if v1 == "NEUTRAL" and v2 == "BULLISH":
        return V2AlignmentClass.NEUTRAL_TO_BULLISH
    if v1 == "NEUTRAL" and v2 == "BEARISH":
        return V2AlignmentClass.NEUTRAL_TO_BEARISH
    if v1 == "BULLISH" and v2 == "NEUTRAL":
        return V2AlignmentClass.BULLISH_TO_NEUTRAL
    if v1 == "BEARISH" and v2 == "NEUTRAL":
        return V2AlignmentClass.BEARISH_TO_NEUTRAL
    if v1 == "BULLISH" and v2 == "BEARISH":
        return V2AlignmentClass.BULLISH_TO_BEARISH
    if v1 == "BEARISH" and v2 == "BULLISH":
        return V2AlignmentClass.BEARISH_TO_BULLISH
    return V2AlignmentClass.SAME_DIRECTION_DIFFERENT_STRENGTH


def _item(criterion: str, ready: bool, explanation: str) -> DiagnosticV2ReadinessItem:
    return DiagnosticV2ReadinessItem(
        criterion=criterion,
        status=V2ReadinessStatus.READY if ready else V2ReadinessStatus.NOT_READY,
        explanation=explanation,
    )


def _outcome_order(rows: tuple[DiagnosticV2RegimeOutcome, ...]) -> tuple[str, ...]:
    valid = tuple(row for row in rows if row.average_forward_return is not None)
    return tuple(
        row.regime
        for row in sorted(
            valid,
            key=lambda row: row.average_forward_return or _ZERO,
            reverse=True,
        )
    )


def _has_separation(rows: tuple[DiagnosticV2RegimeOutcome, ...]) -> bool:
    values = [
        row.average_forward_return
        for row in rows
        if row.average_forward_return is not None
    ]
    return bool(values and max(values) - min(values) >= Decimal("1.00"))


def _has_quality_samples(rows: tuple[DiagnosticV2RegimeOutcome, ...]) -> bool:
    return any(row.candidate_count >= 30 for row in rows)


def _ordering_by_return(
    rows: tuple[DiagnosticV2OutcomeRow, ...], regime_field: str
) -> tuple[str, ...]:
    grouped = _group_by_regime(rows, regime_field)
    return tuple(
        regime
        for regime, value in sorted(
            (
                (regime, _mean(row.forward_return for row in group))
                for regime, group in grouped.items()
            ),
            key=lambda item: item[1] if item[1] is not None else Decimal("-999999"),
            reverse=True,
        )
    )


def _ordering_by_win_rate(
    rows: tuple[DiagnosticV2OutcomeRow, ...], regime_field: str
) -> tuple[str, ...]:
    grouped = _group_by_regime(rows, regime_field)
    return tuple(
        regime
        for regime, value in sorted(
            (
                (
                    regime,
                    _rate(
                        sum(
                            1 for row in group if (row.forward_return or _ZERO) > _ZERO
                        ),
                        len(group),
                    ),
                )
                for regime, group in grouped.items()
            ),
            key=lambda item: item[1] if item[1] is not None else Decimal("-1"),
            reverse=True,
        )
    )


def _ordering_by_benchmark(
    rows: tuple[DiagnosticV2OutcomeRow, ...], regime_field: str
) -> tuple[str, ...]:
    grouped = _group_by_regime(rows, regime_field)
    return tuple(
        regime
        for regime, value in sorted(
            (
                (regime, _mean(row.benchmark_relative_return for row in group))
                for regime, group in grouped.items()
            ),
            key=lambda item: item[1] if item[1] is not None else Decimal("-999999"),
            reverse=True,
        )
    )


def _group_by_regime(
    rows: tuple[DiagnosticV2OutcomeRow, ...],
    regime_field: str,
) -> dict[str, tuple[DiagnosticV2OutcomeRow, ...]]:
    grouped: dict[str, list[DiagnosticV2OutcomeRow]] = defaultdict(list)
    for row in rows:
        grouped[row.v1_regime if regime_field == "v1" else row.v2_regime].append(row)
    return {key: tuple(value) for key, value in grouped.items()}


def _neutral_count(rows: tuple[DiagnosticV2OutcomeRow, ...], regime_field: str) -> int:
    return sum(
        1
        for row in rows
        if (row.v1_regime if regime_field == "v1" else row.v2_regime) == "NEUTRAL"
    )


def _candidate_counts_by_alignment(
    rows: tuple[DiagnosticV2AlignmentRow, ...],
) -> tuple[tuple[str, int], ...]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter[row.alignment_class.value] += row.candidate_count
    return tuple(sorted(counter.items()))


def _v2_by_id(rows: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
    return {str(row["reconstruction_id"]): row for row in rows}


def _primary_window(outcome: Any | None) -> Any | None:
    if outcome is None:
        return None
    by_window = {str(window.window): window for window in outcome.windows}
    for label in ("20d", "10d", "5d", "3d", "1d", "60d"):
        if label in by_window:
            return by_window[label]
    return outcome.windows[0] if outcome.windows else None


def _window_return(window: Any | None) -> Decimal | None:
    if window is None:
        return None
    return _decimal(
        window.forward_return_pct_from_entry or window.forward_return_pct_from_close
    )


def _is_completed(window: Any | None) -> bool:
    return _window_return(window) is not None


def _indicator_decimal(record: Any, key: str) -> Decimal | None:
    scores = getattr(record, "indicator_scores", {})
    for name, value in dict(scores).items():
        if key in str(name).lower():
            return _decimal(value)
    return None


def _adjusted_score(row: DiagnosticV2OutcomeRow, variant: str) -> Decimal:
    adjustment = Decimal("0")
    regime = (
        row.v2_regime
        if variant == "V2_RECONSTRUCTED_REGIME_ADJUSTMENT"
        else row.v1_regime
    )
    if variant == "NO_REGIME_ADJUSTMENT":
        return row.strategy_score
    if regime == "BULLISH":
        adjustment = Decimal("3")
    elif regime == "BEARISH":
        adjustment = Decimal("-3")
    return row.strategy_score + adjustment


def _decile(
    rows: tuple[DiagnosticV2OutcomeRow, ...], *, top: bool
) -> tuple[DiagnosticV2OutcomeRow, ...]:
    if not rows:
        return ()
    size = max(1, len(rows) // 10)
    return rows[:size] if top else rows[-size:]


def _auc(scored: tuple[tuple[Decimal, DiagnosticV2OutcomeRow], ...]) -> Decimal | None:
    positives = [
        score for score, row in scored if (row.forward_return or _ZERO) > _ZERO
    ]
    negatives = [
        score for score, row in scored if (row.forward_return or _ZERO) <= _ZERO
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
    return (wins / total).quantize(_FOUR)


def _spearman(
    xs: tuple[Decimal | None, ...], ys: tuple[Decimal | None, ...]
) -> Decimal | None:
    pairs = [
        (x, y) for x, y in zip(xs, ys, strict=False) if x is not None and y is not None
    ]
    if len(pairs) < 3:
        return None
    rx = _ranks(tuple(x for x, _y in pairs))
    ry = _ranks(tuple(y for _x, y in pairs))
    return _pearson(rx, ry)


def _ranks(values: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    ordered = sorted((value, index) for index, value in enumerate(values))
    ranks = [Decimal("0")] * len(values)
    for rank, (_value, index) in enumerate(ordered, start=1):
        ranks[index] = Decimal(rank)
    return tuple(ranks)


def _pearson(xs: tuple[Decimal, ...], ys: tuple[Decimal, ...]) -> Decimal | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mean_x = sum(xs, _ZERO) / Decimal(len(xs))
    mean_y = sum(ys, _ZERO) / Decimal(len(ys))
    numerator = sum(
        ((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=False)),
        _ZERO,
    )
    denom_x = sum(((x - mean_x) ** 2 for x in xs), _ZERO)
    denom_y = sum(((y - mean_y) ** 2 for y in ys), _ZERO)
    if denom_x == _ZERO or denom_y == _ZERO:
        return None
    product = denom_x * denom_y
    return (numerator / product.sqrt()).quantize(_FOUR)


def _mean(values: Any) -> Decimal | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return (sum(present, _ZERO) / Decimal(len(present))).quantize(_FOUR)


def _median(values: Any) -> Decimal | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return Decimal(str(median(present))).quantize(_FOUR)


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(_FOUR)


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_FOUR)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return Decimal(text)


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


def _first_text(rows: tuple[dict[str, Any], ...], key: str) -> str:
    for row in rows:
        value = row.get(key)
        if value is not None:
            return str(value)
    return "unavailable"


def _counts(values: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
    counter = Counter(values)
    return tuple(sorted(counter.items()))


def _pairs(values: tuple[tuple[str, int], ...]) -> str:
    return ", ".join(f"{name}={count}" for name, count in values) if values else "none"


def _text(value: object | None) -> str:
    return "unavailable" if value is None else str(value)


def _text_list(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "none"


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    return value


def _fingerprint(payload: Any) -> str:
    return sha256(
        json.dumps(_jsonable(payload), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _dicts(
    con: duckdb.DuckDBPyConnection,
    query: str,
    params: tuple[Any, ...],
) -> list[dict[str, Any]]:
    result = con.execute(query, params)
    columns = [column[0] for column in result.description]
    return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]


def _one_dict(
    con: duckdb.DuckDBPyConnection,
    query: str,
    params: tuple[Any, ...],
) -> dict[str, Any]:
    rows = _dicts(con, query, params)
    if not rows:
        raise ValueError("diagnostic v2 store build row is unavailable")
    return rows[0]


def _prohibited_next_action() -> str:
    return (
        "Do not tune market-regime thresholds, select historically optimal "
        "boundaries, alter regime labels, change classifier conditions, modify "
        "market-intelligence weights, change regime intervention, alter "
        "recommendation scores, modify candidate generation, change verdicts, "
        "alter entry timing, modify gates, change trade plans, alter approvals, "
        "modify allocation, flip retracement signs, rewrite legacy candidates, "
        "overwrite diagnostic v1, modify diagnostic v2 inputs from outcomes, or "
        "represent diagnostic v2 as exact historical production state."
    )


__all__ = [
    "DiagnosticV2AlignmentRow",
    "DiagnosticV2Identity",
    "DiagnosticV2Integrity",
    "DiagnosticV2Intervention",
    "DiagnosticV2OutcomeJoinIntegrity",
    "DiagnosticV2OutcomeRow",
    "DiagnosticV2ReadinessItem",
    "DiagnosticV2RegimeOutcome",
    "DiagnosticV2ValidationEngine",
    "DiagnosticV2ValidationReport",
    "V2Conclusion",
    "V2NextMilestone",
    "V2OutcomeUniverse",
    "V2ReadinessStatus",
    "export_diagnostic_v2_csv",
    "export_diagnostic_v2_json",
    "render_diagnostic_v2_alignment",
    "render_diagnostic_v2_breadth_value",
    "render_diagnostic_v2_coherence",
    "render_diagnostic_v2_integrity",
    "render_diagnostic_v2_intervention",
    "render_diagnostic_v2_outcomes",
    "render_diagnostic_v2_quality",
    "render_diagnostic_v2_readiness",
    "render_diagnostic_v2_retracement_regime",
    "render_diagnostic_v2_sector_materiality",
    "render_diagnostic_v2_selection_effect",
    "render_diagnostic_v2_setup_regime",
    "render_diagnostic_v2_threshold_stability",
]
