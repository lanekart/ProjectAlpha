from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest
import requests
from typer.testing import CliRunner

from alpha.historical_truth.cli import historical_truth_app
from alpha.historical_truth.event_sourced_universe_engine import (
    EventSourcedIntervalReconstructor,
    EventSourcedUniverseCertificationEngine,
    _reject_conflicting_events,
)
from alpha.historical_truth.event_sourced_universe_exports import (
    EventSourcedUniverseArtifactExporter,
)
from alpha.historical_truth.event_sourced_universe_models import (
    PRODUCTION_INFLUENCE,
    EventAdmissionState,
    EventConfidenceState,
    EventSourceSpec,
    EventSourceStatus,
    MembershipCertificationState,
    MembershipEffect,
    SecurityEventRecord,
    SecurityEventType,
    TradabilityEffect,
    stable_event_id,
)
from alpha.historical_truth.event_sourced_universe_sources import (
    EVENT_SOURCE_HEADERS,
    OfficialSecurityEventStore,
    ParsedEventSource,
)


class FakeResponse:
    def __init__(
        self,
        content: bytes,
        url: str,
        *,
        status_code: int = 200,
        content_type: str = "text/csv",
    ) -> None:
        self.content = content
        self.url = url
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.history: tuple[Any, ...] = ()

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
        allow_redirects: bool,
    ) -> FakeResponse:
        del timeout, allow_redirects
        self.calls.append((url, headers))
        self.response.url = url
        return self.response


def _spec(
    event_type: SecurityEventType,
    parser: str = "generic_csv_v1",
    *,
    url: str = "https://nsearchives.nseindia.com/content/equities/events.csv",
    effective_date: date | None = None,
) -> EventSourceSpec:
    return EventSourceSpec(
        f"source_{event_type.value.lower()}",
        "TEST",
        url,
        parser,
        event_type,
        effective_date,
    )


def _event(
    event_type: SecurityEventType,
    effective_date: date,
    *,
    isin: str = "INE000A01001",
    symbol: str = "AAA",
    series: str = "EQ",
    old_symbol: str | None = None,
    old_isin: str | None = None,
    status: EventAdmissionState = EventAdmissionState.ADMITTED,
) -> SecurityEventRecord:
    membership, tradability = {
        SecurityEventType.LISTED: (MembershipEffect.OPEN, TradabilityEffect.OPEN),
        SecurityEventType.RELISTED: (MembershipEffect.OPEN, TradabilityEffect.OPEN),
        SecurityEventType.SUSPENDED: (
            MembershipEffect.UNCHANGED,
            TradabilityEffect.CLOSE,
        ),
        SecurityEventType.SUSPENSION_REVOKED: (
            MembershipEffect.UNCHANGED,
            TradabilityEffect.OPEN,
        ),
        SecurityEventType.DELISTED: (MembershipEffect.CLOSE, TradabilityEffect.CLOSE),
    }.get(event_type, (MembershipEffect.UNCHANGED, TradabilityEffect.UNCHANGED))
    event_id = stable_event_id(
        "fixture",
        event_type,
        effective_date,
        old_symbol,
        symbol,
        old_isin,
        isin,
    )
    key = f"nse:isin:{isin}"
    return SecurityEventRecord(
        event_id,
        "NSE",
        event_type,
        effective_date,
        None,
        old_symbol,
        symbol,
        series,
        series,
        old_isin,
        isin,
        "Alpha Limited",
        f"nse:isin:{old_isin}" if old_isin else key,
        key,
        membership,
        tradability,
        "fixture",
        "https://nsearchives.nseindia.com/fixture.csv",
        status,
        EventConfidenceState.HIGH,
    )


@pytest.mark.parametrize(
    ("event_type", "expected_membership", "expected_tradability"),
    [
        (SecurityEventType.LISTED, MembershipEffect.OPEN, TradabilityEffect.OPEN),
        (
            SecurityEventType.SUSPENDED,
            MembershipEffect.UNCHANGED,
            TradabilityEffect.CLOSE,
        ),
        (
            SecurityEventType.SUSPENSION_REVOKED,
            MembershipEffect.UNCHANGED,
            TradabilityEffect.OPEN,
        ),
        (SecurityEventType.DELISTED, MembershipEffect.CLOSE, TradabilityEffect.CLOSE),
        (SecurityEventType.MERGED, MembershipEffect.CLOSE, TradabilityEffect.CLOSE),
        (
            SecurityEventType.SCHEME_EFFECTIVE,
            MembershipEffect.UNCHANGED,
            TradabilityEffect.UNCHANGED,
        ),
    ],
)
def test_official_event_parsing(
    tmp_path: Path,
    event_type: SecurityEventType,
    expected_membership: MembershipEffect,
    expected_tradability: TradabilityEffect,
) -> None:
    raw = (
        "symbol,series,isin,effective_date,status\n"
        f"AAA,EQ,INE000A01001,2020-01-03,{event_type.value}\n"
    ).encode()
    store = OfficialSecurityEventStore(
        tmp_path,
        now=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )
    result = store.acquire(
        (_spec(event_type),),
        session=FakeSession(FakeResponse(raw, "")),
    )[0]

    assert result.inventory.status is EventSourceStatus.ACQUIRED
    assert result.events[0].event_type is event_type
    assert result.events[0].membership_effect is expected_membership
    assert result.events[0].tradability_effect is expected_tradability
    assert result.inventory.sha256
    assert result.inventory.source_path


def test_symbol_and_name_change_parsers(tmp_path: Path) -> None:
    store = OfficialSecurityEventStore(tmp_path)
    symbol_raw = b"Alpha Limited,AAA,AAB,03-JAN-2020\n"
    symbol = store.acquire(
        (_spec(SecurityEventType.SYMBOL_CHANGED, "nse_symbol_change_csv_v1"),),
        session=FakeSession(FakeResponse(symbol_raw, "")),
    )[0]
    name_raw = (
        b"NCH_SYMBOL,NCH_PREV_NAME,NCH_NEW_NAME,NCH_DT\n"
        b"AAB,Old Alpha,Alpha Limited,03-JAN-2020\n"
    )
    name = store.acquire(
        (_spec(SecurityEventType.NAME_CHANGED, "nse_name_change_csv_v1"),),
        session=FakeSession(FakeResponse(name_raw, "")),
    )[0]

    assert (symbol.events[0].old_symbol, symbol.events[0].new_symbol) == (
        "AAA",
        "AAB",
    )
    assert name.events[0].new_symbol == "AAB"
    assert name.events[0].security_name == "Alpha Limited"


def test_isin_change_and_suspension_revocation_parsing(tmp_path: Path) -> None:
    raw = (
        b"symbol,series,old_isin,new_isin,effective_date,status\n"
        b"AAA,EQ,INE000A01001,INE000B01002,2020-01-03,RESTORED\n"
    )
    result = OfficialSecurityEventStore(tmp_path).acquire(
        (_spec(SecurityEventType.SUSPENDED),),
        session=FakeSession(FakeResponse(raw, "")),
    )[0]

    assert result.events[0].event_type is SecurityEventType.SUSPENSION_REVOKED
    assert result.events[0].old_isin == "INE000A01001"
    assert result.events[0].new_isin == "INE000B01002"


def test_mii_checkpoint_emits_listing_and_respects_active_status(
    tmp_path: Path,
) -> None:
    raw = (
        b"TckrSymb,SctySrs,ISIN,Sgmt,ListgDt,ElgbltyNrmlMkt,DelFlg\n"
        b"AAA,EQ,INE000A01001,CM,1577923200,1,N\n"
        b"OLD,EQ,INE000B01002,CM,1577923200,0,Y\n"
    )
    result = OfficialSecurityEventStore(tmp_path).acquire(
        (
            _spec(
                SecurityEventType.CHECKPOINT_PRESENT,
                "nse_mii_checkpoint_csv_v1",
                effective_date=date(2020, 1, 6),
            ),
        ),
        session=FakeSession(FakeResponse(raw, "")),
    )[0]
    active = tuple(item for item in result.events if item.new_isin == "INE000A01001")
    inactive_checkpoint = next(
        item
        for item in result.events
        if item.new_isin == "INE000B01002"
        and item.event_type is SecurityEventType.CHECKPOINT_PRESENT
    )

    assert {item.event_type for item in active} == {
        SecurityEventType.CHECKPOINT_PRESENT,
        SecurityEventType.LISTED,
    }
    assert next(
        item for item in active if item.event_type is SecurityEventType.LISTED
    ).effective_date == date(2020, 1, 2)
    assert inactive_checkpoint.admission_state is EventAdmissionState.PROVISIONAL
    assert result.inventory.events_admitted == 3
    assert result.inventory.events_rejected == 1


def test_wrong_segment_duplicate_and_wrong_date_are_rejected(tmp_path: Path) -> None:
    raw = (
        b"symbol,series,isin,effective_date,segment\n"
        b"AAA,EQ,INE000A01001,2020-01-03,FO\n"
        b"BBB,EQ,INE000B01002,2020-01-03,CM\n"
        b"BBB,EQ,INE000B01002,2020-01-03,CM\n"
    )
    store = OfficialSecurityEventStore(tmp_path)
    result = store.acquire(
        (_spec(SecurityEventType.LISTED),),
        session=FakeSession(FakeResponse(raw, "")),
    )[0]
    dated = store.acquire(
        (
            _spec(
                SecurityEventType.CHECKPOINT_PRESENT,
                url=(
                    "https://nsearchives.nseindia.com/content/cm/"
                    "NSE_CM_security_01012020.csv.gz"
                ),
                effective_date=date(2020, 1, 2),
            ),
        ),
        session=FakeSession(FakeResponse(raw, "")),
    )[0]

    assert {item.failure_code for item in result.rejected} == {
        "WRONG_SEGMENT",
        "DUPLICATE_EVENT",
    }
    assert dated.inventory.failure_code == "WRONG_EFFECTIVE_DATE"


def test_official_host_and_response_type_are_required(tmp_path: Path) -> None:
    store = OfficialSecurityEventStore(tmp_path)
    unofficial = store.acquire(
        (
            _spec(
                SecurityEventType.LISTED,
                url="https://example.com/events.csv",
            ),
        ),
        session=FakeSession(FakeResponse(b"symbol,date\nAAA,2020-01-01\n", "")),
    )[0]
    html = store.acquire(
        (_spec(SecurityEventType.LISTED),),
        session=FakeSession(
            FakeResponse(b"<html>blocked</html>", "", content_type="text/html")
        ),
    )[0]

    assert unofficial.inventory.failure_code == "UNOFFICIAL_HOST"
    assert html.inventory.failure_code == "HTML_MASQUERADING_AS_DATA"


def test_immutable_reuse_and_checksum_mismatch(tmp_path: Path) -> None:
    raw = b"symbol,series,isin,date_of_listing\nAAA,EQ,INE000A01001,03-JAN-2020\n"
    store = OfficialSecurityEventStore(tmp_path)
    spec = _spec(SecurityEventType.LISTED)
    acquired = store.acquire(
        (spec,),
        session=FakeSession(FakeResponse(raw, "")),
    )[0]
    reused = store.verify_or_missing((spec,))[0]
    Path(str(acquired.inventory.source_path)).write_bytes(raw + b"corrupt")
    mismatch = store.verify_or_missing((spec,))[0]

    assert reused.inventory.status is EventSourceStatus.REUSED
    assert reused.events == acquired.events
    assert mismatch.inventory.failure_code == "CHECKSUM_MISMATCH"


def test_required_request_headers_are_preserved(tmp_path: Path) -> None:
    raw = b"symbol,series,isin,date_of_listing\nAAA,EQ,INE000A01001,2020-01-03\n"
    session = FakeSession(FakeResponse(raw, ""))
    OfficialSecurityEventStore(tmp_path).acquire(
        (_spec(SecurityEventType.LISTED),),
        session=session,
    )

    assert session.calls[0][1] == EVENT_SOURCE_HEADERS


def test_models_are_immutable() -> None:
    event = _event(SecurityEventType.LISTED, date(2020, 1, 2))
    with pytest.raises(FrozenInstanceError):
        event.new_symbol = "CHANGED"


def test_listing_opens_membership_and_delisting_closes_it() -> None:
    sessions = tuple(date(2020, 1, day) for day in range(2, 11))
    events = (
        _event(SecurityEventType.LISTED, date(2020, 1, 3)),
        _event(SecurityEventType.DELISTED, date(2020, 1, 8)),
    )
    result = EventSourcedIntervalReconstructor().reconstruct(events, sessions)

    assert result.membership[0].valid_from == date(2020, 1, 3)
    assert result.membership[0].valid_to == date(2020, 1, 7)
    assert result.membership[0].state is (
        MembershipCertificationState.CERTIFIED_ACTIVE_TRADABLE
    )
    assert result.delistings[0].effective_date == date(2020, 1, 8)


def test_relisting_opens_a_new_non_overlapping_membership_interval() -> None:
    sessions = tuple(date(2020, 1, day) for day in range(2, 11))
    events = (
        _event(SecurityEventType.LISTED, date(2020, 1, 2)),
        _event(SecurityEventType.DELISTED, date(2020, 1, 5)),
        _event(SecurityEventType.RELISTED, date(2020, 1, 8)),
    )
    result = EventSourcedIntervalReconstructor().reconstruct(
        events,
        sessions,
        checkpoint_identities=frozenset({"nse:isin:INE000A01001"}),
    )

    assert [(item.valid_from, item.valid_to) for item in result.membership] == [
        (date(2020, 1, 2), date(2020, 1, 4)),
        (date(2020, 1, 8), date(2020, 1, 10)),
    ]


def test_suspension_pauses_tradability_without_closing_membership() -> None:
    sessions = tuple(date(2020, 1, day) for day in range(2, 11))
    events = (
        _event(SecurityEventType.LISTED, date(2020, 1, 2)),
        _event(SecurityEventType.SUSPENDED, date(2020, 1, 5)),
        _event(SecurityEventType.SUSPENSION_REVOKED, date(2020, 1, 8)),
    )
    result = EventSourcedIntervalReconstructor().reconstruct(
        events,
        sessions,
        checkpoint_identities=frozenset({"nse:isin:INE000A01001"}),
    )

    assert len(result.membership) == 1
    assert [item.tradable for item in result.tradability] == [True, False, True]
    assert result.tradability[1].state is (
        MembershipCertificationState.CERTIFIED_ACTIVE_SUSPENDED
    )
    assert result.suspensions[0].restored_on == date(2020, 1, 8)


def test_missing_restoration_and_termination_remain_unresolved() -> None:
    sessions = tuple(date(2020, 1, day) for day in range(2, 11))
    events = (
        _event(SecurityEventType.LISTED, date(2020, 1, 2)),
        _event(SecurityEventType.SUSPENDED, date(2020, 1, 5)),
    )
    result = EventSourcedIntervalReconstructor().reconstruct(events, sessions)

    assert result.membership[0].state is (
        MembershipCertificationState.UNRESOLVED_NO_TERMINATION_EVIDENCE
    )
    assert result.suspensions[0].final_status is (
        MembershipCertificationState.UNRESOLVED_SUSPENSION_STATE
    )


def test_symbol_change_creates_adjacent_intervals_for_same_isin() -> None:
    sessions = tuple(date(2020, 1, day) for day in range(2, 11))
    listed = _event(SecurityEventType.LISTED, date(2020, 1, 2), symbol="AAA")
    changed = _event(
        SecurityEventType.SYMBOL_CHANGED,
        date(2020, 1, 6),
        symbol="AAB",
        old_symbol="AAA",
    )
    result = EventSourcedIntervalReconstructor().reconstruct(
        (listed, changed),
        sessions,
        checkpoint_identities=frozenset({"nse:isin:INE000A01001"}),
    )

    assert [
        (item.symbol, item.valid_from, item.valid_to) for item in result.symbols
    ] == [
        ("AAA", date(2020, 1, 2), date(2020, 1, 5)),
        ("AAB", date(2020, 1, 6), date(2020, 1, 10)),
    ]


def test_different_isin_successor_creates_relationship() -> None:
    sessions = tuple(date(2020, 1, day) for day in range(2, 11))
    listed = _event(SecurityEventType.LISTED, date(2020, 1, 2))
    successor = _event(
        SecurityEventType.SUCCESSOR_CREATED,
        date(2020, 1, 6),
        isin="INE000B01002",
        symbol="AAB",
        old_symbol="AAA",
        old_isin="INE000A01001",
    )
    result = EventSourcedIntervalReconstructor().reconstruct(
        (listed, successor),
        sessions,
    )

    assert result.relationships[0].predecessor_identity == "nse:isin:INE000A01001"
    assert result.relationships[0].successor_identity == "nse:isin:INE000B01002"


def test_future_listing_and_future_symbol_are_not_visible_historically() -> None:
    sessions = tuple(date(2020, 1, day) for day in range(2, 11))
    events = (
        _event(SecurityEventType.LISTED, date(2020, 1, 6), symbol="AAA"),
        _event(
            SecurityEventType.SYMBOL_CHANGED,
            date(2020, 1, 8),
            symbol="AAB",
            old_symbol="AAA",
        ),
    )
    result = EventSourcedIntervalReconstructor().reconstruct(
        events,
        sessions,
        checkpoint_identities=frozenset({"nse:isin:INE000A01001"}),
    )

    assert result.membership[0].valid_from == date(2020, 1, 6)
    assert result.symbols[1].valid_from == date(2020, 1, 8)


def test_conflicting_boundaries_are_fail_visible() -> None:
    listed = _event(SecurityEventType.LISTED, date(2020, 1, 2))
    delisted = _event(SecurityEventType.DELISTED, date(2020, 1, 2))
    events, rejected = _reject_conflicting_events((listed, delisted))

    assert all(
        item.admission_state is EventAdmissionState.CONFLICTING for item in events
    )
    assert rejected[0].failure_code == "CONFLICTING_OFFICIAL_EVENTS"


def test_candle_presence_is_not_an_event_or_membership_proof() -> None:
    sessions = (date(2020, 1, 2), date(2020, 1, 3))
    result = EventSourcedIntervalReconstructor().reconstruct((), sessions)

    assert result.membership == ()
    assert result.tradability == ()
    assert PRODUCTION_INFLUENCE is False


def test_checkpoint_perfect_match_and_mismatch() -> None:
    sessions = tuple(date(2020, 1, day) for day in range(2, 11))
    listed = _event(SecurityEventType.LISTED, date(2020, 1, 2))
    checkpoint = replace(
        _event(SecurityEventType.CHECKPOINT_PRESENT, date(2020, 1, 10)),
        membership_effect=MembershipEffect.UNCHANGED,
        tradability_effect=TradabilityEffect.UNCHANGED,
    )
    engine = EventSourcedUniverseCertificationEngine.__new__(
        EventSourcedUniverseCertificationEngine
    )
    intervals = EventSourcedIntervalReconstructor().reconstruct(
        (listed, checkpoint),
        sessions,
        checkpoint_identities=frozenset({"nse:isin:INE000A01001"}),
    )
    perfect = engine._checkpoints((checkpoint,), intervals, sessions)
    mismatch = engine._checkpoints(
        (replace(checkpoint, new_symbol="WRONG"),),
        intervals,
        sessions,
    )

    assert perfect[0].issue_codes == ()
    assert mismatch[0].symbol_mismatches == 1
    assert mismatch[0].issue_codes == ("SYMBOL_MISMATCH",)


class StaticEventStore:
    def __init__(self, sources: tuple[ParsedEventSource, ...]) -> None:
        self.sources = sources

    def acquire(self, specs: object) -> tuple[ParsedEventSource, ...]:
        del specs
        return self.sources

    def verify_or_missing(self, specs: object) -> tuple[ParsedEventSource, ...]:
        del specs
        return self.sources


def _integration_fixture(
    tmp_path: Path,
) -> dict[str, Path | tuple[ParsedEventSource, ...]]:
    database = tmp_path / "historical_truth.duckdb"
    calendar = tmp_path / "calendar.json"
    baseline = tmp_path / "baseline"
    source_root = tmp_path / "source"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            CREATE TABLE daily_candle(
                trading_date DATE,
                exchange VARCHAR,
                symbol VARCHAR,
                series VARCHAR,
                isin VARCHAR,
                open_price DOUBLE,
                high_price DOUBLE,
                low_price DOUBLE,
                close_price DOUBLE,
                volume BIGINT,
                source_sha256 VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO daily_candle VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    date(2020, 1, day),
                    "nse",
                    "AAA",
                    "EQ",
                    "INE000A01001",
                    10.0,
                    11.0,
                    9.0,
                    10.5,
                    100,
                    "source-hash",
                )
                for day in (2, 3, 6)
            ],
        )
    calendar.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "trading_date": f"2020-01-{day:02d}",
                        "classification": "regular_session",
                    }
                    for day in (2, 3, 6)
                ]
            }
        ),
        encoding="utf-8",
    )
    baseline.mkdir()
    certification = {
        "certification": {"primary_state": "BLOCKED_MISSING_SECURITY_MASTER"},
        "identity_summary": {
            "governed_identities": 0,
            "provisional_identities": 1,
            "unresolved_identities": 0,
            "symbol_reuse_conflicts": 0,
            "symbol_changes_resolved": 0,
            "symbol_changes_unresolved": 0,
        },
        "membership_summary": {
            "identity_days_certified": 0,
            "unresolved_membership_days": 3,
        },
    }
    records = {
        "htr009a_certification.json": certification,
        "htr009a_security_identities.json": {
            "records": [
                {
                    "identity_key": "nse:isin:INE000A01001",
                    "symbols": ["AAA"],
                }
            ]
        },
        "htr009a_listing_delisting.json": {
            "records": [
                {
                    "official_listing_date": "2020-01-02",
                    "official_delisting_date": None,
                }
            ]
        },
        "htr009a_symbol_reuse.json": {"records": []},
        "htr009a_symbol_changes.json": {"records": []},
        "htr009a_candidate_exposure.json": {"records": []},
    }
    for filename, payload in records.items():
        (baseline / filename).write_text(json.dumps(payload), encoding="utf-8")
    listing_raw = (
        b"SYMBOL,NAME OF COMPANY,SERIES,DATE OF LISTING,ISIN NUMBER\n"
        b"AAA,Alpha Limited,EQ,02-JAN-2020,INE000A01001\n"
    )
    listing_spec = _spec(
        SecurityEventType.LISTED,
        "nse_equity_listing_csv_v1",
    )
    listing = OfficialSecurityEventStore(source_root).acquire(
        (listing_spec,),
        session=FakeSession(FakeResponse(listing_raw, "")),
    )[0]
    checkpoint_raw = b"TckrSymb,SctySrs,ISIN,Sgmt\nAAA,EQ,INE000A01001,CM\n"
    checkpoint_spec = _spec(
        SecurityEventType.CHECKPOINT_PRESENT,
        "nse_mii_checkpoint_csv_v1",
        effective_date=date(2020, 1, 6),
    )
    checkpoint = OfficialSecurityEventStore(source_root).acquire(
        (checkpoint_spec,),
        session=FakeSession(FakeResponse(checkpoint_raw, "")),
    )[0]
    return {
        "database": database,
        "calendar": calendar,
        "baseline": baseline,
        "root": tmp_path / "data",
        "sources": (listing, checkpoint),
    }


def test_engine_persists_backward_compatible_event_tables(tmp_path: Path) -> None:
    fixture = _integration_fixture(tmp_path)
    engine = EventSourcedUniverseCertificationEngine(
        fixture["database"],
        fixture["root"],
        baseline_directory=fixture["baseline"],
    )
    engine.source_store = StaticEventStore(fixture["sources"])
    report = engine.run(
        calendar_report=fixture["calendar"],
        start_date=date(2020, 1, 2),
        requested_end=None,
        refresh_sources=False,
        verify_only=False,
    )

    assert report.identity_summary.governed_identities == 1
    assert report.membership_summary.certified_identity_days == 3
    assert report.candle_conflicts == ()
    assert report.production_influence is False
    with duckdb.connect(str(fixture["database"]), read_only=True) as connection:
        tables = {item[0] for item in connection.execute("SHOW TABLES").fetchall()}
        assert "security_event" in tables
        assert "security_membership_interval" in tables
        assert connection.execute("SELECT COUNT(*) FROM security_event").fetchone()[0]


def test_verify_only_does_not_mutate_database(tmp_path: Path) -> None:
    fixture = _integration_fixture(tmp_path)
    engine = EventSourcedUniverseCertificationEngine(
        fixture["database"],
        fixture["root"],
        baseline_directory=fixture["baseline"],
    )
    engine.source_store = StaticEventStore(fixture["sources"])
    report = engine.run(
        calendar_report=fixture["calendar"],
        start_date=date(2020, 1, 2),
        requested_end=None,
        refresh_sources=False,
        verify_only=True,
    )

    assert report.report_sha256 == report.calculated_sha256()
    with duckdb.connect(str(fixture["database"]), read_only=True) as connection:
        assert "security_event" not in {
            item[0] for item in connection.execute("SHOW TABLES").fetchall()
        }


def test_artifacts_are_deterministic_and_include_baseline(tmp_path: Path) -> None:
    fixture = _integration_fixture(tmp_path)
    engine = EventSourcedUniverseCertificationEngine(
        fixture["database"],
        fixture["root"],
        baseline_directory=fixture["baseline"],
    )
    engine.source_store = StaticEventStore(fixture["sources"])
    report = engine.run(
        calendar_report=fixture["calendar"],
        start_date=date(2020, 1, 2),
        requested_end=None,
        refresh_sources=False,
        verify_only=True,
    )
    first = tmp_path / "first"
    second = tmp_path / "second"
    paths = EventSourcedUniverseArtifactExporter().export(report, first)
    EventSourcedUniverseArtifactExporter().export(report, second)

    assert (first / "baseline" / "htr009a_baseline.json").exists()
    assert (first / "htr009a2_certification.md").read_text() == (
        second / "htr009a2_certification.md"
    ).read_text()
    executive = json.loads(
        (first / "htr009a2_executive_report.json").read_text(encoding="utf-8")
    )
    assert "events" not in executive
    assert executive["event_summary"]["events_admitted"] == 2
    assert len(paths) == 34


def test_cli_rejects_mutually_exclusive_source_modes(tmp_path: Path) -> None:
    fixture = _integration_fixture(tmp_path)
    result = CliRunner().invoke(
        historical_truth_app,
        [
            "event-sourced-universe-certify",
            "--database",
            str(fixture["database"]),
            "--calendar-report",
            str(fixture["calendar"]),
            "--verify-only",
            "--refresh-sources",
        ],
    )

    assert result.exit_code != 0
    assert "cannot be combined" in result.output
