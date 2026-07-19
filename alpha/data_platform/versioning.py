from __future__ import annotations

from collections.abc import Mapping

from alpha.data_platform.models import (
    ReplayDataBinding,
    WarehouseRelease,
    WarehouseReleaseStatus,
    stable_hash,
)


class WarehouseVersionRegistry:
    def __init__(self, releases: tuple[WarehouseRelease, ...]) -> None:
        ordered = tuple(sorted(releases, key=lambda item: item.warehouse_version))
        if len({item.warehouse_version for item in ordered}) != len(ordered):
            raise ValueError("ADP warehouse versions must be unique")
        versions = {item.warehouse_version for item in ordered}
        for release in ordered:
            if release.parent_version and release.parent_version not in versions:
                raise ValueError("ADP warehouse parent version is not registered")
        self._releases = ordered

    @property
    def releases(self) -> tuple[WarehouseRelease, ...]:
        return self._releases

    @property
    def lineage_hash(self) -> str:
        return stable_hash(self._releases)

    def get(self, version: str) -> WarehouseRelease:
        for release in self._releases:
            if release.warehouse_version == version:
                return release
        raise KeyError(f"ADP warehouse version is not registered: {version}")

    def register(self, release: WarehouseRelease) -> WarehouseVersionRegistry:
        if any(
            item.warehouse_version == release.warehouse_version
            for item in self._releases
        ):
            raise ValueError("ADP warehouse version is already registered")
        return WarehouseVersionRegistry((*self._releases, release))

    def bind_replay(
        self,
        *,
        warehouse_version: str,
        feature_version: str,
        policy_version: str,
        decision_version: str,
        dataset_versions: Mapping[str, str],
    ) -> ReplayDataBinding:
        release = self.get(warehouse_version)
        if release.status not in {
            WarehouseReleaseStatus.FROZEN,
            WarehouseReleaseStatus.PUBLISHED,
        }:
            raise ValueError("ADP replay binding requires a frozen warehouse release")
        return ReplayDataBinding(
            warehouse_version=warehouse_version,
            feature_version=feature_version,
            policy_version=policy_version,
            decision_version=decision_version,
            dataset_versions=dataset_versions,
        )


def default_warehouse_versions() -> WarehouseVersionRegistry:
    legacy = _release(
        "WAREHOUSE_V1_LEGACY",
        status=WarehouseReleaseStatus.PUBLISHED,
        parent=None,
        dataset_versions={"legacy-dataset": "PROVISIONAL"},
        schemas=("legacy-schema-unknown",),
        read_only=True,
        notes="Existing Warehouse v1 remains unchanged and provisional.",
    )
    canonical = _release(
        "WAREHOUSE_V2_CANONICAL_DRAFT",
        status=WarehouseReleaseStatus.DRAFT,
        parent=legacy.warehouse_version,
        dataset_versions={},
        schemas=("adp-canonical-schema-family-v1",),
        read_only=False,
        notes="Architecture only; no official datasets acquired or published.",
    )
    institutional = _release(
        "WAREHOUSE_V3_INSTITUTIONAL_PLANNED",
        status=WarehouseReleaseStatus.PLANNED,
        parent=canonical.warehouse_version,
        dataset_versions={},
        schemas=("adp-institutional-schema-family-unavailable",),
        read_only=False,
        notes="Reserved upgrade path; scope and data rights remain unknown.",
    )
    return WarehouseVersionRegistry((legacy, canonical, institutional))


def _release(
    version: str,
    *,
    status: WarehouseReleaseStatus,
    parent: str | None,
    dataset_versions: Mapping[str, str],
    schemas: tuple[str, ...],
    read_only: bool,
    notes: str,
) -> WarehouseRelease:
    payload = {
        "warehouse_version": version,
        "status": status.value,
        "parent_version": parent,
        "dataset_versions": dict(sorted(dataset_versions.items())),
        "schema_versions": schemas,
        "read_only": read_only,
        "notes": notes,
    }
    return WarehouseRelease(
        warehouse_version=version,
        status=status,
        parent_version=parent,
        dataset_versions=dataset_versions,
        schema_versions=schemas,
        release_hash=stable_hash(payload),
        read_only=read_only,
        notes=notes,
    )


__all__ = ["WarehouseVersionRegistry", "default_warehouse_versions"]
