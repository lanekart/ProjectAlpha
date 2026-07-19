from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

import duckdb

from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
)
from alpha.candidate_learning.repository import LearningLedgerRepository
from alpha.market_intelligence.point_in_time_store import (
    resolve_point_in_time_store_path,
)

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_FOUR = Decimal("0.0001")
_TWO = Decimal("0.01")
_POSITIVE_VERDICTS = {"BUY", "STRONG_BUY"}
_DEPLOYABLE_VERDICTS = {"BUY", "STRONG_BUY"}
_PROHIBITED_ACTION = (
    "Do not disable regime in production, alter scores, verdicts, gates, "
    "trade plans, approvals, allocation, market-regime thresholds, regime "
    "labels, candidate generation, posterior probability, expectancy, "
    "retracement calculations, diagnostic records, snapshots, provenance, or "
    "release manifests from this diagnostic audit."
)


class RegimeDependencyRole(StrEnum):
    DIRECT_SCORE_INPUT = "DIRECT_SCORE_INPUT"
    DIRECT_VERDICT_INPUT = "DIRECT_VERDICT_INPUT"
    DIRECT_GATE_INPUT = "DIRECT_GATE_INPUT"
    DIRECT_ALLOCATION_INPUT = "DIRECT_ALLOCATION_INPUT"
    INDIRECT_DEPENDENCY = "INDIRECT_DEPENDENCY"
    DISPLAY_ONLY = "DISPLAY_ONLY"
    PROVENANCE_ONLY = "PROVENANCE_ONLY"
    UNUSED = "UNUSED"


class RegimeCounterfactualView(StrEnum):
    RECORDED_PRODUCTION = "RECORDED_PRODUCTION"
    NO_REGIME_INTERVENTION = "NO_REGIME_INTERVENTION"
    REGIME_CONTEXT_ONLY = "REGIME_CONTEXT_ONLY"
    REGIME_INTERVENTION_ZEROED = "REGIME_INTERVENTION_ZEROED"
    BULLISH_ONLY_POSITIVE_ADJUSTMENT_REMOVED = (
        "BULLISH_ONLY_POSITIVE_ADJUSTMENT_REMOVED"
    )
    BEARISH_ONLY_NEGATIVE_ADJUSTMENT_REMOVED = (
        "BEARISH_ONLY_NEGATIVE_ADJUSTMENT_REMOVED"
    )
    DIAGNOSTIC_V2_REGIME_WITH_CURRENT_ADJUSTMENT = (
        "DIAGNOSTIC_V2_REGIME_WITH_CURRENT_ADJUSTMENT"
    )
    RECORDED_REGIME_WITH_CURRENT_ADJUSTMENT = "RECORDED_REGIME_WITH_CURRENT_ADJUSTMENT"


class RegimeInfluenceConclusion(StrEnum):
    REGIME_INTERVENTION_ADDS_STABLE_VALUE = "REGIME_INTERVENTION_ADDS_STABLE_VALUE"
    REGIME_INTERVENTION_ADDS_LIMITED_VALUE = "REGIME_INTERVENTION_ADDS_LIMITED_VALUE"
    REGIME_INTERVENTION_HAS_NEGLIGIBLE_EFFECT = (
        "REGIME_INTERVENTION_HAS_NEGLIGIBLE_EFFECT"
    )
    REGIME_INTERVENTION_DEGRADES_RANKING = "REGIME_INTERVENTION_DEGRADES_RANKING"
    REGIME_INTERVENTION_CAUSES_HARMFUL_VERDICT_CHANGES = (
        "REGIME_INTERVENTION_CAUSES_HARMFUL_VERDICT_CHANGES"
    )
    BEARISH_INTERVENTION_ADDS_DOWNSIDE_PROTECTION = (
        "BEARISH_INTERVENTION_ADDS_DOWNSIDE_PROTECTION"
    )
    BULLISH_INTERVENTION_ADDS_FALSE_PROMOTIONS = (
        "BULLISH_INTERVENTION_ADDS_FALSE_PROMOTIONS"
    )
    REGIME_INFLUENCE_IS_SETUP_SPECIFIC = "REGIME_INFLUENCE_IS_SETUP_SPECIFIC"
    REGIME_SHOULD_REMAIN_CONTEXT_ONLY = "REGIME_SHOULD_REMAIN_CONTEXT_ONLY"
    REGIME_CAN_BE_SAFELY_REMOVED_FROM_SCORE_RESEARCH = (
        "REGIME_CAN_BE_SAFELY_REMOVED_FROM_SCORE_RESEARCH"
    )
    INSUFFICIENT_EVIDENCE_FOR_REGIME_DEACTIVATION = (
        "INSUFFICIENT_EVIDENCE_FOR_REGIME_DEACTIVATION"
    )


class RegimeInfluenceNextMilestone(StrEnum):
    IMPLEMENT_REGIME_CONTEXT_ONLY_SHADOW_MODE = (
        "IMPLEMENT_REGIME_CONTEXT_ONLY_SHADOW_MODE"
    )
    AUDIT_REGIME_INTERVENTION_POLICY = "AUDIT_REGIME_INTERVENTION_POLICY"
    REMOVE_REGIME_FROM_SCORE_BEHIND_FEATURE_FLAG = (
        "REMOVE_REGIME_FROM_SCORE_BEHIND_FEATURE_FLAG"
    )
    RETAIN_BEARISH_INTERVENTION_ONLY_SHADOW_MODE = (
        "RETAIN_BEARISH_INTERVENTION_ONLY_SHADOW_MODE"
    )
    RETAIN_REGIME_PRODUCTION_INFLUENCE = "RETAIN_REGIME_PRODUCTION_INFLUENCE"
    AUDIT_MOMENTUM_MARKET_STATE_INTERACTION = "AUDIT_MOMENTUM_MARKET_STATE_INTERACTION"
    MATERIALIZE_BENCHMARK_FIELDS_IN_DIAGNOSTIC_STORE = (
        "MATERIALIZE_BENCHMARK_FIELDS_IN_DIAGNOSTIC_STORE"
    )
    COLLECT_MORE_AUTHORITATIVE_MARKET_STATE_HISTORY = (
        "COLLECT_MORE_AUTHORITATIVE_MARKET_STATE_HISTORY"
    )


class RegimeDecisionMatrixStatus(StrEnum):
    RETAIN_PRODUCTION_INFLUENCE = "RETAIN_PRODUCTION_INFLUENCE"
    RETAIN_NEGATIVE_ONLY = "RETAIN_NEGATIVE_ONLY"
    RETAIN_POSITIVE_ONLY = "RETAIN_POSITIVE_ONLY"
    RETAIN_AS_CONTEXT_ONLY = "RETAIN_AS_CONTEXT_ONLY"
    REMOVE_FROM_SCORE_RETAIN_FOR_GATES = "REMOVE_FROM_SCORE_RETAIN_FOR_GATES"
    REMOVE_FROM_DECISIONS = "REMOVE_FROM_DECISIONS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True, slots=True)
class RegimeProductionDependency:
    consumer: str
    input_field: str
    source: str
    dependency_type: str
    decision_relevant: bool
    display_only: bool
    fallback_behavior: str
    missing_input_behavior: str
    maximum_theoretical_impact: str
    role: RegimeDependencyRole


@dataclass(frozen=True, slots=True)
class RegimeInfluenceUniverse:
    candidate_records: int
    completed_outcomes: int
    distinct_decision_dates: int
    recorded_regime_available: int
    diagnostic_v2_regime_available: int
    pre_regime_score_available: int
    post_regime_score_available: int
    verdict_available: int
    approval_available: int
    allocation_available: int
    diagnostic_v2_candidate_links: int
    diagnostic_v2_fingerprint: str


@dataclass(frozen=True, slots=True)
class RegimeInterventionDefinition:
    input_regime: str
    adjustment_magnitude: Decimal
    score_component_affected: str
    pre_adjustment_score: Decimal | None
    post_adjustment_score: Decimal | None
    clamping_behavior: str
    normalization_behavior: str
    verdict_thresholds_affected: str
    fallback_regime: str
    missing_regime_behavior: str


@dataclass(frozen=True, slots=True)
class RegimeScoreInfluenceRow:
    view: RegimeCounterfactualView
    candidate_count: int
    mean_score_change: Decimal | None
    median_score_change: Decimal | None
    maximum_score_change: Decimal | None
    minimum_score_change: Decimal | None
    score_rank_changes: int
    top_decile_membership_changes: int
    bottom_decile_membership_changes: int
    candidates_with_no_score_change: int
    small_score_change: int
    material_score_change: int
    verdict_boundary_proximity: int


@dataclass(frozen=True, slots=True)
class RegimeVerdictInfluenceRow:
    view: RegimeCounterfactualView
    transition: str
    candidate_count: int
    distinct_dates: int
    setup_distribution: tuple[tuple[str, int], ...]
    recorded_regime_distribution: tuple[tuple[str, int], ...]
    diagnostic_v2_regime_distribution: tuple[tuple[str, int], ...]
    completed_outcomes: int
    win_rate: Decimal | None
    average_return: Decimal | None
    benchmark_relative_return: Decimal | None


@dataclass(frozen=True, slots=True)
class RegimeRankingInfluenceRow:
    view: RegimeCounterfactualView
    auc: Decimal | None
    spearman_correlation: Decimal | None
    top_decile_win_rate: Decimal | None
    bottom_decile_win_rate: Decimal | None
    top_decile_membership_overlap: Decimal | None
    rank_displacement: Decimal | None
    buy_precision_proxy: Decimal | None
    profitable_rejection_recovery: int


@dataclass(frozen=True, slots=True)
class RegimeSelectionInfluenceRow:
    stage: str
    before_regime_intervention: int
    after_regime_intervention: int
    candidates_added: int
    candidates_removed: int
    winners_added: int
    losers_added: int
    winners_removed: int
    losers_removed: int
    influence_path: str


@dataclass(frozen=True, slots=True)
class RegimeApprovalInfluenceReport:
    raw_recorded_approval_count: int
    raw_no_regime_approval_count: int
    strict_recorded_approval_count: int
    strict_no_regime_approval_count: int
    rejection_count: int
    near_approval_count: int
    mean_approval_margin_change: Decimal | None
    candidates_crossing_approval_threshold: int
    profitable_approvals_gained: int
    losing_approvals_gained: int
    profitable_approvals_lost: int
    losing_approvals_lost: int


@dataclass(frozen=True, slots=True)
class RegimeAllocationInfluenceReport:
    direct_allocation_consumer: bool
    indirect_allocation_path: str
    candidates_with_allocation_change: int
    total_target_weight_change: Decimal | None
    gross_exposure_change: Decimal | None
    net_exposure_change: Decimal | None
    capital_deployment_gained: Decimal | None
    capital_deployment_removed: Decimal | None
    explanation: str


@dataclass(frozen=True, slots=True)
class RegimeSetupInfluenceRow:
    setup_family: str
    sample_count: int
    mean_score_change: Decimal | None
    verdict_changes: int
    approval_changes: int
    average_outcome: Decimal | None
    benchmark_relative_outcome: Decimal | None
    mfe: Decimal | None
    mae: Decimal | None
    finding: str


@dataclass(frozen=True, slots=True)
class RegimeAsymmetryReport:
    bullish_promotions: int
    bullish_promoted_winners: int
    bullish_promoted_losers: int
    bearish_demotions: int
    bearish_demoted_winners: int
    bearish_demoted_losers: int
    neutral_unchanged: int
    precision_of_bullish_promotions: Decimal | None
    downside_avoided_by_bearish_demotions: Decimal | None
    missed_upside_from_bearish_demotions: Decimal | None
    false_promotion_rate: Decimal | None
    false_demotion_rate: Decimal | None
    conclusion: RegimeInfluenceConclusion


@dataclass(frozen=True, slots=True)
class RecordedVsV2RegimeInfluenceReport:
    agreement_count: int
    disagreement_count: int
    score_differences: int
    verdict_differences: int
    ranking_differences: int
    approval_differences: int
    allocation_differences: int
    average_outcome_on_disagreement: Decimal | None
    explanation: str


@dataclass(frozen=True, slots=True)
class RegimeContextOnlyReport:
    retained_capabilities: tuple[str, ...]
    removed_in_context_only: tuple[str, ...]
    score_unchanged: bool
    verdict_unchanged: bool
    approval_unchanged: bool
    allocation_unchanged: bool
    explanation_retained: bool
    grouping_retained: bool
    shadow_mode_design: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RegimeSafeDeactivationReadinessReport:
    universe: RegimeInfluenceUniverse
    dependency_count: int
    direct_regime_consumers: int
    indirect_regime_consumers: int
    display_only_consumers: int
    score_materiality: str
    verdict_changes: int
    approval_changes: int
    allocation_changes: int
    date_weighted_alignment: str
    quality_conditioned_stability: str
    hidden_dependencies_found: bool
    safe_deactivation_preconditions: tuple[tuple[str, bool], ...]
    decision_matrix: tuple[tuple[str, RegimeDecisionMatrixStatus, str], ...]
    primary_conclusion: RegimeInfluenceConclusion
    secondary_conclusion: RegimeInfluenceConclusion | None
    recommended_next_milestone: RegimeInfluenceNextMilestone
    prohibited_action: str


@dataclass(frozen=True, slots=True)
class _V2Link:
    regime: str
    diagnostic_quality: str


@dataclass(frozen=True, slots=True)
class _Outcome:
    forward_return: Decimal | None
    benchmark_relative_return: Decimal | None
    mfe: Decimal | None
    mae: Decimal | None
    target_hit: bool
    stop_hit: bool


@dataclass(frozen=True, slots=True)
class _Counterfactual:
    record: CandidateDecisionRecord
    outcome: _Outcome | None
    v2: _V2Link | None
    recorded_adjustment: Decimal
    no_regime_score: Decimal
    recorded_score: Decimal
    no_regime_verdict: str
    recorded_verdict: str


class RegimeProductionInfluenceAuditEngine:
    def __init__(
        self,
        *,
        ledger_path: Path | str | None = None,
        store_path: Path | str | None = None,
    ) -> None:
        self.ledger = LearningLedgerRepository(ledger_path)
        self.store_path = resolve_point_in_time_store_path(store_path)

    def dependency_map(self) -> tuple[RegimeProductionDependency, ...]:
        return (
            RegimeProductionDependency(
                consumer="EvidenceScoringEngine.assess",
                input_field="RecommendationCandidate.market_regime",
                source="recommendation candidate / persisted candidate ledger",
                dependency_type="direct",
                decision_relevant=True,
                display_only=False,
                fallback_behavior="sideways-style caution when not bull or bear",
                missing_input_behavior="defaults to non-bull/non-bear branch",
                maximum_theoretical_impact=(
                    "5% weighted market-regime evidence plus +/-2 to -9 "
                    "regime adjustment points"
                ),
                role=RegimeDependencyRole.DIRECT_SCORE_INPUT,
            ),
            RegimeProductionDependency(
                consumer="RecommendationScoringEngine._apply_regime_and_risk_overrides",
                input_field="RecommendationCandidate.market_regime",
                source="recommendation candidate",
                dependency_type="direct",
                decision_relevant=True,
                display_only=False,
                fallback_behavior="no bear/sideways override when regime differs",
                missing_input_behavior="no explicit regime override",
                maximum_theoretical_impact="score capped to 74 or 59 in edge cases",
                role=RegimeDependencyRole.DIRECT_VERDICT_INPUT,
            ),
            RegimeProductionDependency(
                consumer="InstitutionalDecisionEngine.score",
                input_field="InstitutionalCandidate.market_regime",
                source="recommendation to decision candidate adapter",
                dependency_type="direct",
                decision_relevant=True,
                display_only=False,
                fallback_behavior="non-bearish receives higher market fit",
                missing_input_behavior="treated as acceptable market fit",
                maximum_theoretical_impact="7% opportunity-score component",
                role=RegimeDependencyRole.DIRECT_GATE_INPUT,
            ),
            RegimeProductionDependency(
                consumer="SetupQualityScorecard",
                input_field="InstitutionalCandidate.market_regime",
                source="decision candidate",
                dependency_type="direct",
                decision_relevant=True,
                display_only=False,
                fallback_behavior="non-bearish receives higher setup regime fit",
                missing_input_behavior="treated as non-bearish",
                maximum_theoretical_impact="5% setup-quality scorecard component",
                role=RegimeDependencyRole.INDIRECT_DEPENDENCY,
            ),
            RegimeProductionDependency(
                consumer="CapitalAllocationEngine",
                input_field="final verdict / approved_for_deployment",
                source="regime-adjusted recommendation and decision outputs",
                dependency_type="indirect",
                decision_relevant=True,
                display_only=False,
                fallback_behavior="allocation follows verdict and approval gates",
                missing_input_behavior="no direct market-regime read",
                maximum_theoretical_impact="indirect deployment eligibility change",
                role=RegimeDependencyRole.INDIRECT_DEPENDENCY,
            ),
            RegimeProductionDependency(
                consumer="CLI intelligence and replay rendering",
                input_field="market_regime",
                source="recommendation, candidate ledger and diagnostic store",
                dependency_type="direct",
                decision_relevant=False,
                display_only=True,
                fallback_behavior="print unavailable or neutral context",
                missing_input_behavior="display missing regime context",
                maximum_theoretical_impact="none when used only for rendering",
                role=RegimeDependencyRole.DISPLAY_ONLY,
            ),
            RegimeProductionDependency(
                consumer="snapshot/provenance persistence",
                input_field="classifier_version / market_state_snapshot_id",
                source="market-state snapshot repository",
                dependency_type="direct",
                decision_relevant=False,
                display_only=False,
                fallback_behavior="persist fallback metadata",
                missing_input_behavior="record missing completeness/fallback state",
                maximum_theoretical_impact="audit lineage only",
                role=RegimeDependencyRole.PROVENANCE_ONLY,
            ),
            RegimeProductionDependency(
                consumer="candidate generation",
                input_field="market_regime",
                source="none",
                dependency_type="none",
                decision_relevant=False,
                display_only=False,
                fallback_behavior="not consumed",
                missing_input_behavior="not consumed",
                maximum_theoretical_impact="none observed in ledger audit",
                role=RegimeDependencyRole.UNUSED,
            ),
        )

    def universe(self) -> RegimeInfluenceUniverse:
        records = self.ledger.load_records()
        outcomes = self.ledger.load_outcomes()
        v2 = self._v2_links()
        completed = {
            outcome.candidate_id
            for outcome in outcomes
            if _primary_window(outcome) is not None
        }
        return RegimeInfluenceUniverse(
            candidate_records=len(records),
            completed_outcomes=len(completed),
            distinct_decision_dates=len({record.evaluation_date for record in records}),
            recorded_regime_available=sum(
                1 for record in records if record.market_regime
            ),
            diagnostic_v2_regime_available=sum(
                1 for record in records if record.candidate_id in v2
            ),
            pre_regime_score_available=sum(
                1 for row in self._rows() if row.no_regime_score is not None
            ),
            post_regime_score_available=sum(
                1 for record in records if record.strategy_score is not None
            ),
            verdict_available=sum(1 for record in records if record.final_verdict),
            approval_available=len(records),
            allocation_available=sum(
                1
                for record in records
                if record.capital_action or record.approved_for_deployment is not None
            ),
            diagnostic_v2_candidate_links=len(v2),
            diagnostic_v2_fingerprint=self._v2_fingerprint(),
        )

    def intervention_definition(self) -> tuple[RegimeInterventionDefinition, ...]:
        rows = self._rows()
        examples: dict[str, _Counterfactual] = {}
        for row in rows:
            key = _canonical_regime(row.record.market_regime)
            examples.setdefault(key, row)
        output = []
        for regime in ("BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"):
            example = examples.get(regime)
            adjustment = (
                _regime_adjustment_for(
                    regime, example.record.setup_type if example else None
                )
                if example is None
                else example.recorded_adjustment
            )
            output.append(
                RegimeInterventionDefinition(
                    input_regime=regime,
                    adjustment_magnitude=adjustment,
                    score_component_affected=(
                        "EvidenceAssessment.regime_adjustment_points and "
                        "RecommendationScore.breakdown.market_regime_points"
                    ),
                    pre_adjustment_score=(
                        None if example is None else example.no_regime_score
                    ),
                    post_adjustment_score=(
                        None if example is None else example.recorded_score
                    ),
                    clamping_behavior="final evidence score is clamped to 0-100",
                    normalization_behavior=(
                        "regime aliases canonicalized for audit only"
                    ),
                    verdict_thresholds_affected=(
                        "90 strong buy, 75 buy, 60 watchlist, 40 avoid"
                    ),
                    fallback_regime="SIDEWAYS/NEUTRAL caution branch",
                    missing_regime_behavior=(
                        "no recorded regime is treated as unknown; no hidden value "
                        "is inferred"
                    ),
                )
            )
        return tuple(output)

    def score_influence(self) -> tuple[RegimeScoreInfluenceRow, ...]:
        rows = self._rows()
        return tuple(
            self._score_influence_for(view, rows) for view in RegimeCounterfactualView
        )

    def verdict_influence(
        self,
        view: RegimeCounterfactualView = (
            RegimeCounterfactualView.NO_REGIME_INTERVENTION
        ),
    ) -> tuple[RegimeVerdictInfluenceRow, ...]:
        groups: dict[str, list[_Counterfactual]] = defaultdict(list)
        for row in self._rows():
            transition = f"{row.recorded_verdict} -> {self._verdict_for(view, row)}"
            groups[transition].append(row)
        return tuple(
            self._transition_row(view, transition, tuple(items))
            for transition, items in sorted(groups.items())
        )

    def ranking_influence(self) -> tuple[RegimeRankingInfluenceRow, ...]:
        rows = self._completed_rows()
        return tuple(self._ranking_for(view, rows) for view in RegimeCounterfactualView)

    def selection_influence(self) -> tuple[RegimeSelectionInfluenceRow, ...]:
        rows = self._rows()
        return (
            _stage_row(
                "candidate_creation",
                rows,
                lambda row: True,
                lambda row: True,
                "regime not consumed before candidate record creation",
            ),
            _stage_row(
                "candidate_shortlist",
                rows,
                lambda row: True,
                lambda row: True,
                "ledger contains final candidate universe only; no direct regime path",
            ),
            _stage_row(
                "BUY_classification",
                rows,
                lambda row: row.recorded_verdict in _POSITIVE_VERDICTS,
                lambda row: row.no_regime_verdict in _POSITIVE_VERDICTS,
                "indirect through score and verdict thresholds",
            ),
            _stage_row(
                "acceptable_timing",
                rows,
                lambda row: (
                    (row.record.capital_action or "").upper() in {"BUY", "ACCUMULATE"}
                ),
                lambda row: (
                    (row.record.capital_action or "").upper() in {"BUY", "ACCUMULATE"}
                ),
                "entry timing does not consume regime in the persisted ledger",
            ),
            _stage_row(
                "approval_eligibility",
                rows,
                lambda row: row.record.approved_for_deployment,
                self._no_regime_approved,
                "indirect through verdict and score eligibility",
            ),
            _stage_row(
                "allocation_eligibility",
                rows,
                lambda row: row.record.approved_for_deployment,
                self._no_regime_approved,
                "indirect through approval eligibility; no direct allocation read",
            ),
        )

    def approval_influence(self) -> RegimeApprovalInfluenceReport:
        rows = self._rows()
        recorded = [row for row in rows if row.record.approved_for_deployment]
        no_regime = [row for row in rows if self._no_regime_approved(row)]
        recorded_ids = {row.record.candidate_id for row in recorded}
        no_regime_ids = {row.record.candidate_id for row in no_regime}
        gained = tuple(
            row for row in no_regime if row.record.candidate_id not in recorded_ids
        )
        lost = tuple(
            row for row in recorded if row.record.candidate_id not in no_regime_ids
        )
        margin_changes = [
            (row.no_regime_score - row.recorded_score).quantize(_FOUR)
            for row in rows
            if abs(row.recorded_score - Decimal("75")) <= Decimal("5")
        ]
        return RegimeApprovalInfluenceReport(
            raw_recorded_approval_count=len(recorded),
            raw_no_regime_approval_count=len(no_regime),
            strict_recorded_approval_count=len(recorded),
            strict_no_regime_approval_count=len(no_regime),
            rejection_count=len(rows) - len(recorded),
            near_approval_count=len(margin_changes),
            mean_approval_margin_change=_average(margin_changes),
            candidates_crossing_approval_threshold=len(gained) + len(lost),
            profitable_approvals_gained=sum(_is_winner(row) for row in gained),
            losing_approvals_gained=sum(_is_loser(row) for row in gained),
            profitable_approvals_lost=sum(_is_winner(row) for row in lost),
            losing_approvals_lost=sum(_is_loser(row) for row in lost),
        )

    def allocation_influence(self) -> RegimeAllocationInfluenceReport:
        rows = self._rows()
        changed = tuple(
            row
            for row in rows
            if row.record.approved_for_deployment != self._no_regime_approved(row)
        )
        return RegimeAllocationInfluenceReport(
            direct_allocation_consumer=False,
            indirect_allocation_path=(
                "market_regime -> score/verdict/decision quality -> approval "
                "eligibility -> allocation eligibility"
            ),
            candidates_with_allocation_change=len(changed),
            total_target_weight_change=None,
            gross_exposure_change=None,
            net_exposure_change=None,
            capital_deployment_gained=None,
            capital_deployment_removed=None,
            explanation=(
                "Candidate ledger stores approval and capital action, but not "
                "per-candidate target weights or rupee amounts; exposure deltas "
                "are unavailable rather than fabricated."
            ),
        )

    def setup_influence(self) -> tuple[RegimeSetupInfluenceRow, ...]:
        groups: dict[str, list[_Counterfactual]] = defaultdict(list)
        for row in self._rows():
            groups[_setup_family(row.record.setup_type)].append(row)
        return tuple(
            _setup_row(name, tuple(items), self._no_regime_approved)
            for name, items in sorted(groups.items())
        )

    def asymmetry(self) -> RegimeAsymmetryReport:
        rows = self._rows()
        bullish = tuple(row for row in rows if row.recorded_adjustment > 0)
        bearish = tuple(row for row in rows if row.recorded_adjustment < 0)
        neutral = tuple(row for row in rows if row.recorded_adjustment == 0)
        bullish_promotions = tuple(
            row
            for row in bullish
            if _verdict_rank(row.recorded_verdict)
            > _verdict_rank(row.no_regime_verdict)
        )
        bearish_demotions = tuple(
            row
            for row in bearish
            if _verdict_rank(row.recorded_verdict)
            < _verdict_rank(row.no_regime_verdict)
        )
        missed = [
            row.outcome.forward_return
            for row in bearish_demotions
            if row.outcome is not None
            and row.outcome.forward_return is not None
            and row.outcome.forward_return > 0
        ]
        avoided = [
            abs(row.outcome.forward_return)
            for row in bearish_demotions
            if row.outcome is not None
            and row.outcome.forward_return is not None
            and row.outcome.forward_return < 0
        ]
        false_promotions = sum(_is_loser(row) for row in bullish_promotions)
        false_demotions = sum(_is_winner(row) for row in bearish_demotions)
        conclusion = (
            RegimeInfluenceConclusion.BULLISH_INTERVENTION_ADDS_FALSE_PROMOTIONS
            if false_promotions > sum(_is_winner(row) for row in bullish_promotions)
            else RegimeInfluenceConclusion.BEARISH_INTERVENTION_ADDS_DOWNSIDE_PROTECTION
            if avoided and (sum(avoided, _ZERO) >= sum(missed, _ZERO))
            else RegimeInfluenceConclusion.INSUFFICIENT_EVIDENCE_FOR_REGIME_DEACTIVATION
        )
        return RegimeAsymmetryReport(
            bullish_promotions=len(bullish_promotions),
            bullish_promoted_winners=sum(_is_winner(row) for row in bullish_promotions),
            bullish_promoted_losers=false_promotions,
            bearish_demotions=len(bearish_demotions),
            bearish_demoted_winners=false_demotions,
            bearish_demoted_losers=sum(_is_loser(row) for row in bearish_demotions),
            neutral_unchanged=len(neutral),
            precision_of_bullish_promotions=_ratio(
                sum(_is_winner(row) for row in bullish_promotions),
                len(bullish_promotions),
            ),
            downside_avoided_by_bearish_demotions=_average(avoided),
            missed_upside_from_bearish_demotions=_average(missed),
            false_promotion_rate=_ratio(false_promotions, len(bullish_promotions)),
            false_demotion_rate=_ratio(false_demotions, len(bearish_demotions)),
            conclusion=conclusion,
        )

    def recorded_vs_v2(self) -> RecordedVsV2RegimeInfluenceReport:
        rows = tuple(row for row in self._rows() if row.v2 is not None)
        agreement = tuple(
            row
            for row in rows
            if _canonical_regime(row.record.market_regime)
            == _canonical_regime(row.v2.regime if row.v2 else None)
        )
        disagreement = tuple(row for row in rows if row not in agreement)
        score_differences = sum(
            self._score_for(
                RegimeCounterfactualView.DIAGNOSTIC_V2_REGIME_WITH_CURRENT_ADJUSTMENT,
                row,
            )
            != row.recorded_score
            for row in rows
        )
        verdict_differences = sum(
            self._verdict_for(
                RegimeCounterfactualView.DIAGNOSTIC_V2_REGIME_WITH_CURRENT_ADJUSTMENT,
                row,
            )
            != row.recorded_verdict
            for row in rows
        )
        avg = _average(
            [
                row.outcome.forward_return
                for row in disagreement
                if row.outcome is not None and row.outcome.forward_return is not None
            ]
        )
        return RecordedVsV2RegimeInfluenceReport(
            agreement_count=len(agreement),
            disagreement_count=len(disagreement),
            score_differences=score_differences,
            verdict_differences=verdict_differences,
            ranking_differences=self._score_influence_for(
                RegimeCounterfactualView.DIAGNOSTIC_V2_REGIME_WITH_CURRENT_ADJUSTMENT,
                rows,
            ).score_rank_changes,
            approval_differences=sum(
                self._no_regime_approved(row)
                != (
                    self._verdict_for(
                        RegimeCounterfactualView.DIAGNOSTIC_V2_REGIME_WITH_CURRENT_ADJUSTMENT,
                        row,
                    )
                    in _DEPLOYABLE_VERDICTS
                    and self._score_for(
                        RegimeCounterfactualView.DIAGNOSTIC_V2_REGIME_WITH_CURRENT_ADJUSTMENT,
                        row,
                    )
                    >= Decimal("75")
                    and row.record.approved_for_deployment
                )
                for row in rows
            ),
            allocation_differences=0,
            average_outcome_on_disagreement=avg,
            explanation=(
                "Diagnostic V2 regime is compared research-only; recorded "
                "regimes are not replaced."
            ),
        )

    def context_only(self) -> RegimeContextOnlyReport:
        return RegimeContextOnlyReport(
            retained_capabilities=(
                "market commentary",
                "setup/regime analysis",
                "risk warnings",
                "historical grouping",
                "explainability",
                "post-trade analytics",
            ),
            removed_in_context_only=(
                "score intervention",
                "verdict intervention",
                "approval intervention",
                "allocation intervention",
                "candidate selection intervention",
            ),
            score_unchanged=True,
            verdict_unchanged=True,
            approval_unchanged=True,
            allocation_unchanged=True,
            explanation_retained=True,
            grouping_retained=True,
            shadow_mode_design=(
                "record production score and no-regime score side by side",
                "record production verdict and no-regime verdict",
                "record production approval and no-regime approval",
                "record production allocation and no-regime allocation",
                "persist differences without altering live outputs",
                "version the comparison and retain rollback evidence",
            ),
        )

    def safe_deactivation_readiness(self) -> RegimeSafeDeactivationReadinessReport:
        score = self.score_influence()
        no_regime = next(
            row
            for row in score
            if row.view is RegimeCounterfactualView.NO_REGIME_INTERVENTION
        )
        verdict_changes = sum(
            row.candidate_count
            for row in self.verdict_influence()
            if not row.transition.endswith(f"-> {row.transition.split(' -> ')[0]}")
            and row.transition.split(" -> ")[0] != row.transition.split(" -> ")[1]
        )
        approval = self.approval_influence()
        allocation = self.allocation_influence()
        dependencies = self.dependency_map()
        direct = sum(
            item.role
            in {
                RegimeDependencyRole.DIRECT_SCORE_INPUT,
                RegimeDependencyRole.DIRECT_VERDICT_INPUT,
                RegimeDependencyRole.DIRECT_GATE_INPUT,
                RegimeDependencyRole.DIRECT_ALLOCATION_INPUT,
            }
            for item in dependencies
        )
        indirect = sum(
            item.role is RegimeDependencyRole.INDIRECT_DEPENDENCY
            for item in dependencies
        )
        display = sum(
            item.role is RegimeDependencyRole.DISPLAY_ONLY for item in dependencies
        )
        preconditions = (
            ("counterfactual reconstruction complete", True),
            ("score parity validated", no_regime.material_score_change == 0),
            ("verdict-change inventory complete", True),
            ("approval impact understood", True),
            (
                "allocation impact understood",
                allocation.direct_allocation_consumer is False,
            ),
            ("no hidden dependencies", False),
            ("regression tests prepared", True),
            ("feature flag available", False),
            ("rollback path available", False),
            ("live shadow comparison planned", True),
        )
        primary = (
            RegimeInfluenceConclusion.REGIME_INTERVENTION_HAS_NEGLIGIBLE_EFFECT
            if no_regime.material_score_change == 0 and verdict_changes == 0
            else RegimeInfluenceConclusion.INSUFFICIENT_EVIDENCE_FOR_REGIME_DEACTIVATION
        )
        next_milestone = (
            RegimeInfluenceNextMilestone.IMPLEMENT_REGIME_CONTEXT_ONLY_SHADOW_MODE
        )
        return RegimeSafeDeactivationReadinessReport(
            universe=self.universe(),
            dependency_count=len(dependencies),
            direct_regime_consumers=direct,
            indirect_regime_consumers=indirect,
            display_only_consumers=display,
            score_materiality=(
                "material" if no_regime.material_score_change else "not_material"
            ),
            verdict_changes=verdict_changes,
            approval_changes=approval.candidates_crossing_approval_threshold,
            allocation_changes=allocation.candidates_with_allocation_change,
            date_weighted_alignment="reported separately; no production mutation",
            quality_conditioned_stability="diagnostic-only; not sufficient for removal",
            hidden_dependencies_found=True,
            safe_deactivation_preconditions=preconditions,
            decision_matrix=(
                (
                    "ranking value",
                    RegimeDecisionMatrixStatus.INSUFFICIENT_EVIDENCE,
                    "counterfactual rank impact measured but not causal",
                ),
                (
                    "verdict value",
                    RegimeDecisionMatrixStatus.INSUFFICIENT_EVIDENCE,
                    "verdict transitions require shadow validation",
                ),
                (
                    "allocation value",
                    RegimeDecisionMatrixStatus.RETAIN_AS_CONTEXT_ONLY,
                    "allocation consumes regime indirectly through decisions",
                ),
                (
                    "interpretability",
                    RegimeDecisionMatrixStatus.RETAIN_AS_CONTEXT_ONLY,
                    "context retains explanatory usefulness",
                ),
                (
                    "maintenance burden",
                    RegimeDecisionMatrixStatus.INSUFFICIENT_EVIDENCE,
                    "feature flag and rollback path are not implemented",
                ),
            ),
            primary_conclusion=primary,
            secondary_conclusion=RegimeInfluenceConclusion.REGIME_SHOULD_REMAIN_CONTEXT_ONLY,
            recommended_next_milestone=next_milestone,
            prohibited_action=_PROHIBITED_ACTION,
        )

    def _rows(self) -> tuple[_Counterfactual, ...]:
        outcomes = {
            outcome.candidate_id: _outcome_from(_primary_window(outcome))
            for outcome in self.ledger.load_outcomes()
        }
        v2 = self._v2_links()
        return tuple(
            _counterfactual(
                record, outcomes.get(record.candidate_id), v2.get(record.candidate_id)
            )
            for record in self.ledger.load_records()
        )

    def _completed_rows(self) -> tuple[_Counterfactual, ...]:
        return tuple(row for row in self._rows() if row.outcome is not None)

    def _score_for(
        self,
        view: RegimeCounterfactualView,
        row: _Counterfactual,
    ) -> Decimal:
        if view is RegimeCounterfactualView.RECORDED_PRODUCTION:
            return row.recorded_score
        if view in {
            RegimeCounterfactualView.NO_REGIME_INTERVENTION,
            RegimeCounterfactualView.REGIME_CONTEXT_ONLY,
            RegimeCounterfactualView.REGIME_INTERVENTION_ZEROED,
        }:
            return row.no_regime_score
        if (
            view is RegimeCounterfactualView.BULLISH_ONLY_POSITIVE_ADJUSTMENT_REMOVED
            and row.recorded_adjustment > 0
        ):
            return row.no_regime_score
        if (
            view is RegimeCounterfactualView.BEARISH_ONLY_NEGATIVE_ADJUSTMENT_REMOVED
            and row.recorded_adjustment < 0
        ):
            return row.no_regime_score
        if (
            view
            is RegimeCounterfactualView.DIAGNOSTIC_V2_REGIME_WITH_CURRENT_ADJUSTMENT
        ):
            v2_adj = _regime_adjustment_for(
                row.v2.regime if row.v2 else None,
                row.record.setup_type,
            )
            return _clamp_score(row.no_regime_score + v2_adj)
        if view is RegimeCounterfactualView.RECORDED_REGIME_WITH_CURRENT_ADJUSTMENT:
            return _clamp_score(row.no_regime_score + row.recorded_adjustment)
        return row.recorded_score

    def _verdict_for(
        self,
        view: RegimeCounterfactualView,
        row: _Counterfactual,
    ) -> str:
        return _verdict_from_score(self._score_for(view, row))

    def _score_influence_for(
        self,
        view: RegimeCounterfactualView,
        rows: Sequence[_Counterfactual],
    ) -> RegimeScoreInfluenceRow:
        changes = [
            (self._score_for(view, row) - row.recorded_score).quantize(_FOUR)
            for row in rows
        ]
        recorded_top = _top_ids(rows, lambda row: row.recorded_score, True)
        view_top = _top_ids(rows, lambda row: self._score_for(view, row), True)
        recorded_bottom = _top_ids(rows, lambda row: row.recorded_score, False)
        view_bottom = _top_ids(rows, lambda row: self._score_for(view, row), False)
        return RegimeScoreInfluenceRow(
            view=view,
            candidate_count=len(rows),
            mean_score_change=_average(changes),
            median_score_change=_median(changes),
            maximum_score_change=max(changes) if changes else None,
            minimum_score_change=min(changes) if changes else None,
            score_rank_changes=_rank_changes(
                rows,
                lambda row: row.recorded_score,
                lambda row: self._score_for(view, row),
            ),
            top_decile_membership_changes=len(
                recorded_top.symmetric_difference(view_top)
            ),
            bottom_decile_membership_changes=len(
                recorded_bottom.symmetric_difference(view_bottom)
            ),
            candidates_with_no_score_change=sum(change == 0 for change in changes),
            small_score_change=sum(
                0 < abs(change) < Decimal("2") for change in changes
            ),
            material_score_change=sum(
                abs(change) >= Decimal("5") for change in changes
            ),
            verdict_boundary_proximity=sum(
                _near_verdict_boundary(row.recorded_score) for row in rows
            ),
        )

    def _transition_row(
        self,
        view: RegimeCounterfactualView,
        transition: str,
        rows: tuple[_Counterfactual, ...],
    ) -> RegimeVerdictInfluenceRow:
        completed = tuple(row for row in rows if row.outcome is not None)
        returns = [
            row.outcome.forward_return
            for row in completed
            if row.outcome is not None and row.outcome.forward_return is not None
        ]
        relative = [
            row.outcome.benchmark_relative_return
            for row in completed
            if row.outcome is not None
            and row.outcome.benchmark_relative_return is not None
        ]
        return RegimeVerdictInfluenceRow(
            view=view,
            transition=transition,
            candidate_count=len(rows),
            distinct_dates=len({row.record.evaluation_date for row in rows}),
            setup_distribution=_counts(
                row.record.setup_type or "UNKNOWN" for row in rows
            ),
            recorded_regime_distribution=_counts(
                _canonical_regime(row.record.market_regime) for row in rows
            ),
            diagnostic_v2_regime_distribution=_counts(
                _canonical_regime(row.v2.regime if row.v2 else None) for row in rows
            ),
            completed_outcomes=len(completed),
            win_rate=_ratio(sum(value > 0 for value in returns), len(returns)),
            average_return=_average(returns),
            benchmark_relative_return=_average(relative),
        )

    def _ranking_for(
        self,
        view: RegimeCounterfactualView,
        rows: tuple[_Counterfactual, ...],
    ) -> RegimeRankingInfluenceRow:
        scored = tuple((self._score_for(view, row), row) for row in rows)
        recorded_top = _top_ids(rows, lambda row: row.recorded_score, True)
        view_top = _top_ids(rows, lambda row: self._score_for(view, row), True)
        return RegimeRankingInfluenceRow(
            view=view,
            auc=_auc(scored),
            spearman_correlation=_spearman(
                [row.recorded_score for row in rows],
                [self._score_for(view, row) for row in rows],
            ),
            top_decile_win_rate=_decile_win_rate(scored, top=True),
            bottom_decile_win_rate=_decile_win_rate(scored, top=False),
            top_decile_membership_overlap=_ratio(
                len(recorded_top.intersection(view_top)),
                len(recorded_top) or 1,
            ),
            rank_displacement=_average(
                _rank_displacements(
                    rows,
                    lambda row: row.recorded_score,
                    lambda row: self._score_for(view, row),
                )
            ),
            buy_precision_proxy=_buy_precision(scored),
            profitable_rejection_recovery=sum(
                _is_winner(row)
                and row.recorded_verdict not in _POSITIVE_VERDICTS
                and self._verdict_for(view, row) in _POSITIVE_VERDICTS
                for _, row in scored
            ),
        )

    def _no_regime_approved(self, row: _Counterfactual) -> bool:
        if not row.record.approved_for_deployment:
            return False
        return (
            row.no_regime_verdict in _DEPLOYABLE_VERDICTS
            and row.no_regime_score >= Decimal("75")
        )

    def _v2_links(self) -> dict[str, _V2Link]:
        if not self.store_path.exists():
            return {}
        with duckdb.connect(str(self.store_path), read_only=True) as con:
            rows = con.execute(
                """
                SELECT link.candidate_stable_id, link.v2_regime,
                       state.diagnostic_quality
                FROM diagnostic_market_state_v2_candidate_links AS link
                LEFT JOIN diagnostic_market_state_v2 AS state
                  ON state.reconstruction_id = link.reconstruction_id
                ORDER BY link.candidate_stable_id
                """
            ).fetchall()
        return {
            str(row[0]): _V2Link(
                regime=str(row[1] or "UNKNOWN"),
                diagnostic_quality=str(row[2] or "UNKNOWN"),
            )
            for row in rows
        }

    def _v2_fingerprint(self) -> str:
        if not self.store_path.exists():
            return "unavailable"
        with duckdb.connect(str(self.store_path), read_only=True) as con:
            row = con.execute(
                """
                SELECT source_fingerprint
                FROM diagnostic_pit_builds
                ORDER BY imported_at DESC, build_id DESC
                LIMIT 1
                """
            ).fetchone()
        return "unavailable" if row is None else str(row[0])


def render_regime_production_dependency(
    rows: tuple[RegimeProductionDependency, ...],
) -> tuple[str, ...]:
    lines = ["Regime Production Dependency Map"]
    for row in rows:
        lines.append(
            f"- {row.consumer}: role={row.role.value}, field={row.input_field}, "
            f"decision_relevant={row.decision_relevant}, "
            f"display_only={row.display_only}; "
            f"impact={row.maximum_theoretical_impact}"
        )
    return tuple(lines)


def render_regime_score_influence(
    rows: tuple[RegimeScoreInfluenceRow, ...],
) -> tuple[str, ...]:
    lines = ["Regime Score Influence"]
    for row in rows:
        lines.append(
            f"- {row.view.value}: n={row.candidate_count}, "
            f"mean={_text(row.mean_score_change)}, "
            f"median={_text(row.median_score_change)}, "
            f"max={_text(row.maximum_score_change)}, "
            f"min={_text(row.minimum_score_change)}, "
            f"rank_changes={row.score_rank_changes}, "
            f"material={row.material_score_change}, "
            f"top_decile_changes={row.top_decile_membership_changes}"
        )
    return tuple(lines)


def render_regime_verdict_influence(
    rows: tuple[RegimeVerdictInfluenceRow, ...],
) -> tuple[str, ...]:
    lines = ["Regime Verdict Influence"]
    for row in rows:
        lines.append(
            f"- {row.view.value}/{row.transition}: n={row.candidate_count}, "
            f"dates={row.distinct_dates}, completed={row.completed_outcomes}, "
            f"win={_text(row.win_rate)}, avg={_text(row.average_return)}"
        )
    return tuple(lines)


def render_regime_ranking_influence(
    rows: tuple[RegimeRankingInfluenceRow, ...],
) -> tuple[str, ...]:
    lines = ["Regime Ranking Influence"]
    for row in rows:
        lines.append(
            f"- {row.view.value}: auc={_text(row.auc)}, "
            f"spearman={_text(row.spearman_correlation)}, "
            f"top_win={_text(row.top_decile_win_rate)}, "
            f"bottom_win={_text(row.bottom_decile_win_rate)}, "
            f"overlap={_text(row.top_decile_membership_overlap)}, "
            f"displacement={_text(row.rank_displacement)}, "
            f"buy_precision={_text(row.buy_precision_proxy)}"
        )
    return tuple(lines)


def render_regime_selection_influence(
    rows: tuple[RegimeSelectionInfluenceRow, ...],
) -> tuple[str, ...]:
    lines = ["Regime Selection Influence"]
    for row in rows:
        lines.append(
            f"- {row.stage}: before={row.before_regime_intervention}, "
            f"after={row.after_regime_intervention}, added={row.candidates_added}, "
            f"removed={row.candidates_removed}; {row.influence_path}"
        )
    return tuple(lines)


def render_regime_approval_influence(
    report: RegimeApprovalInfluenceReport,
) -> tuple[str, ...]:
    return (
        "Regime Approval Influence",
        f"Raw Recorded Approvals: {report.raw_recorded_approval_count}",
        f"Raw No-Regime Approvals: {report.raw_no_regime_approval_count}",
        f"Strict Recorded Approvals: {report.strict_recorded_approval_count}",
        f"Strict No-Regime Approvals: {report.strict_no_regime_approval_count}",
        f"Near-Approval Count: {report.near_approval_count}",
        "Approval Threshold Crossings: "
        f"{report.candidates_crossing_approval_threshold}",
        f"Profitable Approvals Gained: {report.profitable_approvals_gained}",
        f"Losing Approvals Gained: {report.losing_approvals_gained}",
        f"Profitable Approvals Lost: {report.profitable_approvals_lost}",
        f"Losing Approvals Lost: {report.losing_approvals_lost}",
    )


def render_regime_allocation_influence(
    report: RegimeAllocationInfluenceReport,
) -> tuple[str, ...]:
    return (
        "Regime Allocation Influence",
        "Direct Allocation Consumer: "
        f"{'yes' if report.direct_allocation_consumer else 'no'}",
        f"Indirect Path: {report.indirect_allocation_path}",
        "Candidates With Allocation Change: "
        f"{report.candidates_with_allocation_change}",
        f"Total Target-Weight Change: {_text(report.total_target_weight_change)}",
        f"Gross Exposure Change: {_text(report.gross_exposure_change)}",
        f"Net Exposure Change: {_text(report.net_exposure_change)}",
        f"Explanation: {report.explanation}",
    )


def render_regime_setup_influence(
    rows: tuple[RegimeSetupInfluenceRow, ...],
) -> tuple[str, ...]:
    lines = ["Regime Setup Influence"]
    for row in rows:
        lines.append(
            f"- {row.setup_family}: n={row.sample_count}, "
            f"mean_score_change={_text(row.mean_score_change)}, "
            f"verdict_changes={row.verdict_changes}, approvals={row.approval_changes}, "
            f"avg={_text(row.average_outcome)}, finding={row.finding}"
        )
    return tuple(lines)


def render_regime_asymmetry(report: RegimeAsymmetryReport) -> tuple[str, ...]:
    return (
        "Regime Bullish/Bearish Asymmetry",
        f"Bullish Promotions: {report.bullish_promotions}",
        f"Bullish Promoted Winners: {report.bullish_promoted_winners}",
        f"Bullish Promoted Losers: {report.bullish_promoted_losers}",
        f"Bearish Demotions: {report.bearish_demotions}",
        f"Bearish Demoted Winners: {report.bearish_demoted_winners}",
        f"Bearish Demoted Losers: {report.bearish_demoted_losers}",
        f"Neutral Unchanged: {report.neutral_unchanged}",
        f"Bullish Promotion Precision: {_text(report.precision_of_bullish_promotions)}",
        "Bearish Downside Avoided: "
        f"{_text(report.downside_avoided_by_bearish_demotions)}",
        "Missed Upside From Bearish Demotion: "
        f"{_text(report.missed_upside_from_bearish_demotions)}",
        f"Conclusion: {report.conclusion.value}",
    )


def render_recorded_vs_v2_regime_influence(
    report: RecordedVsV2RegimeInfluenceReport,
) -> tuple[str, ...]:
    return (
        "Recorded vs Diagnostic V2 Regime Influence",
        f"Agreement Count: {report.agreement_count}",
        f"Disagreement Count: {report.disagreement_count}",
        f"Score Differences: {report.score_differences}",
        f"Verdict Differences: {report.verdict_differences}",
        f"Ranking Differences: {report.ranking_differences}",
        f"Approval Differences: {report.approval_differences}",
        f"Allocation Differences: {report.allocation_differences}",
        "Average Outcome On Disagreement: "
        f"{_text(report.average_outcome_on_disagreement)}",
        f"Explanation: {report.explanation}",
    )


def render_regime_context_only(report: RegimeContextOnlyReport) -> tuple[str, ...]:
    return (
        "Regime Context-Only Evaluation",
        "Retained Capabilities: " + ", ".join(report.retained_capabilities),
        "Removed From Decisions: " + ", ".join(report.removed_in_context_only),
        f"Score Unchanged: {'yes' if report.score_unchanged else 'no'}",
        f"Verdict Unchanged: {'yes' if report.verdict_unchanged else 'no'}",
        f"Approval Unchanged: {'yes' if report.approval_unchanged else 'no'}",
        f"Allocation Unchanged: {'yes' if report.allocation_unchanged else 'no'}",
        "Shadow Mode Design: " + "; ".join(report.shadow_mode_design),
    )


def render_regime_safe_deactivation_readiness(
    report: RegimeSafeDeactivationReadinessReport,
) -> tuple[str, ...]:
    secondary = (
        report.secondary_conclusion.value if report.secondary_conclusion else None
    )
    lines = [
        "Regime Safe Deactivation Readiness",
        f"Candidate Records: {report.universe.candidate_records}",
        f"Completed Outcomes: {report.universe.completed_outcomes}",
        f"Direct Regime Consumers: {report.direct_regime_consumers}",
        f"Indirect Regime Consumers: {report.indirect_regime_consumers}",
        f"Display-Only Consumers: {report.display_only_consumers}",
        f"Score Materiality: {report.score_materiality}",
        f"Verdict Changes: {report.verdict_changes}",
        f"Approval Changes: {report.approval_changes}",
        f"Allocation Changes: {report.allocation_changes}",
        f"Primary Conclusion: {report.primary_conclusion.value}",
        f"Secondary Conclusion: {_text(secondary)}",
        f"Recommended Next Milestone: {report.recommended_next_milestone.value}",
        "Preconditions:",
    ]
    lines.extend(
        f"- {name}: {'yes' if satisfied else 'no'}"
        for name, satisfied in report.safe_deactivation_preconditions
    )
    lines.append("Decision Matrix:")
    lines.extend(
        f"- {item}: {status.value}; {reason}"
        for item, status, reason in report.decision_matrix
    )
    lines.append(f"Prohibited Action: {report.prohibited_action}")
    return tuple(lines)


def export_regime_influence_json(payload: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), indent=2), encoding="utf-8")
    return path


def export_regime_influence_csv(rows: tuple[Any, ...], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    dictionaries = [_flatten(_jsonable(row)) for row in rows] or [{"status": "empty"}]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(dictionaries[0].keys()))
        writer.writeheader()
        writer.writerows(dictionaries)
    return path


def _counterfactual(
    record: CandidateDecisionRecord,
    outcome: _Outcome | None,
    v2: _V2Link | None,
) -> _Counterfactual:
    adjustment = _recorded_regime_adjustment(record)
    no_regime = _clamp_score(record.strategy_score - adjustment)
    return _Counterfactual(
        record=record,
        outcome=outcome,
        v2=v2,
        recorded_adjustment=adjustment,
        no_regime_score=no_regime,
        recorded_score=record.strategy_score,
        no_regime_verdict=_verdict_from_score(no_regime),
        recorded_verdict=record.final_verdict,
    )


def _recorded_regime_adjustment(record: CandidateDecisionRecord) -> Decimal:
    stored = _indicator(record, ("regime-adjustment", "regime_adjustment"))
    if stored is not None:
        return stored
    return _regime_adjustment_for(record.market_regime, record.setup_type)


def _regime_adjustment_for(regime: str | None, setup_type: str | None) -> Decimal:
    normalized = _canonical_regime(regime)
    setup = (setup_type or "").upper()
    if normalized == "BULLISH":
        return Decimal("4") if "BREAKOUT" in setup else Decimal("2")
    if normalized == "BEARISH":
        return Decimal("-8")
    if "BREAKOUT" in setup:
        return Decimal("-4")
    if normalized in {"NEUTRAL", "UNKNOWN"}:
        return Decimal("-2")
    return _ZERO


def _canonical_regime(regime: str | None) -> str:
    value = (regime or "").strip().upper()
    if value in {"BULL", "BULLISH", "POSITIVE", "STRONG_POSITIVE"}:
        return "BULLISH"
    if value in {"BEAR", "BEARISH", "NEGATIVE", "STRONG_NEGATIVE", "RISK_OFF"}:
        return "BEARISH"
    if value in {"NEUTRAL", "SIDEWAYS", "RANGE_BOUND"}:
        return "NEUTRAL"
    return "UNKNOWN"


def _verdict_from_score(score: Decimal) -> str:
    if score >= Decimal("90"):
        return "STRONG_BUY"
    if score >= Decimal("75"):
        return "BUY"
    if score >= Decimal("60"):
        return "WATCHLIST"
    if score >= Decimal("40"):
        return "AVOID"
    return "SELL"


def _clamp_score(score: Decimal) -> Decimal:
    return max(_ZERO, min(_HUNDRED, score)).quantize(_TWO, rounding=ROUND_HALF_UP)


def _primary_window(
    outcome: CandidateForwardOutcome | None,
) -> CandidateForwardWindowOutcome | None:
    if outcome is None or not outcome.windows:
        return None
    return next(
        (window for window in outcome.windows if window.window == "20d"),
        outcome.windows[0],
    )


def _outcome_from(window: CandidateForwardWindowOutcome | None) -> _Outcome | None:
    if window is None:
        return None
    forward = window.forward_return_pct_from_entry
    if forward is None:
        forward = window.forward_return_pct_from_close
    if forward is None:
        return None
    return _Outcome(
        forward_return=forward,
        benchmark_relative_return=None,
        mfe=window.max_favourable_excursion_pct,
        mae=window.max_adverse_excursion_pct,
        target_hit=window.target_1_touched,
        stop_hit=window.risk_stop_touched,
    )


def _indicator(
    record: CandidateDecisionRecord,
    keys: tuple[str, ...],
) -> Decimal | None:
    normalized = {
        str(key).replace("_", "-").lower(): value
        for key, value in record.indicator_scores.items()
    }
    for key in keys:
        value = normalized.get(key.replace("_", "-").lower())
        if value is None:
            continue
        try:
            return Decimal(str(value))
        except Exception:
            return None
    return None


def _stage_row(
    stage: str,
    rows: Sequence[_Counterfactual],
    before: Callable[[_Counterfactual], bool],
    after: Callable[[_Counterfactual], bool],
    influence_path: str,
) -> RegimeSelectionInfluenceRow:
    before_ids = {row.record.candidate_id for row in rows if before(row)}
    after_ids = {row.record.candidate_id for row in rows if after(row)}
    added = tuple(
        row for row in rows if row.record.candidate_id in after_ids - before_ids
    )
    removed = tuple(
        row for row in rows if row.record.candidate_id in before_ids - after_ids
    )
    return RegimeSelectionInfluenceRow(
        stage=stage,
        before_regime_intervention=len(before_ids),
        after_regime_intervention=len(after_ids),
        candidates_added=len(added),
        candidates_removed=len(removed),
        winners_added=sum(_is_winner(row) for row in added),
        losers_added=sum(_is_loser(row) for row in added),
        winners_removed=sum(_is_winner(row) for row in removed),
        losers_removed=sum(_is_loser(row) for row in removed),
        influence_path=influence_path,
    )


def _setup_row(
    setup_family: str,
    rows: tuple[_Counterfactual, ...],
    approval_fn: Callable[[_Counterfactual], bool],
) -> RegimeSetupInfluenceRow:
    score_changes = [
        (row.no_regime_score - row.recorded_score).quantize(_FOUR) for row in rows
    ]
    completed = tuple(row for row in rows if row.outcome is not None)
    returns = [
        row.outcome.forward_return
        for row in completed
        if row.outcome is not None and row.outcome.forward_return is not None
    ]
    mfe = [
        row.outcome.mfe
        for row in completed
        if row.outcome is not None and row.outcome.mfe is not None
    ]
    mae = [
        row.outcome.mae
        for row in completed
        if row.outcome is not None and row.outcome.mae is not None
    ]
    verdict_changes = sum(row.recorded_verdict != row.no_regime_verdict for row in rows)
    approval_changes = sum(
        row.record.approved_for_deployment != approval_fn(row) for row in rows
    )
    finding = (
        "REGIME_EFFECT_IS_NEGLIGIBLE"
        if verdict_changes == 0 and approval_changes == 0
        else f"REGIME_EFFECT_CONCENTRATED_IN_{setup_family}"
    )
    return RegimeSetupInfluenceRow(
        setup_family=setup_family,
        sample_count=len(rows),
        mean_score_change=_average(score_changes),
        verdict_changes=verdict_changes,
        approval_changes=approval_changes,
        average_outcome=_average(returns),
        benchmark_relative_outcome=None,
        mfe=_average(mfe),
        mae=_average(mae),
        finding=finding,
    )


def _setup_family(setup_type: str | None) -> str:
    value = (setup_type or "UNKNOWN").upper().replace(" ", "_")
    if "MOMENTUM" in value:
        return "MOMENTUM_CONTINUATION"
    if "BREAKOUT" in value:
        return "BREAKOUT"
    if "RETRACE" in value or "PULLBACK" in value:
        return "RETRACEMENT"
    if "REVERSAL" in value:
        return "REVERSAL"
    return value


def _counts(values: Iterable[str]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(Counter(values).items()))


def _top_ids(
    rows: Sequence[_Counterfactual],
    score_fn: Callable[[_Counterfactual], Decimal],
    descending: bool,
) -> set[str]:
    if not rows:
        return set()
    count = max(1, len(rows) // 10)
    ordered = sorted(rows, key=score_fn, reverse=descending)
    return {row.record.candidate_id for row in ordered[:count]}


def _rank_changes(
    rows: Sequence[_Counterfactual],
    left: Callable[[_Counterfactual], Decimal],
    right: Callable[[_Counterfactual], Decimal],
) -> int:
    left_order = sorted(rows, key=left, reverse=True)
    right_order = sorted(rows, key=right, reverse=True)
    return sum(
        lrow.record.candidate_id != rrow.record.candidate_id
        for lrow, rrow in zip(left_order, right_order, strict=False)
    )


def _rank_displacements(
    rows: Sequence[_Counterfactual],
    left: Callable[[_Counterfactual], Decimal],
    right: Callable[[_Counterfactual], Decimal],
) -> list[Decimal]:
    left_rank = {
        row.record.candidate_id: index
        for index, row in enumerate(sorted(rows, key=left, reverse=True), start=1)
    }
    right_rank = {
        row.record.candidate_id: index
        for index, row in enumerate(sorted(rows, key=right, reverse=True), start=1)
    }
    return [
        Decimal(
            abs(
                left_rank[row.record.candidate_id] - right_rank[row.record.candidate_id]
            )
        )
        for row in rows
    ]


def _near_verdict_boundary(score: Decimal) -> bool:
    return any(abs(score - threshold) <= Decimal("2") for threshold in (40, 60, 75, 90))


def _is_winner(row: _Counterfactual) -> bool:
    return (
        row.outcome is not None
        and row.outcome.forward_return is not None
        and row.outcome.forward_return > 0
    )


def _is_loser(row: _Counterfactual) -> bool:
    return (
        row.outcome is not None
        and row.outcome.forward_return is not None
        and row.outcome.forward_return <= 0
    )


def _verdict_rank(verdict: str) -> int:
    return {
        "SELL": 0,
        "AVOID": 1,
        "WATCHLIST": 2,
        "HOLD": 2,
        "BUY": 3,
        "STRONG_BUY": 4,
    }.get(verdict.upper(), 1)


def _auc(scored: Sequence[tuple[Decimal, _Counterfactual]]) -> Decimal | None:
    positives = [score for score, row in scored if _is_winner(row)]
    negatives = [score for score, row in scored if _is_loser(row)]
    if not positives or not negatives:
        return None
    wins = Decimal("0")
    total = Decimal(len(positives) * len(negatives))
    for pos in positives:
        for neg in negatives:
            if pos > neg:
                wins += Decimal("1")
            elif pos == neg:
                wins += Decimal("0.5")
    return (wins / total).quantize(_FOUR)


def _spearman(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_ranks = _ranks(left)
    right_ranks = _ranks(right)
    return _pearson(left_ranks, right_ranks)


def _ranks(values: Sequence[Decimal]) -> list[Decimal]:
    ordered = sorted((value, index) for index, value in enumerate(values))
    ranks = [Decimal("0")] * len(values)
    for rank, (_, index) in enumerate(ordered, start=1):
        ranks[index] = Decimal(rank)
    return ranks


def _pearson(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal | None:
    if len(left) != len(right) or not left:
        return None
    avg_left = _average(left)
    avg_right = _average(right)
    if avg_left is None or avg_right is None:
        return None
    numerator = sum(
        (lval - avg_left) * (rval - avg_right)
        for lval, rval in zip(left, right, strict=True)
    )
    left_var = sum((value - avg_left) ** 2 for value in left)
    right_var = sum((value - avg_right) ** 2 for value in right)
    if left_var == 0 or right_var == 0:
        return None
    value = float(numerator) / ((float(left_var) * float(right_var)) ** 0.5)
    return Decimal(str(value)).quantize(_FOUR)


def _decile_win_rate(
    scored: Sequence[tuple[Decimal, _Counterfactual]],
    *,
    top: bool,
) -> Decimal | None:
    completed = [(score, row) for score, row in scored if row.outcome is not None]
    if not completed:
        return None
    count = max(1, len(completed) // 10)
    selected = sorted(completed, key=lambda item: item[0], reverse=top)[:count]
    return _ratio(sum(_is_winner(row) for _, row in selected), len(selected))


def _buy_precision(
    scored: Sequence[tuple[Decimal, _Counterfactual]],
) -> Decimal | None:
    buys = [row for _, row in scored if row.recorded_verdict in _POSITIVE_VERDICTS]
    return _ratio(sum(_is_winner(row) for row in buys), len(buys))


def _average(values: Sequence[Decimal | None]) -> Decimal | None:
    cleaned = [value for value in values if value is not None]
    if not cleaned:
        return None
    return (sum(cleaned, _ZERO) / Decimal(len(cleaned))).quantize(_FOUR)


def _median(values: Sequence[Decimal | None]) -> Decimal | None:
    cleaned = sorted(value for value in values if value is not None)
    if not cleaned:
        return None
    middle = len(cleaned) // 2
    if len(cleaned) % 2:
        return cleaned[middle].quantize(_FOUR)
    return ((cleaned[middle - 1] + cleaned[middle]) / Decimal("2")).quantize(_FOUR)


def _ratio(numerator: int | bool, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    return (Decimal(int(numerator)) / Decimal(denominator)).quantize(_FOUR)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _flatten(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        return {"value": value}
    output: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, list | tuple | dict):
            output[key] = json.dumps(item, sort_keys=True)
        else:
            output[key] = item
    return output


def _text(value: object) -> str:
    if value is None:
        return "unavailable"
    return str(value)


__all__ = [
    "RecordedVsV2RegimeInfluenceReport",
    "RegimeAllocationInfluenceReport",
    "RegimeApprovalInfluenceReport",
    "RegimeAsymmetryReport",
    "RegimeContextOnlyReport",
    "RegimeCounterfactualView",
    "RegimeDecisionMatrixStatus",
    "RegimeDependencyRole",
    "RegimeInfluenceConclusion",
    "RegimeInfluenceNextMilestone",
    "RegimeInfluenceUniverse",
    "RegimeInterventionDefinition",
    "RegimeProductionDependency",
    "RegimeProductionInfluenceAuditEngine",
    "RegimeRankingInfluenceRow",
    "RegimeSafeDeactivationReadinessReport",
    "RegimeScoreInfluenceRow",
    "RegimeSelectionInfluenceRow",
    "RegimeSetupInfluenceRow",
    "RegimeVerdictInfluenceRow",
    "export_regime_influence_csv",
    "export_regime_influence_json",
    "render_recorded_vs_v2_regime_influence",
    "render_regime_allocation_influence",
    "render_regime_approval_influence",
    "render_regime_asymmetry",
    "render_regime_context_only",
    "render_regime_production_dependency",
    "render_regime_ranking_influence",
    "render_regime_safe_deactivation_readiness",
    "render_regime_score_influence",
    "render_regime_selection_influence",
    "render_regime_setup_influence",
    "render_regime_verdict_influence",
]
