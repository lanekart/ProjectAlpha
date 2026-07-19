from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

import alpha.cli as cli_module
from alpha.cli import app
from alpha.historical_replay.breakout_source_gap import BreakoutGapCause
from alpha.historical_replay.historical_identity_bridge import (
    DuplicateOriginClassification,
    DuplicateSessionObservation,
    HistoricalIdentityAuditBundle,
    HistoricalIdentityBridgeEngine,
    HistoricalIdentityEvidenceDataset,
    HistoricalIdentityEvidenceRepository,
    HistoricalIdentitySourceRecord,
    HistoricalIdentityStatus,
    IdentityAuditConclusion,
    IdentityMatchMethod,
    IdentitySourceAuthority,
    ProvisionalMatchClassification,
    UnresolvedIdentityCause,
    UpstoxDuplicateOriginAuditEngine,
    UpstoxIdentityMetadataAuditEngine,
    classify_duplicate_origin,
    export_identity_json,
    filter_identity_records,
    render_historical_identity_bridge_audit,
)
from alpha.historical_replay.historical_source_evaluation import (
    HistoricalSourceEvaluationManifest,
    HistoricalSourceEvaluationManifestRecord,
    HistoricalSourceSampleManifest,
)
from alpha.historical_replay.upstox_historical_probe import (
    UpstoxAuthProbeStatus,
    UpstoxCoverageClassification,
    UpstoxHistoricalCandidateEvidence,
    UpstoxHistoricalCandleValidator,
    UpstoxHistoricalEvidenceDataset,
    UpstoxHistoricalEvidenceReportEngine,
    UpstoxIdentityConfidence,
    UpstoxIdentityMatchMethod,
    UpstoxIdentityResolution,
    UpstoxIdentityStatus,
    UpstoxInstrumentRecord,
    UpstoxProbeCredentialStatus,
    render_upstox_evidence_report,
)

runner = CliRunner()


def _candidate(
    *,
    candidate_id: str = "candidate-1",
    symbol: str = "ALPHAOLD",
    permanent_identifier: str = "INTERNAL-1",
    current_symbol: str | None = None,
    candidate_date: date = date(2020, 6, 15),
    corporate_action_required: bool = False,
) -> HistoricalSourceEvaluationManifestRecord:
    return HistoricalSourceEvaluationManifestRecord(
        candidate_id=candidate_id,
        candidate_date=candidate_date,
        current_symbol=current_symbol,
        historical_symbol=symbol,
        permanent_identifier=permanent_identifier,
        required_start_date=date(2019, 12, 1),
        required_end_date=date(2020, 6, 12),
        required_start_basis="test",
        minimum_bars_required=121,
        gap_cause=BreakoutGapCause.SYMBOL_IDENTITY_UNRESOLVED,
        corporate_action_requirement=corporate_action_required,
        identity_uncertainty=True,
        recovery_population="REQUIRES_NEW_EXTERNAL_SOURCE",
        replay_year=2020,
        sector="TEST",
        market_regime="SIDEWAYS",
        setup_type="BREAKOUT",
        liquidity_proxy=None,
        continuity_status="ACTIVE_TO_SOURCE_END",
    )


def _provider(
    candidate: HistoricalSourceEvaluationManifestRecord,
    *,
    symbol: str | None = None,
    isin: str | None = "INE000A01001",
    instrument_key: str | None = "NSE_EQ|INE000A01001",
    status: UpstoxIdentityStatus = (
        UpstoxIdentityStatus.RESOLVED_PROVISIONAL_FOR_PRICE_PROBE
    ),
    series: str | None = "EQ",
    inactive: bool = False,
) -> UpstoxHistoricalCandidateEvidence:
    eligible = instrument_key is not None
    identity = UpstoxIdentityResolution(
        candidate_id=candidate.candidate_id,
        requested_historical_symbol=candidate.historical_symbol,
        matched_symbol=symbol or candidate.historical_symbol,
        isin=isin,
        instrument_key=instrument_key,
        match_method=(
            UpstoxIdentityMatchMethod.UPSTOX_INSTRUMENT_SEARCH
            if eligible
            else UpstoxIdentityMatchMethod.UNRESOLVED
        ),
        match_confidence=(
            UpstoxIdentityConfidence.MEDIUM
            if eligible
            else UpstoxIdentityConfidence.NONE
        ),
        status=status,
        active_status="INACTIVE_OR_ENDED" if inactive else "ACTIVE_TO_SOURCE_END",
        historical_continuity_evidence="test provider evidence",
        ambiguity_reason=(
            "No exact historical symbol matched."
            if status is UpstoxIdentityStatus.INSTRUMENT_NOT_FOUND
            else None
        ),
        price_probe_eligible=eligible,
        identity_confirmed=False,
        renamed_security=False,
        inactive_security=inactive,
        provider_exchange="NSE",
        provider_segment="NSE_EQ",
        provider_series=series,
        provider_exchange_token="12345",
        provider_security_type="EQUITY",
        provider_instrument_type="EQ",
        provider_metadata_source="INSTRUMENT_SEARCH",
        identity_search_query=candidate.historical_symbol,
        identity_search_page_size=10,
    )
    return UpstoxHistoricalCandleValidator().evaluate(candidate, identity)


def _source(
    *,
    permanent_identifier: str = "EXCHANGE-1",
    historical_symbol: str = "ALPHAOLD",
    isin: str | None = "INE000A01001",
    series: str | None = "EQ",
    effective_from: date | None = date(2010, 1, 1),
    effective_to: date | None = date(2020, 12, 31),
    listing_date: date | None = date(2010, 1, 1),
    delisting_date: date | None = date(2020, 12, 31),
    current_symbol: str | None = None,
    predecessor_identifier: str | None = None,
    successor_identifier: str | None = None,
    rename_event: str | None = None,
    series_migration_event: str | None = None,
    merger_or_demerger_event: str | None = None,
    provider_instrument_key: str | None = "NSE_EQ|INE000A01001",
) -> HistoricalIdentitySourceRecord:
    return HistoricalIdentitySourceRecord(
        permanent_identifier=permanent_identifier,
        historical_symbol=historical_symbol,
        exchange="NSE",
        series=series,
        isin=isin,
        provider_instrument_key=provider_instrument_key,
        source="OFFICIAL_TEST_MASTER",
        source_version="2020-06-15",
        source_authority=IdentitySourceAuthority.OFFICIAL_EXCHANGE,
        effective_from=effective_from,
        effective_to=effective_to,
        listing_date=listing_date,
        delisting_date=delisting_date,
        current_symbol=current_symbol,
        predecessor_identifier=predecessor_identifier,
        successor_identifier=successor_identifier,
        rename_event=rename_event,
        series_migration_event=series_migration_event,
        merger_or_demerger_event=merger_or_demerger_event,
    )


def _manifest(
    records: tuple[HistoricalSourceEvaluationManifestRecord, ...],
) -> HistoricalSourceEvaluationManifest:
    return HistoricalSourceEvaluationManifest(
        manifest_version="test-manifest-v1",
        records=records,
        source_required_count=len(records),
        recovery_uncertain_count=0,
        unique_symbols=len({item.historical_symbol for item in records}),
        earliest_required_date=min(item.required_start_date for item in records),
        latest_required_date=max(item.required_end_date for item in records),
        checksum="manifest-checksum",
    )


def _upstox_dataset(
    records: tuple[UpstoxHistoricalCandidateEvidence, ...],
) -> UpstoxHistoricalEvidenceDataset:
    return UpstoxHistoricalEvidenceDataset(
        dataset_version="upstox-test-v1",
        probe_version="probe-test-v1",
        source_manifest_version="test-manifest-v1",
        source_manifest_checksum="manifest-checksum",
        sample_checksum="sample-checksum",
        scope="FULL_POPULATION",
        credential_status=UpstoxProbeCredentialStatus.CONFIGURED_REDACTED,
        authentication_status=UpstoxAuthProbeStatus.TOKEN_ACCEPTED,
        records=records,
    )


def _identity_dataset(
    records: tuple[HistoricalIdentitySourceRecord, ...],
) -> HistoricalIdentityEvidenceDataset:
    return HistoricalIdentityEvidenceDataset(
        dataset_version="identity-test-v1",
        authorized_for_diagnostic_use=True,
        records=records,
    )


def _resolve(
    candidate: HistoricalSourceEvaluationManifestRecord,
    *,
    provider: UpstoxHistoricalCandidateEvidence | None,
    sources: tuple[HistoricalIdentitySourceRecord, ...],
):
    return HistoricalIdentityBridgeEngine().resolve_candidate(
        candidate,
        provider=provider,
        sources=sources,
    )


def test_permanent_identifier_is_highest_authoritative_match() -> None:
    candidate = _candidate(permanent_identifier="EXCHANGE-1")
    result = _resolve(candidate, provider=_provider(candidate), sources=(_source(),))
    assert (
        result.final_identity_status
        is HistoricalIdentityStatus.AUTHORITATIVE_PERMANENT_ID_MATCH
    )
    assert result.match_method is IdentityMatchMethod.PERMANENT_EXCHANGE_IDENTIFIER
    assert result.authoritative


def test_isin_interval_match_is_authoritative() -> None:
    candidate = _candidate()
    result = _resolve(candidate, provider=_provider(candidate), sources=(_source(),))
    assert (
        result.final_identity_status
        is HistoricalIdentityStatus.AUTHORITATIVE_ISIN_INTERVAL_MATCH
    )


def test_historical_symbol_exchange_series_interval_match() -> None:
    candidate = _candidate()
    provider = _provider(candidate, isin=None, series="EQ")
    source = _source(isin=None, series="EQ")
    result = _resolve(candidate, provider=provider, sources=(source,))
    assert result.final_identity_status is (
        HistoricalIdentityStatus.AUTHORITATIVE_HISTORICAL_SYMBOL_INTERVAL_MATCH
    )


def test_authoritative_rename_chain() -> None:
    candidate = _candidate()
    provider = _provider(candidate, symbol="ALPHANEW", isin=None, series=None)
    source = _source(
        isin=None,
        series=None,
        current_symbol="ALPHANEW",
        rename_event="ALPHAOLD renamed ALPHANEW",
    )
    result = _resolve(candidate, provider=provider, sources=(source,))
    assert (
        result.final_identity_status
        is HistoricalIdentityStatus.AUTHORITATIVE_RENAME_CHAIN_MATCH
    )


def test_authoritative_successor_predecessor_chain() -> None:
    candidate = _candidate(permanent_identifier="PREDECESSOR-1")
    provider = _provider(candidate, isin=None, series=None)
    source = _source(
        isin=None,
        series=None,
        predecessor_identifier="PREDECESSOR-1",
        successor_identifier="EXCHANGE-1",
    )
    result = _resolve(candidate, provider=provider, sources=(source,))
    assert result.final_identity_status is (
        HistoricalIdentityStatus.AUTHORITATIVE_SUCCESSOR_PREDECESSOR_MATCH
    )


def test_provider_instrument_key_bridges_through_authoritative_source() -> None:
    candidate = _candidate()
    result = _resolve(
        candidate,
        provider=_provider(candidate, isin=None, series=None),
        sources=(_source(isin=None, series=None),),
    )
    assert result.final_identity_status is (
        HistoricalIdentityStatus.AUTHORITATIVE_PERMANENT_ID_MATCH
    )
    assert result.match_method is IdentityMatchMethod.PROVIDER_INSTRUMENT_BRIDGE


def test_current_symbol_only_is_rejected() -> None:
    candidate = _candidate(current_symbol="ALPHANEW")
    result = _resolve(
        candidate,
        provider=_provider(candidate, symbol="ALPHANEW", isin=None),
        sources=(),
    )
    assert (
        result.final_identity_status
        is HistoricalIdentityStatus.CURRENT_SYMBOL_ONLY_UNPROVEN
    )


def test_symbol_reuse_is_ambiguous() -> None:
    candidate = _candidate()
    sources = (
        _source(permanent_identifier="EXCHANGE-1", isin=None, series=None),
        _source(permanent_identifier="EXCHANGE-2", isin=None, series=None),
    )
    result = _resolve(
        candidate,
        provider=_provider(candidate, isin=None, series=None),
        sources=sources,
    )
    assert (
        result.final_identity_status is HistoricalIdentityStatus.SYMBOL_REUSE_AMBIGUITY
    )


def test_series_migration_is_ambiguous() -> None:
    candidate = _candidate()
    result = _resolve(
        candidate,
        provider=_provider(candidate, isin=None, series="BE"),
        sources=(_source(isin=None, series="EQ", series_migration_event="BE to EQ"),),
    )
    assert result.final_identity_status is (
        HistoricalIdentityStatus.SERIES_MIGRATION_AMBIGUITY
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        (
            _source(
                effective_from=date(2021, 1, 1),
                listing_date=date(2021, 1, 1),
            ),
            HistoricalIdentityStatus.LISTING_INTERVAL_CONFLICT,
        ),
        (
            _source(
                effective_to=date(2019, 12, 31),
                delisting_date=date(2019, 12, 31),
            ),
            HistoricalIdentityStatus.DELISTING_INTERVAL_CONFLICT,
        ),
    ),
)
def test_listing_and_delisting_conflicts(
    source: HistoricalIdentitySourceRecord,
    expected: HistoricalIdentityStatus,
) -> None:
    candidate = _candidate()
    result = _resolve(candidate, provider=_provider(candidate), sources=(source,))
    assert result.final_identity_status is expected


def test_isin_conflict_is_not_upgraded() -> None:
    candidate = _candidate()
    result = _resolve(
        candidate,
        provider=_provider(candidate, isin="INE111A01001"),
        sources=(_source(isin="INE222A01001", series=None),),
    )
    assert result.final_identity_status is HistoricalIdentityStatus.ISIN_CONFLICT


def test_multiple_isin_matches_are_rejected() -> None:
    candidate = _candidate()
    sources = (
        _source(permanent_identifier="EXCHANGE-1"),
        _source(permanent_identifier="EXCHANGE-2"),
    )
    result = _resolve(candidate, provider=_provider(candidate), sources=sources)
    assert result.final_identity_status is (
        HistoricalIdentityStatus.MULTIPLE_INSTRUMENT_MATCHES
    )


def test_merger_without_direct_bridge_remains_ambiguous() -> None:
    candidate = _candidate()
    result = _resolve(
        candidate,
        provider=_provider(candidate, isin=None, series=None),
        sources=(
            _source(
                isin=None,
                series=None,
                merger_or_demerger_event="merger into successor",
            ),
        ),
    )
    assert result.final_identity_status is (
        HistoricalIdentityStatus.MERGER_OR_DEMERGER_AMBIGUITY
    )


def test_no_evidence_remains_unresolved() -> None:
    candidate = _candidate()
    result = _resolve(candidate, provider=None, sources=())
    assert result.final_identity_status is HistoricalIdentityStatus.IDENTITY_UNRESOLVED
    assert result.unresolved_cause is UnresolvedIdentityCause.MANIFEST_MISSING_ISIN


def test_provider_not_found_and_rename_causes_are_distinct() -> None:
    candidate = _candidate(current_symbol="ALPHANEW")
    not_found = _resolve(
        candidate,
        provider=_provider(
            candidate,
            isin=None,
            instrument_key=None,
            status=UpstoxIdentityStatus.INSTRUMENT_NOT_FOUND,
        ),
        sources=(),
    )
    renamed = _resolve(
        candidate,
        provider=_provider(candidate, symbol="ALPHANEW", isin=None),
        sources=(),
    )
    assert not_found.unresolved_cause is UnresolvedIdentityCause.PROVIDER_SEARCH_FAILURE
    assert renamed.unresolved_cause is UnresolvedIdentityCause.KNOWN_RENAME


def test_provider_match_and_price_coverage_remain_provisional() -> None:
    candidate = _candidate()
    provider = replace(_provider(candidate), full_price_coverage=True)
    result = _resolve(candidate, provider=provider, sources=())
    assert result.final_identity_status is (
        HistoricalIdentityStatus.PROVISIONAL_PROVIDER_SYMBOL_MATCH
    )
    assert result.provisional_classification is (
        ProvisionalMatchClassification.READY_IF_AUTHORITY_SUPPLIED
    )
    assert not result.authoritative


def test_inactive_exact_provider_symbol_remains_provisional() -> None:
    candidate = _candidate()
    result = _resolve(
        candidate,
        provider=_provider(candidate, inactive=True),
        sources=(),
    )
    assert result.inactive
    assert result.final_identity_status is (
        HistoricalIdentityStatus.PROVISIONAL_PROVIDER_SYMBOL_MATCH
    )


def test_metadata_fields_are_parsed_and_retained() -> None:
    instrument = UpstoxInstrumentRecord.from_payload(
        {
            "instrument_key": "NSE_EQ|INE000A01001",
            "trading_symbol": "ALPHAOLD",
            "isin": "INE000A01001",
            "exchange": "NSE",
            "segment": "NSE_EQ",
            "series": "EQ",
            "exchange_token": "12345",
            "security_type": "EQUITY",
            "instrument_type": "EQ",
        },
        source="INSTRUMENT_SEARCH",
    )
    assert instrument is not None
    assert instrument.exchange_token == "12345"
    assert instrument.series == "EQ"
    candidate = _candidate()
    evidence = _provider(candidate)
    audit = UpstoxIdentityMetadataAuditEngine().build(_upstox_dataset((evidence,)))
    counts = dict(audit.retained_field_counts)
    assert counts["isin"] == 1
    assert counts["instrument_key"] == 1
    assert counts["exchange"] == 1
    assert counts["series"] == 1
    assert audit.secret_fields_persisted == ()
    assert audit.account_fields_persisted == ()


def test_metadata_export_is_deterministic_and_secret_free(tmp_path: Path) -> None:
    candidate = _candidate()
    audit = UpstoxIdentityMetadataAuditEngine().build(
        _upstox_dataset((_provider(candidate),))
    )
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    export_identity_json(audit, first)
    export_identity_json(audit, second)
    assert first.read_bytes() == second.read_bytes()
    text = first.read_text(encoding="utf-8").lower()
    assert "authorization" not in text
    assert "access_token" not in text
    assert "client_secret" not in text
    assert "account_id" not in text


def test_authorized_identity_package_loads_effective_dates(tmp_path: Path) -> None:
    path = tmp_path / "identity.json"
    path.write_text(
        """{
  "authorized_for_diagnostic_use": true,
  "dataset_version": "official-test-v1",
  "records": [{
    "permanent_identifier": "EXCHANGE-1",
    "historical_symbol": "ALPHAOLD",
    "exchange": "NSE",
    "series": "EQ",
    "isin": "INE000A01001",
    "provider_instrument_key": "NSE_EQ|INE000A01001",
    "source": "OFFICIAL_TEST_MASTER",
    "source_version": "2020-06-15",
    "source_authority": "OFFICIAL_EXCHANGE",
    "effective_from": "2010-01-01",
    "effective_to": "2020-12-31"
  }]
}
""",
        encoding="utf-8",
    )
    dataset = HistoricalIdentityEvidenceRepository(path).load()
    assert dataset.authorized_for_diagnostic_use
    assert dataset.records[0].effective_from == date(2010, 1, 1)
    assert dataset.records[0].source_authority.authoritative


def test_unauthorized_identity_package_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "identity.json"
    path.write_text(
        """{
  "authorized_for_diagnostic_use": false,
  "records": [{
    "permanent_identifier": "EXCHANGE-1",
    "historical_symbol": "ALPHAOLD",
    "exchange": "NSE",
    "series": "EQ",
    "isin": null,
    "provider_instrument_key": null,
    "source": "UNAUTHORIZED",
    "source_version": "v1",
    "source_authority": "OFFICIAL_EXCHANGE",
    "effective_from": null,
    "effective_to": null
  }]
}
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not authorized"):
        HistoricalIdentityEvidenceRepository(path).load()


def test_repeated_unresolved_symbol_reconciles_candidate_and_symbol_counts() -> None:
    first = _candidate(candidate_id="one", symbol="REPEATED")
    second = _candidate(candidate_id="two", symbol="REPEATED")
    providers = (
        _provider(
            first,
            isin=None,
            instrument_key=None,
            status=UpstoxIdentityStatus.INSTRUMENT_NOT_FOUND,
            inactive=True,
        ),
        _provider(
            second,
            isin=None,
            instrument_key=None,
            status=UpstoxIdentityStatus.INSTRUMENT_NOT_FOUND,
            inactive=True,
        ),
    )
    report = HistoricalIdentityBridgeEngine().build(
        manifest=_manifest((first, second)),
        upstox_dataset=_upstox_dataset(providers),
        identity_dataset=_identity_dataset(()),
        actual_authoritative_readiness=889,
    )
    assert report.unresolved_candidates == 2
    assert report.unresolved_unique_symbols == 1
    assert report.unresolved_clusters[0].candidate_count == 2
    assert report.unresolved_clusters[0].unique_symbol_count == 1
    assert report.actual_authoritative_readiness == 889


def _duplicate_observation(
    *,
    fingerprint: str = "same",
    provider_row: str | None = None,
    request_id: str | None = None,
    request_window: str | None = None,
    stage: str | None = None,
    resume: int | None = None,
) -> DuplicateSessionObservation:
    return DuplicateSessionObservation(
        candidate_id="candidate-1",
        symbol="ALPHAOLD",
        session_date=date(2020, 5, 1),
        ohlcv_fingerprint=fingerprint,
        provider_row_fingerprint=provider_row,
        request_id=request_id,
        request_window=request_window,
        normalization_stage=stage,
        resume_generation=resume,
    )


@pytest.mark.parametrize(
    ("observations", "expected"),
    (
        (
            (_duplicate_observation(), _duplicate_observation()),
            DuplicateOriginClassification.EXACT_DUPLICATE_PROVIDER_ROW,
        ),
        (
            (
                _duplicate_observation(fingerprint="one"),
                _duplicate_observation(fingerprint="two"),
            ),
            DuplicateOriginClassification.CONFLICTING_DUPLICATE_PROVIDER_ROW,
        ),
        (
            (
                _duplicate_observation(request_id="one", request_window="a"),
                _duplicate_observation(request_id="two", request_window="b"),
            ),
            DuplicateOriginClassification.REQUEST_WINDOW_OVERLAP,
        ),
        (
            (
                _duplicate_observation(resume=1),
                _duplicate_observation(resume=2),
            ),
            DuplicateOriginClassification.RESUME_MERGE_DUPLICATE,
        ),
        (
            (
                _duplicate_observation(provider_row="row", stage="parse"),
                _duplicate_observation(provider_row="row", stage="normalize"),
            ),
            DuplicateOriginClassification.NORMALIZATION_DUPLICATE,
        ),
    ),
)
def test_duplicate_origin_classification(
    observations: tuple[DuplicateSessionObservation, ...],
    expected: DuplicateOriginClassification,
) -> None:
    assert classify_duplicate_origin(observations) is expected


def test_persisted_duplicate_count_without_rows_stays_unknown() -> None:
    candidate = _candidate()
    evidence = replace(_provider(candidate), duplicate_sessions=1)
    report = UpstoxDuplicateOriginAuditEngine().build((evidence,))
    assert report.conclusion == "DUPLICATE_ORIGIN_UNRESOLVED"
    assert report.origin_distribution == (("UNKNOWN_DUPLICATE_ORIGIN", 1),)
    assert not report.future_safe_deduplication_supportable


def test_cross_symbol_same_session_duplicate_pattern_is_detected() -> None:
    first = (_duplicate_observation(), _duplicate_observation())
    second = tuple(
        replace(item, candidate_id="candidate-2", symbol="BETA") for item in first
    )
    report = UpstoxDuplicateOriginAuditEngine().build(
        (), observations=(*first, *second)
    )
    assert len(report.attributions) == 2
    assert all(item.cross_symbol_same_session for item in report.attributions)
    assert report.future_safe_deduplication_supportable


def test_bridge_report_keeps_identity_and_corporate_action_separate() -> None:
    first = _candidate(candidate_id="one")
    second = _candidate(candidate_id="two", corporate_action_required=True)
    providers = (
        replace(_provider(first), full_price_coverage=True),
        replace(_provider(second), full_price_coverage=True),
    )
    report = HistoricalIdentityBridgeEngine().build(
        manifest=_manifest((first, second)),
        upstox_dataset=_upstox_dataset(providers),
        identity_dataset=_identity_dataset(()),
        actual_authoritative_readiness=889,
    )
    assert report.provisional_upstox_matches == 2
    assert report.authoritative_identities == 0
    assert report.full_price_covered_identity_blocked_candidates == 2
    assert report.full_price_covered_corporate_action_blocked_candidates == 1
    assert report.projected_readiness_with_existing_evidence == 889
    assert report.projected_readiness_if_authority_supplied == 890
    assert report.conclusion is (
        IdentityAuditConclusion.AUTHORITATIVE_EXTERNAL_IDENTITY_SOURCE_REQUIRED
    )
    assert "PRODUCTION_INFLUENCE=false" in render_historical_identity_bridge_audit(
        report
    )


def test_full_population_report_replaces_stale_sample_warning() -> None:
    candidate = _candidate()
    evidence = replace(
        _provider(candidate),
        coverage_classification=UpstoxCoverageClassification.FULL_PRICE_COVERAGE,
        full_price_coverage=True,
        has_sufficient_raw_lookback=True,
        has_sufficient_pre_cutoff_lookback=True,
        has_sufficient_valid_lookback=True,
    )
    manifest = _manifest((candidate,))
    sample = HistoricalSourceSampleManifest(
        sample_version="sample-v1",
        source_manifest_version=manifest.manifest_version,
        population_count=1,
        requested_sample_size=1,
        records=(candidate,),
        stratum_counts=(),
        limitations=(),
        checksum="sample-checksum",
    )
    report = UpstoxHistoricalEvidenceReportEngine().build(
        manifest=manifest,
        sample=sample,
        dataset=_upstox_dataset((evidence,)),
    )
    rendered = "\n".join(render_upstox_evidence_report(report))
    assert "The full 1/1 manifest was observed" in rendered
    assert "unless the full manifest is tested" not in rendered


def test_filters_are_deterministic() -> None:
    candidate = _candidate()
    report = HistoricalIdentityBridgeEngine().build(
        manifest=_manifest((candidate,)),
        upstox_dataset=_upstox_dataset((_provider(candidate),)),
        identity_dataset=_identity_dataset(()),
    )
    selected = filter_identity_records(
        report.records,
        symbol="alphaold",
        status="PROVISIONAL_PROVIDER_SYMBOL_MATCH",
        source="UPSTOX_PROVISIONAL_OR_NONE",
        year=2020,
    )
    assert len(selected) == 1


def test_cli_identity_reports_are_read_only_and_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate()
    provider = replace(_provider(candidate), full_price_coverage=True)
    dataset = _upstox_dataset((provider,))
    bridge = HistoricalIdentityBridgeEngine().build(
        manifest=_manifest((candidate,)),
        upstox_dataset=dataset,
        identity_dataset=_identity_dataset(()),
        actual_authoritative_readiness=889,
    )
    bundle = HistoricalIdentityAuditBundle(
        bridge=bridge,
        metadata=UpstoxIdentityMetadataAuditEngine().build(dataset),
        duplicates=UpstoxDuplicateOriginAuditEngine().build((provider,)),
    )
    monkeypatch.setattr(cli_module, "_historical_identity_audit_bundle", lambda: bundle)
    for command, expected in (
        ("historical-identity-bridge-audit", "Authoritative Historical Identity"),
        ("historical-identity-unresolved", "Unresolved Clusters"),
        ("historical-identity-provisional", "Provisional Match Audit"),
        ("historical-identity-source-coverage", "Identity Source Coverage"),
        ("upstox-identity-metadata-audit", "Metadata Retention Audit"),
        ("upstox-duplicate-origin-audit", "Duplicate-Session Origin Audit"),
        ("historical-identity-readiness", "Reconstruction Readiness"),
    ):
        result = runner.invoke(app, ["replay", command])
        assert result.exit_code == 0
        assert expected in result.output
        assert "PRODUCTION_INFLUENCE=false" in result.output
        assert "access_token" not in result.output.lower()
