from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from alpha.cli import app
from alpha.data.repositories.database import Database
from alpha.data.repositories.prices import PricesRepository
from alpha.market_truth.cache_manager import (
    MarketTruthCacheIntegrityError,
    MarketTruthCacheManager,
)
from alpha.market_truth.consumer_repository import MarketTruthPriceRepository
from alpha.market_truth.market_truth_engine import MarketTruthEngine
from alpha.market_truth.models import (
    CorporateAction,
    CorporateActionType,
    DataQuality,
    DatasetKind,
    EvidenceClass,
    FundamentalObservation,
    IdentityAuthority,
    IndexObservation,
    MarketBar,
    MarketTick,
    MarketTruthRecord,
    MarketTruthRequest,
    ProviderClass,
    ProviderDataset,
    ProviderDescriptor,
    ProviderHealthState,
    SecurityIdentity,
    SecurityStatus,
    TradingSession,
    TradingSessionType,
)
from alpha.market_truth.provider_health import ProviderHealthMonitor
from alpha.market_truth.provider_registry import (
    DeterministicCacheProvider,
    MarketTruthProviderRegistry,
    StaticMarketTruthProvider,
    UnavailableMarketTruthProvider,
    default_provider_registry,
)
from alpha.market_truth.rendering import export_truth_csv, export_truth_json


def test_provider_registration_is_deterministic_and_conflicts_are_rejected() -> None:
    provider = _static_provider("PRIMARY", priority=10)
    registry = MarketTruthProviderRegistry((provider,))

    assert not registry.register(provider)
    with pytest.raises(ValueError, match="conflicting metadata"):
        registry.register(_static_provider("PRIMARY", priority=20))


def test_provider_failover_records_failure_and_uses_next_source(tmp_path: Path) -> None:
    unavailable = UnavailableMarketTruthProvider(
        descriptor=_descriptor("PRIMARY", priority=10),
        reason="provider unavailable",
    )
    secondary = _static_provider("SECONDARY", priority=20)
    engine = _engine(tmp_path, (unavailable, secondary))

    truth = engine.historical.daily(
        symbols=("TEST",),
        start=date(2026, 1, 1),
        end=date(2026, 1, 3),
        as_of=date(2026, 1, 3),
    )

    assert truth.provider == "SECONDARY"
    assert truth.quality.quality is DataQuality.COMPLETE
    assert [item.provider_id for item in truth.provenance.attempts] == [
        "PRIMARY",
        "SECONDARY",
    ]
    assert engine.cache.count() == 1


def test_provider_health_reflects_observed_success_and_failure(tmp_path: Path) -> None:
    unavailable = UnavailableMarketTruthProvider(
        descriptor=_descriptor("PRIMARY", priority=10), reason="offline"
    )
    engine = _engine(
        tmp_path, (unavailable, _static_provider("SECONDARY", priority=20))
    )
    engine.historical.daily(
        symbols=("TEST",),
        start=date(2026, 1, 1),
        end=date(2026, 1, 3),
        as_of=date(2026, 1, 3),
    )

    states = {item.provider_id: item.state for item in engine.health().providers}
    assert states["PRIMARY"] is ProviderHealthState.UNAVAILABLE
    assert states["SECONDARY"] is ProviderHealthState.HEALTHY


def test_daily_weekly_and_monthly_are_point_in_time_and_deterministic(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path, (_static_provider("PRIMARY", priority=10),))
    daily = engine.historical.daily(
        symbols=("TEST",),
        start=date(2026, 1, 1),
        end=date(2026, 2, 5),
        as_of=date(2026, 2, 5),
    )
    weekly = engine.historical.weekly(
        symbols=("TEST",),
        start=date(2026, 1, 1),
        end=date(2026, 2, 5),
        as_of=date(2026, 2, 5),
    )
    monthly = engine.historical.monthly(
        symbols=("TEST",),
        start=date(2026, 1, 1),
        end=date(2026, 2, 5),
        as_of=date(2026, 2, 5),
    )

    assert len(daily.records) == 4
    assert len(weekly.records) == 4
    assert len(monthly.records) == 2
    assert all(
        isinstance(item, MarketBar) and item.observed_at.date() <= date(2026, 2, 5)
        for item in monthly.records
    )
    assert monthly.provenance.request_id == monthly.request.request_id


def test_future_record_is_degraded_and_not_actionable(tmp_path: Path) -> None:
    provider = StaticMarketTruthProvider(
        descriptor=_descriptor("FUTURE", priority=10),
        responder=lambda request: _dataset(
            request,
            provider_id="FUTURE",
            records=(_bar(datetime(2026, 2, 1, tzinfo=UTC)),),
        ),
    )
    engine = _engine(tmp_path, (provider,))

    truth = engine.historical.daily(
        symbols=("TEST",),
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        as_of=date(2026, 1, 31),
    )

    assert truth.quality.quality is DataQuality.DEGRADED
    assert not truth.actionable


def test_stale_intraday_data_is_degraded_and_not_actionable(tmp_path: Path) -> None:
    provider = _static_provider(
        "LIVE",
        priority=10,
        capabilities=(DatasetKind.TICK,),
        stale_tick=True,
    )
    engine = _engine(tmp_path, (provider,))
    end = datetime(2026, 1, 2, 10, tzinfo=UTC)

    truth = engine.intraday.ticks(
        symbols=("TEST",),
        start=end - timedelta(minutes=10),
        end=end,
        as_of=end,
    )

    assert truth.quality.quality is DataQuality.DEGRADED
    assert not truth.actionable
    assert any("freshness" in item for item in truth.quality.reasons)


def test_identity_and_corporate_actions_retain_authority_and_intervals(
    tmp_path: Path,
) -> None:
    provider = _static_provider(
        "MASTER",
        priority=10,
        capabilities=(DatasetKind.IDENTITY, DatasetKind.CORPORATE_ACTIONS),
    )
    engine = _engine(tmp_path, (provider,))

    identities = engine.identity.resolve(symbols=("TEST",), as_of=date(2026, 1, 5))
    actions = engine.corporate_actions.events(
        symbols=("TEST",),
        start=date(2025, 1, 1),
        end=date(2026, 1, 5),
        as_of=date(2026, 1, 5),
    )

    identity = identities.records[0]
    action = actions.records[0]
    assert isinstance(identity, SecurityIdentity)
    assert identity.authority is IdentityAuthority.EXCHANGE
    assert isinstance(action, CorporateAction)
    assert action.action_type is CorporateActionType.SPLIT


def test_calendar_index_and_fundamentals_use_typed_truth(tmp_path: Path) -> None:
    provider = _static_provider(
        "REFERENCE",
        priority=10,
        capabilities=(
            DatasetKind.CALENDAR,
            DatasetKind.INDEX,
            DatasetKind.FUNDAMENTAL,
        ),
    )
    engine = _engine(tmp_path, (provider,))

    calendar = engine.calendar.sessions(
        start=date(2026, 1, 1), end=date(2026, 1, 5), as_of=date(2026, 1, 5)
    )
    index = engine.indices.history(
        indices=("NIFTY50",),
        start=date(2026, 1, 1),
        end=date(2026, 1, 5),
        as_of=date(2026, 1, 5),
    )
    fundamentals = engine.fundamentals.observations(
        symbols=("TEST",),
        start=date(2025, 1, 1),
        end=date(2026, 1, 5),
        as_of=date(2026, 1, 5),
    )

    assert isinstance(calendar.records[0], TradingSession)
    assert isinstance(index.records[0], IndexObservation)
    assert isinstance(fundamentals.records[0], FundamentalObservation)


def test_one_and_five_minute_services_preserve_interval(tmp_path: Path) -> None:
    provider = _static_provider(
        "LIVE",
        priority=10,
        capabilities=(DatasetKind.MINUTE_1, DatasetKind.MINUTE_5),
    )
    engine = _engine(tmp_path, (provider,))
    end = datetime(2026, 1, 2, 10, tzinfo=UTC)

    one = engine.intraday.one_minute(
        symbols=("TEST",), start=end - timedelta(minutes=1), end=end, as_of=end
    )
    five = engine.intraday.five_minute(
        symbols=("TEST",), start=end - timedelta(minutes=5), end=end, as_of=end
    )

    assert isinstance(one.records[0], MarketBar)
    assert one.records[0].interval is DatasetKind.MINUTE_1
    assert isinstance(five.records[0], MarketBar)
    assert five.records[0].interval is DatasetKind.MINUTE_5


def test_unconfigured_dataset_returns_explicit_no_data(tmp_path: Path) -> None:
    engine = MarketTruthEngine.default(
        cache_path=tmp_path / "cache.json",
        health_path=tmp_path / "health.json",
        database_path=tmp_path / "absent.duckdb",
    )

    truth = engine.identity.resolve(symbols=("TEST",), as_of=date(2026, 1, 1))

    assert truth.provider == "NO_DATA"
    assert truth.quality.quality is DataQuality.UNAVAILABLE
    assert truth.confidence.confidence_pct == 0
    assert not truth.records


def test_cache_is_immutable_and_checksum_verified(tmp_path: Path) -> None:
    cache = MarketTruthCacheManager(tmp_path / "cache.json")
    request = _request()
    dataset = _dataset(
        request,
        provider_id="PRIMARY",
        records=(_bar(datetime(2026, 1, 2, tzinfo=UTC)),),
    )

    assert cache.put(request, dataset)
    assert not cache.put(request, dataset)
    payload = json.loads(cache.path.read_text())
    payload["entries"][request.request_id]["checksum"] = "tampered"
    cache.path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MarketTruthCacheIntegrityError, match="checksum"):
        cache.get(request)


def test_versioned_cache_is_the_final_failover_without_rewriting_source(
    tmp_path: Path,
) -> None:
    cache = MarketTruthCacheManager(tmp_path / "cache.json")
    request = _request()
    cache.put(
        request,
        _dataset(
            request,
            provider_id="NSE_OFFICIAL",
            records=(_bar(datetime(2026, 1, 2, tzinfo=UTC)),),
        ),
    )
    engine = MarketTruthEngine(
        registry=MarketTruthProviderRegistry((DeterministicCacheProvider(cache),)),
        cache=cache,
        health_monitor=ProviderHealthMonitor(tmp_path / "health.json"),
    )

    truth = engine.router.route(request)

    assert truth.provider == "LOCAL_VERSIONED_CACHE"
    assert truth.evidence_class is EvidenceClass.CACHED_AUTHORITATIVE
    assert truth.provenance.source_reference.startswith("cache:")


def test_versions_and_provenance_are_content_addressed(tmp_path: Path) -> None:
    engine = _engine(tmp_path, (_static_provider("PRIMARY", priority=10),))
    first = engine.historical.daily(
        symbols=("TEST",),
        start=date(2026, 1, 1),
        end=date(2026, 1, 3),
        as_of=date(2026, 1, 3),
    )
    second = engine.historical.daily(
        symbols=("TEST",),
        start=date(2026, 1, 1),
        end=date(2026, 1, 3),
        as_of=date(2026, 1, 3),
    )

    assert first.version == second.version
    assert first.provenance.lineage_hash == second.provenance.lineage_hash
    assert first.provenance.provider_checksum is not None


def test_local_price_repository_reads_only_through_mte(tmp_path: Path) -> None:
    database_path = tmp_path / "market.duckdb"
    database = Database(str(database_path))
    PricesRepository(database).insert(
        pd.DataFrame(
            {
                "symbol": ["TEST"],
                "trade_date": [date(2026, 1, 2)],
                "open": [100],
                "high": [105],
                "low": [99],
                "close": [104],
                "volume": [1000],
                "exchange": ["NSE"],
            }
        )
    )
    database.close()
    engine = MarketTruthEngine.default(
        cache_path=tmp_path / "cache.json",
        health_path=tmp_path / "health.json",
        database_path=database_path,
    )
    repository = MarketTruthPriceRepository(engine, database_path=database_path)

    frame = repository.find_by_trade_date(date(2026, 1, 2))

    assert frame.iloc[0]["symbol"] == "TEST"
    assert frame.iloc[0]["close"] == 104.0


def test_json_and_csv_exports_preserve_truth_metadata(tmp_path: Path) -> None:
    engine = _engine(tmp_path, (_static_provider("PRIMARY", priority=10),))
    truth = engine.historical.daily(
        symbols=("TEST",),
        start=date(2026, 1, 1),
        end=date(2026, 1, 3),
        as_of=date(2026, 1, 3),
    )
    json_path = tmp_path / "truth.json"
    csv_path = tmp_path / "truth.csv"

    export_truth_json(truth, json_path)
    export_truth_csv(truth, csv_path)

    payload = json.loads(json_path.read_text())
    assert payload["provider"] == "PRIMARY"
    assert payload["production_influence"] is False
    assert "close_price" in csv_path.read_text()


def test_cli_commands_render_provider_and_truth_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _engine(tmp_path, (_static_provider("PRIMARY", priority=10),))
    monkeypatch.setattr(
        "alpha.application.market_truth_cli._engine",
        lambda **_: engine,
    )
    runner = CliRunner()

    providers = runner.invoke(app, ["market-truth", "providers"])
    daily = runner.invoke(
        app,
        [
            "market-truth",
            "daily",
            "--symbol",
            "TEST",
            "--start",
            "2026-01-01",
            "--end",
            "2026-01-03",
        ],
    )
    report = runner.invoke(app, ["market-truth", "report"])

    assert providers.exit_code == 0
    assert "Market Truth Provider Registry" in providers.stdout
    assert daily.exit_code == 0
    assert "Provider: PRIMARY" in daily.stdout
    assert "Evidence: AUTHORITATIVE" in daily.stdout
    assert "Quality: COMPLETE" in daily.stdout
    assert report.exit_code == 0
    assert "PRODUCTION_INFLUENCE=false" in report.stdout


def test_required_consumers_have_no_direct_provider_or_network_access() -> None:
    roots = (
        "forward_validation",
        "continuous_learning",
        "autonomous_loop",
        "market_dna",
        "strategy_lab",
        "historical_replay",
        "research",
    )
    banned = (
        "from alpha.data.providers",
        "from alpha.data.downloader",
        "from alpha.live.upstox",
        "urllib.request",
        "requests.",
        "Database(",
        "PricesRepository(",
    )
    for root in roots:
        for path in (Path("alpha") / root).glob("*.py"):
            source = path.read_text(encoding="utf-8")
            for marker in banned:
                assert marker not in source, f"{path} bypasses MTE via {marker}"


def test_default_registry_contains_all_initial_provider_classes(tmp_path: Path) -> None:
    registry = default_provider_registry(
        cache=MarketTruthCacheManager(tmp_path / "cache.json"),
        database_path=tmp_path / "absent.duckdb",
    )

    classes = {item.provider_class for item in registry.descriptors()}
    assert classes == set(ProviderClass)


def _engine(
    tmp_path: Path,
    providers: tuple[object, ...],
) -> MarketTruthEngine:
    typed = tuple(
        item
        for item in providers
        if isinstance(item, (StaticMarketTruthProvider, UnavailableMarketTruthProvider))
    )
    return MarketTruthEngine(
        registry=MarketTruthProviderRegistry(typed),
        cache=MarketTruthCacheManager(tmp_path / "cache.json"),
        health_monitor=ProviderHealthMonitor(tmp_path / "health.json"),
    )


def _descriptor(
    provider_id: str,
    *,
    priority: int,
    capabilities: tuple[DatasetKind, ...] = (DatasetKind.DAILY,),
) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=provider_id,
        provider_class=ProviderClass.NSE_OFFICIAL,
        display_name=provider_id,
        capabilities=capabilities,
        priority=priority,
        authoritative=True,
        configured=True,
    )


def _static_provider(
    provider_id: str,
    *,
    priority: int,
    capabilities: tuple[DatasetKind, ...] = (
        DatasetKind.DAILY,
        DatasetKind.IDENTITY,
        DatasetKind.CORPORATE_ACTIONS,
    ),
    stale_tick: bool = False,
) -> StaticMarketTruthProvider:
    descriptor = _descriptor(provider_id, priority=priority, capabilities=capabilities)

    def respond(request: MarketTruthRequest) -> ProviderDataset:
        records: tuple[MarketTruthRecord, ...]
        if request.dataset is DatasetKind.IDENTITY:
            records = (
                SecurityIdentity(
                    symbol="TEST",
                    series="EQ",
                    isin="INE000000001",
                    security_id="NSE:TEST",
                    status=SecurityStatus.ACTIVE,
                    effective_from=date(2020, 1, 1),
                    effective_to=None,
                    continuity_id="INE000000001",
                    authority=IdentityAuthority.EXCHANGE,
                ),
            )
        elif request.dataset is DatasetKind.CORPORATE_ACTIONS:
            records = (
                CorporateAction(
                    action_id="action-1",
                    security_id="NSE:TEST",
                    symbol="TEST",
                    action_type=CorporateActionType.SPLIT,
                    ex_date=date(2025, 6, 1),
                    ratio="2:1",
                ),
            )
        elif request.dataset is DatasetKind.TICK:
            assert request.as_of is not None
            observed = (
                request.as_of - timedelta(minutes=5) if stale_tick else request.as_of
            )
            records = (
                MarketTick(
                    symbol="TEST",
                    observed_at=observed,
                    last_price=Decimal("104"),
                ),
            )
        elif request.dataset in {DatasetKind.MINUTE_1, DatasetKind.MINUTE_5}:
            assert request.as_of is not None
            records = (
                MarketBar(
                    symbol="TEST",
                    observed_at=request.as_of,
                    open_price=Decimal("103"),
                    high_price=Decimal("105"),
                    low_price=Decimal("102"),
                    close_price=Decimal("104"),
                    volume=Decimal("1000"),
                    interval=request.dataset,
                    exchange="NSE",
                ),
            )
        elif request.dataset is DatasetKind.CALENDAR:
            records = (
                TradingSession(
                    session_date=date(2026, 1, 2),
                    session_type=TradingSessionType.FULL,
                    settlement_date=date(2026, 1, 5),
                    exchange="NSE",
                ),
            )
        elif request.dataset is DatasetKind.INDEX:
            records = (
                IndexObservation(
                    index_id="NIFTY50",
                    observed_at=datetime(2026, 1, 2, tzinfo=UTC),
                    value=Decimal("25000"),
                ),
            )
        elif request.dataset is DatasetKind.FUNDAMENTAL:
            records = (
                FundamentalObservation(
                    security_id="NSE:TEST",
                    symbol="TEST",
                    metric="EPS",
                    value=Decimal("12.5"),
                    period_end=date(2025, 12, 31),
                    published_at=datetime(2026, 1, 2, tzinfo=UTC),
                ),
            )
        else:
            records = (
                _bar(datetime(2026, 1, 2, tzinfo=UTC), close="101"),
                _bar(datetime(2026, 1, 8, tzinfo=UTC), close="103"),
                _bar(datetime(2026, 1, 30, tzinfo=UTC), close="105"),
                _bar(datetime(2026, 2, 3, tzinfo=UTC), close="108"),
            )
            if request.start is not None:
                records = tuple(
                    item
                    for item in records
                    if isinstance(item, MarketBar) and item.observed_at >= request.start
                )
            if request.end is not None:
                records = tuple(
                    item
                    for item in records
                    if not isinstance(item, MarketBar)
                    or item.observed_at <= request.end
                )
        return _dataset(
            request,
            provider_id=provider_id,
            records=records,
        )

    return StaticMarketTruthProvider(descriptor=descriptor, responder=respond)


def _request() -> MarketTruthRequest:
    return MarketTruthRequest(
        dataset=DatasetKind.DAILY,
        symbols=("TEST",),
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 3, tzinfo=UTC),
        as_of=datetime(2026, 1, 3, tzinfo=UTC),
    )


def _dataset(
    request: MarketTruthRequest,
    *,
    provider_id: str,
    records: tuple[MarketTruthRecord, ...],
) -> ProviderDataset:
    return ProviderDataset(
        request_id=request.request_id,
        provider_id=provider_id,
        source=f"{provider_id} source",
        evidence_class=EvidenceClass.AUTHORITATIVE,
        observed_at=request.as_of or datetime(2026, 1, 1, tzinfo=UTC),
        records=records,
        reported_completeness=Decimal("1"),
        source_reference=f"source:{provider_id}",
    )


def _bar(observed_at: datetime, *, close: str = "104") -> MarketBar:
    close_price = Decimal(close)
    return MarketBar(
        symbol="TEST",
        observed_at=observed_at,
        open_price=close_price - 1,
        high_price=close_price + 2,
        low_price=close_price - 2,
        close_price=close_price,
        volume=Decimal("1000"),
        interval=DatasetKind.DAILY,
        exchange="NSE",
        series="EQ",
    )
