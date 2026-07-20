from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.benchmark_replay.exporting import BenchmarkArtifactExporter
from alpha.benchmark_replay.models import PRODUCTION_INFLUENCE, BenchmarkReplayReport
from alpha.benchmark_replay.rendering import render_executive_report


def test_export_is_deterministic_schema_complete_and_immutable(
    tmp_path: Path,
    benchmark_report: BenchmarkReplayReport,
) -> None:
    exporter = BenchmarkArtifactExporter()
    first = exporter.export(benchmark_report, output_directory=tmp_path)
    first_bytes = {path.name: path.read_bytes() for path in first}
    second = exporter.export(benchmark_report, output_directory=tmp_path)
    assert first_bytes == {path.name: path.read_bytes() for path in second}
    assert len(first) == 16

    assert (tmp_path / "decision_eligibility.csv").is_file()
    assert (tmp_path / "top_rejection_reasons.csv").is_file()
    trade_headers = next(csv.reader((tmp_path / "trade_log.csv").open()))
    assert {"trade_id", "entry_price", "exit_reason"}.issubset(trade_headers)
    approval_headers = next(csv.reader((tmp_path / "approval_statistics.csv").open()))
    assert "final_signal" in approval_headers
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["production_influence"] is False
    assert len(manifest["artifact_hashes"]) == 15
    assert manifest["replay_classification"] == "OBSERVED_MARKET_REPLAY"


def test_existing_baseline_rejects_different_input_hash(
    tmp_path: Path,
    benchmark_report: BenchmarkReplayReport,
) -> None:
    BenchmarkArtifactExporter().export(benchmark_report, output_directory=tmp_path)
    manifest_path = tmp_path / "manifest.json"
    payload = json.loads(manifest_path.read_text())
    payload["input_hash"] = "different"
    manifest_path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="immutable benchmark"):
        BenchmarkArtifactExporter().export(
            benchmark_report,
            output_directory=tmp_path,
        )


def test_report_labels_observed_replay_and_unavailable_metrics(
    benchmark_report: BenchmarkReplayReport,
) -> None:
    rendered = render_executive_report(benchmark_report)
    assert "ALPHA_BASELINE_v1.0 / OBSERVED_MARKET_REPLAY" in rendered
    assert "Win rate | unavailable" in rendered
    assert "NIFTY_50_BUY_AND_HOLD" in rendered
    assert "UNAVAILABLE" in rendered
    assert "PRODUCTION_INFLUENCE=false" in rendered


def test_cli_report_trades_portfolio_and_opportunity(
    tmp_path: Path,
    benchmark_report: BenchmarkReplayReport,
) -> None:
    BenchmarkArtifactExporter().export(benchmark_report, output_directory=tmp_path)
    runner = CliRunner()
    report = runner.invoke(benchmark_app, ["report", "--output", str(tmp_path)])
    trades = runner.invoke(benchmark_app, ["trades", "--output", str(tmp_path)])
    portfolio = runner.invoke(benchmark_app, ["portfolio", "--output", str(tmp_path)])
    opportunity = runner.invoke(
        benchmark_app, ["opportunity", "--output", str(tmp_path)]
    )
    assert report.exit_code == trades.exit_code == portfolio.exit_code == 0
    assert opportunity.exit_code == 0
    assert "Canonical Alpha Benchmark Replay" in report.stdout
    assert "No trades executed" in trades.stdout
    assert "Starting Capital: 1000000" in portfolio.stdout
    assert "major=10" in opportunity.stdout


def test_production_influence_is_permanently_false() -> None:
    assert PRODUCTION_INFLUENCE is False
