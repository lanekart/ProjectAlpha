"""Full-market, candidate-independent HTR-010A certification engine."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import duckdb

from alpha.historical_truth.complete_security_dataset_models import (
    HTR010A_CONTRACT_VERSION,
    PRODUCTION_INFLUENCE,
    AttributeInterval,
    CandleReconciliationState,
    CandleReconciliationSummary,
    CandleSummary,
    CertificationSummary,
    CertificationTier,
    CompleteMembershipInterval,
    CompleteSecurityDatasetReport,
    CompleteSecurityIdentity,
    ContinuitySummary,
    DatasetCertificationRecord,
    EvidenceSummary,
    IdentityInterval,
    IdentityState,
    MembershipState,
    MembershipSummary,
    OverallCertificationState,
    PopulationSummary,
    RejectedEvidenceRecord,
    SecurityCensusRecord,
    SecuritySessionGapSummary,
    SourceInventoryRecord,
    SourceStatus,
    SuspensionInterval,
    SymbolReuseRecord,
    TerminationRecord,
    TransitionRecord,
    YtdSummary,
    stable_synthetic_identity,
)
from alpha.historical_truth.complete_security_dataset_sources import (
    CompleteDatasetSourceInventory,
)
from alpha.historical_truth.session_calendar import (
    CalendarCertificationState,
    OfficialSessionCalendarEngine,
    SessionClassification,
)

_ISIN = re.compile(r"^IN[A-Z0-9]{10}$")
_SUPPORTED_SERIES = frozenset({"EQ", "BE", "BZ", "BL", "SM", "ST"})
_CERTIFIED_MEMBERSHIP = frozenset(
    {
        "CERTIFIED_ACTIVE_TRADABLE",
        "CERTIFIED_ACTIVE_SUSPENDED",
        "CERTIFIED_RELISTED",
    }
)
_CONFLICTING_CODES = frozenset(
    {
        IdentityState.ISIN_CONFLICT.value,
        IdentityState.OVERLAPPING_IDENTITY_INTERVALS.value,
        IdentityState.CONFLICTING_OFFICIAL_EVIDENCE.value,
    }
)


class CompleteSecurityDatasetCertificationEngine:
    """Certify the complete observed NSE CM population without candidate filters."""

    def __init__(self, database_path: Path, root: Path) -> None:
        self.database_path = database_path
        self.root = root
        self.sources = CompleteDatasetSourceInventory(root)

    def run(
        self,
        *,
        calendar_report: Path,
        snapshot_root: Path,
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
        only_conflicting: bool = False,
    ) -> CompleteSecurityDatasetReport:
        del snapshot_root  # Snapshot integrity is inherited from HTR-007C.
        if refresh_sources and verify_only:
            raise ValueError("refresh_sources and verify_only are mutually exclusive")
        if verify_only:
            report = self._load_persisted_report()
            _verify_source_checksums(report.source_inventory)
        else:
            report = self._build(
                calendar_report=calendar_report,
                start_date=start_date,
                requested_end=requested_end,
                refresh_sources=refresh_sources,
            )
            self._persist(report)
        return _filter_report(
            report,
            symbols=symbols,
            isins=isins,
            years=years,
            identity_states=identity_states,
            membership_states=membership_states,
            only_unresolved=only_unresolved,
            only_conflicting=only_conflicting,
        )

    def _build(
        self,
        *,
        calendar_report: Path,
        start_date: date,
        requested_end: date | None,
        refresh_sources: bool,
    ) -> CompleteSecurityDatasetReport:
        source_inventory, source_rejections = self.sources.collect(
            refresh_sources=refresh_sources,
            verify_only=False,
        )
        sessions, end_date, ytd_calendar = self._sessions(
            calendar_report, start_date, requested_end
        )
        with duckdb.connect(str(self.database_path)) as connection:
            census = self._census(connection, start_date, end_date)
            identities = self._identities(connection, census)
            symbol_intervals = self._attribute_intervals(
                connection, census, identities, "symbol"
            )
            series_intervals = self._attribute_intervals(
                connection, census, identities, "series"
            )
            identity_intervals = self._identity_intervals(
                identities, census, symbol_intervals
            )
            membership, tradability = self._membership_intervals(
                connection, identities, census, start_date, end_date
            )
            suspensions = self._suspensions(connection)
            terminations = self._terminations(connection)
            transitions = self._transitions(connection)
            symbol_reuse = self._symbol_reuse(census)
            reconciliation = self._candle_reconciliation(
                connection,
                census,
                identities,
                membership,
                start_date,
                end_date,
            )
            gaps = self._security_session_gaps(
                connection,
                sessions,
                identities,
                membership,
                start_date,
                end_date,
            )
        matrix = self._certification_matrix(
            identities,
            identity_intervals,
            symbol_intervals,
            series_intervals,
            membership,
            suspensions,
            terminations,
            transitions,
            reconciliation,
            symbol_reuse,
        )
        population = _population_summary(census, identities)
        evidence = _evidence_summary(source_inventory)
        membership_summary = _membership_summary(
            membership, tradability, suspensions, terminations
        )
        candle_summary = _candle_summary(reconciliation)
        continuity = _continuity_summary(gaps, reconciliation, identities)
        ytd = self._ytd_summary(
            end_date,
            ytd_calendar,
            identities,
            membership,
            connection_end=self._canonical_end(),
        )
        certification = _certification_summary(
            matrix, symbol_reuse, transitions, suspensions, candle_summary
        )
        report = CompleteSecurityDatasetReport(
            HTR010A_CONTRACT_VERSION,
            PRODUCTION_INFLUENCE,
            str(self.database_path),
            start_date,
            end_date,
            source_inventory,
            source_rejections,
            census,
            identities,
            identity_intervals,
            symbol_intervals,
            series_intervals,
            membership,
            tradability,
            suspensions,
            terminations,
            symbol_reuse,
            transitions,
            reconciliation,
            gaps,
            matrix,
            population,
            evidence,
            membership_summary,
            candle_summary,
            continuity,
            ytd,
            certification,
            "",
        )
        return replace(report, report_sha256=report.calculated_sha256())

    def _sessions(
        self,
        calendar_report: Path,
        start_date: date,
        requested_end: date | None,
    ) -> tuple[tuple[date, ...], date, tuple[str, date | None, str | None]]:
        payload = json.loads(calendar_report.read_text(encoding="utf-8"))
        certified = tuple(
            sorted(
                {
                    date.fromisoformat(str(item["trading_date"]))
                    for item in payload.get("records", ())
                    if item.get("classification")
                    in {
                        SessionClassification.REGULAR_SESSION.value,
                        SessionClassification.SPECIAL_SESSION.value,
                    }
                    and date.fromisoformat(str(item["trading_date"])) >= start_date
                }
            )
        )
        if not certified:
            raise ValueError("calendar report has no certified sessions")
        canonical_end = self._canonical_end()
        target = min(
            item for item in (canonical_end, requested_end) if item is not None
        )
        base_end = min(certified[-1], target)
        sessions = tuple(item for item in certified if item <= base_end)
        ytd_state = "NOT_APPLICABLE"
        ytd_cutoff: date | None = None
        blocker: str | None = None
        if target.year > base_end.year or target > base_end:
            extension = self._calendar_extension(start_date, target, payload)
            if extension is not None:
                extension_sessions, extension_state, extension_blocker = extension
                ytd_state = extension_state
                ytd_cutoff = max(extension_sessions, default=None)
                blocker = extension_blocker
                if extension_state == CalendarCertificationState.CERTIFIED.value:
                    sessions = tuple(sorted(set(sessions).union(extension_sessions)))
                    base_end = min(target, sessions[-1])
            else:
                ytd_state = (
                    CalendarCertificationState.INCOMPLETE_OFFICIAL_EVIDENCE.value
                )
                blocker = "No governed 2026 official calendar source was available."
        return sessions, base_end, (ytd_state, ytd_cutoff, blocker)

    def _calendar_extension(
        self,
        start_date: date,
        target: date,
        payload: dict[str, Any],
    ) -> tuple[tuple[date, ...], str, str | None] | None:
        paths = {
            Path(str(item["source_path"]))
            for item in payload.get("sources", ())
            if item.get("source_path")
        }
        paths.update((self.root / "raw" / "nse" / "calendar").glob("*.json"))
        sources = []
        for path in sorted(paths):
            try:
                sources.append(OfficialSessionCalendarEngine.load_source(path))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        if not sources or not any(
            target.year in item.covered_years for item in sources
        ):
            return None
        from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse

        engine = OfficialSessionCalendarEngine(
            CanonicalPointInTimeWarehouse(self.database_path)
        )
        extension_start = max(start_date, date(target.year, 1, 1))
        report = engine.reconcile(extension_start, target, sources)
        sessions = tuple(
            item.trading_date
            for item in report.records
            if item.classification
            in {
                SessionClassification.REGULAR_SESSION,
                SessionClassification.SPECIAL_SESSION,
            }
        )
        blocker = None
        if report.certification_state is not CalendarCertificationState.CERTIFIED:
            blocker = (
                f"2026 calendar has {report.unresolved_weekday_count} unresolved "
                f"weekdays and {report.unconfirmed_special_session_count} "
                "unconfirmed special sessions."
            )
        return sessions, report.certification_state.value, blocker

    def _canonical_end(self) -> date:
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            row = connection.execute(
                "SELECT MAX(trading_date) FROM daily_candle"
            ).fetchone()
        if row is None or not isinstance(row[0], date):
            raise ValueError("canonical warehouse contains no daily candles")
        return row[0]

    def _census(
        self,
        connection: duckdb.DuckDBPyConnection,
        start_date: date,
        end_date: date,
    ) -> tuple[SecurityCensusRecord, ...]:
        rows = connection.execute(
            """SELECT UPPER(exchange), UPPER(symbol), UPPER(series), UPPER(isin),
                      MIN(trading_date), MAX(trading_date), COUNT(*)
               FROM daily_candle
               WHERE trading_date BETWEEN ? AND ?
               GROUP BY ALL
               ORDER BY 1, 2, 3, 4""",
            [start_date, end_date],
        ).fetchall()
        evidence = self._event_census(connection, start_date, end_date)
        keyed: dict[tuple[str, str, str, str | None], dict[str, Any]] = {}
        for exchange, symbol, series, isin, first_date, last_date, count in rows:
            key = (exchange, symbol, series, isin)
            keyed[key] = {
                "name": None,
                "first": first_date,
                "last": last_date,
                "rows": count,
                "sources": {"canonical_daily_candle"},
                "source_count": 1,
            }
        for item in evidence:
            key = (item[0], item[1], item[2], item[3])
            entry = keyed.setdefault(
                key,
                {
                    "name": None,
                    "first": item[5],
                    "last": item[5],
                    "rows": 0,
                    "sources": set(),
                    "source_count": 0,
                },
            )
            entry["name"] = entry["name"] or item[4]
            entry["first"] = _min_date(entry["first"], item[5])
            entry["last"] = _max_date(entry["last"], item[5])
            entry["sources"].add(item[6])
            entry["source_count"] += 1
        result = []
        for (exchange, symbol, series, isin), value in sorted(
            keyed.items(),
            key=lambda item: (
                item[0][0],
                item[0][1],
                item[0][2],
                item[0][3] is None,
                item[0][3] or "",
            ),
        ):
            valid_isin = _valid_isin(isin)
            identity = (
                f"nse:isin:{isin}"
                if valid_isin
                else stable_synthetic_identity(
                    exchange, symbol, series, value["first"], value["last"]
                )
            )
            result.append(
                SecurityCensusRecord(
                    exchange,
                    symbol,
                    series,
                    isin,
                    value["name"],
                    value["first"],
                    value["last"],
                    int(value["rows"]),
                    tuple(sorted(value["sources"])),
                    int(value["source_count"]),
                    series in _SUPPORTED_SERIES,
                    identity,
                )
            )
        return tuple(result)

    @staticmethod
    def _event_census(
        connection: duckdb.DuckDBPyConnection,
        start_date: date,
        end_date: date,
    ) -> tuple[tuple[Any, ...], ...]:
        records: list[tuple[Any, ...]] = []
        if _table_exists(connection, "security_event"):
            rows = connection.execute(
                """SELECT UPPER(exchange), UPPER(COALESCE(new_symbol, old_symbol)),
                          UPPER(COALESCE(new_series, old_series, 'EQ')),
                          UPPER(COALESCE(new_isin, old_isin)), security_name,
                          effective_date, official_source_id
                   FROM security_event
                   WHERE admission_state = 'ADMITTED'
                     AND effective_date <= ?
                     AND COALESCE(new_symbol, old_symbol) IS NOT NULL""",
                [end_date],
            ).fetchall()
            records.extend(rows)
        if _table_exists(connection, "corporate_action_event"):
            rows = connection.execute(
                """SELECT UPPER(exchange), UPPER(symbol),
                          UPPER(COALESCE(series, 'EQ')), UPPER(isin), NULL,
                          COALESCE(effective_date, ex_date), source_id
                   FROM corporate_action_event
                   WHERE admission_state = 'ADMITTED'
                     AND COALESCE(effective_date, ex_date) BETWEEN ? AND ?
                     AND symbol IS NOT NULL""",
                [start_date, end_date],
            ).fetchall()
            records.extend(rows)
        return tuple(records)

    def _identities(
        self,
        connection: duckdb.DuckDBPyConnection,
        census: Sequence[SecurityCensusRecord],
    ) -> tuple[CompleteSecurityIdentity, ...]:
        grouped: dict[str, list[SecurityCensusRecord]] = defaultdict(list)
        for item in census:
            grouped[item.identity_key].append(item)
        governed = _governed_identity_keys(connection)
        identities = []
        for key, records in sorted(grouped.items()):
            ordered = sorted(
                records, key=lambda item: (item.last_observed or date.min, item.symbol)
            )
            latest = ordered[-1]
            issues: set[str] = set()
            if any(not item.supported_security_type for item in records):
                state = IdentityState.UNSUPPORTED_SECURITY_TYPE
                issues.add(IdentityState.UNSUPPORTED_SECURITY_TYPE.value)
            elif latest.isin and not _valid_isin(latest.isin):
                state = IdentityState.INVALID_ISIN
                issues.add(IdentityState.INVALID_ISIN.value)
            elif latest.isin is None:
                state = IdentityState.MISSING_IDENTITY_EVIDENCE
                issues.add(IdentityState.MISSING_IDENTITY_EVIDENCE.value)
            elif key in governed:
                state = IdentityState.GOVERNED_IDENTITY
            else:
                state = IdentityState.PROVISIONAL_IDENTITY
                issues.add("NO_OFFICIAL_IDENTITY_EVENT")
            symbols = {item.symbol for item in records}
            if len(symbols) > 1 and key not in governed:
                issues.add(IdentityState.SYMBOL_CHANGE_UNRESOLVED.value)
            identities.append(
                CompleteSecurityIdentity(
                    key,
                    latest.exchange,
                    latest.isin if _valid_isin(latest.isin) else None,
                    latest.symbol,
                    latest.series,
                    latest.security_name,
                    min(
                        (
                            item.first_observed
                            for item in records
                            if item.first_observed
                        ),
                        default=None,
                    ),
                    max(
                        (item.last_observed for item in records if item.last_observed),
                        default=None,
                    ),
                    state,
                    tuple(sorted(issues)),
                    tuple(
                        sorted(
                            {source for item in records for source in item.source_ids}
                        )
                    ),
                    None
                    if _valid_isin(latest.isin)
                    else "No valid official ISIN was available.",
                )
            )
        return tuple(identities)

    @staticmethod
    def _attribute_intervals(
        connection: duckdb.DuckDBPyConnection,
        census: Sequence[SecurityCensusRecord],
        identities: Sequence[CompleteSecurityIdentity],
        attribute: str,
    ) -> tuple[AttributeInterval, ...]:
        table = f"security_{attribute}_interval"
        existing: list[AttributeInterval] = []
        if _table_exists(connection, table):
            rows = connection.execute(
                f"""SELECT identity_key, {attribute}, valid_from, valid_to,
                           confidence_state, source_event_ids, issue_codes
                    FROM {table}
                    ORDER BY 1, 3, 2"""  # noqa: S608
            ).fetchall()
            existing = [
                AttributeInterval(
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    _split(row[5]),
                    _split(row[6]),
                )
                for row in rows
            ]
        existing_keys = {(item.identity_key, item.value) for item in existing}
        state_by_key = {item.identity_key: item.identity_state for item in identities}
        additions = []
        for item in census:
            value = item.symbol if attribute == "symbol" else item.series
            if (item.identity_key, value) in existing_keys:
                continue
            if item.first_observed is None or item.last_observed is None:
                continue
            additions.append(
                AttributeInterval(
                    item.identity_key,
                    value,
                    item.first_observed,
                    item.last_observed,
                    "LOW",
                    (),
                    (
                        "OBSERVED_CANDLE_RANGE_NOT_MEMBERSHIP_PROOF",
                        state_by_key[item.identity_key].value,
                    ),
                )
            )
        return tuple(
            sorted(
                (*existing, *additions),
                key=lambda item: (item.identity_key, item.valid_from, item.value),
            )
        )

    @staticmethod
    def _identity_intervals(
        identities: Sequence[CompleteSecurityIdentity],
        census: Sequence[SecurityCensusRecord],
        symbols: Sequence[AttributeInterval],
    ) -> tuple[IdentityInterval, ...]:
        census_by_key: dict[str, list[SecurityCensusRecord]] = defaultdict(list)
        for census_item in census:
            census_by_key[census_item.identity_key].append(census_item)
        symbol_by_key: dict[str, list[AttributeInterval]] = defaultdict(list)
        for symbol_item in symbols:
            symbol_by_key[symbol_item.identity_key].append(symbol_item)
        result = []
        for identity in identities:
            first = min(
                (
                    item.first_observed
                    for item in census_by_key[identity.identity_key]
                    if item.first_observed
                ),
                default=identity.first_evidence_date,
            )
            last = max(
                (
                    item.last_observed
                    for item in census_by_key[identity.identity_key]
                    if item.last_observed
                ),
                default=identity.last_evidence_date,
            )
            if first is None or last is None:
                continue
            issues = set(identity.secondary_issue_codes)
            ordered = sorted(
                symbol_by_key[identity.identity_key], key=lambda item: item.valid_from
            )
            for left, right in zip(ordered, ordered[1:], strict=False):
                if left.valid_to >= right.valid_from:
                    issues.add(IdentityState.OVERLAPPING_IDENTITY_INTERVALS.value)
                elif left.valid_to + timedelta(days=1) < right.valid_from:
                    issues.add(IdentityState.IDENTITY_INTERVAL_GAP.value)
            result.append(
                IdentityInterval(
                    identity.identity_key,
                    first,
                    last,
                    identity.identity_state,
                    tuple(
                        sorted(
                            {
                                event
                                for item in ordered
                                for event in item.source_event_ids
                            }
                        )
                    ),
                    tuple(sorted(issues)),
                )
            )
        return tuple(result)

    @staticmethod
    def _membership_intervals(
        connection: duckdb.DuckDBPyConnection,
        identities: Sequence[CompleteSecurityIdentity],
        census: Sequence[SecurityCensusRecord],
        start_date: date,
        end_date: date,
    ) -> tuple[
        tuple[CompleteMembershipInterval, ...], tuple[CompleteMembershipInterval, ...]
    ]:
        membership: list[CompleteMembershipInterval] = []
        tradability: list[CompleteMembershipInterval] = []
        if _table_exists(connection, "security_membership_interval"):
            for row in connection.execute(
                """SELECT identity_key, valid_from, valid_to, state,
                          source_event_ids, identity_days, issue_codes
                   FROM security_membership_interval
                   WHERE valid_to >= ? AND valid_from <= ?
                   ORDER BY 1, 2""",
                [start_date, end_date],
            ).fetchall():
                state = _membership_state(row[3])
                membership.append(
                    CompleteMembershipInterval(
                        row[0],
                        max(row[1], start_date),
                        min(row[2], end_date),
                        state,
                        state is MembershipState.CERTIFIED_ACTIVE_TRADABLE,
                        _split(row[4]),
                        int(row[5]),
                        _split(row[6]),
                    )
                )
        if _table_exists(connection, "security_tradability_interval"):
            for row in connection.execute(
                """SELECT identity_key, valid_from, valid_to, tradable, state,
                          source_event_ids, identity_days, issue_codes
                   FROM security_tradability_interval
                   WHERE valid_to >= ? AND valid_from <= ?
                   ORDER BY 1, 2""",
                [start_date, end_date],
            ).fetchall():
                tradability.append(
                    CompleteMembershipInterval(
                        row[0],
                        max(row[1], start_date),
                        min(row[2], end_date),
                        _membership_state(row[4]),
                        bool(row[3]),
                        _split(row[5]),
                        int(row[6]),
                        _split(row[7]),
                    )
                )
        present = {item.identity_key for item in membership}
        identity_by_key = {item.identity_key: item for item in identities}
        census_by_key: dict[str, list[SecurityCensusRecord]] = defaultdict(list)
        for item in census:
            census_by_key[item.identity_key].append(item)
        for key, records in sorted(census_by_key.items()):
            if key in present:
                continue
            first = min(
                (item.first_observed for item in records if item.first_observed),
                default=None,
            )
            last = max(
                (item.last_observed for item in records if item.last_observed),
                default=None,
            )
            if first is None or last is None:
                continue
            identity = identity_by_key[key]
            state = (
                MembershipState.UNSUPPORTED_SECURITY_TYPE
                if identity.identity_state is IdentityState.UNSUPPORTED_SECURITY_TYPE
                else MembershipState.UNRESOLVED_NO_LISTING_EVIDENCE
            )
            interval = CompleteMembershipInterval(
                key,
                first,
                last,
                state,
                False,
                (),
                (last - first).days + 1,
                ("CANDLE_RANGE_IS_NOT_LISTING_EVIDENCE",),
            )
            membership.append(interval)
            tradability.append(interval)
        return (
            tuple(
                sorted(
                    membership, key=lambda item: (item.identity_key, item.valid_from)
                )
            ),
            tuple(
                sorted(
                    tradability, key=lambda item: (item.identity_key, item.valid_from)
                )
            ),
        )

    @staticmethod
    def _suspensions(
        connection: duckdb.DuckDBPyConnection,
    ) -> tuple[SuspensionInterval, ...]:
        if not _table_exists(connection, "security_event"):
            return ()
        rows = connection.execute(
            """SELECT event_id, COALESCE(new_isin, old_isin), effective_date,
                      event_type, official_source_id
               FROM security_event
               WHERE event_type IN ('SUSPENDED', 'SUSPENSION_REVOKED')
                 AND admission_state = 'ADMITTED'
               ORDER BY 2, 3, 1"""
        ).fetchall()
        open_events: dict[str, tuple[str, date, str]] = {}
        result = []
        for event_id, isin, effective, event_type, source_id in rows:
            if not _valid_isin(isin):
                continue
            key = f"nse:isin:{isin}"
            if event_type == "SUSPENDED":
                open_events[key] = (event_id, effective, source_id)
            elif key in open_events:
                opened = open_events.pop(key)
                result.append(
                    SuspensionInterval(
                        key,
                        opened[1],
                        effective,
                        effective,
                        (opened[0], event_id),
                        "RESTORED",
                    )
                )
        result.extend(
            SuspensionInterval(key, item[1], None, None, (item[0],), "OPEN")
            for key, item in sorted(open_events.items())
        )
        return tuple(result)

    @staticmethod
    def _terminations(
        connection: duckdb.DuckDBPyConnection,
    ) -> tuple[TerminationRecord, ...]:
        if not _table_exists(connection, "security_event"):
            return ()
        rows = connection.execute(
            """SELECT event_id, COALESCE(new_isin, old_isin), effective_date,
                      event_type, official_source_id
               FROM security_event
               WHERE event_type IN ('DELISTED', 'ADMISSION_WITHDRAWN',
                   'IDENTITY_TERMINATED') AND admission_state = 'ADMITTED'
               ORDER BY 3, 1"""
        ).fetchall()
        return tuple(
            TerminationRecord(f"nse:isin:{row[1]}", row[2], row[3], row[0], row[4])
            for row in rows
            if _valid_isin(row[1])
        )

    @staticmethod
    def _transitions(
        connection: duckdb.DuckDBPyConnection,
    ) -> tuple[TransitionRecord, ...]:
        result: list[TransitionRecord] = []
        if _table_exists(connection, "identity_transition"):
            for row in connection.execute(
                """SELECT transition_id, action_type, effective_date,
                          predecessor_identity, successor_identity, old_symbol,
                          new_symbol, old_isin, new_isin, official_source,
                          confidence_state, issue_codes
                   FROM identity_transition ORDER BY 3, 1"""
            ).fetchall():
                result.append(
                    TransitionRecord(
                        row[0],
                        row[1],
                        row[2],
                        row[3],
                        row[4],
                        row[5],
                        row[6],
                        None,
                        None,
                        row[7],
                        row[8],
                        row[9],
                        "RESOLVED" if row[10] in {"HIGH", "MEDIUM"} else "UNRESOLVED",
                        _split(row[11]),
                    )
                )
        if _table_exists(connection, "security_event"):
            for row in connection.execute(
                """SELECT event_id, event_type, effective_date,
                          predecessor_identity, successor_identity, old_symbol,
                          new_symbol, old_series, new_series, old_isin, new_isin,
                          official_source_id, confidence_state
                   FROM security_event
                   WHERE event_type IN ('SYMBOL_CHANGED', 'SERIES_CHANGED',
                       'ISIN_CHANGED', 'MERGED', 'DEMERGED', 'AMALGAMATED',
                       'SCHEME_EFFECTIVE', 'SUCCESSOR_CREATED')
                     AND admission_state = 'ADMITTED'
                   ORDER BY 3, 1"""
            ).fetchall():
                result.append(
                    TransitionRecord(
                        row[0],
                        row[1],
                        row[2],
                        row[3],
                        row[4],
                        row[5],
                        row[6],
                        row[7],
                        row[8],
                        row[9],
                        row[10],
                        row[11],
                        "RESOLVED" if row[12] in {"HIGH", "MEDIUM"} else "UNRESOLVED",
                        (),
                    )
                )
        return tuple(
            sorted(
                {item.transition_id: item for item in result}.values(),
                key=lambda item: (item.effective_date, item.transition_id),
            )
        )

    @staticmethod
    def _symbol_reuse(
        census: Sequence[SecurityCensusRecord],
    ) -> tuple[SymbolReuseRecord, ...]:
        grouped: dict[str, list[SecurityCensusRecord]] = defaultdict(list)
        for item in census:
            if _valid_isin(item.isin):
                grouped[item.symbol].append(item)
        result = []
        for symbol, records in sorted(grouped.items()):
            by_identity = {item.identity_key: item for item in records}
            if len(by_identity) < 2:
                continue
            ordered = sorted(
                by_identity.values(), key=lambda item: item.first_observed or date.min
            )
            overlap = any(
                left.last_observed is not None
                and right.first_observed is not None
                and left.last_observed >= right.first_observed
                for left, right in zip(ordered, ordered[1:], strict=False)
            )
            gap = any(
                left.last_observed is not None
                and right.first_observed is not None
                and left.last_observed + timedelta(days=1) < right.first_observed
                for left, right in zip(ordered, ordered[1:], strict=False)
            )
            result.append(
                SymbolReuseRecord(
                    symbol,
                    tuple(item.identity_key for item in ordered),
                    tuple(sorted({item.isin for item in ordered if item.isin})),
                    min(
                        (
                            item.first_observed
                            for item in ordered
                            if item.first_observed
                        ),
                        default=None,
                    ),
                    max(
                        (item.last_observed for item in ordered if item.last_observed),
                        default=None,
                    ),
                    overlap,
                    gap,
                    "SYMBOL_REUSE_UNRESOLVED" if overlap else "SYMBOL_REUSE_RESOLVED",
                    ("OVERLAPPING_OBSERVED_RANGES",) if overlap else (),
                )
            )
        return tuple(result)

    @staticmethod
    def _candle_reconciliation(
        connection: duckdb.DuckDBPyConnection,
        census: Sequence[SecurityCensusRecord],
        identities: Sequence[CompleteSecurityIdentity],
        membership: Sequence[CompleteMembershipInterval],
        start_date: date,
        end_date: date,
    ) -> tuple[CandleReconciliationSummary, ...]:
        connection.execute("DROP TABLE IF EXISTS temp_htr010a_census")
        connection.execute("DROP TABLE IF EXISTS temp_htr010a_identity")
        connection.execute("DROP TABLE IF EXISTS temp_htr010a_membership")
        connection.execute(
            """CREATE TEMP TABLE temp_htr010a_census(
                exchange VARCHAR, symbol VARCHAR, series VARCHAR, isin VARCHAR,
                identity_key VARCHAR, supported BOOLEAN)"""
        )
        connection.executemany(
            "INSERT INTO temp_htr010a_census VALUES (?,?,?,?,?,?)",
            [
                (
                    item.exchange,
                    item.symbol,
                    item.series,
                    item.isin,
                    item.identity_key,
                    item.supported_security_type,
                )
                for item in census
            ],
        )
        connection.execute(
            """CREATE TEMP TABLE temp_htr010a_identity(
                identity_key VARCHAR, identity_state VARCHAR)"""
        )
        connection.executemany(
            "INSERT INTO temp_htr010a_identity VALUES (?,?)",
            [(item.identity_key, item.identity_state.value) for item in identities],
        )
        connection.execute(
            """CREATE TEMP TABLE temp_htr010a_membership(
                identity_key VARCHAR, valid_from DATE, valid_to DATE,
                state VARCHAR)"""
        )
        connection.executemany(
            "INSERT INTO temp_htr010a_membership VALUES (?,?,?,?)",
            [
                (item.identity_key, item.valid_from, item.valid_to, item.state.value)
                for item in membership
            ],
        )
        rows = connection.execute(
            """WITH classified AS (
                   SELECT c.identity_key,
                     CASE
                       WHEN c.supported = FALSE THEN 'UNSUPPORTED_SERIES'
                       WHEN i.identity_state IN ('MISSING_IDENTITY_EVIDENCE',
                            'INVALID_ISIN', 'AMBIGUOUS_IDENTITY')
                         THEN 'IDENTITY_UNRESOLVED'
                       WHEN m.identity_key IS NULL THEN 'PROVISIONAL_IN_INTERVAL'
                       WHEN m.state = 'CERTIFIED_ACTIVE_SUSPENDED'
                         THEN 'SUSPENDED_DATE_ROW'
                       WHEN m.state IN ('CERTIFIED_ACTIVE_TRADABLE',
                            'CERTIFIED_RELISTED') THEN 'CERTIFIED_IN_INTERVAL'
                       ELSE 'PROVISIONAL_IN_INTERVAL'
                     END AS state,
                     d.trading_date
                   FROM daily_candle d
                   LEFT JOIN temp_htr010a_census c
                     ON UPPER(d.exchange)=c.exchange AND UPPER(d.symbol)=c.symbol
                    AND UPPER(d.series)=c.series
                    AND COALESCE(UPPER(d.isin),'')=COALESCE(c.isin,'')
                   LEFT JOIN temp_htr010a_identity i USING(identity_key)
                   LEFT JOIN temp_htr010a_membership m
                     ON m.identity_key=c.identity_key
                    AND d.trading_date BETWEEN m.valid_from AND m.valid_to
                   WHERE d.trading_date BETWEEN ? AND ?
               )
               SELECT COALESCE(identity_key, 'nse:synthetic:unresolved'), state,
                      COUNT(*), MIN(trading_date), MAX(trading_date)
               FROM classified GROUP BY 1, 2 ORDER BY 1, 2""",
            [start_date, end_date],
        ).fetchall()
        return tuple(
            CandleReconciliationSummary(
                row[0], CandleReconciliationState(row[1]), row[2], row[3], row[4]
            )
            for row in rows
        )

    @staticmethod
    def _security_session_gaps(
        connection: duckdb.DuckDBPyConnection,
        sessions: Sequence[date],
        identities: Sequence[CompleteSecurityIdentity],
        membership: Sequence[CompleteMembershipInterval],
        start_date: date,
        end_date: date,
    ) -> tuple[SecuritySessionGapSummary, ...]:
        del start_date, end_date
        connection.execute("DROP TABLE IF EXISTS temp_htr010a_session")
        connection.execute("DROP TABLE IF EXISTS temp_htr010a_gap_membership")
        connection.execute("CREATE TEMP TABLE temp_htr010a_session(session_date DATE)")
        connection.executemany(
            "INSERT INTO temp_htr010a_session VALUES (?)",
            [(item,) for item in sessions],
        )
        identity_keys = {item.identity_key for item in identities}
        connection.execute(
            """CREATE TEMP TABLE temp_htr010a_gap_membership(
                identity_key VARCHAR, isin VARCHAR, valid_from DATE,
                valid_to DATE, state VARCHAR)"""
        )
        gap_intervals = [
            (
                item.identity_key,
                item.identity_key.removeprefix("nse:isin:"),
                item.valid_from,
                item.valid_to,
                item.state.value,
            )
            for item in membership
            if item.identity_key in identity_keys
            and item.identity_key.startswith("nse:isin:")
        ]
        if gap_intervals:
            connection.executemany(
                "INSERT INTO temp_htr010a_gap_membership VALUES (?,?,?,?,?)",
                gap_intervals,
            )
        rows = connection.execute(
            """WITH observed AS (
                   SELECT UPPER(isin) AS isin, trading_date
                   FROM daily_candle WHERE isin IS NOT NULL GROUP BY ALL
               ), missing AS (
                   SELECT m.identity_key, s.session_date,
                     CASE
                       WHEN m.state='CERTIFIED_ACTIVE_SUSPENDED' THEN 'SUSPENDED'
                       WHEN m.state='UNRESOLVED_NO_LISTING_EVIDENCE'
                         THEN 'IDENTITY_UNRESOLVED'
                       WHEN m.state='UNSUPPORTED_SECURITY_TYPE'
                         THEN 'SERIES_NOT_TRADABLE'
                       ELSE 'UNEXPLAINED_INTERNAL_GAP'
                     END AS classification
                   FROM temp_htr010a_gap_membership m
                   JOIN temp_htr010a_session s
                     ON s.session_date BETWEEN m.valid_from AND m.valid_to
                   LEFT JOIN observed o
                     ON o.isin=m.isin AND o.trading_date=s.session_date
                   WHERE o.isin IS NULL
               )
               SELECT identity_key, classification, COUNT(*),
                      MIN(session_date), MAX(session_date)
               FROM missing GROUP BY 1, 2 ORDER BY 1, 2"""
        ).fetchall()
        return tuple(
            SecuritySessionGapSummary(row[0], row[1], row[2], row[3], row[4])
            for row in rows
        )

    @staticmethod
    def _certification_matrix(
        identities: Sequence[CompleteSecurityIdentity],
        identity_intervals: Sequence[IdentityInterval],
        symbols: Sequence[AttributeInterval],
        series: Sequence[AttributeInterval],
        membership: Sequence[CompleteMembershipInterval],
        suspensions: Sequence[SuspensionInterval],
        terminations: Sequence[TerminationRecord],
        transitions: Sequence[TransitionRecord],
        reconciliation: Sequence[CandleReconciliationSummary],
        reuse: Sequence[SymbolReuseRecord],
    ) -> tuple[DatasetCertificationRecord, ...]:
        symbol_keys = {item.identity_key for item in symbols if item.source_event_ids}
        series_keys = {item.identity_key for item in series if item.source_event_ids}
        membership_by_key: dict[str, list[CompleteMembershipInterval]] = defaultdict(
            list
        )
        for item in membership:
            membership_by_key[item.identity_key].append(item)
        interval_issues = {
            item.identity_key: set(item.issue_codes) for item in identity_intervals
        }
        suspension_keys = {item.identity_key for item in suspensions}
        termination_keys = {item.identity_key for item in terminations}
        transition_keys = {
            key
            for item in transitions
            for key in (item.predecessor_identity, item.successor_identity)
            if key
        }
        reconciled: dict[str, set[CandleReconciliationState]] = defaultdict(set)
        for reconciliation_item in reconciliation:
            reconciled[reconciliation_item.identity_key].add(reconciliation_item.state)
        reuse_conflicts = {
            key for item in reuse if item.interval_overlap for key in item.identity_keys
        }
        result = []
        for identity in identities:
            key = identity.identity_key
            blockers = set(identity.secondary_issue_codes)
            blockers.update(interval_issues.get(key, set()))
            intervals = membership_by_key[key]
            certified_membership = any(
                item.state.value in _CERTIFIED_MEMBERSHIP for item in intervals
            )
            listing = "OFFICIAL" if certified_membership else "MISSING"
            termination = "OFFICIAL" if key in termination_keys else "UNKNOWN_OR_ACTIVE"
            if key in reuse_conflicts:
                blockers.add(IdentityState.SYMBOL_REUSE_UNRESOLVED.value)
            states = reconciled[key]
            if CandleReconciliationState.IDENTITY_UNRESOLVED in states:
                blockers.add("UNRESOLVED_CANDLE_ROWS")
            conflicting = bool(set(blockers) & _CONFLICTING_CODES)
            if conflicting:
                tier = CertificationTier.CONFLICTING
            elif identity.identity_state not in {
                IdentityState.GOVERNED_IDENTITY,
                IdentityState.SYMBOL_REUSE_RESOLVED,
                IdentityState.SYMBOL_CHANGE_RESOLVED,
            }:
                tier = CertificationTier.UNRESOLVED
            elif certified_membership and key in symbol_keys and key in series_keys:
                tier = (
                    CertificationTier.TIER_A_CERTIFIED
                    if termination == "OFFICIAL"
                    or "NO_OFFICIAL_IDENTITY_EVENT" not in blockers
                    else CertificationTier.TIER_A_PARTIAL
                )
            elif certified_membership:
                tier = CertificationTier.IDENTITY_CERTIFIED_MEMBERSHIP_PARTIAL
            else:
                tier = CertificationTier.IDENTITY_PARTIAL
            result.append(
                DatasetCertificationRecord(
                    key,
                    "GOVERNED"
                    if identity.identity_state is IdentityState.GOVERNED_IDENTITY
                    else "PARTIAL",
                    listing,
                    termination,
                    "OFFICIAL" if key in suspension_keys else "SOURCE_GAP",
                    "OFFICIAL" if key in symbol_keys else "OBSERVED_ONLY",
                    "OFFICIAL" if key in series_keys else "OBSERVED_ONLY",
                    "VALID" if identity.isin else "MISSING",
                    "CERTIFIED" if certified_membership else "UNRESOLVED",
                    "CERTIFIED"
                    if any(item.tradable for item in intervals)
                    else "UNRESOLVED",
                    "CERTIFIED"
                    if states == {CandleReconciliationState.CERTIFIED_IN_INTERVAL}
                    else "PARTIAL",
                    "PRESENT" if identity.official_source_ids else "MISSING",
                    "PRESENT"
                    if key in transition_keys
                    else "NOT_APPLICABLE_OR_MISSING",
                    tier,
                    tuple(sorted(blockers)),
                )
            )
        return tuple(result)

    @staticmethod
    def _ytd_summary(
        end_date: date,
        calendar: tuple[str, date | None, str | None],
        identities: Sequence[CompleteSecurityIdentity],
        membership: Sequence[CompleteMembershipInterval],
        *,
        connection_end: date,
    ) -> YtdSummary:
        year = connection_end.year
        identity_cutoff = max(
            (item.last_evidence_date for item in identities if item.last_evidence_date),
            default=None,
        )
        ytd_identities = {
            item.identity_key
            for item in identities
            if item.first_evidence_date is not None
            and item.last_evidence_date is not None
            and item.first_evidence_date <= connection_end
            and item.last_evidence_date >= date(year, 1, 1)
        }
        governed = sum(
            item.identity_key in ytd_identities
            and item.identity_state is IdentityState.GOVERNED_IDENTITY
            for item in identities
        )
        unresolved = sum(
            item.identity_key in ytd_identities
            and item.identity_state is not IdentityState.GOVERNED_IDENTITY
            for item in identities
        )
        final_state = (
            "CERTIFIED"
            if end_date.year == year and calendar[0] == "certified"
            else "PROVISIONAL"
        )
        blocker = calendar[2]
        if end_date.year < year and blocker is None:
            blocker = (
                "Primary certification remains at the last certified calendar date."
            )
        return YtdSummary(
            year,
            calendar[0],
            calendar[1],
            connection_end,
            identity_cutoff,
            min(
                (
                    item
                    for item in (calendar[1], connection_end, identity_cutoff)
                    if item
                ),
                default=None,
            ),
            len(ytd_identities),
            governed,
            sum(
                item.valid_to.year == year or item.valid_from.year == year
                for item in membership
            ),
            unresolved,
            final_state,
            blocker,
        )

    def _persist(self, report: CompleteSecurityDatasetReport) -> None:
        with duckdb.connect(str(self.database_path)) as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                _create_tables(connection)
                _replace_contract_rows(connection)
                _insert_report_rows(connection, report)
                _create_views(connection)
                connection.execute(
                    "INSERT INTO complete_security_dataset_run VALUES (?, ?, ?, ?, ?)",
                    [
                        HTR010A_CONTRACT_VERSION,
                        report.start_date,
                        report.end_date,
                        report.report_sha256,
                        json.dumps(report.payload(), sort_keys=True),
                    ],
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def _load_persisted_report(self) -> CompleteSecurityDatasetReport:
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            if not _table_exists(connection, "complete_security_dataset_run"):
                raise ValueError("no persisted HTR-010A run exists for verification")
            row = connection.execute(
                """SELECT report_json FROM complete_security_dataset_run
                   WHERE contract_version = ? ORDER BY end_date DESC LIMIT 1""",
                [HTR010A_CONTRACT_VERSION],
            ).fetchone()
        if row is None:
            raise ValueError("no persisted HTR-010A run exists for verification")
        return _report_from_payload(json.loads(row[0]))


def _create_tables(connection: duckdb.DuckDBPyConnection) -> None:
    statements = (
        """CREATE TABLE IF NOT EXISTS complete_security_identity(
            contract_version VARCHAR, identity_key VARCHAR, exchange VARCHAR,
            isin VARCHAR, current_symbol VARCHAR, current_series VARCHAR,
            current_name VARCHAR, first_evidence_date DATE, last_evidence_date DATE,
            identity_state VARCHAR, secondary_issue_codes VARCHAR,
            official_source_ids VARCHAR, synthetic_reason VARCHAR,
            candidate_independent BOOLEAN,
            PRIMARY KEY(contract_version, identity_key))""",
        """CREATE TABLE IF NOT EXISTS complete_security_census(
            contract_version VARCHAR, exchange VARCHAR, symbol VARCHAR,
            series VARCHAR, isin VARCHAR, security_name VARCHAR,
            first_observed DATE, last_observed DATE, candle_rows BIGINT,
            source_ids VARCHAR, source_record_count BIGINT,
            supported_security_type BOOLEAN, identity_key VARCHAR)""",
        """CREATE TABLE IF NOT EXISTS security_identity_interval_complete(
            contract_version VARCHAR, identity_key VARCHAR, valid_from DATE,
            valid_to DATE, identity_state VARCHAR, source_event_ids VARCHAR,
            issue_codes VARCHAR)""",
        """CREATE TABLE IF NOT EXISTS security_symbol_interval_complete(
            contract_version VARCHAR, identity_key VARCHAR, value VARCHAR,
            valid_from DATE, valid_to DATE, confidence_state VARCHAR,
            source_event_ids VARCHAR, issue_codes VARCHAR)""",
        """CREATE TABLE IF NOT EXISTS security_series_interval_complete(
            contract_version VARCHAR, identity_key VARCHAR, value VARCHAR,
            valid_from DATE, valid_to DATE, confidence_state VARCHAR,
            source_event_ids VARCHAR, issue_codes VARCHAR)""",
        """CREATE TABLE IF NOT EXISTS security_isin_interval_complete(
            contract_version VARCHAR, identity_key VARCHAR, isin VARCHAR,
            valid_from DATE, valid_to DATE, confidence_state VARCHAR)""",
        """CREATE TABLE IF NOT EXISTS security_membership_interval_complete(
            contract_version VARCHAR, identity_key VARCHAR, valid_from DATE,
            valid_to DATE, state VARCHAR, tradable BOOLEAN,
            source_event_ids VARCHAR, identity_days BIGINT, issue_codes VARCHAR)""",
        """CREATE TABLE IF NOT EXISTS security_tradability_interval_complete(
            contract_version VARCHAR, identity_key VARCHAR, valid_from DATE,
            valid_to DATE, state VARCHAR, tradable BOOLEAN,
            source_event_ids VARCHAR, identity_days BIGINT, issue_codes VARCHAR)""",
        """CREATE TABLE IF NOT EXISTS security_suspension_interval_complete(
            contract_version VARCHAR, identity_key VARCHAR, valid_from DATE,
            valid_to DATE, restoration_date DATE, source_event_ids VARCHAR,
            state VARCHAR)""",
        """CREATE TABLE IF NOT EXISTS security_termination_event_complete(
            contract_version VARCHAR, identity_key VARCHAR, termination_date DATE,
            event_type VARCHAR, source_event_id VARCHAR, source_id VARCHAR)""",
        """CREATE TABLE IF NOT EXISTS security_predecessor_successor_complete(
            contract_version VARCHAR, transition_id VARCHAR, transition_type VARCHAR,
            effective_date DATE, predecessor_identity VARCHAR,
            successor_identity VARCHAR, old_symbol VARCHAR, new_symbol VARCHAR,
            old_series VARCHAR, new_series VARCHAR, old_isin VARCHAR,
            new_isin VARCHAR, source_event_id VARCHAR, final_state VARCHAR,
            issue_codes VARCHAR)""",
        """CREATE TABLE IF NOT EXISTS security_identity_lineage_complete(
            contract_version VARCHAR, identity_key VARCHAR, source_ids VARCHAR,
            source_count BIGINT)""",
        """CREATE TABLE IF NOT EXISTS security_membership_rejection_complete(
            contract_version VARCHAR, source_id VARCHAR, failure_code VARCHAR,
            failure_detail VARCHAR, raw_identifier VARCHAR)""",
        """CREATE TABLE IF NOT EXISTS security_candle_reconciliation_summary(
            contract_version VARCHAR, identity_key VARCHAR, state VARCHAR,
            row_count BIGINT, first_date DATE, last_date DATE)""",
        """CREATE TABLE IF NOT EXISTS security_dataset_certification(
            contract_version VARCHAR, identity_key VARCHAR, identity_coverage VARCHAR,
            listing_coverage VARCHAR, termination_coverage VARCHAR,
            suspension_coverage VARCHAR, symbol_history_coverage VARCHAR,
            series_history_coverage VARCHAR, isin_history_coverage VARCHAR,
            membership_coverage VARCHAR, tradability_coverage VARCHAR,
            candle_reconciliation VARCHAR, source_lineage_coverage VARCHAR,
            corporate_transition_coverage VARCHAR, overall_state VARCHAR,
            unresolved_blockers VARCHAR)""",
        """CREATE TABLE IF NOT EXISTS complete_security_dataset_run(
            contract_version VARCHAR, start_date DATE, end_date DATE,
            report_sha256 VARCHAR, report_json VARCHAR,
            PRIMARY KEY(contract_version, report_sha256))""",
    )
    for statement in statements:
        connection.execute(statement)


def _replace_contract_rows(connection: duckdb.DuckDBPyConnection) -> None:
    tables = (
        "complete_security_identity",
        "complete_security_census",
        "security_identity_interval_complete",
        "security_symbol_interval_complete",
        "security_series_interval_complete",
        "security_isin_interval_complete",
        "security_membership_interval_complete",
        "security_tradability_interval_complete",
        "security_suspension_interval_complete",
        "security_termination_event_complete",
        "security_predecessor_successor_complete",
        "security_identity_lineage_complete",
        "security_membership_rejection_complete",
        "security_candle_reconciliation_summary",
        "security_dataset_certification",
        "complete_security_dataset_run",
    )
    for table in tables:
        connection.execute(
            f"DELETE FROM {table} WHERE contract_version = ?",  # noqa: S608
            [HTR010A_CONTRACT_VERSION],
        )


def _insert_report_rows(
    connection: duckdb.DuckDBPyConnection,
    report: CompleteSecurityDatasetReport,
) -> None:
    version = HTR010A_CONTRACT_VERSION
    _many(
        connection,
        "complete_security_identity",
        14,
        [
            (
                version,
                i.identity_key,
                i.exchange,
                i.isin,
                i.current_symbol,
                i.current_series,
                i.current_name,
                i.first_evidence_date,
                i.last_evidence_date,
                i.identity_state.value,
                _join(i.secondary_issue_codes),
                _join(i.official_source_ids),
                i.synthetic_reason,
                i.candidate_independent,
            )
            for i in report.identities
        ],
    )
    _many(
        connection,
        "complete_security_census",
        13,
        [
            (
                version,
                i.exchange,
                i.symbol,
                i.series,
                i.isin,
                i.security_name,
                i.first_observed,
                i.last_observed,
                i.candle_rows,
                _join(i.source_ids),
                i.source_record_count,
                i.supported_security_type,
                i.identity_key,
            )
            for i in report.census
        ],
    )
    _many(
        connection,
        "security_identity_interval_complete",
        7,
        [
            (
                version,
                i.identity_key,
                i.valid_from,
                i.valid_to,
                i.identity_state.value,
                _join(i.source_event_ids),
                _join(i.issue_codes),
            )
            for i in report.identity_intervals
        ],
    )
    for table, interval_values in (
        ("security_symbol_interval_complete", report.symbol_intervals),
        ("security_series_interval_complete", report.series_intervals),
    ):
        _many(
            connection,
            table,
            8,
            [
                (
                    version,
                    i.identity_key,
                    i.value,
                    i.valid_from,
                    i.valid_to,
                    i.confidence_state,
                    _join(i.source_event_ids),
                    _join(i.issue_codes),
                )
                for i in interval_values
            ],
        )
    _many(
        connection,
        "security_isin_interval_complete",
        6,
        [
            (
                version,
                i.identity_key,
                i.isin,
                i.first_evidence_date,
                i.last_evidence_date,
                "HIGH"
                if i.identity_state is IdentityState.GOVERNED_IDENTITY
                else "LOW",
            )
            for i in report.identities
            if i.isin and i.first_evidence_date and i.last_evidence_date
        ],
    )
    for table, values in (
        ("security_membership_interval_complete", report.membership_intervals),
        ("security_tradability_interval_complete", report.tradability_intervals),
    ):
        _many(
            connection,
            table,
            9,
            [
                (
                    version,
                    i.identity_key,
                    i.valid_from,
                    i.valid_to,
                    i.state.value,
                    i.tradable,
                    _join(i.source_event_ids),
                    i.identity_days,
                    _join(i.issue_codes),
                )
                for i in values
            ],
        )
    _many(
        connection,
        "security_suspension_interval_complete",
        7,
        [
            (
                version,
                i.identity_key,
                i.valid_from,
                i.valid_to,
                i.restoration_date,
                _join(i.source_event_ids),
                i.state,
            )
            for i in report.suspensions
        ],
    )
    _many(
        connection,
        "security_termination_event_complete",
        6,
        [
            (
                version,
                i.identity_key,
                i.termination_date,
                i.event_type,
                i.source_event_id,
                i.source_id,
            )
            for i in report.terminations
        ],
    )
    _many(
        connection,
        "security_predecessor_successor_complete",
        15,
        [
            (
                version,
                i.transition_id,
                i.transition_type,
                i.effective_date,
                i.predecessor_identity,
                i.successor_identity,
                i.old_symbol,
                i.new_symbol,
                i.old_series,
                i.new_series,
                i.old_isin,
                i.new_isin,
                i.source_event_id,
                i.final_state,
                _join(i.issue_codes),
            )
            for i in report.transitions
        ],
    )
    _many(
        connection,
        "security_identity_lineage_complete",
        4,
        [
            (
                version,
                i.identity_key,
                _join(i.official_source_ids),
                len(i.official_source_ids),
            )
            for i in report.identities
        ],
    )
    _many(
        connection,
        "security_membership_rejection_complete",
        5,
        [
            (version, i.source_id, i.failure_code, i.failure_detail, i.raw_identifier)
            for i in report.rejected_evidence
        ],
    )
    _many(
        connection,
        "security_candle_reconciliation_summary",
        6,
        [
            (
                version,
                i.identity_key,
                i.state.value,
                i.row_count,
                i.first_date,
                i.last_date,
            )
            for i in report.candle_reconciliation
        ],
    )
    _many(
        connection,
        "security_dataset_certification",
        16,
        [
            (
                version,
                i.identity_key,
                i.identity_coverage,
                i.listing_coverage,
                i.termination_coverage,
                i.suspension_coverage,
                i.symbol_history_coverage,
                i.series_history_coverage,
                i.isin_history_coverage,
                i.membership_coverage,
                i.tradability_coverage,
                i.candle_reconciliation,
                i.source_lineage_coverage,
                i.corporate_transition_coverage,
                i.overall_state.value,
                _join(i.unresolved_blockers),
            )
            for i in report.certification_matrix
        ],
    )


def _create_views(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """CREATE OR REPLACE VIEW complete_point_in_time_universe AS
           SELECT m.valid_from, m.valid_to, i.identity_key, i.exchange,
                  s.value AS symbol, r.value AS series, i.isin,
                  i.current_name AS security_name, m.state AS membership_state,
                  t.state AS tradability_state, t.tradable,
                  i.identity_state, i.official_source_ids,
                  CASE WHEN m.state LIKE 'CERTIFIED_%' THEN 'CERTIFIED'
                       ELSE 'PROVISIONAL' END AS certification_state
           FROM security_membership_interval_complete m
           JOIN complete_security_identity i USING(contract_version, identity_key)
           LEFT JOIN security_symbol_interval_complete s
             ON s.contract_version=m.contract_version AND s.identity_key=m.identity_key
            AND s.valid_from <= m.valid_to AND s.valid_to >= m.valid_from
           LEFT JOIN security_series_interval_complete r
             ON r.contract_version=m.contract_version AND r.identity_key=m.identity_key
            AND r.valid_from <= m.valid_to AND r.valid_to >= m.valid_from
           LEFT JOIN security_tradability_interval_complete t
             ON t.contract_version=m.contract_version AND t.identity_key=m.identity_key
            AND t.valid_from=m.valid_from AND t.valid_to=m.valid_to
           WHERE m.contract_version='HTR-010A-v1.0.0'"""
    )
    connection.execute(
        """CREATE OR REPLACE VIEW security_candle_reconciliation AS
           SELECT d.*, c.identity_key, i.identity_state,
                  COALESCE(
                    m.state, 'UNRESOLVED_NO_LISTING_EVIDENCE'
                  ) AS membership_state,
                  COALESCE(
                    t.state, 'UNRESOLVED_NO_LISTING_EVIDENCE'
                  ) AS tradability_state,
                  CASE
                    WHEN c.supported_security_type = FALSE THEN 'UNSUPPORTED_SERIES'
                    WHEN i.identity_state IN (
                         'MISSING_IDENTITY_EVIDENCE','INVALID_ISIN',
                         'AMBIGUOUS_IDENTITY') THEN 'IDENTITY_UNRESOLVED'
                    WHEN m.identity_key IS NULL THEN 'PROVISIONAL_IN_INTERVAL'
                    WHEN m.state='CERTIFIED_ACTIVE_SUSPENDED' THEN 'SUSPENDED_DATE_ROW'
                    WHEN m.state IN ('CERTIFIED_ACTIVE_TRADABLE','CERTIFIED_RELISTED')
                         THEN 'CERTIFIED_IN_INTERVAL'
                    ELSE 'PROVISIONAL_IN_INTERVAL'
                  END AS reconciliation_state
           FROM daily_candle d
           LEFT JOIN complete_security_census c
             ON c.contract_version='HTR-010A-v1.0.0'
            AND UPPER(d.exchange)=c.exchange AND UPPER(d.symbol)=c.symbol
            AND UPPER(d.series)=c.series
            AND COALESCE(UPPER(d.isin),'')=COALESCE(c.isin,'')
           LEFT JOIN complete_security_identity i
             ON i.contract_version=c.contract_version AND i.identity_key=c.identity_key
           LEFT JOIN security_membership_interval_complete m
             ON m.contract_version=c.contract_version AND m.identity_key=c.identity_key
            AND d.trading_date BETWEEN m.valid_from AND m.valid_to
           LEFT JOIN security_tradability_interval_complete t
             ON t.contract_version=c.contract_version AND t.identity_key=c.identity_key
            AND d.trading_date BETWEEN t.valid_from AND t.valid_to"""
    )


def _many(
    connection: duckdb.DuckDBPyConnection,
    table: str,
    columns: int,
    rows: Sequence[tuple[Any, ...]],
) -> None:
    if rows:
        placeholders = ",".join("?" for _ in range(columns))
        connection.executemany(
            f"INSERT INTO {table} VALUES ({placeholders})",  # noqa: S608
            rows,
        )


def _population_summary(
    census: Sequence[SecurityCensusRecord],
    identities: Sequence[CompleteSecurityIdentity],
) -> PopulationSummary:
    return PopulationSummary(
        len({item.symbol for item in census}),
        len({(item.symbol, item.series) for item in census}),
        len({item.isin for item in census if _valid_isin(item.isin)}),
        sum(
            item.identity_state is IdentityState.GOVERNED_IDENTITY
            for item in identities
        ),
        sum(
            item.identity_state is IdentityState.PROVISIONAL_IDENTITY
            for item in identities
        ),
        sum(
            item.identity_state
            in {
                IdentityState.MISSING_IDENTITY_EVIDENCE,
                IdentityState.INVALID_ISIN,
                IdentityState.AMBIGUOUS_IDENTITY,
            }
            for item in identities
        ),
        sum(
            item.identity_state is IdentityState.UNSUPPORTED_SECURITY_TYPE
            for item in identities
        ),
    )


def _evidence_summary(sources: Sequence[SourceInventoryRecord]) -> EvidenceSummary:
    return EvidenceSummary(
        len({item.source_family for item in sources}),
        len(sources),
        sum(item.status is SourceStatus.ACQUIRED for item in sources),
        sum(item.status is SourceStatus.REUSED for item in sources),
        sum(
            item.status in {SourceStatus.FAILED, SourceStatus.REJECTED}
            for item in sources
        ),
        sum(item.records_parsed for item in sources),
        sum(item.records_admitted for item in sources),
        sum(item.records_rejected for item in sources),
    )


def _membership_summary(
    membership: Sequence[CompleteMembershipInterval],
    tradability: Sequence[CompleteMembershipInterval],
    suspensions: Sequence[SuspensionInterval],
    terminations: Sequence[TerminationRecord],
) -> MembershipSummary:
    certified = sum(
        i.identity_days for i in membership if i.state.value in _CERTIFIED_MEMBERSHIP
    )
    provisional = sum(
        i.identity_days
        for i in membership
        if i.state is MembershipState.PROVISIONAL_ACTIVE
    )
    unresolved = sum(
        i.identity_days
        for i in membership
        if i.state.value not in _CERTIFIED_MEMBERSHIP
        and i.state is not MembershipState.PROVISIONAL_ACTIVE
    )
    return MembershipSummary(
        len(membership),
        len(tradability),
        sum(bool(i.source_event_ids) for i in membership),
        len(terminations),
        len(suspensions),
        sum(i.restoration_date is not None for i in suspensions),
        sum(i.state is MembershipState.CERTIFIED_RELISTED for i in membership),
        certified + provisional + unresolved,
        certified,
        provisional,
        unresolved,
    )


def _candle_summary(items: Sequence[CandleReconciliationSummary]) -> CandleSummary:
    counts: defaultdict[CandleReconciliationState, int] = defaultdict(int)
    for item in items:
        counts[item.state] += item.row_count
    return CandleSummary(
        sum(counts.values()),
        counts[CandleReconciliationState.CERTIFIED_IN_INTERVAL],
        counts[CandleReconciliationState.PROVISIONAL_IN_INTERVAL],
        counts[CandleReconciliationState.PRE_LISTING_ROW],
        counts[CandleReconciliationState.POST_TERMINATION_ROW],
        counts[CandleReconciliationState.SUSPENDED_DATE_ROW],
        counts[CandleReconciliationState.SYMBOL_INTERVAL_MISMATCH],
        counts[CandleReconciliationState.SERIES_INTERVAL_MISMATCH],
        counts[CandleReconciliationState.ISIN_MISMATCH],
        counts[CandleReconciliationState.IDENTITY_UNRESOLVED],
        counts[CandleReconciliationState.UNSUPPORTED_SERIES],
    )


def _continuity_summary(
    gaps: Sequence[SecuritySessionGapSummary],
    reconciliation: Sequence[CandleReconciliationSummary],
    identities: Sequence[CompleteSecurityIdentity],
) -> ContinuitySummary:
    unexplained = sum(
        i.gap_count for i in gaps if i.classification == "UNEXPLAINED_INTERNAL_GAP"
    )
    explained = sum(
        i.gap_count for i in gaps if i.classification != "UNEXPLAINED_INTERNAL_GAP"
    )
    unresolved_keys = {
        i.identity_key for i in gaps if i.classification == "UNEXPLAINED_INTERNAL_GAP"
    }
    observed = sum(i.row_count for i in reconciliation)
    return ContinuitySummary(
        observed + explained + unexplained,
        observed,
        explained,
        unexplained,
        len(identities) - len(unresolved_keys),
        len(unresolved_keys),
    )


def _certification_summary(
    matrix: Sequence[DatasetCertificationRecord],
    reuse: Sequence[SymbolReuseRecord],
    transitions: Sequence[TransitionRecord],
    suspensions: Sequence[SuspensionInterval],
    candles: CandleSummary,
) -> CertificationSummary:
    blockers = []
    if any(i.listing_coverage == "MISSING" for i in matrix):
        blockers.append(OverallCertificationState.BLOCKED_LISTING_EVIDENCE)
    if any(i.termination_coverage == "UNKNOWN_OR_ACTIVE" for i in matrix):
        blockers.append(OverallCertificationState.BLOCKED_TERMINATION_EVIDENCE)
    if not suspensions:
        blockers.append(OverallCertificationState.BLOCKED_SUSPENSION_EVIDENCE)
    if any(i.interval_overlap for i in reuse):
        blockers.append(OverallCertificationState.BLOCKED_SYMBOL_REUSE)
    if any(i.final_state == "UNRESOLVED" for i in transitions):
        blockers.append(OverallCertificationState.BLOCKED_IDENTITY_TRANSITIONS)
    if candles.unresolved_rows or candles.unsupported_series_rows:
        blockers.append(OverallCertificationState.BLOCKED_CANDLE_RECONCILIATION)
    if any(i.overall_state is CertificationTier.CONFLICTING for i in matrix):
        blockers.append(OverallCertificationState.BLOCKED_CONFLICTING_OFFICIAL_EVIDENCE)
    unique = tuple(dict.fromkeys(blockers))
    primary = (
        OverallCertificationState.FULL_MARKET_IDENTITY_MEMBERSHIP_CERTIFIED
        if not unique
        else OverallCertificationState.PARTIALLY_CERTIFIED
    )
    tier_a = sum(i.overall_state is CertificationTier.TIER_A_CERTIFIED for i in matrix)
    return CertificationSummary(
        primary,
        unique,
        (
            "Governed exchange-plus-ISIN identity.",
            "Official listing or admission boundary.",
            "Official termination boundary or evidenced active checkpoint.",
            "Official symbol and series history with no unresolved reuse.",
            "Point-in-time membership interval and source lineage.",
        ),
        tier_a,
        tier_a / len(matrix) if matrix else 0.0,
        "Certification is fail-closed: any material full-market evidence gap "
        "remains a blocker.",
    )


def _filter_report(
    report: CompleteSecurityDatasetReport,
    *,
    symbols: tuple[str, ...],
    isins: tuple[str, ...],
    years: tuple[int, ...],
    identity_states: tuple[IdentityState, ...],
    membership_states: tuple[MembershipState, ...],
    only_unresolved: bool,
    only_conflicting: bool,
) -> CompleteSecurityDatasetReport:
    if not any(
        (
            symbols,
            isins,
            years,
            identity_states,
            membership_states,
            only_unresolved,
            only_conflicting,
        )
    ):
        return report
    wanted_symbols = {i.upper() for i in symbols}
    wanted_isins = {i.upper() for i in isins}
    identity_by_key = {i.identity_key: i for i in report.identities}
    census_keys = {
        i.identity_key
        for i in report.census
        if (not wanted_symbols or i.symbol in wanted_symbols)
        and (not wanted_isins or i.isin in wanted_isins)
        and (
            not years
            or any(
                i.first_observed
                and i.last_observed
                and i.first_observed.year <= year <= i.last_observed.year
                for year in years
            )
        )
    }
    keys = {
        key
        for key in census_keys
        if (
            not identity_states
            or identity_by_key[key].identity_state in identity_states
        )
        and (
            not only_unresolved
            or identity_by_key[key].identity_state
            is not IdentityState.GOVERNED_IDENTITY
        )
        and (
            not only_conflicting
            or bool(
                set(identity_by_key[key].secondary_issue_codes) & _CONFLICTING_CODES
            )
        )
    }
    if membership_states:
        keys &= {
            i.identity_key
            for i in report.membership_intervals
            if i.state in membership_states
        }

    def selected(items: Iterable[Any]) -> tuple[Any, ...]:
        return tuple(i for i in items if getattr(i, "identity_key", None) in keys)

    return replace(
        report,
        census=selected(report.census),
        identities=selected(report.identities),
        identity_intervals=selected(report.identity_intervals),
        symbol_intervals=selected(report.symbol_intervals),
        series_intervals=selected(report.series_intervals),
        membership_intervals=selected(report.membership_intervals),
        tradability_intervals=selected(report.tradability_intervals),
        suspensions=selected(report.suspensions),
        terminations=selected(report.terminations),
        candle_reconciliation=selected(report.candle_reconciliation),
        security_session_gaps=selected(report.security_session_gaps),
        certification_matrix=selected(report.certification_matrix),
    )


def _report_from_payload(payload: dict[str, Any]) -> CompleteSecurityDatasetReport:
    def records(key: str, cls: Any) -> tuple[Any, ...]:
        return tuple(cls(**_convert_record(cls, item)) for item in payload.get(key, ()))

    return CompleteSecurityDatasetReport(
        payload["contract_version"],
        bool(payload["production_influence"]),
        payload["database_path"],
        date.fromisoformat(payload["start_date"]),
        date.fromisoformat(payload["end_date"]),
        records("source_inventory", SourceInventoryRecord),
        records("rejected_evidence", RejectedEvidenceRecord),
        records("census", SecurityCensusRecord),
        records("identities", CompleteSecurityIdentity),
        records("identity_intervals", IdentityInterval),
        records("symbol_intervals", AttributeInterval),
        records("series_intervals", AttributeInterval),
        records("membership_intervals", CompleteMembershipInterval),
        records("tradability_intervals", CompleteMembershipInterval),
        records("suspensions", SuspensionInterval),
        records("terminations", TerminationRecord),
        records("symbol_reuse", SymbolReuseRecord),
        records("transitions", TransitionRecord),
        records("candle_reconciliation", CandleReconciliationSummary),
        records("security_session_gaps", SecuritySessionGapSummary),
        records("certification_matrix", DatasetCertificationRecord),
        PopulationSummary(**payload["population_summary"]),
        EvidenceSummary(**payload["evidence_summary"]),
        MembershipSummary(**payload["membership_summary"]),
        CandleSummary(**payload["candle_summary"]),
        ContinuitySummary(**payload["continuity_summary"]),
        YtdSummary(**_convert_dates(payload["ytd_summary"])),
        CertificationSummary(
            **_convert_record(CertificationSummary, payload["certification"])
        ),
        payload["report_sha256"],
    )


def _convert_record(cls: Any, item: dict[str, Any]) -> dict[str, Any]:
    converted = dict(item)
    date_fields = {
        "first_observed",
        "last_observed",
        "first_evidence_date",
        "last_evidence_date",
        "valid_from",
        "valid_to",
        "restoration_date",
        "termination_date",
        "effective_date",
        "first_date",
        "last_date",
    }
    for key in date_fields & converted.keys():
        if converted[key] is not None:
            converted[key] = date.fromisoformat(converted[key])
    tuple_fields = {
        "redirects",
        "source_ids",
        "official_source_ids",
        "secondary_issue_codes",
        "source_event_ids",
        "issue_codes",
        "identity_keys",
        "isins",
        "unresolved_blockers",
        "secondary_blockers",
        "tier_a_thresholds",
    }
    for key in tuple_fields & converted.keys():
        converted[key] = tuple(converted[key])
    if cls is SourceInventoryRecord:
        converted["status"] = SourceStatus(converted["status"])
    if cls in {CompleteSecurityIdentity, IdentityInterval}:
        converted["identity_state"] = IdentityState(converted["identity_state"])
    if cls is CompleteMembershipInterval:
        converted["state"] = MembershipState(converted["state"])
    if cls is CandleReconciliationSummary:
        converted["state"] = CandleReconciliationState(converted["state"])
    if cls is DatasetCertificationRecord:
        converted["overall_state"] = CertificationTier(converted["overall_state"])
    if cls is CertificationSummary:
        converted["primary_state"] = OverallCertificationState(
            converted["primary_state"]
        )
    if "secondary_blockers" in converted:
        converted["secondary_blockers"] = tuple(
            OverallCertificationState(i) for i in converted["secondary_blockers"]
        )
    return converted


def _convert_dates(item: dict[str, Any]) -> dict[str, Any]:
    converted = dict(item)
    for key in (
        "calendar_cutoff",
        "canonical_cutoff",
        "identity_evidence_cutoff",
        "final_common_date",
    ):
        if converted.get(key):
            converted[key] = date.fromisoformat(converted[key])
    return converted


def _table_exists(connection: duckdb.DuckDBPyConnection, table: str) -> bool:
    row = connection.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
        [table],
    ).fetchone()
    return bool(row and row[0])


def _verify_source_checksums(sources: Sequence[SourceInventoryRecord]) -> None:
    for source in sources:
        if source.source_path is None or source.sha256 is None:
            continue
        path = Path(source.source_path)
        if not path.is_file():
            raise ValueError(f"governed source is missing: {path}")
        actual = sha256(path.read_bytes()).hexdigest()
        if actual != source.sha256:
            raise ValueError(f"governed source checksum mismatch: {path}")


def _governed_identity_keys(connection: duckdb.DuckDBPyConnection) -> frozenset[str]:
    if not _table_exists(connection, "security_event"):
        return frozenset()
    rows = connection.execute(
        """SELECT DISTINCT UPPER(COALESCE(new_isin, old_isin))
           FROM security_event WHERE admission_state = 'ADMITTED'
             AND COALESCE(new_isin, old_isin) IS NOT NULL"""
    ).fetchall()
    return frozenset(f"nse:isin:{row[0]}" for row in rows if _valid_isin(row[0]))


def _valid_isin(value: object) -> bool:
    return isinstance(value, str) and bool(_ISIN.fullmatch(value.upper()))


def _membership_state(value: str) -> MembershipState:
    aliases = {"CERTIFIED_POST_DELISTING": "CERTIFIED_POST_TERMINATION"}
    return MembershipState(aliases.get(value, value))


def _split(value: object) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return tuple(str(item) for item in parsed)
        except json.JSONDecodeError:
            return tuple(item for item in value.split("|") if item)
    return tuple(str(item) for item in cast(Iterable[Any], value))


def _join(values: Sequence[str]) -> str:
    return json.dumps(list(values), separators=(",", ":"))


def _min_date(left: date | None, right: date | None) -> date | None:
    return (
        min(item for item in (left, right) if item is not None)
        if left or right
        else None
    )


def _max_date(left: date | None, right: date | None) -> date | None:
    return (
        max(item for item in (left, right) if item is not None)
        if left or right
        else None
    )


__all__ = ["CompleteSecurityDatasetCertificationEngine"]
