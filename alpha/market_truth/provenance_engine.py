from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from alpha.market_truth.models import (
    MarketTruthRequest,
    Provenance,
    ProviderAttempt,
    ProviderDataset,
    canonical_json,
    utc,
)


class MarketTruthProvenanceEngine:
    def build(
        self,
        *,
        request: MarketTruthRequest,
        dataset: ProviderDataset | None,
        attempts: tuple[ProviderAttempt, ...],
        generated_at: datetime,
    ) -> Provenance:
        timestamp = utc(generated_at)
        payload = {
            "request_id": request.request_id,
            "provider_id": "NO_DATA" if dataset is None else dataset.provider_id,
            "provider_checksum": None if dataset is None else dataset.checksum,
            "attempts": [
                {
                    "provider_id": item.provider_id,
                    "succeeded": item.succeeded,
                    "reason": item.reason,
                    "checksum": item.dataset_checksum,
                }
                for item in attempts
            ],
        }
        lineage = sha256(canonical_json(payload).encode()).hexdigest()
        return Provenance(
            provenance_id="mte-provenance-" + lineage[:24],
            request_id=request.request_id,
            source="NO_DATA" if dataset is None else dataset.source,
            provider_id="NO_DATA" if dataset is None else dataset.provider_id,
            source_reference=(
                "No provider supplied data"
                if dataset is None
                else dataset.source_reference
            ),
            provider_checksum=None if dataset is None else dataset.checksum,
            lineage_hash=lineage,
            attempts=attempts,
            generated_at=timestamp,
        )


__all__ = ["MarketTruthProvenanceEngine"]
