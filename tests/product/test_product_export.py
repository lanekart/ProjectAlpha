from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from alpha.product import (
    ProductExportManifest,
    ProductExportService,
    ProductReport,
    ProductReportMetadata,
    ProductReportSection,
)


def make_report() -> ProductReport:
    return ProductReport(
        metadata=ProductReportMetadata(
            kind="foundation_report",
            title="Foundation Report",
            observed_on=date(2026, 1, 30),
        ),
        sections=(
            ProductReportSection(
                title="Status",
                lines=("Product infrastructure is available.",),
            ),
        ),
    )


def test_product_export_writes_json_and_text(tmp_path: Path) -> None:
    json_path = tmp_path / "foundation.json"
    text_path = tmp_path / "foundation.txt"

    result = ProductExportService().export(
        make_report(),
        json_path=json_path,
        text_path=text_path,
    )

    assert result.wrote_any
    assert result.json_path == json_path
    assert result.text_path == text_path
    assert result.manifest.as_lines() == (
        f"json: {json_path.as_posix()}",
        f"text: {text_path.as_posix()}",
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["kind"] == "foundation_report"
    assert payload["metadata"]["observed_on"] == "2026-01-30"
    assert "Foundation Report" in text_path.read_text(encoding="utf-8")


def test_product_export_returns_empty_result_without_paths() -> None:
    result = ProductExportService().export(make_report())

    assert not result.wrote_any
    assert result.manifest == ProductExportManifest(())


def test_product_export_rejects_invalid_json_suffix(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="expected .json output path"):
        ProductExportService().export(
            make_report(),
            json_path=tmp_path / "foundation.txt",
        )


def test_product_export_rejects_invalid_text_suffix(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="expected .txt output path"):
        ProductExportService().export(
            make_report(),
            text_path=tmp_path / "foundation.json",
        )
