from __future__ import annotations

import csv
import json
from pathlib import Path

from alpha.market_truth.models import (
    MarketBar,
    MarketTick,
    MarketTruth,
    MarketTruthRecord,
    MarketTruthSystemReport,
    ProviderDescriptor,
    ProviderHealthReport,
    record_as_dict,
)


def render_providers(providers: tuple[ProviderDescriptor, ...]) -> tuple[str, ...]:
    lines = ["Market Truth Provider Registry", f"Providers: {len(providers)}"]
    for item in providers:
        capabilities = ", ".join(value.value for value in item.capabilities)
        lines.append(
            f"- {item.provider_id}: {item.display_name}; "
            f"class={item.provider_class.value}; priority={item.priority}; "
            f"configured={'Yes' if item.configured else 'No'}; "
            f"capabilities={capabilities}"
        )
    lines.extend(_safety())
    return tuple(lines)


def render_health(report: ProviderHealthReport) -> tuple[str, ...]:
    lines = [
        "Market Truth Provider Health",
        f"Generated At: {report.generated_at.isoformat()}",
    ]
    for item in report.providers:
        lines.append(f"- {item.provider_id}: {item.state.value}; {item.message}")
    lines.extend(_safety())
    return tuple(lines)


def render_truth(truth: MarketTruth, *, title: str) -> tuple[str, ...]:
    lines = [
        title,
        f"Dataset: {truth.request.dataset.value}",
        f"Records: {len(truth.records)}",
        f"Source: {truth.source}",
        f"Provider: {truth.provider}",
        f"Timestamp: {truth.timestamp.isoformat()}",
        f"Evidence: {truth.evidence_class.value}",
        (
            f"Confidence: {truth.confidence.confidence_pct}% "
            f"({truth.confidence.band.value})"
        ),
        f"Quality: {truth.quality.quality.value}",
        f"Completeness: {truth.completeness * 100}%",
        f"Version: {truth.version}",
        f"Provenance: {truth.provenance.provenance_id}",
    ]
    if truth.quality.reasons:
        lines.append("Quality Notes: " + " ".join(truth.quality.reasons))
    lines.append("Sample:")
    if not truth.records:
        lines.append("- NO_DATA. Alpha must refuse data-dependent action.")
    else:
        lines.extend(f"- {_record_line(item)}" for item in truth.records[:10])
        if len(truth.records) > 10:
            lines.append(f"- ... {len(truth.records) - 10} more record(s)")
    lines.extend(_safety())
    return tuple(lines)


def render_system_report(report: MarketTruthSystemReport) -> tuple[str, ...]:
    return (
        "Market Truth Engine Report",
        f"Generated At: {report.generated_at.isoformat()}",
        f"Schema Version: {report.schema_version}",
        f"Registered Providers: {report.provider_count}",
        f"Configured Providers: {report.configured_providers}",
        f"Healthy Providers: {report.healthy_providers}",
        f"Degraded Providers: {report.degraded_providers}",
        f"Unavailable / Unconfigured Providers: {report.unavailable_providers}",
        f"Versioned Cache Entries: {report.cached_datasets}",
        "Broker Orders: DISABLED",
        "Automatic Capital Deployment: DISABLED",
        "PRODUCTION_INFLUENCE=false",
    )


def export_truth_json(truth: MarketTruth, path: Path) -> None:
    payload = {
        "request": truth.request.as_dict(),
        "records": [record_as_dict(item) for item in truth.records],
        "source": truth.source,
        "provider": truth.provider,
        "timestamp": truth.timestamp.isoformat(),
        "evidence_class": truth.evidence_class.value,
        "confidence_pct": str(truth.confidence.confidence_pct),
        "confidence_band": truth.confidence.band.value,
        "quality": truth.quality.quality.value,
        "completeness": str(truth.completeness),
        "version": truth.version,
        "provenance_id": truth.provenance.provenance_id,
        "lineage_hash": truth.provenance.lineage_hash,
        "production_influence": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def export_truth_csv(truth: MarketTruth, path: Path) -> None:
    rows = [record_as_dict(item) for item in truth.records]
    fields = sorted({key for row in rows for key in row}) or ["type"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _record_line(record: MarketTruthRecord) -> str:
    if isinstance(record, MarketBar):
        return (
            f"{record.symbol} {record.observed_at.date().isoformat()}: "
            f"O={record.open_price} H={record.high_price} L={record.low_price} "
            f"C={record.close_price} V={record.volume}"
        )
    if isinstance(record, MarketTick):
        return (
            f"{record.symbol} {record.observed_at.isoformat()}: "
            f"last={record.last_price}"
        )
    return json.dumps(record_as_dict(record), sort_keys=True, default=str)


def _safety() -> tuple[str, ...]:
    return (
        "Broker Orders: DISABLED",
        "Automatic Capital Deployment: DISABLED",
        "PRODUCTION_INFLUENCE=false",
    )


__all__ = [
    "export_truth_csv",
    "export_truth_json",
    "render_health",
    "render_providers",
    "render_system_report",
    "render_truth",
]
