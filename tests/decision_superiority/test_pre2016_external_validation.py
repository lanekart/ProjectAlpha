from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pandas as pd
import pytest

from alpha.decision_superiority.pre2016_external_validation import (
    _apply_structural_stop,
    _external_classification,
    _latest_frozen_mapping,
    governance_flags,
)
from alpha.decision_superiority.pre2016_external_validation_artifacts import (
    DSI010_ARTIFACTS,
    DSI010_CERTIFICATE,
    export_pre2016_external_validation,
    validate_pre2016_external_validation_certificate,
)
from alpha.decision_superiority.pre2016_external_validation_models import (
    Pre2016ExternalValidationError,
    Pre2016ExternalValidationPolicy,
    Pre2016ExternalValidationResult,
)


def test_policy_rejects_discovery_era_overlap() -> None:
    with pytest.raises(
        Pre2016ExternalValidationError,
        match="EXTERNAL_PERIOD_OVERLAPS_DISCOVERY_ERA",
    ):
        Pre2016ExternalValidationPolicy(external_end="2016-01-01")


def test_policy_freezes_structural_stop() -> None:
    policy = Pre2016ExternalValidationPolicy()
    assert policy.external_start == "2005-01-01"
    assert policy.external_end == "2015-12-31"
    assert policy.frozen_challenger_id == "STOP-STRUCTURAL-10D"


def test_governance_is_research_only() -> None:
    flags = governance_flags()
    assert flags
    assert all(value is False for value in flags.values())
    assert flags["PRODUCTION_INFLUENCE"] is False
    assert flags["STOP_POLICY_AUTOMATIC_PROMOTION_ENABLED"] is False


def test_latest_frozen_mapping_uses_last_dsi007_fold(tmp_path: Path) -> None:
    mapping = tmp_path / "dsi007_regime_strategy_mapping.csv"
    mapping.write_text(
        "walk_forward_fold_id,regime_state,"
        "selected_strategy_variant_id,test_end\n"
        "WF-2024,BEAR_TREND,NO_TRADE,2024-12-31\n"
        "WF-2025,BEAR_TREND,TREND_FOLLOWING_60D_V1,2025-12-24\n"
        "WF-2025,BULL_TREND_LOW_VOLATILITY,"
        "RS_CONTINUATION_V1,2025-12-24\n"
    )
    frozen, rows = _latest_frozen_mapping(tmp_path)
    assert frozen == {
        "BEAR_TREND": "TREND_FOLLOWING_60D_V1",
        "BULL_TREND_LOW_VOLATILITY": "RS_CONTINUATION_V1",
    }
    assert len(rows) == 2
    assert all(
        row["external_results_used_for_mapping"] is False for row in rows
    )


def test_structural_stop_uses_prior_ten_session_support() -> None:
    sessions = pd.date_range("2005-01-01", periods=12, freq="D").date
    featured = pd.DataFrame(
        {
            "identity_key": ["ABC"] * 12,
            "trading_date": sessions,
            "low": [
                100.0,
                99.0,
                98.0,
                97.0,
                96.0,
                95.0,
                94.0,
                93.0,
                92.0,
                91.0,
                90.0,
                89.0,
            ],
        }
    )
    selected = pd.DataFrame(
        [
            {
                "signal_id": "SIG-1",
                "identity_key": "ABC",
                "trading_date": sessions[10],
                "entry_eligibility_date": sessions[11],
                "signal_strength": 1.0,
                "entry_price": 105.0,
                "initial_stop": 101.0,
                "trade_plan_id": "PLAN-1",
            }
        ]
    )
    challenged = _apply_structural_stop(selected, featured)
    assert challenged.iloc[0]["initial_stop"] == 91.0
    assert challenged.iloc[0]["trade_plan_id"] != "PLAN-1"


def test_external_classification_requires_minimum_sample() -> None:
    state = _external_classification(
        {"net_cagr": 0.10, "maximum_drawdown": -0.10},
        {
            "net_cagr": 0.20,
            "maximum_drawdown": -0.08,
            "trade_count": 5,
        },
        {"net_cagr": 0.15},
        minimum_trades=20,
    )
    assert state == "INSUFFICIENT_EXTERNAL_SAMPLE"


def test_external_classification_can_beat_benchmark() -> None:
    state = _external_classification(
        {"net_cagr": 0.10, "maximum_drawdown": -0.10},
        {
            "net_cagr": 0.20,
            "maximum_drawdown": -0.08,
            "trade_count": 25,
        },
        {"net_cagr": 0.15},
        minimum_trades=20,
    )
    assert state == "CHALLENGER_BEATS_BENCHMARK"


def test_artifact_package_round_trip_and_tamper_detection(
    tmp_path: Path,
) -> None:
    rows = {
        key: (
            {
                "artifact": key,
                "value": 1,
            },
        )
        for key in DSI010_ARTIFACTS
    }
    result = Pre2016ExternalValidationResult(
        source_commit="abc123",
        readiness=MappingProxyType(
            {
                "A": "READY_FOR_PRE2016_EXTERNAL_VALIDATION",
                "B": "READY_FOR_GOVERNED_PRE2016_MARKET_REPLAY",
                "C": "READY_FOR_GOVERNED_PRE2016_POINT_IN_TIME_UNIVERSE",
                "D": "READY_FOR_GOVERNED_PRE2016_TRI_COMPARISON",
                "E": "READY_FOR_GOVERNED_FROZEN_STOP_EXTERNAL_TEST",
                "F": "READY_FOR_GOVERNED_WALK_FORWARD_SELECTION",
                "G": "READY_FOR_GOVERNED_PRE2016_PERFORMANCE_COMPARISON",
                "H": "READY_FOR_GOVERNED_EXTERNAL_VALIDITY_CONCLUSION",
                "I": "READY_FOR_EXTENDED_FORWARD_PAPER_VALIDATION",
            }
        ),
        blockers=(),
        rows=MappingProxyType(rows),
        summaries=MappingProxyType(
            {
                "protocol": {
                    "external_start": "2005-01-01",
                    "external_end": "2015-12-31",
                },
                "source_coverage": {
                    "actual_start": "2005-01-01",
                    "actual_end": "2015-12-31",
                },
                "frozen_mapping": {"BEAR_TREND": "NO_TRADE"},
                "test_a_incumbent": {
                    "net_cagr": 0.10,
                    "maximum_drawdown": -0.10,
                    "trade_count": 20,
                },
                "test_a_challenger": {
                    "net_cagr": 0.20,
                    "maximum_drawdown": -0.08,
                    "trade_count": 20,
                },
                "benchmark": {"net_cagr": 0.15},
                "test_b_regime_aware": {
                    "net_cagr": 0.12,
                    "maximum_drawdown": -0.09,
                    "trade_count": 20,
                },
                "test_b_fixed": {"net_cagr": 0.05},
                "test_b_momentum": {"net_cagr": 0.08},
                "test_b_trend": {"net_cagr": 0.07},
                "external_validation_classification": (
                    "CHALLENGER_BEATS_BENCHMARK"
                ),
                "forward_paper_eligible": True,
                "automatic_promotion_count": 0,
            }
        ),
        governance=MappingProxyType(governance_flags()),
    )
    paths = export_pre2016_external_validation(result, tmp_path)
    assert len(paths) == len(DSI010_ARTIFACTS) + 2
    certificate = tmp_path / DSI010_CERTIFICATE
    payload = validate_pre2016_external_validation_certificate(
        certificate,
        require_ready=True,
    )
    assert (
        payload["external_validation_classification"]
        == "CHALLENGER_BEATS_BENCHMARK"
    )

    support = tmp_path / next(iter(DSI010_ARTIFACTS.values()))
    support.write_text(support.read_text() + "tampered\n")
    with pytest.raises(
        Pre2016ExternalValidationError,
        match="DSI010_ARTIFACT_TAMPERED",
    ):
        validate_pre2016_external_validation_certificate(certificate)
