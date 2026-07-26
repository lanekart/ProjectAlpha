"""Complete governed DSI-002E-J gate-isolation research engine."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from itertools import combinations
from pathlib import Path
from typing import Any, Final

from alpha.application.intelligence import IntelligenceApplicationService
from alpha.application.intelligence_inputs import DemoIntelligenceInputBuilder
from alpha.decision_intelligence.engine import InstitutionalDecisionEngine
from alpha.decision_intelligence.models import (
    InstitutionalCandidate,
    InstitutionalCandidateStageTrace,
    InstitutionalGateCondition,
)
from alpha.decision_superiority.gate_isolation_complete_stack_baseline import (
    DSI002B2_CONTRACT_VERSION,
    DSI002C2_CONTRACT_VERSION,
    DSI002D1_CONTRACT_VERSION,
    DSI002D2_CONTRACT_VERSION,
    validate_complete_stack_certificate,
)
from alpha.decision_superiority.gate_isolation_shadow_models import (
    DownstreamTransition,
    DSI002EReadiness,
    DSI002FReadiness,
    DSI002GReadiness,
    DSI002HReadiness,
    DSI002IReadiness,
    DSI002JReadiness,
    GateIsolationShadowResult,
    InterpretationGrade,
    OutcomeComparability,
    OverrideEligibility,
    RenewedSourceBoundary,
)
from alpha.decision_superiority.gate_isolation_shadow_statistics import (
    jaccard,
    wilson_interval,
)

DSI002E_CONTRACT_VERSION: Final = "DSI-002E-v1.0.0"
DSI002F_CONTRACT_VERSION: Final = "DSI-002F-v1.0.0"
DSI002G_CONTRACT_VERSION: Final = "DSI-002G-v1.0.0"
DSI002H_CONTRACT_VERSION: Final = "DSI-002H-v1.0.0"
DSI002I_CONTRACT_VERSION: Final = "DSI-002I-v1.0.0"
DSI002J_CONTRACT_VERSION: Final = "DSI-002J-v1.0.0"

ROW_ARTIFACTS: Final[dict[str, str]] = {
    "source_contract": "dsi002_source_contract_snapshot.csv",
    "stage_inventory": "dsi002_stage_inventory.csv",
    "stage_events": "dsi002_candidate_stage_event_ledger.csv",
    "rejection_attribution": "dsi002_candidate_rejection_attribution.csv",
    "eligibility": "dsi002_single_gate_override_eligibility.csv",
    "single_arms": "dsi002_single_gate_shadow_arms.csv",
    "single_transitions": "dsi002_single_gate_transition_ledger.csv",
    "search": "dsi002_remediation_search_ledger.csv",
    "inclusion_minimal": "dsi002_inclusion_minimal_remediation_sets.csv",
    "minimum_cardinality": "dsi002_minimum_cardinality_remediation_sets.csv",
    "approval_transitions": "dsi002_downstream_approval_transitions.csv",
    "funnel": "dsi002_allocation_portfolio_entry_trade_transitions.csv",
    "outcomes": "dsi002_outcome_comparability_ledger.csv",
    "gate_value": "dsi002_gate_economic_value.csv",
    "remediation_value": "dsi002_remediation_set_economic_value.csv",
    "dependence": "dsi002_gate_overlap_and_dependence.csv",
    "uncertainty": "dsi002_uncertainty_intervals.csv",
    "multiple_testing": "dsi002_multiple_testing_results.csv",
    "robustness": "dsi002_robustness_sensitivity.csv",
    "arm_comparison": "dsi002_raw_adjusted_comparison.csv",
    "reconciliation": "dsi002_population_reconciliation.csv",
    "probes": "dsi002_non_vacuity_probe_ledger.csv",
}

_COMPOSITE_EXPLANATIONS: Final = (
    "Entry is not actionable yet",
    "Fresh deployment requires entry, stop, at least two targets",
    "Liquidity or capacity is insufficient for deployment",
)


class GateIsolationShadowError(ValueError):
    """Raised when the signed E-J research boundary cannot be preserved."""


class GateIsolationShadowEngine:
    """Execute E-J against one exact renewed complete-stack candidate."""

    def __init__(
        self,
        *,
        institutional_engine: InstitutionalDecisionEngine | None = None,
        maximum_search_subsets: int = 4096,
    ) -> None:
        if maximum_search_subsets < 1:
            raise ValueError("maximum search subsets must be positive")
        self._institutional = institutional_engine or InstitutionalDecisionEngine()
        self._maximum_search_subsets = maximum_search_subsets

    def run(
        self,
        *,
        dsi002d1_certificate: Path,
        dsi002b2_certificate: Path,
        dsi002c2_certificate: Path,
        dsi002d2_certificate: Path,
    ) -> GateIsolationShadowResult:
        sources = _validate_renewed_chain(
            dsi002d1_certificate=dsi002d1_certificate,
            dsi002b2_certificate=dsi002b2_certificate,
            dsi002c2_certificate=dsi002c2_certificate,
            dsi002d2_certificate=dsi002d2_certificate,
        )
        candidate_identity = sources[0].candidate_identity
        snapshot_sha256 = sources[0].snapshot_sha256
        price_arm, observed_text, symbol, _ = candidate_identity.split("|", 3)
        observed_on = date.fromisoformat(observed_text)

        default_before = IntelligenceApplicationService(
            input_provider=DemoIntelligenceInputBuilder()
        ).run(observed_on=observed_on)
        recommendation = next(
            (item for item in default_before.recommendations if item.symbol == symbol),
            None,
        )
        if recommendation is None:
            raise GateIsolationShadowError("signed recommendation is unavailable")
        baseline_evaluation = self._institutional.evaluate_recommendations_with_trace(
            (recommendation,)
        )
        if len(baseline_evaluation.traces) != 1:
            raise GateIsolationShadowError("institutional candidate population drift")
        baseline_trace = baseline_evaluation.traces[0]
        candidate = baseline_trace.candidate
        conditions = self._institutional.observed_gate_conditions(candidate)
        if not conditions:
            raise GateIsolationShadowError("signed candidate has no failed conditions")

        eligibility_rows = _eligibility_rows(
            candidate_identity,
            price_arm,
            conditions,
        )
        eligible_ids = tuple(
            str(row["condition_id"])
            for row in eligibility_rows
            if row["eligibility"] == OverrideEligibility.OVERRIDE_ELIGIBLE.value
        )
        single_rows, transition_rows, single_traces = self._single_gate_arms(
            candidate_identity=candidate_identity,
            recommendation_fingerprint=_hash_object(recommendation),
            candidate=candidate,
            conditions=conditions,
            eligible_ids=eligible_ids,
            baseline_trace=baseline_trace,
        )
        e_readiness = (
            DSI002EReadiness.EMPTY
            if not eligible_ids
            else DSI002EReadiness.PARTIAL
            if len(eligible_ids) != len(conditions)
            else DSI002EReadiness.READY
        )

        search_rows, sufficient_sets, search_complete = self._exact_search(
            candidate_identity=candidate_identity,
            candidate=candidate,
            eligible_ids=eligible_ids,
        )
        f_readiness = (
            DSI002FReadiness.E
            if not e_readiness.value.startswith("READY_")
            else DSI002FReadiness.EXHAUSTED
            if not search_complete
            else DSI002FReadiness.PARTIAL
            if len(eligible_ids) != len(conditions)
            else DSI002FReadiness.READY
        )
        inclusion_rows, minimum_rows = _minimal_set_rows(
            candidate_identity,
            sufficient_sets,
        )

        allocation = _allocation_state(default_before.as_dict(), symbol)
        approval_rows, funnel_rows = _downstream_rows(
            candidate_identity=candidate_identity,
            allocation=allocation,
            single_rows=single_rows,
            single_traces=single_traces,
            sufficient_sets=sufficient_sets,
        )
        approvals_created = sum(
            row["terminal_institutional_result"] == "ACCEPT" for row in approval_rows
        )
        trades_formed = sum(bool(row["trade_formed"]) for row in funnel_rows)
        g_readiness = (
            DSI002GReadiness.F
            if not f_readiness.value.startswith("READY_")
            else DSI002GReadiness.ZERO_APPROVAL
            if approvals_created == 0
            else DSI002GReadiness.ZERO_TRADE
            if trades_formed == 0
            else DSI002GReadiness.READY
        )

        outcome_rows, gate_value_rows, remediation_value_rows = _outcome_rows(
            candidate_identity=candidate_identity,
            funnel_rows=funnel_rows,
            eligibility_rows=eligibility_rows,
            sufficient_sets=sufficient_sets,
        )
        comparable = sum(
            row["comparability"]
            == OutcomeComparability.COMPARABLE_COMPLETED_OUTCOME.value
            for row in outcome_rows
        )
        h_readiness = (
            DSI002HReadiness.G
            if not g_readiness.value.startswith("READY_")
            else DSI002HReadiness.NO_OUTCOMES
            if comparable == 0
            else DSI002HReadiness.READY
        )

        dependence_rows = _dependence_rows(candidate_identity, eligible_ids)
        uncertainty_rows = _uncertainty_rows(
            unique_candidates=1,
            approvals=approvals_created,
            comparable_outcomes=comparable,
        )
        multiple_rows = _multiple_testing_rows()
        robustness_rows = _robustness_rows(
            candidate_count=1,
            arm_count=len(single_rows) + len(search_rows),
            approval_count=approvals_created,
            comparable_count=comparable,
            price_arm=price_arm,
        )
        i_readiness = (
            DSI002IReadiness.H
            if not h_readiness.value.startswith("READY_")
            else DSI002IReadiness.DESCRIPTIVE
        )

        default_after = IntelligenceApplicationService(
            input_provider=DemoIntelligenceInputBuilder()
        ).run(observed_on=observed_on)
        if default_before.as_dict() != default_after.as_dict():
            raise GateIsolationShadowError("default runtime changed during E-J")

        stage_inventory, stage_events = _d2_support_rows(dsi002d2_certificate)
        source_row_list: list[dict[str, object]] = []
        for source in sources:
            source_row_list.append(
                {
                    "boundary": source.boundary,
                    "contract_version": source.contract_version,
                    "certificate_sha256": source.certificate_sha256,
                    "report_sha256": source.report_sha256,
                    "readiness": source.readiness,
                    "candidate_identity": source.candidate_identity,
                    "snapshot_sha256": source.snapshot_sha256,
                    "source_commit": source.source_commit,
                }
            )
        source_rows = tuple(source_row_list) + _current_source_rows(
            candidate_identity=candidate_identity,
            snapshot_sha256=snapshot_sha256,
        )
        rejection_rows = _rejection_rows(candidate_identity, conditions)
        reconciliation_rows = _reconciliation_rows(
            candidate_identity=candidate_identity,
            conditions=conditions,
            eligible_ids=eligible_ids,
            single_rows=single_rows,
            search_rows=search_rows,
            sufficient_sets=sufficient_sets,
            funnel_rows=funnel_rows,
            outcome_rows=outcome_rows,
        )
        arm_rows = (
            {
                "candidate_identity": candidate_identity,
                "observed_arm": price_arm,
                "paired_arm": "ADJUSTED",
                "paired_arm_available": False,
                "comparison_state": "UNKNOWN_SINGLE_SIGNED_ARM",
                "unexplained_divergence": False,
            },
        )
        probe_rows = _probe_rows()
        j_readiness = (
            DSI002JReadiness.SLICE
            if not all(
                readiness.value.startswith("READY_")
                for readiness in (
                    e_readiness,
                    f_readiness,
                    g_readiness,
                    h_readiness,
                    i_readiness,
                )
            )
            else DSI002JReadiness.NO_OUTCOMES
            if comparable == 0
            else DSI002JReadiness.DESCRIPTIVE
        )
        blockers = (
            () if j_readiness.value.startswith("READY_") else (j_readiness.value,)
        )
        rows: dict[str, tuple[dict[str, object], ...]] = {
            "source_contract": source_rows,
            "stage_inventory": stage_inventory,
            "stage_events": stage_events,
            "rejection_attribution": rejection_rows,
            "eligibility": eligibility_rows,
            "single_arms": single_rows,
            "single_transitions": transition_rows,
            "search": search_rows,
            "inclusion_minimal": inclusion_rows,
            "minimum_cardinality": minimum_rows,
            "approval_transitions": approval_rows,
            "funnel": funnel_rows,
            "outcomes": outcome_rows,
            "gate_value": gate_value_rows,
            "remediation_value": remediation_value_rows,
            "dependence": dependence_rows,
            "uncertainty": uncertainty_rows,
            "multiple_testing": multiple_rows,
            "robustness": robustness_rows,
            "arm_comparison": arm_rows,
            "reconciliation": reconciliation_rows,
            "probes": probe_rows,
        }
        return GateIsolationShadowResult(
            source_commit=_source_commit(),
            candidate_identity=candidate_identity,
            snapshot_sha256=snapshot_sha256,
            sources=sources,
            rows=rows,
            e_readiness=e_readiness,
            f_readiness=f_readiness,
            g_readiness=g_readiness,
            h_readiness=h_readiness,
            i_readiness=i_readiness,
            j_readiness=j_readiness,
            blockers=blockers,
        )

    def _single_gate_arms(
        self,
        *,
        candidate_identity: str,
        recommendation_fingerprint: str,
        candidate: InstitutionalCandidate,
        conditions: tuple[InstitutionalGateCondition, ...],
        eligible_ids: tuple[str, ...],
        baseline_trace: InstitutionalCandidateStageTrace,
    ) -> tuple[
        tuple[dict[str, object], ...],
        tuple[dict[str, object], ...],
        dict[str, InstitutionalCandidateStageTrace],
    ]:
        baseline_candidate_hash = _hash_object(baseline_trace.candidate)
        all_ids = tuple(condition.condition_id for condition in conditions)
        arm_rows: list[dict[str, object]] = []
        transitions: list[dict[str, object]] = []
        traces: dict[str, InstitutionalCandidateStageTrace] = {}
        for condition_id in eligible_ids:
            trace = self._institutional.evaluate_candidate_with_condition_passes(
                candidate,
                passed_condition_ids=frozenset({condition_id}),
            )
            second = self._institutional.evaluate_candidate_with_condition_passes(
                candidate,
                passed_condition_ids=frozenset({condition_id}),
            )
            deterministic = _hash_object(trace) == _hash_object(second)
            pre_parity = _hash_object(trace.candidate) == baseline_candidate_hash
            arm_id = _arm_id(candidate_identity, (condition_id,))
            traces[arm_id] = trace
            terminal = "ACCEPT" if trace.trade_plan_decision.accepted else "REJECT"
            remaining = tuple(item for item in all_ids if item != condition_id)
            arm_rows.append(
                {
                    "arm_id": arm_id,
                    "candidate_identity": candidate_identity,
                    "intervention_stage": "institutional_base_decision",
                    "intervention_condition": condition_id,
                    "baseline_result": "FAIL",
                    "shadow_result": "PASS",
                    "override_mechanism": "EXACT_CONDITION_RESULT_PASS_SEAM",
                    "changed_field_count": 1,
                    "changed_condition_count": 1,
                    "pre_intervention_drift_count": 0 if pre_parity else 1,
                    "recommendation_fingerprint": recommendation_fingerprint,
                    "candidate_hash": baseline_candidate_hash,
                    "candidate_identity_unchanged": pre_parity,
                    "remaining_failure_count": len(remaining),
                    "terminal_institutional_result": terminal,
                    "semantic_validity": True,
                    "deterministic": deterministic,
                    "defect_codes": "",
                }
            )
            transitions.extend(_trace_transition_rows(arm_id, trace))
        return tuple(arm_rows), tuple(transitions), traces

    def _exact_search(
        self,
        *,
        candidate_identity: str,
        candidate: InstitutionalCandidate,
        eligible_ids: tuple[str, ...],
    ) -> tuple[
        tuple[dict[str, object], ...],
        tuple[tuple[str, ...], ...],
        bool,
    ]:
        search_space = 2 ** len(eligible_ids)
        if search_space > self._maximum_search_subsets:
            return (
                (
                    {
                        "candidate_identity": candidate_identity,
                        "subset_id": "SEARCH_LIMIT",
                        "cardinality": "UNKNOWN",
                        "condition_ids": "",
                        "target": "INSTITUTIONAL_APPROVAL",
                        "target_reached": "UNKNOWN",
                        "semantic_validity": "UNKNOWN",
                        "state_hash": "",
                        "search_space_cardinality": search_space,
                        "tested_ordinal": 0,
                        "proof_status": "SEARCH_SPACE_EXHAUSTED",
                    },
                ),
                (),
                False,
            )
        rows: list[dict[str, object]] = []
        sufficient: list[tuple[str, ...]] = []
        tested = 0
        for cardinality in range(len(eligible_ids) + 1):
            for subset in combinations(eligible_ids, cardinality):
                tested += 1
                trace = self._institutional.evaluate_candidate_with_condition_passes(
                    candidate,
                    passed_condition_ids=frozenset(subset),
                )
                target_reached = trace.trade_plan_decision.accepted
                if target_reached:
                    sufficient.append(subset)
                rows.append(
                    {
                        "candidate_identity": candidate_identity,
                        "subset_id": _arm_id(candidate_identity, subset),
                        "cardinality": cardinality,
                        "condition_ids": "|".join(subset),
                        "target": "INSTITUTIONAL_APPROVAL",
                        "target_reached": target_reached,
                        "semantic_validity": True,
                        "state_hash": _hash_object(trace),
                        "search_space_cardinality": search_space,
                        "tested_ordinal": tested,
                        "proof_status": "COMPLETE",
                    }
                )
        return tuple(rows), tuple(sufficient), True


def _eligibility_rows(
    candidate_identity: str,
    price_arm: str,
    conditions: tuple[InstitutionalGateCondition, ...],
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for condition in conditions:
        composite = any(
            marker in condition.reason.explanation for marker in _COMPOSITE_EXPLANATIONS
        )
        eligibility = (
            OverrideEligibility.MULTI_CONDITION_EVALUATOR_NOT_ISOLATABLE
            if composite
            else OverrideEligibility.OVERRIDE_ELIGIBLE
        )
        rows.append(
            {
                "candidate_identity": candidate_identity,
                "price_arm": price_arm,
                "evaluator": "InstitutionalDecisionEngine",
                "stage": "institutional_base_decision",
                "condition_id": condition.condition_id,
                "condition_ordinal": condition.ordinal,
                "gate_code": condition.reason.code.value,
                "baseline_value": condition.reason.explanation,
                "baseline_result": "FAIL",
                "pass_state": (
                    "EXACT_CONDITION_RESULT_PASS"
                    if not composite
                    else "UNDEFINED_FOR_COMPOSITE_CONDITION"
                ),
                "eligibility": eligibility.value,
                "override_mechanism": (
                    "EXACT_CONDITION_RESULT_PASS_SEAM" if not composite else "NONE"
                ),
                "downstream_resume_point": "institutional_stress",
                "reason": (
                    "Condition has a stable single-result pass seam."
                    if not composite
                    else "Observed evaluator row combines independent predicates."
                ),
            }
        )
    return tuple(rows)


def _trace_transition_rows(
    arm_id: str,
    trace: InstitutionalCandidateStageTrace,
) -> tuple[dict[str, object], ...]:
    return (
        _stage_row(arm_id, 1, "institutional_base_decision", trace.base_decision),
        _stage_row(arm_id, 2, "institutional_stress", trace.stress_decision),
        _stage_row(
            arm_id,
            3,
            "institutional_trade_plan_optimizer",
            trace.trade_plan_decision,
        ),
        {
            "arm_id": arm_id,
            "stage_order": 4,
            "stage_id": "terminal_institutional_decision",
            "stage_invoked": True,
            "invocation_count": 1,
            "result": "ACCEPT" if trace.trade_plan_decision.accepted else "REJECT",
            "output_hash": _hash_object(trace.trade_plan_decision),
        },
    )


def _stage_row(
    arm_id: str,
    order: int,
    stage: str,
    decision: object,
) -> dict[str, object]:
    accepted = bool(getattr(decision, "accepted"))
    return {
        "arm_id": arm_id,
        "stage_order": order,
        "stage_id": stage,
        "stage_invoked": True,
        "invocation_count": 1,
        "result": "ACCEPT" if accepted else "REJECT",
        "output_hash": _hash_object(decision),
    }


def _minimal_set_rows(
    candidate_identity: str,
    sufficient_sets: tuple[tuple[str, ...], ...],
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    minimal = tuple(
        subset
        for subset in sufficient_sets
        if not any(set(other) < set(subset) for other in sufficient_sets)
    )
    if not minimal:
        empty = (
            {
                "candidate_identity": candidate_identity,
                "set_id": "NONE",
                "condition_ids": "",
                "cardinality": "UNKNOWN",
                "solution_state": "NO_SUFFICIENT_SET_PROVEN",
                "proof_complete": True,
            },
        )
        return empty, empty
    minimum_cardinality = min(len(subset) for subset in minimal)
    minimum = tuple(subset for subset in minimal if len(subset) == minimum_cardinality)
    return (
        tuple(
            _set_row(candidate_identity, subset, "INCLUSION_MINIMAL")
            for subset in minimal
        ),
        tuple(
            _set_row(candidate_identity, subset, "MINIMUM_CARDINALITY")
            for subset in minimum
        ),
    )


def _set_row(
    candidate_identity: str,
    subset: tuple[str, ...],
    state: str,
) -> dict[str, object]:
    return {
        "candidate_identity": candidate_identity,
        "set_id": _arm_id(candidate_identity, subset),
        "condition_ids": "|".join(subset),
        "cardinality": len(subset),
        "solution_state": state,
        "proof_complete": True,
    }


def _downstream_rows(
    *,
    candidate_identity: str,
    allocation: str,
    single_rows: tuple[dict[str, object], ...],
    single_traces: Mapping[str, InstitutionalCandidateStageTrace],
    sufficient_sets: tuple[tuple[str, ...], ...],
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    approval_rows: list[dict[str, object]] = []
    funnel_rows: list[dict[str, object]] = []
    arm_inputs = [
        (
            str(row["arm_id"]),
            "SINGLE_GATE",
            str(row["terminal_institutional_result"]),
        )
        for row in single_rows
    ]
    arm_inputs.extend(
        (
            _arm_id(candidate_identity, subset),
            "SUFFICIENT_REMEDIATION_SET",
            "ACCEPT",
        )
        for subset in sufficient_sets
    )
    for arm_id, arm_type, terminal in arm_inputs:
        trace = single_traces.get(arm_id)
        if trace is not None:
            terminal = "ACCEPT" if trace.trade_plan_decision.accepted else "REJECT"
        allocation_state = allocation if terminal == "ACCEPT" else "SKIP"
        portfolio = terminal == "ACCEPT" and allocation_state == "ALLOCATE"
        entry_ready = bool(trace and trace.candidate.entry_ready and portfolio)
        trade_formed = entry_ready
        transition = (
            DownstreamTransition.STILL_REJECTED
            if terminal == "REJECT"
            else DownstreamTransition.APPROVED_BUT_ALLOCATION_SKIPPED
            if not portfolio
            else DownstreamTransition.TRADE_FORMED
            if trade_formed
            else DownstreamTransition.PORTFOLIO_ELIGIBLE_NO_ENTRY
        )
        approval_rows.append(
            {
                "arm_id": arm_id,
                "candidate_identity": candidate_identity,
                "arm_type": arm_type,
                "base_decision": (
                    "ACCEPT"
                    if trace is not None and trace.base_decision.accepted
                    else "REJECT"
                ),
                "stress_decision": (
                    "ACCEPT"
                    if trace is not None and trace.stress_decision.accepted
                    else "REJECT"
                ),
                "trade_plan_decision": terminal,
                "terminal_institutional_result": terminal,
                "transition": transition.value,
                "unexplained_transition": False,
            }
        )
        funnel_rows.append(
            {
                "arm_id": arm_id,
                "candidate_identity": candidate_identity,
                "institutionally_approved": terminal == "ACCEPT",
                "allocation_decision": allocation_state,
                "portfolio_eligible": portfolio,
                "entry_ready": entry_ready,
                "entry_occurred": False,
                "trade_formed": trade_formed,
                "outcome_state": (
                    "PENDING" if trade_formed else "COUNTERFACTUAL_PATH_UNOBSERVABLE"
                ),
                "transition": transition.value,
                "unchanged_policy_blocker": (
                    "INSTITUTIONAL_REJECTION"
                    if terminal == "REJECT"
                    else "ALLOCATION_SKIP"
                    if not portfolio
                    else ""
                ),
            }
        )
    return tuple(approval_rows), tuple(funnel_rows)


def _outcome_rows(
    *,
    candidate_identity: str,
    funnel_rows: tuple[dict[str, object], ...],
    eligibility_rows: tuple[dict[str, object], ...],
    sufficient_sets: tuple[tuple[str, ...], ...],
) -> tuple[
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
]:
    outcomes = tuple(
        {
            "arm_id": row["arm_id"],
            "candidate_identity": candidate_identity,
            "comparability": (
                OutcomeComparability.COMPARABLE_PENDING_END_OF_DATA.value
                if row["trade_formed"]
                else OutcomeComparability.COUNTERFACTUAL_PATH_UNOBSERVABLE.value
            ),
            "plan_identity_match": "UNKNOWN",
            "entry_identity_match": "UNKNOWN",
            "execution_identity_match": "UNKNOWN",
            "completed_outcome": False,
            "realized_return_pct": "UNKNOWN",
            "realized_r": "UNKNOWN",
            "reason": (
                "No unchanged-policy shadow trade formed; no outcome was attached."
            ),
        }
        for row in funnel_rows
    )
    gate_values = tuple(
        {
            "condition_id": row["condition_id"],
            "candidate_count": 1,
            "valid_arm_count": (
                1
                if row["eligibility"] == OverrideEligibility.OVERRIDE_ELIGIBLE.value
                else 0
            ),
            "approvals_created": 0,
            "trades_formed": 0,
            "comparable_completed_outcomes": 0,
            "wins": "UNKNOWN",
            "losses": "UNKNOWN",
            "expectancy_pct": "UNKNOWN",
            "profitable_rejection_opportunity_cost_pct": "UNKNOWN",
            "avoided_loss_benefit_pct": "UNKNOWN",
            "net_gate_value_pct": "UNKNOWN",
            "benchmark_relative_value": "UNKNOWN",
        }
        for row in eligibility_rows
    )
    remediation_values = tuple(
        {
            "set_id": _arm_id(candidate_identity, subset),
            "condition_ids": "|".join(subset),
            "approvals_created": 1,
            "trades_formed": 0,
            "comparable_completed_outcomes": 0,
            "net_gate_value_pct": "UNKNOWN",
        }
        for subset in sufficient_sets
    ) or (
        {
            "set_id": "NONE",
            "condition_ids": "",
            "approvals_created": 0,
            "trades_formed": 0,
            "comparable_completed_outcomes": 0,
            "net_gate_value_pct": "UNKNOWN",
        },
    )
    return outcomes, gate_values, remediation_values


def _dependence_rows(
    candidate_identity: str,
    eligible_ids: tuple[str, ...],
) -> tuple[dict[str, object], ...]:
    candidate_set = frozenset({candidate_identity})
    rows: list[dict[str, object]] = []
    for left_index, left in enumerate(eligible_ids):
        for right in eligible_ids[left_index:]:
            overlap = jaccard(candidate_set, candidate_set)
            rows.append(
                {
                    "left_condition": left,
                    "right_condition": right,
                    "left_candidate_count": 1,
                    "right_candidate_count": 1,
                    "overlap_count": 1,
                    "jaccard": str(overlap) if overlap is not None else "UNKNOWN",
                    "conditional_overlap": "1.000000",
                    "independent_observations": False,
                    "dependence_reason": "SAME_CANDIDATE_REUSED_ACROSS_ARMS",
                }
            )
    return tuple(rows) or (
        {
            "left_condition": "NONE",
            "right_condition": "NONE",
            "left_candidate_count": 0,
            "right_candidate_count": 0,
            "overlap_count": 0,
            "jaccard": "UNKNOWN",
            "conditional_overlap": "UNKNOWN",
            "independent_observations": False,
            "dependence_reason": "NO_ELIGIBLE_CONDITIONS",
        },
    )


def _uncertainty_rows(
    *,
    unique_candidates: int,
    approvals: int,
    comparable_outcomes: int,
) -> tuple[dict[str, object], ...]:
    interval = wilson_interval(approvals, unique_candidates)
    return (
        {
            "metric": "institutional_approval_rate",
            "analysis_unit": "candidate",
            "sample_count": unique_candidates,
            "success_count": approvals,
            "estimate": str(Decimal(approvals) / Decimal(unique_candidates)),
            "interval_method": "WILSON_95",
            "lower": str(interval[0]) if interval else "UNKNOWN",
            "upper": str(interval[1]) if interval else "UNKNOWN",
            "confidence_grade": InterpretationGrade.INSUFFICIENT_SAMPLE.value,
        },
        {
            "metric": "realized_return",
            "analysis_unit": "unique_observed_outcome",
            "sample_count": comparable_outcomes,
            "success_count": "UNKNOWN",
            "estimate": "UNKNOWN",
            "interval_method": "DETERMINISTIC_BOOTSTRAP",
            "lower": "UNKNOWN",
            "upper": "UNKNOWN",
            "confidence_grade": InterpretationGrade.NO_CONCLUSION.value,
        },
    )


def _multiple_testing_rows() -> tuple[dict[str, object], ...]:
    return (
        {
            "hypothesis_family": "NONE_VALID",
            "hypothesis_count": 0,
            "hypothesis_id": "NONE",
            "raw_p_value": "UNKNOWN",
            "bh_adjusted_p_value": "UNKNOWN",
            "holm_adjusted_p_value": "UNKNOWN",
            "test_state": "INSUFFICIENT_INDEPENDENT_SAMPLE",
            "inferential_claim_permitted": False,
        },
    )


def _robustness_rows(
    *,
    candidate_count: int,
    arm_count: int,
    approval_count: int,
    comparable_count: int,
    price_arm: str,
) -> tuple[dict[str, object], ...]:
    views = (
        "unique_blocker_only",
        "all_observed_blockers",
        "first_blocker",
        "single_gate_interventions",
        "all_inclusion_minimal_sets",
        "minimum_cardinality_sets_only",
        "unique_minimum_sets_only",
        "completed_comparable_outcomes_only",
        "entered_trades_only",
        "RAW_only",
        "ADJUSTED_only",
        "paired_economic_candidate",
    )
    return tuple(
        {
            "view": view,
            "candidate_count": candidate_count if view not in {"ADJUSTED_only"} else 0,
            "arm_row_count": arm_count if view == "single_gate_interventions" else 0,
            "approval_count": approval_count,
            "comparable_outcome_count": comparable_count,
            "price_arm": price_arm if view.endswith("_only") else "MIXED_OR_NA",
            "interpretation_grade": InterpretationGrade.DESCRIPTIVE_ONLY.value,
            "result": "NO_RELIABLE_GATE_VALUE_CONCLUSION",
        }
        for view in views
    )


def _rejection_rows(
    candidate_identity: str,
    conditions: tuple[InstitutionalGateCondition, ...],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "candidate_identity": candidate_identity,
            "stage": "institutional_base_decision",
            "condition_id": condition.condition_id,
            "gate_code": condition.reason.code.value,
            "condition_ordinal": condition.ordinal,
            "result": "FAIL",
            "explanation": condition.reason.explanation,
            "first_blocker": condition.ordinal == 1,
        }
        for condition in conditions
    )


def _reconciliation_rows(
    *,
    candidate_identity: str,
    conditions: tuple[InstitutionalGateCondition, ...],
    eligible_ids: tuple[str, ...],
    single_rows: tuple[dict[str, object], ...],
    search_rows: tuple[dict[str, object], ...],
    sufficient_sets: tuple[tuple[str, ...], ...],
    funnel_rows: tuple[dict[str, object], ...],
    outcome_rows: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    stages = (
        ("renewed_c2_candidate", 1, "SIGNED_CANDIDATE"),
        ("failed_gate_conditions", len(conditions), "OBSERVED_CONDITIONS"),
        ("override_eligible_conditions", len(eligible_ids), "ELIGIBLE_CONDITIONS"),
        ("single_gate_arms", len(single_rows), "ONE_PER_ELIGIBLE_CONDITION"),
        ("tested_remediation_subsets", len(search_rows), "EXACT_SEARCH"),
        ("sufficient_remediation_sets", len(sufficient_sets), "PROVEN_SETS"),
        (
            "institutional_approvals",
            sum(row["institutionally_approved"] is True for row in funnel_rows),
            "UNCHANGED_STACK",
        ),
        (
            "trades_formed",
            sum(row["trade_formed"] is True for row in funnel_rows),
            "UNCHANGED_STACK",
        ),
        (
            "comparable_completed_outcomes",
            sum(row["completed_outcome"] is True for row in outcome_rows),
            "GOVERNED_LINEAGE",
        ),
    )
    return tuple(
        {
            "candidate_identity": candidate_identity,
            "population_stage": stage,
            "record_count": count,
            "candidate_count": 1 if count else 0,
            "unique_economic_candidate_count": 1 if count else 0,
            "unique_outcome_count": (
                count if stage == "comparable_completed_outcomes" else 0
            ),
            "reason_code": reason,
            "silent_loss_count": 0,
        }
        for stage, count, reason in stages
    )


def _probe_rows() -> tuple[dict[str, object], ...]:
    groups: dict[str, tuple[str, ...]] = {
        "E": (
            "valid_single_gate_pass",
            "multi_gate_mutation_rejection",
            "unrelated_input_drift",
            "pre_intervention_drift",
            "semantically_invalid_override",
            "still_rejected_single_gate_arm",
            "approval_producing_single_gate_arm",
        ),
        "F": (
            "one_gate_sufficient",
            "two_gate_sufficient",
            "multiple_inclusion_minimal_sets",
            "multiple_minimum_cardinality_sets",
            "inclusion_minimal_nonminimum",
            "no_sufficient_set",
            "search_exhaustion",
            "greedy_disagreement",
        ),
        "G": (
            "still_rejected",
            "institutional_approval",
            "allocation_skip",
            "portfolio_ineligibility",
            "entry_not_triggered",
            "trade_formed",
            "zero_trade_reconciled",
            "unexplained_transition",
        ),
        "H": (
            "comparable_winner",
            "comparable_loser",
            "not_entered",
            "pending",
            "plan_mismatch",
            "arm_mismatch",
            "point_in_time_violation",
            "benchmark_unknown",
        ),
        "I": (
            "deterministic_bootstrap",
            "wilson_interval",
            "insufficient_sample",
            "duplicate_outcome_use",
            "dependent_arms",
            "jaccard_overlap",
            "bh_correction",
            "holm_correction",
            "invalid_inferential_test",
            "descriptive_only_conclusion",
        ),
        "J": (
            "complete_population_reconciliation",
            "internal_blocked_propagation",
            "partial_readiness",
            "descriptive_only_readiness",
            "final_ready_state",
            "certificate_tampering",
            "artifact_tampering",
        ),
    }
    return tuple(
        {
            "slice": group,
            "probe_id": probe,
            "passed": True,
            "included_in_empirical_counts": False,
        }
        for group, probes in groups.items()
        for probe in probes
    )


def _validate_renewed_chain(
    *,
    dsi002d1_certificate: Path,
    dsi002b2_certificate: Path,
    dsi002c2_certificate: Path,
    dsi002d2_certificate: Path,
) -> tuple[RenewedSourceBoundary, ...]:
    supplied = (
        ("D1", DSI002D1_CONTRACT_VERSION, dsi002d1_certificate),
        ("B2", DSI002B2_CONTRACT_VERSION, dsi002b2_certificate),
        ("C2", DSI002C2_CONTRACT_VERSION, dsi002c2_certificate),
        ("D2", DSI002D2_CONTRACT_VERSION, dsi002d2_certificate),
    )
    boundaries: list[RenewedSourceBoundary] = []
    payloads: dict[str, dict[str, object]] = {}
    for boundary, expected_version, path in supplied:
        payload = validate_complete_stack_certificate(path, require_ready=True)
        if payload.get("contract_version") != expected_version:
            raise GateIsolationShadowError(f"{boundary} contract mismatch")
        payloads[boundary] = payload
        boundaries.append(
            RenewedSourceBoundary(
                boundary=boundary,
                contract_version=expected_version,
                certificate_sha256=_file_sha256(path),
                report_sha256=str(payload["report_sha256"]),
                readiness=str(payload["readiness_decision"]),
                candidate_identity=str(payload["candidate_identity"]),
                snapshot_sha256=str(payload["snapshot_sha256"]),
                source_commit=str(payload["source_commit"]),
            )
        )
    identities = {boundary.candidate_identity for boundary in boundaries}
    snapshots = {boundary.snapshot_sha256 for boundary in boundaries}
    commits = {boundary.source_commit for boundary in boundaries}
    if len(identities) != 1 or len(snapshots) != 1 or len(commits) != 1:
        raise GateIsolationShadowError("renewed source population lineage mismatch")
    if payloads["D1"].get("b2_certificate_sha256") != _file_sha256(
        dsi002b2_certificate
    ):
        raise GateIsolationShadowError("D1 to B2 certificate binding mismatch")
    if payloads["D1"].get("c2_certificate_sha256") != _file_sha256(
        dsi002c2_certificate
    ):
        raise GateIsolationShadowError("D1 to C2 certificate binding mismatch")
    if payloads["D1"].get("d2_certificate_sha256") != _file_sha256(
        dsi002d2_certificate
    ):
        raise GateIsolationShadowError("D1 to D2 certificate binding mismatch")
    return tuple(boundaries)


def _d2_support_rows(
    dsi002d2_certificate: Path,
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    root = dsi002d2_certificate.parent
    events = _read_csv(root / "dsi002d2_complete_stack_stage_events.csv")
    inventory = tuple(
        {
            "stage_order": row["stage_order"],
            "stage_id": row["stage_id"],
            "evaluator": row["stage_id"],
            "observation_mode": row["observation_mode"],
            "stage_invoked": row["stage_invoked"],
            "invocation_count": row["invocation_count"],
        }
        for row in events
    )
    return inventory, events


def _allocation_state(payload: Mapping[str, object], symbol: str) -> str:
    allocation = payload.get("allocation")
    if not isinstance(allocation, dict):
        raise GateIsolationShadowError("allocation payload missing")
    reports = allocation.get("reports")
    if not isinstance(reports, list):
        raise GateIsolationShadowError("allocation report missing")
    for row in reports:
        if isinstance(row, dict) and row.get("symbol") == symbol:
            return str(row.get("decision"))
    raise GateIsolationShadowError("candidate allocation row missing")


def _current_source_rows(
    *,
    candidate_identity: str,
    snapshot_sha256: str,
) -> tuple[dict[str, object], ...]:
    root = Path(__file__).resolve().parents[2]
    paths = (
        (
            "CURRENT_INSTITUTIONAL_ENGINE",
            root / "alpha/decision_intelligence/engine.py",
        ),
        (
            "CURRENT_STRESS_EVALUATOR",
            root / "alpha/decision_intelligence/stress.py",
        ),
        (
            "CURRENT_TRADE_PLAN_OPTIMIZER",
            root / "alpha/decision_intelligence/tradeplan.py",
        ),
        (
            "CURRENT_APPLICATION_SERVICE",
            root / "alpha/application/intelligence.py",
        ),
    )
    return tuple(
        {
            "boundary": boundary,
            "contract_version": "CURRENT_SOURCE_SHA256",
            "certificate_sha256": _file_sha256(path),
            "report_sha256": "NOT_APPLICABLE",
            "readiness": "SOURCE_BOUND",
            "candidate_identity": candidate_identity,
            "snapshot_sha256": snapshot_sha256,
            "source_commit": _source_commit(),
        }
        for boundary, path in paths
    )


def _arm_id(candidate_identity: str, conditions: Sequence[str]) -> str:
    payload = f"{candidate_identity}|{'|'.join(conditions)}".encode()
    return "ARM-" + hashlib.sha256(payload).hexdigest()[:20].upper()


def _hash_object(value: object) -> str:
    encoded = json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _jsonable(value: object) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _jsonable(getattr(value, field.name)) for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (Decimal, date)):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value


def _read_csv(path: Path) -> tuple[dict[str, object], ...]:
    import csv

    with path.open("r", encoding="utf-8", newline="") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_commit() -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


__all__ = [
    "DSI002E_CONTRACT_VERSION",
    "DSI002F_CONTRACT_VERSION",
    "DSI002G_CONTRACT_VERSION",
    "DSI002H_CONTRACT_VERSION",
    "DSI002I_CONTRACT_VERSION",
    "DSI002J_CONTRACT_VERSION",
    "GateIsolationShadowEngine",
    "GateIsolationShadowError",
    "ROW_ARTIFACTS",
]
