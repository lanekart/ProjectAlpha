"""CLI for HTR-010B1E bridge-aware admission reconciliation."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.adjustment_replay_admission_exports import (
    AdjustmentReplayAdmissionArtifactExporter,
)
from alpha.historical_truth.adjustment_replay_admission_repair import (
    InputContractError,
)
from alpha.historical_truth.bridge_aware_admission_reconciliation_integrity import (
    BridgeAwareAdmissionReconciliationIntegrityEngine,
)


def bridge_aware_admission_reconcile(
    database: Path = typer.Option(
        Path("alpha_data/warehouse/historical_truth.duckdb"),
        "--database",
        exists=True,
        dir_okay=False,
    ),
    htr010a3_output: Path = typer.Option(
        Path("artifacts/htr010a3_tier_a_foundation_readiness"),
        "--htr010a3-output",
        exists=True,
        file_okay=False,
    ),
    htr010b_output: Path = typer.Option(
        Path("artifacts/htr010b_complete_corporate_action_dataset"),
        "--htr010b-output",
        exists=True,
        file_okay=False,
    ),
    htr010b1d2_output: Path = typer.Option(
        Path("artifacts/htr010b1d2_bridge_aware_validation_repair_2026"),
        "--htr010b1d2-output",
        exists=True,
        file_okay=False,
    ),
    session_calendar_report: Path = typer.Option(
        Path(
            "artifacts/htr007c_governed_calendar_extension_2026/"
            "htr007_session_calendar.json"
        ),
        "--session-calendar-report",
        exists=True,
        dir_okay=False,
    ),
    start: str = typer.Option("2026-01-01", "--start"),
    end: str = typer.Option("2026-07-20", "--end"),
    output: Path = typer.Option(
        Path("artifacts/htr010b1e_bridge_aware_admission_reconciliation_2026"),
        "--output",
    ),
) -> None:
    """Reconcile corrected factor outcomes with explicit bridge quarantine."""

    start_date = _date(start, "--start")
    end_date = _date(end, "--end")
    if end_date < start_date:
        raise typer.BadParameter("must be on or after --start", param_hint="--end")
    try:
        report = BridgeAwareAdmissionReconciliationIntegrityEngine().run(
            database_path=database,
            htr010a3_output=htr010a3_output,
            htr010b_output=htr010b_output,
            htr010b1d2_output=htr010b1d2_output,
            session_calendar_report=session_calendar_report,
            start_date=start_date,
            end_date=end_date,
        )
    except (InputContractError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    paths = AdjustmentReplayAdmissionArtifactExporter().export(report, output)
    diagnostics = report.input_contract_diagnostics.get(
        "bridge_aware_admission_reconciliation",
        {},
    )
    interval_diagnostics = report.input_contract_diagnostics.get(
        "admission_interval_quarantine_augmentation",
        {},
    )
    reconciliation = report.quarantine_population_reconciliation
    readiness = report.replay_readiness
    print("HTR-010B1E Bridge-Aware Admission Reconciliation")
    print(f"Factor validation cases: {len(report.factor_validation_results):,}")
    print(
        "Corrected B1D2 cases: "
        f"{diagnostics.get('corrected_case_count', 0):,}"
    )
    print(
        "Factor-quality confirmed: "
        f"{diagnostics.get('factor_quality_confirmed_count', 0):,}"
    )
    print(
        "Bridge-uncertified corrected cases: "
        f"{diagnostics.get('bridge_uncertified_count', 0):,}"
    )
    print(
        "Implementation defects remaining: "
        f"{diagnostics.get('implementation_defect_count', 0):,}"
    )
    print(
        "Admission interval quarantine rows added: "
        f"{interval_diagnostics.get('admission_interval_rows_added', 0):,}"
    )
    print(f"Validation outcomes: {readiness.get('validation_outcomes', {})}")
    print(f"Admission states: {readiness.get('admission_state_counts', {})}")
    print(
        "Admission-quarantined identities: "
        f"{reconciliation.get('admission_quarantined_identity_count', 0):,}"
    )
    print(
        "Observed Tier A row weight quarantined: "
        f"{reconciliation.get('pct_observed_tier_a_rows_quarantined')}"
    )
    print(f"Replay readiness: {readiness['state']}")
    print(f"Readiness blockers: {readiness.get('blockers', [])}")
    print(f"Report SHA256: {report.report_sha256}")
    print(f"Artifacts written: {len(paths)}")
    print("Full benchmark replays: 0")
    print("PRODUCTION_INFLUENCE=false")


def _date(value: str, option: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("must use YYYY-MM-DD", param_hint=option) from exc


__all__ = ["bridge_aware_admission_reconcile"]
