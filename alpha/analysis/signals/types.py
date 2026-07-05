from __future__ import annotations

from typing import TypedDict

import pandas as pd


class DailyReport(TypedDict):
    top_gainers: pd.DataFrame
    top_losers: pd.DataFrame
    regime: str
