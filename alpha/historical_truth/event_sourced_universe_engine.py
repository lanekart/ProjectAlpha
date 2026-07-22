"""HTR-009A2 event-sourced point-in-time universe reconstruction."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import duckdb

from alpha.historical_truth.event_sourced_universe_models import (
    HTR009A2_CONTRACT_VERSION,
    PRODUCTION_INFLUENCE,
    CandleIntervalConflictRecord,
    CheckpointReconciliationRecord,
    DelistingAssessment,
    EventAdmissionState,
    EventCandidateExposureRecord,
    EventCertificationSummary,
    EventConfidenceState,
    EventIdentitySummary,
    EventMembershipSummary,
    EventRejectionRecord,
    EventSourcedCertificationState,
    EventSourcedUniverseReport,
    EventSourceStatus,
    EventSummary,
    IdentityRelationshipRecord,
    IdentityRelationshipType,
    MembershipCertificationState,
    MembershipEffect,
    MembershipIntervalRecord,
    NameIntervalRecord,
    SecurityEventRecord,
    SecurityEventType,
    SeriesIntervalRecord,
    SuspensionAssessment,
    SymbolChangeAssessment,
    SymbolIntervalRecord,
    SymbolReuseAssessment,
    TradabilityEffect,
    TradabilityIntervalRecord,
    YtdEvidenceSummary,
)
from alpha.historical_truth.event_sourced_universe_sources import (
    OfficialSecurityEventStore,
    default_event_source_specs,
)

_DEFAULT_BASELINE = Path("artifacts/htr009a_point_in_time_universe")


@dataclass(frozen=True, slots=True)
class ReconstructedIntervals:
    membership: tuple[MembershipIntervalRecord, ...]
    tradability: tuple[TradabilityIntervalRecord, ...]
    symbols: tuple[SymbolIntervalRecord, ...]
    series: tuple[SeriesIntervalRecord, ...]
    names: tuple[NameIntervalRecord, ...]
    relationships: tuple[IdentityRelationshipRecord, ...]
    suspensions: tuple[SuspensionAssessment, ...]
    delistings: tuple[DelistingAssessment, ...]


class EventSourcedIntervalReconstructor:
    """Build identity intervals only from admitted official event evidence."""

    def reconstruct(
        self,
        events: Sequence[SecurityEventRecord],
        sessions: Sequence[date],
        *,
        checkpoint_identities: frozenset[str] = frozenset(),
    ) -> ReconstructedIntervals:
        if not sessions:
            return ReconstructedIntervals((), (), (), (), (), (), (), ())
        ordered_sessions = tuple(sorted(set(sessions)))
        start, end = ordered_sessions[0], ordered_sessions[-1]
        by_identity: dict[str, list[SecurityEventRecord]] = defaultdict(list)
        for event in events:
            if event.admission_state is not EventAdmissionState.ADMITTED:
                continue
            event_series = event.new_series or event.old_series
            if event_series is not None and event_series != "EQ":
                continue
            keys = tuple(
                dict.fromkeys(
                    key
                    for key in (
                        event.predecessor_identity,
                        event.successor_identity,
                        event.identity_key,
                    )
                    if key is not None
                )
            )
            for key in keys:
                by_identity[key].append(event)
        membership: list[MembershipIntervalRecord] = []
        tradability: list[TradabilityIntervalRecord] = []
        symbols: list[SymbolIntervalRecord] = []
        series: list[SeriesIntervalRecord] = []
        names: list[NameIntervalRecord] = []
        relationships: list[IdentityRelationshipRecord] = []
        suspensions: list[SuspensionAssessment] = []
        delistings: list[DelistingAssessment] = []
        for key, identity_events in sorted(by_identity.items()):
            stream = tuple(
                sorted(
                    identity_events,
                    key=lambda item: (item.effective_date, item.event_id),
                )
            )
            membership.extend(
                self._membership_intervals(
                    key,
                    stream,
                    ordered_sessions,
                    checkpoint_identities,
                )
            )
            identity_membership = tuple(
                item for item in membership if item.identity_key == key
            )
            tradability.extend(
                self._tradability_intervals(
                    key,
                    stream,
                    ordered_sessions,
                    identity_membership,
                )
            )
            symbols.extend(
                cast(
                    tuple[SymbolIntervalRecord, ...],
                    self._attribute_intervals(key, stream, start, end, "symbol"),
                )
            )
            series.extend(
                cast(
                    tuple[SeriesIntervalRecord, ...],
                    self._attribute_intervals(key, stream, start, end, "series"),
                )
            )
            names.extend(self._name_intervals(key, stream, start, end))
            suspensions.extend(self._suspension_assessments(key, stream))
            delistings.extend(self._delisting_assessments(key, stream))
        for event in events:
            if (
                event.predecessor_identity
                and event.successor_identity
                and event.predecessor_identity != event.successor_identity
                and event.admission_state is EventAdmissionState.ADMITTED
            ):
                relationship_type = _relationship_type(event.event_type)
                relationship_id = (
                    "relationship:"
                    + sha256(
                        (
                            f"{event.predecessor_identity}|{event.successor_identity}|"
                            f"{event.event_type.value}|{event.effective_date}"
                        ).encode()
                    ).hexdigest()
                )
                relationships.append(
                    IdentityRelationshipRecord(
                        relationship_id,
                        event.predecessor_identity,
                        event.successor_identity,
                        relationship_type,
                        event.effective_date,
                        event.event_id,
                        event.confidence_state,
                    )
                )
        return ReconstructedIntervals(
            tuple(sorted(membership, key=_interval_key)),
            tuple(sorted(tradability, key=_interval_key)),
            tuple(sorted(symbols, key=_interval_key)),
            tuple(sorted(series, key=_interval_key)),
            tuple(sorted(names, key=_interval_key)),
            tuple(sorted(relationships, key=lambda item: item.relationship_id)),
            tuple(
                sorted(
                    suspensions,
                    key=lambda item: (item.identity_key, item.suspended_from),
                )
            ),
            tuple(
                sorted(
                    delistings,
                    key=lambda item: (item.identity_key, item.effective_date),
                )
            ),
        )

    @staticmethod
    def _membership_intervals(
        key: str,
        stream: Sequence[SecurityEventRecord],
        sessions: Sequence[date],
        checkpoint_identities: frozenset[str],
    ) -> tuple[MembershipIntervalRecord, ...]:
        records: list[MembershipIntervalRecord] = []
        active_from: date | None = None
        source_ids: list[str] = []
        for event in stream:
            if event.membership_effect is MembershipEffect.OPEN:
                if active_from is None:
                    active_from = event.effective_date
                    source_ids = [event.event_id]
                else:
                    source_ids.append(event.event_id)
                continue
            if event.membership_effect is not MembershipEffect.CLOSE:
                if active_from is not None:
                    source_ids.append(event.event_id)
                continue
            if active_from is None:
                continue
            start = _session_on_or_after(sessions, active_from)
            end = _session_before(sessions, event.effective_date)
            if start is not None and end is not None and end >= start:
                records.append(
                    MembershipIntervalRecord(
                        key,
                        start,
                        end,
                        MembershipCertificationState.CERTIFIED_ACTIVE_TRADABLE,
                        tuple((*source_ids, event.event_id)),
                        _session_count(sessions, start, end),
                    )
                )
            active_from = None
            source_ids = []
        if active_from is not None:
            start = _session_on_or_after(sessions, active_from)
            if start is not None:
                corroborated = key in checkpoint_identities
                state = (
                    MembershipCertificationState.CERTIFIED_ACTIVE_TRADABLE
                    if corroborated
                    else MembershipCertificationState.UNRESOLVED_NO_TERMINATION_EVIDENCE
                )
                issues = (
                    () if corroborated else ("MISSING_TERMINATION_OR_LATER_CHECKPOINT",)
                )
                records.append(
                    MembershipIntervalRecord(
                        key,
                        start,
                        sessions[-1],
                        state,
                        tuple(source_ids),
                        _session_count(sessions, start, sessions[-1]),
                        issues,
                    )
                )
        return tuple(records)

    @staticmethod
    def _tradability_intervals(
        key: str,
        stream: Sequence[SecurityEventRecord],
        sessions: Sequence[date],
        membership: Sequence[MembershipIntervalRecord],
    ) -> tuple[TradabilityIntervalRecord, ...]:
        if not membership:
            return ()
        result: list[TradabilityIntervalRecord] = []
        for active in membership:
            cursor = active.valid_from
            tradable = (
                active.state is MembershipCertificationState.CERTIFIED_ACTIVE_TRADABLE
            )
            source_ids = list(active.source_event_ids)
            relevant = tuple(
                event
                for event in stream
                if active.valid_from <= event.effective_date <= active.valid_to
                and event.tradability_effect
                in {TradabilityEffect.OPEN, TradabilityEffect.CLOSE}
                and event.membership_effect is MembershipEffect.UNCHANGED
            )
            for event in relevant:
                boundary = _session_on_or_after(sessions, event.effective_date)
                if boundary is None or boundary < cursor:
                    continue
                previous = _session_before(sessions, boundary)
                if previous is not None and previous >= cursor:
                    result.append(
                        _tradability_record(
                            key,
                            cursor,
                            previous,
                            tradable,
                            tuple(source_ids),
                            sessions,
                            active.state,
                        )
                    )
                tradable = event.tradability_effect is TradabilityEffect.OPEN
                source_ids.append(event.event_id)
                cursor = boundary
            if cursor <= active.valid_to:
                result.append(
                    _tradability_record(
                        key,
                        cursor,
                        active.valid_to,
                        tradable,
                        tuple(source_ids),
                        sessions,
                        active.state,
                    )
                )
        return tuple(result)

    @staticmethod
    def _attribute_intervals(
        key: str,
        stream: Sequence[SecurityEventRecord],
        start: date,
        end: date,
        attribute: str,
    ) -> tuple[SymbolIntervalRecord, ...] | tuple[SeriesIntervalRecord, ...]:
        changes: list[tuple[date, str, str]] = []
        for event in stream:
            value = (
                event.new_symbol or event.old_symbol
                if attribute == "symbol"
                else event.new_series or event.old_series
            )
            if value:
                changes.append((event.effective_date, value, event.event_id))
        deduplicated: list[tuple[date, str, str]] = []
        for item in sorted(changes):
            if deduplicated and deduplicated[-1][1] == item[1]:
                continue
            deduplicated.append(item)
        records: list[SymbolIntervalRecord | SeriesIntervalRecord] = []
        for index, (effective, value, event_id) in enumerate(deduplicated):
            valid_from = max(start, effective)
            valid_to = (
                min(end, deduplicated[index + 1][0] - timedelta(days=1))
                if index + 1 < len(deduplicated)
                else end
            )
            if valid_to < valid_from:
                continue
            if attribute == "symbol":
                records.append(
                    SymbolIntervalRecord(
                        key,
                        value,
                        valid_from,
                        valid_to,
                        (event_id,),
                        EventConfidenceState.HIGH,
                    )
                )
            else:
                records.append(
                    SeriesIntervalRecord(
                        key,
                        value,
                        valid_from,
                        valid_to,
                        (event_id,),
                        EventConfidenceState.HIGH,
                    )
                )
        return tuple(records)  # type: ignore[return-value]

    @staticmethod
    def _name_intervals(
        key: str,
        stream: Sequence[SecurityEventRecord],
        start: date,
        end: date,
    ) -> tuple[NameIntervalRecord, ...]:
        changes = tuple(
            (event.effective_date, event.security_name, event.event_id)
            for event in stream
            if event.security_name
        )
        records: list[NameIntervalRecord] = []
        for index, (effective, name, event_id) in enumerate(changes):
            valid_from = max(start, effective)
            valid_to = (
                min(end, changes[index + 1][0] - timedelta(days=1))
                if index + 1 < len(changes)
                else end
            )
            if name and valid_to >= valid_from:
                records.append(
                    NameIntervalRecord(
                        key,
                        name,
                        valid_from,
                        valid_to,
                        (event_id,),
                        EventConfidenceState.HIGH,
                    )
                )
        return tuple(records)

    @staticmethod
    def _suspension_assessments(
        key: str,
        stream: Sequence[SecurityEventRecord],
    ) -> tuple[SuspensionAssessment, ...]:
        records: list[SuspensionAssessment] = []
        for index, event in enumerate(stream):
            if event.event_type is not SecurityEventType.SUSPENDED:
                continue
            restoration = next(
                (
                    candidate
                    for candidate in stream[index + 1 :]
                    if candidate.event_type is SecurityEventType.SUSPENSION_REVOKED
                ),
                None,
            )
            records.append(
                SuspensionAssessment(
                    key,
                    event.effective_date,
                    restoration.effective_date if restoration else None,
                    (
                        (event.event_id, restoration.event_id)
                        if restoration
                        else (event.event_id,)
                    ),
                    (
                        MembershipCertificationState.CERTIFIED_ACTIVE_TRADABLE
                        if restoration
                        else MembershipCertificationState.UNRESOLVED_SUSPENSION_STATE
                    ),
                )
            )
        return tuple(records)

    @staticmethod
    def _delisting_assessments(
        key: str,
        stream: Sequence[SecurityEventRecord],
    ) -> tuple[DelistingAssessment, ...]:
        return tuple(
            DelistingAssessment(
                key,
                event.effective_date,
                event.event_type,
                event.event_id,
                event.confidence_state,
            )
            for event in stream
            if event.membership_effect is MembershipEffect.CLOSE
        )


class EventSourcedUniverseCertificationEngine:
    """Run HTR-009A2 without changing recommendation or trading policy."""

    def __init__(
        self,
        database_path: Path,
        root: Path,
        *,
        baseline_directory: Path = _DEFAULT_BASELINE,
    ) -> None:
        self.database_path = database_path
        self.root = root
        self.baseline_directory = baseline_directory
        self.source_store = OfficialSecurityEventStore(root)
        self.reconstructor = EventSourcedIntervalReconstructor()

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
        event_types: tuple[SecurityEventType, ...] = (),
        membership_states: tuple[MembershipCertificationState, ...] = (),
        only_unresolved: bool = False,
    ) -> EventSourcedUniverseReport:
        if refresh_sources and verify_only:
            raise ValueError("refresh_sources and verify_only are mutually exclusive")
        sessions, calendar_end = _calendar_sessions(calendar_report, start_date)
        canonical_end = self._canonical_end()
        end_date = min(
            item for item in (calendar_end, canonical_end) if item is not None
        )
        if requested_end is not None:
            end_date = min(end_date, requested_end)
        sessions = tuple(item for item in sessions if item <= end_date)
        if not sessions:
            raise ValueError(
                "no certified official sessions exist in the requested window"
            )
        baseline = self._load_baseline()
        specs = default_event_source_specs(end_date)
        parsed_sources = (
            self.source_store.acquire(specs)
            if refresh_sources
            else self.source_store.verify_or_missing(specs)
        )
        events = self._enrich_events(
            tuple(event for source in parsed_sources for event in source.events),
            baseline,
        )
        events, conflict_rejections = _reject_conflicting_events(events)
        checkpoint_keys = frozenset(
            event.identity_key
            for event in events
            if event.event_type is SecurityEventType.CHECKPOINT_PRESENT
            and event.new_series == "EQ"
            and event.admission_state is EventAdmissionState.ADMITTED
            and event.identity_key is not None
        )
        intervals = self.reconstructor.reconstruct(
            events,
            sessions,
            checkpoint_identities=checkpoint_keys,
        )
        symbol_reuse = self._symbol_reuse(baseline, intervals, events)
        symbol_changes = self._symbol_changes(baseline, events)
        checkpoints = self._checkpoints(events, intervals, sessions)
        candle_conflicts = self._candle_conflicts(intervals, start_date, end_date)
        candidate_exposure = self._candidate_exposure(intervals, baseline)
        rejected = tuple(
            sorted(
                (
                    *(item for source in parsed_sources for item in source.rejected),
                    *conflict_rejections,
                ),
                key=lambda item: (
                    item.source_id,
                    item.failure_code,
                    item.row_number or 0,
                ),
            )
        )
        sources = tuple(source.inventory for source in parsed_sources)
        event_summary = self._event_summary(sources, events, rejected)
        identity_summary = self._identity_summary(
            baseline,
            intervals,
            symbol_reuse,
            symbol_changes,
        )
        membership_summary = self._membership_summary(
            baseline,
            intervals,
            candle_conflicts,
        )
        ytd_summary = self._ytd_summary(events, calendar_end, canonical_end)
        certification = self._certification(
            baseline,
            intervals,
            symbol_reuse,
            symbol_changes,
            checkpoints,
            rejected,
            sources,
            sessions,
        )
        report_baseline = {
            key: value
            for key, value in baseline.items()
            if key
            not in {
                "identities",
                "boundaries",
                "symbol_reuse",
                "symbol_changes",
                "candidate_exposure",
            }
        }
        report = EventSourcedUniverseReport(
            HTR009A2_CONTRACT_VERSION,
            PRODUCTION_INFLUENCE,
            str(self.database_path),
            sessions[0],
            sessions[-1],
            report_baseline,
            sources,
            rejected,
            _filter_events(events, symbols, isins, years, event_types),
            tuple(item for source in parsed_sources for item in source.lineage),
            intervals.relationships,
            _filter_intervals(intervals.symbols, symbols, isins, years),
            _filter_intervals(intervals.series, symbols, isins, years),
            _filter_intervals(intervals.names, symbols, isins, years),
            _filter_membership(
                intervals.membership,
                isins,
                years,
                membership_states,
                only_unresolved,
            ),
            _filter_tradability(
                intervals.tradability,
                isins,
                years,
                membership_states,
                only_unresolved,
            ),
            symbol_reuse,
            symbol_changes,
            intervals.suspensions,
            intervals.delistings,
            checkpoints,
            candle_conflicts,
            candidate_exposure,
            event_summary,
            identity_summary,
            membership_summary,
            ytd_summary,
            certification,
            "",
        )
        report = replace(report, report_sha256=report.calculated_sha256())
        if not verify_only:
            self._persist(report)
        return report

    def _canonical_end(self) -> date | None:
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            row = connection.execute(
                "SELECT MAX(trading_date) FROM daily_candle"
            ).fetchone()
        return row[0] if row and isinstance(row[0], date) else None

    def _load_baseline(self) -> dict[str, Any]:
        required = {
            "certification": "htr009a_certification.json",
            "identities": "htr009a_security_identities.json",
            "boundaries": "htr009a_listing_delisting.json",
            "symbol_reuse": "htr009a_symbol_reuse.json",
            "symbol_changes": "htr009a_symbol_changes.json",
            "candidate_exposure": "htr009a_candidate_exposure.json",
        }
        loaded: dict[str, Any] = {}
        hashes: dict[str, str] = {}
        for key, filename in required.items():
            path = self.baseline_directory / filename
            raw = path.read_bytes()
            loaded[key] = json.loads(raw)
            hashes[filename] = sha256(raw).hexdigest()
        certification = cast(dict[str, Any], loaded["certification"])
        identity_summary = cast(dict[str, Any], certification["identity_summary"])
        membership_summary = cast(dict[str, Any], certification["membership_summary"])
        return {
            "source_directory": str(self.baseline_directory),
            "source_hashes": hashes,
            "prior_certification_state": certification["certification"][
                "primary_state"
            ],
            "governed_identities": identity_summary["governed_identities"],
            "provisional_identities": identity_summary["provisional_identities"],
            "unresolved_identities": identity_summary["unresolved_identities"],
            "certified_identity_days": membership_summary["identity_days_certified"],
            "unresolved_membership_days": membership_summary[
                "unresolved_membership_days"
            ],
            "symbol_reuse_cases": identity_summary["symbol_reuse_conflicts"],
            "symbol_changes_resolved": identity_summary["symbol_changes_resolved"],
            "symbol_changes_unresolved": identity_summary["symbol_changes_unresolved"],
            "listing_dates": sum(
                item["official_listing_date"] is not None
                for item in loaded["boundaries"]["records"]
            ),
            "delisting_dates": sum(
                item["official_delisting_date"] is not None
                for item in loaded["boundaries"]["records"]
            ),
            "suspension_intervals": 0,
            "identities": loaded["identities"]["records"],
            "boundaries": loaded["boundaries"]["records"],
            "symbol_reuse": loaded["symbol_reuse"]["records"],
            "symbol_changes": loaded["symbol_changes"]["records"],
            "candidate_exposure": loaded["candidate_exposure"]["records"],
        }

    @staticmethod
    def _enrich_events(
        events: Sequence[SecurityEventRecord],
        baseline: Mapping[str, Any],
    ) -> tuple[SecurityEventRecord, ...]:
        symbol_keys: dict[str, set[str]] = defaultdict(set)
        for record in baseline["identities"]:
            key = str(record["identity_key"])
            for symbol in record["symbols"]:
                symbol_keys[str(symbol).upper()].add(key)
        enriched: list[SecurityEventRecord] = []
        for event in events:
            if event.identity_key is not None:
                enriched.append(event)
                continue
            old_keys = symbol_keys.get(str(event.old_symbol or "").upper(), set())
            new_keys = symbol_keys.get(str(event.new_symbol or "").upper(), set())
            candidates = (
                old_keys & new_keys if old_keys and new_keys else old_keys | new_keys
            )
            if len(candidates) != 1:
                enriched.append(
                    replace(
                        event,
                        admission_state=EventAdmissionState.PROVISIONAL,
                        confidence_state=EventConfidenceState.LOW,
                    )
                )
                continue
            key = next(iter(candidates))
            isin = key.rsplit(":", 1)[-1] if ":isin:" in key else None
            enriched.append(
                replace(
                    event,
                    old_isin=isin,
                    new_isin=isin,
                    predecessor_identity=key,
                    successor_identity=key,
                )
            )
        return tuple(
            sorted(enriched, key=lambda item: (item.effective_date, item.event_id))
        )

    @staticmethod
    def _symbol_reuse(
        baseline: Mapping[str, Any],
        intervals: ReconstructedIntervals,
        events: Sequence[SecurityEventRecord],
    ) -> tuple[SymbolReuseAssessment, ...]:
        membership_by_key = _group_by_identity(intervals.membership)
        termination_keys = {
            event.predecessor_identity
            for event in events
            if event.membership_effect is MembershipEffect.CLOSE
        }
        listing_keys = {
            event.successor_identity
            for event in events
            if event.membership_effect is MembershipEffect.OPEN
        }
        records: list[SymbolReuseAssessment] = []
        for item in baseline["symbol_reuse"]:
            keys = tuple(f"nse:isin:{isin}" for isin in item["involved_isins"])
            spans = tuple(
                interval for key in keys for interval in membership_by_key.get(key, ())
            )
            overlap = _intervals_overlap(spans)
            terminated = bool(set(keys[:-1]) & termination_keys)
            successor = bool(set(keys[1:]) & listing_keys)
            resolved = (
                len(spans) == len(keys) and not overlap and terminated and successor
            )
            records.append(
                SymbolReuseAssessment(
                    str(item["symbol"]),
                    keys,
                    tuple(str(value) for value in item["involved_isins"]),
                    (),
                    tuple(
                        f"{interval.identity_key}:{interval.valid_from}:{interval.valid_to}"
                        for interval in spans
                    ),
                    overlap,
                    _minimum_interval_gap(spans),
                    terminated,
                    successor,
                    int(item["candle_count"] if not resolved else 0),
                    int(item["candidate_count"] if not resolved else 0),
                    (
                        MembershipCertificationState.CERTIFIED_ACTIVE_TRADABLE
                        if resolved
                        else MembershipCertificationState.SYMBOL_REUSE_CONFLICT
                    ),
                )
            )
        return tuple(sorted(records, key=lambda item: item.symbol))

    @staticmethod
    def _symbol_changes(
        baseline: Mapping[str, Any],
        events: Sequence[SecurityEventRecord],
    ) -> tuple[SymbolChangeAssessment, ...]:
        official: dict[tuple[str, str], list[SecurityEventRecord]] = defaultdict(list)
        for event in events:
            if event.event_type is SecurityEventType.SYMBOL_CHANGED:
                official[(str(event.old_symbol), str(event.new_symbol))].append(event)
        records: list[SymbolChangeAssessment] = []
        for item in baseline["symbol_changes"]:
            key = (str(item["previous_symbol"]), str(item["new_symbol"]))
            evidence = tuple(official.get(key, ()))
            same_identity = str(item["predecessor_identity"]) == str(
                item["successor_identity"]
            )
            resolved = (
                bool(evidence)
                and same_identity
                and all(
                    event.admission_state is EventAdmissionState.ADMITTED
                    for event in evidence
                )
            )
            records.append(
                SymbolChangeAssessment(
                    key[0],
                    key[1],
                    evidence[0].effective_date if evidence else None,
                    str(item["predecessor_identity"]),
                    str(item["successor_identity"]),
                    "CONTINUOUS_IDENTITY" if resolved else "UNRESOLVED",
                    tuple(event.event_id for event in evidence),
                    (
                        MembershipCertificationState.CERTIFIED_ACTIVE_TRADABLE
                        if resolved
                        else MembershipCertificationState.UNRESOLVED_IDENTITY_TRANSITION
                    ),
                )
            )
        return tuple(
            sorted(records, key=lambda item: (item.old_symbol, item.new_symbol))
        )

    @staticmethod
    def _checkpoints(
        events: Sequence[SecurityEventRecord],
        intervals: ReconstructedIntervals,
        sessions: Sequence[date],
    ) -> tuple[CheckpointReconciliationRecord, ...]:
        by_date: dict[date, list[SecurityEventRecord]] = defaultdict(list)
        for event in events:
            if event.event_type is SecurityEventType.CHECKPOINT_PRESENT:
                if (
                    event.new_series != "EQ"
                    or event.admission_state is not EventAdmissionState.ADMITTED
                ):
                    continue
                by_date[event.effective_date].append(event)
        records: list[CheckpointReconciliationRecord] = []
        symbol_by_key = _attribute_at(intervals.symbols)
        series_by_key = _attribute_at(intervals.series)
        for checkpoint_date, checkpoint_events in sorted(by_date.items()):
            master = {
                event.identity_key: event
                for event in checkpoint_events
                if event.identity_key is not None
            }
            derived = {
                interval.identity_key
                for interval in intervals.membership
                if interval.valid_from <= checkpoint_date <= interval.valid_to
            }
            missing = set(master) - derived
            unexpected = derived - set(master)
            symbol_mismatches = sum(
                symbol_by_key.get(key, lambda _: None)(checkpoint_date)
                != event.new_symbol
                for key, event in master.items()
                if key in derived and event.new_symbol
            )
            series_mismatches = sum(
                series_by_key.get(key, lambda _: None)(checkpoint_date)
                != event.new_series
                for key, event in master.items()
                if key in derived and event.new_series
            )
            issues = tuple(
                code
                for condition, code in (
                    (bool(missing), "MISSING_DERIVED_IDENTITIES"),
                    (bool(unexpected), "UNEXPECTED_DERIVED_IDENTITIES"),
                    (symbol_mismatches > 0, "SYMBOL_MISMATCH"),
                    (series_mismatches > 0, "SERIES_MISMATCH"),
                )
                if condition
            )
            records.append(
                CheckpointReconciliationRecord(
                    checkpoint_date,
                    len(derived),
                    len(master),
                    len(missing),
                    len(unexpected),
                    symbol_mismatches,
                    0,
                    series_mismatches,
                    0,
                    issues,
                )
            )
        del sessions
        return tuple(records)

    def _candle_conflicts(
        self,
        intervals: ReconstructedIntervals,
        start_date: date,
        end_date: date,
    ) -> tuple[CandleIntervalConflictRecord, ...]:
        certified = tuple(
            item
            for item in intervals.tradability
            if item.tradable
            and item.state is MembershipCertificationState.CERTIFIED_ACTIVE_TRADABLE
        )
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            connection.execute(
                """
                CREATE TEMP TABLE certified_interval(
                    identity_key VARCHAR,
                    valid_from DATE,
                    valid_to DATE
                )
                """
            )
            if certified:
                connection.executemany(
                    "INSERT INTO certified_interval VALUES (?, ?, ?)",
                    [
                        (item.identity_key, item.valid_from, item.valid_to)
                        for item in certified
                    ],
                )
            rows = connection.execute(
                """
                SELECT MIN(c.trading_date), MAX(c.trading_date), UPPER(c.symbol),
                       UPPER(c.series), c.isin,
                       CASE WHEN c.isin IS NOT NULL
                            THEN 'nse:isin:' || UPPER(TRIM(c.isin))
                            ELSE 'nse:unresolved:' || UPPER(c.symbol) || ':' ||
                                 UPPER(c.series) END AS identity_key,
                       COUNT(*)
                FROM daily_candle c
                LEFT JOIN certified_interval i
                  ON i.identity_key = CASE WHEN c.isin IS NOT NULL
                       THEN 'nse:isin:' || UPPER(TRIM(c.isin))
                       ELSE 'nse:unresolved:' || UPPER(c.symbol) || ':' ||
                            UPPER(c.series) END
                 AND c.trading_date BETWEEN i.valid_from AND i.valid_to
                WHERE c.trading_date BETWEEN ? AND ?
                  AND i.identity_key IS NULL
                GROUP BY UPPER(c.symbol), UPPER(c.series), c.isin, identity_key
                ORDER BY MIN(c.trading_date), UPPER(c.symbol), UPPER(c.series)
                """,
                [start_date, end_date],
            ).fetchall()
        return tuple(
            CandleIntervalConflictRecord(
                row[0],
                row[1],
                str(row[2]),
                str(row[3]),
                str(row[4]) if row[4] else None,
                str(row[5]),
                MembershipCertificationState.UNRESOLVED_NO_LISTING_EVIDENCE,
                "CANDLE_OUTSIDE_CERTIFIED_ACTIVE_TRADABLE_INTERVAL",
                int(row[6]),
            )
            for row in rows
        )

    @staticmethod
    def _candidate_exposure(
        intervals: ReconstructedIntervals,
        baseline: Mapping[str, Any],
    ) -> tuple[EventCandidateExposureRecord, ...]:
        identities_by_state: dict[MembershipCertificationState, set[str]] = defaultdict(
            set
        )
        for item in intervals.membership:
            identities_by_state[item.state].add(item.identity_key)
        baseline_counts = {
            key: sum(int(item[key]) for item in baseline["candidate_exposure"])
            for key in (
                "technical_candidates",
                "watchlist_candidates",
                "buy_candidates",
                "strong_buy_candidates",
                "approvals",
            )
        }
        records: list[EventCandidateExposureRecord] = []
        for state in MembershipCertificationState:
            affected = len(identities_by_state.get(state, set()))
            if state is MembershipCertificationState.UNRESOLVED_NO_LISTING_EVIDENCE:
                affected = int(baseline.get("unresolved_identities", affected))
            records.append(
                EventCandidateExposureRecord(
                    state,
                    affected,
                    baseline_counts["technical_candidates"]
                    if state
                    is MembershipCertificationState.UNRESOLVED_NO_LISTING_EVIDENCE
                    else 0,
                    baseline_counts["watchlist_candidates"]
                    if state
                    is MembershipCertificationState.UNRESOLVED_NO_LISTING_EVIDENCE
                    else 0,
                    baseline_counts["buy_candidates"]
                    if state
                    is MembershipCertificationState.UNRESOLVED_NO_LISTING_EVIDENCE
                    else 0,
                    baseline_counts["strong_buy_candidates"]
                    if state
                    is MembershipCertificationState.UNRESOLVED_NO_LISTING_EVIDENCE
                    else 0,
                    baseline_counts["approvals"]
                    if state
                    is MembershipCertificationState.UNRESOLVED_NO_LISTING_EVIDENCE
                    else 0,
                    "BASELINE_TOTALS_NOT_IDENTITY_DATE_LINKABLE",
                )
            )
        return tuple(records)

    @staticmethod
    def _event_summary(
        sources: Sequence[Any],
        events: Sequence[SecurityEventRecord],
        rejected: Sequence[EventRejectionRecord],
    ) -> EventSummary:
        counts = Counter(event.event_type.value for event in events)
        return EventSummary(
            len(sources),
            sum(int(item.events_parsed) for item in sources),
            sum(
                event.admission_state is EventAdmissionState.ADMITTED
                for event in events
            ),
            sum(int(item.events_rejected) for item in sources)
            + sum(
                item.failure_code == "CONFLICTING_OFFICIAL_EVENTS" for item in rejected
            ),
            tuple(sorted(counts.items())),
        )

    @staticmethod
    def _identity_summary(
        baseline: Mapping[str, Any],
        intervals: ReconstructedIntervals,
        reuse: Sequence[SymbolReuseAssessment],
        changes: Sequence[SymbolChangeAssessment],
    ) -> EventIdentitySummary:
        governed = {
            item.identity_key
            for item in intervals.membership
            if item.state is MembershipCertificationState.CERTIFIED_ACTIVE_TRADABLE
        }
        provisional = {
            item.identity_key
            for item in intervals.membership
            if item.state
            is MembershipCertificationState.UNRESOLVED_NO_TERMINATION_EVIDENCE
        }
        return EventIdentitySummary(
            len(governed),
            len(provisional),
            max(0, int(baseline["unresolved_identities"]) - len(governed)),
            len(intervals.relationships),
            sum(
                item.final_status
                is MembershipCertificationState.CERTIFIED_ACTIVE_TRADABLE
                for item in reuse
            ),
            sum(
                item.final_status is MembershipCertificationState.SYMBOL_REUSE_CONFLICT
                for item in reuse
            ),
            sum(item.classification != "UNRESOLVED" for item in changes),
            sum(item.classification == "UNRESOLVED" for item in changes),
            0,
            0,
        )

    def _membership_summary(
        self,
        baseline: Mapping[str, Any],
        intervals: ReconstructedIntervals,
        conflicts: Sequence[CandleIntervalConflictRecord],
    ) -> EventMembershipSummary:
        expected = int(baseline.get("certified_identity_days", 0)) + int(
            baseline.get("unresolved_membership_days", 0)
        )
        observed = self._observed_identity_days_by_state(intervals.membership)
        certified = observed[MembershipCertificationState.CERTIFIED_ACTIVE_TRADABLE]
        provisional = observed[
            MembershipCertificationState.UNRESOLVED_NO_TERMINATION_EVIDENCE
        ]
        suspended = sum(
            item.identity_days
            for item in intervals.tradability
            if item.state is MembershipCertificationState.CERTIFIED_ACTIVE_SUSPENDED
        )
        return EventMembershipSummary(
            expected,
            certified,
            provisional,
            max(0, expected - certified - provisional),
            certified,
            suspended,
            0,
            0,
            sum(item.candle_rows for item in conflicts),
        )

    def _observed_identity_days_by_state(
        self,
        intervals: Sequence[MembershipIntervalRecord],
    ) -> Counter[MembershipCertificationState]:
        counts: Counter[MembershipCertificationState] = Counter()
        if not intervals:
            return counts
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            connection.execute(
                """
                CREATE TEMP TABLE classified_membership_interval(
                    identity_key VARCHAR,
                    valid_from DATE,
                    valid_to DATE,
                    state VARCHAR
                )
                """
            )
            connection.executemany(
                "INSERT INTO classified_membership_interval VALUES (?, ?, ?, ?)",
                [
                    (
                        item.identity_key,
                        item.valid_from,
                        item.valid_to,
                        item.state.value,
                    )
                    for item in intervals
                ],
            )
            rows = connection.execute(
                """
                SELECT state, COUNT(*)
                FROM (
                    SELECT DISTINCT
                        CASE WHEN c.isin IS NOT NULL
                             THEN 'nse:isin:' || UPPER(TRIM(c.isin))
                             ELSE 'nse:unresolved:' || UPPER(c.symbol) || ':' ||
                                  UPPER(c.series) END AS identity_key,
                        c.trading_date,
                        i.state
                    FROM daily_candle c
                    JOIN classified_membership_interval i
                      ON i.identity_key = CASE WHEN c.isin IS NOT NULL
                           THEN 'nse:isin:' || UPPER(TRIM(c.isin))
                           ELSE 'nse:unresolved:' || UPPER(c.symbol) || ':' ||
                                UPPER(c.series) END
                     AND c.trading_date BETWEEN i.valid_from AND i.valid_to
                ) classified
                GROUP BY state
                """
            ).fetchall()
        for state, count in rows:
            counts[MembershipCertificationState(str(state))] = int(count)
        return counts

    @staticmethod
    def _ytd_summary(
        events: Sequence[SecurityEventRecord],
        calendar_end: date | None,
        canonical_end: date | None,
    ) -> YtdEvidenceSummary:
        year = canonical_end.year if canonical_end else date.today().year
        event_cutoff = max((event.effective_date for event in events), default=None)
        certified = bool(
            calendar_end
            and canonical_end
            and event_cutoff
            and calendar_end >= canonical_end
            and event_cutoff >= canonical_end
        )
        blocker = None
        if not certified:
            if calendar_end and canonical_end and calendar_end < canonical_end:
                blocker = "OFFICIAL_SESSION_CALENDAR_EVIDENCE_BEHIND_CANONICAL_CUTOFF"
            elif event_cutoff and canonical_end and event_cutoff < canonical_end:
                blocker = "EVENT_OR_MASTER_EVIDENCE_BEHIND_CANONICAL_CUTOFF"
            else:
                blocker = "INSUFFICIENT_MATCHED_2026_EVIDENCE"
        return YtdEvidenceSummary(
            year,
            canonical_end,
            calendar_end,
            event_cutoff,
            certified,
            blocker,
        )

    @staticmethod
    def _certification(
        baseline: Mapping[str, Any],
        intervals: ReconstructedIntervals,
        reuse: Sequence[SymbolReuseAssessment],
        changes: Sequence[SymbolChangeAssessment],
        checkpoints: Sequence[CheckpointReconciliationRecord],
        rejected: Sequence[EventRejectionRecord],
        sources: Sequence[Any],
        sessions: Sequence[date],
    ) -> EventCertificationSummary:
        thresholds = (
            "Every certified identity has an official listing or admission event",
            "Every open interval is corroborated by termination or a later checkpoint",
            "Suspension and restoration boundaries are official-source-backed",
            "Symbol and ISIN transitions are complete and non-conflicting",
            "Checkpoint reconciliation has zero material mismatches",
            "Candle presence is never authoritative membership evidence",
        )
        blockers: list[EventSourcedCertificationState] = []
        if not intervals.membership:
            blockers.append(EventSourcedCertificationState.BLOCKED_LISTING_EVIDENCE)
        if (
            any(
                item.state
                is MembershipCertificationState.UNRESOLVED_NO_TERMINATION_EVIDENCE
                for item in intervals.membership
            )
            or int(baseline.get("delisting_dates", 0)) == 0
        ):
            blockers.append(EventSourcedCertificationState.BLOCKED_TERMINATION_EVIDENCE)
        if not any(
            event_source.source_family == "TEMPORARY_STATUS"
            and event_source.status
            in {EventSourceStatus.ACQUIRED, EventSourceStatus.REUSED}
            for event_source in sources
        ):
            blockers.append(EventSourcedCertificationState.BLOCKED_SUSPENSION_EVIDENCE)
        if any(item.classification == "UNRESOLVED" for item in changes):
            blockers.append(EventSourcedCertificationState.BLOCKED_IDENTITY_TRANSITIONS)
        if any(
            item.final_status is MembershipCertificationState.SYMBOL_REUSE_CONFLICT
            for item in reuse
        ):
            blockers.append(EventSourcedCertificationState.BLOCKED_SYMBOL_REUSE)
        if any(item.issue_codes for item in checkpoints):
            blockers.append(EventSourcedCertificationState.BLOCKED_CHECKPOINT_MISMATCH)
        if any(item.failure_code == "CONFLICTING_OFFICIAL_EVENTS" for item in rejected):
            blockers.append(
                EventSourcedCertificationState.BLOCKED_CONFLICTING_OFFICIAL_EVIDENCE
            )
        unique = tuple(dict.fromkeys(blockers))
        if not intervals.membership:
            primary = EventSourcedCertificationState.INSUFFICIENT_EVIDENCE
        elif not unique:
            primary = EventSourcedCertificationState.EVENT_SOURCED_UNIVERSE_CERTIFIED
        elif any(
            item.state is MembershipCertificationState.CERTIFIED_ACTIVE_TRADABLE
            for item in intervals.membership
        ):
            primary = EventSourcedCertificationState.PARTIALLY_CERTIFIED
        else:
            primary = unique[0]
        certified_intervals = tuple(
            item
            for item in intervals.membership
            if item.state is MembershipCertificationState.CERTIFIED_ACTIVE_TRADABLE
        )
        return EventCertificationSummary(
            primary,
            unique,
            (
                f"{len(certified_intervals)} event-sourced membership intervals are "
                f"certified across {len(sessions)} official sessions. "
                f"{len(unique)} fail-closed blockers remain; exact-date daily masters "
                "are not required when official interval evidence is complete."
            ),
            thresholds,
            min((item.valid_from for item in certified_intervals), default=None),
            max((item.valid_to for item in certified_intervals), default=None),
        )

    def _persist(self, report: EventSourcedUniverseReport) -> None:
        """Create backward-compatible governed tables and replace this contract run."""

        with duckdb.connect(str(self.database_path)) as connection:
            _create_event_tables(connection)
            tables = (
                "security_event",
                "security_event_lineage",
                "security_identity_relationship",
                "security_symbol_interval",
                "security_series_interval",
                "security_name_interval",
                "security_membership_interval",
                "security_tradability_interval",
                "security_event_rejection",
                "security_checkpoint_reconciliation",
            )
            for table in tables:
                connection.execute(
                    f"DELETE FROM {table} WHERE contract_version = ?",  # noqa: S608
                    [HTR009A2_CONTRACT_VERSION],
                )
            _insert_report(connection, report)


def _calendar_sessions(path: Path, start: date) -> tuple[tuple[date, ...], date | None]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    sessions = tuple(
        date.fromisoformat(str(item["trading_date"]))
        for item in payload.get("records", ())
        if item.get("classification") in {"regular_session", "special_session"}
        and date.fromisoformat(str(item["trading_date"])) >= start
    )
    return tuple(sorted(set(sessions))), max(sessions, default=None)


def _reject_conflicting_events(
    events: Sequence[SecurityEventRecord],
) -> tuple[tuple[SecurityEventRecord, ...], tuple[EventRejectionRecord, ...]]:
    grouped: dict[tuple[str | None, date], list[SecurityEventRecord]] = defaultdict(
        list
    )
    for event in events:
        grouped[(event.identity_key, event.effective_date)].append(event)
    conflicts: set[str] = set()
    rejected: list[EventRejectionRecord] = []
    for (key, event_date), group in grouped.items():
        membership = {item.membership_effect for item in group}
        tradability = {item.tradability_effect for item in group}
        if (
            MembershipEffect.OPEN in membership and MembershipEffect.CLOSE in membership
        ) or (
            TradabilityEffect.OPEN in tradability
            and TradabilityEffect.CLOSE in tradability
        ):
            for event in group:
                conflicts.add(event.event_id)
            rejected.append(
                EventRejectionRecord(
                    "event_stream",
                    "internal:event-stream",
                    "CONFLICTING_OFFICIAL_EVENTS",
                    f"conflicting effects for {key or 'unresolved'} on {event_date}",
                )
            )
    return (
        tuple(
            replace(event, admission_state=EventAdmissionState.CONFLICTING)
            if event.event_id in conflicts
            else event
            for event in events
        ),
        tuple(rejected),
    )


def _create_event_tables(connection: duckdb.DuckDBPyConnection) -> None:
    statements = (
        """CREATE TABLE IF NOT EXISTS security_event(
            contract_version VARCHAR, event_id VARCHAR, exchange VARCHAR,
            event_type VARCHAR, effective_date DATE, announcement_date DATE,
            old_symbol VARCHAR, new_symbol VARCHAR, old_series VARCHAR,
            new_series VARCHAR, old_isin VARCHAR, new_isin VARCHAR,
            security_name VARCHAR, predecessor_identity VARCHAR,
            successor_identity VARCHAR, membership_effect VARCHAR,
            tradability_effect VARCHAR, official_source_id VARCHAR,
            document_location VARCHAR, admission_state VARCHAR,
            confidence_state VARCHAR,
            PRIMARY KEY(contract_version, event_id))""",
        """CREATE TABLE IF NOT EXISTS security_event_lineage(
            contract_version VARCHAR, event_id VARCHAR, source_id VARCHAR,
            source_sha256 VARCHAR, source_url VARCHAR, parser VARCHAR,
            row_number BIGINT,
            PRIMARY KEY(contract_version, event_id, source_id))""",
        """CREATE TABLE IF NOT EXISTS security_identity_relationship(
            contract_version VARCHAR, relationship_id VARCHAR,
            predecessor_identity VARCHAR, successor_identity VARCHAR,
            relationship_type VARCHAR, effective_date DATE,
            source_event_id VARCHAR, confidence_state VARCHAR,
            PRIMARY KEY(contract_version, relationship_id))""",
        """CREATE TABLE IF NOT EXISTS security_symbol_interval(
            contract_version VARCHAR, identity_key VARCHAR, symbol VARCHAR,
            valid_from DATE, valid_to DATE, source_event_ids VARCHAR,
            confidence_state VARCHAR, issue_codes VARCHAR,
            PRIMARY KEY(contract_version, identity_key, symbol, valid_from))""",
        """CREATE TABLE IF NOT EXISTS security_series_interval(
            contract_version VARCHAR, identity_key VARCHAR, series VARCHAR,
            valid_from DATE, valid_to DATE, source_event_ids VARCHAR,
            confidence_state VARCHAR, issue_codes VARCHAR,
            PRIMARY KEY(contract_version, identity_key, series, valid_from))""",
        """CREATE TABLE IF NOT EXISTS security_name_interval(
            contract_version VARCHAR, identity_key VARCHAR, security_name VARCHAR,
            valid_from DATE, valid_to DATE, source_event_ids VARCHAR,
            confidence_state VARCHAR,
            PRIMARY KEY(contract_version, identity_key, security_name, valid_from))""",
        """CREATE TABLE IF NOT EXISTS security_membership_interval(
            contract_version VARCHAR, identity_key VARCHAR, valid_from DATE,
            valid_to DATE, state VARCHAR, source_event_ids VARCHAR,
            identity_days BIGINT, issue_codes VARCHAR,
            PRIMARY KEY(contract_version, identity_key, valid_from, state))""",
        """CREATE TABLE IF NOT EXISTS security_tradability_interval(
            contract_version VARCHAR, identity_key VARCHAR, valid_from DATE,
            valid_to DATE, tradable BOOLEAN, state VARCHAR,
            source_event_ids VARCHAR, identity_days BIGINT, issue_codes VARCHAR,
            PRIMARY KEY(contract_version, identity_key, valid_from, tradable))""",
        """CREATE TABLE IF NOT EXISTS security_event_rejection(
            contract_version VARCHAR, source_id VARCHAR, source_url VARCHAR,
            failure_code VARCHAR, failure_detail VARCHAR, row_number BIGINT,
            raw_identifier VARCHAR)""",
        """CREATE TABLE IF NOT EXISTS security_checkpoint_reconciliation(
            contract_version VARCHAR, checkpoint_date DATE,
            derived_identities BIGINT, master_identities BIGINT,
            missing_derived_identities BIGINT,
            unexpected_derived_identities BIGINT, symbol_mismatches BIGINT,
            isin_mismatches BIGINT, series_mismatches BIGINT,
            status_mismatches BIGINT, issue_codes VARCHAR,
            PRIMARY KEY(contract_version, checkpoint_date))""",
    )
    for statement in statements:
        connection.execute(statement)


def _insert_report(
    connection: duckdb.DuckDBPyConnection,
    report: EventSourcedUniverseReport,
) -> None:
    version = HTR009A2_CONTRACT_VERSION
    if report.events:
        connection.executemany(
            "INSERT INTO security_event VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    version,
                    item.event_id,
                    item.exchange,
                    item.event_type.value,
                    item.effective_date,
                    item.announcement_date,
                    item.old_symbol,
                    item.new_symbol,
                    item.old_series,
                    item.new_series,
                    item.old_isin,
                    item.new_isin,
                    item.security_name,
                    item.predecessor_identity,
                    item.successor_identity,
                    item.membership_effect.value,
                    item.tradability_effect.value,
                    item.official_source_id,
                    item.document_location,
                    item.admission_state.value,
                    item.confidence_state.value,
                )
                for item in report.events
            ],
        )
    _insert_dataclass_rows(connection, "security_event_lineage", report.event_lineage)
    _insert_dataclass_rows(
        connection,
        "security_identity_relationship",
        report.identity_relationships,
    )
    _insert_interval_rows(
        connection, "security_symbol_interval", report.symbol_intervals
    )
    _insert_interval_rows(
        connection, "security_series_interval", report.series_intervals
    )
    _insert_interval_rows(connection, "security_name_interval", report.name_intervals)
    _insert_interval_rows(
        connection,
        "security_membership_interval",
        report.membership_intervals,
    )
    _insert_interval_rows(
        connection,
        "security_tradability_interval",
        report.tradability_intervals,
    )
    _insert_dataclass_rows(
        connection,
        "security_event_rejection",
        report.rejected_evidence,
    )
    _insert_dataclass_rows(
        connection,
        "security_checkpoint_reconciliation",
        report.checkpoints,
    )


def _insert_dataclass_rows(
    connection: duckdb.DuckDBPyConnection,
    table: str,
    records: Sequence[Any],
) -> None:
    if not records:
        return
    rows = [_database_values(record) for record in records]
    placeholders = ",".join("?" for _ in range(len(rows[0]) + 1))
    connection.executemany(
        f"INSERT INTO {table} VALUES ({placeholders})",  # noqa: S608
        [(HTR009A2_CONTRACT_VERSION, *row) for row in rows],
    )


def _insert_interval_rows(
    connection: duckdb.DuckDBPyConnection,
    table: str,
    records: Sequence[Any],
) -> None:
    _insert_dataclass_rows(connection, table, records)


def _database_values(record: Any) -> tuple[Any, ...]:
    from dataclasses import fields
    from enum import StrEnum

    values: list[Any] = []
    for field in fields(record):
        value = getattr(record, field.name)
        if isinstance(value, StrEnum):
            values.append(value.value)
        elif isinstance(value, tuple):
            values.append(json.dumps([getattr(item, "value", item) for item in value]))
        else:
            values.append(value)
    return tuple(values)


def _filter_events(
    events: Sequence[SecurityEventRecord],
    symbols: Sequence[str],
    isins: Sequence[str],
    years: Sequence[int],
    event_types: Sequence[SecurityEventType],
) -> tuple[SecurityEventRecord, ...]:
    symbol_set = {item.upper() for item in symbols}
    isin_set = {item.upper() for item in isins}
    year_set = set(years)
    type_set = set(event_types)
    return tuple(
        event
        for event in events
        if (not symbol_set or {event.old_symbol, event.new_symbol} & symbol_set)
        and (not isin_set or {event.old_isin, event.new_isin} & isin_set)
        and (not year_set or event.effective_date.year in year_set)
        and (not type_set or event.event_type in type_set)
    )


def _filter_intervals(
    intervals: Sequence[Any],
    symbols: Sequence[str],
    isins: Sequence[str],
    years: Sequence[int],
) -> tuple[Any, ...]:
    symbol_set = {item.upper() for item in symbols}
    isin_set = {item.upper() for item in isins}
    year_set = set(years)
    return tuple(
        item
        for item in intervals
        if (not symbol_set or str(getattr(item, "symbol", "")).upper() in symbol_set)
        and (not isin_set or item.identity_key.rsplit(":", 1)[-1] in isin_set)
        and (
            not year_set
            or any(
                year in year_set
                for year in range(item.valid_from.year, item.valid_to.year + 1)
            )
        )
    )


def _filter_membership(
    intervals: Sequence[MembershipIntervalRecord],
    isins: Sequence[str],
    years: Sequence[int],
    states: Sequence[MembershipCertificationState],
    only_unresolved: bool,
) -> tuple[MembershipIntervalRecord, ...]:
    result = cast(
        tuple[MembershipIntervalRecord, ...],
        _filter_intervals(intervals, (), isins, years),
    )
    state_set = set(states)
    return tuple(
        item
        for item in result
        if (not state_set or item.state in state_set)
        and (not only_unresolved or item.state.value.startswith("UNRESOLVED"))
    )


def _filter_tradability(
    intervals: Sequence[TradabilityIntervalRecord],
    isins: Sequence[str],
    years: Sequence[int],
    states: Sequence[MembershipCertificationState],
    only_unresolved: bool,
) -> tuple[TradabilityIntervalRecord, ...]:
    result = cast(
        tuple[TradabilityIntervalRecord, ...],
        _filter_intervals(intervals, (), isins, years),
    )
    state_set = set(states)
    return tuple(
        item
        for item in result
        if (not state_set or item.state in state_set)
        and (not only_unresolved or item.state.value.startswith("UNRESOLVED"))
    )


def _session_on_or_after(sessions: Sequence[date], boundary: date) -> date | None:
    return next((item for item in sessions if item >= boundary), None)


def _session_before(sessions: Sequence[date], boundary: date) -> date | None:
    return next((item for item in reversed(sessions) if item < boundary), None)


def _session_count(sessions: Sequence[date], start: date, end: date) -> int:
    return sum(start <= item <= end for item in sessions)


def _tradability_record(
    key: str,
    start: date,
    end: date,
    tradable: bool,
    source_ids: tuple[str, ...],
    sessions: Sequence[date],
    membership_state: MembershipCertificationState,
) -> TradabilityIntervalRecord:
    if (
        not tradable
        and membership_state is MembershipCertificationState.CERTIFIED_ACTIVE_TRADABLE
    ):
        state = MembershipCertificationState.CERTIFIED_ACTIVE_SUSPENDED
    else:
        state = membership_state
    return TradabilityIntervalRecord(
        key,
        start,
        end,
        tradable,
        state,
        source_ids,
        _session_count(sessions, start, end),
    )


def _relationship_type(event_type: SecurityEventType) -> IdentityRelationshipType:
    return {
        SecurityEventType.MERGED: IdentityRelationshipType.MERGER,
        SecurityEventType.DEMERGED: IdentityRelationshipType.DEMERGER,
        SecurityEventType.AMALGAMATED: IdentityRelationshipType.AMALGAMATION,
        SecurityEventType.SCHEME_EFFECTIVE: IdentityRelationshipType.SCHEME,
        SecurityEventType.SYMBOL_CHANGED: IdentityRelationshipType.CONTINUOUS,
    }.get(event_type, IdentityRelationshipType.PREDECESSOR_SUCCESSOR)


def _interval_key(item: Any) -> tuple[str, date, date, str]:
    return (
        item.identity_key,
        item.valid_from,
        item.valid_to,
        str(getattr(item, "symbol", getattr(item, "series", ""))),
    )


def _group_by_identity(items: Iterable[Any]) -> dict[str, tuple[Any, ...]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for item in items:
        grouped[item.identity_key].append(item)
    return {key: tuple(value) for key, value in grouped.items()}


def _intervals_overlap(intervals: Sequence[MembershipIntervalRecord]) -> bool:
    ordered = sorted(intervals, key=lambda item: (item.valid_from, item.valid_to))
    return any(
        current.valid_from <= previous.valid_to
        for previous, current in zip(ordered, ordered[1:])
    )


def _minimum_interval_gap(intervals: Sequence[MembershipIntervalRecord]) -> int | None:
    ordered = sorted(intervals, key=lambda item: (item.valid_from, item.valid_to))
    gaps = [
        (current.valid_from - previous.valid_to).days - 1
        for previous, current in zip(ordered, ordered[1:])
        if current.valid_from > previous.valid_to
    ]
    return min(gaps) if gaps else None


def _attribute_at(intervals: Sequence[Any]) -> dict[str, Any]:
    grouped = _group_by_identity(intervals)
    return {
        key: lambda day, values=values: next(
            (
                getattr(item, "symbol", getattr(item, "series", None))
                for item in values
                if item.valid_from <= day <= item.valid_to
            ),
            None,
        )
        for key, values in grouped.items()
    }


__all__ = [
    "EventSourcedIntervalReconstructor",
    "EventSourcedUniverseCertificationEngine",
    "ReconstructedIntervals",
]
