from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from alpha.application.intelligence import IntelligenceRun
from alpha.backtest.backtest_export_manifest import (
    BacktestExportArtifact,
    BacktestExportManifest,
)
from alpha.backtest.backtest_export_session import BacktestExportSession


@dataclass(frozen=True, slots=True)
class IntelligenceExportResult:
    """Immutable result describing persisted intelligence report outputs."""

    json_path: Path | None = None
    text_path: Path | None = None
    session: BacktestExportSession | None = None
    manifest: BacktestExportManifest = field(
        default_factory=lambda: BacktestExportManifest(())
    )

    def __post_init__(self) -> None:
        artifacts: list[BacktestExportArtifact] = []

        if self.json_path is not None:
            artifacts.append(BacktestExportArtifact(kind="json", path=self.json_path))

        if self.text_path is not None:
            artifacts.append(BacktestExportArtifact(kind="text", path=self.text_path))

        manifest = BacktestExportManifest(artifacts, session=self.session)
        object.__setattr__(self, "manifest", manifest)

    @property
    def wrote_any(self) -> bool:
        return not self.manifest.is_empty


@dataclass(frozen=True, slots=True)
class IntelligenceExportService:
    """Persist deterministic intelligence recommendation report outputs."""

    def export(
        self,
        run: IntelligenceRun,
        *,
        json_path: Path | None = None,
        text_path: Path | None = None,
    ) -> IntelligenceExportResult:
        written_json_path: Path | None = None
        written_text_path: Path | None = None

        if json_path is not None:
            written_json_path = self.write_json(run, json_path)

        if text_path is not None:
            written_text_path = self.write_text(run, text_path)

        return IntelligenceExportResult(
            json_path=written_json_path,
            text_path=written_text_path,
            session=self._session_from_run(run),
        )

    def write_json(
        self,
        run: IntelligenceRun,
        path: Path,
        *,
        indent: int | None = 2,
    ) -> Path:
        self._ensure_supported_path(path=path, expected_suffix=".json")
        self._ensure_parent_directory(path)
        path.write_text(
            json.dumps(
                self._payload(run),
                indent=indent,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return path

    def write_text(self, run: IntelligenceRun, path: Path) -> Path:
        self._ensure_supported_path(path=path, expected_suffix=".txt")
        self._ensure_parent_directory(path)
        content = "\n".join(self._text_lines(run))
        path.write_text(f"{content}\n", encoding="utf-8")
        return path

    def _payload(self, run: IntelligenceRun) -> dict[str, Any]:
        return {
            "kind": "recommendation_report",
            "observed_on": run.observed_on.isoformat(),
            "market": {
                "symbol": run.market_report.symbol,
                "bias": run.market_report.bias.value,
                "composite_score": self._decimal(run.market_report.composite_score),
            },
            "recommendations": [
                self._recommendation_payload(recommendation)
                for recommendation in run.recommendations
            ],
        }

    def _recommendation_payload(self, recommendation: Any) -> dict[str, Any]:
        breakdown = recommendation.score_breakdown
        expected_value = recommendation.expected_value
        allocation = recommendation.allocation
        opportunity_cost = recommendation.opportunity_cost

        return {
            "symbol": recommendation.symbol,
            "observed_on": recommendation.observed_on.isoformat(),
            "action": recommendation.action.value,
            "decision": recommendation.decision.value,
            "score": self._decimal(recommendation.score),
            "score_breakdown": {
                "strategy_points": self._decimal(breakdown.strategy_points),
                "probability_points": self._decimal(breakdown.probability_points),
                "market_intelligence_points": self._decimal(
                    breakdown.market_intelligence_points
                ),
                "liquidity_points": self._decimal(breakdown.liquidity_points),
                "risk_points": self._decimal(breakdown.risk_points),
                "portfolio_adjustment_points": self._decimal(
                    breakdown.portfolio_adjustment_points
                ),
                "opportunity_cost_points": self._decimal(
                    breakdown.opportunity_cost_points
                ),
                "gross_points": self._decimal(breakdown.gross_points),
                "total_points": self._decimal(breakdown.total_points),
            },
            "expected_value": {
                "expected_return": self._decimal(expected_value.expected_return),
                "expected_drawdown": self._decimal(expected_value.expected_drawdown),
                "reward_to_risk": self._decimal(expected_value.reward_to_risk),
                "expected_holding_period_days": self._decimal(
                    expected_value.expected_holding_period_days
                ),
                "score": self._decimal(expected_value.score),
                "reasons": list(expected_value.reasons),
            },
            "opportunity_cost": {
                "rank": opportunity_cost.rank,
                "candidate_count": opportunity_cost.candidate_count,
                "percentile": self._decimal(opportunity_cost.percentile),
                "opportunity_cost_points": self._decimal(
                    opportunity_cost.opportunity_cost_points
                ),
                "reasons": list(opportunity_cost.reasons),
                "better_candidates": [
                    {
                        "symbol": candidate.symbol,
                        "score": self._decimal(candidate.score),
                        "expected_return": self._decimal(candidate.expected_return),
                        "expected_drawdown": self._decimal(candidate.expected_drawdown),
                        "rank": candidate.rank,
                    }
                    for candidate in opportunity_cost.better_candidates
                ],
            },
            "allocation": {
                "base_allocation_percent": self._decimal(
                    allocation.base_allocation_percent
                ),
                "adjusted_allocation_percent": self._decimal(
                    allocation.adjusted_allocation_percent
                ),
                "adjustment_points": self._decimal(allocation.adjustment_points),
                "reasons": list(allocation.reasons),
            },
            "supporting_evidence": [
                {
                    "label": evidence.label,
                    "score_points": self._decimal(evidence.score_points),
                    "max_points": self._decimal(evidence.max_points),
                    "score_ratio": self._decimal(evidence.score_ratio),
                    "rationale": evidence.rationale,
                }
                for evidence in recommendation.supporting_evidence
            ],
            "opposing_evidence": [
                {
                    "label": risk.label,
                    "penalty_points": self._decimal(risk.penalty_points),
                    "rationale": risk.rationale,
                }
                for risk in recommendation.opposing_evidence
            ],
            "explanation": list(recommendation.explanation),
            "metadata": dict(recommendation.metadata),
        }

    def _text_lines(self, run: IntelligenceRun) -> tuple[str, ...]:
        lines = [
            "Project Alpha Recommendation Report",
            "",
            f"Observed On      : {run.observed_on.isoformat()}",
            f"Market Symbol    : {run.market_report.symbol}",
            f"Market Bias      : {run.market_report.bias.value}",
            f"Composite Score  : {run.market_report.composite_score}",
            "",
            "Recommendations:",
        ]

        for index, recommendation in enumerate(run.recommendations, start=1):
            lines.extend(
                (
                    f"{index}. {recommendation.symbol}",
                    f"   Action       : {recommendation.action.value}",
                    f"   Decision     : {recommendation.decision.value}",
                    f"   Score        : {recommendation.score}",
                    "   Allocation   : "
                    f"{recommendation.allocation.adjusted_allocation_percent}%",
                    "   Expected Ret : "
                    f"{recommendation.expected_value.expected_return}",
                    "   Drawdown     : "
                    f"{recommendation.expected_value.expected_drawdown}",
                    "   Evidence:",
                )
            )
            lines.extend(
                f"   - {evidence.label}: {evidence.rationale}"
                for evidence in recommendation.supporting_evidence
            )
            if recommendation.opposing_evidence:
                lines.append("   Risks:")
                lines.extend(
                    f"   - {risk.label}: {risk.rationale}"
                    for risk in recommendation.opposing_evidence
                )
            lines.append("   Explanation:")
            lines.extend(f"   - {line}" for line in recommendation.explanation)

        return tuple(lines)

    def _session_from_run(self, run: IntelligenceRun) -> BacktestExportSession:
        return BacktestExportSession(
            strategy="recommendation-intelligence",
            start=run.observed_on.isoformat(),
            end=run.observed_on.isoformat(),
        )

    def _ensure_supported_path(self, *, path: Path, expected_suffix: str) -> None:
        if path.suffix.lower() != expected_suffix:
            raise ValueError(f"expected {expected_suffix} output path")

    def _ensure_parent_directory(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

    def _decimal(self, value: Decimal) -> str:
        return str(value)


__all__ = ["IntelligenceExportResult", "IntelligenceExportService"]
