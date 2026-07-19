from __future__ import annotations

import json
import zipfile
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from alpha.cli import app
from alpha.market_truth.market_truth_engine import MarketTruthEngine
from alpha.market_truth.models import PriceHistoryMode
from alpha.market_truth.warehouse import (
    AcquisitionMethod,
    AcquisitionNotAuthorisedError,
    AdjustmentMode,
    AggregatePeriod,
    AuthorisationStatus,
    DividendMode,
    Exchange,
    HistoricalMarketWarehouse,
    SourceAuthorisation,
    SourceAuthorisationRegistry,
    WarehouseDataset,
    aggregate_bars,
)
from alpha.market_truth.warehouse.models import (
    IngestionResult,
    IngestionStatus,
    SessionState,
    WarehouseQualityState,
)
from alpha.market_truth.warehouse.rendering import export_csv, export_json


def test_acquisition_policy_fails_closed_and_manual_import_requires_attestation(
    tmp_path: Path,
) -> None:
    warehouse = HistoricalMarketWarehouse(tmp_path / "warehouse")

    with pytest.raises(AcquisitionNotAuthorisedError, match="LICENCE_REQUIRED"):
        warehouse.policy.permit_automated("NSE_BHAVCOPY_AUTOMATED_V1")
    with pytest.raises(AcquisitionNotAuthorisedError, match="attestation"):
        warehouse.policy.permit_manual(
            "NSE_BHAVCOPY_MANUAL_V1", lawfully_obtained=False
        )

    allowed = warehouse.policy.permit_manual(
        "NSE_BHAVCOPY_MANUAL_V1", lawfully_obtained=True
    )
    assert allowed.status is AuthorisationStatus.MANUAL_IMPORT_ONLY
    assert allowed.redistribution_permitted is False


def test_authorised_automated_acquisition_uses_same_immutable_pipeline(
    tmp_path: Path,
) -> None:
    source = _daily_file(tmp_path / "daily.csv")
    record = SourceAuthorisation(
        record_id="NSE_DAILY_AUTOMATED_TEST",
        provider="NSE",
        dataset=WarehouseDataset.BHAVCOPY,
        acquisition_method=AcquisitionMethod.AUTOMATED,
        authorisation_basis="Test fixture licence.",
        internal_storage_permitted=True,
        internal_research_permitted=True,
        redistribution_permitted=False,
        retention_permitted=True,
        effective_date=date(2020, 1, 1),
        expiry_date=None,
        evidence_reference="TEST-LICENCE",
        status=AuthorisationStatus.AUTHORISED,
    )
    registry = SourceAuthorisationRegistry((record,))
    warehouse = HistoricalMarketWarehouse(
        tmp_path / "warehouse", authorisations=registry
    )

    result = warehouse.ingestion.acquire(
        exchange=Exchange.NSE,
        dataset=WarehouseDataset.BHAVCOPY,
        session_date=date(2020, 1, 3),
        authorisation_record_id=record.record_id,
        fetcher=lambda exchange, dataset, session: source,
    )

    assert result.status is IngestionStatus.VALIDATED
    assert result.accepted_records == 3


def test_raw_vault_checksum_deduplication_and_correction_supersession(
    tmp_path: Path,
) -> None:
    warehouse = HistoricalMarketWarehouse(tmp_path / "warehouse")
    source = _daily_file(tmp_path / "daily.csv")
    first = _import_daily(warehouse, source, trading_date=date(2020, 1, 3))
    repeated = _import_daily(warehouse, source, trading_date=date(2020, 1, 3))
    corrected_path = _daily_file(tmp_path / "corrected.csv", corrected=True)
    corrected = _import_daily(warehouse, corrected_path, trading_date=date(2020, 1, 3))

    assert repeated.idempotent is True
    assert corrected.source_file.supersedes_file_id == first.source_file.source_file_id
    assert warehouse.vault.require(
        first.source_file.source_file_id
    ).ingestion_status is (IngestionStatus.SUPERSEDED)
    warehouse.vault.verify(corrected.source_file)
    assert source.read_bytes() != corrected_path.read_bytes()
    assert len(warehouse.vault.records()) == 2


def test_compressed_source_is_preserved_and_ingested_without_extraction_side_effects(
    tmp_path: Path,
) -> None:
    warehouse = HistoricalMarketWarehouse(tmp_path / "warehouse")
    csv_path = _daily_file(tmp_path / "daily.csv")
    archive = tmp_path / "daily.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("inside.csv", csv_path.read_bytes())
    original = archive.read_bytes()

    result = _import_daily(warehouse, archive)

    assert result.accepted_records == 3
    assert archive.read_bytes() == original
    assert warehouse.vault.path_for(result.source_file).read_bytes() == original


def test_bse_bhavcopy_aliases_are_canonicalised_with_explicit_session_date(
    tmp_path: Path,
) -> None:
    warehouse = HistoricalMarketWarehouse(tmp_path / "warehouse")
    source = tmp_path / "bse.csv"
    source.write_text(
        "SC_CODE,SC_NAME,OPEN,HIGH,LOW,CLOSE,NO_OF_SHRS,NO_TRADES,NET_TURNOV\n"
        "500325,RELIANCE,100,102,99,101,2000,50,202000\n"
    )

    result = warehouse.import_file(
        source,
        exchange=Exchange.BSE,
        dataset=WarehouseDataset.BHAVCOPY,
        authorisation_record_id="BSE_BHAVCOPY_MANUAL_V1",
        lawfully_obtained=True,
        trading_date=date(2020, 1, 3),
    )

    assert result.status is IngestionStatus.VALIDATED
    record = warehouse.store.daily_records(exchange=Exchange.BSE)[0]
    assert record.symbol_as_traded == "500325"
    assert record.volume == Decimal("2000")
    assert record.trade_count == 50


def test_index_and_deliverable_extension_archives_are_canonicalised(
    tmp_path: Path,
) -> None:
    warehouse = HistoricalMarketWarehouse(tmp_path / "warehouse")
    index_file = tmp_path / "index.csv"
    index_file.write_text(
        "index_id,index_name,date,open,high,low,close\n"
        "NIFTY50,NIFTY 50,2020-01-03,12000,12100,11900,12050\n"
    )
    deliverable_file = tmp_path / "deliverable.csv"
    deliverable_file.write_text(
        "symbol,series,isin,date,deliverable_quantity,deliverable_percentage\n"
        "RELIANCE,EQ,INE002A01018,2020-01-03,500,41.67\n"
    )

    index_result = warehouse.import_file(
        index_file,
        exchange=Exchange.NSE,
        dataset=WarehouseDataset.INDICES,
        authorisation_record_id="NSE_INDICES_MANUAL_V1",
        lawfully_obtained=True,
    )
    delivery_result = warehouse.import_file(
        deliverable_file,
        exchange=Exchange.NSE,
        dataset=WarehouseDataset.DELIVERABLES,
        authorisation_record_id="NSE_DELIVERABLES_MANUAL_V1",
        lawfully_obtained=True,
    )

    assert index_result.accepted_records == 1
    assert delivery_result.accepted_records == 1
    assert warehouse.store.index_records()[0].close == Decimal("12050")


def test_malformed_rows_are_quarantined_without_imputation(tmp_path: Path) -> None:
    warehouse = HistoricalMarketWarehouse(tmp_path / "warehouse")
    malformed = tmp_path / "bad.csv"
    malformed.write_text(
        _DAILY_HEADER + "BAD,EQ,INE000BAD,10,9,8,9,9,10,100,900,03-Jan-2020\n"
    )

    result = _import_daily(warehouse, malformed)

    assert result.status is IngestionStatus.QUARANTINED
    assert result.accepted_records == 0
    assert result.rejected_records == 1
    assert warehouse.status().quarantined_records == 1


def test_schema_changes_are_visible_in_component_quality(tmp_path: Path) -> None:
    warehouse = HistoricalMarketWarehouse(tmp_path / "warehouse")
    _import_daily(warehouse, _daily_file(tmp_path / "one.csv"))
    changed = tmp_path / "two.csv"
    changed.write_text(
        _DAILY_HEADER.replace("TOTTRDVAL", "TOTTRDVAL,EXTRA")
        + "RELIANCE,EQ,INE002A01018,100,101,99,100,100,99,1000,100000,x,03-Jan-2020\n"
    )
    _import_daily(warehouse, changed, trading_date=date(2020, 1, 3))

    report = warehouse.quality.audit()
    schema = next(
        item for item in report.components if item.name == "schema_consistency"
    )
    assert schema.affected_records == 1
    assert schema.state is WarehouseQualityState.PARTIAL


def test_session_inventory_separates_exchange_coverage_and_missing_dates(
    tmp_path: Path,
) -> None:
    warehouse = HistoricalMarketWarehouse(tmp_path / "warehouse")
    _import_daily(
        warehouse,
        _daily_file(tmp_path / "daily.csv"),
        trading_date=date(2020, 1, 3),
    )
    warehouse.sessions.materialise(start=date(2020, 1, 3), end=date(2020, 1, 6))

    nse = warehouse.sessions.coverage(
        exchange=Exchange.NSE, start=date(2020, 1, 3), end=date(2020, 1, 6)
    )
    bse = warehouse.sessions.coverage(
        exchange=Exchange.BSE, start=date(2020, 1, 3), end=date(2020, 1, 6)
    )
    assert nse.validated == 1
    assert nse.missing == 1
    assert bse.missing == 2
    assert len(warehouse.sessions.missing()) == 3


def test_authoritative_calendar_import_preserves_holiday_and_special_session(
    tmp_path: Path,
) -> None:
    warehouse = HistoricalMarketWarehouse(tmp_path / "warehouse")
    source = tmp_path / "calendar.csv"
    source.write_text(
        "session_date,status\n"
        "2020-01-04,HOLIDAY\n"
        "2020-01-05,SPECIAL_SESSION\n"
        "2020-01-06,TRADING\n"
    )

    result = warehouse.import_file(
        source,
        exchange=Exchange.NSE,
        dataset=WarehouseDataset.CALENDAR,
        authorisation_record_id="NSE_CALENDAR_MANUAL_V1",
        lawfully_obtained=True,
    )

    assert result.accepted_records == 3
    states = {item.session_date: item.state for item in warehouse.store.sessions()}
    assert states[date(2020, 1, 4)] is SessionState.HOLIDAY
    assert states[date(2020, 1, 5)] is SessionState.SPECIAL_SESSION
    assert states[date(2020, 1, 6)] is SessionState.EXPECTED


def test_identity_continuity_symbol_and_isin_changes_are_point_in_time(
    tmp_path: Path,
) -> None:
    warehouse = HistoricalMarketWarehouse(tmp_path / "warehouse")
    identity = _identity_file(tmp_path / "identity.csv")
    result = warehouse.import_file(
        identity,
        exchange=Exchange.NSE,
        dataset=WarehouseDataset.SECURITIES,
        authorisation_record_id="NSE_SECURITIES_MANUAL_V1",
        lawfully_obtained=True,
    )

    assert result.accepted_records == 3
    old = warehouse.identities.resolve(
        exchange=Exchange.NSE, symbol="OLDCO", as_of=date(2020, 6, 1)
    )
    new = warehouse.identities.resolve(
        exchange=Exchange.NSE, symbol="NEWCO", as_of=date(2021, 6, 1)
    )
    assert old is not None and new is not None
    assert old.security_id == new.security_id == "SEC-1"
    assert old.isin == "INEOLD"
    assert new.isin == "INENEW"
    audit = warehouse.identities.audit()
    assert audit.isin_continuity_breaks == 1


def test_universe_snapshots_respect_listing_delisting_and_suspension(
    tmp_path: Path,
) -> None:
    warehouse = HistoricalMarketWarehouse(tmp_path / "warehouse")
    warehouse.import_file(
        _identity_file(tmp_path / "identity.csv"),
        exchange=Exchange.NSE,
        dataset=WarehouseDataset.SECURITIES,
        authorisation_record_id="NSE_SECURITIES_MANUAL_V1",
        lawfully_obtained=True,
    )

    during_suspension = warehouse.universe.materialise(
        session_date=date(2021, 6, 15),
        exchange=Exchange.NSE,
        identity_version="identity-test",
    )
    after_delisting = warehouse.universe.materialise(
        session_date=date(2022, 1, 3),
        exchange=Exchange.NSE,
        identity_version="identity-test",
    )

    newco = next(item for item in during_suspension if item.symbol == "NEWCO")
    assert newco.suspended is True
    assert newco.eligible_for_research is False
    assert all(item.symbol != "NEWCO" for item in after_delisting)


def test_split_bonus_rights_and_dividend_adjustments_are_versioned(
    tmp_path: Path,
) -> None:
    warehouse = _populated_warehouse(tmp_path)

    result = warehouse.adjustments.build(
        mode=AdjustmentMode.ADJUSTED,
        adjustment_as_of=date(2020, 1, 6),
    )

    first = result.records[0]
    assert first.open < first.raw.open
    assert first.volume > first.raw.volume
    assert set(result.applied_events) >= {
        "SPLIT-1",
        "BONUS-1",
        "RIGHTS-1",
    }
    assert "MERGER-1" in result.skipped_events
    assert first.adjustment_policy_version == "ADJUSTMENT_POLICY_1.0.0"
    assert first.source_event_ids


def test_dividend_mode_is_explicit_and_raw_history_is_immutable(
    tmp_path: Path,
) -> None:
    warehouse = _populated_warehouse(tmp_path)
    raw_before = warehouse.store.daily_records()
    price_adjusted = warehouse.adjustments.build(
        mode=AdjustmentMode.ADJUSTED,
        adjustment_as_of=date(2020, 1, 6),
        dividend_mode=DividendMode.PRICE_ADJUSTED,
    )
    raw_after = warehouse.store.daily_records()

    assert raw_after == raw_before
    assert "DIV-1" in price_adjusted.applied_events
    with pytest.raises(FrozenInstanceError):
        raw_before[0].close = Decimal("1")  # type: ignore[misc]


def test_point_in_time_adjustments_exclude_future_announcements_and_bars(
    tmp_path: Path,
) -> None:
    warehouse = _populated_warehouse(tmp_path)

    before_announcement = warehouse.adjustments.build(
        mode=AdjustmentMode.POINT_IN_TIME,
        adjustment_as_of=date(2020, 1, 1),
    )
    after_announcement = warehouse.adjustments.build(
        mode=AdjustmentMode.POINT_IN_TIME,
        adjustment_as_of=date(2020, 1, 3),
    )

    assert len(before_announcement.records) == 1
    assert before_announcement.records[0].cumulative_price_factor == 1
    assert len(after_announcement.records) == 3
    assert "SPLIT-1" in after_announcement.applied_events


def test_weekly_and_monthly_aggregation_is_deterministic(tmp_path: Path) -> None:
    warehouse = _populated_warehouse(tmp_path)
    daily = warehouse.store.daily_records()

    weekly = aggregate_bars(daily, period=AggregatePeriod.WEEKLY)
    monthly = aggregate_bars(daily, period=AggregatePeriod.MONTHLY)

    assert weekly == aggregate_bars(daily, period=AggregatePeriod.WEEKLY)
    assert weekly[0].open == Decimal("100")
    assert weekly[0].close == Decimal("52")
    assert weekly[0].volume == Decimal("3300")
    assert len(monthly) == 1
    assert monthly[0].session_count == 3


def test_materialisation_versions_and_mte_warehouse_provider(tmp_path: Path) -> None:
    warehouse = _populated_warehouse(tmp_path)
    materialised = warehouse.materialise(as_of=date(2020, 1, 3))
    warehouse.publish(confirm=True, version=materialised.dataset_version)
    engine = MarketTruthEngine.default(
        warehouse_path=warehouse.paths.root,
        database_path=tmp_path / "absent.duckdb",
        cache_path=tmp_path / "cache.json",
        health_path=tmp_path / "health.json",
    )

    truth = engine.historical.daily(
        symbols=("RELIANCE",),
        start=date(2020, 1, 1),
        end=date(2020, 1, 3),
        as_of=date(2020, 1, 3),
        price_mode=PriceHistoryMode.RAW,
        warehouse_version=materialised.dataset_version.version,
        provider_hint="NSE_BSE_RAW_WAREHOUSE",
    )

    assert truth.available is True
    assert truth.provider == "NSE_BSE_RAW_WAREHOUSE"
    assert len(truth.records) == 3
    assert "warehouse:" in truth.provenance.source_reference

    identity = engine.identity.resolve(symbols=("RELIANCE",), as_of=date(2020, 1, 3))
    actions = engine.corporate_actions.events(
        symbols=("RELIANCE",),
        start=date(2020, 1, 1),
        end=date(2020, 1, 6),
        as_of=date(2020, 1, 6),
    )
    calendar = engine.calendar.sessions(
        start=date(2020, 1, 1), end=date(2020, 1, 3), as_of=date(2020, 1, 3)
    )
    universe = engine.universe.resolve(as_of=date(2020, 1, 3))
    assert identity.records
    assert actions.records
    assert calendar.records
    assert universe.records


def test_materialised_but_unpublished_warehouse_is_not_an_mte_source(
    tmp_path: Path,
) -> None:
    warehouse = _populated_warehouse(tmp_path)
    warehouse.materialise(as_of=date(2020, 1, 3))

    engine = MarketTruthEngine.default(
        warehouse_path=warehouse.paths.root,
        database_path=tmp_path / "absent.duckdb",
        cache_path=tmp_path / "cache.json",
        health_path=tmp_path / "health.json",
    )
    descriptor = engine.registry.require("NSE_BSE_RAW_WAREHOUSE").descriptor

    assert descriptor.configured is False


def test_explicit_publication_writes_versioned_partitioned_parquet(
    tmp_path: Path,
) -> None:
    warehouse = _populated_warehouse(tmp_path)
    materialised = warehouse.materialise(as_of=date(2020, 1, 3))

    with pytest.raises(RuntimeError, match="explicit confirmation"):
        warehouse.publisher.publish(materialised.dataset_version, confirm=False)
    target = warehouse.publish(confirm=True, version=materialised.dataset_version)

    assert (target / "dataset_version.json").is_file()
    assert tuple((target / "canonical" / "daily").rglob("*.parquet"))
    metadata = json.loads((target / "dataset_version.json").read_text())
    assert metadata["version"] == materialised.dataset_version.version


def test_current_store_reconciliation_does_not_replace_legacy_data(
    tmp_path: Path,
) -> None:
    warehouse = _populated_warehouse(tmp_path)
    legacy = tmp_path / "legacy.duckdb"
    database = duckdb.connect(str(legacy))
    database.execute(
        """
        CREATE TABLE daily_prices (
            symbol VARCHAR, trade_date DATE, open DOUBLE, high DOUBLE,
            low DOUBLE, close DOUBLE, volume BIGINT, exchange VARCHAR
        )
        """
    )
    database.execute(
        "INSERT INTO daily_prices VALUES "
        "('RELIANCE', '2020-01-01', 100, 101, 99, 100, 1000, 'NSE')"
    )
    database.close()

    report = warehouse.reconciler.reconcile(legacy)

    assert report.compared_rows == 1
    assert report.matching_rows == 1
    check = duckdb.connect(str(legacy), read_only=True)
    assert check.execute("SELECT COUNT(*) FROM daily_prices").fetchone() == (1,)
    check.close()


def test_json_csv_exports_and_cli_are_readable(tmp_path: Path) -> None:
    root = tmp_path / "warehouse"
    warehouse = HistoricalMarketWarehouse(root)
    result = _import_daily(warehouse, _daily_file(tmp_path / "daily.csv"))
    json_path = tmp_path / "result.json"
    csv_path = tmp_path / "result.csv"
    export_json(result, json_path)
    export_csv((result,), csv_path)

    runner = CliRunner()
    status = runner.invoke(app, ["warehouse", "status", "--root", str(root)])
    quality = runner.invoke(app, ["warehouse", "quality", "--root", str(root)])
    authorisations = runner.invoke(
        app, ["warehouse", "authorisations", "--root", str(root)]
    )

    assert status.exit_code == 0
    assert "Canonical Daily Records: 3" in status.stdout
    assert "Production Influence: false" in status.stdout
    assert quality.exit_code == 0
    assert "Warehouse Data Quality" in quality.stdout
    assert authorisations.exit_code == 0
    assert "LICENCE_REQUIRED" in authorisations.stdout
    assert json.loads(json_path.read_text())["accepted_records"] == 3
    assert "source_file.sha256" in csv_path.read_text()


def test_failed_ingestion_is_restart_visible_and_never_published(
    tmp_path: Path,
) -> None:
    warehouse = HistoricalMarketWarehouse(tmp_path / "warehouse")
    unsupported = tmp_path / "index.json"
    unsupported.write_text('{"date":"2020-01-01","index":"NIFTY 50"}\n')

    with pytest.raises(ValueError, match="unsupported warehouse source payload"):
        warehouse.import_file(
            unsupported,
            exchange=Exchange.NSE,
            dataset=WarehouseDataset.INDICES,
            authorisation_record_id="NSE_INDICES_MANUAL_V1",
            lawfully_obtained=True,
        )

    assert len(warehouse.ingestion.resume()) == 1
    assert warehouse.status().daily_records == 0
    with pytest.raises(RuntimeError, match="requires canonical daily"):
        warehouse.publish(confirm=True)


def test_production_influence_is_always_false(tmp_path: Path) -> None:
    warehouse = HistoricalMarketWarehouse(tmp_path / "warehouse")
    assert warehouse.status().production_influence is False
    assert warehouse.quality.audit().production_influence is False


def _import_daily(
    warehouse: HistoricalMarketWarehouse,
    path: Path,
    *,
    trading_date: date | None = None,
) -> IngestionResult:
    return warehouse.import_file(
        path,
        exchange=Exchange.NSE,
        dataset=WarehouseDataset.BHAVCOPY,
        authorisation_record_id="NSE_BHAVCOPY_MANUAL_V1",
        lawfully_obtained=True,
        trading_date=trading_date,
    )


def _populated_warehouse(tmp_path: Path) -> HistoricalMarketWarehouse:
    warehouse = HistoricalMarketWarehouse(tmp_path / "warehouse")
    _import_daily(warehouse, _daily_file(tmp_path / "daily.csv"))
    warehouse.import_file(
        _identity_file(tmp_path / "identity.csv", simple=True),
        exchange=Exchange.NSE,
        dataset=WarehouseDataset.SECURITIES,
        authorisation_record_id="NSE_SECURITIES_MANUAL_V1",
        lawfully_obtained=True,
    )
    warehouse.import_file(
        _actions_file(tmp_path / "actions.csv"),
        exchange=Exchange.NSE,
        dataset=WarehouseDataset.CORPORATE_ACTIONS,
        authorisation_record_id="NSE_CORPORATE_ACTIONS_MANUAL_V1",
        lawfully_obtained=True,
    )
    return warehouse


_DAILY_HEADER = (
    "SYMBOL,SERIES,ISIN,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,"
    "TOTTRDQTY,TOTTRDVAL,TIMESTAMP\n"
)


def _daily_file(path: Path, *, corrected: bool = False) -> Path:
    final_close = "53" if corrected else "52"
    path.write_text(
        _DAILY_HEADER
        + "RELIANCE,EQ,INE002A01018,100,101,99,100,100,99,1000,100000,01-Jan-2020\n"
        + "RELIANCE,EQ,INE002A01018,100,102,99,100,100,100,1100,110000,02-Jan-2020\n"
        + "RELIANCE,EQ,INE002A01018,50,53,49,"
        f"{final_close},{final_close},100,1200,62400,03-Jan-2020\n"
    )
    return path


def _identity_file(path: Path, *, simple: bool = False) -> Path:
    header = (
        "security_id,symbol,series,isin,company_name,listing_date,delisting_date,"
        "symbol_valid_from,symbol_valid_to,series_valid_from,series_valid_to,"
        "suspension_from,suspension_to\n"
    )
    if simple:
        rows = (
            "NSE:ISIN:INE002A01018,RELIANCE,EQ,INE002A01018,Reliance Industries,"
            "1995-01-01,,1995-01-01,,1995-01-01,,,\n"
        )
    else:
        rows = (
            "SEC-1,OLDCO,EQ,INEOLD,Old Company,2020-01-01,,2020-01-01,"
            "2020-12-31,2020-01-01,2020-12-31,,\n"
            "SEC-1,NEWCO,EQ,INENEW,New Company,2020-01-01,2021-12-31,"
            "2021-01-01,2021-12-31,2021-01-01,2021-12-31,2021-06-01,"
            "2021-06-30\n"
            "SEC-2,SECOND,EQ,INESECON,Second Company,2020-01-01,,2020-01-01,,"
            "2020-01-01,,,\n"
        )
    path.write_text(header + rows)
    return path


def _actions_file(path: Path) -> Path:
    path.write_text(
        "corporate_action_id,security_id,symbol,action_type,announcement_date,"
        "ex_date,ratio_numerator,ratio_denominator,cash_amount,raw_terms\n"
        "SPLIT-1,NSE:ISIN:INE002A01018,RELIANCE,STOCK_SPLIT,2020-01-02,"
        "2020-01-03,2,1,,2:1 split\n"
        "BONUS-1,NSE:ISIN:INE002A01018,RELIANCE,BONUS,2020-01-03,"
        "2020-01-04,1,1,,1:1 bonus\n"
        "RIGHTS-1,NSE:ISIN:INE002A01018,RELIANCE,RIGHTS,2020-01-03,"
        "2020-01-05,1,4,40,1:4 rights\n"
        "DIV-1,NSE:ISIN:INE002A01018,RELIANCE,DIVIDEND,2020-01-03,"
        "2020-01-06,,,2,Dividend INR 2\n"
        "MERGER-1,NSE:ISIN:INE002A01018,RELIANCE,MERGER,2020-01-03,"
        "2020-01-06,,,,Terms pending\n"
    )
    return path
