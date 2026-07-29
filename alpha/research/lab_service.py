"""Application service for compiling, executing, and inspecting research runs."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import duckdb
import pandas as pd

from alpha.backtest.research_runner import (
    CanonicalResearchBacktestRunner,
    ResearchBacktestResult,
)
from alpha.research.lab_artifacts import ResearchArtifactExporter
from alpha.research.lab_compiler import NaturalLanguageResearchCompiler
from alpha.research.lab_data_contract import (
    ResearchDataContract,
    ResearchDataContractAuditor,
)
from alpha.research.lab_features import ResearchFeatureEngine
from alpha.research.lab_models import (
    CompilationResult,
    Condition,
    ExperimentStatus,
    ParameterSweep,
    ResearchExperimentSpec,
    RuleKind,
    StopPolicy,
    StopRule,
    StrategyMode,
    TargetPolicy,
    TargetRule,
)
from alpha.research.lab_store import ResearchLabStore


@dataclass(frozen=True, slots=True)
class LabExecution:
    compilation: CompilationResult
    contract: ResearchDataContract
    output: Path
    result: ResearchBacktestResult | None

    @property
    def completed(self) -> bool:
        return self.result is not None


class ConversationalResearchLab:
    def __init__(
        self,
        *,
        database: Path,
        root: Path = Path(".alpha/research"),
        maximum_sweep_children: int = 100,
    ) -> None:
        self.database = database
        self.store = ResearchLabStore(root)
        self.maximum_sweep_children = maximum_sweep_children
        self.compiler = NaturalLanguageResearchCompiler()
        self.auditor = ResearchDataContractAuditor()
        self.feature_engine = ResearchFeatureEngine()
        self.runner = CanonicalResearchBacktestRunner()
        self.exporter = ResearchArtifactExporter()

    def ask(
        self,
        request: str,
        *,
        parent_experiment_id: str | None = None,
        session_id: str | None = None,
        execute: bool = True,
    ) -> LabExecution:
        contract = self.auditor.audit(self.database)
        parent = (
            None
            if parent_experiment_id is None
            else self.store.load_specification(parent_experiment_id)
        )
        experiment_id = self.store.allocate_experiment_id()
        resolved_session = (
            session_id
            or (parent.research_session_id if parent is not None else None)
            or self.store.allocate_session_id()
        )
        start = contract.actual_start or date(2016, 1, 1)
        end = contract.actual_end or start
        compilation = self.compiler.compile(
            request,
            experiment_id=experiment_id,
            session_id=resolved_session,
            certified_start=max(start, date(2016, 1, 1)),
            certified_end=end,
            parent=parent,
        )
        output = self.store.save_compilation(
            result=compilation,
            user_command=request,
            session_id=resolved_session,
            experiment_id=experiment_id,
        )
        spec = compilation.specification
        if spec is None or not execute:
            return LabExecution(compilation, contract, output, None)
        if compilation.planned_children > self.maximum_sweep_children:
            raise ValueError(
                "parameter sweep blocked: "
                f"{compilation.planned_children} children exceeds "
                f"limit {self.maximum_sweep_children}"
            )
        if spec.parameter_sweeps:
            children = self.expand_sweep(spec)
            child_results: list[dict[str, object]] = []
            for child in children:
                child_compilation = CompilationResult(
                    status=ExperimentStatus.COMPILED,
                    normalized_request=compilation.normalized_request,
                    intent="SWEEP_CHILD",
                    specification=child,
                )
                child_output = self.store.save_compilation(
                    result=child_compilation,
                    user_command=request,
                    session_id=resolved_session,
                    experiment_id=child.experiment_id,
                )
                child_result = self._execute_or_block(
                    child,
                    contract,
                    child_output,
                )
                child_results.append(
                    {
                        "experiment_id": child.experiment_id,
                        "completed": child_result is not None,
                        "output": f"runs/{child.experiment_id}",
                    }
                )
            (output / "sweep_summary.json").write_text(
                json.dumps(
                    {
                        "parent_experiment_id": spec.experiment_id,
                        "children": child_results,
                    },
                    sort_keys=True,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            return LabExecution(compilation, contract, output, None)
        return self._execute_lab(compilation, contract, output)

    def _execute_lab(
        self,
        compilation: CompilationResult,
        contract: ResearchDataContract,
        output: Path,
    ) -> LabExecution:
        spec = compilation.specification
        if spec is None:
            return LabExecution(compilation, contract, output, None)
        result = self._execute_or_block(spec, contract, output)
        return LabExecution(compilation, contract, output, result)

    def _execute_or_block(
        self,
        spec: ResearchExperimentSpec,
        contract: ResearchDataContract,
        output: Path,
    ) -> ResearchBacktestResult | None:
        if not contract.ready:
            self.exporter.export_blocked(
                output=output,
                spec=spec,
                contract=contract,
            )
            return None
        if (
            spec.strategy_mode is not StrategyMode.PURE_TECHNICAL
            and not contract.alpha_signal_ready
        ):
            contract = replace(
                contract,
                blockers=(
                    *contract.blockers,
                    "FROZEN_ALPHA_SIGNAL_POPULATION_UNAVAILABLE",
                ),
            )
            self.exporter.export_blocked(
                output=output,
                spec=spec,
                contract=contract,
            )
            return None
        frame = self._load_frame(spec)
        featured = self.feature_engine.build(frame, spec)
        result = self.runner.run(featured, spec)
        self.exporter.export_completed(
            output=output,
            spec=spec,
            contract=contract,
            result=result,
        )
        return result

    def show(self, experiment_id: str) -> ResearchExperimentSpec:
        return self.store.load_specification(experiment_id)

    def rerun(self, experiment_id: str) -> LabExecution:
        original = self.store.load_specification(experiment_id)
        return self.ask(
            f"repeat {experiment_id}",
            parent_experiment_id=experiment_id,
            session_id=original.research_session_id,
        )

    def compare(self, experiment_ids: tuple[str, ...]) -> dict[str, Any]:
        if len(experiment_ids) < 2:
            raise ValueError("comparison requires at least two experiments")
        rows: list[dict[str, Any]] = []
        trades: dict[str, list[dict[str, Any]]] = {}
        for experiment_id in experiment_ids:
            root = self.store.runs_root / experiment_id
            summary_path = root / "summary.json"
            if not summary_path.is_file():
                raise FileNotFoundError(
                    f"experiment has no execution summary: {experiment_id}"
                )
            rows.append(json.loads(summary_path.read_text()))
            trade_path = root / "trades.json"
            trades[experiment_id] = (
                cast(list[dict[str, Any]], json.loads(trade_path.read_text()))
                if trade_path.is_file()
                else []
            )
        contributors = _trade_contributors(trades)
        return {
            "experiments": rows,
            "trade_contributors": contributors,
            "attribution_dimensions": (
                "added_or_removed_trades",
                "changed_entries",
                "changed_exits",
                "stop_triggers",
                "target_triggers",
                "holding_period",
                "capital_utilisation",
            ),
        }

    def expand_sweep(
        self,
        spec: ResearchExperimentSpec,
    ) -> tuple[ResearchExperimentSpec, ...]:
        children: tuple[ResearchExperimentSpec, ...] = (spec,)
        for sweep in spec.parameter_sweeps:
            expanded: list[ResearchExperimentSpec] = []
            for child in children:
                for value in sweep.values:
                    expanded.append(_apply_sweep_value(child, sweep, value))
            children = tuple(expanded)
            if len(children) > self.maximum_sweep_children:
                raise ValueError("parameter sweep exceeds configured child limit")
        return tuple(
            child.with_identity(
                experiment_id=f"{spec.experiment_id}-S{index:03d}",
                parent_experiment_id=spec.experiment_id,
            )
            for index, child in enumerate(children, start=1)
        )

    def _load_frame(self, spec: ResearchExperimentSpec) -> pd.DataFrame:
        connection = duckdb.connect(str(self.database), read_only=True)
        try:
            frame = connection.execute(
                """
                SELECT trading_date, isin AS security_id, symbol, series,
                       adjusted_open AS open, adjusted_high AS high,
                       adjusted_low AS low, adjusted_close AS close,
                       adjusted_volume AS volume
                FROM adjusted_daily_candle
                WHERE UPPER(exchange) = 'NSE'
                  AND trading_date BETWEEN ? AND ?
                  AND series = 'EQ'
                ORDER BY trading_date, isin
                """,
                (spec.data_start, spec.data_end),
            ).fetchdf()
            if spec.strategy_mode is not StrategyMode.PURE_TECHNICAL:
                frame = self._attach_signals(connection, frame)
            return frame
        finally:
            connection.close()

    def _attach_signals(
        self,
        connection: duckdb.DuckDBPyConnection,
        frame: pd.DataFrame,
    ) -> pd.DataFrame:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='main'"
            ).fetchall()
        }
        if "frozen_recommendation" not in tables:
            raise ValueError("frozen Alpha recommendation source is unavailable")
        signals = connection.execute(
            """
            SELECT generated_at::DATE AS trading_date, isin AS security_id,
                   final_verdict AS final_signal
            FROM frozen_recommendation
            """
        ).fetchdf()
        return frame.merge(
            signals,
            on=["trading_date", "security_id"],
            how="left",
            validate="one_to_one",
        )


def _apply_sweep_value(
    spec: ResearchExperimentSpec,
    sweep: ParameterSweep,
    value: str,
) -> ResearchExperimentSpec:
    if sweep.field == "MAXIMUM_HOLDING_SESSIONS":
        return replace(spec, maximum_holding_sessions=int(value), parameter_sweeps=())
    if sweep.field == "MAXIMUM_CONCURRENT_POSITIONS":
        return replace(
            spec,
            maximum_concurrent_positions=int(value),
            parameter_sweeps=(),
        )
    if sweep.field == "ENTRY.RSI.THRESHOLD":
        conditions = tuple(
            replace(item, value=Decimal(value)) if item.name == "RSI" else item
            for item in spec.entry_conditions.conditions
        )
        return replace(
            spec,
            entry_conditions=replace(spec.entry_conditions, conditions=conditions),
            parameter_sweeps=(),
        )
    if sweep.field == "STOP_POLICY":
        if value == "STOP-STRUCTURAL-10D":
            policy = StopPolicy(rules=(StopRule(value),))
        else:
            rule_id, amount = value.split(":", maxsplit=1)
            policy = StopPolicy(rules=(StopRule(rule_id, Decimal(amount)),))
        return replace(spec, stop_policy=policy, parameter_sweeps=())
    if sweep.field == "TARGET_POLICY":
        target_policy = (
            TargetPolicy()
            if value == "NONE"
            else TargetPolicy(
                rules=(
                    TargetRule(
                        value.split(":", maxsplit=1)[0],
                        Decimal(value.split(":", maxsplit=1)[1]),
                    ),
                )
            )
        )
        return replace(
            spec,
            target_policy=target_policy,
            parameter_sweeps=(),
        )
    if sweep.field == "CANDLE_CONFIRMATION":
        conditions = tuple(
            item
            for item in spec.entry_conditions.conditions
            if item.kind is not RuleKind.CANDLE
        )
        if value != "NONE":
            conditions = (
                *conditions,
                Condition(
                    condition_id=value,
                    kind=RuleKind.CANDLE,
                    name=value,
                ),
            )
        return replace(
            spec,
            entry_conditions=replace(
                spec.entry_conditions,
                conditions=conditions,
            ),
            parameter_sweeps=(),
        )
    raise ValueError(f"unsupported sweep field: {sweep.field}")


def _trade_contributors(
    experiments: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for experiment_id, trades in sorted(experiments.items()):
        for trade in trades:
            rows.append(
                {
                    "experiment_id": experiment_id,
                    "trade_id": trade.get("trade_id"),
                    "symbol": trade.get("symbol"),
                    "gross_profit_loss": trade.get("gross_profit_loss"),
                    "exit_reason": trade.get("exit_reason"),
                }
            )
    return sorted(
        rows,
        key=lambda item: (
            -abs(float(item["gross_profit_loss"] or 0)),
            str(item["experiment_id"]),
            str(item["trade_id"]),
        ),
    )[:25]


__all__ = ["ConversationalResearchLab", "LabExecution"]
