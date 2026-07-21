"""Tests for deterministic historical replay readiness certificates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from alpha.historical_replay.readiness import (
    HistoricalReplayReadinessBlocker,
    HistoricalReplayReadinessCertificate,
    HistoricalReplayReadinessError,
    HistoricalReplayReadinessStatus,
    assess_historical_replay_readiness,
)

_FROM = date(2025, 1, 10)
_TO = date(2025, 1, 20)


@dataclass(frozen=True, slots=True)
class StubBuild:
    replay_dates: tuple[date, ...]
    skipped_dates: tuple[str, ...]
    repository_reads: tuple[object, ...] = ()
    consumer_attestations: tuple[object, ...] = ()
    run_sha256: str = "a" * 64


def test_ready_certificate_is_deterministic() -> None:
    build = StubBuild(
        replay_dates=(_FROM, _TO),
        skipped_dates=(),
        repository_reads=(object(), object()),
        consumer_attestations=(object(), object()),
    )

    first = assess_historical_replay_readiness(
        build,  # type: ignore[arg-type]
        from_date=_FROM,
        to_date=_TO,
    )
    second = assess_historical_replay_readiness(
        build,  # type: ignore[arg-type]
        from_date=_FROM,
        to_date=_TO,
    )

    assert first.status is HistoricalReplayReadinessStatus.READY
    assert first.blockers == ()
    assert first.repository_read_count == 2
    assert first.consumer_attestation_count == 2
    assert first.readiness_sha256 == second.readiness_sha256
    assert first.as_dict() == second.as_dict()
    first.assert_ready()


def test_no_replay_dates_blocks_execution() -> None:
    certificate = assess_historical_replay_readiness(
        StubBuild(replay_dates=(), skipped_dates=()),  # type: ignore[arg-type]
        from_date=_FROM,
        to_date=_TO,
    )

    assert certificate.status is HistoricalReplayReadinessStatus.BLOCKED
    assert certificate.blockers == (HistoricalReplayReadinessBlocker.NO_REPLAY_DATES,)
    with pytest.raises(HistoricalReplayReadinessError, match="NO_REPLAY_DATES"):
        certificate.assert_ready()


def test_skipped_replay_dates_block_execution() -> None:
    certificate = assess_historical_replay_readiness(
        StubBuild(
            replay_dates=(_FROM,),
            skipped_dates=(f"{_FROM.isoformat()}: no persisted prices",),
        ),  # type: ignore[arg-type]
        from_date=_FROM,
        to_date=_TO,
    )

    assert certificate.status is HistoricalReplayReadinessStatus.BLOCKED
    assert certificate.blockers == (
        HistoricalReplayReadinessBlocker.SKIPPED_REPLAY_DATES,
    )


def test_certificate_rejects_status_that_disagrees_with_blockers() -> None:
    with pytest.raises(ValueError, match="status does not match blockers"):
        HistoricalReplayReadinessCertificate(
            from_date=_FROM,
            to_date=_TO,
            observation_run_sha256="a" * 64,
            replay_dates=(_FROM,),
            skipped_dates=(),
            repository_read_count=1,
            consumer_attestation_count=1,
            blockers=(HistoricalReplayReadinessBlocker.SKIPPED_REPLAY_DATES,),
            status=HistoricalReplayReadinessStatus.READY,
        )
