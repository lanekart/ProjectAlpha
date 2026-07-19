from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from alpha.data_platform import build_default_platform
from alpha.historical_truth_acquisition.engine import (
    HistoricalTruthAcquisitionEngine,
)
from alpha.historical_truth_acquisition.models import DEFAULT_HTA_OUTPUT, HTAResult
from alpha.historical_truth_acquisition.rendering import (
    render_certification,
    render_reconciliation,
    render_result,
    render_scorecard,
    render_warehouse,
)


def register_hta_commands(app: typer.Typer) -> None:
    @app.command("acquire")
    def acquire(
        dataset: Annotated[str | None, typer.Option("--dataset")] = None,
        resume: Annotated[bool, typer.Option("--resume")] = False,
        verify: Annotated[bool, typer.Option("--verify")] = False,
        force: Annotated[bool, typer.Option("--force")] = False,
        parallelism: Annotated[int, typer.Option("--parallel", min=1, max=32)] = 4,
        since: Annotated[str | None, typer.Option("--since")] = None,
        until: Annotated[str | None, typer.Option("--until")] = None,
        source_directory: Annotated[Path | None, typer.Option("--source-dir")] = None,
        lawfully_obtained: Annotated[bool, typer.Option("--lawfully-obtained")] = False,
        output: Annotated[Path, typer.Option("--output")] = DEFAULT_HTA_OUTPUT,
    ) -> None:
        """Acquire only licensed or lawfully supplied official history."""

        if dataset is not None:
            try:
                build_default_platform().registry.get(dataset)
            except KeyError as error:
                raise typer.BadParameter(str(error)) from error
        if source_directory is not None and not lawfully_obtained:
            raise typer.BadParameter(
                "--source-dir requires explicit --lawfully-obtained attestation"
            )
        try:
            result = HistoricalTruthAcquisitionEngine().execute(
                output_directory=output,
                source_directory=source_directory,
                lawfully_obtained=lawfully_obtained,
                dataset=dataset,
                resume=resume,
                verify=verify,
                force=force,
                parallelism=parallelism,
                since=_date(since),
                until=_date(until),
                acquire=True,
            )
        except (PermissionError, RuntimeError, ValueError) as error:
            raise typer.BadParameter(str(error)) from error
        typer.echo(render_result(result), nl=False)
        typer.echo(f"Output: {output}")

    @app.command("certify")
    def certify(
        since: Annotated[str | None, typer.Option("--since")] = None,
        until: Annotated[str | None, typer.Option("--until")] = None,
        output: Annotated[Path, typer.Option("--output")] = DEFAULT_HTA_OUTPUT,
    ) -> None:
        """Certify the isolated HTA candidate without activating it."""

        result = _evaluate(output, _date(since), _date(until))
        typer.echo(render_certification(result), nl=False)

    @app.command("reconcile")
    def reconcile(
        since: Annotated[str | None, typer.Option("--since")] = None,
        until: Annotated[str | None, typer.Option("--until")] = None,
        output: Annotated[Path, typer.Option("--output")] = DEFAULT_HTA_OUTPUT,
    ) -> None:
        """Classify Legacy/NSE/BSE discrepancies without overwriting any source."""

        result = _evaluate(output, _date(since), _date(until))
        typer.echo(render_reconciliation(result), nl=False)

    @app.command("scorecard")
    def scorecard(
        since: Annotated[str | None, typer.Option("--since")] = None,
        until: Annotated[str | None, typer.Option("--until")] = None,
        output: Annotated[Path, typer.Option("--output")] = DEFAULT_HTA_OUTPUT,
    ) -> None:
        """Show the certification-weighted historical truth score."""

        result = _evaluate(output, _date(since), _date(until))
        typer.echo(render_scorecard(result), nl=False)

    @app.command("warehouse")
    def warehouse(
        since: Annotated[str | None, typer.Option("--since")] = None,
        until: Annotated[str | None, typer.Option("--until")] = None,
        output: Annotated[Path, typer.Option("--output")] = DEFAULT_HTA_OUTPUT,
    ) -> None:
        """Inspect Warehouse v2 candidate readiness; never activate it."""

        result = _evaluate(output, _date(since), _date(until))
        typer.echo(render_warehouse(result), nl=False)


def _evaluate(output: Path, since: date | None, until: date | None) -> HTAResult:
    try:
        return HistoricalTruthAcquisitionEngine().execute(
            output_directory=output,
            since=since,
            until=until,
            acquire=False,
        )
    except (RuntimeError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error


def _date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter("HTA dates must use YYYY-MM-DD") from error


__all__ = ["register_hta_commands"]
