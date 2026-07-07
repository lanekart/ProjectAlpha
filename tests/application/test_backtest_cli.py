from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import typer

from alpha.application.backtest import BacktestSummary
from alpha.backtest.models import BacktestResult
from alpha.cli import (
    _export_backtest_summary,
    _parse_date,
    _print_backtest_summary,
    _validate_export_paths,
)


def make_summary() -> BacktestSummary:
    result = BacktestResult(
        starting_cash=Decimal("1000"),
        ending_cash=Decimal("100"),
        equity=Decimal("1100"),
        positions={"AAPL": 10},
        trades=(),
    )
    return BacktestSummary(
        strategy="momentum",
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        starting_cash=result.starting_cash,
        ending_cash=result.ending_cash,
        equity=result.equity,
        processed_days=22,
        order_count=1,
        trade_count=0,
        position_count=1,
        positions=result.positions,
        result=result,
    )


def test_parse_date() -> None:
    assert _parse_date("2024-01-15") == date(2024, 1, 15)


def test_print_backtest_summary_uses_unified_report_renderer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _print_backtest_summary(make_summary())

    output = capsys.readouterr().out

    assert "Project Alpha Backtest" in output
    assert "Performance:" in output
    assert "Strategy Statistics:" in output
    assert "Execution:" in output
    assert "Positions:" in output


def test_export_backtest_summary_writes_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "report.json"

    _export_backtest_summary(
        summary=make_summary(),
        export_json=output_path,
        export_text=None,
    )

    output = capsys.readouterr().out

    assert "JSON report written:" in output
    assert (
        json.loads(output_path.read_text(encoding="utf-8"))["metadata"]["strategy"]
        == "momentum"
    )


def test_export_backtest_summary_writes_text(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "report.txt"

    _export_backtest_summary(
        summary=make_summary(),
        export_json=None,
        export_text=output_path,
    )

    output = capsys.readouterr().out

    assert "Text report written:" in output
    assert "Project Alpha Backtest" in output_path.read_text(encoding="utf-8")


def test_export_backtest_summary_writes_json_and_text(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    json_path = tmp_path / "report.json"
    text_path = tmp_path / "report.txt"

    _export_backtest_summary(
        summary=make_summary(),
        export_json=json_path,
        export_text=text_path,
    )

    output = capsys.readouterr().out

    assert "JSON report written:" in output
    assert "Text report written:" in output
    assert json_path.exists()
    assert text_path.exists()


def test_validate_export_paths_accepts_valid_suffixes() -> None:
    _validate_export_paths(
        export_json=Path("reports/backtest.json"),
        export_text=Path("reports/backtest.txt"),
    )


def test_validate_export_paths_rejects_invalid_json_suffix() -> None:
    with pytest.raises(
        typer.BadParameter,
        match="Expected --export-json path to end with .json.",
    ):
        _validate_export_paths(
            export_json=Path("reports/backtest.txt"),
            export_text=None,
        )


def test_validate_export_paths_rejects_invalid_text_suffix() -> None:
    with pytest.raises(
        typer.BadParameter,
        match="Expected --export-text path to end with .txt.",
    ):
        _validate_export_paths(
            export_json=None,
            export_text=Path("reports/backtest.json"),
        )
