"""Tests for the governed historical replay application service."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from alpha.application.governed_historical_replay import (
    GovernedHistoricalReplayService,
    export_governed_historical_replay_run,
)
from alpha.historical_replay.factory import HistoricalObservationBuildResult
from alpha.historical_replay.governed_artifacts import (
    GovernedReplayInputManifest,
    GovernedReplayInputs,
)
from alpha.historical_replay.governed_price_repository import (
    CanonicalReplayPriceRepository,
)
from alpha.historical_replay.models import ReplayCandidateObservation, ReplayRunRecord
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
class FakeExecutor:
    replay_date: date = _TRADE_DATE
    data_cutoff_date: date = _TRADE_DATE
    runtime_seconds: Decimal = Decimal("0.01")
    created_at: datetime = datetime(2025, 1, 10, tzinfo=UTC)
    seen_observations: tuple[ReplayCandidateObservation, ...] = ()

    def run(
        self,
        *,
        from_date: date,
        to_date: date,
        observations: tuple[ReplayCandidateObservation, ...] = (),
    ) -> tuple[ReplayRunRecord, ...]:
        del from_date, to_date
        self.seen_observations = observations
        return (
            ReplayRunRecord(
                replay_run_id=f"replay-{self.replay_date.isoformat()}",
                replay_date=self.replay_date,
                symbols_scanned=1,
                candidates_stored=0,
                emitted_decisions=0,
                approved_recommendations=0,
                market_regime="BULLISH",
                long_trade_permission=True,
                data_cutoff_date=self.data_cutoff_date,
                outcome_windows_available=("5D", "20D"),
                data_gaps=0,
                runtime_seconds=self.runtime_seconds,
                created_at=self.created_at,
            ),
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
    actions = CorporateActionTimeline(())
    manifest = GovernedReplayInputManifest(
        identity_path="identities.csv",
        corporate_action_path="actions.csv",
        identity_sha256="1" * 64,
        corporate_action_sha256="2" * 64,
        identity_count=1,
        corporate_action_count=0,
        unresolved_action_ids=(),
        security_ids=("SEC-1",),
    )
    return GovernedReplayInputs(
        identities=identities,
        actions=actions,
        manifest=manifest,
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


def _service(executor: FakeExecutor) -> GovernedHistoricalReplayService:
    return GovernedHistoricalReplayService(
        source=_source(),
        inputs=_inputs(),
        executor=executor,
        observation_builder_factory=ReadingBuilder,
    )


def test_service_binds_inputs_observations_and_engine_outputs() -> None:
    executor = FakeExecutor()

    run = _service(executor).run(from_date=_TRADE_DATE, to_date=_TRADE_DATE)

    assert run.canonical_replay_enforced
    assert run.inputs.manifest.security_ids == ("SEC-1",)
    assert len(run.observation_build.repository_reads) == 3
    assert len(run.observation_build.consumer_attestations) == 3
    assert run.replay_runs[0].replay_date == _TRADE_DATE
    assert executor.seen_observations == ()
    assert len(run.run_sha256) == 64


def test_run_digest_excludes_runtime_and_wall_clock_noise() -> None:
    first = _service(FakeExecutor()).run(
        from_date=_TRADE_DATE,
        to_date=_TRADE_DATE,
    )
    second = _service(
        FakeExecutor(
            runtime_seconds=Decimal("9.99"),
            created_at=datetime(2030, 1, 1, tzinfo=UTC),
        )
    ).run(from_date=_TRADE_DATE, to_date=_TRADE_DATE)

    assert first.run_sha256 == second.run_sha256
    assert first.as_dict() == second.as_dict()


def test_service_rejects_ungoverned_engine_dates_and_cutoffs() -> None:
    with pytest.raises(ValueError, match="ungoverned dates"):
        _service(FakeExecutor(replay_date=date(2025, 1, 11))).run(
            from_date=_TRADE_DATE,
            to_date=_TRADE_DATE,
        )

    with pytest.raises(ValueError, match="non-point-in-time data cutoff"):
        _service(FakeExecutor(data_cutoff_date=date(2025, 1, 9))).run(
            from_date=_TRADE_DATE,
            to_date=_TRADE_DATE,
        )


def test_run_exports_are_deterministic_and_complete(tmp_path: Path) -> None:
    run = _service(FakeExecutor()).run(
        from_date=_TRADE_DATE,
        to_date=_TRADE_DATE,
    )

    first_paths = export_governed_historical_replay_run(run, tmp_path)
    first_content = {
        path.name: path.read_text(encoding="utf-8") for path in first_paths
    }
    second_paths = export_governed_historical_replay_run(run, tmp_path)
    second_content = {
        path.name: path.read_text(encoding="utf-8") for path in second_paths
    }

    assert first_content == second_content
    assert tuple(path.name for path in first_paths) == (
        "governed_historical_replay_run.json",
        "governed_replay_inputs.json",
        "governed_replay_reads.csv",
        "governed_historical_replay_run.md",
        "canonical_replay_attestations.json",
        "canonical_replay_attestations.csv",
        "canonical_replay_attestations.md",
    )
    payload = json.loads(first_content["governed_historical_replay_run.json"])
    assert payload["canonical_replay_enforced"] is True
    assert payload["run_sha256"] == run.run_sha256
    assert payload["inputs"]["manifest_sha256"] == run.inputs.manifest.manifest_sha256
