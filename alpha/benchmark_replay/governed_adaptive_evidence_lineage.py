"""Governed point-in-time adaptive evidence lineage certification for HTR-010B8."""

from __future__ import annotations

import csv
import hashlib
import inspect
import json
import os
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace
from typing import Any, cast

from alpha.application.intelligence import IntelligenceApplicationService
from alpha.benchmark_replay.governed_setup_matched_evidence import (
    B7_READY,
    HTR010B7_CONTRACT_VERSION,
    validate_governed_setup_matched_evidence_certificate,
)
from alpha.decision_intelligence.engine import candidate_from_recommendation
from alpha.learning_intelligence import (
    AdaptiveLearningEngine,
    EvidenceStrength,
    FingerprintStatistics,
    LearningOutcomeSample,
    SetupFingerprint,
)
from alpha.learning_intelligence.fingerprints import (
    fingerprint_from_ledger_entry,
    fingerprint_from_recommendation,
)
from alpha.performance_intelligence.models import RecommendationLedgerEntry
from alpha.recommendation_intelligence.engines import RecommendationEngine

HTR010B8_CONTRACT_VERSION = "HTR-010B8-v1.0.0"

B8_READY = "READY_FOR_GOVERNED_ADAPTIVE_EVIDENCE_LINEAGE_RESEARCH"
B8_BLOCKED_EMPTY = "BLOCKED_BY_EMPTY_POINT_IN_TIME_ADAPTIVE_POPULATION"
B8_BLOCKED_FINGERPRINT = "BLOCKED_BY_FINGERPRINT_CONTRACT_MISMATCH"
B8_BLOCKED_PUBLICATION = "BLOCKED_BY_UNEXPLAINED_ADAPTIVE_EVIDENCE_PUBLICATION_GAP"
B8_BLOCKED_LEAKAGE = "BLOCKED_BY_POINT_IN_TIME_EVIDENCE_LEAKAGE"
B8_BLOCKED_DEFECT = "BLOCKED_BY_ADAPTIVE_EVIDENCE_IMPLEMENTATION_DEFECT"
B8_BLOCKED_ARM = "BLOCKED_BY_UNEXPLAINED_ADAPTIVE_ARM_DIVERGENCE"

RESEARCH_SCOPE = "GOVERNED_ADAPTIVE_EVIDENCE_LINEAGE_RESEARCH_ONLY"

ProgressCallback = Callable[[int, int, str], None]
CandidateKey = tuple[str, date, str]

_B7_CANDIDATE_ARTIFACT = "htr010b7_candidate_evidence_sufficiency.csv"
_B7_OUTCOME_ARTIFACT = "htr010b7_outcome_coverage_ledger.csv"

_REQUIRED_B8_SUPPORT_ARTIFACTS = frozenset(
    {
        "htr010b8_candidate_adaptive_evidence_lineage.csv",
        "htr010b8_point_in_time_outcome_eligibility.csv",
        "htr010b8_fingerprint_parity_ledger.csv",
        "htr010b8_shadow_adaptive_assessments.csv",
        "htr010b8_publication_contract_gap_ledger.csv",
        "htr010b8_evidence_source_separation.csv",
        "htr010b8_raw_adjusted_adaptive_comparison.csv",
        "htr010b8_non_vacuity_probe_ledger.csv",
        "htr010b8_executive_report.md",
    }
)

_ADAPTIVE_METADATA_CONTRACT = (
    (
        "adaptive_adjusted_confidence",
        "adjusted_confidence",
        "TEXT",
    ),
    (
        "adaptive_evidence_strength",
        "evidence_strength",
        "TEXT",
    ),
    (
        "adaptive_posterior_probability",
        "posterior_win_probability",
        "DECIMAL",
    ),
    (
        "adaptive_expectancy",
        "expectancy",
        "DECIMAL",
    ),
    (
        "adaptive_sample_count",
        "completed_sample_count",
        "INTEGER",
    ),
)

_SOURCE_CONTRACT_PATHS = (
    "alpha/application/intelligence.py",
    "alpha/decision_intelligence/engine.py",
    "alpha/learning_intelligence/engine.py",
    "alpha/learning_intelligence/fingerprints.py",
    "alpha/performance_intelligence/recorder.py",
    "alpha/recommendation_intelligence/engines.py",
)

_FINGERPRINT_DIMENSIONS = (
    "final_verdict",
    "setup_type",
    "setup_state",
    "market_regime",
    "sector",
    "trend_regime",
    "volume_regime",
    "volatility_regime",
    "relative_strength_regime",
    "candle_pattern",
    "breakout_retracement_state",
    "dma_alignment",
    "data_completeness_level",
)

_B7_UNOBSERVABLE_FINGERPRINT_DIMENSIONS = (
    "market_regime",
    "sector",
    "trend_regime",
    "volume_regime",
    "volatility_regime",
    "relative_strength_regime",
    "candle_pattern",
    "breakout_retracement_state",
    "dma_alignment",
    "data_completeness_level",
)

_CANDIDATE_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "final_signal",
    "setup_type",
    "setup_stage",
    "fingerprint_key",
    "eligible_completed_sample_count",
    "eventual_completed_match_count",
    "posterior_win_probability",
    "expectancy",
    "evidence_strength",
    "adjusted_confidence",
    "current_published_sample_count",
    "current_published_posterior",
    "current_published_expectancy",
    "current_published_evidence_strength",
    "publication_gap_field_count",
    "publication_gap_fully_attributed",
    "primary_lineage_finding",
    "point_in_time_contract_complete",
    "input_fingerprint",
)
_ELIGIBILITY_FIELDS = (
    "price_view",
    "candidate_observed_on",
    "candidate_symbol",
    "candidate_fingerprint_key",
    "outcome_observed_on",
    "outcome_symbol",
    "outcome_status",
    "outcome_holding_period_days",
    "inferred_completion_date",
    "fingerprint_match",
    "same_price_arm",
    "completed",
    "eligible",
    "eligibility_reason",
    "realized_r",
)
_FINGERPRINT_FIELDS = (
    "scope",
    "price_view",
    "observed_on",
    "symbol",
    "recommendation_fingerprint_key",
    "ledger_fingerprint_key",
    "adaptive_lookup_fingerprint_key",
    "observable_parity",
    "full_parity_certified",
    "mismatch_codes",
    "unobservable_dimensions",
    "gap_explained",
    "contract_status",
)
_ASSESSMENT_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "fingerprint_key",
    "base_confidence",
    "completed_sample_count",
    "pending_sample_count",
    "not_triggered_count",
    "win_count",
    "loss_count",
    "expectancy",
    "prior_win_probability",
    "posterior_win_probability",
    "lower_confidence_bound",
    "upper_confidence_bound",
    "evidence_strength",
    "adjusted_confidence",
    "confidence_adjustment_reason",
    "eventual_completed_match_count",
    "point_in_time_contract_complete",
)
_PUBLICATION_FIELDS = (
    "scope",
    "price_view",
    "observed_on",
    "symbol",
    "metadata_key",
    "adaptive_field",
    "value_type",
    "shadow_computed_value",
    "currently_published_value",
    "institutional_observed_value",
    "consumer_expects_key",
    "producer_publishes_key",
    "orchestrator_invokes_adaptive_assessment",
    "publication_status",
    "root_cause",
    "gap_explained",
)
_SOURCE_SEPARATION_FIELDS = (
    "evidence_source",
    "matching_definition",
    "sample_unit",
    "time_boundary",
    "primary_consumer",
    "equivalent_to_adaptive_learning",
    "cross_source_merge_permitted",
    "governance_note",
)
_COMPARISON_FIELDS = (
    "observed_on",
    "symbol",
    "raw_present",
    "adjusted_present",
    "raw_fingerprint_key",
    "adjusted_fingerprint_key",
    "raw_completed_sample_count",
    "adjusted_completed_sample_count",
    "raw_posterior",
    "adjusted_posterior",
    "raw_expectancy",
    "adjusted_expectancy",
    "raw_publication_gap_fields",
    "adjusted_publication_gap_fields",
    "input_fingerprint_changed",
    "difference_codes",
    "explained",
)
_PROBE_FIELDS = (
    "probe_id",
    "probe_scope",
    "expected",
    "observed",
    "passed",
    "deterministic",
    "governance_note",
)


@dataclass(frozen=True, slots=True)
class _CandidateRecord:
    key: CandidateKey
    row: dict[str, str]
    outcome: dict[str, str]
    fingerprint: SetupFingerprint


@dataclass(frozen=True, slots=True)
class GovernedAdaptiveEvidenceLineageResult:
    report: dict[str, Any]
    candidate_rows: tuple[dict[str, object], ...]
    eligibility_rows: tuple[dict[str, object], ...]
    fingerprint_rows: tuple[dict[str, object], ...]
    assessment_rows: tuple[dict[str, object], ...]
    publication_rows: tuple[dict[str, object], ...]
    source_separation_rows: tuple[dict[str, object], ...]
    comparison_rows: tuple[dict[str, object], ...]
    probe_rows: tuple[dict[str, object], ...]
    paths: tuple[Path, ...]


class GovernedAdaptiveEvidenceLineageEngine:
    """Certify adaptive evidence lineage without publishing adaptive metadata."""

    def run(
        self,
        *,
        b7_certificate: Path,
        output: Path,
        project_root: Path | str = Path("."),
        progress: ProgressCallback | None = None,
    ) -> GovernedAdaptiveEvidenceLineageResult:
        total_steps = 7
        root = Path(project_root)
        _progress(progress, 1, total_steps, "Validating signed HTR-010B7 handoff")
        b7 = validate_governed_setup_matched_evidence_certificate(
            b7_certificate,
            require_ready=True,
            project_root=root,
        )
        _validate_b7_handoff(b7)

        candidate_path = b7_certificate.parent / _B7_CANDIDATE_ARTIFACT
        outcome_path = b7_certificate.parent / _B7_OUTCOME_ARTIFACT
        immutable_paths = {
            "b7_certificate": b7_certificate,
            "b7_candidate_ledger": candidate_path,
            "b7_outcome_ledger": outcome_path,
        }
        immutable_hashes = _hash_paths(immutable_paths)

        _progress(progress, 2, total_steps, "Loading B7 candidate and outcome evidence")
        candidate_input = _csv_rows(candidate_path)
        outcome_input = _csv_rows(outcome_path)
        candidates, input_defects = _candidate_records(candidate_input, outcome_input)

        _progress(progress, 3, total_steps, "Tracing source publication contracts")
        source_hashes = _source_contract_hashes(root)
        source_contract_rows, source_contract_summary = _publication_source_contract()

        _progress(progress, 4, total_steps, "Building point-in-time shadow evidence")
        (
            candidate_rows,
            eligibility_rows,
            assessment_rows,
            publication_rows,
            empirical_defects,
        ) = _shadow_lineage(
            candidates,
            source_contract_rows=source_contract_rows,
        )
        publication_rows = (*source_contract_rows, *publication_rows)

        _progress(progress, 5, total_steps, "Certifying fingerprints and arm parity")
        candidate_fingerprint_rows = _candidate_fingerprint_rows(candidates)
        probe_fingerprint_rows, fingerprint_summary = _fingerprint_contract_probes()
        fingerprint_rows = (*candidate_fingerprint_rows, *probe_fingerprint_rows)
        comparison_rows, unexplained_arm_divergences = _arm_comparison(
            candidate_rows,
            assessment_rows,
        )
        source_separation_rows = _evidence_source_separation()

        _progress(progress, 6, total_steps, "Running deterministic non-vacuity probes")
        probe_rows, probe_summary, probe_defects = _non_vacuity_probes()
        implementation_defects = tuple(
            sorted({*input_defects, *empirical_defects, *probe_defects})
        )
        leakage_count = sum(
            bool(row["eligible"])
            and (
                row["inferred_completion_date"] == ""
                or str(row["inferred_completion_date"])
                >= str(row["candidate_observed_on"])
            )
            for row in eligibility_rows
        )
        empirical_population_count = sum(
            int(cast(int, row["completed_sample_count"])) > 0 for row in assessment_rows
        )
        unexplained_publication_gaps = sum(
            row["scope"] == "CANDIDATE_FIELD"
            and row["publication_status"] == "UNEXPLAINED_PUBLICATION_GAP"
            for row in publication_rows
        )
        unexplained_fingerprint_mismatches = int(
            not bool(fingerprint_summary["current_gap_explained"])
        )
        readiness, blockers = _readiness(
            empirical_population_count=empirical_population_count,
            unexplained_fingerprint_mismatches=unexplained_fingerprint_mismatches,
            unexplained_publication_gaps=unexplained_publication_gaps,
            leakage_count=leakage_count,
            implementation_defects=implementation_defects,
            unexplained_arm_divergences=unexplained_arm_divergences,
        )
        enabled = readiness == B8_READY

        _validate_paths_unchanged(immutable_paths, immutable_hashes)
        if _source_contract_hashes(root) != source_hashes:
            raise ValueError("HTR-010B8 source contract changed during analysis")

        raw_summary = _arm_summary(candidate_rows, assessment_rows, "RAW")
        adjusted_summary = _arm_summary(candidate_rows, assessment_rows, "ADJUSTED")
        report: dict[str, Any] = {
            "contract_version": HTR010B8_CONTRACT_VERSION,
            "b7_contract_version": b7["contract_version"],
            "b7_report_sha256": b7["report_sha256"],
            "b7_certificate_file_sha256": _file_sha256(b7_certificate),
            "b7_candidate_ledger_sha256": _file_sha256(candidate_path),
            "b7_outcome_ledger_sha256": _file_sha256(outcome_path),
            "replay_start": b7["replay_start"],
            "replay_end": b7["replay_end"],
            "session_count": b7["session_count"],
            "source_contract_file_sha256s": source_hashes,
            "b7_institutional_policy_source_sha256s": _mapping_copy(
                b7,
                "institutional_policy_source_sha256s",
            ),
            "b7_frozen_pipeline_component_sha256s": _mapping_copy(
                b7,
                "frozen_pipeline_component_sha256s",
            ),
            "raw_adaptive_summary": raw_summary,
            "adjusted_adaptive_summary": adjusted_summary,
            "publication_contract_summary": source_contract_summary,
            "fingerprint_contract_summary": fingerprint_summary,
            "point_in_time_summary": _point_in_time_summary(
                eligibility_rows,
                assessment_rows,
            ),
            "evidence_source_summary": _source_separation_summary(
                source_separation_rows
            ),
            "probe_summary": probe_summary,
            "adaptive_population_nonempty": empirical_population_count > 0,
            "candidate_population_count": len(candidate_rows),
            "candidate_with_prior_evidence_count": empirical_population_count,
            "point_in_time_leakage_count": leakage_count,
            "fingerprint_contract_mismatch_count": int(
                bool(fingerprint_summary["current_contract_mismatch"])
            ),
            "unexplained_fingerprint_mismatch_count": (
                unexplained_fingerprint_mismatches
            ),
            "publication_gap_count": sum(
                row["scope"] == "CANDIDATE_FIELD"
                and row["publication_status"] != "CURRENTLY_PUBLISHED"
                for row in publication_rows
            ),
            "unexplained_publication_gap_count": unexplained_publication_gaps,
            "implementation_defects": list(implementation_defects),
            "implementation_defect_count": len(implementation_defects),
            "unexplained_adaptive_arm_divergence_count": (unexplained_arm_divergences),
            "readiness_blockers": list(blockers),
            "readiness_decision": readiness,
            "governed_adaptive_evidence_lineage_research_enabled": enabled,
            "governed_setup_matched_evidence_research_enabled": True,
            "adaptive_metadata_publication_enabled": False,
            "approval_policy_change_permitted": False,
            "evidence_threshold_change_permitted": False,
            "fingerprint_matching_change_permitted": False,
            "production_ledger_mutation_enabled": False,
            "synthetic_outcomes_permitted": False,
            "counterfactual_approval_claimed": False,
            "governed_adjusted_trade_research_enabled": False,
            "economic_superiority_claimed": False,
            "live_scoring_enabled": False,
            "recommendation_influence": False,
            "portfolio_policy_influence": False,
            "execution_influence": False,
            "learning_mutation_enabled": False,
            "active_replay_integration": False,
            "production_influence": False,
            "research_scope": RESEARCH_SCOPE,
        }

        _progress(progress, 7, total_steps, "Exporting signed HTR-010B8 artifacts")
        paths = export_governed_adaptive_evidence_lineage(
            report=report,
            candidate_rows=tuple(candidate_rows),
            eligibility_rows=tuple(eligibility_rows),
            fingerprint_rows=tuple(fingerprint_rows),
            assessment_rows=tuple(assessment_rows),
            publication_rows=tuple(publication_rows),
            source_separation_rows=source_separation_rows,
            comparison_rows=comparison_rows,
            probe_rows=probe_rows,
            output=output,
        )
        return GovernedAdaptiveEvidenceLineageResult(
            report=report,
            candidate_rows=tuple(candidate_rows),
            eligibility_rows=tuple(eligibility_rows),
            fingerprint_rows=tuple(fingerprint_rows),
            assessment_rows=tuple(assessment_rows),
            publication_rows=tuple(publication_rows),
            source_separation_rows=source_separation_rows,
            comparison_rows=comparison_rows,
            probe_rows=probe_rows,
            paths=paths,
        )


def _validate_b7_handoff(b7: Mapping[str, object]) -> None:
    if b7.get("contract_version") != HTR010B7_CONTRACT_VERSION:
        raise ValueError("HTR-010B8 requires the HTR-010B7 evidence contract")
    if b7.get("readiness_decision") != B7_READY:
        raise ValueError("HTR-010B8 requires a ready HTR-010B7 certificate")
    if b7.get("production_influence") is not False:
        raise ValueError("HTR-010B7 unexpectedly permits production influence")
    if b7.get("governed_adjusted_trade_research_enabled") is not False:
        raise ValueError("HTR-010B7 unexpectedly permits governed trade research")


def _candidate_records(
    candidate_rows: Sequence[dict[str, str]],
    outcome_rows: Sequence[dict[str, str]],
) -> tuple[tuple[_CandidateRecord, ...], tuple[str, ...]]:
    defects: list[str] = []
    candidates: dict[CandidateKey, dict[str, str]] = {}
    outcomes: dict[CandidateKey, dict[str, str]] = {}
    for label, rows, destination in (
        ("B7_CANDIDATE", candidate_rows, candidates),
        ("B7_OUTCOME", outcome_rows, outcomes),
    ):
        for row in rows:
            key = _candidate_key(row)
            if key in destination:
                defects.append(_key_defect(f"DUPLICATE_{label}", key))
            destination[key] = row
    for key in sorted(set(candidates).difference(outcomes)):
        defects.append(_key_defect("B7_OUTCOME_MISSING", key))
    for key in sorted(set(outcomes).difference(candidates)):
        defects.append(_key_defect("B7_CANDIDATE_MISSING", key))
    records = tuple(
        _CandidateRecord(
            key=key,
            row=candidates[key],
            outcome=outcomes[key],
            fingerprint=_coarse_fingerprint(candidates[key]),
        )
        for key in sorted(set(candidates).intersection(outcomes))
    )
    return records, tuple(sorted(set(defects)))


def _coarse_fingerprint(row: Mapping[str, object]) -> SetupFingerprint:
    return SetupFingerprint(
        final_verdict=str(row.get("final_signal") or "UNKNOWN"),
        setup_type=str(row.get("setup_type") or "UNKNOWN"),
        setup_state=str(row.get("setup_stage") or "UNKNOWN"),
        market_regime="UNKNOWN",
        sector="UNKNOWN",
        trend_regime="UNKNOWN",
        volume_regime="UNKNOWN",
        volatility_regime="UNKNOWN",
        relative_strength_regime="UNKNOWN",
        candle_pattern="UNKNOWN",
        breakout_retracement_state="UNKNOWN",
        dma_alignment="UNKNOWN",
        data_completeness_level="UNKNOWN",
    )


def _publication_source_contract() -> tuple[
    tuple[dict[str, object], ...], dict[str, object]
]:
    consumer_source = inspect.getsource(candidate_from_recommendation)
    producer_source = inspect.getsource(RecommendationEngine._build_one)
    orchestrator_source = inspect.getsource(IntelligenceApplicationService.run)
    invokes_adaptive = (
        "AdaptiveLearning" in orchestrator_source or "adaptive_" in orchestrator_source
    )
    rows: list[dict[str, object]] = []
    for metadata_key, adaptive_field, value_type in _ADAPTIVE_METADATA_CONTRACT:
        consumer = metadata_key in consumer_source
        producer = metadata_key in producer_source
        if consumer and not producer and not invokes_adaptive:
            status = "ATTRIBUTED_PUBLICATION_GAP"
            root_cause = "ADAPTIVE_ASSESSMENT_NOT_INVOKED|METADATA_KEY_NOT_PUBLISHED"
            explained = True
        elif consumer and not producer:
            status = "ATTRIBUTED_PUBLICATION_GAP"
            root_cause = "METADATA_KEY_NOT_PUBLISHED"
            explained = True
        elif consumer and producer:
            status = "PUBLICATION_CONTRACT_PRESENT"
            root_cause = "NONE"
            explained = True
        else:
            status = "UNEXPLAINED_PUBLICATION_GAP"
            root_cause = "CONSUMER_CONTRACT_UNAVAILABLE"
            explained = False
        rows.append(
            {
                "scope": "SOURCE_CONTRACT",
                "price_view": "",
                "observed_on": "",
                "symbol": "",
                "metadata_key": metadata_key,
                "adaptive_field": adaptive_field,
                "value_type": value_type,
                "shadow_computed_value": "",
                "currently_published_value": "",
                "institutional_observed_value": "",
                "consumer_expects_key": consumer,
                "producer_publishes_key": producer,
                "orchestrator_invokes_adaptive_assessment": invokes_adaptive,
                "publication_status": status,
                "root_cause": root_cause,
                "gap_explained": explained,
            }
        )
    summary: dict[str, object] = {
        "metadata_key_count": len(rows),
        "consumer_contract_key_count": sum(
            bool(row["consumer_expects_key"]) for row in rows
        ),
        "producer_publication_key_count": sum(
            bool(row["producer_publishes_key"]) for row in rows
        ),
        "orchestrator_invokes_adaptive_assessment": invokes_adaptive,
        "attributed_gap_count": sum(
            row["publication_status"] == "ATTRIBUTED_PUBLICATION_GAP" for row in rows
        ),
        "unexplained_gap_count": sum(
            row["publication_status"] == "UNEXPLAINED_PUBLICATION_GAP" for row in rows
        ),
        "current_publication_bridge_present": all(
            row["publication_status"] == "PUBLICATION_CONTRACT_PRESENT" for row in rows
        ),
    }
    return tuple(rows), summary


def _shadow_lineage(
    candidates: Sequence[_CandidateRecord],
    *,
    source_contract_rows: Sequence[dict[str, object]],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    tuple[dict[str, object], ...],
    tuple[str, ...],
]:
    defects: list[str] = []
    candidate_rows: list[dict[str, object]] = []
    eligibility_rows: list[dict[str, object]] = []
    assessment_rows: list[dict[str, object]] = []
    publication_rows: list[dict[str, object]] = []
    contract_by_key = {str(row["metadata_key"]): row for row in source_contract_rows}
    grouped: dict[tuple[str, str], list[_CandidateRecord]] = defaultdict(list)
    for record in candidates:
        grouped[(record.key[0], record.fingerprint.key)].append(record)

    for record in sorted(candidates, key=lambda item: item.key):
        view, observed_on, symbol = record.key
        matching = tuple(grouped[(view, record.fingerprint.key)])
        samples: list[LearningOutcomeSample] = []
        eventual_completed = 0
        for outcome_record in sorted(matching, key=lambda item: item.key):
            outcome = outcome_record.outcome
            status = str(outcome.get("forward_outcome_status") or "")
            completed = status.startswith("COMPLETED")
            if completed:
                eventual_completed += 1
            completion_date = _completion_date(outcome_record)
            fingerprint_match = outcome_record.fingerprint.key == record.fingerprint.key
            same_arm = outcome_record.key[0] == view
            eligible, reason = _outcome_eligibility(
                candidate_date=observed_on,
                outcome_status=status,
                inferred_completion_date=completion_date,
                fingerprint_match=fingerprint_match,
                same_price_arm=same_arm,
            )
            eligibility_rows.append(
                {
                    "price_view": view,
                    "candidate_observed_on": observed_on,
                    "candidate_symbol": symbol,
                    "candidate_fingerprint_key": record.fingerprint.key,
                    "outcome_observed_on": outcome_record.key[1],
                    "outcome_symbol": outcome_record.key[2],
                    "outcome_status": status,
                    "outcome_holding_period_days": _optional_int(
                        outcome.get("holding_period_days")
                    ),
                    "inferred_completion_date": completion_date,
                    "fingerprint_match": fingerprint_match,
                    "same_price_arm": same_arm,
                    "completed": completed,
                    "eligible": eligible,
                    "eligibility_reason": reason,
                    "realized_r": _optional_decimal(outcome.get("realized_r")),
                }
            )
            if eligible:
                samples.append(
                    _learning_sample(
                        record.fingerprint,
                        outcome_record.outcome,
                    )
                )
        assessment = _adaptive_assessment(
            fingerprint=record.fingerprint,
            samples=tuple(samples),
            base_confidence="LOW",
        )
        assessment_row = {
            "price_view": view,
            "observed_on": observed_on,
            "symbol": symbol,
            "fingerprint_key": record.fingerprint.key,
            "base_confidence": "LOW",
            "completed_sample_count": assessment["completed_sample_count"],
            "pending_sample_count": assessment["pending_sample_count"],
            "not_triggered_count": assessment["not_triggered_count"],
            "win_count": assessment["win_count"],
            "loss_count": assessment["loss_count"],
            "expectancy": assessment["expectancy"],
            "prior_win_probability": assessment["prior_win_probability"],
            "posterior_win_probability": assessment["posterior_win_probability"],
            "lower_confidence_bound": assessment["lower_confidence_bound"],
            "upper_confidence_bound": assessment["upper_confidence_bound"],
            "evidence_strength": assessment["evidence_strength"],
            "adjusted_confidence": assessment["adjusted_confidence"],
            "confidence_adjustment_reason": assessment["confidence_adjustment_reason"],
            "eventual_completed_match_count": eventual_completed,
            "point_in_time_contract_complete": True,
        }
        assessment_rows.append(assessment_row)
        shadow_values = {
            "adaptive_adjusted_confidence": assessment["adjusted_confidence"],
            "adaptive_evidence_strength": assessment["evidence_strength"],
            "adaptive_posterior_probability": assessment["posterior_win_probability"],
            "adaptive_expectancy": assessment["expectancy"],
            "adaptive_sample_count": assessment["completed_sample_count"],
        }
        current_values = {
            "adaptive_adjusted_confidence": "",
            "adaptive_evidence_strength": record.row.get("evidence_strength") or "",
            "adaptive_posterior_probability": (
                record.row.get("posterior_probability") or ""
            ),
            "adaptive_expectancy": record.row.get("expectancy") or "",
            "adaptive_sample_count": record.row.get("evidence_sample_count") or "",
        }
        candidate_publication_rows: list[dict[str, object]] = []
        for metadata_key, adaptive_field, value_type in _ADAPTIVE_METADATA_CONTRACT:
            contract = contract_by_key[metadata_key]
            current = current_values[metadata_key]
            if current not in {"", "UNAVAILABLE", "None", "none"}:
                publication_status = "CURRENTLY_PUBLISHED"
                root_cause = "NONE"
                explained = True
            elif bool(contract["gap_explained"]):
                publication_status = "ATTRIBUTED_PUBLICATION_GAP"
                root_cause = str(contract["root_cause"])
                explained = True
            else:
                publication_status = "UNEXPLAINED_PUBLICATION_GAP"
                root_cause = "PUBLICATION_PATH_UNEXPLAINED"
                explained = False
            candidate_publication_rows.append(
                {
                    "scope": "CANDIDATE_FIELD",
                    "price_view": view,
                    "observed_on": observed_on,
                    "symbol": symbol,
                    "metadata_key": metadata_key,
                    "adaptive_field": adaptive_field,
                    "value_type": value_type,
                    "shadow_computed_value": shadow_values[metadata_key],
                    "currently_published_value": current,
                    "institutional_observed_value": current,
                    "consumer_expects_key": contract["consumer_expects_key"],
                    "producer_publishes_key": contract["producer_publishes_key"],
                    "orchestrator_invokes_adaptive_assessment": contract[
                        "orchestrator_invokes_adaptive_assessment"
                    ],
                    "publication_status": publication_status,
                    "root_cause": root_cause,
                    "gap_explained": explained,
                }
            )
        publication_rows.extend(candidate_publication_rows)
        gaps = sum(
            row["publication_status"] != "CURRENTLY_PUBLISHED"
            for row in candidate_publication_rows
        )
        all_explained = all(
            bool(row["gap_explained"]) for row in candidate_publication_rows
        )
        primary = (
            "POINT_IN_TIME_ADAPTIVE_EVIDENCE_AVAILABLE_BUT_UNPUBLISHED"
            if int(cast(int, assessment["completed_sample_count"])) > 0
            else "NO_POINT_IN_TIME_ELIGIBLE_OUTCOMES_AND_PUBLICATION_BRIDGE_ABSENT"
        )
        candidate_rows.append(
            {
                "price_view": view,
                "observed_on": observed_on,
                "symbol": symbol,
                "final_signal": record.row.get("final_signal") or "",
                "setup_type": record.row.get("setup_type") or "",
                "setup_stage": record.row.get("setup_stage") or "",
                "fingerprint_key": record.fingerprint.key,
                "eligible_completed_sample_count": assessment["completed_sample_count"],
                "eventual_completed_match_count": eventual_completed,
                "posterior_win_probability": assessment["posterior_win_probability"],
                "expectancy": assessment["expectancy"],
                "evidence_strength": assessment["evidence_strength"],
                "adjusted_confidence": assessment["adjusted_confidence"],
                "current_published_sample_count": current_values[
                    "adaptive_sample_count"
                ],
                "current_published_posterior": current_values[
                    "adaptive_posterior_probability"
                ],
                "current_published_expectancy": current_values["adaptive_expectancy"],
                "current_published_evidence_strength": current_values[
                    "adaptive_evidence_strength"
                ],
                "publication_gap_field_count": gaps,
                "publication_gap_fully_attributed": all_explained,
                "primary_lineage_finding": primary,
                "point_in_time_contract_complete": True,
                "input_fingerprint": record.row.get("input_fingerprint") or "",
            }
        )
    return (
        candidate_rows,
        eligibility_rows,
        assessment_rows,
        tuple(publication_rows),
        tuple(sorted(set(defects))),
    )


def _completion_date(record: _CandidateRecord) -> date | None:
    status = str(record.outcome.get("forward_outcome_status") or "")
    if not status.startswith("COMPLETED"):
        return None
    holding = _optional_int(record.outcome.get("holding_period_days"))
    if holding is None or holding < 0:
        return None
    return record.key[1] + timedelta(days=holding)


def _outcome_eligibility(
    *,
    candidate_date: date,
    outcome_status: str,
    inferred_completion_date: date | None,
    fingerprint_match: bool,
    same_price_arm: bool,
) -> tuple[bool, str]:
    if not same_price_arm:
        return False, "OPPOSITE_PRICE_ARM_EXCLUDED"
    if not fingerprint_match:
        return False, "FINGERPRINT_MISMATCH_EXCLUDED"
    if not outcome_status.startswith("COMPLETED"):
        return False, "OUTCOME_NOT_COMPLETED"
    if inferred_completion_date is None:
        return False, "COMPLETION_DATE_UNAVAILABLE"
    if inferred_completion_date >= candidate_date:
        return False, "SAME_DATE_OR_FUTURE_COMPLETION_EXCLUDED"
    return True, "ELIGIBLE_PRIOR_COMPLETED_MATCH"


def _learning_sample(
    fingerprint: SetupFingerprint,
    outcome: Mapping[str, object],
) -> LearningOutcomeSample:
    status = str(outcome.get("forward_outcome_status") or "")
    exit_reason = str(outcome.get("exit_reason") or "")
    realized_r = _optional_decimal(outcome.get("realized_r"))
    won = _boolean_optional(outcome.get("won"))
    if won is None:
        won = status == "COMPLETED_WIN"
    return LearningOutcomeSample(
        fingerprint=fingerprint,
        completed=True,
        win=won,
        pending=False,
        not_triggered=False,
        target_1_hit="TARGET" in exit_reason.upper(),
        target_2_hit=False,
        target_3_hit=False,
        stop_hit="STOP" in exit_reason.upper(),
        realized_r=realized_r,
        holding_period_days=_optional_int(outcome.get("holding_period_days")),
    )


def _adaptive_assessment(
    *,
    fingerprint: SetupFingerprint,
    samples: tuple[LearningOutcomeSample, ...],
    base_confidence: str,
) -> dict[str, object]:
    engine = AdaptiveLearningEngine()
    if samples:
        report = engine.build_report(
            entries=(),
            outcomes=(),
            historical_samples=samples,
        )
        statistics = next(
            (
                item
                for item in report.fingerprint_statistics
                if item.fingerprint.key == fingerprint.key
            ),
            _zero_statistics(fingerprint),
        )
    else:
        statistics = _zero_statistics(fingerprint)
    bayesian = engine.bayesian_calibration(statistics)
    confidence = engine.recalibrate_confidence(
        base_confidence=base_confidence,
        statistics=statistics,
        bayesian=bayesian,
    )
    return {
        "completed_sample_count": statistics.completed_trade_count,
        "pending_sample_count": statistics.pending_count,
        "not_triggered_count": statistics.not_triggered_count,
        "win_count": statistics.win_count,
        "loss_count": statistics.loss_count,
        "expectancy": statistics.expectancy,
        "prior_win_probability": bayesian.prior_win_probability,
        "posterior_win_probability": bayesian.posterior_win_probability,
        "lower_confidence_bound": bayesian.lower_confidence_bound,
        "upper_confidence_bound": bayesian.upper_confidence_bound,
        "evidence_strength": statistics.evidence_strength.value,
        "adjusted_confidence": confidence.adjusted_confidence,
        "confidence_adjustment_reason": confidence.adjustment_reason,
    }


def _zero_statistics(fingerprint: SetupFingerprint) -> FingerprintStatistics:
    return FingerprintStatistics(
        fingerprint=fingerprint,
        sample_count=0,
        completed_trade_count=0,
        win_count=0,
        loss_count=0,
        pending_count=0,
        not_triggered_count=0,
        target_1_hit_rate=None,
        target_2_hit_rate=None,
        target_3_hit_rate=None,
        stop_hit_rate=None,
        average_r=None,
        expectancy=None,
        average_holding_period=None,
        max_drawdown_proxy=None,
        evidence_strength=EvidenceStrength.INSUFFICIENT,
    )


def _candidate_fingerprint_rows(
    candidates: Sequence[_CandidateRecord],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "scope": "B7_CANDIDATE_COARSE_CONTRACT",
            "price_view": record.key[0],
            "observed_on": record.key[1],
            "symbol": record.key[2],
            "recommendation_fingerprint_key": record.fingerprint.key,
            "ledger_fingerprint_key": record.fingerprint.key,
            "adaptive_lookup_fingerprint_key": record.fingerprint.key,
            "observable_parity": True,
            "full_parity_certified": False,
            "mismatch_codes": (),
            "unobservable_dimensions": _B7_UNOBSERVABLE_FINGERPRINT_DIMENSIONS,
            "gap_explained": True,
            "contract_status": "COARSE_PARITY_ONLY_B7_DID_NOT_EXPORT_FULL_DIMENSIONS",
        }
        for record in sorted(candidates, key=lambda item: item.key)
    )


def _fingerprint_contract_probes() -> tuple[
    tuple[dict[str, object], ...], dict[str, object]
]:
    recommendation = _probe_recommendation()
    recommendation_fingerprint = fingerprint_from_recommendation(
        cast(Any, recommendation),
        market_regime="BULL",
    )
    current_entry = _probe_ledger_entry(include_missing_dimensions=False)
    complete_entry = _probe_ledger_entry(include_missing_dimensions=True)
    current_fingerprint = fingerprint_from_ledger_entry(current_entry)
    complete_fingerprint = fingerprint_from_ledger_entry(complete_entry)
    current_codes = _fingerprint_mismatch_codes(
        recommendation_fingerprint,
        current_fingerprint,
    )
    complete_codes = _fingerprint_mismatch_codes(
        recommendation_fingerprint,
        complete_fingerprint,
    )
    expected = {
        "CANDLE_PATTERN_NOT_RECORDED",
        "RETRACEMENT_STATE_NOT_RECORDED",
    }
    current_explained = set(current_codes) == expected
    complete_parity = not complete_codes
    rows = (
        {
            "scope": "CURRENT_RECORDER_CONTRACT_PROBE",
            "price_view": "",
            "observed_on": date(2026, 1, 10),
            "symbol": "PROBE",
            "recommendation_fingerprint_key": recommendation_fingerprint.key,
            "ledger_fingerprint_key": current_fingerprint.key,
            "adaptive_lookup_fingerprint_key": current_fingerprint.key,
            "observable_parity": False,
            "full_parity_certified": False,
            "mismatch_codes": current_codes,
            "unobservable_dimensions": (),
            "gap_explained": current_explained,
            "contract_status": (
                "ATTRIBUTED_RECORDER_FINGERPRINT_GAP"
                if current_explained
                else "UNEXPLAINED_FINGERPRINT_CONTRACT_MISMATCH"
            ),
        },
        {
            "scope": "COMPLETE_SNAPSHOT_PARITY_PROBE",
            "price_view": "",
            "observed_on": date(2026, 1, 10),
            "symbol": "PROBE",
            "recommendation_fingerprint_key": recommendation_fingerprint.key,
            "ledger_fingerprint_key": complete_fingerprint.key,
            "adaptive_lookup_fingerprint_key": complete_fingerprint.key,
            "observable_parity": complete_parity,
            "full_parity_certified": complete_parity,
            "mismatch_codes": complete_codes,
            "unobservable_dimensions": (),
            "gap_explained": complete_parity,
            "contract_status": (
                "PARITY_REACHABLE_WITH_COMPLETE_SNAPSHOT"
                if complete_parity
                else "COMPLETE_SNAPSHOT_PARITY_FAILED"
            ),
        },
    )
    summary = {
        "current_contract_mismatch": bool(current_codes),
        "current_mismatch_codes": list(current_codes),
        "current_gap_explained": current_explained,
        "complete_snapshot_parity_reachable": complete_parity,
        "complete_snapshot_mismatch_codes": list(complete_codes),
        "adaptive_lookup_uses_ledger_fingerprint": True,
        "matching_policy_change_permitted": False,
    }
    return rows, summary


def _probe_recommendation() -> SimpleNamespace:
    return SimpleNamespace(
        final_signal="BUY",
        setup_name="MOMENTUM CONTINUATION",
        setup_stage="ENTRY_READY",
        price_evidence=SimpleNamespace(
            trend_state="UPTREND",
            breakout_state="BREAKOUT",
            retracement_state="HEALTHY",
        ),
        volume_evidence=SimpleNamespace(volume_score="0.80"),
        trade_plan=SimpleNamespace(
            atr_value="2",
            relative_volume="1.20",
            candle_pattern="HAMMER",
            dma_20_invalidation="120",
            dma_50="110",
            dma_200="100",
        ),
        metadata={"sector": "ENERGY", "data_quality": "COMPLETE"},
    )


def _probe_ledger_entry(
    *,
    include_missing_dimensions: bool,
) -> RecommendationLedgerEntry:
    snapshot = {
        "price_trend": "UPTREND",
        "price_structure": "CONSTRUCTIVE",
        "price_breakout": "BREAKOUT",
        "price_score": "0.80",
        "volume_score": "0.80",
        "relative_volume": "1.20",
        "dma_20": "120",
        "dma_50": "110",
        "dma_200": "100",
        "atr": "2",
    }
    if include_missing_dimensions:
        snapshot["candle_pattern"] = "HAMMER"
        snapshot["retracement_state"] = "HEALTHY"
    return RecommendationLedgerEntry(
        recommendation_id=(
            "probe-complete" if include_missing_dimensions else "probe-current"
        ),
        generated_at=datetime.fromisoformat("2026-01-10T00:00:00+00:00"),
        symbol="PROBE",
        final_verdict="BUY",
        confidence="LOW",
        score=Decimal("80"),
        setup_type="MOMENTUM CONTINUATION",
        setup_state="ENTRY_READY",
        entry_zone_low=None,
        entry_zone_high=None,
        confirmation_entry=None,
        stop_loss=None,
        target_1=None,
        target_2=None,
        target_3=None,
        trailing_stop_strategy=None,
        holding_period=None,
        market_regime="BULL",
        sector="ENERGY",
        key_indicator_snapshot=snapshot,
        statistical_edge_snapshot={},
        data_completeness_snapshot={"data_quality": "COMPLETE"},
        source_run_id="HTR010B8-PROBE",
        candle_pattern="HAMMER",
    )


def _fingerprint_mismatch_codes(
    expected: SetupFingerprint,
    observed: SetupFingerprint,
) -> tuple[str, ...]:
    codes: list[str] = []
    for dimension in _FINGERPRINT_DIMENSIONS:
        left = str(expected.dimensions[dimension])
        right = str(observed.dimensions[dimension])
        if left == right:
            continue
        if dimension == "candle_pattern" and right == "UNKNOWN":
            codes.append("CANDLE_PATTERN_NOT_RECORDED")
        elif (
            dimension == "breakout_retracement_state"
            and left.endswith("+HEALTHY")
            and right == "BREAKOUT"
        ):
            codes.append("RETRACEMENT_STATE_NOT_RECORDED")
        else:
            codes.append(f"{dimension.upper()}_MISMATCH")
    return tuple(codes)


def _evidence_source_separation() -> tuple[dict[str, object], ...]:
    return (
        {
            "evidence_source": "ADAPTIVE_LEARNING",
            "matching_definition": (
                "Exact SetupFingerprint over completed recommendation outcomes"
            ),
            "sample_unit": "completed recommendation outcome",
            "time_boundary": "completion date strictly before candidate date",
            "primary_consumer": "institutional candidate adaptive fields",
            "equivalent_to_adaptive_learning": True,
            "cross_source_merge_permitted": False,
            "governance_note": "B8 shadow source; publication remains disabled.",
        },
        {
            "evidence_source": "STRATEGY_REGIME_HISTORICAL_EDGE",
            "matching_definition": (
                "indicator set plus market regime in strategy-regime repository"
            ),
            "sample_unit": "strategy holding-period outcome",
            "time_boundary": "latest stored strategy-regime run",
            "primary_consumer": "recommendation historical-edge score adjustment",
            "equivalent_to_adaptive_learning": False,
            "cross_source_merge_permitted": False,
            "governance_note": (
                "Separate evidence definition; no substitution permitted."
            ),
        },
        {
            "evidence_source": "TRADE_STRATEGY_STATISTICAL_EDGE",
            "matching_definition": "generic local-bar trend, volume and DMA matcher",
            "sample_unit": "simulated matched historical bar",
            "time_boundary": "candidate historical price window",
            "primary_consumer": "trade-strategy playbook",
            "equivalent_to_adaptive_learning": False,
            "cross_source_merge_permitted": False,
            "governance_note": "May not populate adaptive_sample_count.",
        },
        {
            "evidence_source": "B7_GOVERNED_FORWARD_OUTCOME",
            "matching_definition": "governed candidate setup and frozen trade plan",
            "sample_unit": "price-arm candidate outcome row",
            "time_boundary": (
                "future label after recorded decision; "
                "B8 re-applies point-in-time cutoff"
            ),
            "primary_consumer": "B7/B8 diagnostic research",
            "equivalent_to_adaptive_learning": False,
            "cross_source_merge_permitted": False,
            "governance_note": (
                "RAW and ADJUSTED rows are paired views, not independent evidence."
            ),
        },
    )


def _arm_comparison(
    candidate_rows: Sequence[dict[str, object]],
    assessment_rows: Sequence[dict[str, object]],
) -> tuple[tuple[dict[str, object], ...], int]:
    candidates = {
        (str(row["price_view"]), str(row["observed_on"]), str(row["symbol"])): row
        for row in candidate_rows
    }
    assessments = {
        (str(row["price_view"]), str(row["observed_on"]), str(row["symbol"])): row
        for row in assessment_rows
    }
    paired_keys = sorted(
        {(observed_on, symbol) for _, observed_on, symbol in candidates}
    )
    rows: list[dict[str, object]] = []
    unexplained = 0
    for observed_on, symbol in paired_keys:
        raw_key = ("RAW", observed_on, symbol)
        adjusted_key = ("ADJUSTED", observed_on, symbol)
        raw = candidates.get(raw_key)
        adjusted = candidates.get(adjusted_key)
        raw_assessment = assessments.get(raw_key)
        adjusted_assessment = assessments.get(adjusted_key)
        codes: list[str] = []
        if raw is None:
            codes.append("RAW_CANDIDATE_MISSING")
        if adjusted is None:
            codes.append("ADJUSTED_CANDIDATE_MISSING")
        if raw is not None and adjusted is not None:
            for code, field in (
                ("FINGERPRINT_CHANGED", "fingerprint_key"),
                ("SAMPLE_COUNT_CHANGED", "eligible_completed_sample_count"),
                ("POSTERIOR_CHANGED", "posterior_win_probability"),
                ("EXPECTANCY_CHANGED", "expectancy"),
                ("PUBLICATION_GAP_CHANGED", "publication_gap_field_count"),
            ):
                if raw.get(field) != adjusted.get(field):
                    codes.append(code)
        input_changed = bool(
            raw is not None
            and adjusted is not None
            and raw.get("input_fingerprint") != adjusted.get("input_fingerprint")
        )
        explained = not codes or input_changed
        if codes and not explained:
            unexplained += 1
        rows.append(
            {
                "observed_on": observed_on,
                "symbol": symbol,
                "raw_present": raw is not None,
                "adjusted_present": adjusted is not None,
                "raw_fingerprint_key": "" if raw is None else raw["fingerprint_key"],
                "adjusted_fingerprint_key": (
                    "" if adjusted is None else adjusted["fingerprint_key"]
                ),
                "raw_completed_sample_count": (
                    ""
                    if raw_assessment is None
                    else raw_assessment["completed_sample_count"]
                ),
                "adjusted_completed_sample_count": (
                    ""
                    if adjusted_assessment is None
                    else adjusted_assessment["completed_sample_count"]
                ),
                "raw_posterior": (
                    ""
                    if raw_assessment is None
                    else raw_assessment["posterior_win_probability"]
                ),
                "adjusted_posterior": (
                    ""
                    if adjusted_assessment is None
                    else adjusted_assessment["posterior_win_probability"]
                ),
                "raw_expectancy": (
                    "" if raw_assessment is None else raw_assessment["expectancy"]
                ),
                "adjusted_expectancy": (
                    ""
                    if adjusted_assessment is None
                    else adjusted_assessment["expectancy"]
                ),
                "raw_publication_gap_fields": (
                    "" if raw is None else raw["publication_gap_field_count"]
                ),
                "adjusted_publication_gap_fields": (
                    "" if adjusted is None else adjusted["publication_gap_field_count"]
                ),
                "input_fingerprint_changed": input_changed,
                "difference_codes": tuple(codes),
                "explained": explained,
            }
        )
    return tuple(rows), unexplained


def _non_vacuity_probes() -> tuple[
    tuple[dict[str, object], ...],
    dict[str, object],
    tuple[str, ...],
]:
    first = _probe_pass()
    second = _probe_pass()
    rows: list[dict[str, object]] = []
    defects: list[str] = []
    for left, right in zip(first, second, strict=True):
        row = dict(left)
        row["deterministic"] = left == right
        if not bool(row["passed"]):
            defects.append(f"ADAPTIVE_LINEAGE_PROBE_FAILED@{row['probe_id']}")
        if left != right:
            defects.append(f"ADAPTIVE_LINEAGE_PROBE_NONDETERMINISTIC@{row['probe_id']}")
        rows.append(row)
    summary: dict[str, object] = {
        "probe_count": len(rows),
        "passed_probe_count": sum(bool(row["passed"]) for row in rows),
        "failed_probe_count": sum(not bool(row["passed"]) for row in rows),
        "deterministic": first == second,
    }
    return tuple(rows), summary, tuple(sorted(set(defects)))


def _probe_pass() -> tuple[dict[str, object], ...]:
    candidate_date = date(2026, 1, 10)
    fp = _probe_fingerprint()
    other_fp = SetupFingerprint(
        **{
            **dict(fp.dimensions),
            "sector": "BANKS",
        }
    )
    eligibility_cases = (
        (
            "PRIOR_COMPLETION_INCLUDED",
            "COMPLETED_WIN",
            date(2026, 1, 9),
            True,
            True,
            True,
        ),
        (
            "SAME_DATE_COMPLETION_EXCLUDED",
            "COMPLETED_WIN",
            date(2026, 1, 10),
            True,
            True,
            False,
        ),
        (
            "FUTURE_COMPLETION_EXCLUDED",
            "COMPLETED_WIN",
            date(2026, 1, 11),
            True,
            True,
            False,
        ),
        (
            "PENDING_OUTCOME_EXCLUDED",
            "PENDING_END_OF_DATA",
            None,
            True,
            True,
            False,
        ),
        (
            "FINGERPRINT_MISMATCH_EXCLUDED",
            "COMPLETED_WIN",
            date(2026, 1, 9),
            False,
            True,
            False,
        ),
        (
            "OPPOSITE_ARM_EXCLUDED",
            "COMPLETED_WIN",
            date(2026, 1, 9),
            True,
            False,
            False,
        ),
    )
    rows: list[dict[str, object]] = []
    for (
        probe_id,
        status,
        completion,
        fingerprint_match,
        same_arm,
        expected,
    ) in eligibility_cases:
        observed, _ = _outcome_eligibility(
            candidate_date=candidate_date,
            outcome_status=status,
            inferred_completion_date=completion,
            fingerprint_match=fingerprint_match,
            same_price_arm=same_arm,
        )
        rows.append(
            _probe_row(
                probe_id,
                "POINT_IN_TIME_ELIGIBILITY",
                expected,
                observed,
                (
                    "Only strictly prior completed exact-fingerprint "
                    "same-arm outcomes qualify."
                ),
            )
        )

    one_sample = LearningOutcomeSample(
        fingerprint=fp,
        completed=True,
        win=True,
        pending=False,
        not_triggered=False,
        target_1_hit=True,
        target_2_hit=False,
        target_3_hit=False,
        stop_hit=False,
        realized_r=Decimal("2"),
        holding_period_days=5,
    )
    assessment = _adaptive_assessment(
        fingerprint=fp,
        samples=(one_sample,),
        base_confidence="LOW",
    )
    rows.append(
        _probe_row(
            "ONE_SAMPLE_SHADOW_ASSESSMENT",
            "ADAPTIVE_ENGINE",
            1,
            assessment["completed_sample_count"],
            "Existing AdaptiveLearningEngine must consume the eligible shadow sample.",
        )
    )
    zero = _adaptive_assessment(
        fingerprint=other_fp,
        samples=(),
        base_confidence="LOW",
    )
    rows.append(
        _probe_row(
            "ZERO_SAMPLE_FAIL_CLOSED",
            "ADAPTIVE_ENGINE",
            0,
            zero["completed_sample_count"],
            "No synthetic adaptive samples may be created.",
        )
    )
    fingerprint_rows, fingerprint_summary = _fingerprint_contract_probes()
    rows.append(
        _probe_row(
            "CURRENT_RECORDER_GAP_ATTRIBUTED",
            "FINGERPRINT_CONTRACT",
            True,
            fingerprint_summary["current_gap_explained"],
            "Current recorder omissions must be detected rather than normalized away.",
        )
    )
    rows.append(
        _probe_row(
            "COMPLETE_SNAPSHOT_PARITY_REACHABLE",
            "FINGERPRINT_CONTRACT",
            True,
            fingerprint_summary["complete_snapshot_parity_reachable"],
            (
                "Exact parity must be demonstrably reachable without "
                "changing matching policy."
            ),
        )
    )
    metadata = {
        "adaptive_adjusted_confidence": "HIGH",
        "adaptive_evidence_strength": "strong",
        "adaptive_posterior_probability": "0.70",
        "adaptive_expectancy": "0.25",
        "adaptive_sample_count": "42",
        "price": "100",
        "volume": "100000",
        "average_volume": "90000",
        "data_quality": "COMPLETE",
        "sector": "ENERGY",
    }
    candidate = candidate_from_recommendation(
        cast(Any, _probe_institutional_recommendation(metadata))
    )
    round_trip = (
        candidate.adjusted_confidence == "HIGH"
        and candidate.evidence_strength == "strong"
        and candidate.posterior_probability == Decimal("0.70")
        and candidate.expectancy == Decimal("0.25")
        and candidate.evidence_sample_count == 42
    )
    rows.append(
        _probe_row(
            "METADATA_CONSUMER_ROUND_TRIP",
            "PUBLICATION_CONTRACT",
            True,
            round_trip,
            (
                "Institutional consumer must parse the complete adaptive "
                "metadata contract."
            ),
        )
    )
    malformed = dict(metadata)
    malformed["adaptive_posterior_probability"] = "bad"
    malformed["adaptive_expectancy"] = "bad"
    malformed["adaptive_sample_count"] = "bad"
    malformed_candidate = candidate_from_recommendation(
        cast(Any, _probe_institutional_recommendation(malformed))
    )
    malformed_closed = (
        malformed_candidate.posterior_probability is None
        and malformed_candidate.expectancy is None
        and malformed_candidate.evidence_sample_count is None
    )
    rows.append(
        _probe_row(
            "MALFORMED_METADATA_FAILS_CLOSED",
            "PUBLICATION_CONTRACT",
            True,
            malformed_closed,
            "Malformed adaptive numeric values must remain unavailable.",
        )
    )
    rows.append(
        _probe_row(
            "FINGERPRINT_ONE_DIMENSION_DIFFERENCE",
            "FINGERPRINT_CONTRACT",
            False,
            fp.key == other_fp.key,
            "One fingerprint dimension must isolate the adaptive cohort.",
        )
    )
    rows.append(
        _probe_row(
            "PROBE_ROWS_NONEMPTY",
            "NON_VACUITY",
            True,
            bool(fingerprint_rows),
            "The fingerprint contract probe must produce auditable evidence.",
        )
    )
    return tuple(rows)


def _probe_fingerprint() -> SetupFingerprint:
    return SetupFingerprint(
        final_verdict="BUY",
        setup_type="MOMENTUM CONTINUATION",
        setup_state="ENTRY_READY",
        market_regime="BULL",
        sector="ENERGY",
        trend_regime="UPTREND",
        volume_regime="STRONG",
        volatility_regime="NORMAL",
        relative_strength_regime="STRONG",
        candle_pattern="HAMMER",
        breakout_retracement_state="BREAKOUT+HEALTHY",
        dma_alignment="BULLISH",
        data_completeness_level="COMPLETE",
    )


def _probe_institutional_recommendation(
    metadata: Mapping[str, str],
) -> SimpleNamespace:
    return SimpleNamespace(
        metadata=dict(metadata),
        symbol="PROBE",
        final_signal="BUY",
        confidence="MEDIUM",
        final_score=Decimal("90"),
        risk_reward_ratio=Decimal("2"),
        entry_price=Decimal("100"),
        entry_zone_high=Decimal("100"),
        initial_stop_loss=Decimal("95"),
        target_1=Decimal("110"),
        target_2=Decimal("115"),
        target_3=Decimal("120"),
        setup_quality_label="A",
        unavailable_reasons=(),
        setup_stage="ENTRY_READY",
        trigger_status=SimpleNamespace(value="TRIGGER_CONFIRMED"),
        setup_entry_ready=True,
        historical_bar_count=250,
        support_level_used=Decimal("98"),
        swing_low=Decimal("90"),
        swing_high=Decimal("110"),
        trade_plan=SimpleNamespace(
            dma_20_invalidation=Decimal("97"),
            atr_value=Decimal("2"),
        ),
        opposing_evidence=(),
        price_evidence=SimpleNamespace(
            breakout_state="BREAKOUT",
            structure_state="CONSTRUCTIVE",
        ),
        volume_evidence=SimpleNamespace(selloff_volume_penalty=Decimal("0.10")),
        candle_confirmation="CONFIRMS",
    )


def _probe_row(
    probe_id: str,
    scope: str,
    expected: object,
    observed: object,
    note: str,
) -> dict[str, object]:
    return {
        "probe_id": probe_id,
        "probe_scope": scope,
        "expected": expected,
        "observed": observed,
        "passed": observed == expected,
        "governance_note": note,
    }


def _readiness(
    *,
    empirical_population_count: int,
    unexplained_fingerprint_mismatches: int,
    unexplained_publication_gaps: int,
    leakage_count: int,
    implementation_defects: Sequence[str],
    unexplained_arm_divergences: int,
) -> tuple[str, tuple[str, ...]]:
    if implementation_defects:
        return B8_BLOCKED_DEFECT, tuple(sorted(set(implementation_defects)))
    if leakage_count:
        return B8_BLOCKED_LEAKAGE, (f"POINT_IN_TIME_LEAKAGE_COUNT={leakage_count}",)
    if unexplained_fingerprint_mismatches:
        return B8_BLOCKED_FINGERPRINT, (
            f"UNEXPLAINED_FINGERPRINT_MISMATCHES={unexplained_fingerprint_mismatches}",
        )
    if unexplained_publication_gaps:
        return B8_BLOCKED_PUBLICATION, (
            f"UNEXPLAINED_PUBLICATION_GAPS={unexplained_publication_gaps}",
        )
    if unexplained_arm_divergences:
        return B8_BLOCKED_ARM, (
            f"UNEXPLAINED_ADAPTIVE_ARM_DIVERGENCES={unexplained_arm_divergences}",
        )
    if empirical_population_count <= 0:
        return B8_BLOCKED_EMPTY, ("EMPTY_POINT_IN_TIME_ADAPTIVE_POPULATION",)
    return B8_READY, ()


def _arm_summary(
    candidate_rows: Sequence[dict[str, object]],
    assessment_rows: Sequence[dict[str, object]],
    price_view: str,
) -> dict[str, object]:
    candidates = tuple(row for row in candidate_rows if row["price_view"] == price_view)
    assessments = tuple(
        row for row in assessment_rows if row["price_view"] == price_view
    )
    sample_counts = tuple(
        int(cast(int, row["completed_sample_count"])) for row in assessments
    )
    evidence = Counter(str(row["evidence_strength"]) for row in assessments)
    findings = Counter(str(row["primary_lineage_finding"]) for row in candidates)
    return {
        "candidate_count": len(candidates),
        "candidate_with_prior_evidence_count": sum(
            value > 0 for value in sample_counts
        ),
        "zero_prior_evidence_count": sum(value == 0 for value in sample_counts),
        "minimum_point_in_time_sample_count": min(sample_counts, default=0),
        "median_point_in_time_sample_count": _median_int(sample_counts),
        "maximum_point_in_time_sample_count": max(sample_counts, default=0),
        "average_point_in_time_sample_count": _average_int(sample_counts),
        "evidence_strength_distribution": dict(sorted(evidence.items())),
        "publication_gap_candidate_count": sum(
            int(cast(int, row["publication_gap_field_count"])) > 0 for row in candidates
        ),
        "publication_gap_fully_attributed": all(
            bool(row["publication_gap_fully_attributed"]) for row in candidates
        ),
        "dominant_lineage_finding": (
            findings.most_common(1)[0][0] if findings else "NONE"
        ),
    }


def _point_in_time_summary(
    eligibility_rows: Sequence[dict[str, object]],
    assessment_rows: Sequence[dict[str, object]],
) -> dict[str, object]:
    reasons = Counter(str(row["eligibility_reason"]) for row in eligibility_rows)
    return {
        "eligibility_row_count": len(eligibility_rows),
        "eligible_match_row_count": sum(
            bool(row["eligible"]) for row in eligibility_rows
        ),
        "candidate_with_prior_evidence_count": sum(
            int(cast(int, row["completed_sample_count"])) > 0 for row in assessment_rows
        ),
        "maximum_candidate_sample_count": max(
            (int(cast(int, row["completed_sample_count"])) for row in assessment_rows),
            default=0,
        ),
        "eligibility_reason_distribution": dict(sorted(reasons.items())),
        "same_date_and_future_outcomes_excluded": True,
        "opposite_price_arms_isolated": True,
    }


def _source_separation_summary(
    rows: Sequence[dict[str, object]],
) -> dict[str, object]:
    return {
        "source_count": len(rows),
        "adaptive_source_count": sum(
            bool(row["equivalent_to_adaptive_learning"]) for row in rows
        ),
        "non_equivalent_source_count": sum(
            not bool(row["equivalent_to_adaptive_learning"]) for row in rows
        ),
        "cross_source_merge_permitted": any(
            bool(row["cross_source_merge_permitted"]) for row in rows
        ),
    }


def export_governed_adaptive_evidence_lineage(
    *,
    report: dict[str, Any],
    candidate_rows: tuple[dict[str, object], ...],
    eligibility_rows: tuple[dict[str, object], ...],
    fingerprint_rows: tuple[dict[str, object], ...],
    assessment_rows: tuple[dict[str, object], ...],
    publication_rows: tuple[dict[str, object], ...],
    source_separation_rows: tuple[dict[str, object], ...],
    comparison_rows: tuple[dict[str, object], ...],
    probe_rows: tuple[dict[str, object], ...],
    output: Path,
) -> tuple[Path, ...]:
    """Export deterministic B8 evidence and bind every supporting file."""

    output.mkdir(parents=True, exist_ok=True)
    certificate_path = output / "htr010b8_adaptive_evidence_lineage_certificate.json"
    certificate_path.unlink(missing_ok=True)
    support_paths = (
        _write_csv(
            output / "htr010b8_candidate_adaptive_evidence_lineage.csv",
            candidate_rows,
            fieldnames=_CANDIDATE_FIELDS,
        ),
        _write_csv(
            output / "htr010b8_point_in_time_outcome_eligibility.csv",
            eligibility_rows,
            fieldnames=_ELIGIBILITY_FIELDS,
        ),
        _write_csv(
            output / "htr010b8_fingerprint_parity_ledger.csv",
            fingerprint_rows,
            fieldnames=_FINGERPRINT_FIELDS,
        ),
        _write_csv(
            output / "htr010b8_shadow_adaptive_assessments.csv",
            assessment_rows,
            fieldnames=_ASSESSMENT_FIELDS,
        ),
        _write_csv(
            output / "htr010b8_publication_contract_gap_ledger.csv",
            publication_rows,
            fieldnames=_PUBLICATION_FIELDS,
        ),
        _write_csv(
            output / "htr010b8_evidence_source_separation.csv",
            source_separation_rows,
            fieldnames=_SOURCE_SEPARATION_FIELDS,
        ),
        _write_csv(
            output / "htr010b8_raw_adjusted_adaptive_comparison.csv",
            comparison_rows,
            fieldnames=_COMPARISON_FIELDS,
        ),
        _write_csv(
            output / "htr010b8_non_vacuity_probe_ledger.csv",
            probe_rows,
            fieldnames=_PROBE_FIELDS,
        ),
        _write_text(
            output / "htr010b8_executive_report.md",
            _markdown(report),
        ),
    )
    report["artifact_hashes"] = {
        path.name: _file_sha256(path) for path in support_paths
    }
    report["report_sha256"] = _digest_mapping(report)
    certificate = _write_json(certificate_path, report)
    return (certificate, *support_paths)


def validate_governed_adaptive_evidence_lineage_certificate(
    path: Path,
    *,
    require_ready: bool = False,
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    """Validate the signed B8 contract and every supporting artifact."""

    payload = _mapping(path)
    if payload.get("contract_version") != HTR010B8_CONTRACT_VERSION:
        raise ValueError("unsupported HTR-010B8 adaptive lineage contract")
    _validate_digest(payload, "HTR-010B8 adaptive evidence lineage certificate")
    _validate_research_only_flags(payload)
    _validate_certificate_lineage(payload)
    hashes = payload.get("artifact_hashes")
    if not isinstance(hashes, dict):
        raise ValueError("HTR-010B8 certificate lacks supporting artifact hashes")
    names = frozenset(str(name) for name in hashes)
    if names != _REQUIRED_B8_SUPPORT_ARTIFACTS:
        raise ValueError("HTR-010B8 supporting artifact set mismatch")
    for name, expected in sorted(hashes.items()):
        expected_sha256 = str(expected)
        if not _is_sha256(expected_sha256):
            raise ValueError(f"HTR-010B8 supporting digest is invalid: {name}")
        if _file_sha256(_artifact_path(path.parent, name)) != expected_sha256:
            raise ValueError(f"HTR-010B8 supporting artifact changed: {name}")
    if project_root is not None:
        root = Path(project_root)
        expected_sources = _mapping_copy(payload, "source_contract_file_sha256s")
        if _source_contract_hashes(root) != expected_sources:
            raise ValueError("HTR-010B8 source contract digest mismatch")
        b7_policy = _mapping_copy(
            payload,
            "b7_institutional_policy_source_sha256s",
        )
        b7_pipeline = _mapping_copy(
            payload,
            "b7_frozen_pipeline_component_sha256s",
        )
        if not b7_policy or not b7_pipeline:
            raise ValueError("HTR-010B8 lacks B7 policy and pipeline lineage")
    readiness = str(payload.get("readiness_decision") or "")
    valid = {
        B8_READY,
        B8_BLOCKED_EMPTY,
        B8_BLOCKED_FINGERPRINT,
        B8_BLOCKED_PUBLICATION,
        B8_BLOCKED_LEAKAGE,
        B8_BLOCKED_DEFECT,
        B8_BLOCKED_ARM,
    }
    if readiness not in valid:
        raise ValueError("HTR-010B8 readiness decision is invalid")
    enabled = payload.get("governed_adaptive_evidence_lineage_research_enabled")
    expected_enabled = readiness == B8_READY
    if enabled is not expected_enabled:
        raise ValueError("HTR-010B8 readiness and enablement disagree")
    _validate_certificate_state_semantics(payload)
    if require_ready and not expected_enabled:
        raise ValueError("HTR-010B8 does not permit adaptive lineage research")
    return payload


def _validate_research_only_flags(payload: Mapping[str, object]) -> None:
    required_false = (
        "adaptive_metadata_publication_enabled",
        "approval_policy_change_permitted",
        "evidence_threshold_change_permitted",
        "fingerprint_matching_change_permitted",
        "production_ledger_mutation_enabled",
        "synthetic_outcomes_permitted",
        "counterfactual_approval_claimed",
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
            raise ValueError(f"HTR-010B8 governance flag must remain false: {key}")
    if payload.get("research_scope") != RESEARCH_SCOPE:
        raise ValueError("HTR-010B8 research scope is invalid")
    if payload.get("governed_setup_matched_evidence_research_enabled") is not True:
        raise ValueError("HTR-010B8 requires B7 evidence-research readiness")


def _validate_certificate_lineage(payload: Mapping[str, object]) -> None:
    if payload.get("b7_contract_version") != HTR010B7_CONTRACT_VERSION:
        raise ValueError("HTR-010B8 B7 contract lineage is invalid")
    for key in (
        "b7_report_sha256",
        "b7_certificate_file_sha256",
        "b7_candidate_ledger_sha256",
        "b7_outcome_ledger_sha256",
    ):
        if not _is_sha256(str(payload.get(key) or "")):
            raise ValueError(f"HTR-010B8 lineage digest is invalid: {key}")
    sources = _mapping_copy(payload, "source_contract_file_sha256s")
    if set(sources) != set(_SOURCE_CONTRACT_PATHS):
        raise ValueError("HTR-010B8 source contract file set is invalid")
    if any(not _is_sha256(value) for value in sources.values()):
        raise ValueError("HTR-010B8 source contract digest is invalid")


def _validate_certificate_state_semantics(payload: Mapping[str, object]) -> None:
    defects = tuple(
        str(item) for item in _list_value(payload, "implementation_defects")
    )
    if defects != tuple(sorted(set(defects))):
        raise ValueError("HTR-010B8 implementation defects are not deterministic")
    if _integer(payload.get("implementation_defect_count"), "defect count") != len(
        defects
    ):
        raise ValueError("HTR-010B8 implementation defect count is inconsistent")
    expected, blockers = _readiness(
        empirical_population_count=_integer(
            payload.get("candidate_with_prior_evidence_count"),
            "candidate prior evidence count",
        ),
        unexplained_fingerprint_mismatches=_integer(
            payload.get("unexplained_fingerprint_mismatch_count"),
            "unexplained fingerprint mismatch count",
        ),
        unexplained_publication_gaps=_integer(
            payload.get("unexplained_publication_gap_count"),
            "unexplained publication gap count",
        ),
        leakage_count=_integer(
            payload.get("point_in_time_leakage_count"),
            "point-in-time leakage count",
        ),
        implementation_defects=defects,
        unexplained_arm_divergences=_integer(
            payload.get("unexplained_adaptive_arm_divergence_count"),
            "unexplained arm divergence count",
        ),
    )
    if payload.get("readiness_decision") != expected:
        raise ValueError("HTR-010B8 readiness disagrees with certificate evidence")
    observed_blockers = tuple(
        str(item) for item in _list_value(payload, "readiness_blockers")
    )
    if observed_blockers != blockers:
        raise ValueError("HTR-010B8 readiness blockers are inconsistent")
    probes = _nested_mapping(payload, "probe_summary")
    if (
        _integer(probes.get("failed_probe_count"), "failed probes") != 0
        and expected == B8_READY
    ):
        raise ValueError("HTR-010B8 ready certificate has failed probes")


def _markdown(report: Mapping[str, object]) -> str:
    raw = _nested_mapping(report, "raw_adaptive_summary")
    adjusted = _nested_mapping(report, "adjusted_adaptive_summary")
    publication = _nested_mapping(report, "publication_contract_summary")
    fingerprint = _nested_mapping(report, "fingerprint_contract_summary")
    point_in_time = _nested_mapping(report, "point_in_time_summary")
    probes = _nested_mapping(report, "probe_summary")
    lines = [
        "# HTR-010B8 Governed Adaptive Evidence Lineage Certification",
        "",
        f"Readiness: **{report['readiness_decision']}**",
        "",
        "## Point-in-time adaptive population",
        "",
        f"- RAW candidates: {raw['candidate_count']}",
        (
            "- RAW candidates with prior completed evidence: "
            f"{raw['candidate_with_prior_evidence_count']}"
        ),
        f"- ADJUSTED candidates: {adjusted['candidate_count']}",
        (
            "- ADJUSTED candidates with prior completed evidence: "
            f"{adjusted['candidate_with_prior_evidence_count']}"
        ),
        (
            "- Maximum point-in-time sample count: "
            f"{point_in_time['maximum_candidate_sample_count']}"
        ),
        "",
        "## Publication lineage",
        "",
        (
            "- Adaptive orchestrator invocation present: "
            f"{publication['orchestrator_invokes_adaptive_assessment']}"
        ),
        (
            "- Producer adaptive metadata keys: "
            f"{publication['producer_publication_key_count']}/"
            f"{publication['metadata_key_count']}"
        ),
        (f"- Attributed publication gaps: {publication['attributed_gap_count']}"),
        "",
        "## Fingerprint contract",
        "",
        (f"- Current recorder mismatch: {fingerprint['current_contract_mismatch']}"),
        (f"- Current mismatch explained: {fingerprint['current_gap_explained']}"),
        (
            "- Complete snapshot parity reachable: "
            f"{fingerprint['complete_snapshot_parity_reachable']}"
        ),
        "",
        "## Certification",
        "",
        f"- Point-in-time leakage count: {report['point_in_time_leakage_count']}",
        f"- Implementation defects: {report['implementation_defect_count']}",
        (
            "- Unexplained publication gaps: "
            f"{report['unexplained_publication_gap_count']}"
        ),
        (
            "- Unexplained RAW/ADJUSTED divergences: "
            f"{report['unexplained_adaptive_arm_divergence_count']}"
        ),
        f"- Non-vacuity probes passed: {probes['passed_probe_count']}",
        "",
        "## Governance",
        "",
        "- Adaptive metadata publication remains disabled.",
        "- No threshold or fingerprint-matching policy changed.",
        "- No production ledger was mutated.",
        (
            "- No recommendation, approval, portfolio, execution, learning, "
            "or production influence."
        ),
        "",
    ]
    return "\n".join(lines)


def _source_contract_hashes(root: Path) -> dict[str, str]:
    return {
        relative: _file_sha256(root / relative) for relative in _SOURCE_CONTRACT_PATHS
    }


def _candidate_key(row: Mapping[str, object]) -> CandidateKey:
    return (
        str(row.get("price_view") or "").strip().upper(),
        _date_value(row.get("observed_on"), "candidate observed_on"),
        str(row.get("symbol") or "").strip().upper(),
    )


def _key_defect(code: str, key: CandidateKey) -> str:
    return f"{code}@{key[0]}:{key[1].isoformat()}:{key[2]}"


def _progress(
    callback: ProgressCallback | None,
    current: int,
    total: int,
    description: str,
) -> None:
    if callback is not None:
        callback(current, total, description)


def _csv_rows(path: Path) -> tuple[dict[str, str], ...]:
    if not path.exists():
        raise ValueError(f"required HTR-010B8 input is missing: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return tuple(csv.DictReader(handle))


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    *,
    fieldnames: Sequence[str],
) -> Path:
    _ensure_parent(path)
    with NamedTemporaryFile(
        mode="w",
        newline="",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: _csv_value(row.get(name)) for name in fieldnames})
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return path


def _write_json(path: Path, payload: Mapping[str, object]) -> Path:
    return _write_text(
        path,
        json.dumps(_json_ready(payload), indent=2, sort_keys=True) + "\n",
    )


def _write_text(path: Path, content: str) -> Path:
    _ensure_parent(path)
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return path


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (tuple, list, set, frozenset)):
        return "|".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(_json_ready(value), sort_keys=True)
    return value


def _json_ready(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected mapping: {path}")
    return cast(dict[str, Any], payload)


def _mapping_copy(
    payload: Mapping[str, object],
    key: str,
) -> dict[str, str]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"expected mapping field: {key}")
    return {str(name): str(digest) for name, digest in value.items()}


def _nested_mapping(
    payload: Mapping[str, object],
    key: str,
) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"expected mapping field: {key}")
    return cast(Mapping[str, object], value)


def _list_value(
    payload: Mapping[str, object],
    key: str,
) -> list[object]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"expected list field: {key}")
    return value


def _date_value(value: object, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"{label} must use YYYY-MM-DD") from error


def _optional_int(value: object) -> int | None:
    if value is None or str(value).strip().lower() in {
        "",
        "none",
        "unavailable",
        "unknown",
    }:
        return None
    try:
        return int(str(value))
    except ValueError:
        return None


def _integer(value: object, label: str) -> int:
    parsed = _optional_int(value)
    if parsed is None:
        raise ValueError(f"{label} must be an integer")
    return parsed


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or str(value).strip().lower() in {
        "",
        "none",
        "unavailable",
        "unknown",
    }:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _boolean_optional(value: object) -> bool | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def _median_int(values: Sequence[int]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return Decimal(ordered[middle])
    return (
        (Decimal(ordered[middle - 1]) + Decimal(ordered[middle])) / Decimal("2")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _average_int(values: Sequence[int]) -> Decimal | None:
    if not values:
        return None
    return (
        sum((Decimal(value) for value in values), Decimal("0")) / Decimal(len(values))
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _hash_paths(paths: Mapping[str, Path]) -> dict[str, str]:
    return {key: _file_sha256(path) for key, path in sorted(paths.items())}


def _validate_paths_unchanged(
    paths: Mapping[str, Path],
    expected: Mapping[str, str],
) -> None:
    observed = _hash_paths(paths)
    if observed != dict(expected):
        raise ValueError("HTR-010B8 immutable input changed during analysis")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest_mapping(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(
        _json_ready(payload),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_digest(payload: Mapping[str, object], label: str) -> None:
    expected = str(payload.get("report_sha256") or "")
    if not _is_sha256(expected):
        raise ValueError(f"{label} lacks a valid report digest")
    material = dict(payload)
    material.pop("report_sha256", None)
    if _digest_mapping(material) != expected:
        raise ValueError(f"{label} report digest mismatch")


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _artifact_path(root: Path, name: object) -> Path:
    path = root / str(name)
    if path.parent != root:
        raise ValueError("HTR-010B8 artifact path escapes certificate directory")
    return path


__all__ = [
    "B8_BLOCKED_ARM",
    "B8_BLOCKED_DEFECT",
    "B8_BLOCKED_EMPTY",
    "B8_BLOCKED_FINGERPRINT",
    "B8_BLOCKED_LEAKAGE",
    "B8_BLOCKED_PUBLICATION",
    "B8_READY",
    "HTR010B8_CONTRACT_VERSION",
    "GovernedAdaptiveEvidenceLineageEngine",
    "GovernedAdaptiveEvidenceLineageResult",
    "export_governed_adaptive_evidence_lineage",
    "validate_governed_adaptive_evidence_lineage_certificate",
]
