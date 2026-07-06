from __future__ import annotations

from dataclasses import dataclass, field

from alpha.portfolio.position import Position


@dataclass
class PortfolioBook:
    """
    Institutional portfolio container.

    Maintains every open position keyed by symbol.

    This becomes the single source of truth for
    portfolio positions throughout Alpha.
    """

    _positions: dict[str, Position] = field(default_factory=dict)

    def get(
        self,
        symbol: str,
    ) -> Position | None:
        """
        Return a position if one exists.
        """
        return self._positions.get(symbol)

    def add(
        self,
        position: Position,
    ) -> None:
        """
        Insert or replace a position.
        """
        self._positions[position.symbol] = position

    def contains(
        self,
        symbol: str,
    ) -> bool:
        return symbol in self._positions

    def positions(self) -> tuple[Position, ...]:
        """
        Immutable collection of positions.
        """
        return tuple(self._positions.values())

    def symbols(self) -> tuple[str, ...]:
        """
        Immutable collection of symbols.
        """
        return tuple(self._positions.keys())

    def __len__(self) -> int:
        return len(self._positions)
