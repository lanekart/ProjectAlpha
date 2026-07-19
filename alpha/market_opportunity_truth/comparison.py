from __future__ import annotations

import csv
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from alpha.market_opportunity_truth.models import (
    AlphaComparisonRecord,
    CaptureStatistics,
    DetectionStatus,
    MarketOpportunity,
)

_TWO = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class _AlphaRecord:
    record_id: str
    symbol: str
    observed_on: date
    final_signal: str
    directional_candidate: bool
    approved: bool


@dataclass(frozen=True, slots=True)
class _ExecutionRecord:
    record_id: str
    symbol: str
    decision_date: date
    entry_date: date


class AlphaOpportunityComparisonEngine:
    """Match market onsets to frozen Alpha records without outcome-based matching."""

    def compare(
        self,
        *,
        opportunities: tuple[MarketOpportunity, ...],
        sessions: tuple[date, ...],
        candidate_rankings_path: Path | str,
        trade_log_path: Path | str,
        matching_window_sessions: int = 5,
    ) -> tuple[tuple[AlphaComparisonRecord, ...], CaptureStatistics]:
        if matching_window_sessions < 1:
            raise ValueError("MOTA matching window must be positive")
        session_position = {session: index for index, session in enumerate(sessions)}
        alpha = _load_alpha_records(Path(candidate_rankings_path))
        executions = _load_execution_records(Path(trade_log_path))
        technical_by_symbol = _group_alpha(alpha)
        directional_by_symbol = _group_alpha(
            tuple(item for item in alpha if item.directional_candidate)
        )
        approved_by_symbol = _group_alpha(
            tuple(item for item in alpha if item.approved)
        )
        execution_by_symbol = _group_execution(executions)
        used_technical: set[str] = set()
        used_directional: set[str] = set()
        used_approved: set[str] = set()
        used_execution: set[str] = set()
        rows = []
        for item in sorted(
            opportunities,
            key=lambda value: (value.symbol, value.onset_date, value.opportunity_id),
        ):
            start = session_position.get(item.onset_date)
            end = _window_end(
                item=item,
                start=start,
                sessions=sessions,
                session_position=session_position,
                window=matching_window_sessions,
            )
            technical = _select_alpha(
                technical_by_symbol.get(item.symbol, ()),
                start=start,
                end=end,
                session_position=session_position,
                used=used_technical,
            )
            directional = _select_alpha(
                directional_by_symbol.get(item.symbol, ()),
                start=start,
                end=end,
                session_position=session_position,
                used=used_directional,
            )
            approved = _select_alpha(
                approved_by_symbol.get(item.symbol, ()),
                start=start,
                end=end,
                session_position=session_position,
                used=used_approved,
            )
            execution = _select_execution(
                execution_by_symbol.get(item.symbol, ()),
                start=start,
                end=end,
                session_position=session_position,
                used=used_execution,
            )
            if directional is not None and technical is None:
                technical = directional
            rows.append(
                AlphaComparisonRecord(
                    opportunity_id=item.opportunity_id,
                    symbol=item.symbol,
                    onset_date=item.onset_date,
                    quality=item.quality,
                    institutional_quality=item.quality.institutional,
                    detected_status=(
                        DetectionStatus.DETECTED
                        if technical is not None
                        else DetectionStatus.NOT_DETECTED
                    ),
                    detection_date=(
                        None if technical is None else technical.observed_on
                    ),
                    detection_delay_sessions=_delay(
                        item.onset_date,
                        None if technical is None else technical.observed_on,
                        session_position,
                    ),
                    candidate_created=directional is not None,
                    candidate_date=(
                        None if directional is None else directional.observed_on
                    ),
                    candidate_delay_sessions=_delay(
                        item.onset_date,
                        None if directional is None else directional.observed_on,
                        session_position,
                    ),
                    candidate_signal=(
                        None if directional is None else directional.final_signal
                    ),
                    institutional_approved=approved is not None,
                    approval_date=None if approved is None else approved.observed_on,
                    executed=execution is not None,
                    execution_date=(
                        None if execution is None else execution.entry_date
                    ),
                    matching_window_sessions=matching_window_sessions,
                    matching_explanation=(
                        "One-to-one symbol match from onset through the earlier of "
                        "five market sessions or the frozen stop/target event. "
                        "Technical ranking is a detection proxy; a separate setup "
                        "detection trace was not persisted."
                    ),
                )
            )
        result = tuple(sorted(rows, key=lambda value: (value.onset_date, value.symbol)))
        return result, capture_statistics(result)


def capture_statistics(
    rows: tuple[AlphaComparisonRecord, ...],
) -> CaptureStatistics:
    institutional = tuple(item for item in rows if item.institutional_quality)
    detected = sum(item.detected_status is DetectionStatus.DETECTED for item in rows)
    institutional_detected = sum(
        item.detected_status is DetectionStatus.DETECTED for item in institutional
    )
    candidates = sum(item.candidate_created for item in rows)
    institutional_candidates = sum(item.candidate_created for item in institutional)
    approved = sum(item.institutional_approved for item in rows)
    institutional_approved = sum(item.institutional_approved for item in institutional)
    executed = sum(item.executed for item in rows)
    institutional_executed = sum(item.executed for item in institutional)
    return CaptureStatistics(
        market_opportunities=len(rows),
        institutional_quality_opportunities=len(institutional),
        detected_opportunities=detected,
        directional_candidates=candidates,
        approved_opportunities=approved,
        executed_opportunities=executed,
        overall_detection_recall_percent=_rate(detected, len(rows)),
        institutional_detection_recall_percent=_rate(
            institutional_detected, len(institutional)
        ),
        overall_candidate_recall_percent=_rate(candidates, len(rows)),
        institutional_candidate_recall_percent=_rate(
            institutional_candidates, len(institutional)
        ),
        institutional_approval_recall_percent=_rate(
            institutional_approved, len(institutional)
        ),
        institutional_execution_recall_percent=_rate(
            institutional_executed, len(institutional)
        ),
        opportunity_capture_rate_percent=_rate(
            institutional_executed, len(institutional)
        ),
        move_capture_percent=None,
        capital_capture_percent=None,
        detection_trace_complete=False,
        explanation=(
            "Candidate, approval, and execution recall use provisional A+/A "
            "market opportunities as the primary denominator. Detection uses the "
            "persisted technical-ranking proxy because full pre-candidate setup "
            "detections are unavailable. Move and capital capture remain unavailable "
            "without executed trades."
        ),
    )


def _window_end(
    *,
    item: MarketOpportunity,
    start: int | None,
    sessions: tuple[date, ...],
    session_position: dict[date, int],
    window: int,
) -> int | None:
    if start is None:
        return None
    end = min(start + window - 1, len(sessions) - 1)
    if item.first_event_date is not None:
        event = session_position.get(item.first_event_date)
        if event is not None:
            end = min(end, event)
    return end


def _select_alpha(
    values: tuple[_AlphaRecord, ...],
    *,
    start: int | None,
    end: int | None,
    session_position: dict[date, int],
    used: set[str],
) -> _AlphaRecord | None:
    if start is None or end is None or not values:
        return None
    positions = tuple(session_position.get(item.observed_on, -1) for item in values)
    for index in range(bisect_left(positions, start), len(values)):
        item = values[index]
        position = positions[index]
        if position > end:
            break
        if item.record_id not in used:
            used.add(item.record_id)
            return item
    return None


def _select_execution(
    values: tuple[_ExecutionRecord, ...],
    *,
    start: int | None,
    end: int | None,
    session_position: dict[date, int],
    used: set[str],
) -> _ExecutionRecord | None:
    if start is None or end is None or not values:
        return None
    positions = tuple(session_position.get(item.decision_date, -1) for item in values)
    for index in range(bisect_left(positions, start), len(values)):
        item = values[index]
        position = positions[index]
        if position > end:
            break
        if item.record_id not in used:
            used.add(item.record_id)
            return item
    return None


def _load_alpha_records(path: Path) -> tuple[_AlphaRecord, ...]:
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for index, row in enumerate(csv.DictReader(handle), start=1):
            observed_on = date.fromisoformat(_required(row, "observed_on"))
            symbol = _required(row, "symbol").upper()
            rows.append(
                _AlphaRecord(
                    record_id=f"{observed_on}|{symbol}|{index}",
                    symbol=symbol,
                    observed_on=observed_on,
                    final_signal=_required(row, "final_signal"),
                    directional_candidate=_bool(_required(row, "approval_candidate")),
                    approved=_bool(_required(row, "institutional_approved")),
                )
            )
    return tuple(rows)


def _load_execution_records(path: Path) -> tuple[_ExecutionRecord, ...]:
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for index, row in enumerate(csv.DictReader(handle), start=1):
            if not row.get("symbol", "").strip():
                continue
            decision_date = date.fromisoformat(_required(row, "decision_date"))
            rows.append(
                _ExecutionRecord(
                    record_id=row.get("trade_id", "").strip() or f"trade-{index}",
                    symbol=_required(row, "symbol").upper(),
                    decision_date=decision_date,
                    entry_date=date.fromisoformat(_required(row, "entry_date")),
                )
            )
    return tuple(rows)


def _group_alpha(
    values: tuple[_AlphaRecord, ...],
) -> dict[str, tuple[_AlphaRecord, ...]]:
    grouped: dict[str, list[_AlphaRecord]] = defaultdict(list)
    for item in values:
        grouped[item.symbol].append(item)
    return {
        symbol: tuple(sorted(items, key=lambda item: item.observed_on))
        for symbol, items in grouped.items()
    }


def _group_execution(
    values: tuple[_ExecutionRecord, ...],
) -> dict[str, tuple[_ExecutionRecord, ...]]:
    grouped: dict[str, list[_ExecutionRecord]] = defaultdict(list)
    for item in values:
        grouped[item.symbol].append(item)
    return {
        symbol: tuple(sorted(items, key=lambda item: item.decision_date))
        for symbol, items in grouped.items()
    }


def _delay(
    start: date,
    end: date | None,
    positions: dict[date, int],
) -> int | None:
    if end is None or start not in positions or end not in positions:
        return None
    return positions[end] - positions[start]


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator) * Decimal("100")).quantize(
        _TWO, rounding=ROUND_HALF_UP
    )


def _bool(value: str) -> bool:
    if value == "True":
        return True
    if value == "False":
        return False
    raise ValueError(f"invalid Alpha comparison boolean: {value}")


def _required(row: dict[str, str], key: str) -> str:
    value = row.get(key, "").strip()
    if not value:
        raise ValueError(f"Alpha comparison field is unavailable: {key}")
    return value


__all__ = ["AlphaOpportunityComparisonEngine", "capture_statistics"]
