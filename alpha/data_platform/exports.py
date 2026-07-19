from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

from alpha.data_platform.models import DEFAULT_OUTPUT, ADPManifest
from alpha.data_platform.platform import AlphaDataPlatform
from alpha.data_platform.rendering import render_documents

DEFAULT_DATA_PLATFORM_OUTPUT = Path(DEFAULT_OUTPUT)


class DataPlatformExporter:
    """Write the frozen architecture bundle without acquiring market data."""

    def export(
        self,
        platform: AlphaDataPlatform,
        *,
        output_directory: Path | str = DEFAULT_DATA_PLATFORM_OUTPUT,
    ) -> tuple[Path, ...]:
        output = Path(output_directory)
        documents = render_documents(platform)
        payloads = {
            **{name: value for name, value in documents.items()},
            "dataset_registry.json": json.dumps(
                {
                    "platform_version": platform.manifest.platform_version,
                    "registry_hash": platform.registry.registry_hash,
                    "datasets": [
                        _json_value(item) for item in platform.registry.records
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
        }
        artifact_hashes = {
            name: sha256(value.encode()).hexdigest()
            for name, value in sorted(payloads.items())
        }
        self._assert_compatible(output, platform.manifest, artifact_hashes)
        output.mkdir(parents=True, exist_ok=True)
        paths = tuple(
            _write_text(output / name, value)
            for name, value in sorted(payloads.items())
        )
        manifest = replace(platform.manifest, artifact_hashes=artifact_hashes)
        manifest_path = _write_text(
            output / "manifest.json",
            json.dumps(_json_value(manifest), indent=2, sort_keys=True) + "\n",
        )
        return (*paths, manifest_path)

    @staticmethod
    def _assert_compatible(
        output: Path,
        manifest: ADPManifest,
        artifact_hashes: Mapping[str, str],
    ) -> None:
        path = output / "manifest.json"
        if not path.exists():
            return
        existing = json.loads(path.read_text(encoding="utf-8"))
        identity = (
            "platform_version",
            "registry_hash",
            "schema_catalog_hash",
            "warehouse_lineage_hash",
            "layer_contract_hash",
        )
        expected = {
            "platform_version": manifest.platform_version,
            "registry_hash": manifest.registry_hash,
            "schema_catalog_hash": manifest.schema_catalog_hash,
            "warehouse_lineage_hash": manifest.warehouse_lineage_hash,
            "layer_contract_hash": manifest.layer_contract_hash,
        }
        if any(existing.get(key) != expected[key] for key in identity):
            raise ValueError("frozen ADP output exists for a different architecture")
        if existing.get("artifact_hashes") != dict(sorted(artifact_hashes.items())):
            raise ValueError("frozen ADP artifacts cannot be rewritten in place")


def load_manifest(
    output_directory: Path | str = DEFAULT_DATA_PLATFORM_OUTPUT,
) -> dict[str, object]:
    path = Path(output_directory) / "manifest.json"
    if not path.exists():
        raise FileNotFoundError("ADP manifest unavailable; run alpha data platform")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("production_influence") is not False:
        raise ValueError("invalid ADP production isolation marker")
    return {str(key): value for key, value in payload.items()}


def _json_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(
            {item.name: getattr(value, item.name) for item in fields(value)}
        )
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime, Decimal, Path)):
        return str(value)
    return value


def _write_text(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(value)
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return path


__all__ = ["DEFAULT_DATA_PLATFORM_OUTPUT", "DataPlatformExporter", "load_manifest"]
