from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.decision_superiority.entry_stop_improvement import (
    _accepted_entry_champion,
    _accepted_stop_champion,
    _entry_fill,
    _entry_stop_attribution,
    _multiple_testing,
    _outer_signals,
    _readiness,
    _stop_level,
    _structural_probes,
    _validate_trade_path_count,
    default_entry_registry,
    default_stop_registry,
    governance_flags,
    validate_registries,
)
from alpha.decision_superiority.entry_stop_improvement_artifacts import (
    DSI009_ARTIFACTS,
    DSI009_CERTIFICATE,
    export_entry_stop_improvement,
    validate_entry_stop_improvement_certificate,
)
from alpha.decision_superiority.entry_stop_improvement_models import (
    EntryChallengerState,
    EntryStopImprovementError,
    EntryStopImprovementResult,
    EntryStopPolicy,
    FillState,
    StopChallengerState,
)


def test_governance_flags_are_all_false() -> None:
    flags = governance_flags()
    assert len(flags) == 20
    assert not any(flags.values())
    assert flags["LIVE_ENTRY_POLICY_ENABLED"] is False
    assert flags["LIVE_STOP_POLICY_ENABLED"] is False
    assert flags["PRODUCTION_INFLUENCE"] is False


def test_policy_and_mechanisms_are_immutable() -> None:
    policy = EntryStopPolicy()
    mechanism = default_entry_registry()[0]
    with pytest.raises(FrozenInstanceError):
        policy.minimum_challenger_trades = 1  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        mechanism.maximum_wait_sessions = 2  # type: ignore[misc]


def test_registries_are_bounded_unique_and_have_one_incumbent() -> None:
    entries = default_entry_registry()
    stops = default_stop_registry()
    validate_registries(entries, stops, policy=EntryStopPolicy())
    assert len(entries) == 7
    assert len(stops) == 6
    assert sum(item.incumbent for item in entries) == 1
    assert sum(item.incumbent for item in stops) == 1


def test_duplicate_and_unbounded_entry_registry_fail_closed() -> None:
    entries = default_entry_registry()
    stops = default_stop_registry()
    with pytest.raises(EntryStopImprovementError, match="DUPLICATE"):
        validate_registries(
            (*entries, entries[0]),
            stops,
            policy=EntryStopPolicy(maximum_entry_challengers=8),
        )
    with pytest.raises(EntryStopImprovementError, match="UNBOUNDED"):
        validate_registries(
            entries,
            stops,
            policy=EntryStopPolicy(maximum_entry_challengers=6),
        )


def test_outer_signal_population_uses_frozen_fold_regime_selection() -> None:
    signals = pd.DataFrame(
        [
            _signal_row("S-1", "A", "TRANSITION", "WF-2021"),
            _signal_row("S-2", "B", "TRANSITION", "WF-2021"),
            _signal_row("S-3", "A", "BEAR_TREND", "WF-2021"),
        ]
    )
    selections = pd.DataFrame(
        [
            {
                "walk_forward_fold_id": "WF-2021",
                "selection_scope": "REGIME:TRANSITION",
                "selected_strategy_variant_id": "A",
            },
            {
                "walk_forward_fold_id": "WF-2021",
                "selection_scope": "REGIME:BEAR_TREND",
                "selected_strategy_variant_id": "NO_TRADE",
            },
        ]
    )
    selected = _outer_signals(
        signals,
        selections=selections,
        policy=EntryStopPolicy(),
    )
    assert selected["signal_id"].tolist() == ["S-1"]


def test_outer_signal_population_excludes_right_censored_entries() -> None:
    eligible = _signal_row("S-1", "A", "TRANSITION", "WF-2021")
    right_censored = _signal_row("S-2", "A", "TRANSITION", "WF-2021")
    right_censored["signal_date"] = date(2025, 12, 24)
    right_censored["entry_eligibility_date"] = date(2025, 12, 26)
    selections = pd.DataFrame(
        [
            {
                "walk_forward_fold_id": "WF-2021",
                "selection_scope": "REGIME:TRANSITION",
                "selected_strategy_variant_id": "A",
            }
        ]
    )
    selected = _outer_signals(
        pd.DataFrame([eligible, right_censored]),
        selections=selections,
        policy=EntryStopPolicy(),
    )
    assert selected["signal_id"].tolist() == ["S-1"]


def test_missing_fold_regime_selection_fails_closed() -> None:
    signals = pd.DataFrame([_signal_row("S-1", "A", "TRANSITION", "WF-2021")])
    selections = pd.DataFrame(
        [
            {
                "walk_forward_fold_id": "WF-2021",
                "selection_scope": "REGIME:BEAR_TREND",
                "selected_strategy_variant_id": "NO_TRADE",
            }
        ]
    )
    with pytest.raises(EntryStopImprovementError, match="POLICY_MISSING"):
        _outer_signals(
            signals,
            selections=selections,
            policy=EntryStopPolicy(),
        )


def test_next_open_entry_is_executable_and_preserves_frozen_plan() -> None:
    fill = _entry_fill(
        _signal(),
        _bars(),
        default_entry_registry()[0],
        policy=EntryStopPolicy(),
    )
    assert fill["fill_state"] == FillState.ENTERED.value
    assert fill["entry_eligibility_date"] == date(2024, 1, 3)
    assert fill["raw_entry_price"] == 101.0
    assert fill["entry_price_after_slippage"] == 101.101
    assert fill["initial_stop"] == 90.0
    assert fill["target_1"] == 120.0
    assert fill["target_2"] == 130.0
    assert fill["impossible_fill"] is False


def test_close_confirmation_executes_only_on_following_open() -> None:
    fill = _entry_fill(
        _signal(),
        _bars(),
        default_entry_registry()[1],
        policy=EntryStopPolicy(),
    )
    assert fill["fill_state"] == FillState.ENTERED.value
    assert fill["entry_eligibility_date"] == date(2024, 1, 4)
    assert fill["raw_entry_price"] == 103.0


def test_retest_entry_waits_for_hold_then_uses_following_open() -> None:
    fill = _entry_fill(
        _signal(),
        _bars(),
        default_entry_registry()[2],
        policy=EntryStopPolicy(),
    )
    assert fill["fill_state"] == FillState.ENTERED.value
    assert fill["entry_eligibility_date"] == date(2024, 1, 5)
    assert fill["raw_entry_price"] == 102.0


def test_retest_never_reached_remains_unfilled() -> None:
    bars = _bars().assign(low=[101.0, 102.0, 103.0, 104.0])
    fill = _entry_fill(
        _signal(),
        bars,
        default_entry_registry()[2],
        policy=EntryStopPolicy(),
    )
    assert fill["fill_state"] == FillState.TRIGGER_NEVER_REACHED.value
    assert fill["raw_entry_price"] is None


def test_pullback_limit_uses_level_or_better_without_future_selection() -> None:
    fill = _entry_fill(
        _signal(),
        _bars(),
        default_entry_registry()[3],
        policy=EntryStopPolicy(),
    )
    assert fill["fill_state"] == FillState.ENTERED.value
    assert fill["raw_entry_price"] == 99.0
    assert fill["outer_test_used_for_rule_definition"] is False


def test_gap_filter_rejects_excessive_next_open() -> None:
    bars = _bars().copy()
    bars.loc[0, "open"] = 104.0
    fill = _entry_fill(
        _signal(),
        bars,
        default_entry_registry()[5],
        policy=EntryStopPolicy(),
    )
    assert fill["fill_state"] == FillState.GAP_BEYOND_ENTRY_LIMIT.value
    assert fill["raw_entry_price"] is None


def test_delayed_trigger_is_invalidated_when_stop_breaks_first() -> None:
    bars = _bars().copy()
    bars.loc[0, "low"] = 89.0
    fill = _entry_fill(
        _signal(),
        bars,
        default_entry_registry()[1],
        policy=EntryStopPolicy(),
    )
    assert fill["fill_state"] == FillState.INVALIDATED_BEFORE_ENTRY.value
    assert fill["entry_eligibility_date"] is None


def test_liquidity_rejection_is_explicit() -> None:
    signal = _signal()
    signal.average_traded_value20 = 1_000_000.0
    fill = _entry_fill(
        signal,
        _bars(),
        default_entry_registry()[0],
        policy=EntryStopPolicy(),
    )
    assert fill["fill_state"] == FillState.LIQUIDITY_REJECTED.value


def test_trade_path_count_reconciles_to_current_incumbent_population() -> None:
    _validate_trade_path_count(
        paths=[{"id": "P-1"}, {"id": "P-2"}],
        incumbent_trades=[{"id": "T-1"}, {"id": "T-2"}],
    )
    with pytest.raises(
        EntryStopImprovementError,
        match="UNRECONCILED_INCUMBENT_TRADE_COUNT:1:2",
    ):
        _validate_trade_path_count(
            paths=[{"id": "P-1"}],
            incumbent_trades=[{"id": "T-1"}, {"id": "T-2"}],
        )


def test_attribution_separates_entry_recovery_and_tail_protection() -> None:
    recovered = _trade_path(
        logical_trade_id="T-1",
        exit_reason="STOP",
        realised_return=-0.05,
        recovery_after_stop=True,
        recovery_date=date(2024, 1, 8),
        stop_date=date(2024, 1, 5),
        later_low=-0.02,
    )
    protected = _trade_path(
        logical_trade_id="T-2",
        exit_reason="STOP",
        realised_return=-0.05,
        recovery_after_stop=False,
        recovery_date=None,
        stop_date=date(2024, 1, 5),
        later_low=-0.20,
    )
    rows = _entry_stop_attribution(
        [recovered, protected],
        policy=EntryStopPolicy(),
    )
    assert rows[0]["primary_attribution"] == ("STOP_TOO_TIGHT_RECOVERED_QUICKLY")
    assert rows[1]["primary_attribution"] == "STOP_PREVENTED_LARGER_LOSS"
    assert all(row["diagnostic_not_causal"] for row in rows)


def test_entry_extension_classification_is_pre_registered() -> None:
    trade = _trade_path(
        logical_trade_id="T-1",
        exit_reason="TIME_EXIT",
        realised_return=-0.02,
        recovery_after_stop=False,
        recovery_date=None,
        stop_date=None,
        later_low=None,
    )
    trade["entry_extension_atr"] = 1.5
    row = _entry_stop_attribution(
        [trade],
        policy=EntryStopPolicy(maximum_entry_extension_atr=1.0),
    )[0]
    assert row["primary_attribution"] == "ENTRY_TOO_EXTENDED"
    assert row["definitions_frozen_before_classification"] is True


def test_stop_candidates_are_bounded_below_entry() -> None:
    row = pd.Series(
        {
            "entry_price_after_slippage": 100.0,
            "initial_stop": 92.0,
            "atr14": 4.0,
        }
    )
    stops = {item.mechanism_id: item for item in default_stop_registry()}
    assert _stop_level(row, stops["STOP-ATR-125"], support=None) == 95.0
    assert _stop_level(row, stops["STOP-ATR-225"], support=None) == 91.0
    assert _stop_level(row, stops["STOP-STRUCTURAL-10D"], support=94.0) == 94.0
    assert 0 < _stop_level(row, stops["STOP-MAX-RISK-080"], support=None) < 100


def test_descriptive_results_are_never_accepted_as_champions() -> None:
    assert (
        _accepted_entry_champion(
            [
                {
                    "mechanism_id": "ENTRY-X",
                    "state": EntryChallengerState.DESCRIPTIVELY_BETTER.value,
                }
            ]
        )
        is None
    )
    assert (
        _accepted_stop_champion(
            [
                {
                    "mechanism_id": "STOP-X",
                    "state": StopChallengerState.DESCRIPTIVELY_BETTER.value,
                }
            ]
        )
        is None
    )


def test_exactly_one_robust_challenger_can_be_named_for_research() -> None:
    assert (
        _accepted_entry_champion(
            [
                {
                    "mechanism_id": "ENTRY-X",
                    "state": EntryChallengerState.ROBUSTLY_BETTER.value,
                }
            ]
        )
        == "ENTRY-X"
    )
    assert (
        _accepted_entry_champion(
            [
                {
                    "mechanism_id": "ENTRY-X",
                    "state": EntryChallengerState.ROBUSTLY_BETTER.value,
                },
                {
                    "mechanism_id": "ENTRY-Y",
                    "state": EntryChallengerState.DIRECTIONALLY_STABLE.value,
                },
            ]
        )
        is None
    )


def test_multiple_testing_correction_retains_insufficient_fold_warning() -> None:
    entry = [
        {
            "mechanism_id": "ENTRY-X",
            "state": EntryChallengerState.REJECTED.value,
            "positive_fold_count": 1,
            "negative_fold_count": 0,
        }
    ]
    rows = _multiple_testing(entry, [])
    assert rows[0]["survives_bh_5pct"] is False
    assert rows[0]["survives_holm_5pct"] is False
    assert rows[0]["no_test_reason"] == "INSUFFICIENT_NON_TIED_FOLDS"


def test_benchmark_outperformance_does_not_create_alpha_readiness() -> None:
    readiness, blockers, grade = _readiness(
        trade_paths=[{"id": index} for index in range(56)],
        attribution_rows=[{"id": index} for index in range(56)],
        expected_incumbent_trade_count=56,
        entry_result_rows=[],
        stop_result_rows=[],
        portfolio_rows=[
            {
                "portfolio_name": "DSI008_INCUMBENT",
                "availability": "AVAILABLE",
                "net_cagr": 0.10,
            },
            {
                "portfolio_name": "NIFTY_500_TRI",
                "availability": "AVAILABLE",
                "net_cagr": 0.17,
            },
        ],
        tier_outcomes=[
            {
                "tier": "ALPHA_ELITE",
                "accuracy_target_supported": False,
            }
        ],
        multiple_rows=[],
        entry_champion=None,
        stop_champion=None,
    )
    assert readiness["G"] == "READY_WITH_NO_NET_WEALTH_IMPROVEMENT"
    assert grade == "NO_RELIABLE_ENTRY_STOP_IMPROVEMENT"
    assert "75 percent accuracy was not established" in blockers


def test_descriptive_alpha_improvement_is_reported_without_promotion() -> None:
    readiness, _, _ = _readiness(
        trade_paths=[{"id": index} for index in range(56)],
        attribution_rows=[{"id": index} for index in range(56)],
        expected_incumbent_trade_count=56,
        entry_result_rows=[],
        stop_result_rows=[
            {
                "mechanism_id": "STOP-X",
                "state": StopChallengerState.DESCRIPTIVELY_BETTER.value,
                "net_cagr": 0.16,
            }
        ],
        portfolio_rows=[
            {
                "portfolio_name": "DSI008_INCUMBENT",
                "availability": "AVAILABLE",
                "net_cagr": 0.10,
            }
        ],
        tier_outcomes=[
            {
                "tier": "ALPHA_ELITE",
                "accuracy_target_supported": False,
            }
        ],
        multiple_rows=[],
        entry_champion=None,
        stop_champion=None,
    )
    assert readiness["G"] == "READY_WITH_IMPROVEMENT_BUT_STILL_BELOW_BENCHMARK"
    assert readiness["I"] == "READY_WITH_NO_RELIABLE_ENTRY_STOP_IMPROVEMENT"


def test_structural_probes_are_separate_from_empirical_results() -> None:
    rows = _structural_probes()
    assert len(rows) == 19
    assert {row["probe"] for row in rows} >= {
        "WINNER_ENTERED_WELL",
        "IMPOSSIBLE_FILL_REJECTION",
        "SEQUENTIAL_SELECTION_LEAKAGE",
        "CERTIFICATE_TAMPERING",
    }
    assert not any(row["empirical_population_influence"] for row in rows)


def test_artifact_export_certificate_and_cli_validation(tmp_path: Path) -> None:
    paths = export_entry_stop_improvement(_result(), tmp_path)
    assert len(paths) == len(DSI009_ARTIFACTS) + 2
    payload = validate_entry_stop_improvement_certificate(
        tmp_path / DSI009_CERTIFICATE,
        require_ready=True,
    )
    assert payload["automatic_promotion_count"] == 0
    assert payload["forward_paper_eligible"] is False
    cli = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-entry-stop-improvement-verify",
            "--certificate",
            str(tmp_path / DSI009_CERTIFICATE),
            "--require-ready",
        ],
    )
    assert cli.exit_code == 0
    assert "DSI-009-v1.0.0" in cli.stdout
    assert "Certificate: VALID" in cli.stdout


def test_artifact_and_certificate_tampering_are_detected(tmp_path: Path) -> None:
    export_entry_stop_improvement(_result(), tmp_path)
    artifact = tmp_path / next(iter(DSI009_ARTIFACTS.values()))
    artifact.write_text(artifact.read_text("utf-8") + "tamper", "utf-8")
    with pytest.raises(EntryStopImprovementError, match="ARTIFACT_TAMPERED"):
        validate_entry_stop_improvement_certificate(tmp_path / DSI009_CERTIFICATE)


def test_export_is_byte_deterministic_and_portable(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    export_entry_stop_improvement(_result(), first)
    export_entry_stop_improvement(_result(), second)
    first_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in first.iterdir()
    }
    second_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in second.iterdir()
    }
    assert first_hashes == second_hashes
    assert not any(b"/Users/" in path.read_bytes() for path in first.iterdir())


def _signal_row(
    signal_id: str,
    strategy: str,
    regime: str,
    fold: str,
) -> dict[str, Any]:
    return {
        "signal_id": signal_id,
        "signal_date": date(2024, 1, 2),
        "entry_eligibility_date": date(2024, 1, 3),
        "walk_forward_fold_id": fold,
        "strategy_variant_id": strategy,
        "regime_state": regime,
    }


def _signal() -> SimpleNamespace:
    return SimpleNamespace(
        signal_id="S-1",
        identity_key="SEC-1",
        symbol="TEST",
        strategy_variant_id="TREND",
        walk_forward_fold_id="WF-2024",
        regime_state="BULL_TREND_LOW_VOLATILITY",
        signal_date=date(2024, 1, 2),
        entry_eligibility_date=date(2024, 1, 3),
        signal_strength=0.80,
        signal_close=100.0,
        entry_price=101.101,
        initial_stop=90.0,
        target_1=120.0,
        target_2=130.0,
        atr14=2.0,
        support10=95.0,
        maximum_holding_sessions=20,
        average_traded_value20=10_000_000.0,
    )


def _bars() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trading_date": date(2024, 1, 3),
                "open": 101.0,
                "high": 102.0,
                "low": 100.5,
                "close": 101.5,
            },
            {
                "trading_date": date(2024, 1, 4),
                "open": 103.0,
                "high": 104.0,
                "low": 99.0,
                "close": 100.5,
            },
            {
                "trading_date": date(2024, 1, 5),
                "open": 102.0,
                "high": 105.0,
                "low": 101.0,
                "close": 104.0,
            },
            {
                "trading_date": date(2024, 1, 8),
                "open": 105.0,
                "high": 107.0,
                "low": 104.0,
                "close": 106.0,
            },
        ]
    )


def _trade_path(
    *,
    logical_trade_id: str,
    exit_reason: str,
    realised_return: float,
    recovery_after_stop: bool,
    recovery_date: date | None,
    stop_date: date | None,
    later_low: float | None,
) -> dict[str, Any]:
    return {
        "logical_trade_id": logical_trade_id,
        "symbol": "TEST",
        "walk_forward_fold_id": "WF-2024",
        "exit_date": date(2024, 1, 10),
        "regime_at_signal": "TRANSITION",
        "strategy_variant_id": "TREND",
        "setup": "TREND",
        "realised_return": realised_return,
        "net_pnl": realised_return * 1000,
        "incumbent_entry": 100.0,
        "stop": 95.0,
        "entry_extension_atr": 0.5,
        "mfe": 0.08,
        "mae": -0.06,
        "recovery_after_stop": recovery_after_stop,
        "recovery_date": recovery_date,
        "stop_date": stop_date,
        "lowest_subsequent_return_after_stop": later_low,
        "exit_reason": exit_reason,
    }


def _result() -> EntryStopImprovementResult:
    rows: dict[str, tuple[dict[str, Any], ...]] = {
        key: ({"state": f"{key}:OBSERVED"},) for key in DSI009_ARTIFACTS
    }
    rows["source_contract"] = (
        {
            "source_role": "DSI008_CERTIFICATE",
            "contract_version": "DSI-008-v1.0.0",
            "sha256": "a" * 64,
            "used_for_selection": False,
            "used_for_outer_evaluation": True,
        },
        {
            "source_role": "DSI007_CERTIFICATE",
            "contract_version": "DSI-007-v1.0.0",
            "sha256": "b" * 64,
            "used_for_selection": True,
            "used_for_outer_evaluation": True,
        },
    )
    tier = {
        "completed_trades": 20,
        "observed_accuracy": 0.55,
        "wilson_lower": 0.34,
        "wilson_upper": 0.74,
        "expectancy": 0.03,
        "target_status": "75_PERCENT_TARGET_NOT_ESTABLISHED",
    }
    summaries = {
        "incumbent": {
            "availability": "AVAILABLE",
            "starting_capital": 1_000_000.0,
            "ending_capital": 1_655_122.0,
            "net_cagr": 0.1065,
            "maximum_drawdown": -0.0718,
            "sharpe": 1.34,
            "sortino": 0.94,
            "calmar": 1.48,
            "trade_count": 56,
            "costs": 43_003.0,
            "turnover": 1.7547,
            "exposure": 0.5068,
            "time_in_market": 0.8945,
            "benchmark_cagr": 0.1682,
            "excess_cagr": -0.0617,
            "portfolio_name": "DSI007_INCUMBENT",
        },
        "incumbent_replay": {
            "starting_capital": 1_000_000.0,
            "ending_capital": 1_655_122.0,
            "net_cagr": 0.1065,
            "maximum_drawdown": -0.0718,
            "sharpe": 1.34,
            "sortino": 0.94,
            "calmar": 1.48,
            "trade_count": 56,
            "win_rate": 0.5179,
            "expectancy": 0.063,
            "total_costs": 43_003.0,
            "turnover": 1.7547,
            "excess_cagr": -0.0617,
        },
        "benchmark": {"cagr": 0.1682},
        "early_entry_count": 5,
        "extended_entry_count": 1,
        "loss_attribution": {"ENTRY_TOO_EARLY_RECOVERED_AFTER_STOP": 5},
        "stop_value": {"STOP_PREVENTED_TAIL_LOSS": 8},
        "entry_challengers_tested": 6,
        "entry_champion": None,
        "stop_challengers_tested": 5,
        "stop_champion": None,
        "sequential_champion": None,
        "improved_portfolio": None,
        "benchmark_gap_closed": None,
        "best_descriptive_result": None,
        "descriptive_benchmark_gap_closed": None,
        "descriptive_remaining_benchmark_gap": None,
        "tiers": {
            "ALPHA_STANDARD": tier,
            "ALPHA_HIGH_CONVICTION": tier,
            "ALPHA_ELITE": tier,
        },
        "multiple_testing_survived": False,
        "robustness_grade": "NO_RELIABLE_ENTRY_STOP_IMPROVEMENT",
        "forward_paper_eligible": False,
        "fresh_holdout_available": False,
        "interpretation": "Descriptive research only.",
    }
    readiness = MappingProxyType(
        {
            "A": "READY_FOR_GOVERNED_ENTRY_PATH_RESEARCH",
            "B": "READY_FOR_GOVERNED_ENTRY_STOP_ATTRIBUTION",
            "C": "READY_FOR_GOVERNED_ENTRY_CHALLENGERS",
            "D": "READY_WITH_NO_BETTER_ENTRY_MECHANISM",
            "E": "READY_FOR_GOVERNED_STOP_VALUE_RESEARCH",
            "F": "READY_WITH_NO_BETTER_STOP_MECHANISM",
            "G": "READY_WITH_NO_NET_WEALTH_IMPROVEMENT",
            "H": "READY_WITH_NO_RELIABLE_IMPROVEMENT",
            "I": "READY_WITH_NO_RELIABLE_ENTRY_STOP_IMPROVEMENT",
        }
    )
    return EntryStopImprovementResult(
        source_commit="c" * 40,
        readiness=readiness,
        blockers=("No fresh unused holdout.",),
        rows=MappingProxyType(rows),
        summaries=MappingProxyType(summaries),
        governance=MappingProxyType(governance_flags()),
    )
