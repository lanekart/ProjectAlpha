"""Governed trade-formation and economic non-vacuity certification for HTR-010B4."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, cast

from alpha.benchmark_replay.governed_adjusted import HTR010B2_CONTRACT_VERSION
from alpha.benchmark_replay.governed_adjusted_stability import (
    B3_READY,
    HTR010B3_ACTIVATION_CONTRACT_VERSION,
    HTR010B3_CONTRACT_VERSION,
    validate_governed_adjusted_research_activation,
)

HTR010B4_CONTRACT_VERSION = "HTR-010B4-v1.0.0"

B4_READY = "READY_FOR_GOVERNED_ADJUSTED_TRADE_RESEARCH"
B4_BLOCKED_ZERO = "BLOCKED_BY_ZERO_TRADE_POPULATION"
B4_BLOCKED_INSUFFICIENT = "BLOCKED_BY_INSUFFICIENT_COMPLETED_TRADES"
B4_BLOCKED_DEFECT = "BLOCKED_BY_FUNNEL_IMPLEMENTATION_DEFECT"
B4_BLOCKED_DIVERGENCE = "BLOCKED_BY_UNEXPLAINED_TRADE_DIVERGENCE"

MINIMUM_COMPLETED_PAIRED_TRADES = 20
MINIMUM_TRADE_WINDOWS = 2
RESEARCH_SCOPE = "GOVERNED_TRADE_FORMATION_RESEARCH_ONLY"

ProgressCallback = Callable[[int, int, str], None]

_APPROVABLE_SIGNALS = frozenset({"BUY", "STRONG_BUY"})
_EXPECTED_BENCHMARK_ARTIFACTS = frozenset(
    {
        "approval_statistics.csv",
        "candidate_statistics.csv",
        "capital_curve.csv",
        "decision_eligibility.csv",
        "portfolio_statistics.csv",
        "position_history.csv",
        "top_rejection_reasons.csv",
        "trade_log.csv",
    }
)

_FUNNEL_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "action_cohort",
    "action_types",
    "final_signal",
    "approvable_signal",
    "institutional_approved",
    "opportunity_score",
    "primary_reason_code",
    "rejection_category",
    "runtime_status",
    "trade_executed",
    "trade_id",
    "stage_reached",
    "terminal_gate",
    "gate_category",
    "gate_explanation",
    "unexplained_terminal_gate",
)
_GATE_FIELDS = (
    "price_view",
    "cohort",
    "terminal_gate",
    "gate_category",
    "candidate_count",
    "candidate_percent",
)
_ENTRY_FIELDS = (
    "observed_on",
    "symbol",
    "action_cohort",
    "action_types",
    "raw_present",
    "adjusted_present",
    "raw_signal",
    "adjusted_signal",
    "signal_changed",
    "raw_approved",
    "adjusted_approved",
    "approval_changed",
    "raw_terminal_gate",
    "adjusted_terminal_gate",
    "terminal_gate_changed",
    "raw_trade_executed",
    "adjusted_trade_executed",
    "raw_score",
    "adjusted_score",
    "score_delta",
    "explained_gate_difference",
)
_TRADE_FIELDS = (
    "decision_date",
    "symbol",
    "action_cohort",
    "action_types",
    "raw_present",
    "adjusted_present",
    "paired",
    "raw_trade_id",
    "adjusted_trade_id",
    "raw_entry_date",
    "adjusted_entry_date",
    "raw_exit_date",
    "adjusted_exit_date",
    "raw_net_return_percent",
    "adjusted_net_return_percent",
    "net_return_delta",
    "raw_net_profit_loss",
    "adjusted_net_profit_loss",
    "net_profit_loss_delta",
    "raw_transaction_cost",
    "adjusted_transaction_cost",
    "raw_slippage_cost",
    "adjusted_slippage_cost",
    "raw_exit_reason",
    "adjusted_exit_reason",
    "exit_reason_changed",
    "explained_presence_difference",
    "unexplained_trade_divergence",
)
_ECONOMIC_FIELDS = (
    "scope",
    "start_date",
    "end_date",
    "raw_trade_count",
    "adjusted_trade_count",
    "paired_trade_count",
    "raw_only_trade_count",
    "adjusted_only_trade_count",
    "raw_net_profit_loss",
    "adjusted_net_profit_loss",
    "net_profit_loss_delta",
    "raw_mean_net_return_percent",
    "adjusted_mean_net_return_percent",
    "mean_net_return_delta",
    "raw_transaction_cost",
    "adjusted_transaction_cost",
    "transaction_cost_delta",
    "raw_slippage_cost",
    "adjusted_slippage_cost",
    "slippage_cost_delta",
    "raw_portfolio_return_percent",
    "adjusted_portfolio_return_percent",
    "portfolio_return_delta",
    "raw_maximum_drawdown_percent",
    "adjusted_maximum_drawdown_percent",
)
_COHORT_FIELDS = (
    "cohort",
    "paired_decisions",
    "approval_flips",
    "signal_changes",
    "terminal_gate_changes",
    "raw_trade_count",
    "adjusted_trade_count",
    "paired_trade_count",
    "raw_only_trade_count",
    "adjusted_only_trade_count",
    "raw_net_profit_loss",
    "adjusted_net_profit_loss",
    "net_profit_loss_delta",
)


@dataclass(frozen=True, slots=True)
class BenchmarkTradeBundle:
    """Verified CABR artifacts required for trade-formation certification."""

    root: Path
    manifest: dict[str, Any]
    manifest_sha256: str
    candidate_rows: tuple[dict[str, str], ...]
    approval_rows: tuple[dict[str, str], ...]
    trade_rows: tuple[dict[str, str], ...]
    position_rows: tuple[dict[str, str], ...]
    capital_rows: tuple[dict[str, str], ...]
    portfolio_rows: tuple[dict[str, str], ...]
    eligibility_rows: tuple[dict[str, str], ...]
    rejection_rows: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class DecisionEvidence:
    """One CABR decision record used to reconstruct the frozen funnel."""

    observed_on: date
    symbol: str
    approved: bool
    opportunity_score: Decimal
    final_signal: str
    primary_reason_code: str
    rejection_category: str
    explanation: str


@dataclass(frozen=True, slots=True)
class ActionEvent:
    """Resolved action metadata used only for retrospective attribution."""

    action_type: str
    effective_date: date
    symbols: frozenset[str]


@dataclass(frozen=True, slots=True)
class FunnelRecord:
    """One candidate's terminal position in the frozen benchmark funnel."""

    price_view: str
    observed_on: date
    symbol: str
    action_cohort: str
    action_types: tuple[str, ...]
    final_signal: str
    approvable_signal: bool
    institutional_approved: bool
    opportunity_score: Decimal
    primary_reason_code: str
    rejection_category: str
    runtime_status: str
    trade_executed: bool
    trade_id: str | None
    stage_reached: str
    terminal_gate: str
    gate_category: str
    gate_explanation: str
    unexplained_terminal_gate: bool

    def as_dict(self) -> dict[str, object]:
        return cast(dict[str, object], _json_ready(asdict(self)))


@dataclass(frozen=True, slots=True)
class GovernedTradeFormationResult:
    """Signed B4 certificate and its deterministic supporting evidence."""

    report: dict[str, Any]
    funnel_rows: tuple[dict[str, object], ...]
    gate_rows: tuple[dict[str, object], ...]
    entry_rows: tuple[dict[str, object], ...]
    trade_rows: tuple[dict[str, object], ...]
    economic_rows: tuple[dict[str, object], ...]
    cohort_rows: tuple[dict[str, object], ...]
    paths: tuple[Path, ...]


class GovernedTradeFormationEngine:
    """Explain the complete RAW/ADJUSTED candidate-to-trade funnel."""

    def run(
        self,
        *,
        b2_report: Path,
        b3_certificate: Path,
        b3_activation_contract: Path,
        raw_benchmark: Path,
        adjusted_benchmark: Path,
        corporate_action_artifact: Path,
        output: Path,
        progress: ProgressCallback | None = None,
    ) -> GovernedTradeFormationResult:
        total_steps = 8
        _progress(progress, 1, total_steps, "Validating signed HTR-010B3 handoff")
        activation = validate_governed_adjusted_research_activation(
            stability_certificate=b3_certificate,
            activation_contract=b3_activation_contract,
        )
        certificate = _mapping(b3_certificate)
        _validate_b3_handoff(certificate, activation)

        _progress(progress, 2, total_steps, "Validating signed HTR-010B2 benchmark")
        b2 = _validated_b2_report(b2_report)
        _validate_lineage(b2=b2, certificate=certificate, activation=activation)

        _progress(progress, 3, total_steps, "Verifying RAW benchmark funnel artifacts")
        raw = _load_bundle(raw_benchmark)
        _validate_bundle_against_summary(raw, _nested_mapping(b2, "raw_summary"))

        _progress(
            progress,
            4,
            total_steps,
            "Verifying ADJUSTED benchmark funnel artifacts",
        )
        adjusted = _load_bundle(adjusted_benchmark)
        _validate_bundle_against_summary(
            adjusted,
            _nested_mapping(b2, "adjusted_summary"),
        )
        _validate_bundle_pair(raw, adjusted, certificate)

        replay_end = _date_value(raw.manifest.get("replay_end"), "RAW replay end")
        _progress(progress, 5, total_steps, "Reconstructing candidate-to-trade funnels")
        actions = _load_action_events(corporate_action_artifact, replay_end=replay_end)
        raw_funnel, raw_defects = _build_funnel(
            raw,
            price_view="RAW",
            actions=actions,
            replay_end=replay_end,
        )
        adjusted_funnel, adjusted_defects = _build_funnel(
            adjusted,
            price_view="ADJUSTED",
            actions=actions,
            replay_end=replay_end,
        )
        funnel_rows = tuple(item.as_dict() for item in (*raw_funnel, *adjusted_funnel))
        entry_rows, gate_divergences = _entry_comparisons(
            raw_funnel,
            adjusted_funnel,
        )

        _progress(progress, 6, total_steps, "Attributing gates and action cohorts")
        gate_rows = _gate_attribution((*raw_funnel, *adjusted_funnel))
        trade_rows, trade_defects = _trade_pairing(
            raw=raw,
            adjusted=adjusted,
            entry_rows=entry_rows,
            actions=actions,
            replay_end=replay_end,
        )
        cohort_rows = _action_cohort_impact(entry_rows, trade_rows)

        _progress(progress, 7, total_steps, "Evaluating economic non-vacuity")
        economic_rows = _economic_impact(
            raw=raw,
            adjusted=adjusted,
            trade_rows=trade_rows,
            b3_certificate=certificate,
        )
        defects = tuple(sorted({*raw_defects, *adjusted_defects, *trade_defects}))
        unexplained_terminal = sum(
            bool(row["unexplained_terminal_gate"]) for row in funnel_rows
        )
        unexplained_trade = sum(
            bool(row["unexplained_trade_divergence"]) for row in trade_rows
        )
        raw_summary = _funnel_summary(raw_funnel, raw)
        adjusted_summary = _funnel_summary(adjusted_funnel, adjusted)
        trade_summary = _trade_summary(trade_rows)
        zero_trade_consistent = (
            raw_summary["trade_count"] == 0
            and adjusted_summary["trade_count"] == 0
            and raw_summary["institutional_approval_count"] == 0
            and adjusted_summary["institutional_approval_count"] == 0
            and not defects
            and unexplained_terminal == 0
            and gate_divergences == 0
            and unexplained_trade == 0
        )
        readiness, blockers = _readiness(
            defects=defects,
            unexplained_terminal=unexplained_terminal,
            unexplained_gate_divergences=gate_divergences,
            unexplained_trade_divergences=unexplained_trade,
            raw_trade_count=cast(int, raw_summary["trade_count"]),
            adjusted_trade_count=cast(int, adjusted_summary["trade_count"]),
            paired_trade_count=cast(int, trade_summary["paired_trade_count"]),
            paired_trade_windows=_paired_trade_windows(
                trade_rows,
                certificate,
            ),
        )
        enabled = readiness == B4_READY

        report: dict[str, Any] = {
            "contract_version": HTR010B4_CONTRACT_VERSION,
            "b2_report_sha256": b2["report_sha256"],
            "b2_report_file_sha256": _file_sha256(b2_report),
            "b3_stability_certificate_sha256": certificate["report_sha256"],
            "b3_stability_certificate_file_sha256": _file_sha256(b3_certificate),
            "b3_activation_contract_sha256": activation["report_sha256"],
            "b3_activation_contract_file_sha256": _file_sha256(b3_activation_contract),
            "raw_manifest_sha256": raw.manifest_sha256,
            "adjusted_manifest_sha256": adjusted.manifest_sha256,
            "corporate_action_artifact_sha256": _file_sha256(corporate_action_artifact),
            "replay_start": raw.manifest["replay_start"],
            "replay_end": raw.manifest["replay_end"],
            "session_count": _integer(raw.manifest["sessions"], "session count"),
            "trade_readiness_contract": {
                "minimum_completed_paired_trades": MINIMUM_COMPLETED_PAIRED_TRADES,
                "minimum_trade_windows": MINIMUM_TRADE_WINDOWS,
                "policy_change_permitted": False,
                "threshold_change_permitted": False,
            },
            "raw_funnel_summary": raw_summary,
            "adjusted_funnel_summary": adjusted_summary,
            "trade_pairing_summary": trade_summary,
            "gate_attribution_summary": _gate_summary(gate_rows),
            "action_cohort_summary": list(cohort_rows),
            "implementation_defects": list(defects),
            "implementation_defect_count": len(defects),
            "unexplained_terminal_gate_count": unexplained_terminal,
            "unexplained_gate_divergence_count": gate_divergences,
            "unexplained_trade_divergence_count": unexplained_trade,
            "zero_trade_policy_consistent": zero_trade_consistent,
            "funnel_metrics_evaluated": True,
            "economic_metrics_evaluated": (
                cast(int, raw_summary["trade_count"])
                + cast(int, adjusted_summary["trade_count"])
                > 0
            ),
            "readiness_blockers": list(blockers),
            "readiness_decision": readiness,
            "trade_formation_certified": not defects
            and unexplained_terminal == 0
            and gate_divergences == 0
            and unexplained_trade == 0,
            "governed_adjusted_trade_research_enabled": enabled,
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
        report["report_sha256"] = _digest_mapping(report)

        _progress(progress, 8, total_steps, "Exporting signed HTR-010B4 artifacts")
        paths = export_governed_trade_formation(
            report=report,
            funnel_rows=funnel_rows,
            gate_rows=gate_rows,
            entry_rows=entry_rows,
            trade_rows=trade_rows,
            economic_rows=economic_rows,
            cohort_rows=cohort_rows,
            output=output,
        )
        return GovernedTradeFormationResult(
            report=report,
            funnel_rows=funnel_rows,
            gate_rows=gate_rows,
            entry_rows=entry_rows,
            trade_rows=trade_rows,
            economic_rows=economic_rows,
            cohort_rows=cohort_rows,
            paths=paths,
        )


def export_governed_trade_formation(
    *,
    report: dict[str, Any],
    funnel_rows: tuple[dict[str, object], ...],
    gate_rows: tuple[dict[str, object], ...],
    entry_rows: tuple[dict[str, object], ...],
    trade_rows: tuple[dict[str, object], ...],
    economic_rows: tuple[dict[str, object], ...],
    cohort_rows: tuple[dict[str, object], ...],
    output: Path,
) -> tuple[Path, ...]:
    """Write deterministic B4 certification and funnel evidence artifacts."""

    output.mkdir(parents=True, exist_ok=True)
    return (
        _write_json(output / "htr010b4_trade_formation_certificate.json", report),
        _write_csv(
            output / "htr010b4_funnel_ledger.csv",
            funnel_rows,
            fieldnames=_FUNNEL_FIELDS,
        ),
        _write_csv(
            output / "htr010b4_gate_attribution.csv",
            gate_rows,
            fieldnames=_GATE_FIELDS,
        ),
        _write_csv(
            output / "htr010b4_entry_eligibility_comparison.csv",
            entry_rows,
            fieldnames=_ENTRY_FIELDS,
        ),
        _write_csv(
            output / "htr010b4_trade_pairing.csv",
            trade_rows,
            fieldnames=_TRADE_FIELDS,
        ),
        _write_csv(
            output / "htr010b4_economic_impact.csv",
            economic_rows,
            fieldnames=_ECONOMIC_FIELDS,
        ),
        _write_csv(
            output / "htr010b4_action_cohort_impact.csv",
            cohort_rows,
            fieldnames=_COHORT_FIELDS,
        ),
        _write_text(
            output / "htr010b4_executive_report.md",
            _markdown(report),
        ),
    )


def validate_governed_trade_formation_certificate(
    path: Path,
    *,
    require_ready: bool = False,
) -> dict[str, Any]:
    """Validate the signed B4 contract for a later governed research consumer."""

    payload = _mapping(path)
    if payload.get("contract_version") != HTR010B4_CONTRACT_VERSION:
        raise ValueError("unsupported HTR-010B4 trade-formation contract")
    _validate_digest(payload, "HTR-010B4 trade-formation certificate")
    _validate_research_only_flags(payload)
    if require_ready and payload.get("readiness_decision") != B4_READY:
        raise ValueError("HTR-010B4 does not permit governed adjusted trade research")
    if (
        require_ready
        and payload.get("governed_adjusted_trade_research_enabled") is not True
    ):
        raise ValueError("HTR-010B4 trade research is disabled")
    return payload


def _validate_b3_handoff(
    certificate: dict[str, Any],
    activation: dict[str, Any],
) -> None:
    if certificate.get("contract_version") != HTR010B3_CONTRACT_VERSION:
        raise ValueError("B4 requires the HTR-010B3 stability certificate")
    if activation.get("contract_version") != HTR010B3_ACTIVATION_CONTRACT_VERSION:
        raise ValueError("B4 requires the HTR-010B3 activation contract")
    if certificate.get("readiness_decision") != B3_READY:
        raise ValueError("HTR-010B3 does not permit trade-formation certification")
    if certificate.get("research_scope") != "GOVERNED_BENCHMARK_RESEARCH_ONLY":
        raise ValueError("HTR-010B3 research scope is invalid")
    if activation.get("research_scope") != "GOVERNED_BENCHMARK_RESEARCH_ONLY":
        raise ValueError("HTR-010B3 activation scope is invalid")


def _validate_lineage(
    *,
    b2: dict[str, Any],
    certificate: dict[str, Any],
    activation: dict[str, Any],
) -> None:
    b2_sha = str(b2["report_sha256"])
    if certificate.get("b2_report_sha256") != b2_sha:
        raise ValueError("HTR-010B3 certificate does not match HTR-010B2")
    if activation.get("b2_report_sha256") != b2_sha:
        raise ValueError("HTR-010B3 activation does not match HTR-010B2")
    if activation.get("stability_certificate_sha256") != certificate.get(
        "report_sha256"
    ):
        raise ValueError("HTR-010B3 activation does not match its certificate")


def _validated_b2_report(path: Path) -> dict[str, Any]:
    payload = _mapping(path)
    if payload.get("contract_version") != HTR010B2_CONTRACT_VERSION:
        raise ValueError("B4 requires the HTR-010B2 benchmark contract")
    _validate_digest(payload, "HTR-010B2 benchmark report")
    if payload.get("readiness_decision") != (
        "READY_FOR_GOVERNED_ADJUSTED_BENCHMARK_RESEARCH"
    ):
        raise ValueError("HTR-010B2 does not permit trade-formation certification")
    if payload.get("decision_metrics_evaluated") is not True:
        raise ValueError("HTR-010B2 decision metrics were not evaluated")
    if payload.get("governed_adjusted_benchmark_enabled") is not True:
        raise ValueError("HTR-010B2 benchmark research is disabled")
    comparison = _nested_mapping(payload, "comparison")
    if comparison.get("benchmark_population_nonempty") is not True:
        raise ValueError("HTR-010B2 benchmark population is empty")
    if int(comparison.get("unexplained_divergence_count", -1)) != 0:
        raise ValueError("HTR-010B2 contains unexplained divergences")
    if list(comparison.get("readiness_blockers") or []):
        raise ValueError("HTR-010B2 contains readiness blockers")
    if payload.get("active_replay_integration") is not False:
        raise ValueError("HTR-010B2 active replay integration is not disabled")
    if payload.get("production_influence") is not False:
        raise ValueError("HTR-010B2 production influence is not disabled")
    return payload


def _load_bundle(root: Path) -> BenchmarkTradeBundle:
    manifest_path = root / "manifest.json"
    manifest = _mapping(manifest_path)
    if manifest.get("production_influence") is not False:
        raise ValueError(f"benchmark manifest permits production influence: {root}")
    if manifest.get("point_in_time_enforced") is not True:
        raise ValueError(f"benchmark manifest is not point-in-time enforced: {root}")
    if manifest.get("no_future_leakage") is not True:
        raise ValueError(f"benchmark manifest permits future leakage: {root}")
    raw_hashes = manifest.get("artifact_hashes")
    if not isinstance(raw_hashes, dict):
        raise ValueError(f"benchmark manifest lacks artifact hashes: {root}")
    hashes = {str(key): str(value) for key, value in raw_hashes.items()}
    missing = tuple(sorted(_EXPECTED_BENCHMARK_ARTIFACTS.difference(hashes)))
    if missing:
        raise ValueError(
            f"benchmark manifest lacks required artifacts: {', '.join(missing)}"
        )
    for name, expected in sorted(hashes.items()):
        artifact = root / name
        if not artifact.is_file():
            raise ValueError(f"benchmark artifact is missing: {artifact}")
        if _file_sha256(artifact) != expected:
            raise ValueError(f"benchmark artifact digest mismatch: {artifact}")
    return BenchmarkTradeBundle(
        root=root,
        manifest=manifest,
        manifest_sha256=_file_sha256(manifest_path),
        candidate_rows=_csv_rows(root / "candidate_statistics.csv"),
        approval_rows=_csv_rows(root / "approval_statistics.csv"),
        trade_rows=_csv_rows(root / "trade_log.csv"),
        position_rows=_csv_rows(root / "position_history.csv"),
        capital_rows=_csv_rows(root / "capital_curve.csv"),
        portfolio_rows=_csv_rows(root / "portfolio_statistics.csv"),
        eligibility_rows=_csv_rows(root / "decision_eligibility.csv"),
        rejection_rows=_csv_rows(root / "top_rejection_reasons.csv"),
    )


def _validate_bundle_against_summary(
    bundle: BenchmarkTradeBundle,
    summary: dict[str, Any],
) -> None:
    sessions = _integer(bundle.manifest.get("sessions"), "manifest sessions")
    if sessions != _integer(summary.get("session_count"), "summary sessions"):
        raise ValueError("benchmark manifest and B2 session counts differ")
    if len(bundle.candidate_rows) != sessions:
        raise ValueError("candidate statistics do not cover every replay session")
    candidate_total = sum(
        _integer(row.get("technical_candidates"), "technical candidates")
        for row in bundle.candidate_rows
    )
    approval_total = sum(
        _integer(row.get("institutional_approvals"), "institutional approvals")
        for row in bundle.candidate_rows
    )
    if candidate_total != len(bundle.approval_rows):
        raise ValueError("approval rows do not cover every technical candidate")
    if candidate_total != _integer(
        summary.get("technical_candidate_count"),
        "summary technical candidates",
    ):
        raise ValueError("candidate artifact does not match B2 summary")
    if approval_total != _integer(
        summary.get("institutional_approval_count"),
        "summary institutional approvals",
    ):
        raise ValueError("approval artifact does not match B2 summary")
    approved_rows = sum(
        _boolean(row.get("approved"), "approval row approved")
        for row in bundle.approval_rows
    )
    if approved_rows != approval_total:
        raise ValueError("approval row decisions do not match candidate statistics")
    if len(bundle.trade_rows) != _integer(summary.get("trade_count"), "summary trades"):
        raise ValueError("trade artifact does not match B2 summary")
    if len(bundle.portfolio_rows) != 1:
        raise ValueError("portfolio statistics artifact must contain one row")
    if len(bundle.eligibility_rows) != 1:
        raise ValueError("decision eligibility artifact must contain one row")
    eligibility = bundle.eligibility_rows[0]
    if _integer(eligibility.get("eligible_securities"), "eligible securities") != (
        _integer(summary.get("eligible_security_count"), "summary eligible securities")
    ):
        raise ValueError("eligible security count does not match B2 summary")
    if _integer(
        eligibility.get("eligible_security_days"),
        "eligible security days",
    ) != _integer(
        summary.get("eligible_security_observation_count"),
        "summary eligible observations",
    ):
        raise ValueError("eligible observation count does not match B2 summary")


def _validate_bundle_pair(
    raw: BenchmarkTradeBundle,
    adjusted: BenchmarkTradeBundle,
    certificate: Mapping[str, object],
) -> None:
    raw_dates = tuple(_candidate_session_map(raw.candidate_rows, "RAW"))
    adjusted_dates = tuple(_candidate_session_map(adjusted.candidate_rows, "ADJUSTED"))
    if raw_dates != adjusted_dates:
        raise ValueError("RAW and ADJUSTED candidate session coverage differs")
    if not raw_dates:
        raise ValueError("B4 candidate session population is empty")
    if _integer(certificate.get("session_count"), "B3 sessions") != len(raw_dates):
        raise ValueError("HTR-010B3 and benchmark session counts differ")
    evidence = _nested_mapping(certificate, "evidence_summary")
    if _integer(evidence.get("raw_decision_count"), "B3 RAW decisions") != len(
        raw.approval_rows
    ):
        raise ValueError("HTR-010B3 RAW decision count differs")
    if _integer(
        evidence.get("adjusted_decision_count"),
        "B3 ADJUSTED decisions",
    ) != len(adjusted.approval_rows):
        raise ValueError("HTR-010B3 ADJUSTED decision count differs")
    if _integer(evidence.get("raw_trade_count"), "B3 RAW trades") != len(
        raw.trade_rows
    ):
        raise ValueError("HTR-010B3 RAW trade count differs")
    if _integer(evidence.get("adjusted_trade_count"), "B3 ADJUSTED trades") != len(
        adjusted.trade_rows
    ):
        raise ValueError("HTR-010B3 ADJUSTED trade count differs")


def _build_funnel(
    bundle: BenchmarkTradeBundle,
    *,
    price_view: str,
    actions: tuple[ActionEvent, ...],
    replay_end: date,
) -> tuple[tuple[FunnelRecord, ...], tuple[str, ...]]:
    sessions = _candidate_session_map(bundle.candidate_rows, price_view)
    decisions = _decision_map(bundle.approval_rows, price_view)
    trades_by_decision, trade_defects = _trade_map(bundle.trade_rows, price_view)
    defects: list[str] = list(trade_defects)
    decisions_by_date: dict[date, list[DecisionEvidence]] = defaultdict(list)
    for decision in decisions.values():
        decisions_by_date[decision.observed_on].append(decision)
    entry_counts = Counter(
        _date_value(row.get("entry_date"), f"{price_view} trade entry date")
        for row in bundle.trade_rows
    )
    for observed_on, session in sessions.items():
        expected_candidates = _integer(
            session.get("technical_candidates"),
            f"{price_view} technical candidates",
        )
        actual_candidates = len(decisions_by_date.get(observed_on, ()))
        if actual_candidates != expected_candidates:
            defects.append(
                f"{price_view}_DECISION_COVERAGE_MISMATCH@{observed_on.isoformat()}"
            )
        expected_entries = _integer(
            session.get("portfolio_entries"),
            f"{price_view} portfolio entries",
        )
        if entry_counts.get(observed_on, 0) != expected_entries:
            defects.append(
                f"{price_view}_ENTRY_COVERAGE_MISMATCH@{observed_on.isoformat()}"
            )
    result: list[FunnelRecord] = []
    matched_trade_keys: set[tuple[date, str]] = set()
    for key, decision in sorted(decisions.items()):
        session_row = sessions.get(decision.observed_on)
        if session_row is None:
            defects.append(
                f"{price_view}_DECISION_WITHOUT_SESSION@"
                f"{decision.observed_on.isoformat()}|{decision.symbol}"
            )
            runtime_status = "MISSING_SESSION"
        else:
            runtime_status = (
                str(session_row.get("runtime_status") or "").strip().upper()
            )
        trade = trades_by_decision.get(key)
        if trade is not None:
            matched_trade_keys.add(key)
        approvable = decision.final_signal in _APPROVABLE_SIGNALS
        if decision.approved and not approvable:
            defects.append(
                f"{price_view}_APPROVED_NON_APPROVABLE_SIGNAL@"
                f"{decision.observed_on.isoformat()}|{decision.symbol}"
            )
        if trade is not None and not decision.approved:
            defects.append(
                f"{price_view}_TRADE_WITHOUT_APPROVAL@"
                f"{decision.observed_on.isoformat()}|{decision.symbol}"
            )
        stage, gate, category, explanation, unexplained = _terminal_gate(
            decision=decision,
            runtime_status=runtime_status,
            trade=trade,
        )
        action_types = _affecting_action_types(
            actions,
            symbol=decision.symbol,
            observed_on=decision.observed_on,
            replay_end=replay_end,
        )
        result.append(
            FunnelRecord(
                price_view=price_view,
                observed_on=decision.observed_on,
                symbol=decision.symbol,
                action_cohort=("ACTION_AFFECTED" if action_types else "UNAFFECTED"),
                action_types=action_types,
                final_signal=decision.final_signal,
                approvable_signal=approvable,
                institutional_approved=decision.approved,
                opportunity_score=decision.opportunity_score,
                primary_reason_code=decision.primary_reason_code,
                rejection_category=decision.rejection_category,
                runtime_status=runtime_status,
                trade_executed=trade is not None,
                trade_id=None if trade is None else str(trade.get("trade_id") or ""),
                stage_reached=stage,
                terminal_gate=gate,
                gate_category=category,
                gate_explanation=explanation,
                unexplained_terminal_gate=unexplained,
            )
        )
    for key in sorted(set(trades_by_decision).difference(matched_trade_keys)):
        defects.append(
            f"{price_view}_TRADE_WITHOUT_DECISION@{key[0].isoformat()}|{key[1]}"
        )
    return tuple(result), tuple(sorted(set(defects)))


def _terminal_gate(
    *,
    decision: DecisionEvidence,
    runtime_status: str,
    trade: dict[str, str] | None,
) -> tuple[str, str, str, str, bool]:
    if runtime_status != "SUCCESS":
        return (
            "CANONICAL_RUNTIME",
            "CANONICAL_RUNTIME_FAILURE",
            "RUNTIME",
            f"Candidate session runtime status was {runtime_status or 'UNKNOWN'}.",
            False,
        )
    if decision.final_signal not in _APPROVABLE_SIGNALS:
        signal = decision.final_signal or "UNKNOWN"
        return (
            "SIGNAL",
            f"NON_APPROVABLE_SIGNAL:{signal}",
            "SIGNAL",
            f"Frozen signal was {signal}, not BUY or STRONG_BUY.",
            False,
        )
    if not decision.approved:
        reason = (
            decision.primary_reason_code.strip() or "INSTITUTIONAL_REJECTION_UNKNOWN"
        )
        unexplained = reason in {"UNKNOWN", "INSTITUTIONAL_REJECTION_UNKNOWN"}
        return (
            "INSTITUTIONAL_DECISION",
            reason,
            decision.rejection_category or "INSTITUTIONAL",
            decision.explanation or "Institutional approval was not granted.",
            unexplained,
        )
    if trade is not None:
        return (
            "COMPLETED_TRADE",
            "TRADE_COMPLETED",
            "EXECUTION",
            "Approved candidate entered and completed a benchmark trade.",
            False,
        )
    return (
        "INSTITUTIONAL_APPROVAL",
        "APPROVED_WITHOUT_EXECUTABLE_TRADE",
        "EXECUTION",
        "Approved candidate has no completed benchmark trade evidence.",
        True,
    )


def _entry_comparisons(
    raw_records: tuple[FunnelRecord, ...],
    adjusted_records: tuple[FunnelRecord, ...],
) -> tuple[tuple[dict[str, object], ...], int]:
    raw = {(item.observed_on, item.symbol): item for item in raw_records}
    adjusted = {(item.observed_on, item.symbol): item for item in adjusted_records}
    keys = tuple(sorted(set(raw).union(adjusted)))
    result: list[dict[str, object]] = []
    unexplained = 0
    for key in keys:
        raw_item = raw.get(key)
        adjusted_item = adjusted.get(key)
        reference = raw_item or adjusted_item
        if reference is None:
            continue
        signal_changed = (
            raw_item is not None
            and adjusted_item is not None
            and raw_item.final_signal != adjusted_item.final_signal
        )
        approval_changed = (
            raw_item is not None
            and adjusted_item is not None
            and raw_item.institutional_approved != adjusted_item.institutional_approved
        )
        reason_changed = (
            raw_item is not None
            and adjusted_item is not None
            and raw_item.primary_reason_code != adjusted_item.primary_reason_code
        )
        gate_changed = (
            raw_item is None
            or adjusted_item is None
            or raw_item.terminal_gate != adjusted_item.terminal_gate
        )
        explained = (
            not gate_changed or signal_changed or approval_changed or reason_changed
        )
        if gate_changed and not explained:
            unexplained += 1
        score_delta = (
            adjusted_item.opportunity_score - raw_item.opportunity_score
            if raw_item is not None and adjusted_item is not None
            else None
        )
        action_types = tuple(
            sorted(
                {
                    *(raw_item.action_types if raw_item is not None else ()),
                    *(adjusted_item.action_types if adjusted_item is not None else ()),
                }
            )
        )
        result.append(
            {
                "observed_on": key[0],
                "symbol": key[1],
                "action_cohort": ("ACTION_AFFECTED" if action_types else "UNAFFECTED"),
                "action_types": action_types,
                "raw_present": raw_item is not None,
                "adjusted_present": adjusted_item is not None,
                "raw_signal": None if raw_item is None else raw_item.final_signal,
                "adjusted_signal": (
                    None if adjusted_item is None else adjusted_item.final_signal
                ),
                "signal_changed": signal_changed,
                "raw_approved": (
                    None if raw_item is None else raw_item.institutional_approved
                ),
                "adjusted_approved": (
                    None
                    if adjusted_item is None
                    else adjusted_item.institutional_approved
                ),
                "approval_changed": approval_changed,
                "raw_terminal_gate": (
                    None if raw_item is None else raw_item.terminal_gate
                ),
                "adjusted_terminal_gate": (
                    None if adjusted_item is None else adjusted_item.terminal_gate
                ),
                "terminal_gate_changed": gate_changed,
                "raw_trade_executed": (
                    False if raw_item is None else raw_item.trade_executed
                ),
                "adjusted_trade_executed": (
                    False if adjusted_item is None else adjusted_item.trade_executed
                ),
                "raw_score": None if raw_item is None else raw_item.opportunity_score,
                "adjusted_score": (
                    None if adjusted_item is None else adjusted_item.opportunity_score
                ),
                "score_delta": score_delta,
                "explained_gate_difference": explained,
            }
        )
    return tuple(result), unexplained


def _gate_attribution(
    records: Sequence[FunnelRecord],
) -> tuple[dict[str, object], ...]:
    grouped: Counter[tuple[str, str, str, str]] = Counter()
    totals: Counter[tuple[str, str]] = Counter()
    for record in records:
        cohorts = ["ALL", record.action_cohort]
        cohorts.extend(f"ACTION_TYPE:{item}" for item in record.action_types)
        for cohort in cohorts:
            grouped[
                (
                    record.price_view,
                    cohort,
                    record.terminal_gate,
                    record.gate_category,
                )
            ] += 1
            totals[(record.price_view, cohort)] += 1
    return tuple(
        {
            "price_view": price_view,
            "cohort": cohort,
            "terminal_gate": gate,
            "gate_category": category,
            "candidate_count": count,
            "candidate_percent": _percent(count, totals[(price_view, cohort)]),
        }
        for (price_view, cohort, gate, category), count in sorted(grouped.items())
    )


def _trade_pairing(
    *,
    raw: BenchmarkTradeBundle,
    adjusted: BenchmarkTradeBundle,
    entry_rows: tuple[dict[str, object], ...],
    actions: tuple[ActionEvent, ...],
    replay_end: date,
) -> tuple[tuple[dict[str, object], ...], tuple[str, ...]]:
    raw_map, raw_defects = _trade_map(raw.trade_rows, "RAW")
    adjusted_map, adjusted_defects = _trade_map(adjusted.trade_rows, "ADJUSTED")
    entry_map = {
        (cast(date, row["observed_on"]), str(row["symbol"])): row for row in entry_rows
    }
    keys = tuple(sorted(set(raw_map).union(adjusted_map)))
    result: list[dict[str, object]] = []
    defects = [*raw_defects, *adjusted_defects]
    for key in keys:
        raw_item = raw_map.get(key)
        adjusted_item = adjusted_map.get(key)
        entry = entry_map.get(key)
        if entry is None:
            defects.append(
                f"TRADE_WITHOUT_FUNNEL_DECISION@{key[0].isoformat()}|{key[1]}"
            )
        action_types = _affecting_action_types(
            actions,
            symbol=key[1],
            observed_on=key[0],
            replay_end=replay_end,
        )
        raw_return = _optional_decimal_value(raw_item, "net_return_percent")
        adjusted_return = _optional_decimal_value(
            adjusted_item,
            "net_return_percent",
        )
        raw_pnl = _optional_decimal_value(raw_item, "net_profit_loss")
        adjusted_pnl = _optional_decimal_value(adjusted_item, "net_profit_loss")
        raw_tx = _optional_decimal_value(raw_item, "transaction_cost")
        adjusted_tx = _optional_decimal_value(adjusted_item, "transaction_cost")
        raw_slippage = _optional_decimal_value(raw_item, "slippage_cost")
        adjusted_slippage = _optional_decimal_value(adjusted_item, "slippage_cost")
        presence_diff = (raw_item is None) != (adjusted_item is None)
        explained = not presence_diff
        if presence_diff and entry is not None:
            explained = (
                bool(entry.get("terminal_gate_changed"))
                or bool(entry.get("signal_changed"))
                or bool(entry.get("approval_changed"))
            )
        unexplained = presence_diff and not explained
        result.append(
            {
                "decision_date": key[0],
                "symbol": key[1],
                "action_cohort": ("ACTION_AFFECTED" if action_types else "UNAFFECTED"),
                "action_types": action_types,
                "raw_present": raw_item is not None,
                "adjusted_present": adjusted_item is not None,
                "paired": raw_item is not None and adjusted_item is not None,
                "raw_trade_id": None if raw_item is None else raw_item.get("trade_id"),
                "adjusted_trade_id": (
                    None if adjusted_item is None else adjusted_item.get("trade_id")
                ),
                "raw_entry_date": (
                    None if raw_item is None else raw_item.get("entry_date")
                ),
                "adjusted_entry_date": (
                    None if adjusted_item is None else adjusted_item.get("entry_date")
                ),
                "raw_exit_date": (
                    None if raw_item is None else raw_item.get("exit_date")
                ),
                "adjusted_exit_date": (
                    None if adjusted_item is None else adjusted_item.get("exit_date")
                ),
                "raw_net_return_percent": raw_return,
                "adjusted_net_return_percent": adjusted_return,
                "net_return_delta": _difference(adjusted_return, raw_return),
                "raw_net_profit_loss": raw_pnl,
                "adjusted_net_profit_loss": adjusted_pnl,
                "net_profit_loss_delta": _difference(adjusted_pnl, raw_pnl),
                "raw_transaction_cost": raw_tx,
                "adjusted_transaction_cost": adjusted_tx,
                "raw_slippage_cost": raw_slippage,
                "adjusted_slippage_cost": adjusted_slippage,
                "raw_exit_reason": (
                    None if raw_item is None else raw_item.get("exit_reason")
                ),
                "adjusted_exit_reason": (
                    None if adjusted_item is None else adjusted_item.get("exit_reason")
                ),
                "exit_reason_changed": (
                    raw_item is not None
                    and adjusted_item is not None
                    and raw_item.get("exit_reason") != adjusted_item.get("exit_reason")
                ),
                "explained_presence_difference": explained,
                "unexplained_trade_divergence": unexplained,
            }
        )
    return tuple(result), tuple(sorted(set(defects)))


def _economic_impact(
    *,
    raw: BenchmarkTradeBundle,
    adjusted: BenchmarkTradeBundle,
    trade_rows: tuple[dict[str, object], ...],
    b3_certificate: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    rows = [
        _economic_row(
            scope="OVERALL",
            start_date=_date_value(raw.manifest["replay_start"], "replay start"),
            end_date=_date_value(raw.manifest["replay_end"], "replay end"),
            trade_rows=trade_rows,
            raw=raw,
            adjusted=adjusted,
        )
    ]
    windows = b3_certificate.get("window_stability")
    if not isinstance(windows, list):
        raise ValueError("HTR-010B3 certificate lacks window stability evidence")
    for item in windows:
        if not isinstance(item, dict):
            raise ValueError("HTR-010B3 window stability row must be a mapping")
        index = _integer(item.get("window_index"), "window index")
        start = _date_value(item.get("start_date"), "window start")
        end = _date_value(item.get("end_date"), "window end")
        rows.append(
            _economic_row(
                scope=f"WINDOW_{index}",
                start_date=start,
                end_date=end,
                trade_rows=tuple(
                    row
                    for row in trade_rows
                    if start <= cast(date, row["decision_date"]) <= end
                ),
                raw=raw,
                adjusted=adjusted,
            )
        )
    return tuple(rows)


def _economic_row(
    *,
    scope: str,
    start_date: date,
    end_date: date,
    trade_rows: tuple[dict[str, object], ...],
    raw: BenchmarkTradeBundle,
    adjusted: BenchmarkTradeBundle,
) -> dict[str, object]:
    raw_rows = tuple(row for row in trade_rows if bool(row["raw_present"]))
    adjusted_rows = tuple(row for row in trade_rows if bool(row["adjusted_present"]))
    paired = tuple(row for row in trade_rows if bool(row["paired"]))
    raw_curve = _curve_metrics(raw.capital_rows, start_date, end_date)
    adjusted_curve = _curve_metrics(adjusted.capital_rows, start_date, end_date)
    raw_pnl = _sum_optional(raw_rows, "raw_net_profit_loss")
    adjusted_pnl = _sum_optional(adjusted_rows, "adjusted_net_profit_loss")
    raw_return = _mean_optional(raw_rows, "raw_net_return_percent")
    adjusted_return = _mean_optional(adjusted_rows, "adjusted_net_return_percent")
    raw_tx = _sum_optional(raw_rows, "raw_transaction_cost")
    adjusted_tx = _sum_optional(adjusted_rows, "adjusted_transaction_cost")
    raw_slippage = _sum_optional(raw_rows, "raw_slippage_cost")
    adjusted_slippage = _sum_optional(adjusted_rows, "adjusted_slippage_cost")
    return {
        "scope": scope,
        "start_date": start_date,
        "end_date": end_date,
        "raw_trade_count": len(raw_rows),
        "adjusted_trade_count": len(adjusted_rows),
        "paired_trade_count": len(paired),
        "raw_only_trade_count": sum(
            bool(row["raw_present"]) and not bool(row["adjusted_present"])
            for row in trade_rows
        ),
        "adjusted_only_trade_count": sum(
            bool(row["adjusted_present"]) and not bool(row["raw_present"])
            for row in trade_rows
        ),
        "raw_net_profit_loss": raw_pnl,
        "adjusted_net_profit_loss": adjusted_pnl,
        "net_profit_loss_delta": adjusted_pnl - raw_pnl,
        "raw_mean_net_return_percent": raw_return,
        "adjusted_mean_net_return_percent": adjusted_return,
        "mean_net_return_delta": _difference(adjusted_return, raw_return),
        "raw_transaction_cost": raw_tx,
        "adjusted_transaction_cost": adjusted_tx,
        "transaction_cost_delta": adjusted_tx - raw_tx,
        "raw_slippage_cost": raw_slippage,
        "adjusted_slippage_cost": adjusted_slippage,
        "slippage_cost_delta": adjusted_slippage - raw_slippage,
        "raw_portfolio_return_percent": raw_curve["return_percent"],
        "adjusted_portfolio_return_percent": adjusted_curve["return_percent"],
        "portfolio_return_delta": _difference(
            adjusted_curve["return_percent"],
            raw_curve["return_percent"],
        ),
        "raw_maximum_drawdown_percent": raw_curve["maximum_drawdown_percent"],
        "adjusted_maximum_drawdown_percent": adjusted_curve["maximum_drawdown_percent"],
    }


def _action_cohort_impact(
    entry_rows: tuple[dict[str, object], ...],
    trade_rows: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    cohorts: set[str] = {"ALL", "ACTION_AFFECTED", "UNAFFECTED"}
    for row in entry_rows:
        cohorts.update(
            f"ACTION_TYPE:{item}" for item in cast(tuple[str, ...], row["action_types"])
        )
    result: list[dict[str, object]] = []
    for cohort in sorted(cohorts):
        decisions = tuple(row for row in entry_rows if _in_cohort(row, cohort))
        trades = tuple(row for row in trade_rows if _in_cohort(row, cohort))
        raw_pnl = _sum_optional(trades, "raw_net_profit_loss")
        adjusted_pnl = _sum_optional(trades, "adjusted_net_profit_loss")
        result.append(
            {
                "cohort": cohort,
                "paired_decisions": sum(
                    bool(row["raw_present"]) and bool(row["adjusted_present"])
                    for row in decisions
                ),
                "approval_flips": sum(
                    bool(row["approval_changed"]) for row in decisions
                ),
                "signal_changes": sum(bool(row["signal_changed"]) for row in decisions),
                "terminal_gate_changes": sum(
                    bool(row["terminal_gate_changed"]) for row in decisions
                ),
                "raw_trade_count": sum(bool(row["raw_present"]) for row in trades),
                "adjusted_trade_count": sum(
                    bool(row["adjusted_present"]) for row in trades
                ),
                "paired_trade_count": sum(bool(row["paired"]) for row in trades),
                "raw_only_trade_count": sum(
                    bool(row["raw_present"]) and not bool(row["adjusted_present"])
                    for row in trades
                ),
                "adjusted_only_trade_count": sum(
                    bool(row["adjusted_present"]) and not bool(row["raw_present"])
                    for row in trades
                ),
                "raw_net_profit_loss": raw_pnl,
                "adjusted_net_profit_loss": adjusted_pnl,
                "net_profit_loss_delta": adjusted_pnl - raw_pnl,
            }
        )
    return tuple(result)


def _funnel_summary(
    records: tuple[FunnelRecord, ...],
    bundle: BenchmarkTradeBundle,
) -> dict[str, object]:
    gates = Counter(item.terminal_gate for item in records)
    dominant_gate, dominant_count = gates.most_common(1)[0] if gates else ("NONE", 0)
    return {
        "candidate_count": len(records),
        "approvable_signal_count": sum(item.approvable_signal for item in records),
        "institutional_approval_count": sum(
            item.institutional_approved for item in records
        ),
        "portfolio_entry_count": sum(
            _integer(row.get("portfolio_entries"), "portfolio entries")
            for row in bundle.candidate_rows
        ),
        "trade_count": len(bundle.trade_rows),
        "unexplained_terminal_gate_count": sum(
            item.unexplained_terminal_gate for item in records
        ),
        "dominant_terminal_gate": dominant_gate,
        "dominant_terminal_gate_count": dominant_count,
        "terminal_gate_counts": dict(sorted(gates.items())),
    }


def _gate_summary(rows: tuple[dict[str, object], ...]) -> dict[str, object]:
    return {
        "row_count": len(rows),
        "raw_all_gate_count": sum(
            row["price_view"] == "RAW" and row["cohort"] == "ALL" for row in rows
        ),
        "adjusted_all_gate_count": sum(
            row["price_view"] == "ADJUSTED" and row["cohort"] == "ALL" for row in rows
        ),
    }


def _trade_summary(rows: tuple[dict[str, object], ...]) -> dict[str, object]:
    paired = tuple(row for row in rows if bool(row["paired"]))
    return {
        "trade_union_count": len(rows),
        "paired_trade_count": len(paired),
        "raw_only_trade_count": sum(
            bool(row["raw_present"]) and not bool(row["adjusted_present"])
            for row in rows
        ),
        "adjusted_only_trade_count": sum(
            bool(row["adjusted_present"]) and not bool(row["raw_present"])
            for row in rows
        ),
        "exit_reason_change_count": sum(
            bool(row["exit_reason_changed"]) for row in paired
        ),
        "unexplained_trade_divergence_count": sum(
            bool(row["unexplained_trade_divergence"]) for row in rows
        ),
    }


def _readiness(
    *,
    defects: tuple[str, ...],
    unexplained_terminal: int,
    unexplained_gate_divergences: int,
    unexplained_trade_divergences: int,
    raw_trade_count: int,
    adjusted_trade_count: int,
    paired_trade_count: int,
    paired_trade_windows: int,
) -> tuple[str, tuple[str, ...]]:
    blockers: list[str] = []
    if defects:
        blockers.append("FUNNEL_IMPLEMENTATION_DEFECT")
    if unexplained_terminal:
        blockers.append("UNEXPLAINED_TERMINAL_GATE")
    if unexplained_gate_divergences:
        blockers.append("UNEXPLAINED_GATE_DIVERGENCE")
    if defects or unexplained_terminal or unexplained_gate_divergences:
        return B4_BLOCKED_DEFECT, tuple(sorted(set(blockers)))
    if unexplained_trade_divergences:
        return B4_BLOCKED_DIVERGENCE, ("UNEXPLAINED_TRADE_DIVERGENCE",)
    if raw_trade_count == 0 and adjusted_trade_count == 0:
        return B4_BLOCKED_ZERO, ("ZERO_TRADE_POPULATION",)
    if raw_trade_count == 0 or adjusted_trade_count == 0:
        return B4_BLOCKED_DIVERGENCE, ("ONE_SIDED_TRADE_POPULATION",)
    if paired_trade_count < MINIMUM_COMPLETED_PAIRED_TRADES:
        blockers.append("INSUFFICIENT_COMPLETED_PAIRED_TRADES")
    if paired_trade_windows < MINIMUM_TRADE_WINDOWS:
        blockers.append("INSUFFICIENT_TRADE_WINDOWS")
    if blockers:
        return B4_BLOCKED_INSUFFICIENT, tuple(sorted(set(blockers)))
    return B4_READY, ()


def _paired_trade_windows(
    trade_rows: tuple[dict[str, object], ...],
    certificate: Mapping[str, object],
) -> int:
    windows = certificate.get("window_stability")
    if not isinstance(windows, list):
        raise ValueError("HTR-010B3 certificate lacks window stability evidence")
    count = 0
    for item in windows:
        if not isinstance(item, dict):
            raise ValueError("HTR-010B3 window stability row must be a mapping")
        start = _date_value(item.get("start_date"), "window start")
        end = _date_value(item.get("end_date"), "window end")
        if any(
            bool(row["paired"]) and start <= cast(date, row["decision_date"]) <= end
            for row in trade_rows
        ):
            count += 1
    return count


def _candidate_session_map(
    rows: tuple[dict[str, str], ...],
    label: str,
) -> dict[date, dict[str, str]]:
    result: dict[date, dict[str, str]] = {}
    for row in rows:
        observed_on = _date_value(row.get("observed_on"), f"{label} candidate date")
        if observed_on in result:
            raise ValueError(f"{label} candidate artifact contains duplicate sessions")
        result[observed_on] = row
    return dict(sorted(result.items()))


def _decision_map(
    rows: tuple[dict[str, str], ...],
    label: str,
) -> dict[tuple[date, str], DecisionEvidence]:
    result: dict[tuple[date, str], DecisionEvidence] = {}
    for row in rows:
        record = DecisionEvidence(
            observed_on=_date_value(row.get("observed_on"), f"{label} decision date"),
            symbol=_symbol(row.get("symbol"), f"{label} decision symbol"),
            approved=_boolean(row.get("approved"), f"{label} approved"),
            opportunity_score=_decimal(
                row.get("opportunity_score"),
                f"{label} opportunity score",
            ),
            final_signal=str(row.get("final_signal") or "").strip().upper(),
            primary_reason_code=str(row.get("primary_reason_code") or "").strip(),
            rejection_category=str(row.get("rejection_category") or "").strip(),
            explanation=str(row.get("explanation") or "").strip(),
        )
        key = record.observed_on, record.symbol
        if key in result:
            raise ValueError(f"{label} approval artifact contains duplicate decisions")
        result[key] = record
    return result


def _trade_map(
    rows: tuple[dict[str, str], ...],
    label: str,
) -> tuple[dict[tuple[date, str], dict[str, str]], tuple[str, ...]]:
    result: dict[tuple[date, str], dict[str, str]] = {}
    trade_ids: set[str] = set()
    defects: list[str] = []
    for row in rows:
        trade_id = str(row.get("trade_id") or "").strip()
        if not trade_id:
            defects.append(f"{label}_EMPTY_TRADE_ID")
        elif trade_id in trade_ids:
            defects.append(f"{label}_DUPLICATE_TRADE_ID:{trade_id}")
        trade_ids.add(trade_id)
        key = (
            _date_value(row.get("decision_date"), f"{label} trade decision date"),
            _symbol(row.get("symbol"), f"{label} trade symbol"),
        )
        if key in result:
            defects.append(
                f"{label}_DUPLICATE_TRADE_DECISION@{key[0].isoformat()}|{key[1]}"
            )
        result[key] = row
    return result, tuple(sorted(set(defects)))


def _load_action_events(path: Path, *, replay_end: date) -> tuple[ActionEvent, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("records", payload.get("data", []))
    if not isinstance(payload, list):
        raise ValueError("corporate action artifact must contain records")
    events: list[ActionEvent] = []
    for raw in payload:
        if not isinstance(raw, dict):
            raise ValueError("corporate action record must contain a mapping")
        if str(raw.get("status") or "").strip().upper() != "RESOLVED":
            continue
        effective = _date_value(raw.get("effective_date"), "action effective date")
        if effective > replay_end:
            continue
        symbols = frozenset(
            _symbol(value, "action symbol")
            for value in (
                raw.get("symbol"),
                raw.get("old_symbol"),
                raw.get("new_symbol"),
            )
            if value is not None and str(value).strip()
        )
        if not symbols:
            continue
        action_type = str(raw.get("action_type") or "").strip().upper()
        if not action_type:
            raise ValueError("resolved corporate action is missing action_type")
        events.append(
            ActionEvent(
                action_type=action_type,
                effective_date=effective,
                symbols=symbols,
            )
        )
    return tuple(
        sorted(
            events,
            key=lambda item: (
                item.effective_date,
                item.action_type,
                tuple(sorted(item.symbols)),
            ),
        )
    )


def _affecting_action_types(
    actions: tuple[ActionEvent, ...],
    *,
    symbol: str,
    observed_on: date,
    replay_end: date,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                item.action_type
                for item in actions
                if symbol in item.symbols
                and observed_on < item.effective_date <= replay_end
            }
        )
    )


def _curve_metrics(
    rows: tuple[dict[str, str], ...],
    start: date,
    end: date,
) -> dict[str, Decimal | None]:
    selected = tuple(
        row
        for row in rows
        if start <= _date_value(row.get("observed_on"), "capital curve date") <= end
    )
    if len(selected) < 2:
        return {"return_percent": None, "maximum_drawdown_percent": None}
    opening = _decimal(selected[0].get("portfolio_value"), "opening portfolio value")
    closing = _decimal(selected[-1].get("portfolio_value"), "closing portfolio value")
    returns = None if opening <= 0 else _quantize((closing / opening - 1) * 100)
    drawdowns = tuple(
        abs(_decimal(row.get("drawdown_percent"), "drawdown percent"))
        for row in selected
    )
    return {
        "return_percent": returns,
        "maximum_drawdown_percent": max(drawdowns, default=Decimal("0")),
    }


def _in_cohort(row: Mapping[str, object], cohort: str) -> bool:
    if cohort == "ALL":
        return True
    if row.get("action_cohort") == cohort:
        return True
    if cohort.startswith("ACTION_TYPE:"):
        action_type = cohort.split(":", 1)[1]
        return action_type in cast(tuple[str, ...], row.get("action_types") or ())
    return False


def _optional_decimal_value(
    row: Mapping[str, object] | None,
    key: str,
) -> Decimal | None:
    if row is None:
        return None
    value = row.get(key)
    if value in (None, ""):
        return None
    return _decimal(value, key)


def _sum_optional(rows: Sequence[Mapping[str, object]], key: str) -> Decimal:
    return _quantize(
        sum(
            (
                value
                for row in rows
                if (value := _optional_decimal_value(row, key)) is not None
            ),
            Decimal("0"),
        )
    )


def _mean_optional(
    rows: Sequence[Mapping[str, object]],
    key: str,
) -> Decimal | None:
    values = tuple(
        value
        for row in rows
        if (value := _optional_decimal_value(row, key)) is not None
    )
    if not values:
        return None
    return _quantize(sum(values, Decimal("0")) / Decimal(len(values)))


def _difference(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return _quantize(left - right)


def _percent(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return _quantize(Decimal(numerator) * Decimal("100") / Decimal(denominator))


def _nested_mapping(payload: Mapping[str, object], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"artifact is missing mapping {key}")
    return {str(item_key): item for item_key, item in value.items()}


def _mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"artifact must contain a mapping: {path}")
    return {str(key): value for key, value in payload.items()}


def _csv_rows(path: Path) -> tuple[dict[str, str], ...]:
    if not path.is_file():
        raise ValueError(f"required benchmark artifact is missing: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


def _file_sha256(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"required artifact is missing: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest_mapping(value: dict[str, Any]) -> str:
    payload = dict(value)
    payload.pop("report_sha256", None)
    encoded = json.dumps(
        _json_ready(payload),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
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
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_ready(item) for item in value]
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


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"))


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
    if isinstance(value, (tuple, list, set, frozenset)):
        return "|".join(str(_csv_value(item)) for item in value)
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
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return path


def _markdown(report: Mapping[str, object]) -> str:
    raw = cast(Mapping[str, object], report["raw_funnel_summary"])
    adjusted = cast(Mapping[str, object], report["adjusted_funnel_summary"])
    trade = cast(Mapping[str, object], report["trade_pairing_summary"])
    blockers = cast(Sequence[object], report["readiness_blockers"])
    defects = cast(Sequence[object], report["implementation_defects"])
    lines = [
        "# HTR-010B4 Governed Trade-Formation Certification",
        "",
        f"- Readiness: `{report['readiness_decision']}`",
        f"- Replay Window: `{report['replay_start']}` to `{report['replay_end']}`",
        f"- Sessions: `{report['session_count']}`",
        f"- RAW Candidates: `{raw['candidate_count']}`",
        f"- ADJUSTED Candidates: `{adjusted['candidate_count']}`",
        f"- RAW Institutional Approvals: `{raw['institutional_approval_count']}`",
        "- ADJUSTED Institutional Approvals: "
        f"`{adjusted['institutional_approval_count']}`",
        f"- RAW Trades: `{raw['trade_count']}`",
        f"- ADJUSTED Trades: `{adjusted['trade_count']}`",
        f"- Paired Trades: `{trade['paired_trade_count']}`",
        f"- Zero-Trade Policy Consistent: `{report['zero_trade_policy_consistent']}`",
        f"- Research Scope: `{report['research_scope']}`",
        f"- Report SHA-256: `{report['report_sha256']}`",
        "- Active Replay Integration: `False`",
        "- Production Influence: `False`",
        "",
        "## Dominant Terminal Gates",
        "",
        f"- RAW: `{raw['dominant_terminal_gate']}` "
        f"(`{raw['dominant_terminal_gate_count']}` candidates)",
        f"- ADJUSTED: `{adjusted['dominant_terminal_gate']}` "
        f"(`{adjusted['dominant_terminal_gate_count']}` candidates)",
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
            "This certificate explains the frozen candidate-to-trade funnel without "
            "changing strategy thresholds, approval policy, portfolio policy, "
            "execution "
            "assumptions, or Historical Truth. A zero-trade result is accepted only as "
            "diagnostic evidence and does not enable trade research, live scoring, "
            "recommendations, execution, mutable learning, or production consumers.",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "B4_BLOCKED_DEFECT",
    "B4_BLOCKED_DIVERGENCE",
    "B4_BLOCKED_INSUFFICIENT",
    "B4_BLOCKED_ZERO",
    "B4_READY",
    "HTR010B4_CONTRACT_VERSION",
    "GovernedTradeFormationEngine",
    "GovernedTradeFormationResult",
    "export_governed_trade_formation",
    "validate_governed_trade_formation_certificate",
]
