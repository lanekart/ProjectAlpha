"""Governed DSI-013 intraday source-readiness certification engine."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from enum import Enum
from types import MappingProxyType
from typing import Any

from alpha.decision_superiority.intraday_execution_models import (
    DSI013_RESEARCH_SCOPE,
    IntradayBar,
    IntradayExecutionPolicy,
    IntradayReadiness,
)
from alpha.decision_superiority.intraday_execution_population import (
    IntradayPopulationPlan,
    PlannedIntradayRequest,
)
from alpha.decision_superiority.intraday_execution_reconciliation import (
    DailyCandleReference,
    DailyReconciliationResult,
    IdentityResolutionState,
    InstrumentResolution,
    reconcile_raw_daily_session,
)
from alpha.decision_superiority.intraday_execution_source import audit_intraday_bars

DSI013_SOURCE_CONTRACT_VERSION = "DSI-013-SOURCE-v1.0.0"


@dataclass(frozen=True, slots=True)
class IntradaySourceEvidence:
    """Caller-supplied immutable evidence for source certification."""

    source_commit: str
    population: IntradayPopulationPlan
    identity_resolutions: Mapping[str, InstrumentResolution]
    bars_by_request: Mapping[tuple[str, date], Sequence[IntradayBar]]
    daily_by_request: Mapping[tuple[str, date], DailyCandleReference]


@dataclass(frozen=True, slots=True)
class IntradaySourceCertificationResult:
    """Deterministic source-readiness evidence and decision."""

    source_commit: str
    readiness: IntradayReadiness
    blockers: tuple[str, ...]
    rows: MappingProxyType[str, tuple[dict[str, Any], ...]]
    summaries: MappingProxyType[str, Any]
    governance: MappingProxyType[str, bool]


def source_governance_flags() -> dict[str, bool]:
    """Return the immutable source-certification governance boundary."""

    return {
        "VALIDATED_STRATEGY": False,
        "INTRADAY_LIVE_TRADING_ENABLED": False,
        "AUTOMATIC_STRATEGY_PROMOTION_ENABLED": False,
        "RECOMMENDATION_INFLUENCE": False,
        "PORTFOLIO_POLICY_INFLUENCE": False,
        "EXECUTION_INFLUENCE": False,
        "LEARNING_MUTATION_ENABLED": False,
        "PRODUCTION_INFLUENCE": False,
        "ONE_MINUTE_STRATEGY_MINING_ENABLED": False,
        "FULL_UNIVERSE_INTRADAY_SWEEP_ENABLED": False,
        "MISSING_BAR_FORWARD_FILL_ENABLED": False,
        "SYMBOL_ONLY_IDENTITY_ENABLED": False,
    }


class GovernedIntradaySourceCertificationEngine:
    """Certify the candidate-bounded broker source before strategy research."""

    def run(
        self,
        evidence: IntradaySourceEvidence,
        *,
        policy: IntradayExecutionPolicy | None = None,
    ) -> IntradaySourceCertificationResult:
        """Validate every planned identity/session request fail-closed."""

        active_policy = policy or IntradayExecutionPolicy()
        rows: dict[str, list[dict[str, Any]]] = {
            "source_contract": [],
            "candidate_population": [],
            "request_plan": [],
            "identity_resolution": [],
            "bar_validation": [],
            "session_validation": [],
            "daily_reconciliation": [],
            "source_exclusions": list(evidence.population.exclusions),
            "population_reconciliation": list(evidence.population.reconciliation),
        }
        blockers: list[str] = []
        identity_failure_count = 0
        source_unavailable_count = 0
        session_failure_count = 0
        reconciliation_failure_count = 0

        rows["source_contract"].extend(
            _source_contract_rows(evidence=evidence, policy=active_policy)
        )
        rows["candidate_population"].extend(
            _candidate_rows(evidence.population)
        )
        rows["request_plan"].extend(_request_rows(evidence.population.requests))

        for request in evidence.population.requests:
            identity = request.identity_key
            key = (identity, request.session_date)
            resolution = evidence.identity_resolutions.get(identity)
            if resolution is None:
                identity_failure_count += 1
                blocker = f"DSI013_IDENTITY_RESOLUTION_MISSING:{identity}"
                blockers.append(blocker)
                rows["identity_resolution"].append(
                    {
                        "identity_key": identity,
                        "state": IdentityResolutionState.SOURCE_RECORD_MISSING.value,
                        "instrument_key": None,
                        "source_sha256": None,
                        "resolved_at": None,
                        "blocker": blocker,
                    }
                )
                continue
            rows["identity_resolution"].append(_identity_row(resolution))
            if (
                resolution.state is not IdentityResolutionState.RESOLVED
                or resolution.instrument is None
            ):
                identity_failure_count += 1
                blockers.append(
                    resolution.blocker
                    or f"DSI013_IDENTITY_RESOLUTION_FAILED:{identity}"
                )
                continue

            bars = tuple(evidence.bars_by_request.get(key, ()))
            if not bars:
                source_unavailable_count += 1
                blocker = (
                    "DSI013_INTRADAY_SOURCE_BARS_MISSING:"
                    f"{identity}:{request.session_date.isoformat()}"
                )
                blockers.append(blocker)
                rows["source_exclusions"].append(
                    _request_exclusion(request, "INTRADAY_SOURCE_BARS_MISSING")
                )
                continue

            audit = audit_intraday_bars(
                bars,
                policy=active_policy,
                regular_session_dates=frozenset({request.session_date}),
            )
            rows["bar_validation"].extend(
                _attach_request(row, request) for row in audit.validation_rows
            )
            rows["session_validation"].extend(
                _attach_request(row, request) for row in audit.session_rows
            )
            if audit.readiness is not IntradayReadiness.SOURCE_READY:
                session_failure_count += 1
                blockers.extend(audit.blockers)
                continue

            daily = evidence.daily_by_request.get(key)
            if daily is None:
                reconciliation_failure_count += 1
                blocker = (
                    "DSI013_RAW_DAILY_REFERENCE_MISSING:"
                    f"{identity}:{request.session_date.isoformat()}"
                )
                blockers.append(blocker)
                rows["source_exclusions"].append(
                    _request_exclusion(request, "RAW_DAILY_REFERENCE_MISSING")
                )
                continue
            reconciliation = reconcile_raw_daily_session(
                bars,
                daily,
                instrument_key=resolution.instrument.instrument_key,
                policy=active_policy,
            )
            rows["daily_reconciliation"].extend(
                _reconciliation_rows(request, reconciliation)
            )
            if not reconciliation.passed:
                reconciliation_failure_count += 1
                blockers.extend(reconciliation.blockers)

        readiness = _source_readiness(
            identity_failure_count=identity_failure_count,
            source_unavailable_count=source_unavailable_count,
            session_failure_count=session_failure_count,
            reconciliation_failure_count=reconciliation_failure_count,
        )
        unique_blockers = tuple(sorted(set(blockers)))
        summaries = {
            "research_scope": DSI013_RESEARCH_SCOPE,
            "candidate_count": len(evidence.population.candidates),
            "request_count": len(evidence.population.requests),
            "identity_resolution_count": len(evidence.identity_resolutions),
            "identity_failure_count": identity_failure_count,
            "source_unavailable_count": source_unavailable_count,
            "session_failure_count": session_failure_count,
            "reconciliation_failure_count": reconciliation_failure_count,
            "admitted_request_count": (
                len(evidence.population.requests)
                - identity_failure_count
                - source_unavailable_count
                - session_failure_count
                - reconciliation_failure_count
            ),
            "readiness": readiness.value,
            "blocker_count": len(unique_blockers),
        }
        return IntradaySourceCertificationResult(
            source_commit=evidence.source_commit,
            readiness=readiness,
            blockers=unique_blockers,
            rows=MappingProxyType(
                {
                    key: tuple(_normalise(row) for row in value)
                    for key, value in rows.items()
                }
            ),
            summaries=MappingProxyType(_normalise(summaries)),
            governance=MappingProxyType(source_governance_flags()),
        )


def _source_readiness(
    *,
    identity_failure_count: int,
    source_unavailable_count: int,
    session_failure_count: int,
    reconciliation_failure_count: int,
) -> IntradayReadiness:
    if identity_failure_count:
        return IntradayReadiness.IDENTITY_DEFECT
    if source_unavailable_count:
        return IntradayReadiness.SOURCE_UNAVAILABLE
    if session_failure_count:
        return IntradayReadiness.SESSION_INTEGRITY_DEFECT
    if reconciliation_failure_count:
        return IntradayReadiness.DAILY_RECONCILIATION_DEFECT
    return IntradayReadiness.SOURCE_READY


def _source_contract_rows(
    *,
    evidence: IntradaySourceEvidence,
    policy: IntradayExecutionPolicy,
) -> list[dict[str, Any]]:
    return [
        {
            "source_role": "DSI009_CERTIFICATE",
            "sha256": evidence.population.dsi009_certificate_sha256,
            "required": True,
        },
        {
            "source_role": "UPSTOX_V3_HISTORICAL_CANDLES",
            "sha256": "PER_REQUEST_RAW_SHA256_IN_IMMUTABLE_CACHE",
            "required": True,
        },
        {
            "source_role": "GOVERNED_RAW_DAILY_CANDLES",
            "sha256": "PER_SESSION_SOURCE_SHA256",
            "required": True,
        },
        {
            "source_role": "PRIMARY_INTERVAL_MINUTES",
            "sha256": str(policy.interval_minutes),
            "required": True,
        },
        {
            "source_role": "COMPARISON_WINDOW",
            "sha256": (
                f"{policy.comparison_start.isoformat()}_"
                f"{policy.comparison_end.isoformat()}"
            ),
            "required": True,
        },
    ]


def _candidate_rows(population: IntradayPopulationPlan) -> list[dict[str, Any]]:
    return [_normalise(asdict(candidate)) for candidate in population.candidates]


def _request_rows(
    requests: Sequence[PlannedIntradayRequest],
) -> list[dict[str, Any]]:
    return [
        {
            "identity_key": request.identity_key,
            "session_date": request.session_date.isoformat(),
            "signal_ids": "|".join(request.signal_ids),
            "signal_count": len(request.signal_ids),
            "candidate_bounded": True,
        }
        for request in requests
    ]


def _identity_row(resolution: InstrumentResolution) -> dict[str, Any]:
    instrument = resolution.instrument
    return {
        "identity_key": resolution.governed_identity,
        "governed_isin": resolution.governed_isin,
        "state": resolution.state.value,
        "instrument_key": None if instrument is None else instrument.instrument_key,
        "trading_symbol": None if instrument is None else instrument.trading_symbol,
        "exchange_token": None if instrument is None else instrument.exchange_token,
        "source_sha256": resolution.source_sha256,
        "resolved_at": resolution.resolved_at.isoformat(),
        "blocker": resolution.blocker,
    }


def _attach_request(
    row: Mapping[str, Any],
    request: PlannedIntradayRequest,
) -> dict[str, Any]:
    return {
        "request_identity_key": request.identity_key,
        "request_session_date": request.session_date.isoformat(),
        "request_signal_ids": "|".join(request.signal_ids),
        **dict(row),
    }


def _reconciliation_rows(
    request: PlannedIntradayRequest,
    result: DailyReconciliationResult,
) -> list[dict[str, Any]]:
    return [
        {
            "identity_key": request.identity_key,
            "session_date": request.session_date.isoformat(),
            "signal_ids": "|".join(request.signal_ids),
            "state": result.state.value,
            "metric": row["metric"],
            "expected": row["expected"],
            "actual": row["actual"],
            "delta": row["delta"],
            "tolerance": row["tolerance"],
            "passed": row["passed"],
            "blockers": "|".join(result.blockers),
        }
        for row in result.metric_rows
    ]


def _request_exclusion(
    request: PlannedIntradayRequest,
    reason: str,
) -> dict[str, Any]:
    return {
        "signal_id": "|".join(request.signal_ids),
        "identity_key": request.identity_key,
        "signal_date": "",
        "entry_eligibility_date": request.session_date.isoformat(),
        "reason": reason,
        "detail": request.session_date.isoformat(),
    }


def _normalise(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalise(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_normalise(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


__all__ = [
    "DSI013_SOURCE_CONTRACT_VERSION",
    "GovernedIntradaySourceCertificationEngine",
    "IntradaySourceCertificationResult",
    "IntradaySourceEvidence",
    "source_governance_flags",
]
