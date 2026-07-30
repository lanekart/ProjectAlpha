"""CLI for DSI-010B6 pre-2016 identity reconstruction."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.pre2016_identity_reconstruction import (
    Pre2016IdentityReconstructionEngine,
    Pre2016IdentityReconstructionExporter,
)


def complete_pre2016_identity_reconstruction_certify(
    database: Path = typer.Option(..., "--database", exists=True, dir_okay=False),
    root: Path = typer.Option(Path("alpha_data"), "--root"),
    htr009a2_output: Path = typer.Option(
        ..., "--htr009a2-output", exists=True, file_okay=False
    ),
    htr010a3_output: Path = typer.Option(
        ..., "--htr010a3-output", exists=True, file_okay=False
    ),
    htr010b_output: Path = typer.Option(
        ..., "--htr010b-output", exists=True, file_okay=False
    ),
    final_b1c_output: Path = typer.Option(
        ..., "--final-b1c-output", exists=True, file_okay=False
    ),
    final_b1e2_output: Path = typer.Option(
        ..., "--final-b1e2-output", exists=True, file_okay=False
    ),
    signed_b5_output: Path = typer.Option(
        ..., "--signed-b5-output", exists=True, file_okay=False
    ),
    start: str = typer.Option("2005-01-01", "--start"),
    end: str = typer.Option("2015-12-31", "--end"),
    output: Path = typer.Option(
        Path("artifacts/dsi010b6_pre2016_identity_reconstruction"),
        "--output",
    ),
    verify_only: bool = typer.Option(False, "--verify-only"),
    refresh_sources: bool = typer.Option(False, "--refresh-sources"),
) -> None:
    """Reconstruct governed identities and certify adjusted-replay readiness."""

    if verify_only and refresh_sources:
        raise typer.BadParameter(
            "cannot combine --verify-only and --refresh-sources",
            param_hint="--verify-only/--refresh-sources",
        )
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError as exc:
        raise typer.BadParameter(
            "dates must use YYYY-MM-DD",
            param_hint="--start/--end",
        ) from exc
    report = Pre2016IdentityReconstructionEngine().run(
        database_path=database,
        root=root,
        htr009a2_output=htr009a2_output,
        htr010a3_output=htr010a3_output,
        htr010b_output=htr010b_output,
        final_b1c_output=final_b1c_output,
        final_b1e2_output=final_b1e2_output,
        signed_b5_output=signed_b5_output,
        start_date=start_date,
        end_date=end_date,
        output=output,
        refresh_sources=refresh_sources,
    )
    paths = Pre2016IdentityReconstructionExporter().export(report, output)
    summary = report.summary
    census = summary["full_canonical_row_reconciliation"]
    print("DSI-010B6 Complete Pre-2016 Identity Reconstruction")
    print(f"Starting segments: {summary['starting_segment_count']}")
    print(f"Resolved segments: {summary['resolved_segment_count']}")
    print(f"Remaining segments: {summary['remaining_segment_count']}")
    print(
        "Newly certified action-exposed rows: "
        f"{summary['newly_certified_affected_row_count']:,}"
    )
    print(
        "Full canonical identity coverage: "
        f"{census['governed_identity_row_count']:,}/"
        f"{census['total_canonical_row_count']:,}"
    )
    print(
        f"Rows without governed identity: {census['unresolved_identity_row_count']:,}"
    )
    print(
        f"Adjusted rows: {summary['adjusted_rows_before']:,} -> "
        f"{summary['adjusted_rows_after']:,}"
    )
    print(
        f"Mixed identities: {summary['mixed_identities_before']} -> "
        f"{summary['mixed_identities_after']}"
    )
    print(f"Readiness: {summary['readiness']}")
    print(f"Report SHA256: {report.report_sha256}")
    print(f"Certificate SHA256: {report.certificate_sha256}")
    print(f"Artifacts written: {len(paths)}")
    print("FULL_BENCHMARK_REPLAYS=0")
    print("STOP_POLICY_AUTOMATIC_PROMOTION_ENABLED=false")
    print(
        "ADJUSTED_REPLAY_READY=" + str(bool(summary["adjusted_replay_ready"])).lower()
    )
    print("PRODUCTION_INFLUENCE=false")


__all__ = ["complete_pre2016_identity_reconstruction_certify"]
