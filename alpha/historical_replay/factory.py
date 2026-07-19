from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Protocol, cast

import pandas as pd

from alpha.analysis.signals.daily_report import DailyMarketReport
from alpha.application.intelligence import IntelligenceApplicationService
from alpha.candidate_learning.raw_universe import raw_record_from_candidate
from alpha.candidate_learning.recorder import recommendation_to_candidate_record
from alpha.historical_replay.models import ReplayCandidateObservation
from alpha.recommendation_intelligence.models import OHLCVBar

_HISTORY_WINDOW = 1260
_OUTCOME_WINDOW = 60


class ReplayPriceRepository(Protocol):
    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        """Return persisted prices for one trading date."""
        ...

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        """Return point-in-time historical prices up to end_date."""
        ...


@dataclass(frozen=True, slots=True)
class HistoricalObservationBuildResult:
    observations: tuple[ReplayCandidateObservation, ...]
    replay_dates: tuple[date, ...]
    skipped_dates: tuple[str, ...]


class HistoricalObservationFactory:
    def __init__(
        self,
        *,
        price_repository: ReplayPriceRepository,
        report: DailyMarketReport | None = None,
    ) -> None:
        self.price_repository = _ReplaySafePriceRepository(price_repository)
        self.report = report or DailyMarketReport()

    def build(
        self,
        *,
        from_date: date,
        to_date: date,
    ) -> HistoricalObservationBuildResult:
        if to_date < from_date:
            raise ValueError("to_date must be on or after from_date")
        replay_dates = _trade_dates(
            repository=self.price_repository,
            from_date=from_date,
            to_date=to_date,
        )
        observations: list[ReplayCandidateObservation] = []
        skipped: list[str] = []
        for replay_date in replay_dates:
            try:
                observations.extend(self._build_for_date(replay_date))
            except ValueError as error:
                skipped.append(f"{replay_date.isoformat()}: {error}")
        return HistoricalObservationBuildResult(
            observations=tuple(observations),
            replay_dates=replay_dates,
            skipped_dates=tuple(skipped),
        )

    def _build_for_date(
        self,
        replay_date: date,
    ) -> tuple[ReplayCandidateObservation, ...]:
        prices = self.price_repository.find_by_trade_date(replay_date)
        if prices.empty:
            raise ValueError("no persisted prices")
        prices = _valid_ohlc_prices(prices)
        if prices.empty:
            raise ValueError("no valid OHLC prices")
        report = self.report.generate(prices)
        analysis = report["analysis"]
        service = IntelligenceApplicationService.from_analysis(
            analysis=analysis,
            price_repository=self.price_repository,
            history_window=_HISTORY_WINDOW,
        )
        run = service.run(observed_on=replay_date)
        run_id = f"historical_replay|{replay_date.isoformat()}"
        created_at = datetime.combine(replay_date, datetime.min.time(), tzinfo=UTC)
        emitted = {
            recommendation.symbol: recommendation.final_signal
            for recommendation in run.recommendations
        }
        allocation_by_symbol = {
            allocation.symbol: allocation for allocation in run.allocation_plan.reports
        }
        decision_by_symbol = {
            recommendation.symbol: recommendation_to_candidate_record(
                recommendation=recommendation,
                run_id=run_id,
                market_regime=run.market_report.bias.value,
                created_at=created_at,
                allocation_report=allocation_by_symbol.get(recommendation.symbol),
            )
            for recommendation in run.recommendations
        }
        symbols = tuple(candidate.symbol for candidate in run.raw_candidates)
        bars_by_symbol = _bars_by_symbol(
            frame=_future_frame(
                repository=self.price_repository,
                symbols=symbols,
                replay_date=replay_date,
            )
        )
        return tuple(
            ReplayCandidateObservation(
                raw_candidate=raw_record_from_candidate(
                    candidate=candidate,
                    run_id=run_id,
                    created_at=created_at,
                    emitted_verdict_by_symbol=emitted,
                    raw_rank=index,
                ),
                emitted_decision=decision_by_symbol.get(candidate.symbol),
                bars=bars_by_symbol.get(candidate.symbol, ()),
            )
            for index, candidate in enumerate(run.raw_candidates, start=1)
        )


def _trade_dates(
    *,
    repository: ReplayPriceRepository,
    from_date: date,
    to_date: date,
) -> tuple[date, ...]:
    find_trade_dates = getattr(repository, "find_trade_dates", None)
    if callable(find_trade_dates):
        typed_find_trade_dates = cast(
            Callable[..., tuple[date, ...]],
            find_trade_dates,
        )
        return tuple(typed_find_trade_dates(start=from_date, end=to_date))
    dates: list[date] = []
    current = from_date
    while current <= to_date:
        if not repository.find_by_trade_date(current).empty:
            dates.append(current)
        current += timedelta(days=1)
    return tuple(dates)


class _ReplaySafePriceRepository:
    def __init__(self, repository: ReplayPriceRepository) -> None:
        self.repository = repository

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        return _valid_ohlc_prices(self.repository.find_by_trade_date(trade_date))

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        return _valid_ohlc_prices(
            self.repository.find_history_by_symbols(
                symbols=symbols,
                end_date=end_date,
                limit=limit,
            )
        )

    def find_trade_dates(self, *, start: date, end: date) -> tuple[date, ...]:
        find_trade_dates = getattr(self.repository, "find_trade_dates", None)
        if callable(find_trade_dates):
            typed_find_trade_dates = cast(
                Callable[..., tuple[date, ...]],
                find_trade_dates,
            )
            return tuple(typed_find_trade_dates(start=start, end=end))
        dates: list[date] = []
        current = start
        while current <= end:
            if not self.find_by_trade_date(current).empty:
                dates.append(current)
            current += timedelta(days=1)
        return tuple(dates)

    def find_range_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        find_range = getattr(self.repository, "find_range_by_symbols", None)
        if not callable(find_range):
            frame = self.find_history_by_symbols(
                symbols=symbols,
                end_date=end_date,
                limit=_HISTORY_WINDOW + _OUTCOME_WINDOW,
            )
            if frame.empty:
                return frame
            result = frame.copy()
            result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.date
            return result.loc[
                (result["trade_date"] >= start_date)
                & (result["trade_date"] <= end_date)
            ]
        typed_find_range = cast(Callable[..., pd.DataFrame], find_range)
        return _valid_ohlc_prices(
            typed_find_range(
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
            )
        )


def _future_frame(
    *,
    repository: ReplayPriceRepository,
    symbols: tuple[str, ...],
    replay_date: date,
) -> pd.DataFrame:
    end_date = replay_date + timedelta(days=120)
    find_range = getattr(repository, "find_range_by_symbols", None)
    if callable(find_range):
        typed_find_range = cast(Callable[..., pd.DataFrame], find_range)
        return typed_find_range(
            symbols=symbols,
            start_date=replay_date + timedelta(days=1),
            end_date=end_date,
        )
    frame = repository.find_history_by_symbols(
        symbols=symbols,
        end_date=end_date,
        limit=_HISTORY_WINDOW + _OUTCOME_WINDOW,
    )
    if frame.empty:
        return frame
    result = frame.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.date
    return result.loc[result["trade_date"] > replay_date]


def _valid_ohlc_prices(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in ("open", "high", "low", "close"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    valid = (
        result["open"].notna()
        & result["high"].notna()
        & result["low"].notna()
        & result["close"].notna()
        & (result["high"] >= result["low"])
        & (result["open"] <= result["high"])
        & (result["open"] >= result["low"])
        & (result["close"] <= result["high"])
        & (result["close"] >= result["low"])
    )
    return result.loc[valid].copy()


def _bars_by_symbol(frame: pd.DataFrame) -> dict[str, tuple[OHLCVBar, ...]]:
    if frame.empty:
        return {}
    result = _valid_ohlc_prices(frame)
    if result.empty:
        return {}
    result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.date
    bars: dict[str, tuple[OHLCVBar, ...]] = {}
    for symbol, group in result.groupby("symbol", sort=True):
        bars[str(symbol).strip().upper()] = tuple(
            OHLCVBar(
                observed_on=cast(date, row["trade_date"]),
                open_price=Decimal(str(row["open"])),
                high_price=Decimal(str(row["high"])),
                low_price=Decimal(str(row["low"])),
                close_price=Decimal(str(row["close"])),
                volume=Decimal(str(row["volume"])),
            )
            for row in group.sort_values("trade_date").to_dict("records")
        )
    return bars


__all__ = [
    "HistoricalObservationBuildResult",
    "HistoricalObservationFactory",
    "ReplayPriceRepository",
]
