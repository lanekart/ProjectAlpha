from __future__ import annotations

import asyncio
import io
import urllib.error
import urllib.parse
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from email.message import Message
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha.cli import _parse_live_symbols, _print_live_snapshot, app
from alpha.live import (
    RECORDED_UPSTOX_FIXTURE_NAME,
    FeedHealthEngine,
    FeedHealthStatus,
    InstrumentSubscription,
    LatencyMonitor,
    LiveBarBuilder,
    LiveInstrumentRegistry,
    LiveRiskContext,
    LiveRiskEngine,
    LiveTick,
    MarketSessionEngine,
    RecordedProviderMode,
    RecordedUpstoxMarketDataProvider,
    RecordedUpstoxReadinessAuditEngine,
    TickQualityEngine,
    TickQualityStatus,
    UpstoxLiveAcceptanceClassification,
    UpstoxLiveAcceptanceHarness,
    build_protocol_audit_report,
    load_recorded_upstox_fixture,
    render_protocol_audit,
    run_live_monitor,
    run_recorded_upstox_simulation,
    schema_hash,
)
from alpha.live.models import LiveFeedStatus, MarketSessionState
from alpha.live.upstox import UpstoxLiveMarketDataProvider
from alpha.live.upstox_auth import (
    InstrumentResolutionStatus,
    UpstoxAuthConfig,
    UpstoxAuthService,
    UpstoxFeedAuthorization,
    UpstoxInstrumentResolver,
    UpstoxProviderHttpError,
    UpstoxProviderPreflight,
    UpstoxReadinessStatus,
    UpstoxTokenExchangeError,
    UpstoxTokenExchangeFailure,
    UpstoxTokenMetadata,
    UpstoxTokenStatus,
    UpstoxTokenValidation,
    UrlLibUpstoxTransport,
)
from alpha.live.upstox_proto import market_data_feed_v3_pb2
from alpha.live.upstox_protocol import (
    UPSTOX_FEED_V3_DOC_URL,
    UPSTOX_FEED_V3_SCHEMA_VERSION,
    UpstoxAuthorizedUriGuard,
    UpstoxFeedAuthUriClassification,
    UpstoxFeedMessageCategory,
    UpstoxProtocolAuditClassification,
    UpstoxSequenceTracker,
    capture_protocol_metadata,
    decode_feed_message,
    encode_subscription_request,
    normalize_feed_message,
)


def test_live_bar_builder_builds_one_minute_ohlcv_and_vwap() -> None:
    builder = LiveBarBuilder(timeframe_minutes=1)
    started = datetime(2026, 7, 9, 9, 15, 1, tzinfo=UTC)

    builder.update(
        LiveTick(
            symbol="kalyankjil",
            price=Decimal("100"),
            volume=Decimal("10"),
            observed_at=started,
        )
    )
    bar = builder.update(
        LiveTick(
            symbol="KALYANKJIL",
            price=Decimal("104"),
            volume=Decimal("30"),
            observed_at=started + timedelta(seconds=20),
        )
    )

    assert bar.symbol == "KALYANKJIL"
    assert bar.open_price == Decimal("100")
    assert bar.high_price == Decimal("104")
    assert bar.low_price == Decimal("100")
    assert bar.close_price == Decimal("104")
    assert bar.volume == Decimal("40")
    assert bar.vwap == Decimal("103")


def test_live_bar_builder_emits_completed_bars() -> None:
    builder = LiveBarBuilder(timeframe_minutes=5)
    observed_at = datetime(2026, 7, 9, 9, 16, tzinfo=UTC)

    builder.update(
        LiveTick(
            symbol="PCJEWELLER",
            price=Decimal("20"),
            volume=Decimal("100"),
            observed_at=observed_at,
        )
    )

    completed = builder.completed_before(datetime(2026, 7, 9, 9, 25, tzinfo=UTC))

    assert len(completed) == 1
    assert completed[0].started_at == datetime(2026, 7, 9, 9, 15, tzinfo=UTC)


def test_upstox_provider_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)

    provider = UpstoxLiveMarketDataProvider.from_environment()

    assert provider.configured() is False
    assert provider.status is LiveFeedStatus.DISCONNECTED


def test_upstox_stale_feed_detection() -> None:
    provider = UpstoxLiveMarketDataProvider(access_token="token")
    provider._status = LiveFeedStatus.CONNECTED
    provider._last_message_at = datetime(2026, 7, 9, 9, 15, tzinfo=UTC)

    assert provider.is_stale(now=datetime(2026, 7, 9, 9, 15, 20, tzinfo=UTC))


def test_upstox_auth_reports_missing_token(tmp_path: Path) -> None:
    config = _upstox_config(tmp_path, token=None)

    validation = UpstoxAuthService(
        config=config,
        transport=_FakeUpstoxTransport(),
    ).validate_token()

    assert validation.status is UpstoxTokenStatus.TOKEN_MISSING
    assert validation.token_configured is False


def test_upstox_auth_detects_expired_token(tmp_path: Path) -> None:
    config = _upstox_config(tmp_path, token="expired-token")
    service = UpstoxAuthService(config=config, transport=_FakeUpstoxTransport())
    service.save_metadata(
        UpstoxTokenMetadata(
            provider="upstox",
            token_fingerprint=_token_fingerprint("expired-token"),
            issued_at=datetime(2026, 1, 1, tzinfo=UTC),
            expected_expiry=datetime(2020, 1, 1, tzinfo=UTC),
            last_validation_at=None,
            validation_status=UpstoxTokenStatus.TOKEN_VALID,
            credential_source="test",
        )
    )

    validation = service.validate_token()

    assert validation.status is UpstoxTokenStatus.TOKEN_EXPIRED


def test_upstox_auth_reports_rejected_token(tmp_path: Path) -> None:
    transport = _FakeUpstoxTransport(
        profile_error=urllib.error.HTTPError(
            url="profile",
            code=401,
            msg="unauthorized",
            hdrs=None,
            fp=None,
        )
    )
    service = UpstoxAuthService(
        config=_upstox_config(tmp_path, token="bad-token"),
        transport=transport,
    )

    validation = service.validate_token()

    assert validation.status is UpstoxTokenStatus.TOKEN_REJECTED


def test_upstox_exchange_code_persists_only_safe_metadata(tmp_path: Path) -> None:
    service = UpstoxAuthService(
        config=_upstox_config(tmp_path, token=None),
        transport=_FakeUpstoxTransport(token_response={"access_token": "secret-token"}),
    )

    metadata = service.exchange_code("single-use-code")
    stored = (tmp_path / "upstox-metadata.json").read_text(encoding="utf-8")

    assert metadata.token_fingerprint
    assert "secret-token" not in stored
    assert "single-use-code" not in stored


def test_upstox_exchange_code_uses_official_token_request(tmp_path: Path) -> None:
    transport = _RecordingUpstoxTransport()
    service = UpstoxAuthService(
        config=_upstox_config(tmp_path, token=None),
        transport=transport,
    )

    service.exchange_code("code with spaces")

    assert transport.url == "https://api.upstox.com/v2/login/authorization/token"
    assert transport.headers == {
        "Accept": "application/json",
        "Connection": "close",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "ProjectAlpha/1.0 UpstoxOAuthClient",
    }
    encoded = urllib.parse.urlencode(transport.form)
    parsed = urllib.parse.parse_qs(encoded)
    assert parsed == {
        "code": ["code with spaces"],
        "client_id": ["client-id"],
        "client_secret": ["client-secret"],
        "redirect_uri": ["http://localhost/callback"],
        "grant_type": ["authorization_code"],
    }


def test_upstox_url_transport_sends_urlencoded_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout):  # noqa: ANN001, ANN202
        captured["url"] = request.full_url
        captured["headers"] = dict(request.headers)
        captured["body"] = request.data.decode("utf-8")
        captured["timeout"] = timeout
        return _FakeHttpResponse('{"access_token":"token"}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    UrlLibUpstoxTransport().post_form(
        "https://api.upstox.com/v2/login/authorization/token",
        {
            "code": "code with spaces",
            "client_id": "client-id",
            "client_secret": "client-secret",
            "redirect_uri": "http://localhost/callback",
            "grant_type": "authorization_code",
        },
        {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    assert captured["url"] == "https://api.upstox.com/v2/login/authorization/token"
    assert captured["headers"]["Accept"] == "application/json"
    assert captured["headers"]["Connection"] == "close"
    assert captured["headers"]["Content-type"] == "application/x-www-form-urlencoded"
    assert captured["headers"]["User-agent"] == "ProjectAlpha/1.0 UpstoxOAuthClient"
    assert captured["body"] == (
        "code=code+with+spaces&client_id=client-id&"
        "client_secret=client-secret&redirect_uri=http%3A%2F%2Flocalhost%2F"
        "callback&grant_type=authorization_code"
    )


def test_upstox_url_transport_sanitizes_http_error_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request, timeout):  # noqa: ANN001, ANN202
        body = (
            '{"status":"error","errors":[{"error_code":"UDAPI100057",'
            '"message":"Invalid Auth code single-use-code",'
            '"invalid_value":"single-use-code"}]}'
        )
        raise urllib.error.HTTPError(
            url=request.full_url,
            code=400,
            msg="bad request",
            hdrs=None,
            fp=io.BytesIO(body.encode("utf-8")),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(UpstoxProviderHttpError) as exc_info:
        UrlLibUpstoxTransport().post_form(
            "https://api.upstox.com/v2/login/authorization/token",
            {
                "code": "single-use-code",
                "client_id": "client-id",
                "client_secret": "client-secret",
                "redirect_uri": "http://localhost/callback",
                "grant_type": "authorization_code",
            },
            {
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

    assert exc_info.value.http_status == 400
    assert exc_info.value.provider_error_code == "UDAPI100057"
    assert "single-use-code" not in exc_info.value.sanitized_message
    assert "[redacted]" in exc_info.value.sanitized_message
    assert "client-secret" not in str(exc_info.value)


def test_upstox_exchange_maps_url_transport_provider_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request, timeout):  # noqa: ANN001, ANN202
        body = (
            '{"status":"error","errors":[{"error_code":"UDAPI100057",'
            '"message":"Invalid Auth code single-use-code"}]}'
        )
        raise urllib.error.HTTPError(
            url=request.full_url,
            code=400,
            msg="bad request",
            hdrs=None,
            fp=io.BytesIO(body.encode("utf-8")),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    service = UpstoxAuthService(
        config=_upstox_config(tmp_path, token="access-token-secret"),
        transport=UrlLibUpstoxTransport(),
    )

    with pytest.raises(UpstoxTokenExchangeError) as exc_info:
        service.exchange_code("single-use-code")

    assert exc_info.value.http_status == 400
    assert exc_info.value.provider_error_code == "UDAPI100057"
    assert exc_info.value.category is (
        UpstoxTokenExchangeFailure.INVALID_OR_USED_AUTHORIZATION_CODE
    )
    assert "single-use-code" not in str(exc_info.value)
    assert "client-secret" not in str(exc_info.value)
    assert "access-token-secret" not in str(exc_info.value)


def test_upstox_exchange_classifies_cloudflare_1010(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request, timeout):  # noqa: ANN001, ANN202
        body = (
            "<html><title>Access denied | api.upstox.com used Cloudflare to "
            "restrict access</title><body>Error 1010 Ray ID: "
            "88abc123-COK</body></html>"
        )
        headers = Message()
        headers["Content-Type"] = "text/html; charset=UTF-8"
        headers["Server"] = "cloudflare"
        headers["CF-Ray"] = "88abc123-COK"
        headers["CF-Mitigated"] = "challenge"
        raise urllib.error.HTTPError(
            url=request.full_url,
            code=403,
            msg="forbidden",
            hdrs=headers,
            fp=io.BytesIO(body.encode("utf-8")),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    service = UpstoxAuthService(
        config=_upstox_config(tmp_path, token="access-token-secret"),
        transport=UrlLibUpstoxTransport(),
    )

    with pytest.raises(UpstoxTokenExchangeError) as exc_info:
        service.exchange_code("single-use-code")

    assert exc_info.value.category is (
        UpstoxTokenExchangeFailure.CLOUDFLARE_CLIENT_SIGNATURE_REJECTED
    )
    assert exc_info.value.http_status == 403
    assert exc_info.value.provider_error_code == "1010"
    assert exc_info.value.diagnostic_headers == {
        "Content-Type": "text/html; charset=UTF-8",
        "Server": "cloudflare",
        "CF-Ray": "88abc123-COK",
        "CF-Mitigated": "challenge",
    }
    assert "CF-Ray: 88abc123-COK" in str(exc_info.value)
    assert "single-use-code" not in str(exc_info.value)
    assert "client-secret" not in str(exc_info.value)
    assert "access-token-secret" not in str(exc_info.value)


def test_upstox_plain_1010_is_not_documented_oauth_mapping(tmp_path: Path) -> None:
    service = UpstoxAuthService(
        config=_upstox_config(tmp_path, token=None),
        transport=_RejectingUpstoxTransport("1010", "Plain provider code 1010."),
    )

    with pytest.raises(UpstoxTokenExchangeError) as exc_info:
        service.exchange_code("single-use-code")

    assert exc_info.value.category is (
        UpstoxTokenExchangeFailure.TOKEN_EXCHANGE_PROVIDER_REJECTION
    )
    assert exc_info.value.provider_error_code == "1010"


def test_upstox_exchange_maps_invalid_client_credentials(
    tmp_path: Path,
) -> None:
    service = UpstoxAuthService(
        config=_upstox_config(tmp_path, token="access-token-secret"),
        transport=_RejectingUpstoxTransport(
            "UDAPI100069",
            "Check your client-secret; one or both are incorrect.",
        ),
    )

    with pytest.raises(UpstoxTokenExchangeError) as exc_info:
        service.exchange_code("single-use-code")

    assert exc_info.value.category is (
        UpstoxTokenExchangeFailure.INVALID_CLIENT_CREDENTIALS
    )
    assert exc_info.value.provider_error_code == "UDAPI100069"
    assert "client-secret" not in str(exc_info.value)
    assert "single-use-code" not in str(exc_info.value)
    assert "access-token-secret" not in str(exc_info.value)


def test_upstox_exchange_maps_invalid_redirect_uri(tmp_path: Path) -> None:
    service = UpstoxAuthService(
        config=_upstox_config(tmp_path, token=None),
        transport=_RejectingUpstoxTransport(
            "UDAPI100070",
            "The redirect_uri provided is invalid.",
        ),
    )

    with pytest.raises(UpstoxTokenExchangeError) as exc_info:
        service.exchange_code("single-use-code")

    assert exc_info.value.category is UpstoxTokenExchangeFailure.REDIRECT_URI_INVALID
    assert exc_info.value.provider_error_code == "UDAPI100070"


def test_upstox_exchange_maps_invalid_or_used_authorization_code(
    tmp_path: Path,
) -> None:
    service = UpstoxAuthService(
        config=_upstox_config(tmp_path, token=None),
        transport=_RejectingUpstoxTransport(
            "UDAPI100057",
            "Invalid Auth code single-use-code",
        ),
    )

    with pytest.raises(UpstoxTokenExchangeError) as exc_info:
        service.exchange_code("single-use-code")

    assert exc_info.value.category is (
        UpstoxTokenExchangeFailure.INVALID_OR_USED_AUTHORIZATION_CODE
    )
    assert exc_info.value.provider_error_code == "UDAPI100057"
    assert "single-use-code" not in str(exc_info.value)


def test_upstox_exchange_maps_no_active_trading_segments(tmp_path: Path) -> None:
    service = UpstoxAuthService(
        config=_upstox_config(tmp_path, token=None),
        transport=_RejectingUpstoxTransport(
            "UDAPI100058",
            "No active trading segments.",
        ),
    )

    with pytest.raises(UpstoxTokenExchangeError) as exc_info:
        service.exchange_code("single-use-code")

    assert exc_info.value.category is (
        UpstoxTokenExchangeFailure.NO_ACTIVE_TRADING_SEGMENTS
    )
    assert exc_info.value.provider_error_code == "UDAPI100058"
    assert "Reactivate at least one segment" in str(exc_info.value)
    assert "single-use-code" not in str(exc_info.value)


def test_upstox_login_url_requires_client_id_and_redirect(tmp_path: Path) -> None:
    service = UpstoxAuthService(
        config=UpstoxAuthConfig(
            client_id=None,
            client_secret=None,
            redirect_uri=None,
            access_token=None,
            websocket_url="wss://example",
            token_metadata_path=tmp_path / "upstox-metadata.json",
        )
    )

    with pytest.raises(ValueError, match="UPSTOX_CLIENT_ID"):
        service.authorization_url()


def test_upstox_feed_v3_authorization_uses_redirect_response(tmp_path: Path) -> None:
    service = UpstoxAuthService(
        config=_upstox_config(tmp_path, token="valid-token"),
        transport=_FakeUpstoxTransport(
            feed_response={
                "data": {
                    "authorized_redirect_uri": (
                        "wss://example.upstox.com/market-data-feeder/v3"
                    )
                }
            }
        ),
    )

    authorization = service.authorize_market_data_feed_v3()

    assert authorization == UpstoxFeedAuthorization(
        authorized=True,
        feed_api_version="UPSTOX_MARKET_DATA_FEED_V3",
        authorized_redirect_uri_present=True,
        status="AUTHORIZED",
        reason="Authorized V3 websocket redirect URI received.",
    )


def test_upstox_preflight_reports_registry_unavailable(tmp_path: Path) -> None:
    service = UpstoxAuthService(
        config=_upstox_config(tmp_path, token="valid-token"),
        transport=_FakeUpstoxTransport(),
    )

    report = UpstoxProviderPreflight(
        auth=service,
        resolver=UpstoxInstrumentResolver(registry_path=tmp_path / "missing.json"),
    ).status(symbol="KALYANKJIL")

    assert report.feed_api_version == "UPSTOX_MARKET_DATA_FEED_V3"
    assert report.instrument_resolution is not None
    assert (
        report.instrument_resolution.status is InstrumentResolutionStatus.STALE_REGISTRY
    )
    assert (
        report.overall_readiness
        is UpstoxReadinessStatus.INSTRUMENT_REGISTRY_UNAVAILABLE
    )


def test_upstox_instrument_resolver_resolves_exact_json_registry(
    tmp_path: Path,
) -> None:
    registry = tmp_path / "registry.json"
    registry.write_text(
        '[{"tradingsymbol":"KALYANKJIL","exchange":"NSE_EQ",'
        '"instrument_key":"NSE_EQ|INE303R01014","instrument_type":"EQ"}]',
        encoding="utf-8",
    )

    resolution = UpstoxInstrumentResolver(registry_path=registry).resolve("KALYANKJIL")

    assert resolution.status is InstrumentResolutionStatus.RESOLVED_EXACT
    assert resolution.instrument_key == "NSE_EQ|INE303R01014"


def test_recorded_upstox_fixture_is_sanitized_contract_data() -> None:
    fixture = load_recorded_upstox_fixture()
    raw = Path("alpha/live/fixtures/upstox_recorded_contract.json").read_text(
        encoding="utf-8"
    )

    assert fixture.fixture_id == "upstox_recorded_contract_v1"
    assert fixture.recorded_simulation is True
    assert "not a captured production payload" in fixture.description
    for secret in ("access_token", "authorization_code", "api_secret", "user_id"):
        assert secret not in raw


def test_recorded_upstox_messages_normalize_ticks_quotes_and_rejections() -> None:
    fixture = load_recorded_upstox_fixture()
    run = run_recorded_upstox_simulation(fixture=fixture)

    assert run.provider_mode is RecordedProviderMode.RECORDED_SIMULATION
    assert run.messages_processed == 15
    assert run.messages_rejected == 3
    assert run.duplicate_count == 1
    assert run.out_of_order_count == 1
    assert run.stale_events == 1
    assert run.reconnect_count == 1
    assert run.market_open_events == 1
    assert run.market_closed_events == 1
    assert run.instruments_resolved == 2
    assert len(run.ticks) == 9
    assert len(run.quotes) == 9
    assert run.ticks[0].symbol == "KALYANKJIL"
    assert run.ticks[0].instrument_key == "NSE_EQ|INE303R01014"
    assert run.ticks[0].price == Decimal("465.00")
    rejected = {
        diagnostic.event_id: diagnostic.reasons
        for diagnostic in run.diagnostics
        if diagnostic.status == "REJECTED"
    }
    assert "unknown instrument key" in rejected["unknown-instrument"]
    assert "missing price" in rejected["malformed-payload"]
    assert "timestamp regression" in rejected["out-of-order-event"]


def test_recorded_upstox_builds_deterministic_bars() -> None:
    run = run_recorded_upstox_simulation(fixture=load_recorded_upstox_fixture())

    one_minute = {
        (bar.symbol, bar.started_at.isoformat()): bar for bar in run.one_minute_bars
    }

    kalyan_0915 = one_minute[("KALYANKJIL", "2026-07-17T09:15:00+05:30")]
    assert kalyan_0915.open_price == Decimal("465.00")
    assert kalyan_0915.high_price == Decimal("466.00")
    assert kalyan_0915.low_price == Decimal("465.00")
    assert kalyan_0915.close_price == Decimal("466.00")
    assert kalyan_0915.volume == Decimal("250")
    assert kalyan_0915.vwap == Decimal("465.60")
    assert len(run.five_minute_bars) == 2


def test_recorded_provider_refuses_unknown_subscription() -> None:
    provider = RecordedUpstoxMarketDataProvider(
        fixture=load_recorded_upstox_fixture(),
    )

    async def attempt() -> None:
        await provider.connect()
        await provider.subscribe(
            (
                InstrumentSubscription(
                    symbol="UNKNOWN",
                    instrument_key="NSE_EQ|UNKNOWN",
                ),
            )
        )

    with pytest.raises(ValueError, match="not present in fixture"):
        asyncio.run(attempt())


def test_recorded_upstox_readiness_audit_reports_simulation_not_live() -> None:
    report = RecordedUpstoxReadinessAuditEngine().run()

    assert report.live_provider_connected is False
    assert report.simulation_mode == "RECORDED_SIMULATION"
    assert report.downstream_simulation_pass is True
    assert report.live_acceptance_complete is False
    assert report.account_segment_state == "NO_ACTIVE_TRADING_SEGMENTS"
    assert (
        report.overall_readiness_classification.value
        == "BLOCKED_BY_ACCOUNT_REACTIVATION"
    )
    assert report.candidate_path_executed is True
    assert report.shadow_observation_executed is True
    assert report.order_api_calls == 0


def test_upstox_readiness_audit_cli_outputs_text_and_json(tmp_path: Path) -> None:
    output = tmp_path / "readiness.json"

    text_result = CliRunner().invoke(
        app,
        [
            "provider",
            "upstox",
            "readiness-audit",
            "--fixture",
            RECORDED_UPSTOX_FIXTURE_NAME,
        ],
    )
    json_result = CliRunner().invoke(
        app,
        [
            "provider",
            "upstox",
            "readiness-audit",
            "--format",
            "json",
            "--output",
            str(output),
        ],
    )

    assert text_result.exit_code == 0
    assert "Recorded Simulation: true" in text_result.stdout
    assert "Order API Calls: 0" in text_result.stdout
    assert json_result.exit_code == 0
    assert output.exists()
    exported = output.read_text(encoding="utf-8")
    assert '"simulation_mode": "RECORDED_SIMULATION"' in exported
    assert "access-token-secret" not in exported


@pytest.mark.parametrize(
    ("auth", "classification"),
    (
        (
            lambda: _AcceptanceAuth(local_status=UpstoxTokenStatus.TOKEN_MISSING),
            UpstoxLiveAcceptanceClassification.TOKEN_UNAVAILABLE,
        ),
        (
            lambda: _AcceptanceAuth(local_status=UpstoxTokenStatus.TOKEN_EXPIRED),
            UpstoxLiveAcceptanceClassification.TOKEN_EXPIRED,
        ),
        (
            lambda: _AcceptanceAuth(remote_status=UpstoxTokenStatus.TOKEN_REJECTED),
            UpstoxLiveAcceptanceClassification.TOKEN_REMOTE_VALIDATION_FAILED,
        ),
        (
            lambda: _AcceptanceAuth(
                remote_status=UpstoxTokenStatus.TOKEN_REJECTED,
                remote_reason="UDAPI100058 no active trading segments",
            ),
            UpstoxLiveAcceptanceClassification.NO_ACTIVE_TRADING_SEGMENTS,
        ),
        (
            lambda: _AcceptanceAuth(feed_authorized=False),
            UpstoxLiveAcceptanceClassification.FEED_AUTHORIZATION_FAILED,
        ),
    ),
)
def test_upstox_live_acceptance_preflight_refusals(
    tmp_path: Path,
    auth,  # noqa: ANN001
    classification: UpstoxLiveAcceptanceClassification,
) -> None:
    report = _acceptance_harness(tmp_path, auth=auth()).run(
        instrument_key="NSE_EQ|INE303R01014",
        max_events=1,
        timeout_seconds=1,
    )

    assert report.overall_classification is classification
    assert report.provider_mode.value == "LIVE"
    assert report.protocol.connection_opened is False
    assert report.order_api_call_count == 0


def test_upstox_live_acceptance_refuses_unknown_and_wildcard_instrument(
    tmp_path: Path,
) -> None:
    harness = _acceptance_harness(tmp_path)

    unknown = harness.run(
        instrument_key="NSE_EQ|UNKNOWN",
        max_events=1,
        timeout_seconds=1,
    )
    wildcard = harness.run(
        instrument_key="NSE_EQ|*",
        max_events=1,
        timeout_seconds=1,
    )

    assert unknown.overall_classification is (
        UpstoxLiveAcceptanceClassification.INSTRUMENT_NOT_RESOLVED
    )
    assert wildcard.overall_classification is (
        UpstoxLiveAcceptanceClassification.INSTRUMENT_NOT_RESOLVED
    )


def test_upstox_live_acceptance_connection_and_subscription_failures(
    tmp_path: Path,
) -> None:
    connection = _acceptance_harness(
        tmp_path,
        provider=_AcceptanceProvider(connect_error=RuntimeError("socket failed")),
    ).run(
        instrument_key="NSE_EQ|INE303R01014",
        max_events=1,
        timeout_seconds=1,
    )
    subscription = _acceptance_harness(
        tmp_path,
        provider=_AcceptanceProvider(subscribe_error=ValueError("rejected")),
    ).run(
        instrument_key="NSE_EQ|INE303R01014",
        max_events=1,
        timeout_seconds=1,
    )

    assert connection.overall_classification is (
        UpstoxLiveAcceptanceClassification.LIVE_CONNECTION_FAILED
    )
    assert connection.protocol.clean_shutdown is True
    assert subscription.overall_classification is (
        UpstoxLiveAcceptanceClassification.SUBSCRIPTION_FAILED
    )
    assert subscription.protocol.clean_shutdown is True


def test_upstox_live_acceptance_bounded_events_and_exact_instrument(
    tmp_path: Path,
) -> None:
    provider = _AcceptanceProvider(
        ticks=(
            _acceptance_tick("NSE_EQ|INE303R01014", "465", "100", second=1),
            _acceptance_tick("NSE_EQ|INE303R01014", "466", "120", second=2),
            _acceptance_tick("NSE_EQ|INE303R01014", "467", "140", second=3),
        )
    )

    report = _acceptance_harness(tmp_path, provider=provider).run(
        instrument_key="NSE_EQ|INE303R01014",
        max_events=2,
        timeout_seconds=5,
    )

    assert report.overall_classification is (
        UpstoxLiveAcceptanceClassification.LIVE_ACCEPTANCE_PASS
    )
    assert len(report.events) == 2
    assert all(event.instrument_key == "NSE_EQ|INE303R01014" for event in report.events)
    assert report.protocol.subscription_acknowledged is True
    assert provider.closed is True
    assert report.order_api_call_count == 0


def test_upstox_live_acceptance_timeout_market_closed_classification(
    tmp_path: Path,
) -> None:
    report = _acceptance_harness(
        tmp_path,
        provider=_AcceptanceProvider(ticks=()),
    ).run(
        instrument_key="NSE_EQ|INE303R01014",
        max_events=1,
        timeout_seconds=1,
    )

    assert report.overall_classification is (
        UpstoxLiveAcceptanceClassification.LIVE_CONNECTIVITY_PASS_DATA_ACCEPTANCE_PENDING_MARKET_HOURS
    )
    assert report.protocol.connection_opened is True
    assert report.events == ()


def test_upstox_live_acceptance_interrupt_cleanup(tmp_path: Path) -> None:
    provider = _AcceptanceProvider(interrupt=True)

    report = _acceptance_harness(tmp_path, provider=provider).run(
        instrument_key="NSE_EQ|INE303R01014",
        max_events=1,
        timeout_seconds=1,
    )

    assert report.overall_classification is (
        UpstoxLiveAcceptanceClassification.LIVE_ACCEPTANCE_INTERRUPTED
    )
    assert report.protocol.clean_shutdown is True
    assert provider.closed is True


def test_upstox_live_acceptance_malformed_duplicate_out_of_order(
    tmp_path: Path,
) -> None:
    provider = _AcceptanceProvider(
        ticks=(
            _acceptance_tick("NSE_EQ|INE303R01014", "465", "100", second=2),
            _acceptance_tick("NSE_EQ|INE303R01014", "465", "100", second=2),
            _acceptance_tick("NSE_EQ|INE303R01014", "464", "100", second=1),
            _acceptance_tick("NSE_EQ|UNKNOWN", "1", "1", second=3),
        )
    )

    report = _acceptance_harness(tmp_path, provider=provider).run(
        instrument_key="NSE_EQ|INE303R01014",
        max_events=4,
        timeout_seconds=5,
    )

    assert report.protocol.duplicate_count == 1
    assert report.protocol.out_of_order_count == 1
    assert report.protocol.unknown_event_count == 1
    assert report.overall_classification is (
        UpstoxLiveAcceptanceClassification.LIVE_ACCEPTANCE_FAILED
    )


def test_upstox_live_acceptance_json_export_and_secret_redaction(
    tmp_path: Path,
) -> None:
    output = tmp_path / "acceptance.json"
    report = _acceptance_harness(
        tmp_path,
        auth=_AcceptanceAuth(secret="access-token-secret"),
        provider=_AcceptanceProvider(
            ticks=(_acceptance_tick("NSE_EQ|INE303R01014", "465", "100"),)
        ),
    ).run(
        instrument_key="NSE_EQ|INE303R01014",
        max_events=1,
        timeout_seconds=5,
    )

    from alpha.live import export_upstox_live_acceptance_json

    export_upstox_live_acceptance_json(report, output)
    exported = output.read_text(encoding="utf-8")

    assert '"provider_mode": "LIVE"' in exported
    assert "access-token-secret" not in exported
    assert "authorization-code" not in exported
    assert report.overall_classification is (
        UpstoxLiveAcceptanceClassification.LIVE_ACCEPTANCE_PASS
    )


def test_upstox_live_acceptance_cli_missing_token_sample_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("UPSTOX_TOKEN_METADATA_PATH", str(tmp_path / "missing.json"))
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)

    result = CliRunner().invoke(
        app,
        [
            "provider",
            "upstox",
            "live-acceptance",
            "--instrument-key",
            "NSE_EQ|INE303R01014",
            "--max-events",
            "1",
            "--timeout-seconds",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert "Provider Mode: LIVE" in result.stdout
    assert "Overall Classification: TOKEN_UNAVAILABLE" in result.stdout
    assert "Order API Calls: 0" in result.stdout


def test_live_acceptance_and_simulation_remain_isolated(tmp_path: Path) -> None:
    live = _acceptance_harness(
        tmp_path,
        provider=_AcceptanceProvider(
            ticks=(_acceptance_tick("NSE_EQ|INE303R01014", "465", "100"),)
        ),
    ).run(
        instrument_key="NSE_EQ|INE303R01014",
        max_events=1,
        timeout_seconds=5,
    )
    simulation = RecordedUpstoxReadinessAuditEngine().run()

    assert live.provider_mode.value == "LIVE"
    assert live.overall_classification is (
        UpstoxLiveAcceptanceClassification.LIVE_ACCEPTANCE_PASS
    )
    assert simulation.live_provider_connected is False
    assert simulation.live_acceptance_complete is False


def test_upstox_protocol_schema_provenance_and_binding_import() -> None:
    digest = schema_hash()

    assert UPSTOX_FEED_V3_DOC_URL.endswith("/v3/get-market-data-feed/")
    assert len(digest) == 64
    assert UPSTOX_FEED_V3_SCHEMA_VERSION == (
        "upstox-market-data-feed-v3-docs-2026-07-17"
    )
    assert market_data_feed_v3_pb2.FeedResponse is not None


def test_upstox_authorized_uri_redaction_and_single_use() -> None:
    guard = UpstoxAuthorizedUriGuard(
        "wss://api.upstox.com/feed?code=one-time-secret&client_id=abc"
    )

    first = guard.consume()
    second = guard.consume()

    assert first.classification is UpstoxFeedAuthUriClassification.AUTHORIZED
    assert "one-time-secret" not in first.sanitized_uri
    assert "[redacted]" in first.sanitized_uri
    assert second.classification is (
        UpstoxFeedAuthUriClassification.FEED_AUTH_URI_ALREADY_CONSUMED
    )


def test_upstox_subscription_encoder_payload_and_refusals() -> None:
    payload = encode_subscription_request(
        instrument_keys=("NSE_EQ|INE303R01014", "NSE_EQ|INE303R01014"),
        guid="guid-1",
    )

    assert payload == (
        b'{"data":{"instrumentKeys":["NSE_EQ|INE303R01014"],'
        b'"mode":"ltpc"},"guid":"guid-1","method":"sub"}'
    )
    with pytest.raises(ValueError, match="empty"):
        encode_subscription_request(instrument_keys=(), guid="guid-1")
    with pytest.raises(ValueError, match="wildcard"):
        encode_subscription_request(instrument_keys=("NSE_EQ|*",), guid="guid-1")


def test_upstox_protocol_decodes_market_status_snapshot_and_ltpc() -> None:
    market = decode_feed_message(_protocol_fixture("market_status.bin"))
    snapshot = decode_feed_message(_protocol_fixture("snapshot_ltpc.bin"))

    assert market.category is UpstoxFeedMessageCategory.MARKET_STATUS
    assert market.market_status["NSE_EQ"] == "NORMAL_OPEN"
    assert snapshot.category is UpstoxFeedMessageCategory.LIVE_UPDATE
    assert "NSE_EQ|INE303R01014" in snapshot.feeds


def test_upstox_protocol_normalizes_multiple_instruments_ohlc_and_volume() -> None:
    decoded = decode_feed_message(_protocol_fixture("live_update_multi_full.bin"))
    normalized = normalize_feed_message(
        decoded,
        received_at=datetime(2025, 2, 28, 13, 29, 30, tzinfo=UTC),
    )

    assert normalized.category is UpstoxFeedMessageCategory.LIVE_UPDATE
    assert len(normalized.ticks) == 2
    assert normalized.ticks[0].instrument_key == "NSE_EQ|INE303R01014"
    assert normalized.ticks[0].price == Decimal("466.0")
    assert normalized.ticks[0].volume == Decimal("120")
    assert normalized.ohlc["NSE_EQ|INE303R01014"][0]["interval"] == "I1"


def test_upstox_protocol_missing_optional_and_malformed_payloads() -> None:
    decoded = decode_feed_message(_protocol_fixture("missing_optional.bin"))
    normalized = normalize_feed_message(
        decoded,
        received_at=datetime(2025, 2, 28, 13, 29, 30, tzinfo=UTC),
    )

    assert normalized.ticks[0].volume == Decimal("0")
    with pytest.raises(ValueError, match="malformed"):
        decode_feed_message(_protocol_fixture("malformed_payload.bin"))


def test_upstox_protocol_unknown_future_and_metadata_capture() -> None:
    unknown = decode_feed_message(_protocol_fixture("unknown_type.bin"))
    future = normalize_feed_message(
        decode_feed_message(_protocol_fixture("future_timestamp.bin")),
        received_at=datetime(2026, 7, 17, tzinfo=UTC),
    )
    metadata = capture_protocol_metadata(_protocol_fixture("malformed_payload.bin"))

    assert unknown.category is UpstoxFeedMessageCategory.UNKNOWN
    assert "implausible future timestamp" in future.reasons[0]
    assert metadata.decode_success is False
    assert metadata.payload_byte_length > 0


def test_upstox_protocol_sequence_tracker_and_reconnect_reset() -> None:
    tracker = UpstoxSequenceTracker()

    assert tracker.observe(UpstoxFeedMessageCategory.LIVE_UPDATE) == (
        "first message was not market status",
        "live update before snapshot",
    )
    tracker.reset_for_reconnect()
    tracker.observe(UpstoxFeedMessageCategory.MARKET_STATUS)
    diagnostics = tracker.observe(UpstoxFeedMessageCategory.SNAPSHOT)

    assert diagnostics == ()
    assert tracker.market_status_received is True
    assert tracker.snapshot_received is True


def test_upstox_protocol_audit_cli_text_and_json(tmp_path: Path) -> None:
    output = tmp_path / "protocol.json"

    text = CliRunner().invoke(app, ["provider", "upstox", "protocol-audit"])
    json_result = CliRunner().invoke(
        app,
        [
            "provider",
            "upstox",
            "protocol-audit",
            "--format",
            "json",
            "--output",
            str(output),
        ],
    )

    assert text.exit_code == 0
    assert "Overall Classification: PROTOCOL_ADAPTER_READY_FOR_LIVE_TEST" in text.stdout
    assert json_result.exit_code == 0
    exported = output.read_text(encoding="utf-8")
    assert (
        '"overall_classification": "PROTOCOL_ADAPTER_READY_FOR_LIVE_TEST"' in exported
    )
    assert "one-time-secret" not in exported


def test_upstox_protocol_audit_report_ready_and_no_order_api_refs() -> None:
    report = build_protocol_audit_report()

    assert report.overall_classification is (
        UpstoxProtocolAuditClassification.PROTOCOL_ADAPTER_READY_FOR_LIVE_TEST
    )
    assert report.order_api_references_found == 0
    assert report.deterministic_fixture_count >= 7
    assert report.malformed_fixture_rejection_count >= 1
    assert any("MARKET_STATUS" in line for line in render_protocol_audit(report))


def test_upstox_provider_status_cli_does_not_print_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "super-secret-token")

    result = CliRunner().invoke(app, ["provider", "upstox", "status"])

    assert result.exit_code == 0
    assert "super-secret-token" not in result.stdout
    assert "UPSTOX_MARKET_DATA_FEED_V3" in result.stdout


def test_live_cli_does_not_fake_live_data_without_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)
    result = CliRunner().invoke(
        app,
        ["live", "--symbols", "KALYANKJIL,PCJEWELLER"],
    )

    assert result.exit_code == 0
    assert "Live feed unavailable" in result.stdout
    assert "No live recommendations generated." in result.stdout


def test_live_symbol_parser_accepts_comma_separated_symbols() -> None:
    assert _parse_live_symbols(
        symbols=["KALYANKJIL,PCJEWELLER,CUPID"],
        repeated_symbols=None,
    ) == ("KALYANKJIL", "PCJEWELLER", "CUPID")


def test_live_symbol_parser_accepts_repeated_symbol_flags() -> None:
    assert _parse_live_symbols(
        symbols=None,
        repeated_symbols=["KALYANKJIL", "PCJEWELLER"],
    ) == ("KALYANKJIL", "PCJEWELLER")


def test_live_symbol_parser_preserves_order_and_deduplicates() -> None:
    assert _parse_live_symbols(
        symbols=["KALYANKJIL,PCJEWELLER"],
        repeated_symbols=["KALYANKJIL", "CUPID"],
    ) == ("KALYANKJIL", "PCJEWELLER", "CUPID")


def test_live_symbol_parser_rejects_empty_symbols() -> None:
    with pytest.raises(Exception, match="Provide at least one symbol"):
        _parse_live_symbols(symbols=[" , "], repeated_symbols=[])


def test_live_monitor_uses_fake_provider_and_emits_status() -> None:
    provider = _FakeLiveProvider(
        ticks=(
            LiveTick(
                symbol="KALYANKJIL",
                price=Decimal("100"),
                volume=Decimal("25"),
                observed_at=datetime(2026, 7, 9, 9, 15, tzinfo=UTC),
            ),
        )
    )

    snapshots = asyncio.run(
        run_live_monitor(
            provider=provider,
            subscriptions=(
                InstrumentSubscription(
                    symbol="KALYANKJIL",
                    instrument_key="NSE_EQ|KALYANKJIL",
                ),
            ),
            max_ticks=1,
        )
    )

    assert len(snapshots) == 1
    assert snapshots[0].symbol == "KALYANKJIL"
    assert snapshots[0].price == Decimal("100")
    assert snapshots[0].volume == Decimal("25")
    assert snapshots[0].feed_status is LiveFeedStatus.CONNECTED


def test_instrument_subscription_normalizes_symbol() -> None:
    subscription = InstrumentSubscription(
        symbol=" kalyankjil ",
        instrument_key="NSE_EQ|KALYANKJIL",
    )

    assert subscription.symbol == "KALYANKJIL"


def test_feed_health_detects_heartbeat_timeout() -> None:
    engine = FeedHealthEngine(provider_name="Fake")
    observed_at = datetime(2026, 7, 9, 9, 15, tzinfo=UTC)
    engine.mark_connected(authenticated=True, observed_at=observed_at)
    engine.mark_subscribed()
    engine.mark_tick(observed_at=observed_at)

    snapshot = engine.snapshot(observed_at=observed_at + timedelta(seconds=40))

    assert snapshot.status is FeedHealthStatus.STALE
    assert snapshot.heartbeat_age_seconds == Decimal("40.00")


def test_feed_health_reports_reconnect_state() -> None:
    engine = FeedHealthEngine(provider_name="Fake")

    engine.mark_reconnecting()
    snapshot = engine.snapshot(observed_at=datetime(2026, 7, 9, 9, 15, tzinfo=UTC))

    assert snapshot.status is FeedHealthStatus.RECONNECTING
    assert snapshot.reconnect_attempts == 1


def test_tick_quality_detects_duplicate_ticks() -> None:
    engine = TickQualityEngine(subscriptions=(_subscription("AAA"),))
    tick = LiveTick(
        symbol="AAA",
        price=Decimal("100"),
        volume=Decimal("10"),
        observed_at=datetime(2026, 7, 9, 9, 15, tzinfo=UTC),
    )

    assert engine.validate_tick(tick).status is TickQualityStatus.VALID
    duplicate = engine.validate_tick(tick)

    assert duplicate.status is TickQualityStatus.SUSPECT
    assert "duplicate timestamp" in duplicate.reasons
    assert "duplicate price" in duplicate.reasons


def test_tick_quality_rejects_invalid_ticks() -> None:
    engine = TickQualityEngine(subscriptions=(_subscription("AAA"),))

    assessment = engine.validate_fields(
        symbol="ZZZ",
        price=Decimal("100"),
        volume=Decimal("10"),
        observed_at=datetime(2026, 7, 9, 9, 15, tzinfo=UTC),
    )

    assert assessment.status is TickQualityStatus.INVALID
    assert "invalid instrument" in assessment.reasons


def test_tick_quality_rejects_zero_price_and_negative_volume() -> None:
    engine = TickQualityEngine(subscriptions=(_subscription("AAA"),))

    assessment = engine.validate_fields(
        symbol="AAA",
        price=Decimal("0"),
        volume=Decimal("-1"),
        observed_at=datetime(2026, 7, 9, 9, 15, tzinfo=UTC),
    )

    assert assessment.status is TickQualityStatus.INVALID
    assert "zero price" in assessment.reasons
    assert "negative volume" in assessment.reasons
    assert engine.statistics.invalid_ticks == 1


def test_latency_monitor_calculates_rolling_metrics() -> None:
    monitor = LatencyMonitor(window_size=5)
    exchange = datetime(2026, 7, 9, 9, 15, tzinfo=UTC)

    monitor.record(
        symbol="AAA",
        exchange_timestamp=exchange,
        provider_timestamp=exchange + timedelta(milliseconds=100),
        alpha_receive_timestamp=exchange + timedelta(milliseconds=200),
        indicator_completion_timestamp=exchange + timedelta(milliseconds=300),
        recommendation_completion_timestamp=exchange + timedelta(milliseconds=500),
    )
    summary = monitor.summary()

    assert summary.sample_count == 1
    assert summary.rolling_average_seconds == Decimal("0.5000")
    assert summary.rolling_p95_seconds == Decimal("0.5000")


def test_feed_degradation_when_subscription_missing() -> None:
    engine = FeedHealthEngine(provider_name="Fake")
    observed_at = datetime(2026, 7, 9, 9, 15, tzinfo=UTC)
    engine.mark_connected(authenticated=True, observed_at=observed_at)

    snapshot = engine.snapshot(observed_at=observed_at)

    assert snapshot.status is FeedHealthStatus.DEGRADED


def test_market_session_transitions_and_weekend_holiday_detection() -> None:
    holiday = date(2026, 7, 10)
    engine = MarketSessionEngine(holidays=frozenset({holiday}))

    assert (
        engine.state_at(datetime(2026, 7, 9, 9, 5, tzinfo=UTC))
        is MarketSessionState.PRE_OPEN
    )
    assert (
        engine.state_at(datetime(2026, 7, 9, 10, 30, tzinfo=UTC))
        is MarketSessionState.MID_SESSION
    )
    assert (
        engine.state_at(datetime(2026, 7, 9, 14, 45, tzinfo=UTC))
        is MarketSessionState.POWER_HOUR
    )
    assert (
        engine.state_at(datetime(2026, 7, 11, 10, 0, tzinfo=UTC))
        is MarketSessionState.WEEKEND
    )
    assert (
        engine.state_at(datetime(2026, 7, 10, 10, 0, tzinfo=UTC))
        is MarketSessionState.HOLIDAY
    )
    assert engine.is_trading(datetime(2026, 7, 9, 10, 30, tzinfo=UTC))


def test_registry_updates_tick_bar_and_feed_quality() -> None:
    registry = LiveInstrumentRegistry((_subscription("AAA"),))
    health = FeedHealthEngine(provider_name="Fake")
    observed_at = datetime(2026, 7, 9, 9, 15, tzinfo=UTC)
    health.mark_connected(authenticated=True, observed_at=observed_at)
    health.mark_subscribed()
    tick = LiveTick("AAA", Decimal("100"), Decimal("10"), observed_at)
    bar = LiveBarBuilder(timeframe_minutes=1).update(tick)
    snapshot = health.snapshot(observed_at=observed_at)

    registry.update_tick(
        tick,
        session=MarketSessionState.OPEN,
        feed_health=snapshot,
        latency=LatencyMonitor().summary(),
        observed_at=observed_at,
    )
    registry.update_bar(bar)

    state = registry.state("AAA")
    assert state is not None
    assert state.tick_count == 1
    assert state.bar_count == 1
    assert state.feed_quality == Decimal("100")


def test_live_risk_warnings_explain_stale_feed() -> None:
    health = FeedHealthEngine(provider_name="Fake")
    observed_at = datetime(2026, 7, 9, 9, 15, tzinfo=UTC)
    health.mark_connected(authenticated=True, observed_at=observed_at)
    health.mark_subscribed()
    health.mark_tick(observed_at=observed_at)
    stale_snapshot = health.snapshot(observed_at=observed_at + timedelta(seconds=45))

    warnings = LiveRiskEngine().evaluate(
        LiveRiskContext(
            tick=None,
            quote=None,
            bar=None,
            previous_tick=None,
            previous_bar=None,
            feed_health=stale_snapshot,
            observed_at=observed_at + timedelta(seconds=45),
        )
    )

    assert warnings[0].message == "Feed stale for 45.00 seconds"
    assert warnings[0].why
    assert warnings[0].operator_action


def test_live_cli_compact_snapshot_output(capsys: pytest.CaptureFixture[str]) -> None:
    snapshot = _fake_snapshot()

    _print_live_snapshot(snapshot, verbose=False)

    output = capsys.readouterr().out
    assert "Provider" in output
    assert "Feed Quality:" in output
    assert "Risk Flags:" in output
    assert "Tick Diagnostics" not in output


def test_live_cli_verbose_snapshot_output(capsys: pytest.CaptureFixture[str]) -> None:
    snapshot = _fake_snapshot()

    _print_live_snapshot(snapshot, verbose=True)

    output = capsys.readouterr().out
    assert "Tick Diagnostics" in output
    assert "Latency Breakdown" in output
    assert "Health History" in output


class _FakeLiveProvider:
    def __init__(self, *, ticks: tuple[LiveTick, ...]) -> None:
        self._ticks = ticks
        self._status = LiveFeedStatus.DISCONNECTED
        self._subscriptions: tuple[InstrumentSubscription, ...] = ()

    @property
    def status(self) -> LiveFeedStatus:
        return self._status

    @property
    def session_state(self) -> MarketSessionState:
        return MarketSessionState.OPEN

    def is_stale(self, *, now: datetime) -> bool:
        return False

    async def connect(self) -> None:
        self._status = LiveFeedStatus.CONNECTED

    async def subscribe(
        self,
        subscriptions: Iterable[InstrumentSubscription],
    ) -> None:
        self._subscriptions = tuple(subscriptions)

    async def ticks(self) -> AsyncIterator[LiveTick]:
        for tick in self._ticks:
            yield tick

    async def close(self) -> None:
        self._status = LiveFeedStatus.DISCONNECTED


class _FakeUpstoxTransport:
    def __init__(
        self,
        *,
        token_response: dict[str, Any] | None = None,
        profile_error: Exception | None = None,
        feed_response: dict[str, Any] | None = None,
    ) -> None:
        self.token_response = token_response or {"access_token": "valid-token"}
        self.profile_error = profile_error
        self.feed_response = feed_response or {
            "data": {
                "authorized_redirect_uri": (
                    "wss://example.upstox.com/market-data-feeder/v3"
                )
            }
        }

    def post_form(self, url, form, headers):  # noqa: ANN001, ANN201
        assert "client_secret" in form
        assert "code" in form
        return self.token_response

    def get_json(self, url, headers):  # noqa: ANN001, ANN201
        assert headers["Authorization"].startswith("Bearer ")
        if "user/profile" in url:
            if self.profile_error is not None:
                raise self.profile_error
            return {"status": "success", "data": {"user_id": "test"}}
        if "market-data-feed/authorize" in url:
            return self.feed_response
        return {"status": "success"}


class _RecordingUpstoxTransport:
    def __init__(self) -> None:
        self.url = ""
        self.form: dict[str, str] = {}
        self.headers: dict[str, str] = {}

    def post_form(self, url, form, headers):  # noqa: ANN001, ANN201
        self.url = str(url)
        self.form = dict(form)
        self.headers = dict(headers)
        return {"access_token": "valid-token"}

    def get_json(self, url, headers):  # noqa: ANN001, ANN201
        return {"status": "success"}


class _RejectingUpstoxTransport:
    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        self.message = message

    def post_form(self, url, form, headers):  # noqa: ANN001, ANN201
        body = (
            '{"status":"error","errors":[{"errorCode":"'
            + self.error_code
            + '","error_code":"'
            + self.error_code
            + '","message":"'
            + self.message
            + '","invalidValue":"'
            + str(form.get("client_secret", ""))
            + '"}]}'
        )
        raise urllib.error.HTTPError(
            url=str(url),
            code=400,
            msg="bad request",
            hdrs=None,
            fp=io.BytesIO(body.encode("utf-8")),
        )

    def get_json(self, url, headers):  # noqa: ANN001, ANN201
        return {"status": "success"}


class _FakeHttpResponse:
    def __init__(self, body: str) -> None:
        self.body = body.encode("utf-8")

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, exc_type, exc, traceback):  # noqa: ANN001, ANN204
        return False

    def read(self) -> bytes:
        return self.body


class _AcceptanceAuth:
    def __init__(
        self,
        *,
        local_status: UpstoxTokenStatus = UpstoxTokenStatus.TOKEN_VALID,
        remote_status: UpstoxTokenStatus = UpstoxTokenStatus.TOKEN_VALID,
        remote_reason: str = "Provider accepted the configured token.",
        feed_authorized: bool = True,
        secret: str = "token",
    ) -> None:
        self.local_status = local_status
        self.remote_status = remote_status
        self.remote_reason = remote_reason
        self.feed_authorized = feed_authorized
        self.secret = secret

    def load_metadata(self) -> object | None:
        if self.local_status is UpstoxTokenStatus.TOKEN_MISSING:
            return None
        return object()

    def validate_token(self, *, remote: bool = True) -> UpstoxTokenValidation:
        status = self.remote_status if remote else self.local_status
        reason = self.remote_reason if remote else "Token is locally valid."
        return UpstoxTokenValidation(
            status=status,
            token_configured=status is not UpstoxTokenStatus.TOKEN_MISSING,
            expected_expiry=datetime(2026, 7, 18, tzinfo=UTC),
            last_validation_at=datetime(2026, 7, 17, 9, 0, tzinfo=UTC),
            token_fingerprint="safe-fingerprint",
            reason=reason,
        )

    def authorize_market_data_feed_v3(self) -> UpstoxFeedAuthorization:
        return UpstoxFeedAuthorization(
            authorized=self.feed_authorized,
            feed_api_version="UPSTOX_MARKET_DATA_FEED_V3",
            authorized_redirect_uri_present=self.feed_authorized,
            status=(
                "AUTHORIZED" if self.feed_authorized else "FEED_AUTHORIZATION_FAILED"
            ),
            reason=(
                "Authorized V3 websocket redirect URI received."
                if self.feed_authorized
                else "Feed authorization failed."
            ),
        )


class _AcceptanceProvider:
    def __init__(
        self,
        *,
        ticks: tuple[LiveTick, ...] = (),
        connect_error: RuntimeError | None = None,
        subscribe_error: ValueError | None = None,
        interrupt: bool = False,
    ) -> None:
        self._ticks = ticks
        self.connect_error = connect_error
        self.subscribe_error = subscribe_error
        self.interrupt = interrupt
        self._status = LiveFeedStatus.DISCONNECTED
        self.closed = False

    @property
    def status(self) -> LiveFeedStatus:
        return self._status

    async def connect(self) -> None:
        if self.connect_error is not None:
            raise self.connect_error
        self._status = LiveFeedStatus.CONNECTED

    async def subscribe(
        self,
        subscriptions: Iterable[InstrumentSubscription],
    ) -> None:
        tuple(subscriptions)
        if self.subscribe_error is not None:
            raise self.subscribe_error

    async def close(self) -> None:
        self.closed = True
        self._status = LiveFeedStatus.DISCONNECTED

    async def _tick_stream(self) -> AsyncIterator[LiveTick]:
        if self.interrupt:
            raise KeyboardInterrupt
        for tick in self._ticks:
            yield tick

    def ticks(self) -> AsyncIterator[LiveTick]:
        return self._tick_stream()


def _acceptance_harness(
    tmp_path: Path,
    *,
    auth: _AcceptanceAuth | None = None,
    provider: _AcceptanceProvider | None = None,
) -> UpstoxLiveAcceptanceHarness:
    selected_provider = provider or _AcceptanceProvider()
    return UpstoxLiveAcceptanceHarness(
        auth=auth or _AcceptanceAuth(),
        resolver=UpstoxInstrumentResolver(
            registry_path=_acceptance_registry(tmp_path),
            registry_timestamp=datetime(2026, 7, 17, 8, 0, tzinfo=UTC),
        ),
        provider_factory=lambda: selected_provider,
        now=lambda: datetime(2026, 7, 17, 9, 15, 10, tzinfo=UTC),
    )


def _acceptance_registry(tmp_path: Path) -> Path:
    path = tmp_path / "upstox-registry.json"
    path.write_text(
        '[{"tradingsymbol":"KALYANKJIL","exchange":"NSE",'
        '"instrument_key":"NSE_EQ|INE303R01014","instrument_type":"EQ"}]',
        encoding="utf-8",
    )
    return path


def _acceptance_tick(
    instrument_key: str,
    price: str,
    volume: str,
    *,
    second: int = 1,
) -> LiveTick:
    symbol = "KALYANKJIL" if instrument_key == "NSE_EQ|INE303R01014" else "UNKNOWN"
    observed_at = datetime(2026, 7, 17, 9, 15, second, tzinfo=UTC)
    return LiveTick(
        symbol=symbol,
        price=Decimal(price),
        volume=Decimal(volume),
        observed_at=observed_at,
        exchange_timestamp=observed_at,
        provider_timestamp=observed_at,
        received_at=observed_at,
        instrument_key=instrument_key,
    )


def _protocol_fixture(name: str) -> bytes:
    return (Path("alpha/live/protocol_fixtures") / name).read_bytes()


def _upstox_config(tmp_path: Path, *, token: str | None) -> UpstoxAuthConfig:
    return UpstoxAuthConfig(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="http://localhost/callback",
        access_token=token,
        websocket_url="wss://api.upstox.com/v3/feed/market-data-feed",
        token_metadata_path=tmp_path / "upstox-metadata.json",
    )


def _token_fingerprint(token: str) -> str:
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _subscription(symbol: str) -> InstrumentSubscription:
    return InstrumentSubscription(symbol=symbol, instrument_key=f"NSE_EQ|{symbol}")


def _fake_snapshot():
    provider = _FakeLiveProvider(ticks=())
    provider._status = LiveFeedStatus.CONNECTED
    tick = LiveTick(
        symbol="AAA",
        price=Decimal("100"),
        volume=Decimal("10"),
        observed_at=datetime(2026, 7, 9, 9, 15, tzinfo=UTC),
    )
    bar = LiveBarBuilder(timeframe_minutes=1).update(tick)
    snapshots = asyncio.run(
        run_live_monitor(
            provider=_FakeLiveProvider(ticks=(tick,)),
            subscriptions=(_subscription("AAA"),),
            max_ticks=1,
        )
    )
    assert bar.symbol == "AAA"
    return snapshots[0]
