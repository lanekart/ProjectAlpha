"""Governed end-to-end HTR-010B1 final closure."""

from __future__ import annotations

import json
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

HTR010B1_FINAL_CONTRACT_VERSION = "HTR-010B1-FINAL-v1.0.0"

_READY = "READY_FOR_GOVERNED_ADJUSTED_REPLAY"
_READY_EXCLUSIONS = "READY_WITH_GOVERNED_EXCLUSIONS"
_BLOCKED_DATA = "BLOCKED_BY_DATA_GAPS"
_BLOCKED_CONTRACT = "BLOCKED_BY_CONTRACT_CONTRADICTIONS"
_BLOCKED_DEFECTS = "BLOCKED_BY_IMPLEMENTATION_DEFECTS"
_CERTIFIED = "CERTIFIED_CONTINUOUS_IDENTITY"
_UNRESOLVED = {
    "INSUFFICIENT_OFFICIAL_EVIDENCE",
    "CONFLICTING_OFFICIAL_EVIDENCE",
    "CERTIFIED_NONCONTINUOUS_IDENTITY",
}


class B1FinalClosureEngine:
    """Rebuild bridge-governed validation and admission state fail-closed."""

    def run(
        self,
        *,
        b1f_certifications_path: Path,
        b1g_directives_path: Path,
        validation_results_path: Path,
        admission_intervals_path: Path,
        upstream_reports: dict[str, Path],
        raw_replay_summary_path: Path | None = None,
        adjusted_replay_summary_path: Path | None = None,
    ) -> dict[str, Any]:
        certifications = _records(b1f_certifications_path)
        directives = _records(b1g_directives_path)
        validations = _records(validation_results_path)
        intervals = _records(admission_intervals_path)
        lineage = _lineage(upstream_reports)

        certification_by_case = _index(certifications, "bridge_case_id", "case_id")
        directive_by_case = _index(directives, "bridge_case_id", "case_id")
        rebuilt_validations = _rebuild_validations(
            validations,
            certification_by_case,
            directive_by_case,
        )
        rebuilt_intervals = _rebuild_intervals(
            intervals,
            certification_by_case,
            directive_by_case,
        )
        exclusions = _governed_exclusions(certifications, directives)
        shadow = _shadow_comparison(
            raw_replay_summary_path,
            adjusted_replay_summary_path,
        )
        contradictions = _contract_contradictions(
            certifications,
            directives,
            rebuilt_validations,
            rebuilt_intervals,
        )
        defects = _implementation_defects(
            certifications,
            directives,
            exclusions,
            rebuilt_validations,
            rebuilt_intervals,
        )
        readiness = _readiness(
            defects=defects,
            contradictions=contradictions,
            exclusions=exclusions,
            shadow=shadow,
        )
        interval_counts = Counter(
            str(row.get("admission_state") or "") for row in rebuilt_intervals
        )
        report = {
            "contract_version": HTR010B1_FINAL_CONTRACT_VERSION,
            "input_bridge_case_count": len(certifications),
            "propagation_directive_count": len(directives),
            "certified_bridge_case_count": sum(
                str(row.get("continuity_decision") or "") == _CERTIFIED
                for row in certifications
            ),
            "governed_exclusion_count": len(exclusions),
            "rebuilt_validation_row_count": len(rebuilt_validations),
            "rebuilt_admission_interval_count": len(rebuilt_intervals),
            "admission_state_counts": dict(sorted(interval_counts.items())),
            "contract_contradiction_count": len(contradictions),
            "contract_contradictions": contradictions,
            "implementation_defect_count": len(defects),
            "implementation_defects": defects,
            "shadow_replay": shadow,
            "upstream_lineage": lineage,
            "final_readiness_decision": readiness,
            "adjusted_replay_integration_enabled": False,
            "benchmark_replay_count": int(shadow["comparison_state"] == "COMPARED"),
            "production_influence": False,
            "rebuilt_validations": list(rebuilt_validations),
            "rebuilt_admission_intervals": list(rebuilt_intervals),
            "governed_exclusions": list(exclusions),
        }
        report["report_sha256"] = _digest(report)
        return report

    @staticmethod
    def export(report: dict[str, Any], output: Path) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        paths = (
            output / "htr010b1_final_closure_report.json",
            output / "htr010b1_final_rebuilt_validations.json",
            output / "htr010b1_final_rebuilt_admission_intervals.json",
            output / "htr010b1_final_governed_exclusions.json",
            output / "htr010b1_final_shadow_replay_comparison.json",
            output / "htr010b1_final_executive_report.md",
        )
        paths[0].write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        paths[1].write_text(
            json.dumps(report["rebuilt_validations"], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        paths[2].write_text(
            json.dumps(
                report["rebuilt_admission_intervals"],
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        paths[3].write_text(
            json.dumps(report["governed_exclusions"], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        paths[4].write_text(
            json.dumps(report["shadow_replay"], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        paths[5].write_text(_markdown(report), encoding="utf-8")
        return paths


def _rebuild_validations(
    rows: tuple[dict[str, Any], ...],
    certifications: dict[str, dict[str, Any]],
    directives: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    by_case = _index(rows, "bridge_case_id", "case_id")
    rebuilt: list[dict[str, Any]] = []
    for case_id, certification in sorted(certifications.items()):
        decision = str(certification.get("continuity_decision") or "")
        certified = decision == _CERTIFIED
        original = by_case.get(case_id, {})
        directive = directives.get(case_id, {})
        rebuilt.append(
            {
                **original,
                "bridge_case_id": case_id,
                "bridge_certified_for_replay": certified,
                "identity_continuity_certified": certified,
                "price_series_continuity_certified": bool(
                    certification.get("price_series_continuity_certified")
                ),
                "tradability_continuity_certified": bool(
                    certification.get("tradability_continuity_certified")
                ),
                "factor_basis_compatible": bool(
                    certification.get("factor_basis_compatible")
                ),
                "official_evidence_ids": certification.get("official_evidence_ids", []),
                "official_document_sha256": certification.get(
                    "official_document_sha256", []
                ),
                "b1g_reconciliation_state": directive.get("reconciliation_state"),
                "b1_final_state": (
                    "CERTIFIED_FOR_GOVERNED_REBUILD"
                    if certified
                    else "GOVERNED_EXCLUSION"
                ),
                "production_influence": False,
            }
        )
    return tuple(rebuilt)


def _rebuild_intervals(
    rows: tuple[dict[str, Any], ...],
    certifications: dict[str, dict[str, Any]],
    directives: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    grouped = _group_intervals(rows)
    rebuilt: list[dict[str, Any]] = []
    for case_id, certification in sorted(certifications.items()):
        decision = str(certification.get("continuity_decision") or "")
        certified = decision == _CERTIFIED
        adjusted = certified and bool(certification.get("adjusted_replay_certified"))
        state = (
            "ADJUSTED_REPLAY_CANDIDATE_PENDING_SHADOW_VALIDATION"
            if adjusted
            else (
                "RAW_REPLAY_CERTIFIED_BRIDGE_CONTINUITY_ONLY"
                if certified
                else "BRIDGE_UNCERTIFIED_QUARANTINED"
            )
        )
        admitted_view = "ADJUSTED" if adjusted else ("RAW" if certified else "NONE")
        source_rows = grouped.get(case_id) or ({},)
        for original in source_rows:
            rebuilt.append(
                {
                    **original,
                    "bridge_case_id": case_id,
                    "pre_isin": certification.get("pre_isin"),
                    "post_isin": certification.get("post_isin"),
                    "effective_from": certification.get("effective_from"),
                    "admission_state": state,
                    "admitted_price_view": admitted_view,
                    "prohibited_price_view": (
                        "RAW" if admitted_view == "ADJUSTED" else "MIXED"
                    ),
                    "reset_required": adjusted,
                    "b1g_required_admission_state": directives.get(case_id, {}).get(
                        "required_admission_state"
                    ),
                    "production_influence": False,
                }
            )
    return tuple(rebuilt)


def _group_intervals(
    rows: tuple[dict[str, Any], ...],
) -> dict[str, tuple[dict[str, Any], ...]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        case_id = str(row.get("bridge_case_id") or row.get("case_id") or "")
        if case_id:
            grouped.setdefault(case_id, []).append(row)
    return {key: tuple(value) for key, value in grouped.items()}


def _governed_exclusions(
    certifications: tuple[dict[str, Any], ...],
    directives: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    directive_by_case = _index(directives, "bridge_case_id", "case_id")
    rows = []
    for certification in certifications:
        decision = str(certification.get("continuity_decision") or "")
        if decision not in _UNRESOLVED:
            continue
        case_id = str(certification.get("bridge_case_id") or "")
        rows.append(
            {
                "bridge_case_id": case_id,
                "symbol": certification.get("post_symbol"),
                "pre_isin": certification.get("pre_isin"),
                "post_isin": certification.get("post_isin"),
                "continuity_decision": decision,
                "quarantine_reason": decision,
                "required_admission_state": "BRIDGE_UNCERTIFIED_QUARANTINED",
                "b1g_reconciliation_state": directive_by_case.get(case_id, {}).get(
                    "reconciliation_state"
                ),
                "production_influence": False,
            }
        )
    return tuple(rows)


def _shadow_comparison(
    raw_path: Path | None,
    adjusted_path: Path | None,
) -> dict[str, Any]:
    if raw_path is None or adjusted_path is None:
        return {
            "comparison_state": "NOT_RUN_INPUT_NOT_PROVIDED",
            "raw_report_sha256": None,
            "adjusted_report_sha256": None,
            "metric_deltas": {},
            "unexplained_divergence_count": 0,
            "production_influence": False,
        }
    raw = _object(raw_path)
    adjusted = _object(adjusted_path)
    metrics = (
        "session_count",
        "eligible_security_count",
        "technical_candidate_count",
        "buy_candidate_count",
        "institutional_approval_count",
        "trade_count",
    )
    deltas = {
        metric: _number(adjusted.get(metric)) - _number(raw.get(metric))
        for metric in metrics
        if metric in raw or metric in adjusted
    }
    unexplained = sum(
        abs(value) > 0
        for metric, value in deltas.items()
        if metric in {"session_count", "eligible_security_count"}
    )
    return {
        "comparison_state": "COMPARED",
        "raw_report_sha256": _digest(raw),
        "adjusted_report_sha256": _digest(adjusted),
        "metric_deltas": deltas,
        "unexplained_divergence_count": unexplained,
        "production_influence": False,
    }


def _contract_contradictions(
    certifications: tuple[dict[str, Any], ...],
    directives: tuple[dict[str, Any], ...],
    validations: tuple[dict[str, Any], ...],
    intervals: tuple[dict[str, Any], ...],
) -> list[str]:
    contradictions: list[str] = []
    certification_by_case = _index(certifications, "bridge_case_id", "case_id")
    directive_by_case = _index(directives, "bridge_case_id", "case_id")
    validation_by_case = _index(validations, "bridge_case_id", "case_id")
    interval_by_case = _index(intervals, "bridge_case_id", "case_id")
    for case_id, certification in certification_by_case.items():
        decision = str(certification.get("continuity_decision") or "")
        certified = decision == _CERTIFIED
        if case_id not in directive_by_case:
            contradictions.append(f"MISSING_B1G_DIRECTIVE:{case_id}")
        if (
            bool(validation_by_case.get(case_id, {}).get("bridge_certified_for_replay"))
            != certified
        ):
            contradictions.append(f"VALIDATION_PROPAGATION_MISMATCH:{case_id}")
        interval = interval_by_case.get(case_id, {})
        admitted = str(interval.get("admitted_price_view") or "") not in {"", "NONE"}
        if admitted != certified:
            contradictions.append(f"ADMISSION_PROPAGATION_MISMATCH:{case_id}")
    return contradictions


def _implementation_defects(
    certifications: tuple[dict[str, Any], ...],
    directives: tuple[dict[str, Any], ...],
    exclusions: tuple[dict[str, Any], ...],
    validations: tuple[dict[str, Any], ...],
    intervals: tuple[dict[str, Any], ...],
) -> list[str]:
    defects: list[str] = []
    if len(certifications) != 24:
        defects.append(f"EXPECTED_24_CERTIFICATIONS_FOUND_{len(certifications)}")
    if len(directives) != 24:
        defects.append(f"EXPECTED_24_DIRECTIVES_FOUND_{len(directives)}")
    if len(validations) != len(certifications):
        defects.append("REBUILT_VALIDATION_COUNT_MISMATCH")
    if not intervals:
        defects.append("NO_REBUILT_ADMISSION_INTERVALS")
    if any(row.get("production_influence") is True for row in intervals):
        defects.append("PRODUCTION_INFLUENCE_TRUE")
    if any(
        row.get("required_admission_state") != "BRIDGE_UNCERTIFIED_QUARANTINED"
        for row in exclusions
    ):
        defects.append("UNSAFE_GOVERNED_EXCLUSION_STATE")
    return defects


def _readiness(
    *,
    defects: list[str],
    contradictions: list[str],
    exclusions: tuple[dict[str, Any], ...],
    shadow: dict[str, Any],
) -> str:
    if defects:
        return _BLOCKED_DEFECTS
    if contradictions:
        return _BLOCKED_CONTRACT
    if shadow["comparison_state"] != "COMPARED":
        return _BLOCKED_DATA
    if int(shadow["unexplained_divergence_count"]) > 0:
        return _BLOCKED_CONTRACT
    return _READY_EXCLUSIONS if exclusions else _READY


def _lineage(paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "path": str(path),
            "sha256": _path_digest(path),
            "exists": path.exists(),
        }
        for name, path in sorted(paths.items())
    }


def _path_digest(path: Path) -> str | None:
    if not path.exists():
        return None
    if path.is_file():
        return sha256(path.read_bytes()).hexdigest()
    digest = sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(child.relative_to(path).as_posix().encode())
        digest.update(child.read_bytes())
    return digest.hexdigest()


def _records(path: Path) -> tuple[dict[str, Any], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return tuple(row for row in payload if isinstance(row, dict))
    if isinstance(payload, dict):
        for key in (
            "cases",
            "records",
            "rows",
            "directives",
            "factor_validation_results",
            "replay_admission_intervals",
            "rebuilt_validations",
            "rebuilt_admission_intervals",
        ):
            rows = payload.get(key)
            if isinstance(rows, list):
                return tuple(row for row in rows if isinstance(row, dict))
    raise ValueError(f"unsupported record payload: {path}")


def _object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object payload: {path}")
    return payload


def _index(
    rows: tuple[dict[str, Any], ...],
    *keys: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = next((str(row.get(key) or "") for key in keys if row.get(key)), "")
        if value:
            result[value] = row
    return result


def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _digest(value: dict[str, Any]) -> str:
    payload = {**value, "report_sha256": ""}
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _markdown(report: dict[str, Any]) -> str:
    keys = (
        "input_bridge_case_count",
        "certified_bridge_case_count",
        "governed_exclusion_count",
        "contract_contradiction_count",
        "implementation_defect_count",
        "final_readiness_decision",
        "report_sha256",
    )
    lines = ["# HTR-010B1 Final Closure", ""]
    lines.extend(f"- {key}: {report.get(key)}" for key in keys)
    lines.extend(["", "PRODUCTION_INFLUENCE=false", ""])
    return "\n".join(lines)


__all__ = ["B1FinalClosureEngine", "HTR010B1_FINAL_CONTRACT_VERSION"]
