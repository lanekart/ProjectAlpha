from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from alpha.backtest import (
    StrategyStatistics,
    StrategyStatisticsReport,
    StrategyStatisticsReportBuilder,
    StrategyStatisticsReportRenderer,
)


def make_statistics() -> StrategyStatistics:
    return StrategyStatistics(
        recovery_factor=Decimal("2.5"),
        gain_to_pain_ratio=Decimal("4"),
        system_quality_number=Decimal("1.75"),
        payoff_ratio=Decimal("2"),
        kelly_fraction=Decimal("0.40"),
        risk_of_ruin=Decimal("0.017341529915832612"),
        consecutive_wins=3,
        consecutive_losses=2,
        trade_frequency=Decimal("126"),
        annual_return=Decimal("0.25"),
        monthly_return=Decimal("0.018769265"),
    )


def test_strategy_statistics_report_is_immutable() -> None:
    report = StrategyStatisticsReport(metrics={"recovery_factor": Decimal("2.5")})

    with pytest.raises(FrozenInstanceError):
        report.metrics = {}  # type: ignore[misc]

    with pytest.raises(TypeError):
        report.metrics["recovery_factor"] = Decimal("0")  # type: ignore[index]


def test_strategy_statistics_report_rejects_empty_metric_name() -> None:
    with pytest.raises(ValueError, match="metric name cannot be empty"):
        StrategyStatisticsReport(metrics={" ": Decimal("0")})


def test_strategy_statistics_report_serializes_values_as_strings() -> None:
    report = StrategyStatisticsReport(
        metrics={
            "recovery_factor": Decimal("2.5"),
            "consecutive_wins": 3,
        }
    )

    assert report.as_dict() == {
        "recovery_factor": "2.5",
        "consecutive_wins": "3",
    }


def test_strategy_statistics_report_rows_preserve_metric_order() -> None:
    report = StrategyStatisticsReport(
        metrics={
            "first": Decimal("1"),
            "second": 2,
            "third": Decimal("3"),
        }
    )

    assert report.as_rows() == (
        ("first", "1"),
        ("second", "2"),
        ("third", "3"),
    )


def test_strategy_statistics_report_builder_exports_full_surface() -> None:
    report = StrategyStatisticsReportBuilder().build(make_statistics())

    assert report.as_dict() == {
        "recovery_factor": "2.5",
        "gain_to_pain_ratio": "4",
        "system_quality_number": "1.75",
        "payoff_ratio": "2",
        "kelly_fraction": "0.40",
        "risk_of_ruin": "0.017341529915832612",
        "consecutive_wins": "3",
        "consecutive_losses": "2",
        "trade_frequency": "126",
        "annual_return": "0.25",
        "monthly_return": "0.018769265",
    }


def test_strategy_statistics_report_renderer_outputs_labeled_rows() -> None:
    report = StrategyStatisticsReport(
        metrics={
            "recovery_factor": Decimal("2.5"),
            "consecutive_wins": 3,
        }
    )

    assert StrategyStatisticsReportRenderer().render(report) == (
        "Recovery Factor       : 2.5",
        "Consecutive Wins      : 3",
    )


def test_strategy_statistics_report_renderer_supports_custom_labels() -> None:
    report = StrategyStatisticsReport(metrics={"recovery_factor": Decimal("2.5")})
    renderer = StrategyStatisticsReportRenderer(labels={"recovery_factor": "Recovery"})

    assert renderer.render(report) == ("Recovery              : 2.5",)


def test_strategy_statistics_report_renderer_falls_back_to_metric_name() -> None:
    report = StrategyStatisticsReport(metrics={"custom_metric": Decimal("1")})

    assert StrategyStatisticsReportRenderer().render(report) == (
        "custom_metric         : 1",
    )
