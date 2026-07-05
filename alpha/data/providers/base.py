from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from alpha.data.models import DownloadResult


class MarketDataProvider(ABC):
    """
    Base interface for all market data providers.

    Every provider must implement a method that downloads
    market data for a trading date and returns a DownloadResult.
    """

    @abstractmethod
    def download_bhavcopy(self, target_date: date) -> DownloadResult:
        """
        Download the bhavcopy for the requested trading date.

        Returns
        -------
        DownloadResult
            Metadata and file contents.

        Raises
        ------
        DownloadError
            If the download cannot be completed.
        """
        raise NotImplementedError
