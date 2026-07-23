from __future__ import annotations

import json
from pathlib import Path

from alpha.historical_replay.governed_artifacts import load_governed_replay_inputs
from alpha.historical_truth.b1_canonical_identity_materializer import (
    B1CanonicalIdentityMaterializer,
)


def _write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_materializes_supported_equity_and_rejects_gs(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "identities.json",
        [
            {
                "identity_key": "nse:isin:INE1",
                "symbol": "AAA",
                "series": "EQ",
                "confidence": "HIGH",
                "admission_status": "GOVERNED_OFFICIAL_VALIDITY_FIELDS",
                "valid_from": "2020-01-01",
                "valid_to": "2026-12-31",
                "source_id": "official-equity",
            },
            {
                "identity_key": "nse:isin:INGOVT",
                "symbol": "GS1",
                "series": "GS",
                "confidence": "HIGH",
                "admission_status": "GOVERNED_OFFICIAL_VALIDITY_FIELDS",
                "valid_from": "2020-01-01",
                "valid_to": "2026-12-31",
                "source_id": "official-gs",
            },
        ],
    )

    report = B1CanonicalIdentityMaterializer().run(
        source_path=source,
        output=tmp_path / "out",
    )

    assert report["materialized_identity_count"] == 1
    assert report["rejected_identity_count"] == 1
    assert report["rejection_reason_counts"] == {"UNSUPPORTED_SERIES": 1}

    identity_path = tmp_path / "out" / "htr010b1_canonical_identity_timeline.json"
    action_path = _write(tmp_path / "actions.json", [])
    inputs = load_governed_replay_inputs(
        identity_path=identity_path,
        corporate_action_path=action_path,
    )
    assert len(inputs.identities.records) == 1
    assert inputs.identities.records[0].security_id == "nse:isin:INE1"


def test_rejects_non_high_confidence_equity(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "identities.json",
        [
            {
                "identity_key": "nse:isin:INE1",
                "symbol": "AAA",
                "series": "EQ",
                "confidence": "MEDIUM",
                "admission_status": "OBSERVED_DATES_ONLY_NOT_CONTINUOUS_VALIDITY",
                "valid_from": "2020-01-01",
                "valid_to": "2026-12-31",
                "source_id": "bhavcopy",
            }
        ],
    )
    report = B1CanonicalIdentityMaterializer().run(
        source_path=source,
        output=tmp_path / "out",
    )
    assert report["materialized_identity_count"] == 0
    assert report["rejection_reason_counts"] == {"CONFIDENCE_NOT_HIGH": 1}
