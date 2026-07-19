from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from alpha.historical_replay.models import ReplayRunRecord, ReplaySummary

DEFAULT_REPLAY_LEDGER_PATH = Path(".alpha/historical_replay_ledger.json")


class HistoricalReplayRepository:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_replay_ledger_path(path)

    def save_runs(self, runs: tuple[ReplayRunRecord, ...]) -> int:
        existing = {run.replay_run_id: run for run in self.load_runs()}
        inserted = 0
        for run in runs:
            if run.replay_run_id not in existing:
                inserted += 1
            existing[run.replay_run_id] = run
        self._write(tuple(existing.values()))
        return inserted

    def load_runs(self) -> tuple[ReplayRunRecord, ...]:
        payload = self._read()
        runs = payload.get("runs", [])
        if not isinstance(runs, list):
            return ()
        return tuple(
            sorted(
                (
                    ReplayRunRecord.from_dict(run)
                    for run in runs
                    if isinstance(run, dict)
                ),
                key=lambda run: run.replay_date,
            )
        )

    def summary(self) -> ReplaySummary:
        runs = self.load_runs()
        return ReplaySummary(
            total_runs=len(runs),
            symbols_scanned=sum(run.symbols_scanned for run in runs),
            candidates_stored=sum(run.candidates_stored for run in runs),
            emitted_decisions=sum(run.emitted_decisions for run in runs),
            approved_recommendations=sum(run.approved_recommendations for run in runs),
            data_gaps=sum(run.data_gaps for run in runs),
            first_replay_date=runs[0].replay_date if runs else None,
            last_replay_date=runs[-1].replay_date if runs else None,
        )

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"runs": []}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"runs": []}

    def _write(self, runs: tuple[ReplayRunRecord, ...]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"runs": [run.as_dict() for run in runs]},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


def resolve_replay_ledger_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.environ.get("ALPHA_HISTORICAL_REPLAY_LEDGER")
    if configured:
        return Path(configured)
    return DEFAULT_REPLAY_LEDGER_PATH


__all__ = [
    "DEFAULT_REPLAY_LEDGER_PATH",
    "HistoricalReplayRepository",
    "resolve_replay_ledger_path",
]
