"""Candidate-independent HTR-010A1 population and interval repair engine."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb

from alpha.historical_truth.security_population_repair_models import (
    HTR010A1_CONTRACT_VERSION,
    PRODUCTION_INFLUENCE,
    SUPPORT_POLICY_VERSION,
    BoundaryEvidenceRecord,
    BoundaryState,
    CensusReconciliationRecord,
    CertificationState,
    CheckpointReconciliationRecord,
    DenominatorSummary,
    GapClassification,
    IdentityDenominatorRecord,
    InstrumentTaxonomyRecord,
    InstrumentType,
    IntervalConflictRecord,
    IntervalGapRecord,
    IntervalRepairRecord,
    OverlapClassification,
    PopulationRepairCertification,
    PopulationRepairSummary,
    RepairAction,
    RepairSummary,
    SecurityPopulationRepairReport,
    SupportedSecurityCertification,
    SupportPolicyRecord,
    SupportState,
    SuspensionEvidenceRecord,
    TierCandleReconciliationRecord,
    TierContinuityRecord,
    UniverseReconciliationRecord,
    stable_record_id,
)
from alpha.historical_truth.security_population_repair_sources import (
    OfficialMasterRecord,
    SecurityPopulationSourceInventory,
    SourceEvidence,
    verify_source_checksums,
)

_CORE_EQUITY_SERIES = frozenset({"EQ", "BE", "BZ"})
_SME_SERIES = frozenset({"SM", "ST"})
_PARTLY_PAID_SERIES = frozenset({"E1", "E2", "E3", "E4", "E5", "E6"})
_TEMPORARY_SERIES = frozenset({"BL", "IL", "IQ", "RL", "SL", "SQ"})
_GOVERNMENT_SERIES = frozenset({"GB", "GS", "SG", "TB"})
_DEBT_PREFIXES = ("N", "U", "Y", "D")
_SUPPORT_ORDER = {
    SupportState.TIER_A_CORE_EQUITY: 0,
    SupportState.SUPPORTED_EQUITY_NON_CORE: 1,
    SupportState.SUPPORTED_SEPARATE_ASSET_CLASS: 2,
    SupportState.PRESERVED_UNSUPPORTED: 3,
    SupportState.CONFLICTING_CLASSIFICATION: 4,
    SupportState.UNKNOWN_CLASSIFICATION: 5,
}


class SecurityPopulationRepairEngine:
    """Repair population scope without influencing replay or production policy."""

    def __init__(self, database_path: Path, root: Path) -> None:
        self.database_path = database_path
        self.root = root
        self.sources = SecurityPopulationSourceInventory(root)

    def run(
        self,
        *,
        htr010a_output: Path,
        start_date: date,
        end_date: date,
        output: Path,
        refresh_sources: bool,
        verify_only: bool,
    ) -> SecurityPopulationRepairReport:
        if refresh_sources and verify_only:
            raise ValueError("refresh_sources and verify_only are mutually exclusive")
        masters, evidence = self.sources.collect(
            refresh_sources=refresh_sources,
        )
        verify_source_checksums(evidence)
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            report = self._build(
                connection,
                masters,
                evidence,
                htr010a_output,
                start_date,
                end_date,
            )
        self._persist_sidecar(report, output / "htr010a1_repair.duckdb")
        return report

    def _build(
        self,
        connection: duckdb.DuckDBPyConnection,
        masters: tuple[OfficialMasterRecord, ...],
        evidence: tuple[SourceEvidence, ...],
        htr010a_output: Path,
        start_date: date,
        end_date: date,
    ) -> SecurityPopulationRepairReport:
        census = _fetch_dicts(
            connection,
            "SELECT * FROM complete_security_census "
            "ORDER BY identity_key, symbol, series",
        )
        identities = _fetch_dicts(
            connection,
            "SELECT * FROM complete_security_identity ORDER BY identity_key",
        )
        masters_by_key: dict[str, list[OfficialMasterRecord]] = defaultdict(list)
        for master in masters:
            masters_by_key[master.identity_key].append(master)
        taxonomy = self._taxonomy(census, masters_by_key)
        policy = tuple(_policy(item) for item in taxonomy)
        identity_states = _identity_support_states(policy)
        intervals = _support_intervals(
            identities,
            masters_by_key,
            identity_states,
            start_date,
            end_date,
        )
        overlaps, repairs = self._overlaps(connection, identity_states)
        gaps = self._gaps(connection, census)
        listing, termination = _boundaries(
            connection,
            identities,
            masters_by_key,
            start_date,
            end_date,
        )
        suspension = _suspension_evidence(evidence)
        denominator = _denominators(
            connection,
            identities,
            intervals,
            identity_states,
            listing,
            termination,
        )
        checkpoints = _checkpoints(masters, intervals, identity_states)
        universe = _universe(end_date, intervals, identity_states, masters)
        candle = _candle_reconciliation(connection, identity_states, intervals)
        continuity = _continuity(connection, candle, denominator)
        certifications = _certifications(
            identities,
            taxonomy,
            identity_states,
            intervals,
            overlaps,
            gaps,
            listing,
            termination,
            suspension,
        )
        census_reconciliation = _census_reconciliation(
            census,
            taxonomy,
            policy,
        )
        symbol_reuse = _load_json_records(htr010a_output / "htr010a_symbol_reuse.json")
        population_summary = _population_summary(
            census,
            identities,
            identity_states,
            set(masters_by_key),
        )
        repair_summary = _repair_summary(overlaps, gaps, symbol_reuse)
        denominator_summary = _denominator_summary(denominator)
        blockers = _blockers(certifications, gaps, overlaps, suspension)
        tier_a_ready = not any(
            item.certification_state
            in {
                CertificationState.UNRESOLVED,
                CertificationState.CONFLICTING,
                CertificationState.IDENTITY_CERTIFIED_INTERVAL_CONFLICT,
            }
            and item.support_state is SupportState.TIER_A_CORE_EQUITY
            for item in certifications
        )
        certification = PopulationRepairCertification(
            "PARTIALLY_CERTIFIED" if blockers else "CERTIFIED",
            tier_a_ready,
            (
                "READY_FOR_HTR010B"
                if tier_a_ready
                else "NOT_READY_FOR_HTR010B_UNRESOLVED_IDENTITY_BOUNDARIES"
            ),
            blockers,
            "Fail-closed certification separates membership evidence from "
            "tradability and never treats candles as listing proof.",
        )
        rejected = tuple(
            {
                "source_id": item.source_id,
                "failure_code": item.failure_code,
                "failure_detail": item.failure_detail,
            }
            for item in evidence
            if item.failure_code
        )
        source_checksums = tuple(
            sorted(
                (item.source_path, item.source_sha256)
                for item in evidence
                if item.source_path and item.source_sha256
            )
        )
        report = SecurityPopulationRepairReport(
            HTR010A1_CONTRACT_VERSION,
            SUPPORT_POLICY_VERSION,
            PRODUCTION_INFLUENCE,
            str(self.database_path),
            start_date,
            end_date,
            taxonomy,
            policy,
            census_reconciliation,
            denominator,
            overlaps,
            repairs,
            gaps,
            symbol_reuse,
            listing,
            termination,
            suspension,
            checkpoints,
            universe,
            candle,
            continuity,
            certifications,
            rejected,
            population_summary,
            repair_summary,
            denominator_summary,
            certification,
            source_checksums,
            "",
        )
        return replace(report, report_sha256=report.calculated_sha256())

    def _taxonomy(
        self,
        census: Sequence[dict[str, Any]],
        masters_by_key: dict[str, list[OfficialMasterRecord]],
    ) -> tuple[InstrumentTaxonomyRecord, ...]:
        records: list[InstrumentTaxonomyRecord] = []
        for row in census:
            key = str(row["identity_key"])
            candidates = masters_by_key.get(key, [])
            exact = [item for item in candidates if item.series == row["series"]]
            master = (
                max(exact or candidates, key=lambda item: item.checkpoint_date)
                if candidates
                else None
            )
            instrument, reason, confidence = classify_instrument(
                symbol=str(row["symbol"]),
                series=str(row["series"]),
                isin=_text(row["isin"]),
                security_name=_text(row["security_name"]),
                security_type_flag=(master.security_type_flag if master else None),
                official_instrument_type=(master.instrument_type if master else None),
            )
            records.append(
                InstrumentTaxonomyRecord(
                    key,
                    "NSE",
                    str(row["symbol"]),
                    str(row["series"]),
                    _text(row["isin"]),
                    _text(row["security_name"])
                    or (master.security_name if master else None),
                    master.security_type_flag if master else None,
                    master.instrument_type if master else None,
                    instrument,
                    master.listing_date if master else row["first_observed"],
                    master.removal_date if master else row["last_observed"],
                    master.source_id if master else "canonical_daily_candle",
                    master.source_path if master else str(self.database_path),
                    master.source_sha256 if master else "",
                    reason,
                    confidence,
                    () if master else ("OFFICIAL_INSTRUMENT_CLASSIFICATION_MISSING",),
                )
            )
        return tuple(records)

    def _overlaps(
        self,
        connection: duckdb.DuckDBPyConnection,
        states: dict[str, SupportState],
    ) -> tuple[
        tuple[IntervalConflictRecord, ...],
        tuple[IntervalRepairRecord, ...],
    ]:
        flagged = connection.execute(
            """SELECT identity_key, valid_from, valid_to
               FROM security_identity_interval_complete
               WHERE issue_codes LIKE '%OVERLAPPING_IDENTITY_INTERVALS%'
               ORDER BY identity_key"""
        ).fetchall()
        symbol = _interval_map(connection, "security_symbol_interval_complete")
        series = _interval_map(connection, "security_series_interval_complete")
        conflicts: list[IntervalConflictRecord] = []
        repairs: list[IntervalRepairRecord] = []
        for key, identity_from, identity_to in flagged:
            symbol_pair = _first_overlap(symbol.get(key, ()))
            series_pair = _first_overlap(series.get(key, ()))
            if series_pair[0] is not None:
                left, right = series_pair
                attribute = "series"
            else:
                left, right = symbol_pair
                attribute = "symbol"
            if left is None or right is None:
                left = ("identity", identity_from, identity_to, (), ())
                right = left
                attribute = "identity"
            classification, action = _classify_overlap(key, left, right, states[key])
            overlap_start = max(left[1], right[1])
            overlap_end = min(left[2], right[2])
            conflict_id = stable_record_id(
                "overlap", key, left[0], right[0], overlap_start, overlap_end
            )
            issue = (
                ()
                if action is not RepairAction.RETAINED_CONFLICTING
                else ("UNRESOLVED_INTERVAL_OVERLAP",)
            )
            conflicts.append(
                IntervalConflictRecord(
                    conflict_id,
                    key,
                    attribute,
                    left[0],
                    right[0],
                    overlap_start,
                    overlap_end,
                    classification,
                    action,
                    left[3],
                    right[3],
                    issue,
                )
            )
            if action in {
                RepairAction.MERGED,
                RepairAction.RETAINED_PARALLEL,
                RepairAction.EXCLUDED_FROM_SUPPORTED_DENOMINATOR,
            }:
                repairs.append(
                    IntervalRepairRecord(
                        stable_record_id("repair", conflict_id, action),
                        key,
                        attribute,
                        left[0],
                        (
                            f"{left[0]}:{left[1]}:{left[2]}",
                            f"{right[0]}:{right[1]}:{right[2]}",
                        ),
                        min(left[1], right[1]),
                        max(left[2], right[2]),
                        action,
                        classification.value,
                        tuple(sorted({*left[3], *right[3]})),
                        issue,
                    )
                )
        return tuple(conflicts), tuple(repairs)

    def _gaps(
        self,
        connection: duckdb.DuckDBPyConnection,
        census: Sequence[dict[str, Any]],
    ) -> tuple[IntervalGapRecord, ...]:
        flagged = {
            row[0]
            for row in connection.execute(
                """SELECT identity_key FROM security_identity_interval_complete
                   WHERE issue_codes LIKE '%IDENTITY_INTERVAL_GAP%'"""
            ).fetchall()
        }
        by_key: dict[str, list[tuple[str, date, date]]] = defaultdict(list)
        for row in census:
            if row["identity_key"] in flagged:
                by_key[str(row["identity_key"])].append(
                    (str(row["symbol"]), row["first_observed"], row["last_observed"])
                )
        events = _transition_events(connection)
        records: list[IntervalGapRecord] = []
        for key in sorted(flagged):
            pair = _largest_gap(by_key.get(key, []))
            if pair is None:
                base = min((item[1] for item in by_key.get(key, [])), default=date.min)
                pair = (
                    ("UNKNOWN", base, base),
                    ("UNKNOWN", base + timedelta(days=2), base + timedelta(days=2)),
                )
            left, right = pair
            start = left[2] + timedelta(days=1)
            end = right[1] - timedelta(days=1)
            classification = _classify_gap(key, left, right, events)
            action = (
                RepairAction.NO_CHANGE
                if classification
                in {
                    GapClassification.LEGITIMATE_INTERVAL_GAP,
                    GapClassification.SUSPENSION,
                }
                else RepairAction.RETAINED_CONFLICTING
            )
            records.append(
                IntervalGapRecord(
                    stable_record_id("gap", key, start, end),
                    key,
                    "identity",
                    left[0],
                    right[0],
                    start,
                    end,
                    max((end - start).days + 1, 1),
                    classification,
                    action,
                    tuple(item[0] for item in events.get(key, ())),
                    (
                        ("UNRESOLVED_INTERVAL_GAP",)
                        if classification is GapClassification.UNRESOLVED
                        else ()
                    ),
                )
            )
        return tuple(records)

    def _persist_sidecar(
        self,
        report: SecurityPopulationRepairReport,
        path: Path,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(path)) as connection:
            _create_sidecar_tables(connection)
            for table in _SIDECAR_TABLES:
                connection.execute(f"DELETE FROM {table}")  # noqa: S608
            _persist_report(connection, report)


def classify_instrument(
    *,
    symbol: str,
    series: str,
    isin: str | None,
    security_name: str | None,
    security_type_flag: str | None,
    official_instrument_type: str | None,
) -> tuple[InstrumentType, str, str]:
    """Classify with official master fields ahead of series heuristics."""

    symbol = symbol.upper()
    series = series.upper()
    name = (security_name or "").upper()
    official = (official_instrument_type or "").upper()
    if "TEST" in symbol or "TEST" in name or (isin or "").startswith("DUMMY"):
        return (
            InstrumentType.TEST_OR_ADMINISTRATIVE_RECORD,
            "official record is marked as test or administrative",
            "HIGH",
        )
    if (
        symbol.endswith("-RE")
        or "RIGHT ENTITLEMENT" in name
        or "RIGHTS ENTITLEMENT" in name
    ):
        return InstrumentType.RIGHTS_ENTITLEMENT, "rights-entitlement naming", "HIGH"
    if security_type_flag == "1":
        return InstrumentType.PREFERENCE_SHARE, "official security type flag 1", "HIGH"
    if security_type_flag == "2":
        if "SECURITISED" in name or "SECURITIZED" in name:
            return (
                InstrumentType.SECURITISED_DEBT,
                "official debt flag and name",
                "HIGH",
            )
        if "MUNICIPAL" in name:
            return InstrumentType.MUNICIPAL_DEBT, "official debt flag and name", "HIGH"
        return InstrumentType.CORPORATE_DEBT, "official security type flag 2", "HIGH"
    if security_type_flag == "3":
        return InstrumentType.WARRANT, "official security type flag 3", "HIGH"
    if security_type_flag == "4":
        if series == "GB" or "SOVEREIGN GOLD" in name:
            return (
                InstrumentType.SOVEREIGN_GOLD_BOND,
                "official flag and series",
                "HIGH",
            )
        if series in _GOVERNMENT_SERIES:
            return (
                InstrumentType.GOVERNMENT_SECURITY,
                "official flag and series",
                "HIGH",
            )
        if series == "MF" and "ETF" not in name:
            return (
                InstrumentType.MUTUAL_FUND_UNIT,
                "official fund flag and series",
                "HIGH",
            )
        if "ETF" in name or (isin or "").startswith("INF"):
            return InstrumentType.ETF, "official fund flag and identity", "HIGH"
        return (
            InstrumentType.INTEREST_RATE_INSTRUMENT,
            "official security type flag 4",
            "MEDIUM",
        )
    if security_type_flag == "0" or "EQUITY" in official:
        if "INVIT" in name or "INFRASTRUCTURE INVESTMENT TRUST" in name:
            return (
                InstrumentType.INVIT,
                "official equity-market master and name",
                "HIGH",
            )
        if "REIT" in name or "REAL ESTATE INVESTMENT TRUST" in name:
            return InstrumentType.REIT, "official equity-market master and name", "HIGH"
        if series in _SME_SERIES:
            kind = (
                InstrumentType.SME_TRADE_FOR_TRADE
                if series == "ST"
                else InstrumentType.SME_EQUITY
            )
            return kind, "official equity flag and SME series", "HIGH"
        if series in _PARTLY_PAID_SERIES:
            return (
                InstrumentType.PARTLY_PAID_EQUITY,
                "official equity flag and series",
                "HIGH",
            )
        if series in {"BE", "BZ"}:
            return (
                InstrumentType.TRADE_FOR_TRADE_EQUITY,
                "official equity flag and series",
                "HIGH",
            )
        if series == "EQ":
            return (
                InstrumentType.MAINBOARD_EQUITY,
                "official equity flag and series",
                "HIGH",
            )
        if series == "RR":
            return InstrumentType.REIT, "official equity-market trust series", "MEDIUM"
        if series in _TEMPORARY_SERIES:
            return (
                InstrumentType.TEMPORARY_OR_AUCTION_SERIES,
                "official equity flag and temporary series",
                "HIGH",
            )
    if series in _CORE_EQUITY_SERIES and isin and isin.startswith("INE"):
        kind = (
            InstrumentType.MAINBOARD_EQUITY
            if series == "EQ"
            else InstrumentType.TRADE_FOR_TRADE_EQUITY
        )
        return kind, "observed equity series without official type field", "MEDIUM"
    if series in _SME_SERIES and isin and isin.startswith("INE"):
        kind = (
            InstrumentType.SME_EQUITY
            if series == "SM"
            else InstrumentType.SME_TRADE_FOR_TRADE
        )
        return kind, "observed SME series without official type field", "MEDIUM"
    if series.startswith(_DEBT_PREFIXES):
        return InstrumentType.CORPORATE_DEBT, "debt-series fallback", "LOW"
    return (
        InstrumentType.UNKNOWN_SECURITY_TYPE,
        "no authoritative classification",
        "LOW",
    )


def _policy(item: InstrumentTaxonomyRecord) -> SupportPolicyRecord:
    core = {
        InstrumentType.MAINBOARD_EQUITY,
        InstrumentType.TRADE_FOR_TRADE_EQUITY,
    }
    non_core = {
        InstrumentType.SME_EQUITY,
        InstrumentType.SME_TRADE_FOR_TRADE,
        InstrumentType.PARTLY_PAID_EQUITY,
        InstrumentType.SUSPENDED_EQUITY,
        InstrumentType.RELISTED_EQUITY,
    }
    separate = {InstrumentType.ETF, InstrumentType.REIT, InstrumentType.INVIT}
    if item.instrument_type in core:
        state = SupportState.TIER_A_CORE_EQUITY
    elif item.instrument_type in non_core:
        state = SupportState.SUPPORTED_EQUITY_NON_CORE
    elif item.instrument_type in separate:
        state = SupportState.SUPPORTED_SEPARATE_ASSET_CLASS
    elif item.instrument_type is InstrumentType.UNKNOWN_SECURITY_TYPE:
        state = SupportState.UNKNOWN_CLASSIFICATION
    else:
        state = SupportState.PRESERVED_UNSUPPORTED
    return SupportPolicyRecord(
        item.identity_key,
        item.symbol,
        item.series,
        item.instrument_type,
        state,
        item.valid_from,
        item.valid_to,
        SUPPORT_POLICY_VERSION,
        f"{item.classification_reason}; mapped by {SUPPORT_POLICY_VERSION}",
        item.confidence,
        item.issue_codes,
    )


def _identity_support_states(
    policy: Sequence[SupportPolicyRecord],
) -> dict[str, SupportState]:
    values: dict[str, set[SupportState]] = defaultdict(set)
    for item in policy:
        values[item.identity_key].add(item.support_state)
    result: dict[str, SupportState] = {}
    for key, states in values.items():
        supported = {
            item
            for item in states
            if item
            in {
                SupportState.TIER_A_CORE_EQUITY,
                SupportState.SUPPORTED_EQUITY_NON_CORE,
                SupportState.SUPPORTED_SEPARATE_ASSET_CLASS,
            }
        }
        if (
            len(supported) > 1
            and SupportState.SUPPORTED_SEPARATE_ASSET_CLASS in supported
        ):
            result[key] = SupportState.CONFLICTING_CLASSIFICATION
        else:
            result[key] = min(states, key=lambda item: _SUPPORT_ORDER[item])
    return result


def _support_intervals(
    identities: Sequence[dict[str, Any]],
    masters: dict[str, list[OfficialMasterRecord]],
    states: dict[str, SupportState],
    start: date,
    end: date,
) -> dict[str, tuple[date, date, str]]:
    result: dict[str, tuple[date, date, str]] = {}
    for identity in identities:
        key = str(identity["identity_key"])
        records = masters.get(key, [])
        current = [
            item for item in records if item.source_id.startswith("nse_current_equity")
        ]
        official_dates = [
            boundary
            for item in records
            if (boundary := item.readmission_date or item.listing_date) is not None
        ]
        official_start = min(official_dates, default=None)
        lower = max(start, official_start or identity["first_evidence_date"] or start)
        removals = [item.removal_date for item in records if item.removal_date]
        if removals:
            upper = min(end, min(removals))
            evidence_state = "OFFICIAL_TERMINATION"
        elif current:
            upper = end
            evidence_state = "ACTIVE_FINAL_CHECKPOINT"
        elif records:
            upper = min(end, max(item.checkpoint_date for item in records))
            evidence_state = "CHECKPOINT_BOUNDED"
        else:
            upper = min(end, identity["last_evidence_date"] or end)
            evidence_state = "PROVISIONAL_OBSERVATION_BOUND"
        if upper < lower:
            upper = lower
            evidence_state = "CONFLICTING_BOUNDARY"
        result[key] = (lower, upper, evidence_state)
    return result


def _boundaries(
    connection: duckdb.DuckDBPyConnection,
    identities: Sequence[dict[str, Any]],
    masters: dict[str, list[OfficialMasterRecord]],
    start: date,
    end: date,
) -> tuple[tuple[BoundaryEvidenceRecord, ...], tuple[BoundaryEvidenceRecord, ...]]:
    listing: list[BoundaryEvidenceRecord] = []
    termination: list[BoundaryEvidenceRecord] = []
    event_terminations: dict[str, tuple[date, str, str]] = {}
    if _table_exists(connection, "security_termination_event_complete"):
        for key, boundary, event_type, source_id in connection.execute(
            """SELECT identity_key, termination_date, event_type, source_id
               FROM security_termination_event_complete
               ORDER BY identity_key, termination_date"""
        ).fetchall():
            event_terminations[key] = (boundary, event_type, source_id)
    for identity in identities:
        key = str(identity["identity_key"])
        records = masters.get(key, [])
        listing_dates = [
            boundary
            for item in records
            if (boundary := item.readmission_date or item.listing_date) is not None
        ]
        if listing_dates:
            master = min(records, key=lambda item: item.checkpoint_date)
            listing.append(
                BoundaryEvidenceRecord(
                    key,
                    "LISTING_OR_ADMISSION",
                    min(listing_dates),
                    BoundaryState.OFFICIAL_EXACT,
                    master.source_id,
                    master.source_path,
                    "HIGH",
                    (),
                )
            )
        else:
            listing.append(
                BoundaryEvidenceRecord(
                    key,
                    "LISTING_OR_ADMISSION",
                    identity["first_evidence_date"],
                    BoundaryState.FIRST_CANDLE_OBSERVATION,
                    None,
                    None,
                    "LOW",
                    ("FIRST_CANDLE_NOT_LISTING_PROOF",),
                )
            )
        removals = [item for item in records if item.removal_date]
        current = [
            item for item in records if item.source_id.startswith("nse_current_equity")
        ]
        if key in event_terminations:
            boundary, event_type, source_id = event_terminations[key]
            termination.append(
                BoundaryEvidenceRecord(
                    key,
                    event_type,
                    boundary,
                    BoundaryState.OFFICIAL_EXACT,
                    source_id,
                    None,
                    "HIGH",
                    (),
                )
            )
        elif removals:
            master = min(removals, key=lambda item: item.removal_date or date.max)
            termination.append(
                BoundaryEvidenceRecord(
                    key,
                    "TERMINATION",
                    master.removal_date,
                    BoundaryState.OFFICIAL_EXACT,
                    master.source_id,
                    master.source_path,
                    "HIGH",
                    (),
                )
            )
        elif current:
            master = max(current, key=lambda item: item.checkpoint_date)
            termination.append(
                BoundaryEvidenceRecord(
                    key,
                    "ACTIVE_STATUS",
                    min(master.checkpoint_date, end),
                    BoundaryState.ACTIVE_FINAL_CHECKPOINT,
                    master.source_id,
                    master.source_path,
                    "HIGH",
                    (),
                )
            )
        else:
            termination.append(
                BoundaryEvidenceRecord(
                    key,
                    "TERMINATION",
                    None,
                    BoundaryState.MISSING_EVIDENCE,
                    None,
                    None,
                    "LOW",
                    ("LAST_CANDLE_NOT_TERMINATION_PROOF",),
                )
            )
    return tuple(listing), tuple(termination)


def _denominators(
    connection: duckdb.DuckDBPyConnection,
    identities: Sequence[dict[str, Any]],
    intervals: dict[str, tuple[date, date, str]],
    states: dict[str, SupportState],
    listing: Sequence[BoundaryEvidenceRecord],
    termination: Sequence[BoundaryEvidenceRecord],
) -> tuple[IdentityDenominatorRecord, ...]:
    candle = {
        row[0]: (row[1], row[2])
        for row in connection.execute(
            """SELECT identity_key, MIN(first_observed), MAX(last_observed)
               FROM complete_security_census GROUP BY identity_key"""
        ).fetchall()
    }
    sessions = tuple(
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT trading_date FROM daily_candle ORDER BY trading_date"
        ).fetchall()
    )
    listing_map = {item.identity_key: item for item in listing}
    termination_map = {item.identity_key: item for item in termination}
    records: list[IdentityDenominatorRecord] = []
    for identity in identities:
        key = str(identity["identity_key"])
        lower, upper, state = intervals[key]
        expected = sum(lower <= session <= upper for session in sessions)
        certified = (
            expected
            if state in {"OFFICIAL_TERMINATION", "ACTIVE_FINAL_CHECKPOINT"}
            and listing_map[key].boundary_state is BoundaryState.OFFICIAL_EXACT
            else 0
        )
        provisional = (
            expected if certified == 0 and state != "CONFLICTING_BOUNDARY" else 0
        )
        unresolved = expected if state == "CONFLICTING_BOUNDARY" else 0
        first_candle, last_candle = candle.get(key, (None, None))
        termination_record = termination_map[key]
        records.append(
            IdentityDenominatorRecord(
                key,
                states[key],
                lower,
                (
                    listing_map[key].boundary_date
                    if listing_map[key].boundary_state is BoundaryState.OFFICIAL_EXACT
                    else None
                ),
                identity["first_evidence_date"],
                first_candle,
                (
                    termination_record.boundary_date
                    if termination_record.boundary_type == "TERMINATION"
                    and termination_record.boundary_state
                    is BoundaryState.OFFICIAL_EXACT
                    else None
                ),
                (
                    termination_record.boundary_date
                    if termination_record.boundary_state
                    is BoundaryState.ACTIVE_FINAL_CHECKPOINT
                    else None
                ),
                last_candle,
                (
                    True
                    if termination_record.boundary_state
                    is BoundaryState.ACTIVE_FINAL_CHECKPOINT
                    else False
                    if termination_record.boundary_state is BoundaryState.OFFICIAL_EXACT
                    else None
                ),
                state,
                expected,
                certified,
                provisional,
                unresolved,
                tuple(
                    sorted(
                        {*listing_map[key].issue_codes, *termination_record.issue_codes}
                    )
                ),
            )
        )
    return tuple(records)


def _checkpoints(
    masters: Sequence[OfficialMasterRecord],
    intervals: dict[str, tuple[date, date, str]],
    states: dict[str, SupportState],
) -> tuple[CheckpointReconciliationRecord, ...]:
    by_checkpoint: dict[date, list[OfficialMasterRecord]] = defaultdict(list)
    for item in masters:
        by_checkpoint[item.checkpoint_date].append(item)
    records: list[CheckpointReconciliationRecord] = []
    for checkpoint, rows in sorted(by_checkpoint.items()):
        for state in SupportState:
            master_keys = {
                item.identity_key
                for item in rows
                if states.get(item.identity_key) is state
            }
            reconstructed = {
                key
                for key, interval in intervals.items()
                if states.get(key) is state and interval[0] <= checkpoint <= interval[1]
            }
            records.append(
                CheckpointReconciliationRecord(
                    checkpoint,
                    state,
                    len(master_keys),
                    len(reconstructed),
                    len(master_keys),
                    len(master_keys - reconstructed),
                    len(reconstructed - master_keys),
                    0,
                    0,
                    0,
                    0,
                    f"official-master:{checkpoint.isoformat()}",
                )
            )
    return tuple(records)


def _universe(
    end: date,
    intervals: dict[str, tuple[date, date, str]],
    states: dict[str, SupportState],
    masters: Sequence[OfficialMasterRecord],
) -> tuple[UniverseReconciliationRecord, ...]:
    symbols: dict[str, set[str]] = defaultdict(set)
    official: dict[SupportState, set[str]] = defaultdict(set)
    for item in masters:
        if item.checkpoint_date >= end and states.get(item.identity_key):
            official[states[item.identity_key]].add(item.identity_key)
            symbols[item.identity_key].add(item.symbol)
    records: list[UniverseReconciliationRecord] = []
    for state in SupportState:
        active = {
            key
            for key, interval in intervals.items()
            if states.get(key) is state and interval[0] <= end <= interval[1]
        }
        provisional = sum(intervals[key][2].startswith("PROVISIONAL") for key in active)
        unresolved = sum(intervals[key][2] == "CONFLICTING_BOUNDARY" for key in active)
        records.append(
            UniverseReconciliationRecord(
                end,
                state,
                len(active),
                sum(max(len(symbols.get(key, ())), 1) for key in active),
                0,
                len(official[state]),
                provisional,
                unresolved,
                "Active only where an official final checkpoint or bounded "
                "interval supports the date.",
            )
        )
    return tuple(records)


def _candle_reconciliation(
    connection: duckdb.DuckDBPyConnection,
    states: dict[str, SupportState],
    intervals: dict[str, tuple[date, date, str]],
) -> tuple[TierCandleReconciliationRecord, ...]:
    rows = connection.execute(
        """SELECT identity_key, SUM(candle_rows), MIN(first_observed),
                  MAX(last_observed)
           FROM complete_security_census GROUP BY identity_key"""
    ).fetchall()
    grouped: dict[tuple[SupportState, str], list[tuple[int, date, date]]] = defaultdict(
        list
    )
    for key, count, first, last in rows:
        state = states.get(key, SupportState.UNKNOWN_CLASSIFICATION)
        lower, upper, interval_state = intervals[key]
        if first < lower:
            reconciliation = "PRE_LISTING_OR_LOWER_BOUND"
        elif last > upper:
            reconciliation = "POST_TERMINATION_OR_CHECKPOINT"
        elif interval_state == "CONFLICTING_BOUNDARY":
            reconciliation = "INTERVAL_CONFLICT"
        elif interval_state.startswith("PROVISIONAL"):
            reconciliation = "PROVISIONAL_IN_INTERVAL"
        else:
            reconciliation = "CERTIFIED_IN_INTERVAL"
        grouped[state, reconciliation].append((int(count), first, last))
    return tuple(
        TierCandleReconciliationRecord(
            state,
            reconciliation,
            sum(item[0] for item in values),
            len(values),
            min(item[1] for item in values),
            max(item[2] for item in values),
        )
        for (state, reconciliation), values in sorted(
            grouped.items(), key=lambda item: (item[0][0].value, item[0][1])
        )
    )


def _continuity(
    connection: duckdb.DuckDBPyConnection,
    candles: Sequence[TierCandleReconciliationRecord],
    denominator: Sequence[IdentityDenominatorRecord],
) -> tuple[TierContinuityRecord, ...]:
    del connection
    expected = Counter(item.support_state for item in denominator)
    expected_days: Counter[SupportState] = Counter()
    provisional_days: Counter[SupportState] = Counter()
    for item in denominator:
        expected_days[item.support_state] += item.expected_identity_days
        provisional_days[item.support_state] += item.provisional_identity_days
    observed: Counter[SupportState] = Counter()
    for candle_item in candles:
        observed[candle_item.support_state] += candle_item.row_count
    records: list[TierContinuityRecord] = []
    for state in SupportState:
        missing = max(expected_days[state] - observed[state], 0)
        explained = min(missing, provisional_days[state])
        unexplained = missing - explained
        records.append(
            TierContinuityRecord(
                state,
                expected_days[state],
                observed[state],
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                explained,
                unexplained,
                expected[state] if unexplained else 0,
            )
        )
    return tuple(records)


def _certifications(
    identities: Sequence[dict[str, Any]],
    taxonomy: Sequence[InstrumentTaxonomyRecord],
    states: dict[str, SupportState],
    intervals: dict[str, tuple[date, date, str]],
    overlaps: Sequence[IntervalConflictRecord],
    gaps: Sequence[IntervalGapRecord],
    listing: Sequence[BoundaryEvidenceRecord],
    termination: Sequence[BoundaryEvidenceRecord],
    suspension: Sequence[SuspensionEvidenceRecord],
) -> tuple[SupportedSecurityCertification, ...]:
    type_by_key: dict[str, InstrumentType] = {}
    for item in taxonomy:
        type_by_key.setdefault(item.identity_key, item.instrument_type)
    overlap_count = Counter(item.identity_key for item in overlaps)
    gap_count = Counter(item.identity_key for item in gaps)
    listing_map = {item.identity_key: item for item in listing}
    termination_map = {item.identity_key: item for item in termination}
    suspension_complete = _historical_suspension_complete(suspension)
    records: list[SupportedSecurityCertification] = []
    for identity in identities:
        key = str(identity["identity_key"])
        state = states[key]
        blockers: list[str] = []
        if overlap_count[key]:
            blockers.append("INTERVAL_OVERLAP")
        if gap_count[key]:
            blockers.append("INTERVAL_GAP")
        if listing_map[key].boundary_state is not BoundaryState.OFFICIAL_EXACT:
            blockers.append("LISTING_BOUNDARY_PARTIAL")
        if termination_map[key].boundary_state not in {
            BoundaryState.OFFICIAL_EXACT,
            BoundaryState.ACTIVE_FINAL_CHECKPOINT,
        }:
            blockers.append("TERMINATION_OR_ACTIVE_BOUNDARY_PARTIAL")
        if state is SupportState.PRESERVED_UNSUPPORTED:
            certification = CertificationState.PRESERVED_UNSUPPORTED
        elif state in {
            SupportState.UNKNOWN_CLASSIFICATION,
            SupportState.CONFLICTING_CLASSIFICATION,
        }:
            certification = (
                CertificationState.UNRESOLVED
                if state is SupportState.UNKNOWN_CLASSIFICATION
                else CertificationState.CONFLICTING
            )
        elif overlap_count[key]:
            certification = CertificationState.IDENTITY_CERTIFIED_INTERVAL_CONFLICT
        elif blockers:
            certification = (
                CertificationState.TIER_A_MEMBERSHIP_PARTIAL
                if state is SupportState.TIER_A_CORE_EQUITY
                else CertificationState.IDENTITY_PARTIAL
            )
        elif not suspension_complete:
            certification = (
                CertificationState.TIER_A_TRADABILITY_PARTIAL
                if state is SupportState.TIER_A_CORE_EQUITY
                else CertificationState.IDENTITY_PARTIAL
            )
        else:
            certification = (
                CertificationState.TIER_A_CERTIFIED
                if state is SupportState.TIER_A_CORE_EQUITY
                else CertificationState.IDENTITY_PARTIAL
            )
        records.append(
            SupportedSecurityCertification(
                key,
                state,
                type_by_key[key],
                listing_map[key].boundary_state.value,
                termination_map[key].boundary_state.value,
                "EFFECTIVE_DATED",
                "EFFECTIVE_DATED",
                intervals[key][2],
                "PARTIAL_HISTORICAL_SUSPENSION_EVIDENCE"
                if not suspension_complete
                else "CURRENT_EVIDENCE_ACQUIRED",
                overlap_count[key],
                gap_count[key],
                certification,
                tuple(blockers),
            )
        )
    return tuple(records)


def _census_reconciliation(
    census: Sequence[dict[str, Any]],
    taxonomy: Sequence[InstrumentTaxonomyRecord],
    policy: Sequence[SupportPolicyRecord],
) -> tuple[CensusReconciliationRecord, ...]:
    dimensions: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0] * 6)
    for row, tax, support in zip(census, taxonomy, policy, strict=True):
        for dimension, value in (
            (
                "source_family",
                "canonical" if row["candle_rows"] else "official_master_only",
            ),
            ("instrument_type", tax.instrument_type.value),
            ("series", tax.series),
            ("year_first_observed", str(row["first_observed"].year)),
            ("year_last_observed", str(row["last_observed"].year)),
            ("candle_presence", "PRESENT" if row["candle_rows"] else "ABSENT"),
            ("support_state", support.support_state.value),
        ):
            bucket = dimensions[dimension, value]
            bucket[0] += int(row["source_record_count"])
            bucket[1] += 1
            bucket[2] += 1
            bucket[3] += int(row["candle_rows"])
            bucket[4] += int(not row["candle_rows"])
            bucket[5] += max(int(row["source_record_count"]) - 1, 0)
    return tuple(
        CensusReconciliationRecord(dimension, value, *counts)
        for (dimension, value), counts in sorted(dimensions.items())
    )


def _population_summary(
    census: Sequence[dict[str, Any]],
    identities: Sequence[dict[str, Any]],
    states: dict[str, SupportState],
    master_keys: set[str],
) -> PopulationRepairSummary:
    counts = Counter(states.values())
    candle_keys = {str(row["identity_key"]) for row in census if row["candle_rows"]}
    all_keys = set(states)
    return PopulationRepairSummary(
        6334,
        15428,
        len(identities),
        len(census) - len(identities),
        counts[SupportState.TIER_A_CORE_EQUITY],
        counts[SupportState.SUPPORTED_EQUITY_NON_CORE],
        counts[SupportState.SUPPORTED_SEPARATE_ASSET_CLASS],
        counts[SupportState.PRESERVED_UNSUPPORTED],
        counts[SupportState.UNKNOWN_CLASSIFICATION],
        counts[SupportState.CONFLICTING_CLASSIFICATION],
        len((master_keys & all_keys) - candle_keys),
        len(candle_keys - master_keys),
    )


def _repair_summary(
    overlaps: Sequence[IntervalConflictRecord],
    gaps: Sequence[IntervalGapRecord],
    symbol_reuse: Sequence[dict[str, Any]],
) -> RepairSummary:
    return RepairSummary(
        len(overlaps),
        sum(item.repair_action is RepairAction.MERGED for item in overlaps),
        sum(item.repair_action is RepairAction.RETAINED_PARALLEL for item in overlaps),
        sum(
            item.repair_action is RepairAction.RETAINED_CONFLICTING for item in overlaps
        ),
        len(gaps),
        sum(
            item.repair_action is not RepairAction.RETAINED_CONFLICTING for item in gaps
        ),
        sum(item.repair_action is RepairAction.RETAINED_CONFLICTING for item in gaps),
        sum(
            str(item.get("resolution_state", "")).upper() == "RESOLVED"
            for item in symbol_reuse
        ),
        sum(
            str(item.get("resolution_state", "")).upper() != "RESOLVED"
            for item in symbol_reuse
        ),
    )


def _denominator_summary(
    records: Sequence[IdentityDenominatorRecord],
) -> tuple[DenominatorSummary, ...]:
    grouped: dict[SupportState, list[IdentityDenominatorRecord]] = defaultdict(list)
    for item in records:
        grouped[item.support_state].append(item)
    return tuple(
        DenominatorSummary(
            state,
            len(values),
            sum(item.expected_identity_days for item in values),
            sum(item.certified_identity_days for item in values),
            sum(item.provisional_identity_days for item in values),
            sum(item.unresolved_identity_days for item in values),
        )
        for state, values in sorted(grouped.items(), key=lambda item: item[0].value)
    )


def _suspension_evidence(
    evidence: Sequence[SourceEvidence],
) -> tuple[SuspensionEvidenceRecord, ...]:
    return tuple(
        SuspensionEvidenceRecord(
            None,
            None,
            None,
            None,
            item.evidence_type,
            item.source_id,
            item.source_url,
            item.source_path or None,
            item.source_sha256 or None,
            item.status,
            item.failure_code,
            item.failure_detail,
        )
        for item in evidence
        if item.evidence_type == "SUSPENSION_AND_RESTORATION"
    )


def _blockers(
    certifications: Sequence[SupportedSecurityCertification],
    gaps: Sequence[IntervalGapRecord],
    overlaps: Sequence[IntervalConflictRecord],
    suspension: Sequence[SuspensionEvidenceRecord],
) -> tuple[str, ...]:
    blockers: list[str] = []
    if any(
        item.repair_action is RepairAction.RETAINED_CONFLICTING for item in overlaps
    ):
        blockers.append("UNRESOLVED_SUPPORTED_INTERVAL_OVERLAPS")
    if any(item.classification is GapClassification.UNRESOLVED for item in gaps):
        blockers.append("UNRESOLVED_IDENTITY_INTERVAL_GAPS")
    if not _historical_suspension_complete(suspension):
        blockers.append("HISTORICAL_SUSPENSION_INTERVALS_UNAVAILABLE")
    if any(
        item.certification_state is CertificationState.CONFLICTING
        for item in certifications
    ):
        blockers.append("CONFLICTING_INSTRUMENT_CLASSIFICATIONS")
    return tuple(blockers)


def _interval_map(
    connection: duckdb.DuckDBPyConnection,
    table: str,
) -> dict[str, tuple[tuple[str, date, date, tuple[str, ...], tuple[str, ...]], ...]]:
    result: dict[
        str, list[tuple[str, date, date, tuple[str, ...], tuple[str, ...]]]
    ] = defaultdict(list)
    rows = connection.execute(
        f"SELECT identity_key, value, valid_from, valid_to, source_event_ids, issue_codes FROM {table} ORDER BY identity_key, valid_from, valid_to, value"  # noqa: S608,E501
    ).fetchall()
    for key, value, lower, upper, source_ids, issue_codes in rows:
        result[key].append(
            (value, lower, upper, _json_tuple(source_ids), _json_tuple(issue_codes))
        )
    return {key: tuple(values) for key, values in result.items()}


def _first_overlap(
    intervals: Sequence[tuple[str, date, date, tuple[str, ...], tuple[str, ...]]],
) -> tuple[
    tuple[str, date, date, tuple[str, ...], tuple[str, ...]] | None,
    tuple[str, date, date, tuple[str, ...], tuple[str, ...]] | None,
]:
    for index, left in enumerate(intervals):
        for right in intervals[index + 1 :]:
            if max(left[1], right[1]) <= min(left[2], right[2]):
                return left, right
    return None, None


def _classify_overlap(
    key: str,
    left: tuple[str, date, date, tuple[str, ...], tuple[str, ...]],
    right: tuple[str, date, date, tuple[str, ...], tuple[str, ...]],
    state: SupportState,
) -> tuple[OverlapClassification, RepairAction]:
    if key.startswith("nse:synthetic:"):
        return (
            OverlapClassification.SYNTHETIC_IDENTITY_COLLISION,
            RepairAction.RETAINED_CONFLICTING,
        )
    if left[:3] == right[:3]:
        return (
            OverlapClassification.DUPLICATE_RECONSTRUCTED_INTERVAL,
            RepairAction.MERGED,
        )
    if left[0] == right[0]:
        return OverlapClassification.DUPLICATE_EVIDENCE, RepairAction.MERGED
    values = {left[0], right[0]}
    if values <= _CORE_EQUITY_SERIES | _SME_SERIES | _TEMPORARY_SERIES:
        if values & _TEMPORARY_SERIES:
            return (
                OverlapClassification.LEGITIMATE_PARALLEL_SERIES,
                RepairAction.RETAINED_PARALLEL,
            )
        return (
            OverlapClassification.SERIES_OVERLAP_SAME_IDENTITY,
            RepairAction.RETAINED_PARALLEL,
        )
    if state is SupportState.PRESERVED_UNSUPPORTED:
        return (
            OverlapClassification.CURRENT_MASTER_BACKFILL_ERROR,
            RepairAction.EXCLUDED_FROM_SUPPORTED_DENOMINATOR,
        )
    return OverlapClassification.UNRESOLVED, RepairAction.RETAINED_CONFLICTING


def _largest_gap(
    values: Sequence[tuple[str, date, date]],
) -> tuple[tuple[str, date, date], tuple[str, date, date]] | None:
    ordered = sorted(values, key=lambda item: (item[1], item[2], item[0]))
    candidates = [
        (left, right)
        for left, right in zip(ordered, ordered[1:])
        if right[1] > left[2] + timedelta(days=1)
    ]
    return (
        max(candidates, key=lambda pair: (pair[1][1] - pair[0][2]).days)
        if candidates
        else None
    )


def _transition_events(
    connection: duckdb.DuckDBPyConnection,
) -> dict[str, tuple[tuple[str, str, date], ...]]:
    result: dict[str, list[tuple[str, str, date]]] = defaultdict(list)
    if not _table_exists(connection, "security_event"):
        return {}
    for (
        event_id,
        event_type,
        effective_date,
        predecessor,
        successor,
    ) in connection.execute(
        """SELECT event_id, event_type, effective_date,
                  predecessor_identity, successor_identity
           FROM security_event WHERE admission_state = 'ADMITTED'"""
    ).fetchall():
        for key in (predecessor, successor):
            if key:
                result[key].append((event_id, event_type, effective_date))
    return {key: tuple(sorted(values)) for key, values in result.items()}


def _classify_gap(
    key: str,
    left: tuple[str, date, date],
    right: tuple[str, date, date],
    events: dict[str, tuple[tuple[str, str, date], ...]],
) -> GapClassification:
    relevant = tuple(
        item for item in events.get(key, ()) if left[2] <= item[2] <= right[1]
    )
    if any(item[1] == "SYMBOL_CHANGED" for item in relevant):
        return GapClassification.SYMBOL_TRANSITION
    if any(item[1] == "DELISTED" for item in relevant):
        return GapClassification.TEMPORARY_CESSATION
    return GapClassification.UNRESOLVED


def _fetch_dicts(
    connection: duckdb.DuckDBPyConnection,
    query: str,
) -> tuple[dict[str, Any], ...]:
    cursor = connection.execute(query)
    columns = [item[0] for item in cursor.description]
    return tuple(dict(zip(columns, row, strict=True)) for row in cursor.fetchall())


def _load_json_records(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.exists():
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("records", [])
    return tuple(payload) if isinstance(payload, list) else ()


def _text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _json_tuple(value: object) -> tuple[str, ...]:
    try:
        payload = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return ()
    return tuple(str(item) for item in payload)


def _table_exists(connection: duckdb.DuckDBPyConnection, table: str) -> bool:
    row = connection.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
        [table],
    ).fetchone()
    return bool(row and row[0])


def _evidence_available(item: SuspensionEvidenceRecord) -> bool:
    return bool(
        item.status in {"ACQUIRED", "REUSED"}
        and item.source_path
        and item.source_sha256
    )


def _historical_suspension_complete(
    evidence: Sequence[SuspensionEvidenceRecord],
) -> bool:
    return any(
        _evidence_available(item) and item.identity_key and item.suspension_date
        for item in evidence
    )


_SIDECAR_TABLES = (
    "security_instrument_taxonomy",
    "security_support_policy",
    "security_support_interval",
    "identity_interval_conflict",
    "identity_interval_repair",
    "identity_boundary_evidence",
    "security_checkpoint_reconciliation_repair",
    "supported_security_certification",
    "supported_security_session_gap",
    "security_population_repair_run",
)


def _create_sidecar_tables(connection: duckdb.DuckDBPyConnection) -> None:
    for table in _SIDECAR_TABLES[:-1]:
        connection.execute(f"CREATE TABLE IF NOT EXISTS {table}(payload JSON)")  # noqa: S608
    connection.execute(
        """CREATE TABLE IF NOT EXISTS security_population_repair_run(
               contract_version VARCHAR, report_sha256 VARCHAR, report_json JSON)"""
    )


def _persist_report(
    connection: duckdb.DuckDBPyConnection,
    report: SecurityPopulationRepairReport,
) -> None:
    mappings: tuple[tuple[str, Iterable[Any]], ...] = (
        ("security_instrument_taxonomy", report.taxonomy),
        ("security_support_policy", report.support_policy),
        ("security_support_interval", report.denominator_audit),
        ("identity_interval_conflict", report.interval_overlaps),
        ("identity_interval_repair", report.interval_repairs),
        (
            "identity_boundary_evidence",
            (*report.listing_boundaries, *report.termination_boundaries),
        ),
        ("security_checkpoint_reconciliation_repair", report.checkpoint_reconciliation),
        ("supported_security_certification", report.certification_matrix),
        ("supported_security_session_gap", report.continuity),
    )
    for table, values in mappings:
        rows = [
            (json.dumps(_object_payload(value), sort_keys=True),) for value in values
        ]
        if rows:
            connection.executemany(f"INSERT INTO {table} VALUES (?)", rows)  # noqa: S608
    connection.execute(
        "INSERT INTO security_population_repair_run VALUES (?, ?, ?)",
        [
            report.contract_version,
            report.report_sha256,
            json.dumps(report.payload(), sort_keys=True),
        ],
    )


def _object_payload(value: Any) -> dict[str, Any]:
    from dataclasses import asdict

    raw = asdict(value)
    for key, item in tuple(raw.items()):
        if isinstance(item, date):
            raw[key] = item.isoformat()
        elif hasattr(item, "value"):
            raw[key] = item.value
        elif isinstance(item, tuple):
            raw[key] = list(item)
    return raw


__all__ = ["SecurityPopulationRepairEngine", "classify_instrument"]
