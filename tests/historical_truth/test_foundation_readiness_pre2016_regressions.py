from __future__ import annotations

from alpha.historical_truth.foundation_readiness_engine import (
    readiness_decision,
    resolve_discrepancies,
)
from alpha.historical_truth.foundation_readiness_models import (
    FoundationReadiness,
    JoinReadiness,
)


def test_unmapped_external_era_discrepancy_is_retained_and_blocks_readiness() -> None:
    rows = resolve_discrepancies(
        [
            {
                "symbol": "SRICHAMUND",
                "identity_key": "nse:isin:INE000S01001",
                "derived_interval_state": "DERIVED_ACTIVE_PROVISIONAL",
                "checkpoint_state": "ABSENT",
                "source_evidence": ["official:checkpoint:fixture"],
            }
        ]
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.symbol == "SRICHAMUND"
    assert row.final_state == "UNRESOLVED_EXTERNAL_ERA_CHECKPOINT_DISCREPANCY"
    assert row.join_readiness is JoinReadiness.UNRESOLVED_IDENTITY
    assert row.event_date is None
    assert not row.parity_should_hold
    assert row.source_evidence == ("official:checkpoint:fixture",)

    decision = readiness_decision((), (), rows)
    assert decision.state is FoundationReadiness.NOT_READY_FOR_HTR_010B
    assert decision.blockers == ("1 unexplained 2026 discrepancies",)
