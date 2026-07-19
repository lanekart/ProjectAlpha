from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from types import MappingProxyType

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_TWO = Decimal("0.01")


class GateDecision(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class OpportunityGrade(StrEnum):
    A_PLUS = "A+"
    A = "A"
    B = "B"
    C = "C"
    REJECT = "Reject"


class RejectionReasonCode(StrEnum):
    WEAK_VERDICT = "WEAK_VERDICT"
    WEAK_CONFIDENCE = "WEAK_CONFIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    POOR_REWARD_RISK = "POOR_REWARD_RISK"
    EXCESS_DOWNSIDE_RISK = "EXCESS_DOWNSIDE_RISK"
    POOR_DATA_COMPLETENESS = "POOR_DATA_COMPLETENESS"
    INSUFFICIENT_CAPACITY = "INSUFFICIENT_CAPACITY"
    LIVE_FEED_UNHEALTHY = "LIVE_FEED_UNHEALTHY"
    WEAK_SETUP = "WEAK_SETUP"
    MISSING_TRADE_PLAN = "MISSING_TRADE_PLAN"
    PENDING_ENTRY_TRIGGER = "PENDING_ENTRY_TRIGGER"
    LATE_ENTRY = "LATE_ENTRY"
    POOR_HISTORICAL_EDGE = "POOR_HISTORICAL_EDGE"


class StressSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class StressDecisionAction(StrEnum):
    KEEP = "keep"
    DOWNGRADE = "downgrade"
    REDUCE_SIZE = "reduce size"
    TIGHTEN_STOP = "tighten stop"
    WIDEN_STOP = "widen stop"
    LOWER_TARGET = "lower target"
    REJECT = "reject"


class StressReasonCode(StrEnum):
    WEAK_EVIDENCE_HIGH_SCORE = "WEAK_EVIDENCE_HIGH_SCORE"
    HIGH_CONFIDENCE_LOW_SAMPLE = "HIGH_CONFIDENCE_LOW_SAMPLE"
    POOR_REWARD_RISK = "POOR_REWARD_RISK"
    BAD_MARKET_REGIME = "BAD_MARKET_REGIME"
    SECTOR_CROWDING = "SECTOR_CROWDING"
    EXCESSIVE_VOLATILITY = "EXCESSIVE_VOLATILITY"
    LOW_CAPACITY = "LOW_CAPACITY"
    STALE_OR_INCOMPLETE_DATA = "STALE_OR_INCOMPLETE_DATA"
    STOP_TOO_CLOSE = "STOP_TOO_CLOSE"
    STOP_TOO_WIDE = "STOP_TOO_WIDE"
    TARGET_TOO_OPTIMISTIC = "TARGET_TOO_OPTIMISTIC"
    CORRELATION_CONCENTRATION = "CORRELATION_CONCENTRATION"
    CONFLICTING_SIGNALS = "CONFLICTING_SIGNALS"
    RECENT_FAILED_SIMILAR_SETUP = "RECENT_FAILED_SIMILAR_SETUP"
    FRAGILE_NEAR_RESISTANCE = "FRAGILE_NEAR_RESISTANCE"
    GAP_RISK = "GAP_RISK"
    BUY_CONTRADICTED_BY_SELL_INDICATORS = "BUY_CONTRADICTED_BY_SELL_INDICATORS"
    INSUFFICIENT_FIVE_YEAR_HISTORY = "INSUFFICIENT_FIVE_YEAR_HISTORY"


class StopQuality(StrEnum):
    GOOD = "good"
    ACCEPTABLE = "acceptable"
    WEAK = "weak"
    INVALID = "invalid"


class TargetQuality(StrEnum):
    GOOD = "good"
    ACCEPTABLE = "acceptable"
    WEAK = "weak"
    INVALID = "invalid"


class FinalDecisionAction(StrEnum):
    ACCEPT = "accept"
    DOWNGRADE = "downgrade"
    REJECT = "reject"


class ExitStrategyType(StrEnum):
    FIXED_TARGET = "fixed target"
    PARTIAL_PROFIT_RUNNER = "partial profit + runner"
    TRAILING_AFTER_TARGET_1 = "trailing stop after target 1"
    TIME_BASED = "time based"
    INVALIDATION = "invalidation"


@dataclass(frozen=True, slots=True)
class RejectionReason:
    code: RejectionReasonCode
    explanation: str

    def __post_init__(self) -> None:
        explanation = self.explanation.strip()
        if not explanation:
            raise ValueError("rejection explanation cannot be empty")
        object.__setattr__(self, "code", RejectionReasonCode(self.code))
        object.__setattr__(self, "explanation", explanation)


@dataclass(frozen=True, slots=True)
class CapacityAssessment:
    capacity_score: Decimal
    deployable_capital_estimate: Decimal | None
    liquidity_warning: str | None
    explanation: str
    data_sufficient: bool

    def __post_init__(self) -> None:
        explanation = self.explanation.strip()
        warning = self.liquidity_warning.strip() if self.liquidity_warning else None
        if not explanation:
            raise ValueError("capacity explanation cannot be empty")
        object.__setattr__(
            self,
            "capacity_score",
            _bounded_score(self.capacity_score, "capacity score"),
        )
        object.__setattr__(
            self,
            "deployable_capital_estimate",
            None
            if self.deployable_capital_estimate is None
            else Decimal(str(self.deployable_capital_estimate)).quantize(_TWO),
        )
        object.__setattr__(self, "liquidity_warning", warning)
        object.__setattr__(self, "explanation", explanation)


@dataclass(frozen=True, slots=True)
class SetupQualityScorecard:
    trend_alignment: Decimal
    price_volume_confirmation: Decimal
    entry_quality: Decimal
    stop_quality: Decimal
    target_realism: Decimal
    reward_risk_quality: Decimal
    historical_evidence: Decimal
    liquidity_capacity: Decimal
    market_regime_fit: Decimal
    total_score: Decimal
    setup_grade: OpportunityGrade
    summary: str

    def __post_init__(self) -> None:
        for field_name in (
            "trend_alignment",
            "price_volume_confirmation",
            "entry_quality",
            "stop_quality",
            "target_realism",
            "reward_risk_quality",
            "historical_evidence",
            "liquidity_capacity",
            "market_regime_fit",
            "total_score",
        ):
            object.__setattr__(
                self,
                field_name,
                _bounded_score(getattr(self, field_name), field_name),
            )
        object.__setattr__(self, "setup_grade", OpportunityGrade(self.setup_grade))
        summary = self.summary.strip()
        if not summary:
            raise ValueError("setup scorecard summary cannot be empty")
        object.__setattr__(self, "summary", summary)

    def as_mapping(self) -> MappingProxyType[str, str]:
        return MappingProxyType(
            {
                "trend_alignment": str(self.trend_alignment),
                "price_volume_confirmation": str(self.price_volume_confirmation),
                "entry_quality": str(self.entry_quality),
                "stop_quality": str(self.stop_quality),
                "target_realism": str(self.target_realism),
                "reward_risk_quality": str(self.reward_risk_quality),
                "historical_evidence": str(self.historical_evidence),
                "liquidity_capacity": str(self.liquidity_capacity),
                "market_regime_fit": str(self.market_regime_fit),
                "total_score": str(self.total_score),
                "setup_grade": self.setup_grade.value,
            }
        )


@dataclass(frozen=True, slots=True)
class InstitutionalCandidate:
    symbol: str
    final_verdict: str
    adjusted_confidence: str
    evidence_strength: str | None
    final_score: Decimal
    reward_risk_ratio: Decimal | None
    stop_distance_percent: Decimal | None
    data_completeness: str
    setup_quality: str
    sector: str
    market_regime: str | None
    sector_fit: Decimal | None
    portfolio_fit: Decimal | None
    posterior_probability: Decimal | None
    expectancy: Decimal | None
    entry: Decimal | None
    stop: Decimal | None
    target_1: Decimal | None
    target_2: Decimal | None
    target_3: Decimal | None
    capacity: CapacityAssessment
    support_level: Decimal | None = None
    swing_low: Decimal | None = None
    dma_20: Decimal | None = None
    atr: Decimal | None = None
    resistance_level: Decimal | None = None
    swing_high: Decimal | None = None
    live_feed_healthy: bool | None = None
    live_risk_warning_count: int = 0
    evidence_sample_count: int | None = None
    recent_similar_failures: int = 0
    conflicting_signal_count: int = 0
    near_resistance: bool = False
    gap_risk: bool = False
    missing_data: tuple[str, ...] = field(default_factory=tuple)
    setup_stage: str = "ENTRY_READY"
    entry_ready: bool = True
    trigger_status: str = "TRIGGER_CONFIRMED"
    execution_status: str = "BUY NOW"
    allocation_eligible: bool = True
    setup_scorecard: SetupQualityScorecard | None = None
    historical_bar_count: int = 1260
    bearish_indicator_count: int = 0
    bearish_indicator_reasons: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("candidate symbol cannot be empty")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "final_verdict", self.final_verdict.strip().upper())
        object.__setattr__(
            self,
            "adjusted_confidence",
            self.adjusted_confidence.strip().upper(),
        )
        object.__setattr__(
            self,
            "final_score",
            _bounded_score(self.final_score, "score"),
        )
        object.__setattr__(
            self,
            "data_completeness",
            self.data_completeness.strip().upper() or "UNKNOWN",
        )
        object.__setattr__(
            self,
            "setup_quality",
            self.setup_quality.strip().upper() or "UNKNOWN",
        )
        object.__setattr__(self, "sector", self.sector.strip().upper() or "UNKNOWN")
        object.__setattr__(
            self,
            "missing_data",
            tuple(item.strip() for item in self.missing_data if item.strip()),
        )
        object.__setattr__(
            self,
            "setup_stage",
            self.setup_stage.strip().upper() or "UNKNOWN",
        )
        object.__setattr__(
            self,
            "trigger_status",
            self.trigger_status.strip().upper() or "UNKNOWN",
        )
        object.__setattr__(
            self,
            "execution_status",
            self.execution_status.strip().upper() or "UNKNOWN",
        )
        if self.live_risk_warning_count < 0:
            raise ValueError("live risk warning count cannot be negative")
        if self.recent_similar_failures < 0:
            raise ValueError("recent similar failures cannot be negative")
        if self.conflicting_signal_count < 0:
            raise ValueError("conflicting signal count cannot be negative")
        if self.historical_bar_count < 0:
            raise ValueError("historical bar count cannot be negative")
        if self.bearish_indicator_count < 0:
            raise ValueError("bearish indicator count cannot be negative")
        object.__setattr__(
            self,
            "bearish_indicator_reasons",
            tuple(
                reason.strip()
                for reason in self.bearish_indicator_reasons
                if reason.strip()
            ),
        )


@dataclass(frozen=True, slots=True)
class StressTestResult:
    passed: bool
    severity: StressSeverity
    reason_code: StressReasonCode
    explanation: str
    suggested_action: StressDecisionAction

    def __post_init__(self) -> None:
        explanation = self.explanation.strip()
        if not explanation:
            raise ValueError("stress test explanation cannot be empty")
        object.__setattr__(self, "severity", StressSeverity(self.severity))
        object.__setattr__(self, "reason_code", StressReasonCode(self.reason_code))
        object.__setattr__(
            self,
            "suggested_action",
            StressDecisionAction(self.suggested_action),
        )
        object.__setattr__(self, "explanation", explanation)


@dataclass(frozen=True, slots=True)
class StopQualityAssessment:
    stop_quality: StopQuality
    recommended_adjustment: str | None
    explanation: str

    def __post_init__(self) -> None:
        explanation = self.explanation.strip()
        adjustment = (
            self.recommended_adjustment.strip() if self.recommended_adjustment else None
        )
        if not explanation:
            raise ValueError("stop quality explanation cannot be empty")
        object.__setattr__(self, "stop_quality", StopQuality(self.stop_quality))
        object.__setattr__(self, "recommended_adjustment", adjustment)
        object.__setattr__(self, "explanation", explanation)


@dataclass(frozen=True, slots=True)
class TargetQualityAssessment:
    target_quality: TargetQuality
    recommended_adjustment: str | None
    explanation: str

    def __post_init__(self) -> None:
        explanation = self.explanation.strip()
        adjustment = (
            self.recommended_adjustment.strip() if self.recommended_adjustment else None
        )
        if not explanation:
            raise ValueError("target quality explanation cannot be empty")
        object.__setattr__(self, "target_quality", TargetQuality(self.target_quality))
        object.__setattr__(self, "recommended_adjustment", adjustment)
        object.__setattr__(self, "explanation", explanation)


@dataclass(frozen=True, slots=True)
class OverconfidenceAssessment:
    base_confidence: str
    adjusted_confidence: str
    reduction_applied: bool
    penalty_points: Decimal
    explanation: str

    def __post_init__(self) -> None:
        explanation = self.explanation.strip()
        if not explanation:
            raise ValueError("overconfidence explanation cannot be empty")
        object.__setattr__(
            self,
            "base_confidence",
            self.base_confidence.strip().upper(),
        )
        object.__setattr__(
            self,
            "adjusted_confidence",
            self.adjusted_confidence.strip().upper(),
        )
        object.__setattr__(
            self,
            "penalty_points",
            _bounded_score(self.penalty_points, "overconfidence penalty"),
        )
        object.__setattr__(self, "explanation", explanation)


@dataclass(frozen=True, slots=True)
class DecisionQualityAssessment:
    decision_quality_score: Decimal
    decision_quality_grade: OpportunityGrade
    final_action: FinalDecisionAction
    top_risk_warnings: tuple[str, ...]
    stress_penalty: Decimal
    stop_quality: StopQualityAssessment
    target_quality: TargetQualityAssessment
    overconfidence: OverconfidenceAssessment

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "decision_quality_score",
            _bounded_score(self.decision_quality_score, "decision quality score"),
        )
        object.__setattr__(
            self,
            "decision_quality_grade",
            OpportunityGrade(self.decision_quality_grade),
        )
        object.__setattr__(
            self,
            "final_action",
            FinalDecisionAction(self.final_action),
        )
        object.__setattr__(
            self,
            "top_risk_warnings",
            tuple(
                warning.strip() for warning in self.top_risk_warnings if warning.strip()
            )[:3],
        )


@dataclass(frozen=True, slots=True)
class StopCandidate:
    name: str
    level: Decimal | None
    risk_percent: Decimal | None
    atr_multiple: Decimal | None
    reward_risk: Decimal | None
    quality: StopQuality
    accepted: bool
    explanation: str


@dataclass(frozen=True, slots=True)
class TargetCandidate:
    name: str
    targets: tuple[Decimal, ...]
    reward_risk: Decimal | None
    atr_multiple: Decimal | None
    quality: TargetQuality
    accepted: bool
    explanation: str


@dataclass(frozen=True, slots=True)
class PartialProfitPlan:
    target_1_exit_percent: Decimal
    move_stop_to_breakeven: bool
    runner_targets: tuple[Decimal, ...]
    trailing_stop_after_target_1: bool
    explanation: str


@dataclass(frozen=True, slots=True)
class ExitStrategyAssessment:
    strategy_type: ExitStrategyType
    expected_r: Decimal | None
    estimated_win_rate: Decimal | None
    downside_exposure: Decimal | None
    average_holding_period: Decimal | None
    evidence_sample_count: int | None
    uncertainty_penalty: Decimal
    selected: bool
    explanation: str


@dataclass(frozen=True, slots=True)
class OptimizedTradePlan:
    entry: Decimal
    selected_stop: Decimal
    selected_targets: tuple[Decimal, ...]
    selected_exit_strategy: ExitStrategyType
    reward_risk: Decimal
    partial_profit_plan: PartialProfitPlan | None
    trailing_stop_rule: str | None
    explanation: str


@dataclass(frozen=True, slots=True)
class TradePlanQualityAssessment:
    trade_plan_quality_score: Decimal
    trade_plan_grade: OpportunityGrade
    final_action: FinalDecisionAction
    final_selected_plan: OptimizedTradePlan | None
    stop_quality: StopQuality
    stop_confidence: Decimal
    target_quality: TargetQuality
    target_confidence: Decimal
    weaknesses: tuple[str, ...]
    rejected_stop_candidates: tuple[StopCandidate, ...]
    rejected_target_candidates: tuple[TargetCandidate, ...]
    exit_strategy_comparison: tuple[ExitStrategyAssessment, ...]
    quality_breakdown: MappingProxyType[str, str]


@dataclass(frozen=True, slots=True)
class OpportunityScoreBreakdown:
    posterior_probability: Decimal | None
    expectancy: Decimal | None
    reward_risk: Decimal | None
    stop_distance: Decimal | None
    data_completeness: Decimal
    capacity: Decimal
    market_regime_fit: Decimal
    sector_fit: Decimal
    portfolio_fit: Decimal
    live_risk: Decimal
    total_score: Decimal

    def as_mapping(self) -> MappingProxyType[str, str]:
        return MappingProxyType(
            {
                "posterior_probability": _score_text(self.posterior_probability),
                "expectancy": _score_text(self.expectancy),
                "reward_risk": _score_text(self.reward_risk),
                "stop_distance": _score_text(self.stop_distance),
                "data_completeness": str(self.data_completeness),
                "capacity": str(self.capacity),
                "market_regime_fit": str(self.market_regime_fit),
                "sector_fit": str(self.sector_fit),
                "portfolio_fit": str(self.portfolio_fit),
                "live_risk": str(self.live_risk),
                "total_score": str(self.total_score),
            }
        )


@dataclass(frozen=True, slots=True)
class OpportunityDecision:
    candidate: InstitutionalCandidate
    gate_decision: GateDecision
    rejection_reasons: tuple[RejectionReason, ...]
    opportunity_score: Decimal
    opportunity_grade: OpportunityGrade
    score_breakdown: OpportunityScoreBreakdown
    primary_strength: str
    primary_weakness: str
    selection_reason: str
    portfolio_penalty: Decimal
    stress_tests: tuple[StressTestResult, ...] = ()
    decision_quality: DecisionQualityAssessment | None = None
    trade_plan_quality: TradePlanQualityAssessment | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "gate_decision", GateDecision(self.gate_decision))
        object.__setattr__(
            self,
            "opportunity_score",
            _bounded_score(self.opportunity_score, "opportunity score"),
        )
        object.__setattr__(
            self,
            "opportunity_grade",
            OpportunityGrade(self.opportunity_grade),
        )
        object.__setattr__(self, "rejection_reasons", tuple(self.rejection_reasons))

    @property
    def accepted(self) -> bool:
        if self.gate_decision is not GateDecision.ACCEPT:
            return False
        if self.decision_quality is None:
            return True
        if self.decision_quality.final_action is not FinalDecisionAction.ACCEPT:
            return False
        if self.trade_plan_quality is None:
            return True
        return self.trade_plan_quality.final_action is FinalDecisionAction.ACCEPT

    @property
    def downgraded(self) -> bool:
        return (
            self.decision_quality is not None
            and self.decision_quality.final_action is FinalDecisionAction.DOWNGRADE
        )


@dataclass(frozen=True, slots=True)
class InstitutionalDecisionReport:
    decisions: tuple[OpportunityDecision, ...]
    candidates_scanned: int
    accepted_opportunities: tuple[OpportunityDecision, ...]
    rejected_opportunities: tuple[OpportunityDecision, ...]
    acceptance_rate: Decimal
    average_opportunity_score: Decimal | None
    concentration_warnings: tuple[str, ...]
    evidence_quality_summary: str
    no_trade_reason: str | None


@dataclass(frozen=True, slots=True)
class DecisionAuditReport:
    candidates_scanned: int
    institutional_accepted_before_stress: int
    final_accepted_after_stress: int
    downgraded: int
    rejected_by_stress: int
    top_failure_modes: tuple[tuple[StressReasonCode, int], ...]
    average_decision_quality_score: Decimal | None
    stop_quality_distribution: MappingProxyType[str, int]
    target_quality_distribution: MappingProxyType[str, int]
    overconfidence_reductions: int
    no_trade_explanation: str | None


@dataclass(frozen=True, slots=True)
class TradePlanAuditReport:
    accepted_opportunities_reviewed: int
    optimized_plans: int
    rejected_due_to_weak_trade_plan: int
    average_trade_plan_quality_score: Decimal | None
    stop_quality_distribution: MappingProxyType[str, int]
    target_quality_distribution: MappingProxyType[str, int]
    selected_exit_strategy_distribution: MappingProxyType[str, int]
    common_trade_plan_weaknesses: tuple[tuple[str, int], ...]


def opportunity_grade(score: Decimal, *, accepted: bool) -> OpportunityGrade:
    if not accepted:
        return OpportunityGrade.REJECT
    if score >= Decimal("90"):
        return OpportunityGrade.A_PLUS
    if score >= Decimal("80"):
        return OpportunityGrade.A
    if score >= Decimal("70"):
        return OpportunityGrade.B
    return OpportunityGrade.C


def _bounded_score(value: Decimal, label: str) -> Decimal:
    normalized = Decimal(str(value))
    if normalized < _ZERO or normalized > _HUNDRED:
        raise ValueError(f"{label} must be between 0 and 100")
    return normalized.quantize(_TWO, rounding=ROUND_HALF_UP)


def _score_text(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


__all__ = [
    "CapacityAssessment",
    "DecisionAuditReport",
    "DecisionQualityAssessment",
    "FinalDecisionAction",
    "ExitStrategyAssessment",
    "ExitStrategyType",
    "GateDecision",
    "InstitutionalCandidate",
    "InstitutionalDecisionReport",
    "OpportunityDecision",
    "OpportunityGrade",
    "OpportunityScoreBreakdown",
    "OverconfidenceAssessment",
    "OptimizedTradePlan",
    "PartialProfitPlan",
    "RejectionReason",
    "RejectionReasonCode",
    "SetupQualityScorecard",
    "StopCandidate",
    "StopQuality",
    "StopQualityAssessment",
    "StressDecisionAction",
    "StressReasonCode",
    "StressSeverity",
    "StressTestResult",
    "TargetQuality",
    "TargetQualityAssessment",
    "TargetCandidate",
    "TradePlanAuditReport",
    "TradePlanQualityAssessment",
    "opportunity_grade",
]
