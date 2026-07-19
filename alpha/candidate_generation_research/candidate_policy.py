from __future__ import annotations

import hashlib
import json

from alpha.candidate_generation_research.models import (
    CANONICAL_POLICY_ID,
    CandidatePolicyProposal,
    CandidateVariantDefinition,
    CandidateVariantResult,
    ChronologicalValidationResult,
    PolicyProposalStatus,
    to_primitive,
)


class CandidatePolicyProposalEngine:
    def build(
        self,
        *,
        definitions: tuple[CandidateVariantDefinition, ...],
        results: tuple[CandidateVariantResult, ...],
        validations: tuple[ChronologicalValidationResult, ...],
    ) -> CandidatePolicyProposal:
        selected = next(
            (
                item
                for item in validations
                if item.status is PolicyProposalStatus.PROMOTE_TO_POLICY_REVIEW
            ),
            None,
        )
        definition = (
            None
            if selected is None
            else next(
                item for item in definitions if item.variant_id == selected.variant_id
            )
        )
        rows = tuple(
            item
            for item in results
            if selected is not None and item.variant_id == selected.variant_id
        )
        payload = {
            "parent": CANONICAL_POLICY_ID,
            "selected": None if selected is None else selected.variant_id,
            "definition": to_primitive(definition) if definition is not None else None,
            "results": to_primitive(rows),
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return CandidatePolicyProposal(
            policy_id=(
                "NO_CANDIDATE_POLICY_PROPOSAL"
                if selected is None
                else "ALPHA_CANDIDATE_POLICY_RESEARCH_0001"
            ),
            parent_policy=CANONICAL_POLICY_ID,
            variant_family=None if definition is None else definition.family.value,
            setup_definitions=(
                ()
                if definition is None
                else tuple(item.value for item in definition.supported_families)
            ),
            candidate_creation_rules=(
                ()
                if definition is None
                else (
                    f"confidence>={definition.minimum_confidence}",
                    f"volume_ratio>={definition.minimum_volume_ratio}",
                    f"extension<={definition.maximum_extension}",
                    f"prospective_rr>={definition.minimum_rr}",
                )
            ),
            timing_rules=(
                ()
                if definition is None
                else (f"duplicate_cooldown={definition.duplicate_cooldown_sessions}",)
            ),
            evidence_partitions=tuple(item.partition.value for item in rows),
            candidate_counts={item.partition.value: item.candidates for item in rows},
            recall={
                item.partition.value: _text(item.candidate_recall) for item in rows
            },
            precision={
                item.partition.value: _text(item.candidate_precision) for item in rows
            },
            expectancy={
                item.partition.value: _text(item.forward_expectancy_after_costs)
                for item in rows
            },
            drawdown={
                item.partition.value: _text(item.maximum_drawdown_proxy)
                for item in rows
            },
            major_move_coverage={
                item.partition.value: _text(item.major_move_capture_rate)
                for item in rows
            },
            false_candidate_rate={
                item.partition.value: _text(item.false_candidate_rate) for item in rows
            },
            validation_status=("NOT_PASSED" if selected is None else "VALIDATION_PASS"),
            holdout_status="NOT_OPENED_OR_FAILED"
            if selected is None
            else "HOLDOUT_PASS",
            status=(
                PolicyProposalStatus.MORE_EVIDENCE
                if selected is None
                else PolicyProposalStatus.PROMOTE_TO_POLICY_REVIEW
            ),
            manifest_hash=digest,
        )


def _text(value: object) -> str:
    return "UNAVAILABLE" if value is None else str(value)


__all__ = ["CandidatePolicyProposalEngine"]
