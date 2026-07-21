"""Deterministic hashing and reconstruction for replay consumer frames."""

from __future__ import annotations

import ast
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import cast

import pandas as pd

from .canonical_replay import CanonicalReplayBar, CanonicalReplayStatus

HASH_COLUMN = "canonical_frame_sha256"


def stamp_canonical_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy stamped with its deterministic consumer-frame digest."""

    result = frame.copy()
    result[HASH_COLUMN] = canonical_frame_sha256(result)
    return result


def canonical_frame_sha256(frame: pd.DataFrame) -> str:
    """Hash the exact consumer frame independently of row order."""

    payload_frame = frame.drop(columns=[HASH_COLUMN], errors="ignore")
    records = cast(list[dict[str, object]], payload_frame.to_dict("records"))
    normalized = [_normalized_record(record) for record in records]
    normalized.sort(
        key=lambda row: (
            str(row.get("trade_date", "")),
            str(row.get("security_id", "")),
            str(row.get("raw_symbol", "")),
        )
    )
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def canonical_bars_from_frame(
    frame: pd.DataFrame,
    *,
    trade_date: date,
    as_of: date,
) -> tuple[CanonicalReplayBar, ...]:
    """Reconstruct exact replay bars for snapshot integrity verification."""

    records = cast(list[dict[str, object]], frame.to_dict("records"))
    bars = tuple(
        _bar_from_record(row, trade_date=trade_date, as_of=as_of) for row in records
    )
    return tuple(
        sorted(
            bars,
            key=lambda item: (
                item.trading_date,
                item.security_id,
                item.raw_symbol,
            ),
        )
    )


def event_ids(value: object, label: str) -> tuple[str, ...]:
    """Decode in-memory, JSON, or CSV event lineage into a stable tuple."""

    if value is None:
        return ()
    if isinstance(value, float) and math.isnan(value):
        return ()
    if isinstance(value, (tuple, list)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        text = value.strip()
        if not text or text in {"[]", "()"}:
            return ()
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            try:
                decoded = ast.literal_eval(text)
            except (SyntaxError, ValueError) as error:
                raise ValueError(f"invalid {label} encoding") from error
        if not isinstance(decoded, (tuple, list)):
            raise ValueError(f"invalid {label} encoding")
        return tuple(str(item).strip() for item in decoded if str(item).strip())
    raise ValueError(f"invalid {label} encoding")


def decimal_value(value: object, label: str) -> Decimal:
    """Return one finite Decimal or fail closed."""

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(
            f"invalid canonical replay numeric value for {label}"
        ) from error
    if not result.is_finite():
        raise ValueError(f"invalid canonical replay numeric value for {label}")
    return result


def _bar_from_record(
    row: Mapping[str, object],
    *,
    trade_date: date,
    as_of: date,
) -> CanonicalReplayBar:
    return CanonicalReplayBar(
        security_id=str(row["security_id"]),
        raw_symbol=str(row["raw_symbol"]),
        canonical_symbol=str(row["canonical_symbol"]),
        trading_date=trade_date,
        as_of=as_of,
        raw_open=decimal_value(row["raw_open"], "raw_open"),
        raw_high=decimal_value(row["raw_high"], "raw_high"),
        raw_low=decimal_value(row["raw_low"], "raw_low"),
        raw_close=decimal_value(row["raw_close"], "raw_close"),
        raw_volume=decimal_value(row["raw_volume"], "raw_volume"),
        adjusted_open=decimal_value(row["adjusted_open"], "adjusted_open"),
        adjusted_high=decimal_value(row["adjusted_high"], "adjusted_high"),
        adjusted_low=decimal_value(row["adjusted_low"], "adjusted_low"),
        adjusted_close=decimal_value(row["adjusted_close"], "adjusted_close"),
        adjusted_volume=decimal_value(row["adjusted_volume"], "adjusted_volume"),
        cumulative_price_factor=decimal_value(
            row["cumulative_price_factor"],
            "cumulative_price_factor",
        ),
        cumulative_volume_factor=decimal_value(
            row["cumulative_volume_factor"],
            "cumulative_volume_factor",
        ),
        applied_event_ids=event_ids(row["applied_event_ids"], "applied_event_ids"),
        unresolved_event_ids=event_ids(
            row["unresolved_event_ids"],
            "unresolved_event_ids",
        ),
        status=CanonicalReplayStatus(str(row["replay_status"])),
        recovery_version=str(row["recovery_version"]),
    )


def _normalized_record(record: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _normalized_value(value) for key, value in record.items()}


def _normalized_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, CanonicalReplayStatus):
        return value.value
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, tuple):
        return [_normalized_value(item) for item in value]
    if isinstance(value, list):
        return [_normalized_value(item) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _normalized_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical replay frame contains non-finite values")
        return format(value, ".17g")
    if isinstance(value, (str, int, bool)):
        return value
    return str(value)
