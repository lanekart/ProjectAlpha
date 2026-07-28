"""Governed dated identity bridge for legacy candles without an ISIN."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

LEGACY_ISIN_REFERENCE_BRIDGE_CONTRACT_VERSION = (
    "HTR-010B-LEGACY-ISIN-REFERENCE-BRIDGE-v1.0.0"
)

_REQUIRED_FILES = (
    "htr009a2_membership_intervals.json",
    "htr009a2_symbol_intervals.json",
    "htr009a2_security_events.json",
)


@dataclass(frozen=True, slots=True)
class LegacyIsinReferenceBridgeResult:
    """Evidence result for one prior close whose candle omits an ISIN."""

    state: str
    certified: bool
    identity_key: str
    symbol: str
    series: str
    isin: str
    reference_date: date
    membership_source_event_ids: tuple[str, ...] = ()
    symbol_source_event_ids: tuple[str, ...] = ()
    official_event_ids: tuple[str, ...] = ()
    official_source_ids: tuple[str, ...] = ()

    def provenance(self) -> dict[str, Any]:
        return {
            "reference_price_bridge_contract_version": (
                LEGACY_ISIN_REFERENCE_BRIDGE_CONTRACT_VERSION
            ),
            "reference_price_bridge_state": self.state,
            "reference_price_bridge_identity": self.identity_key,
            "reference_price_bridge_symbol": self.symbol,
            "reference_price_bridge_series": self.series,
            "reference_price_bridge_isin": self.isin,
            "reference_price_bridge_membership_event_ids": list(
                self.membership_source_event_ids
            ),
            "reference_price_bridge_symbol_event_ids": list(
                self.symbol_source_event_ids
            ),
            "reference_price_bridge_official_event_ids": list(self.official_event_ids),
            "reference_price_bridge_official_source_ids": list(
                self.official_source_ids
            ),
        }


@dataclass(frozen=True, slots=True)
class _OfficialState:
    effective_date: date
    identity_key: str
    symbol: str
    series: str
    isin: str
    event_id: str
    official_source_id: str


class LegacyIsinReferenceBridge:
    """Resolve only exact, dated, lineage-bound legacy identity contexts."""

    def __init__(
        self,
        *,
        memberships: tuple[dict[str, Any], ...],
        symbols: tuple[dict[str, Any], ...],
        official_states: tuple[_OfficialState, ...],
        source_checksums: tuple[tuple[str, str], ...],
    ) -> None:
        self.source_checksums = source_checksums
        self._memberships: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._symbols_by_identity: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._symbols_by_value: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._official_states: dict[str, list[_OfficialState]] = defaultdict(list)
        for row in memberships:
            self._memberships[str(row["identity_key"])].append(row)
        for row in symbols:
            self._symbols_by_identity[str(row["identity_key"])].append(row)
            self._symbols_by_value[str(row["symbol"]).upper()].append(row)
        for state in official_states:
            self._official_states[state.identity_key].append(state)

    @classmethod
    def from_output(cls, output: Path) -> LegacyIsinReferenceBridge:
        paths = tuple(_unique_file(output, name) for name in _REQUIRED_FILES)
        payloads = {path.name: _records(path) for path in paths}
        memberships = tuple(payloads[_REQUIRED_FILES[0]])
        symbols = tuple(payloads[_REQUIRED_FILES[1]])
        events = tuple(payloads[_REQUIRED_FILES[2]])
        _validate_memberships(memberships)
        _validate_symbols(symbols)
        official_states = _official_states(events)
        checksums = tuple(
            sorted(
                (
                    f"htr009a2/{path.name}",
                    sha256(path.read_bytes()).hexdigest(),
                )
                for path in paths
            )
        )
        return cls(
            memberships=memberships,
            symbols=symbols,
            official_states=official_states,
            source_checksums=checksums,
        )

    def resolve(
        self,
        *,
        identity_key: str,
        symbol: str,
        series: str,
        isin: str,
        reference_date: date,
    ) -> LegacyIsinReferenceBridgeResult:
        normalized_symbol = symbol.upper()
        normalized_series = series.upper()
        normalized_isin = isin.upper()

        memberships = tuple(
            row
            for row in self._memberships.get(identity_key, ())
            if _contains(row, reference_date)
        )
        symbol_rows = tuple(
            row
            for row in self._symbols_by_identity.get(identity_key, ())
            if str(row["symbol"]).upper() == normalized_symbol
            and _contains(row, reference_date)
        )
        conflicts = tuple(
            row
            for row in self._symbols_by_value.get(normalized_symbol, ())
            if str(row["identity_key"]) != identity_key
            and _contains(row, reference_date)
        )
        membership_lineage = _lineage(memberships)
        symbol_lineage = _lineage(symbol_rows)
        states = tuple(
            row
            for row in self._official_states.get(identity_key, ())
            if row.effective_date <= reference_date
        )
        latest_date = max((row.effective_date for row in states), default=None)
        latest = tuple(row for row in states if row.effective_date == latest_date)
        latest_values = {(row.symbol, row.series, row.isin) for row in latest}
        official_event_ids = tuple(sorted({row.event_id for row in latest}))
        official_source_ids = tuple(sorted({row.official_source_id for row in latest}))

        state = "CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE"
        if len(memberships) != 1:
            state = "MEMBERSHIP_INTERVAL_NOT_UNIQUE"
        elif not membership_lineage:
            state = "MEMBERSHIP_LINEAGE_MISSING"
        elif len(symbol_rows) != 1:
            state = "SYMBOL_INTERVAL_NOT_UNIQUE"
        elif str(symbol_rows[0].get("confidence_state")) != "HIGH":
            state = "SYMBOL_INTERVAL_CONFIDENCE_NOT_HIGH"
        elif tuple(symbol_rows[0].get("issue_codes") or ()):
            state = "SYMBOL_INTERVAL_HAS_ISSUES"
        elif not symbol_lineage:
            state = "SYMBOL_INTERVAL_LINEAGE_MISSING"
        elif conflicts:
            state = "OVERLAPPING_SYMBOL_IDENTITY"
        elif latest_date is None:
            state = "OFFICIAL_SERIES_EVENT_MISSING"
        elif len(latest_values) != 1:
            state = "OFFICIAL_SERIES_EVENT_AMBIGUOUS"
        else:
            observed_symbol, observed_series, observed_isin = next(iter(latest_values))
            if observed_symbol != normalized_symbol:
                state = "OFFICIAL_EVENT_SYMBOL_MISMATCH"
            elif observed_series != normalized_series:
                state = "OFFICIAL_EVENT_SERIES_MISMATCH"
            elif observed_isin != normalized_isin:
                state = "OFFICIAL_EVENT_ISIN_MISMATCH"
            elif not set(official_event_ids).issubset(membership_lineage):
                state = "MEMBERSHIP_EVENT_LINEAGE_DIVERGES"
            elif not set(official_event_ids).issubset(symbol_lineage):
                state = "SYMBOL_EVENT_LINEAGE_DIVERGES"

        return LegacyIsinReferenceBridgeResult(
            state=state,
            certified=state == "CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE",
            identity_key=identity_key,
            symbol=normalized_symbol,
            series=normalized_series,
            isin=normalized_isin,
            reference_date=reference_date,
            membership_source_event_ids=tuple(sorted(membership_lineage)),
            symbol_source_event_ids=tuple(sorted(symbol_lineage)),
            official_event_ids=official_event_ids,
            official_source_ids=official_source_ids,
        )


def _unique_file(output: Path, name: str) -> Path:
    direct = output / name
    if direct.is_file():
        return direct
    matches = tuple(sorted(output.rglob(name))) if output.is_dir() else ()
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one {name} under {output}, found {len(matches)}"
        )
    return matches[0]


def _records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("records"), list):
        rows = payload["records"]
    else:
        raise ValueError(f"{path.name} must contain a records array")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{path.name} contains a non-object record")
    return [dict(row) for row in rows]


def _validate_memberships(rows: tuple[dict[str, Any], ...]) -> None:
    required = {"identity_key", "valid_from", "valid_to", "source_event_ids"}
    _validate_rows(rows, required, "membership interval")


def _validate_symbols(rows: tuple[dict[str, Any], ...]) -> None:
    required = {
        "identity_key",
        "symbol",
        "valid_from",
        "valid_to",
        "confidence_state",
        "issue_codes",
        "source_event_ids",
    }
    _validate_rows(rows, required, "symbol interval")


def _validate_rows(
    rows: tuple[dict[str, Any], ...], required: set[str], label: str
) -> None:
    for index, row in enumerate(rows):
        missing = required - row.keys()
        if missing:
            raise ValueError(f"{label} {index} missing fields: {sorted(missing)}")
        start = date.fromisoformat(str(row["valid_from"]))
        end = date.fromisoformat(str(row["valid_to"]))
        if end < start:
            raise ValueError(f"{label} {index} has an inverted interval")


def _official_states(rows: tuple[dict[str, Any], ...]) -> tuple[_OfficialState, ...]:
    states: list[_OfficialState] = []
    for row in rows:
        if row.get("admission_state") != "ADMITTED":
            continue
        if row.get("confidence_state") != "HIGH":
            continue
        effective = row.get("effective_date")
        event_id = str(row.get("event_id") or "")
        source_id = str(row.get("official_source_id") or "")
        if not effective or not event_id or not source_id:
            continue
        for side in ("new", "old"):
            identity_field = (
                "successor_identity" if side == "new" else "predecessor_identity"
            )
            identity = str(row.get(identity_field) or "")
            symbol = str(row.get(f"{side}_symbol") or "").upper()
            series = str(row.get(f"{side}_series") or "").upper()
            isin = str(row.get(f"{side}_isin") or "").upper()
            if not identity or not symbol or not series or not isin:
                continue
            if identity != f"nse:isin:{isin}":
                continue
            states.append(
                _OfficialState(
                    effective_date=date.fromisoformat(str(effective)),
                    identity_key=identity,
                    symbol=symbol,
                    series=series,
                    isin=isin,
                    event_id=event_id,
                    official_source_id=source_id,
                )
            )
    return tuple(
        sorted(
            states,
            key=lambda row: (
                row.identity_key,
                row.effective_date,
                row.event_id,
                row.symbol,
                row.series,
            ),
        )
    )


def _contains(row: dict[str, Any], value: date) -> bool:
    return (
        date.fromisoformat(str(row["valid_from"]))
        <= value
        <= date.fromisoformat(str(row["valid_to"]))
    )


def _lineage(rows: tuple[dict[str, Any], ...]) -> set[str]:
    return {
        str(item)
        for row in rows
        for item in tuple(row.get("source_event_ids") or ())
        if str(item)
    }


__all__ = [
    "LEGACY_ISIN_REFERENCE_BRIDGE_CONTRACT_VERSION",
    "LegacyIsinReferenceBridge",
    "LegacyIsinReferenceBridgeResult",
]
