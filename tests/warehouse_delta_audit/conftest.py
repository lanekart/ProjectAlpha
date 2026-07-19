from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from alpha.warehouse_delta_audit.models import (
    AuditStatus,
    CandidateDeltaRecord,
    ConfidenceLevel,
    CorporateActionDeltaRecord,
    DecisionDeltaRecord,
    DecisionSeverity,
    IndicatorDeltaRecord,
    PersonalDecision,
    PriceDeltaRecord,
    PurchaseRecommendation,
    ReplayDeltaRecord,
    SampleProfile,
    SourceLineage,
    ValueAttributionRecord,
    WarehouseDeltaManifest,
    WarehouseDeltaReport,
)


@pytest.fixture
def warehouse_delta_report() -> WarehouseDeltaReport:
    manifest = WarehouseDeltaManifest(
        audit_version="WDA_v1.0",
        baseline_id="ALPHA_BASELINE_v1.0",
        data_platform_id="ALPHA_DATA_PLATFORM_v1.0",
        source_commit="abc123",
        warehouse_version="LEGACY_DATASET/PROVISIONAL",
        comparison_warehouse_version="WAREHOUSE_SAMPLE_V2",
        feature_version="feature-v1",
        candidate_version="candidate-v1",
        policy_version="policy-v1",
        baseline_manifest_hash="baseline-hash",
        data_platform_manifest_hash="platform-hash",
        legacy_warehouse_hash="legacy-hash",
        comparison_source_hash="comparison-hash",
        sample_symbols_hash="sample-hash",
        manifest_hash="manifest-hash",
        source_lineage=SourceLineage.LEGACY_LINEAGE_RAW_SOURCE,
        source_attestation=None,
    )
    sample = SampleProfile(
        requested_symbols=500,
        selected_symbols=("HDFCBANK", "KALYANKJIL", "LT", "PCJEWELLER"),
        mandatory_symbols_present=("HDFCBANK", "KALYANKJIL", "LT", "PCJEWELLER"),
        mandatory_symbols_missing=("RELIANCE", "TCS", "TATASTEEL"),
        start=date(2020, 1, 1),
        end=date(2025, 12, 31),
        sessions=1480,
        source_files=1480,
        liquidity_high=2,
        liquidity_medium=1,
        liquidity_low=1,
        sector_coverage="UNKNOWN",
        market_cap_coverage="UNAVAILABLE",
    )
    return WarehouseDeltaReport(
        manifest=manifest,
        sample=sample,
        status=AuditStatus.COMPLETE_SAME_LINEAGE_CONTROL,
        price_deltas=(
            PriceDeltaRecord(
                symbol="LT",
                matched_observations=1480,
                exact_observations=1480,
                small_difference_observations=0,
                large_difference_observations=0,
                missing_from_comparison=0,
                missing_from_legacy=0,
                legacy_duplicate_observations=0,
                comparison_duplicate_observations=0,
                open_changed=0,
                high_changed=0,
                low_changed=0,
                close_changed=0,
                volume_changed=0,
                maximum_close_relative_delta=Decimal("0"),
                maximum_volume_relative_delta=Decimal("0"),
            ),
        ),
        indicator_deltas=(
            IndicatorDeltaRecord(
                symbol="LT",
                indicator="EMA20",
                compared_observations=1461,
                identical_observations=1461,
                minor_changes=0,
                material_changes=0,
                signal_changes=0,
                maximum_relative_delta=Decimal("0"),
            ),
        ),
        candidate_deltas=(
            CandidateDeltaRecord("LT", 3, 0, 0, 0, 0, Decimal("0"), Decimal("0")),
        ),
        decision_deltas=(
            DecisionDeltaRecord(
                observed_on=date(2025, 1, 2),
                symbol="LT",
                legacy_score=Decimal("80"),
                comparison_score=Decimal("80"),
                legacy_approved=True,
                comparison_approved=True,
                legacy_reason="APPROVED",
                comparison_reason="APPROVED",
                severity=DecisionSeverity.NO_CHANGE,
                explanation="Decision is unchanged.",
            ),
        ),
        replay_deltas=(
            ReplayDeltaRecord(
                metric="expectancy",
                legacy_value=Decimal("1.2"),
                comparison_value=Decimal("1.2"),
                delta=Decimal("0"),
                unit="percent",
                interpretation="expectancy is unchanged.",
            ),
        ),
        corporate_action_deltas=(
            CorporateActionDeltaRecord(
                event_type="SPLIT",
                legacy_events=None,
                comparison_events=None,
                indicator_changing_events=None,
                replay_changing_events=None,
                status="UNKNOWN_SOURCE_UNAVAILABLE",
                explanation="No independent sample.",
            ),
        ),
        value_attribution=(
            ValueAttributionRecord(
                source="corrected_prices",
                observable_changes=0,
                decision_changes=0,
                replay_effect="NO_CHANGE",
                confidence=ConfidenceLevel.HIGH,
                explanation="No observed change.",
            ),
        ),
        purchase_recommendation=PurchaseRecommendation.PURCHASE_NOT_JUSTIFIED,
        personal_decision=PersonalDecision.NOT_YET,
        estimated_alpha_improvement=("Independent Alpha improvement remains UNKNOWN."),
        confidence=ConfidenceLevel.LOW,
        recommendation_reason="Independent vendor uplift has not been measured.",
        limitations=("No independent corporate-action sample.",),
    )
