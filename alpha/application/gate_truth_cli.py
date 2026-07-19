from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Annotated

import typer

from alpha.benchmark_replay.exporting import DEFAULT_BENCHMARK_OUTPUT
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.config.settings import settings
from alpha.institutional_gate_truth import (
    DEFAULT_GATE_OUTPUT,
    InstitutionalGateTruthAuditEngine,
    InstitutionalGateTruthExporter,
    render_audit_summary,
)

DEFAULT_ACU_OUTPUT = Path(".alpha/acu/ALPHA_CANONICAL_v1.0")

gate_app = typer.Typer(
    help="Audit the empirical truth of frozen institutional gate rejections.",
    no_args_is_help=True,
)


@gate_app.command("audit")
def gate_audit(
    database: Annotated[Path, typer.Option("--database")] = settings.database_path,
    benchmark_output: Annotated[
        Path, typer.Option("--benchmark-output")
    ] = DEFAULT_BENCHMARK_OUTPUT,
    acu_output: Annotated[Path, typer.Option("--acu-output")] = DEFAULT_ACU_OUTPUT,
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_GATE_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run IGTA against immutable CABR evidence and later market bars."""

    with LegacyMarketDataStore(database) as store:
        report = InstitutionalGateTruthAuditEngine().run(
            store=store,
            benchmark_output=benchmark_output,
            acu_output=acu_output,
        )
    paths = InstitutionalGateTruthExporter().export(
        report,
        output_directory=output,
    )
    if as_json:
        effect = report.effectiveness
        counterfactual = report.counterfactual_statistics
        payload = {
            "rejected_population": effect.rejected_population,
            "correct_rejections": effect.correct_rejections,
            "false_rejections": effect.false_rejections,
            "marginal": effect.marginal_rejections,
            "data_uncertain": effect.data_uncertain_rejections,
            "rejection_accuracy_percent": str(
                effect.overall_rejection_accuracy_percent
            ),
            "counterfactual_cagr_percent": str(counterfactual.cagr_percent),
            "counterfactual_maximum_drawdown_percent": str(
                counterfactual.maximum_drawdown_percent
            ),
            "conclusion": effect.conclusion.value,
            "production_influence": False,
        }
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(render_audit_summary(report), nl=False)
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


@gate_app.command("rejected")
def gate_rejected(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_GATE_OUTPUT,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 25,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Inspect classified rejected BUY and STRONG BUY candidates."""

    rows = _csv_rows(output / "rejection_classification.csv")
    if as_json:
        typer.echo(json.dumps(rows[:limit], indent=2, sort_keys=True))
        return
    typer.echo("Rejected BUY Population")
    typer.echo(f"Total: {len(rows)}")
    for index, row in enumerate(rows[:limit], start=1):
        typer.echo(
            f"{index}. {row['observed_on']} {row['symbol']} "
            f"{row['final_signal']} score={row['candidate_score']}; "
            f"reason={row['rejection_reason']}; "
            f"outcome={row['classification']}"
        )
    typer.echo("PRODUCTION_INFLUENCE=false")


@gate_app.command("effectiveness")
def gate_effectiveness(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_GATE_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show aggregate gate accuracy and reason-level effectiveness."""

    rows = _csv_rows(output / "gate_effectiveness.csv")
    row = rows[0] if rows else {}
    if as_json:
        typer.echo(json.dumps(row, indent=2, sort_keys=True))
        return
    typer.echo("Institutional Gate Effectiveness")
    for label, key in (
        ("Rejected Population", "rejected_population"),
        ("Correct Rejections", "correct_rejections"),
        ("False Rejections", "false_rejections"),
        ("Marginal", "marginal_rejections"),
        ("Data Uncertain", "data_uncertain_rejections"),
        ("Rejection Accuracy", "overall_rejection_accuracy_percent"),
        ("False Rejection Rate", "overall_false_rejection_rate_percent"),
        ("Opportunity Value Lost", "opportunity_value_lost"),
        ("Capital Protection Gained", "capital_protection_gained"),
        ("Conclusion", "conclusion"),
    ):
        typer.echo(f"{label}: {row.get(key) or 'unavailable'}")
    typer.echo("PRODUCTION_INFLUENCE=false")


@gate_app.command("counterfactual")
def gate_counterfactual(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_GATE_OUTPUT,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show the equal-weight diagnostic portfolio with the gate removed."""

    rows = _csv_rows(output / "counterfactual_statistics.csv")
    row = rows[0] if rows else {}
    if as_json:
        typer.echo(json.dumps(row, indent=2, sort_keys=True))
        return
    typer.echo("Gate-Off Counterfactual Portfolio")
    for label, key in (
        ("Rejected Signals", "rejected_signals"),
        ("Entered Trades", "entered_trades"),
        ("Completed Trades", "completed_trades"),
        ("Win Rate", "win_rate_percent"),
        ("Payoff Ratio", "payoff_ratio"),
        ("Expectancy", "expectancy_percent"),
        ("CAGR", "cagr_percent"),
        ("Maximum Drawdown", "maximum_drawdown_percent"),
        ("Sharpe", "sharpe_ratio"),
        ("Sortino", "sortino_ratio"),
    ):
        typer.echo(f"{label}: {row.get(key) or 'unavailable'}")
    typer.echo("PRODUCTION_INFLUENCE=false")


@gate_app.command("report")
def gate_report(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_GATE_OUTPUT,
) -> None:
    """Print the full institutional gate truth report."""

    path = output / "executive_report.md"
    if not path.exists():
        raise typer.BadParameter("IGTA artifacts unavailable; run alpha gate audit")
    typer.echo(path.read_text(encoding="utf-8"), nl=False)


def _csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise typer.BadParameter("IGTA artifacts unavailable; run alpha gate audit")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


__all__ = ["gate_app"]
