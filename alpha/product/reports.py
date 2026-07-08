from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any

ScalarValue = str | int | float | Decimal | bool | date | None
ReportValue = ScalarValue | tuple[ScalarValue, ...] | Mapping[str, ScalarValue]


@dataclass(frozen=True, slots=True)
class ProductReportMetadata:
    """Stable metadata attached to every product-facing report."""

    kind: str
    title: str
    observed_on: date
    version: str = "1"
    attributes: Mapping[str, ScalarValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kind = self.kind.strip().lower()
        title = self.title.strip()
        version = self.version.strip()
        attributes = _normalize_mapping(self.attributes)

        if not kind:
            raise ValueError("report kind cannot be empty")
        if not title:
            raise ValueError("report title cannot be empty")
        if not version:
            raise ValueError("report version cannot be empty")

        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "attributes", attributes)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "observed_on": self.observed_on.isoformat(),
            "version": self.version,
            "attributes": _serialize_mapping(self.attributes),
        }


@dataclass(frozen=True, slots=True)
class ProductReportSection:
    """A deterministic report section.

    Sections are presentation-neutral. They can be rendered to text, serialized
    to JSON, or transformed into future formats without changing domain engines.
    """

    title: str
    lines: tuple[str, ...] = ()
    metrics: Mapping[str, ReportValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        title = self.title.strip()
        lines = tuple(line.strip() for line in self.lines)
        metrics = _normalize_mapping(self.metrics)

        if not title:
            raise ValueError("section title cannot be empty")
        if any(not line for line in lines):
            raise ValueError("section lines cannot be empty")

        object.__setattr__(self, "title", title)
        object.__setattr__(self, "lines", lines)
        object.__setattr__(self, "metrics", metrics)

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "lines": list(self.lines),
            "metrics": _serialize_mapping(self.metrics),
        }


@dataclass(frozen=True, slots=True)
class ProductReport:
    """Immutable product report consumed by renderers and exporters."""

    metadata: ProductReportMetadata
    sections: tuple[ProductReportSection, ...]
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.sections) == 0:
            raise ValueError("product report requires at least one section")

        diagnostics = tuple(line.strip() for line in self.diagnostics)
        if any(not line for line in diagnostics):
            raise ValueError("diagnostic lines cannot be empty")

        object.__setattr__(self, "diagnostics", diagnostics)

    @property
    def kind(self) -> str:
        return self.metadata.kind

    @property
    def observed_on(self) -> date:
        return self.metadata.observed_on

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.metadata.kind,
            "metadata": self.metadata.as_dict(),
            "sections": [section.as_dict() for section in self.sections],
            "diagnostics": list(self.diagnostics),
        }


def _normalize_mapping(
    values: Mapping[str, ReportValue | ScalarValue],
) -> Mapping[str, ReportValue | ScalarValue]:
    normalized: dict[str, ReportValue | ScalarValue] = {}
    for key, value in values.items():
        normalized_key = key.strip()
        if not normalized_key:
            raise ValueError("mapping keys cannot be empty")
        normalized[normalized_key] = _normalize_value(value)
    return MappingProxyType(dict(sorted(normalized.items())))


def _normalize_value(value: ReportValue | ScalarValue) -> ReportValue | ScalarValue:
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, Mapping):
        return MappingProxyType(
            dict(
                sorted(
                    (
                        str(item_key).strip(),
                        _normalize_scalar(item_value),
                    )
                    for item_key, item_value in value.items()
                    if str(item_key).strip()
                )
            )
        )
    if isinstance(value, Sequence) and not isinstance(value, str):
        return tuple(_normalize_scalar(item) for item in value)
    return _normalize_scalar(value)


def _normalize_scalar(value: Any) -> ScalarValue:
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, Decimal | date | str | int | float | bool) or value is None:
        return value
    return str(value)


def _serialize_mapping(
    values: Mapping[str, ReportValue | ScalarValue],
) -> dict[str, Any]:
    return {key: _serialize_value(value) for key, value in values.items()}


def _serialize_value(value: ReportValue | ScalarValue) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {key: _serialize_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_serialize_value(item) for item in value]
    return value


__all__ = [
    "ProductReport",
    "ProductReportMetadata",
    "ProductReportSection",
    "ReportValue",
    "ScalarValue",
]
