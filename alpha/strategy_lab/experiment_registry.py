from __future__ import annotations

import csv
import json
import os
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from alpha.strategy_lab.models import STRATEGY_LAB_SCHEMA_VERSION, StrategyLabReport

DEFAULT_STRATEGY_LAB_REGISTRY = Path(".alpha/strategy_lab/experiment_registry.json")


class StrategyLabExperimentRegistry:
    """Append-only registry that permanently remembers tested and failed strategies."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_strategy_lab_registry(path)

    def record(self, report: StrategyLabReport) -> bool:
        payload = self._read()
        experiments = _rows(payload.get("experiments"))
        row = _jsonable(report)
        existing = next(
            (
                item
                for item in experiments
                if item.get("experiment_id") == report.experiment_id
            ),
            None,
        )
        if existing is not None:
            if existing != row:
                raise ValueError("immutable strategy lab experiment conflict")
            return False
        experiments.append(row)
        payload["experiments"] = sorted(
            experiments, key=lambda item: str(item.get("experiment_id", ""))
        )
        self._write(payload)
        return True

    def latest_payload(self) -> dict[str, Any] | None:
        experiments = _rows(self._read().get("experiments"))
        return experiments[-1] if experiments else None

    def export_json(self, path: Path | str) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self._read(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return destination

    def export_csv(self, path: Path | str) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fields_ = (
            "experiment_id",
            "dataset_version",
            "strategy_id",
            "strategy_hash",
            "family",
            "conditions",
            "entry_rule",
            "stop_rule",
            "target_rule",
            "holding_period_days",
            "evidence_label",
            "classification",
            "completed_trades",
            "precision_pct",
            "expectancy_pct",
            "profit_factor",
            "payoff_ratio",
            "maximum_drawdown_pct",
            "research_score",
            "rejection_reason",
            "production_influence",
        )
        with destination.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields_)
            writer.writeheader()
            for experiment in _rows(self._read().get("experiments")):
                for result in _rows(experiment.get("results")):
                    writer.writerow(_csv_row(experiment, result))
        return destination

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": STRATEGY_LAB_SCHEMA_VERSION,
                "production_influence": False,
                "experiments": [],
            }
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("strategy lab registry must be an object")
        if payload.get("production_influence") is not False:
            raise ValueError("strategy lab registry must remain research-only")
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        payload["schema_version"] = STRATEGY_LAB_SCHEMA_VERSION
        payload["production_influence"] = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, self.path)


def resolve_strategy_lab_registry(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.getenv("ALPHA_STRATEGY_LAB_REGISTRY", "").strip()
    return Path(configured) if configured else DEFAULT_STRATEGY_LAB_REGISTRY


def _jsonable(value: object) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _jsonable(getattr(value, item.name)) for item in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def _rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _csv_row(experiment: dict[str, Any], result: dict[str, Any]) -> dict[str, object]:
    strategy = result.get("strategy", {})
    metrics = result.get("metrics", {})
    reasons = result.get("classification_reasons", [])
    conditions = strategy.get("conditions", []) if isinstance(strategy, dict) else []
    return {
        "experiment_id": experiment.get("experiment_id", ""),
        "dataset_version": experiment.get("dataset_version", ""),
        "strategy_id": strategy.get("strategy_id", "")
        if isinstance(strategy, dict)
        else "",
        "strategy_hash": strategy.get("strategy_hash", "")
        if isinstance(strategy, dict)
        else "",
        "family": strategy.get("family", "") if isinstance(strategy, dict) else "",
        "conditions": json.dumps(conditions, sort_keys=True),
        "entry_rule": strategy.get("entry_rule", "")
        if isinstance(strategy, dict)
        else "",
        "stop_rule": strategy.get("stop_rule", "")
        if isinstance(strategy, dict)
        else "",
        "target_rule": strategy.get("target_rule", "")
        if isinstance(strategy, dict)
        else "",
        "holding_period_days": strategy.get("holding_period_days", "")
        if isinstance(strategy, dict)
        else "",
        "evidence_label": result.get("evidence_label", ""),
        "classification": result.get("classification", ""),
        "completed_trades": metrics.get("completed_trades", "")
        if isinstance(metrics, dict)
        else "",
        "precision_pct": metrics.get("precision_pct", "")
        if isinstance(metrics, dict)
        else "",
        "expectancy_pct": metrics.get("expectancy_pct", "")
        if isinstance(metrics, dict)
        else "",
        "profit_factor": metrics.get("profit_factor", "")
        if isinstance(metrics, dict)
        else "",
        "payoff_ratio": metrics.get("payoff_ratio", "")
        if isinstance(metrics, dict)
        else "",
        "maximum_drawdown_pct": metrics.get("maximum_drawdown_pct", "")
        if isinstance(metrics, dict)
        else "",
        "research_score": result.get("research_score", ""),
        "rejection_reason": " | ".join(str(item) for item in reasons),
        "production_influence": "false",
    }


__all__ = [
    "DEFAULT_STRATEGY_LAB_REGISTRY",
    "StrategyLabExperimentRegistry",
    "resolve_strategy_lab_registry",
]
