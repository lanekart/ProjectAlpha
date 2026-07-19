"""Cross-record integrity validation for universe evidence."""

from __future__ import annotations

from dataclasses import dataclass

from alpha.point_in_time_universe.corporate_actions import CorporateActionHistory
from alpha.point_in_time_universe.index_membership import IndexMembershipHistory
from alpha.point_in_time_universe.listing_history import ListingHistory
from alpha.point_in_time_universe.models import EvidenceStatus, UniverseSnapshot
from alpha.point_in_time_universe.sector_history import SectorHistory
from alpha.point_in_time_universe.security_master import SecurityMaster
from alpha.point_in_time_universe.survivorship_audit import SurvivorshipAuditEngine


@dataclass(frozen=True, slots=True)
class UniverseIntegrityReport:
    securities: int
    orphan_listing_records: int
    orphan_index_records: int
    orphan_sector_records: int
    orphan_corporate_actions: int
    survivorship_failures: int
    future_constituent_leaks: int
    unknown_index_snapshots: int
    unknown_sector_members: int
    passed: bool


class UniverseIntegrityEngine:
    def validate(
        self,
        *,
        security_master: SecurityMaster,
        listings: ListingHistory,
        indices: IndexMembershipHistory,
        sectors: SectorHistory,
        corporate_actions: CorporateActionHistory,
        snapshots: tuple[UniverseSnapshot, ...],
    ) -> UniverseIntegrityReport:
        identities = {item.security_id for item in security_master.records}
        orphan_listing = sum(
            item.security_id not in identities for item in listings.records
        )
        orphan_index = sum(
            item.security_id not in identities for item in indices.records
        )
        orphan_sector = sum(
            item.security_id not in identities for item in sectors.records
        )
        orphan_action_ids = {
            security_id
            for item in corporate_actions.records
            for security_id in (
                item.security_id,
                *item.predecessor_security_ids,
                *item.successor_security_ids,
            )
            if security_id not in identities
        }
        orphan_actions = len(orphan_action_ids)
        audits = tuple(
            SurvivorshipAuditEngine().audit(snapshot, security_master=security_master)
            for snapshot in snapshots
        )
        survivorship_failures = sum(item.invalid_security_count for item in audits)
        future_leaks = sum(item.future_constituent_leaks for item in audits)
        unknown_indices = sum(
            item.status is EvidenceStatus.UNKNOWN
            for snapshot in snapshots
            for item in snapshot.index_snapshots
        )
        unknown_sectors = sum(item.unknown_sector_count for item in audits)
        hard_failures = (
            orphan_listing
            + orphan_index
            + orphan_sector
            + orphan_actions
            + survivorship_failures
            + future_leaks
        )
        return UniverseIntegrityReport(
            securities=len(identities),
            orphan_listing_records=orphan_listing,
            orphan_index_records=orphan_index,
            orphan_sector_records=orphan_sector,
            orphan_corporate_actions=orphan_actions,
            survivorship_failures=survivorship_failures,
            future_constituent_leaks=future_leaks,
            unknown_index_snapshots=unknown_indices,
            unknown_sector_members=unknown_sectors,
            passed=hard_failures == 0,
        )


__all__ = ["UniverseIntegrityEngine", "UniverseIntegrityReport"]
