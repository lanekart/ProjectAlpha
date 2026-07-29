"""HTR-009B corporate-action, price-basis, and continuity certification."""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, cast

import duckdb

from alpha.historical_truth.corporate_action_price_models import (
    HTR009B_CONTRACT_VERSION,
    PRODUCTION_INFLUENCE,
    ActionAdmissionState,
    AdjustedCandleSummary,
    AdjustmentDirection,
    AdjustmentFactor,
    AdjustmentFactorState,
    CandidateCorporateActionExposure,
    CandidateExposureSummary,
    CertificationState,
    ContaminationState,
    ContinuitySummary,
    ContinuityType,
    CorporateActionCertification,
    CorporateActionEvent,
    CorporateActionPriceReport,
    CorporateActionRejection,
    CorporateActionSourceRecord,
    CorporateActionType,
    CoverageCutoffs,
    EventSummary,
    EvidenceConfidence,
    FactorSummary,
    FailureCode,
    IdentityTransition,
    IdentityTransitionSummary,
    IndicatorContamination,
    PriceBasisInterval,
    PriceBasisState,
    PriceBasisSummary,
    PriceDiscontinuity,
    SourceStatus,
    SourceSummary,
    StopContamination,
    stable_id,
)
from alpha.historical_truth.corporate_action_price_sources import (
    OfficialCorporateActionStore,
    default_corporate_action_sources,
    reject_conflicting_actions,
)
from alpha.historical_truth.official_corporate_action_supplements import (
    apply_official_corporate_action_supplements,
    official_corporate_action_supplements,
)

CALCULATION_VERSION = "htr009b-adjustment-v1"
MATERIAL_ACTIONS = frozenset(
    {
        CorporateActionType.SPLIT,
        CorporateActionType.BONUS,
        CorporateActionType.RIGHTS,
        CorporateActionType.FACE_VALUE_CHANGE,
        CorporateActionType.CAPITAL_REDUCTION,
    }
)
TRANSITION_ACTIONS = frozenset(
    {
        CorporateActionType.MERGER,
        CorporateActionType.DEMERGER,
        CorporateActionType.AMALGAMATION,
        CorporateActionType.SCHEME_OF_ARRANGEMENT,
        CorporateActionType.SPIN_OFF,
        CorporateActionType.SECURITY_REPLACEMENT,
        CorporateActionType.ISIN_CHANGE,
        CorporateActionType.SYMBOL_CHANGE,
        CorporateActionType.RELISTING,
        CorporateActionType.SHARE_CANCELLATION,
    }
)
KNOWN_FACTOR_STATES = frozenset(
    {
        AdjustmentFactorState.KNOWN_OFFICIAL,
        AdjustmentFactorState.DERIVED_FROM_OFFICIAL_TERMS,
    }
)


class AdjustmentFactorEngine:
    """Derive transparent factors from official terms without guessing."""

    def derive(
        self,
        action: CorporateActionEvent,
        *,
        reference_price: float | None = None,
        direction: AdjustmentDirection = AdjustmentDirection.BACKWARD,
    ) -> AdjustmentFactor:
        price_factor = action.adjustment_factor
        state = action.adjustment_factor_state
        explanation = "Official action does not require price-only adjustment."
        quantity_factor: float | None = None
        if state is AdjustmentFactorState.NOT_REQUIRED and not (
            action.action_type is CorporateActionType.CAPITAL_REDUCTION
            and price_factor is not None
        ):
            price_factor = None
            explanation = (
                "Official event is governed as a non-multiplicative equity-price "
                "transition."
            )
        elif action.action_type in {
            CorporateActionType.SPLIT,
            CorporateActionType.FACE_VALUE_CHANGE,
        }:
            if price_factor is not None and price_factor > 0:
                quantity_factor = 1.0 / price_factor
                explanation = (
                    "Face-value terms determine reciprocal price/quantity factors."
                )
        elif action.action_type is CorporateActionType.BONUS:
            if price_factor is not None and price_factor > 0:
                quantity_factor = 1.0 / price_factor
                explanation = "Bonus ratio determines theoretical ex-bonus factor."
        elif action.action_type is CorporateActionType.RIGHTS:
            derived = self._rights_factor(action, reference_price)
            if derived is None:
                price_factor = None
                quantity_factor = None
                state = AdjustmentFactorState.UNKNOWN
                explanation = (
                    "Rights factor requires ratio, rights price, and pre-rights "
                    "reference close."
                )
            else:
                price_factor, quantity_factor = derived
                state = AdjustmentFactorState.DERIVED_FROM_OFFICIAL_TERMS
                explanation = "TERP derived from official rights terms and prior close."
        elif action.action_type is CorporateActionType.CAPITAL_REDUCTION:
            old_quantity = action.old_quantity
            new_quantity = action.new_quantity
            if (
                price_factor is not None
                and old_quantity is not None
                and new_quantity is not None
                and old_quantity > 0
                and new_quantity > 0
            ):
                quantity_factor = new_quantity / old_quantity
                explanation = (
                    "Official capital-reduction terms determine the price factor "
                    "and share-count quantity factor."
                )
            else:
                state = AdjustmentFactorState.NOT_REQUIRED
                explanation = (
                    "Capital reduction is retained as a governed "
                    "non-multiplicative transition."
                )
        elif action.action_type in TRANSITION_ACTIONS:
            price_factor = None
            quantity_factor = None
            state = AdjustmentFactorState.NOT_REQUIRED
            explanation = (
                "Reorganisation is a governed non-multiplicative identity transition."
            )
        elif action.action_type is CorporateActionType.DIVIDEND:
            price_factor = None
            quantity_factor = None
            state = AdjustmentFactorState.NOT_REQUIRED
            explanation = (
                "Dividend retained for total-return analysis; technical price series "
                "is not adjusted by policy."
            )
        if price_factor is not None and (
            not math.isfinite(price_factor) or price_factor <= 0
        ):
            price_factor = None
            quantity_factor = None
            state = AdjustmentFactorState.INVALID
            explanation = "Derived factor is non-positive or non-finite."
        if direction is AdjustmentDirection.FORWARD and price_factor is not None:
            price_factor = 1.0 / price_factor
            quantity_factor = (
                1.0 / quantity_factor
                if quantity_factor is not None and quantity_factor > 0
                else None
            )
            explanation = f"Forward basis: {explanation}"
        return AdjustmentFactor(
            stable_id(action.action_id, direction.value, CALCULATION_VERSION),
            action.action_id,
            action.governed_identity_id or f"nse:unresolved:{action.symbol}",
            action.effective_date,
            direction,
            price_factor,
            quantity_factor,
            state,
            action.source_id,
            CALCULATION_VERSION,
            reference_price,
            explanation,
        )

    @staticmethod
    def _rights_factor(
        action: CorporateActionEvent,
        reference_price: float | None,
    ) -> tuple[float, float] | None:
        new = action.ratio_numerator
        old = action.ratio_denominator
        rights_price = action.rights_price
        if (
            new is None
            or old is None
            or rights_price is None
            or reference_price is None
            or new <= 0
            or old <= 0
            or rights_price < 0
            or reference_price <= 0
        ):
            return None
        terp = ((old * reference_price) + (new * rights_price)) / (old + new)
        return terp / reference_price, (old + new) / old

    @staticmethod
    def cumulative(
        factors: Sequence[AdjustmentFactor],
    ) -> tuple[float, float]:
        price = 1.0
        quantity = 1.0
        for factor in sorted(factors, key=lambda item: item.effective_date):
            if factor.price_factor is None or factor.quantity_factor is None:
                continue
            price *= factor.price_factor
            quantity *= factor.quantity_factor
        return price, quantity


class CorporateActionPriceCertificationEngine:
    """Build diagnostic-only governed action and adjusted-price evidence."""

    def __init__(self, database_path: Path, root: Path) -> None:
        self.database_path = database_path
        self.root = root
        self.store = OfficialCorporateActionStore(root)
        self.factor_engine = AdjustmentFactorEngine()

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
        action_types: tuple[CorporateActionType, ...] = (),
        price_basis_states: tuple[PriceBasisState, ...] = (),
        only_unresolved: bool = False,
        only_candidate_exposed: bool = False,
    ) -> CorporateActionPriceReport:
        if refresh_sources and verify_only:
            raise ValueError("refresh_sources and verify_only are mutually exclusive")
        calendar_end = _calendar_cutoff(calendar_report)
        canonical_start, canonical_end, raw_count = self._canonical_coverage()
        if canonical_end is None or canonical_start is None:
            raise ValueError("canonical daily_candle table is empty")
        source_end = requested_end or canonical_end
        if source_end < start_date:
            raise ValueError("end date must be on or after start date")
        specs = default_corporate_action_sources(start_date, source_end)
        parsed_sources = (
            self.store.verify_or_missing(specs)
            if verify_only or not refresh_sources
            else self.store.acquire(specs)
        )
        actions = tuple(
            action
            for source in parsed_sources
            for action in source.actions
            if start_date <= action.ex_date <= source_end
        )
        actions, conflict_rejections = reject_conflicting_actions(actions)
        verified_supplements, _ = official_corporate_action_supplements(self.root)
        actions, _, _ = apply_official_corporate_action_supplements(
            actions,
            verified_supplements,
        )
        rejected = tuple(
            sorted(
                (
                    *(item for source in parsed_sources for item in source.rejected),
                    *conflict_rejections,
                    *self._rejected_actions(actions),
                ),
                key=lambda item: (
                    item.source_id,
                    item.failure_code.value,
                    item.row_number or 0,
                ),
            )
        )
        actions = self._resolve_factor_states(actions)
        evidence_end = max(
            (
                item.covered_end
                for item in (source.inventory for source in parsed_sources)
                if item.status in {SourceStatus.ACQUIRED, SourceStatus.REUSED}
            ),
            default=None,
        )
        transition_evidence_end = self._transition_evidence_cutoff(actions)
        snapshot_end = _snapshot_cutoff(self.root / "snapshots")
        common_dates = [
            calendar_end,
            canonical_end,
            evidence_end,
            transition_evidence_end,
        ]
        common = min(item for item in common_dates if item is not None)
        audit_end = min(source_end, common)
        if audit_end < start_date:
            raise ValueError("no common auditable date range")
        factors = self._factors(actions, audit_end)
        intervals, adjusted = self._price_basis(
            actions,
            factors,
            start_date,
            audit_end,
        )
        discontinuities = self._continuity(actions, factors, audit_end)
        indicator_contamination = self._indicator_contamination(discontinuities)
        transitions = self._identity_transitions(actions, audit_end)
        candidate_exposure, candidate_summary = self._candidate_exposure(
            actions,
            intervals,
        )
        stop_contamination = self._stop_contamination(candidate_exposure)
        audited_actions = tuple(item for item in actions if item.ex_date <= audit_end)
        ytd_actions = tuple(item for item in actions if item.ex_date.year == 2026)
        cutoffs = CoverageCutoffs(
            calendar_end,
            canonical_end,
            snapshot_end,
            evidence_end,
            transition_evidence_end,
            audit_end,
            len(ytd_actions),
            sum(
                item.admission_state is ActionAdmissionState.ADMITTED
                for item in ytd_actions
            ),
            bool(
                calendar_end
                and canonical_end
                and snapshot_end
                and evidence_end
                and transition_evidence_end
                and min(
                    calendar_end,
                    canonical_end,
                    snapshot_end,
                    evidence_end,
                    transition_evidence_end,
                ).year
                >= 2026
            ),
            None,
        )
        if not cutoffs.ytd_2026_certified:
            cutoffs = replace(
                cutoffs,
                ytd_2026_blocker=(
                    "CALENDAR_IDENTITY_SNAPSHOT_AND_CORPORATE_ACTION_CUTOFFS_"
                    "DO_NOT_SHARE_A_2026_DATE"
                ),
            )
        source_summary = self._source_summary(parsed_sources)
        event_summary = self._event_summary(audited_actions, rejected)
        factor_summary = self._factor_summary(factors)
        price_basis_summary = self._price_basis_summary(
            raw_count,
            intervals,
            adjusted,
        )
        continuity_summary = self._continuity_summary(
            discontinuities,
            indicator_contamination,
        )
        transition_summary = self._transition_summary(transitions)
        certification = self._certification(
            source_summary,
            audited_actions,
            factors,
            intervals,
            transitions,
            cutoffs,
        )
        source_inventory = (
            *(source.inventory for source in parsed_sources),
            self._existing_inventory(start_date, audit_end),
        )
        report = CorporateActionPriceReport(
            HTR009B_CONTRACT_VERSION,
            PRODUCTION_INFLUENCE,
            str(self.database_path),
            start_date,
            audit_end,
            cutoffs,
            source_inventory,
            rejected,
            _filter_actions(actions, symbols, isins, years, action_types),
            tuple(item for source in parsed_sources for item in source.lineage),
            _filter_factors(factors, isins, years),
            _filter_intervals(
                intervals,
                isins,
                years,
                price_basis_states,
                only_unresolved,
            ),
            tuple(
                item for item in adjusted if _identity_matches(item.identity_key, isins)
            ),
            tuple(
                item
                for item in discontinuities
                if _record_matches(item.symbol, item.identity_key, symbols, isins)
            ),
            tuple(
                item
                for item in indicator_contamination
                if _record_matches(item.symbol, item.identity_key, symbols, isins)
            ),
            stop_contamination,
            tuple(
                item
                for item in transitions
                if _transition_matches(item, symbols, isins)
            ),
            candidate_exposure
            if not only_candidate_exposed
            else tuple(
                item
                for item in candidate_exposure
                if item.corporate_action_risk
                not in {ContaminationState.NOT_EXPOSED, ContaminationState.UNKNOWN}
            ),
            source_summary,
            event_summary,
            factor_summary,
            price_basis_summary,
            continuity_summary,
            transition_summary,
            candidate_summary,
            certification,
            "",
        )
        report = replace(report, report_sha256=report.calculated_sha256())
        filtered_request = bool(
            symbols
            or isins
            or years
            or action_types
            or price_basis_states
            or only_unresolved
            or only_candidate_exposed
        )
        if not verify_only and not filtered_request:
            self._persist(report)
        return report

    def _existing_inventory(
        self,
        start_date: date,
        end_date: date,
    ) -> CorporateActionSourceRecord:
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            tables = {item[0] for item in connection.execute("SHOW TABLES").fetchall()}
            row = (
                connection.execute("SELECT COUNT(*) FROM corporate_action").fetchone()
                if "corporate_action" in tables
                else None
            )
            row_count = int(row[0]) if row else 0
        return CorporateActionSourceRecord(
            "existing_canonical_corporate_action_table",
            "EXISTING_CORPORATE_ACTION_INVENTORY",
            f"internal:{self.database_path}#corporate_action",
            False,
            "canonical.corporate_action",
            None,
            None,
            "application/x-duckdb-table",
            (),
            0,
            None,
            start_date,
            end_date,
            "schema_inventory_v1",
            str(self.database_path),
            row_count,
            row_count,
            row_count,
            0,
            SourceStatus.INVENTORIED,
            "PREEXISTING_SCHEMA_INSPECTED",
            consumer_usage="NO_CONSUMER; TABLE_EMPTY" if row_count == 0 else "UNKNOWN",
            price_basis="UNKNOWN",
            known_limitations=(
                "Schema existed but contained no admitted corporate-action evidence."
                if row_count == 0
                else (
                    "Legacy rows require source-lineage and price-basis reconciliation."
                )
            ),
        )

    def _canonical_coverage(self) -> tuple[date | None, date | None, int]:
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            row = connection.execute(
                "SELECT MIN(trading_date), MAX(trading_date), COUNT(*) "
                "FROM daily_candle"
            ).fetchone()
        if row is None:
            return None, None, 0
        return row[0], row[1], int(row[2])

    @staticmethod
    def _rejected_actions(
        actions: Sequence[CorporateActionEvent],
    ) -> tuple[CorporateActionRejection, ...]:
        return tuple(
            CorporateActionRejection(
                item.source_id,
                item.source_location,
                (
                    FailureCode.IDENTITY_UNRESOLVED
                    if item.governed_identity_id is None
                    else FailureCode.UNKNOWN_FAILURE
                ),
                (
                    "identity is unresolved; event retained provisionally"
                    if item.governed_identity_id is None
                    else "event purpose is not a governed corporate action"
                ),
                raw_identifier=item.action_id,
            )
            for item in actions
            if item.admission_state is not ActionAdmissionState.ADMITTED
        )

    def _resolve_factor_states(
        self,
        actions: Sequence[CorporateActionEvent],
    ) -> tuple[CorporateActionEvent, ...]:
        results: list[CorporateActionEvent] = []
        for action in actions:
            if action.action_type is not CorporateActionType.RIGHTS:
                results.append(action)
                continue
            reference = self._prior_close(action)
            factor = self.factor_engine.derive(action, reference_price=reference)
            results.append(
                replace(
                    action,
                    adjustment_factor_state=factor.state,
                    adjustment_factor=factor.price_factor,
                )
            )
        return tuple(results)

    def _prior_close(self, action: CorporateActionEvent) -> float | None:
        if not action.isin:
            return None
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            rows = connection.execute(
                """
                WITH latest AS (
                    SELECT MAX(trading_date) AS trading_date
                    FROM daily_candle
                    WHERE trading_date < ?
                      AND UPPER(TRIM(isin)) = UPPER(TRIM(?))
                )
                SELECT c.close_price
                FROM daily_candle c
                JOIN latest l USING (trading_date)
                WHERE UPPER(TRIM(c.isin)) = UPPER(TRIM(?))
                  AND c.close_price > 0
                ORDER BY c.exchange, c.symbol, c.series, c.source_sha256
                """,
                [
                    action.ex_date,
                    action.isin,
                    action.isin,
                ],
            ).fetchall()
            if len(rows) == 1:
                return float(rows[0][0])
            security_events_available = connection.execute(
                """
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = 'main' AND table_name = 'security_event'
                """
            ).fetchone()
            if not security_events_available or not security_events_available[0]:
                return None
            rows = connection.execute(
                """
                WITH candidate_date AS (
                    SELECT MAX(trading_date) AS trading_date
                    FROM daily_candle
                    WHERE trading_date < ?
                      AND UPPER(TRIM(symbol)) = UPPER(TRIM(?))
                      AND UPPER(TRIM(series)) = UPPER(TRIM(?))
                ),
                candidate AS (
                    SELECT c.trading_date, c.isin, c.close_price, c.source_sha256
                    FROM daily_candle c
                    JOIN candidate_date d USING (trading_date)
                    WHERE UPPER(TRIM(c.symbol)) = UPPER(TRIM(?))
                      AND UPPER(TRIM(c.series)) = UPPER(TRIM(?))
                      AND c.isin IS NOT NULL AND TRIM(c.isin) <> ''
                      AND c.close_price > 0
                      AND c.source_sha256 IS NOT NULL
                      AND TRIM(c.source_sha256) <> ''
                ),
                governed AS (
                    SELECT c.close_price, c.isin
                    FROM candidate c
                    WHERE EXISTS (
                        SELECT 1
                        FROM security_event e
                        WHERE e.admission_state = 'ADMITTED'
                          AND e.confidence_state = 'HIGH'
                          AND e.effective_date <= c.trading_date
                          AND UPPER(TRIM(e.new_symbol)) = UPPER(TRIM(?))
                          AND UPPER(TRIM(e.new_series)) = UPPER(TRIM(?))
                          AND UPPER(TRIM(e.new_isin)) = UPPER(TRIM(c.isin))
                    )
                )
                SELECT close_price
                FROM governed
                WHERE (
                    SELECT COUNT(DISTINCT UPPER(TRIM(isin))) FROM governed
                ) = 1
                """,
                [
                    action.ex_date,
                    action.symbol,
                    action.series,
                    action.symbol,
                    action.series,
                    action.symbol,
                    action.series,
                ],
            ).fetchall()
        if len(rows) != 1:
            return None
        return float(rows[0][0])

    def _factors(
        self,
        actions: Sequence[CorporateActionEvent],
        audit_end: date,
    ) -> tuple[AdjustmentFactor, ...]:
        factors = [
            self.factor_engine.derive(
                item,
                reference_price=self._prior_close(item)
                if item.action_type is CorporateActionType.RIGHTS
                else None,
            )
            for item in actions
            if item.ex_date <= audit_end
            and item.admission_state is ActionAdmissionState.ADMITTED
        ]
        return tuple(
            sorted(factors, key=lambda item: (item.effective_date, item.factor_id))
        )

    def _price_basis(
        self,
        actions: Sequence[CorporateActionEvent],
        factors: Sequence[AdjustmentFactor],
        start_date: date,
        end_date: date,
    ) -> tuple[tuple[PriceBasisInterval, ...], tuple[AdjustedCandleSummary, ...]]:
        factors_by_identity: dict[str, list[AdjustmentFactor]] = defaultdict(list)
        actions_by_identity: dict[str, list[CorporateActionEvent]] = defaultdict(list)
        for factor in factors:
            factors_by_identity[factor.identity_key].append(factor)
        for action in actions:
            if action.governed_identity_id:
                actions_by_identity[action.governed_identity_id].append(action)
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            rows = connection.execute(
                """
                SELECT CASE WHEN isin IS NOT NULL
                            THEN 'nse:isin:' || UPPER(TRIM(isin))
                            ELSE 'nse:unresolved:' || UPPER(symbol) || ':' ||
                                 UPPER(series)
                       END AS identity_key,
                       MIN(trading_date), MAX(trading_date), COUNT(*)
                FROM daily_candle
                WHERE trading_date BETWEEN ? AND ?
                GROUP BY identity_key
                ORDER BY identity_key
                """,
                [start_date, end_date],
            ).fetchall()
        intervals: list[PriceBasisInterval] = []
        summaries: list[AdjustedCandleSummary] = []
        for identity, lower, upper, count in rows:
            identity_key = str(identity)
            identity_factors = factors_by_identity.get(identity_key, [])
            identity_actions = actions_by_identity.get(identity_key, [])
            known = [
                item for item in identity_factors if item.state in KNOWN_FACTOR_STATES
            ]
            unknown = [
                item
                for item in identity_factors
                if item.state
                in {
                    AdjustmentFactorState.UNKNOWN,
                    AdjustmentFactorState.AMBIGUOUS,
                    AdjustmentFactorState.INVALID,
                    AdjustmentFactorState.CONFLICTING,
                }
            ]
            transition = any(
                item.action_type in TRANSITION_ACTIONS for item in identity_actions
            )
            state, issues = _basis_state(known, unknown, transition)
            adjusted_rows = self._adjusted_row_count(identity_key, known, lower, upper)
            action_ids = tuple(sorted(item.action_id for item in identity_actions))
            intervals.append(
                PriceBasisInterval(
                    identity_key,
                    lower,
                    upper,
                    state,
                    action_ids,
                    len(known),
                    len(unknown),
                    int(count),
                    adjusted_rows,
                    issues,
                )
            )
            if known:
                price, quantity = self.factor_engine.cumulative(known)
                summaries.append(
                    AdjustedCandleSummary(
                        identity_key,
                        int(count),
                        adjusted_rows,
                        lower,
                        upper,
                        price,
                        quantity,
                        tuple(sorted(item.action_id for item in known)),
                        state,
                    )
                )
        return tuple(intervals), tuple(summaries)

    def _adjusted_row_count(
        self,
        identity_key: str,
        factors: Sequence[AdjustmentFactor],
        lower: date,
        upper: date,
    ) -> int:
        effective_dates = [
            item.effective_date
            for item in factors
            if item.price_factor is not None and item.effective_date > lower
        ]
        if not effective_dates:
            return 0
        latest = max(effective_dates)
        isin = _isin_from_identity(identity_key)
        if isin is None:
            return 0
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM daily_candle WHERE UPPER(isin) = ? "
                "AND trading_date BETWEEN ? AND ? AND trading_date < ?",
                [isin, lower, upper, latest],
            ).fetchone()
        return int(row[0]) if row else 0

    def _continuity(
        self,
        actions: Sequence[CorporateActionEvent],
        factors: Sequence[AdjustmentFactor],
        audit_end: date,
    ) -> tuple[PriceDiscontinuity, ...]:
        factor_by_action = {item.action_id: item for item in factors}
        records: list[PriceDiscontinuity] = []
        for action in actions:
            if (
                action.action_type not in MATERIAL_ACTIONS
                or action.ex_date > audit_end
                or action.admission_state is not ActionAdmissionState.ADMITTED
            ):
                continue
            factor = factor_by_action.get(action.action_id)
            bars = self._event_bars(action)
            previous = bars[:-1]
            current = bars[-1] if bars else None
            prior = previous[-1] if previous else None
            previous_close = float(prior[4]) if prior else None
            action_open = float(current[1]) if current else None
            action_close = float(current[4]) if current else None
            raw_gap = _pct(action_open, previous_close)
            adjusted_reference = (
                previous_close * factor.price_factor
                if previous_close is not None
                and factor is not None
                and factor.price_factor is not None
                else None
            )
            adjusted_gap = _pct(action_open, adjusted_reference)
            atr = _atr(previous)
            raw_gap_atr = (
                abs(action_open - previous_close) / atr
                if action_open is not None
                and previous_close is not None
                and atr is not None
                and atr > 0
                else None
            )
            adjusted_gap_atr = (
                abs(action_open - adjusted_reference) / (atr * factor.price_factor)
                if action_open is not None
                and adjusted_reference is not None
                and atr is not None
                and atr > 0
                and factor is not None
                and factor.price_factor is not None
                else None
            )
            volume_change = (
                _pct(float(current[5]), float(prior[5])) if current and prior else None
            )
            raw_discontinuous = raw_gap is not None and abs(raw_gap) >= 0.15
            adjusted_continuous = adjusted_gap is not None and abs(adjusted_gap) < 0.15
            records.append(
                PriceDiscontinuity(
                    action.action_id,
                    action.governed_identity_id or f"nse:unresolved:{action.symbol}",
                    action.symbol,
                    action.action_type,
                    action.ex_date,
                    cast(date | None, prior[0] if prior else None),
                    cast(date | None, current[0] if current else None),
                    previous_close,
                    action_open,
                    action_close,
                    raw_gap,
                    adjusted_gap,
                    atr,
                    raw_gap_atr,
                    adjusted_gap_atr,
                    volume_change,
                    bool(raw_discontinuous and raw_gap is not None and raw_gap > 0),
                    bool(raw_discontinuous and raw_gap is not None and raw_gap < 0),
                    bool(raw_discontinuous and adjusted_continuous),
                    () if current and prior else ("INSUFFICIENT_CANDLE_CONTEXT",),
                )
            )
        return tuple(records)

    def _event_bars(self, action: CorporateActionEvent) -> list[tuple[Any, ...]]:
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            prior = connection.execute(
                """
                SELECT trading_date, open_price, high_price, low_price, close_price,
                       volume
                FROM daily_candle
                WHERE trading_date < ? AND UPPER(symbol) = ? AND UPPER(series) = ?
                  AND (? IS NULL OR UPPER(isin) = ?)
                ORDER BY trading_date DESC LIMIT 15
                """,
                [
                    action.ex_date,
                    action.symbol,
                    action.series,
                    action.isin,
                    action.isin,
                ],
            ).fetchall()
            current = connection.execute(
                """
                SELECT trading_date, open_price, high_price, low_price, close_price,
                       volume
                FROM daily_candle
                WHERE trading_date >= ? AND UPPER(symbol) = ? AND UPPER(series) = ?
                  AND (? IS NULL OR UPPER(isin) = ?)
                ORDER BY trading_date LIMIT 1
                """,
                [
                    action.ex_date,
                    action.symbol,
                    action.series,
                    action.isin,
                    action.isin,
                ],
            ).fetchone()
        return [*reversed(prior), *([current] if current else [])]

    @staticmethod
    def _indicator_contamination(
        discontinuities: Sequence[PriceDiscontinuity],
    ) -> tuple[IndicatorContamination, ...]:
        records: list[IndicatorContamination] = []
        for item in discontinuities:
            exposed = item.false_breakout_risk or item.false_breakdown_risk
            state = (
                ContaminationState.EXPOSED_ADJUSTED
                if exposed and item.continuity_restored
                else ContaminationState.EXPOSED_UNADJUSTED
                if exposed
                else ContaminationState.NOT_EXPOSED
            )
            divergence = (
                item.raw_gap_pct - item.theoretical_adjusted_gap_pct
                if item.raw_gap_pct is not None
                and item.theoretical_adjusted_gap_pct is not None
                else None
            )
            records.append(
                IndicatorContamination(
                    item.action_id,
                    item.identity_key,
                    item.symbol,
                    item.ex_date,
                    state,
                    state,
                    state,
                    state,
                    item.false_breakout_risk,
                    item.false_breakdown_risk,
                    divergence,
                    (
                        "Raw discontinuity crosses the 15% audit threshold; "
                        "moving averages, ATR, Fibonacci and support/resistance "
                        "may be distorted."
                        if exposed
                        else "No material raw discontinuity detected at the action."
                    ),
                )
            )
        return tuple(records)

    def _identity_transitions(
        self,
        actions: Sequence[CorporateActionEvent],
        audit_end: date,
    ) -> tuple[IdentityTransition, ...]:
        records: list[IdentityTransition] = []
        for item in actions:
            if item.action_type not in TRANSITION_ACTIONS or item.ex_date > audit_end:
                continue
            successor = item.successor_identity
            resolved = bool(item.predecessor_identity and successor)
            continuity = (
                ContinuityType.SAME_IDENTITY
                if resolved and item.predecessor_identity == successor
                else ContinuityType.PREDECESSOR_SUCCESSOR
                if resolved
                else ContinuityType.MULTIPLE_SUCCESSORS
                if item.action_type
                in {CorporateActionType.DEMERGER, CorporateActionType.SPIN_OFF}
                else ContinuityType.UNRESOLVED
            )
            records.append(
                IdentityTransition(
                    stable_id(item.action_id, "identity-transition"),
                    item.predecessor_identity,
                    successor,
                    item.symbol,
                    None,
                    item.isin,
                    None,
                    item.action_type,
                    item.effective_date,
                    (
                        f"{item.ratio_numerator:g}:{item.ratio_denominator:g}"
                        if item.ratio_numerator is not None
                        and item.ratio_denominator is not None
                        else None
                    ),
                    continuity,
                    resolved,
                    resolved and continuity is ContinuityType.SAME_IDENTITY,
                    continuity is not ContinuityType.SAME_IDENTITY,
                    item.source_location,
                    EvidenceConfidence.HIGH if resolved else EvidenceConfidence.LOW,
                    () if resolved else ("SUCCESSOR_IDENTITY_NOT_IN_SOURCE",),
                )
            )
        return tuple(records)

    @staticmethod
    def attribute_candidate(
        candidate: Mapping[str, Any],
        actions: Sequence[CorporateActionEvent],
        *,
        lookback_days: int = 200,
    ) -> CandidateCorporateActionExposure:
        candidate_date = cast(date, candidate["date"])
        identity = cast(str | None, candidate.get("identity_key"))
        symbol = cast(str | None, candidate.get("symbol"))
        visible = [
            item
            for item in actions
            if item.ex_date <= candidate_date
            and (candidate_date - item.ex_date).days <= lookback_days
            and (
                (identity and item.governed_identity_id == identity)
                or (symbol and item.symbol == symbol.upper())
            )
        ]
        action = max(visible, key=lambda item: item.ex_date, default=None)
        risk = (
            ContaminationState.NOT_EXPOSED
            if action is None
            else ContaminationState.EXPOSED_ADJUSTED
            if action.adjustment_factor_state in KNOWN_FACTOR_STATES
            else ContaminationState.EXPOSED_UNKNOWN_FACTOR
        )
        return CandidateCorporateActionExposure(
            str(candidate.get("candidate_id") or stable_id(symbol, candidate_date)),
            identity,
            symbol,
            candidate_date,
            cast(str | None, candidate.get("setup")),
            str(candidate.get("verdict") or "UNKNOWN"),
            1,
            action is not None,
            action.action_type if action else None,
            PriceBasisState.BACKWARD_ADJUSTED
            if risk is ContaminationState.EXPOSED_ADJUSTED
            else PriceBasisState.ADJUSTMENT_FACTOR_UNKNOWN
            if risk is ContaminationState.EXPOSED_UNKNOWN_FACTOR
            else PriceBasisState.NO_ADJUSTMENT_REQUIRED,
            risk,
            ContinuityType.UNRESOLVED
            if action and action.action_type in TRANSITION_ACTIONS
            else ContinuityType.SAME_IDENTITY,
            action.adjustment_factor_state
            if action
            else AdjustmentFactorState.NOT_REQUIRED,
            None,
            risk,
            risk,
            risk,
            risk,
            "POINT_IN_TIME_LINKED",
        )

    def _candidate_exposure(
        self,
        actions: Sequence[CorporateActionEvent],
        intervals: Sequence[PriceBasisInterval],
    ) -> tuple[
        tuple[CandidateCorporateActionExposure, ...],
        CandidateExposureSummary,
    ]:
        del actions, intervals
        path = Path(
            "artifacts/htr009a2_event_sourced_universe/htr009a2_candidate_exposure.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        rows = payload.get("records", []) if isinstance(payload, dict) else []
        totals = {
            key: sum(int(item.get(key, 0)) for item in rows)
            for key in (
                "technical_candidates",
                "watchlist_candidates",
                "buy_candidates",
                "strong_buy_candidates",
                "approvals",
            )
        }
        records = tuple(
            CandidateCorporateActionExposure(
                f"BASELINE_AGGREGATE_{verdict}",
                None,
                None,
                None,
                None,
                verdict,
                count,
                None,
                None,
                PriceBasisState.RAW_UNADJUSTED,
                ContaminationState.LINKAGE_UNAVAILABLE,
                ContinuityType.UNRESOLVED,
                AdjustmentFactorState.UNKNOWN,
                None,
                ContaminationState.LINKAGE_UNAVAILABLE,
                ContaminationState.LINKAGE_UNAVAILABLE,
                ContaminationState.LINKAGE_UNAVAILABLE,
                ContaminationState.LINKAGE_UNAVAILABLE,
                "BASELINE_TOTALS_NOT_IDENTITY_DATE_LINKABLE",
            )
            for verdict, count in (
                ("TECHNICAL", totals["technical_candidates"]),
                ("WATCHLIST", totals["watchlist_candidates"]),
                ("BUY", totals["buy_candidates"]),
                ("STRONG_BUY", totals["strong_buy_candidates"]),
                ("APPROVAL", totals["approvals"]),
            )
        )
        summary = CandidateExposureSummary(
            totals["technical_candidates"],
            totals["watchlist_candidates"],
            totals["buy_candidates"],
            totals["strong_buy_candidates"],
            totals["approvals"],
            0,
            0,
            0,
            0,
            False,
        )
        return records, summary

    @staticmethod
    def _stop_contamination(
        exposure: Sequence[CandidateCorporateActionExposure],
    ) -> tuple[StopContamination, ...]:
        return tuple(
            StopContamination(
                item.candidate_id,
                item.identity_key,
                item.symbol,
                item.candidate_date,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                False,
                False,
                False,
                False,
                ContaminationState.LINKAGE_UNAVAILABLE,
                "Saved benchmark totals lack candidate identity/date and cannot "
                "support a stop-policy counterfactual.",
            )
            for item in exposure
            if item.candidate_count > 0
        )

    @staticmethod
    def _source_summary(parsed_sources: Sequence[Any]) -> SourceSummary:
        inventories = [item.inventory for item in parsed_sources]
        covered = {
            item.covered_start.year
            for item in inventories
            if item.status in {SourceStatus.ACQUIRED, SourceStatus.REUSED}
        }
        attempted_years = {item.covered_start.year for item in inventories}
        return SourceSummary(
            len(inventories),
            sum(item.status is SourceStatus.ACQUIRED for item in inventories),
            sum(item.status is SourceStatus.REUSED for item in inventories),
            sum(item.status is SourceStatus.FAILED for item in inventories),
            sum(item.status is SourceStatus.REJECTED for item in inventories),
            tuple(sorted(attempted_years - covered)),
        )

    @staticmethod
    def _event_summary(
        actions: Sequence[CorporateActionEvent],
        rejected: Sequence[CorporateActionRejection],
    ) -> EventSummary:
        counts = Counter(item.action_type.value for item in actions)
        return EventSummary(
            len(actions),
            sum(
                item.admission_state is ActionAdmissionState.ADMITTED
                for item in actions
            ),
            len(rejected),
            sum(
                item.admission_state is ActionAdmissionState.CONFLICTING
                for item in actions
            ),
            tuple(sorted(counts.items())),
        )

    @staticmethod
    def _factor_summary(factors: Sequence[AdjustmentFactor]) -> FactorSummary:
        counts = Counter(item.state for item in factors)
        return FactorSummary(
            counts[AdjustmentFactorState.KNOWN_OFFICIAL],
            counts[AdjustmentFactorState.DERIVED_FROM_OFFICIAL_TERMS],
            counts[AdjustmentFactorState.AMBIGUOUS],
            counts[AdjustmentFactorState.UNKNOWN],
            counts[AdjustmentFactorState.INVALID],
            counts[AdjustmentFactorState.CONFLICTING],
        )

    @staticmethod
    def _price_basis_summary(
        raw_count: int,
        intervals: Sequence[PriceBasisInterval],
        adjusted: Sequence[AdjustedCandleSummary],
    ) -> PriceBasisSummary:
        return PriceBasisSummary(
            raw_count,
            sum(item.adjusted_rows for item in adjusted),
            sum(item.state is PriceBasisState.BACKWARD_ADJUSTED for item in intervals),
            sum(
                item.state is PriceBasisState.ADJUSTMENT_FACTOR_UNKNOWN
                for item in intervals
            ),
            sum(item.state is PriceBasisState.MIXED_PRICE_BASIS for item in intervals),
            sum(
                item.state
                in {
                    PriceBasisState.ADJUSTMENT_FACTOR_UNKNOWN,
                    PriceBasisState.IDENTITY_TRANSITION_UNRESOLVED,
                    PriceBasisState.MIXED_PRICE_BASIS,
                    PriceBasisState.CONFLICTING_EVIDENCE,
                }
                for item in intervals
            ),
        )

    @staticmethod
    def _continuity_summary(
        discontinuities: Sequence[PriceDiscontinuity],
        indicators: Sequence[IndicatorContamination],
    ) -> ContinuitySummary:
        raw = sum(
            item.raw_gap_pct is not None and abs(item.raw_gap_pct) >= 0.15
            for item in discontinuities
        )
        adjusted = sum(
            item.theoretical_adjusted_gap_pct is not None
            and abs(item.theoretical_adjusted_gap_pct) >= 0.15
            for item in discontinuities
        )
        exposed = sum(
            item.atr_state
            in {
                ContaminationState.EXPOSED_ADJUSTED,
                ContaminationState.EXPOSED_UNADJUSTED,
            }
            for item in indicators
        )
        return ContinuitySummary(
            raw,
            adjusted,
            sum(item.false_breakout_risk for item in discontinuities),
            sum(item.false_breakdown_risk for item in discontinuities),
            exposed,
            exposed,
            exposed,
        )

    @staticmethod
    def _transition_summary(
        transitions: Sequence[IdentityTransition],
    ) -> IdentityTransitionSummary:
        resolved = sum(item.histories_may_be_linked for item in transitions)
        return IdentityTransitionSummary(
            resolved,
            len(transitions) - resolved,
            sum(
                item.continuity_type is ContinuityType.PREDECESSOR_SUCCESSOR
                for item in transitions
            ),
            sum(
                item.action_type is CorporateActionType.SYMBOL_CHANGE
                and item.histories_may_be_linked
                for item in transitions
            ),
            sum(
                item.action_type is CorporateActionType.ISIN_CHANGE
                and item.histories_may_be_linked
                for item in transitions
            ),
            sum(item.action_type is CorporateActionType.MERGER for item in transitions),
            sum(
                item.action_type is CorporateActionType.DEMERGER for item in transitions
            ),
            sum(
                item.action_type is CorporateActionType.SCHEME_OF_ARRANGEMENT
                for item in transitions
            ),
        )

    @staticmethod
    def _transition_evidence_cutoff(
        actions: Sequence[CorporateActionEvent],
    ) -> date | None:
        dates = [
            item.effective_date
            for item in actions
            if item.action_type in TRANSITION_ACTIONS
        ]
        return max(
            dates, default=max((item.effective_date for item in actions), default=None)
        )

    @staticmethod
    def _certification(
        sources: SourceSummary,
        actions: Sequence[CorporateActionEvent],
        factors: Sequence[AdjustmentFactor],
        intervals: Sequence[PriceBasisInterval],
        transitions: Sequence[IdentityTransition],
        cutoffs: CoverageCutoffs,
    ) -> CorporateActionCertification:
        blockers: list[CertificationState] = []
        if sources.failed or sources.rejected or sources.uncovered_years:
            blockers.append(
                CertificationState.BLOCKED_MISSING_CORPORATE_ACTION_EVIDENCE
            )
        if any(
            item.state
            in {AdjustmentFactorState.UNKNOWN, AdjustmentFactorState.AMBIGUOUS}
            for item in factors
        ):
            blockers.append(CertificationState.BLOCKED_UNKNOWN_ADJUSTMENT_FACTORS)
        if any(item.state is PriceBasisState.MIXED_PRICE_BASIS for item in intervals):
            blockers.append(CertificationState.BLOCKED_MIXED_PRICE_BASIS)
        if any(not item.histories_may_be_linked for item in transitions):
            blockers.append(CertificationState.BLOCKED_IDENTITY_TRANSITIONS)
        if any(
            item.admission_state is ActionAdmissionState.CONFLICTING for item in actions
        ):
            blockers.append(CertificationState.BLOCKED_CONFLICTING_EVENTS)
        if not cutoffs.ytd_2026_certified:
            blockers.append(CertificationState.BLOCKED_POINT_IN_TIME_SAFETY)
        blockers = list(dict.fromkeys(blockers))
        if not actions:
            primary = CertificationState.INSUFFICIENT_EVIDENCE
        elif not blockers:
            primary = CertificationState.CORPORATE_ACTION_PRICE_BASIS_CERTIFIED
        else:
            primary = CertificationState.PARTIALLY_CERTIFIED
        return CorporateActionCertification(
            primary,
            tuple(blockers),
            (
                f"{len(actions)} official corporate-action rows were normalized; "
                f"{len(factors)} governed factor assessments and "
                f"{len(intervals)} identity price-basis intervals were produced."
            ),
            (
                "Every source is official, immutable and checksum verified",
                "Every material action has known non-conflicting terms",
                "Raw daily candles remain immutable",
                "Adjusted rows derive only from admitted official events",
                "Future event knowledge is excluded from candidate attribution",
                "Reorganisation histories are linked only by official terms",
            ),
        )

    def _persist(self, report: CorporateActionPriceReport) -> None:
        before = self._raw_signature()
        with duckdb.connect(str(self.database_path)) as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                _create_tables(connection)
                _delete_contract_rows(connection)
                _insert_report(connection, report)
                _materialize_adjusted_rows(connection)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        after = self._raw_signature()
        if before != after:
            raise RuntimeError("raw daily candles changed during HTR-009B persistence")

    def _raw_signature(self) -> tuple[int, date | None, date | None, int, int]:
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            row = connection.execute(
                "SELECT COUNT(*), MIN(trading_date), MAX(trading_date), "
                "SUM(volume), SUM(hash(trading_date, exchange, symbol, series, "
                "isin, open_price, high_price, low_price, close_price, volume, "
                "source_sha256))::HUGEINT FROM daily_candle"
            ).fetchone()
        assert row is not None
        return int(row[0]), row[1], row[2], int(row[3] or 0), int(row[4] or 0)


def _basis_state(
    known: Sequence[AdjustmentFactor],
    unknown: Sequence[AdjustmentFactor],
    transition: bool,
) -> tuple[PriceBasisState, tuple[str, ...]]:
    if transition:
        return (
            PriceBasisState.IDENTITY_TRANSITION_UNRESOLVED,
            ("OFFICIAL_SUCCESSOR_TERMS_REQUIRED",),
        )
    if known and unknown:
        return PriceBasisState.MIXED_PRICE_BASIS, ("KNOWN_AND_UNKNOWN_FACTORS",)
    if unknown:
        if any(item.state is AdjustmentFactorState.CONFLICTING for item in unknown):
            return PriceBasisState.CONFLICTING_EVIDENCE, ("CONFLICTING_FACTORS",)
        return PriceBasisState.ADJUSTMENT_FACTOR_UNKNOWN, ("FACTOR_UNKNOWN",)
    if known:
        return PriceBasisState.BACKWARD_ADJUSTED, ()
    return PriceBasisState.NO_ADJUSTMENT_REQUIRED, ()


def _calendar_cutoff(path: Path) -> date | None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    value = payload.get("end_date")
    return date.fromisoformat(str(value)) if value else None


def _snapshot_cutoff(root: Path) -> date | None:
    if not root.exists():
        return None
    dates: list[date] = []
    for path in root.rglob("*"):
        for match in re.findall(r"20\d{2}-?\d{2}-?\d{2}", path.name):
            normalized = (
                match if "-" in match else f"{match[:4]}-{match[4:6]}-{match[6:]}"
            )
            try:
                dates.append(date.fromisoformat(normalized))
            except ValueError:
                pass
    return max(dates, default=None)


def _atr(rows: Sequence[tuple[Any, ...]]) -> float | None:
    if len(rows) < 2:
        return None
    ranges: list[float] = []
    previous_close: float | None = None
    for row in rows[-14:]:
        high, low, close = float(row[2]), float(row[3]), float(row[4])
        true_range = high - low
        if previous_close is not None:
            true_range = max(
                true_range,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        ranges.append(true_range)
        previous_close = close
    return sum(ranges) / len(ranges) if ranges else None


def _pct(value: float | None, base: float | None) -> float | None:
    if value is None or base is None or base == 0:
        return None
    return (value / base) - 1.0


def _isin_from_identity(identity_key: str) -> str | None:
    return identity_key.rsplit(":", 1)[-1] if ":isin:" in identity_key else None


def _filter_actions(
    actions: Sequence[CorporateActionEvent],
    symbols: Sequence[str],
    isins: Sequence[str],
    years: Sequence[int],
    action_types: Sequence[CorporateActionType],
) -> tuple[CorporateActionEvent, ...]:
    symbol_set = {item.upper() for item in symbols}
    isin_set = {item.upper() for item in isins}
    type_set = set(action_types)
    year_set = set(years)
    return tuple(
        item
        for item in actions
        if (not symbol_set or item.symbol in symbol_set)
        and (not isin_set or item.isin in isin_set)
        and (not year_set or item.ex_date.year in year_set)
        and (not type_set or item.action_type in type_set)
    )


def _filter_factors(
    factors: Sequence[AdjustmentFactor],
    isins: Sequence[str],
    years: Sequence[int],
) -> tuple[AdjustmentFactor, ...]:
    isin_set = {item.upper() for item in isins}
    year_set = set(years)
    return tuple(
        item
        for item in factors
        if (not isin_set or _isin_from_identity(item.identity_key) in isin_set)
        and (not year_set or item.effective_date.year in year_set)
    )


def _filter_intervals(
    intervals: Sequence[PriceBasisInterval],
    isins: Sequence[str],
    years: Sequence[int],
    states: Sequence[PriceBasisState],
    only_unresolved: bool,
) -> tuple[PriceBasisInterval, ...]:
    isin_set = {item.upper() for item in isins}
    year_set = set(years)
    state_set = set(states)
    unresolved = {
        PriceBasisState.MIXED_PRICE_BASIS,
        PriceBasisState.ADJUSTMENT_REQUIRED_NOT_APPLIED,
        PriceBasisState.ADJUSTMENT_FACTOR_UNKNOWN,
        PriceBasisState.IDENTITY_TRANSITION_UNRESOLVED,
        PriceBasisState.CONFLICTING_EVIDENCE,
    }
    return tuple(
        item
        for item in intervals
        if (not isin_set or _isin_from_identity(item.identity_key) in isin_set)
        and (
            not year_set
            or any(
                year in year_set
                for year in range(item.valid_from.year, item.valid_to.year + 1)
            )
        )
        and (not state_set or item.state in state_set)
        and (not only_unresolved or item.state in unresolved)
    )


def _identity_matches(identity_key: str, isins: Sequence[str]) -> bool:
    return not isins or _isin_from_identity(identity_key) in {
        item.upper() for item in isins
    }


def _record_matches(
    symbol: str,
    identity_key: str,
    symbols: Sequence[str],
    isins: Sequence[str],
) -> bool:
    return (not symbols or symbol in {item.upper() for item in symbols}) and (
        not isins
        or _isin_from_identity(identity_key) in {item.upper() for item in isins}
    )


def _transition_matches(
    transition: IdentityTransition,
    symbols: Sequence[str],
    isins: Sequence[str],
) -> bool:
    symbol_set = {item.upper() for item in symbols}
    isin_set = {item.upper() for item in isins}
    return (
        not symbol_set
        or transition.old_symbol in symbol_set
        or transition.new_symbol in symbol_set
    ) and (
        not isin_set
        or transition.old_isin in isin_set
        or transition.new_isin in isin_set
    )


def _create_tables(connection: duckdb.DuckDBPyConnection) -> None:
    statements = (
        """CREATE TABLE IF NOT EXISTS corporate_action_event(
            contract_version VARCHAR, action_id VARCHAR, exchange VARCHAR,
            governed_identity_id VARCHAR, symbol VARCHAR, series VARCHAR,
            isin VARCHAR, action_type VARCHAR, purpose VARCHAR,
            announcement_date DATE, record_date DATE, ex_date DATE,
            effective_date DATE, old_face_value DOUBLE, new_face_value DOUBLE,
            ratio_numerator DOUBLE, ratio_denominator DOUBLE, cash_amount DOUBLE,
            rights_price DOUBLE, old_quantity DOUBLE, new_quantity DOUBLE,
            predecessor_identity VARCHAR, successor_identity VARCHAR,
            price_adjustment_required BOOLEAN, adjustment_factor_state VARCHAR,
            adjustment_factor DOUBLE, source_id VARCHAR, source_location VARCHAR,
            admission_state VARCHAR, confidence_state VARCHAR,
            PRIMARY KEY(contract_version, action_id))""",
        """CREATE TABLE IF NOT EXISTS corporate_action_lineage(
            contract_version VARCHAR, action_id VARCHAR, source_id VARCHAR,
            source_sha256 VARCHAR, source_url VARCHAR, parser VARCHAR,
            row_number BIGINT,
            PRIMARY KEY(contract_version, action_id, source_id))""",
        """CREATE TABLE IF NOT EXISTS corporate_action_adjustment_factor(
            contract_version VARCHAR, factor_id VARCHAR, action_id VARCHAR,
            identity_key VARCHAR, effective_date DATE, direction VARCHAR,
            price_factor DOUBLE, quantity_factor DOUBLE, state VARCHAR,
            source_id VARCHAR, calculation_version VARCHAR,
            reference_price DOUBLE, explanation VARCHAR,
            PRIMARY KEY(contract_version, factor_id))""",
        """CREATE TABLE IF NOT EXISTS price_basis_interval(
            contract_version VARCHAR, identity_key VARCHAR, valid_from DATE,
            valid_to DATE, state VARCHAR, action_ids VARCHAR,
            known_factor_count BIGINT, unknown_factor_count BIGINT,
            raw_row_count BIGINT, adjusted_row_count BIGINT, issue_codes VARCHAR,
            PRIMARY KEY(contract_version, identity_key, valid_from))""",
        """CREATE TABLE IF NOT EXISTS adjusted_daily_candle(
            contract_version VARCHAR, trading_date DATE, exchange VARCHAR,
            symbol VARCHAR, series VARCHAR, isin VARCHAR,
            raw_open DOUBLE, raw_high DOUBLE, raw_low DOUBLE, raw_close DOUBLE,
            raw_volume BIGINT, price_factor DOUBLE, quantity_factor DOUBLE,
            adjusted_open DOUBLE, adjusted_high DOUBLE, adjusted_low DOUBLE,
            adjusted_close DOUBLE, adjusted_volume BIGINT, action_ids VARCHAR,
            calculation_version VARCHAR, as_of_date DATE,
            PRIMARY KEY(contract_version, trading_date, exchange, symbol, series))""",
        """CREATE TABLE IF NOT EXISTS adjusted_candle_lineage(
            contract_version VARCHAR, trading_date DATE, exchange VARCHAR,
            symbol VARCHAR, series VARCHAR, raw_source_sha256 VARCHAR,
            action_ids VARCHAR, factor_ids VARCHAR, lineage_digest VARCHAR,
            PRIMARY KEY(contract_version, trading_date, exchange, symbol, series))""",
        """CREATE TABLE IF NOT EXISTS identity_transition(
            contract_version VARCHAR, transition_id VARCHAR,
            predecessor_identity VARCHAR, successor_identity VARCHAR,
            old_symbol VARCHAR, new_symbol VARCHAR, old_isin VARCHAR,
            new_isin VARCHAR, action_type VARCHAR, effective_date DATE,
            exchange_ratio VARCHAR, continuity_type VARCHAR,
            histories_may_be_linked BOOLEAN, price_comparison_valid BOOLEAN,
            new_identity_required BOOLEAN, official_source VARCHAR,
            confidence_state VARCHAR, issue_codes VARCHAR,
            PRIMARY KEY(contract_version, transition_id))""",
        """CREATE TABLE IF NOT EXISTS corporate_action_rejection(
            contract_version VARCHAR, source_id VARCHAR, source_location VARCHAR,
            failure_code VARCHAR, failure_detail VARCHAR, row_number BIGINT,
            raw_identifier VARCHAR)""",
        """CREATE TABLE IF NOT EXISTS candidate_corporate_action_exposure(
            contract_version VARCHAR, candidate_id VARCHAR, identity_key VARCHAR,
            symbol VARCHAR, candidate_date DATE, setup VARCHAR, verdict VARCHAR,
            candidate_count BIGINT, action_in_lookback BOOLEAN, action_type VARCHAR,
            price_basis_state VARCHAR, corporate_action_risk VARCHAR,
            identity_transition_state VARCHAR, adjustment_factor_state VARCHAR,
            raw_adjusted_divergence DOUBLE,
            indicator_contamination_state VARCHAR,
            stop_contamination_state VARCHAR, target_contamination_state VARCHAR,
            outcome_contamination_state VARCHAR, evidence_availability VARCHAR,
            PRIMARY KEY(contract_version, candidate_id))""",
    )
    for statement in statements:
        connection.execute(statement)


def _delete_contract_rows(connection: duckdb.DuckDBPyConnection) -> None:
    for table in (
        "corporate_action_event",
        "corporate_action_lineage",
        "corporate_action_adjustment_factor",
        "price_basis_interval",
        "adjusted_daily_candle",
        "adjusted_candle_lineage",
        "identity_transition",
        "corporate_action_rejection",
        "candidate_corporate_action_exposure",
    ):
        connection.execute(
            f"DELETE FROM {table} WHERE contract_version = ?",  # noqa: S608
            [HTR009B_CONTRACT_VERSION],
        )


def _insert_report(
    connection: duckdb.DuckDBPyConnection,
    report: CorporateActionPriceReport,
) -> None:
    version = HTR009B_CONTRACT_VERSION
    if report.actions:
        connection.executemany(
            "INSERT INTO corporate_action_event VALUES ("
            + ",".join("?" for _ in range(30))
            + ")",
            [
                (
                    version,
                    item.action_id,
                    item.exchange,
                    item.governed_identity_id,
                    item.symbol,
                    item.series,
                    item.isin,
                    item.action_type.value,
                    item.purpose,
                    item.announcement_date,
                    item.record_date,
                    item.ex_date,
                    item.effective_date,
                    item.old_face_value,
                    item.new_face_value,
                    item.ratio_numerator,
                    item.ratio_denominator,
                    item.cash_amount,
                    item.rights_price,
                    item.old_quantity,
                    item.new_quantity,
                    item.predecessor_identity,
                    item.successor_identity,
                    item.price_adjustment_required,
                    item.adjustment_factor_state.value,
                    item.adjustment_factor,
                    item.source_id,
                    item.source_location,
                    item.admission_state.value,
                    item.confidence_state.value,
                )
                for item in report.actions
            ],
        )
    if report.lineage:
        connection.executemany(
            "INSERT INTO corporate_action_lineage VALUES (?,?,?,?,?,?,?)",
            [
                (
                    version,
                    item.action_id,
                    item.source_id,
                    item.source_sha256,
                    item.source_url,
                    item.parser,
                    item.row_number,
                )
                for item in report.lineage
            ],
        )
    if report.factors:
        connection.executemany(
            "INSERT INTO corporate_action_adjustment_factor VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    version,
                    item.factor_id,
                    item.action_id,
                    item.identity_key,
                    item.effective_date,
                    item.direction.value,
                    item.price_factor,
                    item.quantity_factor,
                    item.state.value,
                    item.source_id,
                    item.calculation_version,
                    item.reference_price,
                    item.explanation,
                )
                for item in report.factors
            ],
        )
    if report.price_basis_intervals:
        connection.executemany(
            "INSERT INTO price_basis_interval VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    version,
                    item.identity_key,
                    item.valid_from,
                    item.valid_to,
                    item.state.value,
                    json.dumps(item.action_ids),
                    item.known_factor_count,
                    item.unknown_factor_count,
                    item.raw_row_count,
                    item.adjusted_row_count,
                    json.dumps(item.issue_codes),
                )
                for item in report.price_basis_intervals
            ],
        )
    if report.identity_transitions:
        connection.executemany(
            "INSERT INTO identity_transition VALUES ("
            + ",".join("?" for _ in range(18))
            + ")",
            [
                (
                    version,
                    item.transition_id,
                    item.predecessor_identity,
                    item.successor_identity,
                    item.old_symbol,
                    item.new_symbol,
                    item.old_isin,
                    item.new_isin,
                    item.action_type.value,
                    item.effective_date,
                    item.exchange_ratio,
                    item.continuity_type.value,
                    item.histories_may_be_linked,
                    item.price_comparison_valid,
                    item.new_identity_required,
                    item.official_source,
                    item.confidence_state.value,
                    json.dumps(item.issue_codes),
                )
                for item in report.identity_transitions
            ],
        )
    if report.rejected_evidence:
        connection.executemany(
            "INSERT INTO corporate_action_rejection VALUES (?,?,?,?,?,?,?)",
            [
                (
                    version,
                    item.source_id,
                    item.source_location,
                    item.failure_code.value,
                    item.failure_detail,
                    item.row_number,
                    item.raw_identifier,
                )
                for item in report.rejected_evidence
            ],
        )
    if report.candidate_exposure:
        connection.executemany(
            "INSERT INTO candidate_corporate_action_exposure VALUES ("
            + ",".join("?" for _ in range(20))
            + ")",
            [
                (
                    version,
                    item.candidate_id,
                    item.identity_key,
                    item.symbol,
                    item.candidate_date,
                    item.setup,
                    item.verdict,
                    item.candidate_count,
                    item.action_in_lookback,
                    item.action_type.value if item.action_type else None,
                    item.price_basis_state.value,
                    item.corporate_action_risk.value,
                    item.identity_transition_state.value,
                    item.adjustment_factor_state.value,
                    item.raw_adjusted_divergence,
                    item.indicator_contamination_state.value,
                    item.stop_contamination_state.value,
                    item.target_contamination_state.value,
                    item.outcome_contamination_state.value,
                    item.evidence_availability,
                )
                for item in report.candidate_exposure
            ],
        )


def _materialize_adjusted_rows(connection: duckdb.DuckDBPyConnection) -> None:
    version = HTR009B_CONTRACT_VERSION
    connection.execute(
        """
        INSERT INTO adjusted_daily_candle
        WITH applicable AS (
            SELECT c.trading_date, c.exchange, c.symbol, c.series, c.isin,
                   c.open_price, c.high_price, c.low_price, c.close_price,
                   c.volume, c.source_sha256,
                   EXP(SUM(LN(f.price_factor))) AS price_factor,
                   EXP(SUM(LN(f.quantity_factor))) AS quantity_factor,
                   string_agg(f.action_id, ',' ORDER BY f.effective_date) AS action_ids,
                   MAX(f.effective_date) AS as_of_date
            FROM daily_candle c
            JOIN corporate_action_adjustment_factor f
              ON f.contract_version = ?
             AND f.identity_key = 'nse:isin:' || UPPER(TRIM(c.isin))
             AND c.trading_date < f.effective_date
             AND f.price_factor IS NOT NULL
             AND f.quantity_factor IS NOT NULL
             AND f.state IN ('KNOWN_OFFICIAL', 'DERIVED_FROM_OFFICIAL_TERMS')
            GROUP BY c.trading_date, c.exchange, c.symbol, c.series, c.isin,
                     c.open_price, c.high_price, c.low_price, c.close_price,
                     c.volume, c.source_sha256
        )
        SELECT ?, trading_date, exchange, symbol, series, isin,
               open_price, high_price, low_price, close_price, volume,
               price_factor, quantity_factor,
               open_price * price_factor, high_price * price_factor,
               low_price * price_factor, close_price * price_factor,
               CAST(ROUND(volume * quantity_factor) AS BIGINT), action_ids,
               ?, as_of_date
        FROM applicable
        """,
        [version, version, CALCULATION_VERSION],
    )
    connection.execute(
        """
        INSERT INTO adjusted_candle_lineage
        SELECT a.contract_version, a.trading_date, a.exchange, a.symbol, a.series,
               c.source_sha256, a.action_ids,
               string_agg(f.factor_id, ',' ORDER BY f.effective_date),
               md5(COALESCE(c.source_sha256, '') || '|' || a.action_ids || '|' ||
                   a.calculation_version)
        FROM adjusted_daily_candle a
        JOIN daily_candle c USING(trading_date, exchange, symbol, series)
        JOIN corporate_action_adjustment_factor f
          ON f.contract_version = a.contract_version
         AND f.identity_key = 'nse:isin:' || UPPER(TRIM(a.isin))
         AND a.trading_date < f.effective_date
         AND f.price_factor IS NOT NULL
        WHERE a.contract_version = ?
        GROUP BY a.contract_version, a.trading_date, a.exchange, a.symbol,
                 a.series, c.source_sha256, a.action_ids, a.calculation_version
        """,
        [version],
    )


__all__ = [
    "AdjustmentFactorEngine",
    "CorporateActionPriceCertificationEngine",
]
