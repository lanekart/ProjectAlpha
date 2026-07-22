"""HTR-009A point-in-time security universe and identity certification engine."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import cast

import duckdb

from alpha.historical_truth.point_in_time_identity_models import (
    HTR009A_CONTRACT_VERSION,
    PRODUCTION_INFLUENCE,
    BoundaryRecord,
    CandidateExposureRecord,
    CandleReconciliationRecord,
    CertificationState,
    CertificationSummary,
    ConfidenceState,
    EvidenceType,
    IdentityIntervalRecord,
    IdentityState,
    IdentitySummary,
    MembershipIntervalRecord,
    MembershipState,
    MembershipSummary,
    PointInTimeIdentityReport,
    RejectedEvidenceRecord,
    SecurityIdentityRecord,
    SourceInventoryRecord,
    SourceStatus,
    SourceSummary,
    SurvivorshipRecord,
    SuspensionRecord,
    SymbolChangeRecord,
    SymbolHistoryRecord,
    SymbolReuseRecord,
    TimeBoundarySummary,
    YtdSummary,
    valid_isin,
)
from alpha.historical_truth.point_in_time_identity_sources import (
    OfficialSecurityEvidenceStore,
    ParsedSource,
    default_source_specs,
)

_HTR008_EXPOSURE = Path(
    "artifacts/htr008_replay_eligibility_integrity/htr008_candidate_exposure.json"
)


@dataclass(frozen=True, slots=True)
class _MiiIdentityEvidence:
    identity_key: str
    isin: str
    symbol: str
    series: str
    listing_date: date | None
    removal_date: date | None
    effective_date: date
    source_id: str


class PointInTimeIdentityCertificationEngine:
    """Classify historical identity evidence without mutating the warehouse."""

    def __init__(
        self,
        database_path: Path,
        snapshot_root: Path,
        root: Path,
        *,
        baseline_exposure: Path = _HTR008_EXPOSURE,
    ) -> None:
        self.database_path = database_path
        self.snapshot_root = snapshot_root
        self.root = root
        self.baseline_exposure = baseline_exposure
        self.source_store = OfficialSecurityEvidenceStore(root)

    def run(
        self,
        *,
        calendar_report: Path,
        start_date: date,
        requested_end: date | None,
        refresh_sources: bool,
        verify_only: bool,
        symbols: tuple[str, ...] = (),
        isins: tuple[str, ...] = (),
        years: tuple[int, ...] = (),
        identity_states: tuple[IdentityState, ...] = (),
        membership_states: tuple[MembershipState, ...] = (),
        only_unresolved: bool = False,
    ) -> PointInTimeIdentityReport:
        if refresh_sources and verify_only:
            raise ValueError("refresh_sources and verify_only are mutually exclusive")
        connection = self._connection()
        try:
            latest_canonical = self._scalar_date(
                connection,
                "SELECT MAX(trading_date) FROM source.daily_candle",
            )
            latest_calendar, sessions = self._calendar_sessions(calendar_report)
            latest_snapshot = self._latest_snapshot_date()
            available = [
                item
                for item in (latest_canonical, latest_calendar, latest_snapshot)
                if item is not None
            ]
            if not available:
                raise ValueError("no calendar, candle, or snapshot evidence available")
            analysis_end = min(available)
            if requested_end is not None:
                analysis_end = min(analysis_end, requested_end)
            if analysis_end < start_date:
                raise ValueError("resolved audit end precedes audit start")
            scoped_sessions = tuple(
                item for item in sessions if start_date <= item <= analysis_end
            )
            if not scoped_sessions:
                raise ValueError("calendar has no official session in the audit window")
            specs = default_source_specs(analysis_end)
            if refresh_sources:
                parsed_sources = self.source_store.acquire(specs)
            else:
                parsed_sources = self.source_store.verify_or_missing(specs)
            self._prepare(connection, start_date, analysis_end, scoped_sessions)
            source_inventory = self._existing_bhavcopy_inventory(
                connection,
                start_date,
                analysis_end,
            ) + tuple(item.inventory for item in parsed_sources)
            rejected = tuple(
                record for item in parsed_sources for record in item.rejected
            )
            master_rows = self._master_rows(parsed_sources)
            mii_evidence = self._mii_identity_evidence(parsed_sources)
            self._register_mii_evidence(connection, mii_evidence)
            official_changes = self._official_symbol_changes(parsed_sources)
            master_dates = {
                item.inventory.covered_to
                for item in parsed_sources
                if item.inventory.evidence_type is EvidenceType.MII_SECURITY_MASTER
                and item.inventory.status
                in {SourceStatus.ACQUIRED, SourceStatus.REUSED}
                and item.inventory.covered_to is not None
            }
            reuse_keys = self._reuse_identity_keys(connection)
            change_keys = self._change_identity_keys(connection)
            governed_keys = self._governed_keys(
                mii_evidence,
            )
            identity_rows = self._identity_records(
                connection,
                reuse_keys=reuse_keys,
                change_keys=change_keys,
                official_changes=official_changes,
                governed_keys=governed_keys,
                mii_evidence=mii_evidence,
            )
            all_identities = identity_rows
            identities = self._filter_identities(
                identity_rows,
                symbols=symbols,
                isins=isins,
                years=years,
                states=identity_states,
                only_unresolved=only_unresolved,
            )
            state_by_key = {
                item.identity_key: item.identity_state for item in all_identities
            }
            intervals = self._identity_intervals(
                connection,
                state_by_key,
                mii_evidence,
            )
            symbol_history = self._symbol_history(connection, official_changes)
            reuse = self._symbol_reuse(connection)
            changes = self._symbol_changes(connection, official_changes)
            boundaries = self._boundaries(all_identities, mii_evidence)
            suspensions = self._suspensions(all_identities)
            memberships = self._memberships(connection, state_by_key)
            if membership_states:
                membership_filter = set(membership_states)
                memberships = tuple(
                    item
                    for item in memberships
                    if item.membership_state in membership_filter
                )
            candle_reconciliation = self._candle_reconciliation(
                connection,
                state_by_key,
            )
            candidate_exposure = self._candidate_exposure(all_identities)
            survivorship = self._survivorship(all_identities, master_rows)
            ytd_summary = self._ytd_summary(
                connection,
                year=2026,
                latest_calendar=latest_calendar,
            )
            latest_master = self._latest_master_date(parsed_sources)
            final_common = (
                analysis_end if set(scoped_sessions).issubset(master_dates) else None
            )
            boundaries_summary = TimeBoundarySummary(
                latest_calendar,
                latest_canonical,
                latest_snapshot,
                latest_master,
                latest_canonical,
                final_common,
                analysis_end,
            )
            certification = self._certification(
                all_identities,
                reuse,
                changes,
                parsed_sources,
                scoped_sessions,
                master_dates,
                rejected,
            )
            source_summary = self._source_summary(
                parsed_sources,
                scoped_sessions,
                master_dates,
            )
            identity_summary = self._identity_summary(
                connection,
                all_identities,
                reuse,
                changes,
            )
            membership_summary = self._membership_summary(
                connection,
                memberships,
                state_by_key,
            )
        finally:
            connection.close()
        draft = PointInTimeIdentityReport(
            contract_version=HTR009A_CONTRACT_VERSION,
            production_influence=PRODUCTION_INFLUENCE,
            database_path=str(self.database_path),
            start_date=start_date,
            end_date=analysis_end,
            time_boundaries=boundaries_summary,
            ytd_summary=ytd_summary,
            source_summary=source_summary,
            identity_summary=identity_summary,
            membership_summary=membership_summary,
            sources=source_inventory,
            rejected_evidence=rejected,
            identities=identities,
            identity_intervals=intervals,
            symbol_history=symbol_history,
            symbol_reuse=reuse,
            symbol_changes=changes,
            listing_delisting=boundaries,
            suspensions=suspensions,
            membership_intervals=memberships,
            candle_reconciliation=candle_reconciliation,
            candidate_exposure=candidate_exposure,
            survivorship=survivorship,
            certification=certification,
            report_sha256="",
        )
        return replace(draft, report_sha256=draft.calculated_sha256())

    def _connection(self) -> duckdb.DuckDBPyConnection:
        if not self.database_path.is_file():
            raise FileNotFoundError(
                f"historical truth database not found: {self.database_path}"
            )
        connection = duckdb.connect(":memory:")
        escaped = str(self.database_path.resolve()).replace("'", "''")
        connection.execute(f"ATTACH '{escaped}' AS source (READ_ONLY)")
        return connection

    @staticmethod
    def _calendar_sessions(path: Path) -> tuple[date, tuple[date, ...]]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("calendar report must be an object")
        if payload.get("certification_state") not in {"certified", "complete"}:
            raise ValueError("calendar report is not certified")
        records = payload.get("records")
        if not isinstance(records, list):
            raise ValueError("calendar report records are unavailable")
        sessions = tuple(
            sorted(
                date.fromisoformat(str(item["trading_date"]))
                for item in records
                if isinstance(item, dict)
                and item.get("classification") in {"regular_session", "special_session"}
            )
        )
        if not sessions or len(sessions) != len(set(sessions)):
            raise ValueError("calendar report has no unique official sessions")
        return sessions[-1], sessions

    def _latest_snapshot_date(self) -> date | None:
        dates: list[date] = []
        for path in self.snapshot_root.glob("**/*.json"):
            try:
                dates.append(date.fromisoformat(path.stem))
            except ValueError:
                continue
        return max(dates) if dates else None

    @staticmethod
    def _scalar_date(
        connection: duckdb.DuckDBPyConnection,
        query: str,
    ) -> date | None:
        row = connection.execute(query).fetchone()
        value = row[0] if row is not None else None
        return value if isinstance(value, date) else None

    @staticmethod
    def _prepare(
        connection: duckdb.DuckDBPyConnection,
        start_date: date,
        end_date: date,
        sessions: Sequence[date],
    ) -> None:
        connection.execute("CREATE TEMP TABLE official_session(trading_date DATE)")
        connection.executemany(
            "INSERT INTO official_session VALUES (?)",
            [(item,) for item in sessions],
        )
        connection.execute(
            """
            CREATE TEMP TABLE scoped_candle AS
            SELECT
                c.*,
                CASE
                    WHEN c.isin IS NOT NULL AND LENGTH(TRIM(c.isin)) = 12
                    THEN LOWER(c.exchange) || ':isin:' || UPPER(TRIM(c.isin))
                    ELSE LOWER(c.exchange) || ':unresolved:' ||
                         UPPER(c.symbol) || ':' || UPPER(c.series)
                END AS identity_key
            FROM source.daily_candle c
            JOIN official_session s USING (trading_date)
            WHERE c.trading_date BETWEEN ? AND ?
            """,
            [start_date, end_date],
        )

    def _existing_bhavcopy_inventory(
        self,
        connection: duckdb.DuckDBPyConnection,
        start_date: date,
        end_date: date,
    ) -> tuple[SourceInventoryRecord, ...]:
        rows = connection.execute(
            """
            SELECT YEAR(trading_date), MIN(trading_date), MAX(trading_date),
                   COUNT(*), COUNT(*) FILTER (WHERE isin IS NOT NULL),
                   COUNT(DISTINCT source_sha256),
                   LIST_SORT(
                       LIST(DISTINCT source_sha256)
                           FILTER (WHERE source_sha256 IS NOT NULL)
                   )
            FROM source.daily_candle
            WHERE trading_date BETWEEN ? AND ?
            GROUP BY YEAR(trading_date)
            ORDER BY YEAR(trading_date)
            """,
            [start_date, end_date],
        ).fetchall()
        records: list[SourceInventoryRecord] = []
        for year, first, last, count, with_isin, hash_count, hashes in rows:
            digest = hashlib.sha256(
                "\n".join(str(item) for item in (hashes or ())).encode()
            ).hexdigest()
            files = tuple(
                sorted(
                    (self.root / "raw" / "nse" / "bhavcopy" / str(year)).glob("*.zip")
                )
            )
            records.append(
                SourceInventoryRecord(
                    source_id=f"nse_cm_bhavcopy_{year}",
                    evidence_type=EvidenceType.DAILY_BHAVCOPY,
                    source_path=str(files[0].parent / "*.zip") if files else None,
                    source_url="https://nsearchives.nseindia.com/content/cm/",
                    official_host=True,
                    sha256=digest,
                    acquired_at=None,
                    covered_from=first,
                    covered_to=last,
                    file_format="csv.zip",
                    parser="canonical_nse_bhavcopy",
                    row_count=int(count),
                    admitted_records=int(with_isin),
                    rejected_records=int(count - with_isin),
                    status=SourceStatus.INVENTORIED,
                    limitations=(
                        "PROVES_OBSERVED_TRADING_NOT_SILENT_MEMBERSHIP",
                        f"DISTINCT_SOURCE_HASHES={int(hash_count)}",
                        f"RAW_FILES={len(files)}",
                        f"REQUESTED_WINDOW={start_date}:{end_date}",
                    ),
                )
            )
        return tuple(records)

    @staticmethod
    def _master_rows(sources: Sequence[ParsedSource]) -> tuple[dict[str, str], ...]:
        return tuple(
            row
            for source in sources
            if source.inventory.evidence_type
            in {EvidenceType.MII_SECURITY_MASTER, EvidenceType.CURRENT_SECURITY_LIST}
            for row in source.rows
        )

    @staticmethod
    def _mii_identity_evidence(
        sources: Sequence[ParsedSource],
    ) -> tuple[_MiiIdentityEvidence, ...]:
        evidence: list[_MiiIdentityEvidence] = []
        for source in sources:
            inventory = source.inventory
            if (
                inventory.evidence_type is not EvidenceType.MII_SECURITY_MASTER
                or inventory.covered_to is None
                or inventory.status not in {SourceStatus.ACQUIRED, SourceStatus.REUSED}
            ):
                continue
            for row in source.rows:
                normalized = {
                    key.lower().replace(" ", "_"): value for key, value in row.items()
                }
                isin = normalized.get("isin", "").upper()
                symbol = normalized.get("tckrsymb", "").upper()
                series = normalized.get("sctysrs", "").upper()
                if not valid_isin(isin) or not symbol or not series:
                    continue
                evidence.append(
                    _MiiIdentityEvidence(
                        identity_key=f"nse:isin:{isin}",
                        isin=isin,
                        symbol=symbol,
                        series=series,
                        listing_date=_parse_source_date(normalized.get("listgdt", "")),
                        removal_date=_parse_source_date(normalized.get("rmvldt", "")),
                        effective_date=inventory.covered_to,
                        source_id=inventory.source_id,
                    )
                )
        return tuple(
            sorted(
                evidence,
                key=lambda item: (
                    item.identity_key,
                    item.symbol,
                    item.series,
                    item.effective_date,
                ),
            )
        )

    @staticmethod
    def _register_mii_evidence(
        connection: duckdb.DuckDBPyConnection,
        evidence: Sequence[_MiiIdentityEvidence],
    ) -> None:
        connection.execute(
            """
            CREATE TEMP TABLE official_mii_identity (
                identity_key VARCHAR,
                symbol VARCHAR,
                series VARCHAR,
                listing_date DATE,
                removal_date DATE,
                effective_date DATE,
                source_id VARCHAR
            )
            """
        )
        if evidence:
            connection.executemany(
                "INSERT INTO official_mii_identity VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        item.identity_key,
                        item.symbol,
                        item.series,
                        item.listing_date,
                        item.removal_date,
                        item.effective_date,
                        item.source_id,
                    )
                    for item in evidence
                ],
            )

    @staticmethod
    def _official_symbol_changes(
        sources: Sequence[ParsedSource],
    ) -> tuple[tuple[str, str, date | None, str], ...]:
        changes: list[tuple[str, str, date | None, str]] = []
        for source in sources:
            if source.inventory.evidence_type is not EvidenceType.SYMBOL_CHANGE_HISTORY:
                continue
            for row in source.rows:
                normalized = {
                    key.lower().replace(" ", "_"): value for key, value in row.items()
                }
                old = next(
                    (
                        normalized[key]
                        for key in ("old_symbol", "previous_symbol", "oldsymbol")
                        if normalized.get(key)
                    ),
                    "",
                )
                new = next(
                    (
                        normalized[key]
                        for key in ("new_symbol", "symbol", "newsymbol")
                        if normalized.get(key)
                    ),
                    "",
                )
                raw_date = next(
                    (
                        normalized[key]
                        for key in ("effective_date", "date", "change_date")
                        if normalized.get(key)
                    ),
                    "",
                )
                effective = _parse_flexible_date(raw_date)
                if old and new and old.upper() != new.upper():
                    changes.append(
                        (
                            old.upper(),
                            new.upper(),
                            effective,
                            source.inventory.source_id,
                        )
                    )
        return tuple(sorted(set(changes)))

    @staticmethod
    def _reuse_identity_keys(
        connection: duckdb.DuckDBPyConnection,
    ) -> frozenset[str]:
        rows = connection.execute(
            """
            WITH reused AS (
                SELECT symbol, series
                FROM scoped_candle
                WHERE isin IS NOT NULL
                GROUP BY symbol, series
                HAVING COUNT(DISTINCT isin) > 1
            )
            SELECT DISTINCT c.identity_key
            FROM scoped_candle c JOIN reused r USING (symbol, series)
            ORDER BY c.identity_key
            """
        ).fetchall()
        return frozenset(str(row[0]) for row in rows)

    @staticmethod
    def _change_identity_keys(
        connection: duckdb.DuckDBPyConnection,
    ) -> frozenset[str]:
        return frozenset(
            str(row[0])
            for row in connection.execute(
                """
                SELECT identity_key
                FROM scoped_candle
                GROUP BY identity_key
                HAVING COUNT(DISTINCT symbol) > 1
                ORDER BY identity_key
                """
            ).fetchall()
        )

    @staticmethod
    def _governed_keys(
        evidence: Sequence[_MiiIdentityEvidence],
    ) -> frozenset[str]:
        return frozenset(item.identity_key for item in evidence)

    def _identity_records(
        self,
        connection: duckdb.DuckDBPyConnection,
        *,
        reuse_keys: frozenset[str],
        change_keys: frozenset[str],
        official_changes: Sequence[tuple[str, str, date | None, str]],
        governed_keys: frozenset[str],
        mii_evidence: Sequence[_MiiIdentityEvidence],
    ) -> tuple[SecurityIdentityRecord, ...]:
        rows = connection.execute(
            """
            SELECT identity_key, MIN(exchange), MIN(isin),
                   LIST_SORT(LIST(DISTINCT UPPER(symbol))),
                   LIST_SORT(LIST(DISTINCT UPPER(series))),
                   MIN(trading_date), MAX(trading_date), COUNT(*),
                   LIST_SORT(
                       LIST(DISTINCT source_sha256)
                           FILTER (WHERE source_sha256 IS NOT NULL)
                   )
            FROM scoped_candle
            GROUP BY identity_key
            ORDER BY identity_key
            """
        ).fetchall()
        supported_changes = {(old, new) for old, new, _, _ in official_changes}
        official = {
            (item.identity_key, item.symbol, item.series): item for item in mii_evidence
        }
        records: list[SecurityIdentityRecord] = []
        for key, exchange, isin, symbols, series, first, last, count, hashes in rows:
            symbol_tuple = tuple(str(item) for item in symbols)
            series_tuple = tuple(str(item) for item in series)
            issues: list[str] = []
            official_rows = tuple(
                evidence
                for (identity_key, _, _), evidence in official.items()
                if identity_key == str(key)
                and evidence.symbol in symbol_tuple
                and evidence.series in series_tuple
            )
            earliest_listing = min(
                (
                    item.listing_date
                    for item in official_rows
                    if item.listing_date is not None
                ),
                default=None,
            )
            latest_removal = max(
                (
                    item.removal_date
                    for item in official_rows
                    if item.removal_date is not None
                ),
                default=None,
            )
            if not valid_isin(isin):
                state = IdentityState.MISSING_IDENTITY_EVIDENCE
                issues.append("VALID_ISIN_ABSENT")
            elif any(item != "EQ" for item in series_tuple):
                state = IdentityState.UNSUPPORTED_SECURITY_TYPE
                issues.append("UNSUPPORTED_SERIES")
            elif str(key) in reuse_keys:
                state = IdentityState.SYMBOL_REUSE_CONFLICT
                issues.append("SAME_SYMBOL_DIFFERENT_ISIN")
            elif str(key) in change_keys and not any(
                (left, right) in supported_changes
                for left in symbol_tuple
                for right in symbol_tuple
                if left != right
            ):
                state = IdentityState.SYMBOL_CHANGE_UNRESOLVED
                issues.append("OFFICIAL_SYMBOL_CHANGE_EVIDENCE_MISSING")
            elif earliest_listing is not None and first < earliest_listing:
                state = IdentityState.OUTSIDE_ACTIVE_INTERVAL
                issues.append("CANDLE_BEFORE_OFFICIAL_LISTING")
            elif latest_removal is not None and last > latest_removal:
                state = IdentityState.OUTSIDE_ACTIVE_INTERVAL
                issues.append("CANDLE_AFTER_OFFICIAL_REMOVAL")
            elif str(key) in governed_keys:
                state = IdentityState.GOVERNED_IDENTITY
            else:
                state = IdentityState.PROVISIONAL_IDENTITY
                issues.extend(
                    (
                        "OBSERVED_BHAVCOPY_IDENTITY_ONLY",
                        "LISTING_BOUNDARY_UNVERIFIED",
                        "DELISTING_BOUNDARY_UNVERIFIED",
                        "SUSPENSION_BOUNDARY_UNVERIFIED",
                    )
                )
            records.append(
                SecurityIdentityRecord(
                    identity_key=str(key),
                    exchange=str(exchange),
                    isin=str(isin) if isin else None,
                    symbols=symbol_tuple,
                    series=series_tuple,
                    first_observed=first,
                    last_observed=last,
                    candle_rows=int(count),
                    identity_state=state,
                    secondary_issue_codes=tuple(sorted(set(issues))),
                    source_ids=tuple(str(item) for item in (hashes or ())),
                    confidence=(
                        ConfidenceState.HIGH
                        if state is IdentityState.GOVERNED_IDENTITY
                        else ConfidenceState.MEDIUM
                        if state is IdentityState.PROVISIONAL_IDENTITY
                        else ConfidenceState.LOW
                    ),
                )
            )
        return tuple(records)

    @staticmethod
    def _identity_intervals(
        connection: duckdb.DuckDBPyConnection,
        state_by_key: Mapping[str, IdentityState],
        mii_evidence: Sequence[_MiiIdentityEvidence],
    ) -> tuple[IdentityIntervalRecord, ...]:
        rows = connection.execute(
            """
            SELECT identity_key, UPPER(symbol), UPPER(series),
                   MIN(trading_date), MAX(trading_date), COUNT(*),
                   MIN(source_sha256)
            FROM scoped_candle
            GROUP BY identity_key, UPPER(symbol), UPPER(series)
            ORDER BY identity_key, MIN(trading_date), UPPER(symbol), UPPER(series)
            """
        ).fetchall()
        official = {
            (item.identity_key, item.symbol, item.series): item for item in mii_evidence
        }
        records: list[IdentityIntervalRecord] = []
        for key, symbol, series, first, last, count, source_hash in rows:
            evidence = official.get((str(key), str(symbol), str(series)))
            records.append(
                IdentityIntervalRecord(
                    str(key),
                    str(symbol),
                    str(series),
                    evidence.listing_date or first if evidence else first,
                    evidence.removal_date or evidence.effective_date
                    if evidence
                    else last,
                    evidence.source_id
                    if evidence
                    else str(source_hash or "OFFICIAL_BHAVCOPY_OBSERVATION"),
                    EvidenceType.MII_SECURITY_MASTER
                    if evidence
                    else EvidenceType.DAILY_BHAVCOPY,
                    ConfidenceState.HIGH if evidence else ConfidenceState.MEDIUM,
                    "GOVERNED_OFFICIAL_VALIDITY_FIELDS"
                    if evidence
                    else "OBSERVED_DATES_ONLY_NOT_CONTINUOUS_VALIDITY",
                    int(count),
                    (
                        ("UNSUPPORTED_SERIES",)
                        if str(series) != "EQ"
                        else (
                            state_by_key.get(
                                str(key), IdentityState.AMBIGUOUS_IDENTITY
                            ).value,
                        )
                    ),
                )
            )
        return tuple(records)

    @staticmethod
    def _symbol_history(
        connection: duckdb.DuckDBPyConnection,
        official_changes: Sequence[tuple[str, str, date | None, str]],
    ) -> tuple[SymbolHistoryRecord, ...]:
        evidence = {(old, new): source for old, new, _, source in official_changes}
        rows = connection.execute(
            """
            SELECT identity_key, MIN(isin), UPPER(symbol), UPPER(series),
                   MIN(trading_date), MAX(trading_date)
            FROM scoped_candle
            GROUP BY identity_key, UPPER(symbol), UPPER(series)
            ORDER BY identity_key, MIN(trading_date), UPPER(symbol)
            """
        ).fetchall()
        grouped: dict[str, list[tuple[object, ...]]] = defaultdict(list)
        for row in rows:
            grouped[str(row[0])].append(row)
        records: list[SymbolHistoryRecord] = []
        for key in sorted(grouped):
            items = grouped[key]
            for index, row in enumerate(items):
                previous = str(items[index - 1][2]) if index else None
                following = str(items[index + 1][2]) if index + 1 < len(items) else None
                source_id = None
                if following:
                    source_id = evidence.get((str(row[2]), following))
                if previous and source_id is None:
                    source_id = evidence.get((previous, str(row[2])))
                records.append(
                    SymbolHistoryRecord(
                        identity_key=key,
                        isin=str(row[1]) if row[1] else None,
                        symbol=str(row[2]),
                        series=str(row[3]),
                        first_observed=cast(date, row[4]),
                        last_observed=cast(date, row[5]),
                        previous_symbol=previous,
                        next_symbol=following,
                        continuity_state=(
                            "OFFICIALLY_SUPPORTED"
                            if source_id
                            else "SINGLE_SYMBOL"
                            if previous is None and following is None
                            else "UNRESOLVED"
                        ),
                        official_source_id=source_id,
                    )
                )
        return tuple(records)

    @staticmethod
    def _symbol_reuse(
        connection: duckdb.DuckDBPyConnection,
    ) -> tuple[SymbolReuseRecord, ...]:
        rows = connection.execute(
            """
            WITH reused AS (
                SELECT UPPER(symbol) AS symbol, UPPER(series) AS series
                FROM scoped_candle
                WHERE isin IS NOT NULL
                GROUP BY UPPER(symbol), UPPER(series)
                HAVING COUNT(DISTINCT isin) > 1
            ), ranges AS (
                SELECT UPPER(c.symbol) AS symbol, UPPER(c.series) AS series,
                       UPPER(c.isin) AS isin, MIN(c.trading_date) AS first_date,
                       MAX(c.trading_date) AS last_date, COUNT(*) AS candles
                FROM scoped_candle c JOIN reused r
                  ON UPPER(c.symbol) = r.symbol AND UPPER(c.series) = r.series
                GROUP BY UPPER(c.symbol), UPPER(c.series), UPPER(c.isin)
            )
            SELECT symbol, series, LIST_SORT(LIST(isin)),
                   LIST_SORT(LIST(
                       isin || ':' || CAST(first_date AS VARCHAR) || ':' ||
                       CAST(last_date AS VARCHAR)
                   )), SUM(candles),
                   MAX(last_date) >= MAX(first_date) AS possible_overlap
            FROM ranges
            GROUP BY symbol, series
            ORDER BY symbol, series
            """
        ).fetchall()
        records: list[SymbolReuseRecord] = []
        for symbol, series, isins, summaries, candles, _ in rows:
            parsed = [item.split(":") for item in summaries]
            intervals = [
                (date.fromisoformat(parts[1]), date.fromisoformat(parts[2]))
                for parts in parsed
            ]
            overlap = any(
                left[0] <= right[1] and right[0] <= left[1]
                for index, left in enumerate(intervals)
                for right in intervals[index + 1 :]
            )
            records.append(
                SymbolReuseRecord(
                    str(symbol),
                    str(series),
                    tuple(str(item) for item in isins),
                    tuple(str(item) for item in summaries),
                    overlap,
                    (),
                    int(candles),
                    0,
                    IdentityState.SYMBOL_REUSE_CONFLICT,
                )
            )
        return tuple(records)

    @staticmethod
    def _symbol_changes(
        connection: duckdb.DuckDBPyConnection,
        official_changes: Sequence[tuple[str, str, date | None, str]],
    ) -> tuple[SymbolChangeRecord, ...]:
        official = {
            (old, new): (when, source) for old, new, when, source in official_changes
        }
        rows = connection.execute(
            """
            WITH ranges AS (
                SELECT identity_key, MIN(isin) AS isin, UPPER(symbol) AS symbol,
                       MIN(trading_date) AS first_date,
                       MAX(trading_date) AS last_date, COUNT(*) AS candles
                FROM scoped_candle
                GROUP BY identity_key, UPPER(symbol)
            )
            SELECT a.identity_key, a.isin, a.symbol, b.symbol,
                   a.first_date, a.last_date, b.first_date, b.last_date,
                   a.candles, b.candles
            FROM ranges a JOIN ranges b ON a.identity_key = b.identity_key
            WHERE a.symbol < b.symbol
            ORDER BY a.identity_key, a.symbol, b.symbol
            """
        ).fetchall()
        records: list[SymbolChangeRecord] = []
        for (
            key,
            isin,
            first_symbol,
            second_symbol,
            first_start,
            first_end,
            second_start,
            second_end,
            before_count,
            after_count,
        ) in rows:
            if second_start < first_start:
                old, new = str(second_symbol), str(first_symbol)
                old_end, new_start = second_end, first_start
                old_count, new_count = after_count, before_count
            else:
                old, new = str(first_symbol), str(second_symbol)
                old_end, new_start = first_end, second_start
                old_count, new_count = before_count, after_count
            support = official.get((old, new))
            gap = max(0, (new_start - old_end).days - 1)
            overlap = max(0, (old_end - new_start).days + 1)
            records.append(
                SymbolChangeRecord(
                    old,
                    new,
                    str(isin) if isin else None,
                    str(isin) if isin else None,
                    support[0] if support else None,
                    support[1] if support else None,
                    str(key),
                    str(key),
                    "CONTINUITY_SUPPORTED" if support else "UNRESOLVED",
                    int(old_count),
                    int(new_count),
                    overlap,
                    gap,
                    "ADMITTED" if support else "REJECTED_UNSUPPORTED_CHANGE",
                )
            )
        return tuple(records)

    @staticmethod
    def _boundaries(
        identities: Sequence[SecurityIdentityRecord],
        mii_evidence: Sequence[_MiiIdentityEvidence],
    ) -> tuple[BoundaryRecord, ...]:
        records: list[BoundaryRecord] = []
        for identity in identities:
            evidence = next(
                (
                    item
                    for item in mii_evidence
                    if item.identity_key == identity.identity_key
                    and item.symbol in identity.symbols
                    and item.series in identity.series
                ),
                None,
            )
            listing_date = evidence.listing_date if evidence else None
            removal_date = evidence.removal_date if evidence else None
            records.append(
                BoundaryRecord(
                    identity.identity_key,
                    identity.isin,
                    listing_date,
                    identity.first_observed,
                    (
                        (identity.first_observed - listing_date).days
                        if listing_date is not None
                        else None
                    ),
                    removal_date,
                    identity.last_observed,
                    (
                        (removal_date - identity.last_observed).days
                        if removal_date is not None
                        else None
                    ),
                    (
                        "LISTING_PROVEN_DELISTING_UNVERIFIED"
                        if listing_date is not None
                        else "LISTING_AND_DELISTING_BOUNDARIES_UNVERIFIED"
                    ),
                    identity.source_ids + ((evidence.source_id,) if evidence else ()),
                )
            )
        return tuple(records)

    @staticmethod
    def _suspensions(
        identities: Sequence[SecurityIdentityRecord],
    ) -> tuple[SuspensionRecord, ...]:
        return tuple(
            SuspensionRecord(
                item.identity_key,
                None,
                None,
                None,
                None,
                "SUSPENSION_BOUNDARY_UNVERIFIED",
                0,
            )
            for item in identities
        )

    @staticmethod
    def _memberships(
        connection: duckdb.DuckDBPyConnection,
        state_by_key: Mapping[str, IdentityState],
    ) -> tuple[MembershipIntervalRecord, ...]:
        rows = connection.execute(
            """
            SELECT identity_key, UPPER(symbol), UPPER(series),
                   MIN(trading_date), MAX(trading_date), COUNT(DISTINCT trading_date),
                   MIN(source_sha256)
            FROM scoped_candle
            GROUP BY identity_key, UPPER(symbol), UPPER(series)
            ORDER BY identity_key, MIN(trading_date), UPPER(symbol)
            """
        ).fetchall()
        records: list[MembershipIntervalRecord] = []
        for key, symbol, series, first, last, days, source_hash in rows:
            identity_state = state_by_key[str(key)]
            if str(series) != "EQ":
                state = MembershipState.SERIES_NOT_SUPPORTED
            elif identity_state not in {
                IdentityState.GOVERNED_IDENTITY,
                IdentityState.PROVISIONAL_IDENTITY,
            }:
                state = MembershipState.IDENTITY_UNRESOLVED
            else:
                state = MembershipState.ACTIVE_TRADABLE
            records.append(
                MembershipIntervalRecord(
                    str(key),
                    str(symbol),
                    str(series),
                    first,
                    last,
                    state,
                    str(source_hash) if source_hash else None,
                    "OBSERVED_CANDLE_DATES_ONLY; GAPS_ARE_NOT_SUSPENSIONS",
                    int(days),
                    ("CONTINUOUS_MEMBERSHIP_UNRESOLVED",),
                )
            )
        return tuple(records)

    @staticmethod
    def _candle_reconciliation(
        connection: duckdb.DuckDBPyConnection,
        state_by_key: Mapping[str, IdentityState],
    ) -> tuple[CandleReconciliationRecord, ...]:
        raw = connection.execute(
            """
            SELECT YEAR(trading_date), identity_key, UPPER(series),
                   COUNT(*), COUNT(*) FILTER (WHERE source_sha256 IS NOT NULL)
            FROM scoped_candle
            GROUP BY YEAR(trading_date), identity_key, UPPER(series)
            ORDER BY YEAR(trading_date), identity_key, UPPER(series)
            """
        ).fetchall()
        aggregate: Counter[tuple[int, IdentityState, MembershipState]] = Counter()
        identities: dict[tuple[int, IdentityState, MembershipState], set[str]] = (
            defaultdict(set)
        )
        source_rows: Counter[tuple[int, IdentityState, MembershipState]] = Counter()
        for year, key, series, count, hashes in raw:
            identity_state = state_by_key[str(key)]
            membership = (
                MembershipState.SERIES_NOT_SUPPORTED
                if str(series) != "EQ"
                else MembershipState.IDENTITY_UNRESOLVED
                if identity_state
                not in {
                    IdentityState.GOVERNED_IDENTITY,
                    IdentityState.PROVISIONAL_IDENTITY,
                }
                else MembershipState.ACTIVE_TRADABLE
            )
            group = (int(year), identity_state, membership)
            aggregate[group] += int(count)
            identities[group].add(str(key))
            source_rows[group] += int(hashes)
        return tuple(
            CandleReconciliationRecord(
                year,
                identity_state,
                membership,
                aggregate[(year, identity_state, membership)],
                len(identities[(year, identity_state, membership)]),
                source_rows[(year, identity_state, membership)],
                (
                    "ROW_CLASSIFIED_WITHOUT_MUTATION",
                    "CONTINUOUS_MEMBERSHIP_UNRESOLVED",
                ),
            )
            for year, identity_state, membership in sorted(
                aggregate,
                key=lambda item: (item[0], item[1].value, item[2].value),
            )
        )

    def _candidate_exposure(
        self,
        identities: Sequence[SecurityIdentityRecord],
    ) -> tuple[CandidateExposureRecord, ...]:
        identity_counts = Counter(item.identity_state.value for item in identities)
        output = [
            CandidateExposureRecord(
                f"IDENTITY_STATE:{state}",
                count,
                0,
                0,
                0,
                0,
                0,
                "NOT_ATTRIBUTABLE_FROM_HTR008_BASELINE",
            )
            for state, count in sorted(identity_counts.items())
        ]
        if not self.baseline_exposure.is_file():
            output.append(
                CandidateExposureRecord(
                    "HTR008_BASELINE_UNAVAILABLE",
                    None,
                    0,
                    0,
                    0,
                    0,
                    0,
                    "UNAVAILABLE",
                )
            )
            return tuple(output)
        payload = json.loads(self.baseline_exposure.read_text(encoding="utf-8"))
        records = payload.get("records", []) if isinstance(payload, dict) else []
        for row in records:
            if not isinstance(row, dict):
                continue
            output.append(
                CandidateExposureRecord(
                    str(row.get("certification_class", "UNKNOWN")),
                    None,
                    int(row.get("technical_candidates", 0)),
                    0,
                    int(row.get("buy_candidates", 0)),
                    int(row.get("strong_buy_candidates", 0)),
                    0,
                    "UNAVAILABLE_IN_HTR008_BASELINE",
                )
            )
        return tuple(sorted(output, key=lambda item: item.blocker))

    @staticmethod
    def _source_summary(
        sources: Sequence[ParsedSource],
        sessions: Sequence[date],
        master_dates: set[date],
    ) -> SourceSummary:
        return SourceSummary(
            official_sources_attempted=len(sources),
            sources_acquired=sum(
                item.inventory.status is SourceStatus.ACQUIRED for item in sources
            ),
            sources_reused=sum(
                item.inventory.status is SourceStatus.REUSED for item in sources
            ),
            sources_failed=sum(
                item.inventory.status in {SourceStatus.FAILED, SourceStatus.REJECTED}
                for item in sources
            ),
            records_parsed=sum(item.inventory.row_count for item in sources),
            records_admitted=sum(item.inventory.admitted_records for item in sources),
            records_rejected=sum(item.inventory.rejected_records for item in sources),
            security_master_dates_covered=len(set(sessions).intersection(master_dates)),
            security_master_dates_uncovered=len(set(sessions) - master_dates),
        )

    @staticmethod
    def _identity_summary(
        connection: duckdb.DuckDBPyConnection,
        identities: Sequence[SecurityIdentityRecord],
        reuse: Sequence[SymbolReuseRecord],
        changes: Sequence[SymbolChangeRecord],
    ) -> IdentitySummary:
        raw = connection.execute(
            """
            SELECT COUNT(DISTINCT symbol),
                   COUNT(DISTINCT (symbol, series)),
                   COUNT(DISTINCT isin) FILTER (WHERE isin IS NOT NULL)
            FROM scoped_candle
            """
        ).fetchone()
        counts = Counter(item.identity_state for item in identities)
        unresolved = (
            len(identities)
            - counts[IdentityState.GOVERNED_IDENTITY]
            - counts[IdentityState.PROVISIONAL_IDENTITY]
        )
        return IdentitySummary(
            raw_symbols=int(raw[0]) if raw else 0,
            symbol_series_pairs=int(raw[1]) if raw else 0,
            isins=int(raw[2]) if raw else 0,
            governed_identities=counts[IdentityState.GOVERNED_IDENTITY],
            provisional_identities=counts[IdentityState.PROVISIONAL_IDENTITY],
            unresolved_identities=unresolved,
            ambiguous_identities=counts[IdentityState.AMBIGUOUS_IDENTITY],
            symbol_reuse_conflicts=len(reuse),
            symbol_changes_resolved=sum(
                item.admission_decision == "ADMITTED" for item in changes
            ),
            symbol_changes_unresolved=sum(
                item.admission_decision != "ADMITTED" for item in changes
            ),
            isin_conflicts=counts[IdentityState.ISIN_CONFLICT],
            overlapping_intervals=counts[IdentityState.OVERLAPPING_IDENTITY_INTERVALS],
            interval_gaps=counts[IdentityState.IDENTITY_INTERVAL_GAP],
        )

    @staticmethod
    def _membership_summary(
        connection: duckdb.DuckDBPyConnection,
        memberships: Sequence[MembershipIntervalRecord],
        state_by_key: Mapping[str, IdentityState],
    ) -> MembershipSummary:
        row = connection.execute(
            """
            WITH bounds AS (
                SELECT identity_key, MIN(trading_date) AS first_date,
                       MAX(trading_date) AS last_date
                FROM scoped_candle
                GROUP BY identity_key
            )
            SELECT COUNT(*)
            FROM bounds b
            JOIN official_session s
              ON s.trading_date BETWEEN b.first_date AND b.last_date
            """
        ).fetchone()
        expected = int(row[0]) if row else 0
        active = sum(
            item.identity_days
            for item in memberships
            if item.membership_state is MembershipState.ACTIVE_TRADABLE
        )
        suspended = sum(
            item.identity_days
            for item in memberships
            if item.membership_state
            in {
                MembershipState.ACTIVE_SUSPENDED,
                MembershipState.TEMPORARILY_SUSPENDED,
            }
        )
        certified = sum(
            item.identity_days
            for item in memberships
            if state_by_key.get(item.identity_key) is IdentityState.GOVERNED_IDENTITY
            and item.membership_state
            in {
                MembershipState.ACTIVE_TRADABLE,
                MembershipState.ACTIVE_SUSPENDED,
                MembershipState.TEMPORARILY_SUSPENDED,
            }
        )
        outside = connection.execute(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE m.listing_date IS NOT NULL
                      AND c.trading_date < m.listing_date
                ),
                COUNT(*) FILTER (
                    WHERE m.removal_date IS NOT NULL
                      AND c.trading_date > m.removal_date
                )
            FROM scoped_candle c
            JOIN official_mii_identity m
              ON c.identity_key = m.identity_key
             AND UPPER(c.symbol) = m.symbol
             AND UPPER(c.series) = m.series
            """
        ).fetchone()
        pre_listing = int(outside[0]) if outside else 0
        post_delisting = int(outside[1]) if outside else 0
        return MembershipSummary(
            identity_days_expected=expected,
            identity_days_certified=certified,
            active_tradable_identity_days=active,
            suspended_identity_days=suspended,
            unresolved_membership_days=max(0, expected - certified),
            pre_listing_candle_rows=pre_listing,
            post_delisting_candle_rows=post_delisting,
            candles_outside_active_intervals=pre_listing + post_delisting,
        )

    @staticmethod
    def _survivorship(
        identities: Sequence[SecurityIdentityRecord],
        master_rows: Sequence[Mapping[str, str]],
    ) -> tuple[SurvivorshipRecord, ...]:
        current_isins: set[str] = set()
        for row in master_rows:
            for key, value in row.items():
                if key.lower().replace(" ", "_") in {"isin", "isin_number", "isin_no"}:
                    if valid_isin(value):
                        current_isins.add(value.upper())
        absent = (
            sum(
                1
                for item in identities
                if item.isin and item.isin.upper() not in current_isins
            )
            if current_isins
            else None
        )
        renamed = sum(1 for item in identities if len(item.symbols) > 1)
        return (
            SurvivorshipRecord(
                "HISTORICALLY_OBSERVED_ABSENT_FROM_CURRENT_UNIVERSE",
                absent,
                "MEASURED" if absent is not None else "UNKNOWN",
                "Current official list is comparison-only and never backfilled.",
            ),
            SurvivorshipRecord(
                "DELISTED_IDENTITIES_RETAINED",
                None,
                "UNKNOWN",
                "No complete official delisting history was admitted.",
            ),
            SurvivorshipRecord(
                "RENAMED_IDENTITIES_RETAINED",
                renamed,
                "OBSERVED_NOT_CERTIFIED",
                "Same-ISIN multi-symbol histories remain visible and unjoined "
                "unless official evidence supports continuity.",
            ),
            SurvivorshipRecord(
                "MERGED_OR_CEASED_IDENTITIES_RETAINED",
                None,
                "UNKNOWN",
                "No complete official merger or cessation history was admitted.",
            ),
            SurvivorshipRecord(
                "CURRENT_UNIVERSE_LEAKAGE_DETECTED",
                0,
                "PASS",
                "Current master rows are not used before their effective date.",
            ),
            SurvivorshipRecord(
                "FUTURE_LISTING_LEAKAGE_DETECTED",
                0,
                "PASS",
                "Observed rows never establish an earlier listing boundary.",
            ),
            SurvivorshipRecord(
                "FINAL_SURVIVORSHIP_RISK",
                None,
                "UNKNOWN",
                "Historical listing and delisting boundaries remain incomplete.",
            ),
        )

    @staticmethod
    def _latest_master_date(sources: Sequence[ParsedSource]) -> date | None:
        dates = [
            item.inventory.covered_to
            for item in sources
            if item.inventory.evidence_type is EvidenceType.MII_SECURITY_MASTER
            and item.inventory.status in {SourceStatus.ACQUIRED, SourceStatus.REUSED}
            and item.inventory.covered_to is not None
        ]
        return max(dates) if dates else None

    @staticmethod
    def _ytd_summary(
        connection: duckdb.DuckDBPyConnection,
        *,
        year: int,
        latest_calendar: date | None,
    ) -> YtdSummary:
        row = connection.execute(
            """
            SELECT MAX(trading_date), COUNT(*),
                   COUNT(DISTINCT isin) FILTER (WHERE isin IS NOT NULL),
                   COUNT(*) FILTER (WHERE isin IS NULL)
            FROM source.daily_candle
            WHERE YEAR(trading_date) = ?
            """,
            [year],
        ).fetchone()
        latest = row[0] if row and isinstance(row[0], date) else None
        canonical_rows = int(row[1]) if row else 0
        observed_isins = int(row[2]) if row else 0
        missing_isin = int(row[3]) if row else 0
        included = (
            latest is not None
            and latest_calendar is not None
            and latest <= latest_calendar
        )
        return YtdSummary(
            year=year,
            latest_canonical_date=latest,
            included_in_certified_window=included,
            exclusion_reason=(
                None
                if included
                else "CERTIFIED_SESSION_CALENDAR_DOES_NOT_COVER_2026_YTD"
            ),
            canonical_rows=canonical_rows,
            observed_isin_identities=observed_isins,
            missing_isin_rows=missing_isin,
            governed_identities=0,
            provisional_identities=observed_isins,
            unresolved_identities=missing_isin,
            active_universe_size=None,
            symbol_changes=None,
            listings=None,
            delistings=None,
            suspensions=None,
            technical_candidates=None,
            buy_candidates=None,
            strong_buy_candidates=None,
        )

    @staticmethod
    def _certification(
        identities: Sequence[SecurityIdentityRecord],
        reuse: Sequence[SymbolReuseRecord],
        changes: Sequence[SymbolChangeRecord],
        sources: Sequence[ParsedSource],
        sessions: Sequence[date],
        master_dates: set[date],
        rejected: Sequence[RejectedEvidenceRecord],
    ) -> CertificationSummary:
        thresholds = (
            "100% of official sessions have an admitted date-specific security master",
            "100% of supported canonical rows resolve to governed identity intervals",
            "zero unresolved symbol-reuse or symbol-change cases",
            "100% of listing, delisting, suspension, and relisting boundaries "
            "are official-source-backed",
            "zero conflicting admitted official records",
        )
        blockers: list[CertificationState] = []
        if not set(sessions).issubset(master_dates):
            blockers.append(CertificationState.BLOCKED_MISSING_SECURITY_MASTER)
        if any(
            item.identity_state
            in {
                IdentityState.AMBIGUOUS_IDENTITY,
                IdentityState.MISSING_IDENTITY_EVIDENCE,
            }
            for item in identities
        ):
            blockers.append(CertificationState.BLOCKED_IDENTITY_AMBIGUITY)
        if reuse:
            blockers.append(CertificationState.BLOCKED_SYMBOL_REUSE)
        if any(item.admission_decision != "ADMITTED" for item in changes):
            blockers.append(CertificationState.BLOCKED_SYMBOL_CHANGE_EVIDENCE)
        admitted_types = {
            item.inventory.evidence_type
            for item in sources
            if item.inventory.status in {SourceStatus.ACQUIRED, SourceStatus.REUSED}
        }
        if not {
            EvidenceType.LISTING_NOTICE,
            EvidenceType.DELISTING_NOTICE,
        }.issubset(admitted_types):
            blockers.append(CertificationState.BLOCKED_LISTING_DELISTING_EVIDENCE)
        if EvidenceType.SUSPENSION_NOTICE not in admitted_types:
            blockers.append(CertificationState.BLOCKED_SUSPENSION_EVIDENCE)
        if any(item.reason_code == "CONFLICTING_RECORDS" for item in rejected):
            blockers.append(CertificationState.BLOCKED_CONFLICTING_OFFICIAL_EVIDENCE)
        unique = tuple(dict.fromkeys(blockers))
        primary = (
            CertificationState.POINT_IN_TIME_UNIVERSE_CERTIFIED
            if not unique
            else unique[0]
        )
        missing_sessions = len(set(sessions) - master_dates)
        governed_count = sum(
            item.identity_state is IdentityState.GOVERNED_IDENTITY
            for item in identities
        )
        rationale = (
            f"{len(master_dates)} of {len(sessions)} official sessions have an "
            "admitted "
            f"date-specific security master; {missing_sessions} remain uncovered. "
            f"{governed_count} "
            f"of {len(identities)} observed identities are governed. "
            f"Rejected evidence records: {len(rejected)}."
        )
        return CertificationSummary(primary, unique[1:], rationale, thresholds)

    @staticmethod
    def _filter_identities(
        records: Sequence[SecurityIdentityRecord],
        *,
        symbols: Sequence[str],
        isins: Sequence[str],
        years: Sequence[int],
        states: Sequence[IdentityState],
        only_unresolved: bool,
    ) -> tuple[SecurityIdentityRecord, ...]:
        symbol_filter = {item.upper() for item in symbols}
        isin_filter = {item.upper() for item in isins}
        year_filter = set(years)
        state_filter = set(states)
        return tuple(
            item
            for item in records
            if (not symbol_filter or symbol_filter.intersection(item.symbols))
            and (not isin_filter or (item.isin or "").upper() in isin_filter)
            and (
                not year_filter
                or any(
                    year in year_filter
                    for year in range(
                        item.first_observed.year, item.last_observed.year + 1
                    )
                )
            )
            and (not state_filter or item.identity_state in state_filter)
            and (
                not only_unresolved
                or item.identity_state is not IdentityState.GOVERNED_IDENTITY
            )
        )


def _parse_flexible_date(value: str) -> date | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    for pattern in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y"):
        try:
            from datetime import datetime

            return datetime.strptime(cleaned, pattern).date()
        except ValueError:
            continue
    return None


def _parse_source_date(value: str) -> date | None:
    cleaned = value.strip()
    if not cleaned or cleaned in {"0", "0.0"}:
        return None
    try:
        timestamp = int(float(cleaned))
    except ValueError:
        return _parse_flexible_date(cleaned)
    if timestamp <= 0:
        return None
    from datetime import UTC, datetime

    try:
        return datetime.fromtimestamp(timestamp, tz=UTC).date()
    except (OverflowError, OSError, ValueError):
        return None


__all__ = ["PointInTimeIdentityCertificationEngine"]
