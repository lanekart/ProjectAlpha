from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from typing import TYPE_CHECKING

from alpha import __version__
from alpha.forward_validation.models import PolicyVersion, RecommendationSnapshot
from alpha.forward_validation.validation_registry import canonical_json
from alpha.performance_intelligence.recorder import source_run_id

if TYPE_CHECKING:
    from alpha.application.runtime_models import RuntimeResult
    from alpha.recommendation_intelligence.models import RecommendationReport


class RecommendationSnapshotFactory:
    """Freeze runtime recommendations without recomputation or hindsight."""

    def build(
        self,
        runtime_result: RuntimeResult,
        *,
        policy_version: PolicyVersion,
        generated_at: datetime | None = None,
        source_run_id_override: str | None = None,
    ) -> tuple[RecommendationSnapshot, ...]:
        frozen_at = generated_at or runtime_result.metadata.completed_at
        if source_run_id_override is None:
            run_id = source_run_id(runtime_result)
            immutable_run_id = (
                f"{run_id}|{runtime_result.metadata.started_at.isoformat()}"
            )
        else:
            immutable_run_id = source_run_id_override.strip()
            if not immutable_run_id:
                raise ValueError("source run id override cannot be empty")
        allocation_by_symbol = {
            report.symbol: report
            for report in runtime_result.intelligence_run.allocation_plan.reports
        }
        market_payload = _freeze(runtime_result.intelligence_run.market_report)
        data_version = sha256(
            canonical_json(
                {
                    "observed_on": runtime_result.observed_on.isoformat(),
                    "market": market_payload,
                    "mode": runtime_result.mode.value,
                }
            ).encode()
        ).hexdigest()[:24]
        return tuple(
            self._build_one(
                recommendation=recommendation,
                generated_at=frozen_at,
                source_run_id=immutable_run_id,
                policy_version=policy_version,
                data_version=data_version,
                market_regime=runtime_result.intelligence_run.market_report.bias.value,
                market_payload=market_payload,
                allocation_report=allocation_by_symbol.get(recommendation.symbol),
            )
            for recommendation in runtime_result.intelligence_run.recommendations
        )

    def _build_one(
        self,
        *,
        recommendation: RecommendationReport,
        generated_at: datetime,
        source_run_id: str,
        policy_version: PolicyVersion,
        data_version: str,
        market_regime: str,
        market_payload: object,
        allocation_report: object | None,
    ) -> RecommendationSnapshot:
        diagnostics = {
            "market": market_payload,
            "score_breakdown": _freeze(recommendation.score_breakdown),
            "evidence_assessment": _freeze(recommendation.evidence_assessment),
            "trade_setup": _freeze(recommendation.trade_setup),
            "trade_plan": _freeze(recommendation.trade_plan),
            "supporting_evidence": _freeze(recommendation.supporting_evidence),
            "opposing_evidence": _freeze(recommendation.opposing_evidence),
            "explanation": list(recommendation.explanation),
            "metadata": dict(recommendation.metadata),
        }
        evidence_hashes = {
            key: sha256(canonical_json(value).encode()).hexdigest()
            for key, value in sorted(diagnostics.items())
        }
        recommendation_id = sha256(
            f"{source_run_id}|{recommendation.symbol}|{generated_at.isoformat()}".encode()
        ).hexdigest()[:24]
        approved_deployment = _approved_deployment(allocation_report)
        payload: dict[str, object] = {
            "recommendation_id": recommendation_id,
            "generated_at": generated_at.isoformat(),
            "source_run_id": source_run_id,
            "symbol": recommendation.symbol,
            "current_market_price": _text(recommendation.current_market_price),
            "final_verdict": recommendation.final_signal,
            "recommendation_score": str(recommendation.final_score),
            "confidence": recommendation.confidence,
            "entry_zone_low": _text(recommendation.entry_zone_low),
            "entry_zone_high": _text(recommendation.entry_zone_high),
            "confirmation_entry": _text(recommendation.trade_plan.confirmation_entry),
            "trigger_style": recommendation.trade_plan.entry_trigger_style.value,
            "trigger_status": recommendation.trade_plan.trigger_status.value,
            "stop_loss": _text(recommendation.initial_stop_loss),
            "target_1": _text(recommendation.target_1),
            "target_2": _text(recommendation.target_2),
            "target_3": _text(recommendation.target_3),
            "holding_period": recommendation.trade_plan.expected_holding_period,
            "maximum_holding_days": recommendation.trade_plan.maximum_holding_period,
            "risk_reward": _text(recommendation.risk_reward_ratio),
            "atr_value": _text(recommendation.trade_plan.atr_value),
            "dma_20": _text(recommendation.trade_plan.dma_20_invalidation),
            "trailing_stop_strategy": recommendation.trailing_stop_strategy,
            "invalidation_level": _text(recommendation.invalidation_level),
            "market_regime": market_regime,
            "sector": recommendation.metadata.get("sector"),
            "engine_version": __version__,
            "data_version": data_version,
            "policy_version": policy_version.value,
            "approved_deployment": _text(approved_deployment),
            "diagnostics": diagnostics,
            "evidence_hashes": evidence_hashes,
        }
        payload["snapshot_hash"] = sha256(canonical_json(payload).encode()).hexdigest()
        return RecommendationSnapshot.from_dict(payload)


def _approved_deployment(allocation_report: object | None) -> Decimal | None:
    if allocation_report is None:
        return None
    amount = getattr(allocation_report, "target_amount", None)
    if amount is None:
        return None
    normalized = Decimal(str(amount))
    return normalized if normalized > Decimal("0") else None


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _freeze(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _freeze(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_freeze(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _freeze(getattr(value, item.name)) for item in fields(value)}
    if hasattr(value, "as_dict"):
        return _freeze(value.as_dict())
    return str(value)


__all__ = ["RecommendationSnapshotFactory"]
