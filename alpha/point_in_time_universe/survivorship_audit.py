"""Survivorship and future-constituent leakage diagnostics."""

from __future__ import annotations

from alpha.point_in_time_universe.models import (
    EvidenceStatus,
    SurvivorshipAuditRecord,
    SurvivorshipFailureCode,
    SurvivorshipStatus,
    TradabilityStatus,
    UniverseSnapshot,
)
from alpha.point_in_time_universe.security_master import SecurityMaster


class SurvivorshipAuditEngine:
    def audit(
        self,
        snapshot: UniverseSnapshot,
        *,
        security_master: SecurityMaster,
    ) -> SurvivorshipAuditRecord:
        invalid = future = stale_sector = unknown_sector = 0
        failures: set[SurvivorshipFailureCode] = set()
        for member in snapshot.members:
            identity = security_master.get(member.security_id)
            if identity is None:
                invalid += 1
                continue
            existed = identity.existed_on(snapshot.as_of)
            if existed is False:
                invalid += 1
                if identity.listing_date and snapshot.as_of < identity.listing_date:
                    future += 1
                    failures.add(SurvivorshipFailureCode.SECURITY_BEFORE_LISTING)
                    failures.add(SurvivorshipFailureCode.FUTURE_CONSTITUENT_LEAK)
                else:
                    failures.add(SurvivorshipFailureCode.SECURITY_AFTER_DELISTING)
            if identity.symbol_on(snapshot.as_of) != member.symbol:
                invalid += 1
                failures.add(SurvivorshipFailureCode.SYMBOL_OUTSIDE_EFFECTIVE_INTERVAL)
            if member.sector_status is EvidenceStatus.UNKNOWN:
                unknown_sector += 1
            elif member.sector_status is EvidenceStatus.CONFLICTED:
                stale_sector += 1
                failures.add(SurvivorshipFailureCode.STALE_SECTOR_MAPPING)
            if member.tradability in {
                TradabilityStatus.NOT_YET_LISTED,
                TradabilityStatus.DELISTED,
            }:
                invalid += 1
        unknown_indices = sum(
            item.status is EvidenceStatus.UNKNOWN for item in snapshot.index_snapshots
        )
        if unknown_indices:
            failures.add(SurvivorshipFailureCode.UNKNOWN_INDEX_HISTORY)
        if unknown_sector:
            failures.add(SurvivorshipFailureCode.UNKNOWN_SECTOR_HISTORY)
        if "CORPORATE_ACTIONS" in snapshot.unknown_dimensions:
            failures.add(SurvivorshipFailureCode.UNKNOWN_CORPORATE_ACTION_HISTORY)
        hard_failure = invalid > 0 or future > 0 or stale_sector > 0
        status = (
            SurvivorshipStatus.FAIL
            if hard_failure
            else SurvivorshipStatus.PASS_WITH_UNKNOWN_HISTORY
            if failures
            else SurvivorshipStatus.PASS
        )
        return SurvivorshipAuditRecord(
            as_of=snapshot.as_of,
            observed_universe_size=len(snapshot.members),
            invalid_security_count=invalid,
            future_constituent_leaks=future,
            stale_sector_mappings=stale_sector,
            unknown_index_count=unknown_indices,
            unknown_sector_count=unknown_sector,
            failures=tuple(sorted(failures, key=lambda item: item.value)),
            status=status,
        )


__all__ = ["SurvivorshipAuditEngine"]
