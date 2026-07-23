"""Governed acquisition staging for HTR-010B1F official bridge evidence."""

from __future__ import annotations

import csv
import json
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

HTR010B1F_ACQUISITION_CONTRACT_VERSION = "HTR-010B1F-ACQUISITION-v1.0.0"

_DISCOVERY_SOURCE_CLASSES = {
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


class OfficialBridgeEvidenceAcquisitionEngine:
    """Stage discoveries and admit only byte-verified official documents."""

    def run(
        self,
        *,
        dossiers_path: Path,
        discoveries_path: Path | None,
        downloaded_documents_root: Path | None,
    ) -> dict[str, Any]:
        dossiers = _records(dossiers_path)
        discoveries = _records(discoveries_path) if discoveries_path else ()
        dossier_ids = {str(row.get("dossier_id") or "") for row in dossiers}
        staged = tuple(
            _stage_discovery(row, dossier_ids, downloaded_documents_root)
            for row in discoveries
        )
        states = Counter(str(row["acquisition_state"]) for row in staged)
        defects = _defects(dossiers, staged)
        report = {
            "contract_version": HTR010B1F_ACQUISITION_CONTRACT_VERSION,
            "input_dossier_count": len(dossiers),
            "input_discovery_count": len(discoveries),
            "verified_official_document_count": states["VERIFIED_OFFICIAL_DOCUMENT"],
            "pending_download_count": states["PENDING_DOWNLOAD"],
            "invalid_discovery_count": states["INVALID_DISCOVERY"],
            "hash_mismatch_count": states["HASH_MISMATCH"],
            "missing_document_count": states["MISSING_DOCUMENT"],
            "implementation_defect_count": len(defects),
            "implementation_defects": defects,
            "benchmark_replay_count": 0,
            "production_influence": False,
            "documents": list(staged),
        }
        report["report_sha256"] = _digest(report)
        return report

    @staticmethod
    def export(report: dict[str, Any], output: Path) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        documents = tuple(report.get("documents", ()))
        report_path = output / "htr010b1f_acquisition_report.json"
        documents_json = output / "htr010b1f_acquired_documents.json"
        documents_csv = output / "htr010b1f_acquired_documents.csv"
        admissible_json = output / "htr010b1f_admissible_official_evidence.json"
        markdown = output / "htr010b1f_acquisition_report.md"
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        documents_json.write_text(
            json.dumps(list(documents), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _write_csv(documents_csv, documents)
        admissible = tuple(
            _admissible_evidence(row)
            for row in documents
            if row.get("acquisition_state") == "VERIFIED_OFFICIAL_DOCUMENT"
        )
        admissible_json.write_text(
            json.dumps(list(admissible), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        markdown.write_text(_markdown(report), encoding="utf-8")
        return (
            report_path,
            documents_json,
            documents_csv,
            admissible_json,
            markdown,
        )


def _stage_discovery(
    row: dict[str, Any],
    dossier_ids: set[str],
    downloaded_documents_root: Path | None,
) -> dict[str, Any]:
    dossier_id = str(row.get("dossier_id") or "")
    source_class = str(row.get("source_class") or "")
    source_url = str(row.get("source_url") or "")
    relative_path = str(row.get("relative_path") or "")
    expected_sha256 = str(row.get("source_sha256") or "").lower()
    valid_discovery = (
        dossier_id in dossier_ids
        and source_class in _DISCOVERY_SOURCE_CLASSES
        and source_url.startswith("https://")
        and bool(row.get("document_id"))
        and bool(row.get("document_date"))
    )
    actual_sha256: str | None = None
    state = "INVALID_DISCOVERY"
    file_size_bytes: int | None = None
    if valid_discovery and not relative_path:
        state = "PENDING_DOWNLOAD"
    elif valid_discovery and downloaded_documents_root is None:
        state = "PENDING_DOWNLOAD"
    elif valid_discovery:
        assert downloaded_documents_root is not None
        document_path = downloaded_documents_root / relative_path
        if not document_path.exists() or not document_path.is_file():
            state = "MISSING_DOCUMENT"
        else:
            payload = document_path.read_bytes()
            actual_sha256 = sha256(payload).hexdigest()
            file_size_bytes = len(payload)
            if expected_sha256 and expected_sha256 != actual_sha256:
                state = "HASH_MISMATCH"
            else:
                state = "VERIFIED_OFFICIAL_DOCUMENT"
                expected_sha256 = actual_sha256
    return {
        **row,
        "dossier_id": dossier_id or None,
        "source_class": source_class or None,
        "source_url": source_url or None,
        "relative_path": relative_path or None,
        "source_sha256": expected_sha256 or None,
        "actual_sha256": actual_sha256,
        "file_size_bytes": file_size_bytes,
        "acquisition_state": state,
        "production_influence": False,
    }


def _admissible_evidence(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_id": row.get("evidence_id") or row.get("document_id"),
        "bridge_case_id": row.get("bridge_case_id"),
        "dossier_id": row.get("dossier_id"),
        "source_class": row.get("source_class"),
        "document_id": row.get("document_id"),
        "document_date": row.get("document_date"),
        "effective_date": row.get("effective_date"),
        "source_url": row.get("source_url"),
        "source_sha256": row.get("actual_sha256"),
        "pre_isin": row.get("pre_isin"),
        "post_isin": row.get("post_isin"),
        "pre_symbol": row.get("pre_symbol"),
        "post_symbol": row.get("post_symbol"),
        "pre_series": row.get("pre_series"),
        "post_series": row.get("post_series"),
        "identity_continuity_certified": row.get("identity_continuity_certified"),
        "price_series_continuity_certified": row.get(
            "price_series_continuity_certified"
        ),
        "tradability_continuity_certified": row.get("tradability_continuity_certified"),
        "official_evidence_excerpt": row.get("official_evidence_excerpt"),
        "review_notes": row.get("review_notes"),
        "production_influence": False,
    }


def _defects(
    dossiers: tuple[dict[str, Any], ...], staged: tuple[dict[str, Any], ...]
) -> list[str]:
    defects: list[str] = []
    if len(dossiers) != 20:
        defects.append(f"EXPECTED_20_DOSSIERS_FOUND_{len(dossiers)}")
    if len({str(row.get("dossier_id") or "") for row in dossiers}) != len(dossiers):
        defects.append("DUPLICATE_DOSSIER_ID")
    if any(row.get("production_influence") is True for row in staged):
        defects.append("PRODUCTION_INFLUENCE_TRUE")
    return defects


def _records(path: Path | None) -> tuple[dict[str, Any], ...]:
    if path is None or not path.exists():
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return tuple(row for row in payload if isinstance(row, dict))
    if isinstance(payload, dict):
        for key in ("records", "rows", "dossiers", "documents", "discoveries"):
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
            "# HTR-010B1F Official Evidence Acquisition",
            "",
            f"- Contract Version: {report['contract_version']}",
            f"- Input Dossiers: {report['input_dossier_count']}",
            f"- Discoveries: {report['input_discovery_count']}",
            f"- Verified Documents: {report['verified_official_document_count']}",
            f"- Pending Downloads: {report['pending_download_count']}",
            f"- Hash Mismatches: {report['hash_mismatch_count']}",
            f"- Implementation Defects: {report['implementation_defect_count']}",
            "- Benchmark Replays: 0",
            "- Production Influence: false",
            "",
        ]
    )


__all__ = [
    "HTR010B1F_ACQUISITION_CONTRACT_VERSION",
    "OfficialBridgeEvidenceAcquisitionEngine",
]
