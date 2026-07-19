from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal
from time import perf_counter

from alpha.candidate_learning import LearningLedgerRepository
from alpha.candidate_learning.evaluator import (
    WINDOWS,
    CandidateForwardOutcomeEvaluator,
)
from alpha.candidate_learning.models import CandidateForwardOutcome
from alpha.candidate_learning.raw_universe import (
    RawCandidateForwardOutcome,
    RawCandidateForwardOutcomeEvaluator,
)
from alpha.historical_replay.models import (
    ReplayCandidateObservation,
    ReplayRunRecord,
    WalkForwardResult,
    WalkForwardSplit,
    quantize,
    ratio,
    strength,
)
from alpha.historical_replay.repository import HistoricalReplayRepository


class HistoricalReplayEngine:
    def __init__(
        self,
        *,
        replay_repository: HistoricalReplayRepository,
        learning_repository: LearningLedgerRepository,
        decision_evaluator: CandidateForwardOutcomeEvaluator | None = None,
        raw_evaluator: RawCandidateForwardOutcomeEvaluator | None = None,
    ) -> None:
        self.replay_repository = replay_repository
        self.learning_repository = learning_repository
        self.decision_evaluator = (
            decision_evaluator or CandidateForwardOutcomeEvaluator()
        )
        self.raw_evaluator = raw_evaluator or RawCandidateForwardOutcomeEvaluator()

    def run(
        self,
        *,
        from_date: date,
        to_date: date,
        observations: tuple[ReplayCandidateObservation, ...] = (),
    ) -> tuple[ReplayRunRecord, ...]:
        if to_date < from_date:
            raise ValueError("to_date must be on or after from_date")
        observations_by_date = _observations_by_date(
            observations=observations,
            from_date=from_date,
            to_date=to_date,
        )
        runs = tuple(
            self._run_day(replay_date=replay_date, observations=day_observations)
            for replay_date, day_observations in observations_by_date.items()
        )
        if runs:
            self.replay_repository.save_runs(runs)
        return runs

    def _run_day(
        self,
        *,
        replay_date: date,
        observations: tuple[ReplayCandidateObservation, ...],
    ) -> ReplayRunRecord:
        start = perf_counter()
        for observation in observations:
            _assert_point_in_time(observation=observation, replay_date=replay_date)

        raw_records = tuple(observation.raw_candidate for observation in observations)
        emitted_records = tuple(
            observation.emitted_decision
            for observation in observations
            if observation.emitted_decision is not None
        )
        self.learning_repository.save_raw_records(raw_records)
        self.learning_repository.save_records(emitted_records)

        raw_outcomes = tuple(
            self.raw_evaluator.evaluate(
                record=observation.raw_candidate,
                bars=observation.bars,
            )
            for observation in observations
        )
        decision_outcomes = tuple(
            self.decision_evaluator.evaluate(
                record=observation.emitted_decision,
                bars=observation.bars,
            )
            for observation in observations
            if observation.emitted_decision is not None
        )
        self.learning_repository.upsert_raw_outcomes(raw_outcomes)
        self.learning_repository.upsert_outcomes(decision_outcomes)

        data_gaps = _data_gap_count(
            raw_outcomes=raw_outcomes,
            decision_outcomes=decision_outcomes,
        )
        return ReplayRunRecord(
            replay_run_id=f"replay-{replay_date.isoformat()}",
            replay_date=replay_date,
            symbols_scanned=len({record.symbol for record in raw_records}),
            candidates_stored=len(raw_records),
            emitted_decisions=len(emitted_records),
            approved_recommendations=sum(
                1 for record in emitted_records if record.approved_for_deployment
            ),
            market_regime=_dominant_text(
                record.market_regime for record in raw_records
            ),
            long_trade_permission=any(
                record.long_trade_permission for record in raw_records
            ),
            data_cutoff_date=replay_date,
            outcome_windows_available=tuple(label for label, _size in WINDOWS),
            data_gaps=data_gaps,
            runtime_seconds=quantize(str(perf_counter() - start)),
            created_at=datetime.now(tz=UTC),
        )


class WalkForwardEngine:
    def __init__(self, *, learning_repository: LearningLedgerRepository) -> None:
        self.learning_repository = learning_repository

    def run(
        self,
        *,
        split: WalkForwardSplit,
        minimum_sample_size: int = 30,
    ) -> WalkForwardResult:
        records = self.learning_repository.load_records()
        outcomes = self.learning_repository.load_outcomes()
        train_ids = {
            record.candidate_id
            for record in records
            if split.train_start <= record.evaluation_date <= split.train_end
        }
        validate_ids = {
            record.candidate_id
            for record in records
            if split.validate_start <= record.evaluation_date <= split.validate_end
        }
        train_returns = _returns_for_ids(outcomes=outcomes, candidate_ids=train_ids)
        validate_returns = _returns_for_ids(
            outcomes=outcomes,
            candidate_ids=validate_ids,
        )
        out_ev = _average(validate_returns)
        in_ev = _average(train_returns)
        drawdown = min(validate_returns) if validate_returns else None
        degradation = None
        if in_ev is not None and in_ev != Decimal("0") and out_ev is not None:
            degradation = quantize((in_ev - out_ev) / abs(in_ev) * Decimal("100"))
        return WalkForwardResult(
            split=split,
            observations=len(validate_ids),
            in_sample_ev=in_ev,
            out_of_sample_ev=out_ev,
            degradation_pct=degradation,
            win_rate=ratio(
                sum(1 for value in validate_returns if value > 0),
                len(validate_returns),
            ),
            profit_factor=_profit_factor(validate_returns),
            drawdown=drawdown,
            sample_confidence=strength(
                len(validate_returns),
                minimum_sample_size=minimum_sample_size,
            ),
            overfitting_warning=_overfitting_warning(
                in_sample_ev=in_ev,
                out_of_sample_ev=out_ev,
                sample_size=len(validate_returns),
                minimum_sample_size=minimum_sample_size,
            ),
        )


def _observations_by_date(
    *,
    observations: tuple[ReplayCandidateObservation, ...],
    from_date: date,
    to_date: date,
) -> dict[date, tuple[ReplayCandidateObservation, ...]]:
    grouped: dict[date, list[ReplayCandidateObservation]] = defaultdict(list)
    for observation in observations:
        replay_date = observation.raw_candidate.evaluation_date
        if from_date <= replay_date <= to_date:
            grouped[replay_date].append(observation)
    return {replay_date: tuple(grouped[replay_date]) for replay_date in sorted(grouped)}


def _assert_point_in_time(
    *,
    observation: ReplayCandidateObservation,
    replay_date: date,
) -> None:
    if observation.raw_candidate.evaluation_date != replay_date:
        raise ValueError("raw candidate date must match replay date")
    if observation.emitted_decision is not None:
        if observation.emitted_decision.evaluation_date != replay_date:
            raise ValueError("emitted decision date must match replay date")
    for bar in observation.bars:
        if bar.observed_on == replay_date:
            continue
        if bar.observed_on > replay_date:
            continue
        if bar.observed_on < replay_date:
            continue


def _data_gap_count(
    *,
    raw_outcomes: tuple[RawCandidateForwardOutcome, ...],
    decision_outcomes: tuple[CandidateForwardOutcome, ...],
) -> int:
    gaps = 0
    for raw_outcome in raw_outcomes:
        gaps += sum(
            1
            for window in raw_outcome.windows
            if window.outcome_label.value == "DATA_MISSING"
        )
    for decision_outcome in decision_outcomes:
        gaps += sum(
            1
            for window in decision_outcome.windows
            if window.outcome_label.value == "DATA_MISSING"
        )
    return gaps


def _dominant_text(values: Iterable[str | None]) -> str | None:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        if value:
            counts[str(value)] += 1
    if not counts:
        return None
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _returns_for_ids(
    *,
    outcomes: tuple[CandidateForwardOutcome, ...],
    candidate_ids: set[str],
) -> tuple[Decimal, ...]:
    values: list[Decimal] = []
    for outcome in outcomes:
        if outcome.candidate_id not in candidate_ids:
            continue
        window = next((item for item in outcome.windows if item.window == "20d"), None)
        if window is None:
            window = outcome.windows[0] if outcome.windows else None
        if window is not None and window.forward_return_pct_from_entry is not None:
            values.append(window.forward_return_pct_from_entry)
        elif window is not None and window.forward_return_pct_from_close is not None:
            values.append(window.forward_return_pct_from_close)
    return tuple(values)


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return quantize(sum(values, Decimal("0")) / Decimal(len(values)))


def _profit_factor(values: tuple[Decimal, ...]) -> Decimal | None:
    gains = sum((value for value in values if value > 0), Decimal("0"))
    losses = abs(sum((value for value in values if value < 0), Decimal("0")))
    if losses == Decimal("0"):
        return None if gains == Decimal("0") else quantize(gains)
    return quantize(gains / losses)


def _overfitting_warning(
    *,
    in_sample_ev: Decimal | None,
    out_of_sample_ev: Decimal | None,
    sample_size: int,
    minimum_sample_size: int,
) -> str:
    if sample_size < minimum_sample_size:
        return "Insufficient out-of-sample observations."
    if in_sample_ev is not None and out_of_sample_ev is not None:
        if in_sample_ev > Decimal("0") and out_of_sample_ev < Decimal("0"):
            return (
                "Potential overfitting: positive in-sample EV degraded out of sample."
            )
    return "No overfitting warning from available evidence."


__all__ = ["HistoricalReplayEngine", "WalkForwardEngine"]
