from __future__ import annotations

import json
from datetime import date
from hashlib import sha256
from pathlib import Path

from typer.testing import CliRunner

from alpha.__main__ import _historical_truth_app
from alpha.historical_truth.official_bridge_document_downloader import (
    HTR010B1F_DOWNLOAD_CONTRACT_VERSION,
    OfficialBridgeDocumentDownloader,
)
from alpha.historical_truth.official_bridge_evidence_certification_bundle import (
    HTR010B1F_EVIDENCE_CERTIFICATION_BUNDLE_VERSION,
    OfficialBridgeEvidenceCertificationBundle,
)

_CATALOG = Path(
    "alpha/historical_truth/official_bridge_evidence_source_catalog.json"
)
_DUPLICATED = {"BESTAGRO", "DELPHIFX", "SILVERTUC", "RNBDENIMS"}


def _upstream(path: Path) -> Path:
    catalog = json.loads(_CATALOG.read_text(encoding="utf-8"))
    rows = []
    for source in catalog:
        symbol = source["symbol"]
        repetitions = 2 if symbol in _DUPLICATED else 1
        for offset in range(repetitions):
            cross_series = symbol == "KOTYARK"
            rows.append(
                {
                    "case_id": f"{symbol}-{offset}",
                    "htr010b1d2_contract_version": "HTR-010B1D2-v1.0.0",
                    "effective_date": source["effective_date"],
                    "bridge_type": "CROSS_SERIES" if cross_series else "CROSS_ISIN",
                    "bridge_dependency_state": (
                        "UNCERTIFIED_CROSS_SERIES"
                        if cross_series
                        else "UNCERTIFIED_CROSS_ISIN"
                    ),
                    "prior_isin": source["pre_isin"],
                    "current_isin": source["post_isin"],
                    "prior_symbol": symbol,
                    "current_symbol": symbol,
                    "prior_series": "EQ" if not cross_series else "EQ",
                    "current_series": "EQ" if not cross_series else "BE",
                    "factor_quality_confirmed": True,
                }
            )
    assert len(rows) == 24
    path.mkdir(parents=True)
    (path / "htr010b1d2_reclassified_cases.json").write_text(
        json.dumps(rows), encoding="utf-8"
    )
    return path


def _fake_download(
    self: OfficialBridgeDocumentDownloader,
    *,
    discoveries_path: Path,
    output_root: Path,
) -> dict[str, object]:
    del self
    findings = json.loads(discoveries_path.read_text(encoding="utf-8"))
    downloads = []
    output_root.mkdir(parents=True, exist_ok=True)
    for row in findings:
        role = row["evidence_role"]
        symbol = row["post_symbol"] or row["pre_symbol"]
        if role == "PRE_IDENTITY":
            content = f"{symbol} ISIN {row['pre_isin']}"
        elif role == "POST_IDENTITY":
            content = f"{symbol} ISIN {row['post_isin']}"
        else:
            content = f"{symbol} stock split effective {row['effective_date']}"
        payload = content.encode()
        digest = sha256(payload).hexdigest()
        relative_path = f"{row['dossier_id'].replace(':', '_')}/{role}.html"
        target = output_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        downloads.append(
            {
                "dossier_id": row["dossier_id"],
                "source_url": row["source_url"],
                "final_url": row["source_url"],
                "relative_path": relative_path,
                "source_sha256": digest,
                "file_size_bytes": len(payload),
                "content_type": "text/html",
                "download_state": "DOWNLOADED_VERIFIED_BYTES",
                "error": None,
            }
        )
    return {
        "contract_version": HTR010B1F_DOWNLOAD_CONTRACT_VERSION,
        "input_discovery_count": len(findings),
        "downloaded_document_count": len(downloads),
        "rejected_source_count": 0,
        "failed_download_count": 0,
        "pending_url_count": 0,
        "benchmark_replay_count": 0,
        "production_influence": False,
        "downloads": downloads,
        "report_sha256": "test",
    }


def test_evidence_certification_command_is_registered() -> None:
    app = _historical_truth_app()
    names = {command.name for command in app.registered_commands}
    assert "official-bridge-evidence-certify-all" in names


def test_bundle_certifies_all_semantically_complete_packages(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(OfficialBridgeDocumentDownloader, "run", _fake_download)
    report = OfficialBridgeEvidenceCertificationBundle().run(
        htr010b1d2_output=_upstream(tmp_path / "upstream"),
        source_catalog_path=_CATALOG,
        output=tmp_path / "output",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 20),
    )

    assert report["contract_version"] == (
        HTR010B1F_EVIDENCE_CERTIFICATION_BUNDLE_VERSION
    )
    assert report["input_bridge_case_count"] == 24
    assert report["unique_dossier_count"] == 20
    assert report["complete_source_package_count"] == 19
    assert report["incomplete_source_package_count"] == 1
    assert report["requested_document_count"] == 59
    assert report["downloaded_document_count"] == 59
    assert report["semantically_verified_package_count"] == 19
    assert report["insufficient_semantic_package_count"] == 1
    assert report["covered_bridge_case_count"] == 24
    assert report["certified_continuous_identity_count"] == 23
    assert report["insufficient_official_evidence_count"] == 1
    assert report["implementation_defect_count"] == 0
    assert report["milestone_status"] == "EVIDENCE_GAPS_REMAIN"
    assert "INCOMPLETE_OFFICIAL_SOURCE_PACKAGES" in report["readiness_blockers"]
    assert report["benchmark_replay_count"] == 0
    assert report["production_influence"] is False


def test_cli_rejects_invalid_date_before_network(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        _historical_truth_app(),
        [
            "official-bridge-evidence-certify-all",
            "--htr010b1d2-output",
            str(_upstream(tmp_path / "upstream")),
            "--start",
            "not-a-date",
        ],
    )
    assert result.exit_code != 0
    assert "YYYY-MM-DD" in result.output
