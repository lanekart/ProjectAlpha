"""Tests for the HTR-004 canonical historical replay boundary."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from alpha.recovery.canonical_replay import (
    CanonicalReplayBuilder,
    CanonicalReplayStatus,
    canonical_replay_sha256,
)
from alpha.recovery.corporate_actions import (
    CorporateActionBar,
    CorporateActionEvent,
    CorporateActionStatus,
    CorporateActionTimeline,
    CorporateActionType,
)


def _bar(trading_date: date = date(2025, 1, 10)) -> CorporateActionBar:
    return CorporateActionBar(
        security_id="SEC-1",
        symbol="ALPHA",
        trading_date=trading_date,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("104"),
        volume=Decimal("1000"),
    )


def _event(
    *,
    status: CorporateActionStatus = CorporateActionStatus.RESOLVED,
    announced_at: date = date(2024, 12, 20),
) -> CorporateActionEvent:
    resolved = status is CorporateActionStatus.RESOLVED
    return CorporateActionEvent(
        event_id="SEC-1:SPLIT:2025-01-15",
        security_id="SEC-1",
        symbol="ALPHA",
        action_type=CorporateActionType.SPLIT,
        effective_date=date(2025, 1, 15),
        announced_at=announced_at,
        price_factor=Decimal("0.5") if resolved else None,
        volume_factor=Decimal("2") if resolved else None,
        old_symbol=None,
        new_symbol=None,
        cash_amount=None,
        ratio_numerator=Decimal("2"),
        ratio_denominator=Decimal("1"),
        status=status,
        confidence=Decimal("0.95"),
        evidence_ids=("corporate_action:0",),
        source="test",
    )


def test_build_preserves_raw_and_adjusted_values() -> None:
    replay = CanonicalReplayBuilder(CorporateActionTimeline((_event(),))).build_bar(
        _bar(), as_of=date(2025, 1, 15)
    )

    assert replay.status is CanonicalReplayStatus.READY
    assert replay.raw_close == Decimal("104")
    assert replay.adjusted_close == Decimal("52.00000000")
    assert replay.adjusted_volume == Decimal("2000.00000000")
    assert replay.applied_event_ids == ("SEC-1:SPLIT:2025-01-15",)
    assert replay.unresolved_event_ids == ()


def test_no_lookahead_before_announcement() -> None:
    replay = CanonicalReplayBuilder(CorporateActionTimeline((_event(),))).build_bar(
        _bar(date(2024, 12, 18)), as_of=date(2024, 12, 19)
    )

    assert replay.adjusted_close == Decimal("104.00000000")
    assert replay.applied_event_ids == ()


def test_unresolved_material_action_quarantines_prior_bars() -> None:
    timeline = CorporateActionTimeline(
        (_event(status=CorporateActionStatus.UNRESOLVED),)
    )
    builder = CanonicalReplayBuilder(timeline)

    replay = builder.build_bar(_bar(), as_of=date(2025, 1, 15))
    audit = builder.audit((_bar(),), as_of=date(2025, 1, 15))

    assert replay.status is CanonicalReplayStatus.QUARANTINED
    assert replay.unresolved_event_ids == ("SEC-1:SPLIT:2025-01-15",)
    assert audit.bars_quarantined == 1
    assert not audit.passed


def test_post_effective_bar_is_not_quarantined_by_prior_unresolved_action() -> None:
    timeline = CorporateActionTimeline(
        (_event(status=CorporateActionStatus.UNRESOLVED),)
    )
    replay = CanonicalReplayBuilder(timeline).build_bar(
        _bar(date(2025, 1, 15)), as_of=date(2025, 1, 15)
    )

    assert replay.status is CanonicalReplayStatus.READY
    assert replay.unresolved_event_ids == ()


def test_replay_rejects_future_observations() -> None:
    builder = CanonicalReplayBuilder(CorporateActionTimeline(()))

    with pytest.raises(ValueError, match="after the replay as_of"):
        builder.build_bar(_bar(date(2025, 1, 16)), as_of=date(2025, 1, 15))


def test_build_and_digest_are_order_independent() -> None:
    builder = CanonicalReplayBuilder(CorporateActionTimeline(()))
    first = builder.build(
        (_bar(date(2025, 1, 11)), _bar(date(2025, 1, 10))),
        as_of=date(2025, 1, 11),
    )
    second = builder.build(
        (_bar(date(2025, 1, 10)), _bar(date(2025, 1, 11))),
        as_of=date(2025, 1, 11),
    )

    assert first == second
    assert canonical_replay_sha256(first) == canonical_replay_sha256(second)
