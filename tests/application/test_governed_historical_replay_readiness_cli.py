"""Tests for diagnostic governed historical replay readiness helpers."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from alpha.application.governed_historical_replay_cli import (
    assess_governed_historical_replay,
    render_governed_historical_replay_assessment,
)
from alpha.historical_replay.factory import HistoricalObservationBuildResult
from alpha.historical_replay.governed_price_repository import (
    CanonicalReplayPriceRepository,
)
from alpha.historical_replay.readiness import HistoricalReplayReadinessStatus
from tests.historical_replay.coverage_fixtures import coverage_evidence
from tests.historical_replay.inventory_fixtures import inventory_evidence

_TRADE_DATE = date(2025, 1, 10)


@dataclass(slots=True)
class FakeSource:
    frame: pd.DataFrame
    closed: bool = False

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

    def close(self) -> None:
        self.closed = True


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


def test_diagnostic_assessment_exports_without_executor_invocation(
    tmp_path: Path,
) -> None:
    identity_path, action_path = _write_inputs(tmp_path)
    source = _source()
    output = tmp_path / "readiness"

    assessment = assess_governed_historical_replay(
        from_date=_TRADE_DATE,
        to_date=_TRADE_DATE,
        identity_artifact=identity_path,
        corporate_action_artifact=action_path,
        output=output,
        source=source,
        inventory_evidence=inventory_evidence(period_end=_TRADE_DATE),
        coverage_evidence=coverage_evidence(
            from_date=_TRADE_DATE,
            to_date=_TRADE_DATE,
        ),
        observation_builder_factory=ReadingBuilder,
    )

    assert source.closed
    assert assessment.readiness.status is HistoricalReplayReadinessStatus.READY
    assert assessment.as_dict()["executor_invoked"] is False
    assert (output / "historical_replay_readiness_assessment.json").exists()
    payload = json.loads(
        (output / "historical_replay_readiness_assessment.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["executor_invoked"] is False
    lines = render_governed_historical_replay_assessment(assessment)
    assert lines[0] == "Historical Replay Readiness Assessment"
    assert "Executor Invoked: false" in lines


def test_blocked_assessment_exports_instead_of_executing(tmp_path: Path) -> None:
    identity_path, action_path = _write_inputs(tmp_path)
    output = tmp_path / "blocked"

    assessment = assess_governed_historical_replay(
        from_date=_TRADE_DATE,
        to_date=_TRADE_DATE,
        identity_artifact=identity_path,
        corporate_action_artifact=action_path,
        output=output,
        source=_source(),
        inventory_evidence=inventory_evidence(
            period_end=_TRADE_DATE,
            unready_keys=("trading_calendar",),
        ),
        coverage_evidence=coverage_evidence(
            from_date=_TRADE_DATE,
            to_date=_TRADE_DATE,
        ),
        observation_builder_factory=ReadingBuilder,
    )

    assert assessment.readiness.status is HistoricalReplayReadinessStatus.BLOCKED
    assert (output / "historical_replay_readiness.json").exists()
    assert assessment.as_dict()["executor_invoked"] is False
