"""HTR-010B1F official identity and series bridge certification."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import date
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any

HTR010B1F_CONTRACT_VERSION = "HTR-010B1F-v1.0.0"

_OFFICIAL_SOURCE_CLASSES = {
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


class BridgeCertificationDecision(StrEnum):
    CERTIFIED_CONTINUOUS_IDENTITY = "CERTIFIED_CONTINUOUS_IDENTITY"
    CERTIFIED_NONCONTINUOUS_IDENTITY = "CERTIFIED_NONCONTINUOUS_IDENTITY"
    INSUFFICIENT_OFFICIAL_EVIDENCE = "INSUFFICIENT_OFFICIAL_EVIDENCE"
    CONFLICTING_OFFICIAL_EVIDENCE = "CONFLICTING_OFFICIAL_EVIDENCE"


class OfficialBridgeCertificationEngine:
    """Certify bridge continuity from official effective-dated evidence only."""

    def run(
        self,
        *,
        htr010b1d2_output: Path,
        official_evidence_path: Path | None,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        cases = _records(htr010b1d2_output / "htr010b1d2_reclassified_cases.json")
        selected = tuple(
            row
            for row in cases
            if _is_bridge_case(row)
            and start_date <= (_as_date(row.get("effective_date")) or date.min) <= end_date
        )
        evidence = _records(official_evidence_path) if official_evidence_path else ()
        certifications = tuple(_certify_case(case, evidence) for case in selected)

        decisions = Counter(str(row["continuity_decision"]) for row in certifications)
        bridge_types = Counter(str(row["bridge_type"]) for row in certifications)
        implementation_defects = _implementation_defects(certifications)
        report = {
            "contract_version": HTR010B1F_CONTRACT_VERSION,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "input_bridge_case_count": len(certifications),
            "cross_isin_case_count": bridge_types["CROSS_ISIN"],
            "cross_series_case_count": bridge_types["CROSS_SERIES"],
            "decision_counts": dict(sorted(decisions.items())),
            "certified_continuous_identity_count": decisions[
                BridgeCertificationDecision.CERTIFIED_CONTINUOUS_IDENTITY.value
            ],
            "certified_noncontinuous_identity_count": decisions[
                BridgeCertificationDecision.CERTIFIED_NONCONTINUOUS_IDENTITY.value
            ],
            "insufficient_official_evidence_count": decisions[
                BridgeCertificationDecision.INSUFFICIENT_OFFICIAL_EVIDENCE.value
            ],
            "conflicting_official_evidence_count": decisions[
                BridgeCertificationDecision.CONFLICTING_OFFICIAL_EVIDENCE.value
            ],
            "adjusted_replay_certified_case_count": sum(
                bool(row.get("adjusted_replay_certified")) for row in certifications
            ),
            "adjusted_replay_uncertified_case_count": sum(
                not bool(row.get("adjusted_replay_certified")) for row in certifications
            ),
            "unclassified_bridge_case_count": sum(
                not str(row.get("continuity_decision") or "") for row in certifications
            ),
            "silent_identity_assumption_count": sum(
                bool(row.get("continuity_assumed_without_official_evidence"))
                for row in certifications
            ),
            "implementation_defect_count": len(implementation_defects),
            "implementation_defects": implementation_defects,
            "factor_formula_changed": False,
            "benchmark_replay_count": 0,
            "adjusted_replay_integration_enabled": False,
            "production_policy_changed": False,
            "production_influence": False,
            "cases": list(certifications),
        }
        report["report_sha256"] = _digest(report)
        return report

    @staticmethod
    def export(report: dict[str, Any], output: Path) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        cases = tuple(report.get("cases", ()))
        executive = {key: value for key, value in report.items() if key != "cases"}
        report_json = output / "htr010b1f_official_bridge_certification.json"
        cases_json = output / "htr010b1f_bridge_certifications.json"
        cases_csv = output / "htr010b1f_bridge_certifications.csv"
        unresolved_json = output / "htr010b1f_unresolved_official_evidence.json"
        markdown = output / "htr010b1f_executive_report.md"
        report_json.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        cases_json.write_text(
            json.dumps(list(cases), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        unresolved = tuple(
            row
            for row in cases
            if row.get("continuity_decision")
            in {
                BridgeCertificationDecision.INSUFFICIENT_OFFICIAL_EVIDENCE.value,
                BridgeCertificationDecision.CONFLICTING_OFFICIAL_EVIDENCE.value,
            }
        )
        unresolved_json.write_text(
            json.dumps(list(unresolved), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _write_csv(cases_csv, cases)
        markdown.write_text(_markdown(executive), encoding="utf-8")
        return report_json, cases_json, cases_csv, unresolved_json, markdown


def _certify_case(
    case: dict[str, Any], evidence_rows: tuple[dict[str, Any], ...]
) -> dict[str, Any]:
    bridge_type = str(case.get("bridge_type") or "")
    effective_date = _as_date(case.get("effective_date"))
    matches = tuple(
        row for row in evidence_rows if _evidence_matches(case, row, effective_date)
    )
    official = tuple(row for row in matches if _is_official(row))
    positive = tuple(row for row in official if _evidence_continuity(row) is True)
    negative = tuple(row for row in official if _evidence_continuity(row) is False)

    if positive and negative:
        decision = BridgeCertificationDecision.CONFLICTING_OFFICIAL_EVIDENCE
        reason = "OFFICIAL_EVIDENCE_DISAGREES_ON_IDENTITY_CONTINUITY"
    elif positive:
        decision = BridgeCertificationDecision.CERTIFIED_CONTINUOUS_IDENTITY
        reason = "OFFICIAL_EFFECTIVE_DATED_LINEAGE_CONFIRMS_CONTINUITY"
    elif negative:
        decision = BridgeCertificationDecision.CERTIFIED_NONCONTINUOUS_IDENTITY
        reason = "OFFICIAL_EFFECTIVE_DATED_LINEAGE_CONFIRMS_DISCONTINUITY"
    else:
        decision = BridgeCertificationDecision.INSUFFICIENT_OFFICIAL_EVIDENCE
        reason = "NO_MATCHING_OFFICIAL_EFFECTIVE_DATED_LINEAGE"

    identity_continuity = decision == (
        BridgeCertificationDecision.CERTIFIED_CONTINUOUS_IDENTITY
    )
    tradability_continuity = identity_continuity and bool(
        official
        and all(bool(row.get("tradability_continuity_certified")) for row in official)
    )
    price_series_continuity = identity_continuity and bool(
        official
        and all(bool(row.get("price_series_continuity_certified")) for row in official)
    )
    adjusted_replay_certified = (
        identity_continuity
        and price_series_continuity
        and bool(case.get("factor_quality_confirmed"))
        and (bridge_type != "CROSS_SERIES" or tradability_continuity)
    )

    return {
        "bridge_case_id": case.get("case_id"),
        "source_contract_version": case.get("htr010b1d2_contract_version"),
        "pre_identity_key": _identity_key(case.get("prior_isin")),
        "post_identity_key": _identity_key(case.get("current_isin")),
        "pre_isin": case.get("prior_isin"),
        "post_isin": case.get("current_isin"),
        "pre_symbol": case.get("prior_symbol"),
        "post_symbol": case.get("current_symbol"),
        "pre_series": case.get("prior_series"),
        "post_series": case.get("current_series"),
        "effective_from": case.get("effective_date"),
        "effective_to": None,
        "bridge_type": bridge_type,
        "official_evidence_count": len(official),
        "official_evidence_ids": sorted(
            str(row.get("evidence_id") or row.get("document_id") or "")
            for row in official
            if row.get("evidence_id") or row.get("document_id")
        ),
        "official_evidence_sources": sorted(
            {str(row.get("source_class") or "") for row in official}
        ),
        "official_document_dates": sorted(
            {str(row.get("document_date") or "") for row in official}
        ),
        "official_document_sha256": sorted(
            {str(row.get("source_sha256") or "") for row in official}
        ),
        "continuity_decision": decision.value,
        "continuity_reason": reason,
        "identity_continuity_certified": identity_continuity,
        "price_series_continuity_certified": price_series_continuity,
        "tradability_continuity_certified": tradability_continuity,
        "factor_basis_compatible": bool(
            identity_continuity and case.get("factor_quality_confirmed")
        ),
        "adjusted_replay_certified": adjusted_replay_certified,
        "evidence_confidence": _confidence(decision, official),
        "continuity_assumed_without_official_evidence": False,
        "factor_formula_changed": False,
        "benchmark_replay_count": 0,
        "production_influence": False,
    }


def _is_bridge_case(row: dict[str, Any]) -> bool:
    return str(row.get("bridge_dependency_state") or "") in {
        "UNCERTIFIED_CROSS_ISIN",
        "UNCERTIFIED_CROSS_SERIES",
    }


def _evidence_matches(
    case: dict[str, Any], row: dict[str, Any], effective_date: date | None
) -> bool:
    if effective_date is None:
        return False
    evidence_case_id = str(row.get("bridge_case_id") or "")
    if evidence_case_id and evidence_case_id != str(case.get("case_id") or ""):
        return False
    evidence_date = _as_date(row.get("effective_date"))
    if evidence_date != effective_date:
        return False
    case_isins = {
        str(case.get("prior_isin") or "").upper(),
        str(case.get("current_isin") or "").upper(),
    }
    evidence_isins = {
        str(row.get("pre_isin") or "").upper(),
        str(row.get("post_isin") or "").upper(),
    }
    case_series = {
        str(case.get("prior_series") or "").upper(),
        str(case.get("current_series") or "").upper(),
    }
    evidence_series = {
        str(row.get("pre_series") or "").upper(),
        str(row.get("post_series") or "").upper(),
    }
    if str(case.get("bridge_type") or "") == "CROSS_ISIN":
        return bool(case_isins - {""}) and case_isins == evidence_isins
    return bool(case_series - {""}) and case_series == evidence_series


def _is_official(row: dict[str, Any]) -> bool:
    digest = str(row.get("source_sha256") or "").lower()
    return (
        str(row.get("source_class") or "") in _OFFICIAL_SOURCE_CLASSES
        and bool(row.get("document_id"))
        and _as_date(row.get("document_date")) is not None
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
        and row.get("production_influence") is not True
    )


def _evidence_continuity(row: dict[str, Any]) -> bool | None:
    value = row.get("identity_continuity_certified")
    return value if isinstance(value, bool) else None


def _confidence(
    decision: BridgeCertificationDecision, official: tuple[dict[str, Any], ...]
) -> str:
    if decision in {
        BridgeCertificationDecision.CERTIFIED_CONTINUOUS_IDENTITY,
        BridgeCertificationDecision.CERTIFIED_NONCONTINUOUS_IDENTITY,
    }:
        return "HIGH" if len(official) > 1 else "MEDIUM"
    if decision == BridgeCertificationDecision.CONFLICTING_OFFICIAL_EVIDENCE:
        return "CONFLICTING"
    return "INSUFFICIENT"


def _implementation_defects(cases: tuple[dict[str, Any], ...]) -> list[str]:
    defects: list[str] = []
    if len(cases) != 24:
        defects.append(f"EXPECTED_24_BRIDGE_CASES_FOUND_{len(cases)}")
    if sum(row.get("bridge_type") == "CROSS_ISIN" for row in cases) != 23:
        defects.append("EXPECTED_23_CROSS_ISIN_CASES")
    if sum(row.get("bridge_type") == "CROSS_SERIES" for row in cases) != 1:
        defects.append("EXPECTED_1_CROSS_SERIES_CASE")
    if any(not row.get("continuity_decision") for row in cases):
        defects.append("UNCLASSIFIED_BRIDGE_CASE")
    if any(row.get("continuity_assumed_without_official_evidence") for row in cases):
        defects.append("SILENT_IDENTITY_ASSUMPTION")
    if any(row.get("benchmark_replay_count") != 0 for row in cases):
        defects.append("BENCHMARK_REPLAY_INFLUENCE_DETECTED")
    if any(row.get("production_influence") is not False for row in cases):
        defects.append("PRODUCTION_INFLUENCE_DETECTED")
    return defects


def _records(path: Path | None) -> tuple[dict[str, Any], ...]:
    if path is None or not path.exists():
        return ()
    payload = json.loads(path.read_text())
    if isinstance(payload, list):
        return tuple(row for row in payload if isinstance(row, dict))
    if isinstance(payload, dict):
        for key in ("records", "rows", "cases", "evidence"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return tuple(row for row in rows if isinstance(row, dict))
    raise ValueError(f"unsupported record payload: {path}")


def _identity_key(value: object) -> str | None:
    text = str(value or "").upper()
    return f"nse:isin:{text}" if text else None


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


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
    lines = ["# HTR-010B1F Official Bridge Certification", ""]
    for key, value in report.items():
        lines.append(f"- {key.replace('_', ' ').title()}: {value}")
    lines.extend(["", "PRODUCTION_INFLUENCE=false", ""])
    return "\n".join(lines)


__all__ = [
    "BridgeCertificationDecision",
    "HTR010B1F_CONTRACT_VERSION",
    "OfficialBridgeCertificationEngine",
]
