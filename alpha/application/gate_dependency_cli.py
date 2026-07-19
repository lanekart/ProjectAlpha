from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Annotated

import typer

from alpha.benchmark_replay.exporting import DEFAULT_BENCHMARK_OUTPUT
from alpha.gate_dependency_audit import (
    DEFAULT_GATE_DEPENDENCY_OUTPUT,
    GateDependencyAuditEngine,
    GateDependencyAuditExporter,
    render_audit_summary,
)
from alpha.institutional_gate_truth.exports import DEFAULT_GATE_OUTPUT

DEFAULT_ACU_OUTPUT = Path(".alpha/acu/ALPHA_CANONICAL_v1.0")

gate_dependency_app = typer.Typer(
    help="Audit sequential gate bottlenecks and interactions without policy changes.",
    no_args_is_help=True,
)


@gate_dependency_app.command("audit")
def gate_dependency_audit(
    igta_output: Annotated[Path, typer.Option("--igta-output")] = DEFAULT_GATE_OUTPUT,
    acu_output: Annotated[Path, typer.Option("--acu-output")] = DEFAULT_ACU_OUTPUT,
    benchmark_output: Annotated[
        Path, typer.Option("--benchmark-output")
    ] = DEFAULT_BENCHMARK_OUTPUT,
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_GATE_DEPENDENCY_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Build the immutable GDSBA evidence set from frozen CABR and IGTA data."""

    report = GateDependencyAuditEngine().run(
        igta_output=igta_output,
        acu_output=acu_output,
        benchmark_output=benchmark_output,
        project_root=Path.cwd(),
    )
    paths = GateDependencyAuditExporter().export(
        report,
        output_directory=output,
    )
    if as_json:
        payload = {
            "buy_candidates": report.buy_candidates,
            "largest_bottleneck": report.bottleneck.largest_bottleneck,
            "largest_bottleneck_candidates": (
                report.bottleneck.largest_bottleneck_candidates
            ),
            "ordering_materially_changes_outcomes": (
                report.bottleneck.ordering_materially_changes_outcomes
            ),
            "production_influence": False,
        }
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(render_audit_summary(report), nl=False)
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


@gate_dependency_app.command("survival")
def gate_dependency_survival(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_GATE_DEPENDENCY_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show the frozen source-order sequential survival funnel."""

    rows = _csv_rows(output / "gate_survival.csv")
    if as_json:
        typer.echo(json.dumps(rows, indent=2, sort_keys=True))
        return
    typer.echo("Gate Sequential Survival")
    for row in rows:
        typer.echo(
            f"{row['sequence']}. {row['gate_id']}: entered={row['entered_stage']}; "
            f"passed={row['passed']}; rejected={row['rejected']}; "
            f"pass={_percent(row['pass_percent'])}; "
            f"reject={_percent(row['reject_percent'])}"
        )
    typer.echo("PRODUCTION_INFLUENCE=false")


@gate_dependency_app.command("interactions")
def gate_dependency_interactions(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_GATE_DEPENDENCY_OUTPUT,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 15,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show strongest supported gate overlaps and conditional dependencies."""

    interactions = _csv_rows(output / "interaction_matrix.csv")
    supported = sorted(
        (row for row in interactions if int(row["joint_failures"]) >= 30),
        key=lambda row: (
            -float(row["jaccard_percent"] or 0),
            -int(row["joint_failures"]),
            row["gate_a"],
            row["gate_b"],
        ),
    )
    if as_json:
        typer.echo(json.dumps(supported[:limit], indent=2, sort_keys=True))
        return
    typer.echo("Gate Interaction Matrix")
    for index, row in enumerate(supported[:limit], start=1):
        typer.echo(
            f"{index}. {row['gate_a']} + {row['gate_b']}: "
            f"joint={row['joint_failures']}; "
            f"Jaccard={row['jaccard_percent'] or 'unavailable'}%; "
            f"lift={row['interaction_lift'] or 'unavailable'}"
        )
    typer.echo("PRODUCTION_INFLUENCE=false")


@gate_dependency_app.command("report")
def gate_dependency_report(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_GATE_DEPENDENCY_OUTPUT,
) -> None:
    """Print the complete gate dependency executive report."""

    path = output / "executive_report.md"
    if not path.exists():
        raise typer.BadParameter(
            "GDSBA artifacts unavailable; run alpha gate-dependency audit"
        )
    typer.echo(path.read_text(encoding="utf-8"), nl=False)


def _csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise typer.BadParameter(
            "GDSBA artifacts unavailable; run alpha gate-dependency audit"
        )
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _percent(value: str) -> str:
    return "unavailable" if not value else f"{value}%"


__all__ = ["gate_dependency_app"]
