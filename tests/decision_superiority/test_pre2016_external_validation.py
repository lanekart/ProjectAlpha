from __future__ import annotations

from datetime import date
from types import MappingProxyType

import pandas as pd
import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.application.decision_superiority_pre2016_external_validation_cli import (
    _validate_external_dates,
)
from alpha.decision_superiority.pre2016_external_validation import (
    _apply_frozen_structural_stop,
    _classification,
    _structural_stop_level,
    governance_flags,
)
from alpha.decision_superiority.pre2016_external_validation_artifacts import (
    DSI010_ARTIFACTS,
    DSI010_CERTIFICATE,
    export_pre2016_external_validation,
    validate_pre2016_external_validation_certificate,
)
from alpha.decision_superiority.pre2016_external_validation_models import (
    DSI010_EXTERNAL_END,
    DSI010_EXTERNAL_START,
    ExternalValidationClassification,
    Pre2016ExternalValidationError,
    Pre2016ExternalValidationPolicy,
    Pre2016ExternalValidationResult,
)


def test_policy_is_frozen_before_2016() -> None:
    policy = Pre2016ExternalValidationPolicy()
    assert policy.external_start == date(2005, 1, 1)
    assert policy.external_end == date(2015, 12, 31)
    assert policy.frozen_challenger_id == "STOP-STRUCTURAL-10D"


def test_policy_rejects_2016_overlap() -> None:
    with pytest.raises(
        Pre2016ExternalValidationError,
        match="PRE2016_HOLDOUT_OVERLAPS_2016",
    ):
        Pre2016ExternalValidationPolicy(external_end=date(2016, 1, 1))


def test_policy_rejects_challenger_identity_drift() -> None:
    with pytest.raises(
        Pre2016ExternalValidationError,
        match="FROZEN_CHALLENGER_ID_DRIFT",
    ):
        Pre2016ExternalValidationPolicy(frozen_challenger_id="STOP-STRUCTURAL-20D")


def test_archive_command_rejects_any_non_frozen_range() -> None:
    with pytest.raises(ValueError, match="frozen to 2005-01-01"):
        _validate_external_dates(date(2006, 1, 1), date(2015, 12, 31))
    with pytest.raises(ValueError, match="cannot include 2016"):
        _validate_external_dates(date(2005, 1, 1), date(2016, 1, 1))


def test_structural_stop_uses_point_in_time_support_only() -> None:
    row = pd.Series(
        {
            "raw_entry_price": 100.0,
            "initial_stop": 90.0,
            "support10": 95.0,
            "future_low": 70.0,
        }
    )
    assert _structural_stop_level(row, slippage_fraction=0.001) == 95.0


def test_structural_stop_falls_back_to_incumbent_without_support() -> None:
    row = pd.Series(
        {
            "raw_entry_price": 100.0,
            "initial_stop": 90.0,
            "support10": None,
        }
    )
    assert _structural_stop_level(row, slippage_fraction=0.001) == 90.0


def test_structural_stop_is_clipped_below_executable_entry() -> None:
    row = pd.Series(
        {
            "raw_entry_price": 100.0,
            "initial_stop": 90.0,
            "support10": 110.0,
        }
    )
    assert _structural_stop_level(row, slippage_fraction=0.001) == 100.09


def test_challenger_changes_only_initial_stop() -> None:
    selected = pd.DataFrame(
        [
            {
                "signal_id": "S-1",
                "raw_entry_price": 100.0,
                "initial_stop": 90.0,
                "support10": 95.0,
                "target_1": 120.0,
                "target_2": 130.0,
                "target_3": 140.0,
            }
        ]
    )
    challenger = _apply_frozen_structural_stop(
        selected,
        slippage_fraction=0.001,
    )
    assert challenger.loc[0, "incumbent_initial_stop"] == 90.0
    assert challenger.loc[0, "initial_stop"] == 95.0
    assert challenger.loc[0, "target_1"] == 120.0
    assert challenger.loc[0, "target_2"] == 130.0
    assert challenger.loc[0, "target_3"] == 140.0
    assert not bool(challenger.loc[0, "external_data_used_for_stop_selection"])


def test_external_classification_requires_sufficient_sample() -> None:
    classification = _classification(
        incumbent=_metrics(cagr=0.10, trades=50),
        challenger=_metrics(cagr=0.20, trades=10),
        benchmark={"net_cagr": 0.15},
        top_five_profit_share=0.30,
        policy=Pre2016ExternalValidationPolicy(),
    )
    assert classification is ExternalValidationClassification.INSUFFICIENT_SAMPLE


def test_external_classification_detects_high_concentration() -> None:
    classification = _classification(
        incumbent=_metrics(cagr=0.10),
        challenger=_metrics(cagr=0.20),
        benchmark={"net_cagr": 0.15},
        top_five_profit_share=0.80,
        policy=Pre2016ExternalValidationPolicy(),
    )
    assert classification is ExternalValidationClassification.HIGH_CONCENTRATION


def test_external_classification_distinguishes_benchmark_outperformance() -> None:
    beats_benchmark = _classification(
        incumbent=_metrics(cagr=0.10),
        challenger=_metrics(cagr=0.18),
        benchmark={"net_cagr": 0.15},
        top_five_profit_share=0.30,
        policy=Pre2016ExternalValidationPolicy(),
    )
    closes_gap = _classification(
        incumbent=_metrics(cagr=0.10),
        challenger=_metrics(cagr=0.14),
        benchmark={"net_cagr": 0.15},
        top_five_profit_share=0.30,
        policy=Pre2016ExternalValidationPolicy(),
    )
    assert beats_benchmark is ExternalValidationClassification.BEATS_BENCHMARK
    assert closes_gap is ExternalValidationClassification.BEATS_INCUMBENT_NOT_BENCHMARK


def test_governance_flags_are_all_false() -> None:
    flags = governance_flags()
    assert flags
    assert not any(flags.values())
    assert flags["STOP_POLICY_AUTOMATIC_PROMOTION_ENABLED"] is False
    assert flags["PRODUCTION_INFLUENCE"] is False


def test_artifact_export_and_public_validation(tmp_path) -> None:  # type: ignore[no-untyped-def]
    paths = export_pre2016_external_validation(_result(), tmp_path)
    certificate = tmp_path / DSI010_CERTIFICATE
    payload = validate_pre2016_external_validation_certificate(
        certificate,
        require_ready=True,
    )
    assert len(paths) == len(DSI010_ARTIFACTS) + 2
    assert payload["external_tuning_performed"] is False
    assert payload["challenger_contract_changed"] is False
    assert payload["automatic_promotion_count"] == 0
    assert payload["readiness_decision"].startswith("READY_")


def test_artifact_tamper_is_detected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    export_pre2016_external_validation(_result(), tmp_path)
    support = tmp_path / DSI010_ARTIFACTS["protocol"]
    support.write_text(support.read_text(encoding="utf-8") + "tampered\n")
    with pytest.raises(
        Pre2016ExternalValidationError,
        match="DSI010_ARTIFACT_TAMPERED",
    ):
        validate_pre2016_external_validation_certificate(tmp_path / DSI010_CERTIFICATE)


def test_cli_commands_are_registered() -> None:
    result = CliRunner().invoke(benchmark_app, ["--help"])
    assert result.exit_code == 0
    assert "decision-superiority-pre2016-archive-backfill" in result.stdout
    assert "decision-superiority-pre2016-external-validation" in result.stdout
    assert "decision-superiority-pre2016-external-validation-verify" in result.stdout


def _metrics(*, cagr: float, trades: int = 50) -> dict[str, object]:
    return {
        "portfolio_name": "PORTFOLIO",
        "net_cagr": cagr,
        "maximum_drawdown": -0.10,
        "trade_count": trades,
        "win_rate": 0.60,
        "expectancy": 0.05,
    }


def _result() -> Pre2016ExternalValidationResult:
    rows = {key: tuple() for key in DSI010_ARTIFACTS}
    rows["protocol"] = (
        {
            "external_start": DSI010_EXTERNAL_START,
            "external_end": DSI010_EXTERNAL_END,
            "external_period_used_for_tuning": False,
        },
    )
    rows["frozen_contract"] = (
        {
            "candidate_id": "STOP-STRUCTURAL-10D",
            "contract_frozen": True,
        },
    )
    readiness = {
        "A": "READY_FOR_PRE2016_EXTERNAL_VALIDATION",
        "B": "READY_FOR_GOVERNED_PRE2016_MARKET_REPLAY",
        "C": "READY_FOR_GOVERNED_PRE2016_POINT_IN_TIME_UNIVERSE",
        "D": "READY_FOR_GOVERNED_PRE2016_TRI_COMPARISON",
        "E": "READY_FOR_GOVERNED_FROZEN_STOP_EXTERNAL_TEST",
        "F": "READY_FOR_GOVERNED_PRE2016_WALK_FORWARD_REPLICATION",
        "G": "READY_FOR_GOVERNED_PRE2016_PERFORMANCE_COMPARISON",
        "H": "READY_FOR_GOVERNED_EXTERNAL_VALIDITY_CONCLUSION",
        "I": "READY_WITH_DIRECTIONAL_EXTERNAL_SUPPORT",
    }
    summaries = {
        "external_start": DSI010_EXTERNAL_START,
        "external_end": DSI010_EXTERNAL_END,
        "actual_transport_start": date(2007, 1, 2),
        "actual_transport_end": DSI010_EXTERNAL_END,
        "frozen_challenger_id": "STOP-STRUCTURAL-10D",
        "market_sessions": 2200,
        "market_securities": 300,
        "market_rows": 300_000,
        "incumbent": _metrics(cagr=0.10),
        "challenger": _metrics(cagr=0.14),
        "benchmark": {
            "portfolio_name": "TOTAL_RETURN_INDEX_BENCHMARK",
            "net_cagr": 0.15,
        },
        "benchmark_gap_closed": 0.80,
        "replication_regime_aware": _metrics(cagr=0.12),
        "replication_benchmark": {"net_cagr": 0.15},
        "classification": (
            ExternalValidationClassification.BEATS_INCUMBENT_NOT_BENCHMARK.value
        ),
        "top_five_positive_profit_share": 0.40,
        "external_tuning_performed": False,
        "challenger_contract_changed": False,
        "forward_paper_eligible": True,
    }
    return Pre2016ExternalValidationResult(
        source_commit="abc123",
        readiness=MappingProxyType(readiness),
        blockers=(),
        rows=MappingProxyType(rows),
        summaries=MappingProxyType(summaries),
        governance=MappingProxyType(governance_flags()),
    )
