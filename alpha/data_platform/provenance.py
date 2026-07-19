from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from alpha.data_platform.dataset_registry import DatasetRegistry
from alpha.data_platform.models import (
    ConfidenceLevel,
    ObservationProvenance,
    Scalar,
    TransformationStep,
    TruthClass,
    ValidationStatus,
    stable_hash,
)


class ProvenanceEngine:
    """Build complete field-level lineage without upgrading truth implicitly."""

    def __init__(self, registry: DatasetRegistry) -> None:
        self._registry = registry

    def create(
        self,
        *,
        observation_key: str,
        dataset_id: str,
        fields: Mapping[str, Scalar],
        field_truth: Mapping[str, TruthClass],
        transformation_chain: tuple[TransformationStep, ...],
        warehouse_version: str,
        confidence: ConfidenceLevel,
        validation_status: ValidationStatus,
        last_verified: datetime | None,
    ) -> ObservationProvenance:
        dataset = self._registry.get(dataset_id)
        if set(fields) != set(field_truth):
            missing = sorted(set(fields) - set(field_truth))
            extra = sorted(set(field_truth) - set(fields))
            raise ValueError(
                f"ADP field truth must be complete; missing={missing}; extra={extra}"
            )
        self.assert_chain(transformation_chain)
        checksum = stable_hash(dict(sorted(fields.items())))
        payload = {
            "observation_key": observation_key,
            "dataset_id": dataset_id,
            "source": dataset.source,
            "transformation_chain": transformation_chain,
            "warehouse_version": warehouse_version,
            "confidence": confidence.value,
            "validation_status": validation_status.value,
            "field_truth": {
                key: value.value for key, value in sorted(field_truth.items())
            },
            "last_verified": last_verified,
            "checksum": checksum,
        }
        return ObservationProvenance(
            provenance_id="adp-prov-" + stable_hash(payload)[:24],
            observation_key=observation_key,
            dataset_id=dataset_id,
            source=dataset.source,
            transformation_chain=transformation_chain,
            warehouse_version=warehouse_version,
            confidence=confidence,
            validation_status=validation_status,
            field_truth=field_truth,
            last_verified=last_verified,
            checksum=checksum,
        )

    @staticmethod
    def assert_chain(chain: tuple[TransformationStep, ...]) -> None:
        for previous, current in zip(chain, chain[1:], strict=False):
            if previous.output_checksum != current.input_checksum:
                raise ValueError("ADP transformation chain checksum is discontinuous")


__all__ = ["ProvenanceEngine"]
