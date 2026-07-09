from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_TWO_PLACES = Decimal("0.01")


class PolicyScope(StrEnum):
    """Scope at which a portfolio policy applies."""

    PORTFOLIO = "PORTFOLIO"
    ASSET_CLASS = "ASSET_CLASS"
    SECTOR = "SECTOR"
    THEME = "THEME"
    SECURITY = "SECURITY"
    STRATEGY = "STRATEGY"


class PolicyCategory(StrEnum):
    """Institutional policy category."""

    ELIGIBILITY = "ELIGIBILITY"
    CONCENTRATION = "CONCENTRATION"
    EXPOSURE = "EXPOSURE"
    LIQUIDITY = "LIQUIDITY"
    RISK_BUDGET = "RISK_BUDGET"
    CASH_RESERVE = "CASH_RESERVE"
    MARKET_REGIME = "MARKET_REGIME"
    GOVERNANCE = "GOVERNANCE"


class PolicySeverity(StrEnum):
    """Severity of a policy violation."""

    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


class PolicyDecision(StrEnum):
    """Portfolio-policy decision before allocation mechanics."""

    APPROVE = "APPROVE"
    REVIEW = "REVIEW"
    RESTRICT = "RESTRICT"
    REJECT = "REJECT"

    @property
    def allows_allocation(self) -> bool:
        return self in {
            PolicyDecision.APPROVE,
            PolicyDecision.REVIEW,
            PolicyDecision.RESTRICT,
        }


class PolicyStatus(StrEnum):
    """Status of an individual policy check."""

    PASS = "PASS"
    WATCH = "WATCH"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class PolicyEvidence:
    """Structured evidence used by a policy evaluation."""

    label: str
    value: Decimal | str | bool
    threshold: Decimal | str | bool | None = None
    rationale: str = ""

    def __post_init__(self) -> None:
        label = self.label.strip()
        rationale = self.rationale.strip()

        if not label:
            raise ValueError("policy evidence label cannot be empty")

        object.__setattr__(self, "label", label)
        object.__setattr__(self, "value", _normalize_scalar(self.value))
        object.__setattr__(
            self,
            "threshold",
            None if self.threshold is None else _normalize_scalar(self.threshold),
        )
        object.__setattr__(self, "rationale", rationale)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "value": _serialize_scalar(self.value),
            "threshold": _serialize_scalar(self.threshold),
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class PolicyReason:
    """Human-readable reason attached to a policy outcome."""

    code: str
    message: str
    severity: PolicySeverity = PolicySeverity.INFO
    evidence: tuple[PolicyEvidence, ...] = ()

    def __post_init__(self) -> None:
        code = self.code.strip().upper()
        message = self.message.strip()

        if not code:
            raise ValueError("policy reason code cannot be empty")
        if not message:
            raise ValueError("policy reason message cannot be empty")

        object.__setattr__(self, "code", code)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "evidence", tuple(self.evidence))

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "evidence": [item.as_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class PolicyViolation:
    """A policy breach discovered during governance evaluation."""

    policy_id: str
    category: PolicyCategory
    scope: PolicyScope
    severity: PolicySeverity
    message: str
    evidence: tuple[PolicyEvidence, ...] = ()

    def __post_init__(self) -> None:
        policy_id = _normalize_identifier(self.policy_id, "policy id")
        message = self.message.strip()

        if not message:
            raise ValueError("policy violation message cannot be empty")

        object.__setattr__(self, "policy_id", policy_id)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "evidence", tuple(self.evidence))

    @property
    def is_blocking(self) -> bool:
        return self.severity is PolicySeverity.BLOCKING

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "category": self.category.value,
            "scope": self.scope.value,
            "severity": self.severity.value,
            "message": self.message,
            "evidence": [item.as_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class PortfolioPolicy:
    """Immutable definition of a portfolio governance policy."""

    policy_id: str
    name: str
    category: PolicyCategory
    scope: PolicyScope
    description: str
    enabled: bool = True
    parameters: Mapping[str, Decimal | str | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        policy_id = _normalize_identifier(self.policy_id, "policy id")
        name = self.name.strip()
        description = self.description.strip()
        parameters = _normalize_parameters(self.parameters)

        if not name:
            raise ValueError("portfolio policy name cannot be empty")
        if not description:
            raise ValueError("portfolio policy description cannot be empty")

        object.__setattr__(self, "policy_id", policy_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "parameters", parameters)

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "name": self.name,
            "category": self.category.value,
            "scope": self.scope.value,
            "description": self.description,
            "enabled": self.enabled,
            "parameters": {
                key: _serialize_scalar(value) for key, value in self.parameters.items()
            },
        }


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    """Deterministic policy outcome for one candidate or portfolio state."""

    subject: str
    decision: PolicyDecision
    status: PolicyStatus
    score: Decimal
    reasons: tuple[PolicyReason, ...] = ()
    violations: tuple[PolicyViolation, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        subject = self.subject.strip().upper()
        score = _bounded_score(self.score)
        metadata = _normalize_metadata(self.metadata)

        if not subject:
            raise ValueError("policy evaluation subject cannot be empty")

        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "violations", tuple(self.violations))
        object.__setattr__(self, "metadata", metadata)

        self._validate_consistency()

    @property
    def has_blocking_violations(self) -> bool:
        return any(violation.is_blocking for violation in self.violations)

    @property
    def allows_allocation(self) -> bool:
        return self.decision.allows_allocation and not self.has_blocking_violations

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "decision": self.decision.value,
            "status": self.status.value,
            "score": str(self.score),
            "allows_allocation": self.allows_allocation,
            "reasons": [reason.as_dict() for reason in self.reasons],
            "violations": [violation.as_dict() for violation in self.violations],
            "metadata": dict(self.metadata),
        }

    def _validate_consistency(self) -> None:
        if self.decision is PolicyDecision.REJECT and self.status is PolicyStatus.PASS:
            raise ValueError("rejected policy evaluation cannot have PASS status")

        if self.status is PolicyStatus.FAIL and self.decision is PolicyDecision.APPROVE:
            raise ValueError("failed policy evaluation cannot be approved")

        if self.has_blocking_violations and self.decision is PolicyDecision.APPROVE:
            raise ValueError("blocking policy violations cannot be approved")


def _normalize_identifier(value: str, label: str) -> str:
    normalized = value.strip().upper().replace(" ", "_")
    if not normalized:
        raise ValueError(f"{label} cannot be empty")
    return normalized


def _normalize_metadata(metadata: Mapping[str, str]) -> Mapping[str, str]:
    normalized = {
        key.strip(): value.strip()
        for key, value in metadata.items()
        if key.strip() and value.strip()
    }
    return MappingProxyType(dict(sorted(normalized.items())))


def _normalize_parameters(
    parameters: Mapping[str, Decimal | str | bool],
) -> Mapping[str, Decimal | str | bool]:
    normalized: dict[str, Decimal | str | bool] = {}
    for key, value in parameters.items():
        normalized_key = key.strip()
        if not normalized_key:
            raise ValueError("policy parameter key cannot be empty")
        normalized[normalized_key] = _normalize_scalar(value)

    return MappingProxyType(dict(sorted(normalized.items())))


def _normalize_scalar(value: Decimal | str | bool) -> Decimal | str | bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return Decimal(str(value))
    return value.strip()


def _serialize_scalar(value: Decimal | str | bool | None) -> str | bool | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return value


def _bounded_score(value: Decimal) -> Decimal:
    score = Decimal(str(value))
    if score < _ZERO or score > _HUNDRED:
        raise ValueError("policy score must be between 0 and 100")
    return score.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


__all__ = [
    "PolicyCategory",
    "PolicyDecision",
    "PolicyEvaluation",
    "PolicyEvidence",
    "PolicyReason",
    "PolicyScope",
    "PolicySeverity",
    "PolicyStatus",
    "PolicyViolation",
    "PortfolioPolicy",
]
