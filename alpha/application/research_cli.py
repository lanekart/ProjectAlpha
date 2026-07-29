"""Application services and Typer app for the research CLI."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

import typer

from alpha.research import (
    MarkdownResearchReportFormatter,
    ResearchExperimentManifest,
    ResearchExperimentRecord,
    ResearchReport,
    ResearchReportBuilder,
    ResearchSession,
    ResearchSessionEntry,
    StrategyComparisonEngine,
    StrategyComparisonReport,
    TextResearchReportFormatter,
)
from alpha.research.diagnostic_registry import (
    ExistingReplayEvidence,
    default_diagnostic_registry,
)
from alpha.research.institutional_research_director import (
    InstitutionalResearchDirector,
)
from alpha.research.lab_data_contract import ResearchDataContractAuditor
from alpha.research.lab_service import ConversationalResearchLab, LabExecution
from alpha.research.metric_truth_audit import (
    MetricTruthAuditEngine,
    MetricTruthAuditReport,
    export_metric_truth_csv,
    export_metric_truth_json,
    metric_truth_csv,
    metric_truth_experiment,
    metric_truth_json,
)
from alpha.research.rendering import (
    render_approval_population_reconciliation,
    render_approval_precision_truth,
    render_bottlenecks,
    render_briefing,
    render_metric_truth_summary,
    render_regime_metric_truth,
    render_registry,
    render_roadmap,
    render_roi,
)
from alpha.research.research_registry import ResearchExperimentRegistry

ResearchOutputFormat = Literal["text", "markdown"]
MetricTruthOutputFormat = Literal["text", "json", "csv"]

research_app = typer.Typer(help="Research workflow commands.")


@dataclass(frozen=True, slots=True)
class ResearchCLIService:
    """Application service backing deterministic research CLI commands."""

    def status(self) -> str:
        """Return a deterministic research subsystem status summary."""

        lines = (
            "Project Alpha Research",
            "Status: ready",
            "Capabilities:",
            "- walk-forward validation",
            "- parameter sweeps",
            "- experiment persistence",
            "- research sessions",
            "- strategy comparison",
            "- professional reports",
        )
        return "\n".join(lines) + "\n"

    def demo_session(self) -> str:
        """Return a deterministic demo research session summary."""

        session = build_demo_research_session()
        lines = (
            "Research Session",
            f"Session ID: {session.session_id}",
            f"Name: {session.name}",
            f"Entries: {session.entry_count}",
            f"Objective metrics: {', '.join(session.objective_metrics)}",
            f"Best strategy: {session.best_entry.strategy_name}",
            f"Best label: {session.best_entry.label}",
            f"Best value: {session.best_entry.best_objective_value}",
        )
        return "\n".join(lines) + "\n"

    def demo_comparison(self) -> str:
        """Return a deterministic demo strategy comparison summary."""

        report = build_demo_strategy_comparison()
        lines = [
            "Strategy Comparison",
            f"Session ID: {report.session_id}",
            f"Objective metric: {report.objective_metric}",
            f"Results: {report.result_count}",
            f"Strategies: {report.strategy_count}",
        ]
        lines.extend(
            "Rank "
            f"{result.comparison_rank}: "
            f"{result.strategy_name} / {result.label} "
            f"= {result.objective_value}"
            for result in report.results
        )
        return "\n".join(lines) + "\n"

    def demo_report(self, output_format: ResearchOutputFormat = "text") -> str:
        """Return a deterministic formatted professional research report."""

        session = build_demo_research_session()
        comparison_report = build_demo_strategy_comparison()
        report = ResearchReportBuilder().build_session_report(
            session=session,
            comparison_report=comparison_report,
            title="Project Alpha Research Demo",
        )
        return format_research_report(report=report, output_format=output_format)

    def institutional_bottlenecks(self) -> str:
        director = InstitutionalResearchDirector.from_default()
        return render_bottlenecks(director.bottlenecks)

    def institutional_roadmap(self) -> str:
        director = InstitutionalResearchDirector.from_default()
        return render_roadmap(director.roadmap)

    def institutional_roi(self) -> str:
        director = InstitutionalResearchDirector.from_default()
        return render_roi(director.roi)

    def institutional_registry(self) -> str:
        director = InstitutionalResearchDirector.from_default()
        return render_registry(
            diagnostics=director.diagnostics,
            experiments=director.experiments,
        )

    def institutional_briefing(self) -> str:
        director = InstitutionalResearchDirector.from_default()
        return render_briefing(director.briefing)

    def metric_truth_report(self) -> MetricTruthAuditReport:
        evidence = ExistingReplayEvidence()
        diagnostics = default_diagnostic_registry(
            evidence=evidence,
            discover_plugins=False,
        ).collect()
        report = MetricTruthAuditEngine().audit(
            records=evidence.records,
            outcomes=evidence.outcomes,
            diagnostics=diagnostics,
        )
        ResearchExperimentRegistry().record(metric_truth_experiment(report))
        return report


@research_app.command("status")
def research_status() -> None:
    """Show research subsystem status."""

    typer.echo(ResearchCLIService().status(), nl=False)


@research_app.command("session")
def research_session() -> None:
    """Show a deterministic demo research session."""

    typer.echo(ResearchCLIService().demo_session(), nl=False)


@research_app.command("compare")
def research_compare(
    experiment_ids: Annotated[
        list[str] | None,
        typer.Argument(help="Two or more ARL experiment IDs."),
    ] = None,
    database: Annotated[
        Path,
        typer.Option("--database", help="Historical Truth DuckDB path."),
    ] = Path("alpha_data/warehouse/historical_truth.duckdb"),
    root: Annotated[
        Path,
        typer.Option("--root", help="Research session and run root."),
    ] = Path(".alpha/research"),
) -> None:
    """Compare lab experiments, or show the legacy demo with no IDs."""

    if not experiment_ids:
        typer.echo(ResearchCLIService().demo_comparison(), nl=False)
        return
    result = ConversationalResearchLab(
        database=database,
        root=root,
    ).compare(tuple(experiment_ids))
    typer.echo(json.dumps(result, sort_keys=True, indent=2))


@research_app.command("report")
def research_report(
    output_format: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Output format: text or markdown.",
        ),
    ] = "text",
) -> None:
    """Render a deterministic demo professional research report."""

    parsed_format = _parse_research_output_format(output_format)
    typer.echo(ResearchCLIService().demo_report(parsed_format), nl=False)


@research_app.command("bottlenecks")
def research_bottlenecks() -> None:
    """Rank evidence-backed engineering bottlenecks."""

    typer.echo(ResearchCLIService().institutional_bottlenecks(), nl=False)


@research_app.command("roadmap")
def research_roadmap() -> None:
    """Generate a diagnostic-supported P0/P1/P2 roadmap."""

    typer.echo(ResearchCLIService().institutional_roadmap(), nl=False)


@research_app.command("roi")
def research_roi() -> None:
    """Separate measured engineering ROI from unknown estimates."""

    typer.echo(ResearchCLIService().institutional_roi(), nl=False)


@research_app.command("registry")
def research_registry(
    output_format: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Registry output: text, json, or csv.",
        ),
    ] = "text",
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Optional JSON or CSV export path.",
        ),
    ] = None,
) -> None:
    """Show diagnostic and experiment registries or export experiments."""

    normalized = output_format.strip().lower()
    if normalized not in {"text", "json", "csv"}:
        raise typer.BadParameter("Registry format must be text, json, or csv.")
    director = InstitutionalResearchDirector.from_default()
    if normalized == "text":
        if output is not None:
            raise typer.BadParameter("--output is supported only for JSON or CSV.")
        typer.echo(
            render_registry(
                diagnostics=director.diagnostics,
                experiments=director.experiments,
            ),
            nl=False,
        )
        return
    registry = director.experiment_registry
    text = registry.json_text() if normalized == "json" else registry.csv_text()
    if output is None:
        typer.echo(text, nl=False)
        return
    destination = (
        registry.export_json(output)
        if normalized == "json"
        else registry.export_csv(output)
    )
    typer.echo(f"Research registry exported: {destination}")


@research_app.command("briefing")
def research_briefing() -> None:
    """Render the executive research brief."""

    typer.echo(ResearchCLIService().institutional_briefing(), nl=False)


@research_app.command("approval-precision-truth")
def research_approval_precision_truth(
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output: text, json, or csv."),
    ] = "text",
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional JSON or CSV export path."),
    ] = None,
) -> None:
    """Audit every approval definition and canonical precision contract."""

    _emit_metric_truth(
        renderer=render_approval_precision_truth,
        output_format=output_format,
        output=output,
    )


@research_app.command("approval-population-reconciliation")
def research_approval_population_reconciliation(
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output: text, json, or csv."),
    ] = "text",
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional JSON or CSV export path."),
    ] = None,
) -> None:
    """Reconcile the historical and current raw approval populations."""

    _emit_metric_truth(
        renderer=render_approval_population_reconciliation,
        output_format=output_format,
        output=output,
    )


@research_app.command("regime-metric-truth")
def research_regime_metric_truth(
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output: text, json, or csv."),
    ] = "text",
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional JSON or CSV export path."),
    ] = None,
) -> None:
    """Reconstruct and validate the market-regime confusion metric."""

    _emit_metric_truth(
        renderer=render_regime_metric_truth,
        output_format=output_format,
        output=output,
    )


@research_app.command("metric-truth-summary")
def research_metric_truth_summary(
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output: text, json, or csv."),
    ] = "text",
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional JSON or CSV export path."),
    ] = None,
) -> None:
    """Show the authoritative approval and regime metric conclusions."""

    _emit_metric_truth(
        renderer=render_metric_truth_summary,
        output_format=output_format,
        output=output,
    )


@research_app.command("data-contract")
def research_data_contract(
    database: Annotated[
        Path,
        typer.Option("--database", help="Historical Truth DuckDB path."),
    ] = Path("alpha_data/warehouse/historical_truth.duckdb"),
) -> None:
    """Audit the complete post-2016 adjusted research boundary."""

    contract = ResearchDataContractAuditor().audit(database)
    typer.echo(json.dumps(contract.as_dict(), sort_keys=True, indent=2))


@research_app.command("ask")
def research_ask(
    request: Annotated[str, typer.Argument(help="Conversational strategy request.")],
    parent: Annotated[
        str | None,
        typer.Option("--parent", help="Parent ARL experiment ID."),
    ] = None,
    database: Annotated[
        Path,
        typer.Option("--database", help="Historical Truth DuckDB path."),
    ] = Path("alpha_data/warehouse/historical_truth.duckdb"),
    root: Annotated[
        Path,
        typer.Option("--root", help="Research session and run root."),
    ] = Path(".alpha/research"),
    compile_only: Annotated[
        bool,
        typer.Option("--compile-only", help="Compile and persist without execution."),
    ] = False,
) -> None:
    """Compile and, when certified, execute one conversational experiment."""

    execution = ConversationalResearchLab(database=database, root=root).ask(
        request,
        parent_experiment_id=parent,
        execute=not compile_only,
    )
    typer.echo(_render_lab_execution(execution), nl=False)


@research_app.command("chat")
def research_chat(
    database: Annotated[
        Path,
        typer.Option("--database", help="Historical Truth DuckDB path."),
    ] = Path("alpha_data/warehouse/historical_truth.duckdb"),
    root: Annotated[
        Path,
        typer.Option("--root", help="Research session and run root."),
    ] = Path(".alpha/research"),
) -> None:
    """Start a stateful conversational research session."""

    lab = ConversationalResearchLab(database=database, root=root)
    contract = lab.auditor.audit(database)
    typer.echo("Alpha Research Lab")
    typer.echo(
        "Certified data: "
        f"{contract.actual_start or 'UNAVAILABLE'} to "
        f"{contract.actual_end or 'UNAVAILABLE'}"
    )
    typer.echo(f"Execution status: {'READY' if contract.ready else 'FAIL_CLOSED'}")
    parent: str | None = None
    session_id: str | None = None
    while True:
        try:
            request = input("alpha> ").strip()
        except (EOFError, KeyboardInterrupt):
            typer.echo("")
            break
        if request.lower() in {"exit", "quit"}:
            break
        if not request:
            continue
        execution = lab.ask(
            request,
            parent_experiment_id=parent,
            session_id=session_id,
        )
        typer.echo(_render_lab_execution(execution), nl=False)
        specification = execution.compilation.specification
        if specification is not None:
            parent = specification.experiment_id
            session_id = specification.research_session_id


@research_app.command("show")
def research_show(
    experiment_id: Annotated[str, typer.Argument(help="ARL experiment ID.")],
    root: Annotated[
        Path,
        typer.Option("--root", help="Research session and run root."),
    ] = Path(".alpha/research"),
) -> None:
    """Show the complete typed experiment specification."""

    spec = ConversationalResearchLab(
        database=Path("alpha_data/warehouse/historical_truth.duckdb"),
        root=root,
    ).show(experiment_id)
    typer.echo(json.dumps(spec.as_dict(), sort_keys=True, indent=2))


@research_app.command("strategy")
def research_strategy(
    experiment_id: Annotated[str, typer.Argument(help="ARL experiment ID.")],
    root: Annotated[
        Path,
        typer.Option("--root", help="Research session and run root."),
    ] = Path(".alpha/research"),
) -> None:
    """Render the readable strategy and its typed specification."""

    spec = ConversationalResearchLab(
        database=Path("alpha_data/warehouse/historical_truth.duckdb"),
        root=root,
    ).show(experiment_id)
    typer.echo(f"Experiment: {spec.experiment_id}")
    typer.echo(f"Mode: {spec.strategy_mode.value}")
    typer.echo(f"Signals: {', '.join(spec.base_signal_source) or 'technical only'}")
    typer.echo(f"Entry: {spec.entry_rule.rule_id}")
    typer.echo(
        "Stops: "
        + (", ".join(item.rule_id for item in spec.stop_policy.rules) or "none")
    )
    typer.echo(
        "Targets: "
        + (", ".join(item.rule_id for item in spec.target_policy.rules) or "none")
    )
    typer.echo(json.dumps(spec.as_dict(), sort_keys=True, indent=2))


@research_app.command("trades")
def research_trades(
    experiment_id: Annotated[str, typer.Argument(help="ARL experiment ID.")],
    root: Annotated[
        Path,
        typer.Option("--root", help="Research session and run root."),
    ] = Path(".alpha/research"),
) -> None:
    """Show an experiment's immutable trade ledger."""

    path = root / "runs" / experiment_id / "trades.json"
    if not path.is_file():
        raise typer.BadParameter(
            f"Experiment {experiment_id} has no completed trade ledger."
        )
    typer.echo(path.read_text(), nl=False)


@research_app.command("explain")
def research_explain(
    experiment_id: Annotated[str, typer.Argument(help="ARL experiment ID.")],
    root: Annotated[
        Path,
        typer.Option("--root", help="Research session and run root."),
    ] = Path(".alpha/research"),
) -> None:
    """Show the experiment summary and compilation diff."""

    run = root / "runs" / experiment_id
    output = {
        "summary": _load_optional_json(run / "summary.json"),
        "specification_diff": _load_optional_json(run / "spec_diff.json"),
        "compiled_request": _load_optional_json(run / "compiled_request.json"),
    }
    typer.echo(json.dumps(output, sort_keys=True, indent=2))


@research_app.command("rerun")
def research_rerun(
    experiment_id: Annotated[str, typer.Argument(help="ARL experiment ID.")],
    database: Annotated[
        Path,
        typer.Option("--database", help="Historical Truth DuckDB path."),
    ] = Path("alpha_data/warehouse/historical_truth.duckdb"),
    root: Annotated[
        Path,
        typer.Option("--root", help="Research session and run root."),
    ] = Path(".alpha/research"),
) -> None:
    """Create an immutable child and rerun a prior experiment."""

    execution = ConversationalResearchLab(
        database=database,
        root=root,
    ).rerun(experiment_id)
    typer.echo(_render_lab_execution(execution), nl=False)


@research_app.command("sessions")
def research_sessions(
    root: Annotated[
        Path,
        typer.Option("--root", help="Research session and run root."),
    ] = Path(".alpha/research"),
) -> None:
    """List immutable conversational experiment registry entries."""

    lab = ConversationalResearchLab(
        database=Path("alpha_data/warehouse/historical_truth.duckdb"),
        root=root,
    )
    typer.echo(json.dumps(lab.store.entries(), sort_keys=True, indent=2))


def _render_lab_execution(execution: LabExecution) -> str:
    compilation = execution.compilation
    lines = [
        "Alpha Research Lab",
        f"Compilation: {compilation.status.value}",
    ]
    spec = compilation.specification
    if spec is not None:
        lines.extend(
            (
                f"Experiment: {spec.experiment_id}",
                f"Parent: {spec.parent_experiment_id or 'NONE'}",
                f"Mode: {spec.strategy_mode.value}",
                f"Data: {spec.data_start} to {spec.data_end}",
                f"Specification SHA-256: {spec.specification_sha256}",
            )
        )
    if compilation.changes:
        lines.append("Changed:")
        lines.extend(
            f"- {item.field}: {item.before} -> {item.after}"
            for item in compilation.changes
        )
    if compilation.issues:
        lines.append("Compilation blocked.")
        lines.append("Unresolved fields:")
        lines.extend(f"- {item.message}" for item in compilation.issues)
    if not execution.contract.ready:
        lines.append("Execution: BLOCKED_BY_DATA_CONTRACT")
        lines.extend(f"- {item}" for item in execution.contract.blockers)
    elif execution.result is not None:
        lines.append("Execution: COMPLETED")
        lines.append(json.dumps(execution.result.summary(), sort_keys=True))
    lines.append(f"Artifacts: {execution.output}")
    return "\n".join(lines) + "\n"


def _load_optional_json(path: Path) -> object:
    return json.loads(path.read_text()) if path.is_file() else None


def _emit_metric_truth(
    *,
    renderer: Callable[[MetricTruthAuditReport], str],
    output_format: str,
    output: Path | None,
) -> None:
    normalized = output_format.strip().lower()
    if normalized not in {"text", "json", "csv"}:
        raise typer.BadParameter("Metric truth format must be text, json, or csv.")
    if normalized == "text" and output is not None:
        raise typer.BadParameter("--output is supported only for JSON or CSV.")
    report = ResearchCLIService().metric_truth_report()
    if normalized == "text":
        typer.echo(renderer(report), nl=False)
        return
    if output is None:
        text = (
            metric_truth_json(report)
            if normalized == "json"
            else metric_truth_csv(report)
        )
        typer.echo(text, nl=False)
        return
    destination = (
        export_metric_truth_json(report, output)
        if normalized == "json"
        else export_metric_truth_csv(report, output)
    )
    typer.echo(f"Metric truth audit exported: {destination}")


def build_demo_research_session() -> ResearchSession:
    """Build a deterministic in-memory demo session for CLI smoke workflows."""

    entries = (
        ResearchSessionEntry(
            label="baseline",
            strategy_name="momentum",
            manifest=_manifest(
                run_id="demo-baseline",
                objective_value=Decimal("1.10"),
                lookback=20,
                threshold=Decimal("0.05"),
            ),
        ),
        ResearchSessionEntry(
            label="candidate",
            strategy_name="mean_reversion",
            manifest=_manifest(
                run_id="demo-candidate",
                objective_value=Decimal("1.25"),
                lookback=10,
                threshold=Decimal("0.03"),
            ),
        ),
    )
    return ResearchSession(
        session_id="demo-session",
        name="Research CLI Demo Session",
        entries=entries,
        description="Deterministic in-memory research session for CLI validation.",
        metadata={"environment": "demo"},
    )


def build_demo_strategy_comparison() -> StrategyComparisonReport:
    """Build a deterministic comparison report for the demo session."""

    return StrategyComparisonEngine(objective_metric="score").compare(
        session=build_demo_research_session(),
        metadata={"source": "research_cli"},
    )


def format_research_report(
    *,
    report: ResearchReport,
    output_format: ResearchOutputFormat,
) -> str:
    """Format a professional research report for CLI output."""

    if output_format == "text":
        return TextResearchReportFormatter().format(report)
    if output_format == "markdown":
        return MarkdownResearchReportFormatter().format(report)
    raise ValueError(f"unsupported research output format: {output_format}")


def supported_output_formats() -> Mapping[str, ResearchOutputFormat]:
    """Return supported output formats keyed by CLI option value."""

    return {
        "text": "text",
        "markdown": "markdown",
    }


def _parse_research_output_format(output_format: str) -> ResearchOutputFormat:
    normalized_format = output_format.strip().lower()
    formats = supported_output_formats()
    if normalized_format not in formats:
        raise typer.BadParameter("Research report format must be text or markdown.")
    return formats[normalized_format]


def _manifest(
    *,
    run_id: str,
    objective_value: Decimal,
    lookback: int,
    threshold: Decimal,
) -> ResearchExperimentManifest:
    record = ResearchExperimentRecord(
        experiment_id=f"{run_id}-best",
        parameters={"lookback": lookback, "threshold": threshold},
        objective_metric="score",
        objective_value=objective_value,
        rank=1,
    )
    return ResearchExperimentManifest(
        run_id=run_id,
        objective_metric="score",
        records=(record,),
    )


__all__ = [
    "ResearchCLIService",
    "MetricTruthOutputFormat",
    "ResearchOutputFormat",
    "build_demo_research_session",
    "build_demo_strategy_comparison",
    "format_research_report",
    "research_app",
    "supported_output_formats",
]
