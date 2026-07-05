from datetime import date, timedelta


class TradingDateResolver:
    """
    Resolves the nearest plausible NSE trading date.

    This resolver intentionally avoids weekends and future dates.
    It does not guarantee that NSE has published data for the day;
    the downloader remains responsible for probing archive availability.
    """

    def __init__(self) -> None:
        self.max_lookback_days = 15

    def resolve(self, target_date: date) -> date:
        """
        Resolve the nearest plausible trading date.
        """

        for i in range(self.max_lookback_days):
            candidate = target_date - timedelta(days=i)

            if self._is_plausible_nse_date(candidate):
                return candidate

        raise RuntimeError("No valid NSE trading date found.")

    @staticmethod
    def _is_plausible_nse_date(candidate: date) -> bool:
        """
        Basic trading-day heuristic.

        Excludes:
        - Future dates
        - Saturdays
        - Sundays
        """

        if candidate > date.today():
            return False

        if candidate.weekday() >= 5:
            return False

        return True
