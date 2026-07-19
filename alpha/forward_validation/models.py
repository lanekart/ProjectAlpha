from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any

PRODUCTION_INFLUENCE = False
FORWARD_VALIDATION_SCHEMA_VERSION = "1.0"
CURRENT_POLICY_VERSION = "APPROVAL_POLICY_V1"


class PolicyStage(StrEnum):
    CURRENT = "CURRENT"
    GENERATED = "GENERATED"
    TRAINING_PASSED = "TRAINING_PASSED"
    VALIDATION_PASSED = "VALIDATION_PASSED"
    HOLDOUT_PASSED = "HOLDOUT_PASSED"
    FORWARD_VALIDATION = "FORWARD_VALIDATION"
    CANDIDATE_FOR_DEPLOYMENT = "CANDIDATE_FOR_DEPLOYMENT"
    REJECTED = "REJECTED"


class DeploymentReadiness(StrEnum):
    NOT_READY = "NOT_READY"
    FORWARD_VALIDATION = "FORWARD_VALIDATION"
    LIMITED_CAPITAL = "LIMITED_CAPITAL"
    PRODUCTION_READY = "PRODUCTION_READY"


class OptimizationRecommendation(StrEnum):
    KEEP_POLICY_V1 = "KEEP_POLICY_V1"
    DEPLOY_POLICY_V2_TO_FORWARD_VALIDATION = "DEPLOY_POLICY_V2_TO_FORWARD_VALIDATION"
    DEPLOY_POLICY_V3_TO_FORWARD_VALIDATION = "DEPLOY_POLICY_V3_TO_FORWARD_VALIDATION"
    NO_VALID_POLICY_FOUND = "NO_VALID_POLICY_FOUND"


class PositionStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXITED = "EXITED"
    MISSED = "MISSED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    RISK_BLOCKED = "RISK_BLOCKED"


class PositionEventType(StrEnum):
    ENTRY = "ENTRY"
    ENTRY_MISSED = "ENTRY_MISSED"
    MARK = "MARK"
    STOP_HIT = "STOP_HIT"
    TARGET_1_HIT = "TARGET_1_HIT"
    TARGET_2_HIT = "TARGET_2_HIT"
    TARGET_3_HIT = "TARGET_3_HIT"
    TRAILING_STOP_HIT = "TRAILING_STOP_HIT"
    TIME_EXIT = "TIME_EXIT"
    MANUAL_EXPIRY = "MANUAL_EXPIRY"
    INVALIDATED = "INVALIDATED"
    RISK_BLOCKED = "RISK_BLOCKED"


class StopAuditClassification(StrEnum):
    VALID_POLICY = "VALID_POLICY"
    OVER_RESTRICTIVE = "OVER_RESTRICTIVE"
    UNIT_DEFECT = "UNIT_DEFECT"
    SCALE_DEFECT = "SCALE_DEFECT"
    DATA_DEFECT = "DATA_DEFECT"
    UNKNOWN = "UNKNOWN"


class CounterfactualOperation(StrEnum):
    REMOVE = "REMOVE"
    RELAX = "RELAX"
    TIGHTEN = "TIGHTEN"
    REORDER = "REORDER"
    MERGE = "MERGE"
    REPLACE = "REPLACE"


class ValidationSplit(StrEnum):
    TRAINING = "TRAINING"
    VALIDATION = "VALIDATION"
    HOLDOUT = "HOLDOUT"
    FROZEN_FORWARD = "FROZEN_FORWARD"


@dataclass(frozen=True, slots=True)
class PolicyVersion:
    value: str

    def __post_init__(self) -> None:
        value = self.value.strip().upper()
        if not value.startswith("APPROVAL_POLICY_V"):
            raise ValueError("policy version must use APPROVAL_POLICY_V<n>")
        suffix = value.removeprefix("APPROVAL_POLICY_V")
        if not suffix.isdigit() or int(suffix) <= 0:
            raise ValueError("policy version number must be positive")
        object.__setattr__(self, "value", value)

    @property
    def number(self) -> int:
        return int(self.value.removeprefix("APPROVAL_POLICY_V"))


@dataclass(frozen=True, slots=True)
class ForwardRiskControls:
    maximum_simultaneous_positions: int | None = None
    maximum_allocation_per_position_pct: Decimal | None = None
    maximum_sector_allocation_pct: Decimal | None = None
    daily_loss_limit_pct: Decimal | None = None
    portfolio_drawdown_limit_pct: Decimal | None = None

    def __post_init__(self) -> None:
        if (
            self.maximum_simultaneous_positions is not None
            and self.maximum_simultaneous_positions <= 0
        ):
            raise ValueError("maximum simultaneous positions must be positive")
        for value in (
            self.maximum_allocation_per_position_pct,
            self.maximum_sector_allocation_pct,
            self.daily_loss_limit_pct,
            self.portfolio_drawdown_limit_pct,
        ):
            if value is not None and value <= Decimal("0"):
                raise ValueError("percentage risk controls must be positive")

    def as_dict(self) -> dict[str, object]:
        return {
            "maximum_simultaneous_positions": self.maximum_simultaneous_positions,
            "maximum_allocation_per_position_pct": _text(
                self.maximum_allocation_per_position_pct
            ),
            "maximum_sector_allocation_pct": _text(self.maximum_sector_allocation_pct),
            "daily_loss_limit_pct": _text(self.daily_loss_limit_pct),
            "portfolio_drawdown_limit_pct": _text(self.portfolio_drawdown_limit_pct),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ForwardRiskControls:
        return cls(
            maximum_simultaneous_positions=_optional_int(
                payload.get("maximum_simultaneous_positions")
            ),
            maximum_allocation_per_position_pct=_decimal(
                payload.get("maximum_allocation_per_position_pct")
            ),
            maximum_sector_allocation_pct=_decimal(
                payload.get("maximum_sector_allocation_pct")
            ),
            daily_loss_limit_pct=_decimal(payload.get("daily_loss_limit_pct")),
            portfolio_drawdown_limit_pct=_decimal(
                payload.get("portfolio_drawdown_limit_pct")
            ),
        )


@dataclass(frozen=True, slots=True)
class ForwardValidationConfig:
    started_at: datetime
    initial_capital: Decimal
    policy_version: PolicyVersion
    risk_controls: ForwardRiskControls = field(default_factory=ForwardRiskControls)
    schema_version: str = FORWARD_VALIDATION_SCHEMA_VERSION
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "started_at", _utc(self.started_at))
        if self.initial_capital <= Decimal("0"):
            raise ValueError("initial capital must be positive")
        if self.production_influence:
            raise ValueError("forward validation cannot influence production")

    def as_dict(self) -> dict[str, object]:
        return {
            "started_at": self.started_at.isoformat(),
            "initial_capital": str(self.initial_capital),
            "policy_version": self.policy_version.value,
            "risk_controls": self.risk_controls.as_dict(),
            "schema_version": self.schema_version,
            "production_influence": self.production_influence,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ForwardValidationConfig:
        controls = payload.get("risk_controls", {})
        return cls(
            started_at=datetime.fromisoformat(str(payload["started_at"])),
            initial_capital=Decimal(str(payload["initial_capital"])),
            policy_version=PolicyVersion(str(payload["policy_version"])),
            risk_controls=ForwardRiskControls.from_dict(
                controls if isinstance(controls, dict) else {}
            ),
            schema_version=str(
                payload.get("schema_version", FORWARD_VALIDATION_SCHEMA_VERSION)
            ),
            production_influence=bool(payload.get("production_influence", False)),
        )


@dataclass(frozen=True, slots=True)
class RecommendationSnapshot:
    recommendation_id: str
    generated_at: datetime
    source_run_id: str
    symbol: str
    current_market_price: Decimal | None
    final_verdict: str
    recommendation_score: Decimal
    confidence: str
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    confirmation_entry: Decimal | None
    trigger_style: str | None
    trigger_status: str | None
    stop_loss: Decimal | None
    target_1: Decimal | None
    target_2: Decimal | None
    target_3: Decimal | None
    holding_period: str | None
    maximum_holding_days: int | None
    risk_reward: Decimal | None
    atr_value: Decimal | None
    dma_20: Decimal | None
    trailing_stop_strategy: str | None
    invalidation_level: Decimal | None
    market_regime: str | None
    sector: str | None
    engine_version: str
    data_version: str
    policy_version: PolicyVersion
    approved_deployment: Decimal | None
    diagnostics: dict[str, Any]
    evidence_hashes: dict[str, str]
    snapshot_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "generated_at", _utc(self.generated_at))
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(
            self,
            "diagnostics",
            MappingProxyType(dict(sorted(self.diagnostics.items()))),
        )
        object.__setattr__(
            self,
            "evidence_hashes",
            MappingProxyType(dict(sorted(self.evidence_hashes.items()))),
        )
        if not self.recommendation_id or not self.symbol or not self.snapshot_hash:
            raise ValueError("snapshot identity, symbol, and hash are required")
        if self.approved_deployment is not None and self.approved_deployment < 0:
            raise ValueError("approved deployment cannot be negative")

    def as_dict(self, *, include_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "recommendation_id": self.recommendation_id,
            "generated_at": self.generated_at.isoformat(),
            "source_run_id": self.source_run_id,
            "symbol": self.symbol,
            "current_market_price": _text(self.current_market_price),
            "final_verdict": self.final_verdict,
            "recommendation_score": str(self.recommendation_score),
            "confidence": self.confidence,
            "entry_zone_low": _text(self.entry_zone_low),
            "entry_zone_high": _text(self.entry_zone_high),
            "confirmation_entry": _text(self.confirmation_entry),
            "trigger_style": self.trigger_style,
            "trigger_status": self.trigger_status,
            "stop_loss": _text(self.stop_loss),
            "target_1": _text(self.target_1),
            "target_2": _text(self.target_2),
            "target_3": _text(self.target_3),
            "holding_period": self.holding_period,
            "maximum_holding_days": self.maximum_holding_days,
            "risk_reward": _text(self.risk_reward),
            "atr_value": _text(self.atr_value),
            "dma_20": _text(self.dma_20),
            "trailing_stop_strategy": self.trailing_stop_strategy,
            "invalidation_level": _text(self.invalidation_level),
            "market_regime": self.market_regime,
            "sector": self.sector,
            "engine_version": self.engine_version,
            "data_version": self.data_version,
            "policy_version": self.policy_version.value,
            "approved_deployment": _text(self.approved_deployment),
            "diagnostics": dict(self.diagnostics),
            "evidence_hashes": dict(self.evidence_hashes),
        }
        if include_hash:
            payload["snapshot_hash"] = self.snapshot_hash
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RecommendationSnapshot:
        diagnostics = payload.get("diagnostics", {})
        evidence_hashes = payload.get("evidence_hashes", {})
        return cls(
            recommendation_id=str(payload["recommendation_id"]),
            generated_at=datetime.fromisoformat(str(payload["generated_at"])),
            source_run_id=str(payload["source_run_id"]),
            symbol=str(payload["symbol"]),
            current_market_price=_decimal(payload.get("current_market_price")),
            final_verdict=str(payload["final_verdict"]),
            recommendation_score=Decimal(str(payload["recommendation_score"])),
            confidence=str(payload["confidence"]),
            entry_zone_low=_decimal(payload.get("entry_zone_low")),
            entry_zone_high=_decimal(payload.get("entry_zone_high")),
            confirmation_entry=_decimal(payload.get("confirmation_entry")),
            trigger_style=_optional_text(payload.get("trigger_style")),
            trigger_status=_optional_text(payload.get("trigger_status")),
            stop_loss=_decimal(payload.get("stop_loss")),
            target_1=_decimal(payload.get("target_1")),
            target_2=_decimal(payload.get("target_2")),
            target_3=_decimal(payload.get("target_3")),
            holding_period=_optional_text(payload.get("holding_period")),
            maximum_holding_days=_optional_int(payload.get("maximum_holding_days")),
            risk_reward=_decimal(payload.get("risk_reward")),
            atr_value=_decimal(payload.get("atr_value")),
            dma_20=_decimal(payload.get("dma_20")),
            trailing_stop_strategy=_optional_text(
                payload.get("trailing_stop_strategy")
            ),
            invalidation_level=_decimal(payload.get("invalidation_level")),
            market_regime=_optional_text(payload.get("market_regime")),
            sector=_optional_text(payload.get("sector")),
            engine_version=str(payload["engine_version"]),
            data_version=str(payload["data_version"]),
            policy_version=PolicyVersion(str(payload["policy_version"])),
            approved_deployment=_decimal(payload.get("approved_deployment")),
            diagnostics=(dict(diagnostics) if isinstance(diagnostics, dict) else {}),
            evidence_hashes=(
                {str(key): str(value) for key, value in evidence_hashes.items()}
                if isinstance(evidence_hashes, dict)
                else {}
            ),
            snapshot_hash=str(payload["snapshot_hash"]),
        )


@dataclass(frozen=True, slots=True)
class PositionEventDraft:
    recommendation_id: str
    symbol: str
    occurred_at: datetime
    event_type: PositionEventType
    price: Decimal | None = None
    quantity: Decimal | None = None
    cash_delta: Decimal = Decimal("0")
    reason: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "occurred_at", _utc(self.occurred_at))
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(sorted(self.metadata.items()))),
        )


@dataclass(frozen=True, slots=True)
class PositionEvent:
    sequence: int
    event_id: str
    recommendation_id: str
    symbol: str
    occurred_at: datetime
    event_type: PositionEventType
    price: Decimal | None
    quantity: Decimal | None
    cash_delta: Decimal
    reason: str
    metadata: dict[str, str]
    previous_hash: str
    event_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "occurred_at", _utc(self.occurred_at))
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(sorted(self.metadata.items()))),
        )

    def as_dict(self, *, include_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "sequence": self.sequence,
            "event_id": self.event_id,
            "recommendation_id": self.recommendation_id,
            "symbol": self.symbol,
            "occurred_at": self.occurred_at.isoformat(),
            "event_type": self.event_type.value,
            "price": _text(self.price),
            "quantity": _text(self.quantity),
            "cash_delta": str(self.cash_delta),
            "reason": self.reason,
            "metadata": dict(self.metadata),
            "previous_hash": self.previous_hash,
        }
        if include_hash:
            payload["event_hash"] = self.event_hash
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PositionEvent:
        metadata = payload.get("metadata", {})
        return cls(
            sequence=int(payload["sequence"]),
            event_id=str(payload["event_id"]),
            recommendation_id=str(payload["recommendation_id"]),
            symbol=str(payload["symbol"]),
            occurred_at=datetime.fromisoformat(str(payload["occurred_at"])),
            event_type=PositionEventType(str(payload["event_type"])),
            price=_decimal(payload.get("price")),
            quantity=_decimal(payload.get("quantity")),
            cash_delta=Decimal(str(payload["cash_delta"])),
            reason=str(payload.get("reason", "")),
            metadata=(
                {str(key): str(value) for key, value in metadata.items()}
                if isinstance(metadata, dict)
                else {}
            ),
            previous_hash=str(payload.get("previous_hash", "")),
            event_hash=str(payload["event_hash"]),
        )


@dataclass(frozen=True, slots=True)
class PortfolioValuation:
    valued_at: datetime
    policy_version: PolicyVersion
    cash: Decimal
    invested_value: Decimal
    portfolio_value: Decimal
    realized_profit_loss: Decimal
    unrealized_profit_loss: Decimal
    capital_utilization_pct: Decimal
    event_head_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "valued_at", _utc(self.valued_at))

    def as_dict(self) -> dict[str, object]:
        return {
            "valued_at": self.valued_at.isoformat(),
            "policy_version": self.policy_version.value,
            "cash": str(self.cash),
            "invested_value": str(self.invested_value),
            "portfolio_value": str(self.portfolio_value),
            "realized_profit_loss": str(self.realized_profit_loss),
            "unrealized_profit_loss": str(self.unrealized_profit_loss),
            "capital_utilization_pct": str(self.capital_utilization_pct),
            "event_head_hash": self.event_head_hash,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PortfolioValuation:
        return cls(
            valued_at=datetime.fromisoformat(str(payload["valued_at"])),
            policy_version=PolicyVersion(str(payload["policy_version"])),
            cash=Decimal(str(payload["cash"])),
            invested_value=Decimal(str(payload["invested_value"])),
            portfolio_value=Decimal(str(payload["portfolio_value"])),
            realized_profit_loss=Decimal(str(payload["realized_profit_loss"])),
            unrealized_profit_loss=Decimal(str(payload["unrealized_profit_loss"])),
            capital_utilization_pct=Decimal(str(payload["capital_utilization_pct"])),
            event_head_hash=str(payload["event_head_hash"]),
        )


@dataclass(frozen=True, slots=True)
class ShadowPosition:
    recommendation_id: str
    symbol: str
    sector: str | None
    policy_version: PolicyVersion
    status: PositionStatus
    quantity: Decimal
    average_cost: Decimal
    last_price: Decimal
    entered_at: datetime | None
    exited_at: datetime | None
    realized_profit_loss: Decimal
    unrealized_profit_loss: Decimal
    targets_hit: tuple[int, ...]
    exit_reason: str | None


@dataclass(frozen=True, slots=True)
class ShadowPortfolioSnapshot:
    valued_at: datetime
    policy_version: PolicyVersion
    initial_capital: Decimal
    cash: Decimal
    positions: tuple[ShadowPosition, ...]
    realized_profit_loss: Decimal
    unrealized_profit_loss: Decimal
    portfolio_value: Decimal
    capital_utilization_pct: Decimal
    drawdown_pct: Decimal | None
    daily_loss_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class ForwardPerformanceMetrics:
    policy_version: PolicyVersion
    recommendation_count: int
    entered_count: int
    completed_count: int
    open_count: int
    missed_count: int
    win_rate_pct: Decimal | None
    approval_precision_pct: Decimal | None
    average_winner_pct: Decimal | None
    average_loser_pct: Decimal | None
    profit_factor: Decimal | None
    expectancy_pct: Decimal | None
    average_holding_days: Decimal | None
    maximum_drawdown_pct: Decimal | None
    consecutive_losses: int
    consecutive_wins: int
    capital_utilization_pct: Decimal | None
    cagr_pct: Decimal | None
    sharpe_ratio: Decimal | None
    sortino_ratio: Decimal | None


@dataclass(frozen=True, slots=True)
class PositionJournalRow:
    recommendation_id: str
    symbol: str
    policy_version: PolicyVersion
    generated_at: datetime
    status: PositionStatus
    entry_price: Decimal | None
    entry_at: datetime | None
    exit_price: Decimal | None
    exit_at: datetime | None
    exit_reason: str | None
    return_pct: Decimal | None
    supporting_evidence_hash: str
    event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ForwardValidationReport:
    generated_at: datetime
    metrics: tuple[ForwardPerformanceMetrics, ...]
    portfolio: tuple[ShadowPortfolioSnapshot, ...]
    largest_winner: PositionJournalRow | None
    largest_loser: PositionJournalRow | None
    readiness: DeploymentReadiness
    readiness_reason: str
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class ForwardUpdateSummary:
    recommendations_checked: int
    new_events: int
    newly_entered: int
    newly_exited: int
    still_active: int
    missing_data_count: int
    portfolios: tuple[ShadowPortfolioSnapshot, ...]


@dataclass(frozen=True, slots=True)
class ApprovalGateMetric:
    gate_id: str
    label: str
    candidates_entering: int
    candidates_passing: int
    candidates_rejected: int
    cumulative_survival_pct: Decimal | None
    profitable_rejected_candidates: int
    average_return_rejected_pct: Decimal | None
    average_return_accepted_pct: Decimal | None
    precision_contribution_pct: Decimal | None
    recall_contribution_pct: Decimal | None
    profit_factor_contribution: Decimal | None
    expectancy_contribution_pct: Decimal | None
    drawdown_reduction_pct: Decimal | None
    capital_utilization_impact_pct: Decimal | None
    redundant_on_observed_population: bool


@dataclass(frozen=True, slots=True)
class StopDistanceAudit:
    classification: StopAuditClassification
    evaluated_candidates: int
    distance_available: int
    candidates_at_gate: int
    candidates_passing: int
    profitable_rejections: int
    minimum_distance_pct: Decimal | None
    median_distance_pct: Decimal | None
    maximum_distance_pct: Decimal | None
    current_threshold_pct: Decimal
    recommended_threshold_pct: Decimal | None
    implementation_correction: str | None
    findings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PolicyScorecard:
    policy_version: PolicyVersion
    split: ValidationSplit
    sample_count: int
    approved_count: int
    profitable_approved_count: int
    precision_pct: Decimal | None
    recall_pct: Decimal | None
    average_return_pct: Decimal | None
    profit_factor: Decimal | None
    maximum_drawdown_proxy_pct: Decimal | None
    expectancy_pct: Decimal | None
    passed_baseline: bool
    reason: str


@dataclass(frozen=True, slots=True)
class CounterfactualPolicy:
    policy_version: PolicyVersion
    operation: CounterfactualOperation
    changed_gate_ids: tuple[str, ...]
    description: str
    parameters: dict[str, str]
    scorecards: tuple[PolicyScorecard, ...] = ()
    stage: PolicyStage = PolicyStage.GENERATED

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(dict(sorted(self.parameters.items()))),
        )


@dataclass(frozen=True, slots=True)
class ApprovalOptimizationReport:
    generated_at: datetime
    policy_version: PolicyVersion
    source_population: int
    outcome_population: int
    gates: tuple[ApprovalGateMetric, ...]
    stop_distance_audit: StopDistanceAudit
    candidates: tuple[CounterfactualPolicy, ...]
    recommendation: OptimizationRecommendation
    recommendation_reason: str
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class DeploymentReadinessReport:
    generated_at: datetime
    readiness: DeploymentReadiness
    policy_versions: tuple[PolicyVersion, ...]
    evidence_by_policy: tuple[ForwardPerformanceMetrics, ...]
    candidate_policy: PolicyVersion | None
    reason: str
    missing_evidence: tuple[str, ...]
    production_influence: bool = PRODUCTION_INFLUENCE


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _decimal(value: object) -> Decimal | None:
    if value is None or str(value).strip() in {"", "None", "unavailable"}:
        return None
    return Decimal(str(value))


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(str(value))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def days_between(start: datetime, end: datetime) -> int:
    return max(0, (end.date() - start.date()).days)


def annualization_days(start: date, end: date) -> Decimal:
    return Decimal(str(max(1, (end - start).days)))


__all__ = [
    "ApprovalGateMetric",
    "ApprovalOptimizationReport",
    "CURRENT_POLICY_VERSION",
    "CounterfactualOperation",
    "CounterfactualPolicy",
    "DeploymentReadiness",
    "DeploymentReadinessReport",
    "FORWARD_VALIDATION_SCHEMA_VERSION",
    "ForwardPerformanceMetrics",
    "ForwardRiskControls",
    "ForwardValidationConfig",
    "ForwardValidationReport",
    "ForwardUpdateSummary",
    "OptimizationRecommendation",
    "PRODUCTION_INFLUENCE",
    "PolicyScorecard",
    "PolicyStage",
    "PolicyVersion",
    "PortfolioValuation",
    "PositionEvent",
    "PositionEventDraft",
    "PositionEventType",
    "PositionJournalRow",
    "PositionStatus",
    "RecommendationSnapshot",
    "ShadowPortfolioSnapshot",
    "ShadowPosition",
    "StopAuditClassification",
    "StopDistanceAudit",
    "ValidationSplit",
    "annualization_days",
    "days_between",
]
