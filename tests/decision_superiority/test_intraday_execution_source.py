from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from alpha.decision_superiority.intraday_execution_models import (
    IntradayBar,
    IntradayExecutionPolicy,
    IntradayReadiness,
    IntradaySourceRequest,
)
from alpha.decision_superiority.intraday_execution_source import (
    HttpResponse,
    audit_intraday_bars,
    cache_paths,
    fetch_upstox_v3_bars,
    parse_upstox_v3_payload,
    source_request_id,
    upstox_v3_request_url,
)

IST = timezone(timedelta(hours=5, minutes=30))


class FakeTransport:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls = 0
        self.last_headers: Mapping[str, str] | None = None

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> HttpResponse:
        assert url.startswith("https://api.upstox.com/v3/historical-candle/")
        assert timeout_seconds == 30.0
        self.calls += 1
        self.last_headers = headers
        return HttpResponse(
            status_code=200,
            body=self.body,
            content_type="application/json",
        )


def _request() -> IntradaySourceRequest:
    return IntradaySourceRequest(
        governed_identity="nse:isin:INE000A01000",
        instrument_key="NSE_EQ|INE000A01000",
        from_date=date(2024, 1, 2),
        to_date=date(2024, 1, 2),
    )


def _payload(rows: list[list[object]]) -> dict[str, object]:
    return {"status": "success", "data": {"candles": rows}}


def _regular_session_bars() -> tuple[IntradayBar, ...]:
    start = datetime(2024, 1, 2, 9, 15, tzinfo=IST)
    rows: list[IntradayBar] = []
    for offset in range(75):
        timestamp = start + timedelta(minutes=offset * 5)
        price = 100.0 + offset / 100
        rows.append(
            IntradayBar(
                governed_identity="nse:isin:INE000A01000",
                instrument_key="NSE_EQ|INE000A01000",
                timestamp=timestamp,
                open=price,
                high=price + 0.20,
                low=price - 0.20,
                close=price + 0.05,
                volume=1_000 + offset,
            )
        )
    return tuple(rows)


def test_upstox_request_url_and_identity_are_stable() -> None:
    request = _request()

    assert upstox_v3_request_url(request) == (
        "https://api.upstox.com/v3/historical-candle/"
        "NSE_EQ%7CINE000A01000/minutes/5/2024-01-02/2024-01-02"
    )
    assert source_request_id(request) == source_request_id(request)
    assert len(source_request_id(request)) == 64


def test_parse_upstox_payload_sorts_descending_source_rows() -> None:
    request = _request()
    payload = _payload(
        [
            ["2024-01-02T09:20:00+05:30", 101, 102, 100, 101.5, 2000, 0],
            ["2024-01-02T09:15:00+05:30", 100, 101, 99, 100.5, 1000, 0],
        ]
    )

    bars = parse_upstox_v3_payload(payload, request=request)

    assert [bar.timestamp.hour * 60 + bar.timestamp.minute for bar in bars] == [
        555,
        560,
    ]
    assert bars[0].governed_identity == request.governed_identity
    assert bars[0].instrument_key == request.instrument_key


def test_fetch_cache_is_immutable_and_never_persists_token(tmp_path: Path) -> None:
    request = _request()
    body = json.dumps(
        _payload([["2024-01-02T09:15:00+05:30", 100, 101, 99, 100.5, 1000, 0]])
    ).encode()
    transport = FakeTransport(body)

    first = fetch_upstox_v3_bars(
        request,
        access_token="first-secret-token",
        cache_root=tmp_path,
        transport=transport,
        retrieved_at=datetime(2026, 7, 30, 16, 0, tzinfo=UTC),
    )
    second = fetch_upstox_v3_bars(
        request,
        access_token="different-secret-token",
        cache_root=tmp_path,
        transport=transport,
    )

    assert first == second
    assert transport.calls == 1
    assert transport.last_headers is not None
    assert transport.last_headers["Authorization"] == "Bearer first-secret-token"

    raw_path, manifest_path = cache_paths(tmp_path, request)
    combined = raw_path.read_bytes() + manifest_path.read_bytes()
    assert b"first-secret-token" not in combined
    assert b"different-secret-token" not in combined
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["credential_fields_persisted"] is False
    assert manifest["request"]["interval"] == 5


def test_complete_regular_session_is_source_ready() -> None:
    audit = audit_intraday_bars(_regular_session_bars())

    assert audit.readiness is IntradayReadiness.SOURCE_READY
    assert audit.blockers == ()
    assert len(audit.validation_rows) == 75
    assert len(audit.session_rows) == 1
    session = audit.session_rows[0]
    assert session["session_date"] == "2024-01-02"
    assert session["bar_count"] == 75
    assert session["expected_bar_count"] == 75
    assert session["first_bar"] == "2024-01-02T09:15:00+05:30"
    assert session["last_bar"] == "2024-01-02T15:25:00+05:30"
    assert float(session["session_open"]) == pytest.approx(100.0)
    assert float(session["session_high"]) == pytest.approx(100.94)
    assert float(session["session_low"]) == pytest.approx(99.8)
    assert float(session["session_close"]) == pytest.approx(100.79)
    assert session["session_volume"] == 77_775
    assert session["count_passed"] is True
    assert session["boundary_passed"] is True


def test_duplicate_and_impossible_bar_fail_closed() -> None:
    bars = list(_regular_session_bars())
    duplicate = bars[0]
    broken = IntradayBar(
        governed_identity=duplicate.governed_identity,
        instrument_key=duplicate.instrument_key,
        timestamp=duplicate.timestamp + timedelta(minutes=5),
        open=100.0,
        high=99.0,
        low=98.0,
        close=100.0,
        volume=100,
    )

    audit = audit_intraday_bars((duplicate, duplicate, broken))

    assert audit.readiness is IntradayReadiness.SESSION_INTEGRITY_DEFECT
    assert any("DUPLICATE_TIMESTAMP" in blocker for blocker in audit.blockers)
    assert any("IMPOSSIBLE_OHLC" in blocker for blocker in audit.blockers)
    assert any("SESSION_BAR_COUNT_MISMATCH" in blocker for blocker in audit.blockers)


def test_policy_keeps_primary_interval_frozen() -> None:
    policy = IntradayExecutionPolicy()

    assert policy.interval_minutes == 5
    assert policy.expected_regular_bar_count == 75
