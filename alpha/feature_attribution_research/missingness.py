"""Catalogue institutional information absent from the legacy dataset."""

from __future__ import annotations

from alpha.feature_attribution_research.models import (
    FeatureAvailability,
    MissingInformationRecord,
)


class MissingInformationAudit:
    def audit(self) -> tuple[MissingInformationRecord, ...]:
        rows = (
            _row(
                "delivery_percentage",
                FeatureAvailability.FREE_SOURCE_POSSIBLE,
                "Official exchange delivery archives require separate historical "
                "intake and licensing review.",
                "Direct participation quality is not a transformation of price alone.",
                1,
            ),
            _row(
                "bid_ask_spread",
                FeatureAvailability.PAID_SOURCE_REQUIRED,
                "No historical quote or spread series exists in Alpha.",
                "Measures execution friction rather than directional price structure.",
                None,
            ),
            _row(
                "order_book_imbalance",
                FeatureAvailability.PAID_SOURCE_REQUIRED,
                "No historical Level 2 order-book archive exists in Alpha.",
                "Microstructure pressure is distinct from daily OHLCV.",
                None,
            ),
            _row(
                "free_float",
                FeatureAvailability.CURRENT_ONLY_NOT_HISTORICAL,
                "Point-in-time shares and free-float history are not persisted.",
                "Capacity and ownership structure are distinct from technical "
                "features.",
                None,
            ),
            _row(
                "promoter_holding_changes",
                FeatureAvailability.FREE_SOURCE_POSSIBLE,
                "Quarterly filings are not normalized into a historical point-in-time "
                "series.",
                "Ownership change can separate accumulation from price-only "
                "lookalikes.",
                None,
            ),
            _row(
                "FII_holding_changes",
                FeatureAvailability.FREE_SOURCE_POSSIBLE,
                "Quarterly institutional ownership history is not integrated.",
                "Institutional sponsorship is economically distinct from OHLCV "
                "transforms.",
                3,
            ),
            _row(
                "DII_holding_changes",
                FeatureAvailability.FREE_SOURCE_POSSIBLE,
                "Quarterly institutional ownership history is not integrated.",
                "Domestic sponsorship is distinct from price and volume indicators.",
                None,
            ),
            _row(
                "mutual_fund_holding_changes",
                FeatureAvailability.FREE_SOURCE_POSSIBLE,
                "Fund ownership disclosures are not normalized point in time.",
                "Fund sponsorship is distinct from technical indicators.",
                None,
            ),
            _row(
                "insider_transactions",
                FeatureAvailability.FREE_SOURCE_POSSIBLE,
                "Exchange disclosures are not ingested or identity-reconciled.",
                "Insider behavior is independent evidence when timestamped correctly.",
                None,
            ),
            _row(
                "block_deals",
                FeatureAvailability.FREE_SOURCE_POSSIBLE,
                "Historical block and bulk deals are not integrated.",
                "Large negotiated flows can explain volume not visible in OHLCV alone.",
                None,
            ),
            _row(
                "earnings_surprise",
                FeatureAvailability.PAID_SOURCE_REQUIRED,
                "Alpha has no point-in-time consensus expectation history.",
                "Fundamental surprise is independent of technical feature lineage.",
                None,
            ),
            _row(
                "earnings_revision",
                FeatureAvailability.PAID_SOURCE_REQUIRED,
                "Alpha has no historical analyst-estimate revision series.",
                "Estimate revisions provide an orthogonal fundamental catalyst "
                "dimension.",
                2,
            ),
            _row(
                "order_book_growth",
                FeatureAvailability.UNAVAILABLE,
                "Company order-book disclosures are unstructured and not stored "
                "point in time.",
                "Business demand evidence is distinct from market-price behavior.",
                None,
            ),
            _row(
                "sector_flow",
                FeatureAvailability.UNAVAILABLE,
                "Authoritative point-in-time sector membership and flow data are "
                "absent.",
                "Cross-sectional capital rotation is distinct from single-stock "
                "features.",
                None,
            ),
            _row(
                "institutional_accumulation",
                FeatureAvailability.UNAVAILABLE,
                "Delivery, ownership, and transaction evidence required for this "
                "label is absent.",
                "True institutional accumulation cannot be inferred from volume alone.",
                None,
            ),
        )
        return tuple(sorted(rows, key=lambda item: item.feature_id.lower()))


def _row(
    feature_id: str,
    availability: FeatureAvailability,
    limitation: str,
    rationale: str,
    priority: int | None,
) -> MissingInformationRecord:
    return MissingInformationRecord(
        feature_id=feature_id,
        availability=availability,
        current_source=None,
        orthogonality_rationale=rationale,
        priority=priority,
        limitation=limitation,
    )


__all__ = ["MissingInformationAudit"]
