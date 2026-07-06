from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alpha.analysis.portfolio.report import PortfolioAnalyticsReport
from alpha.portfolio.portfolio_snapshot import PortfolioSnapshot, PositionSnapshot


@dataclass(frozen=True, slots=True)
class PortfolioAnalyticsEngine:
    """
    Computes immutable analytics from a portfolio snapshot.
    """

    def analyze(self, snapshot: PortfolioSnapshot) -> PortfolioAnalyticsReport:
        total_equity = snapshot.total_equity

        largest_position = self._largest_position(snapshot.positions)

        long_count = sum(1 for position in snapshot.positions if position.quantity > 0)

        short_count = sum(1 for position in snapshot.positions if position.quantity < 0)

        return PortfolioAnalyticsReport(
            cash=snapshot.cash,
            market_value=snapshot.market_value,
            total_equity=total_equity,
            gross_exposure=snapshot.gross_exposure,
            net_exposure=snapshot.net_exposure,
            cash_weight=self._safe_divide(
                snapshot.cash,
                total_equity,
            ),
            gross_exposure_weight=self._safe_divide(
                snapshot.gross_exposure,
                total_equity,
            ),
            net_exposure_weight=self._safe_divide(
                snapshot.net_exposure,
                total_equity,
            ),
            position_count=snapshot.position_count,
            long_count=long_count,
            short_count=short_count,
            largest_position_symbol=(
                largest_position.symbol if largest_position is not None else None
            ),
            largest_position_weight=(
                self._safe_divide(
                    largest_position.market_value,
                    total_equity,
                )
                if largest_position is not None
                else Decimal("0")
            ),
        )

    def _largest_position(
        self,
        positions: tuple[PositionSnapshot, ...],
    ) -> PositionSnapshot | None:
        if not positions:
            return None

        return max(
            positions,
            key=lambda position: position.market_value,
        )

    def _safe_divide(
        self,
        numerator: Decimal,
        denominator: Decimal,
    ) -> Decimal:
        if denominator == Decimal("0"):
            return Decimal("0")

        return numerator / denominator
