"""HTR-010B1G official bridge reconciliation and admission propagation planning."""

from __future__ import annotations

import json
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

HTR010B1G_CONTRACT_VERSION = "HTR-010B1G-v1.0.0"
_CERTIFIED = "CERTIFIED_CONTINUOUS_IDENTITY"
_UNRESOLVED = {
    "INSUFFICIENT_OFFICIAL_EVIDENCE",
    "CONFLICTING_OFFICIAL_EVIDENCE",
    "CERTIFIED_NONCONTINUOUS_IDENTITY",
}


class OfficialBridgeReconciliationEngine:
    """Reconcile B1F decisions into downstream validation and admission directives."""

    def run(
        self,
        *,
        bridge_certifications_path: Path,
        validation_results_path: Path,
        admission_intervals_path: Path,
    ) -> dict[str, Any]:
        certifications = _records(bridge_certifications_path)
        validations = _records(validation_results_path)
        intervals = _records(admission_intervals_path)

        validation_by_case = _index(validations, "bridge_case_id", "case_id")
        intervals_by_case = _group(intervals, "bridge_case_id", "case_id")
        directives = tuple(
            _directive(
                certification,
                validation_by_case.get(str(certification.get("bridge_case_id") or "")),
                intervals_by_case.get(
                    str(certification.get("bridge_case_id") or ""), ()
                ),
            )
            for certification in certifications
        )
        states = Counter(str(row["reconciliation_state"]) for row in directives)
        stale = tuple(
            row
            for row in directives
            if row["reconciliation_state"]
            in {
                "CERTIFIED_BUT_DOWNSTREAM_STALE",
                "UNRESOLVED_BUT_DOWNSTREAM_ADMITTED",
                "DOWNSTREAM_STATE_CONTRADICTS_CERTIFICATION",
            }
        )
        unresolved = tuple(
            row for row in directives if not row["identity_continuity_admissible"]
        )
        defects = _defects(certifications, directives)
        report = {
            "contract_version": HTR010B1G_CONTRACT_VERSION,
            "input_bridge_case_count": len(certifications),
            "reconciliation_state_counts": dict(sorted(states.items())),
            "certified_propagation_count": sum(
                row["identity_continuity_admissible"] for row in directives
            ),
            "governed_exclusion_count": len(unresolved),
            "stale_downstream_case_count": len(stale),
            "implementation_defect_count": len(defects),
            "implementation_defects": defects,
            "ready_for_admission_state_rebuild": len(defects) == 0,
            "ready_for_adjusted_replay_integration": False,
            "benchmark_replay_count": 0,
            "production_influence": False,
            "directives": list(sorted(directives, key=_sort_key)),
            "stale_downstream_cases": list(sorted(stale, key=_sort_key)),
            "governed_exclusions": list(sorted(unresolved, key=_sort_key)),
        }
        report["report_sha256"] = _digest(report)
        return report

    @staticmethod
    def export(report: dict[str, Any], output: Path) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        report_path = output / "htr010b1g_reconciliation_report.json"
        directives_path = output / "htr010b1g_propagation_directives.json"
        exclusions_path = output / "htr010b1g_governed_exclusions.json"
        markdown_path = output / "htr010b1g_executive_report.md"
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        directives_path.write_text(
            json.dumps(report.get("directives", []), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        exclusions_path.write_text(
            json.dumps(report.get("governed_exclusions", []), indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        markdown_path.write_text(_markdown(report), encoding="utf-8")
        return report_path, directives_path, exclusions_path, markdown_path


def _directive(
    certification: dict[str, Any],
    validation: dict[str, Any] | None,
    intervals: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    case_id = str(certification.get("bridge_case_id") or "")
    decision = str(certification.get("continuity_decision") or "")
    certified = decision == _CERTIFIED
    validation_certified = _optional_bool(
        validation.get("bridge_certified_for_replay") if validation else None
    )
    admitted = any(_interval_is_admitted(row) for row in intervals)

    if certified and validation_certified is True and admitted:
        state = "CERTIFIED_AND_PROPAGATED"
    elif certified and (validation_certified is not True or not admitted):
        state = "CERTIFIED_BUT_DOWNSTREAM_STALE"
    elif decision in _UNRESOLVED and admitted:
        state = "UNRESOLVED_BUT_DOWNSTREAM_ADMITTED"
    elif decision in _UNRESOLVED:
        state = "GOVERNED_EXCLUSION_PROPAGATED"
    else:
        state = "DOWNSTREAM_STATE_CONTRADICTS_CERTIFICATION"

    return {
        "bridge_case_id": case_id,
        "bridge_type": certification.get("bridge_type"),
        "pre_isin": certification.get("pre_isin"),
        "post_isin": certification.get("post_isin"),
        "pre_series": certification.get("pre_series"),
        "post_series": certification.get("post_series"),
        "effective_from": certification.get("effective_from"),
        "continuity_decision": decision,
        "identity_continuity_admissible": certified,
        "required_validation_bridge_certified_for_replay": certified,
        "required_admission_state": (
            "REBUILD_FROM_CERTIFIED_BRIDGE"
            if certified
            else "BRIDGE_UNCERTIFIED_QUARANTINED"
        ),
        "observed_validation_bridge_certified_for_replay": validation_certified,
        "observed_admitted_interval_count": sum(
            _interval_is_admitted(row) for row in intervals
        ),
        "observed_interval_count": len(intervals),
        "reconciliation_state": state,
        "quarantine_reason": None if certified else decision,
        "adjusted_replay_integration_enabled": False,
        "production_influence": False,
    }


def _interval_is_admitted(row: dict[str, Any]) -> bool:
    state = str(row.get("admission_state") or "")
    view = str(row.get("admitted_price_view") or "")
    return (
        view not in {"", "NONE"} and "QUARANTIN" not in state and state != "UNRESOLVED"
    )


def _records(path: Path) -> tuple[dict[str, Any], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return tuple(row for row in payload if isinstance(row, dict))
    if isinstance(payload, dict):
        for key in (
            "cases",
            "records",
            "rows",
            "factor_validation_results",
            "replay_admission_intervals",
            "directives",
        ):
            rows = payload.get(key)
            if isinstance(rows, list):
                return tuple(row for row in rows if isinstance(row, dict))
    raise ValueError(f"unsupported record payload: {path}")


def _index(rows: tuple[dict[str, Any], ...], *keys: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = next((str(row.get(key) or "") for key in keys if row.get(key)), "")
        if value:
            result[value] = row
    return result


def _group(
    rows: tuple[dict[str, Any], ...], *keys: str
) -> dict[str, tuple[dict[str, Any], ...]]:
    mutable: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        value = next((str(row.get(key) or "") for key in keys if row.get(key)), "")
        if value:
            mutable.setdefault(value, []).append(row)
    return {key: tuple(value) for key, value in mutable.items()}


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _defects(
    certifications: tuple[dict[str, Any], ...],
    directives: tuple[dict[str, Any], ...],
) -> list[str]:
    defects: list[str] = []
    if len(certifications) != 24:
        defects.append(f"EXPECTED_24_CERTIFICATIONS_FOUND_{len(certifications)}")
    if len(directives) != len(certifications):
        defects.append("PROPAGATION_DIRECTIVE_COUNT_MISMATCH")
    if any(not row.get("bridge_case_id") for row in directives):
        defects.append("MISSING_BRIDGE_CASE_ID")
    if any(row.get("production_influence") is True for row in directives):
        defects.append("PRODUCTION_INFLUENCE_TRUE")
    return defects


def _sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("effective_from") or ""), str(row.get("bridge_case_id") or "")


def _digest(report: dict[str, Any]) -> str:
    payload = {**report, "report_sha256": ""}
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _markdown(report: dict[str, Any]) -> str:
    lines = ["# HTR-010B1G Reconciliation", ""]
    for key in (
        "input_bridge_case_count",
        "certified_propagation_count",
        "governed_exclusion_count",
        "stale_downstream_case_count",
        "implementation_defect_count",
        "ready_for_admission_state_rebuild",
        "ready_for_adjusted_replay_integration",
        "report_sha256",
    ):
        lines.append(f"- {key}: {report.get(key)}")
    lines.extend(["", "PRODUCTION_INFLUENCE=false", ""])
    return "\n".join(lines)


__all__ = ["HTR010B1G_CONTRACT_VERSION", "OfficialBridgeReconciliationEngine"]
