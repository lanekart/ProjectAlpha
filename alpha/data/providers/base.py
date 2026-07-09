from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from alpha.data.models import DownloadResult

BhavcopyDownloadResult = DownloadResult


class MarketDataProvider(ABC):
    """
    Base interface for all market data providers.
    """

    @abstractmethod
    def download_bhavcopy(self, target_date: date) -> DownloadResult:
        """
        Download bhavcopy data for a requested trading date.
        """
        raise NotImplementedError


__all__ = ["BhavcopyDownloadResult", "DownloadResult", "MarketDataProvider"]
