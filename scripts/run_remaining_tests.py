"""Run tests not assigned to named Project Alpha CI shards."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_EXCLUDED = {
    "historical_truth",
    "historical_replay",
    "recovery",
    "decision_intelligence",
    "decision_lifecycle",
    "decision_orchestrator",
    "market",
    "market_intelligence",
    "market_truth",
    "portfolio",
    "portfolio_intelligence",
    "backtest",
    "execution",
    "costs",
    "research",
    "trading_signals",
    "strategy_lab",
    "strategy_discovery",
    "setup_discovery",
    "candidate_learning",
}


def main() -> int:
    roots = tuple(
        path.as_posix()
        for path in sorted(Path("tests").iterdir())
        if path.name not in _EXCLUDED
    )
    return subprocess.call([sys.executable, "-m", "pytest", "-q", *roots])


if __name__ == "__main__":
    raise SystemExit(main())
