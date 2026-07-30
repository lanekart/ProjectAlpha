from __future__ import annotations

from pathlib import Path

import pandas as pd

from alpha.decision_superiority.entry_stop_improvement_artifacts import (
    DSI009_ARTIFACTS,
)
from alpha.decision_superiority.structural_stop_risk_scaling_rehydration import (
    _parity_rows,
)


def test_parity_uses_frozen_signed_mechanism_not_current_winner(
    tmp_path: Path,
) -> None:
    pd.DataFrame(
        [
            {
                "mechanism_id": "STOP-ATR-225",
                "net_cagr": 0.30,
                "maximum_drawdown": -0.08,
                "calmar": 3.75,
                "win_rate": 0.70,
                "expectancy": 0.05,
                "trade_count": 60,
            },
            {
                "mechanism_id": "STOP-STRUCTURAL-10D",
                "net_cagr": 0.12,
                "maximum_drawdown": -0.10,
                "calmar": 1.20,
                "win_rate": 0.55,
                "expectancy": 0.02,
                "trade_count": 50,
            },
        ]
    ).to_csv(tmp_path / DSI009_ARTIFACTS["stop_results"], index=False)

    rows, passed = _parity_rows(
        base_metrics={
            "net_cagr": 0.12,
            "maximum_drawdown": -0.10,
            "calmar": 1.20,
            "win_rate": 0.55,
            "expectancy": 0.02,
            "trade_count": 50,
        },
        dsi009_certificate=tmp_path / "dsi009_entry_stop_certificate.json",
    )

    assert passed is True
    assert all(row["passed"] for row in rows)
