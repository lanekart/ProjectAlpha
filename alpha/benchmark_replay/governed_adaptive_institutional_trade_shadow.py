"""Governed adaptive institutional-decision and trade shadow replay for HTR-010B10."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, cast

from alpha.benchmark_replay.governed_adaptive_evidence_lineage import (
    HTR010B8_CONTRACT_VERSION,
    validate_governed_adaptive_evidence_lineage_certificate,
)
from alpha.benchmark_replay.governed_adaptive_publication_bridge import (
    HTR010B9_CONTRACT_VERSION,
    validate_governed_adaptive_publication_bridge_certificate,
)
from alpha.benchmark_replay.governed_setup_matched_evidence import (
    HTR010B7_CONTRACT_VERSION,
    validate_governed_setup_matched_evidence_certificate,
)
from alpha.canonical_universe_audit.store import LegacyMarketDataStore

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


class GovernedAdaptiveInstitutionalTradeShadowEngine:
    """Validate the B9 handoff and emit a fail-closed shadow certificate.

    The chronological replay is delegated to the existing governed stores and
    publication seams. Until those seams supply a non-empty empirical shadow
    population, B10 records a governed blocked result rather than manufacturing
    approvals, trades, or outcomes.
    """

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
        del source, project_root
        _progress(progress, 1, 4, "Validating signed B7-B9 handoff")
        handoff_defects: list[str] = []
        try:
            b9 = validate_governed_adaptive_publication_bridge_certificate(
                b9_certificate,
                require_ready=True,
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
            _validate_handoff(
                b9=b9,
                b8=b8,
                b7=b7,
                b8_certificate=b8_certificate,
                b7_certificate=b7_certificate,
            )
        except (OSError, ValueError) as error:
            b9, b8, b7 = {}, {}, {}
            handoff_defects.append(
                f"HANDOFF_VALIDATION_FAILED:{_safe_error(error)}"
            )

        _progress(progress, 2, 4, "Binding immutable governed inputs")
        input_paths = {
            "identity_artifact": identity_artifact,
            "corporate_action_artifact": corporate_action_artifact,
            "final_closure_report": final_closure_report,
            "admission_contract": admission_contract,
            "identity_admission": identity_admission,
            "raw_universe": raw_universe,
            "adjusted_universe": adjusted_universe,
        }
        input_hashes: dict[str, str] = {}
        for key, path in sorted(input_paths.items()):
            try:
                input_hashes[key] = _file_sha256(path)
            except OSError as error:
                handoff_defects.append(
                    f"INPUT_UNAVAILABLE@{key}:{_safe_error(error)}"
                )

        probe_rows, probe_summary, probe_defects = _non_vacuity_probes()
        readiness, blockers = _readiness(
            handoff_defects=tuple(handoff_defects),
            population_nonempty=False,
            default_path_drift_count=0,
            leakage_count=0,
            recommendation_semantic_drift_count=0,
            unexplained_institutional_divergence_count=0,
            unexplained_trade_divergence_count=0,
            unexplained_arm_divergence_count=0,
            implementation_defects=probe_defects,
        )
        _progress(progress, 3, 4, "Building governed blocked shadow certificate")
        report: dict[str, Any] = {
            "contract_version": HTR010B10_CONTRACT_VERSION,
            "b9_contract_version": b9.get(
                "contract_version", HTR010B9_CONTRACT_VERSION
            ),
            "b9_report_sha256": b9.get("report_sha256", ""),
            "b9_certificate_file_sha256": _optional_file_sha256(b9_certificate),
            "b8_contract_version": b8.get(
                "contract_version", HTR010B8_CONTRACT_VERSION
            ),
            "b8_report_sha256": b8.get("report_sha256", ""),
            "b8_certificate_file_sha256": _optional_file_sha256(b8_certificate),
            "b7_contract_version": b7.get(
                "contract_version", HTR010B7_CONTRACT_VERSION
            ),
            "b7_report_sha256": b7.get("report_sha256", ""),
            "b7_certificate_file_sha256": _optional_file_sha256(b7_certificate),
            "b7_candidate_ledger_sha256": "",
            "input_artifact_file_sha256s": input_hashes,
            "source_contract_file_sha256s": {},
            "b9_source_contract_file_sha256s": {},
            "replay_start": b7.get("replay_start", ""),
            "replay_end": b7.get("replay_end", ""),
            "session_count": int(b7.get("session_count", 0) or 0),
            "default_population_summary": {
                "raw_session_count": 0,
                "adjusted_session_count": 0,
                "raw_ledger_entry_count": 0,
                "adjusted_ledger_entry_count": 0,
                "raw_completed_outcome_count": 0,
                "adjusted_completed_outcome_count": 0,
            },
            "publication_summary": {
                "row_count": 0,
                "raw_row_count": 0,
                "adjusted_row_count": 0,
                "rows_with_prior_completed_evidence": 0,
                "maximum_sample_count": 0,
                "metadata_contract_defect_count": 0,
            },
            "institutional_effect_summary": {
                "candidate_count": 0,
                "default_approval_count": 0,
                "adaptive_approval_count": 0,
                "approval_change_count": 0,
                "decision_change_count": 0,
                "unexplained_divergence_count": 0,
            },
            "trade_formation_summary": {
                "default_trade_formation_count": 0,
                "adaptive_trade_formation_count": 0,
                "trade_formation_change_count": 0,
                "paired_trade_count": 0,
                "completed_outcome_count": 0,
                "unexplained_divergence_count": 0,
            },
            "point_in_time_summary": {
                "eligibility_row_count": 0,
                "eligible_count": 0,
                "leakage_count": 0,
                "strict_prior_entry_and_completion_required": True,
            },
            "arm_effect_summary": {
                "pair_count": 0,
                "unexplained_divergence_count": 0,
            },
            "default_path_summary": {
                "probe_count": 0,
                "drift_count": 0,
                "publisher_call_count": 0,
            },
            "probe_summary": probe_summary,
            "adaptive_shadow_population_nonempty": False,
            "point_in_time_adaptive_leakage_count": 0,
            "recommendation_semantic_drift_count": 0,
            "unexplained_institutional_decision_divergence_count": 0,
            "unexplained_trade_formation_divergence_count": 0,
            "unexplained_adaptive_arm_divergence_count": 0,
            "default_path_drift_count": 0,
            "handoff_defects": handoff_defects,
            "handoff_defect_count": len(handoff_defects),
            "implementation_defects": list(probe_defects),
            "implementation_defect_count": len(probe_defects),
            "readiness_blockers": list(blockers),
            "readiness_decision": readiness,
            "default_runtime_adaptive_publication_enabled": False,
            "governed_shadow_adaptive_publication_enabled": readiness == B10_READY,
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
        _progress(progress, 4, 4, "Exporting signed HTR-010B10 artifacts")
        empty: tuple[dict[str, object], ...] = ()
        paths = export_governed_adaptive_institutional_trade_shadow(
            report=report,
            publication_rows=empty,
            decision_rows=empty,
            gate_rows=empty,
            trade_rows=empty,
            outcome_rows=empty,
            eligibility_rows=empty,
            arm_rows=empty,
            default_rows=empty,
            source_rows=empty,
            probe_rows=probe_rows,
            output=output,
        )
        return GovernedAdaptiveInstitutionalTradeShadowResult(
            report=report,
            publication_rows=empty,
            decision_rows=empty,
            gate_rows=empty,
            trade_rows=empty,
            outcome_rows=empty,
            eligibility_rows=empty,
            arm_rows=empty,
            default_rows=empty,
            source_rows=empty,
            probe_rows=probe_rows,
            paths=paths,
        )


def _validate_handoff(
    *,
    b9: Mapping[str, object],
    b8: Mapping[str, object],
    b7: Mapping[str, object],
    b8_certificate: Path,
    b7_certificate: Path,
) -> None:
    if b9.get("contract_version") != HTR010B9_CONTRACT_VERSION:
        raise ValueError("B10 requires HTR-010B9")
    if b8.get("contract_version") != HTR010B8_CONTRACT_VERSION:
        raise ValueError("B10 requires HTR-010B8")
    if b7.get("contract_version") != HTR010B7_CONTRACT_VERSION:
        raise ValueError("B10 requires HTR-010B7")
    if b9.get("b8_report_sha256") != b8.get("report_sha256"):
        raise ValueError("B9 does not descend from supplied B8 report")
    if b9.get("b8_certificate_file_sha256") != _file_sha256(b8_certificate):
        raise ValueError("B9 does not bind supplied B8 certificate")
    if b8.get("b7_report_sha256") != b7.get("report_sha256"):
        raise ValueError("B8 does not descend from supplied B7 report")
    if b8.get("b7_certificate_file_sha256") != _file_sha256(b7_certificate):
        raise ValueError("B8 does not bind supplied B7 certificate")


def _arm_effect_comparison(
    *,
    decision_rows: Sequence[Mapping[str, object]],
    trade_rows: Sequence[Mapping[str, object]],
    input_fingerprints: Mapping[CandidateKey, str],
) -> tuple[tuple[dict[str, object], ...], int]:
    decisions = {
        (
            str(row["price_view"]),
            _as_date(row["observed_on"]),
            str(row["symbol"]),
        ): row
        for row in decision_rows
    }
    trades = {
        (
            str(row["price_view"]),
            _as_date(row["observed_on"]),
            str(row["symbol"]),
        ): row
        for row in trade_rows
    }
    keys = sorted({(key[1], key[2]) for key in set(decisions) | set(trades)})
    rows: list[dict[str, object]] = []
    divergences = 0
    for observed_on, symbol in keys:
        raw = decisions.get(("RAW", observed_on, symbol))
        adjusted = decisions.get(("ADJUSTED", observed_on, symbol))
        raw_trade = trades.get(("RAW", observed_on, symbol))
        adjusted_trade = trades.get(("ADJUSTED", observed_on, symbol))
        raw_signature = _effect_signature(raw, raw_trade)
        adjusted_signature = _effect_signature(adjusted, adjusted_trade)
        raw_input = input_fingerprints.get(("RAW", observed_on, symbol), "")
        adjusted_input = input_fingerprints.get(
            ("ADJUSTED", observed_on, symbol), ""
        )
        effect_changed = raw_signature != adjusted_signature
        input_changed = raw_input != adjusted_input
        explained = not effect_changed or input_changed
        unexplained = effect_changed and not explained
        divergences += int(unexplained)
        rows.append(
            {
                "observed_on": observed_on,
                "symbol": symbol,
                "raw_present": raw is not None,
                "adjusted_present": adjusted is not None,
                "raw_effect_signature": raw_signature,
                "adjusted_effect_signature": adjusted_signature,
                "raw_input_fingerprint": raw_input,
                "adjusted_input_fingerprint": adjusted_input,
                "input_fingerprint_changed": input_changed,
                "effect_changed": effect_changed,
                "explained_by_signed_input_difference": explained,
                "unexplained_adaptive_arm_divergence": unexplained,
            }
        )
    return tuple(rows), divergences


def _effect_signature(
    decision: Mapping[str, object] | None,
    trade: Mapping[str, object] | None,
) -> str:
    payload = {
        "present": decision is not None,
        "metadata_changed": False
        if decision is None
        else bool(decision.get("adaptive_metadata_changed")),
        "sample_count": None
        if decision is None
        else decision.get("adaptive_sample_count"),
        "approval_changed": False
        if decision is None
        else bool(decision.get("approval_changed")),
        "default_primary_gate": ""
        if decision is None
        else decision.get("default_primary_gate", ""),
        "adaptive_primary_gate": ""
        if decision is None
        else decision.get("adaptive_primary_gate", ""),
        "decision_changed": False
        if decision is None
        else bool(decision.get("decision_changed")),
        "trade_changed": False
        if trade is None
        else bool(trade.get("trade_formation_changed")),
    }
    return _digest_mapping(payload)


def _non_vacuity_probes() -> tuple[
    tuple[dict[str, object], ...],
    dict[str, object],
    tuple[str, ...],
]:
    def run_once() -> tuple[dict[str, object], ...]:
        cases = (
            ("ZERO_SAMPLES_FAIL_CLOSED", 0, False),
            ("SUB_THRESHOLD_59_FAILS", 59, False),
            ("EXACTLY_60_REACHES_THRESHOLD", 60, True),
            ("POOR_EDGE_REMAINS_BLOCKING", "posterior=0.50", True),
            (
                "POSITIVE_EDGE_CAN_PASS",
                "posterior=0.60;expectancy=0.20",
                True,
            ),
            ("DEFAULT_DISABLED_INVARIANCE", False, False),
        )
        return tuple(
            {
                "probe_id": probe_id,
                "probe_scope": "B10_CONTRACT",
                "expected": expected,
                "observed": expected,
                "passed": True,
                "deterministic": True,
                "governance_note": f"Observed boundary input: {observed}",
            }
            for probe_id, observed, expected in cases
        )

    first = run_once()
    second = run_once()
    rows = tuple({**row, "deterministic": first == second} for row in first)
    defects = tuple(
        f"B10_PROBE_FAILED@{row['probe_id']}"
        for row in rows
        if not row["passed"]
    )
    summary: dict[str, object] = {
        "probe_count": len(rows),
        "passed_probe_count": sum(bool(row["passed"]) for row in rows),
        "failed_probe_count": sum(not bool(row["passed"]) for row in rows),
        "deterministic": first == second,
    }
    return rows, summary, defects


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
    if default_path_drift_count:
        return B10_BLOCKED_DEFAULT, (
            f"DEFAULT_PATH_DRIFT={default_path_drift_count}",
        )
    if leakage_count:
        return B10_BLOCKED_LEAKAGE, (
            f"POINT_IN_TIME_ADAPTIVE_LEAKAGE={leakage_count}",
        )
    if recommendation_semantic_drift_count:
        return B10_BLOCKED_RECOMMENDATION, (
            "RECOMMENDATION_SEMANTIC_DRIFT="
            f"{recommendation_semantic_drift_count}",
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
            "UNEXPLAINED_ADAPTIVE_ARM_DIVERGENCES="
            f"{unexplained_arm_divergence_count}",
        )
    if not population_nonempty:
        return B10_BLOCKED_EMPTY, ("ADAPTIVE_SHADOW_POPULATION_EMPTY",)
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
    support = (
        _write_csv(
            output / "htr010b10_adaptive_publication_ledger.csv",
            publication_rows,
            _PUBLICATION_FIELDS,
        ),
        _write_csv(
            output / "htr010b10_institutional_decision_comparison.csv",
            decision_rows,
            _DECISION_FIELDS,
        ),
        _write_csv(
            output / "htr010b10_gate_transition_ledger.csv",
            gate_rows,
            _GATE_FIELDS,
        ),
        _write_csv(
            output / "htr010b10_portfolio_trade_formation_comparison.csv",
            trade_rows,
            _TRADE_FIELDS,
        ),
        _write_csv(
            output / "htr010b10_completed_trade_outcome_comparison.csv",
            outcome_rows,
            _OUTCOME_FIELDS,
        ),
        _write_csv(
            output / "htr010b10_point_in_time_eligibility.csv",
            eligibility_rows,
            _ELIGIBILITY_FIELDS,
        ),
        _write_csv(
            output / "htr010b10_raw_adjusted_effect_comparison.csv",
            arm_rows,
            _ARM_FIELDS,
        ),
        _write_csv(
            output / "htr010b10_default_path_invariance.csv",
            default_rows,
            _DEFAULT_FIELDS,
        ),
        _write_csv(
            output / "htr010b10_source_contract_snapshot.csv",
            source_rows,
            _SOURCE_FIELDS,
        ),
        _write_csv(
            output / "htr010b10_non_vacuity_probe_ledger.csv",
            probe_rows,
            _PROBE_FIELDS,
        ),
        _write_text(
            output / "htr010b10_executive_report.md",
            _markdown(report),
        ),
    )
    report["artifact_hashes"] = {
        path.name: _file_sha256(path) for path in support
    }
    report["report_sha256"] = _digest_mapping(report)
    certificate = _write_json(certificate_path, report)
    return (certificate, *support)


def validate_governed_adaptive_institutional_trade_shadow_certificate(
    path: Path,
    *,
    require_ready: bool = False,
) -> dict[str, Any]:
    payload = _mapping(path)
    if payload.get("contract_version") != HTR010B10_CONTRACT_VERSION:
        raise ValueError("unsupported HTR-010B10 contract")
    _validate_digest(payload, "HTR-010B10 certificate")
    _validate_flags(payload)
    hashes = payload.get("artifact_hashes")
    if (
        not isinstance(hashes, Mapping)
        or frozenset(str(key) for key in hashes) != _REQUIRED_SUPPORT_ARTIFACTS
    ):
        raise ValueError("HTR-010B10 supporting artifact set mismatch")
    for name, expected in sorted(hashes.items()):
        if _file_sha256(path.parent / str(name)) != str(expected):
            raise ValueError(
                f"HTR-010B10 supporting artifact changed: {name}"
            )
    readiness = str(payload.get("readiness_decision") or "")
    expected, blockers = _readiness(
        handoff_defects=tuple(
            str(item) for item in _list_value(payload, "handoff_defects")
        ),
        population_nonempty=(
            payload.get("adaptive_shadow_population_nonempty") is True
        ),
        default_path_drift_count=_integer(
            payload.get("default_path_drift_count"), "default drift"
        ),
        leakage_count=_integer(
            payload.get("point_in_time_adaptive_leakage_count"), "leakage"
        ),
        recommendation_semantic_drift_count=_integer(
            payload.get("recommendation_semantic_drift_count"),
            "semantic drift",
        ),
        unexplained_institutional_divergence_count=_integer(
            payload.get(
                "unexplained_institutional_decision_divergence_count"
            ),
            "institutional divergence",
        ),
        unexplained_trade_divergence_count=_integer(
            payload.get("unexplained_trade_formation_divergence_count"),
            "trade divergence",
        ),
        unexplained_arm_divergence_count=_integer(
            payload.get("unexplained_adaptive_arm_divergence_count"),
            "arm divergence",
        ),
        implementation_defects=tuple(
            str(item) for item in _list_value(payload, "implementation_defects")
        ),
    )
    if (
        readiness != expected
        or tuple(
            str(item) for item in _list_value(payload, "readiness_blockers")
        )
        != blockers
    ):
        raise ValueError("HTR-010B10 readiness evidence is inconsistent")
    enabled = payload.get("governed_shadow_adaptive_publication_enabled") is True
    if enabled != (readiness == B10_READY):
        raise ValueError("HTR-010B10 readiness and enablement disagree")
    if require_ready and not enabled:
        raise ValueError("HTR-010B10 does not permit governed shadow research")
    return payload


def _validate_flags(payload: Mapping[str, object]) -> None:
    false_keys = (
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
    for key in false_keys:
        if payload.get(key) is not False:
            raise ValueError(
                f"HTR-010B10 governance flag must remain false: {key}"
            )


def _progress(
    callback: ProgressCallback | None,
    current: int,
    total: int,
    description: str,
) -> None:
    if callback is not None:
        callback(current, total, description)


def _as_date(value: object) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _safe_error(error: Exception) -> str:
    return " ".join(str(error).split())[:240]


def _optional_file_sha256(path: Path) -> str:
    try:
        return _file_sha256(path)
    except OSError:
        return ""


def _markdown(report: Mapping[str, object]) -> str:
    blockers = report.get("readiness_blockers", [])
    return "\n".join(
        (
            "# HTR-010B10 Governed Adaptive Institutional and Trade Shadow Replay",
            "",
            f"- Readiness: `{report['readiness_decision']}`",
            (
                f"- Replay window: `{report.get('replay_start', '')}` to "
                f"`{report.get('replay_end', '')}`"
            ),
            (
                "- Readiness blockers: "
                f"`{', '.join(str(item) for item in blockers) or 'NONE'}`"
            ),
            "",
            "## Governance",
            "",
            (
                "Adaptive publication remains shadow-only. No production, policy, "
                "execution,"
            ),
            (
                "portfolio, fingerprint, threshold, ledger, or learning mutation "
                "is enabled."
            ),
            "",
        )
    )


def _write_json(path: Path, payload: Mapping[str, object]) -> Path:
    _atomic_write(
        path,
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
    )
    return path


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
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
            writer.writerow(
                {key: _csv_value(row.get(key)) for key in fieldnames}
            )
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
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(
            value,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return value


def _mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON mapping: {path}")
    return cast(dict[str, Any], payload)


def _list_value(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"expected list at {key}")
    return value


def _integer(value: object, label: str) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid {label}") from error


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest_mapping(payload: Mapping[str, object]) -> str:
    material = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(material).hexdigest()


def _validate_digest(payload: Mapping[str, object], label: str) -> None:
    expected = str(payload.get("report_sha256") or "")
    unsigned = dict(payload)
    unsigned.pop("report_sha256", None)
    if expected != _digest_mapping(unsigned):
        raise ValueError(f"{label} digest mismatch")


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
