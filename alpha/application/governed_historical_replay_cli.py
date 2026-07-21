"""Application helpers for governed historical replay CLI commands."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from alpha.application.governed_historical_replay import (
    GovernedHistoricalReplayRun,
    GovernedHistoricalReplayService,
    HistoricalReplayExecutor,
    ObservationBuilderFactory,
    export_governed_historical_replay_run,
)
from alpha.candidate_learning import LearningLedgerRepository
from alpha.historical_replay.engine import HistoricalReplayEngine
from alpha.historical_replay.governed_artifacts import load_governed_replay_inputs
from alpha.historical_replay.governed_price_repository import ReplayPriceSource
from alpha.historical_replay.repository import HistoricalReplayRepository
from alpha.market_truth.consumer_repository import MarketTruthPriceRepository


def execute_governed_historical_replay(
    *,
    from_date: object,
    to_date: object,
    identity_artifact: Path,
    corporate_action_artifact: Path,
    learning_repository: LearningLedgerRepository,
    replay_repository: HistoricalReplayRepository | None = None,
    database_path: Path | str | None = None,
    output: Path | None = None,
    source: ReplayPriceSource | None = None,
    executor: HistoricalReplayExecutor | None = None,
    observation_builder_factory: ObservationBuilderFactory | None = None,
) -> GovernedHistoricalReplayRun:
    """Execute one fail-closed governed replay and optionally export proofs."""

    start = _require_date(from_date, "from_date")
    end = _require_date(to_date, "to_date")
    inputs = load_governed_replay_inputs(
        identity_path=identity_artifact,
        corporate_action_path=corporate_action_artifact,
    )
    price_source = source or MarketTruthPriceRepository(database_path=database_path)
    replay_executor = executor or HistoricalReplayEngine(
        replay_repository=replay_repository or HistoricalReplayRepository(),
        learning_repository=learning_repository,
    )
    try:
        run = GovernedHistoricalReplayService(
            source=price_source,
            inputs=inputs,
            executor=replay_executor,
            observation_builder_factory=observation_builder_factory,
        ).run(from_date=start, to_date=end)
        if output is not None:
            export_governed_historical_replay_run(run, output)
        return run
    finally:
        close = getattr(price_source, "close", None)
        if callable(close):
            close_callback = _close_callback(close)
            close_callback()


def render_governed_historical_replay_run(
    run: GovernedHistoricalReplayRun,
) -> tuple[str, ...]:
    """Render a compact deterministic governed replay summary."""

    build = run.observation_build
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
        f"Input Manifest SHA-256: {run.inputs.manifest.manifest_sha256}",
        f"Run SHA-256: {run.run_sha256}",
        "Canonical Replay Enforced: true",
    ]
    lines.extend(
        f"Skipped: {item}" for item in build.skipped_dates[:10]
    )
    return tuple(lines)


def _require_date(value: object, label: str) -> object:
    from datetime import date

    if not isinstance(value, date):
        raise TypeError(f"{label} must be a date")
    return value


def _close_callback(value: object) -> Callable[[], object]:
    if not callable(value):
        raise TypeError("price source close attribute must be callable")
    return value


__all__ = [
    "execute_governed_historical_replay",
    "render_governed_historical_replay_run",
]
