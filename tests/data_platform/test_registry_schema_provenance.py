from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from alpha.data_platform import (
    ConfidenceLevel,
    DatasetStatus,
    ProvenanceEngine,
    TruthClass,
    default_dataset_registry,
    default_schema_catalog,
)
from alpha.data_platform.models import (
    PlatformLayer,
    TransformationStep,
    ValidationStatus,
)


def test_default_registry_is_complete_and_unacquired() -> None:
    registry = default_dataset_registry()
    assert len(registry.records) == 20
    assert all(item.official for item in registry.records)
    assert all(not item.acquired for item in registry.records)
    assert all(item.status is DatasetStatus.EXPERIMENTAL for item in registry.records)
    assert registry.get("nse-historical-index-membership").entities
    assert registry.registry_hash == default_dataset_registry().registry_hash


def test_registry_acquisition_is_immutable() -> None:
    registry = default_dataset_registry()
    updated = registry.record_acquisition(
        "nse-equity-bhavcopy",
        version="2020-01",
        download_date=date(2026, 7, 19),
        checksum="a" * 64,
        coverage_start=date(2020, 1, 1),
        coverage_end=date(2020, 1, 31),
        confidence=ConfidenceLevel.HIGH,
    )
    assert not registry.get("nse-equity-bhavcopy").acquired
    assert updated.get("nse-equity-bhavcopy").acquired
    with pytest.raises(ValueError, match="already registered"):
        registry.register(registry.get("nse-equity-bhavcopy"))


def test_schema_validation_rejects_missing_unexpected_and_bad_types() -> None:
    catalog = default_schema_catalog()
    valid = catalog.validate(
        "adp-trading-calendar-v1",
        {
            "exchange": "NSE",
            "session_date": date(2024, 1, 2),
            "is_session": True,
            "session_type": "FULL",
        },
    )
    invalid = catalog.validate(
        "adp-trading-calendar-v1",
        {
            "exchange": "NSE",
            "session_date": "2024-01-02",
            "is_session": True,
            "extra": "bad",
        },
    )
    assert valid.valid
    assert not invalid.valid
    assert invalid.missing_fields == ("session_type",)
    assert invalid.unexpected_fields == ("extra",)
    assert invalid.invalid_types == ("session_date",)


def test_provenance_requires_complete_truth_and_is_stable() -> None:
    registry = default_dataset_registry()
    engine = ProvenanceEngine(registry)
    fields = {"close": Decimal("100"), "volume": Decimal("1000")}
    field_truth = {"close": TruthClass.OFFICIAL, "volume": TruthClass.OFFICIAL}
    raw_hash = "a" * 64
    normalized_hash = "b" * 64
    chain = (
        TransformationStep(
            step_id="normalize",
            layer=PlatformLayer.NORMALIZED,
            operation="decimal normalization",
            code_version="v1",
            input_checksum=raw_hash,
            output_checksum=normalized_hash,
        ),
        TransformationStep(
            step_id="truth",
            layer=PlatformLayer.HISTORICAL_TRUTH,
            operation="identity attachment",
            code_version="v1",
            input_checksum=normalized_hash,
            output_checksum="c" * 64,
        ),
    )
    kwargs = {
        "observation_key": "NSE:SEC-1:2020-01-02",
        "dataset_id": "nse-equity-bhavcopy",
        "fields": fields,
        "field_truth": field_truth,
        "transformation_chain": chain,
        "warehouse_version": "WAREHOUSE_V2_CANONICAL_DRAFT",
        "confidence": ConfidenceLevel.HIGH,
        "validation_status": ValidationStatus.VALIDATED,
        "last_verified": datetime(2026, 7, 19, tzinfo=UTC),
    }
    first = engine.create(**kwargs)
    second = engine.create(**kwargs)
    assert first == second
    assert first.field_truth["close"] is TruthClass.OFFICIAL
    with pytest.raises(ValueError, match="field truth must be complete"):
        engine.create(**{**kwargs, "field_truth": {"close": TruthClass.OFFICIAL}})


def test_truth_classification_is_exact() -> None:
    assert {item.value for item in TruthClass} == {
        "OFFICIAL",
        "OBSERVED",
        "RECONCILED",
        "DERIVED",
        "CURRENT_ONLY",
        "UNKNOWN",
    }
