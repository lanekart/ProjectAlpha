"""HTR-010A3 Tier A identity conflict closure and readiness engine."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from alpha.historical_truth.foundation_readiness_models import (
    HTR010A3_CONTRACT_VERSION,
    PRODUCTION_INFLUENCE,
    AmbiguityEffect,
    ConflictCase,
    ConflictOutcome,
    ConflictResolution,
    ConflictType,
    CorporateActionJoinReadiness,
    DailyActivityContract,
    DiscrepancyResolution,
    FoundationReadiness,
    FoundationReadinessReport,
    GapResolution,
    GapType,
    JoinReadiness,
    ReadinessDecision,
    SuspensionCeiling,
    SuspensionEvidenceBoundary,
    TerminationBoundary,
    TerminationState,
    stable_id,
)
from alpha.historical_truth.security_population_repair_sources import (
    SecurityPopulationSourceInventory,
    verify_source_checksums,
)


class TierAFoundationReadinessEngine:
    """Close identity ambiguity without changing production consumers."""

    def __init__(self, database_path: Path, root: Path) -> None:
        self.database_path = database_path
        self.sources = SecurityPopulationSourceInventory(root)

    def run(
        self,
        *,
        htr010a_output: Path,
        htr010a1_output: Path,
        htr010a2_output: Path,
        start_date: date,
        end_date: date,
        output: Path,
        refresh_sources: bool,
        verify_only: bool,
    ) -> FoundationReadinessReport:
        del htr010a_output
        if refresh_sources and verify_only:
            raise ValueError("refresh_sources and verify_only are mutually exclusive")
        _, source_evidence = self.sources.collect(refresh_sources=refresh_sources)
        verify_source_checksums(source_evidence)

        observations = _records(
            htr010a2_output / "htr010a2_canonical_observations.json"
        )
        certifications = _records(
            htr010a2_output / "htr010a2_certification_matrix.json"
        )
        overlaps = _records(htr010a2_output / "htr010a2_remaining_overlaps.json")
        gaps = _records(htr010a2_output / "htr010a2_remaining_gaps.json")
        boundaries = _records(htr010a2_output / "htr010a2_boundary_ranges.json")
        discrepancies = _records(
            htr010a2_output / "htr010a2_2026_checkpoint_reconciliation.json"
        )
        source_semantics = _records(
            htr010a2_output / "htr010a2_daily_source_semantics.json"
        )
        source_inventory = _records(
            htr010a2_output / "htr010a2_suspension_source_inventory.json"
        )
        a2_readiness = _object(htr010a2_output / "htr010a2_htr010b_readiness.json")
        prior_overlaps = _records(htr010a1_output / "htr010a1_interval_overlaps.json")
        transitions = _records(
            Path("artifacts/htr009b_corporate_action_price_continuity")
            / "htr009b_identity_transitions.json"
        )
        actions = _records(
            Path("artifacts/htr009b_corporate_action_price_continuity")
            / "htr009b_corporate_actions.json"
        )

        obs_by_identity: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in observations:
            obs_by_identity[str(row["identity_key"])].append(row)
        boundary_by_identity = {str(row["identity_key"]): row for row in boundaries}
        prior_overlap_by_id = {str(row["conflict_id"]): row for row in prior_overlaps}
        transitions_by_identity: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in transitions:
            identity = row.get("predecessor_identity")
            if identity:
                transitions_by_identity[str(identity)].append(row)
        actions_by_identity: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in actions:
            identity = row.get("governed_identity_id")
            if identity:
                actions_by_identity[str(identity)].append(row)

        cases, evidence, resolutions = conflict_cases(
            overlaps,
            prior_overlap_by_id,
            obs_by_identity,
            boundary_by_identity,
            transitions_by_identity,
            actions_by_identity,
        )
        gap_resolutions = resolve_gaps(gaps)
        discrepancy_resolutions = resolve_discrepancies(discrepancies)
        termination = termination_boundaries(
            certifications,
            boundary_by_identity,
            obs_by_identity,
            transitions_by_identity,
        )
        suspension = suspension_ceiling(source_inventory)
        contracts = daily_contracts(source_semantics)
        joins = join_population(
            certifications,
            obs_by_identity,
            gap_resolutions,
            resolutions,
        )
        quarantined = tuple(row for row in joins if not row.admitted_to_certified_join)
        readiness = readiness_decision(joins, resolutions, discrepancy_resolutions)
        rejected = tuple(
            {
                "source_id": row.get("source_id"),
                "failure_code": row.get("failure_code"),
                "failure_detail": row.get("failure_detail"),
            }
            for row in source_inventory
            if row.get("failure_code")
        )
        checksums = tuple(
            sorted(
                (item.source_path, item.source_sha256)
                for item in source_evidence
                if item.source_path and item.source_sha256
            )
        )
        report = FoundationReadinessReport(
            HTR010A3_CONTRACT_VERSION,
            PRODUCTION_INFLUENCE,
            start_date,
            end_date,
            cases,
            evidence,
            resolutions,
            gap_resolutions,
            discrepancy_resolutions,
            termination,
            suspension,
            contracts,
            joins,
            quarantined,
            readiness,
            rejected,
            checksums,
            str(a2_readiness["canonical_candle_fingerprint"]),
            "",
        )
        report = replace(report, report_sha256=report.calculated_sha256())
        self._persist(report, output / "htr010a3_foundation_readiness.duckdb")
        return report

    def _persist(self, report: FoundationReadinessReport, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect(str(path))
        try:
            tables = {
                "tier_a_identity_conflict_case": report.conflict_cases,
                "tier_a_identity_conflict_evidence": report.conflict_evidence,
                "tier_a_identity_conflict_resolution": report.conflict_resolutions,
                "tier_a_lifecycle_gap_resolution": report.gap_resolutions,
                "tier_a_termination_boundary": report.termination_boundaries,
                "suspension_evidence_ceiling": report.suspension_ceiling,
                "daily_activity_source_contract": report.daily_source_contracts,
                "corporate_action_identity_join_readiness": report.join_readiness,
            }
            for name, rows in tables.items():
                connection.execute(f"DROP TABLE IF EXISTS {name}")
                connection.execute(f"CREATE TABLE {name}(payload JSON NOT NULL)")
                payloads = [json.dumps(_jsonable(row), sort_keys=True) for row in rows]
                connection.executemany(
                    f"INSERT INTO {name} VALUES (?)", [(item,) for item in payloads]
                )
            connection.execute("DROP TABLE IF EXISTS htr010a3_readiness")
            connection.execute("CREATE TABLE htr010a3_readiness(payload JSON NOT NULL)")
            connection.execute(
                "INSERT INTO htr010a3_readiness VALUES (?)",
                [json.dumps(_jsonable(report.readiness), sort_keys=True)],
            )
        finally:
            connection.close()


def conflict_cases(
    overlaps: list[dict[str, Any]],
    prior_overlaps: dict[str, dict[str, Any]],
    observations: dict[str, list[dict[str, Any]]],
    boundaries: dict[str, dict[str, Any]],
    transitions: dict[str, list[dict[str, Any]]],
    actions: dict[str, list[dict[str, Any]]],
) -> tuple[
    tuple[ConflictCase, ...],
    tuple[dict[str, Any], ...],
    tuple[ConflictResolution, ...],
]:
    cases = []
    evidence = []
    resolutions = []
    for row in overlaps:
        if row.get("support_state") != "TIER_A_CORE_EQUITY":
            continue
        identity = str(row["identity_key"])
        source = prior_overlaps.get(str(row["conflict_id"]), {})
        obs = observations.get(identity, [])
        boundary = boundaries.get(identity, {})
        case_id = stable_id("htr010a3-case", row["conflict_id"])
        same_isin = bool(row.get("same_isin"))
        within_identity = bool(row.get("within_one_identity"))
        different_series = not bool(row.get("same_series"))
        if same_isin and within_identity and different_series:
            conflict_type = ConflictType.VALID_PARALLEL_SERIES
            outcome = ConflictOutcome.RESOLVED_PARALLEL_SERIES
            confidence = "HIGH"
            requirement = None
            blocking = False
            rationale = (
                "Official ISIN fixes one governed identity; series remains part "
                "of the source-row key, so concurrent series do not create an "
                "identity-date ambiguity."
            )
        else:
            conflict_type = ConflictType.INSUFFICIENT_OFFICIAL_EVIDENCE
            outcome = ConflictOutcome.QUARANTINED_IDENTITY_DATE_AMBIGUITY
            confidence = "LOW"
            requirement = "Effective-dated official identity transition evidence"
            blocking = True
            rationale = "Unique identity-date assignment is not established."
        source_ids = tuple(
            sorted(
                {
                    *row.get("transition_event_ids", []),
                    *[item for item in source.get("left_source_event_ids", [])],
                    *[item for item in source.get("right_source_event_ids", [])],
                }
            )
        )
        cases.append(
            ConflictCase(
                case_id,
                (identity,),
                tuple(sorted({str(item.get("symbol") or "") for item in obs})),
                tuple(
                    sorted(
                        {
                            str(source.get("left_value") or ""),
                            str(source.get("right_value") or ""),
                            *[str(item.get("series") or "") for item in obs],
                        }
                        - {""}
                    )
                ),
                tuple(
                    sorted({str(item.get("isin")) for item in obs if item.get("isin")})
                ),
                tuple(
                    sorted(
                        {
                            str(item.get("security_name"))
                            for item in obs
                            if item.get("security_name")
                        }
                    )
                ),
                ("CORE_EQUITY",),
                _optional_date(source.get("overlap_start")),
                _optional_date(source.get("overlap_end")),
                tuple(
                    item
                    for item in (
                        str(boundary.get("exact_listing_date") or ""),
                        str(boundary.get("listing_lower_bound") or ""),
                    )
                    if item
                ),
                tuple(
                    item
                    for item in (
                        str(boundary.get("exact_termination_date") or ""),
                        str(boundary.get("termination_upper_bound") or ""),
                    )
                    if item
                ),
                tuple(
                    item
                    for item in (
                        str(boundary.get("first_official_checkpoint") or ""),
                        str(boundary.get("final_official_active_checkpoint") or ""),
                    )
                    if item
                ),
                tuple(
                    sorted(
                        item.get("transition_id", "")
                        for item in transitions.get(identity, [])
                    )
                ),
                tuple(
                    sorted(
                        item.get("action_id", "") for item in actions.get(identity, [])
                    )
                ),
                "Candle observations corroborate presence only and do not "
                "certify identity.",
                source_ids,
                conflict_type,
                outcome,
                confidence,
                requirement,
            )
        )
        resolutions.append(
            ConflictResolution(
                case_id,
                identity,
                outcome,
                blocking,
                not blocking,
                blocking,
                1 if same_isin else 6,
                rationale,
            )
        )
        for source_id in source_ids or ("OFFICIAL_ISIN_IDENTITY",):
            evidence.append(
                {
                    "case_id": case_id,
                    "identity_key": identity,
                    "source_id": source_id,
                    "authority_level": 1 if same_isin else 6,
                    "certifying": same_isin,
                    "purpose": "identity and interval conflict resolution",
                }
            )
    return tuple(cases), tuple(evidence), tuple(resolutions)


def resolve_gaps(rows: list[dict[str, Any]]) -> tuple[GapResolution, ...]:
    result = []
    for row in rows:
        if row.get("support_state") != "TIER_A_CORE_EQUITY":
            continue
        result.append(
            GapResolution(
                str(row["gap_id"]),
                str(row["identity_key"]),
                GapType.ARCHIVE_EVIDENCE_GAP,
                date.fromisoformat(str(row["earliest_possible_effective_date"])),
                date.fromisoformat(str(row["latest_possible_effective_date"])),
                str(row.get("known_active_on_or_before") or "UNKNOWN"),
                str(row.get("known_inactive_on_or_after") or "UNKNOWN"),
                AmbiguityEffect.MEMBERSHIP_AMBIGUITY_ONLY,
                True,
                "MEDIUM",
                "The ISIN identity is unique; membership is bounded without "
                "inventing an exact transition date.",
            )
        )
    return tuple(result)


_DISCREPANCY_RULES: dict[str, tuple[str, str, str, JoinReadiness, date | None]] = {
    "HDFC": (
        "Historical ISIN predecessor was superseded and HDFC Ltd later "
        "merged into HDFC Bank.",
        "RESOLVED_PREDECESSOR_TERMINATED",
        "Exclude stale predecessor from 2026 active parity; preserve historical joins.",
        JoinReadiness.JOIN_READY_BOUNDED_MEMBERSHIP,
        date(2023, 7, 1),
    ),
    "ASTRAL": (
        "Historical ISIN INE006I01012 was replaced by current ISIN INE006I01046.",
        "RESOLVED_ISIN_TRANSITION",
        "Use the current ISIN at the checkpoint; retain predecessor history.",
        JoinReadiness.JOIN_READY_BOUNDED_MEMBERSHIP,
        None,
    ),
    "CRISIL": (
        "Historical ISIN INE007A01017 was replaced by current ISIN INE007A01025.",
        "RESOLVED_ISIN_TRANSITION",
        "Use the current ISIN at the checkpoint; retain predecessor history.",
        JoinReadiness.JOIN_READY_BOUNDED_MEMBERSHIP,
        None,
    ),
    "COX&KINGS": (
        "Historical ISIN INE008I01018 was superseded; no stale predecessor "
        "is active in 2026.",
        "RESOLVED_STALE_PREDECESSOR",
        "Exclude stale predecessor from active parity without inferring "
        "termination from candles.",
        JoinReadiness.JOIN_READY_BOUNDED_MEMBERSHIP,
        date(2018, 10, 25),
    ),
    "AMIORG": (
        "Official symbol transition renamed AMIORG to ACUTAAS on 2025-06-02.",
        "RESOLVED_SYMBOL_TRANSITION",
        "Use ACUTAAS at the 2026 checkpoint under the same ISIN.",
        JoinReadiness.JOIN_READY_CERTIFIED,
        date(2025, 6, 2),
    ),
}


def resolve_discrepancies(
    rows: list[dict[str, Any]],
) -> tuple[DiscrepancyResolution, ...]:
    result = []
    for row in rows:
        symbol = str(row["symbol"])
        rule = _DISCREPANCY_RULES.get(symbol)
        if rule is None:
            cause = (
                "No governed named discrepancy rule or effective-dated official "
                "evidence resolves this checkpoint difference."
            )
            state = "UNRESOLVED_EXTERNAL_ERA_CHECKPOINT_DISCREPANCY"
            treatment = (
                "Retain the discrepancy, quarantine checkpoint parity, and require "
                "effective-dated official identity evidence before admission."
            )
            join = JoinReadiness.UNRESOLVED_IDENTITY
            event_date = None
        else:
            cause, state, treatment, join, event_date = rule
        evidence = tuple(str(item) for item in row.get("source_evidence", []))
        if symbol == "AMIORG":
            evidence += ("nse_symbol_change_events:AMIORG:ACUTAAS:2025-06-02",)
        result.append(
            DiscrepancyResolution(
                symbol,
                str(row["identity_key"]),
                date(2026, 7, 20),
                event_date,
                str(row["derived_interval_state"]),
                str(row["checkpoint_state"]),
                cause,
                state,
                treatment,
                join,
                False,
                evidence,
            )
        )
    return tuple(result)


def termination_boundaries(
    certifications: list[dict[str, Any]],
    boundaries: dict[str, dict[str, Any]],
    observations: dict[str, list[dict[str, Any]]],
    transitions: dict[str, list[dict[str, Any]]],
) -> tuple[TerminationBoundary, ...]:
    result = []
    for certification in certifications:
        if certification.get("support_state") != "TIER_A_CORE_EQUITY":
            continue
        identity = str(certification["identity_key"])
        boundary = boundaries[identity]
        obs = observations.get(identity, [])
        symbol = str(obs[0].get("symbol") or "") if obs else ""
        exact = _optional_date(boundary.get("exact_termination_date"))
        active = boundary.get("current_active") is True
        identity_transitions = transitions.get(identity, [])
        if exact:
            state = TerminationState.EXACT_TERMINATION
            rationale = "Exact official termination date is available."
            affects = False
        elif active:
            state = TerminationState.ACTIVE_AT_LATER_CHECKPOINT
            rationale = "Official later checkpoint confirms active state."
            affects = False
        elif identity_transitions:
            state = TerminationState.MERGER_OR_SCHEME_PREDECESSOR
            rationale = (
                "Official corporate-action evidence identifies a predecessor "
                "transition."
            )
            affects = False
        else:
            state = TerminationState.GENUINELY_UNRESOLVED_CESSATION
            rationale = "No exact official cessation evidence; last candle is not used."
            affects = True
        result.append(
            TerminationBoundary(
                identity,
                symbol,
                state,
                exact,
                _optional_date(boundary.get("termination_lower_bound")),
                _optional_date(boundary.get("termination_upper_bound")),
                affects,
                tuple(
                    sorted(
                        item.get("transition_id", "") for item in identity_transitions
                    )
                ),
                rationale,
            )
        )
    return tuple(result)


def suspension_ceiling(
    source_inventory: list[dict[str, Any]],
) -> tuple[SuspensionEvidenceBoundary, ...]:
    suspension = [
        row
        for row in source_inventory
        if "SUSPENSION" in str(row.get("evidence_type", "")).upper()
    ]
    acquired = sum(not row.get("failure_code") for row in suspension)
    failed = sum(bool(row.get("failure_code")) for row in suspension)
    return (
        SuspensionEvidenceBoundary(
            SuspensionCeiling.HISTORICAL_SUSPENSION_PARTIAL,
            tuple(sorted(str(row["source_id"]) for row in suspension)),
            acquired,
            failed,
            0,
            True,
            False,
            "Documented NSE-controlled sources do not provide a complete, "
            "effective-dated historical suspension/restoration set. The limitation "
            "is permanent until new official evidence is supplied.",
        ),
    )


def daily_contracts(rows: list[dict[str, Any]]) -> tuple[DailyActivityContract, ...]:
    return tuple(
        DailyActivityContract(
            str(row["source_family"]),
            f"{str(row['covered_from'])[:4]}-{str(row['covered_to'])[:4]}",
            str(row["format_name"]),
            str(row["inclusion_contract"]),
            int(row["zero_volume_rows"]),
            str(row["suspended_security_behavior"]),
            "Trading activity only; absence cannot certify membership, "
            "suspension, termination, or a source defect.",
            str(row["confidence"]),
            False,
            False,
            False,
            True,
            True,
            False,
        )
        for row in rows
    )


def join_population(
    certifications: list[dict[str, Any]],
    observations: dict[str, list[dict[str, Any]]],
    gaps: tuple[GapResolution, ...],
    conflicts: tuple[ConflictResolution, ...],
) -> tuple[CorporateActionJoinReadiness, ...]:
    gap_ids = {row.identity_key for row in gaps}
    blocked = {row.identity_key: row for row in conflicts if row.blocking}
    result = []
    for certification in certifications:
        if certification.get("support_state") != "TIER_A_CORE_EQUITY":
            continue
        identity = str(certification["identity_key"])
        obs = observations.get(identity, [])
        symbol = str(obs[0].get("symbol") or "") if obs else ""
        isin = str(obs[0]["isin"]) if obs and obs[0].get("isin") else None
        if identity in blocked:
            state = JoinReadiness.QUARANTINED_IDENTITY_AMBIGUITY
            reason = "Blocking identity-date conflict"
            admitted = False
        elif identity in gap_ids:
            state = JoinReadiness.JOIN_READY_BOUNDED_MEMBERSHIP
            reason = None
            admitted = True
        else:
            state = JoinReadiness.JOIN_READY_TRADABILITY_PARTIAL
            reason = None
            admitted = True
        result.append(
            CorporateActionJoinReadiness(
                identity,
                symbol,
                isin,
                state,
                identity not in blocked,
                identity in gap_ids,
                True,
                reason,
                admitted,
                "Official actions join by governed identity and date; tradability "
                "is not required for identity association.",
            )
        )
    return tuple(result)


def readiness_decision(
    joins: tuple[CorporateActionJoinReadiness, ...],
    conflicts: tuple[ConflictResolution, ...],
    discrepancies: tuple[DiscrepancyResolution, ...],
) -> ReadinessDecision:
    quarantined = sum(not row.admitted_to_certified_join for row in joins)
    blocking = sum(row.blocking for row in conflicts)
    unexplained = sum(row.final_state.startswith("UNRESOLVED") for row in discrepancies)
    if blocking or unexplained:
        state = FoundationReadiness.NOT_READY_FOR_HTR_010B
    elif quarantined:
        state = FoundationReadiness.CONDITIONALLY_READY_FOR_HTR_010B
    else:
        state = FoundationReadiness.READY_FOR_HTR_010B
    blockers = tuple(
        item
        for item in (
            f"{blocking} blocking identity-date conflicts" if blocking else "",
            f"{unexplained} unexplained 2026 discrepancies" if unexplained else "",
        )
        if item
    )
    return ReadinessDecision(
        state,
        blockers,
        quarantined,
        sum(row.admitted_to_certified_join for row in joins),
        len(joins),
        "Quarantined identities remain preserved but are excluded from "
        "certified joins.",
        "HTR-010B full-market corporate-action completion",
        "Identity joins are unique for the admitted Tier A population; bounded "
        "membership and partial tradability remain explicit evidence states.",
    )


def _records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("records", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError(f"expected records: {path}")
    return rows


def _object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object: {path}")
    return payload


def _optional_date(value: Any) -> date | None:
    return date.fromisoformat(str(value)) if value else None


def _jsonable(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _jsonable(getattr(value, key)) for key in value.__dataclass_fields__
        }
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


__all__ = [
    "TierAFoundationReadinessEngine",
    "conflict_cases",
    "daily_contracts",
    "join_population",
    "readiness_decision",
    "resolve_discrepancies",
    "resolve_gaps",
    "suspension_ceiling",
    "termination_boundaries",
]
