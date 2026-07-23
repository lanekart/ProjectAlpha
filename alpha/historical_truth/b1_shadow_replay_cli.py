"""CLI for governed HTR-010B1 raw-versus-adjusted shadow replay."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from alpha.candidate_learning.repository import LearningLedgerRepository
from alpha.historical_replay import (
    HistoricalReplayEngine,
    HistoricalReplayRepository,
)
from alpha.historical_replay.governed_artifacts import load_governed_replay_inputs
from alpha.historical_replay.governed_factory import (
    GovernedHistoricalObservationFactory,
    create_historical_observation_builder,
)
from alpha.historical_replay.governed_price_repository import (
    CanonicalReplayPriceRepository,
)
from alpha.historical_replay.models import ReplayRunRecord
from alpha.historical_truth.b1_shadow_replay import B1ShadowReplayRunner
from alpha.historical_truth.b1_shadow_universe import (
    B1UniverseFilteredPriceRepository,
    load_b1_shadow_admission,
)
from alpha.market_truth.consumer_repository import MarketTruthPriceRepository


def _date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--identity-artifact", type=Path, required=True)
    parser.add_argument("--corporate-action-artifact", type=Path, required=True)
    parser.add_argument("--admission-contract", type=Path, required=True)
    parser.add_argument("--identity-admission", type=Path, required=True)
    parser.add_argument("--raw-universe", type=Path, required=True)
    parser.add_argument("--adjusted-universe", type=Path, required=True)
    parser.add_argument("--start", type=_date, required=True)
    parser.add_argument("--end", type=_date, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    admission = load_b1_shadow_admission(
        contract_path=arguments.admission_contract,
        identity_admission_path=arguments.identity_admission,
        raw_universe_path=arguments.raw_universe,
        adjusted_universe_path=arguments.adjusted_universe,
    )
    if arguments.start != admission.replay_start:
        raise ValueError("shadow replay start does not match B1H admission contract")
    if arguments.end != admission.replay_end:
        raise ValueError("shadow replay end does not match B1H admission contract")

    governed_inputs = load_governed_replay_inputs(
        identity_path=arguments.identity_artifact,
        corporate_action_path=arguments.corporate_action_artifact,
    )
    arguments.output.mkdir(parents=True, exist_ok=True)
    raw_learning_repository = LearningLedgerRepository(
        arguments.output / "raw_learning_ledger.json"
    )
    adjusted_learning_repository = LearningLedgerRepository(
        arguments.output / "adjusted_learning_ledger.json"
    )
    raw_replay_repository = HistoricalReplayRepository(
        arguments.output / "raw_replay_ledger.json"
    )
    adjusted_replay_repository = HistoricalReplayRepository(
        arguments.output / "adjusted_replay_ledger.json"
    )

    def raw_leg() -> tuple[ReplayRunRecord, ...]:
        source = MarketTruthPriceRepository(database_path=arguments.database)
        try:
            filtered = B1UniverseFilteredPriceRepository(
                source,
                admission.admitted_symbols,
            )
            build = create_historical_observation_builder(
                price_repository=filtered
            ).build(
                from_date=arguments.start,
                to_date=arguments.end,
            )
            return HistoricalReplayEngine(
                replay_repository=raw_replay_repository,
                learning_repository=raw_learning_repository,
            ).run(
                from_date=arguments.start,
                to_date=arguments.end,
                observations=build.observations,
            )
        finally:
            source.close()

    def adjusted_leg() -> tuple[ReplayRunRecord, ...]:
        source = MarketTruthPriceRepository(database_path=arguments.database)
        try:
            canonical = CanonicalReplayPriceRepository(
                source,
                governed_inputs.identities,
                governed_inputs.actions,
            )
            filtered_builder = create_historical_observation_builder(
                price_repository=B1UniverseFilteredPriceRepository(
                    canonical,
                    admission.admitted_symbols,
                )
            )
            governed_build = GovernedHistoricalObservationFactory(
                price_repository=canonical,
                builder=filtered_builder,
            ).build(
                from_date=arguments.start,
                to_date=arguments.end,
            )
            governed_output = arguments.output / "adjusted_governed_replay"
            governed_output.mkdir(parents=True, exist_ok=True)
            _write_json(
                governed_output / "governed_input_manifest.json",
                governed_inputs.manifest.as_dict(),
            )
            _write_json(
                governed_output / "governed_observation_manifest.json",
                governed_build.as_dict(),
            )
            return HistoricalReplayEngine(
                replay_repository=adjusted_replay_repository,
                learning_repository=adjusted_learning_repository,
            ).run(
                from_date=arguments.start,
                to_date=arguments.end,
                observations=governed_build.observations,
            )
        finally:
            source.close()

    result = B1ShadowReplayRunner(
        raw_leg=raw_leg,
        adjusted_leg=adjusted_leg,
        admission_contract=admission.as_dict(),
    ).run()
    B1ShadowReplayRunner.export(result, arguments.output)
    report = result.as_dict()
    print("HTR-010B1 Governed Shadow Replay")
    print(f"Admitted identities: {len(admission.admitted_security_ids)}")
    print(f"Raw sessions: {result.raw_summary['session_count']}")
    print(f"Adjusted sessions: {result.adjusted_summary['session_count']}")
    print(f"Session sets match: {result.comparison['session_sets_match']}")
    print(f"Universe counts match: {result.comparison['universe_counts_match']}")
    print(
        f"Unexplained divergences: {result.comparison['unexplained_divergence_count']}"
    )
    print(f"Admission SHA256: {admission.admission_contract_sha256}")
    print(f"Report SHA256: {report['report_sha256']}")
    print("PRODUCTION_INFLUENCE=false")
    return 0


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
