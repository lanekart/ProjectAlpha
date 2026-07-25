"""Immutable frozen-input producers for candidate features and portfolio state."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenInputSection,
    FrozenInputSectionSnapshot,
)

CANDIDATE_FEATURE_PRODUCER_VERSION = "DSI-002A-candidate-features-v1"
PORTFOLIO_STATE_PRODUCER_VERSION = "DSI-002A-portfolio-state-v1"


@dataclass(frozen=True, slots=True)
class CandidateFeatureCaptureInput:
    """Immutable inputs required to preserve candidate feature state."""

    candidate_payload: Mapping[str, object]
    market_payload: Mapping[str, object]
    feature_version: str
    source_hashes: Mapping[str, str]
    observed_on: str

    def __post_init__(self) -> None:
        if not self.feature_version.strip():
            raise ValueError("feature_version cannot be empty")
        if not self.observed_on.strip():
            raise ValueError("observed_on cannot be empty")
        if not self.source_hashes:
            raise ValueError("source_hashes cannot be empty")
        if any(not key.strip() or not value.strip() for key, value in self.source_hashes.items()):
            raise ValueError("source_hashes keys and values cannot be empty")


@dataclass(frozen=True, slots=True)
class PortfolioStateCaptureInput:
    """Immutable portfolio contexts available before recommendation evaluation."""

    recommendation_context: object
    allocation_context: object
    state_version: str
    observed_on: str

    def __post_init__(self) -> None:
        if not self.state_version.strip():
            raise ValueError("state_version cannot be empty")
        if not self.observed_on.strip():
            raise ValueError("observed_on cannot be empty")


class CandidateFeatureSnapshotProducer:
    """Produce the candidate-features section without mutating source objects."""

    def produce(
        self,
        capture_input: CandidateFeatureCaptureInput,
    ) -> FrozenInputSectionSnapshot:
        """Return a canonical candidate-feature section snapshot."""

        payload = {
            "candidate": _normalise(capture_input.candidate_payload),
            "feature_version": capture_input.feature_version,
            "market": _normalise(capture_input.market_payload),
            "source_hashes": _normalise(capture_input.source_hashes),
        }
        return FrozenInputSectionSnapshot.from_mapping(
            section=FrozenInputSection.CANDIDATE_FEATURES,
            payload=payload,
            source_version=CANDIDATE_FEATURE_PRODUCER_VERSION,
            observed_on=capture_input.observed_on,
        )


class PortfolioStateSnapshotProducer:
    """Produce the pre-decision portfolio-state section deterministically."""

    def produce(
        self,
        capture_input: PortfolioStateCaptureInput,
    ) -> FrozenInputSectionSnapshot:
        """Return a canonical portfolio-state section snapshot."""

        payload = {
            "allocation_context": _normalise(capture_input.allocation_context),
            "recommendation_context": _normalise(
                capture_input.recommendation_context
            ),
            "state_version": capture_input.state_version,
        }
        return FrozenInputSectionSnapshot.from_mapping(
            section=FrozenInputSection.PORTFOLIO_STATE,
            payload=payload,
            source_version=PORTFOLIO_STATE_PRODUCER_VERSION,
            observed_on=capture_input.observed_on,
        )


def _normalise(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return _normalise(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _normalise(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalised = [_normalise(item) for item in value]
        return sorted(normalised, key=_sort_key)
    raise TypeError(f"unsupported frozen-input value type:{type(value).__name__}")


def _sort_key(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


__all__ = [
    "CANDIDATE_FEATURE_PRODUCER_VERSION",
    "PORTFOLIO_STATE_PRODUCER_VERSION",
    "CandidateFeatureCaptureInput",
    "CandidateFeatureSnapshotProducer",
    "PortfolioStateCaptureInput",
    "PortfolioStateSnapshotProducer",
]
