"""Fast governed RAW-versus-ADJUSTED population parity audit for HTR-010B1."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from alpha.historical_replay.governed_artifacts import load_governed_replay_inputs
from alpha.historical_replay.governed_price_repository import (
    CanonicalReplayPriceRepository,
)
from alpha.historical_truth.b1_shadow_replay import (
    POPULATION_PARITY_SCOPE,
    B1ShadowReplayLegResult,
    B1ShadowReplayRunner,
)
from alpha.historical_truth.b1_shadow_universe import (
    B1IdentityFilteredPriceRepository,
    load_b1_shadow_admission,
)
from alpha.historical_truth.replay import HistoricalTruthReplayStore

_CONSOLE = Console()


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
        raise ValueError("population audit start does not match B1H contract")
    if arguments.end != admission.replay_end:
        raise ValueError("population audit end does not match B1H contract")

    governed_inputs = load_governed_replay_inputs(
        identity_path=arguments.identity_artifact,
        corporate_action_path=arguments.corporate_action_artifact,
    )
    arguments.output.mkdir(parents=True, exist_ok=True)

    with _CONSOLE.status(
        "[bold cyan]Loading and verifying immutable Historical Truth snapshots..."
    ):
        source = HistoricalTruthReplayStore(
            database_path=arguments.database,
            snapshot_root=arguments.historical_truth_snapshots,
            start=admission.dependency_start,
            end=admission.dependency_end,
        )

    try:
        source_dates = source.find_trade_dates(
            start=arguments.start,
            end=arguments.end,
        )
        if not source_dates:
            raise ValueError("population parity audit found no replay sessions")

        governed_source = B1IdentityFilteredPriceRepository(
            source,
            governed_inputs.identities,
            admission.admitted_security_ids,
        )
        raw_repository = governed_source
        adjusted_repository = CanonicalReplayPriceRepository(
            governed_source,
            governed_inputs.identities,
            governed_inputs.actions,
        )

        raw_counts: list[tuple[date, int]] = []
        adjusted_counts: list[tuple[date, int]] = []
        raw_empty: list[str] = []
        adjusted_empty: list[str] = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=_CONSOLE,
            refresh_per_second=10,
        ) as progress:
            task = progress.add_task(
                "Comparing governed session populations",
                total=len(source_dates) * 2,
            )
            for replay_date in source_dates:
                progress.update(task, description=f"RAW {replay_date.isoformat()}")
                raw_frame = raw_repository.find_by_trade_date(replay_date)
                raw_count = len(raw_frame.index)
                raw_counts.append((replay_date, raw_count))
                if raw_count == 0:
                    raw_empty.append(
                        f"{replay_date.isoformat()}: no admitted RAW observations"
                    )
                progress.advance(task)

                progress.update(
                    task,
                    description=f"ADJUSTED {replay_date.isoformat()}",
                )
                adjusted_frame = adjusted_repository.find_by_trade_date(replay_date)
                adjusted_count = len(adjusted_frame.index)
                adjusted_counts.append((replay_date, adjusted_count))
                if adjusted_count == 0:
                    adjusted_empty.append(
                        f"{replay_date.isoformat()}: no admitted ADJUSTED observations"
                    )
                progress.advance(task)

            progress.update(task, description="Population comparison complete")

        raw_leg = B1ShadowReplayLegResult(
            runs=(),
            replay_dates=source_dates,
            eligible_security_count=len(admission.admitted_security_ids),
            observation_count=0,
            skipped_dates=tuple(raw_empty),
            analysis_scope=POPULATION_PARITY_SCOPE,
            session_observation_counts=tuple(raw_counts),
        )
        adjusted_leg = B1ShadowReplayLegResult(
            runs=(),
            replay_dates=source_dates,
            eligible_security_count=len(admission.admitted_security_ids),
            observation_count=0,
            skipped_dates=tuple(adjusted_empty),
            analysis_scope=POPULATION_PARITY_SCOPE,
            session_observation_counts=tuple(adjusted_counts),
        )
        result = B1ShadowReplayRunner(
            raw_leg=lambda: raw_leg,
            adjusted_leg=lambda: adjusted_leg,
            admission_contract=admission.as_dict(),
        ).run()

        with _CONSOLE.status("[bold cyan]Writing signed parity artifacts..."):
            B1ShadowReplayRunner.export(result, arguments.output)
            _write_json(
                arguments.output / "htr010b1_population_parity_manifest.json",
                {
                    "analysis_scope": POPULATION_PARITY_SCOPE,
                    "dependency_start": admission.dependency_start.isoformat(),
                    "dependency_end": admission.dependency_end.isoformat(),
                    "replay_start": admission.replay_start.isoformat(),
                    "replay_end": admission.replay_end.isoformat(),
                    "source_session_count": len(source_dates),
                    "admitted_identity_count": len(admission.admitted_security_ids),
                    "raw_eligible_observation_count": sum(
                        count for _date, count in raw_counts
                    ),
                    "adjusted_eligible_observation_count": sum(
                        count for _date, count in adjusted_counts
                    ),
                    "decision_metrics_evaluated": False,
                    "production_influence": False,
                },
            )

        report = result.as_dict()
        _CONSOLE.print("[bold]HTR-010B1 Fast Governed Population Parity[/bold]")
        _CONSOLE.print(f"Analysis scope: {POPULATION_PARITY_SCOPE}")
        _CONSOLE.print(f"Admitted identities: {len(admission.admitted_security_ids)}")
        _CONSOLE.print(f"RAW sessions: {result.raw_summary['session_count']}")
        _CONSOLE.print(f"ADJUSTED sessions: {result.adjusted_summary['session_count']}")
        _CONSOLE.print(
            "RAW eligible observations: "
            f"{result.raw_summary['eligible_observation_count']}"
        )
        _CONSOLE.print(
            "ADJUSTED eligible observations: "
            f"{result.adjusted_summary['eligible_observation_count']}"
        )
        _CONSOLE.print(
            "Session observation counts match: "
            f"{result.comparison['session_observation_counts_match']}"
        )
        _CONSOLE.print(
            "Unexplained divergences: "
            f"{result.comparison['unexplained_divergence_count']}"
        )
        _CONSOLE.print(f"Report SHA256: {report['report_sha256']}")
        _CONSOLE.print("Decision metrics evaluated: false")
        _CONSOLE.print("PRODUCTION_INFLUENCE=false")
        return int(result.comparison["unexplained_divergence_count"] != 0)
    finally:
        source.close()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
