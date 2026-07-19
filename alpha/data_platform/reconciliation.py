from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal

from alpha.data_platform.models import (
    CanonicalObservation,
    ReconciliationIssue,
    ReconciliationIssueType,
    ReconciliationReport,
    ReconciliationSource,
    Scalar,
    stable_hash,
)

_PRICE_FIELDS = ("open", "high", "low", "close")
_IDENTITY_FIELDS = ("security_id", "symbol", "symbol_as_traded", "isin")
_ACTION_FIELDS = ("action_type", "ratio", "cash_amount", "effective_date")


class ReconciliationEngine:
    """Compare sources and emit immutable conflicts without selecting a winner."""

    def reconcile(
        self,
        sources: tuple[ReconciliationSource, ...],
        *,
        expected_sessions: tuple[date, ...] = (),
        price_tolerance: Decimal = Decimal("0.01"),
        volume_tolerance_ratio: Decimal = Decimal("0.001"),
    ) -> ReconciliationReport:
        names = tuple(sorted(item.source for item in sources))
        if len(set(names)) != len(names):
            raise ValueError("ADP reconciliation source names must be unique")
        issues: list[ReconciliationIssue] = []
        indexed: dict[str, dict[tuple[str, str], CanonicalObservation]] = {}
        for source in sorted(sources, key=lambda item: item.source):
            counts = Counter(
                (item.dataset_id, item.observation_key) for item in source.observations
            )
            for (dataset_id, key), count in sorted(counts.items()):
                if count > 1:
                    issues.append(
                        _issue(
                            ReconciliationIssueType.DUPLICATE_OBSERVATION,
                            dataset_id,
                            key,
                            (source.source,),
                            f"{count} observations share the same source key.",
                        )
                    )
            indexed[source.source] = {
                (item.dataset_id, item.observation_key): item
                for item in source.observations
            }
        all_keys = sorted(
            set().union(*(set(items) for items in indexed.values()))
            if indexed
            else set()
        )
        matching = 0
        for dataset_id, key in all_keys:
            present = tuple(
                (source, records[(dataset_id, key)])
                for source, records in sorted(indexed.items())
                if (dataset_id, key) in records
            )
            missing = tuple(name for name in names if name not in dict(present))
            if missing:
                issues.append(
                    _issue(
                        ReconciliationIssueType.MISSING_OBSERVATION,
                        dataset_id,
                        key,
                        names,
                        "Missing from: " + ", ".join(missing),
                    )
                )
            if len(present) < 2:
                continue
            pair_issues = _compare_fields(
                dataset_id,
                key,
                present,
                price_tolerance=price_tolerance,
                volume_tolerance_ratio=volume_tolerance_ratio,
            )
            issues.extend(pair_issues)
            if not pair_issues and not missing:
                matching += 1
        issues.extend(_missing_session_issues(sources, expected_sessions))
        ordered_issues = tuple(
            sorted(issues, key=lambda item: (item.issue_type.value, item.issue_id))
        )
        return ReconciliationReport(
            compared_sources=names,
            compared_observations=len(all_keys),
            matching_observations=matching,
            issues=ordered_issues,
            automatic_overwrites=0,
        )


def _compare_fields(
    dataset_id: str,
    key: str,
    present: tuple[tuple[str, CanonicalObservation], ...],
    *,
    price_tolerance: Decimal,
    volume_tolerance_ratio: Decimal,
) -> tuple[ReconciliationIssue, ...]:
    by_source = {source: observation for source, observation in present}
    names = tuple(sorted(by_source))
    issues: list[ReconciliationIssue] = []
    if _field_group_differs(by_source, _PRICE_FIELDS, price_tolerance):
        issues.append(
            _issue(
                ReconciliationIssueType.PRICE_MISMATCH,
                dataset_id,
                key,
                names,
                "One or more OHLC values differ beyond tolerance.",
            )
        )
    if _volume_differs(by_source, volume_tolerance_ratio):
        issues.append(
            _issue(
                ReconciliationIssueType.VOLUME_MISMATCH,
                dataset_id,
                key,
                names,
                "Volume differs beyond relative tolerance.",
            )
        )
    if _field_group_differs(by_source, _IDENTITY_FIELDS, Decimal("0")):
        issues.append(
            _issue(
                ReconciliationIssueType.IDENTITY_MISMATCH,
                dataset_id,
                key,
                names,
                "Security identity fields disagree.",
            )
        )
    if _field_group_differs(by_source, _ACTION_FIELDS, Decimal("0")):
        issues.append(
            _issue(
                ReconciliationIssueType.CORPORATE_ACTION_MISMATCH,
                dataset_id,
                key,
                names,
                "Corporate-action terms disagree.",
            )
        )
    return tuple(issues)


def _field_group_differs(
    observations: dict[str, CanonicalObservation],
    fields: tuple[str, ...],
    tolerance: Decimal,
) -> bool:
    for field in fields:
        values = tuple(
            observation.fields[field]
            for observation in observations.values()
            if field in observation.fields
        )
        if len(values) < 2:
            continue
        first = values[0]
        for value in values[1:]:
            if _different(first, value, tolerance):
                return True
    return False


def _different(left: Scalar, right: Scalar, tolerance: Decimal) -> bool:
    if isinstance(left, Decimal) and isinstance(right, Decimal):
        return abs(left - right) > tolerance
    return left != right


def _volume_differs(
    observations: dict[str, CanonicalObservation], tolerance: Decimal
) -> bool:
    values = tuple(
        item.fields["volume"]
        for item in observations.values()
        if isinstance(item.fields.get("volume"), Decimal)
    )
    if len(values) < 2:
        return False
    decimals = tuple(value for value in values if isinstance(value, Decimal))
    largest = max(decimals)
    smallest = min(decimals)
    return largest > 0 and (largest - smallest) / largest > tolerance


def _missing_session_issues(
    sources: tuple[ReconciliationSource, ...], expected: tuple[date, ...]
) -> tuple[ReconciliationIssue, ...]:
    issues = []
    for source in sorted(sources, key=lambda item: item.source):
        observed = {item.observed_on for item in source.observations}
        for session in sorted(set(expected) - observed):
            issues.append(
                _issue(
                    ReconciliationIssueType.MISSING_SESSION,
                    "ALL_DATASETS",
                    session.isoformat(),
                    (source.source,),
                    "Expected trading session has no source observation.",
                )
            )
    return tuple(issues)


def _issue(
    issue_type: ReconciliationIssueType,
    dataset_id: str,
    key: str,
    sources: tuple[str, ...],
    details: str,
) -> ReconciliationIssue:
    normalized_sources = tuple(sorted(sources))
    issue_id = (
        "adp-rec-"
        + stable_hash((issue_type.value, dataset_id, key, normalized_sources, details))[
            :24
        ]
    )
    return ReconciliationIssue(
        issue_id=issue_id,
        issue_type=issue_type,
        dataset_id=dataset_id,
        observation_key=key,
        sources=normalized_sources,
        details=details,
    )


__all__ = ["ReconciliationEngine"]
