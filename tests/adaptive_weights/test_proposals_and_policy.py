from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from itertools import combinations
from types import MappingProxyType

import pytest

from alpha.adaptive_weights.hierarchy import ConditionalWeightResolver
from alpha.adaptive_weights.models import (
    AlphaComponent,
    CandidatePolicyState,
    ComponentDecisionState,
    ComponentWeight,
    ConditionalWeightPolicy,
    ConditionalWeightSet,
    ConfidenceAssessment,
    ContributionConfidence,
    ContributionEstimate,
    EvidenceQuality,
    HierarchyLevel,
    OverlapFinding,
    RedundancyClass,
    StabilityAssessment,
    StabilityClass,
    WeightLayer,
    WeightSet,
    canonical_weight_set,
)
from alpha.adaptive_weights.policy_registry import (
    CandidateWeightPolicyFactory,
    CandidateWeightPolicyRegistry,
)
from alpha.adaptive_weights.proposal_engine import AdaptiveWeightProposalEngine


def test_canonical_weight_baseline_is_exact_and_immutable() -> None:
    canonical = canonical_weight_set()
    assert tuple((item.component, item.weight) for item in canonical.weights) == (
        (AlphaComponent.PRICE_STRUCTURE, Decimal("20")),
        (AlphaComponent.VOLUME, Decimal("17")),
        (AlphaComponent.TREND, Decimal("15")),
        (AlphaComponent.RELATIVE_STRENGTH, Decimal("13")),
        (AlphaComponent.RETRACEMENT, Decimal("10")),
        (AlphaComponent.CANDLESTICK, Decimal("8")),
        (AlphaComponent.BREAKOUT_SETUP, Decimal("7")),
        (AlphaComponent.MARKET_REGIME, Decimal("5")),
        (AlphaComponent.SECTOR, Decimal("3")),
        (AlphaComponent.RISK_VOLATILITY, Decimal("2")),
    )
    with pytest.raises((AttributeError, TypeError)):
        canonical.weights[0].weight = Decimal("99")  # type: ignore[misc]


def test_positive_and_negative_payoff_change_weights_within_caps() -> None:
    contributions = _contributions(
        {
            AlphaComponent.PRICE_STRUCTURE: Decimal("0.8"),
            AlphaComponent.VOLUME: Decimal("-0.8"),
        }
    )
    proposal = AdaptiveWeightProposalEngine().propose(
        contributions,
        _stabilities(),
        _confidences(),
        _unique_overlaps(),
        evidence_count=80,
    )
    assert proposal.proposed.for_component(AlphaComponent.PRICE_STRUCTURE) > Decimal(
        "20"
    )
    assert proposal.proposed.for_component(AlphaComponent.VOLUME) < Decimal("17")
    assert sum(
        (item.weight for item in proposal.proposed.weights), start=Decimal("0")
    ) == pytest.approx(Decimal("100"))
    for decision in proposal.decisions:
        assert abs(decision.relative_change) <= Decimal("0.20") + Decimal("0.00001")
        assert decision.proposed_weight <= Decimal("30")


def test_weak_evidence_is_fully_shrunk_to_canonical() -> None:
    proposal = AdaptiveWeightProposalEngine().propose(
        _contributions({AlphaComponent.PRICE_STRUCTURE: Decimal("1")}),
        _stabilities(StabilityClass.INSUFFICIENT_EVIDENCE),
        _confidences(ContributionConfidence.INSUFFICIENT, holdout=0, forward=0),
        (),
        evidence_count=3,
    )
    assert proposal.proposed.weights == canonical_weight_set().weights
    assert all(
        item.decision is ComponentDecisionState.INSUFFICIENT_EVIDENCE
        for item in proposal.decisions
    )


def test_negative_holdout_blocks_an_apparent_development_increase() -> None:
    contribution = _contributions(
        {AlphaComponent.PRICE_STRUCTURE: Decimal("0.9")},
        holdout={AlphaComponent.PRICE_STRUCTURE: Decimal("-0.4")},
    )
    proposal = AdaptiveWeightProposalEngine().propose(
        contribution,
        _stabilities(),
        _confidences(),
        (),
        evidence_count=80,
    )
    price = next(
        item
        for item in proposal.decisions
        if item.component is AlphaComponent.PRICE_STRUCTURE
    )
    assert price.proposed_weight <= price.current_weight
    assert "negative holdout contribution blocks increase" in price.blocking_reasons


def test_same_source_and_high_overlap_penalize_duplicate_component() -> None:
    contributions = _contributions({AlphaComponent.PRICE_STRUCTURE: Decimal("0.8")})
    unique = AdaptiveWeightProposalEngine().propose(
        contributions,
        _stabilities(),
        _confidences(),
        (),
        evidence_count=80,
    )
    duplicate = AdaptiveWeightProposalEngine().propose(
        contributions,
        _stabilities(),
        _confidences(),
        (
            OverlapFinding(
                component_a=AlphaComponent.PRICE_STRUCTURE,
                component_b=AlphaComponent.TREND,
                sample_size=80,
                score_correlation=Decimal("0.95"),
                candidate_overlap=Decimal("0.9"),
                approval_overlap=Decimal("0.9"),
                mutual_information=Decimal("0.7"),
                shared_source_lineage=True,
                setup_redundancy=Decimal("0.95"),
                regime_redundancy=Decimal("0.95"),
                redundancy_class=RedundancyClass.SAME_SOURCE,
                recommended_action="do not count as independent",
            ),
        ),
        evidence_count=80,
    )
    assert duplicate.proposed.for_component(
        AlphaComponent.PRICE_STRUCTURE
    ) < unique.proposed.for_component(AlphaComponent.PRICE_STRUCTURE)


def test_conditional_hierarchy_and_insufficient_sample_fallback() -> None:
    universal = _adjusted_weight_set("UNIVERSAL", Decimal("1"))
    setup = ConditionalWeightSet(
        setup="BREAKOUT",
        regime=None,
        horizon=None,
        sample_size=30,
        weights=_adjusted_weight_set("SETUP", Decimal("2")),
        evidence_quality=EvidenceQuality.SUFFICIENT,
    )
    exact = ConditionalWeightSet(
        setup="BREAKOUT",
        regime="BULL",
        horizon=None,
        sample_size=5,
        weights=_adjusted_weight_set("EXACT", Decimal("3")),
        evidence_quality=EvidenceQuality.WEAK,
    )
    policy = ConditionalWeightPolicy(
        universal=universal,
        conditionals=(exact, setup),
        minimum_sample_size=20,
    )
    resolved = ConditionalWeightResolver().resolve(
        policy, setup="BREAKOUT", regime="BULL", horizon="20D"
    )
    assert resolved.hierarchy_level is HierarchyLevel.SETUP
    assert resolved.weights.policy_id == "SETUP"
    fallback = ConditionalWeightResolver().resolve(
        ConditionalWeightPolicy(
            universal=None,
            conditionals=(exact,),
            minimum_sample_size=20,
        ),
        setup="BREAKOUT",
        regime="BULL",
        horizon="20D",
    )
    assert fallback.hierarchy_level is HierarchyLevel.CANONICAL


def test_policy_manifest_and_registry_are_deterministic_and_immutable(tmp_path) -> None:
    proposal = AdaptiveWeightProposalEngine().propose(
        _contributions({AlphaComponent.PRICE_STRUCTURE: Decimal("0.5")}),
        _stabilities(),
        _confidences(),
        (),
        evidence_count=80,
    )
    factory = CandidateWeightPolicyFactory()
    args = {
        "policy_id": "ALPHA_WEIGHT_RESEARCH_0001",
        "parent_policy": "ALPHA_CANONICAL",
        "conditional_weights": (),
        "evidence_window": "2020-01-01..2024-12-31",
        "dataset_version": "DATA-V1",
        "created_at": datetime(2025, 1, 1, tzinfo=UTC),
    }
    first = factory.create(proposal, **args)
    second = factory.create(proposal, **args)
    assert first.manifest_hash == second.manifest_hash
    assert first.state is CandidatePolicyState.DRAFT
    registry = CandidateWeightPolicyRegistry(tmp_path / "policies.json")
    assert registry.register(first) is True
    assert registry.register(second) is False
    with pytest.raises(ValueError, match="immutable"):
        registry.register(replace(first, manifest_hash="different"))


def _contributions(
    overrides: dict[AlphaComponent, Decimal],
    *,
    holdout: dict[AlphaComponent, Decimal] | None = None,
) -> tuple[ContributionEstimate, ...]:
    return tuple(
        ContributionEstimate(
            component=component,
            standalone_contribution=overrides.get(component, Decimal("0")),
            marginal_contribution=overrides.get(component, Decimal("0")),
            conditional_contribution=overrides.get(component, Decimal("0")),
            leave_one_out_contribution=overrides.get(component, Decimal("0")),
            permutation_importance=abs(overrides.get(component, Decimal("0"))),
            confidence_interval_low=overrides.get(component, Decimal("0"))
            - Decimal("0.1"),
            confidence_interval_high=overrides.get(component, Decimal("0"))
            + Decimal("0.1"),
            sample_size=80,
            completed_partition_count=4,
            partition_contributions=MappingProxyType(
                {
                    "DEVELOPMENT": overrides.get(component, Decimal("0")),
                    "VALIDATION": overrides.get(component, Decimal("0")),
                    "HOLDOUT": (holdout or {}).get(
                        component, overrides.get(component, Decimal("0"))
                    ),
                    "FORWARD_OBSERVED": overrides.get(component, Decimal("0")),
                }
            ),
            method_label="fixture transparent methods",
        )
        for component in AlphaComponent
    )


def _stabilities(
    classification: StabilityClass = StabilityClass.ROBUST,
) -> tuple[StabilityAssessment, ...]:
    return tuple(
        StabilityAssessment(
            component=component,
            sample_size=80,
            directional_stability=Decimal("1"),
            magnitude_stability=Decimal("0.9"),
            rank_stability=Decimal("0.9"),
            sector_stability=Decimal("0.8"),
            setup_stability=Decimal("0.8"),
            regime_stability=Decimal("0.8"),
            horizon_stability=Decimal("0.8"),
            era_stability=Decimal("0.8"),
            holdout_consistency=True,
            forward_consistency=True,
            classification=classification,
            evidence_notes=(),
        )
        for component in AlphaComponent
    )


def _confidences(
    confidence: ContributionConfidence = ContributionConfidence.STRONG,
    *,
    holdout: int = 20,
    forward: int = 20,
) -> tuple[ConfidenceAssessment, ...]:
    return tuple(
        ConfidenceAssessment(
            component=component,
            confidence=confidence,
            sample_size=80,
            holdout_sample_size=holdout,
            forward_sample_size=forward,
            uncertainty_penalty=Decimal("0.1"),
            reasons=(),
        )
        for component in AlphaComponent
    )


def _unique_overlaps() -> tuple[OverlapFinding, ...]:
    return tuple(
        OverlapFinding(
            component_a=component_a,
            component_b=component_b,
            sample_size=80,
            score_correlation=Decimal("0.1"),
            candidate_overlap=Decimal("0.2"),
            approval_overlap=Decimal("0.2"),
            mutual_information=Decimal("0.01"),
            shared_source_lineage=False,
            setup_redundancy=Decimal("0.2"),
            regime_redundancy=Decimal("0.2"),
            redundancy_class=RedundancyClass.UNIQUE,
            recommended_action="retain independent contribution",
        )
        for component_a, component_b in combinations(AlphaComponent, 2)
    )


def _adjusted_weight_set(policy_id: str, shift: Decimal) -> WeightSet:
    canonical = canonical_weight_set()
    return WeightSet(
        layer=WeightLayer.RESEARCH_PROPOSED_WEIGHTS,
        policy_id=policy_id,
        weights=tuple(
            ComponentWeight(
                component=item.component,
                weight=(
                    item.weight + shift
                    if item.component is AlphaComponent.PRICE_STRUCTURE
                    else item.weight - shift
                    if item.component is AlphaComponent.VOLUME
                    else item.weight
                ),
            )
            for item in canonical.weights
        ),
    )
