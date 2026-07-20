"""Deterministic tests for entity schema discovery."""

from __future__ import annotations

import json
from pathlib import Path

from alpha.recovery import discover_sources, export_schema_discovery


def test_discovers_csv_and_json_schema(tmp_path: Path) -> None:
    security_master = tmp_path / "security_master.json"
    security_master.write_text(
        json.dumps(
            [
                {
                    "security_id": "SEC-1",
                    "isin": "INE000000001",
                    "symbol": "AAA",
                    "listing_date": "2020-01-01",
                    "historical_symbols": ["OLDAAA"],
                },
                {
                    "security_id": "SEC-2",
                    "isin": "INE000000002",
                    "symbol": "BBB",
                    "listing_date": "2021-02-03",
                    "historical_symbols": [],
                },
            ]
        ),
        encoding="utf-8",
    )
    listing = tmp_path / "listing_history.csv"
    listing.write_text(
        "security_id,official_listing_date,official_delisting_date\n"
        "SEC-1,2020-01-01,\n"
        "SEC-2,2021-02-03,\n",
        encoding="utf-8",
    )

    result = discover_sources((listing, security_master))

    assert tuple(schema.source_name for schema in result.sources) == (
        "listing_history",
        "security_master",
    )
    master = result.sources[1]
    assert master.row_count == 2
    assert "security_id" in master.candidate_primary_keys
    assert "listing_date" in master.candidate_date_fields
    assert "historical_symbols" in master.candidate_lineage_fields
    assert (
        "listing_history",
        "security_master",
        "security_id",
    ) in result.relationship_candidates


def test_mapping_candidates_include_known_aliases(tmp_path: Path) -> None:
    source = tmp_path / "listing_history.csv"
    source.write_text(
        "instrument_id,official_listing_date,sector_name\n"
        "1,2020-01-01,Financial Services\n",
        encoding="utf-8",
    )

    result = discover_sources((source,))
    mappings = {
        (item.raw_field, item.canonical_field, item.confidence)
        for item in result.mappings
    }

    assert ("instrument_id", "security_id", 0.95) in mappings
    assert ("official_listing_date", "listing_date", 0.95) in mappings
    assert ("sector_name", "sector", 0.95) in mappings


def test_exports_are_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "security_master.jsonl"
    source.write_text(
        '{"security_id":"SEC-1","symbol":"AAA"}\n'
        '{"security_id":"SEC-2","symbol":"BBB"}\n',
        encoding="utf-8",
    )
    result = discover_sources((source,))

    paths = export_schema_discovery(result, tmp_path / "artifacts")

    assert tuple(path.name for path in paths) == (
        "security_master.schema.json",
        "canonical_mapping_candidates.json",
        "relationship_graph.json",
        "report.md",
    )
    schema_payload = json.loads(paths[0].read_text(encoding="utf-8"))
    assert schema_payload["row_count"] == 2
    assert schema_payload["candidate_primary_keys"] == ["security_id", "symbol"]
    assert paths[-1].read_text(encoding="utf-8").startswith(
        "# Entity Schema Discovery\n"
    )
