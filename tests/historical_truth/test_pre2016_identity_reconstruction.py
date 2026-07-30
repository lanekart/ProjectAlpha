from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb

from alpha.historical_truth.pre2016_identity_reconstruction import (
    DSI010B6_CONTRACT_VERSION,
    IdentityCheckpointType,
    IdentityIntervalState,
    OfficialIdentityCheckpoint,
    ReconstructedIdentityBridge,
    ReconstructedIdentityInterval,
    _full_canonical_census,
    _resolve_segments,
)
from alpha.historical_truth.pre2016_identity_sources import (
    IdentitySourceState,
    OfficialPre2016IdentityStore,
    default_identity_source_specs,
    historical_master_evidence_ceiling,
)


def _checkpoint(
    *,
    identity: str = "nse:isin:INE000A01001",
    symbol: str = "TEST",
    series: str = "EQ",
    when: date,
    source: str,
) -> OfficialIdentityCheckpoint:
    return OfficialIdentityCheckpoint(
        identity_key=identity,
        isin=identity.removeprefix("nse:isin:"),
        symbol=symbol,
        series=series,
        effective_date=when,
        checkpoint_type=IdentityCheckpointType.OFFICIAL_CORPORATE_ACTION,
        source_id=source,
        source_sha256=(source[0] * 64),
        source_url=f"https://www.nseindia.com/{source}",
    )


def _blocker(
    *,
    identity: str = "nse:isin:INE000A01001",
    symbol: str = "TEST",
    series: str = "EQ",
    affected_row_count: int = 240,
) -> dict[str, Any]:
    return {
        "identity_key": identity,
        "symbol": symbol,
        "series": series,
        "valid_from": "2005-01-03",
        "valid_to": "2005-12-30",
        "affected_row_count": affected_row_count,
        "bridge_rejection_reason": "NO_MATCHING_OFFICIAL_INTERVAL",
    }


def test_two_official_checkpoints_certify_bounded_interval() -> None:
    intervals, resolutions = _resolve_segments(
        (_blocker(),),
        (
            _checkpoint(when=date(2004, 12, 31), source="a"),
            _checkpoint(when=date(2006, 1, 2), source="b"),
        ),
    )

    assert len(intervals) == 1
    assert resolutions[0].resolved
    assert resolutions[0].exact_missing_fact is None
    assert intervals[0].negative_conflict_checks == (
        "NO_COMPETING_IDENTITY_CHECKPOINT",
        "EXACT_SYMBOL_MATCH",
        "EXACT_SERIES_MATCH",
        "CHECKPOINT_SOURCE_HASHES_PRESENT",
    )


def test_missing_lower_checkpoint_remains_fail_closed() -> None:
    intervals, resolutions = _resolve_segments(
        (_blocker(affected_row_count=1),),
        (_checkpoint(when=date(2006, 1, 2), source="b"),),
    )

    assert intervals == ()
    assert (
        resolutions[0].final_state == IdentityIntervalState.NO_LOWER_OFFICIAL_CHECKPOINT
    )
    assert "historical Masters product" in str(resolutions[0].exact_missing_fact)


def test_competing_identity_checkpoint_blocks_interval() -> None:
    intervals, resolutions = _resolve_segments(
        (_blocker(),),
        (
            _checkpoint(when=date(2004, 12, 31), source="a"),
            _checkpoint(when=date(2006, 1, 2), source="b"),
            _checkpoint(
                identity="nse:isin:INE999A01001",
                when=date(2005, 6, 1),
                source="c",
            ),
        ),
    )

    assert intervals == ()
    assert (
        resolutions[0].final_state
        == IdentityIntervalState.CONFLICTING_IDENTITY_CHECKPOINT
    )


def test_series_checkpoint_does_not_certify_another_series() -> None:
    intervals, resolutions = _resolve_segments(
        (_blocker(series="BE"),),
        (
            _checkpoint(when=date(2004, 12, 31), source="a"),
            _checkpoint(when=date(2006, 1, 2), source="b"),
        ),
    )

    assert intervals == ()
    assert (
        resolutions[0].final_state == IdentityIntervalState.NO_LOWER_OFFICIAL_CHECKPOINT
    )


@dataclass(frozen=True)
class _Decision:
    value: str


@dataclass(frozen=True)
class _Result:
    certified: bool
    decision: _Decision
    source_contract_id: str = "baseline"
    source_report_sha256: str = "0" * 64


class _Baseline:
    def resolve(self, **kwargs: Any) -> _Result:
        del kwargs
        return _Result(False, _Decision("NO_MATCHING_OFFICIAL_INTERVAL"))


def test_composite_bridge_uses_reconstructed_interval_only_inside_dates() -> None:
    lower = _checkpoint(when=date(2004, 12, 31), source="a")
    upper = _checkpoint(when=date(2006, 1, 2), source="b")
    interval = ReconstructedIdentityInterval(
        interval_id="interval-1",
        identity_key=lower.identity_key,
        isin=lower.isin,
        symbol=lower.symbol,
        series=lower.series,
        valid_from=date(2005, 1, 3),
        valid_to=date(2005, 12, 30),
        lower_checkpoint=lower,
        upper_checkpoint=upper,
        negative_conflict_checks=("NO_CONFLICT",),
        state=(IdentityIntervalState.CERTIFIED_BOUNDED_OFFICIAL_CHECKPOINT_INTERVAL),
    )
    bridge = ReconstructedIdentityBridge(_Baseline(), (interval,))  # type: ignore[arg-type]

    inside = bridge.resolve(
        identity_key=lower.identity_key,
        symbol="TEST",
        series="EQ",
        isin=lower.isin,
        reference_date=date(2005, 6, 1),
    )
    outside = bridge.resolve(
        identity_key=lower.identity_key,
        symbol="TEST",
        series="EQ",
        isin=lower.isin,
        reference_date=date(2006, 6, 1),
    )

    assert inside.certified
    assert inside.source_contract_id.startswith("DSI-010B6")
    assert not outside.certified


class _Response:
    status_code = 200
    headers = {"Content-Type": "text/html"}
    url = "https://nsearchives.nseindia.com/content/press/28062010.htm"
    history: tuple[Any, ...] = ()

    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _Session:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def get(self, *args: Any, **kwargs: Any) -> _Response:
        del args, kwargs
        return _Response(self.content)


def test_official_press_source_is_hash_bound_and_parsed(tmp_path: Path) -> None:
    html = (
        b"<table><tr><td>MANAPPURAM</td><td>Manappuram General Finance"
        b"</td><td>INE522D01027</td></tr></table>"
    )
    store = OfficialPre2016IdentityStore(
        tmp_path,
        now=lambda: datetime(2026, 7, 29, tzinfo=UTC),
    )
    source = store.acquire(
        (default_identity_source_specs()[0],),
        session=_Session(html),
    )[0]

    assert source.inventory.state == IdentitySourceState.ACQUIRED
    assert source.inventory.sha256 is not None
    assert source.observations[0].identity_key == "nse:isin:INE522D01027"
    assert source.observations[0].effective_date == date(2010, 6, 30)
    assert Path(str(source.inventory.source_path)).read_bytes() == html


def test_historical_master_ceiling_is_explicit_and_not_evidence() -> None:
    ceiling = historical_master_evidence_ceiling()

    assert ceiling.state == IdentitySourceState.SUBSCRIPTION_REQUIRED
    assert ceiling.sha256 is None
    assert "subscription" in str(ceiling.limitation).lower()


def test_full_census_never_presents_unresolved_rows_as_governed(
    tmp_path: Path,
) -> None:
    database = tmp_path / "truth.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            CREATE TABLE daily_candle(
                trading_date DATE, exchange VARCHAR, symbol VARCHAR,
                series VARCHAR, isin VARCHAR, open_price DOUBLE,
                high_price DOUBLE, low_price DOUBLE, close_price DOUBLE,
                volume BIGINT, source_sha256 VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO daily_candle VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    date(2005, 1, 3),
                    "NSE",
                    "TEST",
                    "EQ",
                    "INE000A01001",
                    10.0,
                    11.0,
                    9.0,
                    10.0,
                    100,
                    "a" * 64,
                ),
                (
                    date(2005, 1, 4),
                    "NSE",
                    "TEST",
                    "EQ",
                    None,
                    10.0,
                    11.0,
                    9.0,
                    10.0,
                    100,
                    "b" * 64,
                ),
                (
                    date(2005, 1, 5),
                    "NSE",
                    "OTHER",
                    "EQ",
                    None,
                    10.0,
                    11.0,
                    9.0,
                    10.0,
                    100,
                    "c" * 64,
                ),
            ],
        )
    resolution = _resolve_segments(
        (_blocker(affected_row_count=1),),
        (
            _checkpoint(when=date(2004, 12, 31), source="a"),
            _checkpoint(when=date(2006, 1, 2), source="b"),
        ),
    )[1]

    census = _full_canonical_census(
        database,
        {"certified_bridge_adjusted_row_count": 0},
        resolution,
        date(2005, 1, 1),
        date(2005, 12, 31),
    )

    assert census["total_canonical_row_count"] == 3
    assert census["governed_identity_row_count"] == 2
    assert census["unresolved_identity_row_count"] == 1
    assert DSI010B6_CONTRACT_VERSION == "DSI-010B6-v1.0.0"
