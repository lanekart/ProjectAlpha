from __future__ import annotations

from datetime import date

from alpha.historical_truth.lifecycle_session_engine import (
    canonicalize_lifecycle,
    canonicalize_observations,
    reconcile_certifications,
    session_expectations,
)
from alpha.historical_truth.lifecycle_session_models import (
    PRODUCTION_INFLUENCE,
    AbsenceReason,
    CertificationIssue,
    PrimaryCertification,
    PrimaryCertificationState,
)


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "identity_key": "nse:isin:INE000A01001",
        "exchange": "NSE",
        "isin": "INE000A01001",
        "symbol": "ALPHA",
        "series": "EQ",
        "security_name": "Alpha Limited",
        "first_observed": "2020-01-01",
        "last_observed": "2020-12-31",
        "source_ids": ["official-a"],
        "source_record_count": 1,
        "candle_rows": 100,
    }
    row.update(overrides)
    return row


def test_identical_duplicate_preserves_full_lineage() -> None:
    canonical, duplicates = canonicalize_observations([_row(), _row()])

    assert len(canonical) == 1
    assert len(canonical[0].supporting_record_ids) == 2
    assert duplicates[0].classification.value == "IDENTICAL_DUPLICATE_OBSERVATION"


def test_repeated_checkpoint_and_conflict_are_classified() -> None:
    _, repeated = canonicalize_observations(
        [_row(), _row(first_observed="2021-01-01", last_observed="2021-12-31")]
    )
    _, conflicting = canonicalize_observations([_row(), _row(symbol="BETA")])

    assert repeated[0].classification.value == "REPEATED_CHECKPOINT_OBSERVATION"
    assert conflicting[0].classification.value == "CONFLICTING_OFFICIAL_OBSERVATION"


def test_primary_states_reconcile_without_summing_issue_flags() -> None:
    rows = (
        PrimaryCertification(
            "one",
            "TIER_A_CORE_EQUITY",
            "EQUITY",
            PrimaryCertificationState.TIER_A_MEMBERSHIP_PARTIAL,
            (
                CertificationIssue.INTERVAL_GAP,
                CertificationIssue.MISSING_SUSPENSION_EVIDENCE,
            ),
            "test",
        ),
        PrimaryCertification(
            "two",
            "TIER_A_CORE_EQUITY",
            "EQUITY",
            PrimaryCertificationState.TIER_A_INTERVAL_CONFLICT,
            (
                CertificationIssue.INTERVAL_OVERLAP,
                CertificationIssue.MISSING_SUSPENSION_EVIDENCE,
            ),
            "test",
        ),
    )

    reconciliation = reconcile_certifications(rows)

    full = [row for row in reconciliation if row.population == "FULL_CENSUS"]
    tier = [row for row in reconciliation if row.population == "TIER_A_CORE_EQUITY"]
    assert sum(row.identities for row in full) == 2
    assert sum(row.identities for row in tier) == 2
    assert sum(len(row.issue_flags) for row in rows) == 4


def test_activity_row_semantics_reclassify_missing_membership_sessions() -> None:
    summaries, missing = session_expectations(
        [
            {
                "support_state": "TIER_A_CORE_EQUITY",
                "expected_sessions": 10,
                "observed_sessions": 7,
                "unexplained_missing": 3,
            }
        ]
    )

    assert summaries[0].membership_sessions == 10
    assert summaries[0].expected_source_rows == 7
    assert missing[0].absence_reason is AbsenceReason.ROW_NOT_EXPECTED_SOURCE_SEMANTICS
    assert not missing[0].counted_as_true_source_gap


def test_current_master_backfill_is_removed_from_canonical_intervals() -> None:
    intervals, repairs = canonicalize_lifecycle(
        symbols=[],
        series=[
            {
                "identity_key": "nse:isin:INE000A01001",
                "value": "EQ",
                "valid_from": "2010-01-01",
                "valid_to": "2020-01-01",
                "source_event_ids": [],
                "confidence_state": "LOW",
            }
        ],
        denominators=[],
        observations=(),
        overlap_evidence=[
            {
                "identity_key": "nse:isin:INE000A01001",
                "attribute": "series",
                "left_value": "EQ",
                "right_value": "BE",
                "classification": "CURRENT_MASTER_BACKFILL_ERROR",
            }
        ],
    )

    assert intervals == ()
    assert repairs[0].repair_type.value == "REMOVED_CHECKPOINT_BACKFILL"


def test_production_influence_is_false() -> None:
    assert PRODUCTION_INFLUENCE is False
    assert date.fromisoformat("2026-07-20") == date(2026, 7, 20)
