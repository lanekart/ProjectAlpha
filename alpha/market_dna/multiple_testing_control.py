from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from alpha.market_dna.models import (
    FeatureFinding,
    InteractionFinding,
    MultipleTestingSummary,
)


class FalseDiscoveryControl:
    """Benjamini-Hochberg false-discovery control across tested hypotheses."""

    def adjust_findings(
        self,
        findings: tuple[FeatureFinding, ...],
        *,
        threshold: Decimal = Decimal("0.05"),
    ) -> tuple[tuple[FeatureFinding, ...], MultipleTestingSummary]:
        adjusted = _adjust(
            tuple((item.finding_id, item.raw_p_value) for item in findings)
        )
        output = tuple(
            replace(item, adjusted_p_value=adjusted.get(item.finding_id))
            for item in findings
        )
        surviving = sum(
            item.adjusted_p_value is not None and item.adjusted_p_value <= threshold
            for item in output
        )
        return output, MultipleTestingSummary(
            hypotheses_tested=len(findings),
            effective_hypotheses=len(adjusted),
            procedure="BENJAMINI_HOCHBERG_FDR",
            significance_threshold=threshold,
            surviving_findings=surviving,
            rejected_findings=len(findings) - surviving,
        )

    def adjust_interactions(
        self,
        interactions: tuple[InteractionFinding, ...],
    ) -> tuple[InteractionFinding, ...]:
        adjusted = _adjust(
            tuple((item.interaction_id, item.raw_p_value) for item in interactions)
        )
        return tuple(
            replace(item, adjusted_p_value=adjusted.get(item.interaction_id))
            for item in interactions
        )


def _adjust(items: tuple[tuple[str, Decimal | None], ...]) -> dict[str, Decimal]:
    available = sorted(
        ((key, value) for key, value in items if value is not None),
        key=lambda item: (item[1], item[0]),
    )
    total = len(available)
    if total == 0:
        return {}
    output: dict[str, Decimal] = {}
    running = Decimal("1")
    for reverse_index, (key, value) in enumerate(reversed(available), start=1):
        rank = total - reverse_index + 1
        candidate = min(Decimal("1"), value * Decimal(total) / Decimal(rank))
        running = min(running, candidate)
        output[key] = running.quantize(Decimal("0.000001"))
    return output


__all__ = ["FalseDiscoveryControl"]
