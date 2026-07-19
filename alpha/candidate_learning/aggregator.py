from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from alpha.candidate_learning.models import (
    CandidateDecisionClassification,
    CandidateDecisionQualitySummary,
    CandidateDecisionRecord,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
    LearningSummary,
    rate,
)

_ZERO = Decimal("0")
_TWO = Decimal("0.01")
_MIN_DEPLOYMENT_SCORE = Decimal("85")
_MAX_DEPLOYMENT_STOP_DISTANCE = Decimal("10")
_MIN_DEPLOYMENT_PRICE = Decimal("50")


class LearningSummaryAggregator:
    def __init__(self, *, minimum_sample_size: int = 30) -> None:
        if minimum_sample_size <= 0:
            raise ValueError("minimum_sample_size must be positive")
        self.minimum_sample_size = minimum_sample_size

    def summarize(
        self,
        *,
        records: tuple[CandidateDecisionRecord, ...],
        outcomes: tuple[CandidateForwardOutcome, ...],
        period: str = "lifetime",
    ) -> LearningSummary:
        outcome_by_id = {outcome.candidate_id: outcome for outcome in outcomes}
        classified = tuple(
            (
                record,
                _primary_window(outcome_by_id.get(record.candidate_id)),
            )
            for record in records
        )
        classifications = tuple(
            _classification(record, window) for record, window in classified
        )
        false_positives = classifications.count(
            CandidateDecisionClassification.FALSE_POSITIVE
        )
        false_negatives = classifications.count(
            CandidateDecisionClassification.FALSE_NEGATIVE
        )
        correct_approvals = classifications.count(
            CandidateDecisionClassification.CORRECT_APPROVAL
        )
        correct_rejects = classifications.count(
            CandidateDecisionClassification.CORRECT_REJECT
        )
        approved_count = sum(1 for record in records if is_deployment_approved(record))
        rejected_count = sum(
            1
            for record in records
            if not is_deployment_approved(record)
            and record.final_verdict not in {"WATCHLIST", "AVOID", "SELL"}
        )
        watchlist_count = sum(
            1 for record in records if record.final_verdict == "WATCHLIST"
        )
        avoid_count = sum(1 for record in records if record.final_verdict == "AVOID")
        sell_count = sum(1 for record in records if record.final_verdict == "SELL")
        completed_windows = sum(
            1
            for _, window in classified
            if window is not None
            and window.outcome_label is not CandidateOutcomeLabel.DATA_MISSING
        )
        quality = CandidateDecisionQualitySummary(
            false_positive_count=false_positives,
            false_negative_count=false_negatives,
            correct_approval_count=correct_approvals,
            correct_reject_count=correct_rejects,
            approval_precision=rate(
                correct_approvals,
                correct_approvals + false_positives,
            ),
            rejection_accuracy=rate(correct_rejects, correct_rejects + false_negatives),
            missed_opportunity_rate=rate(
                false_negatives,
                len(records) - approved_count,
            ),
            avoid_success_rate=rate(
                sum(
                    1
                    for record, window in classified
                    if record.final_verdict == "AVOID"
                    and window is not None
                    and window.outcome_label is CandidateOutcomeLabel.WOULD_HAVE_LOST
                ),
                avoid_count,
            ),
            watchlist_conversion_quality=rate(
                sum(
                    1
                    for record, window in classified
                    if record.final_verdict == "WATCHLIST"
                    and window is not None
                    and window.outcome_label is CandidateOutcomeLabel.WOULD_HAVE_WON
                ),
                watchlist_count,
            ),
        )
        return LearningSummary(
            period=period,
            generated_at=datetime.now(tz=UTC),
            total_candidates_evaluated=len(records),
            approved_count=approved_count,
            rejected_count=rejected_count,
            watchlist_count=watchlist_count,
            avoid_count=avoid_count,
            sell_count=sell_count,
            completed_forward_windows=completed_windows,
            quality=quality,
            best_indicator_combinations=_rank_grouped(classified, _indicator_key)[:5],
            worst_indicator_combinations=_rank_grouped(classified, _indicator_key)[-5:],
            best_setup_regime_combinations=_rank_grouped(classified, _setup_regime_key)[
                :5
            ],
            worst_setup_regime_combinations=_rank_grouped(
                classified,
                _setup_regime_key,
            )[-5:],
            data_gaps=sum(
                1
                for _, window in classified
                if window is None
                or window.outcome_label is CandidateOutcomeLabel.DATA_MISSING
            ),
            sufficient_sample=completed_windows >= self.minimum_sample_size,
        )


def _classification(
    record: CandidateDecisionRecord,
    window: CandidateForwardWindowOutcome | None,
) -> CandidateDecisionClassification:
    if window is None or window.outcome_label is CandidateOutcomeLabel.DATA_MISSING:
        return CandidateDecisionClassification.UNRESOLVED
    approved = is_deployment_approved(record)
    won = window.outcome_label is CandidateOutcomeLabel.WOULD_HAVE_WON
    lost = window.outcome_label is CandidateOutcomeLabel.WOULD_HAVE_LOST
    if approved and lost:
        return CandidateDecisionClassification.FALSE_POSITIVE
    if approved and won:
        return CandidateDecisionClassification.CORRECT_APPROVAL
    if not approved and won:
        return CandidateDecisionClassification.FALSE_NEGATIVE
    if not approved and lost:
        return CandidateDecisionClassification.CORRECT_REJECT
    return CandidateDecisionClassification.UNRESOLVED


def is_deployment_approved(record: CandidateDecisionRecord) -> bool:
    if not record.approved_for_deployment:
        return False
    if record.final_verdict not in {"BUY", "STRONG_BUY"}:
        return False
    if record.confidence != "HIGH":
        return False
    if record.data_quality not in {"COMPLETE", "GOOD"}:
        return False
    if record.strategy_score < _MIN_DEPLOYMENT_SCORE:
        return False
    if not _has_complete_trade_plan(record):
        return False
    if (
        record.entry_zone_high is not None
        and record.entry_zone_high < _MIN_DEPLOYMENT_PRICE
    ):
        return False
    stop_distance = _record_stop_distance(record)
    if stop_distance is None or stop_distance > _MAX_DEPLOYMENT_STOP_DISTANCE:
        return False
    reward_risk = _record_reward_risk(record)
    return reward_risk is not None and reward_risk >= Decimal("2")


def _has_complete_trade_plan(record: CandidateDecisionRecord) -> bool:
    return all(
        value is not None
        for value in (
            record.entry_zone_high,
            record.confirmation_entry,
            record.risk_stop,
            record.target_1,
            record.target_2,
            record.target_3,
            record.trailing_stop_plan,
        )
    )


def _record_reward_risk(record: CandidateDecisionRecord) -> Decimal | None:
    entry = record.confirmation_entry or record.entry_zone_high
    stop = record.risk_stop
    target = record.target_2 or record.target_1
    if entry is None or stop is None or target is None:
        return None
    risk = entry - stop
    if risk <= Decimal("0"):
        return None
    return ((target - entry) / risk).quantize(_TWO, rounding=ROUND_HALF_UP)


def _record_stop_distance(record: CandidateDecisionRecord) -> Decimal | None:
    entry = record.confirmation_entry or record.entry_zone_high
    stop = record.risk_stop
    if entry is None or stop is None or entry <= Decimal("0"):
        return None
    return ((entry - stop) / entry * Decimal("100")).quantize(
        _TWO,
        rounding=ROUND_HALF_UP,
    )


def _primary_window(
    outcome: CandidateForwardOutcome | None,
) -> CandidateForwardWindowOutcome | None:
    if outcome is None:
        return None
    preferred = ("20d", "10d", "5d", "3d", "1d", "60d")
    by_window = {window.window: window for window in outcome.windows}
    return next(
        (
            by_window[label]
            for label in preferred
            if label in by_window
            and by_window[label].outcome_label is not CandidateOutcomeLabel.DATA_MISSING
        ),
        outcome.windows[0] if outcome.windows else None,
    )


def _rank_grouped(
    classified: tuple[
        tuple[CandidateDecisionRecord, CandidateForwardWindowOutcome | None], ...
    ],
    key_fn: Callable[[CandidateDecisionRecord], str],
) -> tuple[tuple[str, Decimal], ...]:
    groups: dict[str, list[Decimal]] = defaultdict(list)
    for record, window in classified:
        if window is None or window.forward_return_pct_from_entry is None:
            continue
        groups[key_fn(record)].append(window.forward_return_pct_from_entry)
    ranked = tuple(
        sorted(
            (
                (
                    key,
                    (sum(values, _ZERO) / Decimal(len(values))).quantize(
                        _TWO,
                        rounding=ROUND_HALF_UP,
                    ),
                )
                for key, values in groups.items()
                if values
            ),
            key=lambda item: (item[1], item[0]),
            reverse=True,
        )
    )
    return ranked


def _indicator_key(record: CandidateDecisionRecord) -> str:
    return " + ".join(record.indicators_active) or "unknown"


def _setup_regime_key(record: CandidateDecisionRecord) -> str:
    return f"{record.setup_type or 'UNKNOWN'} / {record.market_regime or 'UNKNOWN'}"


__all__ = ["LearningSummaryAggregator", "is_deployment_approved"]
