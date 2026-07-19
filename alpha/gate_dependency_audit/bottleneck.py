from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from alpha.gate_dependency_audit.gate_sequence import (
    CORE_GATE_SEQUENCE,
    FULL_GATE_SEQUENCE,
)
from alpha.gate_dependency_audit.models import (
    BottleneckSummary,
    CandidateGateLineage,
    EvidenceConfidence,
    FirstFailureStatistic,
    GateGrade,
    GatePathStatistic,
    GateReportCard,
    GateStatus,
    GateSurvivalStatistic,
    InteractionCell,
    MarginalGateValue,
)

_ZERO = Decimal("0")
_TWO = Decimal("0.01")


def first_failure_statistics(
    lineages: tuple[CandidateGateLineage, ...],
) -> tuple[FirstFailureStatistic, ...]:
    criterion: dict[tuple[str, str], list[CandidateGateLineage]] = defaultdict(list)
    group: dict[tuple[str, str], list[CandidateGateLineage]] = defaultdict(list)
    for item in lineages:
        if item.first_failed_gate is not None and item.first_failed_group is not None:
            criterion[(item.first_failed_gate, item.first_failed_group.value)].append(
                item
            )
            group[
                (item.first_failed_group.value, item.first_failed_group.value)
            ].append(item)
    rows = [
        _first_failure_row(
            scope="CRITERION",
            gate_id=gate_id,
            gate_group=gate_group,
            values=tuple(values),
            population=len(lineages),
        )
        for (gate_id, gate_group), values in criterion.items()
    ]
    rows.extend(
        _first_failure_row(
            scope="GROUP",
            gate_id=gate_id,
            gate_group=gate_group,
            values=tuple(values),
            population=len(lineages),
        )
        for (gate_id, gate_group), values in group.items()
    )
    return tuple(
        sorted(
            rows,
            key=lambda item: (
                0 if item.scope == "CRITERION" else 1,
                -item.candidates,
                item.gate_id,
            ),
        )
    )


def sequential_survival(
    lineages: tuple[CandidateGateLineage, ...],
) -> tuple[GateSurvivalStatistic, ...]:
    population = len(lineages)
    rows: list[GateSurvivalStatistic] = []
    for gate in FULL_GATE_SEQUENCE:
        steps = tuple(
            next(step for step in item.lineage if step.gate_id == gate.gate_id)
            for item in lineages
        )
        entered = sum(
            step.sequential_status is not GateStatus.NOT_REACHED for step in steps
        )
        rejected = sum(step.sequential_status is GateStatus.FAIL for step in steps)
        passed = sum(
            step.sequential_status in {GateStatus.PASS, GateStatus.NOT_APPLICABLE}
            for step in steps
        )
        rows.append(
            GateSurvivalStatistic(
                gate_id=gate.gate_id,
                display_name=gate.display_name,
                gate_group=gate.group,
                sequence=gate.sequence,
                entered_stage=entered,
                passed=passed,
                rejected=rejected,
                not_reached=population - entered,
                pass_percent=_rate(passed, entered),
                reject_percent=_rate(rejected, entered),
                cumulative_survival_percent=_rate(passed, population) or _ZERO,
            )
        )
    return tuple(rows)


def path_statistics(
    lineages: tuple[CandidateGateLineage, ...],
    *,
    outcome_classification: str,
) -> tuple[GatePathStatistic, ...]:
    grouped: dict[str, list[CandidateGateLineage]] = defaultdict(list)
    for item in lineages:
        if item.outcome_classification == outcome_classification:
            grouped[" > ".join(item.failed_gates) or "NO_FAILURE"].append(item)
    return tuple(
        GatePathStatistic(
            outcome_classification=outcome_classification,
            failure_path=path,
            candidates=len(values),
            average_return_percent=_mean_return(tuple(values)),
            representative_symbols=tuple(sorted({item.symbol for item in values})[:5]),
        )
        for path, values in sorted(
            grouped.items(), key=lambda item: (-len(item[1]), item[0])
        )
    )


def gate_report_cards(
    lineages: tuple[CandidateGateLineage, ...],
    *,
    marginal_values: tuple[MarginalGateValue, ...],
    initial_capital: Decimal,
) -> tuple[GateReportCard, ...]:
    evaluable = tuple(
        item
        for item in lineages
        if item.outcome_classification in {"CORRECT_REJECTION", "FALSE_REJECTION"}
    )
    total_false = sum(
        item.outcome_classification == "FALSE_REJECTION" for item in evaluable
    )
    notional = initial_capital / Decimal(len(lineages)) if lineages else _ZERO
    marginal = {item.gate_id: item for item in marginal_values}
    cards: list[GateReportCard] = []
    for gate in FULL_GATE_SEQUENCE:
        if gate.gate_id == "INSTITUTIONAL_DECISION":
            failed = lineages
        elif gate.gate_id == "PORTFOLIO_ALLOCATION":
            failed = ()
        else:
            failed = tuple(
                item for item in lineages if gate.gate_id in item.failed_gates
            )
        failed_ids = {item.candidate_id for item in failed}
        true_positive = sum(
            item.candidate_id in failed_ids
            and item.outcome_classification == "CORRECT_REJECTION"
            for item in evaluable
        )
        false_positive = sum(
            item.candidate_id in failed_ids
            and item.outcome_classification == "FALSE_REJECTION"
            for item in evaluable
        )
        true_negative = sum(
            item.candidate_id not in failed_ids
            and item.outcome_classification == "FALSE_REJECTION"
            for item in evaluable
        )
        accuracy = _rate(true_positive + true_negative, len(evaluable))
        precision = _rate(true_positive, true_positive + false_positive)
        protection = _economic_value(
            tuple(
                item
                for item in failed
                if item.outcome_classification == "CORRECT_REJECTION"
            ),
            notional,
            positive=False,
        )
        opportunity = _economic_value(
            tuple(
                item
                for item in failed
                if item.outcome_classification == "FALSE_REJECTION"
            ),
            notional,
            positive=True,
        )
        marginal_row = marginal.get(gate.gate_id)
        incremental_survivors = (
            0 if marginal_row is None else marginal_row.additional_survivors_if_removed
        )
        incremental_value = (
            _ZERO if marginal_row is None else marginal_row.net_capital_protection
        )
        confidence = _confidence(true_positive + false_positive)
        grade = _grade(
            gate_id=gate.gate_id,
            resolved_failures=true_positive + false_positive,
            precision=precision,
            incremental_survivors=incremental_survivors,
            incremental_value=incremental_value,
        )
        cards.append(
            GateReportCard(
                gate_id=gate.gate_id,
                display_name=gate.display_name,
                gate_group=gate.group,
                failures=len(failed),
                evaluable_population=len(evaluable),
                correct_rejections=true_positive,
                false_rejections=false_positive,
                accuracy_percent=accuracy,
                rejection_precision_percent=precision,
                incremental_survivors=incremental_survivors,
                incremental_value=incremental_value,
                false_rejection_contribution_percent=_rate(false_positive, total_false),
                capital_protection=protection,
                opportunity_cost=opportunity,
                confidence=confidence,
                grade=grade,
                explanation=_card_explanation(
                    failures=len(failed),
                    precision=precision,
                    incremental_survivors=incremental_survivors,
                    incremental_value=incremental_value,
                ),
            )
        )
    return tuple(cards)


def bottleneck_summary(
    *,
    first_failures: tuple[FirstFailureStatistic, ...],
    report_cards: tuple[GateReportCard, ...],
    interactions: tuple[InteractionCell, ...],
    marginal_values: tuple[MarginalGateValue, ...],
) -> BottleneckSummary:
    criterion_failures = tuple(
        item for item in first_failures if item.scope == "CRITERION"
    )
    largest = max(criterion_failures, key=lambda item: item.candidates)
    sequential_false = max(
        criterion_failures,
        key=lambda item: (item.false_rejections, item.candidates),
    )
    core_gate_ids = {gate.gate_id for gate in CORE_GATE_SEQUENCE}
    core_cards = tuple(item for item in report_cards if item.gate_id in core_gate_ids)
    false_card = max(
        core_cards,
        key=lambda item: (
            item.false_rejections,
            item.failures,
        ),
    )
    capital_card = max(core_cards, key=lambda item: item.capital_protection)
    supported = tuple(
        item
        for item in interactions
        if item.joint_failures >= 30
        and item.gate_a_failures > 0
        and item.gate_b_failures > 0
    )
    redundant = max(
        supported,
        key=lambda item: (item.jaccard_percent or _ZERO, item.joint_failures),
        default=None,
    )
    strongest = max(
        supported,
        key=lambda item: (item.interaction_lift or _ZERO, item.joint_failures),
        default=None,
    )
    marginal = max(
        marginal_values,
        key=lambda item: (
            item.additional_survivors_if_removed,
            abs(item.net_capital_protection),
        ),
    )
    return BottleneckSummary(
        largest_bottleneck=largest.gate_id,
        largest_bottleneck_candidates=largest.candidates,
        largest_false_rejection_contributor=false_card.gate_id,
        largest_false_rejection_count=false_card.false_rejections,
        largest_sequential_false_rejection_contributor=sequential_false.gate_id,
        largest_sequential_false_rejection_count=(sequential_false.false_rejections),
        largest_capital_protection_contributor=capital_card.gate_id,
        largest_capital_protection=capital_card.capital_protection,
        most_redundant_gate_pair=(
            "unavailable"
            if redundant is None
            else f"{redundant.gate_a} + {redundant.gate_b}"
        ),
        redundancy_percent=None if redundant is None else redundant.jaccard_percent,
        strongest_gate_interaction=(
            "unavailable"
            if strongest is None
            else f"{strongest.gate_a} + {strongest.gate_b}"
        ),
        interaction_lift=(None if strongest is None else strongest.interaction_lift),
        ordering_materially_changes_outcomes=False,
        recommended_next_research_question=(
            f"Why does {marginal.gate_id} uniquely block "
            f"{marginal.additional_survivors_if_removed} candidates, and does "
            "their observed edge survive a separately reserved chronological "
            "holdout under identical costs?"
        ),
    )


def _first_failure_row(
    *,
    scope: str,
    gate_id: str,
    gate_group: str,
    values: tuple[CandidateGateLineage, ...],
    population: int,
) -> FirstFailureStatistic:
    return FirstFailureStatistic(
        scope=scope,
        gate_id=gate_id,
        gate_group=gate_group,
        candidates=len(values),
        population_percent=_rate(len(values), population) or _ZERO,
        correct_rejections=sum(
            item.outcome_classification == "CORRECT_REJECTION" for item in values
        ),
        false_rejections=sum(
            item.outcome_classification == "FALSE_REJECTION" for item in values
        ),
        marginal=sum(item.outcome_classification == "MARGINAL" for item in values),
        data_uncertain=sum(
            item.outcome_classification == "DATA_UNCERTAIN" for item in values
        ),
        average_return_percent=_mean_return(values),
    )


def _economic_value(
    rows: tuple[CandidateGateLineage, ...],
    notional: Decimal,
    *,
    positive: bool,
) -> Decimal:
    values = tuple(
        item.planned_net_return_percent
        for item in rows
        if item.planned_net_return_percent is not None
        and (
            item.planned_net_return_percent > 0
            if positive
            else item.planned_net_return_percent < 0
        )
    )
    return _q(
        sum(
            (notional * abs(value) / Decimal("100") for value in values),
            start=_ZERO,
        )
    )


def _confidence(resolved: int) -> EvidenceConfidence:
    if resolved >= 100:
        return EvidenceConfidence.MEDIUM
    return EvidenceConfidence.LOW


def _grade(
    *,
    gate_id: str,
    resolved_failures: int,
    precision: Decimal | None,
    incremental_survivors: int,
    incremental_value: Decimal,
) -> GateGrade:
    if (
        gate_id in {"INSTITUTIONAL_DECISION", "PORTFOLIO_ALLOCATION"}
        or resolved_failures < 30
        or incremental_survivors == 0
        or precision is None
    ):
        return GateGrade.RESEARCH_ONLY
    if precision >= Decimal("70") and incremental_value > 0:
        return GateGrade.A
    if precision >= Decimal("60") and incremental_value > 0:
        return GateGrade.B
    if precision >= Decimal("50") and incremental_value >= 0:
        return GateGrade.C
    return GateGrade.D


def _card_explanation(
    *,
    failures: int,
    precision: Decimal | None,
    incremental_survivors: int,
    incremental_value: Decimal,
) -> str:
    if failures == 0:
        return "No failures occurred in the frozen population."
    if incremental_survivors == 0:
        return (
            "The gate identified failures but released no candidate when removed "
            "alone because other gates still blocked every case."
        )
    return (
        f"Removing this gate alone releases {incremental_survivors} candidates; "
        f"rejection precision is {_text(precision)}% and marginal net capital "
        f"protection is INR {incremental_value}."
    )


def _mean_return(
    rows: tuple[CandidateGateLineage, ...],
) -> Decimal | None:
    values = tuple(
        item.planned_net_return_percent
        for item in rows
        if item.planned_net_return_percent is not None
    )
    if not values:
        return None
    return _q(sum(values, _ZERO) / Decimal(len(values)))


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return _q(Decimal(numerator) / Decimal(denominator) * Decimal("100"))


def _text(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


__all__ = [
    "bottleneck_summary",
    "first_failure_statistics",
    "gate_report_cards",
    "path_statistics",
    "sequential_survival",
]
