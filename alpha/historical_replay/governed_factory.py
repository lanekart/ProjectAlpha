"""Governed historical observation construction backed by canonical replay."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from alpha.historical_replay.factory import (
    HistoricalObservationBuildResult,
    HistoricalObservationFactory,
)
from alpha.historical_replay.governed_price_repository import (
    CanonicalReplayPriceRepository,
    CanonicalReplayReadOperation,
    CanonicalReplayRepositoryRead,
)
from alpha.historical_replay.models import ReplayCandidateObservation
from alpha.recovery.consumer_attestation import (
    CanonicalReplayConsumerAttestation,
    attestation_payload,
)

GOVERNED_OBSERVATION_CONTRACT_VERSION = "HTR-005-observation-v1.0.0"


class HistoricalObservationBuilder(Protocol):
    """Observation builder contract wrapped by the governed service."""

    def build(
        self,
        *,
        from_date: date,
        to_date: date,
    ) -> HistoricalObservationBuildResult:
        """Build historical observations for one inclusive range."""
        ...


@dataclass(frozen=True, slots=True)
class GovernedHistoricalObservationBuild:
    """Historical observations coupled to exact canonical replay proofs."""

    result: HistoricalObservationBuildResult
    repository_reads: tuple[CanonicalReplayRepositoryRead, ...]
    consumer_attestations: tuple[CanonicalReplayConsumerAttestation, ...]
    contract_version: str = GOVERNED_OBSERVATION_CONTRACT_VERSION
    canonical_replay_enforced: bool = True

    def __post_init__(self) -> None:
        if self.contract_version != GOVERNED_OBSERVATION_CONTRACT_VERSION:
            raise ValueError("unsupported governed observation contract")
        if not self.canonical_replay_enforced:
            raise ValueError("governed observations must enforce canonical replay")
        if any(not item.canonical_replay_enforced for item in self.repository_reads):
            raise ValueError(
                "governed observations contain an unenforced repository read"
            )
        if any(
            not item.canonical_replay_enforced for item in self.consumer_attestations
        ):
            raise ValueError(
                "governed observations contain an unenforced consumer frame"
            )
        replay_dates = set(self.result.replay_dates)
        covered_dates = {
            item.start_date
            for item in self.repository_reads
            if item.operation is CanonicalReplayReadOperation.TRADE_DATE
            and item.start_date == item.end_date
        }
        missing_dates = replay_dates.difference(covered_dates)
        if missing_dates:
            rendered = ", ".join(item.isoformat() for item in sorted(missing_dates))
            raise ValueError(
                f"governed observations are missing trade-date proofs: {rendered}"
            )
        if replay_dates and not self.consumer_attestations:
            raise ValueError("governed observations require consumer attestations")

    @property
    def observations(self) -> tuple[ReplayCandidateObservation, ...]:
        """Expose the immutable observation sequence."""

        return self.result.observations

    @property
    def replay_dates(self) -> tuple[date, ...]:
        """Expose replay dates from the underlying build result."""

        return self.result.replay_dates

    @property
    def skipped_dates(self) -> tuple[str, ...]:
        """Expose deterministic skipped-date reasons."""

        return self.result.skipped_dates

    @property
    def run_sha256(self) -> str:
        """Return a deterministic digest over result counts and replay proofs."""

        payload = self.as_dict(include_digest=False)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def as_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        """Return a stable JSON-compatible governed run manifest."""

        payload: dict[str, object] = {
            "observation_count": len(self.result.observations),
            "replay_dates": [item.isoformat() for item in self.result.replay_dates],
            "skipped_dates": list(self.result.skipped_dates),
            "repository_reads": [item.as_dict() for item in self.repository_reads],
            "consumer_attestations": [
                attestation_payload(item, include_digest=True)
                for item in self.consumer_attestations
            ],
            "contract_version": self.contract_version,
            "canonical_replay_enforced": self.canonical_replay_enforced,
        }
        if include_digest:
            payload["run_sha256"] = self.run_sha256
        return payload


class GovernedHistoricalObservationFactory:
    """Require canonical replay for historical observation construction."""

    def __init__(
        self,
        *,
        price_repository: CanonicalReplayPriceRepository,
        builder: HistoricalObservationBuilder | None = None,
    ) -> None:
        if not isinstance(price_repository, CanonicalReplayPriceRepository):
            raise TypeError(
                "governed historical observations require "
                "CanonicalReplayPriceRepository"
            )
        self.price_repository = price_repository
        self.builder = builder or HistoricalObservationFactory(
            price_repository=price_repository
        )

    def build(
        self,
        *,
        from_date: date,
        to_date: date,
    ) -> GovernedHistoricalObservationBuild:
        """Build observations and capture only proofs produced by this run."""

        if to_date < from_date:
            raise ValueError("to_date must be on or after from_date")
        read_offset = len(self.price_repository.reads)
        attestation_offset = len(self.price_repository.consumer_attestations)
        result = self.builder.build(from_date=from_date, to_date=to_date)
        reads = self.price_repository.reads[read_offset:]
        attestations = self.price_repository.consumer_attestations[attestation_offset:]
        return GovernedHistoricalObservationBuild(
            result=result,
            repository_reads=reads,
            consumer_attestations=attestations,
        )


def governed_run_payloads(
    runs: Sequence[GovernedHistoricalObservationBuild],
) -> list[dict[str, object]]:
    """Return deterministic run manifests sorted by replay range and digest."""

    ordered = sorted(
        runs,
        key=lambda item: (
            item.replay_dates[0] if item.replay_dates else date.min,
            item.replay_dates[-1] if item.replay_dates else date.min,
            item.run_sha256,
        ),
    )
    return [item.as_dict() for item in ordered]


__all__ = [
    "GOVERNED_OBSERVATION_CONTRACT_VERSION",
    "GovernedHistoricalObservationBuild",
    "GovernedHistoricalObservationFactory",
    "HistoricalObservationBuilder",
    "governed_run_payloads",
]
