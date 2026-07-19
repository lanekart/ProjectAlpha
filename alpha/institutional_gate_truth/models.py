from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

PRODUCTION_INFLUENCE = False
NO_GATE_CHANGES = True
NO_WEIGHT_CHANGES = True
NO_THRESHOLD_CHANGES = True
NO_FEATURE_CHANGES = True
IGTA_VERSION = "IGTA_v1.0"
BASELINE_ID = "ALPHA_BASELINE_v1.0"
DEFAULT_OUTPUT = ".alpha/gate_truth/IGTA_v1.0"


class RejectionClassification(StrEnum):
    CORRECT_REJECTION = "CORRECT_REJECTION"
    FALSE_REJECTION = "FALSE_REJECTION"
    MARGINAL = "MARGINAL"
    DATA_UNCERTAIN = "DATA_UNCERTAIN"


class ConclusionConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class GateTruthConclusion(StrEnum):
    GATE_PROTECTS_CAPITAL = "GATE_PROTECTS_CAPITAL"
    GATE_SUPPRESSES_EDGE = "GATE_SUPPRESSES_EDGE"
    MIXED_EVIDENCE = "MIXED_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True, slots=True)
class RejectionCandidate:
    candidate_id: str
    observed_on: date
    symbol: str
    final_signal: str
    candidate_score: Decimal
    confidence: str
    setup: str
    timing: str
    trade_plan_status: str
    rejection_reason: str
    rejection_reasons: tuple[str, ...]
    rejection_categories: tuple[str, ...]
    component_scores: Mapping[str, str]
    entry_price: Decimal | None
    prospective_stop: Decimal | None
    prospective_target: Decimal | None
    expected_reward_risk: Decimal | None
    expected_return: Decimal | None
    holding_period_sessions: int
    sector: str
    liquidity_bucket: str
    rank: int

    def __post_init__(self) -> None:
        if self.final_signal not in {"BUY", "STRONG_BUY"}:
            raise ValueError("IGTA population only accepts rejected BUY signals")
        if self.holding_period_sessions < 1:
            raise ValueError("holding period must be positive")
        symbol = self.symbol.strip().upper()
        if not symbol or not self.candidate_id.strip():
            raise ValueError("rejection candidate requires identity")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "rejection_reasons", tuple(self.rejection_reasons))
        object.__setattr__(
            self, "rejection_categories", tuple(self.rejection_categories)
        )
        object.__setattr__(
            self,
            "component_scores",
            MappingProxyType(dict(sorted(self.component_scores.items()))),
        )

    @property
    def trade_plan_valid(self) -> bool:
        return (
            self.entry_price is not None
            and self.prospective_stop is not None
            and self.prospective_target is not None
            and self.prospective_stop > 0
            and self.prospective_stop < self.entry_price < self.prospective_target
        )


@dataclass(frozen=True, slots=True)
class HorizonOutcome:
    horizon_sessions: int
    available_sessions: int
    holding_sessions: int
    complete: bool
    entered: bool
    entry_date: date | None
    execution_price: Decimal | None
    exit_date: date | None
    exit_price: Decimal | None
    exit_reason: str
    target_reached: bool | None
    stop_reached: bool | None
    stop_before_target: bool | None
    maximum_favourable_excursion_percent: Decimal | None
    maximum_adverse_excursion_percent: Decimal | None
    gross_return_percent: Decimal | None
    net_return_percent: Decimal | None
    realized_r: Decimal | None
    positive_after_costs: bool | None
    ambiguity_count: int = 0

    def __post_init__(self) -> None:
        if (
            self.horizon_sessions < 1
            or self.available_sessions < 0
            or self.holding_sessions < 0
        ):
            raise ValueError("outcome sessions are invalid")
        if self.available_sessions > self.horizon_sessions:
            raise ValueError("available sessions cannot exceed the horizon")
        if self.holding_sessions > self.available_sessions:
            raise ValueError("holding sessions cannot exceed available sessions")


@dataclass(frozen=True, slots=True)
class RejectionAssessment:
    candidate: RejectionCandidate
    classification: RejectionClassification
    classification_reason: str
    planned_outcome: HorizonOutcome
    horizon_20d: HorizonOutcome
    horizon_60d: HorizonOutcome
    horizon_120d: HorizonOutcome
    primary_component: str


@dataclass(frozen=True, slots=True)
class ReasonStatistic:
    reason_scope: str
    rejection_reason: str
    rejected: int
    correct: int
    false: int
    marginal: int
    data_uncertain: int
    evaluable: int
    rejection_accuracy_percent: Decimal | None
    false_rejection_rate_percent: Decimal | None
    average_return_percent: Decimal | None
    average_missed_return_percent: Decimal | None
    average_avoided_loss_percent: Decimal | None
    opportunity_value_lost: Decimal
    capital_protection_gained: Decimal


@dataclass(frozen=True, slots=True)
class ComponentAttribution:
    component: str
    false_rejections: int
    false_rejection_share_percent: Decimal | None


@dataclass(frozen=True, slots=True)
class GateEffectiveness:
    rejected_population: int
    correct_rejections: int
    false_rejections: int
    marginal_rejections: int
    data_uncertain_rejections: int
    evaluable_rejections: int
    overall_rejection_accuracy_percent: Decimal | None
    overall_false_rejection_rate_percent: Decimal | None
    expected_value_preserved: Decimal
    expected_value_lost: Decimal
    average_missed_return_percent: Decimal | None
    average_avoided_loss_percent: Decimal | None
    opportunity_value_lost: Decimal
    capital_protection_gained: Decimal
    opportunity_capture_lost_percent: Decimal | None
    confidence: ConclusionConfidence
    confidence_reason: str
    conclusion: GateTruthConclusion
    primary_recommendation: str


@dataclass(frozen=True, slots=True)
class CounterfactualTrade:
    candidate_id: str
    symbol: str
    signal_date: date
    entry_date: date
    exit_date: date
    entry_price: Decimal
    exit_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    net_return_percent: Decimal
    realized_r: Decimal
    holding_sessions: int
    exit_reason: str


@dataclass(frozen=True, slots=True)
class CounterfactualCurvePoint:
    observed_on: date
    portfolio_value: Decimal
    daily_return_percent: Decimal
    drawdown_percent: Decimal
    active_trades: int


@dataclass(frozen=True, slots=True)
class CounterfactualStatistics:
    starting_capital: Decimal
    ending_capital: Decimal
    rejected_signals: int
    entered_trades: int
    not_entered: int
    completed_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate_percent: Decimal | None
    average_winner_percent: Decimal | None
    average_loser_percent: Decimal | None
    payoff_ratio: Decimal | None
    expectancy_percent: Decimal | None
    cagr_percent: Decimal | None
    maximum_drawdown_percent: Decimal | None
    sharpe_ratio: Decimal | None
    sortino_ratio: Decimal | None
    unresolved_trades: int
    methodology: str


@dataclass(frozen=True, slots=True)
class IGTAManifest:
    audit_version: str
    baseline_id: str
    baseline_manifest_hash: str
    source_commit: str
    warehouse_version: str
    warehouse_hash: str
    candidate_version: str
    candidate_hash: str
    feature_version: str
    feature_hash: str
    approval_policy_version: str
    approval_policy_hash: str
    trade_plan_version: str
    trade_plan_hash: str
    replay_start: date
    replay_end: date
    transaction_cost_percent: Decimal
    slippage_percent: Decimal
    entry_validity_sessions: int
    horizons: tuple[int, ...]
    source_hashes: Mapping[str, str]
    artifact_hashes: Mapping[str, str] = field(default_factory=dict)
    production_influence: bool = PRODUCTION_INFLUENCE
    no_gate_changes: bool = NO_GATE_CHANGES
    no_weight_changes: bool = NO_WEIGHT_CHANGES
    no_threshold_changes: bool = NO_THRESHOLD_CHANGES
    no_feature_changes: bool = NO_FEATURE_CHANGES

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("IGTA must never influence production")
        if not all(
            (
                self.no_gate_changes,
                self.no_weight_changes,
                self.no_threshold_changes,
                self.no_feature_changes,
            )
        ):
            raise ValueError("IGTA guardrails cannot be disabled")
        object.__setattr__(
            self,
            "source_hashes",
            MappingProxyType(dict(sorted(self.source_hashes.items()))),
        )
        object.__setattr__(
            self,
            "artifact_hashes",
            MappingProxyType(dict(sorted(self.artifact_hashes.items()))),
        )
        object.__setattr__(self, "horizons", tuple(self.horizons))


@dataclass(frozen=True, slots=True)
class InstitutionalGateTruthReport:
    manifest: IGTAManifest
    assessments: tuple[RejectionAssessment, ...]
    reason_statistics: tuple[ReasonStatistic, ...]
    component_attribution: tuple[ComponentAttribution, ...]
    effectiveness: GateEffectiveness
    counterfactual_trades: tuple[CounterfactualTrade, ...]
    counterfactual_curve: tuple[CounterfactualCurvePoint, ...]
    counterfactual_statistics: CounterfactualStatistics


__all__ = [
    "BASELINE_ID",
    "DEFAULT_OUTPUT",
    "IGTA_VERSION",
    "NO_FEATURE_CHANGES",
    "NO_GATE_CHANGES",
    "NO_THRESHOLD_CHANGES",
    "NO_WEIGHT_CHANGES",
    "PRODUCTION_INFLUENCE",
    "ComponentAttribution",
    "ConclusionConfidence",
    "CounterfactualCurvePoint",
    "CounterfactualStatistics",
    "CounterfactualTrade",
    "GateEffectiveness",
    "GateTruthConclusion",
    "HorizonOutcome",
    "IGTAManifest",
    "InstitutionalGateTruthReport",
    "ReasonStatistic",
    "RejectionAssessment",
    "RejectionCandidate",
    "RejectionClassification",
]
