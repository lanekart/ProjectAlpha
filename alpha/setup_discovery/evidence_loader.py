from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from alpha.candidate_generation_research.exports import (
    DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
)
from alpha.setup_discovery.models import RawMissedSetupCase


class CandidateResearchEvidenceLoader:
    """Load frozen candidate-research rows without recalculating classifications."""

    def load_cases(
        self,
        *,
        directory: Path | str = DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
        reasons: tuple[str, ...] = (
            "SETUP_FAMILY_NOT_SUPPORTED",
            "LOOKBACK_MISMATCH",
        ),
    ) -> tuple[RawMissedSetupCase, ...]:
        root = Path(directory)
        onsets = {
            row["onset_id"]: row
            for row in _rows(root / "tradable_opportunity_onsets.csv")
        }
        events = {
            row["event_id"]: row for row in _rows(root / "forward_move_events.csv")
        }
        selected = []
        allowed = set(reasons)
        for funnel in _rows(root / "candidate_generation_funnel.csv"):
            if funnel.get("failure_reason") not in allowed:
                continue
            onset_id = funnel.get("onset_id", "")
            onset = onsets.get(onset_id)
            event = events.get(funnel["event_id"])
            if onset is None or event is None:
                continue
            selected.append(_case(funnel, onset, event))
        return tuple(
            sorted(
                selected, key=lambda item: (item.symbol, item.onset_date, item.case_id)
            )
        )

    def symbol_timeline(
        self,
        symbol: str,
        *,
        directory: Path | str = DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
    ) -> tuple[dict[str, str], ...]:
        normalized = symbol.strip().upper()
        root = Path(directory)
        funnel_by_event = {
            row["event_id"]: row
            for row in _rows(root / "candidate_generation_funnel.csv")
            if row.get("symbol", "").upper() == normalized
        }
        rows = []
        for onset in _rows(root / "tradable_opportunity_onsets.csv"):
            if onset.get("symbol", "").upper() != normalized:
                continue
            funnel = funnel_by_event.get(onset.get("forward_event_id", ""), {})
            rows.append(
                {
                    "onset_date": onset.get("onset_date", ""),
                    "event_family": onset.get("event_family", ""),
                    "entry_trigger": onset.get("entry_trigger", ""),
                    "prospective_stop": onset.get("prospective_stop", ""),
                    "prospective_target": onset.get("prospective_target", ""),
                    "prospective_rr": onset.get("prospective_rr", ""),
                    "canonical_setup": funnel.get(
                        "canonical_setup_recognized", "UNAVAILABLE"
                    ),
                    "canonical_candidate": funnel.get(
                        "canonical_candidate_created", "UNAVAILABLE"
                    ),
                    "failure_reason": funnel.get("failure_reason", ""),
                    "coverage": funnel.get("coverage", ""),
                }
            )
        return tuple(sorted(rows, key=lambda item: item["onset_date"]))

    @staticmethod
    def source_audit_id(
        directory: Path | str = DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
    ) -> str:
        path = Path(directory) / "candidate_research_manifest.json"
        if not path.exists():
            return "UNAVAILABLE"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return "UNAVAILABLE"
        return str(payload.get("policy_id", "UNAVAILABLE"))


def _case(
    funnel: dict[str, str],
    onset: dict[str, str],
    event: dict[str, str],
) -> RawMissedSetupCase:
    inputs = json.loads(onset.get("point_in_time_inputs", "{}"))
    if not isinstance(inputs, dict):
        inputs = {}
    return RawMissedSetupCase(
        case_id=funnel["event_id"],
        event_id=funnel["event_id"],
        onset_id=onset["onset_id"],
        symbol=funnel["symbol"],
        onset_date=date.fromisoformat(onset["onset_date"]),
        onset_sequence=int(onset["onset_sequence"]),
        event_family=onset["event_family"],
        failure_reason=funnel["failure_reason"],
        entry_trigger=Decimal(onset["entry_trigger"]),
        prospective_stop=Decimal(onset["prospective_stop"]),
        prospective_target=Decimal(onset["prospective_target"]),
        prospective_rr=Decimal(onset["prospective_rr"]),
        onset_confidence=Decimal(onset["confidence"]),
        point_in_time_inputs={str(key): str(value) for key, value in inputs.items()},
        forward_return=Decimal(event["forward_return"]),
        event_holding_period=int(event["time_to_peak"]),
        event_start_date=date.fromisoformat(event["start_date"]),
        event_peak_date=date.fromisoformat(event["peak_date"]),
    )


def _rows(path: Path) -> tuple[dict[str, str], ...]:
    if not path.exists():
        raise FileNotFoundError(f"required candidate research artifact missing: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


__all__ = ["CandidateResearchEvidenceLoader"]
