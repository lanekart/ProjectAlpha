"""Read-only point-in-time adaptive metadata publication seam.

The publisher in this module is deliberately inert unless injected into an
application service that explicitly enables adaptive metadata publication.  It
never writes to the recommendation ledger and never changes matching or
approval policy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from types import MappingProxyType
from typing import Protocol

from alpha.learning_intelligence.engine import AdaptiveLearningEngine
from alpha.learning_intelligence.fingerprints import fingerprint_from_recommendation
from alpha.performance_intelligence.models import (
    RecommendationLedgerEntry,
    RecommendationOutcome,
    RecommendationOutcomeStatus,
)
from alpha.recommendation_intelligence.models import RecommendationReport

_ADAPTIVE_METADATA_KEYS = (
    "adaptive_adjusted_confidence",
    "adaptive_evidence_strength",
    "adaptive_posterior_probability",
    "adaptive_expectancy",
    "adaptive_sample_count",
)
_COMPLETED_OUTCOME_STATUSES = frozenset(
    {
        RecommendationOutcomeStatus.EXITED,
        RecommendationOutcomeStatus.EXPIRED,
    }
)


@dataclass(frozen=True, slots=True)
class AdaptivePublicationEligibility:
    """One ledger row's eligibility for a recommendation-date assessment."""

    recommendation_symbol: str
    recommendation_observed_on: date
    ledger_recommendation_id: str
    ledger_generated_on: date
    outcome_status: str
    outcome_exit_date: date | None
    fingerprint_match: bool
    eligible: bool
    reason: str


@dataclass(frozen=True, slots=True)
class AdaptiveMetadataPublicationRecord:
    """Auditable publication result for one recommendation."""

    symbol: str
    observed_on: date
    fingerprint_key: str
    eligible_completed_sample_count: int
    posterior_win_probability: str
    expectancy: str
    evidence_strength: str
    adjusted_confidence: str
    published_metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        normalized = dict(sorted(self.published_metadata.items()))
        if tuple(normalized) != tuple(sorted(_ADAPTIVE_METADATA_KEYS)):
            raise ValueError("adaptive publication metadata contract is incomplete")
        object.__setattr__(
            self,
            "published_metadata",
            MappingProxyType(normalized),
        )


@dataclass(frozen=True, slots=True)
class AdaptiveMetadataPublicationBatch:
    """Published recommendations and their immutable diagnostics."""

    recommendations: tuple[RecommendationReport, ...]
    records: tuple[AdaptiveMetadataPublicationRecord, ...]
    eligibility: tuple[AdaptivePublicationEligibility, ...]


class AdaptiveMetadataPublisher(Protocol):
    """Dependency-injection contract for adaptive metadata publication."""

    def publish(
        self,
        *,
        recommendations: tuple[RecommendationReport, ...],
        observed_on: date,
        market_regime: str | None,
    ) -> AdaptiveMetadataPublicationBatch:
        """Return enriched immutable recommendations and diagnostics."""
        ...


class PointInTimeAdaptiveMetadataPublisher:
    """Publish adaptive evidence from immutable, strictly prior ledger outcomes."""

    def __init__(
        self,
        *,
        entries: Sequence[RecommendationLedgerEntry],
        outcomes: Sequence[RecommendationOutcome],
        engine: AdaptiveLearningEngine | None = None,
    ) -> None:
        self._entries = tuple(
            sorted(
                entries,
                key=lambda entry: (
                    entry.generated_at,
                    entry.symbol,
                    entry.recommendation_id,
                ),
            )
        )
        self._outcomes = tuple(
            sorted(
                outcomes,
                key=lambda outcome: (
                    outcome.symbol,
                    outcome.recommendation_id,
                ),
            )
        )
        self._engine = engine or AdaptiveLearningEngine()

    def publish(
        self,
        *,
        recommendations: tuple[RecommendationReport, ...],
        observed_on: date,
        market_regime: str | None,
    ) -> AdaptiveMetadataPublicationBatch:
        outcomes_by_id = {
            outcome.recommendation_id: outcome for outcome in self._outcomes
        }
        enriched: list[RecommendationReport] = []
        records: list[AdaptiveMetadataPublicationRecord] = []
        eligibility: list[AdaptivePublicationEligibility] = []

        for recommendation in recommendations:
            fingerprint = fingerprint_from_recommendation(
                recommendation,
                market_regime=market_regime,
            )
            eligible_entries: list[RecommendationLedgerEntry] = []
            eligible_outcomes: list[RecommendationOutcome] = []

            for entry in self._entries:
                entry_fingerprint = self._entry_fingerprint(entry)
                fingerprint_match = entry_fingerprint == fingerprint.key
                outcome = outcomes_by_id.get(entry.recommendation_id)
                eligible, reason = self._eligibility(
                    entry=entry,
                    outcome=outcome,
                    observed_on=observed_on,
                    fingerprint_match=fingerprint_match,
                )
                eligibility.append(
                    AdaptivePublicationEligibility(
                        recommendation_symbol=recommendation.symbol,
                        recommendation_observed_on=observed_on,
                        ledger_recommendation_id=entry.recommendation_id,
                        ledger_generated_on=entry.generated_at.date(),
                        outcome_status=(
                            "MISSING" if outcome is None else outcome.status.value
                        ),
                        outcome_exit_date=None
                        if outcome is None
                        else outcome.exit_date,
                        fingerprint_match=fingerprint_match,
                        eligible=eligible,
                        reason=reason,
                    )
                )
                if not eligible or outcome is None:
                    continue
                eligible_entries.append(entry)
                eligible_outcomes.append(outcome)

            assessment = self._engine.assess_fingerprint(
                fingerprint=fingerprint,
                base_confidence=recommendation.confidence,
                entries=tuple(eligible_entries),
                outcomes=tuple(eligible_outcomes),
            )
            published = self._metadata(assessment)
            metadata = dict(recommendation.metadata)
            metadata.update(published)
            enriched_recommendation = replace(
                recommendation,
                metadata=metadata,
            )
            enriched.append(enriched_recommendation)
            records.append(
                AdaptiveMetadataPublicationRecord(
                    symbol=recommendation.symbol,
                    observed_on=observed_on,
                    fingerprint_key=fingerprint.key,
                    eligible_completed_sample_count=(
                        assessment.statistics.completed_trade_count
                    ),
                    posterior_win_probability=str(
                        assessment.bayesian.posterior_win_probability
                    ),
                    expectancy=(
                        "unavailable"
                        if assessment.statistics.expectancy is None
                        else str(assessment.statistics.expectancy)
                    ),
                    evidence_strength=assessment.statistics.evidence_strength.value,
                    adjusted_confidence=assessment.confidence.adjusted_confidence,
                    published_metadata=published,
                )
            )

        return AdaptiveMetadataPublicationBatch(
            recommendations=tuple(enriched),
            records=tuple(records),
            eligibility=tuple(eligibility),
        )

    @staticmethod
    def _entry_fingerprint(entry: RecommendationLedgerEntry) -> str:
        from alpha.learning_intelligence.fingerprints import (
            fingerprint_from_ledger_entry,
        )

        return fingerprint_from_ledger_entry(entry).key

    @staticmethod
    def _eligibility(
        *,
        entry: RecommendationLedgerEntry,
        outcome: RecommendationOutcome | None,
        observed_on: date,
        fingerprint_match: bool,
    ) -> tuple[bool, str]:
        if not fingerprint_match:
            return False, "FINGERPRINT_MISMATCH_EXCLUDED"
        if entry.generated_at.date() >= observed_on:
            return False, "SAME_DATE_OR_FUTURE_ENTRY_EXCLUDED"
        if outcome is None:
            return False, "OUTCOME_MISSING"
        if outcome.status not in _COMPLETED_OUTCOME_STATUSES:
            return False, "OUTCOME_NOT_COMPLETED"
        if outcome.realized_r_multiple is None:
            return False, "REALIZED_R_UNAVAILABLE"
        if outcome.exit_date is None:
            return False, "COMPLETION_DATE_UNAVAILABLE"
        if outcome.exit_date >= observed_on:
            return False, "SAME_DATE_OR_FUTURE_COMPLETION_EXCLUDED"
        return True, "ELIGIBLE_PRIOR_COMPLETED_EXACT_FINGERPRINT"

    @staticmethod
    def _metadata(assessment: object) -> dict[str, str]:
        statistics = getattr(assessment, "statistics")
        bayesian = getattr(assessment, "bayesian")
        confidence = getattr(assessment, "confidence")
        expectancy = getattr(statistics, "expectancy")
        return {
            "adaptive_adjusted_confidence": str(
                getattr(confidence, "adjusted_confidence")
            ),
            "adaptive_evidence_strength": str(
                getattr(getattr(statistics, "evidence_strength"), "value")
            ),
            "adaptive_posterior_probability": str(
                getattr(bayesian, "posterior_win_probability")
            ),
            "adaptive_expectancy": (
                "unavailable" if expectancy is None else str(expectancy)
            ),
            "adaptive_sample_count": str(getattr(statistics, "completed_trade_count")),
        }


__all__ = [
    "AdaptiveMetadataPublicationBatch",
    "AdaptiveMetadataPublicationRecord",
    "AdaptiveMetadataPublisher",
    "AdaptivePublicationEligibility",
    "PointInTimeAdaptiveMetadataPublisher",
]
