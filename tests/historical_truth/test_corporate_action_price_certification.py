from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import duckdb
import pytest
from typer.testing import CliRunner

from alpha.historical_truth.cli import historical_truth_app
from alpha.historical_truth.corporate_action_price_engine import (
    AdjustmentFactorEngine,
    CorporateActionPriceCertificationEngine,
)
from alpha.historical_truth.corporate_action_price_exports import (
    CorporateActionPriceArtifactExporter,
)
from alpha.historical_truth.corporate_action_price_models import (
    PRODUCTION_INFLUENCE,
    ActionAdmissionState,
    AdjustmentDirection,
    AdjustmentFactorState,
    ContaminationState,
    CorporateActionEvent,
    CorporateActionSourceSpec,
    CorporateActionType,
    FailureCode,
    PriceBasisState,
    SourceStatus,
    stable_id,
)
from alpha.historical_truth.corporate_action_price_sources import (
    OfficialCorporateActionStore,
    ParsedCorporateActionSource,
    classify_action_type,
    parse_corporate_action_source,
    reject_conflicting_actions,
)


class FakeResponse:
    def __init__(
        self,
        content: bytes,
        *,
        status_code: int = 200,
        content_type: str = "application/json",
        url: str = "https://www.nseindia.com/api/corporates-corporateActions",
    ) -> None:
        self.content = content
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.url = url
        self.history: list[Any] = []

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs))
        return self.response


class StaticStore:
    def __init__(self, sources: tuple[ParsedCorporateActionSource, ...]) -> None:
        self.sources = sources

    def acquire(self, specs: object) -> tuple[ParsedCorporateActionSource, ...]:
        del specs
        return self.sources

    def verify_or_missing(
        self,
        specs: object,
    ) -> tuple[ParsedCorporateActionSource, ...]:
        del specs
        return tuple(
            ParsedCorporateActionSource(
                replace(item.inventory, status=SourceStatus.REUSED),
                item.actions,
                item.lineage,
                item.rejected,
            )
            for item in self.sources
        )


def _spec(year: int = 2020) -> CorporateActionSourceSpec:
    return CorporateActionSourceSpec(
        f"nse_equity_corporate_actions_{year}",
        "NSE_EQUITY_CORPORATE_ACTIONS",
        "https://www.nseindia.com/api/corporates-corporateActions?"
        f"index=equities&from_date=01-01-{year}&to_date=31-12-{year}",
        date(year, 1, 1),
        date(year, 12, 31),
    )


def _row(
    subject: str,
    *,
    ex_date: str = "15-Jun-2020",
    symbol: str = "ALPHA",
    isin: str = "INE000A01010",
    series: str = "EQ",
    face_value: str = "5",
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "series": series,
        "isin": isin,
        "subject": subject,
        "exDate": ex_date,
        "recDate": "16-Jun-2020",
        "caBroadcastDate": "01-Jun-2020",
        "faceVal": face_value,
    }


def _parse(rows: list[dict[str, object]], year: int = 2020):
    raw = json.dumps(rows, sort_keys=True).encode()
    return parse_corporate_action_source(_spec(year), raw, sha256(raw).hexdigest())


def _action(subject: str) -> CorporateActionEvent:
    parsed = _parse([_row(subject)])[1]
    assert len(parsed) == 1
    return parsed[0]


def _seed_database(path: Path) -> None:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """
            CREATE TABLE daily_candle(
                trading_date DATE, exchange VARCHAR, symbol VARCHAR, series VARCHAR,
                isin VARCHAR, open_price DOUBLE, high_price DOUBLE, low_price DOUBLE,
                close_price DOUBLE, volume BIGINT, source_sha256 VARCHAR,
                PRIMARY KEY(trading_date, exchange, symbol, series)
            )
            """
        )
        rows = []
        for day in range(1, 16):
            close = 100.0 + day
            if day == 15:
                close = 57.5
            rows.append(
                (
                    date(2020, 6, day),
                    "NSE",
                    "ALPHA",
                    "EQ",
                    "INE000A01010",
                    close - 1,
                    close + 1,
                    close - 2,
                    close,
                    1_000 + day,
                    f"sha-{day}",
                )
            )
        connection.executemany(
            "INSERT INTO daily_candle VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )


def _calendar(path: Path) -> Path:
    path.write_text(
        json.dumps({"end_date": "2020-12-31"}),
        encoding="utf-8",
    )
    return path


def _candidate_artifact(root: Path) -> None:
    path = root / "artifacts/htr009a2_event_sourced_universe"
    path.mkdir(parents=True)
    (path / "htr009a2_candidate_exposure.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "technical_candidates": 10,
                        "watchlist_candidates": 2,
                        "buy_candidates": 3,
                        "strong_buy_candidates": 1,
                        "approvals": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _parsed_source(rows: list[dict[str, object]]) -> ParsedCorporateActionSource:
    spec = _spec()
    raw = json.dumps(rows, sort_keys=True).encode()
    inspected, actions, lineage, rejected = parse_corporate_action_source(
        spec,
        raw,
        sha256(raw).hexdigest(),
    )
    from alpha.historical_truth.corporate_action_price_models import (
        CorporateActionSourceRecord,
    )

    inventory = CorporateActionSourceRecord(
        spec.source_id,
        spec.source_family,
        spec.url,
        True,
        "NSE_CA_2020",
        "2020-12-31T00:00:00+00:00",
        200,
        "application/json",
        (spec.url,),
        len(raw),
        sha256(raw).hexdigest(),
        spec.covered_start,
        spec.covered_end,
        spec.parser,
        "/immutable/source.json",
        inspected,
        len(actions),
        sum(item.admission_state is ActionAdmissionState.ADMITTED for item in actions),
        len(rejected),
        SourceStatus.ACQUIRED,
        "NEW_DOWNLOAD",
    )
    return ParsedCorporateActionSource(inventory, actions, lineage, rejected)


def test_official_source_is_admitted_and_immutable_reuse_is_verified(
    tmp_path: Path,
) -> None:
    raw = json.dumps([_row("Bonus 1:1")]).encode()
    session = FakeSession(FakeResponse(raw))
    store = OfficialCorporateActionStore(
        tmp_path,
        now=lambda: datetime(2020, 12, 31, tzinfo=UTC),
    )
    acquired = store.acquire((_spec(),), session=session)
    reused = store.verify_or_missing((_spec(),))

    assert acquired[0].inventory.status is SourceStatus.ACQUIRED
    assert acquired[0].inventory.official_host is True
    assert acquired[0].inventory.sha256 == sha256(raw).hexdigest()
    assert reused[0].inventory.status is SourceStatus.REUSED
    assert reused[0].inventory.reuse_state == "CHECKSUM_VERIFIED"
    assert session.calls[0][1]["headers"]["Accept"].startswith("application/json")


def test_third_party_source_is_rejected(tmp_path: Path) -> None:
    spec = replace(_spec(), url="https://example.com/actions.json")
    source = OfficialCorporateActionStore(tmp_path).acquire(
        (spec,),
        session=FakeSession(FakeResponse(b"[]")),
    )[0]
    assert source.inventory.status is SourceStatus.REJECTED
    assert source.inventory.failure_code is FailureCode.OFFICIAL_SOURCE_NOT_FOUND


@pytest.mark.parametrize(
    ("raw", "content_type", "code"),
    [
        (b"", "application/json", FailureCode.EMPTY_RESPONSE),
        (b"[]", "text/html", FailureCode.INVALID_CONTENT_TYPE),
        (b"{}", "application/json", FailureCode.UNSUPPORTED_FORMAT),
    ],
)
def test_invalid_source_content_is_rejected(
    tmp_path: Path,
    raw: bytes,
    content_type: str,
    code: FailureCode,
) -> None:
    source = OfficialCorporateActionStore(tmp_path).acquire(
        (_spec(),),
        session=FakeSession(FakeResponse(raw, content_type=content_type)),
    )[0]
    assert source.inventory.failure_code is code


def test_wrong_segment_and_wrong_year_are_rejected() -> None:
    inspected, actions, _, rejected = _parse(
        [
            _row("Bonus 1:1", series="GB"),
            _row("Bonus 1:1", ex_date="15-Jun-2021"),
        ]
    )
    assert inspected == 2
    assert actions == ()
    assert {item.failure_code for item in rejected} == {
        FailureCode.WRONG_MARKET_SEGMENT,
        FailureCode.WRONG_DATE_RANGE,
    }


def test_checksum_mismatch_is_fail_closed(tmp_path: Path) -> None:
    raw = json.dumps([_row("Bonus 1:1")]).encode()
    store = OfficialCorporateActionStore(tmp_path)
    acquired = store.acquire(
        (_spec(),),
        session=FakeSession(FakeResponse(raw)),
    )[0]
    assert acquired.inventory.immutable_path is not None
    Path(acquired.inventory.immutable_path).write_bytes(b"[]")
    reused = store.verify_or_missing((_spec(),))[0]
    assert reused.inventory.failure_code is FailureCode.CHECKSUM_MISMATCH


@pytest.mark.parametrize(
    ("purpose", "expected"),
    [
        ("Face Value Split (Sub-Division)", CorporateActionType.SPLIT),
        ("Bonus 1:1", CorporateActionType.BONUS),
        ("Rights 1:4 at Rs 50", CorporateActionType.RIGHTS),
        ("Special Dividend Rs 10", CorporateActionType.DIVIDEND),
        ("Consolidation of Equity Shares", CorporateActionType.FACE_VALUE_CHANGE),
        ("Capital Reduction", CorporateActionType.CAPITAL_REDUCTION),
        ("Merger", CorporateActionType.MERGER),
        ("Demerger", CorporateActionType.DEMERGER),
        ("Scheme of Arrangement", CorporateActionType.SCHEME_OF_ARRANGEMENT),
        ("Cancellation of shares", CorporateActionType.SHARE_CANCELLATION),
        ("Annual General Meeting", CorporateActionType.UNKNOWN_ACTION),
    ],
)
def test_action_type_classification(
    purpose: str,
    expected: CorporateActionType,
) -> None:
    assert classify_action_type(purpose) is expected


def test_split_bonus_and_dividend_terms_are_governed() -> None:
    split = _action("Face Value Split - From Rs 10 Per Share To Rs 5 Per Share")
    bonus = _action("Bonus 1:1")
    dividend = _action("Special Dividend Rs 10 Per Share")

    assert split.adjustment_factor == pytest.approx(0.5)
    assert bonus.adjustment_factor == pytest.approx(0.5)
    assert dividend.adjustment_factor_state is AdjustmentFactorState.NOT_REQUIRED
    assert dividend.cash_amount == pytest.approx(10.0)


def test_historical_compact_split_wording_is_parsed() -> None:
    parsed = _parse(
        [
            _row(
                "Split-Rs.10tors.2/Div-60%Purpose Revised",
                face_value="2",
            )
        ]
    )[1]
    split = parsed[0]

    assert split.old_face_value == pytest.approx(10.0)
    assert split.new_face_value == pytest.approx(2.0)
    assert split.adjustment_factor == pytest.approx(0.2)


def test_rights_terp_requires_complete_inputs() -> None:
    complete = _action("Rights 1:4 at Rs 50")
    missing_price = _action("Rights 1:4")
    engine = AdjustmentFactorEngine()

    factor = engine.derive(complete, reference_price=100.0)
    unavailable = engine.derive(missing_price, reference_price=100.0)

    assert factor.price_factor == pytest.approx(0.9)
    assert factor.quantity_factor == pytest.approx(1.25)
    assert factor.state is AdjustmentFactorState.DERIVED_FROM_OFFICIAL_TERMS
    assert unavailable.state is AdjustmentFactorState.UNKNOWN
    assert unavailable.price_factor is None


def test_invalid_and_ambiguous_ratios_do_not_create_factors() -> None:
    bonus = _action("Bonus 1:1")
    invalid = replace(bonus, adjustment_factor=-1.0)
    ambiguous = _action("Bonus issue")
    engine = AdjustmentFactorEngine()

    assert engine.derive(invalid).state is AdjustmentFactorState.INVALID
    assert engine.derive(ambiguous).price_factor is None
    assert engine.derive(ambiguous).state is AdjustmentFactorState.AMBIGUOUS


def test_cumulative_and_forward_adjustments_are_reciprocal() -> None:
    engine = AdjustmentFactorEngine()
    split = engine.derive(
        _action("Face Value Split - From Rs 10 Per Share To Rs 5 Per Share")
    )
    bonus = engine.derive(_action("Bonus 1:1"))
    forward = engine.derive(
        _action("Bonus 1:1"),
        direction=AdjustmentDirection.FORWARD,
    )

    price, quantity = engine.cumulative((split, bonus))
    assert price == pytest.approx(0.25)
    assert quantity == pytest.approx(4.0)
    assert forward.price_factor == pytest.approx(2.0)
    assert forward.quantity_factor == pytest.approx(0.5)


def test_conflicting_official_terms_are_visible_and_unadmitted() -> None:
    first = _action("Bonus 1:1")
    second = replace(
        first,
        action_id=stable_id(first.action_id, "conflict"),
        ratio_numerator=2.0,
        adjustment_factor=1 / 3,
    )
    actions, rejected = reject_conflicting_actions((first, second))

    assert all(
        item.admission_state is ActionAdmissionState.CONFLICTING for item in actions
    )
    assert rejected[0].failure_code is FailureCode.CONFLICTING_EVENT


def test_future_action_is_not_visible_to_candidate() -> None:
    action = _action("Bonus 1:1")
    earlier = CorporateActionPriceCertificationEngine.attribute_candidate(
        {
            "candidate_id": "C1",
            "identity_key": action.governed_identity_id,
            "symbol": action.symbol,
            "date": date(2020, 6, 1),
            "verdict": "BUY",
        },
        (action,),
    )
    later = CorporateActionPriceCertificationEngine.attribute_candidate(
        {
            "candidate_id": "C2",
            "identity_key": action.governed_identity_id,
            "symbol": action.symbol,
            "date": date(2020, 6, 30),
            "verdict": "BUY",
        },
        (action,),
    )

    assert earlier.action_in_lookback is False
    assert earlier.corporate_action_risk is ContaminationState.NOT_EXPOSED
    assert later.action_in_lookback is True


def test_engine_preserves_raw_candles_and_derives_adjusted_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    database = tmp_path / "warehouse.duckdb"
    _seed_database(database)
    _candidate_artifact(tmp_path)
    source = _parsed_source(
        [_row("Face Value Split - From Rs 10 Per Share To Rs 5 Per Share")]
    )
    engine = CorporateActionPriceCertificationEngine(database, tmp_path / "data")
    engine.store = StaticStore((source,))  # type: ignore[assignment]
    before = (
        duckdb.connect(str(database), read_only=True)
        .execute("SELECT COUNT(*), SUM(close_price), SUM(volume) FROM daily_candle")
        .fetchone()
    )

    report = engine.run(
        calendar_report=_calendar(tmp_path / "calendar.json"),
        start_date=date(2020, 1, 1),
        requested_end=date(2020, 12, 31),
        refresh_sources=True,
        verify_only=False,
    )
    with duckdb.connect(str(database), read_only=True) as connection:
        after = connection.execute(
            "SELECT COUNT(*), SUM(close_price), SUM(volume) FROM daily_candle"
        ).fetchone()
        adjusted = connection.execute(
            "SELECT COUNT(*), MIN(price_factor), MAX(quantity_factor) "
            "FROM adjusted_daily_candle"
        ).fetchone()

    assert before == after
    assert adjusted == (14, 0.5, 2.0)
    assert report.price_basis_summary.adjusted_candle_rows == 14
    assert report.continuity_summary.false_breakdown_risks == 1
    assert report.continuity_summary.adjusted_discontinuities == 0
    assert report.candidate_exposure_summary.linkage_available is False
    existing = next(
        item
        for item in report.sources
        if item.source_id == "existing_canonical_corporate_action_table"
    )
    assert existing.records_inspected == 0
    assert existing.consumer_usage == "NO_CONSUMER; TABLE_EMPTY"
    assert report.production_influence is False


def test_verify_only_does_not_mutate_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    database = tmp_path / "warehouse.duckdb"
    _seed_database(database)
    _candidate_artifact(tmp_path)
    engine = CorporateActionPriceCertificationEngine(database, tmp_path / "data")
    engine.store = StaticStore((_parsed_source([_row("Bonus 1:1")]),))  # type: ignore[assignment]

    engine.run(
        calendar_report=_calendar(tmp_path / "calendar.json"),
        start_date=date(2020, 1, 1),
        requested_end=date(2020, 12, 31),
        refresh_sources=False,
        verify_only=True,
    )
    with duckdb.connect(str(database), read_only=True) as connection:
        tables = {item[0] for item in connection.execute("SHOW TABLES").fetchall()}
    assert "corporate_action_event" not in tables


def test_mixed_price_basis_and_unknown_rights_factor_remain_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    database = tmp_path / "warehouse.duckdb"
    _seed_database(database)
    _candidate_artifact(tmp_path)
    source = _parsed_source(
        [
            _row("Bonus 1:1", ex_date="10-Jun-2020"),
            _row("Rights 1:4", ex_date="15-Jun-2020"),
        ]
    )
    engine = CorporateActionPriceCertificationEngine(database, tmp_path / "data")
    engine.store = StaticStore((source,))  # type: ignore[assignment]
    report = engine.run(
        calendar_report=_calendar(tmp_path / "calendar.json"),
        start_date=date(2020, 1, 1),
        requested_end=date(2020, 12, 31),
        refresh_sources=False,
        verify_only=True,
    )

    interval = next(
        item
        for item in report.price_basis_intervals
        if item.identity_key == "nse:isin:INE000A01010"
    )
    assert interval.state is PriceBasisState.MIXED_PRICE_BASIS
    assert report.factor_summary.unknown == 1


def test_demerger_does_not_join_histories_by_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    database = tmp_path / "warehouse.duckdb"
    _seed_database(database)
    _candidate_artifact(tmp_path)
    engine = CorporateActionPriceCertificationEngine(database, tmp_path / "data")
    engine.store = StaticStore((_parsed_source([_row("Demerger")]),))  # type: ignore[assignment]
    report = engine.run(
        calendar_report=_calendar(tmp_path / "calendar.json"),
        start_date=date(2020, 1, 1),
        requested_end=date(2020, 12, 31),
        refresh_sources=False,
        verify_only=True,
    )

    transition = report.identity_transitions[0]
    assert transition.successor_identity is None
    assert transition.histories_may_be_linked is False
    assert transition.new_identity_required is True
    assert transition.issue_codes == ("SUCCESSOR_IDENTITY_NOT_IN_SOURCE",)


def test_exports_are_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    database = tmp_path / "warehouse.duckdb"
    _seed_database(database)
    _candidate_artifact(tmp_path)
    engine = CorporateActionPriceCertificationEngine(database, tmp_path / "data")
    engine.store = StaticStore((_parsed_source([_row("Bonus 1:1")]),))  # type: ignore[assignment]
    report = engine.run(
        calendar_report=_calendar(tmp_path / "calendar.json"),
        start_date=date(2020, 1, 1),
        requested_end=date(2020, 12, 31),
        refresh_sources=False,
        verify_only=True,
    )
    exporter = CorporateActionPriceArtifactExporter()
    first = exporter.export(report, tmp_path / "first")
    second = exporter.export(report, tmp_path / "second")

    assert len(first) == 26
    assert [path.read_bytes() for path in first] == [
        path.read_bytes() for path in second
    ]
    assert (tmp_path / "first/htr009b_certification.json").exists()


def test_cli_registration_and_governance_constant() -> None:
    result = CliRunner().invoke(historical_truth_app, ["--help"])
    assert result.exit_code == 0
    assert "corporate-action-price-certify" in result.stdout
    assert PRODUCTION_INFLUENCE is False
