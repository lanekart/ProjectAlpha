"""Governed institutional approval-gate forensics for HTR-010B5."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Any, cast

from alpha.benchmark_replay.governed_adjusted import (
    HTR010B2_CONTRACT_VERSION,
    GovernedBenchmarkStorePair,
    build_governed_benchmark_stores,
)
from alpha.benchmark_replay.governed_trade_formation import (
    B4_BLOCKED_ZERO,
    HTR010B4_CONTRACT_VERSION,
    validate_governed_trade_formation_certificate,
)
from alpha.canonical_universe_audit.canonical_runner import CanonicalAlphaRunner
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.decision_intelligence import (
    CapacityAssessment,
    FinalDecisionAction,
    GateDecision,
    InstitutionalCandidate,
    InstitutionalDecisionEngine,
    OpportunityDecision,
    RejectionReasonCode,
)

HTR010B5_CONTRACT_VERSION = "HTR-010B5-v1.0.0"

B5_READY = "READY_FOR_GOVERNED_APPROVAL_GATE_RESEARCH"
B5_BLOCKED_VACUOUS = "BLOCKED_BY_VACUOUS_APPROVAL_GATE"
B5_BLOCKED_UNREACHED = "BLOCKED_BY_UNREACHED_APPROVAL_GATE"
B5_BLOCKED_EVIDENCE = "BLOCKED_BY_INSUFFICIENT_APPROVAL_GATE_EVIDENCE"
B5_BLOCKED_DEFECT = "BLOCKED_BY_APPROVAL_FORENSIC_IMPLEMENTATION_DEFECT"
B5_BLOCKED_DIVERGENCE = "BLOCKED_BY_UNEXPLAINED_APPROVAL_GATE_DIVERGENCE"

RESEARCH_SCOPE = "GOVERNED_INSTITUTIONAL_APPROVAL_FORENSICS_ONLY"

ProgressCallback = Callable[[int, int, str], None]
ProbeSpecification = tuple[str, str, str, str, bool, InstitutionalCandidate]

_APPROVABLE_SIGNALS = frozenset({"BUY", "STRONG_BUY"})
_REQUIRED_BENCHMARK_ARTIFACTS = frozenset(
    {"approval_statistics.csv", "candidate_statistics.csv"}
)
_REQUIRED_B5_SUPPORT_ARTIFACTS = frozenset(
    {
        "htr010b5_candidate_gate_forensics.csv",
        "htr010b5_gate_event_ledger.csv",
        "htr010b5_gate_prevalence.csv",
        "htr010b5_raw_adjusted_gate_comparison.csv",
        "htr010b5_structural_non_vacuity_probes.csv",
        "htr010b5_evidence_deficiency_attribution.csv",
        "htr010b5_executive_report.md",
    }
)
_REQUIRED_INPUT_ARTIFACT_KEYS = frozenset(
    {
        "b2_report",
        "b4_certificate",
        "raw_benchmark_manifest",
        "adjusted_benchmark_manifest",
        "identity_artifact",
        "corporate_action_artifact",
        "final_closure_report",
        "admission_contract",
        "identity_admission",
        "raw_universe",
        "adjusted_universe",
    }
)
_POLICY_SOURCE_PATHS = (
    "alpha/decision_intelligence/engine.py",
    "alpha/decision_intelligence/stress.py",
    "alpha/decision_intelligence/tradeplan.py",
    "alpha/decision_intelligence/models.py",
    "alpha/canonical_universe_audit/canonical_runner.py",
)
_FROZEN_PIPELINE_COMPONENTS = {
    "feature_hash": (
        "alpha/analysis",
        "alpha/recommendation_intelligence",
    ),
    "candidate_generation_hash": (
        "alpha/analysis/signals",
        "alpha/application/intelligence_inputs.py",
        "alpha/canonical_universe_audit/canonical_runner.py",
    ),
    "setup_discovery_hash": (
        "alpha/setup_discovery",
        "alpha/recommendation_intelligence/engines.py",
    ),
    "feature_attribution_hash": ("alpha/feature_attribution_research",),
    "approval_policy_hash": ("alpha/decision_intelligence/engine.py",),
    "trade_plan_policy_hash": (
        "alpha/decision_intelligence/tradeplan.py",
        "alpha/recommendation_intelligence/engines.py",
    ),
    "decision_engine_hash": ("alpha/decision_intelligence",),
}

_CANDIDATE_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "rank",
    "final_signal",
    "approvable_signal",
    "recommendation_score",
    "adjusted_confidence",
    "setup_stage",
    "entry_ready",
    "trigger_status",
    "execution_status",
    "allocation_eligible",
    "evidence_strength",
    "evidence_sample_count",
    "posterior_probability",
    "expectancy",
    "reward_risk_ratio",
    "stop_distance_percent",
    "data_completeness",
    "capacity_score",
    "base_gate_decision",
    "base_failure_count",
    "base_failure_codes",
    "stress_stage_reached",
    "stress_failure_count",
    "stress_failure_codes",
    "stress_final_action",
    "trade_plan_stage_reached",
    "trade_plan_quality_score",
    "trade_plan_final_action",
    "terminal_stage",
    "terminal_gate",
    "institutional_approved",
    "provisional_allocation_target_amount",
    "portfolio_eligible",
    "input_fingerprint",
    "benchmark_present",
    "benchmark_signal",
    "benchmark_score",
    "benchmark_approved",
    "benchmark_primary_reason",
    "benchmark_parity",
)
_GATE_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "final_signal",
    "approvable_signal",
    "stage",
    "gate_code",
    "gate_category",
    "gate_ordinal",
    "stage_reached",
    "outcome",
    "primary",
    "severity",
    "suggested_action",
    "explanation",
)
_PREVALENCE_FIELDS = (
    "price_view",
    "stage",
    "gate_code",
    "gate_category",
    "reached_candidate_count",
    "passed_candidate_count",
    "failed_candidate_count",
    "failure_percent",
)
_COMPARISON_FIELDS = (
    "observed_on",
    "symbol",
    "raw_present",
    "adjusted_present",
    "raw_signal",
    "adjusted_signal",
    "signal_changed",
    "raw_score",
    "adjusted_score",
    "score_delta",
    "raw_input_fingerprint",
    "adjusted_input_fingerprint",
    "input_changed",
    "raw_terminal_gate",
    "adjusted_terminal_gate",
    "terminal_gate_changed",
    "raw_approved",
    "adjusted_approved",
    "approval_changed",
    "explained_gate_difference",
    "unexplained_gate_divergence",
)
_PROBE_FIELDS = (
    "probe_id",
    "probe_scope",
    "expected_terminal_stage",
    "expected_gate_code",
    "expected_accepted",
    "observed_base_gate_decision",
    "observed_base_failure_codes",
    "observed_stress_failure_codes",
    "observed_stress_final_action",
    "observed_trade_plan_final_action",
    "observed_terminal_stage",
    "observed_terminal_gate",
    "observed_accepted",
    "expectation_matched",
    "deterministic",
)
_DEFICIENCY_FIELDS = (
    "price_view",
    "stage",
    "gate_code",
    "gate_category",
    "affected_candidate_count",
    "primary_candidate_count",
    "approvable_candidate_count",
    "affected_percent",
)


@dataclass(frozen=True, slots=True)
class BenchmarkApprovalBundle:
    """Verified benchmark evidence required for B5 reconciliation."""

    root: Path
    manifest: dict[str, Any]
    manifest_sha256: str
    approval_rows: tuple[dict[str, str], ...]
    candidate_rows: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class ForensicCandidate:
    """Complete institutional decision path for one replay candidate."""

    price_view: str
    observed_on: date
    symbol: str
    rank: int
    final_signal: str
    approvable_signal: bool
    recommendation_score: Decimal
    adjusted_confidence: str
    setup_stage: str
    entry_ready: bool
    trigger_status: str
    execution_status: str
    allocation_eligible: bool
    evidence_strength: str | None
    evidence_sample_count: int | None
    posterior_probability: Decimal | None
    expectancy: Decimal | None
    reward_risk_ratio: Decimal | None
    stop_distance_percent: Decimal | None
    data_completeness: str
    capacity_score: Decimal
    base_gate_decision: str
    base_failure_codes: tuple[str, ...]
    stress_stage_reached: bool
    stress_failure_codes: tuple[str, ...]
    stress_final_action: str
    trade_plan_stage_reached: bool
    trade_plan_quality_score: Decimal | None
    trade_plan_final_action: str
    terminal_stage: str
    terminal_gate: str
    institutional_approved: bool
    provisional_allocation_target_amount: Decimal
    portfolio_eligible: bool
    input_fingerprint: str

    def as_dict(self) -> dict[str, object]:
        payload = cast(dict[str, object], asdict(self))
        payload["base_failure_count"] = len(self.base_failure_codes)
        payload["stress_failure_count"] = len(self.stress_failure_codes)
        return payload


@dataclass(frozen=True, slots=True)
class GovernedApprovalGateForensicsResult:
    """Signed B5 certificate and deterministic forensic evidence."""

    report: dict[str, Any]
    candidate_rows: tuple[dict[str, object], ...]
    gate_rows: tuple[dict[str, object], ...]
    prevalence_rows: tuple[dict[str, object], ...]
    comparison_rows: tuple[dict[str, object], ...]
    probe_rows: tuple[dict[str, object], ...]
    deficiency_rows: tuple[dict[str, object], ...]
    paths: tuple[Path, ...]


class GovernedApprovalGateForensicsEngine:
    """Certify that the frozen institutional gate is reached and non-vacuous."""

    def run(
        self,
        *,
        source: LegacyMarketDataStore,
        b2_report: Path,
        b4_certificate: Path,
        raw_benchmark: Path,
        adjusted_benchmark: Path,
        identity_artifact: Path,
        corporate_action_artifact: Path,
        final_closure_report: Path,
        admission_contract: Path,
        identity_admission: Path,
        raw_universe: Path,
        adjusted_universe: Path,
        output: Path,
        project_root: Path | str = Path("."),
        progress: ProgressCallback | None = None,
    ) -> GovernedApprovalGateForensicsResult:
        total_steps = 9
        project_root_path = Path(project_root)
        policy_source_hashes = _policy_source_hashes(project_root_path)
        input_paths = {
            "b2_report": b2_report,
            "b4_certificate": b4_certificate,
            "identity_artifact": identity_artifact,
            "corporate_action_artifact": corporate_action_artifact,
            "final_closure_report": final_closure_report,
            "admission_contract": admission_contract,
            "identity_admission": identity_admission,
            "raw_universe": raw_universe,
            "adjusted_universe": adjusted_universe,
        }
        input_file_hashes = _hash_paths(input_paths)
        _progress(progress, 1, total_steps, "Validating signed HTR-010B4 handoff")
        b4 = validate_governed_trade_formation_certificate(b4_certificate)
        _validate_b4_handoff(b4)

        _progress(progress, 2, total_steps, "Validating signed HTR-010B2 lineage")
        b2 = _validated_b2_report(b2_report)
        _validate_lineage(b2=b2, b2_report=b2_report, b4=b4)

        _progress(progress, 3, total_steps, "Verifying RAW benchmark approval evidence")
        raw_bundle = _load_benchmark_bundle(
            raw_benchmark,
            expected_manifest_sha256=str(b4["raw_manifest_sha256"]),
        )
        _validate_bundle_lineage(raw_bundle, b2, b4, price_view="RAW")

        _progress(
            progress,
            4,
            total_steps,
            "Verifying ADJUSTED benchmark approval evidence",
        )
        adjusted_bundle = _load_benchmark_bundle(
            adjusted_benchmark,
            expected_manifest_sha256=str(b4["adjusted_manifest_sha256"]),
        )
        _validate_bundle_lineage(adjusted_bundle, b2, b4, price_view="ADJUSTED")
        _validate_bundle_pair(raw_bundle, adjusted_bundle)
        frozen_pipeline_hashes = _validate_frozen_pipeline_components(
            project_root=project_root_path,
            raw_manifest=raw_bundle.manifest,
            adjusted_manifest=adjusted_bundle.manifest,
        )
        input_file_hashes.update(
            {
                "raw_benchmark_manifest": raw_bundle.manifest_sha256,
                "adjusted_benchmark_manifest": adjusted_bundle.manifest_sha256,
            }
        )

        replay_start = _date_value(b4.get("replay_start"), "B4 replay start")
        replay_end = _date_value(b4.get("replay_end"), "B4 replay end")
        expected_session_dates = tuple(
            _date_value(row.get("observed_on"), "RAW candidate session")
            for row in raw_bundle.candidate_rows
        )
        expected_session_count = _integer(
            b4.get("session_count"),
            "B4 session count",
        )
        if len(expected_session_dates) != expected_session_count:
            raise ValueError("B5 benchmark session sequence differs from B4")
        _progress(progress, 5, total_steps, "Rebuilding signed governed replay stores")
        with TemporaryDirectory(prefix="htr010b5-store-contracts-") as temporary:
            pair = build_governed_benchmark_stores(
                source=source,
                identity_artifact=identity_artifact,
                corporate_action_artifact=corporate_action_artifact,
                final_closure_report=final_closure_report,
                admission_contract=admission_contract,
                identity_admission=identity_admission,
                raw_universe=raw_universe,
                adjusted_universe=adjusted_universe,
                output=Path(temporary),
            )
            try:
                b2_attestations = _validate_pair_lineage(pair, b2)
                _progress(
                    progress,
                    6,
                    total_steps,
                    "Tracing RAW institutional decisions",
                )
                raw_candidates, raw_gates, raw_defects = _run_forensic_arm(
                    pair.raw,
                    price_view="RAW",
                    replay_start=replay_start,
                    replay_end=replay_end,
                    expected_session_dates=expected_session_dates,
                )
                _progress(
                    progress,
                    7,
                    total_steps,
                    "Tracing ADJUSTED institutional decisions",
                )
                (
                    adjusted_candidates,
                    adjusted_gates,
                    adjusted_defects,
                ) = _run_forensic_arm(
                    pair.adjusted,
                    price_view="ADJUSTED",
                    replay_start=replay_start,
                    replay_end=replay_end,
                    expected_session_dates=expected_session_dates,
                )
                (
                    raw_forensic_attestations,
                    adjusted_forensic_attestations,
                    forensic_attestations,
                ) = _validated_forensic_attestations(
                    pair,
                    expected_attestations=b2_attestations,
                )
                lineage = {
                    "identity_session_sha256": pair.identity_session_sha256,
                    "final_closure_report_sha256": pair.final_closure_report_sha256,
                    "admission_contract_sha256": pair.admission_contract_sha256,
                    "governed_input_manifest_sha256": (
                        pair.governed_input_manifest_sha256
                    ),
                    "canonical_attestation_sha256s": list(b2_attestations),
                    "raw_forensic_canonical_attestation_sha256s": list(
                        raw_forensic_attestations
                    ),
                    "adjusted_forensic_canonical_attestation_sha256s": list(
                        adjusted_forensic_attestations
                    ),
                    "forensic_canonical_attestation_sha256s": list(
                        forensic_attestations
                    ),
                }
            finally:
                pair.close()

        _progress(progress, 8, total_steps, "Reconciling gates and proving non-vacuity")
        raw_rows, raw_reconciliation = _reconcile_arm(
            raw_candidates,
            raw_bundle,
            _nested_mapping(b4, "raw_funnel_summary"),
            price_view="RAW",
        )
        adjusted_rows, adjusted_reconciliation = _reconcile_arm(
            adjusted_candidates,
            adjusted_bundle,
            _nested_mapping(b4, "adjusted_funnel_summary"),
            price_view="ADJUSTED",
        )
        candidate_rows = tuple((*raw_rows, *adjusted_rows))
        gate_rows = tuple((*raw_gates, *adjusted_gates))
        comparison_rows, unexplained_divergences = _arm_comparison(
            raw_rows,
            adjusted_rows,
        )
        prevalence_rows = _gate_prevalence(gate_rows)
        deficiency_rows = _deficiency_attribution(gate_rows, candidate_rows)
        probe_rows, probe_summary, probe_defects = _structural_probes()

        defects = tuple(
            sorted(
                {
                    *raw_defects,
                    *adjusted_defects,
                    *cast(tuple[str, ...], raw_reconciliation["defects"]),
                    *cast(tuple[str, ...], adjusted_reconciliation["defects"]),
                    *probe_defects,
                }
            )
        )
        raw_summary = _arm_summary(raw_candidates)
        adjusted_summary = _arm_summary(adjusted_candidates)
        empirical_gate_reached = (
            cast(int, raw_summary["approvable_candidate_count"]) > 0
            and cast(int, adjusted_summary["approvable_candidate_count"]) > 0
        )
        trace_complete = (
            raw_summary["unexplained_terminal_gate_count"] == 0
            and adjusted_summary["unexplained_terminal_gate_count"] == 0
        )
        gate_non_vacuous = (
            empirical_gate_reached
            and trace_complete
            and probe_summary["acceptance_path_reachable"] is True
            and probe_summary["all_base_gate_families_discriminating"] is True
            and probe_summary["stress_rejection_path_discriminating"] is True
            and probe_summary["trade_plan_rejection_path_discriminating"] is True
            and probe_summary["all_institutional_stages_discriminating"] is True
            and probe_summary["deterministic"] is True
        )
        zero_approval_consistent = (
            raw_summary["institutional_approval_count"] == 0
            and adjusted_summary["institutional_approval_count"] == 0
            and gate_non_vacuous
            and not defects
            and unexplained_divergences == 0
            and raw_reconciliation["parity_mismatch_count"] == 0
            and adjusted_reconciliation["parity_mismatch_count"] == 0
        )
        readiness, blockers = _readiness(
            defects=defects,
            unexplained_divergences=unexplained_divergences,
            empirical_gate_reached=empirical_gate_reached,
            trace_complete=trace_complete,
            gate_non_vacuous=gate_non_vacuous,
        )
        enabled = readiness == B5_READY
        _validate_paths_unchanged(input_paths, input_file_hashes)
        _validate_bundle_unchanged(raw_bundle)
        _validate_bundle_unchanged(adjusted_bundle)
        if _policy_source_hashes(project_root_path) != policy_source_hashes:
            raise ValueError("institutional policy source changed during B5 replay")
        if _pipeline_component_hashes(project_root_path) != frozen_pipeline_hashes:
            raise ValueError("frozen pipeline component changed during B5 replay")
        report: dict[str, Any] = {
            "contract_version": HTR010B5_CONTRACT_VERSION,
            "b2_report_sha256": b2["report_sha256"],
            "b2_report_file_sha256": input_file_hashes["b2_report"],
            "b4_trade_formation_certificate_sha256": b4["report_sha256"],
            "b4_trade_formation_certificate_file_sha256": input_file_hashes[
                "b4_certificate"
            ],
            "raw_manifest_sha256": raw_bundle.manifest_sha256,
            "adjusted_manifest_sha256": adjusted_bundle.manifest_sha256,
            "identity_artifact_sha256": input_file_hashes["identity_artifact"],
            "corporate_action_artifact_sha256": input_file_hashes[
                "corporate_action_artifact"
            ],
            "input_artifact_file_sha256s": dict(sorted(input_file_hashes.items())),
            "replay_start": replay_start,
            "replay_end": replay_end,
            "session_count": expected_session_count,
            "governed_store_lineage": lineage,
            "frozen_pipeline_component_sha256s": frozen_pipeline_hashes,
            "institutional_policy_source_sha256s": policy_source_hashes,
            "forensic_contract": {
                "policy_change_permitted": False,
                "threshold_change_permitted": False,
                "synthetic_probe_influences_replay": False,
                "empirical_gate_population_required_per_arm": 1,
                "all_base_gate_families_must_be_discriminating": True,
                "stress_rejection_path_must_be_discriminating": True,
                "trade_plan_rejection_path_must_be_discriminating": True,
                "all_institutional_stages_must_be_discriminating": True,
                "acceptance_path_must_be_reachable": True,
            },
            "raw_forensic_summary": raw_summary,
            "adjusted_forensic_summary": adjusted_summary,
            "raw_reconciliation_summary": _without_defects(raw_reconciliation),
            "adjusted_reconciliation_summary": _without_defects(
                adjusted_reconciliation
            ),
            "structural_probe_summary": probe_summary,
            "gate_prevalence_summary": _prevalence_summary(prevalence_rows),
            "empirical_gate_reached": empirical_gate_reached,
            "approval_gate_trace_complete": trace_complete,
            "approval_gate_non_vacuous": gate_non_vacuous,
            "zero_approval_policy_consistent": zero_approval_consistent,
            "unexplained_arm_divergence_count": unexplained_divergences,
            "implementation_defects": list(defects),
            "implementation_defect_count": len(defects),
            "readiness_blockers": list(blockers),
            "readiness_decision": readiness,
            "governed_approval_gate_research_enabled": enabled,
            "governed_adjusted_trade_research_enabled": False,
            "research_scope": RESEARCH_SCOPE,
            "economic_superiority_claimed": False,
            "live_scoring_enabled": False,
            "recommendation_influence": False,
            "portfolio_policy_influence": False,
            "execution_influence": False,
            "learning_mutation_enabled": False,
            "active_replay_integration": False,
            "production_influence": False,
        }

        _progress(progress, 9, total_steps, "Exporting signed HTR-010B5 artifacts")
        paths = export_governed_approval_gate_forensics(
            report=report,
            candidate_rows=candidate_rows,
            gate_rows=gate_rows,
            prevalence_rows=prevalence_rows,
            comparison_rows=comparison_rows,
            probe_rows=probe_rows,
            deficiency_rows=deficiency_rows,
            output=output,
        )
        return GovernedApprovalGateForensicsResult(
            report=report,
            candidate_rows=candidate_rows,
            gate_rows=gate_rows,
            prevalence_rows=prevalence_rows,
            comparison_rows=comparison_rows,
            probe_rows=probe_rows,
            deficiency_rows=deficiency_rows,
            paths=paths,
        )


def export_governed_approval_gate_forensics(
    *,
    report: dict[str, Any],
    candidate_rows: tuple[dict[str, object], ...],
    gate_rows: tuple[dict[str, object], ...],
    prevalence_rows: tuple[dict[str, object], ...],
    comparison_rows: tuple[dict[str, object], ...],
    probe_rows: tuple[dict[str, object], ...],
    deficiency_rows: tuple[dict[str, object], ...],
    output: Path,
) -> tuple[Path, ...]:
    """Write deterministic B5 evidence and bind support files to the certificate."""

    output.mkdir(parents=True, exist_ok=True)
    certificate_path = output / "htr010b5_approval_gate_certificate.json"
    certificate_path.unlink(missing_ok=True)
    support_paths = (
        _write_csv(
            output / "htr010b5_candidate_gate_forensics.csv",
            candidate_rows,
            fieldnames=_CANDIDATE_FIELDS,
        ),
        _write_csv(
            output / "htr010b5_gate_event_ledger.csv",
            gate_rows,
            fieldnames=_GATE_FIELDS,
        ),
        _write_csv(
            output / "htr010b5_gate_prevalence.csv",
            prevalence_rows,
            fieldnames=_PREVALENCE_FIELDS,
        ),
        _write_csv(
            output / "htr010b5_raw_adjusted_gate_comparison.csv",
            comparison_rows,
            fieldnames=_COMPARISON_FIELDS,
        ),
        _write_csv(
            output / "htr010b5_structural_non_vacuity_probes.csv",
            probe_rows,
            fieldnames=_PROBE_FIELDS,
        ),
        _write_csv(
            output / "htr010b5_evidence_deficiency_attribution.csv",
            deficiency_rows,
            fieldnames=_DEFICIENCY_FIELDS,
        ),
        _write_text(
            output / "htr010b5_executive_report.md",
            _markdown(report),
        ),
    )
    report["artifact_hashes"] = {
        path.name: _file_sha256(path) for path in support_paths
    }
    report["report_sha256"] = _digest_mapping(report)
    certificate = _write_json(certificate_path, report)
    return (certificate, *support_paths)


def validate_governed_approval_gate_forensics_certificate(
    path: Path,
    *,
    require_ready: bool = False,
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    """Validate the signed B5 contract and every bound supporting artifact."""

    payload = _mapping(path)
    if payload.get("contract_version") != HTR010B5_CONTRACT_VERSION:
        raise ValueError("unsupported HTR-010B5 approval-gate contract")
    _validate_digest(payload, "HTR-010B5 approval-gate certificate")
    _validate_research_only_flags(payload)
    _validate_certificate_lineage(payload)
    if project_root is not None:
        expected_policy = _nested_mapping(
            payload,
            "institutional_policy_source_sha256s",
        )
        root = Path(project_root)
        observed_policy = _policy_source_hashes(root)
        if observed_policy != expected_policy:
            raise ValueError("HTR-010B5 frozen policy source digest mismatch")
        expected_components = _nested_mapping(
            payload,
            "frozen_pipeline_component_sha256s",
        )
        if _pipeline_component_hashes(root) != expected_components:
            raise ValueError("HTR-010B5 frozen pipeline component digest mismatch")
    if payload.get("research_scope") != RESEARCH_SCOPE:
        raise ValueError("HTR-010B5 research scope is invalid")
    if payload.get("economic_superiority_claimed") is not False:
        raise ValueError("HTR-010B5 cannot claim economic superiority")
    if payload.get("governed_adjusted_trade_research_enabled") is not False:
        raise ValueError("HTR-010B5 cannot enable governed adjusted trade research")

    hashes = payload.get("artifact_hashes")
    if not isinstance(hashes, dict):
        raise ValueError("HTR-010B5 certificate lacks supporting artifact hashes")
    observed_artifacts = frozenset(str(name) for name in hashes)
    if observed_artifacts != _REQUIRED_B5_SUPPORT_ARTIFACTS:
        missing = sorted(_REQUIRED_B5_SUPPORT_ARTIFACTS.difference(observed_artifacts))
        unexpected = sorted(
            observed_artifacts.difference(_REQUIRED_B5_SUPPORT_ARTIFACTS)
        )
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unexpected:
            details.append("unexpected=" + ",".join(unexpected))
        raise ValueError(
            "HTR-010B5 supporting artifact set mismatch: " + "; ".join(details)
        )
    for name, expected in sorted(hashes.items()):
        expected_sha256 = str(expected)
        if not _is_sha256(expected_sha256):
            raise ValueError(f"HTR-010B5 supporting artifact digest is invalid: {name}")
        artifact = _artifact_path(path.parent, name)
        if _file_sha256(artifact) != expected_sha256:
            raise ValueError(f"HTR-010B5 supporting artifact digest mismatch: {name}")

    readiness = payload.get("readiness_decision")
    valid_readiness_states = {
        B5_READY,
        B5_BLOCKED_VACUOUS,
        B5_BLOCKED_UNREACHED,
        B5_BLOCKED_EVIDENCE,
        B5_BLOCKED_DEFECT,
        B5_BLOCKED_DIVERGENCE,
    }
    if readiness not in valid_readiness_states:
        raise ValueError("HTR-010B5 readiness decision is invalid")
    enabled = payload.get("governed_approval_gate_research_enabled")
    expected_enabled = readiness == B5_READY
    if enabled is not expected_enabled:
        raise ValueError("HTR-010B5 readiness and research enablement disagree")
    _validate_certificate_state_semantics(payload)
    if expected_enabled:
        _validate_ready_certificate_semantics(payload)
    if require_ready and not expected_enabled:
        raise ValueError("HTR-010B5 does not permit approval-gate research")
    return payload


def _validate_certificate_lineage(payload: Mapping[str, object]) -> None:
    for key in (
        "b2_report_sha256",
        "b2_report_file_sha256",
        "b4_trade_formation_certificate_sha256",
        "b4_trade_formation_certificate_file_sha256",
        "raw_manifest_sha256",
        "adjusted_manifest_sha256",
        "identity_artifact_sha256",
        "corporate_action_artifact_sha256",
    ):
        if not _is_sha256(str(payload.get(key) or "")):
            raise ValueError(f"HTR-010B5 certificate has invalid lineage digest: {key}")

    inputs = _nested_mapping(payload, "input_artifact_file_sha256s")
    if set(inputs) != set(_REQUIRED_INPUT_ARTIFACT_KEYS):
        raise ValueError("HTR-010B5 input artifact set is invalid")
    for key, digest in inputs.items():
        if not _is_sha256(str(digest)):
            raise ValueError(f"HTR-010B5 input artifact digest is invalid: {key}")
    duplicated_hashes = {
        "b2_report": "b2_report_file_sha256",
        "b4_certificate": "b4_trade_formation_certificate_file_sha256",
        "raw_benchmark_manifest": "raw_manifest_sha256",
        "adjusted_benchmark_manifest": "adjusted_manifest_sha256",
        "identity_artifact": "identity_artifact_sha256",
        "corporate_action_artifact": "corporate_action_artifact_sha256",
    }
    for input_key, report_key in duplicated_hashes.items():
        if inputs.get(input_key) != payload.get(report_key):
            raise ValueError(f"HTR-010B5 input artifact lineage disagrees: {input_key}")

    replay_start = _date_value(payload.get("replay_start"), "B5 replay start")
    replay_end = _date_value(payload.get("replay_end"), "B5 replay end")
    if replay_end < replay_start:
        raise ValueError("HTR-010B5 replay window is inverted")
    if _integer(payload.get("session_count"), "B5 session count") < 1:
        raise ValueError("HTR-010B5 replay population has no sessions")

    lineage = _nested_mapping(payload, "governed_store_lineage")
    attestation_keys = {
        "canonical_attestation_sha256s",
        "raw_forensic_canonical_attestation_sha256s",
        "adjusted_forensic_canonical_attestation_sha256s",
        "forensic_canonical_attestation_sha256s",
    }
    expected_lineage_keys = {
        "identity_session_sha256",
        "final_closure_report_sha256",
        "admission_contract_sha256",
        "governed_input_manifest_sha256",
        *attestation_keys,
    }
    if set(lineage) != expected_lineage_keys:
        raise ValueError("HTR-010B5 governed store lineage fields are invalid")
    for key in expected_lineage_keys.difference(attestation_keys):
        if not _is_sha256(str(lineage.get(key) or "")):
            raise ValueError(f"HTR-010B5 governed store digest is invalid: {key}")
    normalized_attestations: dict[str, tuple[str, ...]] = {}
    for key in sorted(attestation_keys):
        values = lineage.get(key)
        if not isinstance(values, list) or not values:
            raise ValueError(f"HTR-010B5 lacks canonical attestation lineage: {key}")
        normalized = tuple(str(value) for value in values)
        if normalized != tuple(sorted(set(normalized))):
            raise ValueError(
                f"HTR-010B5 canonical attestations are not deterministic: {key}"
            )
        if any(not _is_sha256(value) for value in normalized):
            raise ValueError(
                f"HTR-010B5 canonical attestation digest is invalid: {key}"
            )
        normalized_attestations[key] = normalized
    forensic_union = tuple(
        sorted(
            {
                *normalized_attestations["raw_forensic_canonical_attestation_sha256s"],
                *normalized_attestations[
                    "adjusted_forensic_canonical_attestation_sha256s"
                ],
            }
        )
    )
    if (
        forensic_union
        != normalized_attestations["forensic_canonical_attestation_sha256s"]
    ):
        raise ValueError("HTR-010B5 forensic attestation union is inconsistent")
    if not set(forensic_union).issubset(
        set(normalized_attestations["canonical_attestation_sha256s"])
    ):
        raise ValueError("HTR-010B5 forensic attestations are outside B2 lineage")
    components = _nested_mapping(payload, "frozen_pipeline_component_sha256s")
    if set(components) != set(_FROZEN_PIPELINE_COMPONENTS):
        raise ValueError("HTR-010B5 frozen pipeline component set is invalid")
    for component, digest in components.items():
        if not _is_sha256(str(digest)):
            raise ValueError(
                f"HTR-010B5 frozen pipeline digest is invalid: {component}"
            )

    policy_hashes = _nested_mapping(payload, "institutional_policy_source_sha256s")
    if set(policy_hashes) != set(_POLICY_SOURCE_PATHS):
        raise ValueError("HTR-010B5 institutional policy source set is invalid")
    for path, digest in policy_hashes.items():
        if not _is_sha256(str(digest)):
            raise ValueError(f"HTR-010B5 policy source digest is invalid: {path}")


def _validate_certificate_state_semantics(payload: Mapping[str, object]) -> None:
    """Recompute every readiness state from its bound forensic evidence."""

    defects = tuple(
        str(item)
        for item in _list_value(
            payload,
            "implementation_defects",
            "B5 implementation defects",
        )
    )
    if any(not item or item != item.strip() for item in defects):
        raise ValueError("HTR-010B5 implementation defect ledger is invalid")
    if defects != tuple(sorted(set(defects))):
        raise ValueError("HTR-010B5 implementation defects are not deterministic")
    if _integer(
        payload.get("implementation_defect_count"),
        "B5 implementation defect count",
    ) != len(defects):
        raise ValueError("HTR-010B5 implementation defect count is inconsistent")

    blockers = tuple(
        str(item)
        for item in _list_value(
            payload,
            "readiness_blockers",
            "B5 readiness blockers",
        )
    )
    if any(not item or item != item.strip() for item in blockers):
        raise ValueError("HTR-010B5 readiness blocker ledger is invalid")
    if blockers != tuple(sorted(set(blockers))):
        raise ValueError("HTR-010B5 readiness blockers are not deterministic")

    raw = _nested_mapping(payload, "raw_forensic_summary")
    adjusted = _nested_mapping(payload, "adjusted_forensic_summary")
    raw_approvable = _integer(
        raw.get("approvable_candidate_count"),
        "B5 RAW approvable candidates",
    )
    adjusted_approvable = _integer(
        adjusted.get("approvable_candidate_count"),
        "B5 ADJUSTED approvable candidates",
    )
    raw_approvals = _integer(
        raw.get("institutional_approval_count"),
        "B5 RAW institutional approvals",
    )
    adjusted_approvals = _integer(
        adjusted.get("institutional_approval_count"),
        "B5 ADJUSTED institutional approvals",
    )
    raw_unexplained = _integer(
        raw.get("unexplained_terminal_gate_count"),
        "B5 RAW unexplained terminal gates",
    )
    adjusted_unexplained = _integer(
        adjusted.get("unexplained_terminal_gate_count"),
        "B5 ADJUSTED unexplained terminal gates",
    )

    probes = _nested_mapping(payload, "structural_probe_summary")
    probe_keys = (
        "acceptance_path_reachable",
        "all_base_gate_families_discriminating",
        "stress_rejection_path_discriminating",
        "trade_plan_rejection_path_discriminating",
        "all_institutional_stages_discriminating",
        "deterministic",
    )
    for key in probe_keys:
        if not isinstance(probes.get(key), bool):
            raise ValueError(f"HTR-010B5 probe evidence is not boolean: {key}")

    empirical_gate_reached = raw_approvable > 0 and adjusted_approvable > 0
    trace_complete = raw_unexplained == 0 and adjusted_unexplained == 0
    gate_non_vacuous = (
        empirical_gate_reached
        and trace_complete
        and all(probes[key] is True for key in probe_keys)
    )
    computed_booleans = {
        "empirical_gate_reached": empirical_gate_reached,
        "approval_gate_trace_complete": trace_complete,
        "approval_gate_non_vacuous": gate_non_vacuous,
    }
    for key, expected in computed_booleans.items():
        if payload.get(key) is not expected:
            raise ValueError(f"HTR-010B5 state evidence is inconsistent: {key}")

    raw_reconciliation = _nested_mapping(payload, "raw_reconciliation_summary")
    adjusted_reconciliation = _nested_mapping(
        payload,
        "adjusted_reconciliation_summary",
    )
    raw_parity_mismatches = _integer(
        raw_reconciliation.get("parity_mismatch_count"),
        "B5 RAW parity mismatches",
    )
    adjusted_parity_mismatches = _integer(
        adjusted_reconciliation.get("parity_mismatch_count"),
        "B5 ADJUSTED parity mismatches",
    )
    unexplained_divergences = _integer(
        payload.get("unexplained_arm_divergence_count"),
        "B5 unexplained arm divergence count",
    )
    zero_approval_consistent = (
        raw_approvals == 0
        and adjusted_approvals == 0
        and gate_non_vacuous
        and not defects
        and unexplained_divergences == 0
        and raw_parity_mismatches == 0
        and adjusted_parity_mismatches == 0
    )
    if payload.get("zero_approval_policy_consistent") is not zero_approval_consistent:
        raise ValueError("HTR-010B5 zero-approval conclusion is inconsistent")

    expected_readiness, expected_blockers = _readiness(
        defects=defects,
        unexplained_divergences=unexplained_divergences,
        empirical_gate_reached=empirical_gate_reached,
        trace_complete=trace_complete,
        gate_non_vacuous=gate_non_vacuous,
    )
    if payload.get("readiness_decision") != expected_readiness:
        raise ValueError("HTR-010B5 readiness decision disagrees with evidence")
    if blockers != expected_blockers:
        raise ValueError("HTR-010B5 readiness blockers disagree with evidence")


def _validate_ready_certificate_semantics(payload: Mapping[str, object]) -> None:
    required_true = (
        "empirical_gate_reached",
        "approval_gate_trace_complete",
        "approval_gate_non_vacuous",
        "zero_approval_policy_consistent",
    )
    for key in required_true:
        if payload.get(key) is not True:
            raise ValueError(f"HTR-010B5 ready certificate lacks required proof: {key}")
    if _integer(
        payload.get("implementation_defect_count"),
        "B5 implementation defect count",
    ) != 0 or _list_value(
        payload,
        "implementation_defects",
        "B5 implementation defects",
    ):
        raise ValueError("HTR-010B5 ready certificate contains implementation defects")
    if (
        _integer(
            payload.get("unexplained_arm_divergence_count"),
            "B5 unexplained arm divergence count",
        )
        != 0
    ):
        raise ValueError("HTR-010B5 ready certificate contains arm divergences")
    if _list_value(payload, "readiness_blockers", "B5 readiness blockers"):
        raise ValueError("HTR-010B5 ready certificate contains readiness blockers")

    contract = _nested_mapping(payload, "forensic_contract")
    required_contract_values = {
        "policy_change_permitted": False,
        "threshold_change_permitted": False,
        "synthetic_probe_influences_replay": False,
        "empirical_gate_population_required_per_arm": 1,
        "all_base_gate_families_must_be_discriminating": True,
        "stress_rejection_path_must_be_discriminating": True,
        "trade_plan_rejection_path_must_be_discriminating": True,
        "all_institutional_stages_must_be_discriminating": True,
        "acceptance_path_must_be_reachable": True,
    }
    for key, expected in required_contract_values.items():
        if contract.get(key) != expected:
            raise ValueError(f"HTR-010B5 forensic contract is invalid: {key}")

    probes = _nested_mapping(payload, "structural_probe_summary")
    for key in (
        "acceptance_path_reachable",
        "all_base_gate_families_discriminating",
        "stress_rejection_path_discriminating",
        "trade_plan_rejection_path_discriminating",
        "all_institutional_stages_discriminating",
        "deterministic",
    ):
        if probes.get(key) is not True:
            raise ValueError(f"HTR-010B5 ready certificate lacks probe proof: {key}")

    for label, key in (
        ("RAW", "raw_reconciliation_summary"),
        ("ADJUSTED", "adjusted_reconciliation_summary"),
    ):
        reconciliation = _nested_mapping(payload, key)
        if (
            _integer(
                reconciliation.get("parity_mismatch_count"),
                f"B5 {label} parity mismatches",
            )
            != 0
        ):
            raise ValueError(f"HTR-010B5 ready certificate has {label} parity mismatch")

    raw = _nested_mapping(payload, "raw_forensic_summary")
    adjusted = _nested_mapping(payload, "adjusted_forensic_summary")
    for label, summary in (("RAW", raw), ("ADJUSTED", adjusted)):
        if (
            _integer(
                summary.get("approvable_candidate_count"),
                f"B5 {label} approvable candidates",
            )
            < 1
        ):
            raise ValueError(
                f"HTR-010B5 ready certificate lacks {label} gate population"
            )
        if (
            _integer(
                summary.get("institutional_approval_count"),
                f"B5 {label} institutional approvals",
            )
            != 0
        ):
            raise ValueError(
                f"HTR-010B5 ready certificate is not a zero-approval {label} population"
            )


def _validate_b4_handoff(payload: Mapping[str, object]) -> None:
    if payload.get("contract_version") != HTR010B4_CONTRACT_VERSION:
        raise ValueError("B5 requires the HTR-010B4 trade-formation contract")
    if payload.get("readiness_decision") != B4_BLOCKED_ZERO:
        raise ValueError("B5 requires B4's policy-consistent zero-trade state")
    if payload.get("research_scope") != "GOVERNED_TRADE_FORMATION_RESEARCH_ONLY":
        raise ValueError("HTR-010B4 research scope is invalid")
    if payload.get("economic_superiority_claimed") is not False:
        raise ValueError("HTR-010B4 cannot claim economic superiority")
    if payload.get("zero_trade_policy_consistent") is not True:
        raise ValueError("HTR-010B4 zero-trade evidence is not policy consistent")
    if payload.get("trade_formation_certified") is not True:
        raise ValueError("HTR-010B4 trade formation is not certified")
    if payload.get("funnel_metrics_evaluated") is not True:
        raise ValueError("HTR-010B4 funnel metrics were not evaluated")
    if payload.get("economic_metrics_evaluated") is not False:
        raise ValueError("HTR-010B4 zero-trade economics are inconsistent")
    if _integer(
        payload.get("implementation_defect_count"), "B4 defects"
    ) != 0 or _list_value(payload, "implementation_defects", "B4 defects"):
        raise ValueError("HTR-010B4 contains implementation defects")
    for key in (
        "unexplained_terminal_gate_count",
        "unexplained_gate_divergence_count",
        "unexplained_trade_divergence_count",
    ):
        if _integer(payload.get(key), f"B4 {key}") != 0:
            raise ValueError(f"HTR-010B4 contains {key}")
    if _list_value(
        payload,
        "readiness_blockers",
        "B4 readiness blockers",
    ) != ("ZERO_TRADE_POPULATION",):
        raise ValueError("HTR-010B4 zero-trade blocker is inconsistent")
    for label, key in (
        ("RAW", "raw_funnel_summary"),
        ("ADJUSTED", "adjusted_funnel_summary"),
    ):
        summary = _nested_mapping(payload, key)
        if _integer(summary.get("trade_count"), f"B4 {label} trades") != 0:
            raise ValueError(f"HTR-010B4 {label} trade population is not zero")
        if (
            _integer(
                summary.get("institutional_approval_count"),
                f"B4 {label} approvals",
            )
            != 0
        ):
            raise ValueError(f"HTR-010B4 {label} approval population is not zero")
    if payload.get("governed_adjusted_trade_research_enabled") is not False:
        raise ValueError("HTR-010B4 unexpectedly enabled trade research")


def _validated_b2_report(path: Path) -> dict[str, Any]:
    payload = _mapping(path)
    if payload.get("contract_version") != HTR010B2_CONTRACT_VERSION:
        raise ValueError("B5 requires the HTR-010B2 benchmark contract")
    _validate_digest(payload, "HTR-010B2 benchmark report")
    if payload.get("readiness_decision") != (
        "READY_FOR_GOVERNED_ADJUSTED_BENCHMARK_RESEARCH"
    ):
        raise ValueError("HTR-010B2 does not permit approval-gate forensics")
    if payload.get("decision_metrics_evaluated") is not True:
        raise ValueError("HTR-010B2 decision metrics were not evaluated")
    if payload.get("governed_adjusted_benchmark_enabled") is not True:
        raise ValueError("HTR-010B2 benchmark research is disabled")
    comparison = _nested_mapping(payload, "comparison")
    if comparison.get("benchmark_population_nonempty") is not True:
        raise ValueError("HTR-010B2 benchmark population is empty")
    if comparison.get("production_influence") is not False:
        raise ValueError("HTR-010B2 comparison permits production influence")
    parity = _nested_mapping(comparison, "parity")
    for key in (
        "session_counts_match",
        "eligible_security_counts_match",
        "eligible_observation_counts_match",
        "source_contracts_distinct",
    ):
        if parity.get(key) is not True:
            raise ValueError(f"HTR-010B2 parity proof failed: {key}")
    if (
        _integer(
            comparison.get("unexplained_divergence_count"),
            "B2 unexplained divergences",
        )
        != 0
    ):
        raise ValueError("HTR-010B2 contains unexplained divergences")
    if _list_value(comparison, "readiness_blockers", "B2 readiness blockers"):
        raise ValueError("HTR-010B2 contains readiness blockers")
    if payload.get("active_replay_integration") is not False:
        raise ValueError("HTR-010B2 active replay integration must remain false")
    if payload.get("production_influence") is not False:
        raise ValueError("HTR-010B2 production influence must remain false")
    return payload


def _validate_lineage(
    *,
    b2: Mapping[str, object],
    b2_report: Path,
    b4: Mapping[str, object],
) -> None:
    if b4.get("b2_report_sha256") != b2.get("report_sha256"):
        raise ValueError("HTR-010B4 does not match the supplied HTR-010B2 report")
    if b4.get("b2_report_file_sha256") != _file_sha256(b2_report):
        raise ValueError("HTR-010B4 B2 file digest does not match")


def _load_benchmark_bundle(
    root: Path,
    *,
    expected_manifest_sha256: str,
) -> BenchmarkApprovalBundle:
    if not _is_sha256(expected_manifest_sha256):
        raise ValueError("expected benchmark manifest digest is invalid")
    manifest_path = root / "manifest.json"
    manifest = _mapping(manifest_path)
    manifest_sha256 = _file_sha256(manifest_path)
    if manifest_sha256 != expected_manifest_sha256:
        raise ValueError("benchmark manifest does not match HTR-010B4")
    if manifest.get("point_in_time_enforced") is not True:
        raise ValueError("benchmark manifest does not enforce point-in-time data")
    if manifest.get("no_future_leakage") is not True:
        raise ValueError("benchmark manifest does not prohibit future leakage")
    if manifest.get("production_influence") is not False:
        raise ValueError("benchmark manifest production influence must remain false")
    hashes = manifest.get("artifact_hashes")
    if not isinstance(hashes, dict):
        raise ValueError("benchmark manifest lacks artifact hashes")
    missing = _REQUIRED_BENCHMARK_ARTIFACTS.difference(hashes)
    if missing:
        raise ValueError(
            "benchmark manifest lacks B5 artifacts: " + ",".join(sorted(missing))
        )
    for name, expected in sorted(hashes.items()):
        expected_sha256 = str(expected)
        if not _is_sha256(expected_sha256):
            raise ValueError(f"benchmark artifact digest is invalid: {name}")
        artifact = _artifact_path(root, name)
        if _file_sha256(artifact) != expected_sha256:
            raise ValueError(f"benchmark artifact digest mismatch: {name}")
    return BenchmarkApprovalBundle(
        root=root,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        approval_rows=_csv_rows(root / "approval_statistics.csv"),
        candidate_rows=_csv_rows(root / "candidate_statistics.csv"),
    )


def _validate_bundle_unchanged(bundle: BenchmarkApprovalBundle) -> None:
    manifest_path = bundle.root / "manifest.json"
    if _file_sha256(manifest_path) != bundle.manifest_sha256:
        raise ValueError("benchmark manifest changed during B5 replay")
    hashes = bundle.manifest.get("artifact_hashes")
    if not isinstance(hashes, dict):
        raise ValueError("benchmark manifest lacks artifact hashes")
    for name, expected in sorted(hashes.items()):
        artifact = _artifact_path(bundle.root, name)
        if _file_sha256(artifact) != str(expected):
            raise ValueError(f"benchmark artifact changed during B5 replay: {name}")


def _validate_bundle_lineage(
    bundle: BenchmarkApprovalBundle,
    b2: Mapping[str, object],
    b4: Mapping[str, object],
    *,
    price_view: str,
) -> None:
    summary_key = "raw_summary" if price_view == "RAW" else "adjusted_summary"
    b4_key = "raw_funnel_summary" if price_view == "RAW" else "adjusted_funnel_summary"
    summary = _nested_mapping(b2, summary_key)
    funnel = _nested_mapping(b4, b4_key)
    sessions = _integer(bundle.manifest.get("sessions"), f"{price_view} sessions")
    if sessions < 1:
        raise ValueError(f"{price_view} benchmark has no replay sessions")
    if sessions != _integer(summary.get("session_count"), "B2 session count"):
        raise ValueError(f"{price_view} manifest session count differs from B2")
    if sessions != _integer(b4.get("session_count"), "B4 session count"):
        raise ValueError(f"{price_view} manifest session count differs from B4")
    if len(bundle.candidate_rows) != sessions:
        raise ValueError(
            f"{price_view} candidate statistics do not cover every session"
        )
    session_dates = tuple(
        _date_value(row.get("observed_on"), f"{price_view} candidate session")
        for row in bundle.candidate_rows
    )
    if len(session_dates) != len(set(session_dates)):
        raise ValueError(
            f"{price_view} candidate statistics contain duplicate sessions"
        )
    if session_dates != tuple(sorted(session_dates)):
        raise ValueError(f"{price_view} candidate sessions are not deterministic")
    manifest_start = _date_value(
        bundle.manifest.get("replay_start"),
        f"{price_view} manifest replay start",
    )
    manifest_end = _date_value(
        bundle.manifest.get("replay_end"),
        f"{price_view} manifest replay end",
    )
    if session_dates[0] != manifest_start or session_dates[-1] != manifest_end:
        raise ValueError(
            f"{price_view} candidate session bounds differ from the manifest"
        )
    if manifest_start != _date_value(b4.get("replay_start"), "B4 replay start"):
        raise ValueError(f"{price_view} manifest replay start differs from B4")
    if manifest_end != _date_value(b4.get("replay_end"), "B4 replay end"):
        raise ValueError(f"{price_view} manifest replay end differs from B4")
    candidate_total = sum(
        _integer(
            row.get("technical_candidates"),
            f"{price_view} technical candidates",
        )
        for row in bundle.candidate_rows
    )
    if candidate_total != len(bundle.approval_rows):
        raise ValueError(
            f"{price_view} approval rows do not cover every technical candidate"
        )
    if candidate_total != _integer(
        summary.get("technical_candidate_count"),
        f"B2 {price_view} candidate count",
    ):
        raise ValueError(f"{price_view} approval evidence differs from B2")
    if candidate_total != _integer(
        funnel.get("candidate_count"),
        f"B4 {price_view} candidate count",
    ):
        raise ValueError(f"{price_view} approval evidence differs from B4")
    approvable_total = sum(
        _integer(row.get("buy_candidates"), f"{price_view} BUY candidates")
        + _integer(
            row.get("strong_buy_candidates"),
            f"{price_view} STRONG_BUY candidates",
        )
        for row in bundle.candidate_rows
    )
    if approvable_total != _integer(
        funnel.get("approvable_signal_count"),
        f"B4 {price_view} approvable signals",
    ):
        raise ValueError(f"{price_view} approvable evidence differs from B4")
    approved_rows = sum(
        _boolean(row.get("approved"), "benchmark approval")
        for row in bundle.approval_rows
    )
    session_approvals = sum(
        _integer(
            row.get("institutional_approvals"),
            f"{price_view} institutional approvals",
        )
        for row in bundle.candidate_rows
    )
    if approved_rows != session_approvals:
        raise ValueError(f"{price_view} approval rows differ from candidate statistics")
    if approved_rows != _integer(
        summary.get("institutional_approval_count"),
        f"B2 {price_view} institutional approvals",
    ):
        raise ValueError(f"{price_view} approval evidence differs from B2")
    if approved_rows != _integer(
        funnel.get("institutional_approval_count"),
        f"B4 {price_view} institutional approvals",
    ):
        raise ValueError(f"{price_view} approval evidence differs from B4")
    if approved_rows != 0:
        raise ValueError(f"{price_view} benchmark is not a zero-approval population")


def _validate_bundle_pair(
    raw: BenchmarkApprovalBundle,
    adjusted: BenchmarkApprovalBundle,
) -> None:
    for key in ("replay_start", "replay_end", "sessions"):
        if raw.manifest.get(key) != adjusted.manifest.get(key):
            raise ValueError(f"RAW and ADJUSTED benchmark manifests differ on {key}")
    raw_sessions = tuple(
        _date_value(row.get("observed_on"), "RAW candidate session")
        for row in raw.candidate_rows
    )
    adjusted_sessions = tuple(
        _date_value(row.get("observed_on"), "ADJUSTED candidate session")
        for row in adjusted.candidate_rows
    )
    if raw_sessions != adjusted_sessions:
        raise ValueError("RAW and ADJUSTED candidate session coverage differs")


def _validate_pair_lineage(
    pair: GovernedBenchmarkStorePair,
    b2: Mapping[str, object],
) -> tuple[str, ...]:
    coverage = _nested_mapping(b2, "identity_coverage")
    comparison = _nested_mapping(b2, "comparison")
    parity = _nested_mapping(comparison, "parity")
    expected_identity = str(parity.get("identity_session_sha256") or "")
    if not expected_identity:
        raise ValueError("HTR-010B2 lacks identity-session lineage")
    if getattr(pair, "identity_session_sha256") != expected_identity:
        raise ValueError("rebuilt identity-session lineage differs from HTR-010B2")
    for key in (
        "final_closure_report_sha256",
        "admission_contract_sha256",
        "governed_input_manifest_sha256",
    ):
        expected = str(b2.get(key) or "")
        if not expected or getattr(pair, key) != expected:
            raise ValueError(f"rebuilt {key} differs from HTR-010B2")
    count_fields = (
        ("admitted_identity_count", "admitted_identity_count"),
        ("observed_identity_count", "observed_identity_count"),
    )
    for report_key, pair_key in count_fields:
        if _integer(coverage.get(report_key), f"B2 {report_key}") != int(
            getattr(pair, pair_key)
        ):
            raise ValueError(f"rebuilt {report_key} differs from HTR-010B2")
    unobserved = tuple(
        str(item) for item in getattr(pair, "unobserved_admitted_identity_ids")
    )
    if _integer(
        coverage.get("unobserved_admitted_identity_count"),
        "B2 unobserved admitted identities",
    ) != len(unobserved):
        raise ValueError(
            "rebuilt unobserved admitted identity count differs from HTR-010B2"
        )
    expected_unobserved_sha256 = str(
        coverage.get("unobserved_admitted_identity_sha256") or ""
    )
    if (
        not expected_unobserved_sha256
        or _digest_sequence(unobserved) != expected_unobserved_sha256
    ):
        raise ValueError(
            "rebuilt unobserved admitted identity lineage differs from HTR-010B2"
        )
    if pair.canonical_attestation_sha256s:
        raise ValueError("fresh B5 stores contain unexpected consumer attestations")
    expected_attestations = tuple(
        str(item)
        for item in _list_value(
            b2,
            "canonical_attestation_sha256s",
            "B2 canonical attestations",
        )
    )
    if expected_attestations != tuple(sorted(set(expected_attestations))):
        raise ValueError("HTR-010B2 canonical attestations are not deterministic")
    if not expected_attestations or any(
        not _is_sha256(item) for item in expected_attestations
    ):
        raise ValueError("HTR-010B2 canonical attestation lineage is invalid")
    if _integer(
        b2.get("canonical_attestation_count"),
        "B2 canonical attestation count",
    ) != len(expected_attestations):
        raise ValueError("HTR-010B2 canonical attestation count is inconsistent")
    return expected_attestations


def _validated_forensic_attestations(
    pair: GovernedBenchmarkStorePair,
    *,
    expected_attestations: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    raw = tuple(sorted({str(item) for item in pair.raw.canonical_attestation_sha256s}))
    adjusted = tuple(
        sorted({str(item) for item in pair.adjusted.canonical_attestation_sha256s})
    )
    if not raw or not adjusted:
        raise ValueError("B5 forensic replay lacks per-arm canonical attestations")
    if any(not _is_sha256(value) for value in (*raw, *adjusted)):
        raise ValueError("B5 forensic canonical attestation digest is invalid")
    combined = tuple(sorted({*raw, *adjusted}))
    pair_attestations = tuple(str(item) for item in pair.canonical_attestation_sha256s)
    if pair_attestations != combined:
        raise ValueError("B5 forensic canonical attestation union is inconsistent")
    if not set(combined).issubset(set(expected_attestations)):
        raise ValueError(
            "B5 forensic attestations are outside the signed HTR-010B2 lineage"
        )
    return raw, adjusted, combined


def _run_forensic_arm(
    store: LegacyMarketDataStore,
    *,
    price_view: str,
    replay_start: date,
    replay_end: date,
    expected_session_dates: tuple[date, ...],
) -> tuple[
    tuple[ForensicCandidate, ...],
    tuple[dict[str, object], ...],
    tuple[str, ...],
]:
    dates = store.trade_dates(start=replay_start, end=replay_end)
    runner = CanonicalAlphaRunner(store=store)
    candidates: list[ForensicCandidate] = []
    gates: list[dict[str, object]] = []
    defects: list[str] = []
    if dates != expected_session_dates:
        expected_digest = _digest_sequence(
            tuple(item.isoformat() for item in expected_session_dates)
        )
        observed_digest = _digest_sequence(tuple(item.isoformat() for item in dates))
        defects.append(
            f"{price_view}_FORENSIC_SESSION_LINEAGE_MISMATCH:"
            f"expected={expected_digest}|observed={observed_digest}"
        )
    if dates and (dates[0] != replay_start or dates[-1] != replay_end):
        defects.append(f"{price_view}_FORENSIC_SESSION_BOUNDS_MISMATCH")
    if len(dates) != len(set(dates)) or dates != tuple(sorted(dates)):
        defects.append(f"{price_view}_FORENSIC_SESSION_ORDER_DEFECT")
    for observed_on in dates:
        try:
            day = runner.run_day(observed_on)
        except (ArithmeticError, RuntimeError, TypeError, ValueError) as error:
            defects.append(
                f"{price_view}_FORENSIC_RUNTIME_FAILURE@{observed_on.isoformat()}:"
                f"{_safe_error(error)}"
            )
            continue
        allocation_by_symbol = _allocation_amounts(day.intelligence.allocation_plan)
        decisions = tuple(
            sorted(
                day.institutional.decisions,
                key=lambda item: (-item.candidate.final_score, item.candidate.symbol),
            )
        )
        for rank, decision in enumerate(decisions, start=1):
            record, event_rows, decision_defects = _decision_trace(
                decision,
                price_view=price_view,
                observed_on=observed_on,
                rank=rank,
                provisional_allocation_target_amount=allocation_by_symbol.get(
                    decision.candidate.symbol,
                    Decimal("0"),
                ),
            )
            candidates.append(record)
            gates.extend(event_rows)
            defects.extend(decision_defects)
    keys = [(item.observed_on, item.symbol) for item in candidates]
    if len(keys) != len(set(keys)):
        defects.append(f"{price_view}_DUPLICATE_FORENSIC_CANDIDATE_KEYS")
    return (
        tuple(
            sorted(
                candidates,
                key=lambda item: (item.observed_on, item.rank, item.symbol),
            )
        ),
        tuple(
            sorted(
                gates,
                key=lambda row: (
                    cast(date, row["observed_on"]),
                    str(row["symbol"]),
                    str(row["stage"]),
                    int(cast(int, row["gate_ordinal"])),
                    str(row["gate_code"]),
                ),
            )
        ),
        tuple(sorted(set(defects))),
    )


def _decision_trace(
    decision: OpportunityDecision,
    *,
    price_view: str,
    observed_on: date,
    rank: int,
    provisional_allocation_target_amount: Decimal,
) -> tuple[ForensicCandidate, tuple[dict[str, object], ...], tuple[str, ...]]:
    candidate = decision.candidate
    defects: list[str] = []
    events: list[dict[str, object]] = []
    approvable_signal = candidate.final_verdict in _APPROVABLE_SIGNALS
    if decision.accepted and not approvable_signal:
        defects.append(
            f"{price_view}_APPROVED_NON_APPROVABLE_SIGNAL@"
            f"{observed_on.isoformat()}|{candidate.symbol}"
        )
    base_failures = tuple(reason.code.value for reason in decision.rejection_reasons)
    explanations: dict[str, list[str]] = defaultdict(list)
    for reason in decision.rejection_reasons:
        explanations[reason.code.value].append(reason.explanation)
    primary_base = base_failures[0] if base_failures else None
    for ordinal, code in enumerate(RejectionReasonCode, start=1):
        failed = code.value in explanations
        events.append(
            _gate_event(
                price_view=price_view,
                observed_on=observed_on,
                candidate=candidate,
                stage="BASE_GATE",
                gate_code=code.value,
                gate_category=_base_gate_category(code),
                gate_ordinal=ordinal,
                stage_reached=True,
                outcome="FAIL" if failed else "PASS",
                primary=failed and primary_base == code.value,
                explanation=(
                    " | ".join(explanations[code.value])
                    if failed
                    else "Candidate cleared this base gate family."
                ),
            )
        )
    if decision.gate_decision is GateDecision.REJECT and not base_failures:
        defects.append(
            f"{price_view}_BASE_REJECTION_WITHOUT_REASON@"
            f"{observed_on.isoformat()}|{candidate.symbol}"
        )
    if decision.gate_decision is GateDecision.ACCEPT and base_failures:
        defects.append(
            f"{price_view}_BASE_ACCEPTANCE_WITH_REJECTION_REASON@"
            f"{observed_on.isoformat()}|{candidate.symbol}"
        )

    stress_reached = decision.gate_decision is GateDecision.ACCEPT
    stress_failures: tuple[str, ...] = ()
    stress_action = "NOT_REACHED"
    if stress_reached:
        if decision.decision_quality is None:
            defects.append(
                f"{price_view}_STRESS_STAGE_MISSING@"
                f"{observed_on.isoformat()}|{candidate.symbol}"
            )
        else:
            stress_failures = tuple(
                item.reason_code.value
                for item in decision.stress_tests
                if not item.passed
            )
            for ordinal, item in enumerate(decision.stress_tests, start=1):
                events.append(
                    _gate_event(
                        price_view=price_view,
                        observed_on=observed_on,
                        candidate=candidate,
                        stage="STRESS_TEST",
                        gate_code=item.reason_code.value,
                        gate_category="STRESS",
                        gate_ordinal=ordinal,
                        stage_reached=True,
                        outcome="PASS" if item.passed else "FAIL",
                        primary=(
                            not item.passed
                            and bool(stress_failures)
                            and stress_failures[0] == item.reason_code.value
                        ),
                        explanation=item.explanation,
                        severity=item.severity.value,
                        suggested_action=item.suggested_action.value,
                    )
                )
            stress_action = decision.decision_quality.final_action.value.upper()
            events.append(
                _gate_event(
                    price_view=price_view,
                    observed_on=observed_on,
                    candidate=candidate,
                    stage="STRESS_DECISION",
                    gate_code="STRESS_FINAL_ACTION",
                    gate_category="STRESS",
                    gate_ordinal=len(decision.stress_tests) + 1,
                    stage_reached=True,
                    outcome=(
                        "PASS"
                        if decision.decision_quality.final_action
                        is FinalDecisionAction.ACCEPT
                        else "FAIL"
                    ),
                    primary=(
                        decision.decision_quality.final_action
                        is not FinalDecisionAction.ACCEPT
                        and not stress_failures
                    ),
                    explanation="Institutional stress-stage final action.",
                    suggested_action=decision.decision_quality.final_action.value,
                )
            )

    stress_passed = (
        stress_reached
        and decision.decision_quality is not None
        and decision.decision_quality.final_action is FinalDecisionAction.ACCEPT
    )
    trade_plan_reached = stress_passed
    trade_plan_score: Decimal | None = None
    trade_plan_action = "NOT_REACHED"
    if trade_plan_reached:
        quality = decision.trade_plan_quality
        if quality is None:
            defects.append(
                f"{price_view}_TRADE_PLAN_STAGE_MISSING@"
                f"{observed_on.isoformat()}|{candidate.symbol}"
            )
        else:
            trade_plan_score = quality.trade_plan_quality_score
            trade_plan_action = quality.final_action.value.upper()
            events.append(
                _gate_event(
                    price_view=price_view,
                    observed_on=observed_on,
                    candidate=candidate,
                    stage="TRADE_PLAN",
                    gate_code="TRADE_PLAN_FINAL_ACTION",
                    gate_category="TRADE_PLAN",
                    gate_ordinal=1,
                    stage_reached=True,
                    outcome=(
                        "PASS"
                        if quality.final_action is FinalDecisionAction.ACCEPT
                        else "FAIL"
                    ),
                    primary=quality.final_action is not FinalDecisionAction.ACCEPT,
                    explanation=(
                        " | ".join(quality.weaknesses)
                        if quality.weaknesses
                        else "Trade-plan quality passed without a recorded weakness."
                    ),
                    suggested_action=quality.final_action.value,
                )
            )

    terminal_stage, terminal_gate = _terminal_gate(
        decision,
        base_failures=base_failures,
        stress_failures=stress_failures,
    )
    if not decision.accepted and terminal_gate == "UNEXPLAINED_REJECTION":
        defects.append(
            f"{price_view}_UNEXPLAINED_FINAL_REJECTION@"
            f"{observed_on.isoformat()}|{candidate.symbol}"
        )
    events.append(
        _gate_event(
            price_view=price_view,
            observed_on=observed_on,
            candidate=candidate,
            stage="FINAL_DECISION",
            gate_code="INSTITUTIONAL_APPROVAL",
            gate_category="APPROVAL",
            gate_ordinal=1,
            stage_reached=True,
            outcome="PASS" if decision.accepted else "FAIL",
            primary=decision.accepted,
            explanation=(
                "Candidate passed the complete institutional decision path."
                if decision.accepted
                else f"Candidate terminated at {terminal_stage}:{terminal_gate}."
            ),
        )
    )
    fingerprint = _candidate_input_fingerprint(candidate)
    record = ForensicCandidate(
        price_view=price_view,
        observed_on=observed_on,
        symbol=candidate.symbol,
        rank=rank,
        final_signal=candidate.final_verdict,
        approvable_signal=approvable_signal,
        recommendation_score=candidate.final_score,
        adjusted_confidence=candidate.adjusted_confidence,
        setup_stage=candidate.setup_stage,
        entry_ready=candidate.entry_ready,
        trigger_status=candidate.trigger_status,
        execution_status=candidate.execution_status,
        allocation_eligible=candidate.allocation_eligible,
        evidence_strength=candidate.evidence_strength,
        evidence_sample_count=candidate.evidence_sample_count,
        posterior_probability=candidate.posterior_probability,
        expectancy=candidate.expectancy,
        reward_risk_ratio=candidate.reward_risk_ratio,
        stop_distance_percent=candidate.stop_distance_percent,
        data_completeness=candidate.data_completeness,
        capacity_score=candidate.capacity.capacity_score,
        base_gate_decision=decision.gate_decision.value,
        base_failure_codes=base_failures,
        stress_stage_reached=stress_reached,
        stress_failure_codes=stress_failures,
        stress_final_action=stress_action,
        trade_plan_stage_reached=trade_plan_reached,
        trade_plan_quality_score=trade_plan_score,
        trade_plan_final_action=trade_plan_action,
        terminal_stage=terminal_stage,
        terminal_gate=terminal_gate,
        institutional_approved=decision.accepted,
        provisional_allocation_target_amount=provisional_allocation_target_amount,
        portfolio_eligible=(
            decision.accepted and provisional_allocation_target_amount > Decimal("0")
        ),
        input_fingerprint=fingerprint,
    )
    return record, tuple(events), tuple(defects)


def _gate_event(
    *,
    price_view: str,
    observed_on: date,
    candidate: InstitutionalCandidate,
    stage: str,
    gate_code: str,
    gate_category: str,
    gate_ordinal: int,
    stage_reached: bool,
    outcome: str,
    primary: bool,
    explanation: str,
    severity: str = "",
    suggested_action: str = "",
) -> dict[str, object]:
    return {
        "price_view": price_view,
        "observed_on": observed_on,
        "symbol": candidate.symbol,
        "final_signal": candidate.final_verdict,
        "approvable_signal": candidate.final_verdict in _APPROVABLE_SIGNALS,
        "stage": stage,
        "gate_code": gate_code,
        "gate_category": gate_category,
        "gate_ordinal": gate_ordinal,
        "stage_reached": stage_reached,
        "outcome": outcome,
        "primary": primary,
        "severity": severity,
        "suggested_action": suggested_action,
        "explanation": explanation,
    }


def _terminal_gate(
    decision: OpportunityDecision,
    *,
    base_failures: tuple[str, ...],
    stress_failures: tuple[str, ...],
) -> tuple[str, str]:
    if base_failures:
        return "BASE_GATE", base_failures[0]
    if decision.decision_quality is None:
        return (
            ("FINAL_DECISION", "ACCEPTED")
            if decision.accepted
            else ("FINAL_DECISION", "UNEXPLAINED_REJECTION")
        )
    if decision.decision_quality.final_action is not FinalDecisionAction.ACCEPT:
        return (
            "STRESS_TEST",
            f"STRESS:{stress_failures[0]}"
            if stress_failures
            else "STRESS_FINAL_ACTION_REJECT",
        )
    if decision.trade_plan_quality is None:
        return (
            ("FINAL_DECISION", "ACCEPTED")
            if decision.accepted
            else ("TRADE_PLAN", "UNEXPLAINED_REJECTION")
        )
    if decision.trade_plan_quality.final_action is not FinalDecisionAction.ACCEPT:
        return "TRADE_PLAN", "TRADE_PLAN_QUALITY_REJECT"
    if decision.accepted:
        return "FINAL_DECISION", "ACCEPTED"
    return "FINAL_DECISION", "UNEXPLAINED_REJECTION"


def _allocation_amounts(plan: object) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for item in getattr(plan, "reports", ()):
        symbol = str(getattr(item, "symbol", "")).strip().upper()
        if symbol:
            result[symbol] = _decimal(
                getattr(item, "target_amount", "0"),
                f"allocation target for {symbol}",
            )
    return result


def _reconcile_arm(
    candidates: tuple[ForensicCandidate, ...],
    bundle: BenchmarkApprovalBundle,
    b4_summary: Mapping[str, object],
    *,
    price_view: str,
) -> tuple[tuple[dict[str, object], ...], dict[str, object]]:
    defects: list[str] = []
    benchmark: dict[tuple[date, str], dict[str, str]] = {}
    for benchmark_row in bundle.approval_rows:
        key = (
            _date_value(
                benchmark_row.get("observed_on"),
                f"{price_view} benchmark date",
            ),
            _symbol(
                benchmark_row.get("symbol"),
                f"{price_view} benchmark symbol",
            ),
        )
        if key in benchmark:
            defects.append(
                f"{price_view}_DUPLICATE_BENCHMARK_APPROVAL@{key[0]}|{key[1]}"
            )
        benchmark[key] = benchmark_row
    forensic = {(item.observed_on, item.symbol): item for item in candidates}
    for key in sorted(set(benchmark).difference(forensic)):
        defects.append(
            f"{price_view}_BENCHMARK_CANDIDATE_MISSING_FROM_FORENSICS@"
            f"{key[0].isoformat()}|{key[1]}"
        )
    for key in sorted(set(forensic).difference(benchmark)):
        defects.append(
            f"{price_view}_FORENSIC_CANDIDATE_MISSING_FROM_BENCHMARK@"
            f"{key[0].isoformat()}|{key[1]}"
        )

    rows: list[dict[str, object]] = []
    parity_mismatches = 0
    for item in candidates:
        candidate_row = item.as_dict()
        evidence = benchmark.get((item.observed_on, item.symbol))
        parity = False
        if evidence is not None:
            benchmark_signal = str(evidence.get("final_signal") or "").strip().upper()
            benchmark_score = _decimal(
                evidence.get("opportunity_score"),
                f"{price_view} benchmark score",
            )
            benchmark_approved = _boolean(
                evidence.get("approved"),
                f"{price_view} benchmark approved",
            )
            benchmark_reason = str(evidence.get("primary_reason_code") or "").strip()
            expected_reason = (
                item.base_failure_codes[0]
                if item.base_failure_codes
                else "ACCEPTED"
                if item.institutional_approved
                else "UNKNOWN"
            )
            parity = (
                benchmark_signal == item.final_signal
                and benchmark_score == item.recommendation_score
                and benchmark_approved == item.institutional_approved
                and benchmark_reason == expected_reason
            )
            candidate_row.update(
                {
                    "benchmark_present": True,
                    "benchmark_signal": benchmark_signal,
                    "benchmark_score": benchmark_score,
                    "benchmark_approved": benchmark_approved,
                    "benchmark_primary_reason": benchmark_reason,
                    "benchmark_parity": parity,
                }
            )
        else:
            candidate_row.update(
                {
                    "benchmark_present": False,
                    "benchmark_signal": None,
                    "benchmark_score": None,
                    "benchmark_approved": None,
                    "benchmark_primary_reason": None,
                    "benchmark_parity": False,
                }
            )
        if not parity:
            parity_mismatches += 1
            if evidence is not None:
                defects.append(
                    f"{price_view}_BENCHMARK_PARITY_MISMATCH@"
                    f"{item.observed_on.isoformat()}|{item.symbol}"
                )
        rows.append(candidate_row)

    session_rows = {
        _date_value(row.get("observed_on"), f"{price_view} session date"): row
        for row in bundle.candidate_rows
    }
    grouped_by_date = _group_candidates_by_date(candidates)
    for observed_on, session in sorted(session_rows.items()):
        grouped = grouped_by_date.get(observed_on, ())
        if len(grouped) != _integer(
            session.get("technical_candidates"),
            f"{price_view} technical candidates",
        ):
            defects.append(
                f"{price_view}_TECHNICAL_CANDIDATE_COUNT_MISMATCH@{observed_on}"
            )
        if sum(item.approvable_signal for item in grouped) != (
            _integer(session.get("buy_candidates"), f"{price_view} BUY candidates")
            + _integer(
                session.get("strong_buy_candidates"),
                f"{price_view} STRONG_BUY candidates",
            )
        ):
            defects.append(
                f"{price_view}_APPROVABLE_CANDIDATE_COUNT_MISMATCH@{observed_on}"
            )
        if sum(item.institutional_approved for item in grouped) != _integer(
            session.get("institutional_approvals"),
            f"{price_view} institutional approvals",
        ):
            defects.append(
                f"{price_view}_INSTITUTIONAL_APPROVAL_COUNT_MISMATCH@{observed_on}"
            )
    for observed_on in sorted(set(grouped_by_date).difference(session_rows)):
        defects.append(
            f"{price_view}_FORENSIC_SESSION_MISSING_FROM_BENCHMARK@{observed_on}"
        )
    if len(candidates) != _integer(b4_summary.get("candidate_count"), "B4 candidates"):
        defects.append(f"{price_view}_B4_CANDIDATE_COUNT_MISMATCH")
    if sum(item.approvable_signal for item in candidates) != _integer(
        b4_summary.get("approvable_signal_count"),
        "B4 approvable signals",
    ):
        defects.append(f"{price_view}_B4_APPROVABLE_COUNT_MISMATCH")
    if sum(item.institutional_approved for item in candidates) != _integer(
        b4_summary.get("institutional_approval_count"),
        "B4 institutional approvals",
    ):
        defects.append(f"{price_view}_B4_APPROVAL_COUNT_MISMATCH")
    return tuple(rows), {
        "candidate_count": len(candidates),
        "benchmark_candidate_count": len(bundle.approval_rows),
        "parity_match_count": len(candidates) - parity_mismatches,
        "parity_mismatch_count": parity_mismatches,
        "defects": tuple(sorted(set(defects))),
    }


def _group_candidates_by_date(
    candidates: Sequence[ForensicCandidate],
) -> dict[date, tuple[ForensicCandidate, ...]]:
    grouped: dict[date, list[ForensicCandidate]] = defaultdict(list)
    for item in candidates:
        grouped[item.observed_on].append(item)
    return {key: tuple(value) for key, value in grouped.items()}


def _arm_summary(candidates: tuple[ForensicCandidate, ...]) -> dict[str, object]:
    approvable = tuple(item for item in candidates if item.approvable_signal)
    terminal = Counter(item.terminal_gate for item in approvable)
    unexplained = sum(
        item.terminal_gate == "UNEXPLAINED_REJECTION" for item in approvable
    )
    return {
        "candidate_count": len(candidates),
        "approvable_candidate_count": len(approvable),
        "institutional_approval_count": sum(
            item.institutional_approved for item in approvable
        ),
        "base_rejection_count": sum(
            bool(item.base_failure_codes) for item in approvable
        ),
        "stress_rejection_count": sum(
            item.terminal_stage == "STRESS_TEST" for item in approvable
        ),
        "trade_plan_rejection_count": sum(
            item.terminal_stage == "TRADE_PLAN" for item in approvable
        ),
        "unexplained_terminal_gate_count": unexplained,
        "distinct_terminal_gate_count": len(terminal),
        "terminal_gate_counts": dict(sorted(terminal.items())),
    }


def _arm_comparison(
    raw_rows: tuple[dict[str, object], ...],
    adjusted_rows: tuple[dict[str, object], ...],
) -> tuple[tuple[dict[str, object], ...], int]:
    raw = {
        (cast(date, row["observed_on"]), str(row["symbol"])): row for row in raw_rows
    }
    adjusted = {
        (cast(date, row["observed_on"]), str(row["symbol"])): row
        for row in adjusted_rows
    }
    result: list[dict[str, object]] = []
    unexplained = 0
    for key in sorted(set(raw).union(adjusted)):
        left = raw.get(key)
        right = adjusted.get(key)
        raw_signal = None if left is None else left["final_signal"]
        adjusted_signal = None if right is None else right["final_signal"]
        raw_score = (
            None if left is None else cast(Decimal, left["recommendation_score"])
        )
        adjusted_score = (
            None if right is None else cast(Decimal, right["recommendation_score"])
        )
        raw_fingerprint = None if left is None else left["input_fingerprint"]
        adjusted_fingerprint = None if right is None else right["input_fingerprint"]
        raw_gate = None if left is None else left["terminal_gate"]
        adjusted_gate = None if right is None else right["terminal_gate"]
        raw_approved = None if left is None else left["institutional_approved"]
        adjusted_approved = None if right is None else right["institutional_approved"]
        both_present = left is not None and right is not None
        input_changed = raw_fingerprint != adjusted_fingerprint
        gate_changed = raw_gate != adjusted_gate
        explained = both_present and (not gate_changed or input_changed)
        divergence = not both_present or (gate_changed and not input_changed)
        unexplained += divergence
        result.append(
            {
                "observed_on": key[0],
                "symbol": key[1],
                "raw_present": left is not None,
                "adjusted_present": right is not None,
                "raw_signal": raw_signal,
                "adjusted_signal": adjusted_signal,
                "signal_changed": raw_signal != adjusted_signal,
                "raw_score": raw_score,
                "adjusted_score": adjusted_score,
                "score_delta": (
                    adjusted_score - raw_score
                    if raw_score is not None and adjusted_score is not None
                    else None
                ),
                "raw_input_fingerprint": raw_fingerprint,
                "adjusted_input_fingerprint": adjusted_fingerprint,
                "input_changed": input_changed,
                "raw_terminal_gate": raw_gate,
                "adjusted_terminal_gate": adjusted_gate,
                "terminal_gate_changed": gate_changed,
                "raw_approved": raw_approved,
                "adjusted_approved": adjusted_approved,
                "approval_changed": raw_approved != adjusted_approved,
                "explained_gate_difference": explained,
                "unexplained_gate_divergence": divergence,
            }
        )
    return tuple(result), unexplained


def _gate_prevalence(
    rows: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, object]]] = defaultdict(
        list
    )
    for row in rows:
        key = (
            str(row["price_view"]),
            str(row["stage"]),
            str(row["gate_code"]),
            str(row["gate_category"]),
        )
        grouped[key].append(row)
    result: list[dict[str, object]] = []
    for key, items in sorted(grouped.items()):
        reached_keys = {
            (cast(date, item["observed_on"]), str(item["symbol"]))
            for item in items
            if bool(item["stage_reached"])
        }
        pass_keys = {
            (cast(date, item["observed_on"]), str(item["symbol"]))
            for item in items
            if item["outcome"] == "PASS"
        }
        fail_keys = {
            (cast(date, item["observed_on"]), str(item["symbol"]))
            for item in items
            if item["outcome"] == "FAIL"
        }
        result.append(
            {
                "price_view": key[0],
                "stage": key[1],
                "gate_code": key[2],
                "gate_category": key[3],
                "reached_candidate_count": len(reached_keys),
                "passed_candidate_count": len(pass_keys),
                "failed_candidate_count": len(fail_keys),
                "failure_percent": _percent(len(fail_keys), len(reached_keys)),
            }
        )
    return tuple(result)


def _deficiency_attribution(
    gate_rows: tuple[dict[str, object], ...],
    candidate_rows: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    approvable_counts = Counter(
        str(row["price_view"])
        for row in candidate_rows
        if bool(row["approvable_signal"])
    )
    grouped: dict[tuple[str, str, str, str], list[dict[str, object]]] = defaultdict(
        list
    )
    for row in gate_rows:
        if row["outcome"] != "FAIL" or not bool(row["approvable_signal"]):
            continue
        key = (
            str(row["price_view"]),
            str(row["stage"]),
            str(row["gate_code"]),
            str(row["gate_category"]),
        )
        grouped[key].append(row)
    result: list[dict[str, object]] = []
    for key, items in sorted(grouped.items()):
        affected = {
            (cast(date, item["observed_on"]), str(item["symbol"])) for item in items
        }
        primary = {
            (cast(date, item["observed_on"]), str(item["symbol"]))
            for item in items
            if bool(item["primary"])
        }
        denominator = approvable_counts[key[0]]
        result.append(
            {
                "price_view": key[0],
                "stage": key[1],
                "gate_code": key[2],
                "gate_category": key[3],
                "affected_candidate_count": len(affected),
                "primary_candidate_count": len(primary),
                "approvable_candidate_count": denominator,
                "affected_percent": _percent(len(affected), denominator),
            }
        )
    return tuple(result)


def _structural_probes() -> tuple[
    tuple[dict[str, object], ...],
    dict[str, object],
    tuple[str, ...],
]:
    base = _passing_candidate()
    mutations = _base_gate_mutations()
    defects: list[str] = []
    if set(mutations) != set(RejectionReasonCode):
        defects.append("STRUCTURAL_PROBE_GATE_FAMILY_COVERAGE_MISMATCH")
    specifications: list[ProbeSpecification] = [
        (
            "CONTROL_ACCEPT",
            "FULL_PATH",
            "FINAL_DECISION",
            "ACCEPTED",
            True,
            base,
        ),
    ]
    for code in RejectionReasonCode:
        mutation = mutations.get(code)
        if mutation is None:
            continue
        specifications.append(
            (
                f"BASE_GATE:{code.value}",
                "BASE_GATE_FAMILY",
                "BASE_GATE",
                code.value,
                False,
                mutation(base),
            )
        )
    specifications.extend(
        (
            (
                "STRESS_STAGE:POOR_REWARD_RISK",
                "STRESS_STAGE",
                "STRESS_TEST",
                "STRESS:POOR_REWARD_RISK",
                False,
                replace(base, reward_risk_ratio=Decimal("2.40")),
            ),
            (
                "TRADE_PLAN_STAGE:NO_VALID_TARGET",
                "TRADE_PLAN_STAGE",
                "TRADE_PLAN",
                "TRADE_PLAN_QUALITY_REJECT",
                False,
                replace(
                    base,
                    target_1=Decimal("99"),
                    target_2=Decimal("98"),
                    target_3=None,
                    resistance_level=None,
                    swing_high=None,
                ),
            ),
        )
    )
    first = _evaluate_probe_set(specifications)
    second = _evaluate_probe_set(specifications)
    rows: list[dict[str, object]] = []
    matched_count = 0
    for left, right in zip(first, second, strict=True):
        deterministic = _probe_signature(left) == _probe_signature(right)
        matched = _probe_expectation_matched(left)
        matched_count += matched
        row = dict(left)
        row["expectation_matched"] = matched
        row["deterministic"] = deterministic
        rows.append(row)
        if not matched:
            defects.append(f"STRUCTURAL_PROBE_EXPECTATION_FAILED:{left['probe_id']}")
        if not deterministic:
            defects.append(f"STRUCTURAL_PROBE_NONDETERMINISTIC:{left['probe_id']}")
    acceptance = next(item for item in rows if item["probe_id"] == "CONTROL_ACCEPT")
    gate_rows = tuple(
        item for item in rows if item["probe_scope"] == "BASE_GATE_FAMILY"
    )
    stress = next(item for item in rows if item["probe_scope"] == "STRESS_STAGE")
    trade_plan = next(
        item for item in rows if item["probe_scope"] == "TRADE_PLAN_STAGE"
    )
    acceptance_reachable = (
        acceptance["observed_accepted"] is True
        and acceptance["expectation_matched"] is True
    )
    base_discriminating = all(
        item["expectation_matched"] is True for item in gate_rows
    ) and len(gate_rows) == len(RejectionReasonCode)
    stress_discriminating = stress["expectation_matched"] is True
    trade_plan_discriminating = trade_plan["expectation_matched"] is True
    summary: dict[str, object] = {
        "probe_count": len(rows),
        "matched_probe_count": matched_count,
        "acceptance_path_reachable": acceptance_reachable,
        "base_gate_family_count": len(RejectionReasonCode),
        "discriminating_base_gate_family_count": sum(
            item["expectation_matched"] is True for item in gate_rows
        ),
        "all_base_gate_families_discriminating": base_discriminating,
        "stress_rejection_path_discriminating": stress_discriminating,
        "trade_plan_rejection_path_discriminating": trade_plan_discriminating,
        "all_institutional_stages_discriminating": (
            acceptance_reachable
            and base_discriminating
            and stress_discriminating
            and trade_plan_discriminating
        ),
        "deterministic": all(item["deterministic"] is True for item in rows),
    }
    return tuple(rows), summary, tuple(sorted(set(defects)))


def _evaluate_probe_set(
    specifications: Sequence[ProbeSpecification],
) -> tuple[dict[str, object], ...]:
    engine = InstitutionalDecisionEngine()
    result: list[dict[str, object]] = []
    for (
        probe_id,
        scope,
        expected_stage,
        expected_code,
        expected_accepted,
        candidate,
    ) in specifications:
        decision = engine.evaluate((candidate,)).decisions[0]
        base_failures = tuple(item.code.value for item in decision.rejection_reasons)
        stress_failures = tuple(
            item.reason_code.value for item in decision.stress_tests if not item.passed
        )
        terminal_stage, terminal_gate = _terminal_gate(
            decision,
            base_failures=base_failures,
            stress_failures=stress_failures,
        )
        result.append(
            {
                "probe_id": probe_id,
                "probe_scope": scope,
                "expected_terminal_stage": expected_stage,
                "expected_gate_code": expected_code,
                "expected_accepted": expected_accepted,
                "observed_base_gate_decision": decision.gate_decision.value,
                "observed_base_failure_codes": base_failures,
                "observed_stress_failure_codes": stress_failures,
                "observed_stress_final_action": (
                    "NOT_REACHED"
                    if decision.decision_quality is None
                    else decision.decision_quality.final_action.value.upper()
                ),
                "observed_trade_plan_final_action": (
                    "NOT_REACHED"
                    if decision.trade_plan_quality is None
                    else decision.trade_plan_quality.final_action.value.upper()
                ),
                "observed_terminal_stage": terminal_stage,
                "observed_terminal_gate": terminal_gate,
                "observed_accepted": decision.accepted,
            }
        )
    return tuple(result)


def _probe_expectation_matched(row: Mapping[str, object]) -> bool:
    scope = str(row["probe_scope"])
    expected_code = str(row["expected_gate_code"])
    base_failures = cast(tuple[str, ...], row["observed_base_failure_codes"])
    accepted_matches = bool(row["observed_accepted"]) == bool(row["expected_accepted"])
    if scope == "BASE_GATE_FAMILY":
        return (
            accepted_matches
            and row["observed_terminal_stage"] == "BASE_GATE"
            and row["observed_terminal_gate"] == expected_code
            and bool(base_failures)
            and base_failures[0] == expected_code
        )
    stage_and_gate_match = (
        row["observed_terminal_stage"] == row["expected_terminal_stage"]
        and row["observed_terminal_gate"] == expected_code
    )
    if scope == "STRESS_STAGE":
        return (
            accepted_matches
            and not base_failures
            and row["observed_stress_final_action"] == "REJECT"
            and row["observed_trade_plan_final_action"] == "NOT_REACHED"
            and stage_and_gate_match
        )
    if scope == "TRADE_PLAN_STAGE":
        return (
            accepted_matches
            and not base_failures
            and row["observed_stress_final_action"] == "ACCEPT"
            and row["observed_trade_plan_final_action"] == "REJECT"
            and stage_and_gate_match
        )
    return accepted_matches and not base_failures and stage_and_gate_match


def _probe_signature(row: Mapping[str, object]) -> str:
    return _digest_mapping(
        {
            key: value
            for key, value in row.items()
            if key not in {"expectation_matched", "deterministic"}
        }
    )


def _passing_candidate() -> InstitutionalCandidate:
    return InstitutionalCandidate(
        symbol="B5CONTROL",
        final_verdict="BUY",
        adjusted_confidence="HIGH",
        evidence_strength="strong",
        final_score=Decimal("96"),
        reward_risk_ratio=Decimal("3"),
        stop_distance_percent=Decimal("5"),
        data_completeness="COMPLETE",
        setup_quality="EXCELLENT",
        sector="FORENSIC",
        market_regime="BULLISH",
        sector_fit=Decimal("90"),
        portfolio_fit=Decimal("90"),
        posterior_probability=Decimal("0.68"),
        expectancy=Decimal("0.45"),
        entry=Decimal("100"),
        stop=Decimal("95"),
        target_1=Decimal("110"),
        target_2=Decimal("115"),
        target_3=Decimal("120"),
        capacity=CapacityAssessment(
            capacity_score=Decimal("95"),
            deployable_capital_estimate=Decimal("10000000"),
            liquidity_warning=None,
            explanation="Forensic control has sufficient deterministic capacity.",
            data_sufficient=True,
        ),
        support_level=Decimal("96"),
        swing_low=Decimal("94"),
        dma_20=Decimal("97"),
        atr=Decimal("2"),
        resistance_level=Decimal("115"),
        swing_high=Decimal("120"),
        live_feed_healthy=True,
        live_risk_warning_count=0,
        evidence_sample_count=120,
        recent_similar_failures=0,
        conflicting_signal_count=0,
        near_resistance=False,
        gap_risk=False,
        missing_data=(),
        setup_stage="ENTRY_READY",
        entry_ready=True,
        trigger_status="TRIGGER_CONFIRMED",
        execution_status="BUY NOW",
        allocation_eligible=True,
        historical_bar_count=1260,
        bearish_indicator_count=0,
        bearish_indicator_reasons=(),
    )


def _base_gate_mutations() -> dict[
    RejectionReasonCode,
    Callable[[InstitutionalCandidate], InstitutionalCandidate],
]:
    return {
        RejectionReasonCode.WEAK_VERDICT: lambda item: replace(
            item,
            final_verdict="HOLD",
        ),
        RejectionReasonCode.WEAK_CONFIDENCE: lambda item: replace(
            item,
            adjusted_confidence="LOW",
        ),
        RejectionReasonCode.INSUFFICIENT_EVIDENCE: lambda item: replace(
            item,
            evidence_strength="insufficient",
            evidence_sample_count=0,
        ),
        RejectionReasonCode.POOR_REWARD_RISK: lambda item: replace(
            item,
            reward_risk_ratio=Decimal("1.50"),
        ),
        RejectionReasonCode.EXCESS_DOWNSIDE_RISK: lambda item: replace(
            item,
            stop_distance_percent=Decimal("11"),
        ),
        RejectionReasonCode.POOR_DATA_COMPLETENESS: lambda item: replace(
            item,
            data_completeness="PARTIAL",
        ),
        RejectionReasonCode.INSUFFICIENT_CAPACITY: lambda item: replace(
            item,
            capacity=CapacityAssessment(
                capacity_score=Decimal("20"),
                deployable_capital_estimate=None,
                liquidity_warning="Insufficient capacity probe.",
                explanation="Forensic mutation intentionally lacks capacity.",
                data_sufficient=False,
            ),
        ),
        RejectionReasonCode.LIVE_FEED_UNHEALTHY: lambda item: replace(
            item,
            live_feed_healthy=False,
        ),
        RejectionReasonCode.WEAK_SETUP: lambda item: replace(
            item,
            final_score=Decimal("80"),
        ),
        RejectionReasonCode.MISSING_TRADE_PLAN: lambda item: replace(
            item,
            target_2=None,
            target_3=None,
        ),
        RejectionReasonCode.PENDING_ENTRY_TRIGGER: lambda item: replace(
            item,
            entry_ready=False,
            trigger_status="PENDING",
            execution_status="WAIT FOR CONFIRMATION",
            allocation_eligible=False,
        ),
        RejectionReasonCode.LATE_ENTRY: lambda item: replace(
            item,
            setup_stage="LATE",
            execution_status="HOLD / NO FRESH ENTRY",
        ),
        RejectionReasonCode.POOR_HISTORICAL_EDGE: lambda item: replace(
            item,
            evidence_strength="strong",
            evidence_sample_count=120,
            expectancy=Decimal("-0.10"),
            posterior_probability=Decimal("0.68"),
        ),
    }


def _candidate_input_fingerprint(candidate: InstitutionalCandidate) -> str:
    payload = asdict(candidate)
    return _digest_mapping(payload)


def _base_gate_category(code: RejectionReasonCode) -> str:
    mapping = {
        RejectionReasonCode.WEAK_VERDICT: "SIGNAL",
        RejectionReasonCode.WEAK_CONFIDENCE: "EVIDENCE",
        RejectionReasonCode.INSUFFICIENT_EVIDENCE: "EVIDENCE",
        RejectionReasonCode.POOR_REWARD_RISK: "RISK",
        RejectionReasonCode.EXCESS_DOWNSIDE_RISK: "RISK",
        RejectionReasonCode.POOR_DATA_COMPLETENESS: "DATA",
        RejectionReasonCode.INSUFFICIENT_CAPACITY: "CAPACITY",
        RejectionReasonCode.LIVE_FEED_UNHEALTHY: "DATA",
        RejectionReasonCode.WEAK_SETUP: "SETUP",
        RejectionReasonCode.MISSING_TRADE_PLAN: "TRADE_PLAN",
        RejectionReasonCode.PENDING_ENTRY_TRIGGER: "ENTRY_TIMING",
        RejectionReasonCode.LATE_ENTRY: "ENTRY_TIMING",
        RejectionReasonCode.POOR_HISTORICAL_EDGE: "EVIDENCE",
    }
    return mapping[code]


def _hash_paths(paths: Mapping[str, Path]) -> dict[str, str]:
    return {key: _file_sha256(path) for key, path in sorted(paths.items())}


def _validate_paths_unchanged(
    paths: Mapping[str, Path],
    expected: Mapping[str, str],
) -> None:
    observed = _hash_paths(paths)
    for key, digest in observed.items():
        if expected.get(key) != digest:
            raise ValueError(f"input artifact changed during B5 replay: {key}")


def _policy_source_hashes(project_root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in _POLICY_SOURCE_PATHS:
        path = project_root / relative
        result[relative] = _file_sha256(path)
    return result


def _pipeline_component_hashes(project_root: Path) -> dict[str, str]:
    return {
        key: _tree_hash(project_root, entries)
        for key, entries in sorted(_FROZEN_PIPELINE_COMPONENTS.items())
    }


def _validate_frozen_pipeline_components(
    *,
    project_root: Path,
    raw_manifest: Mapping[str, object],
    adjusted_manifest: Mapping[str, object],
) -> dict[str, str]:
    raw_versions = _nested_mapping(raw_manifest, "versions")
    adjusted_versions = _nested_mapping(adjusted_manifest, "versions")
    observed = _pipeline_component_hashes(project_root)
    for key, digest in observed.items():
        raw_expected = str(raw_versions.get(key) or "")
        adjusted_expected = str(adjusted_versions.get(key) or "")
        if raw_expected != adjusted_expected:
            raise ValueError(f"RAW and ADJUSTED frozen component differs: {key}")
        if digest != raw_expected:
            raise ValueError(f"current pipeline differs from frozen benchmark: {key}")
    return observed


def _tree_hash(project_root: Path, entries: Sequence[str]) -> str:
    paths: list[Path] = []
    for entry in entries:
        path = project_root / entry
        if path.is_dir():
            paths.extend(
                item
                for item in path.rglob("*")
                if item.is_file() and item.suffix in {".py", ".json", ".toml"}
            )
        elif path.is_file():
            paths.append(path)
        else:
            raise ValueError(f"frozen pipeline source is missing: {entry}")
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        digest.update(str(path.relative_to(project_root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _prevalence_summary(rows: tuple[dict[str, object], ...]) -> dict[str, object]:
    failures = tuple(
        row for row in rows if cast(int, row["failed_candidate_count"]) > 0
    )
    return {
        "row_count": len(rows),
        "failing_gate_row_count": len(failures),
        "raw_failing_gate_row_count": sum(
            row["price_view"] == "RAW" for row in failures
        ),
        "adjusted_failing_gate_row_count": sum(
            row["price_view"] == "ADJUSTED" for row in failures
        ),
    }


def _readiness(
    *,
    defects: tuple[str, ...],
    unexplained_divergences: int,
    empirical_gate_reached: bool,
    trace_complete: bool,
    gate_non_vacuous: bool,
) -> tuple[str, tuple[str, ...]]:
    if defects:
        return B5_BLOCKED_DEFECT, ("APPROVAL_FORENSIC_IMPLEMENTATION_DEFECT",)
    if unexplained_divergences:
        return B5_BLOCKED_DIVERGENCE, ("UNEXPLAINED_APPROVAL_GATE_DIVERGENCE",)
    if not empirical_gate_reached:
        return B5_BLOCKED_UNREACHED, ("APPROVAL_GATE_NOT_REACHED",)
    if not trace_complete:
        return B5_BLOCKED_EVIDENCE, ("INCOMPLETE_APPROVAL_GATE_TRACE",)
    if not gate_non_vacuous:
        return B5_BLOCKED_VACUOUS, ("APPROVAL_GATE_NON_VACUITY_NOT_PROVEN",)
    return B5_READY, ()


def _without_defects(value: Mapping[str, object]) -> dict[str, object]:
    return {key: item for key, item in value.items() if key != "defects"}


def _safe_relative_artifact_name(value: object) -> Path:
    name = str(value)
    path = Path(name)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe artifact path: {name}")
    return path


def _artifact_path(root: Path, value: object) -> Path:
    relative = _safe_relative_artifact_name(value)
    candidate = root / relative
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"artifact path cannot contain symlinks: {value}")
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve(strict=False)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"artifact path escapes its root: {value}") from error
    return candidate


def _nested_mapping(payload: Mapping[str, object], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"artifact is missing mapping {key}")
    return {str(item_key): item for item_key, item in value.items()}


def _list_value(
    payload: Mapping[str, object],
    key: str,
    label: str,
) -> tuple[object, ...]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return tuple(value)


def _mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"artifact must contain a mapping: {path}")
    return {str(key): value for key, value in payload.items()}


def _csv_rows(path: Path) -> tuple[dict[str, str], ...]:
    if not path.is_file():
        raise ValueError(f"required benchmark artifact is missing: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return tuple(
            {
                str(key): "" if value is None else str(value)
                for key, value in row.items()
            }
            for row in csv.DictReader(handle)
        )


def _file_sha256(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"required artifact is missing: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _digest_mapping(value: Mapping[str, object]) -> str:
    payload = dict(value)
    payload.pop("report_sha256", None)
    encoded = json.dumps(
        _json_ready(payload),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _digest_sequence(values: Sequence[str]) -> str:
    encoded = json.dumps(list(values), separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validate_digest(payload: dict[str, Any], label: str) -> None:
    expected = str(payload.get("report_sha256") or "")
    if len(expected) != 64 or expected != _digest_mapping(payload):
        raise ValueError(f"{label} digest mismatch")


def _validate_research_only_flags(payload: Mapping[str, object]) -> None:
    for key in (
        "live_scoring_enabled",
        "recommendation_influence",
        "portfolio_policy_influence",
        "execution_influence",
        "learning_mutation_enabled",
        "active_replay_integration",
        "production_influence",
    ):
        if payload.get(key) is not False:
            raise ValueError(f"governed research guardrail is not false: {key}")


def _json_ready(value: object) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [_json_ready(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    if isinstance(value, (date, Decimal, Path)):
        return str(value)
    return value


def _date_value(value: object, label: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as error:
        raise ValueError(f"invalid date for {label}") from error


def _integer(value: object, label: str) -> int:
    try:
        result = int(str(value))
    except ValueError as error:
        raise ValueError(f"invalid integer for {label}") from error
    if result < 0:
        raise ValueError(f"negative integer for {label}")
    return result


def _decimal(value: object, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"invalid decimal for {label}") from error
    if not result.is_finite():
        raise ValueError(f"non-finite decimal for {label}")
    return result


def _boolean(value: object, label: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"invalid boolean for {label}")


def _symbol(value: object, label: str) -> str:
    result = str(value or "").strip().upper()
    if not result:
        raise ValueError(f"empty symbol for {label}")
    return result


def _percent(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) * Decimal("100") / Decimal(denominator)).quantize(
        Decimal("0.00000001")
    )


def _safe_error(error: Exception) -> str:
    return " ".join(str(error).split())[:300]


def _progress(
    callback: ProgressCallback | None,
    current: int,
    total: int,
    description: str,
) -> None:
    if callback is not None:
        callback(current, total, description)


def _write_json(path: Path, payload: Mapping[str, object]) -> Path:
    return _write_text(
        path,
        json.dumps(_json_ready(payload), indent=2, sort_keys=True) + "\n",
    )


def _write_csv(
    path: Path,
    rows: tuple[Mapping[str, object], ...],
    *,
    fieldnames: tuple[str, ...],
) -> Path:
    from io import StringIO

    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})
    return _write_text(path, stream.getvalue())


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, (tuple, list)):
        return "|".join(str(_csv_value(item)) for item in value)
    if isinstance(value, (set, frozenset)):
        normalized = sorted(str(_csv_value(item)) for item in value)
        return "|".join(normalized)
    if isinstance(value, (date, Decimal)):
        return str(value)
    if isinstance(value, bool):
        return str(value).lower()
    return value


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return path


def _markdown(report: Mapping[str, object]) -> str:
    raw = cast(Mapping[str, object], report["raw_forensic_summary"])
    adjusted = cast(Mapping[str, object], report["adjusted_forensic_summary"])
    probes = cast(Mapping[str, object], report["structural_probe_summary"])
    blockers = cast(Sequence[object], report["readiness_blockers"])
    defects = cast(Sequence[object], report["implementation_defects"])
    lines = [
        "# HTR-010B5 Governed Institutional Approval-Gate Forensics",
        "",
        f"- Readiness: `{report['readiness_decision']}`",
        f"- Replay Window: `{report['replay_start']}` to `{report['replay_end']}`",
        f"- Sessions: `{report['session_count']}`",
        f"- RAW Approvable Candidates: `{raw['approvable_candidate_count']}`",
        f"- ADJUSTED Approvable Candidates: `{adjusted['approvable_candidate_count']}`",
        f"- RAW Institutional Approvals: `{raw['institutional_approval_count']}`",
        "- ADJUSTED Institutional Approvals: "
        f"`{adjusted['institutional_approval_count']}`",
        f"- Empirical Gate Reached: `{report['empirical_gate_reached']}`",
        f"- Gate Trace Complete: `{report['approval_gate_trace_complete']}`",
        f"- Gate Non-Vacuous: `{report['approval_gate_non_vacuous']}`",
        "- Zero-Approval Policy Consistent: "
        f"`{report['zero_approval_policy_consistent']}`",
        f"- Acceptance Path Reachable: `{probes['acceptance_path_reachable']}`",
        "- All Base Gate Families Discriminating: "
        f"`{probes['all_base_gate_families_discriminating']}`",
        "- Stress Rejection Path Discriminating: "
        f"`{probes['stress_rejection_path_discriminating']}`",
        "- Trade-Plan Rejection Path Discriminating: "
        f"`{probes['trade_plan_rejection_path_discriminating']}`",
        "- All Institutional Stages Discriminating: "
        f"`{probes['all_institutional_stages_discriminating']}`",
        f"- Research Scope: `{report['research_scope']}`",
        "- Governed Adjusted Trade Research Enabled: `False`",
        "- Production Influence: `False`",
        "",
        "## Readiness Blockers",
        "",
    ]
    if blockers:
        lines.extend(f"- `{item}`" for item in blockers)
    else:
        lines.append("- `NONE`")
    lines.extend(["", "## Implementation Defects", ""])
    if defects:
        lines.extend(f"- `{item}`" for item in defects)
    else:
        lines.append("- `NONE`")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "This certificate distinguishes an empirically reached but zero-acceptance "
            "institutional population from a vacuous or hard-coded all-reject gate. "
            "The structural probes are synthetic invariants only; they never enter the "
            "replay population and never influence recommendations, allocation, "
            "execution, learning, or production.",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "B5_BLOCKED_DEFECT",
    "B5_BLOCKED_DIVERGENCE",
    "B5_BLOCKED_EVIDENCE",
    "B5_BLOCKED_UNREACHED",
    "B5_BLOCKED_VACUOUS",
    "B5_READY",
    "HTR010B5_CONTRACT_VERSION",
    "RESEARCH_SCOPE",
    "GovernedApprovalGateForensicsEngine",
    "GovernedApprovalGateForensicsResult",
    "export_governed_approval_gate_forensics",
    "validate_governed_approval_gate_forensics_certificate",
]
