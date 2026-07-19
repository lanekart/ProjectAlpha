from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.data_platform_cli import data_app
from alpha.data_platform import (
    DataPlatformExporter,
    DownloadFramework,
    RawArtifactCatalog,
    build_default_platform,
    default_dataset_registry,
)
from alpha.data_platform.models import (
    DownloadStatus,
    RawArtifactMetadata,
)


def test_raw_catalog_is_append_only_and_checksum_verifiable() -> None:
    registry = default_dataset_registry()
    payload = b"official source bytes"
    artifact = RawArtifactMetadata(
        artifact_id="raw-1",
        dataset_id="nse-equity-bhavcopy",
        source="NSE",
        original_filename="cm01JAN2020bhav.csv.zip",
        source_timestamp=None,
        retrieval_timestamp=datetime(2026, 7, 19, tzinfo=UTC),
        checksum=sha256(payload).hexdigest(),
        compression="zip",
        content_type="application/zip",
        byte_size=len(payload),
        relative_path="NSE/BHAVCOPY/2020/cm01JAN2020bhav.csv.zip",
        source_metadata={"official": "true"},
    )
    catalog = RawArtifactCatalog(registry).append(artifact)
    assert catalog.append(artifact) is catalog
    assert RawArtifactCatalog.verify_bytes(artifact, payload)
    with pytest.raises(ValueError, match="cannot be modified"):
        catalog.append(replace(artifact, checksum="a" * 64))


def test_download_framework_is_restart_safe_without_network() -> None:
    framework = DownloadFramework(default_dataset_registry())
    jobs = framework.plan_incremental(
        dataset_id="nse-equity-bhavcopy",
        start=date(2020, 1, 1),
        end=date(2020, 1, 3),
        requested_at=datetime(2026, 7, 19, tzinfo=UTC),
    )
    checkpoint = framework.begin(framework.initial_checkpoint(jobs[0]))
    checkpoint = framework.record_part(checkpoint, part_id="part-1", next_offset=100)
    paused = framework.pause(checkpoint)
    resumed = framework.begin(paused)
    corrupt = framework.verify(
        resumed,
        payload=b"wrong",
        expected_checksum=sha256(b"right").hexdigest(),
    )
    recovered = framework.recover_corruption(corrupt)
    assert len(jobs) == 3
    assert resumed.next_offset == 100
    assert corrupt.status is DownloadStatus.CORRUPT
    assert recovered.next_offset == 0
    assert framework.parallel_batches(jobs, maximum_parallelism=2)


def test_platform_exports_are_reproducible_and_download_free(tmp_path: Path) -> None:
    platform = build_default_platform()
    exporter = DataPlatformExporter()
    first = exporter.export(platform, output_directory=tmp_path)
    first_bytes = {path.name: path.read_bytes() for path in first}
    second = exporter.export(platform, output_directory=tmp_path)
    assert first_bytes == {path.name: path.read_bytes() for path in second}
    assert len(first) == 14
    assert platform.manifest.downloaded_files == 0
    assert platform.manifest.production_influence is False
    for name in (
        "platform_architecture.md",
        "dataset_registry.json",
        "schema_catalog.md",
        "provenance_model.md",
        "truth_classification.md",
        "confidence_engine.md",
        "reconciliation_framework.md",
        "download_framework.md",
        "query_model.md",
        "warehouse_versioning.md",
        "time_travel_design.md",
        "implementation_blueprint.md",
        "executive_report.md",
        "manifest.json",
    ):
        assert (tmp_path / name).exists()


def test_all_data_platform_cli_commands(tmp_path: Path) -> None:
    runner = CliRunner()
    results = (
        runner.invoke(data_app, ["platform", "--output", str(tmp_path)]),
        runner.invoke(data_app, ["registry"]),
        runner.invoke(data_app, ["datasets"]),
        runner.invoke(
            data_app,
            [
                "query",
                "--dataset",
                "nse-corporate-actions",
                "--symbol",
                "RELIANCE",
                "--start",
                "2020-01-01",
                "--end",
                "2020-12-31",
                "--as-of",
                "2020-12-31T23:59:59+00:00",
            ],
        ),
        runner.invoke(data_app, ["provenance"]),
        runner.invoke(data_app, ["architecture"]),
    )
    assert all(result.exit_code == 0 for result in results)
    assert "Registered Official Datasets: 20" in results[0].stdout
    assert "Datasets: 20" in results[1].stdout
    assert "No historical downloads were performed" in results[2].stdout
    assert "DATASET_NOT_ACQUIRED" in results[3].stdout
    assert "Observation Provenance: unavailable" in results[4].stdout
    assert "CANONICAL_WAREHOUSE" in results[5].stdout
