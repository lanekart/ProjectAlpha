from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from alpha.historical_truth.b1_window_action_admission import (
    B1WindowActionAdmissionEngine,
)
from alpha.historical_truth.b1_window_action_admission_cli import (
    _enrich_rejected_actions,
)


def _write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_quarantines_unresolved_and_unsupported_material_actions(tmp_path: Path) -> None:
    identities = _write(
        tmp_path / "identities.json",
        [
            {
                "security_id": "nse:isin:INE1",
                "symbol": "AAA",
                "effective_from": "2020-01-01",
                "effective_to": "2026-12-31",
            },
            {
                "security_id": "nse:isin:INE2",
                "symbol": "BBB",
                "effective_from": "2020-01-01",
                "effective_to": "2026-12-31",
            },
            {
                "security_id": "nse:isin:INE3",
                "symbol": "CCC",
                "effective_from": "2020-01-01",
                "effective_to": "2026-12-31",
            },
        ],
    )
    actions = _write(
        tmp_path / "actions.json",
        [
            {
                "event_id": "rights-1",
                "security_id": "nse:isin:INE1",
                "symbol": "AAA",
                "action_type": "RIGHTS",
                "effective_date": "2025-01-01",
                "status": "UNRESOLVED",
            },
            {
                "event_id": "split-1",
                "security_id": "nse:isin:INE3",
                "symbol": "CCC",
                "action_type": "SPLIT",
                "effective_date": "2025-01-01",
                "status": "RESOLVED",
            },
        ],
    )
    rejected = _write(
        tmp_path / "rejected.json",
        [
            {
                "action_id": "capital-1",
                "security_id": "nse:isin:INE2",
                "symbol": "BBB",
                "action_type": "CAPITAL_REDUCTION",
                "price_adjustment_required": True,
                "reason": "UNSUPPORTED_HTR005_ACTION_TYPE",
            }
        ],
    )

    report = B1WindowActionAdmissionEngine().run(
        identities_path=identities,
        actions_path=actions,
        rejected_actions_path=rejected,
        replay_start=date(2026, 1, 1),
        replay_end=date(2026, 7, 20),
        warmup_calendar_days=300,
        outcome_calendar_days=90,
        output=tmp_path / "out",
    )

    assert report["admitted_identity_count"] == 1
    assert report["excluded_identity_count"] == 2
    assert report["admitted_unresolved_action_count"] == 0
    assert report["raw_adjusted_universe_difference_count"] == 0
    assert report["shadow_replay_ready"] is True
    raw = json.loads((tmp_path / "out" / "htr010b1h_raw_universe.json").read_text())
    adjusted = json.loads(
        (tmp_path / "out" / "htr010b1h_adjusted_universe.json").read_text()
    )
    assert raw == adjusted == ["nse:isin:INE3"]


def test_symbol_only_material_rejection_requires_unique_identity(tmp_path: Path) -> None:
    identities = _write(
        tmp_path / "identities.json",
        [
            {"security_id": "nse:isin:INE1", "symbol": "AAA"},
            {"security_id": "nse:isin:INE2", "symbol": "AAA"},
        ],
    )
    rejected = _write(
        tmp_path / "rejected.json",
        [
            {
                "action_id": "capital-1",
                "symbol": "AAA",
                "price_adjustment_required": True,
            }
        ],
    )

    with pytest.raises(ValueError, match="unique identity resolution"):
        _enrich_rejected_actions(
            identities_path=identities,
            rejected_path=rejected,
            output_path=tmp_path / "enriched.json",
        )
