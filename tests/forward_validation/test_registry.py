from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from alpha.forward_validation.models import (
    ForwardValidationConfig,
    PolicyVersion,
    PositionEventDraft,
    PositionEventType,
)
from alpha.forward_validation.validation_registry import (
    ForwardValidationIntegrityError,
    ForwardValidationRegistry,
)


def test_snapshot_registry_is_immutable_idempotent_and_exportable(
    tmp_path, snapshot_factory
) -> None:  # type: ignore[no-untyped-def]
    registry = ForwardValidationRegistry(tmp_path / "registry.json")
    snapshot = snapshot_factory()

    assert registry.append_snapshots((snapshot,)) == 1
    assert registry.append_snapshots((snapshot,)) == 0
    assert registry.load_snapshots() == (snapshot,)

    tampered = replace(snapshot, confidence="LOW")
    with pytest.raises(ForwardValidationIntegrityError, match="hash mismatch"):
        registry.append_snapshots((tampered,))

    json_path = registry.export_json(tmp_path / "export.json")
    csv_paths = registry.export_csv(tmp_path / "csv")
    assert json_path.exists()
    assert {path.name for path in csv_paths} == {
        "events.csv",
        "snapshots.csv",
        "valuations.csv",
    }


def test_event_chain_is_append_only_and_idempotent(tmp_path, snapshot_factory) -> None:  # type: ignore[no-untyped-def]
    registry = ForwardValidationRegistry(tmp_path / "registry.json")
    snapshot = snapshot_factory()
    registry.append_snapshots((snapshot,))
    draft = PositionEventDraft(
        recommendation_id=snapshot.recommendation_id,
        symbol=snapshot.symbol,
        occurred_at=datetime(2026, 1, 2, tzinfo=UTC),
        event_type=PositionEventType.ENTRY,
        price=Decimal("100"),
        quantity=Decimal("10"),
        cash_delta=Decimal("-1000"),
        reason="test entry",
    )

    first = registry.append_event(draft)
    second = registry.append_event(draft)

    assert first == second
    assert len(registry.load_events()) == 1
    assert first.previous_hash == "GENESIS"


def test_config_is_immutable(tmp_path) -> None:  # type: ignore[no-untyped-def]
    registry = ForwardValidationRegistry(tmp_path / "registry.json")
    config = ForwardValidationConfig(
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        initial_capital=Decimal("100000"),
        policy_version=PolicyVersion("APPROVAL_POLICY_V1"),
    )

    assert registry.initialize(config) is True
    assert registry.initialize(config) is False
    with pytest.raises(ForwardValidationIntegrityError, match="different settings"):
        registry.initialize(replace(config, initial_capital=Decimal("200000")))
