"""Residual continuity-defect attribution for HTR-010B1C."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb

from alpha.historical_truth.adjustment_replay_admission_models import (
    ValidationOutcome,
)
from alpha.historical_truth.adjustment_replay_admission_session_coverage import (
    HTR010B1C_CONTRACT_VERSION,
)


def attribute_residual_factor_cases(
    *,
    database_path: Path,
    results: tuple[dict[str, Any], ...],
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    """Attribute residual failures without changing any official factor."""

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        grouped[(str(row.get("identity_key")), str(row.get("effective_date")))].append(
            row
        )

    enriched: list[dict[str, Any]] = []
    with duckdb.connect(str(database_path), read_only=True) as connection:
        for row in results:
            outcome = str(row.get("validation_outcome") or "")
            attribution = "NOT_APPLICABLE"
            detail: dict[str, Any] = {}
            if outcome == ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE.value:
                attribution = "INSUFFICIENT_CANDLE_CONTEXT"
            elif outcome == ValidationOutcome.IMPLEMENTATION_DEFECT.value:
                attribution, detail = _attribute_implementation_defect(
                    connection,
                    row,
                    grouped[
                        (
                            str(row.get("identity_key")),
                            str(row.get("effective_date")),
                        )
                    ],
                )
            enriched.append(
                {
                    **row,
                    "residual_attribution": attribution,
                    "residual_attribution_detail": detail,
                    "residual_attribution_contract": HTR010B1C_CONTRACT_VERSION,
                    "market_derived_factor_autocorrection": False,
                }
            )

    counts = Counter(str(row["residual_attribution"]) for row in enriched)
    unexplained = counts["UNEXPLAINED_FACTOR_TRANSFORMATION_DEFECT"]
    return tuple(enriched), {
        "contract_version": HTR010B1C_CONTRACT_VERSION,
        "attribution_counts": dict(sorted(counts.items())),
        "implementation_defect_count": sum(
            str(row.get("validation_outcome"))
            == ValidationOutcome.IMPLEMENTATION_DEFECT.value
            for row in enriched
        ),
        "possible_factor_orientation_defect_count": counts[
            "POSSIBLE_FACTOR_ORIENTATION_DEFECT"
        ],
        "possible_effective_date_offset_count": counts[
            "POSSIBLE_EFFECTIVE_DATE_OFFSET"
        ],
        "possible_multiple_action_cumulative_factor_count": counts[
            "POSSIBLE_MULTIPLE_ACTION_CUMULATIVE_FACTOR"
        ],
        "possible_thin_trading_distortion_count": counts[
            "POSSIBLE_THIN_TRADING_DISTORTION"
        ],
        "unexplained_factor_transformation_defect_count": unexplained,
        "market_derived_factor_autocorrection": False,
        "production_influence": False,
    }


def _attribute_implementation_defect(
    connection: duckdb.DuckDBPyConnection,
    row: dict[str, Any],
    same_day_rows: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    defect_code = str(row.get("implementation_defect_code") or "")
    if defect_code == "POSSIBLE_FACTOR_ORIENTATION_DEFECT":
        return "POSSIBLE_FACTOR_ORIENTATION_DEFECT", {
            "official_factor_retained": True,
            "inverse_factor_is_diagnostic_only": True,
        }

    effective = _as_date(row.get("effective_date"))
    isin = str(row.get("isin") or "").upper()
    series = str(row.get("series") or "").upper() or None
    factor = _number(row.get("price_factor"))
    if effective is None or not isin or factor is None or factor <= 0:
        return "UNEXPLAINED_FACTOR_TRANSFORMATION_DEFECT", {
            "reason": "MISSING_EVENT_OR_FACTOR_CONTEXT"
        }

    official_gap = _number(row.get("adjusted_gap_atr"))
    offset = _best_date_offset(
        connection,
        isin=isin,
        series=series,
        effective=effective,
        factor=factor,
    )
    if offset and offset["candidate_date"] != str(row.get("action_session")):
        best_gap = _number(offset.get("adjusted_gap_atr"))
        if best_gap is not None and _materially_better(best_gap, official_gap):
            return "POSSIBLE_EFFECTIVE_DATE_OFFSET", offset

    cumulative = _cumulative_factor(same_day_rows)
    if cumulative is not None:
        metrics = _metrics_for_date(
            connection,
            isin=isin,
            series=series,
            trading_date=effective,
            factor=cumulative,
        )
        cumulative_gap = _number(metrics.get("adjusted_gap_atr"))
        if cumulative_gap is not None and _materially_better(
            cumulative_gap,
            official_gap,
        ):
            return "POSSIBLE_MULTIPLE_ACTION_CUMULATIVE_FACTOR", {
                "same_day_factor_count": len(same_day_rows),
                "diagnostic_cumulative_factor": cumulative,
                "diagnostic_adjusted_gap_atr": cumulative_gap,
                "official_factors_retained": True,
            }

    trading = _thin_trading_context(
        connection,
        isin=isin,
        series=series,
        effective=effective,
    )
    if trading["thin_trading_heuristic"]:
        return "POSSIBLE_THIN_TRADING_DISTORTION", trading

    return "UNEXPLAINED_FACTOR_TRANSFORMATION_DEFECT", {
        "official_adjusted_gap_atr": official_gap,
        "best_offset_diagnostic": offset,
        "thin_trading_context": trading,
    }


def _best_date_offset(
    connection: duckdb.DuckDBPyConnection,
    *,
    isin: str,
    series: str | None,
    effective: date,
    factor: float,
) -> dict[str, Any] | None:
    clause = "" if series is None else " AND upper(series)=?"
    params: list[Any] = [
        effective - timedelta(days=10),
        effective + timedelta(days=10),
        isin,
    ]
    if series is not None:
        params.append(series)
    dates = [
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT trading_date FROM daily_candle "
            "WHERE trading_date BETWEEN ? AND ? AND upper(isin)=?"
            + clause
            + " ORDER BY trading_date",
            params,
        ).fetchall()
    ]
    if not dates:
        return None
    ordered = sorted(dates, key=lambda item: (abs((item - effective).days), item))[:7]
    candidates = []
    for candidate in ordered:
        metrics = _metrics_for_date(
            connection,
            isin=isin,
            series=series,
            trading_date=candidate,
            factor=factor,
        )
        gap = _number(metrics.get("adjusted_gap_atr"))
        if gap is not None:
            candidates.append((gap, candidate, metrics))
    if not candidates:
        return None
    gap, candidate, metrics = min(candidates, key=lambda item: (item[0], item[1]))
    return {
        "candidate_date": candidate.isoformat(),
        "session_offset_calendar_days": (candidate - effective).days,
        "adjusted_gap_atr": gap,
        "raw_gap_atr": metrics.get("raw_gap_atr"),
        "official_factor_retained": True,
    }


def _metrics_for_date(
    connection: duckdb.DuckDBPyConnection,
    *,
    isin: str,
    series: str | None,
    trading_date: date,
    factor: float,
) -> dict[str, Any]:
    prior, current = _bars(connection, isin, series, trading_date)
    if not prior or current is None:
        return {"raw_gap_atr": None, "adjusted_gap_atr": None}
    previous_close = float(prior[-1][4])
    action_open = float(current[1])
    atr = _atr(prior)
    return {
        "raw_gap_atr": _gap(action_open, previous_close, atr, 1.0),
        "adjusted_gap_atr": _gap(action_open, previous_close, atr, factor),
    }


def _thin_trading_context(
    connection: duckdb.DuckDBPyConnection,
    *,
    isin: str,
    series: str | None,
    effective: date,
) -> dict[str, Any]:
    prior, current = _bars(connection, isin, series, effective)
    volumes = [float(row[5]) for row in prior if row[5] is not None]
    median_volume = statistics.median(volumes) if volumes else None
    previous_date = prior[-1][0] if prior else None
    action_date = current[0] if current else None
    session_gap = (
        (action_date - previous_date).days
        if action_date is not None and previous_date is not None
        else None
    )
    thin = bool(
        len(prior) < 10
        or (median_volume is not None and median_volume <= 1000)
        or (session_gap is not None and session_gap > 7)
    )
    return {
        "prior_session_count": len(prior),
        "median_prior_volume": median_volume,
        "calendar_gap_to_action_session": session_gap,
        "thin_trading_heuristic": thin,
        "heuristic_only": True,
    }


def _bars(
    connection: duckdb.DuckDBPyConnection,
    isin: str,
    series: str | None,
    trading_date: date,
) -> tuple[list[tuple[Any, ...]], tuple[Any, ...] | None]:
    clause = "" if series is None else " AND upper(series)=?"
    prior_params: list[Any] = [trading_date, isin]
    current_params: list[Any] = [trading_date, isin]
    if series is not None:
        prior_params.append(series)
        current_params.append(series)
    select = (
        "SELECT trading_date, open_price, high_price, low_price, close_price, volume "
        "FROM daily_candle "
    )
    prior = connection.execute(
        select
        + "WHERE trading_date < ? AND upper(isin)=?"
        + clause
        + " ORDER BY trading_date DESC LIMIT 15",
        prior_params,
    ).fetchall()
    current = connection.execute(
        select
        + "WHERE trading_date >= ? AND upper(isin)=?"
        + clause
        + " ORDER BY trading_date LIMIT 1",
        current_params,
    ).fetchone()
    return list(reversed(prior)), current


def _cumulative_factor(rows: list[dict[str, Any]]) -> float | None:
    factors = [_number(row.get("price_factor")) for row in rows]
    valid = [item for item in factors if item is not None and item > 0]
    if len(valid) <= 1 or len(valid) != len(rows):
        return None
    result = 1.0
    for factor in valid:
        result *= factor
    return result


def _atr(rows: list[tuple[Any, ...]]) -> float | None:
    if len(rows) < 2:
        return None
    ranges: list[float] = []
    previous_close: float | None = None
    for row in rows[-14:]:
        high = float(row[2])
        low = float(row[3])
        close = float(row[4])
        true_range = high - low
        if previous_close is not None:
            true_range = max(
                true_range,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        ranges.append(true_range)
        previous_close = close
    return sum(ranges) / len(ranges) if ranges else None


def _gap(
    action_open: float,
    previous_close: float,
    atr: float | None,
    factor: float,
) -> float | None:
    if atr is None or atr <= 0 or factor <= 0:
        return None
    return abs(action_open - (previous_close * factor)) / (atr * factor)


def _materially_better(candidate: float, official: float | None) -> bool:
    return candidate <= 2.0 or (official is not None and candidate <= official * 0.5)


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _number(value: object) -> float | None:
    if value is None or not isinstance(value, (str, int, float)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


__all__ = ["attribute_residual_factor_cases"]
