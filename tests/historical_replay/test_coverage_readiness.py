"""Tests for deterministic governed replay coverage evidence."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from alpha.historical_replay.coverage_readiness import (
    HistoricalReplayCoverageEvidence,
    build_historical_replay_coverage_evidence,
)

_FROM = date(2025, 1, 1)
_TO = date(2025, 1, 31)


def _database(path: Path, *, warmup: int, outcome: int) -> Path:
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            "CREATE TABLE daily_prices (symbol VARCHAR, trade_date DATE)"
        )
        rows: list[tuple[str, date]] = []
        for offset in range(warmup):
            rows.append(("ALPHA", _FROM - timedelta(days=warmup - offset)))
        for offset in range(1, outcome + 1):
            rows.append(("ALPHA", _TO + timedelta(days=offset)))
        connection.executemany("INSERT INTO daily_prices VALUES (?, ?)", rows)
    finally:
        connection.close()
    return path


def test_builder_counts_warmup_outcomes_and_eligible_securities(tmp_path: Path) -> None:
    evidence = build_historical_replay_coverage_evidence(
        database=_database(tmp_path / "coverage.duckdb", warmup=200, outcome=60),
        from_date=_FROM,
        to_date=_TO,
    )

    assert evidence.observed_warmup_sessions == 200
    assert evidence.observed_outcome_sessions == 60
    assert evidence.eligible_security_ids == ("ALPHA",)
    assert evidence.eligible_security_count == 1
    assert evidence.source_table == "main.daily_prices"
    assert len(evidence.coverage_sha256) == 64


def test_builder_is_deterministic(tmp_path: Path) -> None:
    database = _database(tmp_path / "coverage.duckdb", warmup=200, outcome=60)

    first = build_historical_replay_coverage_evidence(
        database=database,
        from_date=_FROM,
        to_date=_TO,
    )
    second = build_historical_replay_coverage_evidence(
        database=database,
        from_date=_FROM,
        to_date=_TO,
    )

    assert first.as_dict() == second.as_dict()
    assert first.coverage_sha256 == second.coverage_sha256


def test_missing_database_fails_closed_with_zero_coverage(tmp_path: Path) -> None:
    evidence = build_historical_replay_coverage_evidence(
        database=tmp_path / "missing.duckdb",
        from_date=_FROM,
        to_date=_TO,
    )

    assert evidence.observed_warmup_sessions == 0
    assert evidence.observed_outcome_sessions == 0
    assert evidence.eligible_security_ids == ()
    assert evidence.source_table == ""


def test_evidence_rejects_lowered_governed_requirements() -> None:
    with pytest.raises(ValueError, match="unsupported warm-up-session"):
        HistoricalReplayCoverageEvidence(
            from_date=_FROM,
            to_date=_TO,
            observed_warmup_sessions=200,
            observed_outcome_sessions=60,
            eligible_security_ids=("ALPHA",),
            source_table="test",
            required_warmup_sessions=199,
        )
