"""Tests for annual historical-truth governance."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from alpha.diagnostics import DiagnosticContext, HistoricalTruthGovernanceEngine
from alpha.research_dataset_inventory import DatasetInventoryRow


def _row(
    key: str,
    *,
    required: bool = True,
    blocking: bool = True,
    ready: bool = True,
    status: str = "COMPLETE_CANDIDATE",
) -> DatasetInventoryRow:
    return DatasetInventoryRow(
        dataset_key=key,
        dataset_name=key.replace("_", " ").title(),
        required=required,
        blocking=blocking,
        capability="test capability",
        status=status,
        evidence="test evidence",
        matched_tables=key,
        matched_files=1,
        row_count=10 if status != "MISSING" else None,
        first_date="2026-01-01",
        last_date="2026-07-20",
        observed_sessions=100,
        expected_sessions=100,
        missing_sessions=0,
        coverage_percent="100.00",
        certification_ready=ready,
        limitation="test limitation",
    )


def _context(tmp_path: Path) -> DiagnosticContext:
    return DiagnosticContext(
        engine_key="historical-truth-governance",
        as_of=datetime(2026, 7, 20, tzinfo=UTC),
        output_directory=tmp_path,
        parameters={
            "year": 2026,
            "database": tmp_path / "historical_truth.duckdb",
            "snapshots": tmp_path / "snapshots",
            "as_of": date(2026, 7, 20),
        },
    )


def test_governance_certifies_complete_inventory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rows = (
        _row("daily_ohlcv"),
        _row("corporate_actions"),
        _row("security_identity"),
        _row("listing_history"),
        _row("delisting_history"),
        _row("trading_calendar"),
        _row("benchmark_history"),
        _row("sector_mapping"),
        _row("index_constituents", blocking=False),
        _row("market_breadth", required=False, blocking=False),
    )
    monkeypatch.setattr(
        "alpha.diagnostics.historical_truth_governance.build_inventory",
        lambda **_: rows,
    )

    result = HistoricalTruthGovernanceEngine().run(_context(tmp_path))

    assert result.classification == "CERTIFIED"
    assert result.scorecard.weighted_score == 100.0
    assert result.recommendations == ()
    assert result.metadata["blocking_issue_count"] == 0


def test_governance_prioritizes_blocking_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rows = (
        _row("daily_ohlcv"),
        _row(
            "corporate_actions",
            ready=False,
            status="MISSING",
        ),
        _row("security_identity"),
        _row("listing_history"),
        _row(
            "delisting_history",
            ready=False,
            status="MISSING",
        ),
        _row("trading_calendar"),
        _row("benchmark_history"),
        _row("sector_mapping"),
        _row("index_constituents", blocking=False),
    )
    monkeypatch.setattr(
        "alpha.diagnostics.historical_truth_governance.build_inventory",
        lambda **_: rows,
    )

    result = HistoricalTruthGovernanceEngine().run(_context(tmp_path))

    assert result.classification == "NOT_CERTIFIED"
    assert result.metadata["blocking_issue_count"] == 2
    assert [item.key for item in result.recommendations[:2]] == [
        "remediate-corporate_actions",
        "remediate-delisting_history",
    ]
    dimensions = {item.key: item.score for item in result.scorecard.dimensions}
    assert dimensions["lineage"] < 100.0
    assert dimensions["replay_readiness"] < 100.0


def test_governance_rejects_invalid_context(tmp_path: Path) -> None:
    context = DiagnosticContext(
        engine_key="historical-truth-governance",
        as_of=datetime(2026, 7, 20, tzinfo=UTC),
        output_directory=tmp_path,
        parameters={"year": "2026", "database": tmp_path / "db.duckdb"},
    )

    with pytest.raises(ValueError, match="year must be an integer"):
        HistoricalTruthGovernanceEngine().run(context)
