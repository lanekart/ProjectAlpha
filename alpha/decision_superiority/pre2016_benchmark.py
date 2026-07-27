"""Official TRI adapter for the frozen DSI-010 external era."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from alpha.decision_superiority.performance_improvement import load_governed_tri


def load_pre2016_governed_tri(
    benchmark_path: Path,
    *,
    sessions: Sequence[date],
    start: date,
    end: date,
) -> tuple[pd.DataFrame, tuple[dict[str, Any], ...]]:
    """Load the provenance-bound official TRI and align it to governed sessions."""

    benchmark, provenance, contract = load_governed_tri(benchmark_path)
    frame = benchmark.rename(
        columns={
            "date": "trading_date",
            "value": "benchmark_value",
        }
    ).copy()
    frame = frame.loc[frame["trading_date"].between(start, end)]
    governed_sessions = set(sessions)
    frame = frame.loc[frame["trading_date"].isin(governed_sessions)]
    frame = frame.sort_values("trading_date", kind="stable").reset_index(drop=True)

    observed_sessions = set(frame["trading_date"])
    expected_sessions = {
        session for session in governed_sessions if start <= session <= end
    }
    missing_sessions = expected_sessions - observed_sessions
    status = (
        "AVAILABLE_TOTAL_RETURN"
        if len(frame) >= 2 and not missing_sessions
        else "PARTIAL_TOTAL_RETURN"
        if len(frame) >= 2
        else "UNAVAILABLE_EXTERNAL_PERIOD"
    )
    row = {
        **contract,
        "status": status,
        "external_start": start,
        "external_end": end,
        "expected_governed_sessions": len(expected_sessions),
        "aligned_observed_sessions": len(observed_sessions),
        "missing_governed_sessions": len(missing_sessions),
        "index_identifier": provenance.index_identifier,
        "index_name": provenance.index_name,
        "benchmark_kind": provenance.benchmark_kind.value,
        "used_for_external_superiority": status == "AVAILABLE_TOTAL_RETURN",
    }
    return frame, (row,)


__all__ = ["load_pre2016_governed_tri"]
