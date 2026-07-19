"""Composition-based point-in-time universe construction."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pandas as pd

from alpha.point_in_time_universe.corporate_actions import CorporateActionHistory
from alpha.point_in_time_universe.index_membership import IndexMembershipHistory
from alpha.point_in_time_universe.listing_history import ListingHistory
from alpha.point_in_time_universe.models import (
    DATASET_VERSION,
    SCHEMA_VERSION,
    SUPPORTED_INDICES,
    ConfidenceGrade,
    EffectiveInterval,
    EvidenceStatus,
    HistoricalSymbol,
    IndexMembershipSnapshot,
    SecurityIdentity,
    TradabilityStatus,
    UniverseCoverage,
    UniverseManifest,
    UniverseMember,
    UniverseObservation,
    UniverseSnapshot,
    deterministic_generated_at,
    stable_hash,
)
from alpha.point_in_time_universe.sector_history import SectorHistory
from alpha.point_in_time_universe.security_master import SecurityMaster


class PointInTimeUniverseBuilder:
    def __init__(
        self,
        *,
        security_master: SecurityMaster,
        listings: ListingHistory,
        indices: IndexMembershipHistory,
        sectors: SectorHistory,
        corporate_actions: CorporateActionHistory,
    ) -> None:
        self.security_master = security_master
        self.listings = listings
        self.indices = indices
        self.sectors = sectors
        self.corporate_actions = corporate_actions

    def build(
        self,
        as_of: date,
        *,
        observations: Iterable[UniverseObservation] = (),
    ) -> UniverseSnapshot:
        observed = {
            item.security_id: item for item in observations if item.as_of == as_of
        }
        index_snapshots = self.indices.all_snapshots(as_of)
        members = []
        for security_id, observation in sorted(observed.items()):
            identity = self.security_master.get(security_id)
            if identity is None:
                continue
            listing_status = self.listings.status(security_id, as_of)
            if listing_status is not TradabilityStatus.TRADABLE:
                continue
            tradability = (
                TradabilityStatus.TRADABLE
                if observation.price_available and observation.volume_available
                else TradabilityStatus.NOT_OBSERVED
            )
            sector, sector_status = self.sectors.classification(security_id, as_of)
            index_states = tuple(
                (
                    snapshot.index_name,
                    None
                    if snapshot.status is EvidenceStatus.UNKNOWN
                    else security_id in snapshot.members,
                )
                for snapshot in index_snapshots
            )
            evidence = [observation.source, identity.source]
            if sector is not None:
                evidence.append(sector.source)
            members.append(
                UniverseMember(
                    as_of=as_of,
                    security_id=security_id,
                    symbol=identity.symbol_on(as_of) or observation.symbol,
                    exchange=identity.exchange,
                    tradability=tradability,
                    index_memberships=index_states,
                    sector=None if sector is None else sector.sector,
                    sector_status=sector_status,
                    listing_valid=identity.existed_on(as_of),
                    corporate_action_status=self.corporate_actions.validity(as_of),
                    confidence=_member_confidence(
                        identity.confidence,
                        listing_status,
                        sector_status,
                        index_snapshots,
                        self.corporate_actions.validity(as_of),
                    ),
                    evidence=tuple(dict.fromkeys(evidence)),
                )
            )
        unknown_dimensions: list[str] = []
        unknown_dimensions.extend(
            snapshot.index_name
            for snapshot in index_snapshots
            if snapshot.status is EvidenceStatus.UNKNOWN
        )
        if not members or any(
            item.sector_status is EvidenceStatus.UNKNOWN for item in members
        ):
            unknown_dimensions.append("SECTOR")
        if self.corporate_actions.validity(as_of) is EvidenceStatus.UNKNOWN:
            unknown_dimensions.append("CORPORATE_ACTIONS")
        return UniverseSnapshot(
            as_of=as_of,
            members=tuple(members),
            index_snapshots=index_snapshots,
            confidence=_snapshot_confidence(tuple(members), tuple(unknown_dimensions)),
            unknown_dimensions=tuple(dict.fromkeys(unknown_dimensions)),
        )


@dataclass(frozen=True, slots=True)
class UniverseMaterializationResult:
    manifest: UniverseManifest
    paths: tuple[Path, ...]


class LegacyPointInTimeUniverseMaterializer:
    """Materialize only what same-day legacy observations can prove."""

    def materialize(
        self,
        *,
        source_database: Path,
        output_directory: Path,
    ) -> UniverseMaterializationResult:
        from alpha.point_in_time_universe.exports import UniverseExporter
        from alpha.point_in_time_universe.rendering import render_executive_report

        if not source_database.exists():
            raise FileNotFoundError(
                f"legacy market database not found: {source_database}"
            )
        output_directory.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(source_database), read_only=True) as connection:
            stats = _source_stats(connection)
            securities = _legacy_securities(connection, stats[4])
            sessions = _session_sizes(connection)
            membership_path = _export_membership_parquet(
                connection,
                securities=securities,
                output_directory=output_directory,
            )
        source_fingerprint = stable_hash(
            {
                "database": str(source_database),
                "rows": stats[0],
                "symbols": stats[1],
                "sessions": stats[2],
                "first": stats[3],
                "last": stats[4],
            }
        )
        coverage = UniverseCoverage(
            first_session=stats[3],
            last_session=stats[4],
            sessions=stats[2],
            security_master_size=len(securities),
            instrument_types_known=0,
            observation_rows=stats[0],
            sessions_with_universe=len(sessions),
            index_known_sessions=tuple((index, 0) for index in SUPPORTED_INDICES),
            sector_known_security_intervals=0,
            listing_dates_known=0,
            delisting_dates_known=0,
            corporate_actions_known=0,
            unknown_history_percentage=Decimal("100"),
            survivorship_failures=0,
            confidence=ConfidenceGrade.LOW,
        )
        manifest = UniverseManifest(
            build_id=stable_hash(
                {
                    "dataset_version": DATASET_VERSION,
                    "source_fingerprint": source_fingerprint,
                }
            )[:24],
            dataset_version=DATASET_VERSION,
            schema_version=SCHEMA_VERSION,
            generated_at=deterministic_generated_at(stats[4]),
            source_database=str(source_database),
            source_fingerprint=source_fingerprint,
            coverage=coverage,
        )
        exported = UniverseExporter().export_rows(
            output_directory=output_directory,
            manifest=manifest,
            security_master=securities,
            universe_size_by_date=tuple(
                {
                    "date": session_date,
                    "observed_universe_size": size,
                    "confidence": ConfidenceGrade.LOW,
                }
                for session_date, size in sessions
            ),
            index_membership_changes=_unknown_index_rows(sessions),
            sector_history=tuple(
                {
                    "security_id": item.security_id,
                    "effective_from": "",
                    "effective_to": "",
                    "sector": "",
                    "industry": "",
                    "source": "UNAVAILABLE",
                    "confidence": ConfidenceGrade.UNKNOWN,
                    "status": EvidenceStatus.UNKNOWN,
                }
                for item in securities
            ),
            listing_history=tuple(
                {
                    "security_id": item.security_id,
                    "symbol": item.current_symbol,
                    "first_local_observation": item.historical_symbols[
                        0
                    ].interval.effective_from,
                    "last_local_observation": item.historical_symbols[
                        0
                    ].interval.effective_to,
                    "official_listing_date": "",
                    "official_delisting_date": "",
                    "suspended_periods": "",
                    "relisting_dates": "",
                    "source": "legacy daily_prices observation range",
                    "confidence": ConfidenceGrade.LOW,
                }
                for item in securities
            ),
            corporate_actions=(),
            survivorship_audit=tuple(
                {
                    "date": session_date,
                    "observed_universe_size": size,
                    "invalid_securities": 0,
                    "future_constituent_leaks": 0,
                    "stale_sector_mappings": 0,
                    "unknown_indices": len(SUPPORTED_INDICES),
                    "unknown_sectors": size,
                    "status": "PASS_WITH_UNKNOWN_HISTORY",
                }
                for session_date, size in sessions
            ),
            executive_report=render_executive_report(manifest),
        )
        return UniverseMaterializationResult(
            manifest=manifest,
            paths=(*exported, membership_path),
        )


def _member_confidence(
    identity_confidence: ConfidenceGrade,
    listing_status: TradabilityStatus,
    sector_status: EvidenceStatus,
    index_snapshots: tuple[IndexMembershipSnapshot, ...],
    corporate_status: EvidenceStatus,
) -> ConfidenceGrade:
    if listing_status is TradabilityStatus.UNKNOWN:
        return ConfidenceGrade.UNKNOWN
    if (
        sector_status is EvidenceStatus.UNKNOWN
        or corporate_status is EvidenceStatus.UNKNOWN
        or any(item.status is EvidenceStatus.UNKNOWN for item in index_snapshots)
    ):
        return min(identity_confidence, ConfidenceGrade.LOW, key=_confidence_order)
    return identity_confidence


def _snapshot_confidence(
    members: tuple[UniverseMember, ...], unknown_dimensions: tuple[str, ...]
) -> ConfidenceGrade:
    if not members:
        return ConfidenceGrade.UNKNOWN
    if unknown_dimensions:
        return ConfidenceGrade.LOW
    return min((item.confidence for item in members), key=_confidence_order)


def _confidence_order(value: ConfidenceGrade) -> int:
    return {
        ConfidenceGrade.UNKNOWN: 0,
        ConfidenceGrade.LOW: 1,
        ConfidenceGrade.MEDIUM: 2,
        ConfidenceGrade.HIGH: 3,
        ConfidenceGrade.AUTHORITATIVE: 4,
    }[value]


def _source_stats(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[int, int, int, date, date]:
    row = connection.execute(
        """
        SELECT COUNT(*), COUNT(DISTINCT UPPER(TRIM(symbol))),
               COUNT(DISTINCT trade_date), MIN(trade_date), MAX(trade_date)
        FROM daily_prices
        WHERE symbol IS NOT NULL AND TRIM(symbol) <> ''
          AND open > 0 AND high > 0 AND low > 0 AND close > 0 AND volume >= 0
        """
    ).fetchone()
    if row is None or row[3] is None or row[4] is None:
        raise ValueError("legacy daily price population is empty")
    return int(row[0]), int(row[1]), int(row[2]), row[3], row[4]


def _legacy_securities(
    connection: duckdb.DuckDBPyConnection, dataset_end: date
) -> tuple[SecurityIdentity, ...]:
    rows = connection.execute(
        """
        SELECT
            COALESCE(NULLIF(UPPER(TRIM(exchange)), ''), 'NSE') AS exchange,
            UPPER(TRIM(symbol)) AS symbol,
            MIN(trade_date) AS first_observed,
            MAX(trade_date) AS last_observed
        FROM daily_prices
        WHERE symbol IS NOT NULL AND TRIM(symbol) <> ''
          AND open > 0 AND high > 0 AND low > 0 AND close > 0 AND volume >= 0
        GROUP BY 1, 2
        ORDER BY 1, 2
        """
    ).fetchall()
    securities = []
    for exchange, symbol, first_observed, last_observed in rows:
        security_id = stable_hash(
            {"source": "LEGACY", "exchange": exchange, "symbol": symbol}
        )[:24]
        securities.append(
            SecurityIdentity(
                security_id=security_id,
                current_symbol=str(symbol),
                historical_symbols=(
                    HistoricalSymbol(
                        symbol=str(symbol),
                        interval=EffectiveInterval(first_observed, last_observed),
                        source="legacy daily_prices observed symbol",
                        confidence=ConfidenceGrade.LOW,
                    ),
                ),
                isin=None,
                listing_date=None,
                delisting_date=None,
                exchange=str(exchange),
                instrument_type="UNKNOWN",
                active_status=(
                    "OBSERVED_ON_DATASET_END"
                    if last_observed == dataset_end
                    else "LAST_OBSERVED_BEFORE_DATASET_END_UNKNOWN_DELISTING"
                ),
                corporate_action_lineage=(),
                source="legacy daily_prices; ticker-keyed provisional identity",
                confidence=ConfidenceGrade.LOW,
            )
        )
    return tuple(securities)


def _session_sizes(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[tuple[date, int], ...]:
    return tuple(
        (row[0], int(row[1]))
        for row in connection.execute(
            """
            SELECT trade_date, COUNT(DISTINCT (
                COALESCE(NULLIF(UPPER(TRIM(exchange)), ''), 'NSE'),
                UPPER(TRIM(symbol))
            ))
            FROM daily_prices
            WHERE symbol IS NOT NULL AND TRIM(symbol) <> ''
              AND open > 0 AND high > 0 AND low > 0 AND close > 0 AND volume >= 0
            GROUP BY trade_date
            ORDER BY trade_date
            """
        ).fetchall()
    )


def _export_membership_parquet(
    connection: duckdb.DuckDBPyConnection,
    *,
    securities: tuple[SecurityIdentity, ...],
    output_directory: Path,
) -> Path:
    path = output_directory / "universe_membership.parquet"
    temporary = output_directory / ".universe_membership.parquet.tmp"
    if temporary.exists():
        temporary.unlink()
    mapping = pd.DataFrame(
        {
            "security_id": item.security_id,
            "symbol": item.current_symbol,
            "exchange": item.exchange,
        }
        for item in securities
    )
    connection.register("_pit_security_map", mapping)
    escaped = str(temporary).replace("'", "''")
    try:
        connection.execute(
            f"""
            COPY (
                SELECT DISTINCT
                    prices.trade_date AS as_of,
                    mapping.security_id,
                    UPPER(TRIM(prices.symbol)) AS symbol,
                    COALESCE(NULLIF(UPPER(TRIM(prices.exchange)), ''), 'NSE')
                        AS exchange,
                    CASE WHEN prices.volume > 0 THEN 'TRADABLE' ELSE 'UNKNOWN' END
                        AS tradability,
                    NULL::VARCHAR AS sector,
                    'UNKNOWN' AS sector_status,
                    'LOW' AS confidence
                FROM daily_prices AS prices
                JOIN _pit_security_map AS mapping
                  ON mapping.symbol = UPPER(TRIM(prices.symbol))
                 AND mapping.exchange = COALESCE(
                     NULLIF(UPPER(TRIM(prices.exchange)), ''), 'NSE'
                 )
                WHERE prices.open > 0 AND prices.high > 0
                  AND prices.low > 0 AND prices.close > 0 AND prices.volume >= 0
                ORDER BY as_of, symbol, security_id
            ) TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
    finally:
        connection.unregister("_pit_security_map")
    temporary.replace(path)
    return path


def _unknown_index_rows(
    sessions: tuple[tuple[date, int], ...],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "date": session_date,
            "index": index_name,
            "status": EvidenceStatus.UNKNOWN,
            "member_count": "",
            "additions": "",
            "removals": "",
            "source": "UNAVAILABLE",
            "confidence": ConfidenceGrade.UNKNOWN,
        }
        for session_date, _ in sessions
        for index_name in SUPPORTED_INDICES
    )


__all__ = [
    "LegacyPointInTimeUniverseMaterializer",
    "PointInTimeUniverseBuilder",
    "UniverseMaterializationResult",
]
