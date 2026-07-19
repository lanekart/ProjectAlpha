from __future__ import annotations

from decimal import Decimal

from alpha.decision_intelligence.models import CapacityAssessment


class CapacityAssessor:
    def assess(
        self,
        *,
        price: Decimal | None,
        volume: Decimal | None,
        average_volume: Decimal | None,
        spread_percent: Decimal | None = None,
        feed_quality: Decimal | None = None,
    ) -> CapacityAssessment:
        if price is None or volume is None:
            return CapacityAssessment(
                capacity_score=Decimal("0"),
                deployable_capital_estimate=None,
                liquidity_warning="Insufficient price or volume data.",
                explanation=(
                    "Capacity unavailable because traded value cannot be computed."
                ),
                data_sufficient=False,
            )
        traded_value = price * volume
        deployable = traded_value * Decimal("0.01")
        score = min(traded_value / Decimal("1000000") * Decimal("100"), Decimal("100"))
        warning = None
        reasons = [f"Traded value available: {traded_value.quantize(Decimal('0.01'))}."]

        if average_volume is not None and average_volume > Decimal("0"):
            volume_ratio = volume / average_volume
            if volume_ratio < Decimal("0.30"):
                score *= Decimal("0.50")
                warning = "Current volume is materially below average."
            reasons.append(
                f"Volume is {volume_ratio.quantize(Decimal('0.01'))}x average."
            )
        if spread_percent is not None and spread_percent > Decimal("1"):
            score *= Decimal("0.70")
            warning = "Live spread is wide."
            reasons.append("Spread reduced capacity quality.")
        if feed_quality is not None and feed_quality < Decimal("70"):
            score *= Decimal("0.50")
            warning = "Live feed quality is degraded."
            reasons.append("Feed quality reduced capacity quality.")

        return CapacityAssessment(
            capacity_score=max(score, Decimal("0")).quantize(Decimal("0.01")),
            deployable_capital_estimate=deployable,
            liquidity_warning=warning,
            explanation=" ".join(reasons),
            data_sufficient=True,
        )


__all__ = ["CapacityAssessor"]
