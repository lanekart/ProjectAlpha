from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

import alpha.cli as cli_module
from alpha.cli import app
from alpha.historical_replay import (
    HISTORICAL_SOURCE_MANIFEST_VERSION,
    HistoricalArchitectureConclusion,
    HistoricalCapabilityStatus,
    HistoricalCredentialStatus,
    HistoricalEvaluationStatus,
    HistoricalEvidenceLevel,
    HistoricalLicenseStatus,
    HistoricalNextStepConclusion,
    HistoricalPermissionStatus,
    HistoricalRequirementPriority,
    HistoricalSourceCapability,
    HistoricalSourceClass,
    HistoricalSourceEvaluationEngine,
    HistoricalSourceEvaluationManifest,
    HistoricalSourceEvaluationManifestRecord,
    HistoricalSourceObservation,
    HistoricalSourceRecommendationReport,
    build_historical_source_candidates,
    build_project_historical_source_evaluation,
    deterministic_historical_source_sample,
    historical_source_credential_statuses,
    historical_source_requirements,
)
from alpha.historical_replay.breakout_source_gap import (
    BreakoutGapCause,
    BreakoutGapRecoveryClass,
)

runner = CliRunner()

_PROJECT_REPLAY_CORPUS_AVAILABLE = (
    Path(".alpha/breakout_reference_dataset_v1.json").is_file()
    and Path(".alpha/candidate_learning_ledger.json").is_file()
)


def _record(
    candidate_id: str,
    *,
    candidate_date: date = date(2016, 7, 11),
    cause: BreakoutGapCause = BreakoutGapCause.INSUFFICIENT_PRE_CANDIDATE_LOOKBACK,
    corporate_action: bool = False,
    recovery: BreakoutGapRecoveryClass = (
        BreakoutGapRecoveryClass.REQUIRES_NEW_EXTERNAL_SOURCE
    ),
) -> HistoricalSourceEvaluationManifestRecord:
    return HistoricalSourceEvaluationManifestRecord(
        candidate_id=candidate_id,
        candidate_date=candidate_date,
        current_symbol=None,
        historical_symbol=f"SYM{candidate_id}",
        permanent_identifier=f"id-{candidate_id}",
        required_start_date=date(candidate_date.year - 1, 12, 1),
        required_end_date=candidate_date,
        required_start_basis="test basis",
        minimum_bars_required=121,
        gap_cause=cause,
        corporate_action_requirement=corporate_action,
        identity_uncertainty=True,
        recovery_population=recovery.value,
        replay_year=candidate_date.year,
        sector="UNKNOWN",
        market_regime="NEUTRAL",
        setup_type="MOMENTUM CONTINUATION",
        liquidity_proxy=Decimal("0.5"),
        continuity_status="ACTIVE_TO_SOURCE_END",
    )


def _manifest(
    records: tuple[HistoricalSourceEvaluationManifestRecord, ...] | None = None,
) -> HistoricalSourceEvaluationManifest:
    rows = records or (
        _record("a"),
        _record(
            "b",
            candidate_date=date(2024, 3, 4),
            cause=BreakoutGapCause.CORPORATE_ACTION_AMBIGUITY,
            corporate_action=True,
            recovery=BreakoutGapRecoveryClass.RECOVERY_UNCERTAIN,
        ),
    )
    return HistoricalSourceEvaluationManifest(
        manifest_version=HISTORICAL_SOURCE_MANIFEST_VERSION,
        records=rows,
        source_required_count=sum(
            item.recovery_population
            == BreakoutGapRecoveryClass.REQUIRES_NEW_EXTERNAL_SOURCE.value
            for item in rows
        ),
        recovery_uncertain_count=sum(
            item.recovery_population
            == BreakoutGapRecoveryClass.RECOVERY_UNCERTAIN.value
            for item in rows
        ),
        unique_symbols=len({item.historical_symbol for item in rows}),
        earliest_required_date=min(item.required_start_date for item in rows),
        latest_required_date=max(item.required_end_date for item in rows),
        checksum="manifest-checksum",
    )


def _provider(
    *,
    provider_id: str = "TEST_EXCHANGE",
    source_class: HistoricalSourceClass = HistoricalSourceClass.EXCHANGE_LICENSED_DATA,
    all_capabilities: bool = True,
    license_status: HistoricalLicenseStatus = (
        HistoricalLicenseStatus.CLEARLY_PERMITTED
    ),
):
    base = next(
        item
        for item in build_historical_source_candidates()
        if item.provider_id == "NSE_DATA_ANALYTICS_LICENSED"
    )
    capabilities = tuple(
        HistoricalSourceCapability(
            requirement_key=requirement.key,
            status=(
                HistoricalCapabilityStatus.SUPPORTED
                if all_capabilities
                else HistoricalCapabilityStatus.UNKNOWN
            ),
            evidence_level=HistoricalEvidenceLevel.DOCUMENTED,
            explanation="test capability",
            source_url="https://example.test/official",
        )
        for requirement in historical_source_requirements()
    )
    permissions = (
        HistoricalPermissionStatus.PERMITTED
        if license_status is HistoricalLicenseStatus.CLEARLY_PERMITTED
        else HistoricalPermissionStatus.UNKNOWN
    )
    return replace(
        base,
        provider_id=provider_id,
        name=provider_id,
        source_class=source_class,
        capabilities=capabilities,
        license_assessment=replace(
            base.license_assessment,
            status=license_status,
            local_storage=permissions,
            derived_use=permissions,
        ),
        credential_environment_names=("TEST_TOKEN",),
    )


def _observation(
    candidate_id: str,
    *,
    usable_bars: int = 121,
    historical_symbol_matched: bool = True,
    current_symbol_only: bool = False,
    corporate_action: bool | None = True,
    timezone_consistent: bool = True,
    adjustment_consistent: bool = True,
    duplicate: bool = False,
    revision: str | None = "r1",
    checksum: str | None = None,
) -> HistoricalSourceObservation:
    return HistoricalSourceObservation(
        provider_id="TEST_EXCHANGE",
        candidate_id=candidate_id,
        query_succeeded=True,
        bars_returned=usable_bars,
        usable_bars=usable_bars,
        ohlc_complete=True,
        volume_complete=True,
        historical_symbol_matched=historical_symbol_matched,
        current_symbol_only=current_symbol_only,
        renamed_symbol_supported=True,
        delisted_symbol_supported=True,
        corporate_action_evidence_available=corporate_action,
        timezone_consistent=timezone_consistent,
        adjustment_consistent=adjustment_consistent,
        duplicate_or_conflicting_bars=duplicate,
        revision_identifier=revision,
        response_checksum=checksum or f"checksum-{candidate_id}-{revision}",
    )


def _evaluate(
    observations: tuple[HistoricalSourceObservation, ...] = (),
    *,
    manifest: HistoricalSourceEvaluationManifest | None = None,
    provider=None,
    full_population: bool = False,
    credentials: HistoricalCredentialStatus = HistoricalCredentialStatus.CONFIGURED,
) -> HistoricalSourceRecommendationReport:
    source_manifest = manifest or _manifest()
    source_provider = provider or _provider()
    return HistoricalSourceEvaluationEngine().evaluate(
        manifest=source_manifest,
        sample=deterministic_historical_source_sample(
            source_manifest,
            sample_size=len(source_manifest.records),
        ),
        providers=(source_provider,),
        credential_statuses={source_provider.provider_id: credentials},
        observations=observations,
        full_population=full_population,
    )


def test_requirements_include_mandatory_ohlcv() -> None:
    requirements = {item.key: item for item in historical_source_requirements()}
    for key in ("daily_open", "daily_high", "daily_low", "daily_close", "daily_volume"):
        assert requirements[key].priority is HistoricalRequirementPriority.MANDATORY


@pytest.mark.parametrize(
    "key",
    [
        "historical_symbol",
        "permanent_identifier",
        "listing_date",
        "delisting_date",
        "symbol_change_history",
    ],
)
def test_requirements_include_identity_fields(key: str) -> None:
    requirements = {item.key: item for item in historical_source_requirements()}
    assert requirements[key].priority is HistoricalRequirementPriority.MANDATORY


@pytest.mark.parametrize(
    "key",
    [
        "split_bonus_history",
        "corporate_action_effective_dates",
        "adjustment_mode",
        "raw_series",
    ],
)
def test_requirements_include_corporate_action_fields(key: str) -> None:
    requirements = {item.key: item for item in historical_source_requirements()}
    assert requirements[key].priority is HistoricalRequirementPriority.MANDATORY


@pytest.mark.parametrize(
    "key",
    ["publication_timing", "revision_policy", "provenance", "exchange_session"],
)
def test_requirements_include_point_in_time_fields(key: str) -> None:
    requirements = {item.key: item for item in historical_source_requirements()}
    assert requirements[key].priority is HistoricalRequirementPriority.MANDATORY


@pytest.mark.parametrize(
    "key",
    ["local_storage_permission", "derived_use_permission"],
)
def test_requirements_include_permission_fields(key: str) -> None:
    requirements = {item.key: item for item in historical_source_requirements()}
    assert requirements[key].priority is HistoricalRequirementPriority.MANDATORY


def test_delivery_volume_and_adjusted_prices_are_not_required() -> None:
    requirements = {item.key: item for item in historical_source_requirements()}
    assert (
        requirements["delivery_volume"].priority
        is HistoricalRequirementPriority.NOT_REQUIRED
    )
    assert (
        requirements["adjusted_prices"].priority
        is HistoricalRequirementPriority.NOT_REQUIRED
    )


def test_unsupported_mandatory_capability_fails_provider_gate() -> None:
    report = _evaluate(
        (_observation("a"), _observation("b")),
        provider=_provider(all_capabilities=False),
    )
    assert report.coverage_results[0].mandatory_gate_passed is False
    assert report.coverage_results[0].mandatory_failures


@pytest.mark.skipif(
    not _PROJECT_REPLAY_CORPUS_AVAILABLE,
    reason="requires the authoritative local .alpha replay corpus",
)
def test_project_manifest_contains_exact_missing_populations() -> None:
    report = build_project_historical_source_evaluation(dry_run=True)
    assert len(report.manifest.records) == 657
    assert report.manifest.source_required_count == 608
    assert report.manifest.recovery_uncertain_count == 49
    assert report.manifest.unique_symbols == 158


@pytest.mark.skipif(
    not _PROJECT_REPLAY_CORPUS_AVAILABLE,
    reason="requires the authoritative local .alpha replay corpus",
)
def test_project_manifest_is_deterministic_and_retains_identity() -> None:
    first = build_project_historical_source_evaluation(dry_run=True)
    second = build_project_historical_source_evaluation(dry_run=True)
    assert first.manifest.checksum == second.manifest.checksum
    assert first.manifest.records == second.manifest.records
    assert all(item.historical_symbol for item in first.manifest.records)
    assert all(item.permanent_identifier for item in first.manifest.records)
    assert all(item.current_symbol is None for item in first.manifest.records)


@pytest.mark.skipif(
    not _PROJECT_REPLAY_CORPUS_AVAILABLE,
    reason="requires the authoritative local .alpha replay corpus",
)
def test_project_manifest_order_and_lookback_are_conservative() -> None:
    report = build_project_historical_source_evaluation(dry_run=True)
    keys = tuple(
        (item.candidate_date, item.historical_symbol, item.candidate_id)
        for item in report.manifest.records
    )
    assert keys == tuple(sorted(keys))
    assert all(item.minimum_bars_required == 121 for item in report.manifest.records)
    assert all(
        item.required_start_date < item.required_end_date
        for item in report.manifest.records
    )


@pytest.mark.skipif(
    not _PROJECT_REPLAY_CORPUS_AVAILABLE,
    reason="requires the authoritative local .alpha replay corpus",
)
def test_project_manifest_retains_exact_gap_causes() -> None:
    report = build_project_historical_source_evaluation(dry_run=True)
    causes = {item.gap_cause for item in report.manifest.records}
    assert causes == {
        BreakoutGapCause.INSUFFICIENT_PRE_CANDIDATE_LOOKBACK,
        BreakoutGapCause.CORPORATE_ACTION_AMBIGUITY,
        BreakoutGapCause.MULTI_SESSION_GAP,
        BreakoutGapCause.PARTIAL_LOOKBACK_AVAILABLE,
        BreakoutGapCause.LEGITIMATELY_INSUFFICIENT_TRADING_HISTORY,
    }


def test_manifest_and_sample_are_immutable_and_versioned() -> None:
    manifest = _manifest()
    assert manifest.manifest_version == HISTORICAL_SOURCE_MANIFEST_VERSION
    with pytest.raises(FrozenInstanceError):
        manifest.records[0].candidate_id = "changed"  # type: ignore[misc]


def test_deterministic_sample_selection_and_strata() -> None:
    manifest = _manifest()
    first = deterministic_historical_source_sample(manifest, sample_size=2)
    second = deterministic_historical_source_sample(manifest, sample_size=2)
    assert first == second
    assert first.checksum == second.checksum
    assert {item.replay_year for item in first.records} == {2016, 2024}


def test_documented_only_does_not_fabricate_coverage() -> None:
    result = _evaluate().coverage_results[0]
    assert result.evidence_level is HistoricalEvidenceLevel.DOCUMENTED
    assert result.candidates_returned is None
    assert result.projected_reconstruction_readiness is None


def test_credentials_unavailable_is_not_provider_failure() -> None:
    result = _evaluate(
        credentials=HistoricalCredentialStatus.SUBSCRIPTION_REQUIRED
    ).coverage_results[0]
    assert (
        result.evaluation_status
        is HistoricalEvaluationStatus.NOT_EVALUATED_CREDENTIALS_REQUIRED
    )
    assert result.observations_received == 0


def test_provider_rate_limits_are_documented_without_live_calls() -> None:
    providers = build_historical_source_candidates()
    assert all(item.rate_limit for item in providers)
    assert all(item.batch_capability for item in providers)
    assert all(item.authentication_requirement for item in providers)


def test_partial_response_is_observed_but_not_complete() -> None:
    result = _evaluate((_observation("a"),)).coverage_results[0]
    assert (
        result.evaluation_status is HistoricalEvaluationStatus.OBSERVED_SAMPLE_PARTIAL
    )
    assert result.candidates_with_sufficient_lookback == 1
    assert result.mandatory_gate_passed is False


@pytest.mark.parametrize(
    ("observation", "expected_rate"),
    [
        (_observation("a", historical_symbol_matched=False), Decimal("0.0000")),
        (_observation("a", current_symbol_only=True), Decimal("1.0000")),
    ],
)
def test_historical_identity_failures_block_sufficient_coverage(
    observation: HistoricalSourceObservation,
    expected_rate: Decimal,
) -> None:
    single = _manifest((_record("a"),))
    result = _evaluate((observation,), manifest=single).coverage_results[0]
    assert result.candidates_with_sufficient_lookback == 0
    if observation.current_symbol_only:
        assert result.historical_symbol_success_rate == expected_rate
    else:
        assert result.historical_symbol_success_rate == expected_rate


def test_delisted_symbol_observation_is_measured() -> None:
    observation = replace(_observation("a"), delisted_symbol_supported=False)
    single = _manifest((_record("a"),))
    result = _evaluate((observation,), manifest=single).coverage_results[0]
    assert result.delisted_symbol_success_rate == Decimal("0.0000")


@pytest.mark.parametrize(
    ("observation", "expected"),
    [
        (_observation("a"), 1),
        (_observation("a", usable_bars=120), 0),
        (_observation("a", adjustment_consistent=False), 0),
        (_observation("a", timezone_consistent=False), 0),
        (_observation("a", duplicate=True), 0),
    ],
)
def test_integrity_conditions_control_sufficient_lookback(
    observation: HistoricalSourceObservation,
    expected: int,
) -> None:
    single = _manifest((_record("a"),))
    result = _evaluate((observation,), manifest=single).coverage_results[0]
    assert result.candidates_with_sufficient_lookback == expected


def test_corporate_action_mismatch_blocks_corporate_action_case() -> None:
    record = _record(
        "a",
        cause=BreakoutGapCause.CORPORATE_ACTION_AMBIGUITY,
        corporate_action=True,
    )
    result = _evaluate(
        (_observation("a", corporate_action=False),),
        manifest=_manifest((record,)),
    ).coverage_results[0]
    assert result.corporate_action_evidence_success_rate == Decimal("0.0000")
    assert result.candidates_with_sufficient_lookback == 0


def test_revision_and_response_conflict_are_explained() -> None:
    single = _manifest((_record("a"),))
    observations = (
        _observation("a", revision="r1", checksum="one"),
        _observation("a", revision="r2", checksum="two"),
    )
    result = _evaluate(observations, manifest=single).coverage_results[0]
    assert any("conflicting checksums" in item for item in result.warnings)
    assert any("revision identifiers changed" in item for item in result.warnings)
    assert result.mandatory_gate_passed is False


def test_observed_checksum_is_stable_across_response_order() -> None:
    observations = (_observation("a"), _observation("b"))
    first = _evaluate(observations).coverage_results[0]
    second = _evaluate(tuple(reversed(observations))).coverage_results[0]
    assert first.observed_checksum == second.observed_checksum


def test_full_verified_exchange_source_can_pass_single_source_gate() -> None:
    report = _evaluate(
        (_observation("a"), _observation("b")),
        full_population=True,
    )
    assert report.coverage_results[0].mandatory_gate_passed is True
    assert (
        report.architecture_conclusion
        is HistoricalArchitectureConclusion.SINGLE_AUTHORITATIVE_SOURCE_IDENTIFIED
    )
    assert (
        report.next_step_conclusion
        is HistoricalNextStepConclusion.COVERAGE_PROOF_COMPLETE
    )


def test_2016_coverage_is_reported_separately() -> None:
    result = _evaluate((_observation("a"), _observation("b"))).coverage_results[0]
    assert result.candidate_2016_target == 1
    assert result.candidate_2016_returned == 1
    assert result.candidate_2016_sufficient == 1


@pytest.mark.parametrize(
    "expected",
    [
        HistoricalLicenseStatus.CLEARLY_PERMITTED,
        HistoricalLicenseStatus.PERMITTED_WITH_CONDITIONS,
        HistoricalLicenseStatus.REQUIRES_COMMERCIAL_LICENSE,
        HistoricalLicenseStatus.RESTRICTIONS_UNCLEAR,
        HistoricalLicenseStatus.TERMS_NOT_FOUND,
    ],
)
def test_license_classification_values_are_supported(
    expected: HistoricalLicenseStatus,
) -> None:
    assert HistoricalLicenseStatus(expected.value) is expected


def test_static_license_audit_covers_caching_and_derived_use_restrictions() -> None:
    providers = {
        item.provider_id: item for item in build_historical_source_candidates()
    }
    kite = providers["ZERODHA_KITE_HISTORICAL"].license_assessment
    public_nse = providers["NSE_PUBLIC_ARCHIVES"].license_assessment
    assert kite.local_storage is HistoricalPermissionStatus.PROHIBITED
    assert kite.derived_use is HistoricalPermissionStatus.UNKNOWN
    assert public_nse.caching is HistoricalPermissionStatus.REQUIRES_WRITTEN_PERMISSION


def test_catalog_license_classifications_have_evidence_boundaries() -> None:
    providers = {
        item.provider_id: item for item in build_historical_source_candidates()
    }
    assert (
        providers["NSE_DATA_ANALYTICS_LICENSED"].license_assessment.status
        is HistoricalLicenseStatus.REQUIRES_COMMERCIAL_LICENSE
    )
    assert (
        providers["ZERODHA_KITE_HISTORICAL"].license_assessment.status
        is HistoricalLicenseStatus.PERMITTED_WITH_CONDITIONS
    )
    assert (
        providers["UPSTOX_HISTORICAL_V3"].license_assessment.status
        is HistoricalLicenseStatus.TERMS_NOT_FOUND
    )
    assert providers["NSE_PUBLIC_ARCHIVES"].license_assessment.unresolved_questions


def test_broad_coverage_with_unclear_license_fails_gate() -> None:
    provider = _provider(license_status=HistoricalLicenseStatus.RESTRICTIONS_UNCLEAR)
    report = _evaluate(
        (_observation("a"), _observation("b")),
        provider=provider,
        full_population=True,
    )
    assert report.coverage_results[0].mandatory_gate_passed is False
    assert (
        report.next_step_conclusion
        is HistoricalNextStepConclusion.SOURCE_EVIDENCE_INSUFFICIENT
    )


def test_exchange_source_is_preferred_to_equal_broker_source() -> None:
    manifest = _manifest()
    exchange = _provider(provider_id="TEST_EXCHANGE")
    broker = _provider(
        provider_id="TEST_BROKER",
        source_class=HistoricalSourceClass.BROKER_API,
    )
    exchange_observations = (_observation("a"), _observation("b"))
    broker_observations = tuple(
        replace(item, provider_id="TEST_BROKER") for item in exchange_observations
    )
    report = HistoricalSourceEvaluationEngine().evaluate(
        manifest=manifest,
        sample=deterministic_historical_source_sample(manifest, sample_size=2),
        providers=(broker, exchange),
        credential_statuses={
            broker.provider_id: HistoricalCredentialStatus.CONFIGURED,
            exchange.provider_id: HistoricalCredentialStatus.CONFIGURED,
        },
        observations=(*exchange_observations, *broker_observations),
        full_population=True,
    )
    assert report.best_price_history_source == "TEST_EXCHANGE"


def test_broker_only_full_coverage_remains_secondary_architecture() -> None:
    broker = _provider(source_class=HistoricalSourceClass.BROKER_API)
    report = _evaluate(
        (_observation("a"), _observation("b")),
        provider=broker,
        full_population=True,
    )
    assert (
        report.architecture_conclusion
        is HistoricalArchitectureConclusion.MULTI_SOURCE_ARCHITECTURE_REQUIRED
    )


def test_no_provider_adequate_is_deterministic() -> None:
    report = _evaluate(provider=_provider(all_capabilities=False))
    assert (
        report.next_step_conclusion
        is HistoricalNextStepConclusion.SOURCE_EVIDENCE_INSUFFICIENT
    )
    assert report.projected_readiness_approved_combination is None
    assert report.projected_remaining_unresolved_candidates is None


@pytest.mark.skipif(
    not _PROJECT_REPLAY_CORPUS_AVAILABLE,
    reason="requires the authoritative local .alpha replay corpus",
)
def test_price_and_identity_require_separate_documented_sources() -> None:
    report = build_project_historical_source_evaluation(dry_run=True)
    assert report.best_price_history_source == "NSE_DATA_ANALYTICS_LICENSED"
    assert report.best_historical_identity_source == "LSEG_DATASCOPE_SELECT"
    assert (
        report.architecture_conclusion
        is HistoricalArchitectureConclusion.MULTI_SOURCE_ARCHITECTURE_REQUIRED
    )


@pytest.mark.skipif(
    not _PROJECT_REPLAY_CORPUS_AVAILABLE,
    reason="requires the authoritative local .alpha replay corpus",
)
def test_convenient_broker_is_not_promoted_for_poor_identity_coverage() -> None:
    report = build_project_historical_source_evaluation(dry_run=True)
    providers = {item.provider_id: item for item in report.providers}
    upstox = providers["UPSTOX_HISTORICAL_V3"]
    assert (
        upstox.capability("delisting_date").status
        is HistoricalCapabilityStatus.UNSUPPORTED
    )
    assert report.best_price_history_source != upstox.provider_id


def test_credential_status_detection_does_not_return_values() -> None:
    provider = _provider()
    configured = historical_source_credential_statuses(
        (provider,), environment={"TEST_TOKEN": "top-secret"}
    )
    missing = historical_source_credential_statuses((provider,), environment={})
    assert configured == {provider.provider_id: HistoricalCredentialStatus.CONFIGURED}
    assert missing == {
        provider.provider_id: HistoricalCredentialStatus.SUBSCRIPTION_REQUIRED
    }
    assert "top-secret" not in repr(configured)


@pytest.mark.parametrize(
    ("command", "heading"),
    [
        (
            "historical-source-requirements",
            "Historical Market Data Source Requirements",
        ),
        ("historical-source-manifest", "Historical Source Evaluation Manifest"),
        ("historical-source-evaluate", "Historical Source Provider Evaluation"),
        ("historical-source-coverage", "Historical Source Coverage Proof"),
        (
            "historical-source-license-audit",
            "Historical Source License and Permitted-Use Audit",
        ),
        (
            "historical-source-recommendation",
            "Authoritative Historical Source Recommendation",
        ),
    ],
)
def test_all_historical_source_commands(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    heading: str,
) -> None:
    report = _evaluate()
    monkeypatch.setattr(
        cli_module,
        "build_project_historical_source_evaluation",
        lambda **_: report,
    )
    result = runner.invoke(app, ["replay", command])
    assert result.exit_code == 0
    assert heading in result.stdout
    assert "PRODUCTION_INFLUENCE=false" in result.stdout


def test_cli_provider_filter_and_dry_run_are_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, object] = {}
    report = _evaluate()

    def fake_build(**kwargs: object) -> HistoricalSourceRecommendationReport:
        received.update(kwargs)
        return report

    monkeypatch.setattr(
        cli_module,
        "build_project_historical_source_evaluation",
        fake_build,
    )
    result = runner.invoke(
        app,
        [
            "replay",
            "historical-source-evaluate",
            "--provider",
            "upstox-historical-v3",
            "--sample",
            "--dry-run",
            "--credentials-status",
            "not-configured",
        ],
    )
    assert result.exit_code == 0
    assert received["provider"] == "upstox-historical-v3"
    assert received["dry_run"] is True
    assert received["credential_status"] is HistoricalCredentialStatus.NOT_CONFIGURED


def test_cli_requires_explicit_non_conflicting_full_population_mode() -> None:
    result = runner.invoke(
        app,
        [
            "replay",
            "historical-source-coverage",
            "--sample",
            "--full-population",
        ],
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output


def test_cli_explicit_full_population_is_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, object] = {}
    report = _evaluate()

    def fake_build(**kwargs: object) -> HistoricalSourceRecommendationReport:
        received.update(kwargs)
        return report

    monkeypatch.setattr(
        cli_module,
        "build_project_historical_source_evaluation",
        fake_build,
    )
    result = runner.invoke(
        app,
        ["replay", "historical-source-coverage", "--full-population"],
    )
    assert result.exit_code == 0
    assert received["full_population"] is True


def test_cli_rejects_refresh_without_live_adapter() -> None:
    result = runner.invoke(
        app,
        ["replay", "historical-source-evaluate", "--refresh"],
    )
    assert result.exit_code != 0
    assert "refresh is unsupported" in result.output


def test_cli_rejects_invalid_provider() -> None:
    result = runner.invoke(
        app,
        [
            "replay",
            "historical-source-evaluate",
            "--provider",
            "not-a-provider",
        ],
    )
    assert result.exit_code != 0
    assert "unsupported historical source provider" in result.output


@pytest.mark.skipif(
    not _PROJECT_REPLAY_CORPUS_AVAILABLE,
    reason="requires the authoritative local .alpha replay corpus",
)
def test_cli_rejects_invalid_candidate() -> None:
    result = runner.invoke(
        app,
        [
            "replay",
            "historical-source-manifest",
            "--candidate-id",
            "missing-candidate",
        ],
    )
    assert result.exit_code != 0
    assert "candidate id not found" in result.output


def test_cli_json_and_csv_exports_are_deterministic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = _evaluate()
    monkeypatch.setattr(
        cli_module,
        "build_project_historical_source_evaluation",
        lambda **_: report,
    )
    json_path = tmp_path / "coverage.json"
    csv_path = tmp_path / "coverage.csv"
    json_result = runner.invoke(
        app,
        [
            "replay",
            "historical-source-coverage",
            "--format",
            "json",
            "--output",
            str(json_path),
        ],
    )
    csv_result = runner.invoke(
        app,
        [
            "replay",
            "historical-source-coverage",
            "--format",
            "csv",
            "--output",
            str(csv_path),
        ],
    )
    assert json_result.exit_code == 0
    assert csv_result.exit_code == 0
    assert json.loads(json_path.read_text())[0]["provider_id"] == "TEST_EXCHANGE"
    assert csv_path.read_text().splitlines()[0].startswith("provider_id,")


def test_cli_never_prints_configured_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_TOKEN", "never-print-this-secret")
    report = _evaluate()
    monkeypatch.setattr(
        cli_module,
        "build_project_historical_source_evaluation",
        lambda **_: report,
    )
    result = runner.invoke(app, ["replay", "historical-source-recommendation"])
    assert result.exit_code == 0
    assert "never-print-this-secret" not in result.stdout


def test_diagnostic_module_has_no_production_provider_dependency() -> None:
    source = Path("alpha/historical_replay/historical_source_evaluation.py").read_text()
    service = Path(
        "alpha/historical_replay/historical_source_evaluation_service.py"
    ).read_text()
    assert "alpha.data.providers" not in source
    assert "alpha.data.providers" not in service
    assert "PRODUCTION_INFLUENCE = False" in source


def test_diagnostic_report_has_no_production_influence() -> None:
    report = _evaluate()
    assert report.production_influence is False
    assert report.manifest.production_influence is False
    assert report.sample.production_influence is False
    assert all(item.production_influence is False for item in report.coverage_results)
