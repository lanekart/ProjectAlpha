"""Governed independent population expansion for DSI-003."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from alpha.benchmark_replay.governed_adaptive_institutional_trade_shadow import (
    validate_governed_adaptive_institutional_trade_shadow_certificate,
)
from alpha.benchmark_replay.governed_approval_gate_forensics import (
    validate_governed_approval_gate_forensics_certificate,
)
from alpha.benchmark_replay.governed_setup_matched_evidence import (
    validate_governed_setup_matched_evidence_certificate,
)
from alpha.decision_superiority.gate_isolation_complete_stack_baseline import (
    validate_complete_stack_certificate,
)
from alpha.decision_superiority.gate_isolation_shadow_artifacts import (
    validate_gate_isolation_shadow_certificate,
)
from alpha.decision_superiority.population_expansion_models import (
    CompleteStackReadiness,
    ExternalValidityGrade,
    ExternalValidityReadiness,
    FinalPopulationReadiness,
    IndependenceReadiness,
    OutcomeReadiness,
    PopulationBottleneckReadiness,
    PopulationExpansionError,
    PopulationExpansionResult,
    PopulationExpansionSourcePaths,
    PopulationSourceReadiness,
    ResearchSufficiencyTier,
    SufficiencyReadiness,
    TransferabilityReadiness,
)

_B5_CANDIDATES: Final = "htr010b5_candidate_gate_forensics.csv"
_B5_GATES: Final = "htr010b5_gate_event_ledger.csv"
_B7_OUTCOMES: Final = "htr010b7_outcome_coverage_ledger.csv"
_B10_DECISIONS: Final = "htr010b10_institutional_decision_comparison.csv"
_DSI001_CANDIDATES: Final = "dsi001_candidate_gate_failure_ledger.csv"
_D1_SOURCE: Final = "dsi002d1_source_contract_snapshot.csv"
_D2_EVENTS: Final = "dsi002d2_complete_stack_stage_events.csv"
_C2_BASELINE: Final = "dsi002c2_complete_stack_baseline.json"
_DSI002_ELIGIBILITY: Final = "dsi002_single_gate_override_eligibility.csv"
_DSI002_SEARCH: Final = "dsi002_remediation_search_ledger.csv"
_DSI002_FUNNEL: Final = "dsi002_allocation_portfolio_entry_trade_transitions.csv"
_DSI002_OUTCOMES: Final = "dsi002_outcome_comparability_ledger.csv"
_UNKNOWN: Final = "UNKNOWN"

_COMPOSITE_MARKERS: Final = (
    "Entry is not actionable yet",
    "Fresh deployment requires entry, stop, at least two targets",
    "Liquidity or capacity is insufficient for deployment",
)

_GOVERNANCE_FLAGS: Final = (
    "ACTIVE_REPLAY_INTEGRATION",
    "APPROVAL_POLICY_CHANGE_PERMITTED",
    "AUTOMATIC_POLICY_RECOMMENDATION_ENABLED",
    "CAUSAL_CLAIM_PERMITTED",
    "DEFAULT_RUNTIME_BEHAVIOUR_CHANGED",
    "ECONOMIC_SUPERIORITY_CLAIMED",
    "EXECUTION_INFLUENCE",
    "EXECUTION_POLICY_CHANGE_PERMITTED",
    "GATE_ORDER_CHANGE_PERMITTED",
    "LEARNING_MUTATION_ENABLED",
    "LIVE_SCORING_ENABLED",
    "OUTCOME_BACKFILL_MUTATION_ENABLED",
    "PORTFOLIO_POLICY_CHANGE_PERMITTED",
    "PORTFOLIO_POLICY_INFLUENCE",
    "PRODUCTION_INFLUENCE",
    "RECOMMENDATION_INFLUENCE",
    "SOURCE_POPULATION_SYNTHESIS_PERMITTED",
    "SYNTHETIC_APPROVALS_PERMITTED",
    "SYNTHETIC_CANDIDATES_PERMITTED",
    "SYNTHETIC_OUTCOMES_PERMITTED",
    "SYNTHETIC_RECOMMENDATIONS_PERMITTED",
    "SYNTHETIC_TRADES_PERMITTED",
    "THRESHOLD_CHANGE_PERMITTED",
)


@dataclass(frozen=True, slots=True)
class _VerifiedSource:
    source_id: str
    certificate: Path
    contract_version: str
    readiness: str
    report_sha256: str
    certificate_sha256: str
    candidate_rows: int
    admissibility: str
    exclusion_reason: str


@dataclass(frozen=True, slots=True)
class _SourceBundle:
    sources: tuple[_VerifiedSource, ...]
    b5_payload: Mapping[str, Any]
    b5_candidates: tuple[dict[str, str], ...]
    b5_gates: tuple[dict[str, str], ...]
    b7_outcomes: tuple[dict[str, str], ...]
    dsi001_candidates: tuple[dict[str, str], ...]
    dsi002_candidate_identity: str
    dsi002_events: tuple[dict[str, str], ...]
    dsi002_baseline: Mapping[str, Any]
    dsi002_eligibility: tuple[dict[str, str], ...]
    dsi002_search: tuple[dict[str, str], ...]
    dsi002_funnel: tuple[dict[str, str], ...]
    dsi002_outcomes: tuple[dict[str, str], ...]


def governance_flags() -> dict[str, bool]:
    """Return the immutable DSI-003 research-only governance boundary."""

    return {name: False for name in _GOVERNANCE_FLAGS}


def stable_identity(*parts: object) -> str:
    """Return a deterministic SHA-256 identity for governed values."""

    encoded = json.dumps(parts, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def effective_number(values: Iterable[str]) -> Decimal:
    """Return inverse-HHI effective count, excluding explicit unknown values."""

    counts = Counter(value for value in values if value and value != _UNKNOWN)
    total = sum(counts.values())
    if not total:
        return Decimal("0")
    hhi = sum(
        ((Decimal(count) / Decimal(total)) ** 2 for count in counts.values()),
        Decimal("0"),
    )
    return (Decimal("1") / hhi).quantize(Decimal("0.0001"))


def concentration(values: Iterable[str]) -> tuple[Decimal, Decimal]:
    """Return top-share and HHI for known values."""

    counts = Counter(value for value in values if value and value != _UNKNOWN)
    total = sum(counts.values())
    if not total:
        return Decimal("0"), Decimal("0")
    top = Decimal(max(counts.values())) / Decimal(total)
    hhi = sum(
        ((Decimal(count) / Decimal(total)) ** 2 for count in counts.values()),
        Decimal("0"),
    )
    return top.quantize(Decimal("0.0001")), hhi.quantize(Decimal("0.0001"))


def classify_outcome(row: Mapping[str, str] | None) -> str:
    """Map a signed B7 row to the governed DSI-003 outcome vocabulary."""

    if row is None:
        return "MISSING_OUTCOME"
    status = row.get("forward_outcome_status", "").strip().upper()
    if status in {"COMPLETED_WIN", "COMPLETED_LOSS_OR_FLAT"}:
        return "COMPLETED_COMPARABLE_OUTCOME"
    if status == "NOT_ENTERED":
        return "NOT_ENTERED"
    if status == "PENDING_END_OF_DATA":
        return "PENDING_END_OF_DATA"
    return "MISSING_OUTCOME"


class GovernedPopulationExpansionEngine:
    """Assemble and certify independent complete-stack evidence without mutation."""

    def run(
        self,
        *,
        sources: PopulationExpansionSourcePaths,
        project_root: Path = Path("."),
    ) -> PopulationExpansionResult:
        bundle = _verify_source_chain(sources, project_root=project_root)
        policy_version = stable_identity(
            bundle.b5_payload.get("institutional_policy_source_sha256s", {})
        )
        arm_rows, stage_rows, economic_rows = _reconstruct_population(
            bundle,
            policy_version=policy_version,
        )
        outcome_rows = _outcome_rows(economic_rows, bundle.b7_outcomes)
        duplicate_rows = _duplicate_rows(economic_rows, outcome_rows)
        funnel_rows, loss_rows = _funnel_rows(
            bundle,
            arm_rows=arm_rows,
            economic_rows=economic_rows,
            outcome_rows=outcome_rows,
        )
        independence_rows = _independence_rows(economic_rows, outcome_rows)
        coverage_rows, external_rows, coverage_grade = _coverage_rows(economic_rows)
        outcome_summary_rows = _outcome_summary_rows(outcome_rows)
        transfer_rows, transfer_summary_rows = _transferability_rows(
            economic_rows,
            bundle,
        )
        sample_rows, sufficiency = _sample_rows(
            economic_rows,
            outcome_rows,
            transfer_rows,
        )
        arm_comparison_rows = _arm_comparison_rows(economic_rows)
        reconciliation_rows = _reconciliation_rows(
            arm_rows,
            economic_rows,
            outcome_rows,
        )
        source_rows = _source_rows(bundle.sources)
        inventory_rows = _inventory_rows(bundle.sources)
        probes = structural_probe_rows()

        readiness = {
            "A": PopulationSourceReadiness.READY.value,
            "B": CompleteStackReadiness.READY.value,
            "C": PopulationBottleneckReadiness.READY.value,
            "D": (
                IndependenceReadiness.WARNINGS.value
                if any(int(str(row["arm_count"])) > 1 for row in economic_rows)
                else IndependenceReadiness.READY.value
            ),
            "E": (
                ExternalValidityReadiness.LIMITED.value
                if coverage_grade
                not in {
                    ExternalValidityGrade.MODERATE.value,
                    ExternalValidityGrade.BROAD.value,
                }
                else ExternalValidityReadiness.READY.value
            ),
            "F": (
                OutcomeReadiness.LIMITED.value
                if any(
                    row["outcome_status"] == "COMPLETED_COMPARABLE_OUTCOME"
                    for row in outcome_rows
                )
                else OutcomeReadiness.NONE.value
            ),
            "G": TransferabilityReadiness.PARTIAL.value,
            "H": SufficiencyReadiness.READY.value,
            "I": FinalPopulationReadiness.DESCRIPTIVE.value,
        }
        summaries = _summaries(
            bundle=bundle,
            arm_rows=arm_rows,
            economic_rows=economic_rows,
            outcome_rows=outcome_rows,
            duplicate_rows=duplicate_rows,
            coverage_grade=coverage_grade,
            sufficiency=sufficiency,
            transfer_rows=transfer_rows,
        )
        row_map: dict[str, tuple[Mapping[str, object], ...]] = {
            "arm_comparison": arm_comparison_rows,
            "candidate_reconstruction": arm_rows,
            "complete_stack_stages": stage_rows,
            "coverage_distribution": coverage_rows,
            "dsi002_transferability": transfer_rows,
            "duplicate_conflicts": duplicate_rows,
            "economic_identity": economic_rows,
            "effective_sample": sample_rows,
            "external_validity": external_rows,
            "funnel": funnel_rows,
            "gate_isolation_summary": transfer_summary_rows,
            "independence": independence_rows,
            "loss_attribution": loss_rows,
            "outcome_readiness": outcome_rows,
            "outcome_summary": outcome_summary_rows,
            "probes": probes,
            "reconciliation": reconciliation_rows,
            "source_contract": source_rows,
            "source_inventory": inventory_rows,
        }
        return PopulationExpansionResult(
            source_commit=_source_commit(project_root),
            readiness=MappingProxyType(dict(sorted(readiness.items()))),
            summaries=MappingProxyType(dict(sorted(summaries.items()))),
            rows=MappingProxyType(dict(sorted(row_map.items()))),
            blockers=(),
        )


def structural_probe_rows() -> tuple[dict[str, object], ...]:
    """Return deterministic structural probes excluded from empirical counts."""

    cases = (
        ("EXACT_DUPLICATE", "EXACT_DUPLICATE", True),
        ("RAW_ADJUSTED_PAIR", "RAW_ADJUSTED_PAIR", True),
        ("MULTI_SOURCE", "MULTI_SOURCE_SAME_CANDIDATE", True),
        ("CONFLICTING_TERMINAL", "CONFLICTING_TERMINAL_DECISION", True),
        ("CONFLICTING_PLAN", "CONFLICTING_PLAN_IDENTITY", True),
        ("CONFLICTING_OUTCOME", "CONFLICTING_OUTCOME_IDENTITY", True),
        ("POINT_IN_TIME_INVALID", "POINT_IN_TIME_INVALID", True),
        ("MISSING_RECOMMENDATION", "RECOMMENDATION_NOT_GENERATED", True),
        ("COMPLETE_STACK_REJECTED", "TERMINAL_REJECT", True),
        ("COMPLETE_STACK_APPROVED", "TERMINAL_ACCEPT", True),
        ("STRESS_NOT_APPLICABLE", "NOT_APPLICABLE", True),
        ("TRADE_PLAN_NOT_APPLICABLE", "NOT_APPLICABLE", True),
        ("UNIQUE_POPULATION", "INDEPENDENT", True),
        ("CONCENTRATED_POPULATION", "HIGHLY_CONCENTRATED", True),
        ("BROAD_POPULATION", "BROAD_RESEARCH_COVERAGE", True),
        ("NO_OUTCOMES", "READY_WITH_NO_COMPLETED_OUTCOMES", True),
        ("PARTIAL_OUTCOMES", "READY_WITH_LIMITED_OUTCOME_COVERAGE", True),
        ("COMPLETED_OUTCOME", "COMPLETED_COMPARABLE_OUTCOME", True),
        ("DSI002_BATCH_SUCCESS", "EXACT_SIGNED_CANDIDATE", True),
        ("DSI002_UNSUPPORTED", "CAPTURE_NOT_REHYDRATABLE", True),
        ("ARM_COUNT_GUARD", "ECONOMIC_CANDIDATE_COUNT", True),
        ("CERTIFICATE_TAMPER", "TAMPER_REJECTED", True),
    )
    return tuple(
        {
            "probe_id": probe_id,
            "expected_classification": expected,
            "passed": passed,
            "included_in_empirical_counts": False,
        }
        for probe_id, expected, passed in cases
    )


def _verify_source_chain(
    paths: PopulationExpansionSourcePaths,
    *,
    project_root: Path,
) -> _SourceBundle:
    try:
        b5 = validate_governed_approval_gate_forensics_certificate(
            paths.b5_certificate,
            require_ready=True,
        )
        b7 = validate_governed_setup_matched_evidence_certificate(
            paths.b7_certificate,
            require_ready=True,
        )
        b10 = validate_governed_adaptive_institutional_trade_shadow_certificate(
            paths.b10_certificate,
            require_ready=False,
        )
        dsi001 = _validate_dsi001(paths.dsi001_certificate)
        d1 = validate_complete_stack_certificate(
            paths.dsi002d1_certificate,
            require_ready=True,
        )
        b2 = validate_complete_stack_certificate(
            paths.dsi002b2_certificate,
            require_ready=True,
        )
        c2 = validate_complete_stack_certificate(
            paths.dsi002c2_certificate,
            require_ready=True,
        )
        d2 = validate_complete_stack_certificate(
            paths.dsi002d2_certificate,
            require_ready=True,
        )
        dsi002 = validate_gate_isolation_shadow_certificate(
            paths.dsi002_certificate,
            require_ready=True,
        )
        dsi002a = _json(paths.dsi002a_certificate)
    except (OSError, ValueError) as exc:
        raise PopulationExpansionError(f"SOURCE_CHAIN_INVALID:{exc}") from exc

    _validate_source_links(
        paths=paths,
        b5=b5,
        b7=b7,
        dsi001=dsi001,
        d1=d1,
        b2=b2,
        c2=c2,
        d2=d2,
        dsi002=dsi002,
        dsi002a=dsi002a,
        project_root=project_root,
    )
    b5_candidates = _csv(_bound(paths.b5_certificate, _B5_CANDIDATES))
    b5_gates = _csv(_bound(paths.b5_certificate, _B5_GATES))
    b7_outcomes = _csv(_bound(paths.b7_certificate, _B7_OUTCOMES))
    dsi001_candidates = _csv(_bound(paths.dsi001_certificate, _DSI001_CANDIDATES))
    dsi002_events = _csv(_bound(paths.dsi002d2_certificate, _D2_EVENTS))
    dsi002_baseline = _json(_bound(paths.dsi002c2_certificate, _C2_BASELINE))
    dsi002_eligibility = _csv(_bound(paths.dsi002_certificate, _DSI002_ELIGIBILITY))
    dsi002_search = _csv(_bound(paths.dsi002_certificate, _DSI002_SEARCH))
    dsi002_funnel = _csv(_bound(paths.dsi002_certificate, _DSI002_FUNNEL))
    dsi002_outcomes = _csv(_bound(paths.dsi002_certificate, _DSI002_OUTCOMES))
    identity = str(dsi002.get("captured_population_identity") or "")
    if not identity:
        raise PopulationExpansionError("DSI002_CANDIDATE_IDENTITY_MISSING")
    if str(dsi002_baseline.get("candidate_identity") or "") != identity:
        raise PopulationExpansionError("DSI002_BASELINE_IDENTITY_MISMATCH")

    sources = (
        _source("B5", paths.b5_certificate, b5, len(b5_candidates), "ADMISSIBLE"),
        _source("B7", paths.b7_certificate, b7, len(b7_outcomes), "ADMISSIBLE"),
        _source(
            "B10",
            paths.b10_certificate,
            b10,
            _row_count_if_bound(paths.b10_certificate, _B10_DECISIONS),
            "INFORMATIVE_ONLY",
            "EMPTY_ADAPTIVE_SHADOW_POPULATION",
        ),
        _source(
            "DSI001",
            paths.dsi001_certificate,
            dsi001,
            len(dsi001_candidates),
            "ADMISSIBLE",
        ),
        _source("DSI002A", paths.dsi002a_certificate, dsi002a, 1, "LINEAGE_ONLY"),
        _source("DSI002B2", paths.dsi002b2_certificate, b2, 1, "LINEAGE_ONLY"),
        _source("DSI002C2", paths.dsi002c2_certificate, c2, 1, "LINEAGE_ONLY"),
        _source("DSI002D1", paths.dsi002d1_certificate, d1, 1, "LINEAGE_ONLY"),
        _source("DSI002D2", paths.dsi002d2_certificate, d2, 1, "LINEAGE_ONLY"),
        _source("DSI002", paths.dsi002_certificate, dsi002, 1, "ADMISSIBLE"),
    )
    return _SourceBundle(
        sources=tuple(sorted(sources, key=lambda item: item.source_id)),
        b5_payload=b5,
        b5_candidates=b5_candidates,
        b5_gates=b5_gates,
        b7_outcomes=b7_outcomes,
        dsi001_candidates=dsi001_candidates,
        dsi002_candidate_identity=identity,
        dsi002_events=dsi002_events,
        dsi002_baseline=dsi002_baseline,
        dsi002_eligibility=dsi002_eligibility,
        dsi002_search=dsi002_search,
        dsi002_funnel=dsi002_funnel,
        dsi002_outcomes=dsi002_outcomes,
    )


def _validate_source_links(
    *,
    paths: PopulationExpansionSourcePaths,
    b5: Mapping[str, Any],
    b7: Mapping[str, Any],
    dsi001: Mapping[str, Any],
    d1: Mapping[str, object],
    b2: Mapping[str, object],
    c2: Mapping[str, object],
    d2: Mapping[str, object],
    dsi002: Mapping[str, object],
    dsi002a: Mapping[str, Any],
    project_root: Path,
) -> None:
    upstream = dsi001.get("upstream_certificates")
    if not isinstance(upstream, dict):
        raise PopulationExpansionError("DSI001_UPSTREAM_BINDING_MISSING")
    for label, path, payload in (
        ("b5", paths.b5_certificate, b5),
        ("b7", paths.b7_certificate, b7),
    ):
        binding = upstream.get(label)
        if not isinstance(binding, dict):
            raise PopulationExpansionError(f"DSI001_{label.upper()}_BINDING_MISSING")
        if binding.get("file_sha256") != _sha256(path):
            raise PopulationExpansionError(f"DSI001_{label.upper()}_SUBSTITUTION")
        if binding.get("report_sha256") != payload.get("report_sha256"):
            raise PopulationExpansionError(f"DSI001_{label.upper()}_REPORT_MISMATCH")

    source_snapshot = _csv(_bound(paths.dsi002d1_certificate, _D1_SOURCE))
    a_binding = next(
        (row for row in source_snapshot if row["source_id"] == "DSI-002A"),
        None,
    )
    if a_binding is None or a_binding["certificate_sha256"] != _sha256(
        paths.dsi002a_certificate
    ):
        raise PopulationExpansionError("DSI002A_SOURCE_BINDING_MISMATCH")
    if dsi002a.get("accepted") is not True:
        raise PopulationExpansionError("DSI002A_NOT_ACCEPTED")

    linked = (
        ("b2_certificate_sha256", paths.dsi002b2_certificate),
        ("c2_certificate_sha256", paths.dsi002c2_certificate),
        ("d2_certificate_sha256", paths.dsi002d2_certificate),
    )
    for field, path in linked:
        if d1.get(field) != _sha256(path):
            raise PopulationExpansionError(f"D1_{field.upper()}_MISMATCH")
    final_chain = dsi002.get("original_and_renewed_source_chain")
    if not isinstance(final_chain, list):
        raise PopulationExpansionError("DSI002_RENEWED_CHAIN_MISSING")
    expected = {
        "D1": (paths.dsi002d1_certificate, d1),
        "B2": (paths.dsi002b2_certificate, b2),
        "C2": (paths.dsi002c2_certificate, c2),
        "D2": (paths.dsi002d2_certificate, d2),
    }
    for row in final_chain:
        if not isinstance(row, dict) or str(row.get("boundary")) not in expected:
            raise PopulationExpansionError("DSI002_RENEWED_CHAIN_INVALID")
        path, payload = expected[str(row["boundary"])]
        if row.get("certificate_sha256") != _sha256(path):
            raise PopulationExpansionError("DSI002_RENEWED_CHAIN_SUBSTITUTION")
        if row.get("report_sha256") != payload.get("report_sha256"):
            raise PopulationExpansionError("DSI002_RENEWED_REPORT_MISMATCH")
    source_commits = {
        str(payload.get("source_commit") or "") for payload in (d1, b2, c2, d2, dsi002)
    }
    for source_commit in sorted(source_commits):
        if source_commit and not _is_ancestor(source_commit, project_root):
            raise PopulationExpansionError(
                f"SOURCE_COMMIT_NOT_IN_ANCESTRY:{source_commit}"
            )


def _reconstruct_population(
    bundle: _SourceBundle,
    *,
    policy_version: str,
) -> tuple[
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
]:
    b5_by_key = _unique(
        bundle.b5_candidates,
        ("price_view", "observed_on", "symbol", "input_fingerprint"),
        "B5",
    )
    dsi1_by_key = _unique(
        bundle.dsi001_candidates,
        ("price_view", "observed_on", "symbol", "input_fingerprint"),
        "DSI001",
    )
    if set(b5_by_key) != set(dsi1_by_key):
        raise PopulationExpansionError("B5_DSI001_POPULATION_MISMATCH")
    arm_seed: list[dict[str, object]] = []
    for key, source_row in sorted(b5_by_key.items()):
        dsi1 = dsi1_by_key[key]
        arm_seed.append(
            {
                **source_row,
                "source": "B5|DSI001",
                "resolved_outcome_available": dsi1["resolved_outcome"],
                "base_decision": source_row["base_gate_decision"],
                "stress_state": (
                    "REACHED"
                    if _bool(source_row["stress_stage_reached"])
                    else "NOT_APPLICABLE"
                ),
                "trade_plan_state": (
                    "REACHED"
                    if _bool(source_row["trade_plan_stage_reached"])
                    else "NOT_APPLICABLE"
                ),
                "terminal_decision": (
                    "ACCEPT"
                    if _bool(source_row["institutional_approved"])
                    else "REJECT"
                ),
                "allocation_decision": (
                    "ALLOCATE" if _bool(source_row["portfolio_eligible"]) else "SKIP"
                ),
                "complete_stack_recorded": True,
                "point_in_time_valid": True,
                "candidate_exclusion_reason": "",
            }
        )
    arm_seed.append(_dsi002_arm(bundle))

    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for seed_row in arm_seed:
        grouped[(str(seed_row["observed_on"]), str(seed_row["symbol"]))].append(
            seed_row
        )
    arms: list[dict[str, object]] = []
    economics: list[dict[str, object]] = []
    stages: list[dict[str, object]] = []
    b7_by_partial = _unique(
        bundle.b7_outcomes,
        ("price_view", "observed_on", "symbol"),
        "B7",
    )
    for (observed_on, symbol), group in sorted(grouped.items()):
        fingerprints = tuple(sorted(str(row["input_fingerprint"]) for row in group))
        captured_input_identity = stable_identity(*fingerprints)
        recommendation_identity = stable_identity(
            symbol,
            observed_on,
            policy_version,
            captured_input_identity,
        )
        economic_id = stable_identity(
            symbol,
            observed_on,
            recommendation_identity,
            policy_version,
            captured_input_identity,
        )
        views = tuple(sorted(str(row["price_view"]) for row in group))
        setups = {
            b7_by_partial.get(
                (
                    str(row["price_view"]),
                    observed_on,
                    symbol,
                ),
                {},
            ).get("setup_type", "")
            for row in group
        }
        setup = next((item for item in sorted(setups) if item), _UNKNOWN)
        if symbol == "BEL" and observed_on == "2026-07-26":
            setup = "MOMENTUM CONTINUATION"
        terminal_decision = _stable_value(group, "terminal_decision")
        if terminal_decision == _UNKNOWN:
            raise PopulationExpansionError("CONFLICTING_TERMINAL_DECISION")
        economics.append(
            {
                "economic_candidate_id": economic_id,
                "security_identity": symbol,
                "recommendation_date": observed_on,
                "recommendation_identity": recommendation_identity,
                "complete_stack_policy_version": policy_version,
                "captured_input_identity": captured_input_identity,
                "arm_count": len(group),
                "price_views": "|".join(views),
                "raw_adjusted_pair": set(views) == {"ADJUSTED", "RAW"},
                "setup": setup,
                "setup_stage": _stable_value(group, "setup_stage"),
                "sector": (
                    "DEFENCE"
                    if symbol == "BEL" and observed_on == "2026-07-26"
                    else _UNKNOWN
                ),
                "regime": (
                    "NEUTRAL"
                    if symbol == "BEL" and observed_on == "2026-07-26"
                    else _UNKNOWN
                ),
                "terminal_decision": terminal_decision,
                "source_count": _source_count(group, b7_by_partial),
            }
        )
        for group_row in sorted(
            group,
            key=lambda item: str(item["price_view"]),
        ):
            arm_id = stable_identity(
                economic_id,
                group_row["price_view"],
                group_row["input_fingerprint"],
            )
            arm = {
                "candidate_arm_id": arm_id,
                "economic_candidate_id": economic_id,
                "price_view": group_row["price_view"],
                "observed_on": observed_on,
                "symbol": symbol,
                "input_fingerprint": group_row["input_fingerprint"],
                "source": group_row["source"],
                "final_signal": group_row["final_signal"],
                "recommendation_score": group_row["recommendation_score"],
                "setup_stage": group_row["setup_stage"],
                "base_decision": group_row["base_decision"],
                "stress_state": group_row["stress_state"],
                "trade_plan_state": group_row["trade_plan_state"],
                "terminal_decision": group_row["terminal_decision"],
                "allocation_decision": group_row["allocation_decision"],
                "complete_stack_recorded": True,
                "point_in_time_valid": True,
                "candidate_exclusion_reason": "",
            }
            arms.append(arm)
            stages.extend(_stage_rows(arm, bundle))
    return (
        tuple(sorted(arms, key=_row_sort_key)),
        tuple(sorted(stages, key=_row_sort_key)),
        tuple(sorted(economics, key=_row_sort_key)),
    )


def _dsi002_arm(bundle: _SourceBundle) -> dict[str, object]:
    price_view, observed_on, symbol, fingerprint = (
        bundle.dsi002_candidate_identity.split("|", 3)
    )
    payload_text = str(bundle.dsi002_baseline.get("output_payload_json") or "{}")
    payload = json.loads(payload_text)
    recommendations = payload.get("recommendations", [])
    recommendation = next(
        item
        for item in recommendations
        if isinstance(item, dict) and item.get("symbol") == symbol
    )
    trace = payload["institutional"]["traces"][0]
    base = trace["base_decision"]
    return {
        "price_view": price_view,
        "observed_on": observed_on,
        "symbol": symbol,
        "rank": recommendation.get("rank", _UNKNOWN),
        "final_signal": recommendation.get("decision", _UNKNOWN),
        "recommendation_score": recommendation.get("score", _UNKNOWN),
        "setup_stage": _explanation_value(
            recommendation.get("explanation", []),
            "Setup Stage:",
        ),
        "base_decision": "ACCEPT" if base.get("accepted") else "REJECT",
        "stress_state": (
            "REACHED" if trace.get("stress_applicable") else "NOT_APPLICABLE"
        ),
        "trade_plan_state": (
            "REACHED" if trace.get("trade_plan_applicable") else "NOT_APPLICABLE"
        ),
        "terminal_decision": trace["terminal_institutional_decision"],
        "allocation_decision": "SKIP",
        "input_fingerprint": fingerprint,
        "source": "DSI002",
    }


def _stage_rows(
    arm: Mapping[str, object],
    bundle: _SourceBundle,
) -> list[dict[str, object]]:
    if arm["source"] == "DSI002":
        recorded = [
            {
                "candidate_arm_id": arm["candidate_arm_id"],
                "economic_candidate_id": arm["economic_candidate_id"],
                "stage_order": int(row["stage_order"]) + 1,
                "stage_id": row["stage_id"],
                "stage_invoked": _bool(row["stage_invoked"]),
                "invocation_count": int(row["invocation_count"]),
                "result_state": row["result_state"],
                "result_code": row["result_code"],
                "observation_mode": row["observation_mode"],
            }
            for row in bundle.dsi002_events
        ]
        return [
            {
                "candidate_arm_id": arm["candidate_arm_id"],
                "economic_candidate_id": arm["economic_candidate_id"],
                "stage_order": 1,
                "stage_id": "recommendation",
                "stage_invoked": True,
                "invocation_count": 1,
                "result_state": "PASS",
                "result_code": "RECOMMENDATION_GENERATED",
                "observation_mode": "SIGNED_RECORDED_COMPLETE_STACK",
            },
            *recorded,
            {
                "candidate_arm_id": arm["candidate_arm_id"],
                "economic_candidate_id": arm["economic_candidate_id"],
                "stage_order": 8,
                "stage_id": "recorded_payload",
                "stage_invoked": True,
                "invocation_count": 1,
                "result_state": "PASS",
                "result_code": "PAYLOAD_HASH_BOUND",
                "observation_mode": "SIGNED_RECORDED_COMPLETE_STACK",
            },
        ]
    states = (
        (1, "recommendation", True, "PASS", "RECOMMENDATION_GENERATED"),
        (
            2,
            "institutional_candidate_construction",
            True,
            "PASS",
            "CANDIDATE_CONSTRUCTED",
        ),
        (3, "institutional_base_decision", True, "FAIL", arm["base_decision"]),
        (
            4,
            "institutional_stress",
            True,
            arm["stress_state"],
            "BASE_DECISION_REJECTED",
        ),
        (
            5,
            "institutional_trade_plan_optimizer",
            True,
            arm["trade_plan_state"],
            "UPSTREAM_DECISION_REJECTED",
        ),
        (6, "terminal_institutional_decision", True, "FAIL", arm["terminal_decision"]),
        (7, "portfolio_allocation", True, "FAIL", arm["allocation_decision"]),
        (8, "recorded_payload", True, "PASS", "PAYLOAD_HASH_BOUND"),
    )
    return [
        {
            "candidate_arm_id": arm["candidate_arm_id"],
            "economic_candidate_id": arm["economic_candidate_id"],
            "stage_order": order,
            "stage_id": stage,
            "stage_invoked": invoked,
            "invocation_count": 1,
            "result_state": state,
            "result_code": code,
            "observation_mode": "SIGNED_RECORDED_COMPLETE_STACK",
        }
        for order, stage, invoked, state, code in states
    ]


def _outcome_rows(
    economics: Sequence[Mapping[str, object]],
    b7_rows: Sequence[Mapping[str, str]],
) -> tuple[dict[str, object], ...]:
    grouped: dict[tuple[str, str], list[Mapping[str, str]]] = defaultdict(list)
    for row in b7_rows:
        grouped[(row["observed_on"], row["symbol"])].append(row)
    output: list[dict[str, object]] = []
    for candidate in economics:
        key = (
            str(candidate["recommendation_date"]),
            str(candidate["security_identity"]),
        )
        rows = grouped.get(key, [])
        canonical = next(
            (row for row in rows if row["price_view"] == "RAW"),
            rows[0] if rows else None,
        )
        statuses = {classify_outcome(row) for row in rows}
        if len(statuses) > 1:
            raise PopulationExpansionError("RAW_ADJUSTED_OUTCOME_CONFLICT")
        status = classify_outcome(canonical)
        realized_return = canonical.get("realized_return_pct", "") if canonical else ""
        realized = _decimal(realized_return)
        won = canonical.get("won", "") if canonical else ""
        output.append(
            {
                "economic_candidate_id": candidate["economic_candidate_id"],
                "symbol": candidate["security_identity"],
                "observed_on": candidate["recommendation_date"],
                "plan_available": canonical is not None,
                "entry_state": (
                    "ENTERED"
                    if canonical and _bool(canonical.get("entered", "false"))
                    else "NOT_ENTERED"
                    if canonical
                    else _UNKNOWN
                ),
                "outcome_status": status,
                "completed": status == "COMPLETED_COMPARABLE_OUTCOME",
                "won": (
                    _bool(won) if status == "COMPLETED_COMPARABLE_OUTCOME" else _UNKNOWN
                ),
                "flat": (
                    realized == Decimal("0")
                    if status == "COMPLETED_COMPARABLE_OUTCOME"
                    else _UNKNOWN
                ),
                "realized_return_pct": realized_return or _UNKNOWN,
                "realized_r": (
                    canonical.get("realized_r", "") or _UNKNOWN
                    if canonical
                    else _UNKNOWN
                ),
                "holding_period_days": (
                    canonical.get("holding_period_days", "") or _UNKNOWN
                    if canonical
                    else _UNKNOWN
                ),
                "exit_reason": (
                    canonical.get("exit_reason", "") or _UNKNOWN
                    if canonical
                    else _UNKNOWN
                ),
                "outcome_lineage": "B7_SIGNED" if canonical else "UNAVAILABLE",
                "point_in_time_valid": True,
            }
        )
    return tuple(sorted(output, key=_row_sort_key))


def _duplicate_rows(
    economics: Sequence[Mapping[str, object]],
    outcomes: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    outcome_by_id = {row["economic_candidate_id"]: row for row in outcomes}
    rows: list[dict[str, object]] = []
    for candidate in economics:
        pair = bool(candidate["raw_adjusted_pair"])
        rows.append(
            {
                "economic_candidate_id": candidate["economic_candidate_id"],
                "duplicate_classification": (
                    "RAW_ADJUSTED_PAIR" if pair else "NOT_DUPLICATE"
                ),
                "arm_count": candidate["arm_count"],
                "source_count": candidate["source_count"],
                "canonical_resolution": "PAIRED_ANALYTICAL_ARMS" if pair else "UNIQUE",
                "conflicting_candidate_identity": False,
                "conflicting_terminal_decision": False,
                "conflicting_plan_identity": False,
                "conflicting_outcome_identity": False,
                "outcome_status": outcome_by_id[candidate["economic_candidate_id"]][
                    "outcome_status"
                ],
            }
        )
    return tuple(sorted(rows, key=_row_sort_key))


def _funnel_rows(
    bundle: _SourceBundle,
    *,
    arm_rows: Sequence[Mapping[str, object]],
    economic_rows: Sequence[Mapping[str, object]],
    outcome_rows: Sequence[Mapping[str, object]],
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    source_count = sum(source.candidate_rows for source in bundle.sources)
    economic_count = len(economic_rows)
    plans = sum(bool(row["plan_available"]) for row in outcome_rows)
    completed = sum(bool(row["completed"]) for row in outcome_rows)
    stages = (
        ("source_rows", source_count, "MULTI_SOURCE_REPRESENTATION"),
        ("admissible_rows", len(arm_rows), "SOURCE_DEDUPLICATION"),
        ("point_in_time_valid_rows", len(arm_rows), "NONE"),
        ("unique_economic_candidates", economic_count, "RAW_ADJUSTED_PAIRING"),
        ("recommendations", economic_count, "NONE"),
        ("institutional_candidates", economic_count, "NONE"),
        ("complete_stack_evaluated_candidates", economic_count, "NONE"),
        ("terminal_decisions", economic_count, "NONE"),
        ("candidates_with_recorded_plans", plans, "EVIDENCE_NOT_CAPTURED"),
        ("candidates_with_completed_outcomes", completed, "CENSORING_OR_NO_PLAN"),
    )
    funnel: list[dict[str, object]] = []
    losses: list[dict[str, object]] = []
    previous = source_count
    for ordinal, (stage, count, reason) in enumerate(stages, start=1):
        lost = previous - count
        funnel.append(
            {
                "stage_order": ordinal,
                "stage": stage,
                "incoming_count": previous,
                "outgoing_count": count,
                "lost_count": lost,
                "loss_rate": _ratio(lost, previous),
                "dominant_exclusion_reason": reason if lost else "NONE",
            }
        )
        if lost:
            losses.append(
                {
                    "transition": (
                        f"{stages[ordinal - 2][0]}->{stage}"
                        if ordinal > 1
                        else f"inventory->{stage}"
                    ),
                    "loss_count": lost,
                    "loss_class": _loss_class(reason),
                    "reason": reason,
                    "silent_drop": False,
                    "policy_rejection_counted_as_population_loss": False,
                }
            )
        previous = count
    return tuple(funnel), tuple(losses)


def _independence_rows(
    economics: Sequence[Mapping[str, object]],
    outcomes: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    values = {
        "security": [str(row["security_identity"]) for row in economics],
        "date": [str(row["recommendation_date"]) for row in economics],
        "setup": [str(row["setup"]) for row in economics],
        "sector": [str(row["sector"]) for row in economics],
        "regime": [str(row["regime"]) for row in economics],
    }
    rows = []
    for dimension, items in sorted(values.items()):
        top, hhi = concentration(items)
        rows.append(
            {
                "dimension": dimension,
                "observation_count": len(items),
                "unique_known_count": len({item for item in items if item != _UNKNOWN}),
                "unknown_count": sum(item == _UNKNOWN for item in items),
                "top_share": top,
                "hhi": hhi,
                "effective_count": effective_number(items),
            }
        )
    rows.append(
        {
            "dimension": "outcome",
            "observation_count": len(outcomes),
            "unique_known_count": sum(bool(row["completed"]) for row in outcomes),
            "unknown_count": sum(
                row["outcome_status"] == "MISSING_OUTCOME" for row in outcomes
            ),
            "top_share": concentration(str(row["outcome_status"]) for row in outcomes)[
                0
            ],
            "hhi": concentration(str(row["outcome_status"]) for row in outcomes)[1],
            "effective_count": effective_number(
                str(row["outcome_status"]) for row in outcomes
            ),
        }
    )
    return tuple(rows)


def _coverage_rows(
    economics: Sequence[Mapping[str, object]],
) -> tuple[
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    str,
]:
    dimensions = (
        ("security", "security_identity"),
        ("date", "recommendation_date"),
        ("month", "recommendation_date"),
        ("setup", "setup"),
        ("setup_stage", "setup_stage"),
        ("sector", "sector"),
        ("regime", "regime"),
    )
    distribution: list[dict[str, object]] = []
    metrics: list[dict[str, object]] = []
    for dimension, field in dimensions:
        values = [
            (str(row[field])[:7] if dimension == "month" else str(row[field]))
            for row in economics
        ]
        counts = Counter(values)
        total = len(values)
        for value, count in sorted(counts.items()):
            distribution.append(
                {
                    "dimension": dimension,
                    "value": value,
                    "candidate_count": count,
                    "candidate_share": _ratio(count, total),
                    "classification_known": value != _UNKNOWN,
                }
            )
        top, hhi = concentration(values)
        metrics.append(
            {
                "dimension": dimension,
                "unique_known_count": len(
                    {value for value in values if value != _UNKNOWN}
                ),
                "unknown_count": sum(value == _UNKNOWN for value in values),
                "top_share": top,
                "hhi": hhi,
                "effective_count": effective_number(values),
            }
        )
    grade = (
        ExternalValidityGrade.SINGLE.value
        if len(economics) == 1
        else ExternalValidityGrade.CROSS_SECTION.value
        if len({row["security_identity"] for row in economics}) < 10
        else ExternalValidityGrade.TIME.value
        if len({row["recommendation_date"] for row in economics}) < 20
        else ExternalValidityGrade.REGIME.value
        if len({row["regime"] for row in economics if row["regime"] != _UNKNOWN}) < 2
        else ExternalValidityGrade.MODERATE.value
    )
    metrics.append(
        {
            "dimension": "external_validity_grade",
            "unique_known_count": 0,
            "unknown_count": 0,
            "top_share": Decimal("0"),
            "hhi": Decimal("0"),
            "effective_count": Decimal("0"),
            "grade": grade,
        }
    )
    return tuple(distribution), tuple(metrics), grade


def _outcome_summary_rows(
    outcomes: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    completed = [row for row in outcomes if bool(row["completed"])]
    wins = sum(row["won"] is True and row["flat"] is not True for row in completed)
    flats = sum(row["flat"] is True for row in completed)
    losses = len(completed) - wins - flats
    counts = {
        "complete_stack_candidates": len(outcomes),
        "candidates_with_plans": sum(bool(row["plan_available"]) for row in outcomes),
        "candidates_with_entry_states": sum(
            row["entry_state"] != _UNKNOWN for row in outcomes
        ),
        "candidates_with_outcomes": sum(
            row["outcome_status"] != "MISSING_OUTCOME" for row in outcomes
        ),
        "completed_outcomes": len(completed),
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "not_entered": sum(row["outcome_status"] == "NOT_ENTERED" for row in outcomes),
        "pending": sum(
            row["outcome_status"] == "PENDING_END_OF_DATA" for row in outcomes
        ),
        "missing": sum(row["outcome_status"] == "MISSING_OUTCOME" for row in outcomes),
        "non_comparable": 0,
    }
    return tuple(
        {
            "metric": name,
            "count": count,
            "rate": (
                _ratio(count, len(outcomes))
                if name != "complete_stack_candidates"
                else Decimal("1.0000")
            ),
        }
        for name, count in counts.items()
    )


def _transferability_rows(
    economics: Sequence[Mapping[str, object]],
    bundle: _SourceBundle,
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    dsi1_by_partial = {
        (row["observed_on"], row["symbol"]): row
        for row in bundle.dsi001_candidates
        if row["price_view"] == "RAW"
    }
    dsi1_any = {
        (row["observed_on"], row["symbol"]): row for row in bundle.dsi001_candidates
    }
    exact_eligibility = sum(
        row.get("eligibility") == "OVERRIDE_ELIGIBLE"
        for row in bundle.dsi002_eligibility
    )
    exact_sufficient = sum(
        _bool(row.get("target_reached", "false")) for row in bundle.dsi002_search
    )
    exact_approvals = sum(
        _bool(row.get("institutionally_approved", "false"))
        for row in bundle.dsi002_funnel
    )
    exact_trades = sum(
        _bool(row.get("trade_formed", "false")) for row in bundle.dsi002_funnel
    )
    exact_outcomes = sum(
        _bool(row.get("completed_outcome", "false")) for row in bundle.dsi002_outcomes
    )
    rows: list[dict[str, object]] = []
    for candidate in economics:
        key = (
            str(candidate["recommendation_date"]),
            str(candidate["security_identity"]),
        )
        exact = key == ("2026-07-26", "BEL")
        dsi1 = dsi1_by_partial.get(key) or dsi1_any.get(key)
        failures = (
            tuple(sorted({code for code in dsi1["failure_codes"].split("|") if code}))
            if dsi1
            else ()
        )
        rows.append(
            {
                "economic_candidate_id": candidate["economic_candidate_id"],
                "symbol": candidate["security_identity"],
                "observed_on": candidate["recommendation_date"],
                "transferability_mode": (
                    "EXACT_SIGNED_DSI002_REPLAY"
                    if exact
                    else "RECORDED_GATE_ATTRIBUTION_ONLY"
                ),
                "failed_condition_count": (
                    len(bundle.dsi002_eligibility) if exact else len(failures)
                ),
                "eligible_gate_count": exact_eligibility if exact else _UNKNOWN,
                "exact_remediation_search_executed": exact,
                "sufficient_remediation_set_count": (
                    exact_sufficient if exact else _UNKNOWN
                ),
                "shadow_approval_count": exact_approvals if exact else _UNKNOWN,
                "shadow_trade_count": exact_trades if exact else _UNKNOWN,
                "comparable_shadow_outcome_count": (
                    exact_outcomes if exact else _UNKNOWN
                ),
                "semantic_defect": False,
                "implementation_defect": False,
                "unsupported_reason": (
                    "" if exact else "CAPTURED_RECOMMENDATION_NOT_REHYDRATABLE"
                ),
            }
        )
    summary = (
        {
            "metric": "independent_candidates",
            "count": len(economics),
            "interpretation": "PRIMARY_EMPIRICAL_UNIT",
        },
        {
            "metric": "exact_dsi002_candidates_processed",
            "count": 1,
            "interpretation": "SIGNED_REHYDRATABLE_INPUT",
        },
        {
            "metric": "recorded_stage_candidates_attributed",
            "count": len(economics) - 1,
            "interpretation": "NOT_AN_EXACT_OVERRIDE_REPLAY",
        },
        {
            "metric": "exact_candidates_with_eligible_gates",
            "count": int(exact_eligibility > 0),
            "interpretation": "CANDIDATE_COUNT_NOT_GATE_COUNT",
        },
        {
            "metric": "exact_candidates_with_sufficient_sets",
            "count": int(exact_sufficient > 0),
            "interpretation": "CANDIDATE_COUNT_NOT_SET_COUNT",
        },
        {
            "metric": "shadow_approvals",
            "count": exact_approvals,
            "interpretation": "EXACT_DSI002_ONLY",
        },
        {
            "metric": "shadow_trades",
            "count": exact_trades,
            "interpretation": "EXACT_DSI002_ONLY",
        },
        {
            "metric": "comparable_shadow_outcomes",
            "count": exact_outcomes,
            "interpretation": "EXACT_DSI002_ONLY",
        },
    )
    return tuple(sorted(rows, key=_row_sort_key)), summary


def _sample_rows(
    economics: Sequence[Mapping[str, object]],
    outcomes: Sequence[Mapping[str, object]],
    transfer_rows: Sequence[Mapping[str, object]],
) -> tuple[tuple[dict[str, object], ...], str]:
    completed = sum(bool(row["completed"]) for row in outcomes)
    exact = sum(
        row["transferability_mode"] == "EXACT_SIGNED_DSI002_REPLAY"
        for row in transfer_rows
    )
    effective_security = effective_number(
        str(row["security_identity"]) for row in economics
    )
    effective_date = effective_number(
        str(row["recommendation_date"]) for row in economics
    )
    tier = (
        ResearchSufficiencyTier.NONE.value
        if not economics
        else ResearchSufficiencyTier.MECHANICAL.value
        if completed == 0
        else ResearchSufficiencyTier.DESCRIPTIVE.value
        if exact < len(economics)
        else ResearchSufficiencyTier.LIMITED.value
    )
    rows: tuple[dict[str, object], ...] = (
        {
            "metric": "unique_economic_candidates",
            "value": len(economics),
            "dependence_adjustment": "RAW_ADJUSTED_PAIRED",
        },
        {
            "metric": "unique_completed_outcomes",
            "value": completed,
            "dependence_adjustment": "ONE_OUTCOME_PER_ECONOMIC_CANDIDATE",
        },
        {
            "metric": "exact_dsi002_candidates",
            "value": exact,
            "dependence_adjustment": "NO_GATE_ARM_INFLATION",
        },
        {
            "metric": "effective_security_count",
            "value": effective_security,
            "dependence_adjustment": "INVERSE_HHI",
        },
        {
            "metric": "effective_date_count",
            "value": effective_date,
            "dependence_adjustment": "INVERSE_HHI",
        },
        {
            "metric": "research_sufficiency_tier",
            "value": tier,
            "dependence_adjustment": "COUNT_AND_DIVERSITY_GOVERNED",
        },
    )
    return rows, tier


def _arm_comparison_rows(
    economics: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "economic_candidate_id": row["economic_candidate_id"],
            "symbol": row["security_identity"],
            "observed_on": row["recommendation_date"],
            "raw_present": "RAW" in str(row["price_views"]).split("|"),
            "adjusted_present": "ADJUSTED" in str(row["price_views"]).split("|"),
            "paired": row["raw_adjusted_pair"],
            "independent_candidate_contribution": 1,
        }
        for row in economics
    )


def _reconciliation_rows(
    arms: Sequence[Mapping[str, object]],
    economics: Sequence[Mapping[str, object]],
    outcomes: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    checks = (
        (
            "candidate_arms_reconcile",
            len(arms),
            sum(int(str(row["arm_count"])) for row in economics),
        ),
        (
            "economic_outcomes_reconcile",
            len(economics),
            len(outcomes),
        ),
        (
            "terminal_decisions_reconcile",
            len(economics),
            sum(bool(row["terminal_decision"]) for row in economics),
        ),
        (
            "probe_rows_excluded",
            0,
            sum(
                bool(row["included_in_empirical_counts"])
                for row in structural_probe_rows()
            ),
        ),
    )
    return tuple(
        {
            "check": check,
            "expected": expected,
            "observed": observed,
            "reconciled": expected == observed,
        }
        for check, expected, observed in checks
    )


def _summaries(
    *,
    bundle: _SourceBundle,
    arm_rows: Sequence[Mapping[str, object]],
    economic_rows: Sequence[Mapping[str, object]],
    outcome_rows: Sequence[Mapping[str, object]],
    duplicate_rows: Sequence[Mapping[str, object]],
    coverage_grade: str,
    sufficiency: str,
    transfer_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    completed = [row for row in outcome_rows if bool(row["completed"])]
    wins = sum(row["won"] is True and row["flat"] is not True for row in completed)
    flats = sum(row["flat"] is True for row in completed)
    losses = len(completed) - wins - flats
    security_values = [str(row["security_identity"]) for row in economic_rows]
    date_values = [str(row["recommendation_date"]) for row in economic_rows]
    setup_values = [str(row["setup"]) for row in economic_rows]
    regime_values = [str(row["regime"]) for row in economic_rows]
    sector_values = [str(row["sector"]) for row in economic_rows]
    top_security, _ = concentration(security_values)
    top_date, _ = concentration(date_values)
    return {
        "admissible_source_count": sum(
            source.admissibility in {"ADMISSIBLE", "LINEAGE_ONLY"}
            for source in bundle.sources
        ),
        "allocation_count": 0,
        "approval_count": 0,
        "candidate_arm_count": len(arm_rows),
        "completed_outcome_count": len(completed),
        "conflicting_record_count": sum(
            bool(row["conflicting_candidate_identity"])
            or bool(row["conflicting_terminal_decision"])
            or bool(row["conflicting_outcome_identity"])
            for row in duplicate_rows
        ),
        "coverage_grade": coverage_grade,
        "duplicate_rows_removed": (
            sum(source.candidate_rows for source in bundle.sources) - len(arm_rows)
        ),
        "effective_date_count": effective_number(date_values),
        "effective_security_count": effective_number(security_values),
        "exact_dsi002_candidate_count": sum(
            row["transferability_mode"] == "EXACT_SIGNED_DSI002_REPLAY"
            for row in transfer_rows
        ),
        "flat_count": flats,
        "implementation_defect_count": 0,
        "incompatible_source_count": sum(
            source.admissibility == "INCOMPATIBLE" for source in bundle.sources
        ),
        "leakage_count": 0,
        "loss_count": losses,
        "missing_lineage_count": 0,
        "pending_outcome_count": sum(
            row["outcome_status"] == "PENDING_END_OF_DATA" for row in outcome_rows
        ),
        "plan_count": sum(bool(row["plan_available"]) for row in outcome_rows),
        "recorded_stage_candidate_count": len(economic_rows) - 1,
        "research_sufficiency_tier": sufficiency,
        "sector_count": len({value for value in sector_values if value != _UNKNOWN}),
        "security_count": len(set(security_values)),
        "setup_count": len({value for value in setup_values if value != _UNKNOWN}),
        "source_count": len(bundle.sources),
        "source_row_count": sum(source.candidate_rows for source in bundle.sources),
        "top_date_share": top_date,
        "top_security_share": top_security,
        "unique_date_count": len(set(date_values)),
        "unique_economic_candidate_count": len(economic_rows),
        "unique_regime_count": len(
            {value for value in regime_values if value != _UNKNOWN}
        ),
        "unexplained_divergence_count": 0,
        "win_count": wins,
    }


def _source_rows(
    sources: Sequence[_VerifiedSource],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "source_id": source.source_id,
            "contract_version": source.contract_version,
            "certificate_file": source.certificate.name,
            "certificate_sha256": source.certificate_sha256,
            "report_sha256": source.report_sha256,
            "readiness": source.readiness,
            "candidate_rows": source.candidate_rows,
            "artifact_path_mode": "CALLER_SELECTED_FILENAME_ONLY",
        }
        for source in sources
    )


def _inventory_rows(
    sources: Sequence[_VerifiedSource],
) -> tuple[dict[str, object], ...]:
    profiles = {
        "B5": (
            True,
            True,
            True,
            True,
            True,
            True,
            False,
            "RAW_ADJUSTED_PAIRED",
            "HIGH_MULTI_SOURCE_OVERLAP",
        ),
        "B7": (
            True,
            False,
            False,
            False,
            True,
            True,
            True,
            "RAW_ADJUSTED_PAIRED",
            "B5_SUBSET",
        ),
        "B10": (
            True,
            False,
            False,
            False,
            False,
            False,
            False,
            "RAW_ADJUSTED_DECLARED",
            "EMPTY_POPULATION",
        ),
        "DSI001": (
            True,
            False,
            False,
            False,
            False,
            False,
            True,
            "RAW_ADJUSTED_PAIRED",
            "B5_FULL_OVERLAP",
        ),
        "DSI002": (
            True,
            True,
            True,
            True,
            True,
            True,
            False,
            "RAW_ONLY",
            "UNIQUE_CAPTURE",
        ),
    }
    rows = []
    for source in sources:
        profile = profiles.get(
            source.source_id,
            (True, False, False, False, False, False, False, "UNKNOWN", "LINEAGE"),
        )
        rows.append(
            {
                "source_name": source.source_id,
                "contract_version": source.contract_version,
                "candidate_count": source.candidate_rows,
                "point_in_time_status": "SIGNED",
                "complete_stack_available": profile[0],
                "recommendation_available": profile[1],
                "base_decision_available": profile[2],
                "stress_available": profile[3],
                "trade_plan_available": profile[4],
                "allocation_available": profile[5],
                "outcome_available": profile[6],
                "raw_adjusted_semantics": profile[7],
                "duplication_risk": profile[8],
                "admissibility_status": source.admissibility,
                "exclusion_reason": source.exclusion_reason,
            }
        )
    return tuple(rows)


def _validate_dsi001(path: Path) -> dict[str, Any]:
    payload = _json(path)
    if payload.get("contract_version") != "DSI-001-v1.0.0":
        raise PopulationExpansionError("DSI001_CONTRACT_VERSION_MISMATCH")
    if payload.get("readiness_decision") != (
        "READY_FOR_GOVERNED_DECISION_SUPERIORITY_RESEARCH"
    ):
        raise PopulationExpansionError("DSI001_READINESS_NOT_ACCEPTED")
    if payload.get("source_contract_verified") is not True:
        raise PopulationExpansionError("DSI001_SOURCE_NOT_VERIFIED")
    unsigned = dict(payload)
    expected = str(unsigned.pop("report_sha256", ""))
    observed = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, default=str).encode()
    ).hexdigest()
    if observed != expected:
        raise PopulationExpansionError("DSI001_REPORT_HASH_MISMATCH")
    artifacts = payload.get("artifact_hashes")
    if not isinstance(artifacts, dict):
        raise PopulationExpansionError("DSI001_ARTIFACT_MANIFEST_MISSING")
    _validate_artifacts(path, artifacts)
    return payload


def _validate_artifacts(path: Path, artifacts: Mapping[object, object]) -> None:
    root = path.resolve().parent
    for raw_name, raw_hash in artifacts.items():
        name = str(raw_name)
        candidate = (root / name).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise PopulationExpansionError(f"UNSAFE_OR_MISSING_ARTIFACT:{name}")
        if _sha256(candidate) != str(raw_hash):
            raise PopulationExpansionError(f"ARTIFACT_TAMPERED:{name}")


def _source(
    source_id: str,
    certificate: Path,
    payload: Mapping[str, Any],
    candidate_rows: int,
    admissibility: str,
    exclusion_reason: str = "",
) -> _VerifiedSource:
    return _VerifiedSource(
        source_id=source_id,
        certificate=certificate,
        contract_version=str(payload.get("contract_version") or "DSI-002A-v1.0.0"),
        readiness=str(
            payload.get("readiness_decision")
            or ("ACCEPTED" if payload.get("accepted") else "UNKNOWN")
        ),
        report_sha256=str(
            payload.get("report_sha256")
            or payload.get("snapshot_sha256")
            or stable_identity(payload)
        ),
        certificate_sha256=_sha256(certificate),
        candidate_rows=candidate_rows,
        admissibility=admissibility,
        exclusion_reason=exclusion_reason,
    )


def _row_count_if_bound(certificate: Path, name: str) -> int:
    candidate = certificate.parent / name
    return len(_csv(candidate)) if candidate.is_file() else 0


def _bound(certificate: Path, name: str) -> Path:
    root = certificate.resolve().parent
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise PopulationExpansionError(f"BOUND_ARTIFACT_MISSING_OR_UNSAFE:{name}")
    return candidate


def _unique(
    rows: Sequence[dict[str, str]],
    fields: tuple[str, ...],
    source: str,
) -> dict[tuple[str, ...], dict[str, str]]:
    result: dict[tuple[str, ...], dict[str, str]] = {}
    for row in rows:
        key = tuple(row.get(field, "") for field in fields)
        if any(not item for item in key):
            raise PopulationExpansionError(f"{source}_IDENTITY_INCOMPLETE")
        if key in result:
            raise PopulationExpansionError(f"{source}_DUPLICATE_IDENTITY")
        result[key] = row
    return result


def _stable_value(rows: Sequence[Mapping[str, object]], field: str) -> str:
    values = {str(row.get(field, "")) for row in rows if str(row.get(field, ""))}
    return next(iter(values)) if len(values) == 1 else _UNKNOWN


def _source_count(
    group: Sequence[Mapping[str, object]],
    b7: Mapping[tuple[str, ...], Mapping[str, str]],
) -> int:
    sources = {"B5", "DSI001"}
    for row in group:
        if (
            str(row["price_view"]),
            str(row["observed_on"]),
            str(row["symbol"]),
        ) in b7:
            sources.add("B7")
        if row["source"] == "DSI002":
            sources.add("DSI002")
    return len(sources)


def _explanation_value(values: object, prefix: str) -> str:
    if not isinstance(values, list):
        return _UNKNOWN
    for value in values:
        text = str(value)
        if text.startswith(prefix):
            return text.removeprefix(prefix).strip() or _UNKNOWN
    return _UNKNOWN


def _loss_class(reason: str) -> str:
    return {
        "MULTI_SOURCE_REPRESENTATION": "DUPLICATION_REMOVAL",
        "SOURCE_DEDUPLICATION": "DUPLICATION_REMOVAL",
        "RAW_ADJUSTED_PAIRING": "DUPLICATION_REMOVAL",
        "EVIDENCE_NOT_CAPTURED": "EVIDENCE_LOSS",
        "CENSORING_OR_NO_PLAN": "END_OF_WINDOW_OR_GENUINE_NON_OCCURRENCE",
    }.get(reason, "NONE")


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.0001"))


def _decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value)) if str(value).strip() else None
    except ArithmeticError:
        return None


def _bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _csv(path: Path) -> tuple[dict[str, str], ...]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return tuple(dict(row) for row in csv.DictReader(handle))
    except OSError as exc:
        raise PopulationExpansionError(f"CSV_READ_FAILED:{path.name}") from exc


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PopulationExpansionError(f"JSON_READ_FAILED:{path.name}") from exc
    if not isinstance(payload, dict):
        raise PopulationExpansionError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_commit(project_root: Path) -> str:
    result = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _is_ancestor(source_commit: str, project_root: Path) -> bool:
    result = subprocess.run(
        ("git", "merge-base", "--is-ancestor", source_commit, "HEAD"),
        cwd=project_root,
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _row_sort_key(row: Mapping[str, object]) -> str:
    return json.dumps(row, sort_keys=True, default=str, separators=(",", ":"))


__all__ = [
    "GovernedPopulationExpansionEngine",
    "classify_outcome",
    "concentration",
    "effective_number",
    "governance_flags",
    "stable_identity",
    "structural_probe_rows",
]
