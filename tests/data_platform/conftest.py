from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from alpha.data_platform.models import CanonicalObservation


@pytest.fixture
def canonical_observation() -> CanonicalObservation:
    return CanonicalObservation(
        observation_id="obs-1",
        dataset_id="nse-equity-bhavcopy",
        observation_key="NSE:SEC-1:2020-01-02",
        source="NSE",
        observed_on=date(2020, 1, 2),
        effective_from=date(2020, 1, 2),
        effective_to=None,
        known_at=datetime(2020, 1, 2, 18, tzinfo=UTC),
        fields={
            "security_id": "SEC-1",
            "symbol_as_traded": "AAA",
            "open": Decimal("99"),
            "high": Decimal("102"),
            "low": Decimal("98"),
            "close": Decimal("100"),
            "volume": Decimal("1000"),
        },
        provenance_id="prov-1",
        warehouse_version="WAREHOUSE_V2_CANONICAL_DRAFT",
    )
