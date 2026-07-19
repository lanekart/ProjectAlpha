from __future__ import annotations

from datetime import date, datetime

from alpha.data_platform.dataset_registry import DatasetRegistry
from alpha.data_platform.models import (
    CanonicalObservation,
    DataQuery,
    TimeTravelSnapshot,
)
from alpha.data_platform.query import CanonicalQueryEngine, subject_for_category


class TimeTravelEngine:
    """Return only records effective and known at the requested historical cutoff."""

    def __init__(
        self,
        registry: DatasetRegistry,
        query_engine: CanonicalQueryEngine,
    ) -> None:
        self._registry = registry
        self._query_engine = query_engine

    def snapshot(
        self,
        *,
        market_date: date,
        knowledge_as_of: datetime,
        dataset_ids: tuple[str, ...],
    ) -> TimeTravelSnapshot:
        records: list[CanonicalObservation] = []
        versions: dict[str, str] = {}
        unknown = []
        for dataset_id in sorted(dict.fromkeys(dataset_ids)):
            dataset = self._registry.get(dataset_id)
            result = self._query_engine.execute(
                DataQuery(
                    dataset_id=dataset_id,
                    subject=subject_for_category(dataset.category),
                    market_start=market_date,
                    market_end=market_date,
                    knowledge_as_of=knowledge_as_of,
                    limit=1_000_000,
                )
            )
            versions[dataset_id] = dataset.version
            if not result.records:
                unknown.append(dataset_id)
            records.extend(result.records)
        return TimeTravelSnapshot(
            market_date=market_date,
            knowledge_as_of=knowledge_as_of,
            records=tuple(
                sorted(
                    records,
                    key=lambda item: (item.dataset_id, item.observation_key),
                )
            ),
            dataset_versions=versions,
            unknown_datasets=tuple(unknown),
        )


__all__ = ["TimeTravelEngine"]
