from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from alpha.live.models import LatencySample, LatencySummary, LiveTick


@dataclass(slots=True)
class LatencyMonitor:
    window_size: int = 100
    _samples: deque[LatencySample] = field(default_factory=deque)

    def __post_init__(self) -> None:
        if self.window_size <= 0:
            raise ValueError("latency window size must be positive")

    def record(
        self,
        *,
        symbol: str,
        exchange_timestamp: datetime,
        provider_timestamp: datetime,
        alpha_receive_timestamp: datetime,
        indicator_completion_timestamp: datetime,
        recommendation_completion_timestamp: datetime,
    ) -> LatencySample:
        sample = LatencySample(
            symbol=symbol,
            exchange_timestamp=exchange_timestamp,
            provider_timestamp=provider_timestamp,
            alpha_receive_timestamp=alpha_receive_timestamp,
            indicator_completion_timestamp=indicator_completion_timestamp,
            recommendation_completion_timestamp=recommendation_completion_timestamp,
        )
        self._samples.append(sample)
        while len(self._samples) > self.window_size:
            self._samples.popleft()
        return sample

    def record_from_tick(
        self,
        *,
        tick: LiveTick,
        indicator_completion_timestamp: datetime,
        recommendation_completion_timestamp: datetime,
    ) -> LatencySample | None:
        exchange_timestamp = tick.exchange_timestamp
        provider_timestamp = tick.provider_timestamp
        alpha_receive_timestamp = tick.received_at
        if (
            exchange_timestamp is None
            or provider_timestamp is None
            or alpha_receive_timestamp is None
        ):
            return None
        return self.record(
            symbol=tick.symbol,
            exchange_timestamp=exchange_timestamp,
            provider_timestamp=provider_timestamp,
            alpha_receive_timestamp=alpha_receive_timestamp,
            indicator_completion_timestamp=indicator_completion_timestamp,
            recommendation_completion_timestamp=recommendation_completion_timestamp,
        )

    def summary(self) -> LatencySummary:
        seconds = tuple(
            Decimal(str(sample.end_to_end_latency.total_seconds()))
            for sample in self._samples
        )
        if not seconds:
            return LatencySummary(
                sample_count=0,
                rolling_average_seconds=None,
                rolling_max_seconds=None,
                rolling_p95_seconds=None,
                rolling_p99_seconds=None,
            )
        ordered = tuple(sorted(seconds))
        return LatencySummary(
            sample_count=len(seconds),
            rolling_average_seconds=_quantize(
                sum(seconds, Decimal("0")) / len(seconds)
            ),
            rolling_max_seconds=_quantize(max(seconds)),
            rolling_p95_seconds=_quantize(_percentile(ordered, Decimal("0.95"))),
            rolling_p99_seconds=_quantize(_percentile(ordered, Decimal("0.99"))),
        )


def _percentile(values: tuple[Decimal, ...], percentile: Decimal) -> Decimal:
    if len(values) == 1:
        return values[0]
    index = int(
        (Decimal(len(values) - 1) * percentile).to_integral_value(
            rounding=ROUND_HALF_UP
        )
    )
    return values[index]


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


__all__ = ["LatencyMonitor"]
