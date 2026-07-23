"""HTR-010B1F unique official bridge evidence dossiers."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
from typing import Any

HTR010B1F_DOSSIER_CONTRACT_VERSION = "HTR-010B1F-DOSSIER-v1.0.0"


class OfficialBridgeEvidenceDossierBuilder:
    """Group case-level requests into unique official-document dossiers."""

    def run(self, *, evidence_manifest_output: Path) -> dict[str, Any]:
        requests = _records(
            evidence_manifest_output / "htr010b1f_evidence_requests.json"
        )
        grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for row in requests:
            grouped[_signature(row)].append(row)

        dossiers = tuple(
            _dossier(signature, rows) for signature, rows in sorted(grouped.items())
        )
        duplicate_sizes = Counter(len(row["bridge_case_ids"]) for row in dossiers)
        defects = _defects(requests, dossiers)
        report = {
            "contract_version": HTR010B1F_DOSSIER_CONTRACT_VERSION,
            "input_bridge_case_count": len(requests),
            "unique_dossier_count": len(dossiers),
            "single_case_dossier_count": duplicate_sizes[1],
            "multi_case_dossier_count": sum(
                count for size, count in duplicate_sizes.items() if size > 1
            ),
            "maximum_cases_per_dossier": max(duplicate_sizes, default=0),
            "implementation_defect_count": len(defects),
            "implementation_defects": defects,
            "evidence_download_performed": False,
            "benchmark_replay_count": 0,
            "production_influence": False,
            "dossiers": list(dossiers),
        }
        report["report_sha256"] = _digest(report)
        return report

    @staticmethod
    def export(report: dict[str, Any], output: Path) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        report_path = output / "htr010b1f_evidence_dossiers.json"
        queue_path = output / "htr010b1f_unique_acquisition_queue.json"
        markdown = output / "htr010b1f_evidence_dossiers.md"
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        queue_path.write_text(
            json.dumps(report.get("dossiers", []), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        markdown.write_text(_markdown(report), encoding="utf-8")
        return report_path, queue_path, markdown


def _signature(row: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(row.get("bridge_type") or ""),
        str(row.get("effective_date") or ""),
        str(row.get("pre_isin") or ""),
        str(row.get("post_isin") or ""),
        str(row.get("pre_symbol") or ""),
        str(row.get("post_symbol") or ""),
        str(row.get("pre_series") or ""),
        str(row.get("post_series") or ""),
    )


def _dossier(signature: tuple[str, ...], rows: list[dict[str, Any]]) -> dict[str, Any]:
    (
        bridge_type,
        effective_date,
        pre_isin,
        post_isin,
        pre_symbol,
        post_symbol,
        (pre_series),
        post_series,
    ) = signature
    case_ids = sorted(str(row.get("bridge_case_id") or "") for row in rows)
    material = "|".join(signature)
    return {
        "dossier_id": "htr010b1f-dossier:" + sha256(material.encode()).hexdigest(),
        "bridge_type": bridge_type,
        "effective_date": effective_date,
        "pre_isin": pre_isin or None,
        "post_isin": post_isin or None,
        "pre_symbol": pre_symbol or None,
        "post_symbol": post_symbol or None,
        "pre_series": pre_series or None,
        "post_series": post_series or None,
        "bridge_case_ids": case_ids,
        "bridge_case_count": len(case_ids),
        "preferred_source_classes": rows[0].get("preferred_source_classes", []),
        "required_official_questions": rows[0].get("required_official_questions", []),
        "search_terms": rows[0].get("search_terms", []),
        "evidence_status": "PENDING_OFFICIAL_EVIDENCE",
        "evidence_reuse_policy": (
            "ONE_HASHED_OFFICIAL_DOCUMENT_PACKAGE_MAY_SUPPORT_ALL_LISTED_CASE_IDS_"
            "BUT_EACH_CASE_RETAINS_AN_INDEPENDENT_CERTIFICATION_DECISION"
        ),
        "production_influence": False,
    }


def _defects(
    requests: tuple[dict[str, Any], ...],
    dossiers: tuple[dict[str, Any], ...],
) -> list[str]:
    defects: list[str] = []
    if len(requests) != 24:
        defects.append(f"EXPECTED_24_CASE_REQUESTS_FOUND_{len(requests)}")
    if len(dossiers) != 20:
        defects.append(f"EXPECTED_20_UNIQUE_DOSSIERS_FOUND_{len(dossiers)}")
    mapped = sorted(
        case_id
        for dossier in dossiers
        for case_id in dossier.get("bridge_case_ids", [])
    )
    expected = sorted(str(row.get("bridge_case_id") or "") for row in requests)
    if mapped != expected:
        defects.append("DOSSIER_CASE_MAPPING_NOT_EXACT")
    if any(not dossier.get("dossier_id") for dossier in dossiers):
        defects.append("MISSING_DOSSIER_ID")
    return defects


def _records(path: Path) -> tuple[dict[str, Any], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"expected list payload: {path}")
    return tuple(row for row in payload if isinstance(row, dict))


def _digest(report: dict[str, Any]) -> str:
    payload = {**report, "report_sha256": ""}
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _markdown(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# HTR-010B1F Official Evidence Dossiers",
            "",
            f"- Contract Version: {report['contract_version']}",
            f"- Input Bridge Cases: {report['input_bridge_case_count']}",
            f"- Unique Dossiers: {report['unique_dossier_count']}",
            f"- Multi-Case Dossiers: {report['multi_case_dossier_count']}",
            f"- Implementation Defects: {report['implementation_defect_count']}",
            "- Evidence Download Performed: false",
            "- Benchmark Replays: 0",
            "- Production Influence: false",
            "",
        ]
    )


__all__ = [
    "HTR010B1F_DOSSIER_CONTRACT_VERSION",
    "OfficialBridgeEvidenceDossierBuilder",
]
