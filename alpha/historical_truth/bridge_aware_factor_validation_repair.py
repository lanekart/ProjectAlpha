"""HTR-010B1D2 bridge-aware factor-validation contract repair."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

HTR010B1D2_CONTRACT_VERSION = "HTR-010B1D2-v1.0.0"


class BridgeAwareFactorValidationRepairEngine:
    """Correct factor dispositions without changing factors or replay admission."""

    def run(
        self,
        *,
        htr010b1d1_output: Path,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        cases = _records(htr010b1d1_output / "htr010b1d1_bridge_cases.json")
        selected = tuple(
            row
            for row in cases
            if start_date
            <= (_as_date(row.get("effective_date")) or date.min)
            <= end_date
        )
        grouped = _group_cases(selected)
        group_audits = tuple(
            _group_audit(key, rows) for key, rows in sorted(grouped.items())
        )
        group_by_case = {
            str(case_id): audit
            for audit in group_audits
            for case_id in audit["case_ids"]
        }
        repaired = tuple(
            _repair_case(row, group_by_case.get(str(row.get("case_id")), {}))
            for row in selected
        )
        dispositions = Counter(str(row["corrected_disposition"]) for row in repaired)
        proposed = Counter(str(row["proposed_validation_outcome"]) for row in repaired)
        bridge_states = Counter(str(row["bridge_dependency_state"]) for row in repaired)
        repairs = Counter(str(row["recommended_contract_repair"]) for row in repaired)
        report = {
            "contract_version": HTR010B1D2_CONTRACT_VERSION,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "case_count": len(repaired),
            "same_session_group_count": sum(
                int(audit["factor_count"] > 1) for audit in group_audits
            ),
            "composite_confirmed_group_count": sum(
                audit["group_disposition"] == "COMPOSITE_FACTOR_CONFIRMED"
                for audit in group_audits
            ),
            "disposition_counts": dict(sorted(dispositions.items())),
            "proposed_validation_outcome_counts": dict(sorted(proposed.items())),
            "bridge_dependency_counts": dict(sorted(bridge_states.items())),
            "recommended_contract_repair_counts": dict(sorted(repairs.items())),
            "factor_confirmed_case_count": sum(
                bool(row["factor_quality_confirmed"]) for row in repaired
            ),
            "factor_unconfirmed_case_count": sum(
                not bool(row["factor_quality_confirmed"]) for row in repaired
            ),
            "replay_bridge_certified_case_count": sum(
                bool(row["bridge_certified_for_replay"]) for row in repaired
            ),
            "replay_bridge_uncertified_case_count": sum(
                not bool(row["bridge_certified_for_replay"]) for row in repaired
            ),
            "implementation_defect_should_remain_count": sum(
                row["proposed_validation_outcome"] == "IMPLEMENTATION_DEFECT"
                for row in repaired
            ),
            "official_factor_mutated": False,
            "admission_policy_changed": False,
            "full_benchmark_replays": 0,
            "production_influence": False,
            "same_session_groups": list(group_audits),
            "cases": list(
                sorted(
                    repaired,
                    key=lambda row: (
                        str(row.get("effective_date") or ""),
                        str(row.get("identity_key") or ""),
                        str(row.get("case_id") or ""),
                    ),
                )
            ),
        }
        report["report_sha256"] = _digest(report)
        return report

    @staticmethod
    def export(report: dict[str, Any], output: Path) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        cases = tuple(report.get("cases", ()))
        groups = tuple(report.get("same_session_groups", ()))
        executive = {
            key: value
            for key, value in report.items()
            if key not in {"cases", "same_session_groups"}
        }
        report_json = output / "htr010b1d2_validation_repair.json"
        cases_json = output / "htr010b1d2_reclassified_cases.json"
        cases_csv = output / "htr010b1d2_reclassified_cases.csv"
        groups_json = output / "htr010b1d2_same_session_groups.json"
        markdown = output / "htr010b1d2_executive_report.md"
        report_json.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        cases_json.write_text(
            json.dumps(list(cases), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        groups_json.write_text(
            json.dumps(list(groups), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _write_csv(cases_csv, cases)
        markdown.write_text(_markdown(executive), encoding="utf-8")
        return report_json, cases_json, cases_csv, groups_json, markdown


def _group_cases(
    cases: tuple[dict[str, Any], ...],
) -> dict[tuple[str, ...], list[dict[str, Any]]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in cases:
        key = (
            str(row.get("identity_key") or ""),
            str(row.get("effective_date") or ""),
            str(row.get("prior_isin") or ""),
            str(row.get("prior_series") or ""),
            str(row.get("prior_session") or ""),
            str(row.get("current_isin") or ""),
            str(row.get("current_series") or ""),
            str(row.get("current_session") or ""),
        )
        grouped[key].append(row)
    return grouped


def _group_audit(
    key: tuple[str, ...],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    factors = tuple(_number(row.get("official_price_factor")) for row in rows)
    composite = _product(factors)
    selected = rows[0].get("selected_bridge")
    selected_bridge = selected if isinstance(selected, dict) else {}
    prior = selected_bridge.get("prior")
    current = selected_bridge.get("current")
    prior_row = prior if isinstance(prior, dict) else {}
    current_row = current if isinstance(current, dict) else {}
    atr = _number(selected_bridge.get("atr_before"))
    previous_close = _number(prior_row.get("close_price"))
    action_open = _number(current_row.get("open_price"))
    raw_gap = _gap_atr(action_open, previous_close, atr, 1.0)
    composite_gap = _gap_atr(action_open, previous_close, atr, composite)
    if len(rows) <= 1:
        disposition = "NOT_A_COMPOSITE_GROUP"
    elif composite_gap is None:
        disposition = "COMPOSITE_FACTOR_INSUFFICIENT_CANDLE_CONTEXT"
    elif _restores(composite_gap, raw_gap):
        disposition = "COMPOSITE_FACTOR_CONFIRMED"
    else:
        disposition = "COMPOSITE_FACTOR_NOT_CONFIRMED"
    return {
        "group_id": "htr010b1d2-group:" + sha256("|".join(key).encode()).hexdigest(),
        "identity_key": key[0],
        "effective_date": key[1],
        "prior_isin": key[2] or None,
        "prior_series": key[3] or None,
        "prior_session": key[4] or None,
        "current_isin": key[5] or None,
        "current_series": key[6] or None,
        "current_session": key[7] or None,
        "case_ids": sorted(str(row.get("case_id") or "") for row in rows),
        "action_types": sorted(str(row.get("action_type") or "") for row in rows),
        "factor_count": len(rows),
        "constituent_factors": [value for value in factors],
        "diagnostic_composite_factor": composite,
        "raw_gap_atr": raw_gap,
        "composite_adjusted_gap_atr": composite_gap,
        "group_disposition": disposition,
        "official_factors_retained": True,
        "production_influence": False,
    }


def _repair_case(row: dict[str, Any], group: dict[str, Any]) -> dict[str, Any]:
    bridge_type = str(row.get("bridge_type") or "")
    bridge_class = str(row.get("bridge_classification") or "")
    raw_gap = _number(row.get("bridge_raw_gap_atr"))
    adjusted_gap = _number(row.get("bridge_adjusted_gap_atr"))
    factor_count = int(group.get("factor_count") or 0)
    group_state = str(group.get("group_disposition") or "")

    if factor_count > 1 and group_state == "COMPOSITE_FACTOR_CONFIRMED":
        disposition = "FACTOR_CONFIRMED_VIA_SAME_SESSION_COMPOSITE"
        proposed = "FACTOR_CONFIRMED_CORRECT_MULTIPLE_ACTIONS"
        confirmed = True
        repair = "VALIDATE_SAME_SESSION_FACTOR_GROUP_AS_COMPOSITE"
    elif factor_count > 1 and group_state == (
        "COMPOSITE_FACTOR_INSUFFICIENT_CANDLE_CONTEXT"
    ):
        disposition = "FACTOR_INSUFFICIENT_COMPOSITE_CANDLE_CONTEXT"
        proposed = "FACTOR_INSUFFICIENT_EVIDENCE"
        confirmed = False
        repair = "KEEP_QUARANTINED_REQUIRE_COMPOSITE_CANDLE_CONTEXT"
    elif bridge_type == "STABLE_SECURITY_SERIES" and _restores(adjusted_gap, raw_gap):
        disposition = "FACTOR_CONFIRMED_ON_STABLE_SECURITY_PAIR"
        proposed = "FACTOR_CONFIRMED_CORRECT_MARKET_GAP"
        confirmed = True
        repair = "USE_EXPLICIT_STABLE_SERIES_BOUNDARY_PAIR"
    elif (
        bridge_type == "STABLE_SECURITY_SERIES"
        and row.get("b1d_official_term_factor_matches") is True
        and (
            str(row.get("action_type") or "") in {"BONUS", "SPLIT", "FACE_VALUE_CHANGE"}
            or (
                str(row.get("action_type") or "") == "RIGHTS"
                and row.get("b1d_reference_price_certified") is True
            )
        )
    ):
        disposition = "FACTOR_CONFIRMED_BY_GOVERNED_OFFICIAL_TERMS"
        proposed = "FACTOR_CONFIRMED_CORRECT_MARKET_GAP"
        confirmed = True
        repair = "RETAIN_OFFICIAL_FACTOR_CLASSIFY_RESIDUAL_AS_MARKET_GAP"
    elif (
        bridge_type == "STABLE_SECURITY_SERIES"
        and raw_gap is not None
        and raw_gap <= 2.0
        and (adjusted_gap is None or adjusted_gap >= raw_gap)
    ):
        disposition = "RAW_CONTINUITY_ALREADY_PRESENT_FACTOR_NOT_VALIDATED"
        proposed = "FACTOR_INSUFFICIENT_EVIDENCE"
        confirmed = False
        repair = "REVIEW_EVENT_DATE_OR_ALREADY_ADJUSTED_SOURCE_NO_AUTO_INVERSION"
    elif bridge_type == "STABLE_SECURITY_SERIES" and (
        raw_gap is None or adjusted_gap is None
    ):
        disposition = "FACTOR_INSUFFICIENT_STABLE_PAIR_CONTEXT"
        proposed = "FACTOR_INSUFFICIENT_EVIDENCE"
        confirmed = False
        repair = "KEEP_QUARANTINED_REQUIRE_STABLE_PAIR_CANDLE_CONTEXT"
    elif bridge_type == "CROSS_ISIN" and _restores(adjusted_gap, raw_gap):
        disposition = "FACTOR_CONFIRMED_ON_UNCERTIFIED_CROSS_ISIN_BRIDGE"
        proposed = "FACTOR_CONFIRMED_CORRECT_MARKET_GAP"
        confirmed = True
        repair = "SEPARATE_FACTOR_CONFIRMATION_FROM_ISIN_BRIDGE_CERTIFICATION"
    elif bridge_type == "CROSS_SERIES" and _restores(adjusted_gap, raw_gap):
        disposition = "FACTOR_CONFIRMED_ON_UNCERTIFIED_CROSS_SERIES_BRIDGE"
        proposed = "FACTOR_CONFIRMED_CORRECT_MARKET_GAP"
        confirmed = True
        repair = "SEPARATE_FACTOR_CONFIRMATION_FROM_SERIES_BRIDGE_CERTIFICATION"
    elif raw_gap is None or adjusted_gap is None:
        disposition = "FACTOR_INSUFFICIENT_BRIDGE_CANDLE_CONTEXT"
        proposed = "FACTOR_INSUFFICIENT_EVIDENCE"
        confirmed = False
        repair = "KEEP_QUARANTINED_REQUIRE_BRIDGE_CANDLE_CONTEXT"
    else:
        disposition = "FACTOR_NOT_CONFIRMED_AFTER_BRIDGE_REPAIR"
        proposed = "IMPLEMENTATION_DEFECT"
        confirmed = False
        repair = "CONTINUE_TARGETED_FACTOR_FORENSICS"

    dependency = _bridge_dependency(bridge_type, bridge_class)
    bridge_certified = dependency in {
        "NONE_STABLE_SECURITY",
        "GOVERNED_CROSS_ISIN",
    }
    return {
        **row,
        "htr010b1d2_contract_version": HTR010B1D2_CONTRACT_VERSION,
        "same_session_group_id": group.get("group_id"),
        "same_session_factor_count": factor_count,
        "diagnostic_composite_factor": group.get("diagnostic_composite_factor"),
        "diagnostic_composite_gap_atr": group.get("composite_adjusted_gap_atr"),
        "corrected_disposition": disposition,
        "proposed_validation_outcome": proposed,
        "factor_quality_confirmed": confirmed,
        "bridge_dependency_state": dependency,
        "bridge_certified_for_replay": bridge_certified,
        "recommended_contract_repair": repair,
        "official_factor_retained": True,
        "market_derived_factor_autocorrection": False,
        "admitted_to_replay": False,
        "production_influence": False,
    }


def _bridge_dependency(bridge_type: str, bridge_class: str) -> str:
    if bridge_type == "STABLE_SECURITY_SERIES":
        return "NONE_STABLE_SECURITY"
    if bridge_class == "GOVERNED_CROSS_ISIN_BRIDGE_AVAILABLE":
        return "GOVERNED_CROSS_ISIN"
    if bridge_class == "IDENTITY_TRANSITION_NONCOMPARABLE":
        return "NONCOMPARABLE_IDENTITY_TRANSITION"
    if bridge_type == "CROSS_ISIN":
        return "UNCERTIFIED_CROSS_ISIN"
    if bridge_type == "CROSS_SERIES":
        return "UNCERTIFIED_CROSS_SERIES"
    return "UNKNOWN_BRIDGE_DEPENDENCY"


def _restores(candidate: float | None, raw_gap: float | None) -> bool:
    if candidate is None:
        return False
    return candidate <= 2.0 or (
        raw_gap is not None and candidate < raw_gap and candidate <= raw_gap * 0.5
    )


def _gap_atr(
    price: float | None,
    previous_close: float | None,
    atr: float | None,
    factor: float | None,
) -> float | None:
    if (
        price is None
        or previous_close is None
        or atr is None
        or atr <= 0
        or factor is None
        or factor <= 0
    ):
        return None
    reference = previous_close * factor
    return abs(price - reference) / (atr * factor)


def _product(values: tuple[float | None, ...]) -> float | None:
    valid = [value for value in values if value is not None and value > 0]
    if len(valid) <= 1 or len(valid) != len(values):
        return None
    result = 1.0
    for value in valid:
        result *= value
    return result


def _records(path: Path) -> tuple[dict[str, Any], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(
        isinstance(row, dict) for row in payload
    ):
        raise ValueError(f"expected JSON array of objects: {path}")
    return tuple(payload)


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _number(value: object) -> float | None:
    if value is None or not isinstance(value, (str, int, float)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _digest(report: dict[str, Any]) -> str:
    payload = dict(report)
    payload.pop("report_sha256", None)
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write_csv(path: Path, rows: tuple[dict[str, Any], ...]) -> None:
    fields = sorted({key for row in rows for key in row}) or ["value"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
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
        (
            "# HTR-010B1D2 Bridge-Aware Factor Validation Repair",
            "",
            f"- Cases audited: {report['case_count']}",
            f"- Same-session groups: {report['same_session_group_count']}",
            "- Composite groups confirmed: "
            f"{report['composite_confirmed_group_count']}",
            "- Corrected dispositions: "
            f"{json.dumps(report['disposition_counts'], sort_keys=True)}",
            "- Proposed validation outcomes: "
            f"{
                json.dumps(
                    report['proposed_validation_outcome_counts'],
                    sort_keys=True,
                )
            }",
            "- Bridge dependencies: "
            f"{json.dumps(report['bridge_dependency_counts'], sort_keys=True)}",
            "- Factor-quality confirmed cases: "
            f"{report['factor_confirmed_case_count']}",
            "- Replay-bridge uncertified cases: "
            f"{report['replay_bridge_uncertified_case_count']}",
            "- Cases that should remain implementation defects: "
            f"{report['implementation_defect_should_remain_count']}",
            f"- Report SHA-256: `{report['report_sha256']}`",
            "- Full benchmark replays: 0",
            "- Production influence: false",
            "",
            "Factor quality and bridge certification are separate decisions. "
            "Official factors remain immutable and no case is admitted to replay.",
            "",
        )
    )


__all__ = [
    "BridgeAwareFactorValidationRepairEngine",
    "HTR010B1D2_CONTRACT_VERSION",
]
