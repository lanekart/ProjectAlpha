from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import typer

from alpha.application.runtime import ProjectAlphaRuntime
from alpha.candidate_learning.repository import LearningLedgerRepository
from alpha.forward_validation.approval_policy_optimizer import (
    ApprovalPolicyOptimizer,
)
from alpha.forward_validation.forward_validation_engine import ForwardValidationEngine
from alpha.forward_validation.models import (
    CURRENT_POLICY_VERSION,
    ApprovalOptimizationReport,
    CounterfactualPolicy,
    ForwardRiskControls,
    ForwardValidationConfig,
    OptimizationRecommendation,
    PolicyStage,
    PolicyVersion,
)
from alpha.forward_validation.policy_versioning import PolicyVersionRegistry
from alpha.forward_validation.rendering import (
    render_approval_policy,
    render_counterfactuals,
    render_journal,
    render_optimizer,
    render_performance,
    render_portfolios,
    render_readiness,
    render_snapshot,
    render_start,
    render_update,
)
from alpha.forward_validation.validation_registry import ForwardValidationRegistry

forward_app = typer.Typer(
    help="Immutable forward validation and offline approval-policy research."
)


@forward_app.command(name="start")
def forward_start(
    capital: str = typer.Option(
        "1000000",
        "--capital",
        help="Initial virtual capital; no broker funds are touched.",
    ),
    registry: Path | None = typer.Option(None, "--registry"),
    max_positions: int | None = typer.Option(None, "--max-positions"),
    max_position_pct: str | None = typer.Option(None, "--max-position-pct"),
    max_sector_pct: str | None = typer.Option(None, "--max-sector-pct"),
    daily_loss_pct: str | None = typer.Option(None, "--daily-loss-pct"),
    drawdown_limit_pct: str | None = typer.Option(None, "--drawdown-limit-pct"),
) -> None:
    """Initialize immutable forward validation for policy V1."""

    config = ForwardValidationConfig(
        started_at=datetime.now(tz=UTC),
        initial_capital=_decimal(capital, "capital"),
        policy_version=PolicyVersion(CURRENT_POLICY_VERSION),
        risk_controls=ForwardRiskControls(
            maximum_simultaneous_positions=max_positions,
            maximum_allocation_per_position_pct=_optional_decimal(
                max_position_pct, "max-position-pct"
            ),
            maximum_sector_allocation_pct=_optional_decimal(
                max_sector_pct, "max-sector-pct"
            ),
            daily_loss_limit_pct=_optional_decimal(daily_loss_pct, "daily-loss-pct"),
            portfolio_drawdown_limit_pct=_optional_decimal(
                drawdown_limit_pct, "drawdown-limit-pct"
            ),
        ),
    )
    engine = _engine(registry)
    try:
        created = engine.start(config)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print(render_start(engine.registry.load_config(), created=created))


@forward_app.command(name="snapshot")
def forward_snapshot(
    date_value: str = typer.Option("today", "--date"),
    demo: bool = typer.Option(False, "--demo"),
    registry: Path | None = typer.Option(None, "--registry"),
    export_json: Path | None = typer.Option(None, "--export-json"),
    export_csv_dir: Path | None = typer.Option(None, "--export-csv-dir"),
) -> None:
    """Run Alpha and freeze the recommendations produced at that moment."""

    runtime_result = ProjectAlphaRuntime().run_intelligence(
        date_str=date_value,
        demo=demo,
    )
    engine = _engine(registry)
    snapshots, inserted = engine.capture_runtime(runtime_result)
    if export_json is not None:
        engine.registry.export_json(export_json)
    if export_csv_dir is not None:
        engine.registry.export_csv(export_csv_dir)
    _print(render_snapshot(snapshots, inserted=inserted))


@forward_app.command(name="portfolio")
def forward_portfolio(
    as_of: str = typer.Option("today", "--as-of"),
    registry: Path | None = typer.Option(None, "--registry"),
    no_update: bool = typer.Option(False, "--no-update"),
) -> None:
    """Update stored positions from later persisted bars and show accounting."""

    engine = _engine(registry)
    if not no_update:
        summary = engine.update(as_of=_date(as_of))
        _print(render_update(summary))
        print()
    _print(render_portfolios(engine.portfolios()))


@forward_app.command(name="performance")
def forward_performance(
    registry: Path | None = typer.Option(None, "--registry"),
) -> None:
    """Show realized, non-estimated forward metrics by policy cohort."""

    _print(render_performance(_engine(registry).performance()))


@forward_app.command(name="journal")
def forward_journal(
    registry: Path | None = typer.Option(None, "--registry"),
    export_json: Path | None = typer.Option(None, "--export-json"),
    export_csv_dir: Path | None = typer.Option(None, "--export-csv-dir"),
) -> None:
    """Show the append-only recommendation and position journal."""

    engine = _engine(registry)
    if export_json is not None:
        engine.registry.export_json(export_json)
    if export_csv_dir is not None:
        engine.registry.export_csv(export_csv_dir)
    _print(render_journal(engine.journal()))


@forward_app.command(name="approval-policy")
def forward_approval_policy(
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
) -> None:
    """Audit the current approval policy and its stop-distance bottleneck."""

    report = _optimization_report(learning_ledger)
    _print(render_approval_policy(report))


@forward_app.command(name="approval-optimizer")
def forward_approval_optimizer(
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
    policy_registry: Path | None = typer.Option(None, "--policy-registry"),
) -> None:
    """Generate and stage-validate offline candidate approval policies."""

    report = _optimization_report(learning_ledger)
    selected = _selected_candidate(report.recommendation, report.candidates)
    if selected is not None:
        registry = PolicyVersionRegistry(policy_registry)
        registry.register(selected)
        registry.promote(selected.policy_version, PolicyStage.FORWARD_VALIDATION)
    _print(render_optimizer(report))


@forward_app.command(name="approval-counterfactual")
def forward_approval_counterfactual(
    learning_ledger: Path | None = typer.Option(None, "--learning-ledger"),
) -> None:
    """Show remove, relax, tighten, reorder, merge, and replace trials."""

    _print(render_counterfactuals(_optimization_report(learning_ledger)))


@forward_app.command(name="deployment-readiness")
def forward_deployment_readiness(
    registry: Path | None = typer.Option(None, "--registry"),
    policy_registry: Path | None = typer.Option(None, "--policy-registry"),
) -> None:
    """Classify readiness from frozen evidence without inferred thresholds."""

    engine = ForwardValidationEngine(
        registry=ForwardValidationRegistry(registry),
        policy_registry=PolicyVersionRegistry(policy_registry),
    )
    _print(render_readiness(engine.deployment_readiness()))


def _engine(path: Path | None) -> ForwardValidationEngine:
    return ForwardValidationEngine(registry=ForwardValidationRegistry(path))


def _optimization_report(path: Path | None) -> ApprovalOptimizationReport:
    ledger = LearningLedgerRepository(path)
    return ApprovalPolicyOptimizer().optimize(
        records=ledger.load_records(),
        outcomes=ledger.load_outcomes(),
    )


def _selected_candidate(
    recommendation: OptimizationRecommendation,
    candidates: tuple[CounterfactualPolicy, ...],
) -> CounterfactualPolicy | None:
    version = {
        OptimizationRecommendation.DEPLOY_POLICY_V2_TO_FORWARD_VALIDATION: 2,
        OptimizationRecommendation.DEPLOY_POLICY_V3_TO_FORWARD_VALIDATION: 3,
    }.get(recommendation)
    if version is None:
        return None
    return next(
        (item for item in candidates if item.policy_version.number == version),
        None,
    )


def _decimal(value: str, label: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise typer.BadParameter(f"{label} must be numeric") from exc
    if parsed <= Decimal("0"):
        raise typer.BadParameter(f"{label} must be positive")
    return parsed


def _optional_decimal(value: str | None, label: str) -> Decimal | None:
    return None if value is None else _decimal(value, label)


def _date(value: str) -> date:
    if value.strip().lower() == "today":
        return date.today()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("date must be today or YYYY-MM-DD") from exc


def _print(lines: tuple[str, ...]) -> None:
    for line in lines:
        print(line)


__all__ = ["forward_app"]
