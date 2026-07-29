"""CLI for governed retrospective frozen Alpha recommendation replay."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.research.frozen_alpha_replay import (
    FrozenAlphaReplayEngine,
    export_frozen_alpha_replay,
)


def frozen_alpha_replay(
    database: Path = typer.Option(
        Path("alpha_data/warehouse/historical_truth.duckdb"),
        "--database",
        exists=True,
        dir_okay=False,
    ),
    start: str = typer.Option("2016-01-01", "--start"),
    end: str = typer.Option(..., "--end"),
    source_commit: str = typer.Option(..., "--source-commit"),
    output: Path = typer.Option(
        Path("artifacts/dsi011a_post2016_execution/frozen_alpha_replay"),
        "--output",
    ),
) -> None:
    """Build a clearly retrospective recommendation ledger."""

    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError as exc:
        raise typer.BadParameter("dates must use YYYY-MM-DD") from exc
    report = FrozenAlphaReplayEngine().run(
        database,
        start_date=start_date,
        end_date=end_date,
        source_commit=source_commit,
    )
    paths = export_frozen_alpha_replay(report, output)
    print("DSI-011A Retrospective Frozen Alpha Replay")
    print(f"Run ID: {report.run_id}")
    print(f"Sessions completed: {report.sessions_completed}")
    print(f"Sessions failed: {report.sessions_failed}")
    print(f"Recommendations: {report.recommendation_count}")
    print(f"BUY: {report.buy_count}")
    print(f"STRONG_BUY: {report.strong_buy_count}")
    print(f"Earliest signal: {report.earliest_signal_date}")
    print(f"Readiness: {report.readiness_state}")
    print("Signal source: RETROSPECTIVE_FROZEN_ALPHA_REPLAY")
    print("These recommendations were not issued historically.")
    print("PRODUCTION_INFLUENCE=false")
    print(f"Artifacts: {', '.join(str(path) for path in paths)}")


__all__ = ["frozen_alpha_replay"]
