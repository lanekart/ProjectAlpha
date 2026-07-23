from __future__ import annotations

import json
from pathlib import Path

from alpha.historical_truth.official_bridge_evidence_dossier import (
    OfficialBridgeEvidenceDossierBuilder,
)


def _request(
    *,
    case_id: str,
    symbol: str,
    effective_date: str,
    pre_isin: str,
    post_isin: str,
    bridge_type: str = "CROSS_ISIN",
    pre_series: str = "EQ",
    post_series: str = "EQ",
) -> dict[str, object]:
    return {
        "bridge_case_id": case_id,
        "bridge_type": bridge_type,
        "effective_date": effective_date,
        "pre_isin": pre_isin,
        "post_isin": post_isin,
        "pre_symbol": symbol,
        "post_symbol": symbol,
        "pre_series": pre_series,
        "post_series": post_series,
        "preferred_source_classes": ["NSE_CORPORATE_ACTION_NOTICE"],
        "required_official_questions": ["continuity"],
        "search_terms": [symbol, effective_date, pre_isin, post_isin],
    }


def _write_manifest(root: Path, rows: list[dict[str, object]]) -> None:
    root.mkdir(parents=True)
    (root / "htr010b1f_evidence_requests.json").write_text(
        json.dumps(rows), encoding="utf-8"
    )


def test_dossiers_collapse_duplicate_factor_cases(tmp_path: Path) -> None:
    rows = [
        _request(
            case_id=f"case-{index}",
            symbol=f"SYM{index}",
            effective_date=f"2026-01-{index + 1:02d}",
            pre_isin=f"INE000000{index:03d}",
            post_isin=f"INE100000{index:03d}",
        )
        for index in range(16)
    ]
    duplicate_pairs = [
        ("BESTAGRO", "2026-01-16", "INE052T01013", "INE052T01021"),
        ("DELPHIFX", "2026-02-13", "INE726L01019", "INE726L01027"),
        ("SILVERTUC", "2026-03-06", "INE625X01018", "INE625X01026"),
        ("RNBDENIMS", "2026-04-02", "INE012Q01021", "INE012Q01039"),
    ]
    for index, (symbol, effective, pre_isin, post_isin) in enumerate(
        duplicate_pairs
    ):
        rows.extend(
            [
                _request(
                    case_id=f"duplicate-{index}-a",
                    symbol=symbol,
                    effective_date=effective,
                    pre_isin=pre_isin,
                    post_isin=post_isin,
                ),
                _request(
                    case_id=f"duplicate-{index}-b",
                    symbol=symbol,
                    effective_date=effective,
                    pre_isin=pre_isin,
                    post_isin=post_isin,
                ),
            ]
        )
    _write_manifest(tmp_path, rows)

    report = OfficialBridgeEvidenceDossierBuilder().run(
        evidence_manifest_output=tmp_path
    )

    assert report["input_bridge_case_count"] == 24
    assert report["unique_dossier_count"] == 20
    assert report["multi_case_dossier_count"] == 4
    assert report["maximum_cases_per_dossier"] == 2
    assert report["implementation_defect_count"] == 0


def test_dossier_preserves_independent_case_ids(tmp_path: Path) -> None:
    rows = [
        _request(
            case_id="case-a",
            symbol="BESTAGRO",
            effective_date="2026-01-16",
            pre_isin="INE052T01013",
            post_isin="INE052T01021",
        ),
        _request(
            case_id="case-b",
            symbol="BESTAGRO",
            effective_date="2026-01-16",
            pre_isin="INE052T01013",
            post_isin="INE052T01021",
        ),
    ]
    _write_manifest(tmp_path, rows)

    report = OfficialBridgeEvidenceDossierBuilder().run(
        evidence_manifest_output=tmp_path
    )
    dossier = report["dossiers"][0]

    assert dossier["bridge_case_ids"] == ["case-a", "case-b"]
    assert "INDEPENDENT_CERTIFICATION_DECISION" in dossier[
        "evidence_reuse_policy"
    ]
    assert report["implementation_defect_count"] > 0


def test_dossier_export_is_deterministic(tmp_path: Path) -> None:
    rows = [
        _request(
            case_id=f"case-{index}",
            symbol=f"SYM{index}",
            effective_date=f"2026-01-{index + 1:02d}",
            pre_isin=f"INE000000{index:03d}",
            post_isin=f"INE100000{index:03d}",
        )
        for index in range(24)
    ]
    _write_manifest(tmp_path / "manifest", rows)
    builder = OfficialBridgeEvidenceDossierBuilder()
    report = builder.run(evidence_manifest_output=tmp_path / "manifest")
    paths = builder.export(report, tmp_path / "output")

    assert len(paths) == 3
    assert all(path.exists() for path in paths)
    assert report["report_sha256"]
