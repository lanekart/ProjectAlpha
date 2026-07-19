from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from alpha.market_truth.warehouse.acquisition_policy import AcquisitionPolicy
from alpha.market_truth.warehouse.adjustments import (
    CorporateActionAdjustmentService,
)
from alpha.market_truth.warehouse.aggregation import WarehouseAggregationService
from alpha.market_truth.warehouse.archive_vault import RawArchiveVault
from alpha.market_truth.warehouse.identity import HistoricalIdentityService
from alpha.market_truth.warehouse.ingestion import WarehouseIngestionEngine
from alpha.market_truth.warehouse.models import (
    AdjustmentMode,
    AggregatePeriod,
    DatasetVersion,
    DividendMode,
    Exchange,
    IngestionResult,
    WarehouseDataset,
    WarehousePaths,
    WarehouseQualityState,
    WarehouseStatus,
)
from alpha.market_truth.warehouse.publication import WarehousePublisher
from alpha.market_truth.warehouse.quality import WarehouseQualityEngine
from alpha.market_truth.warehouse.reconciliation import CurrentStoreReconciler
from alpha.market_truth.warehouse.session_inventory import HistoricalSessionInventory
from alpha.market_truth.warehouse.source_authorisation import (
    SourceAuthorisationRegistry,
    default_source_authorisations,
)
from alpha.market_truth.warehouse.storage import WarehouseStore
from alpha.market_truth.warehouse.universe import PointInTimeUniverseService
from alpha.market_truth.warehouse.versioning import WarehouseVersioningService


@dataclass(frozen=True, slots=True)
class MaterialisationResult:
    raw_adjustments: int
    adjusted_records: int
    total_return_records: int
    point_in_time_records: int
    weekly_bars: int
    monthly_bars: int
    universe_records: int
    dataset_version: DatasetVersion


class HistoricalMarketWarehouse:
    """Single orchestration boundary for all warehouse reads and mutations."""

    def __init__(
        self,
        root: Path | str = Path("data/market_truth"),
        *,
        authorisations: SourceAuthorisationRegistry | None = None,
    ) -> None:
        self.paths = WarehousePaths(Path(root))
        self.store = WarehouseStore(self.paths)
        self.authorisations = authorisations or default_source_authorisations(
            path=self.paths.root / "metadata" / "source_authorisations.json"
        )
        self.policy = AcquisitionPolicy(self.authorisations)
        self.vault = RawArchiveVault(self.paths)
        self.ingestion = WarehouseIngestionEngine(
            policy=self.policy, vault=self.vault, store=self.store
        )
        self.sessions = HistoricalSessionInventory(self.store)
        self.identities = HistoricalIdentityService(self.store)
        self.adjustments = CorporateActionAdjustmentService(self.store)
        self.aggregates = WarehouseAggregationService(self.store)
        self.universe = PointInTimeUniverseService(self.store)
        self.quality = WarehouseQualityEngine(self.store, self.vault)
        self.versioning = WarehouseVersioningService(
            store=self.store, vault=self.vault, quality=self.quality
        )
        self.publisher = WarehousePublisher(self.store, self.paths)
        self.reconciler = CurrentStoreReconciler(self.store)

    def status(self) -> WarehouseStatus:
        return self.store.status()

    def import_file(
        self,
        path: Path,
        *,
        exchange: Exchange,
        dataset: WarehouseDataset,
        authorisation_record_id: str,
        lawfully_obtained: bool,
        trading_date: date | None = None,
        publication_timestamp: datetime | None = None,
    ) -> IngestionResult:
        return self.ingestion.import_file(
            path,
            exchange=exchange,
            dataset=dataset,
            authorisation_record_id=authorisation_record_id,
            lawfully_obtained=lawfully_obtained,
            trading_date=trading_date,
            publication_timestamp=publication_timestamp,
        )

    def materialise(
        self,
        *,
        as_of: date,
        code_commit: str | None = None,
    ) -> MaterialisationResult:
        raw = self.adjustments.build(
            mode=AdjustmentMode.RAW,
            adjustment_as_of=as_of,
            dividend_mode=DividendMode.UNADJUSTED,
        )
        adjusted = self.adjustments.build(
            mode=AdjustmentMode.ADJUSTED,
            adjustment_as_of=as_of,
            dividend_mode=DividendMode.PRICE_ADJUSTED,
        )
        total_return = self.adjustments.build(
            mode=AdjustmentMode.TOTAL_RETURN,
            adjustment_as_of=as_of,
            dividend_mode=DividendMode.TOTAL_RETURN_ADJUSTED,
        )
        point_in_time = self.adjustments.build(
            mode=AdjustmentMode.POINT_IN_TIME,
            adjustment_as_of=as_of,
            dividend_mode=DividendMode.UNADJUSTED,
        )
        weekly = self.aggregates.generate(period=AggregatePeriod.WEEKLY)
        monthly = self.aggregates.generate(period=AggregatePeriod.MONTHLY)
        identity_version = "identity-materialised"
        universe_records = tuple(
            item
            for exchange in Exchange
            for item in self.universe.materialise(
                session_date=as_of,
                exchange=exchange,
                identity_version=identity_version,
            )
        )
        version = self.versioning.build_version(code_commit=code_commit)
        return MaterialisationResult(
            raw_adjustments=len(raw.records),
            adjusted_records=len(adjusted.records),
            total_return_records=len(total_return.records),
            point_in_time_records=len(point_in_time.records),
            weekly_bars=len(weekly),
            monthly_bars=len(monthly),
            universe_records=len(universe_records),
            dataset_version=version,
        )

    def publish(
        self,
        *,
        confirm: bool,
        version: DatasetVersion | None = None,
    ) -> Path:
        report = self.quality.audit()
        blocking = tuple(
            item
            for item in report.components
            if item.state
            in {WarehouseQualityState.DEGRADED, WarehouseQualityState.QUARANTINED}
        )
        if blocking:
            names = ", ".join(item.name for item in blocking)
            raise RuntimeError(
                f"warehouse publication blocked by quality checks: {names}"
            )
        if self.store.status().daily_records == 0:
            raise RuntimeError("warehouse publication requires canonical daily records")
        metadata = version or self.versioning.build_version()
        return self.publisher.publish(metadata, confirm=confirm)


__all__ = ["HistoricalMarketWarehouse", "MaterialisationResult"]
