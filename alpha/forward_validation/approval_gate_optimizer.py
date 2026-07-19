from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
)
from alpha.forward_validation.models import ApprovalGateMetric

if TYPE_CHECKING:
    from collections.abc import Callable


_TWO = Decimal("0.01")
_PRIMARY_WINDOWS = ("20d", "10d", "5d", "3d", "1d", "60d")


@dataclass(frozen=True, slots=True)
class ApprovalGate:
    gate_id: str
    label: str
    predicate: Callable[[CandidateDecisionRecord], bool]
    parameter: str | None = None
    threshold: Decimal | None = None


class ApprovalGateOptimizer:
    """Measure exact V1 approval-gate marginal value without changing policy."""

    @property
    def gates(self) -> tuple[ApprovalGate, ...]:
        return (
            ApprovalGate("raw_approval", "Raw deployment approval", _raw_approval),
            ApprovalGate("buy_verdict", "BUY or STRONG_BUY verdict", _buy_verdict),
            ApprovalGate("high_confidence", "High confidence", _high_confidence),
            ApprovalGate("data_quality", "Complete or good data", _data_quality),
            ApprovalGate(
                "minimum_score",
                "Strategy score at least 85",
                _minimum_score,
                "minimum_score",
                Decimal("85"),
            ),
            ApprovalGate("complete_trade_plan", "Complete trade plan", _complete_plan),
            ApprovalGate(
                "minimum_price",
                "Entry price at least 50",
                _minimum_price,
                "minimum_price",
                Decimal("50"),
            ),
            ApprovalGate(
                "stop_distance",
                "Stop distance at most 10 percent",
                _stop_distance,
                "maximum_stop_distance_pct",
                Decimal("10"),
            ),
            ApprovalGate(
                "reward_risk",
                "Reward/risk at least 2",
                _reward_risk,
                "minimum_reward_risk",
                Decimal("2"),
            ),
        )

    def analyze(
        self,
        *,
        records: tuple[CandidateDecisionRecord, ...],
        outcomes: tuple[CandidateForwardOutcome, ...],
    ) -> tuple[ApprovalGateMetric, ...]:
        outcome_by_id = {outcome.candidate_id: outcome for outcome in outcomes}
        population = tuple(
            (record, primary_window(outcome_by_id.get(record.candidate_id)))
            for record in records
        )
        survivors = population
        metrics: list[ApprovalGateMetric] = []
        for gate in self.gates:
            entering = survivors
            passing = tuple(item for item in entering if gate.predicate(item[0]))
            rejected = tuple(item for item in entering if not gate.predicate(item[0]))
            other_gates = tuple(
                item for item in self.gates if item.gate_id != gate.gate_id
            )
            accepted_without = {
                record.candidate_id
                for record, _ in population
                if all(item.predicate(record) for item in other_gates)
            }
            accepted_with = {
                record.candidate_id
                for record, _ in population
                if all(item.predicate(record) for item in self.gates)
            }
            metrics.append(
                ApprovalGateMetric(
                    gate_id=gate.gate_id,
                    label=gate.label,
                    candidates_entering=len(entering),
                    candidates_passing=len(passing),
                    candidates_rejected=len(rejected),
                    cumulative_survival_pct=_rate(len(passing), len(population)),
                    profitable_rejected_candidates=sum(
                        1 for _, window in rejected if _profitable(window)
                    ),
                    average_return_rejected_pct=_average_return(rejected),
                    average_return_accepted_pct=_average_return(passing),
                    precision_contribution_pct=_difference(
                        _precision(passing), _precision(entering)
                    ),
                    recall_contribution_pct=_difference(
                        _recall(passing, population), _recall(entering, population)
                    ),
                    profit_factor_contribution=_difference(
                        _profit_factor(passing), _profit_factor(entering)
                    ),
                    expectancy_contribution_pct=_difference(
                        _average_return(passing), _average_return(entering)
                    ),
                    drawdown_reduction_pct=_difference(
                        _average_adverse(entering), _average_adverse(passing)
                    ),
                    capital_utilization_impact_pct=_difference(
                        _rate(len(passing), len(population)),
                        _rate(len(entering), len(population)),
                    ),
                    redundant_on_observed_population=accepted_without == accepted_with,
                )
            )
            survivors = passing
        return tuple(metrics)


def primary_window(
    outcome: CandidateForwardOutcome | None,
) -> CandidateForwardWindowOutcome | None:
    if outcome is None:
        return None
    by_label = {window.window: window for window in outcome.windows}
    return next(
        (
            by_label[label]
            for label in _PRIMARY_WINDOWS
            if label in by_label
            and by_label[label].outcome_label is not CandidateOutcomeLabel.DATA_MISSING
        ),
        outcome.windows[0] if outcome.windows else None,
    )


def record_stop_distance(record: CandidateDecisionRecord) -> Decimal | None:
    entry = record.confirmation_entry or record.entry_zone_high
    stop = record.risk_stop
    if entry is None or stop is None or entry <= Decimal("0"):
        return None
    return ((entry - stop) / entry * Decimal("100")).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )


def record_reward_risk(record: CandidateDecisionRecord) -> Decimal | None:
    entry = record.confirmation_entry or record.entry_zone_high
    stop = record.risk_stop
    target = record.target_2 or record.target_1
    if entry is None or stop is None or target is None:
        return None
    risk = entry - stop
    if risk <= Decimal("0"):
        return None
    return ((target - entry) / risk).quantize(_TWO, rounding=ROUND_HALF_UP)


def _raw_approval(record: CandidateDecisionRecord) -> bool:
    return record.approved_for_deployment


def _buy_verdict(record: CandidateDecisionRecord) -> bool:
    return record.final_verdict in {"BUY", "STRONG_BUY"}


def _high_confidence(record: CandidateDecisionRecord) -> bool:
    return record.confidence == "HIGH"


def _data_quality(record: CandidateDecisionRecord) -> bool:
    return record.data_quality in {"COMPLETE", "GOOD"}


def _minimum_score(record: CandidateDecisionRecord) -> bool:
    return record.strategy_score >= Decimal("85")


def _complete_plan(record: CandidateDecisionRecord) -> bool:
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


def _minimum_price(record: CandidateDecisionRecord) -> bool:
    return record.entry_zone_high is None or record.entry_zone_high >= Decimal("50")


def _stop_distance(record: CandidateDecisionRecord) -> bool:
    distance = record_stop_distance(record)
    return distance is not None and distance <= Decimal("10")


def _reward_risk(record: CandidateDecisionRecord) -> bool:
    ratio = record_reward_risk(record)
    return ratio is not None and ratio >= Decimal("2")


def _return(window: CandidateForwardWindowOutcome | None) -> Decimal | None:
    if window is None:
        return None
    return window.forward_return_pct_from_entry


def _profitable(window: CandidateForwardWindowOutcome | None) -> bool:
    value = _return(window)
    return value is not None and value > Decimal("0")


def _resolved(
    rows: tuple[
        tuple[CandidateDecisionRecord, CandidateForwardWindowOutcome | None], ...
    ],
) -> tuple[CandidateForwardWindowOutcome, ...]:
    return tuple(
        window
        for _, window in rows
        if window is not None and window.forward_return_pct_from_entry is not None
    )


def _precision(
    rows: tuple[
        tuple[CandidateDecisionRecord, CandidateForwardWindowOutcome | None], ...
    ],
) -> Decimal | None:
    windows = _resolved(rows)
    return _rate(sum(1 for window in windows if _profitable(window)), len(windows))


def _recall(
    rows: tuple[
        tuple[CandidateDecisionRecord, CandidateForwardWindowOutcome | None], ...
    ],
    population: tuple[
        tuple[CandidateDecisionRecord, CandidateForwardWindowOutcome | None], ...
    ],
) -> Decimal | None:
    profitable_population = sum(1 for _, window in population if _profitable(window))
    return _rate(
        sum(1 for _, window in rows if _profitable(window)), profitable_population
    )


def _average_return(
    rows: tuple[
        tuple[CandidateDecisionRecord, CandidateForwardWindowOutcome | None], ...
    ],
) -> Decimal | None:
    values = tuple(
        value for _, window in rows if (value := _return(window)) is not None
    )
    return _average(values)


def _profit_factor(
    rows: tuple[
        tuple[CandidateDecisionRecord, CandidateForwardWindowOutcome | None], ...
    ],
) -> Decimal | None:
    values = tuple(
        value for _, window in rows if (value := _return(window)) is not None
    )
    losses = abs(sum((value for value in values if value < 0), start=Decimal("0")))
    if losses == Decimal("0"):
        return None
    gains = sum((value for value in values if value > 0), start=Decimal("0"))
    return (gains / losses).quantize(_TWO, rounding=ROUND_HALF_UP)


def _average_adverse(
    rows: tuple[
        tuple[CandidateDecisionRecord, CandidateForwardWindowOutcome | None], ...
    ],
) -> Decimal | None:
    values = tuple(
        abs(window.max_adverse_excursion_pct)
        for _, window in rows
        if window is not None and window.max_adverse_excursion_pct is not None
    )
    return _average(values)


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, start=Decimal("0")) / Decimal(len(values))).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator) * Decimal("100")).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )


def _difference(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return (left - right).quantize(_TWO, rounding=ROUND_HALF_UP)


__all__ = [
    "ApprovalGate",
    "ApprovalGateOptimizer",
    "primary_window",
    "record_reward_risk",
    "record_stop_distance",
]
