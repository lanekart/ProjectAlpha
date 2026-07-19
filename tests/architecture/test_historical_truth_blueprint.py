from __future__ import annotations

import csv
from pathlib import Path
from urllib.parse import urlparse

DOCS = Path(__file__).resolve().parents[2] / "docs" / "historical_truth"
EXPECTED_FILES = {
    "historical_data_inventory.md",
    "coverage_matrix.csv",
    "warehouse_architecture.md",
    "truth_classification.md",
    "confidence_engine.md",
    "reconciliation_strategy.md",
    "warehouse_versioning.md",
    "download_strategy.md",
    "risk_register.md",
    "implementation_blueprint.md",
    "executive_report.md",
}
OFFICIAL_DOMAINS = {
    "bseindia.com",
    "cdslindia.com",
    "niftyindices.com",
    "nsdl.co.in",
    "nseindia.com",
    "sebi.gov.in",
}


def _read(name: str) -> str:
    return (DOCS / name).read_text()


def _coverage() -> list[dict[str, str]]:
    with (DOCS / "coverage_matrix.csv").open(newline="") as handle:
        return list(csv.DictReader(handle))


def test_all_required_architecture_deliverables_exist() -> None:
    assert {path.name for path in DOCS.iterdir() if path.is_file()} == EXPECTED_FILES


def test_coverage_matrix_is_complete_and_source_backed() -> None:
    rows = _coverage()
    required_columns = {
        "dataset_id",
        "authority",
        "dataset",
        "family",
        "availability",
        "coverage_start",
        "coverage_end",
        "coverage_basis",
        "official",
        "public",
        "requires_registration",
        "paid",
        "point_in_time_role",
        "missing_or_unknown",
        "source_url",
        "verified_on",
    }

    assert len(rows) >= 30
    assert set(rows[0]) == required_columns
    assert len({row["dataset_id"] for row in rows}) == len(rows)
    assert all(all(value.strip() for value in row.values()) for row in rows)
    assert all(row["official"] == "TRUE" for row in rows)
    assert all(row["verified_on"] == "2026-07-19" for row in rows)

    authorities = {row["authority"] for row in rows}
    required_authorities = {
        "BSE",
        "CDSL",
        "NSDL",
        "NSE",
        "NSE Data & Analytics",
        "NSE Indices",
        "SEBI",
    }
    assert required_authorities <= authorities

    for row in rows:
        parsed = urlparse(row["source_url"])
        domain = parsed.netloc.removeprefix("www.")
        assert parsed.scheme == "https"
        assert any(
            domain == allowed or domain.endswith(f".{allowed}")
            for allowed in OFFICIAL_DOMAINS
        )


def test_unknown_coverage_is_not_promoted_to_historical_truth() -> None:
    rows = {row["dataset_id"]: row for row in _coverage()}

    assert rows["NSE_INDEX_CONSTITUENTS_HISTORY"]["coverage_start"] == "UNKNOWN"
    constituent_gap = rows["NSE_INDEX_CONSTITUENTS_HISTORY"]["missing_or_unknown"]
    assert "require" in constituent_gap.lower()
    assert rows["NSE_INDUSTRY_CLASSIFICATION"]["coverage_start"] == "CURRENT_ONLY"
    sector_gap = rows["NSE_INDUSTRY_CLASSIFICATION"]["missing_or_unknown"]
    assert "historical" in sector_gap.lower()
    assert rows["CDSL_ISIN_MASTER"]["coverage_start"] == "CURRENT_ONLY"
    assert rows["BSE_LISTING_HISTORY"]["availability"] == "MISSING_COMPLETE_DATASET"


def test_truth_classification_is_closed_and_separate_from_resolution() -> None:
    document = _read("truth_classification.md")

    for value in ("OFFICIAL", "OBSERVED", "INFERRED", "CURRENT_ONLY", "UNKNOWN"):
        assert f"`{value}`" in document
    for status in ("CONFIRMED", "REVISED", "CONFLICTED", "QUARANTINED"):
        assert f"`{status}`" in document
    assert "Truth class does not resolve disagreement" in document
    assert "cannot be copied backward" in document


def test_architecture_preserves_required_stage_order_and_bitemporality() -> None:
    document = _read("warehouse_architecture.md")
    flow = document.split("## Required Flow", maxsplit=1)[1]
    stages = (
        "Raw Data",
        "Normalization",
        "Corporate Action Engine",
        "Security Master",
        "Identity Resolution",
        "Historical Universe",
        "Canonical Warehouse",
        "Research Layer",
    )

    positions = [flow.index(stage) for stage in stages]
    assert positions == sorted(positions)
    assert "valid time" in document
    assert "knowledge time" in document
    assert "Warehouse v1 remains" in document


def test_confidence_engine_cannot_hide_missing_mandatory_components() -> None:
    document = _read("confidence_engine.md")

    for component in (
        "Source authority",
        "Reconciliation",
        "Completeness",
        "Identity certainty",
        "Corporate-action safety",
        "Point-in-time safety",
    ):
        assert component in document
    assert "lowest grade among mandatory components" in document
    assert "current overall confidence remains `LOW`" in document


def test_reconciliation_covers_required_conflicts_without_conflating_venues() -> None:
    document = _read("reconciliation_strategy.md")

    for mismatch in (
        "Price mismatch",
        "Volume mismatch",
        "Missing day",
        "Symbol or identity mismatch",
        "Corporate-action mismatch",
    ):
        assert mismatch in document
    assert "NSE and BSE prices are separate venue observations" in document
    assert "Legacy evidence can confirm" in document


def test_versioning_pins_the_complete_decision_provenance_bundle() -> None:
    document = _read("warehouse_versioning.md")

    for version in (
        "Warehouse Version",
        "Feature Version",
        "Policy Version",
        "Decision Version",
    ):
        assert version in document
    for family in ("Warehouse v1", "Warehouse v2", "Warehouse v3", "Warehouse v4"):
        assert family in document
    assert "No version is overwritten" in document


def test_download_strategy_is_a_fail_closed_design_not_an_implementation() -> None:
    document = _read("download_strategy.md")

    assert "No downloader exists in this milestone" in document
    assert "Failure at any gate means no acquisition" in document
    assert "Do not bypass CAPTCHA" in document
    assert "does not download data" in document


def test_blueprint_defers_production_and_contains_full_roadmap() -> None:
    document = _read("implementation_blueprint.md")

    for stage in (
        "Historical Truth Engine",
        "Canonical Warehouse v2",
        "Canonical Alpha Fund",
        "Institutional Data Layer",
    ):
        assert stage in document
    assert "No downloader is built before this gate" in document
    assert "production routing or policy changes" in document


def test_every_markdown_deliverable_declares_no_production_influence() -> None:
    for path in DOCS.glob("*.md"):
        document = path.read_text()
        assert "PRODUCTION_INFLUENCE=false" in document
        assert "PRODUCTION_INFLUENCE=true" not in document


def test_executive_report_links_every_deliverable_and_preserves_unknowns() -> None:
    document = _read("executive_report.md")

    for filename in EXPECTED_FILES - {"executive_report.md"}:
        assert filename in document
    assert "Overall current confidence | `LOW`" in document
    assert "do not begin bulk acquisition yet" in document
    assert "no recommendation" in document.lower()
