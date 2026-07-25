from __future__ import annotations

from alpha.decision_superiority.gate_attribution import (
    NOT_SEMANTICALLY_VALID,
    SEMANTICALLY_VALID,
    build_attribution_artifacts,
)


def _candidate(
    *,
    symbol: str,
    observed_on: str = "2026-01-02",
    price_view: str = "RAW",
) -> dict[str, str]:
    return {
        "price_view": price_view,
        "observed_on": observed_on,
        "symbol": symbol,
        "input_fingerprint": f"fp-{symbol}",
    }


def _event(
    *,
    symbol: str,
    gate_code: str,
    gate_ordinal: int,
    outcome: str,
    stage_reached: bool = True,
    observed_on: str = "2026-01-02",
    price_view: str = "RAW",
) -> dict[str, str]:
    return {
        "price_view": price_view,
        "observed_on": observed_on,
        "symbol": symbol,
        "stage": "INSTITUTIONAL",
        "gate_code": gate_code,
        "gate_category": "TEST",
        "gate_ordinal": str(gate_ordinal),
        "stage_reached": str(stage_reached),
        "outcome": outcome,
        "primary": "false",
    }


def _outcome(
    *,
    symbol: str,
    realized_return_pct: str,
    observed_on: str = "2026-01-02",
    price_view: str = "RAW",
) -> dict[str, str]:
    return {
        "price_view": price_view,
        "observed_on": observed_on,
        "symbol": symbol,
        "completed": "true",
        "won": str(float(realized_return_pct) > 0).lower(),
        "realized_return_pct": realized_return_pct,
        "realized_r": "1",
    }


def _key(
    *,
    symbol: str,
    observed_on: str = "2026-01-02",
    price_view: str = "RAW",
) -> tuple[str, str, str]:
    return price_view, observed_on, symbol


def test_remove_one_gate_counterfactual() -> None:
    candidates = [
        _candidate(symbol="UNIQUE"),
        _candidate(symbol="CO", observed_on="2026-01-03"),
    ]
    gates = [
        _event(
            symbol="UNIQUE",
            gate_code="GATE_A",
            gate_ordinal=1,
            outcome="FAIL",
        ),
        _event(
            symbol="CO",
            observed_on="2026-01-03",
            gate_code="GATE_A",
            gate_ordinal=1,
            outcome="FAIL",
        ),
        _event(
            symbol="CO",
            observed_on="2026-01-03",
            gate_code="GATE_B",
            gate_ordinal=2,
            outcome="FAIL",
        ),
    ]
    outcomes = {
        _key(symbol="UNIQUE"): _outcome(
            symbol="UNIQUE",
            realized_return_pct="4",
        ),
        _key(symbol="CO", observed_on="2026-01-03"): _outcome(
            symbol="CO",
            observed_on="2026-01-03",
            realized_return_pct="-2",
        ),
    }

    result = build_attribution_artifacts(
        candidates=candidates,
        gate_events=gates,
        outcomes_by_key=outcomes,
    )

    rows = {
        (row["symbol"], row["removed_gate_code"]): row for row in result.remove_one_rows
    }

    assert rows[("UNIQUE", "GATE_A")]["would_clear_all_observed_failures"] is True
    assert rows[("UNIQUE", "GATE_A")]["failure_count_after"] == 0
    assert rows[("UNIQUE", "GATE_A")]["attribution_population"] == "UNIQUE_BLOCKER"

    assert rows[("CO", "GATE_A")]["would_clear_all_observed_failures"] is False
    assert rows[("CO", "GATE_A")]["remaining_failure_codes"] == "GATE_B"
    assert rows[("CO", "GATE_A")]["attribution_population"] == "CO_BLOCKED"

    assert rows[("CO", "GATE_B")]["would_clear_all_observed_failures"] is False
    assert rows[("CO", "GATE_B")]["remaining_failure_codes"] == "GATE_A"


def test_retain_only_semantically_valid() -> None:
    candidates = [_candidate(symbol="AAA")]
    gates = [
        _event(
            symbol="AAA",
            gate_code="GATE_A",
            gate_ordinal=1,
            outcome="FAIL",
            stage_reached=True,
        )
    ]
    outcomes = {
        _key(symbol="AAA"): _outcome(
            symbol="AAA",
            realized_return_pct="-3",
        )
    }

    result = build_attribution_artifacts(
        candidates=candidates,
        gate_events=gates,
        outcomes_by_key=outcomes,
    )

    row = result.retain_only_rows[0]

    assert row["retained_gate_code"] == "GATE_A"
    assert row["semantic_status"] == SEMANTICALLY_VALID
    assert row["semantic_reason"] == ""
    assert row["gate_reached"] is True
    assert row["gate_failed"] is True
    assert row["retain_only_decision"] == "REJECTED"


def test_retain_only_not_semantically_valid() -> None:
    candidates = [
        _candidate(symbol="AAA"),
        _candidate(symbol="BBB", observed_on="2026-01-03"),
    ]
    gates = [
        _event(
            symbol="AAA",
            gate_code="GATE_A",
            gate_ordinal=1,
            outcome="FAIL",
        ),
        _event(
            symbol="BBB",
            observed_on="2026-01-03",
            gate_code="GATE_B",
            gate_ordinal=2,
            outcome="FAIL",
        ),
    ]
    outcomes = {
        _key(symbol="AAA"): _outcome(
            symbol="AAA",
            realized_return_pct="2",
        ),
        _key(symbol="BBB", observed_on="2026-01-03"): _outcome(
            symbol="BBB",
            observed_on="2026-01-03",
            realized_return_pct="-1",
        ),
    }

    result = build_attribution_artifacts(
        candidates=candidates,
        gate_events=gates,
        outcomes_by_key=outcomes,
    )

    rows = {
        (row["symbol"], row["retained_gate_code"]): row
        for row in result.retain_only_rows
    }

    missing_gate_row = rows[("AAA", "GATE_B")]
    assert missing_gate_row["semantic_status"] == NOT_SEMANTICALLY_VALID
    assert missing_gate_row["semantic_reason"] == "NO_CANDIDATE_GATE_EVENT"
    assert missing_gate_row["retain_only_decision"] == NOT_SEMANTICALLY_VALID


def test_first_failure_attribution() -> None:
    candidates = [_candidate(symbol="AAA")]
    gates = [
        _event(
            symbol="AAA",
            gate_code="GATE_B",
            gate_ordinal=2,
            outcome="FAIL",
        ),
        _event(
            symbol="AAA",
            gate_code="GATE_A",
            gate_ordinal=1,
            outcome="FAIL",
        ),
    ]
    outcomes = {
        _key(symbol="AAA"): _outcome(
            symbol="AAA",
            realized_return_pct="5",
        )
    }

    result = build_attribution_artifacts(
        candidates=candidates,
        gate_events=gates,
        outcomes_by_key=outcomes,
    )

    row = result.first_failure_rows[0]

    assert row["first_failure_gate_code"] == "GATE_A"
    assert row["first_failure_ordinal"] == 1
    assert row["failure_count"] == 2


def test_ordered_marginal_attribution() -> None:
    candidates = [_candidate(symbol="AAA")]
    gates = [
        _event(
            symbol="AAA",
            gate_code="GATE_C",
            gate_ordinal=3,
            outcome="FAIL",
        ),
        _event(
            symbol="AAA",
            gate_code="GATE_A",
            gate_ordinal=1,
            outcome="FAIL",
        ),
        _event(
            symbol="AAA",
            gate_code="GATE_B",
            gate_ordinal=2,
            outcome="FAIL",
        ),
    ]
    outcomes = {
        _key(symbol="AAA"): _outcome(
            symbol="AAA",
            realized_return_pct="-6",
        )
    }

    result = build_attribution_artifacts(
        candidates=candidates,
        gate_events=gates,
        outcomes_by_key=outcomes,
    )

    rows = list(result.ordered_marginal_rows)

    assert [row["gate_code"] for row in rows] == [
        "GATE_A",
        "GATE_B",
        "GATE_C",
    ]
    assert [row["marginal_step"] for row in rows] == [1, 2, 3]

    assert rows[0]["failure_count_before"] == 3
    assert rows[0]["failure_count_after"] == 2
    assert rows[0]["remaining_failure_codes"] == "GATE_B|GATE_C"
    assert rows[0]["would_clear_all_observed_failures"] is False

    assert rows[1]["failure_count_before"] == 2
    assert rows[1]["failure_count_after"] == 1
    assert rows[1]["remaining_failure_codes"] == "GATE_C"
    assert rows[1]["would_clear_all_observed_failures"] is False

    assert rows[2]["failure_count_before"] == 1
    assert rows[2]["failure_count_after"] == 0
    assert rows[2]["remaining_failure_codes"] == ""
    assert rows[2]["would_clear_all_observed_failures"] is True


def test_gate_attribution_summary() -> None:
    candidates = [
        _candidate(symbol="UNIQUE_A"),
        _candidate(symbol="CO", observed_on="2026-01-03"),
        _candidate(symbol="UNIQUE_B", observed_on="2026-01-04"),
    ]
    gates = [
        _event(
            symbol="UNIQUE_A",
            gate_code="GATE_A",
            gate_ordinal=1,
            outcome="FAIL",
        ),
        _event(
            symbol="CO",
            observed_on="2026-01-03",
            gate_code="GATE_A",
            gate_ordinal=1,
            outcome="FAIL",
        ),
        _event(
            symbol="CO",
            observed_on="2026-01-03",
            gate_code="GATE_B",
            gate_ordinal=2,
            outcome="FAIL",
        ),
        _event(
            symbol="UNIQUE_B",
            observed_on="2026-01-04",
            gate_code="GATE_B",
            gate_ordinal=2,
            outcome="FAIL",
        ),
    ]
    outcomes = {
        _key(symbol="UNIQUE_A"): _outcome(
            symbol="UNIQUE_A",
            realized_return_pct="4",
        ),
        _key(symbol="CO", observed_on="2026-01-03"): _outcome(
            symbol="CO",
            observed_on="2026-01-03",
            realized_return_pct="-2",
        ),
        _key(symbol="UNIQUE_B", observed_on="2026-01-04"): _outcome(
            symbol="UNIQUE_B",
            observed_on="2026-01-04",
            realized_return_pct="-5",
        ),
    }

    result = build_attribution_artifacts(
        candidates=candidates,
        gate_events=gates,
        outcomes_by_key=outcomes,
    )

    summary = {row["gate_code"]: row for row in result.summary_rows}

    gate_a = summary["GATE_A"]
    assert gate_a["all_failures_containing_gate_count"] == 2
    assert gate_a["unique_blocker_count"] == 1
    assert gate_a["co_blocked_count"] == 1
    assert gate_a["first_failure_count"] == 2
    assert gate_a["remove_one_clear_count"] == 1
    assert gate_a["ordered_marginal_clear_count"] == 1
    assert gate_a["retain_only_valid_count"] == 2
    assert gate_a["retain_only_invalid_count"] == 1
    assert gate_a["confounding_present"] is True

    gate_b = summary["GATE_B"]
    assert gate_b["all_failures_containing_gate_count"] == 2
    assert gate_b["unique_blocker_count"] == 1
    assert gate_b["co_blocked_count"] == 1
    assert gate_b["first_failure_count"] == 1
    assert gate_b["remove_one_clear_count"] == 1
    assert gate_b["ordered_marginal_clear_count"] == 2
    assert gate_b["retain_only_valid_count"] == 2
    assert gate_b["retain_only_invalid_count"] == 1
    assert gate_b["confounding_present"] is True


def test_gate_order_lineage_is_deterministic() -> None:
    candidates = [
        _candidate(symbol="AAA"),
        _candidate(symbol="BBB", observed_on="2026-01-03"),
    ]
    gates = [
        _event(
            symbol="BBB",
            observed_on="2026-01-03",
            gate_code="GATE_C",
            gate_ordinal=3,
            outcome="FAIL",
        ),
        _event(
            symbol="AAA",
            gate_code="GATE_B",
            gate_ordinal=2,
            outcome="FAIL",
        ),
        _event(
            symbol="AAA",
            gate_code="GATE_A",
            gate_ordinal=1,
            outcome="FAIL",
        ),
        _event(
            symbol="BBB",
            observed_on="2026-01-03",
            gate_code="GATE_A",
            gate_ordinal=1,
            outcome="FAIL",
        ),
    ]
    outcomes = {
        _key(symbol="AAA"): _outcome(
            symbol="AAA",
            realized_return_pct="1",
        ),
        _key(symbol="BBB", observed_on="2026-01-03"): _outcome(
            symbol="BBB",
            observed_on="2026-01-03",
            realized_return_pct="-1",
        ),
    }

    first = build_attribution_artifacts(
        candidates=candidates,
        gate_events=gates,
        outcomes_by_key=outcomes,
    )
    second = build_attribution_artifacts(
        candidates=list(reversed(candidates)),
        gate_events=list(reversed(gates)),
        outcomes_by_key=dict(reversed(tuple(outcomes.items()))),
    )

    assert first.gate_order_rows == second.gate_order_rows
    assert first.ordered_marginal_rows == second.ordered_marginal_rows
    assert first.summary_rows == second.summary_rows

    assert [row["gate_code"] for row in first.gate_order_rows] == [
        "GATE_A",
        "GATE_B",
        "GATE_C",
    ]
    assert [row["governed_order"] for row in first.gate_order_rows] == [1, 2, 3]
