from __future__ import annotations

from pathlib import Path

ENGINE = Path("alpha/historical_truth/foundation_readiness_engine.py")
TEST = Path("tests/historical_truth/test_foundation_readiness_pre2016_regressions.py")


def main() -> None:
    text = ENGINE.read_text(encoding="utf-8")
    old = '''    for row in rows:
        symbol = str(row["symbol"])
        cause, state, treatment, join, event_date = _DISCREPANCY_RULES[symbol]
        evidence = tuple(row.get("source_evidence", []))
        if symbol == "AMIORG":
            evidence += ("nse_symbol_change_events:AMIORG:ACUTAAS:2025-06-02",)
'''
    new = '''    for row in rows:
        symbol = str(row["symbol"])
        rule = _DISCREPANCY_RULES.get(symbol)
        if rule is None:
            cause = (
                "No governed named discrepancy rule or effective-dated official "
                "evidence resolves this checkpoint difference."
            )
            state = "UNRESOLVED_EXTERNAL_ERA_CHECKPOINT_DISCREPANCY"
            treatment = (
                "Retain the discrepancy, quarantine checkpoint parity, and require "
                "effective-dated official identity evidence before admission."
            )
            join = JoinReadiness.UNRESOLVED_IDENTITY
            event_date = None
        else:
            cause, state, treatment, join, event_date = rule
        evidence = tuple(str(item) for item in row.get("source_evidence", []))
        if symbol == "AMIORG":
            evidence += ("nse_symbol_change_events:AMIORG:ACUTAAS:2025-06-02",)
'''
    if old not in text:
        raise RuntimeError("HTR010A3_DISCREPANCY_RULE_BOUNDARY_MISSING")
    ENGINE.write_text(text.replace(old, new, 1), encoding="utf-8")

    TEST.write_text(
        '''from __future__ import annotations

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
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
