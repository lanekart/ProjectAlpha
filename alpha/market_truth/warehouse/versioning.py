from __future__ import annotations

from datetime import UTC, datetime

from alpha.market_truth.warehouse.archive_vault import RawArchiveVault
from alpha.market_truth.warehouse.models import DatasetVersion, stable_hash
from alpha.market_truth.warehouse.quality import WarehouseQualityEngine
from alpha.market_truth.warehouse.storage import WarehouseStore

DEFAULT_WAREHOUSE_VERSION = "MARKET_WAREHOUSE_1.0.0"


class WarehouseVersioningService:
    def __init__(
        self,
        *,
        store: WarehouseStore,
        vault: RawArchiveVault,
        quality: WarehouseQualityEngine,
    ) -> None:
        self.store = store
        self.vault = vault
        self.quality = quality

    def build_version(
        self,
        *,
        release: str = DEFAULT_WAREHOUSE_VERSION,
        build_timestamp: datetime | None = None,
        code_commit: str | None = None,
        parent_version: str | None = None,
    ) -> DatasetVersion:
        daily = self.store.daily_records()
        identities = self.store.identity_records()
        actions = self.store.corporate_action_records()
        report = self.quality.audit(generated_at=build_timestamp)
        quality_hash = stable_hash(report)
        identity_version = (
            "identity-"
            + stable_hash(
                [
                    (
                        item.security_id,
                        item.symbol,
                        item.symbol_valid_from,
                        item.symbol_valid_to,
                        item.source_file_id,
                    )
                    for item in identities
                ]
            )[:20]
        )
        action_version = (
            "corporate-actions-"
            + stable_hash(
                [(item.corporate_action_id, item.version) for item in actions]
            )[:20]
        )
        content_hash = stable_hash(
            {
                "manifest": self.vault.manifest_hash(),
                "quality": quality_hash,
                "records": [item.record_checksum for item in daily],
                "identity": identity_version,
                "actions": action_version,
            }
        )
        version = f"{release}+{content_hash[:12]}"
        dates = tuple(item.trading_date for item in daily)
        metadata = DatasetVersion(
            version=version,
            raw_manifest_hash=self.vault.manifest_hash(),
            session_range_start=min(dates, default=None),
            session_range_end=max(dates, default=None),
            exchange_coverage=tuple(
                sorted({item.exchange for item in daily}, key=lambda item: item.value)
            ),
            security_count=len({item.security_id for item in daily}),
            record_count=len(daily),
            identity_version=identity_version,
            corporate_action_version=action_version,
            adjustment_policy_version="ADJUSTMENT_POLICY_1.0.0",
            quality_report_hash=quality_hash,
            build_timestamp=build_timestamp or datetime.now(tz=UTC),
            code_commit=code_commit,
            parent_version=parent_version or self.store.latest_version(),
        )
        self.store.record_version(metadata)
        return metadata


__all__ = ["DEFAULT_WAREHOUSE_VERSION", "WarehouseVersioningService"]
