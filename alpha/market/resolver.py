from datetime import date, timedelta

from alpha.market.calendar import MarketCalendar


class TradingDateResolver:
    def __init__(self):
        self.calendar = MarketCalendar()

    def resolve(self, target_date: date) -> date:
        """
        Returns the nearest previous trading day.
        """

        while not self.calendar.is_trading_day(target_date):
            target_date -= timedelta(days=1)

        return target_date