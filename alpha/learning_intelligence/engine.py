from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType

from alpha.learning_intelligence.fingerprints import fingerprint_from_ledger_entry
from alpha.learning_intelligence.models import (
    AdaptiveLearningAssessment,
    AdaptiveLearningReport,
    BayesianCalibration,
    ConfidenceCalibration,
    EvidenceStrength,
    FeatureContribution,
    FingerprintStatistics,
    LearningOutcomeSample,
    SetupFingerprint,
    average,
    bounded_probability,
    evidence_strength,
    rate,
)
from alpha.performance_intelligence.models import (
    RecommendationLedgerEntry,
    RecommendationOutcome,
    RecommendationOutcomeStatus,
    confidence_bucket,
)


class AdaptiveLearningEngine:
    def __init__(
        self,
        *,
        alpha_prior: Decimal = Decimal("1"),
        beta_prior: Decimal = Decimal("1"),
    ) -> None:
        if alpha_prior <= Decimal("0") or beta_prior <= Decimal("0"):
            raise ValueError("Bayesian priors must be positive")
        self.alpha_prior = alpha_prior
        self.beta_prior = beta_prior

    def build_report(
        self,
        *,
        entries: tuple[RecommendationLedgerEntry, ...],
        outcomes: tuple[RecommendationOutcome, ...],
        historical_samples: tuple[LearningOutcomeSample, ...] = (),
    ) -> AdaptiveLearningReport:
        samples = self._samples_from_ledger(entries=entries, outcomes=outcomes)
        all_samples = samples + historical_samples
        stats = tuple(
            sorted(
                (
                    self._statistics(fingerprint, tuple(grouped))
                    for fingerprint, grouped in _group_by_fingerprint(
                        all_samples
                    ).items()
                ),
                key=lambda item: item.fingerprint.key,
            )
        )
        completed = sum(item.completed_trade_count for item in stats)
        strongest = tuple(
            item
            for item in sorted(
                (stat for stat in stats if stat.expectancy is not None),
                key=lambda stat: (
                    -(stat.expectancy or Decimal("0")),
                    stat.fingerprint.key,
                ),
            )[:5]
        )
        weakest = tuple(
            item
            for item in sorted(
                (stat for stat in stats if stat.expectancy is not None),
                key=lambda stat: (
                    stat.expectancy or Decimal("0"),
                    stat.fingerprint.key,
                ),
            )[:5]
        )
        warnings = tuple(
            f"{stat.fingerprint.key}: {stat.completed_trade_count} completed samples; "
            "insufficient evidence"
            for stat in stats
            if stat.evidence_strength is EvidenceStrength.INSUFFICIENT
        )
        return AdaptiveLearningReport(
            total_completed_samples=completed,
            fingerprint_statistics=stats,
            strongest_fingerprints=strongest,
            weakest_fingerprints=weakest,
            sector_statistics=MappingProxyType(
                self._dimension_statistics(all_samples, "sector")
            ),
            regime_statistics=MappingProxyType(
                self._dimension_statistics(all_samples, "market_regime")
            ),
            confidence_statistics=MappingProxyType(
                self._confidence_statistics(entries=entries, outcomes=outcomes)
            ),
            feature_contributions=self.feature_contributions(all_samples),
            insufficient_sample_warnings=warnings,
        )

    def assess_fingerprint(
        self,
        *,
        fingerprint: SetupFingerprint,
        base_confidence: str,
        entries: tuple[RecommendationLedgerEntry, ...],
        outcomes: tuple[RecommendationOutcome, ...],
    ) -> AdaptiveLearningAssessment:
        samples = tuple(
            sample
            for sample in self._samples_from_ledger(entries=entries, outcomes=outcomes)
            if sample.fingerprint.key == fingerprint.key
        )
        statistics = self._statistics(fingerprint, samples)
        bayesian = self.bayesian_calibration(statistics)
        confidence = self.recalibrate_confidence(
            base_confidence=base_confidence,
            statistics=statistics,
            bayesian=bayesian,
        )
        return AdaptiveLearningAssessment(
            fingerprint=fingerprint,
            statistics=statistics,
            bayesian=bayesian,
            confidence=confidence,
        )

    def bayesian_calibration(
        self,
        statistics: FingerprintStatistics,
    ) -> BayesianCalibration:
        completed = statistics.completed_trade_count
        wins = statistics.win_count
        posterior_alpha = self.alpha_prior + Decimal(wins)
        posterior_beta = self.beta_prior + Decimal(statistics.loss_count)
        total = posterior_alpha + posterior_beta
        posterior = posterior_alpha / total
        prior = self.alpha_prior / (self.alpha_prior + self.beta_prior)
        if completed == 0:
            uncertainty = Decimal("0.50")
        else:
            variance = posterior * (Decimal("1") - posterior) / Decimal(completed + 1)
            uncertainty = min(Decimal("0.50"), variance.sqrt() * Decimal("1.96"))
        return BayesianCalibration(
            prior_win_probability=bounded_probability(prior),
            posterior_win_probability=bounded_probability(posterior),
            lower_confidence_bound=bounded_probability(posterior - uncertainty),
            upper_confidence_bound=bounded_probability(posterior + uncertainty),
            evidence_strength=statistics.evidence_strength,
            completed_samples=completed,
            alpha_prior=self.alpha_prior,
            beta_prior=self.beta_prior,
        )

    def recalibrate_confidence(
        self,
        *,
        base_confidence: str,
        statistics: FingerprintStatistics,
        bayesian: BayesianCalibration,
    ) -> ConfidenceCalibration:
        normalized = base_confidence.strip().upper() or "LOW"
        if statistics.evidence_strength is EvidenceStrength.INSUFFICIENT:
            return ConfidenceCalibration(
                base_confidence=normalized,
                adjusted_confidence=normalized,
                adjustment_reason=(
                    "Confidence unchanged because evidence is insufficient."
                ),
                evidence_sample_count=statistics.completed_trade_count,
                uncertainty_penalty=Decimal("0.20"),
            )
        if statistics.evidence_strength is EvidenceStrength.WEAK:
            if statistics.expectancy is not None and statistics.expectancy < Decimal(
                "0"
            ):
                return _confidence_result(
                    normalized,
                    _lower_confidence(normalized),
                    "Confidence reduced by weak negative evidence.",
                    statistics.completed_trade_count,
                    Decimal("0.10"),
                )
            return _confidence_result(
                normalized,
                normalized,
                "Confidence unchanged because evidence is weak.",
                statistics.completed_trade_count,
                Decimal("0.10"),
            )
        if (
            statistics.evidence_strength is EvidenceStrength.STRONG
            and statistics.expectancy is not None
            and statistics.expectancy < Decimal("0")
        ):
            return _confidence_result(
                normalized,
                _lower_confidence(normalized),
                "Confidence reduced by strong negative empirical evidence.",
                statistics.completed_trade_count,
                Decimal("0.00"),
            )
        if (
            statistics.expectancy is not None
            and statistics.expectancy > Decimal("0")
            and bayesian.posterior_win_probability > Decimal("0.60")
        ):
            return _confidence_result(
                normalized,
                _raise_confidence(normalized),
                "Confidence increased by positive empirical evidence.",
                statistics.completed_trade_count,
                Decimal("0.00"),
            )
        return _confidence_result(
            normalized,
            normalized,
            "Confidence unchanged after empirical calibration.",
            statistics.completed_trade_count,
            Decimal("0.05"),
        )

    def feature_contributions(
        self,
        samples: tuple[LearningOutcomeSample, ...],
    ) -> tuple[FeatureContribution, ...]:
        grouped: dict[tuple[str, str], list[LearningOutcomeSample]] = defaultdict(list)
        for sample in samples:
            if not sample.completed:
                continue
            for dimension, value in sample.fingerprint.dimensions.items():
                grouped[(dimension, value)].append(sample)
        contributions = tuple(
            self._feature_contribution(dimension, value, tuple(group))
            for (dimension, value), group in grouped.items()
        )
        return tuple(
            sorted(
                contributions,
                key=lambda item: (
                    -(item.average_expectancy or Decimal("-999")),
                    item.dimension,
                    item.value,
                ),
            )
        )

    def _samples_from_ledger(
        self,
        *,
        entries: tuple[RecommendationLedgerEntry, ...],
        outcomes: tuple[RecommendationOutcome, ...],
    ) -> tuple[LearningOutcomeSample, ...]:
        outcomes_by_id = {outcome.recommendation_id: outcome for outcome in outcomes}
        samples: list[LearningOutcomeSample] = []
        for entry in entries:
            outcome = outcomes_by_id.get(entry.recommendation_id)
            fingerprint = fingerprint_from_ledger_entry(entry)
            if outcome is None:
                samples.append(
                    LearningOutcomeSample(
                        fingerprint=fingerprint,
                        completed=False,
                        win=False,
                        pending=True,
                        not_triggered=False,
                        target_1_hit=False,
                        target_2_hit=False,
                        target_3_hit=False,
                        stop_hit=False,
                        realized_r=None,
                        holding_period_days=None,
                    )
                )
                continue
            completed = (
                outcome.status
                in {
                    RecommendationOutcomeStatus.EXITED,
                    RecommendationOutcomeStatus.EXPIRED,
                }
                and outcome.realized_r_multiple is not None
            )
            samples.append(
                LearningOutcomeSample(
                    fingerprint=fingerprint,
                    completed=completed,
                    win=bool(
                        completed
                        and outcome.realized_r_multiple is not None
                        and outcome.realized_r_multiple > Decimal("0")
                    ),
                    pending=outcome.status
                    in {
                        RecommendationOutcomeStatus.PENDING,
                        RecommendationOutcomeStatus.ACTIVE,
                    },
                    not_triggered=outcome.status
                    is RecommendationOutcomeStatus.NOT_TRIGGERED,
                    target_1_hit=outcome.target_1_hit,
                    target_2_hit=outcome.target_2_hit,
                    target_3_hit=outcome.target_3_hit,
                    stop_hit=outcome.stop_hit,
                    realized_r=outcome.realized_r_multiple if completed else None,
                    holding_period_days=outcome.holding_period_days
                    if completed
                    else None,
                    max_drawdown_proxy=outcome.maximum_adverse_excursion,
                )
            )
        return tuple(samples)

    def _statistics(
        self,
        fingerprint: SetupFingerprint,
        samples: tuple[LearningOutcomeSample, ...],
    ) -> FingerprintStatistics:
        completed = tuple(sample for sample in samples if sample.completed)
        wins = tuple(sample for sample in completed if sample.win)
        losses = tuple(sample for sample in completed if not sample.win)
        completed_count = len(completed)
        r_values = tuple(sample.realized_r for sample in completed if sample.realized_r)
        holding = tuple(
            Decimal(sample.holding_period_days)
            for sample in completed
            if sample.holding_period_days is not None
        )
        drawdown = tuple(
            sample.max_drawdown_proxy
            for sample in completed
            if sample.max_drawdown_proxy is not None
        )
        return FingerprintStatistics(
            fingerprint=fingerprint,
            sample_count=len(samples),
            completed_trade_count=completed_count,
            win_count=len(wins),
            loss_count=len(losses),
            pending_count=len(tuple(sample for sample in samples if sample.pending)),
            not_triggered_count=len(
                tuple(sample for sample in samples if sample.not_triggered)
            ),
            target_1_hit_rate=rate(
                len(tuple(sample for sample in completed if sample.target_1_hit)),
                completed_count,
            ),
            target_2_hit_rate=rate(
                len(tuple(sample for sample in completed if sample.target_2_hit)),
                completed_count,
            ),
            target_3_hit_rate=rate(
                len(tuple(sample for sample in completed if sample.target_3_hit)),
                completed_count,
            ),
            stop_hit_rate=rate(
                len(tuple(sample for sample in completed if sample.stop_hit)),
                completed_count,
            ),
            average_r=average(r_values),
            expectancy=average(r_values),
            average_holding_period=average(holding),
            max_drawdown_proxy=average(drawdown),
            evidence_strength=evidence_strength(completed_count),
        )

    def _dimension_statistics(
        self,
        samples: tuple[LearningOutcomeSample, ...],
        dimension: str,
    ) -> dict[str, FingerprintStatistics]:
        groups: dict[str, list[LearningOutcomeSample]] = defaultdict(list)
        for sample in samples:
            value = sample.fingerprint.dimensions[dimension]
            groups[value].append(sample)
        return {
            value: self._statistics(
                _aggregate_fingerprint(dimension, value),
                tuple(group),
            )
            for value, group in sorted(groups.items())
        }

    def _confidence_statistics(
        self,
        *,
        entries: tuple[RecommendationLedgerEntry, ...],
        outcomes: tuple[RecommendationOutcome, ...],
    ) -> dict[str, FingerprintStatistics]:
        outcomes_by_id = {outcome.recommendation_id: outcome for outcome in outcomes}
        groups: dict[str, list[LearningOutcomeSample]] = defaultdict(list)
        for entry in entries:
            outcome = outcomes_by_id.get(entry.recommendation_id)
            sample = self._samples_from_ledger(entries=(entry,), outcomes=outcomes)[0]
            if outcome is not None or sample.pending:
                groups[confidence_bucket(entry.confidence)].append(sample)
        return {
            value: self._statistics(
                _aggregate_fingerprint("confidence", value),
                tuple(group),
            )
            for value, group in sorted(groups.items())
        }

    def _feature_contribution(
        self,
        dimension: str,
        value: str,
        samples: tuple[LearningOutcomeSample, ...],
    ) -> FeatureContribution:
        r_values = tuple(sample.realized_r for sample in samples if sample.realized_r)
        average_expectancy = average(r_values)
        return FeatureContribution(
            dimension=dimension,
            value=value,
            sample_count=len(samples),
            average_expectancy=average_expectancy,
            stop_hit_rate=rate(
                len(tuple(sample for sample in samples if sample.stop_hit)),
                len(samples),
            ),
            target_hit_rate=rate(
                len(tuple(sample for sample in samples if sample.target_1_hit)),
                len(samples),
            ),
            direction="higher"
            if average_expectancy is not None and average_expectancy > Decimal("0")
            else "lower",
        )


def _group_by_fingerprint(
    samples: tuple[LearningOutcomeSample, ...],
) -> dict[SetupFingerprint, list[LearningOutcomeSample]]:
    groups: dict[SetupFingerprint, list[LearningOutcomeSample]] = defaultdict(list)
    for sample in samples:
        groups[sample.fingerprint].append(sample)
    return groups


def _aggregate_fingerprint(dimension: str, value: str) -> SetupFingerprint:
    kwargs = {field: "ALL" for field in SetupFingerprint.__dataclass_fields__}
    if dimension in kwargs:
        kwargs[dimension] = value
    return SetupFingerprint(**kwargs)


def _confidence_result(
    base: str,
    adjusted: str,
    reason: str,
    sample_count: int,
    penalty: Decimal,
) -> ConfidenceCalibration:
    return ConfidenceCalibration(
        base_confidence=base,
        adjusted_confidence=adjusted,
        adjustment_reason=reason,
        evidence_sample_count=sample_count,
        uncertainty_penalty=penalty.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
    )


def _lower_confidence(value: str) -> str:
    order = ("LOW", "MEDIUM", "HIGH")
    normalized = "MEDIUM" if value not in order else value
    index = max(0, order.index(normalized) - 1)
    return order[index]


def _raise_confidence(value: str) -> str:
    order = ("LOW", "MEDIUM", "HIGH")
    normalized = "MEDIUM" if value not in order else value
    index = min(len(order) - 1, order.index(normalized) + 1)
    return order[index]


__all__ = ["AdaptiveLearningEngine"]
