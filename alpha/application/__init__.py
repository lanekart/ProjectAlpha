"""
Application service layer.

This package contains orchestration logic that coordinates
downloaders, pipelines, repositories, and other domain services.

The CLI should depend only on this layer.
"""

from alpha.application.backtest import (
    BacktestApplicationService,
    BacktestRun,
    BacktestSummary,
)
from alpha.application.governed_replay_backtest import (
    CanonicalReplayIngestionService,
    GovernedReplayBacktestRun,
    GovernedReplayBacktestService,
    export_governed_replay_backtest_attestations,
)
from alpha.application.runtime import ProjectAlphaRuntime
from alpha.application.runtime_models import (
    RuntimeMetadata,
    RuntimeMode,
    RuntimeResult,
    RuntimeStatus,
)

__all__ = [
    "BacktestApplicationService",
    "BacktestRun",
    "BacktestSummary",
    "CanonicalReplayIngestionService",
    "GovernedReplayBacktestRun",
    "GovernedReplayBacktestService",
    "ProjectAlphaRuntime",
    "RuntimeMetadata",
    "RuntimeMode",
    "RuntimeResult",
    "RuntimeStatus",
    "export_governed_replay_backtest_attestations",
]
