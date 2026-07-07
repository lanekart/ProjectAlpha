import pandas as pd

from alpha.analysis.signals.daily_report import DailyMarketReport
from alpha.data.ingestion.validator import Validator


def test_daily_report_runs() -> None:
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


def test_daily_report_gainers_are_positive_and_descending() -> None:
    df = pd.DataFrame(
        {
            "symbol": ["A", "B", "C", "D", "E"],
            "open": [100, 100, 100, 100, 100],
            "close": [105, 90, 120, 80, 110],
            "volume": [1000, 1000, 1000, 1000, 1000],
        }
    )

    report = DailyMarketReport().generate(Validator().validate(df))
    gainers = report["top_gainers"]

    assert not gainers.empty
    assert (gainers["momentum_score"] > 0).all()
    assert gainers["symbol"].tolist() == ["C", "E", "A"]
    assert gainers["momentum_score"].is_monotonic_decreasing


def test_daily_report_losers_are_negative_and_ascending() -> None:
    df = pd.DataFrame(
        {
            "symbol": ["A", "B", "C", "D", "E"],
            "open": [100, 100, 100, 100, 100],
            "close": [105, 90, 120, 80, 110],
            "volume": [1000, 1000, 1000, 1000, 1000],
        }
    )

    report = DailyMarketReport().generate(Validator().validate(df))
    losers = report["top_losers"]

    assert not losers.empty
    assert (losers["momentum_score"] < 0).all()
    assert losers["symbol"].tolist() == ["D", "B"]
    assert losers["momentum_score"].is_monotonic_increasing


def test_daily_report_gainers_and_losers_do_not_overlap() -> None:
    df = pd.DataFrame(
        {
            "symbol": ["A", "B", "C", "D", "E"],
            "open": [100, 100, 100, 100, 100],
            "close": [105, 90, 120, 80, 100],
            "volume": [1000, 1000, 1000, 1000, 1000],
        }
    )

    report = DailyMarketReport().generate(Validator().validate(df))
    gainers = set(report["top_gainers"]["symbol"].tolist())
    losers = set(report["top_losers"]["symbol"].tolist())

    assert gainers.isdisjoint(losers)
    assert "E" not in gainers
    assert "E" not in losers
