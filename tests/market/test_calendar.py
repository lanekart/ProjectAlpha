from datetime import date

from alpha.market.calendar import MarketCalendar


calendar = MarketCalendar()


def test_weekday_is_trading_day():
    assert calendar.is_trading_day(date(2024, 6, 10))


def test_saturday_not_trading():
    assert not calendar.is_trading_day(date(2024, 6, 8))


def test_sunday_not_trading():
    assert not calendar.is_trading_day(date(2024, 6, 9))


def test_previous_trading_day_from_monday():
    assert calendar.previous_trading_day(date(2024, 6, 10)) == date(2024, 6, 7)


def test_next_trading_day_from_friday():
    assert calendar.next_trading_day(date(2024, 6, 7)) == date(2024, 6, 10)