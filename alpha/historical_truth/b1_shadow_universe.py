"""Immutable B1H universe binding for governed shadow replay."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

import pandas as pd

from alpha.recovery.security_timeline import (
    SecurityIdentityTimeline,
    normalize_source_security_id,
)

HTR010B1H_CONTRACT_VERSION = "HTR-010B1H-v1.0.0"


@dataclass(frozen=True, slots=True)
class B1ShadowAdmission:
    """Verified B1H admission contract consumed by both replay arms."""

    admitted_security_ids: tuple[str, ...]
    admitted_symbols: tuple[str, ...]
    replay_start: date
    replay_end: date
    dependency_start: date
    dependency_end: date
    admission_contract_sha256: str
    universe_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "admitted_identity_count": len(self.admitted_security_ids),
            "admitted_security_ids": list(self.admitted_security_ids),
            "admitted_symbols": list(self.admitted_symbols),
            "replay_start": self.replay_start.isoformat(),
            "replay_end": self.replay_end.isoformat(),
            "dependency_start": self.dependency_start.isoformat(),
            "dependency_end": self.dependency_end.isoformat(),
            "admission_contract_sha256": self.admission_contract_sha256,
            "universe_sha256": self.universe_sha256,
            "production_influence": False,
        }


def load_b1_shadow_admission(
    *,
    contract_path: Path,
    identity_admission_path: Path,
    raw_universe_path: Path,
    adjusted_universe_path: Path,
) -> B1ShadowAdmission:
    """Load and verify one immutable B1H universe for both replay arms."""

    contract = _mapping(contract_path)
    admissions = _rows(identity_admission_path)
    raw_universe = _string_list(raw_universe_path)
    adjusted_universe = _string_list(adjusted_universe_path)

    if contract.get("contract_version") != HTR010B1H_CONTRACT_VERSION:
        raise ValueError("shadow replay requires the HTR-010B1H contract")
    if contract.get("production_influence") is not False:
        raise ValueError("B1H admission contract must remain diagnostic-only")
    if contract.get("shadow_replay_ready") is not True:
        raise ValueError("B1H admission contract is not shadow-replay ready")
    for key in (
        "admitted_unresolved_action_count",
        "raw_adjusted_universe_difference_count",
        "raw_adjusted_session_difference_count",
        "contract_contradiction_count",
        "implementation_defect_count",
    ):
        if int(contract.get(key, -1)) != 0:
            raise ValueError(f"B1H admission contract has nonzero {key}")

    expected_report_sha = str(contract.get("report_sha256") or "")
    if len(expected_report_sha) != 64 or expected_report_sha != _digest_mapping(
        contract
    ):
        raise ValueError("B1H admission contract digest mismatch")
    if raw_universe != adjusted_universe:
        raise ValueError("RAW and ADJUSTED B1H universes differ")
    if raw_universe != tuple(sorted(set(raw_universe))):
        raise ValueError("B1H universe must be sorted and unique")

    universe_sha = _digest_list(raw_universe)
    if universe_sha != str(contract.get("raw_universe_sha256") or ""):
        raise ValueError("RAW B1H universe digest mismatch")
    if universe_sha != str(contract.get("adjusted_universe_sha256") or ""):
        raise ValueError("ADJUSTED B1H universe digest mismatch")

    admitted_rows = tuple(
        row
        for row in admissions
        if row.get("raw_admitted") is True and row.get("adjusted_admitted") is True
    )
    admitted_by_id: dict[str, str] = {}
    for row in admitted_rows:
        security_id = str(row.get("security_id") or "").strip()
        symbol = str(row.get("symbol") or "").strip().upper()
        if not security_id or not symbol:
            raise ValueError("admitted B1H identity is missing security_id or symbol")
        if security_id in admitted_by_id and admitted_by_id[security_id] != symbol:
            raise ValueError("admitted B1H identity maps to multiple symbols")
        admitted_by_id[security_id] = symbol

    if tuple(sorted(admitted_by_id)) != raw_universe:
        raise ValueError("B1H admission rows do not match the signed universe")
    symbols = tuple(sorted(admitted_by_id.values()))
    if len(symbols) != len(set(symbols)):
        raise ValueError("B1H admitted symbols are not uniquely mapped")
    if int(contract.get("admitted_identity_count", -1)) != len(raw_universe):
        raise ValueError("B1H admitted identity count does not match universe")

    try:
        replay_start = date.fromisoformat(str(contract["replay_start"]))
        replay_end = date.fromisoformat(str(contract["replay_end"]))
        dependency_start = date.fromisoformat(str(contract["dependency_start"]))
        dependency_end = date.fromisoformat(str(contract["dependency_end"]))
    except (KeyError, ValueError) as error:
        raise ValueError(
            "B1H contract requires valid replay and dependency dates"
        ) from error
    if replay_end < replay_start:
        raise ValueError("B1H replay window is inverted")
    if dependency_end < dependency_start:
        raise ValueError("B1H dependency window is inverted")
    if dependency_start > replay_start or dependency_end < replay_end:
        raise ValueError("B1H dependency window does not cover replay window")

    return B1ShadowAdmission(
        admitted_security_ids=raw_universe,
        admitted_symbols=symbols,
        replay_start=replay_start,
        replay_end=replay_end,
        dependency_start=dependency_start,
        dependency_end=dependency_end,
        admission_contract_sha256=expected_report_sha,
        universe_sha256=universe_sha,
    )


class B1IdentityFilteredPriceRepository:
    """Restrict raw source reads to the signed B1H stable-identity universe."""

    def __init__(
        self,
        repository: Any,
        identities: SecurityIdentityTimeline,
        security_ids: tuple[str, ...],
    ) -> None:
        admitted = frozenset(
            item.strip() for item in security_ids if item and item.strip()
        )
        if not admitted:
            raise ValueError("shadow replay requires at least one admitted security ID")
        available = frozenset(record.security_id for record in identities.records)
        missing = tuple(sorted(admitted - available))
        if missing:
            rendered = ", ".join(missing[:10])
            suffix = "..." if len(missing) > 10 else ""
            raise ValueError(
                f"B1H admitted security IDs are absent from identity timeline: "
                f"{rendered}{suffix}"
            )
        self.repository = repository
        self.identities = identities
        self.security_ids = tuple(sorted(admitted))
        self._security_id_set = admitted
        self._source_symbol_set = frozenset(
            symbol
            for record in identities.records
            if record.security_id in admitted
            for symbol in (record.symbol, *record.historical_symbols)
        )

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        return self._filter(self.repository.find_by_trade_date(trade_date))

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        allowed = self._allowed_source_symbols(symbols)
        if not allowed:
            return _empty_price_frame()
        return self._filter(
            self.repository.find_history_by_symbols(
                symbols=allowed,
                end_date=end_date,
                limit=limit,
            )
        )

    def find_range_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        allowed = self._allowed_source_symbols(symbols)
        if not allowed:
            return _empty_price_frame()
        find_range = getattr(self.repository, "find_range_by_symbols", None)
        if not callable(find_range):
            frame = self.find_history_by_symbols(
                symbols=allowed,
                end_date=end_date,
                limit=1320,
            )
            if frame.empty:
                return frame
            result = frame.copy()
            result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.date
            return result.loc[
                (result["trade_date"] >= start_date)
                & (result["trade_date"] <= end_date)
            ].copy()
        return self._filter(
            find_range(
                symbols=allowed,
                start_date=start_date,
                end_date=end_date,
            )
        )

    def find_trade_dates(self, *, start: date, end: date) -> tuple[date, ...]:
        find_trade_dates = getattr(self.repository, "find_trade_dates", None)
        if callable(find_trade_dates):
            return tuple(find_trade_dates(start=start, end=end))
        dates: list[date] = []
        current = start
        while current <= end:
            if not self.find_by_trade_date(current).empty:
                dates.append(current)
            current = date.fromordinal(current.toordinal() + 1)
        return tuple(dates)

    def _allowed_source_symbols(self, symbols: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    symbol.strip().upper()
                    for symbol in symbols
                    if symbol.strip().upper() in self._source_symbol_set
                }
            )
        )

    def _filter(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame.copy()
        required = {"symbol", "trade_date"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(
                "price frame is missing identity columns: " + ", ".join(sorted(missing))
            )

        keep: list[bool] = []
        for row in frame.itertuples(index=False):
            symbol = str(getattr(row, "symbol")).strip().upper()
            raw_exchange = getattr(row, "exchange", None)
            exchange = (
                str(raw_exchange).strip().upper()
                if raw_exchange is not None and str(raw_exchange).strip()
                else None
            )
            direct_id = normalize_source_security_id(
                security_id=_optional_tuple_text(row, "security_id"),
                isin=_optional_tuple_text(row, "isin"),
                exchange=exchange,
            )
            if direct_id is not None and direct_id not in self._security_id_set:
                keep.append(False)
                continue
            if direct_id is None and symbol not in self._source_symbol_set:
                keep.append(False)
                continue

            trading_date = pd.Timestamp(getattr(row, "trade_date")).date()
            resolved = self.identities.resolve_source_identity(
                symbol,
                trading_date=trading_date,
                exchange=exchange,
                security_id=direct_id,
                isin=_optional_tuple_text(row, "isin"),
            )
            if resolved is None:
                rendered_id = direct_id or "NO_SOURCE_SECURITY_ID"
                raise ValueError(
                    "admitted source identity is unresolved: "
                    f"{rendered_id} {symbol} on {trading_date.isoformat()}"
                )
            if direct_id is not None and resolved.security_id != direct_id:
                raise ValueError(
                    "source stable identity disagrees with canonical timeline: "
                    f"{direct_id} != {resolved.security_id}"
                )
            keep.append(resolved.security_id in self._security_id_set)
        return frame.loc[keep].copy()


class B1UniverseFilteredPriceRepository:
    """Restrict every price read to the signed B1H symbol universe."""

    def __init__(self, repository: Any, symbols: tuple[str, ...]) -> None:
        normalized = tuple(
            sorted({item.strip().upper() for item in symbols if item.strip()})
        )
        if not normalized:
            raise ValueError("shadow replay requires at least one admitted symbol")
        self.repository = repository
        self.symbols = normalized
        self._symbol_set = frozenset(normalized)

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        return self._filter(self.repository.find_by_trade_date(trade_date))

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        allowed = self._allowed(symbols)
        if not allowed:
            return _empty_price_frame()
        return self._filter(
            self.repository.find_history_by_symbols(
                symbols=allowed,
                end_date=end_date,
                limit=limit,
            )
        )

    def find_range_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        allowed = self._allowed(symbols)
        if not allowed:
            return _empty_price_frame()
        find_range = getattr(self.repository, "find_range_by_symbols", None)
        if not callable(find_range):
            frame = self.find_history_by_symbols(
                symbols=allowed,
                end_date=end_date,
                limit=1320,
            )
            if frame.empty:
                return frame
            result = frame.copy()
            result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.date
            return result.loc[
                (result["trade_date"] >= start_date)
                & (result["trade_date"] <= end_date)
            ].copy()
        return self._filter(
            find_range(
                symbols=allowed,
                start_date=start_date,
                end_date=end_date,
            )
        )

    def find_trade_dates(self, *, start: date, end: date) -> tuple[date, ...]:
        find_trade_dates = getattr(self.repository, "find_trade_dates", None)
        if callable(find_trade_dates):
            return tuple(find_trade_dates(start=start, end=end))
        dates: list[date] = []
        current = start
        while current <= end:
            if not self.find_by_trade_date(current).empty:
                dates.append(current)
            current = date.fromordinal(current.toordinal() + 1)
        return tuple(dates)

    def _allowed(self, symbols: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    symbol.strip().upper()
                    for symbol in symbols
                    if symbol.strip().upper() in self._symbol_set
                }
            )
        )

    def _filter(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame.copy()
        if "symbol" not in frame.columns:
            raise ValueError("price frame is missing symbol")
        normalized = frame["symbol"].astype(str).str.strip().str.upper()
        return frame.loc[normalized.isin(self._symbol_set)].copy()


def _optional_tuple_text(row: object, field: str) -> str | None:
    value = getattr(row, field, None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"artifact must contain a mapping: {path}")
    return dict(payload)


def _rows(path: Path) -> tuple[dict[str, Any], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    valid = isinstance(payload, list) and all(isinstance(row, dict) for row in payload)
    if not valid:
        raise ValueError(f"artifact must contain record mappings: {path}")
    return tuple(dict(row) for row in payload)


def _string_list(path: Path) -> tuple[str, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    valid = isinstance(payload, list) and all(isinstance(item, str) for item in payload)
    if not valid:
        raise ValueError(f"artifact must contain string values: {path}")
    return tuple(payload)


def _digest_mapping(value: dict[str, Any]) -> str:
    payload = dict(value)
    payload.pop("report_sha256", None)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return sha256(encoded).hexdigest()


def _digest_list(value: tuple[str, ...]) -> str:
    encoded = json.dumps(
        list(value),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return sha256(encoded).hexdigest()


def _empty_price_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=(
            "symbol",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "exchange",
            "security_id",
            "isin",
        )
    )


__all__ = [
    "B1IdentityFilteredPriceRepository",
    "B1ShadowAdmission",
    "B1UniverseFilteredPriceRepository",
    "HTR010B1H_CONTRACT_VERSION",
    "load_b1_shadow_admission",
]
