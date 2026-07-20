from __future__ import annotations

from decimal import Decimal
import json

import pytest

from alpha.decision_lifecycle import LifecycleState
from alpha.decision_science import (
    DecisionStabilityEngine,
    StabilityBand,
    StabilityScenario,
    export_stability_json,
    render_stability_assessment,
)


def _scenario(
    scenario_id: str,
    state: LifecycleState,
    *,
    weight: str = "1",
    critical: bool = False,
) -> StabilityScenario:
    return StabilityScenario(
        scenario_id=scenario_id,
        description=f"Perturbation for {scenario_id}",
        resulting_state=state,
        weight=Decimal(weight),
        critical=critical,
    )


def test_all_unchanged_scenarios_are_very_stable() -> None:
    assessment = DecisionStabilityEngine().assess(
        baseline_state=LifecycleState.READY,
        scenarios=(
            _scenario("PRICE_MINUS_1", LifecycleState.READY),
            _scenario("VOLUME_MINUS_5", LifecycleState.READY),
            _scenario("REGIME_MINUS_10", LifecycleState.READY),
        ),
    )

    assert assessment.score == 100
    assert assessment.band is StabilityBand.VERY_STABLE
    assert assessment.changed_scenarios == 0


def test_weighted_flips_reduce_stability_score() -> None:
    assessment = DecisionStabilityEngine().assess(
        baseline_state=LifecycleState.READY,
        scenarios=(
            _scenario("PRICE_MINUS_1", LifecycleState.READY, weight="1"),
            _scenario("VOLUME_MINUS_5", LifecycleState.WATCHLIST, weight="2"),
            _scenario("REGIME_MINUS_10", LifecycleState.READY, weight="1"),
        ),
    )

    assert assessment.score == 50
    assert assessment.band is StabilityBand.MODERATE
    assert assessment.changed_scenario_ids == ("VOLUME_MINUS_5",)


def test_critical_flip_is_reported_separately() -> None:
    assessment = DecisionStabilityEngine().assess(
        baseline_state=LifecycleState.HOLD,
        scenarios=(
            _scenario("STOP_MINUS_ATR", LifecycleState.EXIT, critical=True),
            _scenario("RS_MINUS_5", LifecycleState.HOLD),
        ),
    )

    assert assessment.critical_flips == ("STOP_MINUS_ATR",)
    assert assessment.changed_scenarios == 1


def test_duplicate_scenario_ids_fail_closed() -> None:
    engine = DecisionStabilityEngine()
    scenarios = (
        _scenario("DUPLICATE", LifecycleState.READY),
        _scenario("duplicate", LifecycleState.WATCHLIST),
    )

    with pytest.raises(ValueError, match="ids must be unique"):
        engine.assess(baseline_state=LifecycleState.READY, scenarios=scenarios)


def test_empty_scenario_set_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one"):
        DecisionStabilityEngine().assess(
            baseline_state=LifecycleState.READY,
            scenarios=(),
        )


def test_scenario_validation_rejects_invalid_weight() -> None:
    with pytest.raises(ValueError, match="weight must be positive"):
        _scenario("BAD_WEIGHT", LifecycleState.READY, weight="0")


def test_rendering_and_json_are_deterministic() -> None:
    assessment = DecisionStabilityEngine().assess(
        baseline_state=LifecycleState.READY,
        scenarios=(
            _scenario("PRICE_MINUS_1", LifecycleState.READY),
            _scenario(
                "REGIME_MINUS_10",
                LifecycleState.WATCHLIST,
                critical=True,
            ),
        ),
    )

    assert render_stability_assessment(assessment) == (
        "Decision Stability Assessment",
        "Baseline State: READY",
        "Stability Score: 50/100",
        "Stability Band: MODERATE",
        "Scenarios Tested: 2",
        "Decision Flips: 1",
        "Changed Scenarios: REGIME_MINUS_10",
        "Critical Flips: REGIME_MINUS_10",
        "Execution Status: NON-EXECUTABLE DECISION DIAGNOSTIC",
    )
    payload = json.loads(export_stability_json(assessment))
    assert payload["baseline_state"] == "READY"
    assert payload["band"] == "MODERATE"
    assert payload["production_influence"] is False


def test_assessment_cannot_claim_production_influence() -> None:
    assessment = DecisionStabilityEngine().assess(
        baseline_state=LifecycleState.READY,
        scenarios=(_scenario("BASE", LifecycleState.READY),),
    )
    payload = assessment.to_dict()

    assert payload["production_influence"] is False
