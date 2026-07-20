"""Tests for HTR-003 corporate action recovery and replay adjustment."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from alpha.recovery.corporate_actions import (
    CorporateActionAdjustmentEngine,
    CorporateActionBar,
    CorporateActionRecoveryEngine,
    CorporateActionStatus,
    CorporateActionTimeline,
    CorporateActionType,
    export_corporate_action_recovery,
    export_corporate_action_replay_audit,
)
from alpha.recovery.models import RecoveryContext


def _write_actions(tmp_path: Path, records: list[dict[str, object]]) -> Path:
    path = tmp_path / "corporate_actions.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def _run(tmp_path: Path, records: list[dict[str, object]]):
    return CorporateActionRecoveryEngine().run(
        RecoveryContext(
            engine_key="corporate-action-recovery",
            as_of=datetime(2026, 7, 20, tzinfo=UTC),
            parameters={"corporate_actions": _write_actions(tmp_path, records)},
        )
    )


def _split() -> dict[str, object]:
    return {
        "event_id": "SEC-1:SPLIT:2025-01-15",
        "security_id": "SEC-1",
        "symbol": "ALPHA",
        "action_type": "SPLIT",
        "effective_date": "2025-01-15",
        "announced_at": "2024-12-20",
        "ratio_numerator": "2",
        "ratio_denominator": "1",
        "confidence": "0.95",
    }


def _bar(trading_date: date = date(2025, 1, 10)) -> CorporateActionBar:
    return CorporateActionBar(
        security_id="SEC-1",
        symbol="ALPHA",
        trading_date=trading_date,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("104"),
        volume=Decimal("1000"),
    )


def test_recovers_split_with_deterministic_factors(tmp_path: Path) -> None:
    result = _run(tmp_path, [_split()])

    assert result.classification == "PREVIEW_READY"
    row = result.canonical_preview[0].values
    assert row["action_type"] == CorporateActionType.SPLIT.value
    assert row["status"] == CorporateActionStatus.RESOLVED.value
    assert row["price_factor"] == "0.50000000"
    assert row["volume_factor"] == "2.00000000"
    assert result.metadata["resolved_event_count"] == 1


def test_bonus_adjustment_uses_post_bonus_share_multiplier(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [
            {
                **_split(),
                "event_id": "SEC-1:BONUS:2025-01-15",
                "action_type": "BONUS",
                "ratio_numerator": "1",
                "ratio_denominator": "1",
            }
        ],
    )

    row = result.canonical_preview[0].values
    assert row["price_factor"] == "0.50000000"
    assert row["volume_factor"] == "2.00000000"


def test_rights_without_reference_price_remains_unresolved(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [
            {
                **_split(),
                "event_id": "SEC-1:RIGHTS:2025-01-15",
                "action_type": "RIGHTS",
                "ratio_numerator": "1",
                "ratio_denominator": "4",
                "rights_price": "80",
            }
        ],
    )

    assert result.classification == "PREVIEW_WITH_WARNINGS"
    assert result.canonical_preview[0].values["status"] == "UNRESOLVED"
    assert result.metadata["unresolved_event_count"] == 1


def test_cash_dividend_requires_reference_price(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [
            {
                **_split(),
                "event_id": "SEC-1:DIVIDEND:2025-01-15",
                "action_type": "CASH_DIVIDEND",
                "cash_amount": "5",
                "reference_price": "100",
                "ratio_numerator": "",
                "ratio_denominator": "",
            }
        ],
    )

    row = result.canonical_preview[0].values
    assert row["price_factor"] == "0.95000000"
    assert row["volume_factor"] == "1"


def test_adjustment_is_point_in_time_and_backward_only(tmp_path: Path) -> None:
    timeline = CorporateActionTimeline.from_recovery_result(_run(tmp_path, [_split()]))
    engine = CorporateActionAdjustmentEngine(timeline)

    before_announcement = engine.adjust_bar(_bar(), as_of=date(2024, 12, 19))
    after_effective = engine.adjust_bar(_bar(), as_of=date(2025, 1, 15))
    post_action_bar = engine.adjust_bar(
        _bar(date(2025, 1, 15)), as_of=date(2025, 1, 15)
    )

    assert before_announcement.close == Decimal("104.00000000")
    assert before_announcement.applied_event_ids == ()
    assert after_effective.close == Decimal("52.00000000")
    assert after_effective.volume == Decimal("2000.00000000")
    assert after_effective.applied_event_ids == ("SEC-1:SPLIT:2025-01-15",)
    assert post_action_bar.close == Decimal("104.00000000")


def test_multiple_actions_compound_deterministically(tmp_path: Path) -> None:
    bonus = {
        **_split(),
        "event_id": "SEC-1:BONUS:2025-02-15",
        "action_type": "BONUS",
        "effective_date": "2025-02-15",
        "announced_at": "2025-01-20",
        "ratio_numerator": "1",
        "ratio_denominator": "1",
    }
    timeline = CorporateActionTimeline.from_recovery_result(
        _run(tmp_path, [_split(), bonus])
    )
    adjusted = CorporateActionAdjustmentEngine(timeline).adjust_bar(
        _bar(), as_of=date(2025, 2, 15)
    )

    assert adjusted.close == Decimal("26.00000000")
    assert adjusted.volume == Decimal("4000.00000000")
    assert adjusted.cumulative_price_factor == Decimal("0.25000000")


def test_symbol_change_updates_lineage_without_price_change(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [
            {
                "event_id": "SEC-1:SYMBOL:2025-01-15",
                "security_id": "SEC-1",
                "symbol": "NEWALPHA",
                "action_type": "SYMBOL_CHANGE",
                "effective_date": "2025-01-15",
                "announced_at": "2025-01-01",
                "old_symbol": "ALPHA",
                "new_symbol": "NEWALPHA",
            }
        ],
    )
    adjusted = CorporateActionAdjustmentEngine(
        CorporateActionTimeline.from_recovery_result(result)
    ).adjust_bar(_bar(), as_of=date(2025, 1, 15))

    assert adjusted.symbol == "NEWALPHA"
    assert adjusted.close == Decimal("104.00000000")
    assert adjusted.applied_event_ids == ("SEC-1:SYMBOL:2025-01-15",)


def test_replay_audit_fails_when_unresolved_events_exist(tmp_path: Path) -> None:
    records = [
        _split(),
        {
            **_split(),
            "event_id": "SEC-1:RIGHTS:2025-02-15",
            "action_type": "RIGHTS",
            "effective_date": "2025-02-15",
            "announced_at": "2025-01-20",
            "ratio_numerator": "1",
            "ratio_denominator": "4",
            "rights_price": "80",
        },
    ]
    engine = CorporateActionAdjustmentEngine(
        CorporateActionTimeline.from_recovery_result(_run(tmp_path, records))
    )
    audit = engine.audit((_bar(),), as_of=date(2025, 2, 15))

    assert audit.bars_examined == 1
    assert audit.bars_adjusted == 1
    assert audit.events_applied == 1
    assert audit.unresolved_events == 1
    assert not audit.passed


def test_exports_are_deterministic(tmp_path: Path) -> None:
    result = _run(tmp_path, [_split()])
    recovery_paths = export_corporate_action_recovery(result, tmp_path / "recovery")
    audit = CorporateActionAdjustmentEngine(
        CorporateActionTimeline.from_recovery_result(result)
    ).audit((_bar(),), as_of=date(2025, 1, 15))
    audit_paths = export_corporate_action_replay_audit(audit, tmp_path / "audit")

    assert tuple(path.name for path in recovery_paths) == (
        "canonical_timeline.csv",
        "unresolved_events.csv",
        "verification.json",
        "provenance.json",
        "report.md",
    )
    assert tuple(path.name for path in audit_paths) == (
        "replay_audit.json",
        "replay_audit.csv",
        "replay_audit.md",
    )
    assert json.loads(audit_paths[0].read_text(encoding="utf-8"))["passed"] is True
