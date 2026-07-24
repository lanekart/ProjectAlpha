"""Tests for point-in-time HTR-002 security identity resolution."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from alpha.recovery.models import (
    CanonicalPreviewRow,
    EvidenceGraphSnapshot,
    RecoveryResult,
)
from alpha.recovery.security_timeline import (
    SecurityIdentityRecord,
    SecurityIdentityTimeline,
    normalize_source_security_id,
)


def test_resolves_current_and_historical_symbols_in_effective_window() -> None:
    timeline = SecurityIdentityTimeline(
        (
            SecurityIdentityRecord(
                security_id="SEC-1",
                symbol="NEWALPHA",
                exchange="NSE",
                effective_from=date(2020, 1, 1),
                historical_symbols=("ALPHA",),
            ),
        )
    )

    current = timeline.resolve(
        "newalpha",
        trading_date=date(2025, 1, 10),
        exchange="nse",
    )
    historical = timeline.resolve(
        "ALPHA",
        trading_date=date(2025, 1, 10),
        exchange="NSE",
    )

    assert current is not None
    assert historical is not None
    assert current.security_id == "SEC-1"
    assert historical.symbol == "NEWALPHA"


def test_resolution_is_date_bounded_and_ambiguous_matches_fail_closed() -> None:
    inactive = SecurityIdentityTimeline(
        (
            SecurityIdentityRecord(
                security_id="SEC-1",
                symbol="ALPHA",
                effective_from=date(2025, 1, 1),
            ),
        )
    )
    assert inactive.resolve("ALPHA", trading_date=date(2024, 12, 31)) is None

    ambiguous = SecurityIdentityTimeline(
        (
            SecurityIdentityRecord("SEC-1", "ALPHA"),
            SecurityIdentityRecord("SEC-2", "ALPHA"),
        )
    )
    with pytest.raises(ValueError, match="ambiguous security identity"):
        ambiguous.resolve("ALPHA", trading_date=date(2025, 1, 10))


def test_authoritative_source_id_resolves_observed_interval_gap() -> None:
    timeline = SecurityIdentityTimeline(
        (
            SecurityIdentityRecord(
                security_id="nse:isin:INE000A01001",
                symbol="ALPHA",
                exchange="NSE",
                effective_from=date(2025, 1, 2),
            ),
        )
    )

    assert timeline.resolve("ALPHA", trading_date=date(2025, 1, 1)) is None
    resolved = timeline.resolve_source_identity(
        "ALPHA",
        trading_date=date(2025, 1, 1),
        exchange="NSE",
        isin="INE000A01001",
    )
    unknown = timeline.resolve_source_identity(
        "ALPHA",
        trading_date=date(2025, 1, 1),
        exchange="NSE",
        isin="INE999A01001",
    )

    assert resolved is not None
    assert resolved.security_id == "nse:isin:INE000A01001"
    assert unknown is None
    assert (
        normalize_source_security_id(
            security_id=None,
            isin="ine000a01001",
            exchange="NSE",
        )
        == "nse:isin:INE000A01001"
    )


def test_builds_timeline_from_htr002_recovery_result() -> None:
    preview = CanonicalPreviewRow(
        record_key="SEC-1",
        values={
            "security_id": "SEC-1",
            "symbol": "NEWALPHA",
            "exchange": "NSE",
            "listing_date": "2020-01-01",
            "historical_symbols": '["ALPHA", "OLDALPHA"]',
            "recovery_version": "HTR-002-v1.0.0",
        },
        evidence_ids=("security_master:0",),
    )
    result = RecoveryResult(
        engine_key="security-entity-recovery",
        engine_version="1.0.0",
        generated_at=datetime(2026, 7, 21, tzinfo=UTC),
        classification="PREVIEW_READY",
        discovery={},
        evidence_graph=EvidenceGraphSnapshot(nodes=(), edges=()),
        validation_issues=(),
        normalized=(),
        canonical_preview=(preview,),
        verification_issues=(),
    )

    timeline = SecurityIdentityTimeline.from_recovery_result(result)
    resolved = timeline.resolve("OLDALPHA", trading_date=date(2025, 1, 10))

    assert resolved is not None
    assert resolved.security_id == "SEC-1"
    assert resolved.evidence_ids == ("security_master:0",)
