from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal

from alpha.market_truth.warehouse.archive_vault import RawArchiveVault
from alpha.market_truth.warehouse.models import (
    AdjustmentMode,
    CanonicalDailyRecord,
    QualityComponent,
    SessionState,
    WarehouseQualityReport,
    WarehouseQualityState,
)
from alpha.market_truth.warehouse.storage import WarehouseStore


class WarehouseQualityEngine:
    def __init__(self, store: WarehouseStore, vault: RawArchiveVault) -> None:
        self.store = store
        self.vault = vault

    def audit(self, *, generated_at: datetime | None = None) -> WarehouseQualityReport:
        sources = self.vault.records()
        integrity_failures = 0
        for source in sources:
            try:
                self.vault.verify(source)
            except RuntimeError:
                integrity_failures += 1
        daily = self.store.daily_records()
        identities = self.store.identity_records()
        actions = self.store.corporate_action_records()
        sessions = self.store.sessions()
        schema_counts = Counter(
            (item.provider, item.dataset_type, item.schema_fingerprint)
            for item in sources
        )
        schema_families = defaultdict(set)
        for provider, dataset, fingerprint in schema_counts:
            schema_families[(provider, dataset)].add(fingerprint)
        schema_changes = sum(
            max(0, len(items) - 1) for items in schema_families.values()
        )
        previous_chain_failures = _previous_close_failures(daily)
        identity_ids = {item.security_id for item in identities}
        missing_identity = sum(item.security_id not in identity_ids for item in daily)
        action_dates = {
            (item.security_id, item.ex_date)
            for item in actions
            if item.ex_date is not None
        }
        unexplained_gaps = _unexplained_gaps(daily, action_dates)
        adjusted = tuple(
            item
            for mode in (
                AdjustmentMode.ADJUSTED,
                AdjustmentMode.TOTAL_RETURN,
                AdjustmentMode.POINT_IN_TIME,
            )
            for item in self.store.adjusted_records(mode)
        )
        factor_failures = sum(
            item.cumulative_price_factor <= 0 or item.cumulative_volume_factor <= 0
            for item in adjusted
        )
        missing_sessions = sum(item.state is SessionState.MISSING for item in sessions)
        components = (
            _component("archive_checksum_integrity", len(sources), integrity_failures),
            _component(
                "schema_consistency",
                len(sources),
                schema_changes,
                warning_only=True,
                detail="Schema changes require an explicit parser/version review.",
            ),
            _component("canonical_ohlc", len(daily), 0),
            _component("previous_close_chain", len(daily), previous_chain_failures),
            _component("point_in_time_identity", len(daily), missing_identity),
            _component("unexplained_price_gaps", len(daily), unexplained_gaps),
            _component("adjustment_factor_continuity", len(adjusted), factor_failures),
            _component(
                "session_completeness",
                len(sessions),
                missing_sessions,
                warning_only=True,
                detail=(
                    "Expected sessions without validated source files remain missing."
                ),
            ),
        )
        status = self.store.status()
        return WarehouseQualityReport(
            generated_at=generated_at or datetime.now(tz=UTC),
            components=components,
            quarantined_records=status.quarantined_records,
        )


def _component(
    name: str,
    checked: int,
    affected: int,
    *,
    warning_only: bool = False,
    detail: str = "",
) -> QualityComponent:
    if checked == 0:
        state = WarehouseQualityState.UNAVAILABLE
        explanation = "No records are available for this check."
    elif affected == 0:
        state = WarehouseQualityState.COMPLETE
        explanation = "No failures detected."
    elif warning_only:
        state = WarehouseQualityState.PARTIAL
        explanation = detail or f"{affected} item(s) require review."
    else:
        state = WarehouseQualityState.DEGRADED
        explanation = detail or f"{affected} item(s) failed this check."
    return QualityComponent(name, state, checked, affected, explanation)


def _previous_close_failures(records: tuple[CanonicalDailyRecord, ...]) -> int:
    grouped: dict[str, list[CanonicalDailyRecord]] = defaultdict(list)
    for item in records:
        grouped[item.security_id].append(item)
    failures = 0
    for values in grouped.values():
        values.sort(key=lambda item: item.trading_date)
        for previous, current in zip(values, values[1:], strict=False):
            published = current.previous_close
            if published is not None and abs(published - previous.close) > Decimal(
                "0.01"
            ):
                failures += 1
    return failures


def _unexplained_gaps(
    records: tuple[CanonicalDailyRecord, ...], action_dates: set[tuple[str, date]]
) -> int:
    grouped: dict[str, list[CanonicalDailyRecord]] = defaultdict(list)
    for item in records:
        grouped[item.security_id].append(item)
    failures = 0
    for security_id, values in grouped.items():
        values.sort(key=lambda item: item.trading_date)
        for previous, current in zip(values, values[1:], strict=False):
            prior_close = previous.close
            if prior_close <= 0:
                continue
            change = abs(current.close / prior_close - Decimal("1"))
            trading_date = current.trading_date
            nearby = any(
                key == security_id
                and action_date is not None
                and abs((trading_date - action_date).days) <= 1
                for key, action_date in action_dates
            )
            if change > Decimal("0.40") and not nearby:
                failures += 1
    return failures


__all__ = ["WarehouseQualityEngine"]
