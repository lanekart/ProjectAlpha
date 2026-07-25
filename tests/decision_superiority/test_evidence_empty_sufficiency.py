from __future__ import annotations

from alpha.decision_superiority.statistics import build_evidence_strength


def test_empty_evidence_is_insufficient_even_when_minimum_is_zero() -> None:
    evidence = build_evidence_strength(
        sample_count=0,
        resolved_count=0,
        minimum_required=0,
    )

    assert evidence.sufficient is False
