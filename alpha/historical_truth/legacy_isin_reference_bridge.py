"""Fail-closed dated identity bridge for legacy rights reference prices."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any

LEGACY_ISIN_REFERENCE_BRIDGE_CONTRACT_VERSION = (
    "HTR-010B1-LEGACY-ISIN-REFERENCE-BRIDGE-v1.0.0"
)
PRODUCTION_INFLUENCE = False

_HTR009A2_CONTRACT_VERSION = "HTR-009A2-v1.0.0"
_ISIN_PATTERN = re.compile(r"^IN[A-Z0-9]{10}$")
_OFFICIAL_PLACEHOLDER_ISIN_PATTERN = re.compile(r"^DUMMY[0-9]{7}$")
_COMPATIBLE_MEMBERSHIP_STATES = frozenset(
    {
        "CERTIFIED_ACTIVE_TRADABLE",
        "UNRESOLVED_NO_TERMINATION_EVIDENCE",
    }
)
_INCOMPATIBLE_TRADABILITY_STATES = frozenset(
    {
        "CERTIFIED_ACTIVE_SUSPENDED",
        "CERTIFIED_PRE_LISTING",
        "CERTIFIED_POST_DELISTING",
        "SYMBOL_REUSE_CONFLICT",
        "CONFLICTING_OFFICIAL_EVIDENCE",
        "UNSUPPORTED_SECURITY_TYPE",
    }
)
_REQUIRED_FILES = (
    "htr009a2_certification.json",
    "htr009a2_executive_report.json",
    "htr009a2_source_inventory.json",
    "htr009a2_membership_intervals.json",
    "htr009a2_tradability_intervals.json",
    "htr009a2_symbol_intervals.json",
    "htr009a2_security_events.json",
    "htr009a2_identity_relationships.json",
    "htr009a2_symbol_reuse.json",
    "htr009a2_symbol_changes.json",
)


class LegacyBridgeDecision(StrEnum):
    """Mutually exclusive result of the dated identity bridge."""

    CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE = (
        "CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE"
    )
    NO_MATCHING_OFFICIAL_INTERVAL = "NO_MATCHING_OFFICIAL_INTERVAL"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    SYMBOL_MISMATCH = "SYMBOL_MISMATCH"
    SERIES_MISMATCH = "SERIES_MISMATCH"
    DATE_OUTSIDE_INTERVAL = "DATE_OUTSIDE_INTERVAL"
    INTERVAL_NOT_ADMITTED = "INTERVAL_NOT_ADMITTED"
    INTERVAL_CONFIDENCE_NOT_HIGH = "INTERVAL_CONFIDENCE_NOT_HIGH"
    INTERVAL_LINEAGE_MISSING = "INTERVAL_LINEAGE_MISSING"
    MEMBERSHIP_NOT_COMPATIBLE = "MEMBERSHIP_NOT_COMPATIBLE"
    OVERLAPPING_IDENTITY_CONFLICT = "OVERLAPPING_IDENTITY_CONFLICT"
    SYMBOL_REUSE_CONFLICT = "SYMBOL_REUSE_CONFLICT"
    SYMBOL_CHANGE_BOUNDARY_UNRESOLVED = "SYMBOL_CHANGE_BOUNDARY_UNRESOLVED"
    SERIES_TRANSITION_UNRESOLVED = "SERIES_TRANSITION_UNRESOLVED"
    EVENT_ISIN_INVALID = "EVENT_ISIN_INVALID"
    PRIOR_ISIN_MISMATCH_NON_BRIDGEABLE = "PRIOR_ISIN_MISMATCH_NON_BRIDGEABLE"
    INSUFFICIENT_OFFICIAL_EVIDENCE = "INSUFFICIENT_OFFICIAL_EVIDENCE"


@dataclass(frozen=True, slots=True)
class LegacyBridgeSourceContract:
    """Pinned signed artifact boundary used by the permanent bridge."""

    contract_id: str
    workflow_run_id: int
    artifact_id: int
    artifact_name: str
    artifact_digest: str
    source_head_sha: str
    expected_file_sha256: tuple[tuple[str, str], ...]

    def expected_checksums(self) -> dict[str, str]:
        return dict(self.expected_file_sha256)


# Pin every input from the immutable signed source artifact. This makes any
# artifact substitution fail closed instead of trusting a mutable sidecar.
SIGNED_DSI010_H09A2_SOURCE_CONTRACT = LegacyBridgeSourceContract(
    contract_id="DSI-010B1-SIGNED-HTR009A2-SOURCE-v1",
    workflow_run_id=30335669653,
    artifact_id=8679067292,
    artifact_name="dsi010-a3-b-repaired-rerun",
    artifact_digest=(
        "sha256:b7c1ec98424ba0db12994213d615f5c187de6198e852315e9deab705bce948f7"
    ),
    source_head_sha="ce2dceb1a2755b68f373b80fbc3184a5fbe87faa",
    expected_file_sha256=(
        (
            "htr009a2_certification.json",
            "66969869f92de7a0c8aa03fe55eea0ded17b2ae44f97dc8820afd4214eda9de9",
        ),
        (
            "htr009a2_executive_report.json",
            "23451d3394fdfc6057548f203257e161b580f1f61884c401fd16e6df3338d81c",
        ),
        (
            "htr009a2_identity_relationships.json",
            "6c1db664439054b14cf5baade95beb5c1b194266ecf60003a2aab24c85fd8359",
        ),
        (
            "htr009a2_membership_intervals.json",
            "ce0c06a082b2821754e321af7977bfdfa89a4d3b562fc2a1c306f55bc3461506",
        ),
        (
            "htr009a2_security_events.json",
            "a6b21c638dee71bb0e9e7a986ce1a4af145fbbe2b094bfc8dd1d5dd672d89fb9",
        ),
        (
            "htr009a2_source_inventory.json",
            "ce971089952e455c94646bbe240df61558876547492db76febbb250a085a1eeb",
        ),
        (
            "htr009a2_symbol_changes.json",
            "8ac6c28e6f9dd943b15706b437bda6384bf8de17855e6fffde44fb87dca15fd1",
        ),
        (
            "htr009a2_symbol_intervals.json",
            "d44a147b51e6b71deb94f6b7816ed62b5449c468994f9236e85daa48448f11d9",
        ),
        (
            "htr009a2_symbol_reuse.json",
            "51ad55a2f0a7b99c0b5b69187bf701dd3027e0f512a32a541ee26ccb03a1ce92",
        ),
        (
            "htr009a2_tradability_intervals.json",
            "0896e932082c6b5dcd99cf6c83c974201b72fcb75c775f3753bedfdb33475fec",
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class LegacyBridgeEvidenceSource:
    source_id: str
    sha256: str
    source_path: str
    official_host: bool


@dataclass(frozen=True, slots=True)
class LegacyBridgeIntervalMatch:
    interval_id: str
    interval_type: str
    identity_key: str
    value: str
    valid_from: date
    valid_to: date
    state: str
    confidence: str
    source_event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LegacyBridgeConflictResult:
    overlapping_identity_keys: tuple[str, ...] = ()
    symbol_reuse_conflict: bool = False
    symbol_change_boundary_unresolved: bool = False
    series_transition_unresolved: bool = False


@dataclass(frozen=True, slots=True)
class LegacyIsinReferenceBridgeResult:
    """Complete evidence result for one prior close whose candle omits an ISIN."""

    decision: LegacyBridgeDecision
    certified: bool
    identity_key: str
    symbol: str
    series: str
    isin: str
    reference_date: date
    membership_interval: LegacyBridgeIntervalMatch | None = None
    symbol_interval: LegacyBridgeIntervalMatch | None = None
    tradability_interval: LegacyBridgeIntervalMatch | None = None
    official_event_ids: tuple[str, ...] = ()
    official_sources: tuple[LegacyBridgeEvidenceSource, ...] = ()
    conflict: LegacyBridgeConflictResult = LegacyBridgeConflictResult()
    source_contract_id: str = ""
    source_report_sha256: str = ""

    @property
    def state(self) -> str:
        """Retain the preliminary public attribute while using a typed enum."""

        return self.decision.value

    def provenance(self) -> dict[str, Any]:
        membership = self.membership_interval
        symbol = self.symbol_interval
        tradability = self.tradability_interval
        return {
            "reference_price_bridge_contract_version": (
                LEGACY_ISIN_REFERENCE_BRIDGE_CONTRACT_VERSION
            ),
            "reference_price_bridge_state": self.decision.value,
            "reference_price_bridge_rejection_reason": (
                None if self.certified else self.decision.value
            ),
            "reference_price_bridge_identity": self.identity_key,
            "reference_price_bridge_symbol": self.symbol,
            "reference_price_bridge_series": self.series,
            "reference_price_bridge_isin": self.isin,
            "reference_price_bridge_reference_date": self.reference_date.isoformat(),
            "reference_price_bridge_candle_isin_remained_missing": True,
            "reference_price_bridge_membership_interval_ids": (
                [membership.interval_id] if membership else []
            ),
            "reference_price_bridge_membership_states": (
                [membership.state] if membership else []
            ),
            "reference_price_bridge_membership_confidence": (
                membership.confidence if membership else None
            ),
            "reference_price_bridge_membership_event_ids": (
                list(membership.source_event_ids) if membership else []
            ),
            "reference_price_bridge_symbol_interval_ids": (
                [symbol.interval_id] if symbol else []
            ),
            "reference_price_bridge_symbol_confidence": (
                symbol.confidence if symbol else None
            ),
            "reference_price_bridge_symbol_event_ids": (
                list(symbol.source_event_ids) if symbol else []
            ),
            "reference_price_bridge_tradability_interval_ids": (
                [tradability.interval_id] if tradability else []
            ),
            "reference_price_bridge_tradability_states": (
                [tradability.state] if tradability else []
            ),
            "reference_price_bridge_tradability_certified": (
                tradability.value == "True" if tradability else None
            ),
            "reference_price_bridge_official_event_ids": list(self.official_event_ids),
            "reference_price_bridge_official_source_ids": [
                item.source_id for item in self.official_sources
            ],
            "reference_price_bridge_evidence_sha256": {
                item.source_id: item.sha256 for item in self.official_sources
            },
            "reference_price_bridge_overlapping_identities": list(
                self.conflict.overlapping_identity_keys
            ),
            "reference_price_bridge_symbol_reuse_conflict": (
                self.conflict.symbol_reuse_conflict
            ),
            "reference_price_bridge_symbol_change_conflict": (
                self.conflict.symbol_change_boundary_unresolved
            ),
            "reference_price_bridge_series_transition_conflict": (
                self.conflict.series_transition_unresolved
            ),
            "reference_price_bridge_source_contract_id": self.source_contract_id,
            "reference_price_bridge_source_report_sha256": (self.source_report_sha256),
            "reference_price_bridge_production_influence": False,
        }


@dataclass(frozen=True, slots=True)
class _OfficialState:
    effective_from: date
    effective_to: date
    identity_key: str
    symbol: str
    series: str
    isin: str
    event_id: str
    official_source_id: str


class LegacyIsinReferenceBridge:
    """Resolve only exact, dated, admitted and immutable official identities."""

    def __init__(
        self,
        *,
        memberships: tuple[dict[str, Any], ...],
        tradability: tuple[dict[str, Any], ...],
        symbols: tuple[dict[str, Any], ...],
        events: tuple[dict[str, Any], ...],
        symbol_reuse: tuple[dict[str, Any], ...],
        symbol_changes: tuple[dict[str, Any], ...],
        sources: tuple[LegacyBridgeEvidenceSource, ...],
        admitted_joins: Mapping[str, dict[str, Any]],
        source_contract: LegacyBridgeSourceContract,
        source_checksums: tuple[tuple[str, str], ...],
        source_report_sha256: str,
    ) -> None:
        self.source_contract = source_contract
        self.source_checksums = source_checksums
        self.source_report_sha256 = source_report_sha256
        self._admitted_joins = dict(admitted_joins)
        self._memberships = _group(memberships, "identity_key")
        self._tradability = _group(tradability, "identity_key")
        self._symbols_by_identity = _group(symbols, "identity_key")
        self._symbols_by_value = _group(symbols, "symbol", uppercase=True)
        self._events_by_id = {str(row["event_id"]): row for row in events}
        self._events_by_identity = _events_by_identity(events)
        self._states_by_identity = _official_states(events)
        self._sources = {item.source_id: item for item in sources}
        self._symbol_reuse = _group(symbol_reuse, "symbol", uppercase=True)
        self._symbol_changes = tuple(symbol_changes)

    @classmethod
    def from_output(
        cls,
        output: Path,
        *,
        htr010a3_output: Path,
        source_contract: LegacyBridgeSourceContract = (
            SIGNED_DSI010_H09A2_SOURCE_CONTRACT
        ),
    ) -> LegacyIsinReferenceBridge:
        """Load and verify the pinned HTR-009A2 and HTR-010A3 boundaries."""

        root = output.resolve()
        paths = {name: _unique_file(root, name) for name in _REQUIRED_FILES}
        checksums = {
            name: sha256(path.read_bytes()).hexdigest() for name, path in paths.items()
        }
        expected = source_contract.expected_checksums()
        missing_expected = set(_REQUIRED_FILES) - expected.keys()
        if missing_expected:
            raise ValueError(
                "signed bridge source contract is incomplete: "
                f"{sorted(missing_expected)}"
            )
        mismatches = {
            name: (expected[name], checksums[name])
            for name in _REQUIRED_FILES
            if expected[name] != checksums[name]
        }
        if mismatches:
            raise ValueError(
                f"signed HTR-009A2 evidence checksum mismatch: {sorted(mismatches)}"
            )

        certification = _object(paths["htr009a2_certification.json"])
        executive = _object(paths["htr009a2_executive_report.json"])
        report_sha = _validate_htr009a2_reports(certification, executive)
        payloads = {
            name: tuple(_records(path))
            for name, path in paths.items()
            if name
            not in {
                "htr009a2_certification.json",
                "htr009a2_executive_report.json",
            }
        }
        joins = _validated_join_map(htr010a3_output)
        a3_paths = {
            name: _unique_file(htr010a3_output.resolve(), name)
            for name in (
                "htr010a3_corporate_action_join_readiness.json",
                "htr010a3_readiness.json",
            )
        }
        return cls._from_payloads(
            payloads,
            joins=joins,
            source_contract=source_contract,
            source_checksums=tuple(
                sorted(
                    (
                        *(
                            (f"htr009a2/{name}", digest)
                            for name, digest in checksums.items()
                        ),
                        *(
                            (
                                f"htr010a3/{name}",
                                sha256(path.read_bytes()).hexdigest(),
                            )
                            for name, path in a3_paths.items()
                        ),
                    )
                )
            ),
            source_report_sha256=report_sha,
        )

    @classmethod
    def from_fixture_output(
        cls,
        output: Path,
        *,
        htr010a3_output: Path,
    ) -> LegacyIsinReferenceBridge:
        """Load deterministic synthetic fixtures without claiming signed evidence."""

        paths = {name: _unique_file(output.resolve(), name) for name in _REQUIRED_FILES}
        certification = _object(paths["htr009a2_certification.json"])
        executive = _object(paths["htr009a2_executive_report.json"])
        report_sha = _validate_htr009a2_reports(certification, executive)
        payloads = {
            name: tuple(_records(path))
            for name, path in paths.items()
            if name
            not in {
                "htr009a2_certification.json",
                "htr009a2_executive_report.json",
            }
        }
        checksums = tuple(
            sorted(
                (
                    f"fixture/{name}",
                    sha256(path.read_bytes()).hexdigest(),
                )
                for name, path in paths.items()
            )
        )
        fixture_contract = LegacyBridgeSourceContract(
            contract_id="SYNTHETIC-TEST-FIXTURE-NONEMPIRICAL",
            workflow_run_id=0,
            artifact_id=0,
            artifact_name="synthetic-test-fixture",
            artifact_digest=f"sha256:{'0' * 64}",
            source_head_sha="0" * 40,
            expected_file_sha256=(),
        )
        return cls._from_payloads(
            payloads,
            joins=_validated_join_map(htr010a3_output),
            source_contract=fixture_contract,
            source_checksums=checksums,
            source_report_sha256=report_sha,
        )

    @classmethod
    def _from_payloads(
        cls,
        payloads: Mapping[str, tuple[dict[str, Any], ...]],
        *,
        joins: Mapping[str, dict[str, Any]],
        source_contract: LegacyBridgeSourceContract,
        source_checksums: tuple[tuple[str, str], ...],
        source_report_sha256: str,
    ) -> LegacyIsinReferenceBridge:
        memberships = payloads["htr009a2_membership_intervals.json"]
        tradability = payloads["htr009a2_tradability_intervals.json"]
        symbols = payloads["htr009a2_symbol_intervals.json"]
        events = payloads["htr009a2_security_events.json"]
        sources = payloads["htr009a2_source_inventory.json"]
        _validate_intervals(memberships, "membership interval")
        _validate_intervals(tradability, "tradability interval")
        _validate_intervals(symbols, "symbol interval", require_confidence=True)
        _validate_events(events)
        _validate_unique_event_ids(events)
        evidence_sources = _validate_sources(sources)
        _validate_interval_lineage(
            (*memberships, *tradability, *symbols),
            events,
            evidence_sources,
        )
        return cls(
            memberships=memberships,
            tradability=tradability,
            symbols=symbols,
            events=events,
            symbol_reuse=payloads["htr009a2_symbol_reuse.json"],
            symbol_changes=payloads["htr009a2_symbol_changes.json"],
            sources=evidence_sources,
            admitted_joins=joins,
            source_contract=source_contract,
            source_checksums=source_checksums,
            source_report_sha256=source_report_sha256,
        )

    def resolve(
        self,
        *,
        identity_key: str,
        symbol: str,
        series: str,
        isin: str,
        reference_date: date,
        prior_isin_mismatch: bool = False,
    ) -> LegacyIsinReferenceBridgeResult:
        normalized_symbol = symbol.upper()
        normalized_series = series.upper()
        normalized_isin = isin.upper()
        base = {
            "identity_key": identity_key,
            "symbol": normalized_symbol,
            "series": normalized_series,
            "isin": normalized_isin,
            "reference_date": reference_date,
            "source_contract_id": self.source_contract.contract_id,
            "source_report_sha256": self.source_report_sha256,
        }
        if prior_isin_mismatch:
            return self._result(
                LegacyBridgeDecision.PRIOR_ISIN_MISMATCH_NON_BRIDGEABLE, base
            )
        if not _valid_isin(normalized_isin):
            return self._result(LegacyBridgeDecision.EVENT_ISIN_INVALID, base)
        if identity_key != f"nse:isin:{normalized_isin}":
            return self._result(LegacyBridgeDecision.IDENTITY_MISMATCH, base)
        join = self._admitted_joins.get(identity_key)
        if join is None or not join.get("admitted_to_certified_join"):
            return self._result(LegacyBridgeDecision.INTERVAL_NOT_ADMITTED, base)
        if str(join.get("isin") or "").upper() != normalized_isin:
            return self._result(LegacyBridgeDecision.IDENTITY_MISMATCH, base)

        memberships = self._dated(self._memberships, identity_key, reference_date)
        if not memberships:
            return self._result(
                (
                    LegacyBridgeDecision.DATE_OUTSIDE_INTERVAL
                    if self._memberships.get(identity_key)
                    else LegacyBridgeDecision.NO_MATCHING_OFFICIAL_INTERVAL
                ),
                base,
            )
        if len(memberships) != 1:
            return self._result(
                LegacyBridgeDecision.OVERLAPPING_IDENTITY_CONFLICT, base
            )
        membership = _interval_match(memberships[0], "MEMBERSHIP", "")
        if membership.state not in _COMPATIBLE_MEMBERSHIP_STATES:
            return self._result(
                LegacyBridgeDecision.MEMBERSHIP_NOT_COMPATIBLE,
                base,
                membership=membership,
            )
        lineage_decision, membership_sources = self._lineage_evidence(
            membership.source_event_ids
        )
        if lineage_decision is not None:
            return self._result(
                lineage_decision,
                base,
                membership=membership,
            )

        dated_symbol_rows = self._dated(
            self._symbols_by_identity, identity_key, reference_date
        )
        symbols = tuple(
            row
            for row in dated_symbol_rows
            if str(row.get("symbol") or "").upper() == normalized_symbol
        )
        if not symbols:
            return self._result(
                LegacyBridgeDecision.SYMBOL_MISMATCH,
                base,
                membership=membership,
                sources=membership_sources,
            )
        if len(symbols) != 1:
            return self._result(
                LegacyBridgeDecision.OVERLAPPING_IDENTITY_CONFLICT,
                base,
                membership=membership,
                sources=membership_sources,
            )
        if any(
            str(row.get("symbol") or "").upper() != normalized_symbol
            for row in dated_symbol_rows
        ):
            return self._result(
                LegacyBridgeDecision.SYMBOL_CHANGE_BOUNDARY_UNRESOLVED,
                base,
                membership=membership,
                sources=membership_sources,
            )
        symbol_interval = _interval_match(symbols[0], "SYMBOL", normalized_symbol)
        if symbol_interval.confidence != "HIGH":
            return self._result(
                LegacyBridgeDecision.INTERVAL_CONFIDENCE_NOT_HIGH,
                base,
                membership=membership,
                symbol=symbol_interval,
                sources=membership_sources,
            )
        if tuple(symbols[0].get("issue_codes") or ()):
            return self._result(
                LegacyBridgeDecision.INSUFFICIENT_OFFICIAL_EVIDENCE,
                base,
                membership=membership,
                symbol=symbol_interval,
                sources=membership_sources,
            )
        lineage_decision, symbol_sources = self._lineage_evidence(
            symbol_interval.source_event_ids
        )
        sources = _merge_sources(membership_sources, symbol_sources)
        if lineage_decision is not None:
            return self._result(
                lineage_decision,
                base,
                membership=membership,
                symbol=symbol_interval,
                sources=sources,
            )

        conflict = self._conflicts(
            identity_key=identity_key,
            symbol=normalized_symbol,
            series=normalized_series,
            reference_date=reference_date,
        )
        if conflict.symbol_reuse_conflict:
            return self._result(
                LegacyBridgeDecision.SYMBOL_REUSE_CONFLICT,
                base,
                membership=membership,
                symbol=symbol_interval,
                conflict=conflict,
                sources=sources,
            )
        if conflict.symbol_change_boundary_unresolved:
            return self._result(
                LegacyBridgeDecision.SYMBOL_CHANGE_BOUNDARY_UNRESOLVED,
                base,
                membership=membership,
                symbol=symbol_interval,
                conflict=conflict,
                sources=sources,
            )
        if conflict.series_transition_unresolved:
            return self._result(
                LegacyBridgeDecision.SERIES_TRANSITION_UNRESOLVED,
                base,
                membership=membership,
                symbol=symbol_interval,
                conflict=conflict,
                sources=sources,
            )
        if conflict.overlapping_identity_keys:
            return self._result(
                LegacyBridgeDecision.OVERLAPPING_IDENTITY_CONFLICT,
                base,
                membership=membership,
                symbol=symbol_interval,
                conflict=conflict,
                sources=sources,
            )

        state_rows = self._state_at(identity_key, reference_date)
        if not state_rows:
            return self._result(
                LegacyBridgeDecision.INSUFFICIENT_OFFICIAL_EVIDENCE,
                base,
                membership=membership,
                symbol=symbol_interval,
                sources=sources,
            )
        state_values = {(row.symbol, row.series, row.isin) for row in state_rows}
        if len(state_values) != 1:
            return self._result(
                LegacyBridgeDecision.SERIES_TRANSITION_UNRESOLVED,
                base,
                membership=membership,
                symbol=symbol_interval,
                sources=sources,
            )
        observed_symbol, observed_series, observed_isin = next(iter(state_values))
        if observed_symbol != normalized_symbol:
            return self._result(
                LegacyBridgeDecision.SYMBOL_MISMATCH,
                base,
                membership=membership,
                symbol=symbol_interval,
                sources=sources,
            )
        if observed_series != normalized_series:
            return self._result(
                LegacyBridgeDecision.SERIES_MISMATCH,
                base,
                membership=membership,
                symbol=symbol_interval,
                sources=sources,
            )
        if observed_isin != normalized_isin:
            return self._result(
                LegacyBridgeDecision.IDENTITY_MISMATCH,
                base,
                membership=membership,
                symbol=symbol_interval,
                sources=sources,
            )
        official_event_ids = tuple(sorted({row.event_id for row in state_rows}))
        state_decision, state_sources = self._lineage_evidence(official_event_ids)
        sources = _merge_sources(sources, state_sources)
        if state_decision is not None:
            return self._result(
                state_decision,
                base,
                membership=membership,
                symbol=symbol_interval,
                sources=sources,
            )
        if not set(official_event_ids).issubset(
            set(membership.source_event_ids)
        ) or not set(official_event_ids).issubset(
            set(symbol_interval.source_event_ids)
        ):
            return self._result(
                LegacyBridgeDecision.INTERVAL_LINEAGE_MISSING,
                base,
                membership=membership,
                symbol=symbol_interval,
                official_event_ids=official_event_ids,
                sources=sources,
            )

        tradability = self._compatible_tradability(identity_key, reference_date)
        if tradability is False:
            return self._result(
                LegacyBridgeDecision.MEMBERSHIP_NOT_COMPATIBLE,
                base,
                membership=membership,
                symbol=symbol_interval,
                official_event_ids=official_event_ids,
                sources=sources,
            )
        if isinstance(tradability, LegacyBridgeIntervalMatch):
            tradability_decision, tradability_sources = self._lineage_evidence(
                tradability.source_event_ids
            )
            sources = _merge_sources(sources, tradability_sources)
            if tradability_decision is not None:
                return self._result(
                    tradability_decision,
                    base,
                    membership=membership,
                    symbol=symbol_interval,
                    tradability=tradability,
                    official_event_ids=official_event_ids,
                    sources=sources,
                )
        return self._result(
            LegacyBridgeDecision.CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE,
            base,
            membership=membership,
            symbol=symbol_interval,
            tradability=(
                tradability
                if isinstance(tradability, LegacyBridgeIntervalMatch)
                else None
            ),
            official_event_ids=official_event_ids,
            sources=sources,
        )

    def _state_at(
        self, identity_key: str, reference_date: date
    ) -> tuple[_OfficialState, ...]:
        return tuple(
            row
            for row in self._states_by_identity.get(identity_key, ())
            if row.effective_from <= reference_date <= row.effective_to
        )

    @staticmethod
    def _dated(
        grouped: Mapping[str, tuple[dict[str, Any], ...]],
        key: str,
        value: date,
    ) -> tuple[dict[str, Any], ...]:
        return tuple(row for row in grouped.get(key, ()) if _contains(row, value))

    def _lineage_evidence(
        self, event_ids: Iterable[str]
    ) -> tuple[
        LegacyBridgeDecision | None,
        tuple[LegacyBridgeEvidenceSource, ...],
    ]:
        normalized = tuple(sorted({str(item) for item in event_ids if str(item)}))
        if not normalized:
            return LegacyBridgeDecision.INTERVAL_LINEAGE_MISSING, ()
        sources: list[LegacyBridgeEvidenceSource] = []
        for event_id in normalized:
            event = self._events_by_id.get(event_id)
            if event is None:
                return LegacyBridgeDecision.INTERVAL_LINEAGE_MISSING, tuple(sources)
            if event.get("admission_state") != "ADMITTED":
                return LegacyBridgeDecision.INTERVAL_NOT_ADMITTED, tuple(sources)
            if event.get("confidence_state") != "HIGH":
                return (
                    LegacyBridgeDecision.INTERVAL_CONFIDENCE_NOT_HIGH,
                    tuple(sources),
                )
            source = self._sources.get(str(event.get("official_source_id") or ""))
            if source is None or not source.sha256 or not source.official_host:
                return LegacyBridgeDecision.INTERVAL_LINEAGE_MISSING, tuple(sources)
            sources.append(source)
        return None, tuple(sorted(set(sources), key=lambda item: item.source_id))

    def _compatible_tradability(
        self, identity_key: str, reference_date: date
    ) -> LegacyBridgeIntervalMatch | bool | None:
        rows = self._dated(self._tradability, identity_key, reference_date)
        if not rows:
            return None
        if len(rows) != 1:
            return False
        row = rows[0]
        if str(row.get("state") or "") in _INCOMPATIBLE_TRADABILITY_STATES:
            return False
        return _interval_match(row, "TRADABILITY", str(bool(row.get("tradable"))))

    def _conflicts(
        self,
        *,
        identity_key: str,
        symbol: str,
        series: str,
        reference_date: date,
    ) -> LegacyBridgeConflictResult:
        overlap = []
        for row in self._dated(self._symbols_by_value, symbol, reference_date):
            other_identity = str(row["identity_key"])
            if other_identity == identity_key:
                continue
            states = self._state_at(other_identity, reference_date)
            if not states or any(item.series == series for item in states):
                overlap.append(other_identity)
        reuse = any(
            identity_key in tuple(row.get("identity_keys") or ())
            and str(row.get("final_status") or "") == "SYMBOL_REUSE_CONFLICT"
            for row in self._symbol_reuse.get(symbol, ())
        )
        symbol_change = any(
            _unresolved_symbol_change(
                row,
                identity_key=identity_key,
                symbol=symbol,
                reference_date=reference_date,
            )
            for row in self._symbol_changes
        )
        series_transition = any(
            _unresolved_series_transition(row, identity_key, reference_date)
            for row in self._events_by_identity.get(identity_key, ())
        )
        return LegacyBridgeConflictResult(
            overlapping_identity_keys=tuple(sorted(set(overlap))),
            symbol_reuse_conflict=reuse,
            symbol_change_boundary_unresolved=symbol_change,
            series_transition_unresolved=series_transition,
        )

    @staticmethod
    def _result(
        decision: LegacyBridgeDecision,
        base: Mapping[str, Any],
        *,
        membership: LegacyBridgeIntervalMatch | None = None,
        symbol: LegacyBridgeIntervalMatch | None = None,
        tradability: LegacyBridgeIntervalMatch | None = None,
        official_event_ids: tuple[str, ...] = (),
        sources: tuple[LegacyBridgeEvidenceSource, ...] = (),
        conflict: LegacyBridgeConflictResult = LegacyBridgeConflictResult(),
    ) -> LegacyIsinReferenceBridgeResult:
        return LegacyIsinReferenceBridgeResult(
            decision=decision,
            certified=(
                decision
                is LegacyBridgeDecision.CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE
            ),
            membership_interval=membership,
            symbol_interval=symbol,
            tradability_interval=tradability,
            official_event_ids=official_event_ids,
            official_sources=sources,
            conflict=conflict,
            **base,
        )


def _unique_file(root: Path, name: str) -> Path:
    if not root.is_dir():
        raise ValueError(f"governed artifact root is not a directory: {root}")
    direct = root / name
    matches = (direct,) if direct.is_file() else tuple(sorted(root.rglob(name)))
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one {name} under {root}, found {len(matches)}"
        )
    resolved = matches[0].resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"evidence path escapes governed artifact root: {name}"
        ) from exc
    if not resolved.is_file():
        raise ValueError(f"governed evidence is not a regular file: {name}")
    return resolved


def _object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain an object")
    return dict(payload)


def _records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("records"), list):
        rows = payload["records"]
    else:
        raise ValueError(f"{path.name} must contain a records array")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{path.name} contains a non-object record")
    return [dict(row) for row in rows]


def _validate_htr009a2_reports(
    certification: Mapping[str, Any],
    executive: Mapping[str, Any],
) -> str:
    if certification.get("contract_version") != _HTR009A2_CONTRACT_VERSION:
        raise ValueError("unexpected HTR-009A2 certification contract")
    if executive.get("contract_version") != _HTR009A2_CONTRACT_VERSION:
        raise ValueError("unexpected HTR-009A2 executive contract")
    if certification.get("production_influence") is not False:
        raise ValueError("HTR-009A2 certification has production influence")
    if executive.get("production_influence") is not False:
        raise ValueError("HTR-009A2 executive report has production influence")
    certified_hash = str(certification.get("report_sha256") or "")
    executive_hash = str(executive.get("report_sha256") or "")
    if not _valid_sha256(certified_hash) or certified_hash != executive_hash:
        raise ValueError("HTR-009A2 report hashes are missing or inconsistent")
    return certified_hash


def _validated_join_map(output: Path) -> dict[str, dict[str, Any]]:
    root = output.resolve()
    path = _unique_file(root, "htr010a3_corporate_action_join_readiness.json")
    readiness_path = _unique_file(root, "htr010a3_readiness.json")
    rows = _records(path)
    readiness = _object(readiness_path)
    if readiness.get("production_influence") is not False:
        raise ValueError("HTR-010A3 readiness has production influence")
    decision = readiness.get("readiness")
    if not isinstance(decision, dict):
        raise ValueError("HTR-010A3 readiness decision must be an object")
    denominator = _nonnegative_int(
        decision.get("denominator_identities"),
        "HTR-010A3 denominator",
    )
    admitted = _nonnegative_int(
        decision.get("admitted_identities"),
        "HTR-010A3 admitted identities",
    )
    quarantined = _nonnegative_int(
        decision.get("quarantined_identities"),
        "HTR-010A3 quarantined identities",
    )
    if admitted + quarantined != denominator:
        raise ValueError("HTR-010A3 readiness population does not reconcile")
    if len(rows) != denominator:
        raise ValueError("HTR-010A3 join rows do not match signed denominator")
    identities: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = str(row.get("identity_key") or "")
        if not identity or identity in identities:
            raise ValueError("HTR-010A3 join identities must be unique and non-empty")
        identities[identity] = row
    observed_admitted = sum(bool(row.get("admitted_to_certified_join")) for row in rows)
    if observed_admitted != admitted:
        raise ValueError("HTR-010A3 admitted join count does not reconcile")
    return identities


def _validate_intervals(
    rows: tuple[dict[str, Any], ...],
    label: str,
    *,
    require_confidence: bool = False,
) -> None:
    seen: set[str] = set()
    for index, row in enumerate(rows):
        required = {"identity_key", "valid_from", "valid_to", "source_event_ids"}
        if require_confidence:
            required.add("confidence_state")
        missing = required - row.keys()
        if missing:
            raise ValueError(f"{label} {index} missing fields: {sorted(missing)}")
        start = _date_value(row["valid_from"], f"{label} {index} valid_from")
        end = _date_value(row["valid_to"], f"{label} {index} valid_to")
        if end < start:
            raise ValueError(f"{label} {index} has an inverted interval")
        interval_id = _interval_id(label, row)
        if interval_id in seen:
            raise ValueError(f"duplicate {label} ID: {interval_id}")
        seen.add(interval_id)


def _validate_events(rows: tuple[dict[str, Any], ...]) -> None:
    required = {
        "event_id",
        "effective_date",
        "official_source_id",
        "admission_state",
        "confidence_state",
    }
    for index, row in enumerate(rows):
        missing = required - row.keys()
        if missing:
            raise ValueError(
                f"security event {index} missing fields: {sorted(missing)}"
            )
        _date_value(row["effective_date"], f"security event {index} effective_date")
        for field in ("old_isin", "new_isin"):
            value = str(row.get(field) or "").upper()
            if value and not (
                _valid_isin(value)
                or _OFFICIAL_PLACEHOLDER_ISIN_PATTERN.fullmatch(value)
            ):
                raise ValueError(f"security event {index} has invalid {field}")


def _validate_unique_event_ids(rows: tuple[dict[str, Any], ...]) -> None:
    ids = [str(row["event_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("HTR-009A2 contains duplicate event IDs")


def _validate_sources(
    rows: tuple[dict[str, Any], ...],
) -> tuple[LegacyBridgeEvidenceSource, ...]:
    sources = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        source_id = str(row.get("source_id") or "")
        digest = str(row.get("sha256") or "")
        source_path = str(row.get("source_path") or "")
        if not source_id or source_id in seen:
            raise ValueError("HTR-009A2 source IDs must be unique and non-empty")
        seen.add(source_id)
        if digest and not _valid_sha256(digest):
            raise ValueError(f"HTR-009A2 source {index} has invalid SHA-256")
        sources.append(
            LegacyBridgeEvidenceSource(
                source_id=source_id,
                sha256=digest,
                source_path=source_path,
                official_host=bool(row.get("official_host")),
            )
        )
    return tuple(sorted(sources, key=lambda item: item.source_id))


def _validate_interval_lineage(
    intervals: tuple[dict[str, Any], ...],
    events: tuple[dict[str, Any], ...],
    sources: tuple[LegacyBridgeEvidenceSource, ...],
) -> None:
    event_by_id = {str(row["event_id"]): row for row in events}
    source_by_id = {row.source_id: row for row in sources}
    for row in intervals:
        for event_id in tuple(row.get("source_event_ids") or ()):
            event = event_by_id.get(str(event_id))
            if event is None:
                raise ValueError(f"interval references unknown event ID: {event_id}")
            source = source_by_id.get(str(event.get("official_source_id") or ""))
            if source is None or not source.sha256:
                raise ValueError(
                    f"interval event lacks immutable source lineage: {event_id}"
                )


def _events_by_identity(
    rows: tuple[dict[str, Any], ...],
) -> dict[str, tuple[dict[str, Any], ...]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for field in ("predecessor_identity", "successor_identity"):
            identity = str(row.get(field) or "")
            if identity:
                grouped[identity].append(row)
    return {
        key: tuple(
            sorted(
                value,
                key=lambda item: (str(item["effective_date"]), str(item["event_id"])),
            )
        )
        for key, value in grouped.items()
    }


def _official_states(
    rows: tuple[dict[str, Any], ...],
) -> dict[str, tuple[_OfficialState, ...]]:
    states: dict[str, list[_OfficialState]] = defaultdict(list)
    maximum = date.max
    for row in rows:
        if row.get("admission_state") != "ADMITTED":
            continue
        if row.get("confidence_state") != "HIGH":
            continue
        effective = _date_value(row["effective_date"], "event effective_date")
        event_id = str(row["event_id"])
        source_id = str(row["official_source_id"])
        for side in ("new", "old"):
            identity_field = (
                "successor_identity" if side == "new" else "predecessor_identity"
            )
            identity = str(row.get(identity_field) or "")
            symbol = str(row.get(f"{side}_symbol") or "").upper()
            series = str(row.get(f"{side}_series") or "").upper()
            isin = str(row.get(f"{side}_isin") or "").upper()
            if not identity or not symbol or not series or not _valid_isin(isin):
                continue
            if identity != f"nse:isin:{isin}":
                continue
            states[identity].append(
                _OfficialState(
                    effective_from=(effective if side == "new" else date.min),
                    effective_to=(
                        maximum if side == "new" else effective - timedelta(days=1)
                    ),
                    identity_key=identity,
                    symbol=symbol,
                    series=series,
                    isin=isin,
                    event_id=event_id,
                    official_source_id=source_id,
                )
            )
    result: dict[str, tuple[_OfficialState, ...]] = {}
    for identity, candidates in states.items():
        ordered = sorted(
            candidates,
            key=lambda item: (
                item.effective_from,
                item.effective_to,
                item.event_id,
                item.symbol,
                item.series,
            ),
        )
        result[identity] = tuple(_trim_state_intervals(ordered))
    return result


def _trim_state_intervals(rows: list[_OfficialState]) -> list[_OfficialState]:
    """Limit open successor states at the next dated successor observation."""

    starts = sorted(
        {
            row.effective_from
            for row in rows
            if row.effective_from not in {date.min, date.max}
        }
    )
    result = []
    for row in rows:
        later = next((value for value in starts if value > row.effective_from), None)
        effective_to = row.effective_to
        if later is not None and effective_to == date.max:
            effective_to = later - timedelta(days=1)
        result.append(
            _OfficialState(
                row.effective_from,
                effective_to,
                row.identity_key,
                row.symbol,
                row.series,
                row.isin,
                row.event_id,
                row.official_source_id,
            )
        )
    return result


def _group(
    rows: Iterable[dict[str, Any]],
    field: str,
    *,
    uppercase: bool = False,
) -> dict[str, tuple[dict[str, Any], ...]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = str(row.get(field) or "")
        if uppercase:
            key = key.upper()
        grouped[key].append(row)
    return {
        key: tuple(sorted(value, key=lambda item: json.dumps(item, sort_keys=True)))
        for key, value in grouped.items()
    }


def _interval_match(
    row: Mapping[str, Any],
    interval_type: str,
    value: str,
) -> LegacyBridgeIntervalMatch:
    return LegacyBridgeIntervalMatch(
        interval_id=_interval_id(interval_type, row),
        interval_type=interval_type,
        identity_key=str(row["identity_key"]),
        value=value,
        valid_from=_date_value(row["valid_from"], "valid_from"),
        valid_to=_date_value(row["valid_to"], "valid_to"),
        state=str(row.get("state") or ""),
        confidence=str(row.get("confidence_state") or "HIGH"),
        source_event_ids=tuple(
            sorted(str(item) for item in tuple(row.get("source_event_ids") or ()))
        ),
    )


def _interval_id(label: str, row: Mapping[str, Any]) -> str:
    material = json.dumps(
        {
            "label": label,
            "identity_key": row.get("identity_key"),
            "symbol": row.get("symbol"),
            "series": row.get("series"),
            "valid_from": row.get("valid_from"),
            "valid_to": row.get("valid_to"),
            "source_event_ids": sorted(row.get("source_event_ids") or ()),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"legacy-bridge-interval:{sha256(material.encode()).hexdigest()}"


def _contains(row: Mapping[str, Any], value: date) -> bool:
    return (
        _date_value(row["valid_from"], "valid_from")
        <= value
        <= _date_value(row["valid_to"], "valid_to")
    )


def _unresolved_symbol_change(
    row: Mapping[str, Any],
    *,
    identity_key: str,
    symbol: str,
    reference_date: date,
) -> bool:
    if str(row.get("final_status") or "") != "UNRESOLVED_IDENTITY_TRANSITION":
        return False
    identities = {
        str(row.get("old_identity") or ""),
        str(row.get("new_identity") or ""),
    }
    symbols = {
        str(row.get("old_symbol") or "").upper(),
        str(row.get("new_symbol") or "").upper(),
    }
    if identity_key not in identities or symbol not in symbols:
        return False
    effective = row.get("effective_date")
    return (
        effective is None
        or _date_value(effective, "symbol change date") == reference_date
    )


def _unresolved_series_transition(
    row: Mapping[str, Any], identity_key: str, reference_date: date
) -> bool:
    if str(row.get("event_type") or "") != "SERIES_CHANGED":
        return False
    if identity_key not in {
        str(row.get("predecessor_identity") or ""),
        str(row.get("successor_identity") or ""),
    }:
        return False
    effective = _date_value(row["effective_date"], "series change date")
    if effective != reference_date:
        return False
    return (
        row.get("admission_state") != "ADMITTED"
        or row.get("confidence_state") != "HIGH"
        or not row.get("old_series")
        or not row.get("new_series")
    )


def _merge_sources(
    *groups: tuple[LegacyBridgeEvidenceSource, ...],
) -> tuple[LegacyBridgeEvidenceSource, ...]:
    by_id = {item.source_id: item for group in groups for item in group}
    return tuple(by_id[key] for key in sorted(by_id))


def _date_value(value: object, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"malformed {label}: {value}") from exc


def _valid_isin(value: str) -> bool:
    return bool(_ISIN_PATTERN.fullmatch(value))


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


__all__ = [
    "LEGACY_ISIN_REFERENCE_BRIDGE_CONTRACT_VERSION",
    "PRODUCTION_INFLUENCE",
    "SIGNED_DSI010_H09A2_SOURCE_CONTRACT",
    "LegacyBridgeConflictResult",
    "LegacyBridgeDecision",
    "LegacyBridgeEvidenceSource",
    "LegacyBridgeIntervalMatch",
    "LegacyBridgeSourceContract",
    "LegacyIsinReferenceBridge",
    "LegacyIsinReferenceBridgeResult",
]
