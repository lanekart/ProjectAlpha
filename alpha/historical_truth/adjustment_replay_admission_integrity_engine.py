"""HTR-010B1C session coverage and residual-attribution wrapper."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from alpha.historical_truth.adjustment_replay_admission_continuity_engine import (
    AdjustmentReplayAdmissionContinuityEngine,
)
from alpha.historical_truth.adjustment_replay_admission_models import (
    AdjustmentReplayAdmissionReport,
    ReplayReadiness,
    ValidationOutcome,
)
from alpha.historical_truth.adjustment_replay_admission_residual_attribution import (
    attribute_residual_factor_cases,
)
from alpha.historical_truth.adjustment_replay_admission_session_coverage import (
    HTR010B1C_CONTRACT_VERSION,
    governed_session_coverage,
)


class AdjustmentReplayAdmissionIntegrityEngine:
    """Add governed session coverage and residual attribution to HTR-010B1B."""

    def run(
        self,
        *,
        database_path: Path,
        htr010a3_output: Path,
        htr010b_output: Path,
        session_calendar_report: Path,
        start_date: date,
        end_date: date,
    ) -> AdjustmentReplayAdmissionReport:
        base = AdjustmentReplayAdmissionContinuityEngine().run(
            database_path=database_path,
            htr010a3_output=htr010a3_output,
            htr010b_output=htr010b_output,
            start_date=start_date,
            end_date=end_date,
        )
        session_coverage = governed_session_coverage(
            calendar_report=session_calendar_report,
            database_path=database_path,
            start_date=start_date,
            end_date=end_date,
        )
        enriched_results, residual_summary = attribute_residual_factor_cases(
            database_path=database_path,
            results=base.factor_validation_results,
        )
        diagnostics = {
            **base.input_contract_diagnostics,
            "governed_session_coverage": session_coverage,
            "residual_factor_attribution": residual_summary,
        }
        coverage_complete = (
            session_coverage["state"] == "GOVERNED_SESSION_COVERAGE_COMPLETE"
        )
        economic_state = economic_weight_measurement_state(session_coverage)
        population = {
            **base.population_reconciliation,
            "requested_window_fully_observed": coverage_complete,
            "governed_session_coverage_state": session_coverage["state"],
            "governed_expected_session_count": session_coverage.get(
                "expected_session_count",
                0,
            ),
            "governed_observed_expected_session_count": session_coverage.get(
                "observed_expected_session_count",
                0,
            ),
            "governed_missing_expected_session_count": session_coverage.get(
                "missing_expected_session_count",
                0,
            ),
            "governed_session_coverage_ratio": session_coverage.get(
                "coverage_ratio",
                0.0,
            ),
        }
        quarantine_reconciliation = {
            **base.quarantine_population_reconciliation,
            "economic_weight_measurement_state": economic_state,
            "governed_session_coverage_state": session_coverage["state"],
        }
        economic_rows = tuple(
            {
                **row,
                "measurement_state": economic_state,
            }
            for row in base.quarantine_economic_weight
        )
        readiness = _readiness(
            base.replay_readiness,
            enriched_results,
            session_coverage,
            residual_summary,
        )
        rejected = tuple(
            row
            for row in enriched_results
            if row["validation_outcome"]
            in {
                ValidationOutcome.FACTOR_CONFLICTING_OFFICIAL_EVIDENCE.value,
                ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE.value,
                ValidationOutcome.IMPLEMENTATION_DEFECT.value,
                ValidationOutcome.UNRESOLVED.value,
            }
        )
        report = replace(
            base,
            contract_version=HTR010B1C_CONTRACT_VERSION,
            input_contract_diagnostics=diagnostics,
            population_reconciliation=population,
            quarantine_population_reconciliation=quarantine_reconciliation,
            quarantine_economic_weight=_sorted(economic_rows),
            factor_validation_results=_sorted(enriched_results),
            replay_readiness=readiness,
            rejected_evidence=_sorted(rejected),
            transformation_contract={
                **base.transformation_contract,
                "governed_session_completeness_required": True,
                "boundary_only_coverage_check_prohibited": True,
                "economic_weight_requires_governed_sessions": True,
                "observed_only_economic_weight_is_explicit": True,
                "residual_factor_cause_attribution": True,
                "market_derived_factor_autocorrection": False,
                "active_replay_integration": False,
            },
            report_sha256="",
        )
        return replace(report, report_sha256=report.calculated_sha256())


def economic_weight_measurement_state(
    session_coverage: dict[str, Any],
) -> str:
    if session_coverage.get("state") == "GOVERNED_SESSION_COVERAGE_COMPLETE":
        return "MEASURED_GOVERNED_COMPLETE_WINDOW"
    return "MEASURED_OBSERVED_DATABASE_WINDOW"


def _readiness(
    base: dict[str, Any],
    results: tuple[dict[str, Any], ...],
    session_coverage: dict[str, Any],
    residual_summary: dict[str, Any],
) -> dict[str, Any]:
    blockers = set(str(item) for item in base.get("blockers", []))
    blockers.discard("REQUESTED_HISTORICAL_WINDOW_NOT_FULLY_OBSERVED")
    blockers.update(str(item) for item in session_coverage.get("blockers", []))

    attribution = residual_summary.get("attribution_counts", {})
    if attribution.get("POSSIBLE_FACTOR_ORIENTATION_DEFECT", 0):
        blockers.add("POSSIBLE_FACTOR_ORIENTATION_DEFECTS")
    if attribution.get("POSSIBLE_EFFECTIVE_DATE_OFFSET", 0):
        blockers.add("POSSIBLE_EFFECTIVE_DATE_OFFSETS")
    if attribution.get("POSSIBLE_MULTIPLE_ACTION_CUMULATIVE_FACTOR", 0):
        blockers.add("POSSIBLE_MULTIPLE_ACTION_CUMULATIVE_FACTORS")
    if attribution.get("UNEXPLAINED_FACTOR_TRANSFORMATION_DEFECT", 0):
        blockers.add("UNEXPLAINED_FACTOR_TRANSFORMATION_DEFECTS")

    outcomes = Counter(str(row["validation_outcome"]) for row in results)
    state = (
        ReplayReadiness.NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION.value
        if blockers
        else base["state"]
    )
    return {
        **base,
        "state": state,
        "blockers": sorted(blockers),
        "validation_outcomes": dict(sorted(outcomes.items())),
        "governed_session_coverage_state": session_coverage["state"],
        "governed_missing_expected_session_count": session_coverage.get(
            "missing_expected_session_count",
            0,
        ),
        "observations_beyond_governed_calendar_window_count": (
            session_coverage.get(
                "observations_beyond_governed_calendar_window_count",
                0,
            )
        ),
        "residual_attribution_counts": dict(sorted(attribution.items())),
        "market_derived_factor_autocorrection": False,
        "active_replay_integration": False,
        "production_influence": False,
    }


def _sorted(rows: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                str(row.get("identity_key") or ""),
                str(row.get("effective_date") or row.get("start_date") or ""),
                str(row.get("event_id") or row.get("case_id") or ""),
            ),
        )
    )


__all__ = [
    "AdjustmentReplayAdmissionIntegrityEngine",
    "economic_weight_measurement_state",
]
