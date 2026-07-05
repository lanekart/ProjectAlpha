from datetime import date, timedelta

import requests
from loguru import logger

from alpha.data.models import DownloadResult
from alpha.exceptions import BhavcopyNotFoundError


class NSEBhavcopyProvider:
    """
    Resilient NSE bhavcopy provider.

    Responsibilities
    ----------------
    - Build NSE archive URLs
    - Attempt downloads
    - Return a DownloadResult on success

    NOTE:
    Date lookback currently remains here for backward compatibility.
    This responsibility will later move into TradingDateResolver.
    """

    BASE_URL = "https://archives.nseindia.com/content/historical/EQUITIES"

    def download_bhavcopy(
        self,
        target_date: date,
        lookback_days: int = 10,
    ) -> DownloadResult:
        """
        Attempt to download the nearest available bhavcopy.

        Returns
        -------
        DownloadResult

        Raises
        ------
        BhavcopyNotFoundError
        """

        last_error: str | None = None

        for i in range(lookback_days):
            candidate = target_date - timedelta(days=i)

            url = self._build_url(candidate)

            try:
                if not self._url_exists(url):
                    logger.warning(f"No data at {url}")
                    continue

                logger.info(f"Downloading NSE bhavcopy: {url}")

                response = requests.get(url, timeout=20)

                if response.status_code == 200:
                    return DownloadResult(
                        trade_date=candidate,
                        source_url=url,
                        content=response.content,
                    )

                logger.error(f"Failed download {url}: HTTP {response.status_code}")
                last_error = f"HTTP {response.status_code}"

            except Exception as exc:
                logger.exception(f"Error downloading {url}")
                last_error = str(exc)

        raise BhavcopyNotFoundError(
            f"No NSE bhavcopy found within "
            f"{lookback_days} day(s). "
            f"Last error: {last_error}"
        )

    def _url_exists(self, url: str) -> bool:
        """
        Lightweight existence probe.

        NOTE:
        This will likely be removed in Engineering Brief 003.3
        when we redesign the HTTP layer.
        """

        try:
            response = requests.head(url, timeout=10)
            return response.status_code == 200
        except Exception:
            return False

    def _build_url(self, trade_date: date) -> str:
        """
        Build the NSE archive URL.

        Example
        -------
        https://archives.nseindia.com/content/historical/EQUITIES/2026/JUL/cm03JUL2026bhav.csv.zip
        """

        year = trade_date.strftime("%Y")
        month = trade_date.strftime("%b").upper()
        day = trade_date.strftime("%d")

        filename = f"cm{day}{month}{year}bhav.csv.zip"

        return f"{self.BASE_URL}/{year}/{month}/{filename}"
