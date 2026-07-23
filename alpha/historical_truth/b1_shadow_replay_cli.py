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
from alpha.historical_truth.b1_shadow_replay import (
    B1ShadowReplayLegResult,
    B1ShadowReplayRunner,
)
from alpha.historical_truth.b1_shadow_universe import (
    B1UniverseFilteredPriceRepository,
    load_b1_shadow_admission,
)
from alpha.historical_truth.replay import HistoricalTruthReplayStore


def _date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument(
        "--historical-truth-snapshots",
        type=Path,
        default=Path("alpha_data/snapshots"),
    )
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

    def raw_leg() -> B1ShadowReplayLegResult:
        source = HistoricalTruthReplayStore(
            database_path=arguments.database,
            snapshot_root=arguments.historical_truth_snapshots,
            start=admission.dependency_start,
            end=admission.dependency_end,
        )
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
            runs: tuple[ReplayRunRecord, ...] = HistoricalReplayEngine(
                replay_repository=raw_replay_repository,
                learning_repository=raw_learning_repository,
            ).run(
                from_date=arguments.start,
                to_date=arguments.end,
                observations=build.observations,
            )
            source_manifest = source.manifest()
            _write_json(
                arguments.output / "raw_observation_manifest.json",
                {
                    "source_dataset_version": source_manifest.dataset_version,
                    "source_first_session": source_manifest.first_session.isoformat(),
                    "source_last_session": source_manifest.last_session.isoformat(),
                    "source_session_count": source_manifest.sessions,
                    "source_row_count": source_manifest.rows,
                    "replay_dates": [item.isoformat() for item in build.replay_dates],
                    "observation_count": len(build.observations),
                    "skipped_dates": list(build.skipped_dates),
                    "admitted_identity_count": len(admission.admitted_security_ids),
                    "production_influence": False,
                },
            )
            return B1ShadowReplayLegResult(
                runs=runs,
                replay_dates=build.replay_dates,
                eligible_security_count=len(admission.admitted_security_ids),
                observation_count=len(build.observations),
                skipped_dates=build.skipped_dates,
            )
        finally:
            source.close()

    def adjusted_leg() -> B1ShadowReplayLegResult:
        source = HistoricalTruthReplayStore(
            database_path=arguments.database,
            snapshot_root=arguments.historical_truth_snapshots,
            start=admission.dependency_start,
            end=admission.dependency_end,
        )
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
            runs: tuple[ReplayRunRecord, ...] = HistoricalReplayEngine(
                replay_repository=adjusted_replay_repository,
                learning_repository=adjusted_learning_repository,
            ).run(
                from_date=arguments.start,
                to_date=arguments.end,
                observations=governed_build.observations,
            )
            return B1ShadowReplayLegResult(
                runs=runs,
                replay_dates=governed_build.replay_dates,
                eligible_security_count=len(admission.admitted_security_ids),
                observation_count=len(governed_build.observations),
                skipped_dates=governed_build.skipped_dates,
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
    print(f"Raw source sessions: {result.raw_summary['session_count']}")
    print(f"Adjusted source sessions: {result.adjusted_summary['session_count']}")
    print(f"Raw executed sessions: {result.raw_summary['executed_session_count']}")
    print(
        "Adjusted executed sessions: "
        f"{result.adjusted_summary['executed_session_count']}"
    )
    print(f"Raw observations: {result.raw_summary['observation_count']}")
    print(f"Adjusted observations: {result.adjusted_summary['observation_count']}")
    print(f"Raw skipped dates: {result.raw_summary['skipped_date_count']}")
    print(f"Adjusted skipped dates: {result.adjusted_summary['skipped_date_count']}")
    print(f"Session sets match: {result.comparison['session_sets_match']}")
    print(
        "Executed session sets match: "
        f"{result.comparison['executed_session_sets_match']}"
    )
    print(f"Universe counts match: {result.comparison['universe_counts_match']}")
    print(
        f"Replay population nonempty: {result.comparison['replay_population_nonempty']}"
    )
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
