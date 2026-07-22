"""Typed HTR-010B1B closed-universe quarantine weight."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb


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
                        int(population["observed_tier_a_candle_rows"]),
                    ),
                    "pct_observed_tier_a_identity_sessions": _pct(
                        affected_sessions,
                        int(population["observed_tier_a_identity_sessions"]),
                    ),
                    "reasons": sorted(reasons_by_identity[identity]),
                    "measurement_state": "MEASURED_TIER_A_CLIPPED_WINDOW",
                }
            )

    measured_rows = sum(int(row["affected_candle_rows"]) for row in rows)
    measured_sessions = sum(
        int(row["affected_identity_sessions"]) for row in rows
    )
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


def _pct(numerator: int, denominator: int) -> float | None:
    return (100.0 * numerator / denominator) if denominator else None


__all__ = ["tier_a_quarantine_economic_weight"]
