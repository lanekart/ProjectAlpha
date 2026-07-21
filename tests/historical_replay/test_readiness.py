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
    verify_historical_replay_readiness_manifest,
)
from tests.historical_replay.coverage_fixtures import coverage_evidence
from tests.historical_replay.inventory_fixtures import inventory_evidence

_FROM = date(2025, 1, 10)
_TO = date(2025, 1, 20)


@dataclass(frozen=True, slots=True)
class StubBuild:
    replay_dates: tuple[date, ...]
    skipped_dates: tuple[str, ...]
    repository_reads: tuple[object, ...] = ()
    consumer_attestations: tuple[object, ...] = ()
    run_sha256: str = "a" * 64


def _inventory(*, unready_keys: tuple[str, ...] = ()):
    return inventory_evidence(period_end=_TO, unready_keys=unready_keys)


def _coverage(
    *,
    warmup_sessions: int = 200,
    outcome_sessions: int = 60,
    eligible_security_ids: tuple[str, ...] = ("SEC-1",),
):
    return coverage_evidence(
        from_date=_FROM,
        to_date=_TO,
        warmup_sessions=warmup_sessions,
        outcome_sessions=outcome_sessions,
        eligible_security_ids=eligible_security_ids,
    )


def _ready_certificate() -> HistoricalReplayReadinessCertificate:
    return assess_historical_replay_readiness(
        StubBuild(replay_dates=(_FROM, _TO), skipped_dates=()),  # type: ignore[arg-type]
        from_date=_FROM,
        to_date=_TO,
        inventory_evidence=_inventory(),
        coverage_evidence=_coverage(),
    )


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
        inventory_evidence=_inventory(),
        coverage_evidence=_coverage(),
    )
    second = assess_historical_replay_readiness(
        build,  # type: ignore[arg-type]
        from_date=_FROM,
        to_date=_TO,
        inventory_evidence=_inventory(),
        coverage_evidence=_coverage(),
    )

    assert first.status is HistoricalReplayReadinessStatus.READY
    assert first.blockers == ()
    assert first.repository_read_count == 2
    assert first.consumer_attestation_count == 2
    assert (
        first.inventory_evidence[0].inventory_sha256
        == second.inventory_evidence[0].inventory_sha256
    )
    assert first.coverage_evidence is not None
    assert second.coverage_evidence is not None
    assert (
        first.coverage_evidence.coverage_sha256
        == second.coverage_evidence.coverage_sha256
    )
    assert first.readiness_sha256 == second.readiness_sha256
    assert first.as_dict() == second.as_dict()
    first.assert_ready()


def test_no_replay_dates_blocks_execution() -> None:
    certificate = assess_historical_replay_readiness(
        StubBuild(replay_dates=(), skipped_dates=()),  # type: ignore[arg-type]
        from_date=_FROM,
        to_date=_TO,
        inventory_evidence=_inventory(),
        coverage_evidence=_coverage(),
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
        inventory_evidence=_inventory(),
        coverage_evidence=_coverage(),
    )

    assert certificate.status is HistoricalReplayReadinessStatus.BLOCKED
    assert certificate.blockers == (
        HistoricalReplayReadinessBlocker.SKIPPED_REPLAY_DATES,
    )


def test_missing_inventory_and_coverage_block_execution() -> None:
    certificate = assess_historical_replay_readiness(
        StubBuild(replay_dates=(_FROM,), skipped_dates=()),  # type: ignore[arg-type]
        from_date=_FROM,
        to_date=_TO,
    )

    assert certificate.blockers == (
        HistoricalReplayReadinessBlocker.MISSING_HISTORICAL_TRUTH_INVENTORY,
        HistoricalReplayReadinessBlocker.MISSING_REPLAY_COVERAGE_EVIDENCE,
    )


def test_source_validation_failure_mapping_blocks_execution() -> None:
    certificate = assess_historical_replay_readiness(
        StubBuild(replay_dates=(_FROM,), skipped_dates=()),  # type: ignore[arg-type]
        from_date=_FROM,
        to_date=_TO,
        inventory_evidence=_inventory(unready_keys=("daily_ohlcv",)),
        coverage_evidence=_coverage(),
    )

    assert certificate.blockers == (
        HistoricalReplayReadinessBlocker.BLOCKING_DATASETS_NOT_READY,
        HistoricalReplayReadinessBlocker.REQUIRED_DATASETS_NOT_READY,
    )


def test_missing_expected_sessions_mapping_blocks_execution() -> None:
    certificate = assess_historical_replay_readiness(
        StubBuild(replay_dates=(_FROM,), skipped_dates=()),  # type: ignore[arg-type]
        from_date=_FROM,
        to_date=_TO,
        inventory_evidence=_inventory(unready_keys=("trading_calendar",)),
        coverage_evidence=_coverage(),
    )

    assert certificate.blockers == (
        HistoricalReplayReadinessBlocker.BLOCKING_DATASETS_NOT_READY,
        HistoricalReplayReadinessBlocker.REQUIRED_DATASETS_NOT_READY,
    )


def test_coverage_blockers_are_deterministic() -> None:
    certificate = assess_historical_replay_readiness(
        StubBuild(replay_dates=(_FROM,), skipped_dates=()),  # type: ignore[arg-type]
        from_date=_FROM,
        to_date=_TO,
        inventory_evidence=_inventory(),
        coverage_evidence=_coverage(
            warmup_sessions=199,
            outcome_sessions=59,
            eligible_security_ids=(),
        ),
    )

    assert certificate.blockers == (
        HistoricalReplayReadinessBlocker.INSUFFICIENT_OUTCOME_SESSIONS,
        HistoricalReplayReadinessBlocker.INSUFFICIENT_WARMUP_SESSIONS,
        HistoricalReplayReadinessBlocker.ZERO_ELIGIBLE_SECURITIES,
    )


def test_readiness_manifest_digest_detects_tampering() -> None:
    payload = _ready_certificate().as_dict()
    verify_historical_replay_readiness_manifest(payload)

    payload["status"] = "BLOCKED"
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_historical_replay_readiness_manifest(payload)


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
            inventory_evidence=_inventory(),
            coverage_evidence=_coverage(),
            blockers=(HistoricalReplayReadinessBlocker.SKIPPED_REPLAY_DATES,),
            status=HistoricalReplayReadinessStatus.READY,
        )
