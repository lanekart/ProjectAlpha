"""Window-scoped governed action quarantine for HTR-010B1H."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

HTR010B1H_CONTRACT_VERSION = "HTR-010B1H-v1.0.0"

_ADMITTED = "SHADOW_REPLAY_ADMITTED"
_UNRESOLVED_RIGHTS = "UNRESOLVED_RIGHTS_QUARANTINED"
_UNRESOLVED_DIVIDEND = "UNRESOLVED_DIVIDEND_QUARANTINED"
_UNRESOLVED_ACTION = "UNRESOLVED_MATERIAL_ACTION_QUARANTINED"
_UNSUPPORTED_ACTION = "UNSUPPORTED_MATERIAL_ACTION_QUARANTINED"
_BRIDGE_QUARANTINE = "UNCERTIFIED_IDENTITY_BRIDGE_QUARANTINED"
_INSUFFICIENT_LOOKBACK = "INSUFFICIENT_LOOKBACK_QUARANTINED"


class B1WindowActionAdmissionEngine:
    """Build one immutable universe contract for both shadow replay arms."""

    def run(
        self,
        *,
        identities_path: Path,
        actions_path: Path,
        rejected_actions_path: Path,
        replay_start: date,
        replay_end: date,
        warmup_calendar_days: int,
        outcome_calendar_days: int,
        output: Path,
        bridge_exclusions_path: Path | None = None,
    ) -> dict[str, Any]:
        if replay_end < replay_start:
            raise ValueError("replay_end cannot precede replay_start")
        if warmup_calendar_days < 0 or outcome_calendar_days < 0:
            raise ValueError("dependency windows cannot be negative")

        dependency_start = replay_start - timedelta(days=warmup_calendar_days)
        dependency_end = replay_end + timedelta(days=outcome_calendar_days)
        identities = _records(identities_path)
        actions = _records(actions_path, allow_empty=True)
        rejected_actions = _records(rejected_actions_path, allow_empty=True)
        bridge_exclusions = (
            _records(bridge_exclusions_path, allow_empty=True)
            if bridge_exclusions_path is not None
            else ()
        )

        identity_by_id = _identity_index(identities)
        action_reasons = _action_quarantine_reasons(
            actions,
            rejected_actions,
            dependency_start=dependency_start,
            dependency_end=dependency_end,
        )
        bridge_reasons = _bridge_quarantine_reasons(bridge_exclusions)

        admissions: list[dict[str, Any]] = []
        exclusions: list[dict[str, Any]] = []
        admitted_ids: list[str] = []

        for security_id, identity_rows in sorted(identity_by_id.items()):
            overlapping = tuple(
                row
                for row in identity_rows
                if _overlaps(row, dependency_start, dependency_end)
            )
            if not overlapping:
                continue

            reasons = [
                *action_reasons.get(security_id, ()),
                *bridge_reasons.get(security_id, ()),
            ]
            if not _covers_dependency_start(overlapping, dependency_start):
                reasons.append(
                    {
                        "reason": _INSUFFICIENT_LOOKBACK,
                        "action_id": None,
                        "action_type": None,
                        "effective_date": None,
                        "detail": "identity interval does not cover dependency start",
                    }
                )

            symbol = str(overlapping[-1].get("symbol") or "")
            state = _ADMITTED if not reasons else str(reasons[0]["reason"])
            row = {
                "security_id": security_id,
                "symbol": symbol,
                "admission_state": state,
                "dependency_start": dependency_start.isoformat(),
                "dependency_end": dependency_end.isoformat(),
                "identity_interval_count": len(overlapping),
                "quarantine_reason_count": len(reasons),
                "quarantine_reasons": reasons,
                "raw_admitted": not reasons,
                "adjusted_admitted": not reasons,
                "production_influence": False,
            }
            admissions.append(row)
            if reasons:
                exclusions.append(row)
            else:
                admitted_ids.append(security_id)

        admissions.sort(key=lambda row: str(row["security_id"]))
        exclusions.sort(key=lambda row: str(row["security_id"]))
        admitted_ids.sort()
        raw_universe = list(admitted_ids)
        adjusted_universe = list(admitted_ids)
        universe_difference = sorted(set(raw_universe) ^ set(adjusted_universe))
        admitted_unresolved = sum(
            any(
                str(reason.get("reason") or "").startswith("UNRESOLVED_")
                for reason in row["quarantine_reasons"]
            )
            and row["raw_admitted"]
            for row in admissions
        )
        contradictions: list[str] = []
        if universe_difference:
            contradictions.append("RAW_ADJUSTED_UNIVERSE_MISMATCH")
        if admitted_unresolved:
            contradictions.append("ADMITTED_UNRESOLVED_ACTION_DEPENDENCY")
        if len(admissions) != len(admitted_ids) + len(exclusions):
            contradictions.append("ADMISSION_POPULATION_RECONCILIATION_FAILED")

        state_counts = Counter(str(row["admission_state"]) for row in admissions)
        contract = {
            "contract_version": HTR010B1H_CONTRACT_VERSION,
            "replay_start": replay_start.isoformat(),
            "replay_end": replay_end.isoformat(),
            "warmup_calendar_days": warmup_calendar_days,
            "outcome_calendar_days": outcome_calendar_days,
            "dependency_start": dependency_start.isoformat(),
            "dependency_end": dependency_end.isoformat(),
            "identity_population_count": len(admissions),
            "admitted_identity_count": len(admitted_ids),
            "excluded_identity_count": len(exclusions),
            "admission_state_counts": dict(sorted(state_counts.items())),
            "admitted_unresolved_action_count": admitted_unresolved,
            "raw_adjusted_universe_difference_count": len(universe_difference),
            "raw_adjusted_session_difference_count": 0,
            "contract_contradiction_count": len(contradictions),
            "contract_contradictions": contradictions,
            "implementation_defect_count": 0,
            "shadow_replay_ready": (
                bool(admitted_ids)
                and admitted_unresolved == 0
                and not universe_difference
                and not contradictions
            ),
            "raw_universe_sha256": _digest(raw_universe),
            "adjusted_universe_sha256": _digest(adjusted_universe),
            "production_influence": False,
        }
        contract["report_sha256"] = _digest(contract)

        output.mkdir(parents=True, exist_ok=True)
        paths = {
            "audit": output / "htr010b1h_action_dependency_audit.json",
            "admission": output / "htr010b1h_identity_admission.json",
            "exclusions": output / "htr010b1h_governed_exclusions.json",
            "raw": output / "htr010b1h_raw_universe.json",
            "adjusted": output / "htr010b1h_adjusted_universe.json",
            "contract": output / "htr010b1h_replay_contract.json",
            "markdown": output / "htr010b1h_executive_report.md",
        }
        audit = {
            "dependency_start": dependency_start.isoformat(),
            "dependency_end": dependency_end.isoformat(),
            "action_row_count": len(actions),
            "rejected_action_row_count": len(rejected_actions),
            "quarantined_security_count": len(action_reasons),
            "bridge_quarantined_security_count": len(bridge_reasons),
            "production_influence": False,
        }
        _write_json(paths["audit"], audit)
        _write_json(paths["admission"], admissions)
        _write_json(paths["exclusions"], exclusions)
        _write_json(paths["raw"], raw_universe)
        _write_json(paths["adjusted"], adjusted_universe)
        _write_json(paths["contract"], contract)
        paths["markdown"].write_text(_markdown(contract), encoding="utf-8")
        return contract


def _action_quarantine_reasons(
    actions: tuple[dict[str, Any], ...],
    rejected: tuple[dict[str, Any], ...],
    *,
    dependency_start: date,
    dependency_end: date,
) -> dict[str, tuple[dict[str, Any], ...]]:
    reasons: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in actions:
        effective = _optional_date(row.get("effective_date"))
        if effective is None or effective > dependency_end:
            continue
        if str(row.get("status") or "").upper() != "UNRESOLVED":
            continue
        security_id = str(row.get("security_id") or "").strip()
        if not security_id:
            continue
        action_type = str(row.get("action_type") or "").upper()
        reason = (
            _UNRESOLVED_RIGHTS
            if action_type == "RIGHTS"
            else (
                _UNRESOLVED_DIVIDEND
                if action_type == "CASH_DIVIDEND"
                else _UNRESOLVED_ACTION
            )
        )
        reasons[security_id].append(
            {
                "reason": reason,
                "action_id": row.get("event_id"),
                "action_type": action_type,
                "effective_date": effective.isoformat(),
                "detail": "unresolved action can contaminate dependency window",
            }
        )

    for row in rejected:
        if not bool(row.get("price_adjustment_required")):
            continue
        security_id = str(
            row.get("security_id")
            or row.get("governed_identity_id")
            or row.get("identity_key")
            or ""
        ).strip()
        if not security_id:
            symbol = str(row.get("symbol") or "").strip().upper()
            security_id = f"symbol:{symbol}" if symbol else ""
        if not security_id:
            continue
        reasons[security_id].append(
            {
                "reason": _UNSUPPORTED_ACTION,
                "action_id": row.get("action_id"),
                "action_type": row.get("action_type"),
                "effective_date": row.get("effective_date"),
                "detail": row.get("reason"),
            }
        )
    return {
        key: tuple(sorted(value, key=lambda row: str(row.get("action_id") or "")))
        for key, value in sorted(reasons.items())
    }


def _bridge_quarantine_reasons(
    rows: tuple[dict[str, Any], ...],
) -> dict[str, tuple[dict[str, Any], ...]]:
    reasons: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        security_id = str(
            row.get("security_id")
            or row.get("post_identity")
            or row.get("post_isin")
            or ""
        ).strip()
        if not security_id:
            continue
        if security_id.startswith("INE"):
            security_id = f"nse:isin:{security_id}"
        reasons[security_id].append(
            {
                "reason": _BRIDGE_QUARANTINE,
                "action_id": row.get("bridge_case_id"),
                "action_type": "IDENTITY_BRIDGE",
                "effective_date": row.get("effective_from"),
                "detail": (
                    row.get("continuity_decision")
                    or row.get("quarantine_reason")
                ),
            }
        )
    return {key: tuple(value) for key, value in sorted(reasons.items())}


def _identity_index(
    rows: tuple[dict[str, Any], ...],
) -> dict[str, tuple[dict[str, Any], ...]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        security_id = str(row.get("security_id") or "").strip()
        if not security_id:
            raise ValueError("canonical identity row is missing security_id")
        grouped[security_id].append(row)
    return {
        key: tuple(
            sorted(
                value,
                key=lambda row: (
                    str(row.get("effective_from") or ""),
                    str(row.get("effective_to") or ""),
                ),
            )
        )
        for key, value in sorted(grouped.items())
    }


def _overlaps(row: dict[str, Any], start: date, end: date) -> bool:
    row_start = _optional_date(row.get("effective_from")) or date.min
    row_end = _optional_date(row.get("effective_to")) or date.max
    return row_start <= end and row_end >= start


def _covers_dependency_start(rows: tuple[dict[str, Any], ...], start: date) -> bool:
    return any(
        (_optional_date(row.get("effective_from")) or date.min) <= start
        <= (_optional_date(row.get("effective_to")) or date.max)
        for row in rows
    )


def _records(
    path: Path | None,
    *,
    allow_empty: bool = False,
) -> tuple[dict[str, Any], ...]:
    if path is None or not path.exists() or not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        nested = next(
            (
                payload.get(key)
                for key in ("records", "data", "timeline", "rows")
                if isinstance(payload.get(key), list)
            ),
            None,
        )
        payload = nested if nested is not None else [payload]
    if not isinstance(payload, list) or not all(
        isinstance(row, dict) for row in payload
    ):
        raise ValueError(f"artifact must contain record mappings: {path}")
    if not payload and not allow_empty:
        raise ValueError(f"artifact contains no records: {path}")
    return tuple(dict(row) for row in payload)


def _optional_date(value: object) -> date | None:
    text = str(value or "").strip()
    return date.fromisoformat(text) if text else None


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _markdown(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# HTR-010B1H Window-Scoped Action Admission",
            "",
            (
                f"- Dependency window: `{report['dependency_start']}` "
                f"to `{report['dependency_end']}`"
            ),
            f"- Admitted identities: `{report['admitted_identity_count']}`",
            f"- Excluded identities: `{report['excluded_identity_count']}`",
            f"- Shadow replay ready: `{report['shadow_replay_ready']}`",
            f"- Report SHA-256: `{report['report_sha256']}`",
            "- PRODUCTION_INFLUENCE=false",
            "",
        ]
    )


__all__ = ["B1WindowActionAdmissionEngine", "HTR010B1H_CONTRACT_VERSION"]
