from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from alpha.data.models import DownloadResult


class MarketDataProvider(ABC):
    """
    Base interface for all market data providers.

    Implementations may represent historical archives, live/current-day
    sources, vendor APIs, or provider chains. Higher application layers should
    depend on this abstraction rather than a concrete NSE endpoint.
    """

    @abstractmethod
    def download_bhavcopy(self, target_date: date) -> DownloadResult:
        """
        Download bhavcopy data for a requested trading date.

        Returns
        -------
        DownloadResult
            Metadata and raw file contents.

        Raises
        ------
        DownloadError
            If the provider cannot supply data for the requested date.
        """
        raise NotImplementedError
