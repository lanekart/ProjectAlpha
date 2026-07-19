from __future__ import annotations

from collections import Counter

from alpha.canonical_integrity_audit.models import (
    CoverageClassification,
    EconomicProblem,
    OpportunityCoverageRecord,
    ParityDivergenceSummary,
    RuntimeFailureRecord,
)


def economic_attribution(
    *,
    coverage: tuple[OpportunityCoverageRecord, ...],
    divergences: tuple[ParityDivergenceSummary, ...],
    runtime_failures: tuple[RuntimeFailureRecord, ...],
) -> tuple[EconomicProblem, tuple[EconomicProblem, ...]]:
    counts: Counter[EconomicProblem] = Counter()
    for item in coverage:
        if item.classification is CoverageClassification.MISSED:
            counts[EconomicProblem.SETUP_RECOGNITION_PROBLEM] += 1
        elif item.classification is CoverageClassification.REJECTED:
            blocker = (item.primary_blocker or "").upper()
            if "TIMING" in blocker or "TRIGGER" in blocker or "LATE" in blocker:
                counts[EconomicProblem.ENTRY_TIMING_PROBLEM] += 1
            elif "TRADE" in blocker or "REWARD" in blocker or "RISK" in blocker:
                counts[EconomicProblem.TRADE_PLAN_PROBLEM] += 1
            elif "VERDICT" in blocker or "SETUP" in blocker:
                counts[EconomicProblem.SIGNAL_QUALITY_PROBLEM] += 1
            else:
                counts[EconomicProblem.APPROVAL_POLICY_PROBLEM] += 1
        elif item.classification is CoverageClassification.RUNTIME_BLOCKED:
            counts[EconomicProblem.RUNTIME_INTEGRITY_PROBLEM] += 1
        elif item.classification in {
            CoverageClassification.DATA_BLOCKED,
            CoverageClassification.UNSCORABLE,
        }:
            counts[EconomicProblem.DATA_QUALITY_PROBLEM] += 1
    if runtime_failures:
        counts[EconomicProblem.RUNTIME_INTEGRITY_PROBLEM] += len(
            {item.trading_date for item in runtime_failures}
        )
    if divergences:
        counts[EconomicProblem.PINE_PARITY_PROBLEM] += sum(
            item.count for item in divergences
        )
    if not counts:
        return EconomicProblem.DATA_QUALITY_PROBLEM, ()
    ordered = tuple(sorted(counts, key=lambda item: (-counts[item], item.value)))
    return ordered[0], ordered[1:3]


__all__ = ["economic_attribution"]
