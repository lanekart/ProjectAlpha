from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from alpha.data_platform.models import (
    ConfidenceAssessment,
    ConfidenceEvidence,
    ConfidenceLevel,
)


class ConfidenceEngine:
    """Calculate bounded confidence from explicit historical-truth evidence."""

    def assess(self, evidence: ConfidenceEvidence) -> ConfidenceAssessment:
        score = Decimal("0")
        reasons: list[str] = []
        if evidence.source_official:
            score += Decimal("35")
            reasons.append("Official source evidence contributes 35 points.")
        else:
            reasons.append("Source is not official; confidence cannot be HIGH.")
        if evidence.reconciled:
            score += Decimal("20")
            reasons.append("Independent reconciliation contributes 20 points.")
        score += evidence.completeness * Decimal("20")
        score += evidence.identity_certainty * Decimal("10")
        if evidence.corporate_actions_complete:
            score += Decimal("10")
        if evidence.conflict_count == 0:
            score += Decimal("5")
        else:
            score -= min(Decimal("20"), Decimal(evidence.conflict_count * 5))
            reasons.append("Unresolved source conflicts cap confidence at LOW.")
        if evidence.unknown_field_count:
            score -= min(Decimal("20"), Decimal(evidence.unknown_field_count * 2))
            reasons.append("Unknown fields reduce confidence.")
        score = max(Decimal("0"), min(Decimal("100"), score)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        capped = False
        if evidence.conflict_count:
            level = ConfidenceLevel.LOW
            capped = True
        elif score >= Decimal("85") and evidence.source_official:
            level = ConfidenceLevel.HIGH
        elif score >= Decimal("60"):
            level = ConfidenceLevel.MEDIUM
        else:
            level = ConfidenceLevel.LOW
        if level is ConfidenceLevel.HIGH and evidence.unknown_field_count:
            level = ConfidenceLevel.MEDIUM
            capped = True
            reasons.append("Unknown fields prevent a HIGH classification.")
        return ConfidenceAssessment(
            level=level,
            score=score,
            reasons=tuple(reasons),
            capped=capped,
        )


__all__ = ["ConfidenceEngine"]
