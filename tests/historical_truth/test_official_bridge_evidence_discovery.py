from __future__ import annotations

import json
from pathlib import Path

from alpha.historical_truth.official_bridge_evidence_discovery import (
    HTR010B1F_DISCOVERY_CONTRACT_VERSION,
    build_discovery_registry,
    export_discovery_registry,
)


def _write_dossiers(root: Path, count: int = 20) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "dossier_id": f"dossier-{index}",
            "bridge_case_ids": [f"case-{index}"],
            "bridge_type": "CROSS_ISIN" if index < 19 else "CROSS_SERIES",
            "effective_date": "2026-01-02",
            "pre_isin": f"INE000000{index:03d}",
            "post_isin": f"INE100000{index:03d}",
            "pre_symbol": f"SYM{index}",
            "post_symbol": f"SYM{index}",
            "pre_series": "EQ",
            "post_series": "BE" if index == 19 else "EQ",
        }
        for index in range(count)
    ]
    path = root / "htr010b1f_evidence_dossiers.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_discovery_registry_builds_one_template_per_dossier(tmp_path: Path) -> None:
    dossiers = _write_dossiers(tmp_path / "dossiers")

    report = build_discovery_registry(dossiers_path=dossiers)

    assert report["contract_version"] == HTR010B1F_DISCOVERY_CONTRACT_VERSION
    assert report["input_dossier_count"] == 20
    assert report["discovery_template_count"] == 20
    assert report["populated_discovery_count"] == 0
    assert report["implementation_defect_count"] == 0
    assert len({row["discovery_id"] for row in report["discoveries"]}) == 20
    assert all(
        row["discovery_state"] == "PENDING_OFFICIAL_SOURCE_DISCOVERY"
        for row in report["discoveries"]
    )


def test_discovery_registry_is_blank_and_fail_closed(tmp_path: Path) -> None:
    dossiers = _write_dossiers(tmp_path / "dossiers")

    report = build_discovery_registry(dossiers_path=dossiers)
    row = report["discoveries"][0]

    assert row["source_url"] is None
    assert row["document_id"] is None
    assert row["source_sha256"] is None
    assert row["identity_continuity_certified"] is None
    assert row["production_influence"] is False
    assert report["benchmark_replay_count"] == 0


def test_discovery_registry_reports_population_defect(tmp_path: Path) -> None:
    dossiers = _write_dossiers(tmp_path / "dossiers", count=19)

    report = build_discovery_registry(dossiers_path=dossiers)

    assert report["implementation_defect_count"] == 1
    assert report["implementation_defects"] == ["EXPECTED_20_DOSSIERS_FOUND_19"]


def test_discovery_registry_export_is_deterministic(tmp_path: Path) -> None:
    dossiers = _write_dossiers(tmp_path / "dossiers")
    report = build_discovery_registry(dossiers_path=dossiers)

    paths = export_discovery_registry(report, tmp_path / "output")

    assert len(paths) == 4
    assert all(path.exists() for path in paths)
    assert report["report_sha256"]
