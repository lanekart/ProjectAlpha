from datetime import date
import requests
from loguru import logger

class NSEProvider:

    def build_url(self, target_date: date) -> str:
        day = target_date.strftime("%d")
        month = target_date.strftime("%b").upper()
        year = target_date.strftime("%Y")

        return (
            "https://archives.nseindia.com/"
            f"content/historical/EQUITIES/{year}/{month}/cm{day}{month}{year}bhav.csv.zip"
        )

    def download_bhavcopy(self, target_date: date) -> bytes:
        url = self.build_url(target_date)

        logger.info(f"Downloading NSE Bhavcopy: {url}")

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com"
        }

        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            logger.error(f"Failed to download bhavcopy: {response.status_code}")
            raise Exception("NSE download failed")

        logger.success("Bhavcopy downloaded successfully")

        return response.content