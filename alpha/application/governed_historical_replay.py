"""Application service for canonical historical observation and replay runs."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from alpha.historical_replay.governed_artifacts import GovernedReplayInputs
from alpha.historical_replay.governed_factory import (
    GovernedHistoricalObservationBuild,
    GovernedHistoricalObservationFactory,
    HistoricalObservationBuilder,
)
from alpha.historical_replay.governed_price_repository import (
    CanonicalReplayPriceRepository,
    ReplayPriceSource,
)
from alpha.historical_replay.models import ReplayCandidateObservation, ReplayRunRecord
from alpha.recovery.consumer_attestation import export_consumer_attestations

GOVERNED_REPLAY_RUN_CONTRACT_VERSION = "HTR-005-run-v1.0.0"
ObservationBuilderFactory = Callable[
    [CanonicalReplayPriceRepository], HistoricalObservationBuilder
]


class HistoricalReplayExecutor(Protocol):
    """Existing historical replay engine contract used by the application service."""

    def run(
        self,
        *,
        from_date: date,
        to_date: date,
        observations: tuple[ReplayCandidateObservation, ...] = (),
    ) -> tuple[ReplayRunRecord, ...]:
        """Persist replay outcomes for governed observations."""
        ...


@dataclass(frozen=True, slots=True)
class GovernedHistoricalReplayRun:
    """Replay outputs bound to canonical inputs and observation proofs."""

    from_date: date
    to_date: date
    inputs: GovernedReplayInputs
    observation_build: GovernedHistoricalObservationBuild
    replay_runs: tuple[ReplayRunRecord, ...]
    contract_version: str = GOVERNED_REPLAY_RUN_CONTRACT_VERSION
    canonical_replay_enforced: bool = True

    def __post_init__(self) -> None:
        if self.to_date < self.from_date:
            raise ValueError("governed replay end cannot precede start")
        if self.contract_version != GOVERNED_REPLAY_RUN_CONTRACT_VERSION:
            raise ValueError("unsupported governed historical replay contract")
        if not self.canonical_replay_enforced:
            raise ValueError("governed historical replay must be enforced")
        if not self.observation_build.canonical_replay_enforced:
            raise ValueError("governed replay contains an unenforced observation build")
        replay_dates = set(self.observation_build.replay_dates)
        invalid = tuple(
            sorted(
                run.replay_date
                for run in self.replay_runs
                if run.replay_date not in replay_dates
            )
        )
        if invalid:
            rendered = ", ".join(item.isoformat() for item in invalid)
            raise ValueError(f"replay engine emitted ungoverned dates: {rendered}")
        if any(run.data_cutoff_date != run.replay_date for run in self.replay_runs):
            raise ValueError("replay engine emitted a non-point-in-time data cutoff")

    @property
    def run_sha256(self) -> str:
        """Return a deterministic digest excluding runtime and wall-clock fields."""

        payload = self.as_dict(include_digest=False)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def as_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        """Return a stable JSON-compatible run manifest."""

        payload: dict[str, object] = {
            "from_date": self.from_date.isoformat(),
            "to_date": self.to_date.isoformat(),
            "inputs": self.inputs.manifest.as_dict(),
            "observation_build": self.observation_build.as_dict(),
            "replay_runs": [_stable_replay_run(item) for item in self.replay_runs],
            "contract_version": self.contract_version,
            "canonical_replay_enforced": self.canonical_replay_enforced,
        }
        if include_digest:
            payload["run_sha256"] = self.run_sha256
        return payload


@dataclass(slots=True)
class GovernedHistoricalReplayService:
    """Run historical research only through canonical replay repositories."""

    source: ReplayPriceSource
    inputs: GovernedReplayInputs
    executor: HistoricalReplayExecutor
    observation_builder_factory: ObservationBuilderFactory | None = None

    def run(
        self,
        *,
        from_date: date,
        to_date: date,
    ) -> GovernedHistoricalReplayRun:
        """Build governed observations and execute the existing replay engine."""

        if to_date < from_date:
            raise ValueError("to_date must be on or after from_date")
        price_repository = CanonicalReplayPriceRepository(
            self.source,
            self.inputs.identities,
            self.inputs.actions,
        )
        builder = (
            self.observation_builder_factory(price_repository)
            if self.observation_builder_factory is not None
            else None
        )
        observation_build = GovernedHistoricalObservationFactory(
            price_repository=price_repository,
            builder=builder,
        ).build(from_date=from_date, to_date=to_date)
        replay_runs = self.executor.run(
            from_date=from_date,
            to_date=to_date,
            observations=observation_build.observations,
        )
        return GovernedHistoricalReplayRun(
            from_date=from_date,
            to_date=to_date,
            inputs=self.inputs,
            observation_build=observation_build,
            replay_runs=replay_runs,
        )


def export_governed_historical_replay_run(
    run: GovernedHistoricalReplayRun,
    output: Path,
) -> tuple[Path, ...]:
    """Export deterministic run, read, input, and consumer proof artifacts."""

    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "governed_historical_replay_run.json"
    input_path = output / "governed_replay_inputs.json"
    reads_path = output / "governed_replay_reads.csv"
    report_path = output / "governed_historical_replay_run.md"
    manifest_path.write_text(
        json.dumps(run.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    input_path.write_text(
        json.dumps(run.inputs.manifest.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_reads_csv(run, reads_path)
    report_path.write_text(_render_run(run), encoding="utf-8")
    attestations = run.observation_build.consumer_attestations
    consumer_paths = (
        export_consumer_attestations(attestations, output) if attestations else ()
    )
    return (
        manifest_path,
        input_path,
        reads_path,
        report_path,
        *consumer_paths,
    )


def _stable_replay_run(run: ReplayRunRecord) -> dict[str, object]:
    return {
        "replay_run_id": run.replay_run_id,
        "replay_date": run.replay_date.isoformat(),
        "symbols_scanned": run.symbols_scanned,
        "candidates_stored": run.candidates_stored,
        "emitted_decisions": run.emitted_decisions,
        "approved_recommendations": run.approved_recommendations,
        "market_regime": run.market_regime,
        "long_trade_permission": run.long_trade_permission,
        "data_cutoff_date": run.data_cutoff_date.isoformat(),
        "outcome_windows_available": list(run.outcome_windows_available),
        "data_gaps": run.data_gaps,
    }


def _write_reads_csv(run: GovernedHistoricalReplayRun, path: Path) -> None:
    rows = [item.as_dict() for item in run.observation_build.repository_reads]
    fieldnames = tuple(rows[0]) if rows else ("operation",)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(value) for key, value in row.items()})


def _csv_value(value: object) -> object:
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def _render_run(run: GovernedHistoricalReplayRun) -> str:
    observations = run.observation_build
    lines = [
        "# Governed Historical Replay Run",
        "",
        f"- From: `{run.from_date.isoformat()}`",
        f"- To: `{run.to_date.isoformat()}`",
        f"- Replay Dates: `{len(observations.replay_dates)}`",
        f"- Observations: `{len(observations.observations)}`",
        f"- Replay Runs: `{len(run.replay_runs)}`",
        f"- Repository Reads: `{len(observations.repository_reads)}`",
        f"- Consumer Attestations: `{len(observations.consumer_attestations)}`",
        f"- Input Manifest SHA-256: `{run.inputs.manifest.manifest_sha256}`",
        f"- Observation SHA-256: `{observations.run_sha256}`",
        f"- Run SHA-256: `{run.run_sha256}`",
        "- Canonical Replay Enforced: `True`",
        "",
        "## Replay Results",
        "",
    ]
    if not run.replay_runs:
        lines.append("- No replay runs were emitted.")
    else:
        for item in run.replay_runs:
            lines.append(
                "- "
                f"`{item.replay_date.isoformat()}`: "
                f"candidates={item.candidates_stored}, "
                f"decisions={item.emitted_decisions}, "
                f"approved={item.approved_recommendations}, "
                f"gaps={item.data_gaps}"
            )
    return "\n".join(lines) + "\n"


__all__ = [
    "GOVERNED_REPLAY_RUN_CONTRACT_VERSION",
    "GovernedHistoricalReplayRun",
    "GovernedHistoricalReplayService",
    "HistoricalReplayExecutor",
    "ObservationBuilderFactory",
    "export_governed_historical_replay_run",
]
