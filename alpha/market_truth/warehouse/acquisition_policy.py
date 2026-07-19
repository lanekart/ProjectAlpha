from __future__ import annotations

from datetime import date

from alpha.market_truth.warehouse.models import (
    AcquisitionMethod,
    AuthorisationStatus,
    SourceAuthorisation,
)
from alpha.market_truth.warehouse.source_authorisation import (
    SourceAuthorisationRegistry,
)


class AcquisitionNotAuthorisedError(PermissionError):
    pass


class AcquisitionPolicy:
    """Fail-closed policy shared by all automated and manual intake paths."""

    def __init__(self, registry: SourceAuthorisationRegistry) -> None:
        self.registry = registry

    def permit_automated(
        self, record_id: str, *, on_date: date | None = None
    ) -> SourceAuthorisation:
        record = self.registry.require(record_id)
        if record.acquisition_method is not AcquisitionMethod.AUTOMATED:
            self._deny(record, "record does not permit automated acquisition")
        if record.status is not AuthorisationStatus.AUTHORISED:
            self._deny(record, f"status is {record.status.value}")
        self._require_common_permissions(record, on_date=on_date)
        return record

    def permit_manual(
        self,
        record_id: str,
        *,
        lawfully_obtained: bool,
        on_date: date | None = None,
    ) -> SourceAuthorisation:
        record = self.registry.require(record_id)
        if not lawfully_obtained:
            self._deny(record, "lawful-source attestation was not supplied")
        if record.acquisition_method is not AcquisitionMethod.MANUAL_IMPORT:
            self._deny(record, "record does not permit manual import")
        if record.status not in {
            AuthorisationStatus.AUTHORISED,
            AuthorisationStatus.MANUAL_IMPORT_ONLY,
        }:
            self._deny(record, f"status is {record.status.value}")
        self._require_common_permissions(record, on_date=on_date)
        return record

    def _require_common_permissions(
        self, record: SourceAuthorisation, *, on_date: date | None
    ) -> None:
        today = on_date or date.today()
        if today < record.effective_date:
            self._deny(record, "authorisation is not yet effective")
        if record.expiry_date is not None and today > record.expiry_date:
            self._deny(record, "authorisation has expired")
        if not record.internal_storage_permitted:
            self._deny(record, "internal storage is not permitted")
        if not record.internal_research_permitted:
            self._deny(record, "internal research is not permitted")
        if not record.retention_permitted:
            self._deny(record, "retention is not permitted")

    @staticmethod
    def _deny(record: SourceAuthorisation, reason: str) -> None:
        raise AcquisitionNotAuthorisedError(
            f"Source {record.record_id} is not authorised: {reason}."
        )


__all__ = ["AcquisitionNotAuthorisedError", "AcquisitionPolicy"]
