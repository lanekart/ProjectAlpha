from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from alpha.backtest.performance_export import (
    PerformanceReport,
    PerformanceReportRenderer,
)
from alpha.backtest.strategy_statistics_export import (
    StrategyStatisticsReport,
    StrategyStatisticsReportRenderer,
)

BacktestReportPayload = dict[
    str,
    dict[str, str] | dict[str, int],
]


@dataclass(frozen=True, slots=True)
class BacktestReport:
    """Immutable serialization-safe report for a completed backtest run."""

    metadata: Mapping[str, str]
    performance: PerformanceReport
    strategy_statistics: StrategyStatisticsReport
    execution: Mapping[str, int]
    positions: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(self._copy_str_mapping(self.metadata)),
        )
        object.__setattr__(
            self,
            "execution",
            MappingProxyType(self._copy_int_mapping(self.execution, "execution")),
        )
        object.__setattr__(
            self,
            "positions",
            MappingProxyType(self._copy_int_mapping(self.positions, "positions")),
        )

    def as_dict(self) -> BacktestReportPayload:
        """Return deterministic nested dictionaries for external serialization."""

        return {
            "metadata": dict(self.metadata),
            "performance": self.performance.as_dict(),
            "strategy_statistics": self.strategy_statistics.as_dict(),
            "execution": dict(self.execution),
            "positions": dict(self.positions),
        }

    def as_json(self, *, indent: int | None = None) -> str:
        """Return deterministic JSON for persistence and tool integration."""

        return json.dumps(
            self.as_dict(),
            indent=indent,
            sort_keys=True,
        )

    def _copy_str_mapping(self, values: Mapping[str, str]) -> dict[str, str]:
        copied: dict[str, str] = {}

        for key, value in values.items():
            normalized_key = key.strip()
            if not normalized_key:
                raise ValueError("metadata key cannot be empty")
            copied[normalized_key] = value

        return copied

    def _copy_int_mapping(
        self,
        values: Mapping[str, int],
        section: str,
    ) -> dict[str, int]:
        copied: dict[str, int] = {}

        for key, value in values.items():
            normalized_key = key.strip()
            if not normalized_key:
                raise ValueError(f"{section} key cannot be empty")
            copied[normalized_key] = value

        return copied


@dataclass(frozen=True, slots=True)
class BacktestReportBuilder:
    """Build serialization-safe reports from application-facing backtest summaries."""

    def build(
        self,
        *,
        strategy: str,
        start: str,
        end: str,
        processed_days: int,
        starting_cash: Decimal,
        ending_cash: Decimal,
        equity: Decimal,
        order_count: int,
        trade_count: int,
        position_count: int,
        positions: Mapping[str, int],
        performance: PerformanceReport,
        strategy_statistics: StrategyStatisticsReport,
    ) -> BacktestReport:
        if not strategy.strip():
            raise ValueError("strategy cannot be empty")
        if processed_days <= 0:
            raise ValueError("processed_days must be positive")
        if order_count < 0:
            raise ValueError("order_count cannot be negative")
        if trade_count < 0:
            raise ValueError("trade_count cannot be negative")
        if position_count < 0:
            raise ValueError("position_count cannot be negative")
        if position_count != len(positions):
            raise ValueError("position_count must match positions")

        return BacktestReport(
            metadata={
                "strategy": strategy.strip().lower(),
                "start": start,
                "end": end,
                "processed_days": str(processed_days),
                "starting_cash": format(starting_cash, "f"),
                "ending_cash": format(ending_cash, "f"),
                "equity": format(equity, "f"),
            },
            performance=performance,
            strategy_statistics=strategy_statistics,
            execution={
                "orders": order_count,
                "trades": trade_count,
                "positions": position_count,
            },
            positions=positions,
        )


@dataclass(frozen=True, slots=True)
class BacktestReportRenderer:
    """Render complete backtest reports into deterministic text."""

    performance_renderer: PerformanceReportRenderer = PerformanceReportRenderer()
    statistics_renderer: StrategyStatisticsReportRenderer = (
        StrategyStatisticsReportRenderer()
    )

    def render(self, report: BacktestReport) -> tuple[str, ...]:
        lines: list[str] = [
            "Project Alpha Backtest",
            "",
            *self._metadata_lines(report),
            "",
            "Performance:",
            *self.performance_renderer.render(report.performance),
            "",
            "Strategy Statistics:",
            *self.statistics_renderer.render(report.strategy_statistics),
            "",
            "Execution:",
            *self._execution_lines(report),
            "",
            *self._position_lines(report),
        ]

        return tuple(lines)

    def _metadata_lines(self, report: BacktestReport) -> tuple[str, ...]:
        return (
            f"Strategy       : {report.metadata['strategy']}",
            f"Start          : {report.metadata['start']}",
            f"End            : {report.metadata['end']}",
            f"Processed Days : {report.metadata['processed_days']}",
            f"Starting Cash  : {report.metadata['starting_cash']}",
            f"Ending Cash    : {report.metadata['ending_cash']}",
            f"Equity         : {report.metadata['equity']}",
        )

    def _execution_lines(self, report: BacktestReport) -> tuple[str, ...]:
        return (
            f"Orders         : {report.execution['orders']}",
            f"Trades         : {report.execution['trades']}",
            f"Positions      : {report.execution['positions']}",
        )

    def _position_lines(self, report: BacktestReport) -> tuple[str, ...]:
        if not report.positions:
            return ("Positions: none",)

        return (
            "Positions:",
            *(
                f"{symbol}: {quantity}"
                for symbol, quantity in sorted(report.positions.items())
            ),
        )
