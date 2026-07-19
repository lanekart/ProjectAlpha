from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from statistics import median
from typing import Any, cast

import pandas as pd

from alpha.market_intelligence.point_in_time import (
    DIAGNOSTIC_MARKET_STATE_V2_VERSION,
    POINT_IN_TIME_SECTOR_DATASET_VERSION,
    POINT_IN_TIME_UNIVERSE_DATASET_VERSION,
    BreadthCoverageStatus,
    HistoricalDateEvidence,
    HistoricalMembershipStatus,
    HistoricalSectorState,
    HistoricalSectorStateBuilder,
    HistoricalSectorStateReport,
    PointInTimeBreadthSnapshot,
    PointInTimeMarketBreadthBuilder,
    PointInTimeSectorClassification,
    PointInTimeSecurityRecord,
    PointInTimeStatus,
    PointInTimeUniverseBuilder,
    PointInTimeUniverseDataset,
    PointInTimeUniverseRow,
    SecurityLineageMapping,
    SurvivorshipBiasAuditReport,
    SurvivorshipBiasRow,
    UniverseQualityGrade,
    build_sector_state_report,
)

DEFAULT_POINT_IN_TIME_MATERIALIZATION_PATH = Path(
    ".alpha/point_in_time_materialization.json"
)
POINT_IN_TIME_MATERIALIZATION_VERSION = "point-in-time-materialization-v1"


class PointInTimeBuildStatus(StrEnum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    INVALIDATED = "INVALIDATED"


class PointInTimeValidationStatus(StrEnum):
    VALID = "VALID"
    VALID_WITH_LIMITATIONS = "VALID_WITH_LIMITATIONS"
    PARTIAL = "PARTIAL"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class PointInTimeBuildCheckpoint:
    batch_number: int
    started_at: datetime
    completed_at: datetime | None
    from_date: date
    to_date: date
    completed_dates: tuple[date, ...]
    batch_fingerprint: str
    rows_expected: int
    rows_written: int
    breadth_rows_written: int
    sector_state_rows_written: int
    validation_status: PointInTimeValidationStatus
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PointInTimeBuildProfile:
    source_rows_read: int
    candidate_dates: int
    security_identities_processed: int
    market_dates_processed: int
    symbols_processed: int
    database_queries_executed: int
    full_table_scans: int
    batch_count: int
    rows_produced: int
    breadth_rows_produced: int
    sector_state_rows_produced: int
    elapsed_seconds_by_stage: tuple[tuple[str, Decimal], ...]
    dominant_stage: str
    peak_batch_size: int
    estimated_memory_rows: int
    cache_hits: int
    cache_misses: int
    checkpoint_writes: int


@dataclass(frozen=True, slots=True)
class PointInTimeDatasetBuildManifest:
    build_id: str
    dataset_version: str
    source_fingerprint: str
    configuration_fingerprint: str
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    requested_from: date | None
    requested_to: date | None
    batch_size: int
    total_dates: int
    completed_dates: tuple[date, ...]
    failed_dates: tuple[date, ...]
    current_checkpoint: date | None
    rows_written: int
    breadth_rows_written: int
    sector_state_rows_written: int
    status: PointInTimeBuildStatus
    failure_reason: str | None
    builder_versions: tuple[tuple[str, str], ...]
    checkpoints: tuple[PointInTimeBuildCheckpoint, ...]


@dataclass(frozen=True, slots=True)
class PointInTimeMaterializedDataset:
    materialization_version: str
    universe: PointInTimeUniverseDataset
    breadth_snapshots: tuple[PointInTimeBreadthSnapshot, ...]
    sector_state_reports: tuple[HistoricalSectorStateReport, ...]
    manifest: PointInTimeDatasetBuildManifest
    profile: PointInTimeBuildProfile


@dataclass(frozen=True, slots=True)
class PointInTimeValidationReport:
    status: PointInTimeValidationStatus
    build_id: str | None
    dataset_version: str | None
    source_fingerprint: str | None
    configuration_fingerprint: str | None
    expected_dates: int
    completed_dates: int
    duplicate_rows: int
    missing_date_batches: tuple[date, ...]
    orphan_security_ids: int
    future_membership_rows: int
    invalid_effective_ranges: int
    breadth_arithmetic_errors: int
    sector_arithmetic_errors: int
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PointInTimeBuildResult:
    materialization: PointInTimeMaterializedDataset
    validation: PointInTimeValidationReport
    persisted: bool


class PointInTimeMaterializationRepository:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_point_in_time_materialization_path(path)

    def load(self) -> PointInTimeMaterializedDataset | None:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        return _materialization_from_payload(payload)

    def save(self, materialization: PointInTimeMaterializedDataset) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(_jsonable(materialization), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


class PointInTimeMaterializationEngine:
    def build(
        self,
        *,
        records: tuple[Any, ...],
        price_repository: Any,
        from_date: date | None,
        to_date: date | None,
        batch_size: int,
        persist: bool,
        resume: bool = False,
        repository: PointInTimeMaterializationRepository | None = None,
    ) -> PointInTimeBuildResult:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        repository = repository or PointInTimeMaterializationRepository()
        all_dates = _candidate_dates(records)
        selected_dates = tuple(
            item
            for item in all_dates
            if (from_date is None or item >= from_date)
            and (to_date is None or item <= to_date)
        )
        started_at = datetime.now(tz=UTC)
        source_fingerprint = build_point_in_time_source_fingerprint(
            records=records,
            price_repository=price_repository,
            candidate_dates=selected_dates,
        )
        configuration_fingerprint = build_point_in_time_configuration_fingerprint(
            batch_size=batch_size,
            from_date=from_date,
            to_date=to_date,
        )
        existing = repository.load() if resume else None
        if existing is not None:
            _assert_resume_compatible(
                existing,
                source_fingerprint=source_fingerprint,
                configuration_fingerprint=configuration_fingerprint,
            )
        completed = set(existing.manifest.completed_dates) if existing else set()
        pending_dates = tuple(item for item in selected_dates if item not in completed)
        batches = tuple(_chunks(pending_dates, batch_size))
        elapsed: dict[str, Decimal] = {}
        query_counter = _QueryCounter(price_repository)
        source_rows = 0
        security_count = 0
        universe_parts = [existing.universe] if existing else []
        breadth_parts = list(existing.breadth_snapshots) if existing else []
        sector_parts = list(existing.sector_state_reports) if existing else []
        checkpoints = list(existing.manifest.checkpoints) if existing else []
        failed_dates: list[date] = []

        for batch_number, batch_dates in enumerate(
            batches,
            start=len(checkpoints) + 1,
        ):
            batch_started = datetime.now(tz=UTC)
            batch_records = tuple(
                record for record in records if record.evaluation_date in batch_dates
            )
            build_start = time.perf_counter()
            universe = PointInTimeUniverseBuilder(
                created_at=datetime(1970, 1, 1, tzinfo=UTC)
            ).build(
                records=batch_records,
                price_repository=query_counter,
                dry_run=not persist,
            )
            elapsed["universe membership construction"] = _elapsed(
                elapsed,
                "universe membership construction",
                build_start,
            )
            source_rows += len(universe.rows)
            security_count = max(security_count, len(universe.security_records))
            breadth_start = time.perf_counter()
            breadth = _build_breadth_batch(
                market_dates=batch_dates,
                universe_rows=universe.rows,
                price_repository=query_counter,
            )
            elapsed["breadth calculation"] = _elapsed(
                elapsed,
                "breadth calculation",
                breadth_start,
            )
            sector_start = time.perf_counter()
            sector_reports = tuple(
                build_sector_state_report(
                    dataset=universe,
                    price_repository=query_counter,
                    market_date=market_date,
                )
                for market_date in batch_dates
            )
            elapsed["sector-state calculation"] = _elapsed(
                elapsed,
                "sector-state calculation",
                sector_start,
            )
            universe_parts.append(universe)
            breadth_parts.extend(breadth)
            sector_parts.extend(sector_reports)
            checkpoint = PointInTimeBuildCheckpoint(
                batch_number=batch_number,
                started_at=batch_started,
                completed_at=datetime.now(tz=UTC),
                from_date=batch_dates[0],
                to_date=batch_dates[-1],
                completed_dates=batch_dates,
                batch_fingerprint=_stable_hash(
                    {
                        "dates": [item.isoformat() for item in batch_dates],
                        "rows": len(universe.rows),
                        "breadth": len(breadth),
                    }
                ),
                rows_expected=len(universe.rows),
                rows_written=len(universe.rows),
                breadth_rows_written=len(breadth),
                sector_state_rows_written=sum(
                    len(report.sector_states) for report in sector_reports
                ),
                validation_status=PointInTimeValidationStatus.VALID_WITH_LIMITATIONS,
            )
            checkpoints.append(checkpoint)

        merged_universe = _merge_universes(tuple(universe_parts), persist=persist)
        completed_dates = tuple(
            sorted(set(completed).union(date for batch in batches for date in batch))
        )
        status = (
            PointInTimeBuildStatus.COMPLETED
            if len(completed_dates) == len(selected_dates) and not failed_dates
            else PointInTimeBuildStatus.PARTIAL
        )
        profile = PointInTimeBuildProfile(
            source_rows_read=source_rows,
            candidate_dates=len(selected_dates),
            security_identities_processed=len(merged_universe.security_records),
            market_dates_processed=len(completed_dates),
            symbols_processed=len({row.symbol for row in merged_universe.rows}),
            database_queries_executed=query_counter.query_count,
            full_table_scans=1 if selected_dates else 0,
            batch_count=len(batches),
            rows_produced=len(merged_universe.rows),
            breadth_rows_produced=len(breadth_parts),
            sector_state_rows_produced=sum(
                len(report.sector_states) for report in sector_parts
            ),
            elapsed_seconds_by_stage=tuple(sorted(elapsed.items())),
            dominant_stage=_dominant_stage(elapsed),
            peak_batch_size=max((len(batch) for batch in batches), default=0),
            estimated_memory_rows=max(
                (len(part.rows) for part in universe_parts), default=0
            ),
            cache_hits=0,
            cache_misses=len(batches),
            checkpoint_writes=len(checkpoints),
        )
        manifest = PointInTimeDatasetBuildManifest(
            build_id=_stable_hash(
                {
                    "source": source_fingerprint,
                    "configuration": configuration_fingerprint,
                    "started_at": started_at.isoformat(),
                }
            )[:16],
            dataset_version=POINT_IN_TIME_UNIVERSE_DATASET_VERSION,
            source_fingerprint=source_fingerprint,
            configuration_fingerprint=configuration_fingerprint,
            started_at=existing.manifest.started_at if existing else started_at,
            updated_at=datetime.now(tz=UTC),
            completed_at=datetime.now(tz=UTC)
            if status is PointInTimeBuildStatus.COMPLETED
            else None,
            requested_from=from_date,
            requested_to=to_date,
            batch_size=batch_size,
            total_dates=len(selected_dates),
            completed_dates=completed_dates,
            failed_dates=tuple(failed_dates),
            current_checkpoint=completed_dates[-1] if completed_dates else None,
            rows_written=len(merged_universe.rows),
            breadth_rows_written=len(breadth_parts),
            sector_state_rows_written=sum(
                len(report.sector_states) for report in sector_parts
            ),
            status=status,
            failure_reason=None,
            builder_versions=_builder_versions(),
            checkpoints=tuple(checkpoints),
        )
        materialization = PointInTimeMaterializedDataset(
            materialization_version=POINT_IN_TIME_MATERIALIZATION_VERSION,
            universe=merged_universe,
            breadth_snapshots=tuple(
                sorted(breadth_parts, key=lambda item: item.market_date)
            ),
            sector_state_reports=tuple(
                sorted(sector_parts, key=lambda item: item.market_date)
            ),
            manifest=manifest,
            profile=profile,
        )
        validation = validate_point_in_time_materialization(materialization)
        if validation.status is PointInTimeValidationStatus.INVALID:
            materialization = replace(
                materialization,
                manifest=replace(
                    manifest,
                    status=PointInTimeBuildStatus.FAILED,
                    failure_reason="dataset validation failed",
                ),
            )
        if persist:
            repository.save(materialization)
        return PointInTimeBuildResult(
            materialization=materialization,
            validation=validation,
            persisted=persist,
        )


class _QueryCounter:
    def __init__(self, repository: Any) -> None:
        self.repository = repository
        self.query_count = 0

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        self.query_count += 1
        return cast(pd.DataFrame, self.repository.find_by_trade_date(trade_date))

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        self.query_count += 1
        return cast(
            pd.DataFrame,
            self.repository.find_history_by_symbols(
                symbols=symbols,
                end_date=end_date,
                limit=limit,
            ),
        )

    @property
    def db(self) -> Any:
        return getattr(self.repository, "db", None)


def _build_breadth_batch(
    *,
    market_dates: tuple[date, ...],
    universe_rows: tuple[PointInTimeUniverseRow, ...],
    price_repository: Any,
) -> tuple[PointInTimeBreadthSnapshot, ...]:
    rows_by_date: dict[date, tuple[PointInTimeUniverseRow, ...]] = {}
    for market_date in market_dates:
        rows_by_date[market_date] = tuple(
            row
            for row in universe_rows
            if row.market_date == market_date
            and row.membership_status is HistoricalMembershipStatus.ELIGIBLE
        )
    symbols = tuple(sorted({row.symbol for row in universe_rows}))
    history_by_symbol: dict[str, list[dict[str, Any]]] = {
        symbol: [] for symbol in symbols
    }
    if symbols and market_dates:
        history = price_repository.find_history_by_symbols(
            symbols=symbols,
            end_date=max(market_dates),
            limit=260 + len(market_dates),
        )
        for item in history.to_dict("records"):
            symbol = str(item.get("symbol", "")).upper()
            if symbol:
                history_by_symbol.setdefault(symbol, []).append(item)
    snapshots = []
    for market_date in market_dates:
        rows = rows_by_date[market_date]
        symbol_set = {row.symbol for row in rows}
        frame = price_repository.find_by_trade_date(market_date)
        if not frame.empty:
            frame = frame.copy()
            frame["symbol"] = frame["symbol"].astype(str).str.upper()
            frame = frame[frame["symbol"].isin(symbol_set)]
        advancers = decliners = unchanged = 0
        returns_1d: list[Decimal] = []
        closes: dict[str, Decimal] = {}
        for item in frame.to_dict("records"):
            close = _decimal(item.get("close"))
            opening = _decimal(item.get("open"))
            symbol = str(item.get("symbol", "")).upper()
            if close is None or opening is None:
                continue
            closes[symbol] = close
            move = close - opening
            returns_1d.append(_pct_return(close, opening) or Decimal("0"))
            if move > Decimal("0"):
                advancers += 1
            elif move < Decimal("0"):
                decliners += 1
            else:
                unchanged += 1
        dma20 = dma50 = dma200 = highs20 = lows20 = highs52 = lows52 = 0
        eligible20 = eligible50 = eligible200 = highlow20 = highlow52 = 0
        returns_5d: list[Decimal] = []
        for symbol, close in closes.items():
            close_values = []
            for row in history_by_symbol.get(symbol, []):
                trade_date = row.get("trade_date")
                if not isinstance(trade_date, date) or trade_date > market_date:
                    continue
                value = _decimal(row.get("close"))
                if value is not None:
                    close_values.append(value)
            if len(close_values) >= 5:
                returns_5d.append(
                    _pct_return(close_values[-1], close_values[-5]) or Decimal("0")
                )
            if len(close_values) >= 20:
                eligible20 += 1
                highlow20 += 1
                avg20 = sum(close_values[-20:], Decimal("0")) / Decimal("20")
                dma20 += int(close >= avg20)
                highs20 += int(close >= max(close_values[-20:]))
                lows20 += int(close <= min(close_values[-20:]))
            if len(close_values) >= 50:
                eligible50 += 1
                avg50 = sum(close_values[-50:], Decimal("0")) / Decimal("50")
                dma50 += int(close >= avg50)
            if len(close_values) >= 200:
                eligible200 += 1
                highlow52 += 1
                avg200 = sum(close_values[-200:], Decimal("0")) / Decimal("200")
                dma200 += int(close >= avg200)
                highs52 += int(close >= max(close_values[-252:]))
                lows52 += int(close <= min(close_values[-252:]))
        priced = len(closes)
        snapshots.append(
            PointInTimeBreadthSnapshot(
                market_date=market_date,
                listed_universe_size=len(rows),
                eligible_universe_size=len(rows),
                priced_universe_size=priced,
                advancers=advancers,
                decliners=decliners,
                unchanged=unchanged,
                breadth_ratio=_rate(advancers, advancers + decliners),
                advance_decline_spread=advancers - decliners,
                percent_above_20dma=_rate(dma20, eligible20),
                percent_above_50dma=_rate(dma50, eligible50),
                percent_above_200dma=_rate(dma200, eligible200),
                new_20_day_highs=highs20 if highlow20 else None,
                new_20_day_lows=lows20 if highlow20 else None,
                new_52_week_highs=highs52 if highlow52 else None,
                new_52_week_lows=lows52 if highlow52 else None,
                median_return_1d=_median(returns_1d),
                median_return_5d=_median(returns_5d),
                cross_sectional_dispersion=_dispersion(returns_1d),
                breadth_completeness=_breadth_status(priced, len(rows), eligible200),
            )
        )
    return tuple(snapshots)


def load_completed_point_in_time_materialization(
    path: Path | str | None = None,
) -> PointInTimeMaterializedDataset:
    materialization = PointInTimeMaterializationRepository(path).load()
    if materialization is None:
        raise ValueError(
            "No completed point-in-time materialization exists. Run "
            "`alpha replay point-in-time-universe-build --persist-diagnostic` first."
        )
    if materialization.manifest.status is not PointInTimeBuildStatus.COMPLETED:
        raise ValueError(
            "Point-in-time materialization is not complete; resume or validate "
            "it first."
        )
    return materialization


def validate_point_in_time_materialization(
    materialization: PointInTimeMaterializedDataset | None,
) -> PointInTimeValidationReport:
    if materialization is None:
        return PointInTimeValidationReport(
            status=PointInTimeValidationStatus.PARTIAL,
            build_id=None,
            dataset_version=None,
            source_fingerprint=None,
            configuration_fingerprint=None,
            expected_dates=0,
            completed_dates=0,
            duplicate_rows=0,
            missing_date_batches=(),
            orphan_security_ids=0,
            future_membership_rows=0,
            invalid_effective_ranges=0,
            breadth_arithmetic_errors=0,
            sector_arithmetic_errors=0,
            issues=("no materialized dataset exists",),
        )
    rows = materialization.universe.rows
    row_keys = [(row.dataset_version, row.market_date, row.security_id) for row in rows]
    duplicate_rows = len(row_keys) - len(set(row_keys))
    expected_dates = set(materialization.manifest.completed_dates)
    row_dates = {row.market_date for row in rows}
    missing = tuple(sorted(expected_dates - row_dates))
    security_ids = {
        row.security_id for row in materialization.universe.security_records
    }
    orphan_security_ids = sum(1 for row in rows if row.security_id not in security_ids)
    future_membership = 0
    for security in materialization.universe.security_records:
        for row in rows:
            if row.security_id != security.security_id:
                continue
            if security.listing_date and row.market_date < security.listing_date:
                future_membership += 1
            if security.delisting_date and row.market_date > security.delisting_date:
                future_membership += 1
    invalid_ranges = sum(
        1
        for security in materialization.universe.security_records
        if security.listing_date
        and security.delisting_date
        and security.listing_date > security.delisting_date
    )
    breadth_errors = sum(
        1
        for item in materialization.breadth_snapshots
        if item.advancers + item.decliners + item.unchanged > item.priced_universe_size
    )
    sector_errors = sum(
        1
        for report in materialization.sector_state_reports
        for item in report.sector_states
        if item.priced_securities > item.eligible_securities
    )
    issues = []
    if duplicate_rows:
        issues.append("duplicate universe rows")
    if missing:
        issues.append("missing completed date batches")
    if orphan_security_ids:
        issues.append("orphan security ids")
    if future_membership:
        issues.append("future membership rows")
    if invalid_ranges:
        issues.append("invalid effective ranges")
    if breadth_errors:
        issues.append("breadth arithmetic errors")
    if sector_errors:
        issues.append("sector arithmetic errors")
    if issues:
        status = PointInTimeValidationStatus.INVALID
    elif materialization.manifest.status is PointInTimeBuildStatus.COMPLETED:
        status = PointInTimeValidationStatus.VALID_WITH_LIMITATIONS
    else:
        status = PointInTimeValidationStatus.PARTIAL
    return PointInTimeValidationReport(
        status=status,
        build_id=materialization.manifest.build_id,
        dataset_version=materialization.manifest.dataset_version,
        source_fingerprint=materialization.manifest.source_fingerprint,
        configuration_fingerprint=materialization.manifest.configuration_fingerprint,
        expected_dates=materialization.manifest.total_dates,
        completed_dates=len(materialization.manifest.completed_dates),
        duplicate_rows=duplicate_rows,
        missing_date_batches=missing,
        orphan_security_ids=orphan_security_ids,
        future_membership_rows=future_membership,
        invalid_effective_ranges=invalid_ranges,
        breadth_arithmetic_errors=breadth_errors,
        sector_arithmetic_errors=sector_errors,
        issues=tuple(issues) or ("diagnostic current-sector limitation remains",),
    )


def build_materialized_survivorship_bias_audit(
    *,
    materialization: PointInTimeMaterializedDataset,
    price_repository: Any,
) -> SurvivorshipBiasAuditReport:
    rows = []
    material = 0
    affected_records = 0
    breadth_by_date = {
        item.market_date: item for item in materialization.breadth_snapshots
    }
    pit_symbols_by_date: dict[date, set[str]] = defaultdict(set)
    row_count_by_date: dict[date, int] = defaultdict(int)
    for row in materialization.universe.rows:
        row_count_by_date[row.market_date] += 1
        if row.membership_status is HistoricalMembershipStatus.ELIGIBLE:
            pit_symbols_by_date[row.market_date].add(row.symbol)
    current_frames = _price_frames_for_dates(
        price_repository,
        materialization.manifest.completed_dates,
    )
    for market_date in materialization.manifest.completed_dates:
        frame = current_frames.get(market_date, _empty_price_frame())
        if not frame.empty:
            frame = frame.copy()
            frame["symbol"] = frame["symbol"].astype(str).str.upper()
        current_symbols = (
            set(frame["symbol"].dropna().tolist()) if "symbol" in frame else set()
        )
        pit_symbols = pit_symbols_by_date.get(market_date, set())
        added = tuple(sorted(current_symbols - pit_symbols))
        omitted = tuple(sorted(pit_symbols - current_symbols))
        current_ratio = _same_day_breadth_ratio(frame)
        pit_snapshot = breadth_by_date.get(market_date)
        difference = None
        if (
            current_ratio is not None
            and pit_snapshot is not None
            and pit_snapshot.breadth_ratio is not None
        ):
            difference = _quantize(current_ratio - pit_snapshot.breadth_ratio)
        is_material = bool(
            added
            or omitted
            or (difference is not None and abs(difference) > Decimal("0.10"))
        )
        material += int(is_material)
        affected_records += row_count_by_date.get(market_date, 0) if is_material else 0
        rows.append(
            SurvivorshipBiasRow(
                market_date=market_date,
                current_universe_count=len(current_symbols),
                point_in_time_universe_count=len(pit_symbols),
                symbols_added_by_current_universe_bias=added,
                symbols_omitted_by_current_universe_bias=omitted,
                breadth_ratio_difference=difference,
                dma_breadth_difference=None,
                new_high_new_low_difference=None,
                regime_input_difference="breadth_ratio" if difference else "none",
                regime_classification_difference=False,
            )
        )
    return SurvivorshipBiasAuditReport(
        rows=tuple(rows),
        dates_materially_affected=material,
        candidate_records_affected=affected_records,
        recorded_reconstructed_regime_changes=0,
        outcome_conclusions_affected="not evaluated by materialized audit",
        finding="CURRENT_UNIVERSE_BIAS_IS_MATERIAL"
        if material
        else "CURRENT_UNIVERSE_BIAS_IS_LIMITED",
    )


def _price_frames_for_dates(
    price_repository: Any,
    market_dates: tuple[date, ...],
) -> dict[date, pd.DataFrame]:
    database = getattr(price_repository, "db", None)
    execute = getattr(database, "execute", None)
    if callable(execute) and market_dates:
        placeholders = ", ".join("?" for _ in market_dates)
        result = execute(
            f"""
            SELECT symbol, trade_date, open, close
            FROM daily_prices
            WHERE trade_date IN ({placeholders})
            ORDER BY trade_date, symbol
            """,
            market_dates,
        )
        frame = pd.DataFrame(
            result.fetchall(),
            columns=("symbol", "trade_date", "open", "close"),
        )
        if frame.empty:
            return {market_date: _empty_price_frame() for market_date in market_dates}
        return {
            market_date: group.reset_index(drop=True)
            for market_date, group in frame.groupby("trade_date")
            if isinstance(market_date, date)
        } | {
            market_date: _empty_price_frame()
            for market_date in market_dates
            if market_date not in set(frame["trade_date"])
        }
    return {
        market_date: price_repository.find_by_trade_date(market_date)
        for market_date in market_dates
    }


def _empty_price_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=("symbol", "trade_date", "open", "close"))


def build_point_in_time_source_fingerprint(
    *,
    records: tuple[Any, ...],
    price_repository: Any,
    candidate_dates: tuple[date, ...],
) -> str:
    payload: dict[str, Any] = {
        "candidate_dates": [item.isoformat() for item in candidate_dates],
        "records": len(records),
    }
    database = getattr(price_repository, "db", None)
    execute = getattr(database, "execute", None)
    if callable(execute) and candidate_dates:
        result = execute(
            """
            SELECT COUNT(*), MIN(trade_date), MAX(trade_date), COUNT(DISTINCT symbol)
            FROM daily_prices
            WHERE trade_date BETWEEN ? AND ?
            """,
            (min(candidate_dates), max(candidate_dates)),
        )
        row = result.fetchone()
        payload["daily_prices"] = tuple(str(item) for item in row)
    return _stable_hash(payload)


def build_point_in_time_configuration_fingerprint(
    *,
    batch_size: int,
    from_date: date | None,
    to_date: date | None,
) -> str:
    return _stable_hash(
        {
            "dataset_version": POINT_IN_TIME_UNIVERSE_DATASET_VERSION,
            "sector_dataset_version": POINT_IN_TIME_SECTOR_DATASET_VERSION,
            "diagnostic_v2_version": DIAGNOSTIC_MARKET_STATE_V2_VERSION,
            "materialization_version": POINT_IN_TIME_MATERIALIZATION_VERSION,
            "batch_size": batch_size,
            "from_date": from_date.isoformat() if from_date else None,
            "to_date": to_date.isoformat() if to_date else None,
            "membership": "same-date eligible rows with weak inferred listing ranges",
            "breadth": PointInTimeMarketBreadthBuilder.version,
            "sector_state": HistoricalSectorStateBuilder.version,
        }
    )


def render_point_in_time_build_result(
    result: PointInTimeBuildResult,
) -> tuple[str, ...]:
    manifest = result.materialization.manifest
    profile = result.materialization.profile
    return (
        "Point-in-Time Incremental Build",
        f"Build ID: {manifest.build_id}",
        f"Status: {manifest.status.value}",
        f"Persisted: {'yes' if result.persisted else 'no'}",
        f"Dataset Version: {manifest.dataset_version}",
        f"Source Fingerprint: {manifest.source_fingerprint}",
        f"Configuration Fingerprint: {manifest.configuration_fingerprint}",
        f"Completed Dates: {len(manifest.completed_dates)} / {manifest.total_dates}",
        f"Rows Written: {manifest.rows_written}",
        f"Breadth Snapshots: {manifest.breadth_rows_written}",
        f"Sector-State Rows: {manifest.sector_state_rows_written}",
        f"Checkpoints: {len(manifest.checkpoints)}",
        f"Dominant Stage: {profile.dominant_stage}",
        f"Database Queries: {profile.database_queries_executed}",
        f"Validation Status: {result.validation.status.value}",
        f"Issues: {_text_list(result.validation.issues)}",
    )


def render_point_in_time_build_status(
    materialization: PointInTimeMaterializedDataset | None,
) -> tuple[str, ...]:
    if materialization is None:
        return (
            "Point-in-Time Build Status",
            "Status: NOT MATERIALIZED",
            "Next Action: run point-in-time-universe-build --persist-diagnostic",
        )
    manifest = materialization.manifest
    return (
        "Point-in-Time Build Status",
        f"Build ID: {manifest.build_id}",
        f"Status: {manifest.status.value}",
        f"Completed Dates: {len(manifest.completed_dates)} / {manifest.total_dates}",
        f"Rows Written: {manifest.rows_written}",
        f"Current Checkpoint: {manifest.current_checkpoint or 'none'}",
        f"Source Fingerprint: {manifest.source_fingerprint}",
    )


def render_point_in_time_build_history(
    materialization: PointInTimeMaterializedDataset | None,
) -> tuple[str, ...]:
    if materialization is None:
        return ("Point-in-Time Build History", "- no materialized builds")
    lines = ["Point-in-Time Build History"]
    for checkpoint in materialization.manifest.checkpoints:
        lines.append(
            f"- batch {checkpoint.batch_number}: {checkpoint.from_date} to "
            f"{checkpoint.to_date}, rows={checkpoint.rows_written}, "
            f"status={checkpoint.validation_status.value}"
        )
    return tuple(lines)


def render_point_in_time_build_profile(
    profile: PointInTimeBuildProfile,
) -> tuple[str, ...]:
    lines = [
        "Point-in-Time Build Profile",
        f"Dominant Stage: {profile.dominant_stage}",
        f"Source Rows Read: {profile.source_rows_read}",
        f"Candidate Dates: {profile.candidate_dates}",
        f"Market Dates Processed: {profile.market_dates_processed}",
        f"Symbols Processed: {profile.symbols_processed}",
        f"Database Queries: {profile.database_queries_executed}",
        f"Full Table Scans: {profile.full_table_scans}",
        f"Batch Count: {profile.batch_count}",
        f"Peak Batch Size: {profile.peak_batch_size}",
        f"Checkpoint Writes: {profile.checkpoint_writes}",
    ]
    lines.extend(
        f"- {stage}: {seconds}s" for stage, seconds in profile.elapsed_seconds_by_stage
    )
    return tuple(lines)


def render_point_in_time_validation(
    report: PointInTimeValidationReport,
) -> tuple[str, ...]:
    return (
        "Point-in-Time Dataset Validation",
        f"Status: {report.status.value}",
        f"Build ID: {report.build_id or 'unavailable'}",
        f"Expected Dates: {report.expected_dates}",
        f"Completed Dates: {report.completed_dates}",
        f"Duplicate Rows: {report.duplicate_rows}",
        f"Missing Date Batches: {_date_list(report.missing_date_batches)}",
        f"Orphan Security IDs: {report.orphan_security_ids}",
        f"Future Membership Rows: {report.future_membership_rows}",
        f"Invalid Effective Ranges: {report.invalid_effective_ranges}",
        f"Breadth Arithmetic Errors: {report.breadth_arithmetic_errors}",
        f"Sector Arithmetic Errors: {report.sector_arithmetic_errors}",
        f"Issues: {_text_list(report.issues)}",
    )


def resolve_point_in_time_materialization_path(
    path: Path | str | None = None,
) -> Path:
    if path is not None:
        return Path(path)
    configured = os.environ.get("ALPHA_POINT_IN_TIME_MATERIALIZATION_LEDGER")
    if configured:
        return Path(configured)
    return DEFAULT_POINT_IN_TIME_MATERIALIZATION_PATH


def _assert_resume_compatible(
    existing: PointInTimeMaterializedDataset,
    *,
    source_fingerprint: str,
    configuration_fingerprint: str,
) -> None:
    if existing.manifest.status is PointInTimeBuildStatus.COMPLETED:
        return
    if existing.manifest.source_fingerprint != source_fingerprint:
        raise ValueError("cannot resume: source fingerprint changed")
    if existing.manifest.configuration_fingerprint != configuration_fingerprint:
        raise ValueError("cannot resume: configuration fingerprint changed")


def _candidate_dates(records: tuple[Any, ...]) -> tuple[date, ...]:
    return tuple(sorted({record.evaluation_date for record in records}))


def _chunks(values: tuple[date, ...], size: int) -> tuple[tuple[date, ...], ...]:
    return tuple(values[index : index + size] for index in range(0, len(values), size))


def _merge_universes(
    datasets: tuple[PointInTimeUniverseDataset, ...],
    *,
    persist: bool,
) -> PointInTimeUniverseDataset:
    rows = {
        (row.dataset_version, row.market_date, row.security_id): row
        for dataset in datasets
        for row in dataset.rows
    }
    securities = {
        row.security_id: row for dataset in datasets for row in dataset.security_records
    }
    classifications = {
        (row.security_id, row.effective_from, row.sector_name): row
        for dataset in datasets
        for row in dataset.sector_classifications
    }
    created_at = (
        datasets[0].created_at if datasets else datetime(1970, 1, 1, tzinfo=UTC)
    )
    return PointInTimeUniverseDataset(
        dataset_version=POINT_IN_TIME_UNIVERSE_DATASET_VERSION,
        rows=tuple(
            sorted(rows.values(), key=lambda item: (item.market_date, item.symbol))
        ),
        security_records=tuple(
            sorted(securities.values(), key=lambda item: item.symbol)
        ),
        sector_classifications=tuple(
            sorted(classifications.values(), key=lambda item: item.security_id)
        ),
        lineage=(),
        dry_run=not persist,
        created_at=created_at,
        non_authoritative_warning=(
            "Point-in-time materialization is diagnostic unless backed by official "
            "security-master and sector effective-period sources."
        ),
    )


def _builder_versions() -> tuple[tuple[str, str], ...]:
    return (
        ("universe", POINT_IN_TIME_UNIVERSE_DATASET_VERSION),
        ("breadth", PointInTimeMarketBreadthBuilder.version),
        ("sector_state", HistoricalSectorStateBuilder.version),
        ("materialization", POINT_IN_TIME_MATERIALIZATION_VERSION),
    )


def _elapsed(
    elapsed: dict[str, Decimal],
    stage: str,
    started: float,
) -> Decimal:
    value = Decimal(str(round(time.perf_counter() - started, 6)))
    return elapsed.get(stage, Decimal("0")) + value


def _dominant_stage(elapsed: dict[str, Decimal]) -> str:
    if not elapsed:
        return "unavailable"
    return max(elapsed.items(), key=lambda item: item[1])[0]


def _stable_hash(payload: Any) -> str:
    return sha256(
        json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    return value


def _materialization_from_payload(
    payload: dict[str, Any],
) -> PointInTimeMaterializedDataset:
    return PointInTimeMaterializedDataset(
        materialization_version=str(payload["materialization_version"]),
        universe=_universe_from_payload(payload["universe"]),
        breadth_snapshots=tuple(
            _breadth_from_payload(item) for item in payload.get("breadth_snapshots", [])
        ),
        sector_state_reports=tuple(
            _sector_report_from_payload(item)
            for item in payload.get("sector_state_reports", [])
        ),
        manifest=_manifest_from_payload(payload["manifest"]),
        profile=_profile_from_payload(payload["profile"]),
    )


def _universe_from_payload(payload: dict[str, Any]) -> PointInTimeUniverseDataset:
    return PointInTimeUniverseDataset(
        dataset_version=str(payload["dataset_version"]),
        rows=tuple(_universe_row_from_payload(row) for row in payload["rows"]),
        security_records=tuple(
            _security_from_payload(row) for row in payload["security_records"]
        ),
        sector_classifications=tuple(
            _classification_from_payload(row)
            for row in payload["sector_classifications"]
        ),
        lineage=tuple(_lineage_from_payload(row) for row in payload.get("lineage", [])),
        dry_run=bool(payload.get("dry_run", False)),
        created_at=_datetime(payload["created_at"]) or datetime(1970, 1, 1, tzinfo=UTC),
        non_authoritative_warning=str(payload["non_authoritative_warning"]),
    )


def _universe_row_from_payload(payload: dict[str, Any]) -> PointInTimeUniverseRow:
    row = dict(payload)
    row["market_date"] = date.fromisoformat(row["market_date"])
    row["membership_status"] = HistoricalMembershipStatus(row["membership_status"])
    row["source_lineage"] = tuple(row.get("source_lineage", ()))
    row["source_quality"] = UniverseQualityGrade(row["source_quality"])
    row["point_in_time_confidence"] = UniverseQualityGrade(
        row["point_in_time_confidence"]
    )
    return PointInTimeUniverseRow(**row)


def _security_from_payload(payload: dict[str, Any]) -> PointInTimeSecurityRecord:
    row = dict(payload)
    for key in (
        "effective_from",
        "effective_to",
        "listing_date",
        "delisting_date",
        "classification_effective_from",
        "classification_effective_to",
    ):
        row[key] = _date(row.get(key))
    row["source_timestamp"] = _datetime(row.get("source_timestamp"))
    row["ingested_at"] = _datetime(row["ingested_at"]) or datetime(
        1970, 1, 1, tzinfo=UTC
    )
    row["listing_date_evidence"] = HistoricalDateEvidence(row["listing_date_evidence"])
    row["delisting_date_evidence"] = HistoricalDateEvidence(
        row["delisting_date_evidence"]
    )
    row["point_in_time_status"] = PointInTimeStatus(row["point_in_time_status"])
    row["corporate_action_lineage"] = tuple(row.get("corporate_action_lineage", ()))
    row["missing_fields"] = tuple(row.get("missing_fields", ()))
    return PointInTimeSecurityRecord(**row)


def _classification_from_payload(
    payload: dict[str, Any],
) -> PointInTimeSectorClassification:
    row = dict(payload)
    row["effective_from"] = _date(row.get("effective_from"))
    row["effective_to"] = _date(row.get("effective_to"))
    row["source_timestamp"] = _datetime(row.get("source_timestamp"))
    row["point_in_time_status"] = PointInTimeStatus(row["point_in_time_status"])
    row["confidence"] = UniverseQualityGrade(row["confidence"])
    return PointInTimeSectorClassification(**row)


def _lineage_from_payload(payload: dict[str, Any]) -> SecurityLineageMapping:
    row = dict(payload)
    row["effective_date"] = _date(row.get("effective_date"))
    row["confidence"] = UniverseQualityGrade(row["confidence"])
    return SecurityLineageMapping(**row)


def _breadth_from_payload(payload: dict[str, Any]) -> PointInTimeBreadthSnapshot:
    row = dict(payload)
    row["market_date"] = date.fromisoformat(row["market_date"])
    row["breadth_completeness"] = BreadthCoverageStatus(row["breadth_completeness"])
    for key, value in tuple(row.items()):
        if value is not None and key not in {
            "market_date",
            "breadth_completeness",
        }:
            if isinstance(value, str) and _decimal_like(value):
                row[key] = Decimal(value)
    return PointInTimeBreadthSnapshot(**row)


def _sector_report_from_payload(payload: dict[str, Any]) -> HistoricalSectorStateReport:
    row = dict(payload)
    row["market_date"] = date.fromisoformat(row["market_date"])
    row["data_completeness"] = BreadthCoverageStatus(row["data_completeness"])
    row["sector_states"] = tuple(
        _sector_state_from_payload(item) for item in row.get("sector_states", [])
    )
    return HistoricalSectorStateReport(**row)


def _sector_state_from_payload(payload: dict[str, Any]) -> HistoricalSectorState:
    row = dict(payload)
    row["market_date"] = date.fromisoformat(row["market_date"])
    row["data_completeness"] = BreadthCoverageStatus(row["data_completeness"])
    for key, value in tuple(row.items()):
        if value is not None and isinstance(value, str) and _decimal_like(value):
            row[key] = Decimal(value)
    return HistoricalSectorState(**row)


def _manifest_from_payload(payload: dict[str, Any]) -> PointInTimeDatasetBuildManifest:
    row = dict(payload)
    for key in ("started_at", "updated_at", "completed_at"):
        if row.get(key):
            row[key] = datetime.fromisoformat(row[key])
    for key in ("requested_from", "requested_to", "current_checkpoint"):
        if row.get(key):
            row[key] = date.fromisoformat(row[key])
    row["status"] = PointInTimeBuildStatus(row["status"])
    row["completed_dates"] = tuple(
        date.fromisoformat(item) for item in row["completed_dates"]
    )
    row["failed_dates"] = tuple(
        date.fromisoformat(item) for item in row["failed_dates"]
    )
    row["builder_versions"] = tuple(tuple(item) for item in row["builder_versions"])
    row["checkpoints"] = tuple(
        _checkpoint_from_payload(item) for item in row.get("checkpoints", [])
    )
    return PointInTimeDatasetBuildManifest(**row)


def _checkpoint_from_payload(payload: dict[str, Any]) -> PointInTimeBuildCheckpoint:
    row = dict(payload)
    row["started_at"] = datetime.fromisoformat(row["started_at"])
    row["completed_at"] = (
        datetime.fromisoformat(row["completed_at"]) if row.get("completed_at") else None
    )
    row["from_date"] = date.fromisoformat(row["from_date"])
    row["to_date"] = date.fromisoformat(row["to_date"])
    row["completed_dates"] = tuple(
        date.fromisoformat(item) for item in row["completed_dates"]
    )
    row["validation_status"] = PointInTimeValidationStatus(row["validation_status"])
    return PointInTimeBuildCheckpoint(**row)


def _profile_from_payload(payload: dict[str, Any]) -> PointInTimeBuildProfile:
    row = dict(payload)
    row["elapsed_seconds_by_stage"] = tuple(
        (str(stage), Decimal(str(seconds)))
        for stage, seconds in row["elapsed_seconds_by_stage"]
    )
    return PointInTimeBuildProfile(**row)


def _date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))


def _datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() in {"NONE", "NAN", "<NA>"}:
        return None
    return Decimal(text)


def _pct_return(close: Decimal, previous: Decimal) -> Decimal | None:
    if previous == Decimal("0"):
        return None
    return _quantize((close - previous) / previous * Decimal("100"))


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return _quantize(Decimal(numerator) / Decimal(denominator))


def _median(values: tuple[Decimal, ...] | list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return _quantize(Decimal(str(median(values))))


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return _quantize(sum(values, Decimal("0")) / Decimal(len(values)))


def _dispersion(values: tuple[Decimal, ...] | list[Decimal]) -> Decimal | None:
    if not values:
        return None
    avg = sum(values, Decimal("0")) / Decimal(len(values))
    return _mean(tuple(abs(value - avg) for value in values))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _breadth_status(
    priced: int,
    eligible: int,
    dma200_eligible: int,
) -> BreadthCoverageStatus:
    if eligible <= 0 or priced <= 0:
        return BreadthCoverageStatus.UNUSABLE
    coverage = Decimal(priced) / Decimal(eligible)
    if coverage >= Decimal("0.95") and dma200_eligible >= max(1, eligible // 2):
        return BreadthCoverageStatus.COMPLETE
    if coverage >= Decimal("0.80"):
        return BreadthCoverageStatus.HIGH_COVERAGE
    if coverage >= Decimal("0.50"):
        return BreadthCoverageStatus.PARTIAL
    return BreadthCoverageStatus.LOW_COVERAGE


def _same_day_breadth_ratio(frame: pd.DataFrame) -> Decimal | None:
    advancers = decliners = 0
    for row in frame.to_dict("records"):
        close = _decimal(row.get("close"))
        opening = _decimal(row.get("open"))
        if close is None or opening is None:
            continue
        if close > opening:
            advancers += 1
        elif close < opening:
            decliners += 1
    return _rate(advancers, advancers + decliners)


def _decimal_like(value: str) -> bool:
    try:
        Decimal(value)
    except Exception:
        return False
    return True


def _text_list(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "none"


def _date_list(values: tuple[date, ...]) -> str:
    return ", ".join(item.isoformat() for item in values) if values else "none"


__all__ = [
    "DEFAULT_POINT_IN_TIME_MATERIALIZATION_PATH",
    "POINT_IN_TIME_MATERIALIZATION_VERSION",
    "PointInTimeBuildCheckpoint",
    "PointInTimeBuildProfile",
    "PointInTimeBuildResult",
    "PointInTimeBuildStatus",
    "PointInTimeDatasetBuildManifest",
    "PointInTimeMaterializationEngine",
    "PointInTimeMaterializationRepository",
    "PointInTimeMaterializedDataset",
    "PointInTimeValidationReport",
    "PointInTimeValidationStatus",
    "build_point_in_time_configuration_fingerprint",
    "build_point_in_time_source_fingerprint",
    "build_materialized_survivorship_bias_audit",
    "load_completed_point_in_time_materialization",
    "render_point_in_time_build_history",
    "render_point_in_time_build_profile",
    "render_point_in_time_build_result",
    "render_point_in_time_build_status",
    "render_point_in_time_validation",
    "resolve_point_in_time_materialization_path",
    "validate_point_in_time_materialization",
]
