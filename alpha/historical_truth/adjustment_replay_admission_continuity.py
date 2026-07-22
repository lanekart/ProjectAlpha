"""HTR-010B1B continuity recomputation and Tier A weight closure."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb

from alpha.historical_truth.adjustment_replay_admission_models import (
    ValidationOutcome,
    stable_id,
)

HTR010B1B_CONTRACT_VERSION = "HTR-010B1B-v1.0.0"

MATERIAL_ACTION_TYPES = {
    "SPLIT",
    "BONUS",
    "RIGHTS",
    "FACE_VALUE_CHANGE",
    "CAPITAL_REDUCTION",
}
CERTIFIED_FACTOR_STATES = {
    "FACTOR_CERTIFIED",
    "FACTOR_DERIVED_OFFICIAL_TERMS",
}
UNKNOWN_FACTOR_STATES = {
    "FACTOR_UNKNOWN_MISSING_TERMS",
    "FACTOR_PROVISIONAL_REFERENCE_PRICE",
}
AMBIGUOUS_FACTOR_STATES = {
    "FACTOR_AMBIGUOUS_TERMS",
    "FACTOR_CONFLICTING_EVENTS",
    "FACTOR_INVALID",
}
NON_MULTIPLICATIVE_STATES = {
    "FACTOR_NOT_MULTIPLICATIVE",
    "FACTOR_IDENTITY_TRANSITION_ONLY",
}


def recompute_factor_validation(
    *,
    database_path: Path,
    events: tuple[dict[str, Any], ...],
    factors: tuple[dict[str, Any], ...],
    legacy_continuity: tuple[dict[str, Any], ...],
    start_date: date,
    end_date: date,
) -> tuple[
    tuple[dict[str, Any], ...],
    tuple[dict[str, Any], ...],
    dict[str, Any],
]:
    """Recompute continuity from HTR-010B factors and canonical candles."""

    event_by_id = {str(row["canonical_event_id"]): row for row in events}
    legacy_by_event = {
        str(
            row.get("event_id")
            or row.get("canonical_event_id")
            or row.get("action_id")
        ): row
        for row in legacy_continuity
    }
    cases: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    with duckdb.connect(str(database_path), read_only=True) as connection:
        for factor in factors:
            event_id = str(factor.get("canonical_event_id") or "")
            event = event_by_id.get(event_id)
            if event is None:
                continue
            action_type = str(event.get("action_type") or "")
            if action_type not in MATERIAL_ACTION_TYPES:
                continue
            effective = _as_date(event.get("effective_date"))
            if effective is None or not start_date <= effective <= end_date:
                continue
            identity = str(
                event.get("governed_identity_id")
                or factor.get("identity_key")
                or ""
            )
            isin = str(event.get("isin") or "").strip().upper()
            series_values = tuple(
                str(item).upper()
                for item in event.get("series_applicability") or ()
            )
            series = series_values[0] if len(series_values) == 1 else None
            bars = _event_bars(connection, isin, series, effective)
            metrics = _continuity_metrics(
                bars,
                _number(factor.get("price_factor")),
            )
            legacy = legacy_by_event.get(event_id, {})
            case = {
                "case_id": stable_id("factor-case-recomputed", event_id),
                "event_id": event_id,
                "identity_key": identity,
                "symbol": event.get("symbol"),
                "series": series,
                "isin": isin or None,
                "action_type": action_type,
                "effective_date": effective.isoformat(),
                "factor_state": factor.get("factor_state"),
                "price_factor": factor.get("price_factor"),
                "raw_gap_atr": metrics["raw_gap_atr"],
                "adjusted_gap_atr": metrics["adjusted_gap_atr"],
                "inverse_adjusted_gap_atr": metrics["inverse_adjusted_gap_atr"],
                "previous_session": metrics["previous_session"],
                "action_session": metrics["action_session"],
                "previous_close": metrics["previous_close"],
                "action_open": metrics["action_open"],
                "atr_before": metrics["atr_before"],
                "candle_context_state": metrics["candle_context_state"],
                "legacy_continuity_state": legacy.get("continuity_state"),
                "legacy_raw_gap_atr": legacy.get("raw_gap_atr"),
                "legacy_adjusted_gap_atr": legacy.get("adjusted_gap_atr"),
                "continuity_source": (
                    "HTR010B_FACTOR_RECOMPUTED_FROM_CANONICAL_CANDLES"
                ),
            }
            cases.append(case)
            results.append(_classify_recomputed_case(case))

    result_counts = Counter(str(row["validation_outcome"]) for row in results)
    legacy_disagreements = sum(
        bool(row.get("legacy_continuity_state"))
        and row.get("legacy_continuity_state")
        != row.get("recomputed_continuity_state")
        for row in results
    )
    orientation_candidates = sum(
        row.get("implementation_defect_code")
        == "POSSIBLE_FACTOR_ORIENTATION_DEFECT"
        for row in results
    )
    summary = {
        "contract_version": HTR010B1B_CONTRACT_VERSION,
        "case_count": len(cases),
        "validation_outcomes": dict(sorted(result_counts.items())),
        "legacy_case_count": len(legacy_continuity),
        "legacy_recomputed_state_disagreement_count": legacy_disagreements,
        "possible_factor_orientation_defect_count": orientation_candidates,
        "market_derived_factor_autocorrection": False,
        "continuity_recomputed_from_canonical_candles": True,
    }
    return tuple(cases), tuple(results), summary


def tier_a_quarantine_economic_weight(
    *,
    database_path: Path,
    quarantine: tuple[dict[str, Any], ...],
    coverage: tuple[dict[str, Any], ...],
    population: dict[str, Any],
    start_date: date,
    end_date: date,
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    """Measure quarantined rows against the identical Tier A denominator."""

    tier_a_ids = {str(row["identity_key"]) for row in coverage}
    observed_ids = set(population.get("by_identity", {}))
    ranges_by_identity: dict[str, list[tuple[date, date]]] = defaultdict(list)
    reasons_by_identity: dict[str, set[str]] = defaultdict(set)
    symbols: dict[str, Any] = {}
    out_of_universe_ids: set[str] = set()
    no_observed_rows_ids: set[str] = set()
    outside_window_rows = 0

    for row in quarantine:
        identity = str(row.get("identity_key") or "")
        if identity not in tier_a_ids:
            out_of_universe_ids.add(identity)
            continue
        if identity not in observed_ids:
            no_observed_rows_ids.add(identity)
        raw_start = _as_date(row.get("interval_start")) or start_date
        raw_end = _as_date(row.get("interval_end")) or end_date
        clipped_start = max(raw_start, start_date)
        clipped_end = min(raw_end, end_date)
        if clipped_start > clipped_end:
            outside_window_rows += 1
            continue
        ranges_by_identity[identity].append((clipped_start, clipped_end))
        reasons_by_identity[identity].add(str(row.get("quarantine_reason")))
        symbols[identity] = row.get("symbol")

    rows: list[dict[str, Any]] = []
    with duckdb.connect(str(database_path), read_only=True) as connection:
        for identity, ranges in sorted(ranges_by_identity.items()):
            merged = _merge_ranges(ranges)
            isin = identity.removeprefix("nse:isin:")
            predicates = " OR ".join(
                "(trading_date BETWEEN ? AND ?)" for _ in merged
            )
            params: list[Any] = [
                isin,
                *[item for pair in merged for item in pair],
            ]
            query = (
                "SELECT COUNT(*), COUNT(DISTINCT trading_date) "
                "FROM daily_candle WHERE upper(isin)=? "
                "AND lower(exchange)='nse' AND ("
                + predicates
                + ")"
            )
            result = connection.execute(query, params).fetchone()
            affected_rows = int(result[0]) if result else 0
            affected_sessions = int(result[1]) if result else 0
            rows.append(
                {
                    "identity_key": identity,
                    "symbol": symbols.get(identity),
                    "quarantine_interval_count": len(ranges),
                    "merged_interval_count": len(merged),
                    "affected_candle_rows": affected_rows,
                    "affected_identity_sessions": affected_sessions,
                    "pct_observed_tier_a_rows": _pct(
                        affected_rows,
                        population["observed_tier_a_candle_rows"],
                    ),
                    "pct_observed_tier_a_identity_sessions": _pct(
                        affected_sessions,
                        population["observed_tier_a_identity_sessions"],
                    ),
                    "reasons": sorted(reasons_by_identity[identity]),
                    "measurement_state": "MEASURED_TIER_A_CLIPPED_WINDOW",
                }
            )

    measured_rows = sum(int(row["affected_candle_rows"]) for row in rows)
    measured_sessions = sum(int(row["affected_identity_sessions"]) for row in rows)
    denominator_rows = int(population["observed_tier_a_candle_rows"])
    denominator_sessions = int(population["observed_tier_a_identity_sessions"])
    if measured_rows > denominator_rows or measured_sessions > denominator_sessions:
        raise RuntimeError(
            "quarantine numerator exceeds the closed Tier A denominator"
        )
    summary = {
        "economic_weight_measurement_state": (
            "MEASURED_PARTIAL_WINDOW"
            if not population["requested_window_fully_observed"]
            else "MEASURED_COMPLETE_WINDOW"
        ),
        "observed_quarantined_candle_rows": measured_rows,
        "observed_quarantined_identity_sessions": measured_sessions,
        "pct_observed_tier_a_rows_quarantined": _pct(
            measured_rows,
            denominator_rows,
        ),
        "pct_observed_tier_a_identity_sessions_quarantined": _pct(
            measured_sessions,
            denominator_sessions,
        ),
        "tier_a_numerator_universe_closed": True,
        "quarantine_ranges_clipped_to_requested_window": True,
        "out_of_tier_a_evidence_identity_count": len(out_of_universe_ids),
        "tier_a_evidence_identities_without_observed_rows": len(
            no_observed_rows_ids
        ),
        "quarantine_evidence_rows_outside_requested_window": outside_window_rows,
    }
    return tuple(rows), summary


def _classify_recomputed_case(case: dict[str, Any]) -> dict[str, Any]:
    state = str(case.get("factor_state") or "")
    raw_gap = _number(case.get("raw_gap_atr"))
    adjusted_gap = _number(case.get("adjusted_gap_atr"))
    inverse_gap = _number(case.get("inverse_adjusted_gap_atr"))
    factor = _number(case.get("price_factor"))
    defect_code: str | None = None

    if state in NON_MULTIPLICATIVE_STATES:
        outcome = ValidationOutcome.FACTOR_NON_MULTIPLICATIVE
    elif state in AMBIGUOUS_FACTOR_STATES:
        outcome = ValidationOutcome.FACTOR_CONFLICTING_OFFICIAL_EVIDENCE
    elif state in UNKNOWN_FACTOR_STATES:
        outcome = ValidationOutcome.FACTOR_REQUIRES_REFERENCE_PRICE
    elif state in CERTIFIED_FACTOR_STATES and factor is None:
        outcome = ValidationOutcome.IMPLEMENTATION_DEFECT
        defect_code = "CERTIFIED_FACTOR_MISSING_VALUE"
    elif raw_gap is None or adjusted_gap is None:
        outcome = ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE
    elif adjusted_gap <= 2.0 or adjusted_gap < raw_gap:
        outcome = ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MARKET_GAP
    elif inverse_gap is not None and (
        inverse_gap <= 2.0 or inverse_gap < raw_gap
    ):
        outcome = ValidationOutcome.IMPLEMENTATION_DEFECT
        defect_code = "POSSIBLE_FACTOR_ORIENTATION_DEFECT"
    else:
        outcome = ValidationOutcome.IMPLEMENTATION_DEFECT
        defect_code = "FACTOR_DOES_NOT_RESTORE_CONTINUITY"

    admitted = outcome is ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MARKET_GAP
    if admitted:
        recomputed_state = "CONTINUITY_RESTORED_OR_IMPROVED"
    elif outcome is ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE:
        recomputed_state = "INSUFFICIENT_CANDLE_CONTEXT"
    elif outcome in {
        ValidationOutcome.FACTOR_REQUIRES_REFERENCE_PRICE,
        ValidationOutcome.FACTOR_CONFLICTING_OFFICIAL_EVIDENCE,
        ValidationOutcome.FACTOR_NON_MULTIPLICATIVE,
    }:
        recomputed_state = "FACTOR_REQUIRES_OFFICIAL_EVIDENCE"
    else:
        recomputed_state = "FACTOR_TRANSFORMATION_DEFECT"
    return {
        **case,
        "validation_outcome": outcome.value,
        "admitted_to_replay": admitted,
        "requires_quarantine": not admitted,
        "implementation_defect_code": defect_code,
        "recomputed_continuity_state": recomputed_state,
        "classification_contract": HTR010B1B_CONTRACT_VERSION,
        "market_derived_factor_autocorrection": False,
        "production_influence": False,
    }


def _event_bars(
    connection: duckdb.DuckDBPyConnection,
    isin: str,
    series: str | None,
    effective: date,
) -> list[tuple[Any, ...]]:
    if not isin:
        return []
    series_clause = "" if series is None else " AND upper(series)=?"
    prior_params: list[Any] = [effective, isin]
    current_params: list[Any] = [effective, isin]
    if series is not None:
        prior_params.append(series)
        current_params.append(series)
    select = (
        "SELECT trading_date, open_price, high_price, low_price, "
        "close_price, volume FROM daily_candle "
    )
    prior = connection.execute(
        select
        + "WHERE trading_date < ? AND upper(isin)=?"
        + series_clause
        + " ORDER BY trading_date DESC LIMIT 15",
        prior_params,
    ).fetchall()
    current = connection.execute(
        select
        + "WHERE trading_date >= ? AND upper(isin)=?"
        + series_clause
        + " ORDER BY trading_date LIMIT 1",
        current_params,
    ).fetchone()
    return [*reversed(prior), *([current] if current else [])]


def _continuity_metrics(
    bars: list[tuple[Any, ...]],
    factor: float | None,
) -> dict[str, Any]:
    previous = bars[:-1]
    current = bars[-1] if bars else None
    prior = previous[-1] if previous else None
    previous_close = float(prior[4]) if prior else None
    action_open = float(current[1]) if current else None
    atr = _atr(previous)
    raw_gap = _gap_atr(action_open, previous_close, atr, 1.0)
    adjusted_gap = _gap_atr(action_open, previous_close, atr, factor)
    inverse = 1.0 / factor if factor not in {None, 0.0} else None
    inverse_gap = _gap_atr(action_open, previous_close, atr, inverse)
    context_available = bool(current and prior and atr)
    return {
        "previous_session": prior[0].isoformat() if prior else None,
        "action_session": current[0].isoformat() if current else None,
        "previous_close": previous_close,
        "action_open": action_open,
        "atr_before": atr,
        "raw_gap_atr": raw_gap,
        "adjusted_gap_atr": adjusted_gap,
        "inverse_adjusted_gap_atr": inverse_gap,
        "candle_context_state": (
            "AVAILABLE" if context_available else "INSUFFICIENT"
        ),
    }


def _gap_atr(
    action_open: float | None,
    previous_close: float | None,
    atr: float | None,
    factor: float | None,
) -> float | None:
    if (
        action_open is None
        or previous_close is None
        or atr is None
        or atr <= 0
        or factor is None
        or factor <= 0
    ):
        return None
    reference = previous_close * factor
    return abs(action_open - reference) / (atr * factor)


def _atr(rows: Sequence[tuple[Any, ...]]) -> float | None:
    if len(rows) < 2:
        return None
    ranges: list[float] = []
    previous_close: float | None = None
    for row in rows[-14:]:
        high, low, close = float(row[2]), float(row[3]), float(row[4])
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


def _merge_ranges(ranges: list[tuple[date, date]]) -> list[tuple[date, date]]:
    merged: list[tuple[date, date]] = []
    for start, end in sorted(ranges):
        if not merged or start > merged[-1][1] + timedelta(days=1):
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _number(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _pct(numerator: int, denominator: int) -> float | None:
    return (100.0 * numerator / denominator) if denominator else None


__all__ = [
    "HTR010B1B_CONTRACT_VERSION",
    "recompute_factor_validation",
    "tier_a_quarantine_economic_weight",
]
