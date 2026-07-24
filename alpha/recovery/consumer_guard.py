"""Fail-closed validation for downstream canonical replay consumers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal

import pandas as pd

from .canonical_replay import CanonicalReplayStatus, canonical_replay_sha256
from .consumer_attestation import (
    CONSUMER_CONTRACT_VERSION,
    CanonicalReplayConsumerAttestation,
    validate_sha256,
)
from .consumer_hash import (
    HASH_COLUMN,
    canonical_bars_from_frame,
    canonical_frame_sha256,
    decimal_value,
    event_ids,
)

_REQUIRED_COLUMNS = {
    "security_id",
    "raw_symbol",
    "canonical_symbol",
    "symbol",
    "trade_date",
    "replay_as_of",
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
    "raw_volume",
    "adjusted_open",
    "adjusted_high",
    "adjusted_low",
    "adjusted_close",
    "adjusted_volume",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "cumulative_price_factor",
    "cumulative_volume_factor",
    "applied_event_ids",
    "unresolved_event_ids",
    "replay_status",
    "recovery_version",
    "canonical_snapshot_sha256",
    HASH_COLUMN,
    "canonical_replay_enforced",
    "replay_contract_version",
}


class CanonicalReplayConsumerGuard:
    """Verify the replay contract immediately before consumption."""

    def validate(
        self,
        frame: pd.DataFrame,
        *,
        expected_trade_date: date | None = None,
        expected_as_of: date | None = None,
    ) -> CanonicalReplayConsumerAttestation:
        if frame.empty:
            raise ValueError("canonical replay consumer frame must not be empty")
        missing = _REQUIRED_COLUMNS.difference(frame.columns)
        if missing:
            rendered = ", ".join(sorted(missing))
            raise ValueError(f"canonical replay consumer contract missing: {rendered}")

        trade_date = _single_date(
            _date_values(frame["trade_date"], "trade_date"),
            "trade_date",
        )
        as_of = _single_date(
            _date_values(frame["replay_as_of"], "replay_as_of"),
            "replay_as_of",
        )
        if expected_trade_date is not None and trade_date != expected_trade_date:
            raise ValueError("canonical replay trade_date does not match request")
        if expected_as_of is not None and as_of != expected_as_of:
            raise ValueError("canonical replay as_of does not match request")
        if as_of < trade_date:
            raise ValueError("canonical replay as_of cannot precede trade_date")

        _validate_contract_flags(frame)
        security_ids = _non_empty_strings(frame["security_id"], "security_id")
        raw_symbols = _non_empty_strings(frame["raw_symbol"], "raw_symbol")
        canonical_symbols = _non_empty_strings(
            frame["canonical_symbol"],
            "canonical_symbol",
        )
        if _non_empty_strings(frame["symbol"], "symbol") != canonical_symbols:
            raise ValueError("consumer symbol must equal canonical_symbol")
        if len(set(security_ids)) != len(security_ids):
            raise ValueError("canonical replay frame contains duplicate security_id")
        if len(set(canonical_symbols)) != len(canonical_symbols):
            raise ValueError(
                "canonical replay frame contains duplicate canonical_symbol"
            )
        if len(raw_symbols) != len(security_ids):
            raise ValueError(
                "raw symbol coverage does not match security identity coverage"
            )

        _validate_ready_rows(frame)
        _validate_ohlcv(frame)
        snapshot_sha256 = _single_string(
            frame["canonical_snapshot_sha256"],
            "canonical_snapshot_sha256",
        )
        validate_sha256(snapshot_sha256, "canonical snapshot")
        actual_snapshot_sha256 = canonical_replay_sha256(
            canonical_bars_from_frame(frame, trade_date=trade_date, as_of=as_of)
        )
        if snapshot_sha256 != actual_snapshot_sha256:
            raise ValueError("canonical replay snapshot digest does not match content")

        stated_frame_sha256 = _single_string(frame[HASH_COLUMN], HASH_COLUMN)
        validate_sha256(stated_frame_sha256, "canonical frame")
        actual_frame_sha256 = canonical_frame_sha256(frame)
        if stated_frame_sha256 != actual_frame_sha256:
            raise ValueError("canonical replay frame digest does not match content")

        recovery_versions = tuple(
            sorted(
                set(_non_empty_strings(frame["recovery_version"], "recovery_version"))
            )
        )
        applied_event_ids = tuple(
            sorted(
                {
                    event_id
                    for value in frame["applied_event_ids"]
                    for event_id in event_ids(value, "applied_event_ids")
                }
            )
        )
        return CanonicalReplayConsumerAttestation(
            trade_date=trade_date,
            as_of=as_of,
            row_count=len(frame),
            security_ids=tuple(sorted(security_ids)),
            canonical_symbols=tuple(sorted(canonical_symbols)),
            canonical_snapshot_sha256=snapshot_sha256,
            canonical_frame_sha256=actual_frame_sha256,
            recovery_versions=recovery_versions,
            applied_event_ids=applied_event_ids,
        )


def _validate_contract_flags(frame: pd.DataFrame) -> None:
    statuses = set(_non_empty_strings(frame["replay_status"], "replay_status"))
    if statuses != {CanonicalReplayStatus.READY.value}:
        rendered = ", ".join(sorted(statuses))
        raise ValueError(
            f"canonical replay consumer received non-ready rows: {rendered}"
        )
    enforced = {
        _boolean(value, "canonical_replay_enforced")
        for value in frame["canonical_replay_enforced"]
    }
    if enforced != {True}:
        raise ValueError("canonical replay enforcement flag is absent or false")
    versions = set(
        _non_empty_strings(frame["replay_contract_version"], "replay_contract_version")
    )
    if versions != {CONSUMER_CONTRACT_VERSION}:
        raise ValueError("canonical replay consumer contract version is invalid")


def _validate_ready_rows(frame: pd.DataFrame) -> None:
    for value in frame["unresolved_event_ids"]:
        if event_ids(value, "unresolved_event_ids"):
            raise ValueError("replay-ready consumer frame contains unresolved actions")


def _validate_ohlcv(frame: pd.DataFrame) -> None:
    records = frame.to_dict("records")
    for raw_record in records:
        row = {str(key): value for key, value in raw_record.items()}
        raw = _ohlcv(row, prefix="raw_")
        adjusted = _ohlcv(row, prefix="adjusted_")
        consumed = _ohlcv(row, prefix="")
        if _consumer_projection(adjusted) != consumed:
            raise ValueError(
                "consumer OHLCV does not match exact adjusted OHLCV projection"
            )
        _validate_bar(raw, label="raw")
        _validate_bar(adjusted, label="adjusted")
        if decimal_value(row["cumulative_price_factor"], "price factor") <= 0:
            raise ValueError("cumulative_price_factor must be positive")
        if decimal_value(row["cumulative_volume_factor"], "volume factor") <= 0:
            raise ValueError("cumulative_volume_factor must be positive")


def _consumer_projection(
    values: tuple[Decimal, Decimal, Decimal, Decimal, Decimal],
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """
    Return the exact decimal representation of the downstream float payload.

    Canonical adjusted values remain eight-decimal ``Decimal`` evidence. Consumer
    OHLCV columns are intentionally float-compatible for the unchanged Alpha stack,
    so equality is checked against the deterministic IEEE-754 projection rather
    than against the higher-precision source decimal itself.
    """

    open_price, high, low, close, volume = values
    return (
        decimal_value(float(open_price), "consumer open projection"),
        decimal_value(float(high), "consumer high projection"),
        decimal_value(float(low), "consumer low projection"),
        decimal_value(float(close), "consumer close projection"),
        decimal_value(float(volume), "consumer volume projection"),
    )


def _ohlcv(
    row: Mapping[str, object],
    *,
    prefix: str,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    return (
        decimal_value(row[f"{prefix}open"], f"{prefix}open"),
        decimal_value(row[f"{prefix}high"], f"{prefix}high"),
        decimal_value(row[f"{prefix}low"], f"{prefix}low"),
        decimal_value(row[f"{prefix}close"], f"{prefix}close"),
        decimal_value(row[f"{prefix}volume"], f"{prefix}volume"),
    )


def _validate_bar(
    values: tuple[Decimal, Decimal, Decimal, Decimal, Decimal],
    *,
    label: str,
) -> None:
    open_price, high, low, close, volume = values
    if min(open_price, high, low, close) <= 0:
        raise ValueError(f"{label} OHLC values must be positive")
    if volume < 0:
        raise ValueError(f"{label} volume must be non-negative")
    if high < max(open_price, low, close):
        raise ValueError(f"{label} high violates OHLC invariants")
    if low > min(open_price, high, close):
        raise ValueError(f"{label} low violates OHLC invariants")


def _date_values(series: pd.Series, label: str) -> tuple[date, ...]:
    parsed = pd.to_datetime(series, errors="coerce")
    if parsed.isna().any():
        raise ValueError(f"canonical replay frame contains invalid {label}")
    return tuple(item.date() for item in parsed)


def _single_date(values: Sequence[date], label: str) -> date:
    unique = set(values)
    if len(unique) != 1:
        rendered = ", ".join(sorted(item.isoformat() for item in unique))
        raise ValueError(
            f"canonical replay frame spans multiple {label} values: {rendered}"
        )
    return next(iter(unique))


def _non_empty_strings(series: pd.Series, label: str) -> list[str]:
    values = [str(value).strip() for value in series]
    if any(not value for value in values):
        raise ValueError(f"canonical replay frame contains empty {label}")
    return values


def _single_string(series: pd.Series, label: str) -> str:
    values = set(_non_empty_strings(series, label))
    if len(values) != 1:
        raise ValueError(f"canonical replay frame contains multiple {label} values")
    return next(iter(values))


def _boolean(value: object, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise ValueError(f"invalid canonical replay boolean value for {label}")
