import pandas as pd

from alpha.analysis.signals.daily_report import DailyMarketReport
from alpha.data.ingestion.validator import Validator


def test_daily_report_runs():
    df = pd.DataFrame(
        {
            "symbol": ["A", "B", "C", "D"],
            "open": [100, 200, 300, 400],
            "close": [110, 180, 330, 390],
            "volume": [1000, 2000, 1500, 1800],
        }
    )

    df = Validator().validate(df)

    report = DailyMarketReport().generate(df)

    assert "top_gainers" in report
    assert "top_losers" in report
    assert "regime" in report
