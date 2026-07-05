from __future__ import annotations

from dataclasses import dataclass, field

from alpha.portfolio.enums import PositionStatus
from alpha.portfolio.position import Position


@dataclass
class Portfolio:
    cash: float = 0.0

    positions: list[Position] = field(default_factory=list)
    closed_positions: list[Position] = field(default_factory=list)

    def open_positions(self) -> list[Position]:
        return [p for p in self.positions if p.status is not PositionStatus.CLOSED]

    def add(self, position: Position) -> None:
        self.positions.append(position)

    def close(self, position: Position) -> None:
        if position not in self.closed_positions:
            self.closed_positions.append(position)
