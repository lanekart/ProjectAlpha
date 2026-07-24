"""Governed adjusted benchmark stability certification for HTR-010B3."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, cast

HTR010B3_CONTRACT_VERSION = "HTR-010B3-v1.0.0"
HTR010B3_ACTIVATION_CONTRACT_VERSION = "HTR-010B3-ACTIVATION-v1.0.0"
HTR010B2_CONTRACT_VERSION = "HTR-010B2-v1.0.0"

B3_READY = "READY_FOR_GOVERNED_ADJUSTED_RESEARCH_ACTIVATION"
B3_BLOCKED = "BLOCKED_BY_INSUFFICIENT_STABILITY_EVIDENCE"

STABILITY_WINDOW_COUNT = 4
MINIMUM_REPLAY_SESSIONS = 80
MINIMUM_WINDOW_SESSIONS = 20
RESEARCH_SCOPE = "GOVERNED_BENCHMARK_RESEARCH_ONLY"

ProgressCallback = Callable[[int, int, str], None]

_EXPECTED_BENCHMARK_ARTIFACTS = frozenset(
    {
        "approval_statistics.csv",
        "candidate_statistics.csv",
        "capital_curve.csv",
        "decision_eligibility.csv",
        "trade_log.csv",
    }
)


@dataclass(frozen=True, slots=True)
class BenchmarkBundle:
    """Verified benchmark artifact bundle required by the B3 certificate."""

    root: Path
    manifest: dict[str, Any]
    manifest_sha256: str
    candidate_rows: tuple[dict[str, str], ...]
    approval_rows: tuple[dict[str, str], ...]
    trade_rows: tuple[dict[str, str], ...]
    capital_rows: tuple[dict[str, str], ...]
    eligibility_rows: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """One deterministic decision row from a CABR approval artifact."""

    observed_on: date
    symbol: str
    approved: bool
    opportunity_score: Decimal
    final_signal: str
    primary_reason_code: str


@dataclass(frozen=True, slots=True)
class ActionEvent:
    """Resolved action metadata used only for retrospective cohort attribution."""

    action_type: str
    effective_date: date
    symbols: frozenset[str]


@dataclass(frozen=True, slots=True)
class StabilityWindow:
    """One balanced contiguous replay window used for stability evidence."""

    window_index: int
    start_date: date
    end_date: date
    sessions: int
    raw_candidates: int
    adjusted_candidates: int
    raw_approvals: int
    adjusted_approvals: int
    raw_portfolio_entries: int
    adjusted_portfolio_entries: int
    paired_decisions: int
    raw_only_decisions: int
    adjusted_only_decisions: int
    approval_flips: int
    signal_changes: int
    mean_absolute_score_delta: Decimal | None
    raw_portfolio_return_percent: Decimal | None
    adjusted_portfolio_return_percent: Decimal | None

    def as_dict(self) -> dict[str, object]:
        return cast(dict[str, object], _json_ready(asdict(self)))


@dataclass(frozen=True, slots=True)
class CohortStability:
    """Decision stability summary for one action-attribution cohort."""

    cohort: str
    raw_decisions: int
    adjusted_decisions: int
    paired_decisions: int
    raw_only_decisions: int
    adjusted_only_decisions: int
    approval_flips: int
    signal_changes: int
    reason_changes: int
    mean_absolute_score_delta: Decimal | None

    def as_dict(self) -> dict[str, object]:
        return cast(dict[str, object], _json_ready(asdict(self)))


@dataclass(frozen=True, slots=True)
class GovernedAdjustedStabilityResult:
    """Signed B3 report and deterministic supporting evidence rows."""

    report: dict[str, Any]
    activation_contract: dict[str, Any]
    windows: tuple[StabilityWindow, ...]
    cohorts: tuple[CohortStability, ...]
    decision_differences: tuple[dict[str, object], ...]
    trade_differences: tuple[dict[str, object], ...]
    paths: tuple[Path, ...]


class GovernedAdjustedStabilityEngine:
    """Certify B2 evidence stability and issue a research-only activation gate."""

    def run(
        self,
        *,
        b2_report: Path,
        raw_benchmark: Path,
        adjusted_benchmark: Path,
        corporate_action_artifact: Path,
        output: Path,
        progress: ProgressCallback | None = None,
    ) -> GovernedAdjustedStabilityResult:
        total_steps = 6
        _progress(progress, 1, total_steps, "Validating signed HTR-010B2 handoff")
        b2 = _validated_b2_report(b2_report)

        _progress(progress, 2, total_steps, "Verifying RAW benchmark artifacts")
        raw = _load_benchmark_bundle(raw_benchmark)
        _validate_bundle_against_summary(raw, _nested_mapping(b2, "raw_summary"))

        _progress(progress, 3, total_steps, "Verifying ADJUSTED benchmark artifacts")
        adjusted = _load_benchmark_bundle(adjusted_benchmark)
        _validate_bundle_against_summary(
            adjusted,
            _nested_mapping(b2, "adjusted_summary"),
        )
        dates, raw_candidates, adjusted_candidates = _paired_candidate_sessions(
            raw,
            adjusted,
        )

        _progress(progress, 4, total_steps, "Pairing decisions and action cohorts")
        actions = _load_action_events(
            corporate_action_artifact,
            replay_end=dates[-1],
        )
        decision_rows = _decision_differences(
            raw.approval_rows,
            adjusted.approval_rows,
            actions=actions,
            replay_end=dates[-1],
        )
        trade_rows = _trade_differences(
            raw.trade_rows,
            adjusted.trade_rows,
            actions=actions,
            replay_end=dates[-1],
        )

        _progress(progress, 5, total_steps, "Building windows and cohort evidence")
        windows = _window_stability(
            dates=dates,
            raw_candidates=raw_candidates,
            adjusted_candidates=adjusted_candidates,
            decision_rows=decision_rows,
            raw_capital=raw.capital_rows,
            adjusted_capital=adjusted.capital_rows,
        )
        cohorts = _cohort_stability(decision_rows)
        blockers = _readiness_blockers(
            dates=dates,
            windows=windows,
            cohorts=cohorts,
            actions=actions,
        )
        readiness = B3_READY if not blockers else B3_BLOCKED
        enabled = readiness == B3_READY

        report: dict[str, Any] = {
            "contract_version": HTR010B3_CONTRACT_VERSION,
            "b2_report_sha256": str(b2["report_sha256"]),
            "b2_report_file_sha256": _file_sha256(b2_report),
            "raw_manifest_sha256": raw.manifest_sha256,
            "adjusted_manifest_sha256": adjusted.manifest_sha256,
            "corporate_action_artifact_sha256": _file_sha256(corporate_action_artifact),
            "replay_start": dates[0].isoformat(),
            "replay_end": dates[-1].isoformat(),
            "session_count": len(dates),
            "window_contract": {
                "window_count": STABILITY_WINDOW_COUNT,
                "minimum_replay_sessions": MINIMUM_REPLAY_SESSIONS,
                "minimum_window_sessions": MINIMUM_WINDOW_SESSIONS,
                "partition_method": "BALANCED_CONTIGUOUS_TRADING_SESSIONS",
            },
            "evidence_summary": _evidence_summary(
                decision_rows=decision_rows,
                trade_rows=trade_rows,
                actions=actions,
                raw=raw,
                adjusted=adjusted,
            ),
            "window_stability": [item.as_dict() for item in windows],
            "cohort_stability": [item.as_dict() for item in cohorts],
            "trade_stability": _trade_summary(trade_rows),
            "readiness_blockers": list(blockers),
            "readiness_decision": readiness,
            "stability_certified": enabled,
            "governed_adjusted_research_enabled": enabled,
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
        activation = _activation_contract(report)

        _progress(progress, 6, total_steps, "Exporting signed HTR-010B3 artifacts")
        paths = export_governed_adjusted_stability(
            report=report,
            activation_contract=activation,
            windows=windows,
            cohorts=cohorts,
            decision_differences=decision_rows,
            trade_differences=trade_rows,
            output=output,
        )
        return GovernedAdjustedStabilityResult(
            report=report,
            activation_contract=activation,
            windows=windows,
            cohorts=cohorts,
            decision_differences=decision_rows,
            trade_differences=trade_rows,
            paths=paths,
        )


def export_governed_adjusted_stability(
    *,
    report: dict[str, Any],
    activation_contract: dict[str, Any],
    windows: tuple[StabilityWindow, ...],
    cohorts: tuple[CohortStability, ...],
    decision_differences: tuple[dict[str, object], ...],
    trade_differences: tuple[dict[str, object], ...],
    output: Path,
) -> tuple[Path, ...]:
    """Write deterministic B3 certification and activation artifacts."""

    output.mkdir(parents=True, exist_ok=True)
    paths = (
        _write_json(output / "htr010b3_stability_certificate.json", report),
        _write_json(
            output / "htr010b3_research_activation_contract.json",
            activation_contract,
        ),
        _write_csv(
            output / "htr010b3_window_stability.csv",
            tuple(item.as_dict() for item in windows),
        ),
        _write_csv(
            output / "htr010b3_cohort_stability.csv",
            tuple(item.as_dict() for item in cohorts),
        ),
        _write_csv(
            output / "htr010b3_decision_differences.csv",
            decision_differences,
        ),
        _write_csv(
            output / "htr010b3_trade_differences.csv",
            trade_differences,
        ),
        _write_text(
            output / "htr010b3_executive_report.md",
            _markdown(report),
        ),
    )
    return paths


def validate_governed_adjusted_research_activation(
    *,
    stability_certificate: Path,
    activation_contract: Path,
) -> dict[str, Any]:
    """Validate the signed B3 gate before any adjusted research consumer runs."""

    certificate = _mapping(stability_certificate)
    activation = _mapping(activation_contract)
    if certificate.get("contract_version") != HTR010B3_CONTRACT_VERSION:
        raise ValueError("research activation requires the HTR-010B3 certificate")
    _validate_digest(certificate, "HTR-010B3 certificate")
    if activation.get("contract_version") != HTR010B3_ACTIVATION_CONTRACT_VERSION:
        raise ValueError("unsupported HTR-010B3 activation contract")
    _validate_digest(activation, "HTR-010B3 activation contract")
    if activation.get("stability_certificate_sha256") != certificate.get(
        "report_sha256"
    ):
        raise ValueError("activation contract does not match stability certificate")
    if certificate.get("readiness_decision") != B3_READY:
        raise ValueError("HTR-010B3 stability certificate is not ready")
    if certificate.get("governed_adjusted_research_enabled") is not True:
        raise ValueError("HTR-010B3 research activation is disabled")
    if activation.get("governed_adjusted_research_enabled") is not True:
        raise ValueError("HTR-010B3 activation contract is disabled")
    _validate_research_only_flags(certificate)
    _validate_research_only_flags(activation)
    return activation


def _validated_b2_report(path: Path) -> dict[str, Any]:
    payload = _mapping(path)
    if payload.get("contract_version") != HTR010B2_CONTRACT_VERSION:
        raise ValueError("B3 requires the HTR-010B2 benchmark contract")
    _validate_digest(payload, "HTR-010B2 benchmark report")
    if payload.get("readiness_decision") != (
        "READY_FOR_GOVERNED_ADJUSTED_BENCHMARK_RESEARCH"
    ):
        raise ValueError("HTR-010B2 does not permit stability certification")
    if payload.get("decision_metrics_evaluated") is not True:
        raise ValueError("HTR-010B2 decision metrics were not evaluated")
    if payload.get("governed_adjusted_benchmark_enabled") is not True:
        raise ValueError("HTR-010B2 benchmark research is not enabled")
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


def _load_benchmark_bundle(root: Path) -> BenchmarkBundle:
    manifest_path = root / "manifest.json"
    manifest = _mapping(manifest_path)
    if manifest.get("production_influence") is not False:
        raise ValueError(f"benchmark manifest permits production influence: {root}")
    if manifest.get("point_in_time_enforced") is not True:
        raise ValueError(f"benchmark manifest is not point-in-time enforced: {root}")
    if manifest.get("no_future_leakage") is not True:
        raise ValueError(f"benchmark manifest does not prohibit future leakage: {root}")
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
    return BenchmarkBundle(
        root=root,
        manifest=manifest,
        manifest_sha256=_file_sha256(manifest_path),
        candidate_rows=_csv_rows(root / "candidate_statistics.csv"),
        approval_rows=_csv_rows(root / "approval_statistics.csv"),
        trade_rows=_csv_rows(root / "trade_log.csv"),
        capital_rows=_csv_rows(root / "capital_curve.csv"),
        eligibility_rows=_csv_rows(root / "decision_eligibility.csv"),
    )


def _validate_bundle_against_summary(
    bundle: BenchmarkBundle,
    summary: dict[str, Any],
) -> None:
    sessions = _integer(bundle.manifest.get("sessions"), "manifest sessions")
    if sessions != _integer(summary.get("session_count"), "summary session count"):
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
    if len(bundle.trade_rows) != _integer(summary.get("trade_count"), "summary trades"):
        raise ValueError("trade artifact does not match B2 summary")
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
    ) != (
        _integer(
            summary.get("eligible_security_observation_count"),
            "summary eligible observations",
        )
    ):
        raise ValueError("eligible observation count does not match B2 summary")


def _paired_candidate_sessions(
    raw: BenchmarkBundle,
    adjusted: BenchmarkBundle,
) -> tuple[
    tuple[date, ...],
    dict[date, dict[str, str]],
    dict[date, dict[str, str]],
]:
    raw_map = _candidate_map(raw.candidate_rows, "RAW")
    adjusted_map = _candidate_map(adjusted.candidate_rows, "ADJUSTED")
    if tuple(raw_map) != tuple(adjusted_map):
        raise ValueError("RAW and ADJUSTED candidate session coverage differs")
    dates = tuple(raw_map)
    if not dates:
        raise ValueError("B3 candidate session population is empty")
    for bundle, label in ((raw, "RAW"), (adjusted, "ADJUSTED")):
        first = _date_value(bundle.manifest.get("replay_start"), f"{label} start")
        last = _date_value(bundle.manifest.get("replay_end"), f"{label} end")
        if first != dates[0] or last != dates[-1]:
            raise ValueError(
                f"{label} manifest window does not match candidate evidence"
            )
    return dates, raw_map, adjusted_map


def _candidate_map(
    rows: tuple[dict[str, str], ...],
    label: str,
) -> dict[date, dict[str, str]]:
    result: dict[date, dict[str, str]] = {}
    for row in rows:
        observed_on = _date_value(row.get("observed_on"), f"{label} observed_on")
        if observed_on in result:
            raise ValueError(f"{label} candidate artifact contains duplicate sessions")
        result[observed_on] = row
    return dict(sorted(result.items()))


def _decision_differences(
    raw_rows: tuple[dict[str, str], ...],
    adjusted_rows: tuple[dict[str, str], ...],
    *,
    actions: tuple[ActionEvent, ...],
    replay_end: date,
) -> tuple[dict[str, object], ...]:
    raw = _decision_map(raw_rows, "RAW")
    adjusted = _decision_map(adjusted_rows, "ADJUSTED")
    keys = tuple(sorted(set(raw).union(adjusted)))
    result: list[dict[str, object]] = []
    for observed_on, symbol in keys:
        raw_item = raw.get((observed_on, symbol))
        adjusted_item = adjusted.get((observed_on, symbol))
        action_types = _affecting_action_types(
            actions,
            symbol=symbol,
            observed_on=observed_on,
            replay_end=replay_end,
        )
        paired = raw_item is not None and adjusted_item is not None
        score_delta = (
            adjusted_item.opportunity_score - raw_item.opportunity_score
            if raw_item is not None and adjusted_item is not None
            else None
        )
        result.append(
            {
                "observed_on": observed_on,
                "symbol": symbol,
                "action_cohort": ("ACTION_AFFECTED" if action_types else "UNAFFECTED"),
                "action_types": action_types,
                "raw_present": raw_item is not None,
                "adjusted_present": adjusted_item is not None,
                "paired": paired,
                "raw_approved": None if raw_item is None else raw_item.approved,
                "adjusted_approved": (
                    None if adjusted_item is None else adjusted_item.approved
                ),
                "approval_changed": (
                    paired and raw_item.approved != adjusted_item.approved
                    if raw_item is not None and adjusted_item is not None
                    else False
                ),
                "raw_signal": None if raw_item is None else raw_item.final_signal,
                "adjusted_signal": (
                    None if adjusted_item is None else adjusted_item.final_signal
                ),
                "signal_changed": (
                    paired and raw_item.final_signal != adjusted_item.final_signal
                    if raw_item is not None and adjusted_item is not None
                    else False
                ),
                "raw_reason": (
                    None if raw_item is None else raw_item.primary_reason_code
                ),
                "adjusted_reason": (
                    None if adjusted_item is None else adjusted_item.primary_reason_code
                ),
                "reason_changed": (
                    paired
                    and raw_item.primary_reason_code
                    != adjusted_item.primary_reason_code
                    if raw_item is not None and adjusted_item is not None
                    else False
                ),
                "raw_score": (None if raw_item is None else raw_item.opportunity_score),
                "adjusted_score": (
                    None if adjusted_item is None else adjusted_item.opportunity_score
                ),
                "score_delta": score_delta,
                "absolute_score_delta": (
                    None if score_delta is None else abs(score_delta)
                ),
            }
        )
    return tuple(result)


def _decision_map(
    rows: tuple[dict[str, str], ...],
    label: str,
) -> dict[tuple[date, str], DecisionRecord]:
    result: dict[tuple[date, str], DecisionRecord] = {}
    for row in rows:
        record = DecisionRecord(
            observed_on=_date_value(row.get("observed_on"), f"{label} decision date"),
            symbol=_symbol(row.get("symbol"), f"{label} decision symbol"),
            approved=_boolean(row.get("approved"), f"{label} approved"),
            opportunity_score=_decimal(
                row.get("opportunity_score"),
                f"{label} opportunity score",
            ),
            final_signal=str(row.get("final_signal") or "").strip(),
            primary_reason_code=str(row.get("primary_reason_code") or "").strip(),
        )
        key = record.observed_on, record.symbol
        if key in result:
            raise ValueError(f"{label} approval artifact has duplicate decision keys")
        result[key] = record
    return result


def _trade_differences(
    raw_rows: tuple[dict[str, str], ...],
    adjusted_rows: tuple[dict[str, str], ...],
    *,
    actions: tuple[ActionEvent, ...],
    replay_end: date,
) -> tuple[dict[str, object], ...]:
    raw = _trade_map(raw_rows, "RAW")
    adjusted = _trade_map(adjusted_rows, "ADJUSTED")
    result: list[dict[str, object]] = []
    for trade_id in sorted(set(raw).union(adjusted)):
        raw_item = raw.get(trade_id)
        adjusted_item = adjusted.get(trade_id)
        reference = raw_item or adjusted_item
        if reference is None:
            continue
        symbol = _symbol(reference.get("symbol"), "trade symbol")
        decision_date = _date_value(
            reference.get("decision_date"),
            "trade decision date",
        )
        action_types = _affecting_action_types(
            actions,
            symbol=symbol,
            observed_on=decision_date,
            replay_end=replay_end,
        )
        raw_return = (
            None
            if raw_item is None
            else _decimal(raw_item.get("net_return_percent"), "RAW trade return")
        )
        adjusted_return = (
            None
            if adjusted_item is None
            else _decimal(
                adjusted_item.get("net_return_percent"),
                "ADJUSTED trade return",
            )
        )
        result.append(
            {
                "trade_id": trade_id,
                "symbol": symbol,
                "decision_date": decision_date,
                "action_cohort": ("ACTION_AFFECTED" if action_types else "UNAFFECTED"),
                "action_types": action_types,
                "raw_present": raw_item is not None,
                "adjusted_present": adjusted_item is not None,
                "paired": raw_item is not None and adjusted_item is not None,
                "raw_net_return_percent": raw_return,
                "adjusted_net_return_percent": adjusted_return,
                "net_return_delta": (
                    adjusted_return - raw_return
                    if raw_return is not None and adjusted_return is not None
                    else None
                ),
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
            }
        )
    return tuple(result)


def _trade_map(
    rows: tuple[dict[str, str], ...],
    label: str,
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        trade_id = str(row.get("trade_id") or "").strip()
        if not trade_id:
            raise ValueError(f"{label} trade artifact contains an empty trade_id")
        if trade_id in result:
            raise ValueError(f"{label} trade artifact contains duplicate trade_id")
        result[trade_id] = row
    return result


def _window_stability(
    *,
    dates: tuple[date, ...],
    raw_candidates: dict[date, dict[str, str]],
    adjusted_candidates: dict[date, dict[str, str]],
    decision_rows: tuple[dict[str, object], ...],
    raw_capital: tuple[dict[str, str], ...],
    adjusted_capital: tuple[dict[str, str], ...],
) -> tuple[StabilityWindow, ...]:
    partitions = _balanced_windows(dates, STABILITY_WINDOW_COUNT)
    raw_curve = _capital_map(raw_capital, "RAW")
    adjusted_curve = _capital_map(adjusted_capital, "ADJUSTED")
    result: list[StabilityWindow] = []
    for index, window_dates in enumerate(partitions, start=1):
        date_set = set(window_dates)
        decisions = tuple(
            row for row in decision_rows if cast(date, row["observed_on"]) in date_set
        )
        paired = tuple(row for row in decisions if bool(row["paired"]))
        absolute_deltas = tuple(
            cast(Decimal, row["absolute_score_delta"])
            for row in paired
            if row["absolute_score_delta"] is not None
        )
        result.append(
            StabilityWindow(
                window_index=index,
                start_date=window_dates[0],
                end_date=window_dates[-1],
                sessions=len(window_dates),
                raw_candidates=sum(
                    _integer(
                        raw_candidates[item].get("technical_candidates"),
                        "RAW window candidates",
                    )
                    for item in window_dates
                ),
                adjusted_candidates=sum(
                    _integer(
                        adjusted_candidates[item].get("technical_candidates"),
                        "ADJUSTED window candidates",
                    )
                    for item in window_dates
                ),
                raw_approvals=sum(
                    _integer(
                        raw_candidates[item].get("institutional_approvals"),
                        "RAW window approvals",
                    )
                    for item in window_dates
                ),
                adjusted_approvals=sum(
                    _integer(
                        adjusted_candidates[item].get("institutional_approvals"),
                        "ADJUSTED window approvals",
                    )
                    for item in window_dates
                ),
                raw_portfolio_entries=sum(
                    _integer(
                        raw_candidates[item].get("portfolio_entries"),
                        "RAW window entries",
                    )
                    for item in window_dates
                ),
                adjusted_portfolio_entries=sum(
                    _integer(
                        adjusted_candidates[item].get("portfolio_entries"),
                        "ADJUSTED window entries",
                    )
                    for item in window_dates
                ),
                paired_decisions=len(paired),
                raw_only_decisions=sum(
                    bool(row["raw_present"]) and not bool(row["adjusted_present"])
                    for row in decisions
                ),
                adjusted_only_decisions=sum(
                    bool(row["adjusted_present"]) and not bool(row["raw_present"])
                    for row in decisions
                ),
                approval_flips=sum(bool(row["approval_changed"]) for row in paired),
                signal_changes=sum(bool(row["signal_changed"]) for row in paired),
                mean_absolute_score_delta=_mean_decimal(absolute_deltas),
                raw_portfolio_return_percent=_window_return(raw_curve, window_dates),
                adjusted_portfolio_return_percent=_window_return(
                    adjusted_curve,
                    window_dates,
                ),
            )
        )
    return tuple(result)


def _cohort_stability(
    decision_rows: tuple[dict[str, object], ...],
) -> tuple[CohortStability, ...]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in decision_rows:
        grouped["ALL"].append(row)
        grouped[str(row["action_cohort"])].append(row)
        for action_type in cast(tuple[str, ...], row["action_types"]):
            grouped[f"ACTION_TYPE:{action_type}"].append(row)
    result: list[CohortStability] = []
    for cohort, rows in sorted(grouped.items()):
        paired = tuple(row for row in rows if bool(row["paired"]))
        absolute_deltas = tuple(
            cast(Decimal, row["absolute_score_delta"])
            for row in paired
            if row["absolute_score_delta"] is not None
        )
        result.append(
            CohortStability(
                cohort=cohort,
                raw_decisions=sum(bool(row["raw_present"]) for row in rows),
                adjusted_decisions=sum(bool(row["adjusted_present"]) for row in rows),
                paired_decisions=len(paired),
                raw_only_decisions=sum(
                    bool(row["raw_present"]) and not bool(row["adjusted_present"])
                    for row in rows
                ),
                adjusted_only_decisions=sum(
                    bool(row["adjusted_present"]) and not bool(row["raw_present"])
                    for row in rows
                ),
                approval_flips=sum(bool(row["approval_changed"]) for row in paired),
                signal_changes=sum(bool(row["signal_changed"]) for row in paired),
                reason_changes=sum(bool(row["reason_changed"]) for row in paired),
                mean_absolute_score_delta=_mean_decimal(absolute_deltas),
            )
        )
    return tuple(result)


def _readiness_blockers(
    *,
    dates: tuple[date, ...],
    windows: tuple[StabilityWindow, ...],
    cohorts: tuple[CohortStability, ...],
    actions: tuple[ActionEvent, ...],
) -> tuple[str, ...]:
    blockers: list[str] = []
    if len(dates) < MINIMUM_REPLAY_SESSIONS:
        blockers.append("INSUFFICIENT_REPLAY_SESSIONS")
    if len(windows) != STABILITY_WINDOW_COUNT:
        blockers.append("INCOMPLETE_WINDOW_PARTITION")
    if any(item.sessions < MINIMUM_WINDOW_SESSIONS for item in windows):
        blockers.append("INSUFFICIENT_WINDOW_SESSIONS")
    if any(item.paired_decisions == 0 for item in windows):
        blockers.append("WINDOW_WITHOUT_PAIRED_DECISIONS")
    by_name = {item.cohort: item for item in cohorts}
    if by_name.get("ALL") is None or by_name["ALL"].paired_decisions == 0:
        blockers.append("NO_PAIRED_DECISIONS")
    affected = by_name.get("ACTION_AFFECTED")
    if affected is None or affected.paired_decisions == 0:
        blockers.append("NO_ACTION_AFFECTED_DECISIONS")
    unaffected = by_name.get("UNAFFECTED")
    if unaffected is None or unaffected.paired_decisions == 0:
        blockers.append("NO_UNAFFECTED_DECISIONS")
    if not actions:
        blockers.append("NO_RESOLVED_ACTION_EVIDENCE")
    return tuple(sorted(set(blockers)))


def _evidence_summary(
    *,
    decision_rows: tuple[dict[str, object], ...],
    trade_rows: tuple[dict[str, object], ...],
    actions: tuple[ActionEvent, ...],
    raw: BenchmarkBundle,
    adjusted: BenchmarkBundle,
) -> dict[str, object]:
    paired = tuple(row for row in decision_rows if bool(row["paired"]))
    return {
        "resolved_action_event_count": len(actions),
        "raw_decision_count": len(raw.approval_rows),
        "adjusted_decision_count": len(adjusted.approval_rows),
        "paired_decision_count": len(paired),
        "raw_only_decision_count": sum(
            bool(row["raw_present"]) and not bool(row["adjusted_present"])
            for row in decision_rows
        ),
        "adjusted_only_decision_count": sum(
            bool(row["adjusted_present"]) and not bool(row["raw_present"])
            for row in decision_rows
        ),
        "action_affected_paired_decision_count": sum(
            bool(row["paired"]) and row["action_cohort"] == "ACTION_AFFECTED"
            for row in decision_rows
        ),
        "unaffected_paired_decision_count": sum(
            bool(row["paired"]) and row["action_cohort"] == "UNAFFECTED"
            for row in decision_rows
        ),
        "approval_flip_count": sum(bool(row["approval_changed"]) for row in paired),
        "signal_change_count": sum(bool(row["signal_changed"]) for row in paired),
        "reason_change_count": sum(bool(row["reason_changed"]) for row in paired),
        "raw_trade_count": len(raw.trade_rows),
        "adjusted_trade_count": len(adjusted.trade_rows),
        "paired_trade_count": sum(bool(row["paired"]) for row in trade_rows),
    }


def _trade_summary(rows: tuple[dict[str, object], ...]) -> dict[str, object]:
    paired = tuple(row for row in rows if bool(row["paired"]))
    deltas = tuple(
        cast(Decimal, row["net_return_delta"])
        for row in paired
        if row["net_return_delta"] is not None
    )
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
        "mean_net_return_delta": _mean_decimal(deltas),
    }


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
        status = str(raw.get("status") or "").strip().upper()
        if status != "RESOLVED":
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


def _balanced_windows(
    dates: tuple[date, ...],
    count: int,
) -> tuple[tuple[date, ...], ...]:
    if count < 1:
        raise ValueError("window count must be positive")
    if len(dates) < count:
        return tuple((item,) for item in dates)
    base, remainder = divmod(len(dates), count)
    result: list[tuple[date, ...]] = []
    offset = 0
    for index in range(count):
        size = base + (1 if index < remainder else 0)
        result.append(dates[offset : offset + size])
        offset += size
    return tuple(result)


def _capital_map(
    rows: tuple[dict[str, str], ...],
    label: str,
) -> dict[date, Decimal]:
    result: dict[date, Decimal] = {}
    for row in rows:
        observed_on = _date_value(row.get("observed_on"), f"{label} capital date")
        if observed_on in result:
            raise ValueError(f"{label} capital curve contains duplicate dates")
        result[observed_on] = _decimal(
            row.get("portfolio_value"),
            f"{label} portfolio value",
        )
    return result


def _window_return(
    curve: dict[date, Decimal],
    window_dates: tuple[date, ...],
) -> Decimal | None:
    values = tuple(curve[item] for item in window_dates if item in curve)
    if len(values) < 2 or values[0] <= 0:
        return None
    return _quantize((values[-1] / values[0] - Decimal("1")) * Decimal("100"))


def _activation_contract(report: dict[str, Any]) -> dict[str, Any]:
    enabled = report.get("readiness_decision") == B3_READY
    payload: dict[str, Any] = {
        "contract_version": HTR010B3_ACTIVATION_CONTRACT_VERSION,
        "stability_certificate_sha256": report["report_sha256"],
        "b2_report_sha256": report["b2_report_sha256"],
        "activation_decision": report["readiness_decision"],
        "governed_adjusted_research_enabled": enabled,
        "research_scope": RESEARCH_SCOPE,
        "allowed_consumers": [
            "BENCHMARK_RESEARCH",
            "DIAGNOSTIC_ANALYSIS",
            "STABILITY_REPORTING",
        ],
        "live_scoring_enabled": False,
        "recommendation_influence": False,
        "portfolio_policy_influence": False,
        "execution_influence": False,
        "learning_mutation_enabled": False,
        "active_replay_integration": False,
        "production_influence": False,
    }
    payload["report_sha256"] = _digest_mapping(payload)
    return payload


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


def _validate_digest(payload: dict[str, Any], label: str) -> None:
    expected = str(payload.get("report_sha256") or "")
    if len(expected) != 64 or expected != _digest_mapping(payload):
        raise ValueError(f"{label} digest mismatch")


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


def _mean_decimal(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return _quantize(sum(values, Decimal("0")) / Decimal(len(values)))


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
) -> Path:
    fieldnames = tuple(rows[0]) if rows else ("record",)
    from io import StringIO

    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_value(value) for key, value in row.items()})
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
    evidence = cast(Mapping[str, object], report["evidence_summary"])
    blockers = cast(Sequence[object], report["readiness_blockers"])
    lines = [
        "# HTR-010B3 Governed Adjusted Stability Certification",
        "",
        f"- Readiness: `{report['readiness_decision']}`",
        f"- Replay Window: `{report['replay_start']}` to `{report['replay_end']}`",
        f"- Sessions: `{report['session_count']}`",
        f"- Paired Decisions: `{evidence['paired_decision_count']}`",
        "- Action-Affected Paired Decisions: "
        f"`{evidence['action_affected_paired_decision_count']}`",
        f"- Approval Flips: `{evidence['approval_flip_count']}`",
        f"- Signal Changes: `{evidence['signal_change_count']}`",
        f"- Paired Trades: `{evidence['paired_trade_count']}`",
        f"- Research Scope: `{report['research_scope']}`",
        f"- Report SHA-256: `{report['report_sha256']}`",
        "- Active Replay Integration: `False`",
        "- Production Influence: `False`",
        "",
        "## Readiness Blockers",
        "",
    ]
    if blockers:
        lines.extend(f"- `{item}`" for item in blockers)
    else:
        lines.append("- `NONE`")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "This certificate permits adjusted prices only inside governed benchmark "
            "research and diagnostic analysis. It does not claim economic superiority "
            "and does not enable live scoring, recommendations, portfolio policy, "
            "execution, mutable learning, or production consumers.",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "B3_BLOCKED",
    "B3_READY",
    "HTR010B3_ACTIVATION_CONTRACT_VERSION",
    "HTR010B3_CONTRACT_VERSION",
    "GovernedAdjustedStabilityEngine",
    "GovernedAdjustedStabilityResult",
    "export_governed_adjusted_stability",
    "validate_governed_adjusted_research_activation",
]
