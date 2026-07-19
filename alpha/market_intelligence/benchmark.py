from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from statistics import pstdev
from typing import Any

import pandas as pd

_ZERO = Decimal("0")
_ONE = Decimal("1")
_FOUR = Decimal("0.0001")
_VOLATILITY_LOOKBACK = 20
_ATR_LOOKBACK = 14
_MAX_VALID_STALENESS_DAYS = 5


class BenchmarkMappingFinding(StrEnum):
    CANONICAL_BENCHMARK_CONFIRMED = "CANONICAL_BENCHMARK_CONFIRMED"
    MULTIPLE_BENCHMARK_DEFINITIONS = "MULTIPLE_BENCHMARK_DEFINITIONS"
    BENCHMARK_NOT_CONFIGURED = "BENCHMARK_NOT_CONFIGURED"
    BENCHMARK_PROVIDER_MAPPING_MISSING = "BENCHMARK_PROVIDER_MAPPING_MISSING"
    BENCHMARK_HISTORY_NOT_INGESTED = "BENCHMARK_HISTORY_NOT_INGESTED"
    BENCHMARK_HISTORY_EXISTS_BUT_NOT_PROPAGATED = (
        "BENCHMARK_HISTORY_EXISTS_BUT_NOT_PROPAGATED"
    )


class BenchmarkAlignment(StrEnum):
    EXACT_TIMESTAMP = "EXACT_TIMESTAMP"
    SAME_TRADING_DAY = "SAME_TRADING_DAY"
    PREVIOUS_COMPLETED_SESSION = "PREVIOUS_COMPLETED_SESSION"
    CARRIED_FORWARD_VALID = "CARRIED_FORWARD_VALID"
    CARRIED_FORWARD_STALE = "CARRIED_FORWARD_STALE"
    FUTURE_BAR_REJECTED = "FUTURE_BAR_REJECTED"
    BENCHMARK_BAR_UNAVAILABLE = "BENCHMARK_BAR_UNAVAILABLE"


class BenchmarkFeatureCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    MINIMUM_VIABLE = "MINIMUM_VIABLE"
    INSUFFICIENT = "INSUFFICIENT"
    UNAVAILABLE = "UNAVAILABLE"


class BenchmarkAuditConclusion(StrEnum):
    BENCHMARK_CAPTURE_IS_COMPLETE = "BENCHMARK_CAPTURE_IS_COMPLETE"
    BENCHMARK_HISTORY_EXISTS_BUT_NOT_PROPAGATED = (
        "BENCHMARK_HISTORY_EXISTS_BUT_NOT_PROPAGATED"
    )
    BENCHMARK_HISTORY_NOT_INGESTED = "BENCHMARK_HISTORY_NOT_INGESTED"
    BENCHMARK_PROVIDER_MAPPING_IS_PRIMARY_BOTTLENECK = (
        "BENCHMARK_PROVIDER_MAPPING_IS_PRIMARY_BOTTLENECK"
    )
    BENCHMARK_LOOKBACK_IS_PRIMARY_BOTTLENECK = (
        "BENCHMARK_LOOKBACK_IS_PRIMARY_BOTTLENECK"
    )
    BENCHMARK_TIMESTAMP_ALIGNMENT_IS_PRIMARY_BOTTLENECK = (
        "BENCHMARK_TIMESTAMP_ALIGNMENT_IS_PRIMARY_BOTTLENECK"
    )
    BENCHMARK_STALENESS_IS_PRIMARY_BOTTLENECK = (
        "BENCHMARK_STALENESS_IS_PRIMARY_BOTTLENECK"
    )
    SNAPSHOT_COMPLETENESS_RULES_ARE_PRIMARY_BOTTLENECK = (
        "SNAPSHOT_COMPLETENESS_RULES_ARE_PRIMARY_BOTTLENECK"
    )
    NON_BENCHMARK_MARKET_INPUTS_ARE_PRIMARY_BOTTLENECK = (
        "NON_BENCHMARK_MARKET_INPUTS_ARE_PRIMARY_BOTTLENECK"
    )
    INSUFFICIENT_EVIDENCE_FOR_BENCHMARK_CONCLUSION = (
        "INSUFFICIENT_EVIDENCE_FOR_BENCHMARK_CONCLUSION"
    )


class BenchmarkNextMilestone(StrEnum):
    AUTHORITATIVE_HISTORICAL_MARKET_DATA_BACKFILL_DESIGN = (
        "AUTHORITATIVE_HISTORICAL_MARKET_DATA_BACKFILL_DESIGN"
    )
    HARDEN_BENCHMARK_PROVIDER_MAPPING = "HARDEN_BENCHMARK_PROVIDER_MAPPING"
    EXPAND_BENCHMARK_HISTORICAL_COVERAGE = "EXPAND_BENCHMARK_HISTORICAL_COVERAGE"
    REPAIR_BENCHMARK_TIMESTAMP_ALIGNMENT = "REPAIR_BENCHMARK_TIMESTAMP_ALIGNMENT"
    ADD_MARKET_BREADTH_CAPTURE = "ADD_MARKET_BREADTH_CAPTURE"
    ADD_SECTOR_MARKET_STATE_CAPTURE = "ADD_SECTOR_MARKET_STATE_CAPTURE"
    HARDEN_SNAPSHOT_COMPLETENESS_SEMANTICS = "HARDEN_SNAPSHOT_COMPLETENESS_SEMANTICS"
    COLLECT_MORE_AUTHORITATIVE_SNAPSHOTS = "COLLECT_MORE_AUTHORITATIVE_SNAPSHOTS"


@dataclass(frozen=True, slots=True)
class BenchmarkConfiguration:
    logical_name: str
    exchange: str
    provider_symbol: str
    instrument_identifier: str
    asset_type: str
    currency: str
    timezone: str
    session_calendar: str
    minimum_history_bars: int
    source_priority: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.minimum_history_bars <= 0:
            raise ValueError("minimum_history_bars must be positive")
        for field_name in (
            "logical_name",
            "exchange",
            "provider_symbol",
            "instrument_identifier",
            "asset_type",
            "currency",
            "timezone",
            "session_calendar",
        ):
            value = getattr(self, field_name).strip()
            if not value:
                raise ValueError(f"{field_name} cannot be empty")
            object.__setattr__(self, field_name, value)
        object.__setattr__(
            self,
            "provider_symbol",
            self.provider_symbol.strip().upper(),
        )
        object.__setattr__(
            self,
            "source_priority",
            tuple(source.strip() for source in self.source_priority if source.strip()),
        )


@dataclass(frozen=True, slots=True)
class BenchmarkState:
    configuration: BenchmarkConfiguration
    benchmark_close: Decimal | None
    benchmark_return_1d: Decimal | None
    benchmark_return_5d: Decimal | None
    benchmark_return_20d: Decimal | None
    benchmark_dma_20: Decimal | None
    benchmark_dma_50: Decimal | None
    benchmark_dma_200: Decimal | None
    benchmark_above_20dma: bool | None
    benchmark_above_50dma: bool | None
    benchmark_above_200dma: bool | None
    benchmark_distance_20dma: Decimal | None
    benchmark_distance_50dma: Decimal | None
    benchmark_distance_200dma: Decimal | None
    benchmark_atr_14: Decimal | None
    benchmark_volatility: Decimal | None
    bars_available: int
    latest_bar_timestamp: datetime | None
    staleness_days: int | None
    alignment: BenchmarkAlignment
    missing_fields: tuple[str, ...]
    completeness: BenchmarkFeatureCompleteness

    @property
    def has_minimum_features(self) -> bool:
        return (
            self.benchmark_close is not None and self.benchmark_return_20d is not None
        )


@dataclass(frozen=True, slots=True)
class BenchmarkHistoryAudit:
    configuration: BenchmarkConfiguration
    finding: BenchmarkMappingFinding
    historical_source: str
    runtime_source: str
    first_available_date: date | None
    last_available_date: date | None
    bar_frequency: str
    row_count: int
    duplicate_count: int
    missing_date_count: int


@dataclass(frozen=True, slots=True)
class BenchmarkCoverageReport:
    history: BenchmarkHistoryAudit
    candidate_dates_covered: int
    candidate_dates_not_covered: int
    exact_date_coverage: int
    previous_session_coverage: int
    stale_coverage: int
    insufficient_lookback_dates: int
    return_1d_coverage: int
    return_5d_coverage: int
    return_20d_coverage: int
    dma_20_coverage: int
    dma_50_coverage: int
    dma_200_coverage: int
    atr_coverage: int
    volatility_coverage: int
    complete_snapshot_count: int
    partial_snapshot_count: int
    insufficient_snapshot_count: int
    fallback_neutral_count: int
    genuine_neutral_count: int
    primary_conclusion: BenchmarkAuditConclusion
    secondary_conclusions: tuple[BenchmarkAuditConclusion, ...]
    recommended_next_milestone: BenchmarkNextMilestone
    prohibited_next_action: str


def canonical_benchmark_configuration(
    *,
    provider_symbol: str | None = None,
) -> BenchmarkConfiguration:
    symbol = (
        provider_symbol
        or os.environ.get("ALPHA_BENCHMARK_PROVIDER_SYMBOL")
        or "NIFTYBEES"
    )
    return BenchmarkConfiguration(
        logical_name="NIFTY 50 broad-market ETF proxy",
        exchange="NSE",
        provider_symbol=symbol,
        instrument_identifier=f"NSE_EQ|{symbol.strip().upper()}",
        asset_type="ETF",
        currency="INR",
        timezone="Asia/Kolkata",
        session_calendar="NSE",
        minimum_history_bars=220,
        source_priority=("local_daily_prices", "nse_bhavcopy"),
    )


class BenchmarkStateBuilder:
    def __init__(
        self,
        *,
        configuration: BenchmarkConfiguration | None = None,
        stale_days: int = _MAX_VALID_STALENESS_DAYS,
    ) -> None:
        if stale_days < 0:
            raise ValueError("stale_days cannot be negative")
        self.configuration = configuration or canonical_benchmark_configuration()
        self.stale_days = stale_days

    def build(
        self,
        *,
        bars: pd.DataFrame,
        decision_as_of: datetime,
    ) -> BenchmarkState:
        as_of = _aware(decision_as_of)
        frame = _prepare_bars(bars, provider_symbol=self.configuration.provider_symbol)
        if frame.empty:
            return self._empty(BenchmarkAlignment.BENCHMARK_BAR_UNAVAILABLE)
        frame = frame[frame["trade_date"] <= as_of.date()].sort_values("trade_date")
        if frame.empty:
            return self._empty(BenchmarkAlignment.FUTURE_BAR_REJECTED)

        closes = tuple(Decimal(str(value)) for value in frame["close"].tolist())
        highs = tuple(Decimal(str(value)) for value in frame["high"].tolist())
        lows = tuple(Decimal(str(value)) for value in frame["low"].tolist())
        latest_date = frame.iloc[-1]["trade_date"]
        latest_timestamp = datetime.combine(
            latest_date,
            datetime.min.time(),
            tzinfo=UTC,
        )
        staleness = (as_of.date() - latest_date).days
        alignment = _alignment(
            as_of=as_of,
            latest_date=latest_date,
            stale_days=self.stale_days,
        )
        close = closes[-1]
        dma_20 = _window_average(closes, 20)
        dma_50 = _window_average(closes, 50)
        dma_200 = _window_average(closes, 200)
        returns = {
            "benchmark_return_1d": _return(closes, 1),
            "benchmark_return_5d": _return(closes, 5),
            "benchmark_return_20d": _return(closes, 20),
        }
        atr = _atr(highs=highs, lows=lows, closes=closes, lookback=_ATR_LOOKBACK)
        volatility = _volatility(closes=closes, lookback=_VOLATILITY_LOOKBACK)
        missing = _missing_fields(
            {
                "benchmark_close": close,
                **returns,
                "benchmark_dma_20": dma_20,
                "benchmark_dma_50": dma_50,
                "benchmark_dma_200": dma_200,
                "benchmark_atr": atr,
                "benchmark_volatility": volatility,
            }
        )
        completeness = _completeness(missing, alignment=alignment)
        return BenchmarkState(
            configuration=self.configuration,
            benchmark_close=close,
            benchmark_return_1d=returns["benchmark_return_1d"],
            benchmark_return_5d=returns["benchmark_return_5d"],
            benchmark_return_20d=returns["benchmark_return_20d"],
            benchmark_dma_20=dma_20,
            benchmark_dma_50=dma_50,
            benchmark_dma_200=dma_200,
            benchmark_above_20dma=None if dma_20 is None else close > dma_20,
            benchmark_above_50dma=None if dma_50 is None else close > dma_50,
            benchmark_above_200dma=None if dma_200 is None else close > dma_200,
            benchmark_distance_20dma=_relative(close, dma_20),
            benchmark_distance_50dma=_relative(close, dma_50),
            benchmark_distance_200dma=_relative(close, dma_200),
            benchmark_atr_14=atr,
            benchmark_volatility=volatility,
            bars_available=len(frame),
            latest_bar_timestamp=latest_timestamp,
            staleness_days=staleness,
            alignment=alignment,
            missing_fields=missing,
            completeness=completeness,
        )

    def _empty(self, alignment: BenchmarkAlignment) -> BenchmarkState:
        missing = (
            "benchmark_close",
            "benchmark_return_1d",
            "benchmark_return_5d",
            "benchmark_return_20d",
            "benchmark_dma_20",
            "benchmark_dma_50",
            "benchmark_dma_200",
            "benchmark_atr",
            "benchmark_volatility",
        )
        return BenchmarkState(
            configuration=self.configuration,
            benchmark_close=None,
            benchmark_return_1d=None,
            benchmark_return_5d=None,
            benchmark_return_20d=None,
            benchmark_dma_20=None,
            benchmark_dma_50=None,
            benchmark_dma_200=None,
            benchmark_above_20dma=None,
            benchmark_above_50dma=None,
            benchmark_above_200dma=None,
            benchmark_distance_20dma=None,
            benchmark_distance_50dma=None,
            benchmark_distance_200dma=None,
            benchmark_atr_14=None,
            benchmark_volatility=None,
            bars_available=0,
            latest_bar_timestamp=None,
            staleness_days=None,
            alignment=alignment,
            missing_fields=missing,
            completeness=BenchmarkFeatureCompleteness.UNAVAILABLE,
        )


def benchmark_history_audit(
    *,
    repository: Any,
    configuration: BenchmarkConfiguration | None = None,
    end_date: date | None = None,
    limit: int = 5000,
) -> BenchmarkHistoryAudit:
    config = configuration or canonical_benchmark_configuration()
    frame = repository.find_history_by_symbols(
        symbols=(config.provider_symbol,),
        end_date=end_date or date.today(),
        limit=limit,
    )
    frame = _prepare_bars(frame, provider_symbol=config.provider_symbol)
    duplicates = (
        0 if frame.empty else int(frame.duplicated(subset=["trade_date"]).sum())
    )
    dates = tuple(frame["trade_date"].tolist()) if not frame.empty else ()
    missing_dates = _missing_business_days(dates)
    finding = (
        BenchmarkMappingFinding.BENCHMARK_HISTORY_NOT_INGESTED
        if frame.empty
        else BenchmarkMappingFinding.CANONICAL_BENCHMARK_CONFIRMED
    )
    return BenchmarkHistoryAudit(
        configuration=config,
        finding=finding,
        historical_source="daily_prices",
        runtime_source="local_daily_prices",
        first_available_date=min(dates) if dates else None,
        last_available_date=max(dates) if dates else None,
        bar_frequency="1d",
        row_count=len(frame),
        duplicate_count=duplicates,
        missing_date_count=missing_dates,
    )


def benchmark_coverage_report(
    *,
    repository: Any,
    snapshots: tuple[Any, ...],
    candidate_dates: tuple[date, ...] = (),
    configuration: BenchmarkConfiguration | None = None,
) -> BenchmarkCoverageReport:
    config = configuration or canonical_benchmark_configuration()
    history = benchmark_history_audit(repository=repository, configuration=config)
    dates = candidate_dates or tuple(snapshot.market_date for snapshot in snapshots)
    unique_dates = tuple(sorted(set(dates)))
    history_dates = _history_dates(repository=repository, configuration=config)
    covered = sum(1 for item in unique_dates if item in history_dates)
    states = tuple(
        BenchmarkStateBuilder(configuration=config).build(
            bars=repository.find_history_by_symbols(
                symbols=(config.provider_symbol,),
                end_date=item,
                limit=config.minimum_history_bars,
            ),
            decision_as_of=datetime.combine(item, datetime.max.time(), tzinfo=UTC),
        )
        for item in unique_dates
    )
    complete = sum(
        1
        for snapshot in snapshots
        if getattr(snapshot, "input_completeness", None)
        and snapshot.input_completeness.value == "COMPLETE"
    )
    partial = sum(
        1
        for snapshot in snapshots
        if getattr(snapshot, "input_completeness", None)
        and snapshot.input_completeness.value == "PARTIAL"
    )
    insufficient = sum(
        1
        for snapshot in snapshots
        if getattr(snapshot, "input_completeness", None)
        and snapshot.input_completeness.value
        in {"INSUFFICIENT", "UNAVAILABLE", "MINIMUM_VIABLE"}
    )
    fallback_neutral = sum(
        1
        for snapshot in snapshots
        if snapshot.classifier_regime == "NEUTRAL" and snapshot.fallback_applied
    )
    genuine_neutral = sum(
        1
        for snapshot in snapshots
        if snapshot.classifier_regime == "NEUTRAL" and not snapshot.fallback_applied
    )
    conclusion, milestone = _audit_decision(
        history=history,
        states=states,
        snapshots=snapshots,
        genuine_neutral=genuine_neutral,
    )
    return BenchmarkCoverageReport(
        history=history,
        candidate_dates_covered=covered,
        candidate_dates_not_covered=max(len(unique_dates) - covered, 0),
        exact_date_coverage=sum(
            1
            for state in states
            if state.alignment is BenchmarkAlignment.SAME_TRADING_DAY
        ),
        previous_session_coverage=sum(
            1
            for state in states
            if state.alignment is BenchmarkAlignment.PREVIOUS_COMPLETED_SESSION
        ),
        stale_coverage=sum(
            1
            for state in states
            if state.alignment is BenchmarkAlignment.CARRIED_FORWARD_STALE
        ),
        insufficient_lookback_dates=sum(
            1
            for state in states
            if state.completeness
            in {
                BenchmarkFeatureCompleteness.INSUFFICIENT,
                BenchmarkFeatureCompleteness.UNAVAILABLE,
            }
        ),
        return_1d_coverage=sum(1 for state in states if state.benchmark_return_1d),
        return_5d_coverage=sum(1 for state in states if state.benchmark_return_5d),
        return_20d_coverage=sum(1 for state in states if state.benchmark_return_20d),
        dma_20_coverage=sum(1 for state in states if state.benchmark_dma_20),
        dma_50_coverage=sum(1 for state in states if state.benchmark_dma_50),
        dma_200_coverage=sum(1 for state in states if state.benchmark_dma_200),
        atr_coverage=sum(1 for state in states if state.benchmark_atr_14),
        volatility_coverage=sum(1 for state in states if state.benchmark_volatility),
        complete_snapshot_count=complete,
        partial_snapshot_count=partial,
        insufficient_snapshot_count=insufficient,
        fallback_neutral_count=fallback_neutral,
        genuine_neutral_count=genuine_neutral,
        primary_conclusion=conclusion,
        secondary_conclusions=(),
        recommended_next_milestone=milestone,
        prohibited_next_action=(
            "Do not tune thresholds, neutral boundaries, recommendation weights, "
            "retracement signs, candidate-generation rules, gates, verdicts, "
            "approvals, trade plans, or allocation from this benchmark audit."
        ),
    )


def render_benchmark_configuration(config: BenchmarkConfiguration) -> tuple[str, ...]:
    return (
        "Canonical Benchmark",
        f"Logical Name: {config.logical_name}",
        f"Exchange: {config.exchange}",
        f"Provider Symbol: {config.provider_symbol}",
        f"Instrument Identifier: {config.instrument_identifier}",
        f"Asset Type: {config.asset_type}",
        f"Currency: {config.currency}",
        f"Timezone: {config.timezone}",
        f"Session Calendar: {config.session_calendar}",
        f"Minimum History Bars: {config.minimum_history_bars}",
        f"Source Priority: {', '.join(config.source_priority)}",
    )


def render_benchmark_history(report: BenchmarkHistoryAudit) -> tuple[str, ...]:
    return (
        "Benchmark History",
        f"Mapping Status: {report.finding.value}",
        f"Historical Source: {report.historical_source}",
        f"Runtime Source: {report.runtime_source}",
        f"First Available Date: {_date_text(report.first_available_date)}",
        f"Last Available Date: {_date_text(report.last_available_date)}",
        f"Bar Frequency: {report.bar_frequency}",
        f"Row Count: {report.row_count}",
        f"Duplicate Count: {report.duplicate_count}",
        f"Missing-Date Count: {report.missing_date_count}",
    )


def render_benchmark_coverage(report: BenchmarkCoverageReport) -> tuple[str, ...]:
    return (
        "Benchmark Market-State Coverage Audit",
        *render_benchmark_configuration(report.history.configuration),
        "",
        "Benchmark Mapping Status",
        f"- {report.history.finding.value}",
        "",
        "Historical Coverage",
        f"- Rows Available: {report.history.row_count}",
        f"- First Date: {_date_text(report.history.first_available_date)}",
        f"- Last Date: {_date_text(report.history.last_available_date)}",
        f"- Duplicate Rows: {report.history.duplicate_count}",
        f"- Missing Dates: {report.history.missing_date_count}",
        "",
        "Point-in-Time Coverage",
        f"- Candidate Dates Covered: {report.candidate_dates_covered}",
        f"- Candidate Dates Not Covered: {report.candidate_dates_not_covered}",
        f"- Exact-Date Coverage: {report.exact_date_coverage}",
        f"- Previous-Session Coverage: {report.previous_session_coverage}",
        f"- Stale Coverage: {report.stale_coverage}",
        f"- Insufficient Lookback Dates: {report.insufficient_lookback_dates}",
        "",
        "Feature Coverage",
        f"- 1-Day Return: {report.return_1d_coverage}",
        f"- 5-Day Return: {report.return_5d_coverage}",
        f"- 20-Day Return: {report.return_20d_coverage}",
        f"- 20-DMA: {report.dma_20_coverage}",
        f"- 50-DMA: {report.dma_50_coverage}",
        f"- 200-DMA: {report.dma_200_coverage}",
        f"- ATR: {report.atr_coverage}",
        f"- Volatility: {report.volatility_coverage}",
        "",
        "Snapshot Completeness",
        f"- Complete: {report.complete_snapshot_count}",
        f"- Partial: {report.partial_snapshot_count}",
        f"- Insufficient: {report.insufficient_snapshot_count}",
        f"- Fallback-Neutral Count: {report.fallback_neutral_count}",
        f"- Genuine-Neutral Count: {report.genuine_neutral_count}",
        "",
        f"Primary Conclusion: {report.primary_conclusion.value}",
        f"Recommended Next Milestone: {report.recommended_next_milestone.value}",
        f"Explicitly Prohibited Next Action: {report.prohibited_next_action}",
    )


def render_benchmark_completeness(
    snapshots: tuple[Any, ...],
) -> tuple[str, ...]:
    counts: dict[str, int] = {}
    fallback: dict[str, int] = {}
    for snapshot in snapshots:
        counts[snapshot.input_completeness.value] = (
            counts.get(snapshot.input_completeness.value, 0) + 1
        )
        fallback[snapshot.fallback_reason.value] = (
            fallback.get(snapshot.fallback_reason.value, 0) + 1
        )
    return (
        "Market-State Snapshot Completeness",
        f"Snapshots: {len(snapshots)}",
        f"Completeness: {_pairs(tuple(sorted(counts.items())))}",
        f"Fallback Reasons: {_pairs(tuple(sorted(fallback.items())))}",
    )


def export_benchmark_coverage_json(
    report: BenchmarkCoverageReport,
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_report_dict(report), indent=2), encoding="utf-8")
    return path


def export_benchmark_coverage_csv(
    report: BenchmarkCoverageReport,
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = _report_dict(report)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(row))
        writer.writeheader()
        writer.writerow(row)
    return path


def _prepare_bars(
    frame: pd.DataFrame,
    *,
    provider_symbol: str,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=("trade_date", "open", "high", "low", "close"))
    data = frame.copy()
    data["symbol"] = data["symbol"].astype(str).str.strip().str.upper()
    data = data[data["symbol"] == provider_symbol.strip().upper()]
    data["trade_date"] = pd.to_datetime(data["trade_date"]).dt.date
    for column in ("open", "high", "low", "close"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["open", "high", "low", "close"])
    data = data[(data["open"] > 0) & (data["high"] > 0) & (data["low"] > 0)]
    data = data[data["close"] > 0]
    data = data.drop_duplicates(subset=["trade_date"], keep="last")
    return data.sort_values("trade_date").reset_index(drop=True)


def _alignment(
    *,
    as_of: datetime,
    latest_date: date,
    stale_days: int,
) -> BenchmarkAlignment:
    if latest_date > as_of.date():
        return BenchmarkAlignment.FUTURE_BAR_REJECTED
    staleness = (as_of.date() - latest_date).days
    if staleness == 0:
        return BenchmarkAlignment.SAME_TRADING_DAY
    if staleness == 1:
        return BenchmarkAlignment.PREVIOUS_COMPLETED_SESSION
    if staleness <= stale_days:
        return BenchmarkAlignment.CARRIED_FORWARD_VALID
    return BenchmarkAlignment.CARRIED_FORWARD_STALE


def _return(values: tuple[Decimal, ...], window: int) -> Decimal | None:
    if len(values) <= window:
        return None
    previous = values[-1 - window]
    if previous <= _ZERO:
        return None
    return ((values[-1] / previous) - _ONE).quantize(_FOUR)


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, _ZERO) / Decimal(len(values))).quantize(_FOUR)


def _window_average(values: tuple[Decimal, ...], window: int) -> Decimal | None:
    if len(values) < window:
        return None
    return _average(values[-window:])


def _relative(value: Decimal, reference: Decimal | None) -> Decimal | None:
    if reference is None or reference <= _ZERO:
        return None
    return ((value / reference) - _ONE).quantize(_FOUR)


def _atr(
    *,
    highs: tuple[Decimal, ...],
    lows: tuple[Decimal, ...],
    closes: tuple[Decimal, ...],
    lookback: int,
) -> Decimal | None:
    if len(closes) <= lookback:
        return None
    true_ranges = []
    start = len(closes) - lookback
    for index in range(start, len(closes)):
        previous_close = closes[index - 1]
        true_ranges.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - previous_close),
                abs(lows[index] - previous_close),
            )
        )
    return (sum(true_ranges, _ZERO) / Decimal(lookback)).quantize(_FOUR)


def _volatility(*, closes: tuple[Decimal, ...], lookback: int) -> Decimal | None:
    if len(closes) <= lookback:
        return None
    returns = []
    for index in range(len(closes) - lookback, len(closes)):
        previous = closes[index - 1]
        if previous <= _ZERO:
            return None
        returns.append(float((closes[index] / previous) - _ONE))
    return Decimal(str(pstdev(returns))).quantize(_FOUR)


def _missing_fields(values: dict[str, Decimal | None]) -> tuple[str, ...]:
    return tuple(key for key, value in sorted(values.items()) if value is None)


def _completeness(
    missing: tuple[str, ...],
    *,
    alignment: BenchmarkAlignment,
) -> BenchmarkFeatureCompleteness:
    if alignment in {
        BenchmarkAlignment.BENCHMARK_BAR_UNAVAILABLE,
        BenchmarkAlignment.FUTURE_BAR_REJECTED,
    }:
        return BenchmarkFeatureCompleteness.UNAVAILABLE
    required = {"benchmark_close", "benchmark_return_20d", "benchmark_dma_50"}
    if required & set(missing):
        return BenchmarkFeatureCompleteness.INSUFFICIENT
    if not missing:
        return BenchmarkFeatureCompleteness.COMPLETE
    if "benchmark_dma_200" in missing:
        return BenchmarkFeatureCompleteness.PARTIAL
    return BenchmarkFeatureCompleteness.MINIMUM_VIABLE


def _audit_decision(
    *,
    history: BenchmarkHistoryAudit,
    states: tuple[BenchmarkState, ...],
    snapshots: tuple[Any, ...],
    genuine_neutral: int,
) -> tuple[BenchmarkAuditConclusion, BenchmarkNextMilestone]:
    if history.row_count == 0:
        return (
            BenchmarkAuditConclusion.BENCHMARK_HISTORY_NOT_INGESTED,
            BenchmarkNextMilestone.EXPAND_BENCHMARK_HISTORICAL_COVERAGE,
        )
    if any(
        state.alignment is BenchmarkAlignment.CARRIED_FORWARD_STALE for state in states
    ):
        return (
            BenchmarkAuditConclusion.BENCHMARK_STALENESS_IS_PRIMARY_BOTTLENECK,
            BenchmarkNextMilestone.REPAIR_BENCHMARK_TIMESTAMP_ALIGNMENT,
        )
    if states and any(
        state.completeness is BenchmarkFeatureCompleteness.INSUFFICIENT
        for state in states
    ):
        return (
            BenchmarkAuditConclusion.BENCHMARK_LOOKBACK_IS_PRIMARY_BOTTLENECK,
            BenchmarkNextMilestone.EXPAND_BENCHMARK_HISTORICAL_COVERAGE,
        )
    if snapshots and not any(
        snapshot.input_completeness.value in {"COMPLETE", "MINIMUM_VIABLE"}
        for snapshot in snapshots
    ):
        return (
            BenchmarkAuditConclusion.BENCHMARK_HISTORY_EXISTS_BUT_NOT_PROPAGATED,
            BenchmarkNextMilestone.HARDEN_SNAPSHOT_COMPLETENESS_SEMANTICS,
        )
    if snapshots and genuine_neutral == 0:
        return (
            BenchmarkAuditConclusion.SNAPSHOT_COMPLETENESS_RULES_ARE_PRIMARY_BOTTLENECK,
            BenchmarkNextMilestone.HARDEN_SNAPSHOT_COMPLETENESS_SEMANTICS,
        )
    return (
        BenchmarkAuditConclusion.BENCHMARK_CAPTURE_IS_COMPLETE,
        BenchmarkNextMilestone.AUTHORITATIVE_HISTORICAL_MARKET_DATA_BACKFILL_DESIGN,
    )


def _history_dates(
    *,
    repository: Any,
    configuration: BenchmarkConfiguration,
) -> set[date]:
    frame = repository.find_history_by_symbols(
        symbols=(configuration.provider_symbol,),
        end_date=date.today(),
        limit=5000,
    )
    frame = _prepare_bars(frame, provider_symbol=configuration.provider_symbol)
    return set(frame["trade_date"].tolist()) if not frame.empty else set()


def _missing_business_days(dates: tuple[date, ...]) -> int:
    if not dates:
        return 0
    present = set(dates)
    current = min(dates)
    missing = 0
    while current <= max(dates):
        if current.weekday() < 5 and current not in present:
            missing += 1
        current = date.fromordinal(current.toordinal() + 1)
    return missing


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _date_text(value: date | None) -> str:
    return "unavailable" if value is None else value.isoformat()


def _pairs(values: tuple[tuple[str, int], ...]) -> str:
    return ", ".join(f"{key}={value}" for key, value in values) if values else "none"


def _report_dict(report: BenchmarkCoverageReport) -> dict[str, Any]:
    payload = asdict(report)
    payload["history"]["configuration"] = asdict(report.history.configuration)
    payload["history"]["finding"] = report.history.finding.value
    payload["primary_conclusion"] = report.primary_conclusion.value
    payload["secondary_conclusions"] = [
        item.value for item in report.secondary_conclusions
    ]
    payload["recommended_next_milestone"] = report.recommended_next_milestone.value
    return payload


__all__ = [
    "BenchmarkAlignment",
    "BenchmarkAuditConclusion",
    "BenchmarkConfiguration",
    "BenchmarkCoverageReport",
    "BenchmarkFeatureCompleteness",
    "BenchmarkHistoryAudit",
    "BenchmarkMappingFinding",
    "BenchmarkNextMilestone",
    "BenchmarkState",
    "BenchmarkStateBuilder",
    "benchmark_coverage_report",
    "benchmark_history_audit",
    "canonical_benchmark_configuration",
    "export_benchmark_coverage_csv",
    "export_benchmark_coverage_json",
    "render_benchmark_completeness",
    "render_benchmark_configuration",
    "render_benchmark_coverage",
    "render_benchmark_history",
]
