from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from alpha.data_platform import (
    CanonicalQueryEngine,
    DataQuery,
    QuerySubject,
    TimeTravelEngine,
    default_dataset_registry,
    default_warehouse_versions,
)
from alpha.data_platform.models import CanonicalObservation


def test_query_engine_enforces_knowledge_time(
    canonical_observation: CanonicalObservation,
) -> None:
    registry = default_dataset_registry()
    engine = CanonicalQueryEngine(registry, (canonical_observation,))
    pending = engine.execute(
        DataQuery(
            dataset_id="nse-equity-bhavcopy",
            subject=QuerySubject.OHLCV,
            market_start=date(2020, 1, 2),
            market_end=date(2020, 1, 2),
            knowledge_as_of=datetime(2020, 1, 2, 17, tzinfo=UTC),
            symbols=("AAA",),
        )
    )
    visible = engine.execute(
        DataQuery(
            dataset_id="nse-equity-bhavcopy",
            subject=QuerySubject.OHLCV,
            market_start=date(2020, 1, 2),
            market_end=date(2020, 1, 2),
            knowledge_as_of=datetime(2020, 1, 2, 19, tzinfo=UTC),
            symbols=("AAA",),
        )
    )
    assert pending.records == ()
    assert visible.records == (canonical_observation,)
    assert visible.plan.point_in_time_enforced


def test_time_travel_reports_unknown_and_blocks_late_observation(
    canonical_observation: CanonicalObservation,
) -> None:
    late = replace(
        canonical_observation,
        observation_id="late",
        observation_key="NSE:SEC-2:2020-01-02",
        known_at=datetime(2020, 1, 3, tzinfo=UTC),
    )
    registry = default_dataset_registry()
    engine = CanonicalQueryEngine(registry, (canonical_observation, late))
    snapshot = TimeTravelEngine(registry, engine).snapshot(
        market_date=date(2020, 1, 2),
        knowledge_as_of=datetime(2020, 1, 2, 20, tzinfo=UTC),
        dataset_ids=("nse-equity-bhavcopy", "nse-corporate-actions"),
    )
    assert snapshot.records == (canonical_observation,)
    assert snapshot.unknown_datasets == ("nse-corporate-actions",)


def test_time_travel_uses_effective_interval_for_security_state(
    canonical_observation: CanonicalObservation,
) -> None:
    identity = replace(
        canonical_observation,
        observation_id="identity",
        dataset_id="nse-security-master",
        observation_key="SEC-1:2010-01-01",
        observed_on=date(2010, 1, 1),
        effective_from=date(2010, 1, 1),
        effective_to=None,
        known_at=datetime(2010, 1, 1, tzinfo=UTC),
        fields={"security_id": "SEC-1", "symbol": "AAA"},
    )
    registry = default_dataset_registry()
    snapshot = TimeTravelEngine(
        registry,
        CanonicalQueryEngine(registry, (identity,)),
    ).snapshot(
        market_date=date(2020, 1, 2),
        knowledge_as_of=datetime(2020, 1, 2, tzinfo=UTC),
        dataset_ids=("nse-security-master",),
    )
    assert snapshot.records == (identity,)
    assert snapshot.unknown_datasets == ()


def test_warehouse_versioning_requires_frozen_release() -> None:
    versions = default_warehouse_versions()
    with pytest.raises(ValueError, match="frozen warehouse release"):
        versions.bind_replay(
            warehouse_version="WAREHOUSE_V2_CANONICAL_DRAFT",
            feature_version="features-v1",
            policy_version="policy-v1",
            decision_version="decision-v1",
            dataset_versions={},
        )
    binding = versions.bind_replay(
        warehouse_version="WAREHOUSE_V1_LEGACY",
        feature_version="features-v1",
        policy_version="policy-v1",
        decision_version="decision-v1",
        dataset_versions={"legacy-dataset": "PROVISIONAL"},
    )
    assert binding.binding_hash == replace(binding).binding_hash
    assert len(versions.releases) == 3
