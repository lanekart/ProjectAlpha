from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from alpha.candidate_generation_research.exports import (
    DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
)
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.config.settings import settings
from alpha.setup_discovery.audit_service import SetupDiscoveryEvidenceEngine
from alpha.setup_discovery.exports import (
    DEFAULT_SETUP_DISCOVERY_OUTPUT,
    SetupDiscoveryExporter,
    load_setup_discovery_summary,
)
from alpha.setup_discovery.rendering import render_summary

setup_discovery_app = typer.Typer(
    help="Explain unsupported setups and causal lookback mismatches.",
    no_args_is_help=True,
)


@setup_discovery_app.command("report")
def report(
    database: Annotated[Path, typer.Option("--database")] = settings.database_path,
    candidate_directory: Annotated[
        Path, typer.Option("--candidate-directory")
    ] = DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_SETUP_DISCOVERY_OUTPUT,
) -> None:
    with LegacyMarketDataStore(database) as store:
        evidence = SetupDiscoveryEvidenceEngine().run(
            store=store,
            candidate_directory=candidate_directory,
        )
    paths = SetupDiscoveryExporter().export(evidence, output_directory=output)
    typer.echo(render_summary(evidence), nl=False)
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


@setup_discovery_app.command("summary")
def summary(
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_SETUP_DISCOVERY_OUTPUT,
) -> None:
    payload = load_setup_discovery_summary(output)
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


@setup_discovery_app.command("deep-dive")
def deep_dive(
    symbol: Annotated[str, typer.Option("--symbol")],
    output: Annotated[Path, typer.Option("--output")] = DEFAULT_SETUP_DISCOVERY_OUTPUT,
) -> None:
    normalized = symbol.strip().upper()
    filenames = {
        "KALYANKJIL": "kalyan_deep_dive.md",
        "PCJEWELLER": "pcjeweller_deep_dive.md",
    }
    filename = filenames.get(normalized)
    if filename is None:
        raise typer.BadParameter(
            "deep-dive evidence is available for KALYANKJIL and PCJEWELLER"
        )
    path = output / filename
    if not path.exists():
        raise typer.BadParameter(f"setup discovery artifact unavailable: {path}")
    typer.echo(path.read_text(encoding="utf-8"), nl=False)


__all__ = ["setup_discovery_app"]
