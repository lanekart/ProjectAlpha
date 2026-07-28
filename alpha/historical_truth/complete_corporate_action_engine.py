"""HTR-010B complete Tier A corporate-action and price-basis engine."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

import duckdb

from alpha.historical_truth.complete_corporate_action_models import (
    ADJUSTMENT_POLICY_VERSION,
    HTR010B_CONTRACT_VERSION,
    PRODUCTION_INFLUENCE,
    AssignmentMethod,
    CertificationState,
    CompleteCorporateActionReport,
    EventAdmission,
    FactorState,
    GovernedActionType,
    PriceBasisState,
    ReplayReadiness,
    stable_id,
)
from alpha.historical_truth.corporate_action_price_engine import (
    AdjustmentFactorEngine,
)
from alpha.historical_truth.corporate_action_price_models import (
    ActionAdmissionState,
    AdjustmentFactorState,
    CorporateActionEvent,
    CorporateActionLineage,
    CorporateActionType,
    EvidenceConfidence,
)
from alpha.historical_truth.corporate_action_price_sources import (
    OfficialCorporateActionStore,
    default_corporate_action_sources,
)
from alpha.historical_truth.legacy_isin_reference_bridge import (
    LegacyIsinReferenceBridge,
)


class CompleteCorporateActionDatasetEngine:
    """Reprocess immutable official action evidence against HTR-010A3."""

    def __init__(self, database_path: Path, root: Path) -> None:
        self.database_path = database_path
        self.store = OfficialCorporateActionStore(root)

    def run(
        self,
        *,
        htr010a3_output: Path,
        htr009a2_output: Path | None = None,
        start_date: date,
        end_date: date,
        output: Path,
        refresh_sources: bool,
        verify_only: bool,
    ) -> CompleteCorporateActionReport:
        if refresh_sources and verify_only:
            raise ValueError("refresh_sources and verify_only are mutually exclusive")
        joins, upstream_a3_readiness = _validated_a3_join_contract(htr010a3_output)
        reference_bridge = (
            LegacyIsinReferenceBridge.from_output(
                htr009a2_output,
                htr010a3_output=htr010a3_output,
            )
            if htr009a2_output is not None
            else None
        )
        admitted = {
            str(row["identity_key"]): row
            for row in joins
            if row.get("admitted_to_certified_join")
        }
        specs = default_corporate_action_sources(start_date, end_date)
        if refresh_sources:
            self.store.acquire(specs)
        # Certification always selects the latest immutable manifest after any
        # acquisition. This makes the refresh and immediate reuse audit use the
        # same pinned source generation even when NSE returns equivalent bytes
        # in a different row order.
        parsed = self.store.verify_or_missing(specs)
        inventory = tuple(item.inventory for item in parsed)
        raw_fingerprint = _raw_candle_fingerprint(self.database_path)
        source_by_id = {item.source_id: item for item in inventory}
        lineages = {
            item.action_id: item for source in parsed for item in source.lineage
        }
        all_actions = tuple(item for source in parsed for item in source.actions)
        tier_actions = tuple(
            item
            for item in all_actions
            if item.governed_identity_id in admitted
            and start_date <= item.effective_date <= end_date
        )
        raw_census = tuple(
            _raw_event(item, source_by_id[item.source_id], lineages.get(item.action_id))
            for item in sorted(
                tier_actions, key=lambda row: (row.ex_date, row.action_id)
            )
        )
        canonical, duplicate_groups, duplicate_rejections = canonicalize_events(
            tier_actions, admitted
        )
        event_lineage = tuple(
            _event_lineage(item, source_by_id, lineages) for item in canonical
        )
        actions_by_id = {item.action_id: item for item in tier_actions}
        factors = derive_factors(
            self.database_path,
            canonical,
            actions_by_id,
            admitted,
            reference_bridge=reference_bridge,
            action_lineage_by_id=lineages,
        )
        cumulative = cumulative_factors(factors)
        canonical_by_raw_id = {
            str(raw_id): str(item["canonical_event_id"])
            for item in canonical
            for raw_id in item["raw_record_ids"]
        }
        transitions = _filter_htr009b_records(
            "htr009b_identity_transitions.json",
            lambda row: (
                row.get("predecessor_identity") in admitted
                or row.get("successor_identity") in admitted
            ),
        )
        legacy_summaries = _filter_htr009b_records(
            "htr009b_adjusted_candle_summary.json",
            lambda row: row.get("identity_key") in admitted,
        )
        summaries, intervals = price_basis(
            joins, canonical, factors, legacy_summaries, start_date, end_date
        )
        continuity = tuple(
            _continuity(row, canonical_by_raw_id[str(row["action_id"])])
            for row in _filter_htr009b_records(
                "htr009b_price_discontinuities.json",
                lambda row: str(row.get("action_id")) in canonical_by_raw_id,
            )
        )
        contamination = tuple(_contamination(row) for row in continuity)
        source_completeness = tuple(_source_completeness(item) for item in inventory)
        parser_rejections = tuple(
            {
                **_jsonable(asdict(item)),
                "admission_state": EventAdmission.REJECTED_INVALID_TERMS.value,
            }
            for source in parsed
            for item in source.rejected
        )
        rejected = tuple(
            sorted(
                (*parser_rejections, *duplicate_rejections),
                key=lambda row: json.dumps(row, sort_keys=True),
            )
        )
        coverage = coverage_matrix(joins, canonical, factors, summaries, inventory)
        ytd = ytd_2026(canonical, factors, summaries, inventory)
        readiness = adjusted_replay_readiness(
            canonical, factors, intervals, raw_fingerprint
        )
        readiness = _apply_upstream_a3_readiness(
            readiness,
            upstream_a3_readiness,
        )
        certification = certification_summary(
            coverage,
            source_completeness,
            raw_fingerprint,
            readiness,
        )
        checksums = tuple(
            sorted(
                (
                    *(
                        (item.immutable_path or item.source_id, item.sha256 or "")
                        for item in inventory
                    ),
                    *(
                        reference_bridge.source_checksums
                        if reference_bridge is not None
                        else ()
                    ),
                )
            )
        )
        report = CompleteCorporateActionReport(
            HTR010B_CONTRACT_VERSION,
            ADJUSTMENT_POLICY_VERSION,
            PRODUCTION_INFLUENCE,
            start_date,
            end_date,
            source_completeness,
            raw_census,
            canonical,
            event_lineage,
            duplicate_groups,
            rejected,
            factors,
            cumulative,
            transitions,
            intervals,
            summaries,
            continuity,
            contamination,
            coverage,
            ytd,
            readiness,
            certification,
            checksums,
            raw_fingerprint,
            "",
        )
        report = replace(report, report_sha256=report.calculated_sha256())
        self._persist(report, output / "htr010b_corporate_action.duckdb")
        if _raw_candle_fingerprint(self.database_path) != raw_fingerprint:
            raise RuntimeError("canonical raw candles changed during HTR-010B")
        return report

    def _persist(self, report: CompleteCorporateActionReport, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect(str(path))
        try:
            datasets = {
                "tier_a_corporate_action_raw_event": report.raw_event_census,
                "tier_a_corporate_action_event": report.canonical_events,
                "tier_a_corporate_action_event_lineage": report.event_lineage,
                "tier_a_corporate_action_duplicate_group": report.duplicate_groups,
                "tier_a_corporate_action_factor": report.adjustment_factors,
                "tier_a_corporate_action_cumulative_factor": report.cumulative_factors,
                "tier_a_price_basis_interval": report.price_basis_intervals,
                "tier_a_identity_transition_action": report.identity_transitions,
                "tier_a_price_continuity_validation": report.price_continuity,
                "tier_a_false_signal_contamination": (
                    report.false_signal_contamination
                ),
                "tier_a_corporate_action_certification": (
                    report.identity_coverage_matrix
                ),
            }
            for name, rows in datasets.items():
                connection.execute(f"DROP TABLE IF EXISTS {name}")
                connection.execute(f"CREATE TABLE {name}(payload JSON NOT NULL)")
                values = [(json.dumps(row, sort_keys=True),) for row in rows]
                if values:
                    connection.executemany(f"INSERT INTO {name} VALUES (?)", values)
            connection.execute("DROP TABLE IF EXISTS adjusted_replay_readiness")
            connection.execute(
                "CREATE TABLE adjusted_replay_readiness(payload JSON NOT NULL)"
            )
            connection.execute(
                "INSERT INTO adjusted_replay_readiness VALUES (?)",
                [json.dumps(report.replay_readiness, sort_keys=True)],
            )
            _copy_adjusted_rows(connection, self.database_path, report)
        finally:
            connection.close()


def canonicalize_events(
    actions: tuple[CorporateActionEvent, ...],
    joins: dict[str, dict[str, Any]],
) -> tuple[
    tuple[dict[str, Any], ...],
    tuple[dict[str, Any], ...],
    tuple[dict[str, Any], ...],
]:
    grouped: dict[tuple[str, date, str, str], list[CorporateActionEvent]] = defaultdict(
        list
    )
    for action in actions:
        normalized = normalize_action(action)
        key = (
            action.governed_identity_id or "",
            action.effective_date,
            normalized.value,
            action.purpose.upper().strip(),
        )
        grouped[key].append(action)
    events = []
    duplicate_groups = []
    rejections = []
    for key, group in sorted(grouped.items(), key=lambda item: str(item[0])):
        selected = sorted(group, key=lambda item: (item.source_id, item.action_id))[0]
        identity = selected.governed_identity_id or ""
        normalized = normalize_action(selected)
        canonical_id = stable_id("htr010b-event", *key)
        join = joins[identity]
        factor_state = map_factor_state(selected, normalized)
        admission = admission_state(selected, normalized, factor_state, join)
        raw_ids = tuple(sorted(item.action_id for item in group))
        applicability = tuple(sorted({item.series for item in group}))
        events.append(
            {
                "canonical_event_id": canonical_id,
                "governed_identity_id": identity,
                "symbol": selected.symbol,
                "series_applicability": list(applicability),
                "isin": selected.isin,
                "action_type": normalized.value,
                "raw_action_text": selected.purpose,
                "normalization_reason": _normalization_reason(selected, normalized),
                "announcement_date": _iso(selected.announcement_date),
                "record_date": _iso(selected.record_date),
                "ex_date": selected.ex_date.isoformat(),
                "effective_date": selected.effective_date.isoformat(),
                "assignment_date": selected.effective_date.isoformat(),
                "assignment_method": AssignmentMethod.OFFICIAL_ISIN_INTERVAL.value,
                "assignment_confidence": "HIGH",
                "matching_isin_interval": selected.isin,
                "matching_symbol_interval": selected.symbol,
                "matching_series_interval": selected.series,
                "predecessor_successor_state": (
                    "PREDECESSOR" if selected.predecessor_identity else "NOT_APPLICABLE"
                ),
                "identity_join_readiness": join["state"],
                "ambiguity_codes": [],
                "admission_state": admission.value,
                "factor_state": factor_state.value,
                "price_adjustment_required": selected.price_adjustment_required,
                "old_face_value": selected.old_face_value,
                "new_face_value": selected.new_face_value,
                "ratio_numerator": selected.ratio_numerator,
                "ratio_denominator": selected.ratio_denominator,
                "cash_amount": selected.cash_amount,
                "rights_price": selected.rights_price,
                "predecessor_identity": selected.predecessor_identity,
                "successor_identity": selected.successor_identity,
                "source_id": selected.source_id,
                "raw_record_ids": list(raw_ids),
            }
        )
        if len(group) > 1:
            duplicate_groups.append(
                {
                    "duplicate_group_id": stable_id("htr010b-duplicate", *key),
                    "canonical_event_id": canonical_id,
                    "classification": "SAME_EVENT_REPEATED_ACROSS_OFFICIAL_FILES",
                    "raw_record_ids": list(raw_ids),
                    "parallel_series": len(applicability) > 1,
                }
            )
            for duplicate in sorted(group, key=lambda item: item.action_id)[1:]:
                rejections.append(
                    {
                        "raw_record_id": duplicate.action_id,
                        "canonical_event_id": canonical_id,
                        "admission_state": EventAdmission.REJECTED_DUPLICATE.value,
                        "reason": "canonical duplicate retained in lineage",
                    }
                )
    return tuple(events), tuple(duplicate_groups), tuple(rejections)


def normalize_action(action: CorporateActionEvent) -> GovernedActionType:
    purpose = action.purpose.upper()
    direct = {
        CorporateActionType.SPLIT: GovernedActionType.SPLIT,
        CorporateActionType.BONUS: GovernedActionType.BONUS,
        CorporateActionType.RIGHTS: GovernedActionType.RIGHTS,
        CorporateActionType.FACE_VALUE_CHANGE: GovernedActionType.FACE_VALUE_CHANGE,
        CorporateActionType.CAPITAL_REDUCTION: GovernedActionType.CAPITAL_REDUCTION,
        CorporateActionType.MERGER: GovernedActionType.MERGER,
        CorporateActionType.DEMERGER: GovernedActionType.DEMERGER,
        CorporateActionType.AMALGAMATION: GovernedActionType.AMALGAMATION,
        CorporateActionType.SCHEME_OF_ARRANGEMENT: (
            GovernedActionType.SCHEME_OF_ARRANGEMENT
        ),
        CorporateActionType.SPIN_OFF: GovernedActionType.SPIN_OFF,
        CorporateActionType.SECURITY_REPLACEMENT: (
            GovernedActionType.SECURITY_REPLACEMENT
        ),
        CorporateActionType.ISIN_CHANGE: GovernedActionType.ISIN_CHANGE,
        CorporateActionType.SYMBOL_CHANGE: GovernedActionType.SYMBOL_CHANGE,
        CorporateActionType.RELISTING: GovernedActionType.RELISTING,
        CorporateActionType.SHARE_CANCELLATION: (GovernedActionType.SHARE_CANCELLATION),
    }
    if action.action_type in direct:
        return direct[action.action_type]
    if action.action_type is CorporateActionType.DIVIDEND:
        if "SPECIAL" in purpose:
            return GovernedActionType.DIVIDEND_SPECIAL
        if "INTERIM" in purpose:
            return GovernedActionType.DIVIDEND_INTERIM
        if "FINAL" in purpose:
            return GovernedActionType.DIVIDEND_FINAL
        return GovernedActionType.DIVIDEND_ORDINARY
    if "BUYBACK" in purpose or "BUY BACK" in purpose:
        return GovernedActionType.BUYBACK
    if "PARTLY PAID" in purpose and "FULLY PAID" in purpose:
        return GovernedActionType.PARTLY_PAID_TO_FULLY_PAID
    if "CALL" in purpose and "PARTLY" in purpose:
        return GovernedActionType.PARTLY_PAID_CALL
    informational_terms = (
        "ANNUAL GENERAL",
        "ANNUAL GEMERAL",
        "ANNUAL GENERAL",
        "ANNUL GENERAL",
        "ANUAL GENERAL",
        "ANUUAL GENERAL",
        "EXTRA ORDINARY GENERAL",
        "EXTRA-ORDINARY GENERAL",
        "EXTRAORDINARY GENERAL",
        "ANNUAL BOOK CLOS",
        "ANNUAL CLOSING",
    )
    if any(term in purpose for term in informational_terms):
        return GovernedActionType.OTHER_NON_ADJUSTING_EVENT
    return GovernedActionType.UNKNOWN_ACTION


def map_factor_state(
    action: CorporateActionEvent, normalized: GovernedActionType
) -> FactorState:
    if normalized is GovernedActionType.BONUS and _is_separate_security_bonus(action):
        return FactorState.FACTOR_NOT_MULTIPLICATIVE
    if normalized is GovernedActionType.RIGHTS and _is_separate_security_rights(action):
        return FactorState.FACTOR_NOT_MULTIPLICATIVE
    non_adjusting = {
        GovernedActionType.DIVIDEND_ORDINARY,
        GovernedActionType.DIVIDEND_INTERIM,
        GovernedActionType.DIVIDEND_FINAL,
        GovernedActionType.DIVIDEND_SPECIAL,
        GovernedActionType.BUYBACK,
        GovernedActionType.OTHER_NON_ADJUSTING_EVENT,
    }
    if normalized in non_adjusting:
        return FactorState.FACTOR_NOT_REQUIRED
    transition = {
        GovernedActionType.MERGER,
        GovernedActionType.DEMERGER,
        GovernedActionType.AMALGAMATION,
        GovernedActionType.SCHEME_OF_ARRANGEMENT,
        GovernedActionType.SPIN_OFF,
    }
    identity_only = {
        GovernedActionType.ISIN_CHANGE,
        GovernedActionType.SYMBOL_CHANGE,
        GovernedActionType.SERIES_CHANGE,
        GovernedActionType.RELISTING,
        GovernedActionType.SECURITY_REPLACEMENT,
    }
    if normalized in transition:
        return FactorState.FACTOR_NOT_MULTIPLICATIVE
    if normalized in identity_only:
        return FactorState.FACTOR_IDENTITY_TRANSITION_ONLY
    mapping = {
        AdjustmentFactorState.KNOWN_OFFICIAL: FactorState.FACTOR_CERTIFIED,
        AdjustmentFactorState.DERIVED_FROM_OFFICIAL_TERMS: (
            FactorState.FACTOR_DERIVED_OFFICIAL_TERMS
        ),
        AdjustmentFactorState.NOT_REQUIRED: FactorState.FACTOR_NOT_REQUIRED,
        AdjustmentFactorState.AMBIGUOUS: FactorState.FACTOR_AMBIGUOUS_TERMS,
        AdjustmentFactorState.UNKNOWN: FactorState.FACTOR_UNKNOWN_MISSING_TERMS,
        AdjustmentFactorState.INVALID: FactorState.FACTOR_INVALID,
        AdjustmentFactorState.CONFLICTING: FactorState.FACTOR_CONFLICTING_EVENTS,
    }
    return mapping[action.adjustment_factor_state]


def _is_separate_security_bonus(action: CorporateActionEvent) -> bool:
    purpose = action.purpose.upper()
    return any(
        marker in purpose
        for marker in (
            " DVR ",
            " DVR:",
            "DVR :",
            "PCCPS",
            "CCPS",
            "WARRANT",
            "BONUS DEB",
            "BONUS PREFERENCE",
        )
    )


def _is_separate_security_rights(action: CorporateActionEvent) -> bool:
    purpose = action.purpose.upper()
    offered_non_equity = any(
        marker in purpose
        for marker in (
            " NCD",
            " BOND",
            " PCD",
            "PCCPS",
        )
    )
    offered_equity = any(
        marker in purpose
        for marker in (
            "RIGHT-EQ",
            "RIGHTS-EQ",
            "RIGHTS EQ",
            "RIGHTS EQUITY",
        )
    )
    return offered_non_equity and not offered_equity


def admission_state(
    action: CorporateActionEvent,
    normalized: GovernedActionType,
    factor: FactorState,
    join: dict[str, Any],
) -> EventAdmission:
    if normalized is GovernedActionType.UNKNOWN_ACTION:
        return EventAdmission.UNRESOLVED_EVENT_TYPE
    if join["state"] == "JOIN_READY_BOUNDED_MEMBERSHIP":
        return EventAdmission.ADMITTED_BOUNDED_IDENTITY
    if factor is FactorState.FACTOR_NOT_REQUIRED:
        return EventAdmission.ADMITTED_NON_ADJUSTING
    if action.admission_state is ActionAdmissionState.REJECTED:
        return EventAdmission.REJECTED_INVALID_TERMS
    if factor in {
        FactorState.FACTOR_DERIVED_OFFICIAL_TERMS,
        FactorState.FACTOR_CERTIFIED,
        FactorState.FACTOR_CERTIFIED_REFERENCE_PRICE,
    }:
        return EventAdmission.ADMITTED_FACTOR_DERIVABLE
    if factor in {
        FactorState.FACTOR_UNKNOWN_MISSING_TERMS,
        FactorState.FACTOR_AMBIGUOUS_TERMS,
        FactorState.FACTOR_NOT_MULTIPLICATIVE,
    }:
        return EventAdmission.ADMITTED_FACTOR_UNKNOWN
    return EventAdmission.ADMITTED_COMPLETE


def derive_factors(
    database_path: Path,
    events: tuple[dict[str, Any], ...],
    actions_by_id: dict[str, CorporateActionEvent],
    joins: dict[str, dict[str, Any]] | None = None,
    *,
    reference_bridge: LegacyIsinReferenceBridge | None = None,
    action_lineage_by_id: Mapping[str, CorporateActionLineage] | None = None,
) -> tuple[dict[str, Any], ...]:
    engine = AdjustmentFactorEngine()
    factors = []
    with duckdb.connect(str(database_path), read_only=True) as connection:
        for event in events:
            source_ids = event["raw_record_ids"]
            source = actions_by_id.get(str(source_ids[0])) if source_ids else None
            if source is None:
                continue
            reference = None
            provenance: dict[str, Any] = {
                "reference_price_date": None,
                "reference_price_series": None,
                "reference_price_isin": None,
                "reference_price_source_sha256": None,
                "reference_price_provenance_state": "NOT_APPLICABLE",
                "reference_price_original_provenance_state": "NOT_APPLICABLE",
                "reference_price_certified": False,
                **_empty_reference_bridge_provenance(),
            }
            if source.action_type is CorporateActionType.RIGHTS:
                if joins is None:
                    row = connection.execute(
                        "SELECT close_price FROM daily_candle WHERE symbol=? AND "
                        "series=? AND trading_date<? ORDER BY trading_date DESC "
                        "LIMIT 1",
                        [source.symbol, source.series, source.effective_date],
                    ).fetchone()
                    reference = float(row[0]) if row else None
                    provenance = {
                        "reference_price_date": None,
                        "reference_price_series": source.series.upper(),
                        "reference_price_isin": None,
                        "reference_price_source_sha256": None,
                        "reference_price_provenance_state": (
                            "LEGACY_UNCERTIFIED_REFERENCE_PRICE"
                            if reference is not None
                            else "PRIOR_CANDLE_MISSING"
                        ),
                        "reference_price_original_provenance_state": (
                            "LEGACY_UNCERTIFIED_REFERENCE_PRICE"
                            if reference is not None
                            else "PRIOR_CANDLE_MISSING"
                        ),
                        "reference_price_certified": False,
                        **_empty_reference_bridge_provenance(),
                    }
                else:
                    reference, provenance = _rights_reference_context(
                        connection,
                        source=source,
                        event=event,
                        join=joins.get(str(event["governed_identity_id"]), {}),
                        reference_bridge=reference_bridge,
                        action_population=tuple(actions_by_id.values()),
                        action_lineage_by_id=action_lineage_by_id or {},
                    )
            factor = engine.derive(source, reference_price=reference)
            state = map_factor_state(source, normalize_action(source))
            if source.action_type is CorporateActionType.RIGHTS:
                if state is FactorState.FACTOR_NOT_MULTIPLICATIVE:
                    pass
                elif factor.price_factor is None:
                    state = FactorState.FACTOR_UNKNOWN_MISSING_TERMS
                elif provenance["reference_price_certified"]:
                    state = FactorState.FACTOR_CERTIFIED_REFERENCE_PRICE
                else:
                    state = FactorState.FACTOR_PROVISIONAL_REFERENCE_PRICE
            factors.append(
                {
                    "factor_id": stable_id(
                        "htr010b-factor", event["canonical_event_id"], "BACKWARD"
                    ),
                    "canonical_event_id": event["canonical_event_id"],
                    "identity_key": event["governed_identity_id"],
                    "effective_date": event["effective_date"],
                    "price_factor": factor.price_factor,
                    "quantity_factor": factor.quantity_factor,
                    "reference_price": reference,
                    **provenance,
                    "factor_state": state.value,
                    "calculation_version": ADJUSTMENT_POLICY_VERSION,
                    "explanation": factor.explanation,
                }
            )
    return tuple(
        sorted(
            factors,
            key=lambda row: (
                row["identity_key"],
                row["effective_date"],
                row["factor_id"],
            ),
        )
    )


def _rights_reference_context(
    connection: duckdb.DuckDBPyConnection,
    *,
    source: CorporateActionEvent,
    event: dict[str, Any],
    join: dict[str, Any],
    reference_bridge: LegacyIsinReferenceBridge | None = None,
    action_population: Sequence[CorporateActionEvent] = (),
    action_lineage_by_id: Mapping[str, CorporateActionLineage] | None = None,
) -> tuple[float | None, dict[str, Any]]:
    applicable = tuple(
        str(item).upper() for item in event.get("series_applicability", ())
    )
    event_isin = str(source.isin or "").upper()
    row = connection.execute(
        "SELECT trading_date, upper(coalesce(isin, '')), close_price, "
        "upper(symbol), "
        "coalesce(source_sha256, '') FROM daily_candle "
        "WHERE upper(symbol)=? AND upper(series)=? AND trading_date<? "
        "ORDER BY trading_date DESC LIMIT 1",
        [source.symbol.upper(), source.series.upper(), source.effective_date],
    ).fetchone()
    used_exact_isin_alias = False
    if row is None and event_isin:
        rows = connection.execute(
            "SELECT trading_date, upper(coalesce(isin, '')), close_price, "
            "upper(symbol), coalesce(source_sha256, '') FROM daily_candle "
            "WHERE upper(isin)=? AND upper(series)=? AND trading_date<? "
            "QUALIFY trading_date=max(trading_date) OVER () "
            "ORDER BY upper(symbol), coalesce(source_sha256, '')",
            [event_isin, source.series.upper(), source.effective_date],
        ).fetchall()
        unique_rows = {
            (item[0], str(item[1]), item[2], str(item[3]), str(item[4]))
            for item in rows
        }
        if len(unique_rows) == 1:
            row = next(iter(unique_rows))
            used_exact_isin_alias = str(row[3]) != source.symbol.upper()
    prior_date = row[0] if row else None
    prior_isin = str(row[1]) if row else ""
    close = float(row[2]) if row and row[2] is not None else None
    observed_symbol = str(row[3]) if row else ""
    source_sha = str(row[4]) if row else ""

    if not join.get("admitted_to_certified_join"):
        state = "A3_JOIN_NOT_ADMITTED"
    elif len(applicable) != 1 or applicable[0] != source.series.upper():
        state = "SERIES_NOT_UNIQUE"
    elif row is None:
        state = "PRIOR_CANDLE_MISSING"
    elif close is None or close <= 0:
        state = "PRIOR_CLOSE_INVALID"
    elif not source_sha:
        state = "SOURCE_SHA256_MISSING"
    elif not event_isin:
        state = "EVENT_ISIN_MISSING"
    elif not prior_isin:
        state = "PRIOR_ISIN_MISSING"
    elif prior_isin != event_isin:
        state = "PRIOR_ISIN_MISMATCH"
    elif used_exact_isin_alias:
        state = "CERTIFIED_SAME_ISIN_ALTERNATE_SYMBOL_PRIOR_CLOSE"
    else:
        state = "CERTIFIED_SAME_ISIN_CANONICAL_PRIOR_CLOSE"

    original_state = state
    bridge_provenance = _empty_reference_bridge_provenance()
    if (
        state == "PRIOR_ISIN_MISSING"
        and reference_bridge is not None
        and prior_date is not None
    ):
        bridge_result = reference_bridge.resolve(
            identity_key=str(event["governed_identity_id"]),
            symbol=source.symbol,
            series=source.series,
            isin=event_isin,
            reference_date=prior_date,
        )
        bridge_provenance = bridge_result.provenance()
        if bridge_result.certified:
            state = "CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE_PRIOR_CLOSE"
    if state == "PRIOR_ISIN_MISSING" and prior_date is not None:
        bounded = _bounded_official_action_identity_provenance(
            source=source,
            reference_date=prior_date,
            action_population=action_population,
            action_lineage_by_id=action_lineage_by_id or {},
        )
        if bounded is not None:
            state = "CERTIFIED_BOUNDED_OFFICIAL_ACTION_IDENTITY_INTERVAL_PRIOR_CLOSE"
            bridge_provenance = bounded
    certified = state in {
        "CERTIFIED_SAME_ISIN_CANONICAL_PRIOR_CLOSE",
        "CERTIFIED_SAME_ISIN_ALTERNATE_SYMBOL_PRIOR_CLOSE",
        "CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE_PRIOR_CLOSE",
        "CERTIFIED_BOUNDED_OFFICIAL_ACTION_IDENTITY_INTERVAL_PRIOR_CLOSE",
    }
    return close, {
        "reference_price_date": prior_date.isoformat() if prior_date else None,
        "reference_price_observed_symbol": observed_symbol or None,
        "reference_price_series": source.series.upper(),
        "reference_price_isin": prior_isin or None,
        "reference_price_source_sha256": source_sha or None,
        "reference_price_provenance_state": state,
        "reference_price_original_provenance_state": original_state,
        "reference_price_certified": certified,
        **bridge_provenance,
    }


def _bounded_official_action_identity_provenance(
    *,
    source: CorporateActionEvent,
    reference_date: date,
    action_population: Sequence[CorporateActionEvent],
    action_lineage_by_id: Mapping[str, CorporateActionLineage],
) -> dict[str, Any] | None:
    isin = str(source.isin or "").upper()
    symbol = source.symbol.upper()
    series = source.series.upper()
    current_lineage = action_lineage_by_id.get(source.action_id)
    if (
        not isin
        or current_lineage is None
        or not _sha256_text(current_lineage.source_sha256)
    ):
        return None
    prior = tuple(
        item
        for item in action_population
        if item.action_id != source.action_id
        and str(item.isin or "").upper() == isin
        and item.symbol.upper() == symbol
        and item.series.upper() == series
        and item.effective_date < source.effective_date
        and item.confidence_state is EvidenceConfidence.HIGH
        and item.action_id in action_lineage_by_id
        and _sha256_text(action_lineage_by_id[item.action_id].source_sha256)
    )
    if not prior:
        return None
    lower = max(prior, key=lambda item: (item.effective_date, item.action_id))
    if not (lower.effective_date <= reference_date < source.effective_date):
        return None
    if any(
        item.symbol.upper() == symbol
        and item.series.upper() == series
        and item.effective_date >= lower.effective_date
        and item.effective_date <= source.effective_date
        and str(item.isin or "").upper() not in {"", isin}
        for item in action_population
    ):
        return None
    lower_lineage = action_lineage_by_id[lower.action_id]
    interval_id = stable_id(
        "htr010b3-official-action-identity-interval",
        isin,
        symbol,
        series,
        lower.effective_date.isoformat(),
        source.effective_date.isoformat(),
    )
    evidence_sha = {
        lower.source_id: lower_lineage.source_sha256,
        source.source_id: current_lineage.source_sha256,
    }
    return {
        **_empty_reference_bridge_provenance(),
        "reference_price_bridge_contract_version": (
            "DSI-010B3-BOUNDED-OFFICIAL-ACTION-IDENTITY-v1.0.0"
        ),
        "reference_price_bridge_state": (
            "CERTIFIED_BOUNDED_OFFICIAL_ACTION_IDENTITY_INTERVAL"
        ),
        "reference_price_bridge_identity": f"nse:isin:{isin}",
        "reference_price_bridge_symbol": symbol,
        "reference_price_bridge_series": series,
        "reference_price_bridge_isin": isin,
        "reference_price_bridge_reference_date": reference_date.isoformat(),
        "reference_price_bridge_candle_isin_remained_missing": True,
        "reference_price_bridge_membership_interval_ids": [interval_id],
        "reference_price_bridge_membership_states": [
            "BOUNDED_OFFICIAL_ACTION_IDENTITY_INTERVAL"
        ],
        "reference_price_bridge_membership_confidence": "HIGH",
        "reference_price_bridge_membership_event_ids": [
            lower.action_id,
            source.action_id,
        ],
        "reference_price_bridge_symbol_interval_ids": [interval_id],
        "reference_price_bridge_symbol_confidence": "HIGH",
        "reference_price_bridge_symbol_event_ids": [
            lower.action_id,
            source.action_id,
        ],
        "reference_price_bridge_official_event_ids": [
            lower.action_id,
            source.action_id,
        ],
        "reference_price_bridge_official_source_ids": sorted(evidence_sha),
        "reference_price_bridge_evidence_sha256": evidence_sha,
        "reference_price_bridge_source_contract_id": interval_id,
        "reference_price_bridge_source_report_sha256": sha256(
            "|".join(
                (
                    interval_id,
                    *(f"{key}:{evidence_sha[key]}" for key in sorted(evidence_sha)),
                )
            ).encode()
        ).hexdigest(),
        "reference_price_bridge_production_influence": False,
    }


def _sha256_text(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text.lower())


def _empty_reference_bridge_provenance() -> dict[str, Any]:
    return {
        "reference_price_bridge_contract_version": None,
        "reference_price_bridge_state": "NOT_APPLICABLE",
        "reference_price_bridge_rejection_reason": None,
        "reference_price_bridge_identity": None,
        "reference_price_bridge_symbol": None,
        "reference_price_bridge_series": None,
        "reference_price_bridge_isin": None,
        "reference_price_bridge_reference_date": None,
        "reference_price_bridge_candle_isin_remained_missing": False,
        "reference_price_bridge_membership_interval_ids": [],
        "reference_price_bridge_membership_states": [],
        "reference_price_bridge_membership_confidence": None,
        "reference_price_bridge_membership_event_ids": [],
        "reference_price_bridge_symbol_interval_ids": [],
        "reference_price_bridge_symbol_confidence": None,
        "reference_price_bridge_symbol_event_ids": [],
        "reference_price_bridge_tradability_interval_ids": [],
        "reference_price_bridge_tradability_states": [],
        "reference_price_bridge_tradability_certified": None,
        "reference_price_bridge_official_event_ids": [],
        "reference_price_bridge_official_source_ids": [],
        "reference_price_bridge_evidence_sha256": {},
        "reference_price_bridge_overlapping_identities": [],
        "reference_price_bridge_symbol_reuse_conflict": False,
        "reference_price_bridge_symbol_change_conflict": False,
        "reference_price_bridge_series_transition_conflict": False,
        "reference_price_bridge_source_contract_id": None,
        "reference_price_bridge_source_report_sha256": None,
        "reference_price_bridge_production_influence": False,
    }


def cumulative_factors(
    factors: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for factor in factors:
        grouped[str(factor["identity_key"])].append(factor)
    result = []
    for identity, rows in sorted(grouped.items()):
        price: float | None = 1.0
        quantity: float | None = 1.0
        contributors = []
        for row in sorted(
            rows, key=lambda item: (item["effective_date"], item["factor_id"])
        ):
            state = str(row["factor_state"])
            unknown = state in {
                FactorState.FACTOR_UNKNOWN_MISSING_TERMS.value,
                FactorState.FACTOR_AMBIGUOUS_TERMS.value,
                FactorState.FACTOR_PROVISIONAL_REFERENCE_PRICE.value,
                FactorState.FACTOR_CONFLICTING_EVENTS.value,
                FactorState.FACTOR_NOT_MULTIPLICATIVE.value,
                FactorState.FACTOR_INVALID.value,
            }
            if unknown:
                price = None
                quantity = None
            elif row["price_factor"] is not None and price is not None:
                price *= float(row["price_factor"])
            elif state != FactorState.FACTOR_NOT_REQUIRED.value:
                price = None
            if row["quantity_factor"] is not None and quantity is not None:
                quantity *= float(row["quantity_factor"])
            elif state != FactorState.FACTOR_NOT_REQUIRED.value:
                quantity = None
            contributors.append(str(row["factor_id"]))
            result.append(
                {
                    "identity_key": identity,
                    "effective_date": row["effective_date"],
                    "backward_cumulative_price_factor": price,
                    "forward_cumulative_price_factor": (
                        1.0 / price if price is not None else None
                    ),
                    "cumulative_quantity_factor": quantity,
                    "factor_ids": list(contributors),
                    "non_commutative": row["factor_state"]
                    == FactorState.FACTOR_NOT_MULTIPLICATIVE.value,
                }
            )
    return tuple(result)


def price_basis(
    joins: list[dict[str, Any]],
    events: tuple[dict[str, Any], ...],
    factors: tuple[dict[str, Any], ...],
    legacy: tuple[dict[str, Any], ...],
    start: date,
    end: date,
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    events_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    factors_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        events_by_id[str(event["governed_identity_id"])].append(event)
    for factor in factors:
        factors_by_id[str(factor["identity_key"])].append(factor)
    legacy_by_id = {str(row["identity_key"]): row for row in legacy}
    summaries = []
    intervals = []
    for join in sorted(joins, key=lambda row: str(row["identity_key"])):
        identity = str(join["identity_key"])
        identity_events = events_by_id.get(identity, [])
        identity_factors = factors_by_id.get(identity, [])
        old = legacy_by_id.get(identity, {})
        raw_rows = int(old.get("raw_rows", 0))
        adjusted_rows = int(old.get("adjusted_rows", 0))
        unknown = sum(
            row["factor_state"]
            in {
                FactorState.FACTOR_UNKNOWN_MISSING_TERMS.value,
                FactorState.FACTOR_AMBIGUOUS_TERMS.value,
                FactorState.FACTOR_PROVISIONAL_REFERENCE_PRICE.value,
                FactorState.FACTOR_NOT_MULTIPLICATIVE.value,
            }
            for row in identity_factors
        )
        known = sum(row["price_factor"] is not None for row in identity_factors)
        transition = any(
            row["factor_state"]
            in {
                FactorState.FACTOR_NOT_MULTIPLICATIVE.value,
                FactorState.FACTOR_IDENTITY_TRANSITION_ONLY.value,
            }
            for row in identity_factors
        )
        if not identity_events:
            state = PriceBasisState.RAW_NO_ACTION_EXPOSURE
        elif transition:
            state = PriceBasisState.IDENTITY_TRANSITION_BOUNDARY
        elif unknown and known:
            state = PriceBasisState.MIXED_PRICE_BASIS
        elif unknown:
            state = PriceBasisState.FACTOR_UNKNOWN
        elif known:
            state = PriceBasisState.BACKWARD_ADJUSTED_CERTIFIED
        else:
            state = PriceBasisState.RAW_NO_ACTION_EXPOSURE
        action_ids = [str(row["canonical_event_id"]) for row in identity_events]
        summaries.append(
            {
                "identity_key": identity,
                "symbol": join["symbol"],
                "raw_rows": raw_rows,
                "adjusted_rows": adjusted_rows,
                "known_factor_count": known,
                "unknown_factor_count": unknown,
                "action_ids": sorted(action_ids),
                "price_basis_state": state.value,
                "raw_preserved": True,
            }
        )
        intervals.append(
            {
                "identity_key": identity,
                "valid_from": start.isoformat(),
                "valid_to": end.isoformat(),
                "price_basis_state": state.value,
                "action_ids": sorted(action_ids),
                "known_factor_count": known,
                "unknown_factor_count": unknown,
                "quarantined": state
                in {
                    PriceBasisState.MIXED_PRICE_BASIS,
                    PriceBasisState.FACTOR_UNKNOWN,
                    PriceBasisState.IDENTITY_TRANSITION_BOUNDARY,
                },
            }
        )
    return tuple(summaries), tuple(intervals)


def coverage_matrix(
    joins: list[dict[str, Any]],
    events: tuple[dict[str, Any], ...],
    factors: tuple[dict[str, Any], ...],
    summaries: tuple[dict[str, Any], ...],
    inventory: tuple[Any, ...],
) -> tuple[dict[str, Any], ...]:
    events_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    factors_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in events:
        events_by_id[str(row["governed_identity_id"])].append(row)
    for row in factors:
        factors_by_id[str(row["identity_key"])].append(row)
    summary_by_id = {str(row["identity_key"]): row for row in summaries}
    complete_sources = all(not item.failure_code for item in inventory)
    result = []
    for join in sorted(joins, key=lambda row: str(row["identity_key"])):
        identity = str(join["identity_key"])
        identity_events = events_by_id.get(identity, [])
        identity_factors = factors_by_id.get(identity, [])
        counts = Counter(str(row["factor_state"]) for row in identity_factors)
        summary = summary_by_id[identity]
        transitions = sum(
            row["factor_state"]
            in {
                FactorState.FACTOR_NOT_MULTIPLICATIVE.value,
                FactorState.FACTOR_IDENTITY_TRANSITION_ONLY.value,
            }
            for row in identity_factors
        )
        factor_required = [
            row
            for row in identity_factors
            if row["factor_state"]
            not in {
                FactorState.FACTOR_NOT_REQUIRED.value,
                FactorState.FACTOR_IDENTITY_TRANSITION_ONLY.value,
            }
        ]
        unknown = counts[FactorState.FACTOR_UNKNOWN_MISSING_TERMS.value]
        ambiguous = counts[FactorState.FACTOR_AMBIGUOUS_TERMS.value]
        provisional = counts[FactorState.FACTOR_PROVISIONAL_REFERENCE_PRICE.value]
        if not identity_events and complete_sources:
            certification = CertificationState.NO_MATERIAL_ACTIONS_FOUND
        elif transitions:
            certification = (
                CertificationState.IDENTITY_TRANSITION_CERTIFIED_PRICE_NONCOMPARABLE
            )
        elif unknown or ambiguous or provisional:
            certification = CertificationState.FACTOR_COVERAGE_PARTIAL
        elif identity_events:
            certification = CertificationState.CORPORATE_ACTION_CERTIFIED
        else:
            certification = CertificationState.UNKNOWN_EVENT_COVERAGE
        result.append(
            {
                "identity_key": identity,
                "symbol": join["symbol"],
                "join_readiness": join["state"],
                "event_census_complete_through_cutoff": complete_sources,
                "identity_assignment_coverage": 1.0,
                "action_type_coverage": 1.0
                if identity_events
                and all(
                    row["action_type"] != GovernedActionType.UNKNOWN_ACTION.value
                    for row in identity_events
                )
                else 0.0,
                "event_count": len(identity_events),
                "factor_required_event_count": len(factor_required),
                "certified_factor_count": counts[FactorState.FACTOR_CERTIFIED.value],
                "reference_certified_factor_count": counts[
                    FactorState.FACTOR_CERTIFIED_REFERENCE_PRICE.value
                ],
                "derived_factor_count": counts[
                    FactorState.FACTOR_DERIVED_OFFICIAL_TERMS.value
                ],
                "provisional_factor_count": counts[
                    FactorState.FACTOR_PROVISIONAL_REFERENCE_PRICE.value
                ],
                "unknown_factor_count": unknown,
                "ambiguous_factor_count": ambiguous,
                "non_multiplicative_event_count": transitions,
                "adjusted_row_coverage": summary["adjusted_rows"],
                "mixed_price_basis_intervals": int(
                    summary["price_basis_state"]
                    == PriceBasisState.MIXED_PRICE_BASIS.value
                ),
                "certification_state": certification.value,
            }
        )
    return tuple(result)


def adjusted_replay_readiness(
    events: tuple[dict[str, Any], ...],
    factors: tuple[dict[str, Any], ...],
    intervals: tuple[dict[str, Any], ...],
    raw_fingerprint: str,
) -> dict[str, Any]:
    unknown_ids = sorted(
        {
            str(row["identity_key"])
            for row in factors
            if row["factor_state"]
            in {
                FactorState.FACTOR_UNKNOWN_MISSING_TERMS.value,
                FactorState.FACTOR_AMBIGUOUS_TERMS.value,
                FactorState.FACTOR_PROVISIONAL_REFERENCE_PRICE.value,
                FactorState.FACTOR_NOT_MULTIPLICATIVE.value,
            }
        }
    )
    mixed = sum(row["quarantined"] for row in intervals)
    state = (
        ReplayReadiness.CONDITIONALLY_READY_FOR_ADJUSTED_REPLAY_INTEGRATION
        if unknown_ids or mixed
        else ReplayReadiness.READY_FOR_ADJUSTED_REPLAY_INTEGRATION
    )
    return {
        "state": state.value,
        "admitted_event_count": sum(
            str(row["admission_state"]).startswith("ADMITTED") for row in events
        ),
        "identity_ambiguities": 0,
        "quarantined_identity_count": len(unknown_ids),
        "quarantined_identities": unknown_ids,
        "quarantined_interval_count": mixed,
        "raw_candle_fingerprint": raw_fingerprint,
        "raw_data_preserved": True,
        "unknown_factor_applied_as_one": False,
        "point_in_time_contract": (
            "Use rolling as-of adjustment views for signal formation; backward "
            "research views are continuity transforms and do not make an event "
            "known before announcement/effective date."
        ),
        "blockers": [],
        "recommended_next_milestone": (
            "Validate quarantined intervals before adjusted replay integration."
            if unknown_ids
            else "Adjusted replay integration validation"
        ),
    }


def ytd_2026(
    events: tuple[dict[str, Any], ...],
    factors: tuple[dict[str, Any], ...],
    summaries: tuple[dict[str, Any], ...],
    inventory: tuple[Any, ...],
) -> dict[str, Any]:
    ytd_events = [
        row for row in events if str(row["effective_date"]).startswith("2026-")
    ]
    ids = {str(row["governed_identity_id"]) for row in ytd_events}
    ytd_factors = [
        row for row in factors if str(row["effective_date"]).startswith("2026-")
    ]
    derived_states = {
        FactorState.FACTOR_CERTIFIED.value,
        FactorState.FACTOR_CERTIFIED_REFERENCE_PRICE.value,
        FactorState.FACTOR_DERIVED_OFFICIAL_TERMS.value,
        FactorState.FACTOR_PROVISIONAL_REFERENCE_PRICE.value,
    }
    unknown_states = {
        FactorState.FACTOR_UNKNOWN_MISSING_TERMS.value,
        FactorState.FACTOR_AMBIGUOUS_TERMS.value,
        FactorState.FACTOR_CONFLICTING_EVENTS.value,
        FactorState.FACTOR_INVALID.value,
    }
    source = [item for item in inventory if item.covered_start.year == 2026]
    return {
        "cutoff": "2026-07-20",
        "events_observed": len(ytd_events),
        "events_admitted": sum(
            str(row["admission_state"]).startswith("ADMITTED") for row in ytd_events
        ),
        "factors_derived": sum(
            row["factor_state"] in derived_states for row in ytd_factors
        ),
        "factors_unknown": sum(
            row["factor_state"] in unknown_states for row in ytd_factors
        ),
        "identities_affected": len(ids),
        "adjusted_rows": sum(
            int(row["adjusted_rows"]) for row in summaries if row["identity_key"] in ids
        ),
        "source_cutoffs": [item.covered_end.isoformat() for item in source],
        "missing_source_coverage": any(item.failure_code for item in source),
        "final_state": "YTD_PARTIAL_NOT_FULL_YEAR",
    }


def certification_summary(
    coverage: tuple[dict[str, Any], ...],
    sources: tuple[dict[str, Any], ...],
    raw_fingerprint: str,
    readiness: dict[str, Any],
) -> dict[str, Any]:
    return {
        "tier_a_identities": len(coverage),
        "certification_counts": dict(
            sorted(Counter(row["certification_state"] for row in coverage).items())
        ),
        "source_file_completeness": all(
            row["acquisition_state"] != "FAILED" for row in sources
        ),
        "parser_completeness": all(
            row["parser_coverage"] == "COMPLETE" for row in sources
        ),
        "identity_join_completeness": 1.0,
        "raw_candle_fingerprint": raw_fingerprint,
        "replay_readiness": readiness["state"],
        "candidate_independent": True,
        "full_benchmark_replays": 0,
        "production_influence": False,
    }


def _raw_event(
    action: CorporateActionEvent, source: Any, lineage: Any
) -> dict[str, Any]:
    return {
        "source_record_id": action.action_id,
        "source_family": source.source_family,
        "source_url": source.source_url,
        "official_host": source.official_host,
        "document_id": source.document_id,
        "source_file": source.immutable_path,
        "source_checksum": source.sha256,
        "retrieval_timestamp": source.retrieval_timestamp,
        "raw_symbol": action.symbol,
        "raw_series": action.series,
        "raw_isin": action.isin,
        "raw_security_name": None,
        "raw_action_text": action.purpose,
        "announcement_date": _iso(action.announcement_date),
        "ex_date": action.ex_date.isoformat(),
        "record_date": _iso(action.record_date),
        "effective_date": action.effective_date.isoformat(),
        "parser_version": source.parser,
        "row_number": lineage.row_number if lineage else None,
        "original_admission_state": action.admission_state.value,
        "governed_identity_id": action.governed_identity_id,
    }


def _event_lineage(
    action: dict[str, Any],
    sources: dict[str, Any],
    lineages: dict[str, Any],
) -> dict[str, Any]:
    raw_ids = tuple(str(item) for item in action["raw_record_ids"])
    raw_lineage = []
    for raw_id in raw_ids:
        lineage = lineages.get(raw_id)
        source = sources[str(action["source_id"])]
        raw_lineage.append(
            {
                "raw_record_id": raw_id,
                "source_id": source.source_id,
                "source_checksum": source.sha256,
                "source_url": source.source_url,
                "parser": source.parser,
                "row_number": lineage.row_number if lineage else None,
            }
        )
    return {
        "canonical_event_id": action["canonical_event_id"],
        "raw_record_ids": list(raw_ids),
        "raw_lineage": raw_lineage,
    }


def _source_completeness(source: Any) -> dict[str, Any]:
    return {
        "source_id": source.source_id,
        "source_family": source.source_family,
        "earliest_available_date": source.covered_start.isoformat(),
        "latest_available_date": source.covered_end.isoformat(),
        "missing_slices": [],
        "acquisition_state": (
            "FAILED" if source.failure_code else "AVAILABLE_IMMUTABLE"
        ),
        "immutable_reuse_state": "CHECKSUM_VERIFIED",
        "parser": source.parser,
        "parser_coverage": "COMPLETE" if not source.failure_code else "FAILED",
        "event_type_coverage": "SOURCE_DEFINED",
        "records_inspected": source.records_inspected,
        "events_parsed": source.events_parsed,
        "events_rejected": source.events_rejected,
        "source_checksum": source.sha256,
        "known_limitations": source.known_limitations,
    }


def _continuity(row: dict[str, Any], canonical_event_id: str) -> dict[str, Any]:
    raw = abs(float(row.get("raw_gap_atr") or 0.0))
    adjusted = abs(float(row.get("adjusted_gap_atr") or 0.0))
    if row.get("continuity_restored"):
        state = "CONTINUITY_RESTORED"
    elif adjusted < raw:
        state = "CONTINUITY_IMPROVED"
    elif adjusted > 5 and adjusted > raw:
        state = "FACTOR_LIKELY_INCORRECT"
    else:
        state = "RESIDUAL_MARKET_GAP"
    return {
        **row,
        "raw_action_id": row["action_id"],
        "action_id": canonical_event_id,
        "continuity_state": state,
        "raw_moving_average_discontinuity": raw,
        "adjusted_moving_average_discontinuity": adjusted,
        "support_resistance_discontinuity": raw > 2,
        "factor_plausible": adjusted <= raw,
    }


def _contamination(row: dict[str, Any]) -> dict[str, Any]:
    exposed = abs(float(row.get("raw_gap_atr") or 0.0)) >= 2
    return {
        "action_id": row["action_id"],
        "identity_key": row["identity_key"],
        "false_breakdown_risk": bool(row.get("false_breakdown_risk")),
        "false_breakout_risk": bool(row.get("false_breakout_risk")),
        "volatility_atr_risk": exposed,
        "moving_average_risk": exposed,
        "relative_strength_risk": exposed,
        "retracement_fibonacci_risk": exposed,
        "support_resistance_risk": exposed,
        "return_mfe_mae_risk": exposed,
        "mitigated_by_adjustment": row["continuity_state"]
        in {"CONTINUITY_RESTORED", "CONTINUITY_IMPROVED"},
    }


def _filter_htr009b_records(
    filename: str, predicate: Any
) -> tuple[dict[str, Any], ...]:
    path = Path("artifacts/htr009b_corporate_action_price_continuity") / filename
    return tuple(row for row in _records(path) if predicate(row))


def _copy_adjusted_rows(
    connection: duckdb.DuckDBPyConnection,
    source_path: Path,
    report: CompleteCorporateActionReport,
) -> None:
    connection.execute("DROP TABLE IF EXISTS tier_a_adjusted_daily_candle")
    connection.execute("DROP TABLE IF EXISTS tier_a_adjusted_candle_lineage")
    connection.execute("DROP TABLE IF EXISTS tier_a_isin")
    connection.execute("CREATE TEMP TABLE tier_a_isin(isin VARCHAR PRIMARY KEY)")
    isins = [
        str(row["identity_key"]).removeprefix("nse:isin:")
        for row in report.identity_coverage_matrix
        if str(row["identity_key"]).startswith("nse:isin:")
    ]
    connection.executemany(
        "INSERT INTO tier_a_isin VALUES (?)", [(item,) for item in isins]
    )
    escaped = str(source_path).replace("'", "''")
    connection.execute(f"ATTACH '{escaped}' AS source_db (READ_ONLY)")
    connection.execute(
        "CREATE TABLE tier_a_adjusted_daily_candle AS SELECT a.* FROM "
        "source_db.adjusted_daily_candle a JOIN tier_a_isin i ON a.isin=i.isin "
        "WHERE a.contract_version='HTR-009B-v1.0.0'"
    )
    connection.execute(
        "CREATE TABLE tier_a_adjusted_candle_lineage AS SELECT l.* FROM "
        "source_db.adjusted_candle_lineage l JOIN tier_a_adjusted_daily_candle a "
        "USING(contract_version,trading_date,exchange,symbol,series)"
    )
    connection.execute("DETACH source_db")


def _raw_candle_fingerprint(path: Path) -> str:
    with duckdb.connect(str(path), read_only=True) as connection:
        row = connection.execute(
            "SELECT COUNT(*), MIN(trading_date), MAX(trading_date), SUM(volume), "
            "COUNT(DISTINCT source_sha256) FROM daily_candle"
        ).fetchone()
    if row is None:
        raise RuntimeError("raw candle fingerprint query returned no row")
    return sha256("|".join(str(item) for item in row).encode()).hexdigest()


def _validated_a3_join_contract(
    output: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    joins = _records(output / "htr010a3_corporate_action_join_readiness.json")
    payload = json.loads(
        (output / "htr010a3_readiness.json").read_text(encoding="utf-8")
    )
    if not isinstance(payload, dict):
        raise ValueError("HTR-010A3 readiness payload must be an object")
    if payload.get("production_influence") is not False:
        raise ValueError("HTR-010A3 readiness must have production influence false")
    readiness = payload.get("readiness")
    if not isinstance(readiness, dict):
        raise ValueError("HTR-010A3 readiness decision must be an object")
    denominator = _nonnegative_int(
        readiness.get("denominator_identities"),
        "denominator_identities",
    )
    admitted = _nonnegative_int(
        readiness.get("admitted_identities"),
        "admitted_identities",
    )
    quarantined = _nonnegative_int(
        readiness.get("quarantined_identities"),
        "quarantined_identities",
    )
    if admitted + quarantined != denominator:
        raise ValueError(
            "HTR-010A3 admitted and quarantined identities must equal denominator"
        )
    if len(joins) != denominator:
        raise ValueError(
            "HTR-010A3 join population does not match signed denominator: "
            f"joins={len(joins)} denominator={denominator}"
        )
    observed_admitted = sum(
        bool(row.get("admitted_to_certified_join")) for row in joins
    )
    if observed_admitted != admitted:
        raise ValueError(
            "HTR-010A3 admitted join count does not match signed readiness: "
            f"joins={observed_admitted} readiness={admitted}"
        )
    if len(joins) - observed_admitted != quarantined:
        raise ValueError(
            "HTR-010A3 quarantined join count does not match signed readiness"
        )
    state = str(readiness.get("state") or "")
    if state not in {
        "READY_FOR_HTR_010B",
        "CONDITIONALLY_READY_FOR_HTR_010B",
        "NOT_READY_FOR_HTR_010B",
    }:
        raise ValueError(f"unsupported HTR-010A3 readiness state: {state}")
    blockers = readiness.get("blockers", [])
    if not isinstance(blockers, list):
        raise ValueError("HTR-010A3 blockers must be a list")
    return joins, {
        "state": state,
        "blockers": [str(item) for item in blockers],
        "denominator_identities": denominator,
        "admitted_identities": admitted,
        "quarantined_identities": quarantined,
        "report_sha256": str(payload.get("report_sha256") or ""),
    }


def _apply_upstream_a3_readiness(
    readiness: dict[str, Any],
    upstream: dict[str, Any],
) -> dict[str, Any]:
    result = dict(readiness)
    upstream_state = str(upstream["state"])
    upstream_blockers = [str(item) for item in upstream.get("blockers", [])]
    result["upstream_htr010a3_readiness"] = upstream_state
    result["upstream_htr010a3_blockers"] = upstream_blockers
    existing_blockers = [str(item) for item in result.get("blockers", [])]
    prefixed = [f"HTR-010A3: {item}" for item in upstream_blockers]
    if upstream_state == "NOT_READY_FOR_HTR_010B":
        result["state"] = (
            ReplayReadiness.NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION.value
        )
        result["blockers"] = [
            *existing_blockers,
            *(prefixed or ["HTR-010A3: upstream foundation is not ready"]),
        ]
    elif upstream_state == "CONDITIONALLY_READY_FOR_HTR_010B":
        if (
            result["state"]
            == ReplayReadiness.READY_FOR_ADJUSTED_REPLAY_INTEGRATION.value
        ):
            result["state"] = (
                ReplayReadiness.CONDITIONALLY_READY_FOR_ADJUSTED_REPLAY_INTEGRATION.value
            )
        result["blockers"] = [*existing_blockers, *prefixed]
    else:
        result["blockers"] = existing_blockers
    return result


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"HTR-010A3 {field} must be a non-negative integer")
    return value


def _records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("records", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError(f"expected records: {path}")
    return rows


def _normalization_reason(
    action: CorporateActionEvent, normalized: GovernedActionType
) -> str:
    if action.action_type is CorporateActionType.DIVIDEND:
        return f"structured dividend subtype normalized as {normalized.value}"
    return f"HTR-009B structured action type mapped to {normalized.value}"


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _jsonable(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


__all__ = [
    "CompleteCorporateActionDatasetEngine",
    "adjusted_replay_readiness",
    "admission_state",
    "canonicalize_events",
    "cumulative_factors",
    "derive_factors",
    "map_factor_state",
    "normalize_action",
    "price_basis",
]
