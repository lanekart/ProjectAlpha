"""HTR-010B1A input-contract, weighting, and interval integrity repair."""

from __future__ import annotations

import bisect
import json
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb

from alpha.historical_truth.adjustment_replay_admission_engine import (
    mixed_basis_resolutions,
    multiple_action_cases,
    series_applicability,
    transformation_contract,
    unknown_factor_impact,
)
from alpha.historical_truth.adjustment_replay_admission_models import (
    PRODUCTION_INFLUENCE,
    TRANSFORMATION_CONTRACT_VERSION,
    AdjustmentReplayAdmissionReport,
    AdmissionState,
    ReplayImpact,
    ReplayReadiness,
    ValidationOutcome,
    stable_id,
)

HTR010B1A_CONTRACT_VERSION = "HTR-010B1A-v1.0.0"

CERTIFIED_FACTOR_STATES = {
    "FACTOR_CERTIFIED",
    "FACTOR_DERIVED_OFFICIAL_TERMS",
    "FACTOR_NOT_REQUIRED",
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
QUARANTINE_ADMISSION_STATES = {
    AdmissionState.FACTOR_UNKNOWN_QUARANTINED.value,
    AdmissionState.FACTOR_AMBIGUOUS_QUARANTINED.value,
    AdmissionState.MIXED_PRICE_BASIS_QUARANTINED.value,
    AdmissionState.CONFLICTING_EVIDENCE_QUARANTINED.value,
    AdmissionState.INSUFFICIENT_EVIDENCE_QUARANTINED.value,
    AdmissionState.UNRESOLVED.value,
}


class InputContractError(ValueError):
    """Raised when an upstream governed artifact violates its declared contract."""


class HTR010BInputAdapter:
    """Normalize HTR-010B field names and fail closed on missing evidence."""

    def load(self, htr010b_output: Path, htr010a3_output: Path) -> dict[str, Any]:
        source = {
            "events": _records(htr010b_output / "htr010b_canonical_events.json"),
            "factors": _records(htr010b_output / "htr010b_adjustment_factors.json"),
            "continuity": _records(htr010b_output / "htr010b_price_continuity.json"),
            "basis": _records(htr010b_output / "htr010b_price_basis_intervals.json"),
            "summaries": _records(
                htr010b_output / "htr010b_adjusted_candle_summary.json"
            ),
            "coverage": _records(
                htr010b_output / "htr010b_identity_coverage_matrix.json"
            ),
            "transitions": _records(
                htr010b_output / "htr010b_identity_transitions.json"
            ),
            "joins": _records(
                htr010a3_output / "htr010a3_corporate_action_join_readiness.json"
            ),
        }
        diagnostics: dict[str, Any] = {
            "contract_version": HTR010B1A_CONTRACT_VERSION,
            "datasets": {},
            "alias_applications": [],
            "errors": [],
        }
        events = _require_rows(
            "events",
            source["events"],
            ("canonical_event_id", "governed_identity_id", "effective_date"),
            diagnostics,
        )
        factors = _require_rows(
            "factors",
            source["factors"],
            ("canonical_event_id", "identity_key", "effective_date", "factor_state"),
            diagnostics,
        )
        coverage = _require_rows(
            "coverage",
            source["coverage"],
            ("identity_key", "symbol"),
            diagnostics,
        )
        joins = _require_rows(
            "joins",
            source["joins"],
            ("identity_key", "admitted_to_certified_join"),
            diagnostics,
        )
        summaries = tuple(
            _apply_aliases(
                "summaries",
                row,
                {
                    "raw_row_count": ("raw_row_count", "raw_rows"),
                    "adjusted_row_count": ("adjusted_row_count", "adjusted_rows"),
                },
                diagnostics,
            )
            for row in source["summaries"]
        )
        summaries = _require_rows(
            "summaries",
            summaries,
            (
                "identity_key",
                "raw_row_count",
                "adjusted_row_count",
                "price_basis_state",
            ),
            diagnostics,
        )
        basis = tuple(
            _apply_aliases(
                "basis",
                row,
                {
                    "interval_start": ("interval_start", "start_date", "valid_from"),
                    "interval_end": ("interval_end", "end_date", "valid_to"),
                },
                diagnostics,
            )
            for row in source["basis"]
        )
        basis = _require_rows(
            "basis",
            basis,
            ("identity_key", "interval_start", "interval_end", "price_basis_state"),
            diagnostics,
        )
        continuity = tuple(
            _apply_aliases(
                "continuity",
                row,
                {
                    "event_id": ("event_id", "canonical_event_id", "action_id"),
                    "raw_gap_atr": ("raw_gap_atr", "raw_moving_average_discontinuity"),
                    "adjusted_gap_atr": (
                        "adjusted_gap_atr",
                        "adjusted_moving_average_discontinuity",
                    ),
                },
                diagnostics,
            )
            for row in source["continuity"]
        )
        continuity = _require_rows(
            "continuity",
            continuity,
            ("event_id", "continuity_state", "raw_gap_atr", "adjusted_gap_atr"),
            diagnostics,
            allow_empty=True,
        )
        transition_rows = tuple(source["transitions"])
        tier_a = {
            str(row["identity_key"])
            for row in joins
            if bool(row.get("admitted_to_certified_join"))
        }
        coverage_ids = {str(row["identity_key"]) for row in coverage}
        diagnostics["tier_a_join_identity_count"] = len(tier_a)
        diagnostics["htr010b_coverage_identity_count"] = len(coverage_ids)
        diagnostics["identity_set_match"] = tier_a == coverage_ids
        if tier_a != coverage_ids:
            diagnostics["errors"].append("HTR010A3_HTR010B_IDENTITY_SET_MISMATCH")
        diagnostics["state"] = (
            "INPUT_CONTRACT_VALID"
            if not diagnostics["errors"]
            else "INPUT_CONTRACT_INVALID"
        )
        if diagnostics["errors"]:
            raise InputContractError(
                "HTR-010B1A input contract failed: "
                + ", ".join(str(item) for item in diagnostics["errors"])
            )
        return {
            "events": events,
            "factors": factors,
            "continuity": continuity,
            "basis": basis,
            "summaries": summaries,
            "coverage": coverage,
            "transitions": transition_rows,
            "joins": joins,
            "diagnostics": diagnostics,
        }


class AdjustmentReplayAdmissionRepairEngine:
    """Produce a fail-closed HTR-010B1A admission and weighting contract."""

    def run(
        self,
        *,
        database_path: Path,
        htr010a3_output: Path,
        htr010b_output: Path,
        start_date: date,
        end_date: date,
    ) -> AdjustmentReplayAdmissionReport:
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        inputs = HTR010BInputAdapter().load(htr010b_output, htr010a3_output)
        population = candle_population(
            database_path,
            inputs["coverage"],
            start_date,
            end_date,
        )
        cases = factor_validation_cases_repaired(
            inputs["events"], inputs["factors"], inputs["continuity"]
        )
        results = tuple(classify_factor_case_repaired(row) for row in cases)
        unknown = unknown_factor_impact(inputs["events"], inputs["factors"])
        mixed = mixed_basis_resolutions(
            inputs["basis"],
            inputs["summaries"],
            inputs["factors"],
            inputs["transitions"],
        )
        quarantine = quarantine_census_repaired(
            basis=inputs["basis"],
            results=results,
            unknown_rows=unknown,
            mixed_rows=mixed,
            start_date=start_date,
            end_date=end_date,
        )
        economic_weight, weight_summary = quarantine_economic_weight(
            database_path=database_path,
            quarantine=quarantine,
            population=population,
            start_date=start_date,
            end_date=end_date,
        )
        intervals = segmented_replay_admission_intervals(
            coverage=inputs["coverage"],
            factors=inputs["factors"],
            sessions=population["sessions"],
            start_date=start_date,
            end_date=end_date,
        )
        lookbacks = session_based_lookback_safety(
            intervals, population["sessions"], (14, 20, 50, 200)
        )
        reporting = population_reconciliation(
            quarantine=quarantine,
            intervals=intervals,
            results=results,
        )
        readiness = replay_readiness_repaired(
            input_contract=inputs["diagnostics"],
            population=population,
            weight_summary=weight_summary,
            intervals=intervals,
            results=results,
            mixed=mixed,
            reporting=reporting,
        )
        transform = {
            **transformation_contract(),
            "contract_version": TRANSFORMATION_CONTRACT_VERSION,
            "session_calendar_source": "daily_candle_distinct_trading_date",
            "calendar_day_lookback_approximation": False,
            "identity_date_segmentation": True,
            "active_replay_integration": False,
        }
        coverage = coverage_matrix_repaired(
            inputs["coverage"], intervals, quarantine, lookbacks
        )
        rejected = tuple(
            row
            for row in results
            if row["validation_outcome"]
            in {
                ValidationOutcome.FACTOR_CONFLICTING_OFFICIAL_EVIDENCE.value,
                ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE.value,
                ValidationOutcome.IMPLEMENTATION_DEFECT.value,
                ValidationOutcome.UNRESOLVED.value,
            }
        )
        report = AdjustmentReplayAdmissionReport(
            contract_version=HTR010B1A_CONTRACT_VERSION,
            transformation_contract_version=TRANSFORMATION_CONTRACT_VERSION,
            production_influence=PRODUCTION_INFLUENCE,
            start_date=start_date,
            end_date=end_date,
            input_contract_diagnostics=inputs["diagnostics"],
            population_reconciliation=population_summary(population),
            quarantine_population_reconciliation={
                **reporting,
                **weight_summary,
            },
            quarantine_census=tuple(sorted(quarantine, key=_row_key)),
            quarantine_economic_weight=tuple(sorted(economic_weight, key=_row_key)),
            factor_validation_cases=tuple(sorted(cases, key=_row_key)),
            factor_validation_results=tuple(sorted(results, key=_row_key)),
            event_boundaries=tuple(
                sorted(
                    event_boundaries_repaired(inputs["events"], population["sessions"]),
                    key=_row_key,
                )
            ),
            multiple_action_cases=tuple(
                sorted(multiple_action_cases(inputs["events"]), key=_row_key)
            ),
            series_applicability=tuple(
                sorted(series_applicability(inputs["events"]), key=_row_key)
            ),
            unknown_factor_impact=tuple(sorted(unknown, key=_row_key)),
            mixed_basis_resolution=tuple(sorted(mixed, key=_row_key)),
            adjusted_row_audit=tuple(
                sorted(
                    adjusted_row_audit_repaired(inputs["summaries"], population),
                    key=_row_key,
                )
            ),
            replay_admission_intervals=tuple(sorted(intervals, key=_row_key)),
            indicator_lookback_safety=tuple(sorted(lookbacks, key=_row_key)),
            transformation_contract=transform,
            coverage_matrix=tuple(sorted(coverage, key=_row_key)),
            replay_readiness=readiness,
            rejected_evidence=tuple(sorted(rejected, key=_row_key)),
            report_sha256="",
        )
        return replace(report, report_sha256=report.calculated_sha256())


def candle_population(
    database_path: Path,
    coverage: tuple[dict[str, Any], ...],
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    identities = tuple(str(row["identity_key"]) for row in coverage)
    isins = tuple(
        identity.removeprefix("nse:isin:")
        for identity in identities
        if identity.startswith("nse:isin:")
    )
    if len(isins) != len(identities):
        raise InputContractError("Tier A population contains non-ISIN identity keys")
    with duckdb.connect(str(database_path), read_only=True) as connection:
        columns = {
            str(row[0])
            for row in connection.execute("DESCRIBE daily_candle").fetchall()
        }
        required = {"trading_date", "exchange", "isin"}
        if not required <= columns:
            raise InputContractError(
                "daily_candle missing required columns: "
                + ", ".join(sorted(required - columns))
            )
        connection.execute("CREATE TEMP TABLE tier_a_isin(isin VARCHAR PRIMARY KEY)")
        connection.executemany(
            "INSERT INTO tier_a_isin VALUES (?)", [(item,) for item in isins]
        )
        grouped = connection.execute(
            "SELECT c.isin, COUNT(*) AS candle_rows, "
            "COUNT(DISTINCT c.trading_date) AS identity_sessions "
            "FROM daily_candle c JOIN tier_a_isin t USING(isin) "
            "WHERE lower(c.exchange)='nse' AND c.trading_date BETWEEN ? AND ? "
            "GROUP BY c.isin",
            [start_date, end_date],
        ).fetchall()
        sessions = tuple(
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT trading_date FROM daily_candle "
                "WHERE lower(exchange)='nse' AND trading_date BETWEEN ? AND ? "
                "ORDER BY trading_date",
                [start_date, end_date],
            ).fetchall()
        )
        observed = connection.execute(
            "SELECT MIN(trading_date), MAX(trading_date), COUNT(*) "
            "FROM daily_candle WHERE lower(exchange)='nse' "
            "AND trading_date BETWEEN ? AND ?",
            [start_date, end_date],
        ).fetchone()
    by_identity: dict[str, dict[str, int | str]] = {
        f"nse:isin:{row[0]}": {
            "identity_key": f"nse:isin:{row[0]}",
            "observed_candle_rows": int(row[1]),
            "observed_identity_sessions": int(row[2]),
        }
        for row in grouped
    }
    total_rows = sum(int(row["observed_candle_rows"]) for row in by_identity.values())
    total_identity_sessions = sum(
        int(row["observed_identity_sessions"]) for row in by_identity.values()
    )
    observed_start = observed[0] if observed else None
    observed_end = observed[1] if observed else None
    coverage_complete = observed_start == start_date and observed_end == end_date
    return {
        "by_identity": by_identity,
        "sessions": sessions,
        "requested_start": start_date,
        "requested_end": end_date,
        "observed_start": observed_start,
        "observed_end": observed_end,
        "observed_exchange_session_count": len(sessions),
        "observed_tier_a_candle_rows": total_rows,
        "observed_tier_a_identity_sessions": total_identity_sessions,
        "identities_with_observed_rows": len(by_identity),
        "tier_a_identity_count": len(identities),
        "identities_without_observed_rows": len(identities) - len(by_identity),
        "requested_window_fully_observed": coverage_complete,
    }


def factor_validation_cases_repaired(
    events: tuple[dict[str, Any], ...],
    factors: tuple[dict[str, Any], ...],
    continuity: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    event_map = {str(row["canonical_event_id"]): row for row in events}
    factor_map = {str(row["canonical_event_id"]): row for row in factors}
    rows = []
    for item in continuity:
        if str(item.get("continuity_state")) != "FACTOR_LIKELY_INCORRECT":
            continue
        event_id = str(item["event_id"])
        event = event_map.get(event_id, {})
        factor = factor_map.get(event_id, {})
        rows.append(
            {
                "case_id": stable_id("factor-case", event_id),
                "event_id": event_id,
                "identity_key": _identity(event, factor, item),
                "symbol": _first(event, factor, item, key="symbol"),
                "series": _first(event, factor, item, key="series"),
                "isin": _first(event, factor, item, key="isin"),
                "action_type": _first(event, factor, item, key="action_type"),
                "effective_date": _first(event, factor, item, key="effective_date"),
                "factor_state": factor.get("factor_state"),
                "price_factor": factor.get("price_factor"),
                "raw_gap_atr": _number(item.get("raw_gap_atr")),
                "adjusted_gap_atr": _number(item.get("adjusted_gap_atr")),
                "factor_plausible": item.get("factor_plausible"),
                "continuity_state": item.get("continuity_state"),
                "source_ids": event.get("source_ids") or [],
            }
        )
    return tuple(rows)


def classify_factor_case_repaired(case: dict[str, Any]) -> dict[str, Any]:
    state = str(case.get("factor_state") or "")
    raw_gap = _number(case.get("raw_gap_atr"))
    adjusted_gap = _number(case.get("adjusted_gap_atr"))
    if state in NON_MULTIPLICATIVE_STATES:
        outcome = ValidationOutcome.FACTOR_NON_MULTIPLICATIVE
    elif state in AMBIGUOUS_FACTOR_STATES:
        outcome = ValidationOutcome.FACTOR_CONFLICTING_OFFICIAL_EVIDENCE
    elif state in UNKNOWN_FACTOR_STATES:
        outcome = ValidationOutcome.FACTOR_REQUIRES_REFERENCE_PRICE
    elif raw_gap is None or adjusted_gap is None:
        outcome = ValidationOutcome.IMPLEMENTATION_DEFECT
    elif adjusted_gap <= 2.0 or adjusted_gap < raw_gap:
        outcome = ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MARKET_GAP
    elif adjusted_gap > 5.0 and adjusted_gap > raw_gap:
        outcome = ValidationOutcome.IMPLEMENTATION_DEFECT
    else:
        outcome = ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE
    admitted = outcome in {
        ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MARKET_GAP,
        ValidationOutcome.FACTOR_CONFIRMED_CORRECT_THIN_TRADING,
        ValidationOutcome.FACTOR_CONFIRMED_CORRECT_EVENT_DATE_OFFSET,
        ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MULTIPLE_ACTIONS,
    }
    return {
        **case,
        "validation_outcome": outcome.value,
        "admitted_to_replay": admitted,
        "requires_quarantine": not admitted,
        "classification_contract": HTR010B1A_CONTRACT_VERSION,
        "production_influence": False,
    }


def quarantine_census_repaired(
    *,
    basis: tuple[dict[str, Any], ...],
    results: tuple[dict[str, Any], ...],
    unknown_rows: tuple[dict[str, Any], ...],
    mixed_rows: tuple[dict[str, Any], ...],
    start_date: date,
    end_date: date,
) -> tuple[dict[str, Any], ...]:
    raw = []
    for row in basis:
        state = str(row.get("price_basis_state") or "")
        if state in {
            "FACTOR_UNKNOWN",
            "FACTOR_AMBIGUOUS",
            "MIXED_PRICE_BASIS",
            "CONFLICTING_OFFICIAL_EVIDENCE",
        }:
            raw.append(
                _quarantine_row(
                    row,
                    row.get("interval_start"),
                    row.get("interval_end"),
                    state,
                    row.get("action_ids") or [],
                )
            )
    for row in results:
        if row.get("requires_quarantine"):
            effective = row.get("effective_date")
            raw.append(
                _quarantine_row(
                    row,
                    effective,
                    effective,
                    row.get("validation_outcome"),
                    [row.get("event_id")],
                )
            )
    for row in unknown_rows:
        if row.get("replay_impact") in {
            ReplayImpact.REQUIRE_CERTIFIED_FACTOR.value,
            ReplayImpact.QUARANTINE_INTERVAL.value,
        }:
            effective = row.get("effective_date")
            raw.append(
                _quarantine_row(
                    row,
                    effective,
                    effective,
                    row.get("replay_impact"),
                    [row.get("event_id")],
                )
            )
    for row in mixed_rows:
        if str(row.get("resolution_state")) == "MIXED_BASIS_QUARANTINED":
            raw.append(
                _quarantine_row(
                    row,
                    start_date,
                    end_date,
                    "MIXED_PRICE_BASIS",
                    [],
                )
            )
    dedup = {}
    for row in raw:
        key = stable_id(
            "quarantine",
            row["identity_key"],
            row["interval_start"],
            row["interval_end"],
            row["quarantine_reason"],
        )
        dedup[key] = {"quarantine_id": key, **row, "production_influence": False}
    return tuple(dedup.values())


def quarantine_economic_weight(
    *,
    database_path: Path,
    quarantine: tuple[dict[str, Any], ...],
    population: dict[str, Any],
    start_date: date,
    end_date: date,
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    ranges_by_identity: dict[str, list[tuple[date, date]]] = defaultdict(list)
    reasons_by_identity: dict[str, set[str]] = defaultdict(set)
    symbols: dict[str, Any] = {}
    for row in quarantine:
        identity = str(row["identity_key"])
        start = _date(row.get("interval_start")) or start_date
        end = _date(row.get("interval_end")) or end_date
        ranges_by_identity[identity].append((start, end))
        reasons_by_identity[identity].add(str(row.get("quarantine_reason")))
        symbols[identity] = row.get("symbol")
    rows: list[dict[str, Any]] = []
    with duckdb.connect(str(database_path), read_only=True) as connection:
        for identity, ranges in sorted(ranges_by_identity.items()):
            merged = _merge_ranges(ranges)
            isin = identity.removeprefix("nse:isin:")
            predicates = " OR ".join("(trading_date BETWEEN ? AND ?)" for _ in merged)
            params: list[Any] = [isin]
            for range_start, range_end in merged:
                params.extend((range_start, range_end))
            result = connection.execute(
                "SELECT COUNT(*), COUNT(DISTINCT trading_date) FROM daily_candle "
                "WHERE isin=? AND lower(exchange)='nse' AND (" + predicates + ")",
                params,
            ).fetchone()
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
                        affected_rows, population["observed_tier_a_candle_rows"]
                    ),
                    "pct_observed_tier_a_identity_sessions": _pct(
                        affected_sessions,
                        population["observed_tier_a_identity_sessions"],
                    ),
                    "reasons": sorted(reasons_by_identity[identity]),
                    "measurement_state": (
                        "MEASURED_OBSERVED_WINDOW"
                        if population["observed_tier_a_candle_rows"] > 0
                        else "DENOMINATOR_UNAVAILABLE"
                    ),
                }
            )
    measured_rows = sum(int(row["affected_candle_rows"]) for row in rows)
    measured_sessions = sum(int(row["affected_identity_sessions"]) for row in rows)
    summary = {
        "economic_weight_measurement_state": (
            "MEASURED_PARTIAL_WINDOW"
            if not population["requested_window_fully_observed"]
            else "MEASURED_COMPLETE_WINDOW"
        ),
        "observed_quarantined_candle_rows": measured_rows,
        "observed_quarantined_identity_sessions": measured_sessions,
        "pct_observed_tier_a_rows_quarantined": _pct(
            measured_rows, population["observed_tier_a_candle_rows"]
        ),
        "pct_observed_tier_a_identity_sessions_quarantined": _pct(
            measured_sessions, population["observed_tier_a_identity_sessions"]
        ),
    }
    return tuple(rows), summary


def segmented_replay_admission_intervals(
    *,
    coverage: tuple[dict[str, Any], ...],
    factors: tuple[dict[str, Any], ...],
    sessions: tuple[date, ...],
    start_date: date,
    end_date: date,
) -> tuple[dict[str, Any], ...]:
    if not sessions:
        raise InputContractError(
            "no governed NSE sessions available for interval segmentation"
        )
    factors_by_identity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in factors:
        effective = _date(row.get("effective_date"))
        if effective and start_date <= effective <= end_date:
            factors_by_identity[str(row["identity_key"])].append(row)
    rows = []
    for identity_row in coverage:
        identity = str(identity_row["identity_key"])
        identity_factors = sorted(
            factors_by_identity.get(identity, []),
            key=lambda row: (str(row["effective_date"]), str(row.get("factor_id"))),
        )
        grouped: dict[date, list[dict[str, Any]]] = defaultdict(list)
        for factor in identity_factors:
            boundary = _session_on_or_after(sessions, _date(factor["effective_date"]))
            if boundary:
                grouped[boundary].append(factor)
        boundaries = sorted(grouped)
        starts = [sessions[0], *boundaries]
        starts = sorted(set(starts))
        for index, interval_start in enumerate(starts):
            next_start = starts[index + 1] if index + 1 < len(starts) else None
            interval_end = (
                _previous_session(sessions, next_start)
                if next_start is not None
                else sessions[-1]
            )
            if interval_end is None or interval_end < interval_start:
                continue
            future_factors = [
                factor
                for boundary, items in grouped.items()
                if boundary > interval_start
                for factor in items
            ]
            preceding = grouped.get(interval_start, [])
            future_states = {str(row.get("factor_state")) for row in future_factors}
            preceding_states = {str(row.get("factor_state")) for row in preceding}
            if not identity_factors:
                state = AdmissionState.RAW_REPLAY_CERTIFIED_NO_ACTION_EXPOSURE
                admitted_view = "RAW"
            elif not future_factors:
                state = AdmissionState.RAW_REPLAY_CERTIFIED_POST_EVENT_SEGMENT
                admitted_view = "RAW"
            elif future_states & AMBIGUOUS_FACTOR_STATES:
                state = AdmissionState.FACTOR_AMBIGUOUS_QUARANTINED
                admitted_view = "NONE"
            elif future_states & UNKNOWN_FACTOR_STATES:
                state = AdmissionState.FACTOR_UNKNOWN_QUARANTINED
                admitted_view = "NONE"
            elif future_states & NON_MULTIPLICATIVE_STATES:
                state = AdmissionState.IDENTITY_TRANSITION_NONCOMPARABLE
                admitted_view = "RAW"
            elif future_states <= CERTIFIED_FACTOR_STATES:
                state = AdmissionState.ADJUSTED_REPLAY_CERTIFIED_TRADABILITY_PARTIAL
                admitted_view = "ADJUSTED"
            else:
                state = AdmissionState.UNRESOLVED
                admitted_view = "NONE"
            reset_required = bool(
                preceding_states
                & (
                    UNKNOWN_FACTOR_STATES
                    | AMBIGUOUS_FACTOR_STATES
                    | NON_MULTIPLICATIVE_STATES
                )
            )
            rows.append(
                {
                    "admission_interval_id": stable_id(
                        "replay-admission",
                        identity,
                        interval_start,
                        interval_end,
                        state.value,
                    ),
                    "identity_key": identity,
                    "symbol": identity_row.get("symbol"),
                    "series": identity_row.get("series"),
                    "isin": identity_row.get("isin"),
                    "start_date": interval_start.isoformat(),
                    "end_date": interval_end.isoformat(),
                    "admission_state": state.value,
                    "admitted_price_view": admitted_view,
                    "prohibited_price_view": "MIXED",
                    "preceding_boundary_factor_states": sorted(preceding_states),
                    "future_bridge_factor_states": sorted(future_states),
                    "reset_required": reset_required,
                    "session_calendar_source": "daily_candle_distinct_trading_date",
                    "production_influence": False,
                }
            )
    return tuple(rows)


def session_based_lookback_safety(
    intervals: tuple[dict[str, Any], ...],
    sessions: tuple[date, ...],
    lookbacks: tuple[int, ...],
) -> tuple[dict[str, Any], ...]:
    rows = []
    for interval in intervals:
        start = _date(interval["start_date"])
        end = _date(interval["end_date"])
        if start is None or end is None:
            continue
        start_index = bisect.bisect_left(sessions, start)
        state = str(interval["admission_state"])
        for lookback in lookbacks:
            if state in QUARANTINE_ADMISSION_STATES:
                earliest = None
                safety = "QUARANTINED"
            elif interval.get("reset_required"):
                candidate_index = start_index + lookback - 1
                candidate = (
                    sessions[candidate_index]
                    if candidate_index < len(sessions)
                    else None
                )
                earliest = candidate if candidate and candidate <= end else None
                safety = (
                    "SAFE_AFTER_SESSION_RESET"
                    if earliest
                    else "INSUFFICIENT_SEGMENT_SESSIONS"
                )
            else:
                earliest = start
                safety = "SAFE_WITHOUT_RESET"
            rows.append(
                {
                    "identity_key": interval["identity_key"],
                    "admission_interval_id": interval["admission_interval_id"],
                    "lookback_sessions": lookback,
                    "safety_state": safety,
                    "earliest_safe_date": earliest.isoformat() if earliest else None,
                    "reset_required": bool(interval.get("reset_required")),
                    "calendar_day_approximation": False,
                }
            )
    return tuple(rows)


def replay_readiness_repaired(
    *,
    input_contract: dict[str, Any],
    population: dict[str, Any],
    weight_summary: dict[str, Any],
    intervals: tuple[dict[str, Any], ...],
    results: tuple[dict[str, Any], ...],
    mixed: tuple[dict[str, Any], ...],
    reporting: dict[str, Any],
) -> dict[str, Any]:
    states = Counter(str(row["admission_state"]) for row in intervals)
    outcomes = Counter(str(row["validation_outcome"]) for row in results)
    silent_mixed = sum(bool(row.get("silent_mixed_basis")) for row in mixed)
    blockers = []
    if input_contract.get("state") != "INPUT_CONTRACT_VALID":
        blockers.append("INPUT_CONTRACT_INVALID")
    if population["observed_tier_a_candle_rows"] == 0:
        blockers.append("ECONOMIC_WEIGHT_DENOMINATOR_UNAVAILABLE")
    if not population["requested_window_fully_observed"]:
        blockers.append("REQUESTED_HISTORICAL_WINDOW_NOT_FULLY_OBSERVED")
    if outcomes[ValidationOutcome.IMPLEMENTATION_DEFECT.value]:
        blockers.append("FACTOR_TRANSFORMATION_IMPLEMENTATION_DEFECTS")
    if outcomes[ValidationOutcome.UNRESOLVED.value]:
        blockers.append("UNRESOLVED_FACTOR_CASES")
    if silent_mixed:
        blockers.append("SILENT_MIXED_PRICE_BASIS")
    if weight_summary["economic_weight_measurement_state"] == "DENOMINATOR_UNAVAILABLE":
        blockers.append("QUARANTINE_WEIGHT_UNMEASURED")
    quarantined_intervals = sum(states[state] for state in QUARANTINE_ADMISSION_STATES)
    if blockers:
        readiness = ReplayReadiness.NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION
    elif quarantined_intervals:
        readiness = ReplayReadiness.CONDITIONALLY_READY_FOR_ADJUSTED_REPLAY_INTEGRATION
    else:
        readiness = ReplayReadiness.READY_FOR_ADJUSTED_REPLAY_INTEGRATION
    return {
        "state": readiness.value,
        "blockers": sorted(set(blockers)),
        "admission_interval_count": len(intervals),
        "admission_state_counts": dict(sorted(states.items())),
        "validation_outcomes": dict(sorted(outcomes.items())),
        "admission_quarantined_identity_count": reporting[
            "admission_quarantined_identity_count"
        ],
        "evidence_quarantined_identity_count": reporting[
            "evidence_quarantined_identity_count"
        ],
        "unresolved_case_identity_count": reporting["unresolved_case_identity_count"],
        "quarantine_population_overlap_count": reporting[
            "quarantine_population_overlap_count"
        ],
        "silent_mixed_basis_count": silent_mixed,
        "economic_weight_measurement_state": weight_summary[
            "economic_weight_measurement_state"
        ],
        "unknown_factor_applied_as_one": False,
        "calendar_day_lookback_approximation": False,
        "active_replay_integration": False,
        "production_influence": False,
    }


def population_reconciliation(
    *,
    quarantine: tuple[dict[str, Any], ...],
    intervals: tuple[dict[str, Any], ...],
    results: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    evidence_ids = {str(row["identity_key"]) for row in quarantine}
    admission_ids = {
        str(row["identity_key"])
        for row in intervals
        if str(row["admission_state"]) in QUARANTINE_ADMISSION_STATES
    }
    unresolved_ids = {
        str(row["identity_key"])
        for row in results
        if str(row["validation_outcome"]) == ValidationOutcome.UNRESOLVED.value
    }
    return {
        "admission_quarantined_identity_count": len(admission_ids),
        "evidence_quarantined_identity_count": len(evidence_ids),
        "unresolved_case_identity_count": len(unresolved_ids),
        "quarantine_population_overlap_count": len(admission_ids & evidence_ids),
        "evidence_only_identity_count": len(evidence_ids - admission_ids),
        "admission_only_identity_count": len(admission_ids - evidence_ids),
    }


def population_summary(population: dict[str, Any]) -> dict[str, Any]:
    return {
        key: (value.isoformat() if isinstance(value, date) else value)
        for key, value in population.items()
        if key not in {"by_identity", "sessions"}
    }


def event_boundaries_repaired(
    events: tuple[dict[str, Any], ...], sessions: tuple[date, ...]
) -> tuple[dict[str, Any], ...]:
    rows = []
    for row in events:
        effective = _date(row.get("effective_date") or row.get("ex_date"))
        observed = _session_on_or_after(sessions, effective)
        rows.append(
            {
                "event_id": row.get("canonical_event_id"),
                "identity_key": row.get("governed_identity_id"),
                "official_ex_date": row.get("ex_date"),
                "effective_date": effective.isoformat() if effective else None,
                "observed_boundary_session": observed.isoformat() if observed else None,
                "boundary_confidence": "HIGH" if row.get("ex_date") else "MODERATE",
                "session_calendar_source": "daily_candle_distinct_trading_date",
            }
        )
    return tuple(rows)


def adjusted_row_audit_repaired(
    summaries: tuple[dict[str, Any], ...], population: dict[str, Any]
) -> tuple[dict[str, Any], ...]:
    rows = []
    for row in summaries:
        identity = str(row["identity_key"])
        observed = population["by_identity"].get(identity, {})
        rows.append(
            {
                "identity_key": identity,
                "symbol": row.get("symbol"),
                "upstream_raw_rows": int(row.get("raw_row_count") or 0),
                "upstream_adjusted_rows": int(row.get("adjusted_row_count") or 0),
                "observed_candle_rows": int(observed.get("observed_candle_rows") or 0),
                "observed_identity_sessions": int(
                    observed.get("observed_identity_sessions") or 0
                ),
                "row_contract_alias_repaired": True,
                "population_measurement_window_complete": population[
                    "requested_window_fully_observed"
                ],
            }
        )
    return tuple(rows)


def coverage_matrix_repaired(
    coverage: tuple[dict[str, Any], ...],
    intervals: tuple[dict[str, Any], ...],
    quarantine: tuple[dict[str, Any], ...],
    lookbacks: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    intervals_by_identity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in intervals:
        intervals_by_identity[str(row["identity_key"])].append(row)
    quarantine_count = Counter(str(row["identity_key"]) for row in quarantine)
    lookback_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in lookbacks:
        lookback_counts[str(row["identity_key"])][str(row["safety_state"])] += 1
    return tuple(
        {
            "identity_key": row["identity_key"],
            "symbol": row.get("symbol"),
            "isin": row.get("isin"),
            "admission_interval_count": len(
                intervals_by_identity[str(row["identity_key"])]
            ),
            "admission_states": sorted(
                {
                    str(item["admission_state"])
                    for item in intervals_by_identity[str(row["identity_key"])]
                }
            ),
            "quarantine_interval_count": quarantine_count[str(row["identity_key"])],
            "safe_lookback_count": sum(
                value
                for key, value in lookback_counts[str(row["identity_key"])].items()
                if key.startswith("SAFE")
            ),
            "quarantined_lookback_count": lookback_counts[str(row["identity_key"])][
                "QUARANTINED"
            ],
        }
        for row in coverage
    )


def _require_rows(
    dataset: str,
    rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    required: tuple[str, ...],
    diagnostics: dict[str, Any],
    *,
    allow_empty: bool = False,
) -> tuple[dict[str, Any], ...]:
    normalized = tuple(rows)
    fields = sorted({str(key) for row in normalized for key in row})
    missing = sorted(
        key
        for key in required
        if normalized and any(key not in row for row in normalized)
    )
    if not normalized and not allow_empty:
        diagnostics["errors"].append(f"{dataset.upper()}_EMPTY")
    if missing:
        diagnostics["errors"].append(
            f"{dataset.upper()}_MISSING_FIELDS:{','.join(missing)}"
        )
    diagnostics["datasets"][dataset] = {
        "record_count": len(normalized),
        "fields": fields,
        "required_fields": list(required),
        "missing_fields": missing,
    }
    return normalized


def _apply_aliases(
    dataset: str,
    row: dict[str, Any],
    aliases: dict[str, tuple[str, ...]],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    result = dict(row)
    for target, candidates in aliases.items():
        if target in result and result[target] is not None:
            continue
        for candidate in candidates:
            if candidate in row and row[candidate] is not None:
                result[target] = row[candidate]
                if candidate != target:
                    diagnostics["alias_applications"].append(
                        {"dataset": dataset, "source": candidate, "target": target}
                    )
                break
    return result


def _quarantine_row(
    row: dict[str, Any],
    interval_start: Any,
    interval_end: Any,
    reason: Any,
    action_ids: list[Any],
) -> dict[str, Any]:
    return {
        "identity_key": _identity(row),
        "symbol": row.get("symbol"),
        "series": row.get("series"),
        "isin": row.get("isin"),
        "interval_start": _iso(interval_start),
        "interval_end": _iso(interval_end),
        "quarantine_reason": str(reason),
        "action_ids": [str(item) for item in action_ids if item],
    }


def _records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise InputContractError(f"required artifact is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("records", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise InputContractError(f"expected a record list: {path}")
    return rows


def _merge_ranges(ranges: list[tuple[date, date]]) -> list[tuple[date, date]]:
    merged: list[tuple[date, date]] = []
    for start, end in sorted(ranges):
        if not merged or start > merged[-1][1] + timedelta(days=1):
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _session_on_or_after(sessions: tuple[date, ...], value: date | None) -> date | None:
    if value is None:
        return None
    index = bisect.bisect_left(sessions, value)
    return sessions[index] if index < len(sessions) else None


def _previous_session(sessions: tuple[date, ...], value: date | None) -> date | None:
    if value is None:
        return None
    index = bisect.bisect_left(sessions, value) - 1
    return sessions[index] if index >= 0 else None


def _identity(*rows: dict[str, Any]) -> str:
    for row in rows:
        value = (
            row.get("identity_key")
            or row.get("governed_identity_id")
            or row.get("identity_id")
        )
        if value:
            return str(value)
    return ""


def _first(*rows: dict[str, Any], key: str) -> Any:
    for row in rows:
        if row.get(key) is not None:
            return row[key]
    return None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _iso(value: Any) -> str | None:
    parsed = _date(value)
    return parsed.isoformat() if parsed else None


def _pct(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100.0, 8) if denominator else None


def _row_key(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, default=str)


__all__ = [
    "AdjustmentReplayAdmissionRepairEngine",
    "HTR010BInputAdapter",
    "HTR010B1A_CONTRACT_VERSION",
    "InputContractError",
    "candle_population",
    "classify_factor_case_repaired",
    "factor_validation_cases_repaired",
    "quarantine_economic_weight",
    "replay_readiness_repaired",
    "segmented_replay_admission_intervals",
    "session_based_lookback_safety",
]
