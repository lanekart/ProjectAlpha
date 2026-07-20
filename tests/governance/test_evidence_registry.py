from __future__ import annotations

from datetime import date
from decimal import Decimal
import json

import pytest

from alpha.governance import (
    EvidenceCategory,
    EvidenceMaturity,
    EvidenceMetadata,
    EvidenceRegistry,
    EvidenceRegistryError,
    EvidenceStatus,
    GovernancePolicy,
    GovernanceVerdict,
    build_registry_summary,
    export_registry_csv,
    export_registry_json,
    render_registry_summary,
)


def _metadata(
    evidence_id: str = "trend_20dma",
    *,
    maturity: EvidenceMaturity = EvidenceMaturity.REPLAY_VERIFIED,
    status: EvidenceStatus = EvidenceStatus.ACTIVE,
    replay_verified: bool = True,
    minimum_sample_size: int = 100,
    current_sample_size: int = 250,
    precision: Decimal | None = Decimal("0.63"),
    last_validation: date | None = None,
) -> EvidenceMetadata:
    return EvidenceMetadata(
        evidence_id=evidence_id,
        display_name="20-day trend",
        provider="TrendEngine",
        category=EvidenceCategory.TREND,
        version="1.0",
        owner="alpha",
        maturity=maturity,
        status=status,
        replay_verified=replay_verified,
        minimum_sample_size=minimum_sample_size,
        current_sample_size=current_sample_size,
        precision=precision,
        lift=Decimal("0.08"),
        calibration_error=Decimal("0.04"),
        applicable_regimes=("bull", "neutral"),
        dependencies=("daily_ohlcv",),
        outputs=("bullish", "bearish"),
        last_validation=last_validation,
        last_calibration=date(2026, 7, 20),
        documentation="docs/evidence/trend.md",
    )


def test_metadata_normalizes_identifiers_and_tokens() -> None:
    metadata = _metadata()

    assert metadata.evidence_id == "TREND_20DMA"
    assert metadata.applicable_regimes == ("BULL", "NEUTRAL")
    assert metadata.dependencies == ("DAILY_OHLCV",)
    assert metadata.sample_ready is True


def test_replay_maturity_requires_replay_verification() -> None:
    with pytest.raises(EvidenceRegistryError, match="replay-verified maturity"):
        _metadata(replay_verified=False)


def test_forward_validation_requires_validation_date() -> None:
    with pytest.raises(EvidenceRegistryError, match="requires last_validation"):
        _metadata(maturity=EvidenceMaturity.FORWARD_VALIDATED)


def test_registry_is_idempotent_but_rejects_conflicts() -> None:
    registry = EvidenceRegistry()
    metadata = _metadata()
    registry.register(metadata)
    registry.register(metadata)

    assert registry.all() == (metadata,)

    conflicting = EvidenceMetadata(
        evidence_id="TREND_20DMA",
        display_name="Conflicting trend",
        provider="OtherEngine",
        category=EvidenceCategory.TREND,
        version="2.0",
        owner="alpha",
        maturity=EvidenceMaturity.DETERMINISTIC,
        status=EvidenceStatus.EXPERIMENTAL,
        replay_verified=False,
        minimum_sample_size=0,
        current_sample_size=0,
    )
    with pytest.raises(EvidenceRegistryError, match="conflicting registration"):
        registry.register(conflicting)


def test_governance_policies_are_environment_specific() -> None:
    metadata = _metadata()
    registry = EvidenceRegistry((metadata,))

    research = registry.assess(metadata.evidence_id, GovernancePolicy.research())
    shadow = registry.assess(metadata.evidence_id, GovernancePolicy.shadow())
    production = registry.assess(metadata.evidence_id, GovernancePolicy.production())

    assert research.verdict is GovernanceVerdict.ALLOWED
    assert shadow.verdict is GovernanceVerdict.ALLOWED
    assert production.verdict is GovernanceVerdict.DIAGNOSTIC_ONLY
    assert production.reasons == (
        "maturity REPLAY_VERIFIED is below FORWARD_VALIDATED",
    )


def test_suspended_evidence_is_blocked() -> None:
    metadata = _metadata(status=EvidenceStatus.SUSPENDED)
    assessment = EvidenceRegistry((metadata,)).assess(
        metadata.evidence_id,
        GovernancePolicy.research(),
    )

    assert assessment.verdict is GovernanceVerdict.BLOCKED


def test_sample_shortfall_is_diagnostic_only() -> None:
    metadata = _metadata(current_sample_size=99)
    assessment = EvidenceRegistry((metadata,)).assess(
        metadata.evidence_id,
        GovernancePolicy.shadow(),
    )

    assert assessment.verdict is GovernanceVerdict.DIAGNOSTIC_ONLY
    assert assessment.reasons == ("minimum sample size has not been reached",)


def test_summary_reconciles_registry_quality() -> None:
    entries = (
        _metadata(),
        _metadata(
            "options_flow",
            maturity=EvidenceMaturity.DETERMINISTIC,
            status=EvidenceStatus.EXPERIMENTAL,
            replay_verified=False,
            minimum_sample_size=500,
            current_sample_size=40,
            precision=None,
        ),
    )

    summary = build_registry_summary(entries)

    assert summary.total_entries == 2
    assert summary.sample_ready_count == 1
    assert summary.replay_verified_count == 1
    assert summary.unknown_precision_count == 1
    assert render_registry_summary(summary)[-1] == (
        "Execution Status: NON-EXECUTABLE GOVERNANCE METADATA"
    )


def test_json_and_csv_exports_are_deterministic() -> None:
    entries = (_metadata("volume_expansion"), _metadata())

    json_output = export_registry_json(entries)
    csv_output = export_registry_csv(entries)

    payload = json.loads(json_output)
    assert [item["evidence_id"] for item in payload] == [
        "TREND_20DMA",
        "VOLUME_EXPANSION",
    ]
    assert payload[0]["maturity_name"] == "REPLAY_VERIFIED"
    assert csv_output.splitlines()[1].startswith("TREND_20DMA,")
    assert csv_output.splitlines()[2].startswith("VOLUME_EXPANSION,")


def test_precision_and_calibration_are_bounded() -> None:
    with pytest.raises(EvidenceRegistryError, match="precision"):
        _metadata(precision=Decimal("1.01"))


def test_registry_metadata_cannot_influence_execution() -> None:
    metadata = _metadata()
    values = {
        field: getattr(metadata, field)
        for field in metadata.__dataclass_fields__
    }
    values["production_influence"] = True

    with pytest.raises(EvidenceRegistryError, match="production execution"):
        EvidenceMetadata(**values)
