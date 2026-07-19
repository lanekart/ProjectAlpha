from __future__ import annotations

import csv
from pathlib import Path
from urllib.parse import urlparse

DOCS = Path(__file__).resolve().parents[2] / "docs" / "hmdpca"
EXPECTED_FILES = {
    "cost_matrix.csv",
    "coverage_matrix.csv",
    "executive_report.md",
    "historical_data_inventory.md",
    "licensing_matrix.csv",
    "procurement_matrix.csv",
    "procurement_roadmap.md",
    "quality_matrix.csv",
    "warehouse_impact.md",
}


def _rows(name: str) -> list[dict[str, str]]:
    with (DOCS / name).open(newline="") as handle:
        return list(csv.DictReader(handle))


def _read(name: str) -> str:
    return (DOCS / name).read_text()


def test_all_hmdpca_deliverables_exist() -> None:
    assert {path.name for path in DOCS.iterdir() if path.is_file()} == EXPECTED_FILES


def test_coverage_matrix_covers_every_required_domain() -> None:
    rows = _rows("coverage_matrix.csv")
    required_columns = {
        "dataset_id",
        "domain",
        "dataset",
        "source",
        "provider_class",
        "official",
        "historical_depth",
        "coverage_pct",
        "coverage_basis",
        "fields",
        "corporate_action_quality",
        "point_in_time_safe",
        "download_method",
        "api",
        "bulk_download",
        "license_status",
        "commercial_use",
        "redistribution",
        "cost_band",
        "published_cost",
        "confidence",
        "quality_grade",
        "update_frequency",
        "source_url",
        "verified_on",
        "decision",
        "production_influence",
    }

    assert len(rows) >= 35
    assert set(rows[0]) == required_columns
    assert len({row["dataset_id"] for row in rows}) == len(rows)
    assert all(all(value.strip() for value in row.values()) for row in rows)
    assert {row["domain"].split("_", maxsplit=1)[0] for row in rows} == set("ABCDEFGHI")
    assert all(row["verified_on"] == "2026-07-19" for row in rows)
    assert all(row["production_influence"] == "FALSE" for row in rows)


def test_unknown_coverage_is_not_fabricated() -> None:
    rows = _rows("coverage_matrix.csv")

    assert all(row["coverage_pct"] == "UNKNOWN_PENDING_SAMPLE" for row in rows)
    assert all(row["quality_grade"] in {"B", "C", "D", "UNUSABLE"} for row in rows)
    assert not any(row["quality_grade"] == "A" for row in rows)


def test_coverage_sources_are_https_and_decisions_are_explicit() -> None:
    rows = _rows("coverage_matrix.csv")

    for row in rows:
        parsed = urlparse(row["source_url"])
        assert parsed.scheme == "https"
        assert parsed.netloc
        assert row["decision"] != "UNKNOWN"


def test_wrapper_and_brokers_are_not_promoted_to_authority() -> None:
    rows = {row["dataset_id"]: row for row in _rows("coverage_matrix.csv")}

    assert rows["NSE_ARCHIVES_WRAPPER"]["quality_grade"] == "D"
    assert rows["NSE_ARCHIVES_WRAPPER"]["decision"] == (
        "ADAPTER_ONLY_AFTER_ENTITLEMENT"
    )
    assert rows["UPSTOX_V3_DAILY"]["decision"] == "SECONDARY_OVERLAP_ONLY"
    assert rows["ZERODHA_CANDLES"]["decision"] == "LIVE_OR_OVERLAP_ONLY"
    assert rows["YAHOO_FINANCE"]["quality_grade"] == "UNUSABLE"
    assert rows["GITHUB_DATASETS"]["quality_grade"] == "UNUSABLE"


def test_cost_matrix_separates_published_prices_from_quotes() -> None:
    rows = _rows("cost_matrix.csv")
    by_product = {(row["source"], row["product"]): row for row in rows}

    assert (
        by_product[("NSE Data & Analytics", "Capital Market EOD")]["published_price"]
        == "100000"
    )
    assert (
        by_product[("NSE Data & Analytics", "Master Data")]["published_price"]
        == "215000"
    )
    assert (
        by_product[("NSE Data & Analytics", "EOD Corporate Data")]["published_price"]
        == "500000"
    )
    assert (
        by_product[("NSE Indices", "Historical levels and constituents")][
            "pricing_status"
        ]
        == "QUOTE_REQUIRED"
    )
    assert all(row["production_influence"] == "FALSE" for row in rows)


def test_licensing_matrix_never_infers_unwritten_rights() -> None:
    rows = _rows("licensing_matrix.csv")
    by_source = {row["source"]: row for row in rows}

    assert by_source["NSE Data & Analytics"]["local_retention"] == ("CONTRACT_REQUIRED")
    assert by_source["nse-archives"]["local_retention"] == "INHERITS_UPSTREAM"
    assert by_source["Yahoo Finance"]["legal_status"] == "REJECTED"
    assert all(row["production_influence"] == "FALSE" for row in rows)


def test_quality_matrix_uses_closed_conservative_grades() -> None:
    rows = _rows("quality_matrix.csv")

    assert len(rows) >= 25
    assert {row["grade"] for row in rows} <= {"B", "C", "D", "UNUSABLE"}
    assert all(row["upgrade_to_a_requires"].strip() for row in rows)
    assert all(row["production_influence"] == "FALSE" for row in rows)


def test_procurement_matrix_is_prioritized_and_fail_closed() -> None:
    rows = _rows("procurement_matrix.csv")

    assert {row["priority"] for row in rows} == {"P0", "P1", "P2", "DEFERRED", "REJECT"}
    assert all(row["acceptance_gate"].strip() for row in rows)
    rejected = [row for row in rows if row["priority"] == "REJECT"]
    assert rejected
    assert all(row["production_influence"] == "FALSE" for row in rows)


def test_markdown_declares_scope_and_required_decisions() -> None:
    for path in DOCS.glob("*.md"):
        document = path.read_text()
        assert "PRODUCTION_INFLUENCE=false" in document
        assert "PRODUCTION_INFLUENCE=true" not in document

    inventory = _read("historical_data_inventory.md")
    normalized_inventory = " ".join(inventory.split())
    assert "UNKNOWN_PENDING_SAMPLE" in inventory
    assert "downloads no market data" in inventory
    assert "software license covers the wrapper code only" in normalized_inventory

    roadmap = _read("procurement_roadmap.md")
    assert "INR 315,000" in roadmap
    assert "INR 815,000" in roadmap
    assert "No downloader or warehouse migration" in roadmap


def test_executive_report_links_every_supporting_artifact() -> None:
    document = _read("executive_report.md")

    for filename in EXPECTED_FILES - {"executive_report.md"}:
        assert filename in document
    assert "## Executive Summary" in document
    assert "INR 315,000" in document
    assert "not the total" in document
    assert "All coverage percentages remain `UNKNOWN_PENDING_SAMPLE`" in document
