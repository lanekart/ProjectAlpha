from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DownloadResult:
    """
    Represents a successfully downloaded market data file.
    """

    trade_date: date
    source_url: str
    content: bytes
