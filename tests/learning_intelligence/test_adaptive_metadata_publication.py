from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from alpha.application.intelligence import IntelligenceApplicationService
from alpha.learning_intelligence.fingerprints import (
    fingerprint_from_ledger_entry,
    fingerprint_from_recommendation,
)
from alpha.learning_intelligence.publication import (
    AdaptiveMetadataPublicationBatch,
    PointInTimeAdaptiveMetadataPublisher,
)
from alpha.performance_intelligence.models import (
    RecommendationOutcome,
    RecommendationOutcomeStatus,
)
from alpha.performance_intelligence.recorder import recommendation_to_ledger_entry


class _ExplodingPublisher:
    def __init__(self) -> None:
        self.calls = 0

    def publish(self, **_: object) -> AdaptiveMetadataPublicationBatch:
        self.calls += 1
        raise AssertionError("disabled publisher must not be called")


def _run() -> object:
    return IntelligenceApplicationService().run(observed_on=date(2026, 1, 10))


def test_default_path_is_identical_and_publisher_is_not_called() -> None:
    baseline = _run()
    publisher = _ExplodingPublisher()
    explicit_disabled = IntelligenceApplicationService(
        adaptive_metadata_publisher=publisher,
        adaptive_metadata_publication_enabled=False,
    ).run(observed_on=date(2026, 1, 10))

    assert explicit_disabled.as_dict() == baseline.as_dict()
    assert publisher.calls == 0


def test_enabled_publication_without_publisher_fails_closed() -> None:
    with pytest.raises(ValueError, match="publisher"):
        IntelligenceApplicationService(
            adaptive_metadata_publication_enabled=True,
        )


def test_point_in_time_publisher_uses_only_strictly_prior_completed_outcome() -> None:
    run = _run()
    recommendation = run.recommendations[0]
    market_regime = run.market_report.bias.value
    observed_on = date(2026, 1, 10)
    entries = tuple(
        recommendation_to_ledger_entry(
            recommendation=recommendation,
            generated_at=datetime(2026, 1, day, tzinfo=UTC),
            source_run_id=f"B9-{label}",
            market_regime=market_regime,
        )
        for day, label in ((1, "eligible"), (2, "same-day"), (3, "pending"))
    )
    outcomes = (
        RecommendationOutcome(
            recommendation_id=entries[0].recommendation_id,
            symbol=entries[0].symbol,
            status=RecommendationOutcomeStatus.EXITED,
            exit_date=date(2026, 1, 9),
            realized_r_multiple=Decimal("1.00"),
            holding_period_days=8,
        ),
        RecommendationOutcome(
            recommendation_id=entries[1].recommendation_id,
            symbol=entries[1].symbol,
            status=RecommendationOutcomeStatus.EXITED,
            exit_date=observed_on,
            realized_r_multiple=Decimal("-1.00"),
            holding_period_days=8,
        ),
        RecommendationOutcome(
            recommendation_id=entries[2].recommendation_id,
            symbol=entries[2].symbol,
            status=RecommendationOutcomeStatus.PENDING,
        ),
    )

    batch = PointInTimeAdaptiveMetadataPublisher(
        entries=entries,
        outcomes=outcomes,
    ).publish(
        recommendations=(recommendation,),
        observed_on=observed_on,
        market_regime=market_regime,
    )

    assert batch.records[0].eligible_completed_sample_count == 1
    assert batch.recommendations[0].metadata["adaptive_sample_count"] == "1"
    assert sum(item.eligible for item in batch.eligibility) == 1
    assert {
        item.reason for item in batch.eligibility if not item.eligible
    } == {
        "SAME_DATE_OR_FUTURE_COMPLETION_EXCLUDED",
        "OUTCOME_NOT_COMPLETED",
    }


def test_opt_in_application_service_publishes_five_field_contract() -> None:
    seed = _run()
    recommendation = seed.recommendations[0]
    market_regime = seed.market_report.bias.value
    entry = recommendation_to_ledger_entry(
        recommendation=recommendation,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_run_id="B9-APPLICATION",
        market_regime=market_regime,
    )
    outcome = RecommendationOutcome(
        recommendation_id=entry.recommendation_id,
        symbol=entry.symbol,
        status=RecommendationOutcomeStatus.EXITED,
        exit_date=date(2026, 1, 9),
        realized_r_multiple=Decimal("1.00"),
        holding_period_days=8,
    )
    publisher = PointInTimeAdaptiveMetadataPublisher(
        entries=(entry,),
        outcomes=(outcome,),
    )

    run = IntelligenceApplicationService(
        adaptive_metadata_publisher=publisher,
        adaptive_metadata_publication_enabled=True,
    ).run(observed_on=date(2026, 1, 10))

    keys = {
        "adaptive_adjusted_confidence",
        "adaptive_evidence_strength",
        "adaptive_posterior_probability",
        "adaptive_expectancy",
        "adaptive_sample_count",
    }
    assert keys <= set(run.recommendations[0].metadata)


def test_future_recorder_snapshot_preserves_full_fingerprint_parity() -> None:
    run = _run()
    recommendation = run.recommendations[0]
    market_regime = run.market_report.bias.value
    entry = recommendation_to_ledger_entry(
        recommendation=recommendation,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_run_id="B9-PARITY",
        market_regime=market_regime,
    )

    expected = fingerprint_from_recommendation(
        recommendation,
        market_regime=market_regime,
    )
    observed = fingerprint_from_ledger_entry(entry)

    assert entry.key_indicator_snapshot["candle_pattern"]
    assert entry.key_indicator_snapshot["retracement_state"]
    assert observed == expected
