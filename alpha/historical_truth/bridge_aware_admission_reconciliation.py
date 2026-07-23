"""HTR-010B1E bridge-aware validation and admission reconciliation."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from alpha.historical_truth.adjustment_replay_admission_continuity import (
    AMBIGUOUS_FACTOR_STATES,
    CERTIFIED_FACTOR_STATES,
    NON_MULTIPLICATIVE_STATES,
    UNKNOWN_FACTOR_STATES,
    tier_a_quarantine_economic_weight,
)
from alpha.historical_truth.adjustment_replay_admission_integrity_engine import (
    AdjustmentReplayAdmissionIntegrityEngine,
)
from alpha.historical_truth.adjustment_replay_admission_models import (
    AdjustmentReplayAdmissionReport,
    AdmissionState,
    ReplayReadiness,
    ValidationOutcome,
    stable_id,
)
from alpha.historical_truth.adjustment_replay_admission_repair import (
    HTR010BInputAdapter,
    candle_population,
    coverage_matrix_repaired,
    population_reconciliation,
    population_summary,
    quarantine_census_repaired,
    session_based_lookback_safety,
)

HTR010B1E_CONTRACT_VERSION = "HTR-010B1E-v1.0.0"

_CONFIRMED_OUTCOMES = {
    ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MARKET_GAP.value,
    ValidationOutcome.FACTOR_CONFIRMED_CORRECT_THIN_TRADING.value,
    ValidationOutcome.FACTOR_CONFIRMED_CORRECT_EVENT_DATE_OFFSET.value,
    ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MULTIPLE_ACTIONS.value,
}
_OLD_FACTOR_BLOCKERS = {
    "FACTOR_TRANSFORMATION_IMPLEMENTATION_DEFECTS",
    "POSSIBLE_EFFECTIVE_DATE_OFFSETS",
    "POSSIBLE_FACTOR_ORIENTATION_DEFECTS",
    "POSSIBLE_MULTIPLE_ACTION_CUMULATIVE_FACTORS",
    "UNEXPLAINED_FACTOR_TRANSFORMATION_DEFECTS",
}


class BridgeAwareAdmissionReconciliationEngine:
    """Apply B1D2 dispositions while preserving uncertified bridge quarantine."""

    def run(
        self,
        *,
        database_path: Path,
        htr010a3_output: Path,
        htr010b_output: Path,
        htr010b1d2_output: Path,
        session_calendar_report: Path,
        start_date: date,
        end_date: date,
    ) -> AdjustmentReplayAdmissionReport:
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        base = AdjustmentReplayAdmissionIntegrityEngine().run(
            database_path=database_path,
            htr010a3_output=htr010a3_output,
            htr010b_output=htr010b_output,
            session_calendar_report=session_calendar_report,
            start_date=start_date,
            end_date=end_date,
        )
        repair_rows = _records(htr010b1d2_output / "htr010b1d2_reclassified_cases.json")
        repaired_results, repair_summary = overlay_bridge_aware_results(
            base.factor_validation_results,
            repair_rows,
        )
        inputs = HTR010BInputAdapter().load(htr010b_output, htr010a3_output)
        population = candle_population(
            database_path,
            inputs["coverage"],
            start_date,
            end_date,
        )
        quarantine_inputs = tuple(
            {**row, "validation_outcome": _quarantine_reason(row)}
            for row in repaired_results
        )
        quarantine = quarantine_census_repaired(
            basis=inputs["basis"],
            results=quarantine_inputs,
            unknown_rows=base.unknown_factor_impact,
            mixed_rows=base.mixed_basis_resolution,
            start_date=start_date,
            end_date=end_date,
        )
        economic_rows, weight_summary = tier_a_quarantine_economic_weight(
            database_path=database_path,
            quarantine=quarantine,
            coverage=inputs["coverage"],
            population=population,
            start_date=start_date,
            end_date=end_date,
        )
        intervals = segmented_admission_with_bridge_reconciliation(
            coverage=inputs["coverage"],
            factors=inputs["factors"],
            validation_results=repaired_results,
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
            results=repaired_results,
        )
        economic_state = base.quarantine_population_reconciliation.get(
            "economic_weight_measurement_state",
            "MEASURED_OBSERVED_DATABASE_WINDOW",
        )
        economic_rows = tuple(
            {**row, "measurement_state": economic_state} for row in economic_rows
        )
        readiness = bridge_aware_readiness(
            base=base.replay_readiness,
            results=repaired_results,
            intervals=intervals,
            repair_summary=repair_summary,
        )
        coverage = coverage_matrix_repaired(
            inputs["coverage"],
            intervals,
            quarantine,
            lookbacks,
        )
        rejected = tuple(
            row
            for row in repaired_results
            if row.get("requires_quarantine")
            or row.get("validation_outcome")
            in {
                ValidationOutcome.FACTOR_CONFLICTING_OFFICIAL_EVIDENCE.value,
                ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE.value,
                ValidationOutcome.IMPLEMENTATION_DEFECT.value,
                ValidationOutcome.UNRESOLVED.value,
            }
        )
        diagnostics = {
            **base.input_contract_diagnostics,
            "bridge_aware_admission_reconciliation": repair_summary,
        }
        quarantine_reconciliation = {
            **reporting,
            **weight_summary,
            "economic_weight_measurement_state": economic_state,
            "bridge_aware_reconciliation_contract": HTR010B1E_CONTRACT_VERSION,
        }
        report = replace(
            base,
            contract_version=HTR010B1E_CONTRACT_VERSION,
            input_contract_diagnostics=diagnostics,
            population_reconciliation={
                **population_summary(population),
                **{
                    key: value
                    for key, value in base.population_reconciliation.items()
                    if key.startswith("governed_")
                    or key == "requested_window_fully_observed"
                },
            },
            quarantine_population_reconciliation=quarantine_reconciliation,
            quarantine_census=_sorted(quarantine),
            quarantine_economic_weight=_sorted(economic_rows),
            factor_validation_results=_sorted(repaired_results),
            replay_admission_intervals=_sorted(intervals),
            indicator_lookback_safety=_sorted(lookbacks),
            coverage_matrix=_sorted(coverage),
            replay_readiness=readiness,
            rejected_evidence=_sorted(rejected),
            transformation_contract={
                **base.transformation_contract,
                "bridge_aware_factor_dispositions_integrated": True,
                "factor_quality_separate_from_bridge_certification": True,
                "same_session_composite_validation_integrated": True,
                "unscoped_series_none_continuity_prohibited": True,
                "uncertified_bridges_remain_quarantined": True,
                "official_factor_mutation": False,
                "active_replay_integration": False,
            },
            report_sha256="",
        )
        return replace(report, report_sha256=report.calculated_sha256())


def overlay_bridge_aware_results(
    base_results: tuple[dict[str, Any], ...],
    repair_rows: tuple[dict[str, Any], ...],
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    """Overlay B1D2 dispositions using strict one-to-one event lineage."""

    repair_by_event: dict[str, dict[str, Any]] = {}
    for row in repair_rows:
        event_id = str(row.get("event_id") or "")
        if not event_id:
            raise ValueError("B1D2 repair row missing event_id")
        if event_id in repair_by_event:
            raise ValueError(f"duplicate B1D2 event_id: {event_id}")
        repair_by_event[event_id] = row
    base_ids = {str(row.get("event_id") or "") for row in base_results}
    missing = sorted(set(repair_by_event) - base_ids)
    if missing:
        raise ValueError(
            "B1D2 events missing from B1C validation results: " + ", ".join(missing)
        )

    corrected: list[dict[str, Any]] = []
    matched = 0
    for row in base_results:
        event_id = str(row.get("event_id") or "")
        repair = repair_by_event.get(event_id)
        if repair is None:
            corrected.append(row)
            continue
        matched += 1
        proposed = str(repair.get("proposed_validation_outcome") or "")
        try:
            ValidationOutcome(proposed)
        except ValueError as exc:
            raise ValueError(
                f"invalid proposed validation outcome: {proposed}"
            ) from exc
        factor_confirmed = bool(repair.get("factor_quality_confirmed"))
        bridge_certified = bool(repair.get("bridge_certified_for_replay"))
        admitted = (
            factor_confirmed and bridge_certified and proposed in _CONFIRMED_OUTCOMES
        )
        corrected.append(
            {
                **row,
                "pre_bridge_validation_outcome": row.get("validation_outcome"),
                "pre_bridge_requires_quarantine": row.get("requires_quarantine"),
                "validation_outcome": proposed,
                "admitted_to_replay": admitted,
                "requires_quarantine": not admitted,
                "implementation_defect_code": None,
                "recomputed_continuity_state": _continuity_state(
                    proposed,
                    factor_confirmed,
                    bridge_certified,
                ),
                "residual_attribution": _residual_attribution(
                    factor_confirmed,
                    bridge_certified,
                ),
                "corrected_disposition": repair.get("corrected_disposition"),
                "factor_quality_confirmed": factor_confirmed,
                "bridge_dependency_state": repair.get("bridge_dependency_state"),
                "bridge_certified_for_replay": bridge_certified,
                "diagnostic_composite_factor": repair.get(
                    "diagnostic_composite_factor"
                ),
                "diagnostic_composite_gap_atr": repair.get(
                    "diagnostic_composite_gap_atr"
                ),
                "htr010b1d2_contract_version": repair.get(
                    "htr010b1d2_contract_version"
                ),
                "classification_contract": HTR010B1E_CONTRACT_VERSION,
                "bridge_aware_reconciliation_applied": True,
                "market_derived_factor_autocorrection": False,
                "production_influence": False,
            }
        )
    if matched != len(repair_rows):
        raise ValueError("not every B1D2 repair row was applied exactly once")

    outcomes = Counter(str(row.get("validation_outcome")) for row in corrected)
    dependencies = Counter(
        str(row.get("bridge_dependency_state"))
        for row in corrected
        if row.get("bridge_dependency_state")
    )
    summary = {
        "contract_version": HTR010B1E_CONTRACT_VERSION,
        "corrected_case_count": matched,
        "corrected_validation_outcomes": dict(sorted(outcomes.items())),
        "corrected_bridge_dependencies": dict(sorted(dependencies.items())),
        "factor_quality_confirmed_count": sum(
            bool(row.get("factor_quality_confirmed")) for row in corrected
        ),
        "bridge_uncertified_count": sum(
            row.get("bridge_certified_for_replay") is False
            for row in corrected
            if row.get("bridge_aware_reconciliation_applied")
        ),
        "implementation_defect_count": outcomes[
            ValidationOutcome.IMPLEMENTATION_DEFECT.value
        ],
        "official_factor_mutated": False,
        "admission_policy_changed": True,
        "active_replay_integration": False,
        "production_influence": False,
    }
    return tuple(corrected), summary


def segmented_admission_with_bridge_reconciliation(
    *,
    coverage: tuple[dict[str, Any], ...],
    factors: tuple[dict[str, Any], ...],
    validation_results: tuple[dict[str, Any], ...],
    sessions: tuple[date, ...],
    start_date: date,
    end_date: date,
) -> tuple[dict[str, Any], ...]:
    """Segment intervals with explicit bridge-certification quarantine."""

    if not sessions:
        raise ValueError("no governed NSE sessions available for interval segmentation")
    validation_by_event = {str(row.get("event_id")): row for row in validation_results}
    factors_by_identity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in factors:
        effective = _as_date(row.get("effective_date"))
        if effective and start_date <= effective <= end_date:
            event_id = str(row.get("canonical_event_id") or "")
            validation = validation_by_event.get(event_id, {})
            enriched = {
                **row,
                "validation_outcome": validation.get("validation_outcome"),
                "bridge_dependency_state": validation.get("bridge_dependency_state"),
                "bridge_certified_for_replay": validation.get(
                    "bridge_certified_for_replay"
                ),
                "factor_quality_confirmed": validation.get("factor_quality_confirmed"),
            }
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
                _as_date(factor.get("effective_date")),
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
            state, admitted_view = _bridge_admission_state(
                identity_factors=identity_factors,
                future_factors=future_factors,
            )
            preceding_outcomes = {
                str(row.get("validation_outcome")) for row in preceding
            }
            preceding_bridges = {
                str(row.get("bridge_dependency_state"))
                for row in preceding
                if row.get("bridge_dependency_state")
            }
            future_outcomes = {
                str(row.get("validation_outcome")) for row in future_factors
            }
            future_bridges = {
                str(row.get("bridge_dependency_state"))
                for row in future_factors
                if row.get("bridge_dependency_state")
            }
            reset_required = bool(
                any(
                    row.get("bridge_certified_for_replay") is False for row in preceding
                )
                or preceding_outcomes
                & {
                    ValidationOutcome.IMPLEMENTATION_DEFECT.value,
                    ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE.value,
                }
                or {str(row.get("factor_state")) for row in preceding}
                & (
                    UNKNOWN_FACTOR_STATES
                    | AMBIGUOUS_FACTOR_STATES
                    | NON_MULTIPLICATIVE_STATES
                )
            )
            rows.append(
                {
                    "admission_interval_id": stable_id(
                        "replay-admission-b1e",
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
                    "preceding_boundary_validation_outcomes": sorted(
                        preceding_outcomes
                    ),
                    "preceding_boundary_bridge_dependencies": sorted(preceding_bridges),
                    "future_bridge_validation_outcomes": sorted(future_outcomes),
                    "future_bridge_dependencies": sorted(future_bridges),
                    "future_bridge_certified_for_replay": all(
                        row.get("bridge_certified_for_replay") is not False
                        for row in future_factors
                    ),
                    "reset_required": reset_required,
                    "session_calendar_source": "governed_session_calendar",
                    "production_influence": False,
                }
            )
    return tuple(rows)


def _bridge_admission_state(
    *,
    identity_factors: list[dict[str, Any]],
    future_factors: list[dict[str, Any]],
) -> tuple[AdmissionState, str]:
    if not identity_factors:
        return AdmissionState.RAW_REPLAY_CERTIFIED_NO_ACTION_EXPOSURE, "RAW"
    if not future_factors:
        return AdmissionState.RAW_REPLAY_CERTIFIED_POST_EVENT_SEGMENT, "RAW"
    outcomes = {str(row.get("validation_outcome")) for row in future_factors}
    states = {str(row.get("factor_state")) for row in future_factors}
    if any(row.get("bridge_certified_for_replay") is False for row in future_factors):
        return AdmissionState.BRIDGE_UNCERTIFIED_QUARANTINED, "NONE"
    if ValidationOutcome.IMPLEMENTATION_DEFECT.value in outcomes:
        return AdmissionState.CONFLICTING_EVIDENCE_QUARANTINED, "NONE"
    if ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE.value in outcomes:
        return AdmissionState.INSUFFICIENT_EVIDENCE_QUARANTINED, "NONE"
    if states & AMBIGUOUS_FACTOR_STATES:
        return AdmissionState.FACTOR_AMBIGUOUS_QUARANTINED, "NONE"
    if states & UNKNOWN_FACTOR_STATES:
        return AdmissionState.FACTOR_UNKNOWN_QUARANTINED, "NONE"
    if states & NON_MULTIPLICATIVE_STATES:
        return AdmissionState.IDENTITY_TRANSITION_NONCOMPARABLE, "RAW"
    if (
        states <= CERTIFIED_FACTOR_STATES
        and outcomes
        and outcomes <= _CONFIRMED_OUTCOMES
    ):
        return AdmissionState.ADJUSTED_REPLAY_CERTIFIED_TRADABILITY_PARTIAL, "ADJUSTED"
    return AdmissionState.UNRESOLVED, "NONE"


def bridge_aware_readiness(
    *,
    base: dict[str, Any],
    results: tuple[dict[str, Any], ...],
    intervals: tuple[dict[str, Any], ...],
    repair_summary: dict[str, Any],
) -> dict[str, Any]:
    blockers = {str(item) for item in base.get("blockers", [])} - _OLD_FACTOR_BLOCKERS
    dependencies = Counter(
        str(row.get("bridge_dependency_state"))
        for row in results
        if row.get("bridge_dependency_state")
    )
    outcomes = Counter(str(row.get("validation_outcome")) for row in results)
    if dependencies["UNCERTIFIED_CROSS_ISIN"]:
        blockers.add("UNCERTIFIED_CROSS_ISIN_BRIDGES")
    if dependencies["UNCERTIFIED_CROSS_SERIES"]:
        blockers.add("UNCERTIFIED_CROSS_SERIES_BRIDGES")
    if outcomes[ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE.value]:
        blockers.add("FACTOR_INSUFFICIENT_EVIDENCE_REMAINS")
    if outcomes[ValidationOutcome.IMPLEMENTATION_DEFECT.value]:
        blockers.add("FACTOR_TRANSFORMATION_IMPLEMENTATION_DEFECTS")
    admission_counts = Counter(str(row.get("admission_state")) for row in intervals)
    state = (
        ReplayReadiness.NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION.value
        if blockers
        else base.get("state")
    )
    return {
        **base,
        "state": state,
        "blockers": sorted(blockers),
        "validation_outcomes": dict(sorted(outcomes.items())),
        "admission_state_counts": dict(sorted(admission_counts.items())),
        "bridge_dependency_counts": dict(sorted(dependencies.items())),
        "bridge_aware_corrected_case_count": repair_summary.get(
            "corrected_case_count",
            0,
        ),
        "factor_quality_confirmed_count": repair_summary.get(
            "factor_quality_confirmed_count",
            0,
        ),
        "bridge_uncertified_count": repair_summary.get(
            "bridge_uncertified_count",
            0,
        ),
        "implementation_defect_count": outcomes[
            ValidationOutcome.IMPLEMENTATION_DEFECT.value
        ],
        "market_derived_factor_autocorrection": False,
        "active_replay_integration": False,
        "production_influence": False,
    }


def _quarantine_reason(row: dict[str, Any]) -> str:
    if not row.get("requires_quarantine"):
        return str(row.get("validation_outcome"))
    dependency = str(row.get("bridge_dependency_state") or "")
    if dependency == "UNCERTIFIED_CROSS_ISIN":
        return "UNCERTIFIED_CROSS_ISIN_BRIDGE"
    if dependency == "UNCERTIFIED_CROSS_SERIES":
        return "UNCERTIFIED_CROSS_SERIES_BRIDGE"
    if dependency == "NONCOMPARABLE_IDENTITY_TRANSITION":
        return "IDENTITY_TRANSITION_NONCOMPARABLE"
    return str(row.get("validation_outcome"))


def _continuity_state(
    outcome: str,
    factor_confirmed: bool,
    bridge_certified: bool,
) -> str:
    if factor_confirmed and bridge_certified:
        return "CONTINUITY_RESTORED_OR_IMPROVED"
    if factor_confirmed:
        return "FACTOR_CONFIRMED_BRIDGE_UNCERTIFIED"
    if outcome == ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE.value:
        return "INSUFFICIENT_CANDLE_CONTEXT"
    return "FACTOR_REQUIRES_GOVERNED_EVIDENCE"


def _residual_attribution(factor_confirmed: bool, bridge_certified: bool) -> str:
    if factor_confirmed and bridge_certified:
        return "BRIDGE_AWARE_FACTOR_CONFIRMED"
    if factor_confirmed:
        return "FACTOR_CONFIRMED_BRIDGE_UNCERTIFIED"
    return "BRIDGE_AWARE_INSUFFICIENT_EVIDENCE"


def _records(path: Path) -> tuple[dict[str, Any], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(
        isinstance(row, dict) for row in payload
    ):
        raise ValueError(f"expected JSON array of objects: {path}")
    return tuple(payload)


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _session_on_or_after(sessions: tuple[date, ...], value: date | None) -> date | None:
    if value is None:
        return None
    return next((session for session in sessions if session >= value), None)


def _previous_session(sessions: tuple[date, ...], value: date | None) -> date | None:
    if value is None:
        return None
    prior = [session for session in sessions if session < value]
    return prior[-1] if prior else None


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
                str(
                    row.get("admission_interval_id")
                    or row.get("case_id")
                    or row.get("quarantine_id")
                    or ""
                ),
            ),
        )
    )


__all__ = [
    "BridgeAwareAdmissionReconciliationEngine",
    "HTR010B1E_CONTRACT_VERSION",
    "bridge_aware_readiness",
    "overlay_bridge_aware_results",
    "segmented_admission_with_bridge_reconciliation",
]
