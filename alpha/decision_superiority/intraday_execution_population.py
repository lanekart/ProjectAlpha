"""Signed DSI-009 candidate population and bounded intraday request planning."""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from alpha.decision_superiority.entry_stop_improvement_artifacts import (
    DSI009_ARTIFACTS,
    validate_entry_stop_improvement_certificate,
)
from alpha.decision_superiority.intraday_execution_models import (
    IntradayExecutionError,
    IntradayExecutionPolicy,
)

CONTROL_MECHANISM_ID = "ENTRY-INCUMBENT-NEXT-OPEN"
ENTERED_STATE = "ENTERED"


@dataclass(frozen=True, slots=True)
class IntradayCandidate:
    """One frozen daily candidate eligible for intraday entry research."""

    signal_id: str
    identity_key: str
    symbol: str
    strategy_variant_id: str
    walk_forward_fold_id: str
    regime: str
    signal_date: date
    entry_session: date
    signal_strength: float
    signed_raw_entry_price: float
    signed_entry_price_after_slippage: float
    initial_stop: float
    target_1: float
    target_2: float
    maximum_holding_sessions: int
    average_traded_value20: float


@dataclass(frozen=True, slots=True)
class PlannedIntradayRequest:
    """One unique identity/session source request serving one or more candidates."""

    identity_key: str
    session_date: date
    signal_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IntradayPopulationPlan:
    """Deterministic admitted population, exclusions, and request plan."""

    candidates: tuple[IntradayCandidate, ...]
    requests: tuple[PlannedIntradayRequest, ...]
    exclusions: tuple[dict[str, Any], ...]
    reconciliation: tuple[dict[str, Any], ...]
    dsi009_certificate_sha256: str | None = None


def load_signed_intraday_population(
    dsi009_certificate: Path,
    *,
    policy: IntradayExecutionPolicy | None = None,
) -> IntradayPopulationPlan:
    """Load the signed DSI-009 control-entry population and plan source requests."""

    validate_entry_stop_improvement_certificate(
        dsi009_certificate,
        require_ready=True,
    )
    ledger = dsi009_certificate.resolve().parent / DSI009_ARTIFACTS["entry_fills"]
    if not ledger.is_file():
        raise IntradayExecutionError("DSI013_DSI009_ENTRY_FILL_LEDGER_MISSING")
    with ledger.open(newline="", encoding="utf-8") as handle:
        rows = tuple(dict(row) for row in csv.DictReader(handle))
    result = plan_intraday_population(rows, policy=policy)
    return IntradayPopulationPlan(
        candidates=result.candidates,
        requests=result.requests,
        exclusions=result.exclusions,
        reconciliation=result.reconciliation,
        dsi009_certificate_sha256=_sha256(dsi009_certificate),
    )


def plan_intraday_population(
    rows: Sequence[Mapping[str, object]],
    *,
    policy: IntradayExecutionPolicy | None = None,
) -> IntradayPopulationPlan:
    """Build a fail-closed candidate and identity/session request population."""

    active_policy = policy or IntradayExecutionPolicy()
    candidates_by_id: dict[str, IntradayCandidate] = {}
    exclusions: list[dict[str, Any]] = []
    mechanism_rows = 0
    entered_rows = 0

    for index, row in enumerate(rows):
        mechanism_id = _required_text(row, "mechanism_id", index=index)
        if mechanism_id != CONTROL_MECHANISM_ID:
            continue
        mechanism_rows += 1
        fill_state = _required_text(row, "fill_state", index=index)
        if fill_state != ENTERED_STATE:
            exclusions.append(
                _exclusion(row, "CONTROL_FILL_NOT_ENTERED", detail=fill_state)
            )
            continue
        entered_rows += 1
        candidate = _candidate_from_row(row, index=index)
        if not _exact_nse_isin_identity(candidate.identity_key):
            exclusions.append(
                _exclusion(
                    row,
                    "GOVERNED_IDENTITY_NOT_EXACT_NSE_ISIN",
                    detail=candidate.identity_key,
                )
            )
            continue
        if candidate.entry_session < active_policy.comparison_start:
            exclusions.append(
                _exclusion(
                    row,
                    "ENTRY_SESSION_BEFORE_INTRADAY_SOURCE_WINDOW",
                    detail=candidate.entry_session.isoformat(),
                )
            )
            continue
        if candidate.entry_session > active_policy.comparison_end:
            exclusions.append(
                _exclusion(
                    row,
                    "ENTRY_SESSION_AFTER_FROZEN_COMPARISON_END",
                    detail=candidate.entry_session.isoformat(),
                )
            )
            continue
        if candidate.signal_date >= candidate.entry_session:
            raise IntradayExecutionError(
                f"DSI013_NON_FORWARD_ENTRY_SESSION:{candidate.signal_id}"
            )
        existing = candidates_by_id.get(candidate.signal_id)
        if existing is not None and existing != candidate:
            raise IntradayExecutionError(
                f"DSI013_DUPLICATE_SIGNAL_CONFLICT:{candidate.signal_id}"
            )
        candidates_by_id[candidate.signal_id] = candidate

    if mechanism_rows == 0:
        raise IntradayExecutionError("DSI013_CONTROL_MECHANISM_POPULATION_EMPTY")
    candidates = tuple(
        sorted(
            candidates_by_id.values(),
            key=lambda item: (
                item.entry_session,
                -item.signal_strength,
                item.signal_id,
            ),
        )
    )
    if not candidates:
        raise IntradayExecutionError("DSI013_OVERLAP_CANDIDATE_POPULATION_EMPTY")

    request_signals: defaultdict[tuple[str, date], list[str]] = defaultdict(list)
    for candidate in candidates:
        request_signals[(candidate.identity_key, candidate.entry_session)].append(
            candidate.signal_id
        )
    requests = tuple(
        PlannedIntradayRequest(
            identity_key=identity,
            session_date=session_date,
            signal_ids=tuple(sorted(signal_ids)),
        )
        for (identity, session_date), signal_ids in sorted(request_signals.items())
    )
    reconciliation = (
        {"population": "all_input_rows", "count": len(rows)},
        {"population": "control_mechanism_rows", "count": mechanism_rows},
        {"population": "control_entered_rows", "count": entered_rows},
        {"population": "intraday_overlap_candidates", "count": len(candidates)},
        {"population": "intraday_unique_requests", "count": len(requests)},
        {"population": "intraday_exclusions", "count": len(exclusions)},
    )
    return IntradayPopulationPlan(
        candidates=candidates,
        requests=requests,
        exclusions=tuple(
            sorted(
                exclusions,
                key=lambda row: (
                    str(row.get("signal_id", "")),
                    str(row.get("reason", "")),
                ),
            )
        ),
        reconciliation=reconciliation,
    )


def _candidate_from_row(
    row: Mapping[str, object],
    *,
    index: int,
) -> IntradayCandidate:
    return IntradayCandidate(
        signal_id=_required_text(row, "signal_id", index=index),
        identity_key=_required_text(row, "identity_key", index=index),
        symbol=_required_text(row, "symbol", index=index),
        strategy_variant_id=_required_text(
            row,
            "strategy_variant_id",
            index=index,
        ),
        walk_forward_fold_id=_required_text(
            row,
            "walk_forward_fold_id",
            index=index,
        ),
        regime=_required_text(row, "regime", index=index),
        signal_date=_required_date(row, "signal_date", index=index),
        entry_session=_required_date(
            row,
            "entry_eligibility_date",
            index=index,
        ),
        signal_strength=_required_float(row, "signal_strength", index=index),
        signed_raw_entry_price=_required_positive_float(
            row,
            "raw_entry_price",
            index=index,
        ),
        signed_entry_price_after_slippage=_required_positive_float(
            row,
            "entry_price_after_slippage",
            index=index,
        ),
        initial_stop=_required_positive_float(row, "initial_stop", index=index),
        target_1=_required_positive_float(row, "target_1", index=index),
        target_2=_required_positive_float(row, "target_2", index=index),
        maximum_holding_sessions=_required_positive_int(
            row,
            "maximum_holding_sessions",
            index=index,
        ),
        average_traded_value20=_required_positive_float(
            row,
            "average_traded_value20",
            index=index,
        ),
    )


def _exclusion(
    row: Mapping[str, object],
    reason: str,
    *,
    detail: str,
) -> dict[str, Any]:
    return {
        "signal_id": str(row.get("signal_id") or ""),
        "identity_key": str(row.get("identity_key") or ""),
        "signal_date": str(row.get("signal_date") or ""),
        "entry_eligibility_date": str(row.get("entry_eligibility_date") or ""),
        "reason": reason,
        "detail": detail,
    }


def _required_text(
    row: Mapping[str, object],
    field: str,
    *,
    index: int,
) -> str:
    value = str(row.get(field) or "").strip()
    if not value:
        raise IntradayExecutionError(f"DSI013_CANDIDATE_FIELD_MISSING:{index}:{field}")
    return value


def _required_date(
    row: Mapping[str, object],
    field: str,
    *,
    index: int,
) -> date:
    value = _required_text(row, field, index=index)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise IntradayExecutionError(
            f"DSI013_CANDIDATE_DATE_INVALID:{index}:{field}:{value}"
        ) from exc


def _required_float(
    row: Mapping[str, object],
    field: str,
    *,
    index: int,
) -> float:
    value = _required_text(row, field, index=index)
    try:
        return float(value)
    except ValueError as exc:
        raise IntradayExecutionError(
            f"DSI013_CANDIDATE_NUMBER_INVALID:{index}:{field}:{value}"
        ) from exc


def _required_positive_float(
    row: Mapping[str, object],
    field: str,
    *,
    index: int,
) -> float:
    value = _required_float(row, field, index=index)
    if value <= 0:
        raise IntradayExecutionError(
            f"DSI013_CANDIDATE_NUMBER_NON_POSITIVE:{index}:{field}:{value}"
        )
    return value


def _required_positive_int(
    row: Mapping[str, object],
    field: str,
    *,
    index: int,
) -> int:
    value = _required_float(row, field, index=index)
    integer = int(value)
    if integer <= 0 or float(integer) != value:
        raise IntradayExecutionError(
            f"DSI013_CANDIDATE_INTEGER_INVALID:{index}:{field}:{value}"
        )
    return integer


def _exact_nse_isin_identity(identity: str) -> bool:
    prefix = "nse:isin:"
    if not identity.startswith(prefix):
        return False
    isin = identity[len(prefix) :]
    return len(isin) == 12 and isin.isalnum() and isin.upper() == isin


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "CONTROL_MECHANISM_ID",
    "ENTERED_STATE",
    "IntradayCandidate",
    "IntradayPopulationPlan",
    "PlannedIntradayRequest",
    "load_signed_intraday_population",
    "plan_intraday_population",
]
