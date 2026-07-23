"""Governed raw-versus-adjusted shadow replay for HTR-010B1 final closure."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

HTR010B1_SHADOW_CONTRACT_VERSION = "HTR-010B1-SHADOW-v1.0.0"


class ReplayRunLike(Protocol):
    replay_date: date
    symbols_scanned: int
    candidates_stored: int
    emitted_decisions: int
    approved_recommendations: int
    data_gaps: int


ReplayLeg = Callable[[], tuple[ReplayRunLike, ...]]


@dataclass(frozen=True, slots=True)
class B1ShadowReplayResult:
    raw_summary: dict[str, Any]
    adjusted_summary: dict[str, Any]
    comparison: dict[str, Any]
    contract_version: str = HTR010B1_SHADOW_CONTRACT_VERSION

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "contract_version": self.contract_version,
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

    def run(self) -> B1ShadowReplayResult:
        raw = _summary("RAW", self.raw_leg())
        adjusted = _summary("ADJUSTED", self.adjusted_leg())
        return B1ShadowReplayResult(
            raw_summary=raw,
            adjusted_summary=adjusted,
            comparison=_compare(raw, adjusted),
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


def _summary(price_view: str, runs: tuple[ReplayRunLike, ...]) -> dict[str, Any]:
    replay_dates = tuple(sorted({run.replay_date.isoformat() for run in runs}))
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
        "eligible_security_count": max(
            (int(run.symbols_scanned) for run in runs),
            default=0,
        ),
        "technical_candidate_count": sum(int(run.candidates_stored) for run in runs),
        "buy_candidate_count": sum(int(run.emitted_decisions) for run in runs),
        "institutional_approval_count": sum(
            int(run.approved_recommendations) for run in runs
        ),
        "trade_count": sum(int(run.approved_recommendations) for run in runs),
        "data_gap_count": sum(int(run.data_gaps) for run in runs),
        "replay_dates": list(replay_dates),
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
        raise ValueError("raw and adjusted shadow legs must use distinct source contracts")
    metrics = (
        "session_count",
        "eligible_security_count",
        "technical_candidate_count",
        "buy_candidate_count",
        "institutional_approval_count",
        "trade_count",
        "data_gap_count",
    )
    deltas = {
        metric: int(adjusted.get(metric, 0)) - int(raw.get(metric, 0))
        for metric in metrics
    }
    unexplained = sum(
        deltas[metric] != 0
        for metric in ("session_count", "eligible_security_count")
    )
    return {
        "comparison_state": "COMPARED",
        "metric_deltas": deltas,
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
    lines = [
        "# HTR-010B1 Shadow Replay",
        "",
        f"- Raw sessions: {raw['session_count']}",
        f"- Adjusted sessions: {adjusted['session_count']}",
        f"- Unexplained divergences: {comparison['unexplained_divergence_count']}",
        f"- Report SHA-256: {report['report_sha256']}",
        "- PRODUCTION_INFLUENCE=false",
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "B1ShadowReplayResult",
    "B1ShadowReplayRunner",
    "HTR010B1_SHADOW_CONTRACT_VERSION",
    "ReplayLeg",
    "ReplayRunLike",
]
