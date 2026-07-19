from __future__ import annotations

from collections import defaultdict
from datetime import date
from hashlib import sha256

from alpha.historical_truth_acquisition.models import (
    AlphaSecurityIdentity,
    ConfidenceGrade,
)
from alpha.market_truth.warehouse.models import IdentityRecord


def alpha_security_id(*, isin: str | None, exchange: str, symbol: str) -> str:
    if isin and isin.strip():
        return "ALPHA:ISIN:" + isin.strip().upper()
    payload = f"{exchange.strip().upper()}|{symbol.strip().upper()}".encode()
    return "ALPHA:EXCHANGE_SYMBOL:" + sha256(payload).hexdigest()[:24].upper()


def build_security_master(
    records: tuple[IdentityRecord, ...],
) -> tuple[AlphaSecurityIdentity, ...]:
    grouped: dict[str, list[IdentityRecord]] = defaultdict(list)
    for record in records:
        grouped[
            alpha_security_id(
                isin=record.isin,
                exchange=record.exchange.value,
                symbol=record.symbol,
            )
        ].append(record)
    identities = []
    for security_id in sorted(grouped):
        history = tuple(grouped[security_id])
        symbols = tuple(sorted({item.symbol for item in history}))
        current = tuple(
            sorted({item.symbol for item in history if item.symbol_valid_to is None})
        )
        listing_dates = tuple(
            item.listing_date for item in history if item.listing_date is not None
        )
        delisting_dates = tuple(
            item.delisting_date for item in history if item.delisting_date is not None
        )
        isins = tuple(sorted({item.isin for item in history if item.isin}))
        identities.append(
            AlphaSecurityIdentity(
                alpha_security_id=security_id,
                isin=(isins[0] if len(isins) == 1 else None),
                exchanges=tuple(sorted({item.exchange.value for item in history})),
                current_symbols=current or symbols[-1:],
                historical_symbols=symbols,
                listing_date=min(listing_dates, default=None),
                delisting_date=max(delisting_dates, default=None),
                source_file_ids=tuple(
                    sorted({item.source_file_id for item in history})
                ),
                confidence=(
                    ConfidenceGrade.HIGH if len(isins) == 1 else ConfidenceGrade.MEDIUM
                ),
            )
        )
    return tuple(identities)


def resolve_symbol(
    records: tuple[IdentityRecord, ...],
    *,
    symbol: str,
    effective_date: date,
    isin: str | None,
) -> tuple[str, ConfidenceGrade, bool]:
    if isin:
        return (
            alpha_security_id(isin=isin, exchange="NSE", symbol=symbol),
            ConfidenceGrade.HIGH,
            True,
        )
    normalized = symbol.strip().upper()
    matches = tuple(
        item
        for item in records
        if item.symbol == normalized
        and item.symbol_valid_from <= effective_date
        and (item.symbol_valid_to is None or item.symbol_valid_to >= effective_date)
    )
    if len(matches) == 1:
        match = matches[0]
        return (
            alpha_security_id(
                isin=match.isin,
                exchange=match.exchange.value,
                symbol=match.symbol,
            ),
            ConfidenceGrade.HIGH if match.isin else ConfidenceGrade.MEDIUM,
            True,
        )
    return (
        alpha_security_id(isin=None, exchange="UNRESOLVED", symbol=normalized),
        ConfidenceGrade.LOW,
        False,
    )


__all__ = ["alpha_security_id", "build_security_master", "resolve_symbol"]
