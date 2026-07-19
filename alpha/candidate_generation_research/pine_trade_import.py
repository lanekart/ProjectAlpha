from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from alpha.candidate_generation_research.models import PineLogicalTradeAudit


class PineLogicalTradeAuditEngine:
    """Aggregate Strategy Tester exit legs under one immutable logical entry."""

    def audit_directory(
        self,
        directory: Path | str | None,
    ) -> tuple[PineLogicalTradeAudit, ...]:
        if directory is None:
            return ()
        root = Path(directory)
        if not root.is_dir():
            raise ValueError(f"Pine evidence directory does not exist: {root}")
        rows: list[PineLogicalTradeAudit] = []
        for path in sorted(root.glob("*.csv")):
            with path.open(encoding="utf-8-sig", newline="") as handle:
                decoded = tuple(
                    _normalize(dict(item)) for item in csv.DictReader(handle)
                )
            if decoded:
                rows.extend(self.audit_rows(decoded, source_file=path.as_posix()))
        return tuple(rows)

    def audit_rows(
        self,
        rows: tuple[dict[str, str], ...],
        *,
        source_file: str = "MEMORY",
    ) -> tuple[PineLogicalTradeAudit, ...]:
        if not rows:
            return ()
        direct = tuple(item for item in rows if _pick(item, "entry_date", "entry_time"))
        if direct:
            return _direct_audit(direct, source_file)
        return _transaction_audit(rows, source_file)


def _direct_audit(
    rows: tuple[dict[str, str], ...],
    source_file: str,
) -> tuple[PineLogicalTradeAudit, ...]:
    grouped: dict[tuple[str, date, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        symbol = (_pick(row, "symbol", "ticker") or "UNKNOWN").upper()
        entry_date = _date(_pick(row, "entry_date", "entry_time"))
        entry_price = _pick(row, "entry_price", "entry")
        signal = _pick(row, "entry_name", "setup", "signal") or "ENTRY"
        grouped[(symbol, entry_date, entry_price, signal)].append(row)
    audits: list[PineLogicalTradeAudit] = []
    for key, items in sorted(grouped.items()):
        symbol, entry_date, entry_price, signal = key
        entry_quantity = max(
            _decimal(_pick(item, "entry_quantity", "initial_quantity"))
            or _decimal(_pick(item, "quantity", "qty", "contracts"))
            or Decimal("1")
            for item in items
        )
        exits = tuple(
            sorted(items, key=lambda item: _pick(item, "exit_date", "exit_time"))
        )
        logical_id = _logical_id(symbol, entry_date, entry_price, signal)
        audits.extend(
            _exit_audits(
                logical_id=logical_id,
                symbol=symbol,
                entry_date=entry_date,
                entry_quantity=entry_quantity,
                exits=exits,
                source_file=source_file,
                direct=True,
            )
        )
    return tuple(audits)


def _transaction_audit(
    rows: tuple[dict[str, str], ...],
    source_file: str,
) -> tuple[PineLogicalTradeAudit, ...]:
    trade_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for index, row in enumerate(rows, start=1):
        number = _pick(row, "trade", "trade_number", "trade_no", "trade_#")
        trade_groups[number or str(index)].append(row)
    grouped: dict[tuple[str, date, str, str], list[dict[str, str]]] = defaultdict(list)
    for number, trade_rows in sorted(trade_groups.items()):
        entry = next(
            (
                item
                for item in trade_rows
                if "entry" in _pick(item, "type", "order_type").lower()
            ),
            None,
        )
        if entry is None:
            continue
        symbol = (_pick(entry, "symbol", "ticker") or "UNKNOWN").upper()
        entry_date = _date(
            _pick(entry, "entry_date", "date/time", "date_time", "date", "time")
        )
        entry_price = _pick(entry, "entry_price", "price", "price_inr")
        signal = _pick(entry, "signal", "entry_name", "order_name") or "ENTRY"
        key = (symbol, entry_date, entry_price, signal)
        grouped[key].append(entry)
        grouped[key].extend(
            item
            for item in trade_rows
            if "exit" in _pick(item, "type", "order_type").lower()
        )
    audits: list[PineLogicalTradeAudit] = []
    for (symbol, entry_date, entry_price, signal), items in sorted(grouped.items()):
        entries = [
            item
            for item in items
            if "entry" in _pick(item, "type", "order_type").lower()
        ]
        exits = [
            item
            for item in items
            if "exit" in _pick(item, "type", "order_type").lower()
        ]
        entry_quantity = max(
            (_quantity(item, Decimal("1")) for item in entries or items),
            default=Decimal("1"),
        )
        logical_id = _logical_id(symbol, entry_date, entry_price, signal)
        audits.extend(
            _exit_audits(
                logical_id=logical_id,
                symbol=symbol,
                entry_date=entry_date,
                entry_quantity=entry_quantity,
                exits=tuple(sorted(exits, key=_row_date)),
                source_file=source_file,
                direct=False,
            )
        )
    return tuple(audits)


def _exit_audits(
    *,
    logical_id: str,
    symbol: str,
    entry_date: date,
    entry_quantity: Decimal,
    exits: tuple[dict[str, str], ...],
    source_file: str,
    direct: bool,
) -> tuple[PineLogicalTradeAudit, ...]:
    if not exits or all(
        not _pick(item, "exit_date", "exit_time", "date/time", "date_time")
        for item in exits
    ):
        return (
            PineLogicalTradeAudit(
                logical_entry_id=logical_id,
                symbol=symbol,
                entry_date=entry_date,
                entry_quantity=entry_quantity,
                exit_leg_id=f"{logical_id}-unresolved",
                exit_date=None,
                exit_quantity=Decimal("0"),
                remaining_quantity=entry_quantity,
                forced_boundary_exit=False,
                issue="OPEN_OR_MISSING_EXIT",
                source_file=source_file,
            ),
        )
    remaining = entry_quantity
    rows = []
    for index, exit_row in enumerate(exits, start=1):
        explicit = _decimal(_pick(exit_row, "exit_quantity", "exit_qty"))
        quantity = min(
            remaining,
            explicit if explicit is not None else _quantity(exit_row, remaining),
        )
        remaining = max(Decimal("0"), remaining - quantity)
        is_last = index == len(exits)
        rows.append(
            PineLogicalTradeAudit(
                logical_entry_id=logical_id,
                symbol=symbol,
                entry_date=entry_date,
                entry_quantity=entry_quantity,
                exit_leg_id=f"{logical_id}-exit-{index}",
                exit_date=_optional_date(
                    _pick(
                        exit_row,
                        "exit_date" if direct else "date/time",
                        "exit_time" if direct else "date_time",
                        "date",
                        "time",
                    )
                ),
                exit_quantity=quantity,
                remaining_quantity=remaining,
                forced_boundary_exit=_forced(exit_row),
                issue=(
                    "RESIDUAL_POSITION"
                    if is_last and remaining > 0
                    else "CLOSED"
                    if is_last
                    else "PARTIAL_EXIT"
                ),
                source_file=source_file,
            )
        )
    return tuple(rows)


def chart_line_mapping() -> dict[str, str]:
    return {
        "blue": "EMA20 trend reference",
        "orange": "EMA50 invalidation reference",
        "red": "Initial stop",
        "green": "Entry trigger",
        "gray": "EMA200 primary trend reference",
        "teal": "Target 1",
        "aqua": "Target 2",
        "purple": "Target 3",
    }


def _quantity(row: dict[str, str], fallback: Decimal) -> Decimal:
    quantity = _decimal(_pick(row, "quantity", "qty", "contracts"))
    if quantity is not None:
        return abs(quantity)
    percent = _decimal(_pick(row, "qty_percent", "quantity_percent"))
    return fallback if percent is None else fallback * abs(percent) / Decimal("100")


def _forced(row: dict[str, str]) -> bool:
    text = " ".join(row.values()).upper()
    return "FORCED_BOUNDARY_EXIT" in text or "END_OF_TEST" in text


def _normalize(row: dict[str, str]) -> dict[str, str]:
    return {
        key.strip().lower().replace(" ", "_"): (value or "").strip()
        for key, value in row.items()
    }


def _pick(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = row.get(key.strip().lower().replace(" ", "_"), "").strip()
        if value:
            return value
    return ""


def _decimal(value: str) -> Decimal | None:
    text = value.replace(",", "").replace("%", "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as error:
        raise ValueError(f"invalid Pine quantity: {value}") from error


def _date(value: str) -> date:
    parsed = _optional_date(value)
    if parsed is None:
        raise ValueError("Pine logical trade requires a date")
    return parsed


def _optional_date(value: str) -> date | None:
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(text.split()[0], pattern).date()
            except ValueError:
                continue
    raise ValueError(f"unsupported Pine date: {value}")


def _row_date(row: dict[str, str]) -> str:
    return _pick(row, "date/time", "date_time", "date", "time")


def _logical_id(symbol: str, entry_date: date, entry_price: str, signal: str) -> str:
    payload = f"{symbol}|{entry_date}|{entry_price}|{signal}"
    return "pine-logical-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


__all__ = ["PineLogicalTradeAuditEngine", "chart_line_mapping"]
