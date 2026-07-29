"""Stable serialization helpers for research lab specifications."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, cast

from alpha.research.lab_models import (
    ComparisonOperator,
    Condition,
    ConditionGroup,
    EntryRule,
    LogicOperator,
    ParameterSweep,
    ResearchExperimentSpec,
    RuleKind,
    SameSessionPolicy,
    StopPolicy,
    StopRule,
    StrategyMode,
    TargetPolicy,
    TargetRule,
)


def specification_from_dict(payload: dict[str, Any]) -> ResearchExperimentSpec:
    return ResearchExperimentSpec(
        experiment_id=str(payload["experiment_id"]),
        research_session_id=str(payload["research_session_id"]),
        experiment_name=str(payload["experiment_name"]),
        parent_experiment_id=_text(payload.get("parent_experiment_id")),
        strategy_mode=StrategyMode(str(payload["strategy_mode"])),
        data_start=date.fromisoformat(str(payload["data_start"])),
        data_end=date.fromisoformat(str(payload["data_end"])),
        universe_definition=str(payload["universe_definition"]),
        base_signal_source=tuple(
            str(item) for item in cast(list[object], payload["base_signal_source"])
        ),
        entry_conditions=_group(cast(dict[str, Any], payload["entry_conditions"])),
        entry_rule=_entry(cast(dict[str, Any], payload["entry_rule"])),
        exit_conditions=_group(cast(dict[str, Any], payload["exit_conditions"])),
        stop_policy=_stops(cast(dict[str, Any], payload["stop_policy"])),
        target_policy=_targets(cast(dict[str, Any], payload["target_policy"])),
        maximum_holding_sessions=_integer(payload.get("maximum_holding_sessions")),
        position_sizing_method=str(payload["position_sizing_method"]),
        initial_capital=Decimal(str(payload["initial_capital"])),
        maximum_concurrent_positions=int(payload["maximum_concurrent_positions"]),
        rebalance_rule=str(payload["rebalance_rule"]),
        sector_filters=tuple(
            str(item) for item in cast(list[object], payload["sector_filters"])
        ),
        regime_filters=tuple(
            str(item) for item in cast(list[object], payload["regime_filters"])
        ),
        price_basis=str(payload["price_basis"]),
        transaction_cost_model=str(payload["transaction_cost_model"]),
        slippage_model=str(payload["slippage_model"]),
        fractional_shares=bool(payload["fractional_shares"]),
        same_session_policy=SameSessionPolicy(str(payload["same_session_policy"])),
        parameter_sweeps=tuple(
            ParameterSweep(
                field=str(item["field"]),
                values=tuple(str(value) for value in item["values"]),
            )
            for item in cast(list[dict[str, Any]], payload["parameter_sweeps"])
        ),
        output_requirements=tuple(
            str(item) for item in cast(list[object], payload["output_requirements"])
        ),
        compiler_version=str(payload["compiler_version"]),
        production_influence=bool(payload["production_influence"]),
    )


def _group(payload: dict[str, Any]) -> ConditionGroup:
    return ConditionGroup(
        operator=LogicOperator(str(payload["operator"])),
        conditions=tuple(
            _condition(item)
            for item in cast(list[dict[str, Any]], payload["conditions"])
        ),
        groups=tuple(
            _group(item) for item in cast(list[dict[str, Any]], payload["groups"])
        ),
        required_count=_integer(payload.get("required_count")),
    )


def _condition(payload: dict[str, Any]) -> Condition:
    value = payload.get("value")
    return Condition(
        condition_id=str(payload["condition_id"]),
        kind=RuleKind(str(payload["kind"])),
        name=str(payload["name"]),
        operator=ComparisonOperator(str(payload["operator"])),
        value=None if value is None else Decimal(str(value)),
        period=_integer(payload.get("period")),
        reference=_text(payload.get("reference")),
        parameters=tuple(
            (str(item[0]), str(item[1]))
            for item in cast(list[list[object]], payload["parameters"])
        ),
    )


def _entry(payload: dict[str, Any]) -> EntryRule:
    return EntryRule(
        rule_id=str(payload["rule_id"]),
        delay_sessions=int(payload["delay_sessions"]),
        expiry_sessions=int(payload["expiry_sessions"]),
        retracement_percent=_decimal(payload.get("retracement_percent")),
        atr_multiple=_decimal(payload.get("atr_multiple")),
        condition_must_remain_valid=bool(payload["condition_must_remain_valid"]),
    )


def _stops(payload: dict[str, Any]) -> StopPolicy:
    return StopPolicy(
        rules=tuple(
            StopRule(
                rule_id=str(item["rule_id"]),
                value=_decimal(item.get("value")),
                atr_period=_integer(item.get("atr_period")),
                activation_gain_percent=_decimal(item.get("activation_gain_percent")),
            )
            for item in cast(list[dict[str, Any]], payload["rules"])
        ),
        combination=_text(payload.get("combination")),
    )


def _targets(payload: dict[str, Any]) -> TargetPolicy:
    trailing = payload.get("trailing_rule")
    return TargetPolicy(
        rules=tuple(
            TargetRule(
                rule_id=str(item["rule_id"]),
                value=_decimal(item.get("value")),
                exit_percent=Decimal(str(item["exit_percent"])),
            )
            for item in cast(list[dict[str, Any]], payload["rules"])
        ),
        trailing_rule=(
            None
            if trailing is None
            else StopRule(
                rule_id=str(cast(dict[str, Any], trailing)["rule_id"]),
                value=_decimal(cast(dict[str, Any], trailing).get("value")),
                atr_period=_integer(cast(dict[str, Any], trailing).get("atr_period")),
                activation_gain_percent=_decimal(
                    cast(dict[str, Any], trailing).get("activation_gain_percent")
                ),
            )
        ),
    )


def _decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _integer(value: object) -> int | None:
    return None if value is None else int(str(value))


def _text(value: object) -> str | None:
    return None if value is None else str(value)


__all__ = ["specification_from_dict"]
