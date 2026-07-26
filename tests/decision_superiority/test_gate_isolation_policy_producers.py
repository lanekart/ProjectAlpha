from __future__ import annotations

import json
from decimal import Decimal

import pytest

from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenInputSection,
)
from alpha.decision_superiority.gate_isolation_policy_producers import (
    APPROVAL_POLICY_PRODUCER_VERSION,
    ENTRY_POLICY_PRODUCER_VERSION,
    ApprovalPolicyCaptureInput,
    ApprovalPolicySnapshotProducer,
    EntryPolicyCaptureInput,
    EntryPolicySnapshotProducer,
)


def test_approval_policy_producer_is_deterministic() -> None:
    capture_input = ApprovalPolicyCaptureInput(
        policy_payload={"minimum_score": Decimal("70")},
        policy_version="approval-v1",
        threshold_provenance={"minimum_score": "governed-config"},
        dependency_versions={"risk": "risk-v2"},
        observed_on="2026-07-26",
    )

    first = ApprovalPolicySnapshotProducer().produce(capture_input)
    second = ApprovalPolicySnapshotProducer().produce(capture_input)

    assert first == second
    assert first.section is FrozenInputSection.APPROVAL_POLICY
    assert first.source_version == APPROVAL_POLICY_PRODUCER_VERSION
    payload = json.loads(first.payload_json)
    assert payload["policy"]["minimum_score"] == "70"
    assert payload["policy_version"] == "approval-v1"
    assert payload["dependency_versions"] == {"risk": "risk-v2"}


def test_entry_policy_producer_is_deterministic() -> None:
    capture_input = EntryPolicyCaptureInput(
        policy_payload={"style": "BREAKOUT"},
        policy_version="entry-v1",
        trigger_payload={"trigger_price": Decimal("101.25")},
        trigger_source_hashes={"daily-candle": "abc123"},
        observed_on="2026-07-26",
    )

    first = EntryPolicySnapshotProducer().produce(capture_input)
    second = EntryPolicySnapshotProducer().produce(capture_input)

    assert first == second
    assert first.section is FrozenInputSection.ENTRY_POLICY
    assert first.source_version == ENTRY_POLICY_PRODUCER_VERSION
    payload = json.loads(first.payload_json)
    assert payload["policy"]["style"] == "BREAKOUT"
    assert payload["trigger"]["trigger_price"] == "101.25"
    assert payload["trigger_source_hashes"] == {"daily-candle": "abc123"}


def test_approval_policy_requires_threshold_provenance() -> None:
    with pytest.raises(
        ValueError,
        match="threshold_provenance cannot be empty",
    ):
        ApprovalPolicyCaptureInput(
            policy_payload={"minimum_score": 70},
            policy_version="approval-v1",
            threshold_provenance={},
            dependency_versions={"risk": "risk-v2"},
            observed_on="2026-07-26",
        )


def test_entry_policy_requires_trigger_source_hashes() -> None:
    with pytest.raises(
        ValueError,
        match="trigger_source_hashes cannot be empty",
    ):
        EntryPolicyCaptureInput(
            policy_payload={"style": "BREAKOUT"},
            policy_version="entry-v1",
            trigger_payload={"trigger_price": "101.25"},
            trigger_source_hashes={},
            observed_on="2026-07-26",
        )
