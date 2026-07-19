from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

import pandas as pd

from alpha.analysis.signals.daily_report import DailyMarketReport
from alpha.application.intelligence import (
    IntelligenceApplicationService,
    IntelligenceInputProvider,
    IntelligenceRun,
)
from alpha.application.intelligence_inputs import (
    HistoricalPriceRepository,
    IntelligenceInputBuilder,
    IntelligenceInputSet,
    _correlation_by_symbol,
    _liquidity_by_symbol,
    _prepare_frame,
    _price_history_by_symbol,
    _ranked_quality_frame,
    _sector_strength_by_sector,
    _strategy_score_by_symbol,
)
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.decision_intelligence import (
    InstitutionalDecisionEngine,
    InstitutionalDecisionReport,
)
from alpha.portfolio_intelligence import AllocationCandidate
from alpha.recommendation_intelligence import OHLCVBar, RecommendationReport

CANONICAL_HISTORY_WINDOW = 250
CANONICAL_TECHNICAL_CANDIDATE_LIMIT = 10


@dataclass(frozen=True, slots=True)
class CanonicalAuditInputSet(IntelligenceInputSet):
    """Diagnostic-only adapter that enforces the allocation unit contract."""

    def allocation_candidates(
        self,
        recommendations: Iterable[RecommendationReport],
    ) -> tuple[AllocationCandidate, ...]:
        recommendation_rows = tuple(recommendations)
        bounded = tuple(
            replace(
                recommendation,
                expected_value=replace(
                    recommendation.expected_value,
                    expected_drawdown=min(
                        recommendation.expected_value.expected_drawdown,
                        Decimal("1"),
                    ),
                ),
            )
            for recommendation in recommendation_rows
        )
        return super().allocation_candidates(bounded)


@dataclass(frozen=True, slots=True)
class CanonicalDailyResult:
    observed_on: date
    analysis: pd.DataFrame
    intelligence: IntelligenceRun
    institutional: InstitutionalDecisionReport


class CanonicalAuditInputBuilder(IntelligenceInputBuilder):
    """
    Preserve canonical candidate selection while bounding history retrieval.

    The production builder ranks the complete frame but asks the repository for
    history for every symbol before retaining ten candidates. This override
    repeats the exact canonical pre-ranking solely to restrict that read to the
    same ten symbols. Recommendation inputs and engine behavior are unchanged.
    """

    def __init__(
        self,
        *,
        price_repository: HistoricalPriceRepository | None = None,
        history_window: int = CANONICAL_HISTORY_WINDOW,
        repair_invalid_ohlcv: bool = True,
    ) -> None:
        super().__init__(
            price_repository=price_repository,
            history_window=history_window,
        )
        self._repair_invalid_ohlcv = repair_invalid_ohlcv

    def build(
        self,
        *,
        observed_on: date,
        analysis: pd.DataFrame,
    ) -> IntelligenceInputSet:
        base = super().build(observed_on=observed_on, analysis=analysis)
        return CanonicalAuditInputSet(
            stock=base.stock,
            breadth=base.breadth,
            sectors=base.sectors,
            correlation=base.correlation,
            recommendation_candidates=base.recommendation_candidates,
            recommendation_portfolio_context=base.recommendation_portfolio_context,
            allocation_portfolio_context=base.allocation_portfolio_context,
            sector_by_symbol=base.sector_by_symbol,
            correlation_by_symbol=base.correlation_by_symbol,
            liquidity_by_symbol=base.liquidity_by_symbol,
        )

    def _price_history_by_symbol(
        self,
        *,
        frame: pd.DataFrame,
        observed_on: date,
    ) -> dict[str, tuple[OHLCVBar, ...]]:
        liquidity_by_symbol = _liquidity_by_symbol(frame)
        correlation_by_symbol = _correlation_by_symbol(frame)
        sector_strength_by_sector = _sector_strength_by_sector(frame)
        strategy_score_by_symbol = _strategy_score_by_symbol(frame)
        ranked = _ranked_quality_frame(
            frame=frame,
            strategy_score_by_symbol=strategy_score_by_symbol,
            liquidity_by_symbol=liquidity_by_symbol,
            correlation_by_symbol=correlation_by_symbol,
            sector_strength_by_sector=sector_strength_by_sector,
        )
        symbols = tuple(
            ranked.sort_values(
                ["candidate_quality_score", "rank", "symbol"],
                ascending=[False, True, True],
            )
            .head(CANONICAL_TECHNICAL_CANDIDATE_LIMIT)["symbol"]
            .astype(str)
            .str.upper()
            .tolist()
        )
        reduced = frame.loc[frame["symbol"].astype(str).str.upper().isin(symbols)]
        if self._repair_invalid_ohlcv:
            history = (
                self._price_repository.find_history_by_symbols(
                    symbols=symbols,
                    end_date=observed_on,
                    limit=self._history_window,
                )
                if self._price_repository is not None
                else reduced
            )
            if not history.empty:
                return dict(
                    _price_history_by_symbol(
                        _valid_ohlcv_rows(history),
                        observed_on,
                    )
                )
        return dict(
            super()._price_history_by_symbol(
                frame=reduced,
                observed_on=observed_on,
            )
        )


def _valid_ohlcv_rows(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close"}
    if not required.issubset(frame.columns):
        return frame
    high_floor = frame[["open", "low", "close"]].max(axis=1)
    low_ceiling = frame[["open", "high", "close"]].min(axis=1)
    return frame.loc[(frame["high"] >= high_floor) & (frame["low"] <= low_ceiling)]


@dataclass(frozen=True, slots=True)
class _CanonicalInputProvider(IntelligenceInputProvider):
    observed_on: date
    analysis: pd.DataFrame
    builder: CanonicalAuditInputBuilder

    def build(self, *, observed_on: date) -> IntelligenceInputSet:
        if observed_on != self.observed_on:
            raise ValueError("canonical provider date mismatch")
        return self.builder.build(observed_on=observed_on, analysis=self.analysis)


class CanonicalAlphaRunner:
    """Execute the frozen current Alpha pipeline without production mutation."""

    def __init__(
        self,
        *,
        store: LegacyMarketDataStore,
        daily_report: DailyMarketReport | None = None,
        institutional_engine: InstitutionalDecisionEngine | None = None,
    ) -> None:
        self.store = store
        self.daily_report = daily_report or DailyMarketReport()
        self.institutional_engine = (
            institutional_engine or InstitutionalDecisionEngine()
        )

    def run_day(self, observed_on: date) -> CanonicalDailyResult:
        prices = self.store.find_by_trade_date(observed_on)
        if prices.empty:
            raise ValueError(f"no valid legacy prices for {observed_on.isoformat()}")
        analysis = self.daily_report.generate(prices)["analysis"]
        return self.run_analysis(observed_on=observed_on, analysis=analysis)

    def run_analysis(
        self,
        *,
        observed_on: date,
        analysis: pd.DataFrame,
    ) -> CanonicalDailyResult:
        provider = _CanonicalInputProvider(
            observed_on=observed_on,
            analysis=analysis,
            builder=CanonicalAuditInputBuilder(
                price_repository=self.store,
                history_window=CANONICAL_HISTORY_WINDOW,
            ),
        )
        intelligence = IntelligenceApplicationService(input_provider=provider).run(
            observed_on=observed_on
        )
        institutional = self.institutional_engine.evaluate_recommendations(
            intelligence.recommendations,
            allocation_plan=intelligence.allocation_plan,
        )
        return CanonicalDailyResult(
            observed_on=observed_on,
            analysis=analysis,
            intelligence=intelligence,
            institutional=institutional,
        )


def candidate_quality_order(analysis: pd.DataFrame) -> tuple[str, ...]:
    """Expose the frozen technical ordering for parity tests and audit notes."""

    frame = _prepare_frame(analysis)
    liquidity = _liquidity_by_symbol(frame)
    correlation = _correlation_by_symbol(frame)
    sector_strength = _sector_strength_by_sector(frame)
    strategy = _strategy_score_by_symbol(frame)
    ranked = _ranked_quality_frame(
        frame=frame,
        strategy_score_by_symbol=strategy,
        liquidity_by_symbol=liquidity,
        correlation_by_symbol=correlation,
        sector_strength_by_sector=sector_strength,
    )
    return tuple(
        ranked.sort_values(
            ["candidate_quality_score", "rank", "symbol"],
            ascending=[False, True, True],
        )
        .head(CANONICAL_TECHNICAL_CANDIDATE_LIMIT)["symbol"]
        .astype(str)
        .str.upper()
    )


__all__ = [
    "CANONICAL_HISTORY_WINDOW",
    "CANONICAL_TECHNICAL_CANDIDATE_LIMIT",
    "CanonicalAlphaRunner",
    "CanonicalAuditInputBuilder",
    "CanonicalAuditInputSet",
    "CanonicalDailyResult",
    "candidate_quality_order",
]
