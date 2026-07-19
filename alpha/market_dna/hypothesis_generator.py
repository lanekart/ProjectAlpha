from __future__ import annotations

from hashlib import sha256

from alpha.market_dna.models import DNAHypothesis, DNAPattern, DNAPatternStatus


class HypothesisGenerator:
    """Promote only governed candidates, never merely interesting associations."""

    def generate(self, patterns: tuple[DNAPattern, ...]) -> tuple[DNAHypothesis, ...]:
        candidates = tuple(
            item
            for item in patterns
            if item.status is DNAPatternStatus.STRATEGY_HYPOTHESIS_CANDIDATE
        )
        output: list[DNAHypothesis] = []
        for pattern in candidates:
            hypothesis_id = (
                "DNA_HYPOTHESIS_"
                + sha256(pattern.pattern_id.encode()).hexdigest()[:12].upper()
            )
            output.append(
                DNAHypothesis(
                    hypothesis_id=hypothesis_id,
                    originating_pattern_ids=(pattern.pattern_id,),
                    canonical_conditions=pattern.feature_conditions,
                    proposed_entry_logic=(
                        "Use the existing setup-specific recorded entry; do not infer "
                        "a new price level from DNA association."
                    ),
                    avoid_conditions=(
                        pattern.feature_conditions
                        if "LOSER" in pattern.outcome_cohort
                        or "FAILURE" in pattern.outcome_cohort
                        else ()
                    ),
                    proposed_horizon="PRIMARY_RECORDED_HORIZON",
                    expected_mechanism=pattern.hypothesis_text,
                    sample_evidence=(
                        f"sample={pattern.sample_size}; adjusted_p="
                        f"{pattern.adjusted_p_value}; enrichment="
                        f"{pattern.enrichment_ratio}"
                    ),
                    limitations=(
                        "Association is not causation.",
                        "A separate Strategy Lab test and untouched walk-forward test "
                        "are required.",
                    ),
                    required_strategy_lab_test=(
                        "Compare the canonical condition with an otherwise-identical "
                        "baseline."
                    ),
                    required_walk_forward_test=(
                        "Evaluate chronological folds with purge gaps and an untouched "
                        "holdout."
                    ),
                    evidence_class=pattern.evidence_class,
                )
            )
        return tuple(output)


__all__ = ["HypothesisGenerator"]
