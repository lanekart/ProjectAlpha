"""Immutable proofs and exports for governed replay consumption."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

CONSUMER_CONTRACT_VERSION = "HTR-004-consumer-v1.0.0"


@dataclass(frozen=True, slots=True)
class CanonicalReplayConsumerAttestation:
    """Proof that one consumer frame satisfied the replay contract."""

    trade_date: date
    as_of: date
    row_count: int
    security_ids: tuple[str, ...]
    canonical_symbols: tuple[str, ...]
    canonical_snapshot_sha256: str
    canonical_frame_sha256: str
    recovery_versions: tuple[str, ...]
    applied_event_ids: tuple[str, ...]
    contract_version: str = CONSUMER_CONTRACT_VERSION
    canonical_replay_enforced: bool = True

    def __post_init__(self) -> None:
        if self.as_of < self.trade_date:
            raise ValueError("attestation as_of cannot precede trade_date")
        if self.row_count <= 0:
            raise ValueError("attestation row_count must be positive")
        if self.row_count != len(self.security_ids):
            raise ValueError("attestation row_count must match security_ids")
        if self.row_count != len(self.canonical_symbols):
            raise ValueError("attestation row_count must match canonical_symbols")
        validate_sha256(self.canonical_snapshot_sha256, "canonical snapshot")
        validate_sha256(self.canonical_frame_sha256, "canonical frame")
        if not self.recovery_versions:
            raise ValueError("attestation requires a recovery version")
        if self.contract_version != CONSUMER_CONTRACT_VERSION:
            raise ValueError("unsupported canonical replay consumer contract")
        if not self.canonical_replay_enforced:
            raise ValueError("canonical replay attestation must be enforced")

    @property
    def attestation_sha256(self) -> str:
        """Return a deterministic digest over the attestation payload."""

        payload = attestation_payload(self, include_digest=False)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def export_consumer_attestations(
    attestations: Iterable[CanonicalReplayConsumerAttestation],
    output: Path,
) -> tuple[Path, ...]:
    """Export deterministic JSON, CSV, and Markdown consumer proofs."""

    ordered = tuple(
        sorted(
            attestations,
            key=lambda item: (
                item.trade_date,
                item.as_of,
                item.canonical_frame_sha256,
            ),
        )
    )
    if not ordered:
        raise ValueError("at least one canonical replay attestation is required")
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "canonical_replay_attestations.json"
    csv_path = output / "canonical_replay_attestations.csv"
    report_path = output / "canonical_replay_attestations.md"
    payload = [attestation_payload(item, include_digest=True) for item in ordered]
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_csv(csv_path, payload)
    report_path.write_text(_render(ordered), encoding="utf-8")
    return json_path, csv_path, report_path


def attestation_payload(
    attestation: CanonicalReplayConsumerAttestation,
    *,
    include_digest: bool,
) -> dict[str, object]:
    payload = asdict(attestation)
    payload["trade_date"] = attestation.trade_date.isoformat()
    payload["as_of"] = attestation.as_of.isoformat()
    payload["security_ids"] = list(attestation.security_ids)
    payload["canonical_symbols"] = list(attestation.canonical_symbols)
    payload["recovery_versions"] = list(attestation.recovery_versions)
    payload["applied_event_ids"] = list(attestation.applied_event_ids)
    if include_digest:
        payload["attestation_sha256"] = attestation.attestation_sha256
    return payload


def validate_sha256(value: str, label: str) -> None:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{label} SHA-256 is invalid")


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, sort_keys=True)
                    if isinstance(value, list)
                    else value
                    for key, value in row.items()
                }
            )


def _render(attestations: Sequence[CanonicalReplayConsumerAttestation]) -> str:
    lines = [
        "# Canonical Replay Consumer Attestations",
        "",
        f"- Attestations: `{len(attestations)}`",
        f"- Rows Consumed: `{sum(item.row_count for item in attestations)}`",
        "- Canonical Replay Enforced: `True`",
        f"- Contract Version: `{CONSUMER_CONTRACT_VERSION}`",
        "",
        "## Snapshots",
        "",
    ]
    for item in attestations:
        lines.append(
            "- "
            f"`{item.trade_date.isoformat()}`: "
            f"rows={item.row_count}, "
            f"snapshot={item.canonical_snapshot_sha256}, "
            f"frame={item.canonical_frame_sha256}, "
            f"attestation={item.attestation_sha256}"
        )
    return "\n".join(lines) + "\n"
