"""Application helpers for governed historical replay CLI commands."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import cast

from alpha.application.governed_historical_replay import (
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
from alpha.historical_replay.repository import HistoricalReplayRepository
from alpha.market_truth.consumer_repository import MarketTruthPriceRepository


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
    replay_executor = executor or HistoricalReplayEngine(
        replay_repository=replay_repository or HistoricalReplayRepository(),
        learning_repository=learning_repository,
    )
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
    else:
        if resolved_inventory is None:
            resolved_inventory = ()

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
        close = getattr(price_source, "close", None)
        if close is not None:
            if not callable(close):
                raise TypeError("price source close attribute must be callable")
            cast(Callable[[], object], close)()


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


__all__ = [
    "execute_governed_historical_replay",
    "render_governed_historical_replay_run",
]
