from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest
import requests
from typer.testing import CliRunner

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.cli import historical_truth_app
from alpha.historical_truth.point_in_time_identity_engine import (
    PointInTimeIdentityCertificationEngine,
)
from alpha.historical_truth.point_in_time_identity_exports import (
    PointInTimeIdentityArtifactExporter,
)
from alpha.historical_truth.point_in_time_identity_models import (
    PRODUCTION_INFLUENCE,
    CertificationState,
    EvidenceType,
    IdentityState,
    MembershipState,
    OfficialSourceSpec,
    RejectedEvidenceRecord,
    SourceStatus,
    classify_membership,
    identity_interval_issues,
    valid_isin,
)
from alpha.historical_truth.point_in_time_identity_sources import (
    DEFAULT_HEADERS,
    OfficialSecurityEvidenceStore,
    ParsedSource,
)


class FakeResponse:
    def __init__(
        self,
        content: bytes,
        url: str,
        *,
        content_type: str = "text/csv",
        status_code: int = 200,
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


@pytest.fixture
def fixture_evidence(tmp_path: Path) -> dict[str, object]:
    database = tmp_path / "historical_truth.duckdb"
    snapshots = tmp_path / "snapshots"
    root = tmp_path / "data"
    calendar = tmp_path / "calendar.json"
    days = (date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6))
    _database(database, days)
    for day in days:
        target = snapshots / "nse" / str(day.year) / f"{day}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}\n", encoding="utf-8")
    _calendar(calendar, days)
    engine = PointInTimeIdentityCertificationEngine(
        database,
        snapshots,
        root,
        baseline_exposure=tmp_path / "missing-htr008.json",
    )
    report = engine.run(
        calendar_report=calendar,
        start_date=days[0],
        requested_end=None,
        refresh_sources=False,
        verify_only=True,
    )
    return {
        "database": database,
        "snapshots": snapshots,
        "root": root,
        "calendar": calendar,
        "days": days,
        "engine": engine,
        "report": report,
    }


def test_identity_models_are_immutable(fixture_evidence: dict[str, object]) -> None:
    report = fixture_evidence["report"]
    identity = report.identities[0]
    with pytest.raises(FrozenInstanceError):
        identity.identity_key = "changed"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("INE000A01001", True),
        (None, False),
        ("", False),
        ("INVALID", False),
        ("1NE000A01001", False),
    ],
)
def test_isin_validation(value: str | None, expected: bool) -> None:
    assert valid_isin(value) is expected


def test_stable_and_missing_identity_are_distinguished(
    fixture_evidence: dict[str, object],
) -> None:
    report = fixture_evidence["report"]
    by_symbol = {item.symbols[0]: item for item in report.identities}

    assert by_symbol["AAA"].identity_state is IdentityState.PROVISIONAL_IDENTITY
    assert by_symbol["NOISIN"].identity_state is (
        IdentityState.MISSING_IDENTITY_EVIDENCE
    )
    assert ":unresolved:" in by_symbol["NOISIN"].identity_key


def test_symbol_reuse_and_symbol_change_fail_visible(
    fixture_evidence: dict[str, object],
) -> None:
    report = fixture_evidence["report"]
    reuse = next(item for item in report.symbol_reuse if item.symbol == "REUSED")
    changed = next(item for item in report.identities if item.isin == "INE000D01004")

    assert reuse.involved_isins == ("INE000B01002", "INE000C01003")
    assert reuse.final_classification is IdentityState.SYMBOL_REUSE_CONFLICT
    assert changed.symbols == ("NEWNAME", "OLDNAME")
    assert changed.identity_state is IdentityState.SYMBOL_CHANGE_UNRESOLVED


def test_same_isin_valid_official_symbol_change_is_supported(
    fixture_evidence: dict[str, object],
) -> None:
    engine = fixture_evidence["engine"]
    report = fixture_evidence["report"]
    source = next(
        item
        for item in report.sources
        if item.evidence_type is EvidenceType.DAILY_BHAVCOPY
    )
    change_source = ParsedSource(
        replace(
            source,
            source_id="official_change",
            evidence_type=EvidenceType.SYMBOL_CHANGE_HISTORY,
            status=SourceStatus.ACQUIRED,
        ),
        (
            {
                "old_symbol": "OLDNAME",
                "new_symbol": "NEWNAME",
                "effective_date": "2020-01-03",
            },
        ),
        (),
    )
    changes = engine._official_symbol_changes((change_source,))
    connection = engine._connection()
    try:
        engine._prepare(
            connection,
            fixture_evidence["days"][0],
            fixture_evidence["days"][-1],
            fixture_evidence["days"],
        )
        records = engine._identity_records(
            connection,
            reuse_keys=engine._reuse_identity_keys(connection),
            change_keys=engine._change_identity_keys(connection),
            official_changes=changes,
            governed_keys=frozenset(),
            mii_evidence=(),
        )
    finally:
        connection.close()

    changed = next(item for item in records if item.isin == "INE000D01004")
    assert changed.identity_state is IdentityState.PROVISIONAL_IDENTITY
    assert changes[0][:3] == ("OLDNAME", "NEWNAME", date(2020, 1, 3))


def test_same_symbol_different_isin_is_never_joined(
    fixture_evidence: dict[str, object],
) -> None:
    report = fixture_evidence["report"]
    reused = [item for item in report.identities if "REUSED" in item.symbols]

    assert len(reused) == 2
    assert len({item.identity_key for item in reused}) == 2


def test_interval_overlap_gap_and_series_transition() -> None:
    start = date(2020, 1, 1)
    issues = identity_interval_issues(
        (
            (start, start + timedelta(days=2), "AAA", "EQ"),
            (start + timedelta(days=2), start + timedelta(days=3), "AAA", "EQ"),
            (start + timedelta(days=6), start + timedelta(days=7), "AAA", "BE"),
        )
    )

    assert IdentityState.OVERLAPPING_IDENTITY_INTERVALS in issues
    assert IdentityState.IDENTITY_INTERVAL_GAP in issues
    assert IdentityState.SERIES_TRANSITION_UNRESOLVED in issues


@pytest.mark.parametrize(
    ("day", "kwargs", "expected"),
    [
        (
            date(2019, 12, 31),
            {"listing_date": date(2020, 1, 1), "delisting_date": None},
            MembershipState.PRE_LISTING,
        ),
        (
            date(2020, 1, 2),
            {"listing_date": date(2020, 1, 1), "delisting_date": None},
            MembershipState.ACTIVE_TRADABLE,
        ),
        (
            date(2020, 1, 3),
            {
                "listing_date": date(2020, 1, 1),
                "delisting_date": None,
                "suspension_intervals": ((date(2020, 1, 3), date(2020, 1, 4)),),
            },
            MembershipState.TEMPORARILY_SUSPENDED,
        ),
        (
            date(2020, 1, 5),
            {
                "listing_date": date(2020, 1, 1),
                "delisting_date": date(2020, 1, 4),
            },
            MembershipState.POST_DELISTING,
        ),
        (
            date(2020, 1, 8),
            {
                "listing_date": date(2020, 1, 1),
                "delisting_date": date(2020, 1, 4),
                "relisting_date": date(2020, 1, 8),
            },
            MembershipState.RELISTED,
        ),
    ],
)
def test_membership_boundaries(
    day: date,
    kwargs: dict[str, object],
    expected: MembershipState,
) -> None:
    assert (
        classify_membership(
            day,
            identity_resolved=True,
            series_supported=True,
            **kwargs,
        )
        is expected
    )


def test_missing_candle_is_not_inferred_as_suspension() -> None:
    assert (
        classify_membership(
            date(2020, 1, 3),
            identity_resolved=True,
            series_supported=True,
            listing_date=date(2020, 1, 1),
            delisting_date=None,
        )
        is MembershipState.ACTIVE_TRADABLE
    )


def test_unresolved_identity_and_unsupported_series_membership() -> None:
    common = {
        "trading_date": date(2020, 1, 2),
        "listing_date": date(2020, 1, 1),
        "delisting_date": None,
    }
    assert (
        classify_membership(
            **common,
            identity_resolved=False,
            series_supported=True,
        )
        is MembershipState.IDENTITY_UNRESOLVED
    )
    assert (
        classify_membership(
            **common,
            identity_resolved=True,
            series_supported=False,
        )
        is MembershipState.SERIES_NOT_SUPPORTED
    )


def test_no_current_or_future_universe_backfill(
    fixture_evidence: dict[str, object],
) -> None:
    report = fixture_evidence["report"]
    survivorship = {item.metric: item for item in report.survivorship}

    assert survivorship["CURRENT_UNIVERSE_LEAKAGE_DETECTED"].count == 0
    assert survivorship["FUTURE_LISTING_LEAKAGE_DETECTED"].count == 0
    assert report.time_boundaries.final_common_as_of_date is None


def test_every_candle_is_classified_without_mutation(
    fixture_evidence: dict[str, object],
) -> None:
    report = fixture_evidence["report"]
    database = fixture_evidence["database"]
    before = _candle_digest(database)

    classified = sum(item.candle_rows for item in report.candle_reconciliation)

    assert classified == 11
    assert _candle_digest(database) == before


def test_missing_master_blocks_certification(
    fixture_evidence: dict[str, object],
) -> None:
    report = fixture_evidence["report"]

    assert report.certification.primary_state is (
        CertificationState.BLOCKED_MISSING_SECURITY_MASTER
    )
    assert report.production_influence is False
    assert PRODUCTION_INFLUENCE is False


def test_fully_certified_and_conflicting_certification_states(
    fixture_evidence: dict[str, object],
) -> None:
    report = fixture_evidence["report"]
    identity = replace(
        next(item for item in report.identities if item.isin == "INE000A01001"),
        identity_state=IdentityState.GOVERNED_IDENTITY,
    )
    base_source = next(
        item
        for item in report.sources
        if item.evidence_type is EvidenceType.DAILY_BHAVCOPY
    )
    day = fixture_evidence["days"][0]
    sources = tuple(
        ParsedSource(
            replace(
                base_source,
                source_id=evidence_type.value,
                evidence_type=evidence_type,
                covered_from=day,
                covered_to=day,
                status=SourceStatus.ACQUIRED,
            ),
            (),
            (),
        )
        for evidence_type in (
            EvidenceType.MII_SECURITY_MASTER,
            EvidenceType.LISTING_NOTICE,
            EvidenceType.DELISTING_NOTICE,
            EvidenceType.SUSPENSION_NOTICE,
        )
    )
    certified = PointInTimeIdentityCertificationEngine._certification(
        (identity,),
        (),
        (),
        sources,
        (day,),
        {day},
        (),
    )
    conflict = PointInTimeIdentityCertificationEngine._certification(
        (identity,),
        (),
        (),
        sources,
        (day,),
        {day},
        (
            RejectedEvidenceRecord(
                "source",
                "https://nsearchives.nseindia.com/source.csv",
                "CONFLICTING_RECORDS",
                "fixture conflict",
            ),
        ),
    )

    assert (
        certified.primary_state is CertificationState.POINT_IN_TIME_UNIVERSE_CERTIFIED
    )
    assert conflict.primary_state is (
        CertificationState.BLOCKED_CONFLICTING_OFFICIAL_EVIDENCE
    )


def test_exports_are_complete_and_deterministic(
    fixture_evidence: dict[str, object],
    tmp_path: Path,
) -> None:
    report = fixture_evidence["report"]
    exporter = PointInTimeIdentityArtifactExporter()

    first = exporter.export(report, tmp_path / "one")
    second = exporter.export(report, tmp_path / "two")

    assert len(first) == 30
    assert [item.name for item in first] == [item.name for item in second]
    assert [item.read_bytes() for item in first] == [
        item.read_bytes() for item in second
    ]
    assert (tmp_path / "one" / "htr009a_certification.md").is_file()


def test_official_source_admission_and_immutable_reuse(tmp_path: Path) -> None:
    store = _store(tmp_path)
    spec = _spec()
    raw = b"segment,symbol,series,isin\nCM,AAA,EQ,INE000A01001\n"
    session = FakeSession(FakeResponse(raw, spec.url))

    acquired = store.acquire((spec,), session=session)[0]
    reused = store.verify_or_missing((spec,))[0]

    assert acquired.inventory.status is SourceStatus.ACQUIRED
    assert reused.inventory.status is SourceStatus.REUSED
    assert acquired.inventory.sha256 == hashlib.sha256(raw).hexdigest()
    assert acquired.rows == reused.rows
    assert session.calls[0][1]["User-Agent"] == DEFAULT_HEADERS["User-Agent"]


def test_refresh_does_not_rewrite_immutable_manifest(tmp_path: Path) -> None:
    store = _store(tmp_path)
    spec = _spec()
    raw = b"segment,symbol,series,isin\nCM,AAA,EQ,INE000A01001\n"
    session = FakeSession(FakeResponse(raw, spec.url))
    first = store.acquire((spec,), session=session)[0]
    assert first.inventory.source_path is not None
    source_path = Path(first.inventory.source_path)
    manifest_path = source_path.with_suffix(source_path.suffix + ".manifest.json")
    source_before = source_path.read_bytes()
    manifest_before = manifest_path.read_bytes()

    second = store.acquire((spec,), session=session)[0]

    assert second.inventory.status is SourceStatus.ACQUIRED
    assert source_path.read_bytes() == source_before
    assert manifest_path.read_bytes() == manifest_before


def test_gzip_source_is_parsed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    spec = _spec()
    raw = gzip.compress(b"segment,symbol,series,isin\nCM,AAA,EQ,INE000A01001\n")

    parsed = store.acquire((spec,), session=FakeSession(FakeResponse(raw, spec.url)))[0]

    assert parsed.inventory.admitted_records == 1
    assert parsed.inventory.file_format == "csv.gz"


@pytest.mark.parametrize(
    ("content", "content_type", "code"),
    [
        (b"", "text/csv", "EMPTY_RESPONSE"),
        (b"<html>denied</html>", "text/html", "HTML_MASQUERADING_AS_DATA"),
        (b"not a csv", "text/plain", "UNEXPECTED_DOCUMENT_TYPE"),
    ],
)
def test_invalid_source_document_rejected(
    tmp_path: Path,
    content: bytes,
    content_type: str,
    code: str,
) -> None:
    store = _store(tmp_path)
    spec = _spec()
    parsed = store.acquire(
        (spec,),
        session=FakeSession(FakeResponse(content, spec.url, content_type=content_type)),
    )[0]

    assert parsed.inventory.status is SourceStatus.REJECTED
    assert parsed.rejected[0].reason_code == code


def test_third_party_and_wrong_effective_date_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    third_party = OfficialSourceSpec(
        "third_party",
        EvidenceType.MII_SECURITY_MASTER,
        "https://example.com/security.csv",
        "csv",
        "CM",
        date(2020, 1, 1),
    )
    wrong_date = OfficialSourceSpec(
        "wrong_date",
        EvidenceType.MII_SECURITY_MASTER,
        "https://nsearchives.nseindia.com/content/cm/NSE_CM_security_02012020.csv.gz",
        "csv",
        "CM",
        date(2020, 1, 1),
    )

    third = store.acquire((third_party,), session=FakeSession(FakeResponse(b"", "")))[0]
    wrong = store.acquire((wrong_date,), session=FakeSession(FakeResponse(b"", "")))[0]

    assert third.rejected[0].reason_code == "THIRD_PARTY_SOURCE"
    assert wrong.rejected[0].reason_code == "WRONG_YEAR_OR_EFFECTIVE_DATE"


def test_duplicate_conflict_and_wrong_segment_are_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    spec = _spec()
    raw = (
        b"segment,symbol,series,isin\n"
        b"CM,AAA,EQ,INE000A01001\n"
        b"CM,AAA,EQ,INE000A01001\n"
        b"CM,AAA,EQ,INE000B01002\n"
        b"FO,DERIV,EQ,INE000C01003\n"
    )

    parsed = store.acquire((spec,), session=FakeSession(FakeResponse(raw, spec.url)))[0]
    codes = {item.reason_code for item in parsed.rejected}

    assert "DUPLICATE_RECORD" in codes
    assert "CONFLICTING_RECORDS" in codes
    assert "WRONG_SEGMENT" in codes
    assert parsed.rows == ()


def test_headerless_official_symbol_change_is_parsed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    spec = OfficialSourceSpec(
        "changes",
        EvidenceType.SYMBOL_CHANGE_HISTORY,
        "https://nsearchives.nseindia.com/content/equities/symbolchange.csv",
        "nse_symbol_change_csv_v1",
        "CM",
    )
    raw = b"Alpha Limited,OLDALPHA,NEWALPHA,03-JAN-2020\n"

    parsed = store.acquire(
        (spec,),
        session=FakeSession(FakeResponse(raw, spec.url)),
    )[0]
    changes = PointInTimeIdentityCertificationEngine._official_symbol_changes((parsed,))

    assert changes == (("OLDALPHA", "NEWALPHA", date(2020, 1, 3), "changes"),)


def test_checksum_mismatch_is_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    spec = _spec()
    raw = b"segment,symbol,series,isin\nCM,AAA,EQ,INE000A01001\n"
    acquired = store.acquire((spec,), session=FakeSession(FakeResponse(raw, spec.url)))[
        0
    ]
    assert acquired.inventory.source_path is not None
    Path(acquired.inventory.source_path).write_bytes(raw + b"tamper")

    verified = store.verify_or_missing((spec,))[0]

    assert verified.inventory.status is SourceStatus.REJECTED
    assert verified.rejected[0].reason_code == "CHECKSUM_MISMATCH"


def test_cli_generates_required_artifacts(
    fixture_evidence: dict[str, object],
    tmp_path: Path,
) -> None:
    output = tmp_path / "cli"
    days = fixture_evidence["days"]
    result = CliRunner().invoke(
        historical_truth_app,
        [
            "point-in-time-universe-certify",
            "--database",
            str(fixture_evidence["database"]),
            "--calendar-report",
            str(fixture_evidence["calendar"]),
            "--snapshot-root",
            str(fixture_evidence["snapshots"]),
            "--start",
            str(days[0]),
            "--end",
            "auto",
            "--root",
            str(fixture_evidence["root"]),
            "--output",
            str(output),
            "--verify-only",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "BLOCKED_MISSING_SECURITY_MASTER" in result.output
    assert "PRODUCTION_INFLUENCE=false" in result.output
    assert (output / "htr009a_executive_report.json").is_file()
    assert (output / "htr009a_certification.md").is_file()


def _store(tmp_path: Path) -> OfficialSecurityEvidenceStore:
    return OfficialSecurityEvidenceStore(
        tmp_path,
        now=lambda: datetime(2020, 1, 1, tzinfo=UTC),
    )


def _spec() -> OfficialSourceSpec:
    return OfficialSourceSpec(
        "master",
        EvidenceType.MII_SECURITY_MASTER,
        "https://nsearchives.nseindia.com/content/cm/NSE_CM_security_01012020.csv.gz",
        "csv",
        "CM",
        date(2020, 1, 1),
    )


def _calendar(path: Path, days: tuple[date, ...]) -> None:
    path.write_text(
        json.dumps(
            {
                "certification_state": "certified",
                "records": [
                    {
                        "trading_date": str(day),
                        "classification": "regular_session",
                    }
                    for day in days
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _database(path: Path, days: tuple[date, ...]) -> None:
    warehouse = CanonicalPointInTimeWarehouse(path)
    warehouse.initialise()
    rows = [
        (days[0], "nse", "AAA", "EQ", "INE000A01001"),
        (days[1], "nse", "AAA", "EQ", "INE000A01001"),
        (days[2], "nse", "AAA", "EQ", "INE000A01001"),
        (days[0], "nse", "REUSED", "EQ", "INE000B01002"),
        (days[2], "nse", "REUSED", "EQ", "INE000C01003"),
        (days[0], "nse", "OLDNAME", "EQ", "INE000D01004"),
        (days[1], "nse", "NEWNAME", "EQ", "INE000D01004"),
        (days[2], "nse", "NEWNAME", "EQ", "INE000D01004"),
        (days[0], "nse", "NOISIN", "EQ", None),
        (days[1], "nse", "NOISIN", "EQ", None),
        (days[0], "nse", "UNSUPPORTED", "BE", "INE000E01005"),
    ]
    with duckdb.connect(str(path)) as connection:
        connection.executemany(
            """
            INSERT INTO daily_candle VALUES (
                ?, ?, ?, ?, ?, 100, 105, 95, 102, 1000, ?
            )
            """,
            [item + (hashlib.sha256(str(item).encode()).hexdigest(),) for item in rows],
        )


def _candle_digest(path: Path) -> str:
    with duckdb.connect(str(path), read_only=True) as connection:
        rows = connection.execute("SELECT * FROM daily_candle ORDER BY ALL").fetchall()
    return hashlib.sha256(repr(rows).encode()).hexdigest()
