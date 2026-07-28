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
)

BRIDGE_AWARE_CONTINUITY_CONTRACT_VERSION = "DSI-010B2-BRIDGE-AWARE-CONTINUITY-v1.0.0"
PRODUCTION_INFLUENCE = False


class GovernedCandleIdentityState(StrEnum):
    """Identity disposition for one candidate canonical candle."""

    EXACT_ISIN_CANDLE = "EXACT_ISIN_CANDLE"
    CERTIFIED_DATED_BRIDGE_CANDLE = "CERTIFIED_DATED_BRIDGE_CANDLE"
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
    """Build immutable bar contexts only for signed DSI-010B1 cases."""

    def __init__(
        self,
        *,
        bridge: LegacyIsinReferenceBridge,
        cases: tuple[dict[str, Any], ...],
        source_checksums: tuple[tuple[str, str], ...],
        source_contract: SignedBridgeContinuitySourceContract,
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
        )

    @classmethod
    def from_fixture(
        cls,
        *,
        bridge: LegacyIsinReferenceBridge,
        cases: tuple[dict[str, Any], ...],
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
        )

    @property
    def event_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._cases))

    def supports(self, event_id: str) -> bool:
        return event_id in self._cases

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
        if signed_case is None:
            return _empty_context(
                event_id,
                ContinuityContextDecision.NO_SIGNED_BRIDGE_CASE,
            )
        identity = str(event.get("governed_identity_id") or "")
        symbol = str(event.get("symbol") or "").upper()
        isin = str(event.get("isin") or "").upper()
        normalized_series = series.upper()
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

        prior_candidates = _candidate_rows(
            connection,
            symbol=symbol,
            series=normalized_series,
            isin=isin,
            effective_date=effective_date,
            prior=True,
        )
        action_candidates = _candidate_rows(
            connection,
            symbol=symbol,
            series=normalized_series,
            isin=isin,
            effective_date=effective_date,
            prior=False,
        )
        admitted_prior, rejected_prior, duplicate_prior = self._govern_candidates(
            prior_candidates,
            identity=identity,
            symbol=symbol,
            series=normalized_series,
            isin=isin,
            role="PRIOR",
        )
        admitted_action, rejected_action, duplicate_action = self._govern_candidates(
            action_candidates,
            identity=identity,
            symbol=symbol,
            series=normalized_series,
            isin=isin,
            role="ACTION",
            stop_after_first=True,
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
            duplicate=duplicate_prior or duplicate_action,
            signed_case=signed_case,
            factor=factor,
            bridge=self.bridge,
        )
        atr_bars = selected_prior[-14:]
        atr = _atr(tuple(item.as_bar() for item in atr_bars))
        metrics = _metrics(
            selected_prior, action_bar, _number(factor.get("price_factor"))
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
        for trading_date in sorted(by_date):
            candidates = by_date[trading_date]
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
            accepted, rejection = self.govern_candle(
                candidates[0],
                identity=identity,
                symbol=symbol,
                series=series,
                isin=isin,
                role=role,
            )
            if accepted is not None:
                governed.append(accepted)
                if stop_after_first:
                    break
            elif rejection is not None:
                rejected.append(rejection)
        return tuple(governed), tuple(rejected), duplicate

    def govern_candle(
        self,
        candle: RawCanonicalCandle,
        *,
        identity: str,
        symbol: str,
        series: str,
        isin: str,
        role: str,
    ) -> tuple[GovernedCandleRecord | None, RejectedCandleRecord | None]:
        if candle.series.upper() != series:
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
                return None, _reject(
                    candle,
                    GovernedCandleIdentityState.EXPLICIT_ISIN_MISMATCH,
                    role,
                )
            return (
                GovernedCandleRecord(
                    candle=candle,
                    identity_state=GovernedCandleIdentityState.EXACT_ISIN_CANDLE,
                    role=role,
                    bridge_evidence=None,
                ),
                None,
            )
        if candle.symbol.upper() != symbol:
            return None, _reject(
                candle,
                GovernedCandleIdentityState.SYMBOL_CONFLICT,
                role,
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
        interval_ids = tuple(
            sorted(
                item.interval_id
                for item in (
                    result.membership_interval,
                    result.symbol_interval,
                    result.tradability_interval,
                )
                if item is not None
            )
        )
        evidence = BridgeEvidence(
            decision=result.decision.value,
            interval_ids=interval_ids,
            official_event_ids=result.official_event_ids,
            official_source_ids=tuple(
                item.source_id for item in result.official_sources
            ),
            source_contract_id=result.source_contract_id,
            source_report_sha256=result.source_report_sha256,
        )
        return (
            GovernedCandleRecord(
                candle=candle,
                identity_state=(
                    GovernedCandleIdentityState.CERTIFIED_DATED_BRIDGE_CANDLE
                ),
                role=role,
                bridge_evidence=evidence,
            ),
            None,
        )


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


def _candidate_rows(
    connection: duckdb.DuckDBPyConnection,
    *,
    symbol: str,
    series: str,
    isin: str,
    effective_date: date,
    prior: bool,
) -> tuple[RawCanonicalCandle, ...]:
    comparator = "<" if prior else ">="
    rows = connection.execute(
        "SELECT trading_date, upper(symbol), upper(series), upper(isin), "
        "open_price, high_price, low_price, close_price, volume, source_sha256 "
        "FROM daily_candle WHERE trading_date "
        + comparator
        + " ? AND upper(series)=? AND "
        "((upper(symbol)=?) OR (upper(isin)=?)) ORDER BY trading_date",
        [effective_date, series, symbol, isin],
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


def _context_decision(
    *,
    selected_prior: tuple[GovernedCandleRecord, ...],
    action_bar: GovernedCandleRecord | None,
    duplicate: bool,
    signed_case: Mapping[str, Any],
    factor: Mapping[str, Any],
    bridge: LegacyIsinReferenceBridge,
) -> ContinuityContextDecision:
    if duplicate:
        return ContinuityContextDecision.DUPLICATE_CANONICAL_CANDLE
    if action_bar is None:
        return ContinuityContextDecision.ACTION_SESSION_MISSING
    if len(selected_prior) < 2:
        return ContinuityContextDecision.INSUFFICIENT_ATR_HISTORY
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
