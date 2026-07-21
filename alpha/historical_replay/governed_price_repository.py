"""Governed canonical replay boundary for historical research repositories."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol, cast

import pandas as pd

from alpha.recovery.consumer_attestation import CanonicalReplayConsumerAttestation
from alpha.recovery.corporate_actions import CorporateActionTimeline
from alpha.recovery.replay_frame import CanonicalReplayFrameAdapter
from alpha.recovery.security_timeline import SecurityIdentityTimeline

REPOSITORY_CONTRACT_VERSION = "HTR-005-repository-v1.0.0"
_TEMP_SECURITY_ID = "__canonical_security_id"
_GOVERNANCE_COLUMNS = {
    "canonical_frame_sha256",
    "canonical_replay_enforced",
    "canonical_snapshot_sha256",
    "replay_contract_version",
}


class CanonicalReplayReadOperation(StrEnum):
    """Governed repository read operations exposed to historical research."""

    TRADE_DATE = "TRADE_DATE"
    HISTORY = "HISTORY"
    RANGE = "RANGE"


class ReplayPriceSource(Protocol):
    """Raw historical price source required by the governed decorator."""

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        """Return raw prices for one trading date."""
        ...

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        """Return raw history ending on the supplied date."""
        ...

    def find_range_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Return raw prices for one inclusive date range."""
        ...

    def find_trade_dates(self, *, start: date, end: date) -> tuple[date, ...]:
        """Return available source trading dates."""
        ...


@dataclass(frozen=True, slots=True)
class CanonicalReplayRepositoryRead:
    """Immutable proof for one governed historical repository read."""

    operation: CanonicalReplayReadOperation
    requested_symbols: tuple[str, ...]
    source_symbols: tuple[str, ...]
    start_date: date
    end_date: date
    as_of: date
    trade_dates: tuple[date, ...]
    row_count: int
    security_ids: tuple[str, ...]
    canonical_symbols: tuple[str, ...]
    snapshot_sha256s: tuple[str, ...]
    frame_sha256s: tuple[str, ...]
    consumer_attestation_sha256s: tuple[str, ...]
    contract_version: str = REPOSITORY_CONTRACT_VERSION
    canonical_replay_enforced: bool = True

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("repository read end cannot precede start")
        if self.as_of < self.end_date:
            raise ValueError("repository read as_of cannot precede end")
        if self.row_count < 0:
            raise ValueError("repository read row_count cannot be negative")
        if self.trade_dates != tuple(sorted(set(self.trade_dates))):
            raise ValueError("repository read trade dates must be sorted and unique")
        if any(
            item < self.start_date or item > self.end_date for item in self.trade_dates
        ):
            raise ValueError("repository read trade date falls outside requested range")
        if self.row_count == 0 and self.trade_dates:
            raise ValueError("empty repository reads cannot contain trade dates")
        if self.row_count > 0 and not self.trade_dates:
            raise ValueError("non-empty repository reads require trade dates")
        digest_count = len(self.trade_dates)
        if len(self.snapshot_sha256s) != digest_count:
            raise ValueError("snapshot digest count must match trade dates")
        if len(self.frame_sha256s) != digest_count:
            raise ValueError("frame digest count must match trade dates")
        if len(self.consumer_attestation_sha256s) != digest_count:
            raise ValueError("consumer attestation count must match trade dates")
        if self.contract_version != REPOSITORY_CONTRACT_VERSION:
            raise ValueError("unsupported canonical replay repository contract")
        if not self.canonical_replay_enforced:
            raise ValueError("canonical replay repository read must be enforced")

    @property
    def read_sha256(self) -> str:
        """Return a deterministic digest over the repository read proof."""

        payload = self.as_dict(include_digest=False)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def as_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        """Return a stable JSON-compatible representation."""

        payload = asdict(self)
        payload["operation"] = self.operation.value
        for key in ("start_date", "end_date", "as_of"):
            payload[key] = str(payload[key])
        payload["trade_dates"] = [item.isoformat() for item in self.trade_dates]
        for key in (
            "requested_symbols",
            "source_symbols",
            "security_ids",
            "canonical_symbols",
            "snapshot_sha256s",
            "frame_sha256s",
            "consumer_attestation_sha256s",
        ):
            payload[key] = list(cast(tuple[str, ...], getattr(self, key)))
        if include_digest:
            payload["read_sha256"] = self.read_sha256
        return payload


class CanonicalReplayPriceRepository:
    """Canonicalize and attest every historical price repository read."""

    canonical_replay_enforced = True
    contract_version = REPOSITORY_CONTRACT_VERSION

    def __init__(
        self,
        source: ReplayPriceSource,
        identities: SecurityIdentityTimeline,
        actions: CorporateActionTimeline,
    ) -> None:
        self._source = source
        self._identities = identities
        self._canonicalizer = CanonicalReplayFrameAdapter(identities, actions)
        self._reads: list[CanonicalReplayRepositoryRead] = []
        self._consumer_attestations: list[CanonicalReplayConsumerAttestation] = []

    @property
    def reads(self) -> tuple[CanonicalReplayRepositoryRead, ...]:
        """Return immutable repository read proofs in execution order."""

        return tuple(self._reads)

    @property
    def consumer_attestations(self) -> tuple[CanonicalReplayConsumerAttestation, ...]:
        """Return immutable per-session consumer attestations."""

        return tuple(self._consumer_attestations)

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        """Return one canonical point-in-time market frame."""

        frame = self._source.find_by_trade_date(trade_date)
        return self._release(
            frame,
            operation=CanonicalReplayReadOperation.TRADE_DATE,
            requested_symbols=(),
            source_symbols=(),
            start_date=trade_date,
            end_date=trade_date,
            as_of=trade_date,
        )

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        """Return canonical history limited by stable security identity."""

        if limit <= 0:
            raise ValueError("history limit must be positive")
        requested = _normalized_symbols(symbols)
        source_symbols = _source_symbols(self._identities, requested)
        frame = self._source.find_history_by_symbols(
            symbols=source_symbols,
            end_date=end_date,
            limit=limit,
        )
        frame = _limit_by_security_identity(
            frame,
            identities=self._identities,
            limit=limit,
        )
        start_date = _minimum_trade_date(frame, fallback=end_date)
        return self._release(
            frame,
            operation=CanonicalReplayReadOperation.HISTORY,
            requested_symbols=requested,
            source_symbols=source_symbols,
            start_date=start_date,
            end_date=end_date,
            as_of=end_date,
        )

    def find_range_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Return canonical history for one inclusive range."""

        if end_date < start_date:
            raise ValueError("range end cannot precede start")
        requested = _normalized_symbols(symbols)
        source_symbols = _source_symbols(self._identities, requested)
        frame = self._source.find_range_by_symbols(
            symbols=source_symbols,
            start_date=start_date,
            end_date=end_date,
        )
        return self._release(
            frame,
            operation=CanonicalReplayReadOperation.RANGE,
            requested_symbols=requested,
            source_symbols=source_symbols,
            start_date=start_date,
            end_date=end_date,
            as_of=end_date,
        )

    def find_trade_dates(self, *, start: date, end: date) -> tuple[date, ...]:
        """Return deterministic source trading dates inside the requested range."""

        if end < start:
            raise ValueError("trade-date range end cannot precede start")
        dates = tuple(sorted(set(self._source.find_trade_dates(start=start, end=end))))
        if any(item < start or item > end for item in dates):
            raise ValueError("source returned a trade date outside the requested range")
        return dates

    def close(self) -> None:
        """Close the wrapped source when it exposes a close method."""

        close = getattr(self._source, "close", None)
        if callable(close):
            cast(Callable[[], None], close)()

    def _release(
        self,
        frame: pd.DataFrame,
        *,
        operation: CanonicalReplayReadOperation,
        requested_symbols: tuple[str, ...],
        source_symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
        as_of: date,
    ) -> pd.DataFrame:
        raw = frame.copy()
        if raw.empty:
            self._reads.append(
                _read_proof(
                    operation=operation,
                    requested_symbols=requested_symbols,
                    source_symbols=source_symbols,
                    start_date=start_date,
                    end_date=end_date,
                    as_of=as_of,
                    frame=raw,
                    attestations=(),
                )
            )
            return raw
        _reject_precanonicalized_source(raw)
        raw = _normalized_trade_dates(raw)
        actual_dates = tuple(sorted(set(cast(list[date], raw["trade_date"].tolist()))))
        if any(item < start_date or item > end_date for item in actual_dates):
            raise ValueError(
                "source frame contains trade dates outside the requested range"
            )
        if any(item > as_of for item in actual_dates):
            raise ValueError("source frame contains observations after replay as_of")
        _reject_duplicate_stable_identities(raw, self._identities)

        released: list[pd.DataFrame] = []
        attestations: list[CanonicalReplayConsumerAttestation] = []
        for trade_date in actual_dates:
            group = raw.loc[raw["trade_date"] == trade_date].copy()
            result = self._canonicalizer.canonicalize(
                group,
                trade_date=trade_date,
                as_of=as_of,
            )
            released.append(result.frame)
            attestations.append(result.attestation)

        output = pd.concat(released, ignore_index=True)
        output = output.sort_values(
            ["trade_date", "security_id", "symbol", "raw_symbol"],
            kind="stable",
        ).reset_index(drop=True)
        proof = _read_proof(
            operation=operation,
            requested_symbols=requested_symbols,
            source_symbols=source_symbols,
            start_date=start_date,
            end_date=end_date,
            as_of=as_of,
            frame=output,
            attestations=tuple(attestations),
        )
        self._reads.append(proof)
        self._consumer_attestations.extend(attestations)
        return output


def _read_proof(
    *,
    operation: CanonicalReplayReadOperation,
    requested_symbols: tuple[str, ...],
    source_symbols: tuple[str, ...],
    start_date: date,
    end_date: date,
    as_of: date,
    frame: pd.DataFrame,
    attestations: tuple[CanonicalReplayConsumerAttestation, ...],
) -> CanonicalReplayRepositoryRead:
    security_ids = _column_values(frame, "security_id")
    canonical_symbols = _column_values(frame, "canonical_symbol")
    return CanonicalReplayRepositoryRead(
        operation=operation,
        requested_symbols=requested_symbols,
        source_symbols=source_symbols,
        start_date=start_date,
        end_date=end_date,
        as_of=as_of,
        trade_dates=tuple(item.trade_date for item in attestations),
        row_count=len(frame),
        security_ids=security_ids,
        canonical_symbols=canonical_symbols,
        snapshot_sha256s=tuple(item.canonical_snapshot_sha256 for item in attestations),
        frame_sha256s=tuple(item.canonical_frame_sha256 for item in attestations),
        consumer_attestation_sha256s=tuple(
            item.attestation_sha256 for item in attestations
        ),
    )


def _column_values(frame: pd.DataFrame, column: str) -> tuple[str, ...]:
    if column not in frame.columns:
        return ()
    return tuple(
        sorted({str(item).strip() for item in frame[column] if str(item).strip()})
    )


def _normalized_symbols(symbols: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({item.strip().upper() for item in symbols if item.strip()}))


def _source_symbols(
    identities: SecurityIdentityTimeline,
    requested: tuple[str, ...],
) -> tuple[str, ...]:
    if not requested:
        return ()
    aliases: set[str] = set()
    for symbol in requested:
        records = tuple(
            record for record in identities.records if record.supports_symbol(symbol)
        )
        security_ids = {record.security_id for record in records}
        if not records:
            raise ValueError(f"unresolved requested security identity: {symbol}")
        if len(security_ids) > 1:
            rendered = ", ".join(sorted(security_ids))
            raise ValueError(
                f"ambiguous requested security continuity for {symbol}: {rendered}"
            )
        for record in records:
            aliases.add(record.symbol)
            aliases.update(record.historical_symbols)
    return tuple(sorted(aliases))


def _normalized_trade_dates(frame: pd.DataFrame) -> pd.DataFrame:
    if "trade_date" not in frame.columns:
        raise ValueError("governed replay source frame is missing trade_date")
    result = frame.copy()
    parsed = pd.to_datetime(result["trade_date"], errors="coerce")
    if parsed.isna().any():
        raise ValueError("governed replay source frame contains invalid trade_date")
    result["trade_date"] = parsed.dt.date
    return result


def _minimum_trade_date(frame: pd.DataFrame, *, fallback: date) -> date:
    if frame.empty:
        return fallback
    normalized = _normalized_trade_dates(frame)
    return min(cast(list[date], normalized["trade_date"].tolist()))


def _limit_by_security_identity(
    frame: pd.DataFrame,
    *,
    identities: SecurityIdentityTimeline,
    limit: int,
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    result = _normalized_trade_dates(frame)
    records = cast(list[dict[str, object]], result.to_dict("records"))
    security_ids: list[str] = []
    for row in records:
        identity = identities.resolve(
            str(row.get("symbol", "")),
            trading_date=cast(date, row["trade_date"]),
            exchange=_optional_exchange(row.get("exchange")),
        )
        if identity is None:
            raise ValueError(
                "unresolved security identity while limiting canonical history: "
                f"{str(row.get('symbol', '')).strip().upper() or '<EMPTY>'}"
            )
        security_ids.append(identity.security_id)
    result[_TEMP_SECURITY_ID] = security_ids
    result = result.sort_values(
        [_TEMP_SECURITY_ID, "trade_date", "symbol"],
        kind="stable",
    )
    limited = (
        result.groupby(_TEMP_SECURITY_ID, group_keys=False, sort=True)
        .tail(limit)
        .drop(columns=[_TEMP_SECURITY_ID])
    )
    return limited.reset_index(drop=True)


def _reject_duplicate_stable_identities(
    frame: pd.DataFrame,
    identities: SecurityIdentityTimeline,
) -> None:
    records = cast(list[dict[str, object]], frame.to_dict("records"))
    seen: set[tuple[str, date]] = set()
    duplicates: set[tuple[str, date]] = set()
    for row in records:
        trade_date = cast(date, row["trade_date"])
        identity = identities.resolve(
            str(row.get("symbol", "")),
            trading_date=trade_date,
            exchange=_optional_exchange(row.get("exchange")),
        )
        if identity is None:
            continue
        key = identity.security_id, trade_date
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    if duplicates:
        rendered = ", ".join(
            f"{security_id}@{trade_date.isoformat()}"
            for security_id, trade_date in sorted(duplicates)
        )
        raise ValueError(
            f"duplicate stable security identities in source frame: {rendered}"
        )


def _reject_precanonicalized_source(frame: pd.DataFrame) -> None:
    present = tuple(sorted(_GOVERNANCE_COLUMNS.intersection(frame.columns)))
    if present:
        rendered = ", ".join(present)
        raise ValueError(
            "governed replay repository requires raw source frames; "
            f"found canonical columns: {rendered}"
        )


def _optional_exchange(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


__all__ = [
    "CanonicalReplayPriceRepository",
    "CanonicalReplayReadOperation",
    "CanonicalReplayRepositoryRead",
    "REPOSITORY_CONTRACT_VERSION",
    "ReplayPriceSource",
]
