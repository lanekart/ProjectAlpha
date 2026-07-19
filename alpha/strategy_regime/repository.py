from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from alpha.strategy_regime.models import StrategyRegimeBacktestRun

DEFAULT_STRATEGY_REGIME_PATH = Path(".alpha/strategy_regime_backtests.json")


class StrategyRegimeBacktestRepository:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_strategy_regime_path(path)

    def save_run(self, run: StrategyRegimeBacktestRun) -> None:
        runs = {item.run_id: item for item in self.load_runs()}
        runs[run.run_id] = run
        self._write(tuple(runs.values()))

    def latest_run(self) -> StrategyRegimeBacktestRun | None:
        runs = self.load_runs()
        if not runs:
            return None
        return max(runs, key=lambda run: (run.generated_at, run.run_id))

    def load_runs(self) -> tuple[StrategyRegimeBacktestRun, ...]:
        payload = self._read()
        runs = payload.get("runs", [])
        if not isinstance(runs, list):
            return ()
        return tuple(
            sorted(
                (
                    StrategyRegimeBacktestRun.from_dict(item)
                    for item in runs
                    if isinstance(item, dict)
                ),
                key=lambda run: (run.generated_at, run.run_id),
            )
        )

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"runs": []}
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            return {"runs": []}
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {"runs": []}

    def _write(self, runs: tuple[StrategyRegimeBacktestRun, ...]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "runs": [
                run.as_dict()
                for run in sorted(
                    runs,
                    key=lambda item: (item.generated_at, item.run_id),
                )
            ]
        }
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(self.path)


def resolve_strategy_regime_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.environ.get("ALPHA_STRATEGY_REGIME_BACKTESTS")
    if configured:
        return Path(configured)
    return DEFAULT_STRATEGY_REGIME_PATH


__all__ = [
    "DEFAULT_STRATEGY_REGIME_PATH",
    "StrategyRegimeBacktestRepository",
    "resolve_strategy_regime_path",
]
