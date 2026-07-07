from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from alpha.backtest import BacktestExportSession


def test_backtest_export_session_is_immutable_and_serializable() -> None:
    session = BacktestExportSession(
        strategy=" Momentum ",
        start="2024-01-01",
        end="2024-01-31",
    )

    assert session.strategy == "momentum"
    assert session.start == "2024-01-01"
    assert session.end == "2024-01-31"
    assert session.generator == "project-alpha"
    assert session.format_version == "1.0"
    assert len(session.session_id) == 16
    assert session.as_dict() == {
        "session_id": session.session_id,
        "generator": "project-alpha",
        "format_version": "1.0",
        "strategy": "momentum",
        "start": "2024-01-01",
        "end": "2024-01-31",
    }

    with pytest.raises(FrozenInstanceError):
        session.strategy = "other"  # type: ignore[misc]


def test_backtest_export_session_id_is_deterministic() -> None:
    first = BacktestExportSession(
        strategy="momentum",
        start="2024-01-01",
        end="2024-01-31",
    )
    second = BacktestExportSession(
        strategy=" Momentum ",
        start="2024-01-01",
        end="2024-01-31",
    )

    assert first.session_id == second.session_id


def test_backtest_export_session_id_changes_with_inputs() -> None:
    first = BacktestExportSession(
        strategy="momentum",
        start="2024-01-01",
        end="2024-01-31",
    )
    second = BacktestExportSession(
        strategy="mean-reversion",
        start="2024-01-01",
        end="2024-01-31",
    )

    assert first.session_id != second.session_id


def test_backtest_export_session_exports_json() -> None:
    session = BacktestExportSession(
        strategy="momentum",
        start="2024-01-01",
        end="2024-01-31",
    )

    assert json.loads(session.as_json()) == session.as_dict()
    assert session.as_json() == json.dumps(
        session.as_dict(),
        sort_keys=True,
    )
    assert "\n" in session.as_json(indent=2)


def test_backtest_export_session_rejects_empty_fields() -> None:
    with pytest.raises(ValueError, match="strategy cannot be empty"):
        BacktestExportSession(strategy=" ", start="2024-01-01", end="2024-01-31")

    with pytest.raises(ValueError, match="start cannot be empty"):
        BacktestExportSession(strategy="momentum", start=" ", end="2024-01-31")

    with pytest.raises(ValueError, match="end cannot be empty"):
        BacktestExportSession(strategy="momentum", start="2024-01-01", end=" ")

    with pytest.raises(ValueError, match="format_version cannot be empty"):
        BacktestExportSession(
            strategy="momentum",
            start="2024-01-01",
            end="2024-01-31",
            format_version=" ",
        )

    with pytest.raises(ValueError, match="generator cannot be empty"):
        BacktestExportSession(
            strategy="momentum",
            start="2024-01-01",
            end="2024-01-31",
            generator=" ",
        )
