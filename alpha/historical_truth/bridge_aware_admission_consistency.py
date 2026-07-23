"""HTR-010B1E1 interval and reporting consistency repair."""

from __future__ import annotations

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
    session_based_lookback_safety,
)
from alpha.historical_truth.bridge_aware_admission_quarantine import (
    augment_quarantine_with_admission_intervals,
)
from alpha.historical_truth.bridge_aware_admission_reconciliation_integrity import (
    BridgeAwareAdmissionReconciliationIntegrityEngine,
)

HTR010B1E1_CONTRACT_VERSION = "HTR-010B1E1-v1.0.0"

_CONFIRMED_OUTCOMES = {
    ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MARKET_GAP.value,
    ValidationOutcome.FACTOR_CONFIRMED_CORRECT_THIN_TRADING.value,
    ValidationOutcome.FACTOR_CONFIRMED_CORRECT_EVENT_DATE_OFFSET.value,
    ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MULTIPLE_ACTIONS.value,
}


class BridgeAwareAdmissionConsistencyEngine:
    """Repair B1E interval, readiness, and diagnostic consistency."""

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
        base = BridgeAwareAdmissionReconciliationIntegrityEngine().run(
            database_path=database_path,
            htr010a3_output=htr010a3_output,
            htr010b_output=htr010b_output,
            htr010b1d2_output=htr010b1d2_output,
            session_calendar_report=session_calendar_report,
            start_date=start_date,
            end_date=end_date,
        )
        inputs = HTR010BInputAdapter().load(htr010b_output, htr010a3_output)
        population = candle_population(
            database_path,
            inputs["coverage"],
            start_date,
            end_date,
        )
        intervals, interval_summary = consistent_admission_intervals(
            coverage=inputs["coverage"],
            factors=inputs["factors"],
            validation_results=base.factor_validation_results,
            sessions=population["sessions"],
            start_date=start_date,
            end_date=end_date,
        )
        lookbacks = session_based_lookback_safety(
            intervals,
            population["sessions"],
            (14, 20, 50, 200),
        )
        evidence_only = tuple(
            row
            for row in base.quarantine_census
            if row.get("source") != "REPLAY_ADMISSION_INTERVAL"
        )
        quarantine = augment_quarantine_with_admission_intervals(
            evidence_only,
            intervals,
        )
        economic_rows, weight_summary = tier_a_quarantine_economic_weight(
            database_path=database_path,
            quarantine=quarantine,
            coverage=inputs["coverage"],
            population=population,
            start_date=start_date,
            end_date=end_date,
        )
        economic_state = base.quarantine_population_reconciliation.get(
            "economic_weight_measurement_state",
            "MEASURED_OBSERVED_DATABASE_WINDOW",
        )
        economic_rows = tuple(
            {**row, "measurement_state": economic_state} for row in economic_rows
        )
        reporting = population_reconciliation(
            quarantine=quarantine,
            intervals=intervals,
            results=base.factor_validation_results,
        )
        coverage = coverage_matrix_repaired(
            inputs["coverage"],
            intervals,
            quarantine,
            lookbacks,
        )
        residual_summary = corrected_residual_attribution(
            base.factor_validation_results,
        )
        readiness = consistent_readiness(
            base=base.replay_readiness,
            intervals=intervals,
            reporting=reporting,
            residual_summary=residual_summary,
        )
        old_residual = base.input_contract_diagnostics.get(
            "residual_factor_attribution",
            {},
        )
        diagnostics = {
            **base.input_contract_diagnostics,
            "pre_bridge_residual_factor_attribution": old_residual,
            "residual_factor_attribution": residual_summary,
            "bridge_aware_admission_consistency": {
                **interval_summary,
                "pre_consistency_quarantine_row_count": len(base.quarantine_census),
                "post_consistency_quarantine_row_count": len(quarantine),
                "readiness_counts_refreshed_after_quarantine_augmentation": True,
                "stale_residual_attribution_superseded": True,
                "production_influence": False,
            },
        }
        reconciliation = {
            **base.quarantine_population_reconciliation,
            **reporting,
            **weight_summary,
            "economic_weight_measurement_state": economic_state,
            "economic_weight_uses_full_blocked_intervals": True,
            "consistency_contract_version": HTR010B1E1_CONTRACT_VERSION,
        }
        report = replace(
            base,
            contract_version=HTR010B1E1_CONTRACT_VERSION,
            input_contract_diagnostics=diagnostics,
            quarantine_population_reconciliation=reconciliation,
            quarantine_census=_sorted(quarantine),
            quarantine_economic_weight=_sorted(economic_rows),
            replay_admission_intervals=_sorted(intervals),
            indicator_lookback_safety=_sorted(lookbacks),
            coverage_matrix=_sorted(coverage),
            replay_readiness=readiness,
            transformation_contract={
                **base.transformation_contract,
                "certified_unvalidated_factor_fallback_explicit": True,
                "unvalidated_factor_none_string_prohibited": True,
                "readiness_counts_refreshed_after_quarantine_augmentation": True,
                "stale_residual_attribution_superseded": True,
                "active_replay_integration": False,
            },
            report_sha256="",
        )
        return replace(report, report_sha256=report.calculated_sha256())


def consistent_admission_intervals(
    *,
    coverage: tuple[dict[str, Any], ...],
    factors: tuple[dict[str, Any], ...],
    validation_results: tuple[dict[str, Any], ...],
    sessions: tuple[date, ...],
    start_date: date,
    end_date: date,
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    """Segment B1E intervals without treating missing outcomes as string values."""

    if not sessions:
        raise ValueError("no governed NSE sessions available for interval segmentation")
    validation_by_event = {str(row.get("event_id")): row for row in validation_results}
    factors_by_identity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    certified_unvalidated = 0
    noncertified_unvalidated = 0
    for row in factors:
        effective = _as_date(row.get("effective_date"))
        if effective is None or not start_date <= effective <= end_date:
            continue
        event_id = str(row.get("canonical_event_id") or "")
        validation = validation_by_event.get(event_id)
        state = str(row.get("factor_state") or "")
        if validation is None:
            if state in CERTIFIED_FACTOR_STATES:
                certified_unvalidated += 1
            else:
                noncertified_unvalidated += 1
        enriched = {
            **row,
            "validation_present": validation is not None,
            "validation_outcome": (
                validation.get("validation_outcome") if validation is not None else None
            ),
            "bridge_dependency_state": (
                validation.get("bridge_dependency_state")
                if validation is not None
                else None
            ),
            "bridge_certified_for_replay": (
                validation.get("bridge_certified_for_replay")
                if validation is not None
                else None
            ),
            "factor_quality_confirmed": (
                validation.get("factor_quality_confirmed")
                if validation is not None
                else None
            ),
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
            state, admitted_view = _consistent_admission_state(
                identity_factors=identity_factors,
                future_factors=future_factors,
            )
            preceding_outcomes = _outcomes(preceding)
            future_outcomes = _outcomes(future_factors)
            preceding_bridges = _dependencies(preceding)
            future_bridges = _dependencies(future_factors)
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
                        "replay-admission-b1e1",
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
                    "future_unvalidated_certified_factor_count": sum(
                        not bool(row.get("validation_present"))
                        and str(row.get("factor_state")) in CERTIFIED_FACTOR_STATES
                        for row in future_factors
                    ),
                    "future_bridge_certified_for_replay": all(
                        row.get("bridge_certified_for_replay") is not False
                        for row in future_factors
                    ),
                    "reset_required": reset_required,
                    "session_calendar_source": "governed_session_calendar",
                    "production_influence": False,
                }
            )
    counts = Counter(str(row["admission_state"]) for row in rows)
    return tuple(rows), {
        "contract_version": HTR010B1E1_CONTRACT_VERSION,
        "certified_unvalidated_factor_count": certified_unvalidated,
        "noncertified_unvalidated_factor_count": noncertified_unvalidated,
        "admission_state_counts": dict(sorted(counts.items())),
        "unresolved_interval_count": counts[AdmissionState.UNRESOLVED.value],
    }


def _consistent_admission_state(
    *,
    identity_factors: list[dict[str, Any]],
    future_factors: list[dict[str, Any]],
) -> tuple[AdmissionState, str]:
    if not identity_factors:
        return AdmissionState.RAW_REPLAY_CERTIFIED_NO_ACTION_EXPOSURE, "RAW"
    if not future_factors:
        return AdmissionState.RAW_REPLAY_CERTIFIED_POST_EVENT_SEGMENT, "RAW"
    outcomes = _outcomes(future_factors)
    states = {str(row.get("factor_state") or "") for row in future_factors}
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
    if states <= CERTIFIED_FACTOR_STATES and (
        not outcomes or outcomes <= _CONFIRMED_OUTCOMES
    ):
        return AdmissionState.ADJUSTED_REPLAY_CERTIFIED_TRADABILITY_PARTIAL, "ADJUSTED"
    return AdmissionState.UNRESOLVED, "NONE"


def corrected_residual_attribution(
    results: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    counts = Counter(
        str(row.get("residual_attribution") or "NOT_REPORTED") for row in results
    )
    corrected = sum(
        bool(row.get("bridge_aware_reconciliation_applied")) for row in results
    )
    return {
        "contract_version": HTR010B1E1_CONTRACT_VERSION,
        "attribution_counts": dict(sorted(counts.items())),
        "bridge_aware_corrected_case_count": corrected,
        "legacy_b1c_attribution_is_pre_reconciliation_only": True,
        "market_derived_factor_autocorrection": False,
        "production_influence": False,
    }


def consistent_readiness(
    *,
    base: dict[str, Any],
    intervals: tuple[dict[str, Any], ...],
    reporting: dict[str, Any],
    residual_summary: dict[str, Any],
) -> dict[str, Any]:
    blockers = {str(item) for item in base.get("blockers", [])}
    counts = Counter(str(row.get("admission_state")) for row in intervals)
    if counts[AdmissionState.UNRESOLVED.value]:
        blockers.add("UNRESOLVED_ADMISSION_INTERVALS")
    else:
        blockers.discard("UNRESOLVED_ADMISSION_INTERVALS")
    state = (
        ReplayReadiness.NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION.value
        if blockers
        else base.get("state")
    )
    bridge_count = int(base.get("bridge_uncertified_count", 0) or 0)
    admission_count = int(reporting.get("admission_quarantined_identity_count", 0))
    evidence_count = int(reporting.get("evidence_quarantined_identity_count", 0))
    unresolved_count = int(reporting.get("unresolved_case_identity_count", 0))
    return {
        **base,
        "state": state,
        "blockers": sorted(blockers),
        "admission_state_counts": dict(sorted(counts.items())),
        "admission_quarantined_identity_count": admission_count,
        "evidence_quarantined_identity_count": evidence_count,
        "unresolved_case_identity_count": unresolved_count,
        "quarantined_identity_count": admission_count,
        "unresolved_factor_case_count": unresolved_count,
        "bridge_uncertified_case_count": bridge_count,
        "bridge_uncertified_count": bridge_count,
        "residual_attribution_counts": residual_summary["attribution_counts"],
        "consistency_contract_version": HTR010B1E1_CONTRACT_VERSION,
        "production_influence": False,
    }


def _outcomes(rows: list[dict[str, Any]]) -> set[str]:
    return {
        str(row["validation_outcome"])
        for row in rows
        if row.get("validation_outcome") not in {None, ""}
    }


def _dependencies(rows: list[dict[str, Any]]) -> set[str]:
    return {
        str(row["bridge_dependency_state"])
        for row in rows
        if row.get("bridge_dependency_state") not in {None, ""}
    }


def _session_on_or_after(sessions: tuple[date, ...], value: date | None) -> date | None:
    if value is None:
        return None
    return next((session for session in sessions if session >= value), None)


def _previous_session(sessions: tuple[date, ...], value: date | None) -> date | None:
    if value is None:
        return None
    prior = [session for session in sessions if session < value]
    return prior[-1] if prior else None


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
                str(row.get("identity_key") or ""),
                str(
                    row.get("interval_start")
                    or row.get("start_date")
                    or row.get("effective_date")
                    or ""
                ),
                str(
                    row.get("quarantine_id")
                    or row.get("admission_interval_id")
                    or row.get("case_id")
                    or ""
                ),
            ),
        )
    )


__all__ = [
    "BridgeAwareAdmissionConsistencyEngine",
    "HTR010B1E1_CONTRACT_VERSION",
    "consistent_admission_intervals",
    "consistent_readiness",
    "corrected_residual_attribution",
]
