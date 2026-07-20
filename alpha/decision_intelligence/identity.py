"""Recovered security identity integration for decision intelligence."""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from alpha.decision_intelligence.engine import InstitutionalDecisionEngine
from alpha.decision_intelligence.models import (
    InstitutionalCandidate,
    InstitutionalDecisionReport,
)
from alpha.recovery.models import RecoveryResult


@dataclass(frozen=True, slots=True)
class SecurityIdentity:
    """Canonical identity consumed by downstream decision systems."""

    record_key: str
    security_id: str | None
    isin: str | None
    symbol: str
    exchange: str | None
    confidence: float
    recovery_version: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IdentityResolution:
    """Explainable result of resolving one user or legacy identifier."""

    query: str
    resolved: bool
    identity: SecurityIdentity | None
    matched_by: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class IdentityParityReport:
    """Compare legacy candidate symbols with recovered canonical symbols."""

    candidate_count: int
    resolved_count: int
    unresolved_symbols: tuple[str, ...]
    changed_symbols: tuple[tuple[str, str], ...]

    @property
    def parity_preserved(self) -> bool:
        return not self.unresolved_symbols and not self.changed_symbols


class RecoveredSecurityIdentityIndex:
    """Immutable lookup index built from an HTR-002 canonical preview."""

    def __init__(self, identities: Sequence[SecurityIdentity]) -> None:
        self._identities = tuple(identities)
        self._lookups: dict[str, tuple[str, SecurityIdentity]] = {}
        for identity in self._identities:
            self._add("record_key", identity.record_key, identity)
            self._add("security_id", identity.security_id, identity)
            self._add("isin", identity.isin, identity)
            self._add("symbol", identity.symbol, identity)

    @classmethod
    def from_recovery_result(
        cls,
        result: RecoveryResult,
    ) -> RecoveredSecurityIdentityIndex:
        identities = tuple(
            _identity_from_mapping(
                row.record_key,
                row.values,
                row.evidence_ids,
            )
            for row in result.canonical_preview
        )
        return cls(identities)

    @classmethod
    def from_preview_csv(cls, path: Path) -> RecoveredSecurityIdentityIndex:
        with path.open(encoding="utf-8", newline="") as handle:
            identities = tuple(
                _identity_from_mapping(
                    str(row.get("record_key", "")),
                    row,
                    (),
                )
                for row in csv.DictReader(handle)
            )
        return cls(identities)

    def resolve(self, query: str) -> IdentityResolution:
        normalized = _normalize(query)
        if not normalized:
            return IdentityResolution(
                query=query,
                resolved=False,
                identity=None,
                matched_by=None,
                reason="Identity query is empty.",
            )
        match = self._lookups.get(normalized)
        if match is None:
            return IdentityResolution(
                query=query,
                resolved=False,
                identity=None,
                matched_by=None,
                reason="No recovered security identity matched the query.",
            )
        matched_by, identity = match
        return IdentityResolution(
            query=query,
            resolved=True,
            identity=identity,
            matched_by=matched_by,
            reason=(
                "Resolved from HTR-002 canonical security identity preview "
                f"with confidence {identity.confidence:.4f}."
            ),
        )

    def _add(
        self,
        matched_by: str,
        value: str | None,
        identity: SecurityIdentity,
    ) -> None:
        if not value:
            return
        key = _normalize(value)
        existing = self._lookups.get(key)
        if existing is not None and existing[1] != identity:
            raise ValueError(f"ambiguous recovered identity key: {value}")
        self._lookups[key] = (matched_by, identity)


class RecoveredIdentityDecisionEngine:
    """Decision-engine facade that canonicalizes symbols before scoring."""

    def __init__(
        self,
        identity_index: RecoveredSecurityIdentityIndex,
        *,
        decision_engine: InstitutionalDecisionEngine | None = None,
        require_resolution: bool = True,
    ) -> None:
        self.identity_index = identity_index
        self.decision_engine = decision_engine or InstitutionalDecisionEngine()
        self.require_resolution = require_resolution

    def canonicalize_candidates(
        self,
        candidates: tuple[InstitutionalCandidate, ...],
    ) -> tuple[InstitutionalCandidate, ...]:
        resolved: list[InstitutionalCandidate] = []
        for candidate in candidates:
            resolution = self.identity_index.resolve(candidate.symbol)
            if not resolution.resolved or resolution.identity is None:
                if self.require_resolution:
                    raise KeyError(
                        f"unresolved recovered security identity: {candidate.symbol}"
                    )
                resolved.append(candidate)
                continue
            resolved.append(
                replace(candidate, symbol=resolution.identity.symbol)
            )
        return tuple(resolved)

    def evaluate(
        self,
        candidates: tuple[InstitutionalCandidate, ...],
    ) -> InstitutionalDecisionReport:
        return self.decision_engine.evaluate(
            self.canonicalize_candidates(candidates)
        )

    def parity_report(
        self,
        candidates: tuple[InstitutionalCandidate, ...],
    ) -> IdentityParityReport:
        unresolved: list[str] = []
        changed: list[tuple[str, str]] = []
        resolved_count = 0
        for candidate in candidates:
            resolution = self.identity_index.resolve(candidate.symbol)
            if not resolution.resolved or resolution.identity is None:
                unresolved.append(candidate.symbol)
                continue
            resolved_count += 1
            canonical = resolution.identity.symbol
            if canonical != candidate.symbol:
                changed.append((candidate.symbol, canonical))
        return IdentityParityReport(
            candidate_count=len(candidates),
            resolved_count=resolved_count,
            unresolved_symbols=tuple(sorted(set(unresolved))),
            changed_symbols=tuple(sorted(set(changed))),
        )


def _identity_from_mapping(
    record_key: str,
    values: Mapping[str, object],
    evidence_ids: tuple[str, ...],
) -> SecurityIdentity:
    symbol = _optional_text(values.get("symbol"))
    if not symbol:
        raise ValueError(f"canonical identity {record_key!r} has no symbol")
    confidence_value = values.get("entity_confidence", 0.0)
    try:
        confidence = float(confidence_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"invalid identity confidence for {record_key!r}"
        ) from exc
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"identity confidence outside [0, 1]: {record_key!r}")
    return SecurityIdentity(
        record_key=record_key,
        security_id=_optional_text(values.get("security_id")),
        isin=_optional_text(values.get("isin")),
        symbol=symbol,
        exchange=_optional_text(values.get("exchange")),
        confidence=confidence,
        recovery_version=(
            _optional_text(values.get("recovery_version")) or "UNKNOWN"
        ),
        evidence_ids=evidence_ids,
    )


def _normalize(value: str) -> str:
    return value.strip().upper()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
