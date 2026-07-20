from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
import csv
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from enum import IntEnum, StrEnum
from io import StringIO
import json


class EvidenceRegistryError(ValueError):
    """Raised when evidence governance invariants are violated."""


class EvidenceCategory(StrEnum):
    PRICE = "PRICE"
    VOLUME = "VOLUME"
    TREND = "TREND"
    VOLATILITY = "VOLATILITY"
    RELATIVE_STRENGTH = "RELATIVE_STRENGTH"
    MARKET_REGIME = "MARKET_REGIME"
    SECTOR = "SECTOR"
    FUNDAMENTALS = "FUNDAMENTALS"
    CORPORATE_ACTIONS = "CORPORATE_ACTIONS"
    MACRO = "MACRO"
    SENTIMENT = "SENTIMENT"
    OPTIONS = "OPTIONS"
    NEWS = "NEWS"
    PORTFOLIO = "PORTFOLIO"
    OTHER = "OTHER"


class EvidenceMaturity(IntEnum):
    PROTOTYPE = 0
    DETERMINISTIC = 1
    REPLAY_VERIFIED = 2
    FORWARD_VALIDATED = 3
    PRODUCTION_TRUSTED = 4
    SELF_CALIBRATING = 5


class EvidenceStatus(StrEnum):
    EXPERIMENTAL = "EXPERIMENTAL"
    ACTIVE = "ACTIVE"
    PENALIZED = "PENALIZED"
    SUSPENDED = "SUSPENDED"
    DEPRECATED = "DEPRECATED"


class GovernanceEnvironment(StrEnum):
    RESEARCH = "RESEARCH"
    SHADOW = "SHADOW"
    PRODUCTION = "PRODUCTION"


class GovernanceVerdict(StrEnum):
    ALLOWED = "ALLOWED"
    DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class EvidenceMetadata:
    evidence_id: str
    display_name: str
    provider: str
    category: EvidenceCategory
    version: str
    owner: str
    maturity: EvidenceMaturity
    status: EvidenceStatus
    replay_verified: bool
    minimum_sample_size: int
    current_sample_size: int
    precision: Decimal | None = None
    lift: Decimal | None = None
    calibration_error: Decimal | None = None
    applicable_regimes: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    last_validation: date | None = None
    last_calibration: date | None = None
    documentation: str | None = None
    production_influence: bool = False

    def __post_init__(self) -> None:
        evidence_id = self.evidence_id.strip().upper()
        display_name = self.display_name.strip()
        provider = self.provider.strip()
        version = self.version.strip()
        owner = self.owner.strip()
        if not evidence_id:
            raise EvidenceRegistryError("evidence_id cannot be empty")
        if not display_name:
            raise EvidenceRegistryError("display_name cannot be empty")
        if not provider:
            raise EvidenceRegistryError("provider cannot be empty")
        if not version:
            raise EvidenceRegistryError("version cannot be empty")
        if not owner:
            raise EvidenceRegistryError("owner cannot be empty")
        if self.minimum_sample_size < 0 or self.current_sample_size < 0:
            raise EvidenceRegistryError("sample sizes cannot be negative")
        for field_name, value in (
            ("precision", self.precision),
            ("calibration_error", self.calibration_error),
        ):
            if value is not None and not Decimal("0") <= value <= Decimal("1"):
                raise EvidenceRegistryError(f"{field_name} must be between 0 and 1")
        if self.production_influence:
            raise EvidenceRegistryError(
                "registry metadata cannot directly influence production execution"
            )
        maturity = EvidenceMaturity(self.maturity)
        if maturity >= EvidenceMaturity.REPLAY_VERIFIED and not self.replay_verified:
            raise EvidenceRegistryError(
                "replay-verified maturity requires replay_verified=True"
            )
        if (
            maturity >= EvidenceMaturity.FORWARD_VALIDATED
            and self.last_validation is None
        ):
            raise EvidenceRegistryError(
                "forward-validated maturity requires last_validation"
            )
        object.__setattr__(self, "evidence_id", evidence_id)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "owner", owner)
        object.__setattr__(self, "category", EvidenceCategory(self.category))
        object.__setattr__(self, "maturity", maturity)
        object.__setattr__(self, "status", EvidenceStatus(self.status))
        object.__setattr__(self, "applicable_regimes", _normalize_tokens(self.applicable_regimes))
        object.__setattr__(self, "dependencies", _normalize_tokens(self.dependencies))
        object.__setattr__(self, "outputs", _normalize_tokens(self.outputs))

    @property
    def sample_ready(self) -> bool:
        return self.current_sample_size >= self.minimum_sample_size

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["category"] = self.category.value
        payload["maturity"] = int(self.maturity)
        payload["maturity_name"] = self.maturity.name
        payload["status"] = self.status.value
        for key in ("precision", "lift", "calibration_error"):
            value = payload[key]
            payload[key] = None if value is None else str(value)
        for key in ("last_validation", "last_calibration"):
            value = payload[key]
            payload[key] = None if value is None else value.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class GovernancePolicy:
    environment: GovernanceEnvironment
    minimum_maturity: EvidenceMaturity
    require_sample_ready: bool = True
    allowed_statuses: tuple[EvidenceStatus, ...] = (EvidenceStatus.ACTIVE,)

    def __post_init__(self) -> None:
        object.__setattr__(self, "environment", GovernanceEnvironment(self.environment))
        object.__setattr__(self, "minimum_maturity", EvidenceMaturity(self.minimum_maturity))
        object.__setattr__(
            self,
            "allowed_statuses",
            tuple(EvidenceStatus(status) for status in self.allowed_statuses),
        )

    @classmethod
    def research(cls) -> GovernancePolicy:
        return cls(
            environment=GovernanceEnvironment.RESEARCH,
            minimum_maturity=EvidenceMaturity.PROTOTYPE,
            require_sample_ready=False,
            allowed_statuses=(
                EvidenceStatus.EXPERIMENTAL,
                EvidenceStatus.ACTIVE,
                EvidenceStatus.PENALIZED,
            ),
        )

    @classmethod
    def shadow(cls) -> GovernancePolicy:
        return cls(
            environment=GovernanceEnvironment.SHADOW,
            minimum_maturity=EvidenceMaturity.REPLAY_VERIFIED,
            allowed_statuses=(EvidenceStatus.ACTIVE, EvidenceStatus.PENALIZED),
        )

    @classmethod
    def production(cls) -> GovernancePolicy:
        return cls(
            environment=GovernanceEnvironment.PRODUCTION,
            minimum_maturity=EvidenceMaturity.FORWARD_VALIDATED,
            allowed_statuses=(EvidenceStatus.ACTIVE,),
        )


@dataclass(frozen=True, slots=True)
class GovernanceAssessment:
    evidence_id: str
    environment: GovernanceEnvironment
    verdict: GovernanceVerdict
    reasons: tuple[str, ...]


class EvidenceRegistry:
    """Deterministic registry for governed evidence metadata."""

    def __init__(self, entries: Iterable[EvidenceMetadata] = ()) -> None:
        self._entries: dict[str, EvidenceMetadata] = {}
        for entry in entries:
            self.register(entry)

    def register(self, metadata: EvidenceMetadata) -> None:
        existing = self._entries.get(metadata.evidence_id)
        if existing is not None and existing != metadata:
            raise EvidenceRegistryError(
                f"conflicting registration for {metadata.evidence_id}"
            )
        self._entries[metadata.evidence_id] = metadata

    def get(self, evidence_id: str) -> EvidenceMetadata:
        key = evidence_id.strip().upper()
        try:
            return self._entries[key]
        except KeyError as exc:
            raise KeyError(key) from exc

    def all(self) -> tuple[EvidenceMetadata, ...]:
        return tuple(self._entries[key] for key in sorted(self._entries))

    def assess(
        self,
        evidence_id: str,
        policy: GovernancePolicy,
    ) -> GovernanceAssessment:
        metadata = self.get(evidence_id)
        reasons: list[str] = []
        if metadata.status not in policy.allowed_statuses:
            reasons.append(f"status {metadata.status.value} is not allowed")
        if metadata.maturity < policy.minimum_maturity:
            reasons.append(
                "maturity "
                f"{metadata.maturity.name} is below {policy.minimum_maturity.name}"
            )
        if policy.require_sample_ready and not metadata.sample_ready:
            reasons.append("minimum sample size has not been reached")
        if metadata.status in {EvidenceStatus.SUSPENDED, EvidenceStatus.DEPRECATED}:
            verdict = GovernanceVerdict.BLOCKED
        elif reasons:
            verdict = GovernanceVerdict.DIAGNOSTIC_ONLY
        else:
            verdict = GovernanceVerdict.ALLOWED
        return GovernanceAssessment(
            evidence_id=metadata.evidence_id,
            environment=policy.environment,
            verdict=verdict,
            reasons=tuple(reasons),
        )


@dataclass(frozen=True, slots=True)
class RegistrySummary:
    total_entries: int
    maturity_counts: tuple[tuple[EvidenceMaturity, int], ...]
    status_counts: tuple[tuple[EvidenceStatus, int], ...]
    sample_ready_count: int
    replay_verified_count: int
    unknown_precision_count: int
    production_influence: bool = False

    def __post_init__(self) -> None:
        if self.total_entries < 0:
            raise EvidenceRegistryError("total_entries cannot be negative")
        if self.production_influence:
            raise EvidenceRegistryError(
                "registry summary cannot influence production execution"
            )


def build_registry_summary(entries: Iterable[EvidenceMetadata]) -> RegistrySummary:
    materialized = tuple(entries)
    maturity_counter = Counter(entry.maturity for entry in materialized)
    status_counter = Counter(entry.status for entry in materialized)
    return RegistrySummary(
        total_entries=len(materialized),
        maturity_counts=tuple(
            (maturity, maturity_counter.get(maturity, 0))
            for maturity in EvidenceMaturity
        ),
        status_counts=tuple(
            (status, status_counter.get(status, 0)) for status in EvidenceStatus
        ),
        sample_ready_count=sum(entry.sample_ready for entry in materialized),
        replay_verified_count=sum(entry.replay_verified for entry in materialized),
        unknown_precision_count=sum(entry.precision is None for entry in materialized),
    )


def render_registry_summary(summary: RegistrySummary) -> tuple[str, ...]:
    lines = [
        "Evidence Registry Summary",
        f"Total Evidence Providers: {summary.total_entries}",
        f"Sample Ready: {summary.sample_ready_count}",
        f"Replay Verified: {summary.replay_verified_count}",
        f"Unknown Precision: {summary.unknown_precision_count}",
        "Maturity:",
    ]
    lines.extend(
        f"- L{int(maturity)} {maturity.name}: {count}"
        for maturity, count in summary.maturity_counts
    )
    lines.append("Status:")
    lines.extend(f"- {status.value}: {count}" for status, count in summary.status_counts)
    lines.append("Execution Status: NON-EXECUTABLE GOVERNANCE METADATA")
    return tuple(lines)


def export_registry_json(entries: Iterable[EvidenceMetadata]) -> str:
    return json.dumps(
        [entry.to_dict() for entry in sorted(entries, key=lambda item: item.evidence_id)],
        indent=2,
        sort_keys=True,
    )


def export_registry_csv(entries: Iterable[EvidenceMetadata]) -> str:
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        (
            "evidence_id",
            "display_name",
            "provider",
            "category",
            "version",
            "owner",
            "maturity",
            "status",
            "replay_verified",
            "minimum_sample_size",
            "current_sample_size",
            "sample_ready",
            "precision",
            "lift",
            "calibration_error",
            "applicable_regimes",
            "dependencies",
            "outputs",
            "last_validation",
            "last_calibration",
            "documentation",
            "production_influence",
        )
    )
    for entry in sorted(entries, key=lambda item: item.evidence_id):
        writer.writerow(
            (
                entry.evidence_id,
                entry.display_name,
                entry.provider,
                entry.category.value,
                entry.version,
                entry.owner,
                f"L{int(entry.maturity)}:{entry.maturity.name}",
                entry.status.value,
                str(entry.replay_verified).lower(),
                entry.minimum_sample_size,
                entry.current_sample_size,
                str(entry.sample_ready).lower(),
                "" if entry.precision is None else entry.precision,
                "" if entry.lift is None else entry.lift,
                "" if entry.calibration_error is None else entry.calibration_error,
                "|".join(entry.applicable_regimes),
                "|".join(entry.dependencies),
                "|".join(entry.outputs),
                "" if entry.last_validation is None else entry.last_validation.isoformat(),
                "" if entry.last_calibration is None else entry.last_calibration.isoformat(),
                "" if entry.documentation is None else entry.documentation,
                str(entry.production_influence).lower(),
            )
        )
    return output.getvalue()


def _normalize_tokens(values: Iterable[str]) -> tuple[str, ...]:
    normalized = {value.strip().upper() for value in values if value.strip()}
    return tuple(sorted(normalized))
