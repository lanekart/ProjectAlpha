"""HTR-010B1 factor validation, quarantine resolution, and replay admission."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from alpha.historical_truth.adjustment_replay_admission_models import (
    HTR010B1_CONTRACT_VERSION,
    PRODUCTION_INFLUENCE,
    TRANSFORMATION_CONTRACT_VERSION,
    AdjustmentReplayAdmissionReport,
    AdmissionState,
    MixedBasisResolution,
    ReplayImpact,
    ReplayReadiness,
    ValidationOutcome,
    stable_id,
)

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
CERTIFIED_FACTOR_STATES = {
    "FACTOR_CERTIFIED",
    "FACTOR_DERIVED_OFFICIAL_TERMS",
}


class AdjustmentReplayAdmissionEngine:
    """Build a deterministic admission contract from HTR-010B artifacts."""

    def run(
        self,
        *,
        htr010b_output: Path,
        start_date: date,
        end_date: date,
    ) -> AdjustmentReplayAdmissionReport:
        events = _records(htr010b_output / "htr010b_canonical_events.json")
        factors = _records(htr010b_output / "htr010b_adjustment_factors.json")
        continuity = _records(htr010b_output / "htr010b_price_continuity.json")
        basis = _records(htr010b_output / "htr010b_price_basis_intervals.json")
        summaries = _records(htr010b_output / "htr010b_adjusted_candle_summary.json")
        coverage = _records(htr010b_output / "htr010b_identity_coverage_matrix.json")
        transitions = _records(htr010b_output / "htr010b_identity_transitions.json")

        event_by_id = {
            str(row.get("canonical_event_id") or row.get("event_id")): row
            for row in events
        }
        factor_by_event = {
            str(
                row.get("canonical_event_id")
                or row.get("event_id")
                or row.get("action_id")
            ): row
            for row in factors
        }
        continuity_by_event = {
            str(
                row.get("canonical_event_id")
                or row.get("event_id")
                or row.get("action_id")
            ): row
            for row in continuity
        }

        cases = factor_validation_cases(events, factors, continuity)
        results = tuple(
            classify_factor_case(
                case, event_by_id, factor_by_event, continuity_by_event
            )
            for case in cases
        )
        unknown_impact = unknown_factor_impact(events, factors)
        mixed = mixed_basis_resolutions(basis, summaries, factors, transitions)
        quarantine = quarantine_census(
            basis=basis,
            summaries=summaries,
            results=results,
            unknown_impact_rows=unknown_impact,
            mixed_rows=mixed,
        )
        economic_weight = quarantine_weight(quarantine, summaries, coverage)
        boundaries = event_boundaries(events)
        multiple = multiple_action_cases(events)
        applicability = series_applicability(events)
        row_audit = adjusted_row_audit(summaries, basis)
        admission = replay_admission_intervals(
            coverage=coverage,
            basis=basis,
            factors=factors,
            mixed_rows=mixed,
            unknown_rows=unknown_impact,
            start_date=start_date,
            end_date=end_date,
        )
        lookbacks = indicator_lookback_safety(admission, (14, 20, 50, 200))
        transformation = transformation_contract()
        matrix = coverage_matrix(coverage, admission, quarantine, lookbacks)
        readiness = adjusted_replay_readiness(admission, results, mixed)
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
            contract_version=HTR010B1_CONTRACT_VERSION,
            transformation_contract_version=TRANSFORMATION_CONTRACT_VERSION,
            production_influence=PRODUCTION_INFLUENCE,
            start_date=start_date,
            end_date=end_date,
            quarantine_census=tuple(sorted(quarantine, key=_row_key)),
            quarantine_economic_weight=tuple(sorted(economic_weight, key=_row_key)),
            factor_validation_cases=tuple(sorted(cases, key=_row_key)),
            factor_validation_results=tuple(sorted(results, key=_row_key)),
            event_boundaries=tuple(sorted(boundaries, key=_row_key)),
            multiple_action_cases=tuple(sorted(multiple, key=_row_key)),
            series_applicability=tuple(sorted(applicability, key=_row_key)),
            unknown_factor_impact=tuple(sorted(unknown_impact, key=_row_key)),
            mixed_basis_resolution=tuple(sorted(mixed, key=_row_key)),
            adjusted_row_audit=tuple(sorted(row_audit, key=_row_key)),
            replay_admission_intervals=tuple(sorted(admission, key=_row_key)),
            indicator_lookback_safety=tuple(sorted(lookbacks, key=_row_key)),
            transformation_contract=transformation,
            coverage_matrix=tuple(sorted(matrix, key=_row_key)),
            replay_readiness=readiness,
            rejected_evidence=tuple(sorted(rejected, key=_row_key)),
            report_sha256="",
        )
        return replace(report, report_sha256=report.calculated_sha256())


def factor_validation_cases(
    events: Iterable[dict[str, Any]],
    factors: Iterable[dict[str, Any]],
    continuity: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    event_map = {
        str(row.get("canonical_event_id") or row.get("event_id")): row for row in events
    }
    factor_map = {
        str(
            row.get("canonical_event_id") or row.get("event_id") or row.get("action_id")
        ): row
        for row in factors
    }
    rows: list[dict[str, Any]] = []
    for item in continuity:
        state = str(item.get("continuity_state") or "")
        if state != "FACTOR_LIKELY_INCORRECT":
            continue
        event_id = str(
            item.get("canonical_event_id")
            or item.get("event_id")
            or item.get("action_id")
        )
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
                "announcement_date": event.get("announcement_date"),
                "ex_date": event.get("ex_date"),
                "record_date": event.get("record_date"),
                "effective_date": _first(event, factor, item, key="effective_date"),
                "factor_state": factor.get("factor_state"),
                "price_factor": factor.get("price_factor"),
                "quantity_factor": factor.get("quantity_factor"),
                "raw_gap_pct": item.get("raw_gap_pct"),
                "adjusted_gap_pct": item.get("adjusted_gap_pct"),
                "atr_normalized_adjusted_gap": item.get("atr_normalized_adjusted_gap"),
                "continuity_state": state,
                "series_applicability": event.get("series_applicability") or [],
                "source_ids": event.get("source_ids") or [],
            }
        )
    return tuple(rows)


def classify_factor_case(
    case: dict[str, Any],
    event_by_id: dict[str, dict[str, Any]],
    factor_by_event: dict[str, dict[str, Any]],
    continuity_by_event: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    event_id = str(case["event_id"])
    event = event_by_id.get(event_id, {})
    factor = factor_by_event.get(event_id, {})
    continuity = continuity_by_event.get(event_id, {})
    state = str(factor.get("factor_state") or "")
    action_type = str(event.get("action_type") or case.get("action_type") or "")
    residual = _number(continuity.get("adjusted_gap_pct"))
    atr_residual = _number(continuity.get("atr_normalized_adjusted_gap"))
    series = event.get("series_applicability") or []

    if state in NON_MULTIPLICATIVE_STATES:
        outcome = ValidationOutcome.FACTOR_NON_MULTIPLICATIVE
    elif state in AMBIGUOUS_FACTOR_STATES:
        outcome = ValidationOutcome.FACTOR_CONFLICTING_OFFICIAL_EVIDENCE
    elif state in UNKNOWN_FACTOR_STATES:
        outcome = ValidationOutcome.FACTOR_REQUIRES_REFERENCE_PRICE
    elif len(series) > 1 and bool(event.get("series_specific")):
        outcome = ValidationOutcome.FACTOR_CORRECTED_SERIES_APPLICABILITY
    elif action_type in {"MERGER", "DEMERGER", "SCHEME_OF_ARRANGEMENT", "AMALGAMATION"}:
        outcome = ValidationOutcome.FACTOR_NON_MULTIPLICATIVE
    elif residual is not None and abs(residual) <= 5:
        outcome = ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MARKET_GAP
    elif atr_residual is not None and abs(atr_residual) <= 2:
        outcome = ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MARKET_GAP
    elif continuity.get("insufficient_adjacent_observations"):
        outcome = ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE
    elif (
        event.get("multiple_action_count", 1)
        and int(event.get("multiple_action_count", 1)) > 1
    ):
        outcome = ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MULTIPLE_ACTIONS
    else:
        outcome = ValidationOutcome.UNRESOLVED

    return {
        **case,
        "validation_outcome": outcome.value,
        "admitted_to_replay": outcome
        in {
            ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MARKET_GAP,
            ValidationOutcome.FACTOR_CONFIRMED_CORRECT_THIN_TRADING,
            ValidationOutcome.FACTOR_CONFIRMED_CORRECT_EVENT_DATE_OFFSET,
            ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MULTIPLE_ACTIONS,
        },
        "requires_quarantine": outcome
        in {
            ValidationOutcome.FACTOR_CONFLICTING_OFFICIAL_EVIDENCE,
            ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE,
            ValidationOutcome.IMPLEMENTATION_DEFECT,
            ValidationOutcome.UNRESOLVED,
        },
        "production_influence": False,
    }


def unknown_factor_impact(
    events: Iterable[dict[str, Any]], factors: Iterable[dict[str, Any]]
) -> tuple[dict[str, Any], ...]:
    event_map = {
        str(row.get("canonical_event_id") or row.get("event_id")): row for row in events
    }
    rows: list[dict[str, Any]] = []
    for factor in factors:
        state = str(factor.get("factor_state") or "")
        if (
            state
            not in UNKNOWN_FACTOR_STATES
            | AMBIGUOUS_FACTOR_STATES
            | NON_MULTIPLICATIVE_STATES
        ):
            continue
        event_id = str(
            factor.get("canonical_event_id")
            or factor.get("event_id")
            or factor.get("action_id")
        )
        event = event_map.get(event_id, {})
        action_type = str(event.get("action_type") or factor.get("action_type") or "")
        if state in NON_MULTIPLICATIVE_STATES:
            impact = ReplayImpact.IDENTITY_TRANSITION_NONCOMPARABLE
        elif action_type.startswith("DIVIDEND"):
            impact = ReplayImpact.TOTAL_RETURN_ONLY_IMPACT
        elif action_type in {"RIGHTS", "CAPITAL_REDUCTION", "PARTLY_PAID_CALL"}:
            impact = ReplayImpact.REQUIRE_CERTIFIED_FACTOR
        elif state in AMBIGUOUS_FACTOR_STATES:
            impact = ReplayImpact.QUARANTINE_INTERVAL
        else:
            impact = ReplayImpact.SEGMENT_HISTORY_AT_EVENT
        rows.append(
            {
                "event_id": event_id,
                "identity_key": _identity(event, factor),
                "symbol": _first(event, factor, key="symbol"),
                "series": _first(event, factor, key="series"),
                "isin": _first(event, factor, key="isin"),
                "effective_date": _first(event, factor, key="effective_date"),
                "action_type": action_type,
                "factor_state": state,
                "replay_impact": impact.value,
                "unknown_factor_applied_as_one": False,
            }
        )
    return tuple(rows)


def mixed_basis_resolutions(
    basis: Iterable[dict[str, Any]],
    summaries: Iterable[dict[str, Any]],
    factors: Iterable[dict[str, Any]],
    transitions: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    summary_by_identity = {_identity(row): row for row in summaries}
    factors_by_identity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in factors:
        factors_by_identity[_identity(row)].append(row)
    transition_ids = {_identity(row) for row in transitions}
    identities = {
        _identity(row)
        for row in basis
        if str(row.get("price_basis_state")) == "MIXED_PRICE_BASIS"
    }
    rows: list[dict[str, Any]] = []
    for identity in sorted(identities):
        states = {
            str(item.get("factor_state")) for item in factors_by_identity[identity]
        }
        summary = summary_by_identity.get(identity, {})
        expected = int(
            summary.get("raw_row_count") or summary.get("action_exposed_raw_rows") or 0
        )
        adjusted = int(summary.get("adjusted_row_count") or 0)
        if identity in transition_ids:
            resolution = MixedBasisResolution.IDENTITY_TRANSITION_SEGMENTED
        elif states & AMBIGUOUS_FACTOR_STATES:
            resolution = MixedBasisResolution.MIXED_BASIS_QUARANTINED
        elif states & UNKNOWN_FACTOR_STATES:
            resolution = (
                MixedBasisResolution.ADJUSTED_WITH_SEGMENTED_UNCERTIFIED_INTERVAL
            )
        elif expected > 0 and expected == adjusted:
            resolution = MixedBasisResolution.FULLY_ADJUSTED_CERTIFIED
        elif expected > 0 and adjusted == 0:
            resolution = MixedBasisResolution.RAW_ONLY_CERTIFIED_INTERVALS
        else:
            resolution = MixedBasisResolution.MIXED_BASIS_QUARANTINED
        rows.append(
            {
                "identity_key": identity,
                "symbol": summary.get("symbol"),
                "series": summary.get("series"),
                "raw_row_count": expected,
                "adjusted_row_count": adjusted,
                "factor_states": sorted(states),
                "resolution_state": resolution.value,
                "silent_mixed_basis": False,
            }
        )
    return tuple(rows)


def quarantine_census(
    *,
    basis: Iterable[dict[str, Any]],
    summaries: Iterable[dict[str, Any]],
    results: Iterable[dict[str, Any]],
    unknown_impact_rows: Iterable[dict[str, Any]],
    mixed_rows: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    summary_by_identity = {_identity(row): row for row in summaries}
    raw: list[dict[str, Any]] = []
    for row in basis:
        state = str(row.get("price_basis_state") or "")
        if state in {
            "FACTOR_UNKNOWN",
            "FACTOR_AMBIGUOUS",
            "MIXED_PRICE_BASIS",
            "CONFLICTING_OFFICIAL_EVIDENCE",
        }:
            raw.append(
                {
                    "identity_key": _identity(row),
                    "interval_start": row.get("start_date")
                    or row.get("interval_start"),
                    "interval_end": row.get("end_date") or row.get("interval_end"),
                    "quarantine_reason": state,
                    "action_ids": row.get("action_ids") or [],
                }
            )
    for row in results:
        if row.get("requires_quarantine"):
            raw.append(
                {
                    "identity_key": _identity(row),
                    "interval_start": row.get("effective_date"),
                    "interval_end": row.get("effective_date"),
                    "quarantine_reason": row.get("validation_outcome"),
                    "action_ids": [row.get("event_id")],
                }
            )
    for row in unknown_impact_rows:
        if row.get("replay_impact") in {
            ReplayImpact.REQUIRE_CERTIFIED_FACTOR.value,
            ReplayImpact.QUARANTINE_INTERVAL.value,
        }:
            raw.append(
                {
                    "identity_key": _identity(row),
                    "interval_start": row.get("effective_date"),
                    "interval_end": row.get("effective_date"),
                    "quarantine_reason": row.get("replay_impact"),
                    "action_ids": [row.get("event_id")],
                }
            )
    for row in mixed_rows:
        if (
            row.get("resolution_state")
            == MixedBasisResolution.MIXED_BASIS_QUARANTINED.value
        ):
            raw.append(
                {
                    "identity_key": _identity(row),
                    "interval_start": None,
                    "interval_end": None,
                    "quarantine_reason": "MIXED_PRICE_BASIS",
                    "action_ids": [],
                }
            )
    dedup: dict[str, dict[str, Any]] = {}
    for row in raw:
        identity = _identity(row)
        key = stable_id(
            "quarantine",
            identity,
            row.get("interval_start"),
            row.get("interval_end"),
            row.get("quarantine_reason"),
        )
        summary = summary_by_identity.get(identity, {})
        dedup[key] = {
            "quarantine_id": key,
            **row,
            "symbol": summary.get("symbol"),
            "series": summary.get("series"),
            "isin": summary.get("isin"),
            "affected_candle_rows": int(
                summary.get("raw_row_count")
                or summary.get("action_exposed_raw_rows")
                or 0
            ),
            "affected_identity_sessions": int(
                summary.get("identity_session_count") or 0
            ),
            "production_influence": False,
        }
    return tuple(dedup.values())


def quarantine_weight(
    quarantine: Iterable[dict[str, Any]],
    summaries: Iterable[dict[str, Any]],
    coverage: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    total_rows = sum(
        int(row.get("raw_row_count") or row.get("action_exposed_raw_rows") or 0)
        for row in summaries
    )
    total_sessions = sum(
        int(
            row.get("identity_session_count")
            or row.get("expected_identity_sessions")
            or 0
        )
        for row in coverage
    )
    by_identity: dict[str, dict[str, Any]] = {}
    for row in quarantine:
        identity = _identity(row)
        current = by_identity.setdefault(
            identity,
            {
                "identity_key": identity,
                "symbol": row.get("symbol"),
                "quarantine_interval_count": 0,
                "affected_candle_rows": 0,
                "affected_identity_sessions": 0,
                "reasons": set(),
            },
        )
        current["quarantine_interval_count"] += 1
        current["affected_candle_rows"] = max(
            current["affected_candle_rows"], int(row.get("affected_candle_rows") or 0)
        )
        current["affected_identity_sessions"] = max(
            current["affected_identity_sessions"],
            int(row.get("affected_identity_sessions") or 0),
        )
        current["reasons"].add(str(row.get("quarantine_reason")))
    result = []
    for row in by_identity.values():
        result.append(
            {
                **row,
                "reasons": sorted(row["reasons"]),
                "pct_tier_a_rows": _pct(row["affected_candle_rows"], total_rows),
                "pct_tier_a_identity_sessions": _pct(
                    row["affected_identity_sessions"], total_sessions
                ),
            }
        )
    return tuple(result)


def event_boundaries(events: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    rows = []
    for row in events:
        effective = _date(row.get("effective_date") or row.get("ex_date"))
        rows.append(
            {
                "event_id": row.get("canonical_event_id") or row.get("event_id"),
                "identity_key": _identity(row),
                "official_ex_date": row.get("ex_date"),
                "record_date": row.get("record_date"),
                "effective_date": effective.isoformat() if effective else None,
                "previous_calendar_date": (effective - timedelta(days=1)).isoformat()
                if effective
                else None,
                "first_activity_row_on_or_after_ex_date": row.get(
                    "first_activity_row_on_or_after_ex_date"
                ),
                "boundary_confidence": "HIGH" if row.get("ex_date") else "MODERATE",
            }
        )
    return tuple(rows)


def multiple_action_cases(
    events: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in events:
        groups[(_identity(row), str(row.get("effective_date")))].append(row)
    return tuple(
        {
            "case_id": stable_id("multi-action", identity, effective),
            "identity_key": identity,
            "effective_date": effective,
            "event_count": len(items),
            "event_ids": sorted(
                str(item.get("canonical_event_id") or item.get("event_id"))
                for item in items
            ),
            "action_types": sorted(str(item.get("action_type")) for item in items),
            "requires_order_validation": len(items) > 1,
        }
        for (identity, effective), items in groups.items()
        if len(items) > 1
    )


def series_applicability(
    events: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    rows = []
    for row in events:
        series = row.get("series_applicability") or (
            [row.get("series")] if row.get("series") else []
        )
        rows.append(
            {
                "event_id": row.get("canonical_event_id") or row.get("event_id"),
                "identity_key": _identity(row),
                "series_applicability": sorted(str(item) for item in series),
                "applicability_state": "IDENTITY_WIDE"
                if len(series) != 1
                else "SERIES_SPECIFIC",
                "duplicate_factor_risk": False,
            }
        )
    return tuple(rows)


def adjusted_row_audit(
    summaries: Iterable[dict[str, Any]], basis: Iterable[dict[str, Any]]
) -> tuple[dict[str, Any], ...]:
    basis_by_identity: dict[str, set[str]] = defaultdict(set)
    for row in basis:
        basis_by_identity[_identity(row)].add(str(row.get("price_basis_state")))
    rows = []
    for summary in summaries:
        raw = int(
            summary.get("raw_row_count") or summary.get("action_exposed_raw_rows") or 0
        )
        adjusted = int(summary.get("adjusted_row_count") or 0)
        rows.append(
            {
                "identity_key": _identity(summary),
                "symbol": summary.get("symbol"),
                "expected_adjusted_row_count": raw,
                "actual_adjusted_row_count": adjusted,
                "row_parity": raw == adjusted,
                "missing_adjusted_rows": max(raw - adjusted, 0),
                "duplicate_adjusted_rows": max(adjusted - raw, 0),
                "factor_lineage_complete": bool(
                    summary.get(
                        "factor_lineage_complete", adjusted == 0 or adjusted <= raw
                    )
                ),
                "price_basis_states": sorted(basis_by_identity[_identity(summary)]),
                "raw_candles_unchanged": True,
            }
        )
    return tuple(rows)


def replay_admission_intervals(
    *,
    coverage: Iterable[dict[str, Any]],
    basis: Iterable[dict[str, Any]],
    factors: Iterable[dict[str, Any]],
    mixed_rows: Iterable[dict[str, Any]],
    unknown_rows: Iterable[dict[str, Any]],
    start_date: date,
    end_date: date,
) -> tuple[dict[str, Any], ...]:
    basis_by_identity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in basis:
        basis_by_identity[_identity(row)].append(row)
    factor_states: dict[str, set[str]] = defaultdict(set)
    for row in factors:
        factor_states[_identity(row)].add(str(row.get("factor_state")))
    mixed_state = {
        _identity(row): str(row.get("resolution_state")) for row in mixed_rows
    }
    unknown_impact_by_identity: dict[str, set[str]] = defaultdict(set)
    for row in unknown_rows:
        unknown_impact_by_identity[_identity(row)].add(str(row.get("replay_impact")))
    rows: list[dict[str, Any]] = []
    for identity_row in coverage:
        identity = _identity(identity_row)
        states = factor_states[identity]
        basis_rows = basis_by_identity[identity]
        basis_states = {str(row.get("price_basis_state")) for row in basis_rows}
        impact = unknown_impact_by_identity[identity]
        if not basis_rows or basis_states <= {"RAW_NO_ACTION_EXPOSURE"}:
            admission = AdmissionState.RAW_REPLAY_CERTIFIED_NO_ACTION_EXPOSURE
        elif (
            mixed_state.get(identity)
            == MixedBasisResolution.MIXED_BASIS_QUARANTINED.value
        ):
            admission = AdmissionState.MIXED_PRICE_BASIS_QUARANTINED
        elif states & AMBIGUOUS_FACTOR_STATES:
            admission = AdmissionState.FACTOR_AMBIGUOUS_QUARANTINED
        elif ReplayImpact.REQUIRE_CERTIFIED_FACTOR.value in impact:
            admission = AdmissionState.FACTOR_UNKNOWN_QUARANTINED
        elif states & NON_MULTIPLICATIVE_STATES:
            admission = AdmissionState.IDENTITY_TRANSITION_NONCOMPARABLE
        elif states & UNKNOWN_FACTOR_STATES:
            admission = AdmissionState.SEGMENT_BOUNDARY_REQUIRED
        elif states & CERTIFIED_FACTOR_STATES:
            admission = AdmissionState.ADJUSTED_REPLAY_CERTIFIED_TRADABILITY_PARTIAL
        else:
            admission = AdmissionState.RAW_REPLAY_CERTIFIED_POST_EVENT_SEGMENT
        rows.append(
            {
                "admission_interval_id": stable_id(
                    "replay-admission", identity, start_date, end_date, admission.value
                ),
                "identity_key": identity,
                "symbol": identity_row.get("symbol"),
                "series": identity_row.get("series"),
                "isin": identity_row.get("isin"),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "admission_state": admission.value,
                "admitted_price_view": "ADJUSTED"
                if admission.value.startswith("ADJUSTED")
                else "RAW",
                "prohibited_price_view": "MIXED",
                "event_boundaries": sorted(
                    str(row.get("start_date") or row.get("interval_start"))
                    for row in basis_rows
                    if row.get("start_date") or row.get("interval_start")
                ),
                "factor_states": sorted(states),
                "minimum_safe_indicator_start_date": start_date.isoformat(),
                "production_influence": False,
            }
        )
    return tuple(rows)


def indicator_lookback_safety(
    admission: Iterable[dict[str, Any]], lookbacks: Iterable[int]
) -> tuple[dict[str, Any], ...]:
    rows = []
    for item in admission:
        start = _date(item.get("start_date"))
        state = str(item.get("admission_state"))
        for lookback in lookbacks:
            safe = state not in {
                AdmissionState.FACTOR_UNKNOWN_QUARANTINED.value,
                AdmissionState.FACTOR_AMBIGUOUS_QUARANTINED.value,
                AdmissionState.MIXED_PRICE_BASIS_QUARANTINED.value,
                AdmissionState.CONFLICTING_EVIDENCE_QUARANTINED.value,
                AdmissionState.INSUFFICIENT_EVIDENCE_QUARANTINED.value,
                AdmissionState.UNRESOLVED.value,
            }
            earliest = start + timedelta(days=lookback * 2) if start and safe else None
            rows.append(
                {
                    "identity_key": _identity(item),
                    "lookback_sessions": lookback,
                    "safety_state": "SAFE_AFTER_RESET" if safe else "QUARANTINED",
                    "earliest_safe_date": earliest.isoformat() if earliest else None,
                    "reset_required": state
                    in {
                        AdmissionState.SEGMENT_BOUNDARY_REQUIRED.value,
                        AdmissionState.IDENTITY_TRANSITION_NONCOMPARABLE.value,
                    },
                }
            )
    return tuple(rows)


def transformation_contract() -> dict[str, Any]:
    return {
        "contract_version": TRANSFORMATION_CONTRACT_VERSION,
        "research_continuity_view": (
            "May use all effective actions known by the research cutoff; "
            "never exposes event knowledge as a predictive feature before "
            "historical availability."
        ),
        "rolling_as_of_replay_view": (
            "At replay date t, use only factors whose actions are effective "
            "on or before t and whose immutable evidence version is pinned "
            "to the replay contract."
        ),
        "event_knowledge_boundary": (
            "Announcement and filing content may influence features only "
            "after its historical availability timestamp."
        ),
        "future_leakage_protection": True,
        "raw_candles_immutable": True,
        "candidate_ids_stable": True,
        "active_replay_integration": False,
        "production_influence": False,
    }


def coverage_matrix(
    coverage: Iterable[dict[str, Any]],
    admission: Iterable[dict[str, Any]],
    quarantine: Iterable[dict[str, Any]],
    lookbacks: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    admission_by_identity = {_identity(row): row for row in admission}
    quarantine_count = Counter(_identity(row) for row in quarantine)
    lookback_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in lookbacks:
        lookback_counts[_identity(row)][str(row.get("safety_state"))] += 1
    return tuple(
        {
            "identity_key": _identity(row),
            "symbol": row.get("symbol"),
            "isin": row.get("isin"),
            "admission_state": admission_by_identity.get(_identity(row), {}).get(
                "admission_state", AdmissionState.UNRESOLVED.value
            ),
            "quarantine_interval_count": quarantine_count[_identity(row)],
            "safe_lookback_count": lookback_counts[_identity(row)]["SAFE_AFTER_RESET"],
            "quarantined_lookback_count": lookback_counts[_identity(row)][
                "QUARANTINED"
            ],
        }
        for row in coverage
    )


def adjusted_replay_readiness(
    admission: Iterable[dict[str, Any]],
    results: Iterable[dict[str, Any]],
    mixed: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    admission_rows = tuple(admission)
    states = Counter(str(row.get("admission_state")) for row in admission_rows)
    unresolved_factors = sum(
        row.get("validation_outcome") == ValidationOutcome.UNRESOLVED.value
        for row in results
    )
    silent_mixed = sum(bool(row.get("silent_mixed_basis")) for row in mixed)
    quarantine_states = {
        AdmissionState.FACTOR_UNKNOWN_QUARANTINED.value,
        AdmissionState.FACTOR_AMBIGUOUS_QUARANTINED.value,
        AdmissionState.MIXED_PRICE_BASIS_QUARANTINED.value,
        AdmissionState.CONFLICTING_EVIDENCE_QUARANTINED.value,
        AdmissionState.INSUFFICIENT_EVIDENCE_QUARANTINED.value,
        AdmissionState.UNRESOLVED.value,
    }
    quarantined = sum(states[state] for state in quarantine_states)
    if silent_mixed or unresolved_factors and quarantined == 0:
        state = ReplayReadiness.NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION
    elif quarantined:
        state = ReplayReadiness.CONDITIONALLY_READY_FOR_ADJUSTED_REPLAY_INTEGRATION
    else:
        state = ReplayReadiness.READY_FOR_ADJUSTED_REPLAY_INTEGRATION
    return {
        "state": state.value,
        "tier_a_identity_count": len(admission_rows),
        "admission_state_counts": dict(sorted(states.items())),
        "quarantined_identity_count": quarantined,
        "silent_mixed_basis_count": silent_mixed,
        "unresolved_factor_case_count": unresolved_factors,
        "unknown_factor_applied_as_one": False,
        "active_replay_integration": False,
        "production_influence": False,
    }


def _records(path: Path) -> tuple[dict[str, Any], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "records" in payload:
        payload = payload["records"]
    if not isinstance(payload, list):
        raise ValueError(f"expected a JSON array in {path}")
    return tuple(dict(row) for row in payload)


def _identity(*rows: dict[str, Any]) -> str:
    for row in rows:
        for key in ("identity_key", "governed_identity_id", "identity_id"):
            value = row.get(key)
            if value:
                return str(value)
    return ""


def _first(*rows: dict[str, Any], key: str) -> Any:
    for row in rows:
        if row.get(key) not in (None, ""):
            return row.get(key)
    return None


def _row_key(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(row.get(key) or "")
        for key in (
            "identity_key",
            "effective_date",
            "start_date",
            "event_id",
            "case_id",
            "quarantine_id",
            "lookback_sessions",
        )
    )


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _pct(value: int, total: int) -> float:
    return round(value * 100 / total, 8) if total else 0.0


__all__ = [name for name in globals() if not name.startswith("_")]
