"""Governed bridge-aware candle context for factor continuity validation."""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any

import duckdb

from alpha.historical_truth.legacy_isin_reference_bridge import (
    LEGACY_ISIN_REFERENCE_BRIDGE_CONTRACT_VERSION,
    LegacyBridgeDecision,
    LegacyIsinReferenceBridge,
    LegacyIsinReferenceBridgeResult,
)
from alpha.historical_truth.official_corporate_action_supplements import (
    SUPPLEMENT_CONTRACT_VERSION,
    OfficialSecurityIdentitySupplement,
    OfficialSecurityTransitionSupplement,
    official_security_identity_supplements,
    official_security_transition_supplements,
)

BRIDGE_AWARE_CONTINUITY_CONTRACT_VERSION = "DSI-010B3-GOVERNED-CONTINUITY-v1.0.0"
PRODUCTION_INFLUENCE = False
_MATERIAL_CONTINUITY_ACTION_TYPES = frozenset(
    {
        "BONUS",
        "CAPITAL_REDUCTION",
        "COMPOSITE",
        "FACE_VALUE_CHANGE",
        "RIGHTS",
        "SPLIT",
    }
)
_EQUITY_TRADING_SERIES = ("EQ", "BE", "BZ")


class GovernedCandleIdentityState(StrEnum):
    """Identity disposition for one candidate canonical candle."""

    EXACT_ISIN_CANDLE = "EXACT_ISIN_CANDLE"
    CERTIFIED_DATED_BRIDGE_CANDLE = "CERTIFIED_DATED_BRIDGE_CANDLE"
    CERTIFIED_OFFICIAL_ISIN_TRANSITION_CANDLE = (
        "CERTIFIED_OFFICIAL_ISIN_TRANSITION_CANDLE"
    )
    CERTIFIED_OFFICIAL_SERIES_TRANSITION_CANDLE = (
        "CERTIFIED_OFFICIAL_SERIES_TRANSITION_CANDLE"
    )
    EXPLICIT_ISIN_MISMATCH = "EXPLICIT_ISIN_MISMATCH"
    MISSING_ISIN_NO_CERTIFIED_BRIDGE = "MISSING_ISIN_NO_CERTIFIED_BRIDGE"
    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
    SYMBOL_CONFLICT = "SYMBOL_CONFLICT"
    SERIES_CONFLICT = "SERIES_CONFLICT"
    DATE_OUTSIDE_CERTIFIED_INTERVAL = "DATE_OUTSIDE_CERTIFIED_INTERVAL"
    SOURCE_HASH_MISSING = "SOURCE_HASH_MISSING"
    DUPLICATE_CANONICAL_CANDLE = "DUPLICATE_CANONICAL_CANDLE"
    NON_POSITIVE_PRICE = "NON_POSITIVE_PRICE"


class ContinuityContextDecision(StrEnum):
    """Final governed disposition of an event candle context."""

    COMPLETE_GOVERNED_CONTINUITY_CONTEXT = "COMPLETE_GOVERNED_CONTINUITY_CONTEXT"
    INSUFFICIENT_ATR_HISTORY = "INSUFFICIENT_ATR_HISTORY"
    ACTION_SESSION_MISSING = "ACTION_SESSION_MISSING"
    REFERENCE_SESSION_MISMATCH = "REFERENCE_SESSION_MISMATCH"
    REFERENCE_PRICE_MISMATCH = "REFERENCE_PRICE_MISMATCH"
    REFERENCE_SOURCE_HASH_MISMATCH = "REFERENCE_SOURCE_HASH_MISMATCH"
    BRIDGE_PROVENANCE_MISMATCH = "BRIDGE_PROVENANCE_MISMATCH"
    DUPLICATE_CANONICAL_CANDLE = "DUPLICATE_CANONICAL_CANDLE"
    NO_SIGNED_BRIDGE_CASE = "NO_SIGNED_BRIDGE_CASE"


@dataclass(frozen=True, slots=True)
class SignedBridgeContinuitySourceContract:
    """Pinned DSI-010B1 acceptance boundary consumed by DSI-010B2."""

    workflow_run_id: int
    artifact_id: int
    artifact_digest: str
    source_head_sha: str
    expected_file_sha256: tuple[tuple[str, str], ...]

    def expected_checksums(self) -> dict[str, str]:
        return dict(self.expected_file_sha256)


SIGNED_DSI010B1_CONTINUITY_SOURCE_CONTRACT = SignedBridgeContinuitySourceContract(
    workflow_run_id=30380882353,
    artifact_id=8697121184,
    artifact_digest=(
        "sha256:15bcc743fd876f0467df17a8347561086e483e52256271da3bbe016bf57e487c"
    ),
    source_head_sha="0fdae5ca031478d7bd0fe9d4d6e464f63ac83923",
    expected_file_sha256=(
        (
            "legacy_rights_reference_bridge_cases.json",
            "32e64973fc6189346265e66cd97cd0a192e1f45d04855a2eaf2021583af3166e",
        ),
        (
            "legacy_rights_reference_bridge_summary.json",
            "023e29320d9b3aa91ed960726351e66326882d13b19e3afcf9ee94f1bb972c5e",
        ),
        (
            "legacy_rights_reference_bridge_source_manifest.json",
            "80376a51f70229579b597dcc82203a8231a6802897a9e5df6582beee7e2bbdc2",
        ),
        (
            "legacy_rights_reference_bridge_report.md",
            "b8c1b8b99c13a7a3e740f5e8c1731fa497e1d1ec42d24cbdf6da8c57d7ac54cc",
        ),
        (
            "legacy_rights_reference_bridge_certificate.json",
            "4a204ead7417d68187bcaf0c8c8330a82054641ff740c4659cd6404cc1e37e41",
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class RawCanonicalCandle:
    trading_date: date
    symbol: str
    series: str
    isin: str | None
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int
    source_sha256: str | None


@dataclass(frozen=True, slots=True)
class BridgeEvidence:
    decision: str
    interval_ids: tuple[str, ...]
    official_event_ids: tuple[str, ...]
    official_source_ids: tuple[str, ...]
    source_contract_id: str
    source_report_sha256: str


@dataclass(frozen=True, slots=True)
class OfficialEventDateIdentityEvidence:
    """Exact-date identity evidence from one immutable official action row."""

    event_id: str
    identity: str
    symbol: str
    series: tuple[str, ...]
    isin: str
    effective_date: date
    source_ids: tuple[str, ...]
    source_sha256: tuple[str, ...]
    source_report_sha256: str
    interval_valid_from: date | None = None
    interval_valid_to: date | None = None
    action_type: str = ""

    def certifies(
        self,
        candle: RawCanonicalCandle,
        *,
        identity: str,
        symbol: str,
        series: str,
        isin: str,
        role: str,
        allow_equity_series_transition: bool = False,
    ) -> bool:
        exact_action_date = role == "ACTION" and (
            candle.trading_date == self.effective_date
        )
        bounded_action_date = (
            role == "ACTION"
            and self.interval_valid_to is not None
            and self.effective_date <= candle.trading_date < self.interval_valid_to
        )
        bounded_prior_date = (
            role == "PRIOR"
            and self.interval_valid_from is not None
            and self.interval_valid_from <= candle.trading_date < self.effective_date
        )
        candle_series = candle.series.upper()
        series_matches = candle_series == series
        series_transition = (
            allow_equity_series_transition
            and candle_series in _EQUITY_TRADING_SERIES
            and series in _EQUITY_TRADING_SERIES
            and any(item in _EQUITY_TRADING_SERIES for item in self.series)
        )
        return (
            (exact_action_date or bounded_action_date or bounded_prior_date)
            and self.identity == identity
            and self.symbol == symbol
            and (series in self.series or series_transition)
            and self.isin == isin
            and candle.symbol.upper() == symbol
            and (series_matches or series_transition)
        )


@dataclass(frozen=True, slots=True)
class OfficialIsinTransitionEvidence:
    """One source-bound old-to-new ISIN transition at an official action date."""

    from_isin: str
    to_isin: str
    effective_date: date
    event_id: str
    source_ids: tuple[str, ...]
    source_report_sha256: str


@dataclass(frozen=True, slots=True)
class GovernedCandleRecord:
    candle: RawCanonicalCandle
    identity_state: GovernedCandleIdentityState
    role: str
    bridge_evidence: BridgeEvidence | None

    def as_bar(self) -> tuple[Any, ...]:
        return (
            self.candle.trading_date,
            self.candle.open_price,
            self.candle.high_price,
            self.candle.low_price,
            self.candle.close_price,
            self.candle.volume,
        )

    def as_dict(self, *, atr_included: bool = False) -> dict[str, Any]:
        evidence = self.bridge_evidence
        return {
            "trading_date": self.candle.trading_date.isoformat(),
            "symbol": self.candle.symbol,
            "series": self.candle.series,
            "original_isin": self.candle.isin,
            "open_price": self.candle.open_price,
            "high_price": self.candle.high_price,
            "low_price": self.candle.low_price,
            "close_price": self.candle.close_price,
            "volume": self.candle.volume,
            "source_sha256": self.candle.source_sha256,
            "identity_state": self.identity_state.value,
            "role": self.role,
            "atr_included": atr_included,
            "bridge_decision": evidence.decision if evidence else None,
            "bridge_interval_ids": list(evidence.interval_ids) if evidence else [],
            "bridge_official_event_ids": (
                list(evidence.official_event_ids) if evidence else []
            ),
            "bridge_official_source_ids": (
                list(evidence.official_source_ids) if evidence else []
            ),
            "bridge_source_contract_id": (
                evidence.source_contract_id if evidence else None
            ),
            "bridge_source_report_sha256": (
                evidence.source_report_sha256 if evidence else None
            ),
        }


@dataclass(frozen=True, slots=True)
class RejectedCandleRecord:
    candle: RawCanonicalCandle
    reason: GovernedCandleIdentityState
    role: str
    bridge_decision: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "trading_date": self.candle.trading_date.isoformat(),
            "symbol": self.candle.symbol,
            "series": self.candle.series,
            "original_isin": self.candle.isin,
            "source_sha256": self.candle.source_sha256,
            "reason": self.reason.value,
            "role": self.role,
            "bridge_decision": self.bridge_decision,
        }


@dataclass(frozen=True, slots=True)
class ATRWindowEvidence:
    selected_prior_bars: tuple[GovernedCandleRecord, ...]
    atr_bars: tuple[GovernedCandleRecord, ...]
    atr: float | None


@dataclass(frozen=True, slots=True)
class ContinuityMetrics:
    previous_session: date | None
    action_session: date | None
    previous_close: float | None
    action_open: float | None
    action_close: float | None
    atr_before: float | None
    median_prior_volume: float | None
    raw_gap_atr: float | None
    adjusted_gap_atr: float | None
    inverse_adjusted_gap_atr: float | None
    close_raw_gap_atr: float | None
    close_adjusted_gap_atr: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "previous_session": (
                self.previous_session.isoformat() if self.previous_session else None
            ),
            "action_session": (
                self.action_session.isoformat() if self.action_session else None
            ),
            "previous_close": self.previous_close,
            "action_open": self.action_open,
            "action_close": self.action_close,
            "atr_before": self.atr_before,
            "median_prior_volume": self.median_prior_volume,
            "raw_gap_atr": self.raw_gap_atr,
            "adjusted_gap_atr": self.adjusted_gap_atr,
            "inverse_adjusted_gap_atr": self.inverse_adjusted_gap_atr,
            "close_raw_gap_atr": self.close_raw_gap_atr,
            "close_adjusted_gap_atr": self.close_adjusted_gap_atr,
        }


@dataclass(frozen=True, slots=True)
class EventBarContext:
    context_id: str
    event_id: str
    decision: ContinuityContextDecision
    prior_window: ATRWindowEvidence
    action_bar: GovernedCandleRecord | None
    rejected_bars: tuple[RejectedCandleRecord, ...]
    metrics: ContinuityMetrics
    exact_isin_prior_bar_count: int
    exact_isin_action_bar_count: int
    potentially_relevant_missing_isin_bar_count: int
    first_candidate_action_date: date | None
    first_market_session_date: date | None = None
    action_search_end_date: date | None = None
    action_session_delay_market_sessions: int | None = None
    pre_event_gap_market_sessions: int | None = None

    @property
    def complete(self) -> bool:
        return (
            self.decision
            is ContinuityContextDecision.COMPLETE_GOVERNED_CONTINUITY_CONTEXT
        )

    def as_dict(self) -> dict[str, Any]:
        atr_ids = {item.candle.trading_date for item in self.prior_window.atr_bars}
        return {
            "context_id": self.context_id,
            "event_id": self.event_id,
            "decision": self.decision.value,
            "complete": self.complete,
            "exact_isin_prior_bar_count": self.exact_isin_prior_bar_count,
            "exact_isin_action_bar_count": self.exact_isin_action_bar_count,
            "potentially_relevant_missing_isin_bar_count": (
                self.potentially_relevant_missing_isin_bar_count
            ),
            "first_candidate_action_date": (
                self.first_candidate_action_date.isoformat()
                if self.first_candidate_action_date
                else None
            ),
            "first_market_session_date": (
                self.first_market_session_date.isoformat()
                if self.first_market_session_date
                else None
            ),
            "action_search_end_date": (
                self.action_search_end_date.isoformat()
                if self.action_search_end_date
                else None
            ),
            "action_session_delay_market_sessions": (
                self.action_session_delay_market_sessions
            ),
            "pre_event_gap_market_sessions": self.pre_event_gap_market_sessions,
            "selected_prior_bars": [
                item.as_dict(
                    atr_included=item.candle.trading_date in atr_ids,
                )
                for item in self.prior_window.selected_prior_bars
            ],
            "action_bar": self.action_bar.as_dict() if self.action_bar else None,
            "rejected_bars": [item.as_dict() for item in self.rejected_bars],
            "metrics": self.metrics.as_dict(),
            "production_influence": False,
        }


@dataclass(frozen=True, slots=True)
class FinalValidationEligibility:
    event_id: str
    context_id: str
    eligible: bool
    decision: ContinuityContextDecision


class BridgeAwareContinuityContextProvider:
    """Build immutable bar contexts from signed point-in-time identity evidence."""

    def __init__(
        self,
        *,
        bridge: LegacyIsinReferenceBridge,
        cases: tuple[dict[str, Any], ...],
        source_checksums: tuple[tuple[str, str], ...],
        source_contract: SignedBridgeContinuitySourceContract,
        all_material_actions: bool = False,
        official_event_evidence: Mapping[str, OfficialEventDateIdentityEvidence]
        | None = None,
        transition_evidence: Sequence[OfficialIsinTransitionEvidence] = (),
        security_transition_supplements: Sequence[
            OfficialSecurityTransitionSupplement
        ] = (),
    ) -> None:
        eligible = tuple(row for row in cases if row.get("bridge_certified") is True)
        if len(eligible) != 18:
            raise ValueError(
                "signed DSI-010B1 population must contain 18 cases, "
                f"found {len(eligible)}"
            )
        self.bridge = bridge
        self.source_checksums = source_checksums
        self.source_contract = source_contract
        self.all_material_actions = all_material_actions
        self._official_event_evidence = dict(official_event_evidence or {})
        self._transition_evidence = tuple(transition_evidence)
        self._security_transition_supplements = tuple(security_transition_supplements)
        self._cases = {
            str(row["event_id"]): dict(row) for row in eligible if row.get("event_id")
        }
        if len(self._cases) != 18:
            raise ValueError("signed DSI-010B1 event IDs are not unique")

    @classmethod
    def from_signed_outputs(
        cls,
        *,
        htr009a2_output: Path,
        htr010a3_output: Path,
        dsi010b1_output: Path,
        htr010b_output: Path | None = None,
        data_root: Path | None = None,
        all_material_actions: bool = False,
        source_contract: SignedBridgeContinuitySourceContract = (
            SIGNED_DSI010B1_CONTINUITY_SOURCE_CONTRACT
        ),
    ) -> BridgeAwareContinuityContextProvider:
        checksums, cases = _load_b1_cases(dsi010b1_output, source_contract)
        bridge = LegacyIsinReferenceBridge.from_output(
            htr009a2_output,
            htr010a3_output=htr010a3_output,
        )
        return cls(
            bridge=bridge,
            cases=cases,
            source_checksums=checksums,
            source_contract=source_contract,
            all_material_actions=all_material_actions,
            official_event_evidence=(
                _load_official_event_date_evidence(
                    htr010b_output,
                    identity_supplements=(
                        official_security_identity_supplements(data_root)
                        if data_root is not None
                        else ()
                    ),
                )
                if htr010b_output is not None
                else None
            ),
            transition_evidence=(
                _load_official_isin_transition_evidence(htr010b_output)
                if htr010b_output is not None
                else ()
            ),
            security_transition_supplements=(
                official_security_transition_supplements(data_root)
                if data_root is not None
                else ()
            ),
        )

    @classmethod
    def from_fixture(
        cls,
        *,
        bridge: LegacyIsinReferenceBridge,
        cases: tuple[dict[str, Any], ...],
        all_material_actions: bool = False,
        official_event_evidence: Mapping[str, OfficialEventDateIdentityEvidence]
        | None = None,
        transition_evidence: Sequence[OfficialIsinTransitionEvidence] = (),
        security_transition_supplements: Sequence[
            OfficialSecurityTransitionSupplement
        ] = (),
    ) -> BridgeAwareContinuityContextProvider:
        contract = SignedBridgeContinuitySourceContract(
            workflow_run_id=0,
            artifact_id=0,
            artifact_digest=f"sha256:{'0' * 64}",
            source_head_sha="0" * 40,
            expected_file_sha256=(),
        )
        return cls(
            bridge=bridge,
            cases=cases,
            source_checksums=(),
            source_contract=contract,
            all_material_actions=all_material_actions,
            official_event_evidence=official_event_evidence,
            transition_evidence=transition_evidence,
            security_transition_supplements=security_transition_supplements,
        )

    @property
    def event_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._cases))

    def supports(self, event_id: str) -> bool:
        return self.all_material_actions or event_id in self._cases

    def case(self, event_id: str) -> dict[str, Any]:
        return dict(self._cases[event_id])

    def build(
        self,
        connection: duckdb.DuckDBPyConnection,
        *,
        event: Mapping[str, Any],
        factor: Mapping[str, Any],
        series: str,
        effective_date: date,
    ) -> EventBarContext:
        event_id = str(event.get("canonical_event_id") or "")
        signed_case = self._cases.get(event_id)
        if signed_case is None and not self.all_material_actions:
            return _empty_context(
                event_id,
                ContinuityContextDecision.NO_SIGNED_BRIDGE_CASE,
            )
        identity = str(event.get("governed_identity_id") or "")
        symbol = str(event.get("symbol") or "").upper()
        isin = str(event.get("isin") or "").upper()
        normalized_series = series.upper()
        if signed_case is not None:
            _validate_case_identity(
                signed_case,
                identity=identity,
                symbol=symbol,
                series=normalized_series,
                isin=isin,
                effective_date=effective_date,
                factor=factor,
                bridge=self.bridge,
            )
        else:
            _validate_material_action_identity(
                identity=identity,
                symbol=symbol,
                series=normalized_series,
                isin=isin,
            )
        official_event_evidence = (
            None
            if signed_case is not None
            else self._official_event_evidence.get(event_id)
        )
        action_search_end = self._next_material_action_date(
            event_id=event_id,
            identity=identity,
            symbol=symbol,
            series=normalized_series,
            effective_date=effective_date,
        )
        event_bound_symbol_transitions = (
            self.bridge.official_symbol_transitions_bound_to_event(
                identity_key=identity,
                event_symbol=symbol,
                event_source_ids=official_event_evidence.source_ids,
            )
            if official_event_evidence is not None
            else ()
        )
        candidate_symbols = tuple(
            sorted(
                {
                    symbol,
                    *(
                        transition_symbol
                        for transition in self.bridge.certified_symbol_transitions(
                            identity_key=identity,
                            allow_isin_transition_resolved_reuse=True,
                        )
                        for transition_symbol in (
                            transition.old_symbol,
                            transition.new_symbol,
                        )
                    ),
                    *(
                        transition_symbol
                        for transition in event_bound_symbol_transitions
                        for transition_symbol in (
                            transition.old_symbol,
                            transition.new_symbol,
                        )
                    ),
                }
            )
        )

        prior_candidates = _candidate_rows(
            connection,
            symbols=candidate_symbols,
            series=(
                _EQUITY_TRADING_SERIES
                if normalized_series in _EQUITY_TRADING_SERIES
                else (normalized_series,)
            ),
            isin=isin,
            effective_date=effective_date,
            prior=True,
        )
        action_candidates = _candidate_rows(
            connection,
            symbols=candidate_symbols,
            series=(
                _EQUITY_TRADING_SERIES
                if normalized_series in _EQUITY_TRADING_SERIES
                else (normalized_series,)
            ),
            isin=isin,
            effective_date=effective_date,
            prior=False,
            end_exclusive=action_search_end,
        )
        event_transition_evidence = self._material_transition_evidence(
            connection,
            symbol=symbol,
            series=normalized_series,
            effective_date=effective_date,
            candidate_symbols=candidate_symbols,
        )
        admitted_prior, rejected_prior, duplicate_prior = self._govern_candidates(
            prior_candidates,
            identity=identity,
            symbol=symbol,
            series=normalized_series,
            isin=isin,
            role="PRIOR",
            official_event_evidence=official_event_evidence,
            transition_evidence=event_transition_evidence,
            event_effective_date=effective_date,
            required_count=15,
            allow_equity_series_transition=True,
        )
        admitted_action, rejected_action, duplicate_action = self._govern_candidates(
            action_candidates,
            identity=identity,
            symbol=symbol,
            series=normalized_series,
            isin=isin,
            role="ACTION",
            stop_after_first=True,
            official_event_evidence=official_event_evidence,
            transition_evidence=event_transition_evidence,
            event_effective_date=effective_date,
            allow_equity_series_transition=True,
        )
        (
            supplemental_candidates,
            supplemental_action,
            rejected_supplemental_action,
            duplicate_supplemental_action,
        ) = self._govern_supplemental_action_candidates(
            connection,
            event_id=event_id,
            symbol=symbol,
            series=normalized_series,
            isin=isin,
            effective_date=effective_date,
            end_exclusive=action_search_end,
        )
        admitted_action = tuple(
            sorted(
                (*admitted_action, *supplemental_action),
                key=lambda item: item.candle.trading_date,
            )
        )
        rejected_action = tuple((*rejected_action, *rejected_supplemental_action))
        action_candidates = tuple(
            sorted(
                (*action_candidates, *supplemental_candidates),
                key=lambda item: item.trading_date,
            )
        )
        selected_prior = tuple(admitted_prior[-15:])
        action_bar = admitted_action[0] if admitted_action else None
        rejected = tuple((*rejected_prior, *rejected_action))
        exact_prior = sum(
            item.identity_state is GovernedCandleIdentityState.EXACT_ISIN_CANDLE
            for item in selected_prior
        )
        exact_action = int(
            action_bar is not None
            and action_bar.identity_state
            is GovernedCandleIdentityState.EXACT_ISIN_CANDLE
        )
        missing_count = sum(
            not str(item.candle.isin or "").strip()
            for item in (
                *selected_prior,
                *((action_bar,) if action_bar is not None else ()),
            )
        )
        decision = _context_decision(
            selected_prior=selected_prior,
            action_bar=action_bar,
            duplicate=(
                duplicate_prior or duplicate_action or duplicate_supplemental_action
            ),
            signed_case=signed_case,
            factor=factor,
            bridge=self.bridge,
        )
        atr_bars = selected_prior[-14:]
        atr = _atr(tuple(item.as_bar() for item in atr_bars))
        metrics = _metrics(
            selected_prior, action_bar, _number(factor.get("price_factor"))
        )
        first_market_session = _first_market_session(connection, effective_date)
        action_session_delay = (
            _market_session_delay(
                connection,
                effective_date=effective_date,
                selected_date=action_bar.candle.trading_date,
            )
            if action_bar is not None
            else None
        )
        pre_event_gap = (
            _pre_event_market_session_gap(
                connection,
                selected_date=selected_prior[-1].candle.trading_date,
                effective_date=effective_date,
            )
            if selected_prior
            else None
        )
        if decision is ContinuityContextDecision.COMPLETE_GOVERNED_CONTINUITY_CONTEXT:
            if atr is None:
                decision = ContinuityContextDecision.INSUFFICIENT_ATR_HISTORY
        context_id = _stable_id(
            "bridge-aware-continuity",
            event_id,
            decision.value,
            *(item.candle.trading_date.isoformat() for item in selected_prior),
            action_bar.candle.trading_date.isoformat() if action_bar else "",
        )
        return EventBarContext(
            context_id=context_id,
            event_id=event_id,
            decision=decision,
            prior_window=ATRWindowEvidence(
                selected_prior_bars=selected_prior,
                atr_bars=atr_bars,
                atr=atr,
            ),
            action_bar=action_bar,
            rejected_bars=rejected,
            metrics=metrics,
            exact_isin_prior_bar_count=exact_prior,
            exact_isin_action_bar_count=exact_action,
            potentially_relevant_missing_isin_bar_count=missing_count,
            first_candidate_action_date=(
                action_candidates[0].trading_date if action_candidates else None
            ),
            first_market_session_date=first_market_session,
            action_search_end_date=action_search_end,
            action_session_delay_market_sessions=action_session_delay,
            pre_event_gap_market_sessions=pre_event_gap,
        )

    def _govern_supplemental_action_candidates(
        self,
        connection: duckdb.DuckDBPyConnection,
        *,
        event_id: str,
        symbol: str,
        series: str,
        isin: str,
        effective_date: date,
        end_exclusive: date | None,
    ) -> tuple[
        tuple[RawCanonicalCandle, ...],
        tuple[GovernedCandleRecord, ...],
        tuple[RejectedCandleRecord, ...],
        bool,
    ]:
        supplements = tuple(
            item
            for item in self._security_transition_supplements
            if item.predecessor_symbol == symbol
            and item.predecessor_series == series
            and item.predecessor_isin == isin
            and item.effective_date >= effective_date
            and (end_exclusive is None or item.effective_date < end_exclusive)
        )
        candidates: list[RawCanonicalCandle] = []
        governed: list[GovernedCandleRecord] = []
        rejected: list[RejectedCandleRecord] = []
        duplicate = False
        for supplement in supplements:
            rows = _candidate_rows(
                connection,
                symbols=(supplement.successor_symbol,),
                series=(supplement.successor_series,),
                isin=supplement.successor_isin,
                effective_date=supplement.effective_date,
                prior=False,
                end_exclusive=end_exclusive,
            )
            candidates.extend(rows)
            first_date = min((item.trading_date for item in rows), default=None)
            first_rows = tuple(item for item in rows if item.trading_date == first_date)
            if len(first_rows) > 1:
                duplicate = True
                rejected.extend(
                    _reject(
                        item,
                        GovernedCandleIdentityState.DUPLICATE_CANONICAL_CANDLE,
                        "ACTION",
                    )
                    for item in first_rows
                )
                continue
            if not first_rows:
                continue
            candle = first_rows[0]
            if not candle.source_sha256:
                rejected.append(
                    _reject(
                        candle,
                        GovernedCandleIdentityState.SOURCE_HASH_MISSING,
                        "ACTION",
                    )
                )
                continue
            if (
                candle.symbol.upper() != supplement.successor_symbol
                or candle.series.upper() != supplement.successor_series
                or (
                    str(candle.isin or "").upper()
                    and str(candle.isin or "").upper() != supplement.successor_isin
                )
            ):
                rejected.append(
                    _reject(
                        candle,
                        GovernedCandleIdentityState.IDENTITY_CONFLICT,
                        "ACTION",
                    )
                )
                continue
            if (
                min(
                    candle.open_price,
                    candle.high_price,
                    candle.low_price,
                    candle.close_price,
                )
                <= 0
            ):
                rejected.append(
                    _reject(
                        candle,
                        GovernedCandleIdentityState.NON_POSITIVE_PRICE,
                        "ACTION",
                    )
                )
                continue
            source_ids = tuple(
                sorted(source.source_id for source in supplement.sources)
            )
            source_hashes = tuple(
                sorted(source.source_sha256 for source in supplement.sources)
            )
            governed.append(
                GovernedCandleRecord(
                    candle=candle,
                    identity_state=(
                        GovernedCandleIdentityState.CERTIFIED_OFFICIAL_ISIN_TRANSITION_CANDLE
                    ),
                    role="ACTION",
                    bridge_evidence=BridgeEvidence(
                        decision=("CERTIFIED_OFFICIAL_SECURITY_TRADING_TRANSITION"),
                        interval_ids=(supplement.supplement_id,),
                        official_event_ids=(event_id,),
                        official_source_ids=source_ids,
                        source_contract_id=SUPPLEMENT_CONTRACT_VERSION,
                        source_report_sha256=_stable_id(
                            supplement.supplement_id,
                            supplement.effective_date.isoformat(),
                            *source_hashes,
                        ),
                    ),
                )
            )
        return (
            tuple(sorted(candidates, key=lambda item: item.trading_date)),
            tuple(sorted(governed, key=lambda item: item.candle.trading_date)),
            tuple(
                sorted(
                    rejected,
                    key=lambda item: (
                        item.candle.trading_date,
                        item.reason.value,
                    ),
                )
            ),
            duplicate,
        )

    def _next_material_action_date(
        self,
        *,
        event_id: str,
        identity: str,
        symbol: str,
        series: str,
        effective_date: date,
    ) -> date | None:
        dates = {
            item.effective_date
            for candidate_event_id, item in self._official_event_evidence.items()
            if candidate_event_id != event_id
            and item.effective_date > effective_date
            and item.identity == identity
            and item.symbol == symbol
            and series in item.series
            and item.action_type in _MATERIAL_CONTINUITY_ACTION_TYPES
        }
        return min(dates) if dates else None

    def _material_transition_evidence(
        self,
        connection: duckdb.DuckDBPyConnection,
        *,
        symbol: str,
        series: str,
        effective_date: date,
        candidate_symbols: Sequence[str],
    ) -> tuple[OfficialIsinTransitionEvidence, ...]:
        events = tuple(
            sorted(
                (
                    item
                    for item in self._official_event_evidence.values()
                    if item.symbol == symbol
                    and series in item.series
                    and item.effective_date <= effective_date
                    and item.action_type
                    in (_MATERIAL_CONTINUITY_ACTION_TYPES - {"COMPOSITE", "RIGHTS"})
                ),
                key=lambda item: (item.effective_date, item.event_id),
            )
        )
        transitions = list(self._transition_evidence)
        for index, evidence in enumerate(events):
            next_date = next(
                (
                    item.effective_date
                    for item in events[index + 1 :]
                    if item.effective_date > evidence.effective_date
                ),
                None,
            )
            prior = _candidate_rows(
                connection,
                symbols=candidate_symbols,
                series=(series,),
                isin=evidence.isin,
                effective_date=evidence.effective_date,
                prior=True,
            )
            action = _candidate_rows(
                connection,
                symbols=candidate_symbols,
                series=(series,),
                isin=evidence.isin,
                effective_date=evidence.effective_date,
                prior=False,
                end_exclusive=next_date,
            )
            derived = _official_action_session_transitions(
                event_evidence=evidence,
                prior_candidates=prior,
                action_candidates=action,
                event_isin=evidence.isin,
                symbol=symbol,
                series=series,
                candidate_symbols=candidate_symbols,
                existing_transitions=tuple(transitions),
            )
            for item in derived:
                if item not in transitions:
                    transitions.append(item)
        return tuple(
            sorted(
                transitions,
                key=lambda item: (
                    item.effective_date,
                    item.from_isin,
                    item.to_isin,
                    item.event_id,
                ),
            )
        )

    def _govern_candidates(
        self,
        rows: Sequence[RawCanonicalCandle],
        *,
        identity: str,
        symbol: str,
        series: str,
        isin: str,
        role: str,
        stop_after_first: bool = False,
        required_count: int | None = None,
        allow_equity_series_transition: bool = False,
        official_event_evidence: OfficialEventDateIdentityEvidence | None = None,
        transition_evidence: Sequence[OfficialIsinTransitionEvidence] = (),
        event_effective_date: date | None = None,
    ) -> tuple[
        tuple[GovernedCandleRecord, ...],
        tuple[RejectedCandleRecord, ...],
        bool,
    ]:
        by_date: dict[date, list[RawCanonicalCandle]] = defaultdict(list)
        for row in rows:
            by_date[row.trading_date].append(row)
        governed: list[GovernedCandleRecord] = []
        rejected: list[RejectedCandleRecord] = []
        duplicate = False
        trading_dates = sorted(by_date, reverse=role == "PRIOR")
        quota_reached = False
        for trading_date in trading_dates:
            candidates = by_date[trading_date]
            exact_series = [
                item for item in candidates if item.series.upper() == series
            ]
            if len(exact_series) == 1:
                candidates = exact_series
            if len(candidates) != 1:
                duplicate = True
                rejected.extend(
                    RejectedCandleRecord(
                        candle=item,
                        reason=GovernedCandleIdentityState.DUPLICATE_CANONICAL_CANDLE,
                        role=role,
                    )
                    for item in candidates
                )
                continue
            if quota_reached:
                observed_isin = str(candidates[0].isin or "").upper()
                if not observed_isin or observed_isin == isin:
                    continue
            accepted, rejection = self.govern_candle(
                candidates[0],
                identity=identity,
                symbol=symbol,
                series=series,
                isin=isin,
                role=role,
                official_event_evidence=official_event_evidence,
                transition_evidence=transition_evidence,
                event_effective_date=event_effective_date,
                allow_equity_series_transition=allow_equity_series_transition,
            )
            if accepted is not None:
                governed.append(accepted)
                if stop_after_first:
                    break
                quota_reached = (
                    required_count is not None and len(governed) >= required_count
                )
            elif rejection is not None:
                rejected.append(rejection)
        return (
            tuple(sorted(governed, key=lambda item: item.candle.trading_date)),
            tuple(rejected),
            duplicate,
        )

    def govern_candle(
        self,
        candle: RawCanonicalCandle,
        *,
        identity: str,
        symbol: str,
        series: str,
        isin: str,
        role: str,
        official_event_evidence: OfficialEventDateIdentityEvidence | None = None,
        transition_evidence: Sequence[OfficialIsinTransitionEvidence] = (),
        event_effective_date: date | None = None,
        allow_equity_series_transition: bool = False,
    ) -> tuple[GovernedCandleRecord | None, RejectedCandleRecord | None]:
        candle_series = candle.series.upper()
        series_transition = (
            allow_equity_series_transition
            and candle_series != series
            and candle_series in _EQUITY_TRADING_SERIES
            and series in _EQUITY_TRADING_SERIES
        )
        if candle_series != series and not series_transition:
            return None, _reject(
                candle,
                GovernedCandleIdentityState.SERIES_CONFLICT,
                role,
            )
        if not candle.source_sha256:
            return None, _reject(
                candle,
                GovernedCandleIdentityState.SOURCE_HASH_MISSING,
                role,
            )
        if (
            min(
                candle.open_price,
                candle.high_price,
                candle.low_price,
                candle.close_price,
            )
            <= 0
        ):
            return None, _reject(
                candle,
                GovernedCandleIdentityState.NON_POSITIVE_PRICE,
                role,
            )
        observed_isin = str(candle.isin or "").upper()
        if observed_isin:
            if observed_isin != isin:
                transition_path = _governed_transition_path(
                    transition_evidence,
                    from_isin=isin,
                    to_isin=observed_isin,
                    as_of=candle.trading_date,
                )
                if (
                    not transition_path
                    and role == "PRIOR"
                    and event_effective_date is not None
                ):
                    transition_path = _governed_predecessor_path(
                        transition_evidence,
                        from_isin=observed_isin,
                        to_isin=isin,
                        after=candle.trading_date,
                        before=event_effective_date,
                    )
                if (
                    not transition_path
                    and role == "ACTION"
                    and event_effective_date is not None
                ):
                    transition_path = _governed_predecessor_path(
                        transition_evidence,
                        from_isin=observed_isin,
                        to_isin=isin,
                        after=event_effective_date,
                        before=candle.trading_date,
                        include_after=True,
                    )
                if transition_path:
                    alias_evidence: LegacyIsinReferenceBridgeResult | None = None
                    if candle.symbol.upper() != symbol:
                        alias_evidence = self.bridge.resolve_symbol_alias(
                            identity_key=identity,
                            event_symbol=symbol,
                            candle_symbol=candle.symbol,
                            series=series,
                            isin=isin,
                            reference_date=candle.trading_date,
                            allow_isin_transition_resolved_reuse=True,
                        )
                        if not alias_evidence.certified:
                            return None, _reject(
                                candle,
                                _bridge_rejection_state(alias_evidence.decision),
                                role,
                                bridge_decision=alias_evidence.decision.value,
                            )
                    alias_event_ids = (
                        alias_evidence.official_event_ids if alias_evidence else ()
                    )
                    alias_source_ids = (
                        tuple(
                            item.source_id for item in alias_evidence.official_sources
                        )
                        if alias_evidence
                        else ()
                    )
                    evidence = BridgeEvidence(
                        decision=(
                            "CERTIFIED_OFFICIAL_ISIN_AND_SYMBOL_TRANSITION_PATH"
                            if alias_evidence
                            else "CERTIFIED_OFFICIAL_PREDECESSOR_SUCCESSOR_PATH"
                        ),
                        interval_ids=(),
                        official_event_ids=tuple(
                            sorted(
                                {
                                    *(item.event_id for item in transition_path),
                                    *alias_event_ids,
                                }
                            )
                        ),
                        official_source_ids=tuple(
                            sorted(
                                {
                                    source_id
                                    for item in transition_path
                                    for source_id in item.source_ids
                                    if source_id
                                }
                                | {
                                    source_id
                                    for source_id in alias_source_ids
                                    if source_id
                                }
                            )
                        ),
                        source_contract_id=(
                            "DSI-010B3-OFFICIAL-ISIN-TRANSITION-v1.0.0"
                        ),
                        source_report_sha256=_stable_id(
                            "combined-identity-transition",
                            _stable_transition_report_hash(transition_path),
                            (
                                alias_evidence.source_report_sha256
                                if alias_evidence
                                else ""
                            ),
                            *alias_event_ids,
                        ),
                    )
                    return (
                        GovernedCandleRecord(
                            candle=candle,
                            identity_state=(
                                GovernedCandleIdentityState.CERTIFIED_OFFICIAL_ISIN_TRANSITION_CANDLE
                            ),
                            role=role,
                            bridge_evidence=evidence,
                        ),
                        None,
                    )
                return None, _reject(
                    candle,
                    GovernedCandleIdentityState.EXPLICIT_ISIN_MISMATCH,
                    role,
                )
            identity_state = (
                GovernedCandleIdentityState.CERTIFIED_OFFICIAL_SERIES_TRANSITION_CANDLE
                if series_transition
                else GovernedCandleIdentityState.EXACT_ISIN_CANDLE
            )
            return (
                GovernedCandleRecord(
                    candle=candle,
                    identity_state=identity_state,
                    role=role,
                    bridge_evidence=(
                        BridgeEvidence(
                            decision=("CERTIFIED_EXACT_ISIN_EQUITY_SERIES_TRANSITION"),
                            interval_ids=(),
                            official_event_ids=(),
                            official_source_ids=(),
                            source_contract_id=(
                                "DSI-010B5-EXACT-ISIN-SERIES-TRANSITION-v1.0.0"
                            ),
                            source_report_sha256=_stable_id(
                                "exact-isin-equity-series-transition",
                                identity,
                                symbol,
                                series,
                                candle_series,
                                candle.trading_date.isoformat(),
                                candle.source_sha256 or "",
                            ),
                        )
                        if series_transition
                        else None
                    ),
                ),
                None,
            )
        if candle.symbol.upper() != symbol:
            alias_result = self.bridge.resolve_symbol_alias(
                identity_key=identity,
                event_symbol=symbol,
                candle_symbol=candle.symbol,
                series=series,
                isin=isin,
                reference_date=candle.trading_date,
            )
            exact_official_action_alias = (
                official_event_evidence is not None
                and role == "ACTION"
                and candle.trading_date == official_event_evidence.effective_date
                and official_event_evidence.identity == identity
                and official_event_evidence.symbol == symbol
                and series in official_event_evidence.series
                and official_event_evidence.isin == isin
            )
            if not alias_result.certified and exact_official_action_alias:
                alias_result = self.bridge.resolve_symbol_alias(
                    identity_key=identity,
                    event_symbol=symbol,
                    candle_symbol=candle.symbol,
                    series=series,
                    isin=isin,
                    reference_date=candle.trading_date,
                    allow_isin_transition_resolved_reuse=True,
                )
            event_bound_alias = False
            if not alias_result.certified and official_event_evidence is not None:
                alias_result = self.bridge.resolve_symbol_alias_bound_to_official_event(
                    identity_key=identity,
                    event_symbol=symbol,
                    candle_symbol=candle.symbol,
                    series=series,
                    isin=isin,
                    reference_date=candle.trading_date,
                    event_source_ids=official_event_evidence.source_ids,
                )
                event_bound_alias = alias_result.certified
            if alias_result.certified:
                if event_bound_alias:
                    assert official_event_evidence is not None
                    return (
                        GovernedCandleRecord(
                            candle=candle,
                            identity_state=(
                                GovernedCandleIdentityState.CERTIFIED_DATED_BRIDGE_CANDLE
                            ),
                            role=role,
                            bridge_evidence=_event_bound_bridge_evidence(
                                alias_result,
                                official_event_evidence,
                            ),
                        ),
                        None,
                    )
                if not exact_official_action_alias:
                    return (
                        GovernedCandleRecord(
                            candle=candle,
                            identity_state=(
                                GovernedCandleIdentityState.CERTIFIED_DATED_BRIDGE_CANDLE
                            ),
                            role=role,
                            bridge_evidence=_bridge_evidence(alias_result),
                        ),
                        None,
                    )
                assert official_event_evidence is not None
                event_ids = set(alias_result.official_event_ids)
                source_ids = {item.source_id for item in alias_result.official_sources}
                event_ids.add(official_event_evidence.event_id)
                source_ids.update(official_event_evidence.source_ids)
                return (
                    GovernedCandleRecord(
                        candle=candle,
                        identity_state=(
                            GovernedCandleIdentityState.CERTIFIED_DATED_BRIDGE_CANDLE
                        ),
                        role=role,
                        bridge_evidence=BridgeEvidence(
                            decision=(
                                "CERTIFIED_EXACT_ACTION_IDENTITY_AND_SYMBOL_TRANSITION"
                            ),
                            interval_ids=(),
                            official_event_ids=tuple(sorted(event_ids)),
                            official_source_ids=tuple(sorted(source_ids)),
                            source_contract_id=(
                                "DSI-010B4-EXACT-ACTION-SYMBOL-BRIDGE-v1.0.0"
                            ),
                            source_report_sha256=_stable_id(
                                "exact-action-symbol-bridge",
                                alias_result.source_report_sha256,
                                official_event_evidence.source_report_sha256,
                                *sorted(event_ids),
                            ),
                        ),
                    ),
                    None,
                )
            return None, _reject(
                candle,
                _bridge_rejection_state(alias_result.decision),
                role,
                bridge_decision=alias_result.decision.value,
            )
        if official_event_evidence is not None and official_event_evidence.certifies(
            candle,
            identity=identity,
            symbol=symbol,
            series=series,
            isin=isin,
            role=role,
            allow_equity_series_transition=allow_equity_series_transition,
        ):
            evidence = BridgeEvidence(
                decision=(
                    "CERTIFIED_OFFICIAL_EVENT_DATE_IDENTITY"
                    if (
                        role == "ACTION"
                        and candle.trading_date
                        == official_event_evidence.effective_date
                    )
                    else "CERTIFIED_BOUNDED_OFFICIAL_ACTION_IDENTITY_INTERVAL"
                ),
                interval_ids=(),
                official_event_ids=(official_event_evidence.event_id,),
                official_source_ids=official_event_evidence.source_ids,
                source_contract_id="HTR-010B-OFFICIAL-EVENT-DATE-v1.0.0",
                source_report_sha256=(official_event_evidence.source_report_sha256),
            )
            return (
                GovernedCandleRecord(
                    candle=candle,
                    identity_state=(
                        GovernedCandleIdentityState.CERTIFIED_OFFICIAL_SERIES_TRANSITION_CANDLE
                        if series_transition
                        else GovernedCandleIdentityState.CERTIFIED_DATED_BRIDGE_CANDLE
                    ),
                    role=role,
                    bridge_evidence=evidence,
                ),
                None,
            )
        if (
            role == "PRIOR"
            and official_event_evidence is not None
            and official_event_evidence.action_type in _MATERIAL_CONTINUITY_ACTION_TYPES
            and candle.trading_date < official_event_evidence.effective_date
            and official_event_evidence.identity == identity
            and official_event_evidence.symbol == symbol
            and (
                series in official_event_evidence.series
                or (
                    series_transition
                    and candle_series in _EQUITY_TRADING_SERIES
                    and any(
                        item in _EQUITY_TRADING_SERIES
                        for item in official_event_evidence.series
                    )
                )
            )
            and official_event_evidence.isin == isin
            and self.bridge.certifies_event_bound_missing_isin(
                identity_key=identity,
                symbol=symbol,
                series=candle_series,
                isin=isin,
                reference_date=candle.trading_date,
            )
        ):
            return (
                GovernedCandleRecord(
                    candle=candle,
                    identity_state=(
                        GovernedCandleIdentityState.CERTIFIED_DATED_BRIDGE_CANDLE
                    ),
                    role=role,
                    bridge_evidence=BridgeEvidence(
                        decision=("CERTIFIED_A3_UNIQUE_EVENT_BOUND_PREDECESSOR_CANDLE"),
                        interval_ids=(),
                        official_event_ids=(official_event_evidence.event_id,),
                        official_source_ids=official_event_evidence.source_ids,
                        source_contract_id=(
                            "DSI-010B5-A3-EVENT-BOUND-PREDECESSOR-v1.0.0"
                        ),
                        source_report_sha256=_stable_id(
                            "a3-event-bound-predecessor",
                            self.bridge.source_report_sha256,
                            official_event_evidence.source_report_sha256,
                            identity,
                            symbol,
                            series,
                            candle_series,
                            isin,
                            candle.trading_date.isoformat(),
                        ),
                    ),
                ),
                None,
            )
        result = self.bridge.resolve(
            identity_key=identity,
            symbol=symbol,
            series=series,
            isin=isin,
            reference_date=candle.trading_date,
        )
        if not result.certified or (
            result.decision
            is not LegacyBridgeDecision.CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE
        ):
            reason = _bridge_rejection_state(result.decision)
            return None, _reject(
                candle,
                reason,
                role,
                bridge_decision=result.decision.value,
            )
        return (
            GovernedCandleRecord(
                candle=candle,
                identity_state=(
                    GovernedCandleIdentityState.CERTIFIED_DATED_BRIDGE_CANDLE
                ),
                role=role,
                bridge_evidence=_bridge_evidence(result),
            ),
            None,
        )


def _governed_transition_path(
    population: Sequence[OfficialIsinTransitionEvidence],
    *,
    from_isin: str,
    to_isin: str,
    as_of: date,
) -> tuple[OfficialIsinTransitionEvidence, ...]:
    current = from_isin
    path: list[OfficialIsinTransitionEvidence] = []
    visited = {current}
    while current != to_isin:
        candidates = tuple(
            item
            for item in population
            if item.from_isin == current and item.effective_date <= as_of
        )
        if not candidates:
            return ()
        latest_date = max(item.effective_date for item in candidates)
        latest = tuple(
            item for item in candidates if item.effective_date == latest_date
        )
        successors = {item.to_isin for item in latest}
        if len(successors) != 1:
            return ()
        selected = min(latest, key=lambda item: item.event_id)
        current = selected.to_isin
        if current in visited:
            return ()
        visited.add(current)
        path.append(selected)
    return tuple(path)


def _governed_predecessor_path(
    population: Sequence[OfficialIsinTransitionEvidence],
    *,
    from_isin: str,
    to_isin: str,
    after: date,
    before: date,
    include_after: bool = False,
) -> tuple[OfficialIsinTransitionEvidence, ...]:
    current = from_isin
    path: list[OfficialIsinTransitionEvidence] = []
    visited = {current}
    while current != to_isin:
        candidates = tuple(
            item
            for item in population
            if item.from_isin == current
            and (
                after < item.effective_date
                or (include_after and item.effective_date == after)
            )
            and item.effective_date <= before
        )
        if not candidates:
            return ()
        earliest_date = min(item.effective_date for item in candidates)
        earliest = tuple(
            item for item in candidates if item.effective_date == earliest_date
        )
        successors = {item.to_isin for item in earliest}
        if len(successors) != 1:
            return ()
        selected = min(earliest, key=lambda item: item.event_id)
        current = selected.to_isin
        if current in visited:
            return ()
        visited.add(current)
        path.append(selected)
    return tuple(path)


def _official_action_session_transitions(
    *,
    event_evidence: OfficialEventDateIdentityEvidence | None,
    prior_candidates: Sequence[RawCanonicalCandle],
    action_candidates: Sequence[RawCanonicalCandle],
    event_isin: str,
    symbol: str,
    series: str,
    candidate_symbols: Sequence[str],
    existing_transitions: Sequence[OfficialIsinTransitionEvidence] = (),
) -> tuple[OfficialIsinTransitionEvidence, ...]:
    if event_evidence is None:
        return ()
    if event_evidence.action_type not in (
        _MATERIAL_CONTINUITY_ACTION_TYPES - {"COMPOSITE", "RIGHTS"}
    ):
        return ()
    governed_symbols = {item.upper() for item in (*candidate_symbols, symbol) if item}
    eligible_prior = tuple(
        row
        for row in prior_candidates
        if row.symbol.upper() in governed_symbols
        and row.series.upper() == series
        and str(row.isin or "").upper()
        and row.source_sha256
    )
    if not eligible_prior:
        return ()
    latest_prior_date = max(row.trading_date for row in eligible_prior)
    latest_prior_rows = tuple(
        row for row in eligible_prior if row.trading_date == latest_prior_date
    )
    latest_prior_isins = {str(row.isin or "").upper() for row in latest_prior_rows}
    if len(latest_prior_rows) != 1 or len(latest_prior_isins) != 1:
        return ()
    predecessor_isin = next(iter(latest_prior_isins))
    if predecessor_isin != event_isin:
        source_hash = str(latest_prior_rows[0].source_sha256)
        evidence_hash = sha256(
            "|".join(
                (
                    event_evidence.source_report_sha256,
                    *event_evidence.source_sha256,
                    source_hash,
                    event_evidence.event_id,
                    predecessor_isin,
                    event_isin,
                    event_evidence.effective_date.isoformat(),
                )
            ).encode()
        ).hexdigest()
        return (
            OfficialIsinTransitionEvidence(
                from_isin=predecessor_isin,
                to_isin=event_isin,
                effective_date=event_evidence.effective_date,
                event_id=event_evidence.event_id,
                source_ids=(
                    *event_evidence.source_ids,
                    f"canonical-daily-candle-sha256:{source_hash}",
                ),
                source_report_sha256=evidence_hash,
            ),
        )
    eligible = tuple(
        row
        for row in action_candidates
        if row.symbol.upper() in governed_symbols
        and row.series.upper() == series
        and str(row.isin or "").upper()
        and str(row.isin or "").upper() != predecessor_isin
        and row.trading_date >= event_evidence.effective_date
        and row.source_sha256
    )
    if not eligible:
        return ()
    if not any(
        row.symbol.upper() in governed_symbols
        and row.series.upper() == series
        and str(row.isin or "").upper() in {"", predecessor_isin}
        and row.trading_date < event_evidence.effective_date
        and row.source_sha256
        for row in prior_candidates
    ):
        return ()
    first_date = min(row.trading_date for row in eligible)
    first_rows = tuple(row for row in eligible if row.trading_date == first_date)
    observed_isins = {str(row.isin or "").upper() for row in first_rows}
    if len(first_rows) != 1 or len(observed_isins) != 1:
        return ()
    observed_isin = next(iter(observed_isins))
    if predecessor_isin != event_isin:
        stale_event_path = _governed_transition_path(
            existing_transitions,
            from_isin=event_isin,
            to_isin=predecessor_isin,
            as_of=event_evidence.effective_date,
        )
        event_is_successor = observed_isin == event_isin
        if not stale_event_path and not event_is_successor:
            return ()
    earlier_non_event_isins = {
        str(row.isin or "").upper()
        for row in action_candidates
        if row.trading_date < first_date
        and str(row.isin or "").upper()
        and str(row.isin or "").upper() != event_isin
    }
    if earlier_non_event_isins:
        return ()
    source_hash = str(first_rows[0].source_sha256)
    evidence_hash = sha256(
        "|".join(
            (
                event_evidence.source_report_sha256,
                *event_evidence.source_sha256,
                source_hash,
                event_evidence.event_id,
                predecessor_isin,
                observed_isin,
                event_evidence.effective_date.isoformat(),
            )
        ).encode()
    ).hexdigest()
    return (
        OfficialIsinTransitionEvidence(
            from_isin=predecessor_isin,
            to_isin=observed_isin,
            effective_date=event_evidence.effective_date,
            event_id=event_evidence.event_id,
            source_ids=(
                *event_evidence.source_ids,
                f"canonical-daily-candle-sha256:{source_hash}",
            ),
            source_report_sha256=evidence_hash,
        ),
    )


def _stable_transition_report_hash(
    path: Sequence[OfficialIsinTransitionEvidence],
) -> str:
    return sha256(
        "|".join(
            f"{item.event_id}:{item.source_report_sha256}" for item in path
        ).encode()
    ).hexdigest()


def _load_official_event_date_evidence(
    output: Path,
    *,
    identity_supplements: Sequence[OfficialSecurityIdentitySupplement] = (),
) -> dict[str, OfficialEventDateIdentityEvidence]:
    event_path = _unique_file(output, "htr010b_canonical_events.json")
    source_path = _unique_file(output, "htr010b_source_completeness.json")
    source_rows = _list_or_wrapped_records(source_path)
    source_sha = {
        str(row.get("source_id") or ""): str(row.get("source_checksum") or "")
        for row in source_rows
        if row.get("acquisition_state") == "AVAILABLE_IMMUTABLE"
        and row.get("immutable_reuse_state") == "CHECKSUM_VERIFIED"
        and _sha256_value(row.get("source_checksum"))
    }
    report_sha = sha256(event_path.read_bytes()).hexdigest()
    parsed: list[dict[str, Any]] = []
    for row in _list_or_wrapped_records(event_path):
        event_id = str(row.get("canonical_event_id") or "")
        source_id = str(row.get("source_id") or "")
        identity = str(row.get("governed_identity_id") or "")
        isin = str(row.get("isin") or "").upper()
        symbol = str(row.get("symbol") or "").upper()
        effective_date = _iso_date(row.get("effective_date"))
        series = tuple(
            sorted(
                {
                    str(item).upper()
                    for item in row.get("series_applicability", ())
                    if str(item).strip()
                }
            )
        )
        if (
            not event_id
            or not identity
            or identity != f"nse:isin:{isin}"
            or not symbol
            or not series
            or effective_date is None
            or source_id not in source_sha
            or str(row.get("assignment_confidence") or "") != "HIGH"
            or str(row.get("assignment_method") or "") != "OFFICIAL_ISIN_INTERVAL"
        ):
            continue
        parsed.append(
            {
                "event_id": event_id,
                "identity": identity,
                "symbol": symbol,
                "series": series,
                "isin": isin,
                "effective_date": effective_date,
                "source_id": source_id,
                "source_sha256": source_sha[source_id],
                "action_type": str(row.get("action_type") or ""),
            }
        )
    by_symbol_series: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in parsed:
        for series_name in row["series"]:
            by_symbol_series[(str(row["symbol"]), series_name)].append(row)
    evidence: dict[str, OfficialEventDateIdentityEvidence] = {}
    for row in parsed:
        prior_rows: list[dict[str, Any]] = []
        subsequent_rows: list[dict[str, Any]] = []
        competing = False
        for series_name in row["series"]:
            population = by_symbol_series[(str(row["symbol"]), series_name)]
            same_identity = [
                item
                for item in population
                if item["identity"] == row["identity"]
                and item["effective_date"] < row["effective_date"]
            ]
            if not same_identity:
                prior = None
            else:
                prior = min(same_identity, key=lambda item: item["effective_date"])
                if any(
                    item["identity"] != row["identity"]
                    and prior["effective_date"]
                    <= item["effective_date"]
                    <= row["effective_date"]
                    for item in population
                ):
                    competing = True
                    break
                prior_rows.append(prior)
            subsequent = tuple(
                item
                for item in population
                if item["identity"] == row["identity"]
                and item["effective_date"] > row["effective_date"]
            )
            if subsequent:
                next_row = min(
                    subsequent,
                    key=lambda item: (item["effective_date"], item["event_id"]),
                )
                if any(
                    item["identity"] != row["identity"]
                    and row["effective_date"]
                    <= item["effective_date"]
                    <= next_row["effective_date"]
                    for item in population
                ):
                    competing = True
                    break
                subsequent_rows.append(next_row)
        interval_valid_from = (
            min(item["effective_date"] for item in prior_rows)
            if prior_rows and not competing
            else None
        )
        matching_identity_supplements = tuple(
            item
            for item in identity_supplements
            if item.identity_key == row["identity"]
            and item.symbol == row["symbol"]
            and item.series in row["series"]
            and item.isin == row["isin"]
            and item.valid_from <= row["effective_date"]
        )
        if matching_identity_supplements and not competing:
            supplement_start = min(
                item.valid_from for item in matching_identity_supplements
            )
            interval_valid_from = (
                min(interval_valid_from, supplement_start)
                if interval_valid_from is not None
                else supplement_start
            )
        interval_valid_to = (
            min(item["effective_date"] for item in subsequent_rows)
            if subsequent_rows and not competing
            else None
        )
        evidence_source_rows = [
            row,
            *(prior_rows if interval_valid_from else ()),
            *(subsequent_rows if interval_valid_to else ()),
            *(
                {
                    "source_id": item.supplement_id,
                    "source_sha256": item.source_sha256,
                }
                for item in matching_identity_supplements
            ),
        ]
        evidence[str(row["event_id"])] = OfficialEventDateIdentityEvidence(
            event_id=str(row["event_id"]),
            identity=str(row["identity"]),
            symbol=str(row["symbol"]),
            series=tuple(row["series"]),
            isin=str(row["isin"]),
            effective_date=row["effective_date"],
            source_ids=tuple(
                sorted({str(item["source_id"]) for item in evidence_source_rows})
            ),
            source_sha256=tuple(
                sorted({str(item["source_sha256"]) for item in evidence_source_rows})
            ),
            source_report_sha256=report_sha,
            interval_valid_from=interval_valid_from,
            interval_valid_to=interval_valid_to,
            action_type=str(row["action_type"]),
        )
    return evidence


def _load_official_isin_transition_evidence(
    output: Path,
) -> tuple[OfficialIsinTransitionEvidence, ...]:
    transition_path = _unique_file(output, "htr010b_identity_transitions.json")
    report_sha = sha256(transition_path.read_bytes()).hexdigest()
    evidence: list[OfficialIsinTransitionEvidence] = []
    for row in _list_or_wrapped_records(transition_path):
        old_isin = str(row.get("old_isin") or "").upper()
        new_isin = str(row.get("new_isin") or "").upper()
        effective_date = _iso_date(row.get("effective_date"))
        event_id = str(row.get("transition_id") or "")
        source_id = str(row.get("official_source") or "")
        if (
            not _isin_value(old_isin)
            or not _isin_value(new_isin)
            or old_isin == new_isin
            or effective_date is None
            or not event_id
            or not source_id
            or str(row.get("confidence_state") or "") != "HIGH"
        ):
            continue
        evidence.append(
            OfficialIsinTransitionEvidence(
                from_isin=old_isin,
                to_isin=new_isin,
                effective_date=effective_date,
                event_id=event_id,
                source_ids=(source_id,),
                source_report_sha256=report_sha,
            )
        )
    return tuple(
        sorted(
            evidence,
            key=lambda item: (
                item.effective_date,
                item.from_isin,
                item.to_isin,
                item.event_id,
            ),
        )
    )


def _list_or_wrapped_records(path: Path) -> tuple[dict[str, Any], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"expected JSON record array: {path}")
    return tuple(rows)


def _sha256_value(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text.lower())


def _isin_value(value: object) -> bool:
    text = str(value or "").upper()
    return len(text) == 12 and text.startswith("INE") and text.isalnum()


def _iso_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _load_b1_cases(
    output: Path,
    contract: SignedBridgeContinuitySourceContract,
) -> tuple[tuple[tuple[str, str], ...], tuple[dict[str, Any], ...]]:
    expected = contract.expected_checksums()
    paths = {name: _unique_file(output, name) for name in expected}
    actual = {
        name: sha256(path.read_bytes()).hexdigest() for name, path in paths.items()
    }
    mismatches = {
        name: (expected[name], actual[name])
        for name in expected
        if expected[name] != actual[name]
    }
    if mismatches:
        raise ValueError(f"signed DSI-010B1 evidence checksum mismatch: {mismatches}")
    certificate = _object(paths["legacy_rights_reference_bridge_certificate.json"])
    summary = _object(paths["legacy_rights_reference_bridge_summary.json"])
    if certificate.get("eligible_bridge_count") != 18:
        raise ValueError("DSI-010B1 certificate does not bind 18 eligible bridges")
    if summary.get("eligible_bridge_count") != 18:
        raise ValueError("DSI-010B1 summary does not bind 18 eligible bridges")
    if certificate.get("production_influence") is not False:
        raise ValueError("DSI-010B1 production influence must be false")
    cases = _records(paths["legacy_rights_reference_bridge_cases.json"])
    return tuple(sorted(actual.items())), cases


def _validate_case_identity(
    case: Mapping[str, Any],
    *,
    identity: str,
    symbol: str,
    series: str,
    isin: str,
    effective_date: date,
    factor: Mapping[str, Any],
    bridge: LegacyIsinReferenceBridge,
) -> None:
    expected = {
        "identity_key": identity,
        "symbol": symbol,
        "series": series,
        "event_isin": isin,
        "effective_date": effective_date.isoformat(),
        "factor_id": str(factor.get("factor_id") or ""),
    }
    for key, value in expected.items():
        observed = case.get(key)
        normalized = (
            str(observed or "").upper()
            if key in {"symbol", "series"}
            else str(observed or "")
        )
        wanted = value.upper() if key in {"symbol", "series"} else value
        if normalized != wanted:
            raise ValueError(
                f"DSI-010B1 case {key} mismatch for {case.get('event_id')}"
            )
    if case.get("bridge_decision") != (
        LegacyBridgeDecision.CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE.value
    ):
        raise ValueError("DSI-010B1 case is not bridge certified")
    if case.get("original_candle_isin_remained_missing") is not True:
        raise ValueError("DSI-010B1 reference candle ISIN was not preserved missing")
    if factor.get("reference_price_bridge_contract_version") != (
        LEGACY_ISIN_REFERENCE_BRIDGE_CONTRACT_VERSION
    ):
        raise ValueError("factor bridge contract version mismatch")
    if factor.get("reference_price_bridge_source_contract_id") != (
        bridge.source_contract.contract_id
    ):
        raise ValueError("factor bridge source contract mismatch")
    if factor.get("reference_price_bridge_source_report_sha256") != (
        bridge.source_report_sha256
    ):
        raise ValueError("factor bridge report hash mismatch")


def _validate_material_action_identity(
    *,
    identity: str,
    symbol: str,
    series: str,
    isin: str,
) -> None:
    if not identity:
        raise ValueError("governed identity is required for continuity context")
    if not symbol:
        raise ValueError("event symbol is required for continuity context")
    if not series:
        raise ValueError("event series is required for continuity context")
    if not isin:
        raise ValueError("event ISIN is required for continuity context")


def _bridge_evidence(
    result: LegacyIsinReferenceBridgeResult,
) -> BridgeEvidence:
    return BridgeEvidence(
        decision=result.decision.value,
        interval_ids=tuple(
            sorted(
                item.interval_id
                for item in (
                    result.membership_interval,
                    result.symbol_interval,
                    result.tradability_interval,
                )
                if item is not None
            )
        ),
        official_event_ids=result.official_event_ids,
        official_source_ids=tuple(item.source_id for item in result.official_sources),
        source_contract_id=result.source_contract_id,
        source_report_sha256=result.source_report_sha256,
    )


def _event_bound_bridge_evidence(
    result: LegacyIsinReferenceBridgeResult,
    event: OfficialEventDateIdentityEvidence,
) -> BridgeEvidence:
    event_ids = tuple(sorted({event.event_id, *result.official_event_ids}))
    source_ids = tuple(
        sorted(
            {
                *event.source_ids,
                *(item.source_id for item in result.official_sources),
            }
        )
    )
    return BridgeEvidence(
        decision="CERTIFIED_OFFICIAL_EVENT_BOUND_SYMBOL_TRANSITION",
        interval_ids=(),
        official_event_ids=event_ids,
        official_source_ids=source_ids,
        source_contract_id="DSI-010B5-OFFICIAL-EVENT-SYMBOL-BRIDGE-v1.0.0",
        source_report_sha256=_stable_id(
            "event-bound-symbol-transition",
            result.source_report_sha256,
            event.source_report_sha256,
            *event_ids,
            *source_ids,
        ),
    )


def _candidate_rows(
    connection: duckdb.DuckDBPyConnection,
    *,
    symbols: Sequence[str],
    series: Sequence[str],
    isin: str,
    effective_date: date,
    prior: bool,
    end_exclusive: date | None = None,
) -> tuple[RawCanonicalCandle, ...]:
    normalized_symbols = tuple(
        sorted({str(symbol).upper() for symbol in symbols if str(symbol).strip()})
    )
    if not normalized_symbols:
        return ()
    symbol_placeholders = ",".join("?" for _ in normalized_symbols)
    normalized_series = tuple(
        sorted({str(item).upper() for item in series if str(item).strip()})
    )
    if not normalized_series:
        return ()
    series_placeholders = ",".join("?" for _ in normalized_series)
    parameters: list[object]
    if prior:
        date_clause = "trading_date < ?"
        parameters = [effective_date]
        direction = "DESC"
        parameters.extend((*normalized_series, *normalized_symbols, isin))
    else:
        date_clause = "trading_date >= ?"
        parameters = [effective_date]
        if end_exclusive is not None:
            date_clause += " AND trading_date < ?"
            parameters.append(end_exclusive)
        direction = "ASC"
        parameters.extend((*normalized_series, *normalized_symbols, isin))
    rows = connection.execute(
        "SELECT * FROM (SELECT trading_date, upper(symbol), upper(series), "
        "upper(isin), open_price, high_price, low_price, close_price, volume, "
        "source_sha256 FROM daily_candle WHERE "
        + date_clause
        + f" AND upper(series) IN ({series_placeholders}) AND "
        f"((upper(symbol) IN ({symbol_placeholders})) OR (upper(isin)=?)) "
        "ORDER BY trading_date " + direction + ") ORDER BY trading_date " + direction,
        parameters,
    ).fetchall()
    return tuple(
        RawCanonicalCandle(
            trading_date=row[0],
            symbol=str(row[1] or ""),
            series=str(row[2] or ""),
            isin=str(row[3]) if row[3] else None,
            open_price=float(row[4]),
            high_price=float(row[5]),
            low_price=float(row[6]),
            close_price=float(row[7]),
            volume=int(row[8]),
            source_sha256=str(row[9]) if row[9] else None,
        )
        for row in rows
    )


def _first_market_session(
    connection: duckdb.DuckDBPyConnection,
    effective_date: date,
) -> date | None:
    row = connection.execute(
        "SELECT min(trading_date) FROM daily_candle WHERE trading_date>=?",
        [effective_date],
    ).fetchone()
    return row[0] if row and isinstance(row[0], date) else None


def _market_session_delay(
    connection: duckdb.DuckDBPyConnection,
    *,
    effective_date: date,
    selected_date: date,
) -> int:
    row = connection.execute(
        "SELECT count(DISTINCT trading_date) FROM daily_candle "
        "WHERE trading_date>=? AND trading_date<?",
        [effective_date, selected_date],
    ).fetchone()
    return int(row[0]) if row else 0


def _pre_event_market_session_gap(
    connection: duckdb.DuckDBPyConnection,
    *,
    selected_date: date,
    effective_date: date,
) -> int:
    row = connection.execute(
        "SELECT count(DISTINCT trading_date) FROM daily_candle "
        "WHERE trading_date>? AND trading_date<?",
        [selected_date, effective_date],
    ).fetchone()
    return int(row[0]) if row else 0


def _context_decision(
    *,
    selected_prior: tuple[GovernedCandleRecord, ...],
    action_bar: GovernedCandleRecord | None,
    duplicate: bool,
    signed_case: Mapping[str, Any] | None,
    factor: Mapping[str, Any],
    bridge: LegacyIsinReferenceBridge,
) -> ContinuityContextDecision:
    if duplicate:
        return ContinuityContextDecision.DUPLICATE_CANONICAL_CANDLE
    if action_bar is None:
        return ContinuityContextDecision.ACTION_SESSION_MISSING
    if len(selected_prior) < 2:
        return ContinuityContextDecision.INSUFFICIENT_ATR_HISTORY
    if signed_case is None:
        return ContinuityContextDecision.COMPLETE_GOVERNED_CONTINUITY_CONTEXT
    prior = selected_prior[-1].candle
    expected_date = _as_date(factor.get("reference_price_date"))
    if expected_date is None:
        expected_date = _as_date(signed_case.get("prior_candle_date"))
    if prior.trading_date != expected_date:
        return ContinuityContextDecision.REFERENCE_SESSION_MISMATCH
    expected_price = _number(factor.get("reference_price"))
    if expected_price is None or prior.close_price != expected_price:
        return ContinuityContextDecision.REFERENCE_PRICE_MISMATCH
    expected_source = str(factor.get("reference_price_source_sha256") or "")
    if (
        not expected_source
        or prior.source_sha256 != expected_source
        or signed_case.get("prior_candle_source_sha256") != expected_source
    ):
        return ContinuityContextDecision.REFERENCE_SOURCE_HASH_MISMATCH
    evidence = selected_prior[-1].bridge_evidence
    if (
        evidence is None
        or evidence.source_contract_id != bridge.source_contract.contract_id
        or evidence.source_report_sha256 != bridge.source_report_sha256
    ):
        return ContinuityContextDecision.BRIDGE_PROVENANCE_MISMATCH
    return ContinuityContextDecision.COMPLETE_GOVERNED_CONTINUITY_CONTEXT


def _metrics(
    prior: tuple[GovernedCandleRecord, ...],
    action: GovernedCandleRecord | None,
    factor: float | None,
) -> ContinuityMetrics:
    prior_bar = prior[-1].candle if prior else None
    action_candle = action.candle if action else None
    atr = _atr(tuple(item.as_bar() for item in prior[-14:]))
    previous_close = prior_bar.close_price if prior_bar else None
    action_open = action_candle.open_price if action_candle else None
    action_close = action_candle.close_price if action_candle else None
    inverse = 1.0 / factor if factor is not None and factor > 0 else None
    volumes = [item.candle.volume for item in prior]
    return ContinuityMetrics(
        previous_session=prior_bar.trading_date if prior_bar else None,
        action_session=action_candle.trading_date if action_candle else None,
        previous_close=previous_close,
        action_open=action_open,
        action_close=action_close,
        atr_before=atr,
        median_prior_volume=statistics.median(volumes) if volumes else None,
        raw_gap_atr=_gap(action_open, previous_close, atr, 1.0),
        adjusted_gap_atr=_gap(action_open, previous_close, atr, factor),
        inverse_adjusted_gap_atr=_gap(action_open, previous_close, atr, inverse),
        close_raw_gap_atr=_gap(action_close, previous_close, atr, 1.0),
        close_adjusted_gap_atr=_gap(action_close, previous_close, atr, factor),
    )


def _atr(rows: Sequence[tuple[Any, ...]]) -> float | None:
    if len(rows) < 2:
        return None
    ranges: list[float] = []
    previous_close: float | None = None
    for row in rows[-14:]:
        high = float(row[2])
        low = float(row[3])
        close = float(row[4])
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


def _gap(
    price: float | None,
    previous_close: float | None,
    atr: float | None,
    factor: float | None,
) -> float | None:
    if (
        price is None
        or previous_close is None
        or atr is None
        or atr <= 0
        or factor is None
        or factor <= 0
    ):
        return None
    return abs(price - (previous_close * factor)) / (atr * factor)


def _bridge_rejection_state(
    decision: LegacyBridgeDecision,
) -> GovernedCandleIdentityState:
    if decision is LegacyBridgeDecision.IDENTITY_MISMATCH:
        return GovernedCandleIdentityState.IDENTITY_CONFLICT
    if decision is LegacyBridgeDecision.SYMBOL_MISMATCH:
        return GovernedCandleIdentityState.SYMBOL_CONFLICT
    if decision is LegacyBridgeDecision.SERIES_MISMATCH:
        return GovernedCandleIdentityState.SERIES_CONFLICT
    if decision in {
        LegacyBridgeDecision.DATE_OUTSIDE_INTERVAL,
        LegacyBridgeDecision.NO_MATCHING_OFFICIAL_INTERVAL,
    }:
        return GovernedCandleIdentityState.DATE_OUTSIDE_CERTIFIED_INTERVAL
    if decision in {
        LegacyBridgeDecision.OVERLAPPING_IDENTITY_CONFLICT,
        LegacyBridgeDecision.SYMBOL_REUSE_CONFLICT,
        LegacyBridgeDecision.SYMBOL_CHANGE_BOUNDARY_UNRESOLVED,
        LegacyBridgeDecision.SERIES_TRANSITION_UNRESOLVED,
    }:
        return GovernedCandleIdentityState.IDENTITY_CONFLICT
    return GovernedCandleIdentityState.MISSING_ISIN_NO_CERTIFIED_BRIDGE


def _reject(
    candle: RawCanonicalCandle,
    reason: GovernedCandleIdentityState,
    role: str,
    *,
    bridge_decision: str | None = None,
) -> RejectedCandleRecord:
    return RejectedCandleRecord(
        candle=candle,
        reason=reason,
        role=role,
        bridge_decision=bridge_decision,
    )


def _empty_context(
    event_id: str,
    decision: ContinuityContextDecision,
) -> EventBarContext:
    metrics = ContinuityMetrics(
        previous_session=None,
        action_session=None,
        previous_close=None,
        action_open=None,
        action_close=None,
        atr_before=None,
        median_prior_volume=None,
        raw_gap_atr=None,
        adjusted_gap_atr=None,
        inverse_adjusted_gap_atr=None,
        close_raw_gap_atr=None,
        close_adjusted_gap_atr=None,
    )
    return EventBarContext(
        context_id=_stable_id("bridge-aware-continuity", event_id, decision.value),
        event_id=event_id,
        decision=decision,
        prior_window=ATRWindowEvidence((), (), None),
        action_bar=None,
        rejected_bars=(),
        metrics=metrics,
        exact_isin_prior_bar_count=0,
        exact_isin_action_bar_count=0,
        potentially_relevant_missing_isin_bar_count=0,
        first_candidate_action_date=None,
    )


def _number(value: object) -> float | None:
    if not isinstance(value, (str, int, float)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}:{sha256('|'.join(parts).encode()).hexdigest()}"


def _unique_file(root: Path, name: str) -> Path:
    matches = tuple(sorted(root.resolve().rglob(name)))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {name}, found {len(matches)}")
    return matches[0]


def _object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _records(path: Path) -> tuple[dict[str, Any], ...]:
    payload = _object(path)
    rows = payload.get("records")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"expected records object: {path}")
    return tuple(rows)


__all__ = [
    "BRIDGE_AWARE_CONTINUITY_CONTRACT_VERSION",
    "PRODUCTION_INFLUENCE",
    "SIGNED_DSI010B1_CONTINUITY_SOURCE_CONTRACT",
    "ATRWindowEvidence",
    "BridgeAwareContinuityContextProvider",
    "BridgeEvidence",
    "ContinuityContextDecision",
    "ContinuityMetrics",
    "EventBarContext",
    "FinalValidationEligibility",
    "GovernedCandleIdentityState",
    "GovernedCandleRecord",
    "RawCanonicalCandle",
    "RejectedCandleRecord",
    "SignedBridgeContinuitySourceContract",
]
