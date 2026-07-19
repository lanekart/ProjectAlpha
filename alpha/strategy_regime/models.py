from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any

_ZERO = Decimal("0")
_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")


class MarketRegime(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    SIDEWAYS = "SIDEWAYS"
    NEUTRAL = "NEUTRAL"
    RISK_OFF = "RISK_OFF"


class SampleConfidence(StrEnum):
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    WEAK_EVIDENCE = "WEAK_EVIDENCE"
    MODERATE_EVIDENCE = "MODERATE_EVIDENCE"
    STRONG_EVIDENCE = "STRONG_EVIDENCE"


class HoldingPeriod(StrEnum):
    NEXT_DAY = "1d"
    THREE_DAYS = "3d"
    FIVE_DAYS = "5d"
    TEN_DAYS = "10d"
    TWENTY_DAYS = "20d"
    SIXTY_DAYS = "60d"

    @property
    def bars(self) -> int:
        return {
            HoldingPeriod.NEXT_DAY: 1,
            HoldingPeriod.THREE_DAYS: 3,
            HoldingPeriod.FIVE_DAYS: 5,
            HoldingPeriod.TEN_DAYS: 10,
            HoldingPeriod.TWENTY_DAYS: 20,
            HoldingPeriod.SIXTY_DAYS: 60,
        }[self]


@dataclass(frozen=True, slots=True)
class StrategySignalObservation:
    symbol: str
    observed_on: date
    regime: MarketRegime
    indicators: tuple[str, ...]
    entry_open: Decimal
    holding_close: MappingProxyType[str, Decimal] | dict[str, Decimal]
    stop_loss: Decimal | None = None
    target_price: Decimal | None = None
    path_high: MappingProxyType[str, Decimal] | dict[str, Decimal] = field(
        default_factory=dict
    )
    path_low: MappingProxyType[str, Decimal] | dict[str, Decimal] = field(
        default_factory=dict
    )
    sector: str | None = None
    capital: Decimal = Decimal("100000")

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("signal symbol cannot be empty")
        indicators = tuple(
            dict.fromkeys(
                indicator.strip().lower().replace("_", "-")
                for indicator in self.indicators
                if indicator.strip()
            )
        )
        if not indicators:
            raise ValueError("signal observation requires at least one indicator")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "regime", MarketRegime(self.regime))
        object.__setattr__(self, "indicators", indicators)
        object.__setattr__(self, "entry_open", _decimal(self.entry_open))
        object.__setattr__(self, "stop_loss", _optional_decimal(self.stop_loss))
        object.__setattr__(self, "target_price", _optional_decimal(self.target_price))
        object.__setattr__(self, "sector", _optional_text(self.sector))
        object.__setattr__(self, "capital", _decimal(self.capital))
        object.__setattr__(
            self,
            "holding_close",
            _decimal_mapping(self.holding_close),
        )
        object.__setattr__(self, "path_high", _decimal_mapping(self.path_high))
        object.__setattr__(self, "path_low", _decimal_mapping(self.path_low))


@dataclass(frozen=True, slots=True)
class StrategyTradeOutcome:
    symbol: str
    regime: MarketRegime
    strategy_name: str
    holding_period: HoldingPeriod
    return_pct: Decimal
    pnl_rs: Decimal
    holding_days: int
    exit_reason: str
    target_hit: bool
    stop_hit: bool
    max_drawdown_pct: Decimal


@dataclass(frozen=True, slots=True)
class HoldingPeriodPerformance:
    holding_period: HoldingPeriod
    total_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate: Decimal | None
    loss_rate: Decimal | None
    average_gain_pct: Decimal | None
    average_loss_pct: Decimal | None
    average_gain_rs: Decimal | None
    average_loss_rs: Decimal | None
    expected_value_pct: Decimal | None
    expected_value_rs: Decimal | None
    median_return: Decimal | None
    profit_factor: Decimal | None
    max_drawdown: Decimal | None
    average_holding_period: Decimal | None
    median_holding_period: Decimal | None
    best_trade: Decimal | None
    worst_trade: Decimal | None
    false_positive_rate: Decimal | None
    sample_size_confidence: SampleConfidence


@dataclass(frozen=True, slots=True)
class StrategyRegimeBacktestResult:
    strategy_name: str
    indicators: tuple[str, ...]
    regime: MarketRegime
    holding_period_results: tuple[HoldingPeriodPerformance, ...]

    @property
    def best_holding_period(self) -> HoldingPeriodPerformance | None:
        if not self.holding_period_results:
            return None
        return max(
            self.holding_period_results,
            key=lambda result: (
                result.expected_value_pct or Decimal("-999"),
                _confidence_rank(result.sample_size_confidence),
                result.profit_factor or _ZERO,
                -(result.max_drawdown or Decimal("999")),
            ),
        )


@dataclass(frozen=True, slots=True)
class IndicatorCombinationResult:
    strategy_name: str
    indicators: tuple[str, ...]
    regime: MarketRegime
    best_holding_period: HoldingPeriod
    expected_value_pct: Decimal | None
    expected_value_rs: Decimal | None
    total_trades: int
    win_rate: Decimal | None
    profit_factor: Decimal | None
    sample_size_confidence: SampleConfidence


@dataclass(frozen=True, slots=True)
class RegimePerformanceSummary:
    regime: MarketRegime
    best_strategies: tuple[IndicatorCombinationResult, ...]
    worst_strategies: tuple[IndicatorCombinationResult, ...]
    avoid_strategies: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrategyRegimeRank:
    rank: int
    strategy_name: str
    regime: MarketRegime
    holding_period: HoldingPeriod
    expected_value_pct: Decimal | None
    profit_factor: Decimal | None
    sample_size_confidence: SampleConfidence


@dataclass(frozen=True, slots=True)
class StrategyRegimeBacktestRun:
    run_id: str
    generated_at: datetime
    from_date: date
    to_date: date
    results: tuple[StrategyRegimeBacktestResult, ...]
    summaries: tuple[RegimePerformanceSummary, ...]
    ranks: tuple[StrategyRegimeRank, ...]

    def __post_init__(self) -> None:
        run_id = self.run_id.strip()
        if not run_id:
            raise ValueError("run_id cannot be empty")
        if self.to_date < self.from_date:
            raise ValueError("to_date must be on or after from_date")
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "generated_at", _normalize_datetime(self.generated_at))
        object.__setattr__(self, "results", tuple(self.results))
        object.__setattr__(self, "summaries", tuple(self.summaries))
        object.__setattr__(self, "ranks", tuple(self.ranks))

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "generated_at": self.generated_at.isoformat(),
            "from_date": self.from_date.isoformat(),
            "to_date": self.to_date.isoformat(),
            "results": [_result_dict(result) for result in self.results],
            "summaries": [_summary_dict(summary) for summary in self.summaries],
            "ranks": [_rank_dict(rank) for rank in self.ranks],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StrategyRegimeBacktestRun:
        return cls(
            run_id=str(payload["run_id"]),
            generated_at=datetime.fromisoformat(str(payload["generated_at"])),
            from_date=date.fromisoformat(str(payload["from_date"])),
            to_date=date.fromisoformat(str(payload["to_date"])),
            results=tuple(_result_from_dict(item) for item in payload["results"]),
            summaries=tuple(_summary_from_dict(item) for item in payload["summaries"]),
            ranks=tuple(_rank_from_dict(item) for item in payload["ranks"]),
        )


def confidence_for_sample(
    sample_size: int,
    minimum_sample_size: int,
) -> SampleConfidence:
    if sample_size < minimum_sample_size:
        return SampleConfidence.INSUFFICIENT_SAMPLE
    if sample_size < minimum_sample_size * 2:
        return SampleConfidence.WEAK_EVIDENCE
    if sample_size < minimum_sample_size * 5:
        return SampleConfidence.MODERATE_EVIDENCE
    return SampleConfidence.STRONG_EVIDENCE


def _result_dict(result: StrategyRegimeBacktestResult) -> dict[str, Any]:
    return {
        "strategy_name": result.strategy_name,
        "indicators": list(result.indicators),
        "regime": result.regime.value,
        "holding_period_results": [
            _holding_dict(item) for item in result.holding_period_results
        ],
    }


def _result_from_dict(payload: dict[str, Any]) -> StrategyRegimeBacktestResult:
    return StrategyRegimeBacktestResult(
        strategy_name=str(payload["strategy_name"]),
        indicators=tuple(str(item) for item in payload["indicators"]),
        regime=MarketRegime(str(payload["regime"])),
        holding_period_results=tuple(
            _holding_from_dict(item) for item in payload["holding_period_results"]
        ),
    )


def _holding_dict(result: HoldingPeriodPerformance) -> dict[str, Any]:
    return {
        "holding_period": result.holding_period.value,
        "total_trades": result.total_trades,
        "winning_trades": result.winning_trades,
        "losing_trades": result.losing_trades,
        "breakeven_trades": result.breakeven_trades,
        "win_rate": _text(result.win_rate),
        "loss_rate": _text(result.loss_rate),
        "average_gain_pct": _text(result.average_gain_pct),
        "average_loss_pct": _text(result.average_loss_pct),
        "average_gain_rs": _text(result.average_gain_rs),
        "average_loss_rs": _text(result.average_loss_rs),
        "expected_value_pct": _text(result.expected_value_pct),
        "expected_value_rs": _text(result.expected_value_rs),
        "median_return": _text(result.median_return),
        "profit_factor": _text(result.profit_factor),
        "max_drawdown": _text(result.max_drawdown),
        "average_holding_period": _text(result.average_holding_period),
        "median_holding_period": _text(result.median_holding_period),
        "best_trade": _text(result.best_trade),
        "worst_trade": _text(result.worst_trade),
        "false_positive_rate": _text(result.false_positive_rate),
        "sample_size_confidence": result.sample_size_confidence.value,
    }


def _holding_from_dict(payload: dict[str, Any]) -> HoldingPeriodPerformance:
    return HoldingPeriodPerformance(
        holding_period=HoldingPeriod(str(payload["holding_period"])),
        total_trades=int(payload["total_trades"]),
        winning_trades=int(payload["winning_trades"]),
        losing_trades=int(payload["losing_trades"]),
        breakeven_trades=int(payload["breakeven_trades"]),
        win_rate=_payload_decimal(payload.get("win_rate")),
        loss_rate=_payload_decimal(payload.get("loss_rate")),
        average_gain_pct=_payload_decimal(payload.get("average_gain_pct")),
        average_loss_pct=_payload_decimal(payload.get("average_loss_pct")),
        average_gain_rs=_payload_decimal(payload.get("average_gain_rs")),
        average_loss_rs=_payload_decimal(payload.get("average_loss_rs")),
        expected_value_pct=_payload_decimal(payload.get("expected_value_pct")),
        expected_value_rs=_payload_decimal(payload.get("expected_value_rs")),
        median_return=_payload_decimal(payload.get("median_return")),
        profit_factor=_payload_decimal(payload.get("profit_factor")),
        max_drawdown=_payload_decimal(payload.get("max_drawdown")),
        average_holding_period=_payload_decimal(payload.get("average_holding_period")),
        median_holding_period=_payload_decimal(payload.get("median_holding_period")),
        best_trade=_payload_decimal(payload.get("best_trade")),
        worst_trade=_payload_decimal(payload.get("worst_trade")),
        false_positive_rate=_payload_decimal(payload.get("false_positive_rate")),
        sample_size_confidence=SampleConfidence(str(payload["sample_size_confidence"])),
    )


def _summary_dict(summary: RegimePerformanceSummary) -> dict[str, Any]:
    return {
        "regime": summary.regime.value,
        "best_strategies": [
            _combination_dict(item) for item in summary.best_strategies
        ],
        "worst_strategies": [
            _combination_dict(item) for item in summary.worst_strategies
        ],
        "avoid_strategies": list(summary.avoid_strategies),
    }


def _summary_from_dict(payload: dict[str, Any]) -> RegimePerformanceSummary:
    return RegimePerformanceSummary(
        regime=MarketRegime(str(payload["regime"])),
        best_strategies=tuple(
            _combination_from_dict(item) for item in payload["best_strategies"]
        ),
        worst_strategies=tuple(
            _combination_from_dict(item) for item in payload["worst_strategies"]
        ),
        avoid_strategies=tuple(str(item) for item in payload["avoid_strategies"]),
    )


def _combination_dict(result: IndicatorCombinationResult) -> dict[str, Any]:
    return {
        "strategy_name": result.strategy_name,
        "indicators": list(result.indicators),
        "regime": result.regime.value,
        "best_holding_period": result.best_holding_period.value,
        "expected_value_pct": _text(result.expected_value_pct),
        "expected_value_rs": _text(result.expected_value_rs),
        "total_trades": result.total_trades,
        "win_rate": _text(result.win_rate),
        "profit_factor": _text(result.profit_factor),
        "sample_size_confidence": result.sample_size_confidence.value,
    }


def _combination_from_dict(payload: dict[str, Any]) -> IndicatorCombinationResult:
    return IndicatorCombinationResult(
        strategy_name=str(payload["strategy_name"]),
        indicators=tuple(str(item) for item in payload["indicators"]),
        regime=MarketRegime(str(payload["regime"])),
        best_holding_period=HoldingPeriod(str(payload["best_holding_period"])),
        expected_value_pct=_payload_decimal(payload.get("expected_value_pct")),
        expected_value_rs=_payload_decimal(payload.get("expected_value_rs")),
        total_trades=int(payload["total_trades"]),
        win_rate=_payload_decimal(payload.get("win_rate")),
        profit_factor=_payload_decimal(payload.get("profit_factor")),
        sample_size_confidence=SampleConfidence(str(payload["sample_size_confidence"])),
    )


def _rank_dict(rank: StrategyRegimeRank) -> dict[str, Any]:
    return {
        "rank": rank.rank,
        "strategy_name": rank.strategy_name,
        "regime": rank.regime.value,
        "holding_period": rank.holding_period.value,
        "expected_value_pct": _text(rank.expected_value_pct),
        "profit_factor": _text(rank.profit_factor),
        "sample_size_confidence": rank.sample_size_confidence.value,
    }


def _rank_from_dict(payload: dict[str, Any]) -> StrategyRegimeRank:
    return StrategyRegimeRank(
        rank=int(payload["rank"]),
        strategy_name=str(payload["strategy_name"]),
        regime=MarketRegime(str(payload["regime"])),
        holding_period=HoldingPeriod(str(payload["holding_period"])),
        expected_value_pct=_payload_decimal(payload.get("expected_value_pct")),
        profit_factor=_payload_decimal(payload.get("profit_factor")),
        sample_size_confidence=SampleConfidence(str(payload["sample_size_confidence"])),
    )


def _decimal(value: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(_TWO, rounding=ROUND_HALF_UP)


def _optional_decimal(value: Decimal | None) -> Decimal | None:
    return None if value is None else _decimal(value)


def _decimal_mapping(
    payload: MappingProxyType[str, Decimal] | dict[str, Decimal],
) -> MappingProxyType[str, Decimal]:
    return MappingProxyType(
        {
            str(key): _decimal(value)
            for key, value in sorted(payload.items())
            if str(key).strip()
        }
    )


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _payload_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _confidence_rank(value: SampleConfidence) -> int:
    return {
        SampleConfidence.INSUFFICIENT_SAMPLE: 0,
        SampleConfidence.WEAK_EVIDENCE: 1,
        SampleConfidence.MODERATE_EVIDENCE: 2,
        SampleConfidence.STRONG_EVIDENCE: 3,
    }[value]


__all__ = [
    "HoldingPeriod",
    "HoldingPeriodPerformance",
    "IndicatorCombinationResult",
    "MarketRegime",
    "RegimePerformanceSummary",
    "SampleConfidence",
    "StrategyRegimeBacktestResult",
    "StrategyRegimeBacktestRun",
    "StrategyRegimeRank",
    "StrategySignalObservation",
    "StrategyTradeOutcome",
    "confidence_for_sample",
]
