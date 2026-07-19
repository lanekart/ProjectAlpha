"""Price, indicator, candidate, decision, and replay delta engines."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from alpha.benchmark_replay.models import (
    ApprovalStatistic,
    BenchmarkReplayReport,
)
from alpha.warehouse_delta_audit.models import (
    CandidateDeltaRecord,
    CorporateActionDeltaRecord,
    DecisionDeltaRecord,
    DecisionSeverity,
    DeltaThresholdPolicy,
    IndicatorDeltaRecord,
    PriceDeltaRecord,
    ReplayDeltaRecord,
)

_ZERO = Decimal("0")


class PriceDeltaEngine:
    """Compare raw OHLCV observations over the paired symbol/date population."""

    def compare(
        self,
        *,
        legacy_sample: Path,
        comparison_sample: Path,
        thresholds: DeltaThresholdPolicy,
    ) -> tuple[PriceDeltaRecord, ...]:
        with duckdb.connect() as connection:
            connection.execute(
                f"ATTACH {_sql_path(legacy_sample)} AS legacy (READ_ONLY)"
            )
            connection.execute(
                f"ATTACH {_sql_path(comparison_sample)} AS comparison (READ_ONLY)"
            )
            rows = connection.execute(
                _price_delta_sql(),
                (
                    float(thresholds.price_small_relative),
                    float(thresholds.volume_small_relative),
                    float(thresholds.price_small_relative),
                    float(thresholds.volume_small_relative),
                ),
            ).fetchall()
        return tuple(_price_record(row) for row in rows)


class IndicatorDeltaEngine:
    """Recalculate required diagnostics on both immutable sample stores."""

    def compare(
        self,
        *,
        legacy_sample: Path,
        comparison_sample: Path,
        symbols: tuple[str, ...],
        thresholds: DeltaThresholdPolicy,
    ) -> tuple[IndicatorDeltaRecord, ...]:
        rows: list[IndicatorDeltaRecord] = []
        with (
            duckdb.connect(str(legacy_sample), read_only=True) as legacy,
            duckdb.connect(str(comparison_sample), read_only=True) as comparison,
        ):
            for symbol in symbols:
                legacy_frame = _indicator_frame(legacy, symbol)
                comparison_frame = _indicator_frame(comparison, symbol)
                rows.extend(
                    _indicator_records(
                        symbol=symbol,
                        legacy=legacy_frame,
                        comparison=comparison_frame,
                        material_threshold=float(
                            thresholds.indicator_material_relative
                        ),
                    )
                )
        return tuple(rows)


class ReplayDeltaEngine:
    """Compare frozen CABR outputs without altering replay settings."""

    def candidate_deltas(
        self,
        *,
        legacy: BenchmarkReplayReport,
        comparison: BenchmarkReplayReport,
        thresholds: DeltaThresholdPolicy,
    ) -> tuple[CandidateDeltaRecord, ...]:
        legacy_by_symbol = _approvals_by_symbol(legacy.approval_statistics)
        comparison_by_symbol = _approvals_by_symbol(comparison.approval_statistics)
        records = []
        for symbol in sorted(set(legacy_by_symbol) | set(comparison_by_symbol)):
            legacy_rows = legacy_by_symbol.get(symbol, {})
            comparison_rows = comparison_by_symbol.get(symbol, {})
            common = sorted(set(legacy_rows) & set(comparison_rows))
            only_legacy = sorted(set(legacy_rows) - set(comparison_rows))
            only_comparison = sorted(set(comparison_rows) - set(legacy_rows))
            shifts = tuple(
                abs(
                    legacy_rows[value].opportunity_score
                    - comparison_rows[value].opportunity_score
                )
                for value in common
            )
            records.append(
                CandidateDeltaRecord(
                    symbol=symbol,
                    candidate_on_both=len(common),
                    candidate_only_legacy=len(only_legacy),
                    candidate_only_comparison=len(only_comparison),
                    timing_shifted=_timing_shifts(
                        only_legacy,
                        only_comparison,
                        thresholds.timing_shift_days,
                    ),
                    score_shifted=sum(value > _ZERO for value in shifts),
                    average_absolute_score_shift=(
                        sum(shifts, _ZERO) / Decimal(len(shifts)) if shifts else None
                    ),
                    maximum_absolute_score_shift=max(shifts, default=None),
                )
            )
        return tuple(records)

    def decision_deltas(
        self,
        *,
        legacy: BenchmarkReplayReport,
        comparison: BenchmarkReplayReport,
        thresholds: DeltaThresholdPolicy,
    ) -> tuple[DecisionDeltaRecord, ...]:
        legacy_rows = _approval_map(legacy.approval_statistics)
        comparison_rows = _approval_map(comparison.approval_statistics)
        records = []
        for observed_on, symbol in sorted(set(legacy_rows) | set(comparison_rows)):
            left = legacy_rows.get((observed_on, symbol))
            right = comparison_rows.get((observed_on, symbol))
            severity, explanation = _decision_severity(
                left,
                right,
                thresholds.candidate_score_material,
            )
            records.append(
                DecisionDeltaRecord(
                    observed_on=observed_on,
                    symbol=symbol,
                    legacy_score=None if left is None else left.opportunity_score,
                    comparison_score=None if right is None else right.opportunity_score,
                    legacy_approved=None if left is None else left.approved,
                    comparison_approved=None if right is None else right.approved,
                    legacy_reason="MISSING"
                    if left is None
                    else left.primary_reason_code,
                    comparison_reason=(
                        "MISSING" if right is None else right.primary_reason_code
                    ),
                    severity=severity,
                    explanation=explanation,
                )
            )
        return tuple(records)

    def replay_deltas(
        self,
        *,
        legacy: BenchmarkReplayReport,
        comparison: BenchmarkReplayReport,
    ) -> tuple[ReplayDeltaRecord, ...]:
        left = legacy.portfolio_statistics
        right = comparison.portfolio_statistics
        candidates_left = sum(
            item.technical_candidates for item in legacy.candidate_statistics
        )
        candidates_right = sum(
            item.technical_candidates for item in comparison.candidate_statistics
        )
        approvals_left = sum(
            item.institutional_approvals for item in legacy.candidate_statistics
        )
        approvals_right = sum(
            item.institutional_approvals for item in comparison.candidate_statistics
        )
        capture_left = _capture_rate(legacy)
        capture_right = _capture_rate(comparison)
        metrics = (
            (
                "candidates",
                Decimal(candidates_left),
                Decimal(candidates_right),
                "count",
            ),
            ("approvals", Decimal(approvals_left), Decimal(approvals_right), "count"),
            (
                "trades",
                Decimal(left.logical_trades),
                Decimal(right.logical_trades),
                "count",
            ),
            (
                "entries",
                Decimal(left.logical_trades),
                Decimal(right.logical_trades),
                "count",
            ),
            (
                "exits",
                Decimal(left.logical_trades),
                Decimal(right.logical_trades),
                "count",
            ),
            ("win_rate", left.win_rate_percent, right.win_rate_percent, "percent"),
            (
                "expectancy",
                left.expectancy_percent,
                right.expectancy_percent,
                "percent",
            ),
            (
                "maximum_drawdown",
                left.maximum_drawdown_percent,
                right.maximum_drawdown_percent,
                "percent",
            ),
            ("opportunity_capture", capture_left, capture_right, "percent"),
        )
        return tuple(
            ReplayDeltaRecord(
                metric=name,
                legacy_value=legacy_value,
                comparison_value=comparison_value,
                delta=(
                    None
                    if legacy_value is None or comparison_value is None
                    else comparison_value - legacy_value
                ),
                unit=unit,
                interpretation=_replay_interpretation(
                    name,
                    legacy_value,
                    comparison_value,
                ),
            )
            for name, legacy_value, comparison_value, unit in metrics
        )


def unavailable_corporate_action_deltas() -> tuple[CorporateActionDeltaRecord, ...]:
    explanation = (
        "No independent point-in-time corporate-action sample was supplied; "
        "the effect remains UNKNOWN rather than zero."
    )
    return tuple(
        CorporateActionDeltaRecord(
            event_type=event_type,
            legacy_events=None,
            comparison_events=None,
            indicator_changing_events=None,
            replay_changing_events=None,
            status="UNKNOWN_SOURCE_UNAVAILABLE",
            explanation=explanation,
        )
        for event_type in (
            "SPLIT",
            "BONUS",
            "SYMBOL_CHANGE",
            "MERGER",
            "ADJUSTED_HISTORY",
        )
    )


def _price_delta_sql() -> str:
    return """
        WITH paired AS (
            SELECT
                COALESCE(l.symbol, o.symbol) AS symbol,
                l.symbol IS NOT NULL AS has_legacy,
                o.symbol IS NOT NULL AS has_comparison,
                l.open AS l_open, o.open AS o_open,
                l.high AS l_high, o.high AS o_high,
                l.low AS l_low, o.low AS o_low,
                l.close AS l_close, o.close AS o_close,
                l.volume AS l_volume, o.volume AS o_volume
            FROM legacy.daily_prices AS l
            FULL OUTER JOIN comparison.daily_prices AS o
              ON l.symbol = o.symbol AND l.trade_date = o.trade_date
        ), normalized AS (
            SELECT *,
                CASE WHEN has_legacy AND has_comparison THEN
                    ABS(l_close-o_close)/GREATEST(ABS(l_close),0.01)
                END AS close_relative,
                CASE WHEN has_legacy AND has_comparison THEN
                    ABS(l_volume-o_volume)/GREATEST(ABS(l_volume),1.0)
                END AS volume_relative,
                CASE WHEN has_legacy AND has_comparison THEN
                    GREATEST(
                        ABS(l_open-o_open)/GREATEST(ABS(l_open),0.01),
                        ABS(l_high-o_high)/GREATEST(ABS(l_high),0.01),
                        ABS(l_low-o_low)/GREATEST(ABS(l_low),0.01),
                        ABS(l_close-o_close)/GREATEST(ABS(l_close),0.01)
                    )
                END AS maximum_price_relative,
                CASE WHEN has_legacy AND has_comparison AND
                    l_open=o_open AND l_high=o_high AND l_low=o_low AND
                    l_close=o_close AND l_volume=o_volume THEN TRUE ELSE FALSE
                END AS exact
            FROM paired
        ), summary AS (
            SELECT
                symbol,
                SUM(CASE WHEN has_legacy AND has_comparison
                    THEN 1 ELSE 0 END) AS matched,
                SUM(CASE WHEN exact THEN 1 ELSE 0 END) AS exact_rows,
                SUM(CASE WHEN has_legacy AND has_comparison AND NOT exact
                    AND maximum_price_relative <= ? AND volume_relative <= ?
                    THEN 1 ELSE 0 END) AS small_rows,
                SUM(CASE WHEN has_legacy AND has_comparison AND NOT exact
                    AND NOT (maximum_price_relative <= ? AND volume_relative <= ?)
                    THEN 1 ELSE 0 END) AS large_rows,
                SUM(CASE WHEN has_legacy AND NOT has_comparison
                    THEN 1 ELSE 0 END) AS missing_comparison,
                SUM(CASE WHEN has_comparison AND NOT has_legacy
                    THEN 1 ELSE 0 END) AS missing_legacy,
                SUM(CASE WHEN has_legacy AND has_comparison AND l_open<>o_open
                    THEN 1 ELSE 0 END) AS open_changed,
                SUM(CASE WHEN has_legacy AND has_comparison AND l_high<>o_high
                    THEN 1 ELSE 0 END) AS high_changed,
                SUM(CASE WHEN has_legacy AND has_comparison AND l_low<>o_low
                    THEN 1 ELSE 0 END) AS low_changed,
                SUM(CASE WHEN has_legacy AND has_comparison AND l_close<>o_close
                    THEN 1 ELSE 0 END) AS close_changed,
                SUM(CASE WHEN has_legacy AND has_comparison AND l_volume<>o_volume
                    THEN 1 ELSE 0 END) AS volume_changed,
                MAX(close_relative) AS max_close_relative,
                MAX(volume_relative) AS max_volume_relative
            FROM normalized
            GROUP BY symbol
        )
        SELECT
            summary.*,
            COALESCE(ld.duplicate_observations, 0),
            COALESCE(od.duplicate_observations, 0),
            COALESCE(li.invalid_observations, 0),
            COALESCE(oi.invalid_observations, 0)
        FROM summary
        LEFT JOIN legacy.source_duplicates AS ld USING(symbol)
        LEFT JOIN comparison.source_duplicates AS od USING(symbol)
        LEFT JOIN legacy.source_invalid_rows AS li USING(symbol)
        LEFT JOIN comparison.source_invalid_rows AS oi USING(symbol)
        ORDER BY symbol
    """


def _price_record(row: tuple[Any, ...]) -> PriceDeltaRecord:
    return PriceDeltaRecord(
        symbol=str(row[0]),
        matched_observations=int(row[1]),
        exact_observations=int(row[2]),
        small_difference_observations=int(row[3]),
        large_difference_observations=int(row[4]),
        missing_from_comparison=int(row[5]),
        missing_from_legacy=int(row[6]),
        open_changed=int(row[7]),
        high_changed=int(row[8]),
        low_changed=int(row[9]),
        close_changed=int(row[10]),
        volume_changed=int(row[11]),
        maximum_close_relative_delta=_optional_decimal(row[12]),
        maximum_volume_relative_delta=_optional_decimal(row[13]),
        legacy_duplicate_observations=int(row[14]),
        comparison_duplicate_observations=int(row[15]),
        legacy_invalid_observations=int(row[16]),
        comparison_invalid_observations=int(row[17]),
    )


def _indicator_frame(
    connection: duckdb.DuckDBPyConnection,
    symbol: str,
) -> pd.DataFrame:
    frame = connection.execute(
        """
        SELECT trade_date, open, high, low, close, volume
        FROM daily_prices
        WHERE symbol = ?
        ORDER BY trade_date
        """,
        (symbol,),
    ).fetchdf()
    if frame.empty:
        return frame
    frame = frame.set_index("trade_date")
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    previous_close = close.shift(1)
    true_range = pd.concat(
        (
            (high - low).abs(),
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ),
        axis=1,
    ).max(axis=1)
    result = pd.DataFrame(index=frame.index)
    result["close"] = close
    result["EMA20"] = close.ewm(span=20, adjust=False, min_periods=20).mean()
    result["EMA50"] = close.ewm(span=50, adjust=False, min_periods=50).mean()
    result["EMA200"] = close.ewm(span=200, adjust=False, min_periods=200).mean()
    result["ATR14"] = true_range.rolling(14, min_periods=14).mean()
    result["SUPPORT60"] = low.rolling(60, min_periods=60).min()
    result["RESISTANCE60"] = high.rolling(60, min_periods=60).max()
    result["BREAKOUT20"] = high.shift(1).rolling(20, min_periods=20).max()
    return result


def _indicator_records(
    *,
    symbol: str,
    legacy: pd.DataFrame,
    comparison: pd.DataFrame,
    material_threshold: float,
) -> tuple[IndicatorDeltaRecord, ...]:
    indicators = (
        "EMA20",
        "EMA50",
        "EMA200",
        "ATR14",
        "SUPPORT60",
        "RESISTANCE60",
        "BREAKOUT20",
    )
    records = []
    for indicator in indicators:
        if legacy.empty or comparison.empty:
            records.append(IndicatorDeltaRecord(symbol, indicator, 0, 0, 0, 0, 0, None))
            continue
        paired = pd.concat(
            (
                legacy[["close", indicator]].rename(
                    columns={"close": "legacy_close", indicator: "legacy_value"}
                ),
                comparison[["close", indicator]].rename(
                    columns={
                        "close": "comparison_close",
                        indicator: "comparison_value",
                    }
                ),
            ),
            axis=1,
            join="inner",
        ).dropna()
        if paired.empty:
            records.append(IndicatorDeltaRecord(symbol, indicator, 0, 0, 0, 0, 0, None))
            continue
        relative = (paired["legacy_value"] - paired["comparison_value"]).abs() / paired[
            "legacy_value"
        ].abs().clip(lower=0.01)
        identical = relative <= 1e-12
        material = relative > material_threshold
        minor = (~identical) & (~material)
        signals = _indicator_signals(paired, indicator)
        records.append(
            IndicatorDeltaRecord(
                symbol=symbol,
                indicator=indicator,
                compared_observations=len(paired),
                identical_observations=int(identical.sum()),
                minor_changes=int(minor.sum()),
                material_changes=int(material.sum()),
                signal_changes=signals,
                maximum_relative_delta=Decimal(str(float(relative.max()))),
            )
        )
    return tuple(records)


def _indicator_signals(paired: pd.DataFrame, indicator: str) -> int:
    if indicator == "ATR14":
        return 0
    if indicator == "SUPPORT60":
        legacy_signal = paired["legacy_close"] < paired["legacy_value"]
        comparison_signal = paired["comparison_close"] < paired["comparison_value"]
    else:
        legacy_signal = paired["legacy_close"] > paired["legacy_value"]
        comparison_signal = paired["comparison_close"] > paired["comparison_value"]
    return int((legacy_signal != comparison_signal).sum())


def _approvals_by_symbol(
    rows: tuple[ApprovalStatistic, ...],
) -> dict[str, dict[date, ApprovalStatistic]]:
    grouped: dict[str, dict[date, ApprovalStatistic]] = defaultdict(dict)
    for item in rows:
        grouped[item.symbol][item.observed_on] = item
    return grouped


def _approval_map(
    rows: tuple[ApprovalStatistic, ...],
) -> dict[tuple[date, str], ApprovalStatistic]:
    return {(item.observed_on, item.symbol): item for item in rows}


def _timing_shifts(
    legacy_dates: list[date],
    comparison_dates: list[date],
    tolerance_days: int,
) -> int:
    unmatched = set(comparison_dates)
    shifts = 0
    for legacy_date in legacy_dates:
        match = min(
            (
                value
                for value in unmatched
                if abs((value - legacy_date).days) <= tolerance_days
            ),
            key=lambda value: (abs((value - legacy_date).days), value),
            default=None,
        )
        if match is not None:
            shifts += 1
            unmatched.remove(match)
    return shifts


def _decision_severity(
    legacy: ApprovalStatistic | None,
    comparison: ApprovalStatistic | None,
    material_score: Decimal,
) -> tuple[DecisionSeverity, str]:
    if legacy is None or comparison is None:
        return DecisionSeverity.MATERIAL, "Candidate exists in only one warehouse."
    if legacy.approved != comparison.approved:
        return DecisionSeverity.CRITICAL, "Institutional approval changed."
    score_delta = abs(legacy.opportunity_score - comparison.opportunity_score)
    if (
        score_delta >= material_score
        or legacy.primary_reason_code != comparison.primary_reason_code
    ):
        return (
            DecisionSeverity.MATERIAL,
            "Score or primary gate reason changed materially.",
        )
    if score_delta > _ZERO:
        return (
            DecisionSeverity.MINOR,
            "Recommendation score changed below the material threshold.",
        )
    return DecisionSeverity.NO_CHANGE, "Recommendation and approval are unchanged."


def _capture_rate(report: BenchmarkReplayReport) -> Decimal | None:
    row = next(
        (
            item
            for item in report.opportunity_capture
            if item.opportunity_definition == "ALL"
        ),
        None,
    )
    return None if row is None else row.capture_rate_percent


def _replay_interpretation(
    metric: str,
    legacy: Decimal | None,
    comparison: Decimal | None,
) -> str:
    if legacy is None or comparison is None:
        return f"{metric} is not estimable in both samples."
    if legacy == comparison:
        return f"{metric} is unchanged under identical replay settings."
    return (
        f"{metric} changed by {comparison - legacy}; direction is reported "
        "without causal attribution."
    )


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _sql_path(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


__all__ = [
    "IndicatorDeltaEngine",
    "PriceDeltaEngine",
    "ReplayDeltaEngine",
    "unavailable_corporate_action_deltas",
]
