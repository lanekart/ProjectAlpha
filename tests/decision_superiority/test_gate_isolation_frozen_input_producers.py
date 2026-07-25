from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

import pytest

from alpha.decision_superiority.gate_isolation_frozen_input_producers import (
    CANDIDATE_FEATURE_PRODUCER_VERSION,
    PORTFOLIO_STATE_PRODUCER_VERSION,
    CandidateFeatureCaptureInput,
    CandidateFeatureSnapshotProducer,
    PortfolioStateCaptureInput,
    PortfolioStateSnapshotProducer,
)
from alpha.decision_superiority.gate_isolation_frozen_inputs import FrozenInputSection


class _State(StrEnum):
    OPEN = "OPEN"


@dataclass(frozen=True, slots=True)
class _PortfolioContext:
    cash: Decimal
    observed_on: date
    sectors: frozenset[str]
    state: _State


def test_candidate_feature_producer_is_deterministic() -> None:
    capture_input = CandidateFeatureCaptureInput(
        candidate_payload={"score": Decimal("7.5"), "symbol": "AAA"},
        market_payload={"regime": "BULL", "breadth": Decimal("0.6")},
        feature_version="feature-v1",
        source_hashes={"analysis": "abc", "history": "def"},
        observed_on="2026-07-26",
    )

    first = CandidateFeatureSnapshotProducer().produce(capture_input)
    second = CandidateFeatureSnapshotProducer().produce(capture_input)

    assert first == second
    assert first.section is FrozenInputSection.CANDIDATE_FEATURES
    assert first.source_version == CANDIDATE_FEATURE_PRODUCER_VERSION
    payload = json.loads(first.payload_json)
    assert payload["candidate"]["score"] == "7.5"
    assert payload["source_hashes"] == {"analysis": "abc", "history": "def"}


def test_portfolio_state_producer_serialises_contexts_canonically() -> None:
    context = _PortfolioContext(
        cash=Decimal("1000.50"),
        observed_on=date(2026, 7, 26),
        sectors=frozenset({"IT", "BANKS"}),
        state=_State.OPEN,
    )
    capture_input = PortfolioStateCaptureInput(
        recommendation_context=context,
        allocation_context={"heat": Decimal("0.25")},
        state_version="portfolio-v1",
        observed_on="2026-07-26",
    )

    snapshot = PortfolioStateSnapshotProducer().produce(capture_input)

    assert snapshot.section is FrozenInputSection.PORTFOLIO_STATE
    assert snapshot.source_version == PORTFOLIO_STATE_PRODUCER_VERSION
    payload = json.loads(snapshot.payload_json)
    assert payload["allocation_context"]["heat"] == "0.25"
    assert payload["recommendation_context"]["cash"] == "1000.50"
    assert payload["recommendation_context"]["sectors"] == ["BANKS", "IT"]
    assert payload["recommendation_context"]["state"] == "OPEN"


def test_candidate_feature_input_requires_source_hashes() -> None:
    with pytest.raises(ValueError, match="source_hashes cannot be empty"):
        CandidateFeatureCaptureInput(
            candidate_payload={"symbol": "AAA"},
            market_payload={"regime": "BULL"},
            feature_version="feature-v1",
            source_hashes={},
            observed_on="2026-07-26",
        )


def test_unsupported_values_fail_closed() -> None:
    capture_input = CandidateFeatureCaptureInput(
        candidate_payload={"unsupported": object()},
        market_payload={"regime": "BULL"},
        feature_version="feature-v1",
        source_hashes={"analysis": "abc"},
        observed_on="2026-07-26",
    )

    with pytest.raises(TypeError, match="unsupported frozen-input value type"):
        CandidateFeatureSnapshotProducer().produce(capture_input)
