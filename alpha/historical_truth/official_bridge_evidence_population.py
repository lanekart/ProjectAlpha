"""Governed population of HTR-010B1F official-source discovery records."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

HTR010B1F_DISCOVERY_POPULATION_CONTRACT_VERSION = (
    "HTR-010B1F-DISCOVERY-POPULATION-v1.0.0"
)

_ALLOWED_SOURCE_CLASSES = {
    "NSE_SECURITY_MASTER",
    "NSE_SYMBOL_CHANGE_NOTICE",
    "NSE_CORPORATE_ACTION_NOTICE",
    "NSE_SCHEME_OF_ARRANGEMENT_NOTICE",
    "NSE_LISTING_NOTICE",
    "NSE_SUSPENSION_RELISTING_NOTICE",
    "NSE_DELISTING_NOTICE",
    "NSE_ISSUER_FILING",
    "BSE_OFFICIAL_NOTICE",
    "DEPOSITORY_OFFICIAL_RECORD",
    "SEBI_OFFICIAL_ORDER",
}

_ALLOWED_HOST_SUFFIXES = (
    "nseindia.com",
    "nsearchives.nseindia.com",
    "archives.nseindia.com",
    "bseindia.com",
    "sebi.gov.in",
    "nsdl.co.in",
    "cdslindia.com",
)


class OfficialBridgeEvidenceDiscoveryPopulationEngine:
    """Merge reviewed source findings into blank governed dossier rows."""

    def run(
        self,
        *,
        discovery_registry_path: Path,
        reviewed_findings_path: Path | None,
    ) -> dict[str, Any]:
        registry = _records(discovery_registry_path)
        findings = _records(reviewed_findings_path) if reviewed_findings_path else ()
        registry_by_id = {
            str(row.get("dossier_id") or ""): row
            for row in registry
            if row.get("dossier_id")
        }
        grouped_findings: dict[str, list[dict[str, Any]]] = {}
        for finding in findings:
            dossier_id = str(finding.get("dossier_id") or "")
            grouped_findings.setdefault(dossier_id, []).append(finding)

        populated: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for dossier_id, template in sorted(registry_by_id.items()):
            candidates = grouped_findings.pop(dossier_id, [])
            if not candidates:
                populated.append(_pending(template))
                continue
            for candidate in candidates:
                state, reasons = _validate(template, candidate)
                if state == "POPULATED_OFFICIAL_SOURCE":
                    populated.append(_merge(template, candidate, state, reasons))
                else:
                    rejected.append(_merge(template, candidate, state, reasons))

        for unknown_dossier, candidates in sorted(grouped_findings.items()):
            for candidate in candidates:
                rejected.append(
                    {
                        **candidate,
                        "dossier_id": unknown_dossier or None,
                        "discovery_state": "REJECTED_UNKNOWN_DOSSIER",
                        "validation_reasons": ["DOSSIER_NOT_IN_GOVERNED_REGISTRY"],
                        "production_influence": False,
                    }
                )

        populated_rows = tuple(_sorted(populated))
        rejected_rows = tuple(_sorted(rejected))
        states = Counter(
            str(row.get("discovery_state") or "") for row in populated_rows
        )
        defects = _defects(registry, populated_rows, rejected_rows)
        report = {
            "contract_version": HTR010B1F_DISCOVERY_POPULATION_CONTRACT_VERSION,
            "input_registry_count": len(registry),
            "input_reviewed_finding_count": len(findings),
            "populated_official_source_count": states["POPULATED_OFFICIAL_SOURCE"],
            "pending_official_source_count": states[
                "PENDING_OFFICIAL_SOURCE_DISCOVERY"
            ],
            "rejected_finding_count": len(rejected_rows),
            "implementation_defect_count": len(defects),
            "implementation_defects": defects,
            "evidence_download_performed": False,
            "benchmark_replay_count": 0,
            "production_influence": False,
            "discoveries": list(populated_rows),
            "rejected_findings": list(rejected_rows),
        }
        report["report_sha256"] = _digest(report)
        return report

    @staticmethod
    def export(report: dict[str, Any], output: Path) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        discoveries = tuple(report.get("discoveries", ()))
        rejected = tuple(report.get("rejected_findings", ()))
        report_path = output / "htr010b1f_discovery_population_report.json"
        discoveries_json = output / "htr010b1f_populated_discoveries.json"
        discoveries_csv = output / "htr010b1f_populated_discoveries.csv"
        rejected_json = output / "htr010b1f_rejected_discovery_findings.json"
        markdown = output / "htr010b1f_discovery_population_report.md"
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        discoveries_json.write_text(
            json.dumps(list(discoveries), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _write_csv(discoveries_csv, discoveries)
        rejected_json.write_text(
            json.dumps(list(rejected), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        markdown.write_text(_markdown(report), encoding="utf-8")
        return report_path, discoveries_json, discoveries_csv, rejected_json, markdown


def _pending(template: dict[str, Any]) -> dict[str, Any]:
    return {
        **template,
        "discovery_state": "PENDING_OFFICIAL_SOURCE_DISCOVERY",
        "production_influence": False,
    }


def _merge(
    template: dict[str, Any],
    finding: dict[str, Any],
    state: str,
    reasons: list[str],
) -> dict[str, Any]:
    return {
        **template,
        **finding,
        "dossier_id": template.get("dossier_id"),
        "effective_date": template.get("effective_date"),
        "pre_isin": template.get("pre_isin"),
        "post_isin": template.get("post_isin"),
        "pre_symbol": template.get("pre_symbol"),
        "post_symbol": template.get("post_symbol"),
        "pre_series": template.get("pre_series"),
        "post_series": template.get("post_series"),
        "discovery_state": state,
        "validation_reasons": reasons,
        "production_influence": False,
    }


def _validate(
    template: dict[str, Any], finding: dict[str, Any]
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    source_class = str(finding.get("source_class") or "")
    source_url = str(finding.get("source_url") or "")
    if source_class not in _ALLOWED_SOURCE_CLASSES:
        reasons.append("SOURCE_CLASS_NOT_ALLOWED")
    if not _official_url(source_url):
        reasons.append("SOURCE_URL_NOT_OFFICIAL_HTTPS")
    if not finding.get("document_id"):
        reasons.append("MISSING_DOCUMENT_ID")
    if _as_date(finding.get("document_date")) is None:
        reasons.append("INVALID_DOCUMENT_DATE")
    if _as_date(finding.get("effective_date")) != _as_date(
        template.get("effective_date")
    ):
        reasons.append("EFFECTIVE_DATE_MISMATCH")
    for key in ("pre_isin", "post_isin", "pre_series", "post_series"):
        candidate = str(finding.get(key) or "").upper()
        governed = str(template.get(key) or "").upper()
        if candidate and candidate != governed:
            reasons.append(f"{key.upper()}_MISMATCH")
    return (
        "POPULATED_OFFICIAL_SOURCE" if not reasons else "REJECTED_REVIEWED_FINDING",
        reasons,
    )


def _official_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(
        host == suffix or host.endswith("." + suffix)
        for suffix in _ALLOWED_HOST_SUFFIXES
    )


def _defects(
    registry: tuple[dict[str, Any], ...],
    discoveries: tuple[dict[str, Any], ...],
    rejected: tuple[dict[str, Any], ...],
) -> list[str]:
    defects: list[str] = []
    if len(registry) != 20:
        defects.append(f"EXPECTED_20_REGISTRY_ROWS_FOUND_{len(registry)}")
    if len({str(row.get("dossier_id") or "") for row in registry}) != len(registry):
        defects.append("DUPLICATE_REGISTRY_DOSSIER_ID")
    governed_ids = {str(row.get("dossier_id") or "") for row in registry}
    output_ids = {str(row.get("dossier_id") or "") for row in discoveries}
    if not output_ids <= governed_ids:
        defects.append("OUTPUT_CONTAINS_UNKNOWN_DOSSIER")
    if any(row.get("production_influence") is True for row in discoveries + rejected):
        defects.append("PRODUCTION_INFLUENCE_TRUE")
    return defects


def _records(path: Path | None) -> tuple[dict[str, Any], ...]:
    if path is None or not path.exists():
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return tuple(row for row in payload if isinstance(row, dict))
    if isinstance(payload, dict):
        for key in (
            "records",
            "rows",
            "discoveries",
            "findings",
            "reviewed_findings",
        ):
            rows = payload.get(key)
            if isinstance(rows, list):
                return tuple(row for row in rows if isinstance(row, dict))
    raise ValueError(f"unsupported record payload: {path}")


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _sorted(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("dossier_id") or ""),
            str(row.get("document_id") or ""),
            str(row.get("source_url") or ""),
        ),
    )


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
            "# HTR-010B1F Discovery Population",
            "",
            f"- Contract Version: {report['contract_version']}",
            f"- Registry Rows: {report['input_registry_count']}",
            f"- Reviewed Findings: {report['input_reviewed_finding_count']}",
            f"- Populated Sources: {report['populated_official_source_count']}",
            f"- Pending Sources: {report['pending_official_source_count']}",
            f"- Rejected Findings: {report['rejected_finding_count']}",
            f"- Implementation Defects: {report['implementation_defect_count']}",
            "- Evidence Download Performed: false",
            "- Benchmark Replays: 0",
            "- Production Influence: false",
            "",
        ]
    )


__all__ = [
    "HTR010B1F_DISCOVERY_POPULATION_CONTRACT_VERSION",
    "OfficialBridgeEvidenceDiscoveryPopulationEngine",
]
