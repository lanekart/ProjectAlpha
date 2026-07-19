from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from decimal import Decimal

from alpha.candidate_generation_research.models import (
    CandidatePartition,
    CandidateVariantResult,
    ChronologicalValidationResult,
    PolicyProposalStatus,
)


class ChronologicalCandidateValidationEngine:
    """Select without holdout, then expose holdout only for the frozen winner."""

    def validate(
        self,
        results: tuple[CandidateVariantResult, ...],
    ) -> tuple[
        tuple[CandidateVariantResult, ...],
        tuple[ChronologicalValidationResult, ...],
    ]:
        by_variant: dict[str, dict[CandidatePartition, CandidateVariantResult]] = (
            defaultdict(dict)
        )
        for item in results:
            by_variant[item.variant_id][item.partition] = item
        eligible = []
        for variant_id, rows in by_variant.items():
            development = rows.get(CandidatePartition.DEVELOPMENT)
            validation = rows.get(CandidatePartition.VALIDATION)
            if development and validation and development.passed and validation.passed:
                eligible.append((variant_id, validation))
        selected = (
            max(
                eligible,
                key=lambda item: (
                    item[1].forward_expectancy_after_costs or Decimal("-999"),
                    item[1].candidate_recall or Decimal("-1"),
                    -item[1].explosion_penalty,
                    item[0],
                ),
            )[0]
            if eligible
            else None
        )
        updated = list(results)
        validations = []
        for variant_id in sorted(by_variant):
            rows = by_variant[variant_id]
            development = rows[CandidatePartition.DEVELOPMENT]
            validation = rows[CandidatePartition.VALIDATION]
            holdout = rows[CandidatePartition.HOLDOUT]
            stable_validation = _stable(development, validation)
            stable_holdout = _stable(validation, holdout)
            development_pass = development.passed
            validation_pass = validation.passed and stable_validation
            is_selected = variant_id == selected
            holdout_pass = is_selected and holdout.passed and stable_holdout
            status = _status(
                development_pass, validation_pass, holdout_pass, is_selected
            )
            validations.append(
                ChronologicalValidationResult(
                    variant_id=variant_id,
                    development_pass=development_pass,
                    validation_pass=validation_pass,
                    holdout_pass=holdout_pass,
                    selected_without_holdout=is_selected,
                    holdout_opened_after_selection=is_selected,
                    status=status,
                    reason=_reason(
                        development_pass,
                        validation_pass,
                        holdout_pass,
                        is_selected,
                        stable_validation,
                        stable_holdout,
                    ),
                )
            )
            for index, item in enumerate(updated):
                if item.variant_id != variant_id:
                    continue
                stability = (
                    "STABLE"
                    if item.partition is CandidatePartition.DEVELOPMENT
                    else "STABLE"
                    if item.partition is CandidatePartition.VALIDATION
                    and stable_validation
                    else "STABLE"
                    if item.partition is CandidatePartition.HOLDOUT and stable_holdout
                    else "UNSTABLE"
                )
                updated[index] = replace(
                    item,
                    stability=stability,
                    passed=item.passed and stability == "STABLE",
                    failure_reasons=(
                        item.failure_reasons
                        if stability == "STABLE"
                        else (*item.failure_reasons, "CROSS_PARTITION_INSTABILITY")
                    ),
                )
        return tuple(updated), tuple(validations)


def _stable(
    earlier: CandidateVariantResult,
    later: CandidateVariantResult,
) -> bool:
    if earlier.candidate_recall is None or later.candidate_recall is None:
        return False
    if (
        earlier.forward_expectancy_after_costs is None
        or later.forward_expectancy_after_costs is None
    ):
        return False
    recall_floor = earlier.candidate_recall * Decimal("0.50")
    return (
        later.candidate_recall >= recall_floor
        and later.forward_expectancy_after_costs > 0
    )


def _status(
    development: bool,
    validation: bool,
    holdout: bool,
    selected: bool,
) -> PolicyProposalStatus:
    if not development:
        return PolicyProposalStatus.REJECTED
    if not validation:
        return PolicyProposalStatus.REJECTED
    if not selected:
        return PolicyProposalStatus.MORE_EVIDENCE
    if not holdout:
        return PolicyProposalStatus.REJECTED
    return PolicyProposalStatus.PROMOTE_TO_POLICY_REVIEW


def _reason(
    development: bool,
    validation: bool,
    holdout: bool,
    selected: bool,
    stable_validation: bool,
    stable_holdout: bool,
) -> str:
    if not development:
        return "Development evidence failed predefined quality gates."
    if not validation:
        return (
            "Validation failed or did not remain stable."
            if not stable_validation
            else "Validation evidence failed predefined quality gates."
        )
    if not selected:
        return "Passed validation but was not selected; holdout cannot promote it."
    if not holdout:
        return (
            "Frozen winner failed holdout stability."
            if not stable_holdout
            else "Frozen winner failed holdout quality gates."
        )
    return "Frozen development/validation winner passed the untouched holdout."


__all__ = ["ChronologicalCandidateValidationEngine"]
