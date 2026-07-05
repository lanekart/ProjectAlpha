from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from random import Random
from uuid import UUID, uuid4

from alpha.execution.fill import Fill

PriceProvider = Callable[[str], Decimal]


@dataclass
class ExecutionSimulator:
    """
    Simulates market microstructure.

    Modes:
    - deterministic (default)
    - stochastic
    """

    seed: int = 42
    deterministic: bool = True
    price_provider: PriceProvider | None = None

    _rng: Random = field(init=False, repr=False)
    _clock: datetime = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = Random(self.seed)
        self._clock = datetime.now(UTC)

    def simulate_market_fill(
        self,
        order_id: UUID,
        symbol: str,
        quantity: int,
    ) -> tuple[Fill, ...]:
        base_price = self._get_price(symbol)

        remaining = quantity
        fills: list[Fill] = []

        if self._rng.random() < 0.5:
            return (
                self._create_fill(
                    order_id,
                    base_price,
                    quantity,
                ),
            )

        while remaining > 0:
            chunk = max(
                1,
                int(abs(self._rng.gauss(remaining / 2, remaining / 4))),
            )
            chunk = min(chunk, remaining)

            slippage_pct = Decimal(str(self._rng.uniform(-0.2, 0.5)))

            price = base_price + (base_price * slippage_pct / Decimal("100"))

            fills.append(
                self._create_fill(
                    order_id,
                    price,
                    chunk,
                )
            )

            remaining -= chunk

        return tuple(fills)

    def _get_price(self, symbol: str) -> Decimal:
        if self.price_provider is not None:
            return self.price_provider(symbol)

        return Decimal("100")

    def _create_fill(
        self,
        order_id: UUID,
        price: Decimal,
        quantity: int,
    ) -> Fill:
        self._clock = self._clock.replace(
            microsecond=(self._clock.microsecond + 1) % 1_000_000
        )

        return Fill(
            fill_id=uuid4(),
            order_id=order_id,
            quantity=quantity,
            price=price,
            timestamp=self._clock,
        )
