from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from types import MappingProxyType
from typing import Any, cast

import pandas as pd

from alpha.canonical_universe_audit.canonical_runner import (
    CanonicalAlphaRunner,
    candidate_quality_order,
)
from alpha.canonical_universe_audit.models import (
    ACU_RUN_VERSION,
    CANONICAL_ENGINE_VERSION,
    CandidateOutcomeRecord,
    CandidateRankingRecord,
    CanonicalUniverseAuditReport,
    DailyOpportunityRecord,
    ExecutiveSummary,
    GateAttributionRecord,
    GateCategory,
    LiquidityBucket,
    LiquidityCapacityRecord,
    MonthlyOpportunitySummary,
    OpportunityHeat,
    PeriodOpportunitySummary,
    SectorOpportunitySummary,
    SymbolOpportunitySummary,
)
from alpha.canonical_universe_audit.store import (
    LegacyMarketDataStore,
    decimal_or_none,
)
from alpha.decision_intelligence import OpportunityDecision, RejectionReasonCode
from alpha.recommendation_intelligence import OHLCVBar, RecommendationReport
from alpha.strategy_lab.execution_assumptions import default_execution_profile
from alpha.strategy_lab.models import (
    EntryRule,
    StopRule,
    TargetRule,
    TradeSimulationRequest,
)
from alpha.strategy_lab.trade_simulator import TradeSimulator

_ZERO = Decimal("0")
_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")
_MINIMUM_COMPLETE_HISTORY = 200
_PORTFOLIO_CAPITAL = Decimal("10000000")
_MAX_POSITION_CAPITAL = Decimal("1000000")
_LIQUIDITY_PARTICIPATION = Decimal("0.01")
_CORRELATION_LIMIT = Decimal("0.75")
_OUTCOME_WINDOW = 60
_APPROVABLE_SIGNALS = frozenset({"BUY", "STRONG_BUY"})


@dataclass(frozen=True, slots=True)
class AuditRunRequest:
    start: date | None = None
    end: date | None = None
    generated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("audit end date cannot precede start date")


class CanonicalUniverseAuditEngine:
    """Measure the frozen Alpha decision funnel over the legacy population."""

    def __init__(self, *, simulator: TradeSimulator | None = None) -> None:
        self.simulator = simulator or TradeSimulator()

    def run(
        self,
        *,
        store: LegacyMarketDataStore,
        request: AuditRunRequest | None = None,
        progress: Callable[[int, int, date], None] | None = None,
    ) -> CanonicalUniverseAuditReport:
        run_request = request or AuditRunRequest()
        manifest = store.manifest()
        dates = store.trade_dates(start=run_request.start, end=run_request.end)
        if not dates:
            raise ValueError("no legacy trading sessions match the audit window")

        liquidity = _liquidity_records(store.liquidity_statistics())
        liquidity_by_symbol = {item.symbol: item for item in liquidity}
        history_counts = store.history_counts_before(dates[0])
        runner = CanonicalAlphaRunner(store=store)
        daily_rows: list[DailyOpportunityRecord] = []
        ranking_rows: list[CandidateRankingRecord] = []
        gate_rows: list[GateAttributionRecord] = []
        recommendations_for_outcomes: dict[str, RecommendationReport] = {}

        total_dates = len(dates)
        for index, observed_on in enumerate(dates, start=1):
            prices = store.find_by_trade_date(observed_on)
            if prices.empty:
                raise ValueError(
                    f"no valid legacy prices for {observed_on.isoformat()}"
                )
            analysis = runner.daily_report.generate(prices)["analysis"]
            universe_symbols = tuple(
                str(value).strip().upper() for value in analysis["symbol"].astype(str)
            )
            for symbol in universe_symbols:
                history_counts[symbol] = history_counts.get(symbol, 0) + 1
            eligible = sum(
                1
                for symbol in universe_symbols
                if history_counts.get(symbol, 0) >= _MINIMUM_COMPLETE_HISTORY
            )
            try:
                day = runner.run_analysis(
                    observed_on=observed_on,
                    analysis=analysis,
                )
            except (ArithmeticError, ValueError) as error:
                failed_symbols = candidate_quality_order(analysis)
                failure = _safe_runtime_error(error)
                daily_rows.append(
                    DailyOpportunityRecord(
                        observed_on=observed_on,
                        universe_size=len(universe_symbols),
                        eligible_securities=eligible,
                        technical_candidates=len(failed_symbols),
                        approval_candidates=0,
                        institutional_approvals=0,
                        portfolio_eligible=0,
                        raw_approvals=0,
                        independent_approvals=0,
                        average_score=None,
                        median_score=None,
                        maximum_score=None,
                        score_80_plus=0,
                        score_90_plus=0,
                        score_95_plus=0,
                        estimated_invested_capital=_ZERO,
                        estimated_position_count=0,
                        runtime_status="FAILED_CLOSED",
                        runtime_error=failure,
                    )
                )
                gate_rows.extend(
                    GateAttributionRecord(
                        observed_on=observed_on,
                        symbol=symbol,
                        gate_code="CANONICAL_RUNTIME_ERROR",
                        category=GateCategory.OTHER,
                        explanation=failure,
                        primary=True,
                    )
                    for symbol in failed_symbols
                )
                if progress is not None:
                    progress(index, total_dates, observed_on)
                continue

            institutional_by_symbol = {
                item.candidate.symbol: item for item in day.institutional.decisions
            }
            allocation_by_symbol = {
                item.symbol: item for item in day.intelligence.allocation_plan.reports
            }
            recommendations = tuple(
                sorted(
                    day.intelligence.recommendations,
                    key=lambda item: (-item.final_score, item.symbol),
                )
            )
            approval_candidates = tuple(
                item
                for item in recommendations
                if item.final_signal in _APPROVABLE_SIGNALS
            )
            approved = tuple(
                item
                for item in recommendations
                if _is_institutionally_approved(
                    institutional_by_symbol.get(item.symbol)
                )
            )
            portfolio_eligible = tuple(
                item
                for item in approved
                if _has_positive_allocation(allocation_by_symbol.get(item.symbol))
            )
            independent = _independent_opportunity_count(
                store=store,
                observed_on=observed_on,
                symbols=tuple(item.symbol for item in approved),
            )

            scores = tuple(item.final_score for item in recommendations)
            estimated_capital = sum(
                (
                    _estimated_position_capital(liquidity_by_symbol.get(item.symbol))
                    for item in portfolio_eligible
                ),
                start=_ZERO,
            )
            estimated_capital = min(estimated_capital, _PORTFOLIO_CAPITAL)
            daily_rows.append(
                DailyOpportunityRecord(
                    observed_on=observed_on,
                    universe_size=len(universe_symbols),
                    eligible_securities=eligible,
                    technical_candidates=len(day.intelligence.raw_candidates),
                    approval_candidates=len(approval_candidates),
                    institutional_approvals=len(approved),
                    portfolio_eligible=len(portfolio_eligible),
                    raw_approvals=len(approved),
                    independent_approvals=independent,
                    average_score=_mean(scores),
                    median_score=_median_decimal(scores),
                    maximum_score=max(scores) if scores else None,
                    score_80_plus=sum(1 for value in scores if value >= Decimal("80")),
                    score_90_plus=sum(1 for value in scores if value >= Decimal("90")),
                    score_95_plus=sum(1 for value in scores if value >= Decimal("95")),
                    estimated_invested_capital=_q(estimated_capital),
                    estimated_position_count=len(portfolio_eligible),
                    runtime_status="SUCCESS",
                    runtime_error=None,
                )
            )
            ranking_rows.extend(
                _ranking_records(
                    observed_on=observed_on,
                    recommendations=recommendations,
                    institutional_by_symbol=institutional_by_symbol,
                    allocation_by_symbol=allocation_by_symbol,
                    liquidity_by_symbol=liquidity_by_symbol,
                )
            )
            gate_rows.extend(
                _gate_records(
                    observed_on=observed_on,
                    decisions=day.institutional.decisions,
                    allocation_by_symbol=allocation_by_symbol,
                )
            )
            for item in approval_candidates:
                recommendations_for_outcomes[
                    _candidate_id(observed_on, item.symbol)
                ] = item
            if progress is not None:
                progress(index, total_dates, observed_on)

        outcomes = self._outcomes(
            store=store,
            recommendations=recommendations_for_outcomes,
        )
        monthly = _monthly_summaries(daily_rows)
        weekly = _period_summaries(daily_rows, period="week")
        yearly = _period_summaries(daily_rows, period="year")
        sectors = _sector_summaries(ranking_rows, outcomes, len(dates))
        symbols = _symbol_summaries(
            ranking_rows,
            manifest.first_session,
            manifest.last_session,
            universe_symbols=tuple(item.symbol for item in liquidity),
        )
        executive = _executive_summary(
            daily=daily_rows,
            monthly=monthly,
            weekly=weekly,
            yearly=yearly,
            rankings=ranking_rows,
            gates=gate_rows,
            outcomes=outcomes,
            symbols=symbols,
        )
        generated_at = run_request.generated_at or datetime.now(tz=UTC)
        audit_id = (
            f"{ACU_RUN_VERSION}|{CANONICAL_ENGINE_VERSION}|"
            f"{dates[0].isoformat()}|"
            f"{dates[-1].isoformat()}"
        )
        return CanonicalUniverseAuditReport(
            audit_id=audit_id,
            generated_at=generated_at,
            canonical_engine_version=CANONICAL_ENGINE_VERSION,
            dataset=manifest,
            daily=tuple(daily_rows),
            rankings=tuple(ranking_rows),
            gates=tuple(gate_rows),
            outcomes=outcomes,
            monthly=monthly,
            weekly=weekly,
            yearly=yearly,
            sectors=sectors,
            liquidity=liquidity,
            symbols=symbols,
            executive=executive,
            definitions=MappingProxyType(
                {
                    "approval_candidate": "Final signal is BUY or STRONG_BUY.",
                    "canonical_history_window": "250 point-in-time daily bars.",
                    "eligible_security": (
                        "At least 200 valid point-in-time OHLCV bars, matching "
                        "Alpha's complete 200-DMA requirement."
                    ),
                    "expected_payoff": (
                        "Mean completed simulated return using the frozen recorded "
                        "trade plan and conservative stop-first same-bar ordering."
                    ),
                    "independent_approval": (
                        "Connected-component count after grouping simultaneous "
                        "approvals whose trailing-return correlation exceeds 0.75."
                    ),
                    "institutional_approval": (
                        "Candidate accepted by the current InstitutionalDecisionEngine."
                    ),
                    "liquidity_capacity": (
                        "Approximate lesser of requested capital and 1% of average "
                        "daily traded value; free float and spread are unavailable."
                    ),
                    "portfolio_eligible": (
                        "Institutionally approved candidate with positive current "
                        "portfolio-allocation output."
                    ),
                    "runtime_failure": (
                        "Canonical exception recorded as FAILED_CLOSED; no scores, "
                        "approvals, allocations, or outcomes are inferred."
                    ),
                    "production_influence": "false",
                    "technical_candidate": (
                        "Candidate retained by the frozen canonical top-ten "
                        "quality rank."
                    ),
                }
            ),
        )

    def _outcomes(
        self,
        *,
        store: LegacyMarketDataStore,
        recommendations: Mapping[str, RecommendationReport],
    ) -> tuple[CandidateOutcomeRecord, ...]:
        if not recommendations:
            return ()
        candidates = pd.DataFrame(
            (
                {
                    "candidate_id": candidate_id,
                    "symbol": recommendation.symbol,
                    "observed_on": recommendation.observed_on,
                }
                for candidate_id, recommendation in sorted(recommendations.items())
            )
        )
        future = store.future_bars(candidates, limit=_OUTCOME_WINDOW)
        bars_by_id = _bars_by_candidate(future)
        profile = default_execution_profile()
        rows: list[CandidateOutcomeRecord] = []
        for candidate_id, recommendation in sorted(recommendations.items()):
            bars = bars_by_id.get(candidate_id, ())
            holding_period = _holding_period(recommendation)
            if len(bars) < holding_period:
                rows.append(
                    CandidateOutcomeRecord(
                        observed_on=recommendation.observed_on,
                        symbol=recommendation.symbol,
                        entered=False,
                        completed=False,
                        won=None,
                        realized_return_pct=None,
                        realized_r=None,
                        holding_period_days=None,
                        exit_reason="PENDING_END_OF_DATA",
                        evidence_note=(
                            f"Requires {holding_period} future bars; has {len(bars)}."
                        ),
                    )
                )
                continue
            simulation = self.simulator.simulate(
                TradeSimulationRequest(
                    recommendation_id=candidate_id,
                    symbol=recommendation.symbol,
                    decision_time=datetime.combine(
                        recommendation.observed_on,
                        datetime.min.time(),
                        tzinfo=UTC,
                    ),
                    bars=bars,
                    entry_rule=_entry_rule(recommendation),
                    stop_rule=StopRule.RECORDED_PLAN,
                    target_rule=TargetRule.RECORDED_PLAN,
                    entry_zone_low=recommendation.entry_zone_low,
                    entry_zone_high=recommendation.entry_zone_high,
                    confirmation_entry=recommendation.trade_plan.confirmation_entry,
                    recorded_stop=recommendation.initial_stop_loss,
                    target_1=recommendation.target_1,
                    target_2=recommendation.target_2,
                    target_3=recommendation.target_3,
                    support=recommendation.support_level_used,
                    swing_low=recommendation.swing_low,
                    atr=recommendation.trade_plan.atr_value,
                    holding_period_days=holding_period,
                ),
                profile,
            )
            completed = simulation.entered and simulation.net_return_pct is not None
            won = (
                None
                if not completed or simulation.realised_r_multiple is None
                else simulation.realised_r_multiple > _ZERO
            )
            rows.append(
                CandidateOutcomeRecord(
                    observed_on=recommendation.observed_on,
                    symbol=recommendation.symbol,
                    entered=simulation.entered,
                    completed=completed,
                    won=won,
                    realized_return_pct=simulation.net_return_pct,
                    realized_r=simulation.realised_r_multiple,
                    holding_period_days=simulation.holding_period_days,
                    exit_reason=simulation.exit_reason.value,
                    evidence_note=" ".join(simulation.audit),
                )
            )
        return tuple(rows)


def _ranking_records(
    *,
    observed_on: date,
    recommendations: tuple[RecommendationReport, ...],
    institutional_by_symbol: Mapping[str, OpportunityDecision],
    allocation_by_symbol: Mapping[str, object],
    liquidity_by_symbol: Mapping[str, LiquidityCapacityRecord],
) -> tuple[CandidateRankingRecord, ...]:
    rows: list[CandidateRankingRecord] = []
    for rank, item in enumerate(recommendations, start=1):
        approved = _is_institutionally_approved(
            institutional_by_symbol.get(item.symbol)
        )
        portfolio_eligible = approved and _has_positive_allocation(
            allocation_by_symbol.get(item.symbol)
        )
        liquidity = liquidity_by_symbol.get(item.symbol)
        expected_return = item.expected_value.expected_return
        rows.append(
            CandidateRankingRecord(
                observed_on=observed_on,
                rank=rank,
                symbol=item.symbol,
                final_signal=item.final_signal,
                score=item.final_score,
                confidence=item.confidence,
                sector=item.metadata.get("sector", "UNKNOWN") or "UNKNOWN",
                liquidity_bucket=(
                    LiquidityBucket.UNAVAILABLE
                    if liquidity is None
                    else liquidity.liquidity_bucket
                ),
                expected_r=item.risk_reward_ratio,
                suggested_priority=(
                    "RESEARCH_PRIORITY_HIGH"
                    if rank <= 3
                    else "RESEARCH_PRIORITY_MEDIUM"
                    if rank <= 6
                    else "RESEARCH_PRIORITY_STANDARD"
                ),
                approval_candidate=item.final_signal in _APPROVABLE_SIGNALS,
                institutional_approved=approved,
                portfolio_eligible=portfolio_eligible,
                setup_type=item.setup_name,
                setup_stage=item.setup_stage,
                entry_price=(
                    item.trade_plan.confirmation_entry
                    or item.entry_zone_high
                    or item.entry_zone_low
                ),
                initial_stop=item.initial_stop_loss,
                target_1=item.target_1,
                expected_return=expected_return,
                holding_period_days=_holding_period(item),
            )
        )
    return tuple(rows)


def _gate_records(
    *,
    observed_on: date,
    decisions: tuple[OpportunityDecision, ...],
    allocation_by_symbol: Mapping[str, object],
) -> tuple[GateAttributionRecord, ...]:
    rows: list[GateAttributionRecord] = []
    for decision in sorted(decisions, key=lambda item: item.candidate.symbol):
        for index, reason in enumerate(decision.rejection_reasons):
            rows.append(
                GateAttributionRecord(
                    observed_on=observed_on,
                    symbol=decision.candidate.symbol,
                    gate_code=reason.code.value,
                    category=_gate_category(reason.code),
                    explanation=reason.explanation,
                    primary=index == 0,
                )
            )
        if decision.accepted and not _has_positive_allocation(
            allocation_by_symbol.get(decision.candidate.symbol)
        ):
            rows.append(
                GateAttributionRecord(
                    observed_on=observed_on,
                    symbol=decision.candidate.symbol,
                    gate_code="PORTFOLIO_ALLOCATION_ZERO",
                    category=GateCategory.PORTFOLIO,
                    explanation=(
                        "Institutional gates passed but current portfolio policy "
                        "approved no capital."
                    ),
                    primary=True,
                )
            )
    return tuple(rows)


def _gate_category(code: RejectionReasonCode) -> GateCategory:
    mapping = {
        RejectionReasonCode.WEAK_VERDICT: GateCategory.PRICE,
        RejectionReasonCode.WEAK_CONFIDENCE: GateCategory.APPROVAL,
        RejectionReasonCode.INSUFFICIENT_EVIDENCE: GateCategory.APPROVAL,
        RejectionReasonCode.POOR_REWARD_RISK: GateCategory.RISK,
        RejectionReasonCode.EXCESS_DOWNSIDE_RISK: GateCategory.RISK,
        RejectionReasonCode.POOR_DATA_COMPLETENESS: GateCategory.APPROVAL,
        RejectionReasonCode.INSUFFICIENT_CAPACITY: GateCategory.VOLUME,
        RejectionReasonCode.LIVE_FEED_UNHEALTHY: GateCategory.OTHER,
        RejectionReasonCode.WEAK_SETUP: GateCategory.TREND,
        RejectionReasonCode.MISSING_TRADE_PLAN: GateCategory.RISK,
        RejectionReasonCode.PENDING_ENTRY_TRIGGER: GateCategory.ENTRY_TIMING,
        RejectionReasonCode.LATE_ENTRY: GateCategory.ENTRY_TIMING,
        RejectionReasonCode.POOR_HISTORICAL_EDGE: GateCategory.APPROVAL,
    }
    return mapping.get(code, GateCategory.OTHER)


def _liquidity_records(frame: pd.DataFrame) -> tuple[LiquidityCapacityRecord, ...]:
    if frame.empty:
        return ()
    valid_turnover = frame["average_daily_turnover"].dropna()
    q25 = (
        Decimal(str(valid_turnover.quantile(0.25)))
        if not valid_turnover.empty
        else _ZERO
    )
    q50 = (
        Decimal(str(valid_turnover.quantile(0.50)))
        if not valid_turnover.empty
        else _ZERO
    )
    q75 = (
        Decimal(str(valid_turnover.quantile(0.75)))
        if not valid_turnover.empty
        else _ZERO
    )
    rows: list[LiquidityCapacityRecord] = []
    for raw in frame.to_dict("records"):
        record = cast(dict[str, Any], raw)
        volume = decimal_or_none(record.get("average_daily_volume"))
        turnover = decimal_or_none(record.get("average_daily_turnover"))
        bucket = _liquidity_bucket(turnover, q25=q25, q50=q50, q75=q75)
        capacity = None if turnover is None else turnover * _LIQUIDITY_PARTICIPATION
        rows.append(
            LiquidityCapacityRecord(
                symbol=str(record["symbol"]),
                average_daily_volume=None if volume is None else _q(volume),
                average_daily_turnover=None if turnover is None else _q(turnover),
                free_float=None,
                liquidity_bucket=bucket,
                deployable_at_10_lakh=_bounded_capacity(capacity, Decimal("1000000")),
                deployable_at_50_lakh=_bounded_capacity(capacity, Decimal("5000000")),
                deployable_at_1_crore=_bounded_capacity(capacity, Decimal("10000000")),
                deployable_at_5_crore=_bounded_capacity(capacity, Decimal("50000000")),
                deployable_at_10_crore=_bounded_capacity(
                    capacity, Decimal("100000000")
                ),
            )
        )
    return tuple(sorted(rows, key=lambda item: item.symbol))


def _liquidity_bucket(
    turnover: Decimal | None,
    *,
    q25: Decimal,
    q50: Decimal,
    q75: Decimal,
) -> LiquidityBucket:
    if turnover is None:
        return LiquidityBucket.UNAVAILABLE
    if turnover >= q75:
        return LiquidityBucket.VERY_HIGH
    if turnover >= q50:
        return LiquidityBucket.HIGH
    if turnover >= q25:
        return LiquidityBucket.MEDIUM
    return LiquidityBucket.LOW


def _monthly_summaries(
    rows: Iterable[DailyOpportunityRecord],
) -> tuple[MonthlyOpportunitySummary, ...]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for item in rows:
        grouped[item.observed_on.strftime("%Y-%m")].append(item.portfolio_eligible)
    totals = tuple(sum(values) for values in grouped.values())
    average_total = _mean(tuple(Decimal(value) for value in totals)) or _ZERO
    result: list[MonthlyOpportunitySummary] = []
    for month, values in sorted(grouped.items()):
        total = sum(values)
        heat = (
            OpportunityHeat.ALMOST_NONE
            if average_total == _ZERO
            or Decimal(total) <= average_total * Decimal("0.25")
            else OpportunityHeat.VERY_HIGH
            if Decimal(total) >= average_total * Decimal("1.75")
            else OpportunityHeat.AVERAGE
        )
        result.append(
            MonthlyOpportunitySummary(
                month=month,
                trading_days=len(values),
                total_opportunities=total,
                average_opportunities_per_day=_q(Decimal(total) / Decimal(len(values))),
                maximum_opportunities=max(values),
                heat=heat,
            )
        )
    return tuple(result)


def _period_summaries(
    rows: Iterable[DailyOpportunityRecord],
    *,
    period: str,
) -> tuple[PeriodOpportunitySummary, ...]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for item in rows:
        if period == "week":
            iso_year, iso_week, _ = item.observed_on.isocalendar()
            key = f"{iso_year}-W{iso_week:02d}"
        elif period == "year":
            key = str(item.observed_on.year)
        else:
            raise ValueError("ACU period must be week or year")
        grouped[key].append(item.portfolio_eligible)
    return tuple(
        PeriodOpportunitySummary(
            period=key,
            trading_days=len(values),
            total_opportunities=sum(values),
            average_opportunities_per_day=_q(
                Decimal(sum(values)) / Decimal(len(values))
            ),
            maximum_opportunities_in_day=max(values),
        )
        for key, values in sorted(grouped.items())
    )


def _sector_summaries(
    rankings: Iterable[CandidateRankingRecord],
    outcomes: Iterable[CandidateOutcomeRecord],
    trading_days: int,
) -> tuple[SectorOpportunitySummary, ...]:
    by_sector: dict[str, list[CandidateRankingRecord]] = defaultdict(list)
    sector_by_key: dict[tuple[date, str], str] = {}
    for ranking in rankings:
        sector = ranking.sector or "UNKNOWN"
        by_sector[sector].append(ranking)
        sector_by_key[(ranking.observed_on, ranking.symbol)] = sector
    outcomes_by_sector: dict[str, list[CandidateOutcomeRecord]] = defaultdict(list)
    for outcome in outcomes:
        outcomes_by_sector[
            sector_by_key.get((outcome.observed_on, outcome.symbol), "UNKNOWN")
        ].append(outcome)
    rows: list[SectorOpportunitySummary] = []
    for sector, items in sorted(by_sector.items()):
        approved = tuple(item for item in items if item.portfolio_eligible)
        completed = tuple(
            item for item in outcomes_by_sector.get(sector, ()) if item.completed
        )
        returns = tuple(
            item.realized_return_pct
            for item in completed
            if item.realized_return_pct is not None
        )
        wins = sum(1 for item in completed if item.won is True)
        expected = tuple(
            item.expected_return for item in items if item.expected_return is not None
        )
        rows.append(
            SectorOpportunitySummary(
                sector=sector,
                candidates=len(items),
                approved_opportunities=len(approved),
                average_opportunities_per_day=_q(
                    Decimal(len(approved)) / Decimal(trading_days)
                ),
                completed_outcomes=len(completed),
                win_rate=(
                    None
                    if not completed
                    else _q(Decimal(wins) / Decimal(len(completed)))
                ),
                average_realized_return_pct=_mean(returns),
                average_expected_return=_mean(expected),
            )
        )
    return tuple(rows)


def _symbol_summaries(
    rankings: Iterable[CandidateRankingRecord],
    first_session: date,
    last_session: date,
    *,
    universe_symbols: tuple[str, ...],
) -> tuple[SymbolOpportunitySummary, ...]:
    grouped: dict[str, list[CandidateRankingRecord]] = defaultdict(list)
    for item in rankings:
        grouped[item.symbol].append(item)
    years = max(
        Decimal("1"),
        Decimal((last_session - first_session).days) / Decimal("365.25"),
    )
    rows = (
        SymbolOpportunitySummary(
            symbol=symbol,
            candidate_count=len(items),
            approval_count=sum(1 for item in items if item.approval_candidate),
            portfolio_eligible_count=sum(
                1 for item in items if item.portfolio_eligible
            ),
            active_years=_q(years),
            candidates_per_year=_q(Decimal(len(items)) / years),
            approvals_per_year=_q(
                Decimal(sum(1 for item in items if item.approval_candidate)) / years
            ),
            candidates_per_decade=_q(Decimal(len(items)) / years * Decimal("10")),
            average_score=_mean(tuple(item.score for item in items)),
            trades_per_year=_q(
                Decimal(sum(1 for item in items if item.portfolio_eligible)) / years
            ),
            trades_per_decade=_q(
                Decimal(sum(1 for item in items if item.portfolio_eligible))
                / years
                * Decimal("10")
            ),
        )
        for symbol in sorted(set(universe_symbols) | set(grouped))
        for items in (grouped.get(symbol, []),)
    )
    return tuple(sorted(rows, key=lambda item: (-item.candidate_count, item.symbol)))


def _executive_summary(
    *,
    daily: list[DailyOpportunityRecord],
    monthly: tuple[MonthlyOpportunitySummary, ...],
    weekly: tuple[PeriodOpportunitySummary, ...],
    yearly: tuple[PeriodOpportunitySummary, ...],
    rankings: list[CandidateRankingRecord],
    gates: list[GateAttributionRecord],
    outcomes: tuple[CandidateOutcomeRecord, ...],
    symbols: tuple[SymbolOpportunitySummary, ...],
) -> ExecutiveSummary:
    opportunity_counts = tuple(item.portfolio_eligible for item in daily)
    scores = tuple(item.score for item in rankings)
    gate_counts = Counter(item.gate_code for item in gates if item.primary)
    largest_gate, largest_count = (
        ("NONE", 0)
        if not gate_counts
        else sorted(gate_counts.items(), key=lambda item: (-item[1], item[0]))[0]
    )
    completed = tuple(item for item in outcomes if item.completed)
    wins = sum(1 for item in completed if item.won is True)
    returns = tuple(
        item.realized_return_pct
        for item in completed
        if item.realized_return_pct is not None
    )
    invested = tuple(
        item.estimated_invested_capital / _PORTFOLIO_CAPITAL * Decimal("100")
        for item in daily
    )
    average_invested = _mean(invested) or _ZERO
    monthly_counts = tuple(item.total_opportunities for item in monthly)
    weekly_counts = tuple(item.total_opportunities for item in weekly)
    yearly_counts = tuple(item.total_opportunities for item in yearly)
    symbol_trade_counts = tuple(
        Decimal(item.portfolio_eligible_count) for item in symbols
    )
    clusters, longest_streak = _opportunity_clusters(daily)
    return ExecutiveSummary(
        total_sessions=len(daily),
        total_candidates=sum(item.technical_candidates for item in daily),
        total_approval_candidates=sum(
            1 for item in rankings if item.approval_candidate
        ),
        total_institutional_approvals=sum(
            item.institutional_approvals for item in daily
        ),
        total_portfolio_eligible=sum(opportunity_counts),
        average_opportunities_per_day=_mean(
            tuple(Decimal(item) for item in opportunity_counts)
        )
        or _ZERO,
        median_opportunities_per_day=_median_decimal(
            tuple(Decimal(item) for item in opportunity_counts)
        )
        or _ZERO,
        maximum_opportunities_per_day=max(opportunity_counts, default=0),
        average_opportunities_per_month=_mean(
            tuple(Decimal(item) for item in monthly_counts)
        )
        or _ZERO,
        maximum_opportunities_per_month=max(monthly_counts, default=0),
        zero_opportunity_days=sum(1 for value in opportunity_counts if value == 0),
        one_opportunity_days=sum(1 for value in opportunity_counts if value == 1),
        two_plus_opportunity_days=sum(1 for value in opportunity_counts if value >= 2),
        five_plus_opportunity_days=sum(1 for value in opportunity_counts if value >= 5),
        average_invested_percent=average_invested,
        average_idle_percent=_q(Decimal("100") - average_invested),
        average_positions=_mean(
            tuple(Decimal(item.estimated_position_count) for item in daily)
        )
        or _ZERO,
        average_score=_mean(scores),
        median_score=_median_decimal(scores),
        score_80_plus=sum(1 for value in scores if value >= Decimal("80")),
        score_90_plus=sum(1 for value in scores if value >= Decimal("90")),
        score_95_plus=sum(1 for value in scores if value >= Decimal("95")),
        largest_gate=largest_gate,
        largest_gate_rejections=largest_count,
        raw_simultaneous_approvals=sum(item.raw_approvals for item in daily),
        independent_simultaneous_approvals=sum(
            item.independent_approvals for item in daily
        ),
        completed_outcomes=len(completed),
        win_rate=(
            None if not completed else _q(Decimal(wins) / Decimal(len(completed)))
        ),
        expected_payoff_pct=_mean(returns),
        canonical_runtime_failure_days=sum(
            1 for item in daily if item.runtime_status != "SUCCESS"
        ),
        scored_candidates=len(rankings),
        average_opportunities_per_week=_mean(
            tuple(Decimal(item) for item in weekly_counts)
        )
        or _ZERO,
        median_opportunities_per_week=_median_decimal(
            tuple(Decimal(item) for item in weekly_counts)
        )
        or _ZERO,
        maximum_opportunities_per_week=max(weekly_counts, default=0),
        average_opportunities_per_year=_mean(
            tuple(Decimal(item) for item in yearly_counts)
        )
        or _ZERO,
        median_opportunities_per_year=_median_decimal(
            tuple(Decimal(item) for item in yearly_counts)
        )
        or _ZERO,
        maximum_opportunities_per_year=max(yearly_counts, default=0),
        average_trades_per_symbol=_mean(symbol_trade_counts) or _ZERO,
        median_trades_per_symbol=_median_decimal(symbol_trade_counts) or _ZERO,
        opportunity_day_clusters=clusters,
        longest_opportunity_day_streak=longest_streak,
        pending_outcomes=sum(1 for item in outcomes if not item.completed),
        not_entered_outcomes=sum(
            1 for item in outcomes if not item.completed and not item.entered
        ),
    )


def _opportunity_clusters(rows: Iterable[DailyOpportunityRecord]) -> tuple[int, int]:
    clusters = 0
    current = 0
    longest = 0
    for item in rows:
        if item.portfolio_eligible > 0:
            if current == 0:
                clusters += 1
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return clusters, longest


def _independent_opportunity_count(
    *,
    store: LegacyMarketDataStore,
    observed_on: date,
    symbols: tuple[str, ...],
) -> int:
    if len(symbols) <= 1:
        return len(symbols)
    returns = store.return_history(symbols=symbols, end_date=observed_on)
    if returns.empty:
        return len(symbols)
    correlations = returns.corr(min_periods=20)
    parent = {symbol: symbol for symbol in symbols}

    def find(symbol: str) -> str:
        while parent[symbol] != symbol:
            parent[symbol] = parent[parent[symbol]]
            symbol = parent[symbol]
        return symbol

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for left_index, left in enumerate(symbols):
        for right in symbols[left_index + 1 :]:
            if left not in correlations.index or right not in correlations.columns:
                continue
            value = correlations.loc[left, right]
            if not pd.isna(value) and abs(Decimal(str(value))) > _CORRELATION_LIMIT:
                union(left, right)
    return len({find(symbol) for symbol in symbols})


def _bars_by_candidate(frame: pd.DataFrame) -> dict[str, tuple[OHLCVBar, ...]]:
    if frame.empty:
        return {}
    result: dict[str, tuple[OHLCVBar, ...]] = {}
    for candidate_id, group in frame.groupby("candidate_id", sort=True):
        bars = tuple(
            OHLCVBar(
                observed_on=_pandas_date(row.trade_date),
                open_price=Decimal(str(row.open)),
                high_price=Decimal(str(row.high)),
                low_price=Decimal(str(row.low)),
                close_price=Decimal(str(row.close)),
                volume=Decimal(str(row.volume)),
            )
            for row in group.itertuples(index=False)
        )
        result[str(candidate_id)] = bars
    return result


def _pandas_date(value: object) -> date:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError("future bar trade_date must be a date")


def _entry_rule(recommendation: RecommendationReport) -> EntryRule:
    if recommendation.setup_entry_ready and recommendation.entry_zone_low is not None:
        return EntryRule.LIMIT_ENTRY_ZONE
    if recommendation.trade_plan.confirmation_entry is not None:
        return EntryRule.CONFIRMATION_ENTRY
    return EntryRule.RECORDED_REFERENCE


def _holding_period(recommendation: RecommendationReport) -> int:
    return max(
        1,
        recommendation.trade_plan.maximum_holding_period
        or recommendation.trade_plan.minimum_holding_period
        or int(recommendation.expected_value.expected_holding_period_days)
        or 20,
    )


def _is_institutionally_approved(decision: OpportunityDecision | None) -> bool:
    return decision is not None and decision.accepted


def _has_positive_allocation(report: object | None) -> bool:
    if report is None:
        return False
    return Decimal(str(getattr(report, "target_amount", "0"))) > _ZERO


def _estimated_position_capital(
    liquidity: LiquidityCapacityRecord | None,
) -> Decimal:
    if liquidity is None or liquidity.average_daily_turnover is None:
        return _ZERO
    return min(
        _MAX_POSITION_CAPITAL,
        liquidity.average_daily_turnover * _LIQUIDITY_PARTICIPATION,
    )


def _bounded_capacity(capacity: Decimal | None, requested: Decimal) -> Decimal | None:
    if capacity is None:
        return None
    return _q(max(_ZERO, min(capacity, requested)))


def _candidate_id(observed_on: date, symbol: str) -> str:
    return f"{observed_on.isoformat()}|{symbol.strip().upper()}"


def _safe_runtime_error(error: Exception) -> str:
    message = " ".join(str(error).split())
    return f"Canonical pipeline failed closed: {message[:300]}"


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return _q(sum(values, start=_ZERO) / Decimal(len(values)))


def _median_decimal(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return _q(Decimal(str(median(values))))


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


__all__ = ["AuditRunRequest", "CanonicalUniverseAuditEngine"]
