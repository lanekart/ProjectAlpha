from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.cli import app
from alpha.historical_replay.breakout_source_gap import BreakoutGapCause
from alpha.historical_replay.historical_source_evaluation import (
    HistoricalSourceEvaluationManifestRecord,
)
from alpha.historical_replay.nse_archive_proof import (
    NseArchiveAccessResult,
    NseArchiveFileEvidence,
    NseArchiveParser,
    NseArchiveSourceType,
    NseCorporateActionProofEngine,
    NseCorporateActionProofStatus,
    NseCorporateActionType,
    NseIdentityEventRecord,
    NseIdentityEventType,
    NseIdentityProofEngine,
    NseIdentityProofStatus,
    NseSecuritySchemaVersion,
    official_bhavcopy_url,
    validate_official_nse_url,
)
from alpha.historical_replay.nse_archive_proof_service import (
    NseArchiveAccessBlocked,
    NseArchiveAuthorizationRequired,
    NseArchiveClient,
    NseArchiveHttpResponse,
    NseArchiveProofRepository,
)
from alpha.historical_replay.upstox_historical_probe import (
    PRODUCTION_INFLUENCE,
    UpstoxHistoricalCandleValidator,
    UpstoxIdentityConfidence,
    UpstoxIdentityMatchMethod,
    UpstoxIdentityResolution,
    UpstoxIdentityStatus,
)

runner = CliRunner()


def _candidate(
    *,
    candidate_id: str = "candidate-1",
    symbol: str = "ALPHAOLD",
    candidate_date: date = date(2020, 6, 15),
    corporate_action: bool = False,
) -> HistoricalSourceEvaluationManifestRecord:
    return HistoricalSourceEvaluationManifestRecord(
        candidate_id=candidate_id,
        candidate_date=candidate_date,
        current_symbol=None,
        historical_symbol=symbol,
        permanent_identifier="INTERNAL-DIAGNOSTIC-ID",
        required_start_date=date(2019, 12, 1),
        required_end_date=date(2020, 6, 12),
        required_start_basis="test",
        minimum_bars_required=121,
        gap_cause=BreakoutGapCause.SYMBOL_IDENTITY_UNRESOLVED,
        corporate_action_requirement=corporate_action,
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
    series: str | None = "EQ",
    exchange_token: str | None = "12345",
):
    identity = UpstoxIdentityResolution(
        candidate_id=candidate.candidate_id,
        requested_historical_symbol=candidate.historical_symbol,
        matched_symbol=symbol or candidate.historical_symbol,
        isin=isin,
        instrument_key=(f"NSE_EQ|{isin}" if isin else "NSE_EQ|ALPHA"),
        match_method=UpstoxIdentityMatchMethod.UPSTOX_INSTRUMENT_SEARCH,
        match_confidence=UpstoxIdentityConfidence.MEDIUM,
        status=UpstoxIdentityStatus.RESOLVED_PROVISIONAL_FOR_PRICE_PROBE,
        active_status="ACTIVE_TO_SOURCE_END",
        historical_continuity_evidence="test",
        ambiguity_reason=None,
        price_probe_eligible=True,
        identity_confirmed=False,
        renamed_security=symbol is not None,
        inactive_security=False,
        provider_exchange="NSE",
        provider_segment="NSE_EQ",
        provider_series=series,
        provider_exchange_token=exchange_token,
        provider_security_type="EQUITY",
        provider_instrument_type="EQ",
        provider_metadata_source="TEST",
    )
    return UpstoxHistoricalCandleValidator().evaluate(candidate, identity)


def _zip_csv(text: str, member: str = "cm15JUN2020bhav.csv") -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, text)
    return target.getvalue()


def _evidence(
    payload: bytes,
    *,
    archive_date: date = date(2020, 6, 15),
    source_type: NseArchiveSourceType = NseArchiveSourceType.CM_BHAVCOPY,
    schema: NseSecuritySchemaVersion = (NseSecuritySchemaVersion.LEGACY_CM_BHAVCOPY_V1),
    filename: str = "bhavcopy_2020-06-15.zip",
) -> NseArchiveFileEvidence:
    return NseArchiveFileEvidence(
        source_type=source_type,
        official_url_pattern=official_bhavcopy_url(archive_date),
        archive_date=archive_date,
        filename=filename,
        archive_category="test",
        mime_type="application/zip",
        compression_format="ZIP",
        schema_version=schema,
        source_checksum=hashlib.sha256(payload).hexdigest(),
        retrieval_timestamp=None,
        access_result=NseArchiveAccessResult.LOCAL_CACHE_AVAILABLE,
        license_or_usage_notice="test",
        retention_restriction="test",
        redistribution_restriction="test",
    )


def _legacy_inspection(
    rows: str = (
        "ALPHAOLD,EQ,10,11,9,10.5,10.5,10,100,1000,15-JUN-2020,10,INE000A01001,\n"
    ),
    *,
    current_state_only: bool = False,
):
    payload = _zip_csv(
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,"
        "TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,\n" + rows
    )
    return NseArchiveParser().parse_security_file(
        payload,
        file_evidence=_evidence(payload),
        current_state_only=current_state_only,
    )


def test_dated_legacy_security_file_parsing() -> None:
    inspection = _legacy_inspection()
    assert inspection.schema_version is NseSecuritySchemaVersion.LEGACY_CM_BHAVCOPY_V1
    assert inspection.records[0].trading_symbol == "ALPHAOLD"
    assert inspection.records[0].security_series == "EQ"
    assert inspection.records[0].isin == "INE000A01001"
    assert inspection.deterministic_checksum is not None


def test_modern_mii_schema_change_is_normalized() -> None:
    payload = (
        b"TckrSymb,SctySrs,ISIN,FinInstrmId,FinInstrmNm,FinInstrmTp,"
        b"Listing_Date,PermittedToTrade\n"
        b"ALPHA,EQ,INE000A01001,12345,Alpha Limited,EQUITY,2020-01-01,1\n"
    )
    evidence = _evidence(
        payload,
        source_type=NseArchiveSourceType.CM_MII_SECURITY_FILE,
        schema=NseSecuritySchemaVersion.MII_CM_SECURITY_V1,
        filename="NSE_CM_security_15062020.csv",
    )
    inspection = NseArchiveParser().parse_security_file(
        payload,
        file_evidence=evidence,
    )
    record = inspection.records[0]
    assert record.trading_symbol == "ALPHA"
    assert record.exchange_security_identifier == "12345"
    assert record.company_or_security_name == "Alpha Limited"
    assert record.permitted_to_trade is True


def test_symbol_and_series_date_match_is_authoritative() -> None:
    result = NseIdentityProofEngine().resolve(
        _candidate(), provider=None, inspection=_legacy_inspection()
    )
    assert result.match_status is NseIdentityProofStatus.NSE_SYMBOL_SERIES_DATE_MATCH
    assert result.authoritative


def test_isin_interval_match_bridges_provider() -> None:
    candidate = _candidate()
    result = NseIdentityProofEngine().resolve(
        candidate,
        provider=_provider(candidate),
        inspection=_legacy_inspection(),
    )
    assert result.match_status is NseIdentityProofStatus.NSE_ISIN_INTERVAL_MATCH
    assert result.provider_bridge_established


def test_exchange_identifier_match_has_highest_authority() -> None:
    payload = b"SYMBOL,SERIES,ISIN,SECURITY_ID\nALPHAOLD,EQ,INE000A01001,12345\n"
    inspection = NseArchiveParser().parse_security_file(
        payload,
        file_evidence=_evidence(
            payload,
            schema=NseSecuritySchemaVersion.MII_CM_SECURITY_V1,
            filename="security.csv",
        ),
    )
    candidate = _candidate()
    result = NseIdentityProofEngine().resolve(
        candidate,
        provider=_provider(candidate),
        inspection=inspection,
    )
    assert result.match_status is NseIdentityProofStatus.NSE_PERMANENT_ID_INTERVAL_MATCH


def test_current_state_only_record_is_rejected_as_authority() -> None:
    result = NseIdentityProofEngine().resolve(
        _candidate(),
        provider=None,
        inspection=_legacy_inspection(current_state_only=True),
    )
    assert result.match_status is NseIdentityProofStatus.NSE_CURRENT_STATE_ONLY
    assert not result.authoritative


@pytest.mark.parametrize(
    ("listing", "delisting"),
    (("2020-06-16", ""), ("", "2020-06-14")),
)
def test_listing_or_delisting_conflict_blocks_interval(
    listing: str,
    delisting: str,
) -> None:
    payload = (
        "SYMBOL,SERIES,ISIN,LISTING_DATE,DELISTING_DATE\n"
        f"ALPHAOLD,EQ,INE000A01001,{listing},{delisting}\n"
    ).encode()
    inspection = NseArchiveParser().parse_security_file(
        payload,
        file_evidence=_evidence(payload, filename="security.csv"),
    )
    result = NseIdentityProofEngine().resolve(
        _candidate(), provider=None, inspection=inspection
    )
    assert result.match_status is NseIdentityProofStatus.NSE_INTERVAL_AMBIGUOUS


def test_suspended_security_requires_manual_review() -> None:
    payload = b"SYMBOL,SERIES,ISIN,SUSPENSION_INDICATOR\nALPHAOLD,EQ,INE000A01001,1\n"
    inspection = NseArchiveParser().parse_security_file(
        payload,
        file_evidence=_evidence(payload, filename="security.csv"),
    )
    result = NseIdentityProofEngine().resolve(
        _candidate(), provider=None, inspection=inspection
    )
    assert result.match_status is NseIdentityProofStatus.NSE_MANUAL_REVIEW_REQUIRED


def test_rename_chain_is_authoritative() -> None:
    candidate = _candidate()
    event = NseIdentityEventRecord(
        event_type=NseIdentityEventType.SYMBOL_CHANGE,
        effective_date=date(2021, 1, 1),
        old_symbol="ALPHAOLD",
        new_symbol="ALPHANEW",
        old_isin="INE000A01001",
        new_isin="INE000A01001",
        predecessor_security_id=None,
        successor_security_id="12345",
        circular_reference="NSE/CML/1",
        source_checksum="checksum",
    )
    result = NseIdentityProofEngine().resolve(
        candidate,
        provider=_provider(candidate, symbol="ALPHANEW"),
        inspection=None,
        identity_events=(event,),
    )
    assert result.match_status is NseIdentityProofStatus.NSE_RENAME_CHAIN_MATCH


@pytest.mark.parametrize(
    "event_type",
    (NseIdentityEventType.MERGER, NseIdentityEventType.DEMERGER),
)
def test_succession_chain_supports_merger_and_demerger(
    event_type: NseIdentityEventType,
) -> None:
    candidate = _candidate()
    event = NseIdentityEventRecord(
        event_type=event_type,
        effective_date=date(2021, 1, 1),
        old_symbol="ALPHAOLD",
        new_symbol="ALPHANEW",
        old_isin="INE000A01001",
        new_isin="INE000B01001",
        predecessor_security_id="OLD-1",
        successor_security_id="NEW-1",
        circular_reference="NSE/CML/2",
        source_checksum="checksum",
    )
    result = NseIdentityProofEngine().resolve(
        candidate,
        provider=_provider(candidate, symbol="ALPHANEW", isin="INE000B01001"),
        inspection=None,
        identity_events=(event,),
    )
    assert result.match_status is NseIdentityProofStatus.NSE_SUCCESSION_CHAIN_MATCH


def test_symbol_reuse_conflict_never_becomes_authoritative() -> None:
    inspection = _legacy_inspection(
        "ALPHAOLD,EQ,10,11,9,10,10,10,100,1000,15-JUN-2020,10,INE000A01001,\n"
        "ALPHAOLD,EQ,10,11,9,10,10,10,100,1000,15-JUN-2020,10,INE000B01001,\n"
    )
    result = NseIdentityProofEngine().resolve(
        _candidate(), provider=None, inspection=inspection
    )
    assert result.match_status is NseIdentityProofStatus.NSE_SOURCE_CONFLICT
    assert not result.authoritative


def test_same_isin_across_series_is_interval_ambiguous() -> None:
    inspection = _legacy_inspection(
        "ALPHAOLD,BL,10,11,9,10,10,10,100,1000,15-JUN-2020,10,"
        "INE000A01001,\n"
        "ALPHAOLD,EQ,10,11,9,10,10,10,100,1000,15-JUN-2020,10,"
        "INE000A01001,\n"
    )
    result = NseIdentityProofEngine().resolve(
        _candidate(), provider=None, inspection=inspection
    )
    assert result.match_status is NseIdentityProofStatus.NSE_INTERVAL_AMBIGUOUS
    assert not result.authoritative


def test_missing_archive_file_is_explicit() -> None:
    result = NseIdentityProofEngine().resolve(
        _candidate(), provider=None, inspection=None
    )
    assert result.match_status is NseIdentityProofStatus.NSE_ARCHIVE_FILE_MISSING


def test_malformed_archive_is_rejected() -> None:
    payload = b"PK\x03\x04not-a-real-zip"
    with pytest.raises(ValueError, match="malformed NSE ZIP"):
        NseArchiveParser().parse_security_file(
            payload,
            file_evidence=_evidence(payload),
        )


def test_source_checksum_mismatch_is_rejected() -> None:
    payload = b"SYMBOL,SERIES\nALPHAOLD,EQ\n"
    evidence = replace(
        _evidence(payload, filename="security.csv"), source_checksum="bad"
    )
    with pytest.raises(ValueError, match="checksum"):
        NseArchiveParser().parse_security_file(payload, file_evidence=evidence)


def test_split_and_bonus_fields_are_parsed() -> None:
    payload = (
        b"SYMBOL,SERIES,PURPOSE,EFFECTIVE_DATE,CIRCULAR_REFERENCE\n"
        b"ALPHAOLD,EQ,Stock Split From Rs 10 To Rs 2,2020-06-10,NSE/CML/10\n"
        b"BETA,EQ,Bonus 1:1,2020-06-10,NSE/CML/11\n"
    )
    actions = NseArchiveParser().parse_corporate_actions(
        payload, filename="corporate_actions.csv"
    )
    assert actions[0].action_type is NseCorporateActionType.SPLIT
    assert actions[0].old_face_value == 10
    assert actions[0].new_face_value == 2
    assert actions[1].action_type is NseCorporateActionType.BONUS
    assert actions[1].bonus_ratio == "1:1"


@pytest.mark.parametrize("action_type", ("MERGER", "DEMERGER"))
def test_merger_and_demerger_linkage_is_complete(action_type: str) -> None:
    candidate = _candidate(corporate_action=True)
    payload = (
        "SYMBOL,SERIES,ACTION_TYPE,PURPOSE,EFFECTIVE_DATE,"
        "PREDECESSOR_SECURITY_ID,SUCCESSOR_SECURITY_ID,CIRCULAR_REFERENCE\n"
        f"ALPHAOLD,EQ,{action_type},{action_type.title()},2020-06-10,OLD,NEW,"
        "NSE/CML/12\n"
    ).encode()
    actions = NseArchiveParser().parse_corporate_actions(
        payload, filename="corporate_actions.csv"
    )
    identity = NseIdentityProofEngine().resolve(
        candidate, provider=None, inspection=_legacy_inspection()
    )
    report = NseCorporateActionProofEngine().build(
        (candidate,),
        actions=actions,
        identity_records={candidate.candidate_id: identity},
    )
    assert report.complete_cases == 1
    assert (
        report.records[0].status
        is NseCorporateActionProofStatus.NSE_CA_EVIDENCE_COMPLETE
    )


def test_corporate_action_not_found_does_not_clear_adjustment_gate() -> None:
    candidate = _candidate(corporate_action=True)
    identity = NseIdentityProofEngine().resolve(
        candidate, provider=None, inspection=_legacy_inspection()
    )
    report = NseCorporateActionProofEngine().build(
        (candidate,),
        actions=(),
        identity_records={candidate.candidate_id: identity},
    )
    assert report.not_found == 1
    assert not report.records[0].price_adjustment_authority_established


class _QueueTransport:
    def __init__(self, responses: Sequence[NseArchiveHttpResponse]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def get(self, url: str, *, timeout_seconds: int) -> NseArchiveHttpResponse:
        del url, timeout_seconds
        self.calls += 1
        return self.responses.pop(0)


def _response(
    status: int,
    *,
    retry_after: str | None = None,
) -> NseArchiveHttpResponse:
    headers = (("Retry-After", retry_after),) if retry_after is not None else ()
    return NseArchiveHttpResponse(status=status, headers=headers, body=b"payload")


def test_client_throttles_consecutive_requests() -> None:
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    client = NseArchiveClient(
        transport=_QueueTransport((_response(200), _response(200))),
        sleeper=sleep,
        monotonic=lambda: now[0],
        minimum_interval_seconds=2,
    )
    client.fetch(official_bhavcopy_url(date(2020, 6, 15)), authorization_reference="A")
    client.fetch(official_bhavcopy_url(date(2020, 6, 16)), authorization_reference="A")
    assert sleeps == [2.0]


def test_retry_after_is_honored() -> None:
    sleeps: list[float] = []
    transport = _QueueTransport((_response(429, retry_after="7"), _response(200)))
    client = NseArchiveClient(
        transport=transport,
        sleeper=sleeps.append,
        minimum_interval_seconds=0,
    )
    response = client.fetch(
        official_bhavcopy_url(date(2020, 6, 15)), authorization_reference="A"
    )
    assert response.status == 200
    assert sleeps == [7.0]
    assert transport.calls == 2


def test_access_blocked_stops_without_circumvention() -> None:
    client = NseArchiveClient(
        transport=_QueueTransport((_response(403),)),
        minimum_interval_seconds=0,
    )
    with pytest.raises(NseArchiveAccessBlocked, match="HTTP 403"):
        client.fetch(
            official_bhavcopy_url(date(2020, 6, 15)),
            authorization_reference="A",
        )


def test_missing_authorization_blocks_before_network() -> None:
    transport = _QueueTransport((_response(200),))
    client = NseArchiveClient(transport=transport, minimum_interval_seconds=0)
    with pytest.raises(NseArchiveAuthorizationRequired):
        client.fetch(
            official_bhavcopy_url(date(2020, 6, 15)),
            authorization_reference=None,
        )
    assert transport.calls == 0


def test_only_official_nse_domains_are_allowed() -> None:
    with pytest.raises(ValueError, match="official NSE domains"):
        validate_official_nse_url("https://example.com/archive.zip")


def test_repository_missing_archive_does_not_write(tmp_path: Path) -> None:
    repository = NseArchiveProofRepository(
        cache_root=tmp_path / "cache",
        raw_archive=tmp_path / "raw",
        extracted_archive=tmp_path / "extracted",
    )
    evidence, inspection = repository.load_bhavcopy(date(2020, 6, 15))
    assert evidence.access_result is NseArchiveAccessResult.FILE_MISSING
    assert inspection is None
    assert not (tmp_path / "cache").exists()


def test_cli_commands_are_registered_and_require_no_live_flag_for_offline_help() -> (
    None
):
    commands = (
        "nse-archive-source-discovery",
        "nse-security-file-inspect",
        "nse-identity-proof",
        "nse-corporate-action-proof",
        "nse-archive-coverage",
        "nse-archive-readiness",
    )
    for command in commands:
        result = runner.invoke(app, ["replay", command, "--help"], terminal_width=200)
        assert result.exit_code == 0
        assert "--live" in result.stdout


def test_diagnostic_models_never_gain_production_influence() -> None:
    result = NseIdentityProofEngine().resolve(
        _candidate(), provider=None, inspection=_legacy_inspection()
    )
    assert PRODUCTION_INFLUENCE is False
    assert result.production_influence is False
