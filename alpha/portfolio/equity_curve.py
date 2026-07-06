from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from alpha.portfolio.portfolio_snapshot import PortfolioSnapshot


@dataclass(frozen=True, slots=True)
class EquityPoint:
    """
    Immutable point-in-time portfolio equity record.
    """

    timestamp: datetime
    equity: Decimal
    cash: Decimal
    market_value: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal

    @classmethod
    def from_snapshot(cls, snapshot: PortfolioSnapshot) -> EquityPoint:
        return cls(
            timestamp=snapshot.timestamp,
            equity=snapshot.total_equity,
            cash=snapshot.cash,
            market_value=snapshot.market_value,
            realized_pnl=snapshot.realized_pnl,
            unrealized_pnl=snapshot.unrealized_pnl,
        )


@dataclass(frozen=True, slots=True)
class EquityCurve:
    """
    Immutable portfolio equity timeline.
    """

    points: tuple[EquityPoint, ...]

    def __init__(self, points: Sequence[EquityPoint]) -> None:
        if not points:
            raise ValueError("EquityCurve cannot be empty")

        normalized = tuple(points)

        previous_timestamp: datetime | None = None

        for point in normalized:
            if previous_timestamp is not None and point.timestamp < previous_timestamp:
                raise ValueError("EquityCurve timestamps must be ordered")

            previous_timestamp = point.timestamp

        object.__setattr__(self, "points", normalized)

    @classmethod
    def from_snapshots(cls, snapshots: Sequence[PortfolioSnapshot]) -> EquityCurve:
        return cls(tuple(EquityPoint.from_snapshot(snapshot) for snapshot in snapshots))

    @property
    def first(self) -> EquityPoint:
        return self.points[0]

    @property
    def last(self) -> EquityPoint:
        return self.points[-1]

    @property
    def starting_equity(self) -> Decimal:
        return self.first.equity

    @property
    def ending_equity(self) -> Decimal:
        return self.last.equity

    @property
    def total_return(self) -> Decimal:
        if self.starting_equity == Decimal("0"):
            return Decimal("0")

        return self.ending_equity / self.starting_equity - Decimal("1")

    @property
    def returns(self) -> tuple[Decimal, ...]:
        values: list[Decimal] = [Decimal("0")]

        for previous, current in zip(self.points, self.points[1:], strict=False):
            if previous.equity == Decimal("0"):
                values.append(Decimal("0"))
            else:
                values.append(current.equity / previous.equity - Decimal("1"))

        return tuple(values)

    @property
    def high_water_marks(self) -> tuple[Decimal, ...]:
        marks: list[Decimal] = []
        current_high = self.first.equity

        for point in self.points:
            if point.equity > current_high:
                current_high = point.equity

            marks.append(current_high)

        return tuple(marks)

    @property
    def drawdowns(self) -> tuple[Decimal, ...]:
        values: list[Decimal] = []

        for point, high_water_mark in zip(
            self.points,
            self.high_water_marks,
            strict=True,
        ):
            if high_water_mark == Decimal("0"):
                values.append(Decimal("0"))
            else:
                values.append(point.equity / high_water_mark - Decimal("1"))

        return tuple(values)

    @property
    def max_drawdown(self) -> Decimal:
        return min(self.drawdowns)

    def __len__(self) -> int:
        return len(self.points)

    def __iter__(self) -> Iterator[EquityPoint]:
        return iter(self.points)

    def __getitem__(self, index: int) -> EquityPoint:
        return self.points[index]
