from __future__ import annotations

from hashlib import sha256

from alpha.market_truth.models import (
    MARKET_TRUTH_SCHEMA_VERSION,
    MarketTruthRequest,
    ProviderDataset,
)


class MarketTruthVersioning:
    """Create content-addressed dataset versions without mutable aliases."""

    def version(
        self,
        *,
        request: MarketTruthRequest,
        dataset: ProviderDataset | None,
    ) -> str:
        checksum = "NO_DATA" if dataset is None else dataset.checksum
        digest = sha256(
            f"{MARKET_TRUTH_SCHEMA_VERSION}|{request.request_id}|{checksum}".encode()
        ).hexdigest()[:20]
        return f"{MARKET_TRUTH_SCHEMA_VERSION}-{request.dataset.value.lower()}-{digest}"


__all__ = ["MarketTruthVersioning"]
