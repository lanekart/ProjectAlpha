from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from alpha.adaptive_weights.models import (
    AlphaComponent,
    CompletedOutcomeEvidence,
    ComponentScore,
    EvidencePartition,
    canonical_weight_set,
    to_primitive,
)
from alpha.forward_validation.models import (
    PositionJournalRow,
    PositionStatus,
    RecommendationSnapshot,
)
from alpha.performance_intelligence.models import (
    RecommendationLedgerEntry,
    RecommendationOutcome,
    RecommendationOutcomeStatus,
)

_SCORE_ALIASES: dict[AlphaComponent, tuple[str, ...]] = {
    AlphaComponent.PRICE_STRUCTURE: ("price_structure_score", "price_score"),
    AlphaComponent.VOLUME: ("volume_confirmation_score", "volume_score"),
    AlphaComponent.TREND: ("trend_alignment_score", "trend_score"),
    AlphaComponent.RELATIVE_STRENGTH: (
        "relative_strength_score",
        "relative_strength",
    ),
    AlphaComponent.RETRACEMENT: ("retracement_score",),
    AlphaComponent.CANDLESTICK: ("candle_score", "candlestick_score"),
    AlphaComponent.BREAKOUT_SETUP: (
        "breakout_setup_score",
        "breakout_score",
        "setup_score",
    ),
    AlphaComponent.MARKET_REGIME: ("market_regime_score", "regime_score"),
    AlphaComponent.SECTOR: ("sector_strength_score", "sector_score"),
    AlphaComponent.RISK_VOLATILITY: (
        "risk_volatility_score",
        "risk_quality_score",
    ),
}


@dataclass(frozen=True, slots=True)
class EvidenceBuildAudit:
    records_seen: int
    completed_records: int
    eligible_records: int
    excluded_unresolved: int
    excluded_incomplete: int
    exclusion_reasons: tuple[str, ...]


class CompletedOutcomeEvidenceBuilder:
    """Builds research evidence only from immutable, fully resolved outcomes."""

    def from_performance_ledger(
        self,
        entries: tuple[RecommendationLedgerEntry, ...],
        outcomes: tuple[RecommendationOutcome, ...],
        *,
        partition: EvidencePartition,
        exchange: str = "NSE",
    ) -> tuple[tuple[CompletedOutcomeEvidence, ...], EvidenceBuildAudit]:
        outcome_by_id = {item.recommendation_id: item for item in outcomes}
        evidence: list[CompletedOutcomeEvidence] = []
        unresolved = 0
        incomplete = 0
        reasons: list[str] = []
        completed = 0
        for entry in sorted(entries, key=lambda item: item.recommendation_id):
            outcome = outcome_by_id.get(entry.recommendation_id)
            if (
                outcome is None
                or outcome.status is not RecommendationOutcomeStatus.EXITED
            ):
                unresolved += 1
                continue
            completed += 1
            built, reason = self._from_resolved_entry(
                entry,
                outcome,
                partition=partition,
                exchange=exchange,
            )
            if built is None:
                incomplete += 1
                reasons.append(f"{entry.recommendation_id}: {reason}")
                continue
            evidence.append(built)
        return (
            tuple(evidence),
            EvidenceBuildAudit(
                records_seen=len(entries),
                completed_records=completed,
                eligible_records=len(evidence),
                excluded_unresolved=unresolved,
                excluded_incomplete=incomplete,
                exclusion_reasons=tuple(reasons),
            ),
        )

    def _from_resolved_entry(
        self,
        entry: RecommendationLedgerEntry,
        outcome: RecommendationOutcome,
        *,
        partition: EvidencePartition,
        exchange: str,
    ) -> tuple[CompletedOutcomeEvidence | None, str]:
        required_prices = (
            outcome.entry_price,
            entry.stop_loss,
            outcome.exit_price,
            outcome.realized_percent_return,
            outcome.realized_r_multiple,
        )
        if any(value is None for value in required_prices):
            return None, "resolved price, return, or R-multiple is unavailable"
        dataset_version = entry.data_completeness_snapshot.get("dataset_version")
        policy_version = entry.statistical_edge_snapshot.get("policy_version")
        transaction_costs = _optional_decimal(
            entry.statistical_edge_snapshot.get("transaction_costs")
        )
        if not dataset_version or not policy_version or transaction_costs is None:
            return None, "dataset, policy, or transaction-cost lineage is unavailable"
        scores = self._component_scores(entry.key_indicator_snapshot)
        entry_price = outcome.entry_price
        stop = entry.stop_loss
        exit_price = outcome.exit_price
        realized_return = outcome.realized_percent_return
        realized_r = outcome.realized_r_multiple
        assert entry_price is not None
        assert stop is not None
        assert exit_price is not None
        assert realized_return is not None
        assert realized_r is not None
        return (
            CompletedOutcomeEvidence(
                recommendation_id=entry.recommendation_id,
                candidate_id=None,
                symbol=entry.symbol,
                exchange=exchange,
                decision_date=entry.generated_at.date(),
                setup_family=entry.setup_type or "UNKNOWN",
                strategy_family=entry.statistical_edge_snapshot.get(
                    "strategy", "UNKNOWN"
                ),
                market_regime=entry.market_regime or "UNKNOWN",
                sector=entry.sector or "UNKNOWN",
                holding_horizon=entry.holding_period or "UNKNOWN",
                component_scores=scores,
                canonical_weights=canonical_weight_set(),
                entry=entry_price,
                stop=stop,
                exit=exit_price,
                realized_return=realized_return,
                realized_r_multiple=realized_r,
                winner=realized_r > Decimal("0"),
                transaction_costs=transaction_costs,
                dataset_version=dataset_version,
                policy_version=policy_version,
                provenance="performance_intelligence.recommendation_ledger",
                partition=partition,
                approved=(entry.approved_deployment_rs or Decimal("0")) > Decimal("0"),
                stop_policy=entry.statistical_edge_snapshot.get(
                    "stop_policy", "RECORDED_PLAN"
                ),
                exit_policy=entry.statistical_edge_snapshot.get(
                    "exit_policy", "RECORDED_PLAN"
                ),
                exit_date=outcome.exit_date,
            ),
            "",
        )

    def from_forward_validation(
        self,
        snapshots: tuple[RecommendationSnapshot, ...],
        journal: tuple[PositionJournalRow, ...],
        *,
        exchange: str = "NSE",
    ) -> tuple[tuple[CompletedOutcomeEvidence, ...], EvidenceBuildAudit]:
        """Adapt immutable forward outcomes, excluding every unresolved row."""

        journal_by_id = {item.recommendation_id: item for item in journal}
        evidence: list[CompletedOutcomeEvidence] = []
        unresolved = 0
        incomplete = 0
        reasons: list[str] = []
        completed = 0
        for snapshot in sorted(snapshots, key=lambda item: item.recommendation_id):
            row = journal_by_id.get(snapshot.recommendation_id)
            if row is None or row.status is not PositionStatus.EXITED:
                unresolved += 1
                continue
            completed += 1
            built, reason = self._from_forward_row(snapshot, row, exchange=exchange)
            if built is None:
                incomplete += 1
                reasons.append(f"{snapshot.recommendation_id}: {reason}")
                continue
            evidence.append(built)
        return (
            tuple(evidence),
            EvidenceBuildAudit(
                records_seen=len(snapshots),
                completed_records=completed,
                eligible_records=len(evidence),
                excluded_unresolved=unresolved,
                excluded_incomplete=incomplete,
                exclusion_reasons=tuple(reasons),
            ),
        )

    def _from_forward_row(
        self,
        snapshot: RecommendationSnapshot,
        row: PositionJournalRow,
        *,
        exchange: str,
    ) -> tuple[CompletedOutcomeEvidence | None, str]:
        if (
            row.entry_price is None
            or row.exit_price is None
            or row.return_pct is None
            or snapshot.stop_loss is None
            or row.exit_at is None
        ):
            return (
                None,
                "forward entry, stop, exit, return, or exit time is unavailable",
            )
        risk = row.entry_price - snapshot.stop_loss
        if risk <= Decimal("0"):
            return None, "forward stop does not define positive long-side risk"
        flattened = _flatten_snapshot(snapshot.diagnostics)
        transaction_costs = _optional_decimal(flattened.get("transaction_costs"))
        if transaction_costs is None:
            return None, "forward transaction-cost evidence is unavailable"
        realised_r = (row.exit_price - row.entry_price) / risk
        return (
            CompletedOutcomeEvidence(
                recommendation_id=snapshot.recommendation_id,
                candidate_id=_optional_text(flattened.get("candidate_id")),
                symbol=snapshot.symbol,
                exchange=exchange,
                decision_date=snapshot.generated_at.date(),
                setup_family=str(flattened.get("setup_family", "UNKNOWN")),
                strategy_family=str(flattened.get("strategy_family", "UNKNOWN")),
                market_regime=snapshot.market_regime or "UNKNOWN",
                sector=snapshot.sector or "UNKNOWN",
                holding_horizon=snapshot.holding_period or "UNKNOWN",
                component_scores=self._component_scores(flattened),
                canonical_weights=canonical_weight_set(),
                entry=row.entry_price,
                stop=snapshot.stop_loss,
                exit=row.exit_price,
                realized_return=row.return_pct,
                realized_r_multiple=realised_r,
                winner=realised_r > Decimal("0"),
                transaction_costs=transaction_costs,
                dataset_version=snapshot.data_version,
                policy_version=snapshot.policy_version.value,
                provenance="forward_validation.immutable_snapshot_and_journal",
                partition=EvidencePartition.FORWARD_OBSERVED,
                approved=(snapshot.approved_deployment or Decimal("0")) > Decimal("0"),
                stop_policy=str(flattened.get("stop_policy", "RECORDED_PLAN")),
                exit_policy=str(
                    flattened.get("exit_policy", row.exit_reason or "UNKNOWN")
                ),
                exit_date=row.exit_at.date(),
            ),
            "",
        )

    def _component_scores(self, snapshot: object) -> tuple[ComponentScore, ...]:
        values: Mapping[object, object] = (
            snapshot if isinstance(snapshot, Mapping) else {}
        )
        scores: list[ComponentScore] = []
        for component in AlphaComponent:
            score: Decimal | None = None
            source_key = "unavailable"
            for key in _SCORE_ALIASES[component]:
                raw = values.get(key)
                parsed = _optional_decimal(raw)
                if parsed is None:
                    continue
                score = parsed / Decimal("100") if parsed > Decimal("1") else parsed
                source_key = f"key_indicator_snapshot.{key}"
                break
            scores.append(
                ComponentScore(
                    component=component,
                    score=score,
                    available=score is not None,
                    source_lineage=source_key,
                )
            )
        return tuple(scores)


def filter_evidence(
    evidence: tuple[CompletedOutcomeEvidence, ...],
    *,
    partition: EvidencePartition | None = None,
    setup: str | None = None,
    regime: str | None = None,
    sector: str | None = None,
    horizon: str | None = None,
    dataset_version: str | None = None,
    policy_version: str | None = None,
) -> tuple[CompletedOutcomeEvidence, ...]:
    return tuple(
        item
        for item in evidence
        if (partition is None or item.partition is partition)
        and (setup is None or item.setup_family == setup)
        and (regime is None or item.market_regime == regime)
        and (sector is None or item.sector == sector)
        and (horizon is None or item.holding_horizon == horizon)
        and (dataset_version is None or item.dataset_version == dataset_version)
        and (policy_version is None or item.policy_version == policy_version)
    )


def load_evidence(path: Path) -> tuple[CompletedOutcomeEvidence, ...]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    else:
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw if isinstance(raw, list) else raw.get("evidence", [])
    return tuple(_evidence_from_mapping(row) for row in rows)


def export_evidence_json(
    evidence: tuple[CompletedOutcomeEvidence, ...], path: Path
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([to_primitive(item) for item in evidence], indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def export_evidence_csv(
    evidence: tuple[CompletedOutcomeEvidence, ...], path: Path
) -> None:
    rows = [_evidence_to_row(item) for item in evidence]
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else _empty_csv_fields()
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _evidence_to_row(item: CompletedOutcomeEvidence) -> dict[str, str]:
    row = {
        "recommendation_id": item.recommendation_id,
        "candidate_id": item.candidate_id or "",
        "symbol": item.symbol,
        "exchange": item.exchange,
        "decision_date": item.decision_date.isoformat(),
        "setup_family": item.setup_family,
        "strategy_family": item.strategy_family,
        "market_regime": item.market_regime,
        "sector": item.sector,
        "holding_horizon": item.holding_horizon,
        "entry": str(item.entry),
        "stop": str(item.stop),
        "exit": str(item.exit),
        "realized_return": str(item.realized_return),
        "realized_r_multiple": str(item.realized_r_multiple),
        "winner": str(item.winner).lower(),
        "transaction_costs": str(item.transaction_costs),
        "dataset_version": item.dataset_version,
        "policy_version": item.policy_version,
        "provenance": item.provenance,
        "partition": item.partition.value,
        "approved": str(item.approved).lower(),
        "stop_policy": item.stop_policy,
        "exit_policy": item.exit_policy,
        "exit_date": item.exit_date.isoformat() if item.exit_date else "",
    }
    for score in item.component_scores:
        row[f"score.{score.component.value}"] = (
            str(score.score) if score.score is not None else ""
        )
        row[f"available.{score.component.value}"] = str(score.available).lower()
        row[f"lineage.{score.component.value}"] = score.source_lineage
    return row


def _evidence_from_mapping(raw: object) -> CompletedOutcomeEvidence:
    if not isinstance(raw, dict):
        raise ValueError("evidence record must be an object")
    nested_scores = raw.get("component_scores")
    by_component: dict[str, dict[str, Any]] = {}
    if isinstance(nested_scores, list):
        for item in nested_scores:
            if isinstance(item, dict):
                by_component[str(item.get("component"))] = item
    scores: list[ComponentScore] = []
    for component in AlphaComponent:
        nested = by_component.get(component.value, {})
        score = _optional_decimal(
            nested.get("score", raw.get(f"score.{component.value}"))
        )
        available_raw = nested.get(
            "available", raw.get(f"available.{component.value}", score is not None)
        )
        scores.append(
            ComponentScore(
                component=component,
                score=score,
                available=_as_bool(available_raw),
                source_lineage=str(
                    nested.get(
                        "source_lineage",
                        raw.get(f"lineage.{component.value}", "fixture.explicit"),
                    )
                ),
            )
        )
    return CompletedOutcomeEvidence(
        recommendation_id=str(raw["recommendation_id"]),
        candidate_id=_optional_text(raw.get("candidate_id")),
        symbol=str(raw["symbol"]),
        exchange=str(raw.get("exchange", "NSE")),
        decision_date=date.fromisoformat(str(raw["decision_date"])),
        setup_family=str(raw["setup_family"]),
        strategy_family=str(raw["strategy_family"]),
        market_regime=str(raw.get("market_regime", "UNKNOWN")),
        sector=str(raw.get("sector", "UNKNOWN")),
        holding_horizon=str(raw["holding_horizon"]),
        component_scores=tuple(scores),
        canonical_weights=canonical_weight_set(),
        entry=_required_decimal(raw, "entry"),
        stop=_required_decimal(raw, "stop"),
        exit=_required_decimal(raw, "exit"),
        realized_return=_required_decimal(raw, "realized_return"),
        realized_r_multiple=_required_decimal(raw, "realized_r_multiple"),
        winner=_as_bool(raw["winner"]),
        transaction_costs=_required_decimal(raw, "transaction_costs"),
        dataset_version=str(raw["dataset_version"]),
        policy_version=str(raw["policy_version"]),
        provenance=str(raw["provenance"]),
        partition=EvidencePartition(str(raw["partition"])),
        approved=_as_bool(raw.get("approved", False)),
        stop_policy=str(raw.get("stop_policy", "RECORDED_PLAN")),
        exit_policy=str(raw.get("exit_policy", "RECORDED_PLAN")),
        exit_date=date.fromisoformat(str(raw["exit_date"]))
        if raw.get("exit_date")
        else None,
    )


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or str(value).strip().lower() in {"", "none", "unavailable"}:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _required_decimal(raw: dict[str, Any], key: str) -> Decimal:
    value = _optional_decimal(raw.get(key))
    if value is None:
        raise ValueError(f"evidence field {key} requires a numeric value")
    return value


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _optional_text(value: object) -> str | None:
    text = "" if value is None else str(value).strip()
    return text or None


def _flatten_snapshot(raw: object, prefix: str = "") -> dict[str, object]:
    if not isinstance(raw, Mapping):
        return {}
    flattened: dict[str, object] = {}
    for key, value in raw.items():
        name = str(key)
        qualified = f"{prefix}.{name}" if prefix else name
        if isinstance(value, Mapping):
            nested = _flatten_snapshot(value, qualified)
            flattened.update(nested)
            for nested_key, nested_value in nested.items():
                flattened.setdefault(nested_key.rsplit(".", 1)[-1], nested_value)
        else:
            flattened[qualified] = value
            flattened.setdefault(name, value)
    return flattened


def _empty_csv_fields() -> list[str]:
    base = [
        "recommendation_id",
        "candidate_id",
        "symbol",
        "exchange",
        "decision_date",
        "setup_family",
        "strategy_family",
        "market_regime",
        "sector",
        "holding_horizon",
        "entry",
        "stop",
        "exit",
        "realized_return",
        "realized_r_multiple",
        "winner",
        "transaction_costs",
        "dataset_version",
        "policy_version",
        "provenance",
        "partition",
        "approved",
        "stop_policy",
        "exit_policy",
        "exit_date",
    ]
    for component in AlphaComponent:
        base.extend(
            (
                f"score.{component.value}",
                f"available.{component.value}",
                f"lineage.{component.value}",
            )
        )
    return base


__all__ = [
    "CompletedOutcomeEvidenceBuilder",
    "EvidenceBuildAudit",
    "export_evidence_csv",
    "export_evidence_json",
    "filter_evidence",
    "load_evidence",
]
