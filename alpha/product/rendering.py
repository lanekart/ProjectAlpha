from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from alpha.product.reports import ProductReport, ReportValue, ScalarValue


@dataclass(frozen=True, slots=True)
class ProductTextRenderer:
    """Render product reports into deterministic human-readable text lines."""

    def render(self, report: ProductReport) -> tuple[str, ...]:
        lines: list[str] = [
            report.metadata.title,
            "",
            f"Kind       : {report.metadata.kind}",
            f"Observed On: {report.metadata.observed_on.isoformat()}",
            f"Version    : {report.metadata.version}",
        ]

        if report.metadata.attributes:
            lines.append("")
            lines.append("Metadata:")
            for metadata_key, metadata_value in report.metadata.attributes.items():
                lines.append(f"- {metadata_key}: {_render_value(metadata_value)}")

        for section in report.sections:
            lines.append("")
            lines.append(section.title)

            for metric_key, metric_value in section.metrics.items():
                lines.append(f"- {metric_key}: {_render_value(metric_value)}")

            for line in section.lines:
                lines.append(f"- {line}")

        if report.diagnostics:
            lines.append("")
            lines.append("Diagnostics:")
            lines.extend(f"- {line}" for line in report.diagnostics)

        return tuple(lines)


def _render_value(value: ReportValue | ScalarValue) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return ", ".join(_render_scalar(item) for item in value)
    if isinstance(value, Mapping):
        return ", ".join(f"{key}={_render_scalar(item)}" for key, item in value.items())
    return _render_scalar(value)


def _render_scalar(value: ScalarValue) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return ""
    return str(value)


__all__ = ["ProductTextRenderer"]
