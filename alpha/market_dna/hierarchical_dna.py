from __future__ import annotations

from decimal import Decimal

from alpha.market_dna.models import FeatureFinding, FeatureSnapshot, HierarchicalResult


class HierarchicalDNA:
    """Summarise universal, setup, and horizon scopes without invalid context labels."""

    def summarize(
        self,
        *,
        snapshots: tuple[FeatureSnapshot, ...],
        findings: tuple[FeatureFinding, ...],
        minimum_sample: int = 30,
    ) -> tuple[HierarchicalResult, ...]:
        results = [
            _result(
                "UNIVERSAL",
                len(snapshots),
                tuple(item for item in findings if item.scope == "UNIVERSAL"),
                None,
                minimum_sample,
            )
        ]
        for setup in sorted({item.setup for item in snapshots}):
            population = sum(item.setup == setup for item in snapshots)
            scoped = tuple(item for item in findings if item.scope == f"SETUP:{setup}")
            results.append(
                _result(
                    f"SETUP:{setup}",
                    population,
                    scoped,
                    False,
                    minimum_sample,
                )
            )
        for horizon in sorted({item.horizon for item in snapshots}):
            population = sum(item.horizon == horizon for item in snapshots)
            scoped = tuple(
                item for item in findings if item.scope == f"HORIZON:{horizon}"
            )
            results.append(
                _result(
                    f"HORIZON:{horizon}",
                    population,
                    scoped,
                    False,
                    minimum_sample,
                )
            )
        results.append(
            HierarchicalResult(
                scope="SECTOR_AND_REGIME",
                population=0,
                strongest_finding_id=None,
                strongest_enrichment_ratio=None,
                generalises_outside_subgroup=None,
                limitations=(
                    "Sector is unavailable point-in-time and market regime is "
                    "quarantined.",
                ),
            )
        )
        return tuple(results)


def _result(
    scope: str,
    population: int,
    findings: tuple[FeatureFinding, ...],
    default_generalisation: bool | None,
    minimum_sample: int,
) -> HierarchicalResult:
    eligible = tuple(
        item
        for item in findings
        if item.cohort_match_count >= minimum_sample
        and item.baseline_match_count >= minimum_sample
        and item.adjusted_p_value is not None
        and item.adjusted_p_value <= Decimal("0.05")
    )
    strongest = max(
        eligible,
        key=lambda item: (
            abs((item.enrichment_ratio or Decimal("1")) - Decimal("1")),
            item.finding_id,
        ),
        default=None,
    )
    return HierarchicalResult(
        scope=scope,
        population=population,
        strongest_finding_id=None if strongest is None else strongest.finding_id,
        strongest_enrichment_ratio=(
            None if strongest is None else strongest.enrichment_ratio
        ),
        generalises_outside_subgroup=default_generalisation,
        limitations=(
            "Subgroup findings require an explicit outside-subgroup comparison."
            if scope != "UNIVERSAL"
            else "Universal scope still reflects reconstructed evidence.",
        ),
    )


__all__ = ["HierarchicalDNA"]
