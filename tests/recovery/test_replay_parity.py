"""Tests for HTR-004 raw-versus-canonical replay parity diagnostics."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from alpha.recovery.canonical_replay import (
    CanonicalReplayBar,
    CanonicalReplayStatus,
)
from alpha.recovery.replay_parity import (
    ReplayEvaluation,
    ReplayParityAnalyzer,
    export_replay_parity,
)

_REPLAY_DATE = date(2025, 1, 10)
_AS_OF = date(2025, 1, 15)


def _bar(
    *,
    adjusted_close: Decimal = Decimal("104"),
    status: CanonicalReplayStatus = CanonicalReplayStatus.READY,
) -> CanonicalReplayBar:
    unresolved = (
        ("SEC-1:RIGHTS:2025-01-15",)
        if status is CanonicalReplayStatus.QUARANTINED
        else ()
    )
    applied = (
        ("SEC-1:SPLIT:2025-01-15",)
        if adjusted_close != Decimal("104")
        else ()
    )
    factor = adjusted_close / Decimal("104")
    return CanonicalReplayBar(
        security_id="SEC-1",
        raw_symbol="ALPHA",
        canonical_symbol="ALPHA",
        trading_date=_REPLAY_DATE,
        as_of=_AS_OF,
        raw_open=Decimal("100"),
        raw_high=Decimal("110"),
        raw_low=Decimal("90"),
        raw_close=Decimal("104"),
        raw_volume=Decimal("1000"),
        adjusted_open=Decimal("100") * factor,
        adjusted_high=Decimal("110") * factor,
        adjusted_low=Decimal("90") * factor,
        adjusted_close=adjusted_close,
        adjusted_volume=Decimal("1000"),
        cumulative_price_factor=factor,
        cumulative_volume_factor=Decimal("1"),
        applied_event_ids=applied,
        unresolved_event_ids=unresolved,
        status=status,
        recovery_version="HTR-004-v1.0.0",
    )


def _evaluation(signal: str, decision: str) -> ReplayEvaluation:
    return ReplayEvaluation(
        security_id="SEC-1",
        trading_date=_REPLAY_DATE,
        signal=signal,
        decision=decision,
    )


def test_unchanged_outputs_have_full_parity() -> None:
    result = ReplayParityAnalyzer().analyze(
        (_bar(),),
        (_evaluation("BULLISH", "BUY"),),
        (_evaluation("BULLISH", "BUY"),),
    )

    assert result.audit.bars_examined == 1
    assert result.audit.signals_changed == 0
    assert result.audit.decisions_changed == 0
    assert result.audit.signal_parity_percent == Decimal("100.0000")
    assert result.audit.decision_parity_percent == Decimal("100.0000")
    assert result.audit.governed_replay_ready


def test_adjustment_changes_signal_and_decision() -> None:
    result = ReplayParityAnalyzer().analyze(
        (_bar(adjusted_close=Decimal("52")),),
        (_evaluation("BULLISH", "BUY"),),
        (_evaluation("NEUTRAL", "HOLD"),),
    )

    row = result.rows[0]
    assert row.price_changed
    assert row.price_change_percent == Decimal("-50.0000")
    assert row.signal_changed is True
    assert row.decision_changed is True
    assert result.audit.bars_price_changed == 1
    assert result.audit.signals_changed == 1
    assert result.audit.decisions_changed == 1
    assert result.audit.securities_affected == ("SEC-1",)


def test_quarantined_bar_cannot_emit_canonical_decision() -> None:
    result = ReplayParityAnalyzer().analyze(
        (_bar(status=CanonicalReplayStatus.QUARANTINED),),
        (_evaluation("BULLISH", "BUY"),),
        (),
    )

    row = result.rows[0]
    assert row.canonical_signal is None
    assert row.canonical_decision is None
    assert row.signal_changed is None
    assert row.decision_changed is None
    assert result.audit.bars_quarantined == 1
    assert not result.audit.governed_replay_ready


def test_missing_raw_evaluation_fails_closed() -> None:
    with pytest.raises(ValueError, match="raw evaluations must exactly match"):
        ReplayParityAnalyzer().analyze((_bar(),), (), ())


def test_canonical_evaluation_for_quarantined_bar_fails_closed() -> None:
    with pytest.raises(
        ValueError,
        match="canonical evaluations must exactly match replay-ready bars",
    ):
        ReplayParityAnalyzer().analyze(
            (_bar(status=CanonicalReplayStatus.QUARANTINED),),
            (_evaluation("BULLISH", "BUY"),),
            (_evaluation("BULLISH", "BUY"),),
        )


def test_exports_are_deterministic(tmp_path: Path) -> None:
    result = ReplayParityAnalyzer().analyze(
        (_bar(adjusted_close=Decimal("52")),),
        (_evaluation("BULLISH", "BUY"),),
        (_evaluation("NEUTRAL", "HOLD"),),
    )

    paths = export_replay_parity(result, tmp_path)

    assert tuple(path.name for path in paths) == (
        "replay_parity.csv",
        "changed_decisions.csv",
        "replay_parity_audit.json",
        "replay_parity.md",
    )
    audit = json.loads(paths[2].read_text(encoding="utf-8"))
    assert audit["decisions_changed"] == 1
    assert audit["decision_parity_percent"] == "0.0000"
    assert "BUY" in paths[1].read_text(encoding="utf-8")
