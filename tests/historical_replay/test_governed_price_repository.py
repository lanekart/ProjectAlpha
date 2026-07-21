"""Tests for the governed historical research price repository boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from alpha.historical_replay.governed_price_repository import (
    CanonicalReplayPriceRepository,
    CanonicalReplayReadOperation,
)
from alpha.recovery.corporate_actions import (
    CorporateActionEvent,
    CorporateActionStatus,
    CorporateActionTimeline,
    CorporateActionType,
)
from alpha.recovery.security_timeline import (
    SecurityIdentityRecord,
    SecurityIdentityTimeline,
)

_BEFORE_SPLIT = date(2025, 1, 10)
_SPLIT_DATE = date(2025, 1, 15)
_AFTER_SPLIT = date(2025, 1, 16)


@dataclass(slots=True)
class FakePriceSource:
    frame: pd.DataFrame
    last_requested_symbols: tuple[str, ...] = ()
    closed: bool = False

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        return self._range(start=trade_date, end=trade_date, symbols=())

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        self.last_requested_symbols = symbols
        result = self._range(start=date.min, end=end_date, symbols=symbols)
        if result.empty:
            return result
        return (
            result.sort_values(["symbol", "trade_date"], kind="stable")
            .groupby("symbol", group_keys=False, sort=True)
            .tail(limit)
            .reset_index(drop=True)
        )

    def find_range_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        self.last_requested_symbols = symbols
        return self._range(start=start_date, end=end_date, symbols=symbols)

    def find_trade_dates(self, *, start: date, end: date) -> tuple[date, ...]:
        result = self._range(start=start, end=end, symbols=())
        if result.empty:
            return ()
        return tuple(sorted(set(result["trade_date"])))

    def close(self) -> None:
        self.closed = True

    def _range(
        self,
        *,
        start: date,
        end: date,
        symbols: tuple[str, ...],
    ) -> pd.DataFrame:
        result = self.frame.copy()
        result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.date
        mask = (result["trade_date"] >= start) & (result["trade_date"] <= end)
        if symbols:
            mask &= result["symbol"].str.upper().isin(symbols)
        return result.loc[mask].reset_index(drop=True)


def _identity_timeline() -> SecurityIdentityTimeline:
    return SecurityIdentityTimeline(
        (
            SecurityIdentityRecord(
                security_id="SEC-1",
                symbol="NEWALPHA",
                exchange="NSE",
                historical_symbols=("ALPHA",),
            ),
        )
    )


def _split(
    status: CorporateActionStatus = CorporateActionStatus.RESOLVED,
) -> CorporateActionEvent:
    resolved = status is CorporateActionStatus.RESOLVED
    return CorporateActionEvent(
        event_id="SEC-1:SPLIT:2025-01-15",
        security_id="SEC-1",
        symbol="NEWALPHA",
        action_type=CorporateActionType.SPLIT,
        effective_date=_SPLIT_DATE,
        announced_at=date(2025, 1, 12),
        price_factor=Decimal("0.5") if resolved else None,
        volume_factor=Decimal("2") if resolved else None,
        old_symbol=None,
        new_symbol=None,
        cash_amount=None,
        ratio_numerator=Decimal("2"),
        ratio_denominator=Decimal("1"),
        status=status,
        confidence=Decimal("0.99"),
        evidence_ids=("corporate_action:0",),
        source="test",
    )


def _row(
    symbol: str,
    trade_date: date,
    *,
    close: int,
    volume: int = 1000,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "open": close - 10,
        "high": close + 10,
        "low": close - 20,
        "close": close,
        "volume": volume,
        "exchange": "NSE",
    }


def _repository(
    rows: list[dict[str, object]],
    *,
    actions: tuple[CorporateActionEvent, ...] = (),
) -> tuple[CanonicalReplayPriceRepository, FakePriceSource]:
    source = FakePriceSource(pd.DataFrame(rows))
    repository = CanonicalReplayPriceRepository(
        source,
        _identity_timeline(),
        CorporateActionTimeline(actions),
    )
    return repository, source


def test_trade_date_read_has_no_corporate_action_lookahead() -> None:
    repository, _ = _repository(
        [_row("ALPHA", _BEFORE_SPLIT, close=100)],
        actions=(_split(),),
    )

    frame = repository.find_by_trade_date(_BEFORE_SPLIT)

    row = frame.iloc[0]
    assert row["raw_symbol"] == "ALPHA"
    assert row["symbol"] == "NEWALPHA"
    assert row["close"] == 100.0
    assert row["applied_event_ids"] == ()
    assert row["replay_as_of"] == _BEFORE_SPLIT.isoformat()
    assert repository.reads[0].operation is CanonicalReplayReadOperation.TRADE_DATE
    assert repository.reads[0].canonical_replay_enforced


def test_history_applies_actions_known_by_history_end() -> None:
    repository, source = _repository(
        [_row("ALPHA", _BEFORE_SPLIT, close=100)],
        actions=(_split(),),
    )

    frame = repository.find_history_by_symbols(
        symbols=("NEWALPHA",),
        end_date=_SPLIT_DATE,
        limit=10,
    )

    assert source.last_requested_symbols == ("ALPHA", "NEWALPHA")
    assert frame.iloc[0]["close"] == 50.0
    assert frame.iloc[0]["volume"] == 2000.0
    assert frame.iloc[0]["applied_event_ids"] == ("SEC-1:SPLIT:2025-01-15",)
    proof = repository.reads[0]
    assert proof.operation is CanonicalReplayReadOperation.HISTORY
    assert proof.requested_symbols == ("NEWALPHA",)
    assert proof.source_symbols == ("ALPHA", "NEWALPHA")
    assert len(proof.read_sha256) == 64


def test_range_read_is_deterministic_across_action_boundary() -> None:
    rows = [
        _row("NEWALPHA", _AFTER_SPLIT, close=60, volume=2000),
        _row("ALPHA", _BEFORE_SPLIT, close=100),
    ]
    repository, _ = _repository(rows, actions=(_split(),))

    first = repository.find_range_by_symbols(
        symbols=("NEWALPHA",),
        start_date=_BEFORE_SPLIT,
        end_date=_AFTER_SPLIT,
    )
    first_proof = repository.reads[-1]
    second = repository.find_range_by_symbols(
        symbols=("NEWALPHA",),
        start_date=_BEFORE_SPLIT,
        end_date=_AFTER_SPLIT,
    )
    second_proof = repository.reads[-1]

    assert list(first["trade_date"]) == [_BEFORE_SPLIT, _AFTER_SPLIT]
    assert list(first["close"]) == [50.0, 60.0]
    assert first.equals(second)
    assert first_proof == second_proof
    assert first_proof.read_sha256 == second_proof.read_sha256
    assert len(first_proof.consumer_attestation_sha256s) == 2


def test_history_limit_is_enforced_by_stable_security_identity() -> None:
    first = date(2025, 1, 1)
    second = date(2025, 1, 2)
    third = date(2025, 1, 3)
    repository, _ = _repository(
        [
            _row("ALPHA", first, close=90),
            _row("ALPHA", second, close=100),
            _row("NEWALPHA", third, close=110),
        ]
    )

    frame = repository.find_history_by_symbols(
        symbols=("NEWALPHA",),
        end_date=third,
        limit=2,
    )

    assert list(frame["trade_date"]) == [second, third]
    assert list(frame["symbol"]) == ["NEWALPHA", "NEWALPHA"]
    assert repository.reads[0].row_count == 2


def test_unresolved_material_action_fails_closed() -> None:
    repository, _ = _repository(
        [_row("ALPHA", _BEFORE_SPLIT, close=100)],
        actions=(_split(CorporateActionStatus.UNRESOLVED),),
    )

    with pytest.raises(ValueError, match="quarantined unresolved actions"):
        repository.find_range_by_symbols(
            symbols=("NEWALPHA",),
            start_date=_BEFORE_SPLIT,
            end_date=_SPLIT_DATE,
        )


def test_duplicate_stable_identity_for_one_date_fails_closed() -> None:
    repository, _ = _repository(
        [
            _row("ALPHA", _BEFORE_SPLIT, close=100),
            _row("NEWALPHA", _BEFORE_SPLIT, close=100),
        ]
    )

    with pytest.raises(ValueError, match="duplicate stable security identities"):
        repository.find_by_trade_date(_BEFORE_SPLIT)


def test_unknown_requested_symbol_and_precanonicalized_source_are_rejected() -> None:
    repository, source = _repository([_row("ALPHA", _BEFORE_SPLIT, close=100)])

    with pytest.raises(ValueError, match="unresolved requested security identity"):
        repository.find_history_by_symbols(
            symbols=("UNKNOWN",),
            end_date=_BEFORE_SPLIT,
            limit=10,
        )

    source.frame["canonical_replay_enforced"] = True
    with pytest.raises(ValueError, match="requires raw source frames"):
        repository.find_by_trade_date(_BEFORE_SPLIT)


def test_trade_dates_and_close_delegate_are_deterministic() -> None:
    repository, source = _repository(
        [
            _row("ALPHA", _BEFORE_SPLIT, close=100),
            _row("NEWALPHA", _AFTER_SPLIT, close=60),
        ]
    )

    dates = repository.find_trade_dates(start=_BEFORE_SPLIT, end=_AFTER_SPLIT)
    repository.close()

    assert dates == (_BEFORE_SPLIT, _AFTER_SPLIT)
    assert source.closed
