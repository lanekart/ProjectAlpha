"""Candidate-independent HTR-010A2 lifecycle/session certification."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

import duckdb

from alpha.historical_truth.lifecycle_session_models import (
    HTR010A2_CONTRACT_VERSION,
    LIFECYCLE_VERSION,
    PRODUCTION_INFLUENCE,
    AbsenceReason,
    BoundaryRange,
    CanonicalLifecycleInterval,
    CanonicalObservation,
    CertificationIssue,
    CertificationReconciliation,
    CheckpointDifference,
    DailySourceSemantics,
    DuplicateClassification,
    DuplicateSourceRecord,
    GapFinalState,
    IntervalType,
    LifecycleRepair,
    LifecycleRepairType,
    LifecycleSessionReport,
    MissingSessionReclassification,
    OverlapFinalState,
    PrimaryCertification,
    PrimaryCertificationState,
    ReadinessDecision,
    ReadinessState,
    RemainingGap,
    RemainingOverlap,
    SessionExpectationSummary,
    SourceSemanticsState,
    stable_id,
)
from alpha.historical_truth.security_population_repair_sources import (
    SecurityPopulationSourceInventory,
    SourceEvidence,
    verify_source_checksums,
)


class LifecycleSessionSemanticsEngine:
    """Build an immutable diagnostic sidecar from HTR-010A/010A1 evidence."""

    def __init__(self, database_path: Path, root: Path) -> None:
        self.database_path = database_path
        self.root = root
        self.sources = SecurityPopulationSourceInventory(root)

    def run(
        self,
        *,
        htr010a_output: Path,
        htr010a1_output: Path,
        start_date: date,
        end_date: date,
        output: Path,
        refresh_sources: bool,
        verify_only: bool,
    ) -> LifecycleSessionReport:
        if refresh_sources and verify_only:
            raise ValueError("refresh_sources and verify_only are mutually exclusive")
        _, evidence = self.sources.collect(refresh_sources=refresh_sources)
        verify_source_checksums(evidence)
        census = _records(htr010a_output / "htr010a_security_census.json")
        taxonomy = _records(htr010a1_output / "htr010a1_instrument_taxonomy.json")
        certifications = _records(
            htr010a1_output / "htr010a1_certification_matrix.json"
        )
        denominators = _records(
            htr010a1_output / "htr010a1_identity_denominator_audit.json"
        )
        overlaps = _records(htr010a1_output / "htr010a1_interval_overlaps.json")
        gaps = _records(htr010a1_output / "htr010a1_interval_gaps.json")
        listings = _records(htr010a1_output / "htr010a1_listing_boundaries.json")
        terminations = _records(
            htr010a1_output / "htr010a1_termination_boundaries.json"
        )
        continuity = _records(
            htr010a1_output / "htr010a1_security_session_continuity.json"
        )
        symbols = _records(htr010a_output / "htr010a_symbol_intervals.json")
        series = _records(htr010a_output / "htr010a_series_intervals.json")

        taxonomy_by_id = {str(row["identity_key"]): row for row in taxonomy}
        cert_by_id = {str(row["identity_key"]): row for row in certifications}
        canonical, duplicates = canonicalize_observations(census)
        remaining_overlaps = classify_remaining_overlaps(overlaps, cert_by_id)
        remaining_gaps = classify_remaining_gaps(gaps, cert_by_id)
        primary = certify_identities(
            taxonomy_by_id,
            cert_by_id,
            remaining_overlaps,
            remaining_gaps,
        )
        reconciliation = reconcile_certifications(primary)
        lifecycle, repairs = canonicalize_lifecycle(
            symbols,
            series,
            denominators,
            canonical,
            overlaps,
        )
        boundaries = boundary_ranges(
            denominators,
            listings,
            terminations,
            taxonomy_by_id,
        )
        semantics = daily_source_semantics(self.database_path, start_date, end_date)
        expectations, missing = session_expectations(continuity)
        checkpoint = checkpoint_differences(canonical, denominators, taxonomy_by_id)
        source_inventory = tuple(_source_payload(item) for item in evidence)
        suspension_events: tuple[dict[str, Any], ...] = ()
        rejected = tuple(
            {
                "source_id": item.source_id,
                "failure_code": item.failure_code,
                "failure_detail": item.failure_detail,
            }
            for item in evidence
            if item.failure_code
        )
        fingerprint = _candle_fingerprint(self.database_path)
        readiness = readiness_decision(primary, semantics, checkpoint)
        checksums = tuple(
            sorted(
                (item.source_path, item.source_sha256)
                for item in evidence
                if item.source_path and item.source_sha256
            )
        )
        report = LifecycleSessionReport(
            HTR010A2_CONTRACT_VERSION,
            LIFECYCLE_VERSION,
            PRODUCTION_INFLUENCE,
            "htr010a2_lifecycle.duckdb",
            start_date,
            end_date,
            primary,
            reconciliation,
            duplicates,
            canonical,
            lifecycle,
            repairs,
            remaining_overlaps,
            remaining_gaps,
            boundaries,
            source_inventory,
            suspension_events,
            semantics,
            expectations,
            missing,
            checkpoint,
            readiness,
            rejected,
            checksums,
            fingerprint,
            "",
        )
        report = replace(report, report_sha256=report.calculated_sha256())
        self._persist(report, output / "htr010a2_lifecycle.duckdb")
        return report

    def _persist(self, report: LifecycleSessionReport, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect(str(path))
        try:
            tables = {
                "canonical_security_observation": report.canonical_observations,
                "security_observation_duplicate_group": report.duplicate_source_records,
                "canonical_identity_lifecycle_interval": report.lifecycle_intervals,
                "identity_lifecycle_repair": report.interval_repairs,
                "identity_boundary_range": report.boundary_ranges,
                "security_primary_certification": report.primary_certifications,
                "daily_source_semantics": report.daily_source_semantics,
                "security_session_expectation": report.session_expectations,
                "security_session_absence_classification": (
                    report.missing_session_reclassification
                ),
            }
            for name, rows in tables.items():
                connection.execute(f"DROP TABLE IF EXISTS {name}")
                payload = [json.dumps(_jsonable(row), sort_keys=True) for row in rows]
                connection.execute(f"CREATE TABLE {name}(payload JSON NOT NULL)")
                connection.executemany(
                    f"INSERT INTO {name} VALUES (?)", [(row,) for row in payload]
                )
            connection.execute("DROP TABLE IF EXISTS htr010b_readiness")
            connection.execute("CREATE TABLE htr010b_readiness(payload JSON NOT NULL)")
            connection.execute(
                "INSERT INTO htr010b_readiness VALUES (?)",
                [json.dumps(_jsonable(report.readiness), sort_keys=True)],
            )
        finally:
            connection.close()


def canonicalize_observations(
    census: list[dict[str, Any]],
) -> tuple[tuple[CanonicalObservation, ...], tuple[DuplicateSourceRecord, ...]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in census:
        grouped[str(row["identity_key"])].append(row)
    canonical: list[CanonicalObservation] = []
    duplicates: list[DuplicateSourceRecord] = []
    for identity, rows in sorted(grouped.items()):
        ordered = sorted(rows, key=_observation_rank)
        selected = ordered[0]
        group_id = stable_id("duplicate-group", identity)
        record_ids = tuple(
            _source_record_id(row, occurrence) for occurrence, row in enumerate(ordered)
        )
        canonical_id = stable_id(
            "canonical-observation",
            identity,
            selected.get("symbol"),
            selected.get("series"),
            selected.get("first_observed"),
        )
        canonical.append(
            CanonicalObservation(
                canonical_id,
                group_id,
                identity,
                str(selected.get("symbol") or ""),
                str(selected.get("series") or ""),
                _optional(selected.get("isin")),
                _optional(selected.get("security_name")),
                _date(selected.get("first_observed"), date.min),
                _date(selected.get("last_observed"), date.max),
                1,
                "CONFLICTING" if _facts_conflict(ordered) else "CONSISTENT",
                record_ids,
                _fact(selected),
            )
        )
        for occurrence, row in enumerate(ordered[1:], start=1):
            classification, reason = _duplicate_classification(selected, row)
            duplicates.append(
                DuplicateSourceRecord(
                    _source_record_id(row, occurrence),
                    canonical_id,
                    group_id,
                    identity,
                    str(row.get("symbol") or ""),
                    str(row.get("series") or ""),
                    classification,
                    _date(row.get("first_observed"), date.min),
                    tuple(sorted(str(item) for item in row.get("source_ids", []))),
                    "CONFLICTING" if _fact(row) != _fact(selected) else "CONSISTENT",
                    reason,
                )
            )
    return tuple(canonical), tuple(duplicates)


def _duplicate_classification(
    selected: dict[str, Any], row: dict[str, Any]
) -> tuple[DuplicateClassification, str]:
    if _fact(selected) == _fact(row):
        if selected.get("first_observed") == row.get("first_observed"):
            return (
                DuplicateClassification.IDENTICAL_DUPLICATE_OBSERVATION,
                "same identity fact and effective observation date",
            )
        return (
            DuplicateClassification.REPEATED_CHECKPOINT_OBSERVATION,
            "same identity fact observed at another checkpoint",
        )
    selected_sources = set(selected.get("source_ids", []))
    row_sources = set(row.get("source_ids", []))
    if selected_sources != row_sources and _same_security_fact(selected, row):
        return (
            DuplicateClassification.MULTIPLE_OFFICIAL_SOURCES_SAME_FACT,
            "independent source families corroborate the identity",
        )
    if _date(row.get("first_observed"), date.min) > _date(
        selected.get("last_observed"), date.max
    ):
        return (
            DuplicateClassification.LEGITIMATE_EFFECTIVE_DATED_OBSERVATION,
            "different fact occurs after the selected observation interval",
        )
    if str(row.get("identity_key", "")).startswith("nse:synthetic:"):
        return (
            DuplicateClassification.SYNTHETIC_DUPLICATION,
            "synthetic identity contains overlapping source facts",
        )
    return (
        DuplicateClassification.CONFLICTING_OFFICIAL_OBSERVATION,
        "overlapping identity facts differ and are retained",
    )


def certify_identities(
    taxonomy: dict[str, dict[str, Any]],
    certifications: dict[str, dict[str, Any]],
    overlaps: tuple[RemainingOverlap, ...],
    gaps: tuple[RemainingGap, ...],
) -> tuple[PrimaryCertification, ...]:
    overlap_ids = {row.identity_key for row in overlaps}
    gap_ids = {row.identity_key for row in gaps}
    rows: list[PrimaryCertification] = []
    for identity, tax in sorted(taxonomy.items()):
        old = certifications[identity]
        support = str(old["support_state"])
        issues: list[CertificationIssue] = []
        if identity in overlap_ids:
            issues.append(CertificationIssue.INTERVAL_OVERLAP)
        if identity in gap_ids:
            issues.append(CertificationIssue.INTERVAL_GAP)
        if old.get("listing_coverage") != "OFFICIAL_EXACT":
            issues.append(CertificationIssue.PROVISIONAL_LISTING_BOUNDARY)
        if old.get("termination_or_active_coverage") == "MISSING_EVIDENCE":
            issues.append(CertificationIssue.MISSING_TERMINATION_EVIDENCE)
        if old.get("tradability_coverage") != "COMPLETE":
            issues.append(CertificationIssue.MISSING_SUSPENSION_EVIDENCE)
        state = _primary_state(support, old, identity in overlap_ids)
        rows.append(
            PrimaryCertification(
                identity,
                support,
                str(tax.get("instrument_type") or "UNKNOWN"),
                state,
                tuple(sorted(set(issues), key=str)),
                "Primary state is exclusive; evidence limitations remain issue flags.",
            )
        )
    return tuple(rows)


def _primary_state(
    support: str, old: dict[str, Any], has_overlap: bool
) -> PrimaryCertificationState:
    if support == "TIER_A_CORE_EQUITY":
        if has_overlap:
            return PrimaryCertificationState.TIER_A_INTERVAL_CONFLICT
        if old.get("membership_coverage") == "PROVISIONAL_OBSERVATION_BOUND":
            return PrimaryCertificationState.TIER_A_MEMBERSHIP_PARTIAL
        if old.get("tradability_coverage") != "COMPLETE":
            return PrimaryCertificationState(
                "TIER_A_MEMBERSHIP_CERTIFIED_TRADABILITY_PARTIAL"
            )
        return PrimaryCertificationState.TIER_A_LIFECYCLE_CERTIFIED
    if support == "SUPPORTED_EQUITY_NON_CORE":
        if old.get("certification_state") == "CERTIFIED" and not has_overlap:
            return PrimaryCertificationState.SUPPORTED_NON_CORE_CERTIFIED
        return PrimaryCertificationState.SUPPORTED_NON_CORE_PARTIAL
    if support == "SUPPORTED_SEPARATE_ASSET_CLASS":
        return PrimaryCertificationState.SEPARATE_ASSET_CLASS
    if support == "PRESERVED_UNSUPPORTED":
        return PrimaryCertificationState.PRESERVED_UNSUPPORTED
    if support == "CONFLICTING_CLASSIFICATION":
        return PrimaryCertificationState.CONFLICTING_CLASSIFICATION
    if support == "UNKNOWN_CLASSIFICATION":
        return PrimaryCertificationState.UNKNOWN_CLASSIFICATION
    return PrimaryCertificationState.UNRESOLVED_IDENTITY


def reconcile_certifications(
    rows: tuple[PrimaryCertification, ...],
) -> tuple[CertificationReconciliation, ...]:
    counts = Counter(row.primary_state for row in rows)
    result = [
        CertificationReconciliation(
            "FULL_CENSUS",
            state,
            counts[state],
            len(rows),
            f"sum(primary_state)={len(rows)}",
        )
        for state in PrimaryCertificationState
        if counts[state]
    ]
    tier = [row for row in rows if row.support_state == "TIER_A_CORE_EQUITY"]
    tier_counts = Counter(row.primary_state for row in tier)
    result.extend(
        CertificationReconciliation(
            "TIER_A_CORE_EQUITY",
            state,
            tier_counts[state],
            len(tier),
            f"sum(Tier A primary_state)={len(tier)}",
        )
        for state in PrimaryCertificationState
        if tier_counts[state]
    )
    return tuple(result)


def classify_remaining_overlaps(
    rows: list[dict[str, Any]], certifications: dict[str, dict[str, Any]]
) -> tuple[RemainingOverlap, ...]:
    result = []
    for row in rows:
        if row.get("classification") != "UNRESOLVED":
            continue
        identity = str(row["identity_key"])
        result.append(
            RemainingOverlap(
                str(row["conflict_id"]),
                identity,
                str(certifications.get(identity, {}).get("support_state", "UNKNOWN")),
                identity.startswith("nse:isin:"),
                True,
                row.get("left_value") == row.get("right_value"),
                True,
                (),
                tuple(
                    sorted(
                        {
                            *row.get("left_source_event_ids", []),
                            *row.get("right_source_event_ids", []),
                        }
                    )
                ),
                OverlapFinalState.UNRESOLVED_INSUFFICIENT_EVIDENCE,
                True,
                "No effective-dated official event safely resolves this overlap.",
            )
        )
    return tuple(result)


def classify_remaining_gaps(
    rows: list[dict[str, Any]], certifications: dict[str, dict[str, Any]]
) -> tuple[RemainingGap, ...]:
    result = []
    for row in rows:
        if row.get("classification") != "UNRESOLVED":
            continue
        start = _date(row.get("gap_start"), date.min)
        end = _date(row.get("gap_end"), date.max)
        identity = str(row["identity_key"])
        result.append(
            RemainingGap(
                str(row["gap_id"]),
                identity,
                str(certifications.get(identity, {}).get("support_state", "UNKNOWN")),
                None,
                None,
                start,
                end,
                start == end,
                GapFinalState.UNRESOLVED,
                tuple(sorted(row.get("evidence_source_ids", []))),
                "Bounded gap retained; candle continuity is not lifecycle evidence.",
            )
        )
    return tuple(result)


def canonicalize_lifecycle(
    symbols: list[dict[str, Any]],
    series: list[dict[str, Any]],
    denominators: list[dict[str, Any]],
    observations: tuple[CanonicalObservation, ...],
    overlap_evidence: list[dict[str, Any]] | None = None,
) -> tuple[tuple[CanonicalLifecycleInterval, ...], tuple[LifecycleRepair, ...]]:
    backfills = _backfill_keys(overlap_evidence or [])
    candidates: list[
        tuple[str, IntervalType, str, date, date, tuple[str, ...], str]
    ] = []
    repairs: list[LifecycleRepair] = []
    for interval_type, rows in (
        (IntervalType.SYMBOL, symbols),
        (IntervalType.SERIES, series),
    ):
        for row in rows:
            identity = str(row["identity_key"])
            value = str(row["value"])
            backfill_key = (identity, interval_type, value)
            if backfill_key in backfills and not row.get("source_event_ids"):
                repairs.append(
                    LifecycleRepair(
                        stable_id("repair-backfill", identity, interval_type, value),
                        identity,
                        interval_type,
                        (value,),
                        "",
                        LifecycleRepairType.REMOVED_CHECKPOINT_BACKFILL,
                        "Current-master fact had no effective-dated event and was "
                        "excluded from canonical history.",
                        (),
                    )
                )
                continue
            candidates.append(
                (
                    identity,
                    interval_type,
                    value,
                    _date(row.get("valid_from"), date.min),
                    _date(row.get("valid_to"), date.max),
                    tuple(sorted(row.get("source_event_ids", []))),
                    str(row.get("confidence_state", "UNKNOWN")),
                )
            )
    obs = {row.identity_key: row for row in observations}
    for row in denominators:
        identity = str(row["identity_key"])
        start = _date(row.get("earliest_possible_membership"), date.min)
        end = _date(
            row.get("termination_date")
            or row.get("last_official_active_checkpoint")
            or row.get("last_canonical_candle"),
            date.max,
        )
        state = str(row.get("interval_state", "UNKNOWN"))
        for kind, value in (
            (IntervalType.IDENTITY_VALIDITY, "VALID"),
            (IntervalType.MARKET_MEMBERSHIP, state),
            (IntervalType.TRADABILITY, "PARTIAL_SUSPENSION_EVIDENCE"),
        ):
            candidates.append((identity, kind, value, start, end, (), "MEDIUM"))
        observation = obs.get(identity)
        if observation and observation.isin:
            candidates.append(
                (
                    identity,
                    IntervalType.ISIN,
                    observation.isin,
                    start,
                    end,
                    observation.supporting_record_ids,
                    "HIGH",
                )
            )
    grouped: dict[tuple[str, IntervalType, str, date, date], list[tuple[str, ...]]] = (
        defaultdict(list)
    )
    confidence: dict[tuple[str, IntervalType, str, date, date], str] = {}
    for identity, kind, value, start, end, source_ids, conf in candidates:
        interval_key = (identity, kind, value, start, end)
        grouped[interval_key].append(source_ids)
        confidence[interval_key] = conf
    intervals = []
    for interval_key, sources in sorted(grouped.items(), key=lambda item: str(item[0])):
        identity, kind, value, start, end = interval_key
        evidence = tuple(sorted({item for group in sources for item in group}))
        collapsed = len(sources) > 1
        repair_type = (
            LifecycleRepairType.COLLAPSED_IDENTICAL
            if collapsed
            else LifecycleRepairType.UNCHANGED
        )
        interval_id = stable_id("lifecycle", identity, kind, value, start, end)
        intervals.append(
            CanonicalLifecycleInterval(
                interval_id,
                identity,
                kind,
                value,
                start,
                end,
                tuple(
                    stable_id("original", identity, kind, value, start, end, i)
                    for i in range(len(sources))
                ),
                repair_type,
                "identical intervals collapsed"
                if collapsed
                else "source interval retained",
                evidence,
                confidence[interval_key],
                LIFECYCLE_VERSION,
                False,
            )
        )
        if collapsed:
            repairs.append(
                LifecycleRepair(
                    stable_id("repair", interval_id),
                    identity,
                    kind,
                    tuple(value for _ in sources),
                    value,
                    repair_type,
                    "Duplicate interval facts collapsed without deleting lineage.",
                    evidence,
                )
            )
    return tuple(intervals), tuple(repairs)


def _backfill_keys(
    overlaps: list[dict[str, Any]],
) -> set[tuple[str, IntervalType, str]]:
    result: set[tuple[str, IntervalType, str]] = set()
    for row in overlaps:
        if row.get("classification") != "CURRENT_MASTER_BACKFILL_ERROR":
            continue
        kind = (
            IntervalType.SERIES
            if row.get("attribute") == "series"
            else IntervalType.SYMBOL
        )
        identity = str(row["identity_key"])
        result.add((identity, kind, str(row.get("left_value") or "")))
        result.add((identity, kind, str(row.get("right_value") or "")))
    return result


def boundary_ranges(
    denominators: list[dict[str, Any]],
    listings: list[dict[str, Any]],
    terminations: list[dict[str, Any]],
    taxonomy: dict[str, dict[str, Any]],
) -> tuple[BoundaryRange, ...]:
    listing_by_id = {str(row["identity_key"]): row for row in listings}
    termination_by_id = {str(row["identity_key"]): row for row in terminations}
    result = []
    for row in denominators:
        identity = str(row["identity_key"])
        listing = listing_by_id.get(identity, {})
        termination = termination_by_id.get(identity, {})
        current = row.get("currently_active")
        exact_listing = (
            _optional_date(listing.get("boundary_date"))
            if listing.get("boundary_state") == "OFFICIAL_EXACT"
            else None
        )
        exact_termination = (
            _optional_date(termination.get("boundary_date"))
            if termination.get("boundary_state") == "OFFICIAL_EXACT"
            else None
        )
        result.append(
            BoundaryRange(
                identity,
                str(
                    taxonomy.get(identity, {}).get("support_state")
                    or row["support_state"]
                ),
                exact_listing,
                _optional_date(row.get("earliest_possible_membership")),
                _optional_date(row.get("official_listing_date")),
                _optional_date(row.get("earliest_official_observation")),
                _optional_date(row.get("first_canonical_candle")),
                exact_termination,
                exact_termination,
                _optional_date(row.get("termination_date")),
                _optional_date(row.get("last_official_active_checkpoint")),
                _optional_date(row.get("last_canonical_candle")),
                current,
                str(listing.get("confidence", "LOW")),
                current is not True and exact_termination is None,
            )
        )
    return tuple(result)


def daily_source_semantics(
    database_path: Path, start_date: date, end_date: date
) -> tuple[DailySourceSemantics, ...]:
    with duckdb.connect(str(database_path), read_only=True) as connection:
        rows = connection.execute(
            "SELECT COUNT(*), SUM(CASE WHEN volume=0 THEN 1 ELSE 0 END) "
            "FROM daily_candle WHERE trading_date BETWEEN ? AND ?",
            [start_date, end_date],
        ).fetchone()
    total = int(rows[0] or 0) if rows else 0
    zero = int(rows[1] or 0) if rows else 0
    return (
        DailySourceSemantics(
            "NSE_CM_LEGACY_BHAVCOPY",
            "legacy CM bhavcopy",
            start_date,
            date(2024, 7, 5),
            SourceSemanticsState.REPORTABLE_ACTIVITY_ONLY,
            zero,
            total,
            "UNRESOLVED; no complete historical suspended-security control set",
            "SCHEMA_AND_EMPIRICAL_EVIDENCE_ONLY",
            "MEDIUM",
            ("TOTTRDQTY field", "canonical warehouse has zero zero-volume rows"),
        ),
        DailySourceSemantics(
            "NSE_CM_UDIFF_BHAVCOPY",
            "NSE UDiFF common bhavcopy",
            date(2024, 7, 8),
            end_date,
            SourceSemanticsState.REPORTABLE_ACTIVITY_ONLY,
            zero,
            total,
            "UNRESOLVED; current workbook cannot certify historical behavior",
            "SCHEMA_AND_EMPIRICAL_EVIDENCE_ONLY",
            "MEDIUM",
            ("TtlTradgVol field", "no zero-volume canonical rows observed"),
        ),
        DailySourceSemantics(
            "NSE_CM_SPECIAL_SESSION_BHAVCOPY",
            "special-session CM bhavcopy",
            date(2016, 10, 30),
            date(2023, 11, 12),
            SourceSemanticsState.REPORTABLE_ACTIVITY_ONLY,
            0,
            0,
            "UNRESOLVED",
            "EMPIRICAL_SPECIAL_SESSION_EVIDENCE",
            "MEDIUM",
            ("official special-session source lineage",),
        ),
    )


def session_expectations(
    continuity: list[dict[str, Any]],
) -> tuple[
    tuple[SessionExpectationSummary, ...], tuple[MissingSessionReclassification, ...]
]:
    summaries = []
    missing = []
    for row in continuity:
        expected = int(row.get("expected_sessions", 0))
        observed = int(row.get("observed_sessions", 0))
        unexplained = int(row.get("unexplained_missing", 0))
        support = str(row["support_state"])
        summaries.append(
            SessionExpectationSummary(
                support,
                expected,
                expected,
                observed,
                observed,
                observed,
                observed,
                "MEDIUM; membership is broader than activity-row expectation",
            )
        )
        if unexplained:
            missing.append(
                MissingSessionReclassification(
                    support,
                    AbsenceReason.ROW_NOT_EXPECTED_SOURCE_SEMANTICS,
                    unexplained,
                    False,
                    False,
                    "MEDIUM",
                    "Activity-row source contract does not guarantee a row "
                    "for every member-session.",
                )
            )
    return tuple(summaries), tuple(missing)


def checkpoint_differences(
    observations: tuple[CanonicalObservation, ...],
    denominators: list[dict[str, Any]],
    taxonomy: dict[str, dict[str, Any]],
) -> tuple[CheckpointDifference, ...]:
    obs = {row.identity_key: row for row in observations}
    result = []
    for row in denominators:
        if (
            row.get("support_state") != "TIER_A_CORE_EQUITY"
            or row.get("interval_state") != "PROVISIONAL_OBSERVATION_BOUND"
            or row.get("currently_active") is not None
        ):
            continue
        observation = obs.get(str(row["identity_key"]))
        if not observation:
            continue
        result.append(
            CheckpointDifference(
                observation.identity_key,
                observation.symbol,
                observation.series,
                observation.isin,
                "DERIVED_ACTIVE_PROVISIONAL",
                "ABSENT_FROM_FINAL_OFFICIAL_CHECKPOINT",
                observation.supporting_record_ids,
                "UNRESOLVED",
                False,
            )
        )
    return tuple(result[:5])


def readiness_decision(
    primary: tuple[PrimaryCertification, ...],
    semantics: tuple[DailySourceSemantics, ...],
    checkpoint: tuple[CheckpointDifference, ...],
) -> ReadinessDecision:
    ambiguous = sum(
        row.primary_state is PrimaryCertificationState.TIER_A_INTERVAL_CONFLICT
        for row in primary
    )
    blockers = []
    if ambiguous:
        blockers.append(f"{ambiguous} Tier A identities retain interval conflicts")
    if any(row.confidence != "HIGH" for row in semantics):
        blockers.append(
            "daily-source row semantics lack complete official documentation"
        )
    if checkpoint:
        blockers.append(
            f"{len(checkpoint)} final-checkpoint differences remain unresolved"
        )
    blockers.append(
        "complete historical suspension/restoration evidence is unavailable"
    )
    return ReadinessDecision(
        ReadinessState.NOT_READY_FOR_HTR_010B,
        tuple(blockers),
        (
            "primary certification reconciles to the census",
            "membership and source-row expectations are separate",
            "canonical candle fingerprint is unchanged",
        ),
        "Acquire effective-dated official lifecycle and suspension evidence "
        "before HTR-010B.",
        "Fail-closed readiness does not infer lifecycle truth from candle continuity.",
    )


def _observation_rank(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        not bool(row.get("isin")),
        -int(row.get("source_record_count", 0)),
        -int(row.get("candle_rows", 0)),
        str(row.get("first_observed") or "9999-12-31"),
        str(row.get("symbol") or ""),
        str(row.get("series") or ""),
    )


def _facts_conflict(rows: list[dict[str, Any]]) -> bool:
    return len({_fact(row) for row in rows}) > 1


def _same_security_fact(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (left.get("isin"), left.get("symbol"), left.get("series")) == (
        right.get("isin"),
        right.get("symbol"),
        right.get("series"),
    )


def _fact(row: dict[str, Any]) -> str:
    return "|".join(
        str(row.get(key) or "")
        for key in ("exchange", "isin", "symbol", "series", "security_name")
    )


def _source_record_id(row: dict[str, Any], occurrence: int = 0) -> str:
    return stable_id(
        "source-record",
        row.get("identity_key"),
        row.get("symbol"),
        row.get("series"),
        row.get("first_observed"),
        row.get("last_observed"),
        ",".join(sorted(row.get("source_ids", []))),
        occurrence,
    )


def _source_payload(item: SourceEvidence) -> dict[str, Any]:
    return {
        "source_id": item.source_id,
        "source_path": item.source_path,
        "source_sha256": item.source_sha256,
        "source_url": item.source_url,
        "status": item.status,
        "evidence_type": item.evidence_type,
        "failure_code": item.failure_code,
        "failure_detail": item.failure_detail,
        "evidence_ceiling": (
            "Current suspension evidence cannot certify complete historical intervals"
            if "susp" in (item.evidence_type + item.source_id).lower()
            else "Source-specific"
        ),
    }


def _candle_fingerprint(path: Path) -> str:
    with duckdb.connect(str(path), read_only=True) as connection:
        row = connection.execute(
            "SELECT COUNT(*), MIN(trading_date), MAX(trading_date), "
            "SUM(volume), COUNT(DISTINCT source_sha256) FROM daily_candle"
        ).fetchone()
    if row is None:
        raise RuntimeError("canonical candle fingerprint query returned no row")
    return sha256("|".join(str(item) for item in row).encode()).hexdigest()


def _records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("records", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError(f"expected record list: {path}")
    return rows


def _date(value: Any, default: date) -> date:
    return date.fromisoformat(str(value)) if value else default


def _optional_date(value: Any) -> date | None:
    return date.fromisoformat(str(value)) if value else None


def _optional(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _jsonable(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _jsonable(getattr(value, key)) for key in value.__dataclass_fields__
        }
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


__all__ = [
    "LifecycleSessionSemanticsEngine",
    "canonicalize_lifecycle",
    "canonicalize_observations",
    "certify_identities",
    "classify_remaining_gaps",
    "classify_remaining_overlaps",
    "daily_source_semantics",
    "reconcile_certifications",
    "session_expectations",
]
