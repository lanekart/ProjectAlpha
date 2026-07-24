"""Regression tests for exact canonical-to-consumer numeric projection."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from alpha.recovery.consumer_guard import CanonicalReplayConsumerGuard
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

_TRADE_DATE = date(2025, 11, 27)
_AS_OF = date(2026, 7, 20)
_EXACT_ADJUSTED_VOLUME = Decimal("1524157875.01905210")


def _adapter() -> CanonicalReplayFrameAdapter:
    identities = SecurityIdentityTimeline(
        (
            SecurityIdentityRecord(
                security_id="nse:isin:INE000A01001",
                symbol="ALPHA",
                exchange="NSE",
                effective_from=date(2020, 1, 1),
            ),
        )
    )
    action = CorporateActionEvent(
        event_id="nse:isin:INE000A01001:SPLIT:2026-01-15",
        security_id="nse:isin:INE000A01001",
        symbol="ALPHA",
        action_type=CorporateActionType.SPLIT,
        effective_date=date(2026, 1, 15),
        announced_at=date(2025, 12, 20),
        price_factor=Decimal("1"),
        volume_factor=Decimal("1.23456789"),
        old_symbol=None,
        new_symbol=None,
        cash_amount=None,
        ratio_numerator=Decimal("1"),
        ratio_denominator=Decimal("1"),
        status=CorporateActionStatus.RESOLVED,
        confidence=Decimal("1"),
        evidence_ids=("official:test",),
        source="test",
    )
    return CanonicalReplayFrameAdapter(
        identities,
        CorporateActionTimeline((action,)),
    )


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "ALPHA",
                "trade_date": _TRADE_DATE,
                "open": 100,
                "high": 110,
                "low": 90,
                "close": 105,
                "volume": 1234567890,
                "exchange": "NSE",
                "security_id": "nse:isin:INE000A01001",
                "isin": "INE000A01001",
            }
        ]
    )


def test_adapter_accepts_exact_float_projection_of_precise_adjustment() -> None:
    result = _adapter().canonicalize(
        _frame(),
        trade_date=_TRADE_DATE,
        as_of=_AS_OF,
    )

    row = result.frame.iloc[0]
    assert row["adjusted_volume"] == str(_EXACT_ADJUSTED_VOLUME)
    assert row["volume"] == float(_EXACT_ADJUSTED_VOLUME)
    assert Decimal(str(row["volume"])) != _EXACT_ADJUSTED_VOLUME
    assert result.attestation.row_count == 1
    assert result.attestation.canonical_frame_sha256 == row["canonical_frame_sha256"]


def test_guard_still_rejects_tampered_float_projection() -> None:
    result = _adapter().canonicalize(
        _frame(),
        trade_date=_TRADE_DATE,
        as_of=_AS_OF,
    )
    tampered = result.frame.copy()
    tampered.loc[0, "volume"] = float(_EXACT_ADJUSTED_VOLUME) + 1

    with pytest.raises(ValueError, match="exact adjusted OHLCV projection"):
        CanonicalReplayConsumerGuard().validate(
            tampered,
            expected_trade_date=_TRADE_DATE,
            expected_as_of=_AS_OF,
        )
