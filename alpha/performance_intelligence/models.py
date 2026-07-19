from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO_PLACES = Decimal("0.01")
_FOUR_PLACES = Decimal("0.0001")


class RecommendationOutcomeStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    EXITED = "exited"
    EXPIRED = "expired"
    NOT_TRIGGERED = "not_triggered"
    DATA_MISSING = "data_missing"


class RecommendationExitReason(StrEnum):
    NONE = "none"
    TARGET_1 = "target_1"
    TARGET_2 = "target_2"
    TARGET_3 = "target_3"
    STOP_LOSS = "stop_loss"
    TRAILING_STOP = "trailing_stop"
    EXPIRED = "expired"
    NOT_TRIGGERED = "not_triggered"
    DATA_MISSING = "data_missing"


class NextDayOutcomeLabel(StrEnum):
    WIN = "WIN"
    LOSS = "LOSS"
    NEUTRAL = "NEUTRAL"
    OPEN = "OPEN"


@dataclass(frozen=True, slots=True)
class RecommendationLedgerEntry:
    recommendation_id: str
    generated_at: datetime
    symbol: str
    final_verdict: str
    confidence: str
    score: Decimal
    setup_type: str | None
    setup_state: str | None
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    confirmation_entry: Decimal | None
    stop_loss: Decimal | None
    target_1: Decimal | None
    target_2: Decimal | None
    target_3: Decimal | None
    trailing_stop_strategy: str | None
    holding_period: str | None
    market_regime: str | None
    sector: str | None
    key_indicator_snapshot: MappingProxyType[str, str] | dict[str, str]
    statistical_edge_snapshot: MappingProxyType[str, str] | dict[str, str]
    data_completeness_snapshot: MappingProxyType[str, str] | dict[str, str]
    source_run_id: str
    company_name: str | None = None
    recommended_position_size_rs: Decimal | None = None
    recommended_quantity: Decimal | None = None
    approved_deployment_rs: Decimal | None = None
    candle_pattern: str | None = None
    reward_risk: Decimal | None = None
    expected_value: Decimal | None = None
    explanation: str | None = None
    status: str = "OPEN"

    def __post_init__(self) -> None:
        recommendation_id = self.recommendation_id.strip()
        symbol = self.symbol.strip().upper()
        final_verdict = self.final_verdict.strip().upper()
        confidence = self.confidence.strip().upper()
        source_run_id = self.source_run_id.strip()

        if not recommendation_id:
            raise ValueError("recommendation_id cannot be empty")
        if not symbol:
            raise ValueError("recommendation symbol cannot be empty")
        if not final_verdict:
            raise ValueError("final verdict cannot be empty")
        if not confidence:
            raise ValueError("confidence cannot be empty")
        if not source_run_id:
            raise ValueError("source_run_id cannot be empty")

        object.__setattr__(self, "recommendation_id", recommendation_id)
        object.__setattr__(self, "generated_at", _normalize_datetime(self.generated_at))
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "final_verdict", final_verdict)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "score", _decimal(self.score))
        object.__setattr__(self, "setup_type", _optional_text(self.setup_type))
        object.__setattr__(self, "setup_state", _optional_text(self.setup_state))
        object.__setattr__(
            self,
            "entry_zone_low",
            _optional_decimal(self.entry_zone_low),
        )
        object.__setattr__(
            self,
            "entry_zone_high",
            _optional_decimal(self.entry_zone_high),
        )
        object.__setattr__(
            self,
            "confirmation_entry",
            _optional_decimal(self.confirmation_entry),
        )
        object.__setattr__(self, "stop_loss", _optional_decimal(self.stop_loss))
        object.__setattr__(self, "target_1", _optional_decimal(self.target_1))
        object.__setattr__(self, "target_2", _optional_decimal(self.target_2))
        object.__setattr__(self, "target_3", _optional_decimal(self.target_3))
        object.__setattr__(
            self,
            "trailing_stop_strategy",
            _optional_text(self.trailing_stop_strategy),
        )
        object.__setattr__(self, "holding_period", _optional_text(self.holding_period))
        object.__setattr__(self, "market_regime", _optional_text(self.market_regime))
        object.__setattr__(self, "sector", _optional_text(self.sector))
        object.__setattr__(self, "company_name", _optional_text(self.company_name))
        object.__setattr__(
            self,
            "recommended_position_size_rs",
            _optional_decimal(self.recommended_position_size_rs),
        )
        object.__setattr__(
            self,
            "recommended_quantity",
            _optional_decimal(self.recommended_quantity),
        )
        object.__setattr__(
            self,
            "approved_deployment_rs",
            _optional_decimal(self.approved_deployment_rs),
        )
        object.__setattr__(self, "candle_pattern", _optional_text(self.candle_pattern))
        object.__setattr__(self, "reward_risk", _optional_decimal(self.reward_risk))
        object.__setattr__(
            self,
            "expected_value",
            _optional_decimal(self.expected_value),
        )
        object.__setattr__(self, "explanation", _optional_text(self.explanation))
        object.__setattr__(self, "status", self.status.strip().upper() or "OPEN")
        object.__setattr__(
            self,
            "key_indicator_snapshot",
            _immutable_snapshot(self.key_indicator_snapshot),
        )
        object.__setattr__(
            self,
            "statistical_edge_snapshot",
            _immutable_snapshot(self.statistical_edge_snapshot),
        )
        object.__setattr__(
            self,
            "data_completeness_snapshot",
            _immutable_snapshot(self.data_completeness_snapshot),
        )
        object.__setattr__(self, "source_run_id", source_run_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "generated_at": self.generated_at.isoformat(),
            "symbol": self.symbol,
            "final_verdict": self.final_verdict,
            "confidence": self.confidence,
            "score": str(self.score),
            "setup_type": self.setup_type,
            "setup_state": self.setup_state,
            "entry_zone_low": _decimal_text(self.entry_zone_low),
            "entry_zone_high": _decimal_text(self.entry_zone_high),
            "confirmation_entry": _decimal_text(self.confirmation_entry),
            "stop_loss": _decimal_text(self.stop_loss),
            "target_1": _decimal_text(self.target_1),
            "target_2": _decimal_text(self.target_2),
            "target_3": _decimal_text(self.target_3),
            "trailing_stop_strategy": self.trailing_stop_strategy,
            "holding_period": self.holding_period,
            "market_regime": self.market_regime,
            "sector": self.sector,
            "company_name": self.company_name,
            "recommended_position_size_rs": _decimal_text(
                self.recommended_position_size_rs
            ),
            "recommended_quantity": _decimal_text(self.recommended_quantity),
            "approved_deployment_rs": _decimal_text(self.approved_deployment_rs),
            "candle_pattern": self.candle_pattern,
            "reward_risk": _decimal_text(self.reward_risk),
            "expected_value": _decimal_text(self.expected_value),
            "explanation": self.explanation,
            "status": self.status,
            "key_indicator_snapshot": dict(self.key_indicator_snapshot),
            "statistical_edge_snapshot": dict(self.statistical_edge_snapshot),
            "data_completeness_snapshot": dict(self.data_completeness_snapshot),
            "source_run_id": self.source_run_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RecommendationLedgerEntry:
        return cls(
            recommendation_id=str(payload["recommendation_id"]),
            generated_at=datetime.fromisoformat(str(payload["generated_at"])),
            symbol=str(payload["symbol"]),
            final_verdict=str(payload["final_verdict"]),
            confidence=str(payload["confidence"]),
            score=Decimal(str(payload["score"])),
            setup_type=_payload_optional_text(payload.get("setup_type")),
            setup_state=_payload_optional_text(payload.get("setup_state")),
            entry_zone_low=_payload_decimal(payload.get("entry_zone_low")),
            entry_zone_high=_payload_decimal(payload.get("entry_zone_high")),
            confirmation_entry=_payload_decimal(payload.get("confirmation_entry")),
            stop_loss=_payload_decimal(payload.get("stop_loss")),
            target_1=_payload_decimal(payload.get("target_1")),
            target_2=_payload_decimal(payload.get("target_2")),
            target_3=_payload_decimal(payload.get("target_3")),
            trailing_stop_strategy=_payload_optional_text(
                payload.get("trailing_stop_strategy")
            ),
            holding_period=_payload_optional_text(payload.get("holding_period")),
            market_regime=_payload_optional_text(payload.get("market_regime")),
            sector=_payload_optional_text(payload.get("sector")),
            company_name=_payload_optional_text(payload.get("company_name")),
            recommended_position_size_rs=_payload_decimal(
                payload.get("recommended_position_size_rs")
            ),
            recommended_quantity=_payload_decimal(payload.get("recommended_quantity")),
            approved_deployment_rs=_payload_decimal(
                payload.get("approved_deployment_rs")
            ),
            candle_pattern=_payload_optional_text(payload.get("candle_pattern")),
            reward_risk=_payload_decimal(payload.get("reward_risk")),
            expected_value=_payload_decimal(payload.get("expected_value")),
            explanation=_payload_optional_text(payload.get("explanation")),
            status=str(payload.get("status", "OPEN")),
            key_indicator_snapshot=_payload_snapshot(
                payload.get("key_indicator_snapshot")
            ),
            statistical_edge_snapshot=_payload_snapshot(
                payload.get("statistical_edge_snapshot")
            ),
            data_completeness_snapshot=_payload_snapshot(
                payload.get("data_completeness_snapshot")
            ),
            source_run_id=str(payload["source_run_id"]),
        )


@dataclass(frozen=True, slots=True)
class RecommendationOutcome:
    recommendation_id: str
    symbol: str
    status: RecommendationOutcomeStatus
    entry_triggered: bool = False
    entry_date: date | None = None
    entry_price: Decimal | None = None
    stop_hit: bool = False
    target_1_hit: bool = False
    target_2_hit: bool = False
    target_3_hit: bool = False
    trailing_stop_hit: bool = False
    exit_date: date | None = None
    exit_price: Decimal | None = None
    exit_reason: RecommendationExitReason = RecommendationExitReason.NONE
    maximum_favorable_excursion: Decimal | None = None
    maximum_adverse_excursion: Decimal | None = None
    realized_r_multiple: Decimal | None = None
    realized_percent_return: Decimal | None = None
    realized_pnl_rs: Decimal | None = None
    unrealized_pnl_rs: Decimal | None = None
    next_day_open: Decimal | None = None
    next_day_high: Decimal | None = None
    next_day_low: Decimal | None = None
    next_day_close: Decimal | None = None
    next_day_return_from_entry: Decimal | None = None
    next_day_return_from_confirmation_entry: Decimal | None = None
    next_day_target_1_touched: bool = False
    next_day_stop_touched: bool = False
    next_day_close_above_entry: bool | None = None
    next_day_outcome_label: NextDayOutcomeLabel = NextDayOutcomeLabel.OPEN
    next_day_pnl_rs: Decimal | None = None
    next_day_pnl_pct: Decimal | None = None
    holding_period_bars: int = 0
    holding_period_days: int = 0
    explanation: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        recommendation_id = self.recommendation_id.strip()
        symbol = self.symbol.strip().upper()
        if not recommendation_id:
            raise ValueError("outcome recommendation_id cannot be empty")
        if not symbol:
            raise ValueError("outcome symbol cannot be empty")
        if self.holding_period_bars < 0:
            raise ValueError("holding_period_bars cannot be negative")
        if self.holding_period_days < 0:
            raise ValueError("holding_period_days cannot be negative")

        object.__setattr__(self, "recommendation_id", recommendation_id)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self,
            "status",
            RecommendationOutcomeStatus(self.status),
        )
        object.__setattr__(
            self,
            "exit_reason",
            RecommendationExitReason(self.exit_reason),
        )
        object.__setattr__(
            self,
            "next_day_outcome_label",
            NextDayOutcomeLabel(self.next_day_outcome_label),
        )
        for field_name in (
            "entry_price",
            "exit_price",
            "maximum_favorable_excursion",
            "maximum_adverse_excursion",
            "realized_r_multiple",
            "realized_percent_return",
            "realized_pnl_rs",
            "unrealized_pnl_rs",
            "next_day_open",
            "next_day_high",
            "next_day_low",
            "next_day_close",
            "next_day_return_from_entry",
            "next_day_return_from_confirmation_entry",
            "next_day_pnl_rs",
            "next_day_pnl_pct",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_decimal(getattr(self, field_name)),
            )
        explanation = tuple(line.strip() for line in self.explanation if line.strip())
        object.__setattr__(self, "explanation", explanation)

    def as_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "symbol": self.symbol,
            "status": self.status.value,
            "entry_triggered": self.entry_triggered,
            "entry_date": self.entry_date.isoformat() if self.entry_date else None,
            "entry_price": _decimal_text(self.entry_price),
            "stop_hit": self.stop_hit,
            "target_1_hit": self.target_1_hit,
            "target_2_hit": self.target_2_hit,
            "target_3_hit": self.target_3_hit,
            "trailing_stop_hit": self.trailing_stop_hit,
            "exit_date": self.exit_date.isoformat() if self.exit_date else None,
            "exit_price": _decimal_text(self.exit_price),
            "exit_reason": self.exit_reason.value,
            "maximum_favorable_excursion": _decimal_text(
                self.maximum_favorable_excursion
            ),
            "maximum_adverse_excursion": _decimal_text(self.maximum_adverse_excursion),
            "realized_r_multiple": _decimal_text(self.realized_r_multiple),
            "realized_percent_return": _decimal_text(self.realized_percent_return),
            "realized_pnl_rs": _decimal_text(self.realized_pnl_rs),
            "unrealized_pnl_rs": _decimal_text(self.unrealized_pnl_rs),
            "next_day_open": _decimal_text(self.next_day_open),
            "next_day_high": _decimal_text(self.next_day_high),
            "next_day_low": _decimal_text(self.next_day_low),
            "next_day_close": _decimal_text(self.next_day_close),
            "next_day_return_from_entry": _decimal_text(
                self.next_day_return_from_entry
            ),
            "next_day_return_from_confirmation_entry": _decimal_text(
                self.next_day_return_from_confirmation_entry
            ),
            "next_day_target_1_touched": self.next_day_target_1_touched,
            "next_day_stop_touched": self.next_day_stop_touched,
            "next_day_close_above_entry": self.next_day_close_above_entry,
            "next_day_outcome_label": self.next_day_outcome_label.value,
            "next_day_pnl_rs": _decimal_text(self.next_day_pnl_rs),
            "next_day_pnl_pct": _decimal_text(self.next_day_pnl_pct),
            "holding_period_bars": self.holding_period_bars,
            "holding_period_days": self.holding_period_days,
            "explanation": list(self.explanation),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RecommendationOutcome:
        return cls(
            recommendation_id=str(payload["recommendation_id"]),
            symbol=str(payload["symbol"]),
            status=RecommendationOutcomeStatus(str(payload["status"])),
            entry_triggered=bool(payload.get("entry_triggered", False)),
            entry_date=_payload_date(payload.get("entry_date")),
            entry_price=_payload_decimal(payload.get("entry_price")),
            stop_hit=bool(payload.get("stop_hit", False)),
            target_1_hit=bool(payload.get("target_1_hit", False)),
            target_2_hit=bool(payload.get("target_2_hit", False)),
            target_3_hit=bool(payload.get("target_3_hit", False)),
            trailing_stop_hit=bool(payload.get("trailing_stop_hit", False)),
            exit_date=_payload_date(payload.get("exit_date")),
            exit_price=_payload_decimal(payload.get("exit_price")),
            exit_reason=RecommendationExitReason(
                str(payload.get("exit_reason", RecommendationExitReason.NONE.value))
            ),
            maximum_favorable_excursion=_payload_decimal(
                payload.get("maximum_favorable_excursion")
            ),
            maximum_adverse_excursion=_payload_decimal(
                payload.get("maximum_adverse_excursion")
            ),
            realized_r_multiple=_payload_decimal(payload.get("realized_r_multiple")),
            realized_percent_return=_payload_decimal(
                payload.get("realized_percent_return")
            ),
            realized_pnl_rs=_payload_decimal(payload.get("realized_pnl_rs")),
            unrealized_pnl_rs=_payload_decimal(payload.get("unrealized_pnl_rs")),
            next_day_open=_payload_decimal(payload.get("next_day_open")),
            next_day_high=_payload_decimal(payload.get("next_day_high")),
            next_day_low=_payload_decimal(payload.get("next_day_low")),
            next_day_close=_payload_decimal(payload.get("next_day_close")),
            next_day_return_from_entry=_payload_decimal(
                payload.get("next_day_return_from_entry")
            ),
            next_day_return_from_confirmation_entry=_payload_decimal(
                payload.get("next_day_return_from_confirmation_entry")
            ),
            next_day_target_1_touched=bool(
                payload.get("next_day_target_1_touched", False)
            ),
            next_day_stop_touched=bool(payload.get("next_day_stop_touched", False)),
            next_day_close_above_entry=payload.get("next_day_close_above_entry"),
            next_day_outcome_label=NextDayOutcomeLabel(
                str(payload.get("next_day_outcome_label", NextDayOutcomeLabel.OPEN))
            ),
            next_day_pnl_rs=_payload_decimal(payload.get("next_day_pnl_rs")),
            next_day_pnl_pct=_payload_decimal(payload.get("next_day_pnl_pct")),
            holding_period_bars=int(payload.get("holding_period_bars", 0)),
            holding_period_days=int(payload.get("holding_period_days", 0)),
            explanation=tuple(str(line) for line in payload.get("explanation", ())),
        )


@dataclass(frozen=True, slots=True)
class PerformanceUpdateSummary:
    recommendations_checked: int
    newly_entered: int
    newly_exited: int
    still_active: int
    expired: int
    missing_data_count: int


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    total_recommendations: int
    completed_trades: int
    win_rate: Decimal | None
    loss_rate: Decimal | None
    average_r: Decimal | None
    expectancy: Decimal | None
    average_gain: Decimal | None
    average_loss: Decimal | None
    profit_factor: Decimal | None
    average_holding_period: Decimal | None
    target_1_hit_rate: Decimal | None
    target_2_hit_rate: Decimal | None
    target_3_hit_rate: Decimal | None
    stop_hit_rate: Decimal | None
    not_triggered_rate: Decimal | None
    pending_count: int
    active_count: int
    sample_count: int
    sufficient_sample: bool
    average_gain_rs: Decimal | None = None
    average_loss_rs: Decimal | None = None
    total_realized_pnl_rs: Decimal | None = None
    total_unrealized_pnl_rs: Decimal | None = None
    cumulative_pnl_rs: Decimal | None = None
    expectancy_pct: Decimal | None = None
    expectancy_rs: Decimal | None = None
    best_trade_rs: Decimal | None = None
    worst_trade_rs: Decimal | None = None
    best_trade_pct: Decimal | None = None
    worst_trade_pct: Decimal | None = None
    median_holding_period: Decimal | None = None
    breakeven_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0


@dataclass(frozen=True, slots=True)
class HistoricalEdge:
    dimension: str
    key: str
    sample_count: int
    win_rate: Decimal | None
    expected_value_rs: Decimal | None
    average_holding_period: Decimal | None

    @property
    def available(self) -> bool:
        return self.win_rate is not None and self.expected_value_rs is not None

    def as_text(self) -> str:
        if not self.available:
            return "Not yet computed"
        return (
            f"sample_count={self.sample_count}, win_rate={self.win_rate}, "
            f"expected_value_rs={self.expected_value_rs}"
        )


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    metrics: PerformanceMetrics
    breakdowns: MappingProxyType[str, PerformanceMetrics]


def confidence_bucket(confidence: str) -> str:
    normalized = confidence.strip().upper()
    if normalized in {"HIGH", "VERY_HIGH", "STRONG"}:
        return "HIGH"
    if normalized in {"MEDIUM", "MODERATE"}:
        return "MEDIUM"
    return "LOW"


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _decimal(value: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _optional_decimal(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value)


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _immutable_snapshot(
    payload: MappingProxyType[str, str] | dict[str, str],
) -> MappingProxyType[str, str]:
    normalized = {
        str(key).strip(): str(value).strip()
        for key, value in payload.items()
        if str(key).strip() and str(value).strip()
    }
    return MappingProxyType(dict(sorted(normalized.items())))


def _payload_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _payload_date(value: object) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(str(value))


def _payload_optional_text(value: object) -> str | None:
    if value is None:
        return None
    return _optional_text(str(value))


def _payload_snapshot(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == _ZERO:
        return None
    return (numerator / denominator).quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)


__all__ = [
    "HistoricalEdge",
    "NextDayOutcomeLabel",
    "PerformanceMetrics",
    "PerformanceReport",
    "PerformanceUpdateSummary",
    "RecommendationExitReason",
    "RecommendationLedgerEntry",
    "RecommendationOutcome",
    "RecommendationOutcomeStatus",
    "confidence_bucket",
    "ratio",
]
