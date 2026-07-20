from __future__ import annotations

import csv
import hashlib
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from statistics import median
from types import MappingProxyType

from alpha.benchmark_replay.metrics import (
    idle_capital_records,
    period_returns,
    portfolio_statistics,
)
from alpha.benchmark_replay.models import (
    BASELINE_ID,
    BENCHMARK_VERSION,
    REPLAY_CLASSIFICATION,
    ApprovalStatistic,
    BenchmarkAvailability,
    BenchmarkComparison,
    BenchmarkManifest,
    BenchmarkPolicy,
    BenchmarkReplayReport,
    CandidateStatistic,
    OpportunityCaptureRecord,
    RejectionCategory,
    ReplayRequest,
)
from alpha.benchmark_replay.portfolio import MarketBar, PortfolioReplayEngine
from alpha.benchmark_replay.provenance import freeze_versions, replay_input_hash
from alpha.canonical_universe_audit.engine import (
    AuditRunRequest,
    CanonicalUniverseAuditEngine,
)
from alpha.canonical_universe_audit.models import (
    CandidateRankingRecord,
    GateAttributionRecord,
)
from alpha.canonical_universe_audit.store import LegacyMarketDataStore

_ZERO = Decimal("0")
_TWO = Decimal("0.01")
_CANONICAL_POLICY = BenchmarkPolicy()
_DEFAULT_MAJOR_OPPORTUNITIES = Path(
    ".alpha/canonical_integrity/ALPHA_CANONICAL_v1.0/major_opportunities.csv"
)
_DEFAULT_TRADABLE_ONSETS = Path(
    ".alpha/candidate_research/ALPHA_CANONICAL_v1.0/tradable_opportunity_onsets.csv"
)


class CanonicalBenchmarkReplayEngine:
    """Freeze and measure the unchanged Alpha stack over observed history."""

    def run(
        self,
        *,
        store: LegacyMarketDataStore,
        request: ReplayRequest | None = None,
        project_root: Path | str = Path("."),
        progress: Callable[[int, int, date], None] | None = None,
        major_opportunities_path: Path | None = None,
        tradable_onsets_path: Path | None = None,
    ) -> BenchmarkReplayReport:
        run_request = request or ReplayRequest()
        root = Path(project_root).resolve()
        dataset = store.manifest()
        dates = store.trade_dates(start=run_request.start, end=run_request.end)
        if not dates:
            raise ValueError("no observed market sessions match the replay window")
        versions = freeze_versions(project_root=root, warehouse=store.path.resolve())
        major_path = major_opportunities_path or root / _DEFAULT_MAJOR_OPPORTUNITIES
        onset_path = tradable_onsets_path or root / _DEFAULT_TRADABLE_ONSETS
        input_hash = replay_input_hash(
            versions=versions,
            policy=run_request.policy,
            start=dates[0].isoformat(),
            end=dates[-1].isoformat(),
            evidence_hashes={
                "major_opportunities": _path_hash(major_path),
                "tradable_onsets": _path_hash(onset_path),
            },
        )
        baseline = (
            dataset.dataset_version == "LEGACY_DATASET"
            and dates[0] == dataset.first_session
            and dates[-1] == dataset.last_session
            and run_request.policy == _CANONICAL_POLICY
        )
        run_id = BASELINE_ID if baseline else "CABR_RESEARCH_" + input_hash[:16].upper()
        audit = CanonicalUniverseAuditEngine().run(
            store=store,
            request=AuditRunRequest(
                start=dates[0],
                end=dates[-1],
                generated_at=datetime.combine(dates[-1], time.min, tzinfo=UTC),
            ),
            progress=progress,
        )
        if audit.executive.total_institutional_approvals > 0:
            raise RuntimeError(
                "CABR failed closed: institutional approvals require complete "
                "point-in-time execution snapshots before portfolio replay"
            )
        rankings_by_date: dict[date, list[CandidateRankingRecord]] = defaultdict(list)
        for ranking in audit.rankings:
            rankings_by_date[ranking.observed_on].append(ranking)
        gates_by_key: dict[tuple[date, str], list[GateAttributionRecord]] = defaultdict(
            list
        )
        for gate in audit.gates:
            gates_by_key[(gate.observed_on, gate.symbol)].append(gate)

        portfolio = PortfolioReplayEngine(run_request.policy)
        candidate_rows: list[CandidateStatistic] = []
        approval_rows: list[ApprovalStatistic] = []
        primary_rejections: Counter[str] = Counter()
        for day in audit.daily:
            bars = _market_bars(store, day.observed_on)
            portfolio.advance(day.observed_on, bars)
            rankings = tuple(rankings_by_date.get(day.observed_on, ()))
            for item in rankings:
                gates = tuple(gates_by_key.get((item.observed_on, item.symbol), ()))
                primary = next((gate for gate in gates if gate.primary), None)
                reason_code = (
                    ("ACCEPTED" if item.institutional_approved else "UNKNOWN")
                    if primary is None
                    else primary.gate_code
                )
                explanation = (
                    "All unchanged institutional gates passed."
                    if item.institutional_approved
                    else "No primary rejection attribution was available."
                    if primary is None
                    else primary.explanation
                )
                category = _rejection_category(reason_code)
                approval_rows.append(
                    ApprovalStatistic(
                        observed_on=item.observed_on,
                        symbol=item.symbol,
                        approved=item.institutional_approved,
                        opportunity_score=item.score,
                        opportunity_grade=(
                            "ACCEPTED" if item.institutional_approved else "REJECT"
                        ),
                        primary_reason_code=reason_code,
                        rejection_category=category,
                        explanation=explanation,
                    )
                )
                if not item.institutional_approved:
                    primary_rejections[reason_code] += 1
            candidate_rows.append(
                CandidateStatistic(
                    observed_on=day.observed_on,
                    period_week=_week(day.observed_on),
                    period_month=day.observed_on.strftime("%Y-%m"),
                    period_year=str(day.observed_on.year),
                    eligible_securities=day.eligible_securities,
                    technical_candidates=day.technical_candidates,
                    buy_candidates=sum(item.final_signal == "BUY" for item in rankings),
                    strong_buy_candidates=sum(
                        item.final_signal == "STRONG_BUY" for item in rankings
                    ),
                    institutional_approvals=day.institutional_approvals,
                    portfolio_entries=portfolio.entered_today,
                    rejected_ranking=0,
                    rejected_capital=0,
                    rejected_liquidity=0,
                    runtime_status=day.runtime_status,
                )
            )
        final_bars = _market_bars(store, dates[-1])
        portfolio.finish(dates[-1], final_bars)

        trades = tuple(portfolio.trades)
        curve = tuple(portfolio.capital_curve)
        stats = portfolio_statistics(
            starting_capital=run_request.policy.initial_capital,
            capital_curve=curve,
            trades=trades,
            turnover=portfolio.turnover,
        )
        opportunity = _opportunity_capture(
            major_path=major_path,
            onset_path=onset_path,
            start=dates[0],
            end=dates[-1],
            rankings=audit.rankings,
            trades=trades,
        )
        eligible_securities = _eligible_security_count(
            store=store,
            start=dates[0],
            end=dates[-1],
        )
        comparisons = _benchmark_comparison(
            store=store,
            dates=dates,
            starting_capital=run_request.policy.initial_capital,
            alpha_ending=stats.ending_capital,
            alpha_cagr=stats.cagr_percent,
            alpha_performance_available=eligible_securities > 0,
        )
        notes = (
            "Historical index membership is unavailable; this is not an index replay.",
            "Historical sector membership is unavailable and is not asserted.",
            "Decision inputs are limited to observations on or before each session.",
            "Opportunity labels use future data only after decisions for evaluation.",
            "Same-bar stop/target ambiguity is resolved stop first.",
            "No approval, recommendation, trade-plan, or production policy "
            "was changed.",
            f"Major-opportunity evidence: {_path_note(major_path, root)}.",
            f"Tradable-onset evidence: {_path_note(onset_path, root)}.",
        )
        manifest = BenchmarkManifest(
            baseline_id=BASELINE_ID if baseline else run_id,
            benchmark_version=BENCHMARK_VERSION,
            replay_classification=REPLAY_CLASSIFICATION,
            run_id=run_id,
            replay_start=dates[0],
            replay_end=dates[-1],
            sessions=len(dates),
            universe_label="OBSERVED HISTORICAL UNIVERSE",
            historical_index_membership="UNKNOWN / NOT USED",
            historical_sector_membership="UNKNOWN / NOT ASSERTED",
            point_in_time_enforced=True,
            no_future_leakage=True,
            policy=run_request.policy,
            versions=versions,
            input_hash=input_hash,
            artifact_hashes=MappingProxyType({}),
            notes=notes,
        )
        return BenchmarkReplayReport(
            manifest=manifest,
            candidate_statistics=tuple(candidate_rows),
            approval_statistics=tuple(approval_rows),
            trades=trades,
            position_history=tuple(portfolio.position_history),
            capital_curve=curve,
            monthly_returns=period_returns(curve, period="month"),
            yearly_returns=period_returns(curve, period="year"),
            opportunity_capture=opportunity,
            idle_capital=idle_capital_records(curve),
            benchmark_comparison=comparisons,
            portfolio_statistics=stats,
            top_rejection_reasons=tuple(
                sorted(
                    primary_rejections.items(), key=lambda item: (-item[1], item[0])
                )[:10]
            ),
            eligible_securities=eligible_securities,
            eligible_security_observations=sum(
                item.eligible_securities for item in audit.daily
            ),
        )


def _market_bars(
    store: LegacyMarketDataStore, observed_on: date
) -> dict[str, MarketBar]:
    frame = store.find_by_trade_date(observed_on)
    result: dict[str, MarketBar] = {}
    for row in frame.itertuples(index=False):
        open_price = Decimal(str(row.open))
        high = Decimal(str(row.high))
        low = Decimal(str(row.low))
        close = Decimal(str(row.close))
        if high < max(open_price, low, close) or low > min(open_price, high, close):
            continue
        result[str(row.symbol).strip().upper()] = MarketBar(
            open=open_price,
            high=high,
            low=low,
            close=close,
        )
    return result


def _opportunity_capture(
    *,
    major_path: Path,
    onset_path: Path,
    start: date,
    end: date,
    rankings: tuple[CandidateRankingRecord, ...],
    trades: tuple[object, ...],
) -> tuple[OpportunityCaptureRecord, ...]:
    candidates = {(item.observed_on, item.symbol) for item in rankings}
    approvals = {
        (item.observed_on, item.symbol)
        for item in rankings
        if item.institutional_approved
    }
    trade_rows = tuple(trades)
    onsets = _read_rows(onset_path)
    onset_counts = Counter(
        row.get("event_family", "ALL")
        for row in onsets
        if _within(row.get("onset_date"), start, end)
    )
    major = tuple(
        row
        for row in _read_rows(major_path)
        if _within(row.get("start_date"), start, end)
    )
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in major:
        grouped[row.get("event_definition", "UNKNOWN")].append(row)
    grouped["ALL"] = list(major)
    result: list[OpportunityCaptureRecord] = []
    for definition, rows in sorted(grouped.items()):
        generated = 0
        approved = 0
        entered = 0
        captured_moves: list[Decimal] = []
        missed_moves: list[Decimal] = []
        for row in rows:
            event_date = date.fromisoformat(row["start_date"])
            peak_date = date.fromisoformat(row["peak_date"])
            symbol = row["symbol"].strip().upper()
            move = Decimal(row["forward_return"]) * 100
            generated += (event_date, symbol) in candidates
            approved += (event_date, symbol) in approvals
            matching = tuple(
                item
                for item in trade_rows
                if getattr(item, "symbol") == symbol
                and event_date <= getattr(item, "entry_date") <= peak_date
            )
            if matching:
                entered += 1
                captured_moves.append(move)
            else:
                missed_moves.append(move)
        result.append(
            OpportunityCaptureRecord(
                opportunity_definition=definition,
                major_opportunities=len(rows),
                tradable_opportunities=(
                    sum(onset_counts.values())
                    if definition == "ALL"
                    else onset_counts.get(definition, 0)
                ),
                candidates_generated=generated,
                approved=approved,
                entered=entered,
                captured=entered,
                missed=len(rows) - entered,
                capture_rate_percent=(
                    None
                    if not rows
                    else _q(Decimal(entered) / Decimal(len(rows)) * 100)
                ),
                median_captured_move_percent=_median(captured_moves),
                median_missed_move_percent=_median(missed_moves),
            )
        )
    return tuple(result)


def _benchmark_comparison(
    *,
    store: LegacyMarketDataStore,
    dates: tuple[date, ...],
    starting_capital: Decimal,
    alpha_ending: Decimal,
    alpha_cagr: Decimal,
    alpha_performance_available: bool,
) -> tuple[BenchmarkComparison, ...]:
    equal_weight = observed_equal_weight_comparison(
        store, dates[0], dates[-1], starting_capital
    )
    nifty = _nifty_comparison(store, dates[0], dates[-1], starting_capital)
    if alpha_performance_available and equal_weight.cagr_percent is not None:
        equal_weight = BenchmarkComparison(
            benchmark=equal_weight.benchmark,
            availability=equal_weight.availability,
            start_date=equal_weight.start_date,
            end_date=equal_weight.end_date,
            starting_value=equal_weight.starting_value,
            ending_value=equal_weight.ending_value,
            total_return_percent=equal_weight.total_return_percent,
            cagr_percent=equal_weight.cagr_percent,
            excess_cagr_percent=_q(alpha_cagr - equal_weight.cagr_percent),
            reason=equal_weight.reason,
        )
    if alpha_performance_available and nifty.cagr_percent is not None:
        nifty = BenchmarkComparison(
            benchmark=nifty.benchmark,
            availability=nifty.availability,
            start_date=nifty.start_date,
            end_date=nifty.end_date,
            starting_value=nifty.starting_value,
            ending_value=nifty.ending_value,
            total_return_percent=nifty.total_return_percent,
            cagr_percent=nifty.cagr_percent,
            excess_cagr_percent=_q(alpha_cagr - nifty.cagr_percent),
            reason=nifty.reason,
        )
    alpha_total = (alpha_ending / starting_capital - 1) * 100
    alpha = BenchmarkComparison(
        benchmark=BASELINE_ID,
        availability=(
            BenchmarkAvailability.AVAILABLE
            if alpha_performance_available
            else BenchmarkAvailability.UNAVAILABLE
        ),
        start_date=dates[0] if alpha_performance_available else None,
        end_date=dates[-1] if alpha_performance_available else None,
        starting_value=starting_capital if alpha_performance_available else None,
        ending_value=alpha_ending if alpha_performance_available else None,
        total_return_percent=(
            _q(alpha_total) if alpha_performance_available else None
        ),
        cagr_percent=alpha_cagr if alpha_performance_available else None,
        excess_cagr_percent=_ZERO if alpha_performance_available else None,
        reason=(
            "Canonical Alpha portfolio capital curve."
            if alpha_performance_available
            else "No security met the 200-session complete-history requirement; "
            "strategy performance is unavailable."
        ),
    )
    return (alpha, equal_weight, nifty)


def observed_equal_weight_comparison(
    store: LegacyMarketDataStore,
    start: date,
    end: date,
    capital: Decimal,
) -> BenchmarkComparison:
    dataset_version = store.manifest().dataset_version
    population_label = (
        "historical-truth population"
        if dataset_version != "LEGACY_DATASET"
        else "legacy market population"
    )
    rows = store.connection.execute(
        """
        WITH lagged AS (
            SELECT
                trade_date,
                close,
                LAG(close) OVER (
                    PARTITION BY UPPER(symbol) ORDER BY trade_date
                ) AS prior_close
            FROM daily_prices
            WHERE close > 0 AND trade_date <= ?
        ), daily AS (
            SELECT trade_date, AVG(close / prior_close - 1) AS equal_weight_return
            FROM lagged
            WHERE trade_date BETWEEN ? AND ? AND prior_close > 0
            GROUP BY trade_date
            ORDER BY trade_date
        )
        SELECT trade_date, equal_weight_return FROM daily ORDER BY trade_date
        """,
        (end, start, end),
    ).fetchall()
    value = capital
    for _, raw_return in rows:
        daily_return = Decimal(str(raw_return))
        value *= Decimal("1") + daily_return
        if value <= 0 or value.adjusted() > 18:
            return BenchmarkComparison(
                benchmark="OBSERVED_EQUAL_WEIGHT_UNIVERSE",
                availability=BenchmarkAvailability.UNAVAILABLE,
                start_date=None,
                end_date=None,
                starting_value=None,
                ending_value=None,
                total_return_percent=None,
                cagr_percent=None,
                excess_cagr_percent=None,
                reason=(
                    "Legacy symbol and corporate-action gaps produce a "
                    "non-economic compounded series; comparison failed closed."
                ),
            )
    years = Decimal((end - start).days) / Decimal("365.25")
    cagr = _ZERO if years <= 0 else _power(value / capital, Decimal("1") / years) - 1
    return BenchmarkComparison(
        benchmark="OBSERVED_EQUAL_WEIGHT_UNIVERSE",
        availability=BenchmarkAvailability.AVAILABLE,
        start_date=start,
        end_date=end,
        starting_value=capital,
        ending_value=_q(value),
        total_return_percent=_q((value / capital - 1) * 100),
        cagr_percent=_q(cagr * 100),
        excess_cagr_percent=None,
        reason=(
            f"Daily equal-weight return of securities observed in the {population_label}; "
            "this is not an investable index and has no costs."
        ),
    )


def _nifty_comparison(
    store: LegacyMarketDataStore,
    start: date,
    end: date,
    capital: Decimal,
) -> BenchmarkComparison:
    aliases = ("NIFTY50", "NIFTY 50", "^NSEI")
    rows = store.connection.execute(
        """
        SELECT trade_date, close
        FROM daily_prices
        WHERE UPPER(symbol) IN (?, ?, ?)
          AND trade_date BETWEEN ? AND ?
          AND close > 0
        ORDER BY trade_date
        """,
        (*aliases, start, end),
    ).fetchall()
    if len(rows) < 2:
        return BenchmarkComparison(
            benchmark="NIFTY_50_BUY_AND_HOLD",
            availability=BenchmarkAvailability.UNAVAILABLE,
            start_date=None,
            end_date=None,
            starting_value=None,
            ending_value=None,
            total_return_percent=None,
            cagr_percent=None,
            excess_cagr_percent=None,
            reason=(
                "Historical NIFTY 50 index OHLC is unavailable in the frozen warehouse."
            ),
        )
    first_date, first_close = rows[0]
    last_date, last_close = rows[-1]
    ratio = Decimal(str(last_close)) / Decimal(str(first_close))
    value = capital * ratio
    years = Decimal((last_date - first_date).days) / Decimal("365.25")
    cagr = _ZERO if years <= 0 else _power(ratio, Decimal("1") / years) - 1
    return BenchmarkComparison(
        benchmark="NIFTY_50_BUY_AND_HOLD",
        availability=BenchmarkAvailability.AVAILABLE,
        start_date=first_date,
        end_date=last_date,
        starting_value=capital,
        ending_value=_q(value),
        total_return_percent=_q((ratio - 1) * 100),
        cagr_percent=_q(cagr * 100),
        excess_cagr_percent=None,
        reason="Observed historical index OHLC in the frozen warehouse.",
    )


def _rejection_category(reason_code: str) -> RejectionCategory:
    if reason_code == "WEAK_VERDICT":
        return RejectionCategory.NO_CANDIDATE
    if reason_code in {"WEAK_SETUP", "WEAK_CONFIDENCE"}:
        return RejectionCategory.WEAK_SCORE
    if reason_code in {"PENDING_ENTRY_TRIGGER", "LATE_ENTRY"}:
        return RejectionCategory.TIMING
    if reason_code in {
        "POOR_REWARD_RISK",
        "EXCESS_DOWNSIDE_RISK",
        "MISSING_TRADE_PLAN",
    }:
        return RejectionCategory.TRADE_PLAN
    if reason_code == "INSUFFICIENT_CAPACITY":
        return RejectionCategory.LIQUIDITY
    if reason_code in {
        "INSUFFICIENT_EVIDENCE",
        "POOR_DATA_COMPLETENESS",
        "POOR_HISTORICAL_EDGE",
    }:
        return RejectionCategory.APPROVAL
    if reason_code.startswith("RANKING"):
        return RejectionCategory.RANKING
    if reason_code.startswith("CAPITAL"):
        return RejectionCategory.CAPITAL
    return RejectionCategory.UNKNOWN


def _read_rows(path: Path) -> tuple[dict[str, str], ...]:
    if not path.exists():
        return ()
    with path.open(newline="", encoding="utf-8") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


def _within(value: str | None, start: date, end: date) -> bool:
    if not value:
        return False
    observed = date.fromisoformat(value)
    return start <= observed <= end


def _path_hash(path: Path) -> str:
    return (
        "UNAVAILABLE"
        if not path.exists()
        else hashlib.sha256(path.read_bytes()).hexdigest()
    )


def _path_note(path: Path, project_root: Path) -> str:
    if not path.exists():
        return "UNAVAILABLE"
    try:
        label = path.resolve().relative_to(project_root.resolve())
    except ValueError:
        label = Path(path.name)
    return f"{label} sha256={_path_hash(path)}"


def _eligible_security_count(
    *,
    store: LegacyMarketDataStore,
    start: date,
    end: date,
) -> int:
    row = store.connection.execute(
        """
        WITH history AS (
            SELECT UPPER(symbol) AS symbol, COUNT(*) AS observations
            FROM daily_prices
            WHERE trade_date <= ?
              AND open > 0 AND high > 0 AND low > 0 AND close > 0 AND volume >= 0
            GROUP BY UPPER(symbol)
            HAVING COUNT(*) >= 200
        ), observed AS (
            SELECT DISTINCT UPPER(symbol) AS symbol
            FROM daily_prices
            WHERE trade_date BETWEEN ? AND ?
        )
        SELECT COUNT(*)
        FROM history
        JOIN observed USING (symbol)
        """,
        (end, start, end),
    ).fetchone()
    return 0 if row is None else int(row[0])


def _week(value: date) -> str:
    year, week, _ = value.isocalendar()
    return f"{year}-W{week:02d}"


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return _q(Decimal(str(median(values))))


def _power(base: Decimal, exponent: Decimal) -> Decimal:
    return Decimal(str(float(base) ** float(exponent)))


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


__all__ = [
    "CanonicalBenchmarkReplayEngine",
    "observed_equal_weight_comparison",
]
