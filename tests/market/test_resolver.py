from datetime import date

from alpha.market.resolver import TradingDateResolver


def test_monday_returns_monday():
    resolver = TradingDateResolver()

    assert resolver.resolve(date(2024, 6, 10)) == date(2024, 6, 10)


def test_saturday_returns_friday():
    resolver = TradingDateResolver()

    assert resolver.resolve(date(2024, 6, 8)) == date(2024, 6, 7)


def test_sunday_returns_friday():
    resolver = TradingDateResolver()

    assert resolver.resolve(date(2024, 6, 9)) == date(2024, 6, 7)