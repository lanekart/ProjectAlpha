"""CLI commands for the Alpha Pine Research Suite."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated

import typer

from alpha.pine_export import (
    FrameworkManifestBuilder,
    PineExportConfig,
    PineStaticValidator,
    PineStrategyExporter,
)
from alpha.pine_export.models import PineValidationReport
from alpha.pine_export.pine_renderer import STRATEGY_FILES
from alpha.pine_export.rendering import (
    render_audit,
    render_compilation_checklist,
    render_report,
    render_validation,
)

pine_app = typer.Typer(help="Export and validate TradingView Pine research scripts.")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pine_app.command("audit")
def audit() -> None:
    """Report the source-to-Pine parity boundary."""

    typer.echo(render_audit(), nl=False)


@pine_app.command("manifest")
def manifest(
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Manifest output directory."),
    ] = None,
) -> None:
    """Generate canonical framework, parity, and default manifests."""

    directory = output or _repository_root() / "tradingview" / "manifests"
    paths = FrameworkManifestBuilder().write(directory)
    typer.echo("Alpha Pine Manifests")
    for path in paths:
        typer.echo(f"Written: {path}")
    typer.echo("PRODUCTION_INFLUENCE=false")


@pine_app.command("export")
def export_strategy(
    strategy: Annotated[str, typer.Option("--strategy")],
    output: Annotated[Path | None, typer.Option("--output")] = None,
    timeframe: Annotated[str, typer.Option("--timeframe")] = "D",
    confirmation_timeframe: Annotated[
        str,
        typer.Option("--confirmation-timeframe"),
    ] = "240",
    setup: Annotated[str, typer.Option("--setup")] = "ANY_SETUP",
    stop_model: Annotated[
        str,
        typer.Option("--stop-model"),
    ] = "ATR_BUFFERED_SUPPORT",
    target_model: Annotated[
        str,
        typer.Option("--target-model"),
    ] = "PARTIAL_2R_3R_4R",
    entry_threshold: Annotated[
        str,
        typer.Option("--entry-threshold"),
    ] = "85",
    config: Annotated[Path | None, typer.Option("--config")] = None,
    self_contained: Annotated[
        bool,
        typer.Option(
            "--self-contained",
            help="Require the already-enforced self-contained export format.",
        ),
    ] = False,
) -> None:
    """Export a configured self-contained Pine strategy."""

    values: dict[str, object] = {
        "strategy": strategy,
        "timeframe": timeframe,
        "confirmation_timeframe": confirmation_timeframe,
        "setup": setup,
        "stop_model": stop_model,
        "target_model": target_model,
        "entry_threshold": entry_threshold,
    }
    if config is not None:
        values.update(_read_config(config))
        values["strategy"] = strategy
    try:
        export_config = PineExportConfig(
            strategy=str(values["strategy"]),
            timeframe=str(values["timeframe"]),
            confirmation_timeframe=str(values["confirmation_timeframe"]),
            setup=str(values["setup"]),
            stop_model=str(values["stop_model"]),
            target_model=str(values["target_model"]),
            entry_threshold=Decimal(str(values["entry_threshold"])),
        )
        path = PineStrategyExporter().export(export_config, output)
    except (InvalidOperation, ValueError, OSError, KeyError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo("Alpha Pine Export")
    typer.echo(f"Strategy: {export_config.strategy}")
    typer.echo(f"Output: {path}")
    typer.echo("SELF_CONTAINED=true")
    typer.echo(f"SELF_CONTAINED_FLAG_REQUESTED={str(self_contained).lower()}")
    typer.echo("PRODUCTION_INFLUENCE=false")
    typer.echo("TRADINGVIEW_MANUAL_COMPILATION=USER_VERIFICATION_REQUIRED")


@pine_app.command("regenerate")
def regenerate() -> None:
    """Regenerate every self-contained strategy through the strict exporter."""

    exporter = PineStrategyExporter()
    typer.echo("Alpha Pine Regeneration")
    strategies = sorted(STRATEGY_FILES, key=STRATEGY_FILES.__getitem__)
    for strategy in strategies:
        try:
            path = exporter.export(PineExportConfig(strategy=strategy))
        except (OSError, ValueError) as exc:
            typer.echo(f"FAILED {strategy}: {exc}")
            raise typer.Exit(code=1) from exc
        typer.echo(f"Written: {path}")
    typer.echo(f"Generated: {len(STRATEGY_FILES)}")
    typer.echo("NO_MANUAL_POST_GENERATION_PATCHING=true")
    typer.echo("PRODUCTION_INFLUENCE=false")


@pine_app.command("validate")
def validate(
    all_files: Annotated[
        bool,
        typer.Option("--all", help="Validate every .pine file in the suite."),
    ] = False,
    file: Annotated[
        Path | None,
        typer.Option("--file", help="Validate one Pine file."),
    ] = None,
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Treat warnings as validation failures."),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Legacy Pine directory to validate."),
    ] = None,
    json_output: Annotated[
        Path | None,
        typer.Option("--json-output", help="Write a machine-readable report."),
    ] = None,
) -> None:
    """Run deterministic static Pine v6 generation-safety checks."""

    if file is not None and (all_files or output is not None):
        raise typer.BadParameter("--file cannot be combined with --all or --output")
    validator = PineStaticValidator()
    try:
        if file is not None:
            report = PineValidationReport(files=(validator.validate_file(file),))
        else:
            root = output or _repository_root() / "tradingview"
            report = validator.validate_directory(root)
    except OSError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(render_validation(report, strict=strict), nl=False)
    if json_output is not None:
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(
            json.dumps(report.as_dict(strict=strict), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        typer.echo(f"JSON report: {json_output}")
    if not (report.strict_passed if strict else report.passed):
        raise typer.Exit(code=1)


@pine_app.command("compilation-checklist")
def compilation_checklist() -> None:
    """Print the honest TradingView compilation and smoke-test protocol."""

    typer.echo(render_compilation_checklist(), nl=False)


@pine_app.command("report")
def report() -> None:
    """Render suite status and validation boundaries."""

    validation = PineStaticValidator().validate_directory(
        _repository_root() / "tradingview"
    )
    typer.echo(render_report(validation), nl=False)


def _read_config(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read Pine config {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Pine config must be a JSON object")
    allowed = {
        "timeframe",
        "confirmation_timeframe",
        "setup",
        "stop_model",
        "target_model",
        "entry_threshold",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unsupported Pine config fields: {', '.join(unknown)}")
    return {str(key): value for key, value in payload.items()}
