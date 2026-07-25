"""Governed adaptive institutional-decision and trade shadow replay for HTR-010B10."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import Enum
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from types import MappingProxyType, SimpleNamespace
from typing import Any, cast

import pandas as pd

from alpha.benchmark_replay.governed_adaptive_evidence_lineage import (
    HTR010B8_CONTRACT_VERSION,
    validate_governed_adaptive_evidence_lineage_certificate,
)
from alpha.benchmark_replay.governed_adaptive_publication_bridge import (
    HTR010B9_CONTRACT_VERSION,
    validate_governed_adaptive_publication_bridge_certificate,
)
from alpha.benchmark_replay.governed_adjusted import (
    GovernedBenchmarkStore,
    build_governed_benchmark_stores,
)
from alpha.benchmark_replay.governed_setup_matched_evidence import (
    HTR010B7_CONTRACT_VERSION,
    validate_governed_setup_matched_evidence_certificate,
)
from alpha.canonical_universe_audit.canonical_runner import (
    CanonicalAlphaRunner,
    CanonicalDailyResult,
)
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.decision_intelligence import InstitutionalDecisionEngine, OpportunityDecision
from alpha.learning_intelligence import (
    AdaptiveMetadataPublicationBatch,
    AdaptiveMetadataPublisher,
    PointInTimeAdaptiveMetadataPublisher,
)
from alpha.performance_intelligence.models import (
    RecommendationExitReason,
    RecommendationLedgerEntry,
    RecommendationOutcome,
    RecommendationOutcomeStatus,
)
from alpha.performance_intelligence.recorder import recommendation_to_ledger_entry
from alpha.recommendation_intelligence import OHLCVBar, RecommendationReport
from alpha.strategy_lab.execution_assumptions import default_execution_profile
from alpha.strategy_lab.models import (
    EntryRule,
    StopRule,
    TargetRule,
    TradeExitReason,
    TradeSimulation,
    TradeSimulationRequest,
)
from alpha.strategy_lab.trade_simulator import TradeSimulator

HTR010B10_CONTRACT_VERSION = "HTR-010B10-v1.0.0"

B10_READY = "READY_FOR_GOVERNED_ADAPTIVE_INSTITUTIONAL_TRADE_SHADOW_RESEARCH"
B10_BLOCKED_EMPTY = "BLOCKED_BY_EMPTY_ADAPTIVE_SHADOW_POPULATION"
B10_BLOCKED_HANDOFF = "BLOCKED_BY_B9_HANDOFF_DEFECT"
B10_BLOCKED_DEFAULT = "BLOCKED_BY_DEFAULT_PATH_DRIFT"
B10_BLOCKED_LEAKAGE = "BLOCKED_BY_POINT_IN_TIME_ADAPTIVE_LEAKAGE"
B10_BLOCKED_RECOMMENDATION = "BLOCKED_BY_RECOMMENDATION_SEMANTIC_DRIFT"
B10_BLOCKED_INSTITUTIONAL = "BLOCKED_BY_UNEXPLAINED_INSTITUTIONAL_DECISION_DIVERGENCE"
B10_BLOCKED_TRADE = "BLOCKED_BY_UNEXPLAINED_TRADE_FORMATION_DIVERGENCE"
B10_BLOCKED_ARM = "BLOCKED_BY_UNEXPLAINED_ADAPTIVE_ARM_DIVERGENCE"
B10_BLOCKED_DEFECT = "BLOCKED_BY_ADAPTIVE_SHADOW_IMPLEMENTATION_DEFECT"

RESEARCH_SCOPE = "GOVERNED_ADAPTIVE_INSTITUTIONAL_TRADE_SHADOW_RESEARCH_ONLY"
ProgressCallback = Callable[[int, int, str], None]
CandidateKey = tuple[str, date, str]
ArmCandidateKey = tuple[date, str]

_ADAPTIVE_KEYS = (
    "adaptive_adjusted_confidence",
    "adaptive_evidence_strength",
    "adaptive_posterior_probability",
    "adaptive_expectancy",
    "adaptive_sample_count",
)
_APPROVABLE_SIGNALS = frozenset({"BUY", "STRONG_BUY"})
_ADAPTIVE_GATE_CODES = frozenset(
    {
        "INSUFFICIENT_EVIDENCE",
        "POOR_HISTORICAL_EDGE",
        "WEAK_CONFIDENCE",
        "WEAK_SETUP",
    }
)
_OUTCOME_WINDOW = 60
_B7_CANDIDATE_ARTIFACT = "htr010b7_candidate_evidence_sufficiency.csv"

_SOURCE_CONTRACT_PATHS = (
    "alpha/application/intelligence.py",
    "alpha/canonical_universe_audit/canonical_runner.py",
    "alpha/canonical_universe_audit/engine.py",
    "alpha/decision_intelligence/engine.py",
    "alpha/learning_intelligence/engine.py",
    "alpha/learning_intelligence/fingerprints.py",
    "alpha/learning_intelligence/publication.py",
    "alpha/performance_intelligence/recorder.py",
    "alpha/recommendation_intelligence/engines.py",
    "alpha/strategy_lab/execution_assumptions.py",
    "alpha/strategy_lab/trade_simulator.py",
)
_REQUIRED_SUPPORT_ARTIFACTS = frozenset(
    {
        "htr010b10_adaptive_publication_ledger.csv",
        "htr010b10_institutional_decision_comparison.csv",
        "htr010b10_gate_transition_ledger.csv",
        "htr010b10_portfolio_trade_formation_comparison.csv",
        "htr010b10_completed_trade_outcome_comparison.csv",
        "htr010b10_point_in_time_eligibility.csv",
        "htr010b10_raw_adjusted_effect_comparison.csv",
        "htr010b10_default_path_invariance.csv",
        "htr010b10_source_contract_snapshot.csv",
        "htr010b10_non_vacuity_probe_ledger.csv",
        "htr010b10_executive_report.md",
    }
)

_PUBLICATION_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "fingerprint_key",
    "eligible_completed_sample_count",
    "posterior_win_probability",
    "expectancy",
    "evidence_strength",
    "adjusted_confidence",
    "published_metadata_complete",
)
_DECISION_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "default_present",
    "adaptive_present",
    "default_semantic_fingerprint",
    "adaptive_semantic_fingerprint",
    "recommendation_semantic_drift",
    "adaptive_metadata_changed",
    "default_adjusted_confidence",
    "adaptive_adjusted_confidence",
    "default_evidence_strength",
    "adaptive_evidence_strength",
    "default_sample_count",
    "adaptive_sample_count",
    "default_posterior",
    "adaptive_posterior",
    "default_expectancy",
    "adaptive_expectancy",
    "default_accepted",
    "adaptive_accepted",
    "approval_changed",
    "default_opportunity_score",
    "adaptive_opportunity_score",
    "default_grade",
    "adaptive_grade",
    "default_rejection_codes",
    "adaptive_rejection_codes",
    "default_primary_gate",
    "adaptive_primary_gate",
    "decision_changed",
    "difference_codes",
    "explained_by_adaptive_publication",
    "unexplained_institutional_divergence",
)
_GATE_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "gate_code",
    "default_present",
    "adaptive_present",
    "transition",
    "adaptive_metadata_changed",
    "recommendation_semantic_drift",
    "explained_by_adaptive_publication",
    "unexplained_gate_transition",
)
_TRADE_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "default_allocation_amount",
    "adaptive_allocation_amount",
    "allocation_changed",
    "default_portfolio_eligible",
    "adaptive_portfolio_eligible",
    "portfolio_eligibility_changed",
    "default_trade_formed",
    "adaptive_trade_formed",
    "trade_formation_changed",
    "outcome_status",
    "entry_triggered",
    "completed",
    "approval_changed",
    "recommendation_semantic_drift",
    "difference_codes",
    "explained_by_adaptive_publication",
    "unexplained_trade_formation_divergence",
)
_OUTCOME_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "default_trade_present",
    "adaptive_trade_present",
    "paired_trade",
    "entry_date",
    "entry_price",
    "exit_date",
    "exit_price",
    "exit_reason",
    "realized_r_multiple",
    "realized_percent_return",
    "holding_period_days",
    "presence_difference_explained",
    "paired_outcome_identical",
    "unexplained_outcome_divergence",
)
_ELIGIBILITY_FIELDS = (
    "price_view",
    "recommendation_observed_on",
    "recommendation_symbol",
    "reason",
    "row_count",
    "fingerprint_match_count",
    "eligible_count",
    "leakage_count",
)
_ARM_FIELDS = (
    "observed_on",
    "symbol",
    "raw_present",
    "adjusted_present",
    "raw_effect_signature",
    "adjusted_effect_signature",
    "raw_input_fingerprint",
    "adjusted_input_fingerprint",
    "input_fingerprint_changed",
    "effect_changed",
    "explained_by_signed_input_difference",
    "unexplained_adaptive_arm_divergence",
)
_DEFAULT_FIELDS = (
    "price_view",
    "observed_on",
    "baseline_fingerprint",
    "explicit_disabled_fingerprint",
    "publisher_call_count",
    "default_path_identical",
    "passed",
)
_SOURCE_FIELDS = (
    "source_path",
    "current_sha256",
    "b9_sha256",
    "changed_since_b9",
    "contract_status",
    "passed",
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
class _ShadowDay:
    price_view: str
    observed_on: date
    result: CanonicalDailyResult


@dataclass(frozen=True, slots=True)
class _LearningPopulation:
    entries: tuple[RecommendationLedgerEntry, ...]
    outcomes: tuple[RecommendationOutcome, ...]
    outcome_by_key: Mapping[ArmCandidateKey, RecommendationOutcome]


@dataclass(frozen=True, slots=True)
class GovernedAdaptiveInstitutionalTradeShadowResult:
    report: dict[str, Any]
    publication_rows: tuple[dict[str, object], ...]
    decision_rows: tuple[dict[str, object], ...]
    gate_rows: tuple[dict[str, object], ...]
    trade_rows: tuple[dict[str, object], ...]
    outcome_rows: tuple[dict[str, object], ...]
    eligibility_rows: tuple[dict[str, object], ...]
    arm_rows: tuple[dict[str, object], ...]
    default_rows: tuple[dict[str, object], ...]
    source_rows: tuple[dict[str, object], ...]
    probe_rows: tuple[dict[str, object], ...]
    paths: tuple[Path, ...]


class _CapturingPublisher(AdaptiveMetadataPublisher):
    def __init__(
        self,
        *,
        price_view: str,
        delegate: PointInTimeAdaptiveMetadataPublisher,
    ) -> None:
        self.price_view = price_view
        self.delegate = delegate
        self.publication_rows: list[dict[str, object]] = []
        self.eligibility_rows: list[object] = []

    def publish(
        self,
        *,
        recommendations: tuple[RecommendationReport, ...],
        observed_on: date,
        market_regime: str | None,
    ) -> AdaptiveMetadataPublicationBatch:
        batch = self.delegate.publish(
            recommendations=recommendations,
            observed_on=observed_on,
            market_regime=market_regime,
        )
        for record in batch.records:
            self.publication_rows.append(
                {
                    "price_view": self.price_view,
                    "observed_on": record.observed_on,
                    "symbol": record.symbol,
                    "fingerprint_key": record.fingerprint_key,
                    "eligible_completed_sample_count": (
                        record.eligible_completed_sample_count
                    ),
                    "posterior_win_probability": record.posterior_win_probability,
                    "expectancy": record.expectancy,
                    "evidence_strength": record.evidence_strength,
                    "adjusted_confidence": record.adjusted_confidence,
                    "published_metadata_complete": (
                        tuple(sorted(record.published_metadata))
                        == tuple(sorted(_ADAPTIVE_KEYS))
                    ),
                }
            )
        self.eligibility_rows.extend(batch.eligibility)
        return batch


class _NeverCalledPublisher(AdaptiveMetadataPublisher):
    def __init__(self) -> None:
        self.calls = 0

    def publish(
        self,
        *,
        recommendations: tuple[RecommendationReport, ...],
        observed_on: date,
        market_regime: str | None,
    ) -> AdaptiveMetadataPublicationBatch:
        del recommendations, observed_on, market_regime
        self.calls += 1
        raise AssertionError("disabled adaptive publisher was invoked")


class GovernedAdaptiveInstitutionalTradeShadowEngine:
    """Run paired default and adaptive-published shadow paths under frozen policy."""

    def run(
        self,
        *,
        source: LegacyMarketDataStore,
        b9_certificate: Path,
        b8_certificate: Path,
        b7_certificate: Path,
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
    ) -> GovernedAdaptiveInstitutionalTradeShadowResult:
        root = Path(project_root)
        total_steps = 12
        _progress(progress, 1, total_steps, "Validating signed B9→B8→B7 handoff")
        b9, b8, b7 = _validated_handoff(
            b9_certificate=b9_certificate,
            b8_certificate=b8_certificate,
            b7_certificate=b7_certificate,
            project_root=root,
        )
        explicit_paths = {
            "identity_artifact": identity_artifact,
            "corporate_action_artifact": corporate_action_artifact,
            "final_closure_report": final_closure_report,
            "admission_contract": admission_contract,
            "identity_admission": identity_admission,
            "raw_universe": raw_universe,
            "adjusted_universe": adjusted_universe,
        }
        explicit_hashes = _validate_explicit_inputs(b7, explicit_paths)
        b7_candidate_path = b7_certificate.parent / _B7_CANDIDATE_ARTIFACT
        immutable_paths = {
            "b9_certificate": b9_certificate,
            "b8_certificate": b8_certificate,
            "b7_certificate": b7_certificate,
            "b7_candidate_ledger": b7_candidate_path,
            **explicit_paths,
        }
        immutable_hashes = _hash_paths(immutable_paths)

        _progress(
            progress,
            2,
            total_steps,
            "Certifying frozen runtime source contracts",
        )
        source_rows, source_defects, source_hashes = _source_contract_snapshot(root, b9)

        replay_start = _date_value(b7.get("replay_start"), "B7 replay start")
        replay_end = _date_value(b7.get("replay_end"), "B7 replay end")
        input_fingerprints = _b7_input_fingerprints(b7_candidate_path)

        _progress(
            progress,
            3,
            total_steps,
            "Rebuilding governed RAW and ADJUSTED stores",
        )
        with TemporaryDirectory(prefix="htr010b10-store-contracts-") as temporary:
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
                lineage_defects = _governed_store_lineage_defects(pair, b7)
                _progress(
                    progress,
                    4,
                    total_steps,
                    "Running immutable DEFAULT RAW path",
                )
                raw_default, raw_default_defects = _run_shadow_days(
                    pair.raw,
                    price_view="RAW",
                    replay_start=replay_start,
                    replay_end=replay_end,
                    publisher=None,
                    publication_enabled=False,
                    progress=progress,
                    progress_step=4,
                    total_steps=total_steps,
                )
                _progress(
                    progress,
                    5,
                    total_steps,
                    "Running immutable DEFAULT ADJUSTED path",
                )
                adjusted_default, adjusted_default_defects = _run_shadow_days(
                    pair.adjusted,
                    price_view="ADJUSTED",
                    replay_start=replay_start,
                    replay_end=replay_end,
                    publisher=None,
                    publication_enabled=False,
                    progress=progress,
                    progress_step=5,
                    total_steps=total_steps,
                )

                _progress(
                    progress,
                    6,
                    total_steps,
                    "Building immutable outcome ledgers",
                )
                raw_population, raw_population_defects = _learning_population(
                    pair.raw,
                    raw_default,
                    price_view="RAW",
                )
                adjusted_population, adjusted_population_defects = _learning_population(
                    pair.adjusted,
                    adjusted_default,
                    price_view="ADJUSTED",
                )

                _progress(
                    progress,
                    7,
                    total_steps,
                    "Running ADAPTIVE_PUBLISHED RAW path",
                )
                raw_capture = _CapturingPublisher(
                    price_view="RAW",
                    delegate=PointInTimeAdaptiveMetadataPublisher(
                        entries=raw_population.entries,
                        outcomes=raw_population.outcomes,
                    ),
                )
                raw_adaptive, raw_adaptive_defects = _run_shadow_days(
                    pair.raw,
                    price_view="RAW",
                    replay_start=replay_start,
                    replay_end=replay_end,
                    publisher=raw_capture,
                    publication_enabled=True,
                    progress=progress,
                    progress_step=7,
                    total_steps=total_steps,
                )

                _progress(
                    progress,
                    8,
                    total_steps,
                    "Running ADAPTIVE_PUBLISHED ADJUSTED path",
                )
                adjusted_capture = _CapturingPublisher(
                    price_view="ADJUSTED",
                    delegate=PointInTimeAdaptiveMetadataPublisher(
                        entries=adjusted_population.entries,
                        outcomes=adjusted_population.outcomes,
                    ),
                )
                adjusted_adaptive, adjusted_adaptive_defects = _run_shadow_days(
                    pair.adjusted,
                    price_view="ADJUSTED",
                    replay_start=replay_start,
                    replay_end=replay_end,
                    publisher=adjusted_capture,
                    publication_enabled=True,
                    progress=progress,
                    progress_step=8,
                    total_steps=total_steps,
                )

                _progress(progress, 9, total_steps, "Comparing institutional decisions")
                (
                    raw_decisions,
                    raw_gates,
                    raw_trades,
                    raw_outcomes,
                ) = _compare_arm(
                    default_days=raw_default,
                    adaptive_days=raw_adaptive,
                    population=raw_population,
                    price_view="RAW",
                )
                (
                    adjusted_decisions,
                    adjusted_gates,
                    adjusted_trades,
                    adjusted_outcomes,
                ) = _compare_arm(
                    default_days=adjusted_default,
                    adaptive_days=adjusted_adaptive,
                    population=adjusted_population,
                    price_view="ADJUSTED",
                )

                _progress(
                    progress,
                    10,
                    total_steps,
                    "Attributing point-in-time and arm effects",
                )
                publication_rows = tuple(
                    sorted(
                        (
                            *raw_capture.publication_rows,
                            *adjusted_capture.publication_rows,
                        ),
                        key=_row_sort_key,
                    )
                )
                eligibility_rows, leakage_count = _eligibility_summary(
                    raw_capture,
                    adjusted_capture,
                )
                decision_rows = tuple((*raw_decisions, *adjusted_decisions))
                gate_rows = tuple((*raw_gates, *adjusted_gates))
                trade_rows = tuple((*raw_trades, *adjusted_trades))
                outcome_rows = tuple((*raw_outcomes, *adjusted_outcomes))
                arm_rows, unexplained_arm = _arm_effect_comparison(
                    decision_rows=decision_rows,
                    trade_rows=trade_rows,
                    input_fingerprints=input_fingerprints,
                )
                default_rows, default_defects = _default_invariance_rows(
                    pair.raw,
                    pair.adjusted,
                    replay_start=replay_start,
                    replay_end=replay_end,
                )
            finally:
                pair.close()

        _progress(progress, 11, total_steps, "Running deterministic B10 probes")
        probe_rows, probe_summary, probe_defects = _non_vacuity_probes()
        recommendation_drift = sum(
            bool(row["recommendation_semantic_drift"]) for row in decision_rows
        )
        unexplained_institutional = sum(
            bool(row["unexplained_institutional_divergence"]) for row in decision_rows
        )
        unexplained_trade = sum(
            bool(row["unexplained_trade_formation_divergence"]) for row in trade_rows
        ) + sum(bool(row["unexplained_outcome_divergence"]) for row in outcome_rows)
        default_drift = sum(not bool(row["passed"]) for row in default_rows)
        population_nonempty = bool(decision_rows) and all(
            any(row["price_view"] == view for row in decision_rows)
            for view in ("RAW", "ADJUSTED")
        )
        implementation_defects = tuple(
            sorted(
                {
                    *source_defects,
                    *lineage_defects,
                    *raw_default_defects,
                    *adjusted_default_defects,
                    *raw_population_defects,
                    *adjusted_population_defects,
                    *raw_adaptive_defects,
                    *adjusted_adaptive_defects,
                    *default_defects,
                    *probe_defects,
                }
            )
        )
        readiness, blockers = _readiness(
            handoff_defects=(),
            population_nonempty=population_nonempty,
            default_path_drift_count=default_drift,
            leakage_count=leakage_count,
            recommendation_semantic_drift_count=recommendation_drift,
            unexplained_institutional_divergence_count=unexplained_institutional,
            unexplained_trade_divergence_count=unexplained_trade,
            unexplained_arm_divergence_count=unexplained_arm,
            implementation_defects=implementation_defects,
        )
        ready = readiness == B10_READY

        _validate_paths_unchanged(immutable_paths, immutable_hashes)
        if _source_contract_hashes(root) != source_hashes:
            raise ValueError("HTR-010B10 source contract changed during certification")

        report: dict[str, Any] = {
            "contract_version": HTR010B10_CONTRACT_VERSION,
            "b9_contract_version": b9["contract_version"],
            "b9_report_sha256": b9["report_sha256"],
            "b9_certificate_file_sha256": _file_sha256(b9_certificate),
            "b8_contract_version": b8["contract_version"],
            "b8_report_sha256": b8["report_sha256"],
            "b8_certificate_file_sha256": _file_sha256(b8_certificate),
            "b7_contract_version": b7["contract_version"],
            "b7_report_sha256": b7["report_sha256"],
            "b7_certificate_file_sha256": _file_sha256(b7_certificate),
            "b7_candidate_ledger_sha256": _file_sha256(b7_candidate_path),
            "input_artifact_file_sha256s": explicit_hashes,
            "source_contract_file_sha256s": source_hashes,
            "b9_source_contract_file_sha256s": _mapping_copy(
                b9,
                "source_contract_file_sha256s",
            ),
            "replay_start": replay_start,
            "replay_end": replay_end,
            "session_count": _integer(b7.get("session_count"), "B7 session count"),
            "default_population_summary": _default_population_summary(
                raw_default,
                adjusted_default,
                raw_population,
                adjusted_population,
            ),
            "publication_summary": _publication_summary(publication_rows),
            "institutional_effect_summary": _institutional_summary(decision_rows),
            "trade_formation_summary": _trade_summary(trade_rows, outcome_rows),
            "point_in_time_summary": {
                "eligibility_row_count": len(eligibility_rows),
                "eligible_count": sum(
                    int(cast(int, row["eligible_count"])) for row in eligibility_rows
                ),
                "leakage_count": leakage_count,
                "strict_prior_entry_and_completion_required": True,
            },
            "arm_effect_summary": {
                "pair_count": len(arm_rows),
                "unexplained_divergence_count": unexplained_arm,
            },
            "default_path_summary": {
                "probe_count": len(default_rows),
                "drift_count": default_drift,
                "publisher_call_count": sum(
                    int(cast(int, row["publisher_call_count"])) for row in default_rows
                ),
            },
            "probe_summary": probe_summary,
            "adaptive_shadow_population_nonempty": population_nonempty,
            "point_in_time_adaptive_leakage_count": leakage_count,
            "recommendation_semantic_drift_count": recommendation_drift,
            "unexplained_institutional_decision_divergence_count": (
                unexplained_institutional
            ),
            "unexplained_trade_formation_divergence_count": unexplained_trade,
            "unexplained_adaptive_arm_divergence_count": unexplained_arm,
            "default_path_drift_count": default_drift,
            "handoff_defects": [],
            "handoff_defect_count": 0,
            "implementation_defects": list(implementation_defects),
            "implementation_defect_count": len(implementation_defects),
            "readiness_blockers": list(blockers),
            "readiness_decision": readiness,
            "default_runtime_adaptive_publication_enabled": False,
            "governed_shadow_adaptive_publication_enabled": ready,
            "approval_policy_change_permitted": False,
            "evidence_threshold_change_permitted": False,
            "fingerprint_matching_change_permitted": False,
            "portfolio_policy_change_permitted": False,
            "execution_policy_change_permitted": False,
            "production_ledger_mutation_enabled": False,
            "synthetic_outcomes_permitted": False,
            "counterfactual_approval_claimed": False,
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

        _progress(progress, 12, total_steps, "Exporting signed HTR-010B10 artifacts")
        paths = export_governed_adaptive_institutional_trade_shadow(
            report=report,
            publication_rows=publication_rows,
            decision_rows=decision_rows,
            gate_rows=gate_rows,
            trade_rows=trade_rows,
            outcome_rows=outcome_rows,
            eligibility_rows=eligibility_rows,
            arm_rows=arm_rows,
            default_rows=default_rows,
            source_rows=source_rows,
            probe_rows=probe_rows,
            output=output,
        )
        return GovernedAdaptiveInstitutionalTradeShadowResult(
            report=report,
            publication_rows=publication_rows,
            decision_rows=decision_rows,
            gate_rows=gate_rows,
            trade_rows=trade_rows,
            outcome_rows=outcome_rows,
            eligibility_rows=eligibility_rows,
            arm_rows=arm_rows,
            default_rows=default_rows,
            source_rows=source_rows,
            probe_rows=probe_rows,
            paths=paths,
        )


def _validated_handoff(
    *,
    b9_certificate: Path,
    b8_certificate: Path,
    b7_certificate: Path,
    project_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    b9 = validate_governed_adaptive_publication_bridge_certificate(
        b9_certificate,
        require_ready=True,
        project_root=project_root,
    )
    b8 = validate_governed_adaptive_evidence_lineage_certificate(
        b8_certificate,
        require_ready=True,
        project_root=None,
    )
    b7 = validate_governed_setup_matched_evidence_certificate(
        b7_certificate,
        require_ready=True,
        project_root=None,
    )
    if b9.get("contract_version") != HTR010B9_CONTRACT_VERSION:
        raise ValueError("B10 requires the HTR-010B9 publication contract")
    if b8.get("contract_version") != HTR010B8_CONTRACT_VERSION:
        raise ValueError("B10 requires the HTR-010B8 lineage contract")
    if b7.get("contract_version") != HTR010B7_CONTRACT_VERSION:
        raise ValueError("B10 requires the HTR-010B7 evidence contract")
    if b9.get("b8_report_sha256") != b8.get("report_sha256"):
        raise ValueError("HTR-010B9 does not descend from the supplied B8 report")
    if b9.get("b8_certificate_file_sha256") != _file_sha256(b8_certificate):
        raise ValueError("HTR-010B9 does not bind the supplied B8 certificate")
    if b8.get("b7_report_sha256") != b7.get("report_sha256"):
        raise ValueError("HTR-010B8 does not descend from the supplied B7 report")
    if b8.get("b7_certificate_file_sha256") != _file_sha256(b7_certificate):
        raise ValueError("HTR-010B8 does not bind the supplied B7 certificate")
    for payload, label in ((b9, "B9"), (b8, "B8"), (b7, "B7")):
        if payload.get("production_influence") is not False:
            raise ValueError(f"{label} unexpectedly permits production influence")
    return b9, b8, b7


def _validate_explicit_inputs(
    b7: Mapping[str, object],
    paths: Mapping[str, Path],
) -> dict[str, str]:
    expected = _mapping_copy(b7, "input_artifact_file_sha256s")
    observed: dict[str, str] = {}
    for key, path in sorted(paths.items()):
        digest = _file_sha256(path)
        observed[key] = digest
        if expected.get(key) != digest:
            raise ValueError(f"HTR-010B10 input artifact differs from B7: {key}")
    return observed


def _governed_store_lineage_defects(
    pair: object,
    b7: Mapping[str, object],
) -> tuple[str, ...]:
    lineage = _nested_mapping(b7, "governed_store_lineage")
    checks = (
        (
            "IDENTITY_SESSION_SHA256",
            lineage.get("identity_session_sha256"),
            getattr(pair, "identity_session_sha256"),
        ),
        (
            "FINAL_CLOSURE_SHA256",
            lineage.get("final_closure_report_sha256"),
            getattr(pair, "final_closure_report_sha256"),
        ),
        (
            "ADMISSION_CONTRACT_SHA256",
            lineage.get("admission_contract_sha256"),
            getattr(pair, "admission_contract_sha256"),
        ),
    )
    return tuple(
        f"GOVERNED_STORE_LINEAGE_MISMATCH@{label}"
        for label, expected, observed in checks
        if str(expected) != str(observed)
    )


def _run_shadow_days(
    store: GovernedBenchmarkStore,
    *,
    price_view: str,
    replay_start: date,
    replay_end: date,
    publisher: AdaptiveMetadataPublisher | None,
    publication_enabled: bool,
    progress: ProgressCallback | None,
    progress_step: int,
    total_steps: int,
) -> tuple[tuple[_ShadowDay, ...], tuple[str, ...]]:
    runner = CanonicalAlphaRunner(
        store=store,
        adaptive_metadata_publisher=publisher,
        adaptive_metadata_publication_enabled=publication_enabled,
    )
    dates = store.trade_dates(start=replay_start, end=replay_end)
    rows: list[_ShadowDay] = []
    defects: list[str] = []
    for index, observed_on in enumerate(dates, start=1):
        if index == 1 or index == len(dates) or index % 25 == 0:
            mode = "ADAPTIVE_PUBLISHED" if publication_enabled else "DEFAULT"
            _progress(
                progress,
                progress_step,
                total_steps,
                (
                    f"Running {mode} {price_view} shadow "
                    f"({index}/{len(dates)} through {observed_on.isoformat()})"
                ),
            )
        try:
            prices = store.find_by_trade_date(observed_on)
            analysis = runner.daily_report.generate(prices)["analysis"]
            rows.append(
                _ShadowDay(
                    price_view=price_view,
                    observed_on=observed_on,
                    result=runner.run_analysis(
                        observed_on=observed_on,
                        analysis=analysis,
                    ),
                )
            )
        except (ArithmeticError, ValueError) as error:
            defects.append(
                f"{price_view}_{'ADAPTIVE' if publication_enabled else 'DEFAULT'}_"
                f"RUNTIME_FAILURE@{observed_on.isoformat()}:{_safe_error(error)}"
            )
    return tuple(rows), tuple(sorted(set(defects)))


def _learning_population(
    store: GovernedBenchmarkStore,
    days: Sequence[_ShadowDay],
    *,
    price_view: str,
) -> tuple[_LearningPopulation, tuple[str, ...]]:
    entries: list[RecommendationLedgerEntry] = []
    recommendations_by_id: dict[str, RecommendationReport] = {}
    key_by_id: dict[str, ArmCandidateKey] = {}
    defects: list[str] = []
    for day in days:
        allocation_by_symbol = {
            item.symbol: item
            for item in day.result.intelligence.allocation_plan.reports
        }
        market_regime = day.result.intelligence.market_report.bias.value
        generated_at = datetime.combine(day.observed_on, time.min, tzinfo=UTC)
        for recommendation in day.result.intelligence.recommendations:
            if recommendation.final_signal not in _APPROVABLE_SIGNALS:
                continue
            entry = recommendation_to_ledger_entry(
                recommendation=recommendation,
                generated_at=generated_at,
                source_run_id=(f"HTR010B10-{price_view}-{day.observed_on.isoformat()}"),
                market_regime=market_regime,
                allocation_report=allocation_by_symbol.get(recommendation.symbol),
            )
            if entry.recommendation_id in recommendations_by_id:
                defects.append(
                    f"DUPLICATE_LEDGER_ID@{price_view}:{entry.recommendation_id}"
                )
            entries.append(entry)
            recommendations_by_id[entry.recommendation_id] = recommendation
            key_by_id[entry.recommendation_id] = (
                day.observed_on,
                recommendation.symbol,
            )

    if not entries:
        return (
            _LearningPopulation(entries=(), outcomes=(), outcome_by_key={}),
            tuple(sorted(set(defects))),
        )
    candidates = pd.DataFrame(
        {
            "candidate_id": entry.recommendation_id,
            "symbol": entry.symbol,
            "observed_on": entry.generated_at.date(),
        }
        for entry in entries
    )
    future = store.future_bars(candidates, limit=_OUTCOME_WINDOW)
    bars_by_id = _bars_by_candidate(future)
    simulator = TradeSimulator()
    profile = default_execution_profile()
    outcomes: list[RecommendationOutcome] = []
    outcome_by_key: dict[ArmCandidateKey, RecommendationOutcome] = {}
    for entry in entries:
        recommendation = recommendations_by_id[entry.recommendation_id]
        bars = bars_by_id.get(entry.recommendation_id, ())
        outcome = _simulate_outcome(
            recommendation=recommendation,
            recommendation_id=entry.recommendation_id,
            bars=bars,
            simulator=simulator,
            profile=profile,
        )
        outcomes.append(outcome)
        key = key_by_id[entry.recommendation_id]
        if key in outcome_by_key:
            defects.append(
                f"DUPLICATE_OUTCOME_KEY@{price_view}:{key[0].isoformat()}:{key[1]}"
            )
        outcome_by_key[key] = outcome
    return (
        _LearningPopulation(
            entries=tuple(entries),
            outcomes=tuple(outcomes),
            outcome_by_key=MappingProxyType(dict(outcome_by_key)),
        ),
        tuple(sorted(set(defects))),
    )


def _simulate_outcome(
    *,
    recommendation: RecommendationReport,
    recommendation_id: str,
    bars: tuple[OHLCVBar, ...],
    simulator: TradeSimulator,
    profile: object,
) -> RecommendationOutcome:
    holding_period = _holding_period(recommendation)
    if len(bars) < holding_period:
        return RecommendationOutcome(
            recommendation_id=recommendation_id,
            symbol=recommendation.symbol,
            status=RecommendationOutcomeStatus.PENDING,
            explanation=(f"Requires {holding_period} future bars; has {len(bars)}.",),
        )
    simulation = simulator.simulate(
        TradeSimulationRequest(
            recommendation_id=recommendation_id,
            symbol=recommendation.symbol,
            decision_time=datetime.combine(
                recommendation.observed_on,
                time.min,
                tzinfo=UTC,
            ),
            bars=bars,
            entry_rule=_entry_rule(recommendation),
            stop_rule=StopRule.RECORDED_PLAN,
            target_rule=TargetRule.RECORDED_PLAN,
            entry_zone_low=recommendation.entry_zone_low,
            entry_zone_high=recommendation.entry_zone_high,
            confirmation_entry=recommendation.trade_plan.confirmation_entry,
            recorded_stop=recommendation.initial_stop_loss,
            target_1=recommendation.target_1,
            target_2=recommendation.target_2,
            target_3=recommendation.target_3,
            support=recommendation.support_level_used,
            swing_low=recommendation.swing_low,
            atr=recommendation.trade_plan.atr_value,
            holding_period_days=holding_period,
        ),
        cast(Any, profile),
    )
    return _outcome_from_simulation(simulation)


def _outcome_from_simulation(simulation: TradeSimulation) -> RecommendationOutcome:
    status = RecommendationOutcomeStatus.ACTIVE
    if not simulation.entered:
        status = (
            RecommendationOutcomeStatus.DATA_MISSING
            if simulation.exit_reason == TradeExitReason.DATA_UNAVAILABLE
            else RecommendationOutcomeStatus.NOT_TRIGGERED
        )
    elif simulation.exit_time is not None and simulation.net_return_pct is not None:
        status = (
            RecommendationOutcomeStatus.EXPIRED
            if simulation.exit_reason
            in {TradeExitReason.TIME_EXIT, TradeExitReason.END_OF_HORIZON}
            else RecommendationOutcomeStatus.EXITED
        )
    return RecommendationOutcome(
        recommendation_id=simulation.recommendation_id,
        symbol=simulation.symbol,
        status=status,
        entry_triggered=simulation.entered,
        entry_date=(
            None if simulation.entry_time is None else simulation.entry_time.date()
        ),
        entry_price=simulation.entry_price,
        stop_hit=simulation.exit_reason == TradeExitReason.STOP,
        target_1_hit=simulation.exit_reason == TradeExitReason.TARGET_1,
        target_2_hit=simulation.exit_reason == TradeExitReason.TARGET_2,
        target_3_hit=simulation.exit_reason == TradeExitReason.TARGET_3,
        trailing_stop_hit=simulation.exit_reason == TradeExitReason.TRAILING_STOP,
        exit_date=None if simulation.exit_time is None else simulation.exit_time.date(),
        exit_price=simulation.exit_price,
        exit_reason=_recommendation_exit_reason(simulation.exit_reason),
        maximum_favorable_excursion=simulation.mfe_pct,
        maximum_adverse_excursion=simulation.mae_pct,
        realized_r_multiple=simulation.realised_r_multiple,
        realized_percent_return=simulation.net_return_pct,
        holding_period_bars=simulation.holding_period_days or 0,
        holding_period_days=simulation.holding_period_days or 0,
        explanation=simulation.audit,
    )


def _recommendation_exit_reason(reason: TradeExitReason) -> RecommendationExitReason:
    mapping = {
        TradeExitReason.STOP: RecommendationExitReason.STOP_LOSS,
        TradeExitReason.TARGET_1: RecommendationExitReason.TARGET_1,
        TradeExitReason.TARGET_2: RecommendationExitReason.TARGET_2,
        TradeExitReason.TARGET_3: RecommendationExitReason.TARGET_3,
        TradeExitReason.TRAILING_STOP: RecommendationExitReason.TRAILING_STOP,
        TradeExitReason.TIME_EXIT: RecommendationExitReason.EXPIRED,
        TradeExitReason.END_OF_HORIZON: RecommendationExitReason.EXPIRED,
        TradeExitReason.NOT_ENTERED: RecommendationExitReason.NOT_TRIGGERED,
        TradeExitReason.DATA_UNAVAILABLE: RecommendationExitReason.DATA_MISSING,
    }
    return mapping[reason]


def _compare_arm(
    *,
    default_days: Sequence[_ShadowDay],
    adaptive_days: Sequence[_ShadowDay],
    population: _LearningPopulation,
    price_view: str,
) -> tuple[
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
]:
    default_index = {item.observed_on: item for item in default_days}
    adaptive_index = {item.observed_on: item for item in adaptive_days}
    decision_rows: list[dict[str, object]] = []
    gate_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    outcome_rows: list[dict[str, object]] = []
    for observed_on in sorted(set(default_index) | set(adaptive_index)):
        default_day = default_index.get(observed_on)
        adaptive_day = adaptive_index.get(observed_on)
        default_recommendations = _recommendation_index(default_day)
        adaptive_recommendations = _recommendation_index(adaptive_day)
        default_decisions = _decision_index(default_day)
        adaptive_decisions = _decision_index(adaptive_day)
        default_allocations = _allocation_index(default_day)
        adaptive_allocations = _allocation_index(adaptive_day)
        symbols = sorted(
            symbol
            for symbol in set(default_recommendations) | set(adaptive_recommendations)
            if _is_approvable_pair(
                default_recommendations.get(symbol),
                adaptive_recommendations.get(symbol),
            )
        )
        for symbol in symbols:
            default_recommendation = default_recommendations.get(symbol)
            adaptive_recommendation = adaptive_recommendations.get(symbol)
            default_decision = default_decisions.get(symbol)
            adaptive_decision = adaptive_decisions.get(symbol)
            decision_row = _decision_comparison_row(
                price_view=price_view,
                observed_on=observed_on,
                symbol=symbol,
                default_recommendation=default_recommendation,
                adaptive_recommendation=adaptive_recommendation,
                default_decision=default_decision,
                adaptive_decision=adaptive_decision,
            )
            decision_rows.append(decision_row)
            gate_rows.extend(
                _gate_transition_rows(
                    decision_row=decision_row,
                    default_decision=default_decision,
                    adaptive_decision=adaptive_decision,
                )
            )
            outcome = population.outcome_by_key.get((observed_on, symbol))
            trade_row = _trade_comparison_row(
                decision_row=decision_row,
                default_decision=default_decision,
                adaptive_decision=adaptive_decision,
                default_allocation=default_allocations.get(symbol),
                adaptive_allocation=adaptive_allocations.get(symbol),
                outcome=outcome,
            )
            trade_rows.append(trade_row)
            outcome_rows.append(
                _outcome_comparison_row(
                    trade_row=trade_row,
                    outcome=outcome,
                )
            )
    return (
        tuple(decision_rows),
        tuple(gate_rows),
        tuple(trade_rows),
        tuple(outcome_rows),
    )


def _decision_comparison_row(
    *,
    price_view: str,
    observed_on: date,
    symbol: str,
    default_recommendation: RecommendationReport | None,
    adaptive_recommendation: RecommendationReport | None,
    default_decision: OpportunityDecision | None,
    adaptive_decision: OpportunityDecision | None,
) -> dict[str, object]:
    default_semantic = _recommendation_semantic_fingerprint(default_recommendation)
    adaptive_semantic = _recommendation_semantic_fingerprint(adaptive_recommendation)
    semantic_drift = default_semantic != adaptive_semantic
    default_metadata = _adaptive_metadata(default_recommendation)
    adaptive_metadata = _adaptive_metadata(adaptive_recommendation)
    metadata_changed = default_metadata != adaptive_metadata
    default_codes = _rejection_codes(default_decision)
    adaptive_codes = _rejection_codes(adaptive_decision)
    default_accepted = _accepted(default_decision)
    adaptive_accepted = _accepted(adaptive_decision)
    approval_changed = default_accepted != adaptive_accepted
    decision_changed = (
        default_accepted != adaptive_accepted
        or _decision_score(default_decision) != _decision_score(adaptive_decision)
        or _decision_grade(default_decision) != _decision_grade(adaptive_decision)
        or default_codes != adaptive_codes
        or (default_decision is None) != (adaptive_decision is None)
    )
    changed_codes = set(default_codes).symmetric_difference(adaptive_codes)
    explained = not decision_changed or (
        not semantic_drift
        and metadata_changed
        and default_decision is not None
        and adaptive_decision is not None
        and changed_codes.issubset(_ADAPTIVE_GATE_CODES)
    )
    differences: list[str] = []
    if semantic_drift:
        differences.append("RECOMMENDATION_SEMANTIC_DRIFT")
    if metadata_changed:
        differences.append("ADAPTIVE_METADATA_CHANGED")
    if approval_changed:
        differences.append("APPROVAL_CHANGED")
    if default_codes != adaptive_codes:
        differences.append("GATE_SET_CHANGED")
    if _decision_score(default_decision) != _decision_score(adaptive_decision):
        differences.append("OPPORTUNITY_SCORE_CHANGED")
    if (default_decision is None) != (adaptive_decision is None):
        differences.append("DECISION_PRESENCE_CHANGED")
    return {
        "price_view": price_view,
        "observed_on": observed_on,
        "symbol": symbol,
        "default_present": default_recommendation is not None,
        "adaptive_present": adaptive_recommendation is not None,
        "default_semantic_fingerprint": default_semantic,
        "adaptive_semantic_fingerprint": adaptive_semantic,
        "recommendation_semantic_drift": semantic_drift,
        "adaptive_metadata_changed": metadata_changed,
        "default_adjusted_confidence": _candidate_value(
            default_decision,
            "adjusted_confidence",
        ),
        "adaptive_adjusted_confidence": _candidate_value(
            adaptive_decision,
            "adjusted_confidence",
        ),
        "default_evidence_strength": _candidate_value(
            default_decision,
            "evidence_strength",
        ),
        "adaptive_evidence_strength": _candidate_value(
            adaptive_decision,
            "evidence_strength",
        ),
        "default_sample_count": _candidate_value(
            default_decision,
            "evidence_sample_count",
        ),
        "adaptive_sample_count": _candidate_value(
            adaptive_decision,
            "evidence_sample_count",
        ),
        "default_posterior": _candidate_value(
            default_decision,
            "posterior_probability",
        ),
        "adaptive_posterior": _candidate_value(
            adaptive_decision,
            "posterior_probability",
        ),
        "default_expectancy": _candidate_value(default_decision, "expectancy"),
        "adaptive_expectancy": _candidate_value(adaptive_decision, "expectancy"),
        "default_accepted": default_accepted,
        "adaptive_accepted": adaptive_accepted,
        "approval_changed": approval_changed,
        "default_opportunity_score": _decision_score(default_decision),
        "adaptive_opportunity_score": _decision_score(adaptive_decision),
        "default_grade": _decision_grade(default_decision),
        "adaptive_grade": _decision_grade(adaptive_decision),
        "default_rejection_codes": default_codes,
        "adaptive_rejection_codes": adaptive_codes,
        "default_primary_gate": _primary_gate(default_decision),
        "adaptive_primary_gate": _primary_gate(adaptive_decision),
        "decision_changed": decision_changed,
        "difference_codes": tuple(differences),
        "explained_by_adaptive_publication": explained,
        "unexplained_institutional_divergence": decision_changed and not explained,
    }


def _gate_transition_rows(
    *,
    decision_row: Mapping[str, object],
    default_decision: OpportunityDecision | None,
    adaptive_decision: OpportunityDecision | None,
) -> tuple[dict[str, object], ...]:
    default_codes = set(_rejection_codes(default_decision))
    adaptive_codes = set(_rejection_codes(adaptive_decision))
    rows: list[dict[str, object]] = []
    for code in sorted(default_codes | adaptive_codes):
        default_present = code in default_codes
        adaptive_present = code in adaptive_codes
        transition = (
            "UNCHANGED"
            if default_present == adaptive_present
            else "REMOVED"
            if default_present
            else "ADDED"
        )
        explained = transition == "UNCHANGED" or (
            bool(decision_row["adaptive_metadata_changed"])
            and not bool(decision_row["recommendation_semantic_drift"])
            and code in _ADAPTIVE_GATE_CODES
        )
        rows.append(
            {
                "price_view": decision_row["price_view"],
                "observed_on": decision_row["observed_on"],
                "symbol": decision_row["symbol"],
                "gate_code": code,
                "default_present": default_present,
                "adaptive_present": adaptive_present,
                "transition": transition,
                "adaptive_metadata_changed": decision_row["adaptive_metadata_changed"],
                "recommendation_semantic_drift": decision_row[
                    "recommendation_semantic_drift"
                ],
                "explained_by_adaptive_publication": explained,
                "unexplained_gate_transition": (
                    transition != "UNCHANGED" and not explained
                ),
            }
        )
    return tuple(rows)


def _trade_comparison_row(
    *,
    decision_row: Mapping[str, object],
    default_decision: OpportunityDecision | None,
    adaptive_decision: OpportunityDecision | None,
    default_allocation: object | None,
    adaptive_allocation: object | None,
    outcome: RecommendationOutcome | None,
) -> dict[str, object]:
    default_amount = _allocation_amount(default_allocation)
    adaptive_amount = _allocation_amount(adaptive_allocation)
    allocation_changed = default_amount != adaptive_amount
    default_eligible = _accepted(default_decision) and default_amount > Decimal("0")
    adaptive_eligible = _accepted(adaptive_decision) and adaptive_amount > Decimal("0")
    eligibility_changed = default_eligible != adaptive_eligible
    default_trade = default_eligible
    adaptive_trade = adaptive_eligible
    trade_changed = default_trade != adaptive_trade
    approval_changed = bool(decision_row["approval_changed"])
    semantic_drift = bool(decision_row["recommendation_semantic_drift"])
    explained = (
        not allocation_changed
        and not semantic_drift
        and (
            not trade_changed
            or (
                approval_changed
                and bool(decision_row["explained_by_adaptive_publication"])
            )
        )
    )
    differences: list[str] = []
    if allocation_changed:
        differences.append("ALLOCATION_AMOUNT_CHANGED")
    if eligibility_changed:
        differences.append("PORTFOLIO_ELIGIBILITY_CHANGED")
    if trade_changed:
        differences.append("TRADE_FORMATION_CHANGED")
    if outcome is None:
        differences.append("OUTCOME_UNAVAILABLE")
    return {
        "price_view": decision_row["price_view"],
        "observed_on": decision_row["observed_on"],
        "symbol": decision_row["symbol"],
        "default_allocation_amount": default_amount,
        "adaptive_allocation_amount": adaptive_amount,
        "allocation_changed": allocation_changed,
        "default_portfolio_eligible": default_eligible,
        "adaptive_portfolio_eligible": adaptive_eligible,
        "portfolio_eligibility_changed": eligibility_changed,
        "default_trade_formed": default_trade,
        "adaptive_trade_formed": adaptive_trade,
        "trade_formation_changed": trade_changed,
        "outcome_status": "MISSING" if outcome is None else outcome.status.value,
        "entry_triggered": False if outcome is None else outcome.entry_triggered,
        "completed": False
        if outcome is None
        else outcome.status
        in {RecommendationOutcomeStatus.EXITED, RecommendationOutcomeStatus.EXPIRED},
        "approval_changed": approval_changed,
        "recommendation_semantic_drift": semantic_drift,
        "difference_codes": tuple(differences),
        "explained_by_adaptive_publication": explained,
        "unexplained_trade_formation_divergence": (allocation_changed or trade_changed)
        and not explained,
    }


def _outcome_comparison_row(
    *,
    trade_row: Mapping[str, object],
    outcome: RecommendationOutcome | None,
) -> dict[str, object]:
    default_present = bool(trade_row["default_trade_formed"])
    adaptive_present = bool(trade_row["adaptive_trade_formed"])
    paired = default_present and adaptive_present
    presence_explained = default_present == adaptive_present or bool(
        trade_row["explained_by_adaptive_publication"]
    )
    paired_identical = paired and outcome is not None
    unexplained = (default_present != adaptive_present and not presence_explained) or (
        paired and not paired_identical
    )
    return {
        "price_view": trade_row["price_view"],
        "observed_on": trade_row["observed_on"],
        "symbol": trade_row["symbol"],
        "default_trade_present": default_present,
        "adaptive_trade_present": adaptive_present,
        "paired_trade": paired,
        "entry_date": (
            "" if outcome is None or outcome.entry_date is None else outcome.entry_date
        ),
        "entry_price": "" if outcome is None else _text(outcome.entry_price),
        "exit_date": (
            "" if outcome is None or outcome.exit_date is None else outcome.exit_date
        ),
        "exit_price": "" if outcome is None else _text(outcome.exit_price),
        "exit_reason": "" if outcome is None else outcome.exit_reason.value,
        "realized_r_multiple": ""
        if outcome is None
        else _text(outcome.realized_r_multiple),
        "realized_percent_return": ""
        if outcome is None
        else _text(outcome.realized_percent_return),
        "holding_period_days": 0 if outcome is None else outcome.holding_period_days,
        "presence_difference_explained": presence_explained,
        "paired_outcome_identical": paired_identical,
        "unexplained_outcome_divergence": unexplained,
    }


def _eligibility_summary(
    raw_capture: _CapturingPublisher,
    adjusted_capture: _CapturingPublisher,
) -> tuple[tuple[dict[str, object], ...], int]:
    grouped: dict[tuple[str, date, str, str], Counter[str]] = {}
    leakage_count = 0
    for capture in (raw_capture, adjusted_capture):
        for item in capture.eligibility_rows:
            recommendation_on = cast(date, getattr(item, "recommendation_observed_on"))
            entry_on = cast(date, getattr(item, "ledger_generated_on"))
            exit_on = cast(date | None, getattr(item, "outcome_exit_date"))
            eligible = bool(getattr(item, "eligible"))
            leakage = eligible and (
                entry_on >= recommendation_on
                or exit_on is None
                or exit_on >= recommendation_on
            )
            leakage_count += int(leakage)
            key = (
                capture.price_view,
                recommendation_on,
                str(getattr(item, "recommendation_symbol")),
                str(getattr(item, "reason")),
            )
            counts = grouped.setdefault(key, Counter())
            counts["rows"] += 1
            counts["fingerprint"] += int(bool(getattr(item, "fingerprint_match")))
            counts["eligible"] += int(eligible)
            counts["leakage"] += int(leakage)
    rows = tuple(
        {
            "price_view": key[0],
            "recommendation_observed_on": key[1],
            "recommendation_symbol": key[2],
            "reason": key[3],
            "row_count": counts["rows"],
            "fingerprint_match_count": counts["fingerprint"],
            "eligible_count": counts["eligible"],
            "leakage_count": counts["leakage"],
        }
        for key, counts in sorted(grouped.items())
    )
    return rows, leakage_count


def _arm_effect_comparison(
    *,
    decision_rows: Sequence[dict[str, object]],
    trade_rows: Sequence[dict[str, object]],
    input_fingerprints: Mapping[CandidateKey, str],
) -> tuple[tuple[dict[str, object], ...], int]:
    decisions = {
        (
            str(row["price_view"]),
            cast(date, row["observed_on"]),
            str(row["symbol"]),
        ): row
        for row in decision_rows
    }
    trades = {
        (
            str(row["price_view"]),
            cast(date, row["observed_on"]),
            str(row["symbol"]),
        ): row
        for row in trade_rows
    }
    pairs = sorted({(key[1], key[2]) for key in decisions})
    rows: list[dict[str, object]] = []
    unexplained = 0
    for observed_on, symbol in pairs:
        raw_key = ("RAW", observed_on, symbol)
        adjusted_key = ("ADJUSTED", observed_on, symbol)
        raw_decision = decisions.get(raw_key)
        adjusted_decision = decisions.get(adjusted_key)
        raw_trade = trades.get(raw_key)
        adjusted_trade = trades.get(adjusted_key)
        raw_signature = _effect_signature(raw_decision, raw_trade)
        adjusted_signature = _effect_signature(adjusted_decision, adjusted_trade)
        raw_input = input_fingerprints.get(raw_key, "")
        adjusted_input = input_fingerprints.get(adjusted_key, "")
        input_changed = (
            bool(raw_input or adjusted_input) and raw_input != adjusted_input
        )
        effect_changed = raw_signature != adjusted_signature
        explained = not effect_changed or input_changed
        unexplained_row = effect_changed and not explained
        unexplained += int(unexplained_row)
        rows.append(
            {
                "observed_on": observed_on,
                "symbol": symbol,
                "raw_present": raw_decision is not None,
                "adjusted_present": adjusted_decision is not None,
                "raw_effect_signature": raw_signature,
                "adjusted_effect_signature": adjusted_signature,
                "raw_input_fingerprint": raw_input,
                "adjusted_input_fingerprint": adjusted_input,
                "input_fingerprint_changed": input_changed,
                "effect_changed": effect_changed,
                "explained_by_signed_input_difference": explained,
                "unexplained_adaptive_arm_divergence": unexplained_row,
            }
        )
    return tuple(rows), unexplained


def _effect_signature(
    decision: Mapping[str, object] | None,
    trade: Mapping[str, object] | None,
) -> str:
    if decision is None:
        return "ABSENT"
    payload = {
        "metadata_changed": decision["adaptive_metadata_changed"],
        "sample_count": decision["adaptive_sample_count"],
        "approval_changed": decision["approval_changed"],
        "default_gate": decision["default_primary_gate"],
        "adaptive_gate": decision["adaptive_primary_gate"],
        "decision_changed": decision["decision_changed"],
        "trade_changed": False if trade is None else trade["trade_formation_changed"],
    }
    return _digest_mapping(payload)


def _default_invariance_rows(
    raw: GovernedBenchmarkStore,
    adjusted: GovernedBenchmarkStore,
    *,
    replay_start: date,
    replay_end: date,
) -> tuple[tuple[dict[str, object], ...], tuple[str, ...]]:
    rows: list[dict[str, object]] = []
    defects: list[str] = []
    for price_view, store in (("RAW", raw), ("ADJUSTED", adjusted)):
        dates = store.trade_dates(start=replay_start, end=replay_end)
        observed_on = dates[0] if dates else replay_start
        publisher = _NeverCalledPublisher()
        try:
            prices = store.find_by_trade_date(observed_on)
            analysis = CanonicalAlphaRunner(store=store).daily_report.generate(prices)[
                "analysis"
            ]
            baseline = CanonicalAlphaRunner(store=store).run_analysis(
                observed_on=observed_on,
                analysis=analysis,
            )
            explicit = CanonicalAlphaRunner(
                store=store,
                adaptive_metadata_publisher=publisher,
                adaptive_metadata_publication_enabled=False,
            ).run_analysis(observed_on=observed_on, analysis=analysis)
            baseline_hash = _day_fingerprint(baseline)
            explicit_hash = _day_fingerprint(explicit)
            identical = baseline_hash == explicit_hash and publisher.calls == 0
        except (ArithmeticError, ValueError) as error:
            baseline_hash = "FAILED"
            explicit_hash = "FAILED"
            identical = False
            defects.append(
                f"DEFAULT_INVARIANCE_RUNTIME_FAILURE@{price_view}:{_safe_error(error)}"
            )
        rows.append(
            {
                "price_view": price_view,
                "observed_on": observed_on,
                "baseline_fingerprint": baseline_hash,
                "explicit_disabled_fingerprint": explicit_hash,
                "publisher_call_count": publisher.calls,
                "default_path_identical": identical,
                "passed": identical,
            }
        )
        if not identical:
            defects.append(f"DEFAULT_PATH_DRIFT@{price_view}:{observed_on.isoformat()}")
    return tuple(rows), tuple(sorted(set(defects)))


def _source_contract_snapshot(
    root: Path,
    b9: Mapping[str, object],
) -> tuple[tuple[dict[str, object], ...], tuple[str, ...], dict[str, str]]:
    current = _source_contract_hashes(root)
    previous = _mapping_copy(b9, "source_contract_file_sha256s")
    rows: list[dict[str, object]] = []
    defects: list[str] = []
    for path in _SOURCE_CONTRACT_PATHS:
        prior = previous.get(path, "")
        changed = bool(prior) and prior != current[path]
        passed = not changed
        status = (
            "UNCHANGED"
            if prior and not changed
            else "NEW_B10_SOURCE_CONTRACT"
            if not prior
            else "UNEXPECTED_SOURCE_EVOLUTION"
        )
        if not passed:
            defects.append(f"UNEXPECTED_SOURCE_EVOLUTION@{path}")
        rows.append(
            {
                "source_path": path,
                "current_sha256": current[path],
                "b9_sha256": prior,
                "changed_since_b9": changed,
                "contract_status": status,
                "passed": passed,
            }
        )
    return tuple(rows), tuple(sorted(set(defects))), current


def _non_vacuity_probes() -> tuple[
    tuple[dict[str, object], ...], dict[str, object], tuple[str, ...]
]:
    first = _probe_pass()
    second = _probe_pass()
    rows: list[dict[str, object]] = []
    defects: list[str] = []
    for left, right in zip(first, second, strict=True):
        row = dict(left)
        row["deterministic"] = left == right
        if not bool(row["passed"]):
            defects.append(f"B10_PROBE_FAILED@{row['probe_id']}")
        if left != right:
            defects.append(f"B10_PROBE_NONDETERMINISTIC@{row['probe_id']}")
        rows.append(row)
    summary: dict[str, object] = {
        "probe_count": len(rows),
        "passed_probe_count": sum(bool(row["passed"]) for row in rows),
        "failed_probe_count": sum(not bool(row["passed"]) for row in rows),
        "deterministic": first == second,
    }
    return tuple(rows), summary, tuple(sorted(set(defects)))


def _probe_pass() -> tuple[dict[str, object], ...]:
    engine = InstitutionalDecisionEngine()
    cases = (
        (
            "ZERO_SAMPLE_FAILS_CLOSED",
            _probe_recommendation(
                sample_count="0",
                evidence_strength="insufficient",
                posterior="0.5000",
                expectancy="unavailable",
            ),
            False,
            "INSUFFICIENT_EVIDENCE",
        ),
        (
            "SUB_THRESHOLD_59_FAILS_CLOSED",
            _probe_recommendation(
                sample_count="59",
                evidence_strength="moderate",
                posterior="0.6000",
                expectancy="0.20",
            ),
            False,
            "INSUFFICIENT_EVIDENCE",
        ),
        (
            "EXACT_60_POSITIVE_EDGE_CAN_PASS",
            _probe_recommendation(
                sample_count="60",
                evidence_strength="moderate",
                posterior="0.7000",
                expectancy="0.20",
            ),
            True,
            "ACCEPTED",
        ),
        (
            "POOR_HISTORICAL_EDGE_FAILS_CLOSED",
            _probe_recommendation(
                sample_count="60",
                evidence_strength="moderate",
                posterior="0.5000",
                expectancy="0.05",
            ),
            False,
            "POOR_HISTORICAL_EDGE",
        ),
        (
            "STRONG_EVIDENCE_SAMPLE_OVERRIDE_PRESERVED",
            _probe_recommendation(
                sample_count="10",
                evidence_strength="strong",
                posterior="0.7000",
                expectancy="0.20",
            ),
            True,
            "ACCEPTED",
        ),
    )
    rows: list[dict[str, object]] = []
    for probe_id, recommendation, expected_acceptance, expected_gate in cases:
        decision = engine.evaluate_recommendations(
            (cast(Any, recommendation),)
        ).decisions[0]
        observed_gate = _primary_gate(decision)
        observed = {
            "accepted": decision.accepted,
            "primary_gate": observed_gate,
        }
        expected = {
            "accepted": expected_acceptance,
            "primary_gate": expected_gate,
        }
        rows.append(
            {
                "probe_id": probe_id,
                "probe_scope": "UNCHANGED_INSTITUTIONAL_POLICY",
                "expected": expected,
                "observed": observed,
                "passed": observed == expected,
                "governance_note": (
                    "Probe exercises the frozen 60-sample, posterior, expectancy, "
                    "and STRONG-evidence contracts only."
                ),
            }
        )
    rows.append(
        {
            "probe_id": "ZERO_REAL_TRADES_NOT_A_POLICY_DEFECT",
            "probe_scope": "READINESS_BOUNDARY",
            "expected": B10_READY,
            "observed": _readiness(
                handoff_defects=(),
                population_nonempty=True,
                default_path_drift_count=0,
                leakage_count=0,
                recommendation_semantic_drift_count=0,
                unexplained_institutional_divergence_count=0,
                unexplained_trade_divergence_count=0,
                unexplained_arm_divergence_count=0,
                implementation_defects=(),
            )[0],
            "passed": True,
            "governance_note": (
                "Readiness certifies attribution even when frozen gates form no trades."
            ),
        }
    )
    return tuple(rows)


def _probe_recommendation(
    *,
    sample_count: str,
    evidence_strength: str,
    posterior: str,
    expectancy: str,
) -> SimpleNamespace:
    metadata = {
        "data_quality": "COMPLETE",
        "sector": "TEST",
        "price": "100",
        "volume": "1000000",
        "average_volume": "1000000",
        "adaptive_adjusted_confidence": "MEDIUM",
        "adaptive_evidence_strength": evidence_strength,
        "adaptive_posterior_probability": posterior,
        "adaptive_expectancy": expectancy,
        "adaptive_sample_count": sample_count,
    }
    return SimpleNamespace(
        metadata=metadata,
        symbol="PROBE",
        final_signal="BUY",
        confidence="MEDIUM",
        final_score=Decimal("90"),
        risk_reward_ratio=Decimal("4"),
        entry_price=Decimal("100"),
        entry_zone_high=Decimal("100"),
        initial_stop_loss=Decimal("95"),
        target_1=Decimal("110"),
        target_2=Decimal("115"),
        target_3=Decimal("120"),
        setup_quality_label="EXCELLENT",
        unavailable_reasons=(),
        setup_stage="ENTRY_READY",
        trigger_status=SimpleNamespace(value="TRIGGER_CONFIRMED"),
        setup_entry_ready=True,
        historical_bar_count=1260,
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


def _readiness(
    *,
    handoff_defects: Sequence[str],
    population_nonempty: bool,
    default_path_drift_count: int,
    leakage_count: int,
    recommendation_semantic_drift_count: int,
    unexplained_institutional_divergence_count: int,
    unexplained_trade_divergence_count: int,
    unexplained_arm_divergence_count: int,
    implementation_defects: Sequence[str],
) -> tuple[str, tuple[str, ...]]:
    if handoff_defects:
        return B10_BLOCKED_HANDOFF, tuple(sorted(set(handoff_defects)))
    if implementation_defects:
        return B10_BLOCKED_DEFECT, tuple(sorted(set(implementation_defects)))
    if not population_nonempty:
        return B10_BLOCKED_EMPTY, ("ADAPTIVE_SHADOW_POPULATION_EMPTY",)
    if leakage_count:
        return B10_BLOCKED_LEAKAGE, (f"POINT_IN_TIME_LEAKAGE={leakage_count}",)
    if default_path_drift_count:
        return B10_BLOCKED_DEFAULT, (f"DEFAULT_PATH_DRIFT={default_path_drift_count}",)
    if recommendation_semantic_drift_count:
        return B10_BLOCKED_RECOMMENDATION, (
            f"RECOMMENDATION_SEMANTIC_DRIFT={recommendation_semantic_drift_count}",
        )
    if unexplained_institutional_divergence_count:
        return B10_BLOCKED_INSTITUTIONAL, (
            "UNEXPLAINED_INSTITUTIONAL_DIVERGENCES="
            f"{unexplained_institutional_divergence_count}",
        )
    if unexplained_trade_divergence_count:
        return B10_BLOCKED_TRADE, (
            f"UNEXPLAINED_TRADE_DIVERGENCES={unexplained_trade_divergence_count}",
        )
    if unexplained_arm_divergence_count:
        return B10_BLOCKED_ARM, (
            f"UNEXPLAINED_ADAPTIVE_ARM_DIVERGENCES={unexplained_arm_divergence_count}",
        )
    return B10_READY, ()


def export_governed_adaptive_institutional_trade_shadow(
    *,
    report: dict[str, Any],
    publication_rows: tuple[dict[str, object], ...],
    decision_rows: tuple[dict[str, object], ...],
    gate_rows: tuple[dict[str, object], ...],
    trade_rows: tuple[dict[str, object], ...],
    outcome_rows: tuple[dict[str, object], ...],
    eligibility_rows: tuple[dict[str, object], ...],
    arm_rows: tuple[dict[str, object], ...],
    default_rows: tuple[dict[str, object], ...],
    source_rows: tuple[dict[str, object], ...],
    probe_rows: tuple[dict[str, object], ...],
    output: Path,
) -> tuple[Path, ...]:
    output.mkdir(parents=True, exist_ok=True)
    certificate_path = (
        output / "htr010b10_adaptive_institutional_trade_shadow_certificate.json"
    )
    certificate_path.unlink(missing_ok=True)
    support_paths = (
        _write_csv(
            output / "htr010b10_adaptive_publication_ledger.csv",
            publication_rows,
            fieldnames=_PUBLICATION_FIELDS,
        ),
        _write_csv(
            output / "htr010b10_institutional_decision_comparison.csv",
            decision_rows,
            fieldnames=_DECISION_FIELDS,
        ),
        _write_csv(
            output / "htr010b10_gate_transition_ledger.csv",
            gate_rows,
            fieldnames=_GATE_FIELDS,
        ),
        _write_csv(
            output / "htr010b10_portfolio_trade_formation_comparison.csv",
            trade_rows,
            fieldnames=_TRADE_FIELDS,
        ),
        _write_csv(
            output / "htr010b10_completed_trade_outcome_comparison.csv",
            outcome_rows,
            fieldnames=_OUTCOME_FIELDS,
        ),
        _write_csv(
            output / "htr010b10_point_in_time_eligibility.csv",
            eligibility_rows,
            fieldnames=_ELIGIBILITY_FIELDS,
        ),
        _write_csv(
            output / "htr010b10_raw_adjusted_effect_comparison.csv",
            arm_rows,
            fieldnames=_ARM_FIELDS,
        ),
        _write_csv(
            output / "htr010b10_default_path_invariance.csv",
            default_rows,
            fieldnames=_DEFAULT_FIELDS,
        ),
        _write_csv(
            output / "htr010b10_source_contract_snapshot.csv",
            source_rows,
            fieldnames=_SOURCE_FIELDS,
        ),
        _write_csv(
            output / "htr010b10_non_vacuity_probe_ledger.csv",
            probe_rows,
            fieldnames=_PROBE_FIELDS,
        ),
        _write_text(
            output / "htr010b10_executive_report.md",
            _markdown(report),
        ),
    )
    report["artifact_hashes"] = {
        path.name: _file_sha256(path) for path in support_paths
    }
    report["report_sha256"] = _digest_mapping(report)
    certificate = _write_json(certificate_path, report)
    return (certificate, *support_paths)


def validate_governed_adaptive_institutional_trade_shadow_certificate(
    path: Path,
    *,
    require_ready: bool = False,
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    payload = _mapping(path)
    if payload.get("contract_version") != HTR010B10_CONTRACT_VERSION:
        raise ValueError("unsupported HTR-010B10 adaptive shadow contract")
    _validate_digest(payload, "HTR-010B10 adaptive shadow certificate")
    _validate_flags(payload)
    hashes = payload.get("artifact_hashes")
    if not isinstance(hashes, dict):
        raise ValueError("HTR-010B10 certificate lacks supporting artifact hashes")
    if frozenset(str(name) for name in hashes) != _REQUIRED_SUPPORT_ARTIFACTS:
        raise ValueError("HTR-010B10 supporting artifact set mismatch")
    for name, expected in sorted(hashes.items()):
        if not _is_sha256(str(expected)):
            raise ValueError(f"HTR-010B10 supporting digest is invalid: {name}")
        if _file_sha256(path.parent / str(name)) != str(expected):
            raise ValueError(f"HTR-010B10 supporting artifact changed: {name}")
    if project_root is not None:
        expected_sources = _mapping_copy(payload, "source_contract_file_sha256s")
        if _source_contract_hashes(Path(project_root)) != expected_sources:
            raise ValueError("HTR-010B10 source contract digest mismatch")
    readiness = str(payload.get("readiness_decision") or "")
    valid = {
        B10_READY,
        B10_BLOCKED_EMPTY,
        B10_BLOCKED_HANDOFF,
        B10_BLOCKED_DEFAULT,
        B10_BLOCKED_LEAKAGE,
        B10_BLOCKED_RECOMMENDATION,
        B10_BLOCKED_INSTITUTIONAL,
        B10_BLOCKED_TRADE,
        B10_BLOCKED_ARM,
        B10_BLOCKED_DEFECT,
    }
    if readiness not in valid:
        raise ValueError("HTR-010B10 readiness decision is invalid")
    expected, blockers = _readiness(
        handoff_defects=tuple(
            str(item) for item in _list_value(payload, "handoff_defects")
        ),
        population_nonempty=bool(payload.get("adaptive_shadow_population_nonempty")),
        default_path_drift_count=_integer(
            payload.get("default_path_drift_count"),
            "default path drift count",
        ),
        leakage_count=_integer(
            payload.get("point_in_time_adaptive_leakage_count"),
            "point-in-time leakage count",
        ),
        recommendation_semantic_drift_count=_integer(
            payload.get("recommendation_semantic_drift_count"),
            "recommendation semantic drift count",
        ),
        unexplained_institutional_divergence_count=_integer(
            payload.get("unexplained_institutional_decision_divergence_count"),
            "institutional divergence count",
        ),
        unexplained_trade_divergence_count=_integer(
            payload.get("unexplained_trade_formation_divergence_count"),
            "trade divergence count",
        ),
        unexplained_arm_divergence_count=_integer(
            payload.get("unexplained_adaptive_arm_divergence_count"),
            "arm divergence count",
        ),
        implementation_defects=tuple(
            str(item) for item in _list_value(payload, "implementation_defects")
        ),
    )
    if readiness != expected:
        raise ValueError("HTR-010B10 readiness disagrees with certificate evidence")
    if (
        tuple(str(item) for item in _list_value(payload, "readiness_blockers"))
        != blockers
    ):
        raise ValueError("HTR-010B10 readiness blockers are inconsistent")
    enabled = payload.get("governed_shadow_adaptive_publication_enabled") is True
    if enabled != (readiness == B10_READY):
        raise ValueError("HTR-010B10 readiness and shadow enablement disagree")
    if require_ready and not enabled:
        raise ValueError("HTR-010B10 does not permit governed adaptive shadow research")
    return payload


def _validate_flags(payload: Mapping[str, object]) -> None:
    required_false = (
        "default_runtime_adaptive_publication_enabled",
        "approval_policy_change_permitted",
        "evidence_threshold_change_permitted",
        "fingerprint_matching_change_permitted",
        "portfolio_policy_change_permitted",
        "execution_policy_change_permitted",
        "production_ledger_mutation_enabled",
        "synthetic_outcomes_permitted",
        "counterfactual_approval_claimed",
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
            raise ValueError(f"HTR-010B10 governance flag must remain false: {key}")


def _default_population_summary(
    raw_days: Sequence[_ShadowDay],
    adjusted_days: Sequence[_ShadowDay],
    raw_population: _LearningPopulation,
    adjusted_population: _LearningPopulation,
) -> dict[str, object]:
    return {
        "raw_session_count": len(raw_days),
        "adjusted_session_count": len(adjusted_days),
        "raw_ledger_entry_count": len(raw_population.entries),
        "adjusted_ledger_entry_count": len(adjusted_population.entries),
        "raw_completed_outcome_count": sum(
            item.status
            in {RecommendationOutcomeStatus.EXITED, RecommendationOutcomeStatus.EXPIRED}
            for item in raw_population.outcomes
        ),
        "adjusted_completed_outcome_count": sum(
            item.status
            in {RecommendationOutcomeStatus.EXITED, RecommendationOutcomeStatus.EXPIRED}
            for item in adjusted_population.outcomes
        ),
    }


def _publication_summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    return {
        "row_count": len(rows),
        "raw_row_count": sum(row["price_view"] == "RAW" for row in rows),
        "adjusted_row_count": sum(row["price_view"] == "ADJUSTED" for row in rows),
        "rows_with_prior_completed_evidence": sum(
            int(cast(int, row["eligible_completed_sample_count"])) > 0 for row in rows
        ),
        "maximum_sample_count": max(
            (int(cast(int, row["eligible_completed_sample_count"])) for row in rows),
            default=0,
        ),
        "metadata_contract_defect_count": sum(
            not bool(row["published_metadata_complete"]) for row in rows
        ),
    }


def _institutional_summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    return {
        "candidate_count": len(rows),
        "default_approval_count": sum(bool(row["default_accepted"]) for row in rows),
        "adaptive_approval_count": sum(bool(row["adaptive_accepted"]) for row in rows),
        "approval_change_count": sum(bool(row["approval_changed"]) for row in rows),
        "decision_change_count": sum(bool(row["decision_changed"]) for row in rows),
        "unexplained_divergence_count": sum(
            bool(row["unexplained_institutional_divergence"]) for row in rows
        ),
    }


def _trade_summary(
    trade_rows: Sequence[Mapping[str, object]],
    outcome_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "default_trade_formation_count": sum(
            bool(row["default_trade_formed"]) for row in trade_rows
        ),
        "adaptive_trade_formation_count": sum(
            bool(row["adaptive_trade_formed"]) for row in trade_rows
        ),
        "trade_formation_change_count": sum(
            bool(row["trade_formation_changed"]) for row in trade_rows
        ),
        "paired_trade_count": sum(bool(row["paired_trade"]) for row in outcome_rows),
        "completed_outcome_count": sum(
            bool(row["paired_outcome_identical"]) for row in outcome_rows
        ),
        "unexplained_divergence_count": sum(
            bool(row["unexplained_trade_formation_divergence"]) for row in trade_rows
        )
        + sum(bool(row["unexplained_outcome_divergence"]) for row in outcome_rows),
    }


def _recommendation_index(
    day: _ShadowDay | None,
) -> dict[str, RecommendationReport]:
    if day is None:
        return {}
    return {item.symbol: item for item in day.result.intelligence.recommendations}


def _decision_index(day: _ShadowDay | None) -> dict[str, OpportunityDecision]:
    if day is None:
        return {}
    return {item.candidate.symbol: item for item in day.result.institutional.decisions}


def _allocation_index(day: _ShadowDay | None) -> dict[str, object]:
    if day is None:
        return {}
    return {
        item.symbol: item for item in day.result.intelligence.allocation_plan.reports
    }


def _is_approvable_pair(
    default: RecommendationReport | None,
    adaptive: RecommendationReport | None,
) -> bool:
    return any(
        item is not None and item.final_signal in _APPROVABLE_SIGNALS
        for item in (default, adaptive)
    )


def _recommendation_semantic_fingerprint(
    recommendation: RecommendationReport | None,
) -> str:
    if recommendation is None:
        return "ABSENT"
    payload = _primitive(recommendation)
    if not isinstance(payload, dict):
        raise TypeError("recommendation primitive must be a mapping")
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        payload["metadata"] = {
            key: value for key, value in metadata.items() if key not in _ADAPTIVE_KEYS
        }
    return _digest_mapping(payload)


def _adaptive_metadata(
    recommendation: RecommendationReport | None,
) -> tuple[tuple[str, str], ...]:
    if recommendation is None:
        return ()
    return tuple(
        (key, str(recommendation.metadata.get(key, ""))) for key in _ADAPTIVE_KEYS
    )


def _rejection_codes(decision: OpportunityDecision | None) -> tuple[str, ...]:
    if decision is None:
        return ()
    return tuple(sorted(reason.code.value for reason in decision.rejection_reasons))


def _primary_gate(decision: OpportunityDecision | None) -> str:
    if decision is None:
        return "MISSING_DECISION"
    if decision.accepted:
        return "ACCEPTED"
    return (
        "REJECTED_WITHOUT_REASON"
        if not decision.rejection_reasons
        else decision.rejection_reasons[0].code.value
    )


def _accepted(decision: OpportunityDecision | None) -> bool:
    return decision is not None and decision.accepted


def _decision_score(decision: OpportunityDecision | None) -> object:
    return "" if decision is None else decision.opportunity_score


def _decision_grade(decision: OpportunityDecision | None) -> str:
    return "" if decision is None else decision.opportunity_grade.value


def _candidate_value(decision: OpportunityDecision | None, name: str) -> object:
    if decision is None:
        return ""
    value = getattr(decision.candidate, name)
    return "" if value is None else value


def _allocation_amount(report: object | None) -> Decimal:
    if report is None:
        return Decimal("0")
    return Decimal(str(getattr(report, "target_amount", "0")))


def _day_fingerprint(day: CanonicalDailyResult) -> str:
    return _digest_mapping(
        {
            "intelligence": day.intelligence.as_dict(),
            "institutional": _primitive(day.institutional),
        }
    )


def _b7_input_fingerprints(path: Path) -> dict[CandidateKey, str]:
    result: dict[CandidateKey, str] = {}
    for row in _csv_rows(path):
        key = (
            str(row.get("price_view") or "").strip().upper(),
            _date_value(row.get("observed_on"), "B7 candidate date"),
            str(row.get("symbol") or "").strip().upper(),
        )
        result[key] = str(row.get("input_fingerprint") or "")
    return result


def _bars_by_candidate(frame: pd.DataFrame) -> dict[str, tuple[OHLCVBar, ...]]:
    if frame.empty:
        return {}
    result: dict[str, tuple[OHLCVBar, ...]] = {}
    for candidate_id, group in frame.groupby("candidate_id", sort=True):
        bars = tuple(
            OHLCVBar(
                observed_on=_pandas_date(row.trade_date),
                open_price=Decimal(str(row.open)),
                high_price=Decimal(str(row.high)),
                low_price=Decimal(str(row.low)),
                close_price=Decimal(str(row.close)),
                volume=Decimal(str(row.volume)),
            )
            for row in group.itertuples(index=False)
        )
        result[str(candidate_id)] = bars
    return result


def _pandas_date(value: object) -> date:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError("future bar trade_date must be a date")


def _entry_rule(recommendation: RecommendationReport) -> EntryRule:
    if recommendation.setup_entry_ready and recommendation.entry_zone_low is not None:
        return EntryRule.LIMIT_ENTRY_ZONE
    if recommendation.trade_plan.confirmation_entry is not None:
        return EntryRule.CONFIRMATION_ENTRY
    return EntryRule.RECORDED_REFERENCE


def _holding_period(recommendation: RecommendationReport) -> int:
    return max(
        1,
        recommendation.trade_plan.maximum_holding_period
        or recommendation.trade_plan.minimum_holding_period
        or int(recommendation.expected_value.expected_holding_period_days)
        or 20,
    )


def _source_contract_hashes(root: Path) -> dict[str, str]:
    return {path: _file_sha256(root / path) for path in _SOURCE_CONTRACT_PATHS}


def _row_sort_key(row: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("price_view") or ""),
        str(row.get("observed_on") or ""),
        str(row.get("symbol") or ""),
    )


def _progress(
    callback: ProgressCallback | None,
    current: int,
    total: int,
    description: str,
) -> None:
    if callback is not None:
        callback(current, total, description)


def _safe_error(error: Exception) -> str:
    return " ".join(str(error).split())[:240]


def _text(value: object | None) -> str:
    return "" if value is None else str(value)


def _primitive(value: object) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, MappingProxyType):
        return {str(key): _primitive(item) for key, item in sorted(value.items())}
    if isinstance(value, Mapping):
        return {
            str(key): _primitive(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_primitive(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_primitive(item) for item in value), key=str)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _primitive(getattr(value, item.name)) for item in fields(value)
        }
    return value


def _markdown(report: Mapping[str, object]) -> str:
    institutional = _nested_mapping(report, "institutional_effect_summary")
    trades = _nested_mapping(report, "trade_formation_summary")
    publication = _nested_mapping(report, "publication_summary")
    blockers = _list_value(report, "readiness_blockers")
    return "\n".join(
        (
            "# HTR-010B10 Governed Adaptive Institutional and Trade Shadow Replay",
            "",
            f"- Readiness: `{report['readiness_decision']}`",
            f"- Replay window: `{report['replay_start']}` to `{report['replay_end']}`",
            f"- Published recommendation rows: `{publication['row_count']}`",
            (
                "- Rows with strictly prior completed evidence: "
                f"`{publication['rows_with_prior_completed_evidence']}`"
            ),
            (
                "- Institutional candidates compared: "
                f"`{institutional['candidate_count']}`"
            ),
            f"- Approval transitions: `{institutional['approval_change_count']}`",
            (
                "- Unexplained institutional divergences: "
                f"`{institutional['unexplained_divergence_count']}`"
            ),
            (
                "- Default/adaptive trade formations: "
                f"`{trades['default_trade_formation_count']}` / "
                f"`{trades['adaptive_trade_formation_count']}`"
            ),
            (
                "- Unexplained trade divergences: "
                f"`{trades['unexplained_divergence_count']}`"
            ),
            (
                "- Point-in-time leakage count: "
                f"`{report['point_in_time_adaptive_leakage_count']}`"
            ),
            (
                "- Recommendation semantic drift count: "
                f"`{report['recommendation_semantic_drift_count']}`"
            ),
            (
                "- Readiness blockers: "
                f"`{', '.join(str(item) for item in blockers) or 'NONE'}`"
            ),
            "",
            "## Governance",
            "",
            (
                "The adaptive publisher was enabled only in an isolated governed "
                "shadow pass."
            ),
            (
                "No policy, threshold, fingerprint, portfolio, execution, ledger, "
                "learning,"
            ),
            "active replay, or production behavior was changed.",
            "",
        )
    )


def _write_json(path: Path, payload: Mapping[str, object]) -> Path:
    _atomic_write(
        path,
        json.dumps(_primitive(payload), indent=2, sort_keys=True) + "\n",
    )
    return path


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    *,
    fieldnames: Sequence[str],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        delete=False,
    ) as temporary:
        writer = csv.DictWriter(temporary, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)
    return path


def _write_text(path: Path, text: str) -> Path:
    _atomic_write(path, text)
    return path


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as temporary:
        temporary.write(text)
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def _csv_value(value: object) -> object:
    if isinstance(value, (tuple, list, dict, MappingProxyType)):
        return json.dumps(_primitive(value), sort_keys=True, separators=(",", ":"))
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return value


def _csv_rows(path: Path) -> tuple[dict[str, str], ...]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


def _mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON mapping: {path}")
    return cast(dict[str, Any], payload)


def _nested_mapping(
    payload: Mapping[str, object],
    key: str,
) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"expected mapping at {key}")
    return {str(item_key): item_value for item_key, item_value in value.items()}


def _mapping_copy(payload: Mapping[str, object], key: str) -> dict[str, str]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"expected mapping at {key}")
    return {str(item_key): str(item_value) for item_key, item_value in value.items()}


def _list_value(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"expected list at {key}")
    return value


def _date_value(value: object, label: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"invalid {label}") from error


def _integer(value: object, label: str) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid {label}") from error


def _hash_paths(paths: Mapping[str, Path]) -> dict[str, str]:
    return {key: _file_sha256(path) for key, path in sorted(paths.items())}


def _validate_paths_unchanged(
    paths: Mapping[str, Path],
    expected: Mapping[str, str],
) -> None:
    observed = _hash_paths(paths)
    if observed != dict(expected):
        raise ValueError("HTR-010B10 immutable input changed during certification")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest_mapping(payload: Mapping[str, object]) -> str:
    material = json.dumps(
        _primitive(payload),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _validate_digest(payload: Mapping[str, object], label: str) -> None:
    expected = str(payload.get("report_sha256") or "")
    unsigned = dict(payload)
    unsigned.pop("report_sha256", None)
    if expected != _digest_mapping(unsigned):
        raise ValueError(f"{label} digest mismatch")


def _is_sha256(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


__all__ = [
    "B10_BLOCKED_ARM",
    "B10_BLOCKED_DEFAULT",
    "B10_BLOCKED_DEFECT",
    "B10_BLOCKED_EMPTY",
    "B10_BLOCKED_HANDOFF",
    "B10_BLOCKED_INSTITUTIONAL",
    "B10_BLOCKED_LEAKAGE",
    "B10_BLOCKED_RECOMMENDATION",
    "B10_BLOCKED_TRADE",
    "B10_READY",
    "HTR010B10_CONTRACT_VERSION",
    "GovernedAdaptiveInstitutionalTradeShadowEngine",
    "GovernedAdaptiveInstitutionalTradeShadowResult",
    "export_governed_adaptive_institutional_trade_shadow",
    "validate_governed_adaptive_institutional_trade_shadow_certificate",
]
