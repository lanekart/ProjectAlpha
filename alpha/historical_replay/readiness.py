"""Fail-closed readiness certificates for governed historical replay."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum

from alpha.historical_replay.governed_factory import GovernedHistoricalObservationBuild

HISTORICAL_REPLAY_READINESS_CONTRACT_VERSION = "HTR-006-readiness-v1.0.0"


class HistoricalReplayReadinessStatus(StrEnum):
    """Whether a governed historical replay may invoke its executor."""

    READY = "READY"
    BLOCKED = "BLOCKED"


class HistoricalReplayReadinessBlocker(StrEnum):
    """Stable reasons that prevent authoritative replay execution."""

    NO_REPLAY_DATES = "NO_REPLAY_DATES"
    SKIPPED_REPLAY_DATES = "SKIPPED_REPLAY_DATES"


class HistoricalReplayReadinessError(ValueError):
    """Raised when an executable governed replay is not ready."""

    def __init__(self, certificate: HistoricalReplayReadinessCertificate) -> None:
        self.certificate = certificate
        rendered = ", ".join(item.value for item in certificate.blockers)
        super().__init__(f"historical replay readiness blocked: {rendered}")


@dataclass(frozen=True, slots=True)
class HistoricalReplayReadinessCertificate:
    """Immutable proof that a governed observation build is executable."""

    from_date: date
    to_date: date
    observation_run_sha256: str
    replay_dates: tuple[date, ...]
    skipped_dates: tuple[str, ...]
    repository_read_count: int
    consumer_attestation_count: int
    blockers: tuple[HistoricalReplayReadinessBlocker, ...]
    status: HistoricalReplayReadinessStatus
    contract_version: str = HISTORICAL_REPLAY_READINESS_CONTRACT_VERSION
    canonical_replay_enforced: bool = True

    def __post_init__(self) -> None:
        if self.to_date < self.from_date:
            raise ValueError("readiness end cannot precede start")
        if len(self.observation_run_sha256) != 64:
            raise ValueError("readiness observation digest must be SHA-256")
        if self.replay_dates != tuple(sorted(set(self.replay_dates))):
            raise ValueError("readiness replay dates must be sorted and unique")
        if any(
            item < self.from_date or item > self.to_date for item in self.replay_dates
        ):
            raise ValueError("readiness replay date falls outside requested range")
        if self.repository_read_count < 0:
            raise ValueError("readiness repository read count cannot be negative")
        if self.consumer_attestation_count < 0:
            raise ValueError("readiness attestation count cannot be negative")
        if self.blockers != tuple(sorted(set(self.blockers), key=str)):
            raise ValueError("readiness blockers must be sorted and unique")
        expected_status = (
            HistoricalReplayReadinessStatus.BLOCKED
            if self.blockers
            else HistoricalReplayReadinessStatus.READY
        )
        if self.status is not expected_status:
            raise ValueError("readiness status does not match blockers")
        if self.status is HistoricalReplayReadinessStatus.READY:
            if not self.replay_dates:
                raise ValueError("ready replay requires at least one replay date")
            if self.skipped_dates:
                raise ValueError("ready replay cannot contain skipped dates")
        if self.contract_version != HISTORICAL_REPLAY_READINESS_CONTRACT_VERSION:
            raise ValueError("unsupported historical replay readiness contract")
        if not self.canonical_replay_enforced:
            raise ValueError("historical replay readiness must enforce canonical replay")

    @property
    def readiness_sha256(self) -> str:
        """Return a deterministic digest over the readiness proof."""

        encoded = json.dumps(
            self.as_dict(include_digest=False),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def as_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        """Return a stable JSON-compatible readiness manifest."""

        payload = asdict(self)
        payload["from_date"] = self.from_date.isoformat()
        payload["to_date"] = self.to_date.isoformat()
        payload["replay_dates"] = [item.isoformat() for item in self.replay_dates]
        payload["skipped_dates"] = list(self.skipped_dates)
        payload["blockers"] = [item.value for item in self.blockers]
        payload["status"] = self.status.value
        if include_digest:
            payload["readiness_sha256"] = self.readiness_sha256
        return payload

    def assert_ready(self) -> None:
        """Fail closed when the certificate is not executable."""

        if self.status is HistoricalReplayReadinessStatus.BLOCKED:
            raise HistoricalReplayReadinessError(self)


def assess_historical_replay_readiness(
    build: GovernedHistoricalObservationBuild,
    *,
    from_date: date,
    to_date: date,
) -> HistoricalReplayReadinessCertificate:
    """Assess one governed observation build without invoking a replay executor."""

    blockers: list[HistoricalReplayReadinessBlocker] = []
    if not build.replay_dates:
        blockers.append(HistoricalReplayReadinessBlocker.NO_REPLAY_DATES)
    if build.skipped_dates:
        blockers.append(HistoricalReplayReadinessBlocker.SKIPPED_REPLAY_DATES)
    ordered_blockers = tuple(sorted(set(blockers), key=str))
    status = (
        HistoricalReplayReadinessStatus.BLOCKED
        if ordered_blockers
        else HistoricalReplayReadinessStatus.READY
    )
    return HistoricalReplayReadinessCertificate(
        from_date=from_date,
        to_date=to_date,
        observation_run_sha256=build.run_sha256,
        replay_dates=build.replay_dates,
        skipped_dates=build.skipped_dates,
        repository_read_count=len(build.repository_reads),
        consumer_attestation_count=len(build.consumer_attestations),
        blockers=ordered_blockers,
        status=status,
    )


__all__ = [
    "HISTORICAL_REPLAY_READINESS_CONTRACT_VERSION",
    "HistoricalReplayReadinessBlocker",
    "HistoricalReplayReadinessCertificate",
    "HistoricalReplayReadinessError",
    "HistoricalReplayReadinessStatus",
    "assess_historical_replay_readiness",
]
