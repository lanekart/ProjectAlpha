"""CLI for governed HTR-010B1 raw-versus-adjusted shadow replay."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from alpha.application.governed_historical_replay_cli import (
    execute_governed_historical_replay,
)
from alpha.candidate_learning import NightlyLearningLoop
from alpha.historical_replay import (
    HistoricalObservationFactory,
    HistoricalReplayEngine,
    HistoricalReplayRepository,
)
from alpha.historical_replay.models import ReplayRunRecord
from alpha.historical_truth.b1_shadow_replay import B1ShadowReplayRunner
from alpha.market_truth.consumer_repository import MarketTruthPriceRepository


def _date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--identity-artifact", type=Path, required=True)
    parser.add_argument("--corporate-action-artifact", type=Path, required=True)
    parser.add_argument("--start", type=_date, required=True)
    parser.add_argument("--end", type=_date, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    learning_repository = NightlyLearningLoop.from_path().repository

    def raw_leg() -> tuple[ReplayRunRecord, ...]:
        source = MarketTruthPriceRepository(database_path=arguments.database)
        try:
            build = HistoricalObservationFactory(price_repository=source).build(
                from_date=arguments.start,
                to_date=arguments.end,
            )
            return HistoricalReplayEngine(
                replay_repository=HistoricalReplayRepository(),
                learning_repository=learning_repository,
            ).run(
                from_date=arguments.start,
                to_date=arguments.end,
                observations=build.observations,
            )
        finally:
            source.close()

    def adjusted_leg() -> tuple[ReplayRunRecord, ...]:
        run = execute_governed_historical_replay(
            from_date=arguments.start,
            to_date=arguments.end,
            identity_artifact=arguments.identity_artifact,
            corporate_action_artifact=arguments.corporate_action_artifact,
            learning_repository=learning_repository,
            replay_repository=HistoricalReplayRepository(),
            database_path=arguments.database,
            output=arguments.output / "adjusted_governed_replay",
        )
        return run.replay_runs

    result = B1ShadowReplayRunner(
        raw_leg=raw_leg,
        adjusted_leg=adjusted_leg,
    ).run()
    B1ShadowReplayRunner.export(result, arguments.output)
    report = result.as_dict()
    print("HTR-010B1 Governed Shadow Replay")
    print(f"Raw sessions: {result.raw_summary['session_count']}")
    print(f"Adjusted sessions: {result.adjusted_summary['session_count']}")
    print(
        "Unexplained divergences: "
        f"{result.comparison['unexplained_divergence_count']}"
    )
    print(f"Report SHA256: {report['report_sha256']}")
    print("PRODUCTION_INFLUENCE=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
