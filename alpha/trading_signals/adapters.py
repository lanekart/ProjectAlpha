from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Protocol

from alpha.trading_signals.models import SignalBatch, SignalSide, TradingSignal

MarketSignalRecord = Mapping[str, object]

_ZERO = Decimal("0")
_ONE = Decimal("1")


class StrategySignalAdapter(Protocol):
    """Protocol for deterministic strategy-to-signal adapters."""

    @property
    def strategy_name(self) -> str:
        """Return the canonical strategy name handled by this adapter."""
        ...

    def generate(
        self,
        *,
        records: Iterable[MarketSignalRecord],
        generated_for: date,
    ) -> SignalBatch:
        """Generate a deterministic signal batch from source records."""
        ...


@dataclass(frozen=True, slots=True)
class MomentumSignalAdapter:
    """Convert normalized momentum signal records into TradingSignal objects."""

    strategy_name: str = "momentum"

    def generate(
        self,
        *,
        records: Iterable[MarketSignalRecord],
        generated_for: date,
    ) -> SignalBatch:
        signals = tuple(
            self._signal_from_record(
                record=record,
                generated_for=generated_for,
            )
            for record in records
        )
        return SignalBatch(
            strategy=self.strategy_name,
            generated_for=generated_for,
            signals=signals,
        )

    def _signal_from_record(
        self,
        *,
        record: MarketSignalRecord,
        generated_for: date,
    ) -> TradingSignal:
        symbol = _required_text(
            record=record,
            key="symbol",
        )
        side = _signal_side(
            _required_text(
                record=record,
                key="signal",
            )
        )
        reference_price = _optional_decimal(
            record=record,
            key="close",
        )
        confidence = _confidence_from_record(record)

        return TradingSignal(
            symbol=symbol,
            side=side,
            strategy=self.strategy_name,
            generated_for=generated_for,
            confidence=confidence,
            reference_price=reference_price,
            reasons=(f"momentum source signal: {side.value}",),
        )


@dataclass(frozen=True, slots=True)
class StrategyAdapterRegistry:
    """Immutable deterministic registry for strategy signal adapters."""

    _adapters: Mapping[str, StrategySignalAdapter]

    def __init__(self, adapters: Iterable[StrategySignalAdapter]) -> None:
        normalized: dict[str, StrategySignalAdapter] = {}
        for adapter in adapters:
            name = adapter.strategy_name.strip().lower()
            if not name:
                raise ValueError("strategy adapter name cannot be empty")
            if name in normalized:
                raise ValueError(f"duplicate strategy adapter: {name}")
            normalized[name] = adapter

        sorted_adapters = dict(sorted(normalized.items()))
        object.__setattr__(
            self,
            "_adapters",
            MappingProxyType(sorted_adapters),
        )

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        return name.strip().lower() in self._adapters

    def __iter__(self) -> Iterator[StrategySignalAdapter]:
        return iter(self._adapters.values())

    def __len__(self) -> int:
        return len(self._adapters)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._adapters)

    def get(self, name: str) -> StrategySignalAdapter:
        normalized_name = name.strip().lower()
        if normalized_name not in self._adapters:
            raise KeyError(f"unknown strategy adapter: {name}")
        return self._adapters[normalized_name]


def default_strategy_adapter_registry() -> StrategyAdapterRegistry:
    """Return the deterministic built-in strategy adapter registry."""

    return StrategyAdapterRegistry((MomentumSignalAdapter(),))


def _required_text(
    *,
    record: MarketSignalRecord,
    key: str,
) -> str:
    if key not in record:
        raise ValueError(f"signal record missing required field: {key}")

    value = str(record[key]).strip()
    if not value:
        raise ValueError(f"signal record field cannot be empty: {key}")
    return value


def _signal_side(value: str) -> SignalSide:
    normalized = value.strip().upper()
    try:
        return SignalSide(normalized)
    except ValueError as error:
        raise ValueError(f"unsupported signal side: {value}") from error


def _optional_decimal(
    *,
    record: MarketSignalRecord,
    key: str,
) -> Decimal | None:
    if key not in record or record[key] is None:
        return None

    try:
        value = Decimal(str(record[key]))
    except InvalidOperation as error:
        raise ValueError(f"signal record field must be decimal: {key}") from error

    if value <= _ZERO:
        raise ValueError(f"signal record field must be positive: {key}")
    return value


def _confidence_from_record(record: MarketSignalRecord) -> Decimal:
    if "confidence" not in record or record["confidence"] is None:
        return _ONE

    try:
        confidence = Decimal(str(record["confidence"]))
    except InvalidOperation as error:
        raise ValueError("signal confidence must be decimal") from error

    if confidence < _ZERO:
        return _ZERO
    if confidence > _ONE:
        return _ONE
    return confidence
