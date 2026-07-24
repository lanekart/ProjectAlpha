"""Tests for the governed pandas bridge into canonical historical replay."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from alpha.recovery.corporate_actions import (
    CorporateActionEvent,
    CorporateActionStatus,
    CorporateActionTimeline,
    CorporateActionType,
)
from alpha.recovery.replay_frame import CanonicalReplayFrameAdapter
from alpha.recovery.security_timeline import (
    SecurityIdentityRecord,
    SecurityIdentityTimeline,
)

_TRADE_DATE = date(2025, 1, 10)
_AS_OF = date(2025, 1, 15)


def _identities() -> SecurityIdentityTimeline:
    return SecurityIdentityTimeline(
        (
            SecurityIdentityRecord(
                security_id="SEC-1",
                symbol="NEWALPHA",
                exchange="NSE",
                effective_from=date(2020, 1, 1),
                historical_symbols=("ALPHA",),
            ),
        )
    )


def _frame(symbol: str = "ALPHA") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "trade_date": _TRADE_DATE,
                "open": 100,
                "high": 110,
                "low": 90,
                "close": 104,
                "volume": 1000,
                "exchange": "NSE",
            }
        ]
    )


def _split(
    status: CorporateActionStatus = CorporateActionStatus.RESOLVED,
) -> CorporateActionEvent:
    resolved = status is CorporateActionStatus.RESOLVED
    return CorporateActionEvent(
        event_id="SEC-1:SPLIT:2025-01-15",
        security_id="SEC-1",
        symbol="ALPHA",
        action_type=CorporateActionType.SPLIT,
        effective_date=_AS_OF,
        announced_at=date(2024, 12, 20),
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


def test_canonicalizes_identity_prices_and_lineage() -> None:
    adapter = CanonicalReplayFrameAdapter(
        _identities(),
        CorporateActionTimeline((_split(),)),
    )

    result = adapter.canonicalize(
        _frame(),
        trade_date=_TRADE_DATE,
        as_of=_AS_OF,
    )

    row = result.frame.iloc[0]
    assert row["security_id"] == "SEC-1"
    assert row["raw_symbol"] == "ALPHA"
    assert row["symbol"] == "NEWALPHA"
    assert row["raw_close"] == 104
    assert row["adjusted_close"] == "52.00000000"
    assert row["close"] == 52.0
    assert row["volume"] == 2000.0
    assert row["replay_status"] == "READY"
    assert row["replay_as_of"] == _AS_OF.isoformat()
    assert row["canonical_replay_enforced"]
    assert row["applied_event_ids"] == ("SEC-1:SPLIT:2025-01-15",)
    assert row["canonical_frame_sha256"] == result.attestation.canonical_frame_sha256
    assert result.attestation.trade_date == _TRADE_DATE
    assert result.audit.bars_adjusted == 1
    assert result.audit.passed


def test_source_stable_id_resolves_interval_gap() -> None:
    identity = SecurityIdentityTimeline(
        (
            SecurityIdentityRecord(
                security_id="nse:isin:INE000A01001",
                symbol="ALPHA",
                exchange="NSE",
                effective_from=date(2025, 1, 11),
            ),
        )
    )
    frame = _frame()
    frame["security_id"] = "nse:isin:INE000A01001"
    frame["isin"] = "INE000A01001"
    adapter = CanonicalReplayFrameAdapter(identity, CorporateActionTimeline(()))

    result = adapter.canonicalize(
        frame,
        trade_date=_TRADE_DATE,
        as_of=_TRADE_DATE,
    )

    assert result.frame.iloc[0]["security_id"] == "nse:isin:INE000A01001"
    assert result.frame.iloc[0]["symbol"] == "ALPHA"


def test_unresolved_identity_fails_closed() -> None:
    adapter = CanonicalReplayFrameAdapter(
        _identities(),
        CorporateActionTimeline(()),
    )

    with pytest.raises(ValueError, match="unresolved security identities: UNKNOWN"):
        adapter.canonicalize(
            _frame("UNKNOWN"),
            trade_date=_TRADE_DATE,
            as_of=_TRADE_DATE,
        )


def test_unknown_source_stable_id_fails_closed() -> None:
    frame = _frame()
    frame["security_id"] = "nse:isin:INE999A01001"
    adapter = CanonicalReplayFrameAdapter(_identities(), CorporateActionTimeline(()))

    with pytest.raises(ValueError, match="unresolved security identities: ALPHA"):
        adapter.canonicalize(
            frame,
            trade_date=_TRADE_DATE,
            as_of=_TRADE_DATE,
        )


def test_unresolved_material_action_fails_closed() -> None:
    adapter = CanonicalReplayFrameAdapter(
        _identities(),
        CorporateActionTimeline((_split(CorporateActionStatus.UNRESOLVED),)),
    )

    with pytest.raises(ValueError, match="quarantined unresolved actions"):
        adapter.canonicalize(
            _frame(),
            trade_date=_TRADE_DATE,
            as_of=_AS_OF,
        )


def test_market_frame_trade_date_must_match_requested_date() -> None:
    adapter = CanonicalReplayFrameAdapter(
        _identities(),
        CorporateActionTimeline(()),
    )

    with pytest.raises(ValueError, match="trade dates do not match"):
        adapter.canonicalize(
            _frame(),
            trade_date=date(2025, 1, 11),
            as_of=date(2025, 1, 11),
        )
