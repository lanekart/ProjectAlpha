"""Governed approval-constraint frontier and remediation attribution for HTR-010B6."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, cast

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
from alpha.decision_intelligence import RejectionReasonCode, StressReasonCode

HTR010B6_CONTRACT_VERSION = "HTR-010B6-v1.0.0"

B6_READY = "READY_FOR_GOVERNED_APPROVAL_CONSTRAINT_RESEARCH"
B6_BLOCKED_EMPTY = "BLOCKED_BY_EMPTY_APPROVAL_CONSTRAINT_POPULATION"
B6_BLOCKED_EVIDENCE = "BLOCKED_BY_INCOMPLETE_APPROVAL_CONSTRAINT_EVIDENCE"
B6_BLOCKED_DEFECT = "BLOCKED_BY_CONSTRAINT_FRONTIER_IMPLEMENTATION_DEFECT"
B6_BLOCKED_DIVERGENCE = "BLOCKED_BY_UNEXPLAINED_CONSTRAINT_FRONTIER_DIVERGENCE"

RESEARCH_SCOPE = "GOVERNED_APPROVAL_CONSTRAINT_FRONTIER_ONLY"

ProgressCallback = Callable[[int, int, str], None]
CandidateKey = tuple[str, date, str]

_B5_CANDIDATE_ARTIFACT = "htr010b5_candidate_gate_forensics.csv"
_B5_GATE_ARTIFACT = "htr010b5_gate_event_ledger.csv"
_REQUIRED_B6_SUPPORT_ARTIFACTS = frozenset(
    {
        "htr010b6_candidate_constraint_frontier.csv",
        "htr010b6_constraint_margin_ledger.csv",
        "htr010b6_gate_bottleneck_prevalence.csv",
        "htr010b6_minimal_remediation_sets.csv",
        "htr010b6_raw_adjusted_constraint_comparison.csv",
        "htr010b6_threshold_contract_snapshot.csv",
        "htr010b6_counterfactual_probe_ledger.csv",
        "htr010b6_executive_report.md",
    }
)

_FRONTIER_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "final_signal",
    "terminal_stage",
    "terminal_gate",
    "distinct_gate_count",
    "failed_constraint_count",
    "measurable_constraint_count",
    "categorical_constraint_count",
    "minimum_remediation_count",
    "remediation_classes",
    "nearest_constraint_ids",
    "total_normalized_gap",
    "maximum_normalized_gap",
    "frontier_rank",
    "constraint_evidence_complete",
    "input_fingerprint",
)
_MARGIN_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "final_signal",
    "terminal_stage",
    "terminal_gate",
    "stage",
    "gate_code",
    "constraint_id",
    "metric",
    "comparator",
    "threshold",
    "observed_value",
    "margin_to_threshold",
    "gap_to_clear",
    "normalized_gap",
    "measurable",
    "remediation_class",
    "remediation_action",
    "primary",
    "input_fingerprint",
)
_PREVALENCE_FIELDS = (
    "price_view",
    "stage",
    "gate_code",
    "remediation_class",
    "failed_candidate_count",
    "primary_candidate_count",
    "measurable_constraint_count",
    "categorical_constraint_count",
    "candidate_percent",
    "average_gap_to_clear",
    "median_gap_to_clear",
    "maximum_gap_to_clear",
)
_REMEDIATION_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "remediation_set_id",
    "minimum_remediation_count",
    "gate_codes",
    "constraint_ids",
    "remediation_classes",
    "measurable_constraint_count",
    "categorical_constraint_count",
    "total_normalized_gap",
    "policy_threshold_change_required",
    "counterfactual_approval_claimed",
    "input_fingerprint",
)
_COMPARISON_FIELDS = (
    "observed_on",
    "symbol",
    "raw_present",
    "adjusted_present",
    "raw_input_fingerprint",
    "adjusted_input_fingerprint",
    "input_changed",
    "raw_constraint_ids",
    "adjusted_constraint_ids",
    "constraint_set_changed",
    "raw_remediation_classes",
    "adjusted_remediation_classes",
    "raw_minimum_remediation_count",
    "adjusted_minimum_remediation_count",
    "remediation_count_delta",
    "raw_total_normalized_gap",
    "adjusted_total_normalized_gap",
    "normalized_gap_delta",
    "explained_constraint_difference",
    "unexplained_constraint_divergence",
)
_THRESHOLD_FIELDS = (
    "constraint_id",
    "stage",
    "gate_code",
    "metric",
    "comparator",
    "threshold",
    "unit",
    "measurable",
    "remediation_class",
    "remediation_action",
    "source_path",
    "source_symbol",
)
_PROBE_FIELDS = (
    "probe_id",
    "constraint_id",
    "comparator",
    "threshold",
    "below_observed",
    "below_gap_to_clear",
    "at_observed",
    "at_gap_to_clear",
    "above_observed",
    "above_gap_to_clear",
    "expectation_matched",
    "deterministic",
)


@dataclass(frozen=True, slots=True)
class ConstraintSpec:
    """One frozen policy constraint in the B6 threshold contract."""

    constraint_id: str
    stage: str
    gate_code: str
    metric: str
    comparator: str
    threshold: Decimal | None
    unit: str
    measurable: bool
    remediation_class: str
    remediation_action: str
    source_path: str
    source_symbol: str

    def as_dict(self) -> dict[str, object]:
        return cast(dict[str, object], asdict(self))


@dataclass(frozen=True, slots=True)
class GovernedApprovalConstraintFrontierResult:
    """Signed B6 certificate plus deterministic constraint-frontier evidence."""

    report: dict[str, Any]
    frontier_rows: tuple[dict[str, object], ...]
    margin_rows: tuple[dict[str, object], ...]
    prevalence_rows: tuple[dict[str, object], ...]
    remediation_rows: tuple[dict[str, object], ...]
    comparison_rows: tuple[dict[str, object], ...]
    threshold_rows: tuple[dict[str, object], ...]
    probe_rows: tuple[dict[str, object], ...]
    paths: tuple[Path, ...]


_BASE_ACTIONS: dict[str, tuple[str, str]] = {
    "WEAK_VERDICT": (
        "SIGNAL_ELIGIBILITY",
        "Wait for a BUY or STRONG_BUY recommendation under the frozen recommender.",
    ),
    "WEAK_CONFIDENCE": (
        "EVIDENCE_QUALITY",
        "Accumulate evidence sufficient to reach MEDIUM adjusted confidence.",
    ),
    "INSUFFICIENT_EVIDENCE": (
        "EVIDENCE_ACCUMULATION",
        "Accumulate completed matched-setup evidence without changing the sample rule.",
    ),
    "POOR_REWARD_RISK": (
        "TRADE_PLAN_QUALITY",
        "Improve entry, stop, or target geometry under the frozen reward/risk rule.",
    ),
    "EXCESS_DOWNSIDE_RISK": (
        "RISK_CONTROL",
        "Wait for a tighter structural entry or stop distance.",
    ),
    "POOR_DATA_COMPLETENESS": (
        "DATA_QUALITY",
        "Complete the required point-in-time decision inputs.",
    ),
    "INSUFFICIENT_CAPACITY": (
        "CAPACITY",
        "Improve observed liquidity or reduce intended deployable capital.",
    ),
    "LIVE_FEED_UNHEALTHY": (
        "DATA_QUALITY",
        "Restore acceptable feed health before any live-mode use.",
    ),
    "WEAK_SETUP": (
        "SETUP_QUALITY",
        "Wait for stronger setup evidence under the frozen quality rules.",
    ),
    "MISSING_TRADE_PLAN": (
        "TRADE_PLAN_COMPLETION",
        "Complete entry, stop, targets, ATR, and 20-DMA invalidation evidence.",
    ),
    "PENDING_ENTRY_TRIGGER": (
        "ENTRY_CONFIRMATION",
        "Wait for actionable entry readiness and a confirmed trigger.",
    ),
    "LATE_ENTRY": (
        "ENTRY_CONFIRMATION",
        "Wait for a fresh entry rather than chase a late setup.",
    ),
    "POOR_HISTORICAL_EDGE": (
        "HISTORICAL_EDGE",
        "Accumulate positive matched-setup outcomes under the frozen edge tests.",
    ),
}
_STRESS_ACTIONS: dict[str, tuple[str, str]] = {
    "WEAK_EVIDENCE_HIGH_SCORE": (
        "EVIDENCE_QUALITY",
        "Strengthen adaptive evidence supporting the technical score.",
    ),
    "HIGH_CONFIDENCE_LOW_SAMPLE": (
        "EVIDENCE_ACCUMULATION",
        "Accumulate enough completed outcomes to support high confidence.",
    ),
    "POOR_REWARD_RISK": (
        "TRADE_PLAN_QUALITY",
        "Improve stressed reward/risk to the frozen 2.5R requirement.",
    ),
    "BAD_MARKET_REGIME": (
        "MARKET_REGIME",
        "Wait for a non-bearish market regime.",
    ),
    "SECTOR_CROWDING": (
        "SECTOR_CAPACITY",
        "Reduce sector crowding or wait for better sector fit.",
    ),
    "EXCESSIVE_VOLATILITY": (
        "RISK_CONTROL",
        "Wait for a lower-volatility entry with a tighter stop distance.",
    ),
    "LOW_CAPACITY": (
        "CAPACITY",
        "Improve stressed liquidity and capacity evidence.",
    ),
    "STALE_OR_INCOMPLETE_DATA": (
        "DATA_QUALITY",
        "Refresh and complete all decision evidence.",
    ),
    "STOP_TOO_CLOSE": (
        "RISK_CONTROL",
        "Use a structurally valid stop outside routine noise.",
    ),
    "STOP_TOO_WIDE": (
        "RISK_CONTROL",
        "Wait for an entry supporting a narrower structural stop.",
    ),
    "TARGET_TOO_OPTIMISTIC": (
        "TRADE_PLAN_QUALITY",
        "Use more realistic targets or partial-profit structure.",
    ),
    "CORRELATION_CONCENTRATION": (
        "PORTFOLIO_FIT",
        "Reduce correlation or concentration before deployment.",
    ),
    "CONFLICTING_SIGNALS": (
        "SIGNAL_CONSISTENCY",
        "Resolve conflicting signals before deployment.",
    ),
    "RECENT_FAILED_SIMILAR_SETUP": (
        "HISTORICAL_EDGE",
        "Wait for the recent matched-setup failure evidence to improve.",
    ),
    "FRAGILE_NEAR_RESISTANCE": (
        "ENTRY_CONFIRMATION",
        "Require a less fragile entry away from resistance.",
    ),
    "GAP_RISK": (
        "EXECUTION_RISK",
        "Wait for reduced gap-risk vulnerability.",
    ),
    "BUY_CONTRADICTED_BY_SELL_INDICATORS": (
        "SIGNAL_CONSISTENCY",
        "Resolve sell-side indicator contradictions.",
    ),
    "INSUFFICIENT_FIVE_YEAR_HISTORY": (
        "HISTORY_COVERAGE",
        "Accumulate five years of historical bars before relying on pattern evidence.",
    ),
    "STRESS_FINAL_ACTION": (
        "STRESS_QUALITY",
        "Improve the complete stress-stage quality result under frozen rules.",
    ),
}
_TRADE_PLAN_ACTION = (
    "TRADE_PLAN_QUALITY",
    "Improve the optimized trade-plan quality score under the frozen rule.",
)


def _numeric_specs() -> tuple[ConstraintSpec, ...]:
    engine = "alpha/decision_intelligence/engine.py"
    stress = "alpha/decision_intelligence/stress.py"
    tradeplan = "alpha/decision_intelligence/tradeplan.py"
    return (
        ConstraintSpec(
            "BASE.WEAK_CONFIDENCE.CONFIDENCE_RANK",
            "BASE_GATE",
            "WEAK_CONFIDENCE",
            "adjusted_confidence_rank",
            "GE",
            Decimal("1"),
            "ordinal",
            True,
            "EVIDENCE_QUALITY",
            _BASE_ACTIONS["WEAK_CONFIDENCE"][1],
            engine,
            "_confidence_rank(MEDIUM)",
        ),
        ConstraintSpec(
            "BASE.WEAK_SETUP.FINAL_SCORE",
            "BASE_GATE",
            "WEAK_SETUP",
            "recommendation_score",
            "GE",
            Decimal("85"),
            "points",
            True,
            "SETUP_QUALITY",
            _BASE_ACTIONS["WEAK_SETUP"][1],
            engine,
            "_MIN_DEPLOYMENT_SCORE",
        ),
        ConstraintSpec(
            "BASE.INSUFFICIENT_EVIDENCE.SAMPLE_COUNT",
            "BASE_GATE",
            "INSUFFICIENT_EVIDENCE",
            "evidence_sample_count",
            "GE",
            Decimal("60"),
            "completed_samples",
            True,
            "EVIDENCE_ACCUMULATION",
            _BASE_ACTIONS["INSUFFICIENT_EVIDENCE"][1],
            engine,
            "_MIN_APPROVAL_SAMPLE_COUNT",
        ),
        ConstraintSpec(
            "BASE.POOR_HISTORICAL_EDGE.POSTERIOR",
            "BASE_GATE",
            "POOR_HISTORICAL_EDGE",
            "posterior_probability",
            "GE",
            Decimal("0.52"),
            "probability",
            True,
            "HISTORICAL_EDGE",
            _BASE_ACTIONS["POOR_HISTORICAL_EDGE"][1],
            engine,
            "_MIN_APPROVAL_POSTERIOR",
        ),
        ConstraintSpec(
            "BASE.POOR_HISTORICAL_EDGE.EXPECTANCY",
            "BASE_GATE",
            "POOR_HISTORICAL_EDGE",
            "expectancy",
            "GE",
            Decimal("0.10"),
            "expectancy",
            True,
            "HISTORICAL_EDGE",
            _BASE_ACTIONS["POOR_HISTORICAL_EDGE"][1],
            engine,
            "_MIN_APPROVAL_EXPECTANCY",
        ),
        ConstraintSpec(
            "BASE.POOR_REWARD_RISK.REWARD_RISK",
            "BASE_GATE",
            "POOR_REWARD_RISK",
            "reward_risk_ratio",
            "GE",
            Decimal("2"),
            "R",
            True,
            "TRADE_PLAN_QUALITY",
            _BASE_ACTIONS["POOR_REWARD_RISK"][1],
            engine,
            "institutional minimum reward/risk",
        ),
        ConstraintSpec(
            "BASE.EXCESS_DOWNSIDE_RISK.STOP_DISTANCE",
            "BASE_GATE",
            "EXCESS_DOWNSIDE_RISK",
            "stop_distance_percent",
            "LE",
            Decimal("10"),
            "percent",
            True,
            "RISK_CONTROL",
            _BASE_ACTIONS["EXCESS_DOWNSIDE_RISK"][1],
            engine,
            "_MAX_DEPLOYMENT_STOP_DISTANCE",
        ),
        ConstraintSpec(
            "BASE.INSUFFICIENT_CAPACITY.CAPACITY_SCORE",
            "BASE_GATE",
            "INSUFFICIENT_CAPACITY",
            "capacity_score",
            "GE",
            Decimal("35"),
            "points",
            True,
            "CAPACITY",
            _BASE_ACTIONS["INSUFFICIENT_CAPACITY"][1],
            engine,
            "base capacity minimum",
        ),
        ConstraintSpec(
            "STRESS.HIGH_CONFIDENCE_LOW_SAMPLE.SAMPLE_COUNT",
            "STRESS_TEST",
            "HIGH_CONFIDENCE_LOW_SAMPLE",
            "evidence_sample_count",
            "GE",
            Decimal("10"),
            "completed_samples",
            True,
            "EVIDENCE_ACCUMULATION",
            _STRESS_ACTIONS["HIGH_CONFIDENCE_LOW_SAMPLE"][1],
            stress,
            "high-confidence sample minimum",
        ),
        ConstraintSpec(
            "STRESS.POOR_REWARD_RISK.REWARD_RISK",
            "STRESS_TEST",
            "POOR_REWARD_RISK",
            "reward_risk_ratio",
            "GE",
            Decimal("2.5"),
            "R",
            True,
            "TRADE_PLAN_QUALITY",
            _STRESS_ACTIONS["POOR_REWARD_RISK"][1],
            stress,
            "stressed reward/risk minimum",
        ),
        ConstraintSpec(
            "STRESS.EXCESSIVE_VOLATILITY.STOP_DISTANCE",
            "STRESS_TEST",
            "EXCESSIVE_VOLATILITY",
            "stop_distance_percent",
            "LE",
            Decimal("10"),
            "percent",
            True,
            "RISK_CONTROL",
            _STRESS_ACTIONS["EXCESSIVE_VOLATILITY"][1],
            stress,
            "excessive-volatility stop maximum",
        ),
        ConstraintSpec(
            "STRESS.LOW_CAPACITY.CAPACITY_SCORE",
            "STRESS_TEST",
            "LOW_CAPACITY",
            "capacity_score",
            "GE",
            Decimal("50"),
            "points",
            True,
            "CAPACITY",
            _STRESS_ACTIONS["LOW_CAPACITY"][1],
            stress,
            "stressed capacity minimum",
        ),
        ConstraintSpec(
            "STRESS.STOP_TOO_CLOSE.STOP_DISTANCE",
            "STRESS_TEST",
            "STOP_TOO_CLOSE",
            "stop_distance_percent",
            "GE",
            Decimal("2"),
            "percent",
            True,
            "RISK_CONTROL",
            _STRESS_ACTIONS["STOP_TOO_CLOSE"][1],
            stress,
            "minimum structurally valid stop distance",
        ),
        ConstraintSpec(
            "STRESS.STOP_TOO_WIDE.STOP_DISTANCE",
            "STRESS_TEST",
            "STOP_TOO_WIDE",
            "stop_distance_percent",
            "LE",
            Decimal("12"),
            "percent",
            True,
            "RISK_CONTROL",
            _STRESS_ACTIONS["STOP_TOO_WIDE"][1],
            stress,
            "maximum structurally valid stop distance",
        ),
        ConstraintSpec(
            "TRADE_PLAN.TRADE_PLAN_FINAL_ACTION.QUALITY_SCORE",
            "TRADE_PLAN",
            "TRADE_PLAN_FINAL_ACTION",
            "trade_plan_quality_score",
            "GE",
            Decimal("70"),
            "points",
            True,
            "TRADE_PLAN_QUALITY",
            _TRADE_PLAN_ACTION[1],
            tradeplan,
            "minimum optimized trade-plan quality",
        ),
    )


def _categorical_specs() -> tuple[ConstraintSpec, ...]:
    rows: list[ConstraintSpec] = []
    for base_code in RejectionReasonCode:
        remediation_class, action = _BASE_ACTIONS[base_code.value]
        rows.append(
            ConstraintSpec(
                f"BASE.{base_code.value}.CATEGORICAL",
                "BASE_GATE",
                base_code.value,
                "categorical_evidence",
                "SATISFY",
                None,
                "categorical",
                False,
                remediation_class,
                action,
                "alpha/decision_intelligence/engine.py",
                f"RejectionReasonCode.{base_code.name}",
            )
        )
    for stress_code in StressReasonCode:
        remediation_class, action = _STRESS_ACTIONS[stress_code.value]
        rows.append(
            ConstraintSpec(
                f"STRESS.{stress_code.value}.CATEGORICAL",
                "STRESS_TEST",
                stress_code.value,
                "categorical_evidence",
                "SATISFY",
                None,
                "categorical",
                False,
                remediation_class,
                action,
                "alpha/decision_intelligence/stress.py",
                f"StressReasonCode.{stress_code.name}",
            )
        )
    for stage, gate_code, remediation in (
        (
            "STRESS_DECISION",
            "STRESS_FINAL_ACTION",
            _STRESS_ACTIONS["STRESS_FINAL_ACTION"],
        ),
        ("TRADE_PLAN", "TRADE_PLAN_FINAL_ACTION", _TRADE_PLAN_ACTION),
    ):
        rows.append(
            ConstraintSpec(
                f"{stage}.{gate_code}.CATEGORICAL",
                stage,
                gate_code,
                "categorical_evidence",
                "SATISFY",
                None,
                "categorical",
                False,
                remediation[0],
                remediation[1],
                (
                    "alpha/decision_intelligence/stress.py"
                    if stage == "STRESS_DECISION"
                    else "alpha/decision_intelligence/tradeplan.py"
                ),
                gate_code,
            )
        )
    return tuple(rows)


_NUMERIC_SPECS = _numeric_specs()
_CATEGORICAL_SPECS = _categorical_specs()
_CONTRACT_SPECS = tuple(
    sorted(
        (*_NUMERIC_SPECS, *_CATEGORICAL_SPECS),
        key=lambda item: item.constraint_id,
    )
)
_NUMERIC_BY_GATE: dict[tuple[str, str], tuple[ConstraintSpec, ...]] = {
    key: tuple(item for item in _NUMERIC_SPECS if (item.stage, item.gate_code) == key)
    for key in sorted({(item.stage, item.gate_code) for item in _NUMERIC_SPECS})
}
_CATEGORICAL_BY_GATE: dict[tuple[str, str], ConstraintSpec] = {
    (item.stage, item.gate_code): item for item in _CATEGORICAL_SPECS
}


class GovernedApprovalConstraintFrontierEngine:
    """Measure the frozen approval frontier from signed B5 forensic evidence."""

    def run(
        self,
        *,
        b5_certificate: Path,
        output: Path,
        project_root: Path | str = Path("."),
        progress: ProgressCallback | None = None,
    ) -> GovernedApprovalConstraintFrontierResult:
        total_steps = 7
        root = Path(project_root)
        _progress(progress, 1, total_steps, "Validating signed HTR-010B5 handoff")
        b5 = validate_governed_approval_gate_forensics_certificate(
            b5_certificate,
            require_ready=True,
            project_root=root,
        )
        _validate_b5_handoff(b5)
        b5_file_sha256 = _file_sha256(b5_certificate)
        candidate_path = b5_certificate.parent / _B5_CANDIDATE_ARTIFACT
        gate_path = b5_certificate.parent / _B5_GATE_ARTIFACT
        candidate_sha256 = _file_sha256(candidate_path)
        gate_sha256 = _file_sha256(gate_path)

        _progress(
            progress,
            2,
            total_steps,
            "Loading bound B5 candidate and gate ledgers",
        )
        candidate_rows = _csv_rows(candidate_path)
        gate_rows = _csv_rows(gate_path)
        candidates, events, defects = _validated_b5_ledgers(
            candidate_rows,
            gate_rows,
            b5=b5,
        )

        _progress(progress, 3, total_steps, "Measuring frozen gate margins")
        threshold_rows = tuple(item.as_dict() for item in _CONTRACT_SPECS)
        frontier_rows, margin_rows, remediation_rows, build_defects = _build_frontier(
            candidates,
            events,
        )
        defects = tuple(sorted({*defects, *build_defects}))

        _progress(progress, 4, total_steps, "Attributing bottleneck prevalence")
        prevalence_rows = _bottleneck_prevalence(frontier_rows, margin_rows)

        _progress(progress, 5, total_steps, "Comparing RAW and ADJUSTED frontiers")
        comparison_rows, unexplained_divergences = _arm_comparison(
            frontier_rows,
            margin_rows,
        )

        _progress(progress, 6, total_steps, "Running deterministic boundary probes")
        probe_rows, probe_summary, probe_defects = _counterfactual_probes()
        defects = tuple(sorted({*defects, *probe_defects}))

        raw_summary = _arm_summary(frontier_rows, margin_rows, price_view="RAW")
        adjusted_summary = _arm_summary(
            frontier_rows,
            margin_rows,
            price_view="ADJUSTED",
        )
        population_nonempty = (
            cast(int, raw_summary["candidate_count"]) > 0
            and cast(int, adjusted_summary["candidate_count"]) > 0
        )
        evidence_complete = (
            population_nonempty
            and all(bool(row["constraint_evidence_complete"]) for row in frontier_rows)
            and cast(int, probe_summary["failed_probe_count"]) == 0
        )
        readiness, blockers = _readiness(
            defects=defects,
            unexplained_divergences=unexplained_divergences,
            population_nonempty=population_nonempty,
            evidence_complete=evidence_complete,
        )
        enabled = readiness == B6_READY
        policy_hashes = _mapping_copy(
            b5,
            "institutional_policy_source_sha256s",
        )
        pipeline_hashes = _mapping_copy(
            b5,
            "frozen_pipeline_component_sha256s",
        )
        if _policy_source_hashes(root) != policy_hashes:
            raise ValueError("institutional policy source changed during B6 analysis")
        if _pipeline_component_hashes(root) != pipeline_hashes:
            raise ValueError("frozen pipeline component changed during B6 analysis")
        if _file_sha256(b5_certificate) != b5_file_sha256:
            raise ValueError("HTR-010B5 certificate changed during B6 analysis")
        if _file_sha256(candidate_path) != candidate_sha256:
            raise ValueError("HTR-010B5 candidate ledger changed during B6 analysis")
        if _file_sha256(gate_path) != gate_sha256:
            raise ValueError("HTR-010B5 gate ledger changed during B6 analysis")

        report: dict[str, Any] = {
            "contract_version": HTR010B6_CONTRACT_VERSION,
            "b5_contract_version": b5["contract_version"],
            "b5_report_sha256": b5["report_sha256"],
            "b5_certificate_file_sha256": b5_file_sha256,
            "b5_candidate_ledger_sha256": candidate_sha256,
            "b5_gate_ledger_sha256": gate_sha256,
            "replay_start": b5["replay_start"],
            "replay_end": b5["replay_end"],
            "session_count": b5["session_count"],
            "institutional_policy_source_sha256s": policy_hashes,
            "frozen_pipeline_component_sha256s": pipeline_hashes,
            "threshold_contract_sha256": _digest_sequence(threshold_rows),
            "threshold_contract_row_count": len(threshold_rows),
            "frontier_contract": {
                "policy_change_permitted": False,
                "threshold_change_permitted": False,
                "counterfactual_mutation_enabled": False,
                "counterfactual_approval_claimed": False,
                "minimal_remediation_requires_all_failed_constraints": True,
                "categorical_constraints_may_not_be_imputed_as_numeric": True,
                "source_price_arms_must_remain_distinct": True,
            },
            "raw_frontier_summary": raw_summary,
            "adjusted_frontier_summary": adjusted_summary,
            "bottleneck_summary": _bottleneck_summary(prevalence_rows),
            "probe_summary": probe_summary,
            "constraint_population_nonempty": population_nonempty,
            "constraint_evidence_complete": evidence_complete,
            "unexplained_constraint_divergence_count": unexplained_divergences,
            "implementation_defects": list(defects),
            "implementation_defect_count": len(defects),
            "readiness_blockers": list(blockers),
            "readiness_decision": readiness,
            "governed_approval_constraint_research_enabled": enabled,
            "governed_approval_gate_research_enabled": True,
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

        _progress(progress, 7, total_steps, "Exporting signed HTR-010B6 artifacts")
        paths = export_governed_approval_constraint_frontier(
            report=report,
            frontier_rows=frontier_rows,
            margin_rows=margin_rows,
            prevalence_rows=prevalence_rows,
            remediation_rows=remediation_rows,
            comparison_rows=comparison_rows,
            threshold_rows=threshold_rows,
            probe_rows=probe_rows,
            output=output,
        )
        return GovernedApprovalConstraintFrontierResult(
            report=report,
            frontier_rows=frontier_rows,
            margin_rows=margin_rows,
            prevalence_rows=prevalence_rows,
            remediation_rows=remediation_rows,
            comparison_rows=comparison_rows,
            threshold_rows=threshold_rows,
            probe_rows=probe_rows,
            paths=paths,
        )


def export_governed_approval_constraint_frontier(
    *,
    report: dict[str, Any],
    frontier_rows: tuple[dict[str, object], ...],
    margin_rows: tuple[dict[str, object], ...],
    prevalence_rows: tuple[dict[str, object], ...],
    remediation_rows: tuple[dict[str, object], ...],
    comparison_rows: tuple[dict[str, object], ...],
    threshold_rows: tuple[dict[str, object], ...],
    probe_rows: tuple[dict[str, object], ...],
    output: Path,
) -> tuple[Path, ...]:
    """Export deterministic B6 evidence and bind every supporting file."""

    output.mkdir(parents=True, exist_ok=True)
    certificate_path = output / "htr010b6_approval_constraint_certificate.json"
    certificate_path.unlink(missing_ok=True)
    support_paths = (
        _write_csv(
            output / "htr010b6_candidate_constraint_frontier.csv",
            frontier_rows,
            fieldnames=_FRONTIER_FIELDS,
        ),
        _write_csv(
            output / "htr010b6_constraint_margin_ledger.csv",
            margin_rows,
            fieldnames=_MARGIN_FIELDS,
        ),
        _write_csv(
            output / "htr010b6_gate_bottleneck_prevalence.csv",
            prevalence_rows,
            fieldnames=_PREVALENCE_FIELDS,
        ),
        _write_csv(
            output / "htr010b6_minimal_remediation_sets.csv",
            remediation_rows,
            fieldnames=_REMEDIATION_FIELDS,
        ),
        _write_csv(
            output / "htr010b6_raw_adjusted_constraint_comparison.csv",
            comparison_rows,
            fieldnames=_COMPARISON_FIELDS,
        ),
        _write_csv(
            output / "htr010b6_threshold_contract_snapshot.csv",
            threshold_rows,
            fieldnames=_THRESHOLD_FIELDS,
        ),
        _write_csv(
            output / "htr010b6_counterfactual_probe_ledger.csv",
            probe_rows,
            fieldnames=_PROBE_FIELDS,
        ),
        _write_text(
            output / "htr010b6_executive_report.md",
            _markdown(report),
        ),
    )
    report["artifact_hashes"] = {
        path.name: _file_sha256(path) for path in support_paths
    }
    report["report_sha256"] = _digest_mapping(report)
    certificate = _write_json(certificate_path, report)
    return (certificate, *support_paths)


def validate_governed_approval_constraint_frontier_certificate(
    path: Path,
    *,
    require_ready: bool = False,
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    """Validate the signed B6 contract and every bound supporting artifact."""

    payload = _mapping(path)
    if payload.get("contract_version") != HTR010B6_CONTRACT_VERSION:
        raise ValueError("unsupported HTR-010B6 approval-constraint contract")
    _validate_digest(payload, "HTR-010B6 approval-constraint certificate")
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
        if _policy_source_hashes(root) != expected_policy:
            raise ValueError("HTR-010B6 frozen policy source digest mismatch")
        if _pipeline_component_hashes(root) != expected_pipeline:
            raise ValueError("HTR-010B6 frozen pipeline component digest mismatch")
    hashes = payload.get("artifact_hashes")
    if not isinstance(hashes, dict):
        raise ValueError("HTR-010B6 certificate lacks supporting artifact hashes")
    names = frozenset(str(name) for name in hashes)
    if names != _REQUIRED_B6_SUPPORT_ARTIFACTS:
        raise ValueError("HTR-010B6 supporting artifact set mismatch")
    for name, expected in sorted(hashes.items()):
        expected_sha256 = str(expected)
        if not _is_sha256(expected_sha256):
            raise ValueError(f"HTR-010B6 supporting artifact digest is invalid: {name}")
        if _file_sha256(_artifact_path(path.parent, name)) != expected_sha256:
            raise ValueError(f"HTR-010B6 supporting artifact digest mismatch: {name}")
    readiness = str(payload.get("readiness_decision") or "")
    valid = {
        B6_READY,
        B6_BLOCKED_EMPTY,
        B6_BLOCKED_EVIDENCE,
        B6_BLOCKED_DEFECT,
        B6_BLOCKED_DIVERGENCE,
    }
    if readiness not in valid:
        raise ValueError("HTR-010B6 readiness decision is invalid")
    expected_enabled = readiness == B6_READY
    if (
        payload.get("governed_approval_constraint_research_enabled")
        is not expected_enabled
    ):
        raise ValueError("HTR-010B6 readiness and research enablement disagree")
    _validate_certificate_state_semantics(payload)
    if require_ready and not expected_enabled:
        raise ValueError("HTR-010B6 does not permit approval-constraint research")
    return payload


def _validate_b5_handoff(payload: Mapping[str, object]) -> None:
    if payload.get("contract_version") != HTR010B5_CONTRACT_VERSION:
        raise ValueError("B6 requires the HTR-010B5 approval-gate contract")
    if payload.get("readiness_decision") != B5_READY:
        raise ValueError("B6 requires B5 approval-gate research readiness")
    if payload.get("governed_approval_gate_research_enabled") is not True:
        raise ValueError("HTR-010B5 approval-gate research is disabled")
    for key in (
        "empirical_gate_reached",
        "approval_gate_trace_complete",
        "approval_gate_non_vacuous",
        "zero_approval_policy_consistent",
    ):
        if payload.get(key) is not True:
            raise ValueError(f"HTR-010B5 handoff lacks required proof: {key}")
    if _integer(payload.get("implementation_defect_count"), "B5 defects") != 0:
        raise ValueError("HTR-010B5 contains implementation defects")
    if (
        _integer(
            payload.get("unexplained_arm_divergence_count"),
            "B5 arm divergences",
        )
        != 0
    ):
        raise ValueError("HTR-010B5 contains unexplained arm divergences")
    if payload.get("governed_adjusted_trade_research_enabled") is not False:
        raise ValueError("HTR-010B5 unexpectedly enabled trade research")
    if payload.get("production_influence") is not False:
        raise ValueError("HTR-010B5 unexpectedly permits production influence")


def _validated_b5_ledgers(
    candidate_rows: tuple[dict[str, str], ...],
    gate_rows: tuple[dict[str, str], ...],
    *,
    b5: Mapping[str, object],
) -> tuple[
    dict[CandidateKey, dict[str, str]],
    dict[CandidateKey, tuple[dict[str, str], ...]],
    tuple[str, ...],
]:
    defects: list[str] = []
    candidates: dict[CandidateKey, dict[str, str]] = {}
    counts: Counter[str] = Counter()
    approvable_counts: Counter[str] = Counter()
    for row in candidate_rows:
        price_view = _price_view(row.get("price_view"))
        key = (
            price_view,
            _date_value(row.get("observed_on"), "B5 candidate date"),
            _symbol(row.get("symbol"), "B5 candidate symbol"),
        )
        if key in candidates:
            defects.append(
                f"DUPLICATE_B5_CANDIDATE@{key[0]}|{key[1].isoformat()}|{key[2]}"
            )
        candidates[key] = row
        counts[price_view] += 1
        if _boolean(row.get("approvable_signal"), "B5 approvable signal"):
            approvable_counts[price_view] += 1
        if _boolean(row.get("institutional_approved"), "B5 approval"):
            defects.append(
                f"B5_APPROVED_CANDIDATE@{key[0]}|{key[1].isoformat()}|{key[2]}"
            )
        if not _boolean(row.get("benchmark_parity"), "B5 benchmark parity"):
            defects.append(
                f"B5_CANDIDATE_PARITY_MISMATCH@{key[0]}|{key[1].isoformat()}|{key[2]}"
            )
    events_by_key: dict[CandidateKey, list[dict[str, str]]] = defaultdict(list)
    event_keys: set[tuple[CandidateKey, str, str]] = set()
    for row in gate_rows:
        key = (
            _price_view(row.get("price_view")),
            _date_value(row.get("observed_on"), "B5 gate date"),
            _symbol(row.get("symbol"), "B5 gate symbol"),
        )
        event_key = (key, str(row.get("stage") or ""), str(row.get("gate_code") or ""))
        if event_key in event_keys:
            defects.append(
                f"DUPLICATE_B5_GATE_EVENT@{key[0]}|{key[1].isoformat()}|"
                f"{key[2]}|{event_key[1]}|{event_key[2]}"
            )
        event_keys.add(event_key)
        events_by_key[key].append(row)
    for key in sorted(set(events_by_key).difference(candidates)):
        defects.append(
            f"B5_GATE_WITHOUT_CANDIDATE@{key[0]}|{key[1].isoformat()}|{key[2]}"
        )
    for price_view, summary_key in (
        ("RAW", "raw_forensic_summary"),
        ("ADJUSTED", "adjusted_forensic_summary"),
    ):
        summary = _nested_mapping(b5, summary_key)
        if counts[price_view] != _integer(
            summary.get("candidate_count"),
            f"B5 {price_view} candidates",
        ):
            defects.append(f"B5_{price_view}_CANDIDATE_COUNT_MISMATCH")
        if approvable_counts[price_view] != _integer(
            summary.get("approvable_candidate_count"),
            f"B5 {price_view} approvable candidates",
        ):
            defects.append(f"B5_{price_view}_APPROVABLE_COUNT_MISMATCH")
    normalized_events = {
        key: tuple(
            sorted(
                rows,
                key=lambda row: (
                    str(row.get("stage") or ""),
                    _integer(row.get("gate_ordinal"), "gate ordinal"),
                    str(row.get("gate_code") or ""),
                ),
            )
        )
        for key, rows in events_by_key.items()
    }
    return candidates, normalized_events, tuple(sorted(set(defects)))


def _build_frontier(
    candidates: Mapping[CandidateKey, dict[str, str]],
    events: Mapping[CandidateKey, tuple[dict[str, str], ...]],
) -> tuple[
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[str, ...],
]:
    frontier: list[dict[str, object]] = []
    margins: list[dict[str, object]] = []
    remediations: list[dict[str, object]] = []
    defects: list[str] = []
    for key, candidate in sorted(candidates.items()):
        if not _boolean(candidate.get("approvable_signal"), "approvable signal"):
            continue
        failed_events = _failed_constraint_events(events.get(key, ()))
        candidate_margins: list[dict[str, object]] = []
        for event in failed_events:
            rows, event_defects = _constraints_for_failure(candidate, event, key=key)
            candidate_margins.extend(rows)
            defects.extend(event_defects)
        candidate_margins = _deduplicate_constraints(candidate_margins)
        if not candidate_margins:
            defects.append(
                f"APPROVABLE_CANDIDATE_WITHOUT_CONSTRAINT@"
                f"{key[0]}|{key[1].isoformat()}|{key[2]}"
            )
        margins.extend(candidate_margins)
        constraint_ids = tuple(
            sorted(str(row["constraint_id"]) for row in candidate_margins)
        )
        gate_codes = tuple(sorted({str(row["gate_code"]) for row in candidate_margins}))
        remediation_classes = tuple(
            sorted({str(row["remediation_class"]) for row in candidate_margins})
        )
        measurable = sum(bool(row["measurable"]) for row in candidate_margins)
        categorical = len(candidate_margins) - measurable
        normalized_gaps = tuple(
            _optional_decimal(row.get("normalized_gap")) or Decimal("0")
            for row in candidate_margins
            if bool(row["measurable"])
        )
        total_gap = sum(normalized_gaps, Decimal("0")).quantize(
            Decimal("0.000001"),
            rounding=ROUND_HALF_UP,
        )
        maximum_gap = max(normalized_gaps, default=Decimal("0")).quantize(
            Decimal("0.000001"),
            rounding=ROUND_HALF_UP,
        )
        nearest = tuple(
            str(row["constraint_id"])
            for row in sorted(
                candidate_margins,
                key=lambda row: (
                    0 if bool(row["measurable"]) else 1,
                    _optional_decimal(row.get("normalized_gap"))
                    if bool(row["measurable"])
                    else Decimal("999999"),
                    str(row["constraint_id"]),
                ),
            )[:3]
        )
        evidence_complete = bool(candidate_margins) and all(
            str(row["remediation_class"]) != "UNCLASSIFIED" for row in candidate_margins
        )
        frontier.append(
            {
                "price_view": key[0],
                "observed_on": key[1],
                "symbol": key[2],
                "final_signal": str(candidate.get("final_signal") or ""),
                "terminal_stage": str(candidate.get("terminal_stage") or ""),
                "terminal_gate": str(candidate.get("terminal_gate") or ""),
                "distinct_gate_count": len(gate_codes),
                "failed_constraint_count": len(candidate_margins),
                "measurable_constraint_count": measurable,
                "categorical_constraint_count": categorical,
                "minimum_remediation_count": len(constraint_ids),
                "remediation_classes": remediation_classes,
                "nearest_constraint_ids": nearest,
                "total_normalized_gap": total_gap,
                "maximum_normalized_gap": maximum_gap,
                "frontier_rank": 0,
                "constraint_evidence_complete": evidence_complete,
                "input_fingerprint": str(candidate.get("input_fingerprint") or ""),
            }
        )
        remediations.append(
            {
                "price_view": key[0],
                "observed_on": key[1],
                "symbol": key[2],
                "remediation_set_id": _digest_sequence(list(constraint_ids)),
                "minimum_remediation_count": len(constraint_ids),
                "gate_codes": gate_codes,
                "constraint_ids": constraint_ids,
                "remediation_classes": remediation_classes,
                "measurable_constraint_count": measurable,
                "categorical_constraint_count": categorical,
                "total_normalized_gap": total_gap,
                "policy_threshold_change_required": False,
                "counterfactual_approval_claimed": False,
                "input_fingerprint": str(candidate.get("input_fingerprint") or ""),
            }
        )
    _assign_frontier_ranks(frontier)
    return (
        tuple(frontier),
        tuple(sorted(margins, key=_constraint_sort_key)),
        tuple(sorted(remediations, key=_candidate_sort_key)),
        tuple(sorted(set(defects))),
    )


def _failed_constraint_events(
    events: Sequence[dict[str, str]],
) -> tuple[dict[str, str], ...]:
    failed = [
        row
        for row in events
        if _boolean(row.get("stage_reached"), "gate stage reached")
        and str(row.get("outcome") or "").upper() == "FAIL"
        and str(row.get("stage") or "")
        in {"BASE_GATE", "STRESS_TEST", "STRESS_DECISION", "TRADE_PLAN"}
    ]
    stress_failures = any(
        str(row.get("stage") or "") == "STRESS_TEST" for row in failed
    )
    return tuple(
        row
        for row in failed
        if not (
            stress_failures
            and str(row.get("stage") or "") == "STRESS_DECISION"
            and str(row.get("gate_code") or "") == "STRESS_FINAL_ACTION"
        )
    )


def _constraints_for_failure(
    candidate: Mapping[str, str],
    event: Mapping[str, str],
    *,
    key: CandidateKey,
) -> tuple[tuple[dict[str, object], ...], tuple[str, ...]]:
    stage = str(event.get("stage") or "")
    gate_code = str(event.get("gate_code") or "")
    explanation = str(event.get("explanation") or "")
    specs = _NUMERIC_BY_GATE.get((stage, gate_code), ())
    rows: list[dict[str, object]] = []
    for spec in specs:
        observed = _metric_value(candidate, spec.metric)
        if observed is None:
            continue
        margin, gap, normalized = _margin(spec, observed)
        if gap > Decimal("0"):
            rows.append(
                _constraint_row(
                    candidate,
                    event,
                    key=key,
                    spec=spec,
                    observed=observed,
                    margin=margin,
                    gap=gap,
                    normalized=normalized,
                )
            )
    needs_categorical = not rows or _has_categorical_residual(
        stage,
        gate_code,
        explanation,
        candidate,
    )
    defects: list[str] = []
    if needs_categorical:
        categorical = _CATEGORICAL_BY_GATE.get((stage, gate_code))
        if categorical is None:
            defects.append(
                f"UNCLASSIFIED_CONSTRAINT@{key[0]}|{key[1].isoformat()}|"
                f"{key[2]}|{stage}|{gate_code}"
            )
            categorical = ConstraintSpec(
                f"{stage}.{gate_code}.UNCLASSIFIED",
                stage,
                gate_code,
                "categorical_evidence",
                "SATISFY",
                None,
                "categorical",
                False,
                "UNCLASSIFIED",
                "Investigate the unclassified frozen gate evidence.",
                "UNKNOWN",
                gate_code,
            )
        rows.append(
            _constraint_row(
                candidate,
                event,
                key=key,
                spec=categorical,
                observed=None,
                margin=None,
                gap=None,
                normalized=None,
            )
        )
    return tuple(rows), tuple(defects)


def _has_categorical_residual(
    stage: str,
    gate_code: str,
    explanation: str,
    candidate: Mapping[str, str],
) -> bool:
    text = explanation.lower()
    if stage == "BASE_GATE" and gate_code == "WEAK_SETUP":
        return "setup quality" in text or "scorecard" in text
    if stage == "BASE_GATE" and gate_code == "INSUFFICIENT_EVIDENCE":
        return "adaptive evidence" in text
    if stage == "BASE_GATE" and gate_code == "INSUFFICIENT_CAPACITY":
        score = _optional_decimal(candidate.get("capacity_score"))
        return score is None or score >= Decimal("35")
    return False


def _constraint_row(
    candidate: Mapping[str, str],
    event: Mapping[str, str],
    *,
    key: CandidateKey,
    spec: ConstraintSpec,
    observed: Decimal | None,
    margin: Decimal | None,
    gap: Decimal | None,
    normalized: Decimal | None,
) -> dict[str, object]:
    return {
        "price_view": key[0],
        "observed_on": key[1],
        "symbol": key[2],
        "final_signal": str(candidate.get("final_signal") or ""),
        "terminal_stage": str(candidate.get("terminal_stage") or ""),
        "terminal_gate": str(candidate.get("terminal_gate") or ""),
        "stage": spec.stage,
        "gate_code": spec.gate_code,
        "constraint_id": spec.constraint_id,
        "metric": spec.metric,
        "comparator": spec.comparator,
        "threshold": spec.threshold,
        "observed_value": observed,
        "margin_to_threshold": margin,
        "gap_to_clear": gap,
        "normalized_gap": normalized,
        "measurable": spec.measurable,
        "remediation_class": spec.remediation_class,
        "remediation_action": spec.remediation_action,
        "primary": _boolean(event.get("primary"), "primary gate"),
        "input_fingerprint": str(candidate.get("input_fingerprint") or ""),
    }


def _metric_value(candidate: Mapping[str, str], metric: str) -> Decimal | None:
    if metric == "adjusted_confidence_rank":
        value = str(candidate.get("adjusted_confidence") or "").strip().upper()
        return Decimal({"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get(value, 0))
    if metric == "evidence_sample_count":
        text = str(candidate.get(metric) or "").strip()
        return Decimal(text) if text else None
    return _optional_decimal(candidate.get(metric))


def _margin(
    spec: ConstraintSpec,
    observed: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    threshold = spec.threshold
    if threshold is None:
        raise ValueError("numeric constraint lacks threshold")
    if spec.comparator == "GE":
        margin = observed - threshold
    elif spec.comparator == "LE":
        margin = threshold - observed
    else:
        raise ValueError(f"unsupported numeric comparator: {spec.comparator}")
    gap = max(Decimal("0"), -margin)
    denominator = abs(threshold) if threshold != Decimal("0") else Decimal("1")
    normalized = (gap / denominator).quantize(
        Decimal("0.000001"),
        rounding=ROUND_HALF_UP,
    )
    return (
        margin.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
        gap.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
        normalized,
    )


def _deduplicate_constraints(
    rows: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    selected: dict[str, dict[str, object]] = {}
    for row in rows:
        selected[str(row["constraint_id"])] = row
    return [selected[key] for key in sorted(selected)]


def _assign_frontier_ranks(rows: list[dict[str, object]]) -> None:
    by_view: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_view[str(row["price_view"])].append(row)
    for price_view in sorted(by_view):
        ordered = sorted(
            by_view[price_view],
            key=lambda row: (
                _integer(row.get("minimum_remediation_count"), "remediation count"),
                _integer(row.get("categorical_constraint_count"), "categorical count"),
                _decimal(row.get("total_normalized_gap"), "normalized gap"),
                str(row["observed_on"]),
                str(row["symbol"]),
            ),
        )
        for rank, row in enumerate(ordered, start=1):
            row["frontier_rank"] = rank


def _bottleneck_prevalence(
    frontier_rows: Sequence[dict[str, object]],
    margin_rows: Sequence[dict[str, object]],
) -> tuple[dict[str, object], ...]:
    population = Counter(str(row["price_view"]) for row in frontier_rows)
    groups: dict[tuple[str, str, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in margin_rows:
        key = (
            str(row["price_view"]),
            str(row["stage"]),
            str(row["gate_code"]),
            str(row["remediation_class"]),
        )
        groups[key].append(row)
    result: list[dict[str, object]] = []
    for key, rows in sorted(groups.items()):
        candidate_keys = {(str(row["observed_on"]), str(row["symbol"])) for row in rows}
        primary_keys = {
            (str(row["observed_on"]), str(row["symbol"]))
            for row in rows
            if bool(row["primary"])
        }
        gaps = tuple(
            cast(Decimal, row["gap_to_clear"])
            for row in rows
            if bool(row["measurable"]) and row["gap_to_clear"] is not None
        )
        denominator = population[key[0]]
        percent = (
            Decimal("0")
            if denominator == 0
            else (Decimal(len(candidate_keys)) / Decimal(denominator) * Decimal("100"))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        result.append(
            {
                "price_view": key[0],
                "stage": key[1],
                "gate_code": key[2],
                "remediation_class": key[3],
                "failed_candidate_count": len(candidate_keys),
                "primary_candidate_count": len(primary_keys),
                "measurable_constraint_count": sum(
                    bool(row["measurable"]) for row in rows
                ),
                "categorical_constraint_count": sum(
                    not bool(row["measurable"]) for row in rows
                ),
                "candidate_percent": percent,
                "average_gap_to_clear": _average(gaps),
                "median_gap_to_clear": _median(gaps),
                "maximum_gap_to_clear": max(gaps, default=None),
            }
        )
    return tuple(result)


def _arm_comparison(
    frontier_rows: Sequence[dict[str, object]],
    margin_rows: Sequence[dict[str, object]],
) -> tuple[tuple[dict[str, object], ...], int]:
    frontier_by_key = {
        (str(row["price_view"]), str(row["observed_on"]), str(row["symbol"])): row
        for row in frontier_rows
    }
    constraints: dict[tuple[str, str, str], tuple[str, ...]] = defaultdict(tuple)
    mutable: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for row in margin_rows:
        key = (str(row["price_view"]), str(row["observed_on"]), str(row["symbol"]))
        mutable[key].append(str(row["constraint_id"]))
    constraints = {key: tuple(sorted(values)) for key, values in mutable.items()}
    candidate_keys = sorted(
        {(date_text, symbol) for _, date_text, symbol in frontier_by_key}
    )
    result: list[dict[str, object]] = []
    unexplained = 0
    for date_text, symbol in candidate_keys:
        raw = frontier_by_key.get(("RAW", date_text, symbol))
        adjusted = frontier_by_key.get(("ADJUSTED", date_text, symbol))
        raw_constraints = constraints.get(("RAW", date_text, symbol), ())
        adjusted_constraints = constraints.get(("ADJUSTED", date_text, symbol), ())
        raw_classes = _tuple_value(raw.get("remediation_classes")) if raw else ()
        adjusted_classes = (
            _tuple_value(adjusted.get("remediation_classes")) if adjusted else ()
        )
        raw_count = (
            _integer(raw.get("minimum_remediation_count"), "RAW remediation count")
            if raw
            else 0
        )
        adjusted_count = (
            _integer(
                adjusted.get("minimum_remediation_count"),
                "ADJUSTED remediation count",
            )
            if adjusted
            else 0
        )
        raw_gap = (
            _decimal(raw.get("total_normalized_gap"), "RAW normalized gap")
            if raw
            else Decimal("0")
        )
        adjusted_gap = (
            _decimal(
                adjusted.get("total_normalized_gap"),
                "ADJUSTED normalized gap",
            )
            if adjusted
            else Decimal("0")
        )
        raw_fingerprint = str(raw.get("input_fingerprint") or "") if raw else ""
        adjusted_fingerprint = (
            str(adjusted.get("input_fingerprint") or "") if adjusted else ""
        )
        input_changed = bool(
            raw and adjusted and raw_fingerprint != adjusted_fingerprint
        )
        constraint_changed = (
            raw_constraints != adjusted_constraints
            or raw_count != adjusted_count
            or raw_gap != adjusted_gap
        )
        one_sided = raw is None or adjusted is None
        explained = constraint_changed and input_changed and not one_sided
        unexplained_row = one_sided or (constraint_changed and not explained)
        unexplained += int(unexplained_row)
        result.append(
            {
                "observed_on": date_text,
                "symbol": symbol,
                "raw_present": raw is not None,
                "adjusted_present": adjusted is not None,
                "raw_input_fingerprint": raw_fingerprint,
                "adjusted_input_fingerprint": adjusted_fingerprint,
                "input_changed": input_changed,
                "raw_constraint_ids": raw_constraints,
                "adjusted_constraint_ids": adjusted_constraints,
                "constraint_set_changed": constraint_changed,
                "raw_remediation_classes": raw_classes,
                "adjusted_remediation_classes": adjusted_classes,
                "raw_minimum_remediation_count": raw_count,
                "adjusted_minimum_remediation_count": adjusted_count,
                "remediation_count_delta": adjusted_count - raw_count,
                "raw_total_normalized_gap": raw_gap,
                "adjusted_total_normalized_gap": adjusted_gap,
                "normalized_gap_delta": adjusted_gap - raw_gap,
                "explained_constraint_difference": explained,
                "unexplained_constraint_divergence": unexplained_row,
            }
        )
    return tuple(result), unexplained


def _counterfactual_probes() -> tuple[
    tuple[dict[str, object], ...],
    dict[str, object],
    tuple[str, ...],
]:
    first = _probe_pass()
    second = _probe_pass()
    deterministic = first == second
    rows: list[dict[str, object]] = []
    defects: list[str] = []
    for left, right in zip(first, second, strict=True):
        row = dict(left)
        row["deterministic"] = left == right
        if not bool(row["expectation_matched"]):
            defects.append(f"BOUNDARY_PROBE_FAILED@{row['constraint_id']}")
        if left != right:
            defects.append(f"BOUNDARY_PROBE_NONDETERMINISTIC@{row['constraint_id']}")
        rows.append(row)
    summary: dict[str, object] = {
        "probe_count": len(rows),
        "passed_probe_count": sum(bool(row["expectation_matched"]) for row in rows),
        "failed_probe_count": sum(not bool(row["expectation_matched"]) for row in rows),
        "deterministic": deterministic,
    }
    return tuple(rows), summary, tuple(sorted(set(defects)))


def _probe_pass() -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for spec in _NUMERIC_SPECS:
        threshold = cast(Decimal, spec.threshold)
        increment = _probe_increment(spec.unit)
        below = threshold - increment
        above = threshold + increment
        _, below_gap, _ = _margin(spec, below)
        _, at_gap, _ = _margin(spec, threshold)
        _, above_gap, _ = _margin(spec, above)
        expected = (
            below_gap > Decimal("0")
            and at_gap == Decimal("0")
            and above_gap == Decimal("0")
            if spec.comparator == "GE"
            else below_gap == Decimal("0")
            and at_gap == Decimal("0")
            and above_gap > Decimal("0")
        )
        rows.append(
            {
                "probe_id": f"BOUNDARY::{spec.constraint_id}",
                "constraint_id": spec.constraint_id,
                "comparator": spec.comparator,
                "threshold": threshold,
                "below_observed": below,
                "below_gap_to_clear": below_gap,
                "at_observed": threshold,
                "at_gap_to_clear": at_gap,
                "above_observed": above,
                "above_gap_to_clear": above_gap,
                "expectation_matched": expected,
            }
        )
    return tuple(rows)


def _probe_increment(unit: str) -> Decimal:
    if unit in {"probability", "expectancy"}:
        return Decimal("0.01")
    if unit == "R":
        return Decimal("0.1")
    return Decimal("1")


def _arm_summary(
    frontier_rows: Sequence[dict[str, object]],
    margin_rows: Sequence[dict[str, object]],
    *,
    price_view: str,
) -> dict[str, object]:
    candidates = tuple(row for row in frontier_rows if row["price_view"] == price_view)
    margins = tuple(row for row in margin_rows if row["price_view"] == price_view)
    counts = tuple(
        _integer(row.get("minimum_remediation_count"), "remediation count")
        for row in candidates
    )
    dominant = Counter(str(row["gate_code"]) for row in margins)
    nearest = min(
        candidates,
        key=lambda row: (
            _integer(row.get("frontier_rank"), "frontier rank"),
            str(row["observed_on"]),
            str(row["symbol"]),
        ),
        default=None,
    )
    return {
        "candidate_count": len(candidates),
        "constraint_count": len(margins),
        "measurable_constraint_count": sum(bool(row["measurable"]) for row in margins),
        "categorical_constraint_count": sum(
            not bool(row["measurable"]) for row in margins
        ),
        "minimum_remediation_count": min(counts, default=0),
        "maximum_remediation_count": max(counts, default=0),
        "average_remediation_count": _average_int(counts),
        "dominant_gate_code": dominant.most_common(1)[0][0] if dominant else "NONE",
        "nearest_frontier_symbol": str(nearest["symbol"]) if nearest else "NONE",
        "nearest_frontier_date": str(nearest["observed_on"]) if nearest else "",
        "constraint_evidence_complete": bool(candidates)
        and all(bool(row["constraint_evidence_complete"]) for row in candidates),
    }


def _bottleneck_summary(
    rows: Sequence[dict[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for price_view in ("RAW", "ADJUSTED"):
        selected = [row for row in rows if row["price_view"] == price_view]
        selected.sort(
            key=lambda row: (
                -_integer(row.get("failed_candidate_count"), "failed candidates"),
                str(row["stage"]),
                str(row["gate_code"]),
            )
        )
        result[price_view.lower()] = [
            {
                "stage": row["stage"],
                "gate_code": row["gate_code"],
                "remediation_class": row["remediation_class"],
                "failed_candidate_count": row["failed_candidate_count"],
                "candidate_percent": row["candidate_percent"],
            }
            for row in selected[:5]
        ]
    return result


def _readiness(
    *,
    defects: Sequence[str],
    unexplained_divergences: int,
    population_nonempty: bool,
    evidence_complete: bool,
) -> tuple[str, tuple[str, ...]]:
    if defects:
        return B6_BLOCKED_DEFECT, ("CONSTRAINT_FRONTIER_IMPLEMENTATION_DEFECT",)
    if unexplained_divergences:
        return B6_BLOCKED_DIVERGENCE, ("UNEXPLAINED_CONSTRAINT_FRONTIER_DIVERGENCE",)
    if not population_nonempty:
        return B6_BLOCKED_EMPTY, ("EMPTY_APPROVAL_CONSTRAINT_POPULATION",)
    if not evidence_complete:
        return B6_BLOCKED_EVIDENCE, ("INCOMPLETE_APPROVAL_CONSTRAINT_EVIDENCE",)
    return B6_READY, ()


def _validate_certificate_lineage(payload: Mapping[str, object]) -> None:
    if payload.get("b5_contract_version") != HTR010B5_CONTRACT_VERSION:
        raise ValueError("HTR-010B6 B5 contract lineage is invalid")
    for key in (
        "b5_report_sha256",
        "b5_certificate_file_sha256",
        "b5_candidate_ledger_sha256",
        "b5_gate_ledger_sha256",
        "threshold_contract_sha256",
    ):
        if not _is_sha256(str(payload.get(key) or "")):
            raise ValueError(f"HTR-010B6 certificate has invalid lineage digest: {key}")
    if _integer(
        payload.get("threshold_contract_row_count"),
        "B6 threshold rows",
    ) != len(_CONTRACT_SPECS):
        raise ValueError("HTR-010B6 threshold contract row count is invalid")
    if payload.get("research_scope") != RESEARCH_SCOPE:
        raise ValueError("HTR-010B6 research scope is invalid")


def _validate_certificate_state_semantics(payload: Mapping[str, object]) -> None:
    defects = _list_value(
        payload,
        "implementation_defects",
        "B6 implementation defects",
    )
    if defects != tuple(sorted(set(defects))):
        raise ValueError("HTR-010B6 implementation defects are not deterministic")
    if _integer(
        payload.get("implementation_defect_count"),
        "B6 implementation defect count",
    ) != len(defects):
        raise ValueError("HTR-010B6 implementation defect count is inconsistent")
    raw = _nested_mapping(payload, "raw_frontier_summary")
    adjusted = _nested_mapping(payload, "adjusted_frontier_summary")
    population_nonempty = (
        _integer(raw.get("candidate_count"), "B6 RAW candidates") > 0
        and _integer(adjusted.get("candidate_count"), "B6 ADJUSTED candidates") > 0
    )
    probes = _nested_mapping(payload, "probe_summary")
    evidence_complete = (
        population_nonempty
        and raw.get("constraint_evidence_complete") is True
        and adjusted.get("constraint_evidence_complete") is True
        and _integer(probes.get("failed_probe_count"), "B6 failed probes") == 0
        and probes.get("deterministic") is True
    )
    if payload.get("constraint_population_nonempty") is not population_nonempty:
        raise ValueError("HTR-010B6 constraint population state is inconsistent")
    if payload.get("constraint_evidence_complete") is not evidence_complete:
        raise ValueError("HTR-010B6 constraint evidence state is inconsistent")
    unexplained = _integer(
        payload.get("unexplained_constraint_divergence_count"),
        "B6 unexplained divergences",
    )
    readiness, blockers = _readiness(
        defects=defects,
        unexplained_divergences=unexplained,
        population_nonempty=population_nonempty,
        evidence_complete=evidence_complete,
    )
    if payload.get("readiness_decision") != readiness:
        raise ValueError("HTR-010B6 readiness decision disagrees with evidence")
    if _list_value(payload, "readiness_blockers", "B6 blockers") != blockers:
        raise ValueError("HTR-010B6 readiness blockers disagree with evidence")
    if readiness == B6_READY:
        contract = _nested_mapping(payload, "frontier_contract")
        expected = {
            "policy_change_permitted": False,
            "threshold_change_permitted": False,
            "counterfactual_mutation_enabled": False,
            "counterfactual_approval_claimed": False,
            "minimal_remediation_requires_all_failed_constraints": True,
            "categorical_constraints_may_not_be_imputed_as_numeric": True,
            "source_price_arms_must_remain_distinct": True,
        }
        for key, value in expected.items():
            if contract.get(key) != value:
                raise ValueError(f"HTR-010B6 frontier contract is invalid: {key}")


def _validate_research_only_flags(payload: Mapping[str, object]) -> None:
    required_false = (
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
            raise ValueError(f"HTR-010B6 research-only guardrail failed: {key}")
    if payload.get("governed_approval_gate_research_enabled") is not True:
        raise ValueError("HTR-010B6 requires B5 approval-gate research enablement")


def _threshold_rows() -> tuple[dict[str, object], ...]:
    return tuple(item.as_dict() for item in _CONTRACT_SPECS)


def _policy_source_hashes(project_root: Path) -> dict[str, str]:
    return dict(_b5_policy_source_hashes(project_root))


def _pipeline_component_hashes(project_root: Path) -> dict[str, str]:
    return dict(_b5_pipeline_component_hashes(project_root))


def _mapping_copy(payload: Mapping[str, object], key: str) -> dict[str, str]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"mapping field is required: {key}")
    result = {str(name): str(digest) for name, digest in value.items()}
    if any(not _is_sha256(digest) for digest in result.values()):
        raise ValueError(f"mapping contains invalid SHA-256 values: {key}")
    return dict(sorted(result.items()))


def _nested_mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"mapping field is required: {key}")
    return cast(Mapping[str, object], value)


def _mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must contain a mapping: {path}")
    return cast(dict[str, Any], payload)


def _csv_rows(path: Path) -> tuple[dict[str, str], ...]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8", newline="") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    *,
    fieldnames: tuple[str, ...],
) -> Path:
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: _csv_value(row.get(name)) for name in fieldnames})
    os.replace(temporary, path)
    return path


def _write_json(path: Path, payload: Mapping[str, object]) -> Path:
    content = json.dumps(_json_ready(payload), indent=2, sort_keys=True) + "\n"
    return _write_text(path, content)


def _write_text(path: Path, content: str) -> Path:
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    os.replace(temporary, path)
    return path


def _markdown(report: Mapping[str, object]) -> str:
    raw = _nested_mapping(report, "raw_frontier_summary")
    adjusted = _nested_mapping(report, "adjusted_frontier_summary")
    probes = _nested_mapping(report, "probe_summary")
    blockers = _list_value(report, "readiness_blockers", "B6 blockers")
    lines = [
        "# HTR-010B6 Governed Approval-Constraint Frontier",
        "",
        f"- Readiness: `{report['readiness_decision']}`",
        f"- Replay sessions: `{report['session_count']}`",
        f"- RAW approvable candidates: `{raw['candidate_count']}`",
        f"- ADJUSTED approvable candidates: `{adjusted['candidate_count']}`",
        f"- RAW constraints: `{raw['constraint_count']}`",
        f"- ADJUSTED constraints: `{adjusted['constraint_count']}`",
        f"- RAW nearest frontier: `{raw['nearest_frontier_symbol']}`",
        f"- ADJUSTED nearest frontier: `{adjusted['nearest_frontier_symbol']}`",
        f"- Boundary probes passed: `{probes['passed_probe_count']}`",
        f"- Implementation defects: `{report['implementation_defect_count']}`",
        "- Unexplained constraint divergences: "
        f"`{report['unexplained_constraint_divergence_count']}`",
        f"- Readiness blockers: `{','.join(blockers) if blockers else 'NONE'}`",
        "",
        "## Governance",
        "",
        "- Policy and threshold changes are prohibited.",
        "- Remediation rows describe work required under the existing policy.",
        "- No counterfactual approval is claimed.",
        "- Governed adjusted trade research remains disabled.",
        "- Live scoring, recommendation, allocation, execution, learning, active "
        "replay, and production influence remain disabled.",
        "",
    ]
    return "\n".join(lines)


def _validate_digest(payload: Mapping[str, object], label: str) -> None:
    expected = str(payload.get("report_sha256") or "")
    if not _is_sha256(expected) or expected != _digest_mapping(payload):
        raise ValueError(f"{label} digest mismatch")


def _digest_mapping(payload: Mapping[str, object]) -> str:
    data = {key: value for key, value in payload.items() if key != "report_sha256"}
    return hashlib.sha256(
        json.dumps(
            _json_ready(data),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _digest_sequence(values: Sequence[object]) -> str:
    return hashlib.sha256(
        json.dumps(
            _json_ready(list(values)),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _json_ready(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (tuple, list, set, frozenset)):
        items = [_json_ready(item) for item in value]
        if isinstance(value, (set, frozenset)):
            return sorted(
                items,
                key=lambda item: json.dumps(item, sort_keys=True),
            )
        return items
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (tuple, list, set, frozenset)):
        return "|".join(str(item) for item in sorted(value, key=str))
    return value


def _file_sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact_path(root: Path, name: object) -> Path:
    text = str(name)
    candidate = Path(text)
    if candidate.name != text or candidate.is_absolute():
        raise ValueError(f"unsafe artifact name: {text}")
    return root / candidate


def _price_view(value: object) -> str:
    text = str(value or "").strip().upper()
    if text not in {"RAW", "ADJUSTED"}:
        raise ValueError(f"invalid price view: {value}")
    return text


def _symbol(value: object, label: str) -> str:
    text = str(value or "").strip().upper()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def _date_value(value: object, label: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as error:
        raise ValueError(f"{label} is invalid") from error


def _boolean(value: object, label: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no", ""}:
        return False
    raise ValueError(f"{label} is invalid")


def _integer(value: object, label: str) -> int:
    try:
        result = int(str(value))
    except ValueError as error:
        raise ValueError(f"{label} is invalid") from error
    if result < 0:
        raise ValueError(f"{label} cannot be negative")
    return result


def _decimal(value: object, label: str) -> Decimal:
    observed = _optional_decimal(value)
    if observed is None:
        raise ValueError(f"{label} is required")
    return observed


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as error:
        raise ValueError(f"invalid decimal value: {value}") from error


def _tuple_value(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (tuple, list, set, frozenset)):
        return tuple(sorted(str(item) for item in value if str(item)))
    text = str(value).strip()
    if not text:
        return ()
    return tuple(sorted(item for item in text.split("|") if item))


def _list_value(
    payload: Mapping[str, object],
    key: str,
    label: str,
) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return tuple(str(item) for item in value)


def _average(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, Decimal("0")) / Decimal(len(values))).quantize(
        Decimal("0.000001"),
        rounding=ROUND_HALF_UP,
    )


def _median(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return ((ordered[middle - 1] + ordered[middle]) / Decimal("2")).quantize(
        Decimal("0.000001"),
        rounding=ROUND_HALF_UP,
    )


def _average_int(values: Sequence[int]) -> Decimal:
    if not values:
        return Decimal("0")
    return (Decimal(sum(values)) / Decimal(len(values))).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def _constraint_sort_key(row: Mapping[str, object]) -> tuple[str, str, str, str, str]:
    return (
        str(row["price_view"]),
        str(row["observed_on"]),
        str(row["symbol"]),
        str(row["stage"]),
        str(row["constraint_id"]),
    )


def _candidate_sort_key(row: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(row["price_view"]),
        str(row["observed_on"]),
        str(row["symbol"]),
    )


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _progress(
    callback: ProgressCallback | None,
    current: int,
    total: int,
    description: str,
) -> None:
    if callback is not None:
        callback(current, total, description)


__all__ = [
    "B6_BLOCKED_DEFECT",
    "B6_BLOCKED_DIVERGENCE",
    "B6_BLOCKED_EMPTY",
    "B6_BLOCKED_EVIDENCE",
    "B6_READY",
    "HTR010B6_CONTRACT_VERSION",
    "RESEARCH_SCOPE",
    "ConstraintSpec",
    "GovernedApprovalConstraintFrontierEngine",
    "GovernedApprovalConstraintFrontierResult",
    "export_governed_approval_constraint_frontier",
    "validate_governed_approval_constraint_frontier_certificate",
]
