from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from alpha.explainability.models import ExplainabilityReport


@dataclass(frozen=True, slots=True)
class ExplainabilityJsonRenderer:
    """Render explainability reports to deterministic JSON-compatible payloads."""

    def render(self, report: ExplainabilityReport) -> dict[str, Any]:
        return report.as_dict()


@dataclass(frozen=True, slots=True)
class ExplainabilityTextRenderer:
    """Render explainability reports to deterministic text lines.

    This renderer is internal. Public CLI/export contracts should decide where
    these lines are embedded so existing report formats remain stable.
    """

    def render(self, report: ExplainabilityReport) -> tuple[str, ...]:
        lines = [
            report.title,
            "",
            f"Observed On : {report.observed_on}",
            f"Confidence  : {report.confidence.value}",
            "",
            "Executive Summary:",
        ]

        lines.extend(
            f"- {bullet.label}: {bullet.detail}" for bullet in report.executive_summary
        )

        for section in report.sections:
            lines.extend(("", f"{section.title}:"))
            lines.extend(
                f"- {bullet.label}: {bullet.detail}" for bullet in section.bullets
            )

        lines.extend(("", "Recommendation Explainability:"))
        for recommendation in report.recommendations:
            lines.extend(
                (
                    f"- {recommendation.symbol}: "
                    f"{recommendation.decision} "
                    f"confidence={recommendation.confidence.value}",
                    f"  Action: {recommendation.action}",
                    f"  Allocation: {recommendation.allocation_decision} "
                    f"weight={recommendation.allocation_weight}",
                )
            )

        return tuple(lines)


__all__ = ["ExplainabilityJsonRenderer", "ExplainabilityTextRenderer"]
