"""HTR-010B1B continuity recomputation and closed-universe admission engine."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from alpha.historical_truth.adjustment_replay_admission_continuity import (
    HTR010B1B_CONTRACT_VERSION,
    recompute_factor_validation,
    tier_a_quarantine_economic_weight,
)
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
    ValidationOutcome,
    stable_id,
)
from alpha.historical_truth.adjustment_replay_admission_repair import (
    AMBIGUOUS_FACTOR_STATES,
    CERTIFIED_FACTOR_STATES,
    NON_MULTIPLICATIVE_STATES,
    UNKNOWN_FACTOR_STATES,
    HTR010BInputAdapter,
    adjusted_row_audit_repaired,
    candle_population,
    coverage_matrix_repaired,
    event_boundaries_repaired,
    population_reconciliation,
    population_summary,
    quarantine_census_repaired,
    replay_readiness_repaired,
    session_based_lookback_safety,
)


class AdjustmentReplayAdmissionContinuityEngine:
    """Build HTR-010B1B from canonical factors and canonical candles."""

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
        cases, results, continuity_summary = recompute_factor_validation(
            database_path=database_path,
            events=inputs["events"],
            factors=inputs["factors"],
            legacy_continuity=inputs["continuity"],
            start_date=start_date,
            end_date=end_date,
        )
        inputs["diagnostics"]["continuity_recomputation"] = continuity_summary
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
        economic_weight, weight_summary = tier_a_quarantine_economic_weight(
            database_path=database_path,
            quarantine=quarantine,
            coverage=inputs["coverage"],
            population=population,
            start_date=start_date,
            end_date=end_date,
        )
        intervals = segmented_admission_with_validation(
            coverage=inputs["coverage"],
            factors=inputs["factors"],
            validation_results=results,
            sessions=population["sessions"],
            start_date=start_date,
            end_date=end_date,
        )
        lookbacks = session_based_lookback_safety(
            intervals,
            population["sessions"],
            (14, 20, 50, 200),
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
            "continuity_source": ("HTR010B_FACTOR_RECOMPUTED_FROM_CANONICAL_CANDLES"),
            "legacy_continuity_is_comparison_only": True,
            "market_derived_factor_autocorrection": False,
            "tier_a_weight_universe_closed": True,
            "quarantine_ranges_clipped_to_requested_window": True,
            "active_replay_integration": False,
        }
        coverage = coverage_matrix_repaired(
            inputs["coverage"],
            intervals,
            quarantine,
            lookbacks,
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
            contract_version=HTR010B1B_CONTRACT_VERSION,
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
            quarantine_census=_sorted(quarantine),
            quarantine_economic_weight=_sorted(economic_weight),
            factor_validation_cases=_sorted(cases),
            factor_validation_results=_sorted(results),
            event_boundaries=_sorted(
                event_boundaries_repaired(inputs["events"], population["sessions"])
            ),
            multiple_action_cases=_sorted(multiple_action_cases(inputs["events"])),
            series_applicability=_sorted(series_applicability(inputs["events"])),
            unknown_factor_impact=_sorted(unknown),
            mixed_basis_resolution=_sorted(mixed),
            adjusted_row_audit=_sorted(
                adjusted_row_audit_repaired(inputs["summaries"], population)
            ),
            replay_admission_intervals=_sorted(intervals),
            indicator_lookback_safety=_sorted(lookbacks),
            transformation_contract=transform,
            coverage_matrix=_sorted(coverage),
            replay_readiness=readiness,
            rejected_evidence=_sorted(rejected),
            report_sha256="",
        )
        return replace(report, report_sha256=report.calculated_sha256())


def segmented_admission_with_validation(
    *,
    coverage: tuple[dict[str, Any], ...],
    factors: tuple[dict[str, Any], ...],
    validation_results: tuple[dict[str, Any], ...],
    sessions: tuple[date, ...],
    start_date: date,
    end_date: date,
) -> tuple[dict[str, Any], ...]:
    """Segment replay and quarantine bridges using recomputed outcomes."""

    if not sessions:
        raise ValueError("no governed NSE sessions available for interval segmentation")
    validation_by_event = {str(row.get("event_id")): row for row in validation_results}
    factors_by_identity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in factors:
        effective = _as_date(row.get("effective_date"))
        if effective and start_date <= effective <= end_date:
            enriched = dict(row)
            enriched["validation_outcome"] = validation_by_event.get(
                str(row.get("canonical_event_id")), {}
            ).get("validation_outcome")
            factors_by_identity[str(row["identity_key"])].append(enriched)

    rows: list[dict[str, Any]] = []
    for identity_row in coverage:
        identity = str(identity_row["identity_key"])
        identity_factors = sorted(
            factors_by_identity.get(identity, []),
            key=lambda row: (str(row["effective_date"]), str(row.get("factor_id"))),
        )
        grouped: dict[date, list[dict[str, Any]]] = defaultdict(list)
        for factor in identity_factors:
            boundary = _session_on_or_after(
                sessions,
                _as_date(factor["effective_date"]),
            )
            if boundary:
                grouped[boundary].append(factor)
        starts = sorted({sessions[0], *grouped})
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
            future_outcomes = {
                str(row.get("validation_outcome")) for row in future_factors
            }
            preceding_outcomes = {
                str(row.get("validation_outcome")) for row in preceding
            }
            state, admitted_view = _admission_state(
                identity_factors=identity_factors,
                future_factors=future_factors,
                future_states=future_states,
                future_outcomes=future_outcomes,
            )
            reset_required = bool(
                preceding_states
                & (
                    UNKNOWN_FACTOR_STATES
                    | AMBIGUOUS_FACTOR_STATES
                    | NON_MULTIPLICATIVE_STATES
                )
                or preceding_outcomes
                & {
                    ValidationOutcome.IMPLEMENTATION_DEFECT.value,
                    ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE.value,
                }
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
                    "preceding_boundary_validation_outcomes": sorted(
                        preceding_outcomes
                    ),
                    "future_bridge_validation_outcomes": sorted(future_outcomes),
                    "reset_required": reset_required,
                    "session_calendar_source": "daily_candle_distinct_trading_date",
                    "production_influence": False,
                }
            )
    return tuple(rows)


def _admission_state(
    *,
    identity_factors: list[dict[str, Any]],
    future_factors: list[dict[str, Any]],
    future_states: set[str],
    future_outcomes: set[str],
) -> tuple[AdmissionState, str]:
    if not identity_factors:
        return AdmissionState.RAW_REPLAY_CERTIFIED_NO_ACTION_EXPOSURE, "RAW"
    if not future_factors:
        return AdmissionState.RAW_REPLAY_CERTIFIED_POST_EVENT_SEGMENT, "RAW"
    if ValidationOutcome.IMPLEMENTATION_DEFECT.value in future_outcomes:
        return AdmissionState.CONFLICTING_EVIDENCE_QUARANTINED, "NONE"
    if ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE.value in future_outcomes:
        return AdmissionState.INSUFFICIENT_EVIDENCE_QUARANTINED, "NONE"
    if future_states & AMBIGUOUS_FACTOR_STATES:
        return AdmissionState.FACTOR_AMBIGUOUS_QUARANTINED, "NONE"
    if future_states & UNKNOWN_FACTOR_STATES:
        return AdmissionState.FACTOR_UNKNOWN_QUARANTINED, "NONE"
    if future_states & NON_MULTIPLICATIVE_STATES:
        return AdmissionState.IDENTITY_TRANSITION_NONCOMPARABLE, "RAW"
    if future_states <= CERTIFIED_FACTOR_STATES:
        return AdmissionState.ADJUSTED_REPLAY_CERTIFIED_TRADABILITY_PARTIAL, "ADJUSTED"
    return AdmissionState.UNRESOLVED, "NONE"


def _session_on_or_after(
    sessions: tuple[date, ...],
    value: date | None,
) -> date | None:
    if value is None:
        return None
    for session in sessions:
        if session >= value:
            return session
    return None


def _previous_session(
    sessions: tuple[date, ...],
    value: date | None,
) -> date | None:
    if value is None:
        return None
    previous = [session for session in sessions if session < value]
    return previous[-1] if previous else None


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _sorted(rows: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                str(row.get("identity_key") or row.get("governed_identity_id") or ""),
                str(
                    row.get("start_date")
                    or row.get("effective_date")
                    or row.get("event_id")
                    or ""
                ),
                str(row.get("admission_interval_id") or row.get("case_id") or ""),
            ),
        )
    )


__all__ = [
    "AdjustmentReplayAdmissionContinuityEngine",
    "segmented_admission_with_validation",
]
