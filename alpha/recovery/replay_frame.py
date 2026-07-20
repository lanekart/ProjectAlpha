"""Pandas bridge from recovered market frames to canonical replay truth."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, cast

import pandas as pd

from .canonical_replay import (
    CanonicalReplayAudit,
    CanonicalReplayBar,
    CanonicalReplayBuilder,
    CanonicalReplayStatus,
)
from .corporate_actions import CorporateActionBar, CorporateActionTimeline
from .security_timeline import SecurityIdentityTimeline

_REQUIRED_COLUMNS = {"symbol", "open", "high", "low", "close", "volume"}


@dataclass(frozen=True, slots=True)
class CanonicalReplayFrameResult:
    """Consumer-compatible DataFrame plus exact governed replay lineage."""

    frame: pd.DataFrame
    bars: tuple[CanonicalReplayBar, ...]
    audit: CanonicalReplayAudit


class CanonicalReplayFrameAdapter:
    """Resolve identity and corporate actions before downstream consumption."""

    def __init__(
        self,
        identities: SecurityIdentityTimeline,
        actions: CorporateActionTimeline,
        *,
        fail_on_quarantine: bool = True,
    ) -> None:
        self._identities = identities
        self._builder = CanonicalReplayBuilder(actions)
        self._fail_on_quarantine = fail_on_quarantine

    def canonicalize(
        self,
        frame: pd.DataFrame,
        *,
        trade_date: date,
        as_of: date,
    ) -> CanonicalReplayFrameResult:
        """Return a deterministic adjusted frame or fail closed."""

        if trade_date > as_of:
            raise ValueError("trade_date cannot be after canonical replay as_of")
        missing = _REQUIRED_COLUMNS.difference(frame.columns)
        if missing:
            rendered = ", ".join(sorted(missing))
            raise ValueError(f"market frame missing canonical columns: {rendered}")
        if frame.empty:
            raise ValueError("cannot canonicalize an empty market frame")
        _validate_trade_dates(frame, trade_date)

        records = cast(list[dict[str, Any]], frame.to_dict("records"))
        inputs: list[CorporateActionBar] = []
        source_by_key: dict[tuple[str, date, str], dict[str, Any]] = {}
        canonical_symbol_by_key: dict[tuple[str, date, str], str] = {}
        unresolved_symbols: set[str] = set()

        for record in records:
            raw_symbol = str(record["symbol"]).strip().upper()
            exchange = _optional_exchange(record.get("exchange"))
            identity = self._identities.resolve(
                raw_symbol,
                trading_date=trade_date,
                exchange=exchange,
            )
            if identity is None:
                unresolved_symbols.add(raw_symbol or "<EMPTY>")
                continue
            bar = CorporateActionBar(
                security_id=identity.security_id,
                symbol=raw_symbol,
                trading_date=trade_date,
                open=_decimal(record, "open"),
                high=_decimal(record, "high"),
                low=_decimal(record, "low"),
                close=_decimal(record, "close"),
                volume=_decimal(record, "volume"),
            )
            key = bar.security_id, bar.trading_date, bar.symbol
            if key in source_by_key:
                raise ValueError(f"duplicate market frame identity: {key!r}")
            inputs.append(bar)
            source_by_key[key] = record
            canonical_symbol_by_key[key] = identity.symbol

        if unresolved_symbols:
            rendered = ", ".join(sorted(unresolved_symbols))
            raise ValueError(f"unresolved security identities: {rendered}")

        ordered_inputs = sorted(
            inputs,
            key=lambda item: (item.trading_date, item.security_id, item.symbol),
        )
        bars = tuple(
            self._builder.build_bar(
                bar,
                as_of=as_of,
                canonical_symbol=canonical_symbol_by_key[
                    (bar.security_id, bar.trading_date, bar.symbol)
                ],
            )
            for bar in ordered_inputs
        )
        audit = self._builder.audit_bars(bars)
        if self._fail_on_quarantine and not audit.passed:
            events = ", ".join(audit.unresolved_event_ids)
            raise ValueError(
                f"canonical replay quarantined unresolved actions: {events}"
            )

        output_rows = [
            _consumer_row(
                source_by_key[(bar.security_id, bar.trading_date, bar.raw_symbol)],
                bar,
                audit.snapshot_sha256,
            )
            for bar in bars
            if bar.status is CanonicalReplayStatus.READY
        ]
        output = pd.DataFrame(output_rows)
        return CanonicalReplayFrameResult(frame=output, bars=bars, audit=audit)


def _validate_trade_dates(frame: pd.DataFrame, expected: date) -> None:
    if "trade_date" not in frame.columns:
        return
    parsed = pd.to_datetime(frame["trade_date"], errors="coerce")
    if parsed.isna().any():
        raise ValueError("market frame contains invalid trade_date values")
    actual = {item.date() for item in parsed}
    if actual != {expected}:
        rendered = ", ".join(sorted(item.isoformat() for item in actual))
        raise ValueError(
            f"market frame trade dates do not match {expected.isoformat()}: {rendered}"
        )


def _consumer_row(
    source: Mapping[str, object],
    bar: CanonicalReplayBar,
    snapshot_sha256: str,
) -> dict[str, object]:
    row = dict(source)
    row.update(
        {
            "security_id": bar.security_id,
            "raw_symbol": bar.raw_symbol,
            "canonical_symbol": bar.canonical_symbol,
            "raw_open": source["open"],
            "raw_high": source["high"],
            "raw_low": source["low"],
            "raw_close": source["close"],
            "raw_volume": source["volume"],
            "symbol": bar.canonical_symbol,
            "open": float(bar.adjusted_open),
            "high": float(bar.adjusted_high),
            "low": float(bar.adjusted_low),
            "close": float(bar.adjusted_close),
            "volume": float(bar.adjusted_volume),
            "cumulative_price_factor": float(bar.cumulative_price_factor),
            "cumulative_volume_factor": float(bar.cumulative_volume_factor),
            "applied_event_ids": bar.applied_event_ids,
            "unresolved_event_ids": bar.unresolved_event_ids,
            "replay_status": bar.status.value,
            "recovery_version": bar.recovery_version,
            "canonical_snapshot_sha256": snapshot_sha256,
        }
    )
    return row


def _optional_exchange(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def _decimal(record: Mapping[str, object], key: str) -> Decimal:
    value = record.get(key)
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"invalid {key} value: {value!r}") from error
    if not result.is_finite():
        raise ValueError(f"invalid {key} value: {value!r}")
    return result
