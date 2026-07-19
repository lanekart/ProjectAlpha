from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from alpha.data_platform import ConfidenceEngine, ConfidenceEvidence, ConfidenceLevel
from alpha.data_platform.models import (
    CanonicalObservation,
    ReconciliationIssueType,
    ReconciliationSource,
)
from alpha.data_platform.reconciliation import ReconciliationEngine


def test_confidence_engine_is_bounded_and_fail_closed() -> None:
    engine = ConfidenceEngine()
    strong = engine.assess(
        ConfidenceEvidence(
            source_official=True,
            reconciled=True,
            completeness=Decimal("1"),
            corporate_actions_complete=True,
            identity_certainty=Decimal("1"),
            conflict_count=0,
            unknown_field_count=0,
        )
    )
    conflicted = engine.assess(
        ConfidenceEvidence(
            source_official=True,
            reconciled=True,
            completeness=Decimal("1"),
            corporate_actions_complete=True,
            identity_certainty=Decimal("1"),
            conflict_count=1,
            unknown_field_count=0,
        )
    )
    incomplete = engine.assess(
        ConfidenceEvidence(
            source_official=False,
            reconciled=False,
            completeness=Decimal("1"),
            corporate_actions_complete=True,
            identity_certainty=Decimal("1"),
            conflict_count=0,
            unknown_field_count=1,
        )
    )
    assert strong.level is ConfidenceLevel.HIGH
    assert conflicted.level is ConfidenceLevel.LOW
    assert conflicted.capped
    assert incomplete.level is not ConfidenceLevel.HIGH


def test_reconciliation_reports_conflicts_without_overwrite(
    canonical_observation: CanonicalObservation,
) -> None:
    bse = replace(
        canonical_observation,
        observation_id="obs-2",
        source="BSE",
        fields={
            **canonical_observation.fields,
            "security_id": "BSE-OTHER",
            "close": Decimal("101"),
            "volume": Decimal("1100"),
        },
    )
    report = ReconciliationEngine().reconcile(
        (
            ReconciliationSource("NSE", (canonical_observation,)),
            ReconciliationSource("BSE", (bse,)),
        ),
        expected_sessions=(date(2020, 1, 2), date(2020, 1, 3)),
    )
    issue_types = {item.issue_type for item in report.issues}
    assert ReconciliationIssueType.PRICE_MISMATCH in issue_types
    assert ReconciliationIssueType.VOLUME_MISMATCH in issue_types
    assert ReconciliationIssueType.IDENTITY_MISMATCH in issue_types
    assert ReconciliationIssueType.MISSING_SESSION in issue_types
    assert report.automatic_overwrites == 0
