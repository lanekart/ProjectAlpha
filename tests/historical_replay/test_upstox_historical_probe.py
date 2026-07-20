from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from email.message import Message
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import alpha.cli as cli_module
from alpha.cli import app
from alpha.historical_replay.breakout_source_gap import (
    BreakoutGapCause,
    BreakoutGapRecoveryClass,
)
from alpha.historical_replay.historical_source_evaluation import (
    HISTORICAL_SOURCE_MANIFEST_VERSION,
    HistoricalSourceEvaluationManifest,
    HistoricalSourceEvaluationManifestRecord,
    deterministic_historical_source_sample,
)
from alpha.historical_replay.historical_source_evaluation_service import (
    build_project_historical_source_evaluation,
)
from alpha.historical_replay.upstox_historical_probe import (
    PRODUCTION_INFLUENCE,
    UPSTOX_INSTRUMENT_SEARCH_DEFAULT_RECORDS,
    UpstoxAdjustmentAuditEngine,
    UpstoxAdjustmentStatus,
    UpstoxAnalyticsTokenConfig,
    UpstoxAuthProbeStatus,
    UpstoxCandle,
    UpstoxCandleBatch,
    UpstoxCorporateActionCase,
    UpstoxCorporateActionStatus,
    UpstoxCoverageClassification,
    UpstoxHistoricalCandidateEvidence,
    UpstoxHistoricalCandleValidator,
    UpstoxHistoricalEvidenceDataset,
    UpstoxHistoricalEvidenceReportEngine,
    UpstoxHistoricalEvidenceRepository,
    UpstoxIdentityHint,
    UpstoxIdentityMatchMethod,
    UpstoxIdentityResolution,
    UpstoxIdentityResolver,
    UpstoxIdentityStatus,
    UpstoxInstrumentRecord,
    UpstoxOperationalMetrics,
    UpstoxProbeCredentialStatus,
    UpstoxProbeErrorCategory,
    UpstoxProbeHttpError,
    UpstoxProbeHttpResponse,
    UpstoxReadOnlyHistoricalClient,
    UpstoxSeriesDefect,
    UrlLibUpstoxHistoricalProbeTransport,
    export_upstox_evidence_csv,
    export_upstox_evidence_json,
)
from alpha.historical_replay.upstox_historical_probe_service import (
    UpstoxHistoricalProbeService,
)
from alpha.historical_replay.upstox_series_integrity import (
    UpstoxSeriesIntegrityEngine,
    export_upstox_series_integrity_csv,
    render_upstox_series_integrity,
)

runner = CliRunner()

_PROJECT_REPLAY_CORPUS_AVAILABLE = (
    Path(".alpha/breakout_reference_dataset_v1.json").is_file()
    and Path(".alpha/candidate_learning_ledger.json").is_file()
)
IST = timezone(timedelta(hours=5, minutes=30))


class ScriptedTransport:
    def __init__(
        self, responses: Sequence[UpstoxProbeHttpResponse | Exception]
    ) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get_json(
        self, url: str, headers: dict[str, str] | Any
    ) -> UpstoxProbeHttpResponse:
        self.calls.append((url, dict(headers)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _credential() -> UpstoxAnalyticsTokenConfig:
    return UpstoxAnalyticsTokenConfig(token="unit-test-only-credential")


def _response(payload: Mapping[str, Any]) -> UpstoxProbeHttpResponse:
    return UpstoxProbeHttpResponse(
        payload=payload,
        http_status=200,
        diagnostic_headers={"Content-Type": "application/json"},
    )


def _search_response(
    symbol: str = "OLDCO",
    *,
    key: str = "NSE_EQ|INE000A01001",
    isin: str = "INE000A01001",
) -> UpstoxProbeHttpResponse:
    return _response(
        {
            "status": "success",
            "data": [
                {
                    "instrument_key": key,
                    "trading_symbol": symbol,
                    "isin": isin,
                    "exchange": "NSE",
                    "segment": "NSE_EQ",
                }
            ],
        }
    )


def _record(
    *,
    candidate_id: str = "candidate-a",
    symbol: str = "OLDCO",
    current_symbol: str | None = None,
    candidate_date: date = date(2016, 7, 11),
    continuity: str = "ACTIVE_TO_SOURCE_END",
    corporate_action: bool = False,
) -> HistoricalSourceEvaluationManifestRecord:
    return HistoricalSourceEvaluationManifestRecord(
        candidate_id=candidate_id,
        candidate_date=candidate_date,
        current_symbol=current_symbol,
        historical_symbol=symbol,
        permanent_identifier="manifest-internal-id",
        required_start_date=candidate_date - timedelta(days=190),
        required_end_date=candidate_date - timedelta(days=1),
        required_start_basis="test",
        minimum_bars_required=121,
        gap_cause=(
            BreakoutGapCause.CORPORATE_ACTION_AMBIGUITY
            if corporate_action
            else BreakoutGapCause.INSUFFICIENT_PRE_CANDIDATE_LOOKBACK
        ),
        corporate_action_requirement=corporate_action,
        identity_uncertainty=True,
        recovery_population=(
            BreakoutGapRecoveryClass.REQUIRES_NEW_EXTERNAL_SOURCE.value
        ),
        replay_year=candidate_date.year,
        sector="UNKNOWN",
        market_regime="NEUTRAL",
        setup_type="MOMENTUM CONTINUATION",
        liquidity_proxy=Decimal("0.5"),
        continuity_status=continuity,
    )


def _instrument(
    symbol: str = "OLDCO",
    *,
    key: str = "NSE_EQ|INE000A01001",
    isin: str | None = "INE000A01001",
    source: str = "INSTRUMENT_SEARCH",
) -> UpstoxInstrumentRecord:
    return UpstoxInstrumentRecord(
        instrument_key=key,
        trading_symbol=symbol,
        isin=isin,
        exchange="NSE",
        segment="NSE_EQ",
        instrument_type="EQ",
        source=source,
    )


def _candles(
    count: int,
    *,
    end: date = date(2016, 7, 10),
    tz: timezone = IST,
    close: Decimal = Decimal("100"),
) -> tuple[UpstoxCandle, ...]:
    start = end - timedelta(days=count - 1)
    return tuple(
        UpstoxCandle(
            observed_at=datetime.combine(
                start + timedelta(days=index), datetime.min.time(), tz
            ),
            open_price=close,
            high_price=close + Decimal("2"),
            low_price=close - Decimal("2"),
            close_price=close,
            volume=Decimal("1000"),
        )
        for index in range(count)
    )


def _batch(candles: tuple[UpstoxCandle, ...]) -> UpstoxCandleBatch:
    return UpstoxCandleBatch(
        candles=candles,
        malformed_rows=0,
        http_status=200,
        response_checksum="response-checksum",
    )


def _identity(
    record: HistoricalSourceEvaluationManifestRecord,
) -> UpstoxIdentityResolution:
    return UpstoxIdentityResolver().resolve(
        record,
        official_instruments=(_instrument(record.historical_symbol),),
        hint=UpstoxIdentityHint(
            effective_historical_symbol=record.historical_symbol,
            effective_from=record.required_start_date,
            effective_to=record.candidate_date,
        ),
    )


def _manifest_for(
    records: tuple[HistoricalSourceEvaluationManifestRecord, ...],
) -> HistoricalSourceEvaluationManifest:
    return HistoricalSourceEvaluationManifest(
        manifest_version=HISTORICAL_SOURCE_MANIFEST_VERSION,
        records=records,
        source_required_count=len(records),
        recovery_uncertain_count=0,
        unique_symbols=len({item.historical_symbol for item in records}),
        earliest_required_date=min(item.required_start_date for item in records),
        latest_required_date=max(item.required_end_date for item in records),
        checksum="test-manifest-checksum",
    )


def _dataset_for(
    records: tuple[UpstoxHistoricalCandidateEvidence, ...],
) -> UpstoxHistoricalEvidenceDataset:
    return UpstoxHistoricalEvidenceDataset(
        dataset_version="upstox-historical-evidence-dataset-v1",
        probe_version="upstox-historical-evidence-probe-v1",
        source_manifest_version=HISTORICAL_SOURCE_MANIFEST_VERSION,
        source_manifest_checksum="test-manifest-checksum",
        sample_checksum="test-sample-checksum",
        scope="SAMPLE",
        credential_status=UpstoxProbeCredentialStatus.CONFIGURED_REDACTED,
        authentication_status=UpstoxAuthProbeStatus.TOKEN_ACCEPTED,
        records=records,
    )


def _provider_error(
    category: UpstoxProbeErrorCategory,
    *,
    message: str = "provider rejection",
) -> UpstoxProbeHttpError:
    return UpstoxProbeHttpError(
        category=category,
        http_status=401 if "AUTH" in category.value else 503,
        provider_error_code="UDAPI_TEST",
        sanitized_message=message,
    )


def test_token_absent_fails_without_network() -> None:
    transport = ScriptedTransport([])
    client = UpstoxReadOnlyHistoricalClient(
        config=UpstoxAnalyticsTokenConfig(token=None), transport=transport
    )
    result = client.authentication_probe(live=True)
    assert result.status is UpstoxAuthProbeStatus.TOKEN_NOT_CONFIGURED
    assert (
        result.credential_status
        is UpstoxProbeCredentialStatus.CREDENTIALS_NOT_CONFIGURED
    )
    assert transport.calls == []


def test_token_accepted_uses_only_two_read_only_gets() -> None:
    transport = ScriptedTransport(
        [_search_response("NIFTY 50"), _response({"data": {"candles": []}})]
    )
    client = UpstoxReadOnlyHistoricalClient(
        config=_credential(), transport=transport, minimum_request_interval=0
    )
    result = client.authentication_probe(live=True)
    assert result.status is UpstoxAuthProbeStatus.TOKEN_ACCEPTED
    assert len(transport.calls) == 2
    assert all(
        call[0].startswith("https://api.upstox.com/") for call in transport.calls
    )
    assert all(call[1]["Accept"] == "application/json" for call in transport.calls)
    assert all(call[1]["Connection"] == "close" for call in transport.calls)
    search_query = urllib.parse.parse_qs(
        urllib.parse.urlparse(transport.calls[0][0]).query
    )
    assert search_query["records"] == ["10"]
    assert UPSTOX_INSTRUMENT_SEARCH_DEFAULT_RECORDS == 10
    assert result.account_endpoint_called is False
    assert result.order_endpoint_called is False
    assert result.production_influence is False


@pytest.mark.parametrize("records", [1, 10, 30])
def test_instrument_search_accepts_documented_page_sizes(records: int) -> None:
    transport = ScriptedTransport([_search_response()])
    client = UpstoxReadOnlyHistoricalClient(
        config=_credential(), transport=transport, minimum_request_interval=0
    )
    client.search_instruments("OLDCO", records=records)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(transport.calls[0][0]).query)
    assert query["records"] == [str(records)]


@pytest.mark.parametrize("records", [0, 31])
def test_instrument_search_rejects_invalid_explicit_page_sizes(records: int) -> None:
    transport = ScriptedTransport([])
    client = UpstoxReadOnlyHistoricalClient(
        config=_credential(), transport=transport, minimum_request_interval=0
    )
    with pytest.raises(ValueError, match="between 1 and 30"):
        client.search_instruments("OLDCO", records=records)
    assert transport.calls == []


def test_udapi1173_is_a_page_size_request_error_and_redacts_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential = "sensitive-page-size-test-value"
    body = json.dumps(
        {
            "errors": [
                {
                    "errorCode": "UDAPI1173",
                    "message": f"Page records exceeds limit. {credential}",
                }
            ]
        }
    ).encode()
    error = urllib.error.HTTPError(
        url="https://api.upstox.com/v2/instruments/search",
        code=400,
        msg="bad request",
        hdrs=Message(),
        fp=io.BytesIO(body),
    )

    def reject(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr("urllib.request.urlopen", reject)
    client = UpstoxReadOnlyHistoricalClient(
        config=UpstoxAnalyticsTokenConfig(token=credential),
        minimum_request_interval=0,
    )
    result = client.authentication_probe(live=True)
    assert result.status is UpstoxAuthProbeStatus.PROBE_ERROR
    assert result.provider_error_code == "UDAPI1173"
    assert "Page records exceeds limit." in result.reason
    assert credential not in result.reason
    assert result.account_endpoint_called is False
    assert result.order_endpoint_called is False
    assert result.production_influence is False


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        (
            UpstoxProbeErrorCategory.AUTHENTICATION_FAILED,
            UpstoxAuthProbeStatus.TOKEN_REJECTED,
        ),
        (UpstoxProbeErrorCategory.TOKEN_EXPIRED, UpstoxAuthProbeStatus.TOKEN_EXPIRED),
        (
            UpstoxProbeErrorCategory.ENDPOINT_FORBIDDEN,
            UpstoxAuthProbeStatus.ENDPOINT_FORBIDDEN,
        ),
    ],
)
def test_authentication_rejections_are_classified(
    category: UpstoxProbeErrorCategory,
    expected: UpstoxAuthProbeStatus,
) -> None:
    client = UpstoxReadOnlyHistoricalClient(
        config=_credential(),
        transport=ScriptedTransport([_provider_error(category)]),
        minimum_request_interval=0,
    )
    assert client.authentication_probe(live=True).status is expected


def test_http_exception_redacts_analytics_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential = "sensitive-unit-value"
    body = json.dumps({"errors": [{"message": f"rejected {credential}"}]}).encode()
    error = urllib.error.HTTPError(
        url="https://api.upstox.com/v2/instruments/search",
        code=401,
        msg="unauthorized",
        hdrs=Message(),
        fp=io.BytesIO(body),
    )

    def reject(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr("urllib.request.urlopen", reject)
    with pytest.raises(UpstoxProbeHttpError) as captured:
        UrlLibUpstoxHistoricalProbeTransport().get_json(
            "https://api.upstox.com/v2/instruments/search?query=x",
            {"Authorization": f"Bearer {credential}"},
        )
    assert credential not in str(captured.value)
    assert "Bearer" not in str(captured.value)


def test_order_endpoint_is_rejected_before_network() -> None:
    with pytest.raises(UpstoxProbeHttpError) as captured:
        UrlLibUpstoxHistoricalProbeTransport().get_json(
            "https://api.upstox.com/v2/order/place", {}
        )
    assert captured.value.category is UpstoxProbeErrorCategory.ENDPOINT_NOT_ALLOWED


def test_credential_model_is_immutable_and_hides_repr() -> None:
    config = _credential()
    assert "unit-test-only" not in repr(config)
    with pytest.raises(FrozenInstanceError):
        config.token = "replacement"  # type: ignore[misc]


def test_isin_resolution_is_authoritative() -> None:
    result = UpstoxIdentityResolver().resolve(
        _record(),
        official_instruments=(_instrument(),),
        hint=UpstoxIdentityHint(isin="INE000A01001"),
    )
    assert result.match_method is UpstoxIdentityMatchMethod.ISIN
    assert result.identity_confirmed is True


def test_historical_symbol_with_effective_interval_is_authoritative() -> None:
    record = _record()
    result = _identity(record)
    assert result.status is UpstoxIdentityStatus.RESOLVED_AUTHORITATIVE
    assert (
        result.match_method
        is UpstoxIdentityMatchMethod.HISTORICAL_SYMBOL_EFFECTIVE_INTERVAL
    )


def test_search_only_historical_symbol_is_provisional_for_price_probe() -> None:
    result = UpstoxIdentityResolver().resolve(
        _record(), search_response=_search_response().payload
    )
    assert result.price_probe_eligible is True
    assert result.identity_confirmed is False
    assert result.status is UpstoxIdentityStatus.RESOLVED_PROVISIONAL_FOR_PRICE_PROBE


def test_current_symbol_only_is_rejected() -> None:
    record = _record(symbol="OLDCO", current_symbol="NEWCO")
    result = UpstoxIdentityResolver().resolve(
        record, search_response=_search_response("NEWCO").payload
    )
    assert result.status is UpstoxIdentityStatus.CURRENT_SYMBOL_ONLY_REJECTED
    assert result.price_probe_eligible is False


def test_renamed_and_inactive_security_flags_are_preserved() -> None:
    record = _record(continuity="SOURCE_CONTINUITY_ENDED_BEFORE_SOURCE_END")
    result = UpstoxIdentityResolver().resolve(
        record,
        official_instruments=(_instrument(),),
        hint=UpstoxIdentityHint(
            effective_historical_symbol="OLDCO",
            effective_to=record.candidate_date,
            renamed_security=True,
        ),
    )
    assert result.renamed_security is True
    assert result.inactive_security is True


@pytest.mark.parametrize("duplicate_keys", [("key-1", "key-2"), ("key-1", "key-1")])
def test_duplicate_or_ambiguous_matches_are_not_fuzzy_authority(
    duplicate_keys: tuple[str, str],
) -> None:
    instruments = tuple(
        _instrument(key=key, isin=None, source="OFFICIAL_INSTRUMENT_FILE")
        for key in duplicate_keys
    )
    result = UpstoxIdentityResolver().resolve(
        _record(), official_instruments=instruments
    )
    if duplicate_keys[0] == duplicate_keys[1]:
        assert result.identity_confirmed is False
    else:
        assert result.status is UpstoxIdentityStatus.AMBIGUOUS


def test_instrument_not_found_is_explicit() -> None:
    result = UpstoxIdentityResolver().resolve(_record())
    assert result.status is UpstoxIdentityStatus.INSTRUMENT_NOT_FOUND


def test_exact_121_pre_candidate_bars_are_full_price_coverage() -> None:
    record = _record()
    result = UpstoxHistoricalCandleValidator().evaluate(
        record, _identity(record), batch=_batch(_candles(121))
    )
    assert result.usable_pre_candidate_bars == 121
    assert result.sufficient_lookback is True
    assert (
        result.coverage_classification
        is UpstoxCoverageClassification.FULL_PRICE_COVERAGE
    )


def test_partial_lookback_is_not_full() -> None:
    record = _record()
    result = UpstoxHistoricalCandleValidator().evaluate(
        record, _identity(record), batch=_batch(_candles(80))
    )
    assert (
        result.coverage_classification
        is UpstoxCoverageClassification.PARTIAL_PRICE_COVERAGE
    )


@pytest.mark.parametrize(
    ("candidate_date", "count", "sufficient"),
    [(date(2016, 7, 11), 121, True), (date(2016, 7, 11), 40, False)],
)
def test_2016_history_availability_is_observed_not_inferred(
    candidate_date: date, count: int, sufficient: bool
) -> None:
    record = _record(candidate_date=candidate_date)
    result = UpstoxHistoricalCandleValidator().evaluate(
        record,
        _identity(record),
        batch=_batch(_candles(count, end=record.required_end_date)),
    )
    assert result.sufficient_lookback is sufficient


def test_duplicate_bars_make_series_invalid() -> None:
    record = _record()
    candles = _candles(121)
    result = UpstoxHistoricalCandleValidator().evaluate(
        record, _identity(record), batch=_batch((*candles, candles[-1]))
    )
    assert result.duplicate_sessions == 1
    assert result.coverage_classification is UpstoxCoverageClassification.INVALID_SERIES


def test_authoritative_calendar_identifies_multi_session_gap() -> None:
    record = _record()
    candles = _candles(121)
    sessions = tuple(item.observed_at.date() for item in candles)
    result = UpstoxHistoricalCandleValidator().evaluate(
        record,
        _identity(record),
        batch=_batch(candles[2:]),
        exchange_sessions=sessions,
    )
    assert result.missing_sessions == 2
    assert (
        result.coverage_classification
        is UpstoxCoverageClassification.MULTI_SESSION_GAPS
    )


def test_missing_sessions_remain_unavailable_without_exchange_calendar() -> None:
    record = _record()
    result = UpstoxHistoricalCandleValidator().evaluate(
        record, _identity(record), batch=_batch(_candles(119))
    )
    assert result.missing_sessions is None


@pytest.mark.parametrize("problem", ["ohlc", "volume", "timezone"])
def test_invalid_ohlc_negative_volume_and_timezone_are_detected(problem: str) -> None:
    record = _record()
    candles = list(_candles(121))
    if problem == "ohlc":
        candles[-1] = replace(candles[-1], low_price=Decimal("105"))
    elif problem == "volume":
        candles[-1] = replace(candles[-1], volume=Decimal("-1"))
    else:
        candles[-1] = replace(
            candles[-1], observed_at=candles[-1].observed_at.astimezone(UTC)
        )
    result = UpstoxHistoricalCandleValidator().evaluate(
        record, _identity(record), batch=_batch(tuple(candles))
    )
    assert result.coverage_classification is UpstoxCoverageClassification.INVALID_SERIES


def test_121_raw_rows_can_leave_fewer_than_121_integrity_valid_rows() -> None:
    record = _record()
    candles = list(_candles(121))
    candles[-1] = replace(candles[-1], low_price=Decimal("105"))
    result = UpstoxHistoricalCandleValidator().evaluate(
        record, _identity(record), batch=_batch(tuple(candles))
    )
    assert result.raw_bars_returned == 121
    assert result.pre_cutoff_bars == 121
    assert result.normalized_bars == 121
    assert result.integrity_valid_bars == 120
    assert result.rejected_bars == 1
    assert result.has_sufficient_raw_lookback is True
    assert result.has_sufficient_valid_lookback is False
    assert result.full_price_coverage is False
    assert result.primary_series_defect is UpstoxSeriesDefect.INVALID_OHLC_RELATIONSHIP
    assert (
        UpstoxSeriesDefect.INSUFFICIENT_VALID_BARS_AFTER_FILTERING
        in result.secondary_series_defects
    )


def test_121_pre_cutoff_rows_with_duplicate_session_are_invalid() -> None:
    record = _record()
    candles = _candles(120)
    result = UpstoxHistoricalCandleValidator().evaluate(
        record, _identity(record), batch=_batch((*candles, candles[-1]))
    )
    assert result.raw_bars_returned == 121
    assert result.pre_cutoff_bars == 121
    assert result.normalized_bars == 121
    assert result.integrity_valid_bars == 120
    assert result.primary_series_defect is UpstoxSeriesDefect.DUPLICATE_SESSION
    assert result.coverage_classification is UpstoxCoverageClassification.INVALID_SERIES
    assert result.full_price_coverage is False


@pytest.mark.parametrize(
    ("count", "expected_status", "full"),
    [
        (121, UpstoxCoverageClassification.FULL_PRICE_COVERAGE, True),
        (120, UpstoxCoverageClassification.PARTIAL_PRICE_COVERAGE, False),
    ],
)
def test_integrity_valid_bar_boundary_is_explicit(
    count: int,
    expected_status: UpstoxCoverageClassification,
    full: bool,
) -> None:
    record = _record()
    result = UpstoxHistoricalCandleValidator().evaluate(
        record, _identity(record), batch=_batch(_candles(count))
    )
    assert result.integrity_valid_bars == count
    assert result.has_sufficient_valid_lookback is full
    assert result.coverage_classification is expected_status
    assert result.full_price_coverage is full


def test_defect_precedence_is_deterministic() -> None:
    record = _record()
    candles = list(_candles(120))
    defective = replace(
        candles[-1],
        low_price=Decimal("0"),
        volume=Decimal("-1"),
    )
    result = UpstoxHistoricalCandleValidator().evaluate(
        record,
        _identity(record),
        batch=_batch((*candles[:-1], defective, defective)),
    )
    assert result.primary_series_defect is UpstoxSeriesDefect.NON_POSITIVE_PRICE
    assert result.secondary_series_defects[:2] == (
        UpstoxSeriesDefect.NEGATIVE_VOLUME,
        UpstoxSeriesDefect.DUPLICATE_SESSION,
    )


def test_report_uses_terminal_full_coverage_for_denominator_and_years() -> None:
    record_full = _record(candidate_id="full-2016", symbol="FULL16")
    record_invalid = _record(candidate_id="invalid-2016", symbol="BAD16")
    record_later = _record(
        candidate_id="full-2017",
        symbol="FULL17",
        candidate_date=date(2017, 7, 11),
    )
    full_2016 = UpstoxHistoricalCandleValidator().evaluate(
        record_full,
        _identity(record_full),
        batch=_batch(_candles(121, end=record_full.required_end_date)),
    )
    invalid_rows = _candles(121, end=record_invalid.required_end_date)
    invalid_2016 = UpstoxHistoricalCandleValidator().evaluate(
        record_invalid,
        _identity(record_invalid),
        batch=_batch((*invalid_rows, invalid_rows[-1])),
    )
    full_2017 = UpstoxHistoricalCandleValidator().evaluate(
        record_later,
        _identity(record_later),
        batch=_batch(_candles(121, end=record_later.required_end_date)),
    )
    source_records = (record_full, record_invalid, record_later)
    manifest = _manifest_for(source_records)
    sample = deterministic_historical_source_sample(manifest, sample_size=3)
    report = UpstoxHistoricalEvidenceReportEngine().build(
        manifest=manifest,
        sample=sample,
        dataset=_dataset_for((full_2016, invalid_2016, full_2017)),
    )
    assert report.candidates_with_121_raw_bars == 3
    assert report.candidates_with_121_pre_cutoff_bars == 3
    assert report.candidates_with_121_integrity_valid_bars == 3
    assert report.full_price_coverage_candidates == 2
    assert report.candidates_2016_full_price_coverage == 1
    assert report.later_year_full_price_coverage == 1
    assert report.observed_price_coverage_rate == Decimal("0.6667")
    assert report.terminal_status_total == 3
    assert report.terminal_statuses_reconcile is True


def test_integrity_report_definitions_exclude_invalid_from_partial_and_no_history() -> (
    None
):
    partial_record = _record(candidate_id="partial", symbol="PARTIAL")
    invalid_record = _record(candidate_id="invalid", symbol="INVALID")
    missing_record = _record(candidate_id="missing", symbol="MISSING")
    partial = UpstoxHistoricalCandleValidator().evaluate(
        partial_record,
        _identity(partial_record),
        batch=_batch(_candles(80, end=partial_record.required_end_date)),
    )
    duplicate_rows = _candles(121, end=invalid_record.required_end_date)
    invalid = UpstoxHistoricalCandleValidator().evaluate(
        invalid_record,
        _identity(invalid_record),
        batch=_batch((*duplicate_rows, duplicate_rows[-1])),
    )
    missing = UpstoxHistoricalCandleValidator().evaluate(
        missing_record,
        UpstoxIdentityResolver().resolve(missing_record),
    )
    report = UpstoxSeriesIntegrityEngine().build((partial, invalid, missing))
    assert report.observed_candidates == 3
    assert report.invalid_series == 1
    assert report.partial_history_candidates == 1
    assert report.no_history_candidates == 1
    assert report.terminal_status_total == 3
    assert report.metric_reconciliation_result == "RECONCILED"
    attribution = report.invalid_attributions[0]
    assert attribution.candidate_id == "invalid"
    assert attribution.raw_row_count == 122
    assert attribution.pre_cutoff_row_count == 122
    assert attribution.normalized_row_count == 122
    assert attribution.valid_row_count == 121
    assert attribution.rejected_row_count == 1
    assert attribution.primary_defect is UpstoxSeriesDefect.DUPLICATE_SESSION


def test_candidate_and_future_bars_are_excluded_from_usable_history() -> None:
    record = _record()
    candles = (
        *_candles(121),
        *_candles(2, end=record.candidate_date + timedelta(days=1)),
    )
    result = UpstoxHistoricalCandleValidator().evaluate(
        record, _identity(record), batch=_batch(candles)
    )
    assert result.usable_pre_candidate_bars == 121
    assert result.candidate_date_included is True
    assert result.future_bars_excluded == 2


def test_response_checksum_is_deterministic() -> None:
    response = _response(
        {"data": {"candles": [["2016-07-10T00:00:00+05:30", 10, 12, 9, 11, 100, 0]]}}
    )
    transports = [ScriptedTransport([response]), ScriptedTransport([response])]
    batches = [
        UpstoxReadOnlyHistoricalClient(
            config=_credential(), transport=item, minimum_request_interval=0
        ).historical_candles(
            "NSE_EQ|INE000A01001",
            from_date=date(2016, 1, 1),
            to_date=date(2016, 7, 10),
        )
        for item in transports
    ]
    assert batches[0].response_checksum == batches[1].response_checksum


def test_rate_limit_is_preserved_after_retry_budget() -> None:
    error = _provider_error(UpstoxProbeErrorCategory.RATE_LIMITED)
    client = UpstoxReadOnlyHistoricalClient(
        config=_credential(),
        transport=ScriptedTransport([error]),
        minimum_request_interval=0,
        max_retries=0,
    )
    with pytest.raises(UpstoxProbeHttpError) as captured:
        client.search_instruments("OLDCO")
    assert captured.value.category is UpstoxProbeErrorCategory.RATE_LIMITED


def test_transient_provider_error_retries_then_succeeds() -> None:
    sleeps: list[float] = []
    transport = ScriptedTransport(
        [
            _provider_error(UpstoxProbeErrorCategory.TRANSIENT_PROVIDER_ERROR),
            _search_response(),
        ]
    )
    client = UpstoxReadOnlyHistoricalClient(
        config=_credential(),
        transport=transport,
        minimum_request_interval=0,
        sleep=sleeps.append,
    )
    assert client.search_instruments("OLDCO").http_status == 200
    assert sleeps == [1.0]


def test_rate_limit_retry_obeys_retry_after_and_tracks_operations() -> None:
    sleeps: list[float] = []
    error = UpstoxProbeHttpError(
        category=UpstoxProbeErrorCategory.RATE_LIMITED,
        http_status=429,
        provider_error_code="UDAPI10005",
        sanitized_message="rate limited",
        retry_after_seconds=7,
    )
    client = UpstoxReadOnlyHistoricalClient(
        config=_credential(),
        transport=ScriptedTransport([error, _search_response()]),
        minimum_request_interval=0,
        sleep=sleeps.append,
    )
    assert client.search_instruments("OLDCO").http_status == 200
    metrics = client.operational_metrics()
    assert sleeps == [7]
    assert metrics.total_network_requests == 2
    assert metrics.successful_requests == 1
    assert metrics.rate_limit_responses == 1
    assert metrics.retries == 1
    assert metrics.account_endpoint_calls == 0
    assert metrics.order_endpoint_calls == 0
    assert metrics.token_exposure_incidents == 0


def test_conservative_request_budget_prevents_provider_limit_overrun() -> None:
    transport = ScriptedTransport([_search_response()])
    client = UpstoxReadOnlyHistoricalClient(
        config=_credential(),
        transport=transport,
        minimum_request_interval=0,
        max_network_requests=1,
    )
    assert client.search_instruments("OLDCO").http_status == 200
    with pytest.raises(UpstoxProbeHttpError) as captured:
        client.search_instruments("SECOND")
    assert captured.value.category is UpstoxProbeErrorCategory.RATE_LIMITED
    assert captured.value.provider_error_code == "LOCAL_REQUEST_BUDGET_EXHAUSTED"
    assert len(transport.calls) == 1


def test_persistent_provider_error_is_classified_after_retries() -> None:
    errors = [
        _provider_error(UpstoxProbeErrorCategory.TRANSIENT_PROVIDER_ERROR)
        for _ in range(3)
    ]
    client = UpstoxReadOnlyHistoricalClient(
        config=_credential(),
        transport=ScriptedTransport(errors),
        minimum_request_interval=0,
        sleep=lambda _: None,
        max_retries=2,
    )
    with pytest.raises(UpstoxProbeHttpError) as captured:
        client.search_instruments("OLDCO")
    assert captured.value.category is UpstoxProbeErrorCategory.PERSISTENT_PROVIDER_ERROR


@pytest.mark.skipif(
    not _PROJECT_REPLAY_CORPUS_AVAILABLE,
    reason="requires the authoritative local .alpha replay corpus",
)
def test_permanent_instrument_not_found_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UPSTOX_INSTRUMENT_REGISTRY", raising=False)
    transport = ScriptedTransport(
        [
            _search_response("NIFTY 50"),
            _response({"data": {"candles": []}}),
            _response({"status": "success", "data": []}),
        ]
    )
    run = UpstoxHistoricalProbeService(
        client=UpstoxReadOnlyHistoricalClient(
            config=_credential(), transport=transport, minimum_request_interval=0
        ),
        repository=UpstoxHistoricalEvidenceRepository(tmp_path / "evidence.json"),
    ).run(live=True, limit=1)
    assert run.dataset is not None
    assert (
        run.dataset.records[0].coverage_classification
        is UpstoxCoverageClassification.INSTRUMENT_NOT_FOUND
    )
    assert len(transport.calls) == 3
    assert run.operational_metrics.retries == 0


def test_raw_split_discontinuity_is_confirmed_with_authoritative_case() -> None:
    candles = (
        _candles(1, end=date(2024, 1, 9), close=Decimal("100"))[0],
        replace(
            _candles(1, end=date(2024, 1, 10), close=Decimal("50"))[0],
            volume=Decimal("2000"),
        ),
    )
    result = UpstoxAdjustmentAuditEngine().evaluate(
        candles,
        (UpstoxCorporateActionCase(date(2024, 1, 10), Decimal("2"), True),),
    )
    assert result.adjustment_status is UpstoxAdjustmentStatus.RAW_SERIES_CONFIRMED


def test_adjusted_split_series_is_confirmed() -> None:
    candles = (
        _candles(1, end=date(2024, 1, 9), close=Decimal("50"))[0],
        _candles(1, end=date(2024, 1, 10), close=Decimal("50"))[0],
    )
    result = UpstoxAdjustmentAuditEngine().evaluate(
        candles,
        (UpstoxCorporateActionCase(date(2024, 1, 10), Decimal("2"), True),),
    )
    assert result.adjustment_status is UpstoxAdjustmentStatus.ADJUSTED_SERIES_CONFIRMED


def test_volume_inconsistency_rejects_raw_classification() -> None:
    candles = (
        _candles(1, end=date(2024, 1, 9), close=Decimal("100"))[0],
        replace(
            _candles(1, end=date(2024, 1, 10), close=Decimal("50"))[0],
            volume=Decimal("100"),
        ),
    )
    result = UpstoxAdjustmentAuditEngine().evaluate(
        candles,
        (UpstoxCorporateActionCase(date(2024, 1, 10), Decimal("2"), True),),
    )
    assert result.adjustment_status is UpstoxAdjustmentStatus.ADJUSTMENT_INCONSISTENT


def test_undocumented_adjustment_requires_corporate_action_evidence() -> None:
    result = UpstoxAdjustmentAuditEngine().evaluate(_candles(5), ())
    assert result.adjustment_status is UpstoxAdjustmentStatus.ADJUSTMENT_UNDOCUMENTED
    assert (
        result.corporate_action_status
        is UpstoxCorporateActionStatus.CORPORATE_ACTION_EVIDENCE_REQUIRED
    )


def test_conflicting_corporate_action_evidence_is_not_accepted() -> None:
    result = UpstoxAdjustmentAuditEngine().evaluate(
        _candles(5),
        (
            UpstoxCorporateActionCase(
                date(2016, 7, 8), Decimal("2"), True, conflicting_evidence=True
            ),
        ),
    )
    assert (
        result.corporate_action_status
        is UpstoxCorporateActionStatus.CONFLICTING_CORPORATE_ACTION_EVIDENCE
    )


def test_dry_run_makes_no_network_call_and_creates_no_evidence_file(
    tmp_path: Path,
) -> None:
    transport = ScriptedTransport([])
    service = UpstoxHistoricalProbeService(
        client=UpstoxReadOnlyHistoricalClient(
            config=_credential(), transport=transport
        ),
        repository=UpstoxHistoricalEvidenceRepository(tmp_path / "evidence.json"),
    )
    plan = service.plan(limit=1)
    run = service.run(dry_run=True)
    assert run.dataset is None
    assert transport.calls == []
    assert not (tmp_path / "evidence.json").exists()
    assert plan.production_influence is False


@pytest.mark.skipif(
    not _PROJECT_REPLAY_CORPUS_AVAILABLE,
    reason="requires the authoritative local .alpha replay corpus",
)
def test_live_sample_is_resumable_and_persistence_is_sanitized(tmp_path: Path) -> None:
    planning = UpstoxHistoricalProbeService(
        client=UpstoxReadOnlyHistoricalClient(
            config=_credential(), transport=ScriptedTransport([])
        ),
        repository=UpstoxHistoricalEvidenceRepository(tmp_path / "evidence.json"),
    )
    target = planning.plan(limit=1).targets[0]
    candle_payload = {
        "data": {
            "candles": [
                [
                    item.observed_at.isoformat(),
                    str(item.open_price),
                    str(item.high_price),
                    str(item.low_price),
                    str(item.close_price),
                    str(item.volume),
                    "0",
                ]
                for item in _candles(121, end=target.required_end_date)
            ]
        }
    }
    first_transport = ScriptedTransport(
        [
            _search_response("NIFTY 50"),
            _response({"data": {"candles": []}}),
            _search_response(target.historical_symbol),
            _response(candle_payload),
        ]
    )
    repository = UpstoxHistoricalEvidenceRepository(tmp_path / "evidence.json")
    first = UpstoxHistoricalProbeService(
        client=UpstoxReadOnlyHistoricalClient(
            config=_credential(), transport=first_transport, minimum_request_interval=0
        ),
        repository=repository,
    ).run(live=True, candidate_id=target.candidate_id, limit=1)
    assert first.attempted_candidates == 1
    persisted = (tmp_path / "evidence.json").read_text(encoding="utf-8")
    assert "unit-test-only-credential" not in persisted
    assert "response-checksum" not in persisted
    second_transport = ScriptedTransport(
        [_search_response("NIFTY 50"), _response({"data": {"candles": []}})]
    )
    second = UpstoxHistoricalProbeService(
        client=UpstoxReadOnlyHistoricalClient(
            config=_credential(), transport=second_transport, minimum_request_interval=0
        ),
        repository=repository,
    ).run(live=True, candidate_id=target.candidate_id, limit=1, resume=True)
    assert second.attempted_candidates == 0
    assert second.resumed_candidates == 1


@pytest.mark.skipif(
    not _PROJECT_REPLAY_CORPUS_AVAILABLE,
    reason="requires the authoritative local .alpha replay corpus",
)
def test_full_population_requires_live_confirmation_and_successful_sample(
    tmp_path: Path,
) -> None:
    service = UpstoxHistoricalProbeService(
        client=UpstoxReadOnlyHistoricalClient(
            config=_credential(), transport=ScriptedTransport([])
        ),
        repository=UpstoxHistoricalEvidenceRepository(tmp_path / "evidence.json"),
    )
    with pytest.raises(ValueError, match="requires --live"):
        service.plan(full_population=True)
    with pytest.raises(ValueError, match="confirm-full-population"):
        service.plan(live=True, full_population=True)
    with pytest.raises(ValueError, match="persisted sample"):
        service.run(
            live=True, full_population=True, confirm_full_population=True, limit=1
        )


@pytest.mark.skipif(
    not _PROJECT_REPLAY_CORPUS_AVAILABLE,
    reason="requires the authoritative local .alpha replay corpus",
)
def test_full_population_resume_reuses_completed_sample_evidence(
    tmp_path: Path,
) -> None:
    repository = UpstoxHistoricalEvidenceRepository(tmp_path / "evidence.json")
    planning = UpstoxHistoricalProbeService(
        client=UpstoxReadOnlyHistoricalClient(
            config=_credential(), transport=ScriptedTransport([])
        ),
        repository=repository,
    )
    plan = planning.plan(
        live=True,
        full_population=True,
        confirm_full_population=True,
        limit=1,
    )
    target = plan.targets[0]
    evidence = UpstoxHistoricalCandleValidator().evaluate(
        target,
        _identity(target),
        batch=_batch(_candles(121, end=target.required_end_date)),
    )
    repository.save(
        UpstoxHistoricalEvidenceDataset(
            dataset_version="upstox-historical-evidence-dataset-v1",
            probe_version="upstox-historical-evidence-probe-v1",
            source_manifest_version=plan.manifest.manifest_version,
            source_manifest_checksum=plan.manifest.checksum,
            sample_checksum=plan.sample.checksum,
            scope="SAMPLE",
            credential_status=UpstoxProbeCredentialStatus.CONFIGURED_REDACTED,
            authentication_status=UpstoxAuthProbeStatus.TOKEN_ACCEPTED,
            records=(evidence,),
            operational_metrics=UpstoxOperationalMetrics(
                total_network_requests=4,
                successful_requests=4,
            ),
        )
    )
    transport = ScriptedTransport(
        [_search_response("NIFTY 50"), _response({"data": {"candles": []}})]
    )
    run = UpstoxHistoricalProbeService(
        client=UpstoxReadOnlyHistoricalClient(
            config=_credential(), transport=transport, minimum_request_interval=0
        ),
        repository=repository,
    ).run(
        live=True,
        full_population=True,
        confirm_full_population=True,
        limit=1,
        resume=True,
    )
    assert run.dataset is not None
    assert run.dataset.scope == "FULL_POPULATION"
    assert run.resumed_candidates == 1
    assert run.attempted_candidates == 0
    assert run.operational_metrics.total_network_requests == 6
    assert len(transport.calls) == 2


@pytest.mark.skipif(
    not _PROJECT_REPLAY_CORPUS_AVAILABLE,
    reason="requires the authoritative local .alpha replay corpus",
)
def test_persistent_authentication_failure_stops_full_run(
    tmp_path: Path,
) -> None:
    repository = UpstoxHistoricalEvidenceRepository(tmp_path / "evidence.json")
    planning = UpstoxHistoricalProbeService(
        client=UpstoxReadOnlyHistoricalClient(
            config=_credential(), transport=ScriptedTransport([])
        ),
        repository=repository,
    )
    plan = planning.plan(
        live=True,
        full_population=True,
        confirm_full_population=True,
        limit=2,
    )
    completed = UpstoxHistoricalCandleValidator().evaluate(
        plan.targets[0],
        _identity(plan.targets[0]),
        batch=_batch(_candles(121, end=plan.targets[0].required_end_date)),
    )
    repository.save(
        UpstoxHistoricalEvidenceDataset(
            dataset_version="upstox-historical-evidence-dataset-v1",
            probe_version="upstox-historical-evidence-probe-v1",
            source_manifest_version=plan.manifest.manifest_version,
            source_manifest_checksum=plan.manifest.checksum,
            sample_checksum=plan.sample.checksum,
            scope="SAMPLE",
            credential_status=UpstoxProbeCredentialStatus.CONFIGURED_REDACTED,
            authentication_status=UpstoxAuthProbeStatus.TOKEN_ACCEPTED,
            records=(completed,),
        )
    )
    auth_error = _provider_error(UpstoxProbeErrorCategory.AUTHENTICATION_FAILED)
    transport = ScriptedTransport(
        [
            _search_response("NIFTY 50"),
            _response({"data": {"candles": []}}),
            auth_error,
        ]
    )
    run = UpstoxHistoricalProbeService(
        client=UpstoxReadOnlyHistoricalClient(
            config=_credential(), transport=transport, minimum_request_interval=0
        ),
        repository=repository,
    ).run(
        live=True,
        full_population=True,
        confirm_full_population=True,
        limit=2,
        resume=True,
    )
    assert run.stopped_early is True
    assert run.attempted_candidates == 1
    assert run.dataset is not None
    assert len(run.dataset.records) == 2
    assert (
        run.dataset.records[-1].coverage_classification
        is UpstoxCoverageClassification.AUTHENTICATION_FAILED
    )


@pytest.mark.skipif(
    not _PROJECT_REPLAY_CORPUS_AVAILABLE,
    reason="requires the authoritative local .alpha replay corpus",
)
def test_read_only_reports_use_persisted_full_population_dataset(
    tmp_path: Path,
) -> None:
    repository = UpstoxHistoricalEvidenceRepository(tmp_path / "evidence.json")
    planning = UpstoxHistoricalProbeService(repository=repository)
    plan = planning.plan(limit=1)
    target = plan.targets[0]
    evidence = UpstoxHistoricalCandleValidator().evaluate(
        target,
        _identity(target),
        batch=_batch(_candles(121, end=target.required_end_date)),
    )
    repository.save(
        UpstoxHistoricalEvidenceDataset(
            dataset_version="upstox-historical-evidence-dataset-v1",
            probe_version="upstox-historical-evidence-probe-v1",
            source_manifest_version=plan.manifest.manifest_version,
            source_manifest_checksum=plan.manifest.checksum,
            sample_checksum=plan.sample.checksum,
            scope="FULL_POPULATION",
            credential_status=UpstoxProbeCredentialStatus.CONFIGURED_REDACTED,
            authentication_status=UpstoxAuthProbeStatus.TOKEN_ACCEPTED,
            records=(evidence,),
        )
    )
    run = planning.run(live=False)
    assert run.dataset is not None
    assert run.dataset.scope == "FULL_POPULATION"
    assert len(run.dataset.records) == 1


@pytest.mark.skipif(
    not _PROJECT_REPLAY_CORPUS_AVAILABLE,
    reason="requires the authoritative local .alpha replay corpus",
)
def test_manifest_filters_are_deterministic() -> None:
    service = UpstoxHistoricalProbeService(
        client=UpstoxReadOnlyHistoricalClient(
            config=_credential(), transport=ScriptedTransport([])
        )
    )
    initial = service.plan(limit=1).targets[0]
    filtered = service.plan(candidate_id=initial.candidate_id)
    assert filtered.targets == (initial,)


def test_json_and_csv_exports_are_deterministic_and_secret_free(tmp_path: Path) -> None:
    service = UpstoxHistoricalProbeService(
        client=UpstoxReadOnlyHistoricalClient(
            config=_credential(), transport=ScriptedTransport([])
        ),
        repository=UpstoxHistoricalEvidenceRepository(tmp_path / "missing.json"),
    )
    run = service.run(dry_run=True)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    export_upstox_evidence_json(run.report, first)
    export_upstox_evidence_json(run.report, second)
    assert first.read_bytes() == second.read_bytes()
    csv_path = tmp_path / "records.csv"
    export_upstox_evidence_csv((), csv_path)
    assert csv_path.read_text(encoding="utf-8").startswith("candidate_id,")
    assert "unit-test-only-credential" not in first.read_text(encoding="utf-8")


def test_series_integrity_json_and_csv_are_deterministic_and_contain_no_raw_rows(
    tmp_path: Path,
) -> None:
    record = _record(candidate_id="invalid-export", symbol="EXPORT")
    candles = _candles(121, end=record.required_end_date)
    evidence = UpstoxHistoricalCandleValidator().evaluate(
        record,
        _identity(record),
        batch=_batch((*candles, candles[-1])),
    )
    report = UpstoxSeriesIntegrityEngine().build((evidence,))
    json_paths = (tmp_path / "one.json", tmp_path / "two.json")
    for path in json_paths:
        export_upstox_evidence_json(report, path)
    assert json_paths[0].read_bytes() == json_paths[1].read_bytes()
    csv_paths = (tmp_path / "one.csv", tmp_path / "two.csv")
    for path in csv_paths:
        export_upstox_series_integrity_csv(report, path)
    assert csv_paths[0].read_bytes() == csv_paths[1].read_bytes()
    exported = json_paths[0].read_text(encoding="utf-8")
    rendered = "\n".join(render_upstox_series_integrity(report))
    for forbidden in (
        "unit-test-only-credential",
        "open_price",
        "close_price",
        "response_checksum",
        "Authorization",
    ):
        assert forbidden not in exported
        assert forbidden not in rendered
    assert report.production_influence is False


def test_series_integrity_cli_reads_persisted_evidence_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _record(candidate_id="invalid-cli", symbol="CLITEST")
    candles = _candles(121, end=record.required_end_date)
    evidence = UpstoxHistoricalCandleValidator().evaluate(
        record,
        _identity(record),
        batch=_batch((*candles, candles[-1])),
    )
    path = tmp_path / "evidence.json"
    UpstoxHistoricalEvidenceRepository(path).save(_dataset_for((evidence,)))
    monkeypatch.setenv("ALPHA_UPSTOX_HISTORICAL_EVIDENCE_PATH", str(path))
    result = runner.invoke(
        app,
        [
            "replay",
            "upstox-series-integrity",
            "--symbol",
            "CLITEST",
            "--limit",
            "1",
        ],
    )
    assert result.exit_code == 0
    assert "Invalid Series: 1" in result.output
    assert "primary=DUPLICATE_SESSION" in result.output
    assert "Metric Reconciliation Result: RECONCILED" in result.output
    assert "PRODUCTION_INFLUENCE=false" in result.output


def test_cli_default_auth_probe_makes_no_network_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = ScriptedTransport([])
    service = UpstoxHistoricalProbeService(
        client=UpstoxReadOnlyHistoricalClient(config=_credential(), transport=transport)
    )
    monkeypatch.setattr(cli_module, "_upstox_historical_probe_service", lambda: service)
    result = runner.invoke(app, ["replay", "upstox-auth-probe"])
    assert result.exit_code == 0
    assert "PROBE_NOT_RUN" in result.output
    assert transport.calls == []


def test_cli_explicit_live_auth_probe_uses_mocked_read_only_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = ScriptedTransport(
        [_search_response("NIFTY 50"), _response({"data": {"candles": []}})]
    )
    service = UpstoxHistoricalProbeService(
        client=UpstoxReadOnlyHistoricalClient(
            config=_credential(), transport=transport, minimum_request_interval=0
        )
    )
    monkeypatch.setattr(cli_module, "_upstox_historical_probe_service", lambda: service)
    result = runner.invoke(app, ["replay", "upstox-auth-probe", "--live"])
    assert result.exit_code == 0
    assert "TOKEN_ACCEPTED" in result.output
    assert "unit-test-only-credential" not in result.output


@pytest.mark.skipif(
    not _PROJECT_REPLAY_CORPUS_AVAILABLE,
    reason="requires the authoritative local .alpha replay corpus",
)
def test_cli_sample_and_headline_report_are_read_only_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "ALPHA_UPSTOX_HISTORICAL_EVIDENCE_PATH", str(tmp_path / "evidence.json")
    )
    sample = runner.invoke(
        app,
        ["replay", "upstox-historical-sample", "--sample", "--dry-run", "--limit", "2"],
    )
    report = runner.invoke(app, ["replay", "upstox-evidence-report"])
    assert sample.exit_code == 0
    assert "Population Candidates: 657" in sample.output
    assert "Attempted This Run: 0" in sample.output
    assert report.exit_code == 0
    assert "Full Reconstruction Readiness" in report.output


def test_cli_full_population_safeguard_and_deterministic_json(tmp_path: Path) -> None:
    blocked = runner.invoke(
        app, ["replay", "upstox-historical-sample", "--full-population"]
    )
    assert blocked.exit_code != 0
    assert "requires --live" in blocked.output
    paths = (tmp_path / "one.json", tmp_path / "two.json")
    for path in paths:
        result = runner.invoke(
            app,
            [
                "replay",
                "upstox-auth-probe",
                "--dry-run",
                "--format",
                "json",
                "--output",
                str(path),
            ],
        )
        assert result.exit_code == 0
    assert paths[0].read_bytes() == paths[1].read_bytes()


@pytest.mark.skipif(
    not _PROJECT_REPLAY_CORPUS_AVAILABLE,
    reason="requires the authoritative local .alpha replay corpus",
)
def test_manifest_and_production_provider_policy_remain_unchanged() -> None:
    report = build_project_historical_source_evaluation(dry_run=True)
    assert report.manifest.manifest_version == HISTORICAL_SOURCE_MANIFEST_VERSION
    assert len(report.manifest.records) == 657
    assert report.manifest.source_required_count == 608
    assert report.manifest.recovery_uncertain_count == 49
    registry = Path("alpha/data/providers/__init__.py").read_text(encoding="utf-8")
    assert "Upstox" not in registry
    assert PRODUCTION_INFLUENCE is False
