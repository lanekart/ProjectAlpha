"""CLI for governed adjustment continuity and admission integrity."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.adjustment_replay_admission_exports import (
    AdjustmentReplayAdmissionArtifactExporter,
)
from alpha.historical_truth.adjustment_replay_admission_integrity_engine import (
    AdjustmentReplayAdmissionIntegrityEngine,
)
from alpha.historical_truth.adjustment_replay_admission_models import (
    AdjustmentReplayAdmissionReport,
)
from alpha.historical_truth.adjustment_replay_admission_repair import (
    InputContractError,
)
from alpha.historical_truth.bridge_aware_continuity_context import (
    BridgeAwareContinuityContextProvider,
)


def adjustment_replay_admission_certify(
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
    session_calendar_report: Path = typer.Option(
        Path(
            "artifacts/htr007_historical_session_evidence/htr007_session_calendar.json"
        ),
        "--session-calendar-report",
    ),
    start: str = typer.Option("2016-01-01", "--start"),
    end: str = typer.Option("2026-07-20", "--end"),
    output: Path = typer.Option(
        Path("artifacts/htr010b1_adjustment_replay_admission"),
        "--output",
    ),
    refresh_sources: bool = typer.Option(False, "--refresh-sources"),
    verify_only: bool = typer.Option(False, "--verify-only"),
    symbol: list[str] = typer.Option([], "--symbol"),
    isin: list[str] = typer.Option([], "--isin"),
    action_type: list[str] = typer.Option([], "--action-type"),
    validation_outcome: list[str] = typer.Option([], "--validation-outcome"),
    quarantine_reason: list[str] = typer.Option([], "--quarantine-reason"),
    admission_state: list[str] = typer.Option([], "--admission-state"),
    year: list[int] = typer.Option([], "--year"),
    only_suspected_factors: bool = typer.Option(False, "--only-suspected-factors"),
    only_mixed_basis: bool = typer.Option(False, "--only-mixed-basis"),
    only_unknown_factors: bool = typer.Option(False, "--only-unknown-factors"),
    only_quarantined: bool = typer.Option(False, "--only-quarantined"),
    only_tier_a: bool = typer.Option(False, "--only-tier-a"),
) -> None:
    """Audit governed sessions, continuity causes and replay admission."""

    del root, only_tier_a
    if refresh_sources:
        raise typer.BadParameter(
            "This audit consumes pinned governed artifacts and cannot refresh sources",
            param_hint="--refresh-sources",
        )
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
            )
            if htr009a2_output is not None and dsi010b1_output is not None
            else None
        )
        report = AdjustmentReplayAdmissionIntegrityEngine().run(
            database_path=database,
            htr010a3_output=htr010a3_output,
            htr010b_output=htr010b_output,
            session_calendar_report=session_calendar_report,
            start_date=start_date,
            end_date=end_date,
            continuity_context_provider=context_provider,
        )
    except InputContractError as exc:
        raise typer.BadParameter(str(exc), param_hint="--htr010b-output") from exc

    paths = AdjustmentReplayAdmissionArtifactExporter().export(report, output)
    selected = _selected_count(
        report,
        symbol=symbol,
        isin=isin,
        action_type=action_type,
        validation_outcome=validation_outcome,
        quarantine_reason=quarantine_reason,
        admission_state=admission_state,
        year=year,
        only_suspected_factors=only_suspected_factors,
        only_mixed_basis=only_mixed_basis,
        only_unknown_factors=only_unknown_factors,
        only_quarantined=only_quarantined,
    )
    reconciliation = report.quarantine_population_reconciliation
    diagnostics = report.input_contract_diagnostics
    continuity = diagnostics.get("continuity_recomputation", {})
    session_coverage = diagnostics.get("governed_session_coverage", {})
    residual = diagnostics.get("residual_factor_attribution", {})

    print(f"{report.contract_version} Session Coverage and Residual Attribution")
    print(f"Factor validation cases: {len(report.factor_validation_cases):,}")
    print(f"Quarantine evidence rows: {len(report.quarantine_census):,}")
    print(f"Segmented admission intervals: {len(report.replay_admission_intervals):,}")
    print(
        "Evidence-quarantined identities: "
        f"{reconciliation.get('evidence_quarantined_identity_count', 0):,}"
    )
    print(
        "Admission-quarantined identities: "
        f"{reconciliation.get('admission_quarantined_identity_count', 0):,}"
    )
    print(
        "Observed Tier A row weight quarantined: "
        f"{reconciliation.get('pct_observed_tier_a_rows_quarantined')}"
    )
    print(f"Governed session coverage: {session_coverage.get('state')}")
    print(
        "Missing expected sessions: "
        f"{session_coverage.get('missing_expected_session_count', 0):,}"
    )
    print(
        "Legacy/recomputed continuity disagreements: "
        f"{continuity.get('legacy_recomputed_state_disagreement_count', 0):,}"
    )
    print(f"Residual attribution: {residual.get('attribution_counts', {})}")
    print(f"Diagnostic records selected: {selected:,}")
    print(f"Replay readiness: {report.replay_readiness['state']}")
    print(f"Readiness blockers: {report.replay_readiness.get('blockers', [])}")
    print(f"Report SHA256: {report.report_sha256}")
    print(f"Artifacts written: {len(paths)}")
    print(f"Verify-only mode: {str(verify_only).lower()}")
    print("Full benchmark replays: 0")
    print("PRODUCTION_INFLUENCE=false")


def _selected_count(
    report: AdjustmentReplayAdmissionReport,
    *,
    symbol: list[str],
    isin: list[str],
    action_type: list[str],
    validation_outcome: list[str],
    quarantine_reason: list[str],
    admission_state: list[str],
    year: list[int],
    only_suspected_factors: bool,
    only_mixed_basis: bool,
    only_unknown_factors: bool,
    only_quarantined: bool,
) -> int:
    rows = list(report.factor_validation_results)
    symbols = {item.upper() for item in symbol}
    isins = {item.upper() for item in isin}
    action_types = set(action_type)
    outcomes = set(validation_outcome)
    years = set(year)
    if symbols:
        rows = [row for row in rows if str(row.get("symbol", "")).upper() in symbols]
    if isins:
        rows = [row for row in rows if str(row.get("isin", "")).upper() in isins]
    if action_types:
        rows = [row for row in rows if str(row.get("action_type")) in action_types]
    if outcomes:
        rows = [row for row in rows if str(row.get("validation_outcome")) in outcomes]
    if years:
        rows = [
            row
            for row in rows
            if row.get("effective_date")
            and int(str(row["effective_date"])[:4]) in years
        ]
    if only_suspected_factors:
        return len(rows)
    if only_mixed_basis:
        return len(report.mixed_basis_resolution)
    if only_unknown_factors:
        return len(report.unknown_factor_impact)
    if only_quarantined or quarantine_reason:
        wanted = set(quarantine_reason)
        return sum(
            not wanted or str(row.get("quarantine_reason")) in wanted
            for row in report.quarantine_census
        )
    if admission_state:
        wanted = set(admission_state)
        return sum(
            str(row.get("admission_state")) in wanted
            for row in report.replay_admission_intervals
        )
    return len(rows)


def _date(value: str, option: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("must use YYYY-MM-DD", param_hint=option) from exc


__all__ = ["adjustment_replay_admission_certify"]
