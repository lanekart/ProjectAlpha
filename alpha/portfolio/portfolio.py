from dataclasses import dataclass, field

from alpha.portfolio.position import Position


@dataclass
class Portfolio:
    cash: float

    positions: list[Position] = field(default_factory=list)

    closed_positions: list[Position] = field(default_factory=list)

    def open_positions(self) -> list[Position]:
        return [p for p in self.positions if p.status.value != "CLOSED"]

    def add(self, position: Position) -> None:
        self.positions.append(position)

    def close(self, position: Position) -> None:
        self.closed_positions.append(position)
