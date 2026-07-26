from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.decision_superiority.regime_strategy_artifacts import (
    DSI007_ARTIFACTS,
    DSI007_CERTIFICATE,
    DSI007_REPORT,
    export_regime_strategy_tournament,
    validate_regime_strategy_tournament_certificate,
)
from alpha.decision_superiority.regime_strategy_models import (
    BenchmarkStatus,
    RegimeState,
    StrategyFamily,
    StrategyVariant,
    TournamentError,
    TournamentPolicy,
    TournamentSourcePaths,
)
from alpha.decision_superiority.regime_strategy_tournament import (
    GovernedRegimeStrategyTournamentEngine,
    _benjamini_hochberg,
    _build_point_in_time_features,
    _classify_regime,
    _holm,
    _independent_trade_outcome,
    _load_benchmark,
    _multiple_testing,
    _portfolio_metrics,
    _walk_forward_folds,
    default_strategy_registry,
    governance_flags,
    structural_probe_rows,
    validate_strategy_registry,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_START = date(2016, 1, 1)
_END = date(2023, 12, 29)


@pytest.fixture(scope="module")
def tournament_inputs(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("dsi007")
    database = root / "historical_truth.duckdb"
    snapshots = root / "snapshots"
    snapshots.mkdir()
    (snapshots / "contract.json").write_text(
        '{"contract":"TEST_SNAPSHOT"}\n',
        encoding="utf-8",
    )
    dates = pd.bdate_range(_START, _END)
    market_rows: list[dict[str, Any]] = []
    lineage_rows: list[dict[str, Any]] = []
    identities: list[dict[str, Any]] = []
    memberships: list[dict[str, Any]] = []
    price_basis: list[dict[str, Any]] = []
    for symbol_index, symbol in enumerate(("ALPHA", "BETA", "GAMMA"), start=1):
        isin = f"INE0000000{symbol_index}"
        identity = f"nse:isin:{isin}"
        identities.append(
            {
                "contract_version": "TEST-v1",
                "identity_key": identity,
                "isin": isin,
                "valid_from": _START,
                "valid_to": _END,
                "confidence_state": "HIGH",
            }
        )
        memberships.append(
            {
                "contract_version": "TEST-v1",
                "identity_key": identity,
                "valid_from": _START,
                "valid_to": _END,
                "state": "CERTIFIED_ACTIVE_TRADABLE",
                "tradable": True,
                "source_event_ids": "TEST",
                "identity_days": len(dates),
                "issue_codes": "[]",
            }
        )
        price_basis.append(
            {
                "contract_version": "TEST-v1",
                "identity_key": identity,
                "valid_from": _START,
                "valid_to": _END,
                "state": "BACKWARD_ADJUSTED",
                "action_ids": "",
                "known_factor_count": 1,
                "unknown_factor_count": 0,
                "raw_row_count": len(dates),
                "adjusted_row_count": len(dates),
                "issue_codes": "[]",
            }
        )
        close = 80.0 + symbol_index * 20.0
        for index, timestamp in enumerate(dates):
            cycle = np.sin(index / 35.0 + symbol_index) * 0.008
            drift = 0.00045 + symbol_index * 0.00005
            if index % 180 in range(0, 25):
                drift += 0.002
            close *= 1.0 + drift + cycle
            open_price = close * (1.0 - 0.002)
            high = max(open_price, close) * 1.012
            low = min(open_price, close) * 0.988
            volume = 1_500_000 + symbol_index * 100_000
            if index % 60 == 0:
                volume *= 2
            source_hash = hashlib.sha256(
                f"{timestamp.date()}|{symbol}".encode()
            ).hexdigest()
            market_rows.append(
                {
                    "contract_version": "HTR-009B-v1.0.0",
                    "trading_date": timestamp.date(),
                    "exchange": "NSE",
                    "symbol": symbol,
                    "series": "EQ",
                    "isin": isin,
                    "raw_open": open_price,
                    "raw_high": high,
                    "raw_low": low,
                    "raw_close": close,
                    "raw_volume": volume,
                    "price_factor": 1.0,
                    "quantity_factor": 1.0,
                    "adjusted_open": open_price,
                    "adjusted_high": high,
                    "adjusted_low": low,
                    "adjusted_close": close,
                    "adjusted_volume": volume,
                    "action_ids": "",
                    "calculation_version": "test-adjustment-v1",
                    "as_of_date": _END,
                }
            )
            lineage_rows.append(
                {
                    "contract_version": "HTR-009B-v1.0.0",
                    "trading_date": timestamp.date(),
                    "exchange": "NSE",
                    "symbol": symbol,
                    "series": "EQ",
                    "raw_source_sha256": source_hash,
                    "action_ids": "",
                    "factor_ids": "",
                    "lineage_digest": source_hash,
                }
            )
    connection = duckdb.connect(str(database))
    try:
        _create_table(connection, "adjusted_daily_candle", pd.DataFrame(market_rows))
        _create_table(
            connection,
            "adjusted_candle_lineage",
            pd.DataFrame(lineage_rows),
        )
        _create_table(
            connection,
            "security_isin_interval_complete",
            pd.DataFrame(identities),
        )
        _create_table(
            connection,
            "security_membership_interval_complete",
            pd.DataFrame(memberships),
        )
        _create_table(
            connection,
            "price_basis_interval",
            pd.DataFrame(price_basis),
        )
        connection.execute(
            """
            create table corporate_action_event (
                effective_date date,
                ex_date date,
                record_date date,
                admission_state varchar,
                adjustment_factor_state varchar
            )
            """
        )
    finally:
        connection.close()
    benchmark = root / "benchmark.csv"
    benchmark_frame = pd.DataFrame(
        {
            "date": [item.date() for item in dates],
            "total_return_index": 1000.0 * np.cumprod(np.full(len(dates), 1.0003)),
        }
    )
    benchmark_frame.to_csv(benchmark, index=False)
    result = GovernedRegimeStrategyTournamentEngine().run(
        sources=TournamentSourcePaths(
            database=database,
            historical_truth_snapshots=snapshots,
            benchmark=str(benchmark),
            project_root=_PROJECT_ROOT,
        ),
        start=_START,
        end=_END,
        policy=TournamentPolicy(minimum_selection_trades=3),
    )
    return {
        "root": root,
        "database": database,
        "snapshots": snapshots,
        "benchmark": benchmark,
        "result": result,
    }


def _create_table(
    connection: duckdb.DuckDBPyConnection,
    name: str,
    frame: pd.DataFrame,
) -> None:
    connection.register("source_frame", frame)
    connection.execute(f"create table {name} as select * from source_frame")
    connection.unregister("source_frame")


def test_governance_flags_are_all_false() -> None:
    flags = governance_flags()
    assert len(flags) == 23
    assert not any(flags.values())
    assert flags["STRATEGY_AUTOMATIC_PROMOTION_ENABLED"] is False
    assert flags["PRODUCTION_INFLUENCE"] is False


def test_strategy_registry_is_bounded_stable_and_has_cash() -> None:
    first = default_strategy_registry()
    second = default_strategy_registry()
    assert first == second
    assert len(first) == 13
    assert len({item.strategy_variant_id for item in first}) == len(first)
    assert any(item.family is StrategyFamily.NO_TRADE for item in first)


def test_duplicate_and_unbounded_registries_fail_closed() -> None:
    variant = default_strategy_registry()[0]
    with pytest.raises(TournamentError, match="DUPLICATE_STRATEGY_VARIANT_ID"):
        validate_strategy_registry((variant, variant), maximum_variants=10)
    with pytest.raises(TournamentError, match="UNBOUNDED"):
        validate_strategy_registry((variant,), maximum_variants=0)


def test_invalid_no_trade_variant_fails_closed() -> None:
    invalid = StrategyVariant(
        strategy_variant_id="BAD_CASH",
        family=StrategyFamily.NO_TRADE,
        parameters=MappingProxyType({"threshold": 1.0}),
        components=("cash",),
        expected_regimes=(RegimeState.UNKNOWN,),
        complexity_score=1,
        source_definition="test",
    )
    with pytest.raises(TournamentError, match="INVALID_NO_TRADE"):
        validate_strategy_registry((invalid,), maximum_variants=2)


def test_policy_and_strategy_models_are_immutable() -> None:
    policy = TournamentPolicy()
    with pytest.raises(FrozenInstanceError):
        policy.maximum_positions = 10  # type: ignore[misc]
    variant = default_strategy_registry()[0]
    with pytest.raises(TypeError):
        variant.parameters["new"] = 1.0  # type: ignore[index]


def test_point_in_time_regime_is_not_changed_by_future_prices() -> None:
    market = _feature_frame()
    first, first_rows, _ = _build_point_in_time_features(market)
    changed = market.copy()
    cutoff = sorted(changed["trading_date"].unique())[260]
    changed.loc[changed["trading_date"] > cutoff, "close"] *= 5.0
    second, second_rows, _ = _build_point_in_time_features(changed)
    first_states = {
        row["observed_on"]: row["regime_state"]
        for row in first_rows
        if row["observed_on"] <= cutoff
    }
    second_states = {
        row["observed_on"]: row["regime_state"]
        for row in second_rows
        if row["observed_on"] <= cutoff
    }
    assert first_states == second_states
    assert len(first) == len(second)


def _feature_frame() -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-01", periods=320)
    rows = []
    for symbol_index, symbol in enumerate(("ONE", "TWO"), start=1):
        for index, timestamp in enumerate(dates):
            close = 100.0 + index * (0.08 + symbol_index * 0.01)
            rows.append(
                {
                    "trading_date": timestamp.date(),
                    "identity_key": f"identity-{symbol}",
                    "exchange": "NSE",
                    "symbol": symbol,
                    "series": "EQ",
                    "isin": f"ISIN{symbol}",
                    "open": close - 0.2,
                    "high": close + 1.0,
                    "low": close - 1.0,
                    "close": close,
                    "volume": 1_000_000,
                    "source_sha256": "a" * 64,
                    "contract_version": "test",
                    "calculation_version": "test",
                    "action_ids": "",
                    "membership_state": "CERTIFIED_ACTIVE_TRADABLE",
                }
            )
    return pd.DataFrame(rows)


def test_regime_applies_only_to_next_session_and_begins_unknown() -> None:
    _, rows, _ = _build_point_in_time_features(_feature_frame())
    assert rows[0]["regime_state"] == RegimeState.UNKNOWN.value
    assert rows[0]["applies_on"] > rows[0]["observed_on"]
    assert rows[-1]["applies_on"] is None
    assert rows[210]["regime_state"] != RegimeState.UNKNOWN.value


def test_regime_classifier_interpretable_states() -> None:
    bull = pd.Series(
        {
            "market_level": 120.0,
            "market_ma50": 110.0,
            "market_ma200": 100.0,
            "market_volatility20": 0.15,
            "breadth": 0.70,
        }
    )
    bear = bull.copy()
    bear.update(
        {
            "market_level": 80.0,
            "market_ma50": 90.0,
            "market_ma200": 100.0,
            "breadth": 0.30,
        }
    )
    assert _classify_regime(bull) is RegimeState.BULL_TREND_LOW_VOLATILITY
    assert _classify_regime(bear) is RegimeState.BEAR_TREND


def test_walk_forward_folds_are_disjoint_and_chronological() -> None:
    folds = _walk_forward_folds(
        pd.DataFrame(
            {
                "trading_date": [
                    item.date() for item in pd.bdate_range("2016-01-01", "2023-12-29")
                ]
            }
        )
    )
    assert folds
    for fold in folds:
        assert fold.train_end < fold.validation_start
        assert fold.validation_end < fold.test_start
        assert fold.walk_forward_fold_id.endswith(str(fold.test_start.year))


def test_stop_wins_same_bar_and_costs_reduce_return() -> None:
    history = {
        "trading_date": np.array([date(2024, 1, 2), date(2024, 1, 3)], dtype=object),
        "high": np.array([101.0, 125.0]),
        "low": np.array([99.0, 85.0]),
        "close": np.array([100.0, 110.0]),
    }
    outcome = _independent_trade_outcome(
        security_history=history,
        entry_index=0,
        plan={
            "entry_price": 100.0,
            "initial_stop": 90.0,
            "target_1": 120.0,
            "target_2": 130.0,
            "risk_per_share": 10.0,
        },
        atr=5.0,
        policy=TournamentPolicy(),
    )
    assert outcome["exit_reason"] == "STOP"
    assert outcome["net_return"] < outcome["gross_return"]


def test_cagr_drawdown_and_cost_metrics_are_deterministic() -> None:
    curve = (
        {
            "observed_on": date(2020, 1, 1),
            "portfolio_value": 100.0,
            "daily_return": 0.0,
            "drawdown": 0.0,
            "gross_exposure": 0.5,
        },
        {
            "observed_on": date(2021, 1, 1),
            "portfolio_value": 110.0,
            "daily_return": 0.10,
            "drawdown": 0.0,
            "gross_exposure": 0.5,
        },
        {
            "observed_on": date(2022, 1, 1),
            "portfolio_value": 99.0,
            "daily_return": -0.10,
            "drawdown": -0.10,
            "gross_exposure": 0.0,
        },
    )
    metrics = _portfolio_metrics(
        name="TEST",
        curve=curve,
        trades=(),
        policy=TournamentPolicy(starting_capital=100.0),
    )
    assert metrics["maximum_drawdown"] == -0.1
    assert metrics["ending_capital"] == 99.0
    assert metrics["trade_count"] == 0


def test_bh_and_holm_corrections_are_monotone_and_bounded() -> None:
    p_values = [0.001, 0.02, 0.04, 0.50]
    bh = _benjamini_hochberg(p_values)
    holm = _holm(p_values)
    assert all(0 <= value <= 1 for value in (*bh, *holm))
    assert bh[0] <= bh[1] <= bh[2] <= bh[3]
    assert holm[0] <= holm[1] <= holm[2] <= holm[3]


def test_multiple_testing_uses_deterministic_monthly_blocks() -> None:
    trades = pd.DataFrame(
        {
            "strategy_variant_id": ["MOMENTUM_20"] * 48,
            "signal_date": pd.date_range("2020-01-01", periods=48, freq="MS").date,
            "net_return": [0.01 if index % 3 else -0.005 for index in range(48)],
        }
    )
    variant = StrategyVariant(
        strategy_variant_id="MOMENTUM_20",
        family=StrategyFamily.MOMENTUM_BREAKOUT,
        parameters=MappingProxyType({"lookback": 20.0}),
        components=("MOMENTUM",),
        expected_regimes=(RegimeState.BULL_TREND_LOW_VOLATILITY,),
        complexity_score=1,
        source_definition="TEST",
    )
    folds = _walk_forward_folds(
        pd.DataFrame(
            {
                "trading_date": pd.bdate_range(
                    "2016-01-01",
                    "2024-12-31",
                ).date
            }
        ),
    )
    first = _multiple_testing(trades, (variant,), folds)
    second = _multiple_testing(trades, (variant,), folds)
    assert first == second
    assert first[0]["independent_time_blocks"] >= 24
    assert first[0]["raw_p_value"] is not None
    assert first[0]["raw_p_value"] >= 1 / 2_001


def test_benchmark_unavailable_does_not_substitute_price_index() -> None:
    frame, rows = _load_benchmark(
        "AUTO",
        sessions=(date(2024, 1, 2),),
        start=date(2024, 1, 2),
        end=date(2024, 1, 2),
    )
    assert frame is None
    assert rows[0]["status"] == BenchmarkStatus.UNAVAILABLE.value
    assert rows[0]["used_for_excess_performance"] is False


def test_benchmark_requires_complete_total_return_fields(tmp_path: Path) -> None:
    invalid = tmp_path / "price_index.csv"
    invalid.write_text("date,close\n2024-01-02,100\n", encoding="utf-8")
    with pytest.raises(TournamentError, match="TOTAL_RETURN"):
        _load_benchmark(
            str(invalid),
            sessions=(date(2024, 1, 2),),
            start=date(2024, 1, 2),
            end=date(2024, 1, 2),
        )


def test_full_fixture_runs_all_slices_without_policy_influence(
    tournament_inputs: dict[str, Any],
) -> None:
    result = tournament_inputs["result"]
    assert tuple(result.readiness) == tuple("ABCDEFGHIJ")
    assert result.readiness["J"].startswith("READY_")
    assert result.summaries["admitted_sessions"] > 1900
    assert result.summaries["valid_variant_count"] == 13
    assert result.summaries["lookahead_leakage_count"] == 0
    assert result.summaries["automatic_promotion_count"] == 0
    assert not any(result.governance.values())


def test_signal_and_plan_timing_is_next_session(
    tournament_inputs: dict[str, Any],
) -> None:
    result = tournament_inputs["result"]
    plans = {row["signal_id"]: row for row in result.rows["trade_plans"]}
    assert result.rows["signals"]
    for signal in result.rows["signals"][:50]:
        plan = plans[signal["signal_id"]]
        assert plan["entry_eligibility_date"] > signal["signal_date"]
        assert plan["same_close_execution"] is False
        assert plan["initial_stop"] < plan["entry_price"] < plan["target_1"]


def test_portfolio_curve_reconciles_cash_and_positions(
    tournament_inputs: dict[str, Any],
) -> None:
    rows = [
        row
        for row in tournament_inputs["result"].rows["portfolio_equity"]
        if row["portfolio_name"] == "REGIME_AWARE_SELECTED"
    ]
    assert rows
    for row in rows:
        assert row["portfolio_value"] == pytest.approx(
            row["cash"] + row["open_position_value"],
            abs=0.02,
        )
        assert row["gross_exposure"] <= 0.75 + 1e-8
        assert row["open_positions"] <= 5


def test_walk_forward_selection_never_uses_outer_test(
    tournament_inputs: dict[str, Any],
) -> None:
    result = tournament_inputs["result"]
    for row in result.rows["strategy_selections"]:
        assert row["outer_test_used_for_selection"] is False
        assert row["selection_data_end"] < row["test_start"]
    for row in result.rows["regime_strategy_mapping"]:
        assert row["holdout_used"] is False


def test_policy_discloses_sector_cap_is_not_enforced(
    tournament_inputs: dict[str, Any],
) -> None:
    result = tournament_inputs["result"]
    policy = result.rows["policy"][0]
    assert policy["maximum_sector_exposure"] == 0.30
    assert policy["sector_data_status"] == "UNAVAILABLE_NOT_ENFORCED"


def test_required_robustness_scenarios_are_actual_reruns(
    tournament_inputs: dict[str, Any],
) -> None:
    rows = {
        row["scenario"]: row for row in tournament_inputs["result"].rows["robustness"]
    }
    for scenario in (
        "INCREASED_TRANSACTION_COST",
        "INCREASED_SLIPPAGE",
        "ONE_SESSION_EXECUTION_LAG",
        "REDUCED_POSITION_LIMIT",
        "LOWER_LIQUIDITY_CAPACITY",
        "BEST_SECURITY_REMOVAL",
        "BEST_MONTH_REMOVAL",
        "BEST_YEAR_REMOVAL",
        "REGIME_MISCLASSIFICATION",
        "BROAD_GOVERNED_ADJUSTED_COHORT",
        "SIMPLER_STRATEGY_COMPARISON",
    ):
        assert rows[scenario]["state"] == "OBSERVED"
        assert rows[scenario]["result_cagr"] is not None
    assert rows["LARGE_CAP_ONLY_UNIVERSE"]["state"].startswith("UNKNOWN_")


def test_complete_tri_enables_relative_statistics(
    tournament_inputs: dict[str, Any],
) -> None:
    row = tournament_inputs["result"].rows["benchmark_relative"][0]
    assert row["benchmark_available"] is True
    assert row["benchmark_cagr"] is not None
    assert row["excess_cagr"] is not None
    assert row["tracking_error"] is not None


def test_structural_probes_are_excluded_from_empirical_results() -> None:
    rows = structural_probe_rows()
    assert len(rows) >= 25
    assert not any(row["empirical_population"] for row in rows)
    assert (
        next(row for row in rows if row["probe_name"] == "SAME_CLOSE_EXECUTION")[
            "accepted"
        ]
        is False
    )


def test_artifact_export_is_complete_and_byte_deterministic(
    tournament_inputs: dict[str, Any],
    tmp_path: Path,
) -> None:
    result = tournament_inputs["result"]
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_paths = export_regime_strategy_tournament(result, first)
    second_paths = export_regime_strategy_tournament(result, second)
    assert len(first_paths) == len(DSI007_ARTIFACTS) + 2
    assert {path.name for path in first_paths} == {
        *DSI007_ARTIFACTS.values(),
        DSI007_CERTIFICATE,
        DSI007_REPORT,
    }
    assert {path.name: path.read_bytes() for path in first_paths} == {
        path.name: path.read_bytes() for path in second_paths
    }


def test_certificate_verifies_artifacts_and_source(
    tournament_inputs: dict[str, Any],
    tmp_path: Path,
) -> None:
    result = tournament_inputs["result"]
    paths = export_regime_strategy_tournament(result, tmp_path)
    certificate = next(path for path in paths if path.name == DSI007_CERTIFICATE)
    payload = validate_regime_strategy_tournament_certificate(
        certificate,
        require_ready=True,
        database=tournament_inputs["database"],
    )
    assert payload["readiness_decision"].startswith("READY_")
    assert payload["automatic_promotion_count"] == 0


def test_artifact_tampering_is_detected(
    tournament_inputs: dict[str, Any],
    tmp_path: Path,
) -> None:
    paths = export_regime_strategy_tournament(
        tournament_inputs["result"],
        tmp_path,
    )
    certificate = next(path for path in paths if path.name == DSI007_CERTIFICATE)
    report = tmp_path / DSI007_REPORT
    report.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(TournamentError, match="ARTIFACT_TAMPERED"):
        validate_regime_strategy_tournament_certificate(certificate)


def test_source_drift_is_detected(
    tournament_inputs: dict[str, Any],
    tmp_path: Path,
) -> None:
    paths = export_regime_strategy_tournament(
        tournament_inputs["result"],
        tmp_path,
    )
    certificate = next(path for path in paths if path.name == DSI007_CERTIFICATE)
    drift = tmp_path / "drift.duckdb"
    drift.write_bytes(tournament_inputs["database"].read_bytes() + b"drift")
    with pytest.raises(TournamentError, match="SOURCE_DATABASE_DRIFT"):
        validate_regime_strategy_tournament_certificate(
            certificate,
            database=drift,
        )


def test_cli_runner_and_verifier_render_governance(
    tournament_inputs: dict[str, Any],
    tmp_path: Path,
) -> None:
    output = tmp_path / "cli"
    run = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-regime-strategy-tournament",
            "--database",
            str(tournament_inputs["database"]),
            "--historical-truth-snapshots",
            str(tournament_inputs["snapshots"]),
            "--start",
            _START.isoformat(),
            "--end",
            _END.isoformat(),
            "--benchmark",
            str(tournament_inputs["benchmark"]),
            "--output",
            str(output),
        ],
    )
    assert run.exit_code == 0, run.output
    assert "DSI-007J Readiness" in run.output
    assert "STRATEGY_AUTOMATIC_PROMOTION_ENABLED=false" in run.output
    assert "PRODUCTION_INFLUENCE=false" in run.output
    verify = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-regime-strategy-tournament-verify",
            "--certificate",
            str(output / DSI007_CERTIFICATE),
            "--require-ready",
        ],
    )
    assert verify.exit_code == 0
    assert "Certificate: VALID" in verify.output


def test_artifacts_contain_no_machine_local_paths(
    tournament_inputs: dict[str, Any],
    tmp_path: Path,
) -> None:
    paths = export_regime_strategy_tournament(
        tournament_inputs["result"],
        tmp_path,
    )
    assert not any(b"/Users/" in path.read_bytes() for path in paths)


def test_report_states_benchmark_and_promotion_limitations(
    tournament_inputs: dict[str, Any],
    tmp_path: Path,
) -> None:
    export_regime_strategy_tournament(tournament_inputs["result"], tmp_path)
    report = (tmp_path / DSI007_REPORT).read_text(encoding="utf-8")
    assert "Out-of-Sample Portfolio" in report
    assert "does not claim these were Alpha's historical recommendations" in report
    assert "No strategy is automatically promoted" in report
    assert "PRODUCTION_INFLUENCE=false" in report


def test_csv_schemas_exist_even_when_rows_are_empty(
    tournament_inputs: dict[str, Any],
    tmp_path: Path,
) -> None:
    export_regime_strategy_tournament(tournament_inputs["result"], tmp_path)
    for filename in DSI007_ARTIFACTS.values():
        with (tmp_path / filename).open(newline="", encoding="utf-8") as handle:
            assert csv.reader(handle).__next__()


def test_certificate_payload_hash_detects_direct_edit(
    tournament_inputs: dict[str, Any],
    tmp_path: Path,
) -> None:
    paths = export_regime_strategy_tournament(
        tournament_inputs["result"],
        tmp_path,
    )
    certificate = next(path for path in paths if path.name == DSI007_CERTIFICATE)
    payload = json.loads(certificate.read_text(encoding="utf-8"))
    payload["readiness_decision"] = "READY_FOR_FORWARD_PAPER_STRATEGY_RESEARCH"
    certificate.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(TournamentError, match="PAYLOAD_TAMPERED"):
        validate_regime_strategy_tournament_certificate(certificate)
