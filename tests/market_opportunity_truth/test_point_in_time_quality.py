from __future__ import annotations

from dataclasses import fields
from datetime import date
from decimal import Decimal

from alpha.market_opportunity_truth.models import (
    OpportunityQuality,
    RawOpportunityOnset,
)
from alpha.market_opportunity_truth.onset_detection import PointInTimeOnsetEngine


def _onset(
    *, future_flag: str = "false", turnover: str = "150000000"
) -> RawOpportunityOnset:
    return RawOpportunityOnset(
        opportunity_id="onset-1",
        symbol="TEST",
        onset_date=date(2024, 1, 2),
        onset_sequence=100,
        entry=Decimal("100"),
        reference_level=Decimal("99"),
        initial_stop=Decimal("90"),
        reasonable_target=Decimal("130"),
        prospective_rr=Decimal("3"),
        source_confidence=Decimal("0.9"),
        point_in_time_inputs=(
            ("atr_14", "2"),
            ("average_turnover_20", turnover),
            ("base_width", "0.10"),
            ("ema_20", "98"),
            ("ema_50", "95"),
            ("extension_pct", "0.02"),
            ("future_return_used_for_detection", future_flag),
            ("volume_ratio_20", "2.2"),
        ),
        dataset_version="LEGACY_DATASET",
        evidence_hash="evidence-hash",
    )


def test_point_in_time_onset_receives_institutional_quality() -> None:
    seed = PointInTimeOnsetEngine().classify((_onset(),))[0]
    assert seed.tradability.tradable is True
    assert seed.quality.quality is OpportunityQuality.A_PLUS
    assert seed.quality.score == Decimal("100.00")
    assert seed.cluster_id == "TIGHT_GEOMETRY"


def test_future_certification_failure_is_not_tradable() -> None:
    seed = PointInTimeOnsetEngine().classify((_onset(future_flag="true"),))[0]
    assert seed.tradability.tradable is False
    assert seed.quality.quality is OpportunityQuality.NOT_TRADABLE
    assert "POINT_IN_TIME_CERTIFICATION_FAILED" in seed.tradability.reasons


def test_quality_hash_has_no_future_outcome_dependency() -> None:
    seed = PointInTimeOnsetEngine().classify((_onset(),))[0]
    field_names = {item.name for item in fields(RawOpportunityOnset)}
    assert "future_return" not in field_names
    assert "mfe" not in field_names
    assert "target_before_stop" not in field_names
    assert seed.point_in_time_decision_hash == (
        PointInTimeOnsetEngine().classify((_onset(),))[0].point_in_time_decision_hash
    )
