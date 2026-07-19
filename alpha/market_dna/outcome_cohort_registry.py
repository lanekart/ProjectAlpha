from __future__ import annotations

from alpha.market_dna.models import OutcomeCohortDefinition

COHORT_REGISTRY_VERSION = "market-dna-cohorts-v1"
DEFAULT_COST_PROFILE = "strategy-lab-execution-v1-30bps"


class OutcomeCohortRegistry:
    """Versioned, explicit outcome definitions. Predicates are never implicit."""

    def __init__(self) -> None:
        self._definitions = _definitions()
        self._by_id = {item.cohort_id: item for item in self._definitions}

    @property
    def definitions(self) -> tuple[OutcomeCohortDefinition, ...]:
        return self._definitions

    def require(self, cohort_id: str) -> OutcomeCohortDefinition:
        normalized = cohort_id.strip().upper().replace("-", "_")
        definition = self._by_id.get(normalized)
        if definition is None:
            raise ValueError(f"unknown outcome cohort: {cohort_id}")
        return definition


def _definitions() -> tuple[OutcomeCohortDefinition, ...]:
    items = (
        ("STRONG_WINNERS", "Strong winners", "net_return_pct >= 20"),
        (
            "MODERATE_WINNERS",
            "Moderate winners",
            "10 <= net_return_pct < 20",
        ),
        ("SMALL_WINNERS", "Small winners", "1 < net_return_pct < 10"),
        ("FLAT_OUTCOMES", "Flat outcomes", "-1 <= net_return_pct <= 1"),
        ("SMALL_LOSERS", "Small losers", "-10 < net_return_pct < -1"),
        ("LARGE_LOSERS", "Large losers", "-25 < net_return_pct <= -10"),
        (
            "CATASTROPHIC_LOSERS",
            "Catastrophic losers",
            "net_return_pct <= -25",
        ),
        ("HIGH_MFE_OPPORTUNITIES", "High-MFE opportunities", "mfe_pct >= 15"),
        ("HIGH_MAE_FAILURES", "High-MAE failures", "mae_pct <= -15"),
        (
            "PROFITABLE_REJECTED",
            "Profitable rejected candidates",
            "raw_approved == false and net_return_pct > 1",
        ),
        (
            "APPROVED_PROFITABLE",
            "Approved profitable candidates",
            "raw_approved == true and net_return_pct > 1",
        ),
        (
            "APPROVED_UNPROFITABLE",
            "Approved unprofitable candidates",
            "raw_approved == true and net_return_pct <= 0",
        ),
        (
            "MISSED_ENTRY_WINNERS",
            "Missed-entry winner proxies",
            "entry_missed_proxy == true and net_return_pct > 1",
        ),
        (
            "STOP_HIT_THEN_RECOVERED",
            "Stop-hit then recovered proxies",
            "stop_touched == true and net_return_pct > 1",
        ),
        (
            "TARGET_ACHIEVED",
            "Target-achieved proxies",
            "target_1_touched == true",
        ),
        (
            "TIME_EXPIRED",
            "Time-expired proxies",
            "target_1_touched == false and stop_touched == false",
        ),
    )
    return tuple(
        OutcomeCohortDefinition(
            cohort_id=cohort_id,
            title=title,
            predicate=predicate,
            horizon="PRIMARY_RECORDED_HORIZON",
            cost_profile_id=DEFAULT_COST_PROFILE,
            version=COHORT_REGISTRY_VERSION,
            description=(
                "Deterministic reconstructed research cohort; target, stop, missed "
                "entry, and expiry states are explicitly labelled proxies when the "
                "source row lacks authoritative event ordering."
            ),
        )
        for cohort_id, title, predicate in items
    )


__all__ = ["COHORT_REGISTRY_VERSION", "OutcomeCohortRegistry"]
