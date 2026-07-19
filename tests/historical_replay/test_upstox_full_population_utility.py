from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

import alpha.cli as cli_module
from alpha.cli import app
from alpha.historical_replay.breakout_source_gap import BreakoutSourceGapAuditReport
from alpha.historical_replay.breakout_source_gap_service import (
    build_project_breakout_source_gap_audit,
)
from alpha.historical_replay.historical_source_evaluation import (
    HistoricalSourceEvaluationManifest,
    HistoricalSourceEvaluationManifestRecord,
)
from alpha.historical_replay.historical_source_evaluation_service import (
    build_project_historical_source_evaluation,
)
from alpha.historical_replay.upstox_full_population_utility import (
    UpstoxFullPopulationUtilityEngine,
    UpstoxSelectionBiasImpact,
    classify_selection_bias_impact,
    render_upstox_full_population_utility,
)
from alpha.historical_replay.upstox_historical_probe import (
    UpstoxAuthProbeStatus,
    UpstoxCandle,
    UpstoxCandleBatch,
    UpstoxCoverageClassification,
    UpstoxHistoricalCandidateEvidence,
    UpstoxHistoricalCandleValidator,
    UpstoxHistoricalEvidenceDataset,
    UpstoxHistoricalEvidenceRepository,
    UpstoxIdentityConfidence,
    UpstoxIdentityMatchMethod,
    UpstoxIdentityResolution,
    UpstoxIdentityStatus,
    UpstoxOperationalMetrics,
    UpstoxProbeConclusion,
    UpstoxProbeCredentialStatus,
    UpstoxRecommendedSourceRole,
    UpstoxSeriesDefect,
    export_upstox_evidence_json,
)
from alpha.historical_replay.upstox_historical_probe_service import (
    UpstoxHistoricalProbeService,
)

IST = timezone(timedelta(hours=5, minutes=30))
runner = CliRunner()


@pytest.fixture(scope="module")
def manifest() -> HistoricalSourceEvaluationManifest:
    return build_project_historical_source_evaluation(dry_run=True).manifest


@pytest.fixture(scope="module")
def breakout_audit() -> BreakoutSourceGapAuditReport:
    return build_project_breakout_source_gap_audit()


def _evidence(
    record: HistoricalSourceEvaluationManifestRecord,
) -> UpstoxHistoricalCandidateEvidence:
    start = record.required_end_date - timedelta(days=120)
    candles = tuple(
        UpstoxCandle(
            observed_at=datetime.combine(
                start + timedelta(days=index), datetime.min.time(), IST
            ),
            open_price=Decimal("100"),
            high_price=Decimal("102"),
            low_price=Decimal("98"),
            close_price=Decimal("101"),
            volume=Decimal("1000"),
        )
        for index in range(121)
    )
    identity = UpstoxIdentityResolution(
        candidate_id=record.candidate_id,
        requested_historical_symbol=record.historical_symbol,
        matched_symbol=record.historical_symbol,
        isin="INE000A01001",
        instrument_key="NSE_EQ|INE000A01001",
        match_method=UpstoxIdentityMatchMethod.UPSTOX_INSTRUMENT_SEARCH,
        match_confidence=UpstoxIdentityConfidence.MEDIUM,
        status=UpstoxIdentityStatus.RESOLVED_PROVISIONAL_FOR_PRICE_PROBE,
        active_status=(
            "ACTIVE_TO_SOURCE_END"
            if record.continuity_status == "ACTIVE_TO_SOURCE_END"
            else "INACTIVE_OR_ENDED"
        ),
        historical_continuity_evidence="Provisional exact symbol match.",
        ambiguity_reason=None,
        price_probe_eligible=True,
        identity_confirmed=False,
        renamed_security=False,
        inactive_security=record.continuity_status != "ACTIVE_TO_SOURCE_END",
    )
    return UpstoxHistoricalCandleValidator().evaluate(
        record,
        identity,
        batch=UpstoxCandleBatch(
            candles=candles,
            malformed_rows=0,
            http_status=200,
            response_checksum="not-persisted",
        ),
    )


def _dataset(
    manifest: HistoricalSourceEvaluationManifest,
    records: tuple[UpstoxHistoricalCandidateEvidence, ...],
    *,
    scope: str = "FULL_POPULATION",
) -> UpstoxHistoricalEvidenceDataset:
    return UpstoxHistoricalEvidenceDataset(
        dataset_version="upstox-historical-evidence-dataset-v1",
        probe_version="upstox-historical-evidence-probe-v1",
        source_manifest_version=manifest.manifest_version,
        source_manifest_checksum=manifest.checksum,
        sample_checksum="deterministic-sample",
        scope=scope,
        credential_status=UpstoxProbeCredentialStatus.CONFIGURED_REDACTED,
        authentication_status=UpstoxAuthProbeStatus.TOKEN_ACCEPTED,
        records=records,
        operational_metrics=UpstoxOperationalMetrics(
            total_network_requests=900,
            successful_requests=900,
            elapsed_seconds=Decimal("120"),
            request_rate_per_second=Decimal("7.5"),
        ),
    )


def _population_records(
    manifest: HistoricalSourceEvaluationManifest,
    *,
    covered_ids: set[str],
) -> tuple[UpstoxHistoricalCandidateEvidence, ...]:
    template = _evidence(manifest.records[0])
    rows: list[UpstoxHistoricalCandidateEvidence] = []
    for record in manifest.records:
        covered = record.candidate_id in covered_ids
        rows.append(
            replace(
                template,
                candidate_id=record.candidate_id,
                candidate_date=record.candidate_date,
                replay_year=record.replay_year,
                gap_cause=record.gap_cause.value,
                setup_type=record.setup_type,
                market_regime=record.market_regime,
                requested_historical_symbol=record.historical_symbol,
                matched_symbol=record.historical_symbol,
                requested_start_date=record.required_start_date,
                requested_end_date=record.required_end_date,
                inactive_security=(record.continuity_status != "ACTIVE_TO_SOURCE_END"),
                active_status=(
                    "ACTIVE_TO_SOURCE_END"
                    if record.continuity_status == "ACTIVE_TO_SOURCE_END"
                    else "INACTIVE_OR_ENDED"
                ),
                raw_bars_returned=121 if covered else 0,
                pre_cutoff_bars=121 if covered else 0,
                normalized_bars=121 if covered else 0,
                integrity_valid_bars=121 if covered else 0,
                returned_bar_count=121 if covered else 0,
                usable_pre_candidate_bars=121 if covered else 0,
                has_sufficient_raw_lookback=covered,
                has_sufficient_pre_cutoff_lookback=covered,
                has_sufficient_valid_lookback=covered,
                sufficient_lookback=covered,
                full_price_coverage=covered,
                coverage_classification=(
                    UpstoxCoverageClassification.FULL_PRICE_COVERAGE
                    if covered
                    else UpstoxCoverageClassification.CANDIDATE_WINDOW_MISSING
                ),
            )
        )
    return tuple(rows)


def test_manifest_population_invariants(
    manifest: HistoricalSourceEvaluationManifest,
) -> None:
    assert len(manifest.records) == 657
    assert manifest.source_required_count == 608
    assert manifest.recovery_uncertain_count == 49


def test_incomplete_population_reconciles_not_tested_without_fabrication(
    manifest: HistoricalSourceEvaluationManifest,
    breakout_audit: BreakoutSourceGapAuditReport,
) -> None:
    evidence = _evidence(manifest.records[0])
    report = UpstoxFullPopulationUtilityEngine().build(
        manifest=manifest,
        dataset=_dataset(manifest, (evidence,), scope="SAMPLE"),
        breakout_audit=breakout_audit,
    )
    assert report.completed_candidates == 1
    assert report.not_tested_candidates == 656
    assert sum(value for _, value in report.terminal_coverage_distribution) == 657
    assert report.full_price_coverage_candidates == 1
    assert report.full_price_coverage_rate == Decimal("0.0015")
    assert report.exact_conclusion is UpstoxProbeConclusion.UPSTOX_FULL_TRIAL_INCOMPLETE
    assert (
        report.recommended_source_role
        is UpstoxRecommendedSourceRole.EMPIRICAL_TRIAL_ONLY
    )


def test_full_population_denominators_and_slices_reconcile(
    manifest: HistoricalSourceEvaluationManifest,
    breakout_audit: BreakoutSourceGapAuditReport,
) -> None:
    covered_ids = {item.candidate_id for item in manifest.records[::2]}
    dataset = _dataset(
        manifest,
        _population_records(manifest, covered_ids=covered_ids),
    )
    report = UpstoxFullPopulationUtilityEngine().build(
        manifest=manifest,
        dataset=dataset,
        breakout_audit=breakout_audit,
    )
    assert report.completed_candidates == 657
    assert report.not_tested_candidates == 0
    assert report.terminal_statuses_reconcile is True
    assert report.full_price_coverage_candidates == len(covered_ids)
    assert report.full_price_coverage_rate == (
        Decimal(len(covered_ids)) / Decimal(657)
    ).quantize(Decimal("0.0001"))
    for dimension in {
        "historical_symbol",
        "replay_year",
        "candidate_year",
        "gap_cause",
        "recovery_population",
    }:
        rows = tuple(
            item for item in report.coverage_slices if item.dimension == dimension
        )
        assert sum(item.candidates for item in rows) == 657
        assert sum(item.full_price_coverage for item in rows) == len(covered_ids)
    assert report.authoritative_identities == 0
    assert report.provisional_identities == 657
    assert report.actual_authoritative_readiness == breakout_audit.ready_records
    assert report.maximum_theoretical_readiness == (
        breakout_audit.ready_records + len(covered_ids)
    )


def test_invalid_series_is_excluded_from_full_price_coverage(
    manifest: HistoricalSourceEvaluationManifest,
    breakout_audit: BreakoutSourceGapAuditReport,
) -> None:
    valid = _evidence(manifest.records[0])
    invalid = replace(
        _evidence(manifest.records[1]),
        coverage_classification=UpstoxCoverageClassification.INVALID_SERIES,
        full_price_coverage=False,
        primary_series_defect=UpstoxSeriesDefect.DUPLICATE_SESSION,
        duplicate_sessions=1,
    )
    report = UpstoxFullPopulationUtilityEngine().build(
        manifest=manifest,
        dataset=_dataset(manifest, (valid, invalid), scope="SAMPLE"),
        breakout_audit=breakout_audit,
    )
    assert report.full_price_coverage_candidates == 1
    assert report.invalid_series_count == 1
    assert report.invalid_series_causes == (("DUPLICATE_SESSION", 1),)


def test_price_only_evidence_cannot_clear_identity_or_corporate_action_blockers(
    manifest: HistoricalSourceEvaluationManifest,
    breakout_audit: BreakoutSourceGapAuditReport,
) -> None:
    blocked = next(
        item
        for item in manifest.records
        if item.identity_uncertainty and item.corporate_action_requirement
    )
    records = _population_records(manifest, covered_ids={blocked.candidate_id})
    report = UpstoxFullPopulationUtilityEngine().build(
        manifest=manifest,
        dataset=_dataset(manifest, records),
        breakout_audit=breakout_audit,
    )
    assert report.candidates_still_blocked_by_identity == 1
    assert report.candidates_still_blocked_by_corporate_actions == 1
    assert report.candidates_blocked_by_both == 1
    assert report.candidates_blocked_only_by_price == 0
    assert report.simulated_readiness_after_mandatory_blockers == (
        breakout_audit.ready_records
    )
    assert report.actual_authoritative_readiness == breakout_audit.ready_records


def test_year_biased_coverage_and_inactive_exclusion_are_explicit(
    manifest: HistoricalSourceEvaluationManifest,
    breakout_audit: BreakoutSourceGapAuditReport,
) -> None:
    groups = {
        "2016": {
            item.candidate_id
            for item in manifest.records
            if item.candidate_date.year == 2016
        },
        "2017-2020": {
            item.candidate_id
            for item in manifest.records
            if 2017 <= item.candidate_date.year <= 2020
        },
        "2021-2026": {
            item.candidate_id
            for item in manifest.records
            if 2021 <= item.candidate_date.year <= 2026
        },
    }
    excluded = min(groups.values(), key=len)
    all_ids = {item.candidate_id for item in manifest.records}
    report = UpstoxFullPopulationUtilityEngine().build(
        manifest=manifest,
        dataset=_dataset(
            manifest,
            _population_records(manifest, covered_ids=all_ids - excluded),
        ),
        breakout_audit=breakout_audit,
    )
    assert (
        report.exact_conclusion
        is UpstoxProbeConclusion.UPSTOX_PRICE_COVERAGE_YEAR_BIASED
    )
    inactive_ids = {
        item.candidate_id
        for item in manifest.records
        if item.continuity_status != "ACTIVE_TO_SOURCE_END"
    }
    inactive_report = UpstoxFullPopulationUtilityEngine().build(
        manifest=manifest,
        dataset=_dataset(
            manifest,
            _population_records(manifest, covered_ids=all_ids - inactive_ids),
        ),
        breakout_audit=breakout_audit,
    )
    inactive_slice = next(
        item
        for item in inactive_report.coverage_slices
        if item.dimension == "active_status" and item.key == "INACTIVE"
    )
    assert inactive_slice.candidates == len(inactive_ids)
    assert inactive_slice.full_price_coverage == 0


@pytest.mark.parametrize(
    ("baseline", "provisional", "hhi", "expected"),
    (
        (
            Decimal("0.20"),
            Decimal("0.12"),
            Decimal("0.05"),
            UpstoxSelectionBiasImpact.MATERIALLY_REDUCES_OBSERVED_SELECTION_BIAS,
        ),
        (
            Decimal("0.20"),
            Decimal("0.18"),
            Decimal("0.05"),
            UpstoxSelectionBiasImpact.MODESTLY_REDUCES_OBSERVED_SELECTION_BIAS,
        ),
        (
            Decimal("0.20"),
            Decimal("0.20"),
            Decimal("0.05"),
            UpstoxSelectionBiasImpact.LEAVES_OBSERVED_SELECTION_BIAS_LARGELY_UNCHANGED,
        ),
        (
            Decimal("0.20"),
            Decimal("0.22"),
            Decimal("0.05"),
            UpstoxSelectionBiasImpact.WORSENS_OBSERVED_CONCENTRATION,
        ),
        (
            Decimal("0.20"),
            Decimal("0.15"),
            Decimal("0.25"),
            UpstoxSelectionBiasImpact.WORSENS_OBSERVED_CONCENTRATION,
        ),
    ),
)
def test_selection_bias_conclusion_is_deterministic(
    baseline: Decimal,
    provisional: Decimal,
    hhi: Decimal,
    expected: UpstoxSelectionBiasImpact,
) -> None:
    assert classify_selection_bias_impact(baseline, provisional, hhi) is expected


def test_utility_json_and_text_are_redacted_and_contain_no_candles(
    tmp_path: Path,
    manifest: HistoricalSourceEvaluationManifest,
    breakout_audit: BreakoutSourceGapAuditReport,
) -> None:
    report = UpstoxFullPopulationUtilityEngine().build(
        manifest=manifest,
        dataset=_dataset(manifest, (_evidence(manifest.records[0]),), scope="SAMPLE"),
        breakout_audit=breakout_audit,
    )
    paths = (tmp_path / "one.json", tmp_path / "two.json")
    for path in paths:
        export_upstox_evidence_json(report, path)
    assert paths[0].read_bytes() == paths[1].read_bytes()
    output = paths[0].read_text(encoding="utf-8") + "\n".join(
        render_upstox_full_population_utility(report)
    )
    for forbidden in (
        "Authorization",
        "UPSTOX_ANALYTICS_TOKEN=",
        "access_token",
        "open_price",
        "close_price",
        "response_checksum",
    ):
        assert forbidden not in output
    assert report.production_influence is False


def test_utility_cli_uses_persisted_evidence_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    manifest: HistoricalSourceEvaluationManifest,
    breakout_audit: BreakoutSourceGapAuditReport,
) -> None:
    repository = UpstoxHistoricalEvidenceRepository(tmp_path / "evidence.json")
    repository.save(
        _dataset(manifest, (_evidence(manifest.records[0]),), scope="SAMPLE")
    )
    service = UpstoxHistoricalProbeService(repository=repository)
    baseline = build_project_historical_source_evaluation(dry_run=True)
    monkeypatch.setattr(cli_module, "_upstox_historical_probe_service", lambda: service)
    monkeypatch.setattr(
        cli_module,
        "build_project_historical_source_evaluation",
        lambda **_: baseline,
    )
    monkeypatch.setattr(
        cli_module,
        "build_project_breakout_source_gap_audit",
        lambda: breakout_audit,
    )
    result = runner.invoke(app, ["replay", "upstox-full-population-utility"])
    assert result.exit_code == 0
    assert "Upstox Full-Population Price Coverage and Utility Audit" in result.output
    assert "Terminal Status Reconciliation: RECONCILED" in result.output
    assert "Actual Authoritative Readiness: 889" in result.output
    assert "Account / Order Endpoint Calls: 0 / 0" in result.output
    assert "PRODUCTION_INFLUENCE=false" in result.output
