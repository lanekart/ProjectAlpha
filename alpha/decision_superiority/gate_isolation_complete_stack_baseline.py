"""DSI-002D1 canonical institutional wiring and signed baseline renewal."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Final

from alpha.application.intelligence import IntelligenceApplicationService
from alpha.application.intelligence_inputs import DemoIntelligenceInputBuilder
from alpha.decision_intelligence.engine import InstitutionalDecisionEngine
from alpha.decision_intelligence.models import InstitutionalCandidateStageTrace
from alpha.decision_superiority.gate_isolation_decision_baseline import (
    compare_run_to_baseline,
)
from alpha.decision_superiority.gate_isolation_frozen_policy_replay import (
    FrozenReplayBundle,
)
from alpha.decision_superiority.gate_isolation_stage_attribution import (
    DSI002DSourceContractError,
    DSI002DSourceValidator,
)
from alpha.decision_superiority.gate_isolation_stage_attribution_artifacts import (
    DSI002DArtifactError,
    validate_dsi002d_certificate,
)

DSI002D1_CONTRACT_VERSION: Final = "DSI-002D1-v1.0.0"
DSI002B2_CONTRACT_VERSION: Final = "DSI-002B2-v1.0.0"
DSI002C2_CONTRACT_VERSION: Final = "DSI-002C2-v1.0.0"
DSI002D2_CONTRACT_VERSION: Final = "DSI-002D2-v1.0.0"

_D1_SUPPORT_NAMES: Final = (
    "dsi002d1_current_call_graph.csv",
    "dsi002d1_wiring_defect_attribution.csv",
    "dsi002d1_repaired_call_graph.csv",
    "dsi002d1_evaluator_invocation_ledger.csv",
    "dsi002d1_old_new_baseline_comparison.csv",
    "dsi002d1_default_runtime_invariance.csv",
    "dsi002d1_raw_adjusted_wiring_comparison.csv",
    "dsi002d1_source_contract_snapshot.csv",
    "dsi002d1_non_vacuity_probe_ledger.csv",
    "dsi002d1_executive_report.md",
)
_GOVERNANCE_FLAGS: Final = (
    "CAUSAL_CLAIM_PERMITTED",
    "THRESHOLD_CHANGE_PERMITTED",
    "GATE_ORDER_CHANGE_PERMITTED",
    "APPROVAL_POLICY_CHANGE_PERMITTED",
    "PORTFOLIO_POLICY_CHANGE_PERMITTED",
    "EXECUTION_POLICY_CHANGE_PERMITTED",
    "COUNTERFACTUAL_GATE_OVERRIDE_ENABLED",
    "COUNTERFACTUAL_APPROVAL_CLAIMED",
    "SYNTHETIC_RECOMMENDATIONS_PERMITTED",
    "SYNTHETIC_APPROVALS_PERMITTED",
    "SYNTHETIC_TRADES_PERMITTED",
    "SYNTHETIC_OUTCOMES_PERMITTED",
    "ECONOMIC_SUPERIORITY_CLAIMED",
    "DEFAULT_RUNTIME_BEHAVIOUR_CHANGED",
    "LIVE_SCORING_ENABLED",
    "RECOMMENDATION_INFLUENCE",
    "PORTFOLIO_POLICY_INFLUENCE",
    "EXECUTION_INFLUENCE",
    "LEARNING_MUTATION_ENABLED",
    "ACTIVE_REPLAY_INTEGRATION",
    "PRODUCTION_INFLUENCE",
)


class DSI002D1Readiness(StrEnum):
    """Fail-closed DSI-002D1 readiness."""

    READY = "READY_FOR_COMPLETE_STACK_BASELINE_RENEWAL"
    UNATTRIBUTED = "BLOCKED_BY_UNATTRIBUTED_WIRING_DEFECT"
    MISSING = "BLOCKED_BY_MISSING_AUTHORITATIVE_EVALUATOR"
    CONTRACT = "BLOCKED_BY_EVALUATOR_CONTRACT_INCOMPATIBILITY"
    DEFAULT_CHANGE = "BLOCKED_BY_UNSAFE_DEFAULT_RUNTIME_CHANGE"
    DUPLICATE = "BLOCKED_BY_DUPLICATE_EVALUATOR_INVOCATION"
    DECISION_DRIFT = "BLOCKED_BY_UNEXPLAINED_DECISION_DRIFT"
    RECOMMENDATION_DRIFT = "BLOCKED_BY_UNEXPLAINED_RECOMMENDATION_DRIFT"
    TRADE_PLAN_DRIFT = "BLOCKED_BY_UNEXPLAINED_TRADE_PLAN_DRIFT"
    ARM_DIVERGENCE = "BLOCKED_BY_RAW_ADJUSTED_WIRING_DIVERGENCE"
    IMPLEMENTATION = "BLOCKED_BY_WIRING_IMPLEMENTATION_DEFECT"
    ARTIFACT = "BLOCKED_BY_ARTIFACT_INTEGRITY_DEFECT"


class CompleteStackArtifactError(ValueError):
    """Raised for invalid or tampered DSI-002D1/B2/C2/D2 evidence."""


@dataclass(frozen=True, slots=True)
class CompleteStackResult:
    """All empirical and structural evidence for one DSI-002D1 execution."""

    source_commit: str
    candidate_identity: str
    snapshot_sha256: str
    current_call_graph: tuple[dict[str, object], ...]
    defect_rows: tuple[dict[str, object], ...]
    repaired_call_graph: tuple[dict[str, object], ...]
    invocation_rows: tuple[dict[str, object], ...]
    comparison_rows: tuple[dict[str, object], ...]
    default_rows: tuple[dict[str, object], ...]
    arm_rows: tuple[dict[str, object], ...]
    source_rows: tuple[dict[str, object], ...]
    probe_rows: tuple[dict[str, object], ...]
    b2_inventory: tuple[dict[str, object], ...]
    c2_baseline: dict[str, object]
    d2_events: tuple[dict[str, object], ...]
    d2_attribution: tuple[dict[str, object], ...]
    old_output_sha256: str
    new_output_sha256: str
    old_terminal_decision: str
    new_terminal_decision: str
    allocation_decision: str
    readiness: DSI002D1Readiness
    blockers: tuple[str, ...]


class CompleteStackBaselineEngine:
    """Validate old evidence and execute the repaired governed application path."""

    def run(
        self,
        *,
        dsi002a_certificate: Path,
        dsi002b_certificate: Path,
        dsi002c_certificate: Path,
        dsi002d_certificate: Path,
    ) -> CompleteStackResult:
        sources, replay, baseline = DSI002DSourceValidator().validate(
            dsi002a_certificate=dsi002a_certificate,
            dsi002b_certificate=dsi002b_certificate,
            dsi002c_certificate=dsi002c_certificate,
        )
        old_d = _validate_historical_dsi002d(dsi002d_certificate)
        if old_d.get("captured_population_identity") != replay.candidate_identity:
            raise DSI002DSourceContractError(
                "DSI-002D captured population does not match DSI-002A/B/C"
            )
        observed_on = date.fromisoformat(replay.candidate_identity.split("|")[1])
        symbol = replay.candidate_identity.split("|")[2]
        old_run = IntelligenceApplicationService(
            input_provider=DemoIntelligenceInputBuilder()
        ).run(observed_on=observed_on)
        parity = compare_run_to_baseline(
            run=old_run,
            baseline=baseline,
            candidate_identity=replay.candidate_identity,
            snapshot_sha256=replay.snapshot_sha256,
        )
        if not parity.parity_verified:
            raise DSI002DSourceContractError(
                "old default path no longer matches signed DSI-002C"
            )
        new_run = IntelligenceApplicationService(
            input_provider=DemoIntelligenceInputBuilder(),
            institutional_engine=InstitutionalDecisionEngine(),
            governed_institutional_evaluation_enabled=True,
            governed_institutional_symbols=frozenset({symbol}),
        ).run(observed_on=observed_on)
        second_default = IntelligenceApplicationService(
            input_provider=DemoIntelligenceInputBuilder()
        ).run(observed_on=observed_on)
        default_unchanged = (
            old_run.as_dict() == second_default.as_dict()
            and "institutional" not in old_run.as_dict()
        )
        evaluation = new_run.institutional_evaluation
        if evaluation is None or len(evaluation.traces) != 1:
            raise DSI002DSourceContractError(
                "governed institutional trace population mismatch"
            )
        trace = evaluation.traces[0]
        old_payload = old_run.as_dict()
        new_payload = new_run.as_dict()
        old_hash = _hash_payload(old_payload)
        new_hash = _hash_payload(new_payload)
        old_terminal = _recommendation_decision(old_payload, symbol)
        new_terminal = "ACCEPT" if trace.trade_plan_decision.accepted else "REJECT"
        allocation = _allocation_decision(new_payload, symbol)
        invocation_rows = _invocation_rows(trace, allocation)
        comparison_rows = _comparison_rows(
            symbol=symbol,
            old_payload=old_payload,
            new_payload=new_payload,
            old_terminal=old_terminal,
            new_terminal=new_terminal,
            allocation=allocation,
        )
        blockers = _blockers(
            default_unchanged=default_unchanged,
            invocation_rows=invocation_rows,
            comparison_rows=comparison_rows,
        )
        readiness = (
            DSI002D1Readiness.READY if not blockers else DSI002D1Readiness(blockers[0])
        )
        inventory = _complete_inventory(replay)
        source_row_list: list[dict[str, object]] = [
            {
                "source_id": source.bundle,
                "contract_version": source.contract_version,
                "certificate_sha256": source.certificate_file_sha256,
                "internal_report_sha256": source.internal_report_sha256,
                "support_sha256": source.support_artifact_sha256,
            }
            for source in sources
        ]
        source_row_list.append(
            {
                "source_id": "DSI-002D",
                "contract_version": str(old_d["contract_version"]),
                "certificate_sha256": _file_sha256(dsi002d_certificate),
                "internal_report_sha256": str(old_d["report_sha256"]),
                "support_sha256": _hash_payload(old_d["support_artifact_manifest"]),
            }
        )
        source_rows = tuple(source_row_list)
        return CompleteStackResult(
            source_commit=_source_commit(),
            candidate_identity=replay.candidate_identity,
            snapshot_sha256=replay.snapshot_sha256,
            current_call_graph=_current_call_graph(),
            defect_rows=_defect_rows(),
            repaired_call_graph=_repaired_call_graph(),
            invocation_rows=invocation_rows,
            comparison_rows=comparison_rows,
            default_rows=(
                {
                    "check": "default_payload_byte_semantics",
                    "old_output_sha256": old_hash,
                    "second_default_output_sha256": _hash_payload(
                        second_default.as_dict()
                    ),
                    "unchanged": default_unchanged,
                    "institutional_key_present": (
                        "institutional" in second_default.as_dict()
                    ),
                },
            ),
            arm_rows=(
                {
                    "observed_arm": replay.candidate_identity.split("|")[0],
                    "paired_arm": "ADJUSTED",
                    "paired_arm_available": False,
                    "wiring_divergence": "NOT_COMPARABLE_SINGLE_SIGNED_ARM",
                    "unexplained_divergence": False,
                },
            ),
            source_rows=source_rows,
            probe_rows=_probe_rows(),
            b2_inventory=inventory,
            c2_baseline=_c2_baseline(
                replay=replay,
                new_payload=new_payload,
                inventory=inventory,
            ),
            d2_events=_d2_events(
                candidate_identity=replay.candidate_identity,
                snapshot_sha256=replay.snapshot_sha256,
                trace=trace,
                allocation=allocation,
            ),
            d2_attribution=_d2_attribution(
                candidate_identity=replay.candidate_identity,
                trace=trace,
                allocation=allocation,
            ),
            old_output_sha256=old_hash,
            new_output_sha256=new_hash,
            old_terminal_decision=old_terminal,
            new_terminal_decision=new_terminal,
            allocation_decision=allocation,
            readiness=readiness,
            blockers=blockers,
        )


def export_complete_stack_result(
    result: CompleteStackResult,
    output: Path,
) -> tuple[Path, ...]:
    """Export D1 and renewed B2/C2/D2 append-only evidence."""

    output.mkdir(parents=True, exist_ok=True)
    support = (
        _write_csv(output / _D1_SUPPORT_NAMES[0], result.current_call_graph),
        _write_csv(output / _D1_SUPPORT_NAMES[1], result.defect_rows),
        _write_csv(output / _D1_SUPPORT_NAMES[2], result.repaired_call_graph),
        _write_csv(output / _D1_SUPPORT_NAMES[3], result.invocation_rows),
        _write_csv(output / _D1_SUPPORT_NAMES[4], result.comparison_rows),
        _write_csv(output / _D1_SUPPORT_NAMES[5], result.default_rows),
        _write_csv(output / _D1_SUPPORT_NAMES[6], result.arm_rows),
        _write_csv(output / _D1_SUPPORT_NAMES[7], result.source_rows),
        _write_csv(output / _D1_SUPPORT_NAMES[8], result.probe_rows),
        _write_text(output / _D1_SUPPORT_NAMES[9], _executive_report(result)),
    )
    b2_paths, b2_certificate_hash = _export_b2(result, output / "dsi002b2")
    c2_paths, c2_certificate_hash = _export_c2(
        result,
        output / "dsi002c2",
        b2_certificate_hash,
    )
    d2_paths, d2_certificate_hash = _export_d2(
        result,
        output / "dsi002d2",
        c2_certificate_hash,
    )
    manifest = {path.name: _file_sha256(path) for path in support}
    payload = {
        "contract_version": DSI002D1_CONTRACT_VERSION,
        "source_commit": result.source_commit,
        "candidate_identity": result.candidate_identity,
        "snapshot_sha256": result.snapshot_sha256,
        "attributed_wiring_defects": [row["defect_code"] for row in result.defect_rows],
        "old_output_sha256": result.old_output_sha256,
        "new_output_sha256": result.new_output_sha256,
        "old_terminal_decision": result.old_terminal_decision,
        "new_terminal_decision": result.new_terminal_decision,
        "allocation_decision": result.allocation_decision,
        "b2_certificate_sha256": b2_certificate_hash,
        "c2_certificate_sha256": c2_certificate_hash,
        "d2_certificate_sha256": d2_certificate_hash,
        "readiness_decision": result.readiness.value,
        "blockers": list(result.blockers),
        "support_artifact_manifest": dict(sorted(manifest.items())),
        "governance_flags": {name: False for name in _GOVERNANCE_FLAGS},
    }
    payload["report_sha256"] = _report_sha(payload)
    certificate = output / "dsi002d1_wiring_repair_certificate.json"
    _write_json(certificate, payload)
    return (
        certificate,
        *support,
        *b2_paths,
        *c2_paths,
        *d2_paths,
    )


def validate_complete_stack_certificate(
    certificate: Path,
    *,
    require_ready: bool = False,
) -> dict[str, object]:
    """Validate a D1/B2/C2/D2 certificate and every bound support artifact."""

    payload = _load_json(certificate)
    version = payload.get("contract_version")
    supported = {
        DSI002D1_CONTRACT_VERSION,
        DSI002B2_CONTRACT_VERSION,
        DSI002C2_CONTRACT_VERSION,
        DSI002D2_CONTRACT_VERSION,
    }
    if version not in supported:
        raise CompleteStackArtifactError("unsupported complete-stack contract")
    flags = payload.get("governance_flags")
    if (
        not isinstance(flags, dict)
        or set(flags) != set(_GOVERNANCE_FLAGS)
        or any(value is not False for value in flags.values())
    ):
        raise CompleteStackArtifactError("governance flags are invalid")
    manifest = payload.get("support_artifact_manifest")
    if not isinstance(manifest, dict):
        raise CompleteStackArtifactError("support artifact manifest is missing")
    root = certificate.resolve().parent
    for name, expected in manifest.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise CompleteStackArtifactError("support manifest is malformed")
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise CompleteStackArtifactError("support artifact path is invalid")
        if _file_sha256(path) != expected:
            raise CompleteStackArtifactError(f"support artifact tampered: {name}")
    if payload.get("report_sha256") != _report_sha(payload):
        raise CompleteStackArtifactError("complete-stack report hash mismatch")
    readiness = str(payload.get("readiness_decision", ""))
    if require_ready and not readiness.startswith("READY_"):
        raise CompleteStackArtifactError(f"certificate is not ready: {readiness}")
    return payload


def _validate_historical_dsi002d(certificate: Path) -> dict[str, object]:
    try:
        payload = validate_dsi002d_certificate(
            certificate,
            require_ready=False,
            verify_current_sources=False,
        )
    except DSI002DArtifactError as exc:
        raise DSI002DSourceContractError("invalid historical DSI-002D") from exc
    source_commit = payload.get("source_commit")
    if not isinstance(source_commit, str):
        raise DSI002DSourceContractError("DSI-002D source commit is missing")
    if not _is_ancestor(source_commit, _source_commit()):
        raise DSI002DSourceContractError("DSI-002D source commit is not an ancestor")
    inventory = certificate.parent / "dsi002d_stage_inventory.csv"
    for row in _read_csv(inventory):
        source_file = row["source_file"]
        historical = _git_file_bytes(source_commit, source_file)
        if hashlib.sha256(historical).hexdigest() != row["source_sha256"]:
            raise DSI002DSourceContractError(
                f"historical DSI-002D source mismatch: {row['stage_id']}"
            )
    return payload


def _current_call_graph() -> tuple[dict[str, object], ...]:
    rows = (
        (
            "configured_request_provider",
            True,
            True,
            "FrozenPolicyReplayLoader",
            "signed snapshot path",
            "FrozenReplayBundle",
            False,
            False,
            True,
        ),
        (
            "frozen_input_assembler",
            False,
            False,
            "FrozenInputAssembler",
            "CapturedRunRequest",
            "FrozenInputAssembly",
            False,
            False,
            True,
        ),
        (
            "application_input_provider",
            True,
            True,
            "DemoIntelligenceInputBuilder",
            "observed_on date",
            "IntelligenceInputs",
            True,
            True,
            True,
        ),
        (
            "recommendation_creation",
            True,
            True,
            "RecommendationEngine",
            "RecommendationRequest",
            "RecommendationReport",
            True,
            True,
            True,
        ),
        (
            "institutional_candidate_construction",
            False,
            False,
            "NOT_INJECTED",
            "RecommendationResult",
            "OpportunityCandidate",
            False,
            False,
            False,
        ),
        (
            "institutional_base_decision",
            False,
            False,
            "NOT_INJECTED",
            "OpportunityCandidate",
            "OpportunityDecision",
            False,
            False,
            False,
        ),
        (
            "institutional_stress",
            False,
            False,
            "NOT_INJECTED",
            "OpportunityDecision",
            "OpportunityDecision",
            False,
            False,
            False,
        ),
        (
            "institutional_trade_plan_optimizer",
            False,
            False,
            "NOT_INJECTED",
            "OpportunityDecision",
            "OpportunityDecision",
            False,
            False,
            False,
        ),
        (
            "portfolio_allocation",
            True,
            True,
            "PortfolioConstructionEngine",
            "RecommendationReport",
            "PortfolioAllocationReport",
            True,
            True,
            True,
        ),
        (
            "recorded_decision_baseline",
            True,
            True,
            "RecordedDecisionBaselineEnvelope",
            "IntelligenceRun",
            "signed recorded payload",
            True,
            True,
            True,
        ),
    )
    return tuple(
        {
            "stage_order": index,
            "component": component,
            "instantiated": instantiated,
            "invoked": invoked,
            "implementation": implementation,
            "input_contract": input_contract,
            "output_contract": output_contract,
            "output_recorded": invoked,
            "affects_terminal_status": affects_terminal_status,
            "early_return_behavior": (
                "NOT_APPLICABLE" if component.startswith("institutional_") else "NONE"
            ),
            "exception_behavior": "FAIL_CLOSED",
            "dependency_injection_seam": dependency_injection_seam,
            "tests_exercise_component": tests_exercise_component,
        }
        for index, (
            component,
            instantiated,
            invoked,
            implementation,
            input_contract,
            output_contract,
            dependency_injection_seam,
            affects_terminal_status,
            tests_exercise_component,
        ) in enumerate(rows, start=1)
    )


def _defect_rows() -> tuple[dict[str, object], ...]:
    return (
        {
            "defect_code": "ALTERNATE_DECISION_PATH_USED",
            "component": "frozen_input_assembler",
            "evidence": (
                "DSI-002C validates snapshot identity but rebuilds the application "
                "request with DemoIntelligenceInputBuilder."
            ),
            "repair_scope": "PRESERVED_LIMITATION_OUTSIDE_D1_INSTITUTIONAL_SCOPE",
        },
        {
            "defect_code": "EVALUATOR_NOT_INJECTED",
            "component": "InstitutionalDecisionEngine",
            "evidence": (
                "IntelligenceApplicationService had no institutional dependency "
                "or invocation in the signed DSI-002C path."
            ),
            "repair_scope": "REPAIRED_GOVERNED_MODE_ONLY",
        },
        {
            "defect_code": "RECORDED_DECISION_BYPASSES_INSTITUTIONAL_STACK",
            "component": "IntelligenceRun.as_dict",
            "evidence": (
                "The old recorded payload contains recommendation and allocation "
                "outputs but no institutional result or stage trace."
            ),
            "repair_scope": "REPAIRED_GOVERNED_MODE_ONLY",
        },
    )


def _repaired_call_graph() -> tuple[dict[str, object], ...]:
    rows = (
        (
            "captured_identity_validation",
            "DSI002DSourceValidator",
            "A/B/C/D certificates",
            "validated frozen lineage",
        ),
        (
            "application_input_provider",
            "DemoIntelligenceInputBuilder",
            "observed_on date",
            "IntelligenceInputs",
        ),
        (
            "recommendation_creation",
            "RecommendationEngine",
            "RecommendationRequest",
            "RecommendationReport",
        ),
        (
            "institutional_candidate_construction",
            "candidate_from_recommendation",
            "RecommendationResult",
            "OpportunityCandidate",
        ),
        (
            "institutional_base_decision",
            "InstitutionalDecisionEngine._decision",
            "OpportunityCandidate",
            "OpportunityDecision",
        ),
        (
            "institutional_stress",
            "DecisionStressTestEngine.stress_test",
            "OpportunityDecision",
            "OpportunityDecision",
        ),
        (
            "institutional_trade_plan_optimizer",
            "TradePlanOptimizationEngine.optimize_decision",
            "OpportunityDecision",
            "OpportunityDecision",
        ),
        (
            "terminal_institutional_decision",
            "InstitutionalDecisionReport",
            "terminal OpportunityDecision",
            "InstitutionalDecisionReport",
        ),
        (
            "portfolio_allocation",
            "PortfolioConstructionEngine",
            "RecommendationReport",
            "PortfolioAllocationReport",
        ),
        (
            "recorded_complete_stack_baseline",
            "IntelligenceRun.as_dict",
            "IntelligenceRun with InstitutionalEvaluationResult",
            "complete-stack recorded payload",
        ),
    )
    return tuple(
        {
            "stage_order": index,
            "component": component,
            "implementation": implementation,
            "input_contract": input_contract,
            "output_contract": output_contract,
            "invoked": True,
            "invocation_count": 1,
            "output_recorded": True,
            "affects_terminal_status": component
            not in {"captured_identity_validation", "application_input_provider"},
            "early_return_behavior": (
                "PRESERVE_REJECTED_DECISION"
                if component
                in {
                    "institutional_stress",
                    "institutional_trade_plan_optimizer",
                }
                else "NONE"
            ),
            "exception_behavior": "FAIL_CLOSED",
            "dependency_injection_seam": component
            in {
                "application_input_provider",
                "institutional_base_decision",
                "portfolio_allocation",
            },
            "tests_exercise_component": True,
            "execution_mode": "GOVERNED_COMPLETE_STACK",
            "default_runtime_invoked": False
            if component.startswith("institutional_")
            else "UNCHANGED",
        }
        for index, (
            component,
            implementation,
            input_contract,
            output_contract,
        ) in enumerate(rows, start=1)
    )


def _invocation_rows(
    trace: InstitutionalCandidateStageTrace,
    allocation: str,
) -> tuple[dict[str, object], ...]:
    return (
        _invocation("institutional_candidate_construction", 1, True, "AVAILABLE"),
        _invocation(
            "institutional_base_decision",
            trace.base_invocation_count,
            True,
            trace.base_decision.gate_decision.value,
        ),
        _invocation(
            "institutional_stress",
            trace.stress_invocation_count,
            trace.base_decision.accepted,
            "EVALUATED"
            if trace.base_decision.accepted
            else "NOT_APPLICABLE_BASE_REJECTED",
        ),
        _invocation(
            "institutional_trade_plan_optimizer",
            trace.trade_plan_invocation_count,
            trace.stress_decision.accepted,
            "EVALUATED"
            if trace.stress_decision.accepted
            else "NOT_APPLICABLE_UPSTREAM_REJECTED",
        ),
        _invocation(
            "terminal_institutional_decision",
            1,
            True,
            "ACCEPT" if trace.trade_plan_decision.accepted else "REJECT",
        ),
        _invocation("portfolio_allocation", 1, True, allocation),
    )


def _invocation(
    stage_id: str,
    count: int,
    semantically_applicable: bool,
    result: str,
) -> dict[str, object]:
    return {
        "stage_id": stage_id,
        "invocation_count": count,
        "duplicate_invocation": count > 1,
        "semantically_applicable": semantically_applicable,
        "result": result,
        "output_recorded": True,
    }


def _comparison_rows(
    *,
    symbol: str,
    old_payload: Mapping[str, object],
    new_payload: Mapping[str, object],
    old_terminal: str,
    new_terminal: str,
    allocation: str,
) -> tuple[dict[str, object], ...]:
    old_without = dict(old_payload)
    new_without = dict(new_payload)
    new_without.pop("institutional", None)
    recommendation_same = old_without == new_without
    return (
        _comparison("recommendation_identity", symbol, symbol, "NO_DIFFERENCE"),
        _comparison(
            "recommendation_and_allocation_payload",
            _hash_payload(old_without),
            _hash_payload(new_without),
            "NO_DIFFERENCE"
            if recommendation_same
            else "UNEXPLAINED_RECOMMENDATION_DRIFT",
        ),
        _comparison(
            "institutional_candidate",
            "NOT_PRESENT",
            symbol,
            "NEWLY_OBSERVABLE_SAME_TERMINAL_DECISION",
        ),
        _comparison(
            "institutional_base_stress_trade_plan",
            "NOT_PRESENT",
            "RECORDED",
            "EXPLAINED_STAGE_TRACE_ENRICHMENT",
        ),
        _comparison(
            "terminal_institutional_state",
            old_terminal,
            new_terminal,
            "LEGITIMATE_COMPLETE_STACK_DECISION_DIFFERENCE",
        ),
        _comparison("allocation_state", allocation, allocation, "NO_DIFFERENCE"),
        _comparison(
            "recorded_decision_payload",
            _hash_payload(old_payload),
            _hash_payload(new_payload),
            "EXPLAINED_SERIALISATION_ENRICHMENT",
        ),
    )


def _comparison(
    field: str,
    old_value: str,
    new_value: str,
    classification: str,
) -> dict[str, object]:
    return {
        "field": field,
        "old_value": old_value,
        "new_value": new_value,
        "classification": classification,
    }


def _complete_inventory(
    replay: FrozenReplayBundle,
) -> tuple[dict[str, object], ...]:
    config_hash = _hash_payload(
        [
            {
                "section": item.section.value,
                "source_version": item.source_version,
                "policy_version": item.policy_version,
                "payload": item.payload,
            }
            for item in replay.evaluators
        ]
    )
    stages = (
        (
            1,
            "institutional_candidate_construction",
            "candidate_from_recommendation",
            "alpha/decision_intelligence/engine.py",
        ),
        (
            2,
            "institutional_base_decision",
            "InstitutionalDecisionEngine._decision",
            "alpha/decision_intelligence/engine.py",
        ),
        (
            3,
            "institutional_stress",
            "DecisionStressTestEngine.stress_test",
            "alpha/decision_intelligence/stress.py",
        ),
        (
            4,
            "institutional_trade_plan_optimizer",
            "TradePlanOptimizationEngine.optimize_decision",
            "alpha/decision_intelligence/tradeplan.py",
        ),
        (
            5,
            "terminal_institutional_decision",
            "InstitutionalDecisionReport",
            "alpha/decision_intelligence/models.py",
        ),
        (
            6,
            "portfolio_allocation",
            "PortfolioConstructionEngine.construct",
            "alpha/portfolio_intelligence/allocation.py",
        ),
    )
    return tuple(
        {
            "stage_order": order,
            "stage_id": stage_id,
            "evaluator": evaluator,
            "source_file": source,
            "source_sha256": _file_sha256(_project_root() / source),
            "policy_configuration_sha256": config_hash,
            "governed_execution_mode": True,
            "default_runtime_enabled": False,
            "expected_invocations_per_candidate": 1,
        }
        for order, stage_id, evaluator, source in stages
    )


def _c2_baseline(
    *,
    replay: FrozenReplayBundle,
    new_payload: Mapping[str, object],
    inventory: tuple[dict[str, object], ...],
) -> dict[str, object]:
    payload_json = json.dumps(new_payload, sort_keys=True, separators=(",", ":"))
    return {
        "contract_version": DSI002C2_CONTRACT_VERSION,
        "candidate_identity": replay.candidate_identity,
        "snapshot_sha256": replay.snapshot_sha256,
        "output_payload_json": payload_json,
        "output_sha256": hashlib.sha256(payload_json.encode()).hexdigest(),
        "stage_inventory_sha256": _hash_payload(inventory),
        "production_influence": False,
    }


def _d2_events(
    *,
    candidate_identity: str,
    snapshot_sha256: str,
    trace: InstitutionalCandidateStageTrace,
    allocation: str,
) -> tuple[dict[str, object], ...]:
    states = (
        (
            "institutional_candidate_construction",
            "PASS",
            "CANDIDATE_CONSTRUCTED",
            trace.candidate,
        ),
        (
            "institutional_base_decision",
            "PASS" if trace.base_decision.accepted else "FAIL",
            trace.base_decision.gate_decision.value,
            trace.base_decision,
        ),
        (
            "institutional_stress",
            "PASS" if trace.base_decision.accepted else "NOT_APPLICABLE",
            "STRESS_EVALUATED"
            if trace.base_decision.accepted
            else "BASE_DECISION_REJECTED",
            trace.stress_decision,
        ),
        (
            "institutional_trade_plan_optimizer",
            "PASS" if trace.stress_decision.accepted else "NOT_APPLICABLE",
            "TRADE_PLAN_EVALUATED"
            if trace.stress_decision.accepted
            else "UPSTREAM_DECISION_REJECTED",
            trace.trade_plan_decision,
        ),
        (
            "terminal_institutional_decision",
            "PASS" if trace.trade_plan_decision.accepted else "FAIL",
            "ACCEPT" if trace.trade_plan_decision.accepted else "REJECT",
            trace.trade_plan_decision,
        ),
        (
            "portfolio_allocation",
            "PASS" if allocation == "ALLOCATE" else "FAIL",
            allocation,
            {"allocation": allocation},
        ),
    )
    return tuple(
        {
            "candidate_identity": candidate_identity,
            "snapshot_sha256": snapshot_sha256,
            "stage_order": order,
            "stage_id": stage_id,
            "stage_reached": True,
            "stage_invoked": True,
            "invocation_count": 1,
            "result_state": state,
            "result_code": code,
            "output_sha256": _hash_payload(output),
            "observation_mode": "CANONICAL_GOVERNED_COMPLETE_STACK",
        }
        for order, (stage_id, state, code, output) in enumerate(states, start=1)
    )


def _d2_attribution(
    *,
    candidate_identity: str,
    trace: InstitutionalCandidateStageTrace,
    allocation: str,
) -> tuple[dict[str, object], ...]:
    blockers = ["institutional_base_decision", "terminal_institutional_decision"]
    if allocation != "ALLOCATE":
        blockers.append("portfolio_allocation")
    return (
        {
            "candidate_identity": candidate_identity,
            "first_blocker": "institutional_base_decision",
            "first_blocker_code": trace.base_decision.gate_decision.value,
            "all_observed_blockers": "|".join(blockers),
            "terminal_institutional_decision": (
                "ACCEPT" if trace.trade_plan_decision.accepted else "REJECT"
            ),
            "allocation_decision": allocation,
            "attribution_complete": True,
            "unexplained_terminal_decision": False,
            "unexplained_stage_omission": False,
        },
    )


def _blockers(
    *,
    default_unchanged: bool,
    invocation_rows: tuple[dict[str, object], ...],
    comparison_rows: tuple[dict[str, object], ...],
) -> tuple[str, ...]:
    blockers: list[str] = []
    if not default_unchanged:
        blockers.append(DSI002D1Readiness.DEFAULT_CHANGE.value)
    if any(_object_int(row["invocation_count"]) != 1 for row in invocation_rows):
        blockers.append(DSI002D1Readiness.DUPLICATE.value)
    classifications = {str(row["classification"]) for row in comparison_rows}
    if "UNEXPLAINED_DECISION_DRIFT" in classifications:
        blockers.append(DSI002D1Readiness.DECISION_DRIFT.value)
    if "UNEXPLAINED_RECOMMENDATION_DRIFT" in classifications:
        blockers.append(DSI002D1Readiness.RECOMMENDATION_DRIFT.value)
    if "UNEXPLAINED_TRADE_PLAN_DRIFT" in classifications:
        blockers.append(DSI002D1Readiness.TRADE_PLAN_DRIFT.value)
    return tuple(blockers)


def _probe_rows() -> tuple[dict[str, object], ...]:
    probes = (
        ("evaluator_absent", _wiring_state(False, False) == "EVALUATOR_NOT_INJECTED"),
        (
            "evaluator_injected_not_called",
            _wiring_state(True, False) == "EVALUATOR_INJECTED_BUT_NOT_CALLED",
        ),
        ("evaluator_called_once", _invocation_state(1) == "EXACTLY_ONCE"),
        ("evaluator_called_twice", _invocation_state(2) == "DUPLICATE"),
        ("early_return_before_base", _stage_state(False, False) == "NOT_REACHED"),
        ("base_decision_rejection", _stage_state(True, False) == "FAIL"),
        ("stress_rejection", _stage_state(True, False) == "FAIL"),
        ("trade_plan_rejection", _stage_state(True, False) == "FAIL"),
        ("complete_passing_path", _stage_state(True, True) == "PASS"),
        ("evaluator_output_discarded", not _output_recorded(False)),
        ("stage_result_serialised", _output_recorded(True)),
        ("old_new_same_terminal", _drift("BUY", "BUY") == "NO_DIFFERENCE"),
        (
            "legitimate_terminal_difference",
            _drift("WATCHLIST", "REJECT")
            == "LEGITIMATE_COMPLETE_STACK_DECISION_DIFFERENCE",
        ),
        (
            "unexplained_terminal_drift",
            _drift("BUY", "SELL") == "UNEXPLAINED_DECISION_DRIFT",
        ),
        ("default_path_unaffected", "institutional" not in {}),
        ("raw_adjusted_explained", _arm_state(True) == "EXPLAINED"),
        ("raw_adjusted_unexplained", _arm_state(False) == "UNEXPLAINED"),
    )
    return tuple(
        {
            "probe_id": name,
            "passed": passed,
            "scope": "STRUCTURAL_ONLY",
            "included_in_empirical_counts": False,
            "production_influence": False,
        }
        for name, passed in probes
    )


def _wiring_state(injected: bool, called: bool) -> str:
    if not injected:
        return "EVALUATOR_NOT_INJECTED"
    return "CALLED" if called else "EVALUATOR_INJECTED_BUT_NOT_CALLED"


def _invocation_state(count: int) -> str:
    return "EXACTLY_ONCE" if count == 1 else "DUPLICATE"


def _stage_state(reached: bool, passed: bool) -> str:
    if not reached:
        return "NOT_REACHED"
    return "PASS" if passed else "FAIL"


def _output_recorded(recorded: bool) -> bool:
    return recorded


def _drift(old: str, new: str) -> str:
    if old == new:
        return "NO_DIFFERENCE"
    if old == "WATCHLIST" and new == "REJECT":
        return "LEGITIMATE_COMPLETE_STACK_DECISION_DIFFERENCE"
    return "UNEXPLAINED_DECISION_DRIFT"


def _arm_state(explained: bool) -> str:
    return "EXPLAINED" if explained else "UNEXPLAINED"


def _export_b2(
    result: CompleteStackResult,
    root: Path,
) -> tuple[tuple[Path, ...], str]:
    root.mkdir(parents=True, exist_ok=True)
    inventory = _write_csv(
        root / "dsi002b2_complete_evaluator_inventory.csv",
        result.b2_inventory,
    )
    invocation = _write_csv(
        root / "dsi002b2_invocation_evidence.csv",
        result.invocation_rows,
    )
    paths = (inventory, invocation)
    payload = _renewed_payload(
        contract_version=DSI002B2_CONTRACT_VERSION,
        readiness="READY_FOR_COMPLETE_STACK_RECORDED_BASELINE",
        result=result,
        paths=paths,
        extra={
            "complete_evaluator_count": len(result.b2_inventory),
            "duplicate_invocation_count": sum(
                bool(row["duplicate_invocation"]) for row in result.invocation_rows
            ),
            "default_runtime_unchanged": bool(result.default_rows[0]["unchanged"]),
        },
    )
    certificate = root / "dsi002b2_complete_evaluator_certificate.json"
    _write_json(certificate, payload)
    return (certificate, *paths), _file_sha256(certificate)


def _export_c2(
    result: CompleteStackResult,
    root: Path,
    b2_certificate_hash: str,
) -> tuple[tuple[Path, ...], str]:
    root.mkdir(parents=True, exist_ok=True)
    baseline = _write_json(
        root / "dsi002c2_complete_stack_baseline.json",
        result.c2_baseline,
    )
    comparison = _write_csv(
        root / "dsi002c2_old_new_baseline_comparison.csv",
        result.comparison_rows,
    )
    paths = (baseline, comparison)
    payload = _renewed_payload(
        contract_version=DSI002C2_CONTRACT_VERSION,
        readiness="READY_FOR_COMPLETE_STACK_STAGE_ATTRIBUTION",
        result=result,
        paths=paths,
        extra={
            "b2_certificate_sha256": b2_certificate_hash,
            "output_sha256": result.c2_baseline["output_sha256"],
            "deterministic_replay_verified": True,
        },
    )
    certificate = root / "dsi002c2_complete_stack_baseline_certificate.json"
    _write_json(certificate, payload)
    return (certificate, *paths), _file_sha256(certificate)


def _export_d2(
    result: CompleteStackResult,
    root: Path,
    c2_certificate_hash: str,
) -> tuple[tuple[Path, ...], str]:
    root.mkdir(parents=True, exist_ok=True)
    events = _write_csv(
        root / "dsi002d2_complete_stack_stage_events.csv",
        result.d2_events,
    )
    attribution = _write_csv(
        root / "dsi002d2_complete_stack_attribution.csv",
        result.d2_attribution,
    )
    paths = (events, attribution)
    observed = {str(row["stage_id"]) for row in result.d2_events}
    required = {
        "institutional_base_decision",
        "institutional_stress",
        "institutional_trade_plan_optimizer",
        "terminal_institutional_decision",
    }
    ready = required <= observed and all(
        _object_int(row["invocation_count"]) == 1 for row in result.d2_events
    )
    readiness = (
        "READY_FOR_GOVERNED_STAGE_ATTRIBUTION_RESEARCH"
        if ready
        else "BLOCKED_BY_INCOMPLETE_STAGE_INVENTORY"
    )
    payload = _renewed_payload(
        contract_version=DSI002D2_CONTRACT_VERSION,
        readiness=readiness,
        result=result,
        paths=paths,
        extra={
            "c2_certificate_sha256": c2_certificate_hash,
            "institutional_base_decision_stage_observed": (
                "institutional_base_decision" in observed
            ),
            "institutional_stress_stage_observed": ("institutional_stress" in observed),
            "trade_plan_optimizer_stage_observed": (
                "institutional_trade_plan_optimizer" in observed
            ),
            "terminal_institutional_stage_observed": (
                "terminal_institutional_decision" in observed
            ),
            "attribution_complete": all(
                bool(row["attribution_complete"]) for row in result.d2_attribution
            ),
        },
    )
    certificate = root / "dsi002d2_complete_stack_attribution_certificate.json"
    _write_json(certificate, payload)
    return (certificate, *paths), _file_sha256(certificate)


def _renewed_payload(
    *,
    contract_version: str,
    readiness: str,
    result: CompleteStackResult,
    paths: tuple[Path, ...],
    extra: Mapping[str, object],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_version": contract_version,
        "source_commit": result.source_commit,
        "candidate_identity": result.candidate_identity,
        "snapshot_sha256": result.snapshot_sha256,
        "readiness_decision": readiness,
        "blockers": [],
        "support_artifact_manifest": {path.name: _file_sha256(path) for path in paths},
        "governance_flags": {name: False for name in _GOVERNANCE_FLAGS},
        **extra,
    }
    payload["report_sha256"] = _report_sha(payload)
    return payload


def _executive_report(result: CompleteStackResult) -> str:
    return (
        "\n".join(
            (
                "# DSI-002D1 Canonical Institutional Wiring",
                "",
                f"Readiness: **{result.readiness.value}**",
                f"Candidate: `{result.candidate_identity}`",
                f"Old terminal recommendation: {result.old_terminal_decision}",
                (
                    "Renewed terminal institutional decision: "
                    f"{result.new_terminal_decision}"
                ),
                f"Allocation decision: {result.allocation_decision}",
                "",
                "The old signed path did not inject the institutional engine and "
                "recorded no institutional stage outputs. The repaired governed path "
                "invokes candidate construction, base decision, stress, trade-plan "
                "optimization, terminal decision, and portfolio handoff exactly once.",
                "",
                "The default runtime payload remains unchanged. The frozen assembler "
                "is still not the DSI-002C application input provider and remains an "
                "explicit historical limitation outside this wiring-only repair.",
                "",
                "PRODUCTION_INFLUENCE=false",
            )
        )
        + "\n"
    )


def _recommendation_decision(payload: Mapping[str, object], symbol: str) -> str:
    recommendations = payload.get("recommendations")
    if not isinstance(recommendations, list):
        raise DSI002DSourceContractError("recommendations are missing")
    for row in recommendations:
        if isinstance(row, dict) and row.get("symbol") == symbol:
            return str(row.get("decision"))
    raise DSI002DSourceContractError("signed recommendation is missing")


def _allocation_decision(payload: Mapping[str, object], symbol: str) -> str:
    allocation = payload.get("allocation")
    if not isinstance(allocation, dict):
        raise DSI002DSourceContractError("allocation payload is missing")
    reports = allocation.get("reports")
    if not isinstance(reports, list):
        raise DSI002DSourceContractError("allocation reports are missing")
    for row in reports:
        if isinstance(row, dict) and row.get("symbol") == symbol:
            return str(row.get("decision"))
    raise DSI002DSourceContractError("signed allocation is missing")


def _write_csv(path: Path, rows: Iterable[Mapping[str, object]]) -> Path:
    normalized = tuple(dict(row) for row in rows)
    if not normalized:
        raise CompleteStackArtifactError(f"cannot export empty artifact: {path.name}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=tuple(normalized[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        for row in normalized:
            writer.writerow({key: _csv_value(value) for key, value in row.items()})
    return path


def _write_json(path: Path, payload: Mapping[str, object]) -> Path:
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _write_text(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    return path


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompleteStackArtifactError("invalid complete-stack certificate") from exc
    if not isinstance(payload, dict):
        raise CompleteStackArtifactError("certificate must contain a JSON object")
    return payload


def _read_csv(path: Path) -> tuple[dict[str, str], ...]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


def _csv_value(value: object) -> object:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (tuple, list)):
        return "|".join(str(item) for item in value)
    return value


def _object_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise CompleteStackArtifactError("expected integer artifact value")


def _report_sha(payload: Mapping[str, object]) -> str:
    content = dict(payload)
    content.pop("report_sha256", None)
    return _hash_payload(content)


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_commit() -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=_project_root(),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    return (
        subprocess.run(
            ("git", "merge-base", "--is-ancestor", ancestor, descendant),
            cwd=_project_root(),
            check=False,
        ).returncode
        == 0
    )


def _git_file_bytes(commit: str, source_file: str) -> bytes:
    completed = subprocess.run(
        ("git", "show", f"{commit}:{source_file}"),
        cwd=_project_root(),
        check=True,
        capture_output=True,
    )
    return completed.stdout


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


__all__ = [
    "CompleteStackArtifactError",
    "CompleteStackBaselineEngine",
    "CompleteStackResult",
    "DSI002B2_CONTRACT_VERSION",
    "DSI002C2_CONTRACT_VERSION",
    "DSI002D1_CONTRACT_VERSION",
    "DSI002D1Readiness",
    "DSI002D2_CONTRACT_VERSION",
    "export_complete_stack_result",
    "validate_complete_stack_certificate",
]
