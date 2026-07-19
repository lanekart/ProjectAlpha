from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from alpha.candidate_learning.models import CandidateDecisionRecord
from alpha.market_intelligence.snapshots import (
    ClassifierInputRecord,
    MarketStateFallbackReason,
    MarketStateInputCompleteness,
    MarketStateSnapshot,
)
from alpha.provenance import (
    AnalyticalReleaseManifest,
    AnalyticalReleaseManifestEntry,
    ComponentCompatibility,
    DecisionProvenanceRepository,
    EvidenceReliability,
    HistoricalBackfillVersionEligibility,
    HistoricalEraAssignmentStatus,
    HistoricalEvidenceItem,
    HistoricalEvidenceType,
    HistoricalVersionRecoveryStatus,
    ManifestBackfillEligibility,
    ReleaseReviewStatus,
    VersionDriftConclusion,
    WorkingTreeState,
    build_historical_evidence_inventory,
    build_historical_manifest_audit,
    build_version_drift_report,
    build_version_lineage_audit,
    capture_current_provenance,
    compatibility_for,
    current_component_registry,
    current_market_classifier_fingerprint,
    render_historical_era_assignments,
    render_historical_manifest_coverage,
    render_manifest_validation,
)


def test_component_registry_fingerprint_is_stable() -> None:
    first = current_component_registry()
    second = current_component_registry()

    assert first == second
    assert len({component.name for component in first}) == len(first)
    assert current_market_classifier_fingerprint()


def test_provenance_repository_idempotent_insert(tmp_path) -> None:
    repository = DecisionProvenanceRepository(tmp_path / "provenance.json")
    provenance = capture_current_provenance(
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        runtime_command="intelligence",
        runtime_mode="LIVE",
        source="test",
    )

    first = repository.upsert(provenance)
    second = repository.upsert(provenance)

    assert first.inserted is True
    assert second.inserted is False
    assert repository.get(provenance.provenance_id) == provenance
    assert len(repository.load_all()) == 1


def test_runtime_without_git_metadata_is_allowed() -> None:
    provenance = capture_current_provenance(
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        runtime_command=None,
        runtime_mode=None,
        source="test",
    )

    assert provenance.provenance_id
    assert provenance.working_tree_state in {
        WorkingTreeState.CLEAN,
        WorkingTreeState.DIRTY,
        WorkingTreeState.UNAVAILABLE,
    }


def test_compatibility_classifications() -> None:
    fingerprint = current_market_classifier_fingerprint()

    assert (
        compatibility_for(
            persisted_version="v1",
            current_version="v1",
            persisted_fingerprint=None,
            current_fingerprint=fingerprint,
        )
        is ComponentCompatibility.EXACT_VERSION_MATCH
    )
    assert (
        compatibility_for(
            persisted_version="v0",
            current_version="v1",
            persisted_fingerprint=fingerprint,
            current_fingerprint=fingerprint,
        )
        is ComponentCompatibility.EXACT_FINGERPRINT_MATCH
    )
    assert (
        compatibility_for(
            persisted_version=None,
            current_version="v1",
            persisted_fingerprint=None,
            current_fingerprint=fingerprint,
        )
        is ComponentCompatibility.VERSION_UNKNOWN
    )


def test_version_lineage_marks_legacy_unknown_without_guessing() -> None:
    record = _candidate(classifier_version=None, provenance_id=None)
    report = build_version_lineage_audit(
        records=(record,),
        snapshots=(),
        provenances=(),
    )

    assert report.unknown_version_coverage == 1
    assert (
        report.recoveries[0].recovery_status
        is HistoricalVersionRecoveryStatus.VERSION_UNKNOWN
    )
    assert (
        report.eligibility[0].eligibility
        is HistoricalBackfillVersionEligibility.BLOCKED_VERSION_UNKNOWN
    )


def test_version_lineage_uses_persisted_classifier_version() -> None:
    record = _candidate(
        classifier_version="market-intelligence-composite-v1",
        provenance_id=None,
    )
    report = build_version_lineage_audit(
        records=(record,),
        snapshots=(),
        provenances=(),
    )

    assert report.exact_version_coverage == 1
    assert (
        report.recoveries[0].recovery_status
        is HistoricalVersionRecoveryStatus.PERSISTED_EXACT
    )


def test_version_lineage_uses_decision_provenance_fingerprint() -> None:
    provenance = capture_current_provenance(
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        runtime_command="run",
        runtime_mode="LIVE",
        source="test",
    )
    record = _candidate(
        classifier_version=None,
        provenance_id=provenance.provenance_id,
    )
    report = build_version_lineage_audit(
        records=(record,),
        snapshots=(),
        provenances=(provenance,),
    )

    assert report.fingerprint_coverage == 1
    assert (
        report.recoveries[0].recovery_status
        is HistoricalVersionRecoveryStatus.PERSISTED_FINGERPRINT
    )
    assert (
        report.eligibility[0].eligibility
        is HistoricalBackfillVersionEligibility.ELIGIBLE_FINGERPRINT_MATCH
    )


def test_version_drift_unknown_without_persisted_provenance() -> None:
    report = build_version_drift_report(records=(), snapshots=(), provenances=())

    assert report.conclusion is VersionDriftConclusion.UNKNOWN_VERSION_DRIFT


def test_candidate_provenance_round_trip() -> None:
    record = _candidate(
        classifier_version="market-intelligence-composite-v1",
        provenance_id="abc123",
    )

    restored = CandidateDecisionRecord.from_dict(record.as_dict())

    assert restored.decision_provenance_id == "abc123"


def test_snapshot_provenance_round_trip() -> None:
    snapshot = _snapshot(provenance_id="prov1")

    restored = MarketStateSnapshot.from_dict(snapshot.as_dict())

    assert restored.provenance_id == "prov1"
    assert restored.market_classifier_fingerprint == "fingerprint1"
    assert restored.benchmark_builder_version == "benchmark-state-builder-v1"


def test_historical_evidence_inventory_classifies_sources() -> None:
    provenance = capture_current_provenance(
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        runtime_command="run",
        runtime_mode="LIVE",
        source="test",
    )
    record = _candidate(classifier_version=None, provenance_id=provenance.provenance_id)

    evidence = build_historical_evidence_inventory(
        records=(record,),
        snapshots=(_snapshot(provenance_id=provenance.provenance_id),),
        provenances=(provenance,),
    )
    by_id = {item.evidence_id: item for item in evidence}

    assert (
        by_id["decision_provenance_ledger"].reliability
        is EvidenceReliability.AUTHORITATIVE
    )
    assert by_id["decision_provenance_ledger"].supports_exact_match is True
    assert by_id["candidate_output_signature"].reliability is EvidenceReliability.WEAK
    assert by_id["candidate_output_signature"].supports_exact_match is False
    assert (
        by_id["deployment_history_absent"].reliability is EvidenceReliability.UNUSABLE
    )


def test_historical_manifest_assigns_persisted_provenance_exact() -> None:
    provenance = capture_current_provenance(
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        runtime_command="run",
        runtime_mode="LIVE",
        source="test",
    )
    record = _candidate(classifier_version=None, provenance_id=provenance.provenance_id)

    report = build_historical_manifest_audit(
        records=(record,),
        snapshots=(),
        provenances=(provenance,),
    )

    assert report.persisted_exact_records == 1
    assert (
        report.assignments[0].assignment_status
        is HistoricalEraAssignmentStatus.PERSISTED_EXACT_PROVENANCE
    )
    assert (
        report.eligibility[0].eligibility
        is ManifestBackfillEligibility.ELIGIBLE_EXACT_FINGERPRINT
    )


def test_historical_manifest_keeps_output_signature_diagnostic_only() -> None:
    record = _candidate(classifier_version=None, provenance_id=None)

    report = build_historical_manifest_audit(
        records=(record,),
        snapshots=(),
        provenances=(),
    )

    assert report.diagnostic_only_records == 1
    assert (
        report.assignments[0].assignment_status
        is HistoricalEraAssignmentStatus.OUTPUT_SIGNATURE_ONLY
    )
    assert (
        report.eligibility[0].eligibility
        is ManifestBackfillEligibility.BLOCKED_OUTPUT_SIGNATURE_ONLY
    )
    assert "output signature" in str(report.assignments[0].blocking_reason)


def test_manifest_validation_rejects_duplicate_entries() -> None:
    evidence = (
        HistoricalEvidenceItem(
            evidence_id="e1",
            evidence_type=HistoricalEvidenceType.DECISION_PROVENANCE_LEDGER,
            source="test",
            source_location="test",
            effective_date_or_range=None,
            component_affected="classifier",
            observed_version="v1",
            observed_behavior="persisted runtime evidence",
            reliability=EvidenceReliability.AUTHORITATIVE,
            record_level_applicability=True,
            release_level_applicability=True,
            supports_exact_match=True,
            supports_semantic_compatibility=True,
            limitations="test",
        ),
    )
    entry = _manifest_entry("era-1")

    try:
        AnalyticalReleaseManifest(
            entries=(entry, entry),
            evidence=evidence,
            reviewed_at=datetime(2026, 1, 1, tzinfo=UTC),
            reviewer="test",
        )
    except ValueError as exc:
        assert str(exc) == "duplicate manifest entry id"
    else:
        raise AssertionError("Expected duplicate manifest entry to fail")


def test_manifest_validation_rejects_missing_evidence_reference() -> None:
    try:
        AnalyticalReleaseManifest(
            entries=(_manifest_entry("era-1"),),
            evidence=(),
            reviewed_at=datetime(2026, 1, 1, tzinfo=UTC),
            reviewer="test",
        )
    except ValueError as exc:
        assert "references missing evidence" in str(exc)
    else:
        raise AssertionError("Expected missing manifest evidence to fail")


def test_manifest_renderers_include_coverage_and_validation() -> None:
    record = _candidate(classifier_version=None, provenance_id=None)
    report = build_historical_manifest_audit(
        records=(record,),
        snapshots=(),
        provenances=(),
    )

    coverage = "\n".join(render_historical_manifest_coverage(report))
    validation = "\n".join(render_manifest_validation(report.manifest))
    grouped = "\n".join(
        render_historical_era_assignments(report.assignments, group_by="status")
    )

    assert "Historical Manifest Coverage" in coverage
    assert "Explicitly Prohibited Next Action" in coverage
    assert "Status: VALID" in validation
    assert "OUTPUT_SIGNATURE_ONLY: 1" in grouped


def _candidate(
    *,
    classifier_version: str | None,
    provenance_id: str | None,
) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        candidate_id="candidate-1",
        run_id="run-1",
        evaluation_date=date(2026, 1, 1),
        symbol="TEST",
        final_verdict="BUY",
        capital_action="BUY",
        approved_for_deployment=True,
        rejection_reasons=(),
        setup_type="Momentum",
        market_regime="BULLISH",
        long_trade_permission=True,
        strategy_score=Decimal("80"),
        confidence="HIGH",
        data_quality="COMPLETE",
        entry_zone_low=Decimal("100"),
        entry_zone_high=Decimal("102"),
        confirmation_entry=Decimal("103"),
        risk_stop=Decimal("95"),
        target_1=Decimal("110"),
        target_2=Decimal("115"),
        target_3=Decimal("120"),
        trailing_stop_plan="2 ATR",
        expected_holding_period="20 days",
        indicators_active=("price",),
        indicator_scores={"price": "80"},
        evidence_layers=("price",),
        explanation="test",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        classifier_version=classifier_version,
        decision_provenance_id=provenance_id,
    )


def _snapshot(*, provenance_id: str) -> MarketStateSnapshot:
    return MarketStateSnapshot(
        snapshot_id="snapshot-1",
        market_date=date(2026, 1, 1),
        as_of_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        source_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        benchmark_symbol="NIFTYBEES",
        benchmark_source="local_daily_prices",
        benchmark_close=Decimal("100"),
        benchmark_return_1d=Decimal("0.01"),
        benchmark_return_5d=Decimal("0.02"),
        benchmark_return_20d=Decimal("0.03"),
        benchmark_dma_20=Decimal("99"),
        benchmark_dma_50=Decimal("98"),
        benchmark_dma_200=Decimal("97"),
        benchmark_above_20dma=True,
        benchmark_above_50dma=True,
        benchmark_above_200dma=True,
        benchmark_distance_20dma=Decimal("0.01"),
        benchmark_distance_50dma=Decimal("0.02"),
        benchmark_distance_200dma=Decimal("0.03"),
        benchmark_atr=Decimal("1.5"),
        benchmark_volatility=Decimal("0.02"),
        benchmark_latest_bar_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        benchmark_alignment="SAME_TRADING_DAY",
        benchmark_bars_available=220,
        breadth_advancers=100,
        breadth_decliners=50,
        breadth_unchanged=10,
        breadth_ratio=Decimal("0.6"),
        percent_above_20dma=None,
        percent_above_50dma=None,
        percent_above_200dma=None,
        new_highs=None,
        new_lows=None,
        sector_leader="TEST",
        sector_laggard="TEST2",
        sector_dispersion=Decimal("1"),
        market_trend_score=Decimal("70"),
        breadth_score=Decimal("65"),
        volatility_score=Decimal("60"),
        participation_score=Decimal("55"),
        classifier_regime="BULLISH",
        classifier_confidence=Decimal("70"),
        classifier_version="market-intelligence-composite-v1",
        input_completeness=MarketStateInputCompleteness.COMPLETE,
        fallback_applied=False,
        fallback_reason=MarketStateFallbackReason.NONE,
        missing_fields=(),
        source_lineage=("test",),
        classifier_inputs=(
            ClassifierInputRecord(
                name="benchmark_close",
                value="100",
                available=True,
                source="test",
                input_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                staleness_days=0,
                fallback_status="NONE",
            ),
        ),
        provenance_id=provenance_id,
        market_classifier_version="market-intelligence-composite-v1",
        market_classifier_fingerprint="fingerprint1",
        benchmark_builder_version="benchmark-state-builder-v1",
        market_feature_definition_version="market-feature-definitions-v1",
        fallback_policy_version="market-fallback-policy-v1",
    )


def _manifest_entry(entry_id: str) -> AnalyticalReleaseManifestEntry:
    return AnalyticalReleaseManifestEntry(
        manifest_entry_id=entry_id,
        release_or_era="Test Era",
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 1, 2),
        application_version="1.0",
        component_versions=(("classifier", "v1"),),
        component_fingerprints=(("classifier", "abc123"),),
        classifier_version="v1",
        classifier_fingerprint="abc123",
        feature_definition_version="features-v1",
        fallback_policy_version="fallback-v1",
        recommendation_policy_version="recommendation-v1",
        entry_timing_version="entry-v1",
        trade_plan_version="trade-v1",
        approval_policy_version="approval-v1",
        allocation_policy_version="allocation-v1",
        schema_signature="schema-v1",
        output_signature="output-v1",
        evidence_refs=("e1",),
        evidence_strength=EvidenceReliability.AUTHORITATIVE,
        compatibility_policy=ComponentCompatibility.EXACT_FINGERPRINT_MATCH,
        confidence="HIGH",
        review_status=ReleaseReviewStatus.VERIFIED,
        exact_reproduction_supported=True,
        semantic_replay_supported=True,
        limitations=("test",),
    )
