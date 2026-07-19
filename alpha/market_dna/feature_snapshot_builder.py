from __future__ import annotations

from decimal import Decimal

from alpha.market_dna.models import DNAEvidenceClass, FeatureSnapshot
from alpha.strategy_discovery.models import DiscoveryDataset, HistoricalTruthClass


class FeatureSnapshotBuilder:
    """Keep pre-decision features physically separate from future outcomes."""

    def __init__(self, *, round_trip_cost_pct: Decimal = Decimal("0.30")) -> None:
        if round_trip_cost_pct < Decimal("0"):
            raise ValueError("round-trip cost cannot be negative")
        self.round_trip_cost_pct = round_trip_cost_pct

    def build(self, dataset: DiscoveryDataset) -> tuple[FeatureSnapshot, ...]:
        evidence = _evidence(dataset.population_class)
        snapshots = tuple(self._snapshot(row, evidence) for row in dataset.rows)
        ids = tuple(item.candidate_id for item in snapshots)
        if len(ids) != len(set(ids)):
            raise ValueError("feature snapshots require unique candidate ids")
        return snapshots

    def _snapshot(
        self,
        row: object,
        evidence: DNAEvidenceClass,
    ) -> FeatureSnapshot:
        from alpha.strategy_discovery.models import DiscoveryRow

        if not isinstance(row, DiscoveryRow):
            raise TypeError("snapshot source must be a DiscoveryRow")
        if row.realised_return_pct is None:
            raise ValueError("snapshot source requires a realised return")
        entry = row.confirmation_entry or row.entry_zone_high or row.entry_zone_low
        target_touched = _target_touched(row, entry)
        stop_touched = _stop_touched(row, entry)
        return FeatureSnapshot(
            candidate_id=row.candidate_id,
            candidate_timestamp=row.candidate_timestamp,
            feature_timestamp=row.feature_timestamp,
            symbol=row.symbol,
            setup=row.setup or "UNAVAILABLE",
            horizon=row.outcome_horizon,
            evidence_class=evidence,
            corporate_action_status=row.corporate_action_status,
            feature_values=row.features,
            realised_outcome=row.realised_outcome,
            gross_return_pct=row.realised_return_pct,
            net_return_pct=row.realised_return_pct - self.round_trip_cost_pct,
            realised_r_multiple=row.realised_r_multiple,
            mfe_pct=row.mfe_pct,
            mae_pct=row.mae_pct,
            target_1_touched=target_touched,
            stop_touched=stop_touched,
            raw_approved=row.features.get("raw_approved") == "true",
            entry_missed_proxy=(row.entry_timing_state != "BUY"),
        )


def _target_touched(row: object, entry: Decimal | None) -> bool | None:
    from alpha.strategy_discovery.models import DiscoveryRow

    if not isinstance(row, DiscoveryRow):
        return None
    if (
        entry is None
        or entry <= Decimal("0")
        or row.target_1 is None
        or row.mfe_pct is None
    ):
        return None
    distance = (row.target_1 - entry) / entry * Decimal("100")
    return distance > Decimal("0") and row.mfe_pct >= distance


def _stop_touched(row: object, entry: Decimal | None) -> bool | None:
    from alpha.strategy_discovery.models import DiscoveryRow

    if not isinstance(row, DiscoveryRow):
        return None
    if (
        entry is None
        or entry <= Decimal("0")
        or row.stop_loss is None
        or row.mae_pct is None
    ):
        return None
    distance = (entry - row.stop_loss) / entry * Decimal("100")
    return distance > Decimal("0") and row.mae_pct <= -distance


def _evidence(value: HistoricalTruthClass) -> DNAEvidenceClass:
    if value is HistoricalTruthClass.AUTHORITATIVE:
        return DNAEvidenceClass.AUTHORITATIVE
    if value is HistoricalTruthClass.RECONSTRUCTED:
        return DNAEvidenceClass.RECONSTRUCTED
    return DNAEvidenceClass.PROVISIONAL


__all__ = ["FeatureSnapshotBuilder"]
