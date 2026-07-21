"""Tests for governed historical observation construction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, cast

import pandas as pd
import pytest

from alpha.historical_replay.factory import HistoricalObservationBuildResult
from alpha.historical_replay.governed_factory import (
    GovernedHistoricalObservationFactory,
    governed_run_payloads,
)
from alpha.historical_replay.governed_price_repository import (
    CanonicalReplayPriceRepository,
)
from alpha.recovery.corporate_actions import CorporateActionTimeline
from alpha.recovery.security_timeline import (
    SecurityIdentityRecord,
    SecurityIdentityTimeline,
)

_TRADE_DATE = date(2025, 1, 10)


@dataclass(slots=True)
class FakePriceSource:
    frame: pd.DataFrame

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        return self._range(start=trade_date, end=trade_date)

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        del symbols
        result = self._range(start=date.min, end=end_date)
        return result.tail(limit).reset_index(drop=True)

    def find_range_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        del symbols
        return self._range(start=start_date, end=end_date)

    def find_trade_dates(self, *, start: date, end: date) -> tuple[date, ...]:
        result = self._range(start=start, end=end)
        return tuple(sorted(set(result["trade_date"]))) if not result.empty else ()

    def _range(self, *, start: date, end: date) -> pd.DataFrame:
        result = self.frame.copy()
        result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.date
        return result.loc[
            (result["trade_date"] >= start) & (result["trade_date"] <= end)
        ].reset_index(drop=True)


@dataclass(slots=True)
class ReadingBuilder:
    repository: CanonicalReplayPriceRepository

    def build(
        self,
        *,
        from_date: date,
        to_date: date,
    ) -> HistoricalObservationBuildResult:
        self.repository.find_by_trade_date(from_date)
        self.repository.find_history_by_symbols(
            symbols=("ALPHA",),
            end_date=from_date,
            limit=10,
        )
        self.repository.find_range_by_symbols(
            symbols=("ALPHA",),
            start_date=from_date,
            end_date=to_date,
        )
        return HistoricalObservationBuildResult(
            observations=(),
            replay_dates=(from_date,),
            skipped_dates=(),
        )


@dataclass(slots=True)
class BypassingBuilder:
    def build(
        self,
        *,
        from_date: date,
        to_date: date,
    ) -> HistoricalObservationBuildResult:
        del to_date
        return HistoricalObservationBuildResult(
            observations=(),
            replay_dates=(from_date,),
            skipped_dates=(),
        )


def _repository() -> CanonicalReplayPriceRepository:
    source = FakePriceSource(
        pd.DataFrame(
            [
                {
                    "symbol": "ALPHA",
                    "trade_date": _TRADE_DATE,
                    "open": 90,
                    "high": 110,
                    "low": 80,
                    "close": 100,
                    "volume": 1000,
                    "exchange": "NSE",
                }
            ]
        )
    )
    identities = SecurityIdentityTimeline(
        (
            SecurityIdentityRecord(
                security_id="SEC-1",
                symbol="ALPHA",
                exchange="NSE",
            ),
        )
    )
    return CanonicalReplayPriceRepository(
        source,
        identities,
        CorporateActionTimeline(()),
    )


def test_governed_factory_captures_only_current_run_proofs() -> None:
    repository = _repository()
    factory = GovernedHistoricalObservationFactory(
        price_repository=repository,
        builder=ReadingBuilder(repository),
    )

    first = factory.build(from_date=_TRADE_DATE, to_date=_TRADE_DATE)
    second = factory.build(from_date=_TRADE_DATE, to_date=_TRADE_DATE)

    assert len(first.repository_reads) == 3
    assert len(first.consumer_attestations) == 3
    assert first.replay_dates == (_TRADE_DATE,)
    assert first.canonical_replay_enforced
    assert first.run_sha256 == second.run_sha256
    assert first.repository_reads == second.repository_reads
    assert len(repository.reads) == 6


def test_governed_factory_rejects_raw_repository() -> None:
    raw = FakePriceSource(pd.DataFrame())

    with pytest.raises(TypeError, match="CanonicalReplayPriceRepository"):
        GovernedHistoricalObservationFactory(
            price_repository=cast(Any, raw),
            builder=cast(Any, BypassingBuilder()),
        )


def test_governed_factory_rejects_builder_that_bypasses_repository() -> None:
    repository = _repository()
    factory = GovernedHistoricalObservationFactory(
        price_repository=repository,
        builder=BypassingBuilder(),
    )

    with pytest.raises(ValueError, match="missing trade-date proofs"):
        factory.build(from_date=_TRADE_DATE, to_date=_TRADE_DATE)


def test_governed_run_payloads_are_deterministic() -> None:
    repository = _repository()
    factory = GovernedHistoricalObservationFactory(
        price_repository=repository,
        builder=ReadingBuilder(repository),
    )
    run = factory.build(from_date=_TRADE_DATE, to_date=_TRADE_DATE)

    first = governed_run_payloads((run,))
    second = governed_run_payloads((run,))

    assert first == second
    assert first[0]["canonical_replay_enforced"] is True
    assert first[0]["run_sha256"] == run.run_sha256
