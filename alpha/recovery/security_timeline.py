"""Point-in-time security identity resolution for governed historical replay."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime

from .models import CanonicalPreviewRow, RecoveryResult


@dataclass(frozen=True, slots=True)
class SecurityIdentityRecord:
    """One canonical security identity valid over a governed date interval."""

    security_id: str
    symbol: str
    exchange: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    historical_symbols: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    recovery_version: str = "HTR-002-v1.0.0"

    def __post_init__(self) -> None:
        security_id = self.security_id.strip()
        symbol = self.symbol.strip().upper()
        if not security_id:
            raise ValueError("security_id must not be empty")
        if not symbol:
            raise ValueError("symbol must not be empty")
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("effective_to cannot be before effective_from")
        normalized_history = tuple(
            sorted(
                {
                    item.strip().upper()
                    for item in self.historical_symbols
                    if item.strip() and item.strip().upper() != symbol
                }
            )
        )
        normalized_exchange = (
            self.exchange.strip().upper()
            if self.exchange and self.exchange.strip()
            else None
        )
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "exchange", normalized_exchange)
        object.__setattr__(self, "historical_symbols", normalized_history)
        object.__setattr__(self, "evidence_ids", tuple(sorted(set(self.evidence_ids))))

    def active_on(self, trading_date: date) -> bool:
        """Return whether this identity record is active on the supplied date."""

        if self.effective_from is not None and trading_date < self.effective_from:
            return False
        if self.effective_to is not None and trading_date > self.effective_to:
            return False
        return True

    def supports_symbol(self, symbol: str) -> bool:
        """Return whether the current or recovered historical symbol matches."""

        normalized = symbol.strip().upper()
        return normalized == self.symbol or normalized in self.historical_symbols


class SecurityIdentityTimeline:
    """Resolve symbols or authoritative source IDs without ambiguity."""

    def __init__(self, records: Iterable[SecurityIdentityRecord]) -> None:
        ordered = tuple(
            sorted(
                records,
                key=lambda item: (
                    item.security_id,
                    item.effective_from or date.min,
                    item.effective_to or date.max,
                    item.symbol,
                ),
            )
        )
        by_symbol: dict[str, list[SecurityIdentityRecord]] = defaultdict(list)
        by_security_id: dict[str, list[SecurityIdentityRecord]] = defaultdict(list)
        for record in ordered:
            by_security_id[record.security_id].append(record)
            for symbol in (record.symbol, *record.historical_symbols):
                by_symbol[symbol].append(record)
        self._records = ordered
        self._by_symbol = {
            symbol: tuple(values) for symbol, values in sorted(by_symbol.items())
        }
        self._by_security_id = {
            security_id: tuple(values)
            for security_id, values in sorted(by_security_id.items())
        }

    @property
    def records(self) -> tuple[SecurityIdentityRecord, ...]:
        return self._records

    def resolve(
        self,
        symbol: str,
        *,
        trading_date: date,
        exchange: str | None = None,
    ) -> SecurityIdentityRecord | None:
        normalized_symbol = symbol.strip().upper()
        normalized_exchange = exchange.strip().upper() if exchange else None
        candidates = tuple(
            record
            for record in self._by_symbol.get(normalized_symbol, ())
            if record.active_on(trading_date)
            and _exchange_matches(record, normalized_exchange)
        )
        unique = {record.security_id: record for record in candidates}
        if not unique:
            return None
        if len(unique) > 1:
            identifiers = ", ".join(sorted(unique))
            raise ValueError(
                f"ambiguous security identity for {normalized_symbol}: {identifiers}"
            )
        return next(iter(unique.values()))

    def resolve_source_identity(
        self,
        symbol: str,
        *,
        trading_date: date,
        exchange: str | None = None,
        security_id: str | None = None,
        isin: str | None = None,
    ) -> SecurityIdentityRecord | None:
        """Prefer authoritative source ID, with symbol resolution as fallback."""

        direct_id = normalize_source_security_id(
            security_id=security_id,
            isin=isin,
            exchange=exchange,
        )
        if direct_id is None:
            return self.resolve(
                symbol,
                trading_date=trading_date,
                exchange=exchange,
            )

        normalized_exchange = exchange.strip().upper() if exchange else None
        candidates = tuple(
            record
            for record in self._by_security_id.get(direct_id, ())
            if _exchange_matches(record, normalized_exchange)
        )
        if not candidates:
            return None

        active = tuple(
            record for record in candidates if record.active_on(trading_date)
        )
        normalized_symbol = symbol.strip().upper()
        active_symbol = tuple(
            record for record in active if record.supports_symbol(normalized_symbol)
        )
        if active_symbol:
            return _reference_record(active_symbol, trading_date)
        if active:
            return _reference_record(active, trading_date)

        supported = tuple(
            record for record in candidates if record.supports_symbol(normalized_symbol)
        )
        return _reference_record(supported or candidates, trading_date)

    @classmethod
    def from_recovery_result(cls, result: RecoveryResult) -> SecurityIdentityTimeline:
        """Build a point-in-time identity timeline from HTR-002 output."""

        return cls(_record_from_preview(row) for row in result.canonical_preview)


def normalize_source_security_id(
    *,
    security_id: str | None,
    isin: str | None,
    exchange: str | None,
) -> str | None:
    """Normalize an explicit stable ID or construct one from an exchange ISIN."""

    explicit = str(security_id or "").strip()
    if explicit:
        marker = explicit.lower().find(":isin:")
        if marker >= 0:
            prefix = explicit[:marker].strip().lower()
            value = explicit[marker + len(":isin:") :].strip().upper()
            if prefix and value:
                return f"{prefix}:isin:{value}"
        return explicit

    normalized_isin = str(isin or "").strip().upper()
    normalized_exchange = str(exchange or "").strip().lower()
    if not normalized_isin or not normalized_exchange:
        return None
    return f"{normalized_exchange}:isin:{normalized_isin}"


def _exchange_matches(
    record: SecurityIdentityRecord,
    normalized_exchange: str | None,
) -> bool:
    return (
        normalized_exchange is None
        or record.exchange is None
        or record.exchange == normalized_exchange
    )


def _reference_record(
    records: tuple[SecurityIdentityRecord, ...],
    trading_date: date,
) -> SecurityIdentityRecord:
    historical = tuple(
        record
        for record in records
        if record.effective_from is None or record.effective_from <= trading_date
    )
    if historical:
        return max(
            historical,
            key=lambda record: (
                record.effective_from or date.min,
                record.effective_to or date.max,
                record.symbol,
            ),
        )
    return min(
        records,
        key=lambda record: (
            record.effective_from or date.min,
            record.effective_to or date.max,
            record.symbol,
        ),
    )


def _record_from_preview(row: CanonicalPreviewRow) -> SecurityIdentityRecord:
    values = row.values
    security_id = _required_text(values, "security_id", fallback=row.record_key)
    symbol = _required_text(values, "symbol")
    return SecurityIdentityRecord(
        security_id=security_id,
        symbol=symbol,
        exchange=_optional_text(values.get("exchange")),
        effective_from=_optional_date(
            values.get("effective_from") or values.get("listing_date")
        ),
        effective_to=_optional_date(
            values.get("effective_to") or values.get("delisting_date")
        ),
        historical_symbols=_symbols(values.get("historical_symbols")),
        evidence_ids=row.evidence_ids,
        recovery_version=str(values.get("recovery_version") or "HTR-002-v1.0.0"),
    )


def _required_text(
    values: Mapping[str, object],
    key: str,
    *,
    fallback: str = "",
) -> str:
    value = values.get(key)
    text = str(value).strip() if value is not None else fallback.strip()
    if not text:
        raise ValueError(f"security recovery preview is missing {key}")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    return date.fromisoformat(text[:10])


def _symbols(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        text = str(value).strip()
        if not text:
            return ()
        if text.startswith("["):
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                raise ValueError("historical_symbols JSON must contain a list")
            items = parsed
        else:
            items = text.replace("|", ",").replace(";", ",").split(",")
    return tuple(
        sorted({str(item).strip().upper() for item in items if str(item).strip()})
    )


__all__ = [
    "SecurityIdentityRecord",
    "SecurityIdentityTimeline",
    "normalize_source_security_id",
]
