from __future__ import annotations

import json

import pytest

from alpha.decision_superiority.gate_isolation_frozen_inputs import (
    FrozenInputSection,
)
from alpha.decision_superiority.gate_isolation_source_lineage_producer import (
    SOURCE_LINEAGE_PRODUCER_VERSION,
    SourceLineageCaptureInput,
    SourceLineageSnapshotProducer,
)


def _input() -> SourceLineageCaptureInput:
    return SourceLineageCaptureInput(
        artifact_hashes={
            "analysis": "sha-analysis",
            "history": "sha-history",
        },
        provider_versions={
            "market_data": "provider-v1",
        },
        source_paths={
            "analysis": "artifacts/analysis.csv",
            "history": "warehouse/history.duckdb",
        },
        dataset_versions={
            "candles": "dataset-v1",
        },
        observed_on="2026-07-26",
    )


def test_source_lineage_producer_is_deterministic() -> None:
    first = SourceLineageSnapshotProducer().produce(_input())
    second = SourceLineageSnapshotProducer().produce(_input())

    assert first == second
    assert first.section is FrozenInputSection.SOURCE_LINEAGE
    assert first.source_version == SOURCE_LINEAGE_PRODUCER_VERSION
    payload = json.loads(first.payload_json)
    assert payload["artifact_hashes"]["analysis"] == "sha-analysis"
    assert payload["provider_versions"]["market_data"] == "provider-v1"


def test_source_lineage_payload_is_canonically_ordered() -> None:
    capture_input = SourceLineageCaptureInput(
        artifact_hashes={"z": "2", "a": "1"},
        provider_versions={"z": "2", "a": "1"},
        source_paths={"z": "z-path", "a": "a-path"},
        dataset_versions={"z": "2", "a": "1"},
        observed_on="2026-07-26",
    )

    snapshot = SourceLineageSnapshotProducer().produce(capture_input)

    assert snapshot.payload_json.index('"a"') < snapshot.payload_json.index('"z"')


def test_missing_lineage_component_fails_closed() -> None:
    with pytest.raises(ValueError, match="artifact_hashes cannot be empty"):
        SourceLineageCaptureInput(
            artifact_hashes={},
            provider_versions={"market_data": "provider-v1"},
            source_paths={"analysis": "artifacts/analysis.csv"},
            dataset_versions={"candles": "dataset-v1"},
            observed_on="2026-07-26",
        )


def test_blank_lineage_value_fails_closed() -> None:
    with pytest.raises(
        ValueError,
        match="provider_versions keys and values cannot be empty",
    ):
        SourceLineageCaptureInput(
            artifact_hashes={"analysis": "sha-analysis"},
            provider_versions={"market_data": ""},
            source_paths={"analysis": "artifacts/analysis.csv"},
            dataset_versions={"candles": "dataset-v1"},
            observed_on="2026-07-26",
        )
