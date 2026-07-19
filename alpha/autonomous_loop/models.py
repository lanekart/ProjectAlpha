from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from alpha.forward_validation.models import PolicyVersion

PRODUCTION_INFLUENCE = False
AUTONOMOUS_LOOP_SCHEMA_VERSION = "autonomous-decision-loop-v1"
DEFAULT_UNIVERSE_ID = "CANONICAL_ALPHA_UNIVERSE"
DEFAULT_SCHEDULE_ID = "WEEKDAY_POST_CLOSE"


class UniverseSource(StrEnum):
    CANONICAL_RUNTIME = "CANONICAL_RUNTIME"
    EXPLICIT_SYMBOLS = "EXPLICIT_SYMBOLS"


class LoopEvidenceClass(StrEnum):
    FORWARD_OBSERVED = "FORWARD_OBSERVED"


class RunStage(StrEnum):
    STARTED = "STARTED"
    RESUMED = "RESUMED"
    DECISIONS_FROZEN = "DECISIONS_FROZEN"
    SHADOW_UPDATED = "SHADOW_UPDATED"
    MARKED_TO_MARKET = "MARKED_TO_MARKET"
    OUTCOMES_PUBLISHED = "OUTCOMES_PUBLISHED"
    DNA_UPDATED = "DNA_UPDATED"
    DRIFT_EVALUATED = "DRIFT_EVALUATED"
    HYPOTHESES_ROUTED = "HYPOTHESES_ROUTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RunStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED_CLOSED = "FAILED_CLOSED"
    ALREADY_COMPLETED = "ALREADY_COMPLETED"
    NOT_DUE = "NOT_DUE"
    IN_PROGRESS = "IN_PROGRESS"


class DecisionKind(StrEnum):
    APPROVED_TRADE = "APPROVED_TRADE"
    NO_TRADE = "NO_TRADE"
    RISK_BLOCKED = "RISK_BLOCKED"
    REJECTED = "REJECTED"
    DATA_BLOCKED = "DATA_BLOCKED"


class ResolutionKind(StrEnum):
    WINNER = "WINNER"
    LOSER = "LOSER"
    CATASTROPHIC_LOSS = "CATASTROPHIC_LOSS"
    FLAT = "FLAT"
    MISSED_OPPORTUNITY = "MISSED_OPPORTUNITY"
    REJECTED_OPPORTUNITY = "REJECTED_OPPORTUNITY"


class ForwardDNACohort(StrEnum):
    WINNERS = "FORWARD_OBSERVED_WINNERS"
    LOSERS = "FORWARD_OBSERVED_LOSERS"
    CATASTROPHIC_LOSSES = "FORWARD_OBSERVED_CATASTROPHIC_LOSSES"
    MISSED_OPPORTUNITIES = "FORWARD_OBSERVED_MISSED_OPPORTUNITIES"
    REJECTED_OPPORTUNITIES = "FORWARD_OBSERVED_REJECTED_OPPORTUNITIES"


class DriftState(StrEnum):
    NO_DRIFT = "NO_DRIFT"
    EARLY_DRIFT = "EARLY_DRIFT"
    SIGNIFICANT_DRIFT = "SIGNIFICANT_DRIFT"
    UNKNOWN = "UNKNOWN"


class HypothesisStage(StrEnum):
    STRATEGY_LAB_PENDING = "STRATEGY_LAB_PENDING"
    WALK_FORWARD_PENDING = "WALK_FORWARD_PENDING"
    SHADOW_VALIDATION_PENDING = "SHADOW_VALIDATION_PENDING"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    REJECTED = "REJECTED"


class ValidationGate(StrEnum):
    STRATEGY_LAB = "STRATEGY_LAB"
    WALK_FORWARD = "WALK_FORWARD"
    SHADOW_VALIDATION = "SHADOW_VALIDATION"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"


class ValidationResult(StrEnum):
    SUBMITTED = "SUBMITTED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    APPROVED = "APPROVED"


@dataclass(frozen=True, slots=True)
class UniverseDefinition:
    universe_id: str
    source: UniverseSource
    symbols: tuple[str, ...] = ()
    version: str = "universe-v1"
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        universe_id = self.universe_id.strip().upper()
        symbols = tuple(
            sorted({item.strip().upper() for item in self.symbols if item.strip()})
        )
        if not universe_id or not self.version.strip():
            raise ValueError("universe identity and version are required")
        if self.source is UniverseSource.EXPLICIT_SYMBOLS and not symbols:
            raise ValueError("explicit universe requires at least one symbol")
        if self.source is UniverseSource.CANONICAL_RUNTIME and symbols:
            raise ValueError(
                "canonical runtime universe cannot declare explicit symbols"
            )
        if self.production_influence:
            raise ValueError("autonomous loop cannot influence production")
        object.__setattr__(self, "universe_id", universe_id)
        object.__setattr__(self, "symbols", symbols)


@dataclass(frozen=True, slots=True)
class ScheduleDefinition:
    schedule_id: str
    universe_id: str
    local_time: time
    timezone: str
    weekdays: tuple[int, ...]
    policy_version: PolicyVersion
    shadow_initial_capital: Decimal
    maximum_data_age_days: int = 3
    markout_horizon_bars: int = 20
    enabled: bool = True
    version: str = "schedule-v1"
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        schedule_id = self.schedule_id.strip().upper()
        universe_id = self.universe_id.strip().upper()
        weekdays = tuple(sorted(set(self.weekdays)))
        if not schedule_id or not universe_id or not self.version.strip():
            raise ValueError("schedule, universe, and version are required")
        if not weekdays or any(day < 0 or day > 6 for day in weekdays):
            raise ValueError("weekdays must contain ISO weekday indexes 0 through 6")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("schedule timezone is unavailable") from exc
        if self.shadow_initial_capital <= Decimal("0"):
            raise ValueError("shadow initial capital must be positive")
        if self.maximum_data_age_days < 0:
            raise ValueError("maximum data age cannot be negative")
        if self.markout_horizon_bars <= 0:
            raise ValueError("markout horizon must be positive")
        if self.production_influence:
            raise ValueError("scheduled research cannot influence production")
        object.__setattr__(self, "schedule_id", schedule_id)
        object.__setattr__(self, "universe_id", universe_id)
        object.__setattr__(self, "weekdays", weekdays)


@dataclass(frozen=True, slots=True)
class RunEvent:
    sequence: int
    event_id: str
    run_id: str
    schedule_id: str
    scheduled_for: datetime
    occurred_at: datetime
    stage: RunStage
    detail: str
    metrics: dict[str, str]
    previous_hash: str
    event_hash: str
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "scheduled_for", _utc(self.scheduled_for))
        object.__setattr__(self, "occurred_at", _utc(self.occurred_at))
        object.__setattr__(
            self,
            "metrics",
            MappingProxyType(dict(sorted(self.metrics.items()))),
        )
        if self.production_influence:
            raise ValueError("run events cannot influence production")


@dataclass(frozen=True, slots=True)
class FrozenDecision:
    decision_id: str
    run_id: str
    schedule_id: str
    universe_id: str
    recommendation_id: str | None
    generated_at: datetime
    observed_on: date
    symbol: str
    decision_kind: DecisionKind
    final_verdict: str
    reference_price: Decimal | None
    approved_deployment: Decimal | None
    policy_version: PolicyVersion
    markout_horizon_bars: int
    reasons: tuple[str, ...]
    feature_snapshot: dict[str, str]
    evidence_hashes: dict[str, str]
    evidence_class: LoopEvidenceClass
    artifact_hash: str
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "generated_at", _utc(self.generated_at))
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(
            self,
            "reasons",
            tuple(item.strip() for item in self.reasons if item.strip()),
        )
        object.__setattr__(
            self,
            "feature_snapshot",
            MappingProxyType(dict(sorted(self.feature_snapshot.items()))),
        )
        object.__setattr__(
            self,
            "evidence_hashes",
            MappingProxyType(dict(sorted(self.evidence_hashes.items()))),
        )
        if not self.decision_id or not self.run_id or not self.symbol:
            raise ValueError("decision identity, run, and symbol are required")
        if self.markout_horizon_bars <= 0:
            raise ValueError("decision markout horizon must be positive")
        if self.reference_price is not None and self.reference_price <= Decimal("0"):
            raise ValueError("reference price must be positive")
        if self.production_influence:
            raise ValueError("frozen decisions cannot influence production")


@dataclass(frozen=True, slots=True)
class DecisionMark:
    mark_id: str
    decision_id: str
    symbol: str
    observed_on: date
    close_price: Decimal
    high_price: Decimal
    low_price: Decimal
    return_pct: Decimal
    favorable_excursion_pct: Decimal
    adverse_excursion_pct: Decimal
    source_hash: str
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        if min(self.close_price, self.high_price, self.low_price) <= Decimal("0"):
            raise ValueError("mark prices must be positive")
        if self.high_price < self.low_price:
            raise ValueError("mark high cannot be below low")
        if self.production_influence:
            raise ValueError("decision marks cannot influence production")


@dataclass(frozen=True, slots=True)
class DecisionResolution:
    resolution_id: str
    decision_id: str
    resolved_at: datetime
    resolution_kind: ResolutionKind
    realised_return_pct: Decimal
    maximum_favorable_excursion_pct: Decimal
    maximum_adverse_excursion_pct: Decimal
    bars_observed: int
    reason: str
    terminal_mark_id: str
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "resolved_at", _utc(self.resolved_at))
        if self.bars_observed <= 0 or not self.reason.strip():
            raise ValueError("resolution requires observed bars and a reason")
        if self.production_influence:
            raise ValueError("decision resolutions cannot influence production")


@dataclass(frozen=True, slots=True)
class ForwardDNAObservation:
    observation_id: str
    decision_id: str
    recommendation_id: str | None
    observed_at: datetime
    symbol: str
    cohort: ForwardDNACohort
    realised_return_pct: Decimal
    features: dict[str, str]
    source_resolution_id: str
    evidence_class: LoopEvidenceClass = LoopEvidenceClass.FORWARD_OBSERVED
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", _utc(self.observed_at))
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(
            self,
            "features",
            MappingProxyType(dict(sorted(self.features.items()))),
        )
        if self.evidence_class is not LoopEvidenceClass.FORWARD_OBSERVED:
            raise ValueError("forward DNA cannot mix evidence classes")
        if self.production_influence:
            raise ValueError("forward DNA cannot influence production")


@dataclass(frozen=True, slots=True)
class DNADriftAssessment:
    drift_id: str
    cohort: ForwardDNACohort
    baseline_count: int
    recent_count: int
    baseline_prevalence_pct: Decimal | None
    recent_prevalence_pct: Decimal | None
    change_pct_points: Decimal | None
    state: DriftState
    evidence_ids: tuple[str, ...]
    explanation: str
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("DNA drift cannot influence production")


@dataclass(frozen=True, slots=True)
class ImprovementHypothesis:
    hypothesis_id: str
    created_at: datetime
    title: str
    subsystem: str
    statement: str
    evidence_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    stage: HypothesisStage
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", _utc(self.created_at))
        if not self.evidence_ids:
            raise ValueError("improvement hypothesis requires evidence")
        if self.production_influence:
            raise ValueError("hypotheses cannot influence production")


@dataclass(frozen=True, slots=True)
class ValidationEvent:
    validation_id: str
    hypothesis_id: str
    occurred_at: datetime
    gate: ValidationGate
    result: ValidationResult
    evidence_artifact_id: str
    explanation: str
    actor: str
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "occurred_at", _utc(self.occurred_at))
        if not self.evidence_artifact_id.strip() or not self.actor.strip():
            raise ValueError("validation evidence and actor are required")
        if self.production_influence:
            raise ValueError("validation events cannot influence production")


@dataclass(frozen=True, slots=True)
class MarkToMarketSummary:
    decisions_checked: int
    marks_inserted: int
    resolutions_inserted: int
    unresolved_count: int
    missing_data_count: int


@dataclass(frozen=True, slots=True)
class AutonomousRunSummary:
    run_id: str
    schedule_id: str
    scheduled_for: datetime
    status: RunStatus
    decisions_frozen: int
    shadow_events: int
    marks_inserted: int
    resolutions_inserted: int
    matured_outcomes_published: int
    forward_dna_inserted: int
    drift_alerts: int
    hypotheses_routed: int
    missing_data_count: int
    detail: str
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "scheduled_for", _utc(self.scheduled_for))
        if self.production_influence:
            raise ValueError("autonomous run cannot influence production")


@dataclass(frozen=True, slots=True)
class AutonomousLoopStatus:
    generated_at: datetime
    universes: int
    schedules: int
    runs: int
    completed_runs: int
    failed_runs: int
    frozen_decisions: int
    unresolved_decisions: int
    resolved_decisions: int
    forward_dna_observations: int
    open_hypotheses: int
    human_approved_hypotheses: int
    last_completed_run: str | None
    production_influence: bool = PRODUCTION_INFLUENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "generated_at", _utc(self.generated_at))
        if self.production_influence:
            raise ValueError("loop status cannot influence production")


def default_universe() -> UniverseDefinition:
    return UniverseDefinition(
        universe_id=DEFAULT_UNIVERSE_ID,
        source=UniverseSource.CANONICAL_RUNTIME,
    )


def default_schedule() -> ScheduleDefinition:
    return ScheduleDefinition(
        schedule_id=DEFAULT_SCHEDULE_ID,
        universe_id=DEFAULT_UNIVERSE_ID,
        local_time=time(15, 45),
        timezone="Asia/Kolkata",
        weekdays=(0, 1, 2, 3, 4),
        policy_version=PolicyVersion("APPROVAL_POLICY_V1"),
        shadow_initial_capital=Decimal("1000000"),
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def optional_decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


__all__ = [
    "AUTONOMOUS_LOOP_SCHEMA_VERSION",
    "DEFAULT_SCHEDULE_ID",
    "DEFAULT_UNIVERSE_ID",
    "PRODUCTION_INFLUENCE",
    "AutonomousLoopStatus",
    "AutonomousRunSummary",
    "DNADriftAssessment",
    "DecisionKind",
    "DecisionMark",
    "DecisionResolution",
    "DriftState",
    "ForwardDNACohort",
    "ForwardDNAObservation",
    "FrozenDecision",
    "HypothesisStage",
    "ImprovementHypothesis",
    "LoopEvidenceClass",
    "MarkToMarketSummary",
    "ResolutionKind",
    "RunEvent",
    "RunStage",
    "RunStatus",
    "ScheduleDefinition",
    "UniverseDefinition",
    "UniverseSource",
    "ValidationEvent",
    "ValidationGate",
    "ValidationResult",
    "default_schedule",
    "default_universe",
    "mapping",
    "optional_decimal",
    "optional_text",
]
