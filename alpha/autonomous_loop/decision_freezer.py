from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256

from alpha.application.runtime_models import RuntimeMode, RuntimeResult
from alpha.autonomous_loop.models import (
    DecisionKind,
    FrozenDecision,
    LoopEvidenceClass,
    ScheduleDefinition,
    UniverseDefinition,
    UniverseSource,
)
from alpha.autonomous_loop.registry import canonical_json
from alpha.forward_validation.models import PolicyVersion, RecommendationSnapshot
from alpha.forward_validation.recommendation_snapshot import (
    RecommendationSnapshotFactory,
)

_BLOCKED_DATA_QUALITY = frozenset(
    {"INVALID", "INCOMPLETE", "STALE", "UNAVAILABLE", "FAILED"}
)


class DecisionDataGate:
    """Fail closed when a scheduled runtime is stale, non-live, or malformed."""

    def reasons(
        self,
        runtime: RuntimeResult,
        *,
        as_of: date,
        maximum_age_days: int,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if runtime.mode is not RuntimeMode.LIVE:
            reasons.append("scheduled autonomous decisions require LIVE runtime mode")
        age = (as_of - runtime.observed_on).days
        if age < 0:
            reasons.append("runtime observation date is in the future")
        elif age > maximum_age_days:
            reasons.append(
                f"market data is stale by {age} days; maximum is {maximum_age_days}"
            )
        if runtime.status.value != "SUCCESS":
            reasons.append(f"runtime status is {runtime.status.value}")
        return tuple(reasons)


class ScheduledDecisionFreezer:
    """Freeze every scheduled recommendation, including blocked and no-trade rows."""

    def __init__(
        self,
        snapshot_factory: RecommendationSnapshotFactory | None = None,
        data_gate: DecisionDataGate | None = None,
    ) -> None:
        self.snapshot_factory = snapshot_factory or RecommendationSnapshotFactory()
        self.data_gate = data_gate or DecisionDataGate()

    def freeze(
        self,
        runtime: RuntimeResult,
        *,
        run_id: str,
        generated_at: datetime,
        as_of: date,
        schedule: ScheduleDefinition,
        universe: UniverseDefinition,
    ) -> tuple[tuple[RecommendationSnapshot, ...], tuple[FrozenDecision, ...], bool]:
        snapshots = self.snapshot_factory.build(
            runtime,
            policy_version=schedule.policy_version,
            generated_at=generated_at,
            source_run_id_override=run_id,
        )
        if universe.source is UniverseSource.EXPLICIT_SYMBOLS:
            allowed = frozenset(universe.symbols)
            snapshots = tuple(item for item in snapshots if item.symbol in allowed)
        global_reasons = self.data_gate.reasons(
            runtime,
            as_of=as_of,
            maximum_age_days=schedule.maximum_data_age_days,
        )
        decisions = tuple(
            self._decision(
                snapshot,
                run_id=run_id,
                schedule=schedule,
                universe=universe,
                observed_on=runtime.observed_on,
                global_reasons=global_reasons,
            )
            for snapshot in snapshots
        )
        if not decisions:
            decisions = (
                self._empty_decision(
                    run_id=run_id,
                    generated_at=generated_at,
                    observed_on=runtime.observed_on,
                    schedule=schedule,
                    universe=universe,
                    reasons=global_reasons
                    or ("runtime produced no recommendation for the universe",),
                ),
            )
        healthy = not global_reasons and all(
            item.decision_kind is not DecisionKind.DATA_BLOCKED for item in decisions
        )
        return snapshots, decisions, healthy

    def blocked_run(
        self,
        *,
        run_id: str,
        generated_at: datetime,
        observed_on: date,
        schedule: ScheduleDefinition,
        universe: UniverseDefinition,
        reason: str,
    ) -> FrozenDecision:
        return self._empty_decision(
            run_id=run_id,
            generated_at=generated_at,
            observed_on=observed_on,
            schedule=schedule,
            universe=universe,
            reasons=(reason,),
        )

    def _decision(
        self,
        snapshot: RecommendationSnapshot,
        *,
        run_id: str,
        schedule: ScheduleDefinition,
        universe: UniverseDefinition,
        observed_on: date,
        global_reasons: tuple[str, ...],
    ) -> FrozenDecision:
        quality = _nested_text(snapshot.diagnostics, "metadata", "data_quality")
        local_reasons = list(global_reasons)
        if quality is not None and quality.upper() in _BLOCKED_DATA_QUALITY:
            local_reasons.append(f"data quality is {quality.upper()}")
        if snapshot.current_market_price is None:
            local_reasons.append("current market price is unavailable")
        kind = _decision_kind(snapshot, bool(local_reasons))
        reasons = tuple(local_reasons) or _decision_reasons(snapshot, kind)
        payload: dict[str, object] = {
            "decision_id": _decision_id(run_id, snapshot.symbol),
            "run_id": run_id,
            "schedule_id": schedule.schedule_id,
            "universe_id": universe.universe_id,
            "recommendation_id": snapshot.recommendation_id,
            "generated_at": snapshot.generated_at.isoformat(),
            "observed_on": observed_on.isoformat(),
            "symbol": snapshot.symbol,
            "decision_kind": kind.value,
            "final_verdict": snapshot.final_verdict,
            "reference_price": _text(snapshot.current_market_price),
            "approved_deployment": _text(snapshot.approved_deployment),
            "policy_version": snapshot.policy_version.value,
            "markout_horizon_bars": schedule.markout_horizon_bars,
            "reasons": list(reasons),
            "feature_snapshot": _features(snapshot, kind),
            "evidence_hashes": dict(snapshot.evidence_hashes),
            "evidence_class": LoopEvidenceClass.FORWARD_OBSERVED.value,
            "production_influence": False,
        }
        payload["artifact_hash"] = sha256(canonical_json(payload).encode()).hexdigest()
        return _from_payload(payload)

    def _empty_decision(
        self,
        *,
        run_id: str,
        generated_at: datetime,
        observed_on: date,
        schedule: ScheduleDefinition,
        universe: UniverseDefinition,
        reasons: tuple[str, ...],
    ) -> FrozenDecision:
        symbol = f"UNIVERSE:{universe.universe_id}"
        payload: dict[str, object] = {
            "decision_id": _decision_id(run_id, symbol),
            "run_id": run_id,
            "schedule_id": schedule.schedule_id,
            "universe_id": universe.universe_id,
            "recommendation_id": None,
            "generated_at": generated_at.isoformat(),
            "observed_on": observed_on.isoformat(),
            "symbol": symbol,
            "decision_kind": DecisionKind.DATA_BLOCKED.value,
            "final_verdict": "NO_TRADE",
            "reference_price": None,
            "approved_deployment": None,
            "policy_version": schedule.policy_version.value,
            "markout_horizon_bars": schedule.markout_horizon_bars,
            "reasons": list(reasons),
            "feature_snapshot": {"universe": universe.universe_id},
            "evidence_hashes": {},
            "evidence_class": LoopEvidenceClass.FORWARD_OBSERVED.value,
            "production_influence": False,
        }
        payload["artifact_hash"] = sha256(canonical_json(payload).encode()).hexdigest()
        return _from_payload(payload)


def _decision_kind(
    snapshot: RecommendationSnapshot, data_blocked: bool
) -> DecisionKind:
    if data_blocked:
        return DecisionKind.DATA_BLOCKED
    verdict = snapshot.final_verdict.upper()
    if verdict in {"SELL", "STRONG_SELL", "AVOID", "REJECT"}:
        return DecisionKind.REJECTED
    if verdict in {"BUY", "STRONG_BUY"}:
        if snapshot.approved_deployment is not None:
            return DecisionKind.APPROVED_TRADE
        return DecisionKind.RISK_BLOCKED
    return DecisionKind.NO_TRADE


def _decision_reasons(
    snapshot: RecommendationSnapshot, kind: DecisionKind
) -> tuple[str, ...]:
    explanation = snapshot.diagnostics.get("explanation", [])
    reasons = (
        tuple(str(item) for item in explanation[:3])
        if isinstance(explanation, list)
        else ()
    )
    if reasons:
        return reasons
    return (f"frozen {kind.value.lower().replace('_', ' ')} decision",)


def _features(snapshot: RecommendationSnapshot, kind: DecisionKind) -> dict[str, str]:
    values = {
        "final_verdict": snapshot.final_verdict,
        "confidence": snapshot.confidence,
        "recommendation_score": str(snapshot.recommendation_score),
        "decision_kind": kind.value,
        "market_regime": snapshot.market_regime or "UNAVAILABLE",
        "sector": snapshot.sector or "UNAVAILABLE",
        "risk_reward": _text(snapshot.risk_reward) or "UNAVAILABLE",
        "atr": _text(snapshot.atr_value) or "UNAVAILABLE",
        "policy_version": snapshot.policy_version.value,
    }
    for path in (
        ("trade_plan", "setup_name"),
        ("trade_plan", "setup_stage"),
        ("trade_plan", "historical_bar_count"),
        ("metadata", "data_quality"),
    ):
        value = _nested_text(snapshot.diagnostics, *path)
        if value is not None:
            values[".".join(path)] = value
    return dict(sorted(values.items()))


def _nested_text(value: Mapping[str, object], *path: str) -> str | None:
    current: object = value
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    if current is None:
        return None
    return str(current)


def _decision_id(run_id: str, symbol: str) -> str:
    return sha256(f"{run_id}|{symbol.upper()}".encode()).hexdigest()[:24]


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _from_payload(payload: dict[str, object]) -> FrozenDecision:
    reasons_value = payload.get("reasons", [])
    reasons = reasons_value if isinstance(reasons_value, list) else []
    features_value = payload.get("feature_snapshot", {})
    features = features_value if isinstance(features_value, dict) else {}
    hashes_value = payload.get("evidence_hashes", {})
    hashes = hashes_value if isinstance(hashes_value, dict) else {}
    return FrozenDecision(
        decision_id=str(payload["decision_id"]),
        run_id=str(payload["run_id"]),
        schedule_id=str(payload["schedule_id"]),
        universe_id=str(payload["universe_id"]),
        recommendation_id=(
            None
            if payload.get("recommendation_id") is None
            else str(payload["recommendation_id"])
        ),
        generated_at=datetime.fromisoformat(str(payload["generated_at"])),
        observed_on=date.fromisoformat(str(payload["observed_on"])),
        symbol=str(payload["symbol"]),
        decision_kind=DecisionKind(str(payload["decision_kind"])),
        final_verdict=str(payload["final_verdict"]),
        reference_price=(
            None
            if payload.get("reference_price") is None
            else Decimal(str(payload["reference_price"]))
        ),
        approved_deployment=(
            None
            if payload.get("approved_deployment") is None
            else Decimal(str(payload["approved_deployment"]))
        ),
        policy_version=PolicyVersion(str(payload["policy_version"])),
        markout_horizon_bars=int(str(payload["markout_horizon_bars"])),
        reasons=tuple(str(item) for item in reasons),
        feature_snapshot={str(key): str(value) for key, value in features.items()},
        evidence_hashes={str(key): str(value) for key, value in hashes.items()},
        evidence_class=LoopEvidenceClass(str(payload["evidence_class"])),
        artifact_hash=str(payload["artifact_hash"]),
        production_influence=bool(payload.get("production_influence", False)),
    )


__all__ = ["DecisionDataGate", "ScheduledDecisionFreezer"]
