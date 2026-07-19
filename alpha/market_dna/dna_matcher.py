from __future__ import annotations

from decimal import Decimal

from alpha.market_dna.effect_size_engine import condition_matches
from alpha.market_dna.models import DNAMatchResult, DNAPattern, FeatureSnapshot


class ResearchDNAMatcher:
    """Retrospective matcher that is intentionally absent from recommendation paths."""

    def match(
        self,
        pattern: DNAPattern,
        snapshot: FeatureSnapshot,
    ) -> DNAMatchResult:
        matched: list[str] = []
        unmatched: list[str] = []
        missing: list[str] = []
        for condition in pattern.feature_conditions:
            value = snapshot.feature_values.get(condition.feature_id)
            if value is None or value.lower() == "unavailable":
                missing.append(condition.canonical_key)
            elif condition_matches(condition, snapshot):
                matched.append(condition.canonical_key)
            else:
                unmatched.append(condition.canonical_key)
        total = len(pattern.feature_conditions)
        similarity = (
            None
            if total == 0
            else (Decimal(len(matched)) / Decimal(total) * Decimal("100")).quantize(
                Decimal("0.01")
            )
        )
        return DNAMatchResult(
            pattern_id=pattern.pattern_id,
            candidate_id=snapshot.candidate_id,
            matched_conditions=tuple(matched),
            unmatched_conditions=tuple(unmatched),
            missing_conditions=tuple(missing),
            pattern_support=pattern.sample_size,
            evidence_quality=pattern.evidence_class.value,
            cohort_similarity_pct=similarity,
        )


__all__ = ["ResearchDNAMatcher"]
