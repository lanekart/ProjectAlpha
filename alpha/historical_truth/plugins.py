from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from alpha.historical_truth.models import ArchiveDataset, ArchiveRequest
from alpha.historical_truth.resumable import HistoricalTruthWarehouse


@dataclass(frozen=True, slots=True)
class NseBhavcopyPlugin:
    warehouse: HistoricalTruthWarehouse

    @property
    def dataset(self) -> ArchiveDataset:
        return ArchiveDataset.BHAVCOPY

    @property
    def exchange(self) -> str:
        return "nse"

    def plan(self, start: date, end: date) -> tuple[ArchiveRequest, ...]:
        return self.warehouse.plan_nse_bhavcopies(start, end)
