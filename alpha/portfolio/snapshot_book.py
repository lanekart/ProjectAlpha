from __future__ import annotations

from dataclasses import dataclass, field

from alpha.portfolio.portfolio_snapshot import PortfolioSnapshot


@dataclass
class SnapshotBook:
    """
    Immutable storage of portfolio snapshots.

    Snapshots are append-only checkpoints that allow
    rapid reconstruction of portfolio state.
    """

    _snapshots: list[PortfolioSnapshot] = field(default_factory=list)

    def append(self, snapshot: PortfolioSnapshot) -> None:
        self._snapshots.append(snapshot)

    def latest(self) -> PortfolioSnapshot | None:
        if not self._snapshots:
            return None
        return self._snapshots[-1]

    def all(self) -> tuple[PortfolioSnapshot, ...]:
        return tuple(self._snapshots)

    def __len__(self) -> int:
        return len(self._snapshots)
