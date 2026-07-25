"""Deterministic counterfactual and attribution diagnostics for DSI-001."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

CandidateKey = tuple[str, str, str]

NOT_SEMANTICALLY_VALID = "NOT_SEMANTICALLY_VALID"
SEMANTICALLY_VALID = "SEMANTICALLY_VALID"


BASELINE_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "failure_count",
    "failure_codes",
    "observed_policy_decision",
    "resolved_outcome",
    "realized_return_pct",
)

REMOVE_ONE_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "removed_gate_code",
    "failure_count_before",
    "failure_count_after",
    "remaining_failure_codes",
    "would_clear_all_observed_failures",
    "attribution_population",
    "resolved_outcome",
    "realized_return_pct",
)

RETAIN_ONLY_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "retained_gate_code",
    "semantic_status",
    "semantic_reason",
    "gate_reached",
    "gate_failed",
    "retain_only_decision",
    "resolved_outcome",
    "realized_return_pct",
)

FIRST_FAILURE_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "first_failure_gate_code",
    "first_failure_ordinal",
    "failure_count",
    "resolved_outcome",
    "realized_return_pct",
)

ORDERED_MARGINAL_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "gate_code",
    "gate_ordinal",
    "marginal_step",
    "failure_count_before",
    "failure_count_after",
    "remaining_failure_codes",
    "would_clear_all_observed_failures",
    "resolved_outcome",
    "realized_return_pct",
)

ATTRIBUTION_SUMMARY_FIELDS = (
    "gate_code",
    "all_failures_containing_gate_count",
    "unique_blocker_count",
    "co_blocked_count",
    "first_failure_count",
    "remove_one_clear_count",
    "ordered_marginal_clear_count",
    "retain_only_valid_count",
    "retain_only_invalid_count",
    "confounding_present",
)


@dataclass(frozen=True, slots=True)
class AttributionArtifacts:
    """Immutable DSI-001 attribution artifact rows."""

    baseline_rows: tuple[dict[str, object], ...]
    remove_one_rows: tuple[dict[str, object], ...]
    retain_only_rows: tuple[dict[str, object], ...]
    first_failure_rows: tuple[dict[str, object], ...]
    ordered_marginal_rows: tuple[dict[str, object], ...]
    summary_rows: tuple[dict[str, object], ...]
    gate_order_rows: tuple[dict[str, object], ...]


def build_attribution_artifacts(
    *,
    candidates: list[dict[str, str]],
    gate_events: list[dict[str, str]],
    outcomes_by_key: dict[CandidateKey, dict[str, str]],
) -> AttributionArtifacts:
    """Build deterministic, diagnostic-only counterfactual attribution rows."""

    events_by_key: dict[CandidateKey, list[dict[str, str]]] = defaultdict(list)
    gate_min_ordinal: dict[str, int] = {}

    for event in gate_events:
        key = _key(event)
        events_by_key[key].append(event)
        gate_code = _gate_code(event)
        ordinal = _ordinal(event)
        current = gate_min_ordinal.get(gate_code)
        gate_min_ordinal[gate_code] = (
            ordinal if current is None else min(current, ordinal)
        )

    ordered_gate_codes = tuple(
        gate
        for gate, _ in sorted(
            gate_min_ordinal.items(),
            key=lambda item: (item[1], item[0]),
        )
    )
    gate_order_rows = tuple(
        {
            "gate_code": gate_code,
            "governed_order": index,
            "minimum_observed_ordinal": gate_min_ordinal[gate_code],
        }
        for index, gate_code in enumerate(ordered_gate_codes, start=1)
    )

    baseline_rows: list[dict[str, object]] = []
    remove_one_rows: list[dict[str, object]] = []
    retain_only_rows: list[dict[str, object]] = []
    first_failure_rows: list[dict[str, object]] = []
    ordered_marginal_rows: list[dict[str, object]] = []

    all_failure_count: Counter[str] = Counter()
    unique_count: Counter[str] = Counter()
    co_count: Counter[str] = Counter()
    first_count: Counter[str] = Counter()
    remove_clear_count: Counter[str] = Counter()
    ordered_clear_count: Counter[str] = Counter()
    retain_valid_count: Counter[str] = Counter()
    retain_invalid_count: Counter[str] = Counter()

    for candidate in sorted(candidates, key=_candidate_sort_key):
        key = _key(candidate)
        events = events_by_key.get(key, [])
        outcome = outcomes_by_key.get(key)
        resolved = outcome is not None
        realized_return = _decimal((outcome or {}).get("realized_return_pct", ""))

        failure_events = _distinct_failed_events(events)
        failure_codes = tuple(_gate_code(event) for event in failure_events)
        unique = len(failure_codes) == 1

        common = {
            "price_view": candidate.get("price_view", ""),
            "observed_on": candidate.get("observed_on", ""),
            "symbol": candidate.get("symbol", ""),
        }

        baseline_rows.append(
            {
                **common,
                "failure_count": len(failure_codes),
                "failure_codes": "|".join(failure_codes),
                "observed_policy_decision": (
                    "REJECTED" if failure_codes else "NOT_REJECTED_BY_OBSERVED_GATES"
                ),
                "resolved_outcome": resolved,
                "realized_return_pct": realized_return if resolved else "",
            }
        )

        for gate_code in failure_codes:
            all_failure_count[gate_code] += 1
            if unique:
                unique_count[gate_code] += 1
            else:
                co_count[gate_code] += 1

            remaining = tuple(code for code in failure_codes if code != gate_code)
            clears = not remaining
            if clears:
                remove_clear_count[gate_code] += 1

            remove_one_rows.append(
                {
                    **common,
                    "removed_gate_code": gate_code,
                    "failure_count_before": len(failure_codes),
                    "failure_count_after": len(remaining),
                    "remaining_failure_codes": "|".join(remaining),
                    "would_clear_all_observed_failures": clears,
                    "attribution_population": (
                        "UNIQUE_BLOCKER" if unique else "CO_BLOCKED"
                    ),
                    "resolved_outcome": resolved,
                    "realized_return_pct": realized_return if resolved else "",
                }
            )

        if failure_events:
            first = failure_events[0]
            first_gate = _gate_code(first)
            first_count[first_gate] += 1
            first_failure_rows.append(
                {
                    **common,
                    "first_failure_gate_code": first_gate,
                    "first_failure_ordinal": _ordinal(first),
                    "failure_count": len(failure_codes),
                    "resolved_outcome": resolved,
                    "realized_return_pct": realized_return if resolved else "",
                }
            )

        remaining_ordered = list(failure_codes)
        for step, event in enumerate(failure_events, start=1):
            gate_code = _gate_code(event)
            before = len(remaining_ordered)
            remaining_ordered = [
                code for code in remaining_ordered if code != gate_code
            ]
            after = len(remaining_ordered)
            clears = after == 0
            if clears:
                ordered_clear_count[gate_code] += 1

            ordered_marginal_rows.append(
                {
                    **common,
                    "gate_code": gate_code,
                    "gate_ordinal": _ordinal(event),
                    "marginal_step": step,
                    "failure_count_before": before,
                    "failure_count_after": after,
                    "remaining_failure_codes": "|".join(remaining_ordered),
                    "would_clear_all_observed_failures": clears,
                    "resolved_outcome": resolved,
                    "realized_return_pct": realized_return if resolved else "",
                }
            )

        event_by_gate = _events_by_gate(events)
        for gate_code in ordered_gate_codes:
            gate_rows = event_by_gate.get(gate_code, ())
            reached = any(_truthy(row.get("stage_reached")) for row in gate_rows)
            failed = any(
                str(row.get("outcome", "")).strip().upper() == "FAIL"
                for row in gate_rows
            )

            if not gate_rows:
                semantic_status = NOT_SEMANTICALLY_VALID
                semantic_reason = "NO_CANDIDATE_GATE_EVENT"
                decision = NOT_SEMANTICALLY_VALID
                retain_invalid_count[gate_code] += 1
            elif not reached:
                semantic_status = NOT_SEMANTICALLY_VALID
                semantic_reason = "GATE_NOT_REACHED_UNDER_OBSERVED_PATH"
                decision = NOT_SEMANTICALLY_VALID
                retain_invalid_count[gate_code] += 1
            else:
                semantic_status = SEMANTICALLY_VALID
                semantic_reason = ""
                decision = "REJECTED" if failed else "NOT_REJECTED"
                retain_valid_count[gate_code] += 1

            retain_only_rows.append(
                {
                    **common,
                    "retained_gate_code": gate_code,
                    "semantic_status": semantic_status,
                    "semantic_reason": semantic_reason,
                    "gate_reached": reached,
                    "gate_failed": failed,
                    "retain_only_decision": decision,
                    "resolved_outcome": resolved,
                    "realized_return_pct": realized_return if resolved else "",
                }
            )

    summary_rows = tuple(
        {
            "gate_code": gate_code,
            "all_failures_containing_gate_count": all_failure_count[gate_code],
            "unique_blocker_count": unique_count[gate_code],
            "co_blocked_count": co_count[gate_code],
            "first_failure_count": first_count[gate_code],
            "remove_one_clear_count": remove_clear_count[gate_code],
            "ordered_marginal_clear_count": ordered_clear_count[gate_code],
            "retain_only_valid_count": retain_valid_count[gate_code],
            "retain_only_invalid_count": retain_invalid_count[gate_code],
            "confounding_present": co_count[gate_code] > 0,
        }
        for gate_code in ordered_gate_codes
    )

    return AttributionArtifacts(
        baseline_rows=tuple(baseline_rows),
        remove_one_rows=tuple(remove_one_rows),
        retain_only_rows=tuple(retain_only_rows),
        first_failure_rows=tuple(first_failure_rows),
        ordered_marginal_rows=tuple(ordered_marginal_rows),
        summary_rows=summary_rows,
        gate_order_rows=gate_order_rows,
    )


def _events_by_gate(
    events: list[dict[str, str]],
) -> dict[str, tuple[dict[str, str], ...]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for event in events:
        grouped[_gate_code(event)].append(event)
    return {
        gate: tuple(sorted(rows, key=_event_sort_key)) for gate, rows in grouped.items()
    }


def _distinct_failed_events(
    events: list[dict[str, str]],
) -> tuple[dict[str, str], ...]:
    first_by_gate: dict[str, dict[str, str]] = {}
    for event in sorted(events, key=_event_sort_key):
        if str(event.get("outcome", "")).strip().upper() != "FAIL":
            continue
        first_by_gate.setdefault(_gate_code(event), event)
    return tuple(sorted(first_by_gate.values(), key=_event_sort_key))


def _event_sort_key(row: dict[str, str]) -> tuple[int, str]:
    return (_ordinal(row), _gate_code(row))


def _candidate_sort_key(row: dict[str, str]) -> CandidateKey:
    return _key(row)


def _key(row: dict[str, str]) -> CandidateKey:
    return (
        str(row.get("price_view", "")),
        str(row.get("observed_on", "")),
        str(row.get("symbol", "")),
    )


def _gate_code(row: dict[str, str]) -> str:
    return str(row.get("gate_code") or "UNKNOWN")


def _ordinal(row: dict[str, str]) -> int:
    try:
        return int(str(row.get("gate_ordinal") or "0"))
    except ValueError:
        return 0


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except InvalidOperation:
        return Decimal("0")
