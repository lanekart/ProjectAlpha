from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from alpha.application.intelligence_inputs import (
    DemoIntelligenceInputBuilder,
    IntelligenceInputBuilder,
)
from alpha.recommendation_intelligence import RecommendationAction


def test_demo_intelligence_input_builder_preserves_fixture_contract() -> None:
    inputs = DemoIntelligenceInputBuilder().build(observed_on=date(2026, 1, 30))

    assert inputs.stock.symbol == "HAL"
    assert inputs.breadth.advances == 1220
    assert [candidate.symbol for candidate in inputs.recommendation_candidates] == [
        "HAL",
        "BEL",
        "LT",
    ]
    assert inputs.recommendation_portfolio_context.existing_symbols == ("LT",)
    assert inputs.allocation_portfolio_context.available_cash == Decimal("300000")


def test_intelligence_input_builder_builds_inputs_from_analysis_frame() -> None:
    inputs = IntelligenceInputBuilder().build(
        observed_on=date(2026, 7, 7),
        analysis=_analysis_frame(),
    )

    assert inputs.stock.symbol == "AAA"
    assert inputs.stock.observed_on == date(2026, 7, 7)
    assert inputs.breadth.advances == 2
    assert inputs.breadth.declines == 1
    assert inputs.sectors[0].sector == "BANKS"
    assert [candidate.symbol for candidate in inputs.recommendation_candidates] == [
        "AAA",
        "CCC",
        "BBB",
    ]
    assert inputs.recommendation_candidates[0].action is RecommendationAction.BUY
    assert inputs.sector_by_symbol["AAA"] == "BANKS"
    assert inputs.liquidity_by_symbol["CCC"] == Decimal("1")


def test_intelligence_input_builder_uses_persisted_price_history() -> None:
    repository = _FakePriceRepository(_history_frame("AAA", bars=75))

    inputs = IntelligenceInputBuilder(
        price_repository=repository,
        history_window=60,
    ).build(
        observed_on=date(2026, 7, 7),
        analysis=_analysis_frame(),
    )
    candidate_by_symbol = {
        candidate.symbol: candidate for candidate in inputs.recommendation_candidates
    }

    assert repository.calls == [("AAA", "BBB", "CCC", date(2026, 7, 7), 60)]
    assert len(candidate_by_symbol["AAA"].price_history) == 60
    assert candidate_by_symbol["AAA"].metadata["historical_bars"] == "60"
    assert "average_volume" in candidate_by_symbol["AAA"].metadata


def test_intelligence_input_builder_defaults_to_five_year_history() -> None:
    repository = _FakePriceRepository(_history_frame("AAA", bars=1260))

    inputs = IntelligenceInputBuilder(price_repository=repository).build(
        observed_on=date(2026, 7, 7),
        analysis=_analysis_frame(),
    )

    assert repository.calls == [("AAA", "BBB", "CCC", date(2026, 7, 7), 1260)]
    assert inputs.recommendation_candidates[0].metadata["historical_bars"] == "1260"


def test_intelligence_input_set_builds_allocation_candidates() -> None:
    inputs = DemoIntelligenceInputBuilder().build(observed_on=date(2026, 1, 30))

    from alpha.recommendation_intelligence import RecommendationEngine

    reports = RecommendationEngine().build(
        inputs.recommendation_candidates,
        portfolio=inputs.recommendation_portfolio_context,
    )
    allocation_candidates = inputs.allocation_candidates(reports)

    assert [candidate.symbol for candidate in allocation_candidates] == [
        "HAL",
        "LT",
        "BEL",
    ]
    assert allocation_candidates[0].sector == "DEFENCE"


def test_intelligence_input_builder_rejects_missing_required_columns() -> None:
    with pytest.raises(ValueError, match="analysis frame missing required columns"):
        IntelligenceInputBuilder().build(
            observed_on=date(2026, 7, 7),
            analysis=pd.DataFrame({"symbol": ["AAA"]}),
        )


def test_intelligence_input_builder_normalizes_missing_sector_to_unknown() -> None:
    frame = _analysis_frame()
    frame["sector"] = [None, None, None]

    inputs = IntelligenceInputBuilder().build(
        observed_on=date(2026, 7, 7),
        analysis=frame,
    )

    assert inputs.sectors[0].sector == "UNKNOWN"
    assert inputs.sector_by_symbol["AAA"] == "UNKNOWN"


def test_intelligence_input_builder_calibrates_raw_alpha_scores() -> None:
    frame = _analysis_frame()
    frame["alpha_score"] = [0.30, -0.04, 0.03]
    frame["signal"] = ["BUY", "SELL", "BUY"]

    inputs = IntelligenceInputBuilder().build(
        observed_on=date(2026, 7, 7),
        analysis=frame,
    )
    candidates = {
        candidate.symbol: candidate for candidate in inputs.recommendation_candidates
    }

    assert candidates["AAA"].strategy_score == Decimal("1.0000")
    assert candidates["CCC"].strategy_score == Decimal("0.4000")
    assert candidates["BBB"].strategy_score == Decimal("0.0000")


def test_intelligence_input_builder_prefers_stronger_buy_candidates() -> None:
    frame = _selection_frame()

    inputs = IntelligenceInputBuilder().build(
        observed_on=date(2026, 7, 7),
        analysis=frame,
    )

    assert [candidate.action for candidate in inputs.recommendation_candidates] == [
        RecommendationAction.BUY
    ] * 10
    assert {candidate.symbol for candidate in inputs.recommendation_candidates} == {
        f"BUY{i:02d}" for i in range(1, 11)
    }
    assert inputs.recommendation_candidates[0].strategy_score >= Decimal("0.60")


def test_intelligence_input_builder_softens_volatility_cliff() -> None:
    frame = _analysis_frame()
    frame["alpha_score"] = [0.30, 0.20, 0.10]
    frame["volatility"] = [0.081, 0.10, 0.20]
    frame["volume"] = [1000, 1000, 1000]
    frame["liquidity"] = [1000, 1000, 1000]
    frame["correlation_to_index"] = [0.50, 0.50, 0.50]

    inputs = IntelligenceInputBuilder().build(
        observed_on=date(2026, 7, 7),
        analysis=frame,
    )
    candidates = {
        candidate.symbol: candidate for candidate in inputs.recommendation_candidates
    }

    assert candidates["AAA"].risk_score > candidates["BBB"].risk_score
    assert candidates["BBB"].risk_score > candidates["CCC"].risk_score


def _analysis_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"],
            "sector": ["BANKS", "IT", "BANKS"],
            "open": [100.0, 100.0, 100.0],
            "close": [110.0, 90.0, 105.0],
            "volume": [1000, 500, 1500],
            "momentum_1d": [0.10, -0.10, 0.05],
            "volatility": [0.12, 0.08, 0.10],
            "liquidity": [1000, 500, 1500],
            "alpha_score": [0.85, 0.35, 0.65],
            "rank": [1, 3, 2],
            "signal": ["BUY", "SELL", "BUY"],
            "correlation_to_index": [0.30, 0.60, 0.40],
            "correlation_to_sector": [0.35, 0.65, 0.45],
        }
    )


class _FakePriceRepository:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame
        self.calls: list[tuple[object, ...]] = []

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        self.calls.append((*symbols, end_date, limit))
        return self._frame.groupby("symbol", group_keys=False).tail(limit)


def _history_frame(symbol: str, *, bars: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": [symbol] * bars,
            "trade_date": [
                date.fromordinal(date(2026, 1, 1).toordinal() + index)
                for index in range(bars)
            ],
            "open": [100 + index for index in range(bars)],
            "high": [102 + index for index in range(bars)],
            "low": [99 + index for index in range(bars)],
            "close": [101 + index for index in range(bars)],
            "volume": [100000 + (index * 1000) for index in range(bars)],
            "sector": ["BANKS"] * bars,
            "exchange": ["NSE"] * bars,
        }
    )


def _selection_frame() -> pd.DataFrame:
    rows = [
        {
            "symbol": "HOLD_TOP",
            "sector": "IT",
            "open": 100.0,
            "close": 102.0,
            "volume": 10000,
            "momentum_1d": 0.02,
            "volatility": 0.05,
            "liquidity": 10000,
            "alpha_score": 0.90,
            "rank": 1,
            "signal": "HOLD",
            "correlation_to_index": 0.35,
            "correlation_to_sector": 0.40,
        },
        {
            "symbol": "SELL_TOP",
            "sector": "IT",
            "open": 100.0,
            "close": 102.0,
            "volume": 10000,
            "momentum_1d": 0.02,
            "volatility": 0.05,
            "liquidity": 10000,
            "alpha_score": 0.80,
            "rank": 2,
            "signal": "SELL",
            "correlation_to_index": 0.35,
            "correlation_to_sector": 0.40,
        },
    ]
    rows.extend(
        {
            "symbol": f"BUY{i:02d}",
            "sector": "BANKS" if i % 2 else "CAPITAL GOODS",
            "open": 100.0,
            "close": 105.0 + i,
            "volume": 9000 + i,
            "momentum_1d": 0.04 + (i * 0.002),
            "volatility": 0.04,
            "liquidity": 9000 + i,
            "alpha_score": 0.10 + (i * 0.005),
            "rank": i + 2,
            "signal": "BUY",
            "correlation_to_index": 0.40,
            "correlation_to_sector": 0.45,
        }
        for i in range(1, 11)
    )
    return pd.DataFrame(rows)
