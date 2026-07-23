"""HTR-010B1F official bridge evidence acquisition manifest."""

from __future__ import annotations

import csv
import json
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

HTR010B1F_EVIDENCE_MANIFEST_VERSION = "HTR-010B1F-EVIDENCE-v1.0.0"

_SOURCE_PRIORITY = (
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
)


class OfficialBridgeEvidenceManifestBuilder:
    """Build deterministic official-evidence acquisition requests for B1F."""

    def run(self, *, htr010b1d2_output: Path) -> dict[str, Any]:
        cases = _records(htr010b1d2_output / "htr010b1d2_reclassified_cases.json")
        selected = tuple(row for row in cases if _is_bridge_case(row))
        requests = tuple(_request(row) for row in selected)
        bridge_types = Counter(str(row["bridge_type"]) for row in requests)
        defects = _defects(requests)
        report = {
            "contract_version": HTR010B1F_EVIDENCE_MANIFEST_VERSION,
            "input_bridge_case_count": len(requests),
            "cross_isin_case_count": bridge_types["CROSS_ISIN"],
            "cross_series_case_count": bridge_types["CROSS_SERIES"],
            "source_priority": list(_SOURCE_PRIORITY),
            "implementation_defect_count": len(defects),
            "implementation_defects": defects,
            "evidence_download_performed": False,
            "benchmark_replay_count": 0,
            "production_influence": False,
            "requests": list(requests),
        }
        report["report_sha256"] = _digest(report)
        return report

    @staticmethod
    def export(report: dict[str, Any], output: Path) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        requests = tuple(report.get("requests", ()))
        report_path = output / "htr010b1f_evidence_manifest.json"
        requests_json = output / "htr010b1f_evidence_requests.json"
        requests_csv = output / "htr010b1f_evidence_requests.csv"
        evidence_template = output / "htr010b1f_official_evidence_template.json"
        markdown = output / "htr010b1f_evidence_manifest.md"
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        requests_json.write_text(
            json.dumps(list(requests), indent=2, sort_keys=True) + "\n"
        )
        _write_csv(requests_csv, requests)
        evidence_template.write_text(
            json.dumps(
                [_evidence_template(row) for row in requests],
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        markdown.write_text(_markdown(report))
        return report_path, requests_json, requests_csv, evidence_template, markdown


def _request(case: dict[str, Any]) -> dict[str, Any]:
    bridge_type = str(case.get("bridge_type") or "")
    pre_isin = case.get("prior_isin")
    post_isin = case.get("current_isin")
    pre_series = case.get("prior_series")
    post_series = case.get("current_series")
    effective_date = case.get("effective_date")
    return {
        "evidence_request_id": "htr010b1f-request:"
        + sha256(str(case.get("case_id") or "").encode()).hexdigest(),
        "bridge_case_id": case.get("case_id"),
        "bridge_type": bridge_type,
        "effective_date": effective_date,
        "pre_isin": pre_isin,
        "post_isin": post_isin,
        "pre_symbol": case.get("prior_symbol"),
        "post_symbol": case.get("current_symbol"),
        "pre_series": pre_series,
        "post_series": post_series,
        "bridge_dependency_state": case.get("bridge_dependency_state"),
        "required_official_questions": _questions(bridge_type),
        "preferred_source_classes": list(_SOURCE_PRIORITY),
        "search_terms": _search_terms(case),
        "evidence_status": "PENDING_OFFICIAL_EVIDENCE",
        "production_influence": False,
    }


def _questions(bridge_type: str) -> list[str]:
    common = [
        (
            "Does official effective-dated evidence identify the predecessor "
            "and successor as the same economic security?"
        ),
        (
            "Does official evidence certify price-series comparability across "
            "the effective date?"
        ),
    ]
    if bridge_type == "CROSS_SERIES":
        common.append(
            "Does official evidence certify tradability continuity across the "
            "series transition?"
        )
    return common


def _search_terms(case: dict[str, Any]) -> list[str]:
    values = {
        str(case.get("prior_isin") or ""),
        str(case.get("current_isin") or ""),
        str(case.get("prior_symbol") or ""),
        str(case.get("current_symbol") or ""),
        str(case.get("effective_date") or ""),
    }
    if str(case.get("bridge_type") or "") == "CROSS_SERIES":
        values.update(
            {
                str(case.get("prior_series") or ""),
                str(case.get("current_series") or ""),
            }
        )
    return sorted(value for value in values if value)


def _evidence_template(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_id": None,
        "bridge_case_id": request.get("bridge_case_id"),
        "source_class": None,
        "document_id": None,
        "document_date": None,
        "effective_date": request.get("effective_date"),
        "source_url": None,
        "source_sha256": None,
        "pre_isin": request.get("pre_isin"),
        "post_isin": request.get("post_isin"),
        "pre_symbol": request.get("pre_symbol"),
        "post_symbol": request.get("post_symbol"),
        "pre_series": request.get("pre_series"),
        "post_series": request.get("post_series"),
        "identity_continuity_certified": None,
        "price_series_continuity_certified": None,
        "tradability_continuity_certified": None,
        "official_evidence_excerpt": None,
        "review_notes": None,
        "production_influence": False,
    }


def _is_bridge_case(row: dict[str, Any]) -> bool:
    return str(row.get("bridge_dependency_state") or "") in {
        "UNCERTIFIED_CROSS_ISIN",
        "UNCERTIFIED_CROSS_SERIES",
    }


def _defects(requests: tuple[dict[str, Any], ...]) -> list[str]:
    defects: list[str] = []
    if len(requests) != 24:
        defects.append(f"EXPECTED_24_BRIDGE_CASES_FOUND_{len(requests)}")
    if sum(row.get("bridge_type") == "CROSS_ISIN" for row in requests) != 23:
        defects.append("EXPECTED_23_CROSS_ISIN_CASES")
    if sum(row.get("bridge_type") == "CROSS_SERIES" for row in requests) != 1:
        defects.append("EXPECTED_1_CROSS_SERIES_CASE")
    if any(not row.get("bridge_case_id") for row in requests):
        defects.append("MISSING_BRIDGE_CASE_ID")
    if any(not row.get("effective_date") for row in requests):
        defects.append("MISSING_EFFECTIVE_DATE")
    return defects


def _records(path: Path) -> tuple[dict[str, Any], ...]:
    payload = json.loads(path.read_text())
    if isinstance(payload, list):
        return tuple(row for row in payload if isinstance(row, dict))
    if isinstance(payload, dict):
        for key in ("records", "rows", "cases"):
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
            "# HTR-010B1F Official Evidence Manifest",
            "",
            f"- Contract Version: {report['contract_version']}",
            f"- Bridge Cases: {report['input_bridge_case_count']}",
            f"- Cross-ISIN Cases: {report['cross_isin_case_count']}",
            f"- Cross-Series Cases: {report['cross_series_case_count']}",
            f"- Implementation Defects: {report['implementation_defect_count']}",
            "- Evidence Download Performed: false",
            "- Benchmark Replays: 0",
            "- Production Influence: false",
            "",
        ]
    )


__all__ = [
    "HTR010B1F_EVIDENCE_MANIFEST_VERSION",
    "OfficialBridgeEvidenceManifestBuilder",
]
