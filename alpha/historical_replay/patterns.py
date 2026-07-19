from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

import pandas as pd

_ZERO = Decimal("0")
_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")
_TRADING_DAYS_PER_YEAR = 252


class PriceHistoryRepository(Protocol):
    def find_range_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame: ...


@dataclass(frozen=True, slots=True)
class PatternSnapshot:
    observed_on: date
    close: Decimal
    dma_20: Decimal | None
    dma_50: Decimal | None
    dma_200: Decimal | None
    close_vs_20_dma: Decimal | None
    close_vs_50_dma: Decimal | None
    close_vs_200_dma: Decimal | None
    dma_20_vs_50: Decimal | None
    dma_50_vs_200: Decimal | None
    return_20d: Decimal | None
    return_60d: Decimal | None
    volatility_20d: Decimal | None
    volume_ratio_20d: Decimal | None


@dataclass(frozen=True, slots=True)
class SimilarPatternMatch:
    observed_on: date
    similarity_score: Decimal
    close: Decimal
    forward_return_20d: Decimal
    max_gain_20d: Decimal
    max_drawdown_20d: Decimal
    snapshot: PatternSnapshot


@dataclass(frozen=True, slots=True)
class SimilarPatternReport:
    symbol: str
    requested_years: int
    available_bars: int
    expected_bars: int
    first_available_date: date | None
    last_available_date: date | None
    current_snapshot: PatternSnapshot | None
    matches: tuple[SimilarPatternMatch, ...]
    minimum_similarity: Decimal

    @property
    def has_full_requested_history(self) -> bool:
        return self.available_bars >= self.expected_bars

    @property
    def completed_matches(self) -> int:
        return len(self.matches)

    @property
    def win_rate(self) -> Decimal | None:
        if not self.matches:
            return None
        wins = sum(1 for match in self.matches if match.forward_return_20d > _ZERO)
        return _ratio_decimal(Decimal(wins), Decimal(len(self.matches)))

    @property
    def average_forward_return(self) -> Decimal | None:
        return _average(tuple(match.forward_return_20d for match in self.matches))

    @property
    def average_max_drawdown(self) -> Decimal | None:
        return _average(tuple(match.max_drawdown_20d for match in self.matches))


class SimilarPatternScanner:
    def __init__(self, *, price_repository: PriceHistoryRepository) -> None:
        self.price_repository = price_repository

    def scan(
        self,
        *,
        symbol: str,
        as_of: date,
        years: int = 10,
        minimum_similarity: Decimal = Decimal("70"),
        top: int = 10,
        forward_days: int = 20,
    ) -> SimilarPatternReport:
        if years <= 0:
            raise ValueError("years must be positive")
        if top <= 0:
            raise ValueError("top must be positive")
        if forward_days <= 0:
            raise ValueError("forward_days must be positive")
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol cannot be empty")

        start_date = as_of - timedelta(days=years * 366)
        frame = self.price_repository.find_range_by_symbols(
            symbols=(normalized_symbol,),
            start_date=start_date,
            end_date=as_of,
        )
        frame = _clean_frame(frame)
        expected_bars = years * _TRADING_DAYS_PER_YEAR
        if frame.empty:
            return SimilarPatternReport(
                symbol=normalized_symbol,
                requested_years=years,
                available_bars=0,
                expected_bars=expected_bars,
                first_available_date=None,
                last_available_date=None,
                current_snapshot=None,
                matches=(),
                minimum_similarity=minimum_similarity,
            )

        snapshots = _snapshots(frame)
        current_snapshot = snapshots[-1] if snapshots else None
        matches: list[SimilarPatternMatch] = []
        if current_snapshot is not None:
            for index, snapshot in enumerate(snapshots[:-forward_days]):
                if snapshot.observed_on >= current_snapshot.observed_on:
                    continue
                score = _similarity_score(current_snapshot, snapshot)
                if score < minimum_similarity:
                    continue
                forward = frame.iloc[index + 1 : index + 1 + forward_days]
                if len(forward) < forward_days:
                    continue
                matches.append(
                    _match(
                        snapshot=snapshot,
                        forward=forward,
                        similarity_score=score,
                    )
                )

        ranked = tuple(
            sorted(
                matches,
                key=lambda item: (
                    -item.similarity_score,
                    -item.forward_return_20d,
                    item.observed_on,
                ),
            )[:top]
        )
        first_date = frame["trade_date"].iloc[0]
        last_date = frame["trade_date"].iloc[-1]
        return SimilarPatternReport(
            symbol=normalized_symbol,
            requested_years=years,
            available_bars=len(frame),
            expected_bars=expected_bars,
            first_available_date=first_date,
            last_available_date=last_date,
            current_snapshot=current_snapshot,
            matches=ranked,
            minimum_similarity=minimum_similarity,
        )


def render_similar_pattern_report(report: SimilarPatternReport) -> tuple[str, ...]:
    lines = [
        "10-Year Similar Pattern Scan",
        f"Symbol: {report.symbol}",
        f"Requested Lookback: {report.requested_years} years",
        f"Available Bars: {report.available_bars}/{report.expected_bars}",
        (
            "Available Window: "
            f"{_date_text(report.first_available_date)} to "
            f"{_date_text(report.last_available_date)}"
        ),
        f"Minimum Similarity: {report.minimum_similarity} / 100",
    ]
    if not report.has_full_requested_history:
        lines.append(
            "Coverage Warning: local history does not yet cover the full requested "
            "10-year window."
        )
    if report.current_snapshot is None:
        lines.append("Current Pattern: unavailable; no local bars found.")
        return tuple(lines)
    snapshot = report.current_snapshot
    lines.extend(
        (
            "",
            "Current Pattern:",
            f"- Close: {_money(snapshot.close)} on {snapshot.observed_on.isoformat()}",
            (
                "- Moving averages: "
                f"20-DMA {_money(snapshot.dma_20)}, "
                f"50-DMA {_money(snapshot.dma_50)}, "
                f"200-DMA {_money(snapshot.dma_200)}"
            ),
            (
                "- Price position: "
                f"{_pct(snapshot.close_vs_20_dma)} vs 20-DMA, "
                f"{_pct(snapshot.close_vs_50_dma)} vs 50-DMA, "
                f"{_pct(snapshot.close_vs_200_dma)} vs 200-DMA"
            ),
            (
                "- Momentum/volume: "
                f"20-day return {_pct(snapshot.return_20d)}, "
                f"60-day return {_pct(snapshot.return_60d)}, "
                f"relative volume {_ratio_text(snapshot.volume_ratio_20d)}"
            ),
            "",
            "Historical Matches:",
        )
    )
    if not report.matches:
        lines.append("- none above similarity threshold")
        lines.append(
            "Conclusion: no statistically useful similar-pattern evidence is "
            "available from the currently persisted history."
        )
        return tuple(lines)
    lines.extend(
        (
            f"- Matches Found: {report.completed_matches}",
            f"- Win Rate: {_pct(report.win_rate)}",
            f"- Average 20-session Return: {_pct(report.average_forward_return)}",
            f"- Average Max Drawdown: {_pct(report.average_max_drawdown)}",
            "",
            "Top Matches:",
        )
    )
    for index, match in enumerate(report.matches, start=1):
        lines.append(
            f"{index}. {match.observed_on.isoformat()} | "
            f"similarity {match.similarity_score}/100 | "
            f"20-session return {_pct(match.forward_return_20d)} | "
            f"max gain {_pct(match.max_gain_20d)} | "
            f"max drawdown {_pct(match.max_drawdown_20d)}"
        )
    return tuple(lines)


def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    result = frame.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.date
    for column in ("open", "high", "low", "close", "volume"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.dropna(subset=["trade_date", "open", "high", "low", "close"])
    result = result[
        (result["open"] >= 0)
        & (result["high"] >= result["low"])
        & (result["close"] >= result["low"])
        & (result["close"] <= result["high"])
    ]
    return result.sort_values("trade_date").reset_index(drop=True)


def _date_value(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _snapshots(frame: pd.DataFrame) -> tuple[PatternSnapshot, ...]:
    closes = tuple(Decimal(str(value)) for value in frame["close"])
    volumes = tuple(Decimal(str(value)) for value in frame["volume"])
    snapshots: list[PatternSnapshot] = []
    for index, row in enumerate(frame.itertuples(index=False)):
        close = closes[index]
        dma_20 = _rolling_average(closes, index=index, window=20)
        dma_50 = _rolling_average(closes, index=index, window=50)
        dma_200 = _rolling_average(closes, index=index, window=200)
        volume_average_20 = _rolling_average(volumes, index=index, window=20)
        snapshots.append(
            PatternSnapshot(
                observed_on=_date_value(row.trade_date),
                close=close.quantize(_TWO, rounding=ROUND_HALF_UP),
                dma_20=_money_optional(dma_20),
                dma_50=_money_optional(dma_50),
                dma_200=_money_optional(dma_200),
                close_vs_20_dma=_relative(close, dma_20),
                close_vs_50_dma=_relative(close, dma_50),
                close_vs_200_dma=_relative(close, dma_200),
                dma_20_vs_50=_relative(dma_20, dma_50),
                dma_50_vs_200=_relative(dma_50, dma_200),
                return_20d=_lookback_return(closes, index=index, window=20),
                return_60d=_lookback_return(closes, index=index, window=60),
                volatility_20d=_volatility(closes, index=index, window=20),
                volume_ratio_20d=_ratio(
                    close=volumes[index],
                    reference=volume_average_20,
                ),
            )
        )
    return tuple(snapshots)


def _match(
    *,
    snapshot: PatternSnapshot,
    forward: pd.DataFrame,
    similarity_score: Decimal,
) -> SimilarPatternMatch:
    future_closes = tuple(Decimal(str(value)) for value in forward["close"])
    future_highs = tuple(Decimal(str(value)) for value in forward["high"])
    future_lows = tuple(Decimal(str(value)) for value in forward["low"])
    return SimilarPatternMatch(
        observed_on=snapshot.observed_on,
        similarity_score=similarity_score,
        close=snapshot.close,
        forward_return_20d=_relative(future_closes[-1], snapshot.close) or _ZERO,
        max_gain_20d=_relative(max(future_highs), snapshot.close) or _ZERO,
        max_drawdown_20d=_relative(min(future_lows), snapshot.close) or _ZERO,
        snapshot=snapshot,
    )


def _similarity_score(current: PatternSnapshot, historical: PatternSnapshot) -> Decimal:
    feature_pairs = (
        (current.close_vs_20_dma, historical.close_vs_20_dma, Decimal("0.08")),
        (current.close_vs_50_dma, historical.close_vs_50_dma, Decimal("0.12")),
        (current.close_vs_200_dma, historical.close_vs_200_dma, Decimal("0.18")),
        (current.dma_20_vs_50, historical.dma_20_vs_50, Decimal("0.08")),
        (current.dma_50_vs_200, historical.dma_50_vs_200, Decimal("0.12")),
        (current.return_20d, historical.return_20d, Decimal("0.15")),
        (current.return_60d, historical.return_60d, Decimal("0.25")),
        (current.volatility_20d, historical.volatility_20d, Decimal("0.12")),
        (current.volume_ratio_20d, historical.volume_ratio_20d, Decimal("2.00")),
    )
    penalties: list[Decimal] = []
    for left, right, tolerance in feature_pairs:
        if left is None or right is None:
            continue
        penalties.append(min(Decimal("1"), abs(left - right) / tolerance))
    if not penalties:
        return _ZERO
    average_penalty = sum(penalties, _ZERO) / Decimal(len(penalties))
    return max(_ZERO, Decimal("100") * (Decimal("1") - average_penalty)).quantize(
        _TWO,
        rounding=ROUND_HALF_UP,
    )


def _rolling_average(
    values: tuple[Decimal, ...],
    *,
    index: int,
    window: int,
) -> Decimal | None:
    if index + 1 < window:
        return None
    window_values = values[index + 1 - window : index + 1]
    return sum(window_values, _ZERO) / Decimal(window)


def _lookback_return(
    values: tuple[Decimal, ...],
    *,
    index: int,
    window: int,
) -> Decimal | None:
    if index < window:
        return None
    return _relative(values[index], values[index - window])


def _volatility(
    values: tuple[Decimal, ...],
    *,
    index: int,
    window: int,
) -> Decimal | None:
    if index < window:
        return None
    returns = tuple(
        _relative(values[item], values[item - 1])
        for item in range(index + 1 - window, index + 1)
    )
    clean = tuple(value for value in returns if value is not None)
    if len(clean) < window:
        return None
    average_return = sum(clean, _ZERO) / Decimal(len(clean))
    variance = sum((value - average_return) ** 2 for value in clean) / Decimal(
        len(clean)
    )
    return Decimal(str(float(variance) ** 0.5)).quantize(
        _FOUR,
        rounding=ROUND_HALF_UP,
    )


def _relative(value: Decimal | None, reference: Decimal | None) -> Decimal | None:
    if value is None or reference is None or reference <= _ZERO:
        return None
    return ((value - reference) / reference).quantize(_FOUR, rounding=ROUND_HALF_UP)


def _ratio(*, close: Decimal | None, reference: Decimal | None) -> Decimal | None:
    if close is None or reference is None or reference <= _ZERO:
        return None
    return (close / reference).quantize(_FOUR, rounding=ROUND_HALF_UP)


def _ratio_decimal(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator <= _ZERO:
        return None
    return (numerator / denominator).quantize(_FOUR, rounding=ROUND_HALF_UP)


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, _ZERO) / Decimal(len(values))).quantize(
        _FOUR,
        rounding=ROUND_HALF_UP,
    )


def _money_optional(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


def _date_text(value: date | None) -> str:
    return "unavailable" if value is None else value.isoformat()


def _money(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"₹{value}"


def _pct(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    return f"{(value * Decimal('100')).quantize(_TWO, rounding=ROUND_HALF_UP)}%"


def _ratio_text(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"{value}x"


__all__ = [
    "PatternSnapshot",
    "SimilarPatternMatch",
    "SimilarPatternReport",
    "SimilarPatternScanner",
    "render_similar_pattern_report",
]
