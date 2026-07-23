"""Case-level materialization for verified HTR-010B1F bridge evidence."""

from __future__ import annotations

import csv
import json
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

HTR010B1F_MATERIALIZATION_CONTRACT_VERSION = "HTR-010B1F-MATERIALIZE-v1.0.0"


class OfficialBridgeEvidenceMaterializationEngine:
    """Expand verified dossier documents into immutable case-level evidence."""

    def run(
        self,
        *,
        dossiers_path: Path,
        admissible_documents_path: Path,
    ) -> dict[str, Any]:
        dossiers = _records(dossiers_path)
        documents = _records(admissible_documents_path)
        dossier_by_id = {
            str(row.get("dossier_id") or ""): row
            for row in dossiers
            if row.get("dossier_id")
        }
        rows: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for document in documents:
            dossier_id = str(document.get("dossier_id") or "")
            dossier = dossier_by_id.get(dossier_id)
            if dossier is None:
                rejected.append(
                    {
                        **document,
                        "materialization_state": "UNKNOWN_DOSSIER",
                        "production_influence": False,
                    }
                )
                continue
            case_ids = tuple(
                str(value)
                for value in dossier.get("bridge_case_ids", ())
                if str(value)
            )
            if not case_ids:
                rejected.append(
                    {
                        **document,
                        "materialization_state": "DOSSIER_HAS_NO_CASE_IDS",
                        "production_influence": False,
                    }
                )
                continue
            if not _document_matches_dossier(document, dossier):
                rejected.append(
                    {
                        **document,
                        "materialization_state": "DOCUMENT_DOSSIER_MISMATCH",
                        "production_influence": False,
                    }
                )
                continue
            for case_id in case_ids:
                rows.append(_case_evidence(document, dossier, case_id))

        materialized = tuple(
            sorted(
                rows,
                key=lambda row: (
                    str(row.get("bridge_case_id") or ""),
                    str(row.get("document_id") or ""),
                ),
            )
        )
        rejected_rows = tuple(
            sorted(
                rejected,
                key=lambda row: (
                    str(row.get("dossier_id") or ""),
                    str(row.get("document_id") or ""),
                ),
            )
        )
        case_counts = Counter(
            str(row.get("bridge_case_id") or "") for row in materialized
        )
        defects = _defects(dossiers, materialized, rejected_rows)
        report = {
            "contract_version": HTR010B1F_MATERIALIZATION_CONTRACT_VERSION,
            "input_dossier_count": len(dossiers),
            "input_verified_document_count": len(documents),
            "materialized_case_evidence_count": len(materialized),
            "covered_bridge_case_count": len(case_counts),
            "rejected_document_count": len(rejected_rows),
            "implementation_defect_count": len(defects),
            "implementation_defects": defects,
            "benchmark_replay_count": 0,
            "production_influence": False,
            "case_evidence": list(materialized),
            "rejected_documents": list(rejected_rows),
        }
        report["report_sha256"] = _digest(report)
        return report

    @staticmethod
    def export(report: dict[str, Any], output: Path) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        case_evidence = tuple(report.get("case_evidence", ()))
        rejected = tuple(report.get("rejected_documents", ()))
        report_path = output / "htr010b1f_materialization_report.json"
        evidence_json = output / "htr010b1f_case_level_official_evidence.json"
        evidence_csv = output / "htr010b1f_case_level_official_evidence.csv"
        rejected_json = output / "htr010b1f_rejected_materialization_documents.json"
        markdown = output / "htr010b1f_materialization_report.md"
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        evidence_json.write_text(
            json.dumps(list(case_evidence), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _write_csv(evidence_csv, case_evidence)
        rejected_json.write_text(
            json.dumps(list(rejected), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        markdown.write_text(_markdown(report), encoding="utf-8")
        return report_path, evidence_json, evidence_csv, rejected_json, markdown


def _case_evidence(
    document: dict[str, Any], dossier: dict[str, Any], case_id: str
) -> dict[str, Any]:
    return {
        **document,
        "bridge_case_id": case_id,
        "dossier_id": dossier.get("dossier_id"),
        "effective_date": dossier.get("effective_date"),
        "pre_isin": dossier.get("pre_isin"),
        "post_isin": dossier.get("post_isin"),
        "pre_symbol": dossier.get("pre_symbol"),
        "post_symbol": dossier.get("post_symbol"),
        "pre_series": dossier.get("pre_series"),
        "post_series": dossier.get("post_series"),
        "materialization_state": "MATERIALIZED_TO_CASE",
        "evidence_reused_across_case_count": len(dossier.get("bridge_case_ids", ())),
        "independent_certification_decision_required": True,
        "production_influence": False,
    }


def _document_matches_dossier(
    document: dict[str, Any], dossier: dict[str, Any]
) -> bool:
    comparisons = (
        ("effective_date", False),
        ("pre_isin", True),
        ("post_isin", True),
        ("pre_series", True),
        ("post_series", True),
    )
    for key, upper in comparisons:
        document_value = str(document.get(key) or "")
        dossier_value = str(dossier.get(key) or "")
        if upper:
            document_value = document_value.upper()
            dossier_value = dossier_value.upper()
        if document_value and document_value != dossier_value:
            return False
    return True


def _defects(
    dossiers: tuple[dict[str, Any], ...],
    materialized: tuple[dict[str, Any], ...],
    rejected: tuple[dict[str, Any], ...],
) -> list[str]:
    defects: list[str] = []
    if len(dossiers) != 20:
        defects.append(f"EXPECTED_20_DOSSIERS_FOUND_{len(dossiers)}")
    if any(row.get("production_influence") is True for row in materialized):
        defects.append("PRODUCTION_INFLUENCE_TRUE")
    if any(not row.get("bridge_case_id") for row in materialized):
        defects.append("MATERIALIZED_ROW_MISSING_CASE_ID")
    if any(
        row.get("materialization_state") != "MATERIALIZED_TO_CASE"
        for row in materialized
    ):
        defects.append("INVALID_MATERIALIZATION_STATE")
    if any(row.get("production_influence") is True for row in rejected):
        defects.append("REJECTED_ROW_PRODUCTION_INFLUENCE_TRUE")
    return defects


def _records(path: Path) -> tuple[dict[str, Any], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return tuple(row for row in payload if isinstance(row, dict))
    if isinstance(payload, dict):
        for key in (
            "records",
            "rows",
            "dossiers",
            "documents",
            "case_evidence",
            "evidence",
        ):
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
            "# HTR-010B1F Case-Level Evidence Materialization",
            "",
            f"- Contract Version: {report['contract_version']}",
            f"- Input Dossiers: {report['input_dossier_count']}",
            f"- Verified Documents: {report['input_verified_document_count']}",
            (
                "- Materialized Evidence Rows: "
                f"{report['materialized_case_evidence_count']}"
            ),
            f"- Covered Bridge Cases: {report['covered_bridge_case_count']}",
            f"- Rejected Documents: {report['rejected_document_count']}",
            f"- Implementation Defects: {report['implementation_defect_count']}",
            "- Benchmark Replays: 0",
            "- Production Influence: false",
            "",
        ]
    )


__all__ = [
    "HTR010B1F_MATERIALIZATION_CONTRACT_VERSION",
    "OfficialBridgeEvidenceMaterializationEngine",
]
