"""Typed HTR-010B1B factor-continuity recomputation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from math import isclose
from pathlib import Path
from typing import Any

import duckdb

from alpha.historical_truth.adjustment_replay_admission_models import (
    ValidationOutcome,
    stable_id,
)
from alpha.historical_truth.bridge_aware_continuity_context import (
    BRIDGE_AWARE_CONTINUITY_CONTRACT_VERSION,
    BridgeAwareContinuityContextProvider,
)

HTR010B1B_CONTRACT_VERSION = "HTR-010B1B-v1.0.0"

MATERIAL_ACTION_TYPES = {
    "SPLIT",
    "BONUS",
    "RIGHTS",
    "FACE_VALUE_CHANGE",
    "CAPITAL_REDUCTION",
}
CERTIFIED_FACTOR_STATES = {
    "FACTOR_CERTIFIED",
    "FACTOR_CERTIFIED_REFERENCE_PRICE",
    "FACTOR_DERIVED_OFFICIAL_TERMS",
}
UNKNOWN_FACTOR_STATES = {
    "FACTOR_UNKNOWN_MISSING_TERMS",
    "FACTOR_PROVISIONAL_REFERENCE_PRICE",
}
AMBIGUOUS_FACTOR_STATES = {
    "FACTOR_AMBIGUOUS_TERMS",
    "FACTOR_CONFLICTING_EVENTS",
    "FACTOR_INVALID",
}
NON_MULTIPLICATIVE_STATES = {
    "FACTOR_NOT_MULTIPLICATIVE",
    "FACTOR_IDENTITY_TRANSITION_ONLY",
}


def recompute_factor_validation(
    *,
    database_path: Path,
    events: tuple[dict[str, Any], ...],
    factors: tuple[dict[str, Any], ...],
    legacy_continuity: tuple[dict[str, Any], ...],
    start_date: date,
    end_date: date,
    continuity_context_provider: BridgeAwareContinuityContextProvider | None = None,
) -> tuple[
    tuple[dict[str, Any], ...],
    tuple[dict[str, Any], ...],
    dict[str, Any],
]:
    """Recompute continuity from canonical factors and canonical candles."""

    event_by_id = {str(row["canonical_event_id"]): row for row in events}
    legacy_by_event = {
        str(
            row.get("event_id") or row.get("canonical_event_id") or row.get("action_id")
        ): row
        for row in legacy_continuity
    }
    cases: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    bridge_context_count = 0
    complete_bridge_context_count = 0

    with duckdb.connect(str(database_path), read_only=True) as connection:
        for factor in factors:
            event_id = str(factor.get("canonical_event_id") or "")
            event = event_by_id.get(event_id)
            if event is None:
                continue
            action_type = str(event.get("action_type") or "")
            if action_type not in MATERIAL_ACTION_TYPES:
                continue
            effective = _as_date(event.get("effective_date"))
            if effective is None or not start_date <= effective <= end_date:
                continue

            identity = str(
                event.get("governed_identity_id") or factor.get("identity_key") or ""
            )
            isin = str(event.get("isin") or "").strip().upper()
            applicable = tuple(
                str(item).upper() for item in event.get("series_applicability") or ()
            )
            series = applicable[0] if len(applicable) == 1 else None
            context_payload: dict[str, Any] = {}
            if (
                continuity_context_provider is not None
                and series is not None
                and continuity_context_provider.supports(event_id)
            ):
                context = continuity_context_provider.build(
                    connection,
                    event=event,
                    factor=factor,
                    series=series,
                    effective_date=effective,
                )
                governed_factor = _governed_rights_factor(
                    event,
                    factor,
                    context.as_dict(),
                )
                effective_factor = (
                    {**factor, **governed_factor}
                    if governed_factor is not None
                    else factor
                )
                if governed_factor is not None:
                    context = continuity_context_provider.build(
                        connection,
                        event=event,
                        factor=effective_factor,
                        series=series,
                        effective_date=effective,
                    )
                bridge_context_count += 1
                complete_bridge_context_count += int(context.complete)
                governed_metrics = context.metrics.as_dict()
                metrics = (
                    {
                        **governed_metrics,
                        "candle_context_state": "AVAILABLE",
                    }
                    if context.complete
                    else {
                        **governed_metrics,
                        "raw_gap_atr": None,
                        "adjusted_gap_atr": None,
                        "inverse_adjusted_gap_atr": None,
                        "candle_context_state": context.decision.value,
                    }
                )
                context_payload = {
                    "governed_continuity_context_id": context.context_id,
                    "governed_continuity_context": context.as_dict(),
                    "continuity_context_contract": (
                        BRIDGE_AWARE_CONTINUITY_CONTRACT_VERSION
                    ),
                }
                continuity_source = (
                    "HTR010B_FACTOR_RECOMPUTED_FROM_GOVERNED_BRIDGE_AWARE_CANDLES"
                )
            else:
                governed_factor = None
                effective_factor = factor
                metrics = _continuity_metrics(
                    _event_bars(connection, isin, series, effective),
                    _number(factor.get("price_factor")),
                )
                continuity_source = "HTR010B_FACTOR_RECOMPUTED_FROM_CANONICAL_CANDLES"
            legacy = legacy_by_event.get(event_id, {})
            case = {
                "case_id": stable_id("factor-case-recomputed", event_id),
                "event_id": event_id,
                "identity_key": identity,
                "symbol": event.get("symbol"),
                "series": series,
                "isin": isin or None,
                "action_type": action_type,
                "effective_date": effective.isoformat(),
                "factor_state": effective_factor.get("factor_state"),
                "price_factor": effective_factor.get("price_factor"),
                "official_term_factor_matches": _official_term_factor_matches(
                    event,
                    effective_factor,
                ),
                "reference_price_certified": effective_factor.get(
                    "reference_price_certified"
                ),
                "governed_reference_certification": governed_factor,
                **metrics,
                "legacy_continuity_state": legacy.get("continuity_state"),
                "legacy_raw_gap_atr": legacy.get("raw_gap_atr"),
                "legacy_adjusted_gap_atr": legacy.get("adjusted_gap_atr"),
                "continuity_source": continuity_source,
                **context_payload,
            }
            cases.append(case)
            results.append(_classify(case))

    outcome_counts = Counter(str(row["validation_outcome"]) for row in results)
    disagreements = sum(
        bool(row.get("legacy_continuity_state"))
        and row.get("legacy_continuity_state") != row.get("recomputed_continuity_state")
        for row in results
    )
    orientation_defects = sum(
        row.get("implementation_defect_code") == "POSSIBLE_FACTOR_ORIENTATION_DEFECT"
        for row in results
    )
    summary = {
        "contract_version": HTR010B1B_CONTRACT_VERSION,
        "case_count": len(cases),
        "validation_outcomes": dict(sorted(outcome_counts.items())),
        "legacy_case_count": len(legacy_continuity),
        "legacy_recomputed_state_disagreement_count": disagreements,
        "possible_factor_orientation_defect_count": orientation_defects,
        "bridge_aware_context_case_count": bridge_context_count,
        "complete_bridge_aware_context_count": complete_bridge_context_count,
        "market_derived_factor_autocorrection": False,
        "continuity_recomputed_from_canonical_candles": True,
    }
    return tuple(cases), tuple(results), summary


def _governed_rights_factor(
    event: Mapping[str, Any],
    factor: Mapping[str, Any],
    context: object,
) -> dict[str, Any] | None:
    if (
        event.get("action_type") != "RIGHTS"
        or factor.get("factor_state")
        not in {
            "FACTOR_CERTIFIED_REFERENCE_PRICE",
            "FACTOR_PROVISIONAL_REFERENCE_PRICE",
            "FACTOR_UNKNOWN_MISSING_TERMS",
        }
        or not isinstance(context, dict)
    ):
        return None
    context_complete = context.get("complete") is True
    missing_reference_only = (
        factor.get("factor_state") == "FACTOR_UNKNOWN_MISSING_TERMS"
        and context.get("decision") == "REFERENCE_PRICE_MISMATCH"
        and not factor.get("reference_price_date")
        and factor.get("reference_price") is None
        and not factor.get("reference_price_source_sha256")
        and not context.get("rejected_bars")
        and isinstance(context.get("action_bar"), dict)
    )
    if not context_complete and not missing_reference_only:
        return None
    selected = context.get("selected_prior_bars")
    if not isinstance(selected, list) or not selected:
        return None
    prior = selected[-1]
    if not isinstance(prior, dict):
        return None
    reference_date = str(factor.get("reference_price_date") or "")
    reference_price = _number(factor.get("reference_price"))
    reference_sha = str(factor.get("reference_price_source_sha256") or "")
    prior_price = _number(prior.get("close_price"))
    prior_date = str(prior.get("trading_date") or "")
    prior_sha = str(prior.get("source_sha256") or "")
    identity_state = str(prior.get("identity_state") or "")
    numerator = _number(event.get("ratio_numerator"))
    denominator = _number(event.get("ratio_denominator"))
    rights_price = _number(event.get("rights_price"))
    if (
        prior_price is None
        or prior_price <= 0
        or not prior_date
        or not prior_sha
        or numerator is None
        or numerator <= 0
        or denominator is None
        or denominator <= 0
        or rights_price is None
        or rights_price < 0
        or identity_state
        not in {
            "EXACT_ISIN_CANDLE",
            "CERTIFIED_DATED_BRIDGE_CANDLE",
            "CERTIFIED_OFFICIAL_ISIN_TRANSITION_CANDLE",
            "CERTIFIED_OFFICIAL_SERIES_TRANSITION_CANDLE",
        }
    ):
        return None
    reference_matches = (
        bool(reference_date)
        and reference_price is not None
        and bool(reference_sha)
        and prior_date == reference_date
        and isclose(reference_price, prior_price, rel_tol=1e-12, abs_tol=1e-12)
        and prior_sha == reference_sha
    )
    state = str(factor.get("factor_state") or "")
    provisional_missing_identity = (
        state == "FACTOR_PROVISIONAL_REFERENCE_PRICE"
        and str(factor.get("reference_price_provenance_state") or "")
        == "PRIOR_ISIN_MISSING"
        and str(factor.get("reference_price_bridge_state") or "")
        != "CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE"
    )
    certified_series_repair = (
        state == "FACTOR_CERTIFIED_REFERENCE_PRICE"
        and identity_state == "CERTIFIED_OFFICIAL_SERIES_TRANSITION_CANDLE"
        and str(factor.get("reference_price_isin") or "").upper()
        == str(event.get("isin") or "").upper()
        and bool(reference_date)
        and prior_date > reference_date
    )
    unknown_terms_recovered = (
        state == "FACTOR_UNKNOWN_MISSING_TERMS"
        and reference_price is None
        and not reference_date
        and not reference_sha
    )
    if not reference_matches and not (
        provisional_missing_identity
        or certified_series_repair
        or unknown_terms_recovered
    ):
        return None
    if state == "FACTOR_CERTIFIED_REFERENCE_PRICE" and reference_matches:
        return None
    price_factor = ((denominator * prior_price) + (numerator * rights_price)) / (
        (denominator + numerator) * prior_price
    )
    return {
        "factor_state": "FACTOR_CERTIFIED_REFERENCE_PRICE",
        "price_factor": price_factor,
        "quantity_factor": (denominator + numerator) / denominator,
        "reference_price": prior_price,
        "reference_price_date": prior_date,
        "reference_price_source_sha256": prior_sha,
        "reference_price_certified": True,
        "decision": "CERTIFIED_FROM_COMPLETE_GOVERNED_CONTINUITY_CONTEXT",
        "reference_repair_reason": (
            "STALE_REFERENCE_REPLACED_BY_GOVERNED_EQUITY_SERIES_SESSION"
            if certified_series_repair
            else (
                "PROVISIONAL_MISSING_IDENTITY_REPLACED_BY_GOVERNED_SESSION"
                if provisional_missing_identity and not reference_matches
                else (
                    "OFFICIAL_TERMS_COMPLETED_WITH_GOVERNED_REFERENCE"
                    if unknown_terms_recovered
                    else "PROVISIONAL_REFERENCE_CONFIRMED"
                )
            )
        ),
        "context_id": context.get("context_id"),
        "reference_date": prior_date,
        "reference_source_sha256": prior_sha,
        "identity_state": identity_state,
        "bridge_decision": prior.get("bridge_decision"),
        "bridge_official_event_ids": prior.get("bridge_official_event_ids") or [],
        "bridge_official_source_ids": prior.get("bridge_official_source_ids") or [],
        "factor_value_mutated": False,
        "production_influence": False,
    }


def _classify(case: dict[str, Any]) -> dict[str, Any]:
    state = str(case.get("factor_state") or "")
    raw_gap = _number(case.get("raw_gap_atr"))
    adjusted_gap = _number(case.get("adjusted_gap_atr"))
    inverse_gap = _number(case.get("inverse_adjusted_gap_atr"))
    factor = _number(case.get("price_factor"))
    defect_code: str | None = None

    if state in NON_MULTIPLICATIVE_STATES:
        outcome = ValidationOutcome.FACTOR_NON_MULTIPLICATIVE
    elif state in AMBIGUOUS_FACTOR_STATES:
        outcome = ValidationOutcome.FACTOR_CONFLICTING_OFFICIAL_EVIDENCE
    elif state in UNKNOWN_FACTOR_STATES:
        outcome = ValidationOutcome.FACTOR_REQUIRES_REFERENCE_PRICE
    elif state in CERTIFIED_FACTOR_STATES and factor is None:
        outcome = ValidationOutcome.IMPLEMENTATION_DEFECT
        defect_code = "CERTIFIED_FACTOR_MISSING_VALUE"
    elif _certified_official_factor_without_testable_atr(case):
        outcome = (
            ValidationOutcome.FACTOR_CERTIFIED_OFFICIAL_TERMS_CONTINUITY_NOT_TESTABLE
        )
    elif raw_gap is None or adjusted_gap is None:
        outcome = ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE
    elif _certified_official_term_close_restoration(case):
        outcome = ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MARKET_GAP
    elif _certified_official_terms_across_noncomparable_window(case):
        outcome = ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MARKET_GAP
    elif adjusted_gap <= 2.0 or adjusted_gap < raw_gap:
        outcome = ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MARKET_GAP
    elif inverse_gap is not None and (inverse_gap <= 2.0 or inverse_gap < raw_gap):
        outcome = ValidationOutcome.IMPLEMENTATION_DEFECT
        defect_code = "POSSIBLE_FACTOR_ORIENTATION_DEFECT"
    else:
        outcome = ValidationOutcome.IMPLEMENTATION_DEFECT
        defect_code = "FACTOR_DOES_NOT_RESTORE_CONTINUITY"

    admitted = outcome in {
        ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MARKET_GAP,
        ValidationOutcome.FACTOR_CERTIFIED_OFFICIAL_TERMS_CONTINUITY_NOT_TESTABLE,
    }
    if outcome is ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MARKET_GAP:
        continuity_state = "CONTINUITY_RESTORED_OR_IMPROVED"
    elif (
        outcome
        is ValidationOutcome.FACTOR_CERTIFIED_OFFICIAL_TERMS_CONTINUITY_NOT_TESTABLE
    ):
        continuity_state = "OFFICIAL_FACTOR_CERTIFIED_CONTINUITY_NOT_TESTABLE"
    elif outcome is ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE:
        continuity_state = "INSUFFICIENT_CANDLE_CONTEXT"
    elif outcome in {
        ValidationOutcome.FACTOR_REQUIRES_REFERENCE_PRICE,
        ValidationOutcome.FACTOR_CONFLICTING_OFFICIAL_EVIDENCE,
        ValidationOutcome.FACTOR_NON_MULTIPLICATIVE,
    }:
        continuity_state = "FACTOR_REQUIRES_OFFICIAL_EVIDENCE"
    else:
        continuity_state = "FACTOR_TRANSFORMATION_DEFECT"

    return {
        **case,
        "validation_outcome": outcome.value,
        "admitted_to_replay": admitted,
        "requires_quarantine": not admitted,
        "implementation_defect_code": defect_code,
        "recomputed_continuity_state": continuity_state,
        "continuity_testable": (
            outcome
            is not (
                ValidationOutcome.FACTOR_CERTIFIED_OFFICIAL_TERMS_CONTINUITY_NOT_TESTABLE
            )
        ),
        "replay_admission_basis": (
            "OFFICIAL_TERMS_WITH_NO_COMPLETE_ATR_WINDOW"
            if outcome
            is ValidationOutcome.FACTOR_CERTIFIED_OFFICIAL_TERMS_CONTINUITY_NOT_TESTABLE
            else None
        ),
        "classification_contract": HTR010B1B_CONTRACT_VERSION,
        "market_derived_factor_autocorrection": False,
        "production_influence": False,
    }


def _certified_official_factor_without_testable_atr(
    case: Mapping[str, Any],
) -> bool:
    if case.get("action_type") == "RIGHTS":
        return False
    if case.get("factor_state") not in CERTIFIED_FACTOR_STATES:
        return False
    if case.get("official_term_factor_matches") is not True:
        return False
    if _number(case.get("price_factor")) is None:
        return False
    context = case.get("governed_continuity_context")
    if not isinstance(context, Mapping):
        return False
    selected = context.get("selected_prior_bars")
    rejected = context.get("rejected_bars")
    action_bar = context.get("action_bar")
    if (
        context.get("decision") != "INSUFFICIENT_ATR_HISTORY"
        or not isinstance(selected, list)
        or len(selected) >= 15
        or not isinstance(rejected, list)
        or rejected
        or not isinstance(action_bar, Mapping)
        or not action_bar.get("source_sha256")
    ):
        return False
    return all(
        isinstance(row, Mapping)
        and bool(row.get("source_sha256"))
        and row.get("identity_state")
        in {
            "EXACT_ISIN_CANDLE",
            "CERTIFIED_DATED_BRIDGE_CANDLE",
            "CERTIFIED_OFFICIAL_ISIN_TRANSITION_CANDLE",
            "CERTIFIED_OFFICIAL_SERIES_TRANSITION_CANDLE",
        }
        for row in selected
    )


def _certified_official_term_close_restoration(case: dict[str, Any]) -> bool:
    action_type = str(case.get("action_type") or "")
    if action_type == "RIGHTS" and (
        case.get("factor_state") != "FACTOR_CERTIFIED_REFERENCE_PRICE"
        or case.get("reference_price_certified") is not True
    ):
        return False
    if case.get("official_term_factor_matches") is not True:
        return False
    raw_close = _number(case.get("close_raw_gap_atr"))
    adjusted_close = _number(case.get("close_adjusted_gap_atr"))
    if adjusted_close is None:
        return False
    return adjusted_close <= 2.0 or (
        raw_close is not None and adjusted_close < raw_close
    )


def _certified_official_terms_across_noncomparable_window(
    case: dict[str, Any],
) -> bool:
    if case.get("official_term_factor_matches") is not True:
        return False
    if str(case.get("factor_state") or "") not in CERTIFIED_FACTOR_STATES:
        return False
    if str(case.get("action_type") or "") == "RIGHTS" and (
        case.get("factor_state") != "FACTOR_CERTIFIED_REFERENCE_PRICE"
        or case.get("reference_price_certified") is not True
    ):
        return False
    context = case.get("governed_continuity_context")
    if not isinstance(context, dict) or context.get("complete") is not True:
        return False
    action_delay = int(context.get("action_session_delay_market_sessions") or 0)
    pre_event_gap = int(context.get("pre_event_gap_market_sessions") or 0)
    return action_delay > 1 or pre_event_gap > 1


def _official_term_factor_matches(
    event: dict[str, Any],
    factor: dict[str, Any],
) -> bool | None:
    action_type = str(event.get("action_type") or "")
    observed = _number(factor.get("price_factor"))
    if observed is None:
        return None
    supplement = event.get("official_term_supplement")
    if isinstance(supplement, dict):
        supplemental_factor = _number(supplement.get("adjustment_factor"))
        if supplemental_factor is not None:
            return isclose(
                observed,
                supplemental_factor,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
    if action_type == "BONUS":
        numerator = _number(event.get("ratio_numerator"))
        denominator = _number(event.get("ratio_denominator"))
        if (
            numerator is None
            or denominator is None
            or numerator <= 0
            or denominator <= 0
        ):
            return None
        expected = denominator / (denominator + numerator)
        old_face = _number(event.get("old_face_value"))
        new_face = _number(event.get("new_face_value"))
        if (
            old_face is not None
            and new_face is not None
            and old_face > 0
            and new_face > 0
            and not isclose(old_face, new_face, rel_tol=1e-12, abs_tol=1e-12)
        ):
            expected *= new_face / old_face
        return isclose(observed, expected, rel_tol=1e-12, abs_tol=1e-12)
    if action_type in {"SPLIT", "FACE_VALUE_CHANGE"}:
        old_face = _number(event.get("old_face_value"))
        new_face = _number(event.get("new_face_value"))
        if old_face is None or new_face is None or old_face <= 0 or new_face <= 0:
            return None
        expected = new_face / old_face
        return isclose(observed, expected, rel_tol=1e-12, abs_tol=1e-12)
    if action_type != "RIGHTS":
        return None
    numerator = _number(event.get("ratio_numerator"))
    denominator = _number(event.get("ratio_denominator"))
    rights_price = _number(event.get("rights_price"))
    reference = _number(factor.get("reference_price"))
    if (
        numerator is None
        or denominator is None
        or rights_price is None
        or reference is None
        or observed is None
        or numerator <= 0
        or denominator <= 0
        or rights_price < 0
        or reference <= 0
    ):
        return None
    expected = ((denominator * reference) + (numerator * rights_price)) / (
        (denominator + numerator) * reference
    )
    return isclose(observed, expected, rel_tol=1e-12, abs_tol=1e-12)


def _event_bars(
    connection: duckdb.DuckDBPyConnection,
    isin: str,
    series: str | None,
    effective: date,
) -> list[tuple[Any, ...]]:
    if not isin:
        return []
    series_clause = "" if series is None else " AND upper(series)=?"
    prior_params: list[Any] = [effective, isin]
    current_params: list[Any] = [effective, isin]
    if series is not None:
        prior_params.append(series)
        current_params.append(series)
    select = (
        "SELECT trading_date, open_price, high_price, low_price, "
        "close_price, volume FROM daily_candle "
    )
    prior = connection.execute(
        select
        + "WHERE trading_date < ? AND upper(isin)=?"
        + series_clause
        + " ORDER BY trading_date DESC LIMIT 15",
        prior_params,
    ).fetchall()
    current = connection.execute(
        select
        + "WHERE trading_date >= ? AND upper(isin)=?"
        + series_clause
        + " ORDER BY trading_date LIMIT 1",
        current_params,
    ).fetchone()
    return [*reversed(prior), *([current] if current else [])]


def _continuity_metrics(
    bars: list[tuple[Any, ...]],
    factor: float | None,
) -> dict[str, Any]:
    previous = bars[:-1]
    current = bars[-1] if bars else None
    prior = previous[-1] if previous else None
    previous_close = float(prior[4]) if prior else None
    action_open = float(current[1]) if current else None
    atr = _atr(previous)
    raw_gap = _gap_atr(action_open, previous_close, atr, 1.0)
    adjusted_gap = _gap_atr(action_open, previous_close, atr, factor)
    inverse: float | None = None
    if factor is not None and factor != 0.0:
        inverse = 1.0 / factor
    inverse_gap = _gap_atr(action_open, previous_close, atr, inverse)
    available = bool(current and prior and atr)
    return {
        "previous_session": prior[0].isoformat() if prior else None,
        "action_session": current[0].isoformat() if current else None,
        "previous_close": previous_close,
        "action_open": action_open,
        "atr_before": atr,
        "raw_gap_atr": raw_gap,
        "adjusted_gap_atr": adjusted_gap,
        "inverse_adjusted_gap_atr": inverse_gap,
        "candle_context_state": "AVAILABLE" if available else "INSUFFICIENT",
    }


def _gap_atr(
    action_open: float | None,
    previous_close: float | None,
    atr: float | None,
    factor: float | None,
) -> float | None:
    if (
        action_open is None
        or previous_close is None
        or atr is None
        or atr <= 0
        or factor is None
        or factor <= 0
    ):
        return None
    reference = previous_close * factor
    return abs(action_open - reference) / (atr * factor)


def _atr(rows: Sequence[tuple[Any, ...]]) -> float | None:
    if len(rows) < 2:
        return None
    ranges: list[float] = []
    previous_close: float | None = None
    for row in rows[-14:]:
        high = float(row[2])
        low = float(row[3])
        close = float(row[4])
        true_range = high - low
        if previous_close is not None:
            true_range = max(
                true_range,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        ranges.append(true_range)
        previous_close = close
    return sum(ranges) / len(ranges) if ranges else None


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _number(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (str, int, float)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


__all__ = [
    "AMBIGUOUS_FACTOR_STATES",
    "CERTIFIED_FACTOR_STATES",
    "HTR010B1B_CONTRACT_VERSION",
    "NON_MULTIPLICATIVE_STATES",
    "UNKNOWN_FACTOR_STATES",
    "recompute_factor_validation",
]
