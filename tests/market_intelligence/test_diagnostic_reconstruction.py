from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from alpha.market_intelligence import (
    DIAGNOSTIC_MARKET_STATE_DATASET_VERSION,
    DiagnosticInputCompleteness,
    DiagnosticMarketStateReconstructionEngine,
    DiagnosticMarketStateRepository,
    build_diagnostic_market_state_coverage_report,
    build_no_lookahead_report,
    build_regime_comparison_report,
    render_diagnostic_coverage,
    render_regime_comparison,
)


def test_diagnostic_reconstruction_is_immutable() -> None:
    dataset = DiagnosticMarketStateReconstructionEngine().build(
        records=(_candidate("AAA", date(2026, 1, 5)),),
        outcomes=(),
        price_repository=_PriceRepository(_benchmark_bars(date(2026, 1, 5), 230)),
    )
    row = dataset.reconstructions[0]

    with pytest.raises(FrozenInstanceError):
        row.current_classifier_regime = "BULLISH"  # type: ignore[misc]


def test_reconstruction_id_is_deterministic_and_version_isolated() -> None:
    records = (_candidate("AAA", date(2026, 1, 5)),)
    repo = _PriceRepository(_benchmark_bars(date(2026, 1, 5), 230))

    first = DiagnosticMarketStateReconstructionEngine(
        dataset_version="diagnostic-v1"
    ).build(records=records, outcomes=(), price_repository=repo)
    second = DiagnosticMarketStateReconstructionEngine(
        dataset_version="diagnostic-v1"
    ).build(records=records, outcomes=(), price_repository=repo)
    third = DiagnosticMarketStateReconstructionEngine(
        dataset_version="diagnostic-v2"
    ).build(records=records, outcomes=(), price_repository=repo)

    assert (
        first.reconstructions[0].reconstruction_id
        == second.reconstructions[0].reconstruction_id
    )
    assert (
        first.reconstructions[0].reconstruction_id
        != third.reconstructions[0].reconstruction_id
    )


def test_dry_run_does_not_write_diagnostic_repository(tmp_path: Path) -> None:
    dataset = DiagnosticMarketStateReconstructionEngine().build(
        records=(_candidate("AAA", date(2026, 1, 5)),),
        outcomes=(),
        price_repository=_PriceRepository(_benchmark_bars(date(2026, 1, 5), 230)),
        dry_run=True,
    )
    path = tmp_path / "diagnostic.json"
    result = DiagnosticMarketStateRepository(path).save_dataset(dataset)

    assert result.dry_run is True
    assert not path.exists()


def test_explicit_persistence_is_idempotent_and_separate(tmp_path: Path) -> None:
    dataset = DiagnosticMarketStateReconstructionEngine().build(
        records=(_candidate("AAA", date(2026, 1, 5)),),
        outcomes=(),
        price_repository=_PriceRepository(_benchmark_bars(date(2026, 1, 5), 230)),
        dry_run=False,
    )
    repository = DiagnosticMarketStateRepository(tmp_path / "diagnostic.json")

    first = repository.save_dataset(dataset)
    second = repository.save_dataset(dataset)

    assert first.inserted_reconstructions == 1
    assert second.inserted_reconstructions == 0
    assert len(repository.load_reconstructions()) == 1
    assert repository.path.name == "diagnostic.json"


def test_future_benchmark_bar_is_excluded() -> None:
    market_date = date(2026, 1, 5)
    future_only = pd.DataFrame(
        [
            {
                "symbol": "NIFTYBEES",
                "trade_date": market_date + timedelta(days=1),
                "open": Decimal("100"),
                "high": Decimal("101"),
                "low": Decimal("99"),
                "close": Decimal("100"),
                "volume": Decimal("1000"),
                "sector": None,
                "exchange": "NSE",
            }
        ]
    )
    dataset = DiagnosticMarketStateReconstructionEngine().build(
        records=(_candidate("AAA", market_date),),
        outcomes=(),
        price_repository=_PriceRepository(future_only),
    )
    row = dataset.reconstructions[0]

    assert row.benchmark_latest_bar is None
    assert row.input_completeness is DiagnosticInputCompleteness.UNAVAILABLE
    assert build_no_lookahead_report(dataset.reconstructions).violations == 0


def test_build_does_not_mutate_candidate_rows() -> None:
    candidate = _candidate("AAA", date(2026, 1, 5))
    before = candidate.market_regime

    DiagnosticMarketStateReconstructionEngine().build(
        records=(candidate,),
        outcomes=(),
        price_repository=_PriceRepository(_benchmark_bars(date(2026, 1, 5), 230)),
    )

    assert candidate.market_regime == before


def test_coverage_and_regime_comparison_render_diagnostic_warning() -> None:
    candidate = _candidate("AAA", date(2026, 1, 5), market_regime="NEUTRAL")
    dataset = DiagnosticMarketStateReconstructionEngine().build(
        records=(candidate,),
        outcomes=(),
        price_repository=_PriceRepository(_benchmark_bars(date(2026, 1, 5), 230)),
    )
    coverage = build_diagnostic_market_state_coverage_report(dataset=dataset)
    comparison = build_regime_comparison_report(
        reconstructions=dataset.reconstructions,
        links=dataset.links,
        records=(candidate,),
        outcomes=(),
    )

    assert "Dataset Status: DIAGNOSTIC ONLY" in "\n".join(
        render_diagnostic_coverage(coverage)
    )
    assert "Dataset Status: DIAGNOSTIC ONLY" in "\n".join(
        render_regime_comparison(comparison)
    )
    assert coverage.dataset_version == DIAGNOSTIC_MARKET_STATE_DATASET_VERSION


class _Candidate:
    def __init__(
        self,
        symbol: str,
        evaluation_date: date,
        market_regime: str | None,
    ) -> None:
        self.candidate_id = f"{symbol}-{evaluation_date.isoformat()}"
        self.run_id = "run-1"
        self.evaluation_date = evaluation_date
        self.symbol = symbol
        self.final_verdict = "WATCHLIST"
        self.capital_action = "AVOID"
        self.approved_for_deployment = False
        self.setup_type = "MOMENTUM_CONTINUATION"
        self.market_regime = market_regime
        self.created_at = datetime.combine(
            evaluation_date,
            datetime.min.time(),
            tzinfo=UTC,
        )
        self.confirmation_entry = Decimal("100")
        self.classifier_version = None
        self.decision_provenance_id = None


def _candidate(
    symbol: str,
    evaluation_date: date,
    market_regime: str | None = "NEUTRAL",
) -> _Candidate:
    return _Candidate(symbol, evaluation_date, market_regime)


class _PriceRepository:
    def __init__(self, benchmark: pd.DataFrame) -> None:
        self.benchmark = benchmark

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        del limit
        frame = self.benchmark.copy()
        frame["symbol"] = frame["symbol"].astype(str).str.upper()
        return frame[frame["symbol"].isin([symbol.upper() for symbol in symbols])]

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        del trade_date
        return pd.DataFrame(
            columns=[
                "symbol",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "sector",
                "exchange",
            ]
        )


def _benchmark_bars(end: date, count: int) -> pd.DataFrame:
    rows = []
    start = end - timedelta(days=count - 1)
    for index in range(count):
        trade_date = start + timedelta(days=index)
        close = Decimal("100") + Decimal(index)
        rows.append(
            {
                "symbol": "NIFTYBEES",
                "trade_date": trade_date,
                "open": close,
                "high": close + Decimal("1"),
                "low": close - Decimal("1"),
                "close": close,
                "volume": Decimal("1000"),
                "sector": None,
                "exchange": "NSE",
            }
        )
    return pd.DataFrame(rows)
