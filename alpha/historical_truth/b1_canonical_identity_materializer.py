"""Materialize HTR-009A identity intervals into the HTR-005 identity contract."""

from __future__ import annotations

import json
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

HTR010B1_IDENTITY_MATERIALIZER_VERSION = "HTR-010B1-IDENTITY-MATERIALIZER-v1.0.0"
_SUPPORTED_SERIES = {"EQ"}
_ALLOWED_ADMISSION_PREFIXES = (
    "GOVERNED_",
    "OBSERVED_DATES_ONLY_",
)


class B1CanonicalIdentityMaterializer:
    """Fail-closed adapter from HTR-009A identity rows to HTR-005 records."""

    def run(self, *, source_path: Path, output: Path) -> dict[str, Any]:
        rows = _records(source_path)
        identities: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []

        for row in rows:
            identity, reason = _materialize(row)
            if identity is None:
                rejected.append(
                    {
                        "identity_key": row.get("identity_key"),
                        "symbol": row.get("symbol"),
                        "series": row.get("series"),
                        "admission_status": row.get("admission_status"),
                        "reason": reason,
                    }
                )
            else:
                identities.append(identity)

        identities.sort(
            key=lambda row: (
                str(row["security_id"]),
                str(row.get("effective_from") or ""),
                str(row.get("effective_to") or ""),
                str(row["symbol"]),
            )
        )
        rejected.sort(
            key=lambda row: (
                str(row.get("identity_key") or ""),
                str(row.get("symbol") or ""),
            )
        )

        duplicate_keys = _duplicate_interval_keys(identities)
        if duplicate_keys:
            raise ValueError(
                "canonical identity materialization produced duplicate intervals: "
                + ",".join(duplicate_keys[:10])
            )

        output.mkdir(parents=True, exist_ok=True)
        identity_path = output / "htr010b1_canonical_identity_timeline.json"
        rejected_path = output / "htr010b1_rejected_identity_rows.json"
        identity_path.write_text(
            json.dumps(identities, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        rejected_path.write_text(
            json.dumps(rejected, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        series_counts = Counter(str(row.get("series") or "") for row in rows)
        rejection_counts = Counter(str(row.get("reason") or "") for row in rejected)
        report: dict[str, Any] = {
            "contract_version": HTR010B1_IDENTITY_MATERIALIZER_VERSION,
            "source_row_count": len(rows),
            "materialized_identity_count": len(identities),
            "rejected_identity_count": len(rejected),
            "source_series_counts": dict(sorted(series_counts.items())),
            "rejection_reason_counts": dict(sorted(rejection_counts.items())),
            "identity_path": str(identity_path),
            "rejected_path": str(rejected_path),
            "production_influence": False,
        }
        report["report_sha256"] = _digest(report)
        (output / "htr010b1_identity_materialization_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report


def _materialize(row: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    series = str(row.get("series") or "").upper()
    if series not in _SUPPORTED_SERIES:
        return None, "UNSUPPORTED_SERIES"

    confidence = str(row.get("confidence") or "").upper()
    if confidence != "HIGH":
        return None, "CONFIDENCE_NOT_HIGH"

    admission = str(row.get("admission_status") or "").upper()
    if not admission.startswith(_ALLOWED_ADMISSION_PREFIXES):
        return None, "UNSUPPORTED_ADMISSION_STATUS"

    required = ("identity_key", "symbol", "valid_from", "valid_to")
    missing = [key for key in required if not str(row.get(key) or "").strip()]
    if missing:
        return None, "MISSING_REQUIRED_FIELDS:" + ",".join(missing)

    source_id = str(row.get("source_id") or "").strip()
    identity_key = str(row["identity_key"]).strip()
    symbol = str(row["symbol"]).strip().upper()
    evidence_ids = [value for value in (source_id, identity_key) if value]
    return (
        {
            "security_id": identity_key,
            "symbol": symbol,
            "exchange": "NSE",
            "effective_from": str(row["valid_from"]),
            "effective_to": str(row["valid_to"]),
            "historical_symbols": [],
            "evidence_ids": evidence_ids,
            "recovery_version": HTR010B1_IDENTITY_MATERIALIZER_VERSION,
        },
        None,
    )


def _duplicate_interval_keys(rows: list[dict[str, Any]]) -> list[str]:
    counts = Counter(
        (
            str(row["security_id"]),
            str(row.get("effective_from") or ""),
            str(row.get("effective_to") or ""),
            str(row["symbol"]),
        )
        for row in rows
    )
    return ["|".join(key) for key, count in sorted(counts.items()) if count > 1]


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
                    "identity_intervals",
                    "identities",
                )
                if isinstance(payload.get(key), list)
            ),
            None,
        )
        payload = nested if nested is not None else [payload]
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise ValueError("HTR-009A identity artifact must contain record mappings")
    return tuple(dict(row) for row in payload)


def _digest(value: dict[str, Any]) -> str:
    payload = dict(value)
    payload.pop("report_sha256", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


__all__ = [
    "B1CanonicalIdentityMaterializer",
    "HTR010B1_IDENTITY_MATERIALIZER_VERSION",
]
