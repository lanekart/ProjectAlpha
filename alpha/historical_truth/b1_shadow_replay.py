"""Governed raw-versus-adjusted shadow replay for HTR-010B1 final closure."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

HTR010B1_SHADOW_CONTRACT_VERSION = "HTR-010B1-SHADOW-v1.2.0"


class ReplayRunLike(Protocol):
    """Read-only structural contract for immutable replay-run records."""

    @property
    def replay_date(self) -> date: ...

    @property
    def symbols_scanned(self) -> int: ...

    @property
    def candidates_stored(self) -> int: ...

    @property
    def emitted_decisions(self) -> int: ...

    @property
    def approved_recommendations(self) -> int: ...

    @property
    def data_gaps(self) -> int: ...


@dataclass(frozen=True, slots=True)
class B1ShadowReplayLegResult:
    """One shadow leg with source-session accounting independent of candidates."""

    runs: tuple[ReplayRunLike, ...]
    replay_dates: tuple[date, ...]
    eligible_security_count: int
    observation_count: int
    skipped_dates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.replay_dates != tuple(sorted(set(self.replay_dates))):
            raise ValueError("shadow replay dates must be sorted and unique")
        if self.eligible_security_count < 0:
            raise ValueError("eligible security count cannot be negative")
        if self.observation_count < 0:
            raise ValueError("observation count cannot be negative")
        replay_date_set = set(self.replay_dates)
        if any(run.replay_date not in replay_date_set for run in self.runs):
            raise ValueError("shadow replay run falls outside the source session set")


type ReplayLegValue = Sequence[ReplayRunLike] | B1ShadowReplayLegResult
type ReplayLeg = Callable[[], ReplayLegValue]


@dataclass(frozen=True, slots=True)
class B1ShadowReplayResult:
    raw_summary: dict[str, Any]
    adjusted_summary: dict[str, Any]
    comparison: dict[str, Any]
    admission_contract: dict[str, Any] = field(default_factory=dict)
    contract_version: str = HTR010B1_SHADOW_CONTRACT_VERSION

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "contract_version": self.contract_version,
            "admission_contract": self.admission_contract,
            "raw_summary": self.raw_summary,
            "adjusted_summary": self.adjusted_summary,
            "comparison": self.comparison,
            "production_influence": False,
        }
        payload["report_sha256"] = _digest(payload)
        return payload


@dataclass(slots=True)
class B1ShadowReplayRunner:
    raw_leg: ReplayLeg
    adjusted_leg: ReplayLeg
    admission_contract: dict[str, Any] = field(default_factory=dict)

    def run(self) -> B1ShadowReplayResult:
        raw = _summary("RAW", _leg_result(self.raw_leg()))
        adjusted = _summary("ADJUSTED", _leg_result(self.adjusted_leg()))
        return B1ShadowReplayResult(
            raw_summary=raw,
            adjusted_summary=adjusted,
            comparison=_compare(raw, adjusted),
            admission_contract=dict(self.admission_contract),
        )

    @staticmethod
    def export(result: B1ShadowReplayResult, output: Path) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        raw_path = output / "htr010b1_raw_shadow_summary.json"
        adjusted_path = output / "htr010b1_adjusted_shadow_summary.json"
        report_path = output / "htr010b1_shadow_replay_report.json"
        markdown_path = output / "htr010b1_shadow_replay_report.md"
        raw_path.write_text(
            json.dumps(result.raw_summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        adjusted_path.write_text(
            json.dumps(result.adjusted_summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report = result.as_dict()
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        markdown_path.write_text(_markdown(report), encoding="utf-8")
        return raw_path, adjusted_path, report_path, markdown_path


def _leg_result(value: ReplayLegValue) -> B1ShadowReplayLegResult:
    if isinstance(value, B1ShadowReplayLegResult):
        return value
    runs = tuple(value)
    replay_dates = tuple(sorted({run.replay_date for run in runs}))
    return B1ShadowReplayLegResult(
        runs=runs,
        replay_dates=replay_dates,
        eligible_security_count=max(
            (int(run.symbols_scanned) for run in runs),
            default=0,
        ),
        observation_count=sum(int(run.candidates_stored) for run in runs),
    )


def _summary(price_view: str, leg: B1ShadowReplayLegResult) -> dict[str, Any]:
    executed_dates = tuple(sorted({run.replay_date.isoformat() for run in leg.runs}))
    replay_dates = tuple(item.isoformat() for item in leg.replay_dates)
    source_contract = (
        "RAW_MARKET_TRUTH_REPOSITORY"
        if price_view == "RAW"
        else "HTR005_CANONICAL_REPLAY_REPOSITORY"
    )
    payload: dict[str, Any] = {
        "contract_version": HTR010B1_SHADOW_CONTRACT_VERSION,
        "price_view": price_view,
        "source_contract": source_contract,
        "session_count": len(replay_dates),
        "executed_session_count": len(executed_dates),
        "eligible_security_count": leg.eligible_security_count,
        "observation_count": leg.observation_count,
        "technical_candidate_count": sum(
            int(run.candidates_stored) for run in leg.runs
        ),
        "buy_candidate_count": sum(int(run.emitted_decisions) for run in leg.runs),
        "institutional_approval_count": sum(
            int(run.approved_recommendations) for run in leg.runs
        ),
        "trade_count": sum(int(run.approved_recommendations) for run in leg.runs),
        "data_gap_count": sum(int(run.data_gaps) for run in leg.runs),
        "skipped_date_count": len(leg.skipped_dates),
        "skipped_dates": list(leg.skipped_dates),
        "replay_dates": list(replay_dates),
        "executed_replay_dates": list(executed_dates),
        "production_influence": False,
    }
    payload["run_sha256"] = _digest(payload)
    return payload


def _compare(raw: dict[str, Any], adjusted: dict[str, Any]) -> dict[str, Any]:
    if raw.get("price_view") != "RAW":
        raise ValueError("raw shadow leg must attest RAW price view")
    if adjusted.get("price_view") != "ADJUSTED":
        raise ValueError("adjusted shadow leg must attest ADJUSTED price view")
    if raw.get("source_contract") == adjusted.get("source_contract"):
        raise ValueError(
            "raw and adjusted shadow legs must use distinct source contracts"
        )
    metrics = (
        "session_count",
        "executed_session_count",
        "eligible_security_count",
        "observation_count",
        "technical_candidate_count",
        "buy_candidate_count",
        "institutional_approval_count",
        "trade_count",
        "data_gap_count",
        "skipped_date_count",
    )
    deltas = {
        metric: int(adjusted.get(metric, 0)) - int(raw.get(metric, 0))
        for metric in metrics
    }
    session_sets_match = raw.get("replay_dates") == adjusted.get("replay_dates")
    executed_session_sets_match = raw.get("executed_replay_dates") == adjusted.get(
        "executed_replay_dates"
    )
    universe_counts_match = raw.get("eligible_security_count") == adjusted.get(
        "eligible_security_count"
    )
    skipped_dates_match = raw.get("skipped_dates") == adjusted.get("skipped_dates")
    replay_population_nonempty = (
        int(raw.get("session_count", 0)) > 0
        and int(adjusted.get("session_count", 0)) > 0
        and int(raw.get("eligible_security_count", 0)) > 0
        and int(adjusted.get("eligible_security_count", 0)) > 0
    )
    unexplained = (
        int(not session_sets_match)
        + int(not universe_counts_match)
        + int(not skipped_dates_match)
        + int(not replay_population_nonempty)
    )
    return {
        "comparison_state": "COMPARED",
        "metric_deltas": deltas,
        "session_sets_match": session_sets_match,
        "executed_session_sets_match": executed_session_sets_match,
        "universe_counts_match": universe_counts_match,
        "skipped_dates_match": skipped_dates_match,
        "replay_population_nonempty": replay_population_nonempty,
        "unexplained_divergence_count": unexplained,
        "raw_run_sha256": raw["run_sha256"],
        "adjusted_run_sha256": adjusted["run_sha256"],
        "source_contracts_distinct": True,
        "production_influence": False,
    }


def _digest(value: dict[str, Any]) -> str:
    payload = dict(value)
    payload.pop("report_sha256", None)
    payload.pop("run_sha256", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _markdown(report: dict[str, Any]) -> str:
    raw = report["raw_summary"]
    adjusted = report["adjusted_summary"]
    comparison = report["comparison"]
    admission = report.get("admission_contract", {})
    lines = [
        "# HTR-010B1 Shadow Replay",
        "",
        f"- Admitted identities: {admission.get('admitted_identity_count', 0)}",
        f"- Raw source sessions: {raw['session_count']}",
        f"- Adjusted source sessions: {adjusted['session_count']}",
        f"- Raw executed sessions: {raw['executed_session_count']}",
        f"- Adjusted executed sessions: {adjusted['executed_session_count']}",
        f"- Raw observations: {raw['observation_count']}",
        f"- Adjusted observations: {adjusted['observation_count']}",
        f"- Session sets match: {comparison['session_sets_match']}",
        (f"- Executed session sets match: {comparison['executed_session_sets_match']}"),
        f"- Universe counts match: {comparison['universe_counts_match']}",
        f"- Replay population nonempty: {comparison['replay_population_nonempty']}",
        f"- Unexplained divergences: {comparison['unexplained_divergence_count']}",
        f"- Report SHA-256: {report['report_sha256']}",
        "- PRODUCTION_INFLUENCE=false",
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "B1ShadowReplayLegResult",
    "B1ShadowReplayResult",
    "B1ShadowReplayRunner",
    "HTR010B1_SHADOW_CONTRACT_VERSION",
    "ReplayLeg",
    "ReplayRunLike",
]
