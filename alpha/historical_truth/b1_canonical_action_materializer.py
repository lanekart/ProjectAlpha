"""Materialize certified HTR-009B rows into the HTR-005 action contract."""

from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any

from alpha.historical_replay.governed_artifacts import load_governed_replay_inputs

HTR010B1_ACTION_MATERIALIZER_VERSION = "HTR-010B1-ACTION-MATERIALIZER-v1.0.0"

_ACTION_TYPE_MAP = {
    "BONUS": "BONUS",
    "SPLIT": "SPLIT",
    "RIGHTS": "RIGHTS",
    "DIVIDEND": "CASH_DIVIDEND",
    "DEMERGER": "DEMERGER",
    "AMALGAMATION": "MERGER",
}


class B1CanonicalActionMaterializer:
    """Fail-closed adapter from HTR-009B analytical rows to HTR-005 events."""

    def run(
        self,
        *,
        source_path: Path,
        identity_path: Path,
        output: Path,
    ) -> dict[str, Any]:
        rows = _records(source_path)
        events: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []

        for row in rows:
            event, reason = _materialize(row)
            if event is None:
                rejected.append(
                    {
                        "action_id": row.get("action_id"),
                        "symbol": row.get("symbol"),
                        "action_type": row.get("action_type"),
                        "price_adjustment_required": bool(
                            row.get("price_adjustment_required")
                        ),
                        "reason": reason,
                    }
                )
            else:
                events.append(event)

        events.sort(
            key=lambda row: (
                str(row["security_id"]),
                str(row["effective_date"]),
                str(row["action_type"]),
                str(row["event_id"]),
            )
        )
        rejected.sort(key=lambda row: str(row.get("action_id") or ""))

        output.mkdir(parents=True, exist_ok=True)
        timeline_path = output / "htr010b1_canonical_action_timeline.json"
        rejected_path = output / "htr010b1_rejected_action_rows.json"
        timeline_path.write_text(
            json.dumps(events, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        rejected_path.write_text(
            json.dumps(rejected, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        loader_error: str | None = None
        identity_count = 0
        action_count = 0
        manifest_sha256: str | None = None
        try:
            inputs = load_governed_replay_inputs(
                identity_path=identity_path,
                corporate_action_path=timeline_path,
            )
            identity_count = len(inputs.identities.records)
            action_count = len(inputs.actions.events)
            manifest_sha256 = inputs.manifest.manifest_sha256
        except (FileNotFoundError, ValueError, TypeError, KeyError) as error:
            loader_error = str(error)

        unresolved_count = sum(event["status"] == "UNRESOLVED" for event in events)
        material_rejected_count = sum(
            bool(row["price_adjustment_required"]) for row in rejected
        )
        type_counts = Counter(str(event["action_type"]) for event in events)
        report: dict[str, Any] = {
            "contract_version": HTR010B1_ACTION_MATERIALIZER_VERSION,
            "source_row_count": len(rows),
            "materialized_event_count": len(events),
            "resolved_event_count": len(events) - unresolved_count,
            "unresolved_event_count": unresolved_count,
            "rejected_row_count": len(rejected),
            "material_rejected_row_count": material_rejected_count,
            "materialized_action_type_counts": dict(sorted(type_counts.items())),
            "identity_count": identity_count,
            "loader_action_count": action_count,
            "loader_manifest_sha256": manifest_sha256,
            "loader_error": loader_error,
            "htr005_contract_loadable": loader_error is None,
            "shadow_replay_safe": (
                loader_error is None
                and unresolved_count == 0
                and material_rejected_count == 0
            ),
            "timeline_path": str(timeline_path),
            "rejected_path": str(rejected_path),
            "production_influence": False,
        }
        report["report_sha256"] = _digest(report)
        (output / "htr010b1_action_materialization_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report


def _materialize(row: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    source_type = str(row.get("action_type") or "").upper()
    action_type = _ACTION_TYPE_MAP.get(source_type)
    if action_type is None:
        return None, "UNSUPPORTED_HTR005_ACTION_TYPE"

    required = ("action_id", "governed_identity_id", "symbol", "effective_date")
    missing = [key for key in required if not str(row.get(key) or "").strip()]
    if missing:
        return None, "MISSING_REQUIRED_FIELDS:" + ",".join(missing)

    admitted = str(row.get("admission_state") or "").upper() == "ADMITTED"
    high_confidence = str(row.get("confidence_state") or "").upper() == "HIGH"
    adjustment_required = bool(row.get("price_adjustment_required"))
    factor = _decimal(row.get("adjustment_factor"))
    factor_official = (
        str(row.get("adjustment_factor_state") or "").upper()
        == "DERIVED_FROM_OFFICIAL_TERMS"
    )

    status = "UNRESOLVED"
    price_factor: Decimal | None = None
    volume_factor: Decimal | None = None
    if admitted and high_confidence and not adjustment_required:
        status = "RESOLVED"
        price_factor = Decimal("1")
        volume_factor = Decimal("1")
    elif (
        admitted
        and high_confidence
        and adjustment_required
        and factor_official
        and factor is not None
        and factor > 0
    ):
        status = "RESOLVED"
        price_factor = factor
        volume_factor = Decimal("1") / factor

    effective = str(row["effective_date"])
    announced = str(row.get("announcement_date") or effective)
    event = {
        "event_id": str(row["action_id"]),
        "security_id": str(row["governed_identity_id"]),
        "symbol": str(row["symbol"]).upper(),
        "action_type": action_type,
        "effective_date": effective,
        "announced_at": announced,
        "price_factor": _json_decimal(price_factor),
        "volume_factor": _json_decimal(volume_factor),
        "old_symbol": None,
        "new_symbol": None,
        "cash_amount": _json_decimal(_decimal(row.get("cash_amount"))),
        "ratio_numerator": _json_decimal(_decimal(row.get("ratio_numerator"))),
        "ratio_denominator": _json_decimal(_decimal(row.get("ratio_denominator"))),
        "status": status,
        "confidence": "1" if high_confidence else "0.5",
        "evidence_ids": [
            value
            for value in (
                str(row.get("source_id") or "").strip(),
                str(row.get("action_id") or "").strip(),
            )
            if value
        ],
        "source": str(row.get("source_location") or row.get("source_id") or "HTR-009B"),
    }
    return event, None


def _records(path: Path) -> tuple[dict[str, Any], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        nested = next(
            (
                payload.get(key)
                for key in (
                    "records",
                    "data",
                    "canonical_preview",
                    "timeline",
                    "corporate_actions",
                    "actions",
                )
                if isinstance(payload.get(key), list)
            ),
            None,
        )
        payload = nested if nested is not None else [payload]
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise ValueError("HTR-009B action artifact must contain record mappings")
    return tuple(dict(row) for row in payload)


def _decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _json_decimal(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _digest(value: dict[str, Any]) -> str:
    payload = dict(value)
    payload.pop("report_sha256", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


__all__ = [
    "B1CanonicalActionMaterializer",
    "HTR010B1_ACTION_MATERIALIZER_VERSION",
]
