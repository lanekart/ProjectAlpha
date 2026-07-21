"""Tests for governed historical replay CLI application helpers."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

import pandas as pd
import pytest

from alpha.application.governed_historical_replay_cli import (
    execute_governed_historical_replay,
    render_governed_historical_replay_run,
)
from alpha.candidate_learning import LearningLedgerRepository
from alpha.historical_replay.factory import HistoricalObservationBuildResult
from alpha.historical_replay.governed_price_repository import (
    CanonicalReplayPriceRepository,
)
from alpha.historical_replay.models import ReplayCandidateObservation, ReplayRunRecord
from tests.historical_replay.coverage_fixtures import coverage_evidence
from tests.historical_replay.inventory_fixtures import inventory_evidence

_TRADE_DATE = date(2025, 1, 10)


@dataclass(slots=True)
class FakeSource:
    frame: pd.DataFrame
    closed: bool = False

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        return self._range(start=trade_date, end=trade_date, symbols=())

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        return self._range(start=date.min, end=end_date, symbols=symbols).tail(limit)

    def find_range_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        return self._range(start=start_date, end=end_date, symbols=symbols)

    def find_trade_dates(self, *, start: date, end: date) -> tuple[date, ...]:
        frame = self._range(start=start, end=end, symbols=())
        return tuple(sorted(set(frame["trade_date"]))) if not frame.empty else ()

    def close(self) -> None:
        self.closed = True

    def _range(
        self,
        *,
        start: date,
        end: date,
        symbols: tuple[str, ...],
    ) -> pd.DataFrame:
        frame = self.frame.copy()
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
        mask = (frame["trade_date"] >= start) & (frame["trade_date"] <= end)
        if symbols:
            mask &= frame["symbol"].str.upper().isin(symbols)
        return frame.loc[mask].reset_index(drop=True)


@dataclass(slots=True)
class ReadingBuilder:
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
class FakeExecutor:
    def run(
        self,
        *,
        from_date: date,
        to_date: date,
        observations: tuple[ReplayCandidateObservation, ...] = (),
    ) -> tuple[ReplayRunRecord, ...]:
        del to_date, observations
        return (
            ReplayRunRecord(
                replay_run_id=f"replay-{from_date.isoformat()}",
                replay_date=from_date,
                symbols_scanned=1,
                candidates_stored=0,
                emitted_decisions=0,
                approved_recommendations=0,
                market_regime="BULLISH",
                long_trade_permission=True,
                data_cutoff_date=from_date,
                outcome_windows_available=("5D",),
                data_gaps=0,
                runtime_seconds=Decimal("0.01"),
                created_at=datetime(2025, 1, 10, tzinfo=UTC),
            ),
        )


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    identity_path = tmp_path / "identities.csv"
    action_path = tmp_path / "actions.csv"
    with identity_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("security_id", "symbol", "exchange"),
        )
        writer.writeheader()
        writer.writerow({"security_id": "SEC-1", "symbol": "ALPHA", "exchange": "NSE"})
    action_path.write_text(
        "event_id,security_id,symbol,action_type,effective_date,status\n",
        encoding="utf-8",
    )
    return identity_path, action_path


def _source() -> FakeSource:
    return FakeSource(
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


def test_execute_helper_loads_artifacts_exports_and_closes_source(
    tmp_path: Path,
) -> None:
    identity_path, action_path = _write_inputs(tmp_path)
    source = _source()
    output = tmp_path / "output"

    run = execute_governed_historical_replay(
        from_date=_TRADE_DATE,
        to_date=_TRADE_DATE,
        identity_artifact=identity_path,
        corporate_action_artifact=action_path,
        learning_repository=cast(LearningLedgerRepository, object()),
        output=output,
        source=source,
        executor=FakeExecutor(),
        inventory_evidence=inventory_evidence(period_end=_TRADE_DATE),
        coverage_evidence=coverage_evidence(
            from_date=_TRADE_DATE,
            to_date=_TRADE_DATE,
        ),
        observation_builder_factory=ReadingBuilder,
    )

    assert source.closed
    assert run.canonical_replay_enforced
    assert run.readiness.inventory_evidence[0].year == 2025
    assert run.readiness.coverage_evidence is not None
    assert run.readiness.coverage_evidence.eligible_security_count == 1
    assert (output / "governed_historical_replay_run.json").exists()
    lines = render_governed_historical_replay_run(run)
    assert lines[0] == "Governed Historical Replay"
    assert "Readiness Status: READY" in lines
    assert "Inventory Years: 1" in lines
    assert "Warm-up Sessions: 200" in lines
    assert "Outcome Sessions: 60" in lines
    assert "Eligible Securities: 1" in lines
    assert "Canonical Replay Enforced: true" in lines


def test_execute_helper_fails_before_raw_replay_when_artifacts_are_missing(
    tmp_path: Path,
) -> None:
    source = _source()

    with pytest.raises(FileNotFoundError):
        execute_governed_historical_replay(
            from_date=_TRADE_DATE,
            to_date=_TRADE_DATE,
            identity_artifact=tmp_path / "missing-identities.csv",
            corporate_action_artifact=tmp_path / "missing-actions.csv",
            learning_repository=cast(LearningLedgerRepository, object()),
            source=source,
            executor=FakeExecutor(),
            inventory_evidence=inventory_evidence(period_end=_TRADE_DATE),
            coverage_evidence=coverage_evidence(
                from_date=_TRADE_DATE,
                to_date=_TRADE_DATE,
            ),
            observation_builder_factory=ReadingBuilder,
        )

    assert not source.closed
