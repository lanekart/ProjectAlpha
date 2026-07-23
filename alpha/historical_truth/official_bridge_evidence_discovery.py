"""Deterministic discovery registry templates for HTR-010B1F evidence dossiers."""

from __future__ import annotations

import csv
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

HTR010B1F_DISCOVERY_CONTRACT_VERSION = "HTR-010B1F-DISCOVERY-v1.0.0"


def build_discovery_registry(*, dossiers_path: Path) -> dict[str, Any]:
    """Build one empty, governed discovery row per unique dossier."""

    dossiers = _records(dossiers_path)
    rows = tuple(_template(row) for row in dossiers)
    defects = _defects(dossiers, rows)
    report = {
        "contract_version": HTR010B1F_DISCOVERY_CONTRACT_VERSION,
        "input_dossier_count": len(dossiers),
        "discovery_template_count": len(rows),
        "populated_discovery_count": 0,
        "implementation_defect_count": len(defects),
        "implementation_defects": defects,
        "benchmark_replay_count": 0,
        "production_influence": False,
        "discoveries": list(rows),
    }
    report["report_sha256"] = _digest(report)
    return report


def export_discovery_registry(report: dict[str, Any], output: Path) -> tuple[Path, ...]:
    output.mkdir(parents=True, exist_ok=True)
    rows = tuple(report.get("discoveries", ()))
    report_path = output / "htr010b1f_discovery_registry_report.json"
    registry_json = output / "htr010b1f_discovery_registry.json"
    registry_csv = output / "htr010b1f_discovery_registry.csv"
    markdown = output / "htr010b1f_discovery_registry.md"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    registry_json.write_text(
        json.dumps(list(rows), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_csv(registry_csv, rows)
    markdown.write_text(_markdown(report), encoding="utf-8")
    return report_path, registry_json, registry_csv, markdown


def _template(dossier: dict[str, Any]) -> dict[str, Any]:
    dossier_id = str(dossier.get("dossier_id") or "")
    return {
        "discovery_id": "htr010b1f-discovery:"
        + sha256(dossier_id.encode()).hexdigest(),
        "dossier_id": dossier_id or None,
        "bridge_case_ids": list(dossier.get("bridge_case_ids") or ()),
        "bridge_type": dossier.get("bridge_type"),
        "effective_date": dossier.get("effective_date"),
        "pre_isin": dossier.get("pre_isin"),
        "post_isin": dossier.get("post_isin"),
        "pre_symbol": dossier.get("pre_symbol"),
        "post_symbol": dossier.get("post_symbol"),
        "pre_series": dossier.get("pre_series"),
        "post_series": dossier.get("post_series"),
        "source_class": None,
        "source_url": None,
        "document_id": None,
        "document_date": None,
        "relative_path": None,
        "source_sha256": None,
        "identity_continuity_certified": None,
        "price_series_continuity_certified": None,
        "tradability_continuity_certified": None,
        "official_evidence_excerpt": None,
        "review_notes": None,
        "discovery_state": "PENDING_OFFICIAL_SOURCE_DISCOVERY",
        "production_influence": False,
    }


def _defects(
    dossiers: tuple[dict[str, Any], ...], rows: tuple[dict[str, Any], ...]
) -> list[str]:
    defects: list[str] = []
    if len(dossiers) != 20:
        defects.append(f"EXPECTED_20_DOSSIERS_FOUND_{len(dossiers)}")
    if len(rows) != len(dossiers):
        defects.append("DISCOVERY_TEMPLATE_COUNT_MISMATCH")
    if any(not row.get("dossier_id") for row in rows):
        defects.append("MISSING_DOSSIER_ID")
    if len({str(row.get("discovery_id") or "") for row in rows}) != len(rows):
        defects.append("DUPLICATE_DISCOVERY_ID")
    if any(row.get("production_influence") is True for row in rows):
        defects.append("PRODUCTION_INFLUENCE_TRUE")
    return defects


def _records(path: Path) -> tuple[dict[str, Any], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return tuple(row for row in payload if isinstance(row, dict))
    if isinstance(payload, dict):
        for key in ("records", "rows", "dossiers"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return tuple(row for row in rows if isinstance(row, dict))
    raise ValueError(f"unsupported record payload: {path}")


def _digest(report: dict[str, Any]) -> str:
    payload = {**report, "report_sha256": ""}
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write_csv(path: Path, rows: tuple[dict[str, Any], ...]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, sort_keys=True)
                    if isinstance(value, (dict, list))
                    else value
                    for key, value in row.items()
                }
            )


def _markdown(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# HTR-010B1F Discovery Registry",
            "",
            f"- Contract Version: {report['contract_version']}",
            f"- Input Dossiers: {report['input_dossier_count']}",
            f"- Discovery Templates: {report['discovery_template_count']}",
            f"- Populated Discoveries: {report['populated_discovery_count']}",
            f"- Implementation Defects: {report['implementation_defect_count']}",
            "- Benchmark Replays: 0",
            "- Production Influence: false",
            "",
        ]
    )


__all__ = [
    "HTR010B1F_DISCOVERY_CONTRACT_VERSION",
    "build_discovery_registry",
    "export_discovery_registry",
]
