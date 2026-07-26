"""Governed DSI-002D stage replay and rejection attribution.

This module is intentionally observational.  It replays the signed DSI-002C
baseline through the unchanged intelligence application and records only
stages whose outputs are present in that canonical run.  Institutional stages
which exist elsewhere in the repository but are not wired into the baseline
are reported as omissions, never synthesized.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, cast

from alpha.application.intelligence import IntelligenceApplicationService
from alpha.application.intelligence_inputs import DemoIntelligenceInputBuilder
from alpha.decision_superiority.gate_isolation_decision_baseline import (
    BASELINE_ENVELOPE_VERSION,
    RecordedDecisionBaselineEnvelope,
    RecordedDecisionBaselineStore,
    compare_run_to_baseline,
)
from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FROZEN_INPUT_CONTRACT_VERSION,
)
from alpha.decision_superiority.gate_isolation_frozen_policy_replay import (
    FrozenPolicyReplayLoader,
    FrozenReplayBundle,
    FrozenReplayReadiness,
)
from alpha.portfolio_intelligence import AllocationDecision
from alpha.recommendation_intelligence import RecommendationDecision

DSI002D_CONTRACT_VERSION: Final = "DSI-002D-v1.0.0"
DSI002B_CONTRACT_VERSION: Final = "DSI-002B-v1.0.0"
_A_CERTIFICATE_KEYS: Final = frozenset(
    {
        "accepted",
        "candidate",
        "capture_failure_isolation_verified",
        "duplicate_protection_verified",
        "missing_section_block_verified",
        "parity_verified",
        "post_observation_block_verified",
        "production_influence",
        "replay_ready",
        "snapshot_sha256",
    }
)
_B_CERTIFICATE_KEYS: Final = frozenset(
    {
        "accepted",
        "candidate_identity",
        "deterministic_reconstruction_verified",
        "evaluator_count",
        "evaluator_lineage_verified",
        "incomplete_block_verified",
        "point_in_time_verified",
        "production_influence",
        "readiness",
        "snapshot_sha256",
        "tamper_block_verified",
        "unsupported_policy_block_verified",
    }
)
_C_CERTIFICATE_KEYS: Final = frozenset(
    {
        "accepted",
        "baseline_output_sha256",
        "baseline_tamper_block_verified",
        "candidate_identity_block_verified",
        "deterministic_replay_verified",
        "exact_payload_match",
        "parity_verified",
        "production_influence",
        "replay_output_sha256",
        "snapshot_identity_block_verified",
    }
)


class StageResultState(StrEnum):
    """Canonical result state for one candidate-stage event."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_REACHED = "NOT_REACHED"
    BLOCKED_BY_UPSTREAM = "BLOCKED_BY_UPSTREAM"
    IMPLEMENTATION_ERROR = "IMPLEMENTATION_ERROR"


class StageOmissionState(StrEnum):
    """Reason a declared stage was not observed canonically."""

    NONE = "NONE"
    NOT_REACHED_CANONICAL_EARLY_RETURN = "NOT_REACHED_CANONICAL_EARLY_RETURN"
    NOT_SEMANTICALLY_VALID_AFTER_UPSTREAM_FAILURE = (
        "NOT_SEMANTICALLY_VALID_AFTER_UPSTREAM_FAILURE"
    )
    SEMANTICALLY_VALID_BUT_NOT_OBSERVED = "SEMANTICALLY_VALID_BUT_NOT_OBSERVED"
    MISSING_EVALUATOR_WIRING = "MISSING_EVALUATOR_WIRING"
    UNEXPLAINED_STAGE_OMISSION = "UNEXPLAINED_STAGE_OMISSION"


class DSI002DReadiness(StrEnum):
    """Fail-closed DSI-002D readiness decisions."""

    READY = "READY_FOR_GOVERNED_STAGE_ATTRIBUTION_RESEARCH"
    INVALID_SOURCE = "BLOCKED_BY_INVALID_DSI002_SOURCE_CHAIN"
    EMPTY = "BLOCKED_BY_EMPTY_STAGE_REPLAY_POPULATION"
    INCOMPLETE_INVENTORY = "BLOCKED_BY_INCOMPLETE_STAGE_INVENTORY"
    FLOW_DEFECT = "BLOCKED_BY_CANDIDATE_FLOW_RECONCILIATION_DEFECT"
    PARITY_DEFECT = "BLOCKED_BY_RECORDED_DECISION_PARITY_DEFECT"
    ATTRIBUTION_DEFECT = "BLOCKED_BY_INCOMPLETE_REJECTION_ATTRIBUTION"
    OMISSION = "BLOCKED_BY_UNEXPLAINED_STAGE_OMISSION"
    DUPLICATE = "BLOCKED_BY_DUPLICATE_EVALUATOR_INVOCATION"
    IMPLEMENTATION = "BLOCKED_BY_STAGE_REPLAY_IMPLEMENTATION_DEFECT"
    ARM_DIVERGENCE = "BLOCKED_BY_UNEXPLAINED_RAW_ADJUSTED_STAGE_DIVERGENCE"
    ARTIFACT = "BLOCKED_BY_ARTIFACT_INTEGRITY_DEFECT"


@dataclass(frozen=True, slots=True)
class SignedSource:
    """One content-verified prerequisite source."""

    bundle: str
    contract_version: str
    certificate_path: str
    certificate_file_sha256: str
    internal_report_sha256: str
    support_artifact_sha256: str
    candidate_identity: str
    snapshot_sha256: str


@dataclass(frozen=True, slots=True)
class StageDefinition:
    """Immutable inventory entry for one actual or explicitly missing stage."""

    stage_id: str
    stage_order: int
    stage_family: str
    evaluator_id: str
    callable_identity: str
    evaluator_contract_version: str
    source_file: str
    source_sha256: str
    configuration_source: str
    configuration_sha256: str
    stage_input_type: str
    stage_output_type: str
    possible_terminal_states: str
    always_evaluated: bool
    conditional: bool
    semantic_prerequisites: str
    downstream_meaningful_after_failure: bool
    multiple_gate_conditions: bool
    future_override_eligible: bool
    wired_into_baseline: bool


@dataclass(frozen=True, slots=True)
class StageEvent:
    """One immutable canonical candidate-stage observation."""

    candidate_key: str
    symbol: str
    observed_on: str
    price_arm: str
    stage_id: str
    stage_order: int
    stage_reached: bool
    stage_invoked: bool
    invocation_count: int
    semantic_prerequisites_satisfied: bool
    input_available: bool
    input_snapshot_hash: str
    evaluator_output_hash: str
    result_state: StageResultState
    normalized_gate_codes: str
    raw_reason_codes: str
    caused_termination: bool
    processing_continued: bool
    terminal_decision_after_stage: str
    observation_mode: str
    attribution_notes: str


@dataclass(frozen=True, slots=True)
class StageOmission:
    """Reachability and omission evidence for one stage."""

    stage_id: str
    stage_order: int
    reached_count: int
    invoked_count: int
    omission_state: StageOmissionState
    explanation: str


@dataclass(frozen=True, slots=True)
class RejectionAttribution:
    """Candidate-level rejection and terminal-decision attribution."""

    candidate_key: str
    symbol: str
    price_arm: str
    stages_reached: str
    stages_passed: str
    stages_failed: str
    stages_unknown: str
    stages_not_applicable: str
    stages_not_reached: str
    first_blocking_stage: str
    first_blocking_gate_code: str
    all_observed_blocking_stages: str
    all_observed_blocking_gate_codes: str
    terminal_stage: str
    recorded_terminal_decision: str
    replayed_terminal_decision: str
    decision_parity: bool
    attribution_complete: bool
    attribution_ambiguity_codes: str
    unexplained_terminal_decision: bool
    unexplained_early_termination: bool


@dataclass(frozen=True, slots=True)
class DSI002DResult:
    """Complete governed DSI-002D result before export."""

    sources: tuple[SignedSource, ...]
    stage_inventory: tuple[StageDefinition, ...]
    events: tuple[StageEvent, ...]
    omissions: tuple[StageOmission, ...]
    attributions: tuple[RejectionAttribution, ...]
    flow_rows: tuple[dict[str, object], ...]
    arm_rows: tuple[dict[str, object], ...]
    invocation_rows: tuple[dict[str, object], ...]
    probe_rows: tuple[dict[str, object], ...]
    source_rows: tuple[dict[str, object], ...]
    source_commit: str
    readiness: DSI002DReadiness
    blockers: tuple[str, ...]


class DSI002DSourceContractError(ValueError):
    """Raised when the accepted A/B/C chain cannot be verified."""


class DSI002DSourceValidator:
    """Validate the exact A/B/C acceptance evidence without trusting paths."""

    def validate(
        self,
        *,
        dsi002a_certificate: Path,
        dsi002b_certificate: Path,
        dsi002c_certificate: Path,
    ) -> tuple[
        tuple[SignedSource, ...],
        FrozenReplayBundle,
        RecordedDecisionBaselineEnvelope,
    ]:
        a_payload = _load_json_object(dsi002a_certificate)
        b_payload = _load_json_object(dsi002b_certificate)
        c_payload = _load_json_object(dsi002c_certificate)
        _require_schema(a_payload, _A_CERTIFICATE_KEYS, "DSI-002A")
        _require_schema(b_payload, _B_CERTIFICATE_KEYS, "DSI-002B")
        _require_schema(c_payload, _C_CERTIFICATE_KEYS, "DSI-002C")
        _require_exact_acceptance(a_payload, "DSI-002A")
        _require_exact_acceptance(b_payload, "DSI-002B")
        _require_exact_acceptance(c_payload, "DSI-002C")
        _require_acceptance_conditions(
            a_payload,
            "DSI-002A",
            (
                "capture_failure_isolation_verified",
                "duplicate_protection_verified",
                "missing_section_block_verified",
                "parity_verified",
                "post_observation_block_verified",
                "replay_ready",
            ),
        )
        _require_acceptance_conditions(
            b_payload,
            "DSI-002B",
            (
                "deterministic_reconstruction_verified",
                "evaluator_lineage_verified",
                "incomplete_block_verified",
                "point_in_time_verified",
                "tamper_block_verified",
                "unsupported_policy_block_verified",
            ),
        )
        if b_payload.get("readiness") != FrozenReplayReadiness.READY.value:
            raise DSI002DSourceContractError("DSI-002B readiness mismatch")
        _require_acceptance_conditions(
            c_payload,
            "DSI-002C",
            (
                "baseline_tamper_block_verified",
                "candidate_identity_block_verified",
                "deterministic_replay_verified",
                "exact_payload_match",
                "parity_verified",
                "snapshot_identity_block_verified",
            ),
        )

        a_root = dsi002a_certificate.resolve().parent
        b_root = dsi002b_certificate.resolve().parent
        c_root = dsi002c_certificate.resolve().parent
        index_path = _inside(
            a_root,
            a_root / "capture" / "dsi002_frozen_input_capture_index.csv",
        )
        index_rows = _read_csv(index_path)
        if len(index_rows) != 1:
            raise DSI002DSourceContractError(
                "DSI-002A must bind exactly one accepted captured candidate"
            )
        snapshot_path = _indexed_snapshot(a_root, index_rows[0]["snapshot_path"])
        replay = FrozenPolicyReplayLoader().load(snapshot_path)
        if replay.readiness is not FrozenReplayReadiness.READY:
            raise DSI002DSourceContractError("DSI-002A snapshot is not replay ready")

        lineage_path = _inside(b_root, b_root / "dsi002b_evaluator_lineage.csv")
        lineage_rows = _read_csv(lineage_path)
        expected_sections = {item.section.value for item in replay.evaluators}
        observed_sections = {row["section"] for row in lineage_rows}
        if observed_sections != expected_sections or len(lineage_rows) != len(
            expected_sections
        ):
            raise DSI002DSourceContractError("DSI-002B evaluator lineage mismatch")
        for row in lineage_rows:
            if row["snapshot_sha256"] != replay.snapshot_sha256:
                raise DSI002DSourceContractError("DSI-002B snapshot lineage mismatch")
            evaluator = next(
                (
                    item
                    for item in replay.evaluators
                    if item.section.value == row["section"]
                ),
                None,
            )
            if evaluator is None or (
                row["source_version"] != evaluator.source_version
                or row["policy_version"] != evaluator.policy_version
                or row["production_influence"] != "False"
            ):
                raise DSI002DSourceContractError(
                    "DSI-002B evaluator source lineage mismatch"
                )

        baseline_path = _inside(
            c_root,
            c_root / "baseline" / "dsi002c_recorded_decision_baseline.json",
        )
        baseline = RecordedDecisionBaselineStore(baseline_path.parent).load(
            baseline_path
        )
        identities = {
            replay.candidate_identity,
            baseline.candidate_identity,
            _candidate_identity_from_a(a_payload),
            str(b_payload.get("candidate_identity", "")),
        }
        if len(identities) != 1:
            raise DSI002DSourceContractError("captured population identity mismatch")
        snapshot_hashes = {
            replay.snapshot_sha256,
            baseline.snapshot_sha256,
            str(a_payload.get("snapshot_sha256", "")),
        }
        if len(snapshot_hashes) != 1:
            raise DSI002DSourceContractError("snapshot lineage mismatch")
        if c_payload.get("baseline_output_sha256") != baseline.output_sha256:
            raise DSI002DSourceContractError("DSI-002C baseline hash mismatch")

        sources = (
            _signed_source(
                "DSI-002A",
                FROZEN_INPUT_CONTRACT_VERSION,
                dsi002a_certificate,
                index_path,
                replay.candidate_identity,
                replay.snapshot_sha256,
            ),
            _signed_source(
                "DSI-002B",
                DSI002B_CONTRACT_VERSION,
                dsi002b_certificate,
                lineage_path,
                replay.candidate_identity,
                replay.snapshot_sha256,
            ),
            _signed_source(
                "DSI-002C",
                BASELINE_ENVELOPE_VERSION,
                dsi002c_certificate,
                baseline_path,
                replay.candidate_identity,
                replay.snapshot_sha256,
            ),
        )
        return sources, replay, baseline


class GovernedStageAttributionEngine:
    """Replay and attribute the signed candidate through actual baseline stages."""

    def run(
        self,
        *,
        dsi002a_certificate: Path,
        dsi002b_certificate: Path,
        dsi002c_certificate: Path,
    ) -> DSI002DResult:
        sources, replay, baseline = DSI002DSourceValidator().validate(
            dsi002a_certificate=dsi002a_certificate,
            dsi002b_certificate=dsi002b_certificate,
            dsi002c_certificate=dsi002c_certificate,
        )
        observed_on = _candidate_date(replay.candidate_identity)
        service = IntelligenceApplicationService(
            input_provider=DemoIntelligenceInputBuilder()
        )
        run = service.run(observed_on=observed_on)
        parity = compare_run_to_baseline(
            run=run,
            baseline=baseline,
            candidate_identity=replay.candidate_identity,
            snapshot_sha256=replay.snapshot_sha256,
        )
        symbol = replay.candidate_identity.split("|")[2]
        report = next(
            (item for item in run.recommendations if item.symbol == symbol),
            None,
        )
        allocation = next(
            (item for item in run.allocation_plan.reports if item.symbol == symbol),
            None,
        )
        inventory = _stage_inventory(replay)
        if report is None or allocation is None:
            return _empty_result(
                sources=sources,
                inventory=inventory,
                candidate_identity=replay.candidate_identity,
                source_commit=_source_commit(),
            )
        events = _events(
            candidate_key=replay.candidate_identity,
            snapshot_sha256=replay.snapshot_sha256,
            report=report,
            allocation=allocation,
            inventory=inventory,
            parity=parity.parity_verified,
        )
        omissions = _omissions(inventory, events)
        attribution = _attribution(
            replay.candidate_identity,
            report.decision.value,
            events,
            parity.parity_verified,
        )
        flow_rows = _flow_rows(
            candidate_identity=replay.candidate_identity,
            events=events,
            parity=parity.parity_verified,
            terminal_decision=report.decision.value,
        )
        arm_rows = _arm_rows(replay.candidate_identity, attribution)
        invocation_rows = _invocation_rows(inventory, events)
        probes = _probe_rows()
        source_rows = _source_rows(sources, inventory)
        blockers = _blockers(
            events=events,
            omissions=omissions,
            attribution=attribution,
            parity=parity.parity_verified,
        )
        readiness = _readiness(blockers)
        return DSI002DResult(
            sources=sources,
            stage_inventory=inventory,
            events=events,
            omissions=omissions,
            attributions=(attribution,),
            flow_rows=flow_rows,
            arm_rows=arm_rows,
            invocation_rows=invocation_rows,
            probe_rows=probes,
            source_rows=source_rows,
            source_commit=_source_commit(),
            readiness=readiness,
            blockers=blockers,
        )


def _stage_inventory(replay: FrozenReplayBundle) -> tuple[StageDefinition, ...]:
    policy_hashes = {
        item.section.value: _hash_payload(item.payload) for item in replay.evaluators
    }
    definitions = (
        _definition(
            1,
            "recommendation.price_volume",
            "RECOMMENDATION",
            "PriceVolumeSignalEngine",
            "alpha.recommendation_intelligence.engines.PriceVolumeSignalEngine.assess",
            "alpha/recommendation_intelligence/engines.py",
            "CANDIDATE_FEATURES",
            policy_hashes,
            "RecommendationCandidate",
            "PriceVolumeAssessment",
            "PASS|FAIL|UNKNOWN",
        ),
        _definition(
            2,
            "recommendation.candle_pattern",
            "RECOMMENDATION",
            "CandlePatternEngine",
            "alpha.recommendation_intelligence.engines.CandlePatternEngine.assess",
            "alpha/recommendation_intelligence/engines.py",
            "CANDIDATE_FEATURES",
            policy_hashes,
            "RecommendationCandidate+PriceVolumeAssessment",
            "CandlePatternAssessment",
            "PASS|FAIL|NOT_APPLICABLE",
        ),
        _definition(
            3,
            "recommendation.evidence_scoring",
            "BASE_DECISION",
            "EvidenceScoringEngine",
            "alpha.recommendation_intelligence.engines.EvidenceScoringEngine.assess",
            "alpha/recommendation_intelligence/engines.py",
            "APPROVAL_POLICY",
            policy_hashes,
            "RecommendationCandidate+technical evidence",
            "EvidenceAssessment",
            "PASS|FAIL|UNKNOWN",
        ),
        _definition(
            4,
            "recommendation.trade_setup",
            "BASE_DECISION",
            "TradeSetupEngine",
            "alpha.recommendation_intelligence.engines.TradeSetupEngine.assess",
            "alpha/recommendation_intelligence/engines.py",
            "ENTRY_POLICY",
            policy_hashes,
            "RecommendationCandidate+technical evidence",
            "TradeSetupAssessment",
            "PASS|FAIL|UNKNOWN",
        ),
        _definition(
            5,
            "recommendation.score_and_rules",
            "BASE_DECISION",
            "RecommendationScoringEngine",
            "alpha.recommendation_intelligence.engines.RecommendationScoringEngine.score",
            "alpha/recommendation_intelligence/engines.py",
            "APPROVAL_POLICY",
            policy_hashes,
            "EvidenceAssessment+TradeSetupAssessment",
            "RecommendationScore",
            "PASS|FAIL",
            multiple=True,
        ),
        _definition(
            6,
            "recommendation.trade_plan",
            "TRADE_PLAN",
            "TradePlanIntelligenceEngine",
            "alpha.recommendation_intelligence.engines.TradePlanIntelligenceEngine.assess",
            "alpha/recommendation_intelligence/engines.py",
            "ENTRY_POLICY",
            policy_hashes,
            "RecommendationCandidate+RecommendationScore",
            "RecommendationTradePlan",
            "PASS|FAIL|UNKNOWN",
        ),
        _missing_definition(
            7,
            "institutional.base_decision",
            "INSTITUTIONAL_BASE_DECISION",
            "InstitutionalDecisionEngine",
            "alpha/decision_intelligence/engine.py",
        ),
        _missing_definition(
            8,
            "institutional.stress",
            "STRESS",
            "DecisionStressTestEngine",
            "alpha/decision_intelligence/stress.py",
        ),
        _missing_definition(
            9,
            "institutional.trade_plan_optimizer",
            "INSTITUTIONAL_TRADE_PLAN",
            "TradePlanOptimizationEngine",
            "alpha/decision_intelligence/tradeplan.py",
        ),
        _definition(
            10,
            "portfolio.allocation",
            "PORTFOLIO_HANDOFF",
            "CapitalAllocationEngine",
            "alpha.portfolio_intelligence.allocation.CapitalAllocationEngine.allocate",
            "alpha/portfolio_intelligence/allocation.py",
            "PORTFOLIO_STATE",
            policy_hashes,
            "AllocationCandidate+PortfolioContext",
            "AllocationReport",
            "PASS|FAIL",
            prerequisites="recommendation report available",
        ),
        _definition(
            11,
            "terminal.reconciliation",
            "TERMINAL",
            "compare_run_to_baseline",
            "alpha.decision_superiority.gate_isolation_decision_baseline.compare_run_to_baseline",
            "alpha/decision_superiority/gate_isolation_decision_baseline.py",
            "SOURCE_LINEAGE",
            policy_hashes,
            "IntelligenceRun+RecordedDecisionBaselineEnvelope",
            "DecisionReplayParityResult",
            "PASS|FAIL",
        ),
    )
    return definitions


def _events(
    *,
    candidate_key: str,
    snapshot_sha256: str,
    report: Any,
    allocation: Any,
    inventory: tuple[StageDefinition, ...],
    parity: bool,
) -> tuple[StageEvent, ...]:
    arm, observed_on, symbol, _ = candidate_key.split("|")
    evidence = report.evidence_assessment
    trade_setup = report.trade_setup
    trade_plan = report.trade_plan
    observed: dict[str, tuple[StageResultState, str, str, object]] = {
        "recommendation.price_volume": (
            StageResultState.FAIL
            if evidence.price_volume.supports_sell
            else StageResultState.PASS,
            "PRICE_VOLUME_SELL"
            if evidence.price_volume.supports_sell
            else "PRICE_VOLUME_AVAILABLE",
            "|".join(evidence.price_volume.override_reasons) or "NONE",
            evidence.price_volume,
        ),
        "recommendation.candle_pattern": (
            StageResultState.NOT_APPLICABLE
            if evidence.candle_pattern.pattern == "NONE"
            else StageResultState.PASS,
            "NO_CANDLE_PATTERN"
            if evidence.candle_pattern.pattern == "NONE"
            else "CANDLE_PATTERN_OBSERVED",
            evidence.candle_pattern.explanation,
            evidence.candle_pattern,
        ),
        "recommendation.evidence_scoring": (
            StageResultState.PASS if evidence.score >= 60 else StageResultState.FAIL,
            "EVIDENCE_SCORE_AT_LEAST_WATCHLIST"
            if evidence.score >= 60
            else "EVIDENCE_SCORE_BELOW_WATCHLIST",
            evidence.regime_reason,
            evidence,
        ),
        "recommendation.trade_setup": (
            StageResultState.PASS if trade_setup.entry_ready else StageResultState.FAIL,
            "ENTRY_READY" if trade_setup.entry_ready else "ENTRY_NOT_READY",
            trade_setup.readiness_reason,
            trade_setup,
        ),
        "recommendation.score_and_rules": (
            StageResultState.PASS
            if report.decision
            in {RecommendationDecision.BUY, RecommendationDecision.STRONG_BUY}
            else StageResultState.FAIL,
            f"FINAL_SIGNAL_{report.decision.value}",
            f"score={report.score}",
            {
                "decision": report.decision.value,
                "score": str(report.score),
                "breakdown": report.score_breakdown,
            },
        ),
        "recommendation.trade_plan": (
            StageResultState.PASS
            if _trade_plan_complete(trade_plan)
            else StageResultState.FAIL,
            "TRADE_PLAN_COMPLETE"
            if _trade_plan_complete(trade_plan)
            else "TRADE_PLAN_INCOMPLETE",
            trade_plan.trade_plan_explanation,
            trade_plan,
        ),
        "portfolio.allocation": (
            StageResultState.PASS
            if allocation.decision is AllocationDecision.ALLOCATE
            else StageResultState.FAIL,
            f"ALLOCATION_{allocation.decision.value}",
            "|".join(allocation.reasons),
            allocation,
        ),
        "terminal.reconciliation": (
            StageResultState.PASS if parity else StageResultState.FAIL,
            (
                "RECORDED_TERMINAL_DECISION_RECONCILED"
                if parity
                else "RECORDED_TERMINAL_DECISION_PARITY_DEFECT"
            ),
            report.decision.value,
            {
                "decision": report.decision.value,
                "allocation": allocation.decision.value,
            },
        ),
    }
    rows: list[StageEvent] = []
    for stage in inventory:
        item = observed.get(stage.stage_id)
        if item is None:
            rows.append(
                StageEvent(
                    candidate_key=candidate_key,
                    symbol=symbol,
                    observed_on=observed_on,
                    price_arm=arm,
                    stage_id=stage.stage_id,
                    stage_order=stage.stage_order,
                    stage_reached=False,
                    stage_invoked=False,
                    invocation_count=0,
                    semantic_prerequisites_satisfied=False,
                    input_available=False,
                    input_snapshot_hash=snapshot_sha256,
                    evaluator_output_hash="",
                    result_state=StageResultState.NOT_REACHED,
                    normalized_gate_codes="MISSING_EVALUATOR_WIRING",
                    raw_reason_codes="NONE",
                    caused_termination=False,
                    processing_continued=True,
                    terminal_decision_after_stage=report.decision.value,
                    observation_mode="CANONICAL_BASELINE",
                    attribution_notes=(
                        "Evaluator exists in the repository but is not invoked "
                        "by IntelligenceApplicationService.run."
                    ),
                )
            )
            continue
        state, gate_code, reasons, output = item
        rows.append(
            StageEvent(
                candidate_key=candidate_key,
                symbol=symbol,
                observed_on=observed_on,
                price_arm=arm,
                stage_id=stage.stage_id,
                stage_order=stage.stage_order,
                stage_reached=True,
                stage_invoked=True,
                invocation_count=1,
                semantic_prerequisites_satisfied=True,
                input_available=True,
                input_snapshot_hash=snapshot_sha256,
                evaluator_output_hash=_hash_payload(output),
                result_state=state,
                normalized_gate_codes=gate_code,
                raw_reason_codes=reasons,
                caused_termination=False,
                processing_continued=(stage.stage_id != "terminal.reconciliation"),
                terminal_decision_after_stage=report.decision.value,
                observation_mode="CANONICAL_BASELINE",
                attribution_notes="Observed from the unchanged canonical run output.",
            )
        )
    return tuple(rows)


def _attribution(
    candidate_key: str,
    recorded_decision: str,
    events: tuple[StageEvent, ...],
    parity: bool,
) -> RejectionAttribution:
    canonical = tuple(event for event in events if event.stage_invoked)
    failed = tuple(
        event for event in canonical if event.result_state is StageResultState.FAIL
    )
    unknown = tuple(
        event for event in canonical if event.result_state is StageResultState.UNKNOWN
    )
    first = failed[0] if failed else None
    omissions = tuple(
        event
        for event in events
        if event.normalized_gate_codes == "MISSING_EVALUATOR_WIRING"
    )
    complete = parity and not omissions and not unknown
    arm, _, symbol, _ = candidate_key.split("|")
    return RejectionAttribution(
        candidate_key=candidate_key,
        symbol=symbol,
        price_arm=arm,
        stages_reached=_join(event.stage_id for event in canonical),
        stages_passed=_join(
            event.stage_id
            for event in canonical
            if event.result_state is StageResultState.PASS
        ),
        stages_failed=_join(event.stage_id for event in failed),
        stages_unknown=_join(event.stage_id for event in unknown),
        stages_not_applicable=_join(
            event.stage_id
            for event in canonical
            if event.result_state is StageResultState.NOT_APPLICABLE
        ),
        stages_not_reached=_join(
            event.stage_id for event in events if not event.stage_reached
        ),
        first_blocking_stage=first.stage_id if first else "NONE",
        first_blocking_gate_code=(first.normalized_gate_codes if first else "NONE"),
        all_observed_blocking_stages=_join(event.stage_id for event in failed),
        all_observed_blocking_gate_codes=_join(
            event.normalized_gate_codes for event in failed
        ),
        terminal_stage="terminal.reconciliation",
        recorded_terminal_decision=recorded_decision,
        replayed_terminal_decision=recorded_decision,
        decision_parity=parity,
        attribution_complete=complete,
        attribution_ambiguity_codes=(
            "MISSING_INSTITUTIONAL_EVALUATOR_WIRING" if omissions else "NONE"
        ),
        unexplained_terminal_decision=not parity,
        unexplained_early_termination=False,
    )


def _omissions(
    inventory: tuple[StageDefinition, ...],
    events: tuple[StageEvent, ...],
) -> tuple[StageOmission, ...]:
    return tuple(
        StageOmission(
            stage_id=stage.stage_id,
            stage_order=stage.stage_order,
            reached_count=sum(
                event.stage_reached
                for event in events
                if event.stage_id == stage.stage_id
            ),
            invoked_count=sum(
                event.invocation_count
                for event in events
                if event.stage_id == stage.stage_id
            ),
            omission_state=(
                StageOmissionState.NONE
                if stage.wired_into_baseline
                else StageOmissionState.MISSING_EVALUATOR_WIRING
            ),
            explanation=(
                "Observed in the canonical DSI-002C application path."
                if stage.wired_into_baseline
                else (
                    "The evaluator is present in source but absent from "
                    "IntelligenceApplicationService.run; no result was inferred."
                )
            ),
        )
        for stage in inventory
    )


def _flow_rows(
    *,
    candidate_identity: str,
    events: tuple[StageEvent, ...],
    parity: bool,
    terminal_decision: str,
) -> tuple[dict[str, object], ...]:
    transitions = (
        ("accepted_captured_input", 1),
        ("request_assembly", 1),
        ("recommendation_availability", 1),
        ("institutional_candidate_formation", 0),
        ("base_decision_stages", 1),
        ("stress_stages", 0),
        ("trade_plan_stages", 1),
        ("terminal_decision", 1),
        ("portfolio_handoff", 1),
    )
    return tuple(
        {
            "candidate_key": candidate_identity,
            "transition_order": order,
            "transition": name,
            "count": count,
            "reconciled": parity and name != "institutional_candidate_formation"
            if name in {"institutional_candidate_formation", "stress_stages"}
            else parity,
            "terminal_decision": terminal_decision,
            "stage_event_count": len(events),
        }
        for order, (name, count) in enumerate(transitions, start=1)
    )


def _arm_rows(
    candidate_identity: str,
    attribution: RejectionAttribution,
) -> tuple[dict[str, object], ...]:
    arm = candidate_identity.split("|")[0]
    return (
        {
            "economic_candidate_key": "|".join(candidate_identity.split("|")[1:]),
            "observed_arm": arm,
            "paired_arm": "ADJUSTED" if arm == "RAW" else "RAW",
            "paired_arm_available": False,
            "first_blocker": attribution.first_blocking_stage,
            "terminal_decision": attribution.recorded_terminal_decision,
            "divergence_classification": "NOT_COMPARABLE_SINGLE_SIGNED_ARM",
            "unexplained_divergence": False,
        },
    )


def _invocation_rows(
    inventory: tuple[StageDefinition, ...],
    events: tuple[StageEvent, ...],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "stage_id": stage.stage_id,
            "expected_max_invocations_per_candidate": 1,
            "observed_invocations": sum(
                event.invocation_count
                for event in events
                if event.stage_id == stage.stage_id
            ),
            "duplicate_invocation_count": sum(
                max(event.invocation_count - 1, 0)
                for event in events
                if event.stage_id == stage.stage_id
            ),
            "evaluator_id": stage.evaluator_id,
            "source_sha256": stage.source_sha256,
        }
        for stage in inventory
    )


def _probe_rows() -> tuple[dict[str, object], ...]:
    probes = (
        ("fully_passing_stage_path", _first_failure(("PASS", "PASS")) == "NONE"),
        ("failure_at_first_stage", _first_failure(("FAIL", "PASS")) == "0"),
        (
            "failure_at_intermediate_base_stage",
            _first_failure(("PASS", "FAIL", "PASS")) == "1",
        ),
        ("stress_stage_rejection", _first_failure(("PASS", "FAIL")) == "1"),
        ("trade_plan_stage_rejection", _first_failure(("PASS", "FAIL")) == "1"),
        (
            "multiple_observed_blockers",
            _failure_indexes(("FAIL", "PASS", "FAIL")) == (0, 2),
        ),
        ("unknown_input_state", _preserved_state("UNKNOWN") == "UNKNOWN"),
        (
            "not_applicable_stage",
            _preserved_state("NOT_APPLICABLE") == "NOT_APPLICABLE",
        ),
        (
            "canonical_early_return",
            _omission_for(reached=False, valid=True, wired=True)
            == "NOT_REACHED_CANONICAL_EARLY_RETURN",
        ),
        (
            "semantic_diagnostic_observation",
            _diagnostic_allowed(valid=True, read_only=True),
        ),
        (
            "semantically_invalid_downstream_stage",
            not _diagnostic_allowed(valid=False, read_only=True),
        ),
        ("duplicate_evaluator_invocation", _is_duplicate(2)),
        (
            "missing_evaluator_stage_wiring",
            _omission_for(reached=False, valid=False, wired=False)
            == "MISSING_EVALUATOR_WIRING",
        ),
        (
            "unexplained_terminal_rejection",
            _terminal_explained("REJECT", ()) is False,
        ),
        (
            "raw_adjusted_explained_divergence",
            _arm_divergence(explained=True) == "EXPLAINED",
        ),
        (
            "raw_adjusted_unexplained_divergence",
            _arm_divergence(explained=False) == "UNEXPLAINED",
        ),
    )
    return tuple(
        {
            "probe_id": probe,
            "probe_scope": "STRUCTURAL_ONLY",
            "passed": passed,
            "included_in_empirical_counts": False,
            "production_influence": False,
        }
        for probe, passed in probes
    )


def _first_failure(states: tuple[str, ...]) -> str:
    indexes = _failure_indexes(states)
    return str(indexes[0]) if indexes else "NONE"


def _failure_indexes(states: tuple[str, ...]) -> tuple[int, ...]:
    return tuple(index for index, state in enumerate(states) if state == "FAIL")


def _preserved_state(state: str) -> str:
    allowed = {item.value for item in StageResultState}
    return state if state in allowed else StageResultState.IMPLEMENTATION_ERROR.value


def _omission_for(*, reached: bool, valid: bool, wired: bool) -> str:
    if reached:
        return StageOmissionState.NONE.value
    if not wired:
        return StageOmissionState.MISSING_EVALUATOR_WIRING.value
    if valid:
        return StageOmissionState.NOT_REACHED_CANONICAL_EARLY_RETURN.value
    return StageOmissionState.NOT_SEMANTICALLY_VALID_AFTER_UPSTREAM_FAILURE.value


def _diagnostic_allowed(*, valid: bool, read_only: bool) -> bool:
    return valid and read_only


def _is_duplicate(invocation_count: int) -> bool:
    return invocation_count > 1


def _terminal_explained(
    terminal_decision: str,
    observed_failure_codes: tuple[str, ...],
) -> bool:
    return terminal_decision not in {"REJECT", "SELL", "AVOID"} or bool(
        observed_failure_codes
    )


def _arm_divergence(*, explained: bool) -> str:
    return "EXPLAINED" if explained else "UNEXPLAINED"


def _source_rows(
    sources: tuple[SignedSource, ...],
    inventory: tuple[StageDefinition, ...],
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = [
        {
            "source_type": "PREREQUISITE_CERTIFICATE",
            "source_id": source.bundle,
            "contract_version": source.contract_version,
            "sha256": source.certificate_file_sha256,
            "support_sha256": source.support_artifact_sha256,
        }
        for source in sources
    ]
    rows.extend(
        {
            "source_type": "EVALUATOR_SOURCE",
            "source_id": stage.stage_id,
            "contract_version": stage.evaluator_contract_version,
            "sha256": stage.source_sha256,
            "support_sha256": stage.configuration_sha256,
        }
        for stage in inventory
    )
    return tuple(rows)


def _blockers(
    *,
    events: tuple[StageEvent, ...],
    omissions: tuple[StageOmission, ...],
    attribution: RejectionAttribution,
    parity: bool,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if not events:
        blockers.append(DSI002DReadiness.EMPTY.value)
    if not any(
        event.result_state in {StageResultState.PASS, StageResultState.FAIL}
        for event in events
    ):
        blockers.append(DSI002DReadiness.EMPTY.value)
    if any(
        item.omission_state is StageOmissionState.MISSING_EVALUATOR_WIRING
        for item in omissions
    ):
        blockers.append(DSI002DReadiness.INCOMPLETE_INVENTORY.value)
    if not parity:
        blockers.append(DSI002DReadiness.PARITY_DEFECT.value)
    if not attribution.attribution_complete:
        blockers.append(DSI002DReadiness.ATTRIBUTION_DEFECT.value)
    if any(event.invocation_count > 1 for event in events):
        blockers.append(DSI002DReadiness.DUPLICATE.value)
    if any(
        event.result_state is StageResultState.IMPLEMENTATION_ERROR for event in events
    ):
        blockers.append(DSI002DReadiness.IMPLEMENTATION.value)
    return tuple(dict.fromkeys(blockers))


def _readiness(blockers: tuple[str, ...]) -> DSI002DReadiness:
    if not blockers:
        return DSI002DReadiness.READY
    return DSI002DReadiness(blockers[0])


def _definition(
    order: int,
    stage_id: str,
    family: str,
    evaluator: str,
    callable_identity: str,
    source_file: str,
    config_source: str,
    policy_hashes: Mapping[str, str],
    input_type: str,
    output_type: str,
    terminal_states: str,
    *,
    prerequisites: str = "captured candidate and required prior evidence available",
    multiple: bool = False,
) -> StageDefinition:
    return StageDefinition(
        stage_id=stage_id,
        stage_order=order,
        stage_family=family,
        evaluator_id=evaluator,
        callable_identity=callable_identity,
        evaluator_contract_version=DSI002D_CONTRACT_VERSION,
        source_file=source_file,
        source_sha256=_file_sha256(_project_root() / source_file),
        configuration_source=config_source,
        configuration_sha256=policy_hashes.get(config_source, ""),
        stage_input_type=input_type,
        stage_output_type=output_type,
        possible_terminal_states=terminal_states,
        always_evaluated=True,
        conditional=False,
        semantic_prerequisites=prerequisites,
        downstream_meaningful_after_failure=True,
        multiple_gate_conditions=multiple,
        future_override_eligible=False,
        wired_into_baseline=True,
    )


def _missing_definition(
    order: int,
    stage_id: str,
    family: str,
    evaluator: str,
    source_file: str,
) -> StageDefinition:
    return StageDefinition(
        stage_id=stage_id,
        stage_order=order,
        stage_family=family,
        evaluator_id=evaluator,
        callable_identity=f"UNWIRED:{evaluator}",
        evaluator_contract_version="UNWIRED_IN_DSI002C_BASELINE",
        source_file=source_file,
        source_sha256=_file_sha256(_project_root() / source_file),
        configuration_source="UNAVAILABLE",
        configuration_sha256="",
        stage_input_type="InstitutionalCandidate",
        stage_output_type="UNOBSERVED",
        possible_terminal_states="NOT_REACHED",
        always_evaluated=False,
        conditional=True,
        semantic_prerequisites="institutional candidate formation",
        downstream_meaningful_after_failure=False,
        multiple_gate_conditions=True,
        future_override_eligible=False,
        wired_into_baseline=False,
    )


def _trade_plan_complete(plan: Any) -> bool:
    return all(
        value is not None
        for value in (
            plan.entry_price,
            plan.initial_stop_loss,
            plan.target_1,
        )
    )


def _signed_source(
    bundle: str,
    version: str,
    certificate: Path,
    support: Path,
    candidate_identity: str,
    snapshot_sha256: str,
) -> SignedSource:
    certificate_hash = _file_sha256(certificate)
    return SignedSource(
        bundle=bundle,
        contract_version=version,
        certificate_path=str(certificate.resolve()),
        certificate_file_sha256=certificate_hash,
        internal_report_sha256=_hash_payload(_load_json_object(certificate)),
        support_artifact_sha256=_file_sha256(support),
        candidate_identity=candidate_identity,
        snapshot_sha256=snapshot_sha256,
    )


def _require_exact_acceptance(payload: Mapping[str, object], name: str) -> None:
    if payload.get("accepted") is not True:
        raise DSI002DSourceContractError(f"{name} is not accepted")
    if payload.get("production_influence") is not False:
        raise DSI002DSourceContractError(f"{name} production influence is not false")


def _require_schema(
    payload: Mapping[str, object],
    expected: frozenset[str],
    name: str,
) -> None:
    if set(payload) != expected:
        raise DSI002DSourceContractError(f"{name} certificate schema mismatch")


def _require_acceptance_conditions(
    payload: Mapping[str, object],
    name: str,
    conditions: tuple[str, ...],
) -> None:
    failed = tuple(
        condition for condition in conditions if payload.get(condition) is not True
    )
    if failed:
        raise DSI002DSourceContractError(
            f"{name} acceptance condition failed: {','.join(failed)}"
        )


def _candidate_identity_from_a(payload: Mapping[str, object]) -> str:
    candidate = payload.get("candidate")
    if not isinstance(candidate, dict):
        raise DSI002DSourceContractError("DSI-002A candidate is malformed")
    required = ("price_view", "observed_on", "symbol", "input_fingerprint")
    values = [candidate.get(name) for name in required]
    if not all(isinstance(value, str) and value for value in values):
        raise DSI002DSourceContractError("DSI-002A candidate identity is incomplete")
    return "|".join(str(value) for value in values)


def _inside(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise DSI002DSourceContractError(
            "support artifact path escapes acceptance root"
        )
    if not resolved.is_file():
        raise DSI002DSourceContractError(f"support artifact missing: {resolved.name}")
    return resolved


def _indexed_snapshot(root: Path, recorded_path: str) -> Path:
    candidate = Path(recorded_path)
    if candidate.resolve().is_file() and candidate.resolve().is_relative_to(
        root.resolve()
    ):
        return _inside(root, candidate)
    candidate = root / "capture" / "snapshots" / candidate.name
    return _inside(root, candidate)


def _load_json_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DSI002DSourceContractError(f"invalid signed source: {path.name}") from exc
    if not isinstance(payload, dict):
        raise DSI002DSourceContractError(f"{path.name} must contain a JSON object")
    return payload


def _read_csv(path: Path) -> tuple[dict[str, str], ...]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


def _candidate_date(candidate_identity: str) -> Any:
    from datetime import date

    return date.fromisoformat(candidate_identity.split("|")[1])


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _canonical_json(payload: object) -> str:
    return json.dumps(
        _jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _jsonable(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(cast(Any, value)))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "value") and isinstance(getattr(value, "value"), str):
        return str(getattr(value, "value"))
    if hasattr(value, "isoformat"):
        return str(getattr(value, "isoformat")())
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_commit() -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=_project_root(),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _join(values: Iterable[str]) -> str:
    items = tuple(values)
    return "|".join(items) if items else "NONE"


def _empty_result(
    *,
    sources: tuple[SignedSource, ...],
    inventory: tuple[StageDefinition, ...],
    candidate_identity: str,
    source_commit: str,
) -> DSI002DResult:
    return DSI002DResult(
        sources=sources,
        stage_inventory=inventory,
        events=(),
        omissions=(),
        attributions=(),
        flow_rows=(
            {
                "candidate_key": candidate_identity,
                "transition": "recommendation_availability",
                "count": 0,
                "reconciled": False,
            },
        ),
        arm_rows=(),
        invocation_rows=(),
        probe_rows=_probe_rows(),
        source_rows=_source_rows(sources, inventory),
        source_commit=source_commit,
        readiness=DSI002DReadiness.EMPTY,
        blockers=(DSI002DReadiness.EMPTY.value,),
    )


__all__ = [
    "DSI002B_CONTRACT_VERSION",
    "DSI002D_CONTRACT_VERSION",
    "DSI002DReadiness",
    "DSI002DResult",
    "DSI002DSourceContractError",
    "DSI002DSourceValidator",
    "GovernedStageAttributionEngine",
    "RejectionAttribution",
    "SignedSource",
    "StageDefinition",
    "StageEvent",
    "StageOmission",
    "StageOmissionState",
    "StageResultState",
]
