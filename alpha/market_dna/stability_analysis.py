from __future__ import annotations

from decimal import Decimal
from hashlib import sha256

from alpha.market_dna.models import (
    DNAEvidenceClass,
    DNAPattern,
    DNAPatternStatus,
    FeatureFinding,
    InteractionFinding,
    PatternDirection,
    TemporalStability,
)


class StabilityAnalysis:
    """Convert all findings into immutable accepted or rejected DNA records."""

    def patterns(
        self,
        *,
        findings: tuple[FeatureFinding, ...],
        interactions: tuple[InteractionFinding, ...],
        minimum_sample: int,
    ) -> tuple[DNAPattern, ...]:
        output = [self._feature_pattern(item, minimum_sample) for item in findings]
        output.extend(
            self._interaction_pattern(item, minimum_sample) for item in interactions
        )
        return tuple(sorted(output, key=lambda item: item.pattern_id))

    def _feature_pattern(
        self, finding: FeatureFinding, minimum_sample: int
    ) -> DNAPattern:
        status, reasons = _feature_status(finding, minimum_sample)
        pattern_id = (
            "DNA_PATTERN_"
            + sha256(finding.finding_id.encode()).hexdigest()[:16].upper()
        )
        return DNAPattern(
            pattern_id=pattern_id,
            version="DNA_PATTERN_V1",
            title=f"{finding.cohort_id}: {finding.condition.canonical_key}",
            outcome_cohort=finding.cohort_id,
            scope=finding.scope,
            feature_conditions=(finding.condition,),
            direction=finding.direction,
            enrichment_ratio=finding.enrichment_ratio,
            effect_size=finding.effect_size,
            confidence_interval_low=finding.confidence_interval_low,
            confidence_interval_high=finding.confidence_interval_high,
            adjusted_p_value=finding.adjusted_p_value,
            sample_size=finding.cohort_match_count,
            years_represented=finding.years_represented,
            symbols_represented=finding.symbols_represented,
            fold_stability_pct=finding.fold_consistency_pct,
            symbol_concentration_pct=finding.symbol_concentration_pct,
            period_concentration_pct=finding.period_concentration_pct,
            winner_concentration_pct=finding.winner_concentration_pct,
            evidence_class=finding.evidence_class,
            lineage_risks=finding.lineage_risks,
            robustness_classification=finding.temporal_stability,
            status=status,
            hypothesis_text=_hypothesis_text(finding),
            rejection_reasons=reasons,
        )

    def _interaction_pattern(
        self, finding: InteractionFinding, minimum_sample: int
    ) -> DNAPattern:
        status, reasons = _interaction_status(finding, minimum_sample)
        return DNAPattern(
            pattern_id="DNA_PATTERN_"
            + sha256(finding.interaction_id.encode()).hexdigest()[:16].upper(),
            version="DNA_PATTERN_V1",
            title=f"{finding.cohort_id}: interaction {finding.interaction_id}",
            outcome_cohort=finding.cohort_id,
            scope="INTERACTION",
            feature_conditions=finding.conditions,
            direction=(
                PatternDirection.ENRICHED
                if finding.enrichment_ratio is not None
                and finding.enrichment_ratio >= Decimal("1")
                else PatternDirection.DEPLETED
            ),
            enrichment_ratio=finding.enrichment_ratio,
            effect_size=finding.effect_size,
            confidence_interval_low=None,
            confidence_interval_high=None,
            adjusted_p_value=finding.adjusted_p_value,
            sample_size=finding.sample_size,
            years_represented=0,
            symbols_represented=0,
            fold_stability_pct=finding.fold_consistency_pct,
            symbol_concentration_pct=finding.symbol_concentration_pct,
            period_concentration_pct=None,
            winner_concentration_pct=None,
            evidence_class=DNAEvidenceClass.RECONSTRUCTED,
            lineage_risks=("same-source interaction",)
            if finding.lineage_penalty
            else (),
            robustness_classification=(
                TemporalStability.STABLE
                if finding.fold_consistency_pct is not None
                and finding.fold_consistency_pct >= Decimal("67")
                else TemporalStability.UNSTABLE
            ),
            status=status,
            hypothesis_text=(
                "Test whether the bounded interaction separates this outcome cohort "
                "under untouched chronological validation."
            ),
            rejection_reasons=reasons,
        )


def _feature_status(
    item: FeatureFinding, minimum_sample: int
) -> tuple[DNAPatternStatus, tuple[str, ...]]:
    if (
        item.cohort_match_count < minimum_sample
        or item.baseline_match_count < minimum_sample
    ):
        return DNAPatternStatus.INSUFFICIENT_SAMPLE, ("minimum sample not met",)
    if item.adjusted_p_value is None or item.adjusted_p_value > Decimal("0.05"):
        return DNAPatternStatus.MULTIPLE_TESTING_FAILURE, (
            "finding did not survive false-discovery control",
        )
    if _high_concentration(item):
        return DNAPatternStatus.CONCENTRATED, (
            "finding is excessively concentrated by symbol, period, or winner",
        )
    if item.temporal_stability not in {
        TemporalStability.STABLE,
        TemporalStability.EMERGING,
    }:
        return DNAPatternStatus.UNSTABLE, ("temporal stability requirement failed",)
    if item.evidence_class is DNAEvidenceClass.RECONSTRUCTED:
        return DNAPatternStatus.RECONSTRUCTED_RESEARCH_ONLY, (
            "reconstructed discovery has no untouched authoritative holdout",
        )
    return DNAPatternStatus.STRATEGY_HYPOTHESIS_CANDIDATE, ()


def _interaction_status(
    item: InteractionFinding, minimum_sample: int
) -> tuple[DNAPatternStatus, tuple[str, ...]]:
    if item.sample_size < minimum_sample or item.baseline_size < minimum_sample:
        return DNAPatternStatus.INSUFFICIENT_SAMPLE, ("minimum cell not met",)
    if item.lineage_penalty:
        return DNAPatternStatus.LINEAGE_CONFOUNDED, ("same-source overlap",)
    if item.adjusted_p_value is None or item.adjusted_p_value > Decimal("0.05"):
        return DNAPatternStatus.MULTIPLE_TESTING_FAILURE, (
            "interaction failed false-discovery control",
        )
    if (
        item.symbol_concentration_pct is not None
        and item.symbol_concentration_pct > Decimal("50")
    ):
        return DNAPatternStatus.CONCENTRATED, (
            "symbol concentration exceeds 50 percent",
        )
    if item.fold_consistency_pct is None or item.fold_consistency_pct < Decimal("67"):
        return DNAPatternStatus.UNSTABLE, (
            "chronological fold consistency is insufficient",
        )
    return DNAPatternStatus.RECONSTRUCTED_RESEARCH_ONLY, (
        "interaction is reconstructed discovery evidence only",
    )


def _high_concentration(item: FeatureFinding) -> bool:
    return any(
        value is not None and value > Decimal("50")
        for value in (
            item.symbol_concentration_pct,
            item.period_concentration_pct,
            item.winner_concentration_pct,
        )
    )


def _hypothesis_text(item: FeatureFinding) -> str:
    relation = (
        "more common" if item.direction is PatternDirection.ENRICHED else "less common"
    )
    return (
        f"{item.condition.canonical_key} may be {relation} in {item.cohort_id}; "
        "test the fixed condition in Strategy Lab and untouched chronological folds."
    )


__all__ = ["StabilityAnalysis"]
