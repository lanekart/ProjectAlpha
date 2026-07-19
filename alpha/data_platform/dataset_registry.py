from __future__ import annotations

from dataclasses import replace
from datetime import date

from alpha.data_platform.models import (
    ConfidenceLevel,
    DatasetCategory,
    DatasetRecord,
    DatasetStatus,
    stable_hash,
)


class DatasetRegistry:
    """Immutable registry of source datasets and acquired dataset versions."""

    def __init__(self, records: tuple[DatasetRecord, ...] = ()) -> None:
        ordered = tuple(sorted(records, key=lambda item: item.dataset_id))
        if len({item.dataset_id for item in ordered}) != len(ordered):
            raise ValueError("ADP dataset ids must be unique")
        self._records = ordered

    @property
    def records(self) -> tuple[DatasetRecord, ...]:
        return self._records

    @property
    def registry_hash(self) -> str:
        return stable_hash(tuple(_record_payload(item) for item in self._records))

    def get(self, dataset_id: str) -> DatasetRecord:
        normalized = dataset_id.strip().lower()
        for record in self._records:
            if record.dataset_id == normalized:
                return record
        raise KeyError(f"ADP dataset is not registered: {dataset_id}")

    def by_source(self, source: str) -> tuple[DatasetRecord, ...]:
        normalized = source.strip().upper()
        return tuple(
            item for item in self._records if item.source.upper() == normalized
        )

    def by_category(self, category: DatasetCategory) -> tuple[DatasetRecord, ...]:
        return tuple(item for item in self._records if item.category is category)

    def register(self, record: DatasetRecord) -> DatasetRegistry:
        if any(item.dataset_id == record.dataset_id for item in self._records):
            raise ValueError(f"ADP dataset already registered: {record.dataset_id}")
        return DatasetRegistry((*self._records, record))

    def record_acquisition(
        self,
        dataset_id: str,
        *,
        version: str,
        download_date: date,
        checksum: str,
        coverage_start: date,
        coverage_end: date,
        confidence: ConfidenceLevel,
    ) -> DatasetRegistry:
        current = self.get(dataset_id)
        updated = replace(
            current,
            version=version,
            download_date=download_date,
            checksum=checksum,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            confidence=confidence,
            status=DatasetStatus.ACTIVE,
        )
        return DatasetRegistry(
            tuple(
                updated if item.dataset_id == dataset_id else item
                for item in self._records
            )
        )


def default_dataset_registry() -> DatasetRegistry:
    records = [
        _dataset(
            "nse-equity-bhavcopy",
            "NSE Equity Daily Bhavcopy",
            "NSE",
            DatasetCategory.DAILY_OHLCV,
            "adp-daily-ohlcv-v1",
            "NSE",
        ),
        _dataset(
            "nse-delivery",
            "NSE Deliverable Quantity and Percentage",
            "NSE",
            DatasetCategory.DELIVERY,
            "adp-delivery-v1",
            "NSE",
        ),
        _dataset(
            "nse-corporate-actions",
            "NSE Corporate Actions",
            "NSE",
            DatasetCategory.CORPORATE_ACTION,
            "adp-corporate-action-v1",
            "NSE",
        ),
        _dataset(
            "nse-security-master",
            "NSE Security Master",
            "NSE",
            DatasetCategory.SECURITY_MASTER,
            "adp-security-master-v1",
            "NSE",
        ),
        _dataset(
            "nse-isin-mapping",
            "NSE ISIN Mapping",
            "NSE",
            DatasetCategory.IDENTITY,
            "adp-isin-map-v1",
            "NSE",
        ),
        _dataset(
            "nse-symbol-history",
            "NSE Symbol and Name History",
            "NSE",
            DatasetCategory.SYMBOL_HISTORY,
            "adp-symbol-history-v1",
            "NSE",
        ),
        _dataset(
            "nse-trading-calendar",
            "NSE Trading Calendar",
            "NSE",
            DatasetCategory.TRADING_CALENDAR,
            "adp-trading-calendar-v1",
            "NSE",
        ),
        _dataset(
            "bse-equity-bhavcopy",
            "BSE Equity Daily Bhavcopy",
            "BSE",
            DatasetCategory.DAILY_OHLCV,
            "adp-daily-ohlcv-v1",
            "BSE",
        ),
        _dataset(
            "bse-corporate-actions",
            "BSE Corporate Actions",
            "BSE",
            DatasetCategory.CORPORATE_ACTION,
            "adp-corporate-action-v1",
            "BSE",
        ),
        _dataset(
            "bse-security-master",
            "BSE Security Master",
            "BSE",
            DatasetCategory.SECURITY_MASTER,
            "adp-security-master-v1",
            "BSE",
        ),
    ]
    broad_indices = (
        ("nifty-50", "NIFTY 50"),
        ("nifty-next-50", "NIFTY NEXT 50"),
        ("nifty-100", "NIFTY 100"),
        ("nifty-200", "NIFTY 200"),
        ("nifty-500", "NIFTY 500"),
        ("nifty-midcap", "NIFTY MIDCAP"),
        ("nifty-smallcap", "NIFTY SMALLCAP"),
        ("nifty-total-market", "NIFTY TOTAL MARKET"),
    )
    records.extend(
        _dataset(
            f"nse-index-{slug}-ohlcv",
            f"{name} Historical Index OHLCV",
            "NSE_INDICES",
            DatasetCategory.INDEX_OHLCV,
            "adp-index-ohlcv-v1",
            "NSE",
            entities=(name,),
        )
        for slug, name in broad_indices
    )
    records.extend(
        (
            _dataset(
                "nse-sector-indices-ohlcv",
                "NSE Official Sector Indices OHLCV",
                "NSE_INDICES",
                DatasetCategory.INDEX_OHLCV,
                "adp-index-ohlcv-v1",
                "NSE",
                entities=("ALL_OFFICIAL_SECTOR_INDICES",),
            ),
            _dataset(
                "nse-historical-index-membership",
                "NSE Historical Index Membership",
                "NSE_INDICES",
                DatasetCategory.INDEX_MEMBERSHIP,
                "adp-index-membership-v1",
                "NSE",
                entities=tuple(name for _, name in broad_indices),
            ),
        )
    )
    return DatasetRegistry(tuple(records))


def _dataset(
    dataset_id: str,
    name: str,
    source: str,
    category: DatasetCategory,
    schema_version: str,
    exchange: str,
    *,
    entities: tuple[str, ...] = (),
) -> DatasetRecord:
    return DatasetRecord(
        dataset_id=dataset_id,
        dataset_name=name,
        version="UNACQUIRED",
        source=source,
        official=True,
        download_date=None,
        checksum=None,
        coverage_start=None,
        coverage_end=None,
        schema_version=schema_version,
        confidence=ConfidenceLevel.LOW,
        status=DatasetStatus.EXPERIMENTAL,
        category=category,
        exchange=exchange,
        entities=entities,
        notes="Connector and schema registered; historical acquisition not performed.",
    )


def _record_payload(record: DatasetRecord) -> dict[str, object]:
    return {
        "dataset_id": record.dataset_id,
        "dataset_name": record.dataset_name,
        "version": record.version,
        "source": record.source,
        "official": record.official,
        "download_date": record.download_date,
        "checksum": record.checksum,
        "coverage_start": record.coverage_start,
        "coverage_end": record.coverage_end,
        "schema_version": record.schema_version,
        "confidence": record.confidence.value,
        "status": record.status.value,
        "category": record.category.value,
        "exchange": record.exchange,
        "entities": record.entities,
        "notes": record.notes,
    }


__all__ = ["DatasetRegistry", "default_dataset_registry"]
