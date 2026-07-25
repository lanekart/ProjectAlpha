from __future__ import annotations

import csv
from pathlib import Path

import pytest

from alpha.decision_superiority.gate_isolation_baseline import (
    FrozenBaselineReconstructor,
    FrozenBaselineSourcePaths,
    GateIsolationBaselineError,
)

FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "input_fingerprint",
    "failure_codes",
    "resolved_outcome",
    "outcome_status",
    "realized_return_pct",
    "realized_r",
    "point_in_time_leakage",
)


def _row(
    *,
    price_view: str = "RAW",
    symbol: str = "AAA",
    fingerprint: str = "fp-a",
    failures: str = '["GATE_A", "GATE_B"]',
    resolved: str = "true",
    status: str = "RESOLVED",
    return_pct: str = "12.5",
    realized_r: str = "1.25",
    leakage: str = "false",
) -> dict[str, str]:
    return {
        "price_view": price_view,
        "observed_on": "2026-01-02",
        "symbol": symbol,
        "input_fingerprint": fingerprint,
        "failure_codes": failures,
        "resolved_outcome": resolved,
        "outcome_status": status,
        "realized_return_pct": return_pct,
        "realized_r": realized_r,
        "point_in_time_leakage": leakage,
    }


def _write(path: Path, rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _paths(tmp_path: Path, rows: list[dict[str, str]]) -> FrozenBaselineSourcePaths:
    return FrozenBaselineSourcePaths(
        b5_candidate_ledger=_write(tmp_path / "b5.csv", rows),
        b7_outcome_ledger=_write(tmp_path / "b7.csv", rows),
        b10_decision_ledger=_write(tmp_path / "b10.csv", rows),
        dsi001_candidate_ledger=_write(tmp_path / "dsi001.csv", rows),
    )


def test_reconstructs_deterministic_complete_baseline(tmp_path: Path) -> None:
    rows = [
        _row(symbol="BBB", fingerprint="fp-b"),
        _row(symbol="AAA", fingerprint="fp-a"),
    ]
    result = FrozenBaselineReconstructor().reconstruct(_paths(tmp_path, rows))

    assert tuple(item.candidate.symbol for item in result.candidates) == ("AAA", "BBB")
    assert result.raw_candidate_count == 2
    assert result.adjusted_candidate_count == 0
    assert result.raw_adjusted_identity_mismatch_count == 2
    assert result.candidates[0].observed_failure_codes == ("GATE_A", "GATE_B")
    assert str(result.candidates[0].realized_return_pct) == "12.5"


def test_raw_adjusted_parity_is_arm_neutral(tmp_path: Path) -> None:
    rows = [
        _row(price_view="RAW"),
        _row(price_view="ADJUSTED"),
    ]
    result = FrozenBaselineReconstructor().reconstruct(_paths(tmp_path, rows))

    assert result.raw_candidate_count == 1
    assert result.adjusted_candidate_count == 1
    assert result.raw_adjusted_identity_mismatch_count == 0


def test_rejects_missing_candidate_in_any_source(tmp_path: Path) -> None:
    rows = [_row()]
    paths = _paths(tmp_path, rows)
    _write(paths.b7_outcome_ledger, [])

    with pytest.raises(
        GateIsolationBaselineError,
        match="B7_IDENTITY_LINEAGE_MISMATCH",
    ):
        FrozenBaselineReconstructor().reconstruct(paths)


def test_rejects_duplicate_candidate_identity(tmp_path: Path) -> None:
    rows = [_row(), _row()]
    paths = _paths(tmp_path, rows)

    with pytest.raises(
        GateIsolationBaselineError,
        match="B5_DUPLICATE_CANDIDATE_IDENTITY",
    ):
        FrozenBaselineReconstructor().reconstruct(paths)


def test_rejects_gate_failure_lineage_conflict(tmp_path: Path) -> None:
    rows = [_row()]
    paths = _paths(tmp_path, rows)
    _write(paths.b5_candidate_ledger, [_row(failures='["GATE_X"]')])

    with pytest.raises(
        GateIsolationBaselineError,
        match="GATE_FAILURE_LINEAGE_MISMATCH",
    ):
        FrozenBaselineReconstructor().reconstruct(paths)


def test_rejects_point_in_time_leakage(tmp_path: Path) -> None:
    rows = [_row()]
    paths = _paths(tmp_path, rows)
    _write(paths.b10_decision_ledger, [_row(leakage="true")])

    with pytest.raises(
        GateIsolationBaselineError,
        match="POINT_IN_TIME_LEAKAGE_DETECTED",
    ):
        FrozenBaselineReconstructor().reconstruct(paths)


def test_unresolved_outcome_preserves_unavailable_values(tmp_path: Path) -> None:
    rows = [
        _row(
            resolved="false",
            status="PENDING",
            return_pct="",
            realized_r="",
        )
    ]
    result = FrozenBaselineReconstructor().reconstruct(_paths(tmp_path, rows))
    candidate = result.candidates[0]

    assert candidate.resolved_outcome is False
    assert candidate.outcome_status == "PENDING"
    assert candidate.realized_return_pct is None
    assert candidate.realized_r is None
