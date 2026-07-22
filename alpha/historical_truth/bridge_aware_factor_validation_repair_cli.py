"""CLI for HTR-010B1D2 bridge-aware validation repair."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.bridge_aware_factor_validation_repair import (
    BridgeAwareFactorValidationRepairEngine,
)


def bridge_aware_factor_validation_repair(
    htr010b1d1_output: Path = typer.Option(
        ...,
        "--htr010b1d1-output",
        exists=True,
        file_okay=False,
    ),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    output: Path = typer.Option(
        Path("artifacts/htr010b1d2_bridge_aware_validation_repair"),
        "--output",
    ),
) -> None:
    """Repair factor dispositions while preserving bridge quarantine."""

    start_date = _parse_date(start, "--start")
    end_date = _parse_date(end, "--end")
    if end_date < start_date:
        raise typer.BadParameter("must be on or after --start", param_hint="--end")
    engine = BridgeAwareFactorValidationRepairEngine()
    report = engine.run(
        htr010b1d1_output=htr010b1d1_output,
        start_date=start_date,
        end_date=end_date,
    )
    paths = engine.export(report, output)
    print("HTR-010B1D2 Bridge-Aware Factor Validation Repair")
    print(f"Cases audited: {report['case_count']}")
    print(f"Corrected dispositions: {report['disposition_counts']}")
    print(f"Proposed outcomes: {report['proposed_validation_outcome_counts']}")
    print(f"Same-session groups: {report['same_session_group_count']}")
    print(f"Composite groups confirmed: {report['composite_confirmed_group_count']}")
    print(f"Factor-quality confirmed: {report['factor_confirmed_case_count']}")
    print(f"Replay bridges uncertified: {report['replay_bridge_uncertified_case_count']}")
    print(
        "Implementation defects remaining: "
        f"{report['implementation_defect_should_remain_count']}"
    )
    print(f"Report SHA256: {report['report_sha256']}")
    print(f"Artifacts written: {len(paths)}")
    print("Full benchmark replays: 0")
    print("PRODUCTION_INFLUENCE=false")


def _parse_date(value: str, option_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            "must use ISO format YYYY-MM-DD",
            param_hint=option_name,
        ) from exc


__all__ = ["bridge_aware_factor_validation_repair"]
