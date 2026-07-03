from datetime import date
from pathlib import Path
from loguru import logger

from alpha.data.providers.nse import NSEProvider


class BhavcopyDownloader:
    def __init__(self):
        self.provider = NSEProvider()
        self.data_dir = Path("data/raw")
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def download(self, target_date: date) -> Path:
        content = self.provider.download_bhavcopy(target_date)

        filename = f"bhavcopy_{target_date}.zip"
        file_path = self.data_dir / filename

        file_path.write_bytes(content)

        logger.success(f"Saved bhavcopy to {file_path}")

        return file_path