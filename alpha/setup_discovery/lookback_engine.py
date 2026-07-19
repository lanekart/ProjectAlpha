# ruff: noqa: E501 - proof explanations are auditable as complete sentences.
from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.setup_discovery.feature_engine import load_histories
from alpha.setup_discovery.models import (
    CANONICAL_LOOKBACK,
    EXPANDED_LOOKBACKS,
    LookbackEvidence,
    LookbackProofStatus,
    RawMissedSetupCase,
)

LOOKBACK_VERSION = "causal-expanded-window-proof-v1.0"
MAXIMUM_ENTRY_EXTENSION = Decimal("0.10")
_ALL_WINDOWS = (CANONICAL_LOOKBACK, *EXPANDED_LOOKBACKS)


class LookbackMismatchEvidenceEngine:
    """Retain a lookback label only when an expanded causal view proves it."""

    def evaluate(
        self,
        *,
        store: LegacyMarketDataStore,
        cases: tuple[RawMissedSetupCase, ...],
    ) -> tuple[LookbackEvidence, ...]:
        claimed = tuple(
            item for item in cases if item.failure_reason == "LOOKBACK_MISMATCH"
        )
        by_symbol: dict[str, list[RawMissedSetupCase]] = {}
        for case in claimed:
            by_symbol.setdefault(case.symbol, []).append(case)
        evidence: list[LookbackEvidence] = []
        symbols = tuple(sorted(by_symbol))
        for offset in range(0, len(symbols), 100):
            batch = symbols[offset : offset + 100]
            batch_cases = tuple(case for symbol in batch for case in by_symbol[symbol])
            histories = load_histories(store, batch_cases, include_future=False)
            for case in batch_cases:
                history = histories.get(case.symbol)
                evidence.append(_evaluate_case(case, history))
        return tuple(
            sorted(
                evidence, key=lambda item: (item.symbol, item.onset_date, item.case_id)
            )
        )


def _evaluate_case(
    case: RawMissedSetupCase,
    history: pd.DataFrame | None,
) -> LookbackEvidence:
    if history is None:
        return _result(
            case,
            status=LookbackProofStatus.DATA_INSUFFICIENT,
            canonical_detected=False,
            window_results=_unavailable_windows(),
            explanation="No point-in-time price history matched the frozen symbol identity.",
        )
    matched = history.index[history["trade_date"] == case.onset_date]
    if matched.empty:
        return _result(
            case,
            status=LookbackProofStatus.DATA_INSUFFICIENT,
            canonical_detected=False,
            window_results=_unavailable_windows(),
            explanation="The frozen onset date is absent from the historical price series.",
        )
    index = int(matched[-1])
    if index + 1 < CANONICAL_LOOKBACK:
        return _result(
            case,
            status=LookbackProofStatus.DATA_INSUFFICIENT,
            canonical_detected=False,
            window_results=_window_results(history, index, case.event_family),
            explanation=(
                f"Only {index + 1} bars were available; the canonical "
                f"{CANONICAL_LOOKBACK}-bar view could not be tested."
            ),
        )
    windows = _window_results(history, index, case.event_family)
    canonical = windows[str(CANONICAL_LOOKBACK)] == "DETECTED"
    if canonical:
        return _result(
            case,
            status=LookbackProofStatus.REJECTED_CANONICAL_WINDOW_SUFFICIENT,
            canonical_detected=True,
            window_results=windows,
            minimum_visible=CANONICAL_LOOKBACK,
            first_detectable=_first_detectable(
                history, index, CANONICAL_LOOKBACK, case.event_family
            ),
            candidate_date=case.onset_date,
            additional=0,
            extension=_entry_extension(history, index),
            extension_acceptable=True,
            explanation=(
                f"The canonical {CANONICAL_LOOKBACK}-bar view already identifies "
                f"the {case.event_family.replace('_', ' ').lower()} structure. "
                "The prior LOOKBACK_MISMATCH label is not supported."
            ),
        )
    minimum = next(
        (window for window in EXPANDED_LOOKBACKS if windows[str(window)] == "DETECTED"),
        None,
    )
    if minimum is None:
        return _result(
            case,
            status=LookbackProofStatus.REJECTED_NO_EXPANDED_LOOKBACK_PROOF,
            canonical_detected=False,
            window_results=windows,
            explanation=(
                f"No coherent setup appears at {CANONICAL_LOOKBACK}, "
                f"{', '.join(str(item) for item in EXPANDED_LOOKBACKS)} bars. "
                "The claimed mismatch has no causal window evidence."
            ),
        )
    extension = _entry_extension(history, index)
    acceptable = extension <= MAXIMUM_ENTRY_EXTENSION
    if not acceptable:
        return _result(
            case,
            status=LookbackProofStatus.REJECTED_ENTRY_TOO_EXTENDED,
            canonical_detected=False,
            window_results=windows,
            minimum_visible=minimum,
            first_detectable=_first_detectable(
                history, index, minimum, case.event_family
            ),
            candidate_date=case.onset_date,
            additional=minimum - CANONICAL_LOOKBACK,
            extension=extension,
            extension_acceptable=False,
            explanation=(
                f"The setup first becomes coherent with {minimum} bars, but price "
                f"is {extension:.2%} above the 20-EMA, beyond the "
                f"{MAXIMUM_ENTRY_EXTENSION:.0%} extension limit."
            ),
        )
    first = _first_detectable(history, index, minimum, case.event_family)
    return _result(
        case,
        status=LookbackProofStatus.CONFIRMED,
        canonical_detected=False,
        window_results=windows,
        minimum_visible=minimum,
        first_detectable=first,
        candidate_date=case.onset_date,
        additional=minimum - CANONICAL_LOOKBACK,
        extension=extension,
        extension_acceptable=True,
        explanation=(
            f"No coherent setup is present in the canonical {CANONICAL_LOOKBACK}-bar "
            f"view. With {minimum} bars, the prior trend and current "
            f"{case.event_family.replace('_', ' ').lower()} become visible; "
            f"{minimum - CANONICAL_LOOKBACK} additional bars are required and the "
            f"entry remains within the {MAXIMUM_ENTRY_EXTENSION:.0%} extension limit."
        ),
    )


def _visible_setup(
    history: pd.DataFrame,
    index: int,
    window: int,
    event_family: str,
) -> bool:
    if index + 1 < window:
        return False
    frame = history.iloc[index - window + 1 : index + 1]
    close = float(frame.iloc[-1]["close"])
    ema_20 = float(frame.iloc[-1]["ema_20"])
    ema_50 = float(frame.iloc[-1]["ema_50"])
    atr = _atr(frame.tail(15))
    volume_average = (
        float(frame["volume"].iloc[-21:-1].mean()) if len(frame) >= 21 else 0.0
    )
    volume_ratio = (
        0.0 if volume_average <= 0 else float(frame.iloc[-1]["volume"]) / volume_average
    )
    prior_high = float(frame["high"].iloc[-21:-1].max()) if len(frame) >= 21 else close
    trend_return = close / float(frame.iloc[0]["close"]) - 1.0
    slope = _slope(frame["close"])
    base_depth = float(
        frame["high"].tail(60).max() - frame["low"].tail(60).min()
    ) / float(frame["high"].tail(60).max())
    extension = 0.0 if ema_20 <= 0 else close / ema_20 - 1.0
    near_support = close >= ema_20 * 0.98 and close <= ema_20 + 2.0 * atr
    aligned = ema_20 > ema_50 and slope > 0
    if event_family in {"EMA_RECLAIM", "PULLBACK_CONTINUATION", "RETEST_HOLD"}:
        return trend_return >= 0.20 and aligned and near_support and extension <= 0.10
    if event_family in {
        "BREAKOUT_FROM_BASE",
        "VOLUME_BREAKOUT",
        "VOLATILITY_CONTRACTION_BREAKOUT",
    }:
        return (
            close >= prior_high * 0.995
            and volume_ratio >= 1.20
            and base_depth <= 0.35
            and slope >= 0
        )
    if event_family in {"TREND_REVERSAL", "EARLY_ACCUMULATION"}:
        low = float(frame["low"].min())
        recovery = 0.0 if low <= 0 else close / low - 1.0
        return close >= ema_20 and slope > 0 and recovery >= 0.15 and extension <= 0.10
    return False


def _first_detectable(
    history: pd.DataFrame,
    onset_index: int,
    window: int,
    event_family: str,
) -> date | None:
    first_index = max(window - 1, onset_index - 20)
    for index in range(first_index, onset_index + 1):
        if _visible_setup(history, index, window, event_family):
            value = history.iloc[index]["trade_date"]
            return value if isinstance(value, date) else pd.Timestamp(value).date()
    return None


def _window_results(
    history: pd.DataFrame,
    index: int,
    event_family: str,
) -> dict[str, str]:
    return {
        str(window): (
            "DATA_INSUFFICIENT"
            if index + 1 < window
            else (
                "DETECTED"
                if _visible_setup(history, index, window, event_family)
                else "NOT_DETECTED"
            )
        )
        for window in _ALL_WINDOWS
    }


def _unavailable_windows() -> dict[str, str]:
    return {str(window): "DATA_INSUFFICIENT" for window in _ALL_WINDOWS}


def _entry_extension(history: pd.DataFrame, index: int) -> Decimal:
    current = history.iloc[index]
    close = Decimal(str(current["close"]))
    ema_20 = Decimal(str(current["ema_20"]))
    if ema_20 <= 0:
        return Decimal("0")
    return max(Decimal("0"), close / ema_20 - Decimal("1")).quantize(
        Decimal("0.000001")
    )


def _atr(frame: pd.DataFrame) -> float:
    previous = frame["close"].shift(1)
    ranges = pd.concat(
        (
            frame["high"] - frame["low"],
            (frame["high"] - previous).abs(),
            (frame["low"] - previous).abs(),
        ),
        axis=1,
    ).max(axis=1)
    value = float(ranges.tail(14).mean())
    return 0.0 if not np.isfinite(value) else value


def _slope(series: pd.Series[Any]) -> float:
    values = np.asarray(series, dtype=float)
    average = float(np.mean(values))
    if len(values) < 2 or average <= 0:
        return 0.0
    return float(np.polyfit(np.arange(len(values)), values, 1)[0]) / average


def _result(
    case: RawMissedSetupCase,
    *,
    status: LookbackProofStatus,
    canonical_detected: bool,
    window_results: dict[str, str],
    explanation: str,
    minimum_visible: int | None = None,
    first_detectable: date | None = None,
    candidate_date: date | None = None,
    additional: int | None = None,
    extension: Decimal | None = None,
    extension_acceptable: bool | None = None,
) -> LookbackEvidence:
    payload = {
        "case_id": case.case_id,
        "onset_date": case.onset_date.isoformat(),
        "canonical_lookback": CANONICAL_LOOKBACK,
        "minimum_visible_lookback": minimum_visible,
        "first_detectable_date": None
        if first_detectable is None
        else first_detectable.isoformat(),
        "additional_bars_required": additional,
        "entry_extension": None if extension is None else str(extension),
        "window_results": window_results,
        "status": status.value,
        "lookback_version": LOOKBACK_VERSION,
    }
    evidence_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return LookbackEvidence(
        case_id=case.case_id,
        event_id=case.event_id,
        onset_id=case.onset_id,
        symbol=case.symbol,
        event_family=case.event_family,
        onset_date=case.onset_date,
        canonical_lookback=CANONICAL_LOOKBACK,
        canonical_setup_detected=canonical_detected,
        minimum_visible_lookback=minimum_visible,
        first_detectable_date=first_detectable,
        expanded_candidate_date=candidate_date,
        additional_bars_required=additional,
        entry_extension=extension,
        extension_acceptable=extension_acceptable,
        window_results=window_results,
        status=status,
        classification_retained=status is LookbackProofStatus.CONFIRMED,
        difference_explained=explanation,
        evidence_hash=evidence_hash,
    )


__all__ = [
    "LOOKBACK_VERSION",
    "MAXIMUM_ENTRY_EXTENSION",
    "LookbackMismatchEvidenceEngine",
]
