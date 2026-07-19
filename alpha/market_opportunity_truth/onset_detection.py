from __future__ import annotations

import hashlib

from alpha.market_opportunity_truth.models import OpportunitySeed, RawOpportunityOnset
from alpha.market_opportunity_truth.opportunity_clusters import assign_natural_cluster
from alpha.market_opportunity_truth.opportunity_quality import OpportunityQualityEngine
from alpha.market_opportunity_truth.tradability import OpportunityTradabilityEngine


class PointInTimeOnsetEngine:
    """Freeze all quality and cluster decisions before outcomes are attached."""

    def classify(
        self,
        onsets: tuple[RawOpportunityOnset, ...],
    ) -> tuple[OpportunitySeed, ...]:
        rows = []
        quality_engine = OpportunityQualityEngine()
        tradability_engine = OpportunityTradabilityEngine()
        for onset in onsets:
            tradability = tradability_engine.assess(onset)
            quality = quality_engine.assess(onset, tradability)
            provisional = OpportunitySeed(
                onset=onset,
                tradability=tradability,
                quality=quality,
                cluster_id="UNASSIGNED",
                cluster_explanation="UNASSIGNED",
                point_in_time_decision_hash="UNASSIGNED",
            )
            cluster_id, cluster_explanation = assign_natural_cluster(provisional)
            decision_hash = _decision_hash(
                onset=onset,
                seed=provisional,
                cluster_id=cluster_id,
            )
            rows.append(
                OpportunitySeed(
                    onset=onset,
                    tradability=tradability,
                    quality=quality,
                    cluster_id=cluster_id,
                    cluster_explanation=cluster_explanation,
                    point_in_time_decision_hash=decision_hash,
                )
            )
        return tuple(rows)


def _decision_hash(
    *,
    onset: RawOpportunityOnset,
    seed: OpportunitySeed,
    cluster_id: str,
) -> str:
    payload = "|".join(
        (
            onset.opportunity_id,
            onset.evidence_hash,
            str(seed.tradability.tradable),
            seed.tradability.liquidity_state.value,
            seed.tradability.trend_state.value,
            seed.tradability.volatility_state.value,
            seed.quality.quality.value,
            str(seed.quality.score),
            cluster_id,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["PointInTimeOnsetEngine"]
