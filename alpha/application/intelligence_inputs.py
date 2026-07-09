from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Protocol, cast

import pandas as pd

from alpha.application.data_completeness import DataCompletenessEngine
from alpha.market_intelligence import (
    CorrelationInput,
    MarketBreadthInput,
    SectorPerformanceInput,
    StockIntelligenceInput,
)
from alpha.portfolio_intelligence import (
    AllocationCandidate,
    RiskBudget,
    SectorExposure,
)
from alpha.portfolio_intelligence import (
    PortfolioContext as AllocationPortfolioContext,
)
from alpha.recommendation_intelligence import (
    OHLCVBar,
    RecommendationAction,
    RecommendationCandidate,
    RecommendationEvidence,
    RecommendationReport,
    RecommendationRisk,
    TradeStrategyAction,
)
from alpha.recommendation_intelligence import (
    PortfolioContext as RecommendationPortfolioContext,
)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")
_DEFAULT_SECTOR = "UNKNOWN"

_SECTOR_COLUMNS = (
    "sector",
    "industry",
    "macro_sector",
    "sector_name",
    "industry_group",
)
_POSITIVE_MOMENTUM_REFERENCE = Decimal("0.06")
_STRONG_MOMENTUM_REFERENCE = Decimal("0.10")
_ACCEPTABLE_VOLATILITY_REFERENCE = Decimal("0.08")
_EXPECTED_RETURN_FLOOR = Decimal("0.01")
_EXPECTED_DRAWDOWN_FLOOR = Decimal("0.01")
_DEFAULT_HISTORY_WINDOW = 250
_SUPPORTED_HISTORY_WINDOWS = frozenset({60, 120, 250})


class HistoricalPriceRepository(Protocol):
    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        """Return chronological OHLCV rows for the requested symbols."""
        ...


@dataclass(frozen=True, slots=True)
class IntelligenceInputSet:
    """
    Canonical adapter output consumed by the intelligence orchestration service.

    This object deliberately contains engine-ready inputs rather than raw
    DataFrames. It is the seam between market analysis / fixtures and the
    deterministic intelligence engines.
    """

    stock: StockIntelligenceInput
    breadth: MarketBreadthInput
    sectors: tuple[SectorPerformanceInput, ...]
    correlation: CorrelationInput
    recommendation_candidates: tuple[RecommendationCandidate, ...]
    recommendation_portfolio_context: RecommendationPortfolioContext
    allocation_portfolio_context: AllocationPortfolioContext
    sector_by_symbol: Mapping[str, str]
    correlation_by_symbol: Mapping[str, Decimal]
    liquidity_by_symbol: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        if not self.sectors:
            raise ValueError("intelligence inputs require at least one sector")
        if not self.recommendation_candidates:
            raise ValueError("intelligence inputs require at least one recommendation")

        sector_by_symbol = _normalize_symbol_sector(self.sector_by_symbol)
        correlation_by_symbol = _normalize_decimal_mapping(self.correlation_by_symbol)
        liquidity_by_symbol = _normalize_decimal_mapping(self.liquidity_by_symbol)

        object.__setattr__(self, "sectors", tuple(self.sectors))
        object.__setattr__(
            self,
            "recommendation_candidates",
            tuple(self.recommendation_candidates),
        )
        object.__setattr__(self, "sector_by_symbol", sector_by_symbol)
        object.__setattr__(self, "correlation_by_symbol", correlation_by_symbol)
        object.__setattr__(self, "liquidity_by_symbol", liquidity_by_symbol)

    def allocation_candidates(
        self,
        recommendations: Iterable[RecommendationReport],
    ) -> tuple[AllocationCandidate, ...]:
        """
        Convert recommendation reports into portfolio-intelligence candidates.
        """

        return tuple(
            AllocationCandidate(
                symbol=recommendation.symbol,
                sector=self.sector_by_symbol.get(
                    recommendation.symbol,
                    _DEFAULT_SECTOR,
                ),
                observed_on=recommendation.observed_on,
                recommendation_score=recommendation.score,
                success_probability=recommendation.expected_value.score,
                expected_return=recommendation.expected_value.expected_return,
                expected_drawdown=recommendation.expected_value.expected_drawdown,
                correlation_to_portfolio=self.correlation_by_symbol.get(
                    recommendation.symbol,
                    Decimal("0.50"),
                ),
                liquidity_score=self.liquidity_by_symbol.get(
                    recommendation.symbol,
                    Decimal("0.60"),
                ),
                conviction_score=recommendation.score / _HUNDRED,
                metadata={
                    "source": "recommendation_intelligence",
                    "trade_plan_valid": str(_has_deployable_trade_plan(recommendation)),
                    "actionable_strategy_action": _actionable_strategy_action(
                        recommendation
                    ),
                },
                recommendation_action=recommendation.action.value,
                final_signal=recommendation.final_signal,
            )
            for recommendation in recommendations
        )


class IntelligenceInputBuilder:
    """
    Build deterministic intelligence inputs from a market-analysis DataFrame.

    This adapter intentionally keeps the existing intelligence engines unchanged.
    It translates analyzed market data into:
    - market intelligence inputs
    - recommendation candidates
    - recommendation portfolio context
    - allocation portfolio context

    Required live columns are intentionally minimal and aligned with the current
    analytical pipeline:
    symbol, open, close, volume, momentum_1d, volatility, liquidity,
    alpha_score, rank, signal.

    Optional columns improve quality when present:
    sector, high, low, delivery_percent, delivery_change_percent,
    volume_change_percent, turnover_value, average_turnover_value,
    spread_percent, correlation_to_index, correlation_to_sector.
    """

    def __init__(
        self,
        *,
        price_repository: HistoricalPriceRepository | None = None,
        history_window: int = _DEFAULT_HISTORY_WINDOW,
    ) -> None:
        if history_window not in _SUPPORTED_HISTORY_WINDOWS:
            raise ValueError("history window must be one of 60, 120, or 250 bars")
        self._price_repository = price_repository
        self._history_window = history_window

    def build(
        self,
        *,
        observed_on: date,
        analysis: pd.DataFrame,
    ) -> IntelligenceInputSet:
        frame = _prepare_frame(analysis)
        sector_by_symbol = _sector_by_symbol(frame)
        liquidity_by_symbol = _liquidity_by_symbol(frame)
        correlation_by_symbol = _correlation_by_symbol(frame)
        sector_strength_by_sector = _sector_strength_by_sector(frame)
        strategy_score_by_symbol = _strategy_score_by_symbol(frame)
        price_history_by_symbol = self._price_history_by_symbol(
            frame=frame,
            observed_on=observed_on,
        )
        frame = _ranked_quality_frame(
            frame=frame,
            strategy_score_by_symbol=strategy_score_by_symbol,
            liquidity_by_symbol=liquidity_by_symbol,
            correlation_by_symbol=correlation_by_symbol,
            sector_strength_by_sector=sector_strength_by_sector,
        )
        leader = _leader(frame)

        recommendation_candidates = self._recommendation_candidates(
            observed_on=observed_on,
            frame=frame,
            sector_by_symbol=sector_by_symbol,
            strategy_score_by_symbol=strategy_score_by_symbol,
            liquidity_by_symbol=liquidity_by_symbol,
            correlation_by_symbol=correlation_by_symbol,
            sector_strength_by_sector=sector_strength_by_sector,
            price_history_by_symbol=price_history_by_symbol,
        )

        return IntelligenceInputSet(
            stock=self._stock_input(observed_on=observed_on, row=leader),
            breadth=self._breadth_input(observed_on=observed_on, frame=frame),
            sectors=self._sector_inputs(frame),
            correlation=self._correlation_input(row=leader),
            recommendation_candidates=recommendation_candidates,
            recommendation_portfolio_context=self._recommendation_portfolio_context(
                sector_by_symbol=sector_by_symbol
            ),
            allocation_portfolio_context=self._allocation_portfolio_context(frame),
            sector_by_symbol=sector_by_symbol,
            correlation_by_symbol=correlation_by_symbol,
            liquidity_by_symbol=liquidity_by_symbol,
        )

    def _stock_input(
        self,
        *,
        observed_on: date,
        row: Mapping[str, Any],
    ) -> StockIntelligenceInput:
        price_change_percent = _percent_from_fraction(_decimal(row["momentum_1d"]))
        volatility_percent = _percent_from_fraction(_decimal(row["volatility"]))
        turnover_value = _turnover_value(row)
        average_turnover_value = _decimal(
            row.get("average_turnover_value", turnover_value)
        )

        return StockIntelligenceInput(
            symbol=str(row["symbol"]),
            observed_on=observed_on,
            price_change_percent=price_change_percent,
            delivery_percent=_bounded_percent(
                _decimal(row.get("delivery_percent", Decimal("50")))
            ),
            delivery_change_percent=_decimal(
                row.get("delivery_change_percent", price_change_percent)
            ),
            volume_change_percent=_decimal(
                row.get("volume_change_percent", _turnover_change_percent(row))
            ),
            turnover_value=turnover_value,
            average_turnover_value=average_turnover_value,
            spread_percent=_decimal(row.get("spread_percent", Decimal("0.50"))),
            volatility_percent=volatility_percent,
        )

    def _breadth_input(
        self,
        *,
        observed_on: date,
        frame: pd.DataFrame,
    ) -> MarketBreadthInput:
        momentum = frame["momentum_1d"]
        advances = int((momentum > 0).sum())
        declines = int((momentum < 0).sum())
        unchanged = int((momentum == 0).sum())

        return MarketBreadthInput(
            observed_on=observed_on,
            advances=advances,
            declines=declines,
            unchanged=unchanged,
        )

    def _sector_inputs(self, frame: pd.DataFrame) -> tuple[SectorPerformanceInput, ...]:
        grouped = frame.groupby("sector", sort=True, dropna=False)
        sectors: list[SectorPerformanceInput] = []

        for sector, sector_frame in grouped:
            momentum = sector_frame["momentum_1d"]
            turnover = sector_frame["turnover_value"]

            average_return = _decimal(momentum.mean())
            breadth_percent = Decimal(str((momentum > 0).mean())) * _HUNDRED
            denominator = max(
                _decimal(sector_frame["average_turnover_value"].sum()),
                Decimal("1"),
            )

            turnover_ratio = turnover.sum() / denominator
            turnover_change_percent = (turnover_ratio - _ONE) * _HUNDRED

            sectors.append(
                SectorPerformanceInput(
                    sector=str(sector),
                    return_percent=_percent_from_fraction(average_return),
                    breadth_percent=_bounded_percent(breadth_percent),
                    turnover_change_percent=turnover_change_percent,
                )
            )

        return tuple(
            sorted(
                sectors,
                key=lambda item: (
                    -item.return_percent,
                    item.sector,
                ),
            )
        )

    def _correlation_input(self, *, row: Mapping[str, Any]) -> CorrelationInput:
        return CorrelationInput(
            symbol=str(row["symbol"]),
            correlation_to_index=_bounded_correlation(
                _decimal(row.get("correlation_to_index", Decimal("0.50")))
            ),
            correlation_to_sector=_bounded_correlation(
                _decimal(row.get("correlation_to_sector", Decimal("0.50")))
            ),
        )

    def _recommendation_candidates(
        self,
        *,
        observed_on: date,
        frame: pd.DataFrame,
        sector_by_symbol: Mapping[str, str],
        strategy_score_by_symbol: Mapping[str, Decimal],
        liquidity_by_symbol: Mapping[str, Decimal],
        correlation_by_symbol: Mapping[str, Decimal],
        sector_strength_by_sector: Mapping[str, Decimal],
        price_history_by_symbol: Mapping[str, tuple[OHLCVBar, ...]],
    ) -> tuple[RecommendationCandidate, ...]:
        records = cast(
            list[dict[str, Any]],
            frame.sort_values(
                ["candidate_quality_score", "rank", "symbol"],
                ascending=[False, True, True],
            )
            .head(10)
            .to_dict("records"),
        )

        candidates: list[RecommendationCandidate] = []
        for record in records:
            symbol = str(record["symbol"]).strip().upper()
            sector = sector_by_symbol.get(symbol, _DEFAULT_SECTOR)
            strategy_score = strategy_score_by_symbol.get(symbol, _ZERO)
            momentum_score = _momentum_quality(_decimal(record["momentum_1d"]))
            turnover_score = _turnover_quality(record)
            liquidity_score = liquidity_by_symbol.get(symbol, Decimal("0.60"))
            correlation = correlation_by_symbol.get(symbol, Decimal("0.50"))
            sector_strength = sector_strength_by_sector.get(sector, Decimal("0.50"))
            volatility = _decimal(record["volatility"])
            price_history = price_history_by_symbol.get(symbol, ())
            data_completion = DataCompletenessEngine().assess(price_history)
            drawdown_quality = _drawdown_quality(volatility)
            signal_quality = _signal_quality(str(record["signal"]))

            probability_score = _bounded_ratio(
                strategy_score * Decimal("0.32")
                + momentum_score * Decimal("0.22")
                + sector_strength * Decimal("0.16")
                + liquidity_score * Decimal("0.12")
                + drawdown_quality * Decimal("0.10")
                + signal_quality * Decimal("0.08")
            )
            risk_score = _bounded_ratio(
                drawdown_quality * Decimal("0.55")
                + _correlation_quality(correlation) * Decimal("0.30")
                + liquidity_score * Decimal("0.15")
            )
            market_intelligence_score = _bounded_ratio(
                sector_strength * Decimal("0.35")
                + momentum_score * Decimal("0.22")
                + turnover_score * Decimal("0.18")
                + liquidity_score * Decimal("0.15")
                + risk_score * Decimal("0.10")
            )
            expected_return = _expected_return(record, strategy_score, sector_strength)
            expected_drawdown = _expected_drawdown(record, risk_score)

            candidates.append(
                RecommendationCandidate(
                    symbol=symbol,
                    observed_on=observed_on,
                    action=_action_from_signal(str(record["signal"])),
                    strategy_score=strategy_score,
                    probability_score=probability_score,
                    market_intelligence_score=market_intelligence_score,
                    liquidity_score=liquidity_score,
                    risk_score=risk_score,
                    expected_return=expected_return,
                    expected_drawdown=expected_drawdown,
                    expected_holding_period_days=_expected_holding_period_days(
                        strategy_score,
                        volatility,
                    ),
                    evidence=(
                        RecommendationEvidence(
                            label="Alpha Signal",
                            score_points=(strategy_score * Decimal("25")).quantize(
                                Decimal("0.01")
                            ),
                            max_points=Decimal("25"),
                            rationale=(
                                "candidate selected from the canonical alpha "
                                "ranking and signal pipeline"
                            ),
                        ),
                        RecommendationEvidence(
                            label="Market Participation",
                            score_points=(
                                market_intelligence_score * Decimal("25")
                            ).quantize(Decimal("0.01")),
                            max_points=Decimal("25"),
                            rationale=(
                                "market participation reflects sector strength, "
                                "momentum, liquidity, turnover, and risk quality"
                            ),
                        ),
                    ),
                    risks=(
                        RecommendationRisk(
                            label="Market Volatility",
                            penalty_points=(
                                min(expected_drawdown, Decimal("0.20")) * Decimal("20")
                            ).quantize(Decimal("0.01")),
                            rationale=(
                                "position sizing should reflect observed "
                                "volatility and correlation risk"
                            ),
                        ),
                    ),
                    metadata={
                        "source": "intelligence_input_builder",
                        "sector": sector,
                        "historical_bars": str(len(price_history)),
                        "data_quality": data_completion.status,
                        "data_fetch_attempted": str(data_completion.fetch_attempted),
                        **_volume_metadata(record, price_history),
                    },
                    price_history=price_history,
                    open_price=_optional_record_decimal(record, "open"),
                    high_price=_optional_record_decimal(record, "high"),
                    low_price=_optional_record_decimal(record, "low"),
                    current_price=_optional_record_decimal(record, "close"),
                )
            )

        return tuple(candidates)

    def _price_history_by_symbol(
        self,
        *,
        frame: pd.DataFrame,
        observed_on: date,
    ) -> Mapping[str, tuple[OHLCVBar, ...]]:
        symbols = tuple(str(symbol).strip().upper() for symbol in frame["symbol"])
        if self._price_repository is not None:
            history_frame = self._price_repository.find_history_by_symbols(
                symbols=symbols,
                end_date=observed_on,
                limit=self._history_window,
            )
            if not history_frame.empty:
                return _price_history_by_symbol(history_frame, observed_on)
        return _price_history_by_symbol(frame, observed_on)

    def _recommendation_portfolio_context(
        self,
        *,
        sector_by_symbol: Mapping[str, str],
    ) -> RecommendationPortfolioContext:
        sector_exposure = {
            sector: Decimal("0")
            for sector in sorted(set(sector_by_symbol.values()))
            if sector
        }

        return RecommendationPortfolioContext(
            existing_symbols=(),
            sector_exposure=sector_exposure,
            symbol_sector=sector_by_symbol,
            max_single_position_percent=Decimal("10"),
            max_sector_exposure_percent=Decimal("25"),
        )

    def _allocation_portfolio_context(
        self,
        frame: pd.DataFrame,
    ) -> AllocationPortfolioContext:
        sector_exposures = tuple(
            SectorExposure(
                sector=str(sector),
                current_weight=Decimal("0"),
            )
            for sector in sorted(frame["sector"].dropna().unique())
        )

        return AllocationPortfolioContext(
            total_capital=Decimal("1000000"),
            available_cash=Decimal("300000"),
            current_positions={},
            sector_exposures=sector_exposures,
            risk_budget=RiskBudget(
                max_position_weight=Decimal("0.10"),
                max_sector_weight=Decimal("0.25"),
                max_correlation=Decimal("0.75"),
                max_portfolio_risk_weight=Decimal("0.35"),
                min_recommendation_score=Decimal("50"),
            ),
        )


class DemoIntelligenceInputBuilder:
    """
    Deterministic fixture adapter retained for tests and demos.

    Production wiring can use IntelligenceInputBuilder with a market-analysis
    frame. This class makes the demo path explicit instead of embedding fixture
    builders inside IntelligenceApplicationService.
    """

    def build(self, *, observed_on: date) -> IntelligenceInputSet:
        market_score = Decimal("0.5856")
        liquidity_score = Decimal("0.90")
        risk_score = Decimal("0.79")

        recommendation_candidates = (
            RecommendationCandidate(
                symbol="HAL",
                observed_on=observed_on,
                action=RecommendationAction.BUY,
                strategy_score=Decimal("0.88"),
                probability_score=Decimal("0.74"),
                market_intelligence_score=market_score,
                liquidity_score=liquidity_score,
                risk_score=risk_score,
                expected_return=Decimal("0.14"),
                expected_drawdown=Decimal("0.045"),
                expected_holding_period_days=Decimal("45"),
                evidence=(
                    RecommendationEvidence(
                        label="Market Intelligence",
                        score_points=Decimal("14.64"),
                        max_points=Decimal("25"),
                        rationale=(
                            "constructive accumulation, liquidity, breadth, "
                            "sector leadership, and correlation profile"
                        ),
                    ),
                    RecommendationEvidence(
                        label="Strategy Strength",
                        score_points=Decimal("22"),
                        max_points=Decimal("25"),
                        rationale="momentum setup remains strong",
                    ),
                ),
                risks=(
                    RecommendationRisk(
                        label="Drawdown",
                        penalty_points=Decimal("2"),
                        rationale="expected drawdown remains controlled",
                    ),
                ),
                metadata={"source": "demo_intelligence_input_builder"},
            ),
            RecommendationCandidate(
                symbol="BEL",
                observed_on=observed_on,
                action=RecommendationAction.ACCUMULATE,
                strategy_score=Decimal("0.81"),
                probability_score=Decimal("0.70"),
                market_intelligence_score=Decimal("0.5456"),
                liquidity_score=Decimal("0.82"),
                risk_score=Decimal("0.63"),
                expected_return=Decimal("0.11"),
                expected_drawdown=Decimal("0.040"),
                expected_holding_period_days=Decimal("40"),
                evidence=(
                    RecommendationEvidence(
                        label="Sector Leadership",
                        score_points=Decimal("18"),
                        max_points=Decimal("25"),
                        rationale="defence sector remains a top leadership pocket",
                    ),
                ),
                risks=(
                    RecommendationRisk(
                        label="Correlation",
                        penalty_points=Decimal("3"),
                        rationale="sector overlap with the top-ranked candidate",
                    ),
                ),
                metadata={"source": "demo_intelligence_input_builder"},
            ),
            RecommendationCandidate(
                symbol="LT",
                observed_on=observed_on,
                action=RecommendationAction.ACCUMULATE,
                strategy_score=Decimal("0.76"),
                probability_score=Decimal("0.66"),
                market_intelligence_score=Decimal("0.62"),
                liquidity_score=Decimal("0.90"),
                risk_score=Decimal("0.72"),
                expected_return=Decimal("0.095"),
                expected_drawdown=Decimal("0.035"),
                expected_holding_period_days=Decimal("50"),
                evidence=(
                    RecommendationEvidence(
                        label="Liquidity",
                        score_points=Decimal("13.50"),
                        max_points=Decimal("15"),
                        rationale="high liquidity supports institutional sizing",
                    ),
                ),
                risks=(
                    RecommendationRisk(
                        label="Opportunity Cost",
                        penalty_points=Decimal("2"),
                        rationale="higher-ranked opportunities are available",
                    ),
                ),
                metadata={"source": "demo_intelligence_input_builder"},
            ),
        )

        sector_by_symbol = {
            "HAL": "DEFENCE",
            "BEL": "DEFENCE",
            "LT": "CAPITAL GOODS",
        }

        return IntelligenceInputSet(
            stock=StockIntelligenceInput(
                symbol="HAL",
                observed_on=observed_on,
                price_change_percent=Decimal("4.20"),
                delivery_percent=Decimal("68.00"),
                delivery_change_percent=Decimal("14.00"),
                volume_change_percent=Decimal("22.00"),
                turnover_value=Decimal("850000000"),
                average_turnover_value=Decimal("500000000"),
                spread_percent=Decimal("0.18"),
                volatility_percent=Decimal("3.20"),
            ),
            breadth=MarketBreadthInput(
                observed_on=observed_on,
                advances=1220,
                declines=760,
                unchanged=120,
            ),
            sectors=(
                SectorPerformanceInput(
                    sector="DEFENCE",
                    return_percent=Decimal("3.80"),
                    breadth_percent=Decimal("72.00"),
                    turnover_change_percent=Decimal("18.00"),
                ),
                SectorPerformanceInput(
                    sector="CAPITAL GOODS",
                    return_percent=Decimal("2.10"),
                    breadth_percent=Decimal("64.00"),
                    turnover_change_percent=Decimal("11.00"),
                ),
                SectorPerformanceInput(
                    sector="BANKS",
                    return_percent=Decimal("0.80"),
                    breadth_percent=Decimal("51.00"),
                    turnover_change_percent=Decimal("4.00"),
                ),
            ),
            correlation=CorrelationInput(
                symbol="HAL",
                correlation_to_index=Decimal("0.42"),
                correlation_to_sector=Decimal("0.55"),
            ),
            recommendation_candidates=recommendation_candidates,
            recommendation_portfolio_context=RecommendationPortfolioContext(
                existing_symbols=("LT",),
                sector_exposure={
                    "DEFENCE": Decimal("12"),
                    "CAPITAL GOODS": Decimal("8"),
                },
                symbol_sector=sector_by_symbol,
                max_single_position_percent=Decimal("10"),
                max_sector_exposure_percent=Decimal("25"),
            ),
            allocation_portfolio_context=AllocationPortfolioContext(
                total_capital=Decimal("1000000"),
                available_cash=Decimal("300000"),
                current_positions={"LT": Decimal("0.08")},
                sector_exposures=(
                    SectorExposure(
                        sector="DEFENCE",
                        current_weight=Decimal("0.12"),
                    ),
                    SectorExposure(
                        sector="CAPITAL GOODS",
                        current_weight=Decimal("0.08"),
                    ),
                ),
                risk_budget=RiskBudget(
                    max_position_weight=Decimal("0.10"),
                    max_sector_weight=Decimal("0.25"),
                    max_correlation=Decimal("0.75"),
                    max_portfolio_risk_weight=Decimal("0.35"),
                    min_recommendation_score=Decimal("60"),
                ),
            ),
            sector_by_symbol=sector_by_symbol,
            correlation_by_symbol={
                "HAL": Decimal("0.42"),
                "BEL": Decimal("0.68"),
                "LT": Decimal("0.48"),
            },
            liquidity_by_symbol={
                "HAL": Decimal("0.90"),
                "BEL": Decimal("0.82"),
                "LT": Decimal("0.90"),
            },
        )


def _prepare_frame(analysis: pd.DataFrame) -> pd.DataFrame:
    required_columns = {
        "symbol",
        "open",
        "close",
        "volume",
        "momentum_1d",
        "volatility",
        "liquidity",
        "alpha_score",
        "rank",
        "signal",
    }
    missing = required_columns.difference(analysis.columns)
    if missing:
        raise ValueError(
            "analysis frame missing required columns: " + ", ".join(sorted(missing))
        )

    frame = analysis.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame = frame.loc[frame["symbol"] != ""].copy()
    if frame.empty:
        raise ValueError("analysis frame contains no symbols")

    frame["sector"] = _sector_values(frame)
    frame["momentum_1d"] = frame["momentum_1d"].map(_decimal)
    frame["volatility"] = frame["volatility"].map(_decimal)
    frame["alpha_score"] = frame["alpha_score"].map(_decimal)
    frame["rank"] = frame["rank"].map(_decimal)
    frame = frame.assign(
        turnover_value=pd.Series(
            _turnover_values(frame),
            index=frame.index,
            dtype=object,
        )
    )
    if "average_turnover_value" not in frame.columns:
        frame["average_turnover_value"] = frame["turnover_value"]
    else:
        frame["average_turnover_value"] = frame["average_turnover_value"].map(_decimal)

    return frame


def _ranked_quality_frame(
    *,
    frame: pd.DataFrame,
    strategy_score_by_symbol: Mapping[str, Decimal],
    liquidity_by_symbol: Mapping[str, Decimal],
    correlation_by_symbol: Mapping[str, Decimal],
    sector_strength_by_sector: Mapping[str, Decimal],
) -> pd.DataFrame:
    records = cast(list[dict[str, Any]], frame.to_dict("records"))
    scores: list[Decimal] = []

    for record in records:
        symbol = str(record["symbol"]).strip().upper()
        sector = str(record["sector"]).strip().upper()
        strategy_score = strategy_score_by_symbol.get(symbol, _ZERO)
        momentum_score = _momentum_quality(_decimal(record["momentum_1d"]))
        turnover_score = _turnover_quality(record)
        liquidity_score = liquidity_by_symbol.get(symbol, Decimal("0.60"))
        correlation = correlation_by_symbol.get(symbol, Decimal("0.50"))
        sector_strength = sector_strength_by_sector.get(sector, Decimal("0.50"))
        risk_score = _bounded_ratio(
            _drawdown_quality(_decimal(record["volatility"])) * Decimal("0.55")
            + _correlation_quality(correlation) * Decimal("0.30")
            + liquidity_score * Decimal("0.15")
        )
        signal_quality = _signal_quality(str(record["signal"]))
        probability_score = _bounded_ratio(
            strategy_score * Decimal("0.32")
            + momentum_score * Decimal("0.22")
            + sector_strength * Decimal("0.16")
            + liquidity_score * Decimal("0.12")
            + _drawdown_quality(_decimal(record["volatility"])) * Decimal("0.10")
            + signal_quality * Decimal("0.08")
        )
        market_intelligence_score = _bounded_ratio(
            sector_strength * Decimal("0.35")
            + momentum_score * Decimal("0.22")
            + turnover_score * Decimal("0.18")
            + liquidity_score * Decimal("0.15")
            + risk_score * Decimal("0.10")
        )
        expected_return = _expected_return(record, strategy_score, sector_strength)
        expected_drawdown = _expected_drawdown(record, risk_score)
        expected_value_score = _expected_value_quality(
            expected_return=expected_return,
            expected_drawdown=expected_drawdown,
            probability_score=probability_score,
        )
        quality = _bounded_ratio(
            (
                strategy_score * Decimal("0.20")
                + probability_score * Decimal("0.14")
                + market_intelligence_score * Decimal("0.14")
                + liquidity_score * Decimal("0.22")
                + risk_score * Decimal("0.20")
                + expected_value_score * Decimal("0.10")
            )
            * _signal_eligibility_multiplier(str(record["signal"]))
        )
        scores.append(quality)

    ranked = frame.copy()
    ranked["candidate_quality_score"] = pd.Series(
        scores,
        index=ranked.index,
        dtype=object,
    )
    return ranked


def _turnover_values(frame: pd.DataFrame) -> list[Decimal]:
    records = cast(
        list[dict[str, Any]],
        frame.to_dict("records"),
    )
    return [_turnover_value(record) for record in records]


def _leader(frame: pd.DataFrame) -> Mapping[str, Any]:
    sort_columns = ["candidate_quality_score", "rank", "symbol"]
    if "candidate_quality_score" not in frame.columns:
        sort_columns = ["rank", "symbol"]

    if sort_columns[0] == "candidate_quality_score":
        ascending = [False, True, True]
    else:
        ascending = [True, True]
    records = cast(
        list[dict[str, Any]],
        frame.sort_values(sort_columns, ascending=ascending).head(1).to_dict("records"),
    )
    if not records:
        raise ValueError("analysis frame contains no ranked leader")
    return records[0]


def _sector_by_symbol(frame: pd.DataFrame) -> Mapping[str, str]:
    records = cast(
        list[dict[str, Any]],
        frame[["symbol", "sector"]]
        .drop_duplicates(subset=["symbol"])
        .to_dict("records"),
    )
    return MappingProxyType(
        {
            str(record["symbol"]).strip().upper(): str(record["sector"]).strip().upper()
            for record in records
        }
    )


def _strategy_score_by_symbol(frame: pd.DataFrame) -> Mapping[str, Decimal]:
    positive_alpha = [
        _decimal(value) for value in frame["alpha_score"] if _decimal(value) > _ZERO
    ]
    alpha_reference = max(positive_alpha, default=_ONE)
    if alpha_reference <= _ZERO:
        alpha_reference = _ONE

    records = cast(
        list[dict[str, Any]],
        frame[["symbol", "alpha_score", "rank", "signal"]]
        .drop_duplicates(subset=["symbol"])
        .to_dict("records"),
    )
    observed_count = max(len(frame), 1)

    return MappingProxyType(
        {
            str(record["symbol"]).strip().upper(): _strategy_quality(
                alpha_score=_decimal(record["alpha_score"]),
                rank=_decimal(record["rank"]),
                observed_count=observed_count,
                signal=str(record["signal"]),
                alpha_reference=alpha_reference,
            )
            for record in records
        }
    )


def _liquidity_by_symbol(frame: pd.DataFrame) -> Mapping[str, Decimal]:
    max_liquidity = max(_decimal(frame["liquidity"].max()), Decimal("1"))
    records = cast(
        list[dict[str, Any]],
        frame[["symbol", "liquidity"]]
        .drop_duplicates(subset=["symbol"])
        .to_dict("records"),
    )
    return MappingProxyType(
        {
            str(record["symbol"]).strip().upper(): _bounded_ratio(
                _decimal(record["liquidity"]) / max_liquidity
            )
            for record in records
        }
    )


def _correlation_by_symbol(frame: pd.DataFrame) -> Mapping[str, Decimal]:
    if "correlation_to_index" not in frame.columns:
        return MappingProxyType(
            {str(symbol).strip().upper(): Decimal("0.50") for symbol in frame["symbol"]}
        )

    records = cast(
        list[dict[str, Any]],
        frame[["symbol", "correlation_to_index"]]
        .drop_duplicates(subset=["symbol"])
        .to_dict("records"),
    )
    return MappingProxyType(
        {
            str(record["symbol"]).strip().upper(): _bounded_correlation(
                _decimal(record["correlation_to_index"])
            )
            for record in records
        }
    )


def _sector_strength_by_sector(frame: pd.DataFrame) -> Mapping[str, Decimal]:
    grouped = frame.groupby("sector", sort=True, dropna=False)
    values: dict[str, Decimal] = {}

    for sector, sector_frame in grouped:
        momentum = _decimal(sector_frame["momentum_1d"].mean())
        breadth = Decimal(str((sector_frame["momentum_1d"] > 0).mean()))
        turnover_ratio = _sector_turnover_ratio(sector_frame)
        momentum_quality = _momentum_quality(momentum)
        turnover_quality = _bounded_ratio(turnover_ratio / Decimal("1.50"))
        strength = _bounded_ratio(
            momentum_quality * Decimal("0.45")
            + breadth * Decimal("0.35")
            + turnover_quality * Decimal("0.20")
        )
        values[str(sector).strip().upper()] = strength

    return MappingProxyType(dict(sorted(values.items())))


def _sector_turnover_ratio(frame: pd.DataFrame) -> Decimal:
    denominator = max(_decimal(frame["average_turnover_value"].sum()), Decimal("1"))
    return _decimal(frame["turnover_value"].sum()) / denominator


def _has_deployable_trade_plan(recommendation: RecommendationReport) -> bool:
    return (
        recommendation.entry_price is not None
        and recommendation.entry_zone_low is not None
        and recommendation.entry_zone_high is not None
        and recommendation.initial_stop_loss is not None
        and recommendation.target_1 is not None
        and recommendation.trade_plan.atr_value is not None
        and recommendation.trade_plan.dma_20_invalidation is not None
        and _actionable_strategy_action(recommendation)
        == TradeStrategyAction.BUY_NOW.value
    )


def _actionable_strategy_action(recommendation: RecommendationReport) -> str:
    strategy = recommendation.actionable_trade_strategy
    if strategy is None:
        return "NONE"
    return strategy.action.value


def _normalize_symbol_sector(values: Mapping[str, str]) -> Mapping[str, str]:
    normalized = {
        symbol.strip().upper(): sector.strip().upper()
        for symbol, sector in values.items()
        if symbol.strip() and sector.strip()
    }
    return MappingProxyType(dict(sorted(normalized.items())))


def _normalize_decimal_mapping(values: Mapping[str, Decimal]) -> Mapping[str, Decimal]:
    normalized = {
        symbol.strip().upper(): Decimal(str(value))
        for symbol, value in values.items()
        if symbol.strip()
    }
    return MappingProxyType(dict(sorted(normalized.items())))


def _sector_values(frame: pd.DataFrame) -> pd.Series:
    for column in _SECTOR_COLUMNS:
        if column in frame.columns:
            return pd.Series(
                [_normalize_optional_sector(value) for value in frame[column]],
                index=frame.index,
                dtype=object,
            )
    return pd.Series(_DEFAULT_SECTOR, index=frame.index, dtype=object)


def _normalize_optional_sector(value: object) -> str:
    if value is None:
        return _DEFAULT_SECTOR

    normalized = str(value).strip().upper()
    if normalized in {"", "NAN", "NONE", "<NA>", "NAT"}:
        return _DEFAULT_SECTOR
    return normalized


def _turnover_value(row: Mapping[str, Any]) -> Decimal:
    if "turnover_value" in row and pd.notna(row["turnover_value"]):
        return _decimal(row["turnover_value"])
    return _decimal(row["close"]) * _decimal(row["volume"])


def _turnover_change_percent(row: Mapping[str, Any]) -> Decimal:
    turnover = _turnover_value(row)
    average_turnover = _decimal(row.get("average_turnover_value", turnover))
    if average_turnover <= _ZERO:
        return _ZERO
    return ((turnover / average_turnover) - _ONE) * _HUNDRED


def _turnover_quality(row: Mapping[str, Any]) -> Decimal:
    turnover = _turnover_value(row)
    average_turnover = _decimal(row.get("average_turnover_value", turnover))
    if average_turnover <= _ZERO:
        return Decimal("0.50")
    return _bounded_ratio((turnover / average_turnover) / Decimal("1.50"))


def _volume_metadata(
    record: Mapping[str, Any],
    price_history: tuple[OHLCVBar, ...],
) -> dict[str, str]:
    volume = _optional_record_decimal(record, "volume")
    average_volume = _rolling_average_volume(price_history)
    metadata: dict[str, str] = {}
    if volume is not None:
        metadata["volume"] = str(volume)
    if average_volume is not None:
        metadata["average_volume"] = str(average_volume)
    return metadata


def _rolling_average_volume(price_history: tuple[OHLCVBar, ...]) -> Decimal | None:
    if len(price_history) < 20:
        return None
    bars = price_history[-21:-1] if len(price_history) >= 21 else price_history[-20:]
    if not bars:
        return None
    return sum((bar.volume for bar in bars), _ZERO) / Decimal(len(bars))


def _price_history_by_symbol(
    frame: pd.DataFrame,
    observed_on: date,
) -> Mapping[str, tuple[OHLCVBar, ...]]:
    required_columns = {"symbol", "open", "high", "low", "close", "volume"}
    if not required_columns.issubset(frame.columns):
        return MappingProxyType({})

    date_column = next(
        (
            column
            for column in ("observed_on", "date", "trade_date", "timestamp")
            if column in frame.columns
        ),
        None,
    )
    sort_columns = ["symbol"]
    if date_column is not None:
        sort_columns.append(date_column)
    grouped = frame.sort_values(sort_columns).groupby("symbol", sort=True)
    histories: dict[str, tuple[OHLCVBar, ...]] = {}

    for symbol, symbol_frame in grouped:
        bars: list[OHLCVBar] = []
        for index, raw_record in enumerate(symbol_frame.to_dict("records")):
            record = cast(dict[str, Any], raw_record)
            if any(pd.isna(record[column]) for column in required_columns):
                continue
            bars.append(
                OHLCVBar(
                    observed_on=_record_date(
                        record,
                        date_column=date_column,
                        fallback=observed_on,
                        offset=index,
                    ),
                    open_price=_decimal(record["open"]),
                    high_price=_decimal(record["high"]),
                    low_price=_decimal(record["low"]),
                    close_price=_decimal(record["close"]),
                    volume=_decimal(record["volume"]),
                )
            )
        if bars:
            histories[str(symbol).strip().upper()] = tuple(bars)

    return MappingProxyType(dict(sorted(histories.items())))


def _record_date(
    record: Mapping[str, Any],
    *,
    date_column: str | None,
    fallback: date,
    offset: int,
) -> date:
    if date_column is None:
        return date.fromordinal(fallback.toordinal() + offset)
    value = record[date_column]
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return date.fromordinal(fallback.toordinal() + offset)
    parsed_date = parsed.date()
    if isinstance(parsed_date, date):
        return parsed_date
    return fallback


def _optional_record_decimal(
    record: Mapping[str, Any],
    key: str,
) -> Decimal | None:
    if key not in record or pd.isna(record[key]):
        return None
    return _decimal(record[key])


def _action_from_signal(signal: str) -> RecommendationAction:
    normalized = signal.strip().upper()
    if normalized == "BUY":
        return RecommendationAction.BUY
    if normalized == "SELL":
        return RecommendationAction.REDUCE
    return RecommendationAction.HOLD


def _signal_quality(signal: str) -> Decimal:
    normalized = signal.strip().upper()
    if normalized == "BUY":
        return _ONE
    if normalized == "HOLD":
        return Decimal("0.55")
    if normalized == "SELL":
        return Decimal("0.10")
    return Decimal("0.40")


def _signal_eligibility_multiplier(signal: str) -> Decimal:
    normalized = signal.strip().upper()
    if normalized == "BUY":
        return _ONE
    if normalized == "HOLD":
        return Decimal("0.65")
    if normalized == "SELL":
        return Decimal("0.30")
    return Decimal("0.50")


def _strategy_quality(
    *,
    alpha_score: Decimal,
    rank: Decimal,
    observed_count: int,
    signal: str,
    alpha_reference: Decimal,
) -> Decimal:
    if alpha_score <= _ZERO:
        return _ZERO

    alpha_quality = _bounded_ratio(
        alpha_score / max(alpha_reference, Decimal("0.0001"))
    )
    rank_quality = _rank_quality(rank=rank, observed_count=observed_count)
    normalized = _bounded_ratio(
        rank_quality * Decimal("0.75") + alpha_quality * Decimal("0.25")
    )
    signal_quality = _signal_quality(signal)

    if signal_quality >= _ONE:
        return normalized

    return _bounded_ratio(normalized * signal_quality)


def _rank_quality(*, rank: Decimal, observed_count: int) -> Decimal:
    if observed_count <= 1:
        return _ONE

    normalized_rank = max(Decimal(str(rank)), _ONE)
    percentile = _ONE - ((normalized_rank - _ONE) / Decimal(observed_count - 1))
    return _bounded_ratio(percentile)


def _momentum_quality(momentum: Decimal) -> Decimal:
    if momentum <= _ZERO:
        return max(Decimal("0.20") + (momentum / _POSITIVE_MOMENTUM_REFERENCE), _ZERO)
    return _bounded_ratio(
        Decimal("0.50") + (momentum / _STRONG_MOMENTUM_REFERENCE) * Decimal("0.50")
    )


def _drawdown_quality(value: Decimal) -> Decimal:
    volatility = abs(Decimal(str(value)))
    if volatility <= _ZERO:
        return _ONE
    if volatility <= _ACCEPTABLE_VOLATILITY_REFERENCE:
        return _bounded_ratio(_ONE - (volatility / _ACCEPTABLE_VOLATILITY_REFERENCE))

    excess_volatility = volatility - _ACCEPTABLE_VOLATILITY_REFERENCE
    return _bounded_ratio(
        Decimal("0.50") - (excess_volatility / _ACCEPTABLE_VOLATILITY_REFERENCE)
    )


def _correlation_quality(value: Decimal) -> Decimal:
    correlation = abs(_bounded_correlation(value))
    return _bounded_ratio(_ONE - (correlation * Decimal("0.70")))


def _expected_value_quality(
    *,
    expected_return: Decimal,
    expected_drawdown: Decimal,
    probability_score: Decimal,
) -> Decimal:
    if expected_drawdown <= _ZERO:
        reward_to_risk = expected_return
    else:
        reward_to_risk = expected_return / expected_drawdown

    return _bounded_ratio(
        _positive_ratio(expected_return / Decimal("0.12")) * Decimal("0.35")
        + _positive_ratio(reward_to_risk / Decimal("3")) * Decimal("0.35")
        + probability_score * Decimal("0.20")
        + _drawdown_quality(expected_drawdown) * Decimal("0.10")
    )


def _expected_return(
    row: Mapping[str, Any],
    strategy_score: Decimal,
    sector_strength: Decimal,
) -> Decimal:
    momentum = _decimal(row["momentum_1d"])
    turnover_quality = _turnover_quality(row)
    signal_quality = _signal_quality(str(row["signal"]))
    raw = (
        max(momentum, _ZERO) * Decimal("1.60")
        + max(strategy_score - Decimal("0.50"), _ZERO) * Decimal("0.08")
        + max(sector_strength - Decimal("0.50"), _ZERO) * Decimal("0.05")
        + max(turnover_quality - Decimal("0.50"), _ZERO) * Decimal("0.03")
        + max(signal_quality - Decimal("0.50"), _ZERO) * Decimal("0.02")
    )
    return max(_EXPECTED_RETURN_FLOOR, raw)


def _expected_drawdown(
    row: Mapping[str, Any],
    risk_score: Decimal,
) -> Decimal:
    volatility = abs(_decimal(row["volatility"]))
    spread_penalty = _decimal(row.get("spread_percent", Decimal("0.50"))) / _HUNDRED
    raw = volatility * Decimal("1.15") + spread_penalty * Decimal("0.35")
    if risk_score >= Decimal("0.75"):
        raw *= Decimal("0.85")
    return max(_EXPECTED_DRAWDOWN_FLOOR, raw)


def _expected_holding_period_days(
    strategy_score: Decimal,
    volatility: Decimal,
) -> Decimal:
    if strategy_score >= Decimal("0.80") and volatility <= Decimal("0.04"):
        return Decimal("45")
    if strategy_score >= Decimal("0.65"):
        return Decimal("30")
    return Decimal("20")


def _percent_from_fraction(value: Decimal) -> Decimal:
    return Decimal(str(value)) * _HUNDRED


def _bounded_percent(value: Decimal) -> Decimal:
    normalized = Decimal(str(value))
    if normalized < _ZERO:
        return _ZERO
    if normalized > _HUNDRED:
        return _HUNDRED
    return normalized


def _bounded_ratio(value: Decimal) -> Decimal:
    normalized = Decimal(str(value))
    if normalized < _ZERO:
        return _ZERO
    if normalized > _ONE:
        return _ONE
    return normalized


def _positive_ratio(value: Decimal) -> Decimal:
    return _bounded_ratio(max(Decimal(str(value)), _ZERO))


def _bounded_correlation(value: Decimal) -> Decimal:
    normalized = Decimal(str(value))
    if normalized < Decimal("-1"):
        return Decimal("-1")
    if normalized > _ONE:
        return _ONE
    return normalized


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


__all__ = [
    "DemoIntelligenceInputBuilder",
    "IntelligenceInputBuilder",
    "IntelligenceInputSet",
]
