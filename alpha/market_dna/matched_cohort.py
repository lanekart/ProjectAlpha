from __future__ import annotations

from alpha.market_dna.models import CohortSummary, FeatureSnapshot, MatchedCohortResult


class MatchedCohortEngine:
    """Deterministic one-to-one matching by horizon, setup, and calendar year."""

    def match(
        self,
        cohort: CohortSummary,
        snapshots: tuple[FeatureSnapshot, ...],
    ) -> MatchedCohortResult:
        cohort_ids = frozenset(cohort.candidate_ids)
        treatment = sorted(
            (item for item in snapshots if item.candidate_id in cohort_ids),
            key=_sort_key,
        )
        controls = sorted(
            (item for item in snapshots if item.candidate_id not in cohort_ids),
            key=_sort_key,
        )
        available = {item.candidate_id: item for item in controls}
        matched_treatment: list[str] = []
        matched_controls: list[str] = []
        for item in treatment:
            candidates = tuple(
                value
                for value in available.values()
                if value.horizon == item.horizon
                and value.setup == item.setup
                and value.candidate_timestamp.year == item.candidate_timestamp.year
            )
            if not candidates:
                continue
            selected = min(
                candidates,
                key=lambda value: (
                    value.symbol != item.symbol,
                    abs((value.candidate_timestamp - item.candidate_timestamp).days),
                    value.symbol,
                    value.candidate_id,
                ),
            )
            matched_treatment.append(item.candidate_id)
            matched_controls.append(selected.candidate_id)
            available.pop(selected.candidate_id)
        limitations = (
            "Matching is exact on recorded horizon, setup, and year.",
            "Unobserved volatility and liquidity confounding remains possible.",
        )
        return MatchedCohortResult(
            cohort_id=cohort.definition.cohort_id,
            cohort_candidates=len(treatment),
            matched_pairs=len(matched_treatment),
            unmatched_cohort=len(treatment) - len(matched_treatment),
            unmatched_baseline=len(controls) - len(matched_controls),
            matching_dimensions=("horizon", "setup", "calendar_year"),
            limitations=limitations,
            matched_candidate_ids=tuple(matched_treatment),
            matched_baseline_ids=tuple(matched_controls),
        )


def _sort_key(item: FeatureSnapshot) -> tuple[object, ...]:
    return item.candidate_timestamp, item.symbol, item.candidate_id


__all__ = ["MatchedCohortEngine"]
