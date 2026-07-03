from datetime import date, timedelta


class MarketCalendar:
    """
    Basic NSE trading calendar.

    Version 1:
    - Weekends are non-trading days
    - Future dates are invalid
    - Holiday support will be added next
    """

    def is_future_date(self, target_date: date) -> bool:
        return target_date > date.today()

    def is_weekend(self, target_date: date) -> bool:
        return target_date.weekday() >= 5

    def is_trading_day(self, target_date: date) -> bool:
        if self.is_future_date(target_date):
            return False

        return not self.is_weekend(target_date)

    def previous_trading_day(self, target_date: date) -> date:
        current = target_date - timedelta(days=1)

        while self.is_weekend(current):
            current -= timedelta(days=1)

        return current

    def next_trading_day(self, target_date: date) -> date:
        current = target_date + timedelta(days=1)

        while self.is_weekend(current):
            current += timedelta(days=1)

        return current