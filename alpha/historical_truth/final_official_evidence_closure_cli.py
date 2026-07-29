"""CLI for DSI-010B5 final official-evidence closure."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.final_official_evidence_closure import (
    FinalOfficialEvidenceClosureEngine,
    FinalOfficialEvidenceClosureExporter,
)


def final_official_evidence_closure_certify(
    database: Path = typer.Option(..., "--database", exists=True, dir_okay=False),
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
    baseline_b4_output: Path = typer.Option(
        ..., "--baseline-b4-output", exists=True, file_okay=False
    ),
    start: str = typer.Option("2005-01-01", "--start"),
    end: str = typer.Option("2015-12-31", "--end"),
    output: Path = typer.Option(
        Path("artifacts/dsi010b5_final_official_evidence_closure"),
        "--output",
    ),
) -> None:
    """Certify material factors and fail closed on unresolved candle identity."""

    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError as exc:
        raise typer.BadParameter(
            "dates must use YYYY-MM-DD",
            param_hint="--start/--end",
        ) from exc
    report = FinalOfficialEvidenceClosureEngine().run(
        database_path=database,
        htr009a2_output=htr009a2_output,
        htr010a3_output=htr010a3_output,
        htr010b_output=htr010b_output,
        final_b1c_output=final_b1c_output,
        final_b1e2_output=final_b1e2_output,
        baseline_b4_output=baseline_b4_output,
        start_date=start_date,
        end_date=end_date,
        output=output,
    )
    paths = FinalOfficialEvidenceClosureExporter().export(report, output)
    summary = report.summary
    print("DSI-010B5 Final Official-Evidence Closure")
    print(f"Starting event blockers: {summary['starting_residual_case_count']}")
    print(f"Validation outcomes: {summary['validation_outcome_counts']}")
    print(
        "Governed adjustment rows: "
        f"{summary['adjusted_row_count_after']:,}/"
        f"{summary['required_adjustment_row_count']:,}"
    )
    print(
        "Uncertified pre-event identity rows: "
        f"{summary['unresolved_identity_adjustment_row_count']:,}"
    )
    print(
        "Mixed price-basis governed identities: "
        f"{summary['mixed_price_basis_intervals_before']} -> "
        f"{summary['mixed_price_basis_intervals_after']}"
    )
    print(
        "Unresolved identity date/series segments: "
        f"{summary['unresolved_identity_segment_count']}"
    )
    print(f"Readiness: {summary['readiness']}")
    print(f"Certificate SHA256: {report.certificate_sha256}")
    print(f"Artifacts written: {len(paths)}")
    print("FULL_BENCHMARK_REPLAYS=0")
    print("STOP_POLICY_AUTOMATIC_PROMOTION_ENABLED=false")
    print(
        "ADJUSTED_REPLAY_READY=" + str(bool(summary["adjusted_replay_ready"])).lower()
    )
    print("PRODUCTION_INFLUENCE=false")


__all__ = ["final_official_evidence_closure_certify"]
