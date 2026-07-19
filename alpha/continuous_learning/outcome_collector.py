from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation
from hashlib import sha256

from alpha.continuous_learning.models import (
    LearningOutcomeStatus,
    OutcomeObservation,
)
from alpha.forward_validation.models import (
    PositionEvent,
    PositionEventType,
    RecommendationSnapshot,
)
from alpha.performance_intelligence.models import (
    RecommendationLedgerEntry,
    RecommendationOutcome,
)


class OutcomeCollector:
    """Normalize immutable recommendation evidence without inferring outcomes."""

    def collect(
        self,
        *,
        entries: tuple[RecommendationLedgerEntry, ...],
        outcomes: tuple[RecommendationOutcome, ...],
        snapshots: tuple[RecommendationSnapshot, ...],
        events: tuple[PositionEvent, ...],
    ) -> tuple[OutcomeObservation, ...]:
        outcome_by_id = {item.recommendation_id: item for item in outcomes}
        observations = [
            self._from_ledger(entry, outcome_by_id.get(entry.recommendation_id))
            for entry in entries
        ]
        ledger_ids = {item.recommendation_id for item in entries}
        events_by_id: dict[str, list[PositionEvent]] = {}
        for event in events:
            events_by_id.setdefault(event.recommendation_id, []).append(event)
        observations.extend(
            self._from_forward(
                snapshot, tuple(events_by_id.get(snapshot.recommendation_id, ()))
            )
            for snapshot in snapshots
            if snapshot.recommendation_id not in ledger_ids
        )
        return tuple(
            sorted(
                observations,
                key=lambda item: (
                    item.observed_at,
                    item.symbol,
                    item.recommendation_id,
                    item.observation_id,
                ),
            )
        )

    def _from_ledger(
        self,
        entry: RecommendationLedgerEntry,
        outcome: RecommendationOutcome | None,
    ) -> OutcomeObservation:
        status = _ledger_status(outcome)
        observed_at = entry.generated_at
        if outcome is not None and outcome.exit_date is not None:
            observed_at = datetime.combine(outcome.exit_date, time.min, tzinfo=UTC)
        features = dict(entry.key_indicator_snapshot)
        payload = {
            "recommendation_id": entry.recommendation_id,
            "status": status.value,
            "entry": False if outcome is None else outcome.entry_triggered,
            "stop": False if outcome is None else outcome.stop_hit,
            "targets": []
            if outcome is None
            else [outcome.target_1_hit, outcome.target_2_hit, outcome.target_3_hit],
            "return": None
            if outcome is None
            else _text(outcome.realized_percent_return),
        }
        observation_id = _hash(payload)
        return OutcomeObservation(
            observation_id=observation_id,
            recommendation_id=entry.recommendation_id,
            observed_at=observed_at,
            generated_at=entry.generated_at,
            symbol=entry.symbol,
            final_verdict=entry.final_verdict,
            predicted_confidence=entry.confidence,
            predicted_score=entry.score,
            setup_type=entry.setup_type or "UNCLASSIFIED",
            status=status,
            entry_achieved=False if outcome is None else outcome.entry_triggered,
            entry_missed=(
                False
                if outcome is None
                else outcome.status.value in {"not_triggered", "expired"}
                and not outcome.entry_triggered
            ),
            stop_hit=False if outcome is None else outcome.stop_hit,
            target_1_hit=False if outcome is None else outcome.target_1_hit,
            target_2_hit=False if outcome is None else outcome.target_2_hit,
            target_3_hit=False if outcome is None else outcome.target_3_hit,
            time_exit=(
                False if outcome is None else outcome.exit_reason.value == "expired"
            ),
            mfe_pct=(None if outcome is None else outcome.maximum_favorable_excursion),
            mae_pct=(None if outcome is None else outcome.maximum_adverse_excursion),
            realised_return_pct=(
                None if outcome is None else outcome.realized_percent_return
            ),
            holding_period_days=(
                None if outcome is None else outcome.holding_period_days
            ),
            market_regime=entry.market_regime,
            sector=entry.sector,
            volatility=_first_decimal(features, "atr", "atr_value", "volatility"),
            liquidity=_first_decimal(
                features,
                "average_traded_value",
                "average_volume",
                "volume",
                "capacity_score",
            ),
            source="recommendation_performance_ledger",
            evidence_hash=_hash(entry.as_dict()),
        )

    def _from_forward(
        self,
        snapshot: RecommendationSnapshot,
        events: tuple[PositionEvent, ...],
    ) -> OutcomeObservation:
        ordered = tuple(
            sorted(events, key=lambda item: (item.occurred_at, item.sequence))
        )
        entry = next(
            (item for item in ordered if item.event_type is PositionEventType.ENTRY),
            None,
        )
        latest = ordered[-1] if ordered else None
        terminal = next(
            (
                item
                for item in reversed(ordered)
                if item.event_type
                in {
                    PositionEventType.STOP_HIT,
                    PositionEventType.TARGET_3_HIT,
                    PositionEventType.TRAILING_STOP_HIT,
                    PositionEventType.TIME_EXIT,
                    PositionEventType.INVALIDATED,
                }
                or item.metadata.get("terminal") == "true"
            ),
            None,
        )
        realised = _forward_return(entry, terminal)
        status = _forward_status(ordered, entry, terminal)
        diagnostics = _flatten(snapshot.diagnostics)
        payload = {
            "snapshot_hash": snapshot.snapshot_hash,
            "event_head": None if latest is None else latest.event_hash,
            "status": status.value,
            "return": _text(realised),
        }
        return OutcomeObservation(
            observation_id=_hash(payload),
            recommendation_id=snapshot.recommendation_id,
            observed_at=(
                terminal.occurred_at
                if terminal is not None
                else latest.occurred_at
                if latest is not None
                else snapshot.generated_at
            ),
            generated_at=snapshot.generated_at,
            symbol=snapshot.symbol,
            final_verdict=snapshot.final_verdict,
            predicted_confidence=snapshot.confidence,
            predicted_score=snapshot.recommendation_score,
            setup_type=str(diagnostics.get("setup_type", "UNCLASSIFIED")),
            status=status,
            entry_achieved=entry is not None,
            entry_missed=any(
                item.event_type is PositionEventType.ENTRY_MISSED for item in ordered
            ),
            stop_hit=any(
                item.event_type is PositionEventType.STOP_HIT for item in ordered
            ),
            target_1_hit=any(
                item.event_type is PositionEventType.TARGET_1_HIT for item in ordered
            ),
            target_2_hit=any(
                item.event_type is PositionEventType.TARGET_2_HIT for item in ordered
            ),
            target_3_hit=any(
                item.event_type is PositionEventType.TARGET_3_HIT for item in ordered
            ),
            time_exit=any(
                item.event_type is PositionEventType.TIME_EXIT for item in ordered
            ),
            mfe_pct=_event_decimal(ordered, "mfe_pct"),
            mae_pct=_event_decimal(ordered, "mae_pct"),
            realised_return_pct=realised,
            holding_period_days=(
                None
                if entry is None or terminal is None
                else max(
                    0, (terminal.occurred_at.date() - entry.occurred_at.date()).days
                )
            ),
            market_regime=snapshot.market_regime,
            sector=snapshot.sector,
            volatility=snapshot.atr_value,
            liquidity=_first_decimal(
                diagnostics,
                "average_traded_value",
                "average_volume",
                "capacity_score",
            ),
            source="forward_validation_registry",
            evidence_hash=snapshot.snapshot_hash,
        )


def _ledger_status(outcome: RecommendationOutcome | None) -> LearningOutcomeStatus:
    if outcome is None:
        return LearningOutcomeStatus.PENDING
    return LearningOutcomeStatus(outcome.status.value.upper())


def _forward_status(
    events: tuple[PositionEvent, ...],
    entry: PositionEvent | None,
    terminal: PositionEvent | None,
) -> LearningOutcomeStatus:
    if terminal is not None:
        return LearningOutcomeStatus.EXITED
    if entry is not None:
        return LearningOutcomeStatus.ACTIVE
    if any(item.event_type is PositionEventType.ENTRY_MISSED for item in events):
        return LearningOutcomeStatus.NOT_TRIGGERED
    if any(item.event_type is PositionEventType.MANUAL_EXPIRY for item in events):
        return LearningOutcomeStatus.EXPIRED
    return LearningOutcomeStatus.PENDING


def _forward_return(
    entry: PositionEvent | None,
    terminal: PositionEvent | None,
) -> Decimal | None:
    if (
        entry is None
        or terminal is None
        or entry.price is None
        or terminal.price is None
        or entry.price <= Decimal("0")
    ):
        return None
    return ((terminal.price - entry.price) / entry.price * Decimal("100")).quantize(
        Decimal("0.01")
    )


def _event_decimal(events: tuple[PositionEvent, ...], key: str) -> Decimal | None:
    for event in reversed(events):
        value = _decimal(event.metadata.get(key))
        if value is not None:
            return value
    return None


def _first_decimal(values: Mapping[str, object], *keys: str) -> Decimal | None:
    lowered = {str(key).lower(): value for key, value in values.items()}
    for key in keys:
        value = _decimal(lowered.get(key.lower()))
        if value is not None:
            return value
    return None


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        return None


def _flatten(value: object, prefix: str = "") -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, object] = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, dict):
            result.update(_flatten(item, name))
            result[str(key)] = item
        else:
            result[name] = item
            result[str(key)] = item
    return result


def _hash(payload: object) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


__all__ = ["OutcomeCollector"]
