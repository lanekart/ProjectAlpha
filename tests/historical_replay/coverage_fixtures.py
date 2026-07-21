"""Shared deterministic replay coverage evidence fixtures for HTR-006 tests."""

from __future__ import annotations

from datetime import date

from alpha.historical_replay.coverage_readiness import (
    HistoricalReplayCoverageEvidence,
)


def coverage_evidence(
    *,
    from_date: date,
    to_date: date,
    warmup_sessions: int = 200,
    outcome_sessions: int = 60,
    eligible_security_ids: tuple[str, ...] = ("SEC-1",),
) -> HistoricalReplayCoverageEvidence:
    """Return deterministic governed coverage evidence for tests."""

    return HistoricalReplayCoverageEvidence(
        from_date=from_date,
        to_date=to_date,
        observed_warmup_sessions=warmup_sessions,
        observed_outcome_sessions=outcome_sessions,
        eligible_security_ids=tuple(sorted(set(eligible_security_ids))),
        source_table="test.coverage",
    )


__all__ = ["coverage_evidence"]
