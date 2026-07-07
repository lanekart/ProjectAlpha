from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from alpha.backtest.performance_export import (
    PerformanceReport,
    PerformanceReportRenderer,
)
from alpha.backtest.strategy_statistics_export import (
    StrategyStatisticsReport,
    StrategyStatisticsReportRenderer,
)

BacktestReportPayload = dict[str, Any]
StringRecord = Mapping[str, str]


@dataclass(frozen=True, slots=True)
class BacktestReport:
    """Immutable serialization-safe report for a completed backtest run."""

    metadata: Mapping[str, str]
    performance: PerformanceReport
    strategy_statistics: StrategyStatisticsReport
    execution: Mapping[str, int]
    positions: Mapping[str, int]
    reconciliation: Mapping[str, str] = MappingProxyType({})
    position_details: Sequence[StringRecord] = ()
    trade_ledger: Sequence[StringRecord] = ()
    equity_curve: Sequence[StringRecord] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(self._copy_str_mapping(self.metadata, "metadata")),
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
        object.__setattr__(
            self,
            "reconciliation",
            MappingProxyType(
                self._copy_str_mapping(self.reconciliation, "reconciliation")
            ),
        )
        object.__setattr__(
            self,
            "position_details",
            self._copy_record_sequence(self.position_details, "position_details"),
        )
        object.__setattr__(
            self,
            "trade_ledger",
            self._copy_record_sequence(self.trade_ledger, "trade_ledger"),
        )
        object.__setattr__(
            self,
            "equity_curve",
            self._copy_record_sequence(self.equity_curve, "equity_curve"),
        )

    def as_dict(self) -> BacktestReportPayload:
        """Return deterministic nested dictionaries for external serialization."""

        payload: BacktestReportPayload = {
            "metadata": dict(self.metadata),
            "performance": self.performance.as_dict(),
            "strategy_statistics": self.strategy_statistics.as_dict(),
            "execution": dict(self.execution),
            "positions": dict(self.positions),
        }

        if self.reconciliation:
            payload["reconciliation"] = dict(self.reconciliation)
        if self.position_details:
            payload["position_details"] = [
                dict(record) for record in self.position_details
            ]
        if self.trade_ledger:
            payload["trade_ledger"] = [dict(record) for record in self.trade_ledger]
        if self.equity_curve:
            payload["equity_curve"] = [dict(record) for record in self.equity_curve]

        return payload

    def as_json(self, *, indent: int | None = None) -> str:
        """Return deterministic JSON for persistence and tool integration."""

        return json.dumps(
            self.as_dict(),
            indent=indent,
            sort_keys=True,
        )

    def _copy_str_mapping(
        self,
        values: Mapping[str, str],
        section: str,
    ) -> dict[str, str]:
        copied: dict[str, str] = {}

        for key, value in values.items():
            normalized_key = key.strip()
            if not normalized_key:
                raise ValueError(f"{section} key cannot be empty")
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

    def _copy_record_sequence(
        self,
        records: Sequence[StringRecord],
        section: str,
    ) -> tuple[Mapping[str, str], ...]:
        copied_records: list[Mapping[str, str]] = []

        for record in records:
            copied_records.append(
                MappingProxyType(self._copy_str_mapping(record, section))
            )

        return tuple(copied_records)


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
        holdings_market_value: Decimal | None = None,
        reconciliation: Mapping[str, str] | None = None,
        position_details: Sequence[StringRecord] = (),
        trade_ledger: Sequence[StringRecord] = (),
        equity_curve: Sequence[StringRecord] = (),
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

        metadata = {
            "strategy": strategy.strip().lower(),
            "start": start,
            "end": end,
            "processed_days": str(processed_days),
            "starting_cash": format(starting_cash, "f"),
            "ending_cash": format(ending_cash, "f"),
            "equity": format(equity, "f"),
        }
        if holdings_market_value is not None:
            metadata["holdings_market_value"] = format(holdings_market_value, "f")

        return BacktestReport(
            metadata=metadata,
            performance=performance,
            strategy_statistics=strategy_statistics,
            execution={
                "orders": order_count,
                "trades": trade_count,
                "positions": position_count,
            },
            positions=positions,
            reconciliation=reconciliation or {},
            position_details=position_details,
            trade_ledger=trade_ledger,
            equity_curve=equity_curve,
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

        if report.reconciliation:
            lines.extend(
                (
                    "",
                    "Reconciliation:",
                    *self._reconciliation_lines(report),
                )
            )
        if report.position_details:
            lines.extend(
                (
                    "",
                    "Position Details:",
                    *self._record_lines(report.position_details),
                )
            )
        if report.trade_ledger:
            lines.extend(
                (
                    "",
                    "Trade Ledger:",
                    *self._record_lines(report.trade_ledger),
                )
            )
        if report.equity_curve:
            lines.extend(
                (
                    "",
                    "Equity Curve:",
                    *self._record_lines(report.equity_curve),
                )
            )

        return tuple(lines)

    def _metadata_lines(self, report: BacktestReport) -> tuple[str, ...]:
        lines = [
            f"Strategy       : {report.metadata['strategy']}",
            f"Start          : {report.metadata['start']}",
            f"End            : {report.metadata['end']}",
            f"Processed Days : {report.metadata['processed_days']}",
            f"Starting Cash  : {report.metadata['starting_cash']}",
            f"Ending Cash    : {report.metadata['ending_cash']}",
        ]
        if "holdings_market_value" in report.metadata:
            lines.append(f"Holdings Value : {report.metadata['holdings_market_value']}")
        lines.append(f"Equity         : {report.metadata['equity']}")
        return tuple(lines)

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

    def _reconciliation_lines(self, report: BacktestReport) -> tuple[str, ...]:
        return tuple(
            f"{key}: {value}" for key, value in sorted(report.reconciliation.items())
        )

    def _record_lines(self, records: Sequence[StringRecord]) -> tuple[str, ...]:
        return tuple(
            " | ".join(f"{key}: {value}" for key, value in sorted(record.items()))
            for record in records
        )
