from __future__ import annotations

import csv
import json
from pathlib import Path

from alpha.decision_superiority.intraday_execution_population import (
    IntradayPopulationPlan,
    plan_intraday_population,
)
from alpha.decision_superiority.intraday_plan_artifacts import (
    DSI013_DAILY_REFERENCE_TEMPLATE,
    DSI013_PLAN_CANDIDATES,
    DSI013_PLAN_REQUESTS,
    DSI013_PLAN_SUMMARY,
    export_intraday_population_plan,
)


def _plan() -> IntradayPopulationPlan:
    result = plan_intraday_population(
        (
            {
                "mechanism_id": "ENTRY-INCUMBENT-NEXT-OPEN",
                "fill_state": "ENTERED",
                "signal_id": "SIG-1",
                "identity_key": "nse:isin:INE000A01000",
                "symbol": "ALPHA",
                "strategy_variant_id": "STRATEGY-1",
                "walk_forward_fold_id": "WF-2024",
                "regime": "BULL",
                "signal_date": "2024-01-02",
                "entry_eligibility_date": "2024-01-03",
                "signal_strength": "0.75",
                "raw_entry_price": "100.00",
                "entry_price_after_slippage": "100.10",
                "initial_stop": "95.00",
                "target_1": "110.00",
                "target_2": "115.00",
                "maximum_holding_sessions": "20",
                "average_traded_value20": "10000000",
            },
        )
    )
    return IntradayPopulationPlan(
        candidates=result.candidates,
        requests=result.requests,
        exclusions=result.exclusions,
        reconciliation=result.reconciliation,
        dsi009_certificate_sha256="d" * 64,
    )


def test_plan_export_is_candidate_bounded_and_credential_free(tmp_path: Path) -> None:
    paths = export_intraday_population_plan(_plan(), tmp_path)

    assert {path.name for path in paths} == {
        DSI013_PLAN_SUMMARY,
        DSI013_PLAN_CANDIDATES,
        DSI013_PLAN_REQUESTS,
        DSI013_DAILY_REFERENCE_TEMPLATE,
    }
    summary = json.loads((tmp_path / DSI013_PLAN_SUMMARY).read_text(encoding="utf-8"))
    assert summary["candidate_count"] == 1
    assert summary["unique_request_count"] == 1
    assert summary["credential_fields_present"] is False
    assert summary["full_universe_intraday_sweep"] is False
    assert summary["one_minute_strategy_mining"] is False
    assert summary["production_influence"] is False

    request_rows = list(
        csv.DictReader(
            (tmp_path / DSI013_PLAN_REQUESTS).open(
                encoding="utf-8",
                newline="",
            )
        )
    )
    assert request_rows == [
        {
            "identity_key": "nse:isin:INE000A01000",
            "session_date": "2024-01-03",
            "signal_count": "1",
            "signal_ids": "SIG-1",
        }
    ]

    template_rows = list(
        csv.DictReader(
            (tmp_path / DSI013_DAILY_REFERENCE_TEMPLATE).open(
                encoding="utf-8",
                newline="",
            )
        )
    )
    assert template_rows[0]["identity_key"] == "nse:isin:INE000A01000"
    assert template_rows[0]["session_date"] == "2024-01-03"
    assert template_rows[0]["price_basis"] == "RAW"
    assert template_rows[0]["open"] == ""
    assert template_rows[0]["source_sha256"] == ""
