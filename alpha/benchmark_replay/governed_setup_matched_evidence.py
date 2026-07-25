"""Governed setup-matched evidence sufficiency certification for HTR-010B7."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Any, cast

from alpha.benchmark_replay.governed_adjusted import (
    GovernedBenchmarkStore,
    GovernedBenchmarkStorePair,
    build_governed_benchmark_stores,
)
from alpha.benchmark_replay.governed_approval_constraint_frontier import (
    B6_READY,
    HTR010B6_CONTRACT_VERSION,
    validate_governed_approval_constraint_frontier_certificate,
)
from alpha.benchmark_replay.governed_approval_gate_forensics import (
    B5_READY,
    HTR010B5_CONTRACT_VERSION,
    validate_governed_approval_gate_forensics_certificate,
)
from alpha.benchmark_replay.governed_approval_gate_forensics import (
    _pipeline_component_hashes as _b5_pipeline_component_hashes,
)
from alpha.benchmark_replay.governed_approval_gate_forensics import (
    _policy_source_hashes as _b5_policy_source_hashes,
)
from alpha.canonical_universe_audit.engine import (
    AuditRunRequest,
    CanonicalUniverseAuditEngine,
)
from alpha.canonical_universe_audit.models import (
    CandidateOutcomeRecord,
    CandidateRankingRecord,
    CanonicalUniverseAuditReport,
)
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.decision_intelligence.engine import (
    _MIN_APPROVAL_EXPECTANCY,
    _MIN_APPROVAL_POSTERIOR,
    _MIN_APPROVAL_SAMPLE_COUNT,
)

HTR010B7_CONTRACT_VERSION = "HTR-010B7-v1.0.0"

B7_READY = "READY_FOR_GOVERNED_SETUP_MATCHED_EVIDENCE_RESEARCH"
B7_BLOCKED_EMPTY = "BLOCKED_BY_EMPTY_SETUP_MATCHED_EVIDENCE_POPULATION"
B7_BLOCKED_PROVENANCE = "BLOCKED_BY_INCOMPLETE_EVIDENCE_PROVENANCE"
B7_BLOCKED_SETUP = "BLOCKED_BY_SETUP_IDENTITY_RECONSTRUCTION_DEFECT"
B7_BLOCKED_DIVERGENCE = "BLOCKED_BY_UNEXPLAINED_EVIDENCE_DIVERGENCE"

RESEARCH_SCOPE = "GOVERNED_SETUP_MATCHED_EVIDENCE_RESEARCH_ONLY"

ProgressCallback = Callable[[int, int, str], None]
CandidateKey = tuple[str, date, str]
ArmCandidateKey = tuple[date, str]

_B5_CANDIDATE_ARTIFACT = "htr010b5_candidate_gate_forensics.csv"
_B5_GATE_ARTIFACT = "htr010b5_gate_event_ledger.csv"
_B6_FRONTIER_ARTIFACT = "htr010b6_candidate_constraint_frontier.csv"
_B6_MARGIN_ARTIFACT = "htr010b6_constraint_margin_ledger.csv"
_SAMPLE_CONSTRAINT_ID = "BASE.INSUFFICIENT_EVIDENCE.SAMPLE_COUNT"
_REQUIRED_SAMPLE_COUNT = int(_MIN_APPROVAL_SAMPLE_COUNT)

_REQUIRED_B7_SUPPORT_ARTIFACTS = frozenset(
    {
        "htr010b7_candidate_evidence_sufficiency.csv",
        "htr010b7_setup_cohort_coverage.csv",
        "htr010b7_outcome_coverage_ledger.csv",
        "htr010b7_evidence_deficit_attribution.csv",
        "htr010b7_setup_fragmentation_diagnostics.csv",
        "htr010b7_raw_adjusted_evidence_comparison.csv",
        "htr010b7_evidence_provenance_audit.csv",
        "htr010b7_evidence_boundary_probe_ledger.csv",
        "htr010b7_executive_report.md",
    }
)

_CANDIDATE_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "rank",
    "final_signal",
    "setup_type",
    "setup_stage",
    "evidence_strength",
    "evidence_sample_count",
    "sample_requirement_applies",
    "required_sample_count",
    "sample_deficit",
    "sample_coverage_ratio",
    "sample_rule_satisfied",
    "posterior_probability",
    "expectancy",
    "posterior_available",
    "expectancy_available",
    "insufficient_evidence_gate_failed",
    "b6_sample_constraint_present",
    "b6_sample_gap_to_clear",
    "forward_outcome_status",
    "forward_entered",
    "forward_completed",
    "forward_won",
    "realized_return_pct",
    "realized_r",
    "holding_period_days",
    "outcome_exit_reason",
    "primary_observed_cause",
    "observed_cause_codes",
    "diagnostic_suspicion_codes",
    "evidence_provenance_complete",
    "input_fingerprint",
)
_COHORT_FIELDS = (
    "price_view",
    "setup_type",
    "candidate_count",
    "unique_symbol_count",
    "observed_session_count",
    "known_sample_count",
    "unknown_sample_count",
    "minimum_sample_count",
    "median_sample_count",
    "maximum_sample_count",
    "average_sample_count",
    "candidates_meeting_requirement",
    "candidates_below_requirement",
    "total_sample_deficit",
    "forward_completed_count",
    "forward_pending_count",
    "forward_not_entered_count",
    "forward_completion_rate",
    "setup_rarity_suspected",
    "matching_fragmentation_suspected",
    "diagnostic_scope",
)
_OUTCOME_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "setup_type",
    "forward_outcome_status",
    "entered",
    "completed",
    "won",
    "realized_return_pct",
    "realized_r",
    "holding_period_days",
    "exit_reason",
    "evidence_note",
    "end_of_window_censored",
    "entry_non_occurrence",
)
_ATTRIBUTION_FIELDS = (
    "price_view",
    "cause_scope",
    "cause_code",
    "candidate_count",
    "candidate_percent",
    "setup_type_count",
    "total_sample_deficit",
    "evidence_note",
)
_FRAGMENTATION_FIELDS = (
    "price_view",
    "setup_type",
    "candidate_count",
    "median_sample_count",
    "maximum_sample_count",
    "candidates_meeting_requirement",
    "setup_occurrence_capacity_60",
    "setup_rarity_suspected",
    "matching_fragmentation_suspected",
    "causal_claim_permitted",
    "diagnostic_explanation",
)
_COMPARISON_FIELDS = (
    "observed_on",
    "symbol",
    "raw_present",
    "adjusted_present",
    "raw_setup_type",
    "adjusted_setup_type",
    "setup_type_changed",
    "raw_sample_count",
    "adjusted_sample_count",
    "sample_count_changed",
    "raw_sample_deficit",
    "adjusted_sample_deficit",
    "sample_deficit_delta",
    "raw_outcome_status",
    "adjusted_outcome_status",
    "outcome_status_changed",
    "raw_observed_causes",
    "adjusted_observed_causes",
    "cause_set_changed",
    "raw_input_fingerprint",
    "adjusted_input_fingerprint",
    "input_changed",
    "explained_evidence_difference",
    "unexplained_evidence_divergence",
)
_PROVENANCE_FIELDS = (
    "check_id",
    "scope",
    "expected",
    "observed",
    "passed",
    "severity",
    "explanation",
)
_PROBE_FIELDS = (
    "probe_id",
    "probe_scope",
    "observed_sample_count",
    "evidence_strength",
    "cohort_candidate_count",
    "expected_sample_deficit",
    "observed_sample_deficit",
    "expected_observed_cause",
    "observed_observed_cause",
    "expected_suspicion",
    "observed_suspicion",
    "expectation_matched",
    "deterministic",
)


@dataclass(frozen=True, slots=True)
class EvidenceSeed:
    """Reconciled signed candidate plus rerun setup and outcome evidence."""

    key: CandidateKey
    candidate: dict[str, str]
    ranking: CandidateRankingRecord
    outcome: CandidateOutcomeRecord
    insufficient_gate_failed: bool
    b6_sample_constraint_present: bool
    b6_sample_gap: Decimal | None


@dataclass(frozen=True, slots=True)
class GovernedSetupMatchedEvidenceResult:
    """Signed B7 certificate plus deterministic evidence artifacts."""

    report: dict[str, Any]
    candidate_rows: tuple[dict[str, object], ...]
    cohort_rows: tuple[dict[str, object], ...]
    outcome_rows: tuple[dict[str, object], ...]
    attribution_rows: tuple[dict[str, object], ...]
    fragmentation_rows: tuple[dict[str, object], ...]
    comparison_rows: tuple[dict[str, object], ...]
    provenance_rows: tuple[dict[str, object], ...]
    probe_rows: tuple[dict[str, object], ...]
    paths: tuple[Path, ...]


class GovernedSetupMatchedEvidenceEngine:
    """Certify setup-matched evidence sufficiency under frozen policy."""

    def run(
        self,
        *,
        source: LegacyMarketDataStore,
        b5_certificate: Path,
        b6_certificate: Path,
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
    ) -> GovernedSetupMatchedEvidenceResult:
        total_steps = 9
        root = Path(project_root)
        _progress(progress, 1, total_steps, "Validating signed B5 and B6 handoff")
        b5 = validate_governed_approval_gate_forensics_certificate(
            b5_certificate,
            require_ready=True,
            project_root=root,
        )
        b6 = validate_governed_approval_constraint_frontier_certificate(
            b6_certificate,
            require_ready=True,
            project_root=root,
        )
        _validate_handoff(b5, b6, b5_certificate=b5_certificate)

        b5_candidate_path = b5_certificate.parent / _B5_CANDIDATE_ARTIFACT
        b5_gate_path = b5_certificate.parent / _B5_GATE_ARTIFACT
        b6_frontier_path = b6_certificate.parent / _B6_FRONTIER_ARTIFACT
        b6_margin_path = b6_certificate.parent / _B6_MARGIN_ARTIFACT
        input_paths = {
            "identity_artifact": identity_artifact,
            "corporate_action_artifact": corporate_action_artifact,
            "final_closure_report": final_closure_report,
            "admission_contract": admission_contract,
            "identity_admission": identity_admission,
            "raw_universe": raw_universe,
            "adjusted_universe": adjusted_universe,
        }
        input_hashes = _validate_explicit_inputs(b5, input_paths)
        immutable_paths = {
            "b5_certificate": b5_certificate,
            "b6_certificate": b6_certificate,
            "b5_candidate_ledger": b5_candidate_path,
            "b5_gate_ledger": b5_gate_path,
            "b6_frontier_ledger": b6_frontier_path,
            "b6_margin_ledger": b6_margin_path,
            **input_paths,
        }
        immutable_hashes = _hash_paths(immutable_paths)

        _progress(progress, 2, total_steps, "Loading signed evidence ledgers")
        b5_candidates = _csv_rows(b5_candidate_path)
        b5_gates = _csv_rows(b5_gate_path)
        b6_frontier = _csv_rows(b6_frontier_path)
        b6_margins = _csv_rows(b6_margin_path)

        replay_start = _date_value(b5.get("replay_start"), "B5 replay start")
        replay_end = _date_value(b5.get("replay_end"), "B5 replay end")
        _progress(
            progress,
            3,
            total_steps,
            "Rebuilding governed RAW and ADJUSTED stores",
        )
        with TemporaryDirectory(prefix="htr010b7-store-contracts-") as temporary:
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
                provenance_rows = list(
                    _pair_provenance_checks(
                        pair,
                        b5=b5,
                        input_hashes=input_hashes,
                    )
                )
                _progress(progress, 4, total_steps, "Recovering RAW setup identities")
                raw_audit = _run_audit(
                    pair.raw,
                    replay_start=replay_start,
                    replay_end=replay_end,
                    progress=progress,
                    progress_step=4,
                    total_steps=total_steps,
                    label="RAW",
                )
                _progress(
                    progress,
                    5,
                    total_steps,
                    "Recovering ADJUSTED setup identities",
                )
                adjusted_audit = _run_audit(
                    pair.adjusted,
                    replay_start=replay_start,
                    replay_end=replay_end,
                    progress=progress,
                    progress_step=5,
                    total_steps=total_steps,
                    label="ADJUSTED",
                )
                provenance_rows.extend(_post_audit_attestation_checks(pair, b5=b5))
            finally:
                pair.close()

        _progress(progress, 6, total_steps, "Reconciling setup and outcome evidence")
        seeds, reconciliation_defects, reconciliation_checks = _reconcile_evidence(
            b5_candidates,
            b5_gates,
            b6_frontier,
            b6_margins,
            raw_audit=raw_audit,
            adjusted_audit=adjusted_audit,
            b5=b5,
            b6=b6,
        )
        provenance_rows.extend(reconciliation_checks)

        _progress(
            progress,
            7,
            total_steps,
            "Measuring evidence sufficiency and coverage",
        )
        candidate_rows, cohort_rows, outcome_rows = _build_evidence_rows(seeds)
        attribution_rows = _deficit_attribution(candidate_rows)
        fragmentation_rows = _fragmentation_diagnostics(cohort_rows)
        comparison_rows, unexplained_divergences = _arm_comparison(candidate_rows)
        probe_rows, probe_summary, probe_defects = _evidence_probes()

        setup_identity_defects = tuple(
            sorted(
                {
                    item
                    for item in reconciliation_defects
                    if item.startswith("SETUP_IDENTITY_")
                }
            )
        )
        implementation_defects = tuple(
            sorted(
                {
                    item
                    for item in (*reconciliation_defects, *probe_defects)
                    if item not in setup_identity_defects
                }
            )
        )
        provenance_failures = tuple(
            row
            for row in provenance_rows
            if not bool(row["passed"]) and row["severity"] == "ERROR"
        )
        population_nonempty = bool(candidate_rows) and all(
            any(row["price_view"] == view for row in candidate_rows)
            for view in ("RAW", "ADJUSTED")
        )
        setup_identity_complete = not setup_identity_defects and all(
            str(row["setup_type"]).strip() not in {"", "UNKNOWN", "UNAVAILABLE"}
            for row in candidate_rows
        )
        evidence_provenance_complete = (
            not provenance_failures
            and all(bool(row["evidence_provenance_complete"]) for row in candidate_rows)
            and cast(int, probe_summary["failed_probe_count"]) == 0
        )
        readiness, blockers = _readiness(
            population_nonempty=population_nonempty,
            setup_identity_complete=setup_identity_complete,
            evidence_provenance_complete=evidence_provenance_complete,
            implementation_defects=implementation_defects,
            unexplained_divergences=unexplained_divergences,
        )
        enabled = readiness == B7_READY
        raw_summary = _arm_summary(candidate_rows, price_view="RAW")
        adjusted_summary = _arm_summary(candidate_rows, price_view="ADJUSTED")
        expected_policy_hashes = _mapping_copy(
            b5,
            "institutional_policy_source_sha256s",
        )
        expected_pipeline_hashes = _mapping_copy(
            b5,
            "frozen_pipeline_component_sha256s",
        )
        if _b5_policy_source_hashes(root) != expected_policy_hashes:
            raise ValueError("institutional policy source changed during B7 analysis")
        if _b5_pipeline_component_hashes(root) != expected_pipeline_hashes:
            raise ValueError("frozen pipeline component changed during B7 analysis")
        _validate_paths_unchanged(immutable_paths, immutable_hashes)

        report: dict[str, Any] = {
            "contract_version": HTR010B7_CONTRACT_VERSION,
            "b5_contract_version": b5["contract_version"],
            "b5_report_sha256": b5["report_sha256"],
            "b5_certificate_file_sha256": _file_sha256(b5_certificate),
            "b6_contract_version": b6["contract_version"],
            "b6_report_sha256": b6["report_sha256"],
            "b6_certificate_file_sha256": _file_sha256(b6_certificate),
            "b5_candidate_ledger_sha256": _file_sha256(b5_candidate_path),
            "b5_gate_ledger_sha256": _file_sha256(b5_gate_path),
            "b6_frontier_ledger_sha256": _file_sha256(b6_frontier_path),
            "b6_margin_ledger_sha256": _file_sha256(b6_margin_path),
            "input_artifact_file_sha256s": input_hashes,
            "replay_start": replay_start,
            "replay_end": replay_end,
            "session_count": b5["session_count"],
            "required_matched_sample_count": _REQUIRED_SAMPLE_COUNT,
            "minimum_approval_posterior": _MIN_APPROVAL_POSTERIOR,
            "minimum_approval_expectancy": _MIN_APPROVAL_EXPECTANCY,
            "governed_store_lineage": {
                "identity_session_sha256": _pair_check_observed(
                    provenance_rows,
                    "PAIR_IDENTITY_SESSION_SHA256",
                ),
                "final_closure_report_sha256": _pair_check_observed(
                    provenance_rows,
                    "PAIR_FINAL_CLOSURE_SHA256",
                ),
                "admission_contract_sha256": _pair_check_observed(
                    provenance_rows,
                    "PAIR_ADMISSION_SHA256",
                ),
                "b5_path_sensitive_input_manifest_sha256": _nested_mapping(
                    b5,
                    "governed_store_lineage",
                )["governed_input_manifest_sha256"],
                "rebuilt_path_sensitive_input_manifest_sha256": _pair_check_observed(
                    provenance_rows,
                    "PAIR_INPUT_MANIFEST_SHA256",
                ),
                "path_neutral_input_artifact_sha256": _digest_mapping(input_hashes),
                "path_representation_neutral_lineage_validated": True,
            },
            "institutional_policy_source_sha256s": _mapping_copy(
                b5,
                "institutional_policy_source_sha256s",
            ),
            "frozen_pipeline_component_sha256s": _mapping_copy(
                b5,
                "frozen_pipeline_component_sha256s",
            ),
            "raw_evidence_summary": raw_summary,
            "adjusted_evidence_summary": adjusted_summary,
            "setup_cohort_summary": _cohort_summary(cohort_rows),
            "outcome_coverage_summary": _outcome_coverage_summary(outcome_rows),
            "deficit_attribution_summary": _attribution_summary(attribution_rows),
            "probe_summary": probe_summary,
            "setup_matched_population_nonempty": population_nonempty,
            "setup_identity_complete": setup_identity_complete,
            "evidence_provenance_complete": evidence_provenance_complete,
            "setup_identity_defects": list(setup_identity_defects),
            "setup_identity_defect_count": len(setup_identity_defects),
            "implementation_defects": list(implementation_defects),
            "implementation_defect_count": len(implementation_defects),
            "unexplained_evidence_divergence_count": unexplained_divergences,
            "readiness_blockers": list(blockers),
            "readiness_decision": readiness,
            "governed_setup_matched_evidence_research_enabled": enabled,
            "governed_approval_constraint_research_enabled": True,
            "governed_approval_gate_research_enabled": True,
            "governed_adjusted_trade_research_enabled": False,
            "research_scope": RESEARCH_SCOPE,
            "threshold_change_permitted": False,
            "synthetic_outcomes_permitted": False,
            "outcome_backfill_mutation_enabled": False,
            "diagnostic_suspicion_may_be_claimed_as_causality": False,
            "economic_superiority_claimed": False,
            "live_scoring_enabled": False,
            "recommendation_influence": False,
            "portfolio_policy_influence": False,
            "execution_influence": False,
            "learning_mutation_enabled": False,
            "active_replay_integration": False,
            "production_influence": False,
        }

        _progress(progress, 8, total_steps, "Exporting signed HTR-010B7 artifacts")
        paths = export_governed_setup_matched_evidence(
            report=report,
            candidate_rows=candidate_rows,
            cohort_rows=cohort_rows,
            outcome_rows=outcome_rows,
            attribution_rows=attribution_rows,
            fragmentation_rows=fragmentation_rows,
            comparison_rows=comparison_rows,
            provenance_rows=tuple(provenance_rows),
            probe_rows=probe_rows,
            output=output,
        )
        _progress(progress, 9, total_steps, "HTR-010B7 evidence certificate complete")
        return GovernedSetupMatchedEvidenceResult(
            report=report,
            candidate_rows=candidate_rows,
            cohort_rows=cohort_rows,
            outcome_rows=outcome_rows,
            attribution_rows=attribution_rows,
            fragmentation_rows=fragmentation_rows,
            comparison_rows=comparison_rows,
            provenance_rows=tuple(provenance_rows),
            probe_rows=probe_rows,
            paths=paths,
        )


def _validate_handoff(
    b5: Mapping[str, object],
    b6: Mapping[str, object],
    *,
    b5_certificate: Path,
) -> None:
    if b5.get("contract_version") != HTR010B5_CONTRACT_VERSION:
        raise ValueError("B7 requires the HTR-010B5 approval-gate contract")
    if b5.get("readiness_decision") != B5_READY:
        raise ValueError("B7 requires a ready HTR-010B5 certificate")
    if b6.get("contract_version") != HTR010B6_CONTRACT_VERSION:
        raise ValueError("B7 requires the HTR-010B6 constraint-frontier contract")
    if b6.get("readiness_decision") != B6_READY:
        raise ValueError("B7 requires a ready HTR-010B6 certificate")
    if b6.get("b5_report_sha256") != b5.get("report_sha256"):
        raise ValueError("HTR-010B6 does not descend from the supplied B5 report")
    if b6.get("b5_certificate_file_sha256") != _file_sha256(b5_certificate):
        raise ValueError("HTR-010B6 does not bind the supplied B5 certificate file")
    for payload, label in ((b5, "B5"), (b6, "B6")):
        if payload.get("production_influence") is not False:
            raise ValueError(f"{label} unexpectedly permits production influence")
        if payload.get("governed_adjusted_trade_research_enabled") is not False:
            raise ValueError(f"{label} unexpectedly permits governed trade research")


def _validate_explicit_inputs(
    b5: Mapping[str, object],
    paths: Mapping[str, Path],
) -> dict[str, str]:
    expected = _mapping_copy(b5, "input_artifact_file_sha256s")
    observed: dict[str, str] = {}
    for key, path in sorted(paths.items()):
        digest = _file_sha256(path)
        observed[key] = digest
        if expected.get(key) != digest:
            raise ValueError(f"HTR-010B7 input artifact differs from B5: {key}")
    return observed


def _pair_provenance_checks(
    pair: GovernedBenchmarkStorePair,
    *,
    b5: Mapping[str, object],
    input_hashes: Mapping[str, str],
) -> tuple[dict[str, object], ...]:
    lineage = _nested_mapping(b5, "governed_store_lineage")
    checks = [
        _provenance_check(
            "PAIR_IDENTITY_SESSION_SHA256",
            "GOVERNED_STORE",
            lineage.get("identity_session_sha256"),
            pair.identity_session_sha256,
            "Rebuilt identity-session population matches B5.",
        ),
        _provenance_check(
            "PAIR_FINAL_CLOSURE_SHA256",
            "GOVERNED_STORE",
            lineage.get("final_closure_report_sha256"),
            pair.final_closure_report_sha256,
            "Rebuilt store uses the B5 final closure report.",
        ),
        _provenance_check(
            "PAIR_ADMISSION_SHA256",
            "GOVERNED_STORE",
            lineage.get("admission_contract_sha256"),
            pair.admission_contract_sha256,
            "Rebuilt store uses the B5 admission contract.",
        ),
        _provenance_check(
            "PAIR_INPUT_MANIFEST_SHA256",
            "GOVERNED_STORE_PATH_REPRESENTATION",
            lineage.get("governed_input_manifest_sha256"),
            pair.governed_input_manifest_sha256,
            (
                "The legacy manifest is path-sensitive. A mismatch is informational "
                "when all bound input file hashes and path-neutral lineage checks pass."
            ),
            severity="INFO",
            force_pass=True,
        ),
        _provenance_check(
            "PAIR_FRESH_ATTESTATIONS",
            "GOVERNED_STORE",
            (),
            pair.canonical_attestation_sha256s,
            "Fresh rebuilt stores contain no unexpected consumer attestations.",
        ),
    ]
    for key, digest in sorted(input_hashes.items()):
        checks.append(
            _provenance_check(
                f"INPUT_FILE::{key}",
                "INPUT_ARTIFACT",
                digest,
                digest,
                "Explicit input file hash matches the B5-bound artifact.",
            )
        )
    return tuple(checks)


def _post_audit_attestation_checks(
    pair: GovernedBenchmarkStorePair,
    *,
    b5: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    lineage = _nested_mapping(b5, "governed_store_lineage")
    allowed = tuple(lineage.get("canonical_attestation_sha256s", ()))
    expected_raw = tuple(lineage.get("raw_forensic_canonical_attestation_sha256s", ()))
    expected_adjusted = tuple(
        lineage.get("adjusted_forensic_canonical_attestation_sha256s", ())
    )
    observed_raw = pair.raw.canonical_attestation_sha256s
    observed_adjusted = pair.adjusted.canonical_attestation_sha256s
    return (
        _subset_provenance_check(
            "RAW_FORENSIC_ATTESTATIONS_PRESENT",
            "RERUN_ATTESTATION",
            expected_raw,
            observed_raw,
            "B5 RAW forensic attestations are present in the fuller B7 audit.",
        ),
        _subset_provenance_check(
            "ADJUSTED_FORENSIC_ATTESTATIONS_PRESENT",
            "RERUN_ATTESTATION",
            expected_adjusted,
            observed_adjusted,
            "B5 ADJUSTED forensic attestations are present in the fuller B7 audit.",
        ),
        _subset_provenance_check(
            "RAW_ATTESTATIONS_WITHIN_SIGNED_LINEAGE",
            "RERUN_ATTESTATION",
            observed_raw,
            allowed,
            "All RAW B7 consumer attestations remain inside signed B2 lineage.",
        ),
        _subset_provenance_check(
            "ADJUSTED_ATTESTATIONS_WITHIN_SIGNED_LINEAGE",
            "RERUN_ATTESTATION",
            observed_adjusted,
            allowed,
            "All ADJUSTED B7 consumer attestations remain inside signed B2 lineage.",
        ),
    )


def _run_audit(
    store: GovernedBenchmarkStore,
    *,
    replay_start: date,
    replay_end: date,
    progress: ProgressCallback | None,
    progress_step: int,
    total_steps: int,
    label: str,
) -> CanonicalUniverseAuditReport:
    generated_at = datetime.combine(replay_end, time.min, tzinfo=UTC)

    def audit_progress(current: int, total: int, observed_on: date) -> None:
        if current == 1 or current == total or current % 25 == 0:
            _progress(
                progress,
                progress_step,
                total_steps,
                (
                    f"Recovering {label} setup identities "
                    f"({current}/{total} through {observed_on.isoformat()})"
                ),
            )

    return CanonicalUniverseAuditEngine().run(
        store=store,
        request=AuditRunRequest(
            start=replay_start,
            end=replay_end,
            generated_at=generated_at,
        ),
        progress=audit_progress,
    )


def _reconcile_evidence(
    b5_candidate_rows: tuple[dict[str, str], ...],
    b5_gate_rows: tuple[dict[str, str], ...],
    b6_frontier_rows: tuple[dict[str, str], ...],
    b6_margin_rows: tuple[dict[str, str], ...],
    *,
    raw_audit: CanonicalUniverseAuditReport,
    adjusted_audit: CanonicalUniverseAuditReport,
    b5: Mapping[str, object],
    b6: Mapping[str, object],
) -> tuple[
    tuple[EvidenceSeed, ...],
    tuple[str, ...],
    tuple[dict[str, object], ...],
]:
    defects: list[str] = []
    checks: list[dict[str, object]] = []
    candidates = _indexed_b5_candidates(b5_candidate_rows, defects)
    gates = _indexed_failed_gates(b5_gate_rows, defects)
    frontiers = _indexed_b6_frontier(b6_frontier_rows, defects)
    sample_margins = _indexed_b6_sample_margins(b6_margin_rows, defects)

    rankings: dict[CandidateKey, CandidateRankingRecord] = {}
    outcomes: dict[CandidateKey, CandidateOutcomeRecord] = {}
    for price_view, audit in (("RAW", raw_audit), ("ADJUSTED", adjusted_audit)):
        for audit_ranking in audit.rankings:
            key = price_view, audit_ranking.observed_on, audit_ranking.symbol
            if key in rankings:
                defects.append(_key_defect("DUPLICATE_RERUN_RANKING", key))
            rankings[key] = audit_ranking
        for audit_outcome in audit.outcomes:
            key = price_view, audit_outcome.observed_on, audit_outcome.symbol
            if key in outcomes:
                defects.append(_key_defect("DUPLICATE_RERUN_OUTCOME", key))
            outcomes[key] = audit_outcome

    approvable_keys = {
        key
        for key, row in candidates.items()
        if _boolean(row.get("approvable_signal"), "B5 approvable signal")
    }
    frontier_keys = set(frontiers)
    if frontier_keys != approvable_keys:
        for key in sorted(approvable_keys.difference(frontier_keys)):
            defects.append(_key_defect("B6_FRONTIER_MISSING_CANDIDATE", key))
        for key in sorted(frontier_keys.difference(approvable_keys)):
            defects.append(_key_defect("B6_FRONTIER_EXTRA_CANDIDATE", key))

    seeds: list[EvidenceSeed] = []
    setup_identity_count = 0
    ranking_parity_count = 0
    outcome_count = 0
    for key in sorted(approvable_keys):
        candidate = candidates[key]
        ranking = rankings.get(key)
        if ranking is None:
            defects.append(_key_defect("SETUP_IDENTITY_RANKING_MISSING", key))
            continue
        setup_type = ranking.setup_type.strip().upper()
        if not setup_type or setup_type in {"UNKNOWN", "UNAVAILABLE"}:
            defects.append(_key_defect("SETUP_IDENTITY_UNAVAILABLE", key))
        else:
            setup_identity_count += 1
        parity = (
            ranking.rank == _integer(candidate.get("rank"), "B5 candidate rank")
            and ranking.final_signal
            == str(candidate.get("final_signal") or "").strip().upper()
            and ranking.score
            == _decimal(candidate.get("recommendation_score"), "B5 score")
            and ranking.setup_stage
            == str(candidate.get("setup_stage") or "").strip().upper()
        )
        if not parity:
            defects.append(_key_defect("SETUP_IDENTITY_RANKING_PARITY_MISMATCH", key))
        else:
            ranking_parity_count += 1
        outcome = outcomes.get(key)
        if outcome is None:
            defects.append(_key_defect("OUTCOME_COVERAGE_ROW_MISSING", key))
            continue
        outcome_count += 1
        failed = "INSUFFICIENT_EVIDENCE" in gates.get(key, frozenset())
        margin = sample_margins.get(key)
        sample_count = _optional_int(candidate.get("evidence_sample_count"))
        strength = str(candidate.get("evidence_strength") or "").strip().upper()
        requirement_applies = strength != "STRONG"
        deficit = _sample_deficit(sample_count, strength)
        if failed != (requirement_applies and deficit > 0):
            defects.append(_key_defect("B5_EVIDENCE_GATE_RULE_MISMATCH", key))
        if margin is not None:
            expected_gap = Decimal(deficit)
            if margin != expected_gap:
                defects.append(_key_defect("B6_SAMPLE_GAP_MISMATCH", key))
        elif sample_count is not None and requirement_applies and deficit > 0:
            defects.append(_key_defect("B6_SAMPLE_MARGIN_MISSING", key))
        seeds.append(
            EvidenceSeed(
                key=key,
                candidate=candidate,
                ranking=ranking,
                outcome=outcome,
                insufficient_gate_failed=failed,
                b6_sample_constraint_present=margin is not None,
                b6_sample_gap=margin,
            )
        )

    expected_raw = _integer(
        _nested_mapping(b5, "raw_forensic_summary").get("approvable_candidate_count"),
        "B5 RAW approvable count",
    )
    expected_adjusted = _integer(
        _nested_mapping(b5, "adjusted_forensic_summary").get(
            "approvable_candidate_count"
        ),
        "B5 ADJUSTED approvable count",
    )
    observed_counts = Counter(seed.key[0] for seed in seeds)
    for view, expected in (("RAW", expected_raw), ("ADJUSTED", expected_adjusted)):
        checks.append(
            _provenance_check(
                f"{view}_APPROVABLE_POPULATION",
                "CANDIDATE_RECONCILIATION",
                expected,
                observed_counts[view],
                "B7 reconciles every B5 approvable candidate.",
            )
        )
    checks.extend(
        (
            _provenance_check(
                "SETUP_IDENTITY_COVERAGE",
                "SETUP_IDENTITY",
                len(approvable_keys),
                setup_identity_count,
                "Every approvable candidate has a governed setup type.",
            ),
            _provenance_check(
                "RANKING_PARITY_COVERAGE",
                "SETUP_IDENTITY",
                len(approvable_keys),
                ranking_parity_count,
                "Rerun ranking identity and score fields match B5.",
            ),
            _provenance_check(
                "OUTCOME_ROW_COVERAGE",
                "OUTCOME_COVERAGE",
                len(approvable_keys),
                outcome_count,
                "Every approvable candidate has one forward-outcome status row.",
            ),
            _provenance_check(
                "B6_FRONTIER_POPULATION",
                "B6_RECONCILIATION",
                len(approvable_keys),
                len(frontier_keys),
                "B6 frontier population equals B5 approvable population.",
            ),
            _provenance_check(
                "B6_CERTIFIED_POPULATION_NONEMPTY",
                "B6_RECONCILIATION",
                True,
                b6.get("constraint_population_nonempty"),
                "B6 certified a nonempty constraint population.",
            ),
        )
    )
    return tuple(seeds), tuple(sorted(set(defects))), tuple(checks)


def _indexed_b5_candidates(
    rows: Sequence[dict[str, str]],
    defects: list[str],
) -> dict[CandidateKey, dict[str, str]]:
    result: dict[CandidateKey, dict[str, str]] = {}
    for row in rows:
        key = _candidate_key(row, "B5 candidate")
        if key in result:
            defects.append(_key_defect("DUPLICATE_B5_CANDIDATE", key))
        result[key] = row
    return result


def _indexed_failed_gates(
    rows: Sequence[dict[str, str]],
    defects: list[str],
) -> dict[CandidateKey, frozenset[str]]:
    result: dict[CandidateKey, set[str]] = defaultdict(set)
    seen: set[tuple[CandidateKey, str, str]] = set()
    for row in rows:
        key = _candidate_key(row, "B5 gate")
        stage = str(row.get("stage") or "")
        gate_code = str(row.get("gate_code") or "")
        event_key = key, stage, gate_code
        if event_key in seen:
            defects.append(_key_defect("DUPLICATE_B5_GATE_EVENT", key, gate_code))
        seen.add(event_key)
        if (
            _boolean(row.get("stage_reached"), "B5 stage reached")
            and str(row.get("outcome") or "").upper() == "FAIL"
        ):
            result[key].add(gate_code)
    return {key: frozenset(values) for key, values in result.items()}


def _indexed_b6_frontier(
    rows: Sequence[dict[str, str]],
    defects: list[str],
) -> dict[CandidateKey, dict[str, str]]:
    result: dict[CandidateKey, dict[str, str]] = {}
    for row in rows:
        key = _candidate_key(row, "B6 frontier")
        if key in result:
            defects.append(_key_defect("DUPLICATE_B6_FRONTIER", key))
        result[key] = row
    return result


def _indexed_b6_sample_margins(
    rows: Sequence[dict[str, str]],
    defects: list[str],
) -> dict[CandidateKey, Decimal]:
    result: dict[CandidateKey, Decimal] = {}
    for row in rows:
        if str(row.get("constraint_id") or "") != _SAMPLE_CONSTRAINT_ID:
            continue
        key = _candidate_key(row, "B6 sample margin")
        gap = _decimal(row.get("gap_to_clear"), "B6 sample gap")
        if key in result:
            defects.append(_key_defect("DUPLICATE_B6_SAMPLE_MARGIN", key))
        result[key] = gap
    return result


def _build_evidence_rows(
    seeds: Sequence[EvidenceSeed],
) -> tuple[
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
]:
    cohort_sizes = Counter((seed.key[0], _setup_type(seed)) for seed in seeds)
    candidates: list[dict[str, object]] = []
    outcomes: list[dict[str, object]] = []
    for seed in sorted(seeds, key=lambda item: item.key):
        view, observed_on, symbol = seed.key
        candidate = seed.candidate
        setup_type = _setup_type(seed)
        setup_size = cohort_sizes[(view, setup_type)]
        sample_count = _optional_int(candidate.get("evidence_sample_count"))
        strength = str(candidate.get("evidence_strength") or "").strip().upper()
        requirement_applies = strength != "STRONG"
        deficit = _sample_deficit(sample_count, strength)
        coverage = _sample_coverage_ratio(sample_count, strength)
        posterior = _optional_decimal(candidate.get("posterior_probability"))
        expectancy = _optional_decimal(candidate.get("expectancy"))
        outcome_status = _outcome_status(seed.outcome)
        observed_causes = _observed_causes(
            sample_count=sample_count,
            evidence_strength=strength,
            posterior=posterior,
            expectancy=expectancy,
            outcome=seed.outcome,
        )
        suspicions = _diagnostic_suspicions(
            sample_count=sample_count,
            evidence_strength=strength,
            cohort_candidate_count=setup_size,
        )
        provenance_complete = (
            bool(setup_type)
            and seed.outcome is not None
            and seed.insufficient_gate_failed == (requirement_applies and deficit > 0)
            and (
                seed.b6_sample_constraint_present
                if sample_count is not None and requirement_applies and deficit > 0
                else True
            )
        )
        row: dict[str, object] = {
            "price_view": view,
            "observed_on": observed_on,
            "symbol": symbol,
            "rank": seed.ranking.rank,
            "final_signal": seed.ranking.final_signal,
            "setup_type": setup_type,
            "setup_stage": seed.ranking.setup_stage,
            "evidence_strength": strength or "UNAVAILABLE",
            "evidence_sample_count": sample_count,
            "sample_requirement_applies": requirement_applies,
            "required_sample_count": (
                _REQUIRED_SAMPLE_COUNT if requirement_applies else 0
            ),
            "sample_deficit": deficit,
            "sample_coverage_ratio": coverage,
            "sample_rule_satisfied": deficit == 0,
            "posterior_probability": posterior,
            "expectancy": expectancy,
            "posterior_available": posterior is not None,
            "expectancy_available": expectancy is not None,
            "insufficient_evidence_gate_failed": seed.insufficient_gate_failed,
            "b6_sample_constraint_present": seed.b6_sample_constraint_present,
            "b6_sample_gap_to_clear": seed.b6_sample_gap,
            "forward_outcome_status": outcome_status,
            "forward_entered": seed.outcome.entered,
            "forward_completed": seed.outcome.completed,
            "forward_won": seed.outcome.won,
            "realized_return_pct": seed.outcome.realized_return_pct,
            "realized_r": seed.outcome.realized_r,
            "holding_period_days": seed.outcome.holding_period_days,
            "outcome_exit_reason": seed.outcome.exit_reason,
            "primary_observed_cause": (
                observed_causes[0] if observed_causes else "NONE"
            ),
            "observed_cause_codes": observed_causes,
            "diagnostic_suspicion_codes": suspicions,
            "evidence_provenance_complete": provenance_complete,
            "input_fingerprint": str(candidate.get("input_fingerprint") or ""),
        }
        candidates.append(row)
        outcomes.append(
            {
                "price_view": view,
                "observed_on": observed_on,
                "symbol": symbol,
                "setup_type": setup_type,
                "forward_outcome_status": outcome_status,
                "entered": seed.outcome.entered,
                "completed": seed.outcome.completed,
                "won": seed.outcome.won,
                "realized_return_pct": seed.outcome.realized_return_pct,
                "realized_r": seed.outcome.realized_r,
                "holding_period_days": seed.outcome.holding_period_days,
                "exit_reason": seed.outcome.exit_reason,
                "evidence_note": seed.outcome.evidence_note,
                "end_of_window_censored": (outcome_status == "PENDING_END_OF_DATA"),
                "entry_non_occurrence": outcome_status == "NOT_ENTERED",
            }
        )
    cohort_rows = _setup_cohort_rows(candidates)
    return (
        tuple(candidates),
        cohort_rows,
        tuple(sorted(outcomes, key=_candidate_sort_key)),
    )


def _setup_cohort_rows(
    candidate_rows: Sequence[dict[str, object]],
) -> tuple[dict[str, object], ...]:
    groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in candidate_rows:
        groups[(str(row["price_view"]), str(row["setup_type"]))].append(row)
    result: list[dict[str, object]] = []
    for (price_view, setup_type), rows in sorted(groups.items()):
        known_samples = tuple(
            cast(int, row["evidence_sample_count"])
            for row in rows
            if row["evidence_sample_count"] is not None
        )
        completed = sum(bool(row["forward_completed"]) for row in rows)
        pending = sum(
            row["forward_outcome_status"] == "PENDING_END_OF_DATA" for row in rows
        )
        not_entered = sum(
            row["forward_outcome_status"] == "NOT_ENTERED" for row in rows
        )
        meeting = sum(bool(row["sample_rule_satisfied"]) for row in rows)
        candidate_count = len(rows)
        rarity = candidate_count < _REQUIRED_SAMPLE_COUNT
        fragmentation = candidate_count >= _REQUIRED_SAMPLE_COUNT and meeting == 0
        completion_rate = (
            Decimal("0")
            if candidate_count == 0
            else (
                Decimal(completed) / Decimal(candidate_count) * Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
        result.append(
            {
                "price_view": price_view,
                "setup_type": setup_type,
                "candidate_count": candidate_count,
                "unique_symbol_count": len({str(row["symbol"]) for row in rows}),
                "observed_session_count": len(
                    {str(row["observed_on"]) for row in rows}
                ),
                "known_sample_count": len(known_samples),
                "unknown_sample_count": candidate_count - len(known_samples),
                "minimum_sample_count": min(known_samples, default=None),
                "median_sample_count": _median_int(known_samples),
                "maximum_sample_count": max(known_samples, default=None),
                "average_sample_count": _average_int(known_samples),
                "candidates_meeting_requirement": meeting,
                "candidates_below_requirement": candidate_count - meeting,
                "total_sample_deficit": sum(
                    cast(int, row["sample_deficit"]) for row in rows
                ),
                "forward_completed_count": completed,
                "forward_pending_count": pending,
                "forward_not_entered_count": not_entered,
                "forward_completion_rate": completion_rate,
                "setup_rarity_suspected": rarity,
                "matching_fragmentation_suspected": fragmentation,
                "diagnostic_scope": "DIAGNOSTIC_SUSPICION_NOT_CAUSAL",
            }
        )
    return tuple(result)


def _deficit_attribution(
    candidate_rows: Sequence[dict[str, object]],
) -> tuple[dict[str, object], ...]:
    groups: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    notes = {
        "SAMPLE_COUNT_UNAVAILABLE": (
            "The signed candidate metadata did not expose a numeric matched-outcome "
            "sample count."
        ),
        "ZERO_MATCHED_OUTCOMES": (
            "The signed candidate reported zero completed matched outcomes."
        ),
        "MATCHED_OUTCOME_DEFICIT": (
            "The numeric completed matched-outcome count is below the frozen "
            f"{_REQUIRED_SAMPLE_COUNT}-sample requirement."
        ),
        "EVIDENCE_STRENGTH_UNAVAILABLE": (
            "The signed adaptive evidence-strength label is unavailable."
        ),
        "POSTERIOR_UNAVAILABLE": (
            "Posterior probability is unavailable in signed candidate metadata."
        ),
        "EXPECTANCY_UNAVAILABLE": (
            "Expectancy is unavailable in signed candidate metadata."
        ),
        "END_OF_WINDOW_CENSORING": (
            "The point-in-time forward outcome is censored by the replay end date."
        ),
        "ENTRY_NON_OCCURRENCE": (
            "The frozen recorded trade plan did not produce an entry."
        ),
        "SETUP_RARITY_SUSPECTED": (
            "Observed setup occurrences are below 60; this is a diagnostic "
            "suspicion, not certified causality."
        ),
        "MATCHING_FRAGMENTATION_SUSPECTED": (
            "Observed setup occurrences reach 60 but matched evidence remains "
            "insufficient; finer matching fragmentation is suspected, not proven."
        ),
    }
    for row in candidate_rows:
        view = str(row["price_view"])
        for code in _tuple_value(row.get("observed_cause_codes")):
            groups[(view, "CERTIFIED_OBSERVATION", code)].append(row)
        for code in _tuple_value(row.get("diagnostic_suspicion_codes")):
            groups[(view, "DIAGNOSTIC_SUSPICION", code)].append(row)
    populations = Counter(str(row["price_view"]) for row in candidate_rows)
    result: list[dict[str, object]] = []
    for (view, scope, code), rows in sorted(groups.items()):
        denominator = populations[view]
        percent = (
            Decimal("0")
            if denominator == 0
            else (Decimal(len(rows)) / Decimal(denominator) * Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        )
        result.append(
            {
                "price_view": view,
                "cause_scope": scope,
                "cause_code": code,
                "candidate_count": len(rows),
                "candidate_percent": percent,
                "setup_type_count": len({str(row["setup_type"]) for row in rows}),
                "total_sample_deficit": sum(
                    cast(int, row["sample_deficit"]) for row in rows
                ),
                "evidence_note": notes.get(code, "Governed evidence attribution."),
            }
        )
    return tuple(result)


def _fragmentation_diagnostics(
    cohort_rows: Sequence[dict[str, object]],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "price_view": row["price_view"],
            "setup_type": row["setup_type"],
            "candidate_count": row["candidate_count"],
            "median_sample_count": row["median_sample_count"],
            "maximum_sample_count": row["maximum_sample_count"],
            "candidates_meeting_requirement": row["candidates_meeting_requirement"],
            "setup_occurrence_capacity_60": (
                cast(int, row["candidate_count"]) >= _REQUIRED_SAMPLE_COUNT
            ),
            "setup_rarity_suspected": row["setup_rarity_suspected"],
            "matching_fragmentation_suspected": row["matching_fragmentation_suspected"],
            "causal_claim_permitted": False,
            "diagnostic_explanation": (
                "Observed setup frequency is below the frozen sample threshold."
                if bool(row["setup_rarity_suspected"])
                else (
                    "Finer setup matching may fragment evidence; causality is unproven."
                )
                if bool(row["matching_fragmentation_suspected"])
                else "No setup-frequency or fragmentation suspicion was triggered."
            ),
        }
        for row in cohort_rows
    )


def _arm_comparison(
    candidate_rows: Sequence[dict[str, object]],
) -> tuple[tuple[dict[str, object], ...], int]:
    indexed = {
        (
            str(row["price_view"]),
            str(row["observed_on"]),
            str(row["symbol"]),
        ): row
        for row in candidate_rows
    }
    keys = sorted({(observed_on, symbol) for _, observed_on, symbol in indexed})
    result: list[dict[str, object]] = []
    unexplained = 0
    for observed_on, symbol in keys:
        raw = indexed.get(("RAW", observed_on, symbol))
        adjusted = indexed.get(("ADJUSTED", observed_on, symbol))
        raw_setup = str(raw.get("setup_type") or "") if raw else ""
        adjusted_setup = str(adjusted.get("setup_type") or "") if adjusted else ""
        raw_sample = raw.get("evidence_sample_count") if raw else None
        adjusted_sample = adjusted.get("evidence_sample_count") if adjusted else None
        raw_deficit = cast(int, raw.get("sample_deficit", 0)) if raw else 0
        adjusted_deficit = (
            cast(int, adjusted.get("sample_deficit", 0)) if adjusted else 0
        )
        raw_outcome = str(raw.get("forward_outcome_status") or "") if raw else ""
        adjusted_outcome = (
            str(adjusted.get("forward_outcome_status") or "") if adjusted else ""
        )
        raw_causes = _tuple_value(raw.get("observed_cause_codes")) if raw else ()
        adjusted_causes = (
            _tuple_value(adjusted.get("observed_cause_codes")) if adjusted else ()
        )
        raw_fingerprint = str(raw.get("input_fingerprint") or "") if raw else ""
        adjusted_fingerprint = (
            str(adjusted.get("input_fingerprint") or "") if adjusted else ""
        )
        input_changed = bool(
            raw and adjusted and raw_fingerprint != adjusted_fingerprint
        )
        setup_changed = raw_setup != adjusted_setup
        sample_changed = raw_sample != adjusted_sample
        outcome_changed = raw_outcome != adjusted_outcome
        cause_changed = raw_causes != adjusted_causes
        any_changed = (
            setup_changed or sample_changed or outcome_changed or cause_changed
        )
        one_sided = raw is None or adjusted is None
        explained = any_changed and input_changed and not one_sided
        unexplained_row = one_sided or (any_changed and not explained)
        unexplained += int(unexplained_row)
        result.append(
            {
                "observed_on": observed_on,
                "symbol": symbol,
                "raw_present": raw is not None,
                "adjusted_present": adjusted is not None,
                "raw_setup_type": raw_setup,
                "adjusted_setup_type": adjusted_setup,
                "setup_type_changed": setup_changed,
                "raw_sample_count": raw_sample,
                "adjusted_sample_count": adjusted_sample,
                "sample_count_changed": sample_changed,
                "raw_sample_deficit": raw_deficit,
                "adjusted_sample_deficit": adjusted_deficit,
                "sample_deficit_delta": adjusted_deficit - raw_deficit,
                "raw_outcome_status": raw_outcome,
                "adjusted_outcome_status": adjusted_outcome,
                "outcome_status_changed": outcome_changed,
                "raw_observed_causes": raw_causes,
                "adjusted_observed_causes": adjusted_causes,
                "cause_set_changed": cause_changed,
                "raw_input_fingerprint": raw_fingerprint,
                "adjusted_input_fingerprint": adjusted_fingerprint,
                "input_changed": input_changed,
                "explained_evidence_difference": explained,
                "unexplained_evidence_divergence": unexplained_row,
            }
        )
    return tuple(result), unexplained


def _observed_causes(
    *,
    sample_count: int | None,
    evidence_strength: str,
    posterior: Decimal | None,
    expectancy: Decimal | None,
    outcome: CandidateOutcomeRecord,
) -> tuple[str, ...]:
    causes: list[str] = []
    if sample_count is None:
        causes.append("SAMPLE_COUNT_UNAVAILABLE")
    elif sample_count == 0:
        causes.append("ZERO_MATCHED_OUTCOMES")
    elif evidence_strength != "STRONG" and sample_count < _REQUIRED_SAMPLE_COUNT:
        causes.append("MATCHED_OUTCOME_DEFICIT")
    if not evidence_strength:
        causes.append("EVIDENCE_STRENGTH_UNAVAILABLE")
    if posterior is None:
        causes.append("POSTERIOR_UNAVAILABLE")
    if expectancy is None:
        causes.append("EXPECTANCY_UNAVAILABLE")
    status = _outcome_status(outcome)
    if status == "PENDING_END_OF_DATA":
        causes.append("END_OF_WINDOW_CENSORING")
    elif status == "NOT_ENTERED":
        causes.append("ENTRY_NON_OCCURRENCE")
    priority = {
        "SAMPLE_COUNT_UNAVAILABLE": 0,
        "ZERO_MATCHED_OUTCOMES": 1,
        "MATCHED_OUTCOME_DEFICIT": 2,
        "EVIDENCE_STRENGTH_UNAVAILABLE": 3,
        "POSTERIOR_UNAVAILABLE": 4,
        "EXPECTANCY_UNAVAILABLE": 5,
        "END_OF_WINDOW_CENSORING": 6,
        "ENTRY_NON_OCCURRENCE": 7,
    }
    return tuple(sorted(set(causes), key=lambda item: (priority[item], item)))


def _diagnostic_suspicions(
    *,
    sample_count: int | None,
    evidence_strength: str,
    cohort_candidate_count: int,
) -> tuple[str, ...]:
    if evidence_strength == "STRONG":
        return ()
    deficit = _sample_deficit(sample_count, evidence_strength)
    if deficit == 0:
        return ()
    if cohort_candidate_count < _REQUIRED_SAMPLE_COUNT:
        return ("SETUP_RARITY_SUSPECTED",)
    return ("MATCHING_FRAGMENTATION_SUSPECTED",)


def _sample_deficit(sample_count: int | None, evidence_strength: str) -> int:
    if evidence_strength.strip().upper() == "STRONG":
        return 0
    observed = sample_count if sample_count is not None else 0
    return max(0, _REQUIRED_SAMPLE_COUNT - observed)


def _sample_coverage_ratio(
    sample_count: int | None,
    evidence_strength: str,
) -> Decimal:
    if evidence_strength.strip().upper() == "STRONG":
        return Decimal("1.0000")
    observed = sample_count if sample_count is not None else 0
    return min(
        Decimal("1"),
        Decimal(observed) / Decimal(_REQUIRED_SAMPLE_COUNT),
    ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _outcome_status(outcome: CandidateOutcomeRecord) -> str:
    if outcome.completed:
        if outcome.won is True:
            return "COMPLETED_WIN"
        if outcome.won is False:
            return "COMPLETED_LOSS_OR_FLAT"
        return "COMPLETED_UNCLASSIFIED"
    if outcome.exit_reason == "PENDING_END_OF_DATA":
        return "PENDING_END_OF_DATA"
    if not outcome.entered:
        return "NOT_ENTERED"
    return "INCOMPLETE"


def _evidence_probes() -> tuple[
    tuple[dict[str, object], ...],
    dict[str, object],
    tuple[str, ...],
]:
    first = _probe_pass()
    second = _probe_pass()
    deterministic = first == second
    defects: list[str] = []
    rows: list[dict[str, object]] = []
    for left, right in zip(first, second, strict=True):
        row = dict(left)
        row["deterministic"] = left == right
        if not bool(row["expectation_matched"]):
            defects.append(f"EVIDENCE_PROBE_FAILED@{row['probe_id']}")
        if left != right:
            defects.append(f"EVIDENCE_PROBE_NONDETERMINISTIC@{row['probe_id']}")
        rows.append(row)
    summary: dict[str, object] = {
        "probe_count": len(rows),
        "passed_probe_count": sum(bool(row["expectation_matched"]) for row in rows),
        "failed_probe_count": sum(not bool(row["expectation_matched"]) for row in rows),
        "deterministic": deterministic,
    }
    return tuple(rows), summary, tuple(sorted(set(defects)))


def _probe_pass() -> tuple[dict[str, object], ...]:
    scenarios = (
        (
            "MISSING_SAMPLE",
            None,
            "INSUFFICIENT",
            10,
            60,
            "SAMPLE_COUNT_UNAVAILABLE",
            "SETUP_RARITY_SUSPECTED",
        ),
        (
            "ZERO_SAMPLE",
            0,
            "INSUFFICIENT",
            10,
            60,
            "ZERO_MATCHED_OUTCOMES",
            "SETUP_RARITY_SUSPECTED",
        ),
        (
            "BELOW_THRESHOLD",
            59,
            "MODERATE",
            60,
            1,
            "MATCHED_OUTCOME_DEFICIT",
            "MATCHING_FRAGMENTATION_SUSPECTED",
        ),
        (
            "AT_THRESHOLD",
            60,
            "MODERATE",
            60,
            0,
            "NONE",
            "NONE",
        ),
        (
            "ABOVE_THRESHOLD",
            61,
            "MODERATE",
            60,
            0,
            "NONE",
            "NONE",
        ),
        (
            "STRONG_OVERRIDE",
            0,
            "STRONG",
            10,
            0,
            "ZERO_MATCHED_OUTCOMES",
            "NONE",
        ),
    )
    rows: list[dict[str, object]] = []
    for (
        probe_id,
        sample_count,
        strength,
        cohort_count,
        expected_deficit,
        expected_cause,
        expected_suspicion,
    ) in scenarios:
        deficit = _sample_deficit(sample_count, strength)
        outcome = CandidateOutcomeRecord(
            observed_on=date(2026, 1, 1),
            symbol="PROBE",
            entered=True,
            completed=True,
            won=True,
            realized_return_pct=Decimal("1"),
            realized_r=Decimal("1"),
            holding_period_days=1,
            exit_reason="TARGET",
            evidence_note="Deterministic B7 probe.",
        )
        causes = _observed_causes(
            sample_count=sample_count,
            evidence_strength=strength,
            posterior=Decimal("0.55"),
            expectancy=Decimal("0.20"),
            outcome=outcome,
        )
        suspicions = _diagnostic_suspicions(
            sample_count=sample_count,
            evidence_strength=strength,
            cohort_candidate_count=cohort_count,
        )
        observed_cause = causes[0] if causes else "NONE"
        observed_suspicion = suspicions[0] if suspicions else "NONE"
        matched = (
            deficit == expected_deficit
            and observed_cause == expected_cause
            and observed_suspicion == expected_suspicion
        )
        rows.append(
            {
                "probe_id": probe_id,
                "probe_scope": "SAMPLE_DEFICIT_AND_CAUSE_CLASSIFICATION",
                "observed_sample_count": sample_count,
                "evidence_strength": strength,
                "cohort_candidate_count": cohort_count,
                "expected_sample_deficit": expected_deficit,
                "observed_sample_deficit": deficit,
                "expected_observed_cause": expected_cause,
                "observed_observed_cause": observed_cause,
                "expected_suspicion": expected_suspicion,
                "observed_suspicion": observed_suspicion,
                "expectation_matched": matched,
            }
        )
    return tuple(rows)


def _arm_summary(
    rows: Sequence[dict[str, object]],
    *,
    price_view: str,
) -> dict[str, object]:
    selected = tuple(row for row in rows if row["price_view"] == price_view)
    known_samples = tuple(
        cast(int, row["evidence_sample_count"])
        for row in selected
        if row["evidence_sample_count"] is not None
    )
    causes = Counter(str(row["primary_observed_cause"]) for row in selected)
    setups = Counter(str(row["setup_type"]) for row in selected)
    completed = sum(bool(row["forward_completed"]) for row in selected)
    return {
        "candidate_count": len(selected),
        "setup_type_count": len(setups),
        "known_sample_count": len(known_samples),
        "unknown_sample_count": len(selected) - len(known_samples),
        "zero_sample_count": sum(value == 0 for value in known_samples),
        "below_requirement_count": sum(
            cast(int, row["sample_deficit"]) > 0 for row in selected
        ),
        "requirement_satisfied_count": sum(
            bool(row["sample_rule_satisfied"]) for row in selected
        ),
        "minimum_sample_count": min(known_samples, default=None),
        "median_sample_count": _median_int(known_samples),
        "maximum_sample_count": max(known_samples, default=None),
        "average_sample_count": _average_int(known_samples),
        "total_sample_deficit": sum(
            cast(int, row["sample_deficit"]) for row in selected
        ),
        "forward_completed_count": completed,
        "forward_pending_count": sum(
            row["forward_outcome_status"] == "PENDING_END_OF_DATA" for row in selected
        ),
        "forward_not_entered_count": sum(
            row["forward_outcome_status"] == "NOT_ENTERED" for row in selected
        ),
        "forward_completion_rate": (
            Decimal("0")
            if not selected
            else (
                Decimal(completed) / Decimal(len(selected)) * Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        ),
        "dominant_setup_type": setups.most_common(1)[0][0] if setups else "NONE",
        "dominant_observed_cause": (causes.most_common(1)[0][0] if causes else "NONE"),
        "evidence_provenance_complete": bool(selected)
        and all(bool(row["evidence_provenance_complete"]) for row in selected),
    }


def _cohort_summary(rows: Sequence[dict[str, object]]) -> dict[str, object]:
    setups = Counter(str(row["setup_type"]) for row in rows)
    rarity = sum(bool(row["setup_rarity_suspected"]) for row in rows)
    fragmentation = sum(bool(row["matching_fragmentation_suspected"]) for row in rows)
    return {
        "cohort_count": len(rows),
        "setup_type_count": len(setups),
        "rarity_suspicion_count": rarity,
        "fragmentation_suspicion_count": fragmentation,
        "causal_claim_permitted": False,
    }


def _outcome_coverage_summary(
    rows: Sequence[dict[str, object]],
) -> dict[str, object]:
    status = Counter(str(row["forward_outcome_status"]) for row in rows)
    return {
        "outcome_row_count": len(rows),
        "completed_count": sum(
            count for key, count in status.items() if key.startswith("COMPLETED")
        ),
        "pending_end_of_data_count": status["PENDING_END_OF_DATA"],
        "not_entered_count": status["NOT_ENTERED"],
        "incomplete_count": status["INCOMPLETE"],
        "status_distribution": dict(sorted(status.items())),
    }


def _attribution_summary(
    rows: Sequence[dict[str, object]],
) -> dict[str, object]:
    observed = Counter(
        str(row["cause_code"])
        for row in rows
        if row["cause_scope"] == "CERTIFIED_OBSERVATION"
    )
    suspected = Counter(
        str(row["cause_code"])
        for row in rows
        if row["cause_scope"] == "DIAGNOSTIC_SUSPICION"
    )
    return {
        "certified_observation_type_count": len(observed),
        "diagnostic_suspicion_type_count": len(suspected),
        "dominant_certified_observation": (
            observed.most_common(1)[0][0] if observed else "NONE"
        ),
        "dominant_diagnostic_suspicion": (
            suspected.most_common(1)[0][0] if suspected else "NONE"
        ),
        "diagnostic_suspicion_may_be_claimed_as_causality": False,
    }


def _readiness(
    *,
    population_nonempty: bool,
    setup_identity_complete: bool,
    evidence_provenance_complete: bool,
    implementation_defects: Sequence[str],
    unexplained_divergences: int,
) -> tuple[str, tuple[str, ...]]:
    if implementation_defects or not setup_identity_complete:
        blockers = tuple(
            sorted(
                {
                    *implementation_defects,
                    *(
                        ("SETUP_IDENTITY_INCOMPLETE",)
                        if not setup_identity_complete
                        else ()
                    ),
                }
            )
        )
        return B7_BLOCKED_SETUP, blockers
    if unexplained_divergences:
        return B7_BLOCKED_DIVERGENCE, (
            f"UNEXPLAINED_EVIDENCE_DIVERGENCES={unexplained_divergences}",
        )
    if not population_nonempty:
        return B7_BLOCKED_EMPTY, ("EMPTY_SETUP_MATCHED_EVIDENCE_POPULATION",)
    if not evidence_provenance_complete:
        return B7_BLOCKED_PROVENANCE, ("INCOMPLETE_EVIDENCE_PROVENANCE",)
    return B7_READY, ()


def export_governed_setup_matched_evidence(
    *,
    report: dict[str, Any],
    candidate_rows: tuple[dict[str, object], ...],
    cohort_rows: tuple[dict[str, object], ...],
    outcome_rows: tuple[dict[str, object], ...],
    attribution_rows: tuple[dict[str, object], ...],
    fragmentation_rows: tuple[dict[str, object], ...],
    comparison_rows: tuple[dict[str, object], ...],
    provenance_rows: tuple[dict[str, object], ...],
    probe_rows: tuple[dict[str, object], ...],
    output: Path,
) -> tuple[Path, ...]:
    """Export deterministic B7 evidence and bind every supporting file."""

    output.mkdir(parents=True, exist_ok=True)
    certificate_path = output / "htr010b7_setup_matched_evidence_certificate.json"
    certificate_path.unlink(missing_ok=True)
    support_paths = (
        _write_csv(
            output / "htr010b7_candidate_evidence_sufficiency.csv",
            candidate_rows,
            fieldnames=_CANDIDATE_FIELDS,
        ),
        _write_csv(
            output / "htr010b7_setup_cohort_coverage.csv",
            cohort_rows,
            fieldnames=_COHORT_FIELDS,
        ),
        _write_csv(
            output / "htr010b7_outcome_coverage_ledger.csv",
            outcome_rows,
            fieldnames=_OUTCOME_FIELDS,
        ),
        _write_csv(
            output / "htr010b7_evidence_deficit_attribution.csv",
            attribution_rows,
            fieldnames=_ATTRIBUTION_FIELDS,
        ),
        _write_csv(
            output / "htr010b7_setup_fragmentation_diagnostics.csv",
            fragmentation_rows,
            fieldnames=_FRAGMENTATION_FIELDS,
        ),
        _write_csv(
            output / "htr010b7_raw_adjusted_evidence_comparison.csv",
            comparison_rows,
            fieldnames=_COMPARISON_FIELDS,
        ),
        _write_csv(
            output / "htr010b7_evidence_provenance_audit.csv",
            provenance_rows,
            fieldnames=_PROVENANCE_FIELDS,
        ),
        _write_csv(
            output / "htr010b7_evidence_boundary_probe_ledger.csv",
            probe_rows,
            fieldnames=_PROBE_FIELDS,
        ),
        _write_text(
            output / "htr010b7_executive_report.md",
            _markdown(report),
        ),
    )
    report["artifact_hashes"] = {
        path.name: _file_sha256(path) for path in support_paths
    }
    report["report_sha256"] = _digest_mapping(report)
    certificate = _write_json(certificate_path, report)
    return (certificate, *support_paths)


def validate_governed_setup_matched_evidence_certificate(
    path: Path,
    *,
    require_ready: bool = False,
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    """Validate the signed B7 contract and every supporting artifact."""

    payload = _mapping(path)
    if payload.get("contract_version") != HTR010B7_CONTRACT_VERSION:
        raise ValueError("unsupported HTR-010B7 evidence contract")
    _validate_digest(payload, "HTR-010B7 setup-matched evidence certificate")
    _validate_research_only_flags(payload)
    _validate_certificate_lineage(payload)
    if project_root is not None:
        root = Path(project_root)
        expected_policy = _mapping_copy(
            payload,
            "institutional_policy_source_sha256s",
        )
        expected_pipeline = _mapping_copy(
            payload,
            "frozen_pipeline_component_sha256s",
        )
        if _b5_policy_source_hashes(root) != expected_policy:
            raise ValueError("HTR-010B7 frozen policy source digest mismatch")
        if _b5_pipeline_component_hashes(root) != expected_pipeline:
            raise ValueError("HTR-010B7 frozen pipeline component digest mismatch")
    hashes = payload.get("artifact_hashes")
    if not isinstance(hashes, dict):
        raise ValueError("HTR-010B7 certificate lacks supporting artifact hashes")
    names = frozenset(str(name) for name in hashes)
    if names != _REQUIRED_B7_SUPPORT_ARTIFACTS:
        raise ValueError("HTR-010B7 supporting artifact set mismatch")
    for name, expected in sorted(hashes.items()):
        expected_sha256 = str(expected)
        if not _is_sha256(expected_sha256):
            raise ValueError(f"HTR-010B7 supporting digest is invalid: {name}")
        if _file_sha256(_artifact_path(path.parent, name)) != expected_sha256:
            raise ValueError(f"HTR-010B7 supporting artifact changed: {name}")
    readiness = str(payload.get("readiness_decision") or "")
    valid = {
        B7_READY,
        B7_BLOCKED_EMPTY,
        B7_BLOCKED_PROVENANCE,
        B7_BLOCKED_SETUP,
        B7_BLOCKED_DIVERGENCE,
    }
    if readiness not in valid:
        raise ValueError("HTR-010B7 readiness decision is invalid")
    enabled = payload.get("governed_setup_matched_evidence_research_enabled")
    expected_enabled = readiness == B7_READY
    if enabled is not expected_enabled:
        raise ValueError("HTR-010B7 readiness and enablement disagree")
    _validate_certificate_state_semantics(payload)
    if require_ready and not expected_enabled:
        raise ValueError("HTR-010B7 does not permit setup-matched evidence research")
    return payload


def _validate_research_only_flags(payload: Mapping[str, object]) -> None:
    required_false = (
        "threshold_change_permitted",
        "synthetic_outcomes_permitted",
        "outcome_backfill_mutation_enabled",
        "diagnostic_suspicion_may_be_claimed_as_causality",
        "governed_adjusted_trade_research_enabled",
        "economic_superiority_claimed",
        "live_scoring_enabled",
        "recommendation_influence",
        "portfolio_policy_influence",
        "execution_influence",
        "learning_mutation_enabled",
        "active_replay_integration",
        "production_influence",
    )
    for key in required_false:
        if payload.get(key) is not False:
            raise ValueError(f"HTR-010B7 governance flag must remain false: {key}")
    if payload.get("research_scope") != RESEARCH_SCOPE:
        raise ValueError("HTR-010B7 research scope is invalid")
    if payload.get("governed_approval_gate_research_enabled") is not True:
        raise ValueError("HTR-010B7 requires B5 approval-gate research readiness")
    if payload.get("governed_approval_constraint_research_enabled") is not True:
        raise ValueError("HTR-010B7 requires B6 constraint research readiness")


def _validate_certificate_lineage(payload: Mapping[str, object]) -> None:
    if payload.get("b5_contract_version") != HTR010B5_CONTRACT_VERSION:
        raise ValueError("HTR-010B7 B5 contract lineage is invalid")
    if payload.get("b6_contract_version") != HTR010B6_CONTRACT_VERSION:
        raise ValueError("HTR-010B7 B6 contract lineage is invalid")
    for key in (
        "b5_report_sha256",
        "b5_certificate_file_sha256",
        "b6_report_sha256",
        "b6_certificate_file_sha256",
        "b5_candidate_ledger_sha256",
        "b5_gate_ledger_sha256",
        "b6_frontier_ledger_sha256",
        "b6_margin_ledger_sha256",
    ):
        if not _is_sha256(str(payload.get(key) or "")):
            raise ValueError(f"HTR-010B7 lineage digest is invalid: {key}")
    inputs = _mapping_copy(payload, "input_artifact_file_sha256s")
    expected_inputs = {
        "identity_artifact",
        "corporate_action_artifact",
        "final_closure_report",
        "admission_contract",
        "identity_admission",
        "raw_universe",
        "adjusted_universe",
    }
    if set(inputs) != expected_inputs:
        raise ValueError("HTR-010B7 input artifact set is invalid")
    if any(not _is_sha256(value) for value in inputs.values()):
        raise ValueError("HTR-010B7 input artifact digest is invalid")
    if (
        _integer(
            payload.get("required_matched_sample_count"),
            "B7 sample requirement",
        )
        != _REQUIRED_SAMPLE_COUNT
    ):
        raise ValueError("HTR-010B7 sample threshold changed")
    if (
        _decimal(
            payload.get("minimum_approval_posterior"),
            "B7 posterior threshold",
        )
        != _MIN_APPROVAL_POSTERIOR
    ):
        raise ValueError("HTR-010B7 posterior threshold changed")
    if (
        _decimal(
            payload.get("minimum_approval_expectancy"),
            "B7 expectancy threshold",
        )
        != _MIN_APPROVAL_EXPECTANCY
    ):
        raise ValueError("HTR-010B7 expectancy threshold changed")
    lineage = _nested_mapping(payload, "governed_store_lineage")
    if lineage.get("path_representation_neutral_lineage_validated") is not True:
        raise ValueError("HTR-010B7 lacks path-neutral lineage validation")
    for key in (
        "identity_session_sha256",
        "final_closure_report_sha256",
        "admission_contract_sha256",
        "b5_path_sensitive_input_manifest_sha256",
        "rebuilt_path_sensitive_input_manifest_sha256",
        "path_neutral_input_artifact_sha256",
    ):
        if not _is_sha256(str(lineage.get(key) or "")):
            raise ValueError(f"HTR-010B7 governed lineage digest is invalid: {key}")


def _validate_certificate_state_semantics(payload: Mapping[str, object]) -> None:
    setup_defects = tuple(
        str(item) for item in _list_value(payload, "setup_identity_defects")
    )
    defects = tuple(
        str(item) for item in _list_value(payload, "implementation_defects")
    )
    if setup_defects != tuple(sorted(set(setup_defects))):
        raise ValueError("HTR-010B7 setup defects are not deterministic")
    if defects != tuple(sorted(set(defects))):
        raise ValueError("HTR-010B7 implementation defects are not deterministic")
    observed_setup_defects = _integer(
        payload.get("setup_identity_defect_count"),
        "setup defect count",
    )
    if observed_setup_defects != len(setup_defects):
        raise ValueError("HTR-010B7 setup defect count is inconsistent")
    if _integer(payload.get("implementation_defect_count"), "defect count") != len(
        defects
    ):
        raise ValueError("HTR-010B7 implementation defect count is inconsistent")
    population = payload.get("setup_matched_population_nonempty") is True
    setup_complete = payload.get("setup_identity_complete") is True
    provenance_complete = payload.get("evidence_provenance_complete") is True
    divergences = _integer(
        payload.get("unexplained_evidence_divergence_count"),
        "B7 divergence count",
    )
    expected, blockers = _readiness(
        population_nonempty=population,
        setup_identity_complete=setup_complete,
        evidence_provenance_complete=provenance_complete,
        implementation_defects=defects,
        unexplained_divergences=divergences,
    )
    if setup_defects:
        expected = B7_BLOCKED_SETUP
        blockers = tuple(sorted({*blockers, "SETUP_IDENTITY_INCOMPLETE"}))
    if payload.get("readiness_decision") != expected:
        raise ValueError("HTR-010B7 readiness disagrees with certificate evidence")
    observed_blockers = tuple(
        str(item) for item in _list_value(payload, "readiness_blockers")
    )
    if observed_blockers != blockers:
        raise ValueError("HTR-010B7 readiness blockers are inconsistent")
    probes = _nested_mapping(payload, "probe_summary")
    failed_probes = _integer(probes.get("failed_probe_count"), "failed probes")
    if failed_probes != 0 and expected == B7_READY:
        raise ValueError("HTR-010B7 ready certificate has failed probes")


def _markdown(report: Mapping[str, object]) -> str:
    raw = _nested_mapping(report, "raw_evidence_summary")
    adjusted = _nested_mapping(report, "adjusted_evidence_summary")
    probes = _nested_mapping(report, "probe_summary")
    attribution = _nested_mapping(report, "deficit_attribution_summary")
    lines = [
        "# HTR-010B7 Governed Setup-Matched Evidence Certification",
        "",
        f"Readiness: **{report['readiness_decision']}**",
        "",
        "## Population",
        "",
        f"- Replay sessions: {report['session_count']}",
        f"- RAW approvable candidates: {raw['candidate_count']}",
        f"- ADJUSTED approvable candidates: {adjusted['candidate_count']}",
        f"- Frozen matched-sample requirement: {_REQUIRED_SAMPLE_COUNT}",
        "",
        "## Evidence sufficiency",
        "",
        f"- RAW candidates below requirement: {raw['below_requirement_count']}",
        (
            "- ADJUSTED candidates below requirement: "
            f"{adjusted['below_requirement_count']}"
        ),
        f"- RAW total sample deficit: {raw['total_sample_deficit']}",
        f"- ADJUSTED total sample deficit: {adjusted['total_sample_deficit']}",
        (
            "- Dominant certified observation: "
            f"{attribution['dominant_certified_observation']}"
        ),
        (
            "- Dominant diagnostic suspicion: "
            f"{attribution['dominant_diagnostic_suspicion']}"
        ),
        "",
        "## Certification",
        "",
        f"- Setup identity complete: {report['setup_identity_complete']}",
        f"- Evidence provenance complete: {report['evidence_provenance_complete']}",
        f"- Boundary probes passed: {probes['passed_probe_count']}",
        f"- Implementation defects: {report['implementation_defect_count']}",
        (
            "- Unexplained evidence divergences: "
            f"{report['unexplained_evidence_divergence_count']}"
        ),
        "",
        "Diagnostic suspicions are not certified causes. No threshold, outcome, ",
        "recommendation, approval, trade, learning, or production policy changed.",
        "",
        "PRODUCTION_INFLUENCE=false",
        "",
    ]
    return "\n".join(lines)


def _provenance_check(
    check_id: str,
    scope: str,
    expected: object,
    observed: object,
    explanation: str,
    *,
    severity: str = "ERROR",
    force_pass: bool = False,
) -> dict[str, object]:
    return {
        "check_id": check_id,
        "scope": scope,
        "expected": _stable_text(expected),
        "observed": _stable_text(observed),
        "passed": force_pass or _json_ready(expected) == _json_ready(observed),
        "severity": severity,
        "explanation": explanation,
    }


def _subset_provenance_check(
    check_id: str,
    scope: str,
    required_subset: Sequence[object],
    available_superset: Sequence[object],
    explanation: str,
) -> dict[str, object]:
    required = tuple(sorted(str(item) for item in required_subset))
    available = tuple(sorted(str(item) for item in available_superset))
    return {
        "check_id": check_id,
        "scope": scope,
        "expected": _stable_text(required),
        "observed": _stable_text(available),
        "passed": set(required).issubset(set(available)),
        "severity": "ERROR",
        "explanation": explanation,
    }


def _pair_check_observed(
    rows: Sequence[dict[str, object]],
    check_id: str,
) -> str:
    for row in rows:
        if row["check_id"] == check_id:
            return str(row["observed"])
    raise ValueError(f"missing B7 provenance check: {check_id}")


def _setup_type(seed: EvidenceSeed) -> str:
    return seed.ranking.setup_type.strip().upper() or "UNKNOWN"


def _candidate_key(row: Mapping[str, object], label: str) -> CandidateKey:
    view = str(row.get("price_view") or "").strip().upper()
    if view not in {"RAW", "ADJUSTED"}:
        raise ValueError(f"{label} has invalid price view")
    return (
        view,
        _date_value(row.get("observed_on"), f"{label} date"),
        _symbol(row.get("symbol"), f"{label} symbol"),
    )


def _key_defect(code: str, key: CandidateKey, suffix: str = "") -> str:
    detail = f"|{suffix}" if suffix else ""
    return f"{code}@{key[0]}|{key[1].isoformat()}|{key[2]}{detail}"


def _candidate_sort_key(row: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("price_view") or ""),
        str(row.get("observed_on") or ""),
        str(row.get("symbol") or ""),
    )


def _median_int(values: Sequence[int]) -> Decimal | None:
    if not values:
        return None
    return Decimal(str(median(values))).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def _average_int(values: Sequence[int]) -> Decimal | None:
    if not values:
        return None
    return (Decimal(sum(values)) / Decimal(len(values))).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def _mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON mapping: {path}")
    return {str(key): value for key, value in payload.items()}


def _mapping_copy(
    payload: Mapping[str, object],
    key: str,
) -> dict[str, str]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"expected mapping: {key}")
    return {str(item_key): str(item) for item_key, item in value.items()}


def _nested_mapping(
    payload: Mapping[str, object],
    key: str,
) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"expected nested mapping: {key}")
    return {str(item_key): item for item_key, item in value.items()}


def _list_value(payload: Mapping[str, object], key: str) -> tuple[object, ...]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"expected list: {key}")
    return tuple(value)


def _tuple_value(value: object) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        return tuple(item for item in value.split("|") if item)
    if isinstance(value, (tuple, list, set, frozenset)):
        return tuple(sorted(str(item) for item in value))
    raise ValueError("expected tuple-compatible value")


def _csv_rows(path: Path) -> tuple[dict[str, str], ...]:
    with path.open(newline="", encoding="utf-8") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


def _date_value(value: object, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO date") from error


def _symbol(value: object, label: str) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol:
        raise ValueError(f"{label} cannot be empty")
    return symbol


def _boolean(value: object, label: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    raise ValueError(f"{label} must be boolean")


def _integer(value: object, label: str) -> int:
    try:
        return int(str(value))
    except ValueError as error:
        raise ValueError(f"{label} must be an integer") from error


def _optional_int(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError as error:
        raise ValueError("optional integer is invalid") from error


def _decimal(value: object, label: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{label} must be numeric") from error


def _optional_decimal(value: object) -> Decimal | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as error:
        raise ValueError("optional decimal is invalid") from error


def _hash_paths(paths: Mapping[str, Path]) -> dict[str, str]:
    return {key: _file_sha256(path) for key, path in sorted(paths.items())}


def _validate_paths_unchanged(
    paths: Mapping[str, Path],
    expected: Mapping[str, str],
) -> None:
    for key, path in sorted(paths.items()):
        if _file_sha256(path) != expected[key]:
            raise ValueError(f"HTR-010B7 input changed during analysis: {key}")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest_mapping(payload: Mapping[str, object]) -> str:
    normalized = {
        str(key): value for key, value in payload.items() if key != "report_sha256"
    }
    encoded = json.dumps(
        _json_ready(normalized),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_digest(payload: Mapping[str, object], label: str) -> None:
    observed = str(payload.get("report_sha256") or "")
    if not _is_sha256(observed) or observed != _digest_mapping(payload):
        raise ValueError(f"{label} digest mismatch")


def _artifact_path(root: Path, name: str) -> Path:
    candidate = root / name
    if candidate.parent != root or not candidate.is_file():
        raise ValueError(f"supporting artifact unavailable: {name}")
    return candidate


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    *,
    fieldnames: Sequence[str],
) -> Path:
    from io import StringIO

    stream = StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=tuple(fieldnames),
        lineterminator="\n",
        extrasaction="raise",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})
    return _write_text(path, stream.getvalue())


def _write_json(path: Path, payload: Mapping[str, object]) -> Path:
    content = json.dumps(_json_ready(payload), indent=2, sort_keys=True) + "\n"
    return _write_text(path, content)


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return path


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (date, datetime, Decimal)):
        return str(value)
    if isinstance(value, Mapping):
        return json.dumps(_json_ready(value), sort_keys=True, separators=(",", ":"))
    if isinstance(value, (tuple, list, set, frozenset)):
        return "|".join(str(_csv_value(item)) for item in value)
    return value


def _json_ready(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(
            (_json_ready(item) for item in value),
            key=lambda item: json.dumps(item, sort_keys=True),
        )
    if isinstance(value, (date, datetime, Decimal, Path)):
        return str(value)
    return value


def _stable_text(value: object) -> str:
    ready = _json_ready(value)
    if isinstance(ready, (dict, list)):
        return json.dumps(ready, sort_keys=True, separators=(",", ":"))
    return str(ready)


def _progress(
    callback: ProgressCallback | None,
    current: int,
    total: int,
    description: str,
) -> None:
    if callback is not None:
        callback(current, total, description)


__all__ = [
    "B7_BLOCKED_DIVERGENCE",
    "B7_BLOCKED_EMPTY",
    "B7_BLOCKED_PROVENANCE",
    "B7_BLOCKED_SETUP",
    "B7_READY",
    "HTR010B7_CONTRACT_VERSION",
    "GovernedSetupMatchedEvidenceEngine",
    "GovernedSetupMatchedEvidenceResult",
    "export_governed_setup_matched_evidence",
    "validate_governed_setup_matched_evidence_certificate",
]
