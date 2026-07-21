"""Tests for fail-closed governed historical replay readiness."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
import pytest

from alpha.application.governed_historical_replay import GovernedHistoricalReplayService
from alpha.historical_replay.factory import HistoricalObservationBuildResult
from alpha.historical_replay.governed_artifacts import (
    GovernedReplayInputManifest,
    GovernedReplayInputs,
)
from alpha.historical_replay.governed_price_repository import (
    CanonicalReplayPriceRepository,
)
from alpha.historical_replay.models import ReplayCandidateObservation, ReplayRunRecord
from alpha.historical_replay.readiness import (
    HistoricalReplayReadinessError,
    HistoricalReplayReadinessStatus,
)
from alpha.recovery.corporate_actions import CorporateActionTimeline
from alpha.recovery.security_timeline import (
    SecurityIdentityRecord,
    SecurityIdentityTimeline,
)
from tests.historical_replay.inventory_fixtures import inventory_evidence

_TRADE_DATE = date(2025, 1, 10)


@dataclass(slots=True)
class FakePriceSource:
    frame: pd.DataFrame

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        frame = self.frame.copy()
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
        return frame.loc[frame["trade_date"] == trade_date].reset_index(drop=True)

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        del symbols, end_date, limit
        return self.frame.iloc[0:0].copy()

    def find_range_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        del symbols, start_date, end_date
        return self.frame.iloc[0:0].copy()

    def find_trade_dates(self, *, start: date, end: date) -> tuple[date, ...]:
        if start <= _TRADE_DATE <= end:
            return (_TRADE_DATE,)
        return ()


@dataclass(slots=True)
class CountingExecutor:
    calls: int = 0

    def run(
        self,
        *,
        from_date: date,
        to_date: date,
        observations: tuple[ReplayCandidateObservation, ...] = (),
    ) -> tuple[ReplayRunRecord, ...]:
        del from_date, to_date, observations
        self.calls += 1
        return ()


@dataclass(slots=True)
class ReadyBuilder:
    repository: CanonicalReplayPriceRepository

    def build(
        self,
        *,
        from_date: date,
        to_date: date,
    ) -> HistoricalObservationBuildResult:
        del to_date
        self.repository.find_by_trade_date(from_date)
        return HistoricalObservationBuildResult(
            observations=(),
            replay_dates=(from_date,),
            skipped_dates=(),
        )


@dataclass(slots=True)
class SkippedBuilder:
    repository: CanonicalReplayPriceRepository

    def build(
        self,
        *,
        from_date: date,
        to_date: date,
    ) -> HistoricalObservationBuildResult:
        del to_date
        self.repository.find_by_trade_date(from_date)
        return HistoricalObservationBuildResult(
            observations=(),
            replay_dates=(from_date,),
            skipped_dates=(f"{from_date.isoformat()}: no valid OHLC prices",),
        )


@dataclass(slots=True)
class EmptyBuilder:
    repository: CanonicalReplayPriceRepository

    def build(
        self,
        *,
        from_date: date,
        to_date: date,
    ) -> HistoricalObservationBuildResult:
        del from_date, to_date
        return HistoricalObservationBuildResult(
            observations=(),
            replay_dates=(),
            skipped_dates=(),
        )


def _inputs() -> GovernedReplayInputs:
    identities = SecurityIdentityTimeline(
        (
            SecurityIdentityRecord(
                security_id="SEC-1",
                symbol="ALPHA",
                exchange="NSE",
            ),
        )
    )
    return GovernedReplayInputs(
        identities=identities,
        actions=CorporateActionTimeline(()),
        manifest=GovernedReplayInputManifest(
            identity_path="identities.csv",
            corporate_action_path="actions.csv",
            identity_sha256="1" * 64,
            corporate_action_sha256="2" * 64,
            identity_count=1,
            corporate_action_count=0,
            unresolved_action_ids=(),
            security_ids=("SEC-1",),
        ),
    )


def _source() -> FakePriceSource:
    return FakePriceSource(
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


def _service(
    executor: CountingExecutor,
    builder: type[ReadyBuilder] | type[SkippedBuilder] | type[EmptyBuilder],
    *,
    include_inventory: bool = True,
    unready_keys: tuple[str, ...] = (),
) -> GovernedHistoricalReplayService:
    evidence = (
        inventory_evidence(period_end=_TRADE_DATE, unready_keys=unready_keys)
        if include_inventory
        else ()
    )
    return GovernedHistoricalReplayService(
        source=_source(),
        inputs=_inputs(),
        executor=executor,
        inventory_evidence=evidence,
        observation_builder_factory=builder,
    )


def test_assessment_reports_blockers_without_invoking_executor() -> None:
    executor = CountingExecutor()
    service = _service(executor, SkippedBuilder)

    assessment = service.assess(from_date=_TRADE_DATE, to_date=_TRADE_DATE)

    assert assessment.readiness.status is HistoricalReplayReadinessStatus.BLOCKED
    assert assessment.as_dict()["executor_invoked"] is False
    assert executor.calls == 0


def test_skipped_dates_block_before_executor_runs() -> None:
    executor = CountingExecutor()

    with pytest.raises(HistoricalReplayReadinessError, match="SKIPPED_REPLAY_DATES"):
        _service(executor, SkippedBuilder).run(
            from_date=_TRADE_DATE,
            to_date=_TRADE_DATE,
        )

    assert executor.calls == 0


def test_empty_replay_calendar_blocks_before_executor_runs() -> None:
    executor = CountingExecutor()

    with pytest.raises(HistoricalReplayReadinessError, match="NO_REPLAY_DATES"):
        _service(executor, EmptyBuilder).run(
            from_date=_TRADE_DATE,
            to_date=_TRADE_DATE,
        )

    assert executor.calls == 0


def test_missing_inventory_blocks_before_executor_runs() -> None:
    executor = CountingExecutor()

    with pytest.raises(
        HistoricalReplayReadinessError,
        match="MISSING_HISTORICAL_TRUTH_INVENTORY",
    ):
        _service(executor, ReadyBuilder, include_inventory=False).run(
            from_date=_TRADE_DATE,
            to_date=_TRADE_DATE,
        )

    assert executor.calls == 0


def test_unready_blocking_dataset_blocks_before_executor_runs() -> None:
    executor = CountingExecutor()

    with pytest.raises(
        HistoricalReplayReadinessError,
        match="BLOCKING_DATASETS_NOT_READY",
    ):
        _service(
            executor,
            ReadyBuilder,
            unready_keys=("daily_ohlcv",),
        ).run(from_date=_TRADE_DATE, to_date=_TRADE_DATE)

    assert executor.calls == 0


def test_ready_certificate_allows_executor_once() -> None:
    executor = CountingExecutor()

    run = _service(executor, ReadyBuilder).run(
        from_date=_TRADE_DATE,
        to_date=_TRADE_DATE,
    )

    assert run.readiness.status is HistoricalReplayReadinessStatus.READY
    assert run.readiness.inventory_evidence[0].year == 2025
    assert executor.calls == 1
