from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
    LearningSummary,
)
from alpha.candidate_learning.raw_universe import (
    RawCandidateForwardOutcome,
    RawCandidateRecord,
)

DEFAULT_LEARNING_LEDGER_PATH = Path(".alpha/candidate_learning_ledger.json")


class LearningLedgerRepository:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_learning_ledger_path(path)

    def save_records(self, records: tuple[CandidateDecisionRecord, ...]) -> int:
        existing = {record.candidate_id: record for record in self.load_records()}
        inserted = 0
        for record in records:
            if record.candidate_id in existing:
                continue
            inserted += 1
            existing[record.candidate_id] = record
        self._write(
            records=tuple(existing.values()),
            outcomes=self.load_outcomes(),
            summaries=self.load_summaries(),
            raw_records=self.load_raw_records(),
            raw_outcomes=self.load_raw_outcomes(),
        )
        return inserted

    def save_raw_records(self, records: tuple[RawCandidateRecord, ...]) -> int:
        existing = {
            record.raw_candidate_id: record for record in self.load_raw_records()
        }
        inserted = 0
        for record in records:
            if record.raw_candidate_id not in existing:
                inserted += 1
            existing[record.raw_candidate_id] = record
        self._write(
            records=self.load_records(),
            outcomes=self.load_outcomes(),
            summaries=self.load_summaries(),
            raw_records=tuple(existing.values()),
            raw_outcomes=self.load_raw_outcomes(),
        )
        return inserted

    def upsert_outcomes(self, outcomes: tuple[CandidateForwardOutcome, ...]) -> None:
        existing = {outcome.candidate_id: outcome for outcome in self.load_outcomes()}
        for outcome in outcomes:
            existing[outcome.candidate_id] = outcome
        self._write(
            records=self.load_records(),
            outcomes=tuple(existing.values()),
            summaries=self.load_summaries(),
            raw_records=self.load_raw_records(),
            raw_outcomes=self.load_raw_outcomes(),
        )

    def upsert_raw_outcomes(
        self,
        outcomes: tuple[RawCandidateForwardOutcome, ...],
    ) -> None:
        existing = {
            outcome.raw_candidate_id: outcome for outcome in self.load_raw_outcomes()
        }
        for outcome in outcomes:
            existing[outcome.raw_candidate_id] = outcome
        self._write(
            records=self.load_records(),
            outcomes=self.load_outcomes(),
            summaries=self.load_summaries(),
            raw_records=self.load_raw_records(),
            raw_outcomes=tuple(existing.values()),
        )

    def save_summaries(self, summaries: tuple[LearningSummary, ...]) -> None:
        existing = {summary.period: summary for summary in self.load_summaries()}
        for summary in summaries:
            existing[summary.period] = summary
        self._write(
            records=self.load_records(),
            outcomes=self.load_outcomes(),
            summaries=tuple(existing.values()),
            raw_records=self.load_raw_records(),
            raw_outcomes=self.load_raw_outcomes(),
        )

    def load_records(self) -> tuple[CandidateDecisionRecord, ...]:
        records = self._read().get("records", [])
        if not isinstance(records, list):
            return ()
        return tuple(
            sorted(
                (
                    CandidateDecisionRecord.from_dict(record)
                    for record in records
                    if isinstance(record, dict)
                ),
                key=lambda record: (record.evaluation_date, record.symbol),
            )
        )

    def load_outcomes(self) -> tuple[CandidateForwardOutcome, ...]:
        outcomes = self._read().get("outcomes", [])
        if not isinstance(outcomes, list):
            return ()
        return tuple(
            sorted(
                (
                    CandidateForwardOutcome.from_dict(outcome)
                    for outcome in outcomes
                    if isinstance(outcome, dict)
                ),
                key=lambda outcome: (outcome.symbol, outcome.candidate_id),
            )
        )

    def load_raw_records(self) -> tuple[RawCandidateRecord, ...]:
        records = self._read().get("raw_records", [])
        if not isinstance(records, list):
            return ()
        return tuple(
            sorted(
                (
                    RawCandidateRecord.from_dict(record)
                    for record in records
                    if isinstance(record, dict)
                ),
                key=lambda record: (record.evaluation_date, record.symbol),
            )
        )

    def load_raw_outcomes(self) -> tuple[RawCandidateForwardOutcome, ...]:
        outcomes = self._read().get("raw_outcomes", [])
        if not isinstance(outcomes, list):
            return ()
        return tuple(
            sorted(
                (
                    RawCandidateForwardOutcome.from_dict(outcome)
                    for outcome in outcomes
                    if isinstance(outcome, dict)
                ),
                key=lambda outcome: (outcome.symbol, outcome.raw_candidate_id),
            )
        )

    def load_summaries(self) -> tuple[LearningSummary, ...]:
        summaries = self._read().get("summaries", [])
        if not isinstance(summaries, list):
            return ()
        return tuple(
            _summary_from_dict(summary)
            for summary in summaries
            if isinstance(summary, dict)
        )

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_payload()
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            return _empty_payload()
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
        return _empty_payload()

    def _write(
        self,
        *,
        records: tuple[CandidateDecisionRecord, ...],
        outcomes: tuple[CandidateForwardOutcome, ...],
        summaries: tuple[LearningSummary, ...],
        raw_records: tuple[RawCandidateRecord, ...],
        raw_outcomes: tuple[RawCandidateForwardOutcome, ...],
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "records": [record.as_dict() for record in records],
            "outcomes": [outcome.as_dict() for outcome in outcomes],
            "summaries": [summary.as_dict() for summary in summaries],
            "raw_records": [record.as_dict() for record in raw_records],
            "raw_outcomes": [outcome.as_dict() for outcome in raw_outcomes],
        }
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


def resolve_learning_ledger_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.environ.get("ALPHA_CANDIDATE_LEARNING_LEDGER")
    if configured:
        return Path(configured)
    return DEFAULT_LEARNING_LEDGER_PATH


def _empty_payload() -> dict[str, list[object]]:
    return {
        "records": [],
        "outcomes": [],
        "summaries": [],
        "raw_records": [],
        "raw_outcomes": [],
    }


def _summary_from_dict(payload: dict[str, Any]) -> LearningSummary:
    from datetime import datetime
    from decimal import Decimal

    from alpha.candidate_learning.models import CandidateDecisionQualitySummary

    quality = payload["quality"]
    return LearningSummary(
        period=str(payload["period"]),
        generated_at=datetime.fromisoformat(str(payload["generated_at"])),
        total_candidates_evaluated=int(payload["total_candidates_evaluated"]),
        approved_count=int(payload["approved_count"]),
        rejected_count=int(payload["rejected_count"]),
        watchlist_count=int(payload["watchlist_count"]),
        avoid_count=int(payload["avoid_count"]),
        sell_count=int(payload["sell_count"]),
        completed_forward_windows=int(payload["completed_forward_windows"]),
        quality=CandidateDecisionQualitySummary(
            false_positive_count=int(quality["false_positive_count"]),
            false_negative_count=int(quality["false_negative_count"]),
            correct_approval_count=int(quality["correct_approval_count"]),
            correct_reject_count=int(quality["correct_reject_count"]),
            approval_precision=_decimal_or_none(quality.get("approval_precision")),
            rejection_accuracy=_decimal_or_none(quality.get("rejection_accuracy")),
            missed_opportunity_rate=_decimal_or_none(
                quality.get("missed_opportunity_rate")
            ),
            avoid_success_rate=_decimal_or_none(quality.get("avoid_success_rate")),
            watchlist_conversion_quality=_decimal_or_none(
                quality.get("watchlist_conversion_quality")
            ),
        ),
        best_indicator_combinations=tuple(
            (str(item[0]), Decimal(str(item[1])))
            for item in payload.get("best_indicator_combinations", ())
        ),
        worst_indicator_combinations=tuple(
            (str(item[0]), Decimal(str(item[1])))
            for item in payload.get("worst_indicator_combinations", ())
        ),
        best_setup_regime_combinations=tuple(
            (str(item[0]), Decimal(str(item[1])))
            for item in payload.get("best_setup_regime_combinations", ())
        ),
        worst_setup_regime_combinations=tuple(
            (str(item[0]), Decimal(str(item[1])))
            for item in payload.get("worst_setup_regime_combinations", ())
        ),
        data_gaps=int(payload["data_gaps"]),
        sufficient_sample=bool(payload["sufficient_sample"]),
    )


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


__all__ = [
    "DEFAULT_LEARNING_LEDGER_PATH",
    "LearningLedgerRepository",
    "resolve_learning_ledger_path",
]
