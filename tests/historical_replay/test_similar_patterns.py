from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pandas as pd

from alpha.historical_replay import (
    SimilarPatternScanner,
    render_similar_pattern_report,
)


class FakePriceRepository:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def find_range_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        del symbols
        frame = self.frame.copy()
        return frame[
            (frame["trade_date"] >= start_date) & (frame["trade_date"] <= end_date)
        ]


def test_similar_pattern_scan_reports_matches_and_forward_outcomes() -> None:
    frame = _price_frame(days=320)

    report = SimilarPatternScanner(
        price_repository=FakePriceRepository(frame),
    ).scan(
        symbol="AAA",
        as_of=date(2026, 1, 1) + timedelta(days=319),
        years=10,
        minimum_similarity=Decimal("50"),
        top=5,
    )

    assert report.symbol == "AAA"
    assert report.available_bars == 320
    assert report.has_full_requested_history is False
    assert report.current_snapshot is not None
    assert report.matches
    assert report.matches[0].forward_return_20d is not None


def test_similar_pattern_rendering_explains_coverage_gap() -> None:
    report = SimilarPatternScanner(
        price_repository=FakePriceRepository(_price_frame(days=260)),
    ).scan(
        symbol="AAA",
        as_of=date(2026, 1, 1) + timedelta(days=259),
        years=10,
        minimum_similarity=Decimal("95"),
        top=3,
    )

    output = "\n".join(render_similar_pattern_report(report))

    assert "10-Year Similar Pattern Scan" in output
    assert "Available Bars: 260/2520" in output
    assert "Coverage Warning" in output
    assert "Current Pattern:" in output


def _price_frame(*, days: int) -> pd.DataFrame:
    start = date(2026, 1, 1)
    rows: list[dict[str, object]] = []
    for offset in range(days):
        cycle = offset % 80
        close = Decimal("100") + Decimal(cycle) * Decimal("0.40")
        high = close + Decimal("1")
        low = close - Decimal("1")
        rows.append(
            {
                "symbol": "AAA",
                "trade_date": start + timedelta(days=offset),
                "open": close - Decimal("0.25"),
                "high": high,
                "low": low,
                "close": close,
                "volume": Decimal("100000") + Decimal(cycle * 100),
                "sector": "TEST",
                "exchange": "NSE",
            }
        )
    return pd.DataFrame(rows)
