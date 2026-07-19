from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from alpha.candidate_learning.raw_universe import RawCandidateRecord
from alpha.candidate_learning.repository import LearningLedgerRepository
from alpha.historical_replay.breakout_reference import (
    BreakoutReconstructionCandidate,
    BreakoutReferenceConfiguration,
    BreakoutReferenceIntegrityAudit,
    BreakoutReferenceMethod,
    BreakoutReferencePersistenceResult,
    BreakoutReferenceReconstructionRecord,
    BreakoutReferenceRepository,
    BreakoutSourceBar,
    HistoricalSecurityIdentity,
    PointInTimeBreakoutReferenceEngine,
    audit_breakout_reference_integrity,
    filter_breakout_reference_records,
    source_bar_from_values,
)
from alpha.market_intelligence.point_in_time import HistoricalMembershipStatus
from alpha.market_intelligence.point_in_time_store import (
    PointInTimeAnalyticalRepository,
)
from alpha.market_truth.consumer_repository import MarketTruthPriceRepository


@dataclass(frozen=True, slots=True)
class BreakoutReferenceSourceRun:
    selected_candidates: int
    records: tuple[BreakoutReferenceReconstructionRecord, ...]
    integrity: BreakoutReferenceIntegrityAudit
    persistence: BreakoutReferencePersistenceResult


def reconstruct_breakout_references_from_project_sources(
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    symbol: str | None = None,
    candidate_id: str | None = None,
    replay_run_id: str | None = None,
    reference_method: BreakoutReferenceMethod = (
        BreakoutReferenceMethod.PRIOR_SWING_HIGH
    ),
    minimum_lookback: int = 60,
    limit: int | None = None,
    force: bool = False,
    dry_run: bool = False,
    output_path: Path | str | None = None,
) -> BreakoutReferenceSourceRun:
    candidates = _filter_candidates(
        LearningLedgerRepository().load_raw_records(),
        from_date=from_date,
        to_date=to_date,
        symbol=symbol,
        candidate_id=candidate_id,
        replay_run_id=replay_run_id,
    )
    if candidate_id is not None and not candidates:
        raise ValueError(f"candidate id not found: {candidate_id}")
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        candidates = candidates[:limit]
    reference_lookback = max(120, minimum_lookback)
    configuration = BreakoutReferenceConfiguration(
        reference_method=reference_method,
        minimum_lookback=minimum_lookback,
        reference_lookback=reference_lookback,
    )
    engine = PointInTimeBreakoutReferenceEngine(configuration)
    identities = _identity_index(candidates)
    records: list[BreakoutReferenceReconstructionRecord] = []
    prices = MarketTruthPriceRepository()
    sessions = _exchange_sessions(prices, candidates)
    for raw_candidate in candidates:
        end_date = _previous_session(sessions, raw_candidate.evaluation_date)
        frame = (
            pd.DataFrame()
            if end_date is None
            else prices.find_history_by_symbols(
                symbols=(raw_candidate.symbol,),
                end_date=end_date,
                limit=configuration.reference_lookback + 1,
            )
        )
        bars = _source_bars(frame)
        identity = identities.get(
            (raw_candidate.evaluation_date, raw_candidate.symbol),
            _unresolved_identity(raw_candidate.symbol),
        )
        records.append(
            engine.reconstruct(
                candidate=BreakoutReconstructionCandidate(
                    replay_run_id=raw_candidate.run_id,
                    candidate_id=raw_candidate.raw_candidate_id,
                    historical_symbol=raw_candidate.symbol,
                    observation_date=raw_candidate.evaluation_date,
                    decision_at=None,
                    timestamp_is_proven=False,
                ),
                bars=bars,
                identity=identity,
                exchange_sessions=sessions,
            )
        )
    reconstructed = tuple(records)
    integrity = audit_breakout_reference_integrity(reconstructed)
    if reconstructed and integrity.leakage_status.value != "PASS":
        raise ValueError("reconstructed records failed the future-leakage audit")
    if reconstructed and integrity.determinism_status.value != "PASS":
        raise ValueError("reconstructed records failed the determinism audit")
    repository = BreakoutReferenceRepository(output_path)
    persistence = repository.save_records(
        reconstructed,
        dry_run=dry_run,
        force=force,
    )
    return BreakoutReferenceSourceRun(
        selected_candidates=len(candidates),
        records=reconstructed,
        integrity=integrity,
        persistence=persistence,
    )


def load_filtered_breakout_reference_records(
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    symbol: str | None = None,
    candidate_id: str | None = None,
    replay_run_id: str | None = None,
    reference_method: BreakoutReferenceMethod | None = None,
    path: Path | str | None = None,
) -> tuple[BreakoutReferenceReconstructionRecord, ...]:
    return filter_breakout_reference_records(
        BreakoutReferenceRepository(path).load_dataset().records,
        from_date=from_date,
        to_date=to_date,
        symbol=symbol,
        candidate_id=candidate_id,
        replay_run_id=replay_run_id,
        reference_method=reference_method,
    )


def count_filtered_replay_candidates(
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    symbol: str | None = None,
    candidate_id: str | None = None,
    replay_run_id: str | None = None,
) -> int:
    return len(
        _filter_candidates(
            LearningLedgerRepository().load_raw_records(),
            from_date=from_date,
            to_date=to_date,
            symbol=symbol,
            candidate_id=candidate_id,
            replay_run_id=replay_run_id,
        )
    )


def _filter_candidates(
    candidates: tuple[RawCandidateRecord, ...],
    *,
    from_date: date | None,
    to_date: date | None,
    symbol: str | None,
    candidate_id: str | None,
    replay_run_id: str | None,
) -> tuple[RawCandidateRecord, ...]:
    if from_date is not None and to_date is not None and to_date < from_date:
        raise ValueError("to_date must be on or after from_date")
    normalized_symbol = symbol.strip().upper() if symbol else None
    return tuple(
        candidate
        for candidate in candidates
        if from_date is None or candidate.evaluation_date >= from_date
        if to_date is None or candidate.evaluation_date <= to_date
        if normalized_symbol is None or candidate.symbol == normalized_symbol
        if candidate_id is None or candidate.raw_candidate_id == candidate_id
        if replay_run_id is None or candidate.run_id == replay_run_id
    )


def _identity_index(
    candidates: tuple[RawCandidateRecord, ...],
) -> dict[tuple[date, str], HistoricalSecurityIdentity]:
    repository = PointInTimeAnalyticalRepository()
    status = repository.status()
    if not status.exists or status.build_id is None:
        return {}
    result: dict[tuple[date, str], HistoricalSecurityIdentity] = {}
    dates = tuple(sorted({candidate.evaluation_date for candidate in candidates}))
    for market_date in dates:
        for row in repository.universe_rows(
            market_date=market_date,
            build_id=status.build_id,
        ):
            result[(market_date, row.symbol)] = HistoricalSecurityIdentity(
                instrument_identifier=row.security_id,
                historical_symbol=row.symbol,
                exchange="NSE",
                security_master_version=(
                    f"{status.store_version}:{status.build_id}:{row.dataset_version}"
                ),
                evidence_reference=(
                    f"{repository.path}#build={status.build_id};"
                    f"date={market_date};security={row.security_id}"
                ),
                resolved=(
                    row.membership_status is HistoricalMembershipStatus.ELIGIBLE
                    and row.price_available
                ),
                identity_quality=row.point_in_time_confidence.value,
            )
    return result


def _unresolved_identity(symbol: str) -> HistoricalSecurityIdentity:
    return HistoricalSecurityIdentity(
        instrument_identifier=None,
        historical_symbol=symbol,
        exchange="NSE",
        security_master_version=None,
        evidence_reference=None,
        resolved=False,
    )


def _exchange_sessions(
    prices: MarketTruthPriceRepository,
    candidates: tuple[RawCandidateRecord, ...],
) -> tuple[date, ...]:
    if not candidates:
        return ()
    start = min(candidate.evaluation_date for candidate in candidates) - timedelta(
        days=550
    )
    end = max(candidate.evaluation_date for candidate in candidates)
    return prices.find_trade_dates(start=start, end=end)


def _previous_session(sessions: tuple[date, ...], target: date) -> date | None:
    prior = tuple(session for session in sessions if session < target)
    return prior[-1] if prior else None


def _source_bars(frame: pd.DataFrame) -> tuple[BreakoutSourceBar, ...]:
    if frame.empty:
        return ()
    rows = frame.sort_values("trade_date").itertuples(index=False)
    return tuple(
        source_bar_from_values(
            observed_on=date.fromisoformat(str(row.trade_date)[:10]),
            open_price=row.open,
            high_price=row.high,
            low_price=row.low,
            close_price=row.close,
            volume=row.volume,
            exchange=str(row.exchange),
        )
        for row in rows
    )


__all__ = [
    "BreakoutReferenceSourceRun",
    "count_filtered_replay_candidates",
    "load_filtered_breakout_reference_records",
    "reconstruct_breakout_references_from_project_sources",
]
