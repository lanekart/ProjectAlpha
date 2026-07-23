"""HTR-010B1E1 report consistency and interval-state integrity repair."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from alpha.historical_truth.adjustment_replay_admission_continuity import (
    tier_a_quarantine_economic_weight,
)
from alpha.historical_truth.adjustment_replay_admission_models import (
    AdjustmentReplayAdmissionReport,
    AdmissionState,
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


class BridgeAwareAdmissionReportIntegrityEngine:
    """Synchronize B1E intervals, diagnostics, readiness, and population counts."""

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
        intervals, interval_summary = repair_unresolved_intervals(
            base.replay_admission_intervals
        )
        inputs = HTR010BInputAdapter().load(htr010b_output, htr010a3_output)
        population = candle_population(
            database_path,
            inputs["coverage"],
            start_date,
            end_date,
        )
        lookbacks = session_based_lookback_safety(
            intervals,
            population["sessions"],
            (14, 20, 50, 200),
        )
        quarantine = augment_quarantine_with_admission_intervals(
            _event_quarantine_only(base.quarantine_census),
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
        residual_summary = _final_residual_summary(base.factor_validation_results)
        readiness = _synchronized_readiness(
            base.replay_readiness,
            base.factor_validation_results,
            intervals,
            reporting,
            residual_summary,
            interval_summary,
        )
        diagnostics = {
            **base.input_contract_diagnostics,
            "residual_factor_attribution": residual_summary,
            "b1e1_interval_state_integrity": interval_summary,
        }
        reconciliation = {
            **base.quarantine_population_reconciliation,
            **reporting,
            **weight_summary,
            "economic_weight_measurement_state": economic_state,
            "economic_weight_uses_full_blocked_intervals": True,
            "report_population_counts_synchronized": True,
        }
        coverage = coverage_matrix_repaired(
            inputs["coverage"],
            intervals,
            quarantine,
            lookbacks,
        )
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
                "unresolved_interval_fallthrough_prohibited": True,
                "report_population_counts_synchronized": True,
                "residual_attribution_uses_final_validation_results": True,
                "readiness_bridge_uncertified_case_count_alias": True,
            },
            report_sha256="",
        )
        return replace(report, report_sha256=report.calculated_sha256())


def repair_unresolved_intervals(
    intervals: tuple[dict[str, Any], ...],
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    """Replace explainable UNRESOLVED fallthroughs with governed states."""

    repaired: list[dict[str, Any]] = []
    causes: Counter[str] = Counter()
    for row in intervals:
        if row.get("admission_state") != AdmissionState.UNRESOLVED.value:
            repaired.append(row)
            continue
        outcomes = set(str(item) for item in row.get("future_bridge_validation_outcomes", []))
        dependencies = set(str(item) for item in row.get("future_bridge_dependencies", []))
        state, view, cause = _state_from_future_evidence(outcomes, dependencies)
        causes[cause] += 1
        repaired.append(
            {
                **row,
                "admission_interval_id": stable_id(
                    "replay-admission-b1e1",
                    row.get("identity_key"),
                    row.get("start_date"),
                    row.get("end_date"),
                    state.value,
                ),
                "pre_b1e1_admission_state": AdmissionState.UNRESOLVED.value,
                "admission_state": state.value,
                "admitted_price_view": view,
                "b1e1_resolution_cause": cause,
                "reset_required": state
                in {
                    AdmissionState.BRIDGE_UNCERTIFIED_QUARANTINED,
                    AdmissionState.FACTOR_UNKNOWN_QUARANTINED,
                    AdmissionState.FACTOR_AMBIGUOUS_QUARANTINED,
                    AdmissionState.INSUFFICIENT_EVIDENCE_QUARANTINED,
                    AdmissionState.IDENTITY_TRANSITION_NONCOMPARABLE,
                    AdmissionState.UNRESOLVED,
                },
            }
        )
    remaining = sum(
        row.get("admission_state") == AdmissionState.UNRESOLVED.value for row in repaired
    )
    summary = {
        "contract_version": HTR010B1E1_CONTRACT_VERSION,
        "pre_repair_unresolved_interval_count": sum(causes.values()),
        "resolution_cause_counts": dict(sorted(causes.items())),
        "post_repair_unresolved_interval_count": remaining,
        "production_influence": False,
    }
    return tuple(repaired), summary


def _state_from_future_evidence(
    outcomes: set[str], dependencies: set[str]
) -> tuple[AdmissionState, str, str]:
    if dependencies & {"UNCERTIFIED_CROSS_ISIN", "UNCERTIFIED_CROSS_SERIES"}:
        return (
            AdmissionState.BRIDGE_UNCERTIFIED_QUARANTINED,
            "NONE",
            "UNCERTIFIED_BRIDGE_DEPENDENCY",
        )
    if ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE.value in outcomes:
        return (
            AdmissionState.INSUFFICIENT_EVIDENCE_QUARANTINED,
            "NONE",
            "FACTOR_INSUFFICIENT_EVIDENCE",
        )
    if ValidationOutcome.FACTOR_REQUIRES_REFERENCE_PRICE.value in outcomes:
        return (
            AdmissionState.FACTOR_UNKNOWN_QUARANTINED,
            "NONE",
            "FACTOR_REQUIRES_REFERENCE_PRICE",
        )
    if ValidationOutcome.FACTOR_CONFLICTING_OFFICIAL_EVIDENCE.value in outcomes:
        return (
            AdmissionState.FACTOR_AMBIGUOUS_QUARANTINED,
            "NONE",
            "FACTOR_CONFLICTING_OFFICIAL_EVIDENCE",
        )
    if ValidationOutcome.FACTOR_NON_MULTIPLICATIVE.value in outcomes:
        return (
            AdmissionState.IDENTITY_TRANSITION_NONCOMPARABLE,
            "RAW",
            "FACTOR_NON_MULTIPLICATIVE",
        )
    if outcomes and outcomes <= _CONFIRMED_OUTCOMES:
        return (
            AdmissionState.ADJUSTED_REPLAY_CERTIFIED_TRADABILITY_PARTIAL,
            "ADJUSTED",
            "CONFIRMED_FACTOR_OUTCOMES",
        )
    return AdmissionState.UNRESOLVED, "NONE", "UNCLASSIFIED_FUTURE_EVIDENCE"


def _event_quarantine_only(
    rows: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    return tuple(
        row
        for row in rows
        if str(row.get("source_type") or "") != "ADMISSION_INTERVAL"
    )


def _final_residual_summary(
    results: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    counts = Counter(str(row.get("residual_attribution") or "NOT_APPLICABLE") for row in results)
    return {
        "contract_version": HTR010B1E1_CONTRACT_VERSION,
        "case_count": len(results),
        "attribution_counts": dict(sorted(counts.items())),
        "source": "FINAL_BRIDGE_AWARE_VALIDATION_RESULTS",
        "stale_b1c_attribution_prohibited": True,
        "production_influence": False,
    }


def _synchronized_readiness(
    base: dict[str, Any],
    results: tuple[dict[str, Any], ...],
    intervals: tuple[dict[str, Any], ...],
    reporting: dict[str, Any],
    residual_summary: dict[str, Any],
    interval_summary: dict[str, Any],
) -> dict[str, Any]:
    outcomes = Counter(str(row.get("validation_outcome")) for row in results)
    admissions = Counter(str(row.get("admission_state")) for row in intervals)
    bridge_uncertified = sum(
        row.get("bridge_certified_for_replay") is False
        for row in results
        if row.get("bridge_aware_reconciliation_applied")
    )
    return {
        **base,
        "validation_outcomes": dict(sorted(outcomes.items())),
        "admission_state_counts": dict(sorted(admissions.items())),
        "residual_attribution_counts": residual_summary["attribution_counts"],
        "admission_quarantined_identity_count": reporting.get(
            "admission_quarantined_identity_count", 0
        ),
        "evidence_quarantined_identity_count": reporting.get(
            "evidence_quarantined_identity_count", 0
        ),
        "unresolved_case_identity_count": reporting.get(
            "unresolved_case_identity_count", 0
        ),
        "quarantined_identity_count": reporting.get(
            "admission_quarantined_identity_count", 0
        ),
        "bridge_uncertified_count": bridge_uncertified,
        "bridge_uncertified_case_count": bridge_uncertified,
        "post_repair_unresolved_interval_count": interval_summary[
            "post_repair_unresolved_interval_count"
        ],
        "report_population_counts_synchronized": True,
        "production_influence": False,
    }


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
    "BridgeAwareAdmissionReportIntegrityEngine",
    "HTR010B1E1_CONTRACT_VERSION",
    "repair_unresolved_intervals",
]
