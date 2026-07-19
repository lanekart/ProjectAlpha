"""CLI for the TradingView Research Laboratory evidence workflow."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, cast

import typer

from alpha.adaptive_weights.models import to_primitive
from alpha.adaptive_weights.policy_registry import CandidateWeightPolicyRegistry
from alpha.pine_export.validation import PineStaticValidator
from alpha.tradingview_research.aggregation import ResearchAggregationEngine
from alpha.tradingview_research.baseline import (
    baseline_manifest,
    canonical_baseline_configuration,
    experiment_template,
)
from alpha.tradingview_research.batch import BatchRunPlanner
from alpha.tradingview_research.comparison import ComparativeResearchEngine
from alpha.tradingview_research.grid import WeightGridGenerator
from alpha.tradingview_research.models import (
    ObservationRole,
    ResearchPartition,
    TradingViewExperiment,
    UniverseMember,
    VariantFamily,
    WeightRange,
)
from alpha.tradingview_research.promotion import CandidatePromotionEngine
from alpha.tradingview_research.ranking import CandidateRankingEngine
from alpha.tradingview_research.registry import (
    TradingViewResearchRegistry,
    configuration_from_dict,
    experiment_from_dict,
)
from alpha.tradingview_research.rendering import (
    comparison_as_dict,
    render_experiment_report,
    render_ranking,
    render_sector_summaries,
    render_universe_distribution,
)
from alpha.tradingview_research.variants import LabVariantGenerator
from alpha.tradingview_research.weight_evidence import (
    TradingViewStrategyTesterImporter,
    TradingViewWeightEvidenceAdapter,
    frozen_weight_presets,
)

trl_app = typer.Typer(help="Govern TradingView experiments against Alpha baseline.")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


@trl_app.command("baseline")
def baseline(
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Render or export the canonical Alpha comparison baseline."""

    payload = baseline_manifest()
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if output is None:
        typer.echo(text, nl=False)
    else:
        _write(output, text)
        typer.echo(f"Written: {output}")


@trl_app.command("template")
def template(
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Write a no-fabrication experiment intake template."""

    _write(
        output,
        json.dumps(experiment_template(), indent=2, sort_keys=True) + "\n",
    )
    typer.echo(f"Written: {output}")
    typer.echo("OBSERVED_METRICS_REQUIRED=true")
    typer.echo("PRODUCTION_INFLUENCE=false")


@trl_app.command("register")
def register(
    input_path: Annotated[Path, typer.Option("--input")],
    registry: Annotated[Path | None, typer.Option("--registry")] = None,
) -> None:
    """Permanently register one complete measured experiment."""

    try:
        experiment = experiment_from_dict(_read_json(input_path))
        created = TradingViewResearchRegistry(registry).record(experiment)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo("TRL Experiment Registration")
    typer.echo(f"Experiment ID: {experiment.experiment_id}")
    typer.echo(f"Status: {'RECORDED' if created else 'ALREADY_RECORDED'}")
    typer.echo(f"Observations: {len(experiment.observations)}")
    typer.echo("PRODUCTION_INFLUENCE=false")


@trl_app.command("report")
def report(
    experiment_id: Annotated[str, typer.Option("--experiment-id")],
    registry: Annotated[Path | None, typer.Option("--registry")] = None,
    json_output: Annotated[
        Path | None,
        typer.Option("--json-output"),
    ] = None,
) -> None:
    """Compare one treatment with its population-matched Alpha baseline."""

    experiment = _require_experiment(experiment_id, registry)
    comparison = ComparativeResearchEngine().compare(experiment)
    promotion = CandidatePromotionEngine().assess(experiment, comparison)
    typer.echo(
        render_experiment_report(experiment, comparison, promotion),
        nl=False,
    )
    if json_output is not None:
        _write(
            json_output,
            json.dumps(
                comparison_as_dict(experiment, comparison, promotion),
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        typer.echo(f"JSON report: {json_output}")


@trl_app.command("promote")
def promote(
    experiment_id: Annotated[str, typer.Option("--experiment-id")],
    registry: Annotated[Path | None, typer.Option("--registry")] = None,
) -> None:
    """Evaluate fail-closed eligibility for Alpha replay research."""

    experiment = _require_experiment(experiment_id, registry)
    comparison = ComparativeResearchEngine().compare(experiment)
    assessment = CandidatePromotionEngine().assess(experiment, comparison)
    typer.echo("TRL Candidate Promotion")
    typer.echo(f"Experiment ID: {experiment.experiment_id}")
    typer.echo(f"Decision: {assessment.decision.value}")
    typer.echo(f"Promote: {'YES' if assessment.promote else 'NO'}")
    typer.echo(
        "Failed Gates: "
        + (
            ", ".join(item.value for item in assessment.failed_reasons)
            if assessment.failed_reasons
            else "none"
        )
    )
    typer.echo(assessment.explanation)
    typer.echo("PRODUCTION_INFLUENCE=false")


@trl_app.command("sector-report")
def sector_report(
    experiment_id: Annotated[str, typer.Option("--experiment-id")],
    registry: Annotated[Path | None, typer.Option("--registry")] = None,
) -> None:
    """Report measured treatment results by sector and partition."""

    experiment = _require_experiment(experiment_id, registry)
    rows = ResearchAggregationEngine().sector_summaries(experiment)
    typer.echo(render_sector_summaries(rows), nl=False)


@trl_app.command("symbol-report")
def symbol_report(
    experiment_id: Annotated[str, typer.Option("--experiment-id")],
    partition: Annotated[
        ResearchPartition,
        typer.Option("--partition", case_sensitive=False),
    ],
    role: Annotated[
        ObservationRole,
        typer.Option("--role", case_sensitive=False),
    ] = ObservationRole.TREATMENT,
    registry: Annotated[Path | None, typer.Option("--registry")] = None,
) -> None:
    """Report symbol-level metric distributions for one frozen partition."""

    experiment = _require_experiment(experiment_id, registry)
    row = ResearchAggregationEngine().universe_distribution(
        experiment,
        role=role,
        partition=partition,
    )
    typer.echo(render_universe_distribution(row), nl=False)


@trl_app.command("rank")
def rank(
    registry: Annotated[Path | None, typer.Option("--registry")] = None,
) -> None:
    """Rank registered candidates using measured deltas only."""

    rows = CandidateRankingEngine().rank(TradingViewResearchRegistry(registry).load())
    typer.echo(render_ranking(rows), nl=False)


@trl_app.command("registry")
def registry_export(
    registry: Annotated[Path | None, typer.Option("--registry")] = None,
    json_output: Annotated[Path | None, typer.Option("--json-output")] = None,
    csv_output: Annotated[Path | None, typer.Option("--csv-output")] = None,
) -> None:
    """Inspect or export the immutable TRL experiment registry."""

    store = TradingViewResearchRegistry(registry)
    typer.echo("TRL Experiment Registry")
    typer.echo(f"Experiments: {len(store.load())}")
    if json_output is not None:
        store.export_json(json_output)
        typer.echo(f"JSON: {json_output}")
    if csv_output is not None:
        store.export_csv(csv_output)
        typer.echo(f"CSV: {csv_output}")
    typer.echo("PRODUCTION_INFLUENCE=false")


@trl_app.command("weight-grid")
def weight_grid(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Generate a bounded development-only component-weight grid."""

    try:
        payload = _object(_read_json(input_path), "weight grid")
        baseline_value = payload.get("configuration")
        configuration = (
            canonical_baseline_configuration()
            if baseline_value is None
            else configuration_from_dict(baseline_value)
        )
        partition = ResearchPartition(str(payload.get("partition", "")))
        ranges = tuple(
            WeightRange(
                component=_required_text(item, "component"),
                minimum=_required_decimal(item, "minimum"),
                maximum=_required_decimal(item, "maximum"),
                step=_required_decimal(item, "step"),
            )
            for item in _objects(payload.get("ranges"), "ranges")
        )
        maximum = _optional_integer(payload.get("maximum_variants"), 5_000)
        variants = WeightGridGenerator().generate(
            configuration,
            ranges,
            partition=partition,
            maximum_variants=maximum,
        )
    except (InvalidOperation, OSError, ValueError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    result = {
        "partition": partition.value,
        "production_influence": False,
        "variants": [
            {
                "configuration": item.as_dict(),
                "configuration_id": item.configuration_id,
            }
            for item in variants
        ],
    }
    _write(output, json.dumps(result, indent=2, sort_keys=True) + "\n")
    typer.echo(f"Variants: {len(variants)}")
    typer.echo(f"Written: {output}")
    typer.echo("HOLDOUT_OPTIMIZATION=false")


@trl_app.command("batch-plan")
def batch_plan(
    input_path: Annotated[Path, typer.Option("--input")],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Create auditable one-symbol-per-run plans for universe research."""

    try:
        payload = _object(_read_json(input_path), "batch plan")
        configuration_value = payload.get("configuration")
        configuration = (
            canonical_baseline_configuration()
            if configuration_value is None
            else configuration_from_dict(configuration_value)
        )
        members = tuple(
            UniverseMember(
                symbol=_required_text(item, "symbol"),
                sector=_required_text(item, "sector"),
            )
            for item in _objects(payload.get("members"), "members")
        )
        partitions_value = payload.get("partitions")
        if not isinstance(partitions_value, list):
            raise ValueError("partitions must be a list")
        partitions = tuple(ResearchPartition(str(item)) for item in partitions_value)
        runs = BatchRunPlanner().plan(configuration, members, partitions)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    result = {
        "configuration_id": configuration.configuration_id,
        "production_influence": False,
        "runs": [
            {
                "configuration_id": item.configuration_id,
                "partition": item.partition.value,
                "run_id": item.run_id,
                "sector": item.sector,
                "symbol": item.symbol,
            }
            for item in runs
        ],
    }
    _write(output, json.dumps(result, indent=2, sort_keys=True) + "\n")
    typer.echo(f"Runs: {len(runs)}")
    typer.echo(f"Written: {output}")
    typer.echo("TRADINGVIEW_BATCH_EXECUTION=MANUAL_PER_SYMBOL")


@trl_app.command("variant-plan")
def variant_plan(
    family: Annotated[
        VariantFamily,
        typer.Option("--family", case_sensitive=False),
    ],
    output: Annotated[Path, typer.Option("--output")],
    configuration_path: Annotated[
        Path | None,
        typer.Option("--configuration"),
    ] = None,
) -> None:
    """Enumerate a complete laboratory family before observing results."""

    try:
        configuration = (
            canonical_baseline_configuration()
            if configuration_path is None
            else configuration_from_dict(_read_json(configuration_path))
        )
        generator = LabVariantGenerator()
        if family is VariantFamily.COMPONENT_ABLATION:
            variants = generator.component_ablation(configuration)
        elif family is VariantFamily.STOP_EXIT:
            variants = generator.stop_exit(configuration)
        else:
            variants = generator.multi_timeframe(configuration)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    payload = {
        "family": family.value,
        "production_influence": False,
        "variants": [
            {
                "configuration": item.as_dict(),
                "configuration_id": item.configuration_id,
            }
            for item in variants
        ],
    }
    _write(output, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    typer.echo(f"Family: {family.value}")
    typer.echo(f"Variants: {len(variants)}")
    typer.echo(f"Written: {output}")
    typer.echo("RESULT_AWARE_SELECTION=false")
    typer.echo("PRODUCTION_INFLUENCE=false")


@trl_app.command("scripts")
def scripts() -> None:
    """List TRL Pine modules and their static-validation status."""

    root = _repository_root() / "tradingview" / "labs"
    report_ = PineStaticValidator().validate_directory(root)
    typer.echo("TradingView Research Laboratory Scripts")
    for result in report_.files:
        typer.echo(
            f"{result.path.name}: {'PASS' if result.passed(strict=True) else 'FAIL'}"
        )
    typer.echo(f"Scripts: {report_.files_checked}")
    typer.echo(f"PINE_STATIC_VALIDATION={'PASS' if report_.strict_passed else 'FAIL'}")
    typer.echo("TRADINGVIEW_MANUAL_COMPILATION=USER_VERIFICATION_REQUIRED")
    typer.echo("PRODUCTION_INFLUENCE=false")
    if not report_.strict_passed:
        raise typer.Exit(code=1)


@trl_app.command("weight-presets")
def weight_presets(
    output: Annotated[Path | None, typer.Option("--output")] = None,
    policy_registry: Annotated[Path | None, typer.Option("--policy-registry")] = None,
) -> None:
    """Export frozen canonical, ablation, and adaptive candidate presets."""

    presets = frozen_weight_presets(CandidateWeightPolicyRegistry(policy_registry))
    payload = {
        "presets": [
            {
                "configuration": item.as_dict(),
                "configuration_id": item.configuration_id,
                "name": item.name,
            }
            for item in presets
        ],
        "tradingview_autonomous_learning": False,
        "production_influence": False,
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if output is None:
        typer.echo(text, nl=False)
    else:
        _write(output, text)
        typer.echo(f"Written: {output}")


@trl_app.command("import-weight-results")
def import_weight_results(
    input_path: Annotated[Path, typer.Option("--input")],
    research_id: Annotated[str, typer.Option("--research-id")],
    treatment_preset: Annotated[str, typer.Option("--treatment-preset")],
    registry: Annotated[Path | None, typer.Option("--registry")] = None,
    policy_registry: Annotated[Path | None, typer.Option("--policy-registry")] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Import measured Strategy Tester CSV evidence under a stable research ID."""

    try:
        presets = {
            item.name: item
            for item in frozen_weight_presets(
                CandidateWeightPolicyRegistry(policy_registry)
            )
        }
        baseline_configuration = presets["ALPHA_CANONICAL"]
        treatment_configuration = presets[treatment_preset]
        experiment = TradingViewStrategyTesterImporter().import_csv(
            input_path,
            research_id=research_id,
            baseline=baseline_configuration,
            treatment=treatment_configuration,
        )
        ablations = TradingViewWeightEvidenceAdapter().to_matched_ablation(experiment)
        created = TradingViewResearchRegistry(registry).record(experiment)
    except (KeyError, OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    payload = {
        "experiment": experiment.as_dict(),
        "matched_ablation_evidence": to_primitive(ablations),
        "registry_status": "CREATED" if created else "ALREADY_RECORDED",
        "tradingview_autonomous_learning": False,
        "production_influence": False,
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if output is None:
        typer.echo(text, nl=False)
    else:
        _write(output, text)
        typer.echo(f"Written: {output}")
    typer.echo("TRADINGVIEW_AUTONOMOUS_LEARNING=false")
    typer.echo("PRODUCTION_INFLUENCE=false")


def _require_experiment(
    experiment_id: str,
    registry: Path | None,
) -> TradingViewExperiment:
    experiment = next(
        (
            item
            for item in TradingViewResearchRegistry(registry).load()
            if item.experiment_id == experiment_id
        ),
        None,
    )
    if experiment is None:
        raise typer.BadParameter(f"unknown TRL experiment {experiment_id!r}")
    return experiment


def _read_json(path: Path) -> object:
    return cast(object, json.loads(path.read_text(encoding="utf-8")))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return {str(key): item for key, item in value.items()}


def _objects(value: object, label: str) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return tuple(_object(item, label) for item in value)


def _required_text(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _required_decimal(row: dict[str, object], key: str) -> Decimal:
    value = row.get(key)
    if not isinstance(value, (str, int, float, Decimal)) or isinstance(value, bool):
        raise ValueError(f"{key} must be numeric")
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise ValueError(f"{key} must be finite")
    return parsed


def _optional_integer(value: object, default: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("maximum_variants must be an integer")
    return value


__all__ = ["trl_app"]
