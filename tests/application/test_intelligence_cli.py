from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
from typer.testing import CliRunner

from alpha.application.intelligence import (
    IntelligenceApplicationService,
    _driver_slug,
    _portfolio_summary_lines,
    _recommendation_driver_line,
    _sector_metadata_notice,
)
from alpha.application.runtime_models import RuntimeMetadata, RuntimeMode, RuntimeResult
from alpha.cli import _print_daily_runtime_result, app
from alpha.portfolio_intelligence import CapitalAllocationPlan

runner = CliRunner()


class _ReportWithoutDrivers:
    supporting_evidence: tuple[object, ...] = ()
    opposing_evidence: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class _Driver:
    label: str


@dataclass(frozen=True, slots=True)
class _ReportWithDrivers:
    supporting_evidence: tuple[_Driver, ...]
    opposing_evidence: tuple[_Driver, ...] = ()


def test_intelligence_command_prints_orchestrated_demo_report() -> None:
    result = runner.invoke(app, ["intelligence", "--demo", "--date", "2026-01-30"])

    assert result.exit_code == 0
    assert "Project Alpha Intelligence Report" in result.stdout
    assert "Observed On      : 2026-01-30" in result.stdout
    assert "Market Bias      :" in result.stdout
    assert "Composite Score  :" in result.stdout
    assert "Metadata Notice:" not in result.stdout
    assert "Market Intelligence Reasons:" in result.stdout
    assert "Recommendations:" in result.stdout
    assert "HAL:" in result.stdout
    assert "raw_allocation_hint=" in result.stdout
    assert " allocation_hint=" not in result.stdout
    assert "final_signal=" in result.stdout
    assert "final_score=" in result.stdout
    assert "confidence=" in result.stdout
    assert "Price-Volume Evidence:" in result.stdout
    assert "Trend Evidence:" in result.stdout
    assert "Retracement Evidence:" in result.stdout
    assert "Candle Pattern Evidence:" in result.stdout
    assert "Entry Zone:" in result.stdout
    assert "Entry Trigger:" in result.stdout
    assert "Initial Stop Loss:" in result.stdout
    assert "20-DMA Invalidation:" in result.stdout
    assert (
        "20-DMA Invalidation: Trade invalid if daily close is below 20-DMA, "
        "currently unavailable."
    ) not in result.stdout
    assert "ATR Value:" in result.stdout
    assert "Trailing Stop:" in result.stdout
    assert "Target 1:" in result.stdout
    assert "Target 2:" in result.stdout
    assert "Target 3:" in result.stdout
    assert "Risk-Reward Ratio:" in result.stdout
    assert "Why:" in result.stdout
    assert "   drivers: market_intelligence, strategy_strength, drawdown" in (
        result.stdout
    )
    assert "Portfolio Allocation:" in result.stdout
    assert "Approved Deployment Weight :" in result.stdout
    assert "approved capital deployments:" in result.stdout
    assert "Remaining Cash              :" in result.stdout
    assert "Portfolio Summary:" in result.stdout
    assert "Approved Deployments : 3" in result.stdout
    assert "Approved Capital     : 128400.00" in result.stdout
    assert "Cash Remaining       : 171600.00" in result.stdout
    assert "Highest Conviction   : HAL" in result.stdout
    assert "Largest Position     : HAL 8.08%" in result.stdout


def test_intelligence_summary_prints_none_without_approved_deployments() -> None:
    plan = CapitalAllocationPlan(
        generated_on=date(2026, 1, 30),
        reports=(),
        total_allocated_weight=Decimal("0"),
        total_allocated_amount=Decimal("0"),
        remaining_cash=Decimal("300000"),
        reasons=("approved capital deployments: 0",),
    )

    lines = _portfolio_summary_lines((), plan)

    assert "Approved Deployments : 0" in lines
    assert "Approved Capital     : 0" in lines
    assert "Cash Remaining       : 300000" in lines
    assert "Highest Conviction   : NONE" in lines
    assert "Largest Position     : NONE" in lines


def test_recommendation_driver_line_omits_empty_driver_sets() -> None:
    assert _recommendation_driver_line(_ReportWithoutDrivers()) is None
    assert _driver_slug("Market Participation") == "market_participation"


def test_recommendation_driver_line_is_deterministic_and_capped() -> None:
    report = _ReportWithDrivers(
        supporting_evidence=(
            _Driver("Alpha Signal"),
            _Driver("Market Participation"),
            _Driver("Alpha Signal"),
            _Driver("Liquidity Quality"),
            _Driver("Expected Value"),
        ),
        opposing_evidence=(_Driver("Market Volatility"),),
    )

    assert _recommendation_driver_line(report) == (
        "   drivers: alpha_signal, market_participation, "
        "liquidity_quality, expected_value"
    )


def test_sector_metadata_notice_only_prints_for_unknown_sector() -> None:
    assert _sector_metadata_notice("DEFENCE") is None
    assert _sector_metadata_notice("UNKNOWN") == (
        "Metadata Notice: Sector metadata unavailable from current live feed."
    )


def test_runtime_output_locks_recommendation_and_allocation_semantics(
    capsys,
) -> None:
    run = IntelligenceApplicationService.from_analysis(
        analysis=_unknown_sector_analysis_frame()
    ).run(observed_on=date(2026, 1, 30))
    runtime_result = RuntimeResult(
        metadata=RuntimeMetadata(
            requested_on=date(2026, 1, 30),
            observed_on=date(2026, 1, 30),
            mode=RuntimeMode.DEMO,
            started_at=datetime(2026, 1, 30, tzinfo=UTC),
            completed_at=datetime(2026, 1, 30, 0, 0, 1, tzinfo=UTC),
        ),
        intelligence_run=run,
    )

    _print_daily_runtime_result(runtime_result)
    output = capsys.readouterr().out
    positive_reports = tuple(
        report for report in run.allocation_plan.reports if report.target_weight > 0
    )
    positive_weight = sum(
        (report.target_weight for report in positive_reports),
        Decimal("0"),
    )
    positive_amount = sum(
        (report.target_amount for report in positive_reports),
        Decimal("0"),
    )

    assert " raw_allocation_hint=" in output
    assert " allocation_hint=" not in output
    assert "final_signal=" in output
    assert "Price-Volume Evidence:" in output
    assert "Trend Evidence:" in output
    assert "Retracement Evidence:" in output
    assert "Candle Pattern Evidence:" in output
    assert "Entry Zone:" in output
    assert "Entry Trigger:" in output
    assert "Initial Stop Loss:" in output
    assert "20-DMA Invalidation:" in output
    assert (
        "20-DMA Invalidation: Trade invalid if daily close is below 20-DMA, "
        "currently unavailable."
    ) not in output
    assert "ATR Value:" in output
    assert "Trailing Stop:" in output
    assert "Target 1:" in output
    assert "Target 2:" in output
    assert "Target 3:" in output
    assert "Risk-Reward Ratio:" in output
    assert "Why:" in output
    assert "3. BBB: SELL action=AVOID score=23.40 raw_allocation_hint=3.8115%" in output
    assert (
        "- BBB: SKIP capital_action=skip target_weight=0.0000 target_amount=0.00"
        in output
    )
    assert f"Approved Deployments : {len(positive_reports)}" in output
    assert f"Approved Deployment Weight : {positive_weight}" in output
    assert f"Approved Deployment Amount : {positive_amount}" in output
    assert (
        "Metadata Notice: Sector metadata unavailable from current live feed." in output
    )


def test_intelligence_command_exports_json_and_text(tmp_path) -> None:
    json_path = tmp_path / "recommendations.json"
    text_path = tmp_path / "recommendations.txt"

    result = runner.invoke(
        app,
        [
            "intelligence",
            "--demo",
            "--date",
            "2026-01-30",
            "--export-json",
            str(json_path),
            "--export-text",
            str(text_path),
        ],
    )

    assert result.exit_code == 0
    assert "JSON report written:" in result.stdout
    assert "Text report written:" in result.stdout
    assert json_path.exists()
    assert text_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["kind"] == "recommendation_report"
    assert payload["observed_on"] == "2026-01-30"
    assert [item["symbol"] for item in payload["recommendations"]] == [
        "HAL",
        "LT",
        "BEL",
    ]
    text = text_path.read_text(encoding="utf-8")
    assert "Raw Allocation Hint :" in text


def test_intelligence_command_rejects_invalid_export_suffix(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "intelligence",
            "--demo",
            "--date",
            "2026-01-30",
            "--export-json",
            str(tmp_path / "recommendations.txt"),
        ],
    )

    assert result.exit_code != 0
    assert "Expected --export-json path to end with .json." in result.stdout


def test_intelligence_command_rejects_invalid_text_export_suffix(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "intelligence",
            "--demo",
            "--date",
            "2026-01-30",
            "--export-text",
            str(tmp_path / "recommendations.json"),
        ],
    )

    assert result.exit_code != 0
    assert "Expected --export-text path to end with .txt." in result.stdout


def test_intelligence_command_is_visible_in_root_help() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "intelligence" in result.stdout


def _unknown_sector_analysis_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"],
            "sector": [None, None, None],
            "open": [100.0, 100.0, 100.0],
            "close": [110.0, 90.0, 105.0],
            "volume": [1000, 500, 1500],
            "momentum_1d": [0.10, -0.10, 0.05],
            "volatility": [0.12, 0.08, 0.10],
            "liquidity": [1000, 500, 1500],
            "alpha_score": [0.85, 0.35, 0.65],
            "rank": [1, 3, 2],
            "signal": ["BUY", "SELL", "BUY"],
            "correlation_to_index": [0.30, 0.60, 0.40],
            "correlation_to_sector": [0.35, 0.65, 0.45],
        }
    )
