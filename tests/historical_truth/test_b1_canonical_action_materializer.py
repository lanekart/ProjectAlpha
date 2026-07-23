from __future__ import annotations

import json
from pathlib import Path

from alpha.historical_truth.b1_canonical_action_materializer import (
    B1CanonicalActionMaterializer,
)


def _write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_materializes_resolved_split_and_unresolved_rights(tmp_path: Path) -> None:
    identity = _write(
        tmp_path / "identity.json",
        [
            {
                "security_id": "nse:isin:INE1",
                "symbol": "AAA",
                "exchange": "NSE",
            }
        ],
    )
    source = _write(
        tmp_path / "actions.json",
        [
            {
                "action_id": "split-1",
                "action_type": "SPLIT",
                "adjustment_factor": 0.5,
                "adjustment_factor_state": "DERIVED_FROM_OFFICIAL_TERMS",
                "admission_state": "ADMITTED",
                "confidence_state": "HIGH",
                "effective_date": "2026-01-02",
                "governed_identity_id": "nse:isin:INE1",
                "symbol": "AAA",
                "price_adjustment_required": True,
                "source_id": "official",
            },
            {
                "action_id": "rights-1",
                "action_type": "RIGHTS",
                "adjustment_factor": None,
                "adjustment_factor_state": "UNKNOWN",
                "admission_state": "ADMITTED",
                "confidence_state": "HIGH",
                "effective_date": "2026-01-03",
                "governed_identity_id": "nse:isin:INE1",
                "symbol": "AAA",
                "price_adjustment_required": True,
                "source_id": "official",
            },
        ],
    )

    report = B1CanonicalActionMaterializer().run(
        source_path=source,
        identity_path=identity,
        output=tmp_path / "out",
    )

    assert report["htr005_contract_loadable"] is True
    assert report["resolved_event_count"] == 1
    assert report["unresolved_event_count"] == 1
    assert report["shadow_replay_safe"] is False

    timeline = json.loads(
        (tmp_path / "out" / "htr010b1_canonical_action_timeline.json").read_text()
    )
    split = next(row for row in timeline if row["event_id"] == "split-1")
    rights = next(row for row in timeline if row["event_id"] == "rights-1")
    assert split["price_factor"] == "0.5"
    assert split["volume_factor"] == "2"
    assert split["status"] == "RESOLVED"
    assert rights["status"] == "UNRESOLVED"


def test_rejected_material_scheme_blocks_shadow_safety(tmp_path: Path) -> None:
    identity = _write(
        tmp_path / "identity.json",
        [{"security_id": "nse:isin:INE1", "symbol": "AAA"}],
    )
    source = _write(
        tmp_path / "actions.json",
        [
            {
                "action_id": "scheme-1",
                "action_type": "SCHEME_OF_ARRANGEMENT",
                "admission_state": "ADMITTED",
                "confidence_state": "HIGH",
                "effective_date": "2026-01-02",
                "governed_identity_id": "nse:isin:INE1",
                "symbol": "AAA",
                "price_adjustment_required": True,
            }
        ],
    )

    report = B1CanonicalActionMaterializer().run(
        source_path=source,
        identity_path=identity,
        output=tmp_path / "out",
    )

    assert report["materialized_event_count"] == 0
    assert report["material_rejected_row_count"] == 1
    assert report["shadow_replay_safe"] is False
