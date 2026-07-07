from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from alpha.backtest.performance import PerformanceSummary


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    """Immutable presentation-safe performance report.

    The analytics engine owns calculations. This report object owns deterministic
    serialization for CLI, text reports, research workflows, and future adapters.
    """

    metrics: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        copied_metrics: dict[str, Decimal] = {}

        for name, value in self.metrics.items():
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("metric name cannot be empty")
            copied_metrics[normalized_name] = value

        object.__setattr__(self, "metrics", MappingProxyType(copied_metrics))

    def as_dict(self) -> dict[str, str]:
        """Return deterministic string values safe for external serialization."""

        return {
            name: self._format_decimal(value) for name, value in self.metrics.items()
        }

    def as_rows(self) -> tuple[tuple[str, str], ...]:
        """Return stable display rows preserving metric insertion order."""

        return tuple(
            (name, self._format_decimal(value)) for name, value in self.metrics.items()
        )

    def _format_decimal(self, value: Decimal) -> str:
        return format(value, "f")


@dataclass(frozen=True, slots=True)
class PerformanceReportBuilder:
    """Build deterministic reports from immutable performance summaries."""

    def build(self, summary: PerformanceSummary) -> PerformanceReport:
        return PerformanceReport(
            metrics={
                "total_return": summary.total_return,
                "cagr": summary.cagr,
                "volatility": summary.volatility,
                "sharpe_ratio": summary.sharpe_ratio,
                "sortino_ratio": summary.sortino_ratio,
                "calmar_ratio": summary.calmar_ratio,
                "maximum_drawdown": summary.maximum_drawdown,
                "win_rate": summary.win_rate,
                "profit_factor": summary.profit_factor,
                "average_win": summary.average_win,
                "average_loss": summary.average_loss,
                "expectancy": summary.expectancy,
                "exposure": summary.exposure,
                "ending_equity": summary.ending_equity,
                "cash_balance": summary.cash_balance,
            }
        )


@dataclass(frozen=True, slots=True)
class PerformanceReportRenderer:
    """Render performance reports into deterministic human-readable text."""

    labels: Mapping[str, str] | None = None

    def render(self, report: PerformanceReport) -> tuple[str, ...]:
        labels = self._labels()
        rows: list[str] = []

        for metric_name, metric_value in report.as_rows():
            label = labels.get(metric_name, metric_name)
            rows.append(f"{label:<16}: {metric_value}")

        return tuple(rows)

    def _labels(self) -> Mapping[str, str]:
        if self.labels is not None:
            return self.labels

        return {
            "total_return": "Total Return",
            "cagr": "CAGR",
            "volatility": "Volatility",
            "sharpe_ratio": "Sharpe Ratio",
            "sortino_ratio": "Sortino Ratio",
            "calmar_ratio": "Calmar Ratio",
            "maximum_drawdown": "Max Drawdown",
            "win_rate": "Win Rate",
            "profit_factor": "Profit Factor",
            "average_win": "Average Win",
            "average_loss": "Average Loss",
            "expectancy": "Expectancy",
            "exposure": "Exposure",
            "ending_equity": "Ending Equity",
            "cash_balance": "Cash Balance",
        }
