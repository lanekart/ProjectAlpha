"""CLI for HTR-010B1E2 final admission state propagation repair."""

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
from alpha.historical_truth.bridge_aware_admission_state_propagation import (
    BridgeAwareAdmissionStatePropagationEngine,
)
from alpha.historical_truth.bridge_aware_continuity_context import (
    BridgeAwareContinuityContextProvider,
)


def bridge_aware_admission_reconcile(
    database: Path = typer.Option(
        Path("alpha_data/warehouse/historical_truth.duckdb"),
        "--database",
        exists=True,
        dir_okay=False,
    ),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
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
    htr009a2_output: Path | None = typer.Option(
        None,
        "--htr009a2-output",
        exists=True,
        file_okay=False,
    ),
    dsi010b1_output: Path | None = typer.Option(
        None,
        "--dsi010b1-output",
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
        Path("artifacts/htr010b1e2_final_admission_state_propagation_2026"),
        "--output",
    ),
) -> None:
    """Repair final admission state propagation without enabling replay."""

    start_date = _date(start, "--start")
    end_date = _date(end, "--end")
    if end_date < start_date:
        raise typer.BadParameter("must be on or after --start", param_hint="--end")
    try:
        bridge_inputs = (htr009a2_output, dsi010b1_output)
        if any(item is not None for item in bridge_inputs) and not all(
            item is not None for item in bridge_inputs
        ):
            raise typer.BadParameter(
                "--htr009a2-output and --dsi010b1-output must be supplied together"
            )
        context_provider = (
            BridgeAwareContinuityContextProvider.from_signed_outputs(
                htr009a2_output=htr009a2_output,
                htr010a3_output=htr010a3_output,
                dsi010b1_output=dsi010b1_output,
                htr010b_output=htr010b_output,
                data_root=root,
                all_material_actions=True,
            )
            if htr009a2_output is not None and dsi010b1_output is not None
            else None
        )
        report = BridgeAwareAdmissionStatePropagationEngine().run(
            database_path=database,
            htr010a3_output=htr010a3_output,
            htr010b_output=htr010b_output,
            htr010b1d2_output=htr010b1d2_output,
            session_calendar_report=session_calendar_report,
            start_date=start_date,
            end_date=end_date,
            continuity_context_provider=context_provider,
        )
    except (InputContractError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    paths = AdjustmentReplayAdmissionArtifactExporter().export(report, output)
    diagnostics = report.input_contract_diagnostics.get(
        "bridge_aware_admission_reconciliation",
        {},
    )
    consistency = report.input_contract_diagnostics.get(
        "bridge_aware_admission_consistency",
        {},
    )
    residual = report.input_contract_diagnostics.get(
        "residual_factor_attribution",
        {},
    )
    reconciliation = report.quarantine_population_reconciliation
    readiness = report.replay_readiness

    print("HTR-010B1E2 Final Admission State Propagation Repair")
    print(f"Contract: {report.contract_version}")
    print(f"Factor validation cases: {len(report.factor_validation_results):,}")
    print(f"Corrected B1D2 cases: {diagnostics.get('corrected_case_count', 0):,}")
    print(
        "Factor-quality confirmed: "
        f"{diagnostics.get('factor_quality_confirmed_count', 0):,}"
    )
    print(
        "Bridge-uncertified corrected cases: "
        f"{readiness.get('bridge_uncertified_case_count', 0):,}"
    )
    print(
        "Implementation defects remaining: "
        f"{readiness.get('implementation_defect_count', 0):,}"
    )
    print(
        "Missing validation outcomes normalized: "
        f"{consistency.get('validation_missing_outcome_row_count', 0):,}"
    )
    print(
        "String missing outcomes normalized: "
        f"{consistency.get('validation_string_missing_outcome_row_count', 0):,}"
    )
    print(
        "Reference-price outcomes fail-closed: "
        f"{consistency.get('validation_reference_price_row_count', 0):,}"
    )
    print(
        "Final unresolved admission intervals: "
        f"{consistency.get('final_unresolved_interval_count', 0):,}"
    )
    print(
        "Consistency quarantine rows: "
        f"{consistency.get('post_consistency_quarantine_row_count', 0):,}"
    )
    print(f"Validation outcomes: {readiness.get('validation_outcomes', {})}")
    print(f"Admission states: {readiness.get('admission_state_counts', {})}")
    print(f"Corrected residual attribution: {residual.get('attribution_counts', {})}")
    print(
        "Admission-quarantined identities: "
        f"{readiness.get('admission_quarantined_identity_count', 0):,}"
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
