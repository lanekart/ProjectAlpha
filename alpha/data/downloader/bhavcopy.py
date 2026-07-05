from __future__ import annotations

from datetime import date
from pathlib import Path

from alpha.config import settings
from alpha.data.providers.base import MarketDataProvider
from alpha.data.providers.nse import NSEBhavcopyProvider


class BhavcopyDownloader:
    """
    Orchestrates bhavcopy download and local storage with caching.
    """

    def __init__(
        self,
        provider: MarketDataProvider | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.provider = provider or NSEBhavcopyProvider()
        self.data_dir = data_dir or settings.raw_data_dir

        self.data_dir.mkdir(parents=True, exist_ok=True)

    def download(self, target_date: date) -> Path:
        """
        Download a bhavcopy and persist it locally.

        If file already exists, returns cached file without calling provider.
        """

        file_path = self.data_dir / f"bhavcopy_{target_date.isoformat()}.zip"

        if file_path.exists():
            return file_path

        result = self.provider.download_bhavcopy(target_date)

        file_path.write_bytes(result.content)

        return file_path
