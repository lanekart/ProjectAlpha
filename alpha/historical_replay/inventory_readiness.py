"""Deterministic historical-truth inventory evidence for replay readiness."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from alpha.research_dataset_inventory import (
    DATASETS,
    DatasetInventoryRow,
    build_inventory,
)

HISTORICAL_TRUTH_INVENTORY_CONTRACT_VERSION = "HTR-006-inventory-v1.0.0"


@dataclass(frozen=True, slots=True)
class HistoricalTruthInventoryEvidence:
    """Immutable annual inventory proof used by executable replay readiness."""

    year: int
    period_end: date
    rows: tuple[DatasetInventoryRow, ...]
    contract_version: str = HISTORICAL_TRUTH_INVENTORY_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.year < 1900:
            raise ValueError("inventory year is invalid")
        if self.period_end.year != self.year:
            raise ValueError("inventory period_end must belong to its year")
        expected_keys = tuple(sorted(item.key for item in DATASETS))
        actual_keys = tuple(item.dataset_key for item in self.rows)
        if actual_keys != tuple(sorted(actual_keys)):
            raise ValueError("inventory rows must be sorted by dataset key")
        if len(actual_keys) != len(set(actual_keys)):
            raise ValueError("inventory rows contain duplicate dataset keys")
        if actual_keys != expected_keys:
            raise ValueError("inventory rows must contain every governed dataset")
        if self.contract_version != HISTORICAL_TRUTH_INVENTORY_CONTRACT_VERSION:
            raise ValueError("unsupported historical-truth inventory contract")

    @property
    def blocking_dataset_keys(self) -> tuple[str, ...]:
        """Return blocking datasets that are not certification ready."""

        return tuple(
            row.dataset_key
            for row in self.rows
            if row.blocking and not row.certification_ready
        )

    @property
    def required_unready_dataset_keys(self) -> tuple[str, ...]:
        """Return required datasets that are not certification ready."""

        return tuple(
            row.dataset_key
            for row in self.rows
            if row.required and not row.certification_ready
        )

    @property
    def inventory_sha256(self) -> str:
        """Return a deterministic digest over the complete annual inventory."""

        encoded = json.dumps(
            self.as_dict(include_digest=False),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def as_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        """Return a stable JSON-compatible annual inventory proof."""

        payload: dict[str, object] = {
            "year": self.year,
            "period_end": self.period_end.isoformat(),
            "rows": [asdict(row) for row in self.rows],
            "blocking_dataset_keys": list(self.blocking_dataset_keys),
            "required_unready_dataset_keys": list(
                self.required_unready_dataset_keys
            ),
            "contract_version": self.contract_version,
        }
        if include_digest:
            payload["inventory_sha256"] = self.inventory_sha256
        return payload


def build_historical_truth_inventory_evidence(
    rows: tuple[DatasetInventoryRow, ...],
    *,
    year: int,
    period_end: date,
) -> HistoricalTruthInventoryEvidence:
    """Build one complete, deterministically ordered annual inventory proof."""

    return HistoricalTruthInventoryEvidence(
        year=year,
        period_end=period_end,
        rows=tuple(sorted(rows, key=lambda item: item.dataset_key)),
    )


def build_historical_truth_inventory_evidence_for_range(
    *,
    database: Path,
    snapshots: Path | None,
    from_date: date,
    to_date: date,
) -> tuple[HistoricalTruthInventoryEvidence, ...]:
    """Build annual inventory proofs covering one requested replay range."""

    if to_date < from_date:
        raise ValueError("inventory range end cannot precede start")
    evidence: list[HistoricalTruthInventoryEvidence] = []
    for year in range(from_date.year, to_date.year + 1):
        period_end = min(to_date, date(year, 12, 31))
        rows = build_inventory(
            year=year,
            database=database,
            snapshots=snapshots,
            as_of=period_end,
        )
        evidence.append(
            build_historical_truth_inventory_evidence(
                rows,
                year=year,
                period_end=period_end,
            )
        )
    return tuple(evidence)


__all__ = [
    "HISTORICAL_TRUTH_INVENTORY_CONTRACT_VERSION",
    "HistoricalTruthInventoryEvidence",
    "build_historical_truth_inventory_evidence",
    "build_historical_truth_inventory_evidence_for_range",
]
