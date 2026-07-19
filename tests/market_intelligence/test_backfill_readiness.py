from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from alpha.market_intelligence.backfill_readiness import (
    BenchmarkDateAlignment,
    BenchmarkLookbackGapReason,
    ClassifierVersionReadiness,
    HistoricalBackfillConclusion,
    HistoricalBackfillNextMilestone,
    HistoricalBackfillStatus,
    HistoricalMarketStateBackfillReadinessEngine,
    ProxySuitability,
    render_backfill_readiness_report,
    render_benchmark_lookback_gaps,
    render_market_state_backfill_simulation,
)


@dataclass(frozen=True, slots=True)
class _Candidate:
    evaluation_date: date
    classifier_version: str | None = None


class _PriceRepository:
    def __init__(self, benchmark: pd.DataFrame, universe_size: int = 5) -> None:
        self.benchmark = benchmark
        self.universe_size = universe_size
        self.write_count = 0

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        del symbols
        frame = self.benchmark[self.benchmark["trade_date"] <= end_date]
        return frame.tail(limit).copy()

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        rows = [
            {
                "symbol": f"STOCK{index}",
                "trade_date": trade_date,
                "open": 100 + index,
                "high": 102 + index,
                "low": 99 + index,
                "close": 101 + index,
                "volume": 1000,
                "sector": "TEST",
                "exchange": "NSE",
            }
            for index in range(self.universe_size)
        ]
        return pd.DataFrame(rows)


def test_backfill_readiness_attributes_early_200dma_gap() -> None:
    benchmark = _benchmark_history(rows=220)
    early_date = benchmark.iloc[10]["trade_date"]
    later_date = benchmark.iloc[205]["trade_date"]
    report = HistoricalMarketStateBackfillReadinessEngine().analyze(
        records=(
            _Candidate(evaluation_date=early_date),
            _Candidate(evaluation_date=later_date),
        ),
        price_repository=_PriceRepository(benchmark),
    )

    early_gap = next(
        gap for gap in report.lookback_gaps if gap.market_date == early_date
    )
    later_row = next(
        row for row in report.date_reconciliation if row.market_date == later_date
    )

    assert (
        early_gap.reason is BenchmarkLookbackGapReason.EXPECTED_EARLY_HISTORY_LIMITATION
    )
    assert later_row.dma_200_available is True
    assert report.source_integrity.first_200dma_ready_date is not None


def test_backfill_blocks_authoritative_replay_without_classifier_lineage() -> None:
    benchmark = _benchmark_history(rows=220)
    report = HistoricalMarketStateBackfillReadinessEngine().analyze(
        records=(_Candidate(evaluation_date=benchmark.iloc[205]["trade_date"]),),
        price_repository=_PriceRepository(benchmark),
    )

    assert (
        report.primary_conclusion
        is HistoricalBackfillConclusion.CLASSIFIER_VERSION_LINEAGE_IS_PRIMARY_BOTTLENECK
    )
    assert (
        report.recommended_next_milestone
        is HistoricalBackfillNextMilestone.ADD_CLASSIFIER_VERSION_LINEAGE
    )
    assert (
        report.classifier_version_readiness.readiness
        is ClassifierVersionReadiness.VERSION_UNKNOWN
    )


def test_backfill_simulation_is_no_write_and_partial_only() -> None:
    benchmark = _benchmark_history(rows=220)
    repository = _PriceRepository(benchmark)
    report = HistoricalMarketStateBackfillReadinessEngine().analyze(
        records=(_Candidate(evaluation_date=benchmark.iloc[205]["trade_date"]),),
        price_repository=repository,
    )
    row = report.simulation_plan.rows[0]

    assert row.backfill_status is HistoricalBackfillStatus.READY_PARTIAL
    assert row.would_create_snapshot is True
    assert row.classifier_replay_available is False
    assert "classifier_version" in row.expected_missing_fields
    assert repository.write_count == 0
    rendered = "\n".join(
        render_market_state_backfill_simulation(report.simulation_plan)
    )
    assert "Dry Run: yes" in rendered
    assert "never writes" in rendered


def test_benchmark_date_reconciliation_uses_only_past_bars() -> None:
    benchmark = _benchmark_history(rows=30)
    candidate_date = date(2024, 2, 10)
    report = HistoricalMarketStateBackfillReadinessEngine().analyze(
        records=(_Candidate(evaluation_date=candidate_date),),
        price_repository=_PriceRepository(benchmark),
    )
    row = report.date_reconciliation[0]

    assert row.latest_benchmark_bar is not None
    assert row.latest_benchmark_bar <= candidate_date
    assert row.alignment is BenchmarkDateAlignment.VALID_CARRIED_FORWARD
    assert row.bars_available == len(benchmark)


def test_proxy_suitability_keeps_niftybees_as_etf_proxy() -> None:
    benchmark = _benchmark_history(rows=220)
    report = HistoricalMarketStateBackfillReadinessEngine().analyze(
        records=(_Candidate(evaluation_date=benchmark.iloc[205]["trade_date"]),),
        price_repository=_PriceRepository(benchmark),
    )

    assert report.proxy_suitability.provider_symbol == "NIFTYBEES"
    assert report.proxy_suitability.asset_type == "ETF"
    assert (
        report.proxy_suitability.suitability
        is ProxySuitability.SUITABLE_WITH_LIMITATIONS
    )
    assert report.proxy_suitability.acceptable_for_authoritative_backfill is False


def test_backfill_readiness_rendering_includes_prohibited_action() -> None:
    benchmark = _benchmark_history(rows=220)
    report = HistoricalMarketStateBackfillReadinessEngine().analyze(
        records=(_Candidate(evaluation_date=benchmark.iloc[205]["trade_date"]),),
        price_repository=_PriceRepository(benchmark),
        group_by="year",
    )
    rendered = "\n".join(render_backfill_readiness_report(report, group_by="year"))
    gaps = "\n".join(render_benchmark_lookback_gaps(report.lookback_gaps))

    assert "Historical Market-State Backfill Readiness" in rendered
    assert "Explicitly Prohibited Next Action" in rendered
    assert "Readiness By Year" in rendered
    assert "No benchmark 200-DMA gaps found." in gaps


def _benchmark_history(*, rows: int) -> pd.DataFrame:
    dates = pd.bdate_range(start="2024-01-01", periods=rows)
    data = []
    for index, item in enumerate(dates):
        value = 100 + index
        data.append(
            {
                "symbol": "NIFTYBEES",
                "trade_date": item.date(),
                "open": value,
                "high": value + 1,
                "low": value - 1,
                "close": value,
                "volume": 1000,
                "sector": None,
                "exchange": "NSE",
            }
        )
    return pd.DataFrame(data)
