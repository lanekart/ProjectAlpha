from __future__ import annotations

from dataclasses import dataclass

from alpha.data_platform.dataset_registry import (
    DatasetRegistry,
    default_dataset_registry,
)
from alpha.data_platform.models import (
    MANIFEST_SCHEMA_VERSION,
    PLATFORM_VERSION,
    ADPManifest,
    LayerContract,
    PlatformLayer,
    stable_hash,
)
from alpha.data_platform.schema_catalog import SchemaCatalog, default_schema_catalog
from alpha.data_platform.versioning import (
    WarehouseVersionRegistry,
    default_warehouse_versions,
)


@dataclass(frozen=True, slots=True)
class AlphaDataPlatform:
    registry: DatasetRegistry
    schemas: SchemaCatalog
    warehouse_versions: WarehouseVersionRegistry
    layers: tuple[LayerContract, ...]
    manifest: ADPManifest


def build_default_platform() -> AlphaDataPlatform:
    registry = default_dataset_registry()
    schemas = default_schema_catalog()
    versions = default_warehouse_versions()
    layers = _layer_contracts()
    known_schemas = {item.schema_version for item in schemas.schemas}
    referenced = {item.schema_version for item in registry.records}
    if not referenced.issubset(known_schemas):
        raise ValueError("ADP registry references schemas outside the catalog")
    manifest = ADPManifest(
        platform_version=PLATFORM_VERSION,
        manifest_schema_version=MANIFEST_SCHEMA_VERSION,
        registry_hash=registry.registry_hash,
        schema_catalog_hash=schemas.catalog_hash,
        warehouse_lineage_hash=versions.lineage_hash,
        layer_contract_hash=stable_hash(layers),
        dataset_count=len(registry.records),
        schema_count=len(schemas.schemas),
        warehouse_release_count=len(versions.releases),
        downloaded_files=0,
        migrated_warehouse_v1=False,
        replay_changed=False,
    )
    return AlphaDataPlatform(
        registry=registry,
        schemas=schemas,
        warehouse_versions=versions,
        layers=layers,
        manifest=manifest,
    )


def _layer_contracts() -> tuple[LayerContract, ...]:
    return (
        LayerContract(
            layer=PlatformLayer.RAW,
            mutable=False,
            business_logic_allowed=False,
            derived_indicators_allowed=False,
            regenerative=False,
            purpose="Immutable source bytes and original source metadata.",
        ),
        LayerContract(
            layer=PlatformLayer.NORMALIZED,
            mutable=False,
            business_logic_allowed=False,
            derived_indicators_allowed=False,
            regenerative=True,
            purpose="Lossless canonical interchange and type normalization.",
        ),
        LayerContract(
            layer=PlatformLayer.HISTORICAL_TRUTH,
            mutable=False,
            business_logic_allowed=True,
            derived_indicators_allowed=False,
            regenerative=True,
            purpose="Identity, corporate actions, validity, and reconciliation.",
        ),
        LayerContract(
            layer=PlatformLayer.CANONICAL_WAREHOUSE,
            mutable=False,
            business_logic_allowed=False,
            derived_indicators_allowed=False,
            regenerative=True,
            purpose="Versioned downstream read model for canonical market truth.",
        ),
        LayerContract(
            layer=PlatformLayer.REPLAY_CACHE,
            mutable=True,
            business_logic_allowed=False,
            derived_indicators_allowed=False,
            regenerative=True,
            purpose="Disposable, version-keyed acceleration cache.",
        ),
    )


__all__ = ["AlphaDataPlatform", "build_default_platform"]
