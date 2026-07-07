from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from alpha.backtest import (
    PerformanceReport,
    PerformanceReportBuilder,
    PerformanceReportRenderer,
    PerformanceSummary,
)


def make_summary() -> PerformanceSummary:
    return PerformanceSummary(
        total_return=Decimal("0.10"),
        cagr=Decimal("0.20"),
        volatility=Decimal("0.30"),
        sharpe_ratio=Decimal("1.5"),
        sortino_ratio=Decimal("2.5"),
        calmar_ratio=Decimal("3.5"),
        maximum_drawdown=Decimal("-0.25"),
        win_rate=Decimal("0.60"),
        profit_factor=Decimal("1.80"),
        average_win=Decimal("120.50"),
        average_loss=Decimal("-40.25"),
        expectancy=Decimal("55.125"),
        exposure=Decimal("0.75"),
        ending_equity=Decimal("110000"),
        cash_balance=Decimal("25000"),
    )


def test_performance_report_is_immutable() -> None:
    report = PerformanceReport(metrics={"total_return": Decimal("0.10")})

    with pytest.raises(FrozenInstanceError):
        report.metrics = {}  # type: ignore[misc]

    with pytest.raises(TypeError):
        report.metrics["total_return"] = Decimal("0")  # type: ignore[index]


def test_performance_report_rejects_empty_metric_name() -> None:
    with pytest.raises(ValueError, match="metric name cannot be empty"):
        PerformanceReport(metrics={" ": Decimal("0")})


def test_performance_report_serializes_decimal_values_as_strings() -> None:
    report = PerformanceReport(
        metrics={
            "total_return": Decimal("0.10"),
            "maximum_drawdown": Decimal("-0.25"),
            "ending_equity": Decimal("110000"),
        }
    )

    assert report.as_dict() == {
        "total_return": "0.10",
        "maximum_drawdown": "-0.25",
        "ending_equity": "110000",
    }


def test_performance_report_rows_preserve_metric_order() -> None:
    report = PerformanceReport(
        metrics={
            "first": Decimal("1"),
            "second": Decimal("2"),
            "third": Decimal("3"),
        }
    )

    assert report.as_rows() == (
        ("first", "1"),
        ("second", "2"),
        ("third", "3"),
    )


def test_performance_report_builder_exports_full_summary_surface() -> None:
    report = PerformanceReportBuilder().build(make_summary())

    assert report.as_dict() == {
        "total_return": "0.10",
        "cagr": "0.20",
        "volatility": "0.30",
        "sharpe_ratio": "1.5",
        "sortino_ratio": "2.5",
        "calmar_ratio": "3.5",
        "maximum_drawdown": "-0.25",
        "win_rate": "0.60",
        "profit_factor": "1.80",
        "average_win": "120.50",
        "average_loss": "-40.25",
        "expectancy": "55.125",
        "exposure": "0.75",
        "ending_equity": "110000",
        "cash_balance": "25000",
    }


def test_performance_report_renderer_outputs_labeled_rows() -> None:
    report = PerformanceReport(
        metrics={
            "total_return": Decimal("0.10"),
            "ending_equity": Decimal("110000"),
        }
    )

    assert PerformanceReportRenderer().render(report) == (
        "Total Return    : 0.10",
        "Ending Equity   : 110000",
    )


def test_performance_report_renderer_supports_custom_labels() -> None:
    report = PerformanceReport(metrics={"total_return": Decimal("0.10")})
    renderer = PerformanceReportRenderer(labels={"total_return": "Return"})

    assert renderer.render(report) == ("Return          : 0.10",)


def test_performance_report_renderer_falls_back_to_metric_name() -> None:
    report = PerformanceReport(metrics={"custom_metric": Decimal("1")})

    assert PerformanceReportRenderer().render(report) == ("custom_metric   : 1",)
