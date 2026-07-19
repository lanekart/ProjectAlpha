from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from alpha.market_dna.models import (
    CohortSummary,
    DNAEvidenceClass,
    FeatureSnapshot,
    OutcomeCohortDefinition,
)


class CohortBuilder:
    """Apply only versioned cohort predicates from OutcomeCohortRegistry."""

    def build(
        self,
        definition: OutcomeCohortDefinition,
        snapshots: tuple[FeatureSnapshot, ...],
    ) -> CohortSummary:
        members = tuple(
            item for item in snapshots if _member(definition.cohort_id, item)
        )
        dates = tuple(item.candidate_timestamp.date() for item in members)
        returns = tuple(item.net_return_pct for item in members)
        evidence = (
            snapshots[0].evidence_class if snapshots else DNAEvidenceClass.PROVISIONAL
        )
        corporate = {item.corporate_action_status for item in members}
        return CohortSummary(
            definition=definition,
            candidate_ids=tuple(item.candidate_id for item in members),
            sample_size=len(members),
            start_date=min(dates) if dates else None,
            end_date=max(dates) if dates else None,
            symbol_count=len({item.symbol for item in members}),
            evidence_class=evidence,
            corporate_action_status=(
                next(iter(corporate)) if len(corporate) == 1 else "MIXED_OR_UNAVAILABLE"
            ),
            reconstruction_status=(
                "RECONSTRUCTED_PROXY"
                if evidence.value == "RECONSTRUCTED"
                else "SOURCE_RECORDED"
            ),
            average_net_return_pct=(
                None
                if not returns
                else (
                    sum(returns, start=Decimal("0")) / Decimal(len(returns))
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            ),
        )


def _member(cohort_id: str, item: FeatureSnapshot) -> bool:
    value = item.net_return_pct
    if cohort_id == "STRONG_WINNERS":
        return value >= Decimal("20")
    if cohort_id == "MODERATE_WINNERS":
        return Decimal("10") <= value < Decimal("20")
    if cohort_id == "SMALL_WINNERS":
        return Decimal("1") < value < Decimal("10")
    if cohort_id == "FLAT_OUTCOMES":
        return Decimal("-1") <= value <= Decimal("1")
    if cohort_id == "SMALL_LOSERS":
        return Decimal("-10") < value < Decimal("-1")
    if cohort_id == "LARGE_LOSERS":
        return Decimal("-25") < value <= Decimal("-10")
    if cohort_id == "CATASTROPHIC_LOSERS":
        return value <= Decimal("-25")
    if cohort_id == "HIGH_MFE_OPPORTUNITIES":
        return item.mfe_pct is not None and item.mfe_pct >= Decimal("15")
    if cohort_id == "HIGH_MAE_FAILURES":
        return item.mae_pct is not None and item.mae_pct <= Decimal("-15")
    if cohort_id == "PROFITABLE_REJECTED":
        return not item.raw_approved and value > Decimal("1")
    if cohort_id == "APPROVED_PROFITABLE":
        return item.raw_approved and value > Decimal("1")
    if cohort_id == "APPROVED_UNPROFITABLE":
        return item.raw_approved and value <= Decimal("0")
    if cohort_id == "MISSED_ENTRY_WINNERS":
        return item.entry_missed_proxy and value > Decimal("1")
    if cohort_id == "STOP_HIT_THEN_RECOVERED":
        return item.stop_touched is True and value > Decimal("1")
    if cohort_id == "TARGET_ACHIEVED":
        return item.target_1_touched is True
    if cohort_id == "TIME_EXPIRED":
        return item.target_1_touched is False and item.stop_touched is False
    raise ValueError(f"cohort predicate is not implemented: {cohort_id}")


__all__ = ["CohortBuilder"]
