from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from alpha.canonical_integrity_audit.models import (
    EvidenceClass,
    PineExperimentMetadata,
    PineTrade,
)


class PineTradeImporter:
    """Import measured TradingView files without upgrading weak evidence."""

    def import_directory(
        self,
        directory: Path | str,
    ) -> tuple[tuple[PineExperimentMetadata, ...], tuple[PineTrade, ...]]:
        root = Path(directory)
        if not root.is_dir():
            raise ValueError(f"Pine import directory does not exist: {root}")
        metadata = self._metadata(root)
        metadata_by_stem = {Path(item.source_file).stem: item for item in metadata}
        imported_metadata = list(metadata)
        trades: list[PineTrade] = []
        for path in sorted(root.glob("*.csv")):
            rows = _read_csv(path)
            if not rows:
                continue
            if not _looks_like_trade_file(rows[0]):
                companion = metadata_by_stem.get(path.stem) or _best_metadata(metadata)
                if companion is not None:
                    imported_metadata.append(
                        replace(
                            companion,
                            evidence_class=EvidenceClass.CSV_SUMMARY,
                            source_file=path.as_posix(),
                        )
                    )
                continue
            companion = metadata_by_stem.get(path.stem) or _best_metadata(metadata)
            trades.extend(_trade_rows(path, rows, companion))
        return (
            tuple(
                sorted(
                    imported_metadata,
                    key=lambda item: (
                        item.symbol,
                        item.start_date,
                        item.source_file,
                    ),
                )
            ),
            tuple(sorted(trades, key=lambda item: item.trade_id)),
        )

    def _metadata(self, root: Path) -> tuple[PineExperimentMetadata, ...]:
        rows: list[PineExperimentMetadata] = []
        for path in sorted(root.glob("*.json")):
            decoded = cast(object, json.loads(path.read_text(encoding="utf-8")))
            for index, item in enumerate(_metadata_rows(decoded)):
                rows.append(_metadata_record(path, item, index))
        return tuple(
            sorted(
                rows, key=lambda item: (item.symbol, item.start_date, item.source_file)
            )
        )


def _trade_rows(
    path: Path,
    rows: tuple[dict[str, str], ...],
    metadata: PineExperimentMetadata | None,
) -> tuple[PineTrade, ...]:
    normalized = [_normalized_row(row) for row in rows]
    direct = tuple(
        _direct_trade(path, row, metadata, index)
        for index, row in enumerate(normalized, start=1)
        if _pick(row, "entry_date", "entry_time", "entry_datetime")
    )
    if direct:
        return direct
    return _transaction_trades(path, normalized, metadata)


def _direct_trade(
    path: Path,
    row: dict[str, str],
    metadata: PineExperimentMetadata | None,
    index: int,
) -> PineTrade:
    entry_date = _date(_pick(row, "entry_date", "entry_time", "entry_datetime"))
    symbol = _pick(row, "symbol", "ticker") or (
        metadata.symbol if metadata else "UNKNOWN"
    )
    exchange = _pick(row, "exchange") or (metadata.exchange if metadata else "UNKNOWN")
    trade_number = _pick(row, "trade", "trade_number", "trade_no") or str(index)
    trade_id = _trade_id(path, trade_number, symbol, entry_date)
    return PineTrade(
        trade_id=trade_id,
        symbol=symbol,
        exchange=exchange,
        entry_date=entry_date,
        entry_bar=_integer(_pick(row, "entry_bar", "bar_index")),
        setup_family=_pick(row, "setup", "setup_family", "signal")
        or (metadata.setup_selection if metadata else "UNKNOWN"),
        strategy_family=_pick(row, "strategy", "strategy_family")
        or (metadata.strategy_family if metadata else "UNKNOWN"),
        score=_decimal(_pick(row, "score", "pine_score")),
        entry_price=_decimal(_pick(row, "entry_price", "entry")),
        stop_price=_decimal(_pick(row, "stop", "stop_price")),
        target_1=_decimal(_pick(row, "target_1", "target1")),
        target_2=_decimal(_pick(row, "target_2", "target2")),
        target_3=_decimal(_pick(row, "target_3", "target3")),
        exit_date=_optional_date(_pick(row, "exit_date", "exit_time", "exit_datetime")),
        exit_price=_decimal(_pick(row, "exit_price", "exit")),
        net_return_pct=_decimal(
            _pick(row, "net_return_pct", "profit_percent", "profit_pct")
        ),
        evidence_class=EvidenceClass.CSV_TRADE_LEVEL,
        source_file=path.as_posix(),
    )


def _transaction_trades(
    path: Path,
    rows: list[dict[str, str]],
    metadata: PineExperimentMetadata | None,
) -> tuple[PineTrade, ...]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for index, row in enumerate(rows, start=1):
        number = _pick(row, "trade", "trade_number", "trade_no", "trade_#") or str(
            index
        )
        grouped.setdefault(number, []).append(row)
    trades = []
    for number, items in sorted(grouped.items()):
        entry = next(
            (
                item
                for item in items
                if "entry" in _pick(item, "type", "order_type").lower()
            ),
            items[-1],
        )
        exit_row = next(
            (
                item
                for item in items
                if "exit" in _pick(item, "type", "order_type").lower()
            ),
            None,
        )
        entry_date = _date(_pick(entry, "date/time", "date_time", "date", "time"))
        symbol = _pick(entry, "symbol", "ticker") or (
            metadata.symbol if metadata else "UNKNOWN"
        )
        exchange = _pick(entry, "exchange") or (
            metadata.exchange if metadata else "UNKNOWN"
        )
        trades.append(
            PineTrade(
                trade_id=_trade_id(path, number, symbol, entry_date),
                symbol=symbol,
                exchange=exchange,
                entry_date=entry_date,
                entry_bar=None,
                setup_family=_pick(entry, "signal", "setup")
                or (metadata.setup_selection if metadata else "UNKNOWN"),
                strategy_family=(metadata.strategy_family if metadata else "UNKNOWN"),
                score=_decimal(_pick(entry, "score", "pine_score")),
                entry_price=_decimal(_pick(entry, "price", "price_inr", "entry_price")),
                stop_price=_decimal(_pick(entry, "stop", "stop_price")),
                target_1=_decimal(_pick(entry, "target_1", "target1")),
                target_2=_decimal(_pick(entry, "target_2", "target2")),
                target_3=_decimal(_pick(entry, "target_3", "target3")),
                exit_date=(
                    None
                    if exit_row is None
                    else _optional_date(
                        _pick(exit_row, "date/time", "date_time", "date", "time")
                    )
                ),
                exit_price=(
                    None
                    if exit_row is None
                    else _decimal(_pick(exit_row, "price", "price_inr", "exit_price"))
                ),
                net_return_pct=(
                    None
                    if exit_row is None
                    else _decimal(
                        _pick(exit_row, "profit_%", "profit_percent", "profit_pct")
                    )
                ),
                evidence_class=EvidenceClass.CSV_TRADE_LEVEL,
                source_file=path.as_posix(),
            )
        )
    return tuple(trades)


def _metadata_record(
    path: Path,
    row: dict[str, object],
    index: int,
) -> PineExperimentMetadata:
    evidence = EvidenceClass(str(row.get("evidence_class", "CSV_SUMMARY")).upper())
    return PineExperimentMetadata(
        symbol=_required_text(row, "symbol"),
        exchange=_text(row.get("exchange"), "UNKNOWN"),
        chart_timeframe=_text(row.get("chart_timeframe"), "UNKNOWN"),
        start_date=_object_date(row.get("start_date")),
        end_date=_object_date(row.get("end_date")),
        entry_threshold=_object_decimal(row.get("entry_threshold")),
        strategy_family=_text(row.get("strategy_family"), "UNKNOWN"),
        setup_selection=_text(row.get("setup_selection"), "UNKNOWN"),
        commission=_object_decimal(row.get("commission")),
        slippage=_object_decimal(row.get("slippage")),
        position_size=_object_decimal(row.get("position_size")),
        market_regime_setting=_text(row.get("market_regime_setting"), "UNAVAILABLE"),
        sector_setting=_text(row.get("sector_setting"), "UNAVAILABLE"),
        script_version=_text(row.get("script_version"), "UNKNOWN"),
        framework_version=_text(row.get("framework_version"), "UNKNOWN"),
        evidence_class=evidence,
        source_file=(path.as_posix() if index == 0 else f"{path.as_posix()}#{index}"),
    )


def _metadata_rows(value: object) -> tuple[dict[str, object], ...]:
    if isinstance(value, dict):
        if isinstance(value.get("experiments"), list):
            return tuple(_object(item) for item in value["experiments"])
        if "symbol" in value:
            return (_object(value),)
    if isinstance(value, list):
        return tuple(_object(item) for item in value)
    return ()


def _looks_like_trade_file(row: dict[str, str]) -> bool:
    keys = {key.strip().lower().replace(" ", "_") for key in row}
    return bool(
        keys
        & {
            "entry_date",
            "entry_time",
            "entry_datetime",
            "trade_#",
            "trade_number",
            "date/time",
        }
    )


def _read_csv(path: Path) -> tuple[dict[str, str], ...]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


def _normalized_row(row: dict[str, str]) -> dict[str, str]:
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


def _date(value: str) -> date:
    parsed = _optional_date(value)
    if parsed is None:
        raise ValueError("Pine trade entry date is required")
    return parsed


def _optional_date(value: str) -> date | None:
    text = value.strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(text.split()[0], pattern).date()
            except ValueError:
                continue
    raise ValueError(f"unsupported Pine date: {text}")


def _decimal(value: str) -> Decimal | None:
    text = value.replace(",", "").replace("%", "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as error:
        raise ValueError(f"invalid Pine numeric value: {value}") from error


def _integer(value: str) -> int | None:
    return None if not value.strip() else int(value)


def _object_decimal(value: object) -> Decimal | None:
    return None if value in {None, ""} else Decimal(str(value))


def _object_date(value: object) -> date:
    if not isinstance(value, str):
        raise ValueError("Pine metadata requires ISO start/end dates")
    return date.fromisoformat(value)


def _required_text(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Pine metadata requires {key}")
    return value.strip()


def _text(value: object, default: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else default


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Pine metadata record must be an object")
    return {str(key): item for key, item in value.items()}


def _trade_id(path: Path, number: str, symbol: str, entry_date: date) -> str:
    payload = f"{path.name}|{number}|{symbol.upper()}|{entry_date.isoformat()}"
    return "pine-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _best_metadata(
    metadata: tuple[PineExperimentMetadata, ...],
) -> PineExperimentMetadata | None:
    return metadata[0] if len(metadata) == 1 else None


__all__ = ["PineTradeImporter"]
