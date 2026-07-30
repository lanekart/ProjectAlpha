from __future__ import annotations

import json
from pathlib import Path

import pytest

from alpha.historical_truth.complete_corporate_action_engine import (
    _apply_upstream_a3_readiness,
    _validated_a3_join_contract,
)
from alpha.historical_truth.complete_corporate_action_models import ReplayReadiness


def _write_a3_contract(
    root: Path,
    joins: list[dict[str, object]],
    *,
    denominator: int,
    admitted: int,
    quarantined: int,
    state: str = "NOT_READY_FOR_HTR_010B",
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "htr010a3_corporate_action_join_readiness.json").write_text(
        json.dumps(joins),
        encoding="utf-8",
    )
    (root / "htr010a3_readiness.json").write_text(
        json.dumps(
            {
                "readiness": {
                    "state": state,
                    "blockers": ["1 unexplained external-era discrepancy"],
                    "denominator_identities": denominator,
                    "admitted_identities": admitted,
                    "quarantined_identities": quarantined,
                },
                "report_sha256": "signed-a3-report",
                "production_influence": False,
            }
        ),
        encoding="utf-8",
    )


def test_dynamic_a3_denominator_accepts_signed_external_era_population(
    tmp_path: Path,
) -> None:
    joins = [
        {"identity_key": "one", "admitted_to_certified_join": True},
        {"identity_key": "two", "admitted_to_certified_join": False},
    ]
    _write_a3_contract(
        tmp_path,
        joins,
        denominator=2,
        admitted=1,
        quarantined=1,
    )

    loaded, readiness = _validated_a3_join_contract(tmp_path)

    assert loaded == joins
    assert readiness["denominator_identities"] == 2
    assert readiness["admitted_identities"] == 1


def test_dynamic_a3_denominator_mismatch_fails_closed(tmp_path: Path) -> None:
    _write_a3_contract(
        tmp_path,
        [{"identity_key": "one", "admitted_to_certified_join": True}],
        denominator=2,
        admitted=1,
        quarantined=1,
    )

    with pytest.raises(ValueError, match="signed denominator"):
        _validated_a3_join_contract(tmp_path)


def test_upstream_not_ready_blocks_adjusted_replay_promotion() -> None:
    result = _apply_upstream_a3_readiness(
        {
            "state": ReplayReadiness.READY_FOR_ADJUSTED_REPLAY_INTEGRATION.value,
            "blockers": [],
        },
        {
            "state": "NOT_READY_FOR_HTR_010B",
            "blockers": ["1 unexplained external-era discrepancy"],
        },
    )

    assert result["state"] == ReplayReadiness.NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION
    assert result["blockers"] == ["HTR-010A3: 1 unexplained external-era discrepancy"]
    assert result["upstream_htr010a3_readiness"] == "NOT_READY_FOR_HTR_010B"
