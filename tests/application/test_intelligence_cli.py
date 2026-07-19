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
    assert "1. HAL —" in result.stdout
    assert "Final Verdict:" in result.stdout
    assert "Execution Status:" in result.stdout
    assert "Portfolio Allocation:" in result.stdout
    assert "Score:" in result.stdout
    assert "Confidence:" in result.stdout
    assert "Action: ACCUMULATE" not in result.stdout
    assert "WATCHLIST Action: ACCUMULATE" not in result.stdout
    assert "Decision: REDUCE" not in result.stdout
    assert "Reason: Reduced deployment only" not in result.stdout
    assert "raw_allocation_hint=" not in result.stdout
    assert " allocation_hint=" not in result.stdout
    assert "final_signal=" not in result.stdout
    assert "final_score=" not in result.stdout
    assert "confidence=" not in result.stdout
    assert "   Setup:" in result.stdout
    assert "   Trade Strategies:" in result.stdout
    assert "   Evidence:" in result.stdout
    assert "   Decision Reason:" in result.stdout
    assert "Relative Volume:" in result.stdout
    assert "20-DMA unavailable; requires 20 bars" in result.stdout
    assert "Support used: unavailable at unavailable" not in result.stdout
    assert "Retracement improved the signal" not in result.stdout
    assert "Trade Setup:" not in result.stdout
    assert "Setup Entry Engine:" not in result.stdout
    assert "Setup Exit Engine:" not in result.stdout
    assert "Price/Volume:" in result.stdout
    assert "Trend:" in result.stdout
    assert "Retracement:" in result.stdout
    assert "Candle:" in result.stdout
    assert "Entry:" in result.stdout
    assert "Entry Zone: ₹0.00 to ₹0.00" not in result.stdout
    assert "Entry Zone: unavailable to unavailable" not in result.stdout
    assert "Trigger:" in result.stdout
    assert "Risk Stop:" in result.stdout
    assert "ATR Value: ₹1.00" not in result.stdout
    assert "Active Exit Rule:" not in result.stdout
    assert "Strategy Rank:" in result.stdout
    assert "Strategy Quality:" in result.stdout
    assert "Entry Zone Basis:" in result.stdout
    assert "Historical Edge:" in result.stdout
    assert "Fill Probability:" in result.stdout
    assert "Recommended Strategy:" in result.stdout
    assert "Suitability:" not in result.stdout
    assert "      Probability:" not in result.stdout
    assert "Trend Reference:" in result.stdout
    assert "Targets:" in result.stdout
    assert "Targets: unavailable, unavailable, unavailable" not in result.stdout
    assert "Risk / Reward:" in result.stdout
    assert "Reward/Risk to Target 1:" in result.stdout
    assert "Capital Deployment Dashboard:" in result.stdout
    assert "Data Completion:" in result.stdout
    assert "FULL ALLOCATION if portfolio policy allows" not in result.stdout
    assert "price_trend=" not in result.stdout
    assert "structure=" not in result.stdout
    assert "Portfolio Allocation:" in result.stdout
    assert "- Approved Capital:" in result.stdout
    assert "- Remaining Cash:" in result.stdout
    assert "- Deployment Count:" in result.stdout
    assert "Positions:" in result.stdout
    assert "Allocation Status: NO ALLOCATION" in result.stdout
    assert "Approved Capital:" in result.stdout
    assert "Target Weight:" in result.stdout
    assert "Final Decision Summary:" in result.stdout
    assert "- Deployable Ideas:" in result.stdout
    assert "- Strong Buy:" in result.stdout
    assert "- Buy:" in result.stdout
    assert "- Watchlist:" in result.stdout
    assert "- Hold:" in result.stdout
    assert "- Reduce:" in result.stdout
    assert "- Sell / Strong Sell:" in result.stdout
    assert "- Avoid / Reject:" in result.stdout
    assert "- Capital Approved:" in result.stdout
    assert "- Cash Remaining:" in result.stdout
    assert "- Highest Conviction:" in result.stdout
    assert "- Best Setup:" in result.stdout
    assert "- Main Market Risk:" in result.stdout


def test_daily_run_default_is_concise_and_verbose_shows_details() -> None:
    concise = runner.invoke(app, ["run", "--date", "2026-01-30", "--demo"])
    verbose = runner.invoke(
        app,
        ["run", "--date", "2026-01-30", "--demo", "--verbose"],
    )

    assert concise.exit_code == 0
    assert "Institutional Opportunities" in concise.stdout
    assert "Use --verbose for rejected candidates and full evidence." in concise.stdout
    assert "Strategy Scorecard:" not in concise.stdout
    assert verbose.exit_code == 0
    assert "Strategy Scorecard:" in verbose.stdout
    assert "Trade Strategies:" in verbose.stdout
    assert "Institutional Decision Layer" in verbose.stdout


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
    positive_amount = sum(
        (report.target_amount for report in positive_reports),
        Decimal("0"),
    )

    assert " raw_allocation_hint=" not in output
    assert " allocation_hint=" not in output
    assert "final_signal=" not in output
    assert "Action: ACCUMULATE" not in output
    assert "Decision: REDUCE" not in output
    assert "Reason: Reduced deployment only" not in output
    assert "   Setup:" in output
    assert "   Trade Strategies:" in output
    assert "   Evidence:" in output
    assert "Data Completion:" in output
    assert "Price/Volume:" in output
    assert "Trend:" in output
    assert "Retracement:" in output
    assert "Candle:" in output
    assert "Entry:" in output
    assert "Entry Zone: ₹0.00 to ₹0.00" not in output
    assert "Trigger:" in output
    assert "Risk Stop:" in output
    assert "Active Exit Rule:" not in output
    assert "Action Now:" in output
    assert "Recommended Strategy:" in output
    assert "Risk Controls:" in output
    assert "Historical Edge:" in output
    assert "Allocation" in output
    assert "Targets:" in output
    assert "Risk / Reward:" in output
    assert "Strategy Scorecard:" in output
    assert "Capital Deployment Dashboard:" in output
    assert "3. BBB — SELL" in output
    assert "Portfolio Summary" in output
    assert "Investment Verdict:" in output
    assert "Execution Status:" in output
    assert "Allocation Status:" in output
    assert "Reduced allocation approved by policy." not in output
    assert "Why Reduced:" in output or "Allocation Status: NO ALLOCATION" in output
    assert f"Approved Deployments : {len(positive_reports)}" in output
    assert f"- Approved Capital: ₹{positive_amount}" in output
    assert "- Deployment Count:" in output
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
    assert payload["recommendations"][0]["trade_setup"]["setup_name"]
    assert "setup_stage" in payload["recommendations"][0]["trade_setup"]
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
