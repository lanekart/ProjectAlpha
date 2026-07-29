from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from alpha.backtest.research_runner import CanonicalResearchBacktestRunner
from alpha.research.lab_compiler import NaturalLanguageResearchCompiler
from alpha.research.lab_data_contract import ResearchDataContract
from alpha.research.lab_features import ResearchFeatureEngine
from alpha.research.lab_models import (
    AlphaSignalSource,
    ComparisonOperator,
    Condition,
    ConditionGroup,
    ExperimentStatus,
    ResearchExperimentSpec,
    RuleKind,
    SameSessionPolicy,
    StopPolicy,
    StopRule,
    StrategyMode,
    TargetPolicy,
    TargetRule,
)
from alpha.research.lab_serialization import specification_from_dict
from alpha.research.lab_service import ConversationalResearchLab
from alpha.research.lab_store import ResearchLabStore

_START = date(2016, 1, 1)
_END = date(2025, 12, 24)


def test_specification_key_is_stable_and_round_trips() -> None:
    spec = _spec()

    restored = specification_from_dict(spec.as_dict())

    assert restored == spec
    assert restored.specification_sha256 == spec.specification_sha256
    assert json.loads(spec.to_json())["transaction_cost_model"] == "NONE"


def test_compiler_creates_hybrid_strategy_with_explicit_defaults() -> None:
    result = _compiler().compile(
        "Backtest Alpha BUY and STRONG BUY recommendations from 2016 to date, "
        "require price above the 200-DMA and RSI above 50, enter next session "
        "open, use an 8% stop and 20% target, maximum 10 positions.",
        experiment_id="ARL-000001",
        session_id="ARS-000001",
        certified_start=_START,
        certified_end=_END,
    )

    assert result.status is ExperimentStatus.COMPILED
    assert result.specification is not None
    assert result.specification.strategy_mode is StrategyMode.HYBRID
    assert result.specification.initial_capital == Decimal("10000000")
    assert result.specification.transaction_cost_model == "NONE"
    assert {item.name for item in result.specification.entry_conditions.conditions} == {
        "RSI",
        "SMA",
    }
    assert result.specification.stop_policy.rules[0].value == Decimal("8")
    assert result.specification.target_policy.rules[0].value == Decimal("20")


def test_follow_up_removes_only_candle_condition() -> None:
    baseline = (
        _compiler()
        .compile(
            "Backtest Alpha BUY recommendations. Require RSI above 50 and add "
            "bullish engulfing as an entry confirmation.",
            experiment_id="ARL-000001",
            session_id="ARS-000001",
            certified_start=_START,
            certified_end=_END,
        )
        .specification
    )
    assert baseline is not None

    result = _compiler().compile(
        "Remove bullish engulfing and keep the indicator filters.",
        experiment_id="ARL-000002",
        session_id="ARS-000001",
        certified_start=_START,
        certified_end=_END,
        parent=baseline,
    )

    assert result.specification is not None
    assert {item.name for item in result.specification.entry_conditions.conditions} == {
        "RSI"
    }
    assert result.specification.stop_policy == baseline.stop_policy
    assert result.specification.target_policy == baseline.target_policy
    assert result.specification.parent_experiment_id == "ARL-000001"


@pytest.mark.parametrize(
    "prompt,missing",
    (
        ("Buy good stocks after a correction.", "good stocks"),
        ("Use a reasonable stop.", "stop method"),
        ("Exit when momentum weakens.", "momentum weakness"),
    ),
)
def test_material_ambiguity_fails_closed(prompt: str, missing: str) -> None:
    result = _compiler().compile(
        prompt,
        experiment_id="ARL-000001",
        session_id="ARS-000001",
        certified_start=_START,
        certified_end=_END,
    )

    assert result.status is ExperimentStatus.BLOCKED
    assert result.specification is None
    assert missing in result.issues[0].message


def test_pre2016_request_is_rejected() -> None:
    result = _compiler().compile(
        "Backtest RSI above 50 from 2014.",
        experiment_id="ARL-000001",
        session_id="ARS-000001",
        certified_start=_START,
        certified_end=_END,
    )

    assert result.status is ExperimentStatus.BLOCKED
    assert "precedes certified boundary" in result.issues[0].message


@pytest.mark.parametrize(
    ("prompt", "source"),
    (
        (
            "Use only Alpha recommendations actually recorded historically.",
            AlphaSignalSource.RECORDED_HISTORICAL_ALPHA_SIGNAL,
        ),
        (
            "Backtest the retrospective frozen Alpha model.",
            AlphaSignalSource.RETROSPECTIVE_FROZEN_ALPHA_REPLAY,
        ),
        (
            "Backtest Alpha using walk-forward recalibration.",
            AlphaSignalSource.WALK_FORWARD_ALPHA_REPLAY,
        ),
    ),
)
def test_compiler_preserves_explicit_alpha_signal_source(
    prompt: str,
    source: AlphaSignalSource,
) -> None:
    result = _compiler().compile(
        prompt,
        experiment_id="ARL-000001",
        session_id="ARS-000001",
        certified_start=_START,
        certified_end=_END,
    )

    assert result.specification is not None
    assert result.specification.alpha_signal_source is source


def test_unimplemented_registered_indicator_fails_closed() -> None:
    result = _compiler().compile(
        "Backtest a MACD bullish crossover.",
        experiment_id="ARL-000001",
        session_id="ARS-000001",
        certified_start=_START,
        certified_end=_END,
    )

    assert result.status is ExperimentStatus.BLOCKED
    assert "does not yet have a canonical" in result.issues[0].message


def test_parameter_sweep_is_bounded_and_expands_deterministically(
    tmp_path: Path,
) -> None:
    compiled = _compiler().compile(
        "Backtest RSI above 50. Test holding periods of 5, 10, 20 and 40 sessions.",
        experiment_id="ARL-000001",
        session_id="ARS-000001",
        certified_start=_START,
        certified_end=_END,
    )
    assert compiled.specification is not None
    lab = ConversationalResearchLab(
        database=tmp_path / "unused.duckdb",
        root=tmp_path / "research",
    )

    children = lab.expand_sweep(compiled.specification)

    assert tuple(item.maximum_holding_sessions for item in children) == (
        5,
        10,
        20,
        40,
    )
    assert children[0].experiment_id == "ARL-000001-S001"


def test_stop_comparison_creates_one_child_per_registered_stop(
    tmp_path: Path,
) -> None:
    compiled = _compiler().compile(
        "Compare 5% stop, 8% stop, 10% stop, 2 ATR stop and STOP-STRUCTURAL-10D.",
        experiment_id="ARL-000001",
        session_id="ARS-000001",
        certified_start=_START,
        certified_end=_END,
    )
    assert compiled.specification is not None
    lab = ConversationalResearchLab(
        database=tmp_path / "unused.duckdb",
        root=tmp_path / "research",
    )

    children = lab.expand_sweep(compiled.specification)

    assert len(children) == 5
    assert children[0].stop_policy.rules[0].value == Decimal("5")
    assert children[-1].stop_policy.rules[0].rule_id == "STOP-STRUCTURAL-10D"


def test_target_comparison_takes_precedence_over_parent_stop(
    tmp_path: Path,
) -> None:
    compiled = _compiler().compile(
        "Using the 8% stop version, compare 10% target, 20% target, "
        "2R target, 3R target and no fixed target.",
        experiment_id="ARL-000001",
        session_id="ARS-000001",
        certified_start=_START,
        certified_end=_END,
    )
    assert compiled.specification is not None
    lab = ConversationalResearchLab(
        database=tmp_path / "unused.duckdb",
        root=tmp_path / "research",
    )

    children = lab.expand_sweep(compiled.specification)

    assert len(children) == 5
    assert children[0].target_policy.rules[0].value == Decimal("10")
    assert children[-1].target_policy.rules == ()


def test_feature_signal_is_close_derived_and_entry_occurs_next_session() -> None:
    frame = _price_frame()
    spec = _spec(
        entry_conditions=ConditionGroup(
            conditions=(
                Condition(
                    condition_id="CLOSE_ABOVE_SMA_2",
                    kind=RuleKind.INDICATOR,
                    name="SMA",
                    operator=ComparisonOperator.ABOVE,
                    period=2,
                    reference="CLOSE",
                ),
            )
        )
    )

    featured = ResearchFeatureEngine().build(frame, spec)
    result = CanonicalResearchBacktestRunner().run(featured, spec)

    assert featured.loc[
        featured["research_signal"], "trading_date"
    ].min() == pd.Timestamp("2020-01-02")
    assert result.trades[0].signal_date == date(2020, 1, 2)
    assert result.trades[0].entry_date == date(2020, 1, 3)


def test_rsi_respects_registered_warmup_period() -> None:
    frame = pd.DataFrame(
        {
            "trading_date": pd.date_range("2020-01-01", periods=16),
            "security_id": ["INE0001"] * 16,
            "symbol": ["TEST"] * 16,
            "open": range(100, 116),
            "high": range(101, 117),
            "low": range(99, 115),
            "close": range(100, 116),
            "volume": [1000] * 16,
        }
    )
    spec = _spec(
        entry_conditions=ConditionGroup(
            conditions=(
                Condition(
                    condition_id="RSI_14_ABOVE_50",
                    kind=RuleKind.INDICATOR,
                    name="RSI",
                    operator=ComparisonOperator.ABOVE,
                    value=Decimal("50"),
                    period=14,
                ),
            )
        )
    )

    featured = ResearchFeatureEngine().build(frame, spec)

    assert not featured.iloc[:14]["research_signal"].any()
    assert featured.iloc[14:]["research_signal"].all()


@pytest.mark.parametrize(
    "stop_rule",
    (
        StopRule("ATR", Decimal("2"), atr_period=14),
        StopRule("STOP-STRUCTURAL-10D"),
    ),
)
def test_stop_rules_materialize_required_execution_features(
    stop_rule: StopRule,
) -> None:
    frame = pd.DataFrame(
        {
            "trading_date": pd.date_range("2020-01-01", periods=18),
            "security_id": ["INE0001"] * 18,
            "symbol": ["TEST"] * 18,
            "open": range(100, 118),
            "high": range(101, 119),
            "low": range(99, 117),
            "close": range(100, 118),
            "volume": [1000] * 18,
        }
    )
    spec = _spec(
        stop_policy=StopPolicy(rules=(stop_rule,)),
        maximum_holding_sessions=2,
    )

    featured = ResearchFeatureEngine().build(frame, spec)
    result = CanonicalResearchBacktestRunner().run(featured, spec)

    assert result.trades
    assert any(item.stop_price is not None for item in result.trades)


def test_same_session_stop_target_ambiguity_uses_stop_first() -> None:
    frame = _price_frame()
    spec = _spec(
        stop_policy=StopPolicy(rules=(StopRule("FIXED_PERCENT", Decimal("5")),)),
        target_policy=TargetPolicy(rules=(TargetRule("FIXED_PERCENT", Decimal("5")),)),
        same_session_policy=SameSessionPolicy.ASSUME_STOP_FIRST,
        maximum_holding_sessions=10,
    )
    featured = ResearchFeatureEngine().build(frame, spec)

    result = CanonicalResearchBacktestRunner().run(featured, spec)

    assert result.ambiguous_sessions >= 1
    assert result.trades[0].exit_reason == "INTRADAY_PATH_AMBIGUOUS_STOP_FIRST"
    assert result.trades[0].exit_price == Decimal("95.00")
    summary = result.summary()
    assert summary["gross_cagr_percent"] is not None
    assert summary["maximum_drawdown_duration_sessions"] >= 0
    assert summary["average_exposure_percent"] is not None
    assert summary["turnover_percent"] is not None


def test_partial_target_leaves_runner_for_trailing_exit() -> None:
    frame = _price_frame()
    spec = _spec(
        stop_policy=StopPolicy(rules=(StopRule("FIXED_PERCENT", Decimal("5")),)),
        target_policy=TargetPolicy(
            rules=(
                TargetRule(
                    "R_MULTIPLE",
                    Decimal("1"),
                    exit_percent=Decimal("50"),
                ),
            ),
            trailing_rule=StopRule("TRAILING_PERCENT", Decimal("10")),
        ),
        same_session_policy=SameSessionPolicy.ASSUME_TARGET_FIRST,
        maximum_holding_sessions=10,
    )
    featured = ResearchFeatureEngine().build(frame, spec)

    result = CanonicalResearchBacktestRunner().run(featured, spec)

    assert result.trades[0].exit_reason == "TARGET_PARTIAL"
    assert len(result.trades) == 2
    assert result.trades[0].quantity > 0
    assert result.trades[-1].exit_reason == "FORCED_BOUNDARY_EXIT"


def test_trail_the_balance_is_not_active_before_partial_target() -> None:
    compiled = _compiler().compile(
        "Backtest Alpha BUY recommendations. Use an 8% stop. "
        "Take half at 2R and trail the balance with a 10% trailing stop.",
        experiment_id="ARL-000001",
        session_id="ARS-000001",
        certified_start=_START,
        certified_end=_END,
    )

    assert compiled.specification is not None
    assert [item.rule_id for item in compiled.specification.stop_policy.rules] == [
        "FIXED_PERCENT"
    ]
    assert compiled.specification.target_policy.rules[0].exit_percent == Decimal("50")
    assert compiled.specification.target_policy.trailing_rule == StopRule(
        "TRAILING_PERCENT", Decimal("10")
    )


def test_store_never_overwrites_an_existing_experiment(tmp_path: Path) -> None:
    store = ResearchLabStore(tmp_path)
    compilation = _compiler().compile(
        "Backtest RSI above 50.",
        experiment_id="ARL-000001",
        session_id="ARS-000001",
        certified_start=_START,
        certified_end=_END,
    )
    store.save_compilation(
        result=compilation,
        user_command="Backtest RSI above 50.",
        session_id="ARS-000001",
        experiment_id="ARL-000001",
    )

    with pytest.raises(FileExistsError):
        store.save_compilation(
            result=compilation,
            user_command="Backtest RSI above 50.",
            session_id="ARS-000001",
            experiment_id="ARL-000001",
        )


def test_service_persists_compilation_and_fails_closed_on_data(tmp_path: Path) -> None:
    database = tmp_path / "truth.duckdb"
    database.touch()
    lab = ConversationalResearchLab(
        database=database,
        root=tmp_path / "research",
    )
    lab.auditor = _BlockedAuditor()

    execution = lab.ask("Backtest RSI above 50.")

    assert not execution.completed
    assert (execution.output / "spec.json").is_file()
    summary = json.loads((execution.output / "summary.json").read_text())
    assert summary["status"] == "BLOCKED_BY_DATA_CONTRACT"
    assert summary["production_influence"] is False


def _compiler() -> NaturalLanguageResearchCompiler:
    return NaturalLanguageResearchCompiler()


def _spec(
    *,
    entry_conditions: ConditionGroup | None = None,
    stop_policy: StopPolicy | None = None,
    target_policy: TargetPolicy | None = None,
    same_session_policy: SameSessionPolicy = SameSessionPolicy.ASSUME_STOP_FIRST,
    maximum_holding_sessions: int = 2,
) -> ResearchExperimentSpec:
    return ResearchExperimentSpec(
        experiment_id="ARL-000001",
        research_session_id="ARS-000001",
        experiment_name="fixture",
        parent_experiment_id=None,
        strategy_mode=StrategyMode.PURE_TECHNICAL,
        data_start=_START,
        data_end=_END,
        entry_conditions=entry_conditions or ConditionGroup(),
        stop_policy=stop_policy or StopPolicy(),
        target_policy=target_policy or TargetPolicy(),
        same_session_policy=same_session_policy,
        maximum_holding_sessions=maximum_holding_sessions,
    )


def _price_frame() -> pd.DataFrame:
    return pd.DataFrame(
        (
            {
                "trading_date": "2020-01-01",
                "security_id": "INE0001",
                "symbol": "TEST",
                "open": 99,
                "high": 101,
                "low": 98,
                "close": 100,
                "volume": 1000,
            },
            {
                "trading_date": "2020-01-02",
                "security_id": "INE0001",
                "symbol": "TEST",
                "open": 100,
                "high": 103,
                "low": 99,
                "close": 102,
                "volume": 1200,
            },
            {
                "trading_date": "2020-01-03",
                "security_id": "INE0001",
                "symbol": "TEST",
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "volume": 900,
            },
            {
                "trading_date": "2020-01-06",
                "security_id": "INE0001",
                "symbol": "TEST",
                "open": 100,
                "high": 110,
                "low": 90,
                "close": 104,
                "volume": 1500,
            },
        )
    )


class _BlockedAuditor:
    def audit(self, database: Path) -> ResearchDataContract:
        return ResearchDataContract(
            requested_start=_START,
            actual_start=_START,
            actual_end=_END,
            expected_trading_sessions=10,
            observed_trading_sessions=9,
            certified_securities=1,
            raw_security_session_rows=10,
            adjusted_security_session_rows=9,
            unresolved_security_identities=1,
            unresolved_series_intervals=0,
            unresolved_corporate_action_factors=1,
            mixed_price_basis_intervals=1,
            invalid_adjusted_ohlc_rows=0,
            duplicate_security_session_rows=0,
            missing_adjusted_rows=1,
            alpha_signal_records=0,
            database_sha256="0" * 64,
            blockers=("MIXED_PRICE_BASIS_INTERVALS:1",),
        )
