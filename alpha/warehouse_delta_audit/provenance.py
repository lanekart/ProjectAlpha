"""Frozen baseline and data-platform provenance for WDA."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

from alpha.benchmark_replay.provenance import file_hash
from alpha.warehouse_delta_audit.models import (
    BASELINE_ID,
    DATA_PLATFORM_ID,
    WDA_VERSION,
    SampleProfile,
    SourceLineage,
    WarehouseDeltaManifest,
)

DEFAULT_BASELINE_MANIFEST = Path(".alpha/benchmark/ALPHA_BASELINE_v1.0/manifest.json")
DEFAULT_PLATFORM_MANIFEST = Path(
    ".alpha/data_platform/ALPHA_DATA_PLATFORM_v1.0/manifest.json"
)


def freeze_wda_manifest(
    *,
    project_root: Path,
    legacy_database: Path,
    comparison_files: tuple[Path, ...],
    source_lineage: SourceLineage,
    source_attestation: str | None,
    sample: SampleProfile,
) -> WarehouseDeltaManifest:
    """Validate both frozen manifests and persist a deterministic WDA freeze."""

    baseline_path = project_root / DEFAULT_BASELINE_MANIFEST
    platform_path = project_root / DEFAULT_PLATFORM_MANIFEST
    baseline = _json_object(baseline_path)
    platform = _json_object(platform_path)
    if baseline.get("baseline_id") != BASELINE_ID:
        raise ValueError("WDA requires ALPHA_BASELINE_v1.0")
    if platform.get("platform_version") != DATA_PLATFORM_ID:
        raise ValueError("WDA requires ALPHA_DATA_PLATFORM_v1.0")
    if baseline.get("production_influence") is not False:
        raise ValueError("baseline production influence must be false")
    if platform.get("production_influence") is not False:
        raise ValueError("data platform production influence must be false")
    versions = _object(baseline.get("versions"), "baseline versions")
    core = {
        "audit_version": WDA_VERSION,
        "baseline_id": BASELINE_ID,
        "data_platform_id": DATA_PLATFORM_ID,
        "source_commit": _text(versions, "source_commit"),
        "warehouse_version": _text(versions, "warehouse_version"),
        "comparison_warehouse_version": "WAREHOUSE_SAMPLE_V2",
        "feature_version": _text(versions, "feature_version"),
        "candidate_version": _text(versions, "candidate_generation_version"),
        "policy_version": _text(versions, "approval_policy_version"),
        "baseline_manifest_hash": file_hash(baseline_path),
        "data_platform_manifest_hash": file_hash(platform_path),
        "legacy_warehouse_hash": _text(versions, "warehouse_hash"),
        "comparison_source_hash": _source_hash(comparison_files),
        "sample_symbols_hash": _hash_text("\n".join(sample.selected_symbols)),
        "source_lineage": source_lineage.value,
        "source_attestation": source_attestation,
        "production_influence": False,
        "no_replay_changes": True,
        "no_gate_changes": True,
        "no_feature_changes": True,
        "no_weight_changes": True,
    }
    manifest_hash = _hash_text(_canonical_json(core))
    return WarehouseDeltaManifest(
        audit_version=WDA_VERSION,
        baseline_id=BASELINE_ID,
        data_platform_id=DATA_PLATFORM_ID,
        source_commit=str(core["source_commit"]),
        warehouse_version=str(core["warehouse_version"]),
        comparison_warehouse_version="WAREHOUSE_SAMPLE_V2",
        feature_version=str(core["feature_version"]),
        candidate_version=str(core["candidate_version"]),
        policy_version=str(core["policy_version"]),
        baseline_manifest_hash=str(core["baseline_manifest_hash"]),
        data_platform_manifest_hash=str(core["data_platform_manifest_hash"]),
        legacy_warehouse_hash=(
            file_hash(legacy_database)
            if str(core["legacy_warehouse_hash"]) == "UNAVAILABLE"
            else str(core["legacy_warehouse_hash"])
        ),
        comparison_source_hash=str(core["comparison_source_hash"]),
        sample_symbols_hash=str(core["sample_symbols_hash"]),
        manifest_hash=manifest_hash,
        source_lineage=source_lineage,
        source_attestation=source_attestation,
    )


def manifest_payload(manifest: WarehouseDeltaManifest) -> dict[str, object]:
    return {
        "audit_version": manifest.audit_version,
        "baseline_id": manifest.baseline_id,
        "data_platform_id": manifest.data_platform_id,
        "source_commit": manifest.source_commit,
        "warehouse_version": manifest.warehouse_version,
        "comparison_warehouse_version": manifest.comparison_warehouse_version,
        "feature_version": manifest.feature_version,
        "candidate_version": manifest.candidate_version,
        "policy_version": manifest.policy_version,
        "baseline_manifest_hash": manifest.baseline_manifest_hash,
        "data_platform_manifest_hash": manifest.data_platform_manifest_hash,
        "legacy_warehouse_hash": manifest.legacy_warehouse_hash,
        "comparison_source_hash": manifest.comparison_source_hash,
        "sample_symbols_hash": manifest.sample_symbols_hash,
        "manifest_hash": manifest.manifest_hash,
        "source_lineage": manifest.source_lineage.value,
        "source_attestation": manifest.source_attestation,
        "production_influence": manifest.production_influence,
        "no_replay_changes": manifest.no_replay_changes,
        "no_gate_changes": manifest.no_gate_changes,
        "no_feature_changes": manifest.no_feature_changes,
        "no_weight_changes": manifest.no_weight_changes,
    }


def _source_hash(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        stat = path.stat()
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(b"\0")
        digest.update(file_hash(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _json_object(path: Path) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"required frozen manifest not found: {path}")
    decoded = cast(object, json.loads(path.read_text(encoding="utf-8")))
    return _object(decoded, str(path))


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return {str(key): item for key, item in value.items()}


def _text(values: dict[str, object], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"frozen manifest missing {key}")
    return value


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


__all__ = ["freeze_wda_manifest", "manifest_payload"]
