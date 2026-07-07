from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from alpha.backtest.strategy_statistics import StrategyStatistics


@dataclass(frozen=True, slots=True)
class StrategyStatisticsReport:
    """Immutable serialization-safe strategy statistics report."""

    metrics: Mapping[str, Decimal | int]

    def __post_init__(self) -> None:
        copied_metrics: dict[str, Decimal | int] = {}

        for name, value in self.metrics.items():
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("metric name cannot be empty")
            copied_metrics[normalized_name] = value

        object.__setattr__(self, "metrics", MappingProxyType(copied_metrics))

    def as_dict(self) -> dict[str, str]:
        """Return deterministic string values safe for external serialization."""

        return {name: self._format_value(value) for name, value in self.metrics.items()}

    def as_rows(self) -> tuple[tuple[str, str], ...]:
        """Return stable display rows preserving metric insertion order."""

        return tuple(
            (name, self._format_value(value)) for name, value in self.metrics.items()
        )

    def _format_value(self, value: Decimal | int) -> str:
        if isinstance(value, Decimal):
            return format(value, "f")
        return str(value)


@dataclass(frozen=True, slots=True)
class StrategyStatisticsReportBuilder:
    """Build deterministic reports from immutable strategy statistics."""

    def build(self, statistics: StrategyStatistics) -> StrategyStatisticsReport:
        return StrategyStatisticsReport(
            metrics={
                "recovery_factor": statistics.recovery_factor,
                "gain_to_pain_ratio": statistics.gain_to_pain_ratio,
                "system_quality_number": statistics.system_quality_number,
                "payoff_ratio": statistics.payoff_ratio,
                "kelly_fraction": statistics.kelly_fraction,
                "risk_of_ruin": statistics.risk_of_ruin,
                "consecutive_wins": statistics.consecutive_wins,
                "consecutive_losses": statistics.consecutive_losses,
                "trade_frequency": statistics.trade_frequency,
                "annual_return": statistics.annual_return,
                "monthly_return": statistics.monthly_return,
            }
        )


@dataclass(frozen=True, slots=True)
class StrategyStatisticsReportRenderer:
    """Render strategy statistics reports into deterministic text rows."""

    labels: Mapping[str, str] | None = None

    def render(self, report: StrategyStatisticsReport) -> tuple[str, ...]:
        labels = self._labels()
        rows: list[str] = []

        for metric_name, metric_value in report.as_rows():
            label = labels.get(metric_name, metric_name)
            rows.append(f"{label:<22}: {metric_value}")

        return tuple(rows)

    def _labels(self) -> Mapping[str, str]:
        if self.labels is not None:
            return self.labels

        return {
            "recovery_factor": "Recovery Factor",
            "gain_to_pain_ratio": "Gain-to-Pain Ratio",
            "system_quality_number": "SQN",
            "payoff_ratio": "Payoff Ratio",
            "kelly_fraction": "Kelly Fraction",
            "risk_of_ruin": "Risk of Ruin",
            "consecutive_wins": "Consecutive Wins",
            "consecutive_losses": "Consecutive Losses",
            "trade_frequency": "Trade Frequency",
            "annual_return": "Annual Return",
            "monthly_return": "Monthly Return",
        }
