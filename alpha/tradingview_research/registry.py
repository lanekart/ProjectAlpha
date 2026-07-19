"""Append-safe persistent registry for immutable TRL experiments."""

from __future__ import annotations

import csv
import io
import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import cast

from alpha.tradingview_research.models import (
    PRODUCTION_INFLUENCE,
    TRL_SCHEMA_VERSION,
    CombinationMode,
    ComponentWeight,
    ExperimentObservation,
    IndicatorId,
    IndicatorSetting,
    LabConfiguration,
    ObservationRole,
    PerformanceMetrics,
    ResearchPartition,
    StrategyId,
    StrategySetting,
    TradingViewExperiment,
)

DEFAULT_TRL_REGISTRY = Path(".alpha/tradingview_research/experiments.json")


class TradingViewResearchRegistry:
    """Persist complete experiments without allowing in-place evidence edits."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_registry_path(path)

    def record(self, experiment: TradingViewExperiment) -> bool:
        experiments = {item.experiment_id: item for item in self.load()}
        existing = experiments.get(experiment.experiment_id)
        if existing is not None:
            if existing != experiment:
                raise ValueError("immutable TRL experiment conflict")
            return False
        experiments[experiment.experiment_id] = experiment
        self._write(tuple(experiments.values()))
        return True

    def load(self) -> tuple[TradingViewExperiment, ...]:
        if not self.path.exists():
            return ()
        payload = cast(object, json.loads(self.path.read_text(encoding="utf-8")))
        root = _mapping(payload, "TRL registry")
        if root.get("production_influence") is not False:
            raise ValueError("TRL registry production influence must remain false")
        if root.get("schema_version") != TRL_SCHEMA_VERSION:
            raise ValueError("unsupported TRL registry schema")
        rows = _sequence(root.get("experiments"), "experiments")
        experiments = tuple(experiment_from_dict(item) for item in rows)
        ids = tuple(item.experiment_id for item in experiments)
        if len(ids) != len(set(ids)):
            raise ValueError("TRL registry contains duplicate experiment ids")
        return tuple(sorted(experiments, key=lambda item: item.experiment_id))

    def json_text(self) -> str:
        return json.dumps(self._payload(self.load()), indent=2, sort_keys=True) + "\n"

    def csv_text(self) -> str:
        output = io.StringIO(newline="")
        columns = (
            "experiment_id",
            "title",
            "experiment_date",
            "baseline_configuration_id",
            "treatment_configuration_id",
            "observations",
            "symbols",
            "sectors",
            "production_influence",
        )
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        for experiment in self.load():
            writer.writerow(
                {
                    "baseline_configuration_id": (experiment.baseline.configuration_id),
                    "experiment_date": experiment.experiment_date.isoformat(),
                    "experiment_id": experiment.experiment_id,
                    "observations": len(experiment.observations),
                    "production_influence": "false",
                    "sectors": "|".join(
                        sorted({item.sector for item in experiment.observations})
                    ),
                    "symbols": "|".join(
                        sorted({item.symbol for item in experiment.observations})
                    ),
                    "title": experiment.title,
                    "treatment_configuration_id": (
                        experiment.treatment.configuration_id
                    ),
                }
            )
        return output.getvalue()

    def export_json(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.json_text(), encoding="utf-8")
        return path

    def export_csv(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.csv_text(), encoding="utf-8")
        return path

    def _write(self, experiments: tuple[TradingViewExperiment, ...]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            delete=False,
        ) as handle:
            json.dump(self._payload(experiments), handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, self.path)

    def _payload(
        self,
        experiments: tuple[TradingViewExperiment, ...],
    ) -> dict[str, object]:
        return {
            "experiments": [
                item.as_dict()
                for item in sorted(experiments, key=lambda row: row.experiment_id)
            ],
            "production_influence": PRODUCTION_INFLUENCE,
            "schema_version": TRL_SCHEMA_VERSION,
        }


def resolve_registry_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.getenv("ALPHA_TRL_REGISTRY", "").strip()
    return Path(configured) if configured else DEFAULT_TRL_REGISTRY


def experiment_from_dict(value: object) -> TradingViewExperiment:
    row = _mapping(value, "experiment")
    if row.get("production_influence") is not False:
        raise ValueError("TRL experiment production influence must be false")
    return TradingViewExperiment(
        experiment_id=_text(row, "experiment_id"),
        title=_text(row, "title"),
        purpose=_text(row, "purpose"),
        experiment_date=date.fromisoformat(_text(row, "experiment_date")),
        baseline=configuration_from_dict(row.get("baseline")),
        treatment=configuration_from_dict(row.get("treatment")),
        observations=tuple(
            observation_from_dict(item)
            for item in _sequence(row.get("observations"), "observations")
        ),
    )


def configuration_from_dict(value: object) -> LabConfiguration:
    row = _mapping(value, "configuration")
    indicators = tuple(
        IndicatorSetting(
            indicator=IndicatorId(_text(item, "indicator")),
            enabled=_boolean(item, "enabled"),
        )
        for item in _mapped_sequence(row.get("indicators"), "indicators")
    )
    strategies = tuple(
        StrategySetting(
            strategy=StrategyId(_text(item, "strategy")),
            enabled=_boolean(item, "enabled"),
            weight=_decimal(item.get("weight"), "strategy weight"),
        )
        for item in _mapped_sequence(row.get("strategies"), "strategies")
    )
    weights = tuple(
        ComponentWeight(
            component=_text(item, "component"),
            weight=_decimal(item.get("weight"), "component weight"),
        )
        for item in _mapped_sequence(row.get("weights"), "weights")
    )
    return LabConfiguration(
        name=_text(row, "name"),
        indicators=indicators,
        strategies=strategies,
        combination_mode=CombinationMode(_text(row, "combination_mode")),
        minimum_strategies=_integer(
            row.get("minimum_strategies"), "minimum_strategies"
        ),
        weights=weights,
        stop_model=_text(row, "stop_model"),
        exit_model=_text(row, "exit_model"),
        trend_timeframe=_text(row, "trend_timeframe"),
        setup_timeframe=_text(row, "setup_timeframe"),
        entry_timeframe=_text(row, "entry_timeframe"),
        universe=_text(row, "universe"),
        sector_scope=_text(row, "sector_scope"),
    )


def observation_from_dict(value: object) -> ExperimentObservation:
    row = _mapping(value, "observation")
    metrics = _mapping(row.get("metrics"), "metrics")
    return ExperimentObservation(
        role=ObservationRole(_text(row, "role")),
        partition=ResearchPartition(_text(row, "partition")),
        symbol=_text(row, "symbol"),
        sector=_text(row, "sector"),
        period_start=date.fromisoformat(_text(row, "period_start")),
        period_end=date.fromisoformat(_text(row, "period_end")),
        metrics=PerformanceMetrics(
            trade_count=_integer(metrics.get("trade_count"), "trade_count"),
            win_rate_pct=_optional_decimal(metrics.get("win_rate_pct")),
            profit_factor=_optional_decimal(metrics.get("profit_factor")),
            expectancy=_optional_decimal(metrics.get("expectancy")),
            maximum_drawdown_pct=_optional_decimal(metrics.get("maximum_drawdown_pct")),
            net_return_pct=_optional_decimal(metrics.get("net_return_pct")),
            average_winner=_optional_decimal(metrics.get("average_winner")),
            average_loser=_optional_decimal(metrics.get("average_loser")),
            stop_out_rate_pct=_optional_decimal(metrics.get("stop_out_rate_pct")),
            average_holding_period=_optional_decimal(
                metrics.get("average_holding_period")
            ),
        ),
        data_source=_text(row, "data_source"),
    )


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def _mapped_sequence(value: object, label: str) -> tuple[dict[str, object], ...]:
    return tuple(_mapping(item, label) for item in _sequence(value, label))


def _text(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _boolean(row: dict[str, object], key: str) -> bool:
    value = row.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be boolean")
    return value


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    return value


def _decimal(value: object, label: str) -> Decimal:
    if not isinstance(value, (str, int, float, Decimal)) or isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise ValueError(f"{label} must be finite")
    return parsed


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else _decimal(value, "metric")
