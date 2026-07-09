from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from alpha.performance_intelligence.models import (
    RecommendationLedgerEntry,
    RecommendationOutcome,
    RecommendationOutcomeStatus,
)


class RecommendationLedgerRepository:
    """Deterministic JSON persistence for recommendation history and outcomes."""

    def __init__(self, ledger_path: Path | str) -> None:
        self.ledger_path = Path(ledger_path)

    def load_entries(self) -> tuple[RecommendationLedgerEntry, ...]:
        payload = self._read_payload()
        entries = payload.get("entries", [])
        if not isinstance(entries, list):
            return ()
        return tuple(
            sorted(
                (
                    RecommendationLedgerEntry.from_dict(entry)
                    for entry in entries
                    if isinstance(entry, dict)
                ),
                key=lambda entry: (
                    entry.generated_at,
                    entry.symbol,
                    entry.recommendation_id,
                ),
            )
        )

    def load_outcomes(self) -> tuple[RecommendationOutcome, ...]:
        payload = self._read_payload()
        outcomes = payload.get("outcomes", [])
        if not isinstance(outcomes, list):
            return ()
        return tuple(
            sorted(
                (
                    RecommendationOutcome.from_dict(outcome)
                    for outcome in outcomes
                    if isinstance(outcome, dict)
                ),
                key=lambda outcome: (outcome.symbol, outcome.recommendation_id),
            )
        )

    def save_entry(self, entry: RecommendationLedgerEntry) -> bool:
        entries = {item.recommendation_id: item for item in self.load_entries()}
        inserted = entry.recommendation_id not in entries
        entries[entry.recommendation_id] = entry
        self._write(
            entries=tuple(entries.values()),
            outcomes=self.load_outcomes(),
        )
        return inserted

    def save_entries(self, entries: tuple[RecommendationLedgerEntry, ...]) -> int:
        existing = {item.recommendation_id: item for item in self.load_entries()}
        inserted = 0
        for entry in entries:
            if entry.recommendation_id not in existing:
                inserted += 1
            existing[entry.recommendation_id] = entry
        self._write(
            entries=tuple(existing.values()),
            outcomes=self.load_outcomes(),
        )
        return inserted

    def upsert_outcome(self, outcome: RecommendationOutcome) -> None:
        outcomes = {item.recommendation_id: item for item in self.load_outcomes()}
        outcomes[outcome.recommendation_id] = outcome
        self._write(
            entries=self.load_entries(),
            outcomes=tuple(outcomes.values()),
        )

    def upsert_outcomes(self, outcomes: tuple[RecommendationOutcome, ...]) -> None:
        existing = {item.recommendation_id: item for item in self.load_outcomes()}
        for outcome in outcomes:
            existing[outcome.recommendation_id] = outcome
        self._write(
            entries=self.load_entries(),
            outcomes=tuple(existing.values()),
        )

    def open_entries(self) -> tuple[RecommendationLedgerEntry, ...]:
        outcomes = {
            outcome.recommendation_id: outcome for outcome in self.load_outcomes()
        }
        open_statuses = {
            RecommendationOutcomeStatus.PENDING,
            RecommendationOutcomeStatus.ACTIVE,
        }
        entries: list[RecommendationLedgerEntry] = []
        for entry in self.load_entries():
            outcome = outcomes.get(entry.recommendation_id)
            if outcome is None or outcome.status in open_statuses:
                entries.append(entry)
        return tuple(entries)

    def _read_payload(self) -> dict[str, Any]:
        if not self.ledger_path.exists():
            return {"entries": [], "outcomes": []}
        raw = self.ledger_path.read_text(encoding="utf-8").strip()
        if not raw:
            return {"entries": [], "outcomes": []}
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return {"entries": [], "outcomes": []}
        return payload

    def _write(
        self,
        *,
        entries: tuple[RecommendationLedgerEntry, ...],
        outcomes: tuple[RecommendationOutcome, ...],
    ) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "entries": [
                entry.as_dict()
                for entry in sorted(
                    entries,
                    key=lambda item: (
                        item.generated_at.isoformat(),
                        item.symbol,
                        item.recommendation_id,
                    ),
                )
            ],
            "outcomes": [
                outcome.as_dict()
                for outcome in sorted(
                    outcomes,
                    key=lambda item: (item.symbol, item.recommendation_id),
                )
            ],
        }
        temporary_path = self.ledger_path.with_suffix(f"{self.ledger_path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(self.ledger_path)


__all__ = ["RecommendationLedgerRepository"]
