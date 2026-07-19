from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from alpha.warehouse_delta_audit.models import (
    MANDATORY_SYMBOLS,
    NO_FEATURE_CHANGES,
    NO_GATE_CHANGES,
    NO_REPLAY_CHANGES,
    NO_WEIGHT_CHANGES,
    PRODUCTION_INFLUENCE,
    SampleProfile,
    SourceLineage,
    WarehouseDeltaRequest,
)
from alpha.warehouse_delta_audit.provenance import freeze_wda_manifest
from alpha.warehouse_delta_audit.sampling import _comparison_files, _select_symbols


def test_policy_isolation_is_permanent() -> None:
    assert PRODUCTION_INFLUENCE is False
    assert NO_REPLAY_CHANGES is True
    assert NO_GATE_CHANGES is True
    assert NO_FEATURE_CHANGES is True
    assert NO_WEIGHT_CHANGES is True


def test_independent_source_requires_attestation() -> None:
    with pytest.raises(ValueError, match="requires an attestation"):
        WarehouseDeltaRequest(
            legacy_database="legacy.duckdb",
            comparison_source="official",
            output_directory="output",
            source_lineage=SourceLineage.INDEPENDENT_OFFICIAL,
        )


def test_sampling_is_stable_broad_and_includes_mandatory_symbols() -> None:
    extra = tuple((f"SYMBOL{index:03}", float(index + 1), 1000) for index in range(60))
    mandatory = tuple(
        (symbol, float(100 + index), 1000)
        for index, symbol in enumerate(MANDATORY_SYMBOLS)
    )
    universe = tuple(sorted(extra + mandatory, key=lambda row: (row[1], row[0])))
    first, strata = _select_symbols(universe, 50)
    second, second_strata = _select_symbols(universe, 50)
    assert first == second
    assert strata == second_strata
    assert set(MANDATORY_SYMBOLS).issubset(first)
    assert len(first) == 50
    assert all(strata[label] > 0 for label in ("LOW", "MEDIUM", "HIGH"))


def test_comparison_discovery_ignores_csv_named_directories(tmp_path: Path) -> None:
    archive = tmp_path / "cm01JAN2024bhav.csv"
    archive.mkdir()
    nested = archive / "cm01JAN2024bhav.csv"
    nested.write_text("SYMBOL,SERIES\nTEST,EQ\n")
    direct = tmp_path / "cm02JAN2024bhav.csv"
    direct.write_text("SYMBOL,SERIES\nTEST,EQ\n")
    files = _comparison_files(tmp_path)
    assert files == tuple(sorted((nested.resolve(), direct.resolve())))
    assert all(path.is_file() for path in files)


def test_frozen_manifest_validates_and_hashes_both_foundations(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / ".alpha/benchmark/ALPHA_BASELINE_v1.0/manifest.json"
    platform = tmp_path / ".alpha/data_platform/ALPHA_DATA_PLATFORM_v1.0/manifest.json"
    baseline.parent.mkdir(parents=True)
    platform.parent.mkdir(parents=True)
    baseline.write_text(
        json.dumps(
            {
                "baseline_id": "ALPHA_BASELINE_v1.0",
                "production_influence": False,
                "versions": {
                    "source_commit": "commit",
                    "warehouse_version": "warehouse-v1",
                    "warehouse_hash": "warehouse-hash",
                    "feature_version": "feature-v1",
                    "candidate_generation_version": "candidate-v1",
                    "approval_policy_version": "policy-v1",
                },
            }
        )
    )
    platform.write_text(
        json.dumps(
            {
                "platform_version": "ALPHA_DATA_PLATFORM_v1.0",
                "production_influence": False,
            }
        )
    )
    legacy = tmp_path / "legacy.duckdb"
    source = tmp_path / "source.csv"
    legacy.write_bytes(b"legacy")
    source.write_text("source")
    sample = SampleProfile(
        requested_symbols=7,
        selected_symbols=MANDATORY_SYMBOLS,
        mandatory_symbols_present=MANDATORY_SYMBOLS,
        mandatory_symbols_missing=(),
        start=date(2020, 1, 1),
        end=date(2025, 1, 1),
        sessions=1200,
        source_files=1,
        liquidity_high=3,
        liquidity_medium=2,
        liquidity_low=2,
        sector_coverage="UNKNOWN",
        market_cap_coverage="UNKNOWN",
    )
    first = freeze_wda_manifest(
        project_root=tmp_path,
        legacy_database=legacy,
        comparison_files=(source,),
        source_lineage=SourceLineage.LEGACY_LINEAGE_RAW_SOURCE,
        source_attestation=None,
        sample=sample,
    )
    second = freeze_wda_manifest(
        project_root=tmp_path,
        legacy_database=legacy,
        comparison_files=(source,),
        source_lineage=SourceLineage.LEGACY_LINEAGE_RAW_SOURCE,
        source_attestation=None,
        sample=sample,
    )
    assert first == second
    assert first.baseline_id == "ALPHA_BASELINE_v1.0"
    assert first.data_platform_id == "ALPHA_DATA_PLATFORM_v1.0"
    assert first.manifest_hash
    assert first.production_influence is False
