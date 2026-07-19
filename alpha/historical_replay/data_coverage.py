from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

import pandas as pd

_TRADING_DAYS_PER_YEAR = 252
_ONE = Decimal("1")
_FOUR = Decimal("0.0001")


class CoveragePriceRepository(Protocol):
    def find_range_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame: ...


@dataclass(frozen=True, slots=True)
class SymbolDataCoverage:
    symbol: str
    requested_years: int
    requested_start: date
    requested_end: date
    expected_bars: int
    available_bars: int
    first_available_date: date | None
    last_available_date: date | None
    coverage_ratio: Decimal
    missing_bars: int
    quality: str
    explanation: str

    @property
    def has_full_requested_history(self) -> bool:
        return self.available_bars >= self.expected_bars


@dataclass(frozen=True, slots=True)
class HistoricalDataCoverageReport:
    requested_years: int
    requested_start: date
    requested_end: date
    symbols: tuple[SymbolDataCoverage, ...]

    @property
    def symbols_checked(self) -> int:
        return len(self.symbols)

    @property
    def sufficient_symbols(self) -> int:
        return sum(1 for symbol in self.symbols if symbol.quality == "FULL")


class HistoricalDataCoverageAnalyzer:
    def __init__(self, *, price_repository: CoveragePriceRepository) -> None:
        self.price_repository = price_repository

    def analyze(
        self,
        *,
        symbols: tuple[str, ...],
        as_of: date,
        years: int = 10,
    ) -> HistoricalDataCoverageReport:
        if years <= 0:
            raise ValueError("years must be positive")
        normalized_symbols = tuple(
            dict.fromkeys(
                symbol.strip().upper() for symbol in symbols if symbol.strip()
            )
        )
        if not normalized_symbols:
            raise ValueError("at least one symbol is required")

        requested_start = as_of - timedelta(days=years * 366)
        frame = self.price_repository.find_range_by_symbols(
            symbols=normalized_symbols,
            start_date=requested_start,
            end_date=as_of,
        )
        frame = _clean_frame(frame)
        expected_bars = years * _TRADING_DAYS_PER_YEAR
        coverage_by_symbol = tuple(
            _coverage_for_symbol(
                symbol=symbol,
                requested_years=years,
                requested_start=requested_start,
                requested_end=as_of,
                expected_bars=expected_bars,
                frame=frame[frame["symbol"].str.upper() == symbol],
            )
            for symbol in normalized_symbols
        )
        return HistoricalDataCoverageReport(
            requested_years=years,
            requested_start=requested_start,
            requested_end=as_of,
            symbols=coverage_by_symbol,
        )


def render_data_coverage_report(
    report: HistoricalDataCoverageReport,
) -> tuple[str, ...]:
    lines = [
        "Historical Data Coverage",
        (
            "Requested Window: "
            f"{report.requested_start.isoformat()} to "
            f"{report.requested_end.isoformat()}"
        ),
        f"Requested Lookback: {report.requested_years} years",
        f"Symbols Checked: {report.symbols_checked}",
        f"Symbols With Full Requested History: {report.sufficient_symbols}",
        "",
        "Coverage By Symbol:",
    ]
    if not report.symbols:
        lines.append("- unavailable")
        return tuple(lines)
    for item in report.symbols:
        lines.append(
            "- "
            f"{item.symbol}: {item.available_bars}/{item.expected_bars} bars "
            f"({_pct(item.coverage_ratio)}), "
            f"{_date_text(item.first_available_date)} to "
            f"{_date_text(item.last_available_date)}; "
            f"{item.quality} - {item.explanation}"
        )
    return tuple(lines)


def _coverage_for_symbol(
    *,
    symbol: str,
    requested_years: int,
    requested_start: date,
    requested_end: date,
    expected_bars: int,
    frame: pd.DataFrame,
) -> SymbolDataCoverage:
    available = len(frame)
    first_available = _date_or_none(frame["trade_date"].min()) if available else None
    last_available = _date_or_none(frame["trade_date"].max()) if available else None
    missing = max(expected_bars - available, 0)
    coverage_ratio = (
        min(Decimal(available) / Decimal(expected_bars), _ONE).quantize(
            _FOUR,
            rounding=ROUND_HALF_UP,
        )
        if expected_bars > 0
        else Decimal("0")
    )
    quality, explanation = _quality(
        available_bars=available,
        expected_bars=expected_bars,
        first_available_date=first_available,
        requested_start=requested_start,
    )
    return SymbolDataCoverage(
        symbol=symbol,
        requested_years=requested_years,
        requested_start=requested_start,
        requested_end=requested_end,
        expected_bars=expected_bars,
        available_bars=available,
        first_available_date=first_available,
        last_available_date=last_available,
        coverage_ratio=coverage_ratio,
        missing_bars=missing,
        quality=quality,
        explanation=explanation,
    )


def _quality(
    *,
    available_bars: int,
    expected_bars: int,
    first_available_date: date | None,
    requested_start: date,
) -> tuple[str, str]:
    if available_bars <= 0:
        return "MISSING", "no persisted price history found"
    if available_bars >= expected_bars:
        return "FULL", "full requested history is available locally"
    if first_available_date is not None and first_available_date > requested_start:
        return (
            "LISTED_HISTORY_LIMITED",
            "history starts after the requested window, likely because local or "
            "listed history begins later",
        )
    if available_bars >= int(expected_bars * 0.5):
        return "PARTIAL", "partial history is available; long-window evidence is weaker"
    return "INSUFFICIENT", "too little history for robust long-window evidence"


def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "trade_date"])
    cleaned = frame.copy()
    cleaned["symbol"] = cleaned["symbol"].astype(str).str.strip().str.upper()
    cleaned["trade_date"] = pd.to_datetime(cleaned["trade_date"]).dt.date
    cleaned = cleaned.drop_duplicates(subset=["symbol", "trade_date"])
    return cleaned.sort_values(["symbol", "trade_date"]).reset_index(drop=True)


def _date_or_none(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return pd.Timestamp(value).date()
    return None


def _date_text(value: date | None) -> str:
    return "unavailable" if value is None else value.isoformat()


def _pct(value: Decimal) -> str:
    return f"{(value * Decimal('100')).quantize(Decimal('0.01'))}%"


__all__ = [
    "CoveragePriceRepository",
    "HistoricalDataCoverageAnalyzer",
    "HistoricalDataCoverageReport",
    "SymbolDataCoverage",
    "render_data_coverage_report",
]
