from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Annotated, Any

import typer

from alpha.candidate_generation_research.audit_service import (
    CandidateGenerationResearchEngine,
)
from alpha.candidate_generation_research.exports import (
    DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
    CandidateResearchExporter,
    load_candidate_research_payload,
)
from alpha.candidate_generation_research.models import (
    CANONICAL_POLICY_ID,
    DATASET_VERSION,
)
from alpha.candidate_generation_research.rendering import render_summary
from alpha.candidate_generation_research.research_integration import (
    record_candidate_research_experiment,
)
from alpha.canonical_integrity_audit.parity_inputs import DEFAULT_ACU_DIRECTORY
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.config.settings import settings

candidate_research_app = typer.Typer(
    help="Audit point-in-time tradability and candidate-generation recovery.",
    no_args_is_help=True,
)


@candidate_research_app.command("define-opportunities")
def define_opportunities(
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
    symbol: Annotated[str | None, typer.Option("--symbol")] = None,
    event_family: Annotated[str | None, typer.Option("--event-family")] = None,
) -> None:
    payload = load_candidate_research_payload(output)
    events = _rows(payload, "forward_move_events")
    onsets = _rows(payload, "onsets")
    if symbol is not None:
        events = tuple(item for item in events if item.get("symbol") == symbol.upper())
        onsets = tuple(item for item in onsets if item.get("symbol") == symbol.upper())
    if event_family is not None:
        onsets = tuple(
            item for item in onsets if item.get("event_family") == event_family.upper()
        )
    typer.echo("Point-in-Time Tradable Opportunity Definition")
    typer.echo(f"Forward Move Events: {len(events)}")
    typer.echo(f"Tradable Onsets: {len(onsets)}")
    typer.echo("Future Return Defines Entry: No")
    typer.echo("PRODUCTION_INFLUENCE=false")


@candidate_research_app.command("funnel")
def funnel(
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
    symbol: Annotated[str | None, typer.Option("--symbol")] = None,
) -> None:
    rows = _rows(load_candidate_research_payload(output), "funnel")
    if symbol is not None:
        rows = tuple(item for item in rows if item.get("symbol") == symbol.upper())
    typer.echo("Candidate Generation Funnel")
    typer.echo(f"Events Traced: {len(rows)}")
    for field in (
        "tradable_onset",
        "canonical_setup_recognized",
        "canonical_candidate_created",
        "timing_actionable",
        "trade_plan_feasible",
    ):
        passed = sum(item.get(field) == "PASS" for item in rows)
        typer.echo(f"{_label(field)} Pass: {passed}")


@candidate_research_app.command("setups")
def setups(
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
    setup_family: Annotated[str | None, typer.Option("--setup-family")] = None,
) -> None:
    rows = _rows(load_candidate_research_payload(output), "setup_metrics")
    if setup_family is not None:
        rows = tuple(
            item
            for item in rows
            if str(item.get("setup_family", "")).upper() == setup_family.upper()
        )
    typer.echo("Canonical Setup Recognition Audit")
    for item in rows:
        typer.echo(
            f"- {item.get('setup_family')}: recall={_percent(item.get('recall'))}; "
            f"detections={item.get('canonical_detections')}"
        )


@candidate_research_app.command("timing")
def timing(
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
) -> None:
    rows = _rows(load_candidate_research_payload(output), "timing_metrics")
    counts = Counter(str(item.get("classification")) for item in rows)
    typer.echo("Candidate Timing Audit")
    typer.echo(f"Onsets Evaluated: {len(rows)}")
    for key, value in counts.most_common():
        typer.echo(f"- {key}: {value}")


@candidate_research_app.command("parity")
def parity(
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
) -> None:
    payload = load_candidate_research_payload(output)
    rows = _rows(payload, "pine_candidate_parity")
    typer.echo("Pine Candidate Recognition Parity")
    typer.echo(f"Imported Trade Comparisons: {len(rows)}")
    if not rows:
        typer.echo("Parity Conclusion: unavailable; exact trade-level CSV required")
    else:
        counts = Counter(str(item.get("classification")) for item in rows)
        for key, value in counts.most_common():
            typer.echo(f"- {key}: {value}")


@candidate_research_app.command("variants")
def variants(
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
    variant: Annotated[str | None, typer.Option("--variant")] = None,
    partition: Annotated[str | None, typer.Option("--partition")] = None,
) -> None:
    rows = _filter_variant_rows(
        _rows(load_candidate_research_payload(output), "variant_results"),
        variant=variant,
        partition=partition,
    )
    typer.echo("Candidate Generation Variants")
    for item in rows:
        typer.echo(
            f"- {item.get('variant_id')}/{item.get('partition')}: "
            f"candidates={item.get('candidates')}; "
            f"expectancy={_percent(item.get('forward_expectancy_after_costs'))}; "
            f"pass={item.get('passed')}"
        )


@candidate_research_app.command("validate")
def validate(
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
    variant: Annotated[str | None, typer.Option("--variant")] = None,
) -> None:
    rows = _rows(load_candidate_research_payload(output), "validations")
    if variant is not None:
        rows = tuple(item for item in rows if item.get("variant_id") == variant.upper())
    typer.echo("Chronological Candidate Validation")
    typer.echo("Selection Uses Holdout: No")
    for item in rows:
        typer.echo(
            f"- {item.get('variant_id')}: {item.get('status')}; {item.get('reason')}"
        )


@candidate_research_app.command("zero-candidates")
def zero_candidates(
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
) -> None:
    rows = _rows(load_candidate_research_payload(output), "zero_candidates")
    counts = Counter(str(item.get("explanation")) for item in rows)
    typer.echo("Zero-Candidate Explanations")
    typer.echo(f"Symbols: {len(rows)}")
    for key, value in counts.most_common():
        typer.echo(f"- {key}: {value}")


@candidate_research_app.command("case-study")
def case_study(
    symbol: Annotated[str, typer.Option("--symbol")],
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
) -> None:
    rows = _rows(load_candidate_research_payload(output), "case_studies")
    selected = next(
        (
            item
            for item in rows
            if item.get("requested_symbol") == symbol.upper()
            or item.get("resolved_symbol") == symbol.upper()
        ),
        None,
    )
    if selected is None:
        raise typer.BadParameter(f"case study unavailable for {symbol.upper()}")
    typer.echo(json.dumps(selected, indent=2, sort_keys=True))


@candidate_research_app.command("policy")
def policy(
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
) -> None:
    proposal = _mapping(
        load_candidate_research_payload(output).get("policy_proposal"),
        "policy proposal",
    )
    typer.echo("Candidate Policy Proposal")
    typer.echo(f"Policy ID: {proposal.get('policy_id')}")
    typer.echo(f"Status: {proposal.get('status')}")
    typer.echo(f"Validation: {proposal.get('validation_status')}")
    typer.echo(f"Holdout: {proposal.get('holdout_status')}")
    typer.echo("Automatic Deployment: No")


@candidate_research_app.command("report")
def report(
    database: Annotated[Path, typer.Option("--database")] = settings.database_path,
    acu_directory: Annotated[
        Path, typer.Option("--acu-directory")
    ] = DEFAULT_ACU_DIRECTORY,
    pine_directory: Annotated[Path | None, typer.Option("--pine-directory")] = None,
    output: Annotated[
        Path, typer.Option("--output")
    ] = DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
    start: Annotated[str | None, typer.Option("--start")] = None,
    end: Annotated[str | None, typer.Option("--end")] = None,
    symbol: Annotated[str | None, typer.Option("--symbol")] = None,
    event_family: Annotated[str | None, typer.Option("--event-family")] = None,
    dataset_version: Annotated[
        str, typer.Option("--dataset-version")
    ] = DATASET_VERSION,
    policy_version: Annotated[
        str, typer.Option("--policy-version")
    ] = CANONICAL_POLICY_ID,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    csv_output: Annotated[bool, typer.Option("--csv")] = False,
) -> None:
    if dataset_version != DATASET_VERSION:
        raise typer.BadParameter(f"only {DATASET_VERSION} is available")
    if policy_version != CANONICAL_POLICY_ID:
        raise typer.BadParameter(f"only {CANONICAL_POLICY_ID} is auditable")
    if event_family is not None:
        typer.echo(
            "Event-family filtering applies to artifact views; the validation run "
            "retains all point-in-time families to avoid selection bias."
        )
    with LegacyMarketDataStore(database) as store:
        research = CandidateGenerationResearchEngine().run(
            store=store,
            acu_directory=acu_directory,
            pine_directory=pine_directory,
            start=_date(start),
            end=_date(end),
            symbol=symbol,
        )
    paths = CandidateResearchExporter().export(research, output_directory=output)
    record_candidate_research_experiment(research)
    typer.echo(render_summary(research), nl=False)
    if json_output:
        typer.echo(f"JSON: {output / 'candidate_research.json'}")
    if csv_output:
        typer.echo(f"CSV Artifacts: {sum(path.suffix == '.csv' for path in paths)}")
    typer.echo(f"Artifacts: {output} ({len(paths)} files)")


def _rows(payload: dict[str, object], key: str) -> tuple[dict[str, Any], ...]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise typer.BadParameter(f"invalid candidate research {key} artifact")
    return tuple(_mapping(item, key) for item in value)


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise typer.BadParameter(f"invalid candidate research {label} artifact")
    return {str(key): item for key, item in value.items()}


def _date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter("dates must use YYYY-MM-DD") from error


def _percent(value: object) -> str:
    if value is None:
        return "unavailable"
    from decimal import Decimal

    return f"{Decimal(str(value)) * Decimal('100'):.2f}%"


def _label(value: str) -> str:
    return value.replace("_", " ").title()


def _filter_variant_rows(
    rows: tuple[dict[str, Any], ...],
    *,
    variant: str | None,
    partition: str | None,
) -> tuple[dict[str, Any], ...]:
    return tuple(
        item
        for item in rows
        if (variant is None or item.get("variant_id") == variant.upper())
        and (partition is None or item.get("partition") == partition.upper())
    )


__all__ = ["candidate_research_app"]
