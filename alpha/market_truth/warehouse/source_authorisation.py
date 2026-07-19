from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from alpha.market_truth.warehouse.models import (
    AcquisitionMethod,
    AuthorisationStatus,
    SourceAuthorisation,
    WarehouseDataset,
)


class SourceAuthorisationRegistry:
    """Permanent, deterministic record of what Alpha may lawfully acquire."""

    def __init__(
        self,
        records: tuple[SourceAuthorisation, ...] = (),
        *,
        path: Path | None = None,
    ) -> None:
        self.path = path
        self._records: dict[str, SourceAuthorisation] = {}
        if path is not None and path.exists():
            for record in _load(path):
                self.register(record)
        for record in records:
            self.register(record)

    def register(self, record: SourceAuthorisation) -> bool:
        existing = self._records.get(record.record_id)
        if existing is not None:
            if existing != record:
                raise ValueError(
                    f"authorisation id {record.record_id} has conflicting metadata"
                )
            return False
        self._records[record.record_id] = record
        self._persist()
        return True

    def require(self, record_id: str) -> SourceAuthorisation:
        try:
            return self._records[record_id]
        except KeyError as exc:
            raise KeyError(f"unknown source authorisation: {record_id}") from exc

    def records(self) -> tuple[SourceAuthorisation, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [_as_dict(record) for record in self.records()]
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        temporary.replace(self.path)


def default_source_authorisations(
    *, path: Path | None = None
) -> SourceAuthorisationRegistry:
    """Conservative defaults: user files only, no assumed archive licence."""

    effective = date(2016, 1, 1)
    records: list[SourceAuthorisation] = []
    for provider in ("NSE", "BSE"):
        for dataset in WarehouseDataset:
            records.append(
                SourceAuthorisation(
                    record_id=f"{provider}_{dataset.value}_MANUAL_V1",
                    provider=provider,
                    dataset=dataset,
                    acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
                    authorisation_basis=(
                        "User attestation that the imported file was lawfully obtained "
                        "and may be retained for internal research."
                    ),
                    internal_storage_permitted=True,
                    internal_research_permitted=True,
                    redistribution_permitted=False,
                    retention_permitted=True,
                    effective_date=effective,
                    expiry_date=None,
                    evidence_reference="USER_LAWFUL_SOURCE_ATTESTATION_REQUIRED",
                    status=AuthorisationStatus.MANUAL_IMPORT_ONLY,
                )
            )
            records.append(
                SourceAuthorisation(
                    record_id=f"{provider}_{dataset.value}_AUTOMATED_V1",
                    provider=provider,
                    dataset=dataset,
                    acquisition_method=AcquisitionMethod.AUTOMATED,
                    authorisation_basis=(
                        "No automated warehouse acquisition right has been recorded."
                    ),
                    internal_storage_permitted=False,
                    internal_research_permitted=False,
                    redistribution_permitted=False,
                    retention_permitted=False,
                    effective_date=effective,
                    expiry_date=None,
                    evidence_reference="LICENCE_OR_WRITTEN_PERMISSION_REQUIRED",
                    status=AuthorisationStatus.LICENCE_REQUIRED,
                )
            )
    return SourceAuthorisationRegistry(tuple(records), path=path)


def _as_dict(record: SourceAuthorisation) -> dict[str, object]:
    payload = asdict(record)
    payload["dataset"] = record.dataset.value
    payload["acquisition_method"] = record.acquisition_method.value
    payload["status"] = record.status.value
    payload["effective_date"] = record.effective_date.isoformat()
    payload["expiry_date"] = (
        None if record.expiry_date is None else record.expiry_date.isoformat()
    )
    return payload


def _load(path: Path) -> tuple[SourceAuthorisation, ...]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise ValueError("source authorisation registry must contain a JSON list")
    return tuple(
        SourceAuthorisation(
            record_id=str(item["record_id"]),
            provider=str(item["provider"]),
            dataset=WarehouseDataset(str(item["dataset"])),
            acquisition_method=AcquisitionMethod(str(item["acquisition_method"])),
            authorisation_basis=str(item["authorisation_basis"]),
            internal_storage_permitted=bool(item["internal_storage_permitted"]),
            internal_research_permitted=bool(item["internal_research_permitted"]),
            redistribution_permitted=bool(item["redistribution_permitted"]),
            retention_permitted=bool(item["retention_permitted"]),
            effective_date=date.fromisoformat(str(item["effective_date"])),
            expiry_date=(
                None
                if item.get("expiry_date") is None
                else date.fromisoformat(str(item["expiry_date"]))
            ),
            evidence_reference=str(item["evidence_reference"]),
            status=AuthorisationStatus(str(item["status"])),
        )
        for item in payload
        if isinstance(item, dict)
    )


__all__ = ["SourceAuthorisationRegistry", "default_source_authorisations"]
