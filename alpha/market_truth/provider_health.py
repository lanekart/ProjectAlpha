from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alpha.market_truth.models import (
    ProviderDescriptor,
    ProviderHealth,
    ProviderHealthReport,
    ProviderHealthState,
    utc,
)

DEFAULT_PROVIDER_HEALTH_PATH = Path(".alpha/market_truth/provider_health.json")
PROVIDER_HEALTH_SCHEMA_VERSION = "market-truth-provider-health-v1"


class ProviderHealthMonitor:
    """Persist the latest sanitized health state for every provider."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PROVIDER_HEALTH_PATH

    def record(self, health: ProviderHealth) -> None:
        payload = self._read()
        rows = _rows(payload)
        rows[health.provider_id] = _health_dict(health)
        self._write(
            {"schema_version": PROVIDER_HEALTH_SCHEMA_VERSION, "providers": rows}
        )

    def report(
        self,
        descriptors: tuple[ProviderDescriptor, ...],
        *,
        generated_at: datetime | None = None,
    ) -> ProviderHealthReport:
        now = utc(generated_at or datetime.now(tz=UTC))
        rows = _rows(self._read())
        health = tuple(
            _health_from_dict(rows[item.provider_id])
            if item.provider_id in rows
            else ProviderHealth(
                provider_id=item.provider_id,
                state=(
                    ProviderHealthState.UNKNOWN
                    if item.configured
                    else ProviderHealthState.UNCONFIGURED
                ),
                checked_at=now,
                latency_ms=None,
                message=(
                    "Configured; no request has been observed."
                    if item.configured
                    else "Provider credentials or endpoint are not configured."
                ),
            )
            for item in descriptors
        )
        return ProviderHealthReport(generated_at=now, providers=health)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": PROVIDER_HEALTH_SCHEMA_VERSION,
                "providers": {},
            }
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("provider health registry must contain an object")
        if payload.get("schema_version") != PROVIDER_HEALTH_SCHEMA_VERSION:
            raise ValueError("unsupported provider health schema")
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            delete=False,
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, self.path)


def _rows(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = payload.get("providers", {})
    if not isinstance(raw, dict):
        raise ValueError("provider health rows must be an object")
    return {str(key): value for key, value in raw.items() if isinstance(value, dict)}


def _health_dict(health: ProviderHealth) -> dict[str, object]:
    return {
        "provider_id": health.provider_id,
        "state": health.state.value,
        "checked_at": health.checked_at.isoformat(),
        "latency_ms": health.latency_ms,
        "message": health.message,
        "consecutive_failures": health.consecutive_failures,
    }


def _health_from_dict(row: dict[str, Any]) -> ProviderHealth:
    return ProviderHealth(
        provider_id=str(row["provider_id"]),
        state=ProviderHealthState(str(row["state"])),
        checked_at=datetime.fromisoformat(str(row["checked_at"])),
        latency_ms=(None if row.get("latency_ms") is None else int(row["latency_ms"])),
        message=str(row["message"]),
        consecutive_failures=int(row.get("consecutive_failures", 0)),
    )


__all__ = [
    "DEFAULT_PROVIDER_HEALTH_PATH",
    "PROVIDER_HEALTH_SCHEMA_VERSION",
    "ProviderHealthMonitor",
]
