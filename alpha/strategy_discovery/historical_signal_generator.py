from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256

from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
    CandidateOutcomeLabel,
)
from alpha.candidate_learning.repository import LearningLedgerRepository
from alpha.forward_validation.approval_gate_optimizer import (
    ApprovalGateOptimizer,
    primary_window,
    record_reward_risk,
    record_stop_distance,
)
from alpha.strategy_discovery.feature_manifest import FeatureManifest
from alpha.strategy_discovery.models import (
    DISCOVERY_SCHEMA_VERSION,
    DiscoveryDataset,
    DiscoveryExclusion,
    DiscoveryRow,
    HistoricalTruthClass,
)


class HistoricalSignalGenerator:
    """Materialize point-in-time rows without exposing outcomes as features."""

    def __init__(
        self,
        *,
        repository: LearningLedgerRepository | None = None,
        feature_manifest: FeatureManifest | None = None,
        gate_optimizer: ApprovalGateOptimizer | None = None,
    ) -> None:
        self.repository = repository or LearningLedgerRepository()
        self.feature_manifest = feature_manifest or FeatureManifest()
        self.gate_optimizer = gate_optimizer or ApprovalGateOptimizer()

    def build(self) -> tuple[DiscoveryDataset, ...]:
        records = self.repository.load_records()
        outcomes = self.repository.load_outcomes()
        outcome_by_id = {item.candidate_id: item for item in outcomes}
        rows: dict[HistoricalTruthClass, list[DiscoveryRow]] = {
            HistoricalTruthClass.AUTHORITATIVE: [],
            HistoricalTruthClass.RECONSTRUCTED: [],
            HistoricalTruthClass.INSUFFICIENT: [],
        }
        exclusions: list[DiscoveryExclusion] = []
        quarantined_population = 0
        for record in records:
            outcome = outcome_by_id.get(record.candidate_id)
            window = primary_window(outcome)
            truth, reason = _truth_class(record, outcome, window)
            if truth is HistoricalTruthClass.INSUFFICIENT:
                exclusions.append(
                    DiscoveryExclusion(
                        candidate_id=record.candidate_id,
                        symbol=record.symbol,
                        reason_code=reason[0],
                        explanation=reason[1],
                    )
                )
                continue
            assert window is not None
            if record.indicator_scores.get("retracement") is not None:
                quarantined_population += 1
            row = self._row(record, outcome, truth)
            if set(row.features) - set(self.feature_manifest.usable_feature_names):
                raise ValueError(
                    "discovery row contains an undeclared or quarantined feature"
                )
            rows[truth].append(row)
        source_hash = _source_hash(records, outcomes)
        generated_at = max(
            (outcome.evaluated_at for outcome in outcomes),
            default=datetime.now(tz=UTC),
        )
        datasets: list[DiscoveryDataset] = []
        for truth in (
            HistoricalTruthClass.AUTHORITATIVE,
            HistoricalTruthClass.RECONSTRUCTED,
        ):
            ordered = tuple(
                sorted(
                    rows[truth],
                    key=lambda item: (
                        item.candidate_timestamp,
                        item.symbol,
                        item.candidate_id,
                    ),
                )
            )
            dataset_hash = sha256(
                json.dumps(
                    [row.as_dict() for row in ordered],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            datasets.append(
                DiscoveryDataset(
                    dataset_version=(
                        f"{DISCOVERY_SCHEMA_VERSION}-{truth.value.lower()}-"
                        f"{dataset_hash[:16]}"
                    ),
                    generated_at=generated_at,
                    source="candidate_learning_ledger",
                    source_hash=source_hash,
                    population_class=truth,
                    rows=ordered,
                    exclusions=tuple(exclusions),
                    quarantined_population=quarantined_population,
                )
            )
        return tuple(datasets)

    def discovery_dataset(self) -> DiscoveryDataset:
        datasets = self.build()
        reconstructed = next(
            item
            for item in datasets
            if item.population_class is HistoricalTruthClass.RECONSTRUCTED
        )
        authoritative = next(
            item
            for item in datasets
            if item.population_class is HistoricalTruthClass.AUTHORITATIVE
        )
        return authoritative if authoritative.row_count >= 30 else reconstructed

    def _row(
        self,
        record: CandidateDecisionRecord,
        outcome: CandidateForwardOutcome | None,
        truth: HistoricalTruthClass,
    ) -> DiscoveryRow:
        window = primary_window(outcome)
        assert window is not None
        stop_distance = record_stop_distance(record)
        realised_r = None
        if (
            stop_distance is not None
            and stop_distance > Decimal("0")
            and window.forward_return_pct_from_entry is not None
        ):
            realised_r = (
                window.forward_return_pct_from_entry / stop_distance
            ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        gates = {
            gate.gate_id: gate.predicate(record) for gate in self.gate_optimizer.gates
        }
        features = _features(record, stop_distance)
        return DiscoveryRow(
            candidate_id=record.candidate_id,
            candidate_timestamp=record.created_at,
            symbol=record.symbol,
            series=None,
            identity_status=(
                "PROVENANCE_LINKED"
                if record.decision_provenance_id is not None
                else "UNVERIFIED"
            ),
            feature_timestamp=record.created_at,
            recommendation=record.final_verdict,
            setup=record.setup_type,
            entry_timing_state=record.capital_action,
            approval_gate_states=gates,
            entry_zone_low=record.entry_zone_low,
            entry_zone_high=record.entry_zone_high,
            confirmation_entry=record.confirmation_entry,
            stop_loss=record.risk_stop,
            target_1=record.target_1,
            target_2=record.target_2,
            target_3=record.target_3,
            outcome_horizon=window.window,
            realised_outcome=window.outcome_label.value,
            mfe_pct=window.max_favourable_excursion_pct,
            mae_pct=window.max_adverse_excursion_pct,
            realised_return_pct=window.forward_return_pct_from_entry,
            realised_r_multiple=realised_r,
            evidence_provenance={
                "candidate_ledger_id": record.candidate_id,
                "decision_provenance_id": (
                    record.decision_provenance_id or "unavailable"
                ),
                "market_state_snapshot_id": (
                    record.market_state_snapshot_id or "unavailable"
                ),
                "outcome_evaluated_at": (
                    outcome.evaluated_at.isoformat() if outcome else "unavailable"
                ),
            },
            replay_version=record.classifier_version or "candidate-learning-v1",
            data_quality_status=record.data_quality,
            corporate_action_status="UNAVAILABLE_NOT_LINKED",
            truth_class=truth,
            features=features,
        )


def _truth_class(
    record: CandidateDecisionRecord,
    outcome: CandidateForwardOutcome | None,
    window: object | None,
) -> tuple[HistoricalTruthClass, tuple[str, str]]:
    if outcome is None or window is None:
        return (
            HistoricalTruthClass.INSUFFICIENT,
            ("OUTCOME_UNAVAILABLE", "No resolved primary forward outcome exists."),
        )
    if outcome.evaluated_at <= record.created_at:
        return (
            HistoricalTruthClass.INSUFFICIENT,
            ("TEMPORAL_ORDER_INVALID", "Outcome was not evaluated after the signal."),
        )
    typed_window = primary_window(outcome)
    if (
        typed_window is None
        or typed_window.outcome_label is CandidateOutcomeLabel.DATA_MISSING
        or typed_window.forward_return_pct_from_entry is None
    ):
        return (
            HistoricalTruthClass.INSUFFICIENT,
            ("RETURN_UNAVAILABLE", "The primary outcome has no realised return."),
        )
    if (
        record.market_state_as_of is not None
        and record.market_state_as_of > record.created_at
    ):
        return (
            HistoricalTruthClass.INSUFFICIENT,
            ("FEATURE_AFTER_DECISION", "A market-state feature follows the decision."),
        )
    authoritative = bool(
        record.decision_provenance_id and record.market_state_snapshot_id
    )
    return (
        HistoricalTruthClass.AUTHORITATIVE
        if authoritative
        else HistoricalTruthClass.RECONSTRUCTED,
        ("", ""),
    )


def _features(
    record: CandidateDecisionRecord,
    stop_distance: Decimal | None,
) -> dict[str, str]:
    reward_risk = record_reward_risk(record)
    entry = record.confirmation_entry or record.entry_zone_high
    complete = all(
        value is not None
        for value in (
            record.entry_zone_high,
            record.confirmation_entry,
            record.risk_stop,
            record.target_1,
            record.target_2,
            record.target_3,
            record.trailing_stop_plan,
        )
    )
    return {
        "strategy_score": str(record.strategy_score),
        "final_verdict": record.final_verdict,
        "raw_approved": _bool(record.approved_for_deployment),
        "confidence": record.confidence,
        "data_quality": record.data_quality,
        "setup_type": record.setup_type or "UNAVAILABLE",
        "entry_timing_state": record.capital_action,
        "long_trade_permission": _bool(record.long_trade_permission),
        "complete_trade_plan": _bool(complete),
        "entry_price": _optional(entry),
        "stop_distance_pct": _optional(stop_distance),
        "reward_risk": _optional(reward_risk),
        "price_component": record.indicator_scores.get("price", "unavailable"),
        "volume_component": record.indicator_scores.get("volume", "unavailable"),
        "candle_component": record.indicator_scores.get("candle", "unavailable"),
    }


def _source_hash(
    records: tuple[CandidateDecisionRecord, ...],
    outcomes: tuple[CandidateForwardOutcome, ...],
) -> str:
    payload = {
        "records": [record.as_dict() for record in records],
        "outcomes": [outcome.as_dict() for outcome in outcomes],
    }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _optional(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


__all__ = ["HistoricalSignalGenerator"]
