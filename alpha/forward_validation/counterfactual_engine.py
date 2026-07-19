from __future__ import annotations

from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal

from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
)
from alpha.forward_validation.approval_gate_optimizer import (
    ApprovalGate,
    ApprovalGateOptimizer,
    primary_window,
    record_reward_risk,
    record_stop_distance,
)
from alpha.forward_validation.models import (
    CounterfactualOperation,
    CounterfactualPolicy,
    PolicyScorecard,
    PolicyStage,
    PolicyVersion,
    ValidationSplit,
)

_TWO = Decimal("0.01")


class CounterfactualPolicyEngine:
    """Generate and validate observed-data policy counterfactuals offline."""

    def __init__(self, gate_optimizer: ApprovalGateOptimizer | None = None) -> None:
        self.gate_optimizer = gate_optimizer or ApprovalGateOptimizer()

    def generate(
        self,
        records: tuple[CandidateDecisionRecord, ...],
    ) -> tuple[CounterfactualPolicy, ...]:
        drafts: list[
            tuple[CounterfactualOperation, tuple[str, ...], str, dict[str, str]]
        ] = []
        for gate in self.gate_optimizer.gates:
            drafts.append(
                (
                    CounterfactualOperation.REMOVE,
                    (gate.gate_id,),
                    f"Remove {gate.label} from the offline policy.",
                    {"disabled_gate": gate.gate_id},
                )
            )
            thresholds = self._empirical_thresholds(gate, records)
            for operation, threshold in thresholds:
                drafts.append(
                    (
                        operation,
                        (gate.gate_id,),
                        f"{operation.value.title()} {gate.label} to the nearest "
                        "observed boundary.",
                        {
                            "gate_id": gate.gate_id,
                            "threshold": str(threshold),
                            "source": "nearest_observed_value",
                        },
                    )
                )
        drafts.extend(
            (
                (
                    CounterfactualOperation.REORDER,
                    tuple(gate.gate_id for gate in reversed(self.gate_optimizer.gates)),
                    "Reverse gate evaluation order; logical acceptance is unchanged.",
                    {"order": "reverse", "logical_policy": "unchanged"},
                ),
                (
                    CounterfactualOperation.MERGE,
                    ("raw_approval", "buy_verdict"),
                    "Merge raw approval and verdict checks into one equivalent gate.",
                    {
                        "merged_gates": "raw_approval,buy_verdict",
                        "logical_policy": "unchanged",
                    },
                ),
                (
                    CounterfactualOperation.REPLACE,
                    ("stop_distance",),
                    "Replace fixed stop distance with ATR-normalized risk only "
                    "when frozen ATR data exists.",
                    {
                        "replacement": "atr_normalized_stop",
                        "supported": "false",
                        "reason": (
                            "candidate ledger does not freeze comparable ATR values"
                        ),
                    },
                ),
            )
        )
        return tuple(
            CounterfactualPolicy(
                policy_version=PolicyVersion(f"APPROVAL_POLICY_V{index}"),
                operation=operation,
                changed_gate_ids=gate_ids,
                description=description,
                parameters=parameters,
            )
            for index, (operation, gate_ids, description, parameters) in enumerate(
                drafts,
                start=2,
            )
        )

    def validate(
        self,
        *,
        candidates: tuple[CounterfactualPolicy, ...],
        records: tuple[CandidateDecisionRecord, ...],
        outcomes: tuple[CandidateForwardOutcome, ...],
    ) -> tuple[CounterfactualPolicy, ...]:
        partitions = _partitions(records)
        outcome_by_id = {outcome.candidate_id: outcome for outcome in outcomes}
        baseline_by_split = {
            split: self._scorecard(
                policy=None,
                split=split,
                records=split_records,
                outcome_by_id=outcome_by_id,
                baseline=None,
            )
            for split, split_records in partitions.items()
        }
        validated: list[CounterfactualPolicy] = []
        for candidate in candidates:
            scorecards: list[PolicyScorecard] = []
            stage = PolicyStage.GENERATED
            for split in (
                ValidationSplit.TRAINING,
                ValidationSplit.VALIDATION,
                ValidationSplit.HOLDOUT,
            ):
                scorecard = self._scorecard(
                    policy=candidate,
                    split=split,
                    records=partitions[split],
                    outcome_by_id=outcome_by_id,
                    baseline=baseline_by_split[split],
                )
                scorecards.append(scorecard)
                if not scorecard.passed_baseline:
                    stage = PolicyStage.REJECTED
                    break
                stage = {
                    ValidationSplit.TRAINING: PolicyStage.TRAINING_PASSED,
                    ValidationSplit.VALIDATION: PolicyStage.VALIDATION_PASSED,
                    ValidationSplit.HOLDOUT: PolicyStage.HOLDOUT_PASSED,
                }[split]
            validated.append(
                replace(candidate, scorecards=tuple(scorecards), stage=stage)
            )
        return tuple(validated)

    def _scorecard(
        self,
        *,
        policy: CounterfactualPolicy | None,
        split: ValidationSplit,
        records: tuple[CandidateDecisionRecord, ...],
        outcome_by_id: dict[str, CandidateForwardOutcome],
        baseline: PolicyScorecard | None,
    ) -> PolicyScorecard:
        resolved = _resolved_rows(records, outcome_by_id)
        approved = tuple(
            (record, window)
            for record, window in resolved
            if self.accepts(record, policy)
        )
        returns = tuple(
            window.forward_return_pct_from_entry
            for _, window in approved
            if window.forward_return_pct_from_entry is not None
        )
        winners = tuple(value for value in returns if value > Decimal("0"))
        losers = tuple(value for value in returns if value <= Decimal("0"))
        precision = _rate(len(winners), len(returns))
        expectancy = _average(returns)
        profit_factor = _profit_factor(winners, losers)
        drawdown = _drawdown_proxy(approved)
        passed, reason = _baseline_dominance(
            sample_count=len(resolved),
            approved_count=len(approved),
            precision=precision,
            expectancy=expectancy,
            drawdown=drawdown,
            baseline=baseline,
            unsupported=(
                policy is not None and policy.parameters.get("supported") == "false"
            ),
        )
        return PolicyScorecard(
            policy_version=(
                policy.policy_version
                if policy is not None
                else PolicyVersion("APPROVAL_POLICY_V1")
            ),
            split=split,
            sample_count=len(resolved),
            approved_count=len(approved),
            profitable_approved_count=len(winners),
            precision_pct=precision,
            recall_pct=_rate(
                len(winners),
                len(
                    tuple(
                        window
                        for _, window in resolved
                        if window.forward_return_pct_from_entry is not None
                        and window.forward_return_pct_from_entry > Decimal("0")
                    )
                ),
            ),
            average_return_pct=expectancy,
            profit_factor=profit_factor,
            maximum_drawdown_proxy_pct=drawdown,
            expectancy_pct=expectancy,
            passed_baseline=passed,
            reason=reason,
        )

    def accepts(
        self,
        record: CandidateDecisionRecord,
        policy: CounterfactualPolicy | None,
    ) -> bool:
        if policy is not None and policy.parameters.get("supported") == "false":
            return False
        disabled = policy.parameters.get("disabled_gate") if policy else None
        threshold_gate = policy.parameters.get("gate_id") if policy else None
        threshold = (
            Decimal(policy.parameters["threshold"])
            if policy is not None and "threshold" in policy.parameters
            else None
        )
        for gate in self.gate_optimizer.gates:
            if gate.gate_id == disabled:
                continue
            if gate.gate_id == threshold_gate and threshold is not None:
                if not _threshold_predicate(record, gate.gate_id, threshold):
                    return False
                continue
            if not gate.predicate(record):
                return False
        return True

    def _empirical_thresholds(
        self,
        gate: ApprovalGate,
        records: tuple[CandidateDecisionRecord, ...],
    ) -> tuple[tuple[CounterfactualOperation, Decimal], ...]:
        if gate.threshold is None:
            return ()
        values = tuple(
            sorted(
                {
                    value
                    for record in records
                    if (value := _gate_value(record, gate.gate_id)) is not None
                }
            )
        )
        if not values:
            return ()
        if gate.gate_id == "stop_distance":
            relaxed = next((value for value in values if value > gate.threshold), None)
            tightened = next(
                (value for value in reversed(values) if value < gate.threshold), None
            )
        else:
            relaxed = next(
                (value for value in reversed(values) if value < gate.threshold), None
            )
            tightened = next(
                (value for value in values if value > gate.threshold), None
            )
        candidates: list[tuple[CounterfactualOperation, Decimal]] = []
        if relaxed is not None:
            candidates.append((CounterfactualOperation.RELAX, relaxed))
        if tightened is not None:
            candidates.append((CounterfactualOperation.TIGHTEN, tightened))
        return tuple(candidates)


def shortlist_validated(
    candidates: tuple[CounterfactualPolicy, ...],
) -> tuple[CounterfactualPolicy, ...]:
    valid = tuple(
        candidate
        for candidate in candidates
        if candidate.stage is PolicyStage.HOLDOUT_PASSED
    )
    ranked = tuple(sorted(valid, key=_ranking_key, reverse=True))
    return tuple(
        replace(
            candidate,
            policy_version=PolicyVersion(f"APPROVAL_POLICY_V{index}"),
        )
        for index, candidate in enumerate(ranked[:2], start=2)
    )


def _resolved_rows(
    records: tuple[CandidateDecisionRecord, ...],
    outcome_by_id: dict[str, CandidateForwardOutcome],
) -> tuple[tuple[CandidateDecisionRecord, CandidateForwardWindowOutcome], ...]:
    rows: list[tuple[CandidateDecisionRecord, CandidateForwardWindowOutcome]] = []
    for record in records:
        window = primary_window(outcome_by_id.get(record.candidate_id))
        if window is None or window.forward_return_pct_from_entry is None:
            continue
        rows.append((record, window))
    return tuple(rows)


def _partitions(
    records: tuple[CandidateDecisionRecord, ...],
) -> dict[ValidationSplit, tuple[CandidateDecisionRecord, ...]]:
    ordered = tuple(
        sorted(
            records,
            key=lambda item: (item.evaluation_date, item.symbol, item.candidate_id),
        )
    )
    total = len(ordered)
    training_end = (total * 60) // 100
    validation_end = (total * 80) // 100
    return {
        ValidationSplit.TRAINING: ordered[:training_end],
        ValidationSplit.VALIDATION: ordered[training_end:validation_end],
        ValidationSplit.HOLDOUT: ordered[validation_end:],
    }


def _threshold_predicate(
    record: CandidateDecisionRecord,
    gate_id: str,
    threshold: Decimal,
) -> bool:
    value = _gate_value(record, gate_id)
    if value is None:
        return gate_id == "minimum_price" and record.entry_zone_high is None
    return value <= threshold if gate_id == "stop_distance" else value >= threshold


def _gate_value(record: CandidateDecisionRecord, gate_id: str) -> Decimal | None:
    if gate_id == "minimum_score":
        return record.strategy_score
    if gate_id == "minimum_price":
        return record.entry_zone_high
    if gate_id == "stop_distance":
        return record_stop_distance(record)
    if gate_id == "reward_risk":
        return record_reward_risk(record)
    return None


def _baseline_dominance(
    *,
    sample_count: int,
    approved_count: int,
    precision: Decimal | None,
    expectancy: Decimal | None,
    drawdown: Decimal | None,
    baseline: PolicyScorecard | None,
    unsupported: bool,
) -> tuple[bool, str]:
    if baseline is None:
        return True, "Current-policy baseline."
    if unsupported:
        return False, "Required frozen input is unavailable."
    if sample_count == 0:
        return False, "No resolved outcomes in this replay split."
    if approved_count == 0:
        return False, "Candidate approves no resolved opportunities."
    comparisons = (
        _not_worse(precision, baseline.precision_pct, higher_is_better=True),
        _not_worse(expectancy, baseline.expectancy_pct, higher_is_better=True),
        _not_worse(
            drawdown,
            baseline.maximum_drawdown_proxy_pct,
            higher_is_better=False,
        ),
    )
    if not all(comparisons):
        return False, "Candidate fails non-degradation against V1 on this split."
    return True, "Candidate weakly dominates V1 on precision, expectancy, and drawdown."


def _not_worse(
    candidate: Decimal | None,
    baseline: Decimal | None,
    *,
    higher_is_better: bool,
) -> bool:
    if candidate is None:
        return False
    if baseline is None:
        return True
    return candidate >= baseline if higher_is_better else candidate <= baseline


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator) * Decimal("100")).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, start=Decimal("0")) / Decimal(len(values))).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )


def _profit_factor(
    winners: tuple[Decimal, ...],
    losers: tuple[Decimal, ...],
) -> Decimal | None:
    gross_loss = abs(sum(losers, start=Decimal("0")))
    if gross_loss == Decimal("0"):
        return None
    return (sum(winners, start=Decimal("0")) / gross_loss).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )


def _drawdown_proxy(
    approved: tuple[tuple[CandidateDecisionRecord, CandidateForwardWindowOutcome], ...],
) -> Decimal | None:
    adverse = tuple(
        abs(window.max_adverse_excursion_pct)
        for _, window in approved
        if window.max_adverse_excursion_pct is not None
    )
    return _average(adverse)


def _ranking_key(
    candidate: CounterfactualPolicy,
) -> tuple[Decimal, Decimal, Decimal, int, int]:
    holdout = next(
        (
            scorecard
            for scorecard in candidate.scorecards
            if scorecard.split is ValidationSplit.HOLDOUT
        ),
        None,
    )
    if holdout is None:
        return (Decimal("-Infinity"),) * 3 + (0, 0)
    operation_preference = {
        CounterfactualOperation.RELAX: 3,
        CounterfactualOperation.TIGHTEN: 2,
        CounterfactualOperation.REMOVE: 1,
    }.get(candidate.operation, 0)
    return (
        holdout.precision_pct or Decimal("-Infinity"),
        holdout.expectancy_pct or Decimal("-Infinity"),
        -(holdout.maximum_drawdown_proxy_pct or Decimal("Infinity")),
        holdout.approved_count,
        operation_preference,
    )


__all__ = ["CounterfactualPolicyEngine", "shortlist_validated"]
