from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType

import pytest
from typer.testing import CliRunner

from alpha.application import market_opportunity_cli
from alpha.application.market_opportunity_cli import market_opportunity_app
from alpha.market_opportunity_truth.exports import MarketOpportunityTruthExporter
from alpha.market_opportunity_truth.models import (
    NO_APPROVAL_CHANGES,
    NO_FEATURE_CHANGES,
    NO_GATE_CHANGES,
    NO_SETUP_CHANGES,
    NO_WEIGHT_CHANGES,
    POINT_IN_TIME_ONLY,
    PRODUCTION_INFLUENCE,
    MarketOpportunityTruthReport,
)


def test_exports_are_complete_and_reproducible(
    tmp_path: Path,
    mota_report: MarketOpportunityTruthReport,
) -> None:
    exporter = MarketOpportunityTruthExporter()
    first = exporter.export(mota_report, output_directory=tmp_path)
    first_bytes = {path.name: path.read_bytes() for path in first}
    second = exporter.export(mota_report, output_directory=tmp_path)
    assert first_bytes == {path.name: path.read_bytes() for path in second}
    assert len(first) == 9
    for name in (
        "market_opportunities.csv",
        "opportunity_calendar.csv",
        "opportunity_density.csv",
        "quality_distribution.csv",
        "opportunity_clusters.csv",
        "alpha_vs_market.csv",
        "capture_statistics.csv",
        "executive_report.md",
        "manifest.json",
    ):
        assert (tmp_path / name).exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["production_influence"] is False
    assert len(manifest["artifact_hashes"]) == 8


def test_cli_read_commands(
    tmp_path: Path,
    mota_report: MarketOpportunityTruthReport,
) -> None:
    MarketOpportunityTruthExporter().export(mota_report, output_directory=tmp_path)
    runner = CliRunner()
    calendar = runner.invoke(
        market_opportunity_app,
        ["calendar", "--output", str(tmp_path)],
    )
    density = runner.invoke(
        market_opportunity_app,
        ["density", "--output", str(tmp_path)],
    )
    compare = runner.invoke(
        market_opportunity_app,
        ["compare", "--output", str(tmp_path)],
    )
    report = runner.invoke(
        market_opportunity_app,
        ["report", "--output", str(tmp_path)],
    )
    assert calendar.exit_code == 0
    assert density.exit_code == 0
    assert compare.exit_code == 0
    assert report.exit_code == 0
    assert "Market Opportunity Calendar" in calendar.stdout
    assert "Market Opportunity Density" in density.stdout
    assert "Alpha vs Market Opportunities" in compare.stdout
    assert "Market Opportunity Truth Audit" in report.stdout


def test_cli_audit_exports_frozen_report(
    tmp_path: Path,
    mota_report: MarketOpportunityTruthReport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubStore:
        def __init__(self, _database: Path) -> None:
            pass

        def __enter__(self) -> StubStore:
            return self

        def __exit__(
            self,
            _exception_type: type[BaseException] | None,
            _exception: BaseException | None,
            _traceback: TracebackType | None,
        ) -> None:
            pass

    def run_stub(
        _engine: object,
        **_kwargs: object,
    ) -> MarketOpportunityTruthReport:
        return mota_report

    monkeypatch.setattr(market_opportunity_cli, "LegacyMarketDataStore", StubStore)
    monkeypatch.setattr(
        market_opportunity_cli.MarketOpportunityTruthEngine,
        "run",
        run_stub,
    )
    result = CliRunner().invoke(
        market_opportunity_app,
        [
            "audit",
            "--database",
            str(tmp_path / "market.db"),
            "--output",
            str(tmp_path / "mota"),
        ],
    )
    assert result.exit_code == 0
    assert "Provisional A+/A Opportunities: 2" in result.stdout
    assert "PRODUCTION_INFLUENCE=false" in result.stdout
    assert "Artifacts:" in result.stdout
    assert (tmp_path / "mota" / "manifest.json").exists()


def test_policy_isolation_constants_are_permanent() -> None:
    assert PRODUCTION_INFLUENCE is False
    assert NO_FEATURE_CHANGES is True
    assert NO_GATE_CHANGES is True
    assert NO_APPROVAL_CHANGES is True
    assert NO_WEIGHT_CHANGES is True
    assert NO_SETUP_CHANGES is True
    assert POINT_IN_TIME_ONLY is True
