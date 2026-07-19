"""Persistent, deterministic registry for governed research experiments."""

from __future__ import annotations

import csv
import io
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import cast

from alpha.research.models import (
    IRD_VERSION,
    PRODUCTION_INFLUENCE,
    ExperimentDecision,
    ExperimentStatus,
    MetricAvailability,
    MetricProvenance,
    RegisteredResearchExperiment,
    ResearchConfidence,
    ResearchMetric,
    ResearchSubsystem,
)

DEFAULT_RESEARCH_REGISTRY_PATH = Path(".alpha/research/experiment_registry.json")


class ResearchExperimentRegistry:
    """Append-safe immutable registry keyed by experiment id."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_research_registry_path(path)

    def record(self, experiment: RegisteredResearchExperiment) -> bool:
        experiments = {item.experiment_id: item for item in self.load()}
        existing = experiments.get(experiment.experiment_id)
        if existing is not None:
            if existing != experiment:
                raise ValueError(
                    "experiment id already exists with different evidence: "
                    f"{experiment.experiment_id}"
                )
            return False
        experiments[experiment.experiment_id] = experiment
        self._write(tuple(experiments.values()))
        return True

    def load(self) -> tuple[RegisteredResearchExperiment, ...]:
        if not self.path.exists():
            return ()
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            return ()
        decoded = cast(object, json.loads(raw))
        if not isinstance(decoded, dict):
            raise ValueError("research registry root must be an object")
        if decoded.get("production_influence") is not False:
            raise ValueError("research registry production influence must be false")
        rows = decoded.get("experiments", [])
        if not isinstance(rows, list):
            raise ValueError("research registry experiments must be a list")
        experiments = tuple(_experiment_from_object(row) for row in rows)
        ids = tuple(item.experiment_id for item in experiments)
        if len(ids) != len(set(ids)):
            raise ValueError("research registry contains duplicate experiment ids")
        return tuple(sorted(experiments, key=_experiment_sort_key))

    def json_text(self) -> str:
        return _canonical_json(_registry_payload(self.load())) + "\n"

    def csv_text(self) -> str:
        output = io.StringIO(newline="")
        columns = (
            "experiment_id",
            "title",
            "subsystem",
            "date",
            "purpose",
            "evidence_sources",
            "baseline",
            "treatment",
            "metrics",
            "statistical_confidence",
            "decision",
            "status",
            "findings",
            "lessons_learned",
            "production_influence",
        )
        writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for experiment in self.load():
            payload = _experiment_payload(experiment)
            writer.writerow(
                {
                    "experiment_id": experiment.experiment_id,
                    "title": experiment.title,
                    "subsystem": experiment.subsystem.value,
                    "date": experiment.experiment_date.isoformat(),
                    "purpose": experiment.purpose,
                    "evidence_sources": _canonical_json(payload["evidence_sources"]),
                    "baseline": _canonical_json(payload["baseline"]),
                    "treatment": _canonical_json(payload["treatment"]),
                    "metrics": _canonical_json(payload["metrics"]),
                    "statistical_confidence": (experiment.statistical_confidence.value),
                    "decision": experiment.decision.value,
                    "status": experiment.status.value,
                    "findings": _canonical_json(payload["findings"]),
                    "lessons_learned": _canonical_json(payload["lessons_learned"]),
                    "production_influence": "false",
                }
            )
        return output.getvalue()

    def export_json(self, path: Path | str) -> Path:
        destination = Path(path)
        _write_text(destination, self.json_text())
        return destination

    def export_csv(self, path: Path | str) -> Path:
        destination = Path(path)
        _write_text(destination, self.csv_text())
        return destination

    def _write(self, experiments: tuple[RegisteredResearchExperiment, ...]) -> None:
        ordered = tuple(sorted(experiments, key=_experiment_sort_key))
        _write_text(
            self.path,
            _canonical_json(_registry_payload(ordered)) + "\n",
        )


def resolve_research_registry_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.getenv("ALPHA_RESEARCH_REGISTRY_PATH")
    return Path(configured) if configured else DEFAULT_RESEARCH_REGISTRY_PATH


def _registry_payload(
    experiments: tuple[RegisteredResearchExperiment, ...],
) -> dict[str, object]:
    return {
        "version": IRD_VERSION,
        "production_influence": PRODUCTION_INFLUENCE,
        "experiments": [_experiment_payload(item) for item in experiments],
    }


def _experiment_payload(
    experiment: RegisteredResearchExperiment,
) -> dict[str, object]:
    return {
        "experiment_id": experiment.experiment_id,
        "title": experiment.title,
        "subsystem": experiment.subsystem.value,
        "date": experiment.experiment_date.isoformat(),
        "purpose": experiment.purpose,
        "evidence_sources": list(experiment.evidence_sources),
        "baseline": [_metric_payload(item) for item in experiment.baseline],
        "treatment": [_metric_payload(item) for item in experiment.treatment],
        "metrics": list(experiment.metrics),
        "statistical_confidence": experiment.statistical_confidence.value,
        "decision": experiment.decision.value,
        "status": experiment.status.value,
        "findings": list(experiment.findings),
        "lessons_learned": list(experiment.lessons_learned),
        "production_influence": experiment.production_influence,
    }


def _metric_payload(metric: ResearchMetric) -> dict[str, object]:
    value_type, value = _encoded_value(metric.value)
    return {
        "metric_id": metric.metric_id,
        "label": metric.label,
        "value": value,
        "value_type": value_type,
        "unit": metric.unit,
        "numerator": _number_text(metric.numerator),
        "denominator": _number_text(metric.denominator),
        "availability": metric.availability_status.value,
        "source": metric.provenance.source,
        "definition": metric.provenance.definition,
        "population": metric.provenance.population,
        "version": metric.provenance.version,
    }


def _encoded_value(value: bool | int | str | Decimal | None) -> tuple[str, object]:
    if value is None:
        return "null", None
    if isinstance(value, bool):
        return "bool", value
    if isinstance(value, int):
        return "int", value
    if isinstance(value, Decimal):
        return "decimal", str(value)
    return "string", value


def _experiment_from_object(value: object) -> RegisteredResearchExperiment:
    row = _object_dict(value, "experiment")
    influence = row.get("production_influence")
    if influence is not False:
        raise ValueError("experiment production influence must be false")
    from datetime import date

    return RegisteredResearchExperiment(
        experiment_id=_required_string(row, "experiment_id"),
        title=_required_string(row, "title"),
        subsystem=ResearchSubsystem(_required_string(row, "subsystem")),
        experiment_date=date.fromisoformat(_required_string(row, "date")),
        purpose=_required_string(row, "purpose"),
        evidence_sources=_string_tuple(row.get("evidence_sources")),
        baseline=_metric_tuple(row.get("baseline")),
        treatment=_metric_tuple(row.get("treatment")),
        metrics=_string_tuple(row.get("metrics")),
        statistical_confidence=ResearchConfidence(
            _required_string(row, "statistical_confidence")
        ),
        decision=ExperimentDecision(_required_string(row, "decision")),
        status=ExperimentStatus(_required_string(row, "status")),
        findings=_optional_string_tuple(row.get("findings", [])),
        lessons_learned=_optional_string_tuple(row.get("lessons_learned", [])),
        production_influence=False,
    )


def _metric_tuple(value: object) -> tuple[ResearchMetric, ...]:
    if not isinstance(value, list):
        raise ValueError("experiment metrics must be a list")
    return tuple(_metric_from_object(item) for item in value)


def _metric_from_object(value: object) -> ResearchMetric:
    row = _object_dict(value, "metric")
    return ResearchMetric(
        metric_id=_required_string(row, "metric_id"),
        label=_required_string(row, "label"),
        value=_decoded_value(row.get("value_type"), row.get("value")),
        unit=_required_string(row, "unit"),
        numerator=_optional_number(row.get("numerator")),
        denominator=_optional_number(row.get("denominator")),
        availability=MetricAvailability(
            str(row.get("availability", "AVAILABLE"))
            if row.get("value") is not None
            else str(row.get("availability", "UNAVAILABLE"))
        ),
        provenance=MetricProvenance(
            source=_required_string(row, "source"),
            definition=_required_string(row, "definition"),
            population=_required_string(row, "population"),
            version=_required_string(row, "version"),
        ),
    )


def _decoded_value(
    value_type: object, value: object
) -> bool | int | str | Decimal | None:
    if value_type == "null":
        return None
    if value_type == "bool" and isinstance(value, bool):
        return value
    if value_type == "int" and isinstance(value, int) and not isinstance(value, bool):
        return value
    if value_type == "decimal" and isinstance(value, str):
        return Decimal(value)
    if value_type == "string" and isinstance(value, str):
        return value
    raise ValueError("research metric contains an invalid encoded value")


def _object_dict(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} keys must be strings")
    return cast(dict[str, object], value)


def _required_string(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"research registry field {key} must be a non-empty string")
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("research registry field must be a list of strings")
    return tuple(cast(list[str], value))


def _optional_string_tuple(value: object) -> tuple[str, ...]:
    return _string_tuple(value)


def _number_text(value: int | Decimal | None) -> str | int | None:
    if isinstance(value, Decimal):
        return str(value)
    return value


def _optional_number(value: object) -> int | Decimal | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        return Decimal(value)
    raise ValueError("research metric numerator or denominator is invalid")


def _experiment_sort_key(
    experiment: RegisteredResearchExperiment,
) -> tuple[str, str]:
    return (experiment.experiment_date.isoformat(), experiment.experiment_id)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
        separators=(",", ": "),
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


__all__ = [
    "DEFAULT_RESEARCH_REGISTRY_PATH",
    "ResearchExperimentRegistry",
    "resolve_research_registry_path",
]
