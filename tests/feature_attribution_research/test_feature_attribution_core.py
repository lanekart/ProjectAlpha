from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from alpha.candidate_generation_research.models import (
    OpportunityFamily,
    TradableOpportunityOnset,
)
from alpha.feature_attribution_research.case_studies import FeatureCaseStudyEngine
from alpha.feature_attribution_research.chronological_validation import (
    OrthogonalEdgeAudit,
)
from alpha.feature_attribution_research.conditional import (
    ConditionalAttributionEngine,
)
from alpha.feature_attribution_research.feature_quality import FeatureQualityEngine
from alpha.feature_attribution_research.feature_registry import FeatureRegistry
from alpha.feature_attribution_research.interactions import FeatureInteractionEngine
from alpha.feature_attribution_research.leakage import FeatureLeakageAudit
from alpha.feature_attribution_research.models import (
    AttributionDirection,
    AttributionResult,
    DirectionalExpectation,
    EvidencePartition,
    FeatureDefinition,
    FeatureGroup,
    FeatureQualityFlag,
    FeatureSnapshot,
    FeatureStabilityScore,
    MissingnessPolicy,
    OutcomeRecord,
    ResearchCohort,
    ResearchPopulationRecord,
    StabilityClassification,
    TransactionCostPolicy,
)
from alpha.feature_attribution_research.negative_feature_audit import (
    NegativeFeatureAudit,
)
from alpha.feature_attribution_research.outcome_labels import (
    OutcomeLabelEngine,
    preregistered_outcome_definitions,
)
from alpha.feature_attribution_research.point_in_time_builder import (
    PointInTimeFeatureBuilder,
    apply_development_transforms,
)
from alpha.feature_attribution_research.population import (
    _LinkedEvidence,
    _population_record,
    deduplicate_linked_onsets,
)
from alpha.feature_attribution_research.redundancy import FeatureRedundancyEngine
from alpha.feature_attribution_research.univariate import UnivariateAttributionEngine


def test_population_deduplication_and_preassociation_cohorts() -> None:
    inputs = json.dumps({"feature_hash": "same"})
    rows = (
        {
            "onset_id": "b",
            "symbol": "ABC",
            "onset_date": "2024-01-01",
            "event_family": "BREAKOUT_FROM_BASE",
            "point_in_time_inputs": inputs,
        },
        {
            "onset_id": "a",
            "symbol": "abc",
            "onset_date": "2024-01-01",
            "event_family": "BREAKOUT_FROM_BASE",
            "point_in_time_inputs": inputs,
        },
    )

    deduplicated = deduplicate_linked_onsets(rows)
    unlinked = _population_record(
        onset=_tradable_onset(),
        linked=None,
        candidates={},
        partition=EvidencePartition.DEVELOPMENT,
    )
    linked = _population_record(
        onset=_tradable_onset(),
        linked=_LinkedEvidence(
            event_ids=("event-1",),
            funnel_rows=(
                {
                    "coverage": "CANONICAL_SETUP_MISSED",
                    "canonical_candidate_id": "",
                },
            ),
        ),
        candidates={},
        partition=EvidencePartition.DEVELOPMENT,
    )

    assert len(deduplicated) == 1
    assert deduplicated[0]["onset_id"] == "a"
    assert ResearchCohort.ALL_MARKET_OPPORTUNITIES in unlinked.cohorts
    assert ResearchCohort.ALL_TRADABLE_ONSETS in unlinked.cohorts
    assert ResearchCohort.LINKED_HINDSIGHT not in unlinked.cohorts
    assert ResearchCohort.LINKED_HINDSIGHT in linked.cohorts
    assert ResearchCohort.CANONICAL_MISSES in linked.cohorts


def test_outcomes_are_preregistered_once_and_stop_wins_same_bar() -> None:
    definitions = preregistered_outcome_definitions()
    assert len({item.outcome_id for item in definitions}) == len(definitions)
    primary = tuple(item for item in definitions if item.primary)
    assert tuple(item.outcome_id for item in primary) == ("TARGET_BEFORE_STOP",)
    assert {20, 60, 120}.issubset(
        {item.horizon for item in definitions if item.outcome_id.startswith("MFE_")}
    )

    population = (_population("tie", date(2024, 1, 1)),)
    future = _future_frame("tie", date(2024, 1, 1), stop_and_target_first=True)
    outcome = OutcomeLabelEngine().evaluate(
        store=_FutureStore(future),  # type: ignore[arg-type]
        population=population,
        transaction_cost_policy=TransactionCostPolicy(
            policy_id="cost-v-test", round_trip_rate=Decimal("0.003")
        ),
    )[0]

    assert outcome.exit_reason == "STOP"
    assert outcome.stop_hit is True
    assert outcome.target_before_stop is False
    assert outcome.plan_target_hit is False
    assert outcome.transaction_cost_policy_id == "cost-v-test"


def test_point_in_time_features_ignore_post_onset_shock_and_preserve_missing() -> None:
    frame = _history_frame(222)
    onset_date = frame.iloc[210]["trade_date"]
    population = (_population("onset", onset_date),)
    truncated = frame.loc[frame["trade_date"] <= onset_date].copy()

    full_snapshot = PointInTimeFeatureBuilder().build_frame(
        frame=frame, population=population
    )[0]
    truncated_snapshot = PointInTimeFeatureBuilder().build_frame(
        frame=truncated, population=population
    )[0]

    assert full_snapshot.values == truncated_snapshot.values
    assert (
        full_snapshot.feature_snapshot_hash == truncated_snapshot.feature_snapshot_hash
    )
    assert full_snapshot.source_max_date == onset_date
    assert full_snapshot.value("relative_strength_60d") is None
    leakage = FeatureLeakageAudit().audit(
        definitions=FeatureRegistry().definitions,
        snapshots=(full_snapshot,),
    )
    assert not any(item.bars_after_onset for item in leakage)
    reward_risk = next(
        item for item in leakage if item.feature_id == "prospective_reward_risk"
    )
    assert reward_risk.outcome_definition_coupled is True
    assert reward_risk.status == "CAUTION_OUTCOME_DEFINITION_COUPLED"


def test_development_only_percentiles_are_unchanged_by_holdout_values() -> None:
    baseline = (
        _snapshot("d1", 1.0, EvidencePartition.DEVELOPMENT, "turnover_20d"),
        _snapshot("d2", 2.0, EvidencePartition.DEVELOPMENT, "turnover_20d"),
        _snapshot("h1", 10.0, EvidencePartition.HOLDOUT, "turnover_20d"),
    )
    changed = baseline + (
        _snapshot("h2", 1_000_000.0, EvidencePartition.HOLDOUT, "turnover_20d"),
    )

    first = apply_development_transforms(baseline)
    second = apply_development_transforms(changed)

    first_development = {
        item.onset_id: item.value("turnover_percentile")
        for item in first
        if item.partition is EvidencePartition.DEVELOPMENT
    }
    second_development = {
        item.onset_id: item.value("turnover_percentile")
        for item in second
        if item.partition is EvidencePartition.DEVELOPMENT
    }
    assert first_development == second_development == {"d1": 0.5, "d2": 1.0}


def test_registry_is_immutable_and_quality_flags_real_defects() -> None:
    definition = _definition("constant")
    snapshots = tuple(
        _snapshot(
            f"row-{index}",
            1.0,
            EvidencePartition.DEVELOPMENT,
            "constant",
            symbol="ONLY",
        )
        for index in range(30)
    )
    quality = FeatureQualityEngine().audit(
        definitions=(definition,), snapshots=snapshots
    )[0]

    assert FeatureQualityFlag.ZERO_VARIANCE in quality.flags
    assert FeatureQualityFlag.SYMBOL_CONCENTRATION in quality.flags
    registry = FeatureRegistry()
    with pytest.raises(FrozenInstanceError):
        registry.definitions[0].feature_id = "changed"  # type: ignore[misc]


def test_quality_flags_era_concentration() -> None:
    definition = _definition("era_feature")
    snapshots = []
    for index in range(200):
        if index < 20:
            year, value = 2015, 0.0
        elif index >= 180:
            year, value = 2025, 100.0
        else:
            year, value = 2020, float(49 + index % 3)
        snapshots.append(
            _snapshot(
                f"era-{index}",
                value,
                EvidencePartition.DEVELOPMENT,
                "era_feature",
                observed_on=date(year, 1, 1) + timedelta(days=index % 20),
                symbol=f"S{index % 20}",
            )
        )

    quality = FeatureQualityEngine().audit(
        definitions=(definition,), snapshots=tuple(snapshots)
    )[0]

    assert FeatureQualityFlag.ERA_DRIFT in quality.flags


def test_univariate_attribution_detects_positive_and_inverse_features() -> None:
    definitions = (_definition("positive"), _definition("inverse"))
    snapshots = []
    outcomes = []
    for index in range(90):
        partition = tuple(EvidencePartition)[min(index // 30, 2)]
        label = index % 30 >= 15
        snapshots.append(
            FeatureSnapshot(
                onset_id=f"u-{index}",
                symbol=f"S{index % 9}",
                onset_date=date(2020 + index // 30, 1, 1) + timedelta(days=index % 30),
                partition=partition,
                values=(
                    ("positive", float(index % 30)),
                    ("inverse", -float(index % 30)),
                ),
                source_max_date=date(2020 + index // 30, 1, 1)
                + timedelta(days=index % 30),
                feature_snapshot_hash=f"hash-{index}",
            )
        )
        outcomes.append(_outcome(f"u-{index}", label))

    rows = UnivariateAttributionEngine().analyze(
        definitions=definitions,
        snapshots=tuple(snapshots),
        outcomes=tuple(outcomes),
        outcome_ids=("TARGET_BEFORE_STOP",),
        minimum_support=10,
        bootstrap_samples=30,
    )
    positive = next(
        item
        for item in rows
        if item.feature_id == "positive" and item.partition is None
    )
    inverse = next(
        item for item in rows if item.feature_id == "inverse" and item.partition is None
    )

    assert positive.auc == Decimal("1.0")
    assert positive.standardized_effect_size is not None
    assert positive.monotonicity_score is not None
    assert positive.monotonicity_score > Decimal("0.8")
    assert positive.direction is AttributionDirection.POSITIVE
    assert inverse.direction is AttributionDirection.NEGATIVE
    assert NegativeFeatureAudit().analyze(rows)[0].feature_id == "inverse"


def test_conditional_engine_flags_simpsons_paradox() -> None:
    definition = _definition("simpson")
    snapshots = []
    population = []
    outcomes = []
    index = 0
    for family, offset, winning_values in (
        ("HIGH_BASE", 6, {6, 7, 8, 9}),
        ("LOW_BASE", 1, {1}),
    ):
        for value in range(offset, offset + 5):
            for _ in range(10):
                onset_id = f"s-{index}"
                observed_on = date(2020, 1, 1) + timedelta(days=index)
                snapshots.append(
                    _snapshot(
                        onset_id,
                        float(value),
                        EvidencePartition.DEVELOPMENT,
                        "simpson",
                        observed_on=observed_on,
                        symbol=f"S{index % 20}",
                    )
                )
                population.append(
                    _population(onset_id, observed_on, event_family=family)
                )
                outcomes.append(_outcome(onset_id, value in winning_values))
                index += 1

    results = ConditionalAttributionEngine().analyze(
        definitions=(definition,),
        population=tuple(population),
        snapshots=tuple(snapshots),
        outcomes=tuple(outcomes),
        minimum_support=20,
    )
    event_family = tuple(
        item for item in results if item.context_name == "event_family"
    )

    assert len(event_family) == 2
    assert all(item.simpson_paradox for item in event_family)
    assert all(item.direction is AttributionDirection.NEGATIVE for item in event_family)


def test_redundancy_and_interaction_support_are_fail_closed() -> None:
    definitions = (
        replace(_definition("first"), source_lineage=("same",)),
        replace(_definition("second"), source_lineage=("same",)),
    )
    snapshots = []
    outcomes = []
    for index in range(36):
        partition = tuple(EvidencePartition)[index // 12]
        values = (
            ("first", float(index)),
            ("second", float(index)),
            ("price_regression_slope_60d", float(index)),
            ("relative_volume_20d", float(index)),
        )
        observed_on = date(2020, 1, 1) + timedelta(days=index)
        snapshots.append(
            FeatureSnapshot(
                onset_id=f"r-{index}",
                symbol=f"S{index % 8}",
                onset_date=observed_on,
                partition=partition,
                values=values,
                source_max_date=observed_on,
                feature_snapshot_hash=f"r-hash-{index}",
            )
        )
        outcomes.append(_outcome(f"r-{index}", index % 2 == 0))

    redundancy = FeatureRedundancyEngine().analyze(
        definitions=definitions,
        snapshots=tuple(snapshots),
        outcomes=tuple(outcomes),
        minimum_support=10,
    )
    interactions = FeatureInteractionEngine().analyze(
        snapshots=tuple(snapshots),
        outcomes=tuple(outcomes),
        minimum_support=20,
    )

    assert redundancy[0].classification.value == "SAME_SOURCE_DUPLICATE"
    assert interactions
    assert not any(item.accepted_for_research for item in interactions)


def test_outcome_definition_coupled_features_are_not_orthogonal_probes() -> None:
    definitions = (
        FeatureRegistry().get("ema20_slope"),
        FeatureRegistry().get("prospective_reward_risk"),
    )
    snapshots = []
    outcomes = []
    for index in range(360):
        partition = tuple(EvidencePartition)[index // 120]
        observed_on = date(2020 + index // 120, 1, 1) + timedelta(days=index % 120)
        snapshots.append(
            FeatureSnapshot(
                onset_id=f"orthogonal-{index}",
                symbol=f"S{index % 20}",
                onset_date=observed_on,
                partition=partition,
                values=(
                    ("ema20_slope", float(index % 120)),
                    ("prospective_reward_risk", float(index % 10)),
                ),
                source_max_date=observed_on,
                feature_snapshot_hash=f"orthogonal-hash-{index}",
            )
        )
        outcomes.append(_outcome(f"orthogonal-{index}", index % 120 >= 60))

    results = OrthogonalEdgeAudit().analyze(
        definitions=definitions,
        snapshots=tuple(snapshots),
        outcomes=tuple(outcomes),
        univariate=(
            _attribution(
                "ema20_slope",
                AttributionDirection.POSITIVE,
                partition=EvidencePartition.DEVELOPMENT,
            ),
            _attribution(
                "prospective_reward_risk",
                AttributionDirection.NEGATIVE,
                partition=EvidencePartition.DEVELOPMENT,
            ),
        ),
        redundancy=(),
        minimum_support=100,
    )

    assert "ema20_slope" in {item.feature_id for item in results}
    assert "prospective_reward_risk" not in {item.feature_id for item in results}


def test_kalyan_and_pcjeweller_case_studies_are_point_in_time_explicit() -> None:
    definition = _definition("feature")
    snapshots = (
        _snapshot(
            "k", 0.9, EvidencePartition.DEVELOPMENT, "feature", symbol="KALYANKJIL"
        ),
        _snapshot(
            "p", 0.1, EvidencePartition.DEVELOPMENT, "feature", symbol="PCJEWELLER"
        ),
    )
    population = (
        _population("k", snapshots[0].onset_date, symbol="KALYANKJIL"),
        _population("p", snapshots[1].onset_date, symbol="PCJEWELLER"),
    )
    outcomes = (_outcome("k", True), _outcome("p", False))
    attribution = (_attribution("feature", AttributionDirection.POSITIVE),)
    stability = (
        FeatureStabilityScore(
            feature_id="feature",
            direction_stability=Decimal("1"),
            support_stability=Decimal("1"),
            era_stability=Decimal("1"),
            regime_stability=None,
            sector_stability=None,
            liquidity_stability=Decimal("1"),
            overall_stability=Decimal("1"),
            classification=StabilityClassification.STABLE_POSITIVE,
            unavailable_dimensions=("regime", "sector"),
        ),
    )

    cases = FeatureCaseStudyEngine().build(
        definitions=(definition,),
        population=population,
        snapshots=snapshots,
        outcomes=outcomes,
        univariate=attribution,
        stability=stability,
        leakage=(),
        rankings=(),
        symbols=("KALYANKJIL", "PCJEWELLER"),
    )

    assert tuple(item.symbol for item in cases) == ("KALYANKJIL", "PCJEWELLER")
    assert all(item.differentiation_available_point_in_time for item in cases)
    assert all("Point-in-time differentiation" in item.explanation for item in cases)


class _FutureStore:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def future_bars(self, candidates: pd.DataFrame, *, limit: int) -> pd.DataFrame:
        del candidates
        return self.frame.head(limit).copy()


def _tradable_onset() -> TradableOpportunityOnset:
    return TradableOpportunityOnset(
        onset_id="onset-1",
        forward_event_id=None,
        symbol="ABC",
        onset_date=date(2024, 1, 1),
        onset_sequence=100,
        event_family=OpportunityFamily.BREAKOUT_FROM_BASE,
        setup_evidence=("point-in-time",),
        entry_trigger=Decimal("100"),
        reference_level=Decimal("99"),
        prospective_stop=Decimal("95"),
        prospective_target=Decimal("110"),
        prospective_rr=Decimal("2"),
        extension_state="ACCEPTABLE",
        liquidity_state="PASS",
        confidence=Decimal("0.7"),
        point_in_time_inputs={"feature_hash": "same"},
        dataset_version="TEST",
    )


def _population(
    onset_id: str,
    observed_on: date,
    *,
    symbol: str = "ABC",
    event_family: str = "BREAKOUT_FROM_BASE",
) -> ResearchPopulationRecord:
    return ResearchPopulationRecord(
        onset_id=onset_id,
        source_onset_id=onset_id,
        event_ids=(),
        symbol=symbol,
        onset_date=observed_on,
        onset_sequence=100,
        event_family=event_family,
        candidate_status="NO_HINDSIGHT_EVENT_LINK",
        canonical_setup=None,
        canonical_score=None,
        canonical_verdict=None,
        canonical_gate_result=None,
        entry_trigger=Decimal("100"),
        reference_level=Decimal("99"),
        prospective_stop=Decimal("95"),
        prospective_target=Decimal("110"),
        prospective_rr=Decimal("2"),
        confidence=Decimal("0.7"),
        point_in_time_inputs=(
            ("extension_pct", "0.02"),
            ("volume_ratio_20", "1.5"),
        ),
        cohorts=(ResearchCohort.ALL_MARKET_OPPORTUNITIES,),
        partition=EvidencePartition.DEVELOPMENT,
        dataset_version="TEST",
        feature_snapshot_hash=f"population-{onset_id}",
    )


def _snapshot(
    onset_id: str,
    value: float,
    partition: EvidencePartition,
    feature_id: str,
    *,
    observed_on: date = date(2024, 1, 1),
    symbol: str = "ABC",
) -> FeatureSnapshot:
    values = ((feature_id, value),)
    if feature_id == "turnover_20d":
        values = (
            ("turnover_20d", value),
            ("turnover_percentile", None),
            ("atr_percent", None),
            ("atr_percentile", None),
            ("bollinger_bandwidth", None),
            ("bandwidth_percentile", None),
        )
    return FeatureSnapshot(
        onset_id=onset_id,
        symbol=symbol,
        onset_date=observed_on,
        partition=partition,
        values=values,
        source_max_date=observed_on,
        feature_snapshot_hash=f"snapshot-{onset_id}",
    )


def _definition(feature_id: str) -> FeatureDefinition:
    return FeatureDefinition(
        feature_id=feature_id,
        feature_name=feature_id.title(),
        feature_group=FeatureGroup.PRICE_STRUCTURE,
        definition="Synthetic point-in-time feature.",
        unit="ratio",
        lookback=20,
        directional_expectation=DirectionalExpectation.POSITIVE,
        source_module="tests",
        source_lineage=(feature_id,),
        point_in_time_safe=True,
        missingness_policy=MissingnessPolicy.PRESERVE_MISSING,
        canonical_component=None,
        version="test-v1",
    )


def _outcome(onset_id: str, winner: bool) -> OutcomeRecord:
    return OutcomeRecord(
        onset_id=onset_id,
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        plan_target_price=Decimal("110"),
        net_return_20d=Decimal("0.1") if winner else Decimal("-0.05"),
        net_return_60d=Decimal("0.2") if winner else Decimal("-0.1"),
        net_return_120d=Decimal("0.3") if winner else Decimal("-0.1"),
        mfe_20d=Decimal("0.1"),
        mfe_60d=Decimal("0.2"),
        mfe_120d=Decimal("0.3"),
        mae_20d=Decimal("-0.02"),
        mae_60d=Decimal("-0.04"),
        mae_120d=Decimal("-0.05"),
        realized_r=Decimal("2") if winner else Decimal("-1"),
        target_1_hit=winner,
        target_2_hit=winner,
        plan_target_hit=winner,
        stop_hit=not winner,
        target_before_stop=winner,
        positive_after_costs_20d=winner,
        positive_after_costs_60d=winner,
        positive_after_costs_120d=winner,
        positive_2r_before_stop=winner,
        high_quality_winner=winner,
        exit_reason="PLAN_TARGET" if winner else "STOP",
        first_event_date=date(2024, 1, 2),
        available_forward_bars=120,
        transaction_cost_policy_id="test-cost",
    )


def _attribution(
    feature_id: str,
    direction: AttributionDirection,
    *,
    partition: EvidencePartition | None = None,
) -> AttributionResult:
    auc = (
        Decimal("0.8") if direction is AttributionDirection.POSITIVE else Decimal("0.2")
    )
    return AttributionResult(
        feature_id=feature_id,
        outcome_id="TARGET_BEFORE_STOP",
        partition=partition,
        horizon=120,
        sample_count=100,
        missing_count=0,
        winner_median=Decimal("0.8"),
        loser_median=Decimal("0.2"),
        median_difference=Decimal("0.6"),
        standardized_effect_size=Decimal("1"),
        rank_biserial_correlation=Decimal("0.6"),
        auc=auc,
        monotonicity_score=Decimal("1"),
        bootstrap_low=auc - Decimal("0.05"),
        bootstrap_high=auc + Decimal("0.05"),
        direction=direction,
        deciles=(),
    )


def _history_frame(sessions: int) -> pd.DataFrame:
    rows = []
    start = date(2020, 1, 1)
    for index in range(sessions):
        close = 100 + index * 0.2
        if index == sessions - 1:
            close = 10_000
        rows.append(
            {
                "symbol": "ABC",
                "trade_date": start + timedelta(days=index),
                "open": close - 0.2,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 100_000 + index * 100,
            }
        )
    return pd.DataFrame(rows)


def _future_frame(
    onset_id: str, observed_on: date, *, stop_and_target_first: bool
) -> pd.DataFrame:
    rows = []
    for index in range(1, 121):
        high = 111.0 if index == 1 and stop_and_target_first else 101.0
        low = 94.0 if index == 1 and stop_and_target_first else 99.0
        rows.append(
            {
                "candidate_id": onset_id,
                "symbol": "ABC",
                "trade_date": observed_on + timedelta(days=index),
                "open": 100.0,
                "high": high,
                "low": low,
                "close": 100.0,
                "volume": 100_000,
                "sector": None,
                "exchange": "NSE",
            }
        )
    return pd.DataFrame(rows)
