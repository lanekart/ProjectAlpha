from __future__ import annotations

import hashlib
import traceback
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from alpha.application.intelligence import IntelligenceApplicationService
from alpha.application.intelligence_inputs import (
    IntelligenceInputBuilder,
    IntelligenceInputSet,
)
from alpha.canonical_integrity_audit.models import (
    LEGACY_DATASET_VERSION,
    FailureCategory,
    RuntimeFailureGroup,
    RuntimeFailureRecord,
)
from alpha.canonical_universe_audit.canonical_runner import (
    CanonicalAuditInputBuilder,
    candidate_quality_order,
)
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.recommendation_intelligence import RecommendationEngine, RecommendationReport


@dataclass(frozen=True, slots=True)
class _PreRepairProvider:
    observed_on: date
    inputs: IntelligenceInputSet

    def build(self, *, observed_on: date) -> IntelligenceInputSet:
        if observed_on != self.observed_on:
            raise ValueError("runtime replay date mismatch")
        return self.inputs


class RuntimeFailureAuditEngine:
    """Reproduce the pre-repair adapter failure without mutating policy."""

    def audit_dates(
        self,
        *,
        store: LegacyMarketDataStore,
        dates: tuple[date, ...],
    ) -> tuple[RuntimeFailureRecord, ...]:
        records: list[RuntimeFailureRecord] = []
        for observed_on in sorted(set(dates)):
            records.extend(self.reproduce_day(store=store, observed_on=observed_on))
        return tuple(records)

    def reproduce_day(
        self,
        *,
        store: LegacyMarketDataStore,
        observed_on: date,
    ) -> tuple[RuntimeFailureRecord, ...]:
        prices = store.find_by_trade_date(observed_on)
        if prices.empty:
            return ()
        from alpha.analysis.signals.daily_report import DailyMarketReport

        analysis = DailyMarketReport().generate(prices)["analysis"]
        builder = CanonicalAuditInputBuilder(
            price_repository=store,
            history_window=250,
            repair_invalid_ohlcv=False,
        )
        try:
            inputs = IntelligenceInputBuilder.build(
                builder,
                observed_on=observed_on,
                analysis=analysis,
            )
        except (ArithmeticError, ValueError) as error:
            symbols = candidate_quality_order(analysis)
            history = store.find_history_by_symbols(
                symbols=symbols,
                end_date=observed_on,
                limit=250,
            )
            return self._symbol_records(
                observed_on=observed_on,
                error=error,
                symbols=symbols,
                invalid_counts=_invalid_ohlcv_counts(history),
            )
        recommendations = RecommendationEngine().build(
            inputs.recommendation_candidates,
            portfolio=inputs.recommendation_portfolio_context,
        )
        try:
            IntelligenceApplicationService(
                input_provider=_PreRepairProvider(observed_on, inputs)
            ).run(observed_on=observed_on)
        except (ArithmeticError, ValueError) as error:
            return self._records(
                observed_on=observed_on,
                error=error,
                recommendations=recommendations,
            )
        return ()

    def _records(
        self,
        *,
        observed_on: date,
        error: Exception,
        recommendations: tuple[RecommendationReport, ...],
    ) -> tuple[RuntimeFailureRecord, ...]:
        extracted = traceback.extract_tb(error.__traceback__)
        frame = extracted[-1] if extracted else None
        source_file = (
            Path(frame.filename).as_posix() if frame is not None else "UNKNOWN"
        )
        source_line = frame.lineno if frame is not None else None
        message = _safe_message(error)
        category, stage = classify_runtime_failure(error, source_file=source_file)
        failure_hash = _failure_hash(
            category=category,
            stage=stage,
            exception_type=type(error).__name__,
            message=message,
            source_file=source_file,
        )
        rows = []
        for recommendation in recommendations:
            symbol = recommendation.symbol
            drawdown = recommendation.expected_value.expected_drawdown
            rows.append(
                RuntimeFailureRecord(
                    trading_date=observed_on,
                    symbol=symbol,
                    candidate_id=f"{observed_on.isoformat()}|{symbol}",
                    pipeline_stage=stage,
                    category=category,
                    exception_type=type(error).__name__,
                    exception_message=message,
                    source_file=source_file,
                    source_line=source_line,
                    input_state={
                        "expected_drawdown": str(drawdown),
                        "expected_drawdown_unit": "fraction",
                        "allocation_contract": "0..1",
                        "final_signal": recommendation.final_signal,
                        "score": str(recommendation.final_score),
                    },
                    missing_fields=(),
                    provider_state="LEGACY_DATASET/PROVISIONAL/READ_ONLY",
                    dataset_version=LEGACY_DATASET_VERSION,
                    deterministic_reproduction=True,
                    failure_hash=failure_hash,
                    directly_triggered=drawdown > 1,
                )
            )
        return tuple(rows)

    def _symbol_records(
        self,
        *,
        observed_on: date,
        error: Exception,
        symbols: tuple[str, ...],
        invalid_counts: dict[str, int],
    ) -> tuple[RuntimeFailureRecord, ...]:
        extracted = traceback.extract_tb(error.__traceback__)
        frame = extracted[-1] if extracted else None
        source_file = (
            Path(frame.filename).as_posix() if frame is not None else "UNKNOWN"
        )
        source_line = frame.lineno if frame is not None else None
        message = _safe_message(error)
        category, stage = classify_runtime_failure(error, source_file=source_file)
        failure_hash = _failure_hash(
            category=category,
            stage=stage,
            exception_type=type(error).__name__,
            message=message,
            source_file=source_file,
        )
        return tuple(
            RuntimeFailureRecord(
                trading_date=observed_on,
                symbol=symbol,
                candidate_id=f"{observed_on.isoformat()}|{symbol}",
                pipeline_stage=stage,
                category=category,
                exception_type=type(error).__name__,
                exception_message=message,
                source_file=source_file,
                source_line=source_line,
                input_state={
                    "invalid_ohlcv_bars": str(invalid_counts.get(symbol, 0)),
                    "repair": "EXCLUDE_INVALID_BAR_NO_VALUE_SUBSTITUTION",
                },
                missing_fields=(),
                provider_state="LEGACY_DATASET/PROVISIONAL/READ_ONLY",
                dataset_version=LEGACY_DATASET_VERSION,
                deterministic_reproduction=True,
                failure_hash=failure_hash,
                directly_triggered=invalid_counts.get(symbol, 0) > 0,
            )
            for symbol in symbols
        )


def classify_runtime_failure(
    error: Exception,
    *,
    source_file: str = "",
) -> tuple[FailureCategory, str]:
    message = str(error).lower()
    source = source_file.lower()
    if "expected drawdown must be between 0 and 1" in message:
        return FailureCategory.DATA_INVALID, "PORTFOLIO_ALLOCATION_ADAPTER"
    if "bar close must be within high/low range" in message:
        return FailureCategory.DATA_INVALID, "OHLCV_HISTORY_ADAPTER"
    if "missing" in message or "not found" in message:
        return FailureCategory.DATA_MISSING, "INPUT_ADAPTER"
    if "setup" in source:
        return FailureCategory.SETUP_FAILURE, "SETUP"
    if "tradeplan" in source or "trade_plan" in source:
        return FailureCategory.TRADE_PLAN_FAILURE, "TRADE_PLAN"
    if "decision_intelligence" in source:
        return FailureCategory.APPROVAL_FAILURE, "APPROVAL"
    if "recommendation_intelligence" in source:
        return FailureCategory.SCORING_FAILURE, "SCORING"
    return FailureCategory.UNKNOWN, "UNKNOWN"


def group_runtime_failures(
    records: tuple[RuntimeFailureRecord, ...],
) -> tuple[RuntimeFailureGroup, ...]:
    grouped: dict[str, list[RuntimeFailureRecord]] = defaultdict(list)
    for record in records:
        grouped[record.failure_hash].append(record)
    groups = []
    for failure_hash, rows in grouped.items():
        first = rows[0]
        days = len({item.trading_date for item in rows})
        groups.append(
            RuntimeFailureGroup(
                failure_hash=failure_hash,
                category=first.category,
                pipeline_stage=first.pipeline_stage,
                exception_type=first.exception_type,
                exception_message=first.exception_message,
                failure_days=days,
                affected_candidates=len(rows),
                directly_triggering_candidates=sum(
                    item.directly_triggered for item in rows
                ),
                repeated=days > 1,
            )
        )
    return tuple(
        sorted(groups, key=lambda item: (-item.affected_candidates, item.failure_hash))
    )


def _failure_hash(
    *,
    category: FailureCategory,
    stage: str,
    exception_type: str,
    message: str,
    source_file: str,
) -> str:
    payload = "|".join((category.value, stage, exception_type, message, source_file))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _safe_message(error: Exception) -> str:
    return " ".join(str(error).split())[:500] or type(error).__name__


def _invalid_ohlcv_counts(frame: object) -> dict[str, int]:
    import pandas as pd

    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return {}
    required = {"symbol", "open", "high", "low", "close"}
    if not required.issubset(frame.columns):
        return {}
    high_floor = frame[["open", "low", "close"]].max(axis=1)
    low_ceiling = frame[["open", "high", "close"]].min(axis=1)
    invalid = frame.loc[
        (frame["high"] < high_floor) | (frame["low"] > low_ceiling)
    ].copy()
    if invalid.empty:
        return {}
    counts = invalid.groupby(invalid["symbol"].astype(str).str.upper()).size()
    return {str(symbol): int(count) for symbol, count in counts.items()}


__all__ = [
    "RuntimeFailureAuditEngine",
    "classify_runtime_failure",
    "group_runtime_failures",
]
