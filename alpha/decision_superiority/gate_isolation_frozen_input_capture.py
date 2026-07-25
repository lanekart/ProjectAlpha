"""Append-only forward capture for DSI-002A frozen candidate inputs."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenCandidateInputSnapshot,
    FrozenInputContractValidator,
)
from alpha.decision_superiority.gate_isolation_models import FrozenCandidateKey


@dataclass(frozen=True, slots=True)
class FrozenInputCaptureResult:
    """Result of one append-only frozen-input capture operation."""

    candidate: FrozenCandidateKey
    snapshot_sha256: str
    snapshot_path: Path
    index_path: Path
    replay_ready: bool
    production_influence: bool = False

    def __post_init__(self) -> None:
        if self.production_influence:
            raise ValueError("frozen input capture must remain diagnostic-only")
        if not self.snapshot_sha256.strip():
            raise ValueError("snapshot_sha256 cannot be empty")


class FrozenInputCaptureWriter:
    """Persist complete frozen-input snapshots without overwrite or mutation."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def capture(
        self,
        snapshot: FrozenCandidateInputSnapshot,
    ) -> FrozenInputCaptureResult:
        """Write one validated snapshot and append its immutable index row."""

        validation = FrozenInputContractValidator().validate(snapshot)
        if not validation.replay_ready:
            raise ValueError(
                "frozen input capture requires a replay-ready snapshot:"
                f"{validation.readiness.value}"
            )

        snapshot_dir = self._root / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        index_path = self._root / "dsi002_frozen_input_capture_index.csv"
        filename = _snapshot_filename(snapshot.candidate, snapshot.snapshot_sha256)
        snapshot_path = snapshot_dir / filename

        if snapshot_path.exists():
            raise FileExistsError(
                f"frozen input snapshot already exists:{snapshot_path}"
            )

        existing = _read_index(index_path)
        identity = _candidate_identity(snapshot.candidate)
        if any(row["candidate_identity"] == identity for row in existing):
            raise ValueError("candidate already has a frozen input capture")
        if any(row["snapshot_sha256"] == snapshot.snapshot_sha256 for row in existing):
            raise ValueError("snapshot hash already exists in capture index")

        payload = _snapshot_payload(snapshot)
        snapshot_path.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        _append_index(
            index_path,
            {
                "candidate_identity": identity,
                "price_view": snapshot.candidate.price_view,
                "observed_on": snapshot.candidate.observed_on,
                "symbol": snapshot.candidate.symbol,
                "input_fingerprint": snapshot.candidate.input_fingerprint,
                "snapshot_sha256": snapshot.snapshot_sha256,
                "snapshot_path": str(snapshot_path),
                "contract_version": snapshot.contract_version,
                "replay_ready": "true",
                "production_influence": "false",
            },
        )
        return FrozenInputCaptureResult(
            candidate=snapshot.candidate,
            snapshot_sha256=snapshot.snapshot_sha256,
            snapshot_path=snapshot_path,
            index_path=index_path,
            replay_ready=True,
        )


def _snapshot_payload(snapshot: FrozenCandidateInputSnapshot) -> dict[str, object]:
    return {
        "candidate": {
            "price_view": snapshot.candidate.price_view,
            "observed_on": snapshot.candidate.observed_on,
            "symbol": snapshot.candidate.symbol,
            "input_fingerprint": snapshot.candidate.input_fingerprint,
        },
        "contract_version": snapshot.contract_version,
        "snapshot_sha256": snapshot.snapshot_sha256,
        "sections": [
            {
                "section": item.section.value,
                "payload_json": item.payload_json,
                "payload_sha256": item.payload_sha256,
                "source_version": item.source_version,
                "observed_on": item.observed_on,
                "contains_post_observation_data": (item.contains_post_observation_data),
            }
            for item in snapshot.sections
        ],
        "production_influence": False,
    }


def _snapshot_filename(candidate: FrozenCandidateKey, sha256: str) -> str:
    safe_symbol = candidate.symbol.replace("/", "_")
    return (
        "__".join(
            (
                candidate.observed_on,
                candidate.price_view,
                safe_symbol,
                sha256,
            )
        )
        + ".json"
    )


def _candidate_identity(candidate: FrozenCandidateKey) -> str:
    return "|".join(
        (
            candidate.price_view,
            candidate.observed_on,
            candidate.symbol,
            candidate.input_fingerprint,
        )
    )


def _read_index(path: Path) -> tuple[dict[str, str], ...]:
    if not path.exists():
        return ()
    with path.open("r", encoding="utf-8", newline="") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


def _append_index(path: Path, row: dict[str, str]) -> None:
    fieldnames = tuple(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


__all__ = [
    "FrozenInputCaptureResult",
    "FrozenInputCaptureWriter",
]
