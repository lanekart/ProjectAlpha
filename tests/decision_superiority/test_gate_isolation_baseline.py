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


def _write(
    path: Path,
    rows: list[dict[str, str]],
    *,
    fields: tuple[str, ...] = FIELDS,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _without_fingerprint(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {key: value for key, value in row.items() if key != "input_fingerprint"}
        for row in rows
    ]


def _paths(
    tmp_path: Path,
    rows: list[dict[str, str]],
    *,
    b7_rows: list[dict[str, str]] | None = None,
    b10_rows: list[dict[str, str]] | None = None,
) -> FrozenBaselineSourcePaths:
    selected_b7 = rows if b7_rows is None else b7_rows
    selected_b10 = rows if b10_rows is None else b10_rows
    b7_fields = tuple(selected_b7[0]) if selected_b7 else FIELDS
    b10_fields = tuple(selected_b10[0]) if selected_b10 else FIELDS
    return FrozenBaselineSourcePaths(
        b5_candidate_ledger=_write(tmp_path / "b5.csv", rows),
        b7_outcome_ledger=_write(
            tmp_path / "b7.csv",
            selected_b7,
            fields=b7_fields,
        ),
        b10_decision_ledger=_write(
            tmp_path / "b10.csv",
            selected_b10,
            fields=b10_fields,
        ),
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


def test_b7_without_fingerprint_joins_to_canonical_identity(tmp_path: Path) -> None:
    rows = [_row()]
    paths = _paths(tmp_path, rows, b7_rows=_without_fingerprint(rows))

    result = FrozenBaselineReconstructor().reconstruct(paths)

    assert result.candidates[0].candidate.input_fingerprint == "fp-a"
    assert result.candidates[0].b7_present is True


def test_b10_without_fingerprint_joins_to_canonical_identity(tmp_path: Path) -> None:
    rows = [_row()]
    paths = _paths(tmp_path, rows, b10_rows=_without_fingerprint(rows))

    result = FrozenBaselineReconstructor().reconstruct(paths)

    assert result.candidates[0].candidate.input_fingerprint == "fp-a"
    assert result.candidates[0].b10_present is True


def test_b7_present_fingerprint_must_match_canonical_identity(
    tmp_path: Path,
) -> None:
    rows = [_row()]
    paths = _paths(tmp_path, rows, b7_rows=[_row(fingerprint="wrong")])

    with pytest.raises(
        GateIsolationBaselineError,
        match="B7_FINGERPRINT_MISMATCH",
    ):
        FrozenBaselineReconstructor().reconstruct(paths)


def test_b10_present_fingerprint_must_match_canonical_identity(
    tmp_path: Path,
) -> None:
    rows = [_row()]
    paths = _paths(tmp_path, rows, b10_rows=[_row(fingerprint="wrong")])

    with pytest.raises(
        GateIsolationBaselineError,
        match="B10_FINGERPRINT_MISMATCH",
    ):
        FrozenBaselineReconstructor().reconstruct(paths)


def test_ambiguous_canonical_identity_fails_closed(tmp_path: Path) -> None:
    rows = [_row(fingerprint="fp-a"), _row(fingerprint="fp-b")]
    partial = _without_fingerprint([rows[0]])
    paths = _paths(tmp_path, rows, b7_rows=partial, b10_rows=partial)

    with pytest.raises(
        GateIsolationBaselineError,
        match="AMBIGUOUS_CANONICAL_IDENTITY",
    ):
        FrozenBaselineReconstructor().reconstruct(paths)


def test_b7_duplicate_available_identity_fails_closed(tmp_path: Path) -> None:
    rows = [_row()]
    paths = _paths(
        tmp_path,
        rows,
        b7_rows=_without_fingerprint([_row(), _row()]),
    )

    with pytest.raises(
        GateIsolationBaselineError,
        match="B7_DUPLICATE_CANDIDATE_IDENTITY",
    ):
        FrozenBaselineReconstructor().reconstruct(paths)


def test_b10_duplicate_available_identity_fails_closed(tmp_path: Path) -> None:
    rows = [_row()]
    paths = _paths(
        tmp_path,
        rows,
        b10_rows=_without_fingerprint([_row(), _row()]),
    )

    with pytest.raises(
        GateIsolationBaselineError,
        match="B10_DUPLICATE_CANDIDATE_IDENTITY",
    ):
        FrozenBaselineReconstructor().reconstruct(paths)


def test_raw_adjusted_parity_is_arm_neutral(tmp_path: Path) -> None:
    rows = [_row(price_view="RAW"), _row(price_view="ADJUSTED")]
    result = FrozenBaselineReconstructor().reconstruct(_paths(tmp_path, rows))

    assert result.raw_candidate_count == 1
    assert result.adjusted_candidate_count == 1
    assert result.raw_adjusted_identity_mismatch_count == 0


def test_missing_b7_candidate_is_preserved_as_uncovered(tmp_path: Path) -> None:
    rows = [_row()]
    paths = _paths(tmp_path, rows, b7_rows=[])

    result = FrozenBaselineReconstructor().reconstruct(paths)

    assert result.candidates[0].b7_present is False
    assert result.candidates[0].resolved_outcome is True


def test_missing_b10_candidate_is_preserved_as_unreached(tmp_path: Path) -> None:
    rows = [_row()]
    paths = _paths(tmp_path, rows, b10_rows=[])

    result = FrozenBaselineReconstructor().reconstruct(paths)

    assert result.candidates[0].b10_present is False


def test_rejects_extra_b7_candidate(tmp_path: Path) -> None:
    rows = [_row()]
    paths = _paths(
        tmp_path,
        rows,
        b7_rows=[_row(), _row(symbol="EXTRA", fingerprint="fp-extra")],
    )

    with pytest.raises(
        GateIsolationBaselineError,
        match="B7_IDENTITY_LINEAGE_MISMATCH",
    ):
        FrozenBaselineReconstructor().reconstruct(paths)


def test_rejects_extra_b10_candidate(tmp_path: Path) -> None:
    rows = [_row()]
    paths = _paths(
        tmp_path,
        rows,
        b10_rows=[_row(), _row(symbol="EXTRA", fingerprint="fp-extra")],
    )

    with pytest.raises(
        GateIsolationBaselineError,
        match="B10_IDENTITY_LINEAGE_MISMATCH",
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
    paths = _paths(tmp_path, rows, b10_rows=[_row(leakage="true")])

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
