"""Final interval-weight integrity layer for HTR-010B1E."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from alpha.historical_truth.adjustment_replay_admission_continuity import (
    tier_a_quarantine_economic_weight,
)
from alpha.historical_truth.adjustment_replay_admission_repair import (
    HTR010BInputAdapter,
    candle_population,
    coverage_matrix_repaired,
    population_reconciliation,
)
from alpha.historical_truth.bridge_aware_admission_quarantine import (
    augment_quarantine_with_admission_intervals,
)
from alpha.historical_truth.bridge_aware_admission_reconciliation import (
    HTR010B1E_CONTRACT_VERSION,
    BridgeAwareAdmissionReconciliationEngine,
)


class BridgeAwareAdmissionReconciliationIntegrityEngine:
    """Measure full admission-quarantined intervals after B1E reconciliation."""

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
    ):
        base = BridgeAwareAdmissionReconciliationEngine().run(
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
        quarantine = augment_quarantine_with_admission_intervals(
            base.quarantine_census,
            base.replay_admission_intervals,
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
            intervals=base.replay_admission_intervals,
            results=base.factor_validation_results,
        )
        coverage = coverage_matrix_repaired(
            inputs["coverage"],
            base.replay_admission_intervals,
            quarantine,
            base.indicator_lookback_safety,
        )
        diagnostics = {
            **base.input_contract_diagnostics,
            "admission_interval_quarantine_augmentation": {
                "contract_version": HTR010B1E_CONTRACT_VERSION,
                "pre_augmentation_quarantine_row_count": len(base.quarantine_census),
                "post_augmentation_quarantine_row_count": len(quarantine),
                "admission_interval_rows_added": max(
                    0,
                    len(quarantine) - len(base.quarantine_census),
                ),
                "economic_weight_uses_full_blocked_intervals": True,
                "production_influence": False,
            },
        }
        reconciliation = {
            **base.quarantine_population_reconciliation,
            **reporting,
            **weight_summary,
            "economic_weight_measurement_state": economic_state,
            "economic_weight_uses_full_blocked_intervals": True,
        }
        report = replace(
            base,
            input_contract_diagnostics=diagnostics,
            quarantine_population_reconciliation=reconciliation,
            quarantine_census=_sorted(quarantine),
            quarantine_economic_weight=_sorted(economic_rows),
            coverage_matrix=_sorted(coverage),
            transformation_contract={
                **base.transformation_contract,
                "admission_interval_quarantine_in_economic_weight": True,
            },
            report_sha256="",
        )
        return replace(report, report_sha256=report.calculated_sha256())


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


__all__ = ["BridgeAwareAdmissionReconciliationIntegrityEngine"]
