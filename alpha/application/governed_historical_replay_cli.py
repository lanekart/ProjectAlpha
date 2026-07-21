"""Application helpers for governed historical replay CLI commands."""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import cast

from alpha.application.governed_historical_replay import (
    GovernedHistoricalReplayAssessment,
    GovernedHistoricalReplayRun,
    GovernedHistoricalReplayService,
    HistoricalReplayExecutor,
    ObservationBuilderFactory,
    export_governed_historical_replay_run,
)
from alpha.candidate_learning import LearningLedgerRepository
from alpha.historical_replay.coverage_readiness import (
    HistoricalReplayCoverageEvidence,
    build_historical_replay_coverage_evidence,
)
from alpha.historical_replay.engine import HistoricalReplayEngine
from alpha.historical_replay.governed_artifacts import load_governed_replay_inputs
from alpha.historical_replay.governed_price_repository import ReplayPriceSource
from alpha.historical_replay.inventory_readiness import (
    HistoricalTruthInventoryEvidence,
    build_historical_truth_inventory_evidence_for_range,
)
from alpha.historical_replay.models import ReplayCandidateObservation, ReplayRunRecord
from alpha.historical_replay.repository import HistoricalReplayRepository
from alpha.market_truth.consumer_repository import MarketTruthPriceRepository
from alpha.recovery.consumer_attestation import export_consumer_attestations


class _DiagnosticOnlyExecutor:
    """Sentinel proving diagnostic assessment cannot execute replay."""

    def run(
        self,
        *,
        from_date: date,
        to_date: date,
        observations: tuple[ReplayCandidateObservation, ...] = (),
    ) -> tuple[ReplayRunRecord, ...]:
        del from_date, to_date, observations
        raise RuntimeError("diagnostic readiness assessment invoked replay executor")


def execute_governed_historical_replay(
    *,
    from_date: date,
    to_date: date,
    identity_artifact: Path,
    corporate_action_artifact: Path,
    learning_repository: LearningLedgerRepository,
    replay_repository: HistoricalReplayRepository | None = None,
    database_path: Path | str | None = None,
    snapshots_path: Path | None = None,
    output: Path | None = None,
    source: ReplayPriceSource | None = None,
    executor: HistoricalReplayExecutor | None = None,
    inventory_evidence: tuple[HistoricalTruthInventoryEvidence, ...] | None = None,
    coverage_evidence: HistoricalReplayCoverageEvidence | None = None,
    observation_builder_factory: ObservationBuilderFactory | None = None,
) -> GovernedHistoricalReplayRun:
    """Execute one fail-closed governed replay and optionally export proofs."""

    inputs = load_governed_replay_inputs(
        identity_path=identity_artifact,
        corporate_action_path=corporate_action_artifact,
    )
    price_source = source or MarketTruthPriceRepository(database_path=database_path)
    resolved_inventory, resolved_coverage = _resolve_readiness_evidence(
        price_source=price_source,
        from_date=from_date,
        to_date=to_date,
        snapshots_path=snapshots_path,
        inventory_evidence=inventory_evidence,
        coverage_evidence=coverage_evidence,
    )
    replay_executor = executor or HistoricalReplayEngine(
        replay_repository=replay_repository or HistoricalReplayRepository(),
        learning_repository=learning_repository,
    )
    try:
        run = GovernedHistoricalReplayService(
            source=price_source,
            inputs=inputs,
            executor=replay_executor,
            inventory_evidence=resolved_inventory,
            coverage_evidence=resolved_coverage,
            observation_builder_factory=observation_builder_factory,
        ).run(from_date=from_date, to_date=to_date)
        if output is not None:
            export_governed_historical_replay_run(run, output)
        return run
    finally:
        _close_price_source(price_source)


def assess_governed_historical_replay(
    *,
    from_date: date,
    to_date: date,
    identity_artifact: Path,
    corporate_action_artifact: Path,
    database_path: Path | str | None = None,
    snapshots_path: Path | None = None,
    output: Path | None = None,
    source: ReplayPriceSource | None = None,
    inventory_evidence: tuple[HistoricalTruthInventoryEvidence, ...] | None = None,
    coverage_evidence: HistoricalReplayCoverageEvidence | None = None,
    observation_builder_factory: ObservationBuilderFactory | None = None,
) -> GovernedHistoricalReplayAssessment:
    """Assess governed replay readiness without invoking the replay executor."""

    inputs = load_governed_replay_inputs(
        identity_path=identity_artifact,
        corporate_action_path=corporate_action_artifact,
    )
    price_source = source or MarketTruthPriceRepository(database_path=database_path)
    resolved_inventory, resolved_coverage = _resolve_readiness_evidence(
        price_source=price_source,
        from_date=from_date,
        to_date=to_date,
        snapshots_path=snapshots_path,
        inventory_evidence=inventory_evidence,
        coverage_evidence=coverage_evidence,
    )
    try:
        assessment = GovernedHistoricalReplayService(
            source=price_source,
            inputs=inputs,
            executor=_DiagnosticOnlyExecutor(),
            inventory_evidence=resolved_inventory,
            coverage_evidence=resolved_coverage,
            observation_builder_factory=observation_builder_factory,
        ).assess(from_date=from_date, to_date=to_date)
        if output is not None:
            export_governed_historical_replay_assessment(assessment, output)
        return assessment
    finally:
        _close_price_source(price_source)


def export_governed_historical_replay_assessment(
    assessment: GovernedHistoricalReplayAssessment,
    output: Path,
) -> tuple[Path, ...]:
    """Export deterministic diagnostic readiness evidence without execution."""

    output.mkdir(parents=True, exist_ok=True)
    assessment_path = output / "historical_replay_readiness_assessment.json"
    readiness_path = output / "historical_replay_readiness.json"
    input_path = output / "governed_replay_inputs.json"
    reads_path = output / "governed_replay_reads.csv"
    report_path = output / "historical_replay_readiness_assessment.md"

    assessment_path.write_text(
        json.dumps(assessment.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    readiness_path.write_text(
        json.dumps(assessment.readiness.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    input_manifest = assessment.inputs.manifest.as_dict()
    input_path.write_text(
        json.dumps(input_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_assessment_reads_csv(assessment, reads_path)
    report_path.write_text(
        _render_governed_historical_replay_assessment_markdown(assessment),
        encoding="utf-8",
    )
    attestations = assessment.observation_build.consumer_attestations
    consumer_paths = (
        export_consumer_attestations(attestations, output) if attestations else ()
    )
    return (
        assessment_path,
        readiness_path,
        input_path,
        reads_path,
        report_path,
        *consumer_paths,
    )


def render_governed_historical_replay_assessment(
    assessment: GovernedHistoricalReplayAssessment,
) -> tuple[str, ...]:
    """Render a compact diagnostic readiness summary."""

    readiness = assessment.readiness
    coverage = readiness.coverage_evidence
    lines = [
        "Historical Replay Readiness Assessment",
        f"From: {assessment.from_date.isoformat()}",
        f"To: {assessment.to_date.isoformat()}",
        f"Status: {readiness.status.value}",
        f"Blockers: {len(readiness.blockers)}",
        f"Replay Dates: {len(assessment.observation_build.replay_dates)}",
        f"Skipped Dates: {len(assessment.observation_build.skipped_dates)}",
        f"Inventory Years: {len(readiness.inventory_evidence)}",
        f"Warm-up Sessions: {coverage.observed_warmup_sessions if coverage else 0}",
        f"Outcome Sessions: {coverage.observed_outcome_sessions if coverage else 0}",
        f"Eligible Securities: {coverage.eligible_security_count if coverage else 0}",
        f"Readiness SHA-256: {readiness.readiness_sha256}",
        "Executor Invoked: false",
        "Diagnostic Only: true",
    ]
    lines.extend(f"Blocker: {item.value}" for item in readiness.blockers)
    return tuple(lines)


def render_governed_historical_replay_run(
    run: GovernedHistoricalReplayRun,
) -> tuple[str, ...]:
    """Render a compact deterministic governed replay summary."""

    build = run.observation_build
    coverage = run.readiness.coverage_evidence
    lines = [
        "Governed Historical Replay",
        f"From: {run.from_date.isoformat()}",
        f"To: {run.to_date.isoformat()}",
        f"Replay Dates: {len(build.replay_dates)}",
        f"Observations: {len(build.observations)}",
        f"Replay Runs: {len(run.replay_runs)}",
        f"Skipped Dates: {len(build.skipped_dates)}",
        f"Repository Reads: {len(build.repository_reads)}",
        f"Consumer Attestations: {len(build.consumer_attestations)}",
        f"Readiness Status: {run.readiness.status.value}",
        f"Inventory Years: {len(run.readiness.inventory_evidence)}",
        f"Warm-up Sessions: {coverage.observed_warmup_sessions if coverage else 0}",
        f"Outcome Sessions: {coverage.observed_outcome_sessions if coverage else 0}",
        f"Eligible Securities: {coverage.eligible_security_count if coverage else 0}",
        f"Input Manifest SHA-256: {run.inputs.manifest.manifest_sha256}",
        f"Run SHA-256: {run.run_sha256}",
        "Canonical Replay Enforced: true",
    ]
    lines.extend(f"Skipped: {item}" for item in build.skipped_dates[:10])
    return tuple(lines)


def _resolve_readiness_evidence(
    *,
    price_source: ReplayPriceSource,
    from_date: date,
    to_date: date,
    snapshots_path: Path | None,
    inventory_evidence: tuple[HistoricalTruthInventoryEvidence, ...] | None,
    coverage_evidence: HistoricalReplayCoverageEvidence | None,
) -> tuple[
    tuple[HistoricalTruthInventoryEvidence, ...],
    HistoricalReplayCoverageEvidence | None,
]:
    resolved_inventory = inventory_evidence
    resolved_coverage = coverage_evidence
    if isinstance(price_source, MarketTruthPriceRepository):
        if resolved_inventory is None:
            resolved_inventory = build_historical_truth_inventory_evidence_for_range(
                database=price_source.database_path,
                snapshots=snapshots_path,
                from_date=from_date,
                to_date=to_date,
            )
        if resolved_coverage is None:
            resolved_coverage = build_historical_replay_coverage_evidence(
                database=price_source.database_path,
                from_date=from_date,
                to_date=to_date,
            )
    elif resolved_inventory is None:
        resolved_inventory = ()
    return resolved_inventory, resolved_coverage


def _write_assessment_reads_csv(
    assessment: GovernedHistoricalReplayAssessment,
    path: Path,
) -> None:
    rows = [item.as_dict() for item in assessment.observation_build.repository_reads]
    fieldnames = tuple(rows[0]) if rows else ("operation",)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, sort_keys=True, separators=(",", ":"))
                    if isinstance(value, (list, dict))
                    else value
                    for key, value in row.items()
                }
            )


def _render_governed_historical_replay_assessment_markdown(
    assessment: GovernedHistoricalReplayAssessment,
) -> str:
    readiness = assessment.readiness
    lines = [
        "# Historical Replay Readiness Assessment",
        "",
        "**DIAGNOSTIC_ONLY=true / EXECUTOR_INVOKED=false**",
        "",
        f"- From: `{assessment.from_date.isoformat()}`",
        f"- To: `{assessment.to_date.isoformat()}`",
        f"- Status: `{readiness.status.value}`",
        f"- Readiness SHA-256: `{readiness.readiness_sha256}`",
        f"- Replay Dates: `{len(assessment.observation_build.replay_dates)}`",
        f"- Skipped Dates: `{len(assessment.observation_build.skipped_dates)}`",
        f"- Inventory Years: `{len(readiness.inventory_evidence)}`",
        "",
        "## Blockers",
        "",
    ]
    if readiness.blockers:
        lines.extend(f"- `{item.value}`" for item in readiness.blockers)
    else:
        lines.append("- None. The assessed inputs are ready for governed execution.")
    return "\n".join(lines) + "\n"


def _close_price_source(price_source: ReplayPriceSource) -> None:
    close = getattr(price_source, "close", None)
    if close is None:
        return
    if not callable(close):
        raise TypeError("price source close attribute must be callable")
    cast(Callable[[], object], close)()


__all__ = [
    "assess_governed_historical_replay",
    "execute_governed_historical_replay",
    "export_governed_historical_replay_assessment",
    "render_governed_historical_replay_assessment",
    "render_governed_historical_replay_run",
]
