from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from alpha.application.data_platform_cli import data_app
from alpha.historical_truth_acquisition.certification import CertificationEngine
from alpha.historical_truth_acquisition.checkpoints import CheckpointStore
from alpha.historical_truth_acquisition.downloader import (
    DownloadChunk,
    DownloadPartition,
    ResumableDownloadCoordinator,
)
from alpha.historical_truth_acquisition.engine import (
    HistoricalTruthAcquisitionEngine,
)
from alpha.historical_truth_acquisition.evidence import EvidenceStore
from alpha.historical_truth_acquisition.identity import build_security_master
from alpha.historical_truth_acquisition.models import (
    CertificationStatus,
    CheckpointStatus,
    EvidenceEvent,
    ReconciliationSummary,
    StageStatus,
    WarehouseCandidateStatus,
)
from alpha.historical_truth_acquisition.reconciliation import (
    HistoricalTruthReconciler,
)
from alpha.historical_truth_acquisition.stages import STAGES
from alpha.market_truth.warehouse import HistoricalMarketWarehouse
from alpha.market_truth.warehouse.models import (
    Exchange,
    IdentityRecord,
    WarehouseDataset,
)

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def test_seven_sequential_stages_cover_all_registered_datasets() -> None:
    assert tuple(stage.order for stage in STAGES) == tuple(range(1, 8))
    assert len({item for stage in STAGES for item in stage.dataset_ids}) == 20
    assert STAGES[0].dependencies == ()
    assert STAGES[-1].dependencies


def test_checkpoint_is_restart_safe_and_uses_bounded_exponential_backoff(
    tmp_path: Path,
) -> None:
    store = CheckpointStore(tmp_path / "checkpoints.json")
    planned = store.get_or_plan(
        dataset_id="nse-equity-bhavcopy",
        source_key="2020-01-03",
        observed_at=NOW,
    )
    running = store.begin(planned, observed_at=NOW)
    failed = store.fail(running, reason="temporary", observed_at=NOW)
    resumed = store.begin(failed, observed_at=NOW)
    failed_again = store.fail(resumed, reason="temporary", observed_at=NOW)
    verified = store.verified(
        resumed,
        checksum="a" * 64,
        completed_bytes=123,
        observed_at=NOW,
    )
    complete = store.complete(verified, observed_at=NOW)

    assert failed.next_retry_seconds == 2
    assert failed_again.next_retry_seconds == 4
    assert complete.status is CheckpointStatus.COMPLETE
    assert (
        store.get_or_plan(
            dataset_id="nse-equity-bhavcopy",
            source_key="2020-01-03",
            observed_at=NOW,
        )
        == complete
    )
    with pytest.raises(FrozenInstanceError):
        complete.attempts = 99  # type: ignore[misc]


def test_chunked_download_resumes_after_interruption_at_verified_offset(
    tmp_path: Path,
) -> None:
    connector = _InterruptedConnector()
    sleeps: list[float] = []
    coordinator = ResumableDownloadCoordinator(
        checkpoints=CheckpointStore(tmp_path / "checkpoints.json"),
        destination=tmp_path / "downloads",
        sleeper=sleeps.append,
        clock=lambda: NOW,
    )
    partition = DownloadPartition(
        dataset_id="nse-equity-bhavcopy",
        partition_id="2020-01-03",
        start=date(2020, 1, 3),
        end=date(2020, 1, 3),
        filename="daily.csv",
    )

    path = coordinator.acquire(partition, connector)

    assert path.read_bytes() == b"abcdef"
    assert connector.offsets == [0, 3, 3]
    assert sleeps == [2.0]
    assert coordinator.acquire(partition, connector) == path


def test_chunked_download_recovers_from_corruption_and_runs_in_parallel(
    tmp_path: Path,
) -> None:
    store = CheckpointStore(tmp_path / "checkpoints.json")
    coordinator = ResumableDownloadCoordinator(
        checkpoints=store,
        destination=tmp_path / "downloads",
        sleeper=lambda _: None,
        clock=lambda: NOW,
    )
    corrupt = DownloadPartition(
        "nse-equity-bhavcopy",
        "one",
        None,
        None,
        "one.csv",
    )
    repaired = coordinator.acquire(corrupt, _CorruptOnceConnector())
    assert repaired.read_bytes() == b"official"

    partitions = (
        DownloadPartition("nse-delivery", "a", None, None, "a.csv"),
        DownloadPartition("nse-security-master", "b", None, None, "b.csv"),
    )
    paths = coordinator.acquire_many(
        partitions,
        {
            "nse-delivery": _StaticConnector(b"delivery"),
            "nse-security-master": _StaticConnector(b"identity"),
        },
        parallelism=2,
    )
    assert tuple(path.read_bytes() for path in paths) == (b"delivery", b"identity")


def test_no_source_run_fails_closed_and_writes_typed_empty_artifacts(
    tmp_path: Path,
) -> None:
    result = HistoricalTruthAcquisitionEngine().execute(
        output_directory=tmp_path,
        acquire=True,
        observed_at=NOW,
    )

    assert result.scorecard.overall_score == Decimal("0.00")
    assert result.warehouse_candidate.status is WarehouseCandidateStatus.NOT_READY
    assert result.warehouse_candidate.activation_performed is False
    assert result.warehouse_candidate.replay_migrated is False
    assert result.warehouse_candidate.production_influence is False
    assert result.manifest.stage_results[0].status is (
        StageStatus.BLOCKED_SOURCE_UNAVAILABLE
    )
    assert all(
        item.status is StageStatus.BLOCKED_DEPENDENCY
        for item in result.manifest.stage_results[1:]
    )
    assert all(
        stage.status is CertificationStatus.FAIL for stage in result.certifications
    )
    for name in _required_artifacts():
        assert (tmp_path / name).exists()
    with duckdb.connect(":memory:") as database:
        assert database.execute(
            "SELECT COUNT(*) FROM read_parquet(?)",
            (str(tmp_path / "daily_history.parquet"),),
        ).fetchone() == (0,)


def test_manual_import_requires_explicit_lawful_source_attestation(
    tmp_path: Path,
) -> None:
    source = _identity_source(tmp_path / "sources")
    with pytest.raises(PermissionError, match="lawfully-obtained"):
        HistoricalTruthAcquisitionEngine().execute(
            output_directory=tmp_path / "output",
            source_directory=source,
            dataset="nse-security-master",
            observed_at=NOW,
        )


def test_security_master_import_is_immutable_idempotent_and_cross_exchange_safe(
    tmp_path: Path,
) -> None:
    source = _identity_source(tmp_path / "sources")
    output = tmp_path / "output"
    engine = HistoricalTruthAcquisitionEngine()
    first = engine.execute(
        output_directory=output,
        source_directory=source,
        lawfully_obtained=True,
        dataset="nse-security-master",
        observed_at=NOW,
    )
    second = engine.execute(
        output_directory=output,
        source_directory=source,
        lawfully_obtained=True,
        dataset="nse-security-master",
        resume=True,
        observed_at=NOW,
    )
    payload = json.loads((output / "security_master.json").read_text())

    nse = next(
        item
        for stage in first.certifications
        for item in stage.dataset_certifications
        if item.dataset_id == "nse-security-master"
    )
    assert nse.status is CertificationStatus.PASS
    assert payload["identity_count"] == 1
    assert payload["identities"][0]["alpha_security_id"] == ("ALPHA:ISIN:INE002A01018")
    assert second.manifest.stage_results[0].duplicate_files == 1
    raw_files = tuple(
        path
        for path in (output / "warehouse_v2_candidate" / "warehouse" / "raw").rglob("*")
        if path.is_file()
    )
    assert len(raw_files) == 1

    combined = build_security_master((_identity(Exchange.NSE), _identity(Exchange.BSE)))
    assert len(combined) == 1
    assert combined[0].exchanges == ("BSE", "NSE")


def test_historical_index_membership_uses_effective_identity_and_never_infers(
    tmp_path: Path,
) -> None:
    source = _identity_source(tmp_path / "sources")
    output = tmp_path / "output"
    engine = HistoricalTruthAcquisitionEngine()
    engine.execute(
        output_directory=output,
        source_directory=source,
        lawfully_obtained=True,
        dataset="nse-security-master",
        observed_at=NOW,
    )
    membership_dir = source / "nse-historical-index-membership"
    membership_dir.mkdir(parents=True)
    (membership_dir / "membership.csv").write_text(
        "index,effective_date,symbol,isin,change,is_member,complete_snapshot\n"
        "NIFTY 50,2020-01-03,RELIANCE,INE002A01018,ADD,true,false\n",
        encoding="utf-8",
    )
    result = engine.execute(
        output_directory=output,
        source_directory=source,
        lawfully_obtained=True,
        dataset="nse-historical-index-membership",
        since=date(2020, 1, 3),
        until=date(2020, 1, 3),
        observed_at=NOW,
    )
    with duckdb.connect(":memory:") as database:
        row = database.execute(
            """
            SELECT effective_date, alpha_security_id, complete_snapshot
            FROM read_parquet(?)
            """,
            (str(output / "index_membership.parquet"),),
        ).fetchone()
    certification = next(
        item
        for stage in result.certifications
        for item in stage.dataset_certifications
        if item.dataset_id == "nse-historical-index-membership"
    )
    assert row == (date(2020, 1, 3), "ALPHA:ISIN:INE002A01018", False)
    assert certification.status is CertificationStatus.PASS
    assert certification.evidence.unresolved_identity_records == 0


def test_unresolved_membership_identity_blocks_certification(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "evidence.json")
    store.append(
        _event(
            "nse-historical-index-membership",
            "one",
            unresolved=1,
        )
    )
    certifications = CertificationEngine(
        store, ReconciliationSummary(0, 0, ())
    ).certify(start=date(2020, 1, 3), end=date(2020, 1, 3))
    membership = next(
        item
        for stage in certifications
        for item in stage.dataset_certifications
        if item.dataset_id == "nse-historical-index-membership"
    )
    assert membership.status is CertificationStatus.FAIL
    assert membership.active is False


def test_index_history_preserves_ohlcv_checksum_and_confidence(tmp_path: Path) -> None:
    source = tmp_path / "sources"
    directory = source / "nse-index-nifty-50-ohlcv"
    directory.mkdir(parents=True)
    (directory / "nifty.csv").write_text(
        "index_id,index_name,date,open,high,low,close,volume\n"
        "NIFTY50,NIFTY 50,2020-01-03,12000,12100,11900,12050,100\n",
        encoding="utf-8",
    )
    output = tmp_path / "output"
    result = HistoricalTruthAcquisitionEngine().execute(
        output_directory=output,
        source_directory=source,
        lawfully_obtained=True,
        dataset="nse-index-nifty-50-ohlcv",
        since=date(2020, 1, 3),
        until=date(2020, 1, 3),
        observed_at=NOW,
    )
    with duckdb.connect(":memory:") as database:
        row = database.execute(
            """
            SELECT close, volume, LENGTH(source_checksum), confidence
            FROM read_parquet(?)
            """,
            (str(output / "index_history.parquet"),),
        ).fetchone()
    certification = next(
        item
        for stage in result.certifications
        for item in stage.dataset_certifications
        if item.dataset_id == "nse-index-nifty-50-ohlcv"
    )
    assert row == (Decimal("12050.00000000"), Decimal("100.0000"), 64, "HIGH")
    assert certification.status is CertificationStatus.PASS


def test_delivery_data_is_ingested_without_estimation(tmp_path: Path) -> None:
    source = tmp_path / "sources"
    directory = source / "nse-delivery"
    directory.mkdir(parents=True)
    (directory / "delivery.csv").write_text(
        "symbol,series,isin,date,deliverable_quantity,deliverable_percentage\n"
        "RELIANCE,EQ,INE002A01018,2020-01-03,500,41.67\n",
        encoding="utf-8",
    )
    output = tmp_path / "output"
    HistoricalTruthAcquisitionEngine().execute(
        output_directory=output,
        source_directory=source,
        lawfully_obtained=True,
        dataset="nse-delivery",
        since=date(2020, 1, 3),
        until=date(2020, 1, 3),
        observed_at=NOW,
    )
    with duckdb.connect(":memory:") as database:
        row = database.execute(
            """
            SELECT deliverable_quantity, deliverable_percentage
            FROM read_parquet(?)
            """,
            (str(output / "delivery_history.parquet"),),
        ).fetchone()
    assert row == (Decimal("500.0000"), Decimal("41.670000"))


def test_corporate_action_symbol_and_isin_lineage_is_exported(tmp_path: Path) -> None:
    source = _identity_source(tmp_path / "sources")
    output = tmp_path / "output"
    engine = HistoricalTruthAcquisitionEngine()
    engine.execute(
        output_directory=output,
        source_directory=source,
        lawfully_obtained=True,
        dataset="nse-security-master",
        observed_at=NOW,
    )
    directory = source / "nse-corporate-actions"
    directory.mkdir(parents=True)
    (directory / "actions.csv").write_text(
        "symbol,announcement_date,effective_date,action_type,raw_terms,"
        "old_symbol,new_symbol,old_isin,new_isin\n"
        "RELIANCE,2020-01-01,2020-01-03,SYMBOL_CHANGE,Symbol changed,"
        "RELIANCE,RELIANCENEW,INE002A01018,INE002A01018\n",
        encoding="utf-8",
    )
    engine.execute(
        output_directory=output,
        source_directory=source,
        lawfully_obtained=True,
        dataset="nse-corporate-actions",
        observed_at=NOW,
    )
    payload = json.loads((output / "security_master.json").read_text())
    lineage = payload["corporate_action_lineage"]
    assert lineage[0]["old_symbol"] == "RELIANCE"
    assert lineage[0]["new_symbol"] == "RELIANCENEW"
    assert lineage[0]["predecessor"] == lineage[0]["successor"]


def test_vault_corruption_is_detected_before_resume(tmp_path: Path) -> None:
    source = _identity_source(tmp_path / "sources")
    output = tmp_path / "output"
    engine = HistoricalTruthAcquisitionEngine()
    engine.execute(
        output_directory=output,
        source_directory=source,
        lawfully_obtained=True,
        dataset="nse-security-master",
        observed_at=NOW,
    )
    raw = next(
        path
        for path in (output / "warehouse_v2_candidate" / "warehouse" / "raw").rglob("*")
        if path.is_file()
    )
    raw.write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        engine.execute(
            output_directory=output,
            dataset="nse-security-master",
            resume=True,
            verify=True,
            observed_at=NOW,
        )


def test_certification_distinguishes_pass_warning_and_fail(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "evidence.json")
    store.append(_event("nse-equity-bhavcopy", "one"))
    store.append(_event("bse-equity-bhavcopy", "two", fingerprint="schema-b"))
    store.append(_event("bse-equity-bhavcopy", "three", fingerprint="schema-c"))
    certifications = CertificationEngine(
        store, ReconciliationSummary(0, 0, ())
    ).certify(start=date(2020, 1, 3), end=date(2020, 1, 3))
    by_id = {
        item.dataset_id: item
        for stage in certifications
        for item in stage.dataset_certifications
    }
    assert by_id["nse-equity-bhavcopy"].status is CertificationStatus.PASS
    assert by_id["bse-equity-bhavcopy"].status is CertificationStatus.PASS_WITH_WARNINGS
    assert by_id["nse-delivery"].status is CertificationStatus.FAIL


def test_reconciliation_classifies_price_and_volume_mismatches_without_overwrite(
    tmp_path: Path,
) -> None:
    warehouse = HistoricalMarketWarehouse(tmp_path / "warehouse")
    nse = tmp_path / "nse.csv"
    bse = tmp_path / "bse.csv"
    _daily_file(nse, close="101", volume="1000")
    _daily_file(bse, close="105", volume="2000")
    warehouse.import_file(
        nse,
        exchange=Exchange.NSE,
        dataset=WarehouseDataset.BHAVCOPY,
        authorisation_record_id="NSE_BHAVCOPY_MANUAL_V1",
        lawfully_obtained=True,
    )
    warehouse.import_file(
        bse,
        exchange=Exchange.BSE,
        dataset=WarehouseDataset.BHAVCOPY,
        authorisation_record_id="BSE_BHAVCOPY_MANUAL_V1",
        lawfully_obtained=True,
    )

    report = HistoricalTruthReconciler(
        warehouse, legacy_database=tmp_path / "missing.duckdb"
    ).reconcile()
    types = {item.discrepancy_type.value for item in report.findings}
    assert {"PRICE_MISMATCH", "VOLUME_MISMATCH"}.issubset(types)
    assert report.automatic_overwrites == 0


def test_all_hta_cli_commands_are_deterministic_and_non_production(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    acquire_command = [
        "acquire",
        "--output",
        str(tmp_path),
        "--resume",
        "--verify",
    ]
    first = runner.invoke(data_app, acquire_command)
    manifest_before = (tmp_path / "acquisition_manifest.json").read_bytes()
    commands = (
        ["certify", "--output", str(tmp_path)],
        ["reconcile", "--output", str(tmp_path)],
        ["scorecard", "--output", str(tmp_path)],
        ["warehouse", "--output", str(tmp_path)],
    )
    results = (first, *(runner.invoke(data_app, command) for command in commands))

    assert all(item.exit_code == 0 for item in results)
    assert "Historical Truth Acquisition" in results[0].stdout
    assert "HTA Certification Report" in results[1].stdout
    assert "Automatic Overwrites: 0" in results[2].stdout
    assert "Overall: 0.00/100" in results[3].stdout
    assert "Activation Performed: NO" in results[4].stdout
    assert "Production Influence: FALSE" in results[4].stdout
    assert (tmp_path / "acquisition_manifest.json").read_bytes() == manifest_before


def test_exports_are_reproducible_for_the_same_frozen_run(tmp_path: Path) -> None:
    engine = HistoricalTruthAcquisitionEngine()
    engine.execute(output_directory=tmp_path, observed_at=NOW)
    first = {name: (tmp_path / name).read_bytes() for name in _required_artifacts()}
    engine.execute(output_directory=tmp_path, observed_at=NOW)
    second = {name: (tmp_path / name).read_bytes() for name in _required_artifacts()}
    assert first == second


def _identity_source(root: Path) -> Path:
    directory = root / "nse-security-master"
    directory.mkdir(parents=True)
    (directory / "security_master.csv").write_text(
        "symbol,series,isin,company_name,listing_date,symbol_valid_from\n"
        "RELIANCE,EQ,INE002A01018,Reliance Industries,1977-01-01,1977-01-01\n",
        encoding="utf-8",
    )
    return root


def _identity(exchange: Exchange) -> IdentityRecord:
    return IdentityRecord(
        exchange=exchange,
        security_id=f"{exchange.value}:INE002A01018",
        symbol="RELIANCE" if exchange is Exchange.NSE else "500325",
        series="EQ",
        isin="INE002A01018",
        company_name="Reliance Industries",
        instrument_type="EQUITY",
        listing_date=date(1977, 1, 1),
        delisting_date=None,
        suspension_intervals=(),
        relisting_intervals=(),
        symbol_valid_from=date(1977, 1, 1),
        symbol_valid_to=None,
        series_valid_from=date(1977, 1, 1),
        series_valid_to=None,
        identity_authority=exchange.value,
        identity_confidence=Decimal("100"),
        source_file_id=f"source-{exchange.value}",
    )


def _event(
    dataset_id: str,
    suffix: str,
    *,
    fingerprint: str = "schema-a",
    unresolved: int = 0,
) -> EvidenceEvent:
    return EvidenceEvent(
        source_file_id=f"source-{suffix}",
        dataset_id=dataset_id,
        checksum=(suffix[0] if suffix else "a") * 64,
        schema_fingerprint=fingerprint,
        accepted_records=10,
        rejected_records=0,
        duplicate_records=0,
        coverage_start=date(2020, 1, 3),
        coverage_end=date(2020, 1, 3),
        observed_dates=(date(2020, 1, 3),),
        checksum_verified=True,
        unresolved_identity_records=unresolved,
    )


def _daily_file(path: Path, *, close: str, volume: str) -> None:
    path.write_text(
        "symbol,series,isin,trade_date,open,high,low,close,volume\n"
        f"RELIANCE,EQ,INE002A01018,2020-01-03,100,106,99,{close},{volume}\n",
        encoding="utf-8",
    )


def _required_artifacts() -> tuple[str, ...]:
    return (
        "acquisition_manifest.json",
        "security_master.json",
        "daily_history.parquet",
        "index_history.parquet",
        "index_membership.parquet",
        "corporate_actions.parquet",
        "delivery_history.parquet",
        "reconciliation_report.csv",
        "certification_report.md",
        "historical_truth_scorecard.md",
        "warehouse_v2_candidate.json",
        "executive_report.md",
    )


class _InterruptedConnector:
    def __init__(self) -> None:
        self.failed = False
        self.offsets: list[int] = []

    def read(self, partition: DownloadPartition, offset: int) -> DownloadChunk:
        del partition
        self.offsets.append(offset)
        if offset == 0:
            return DownloadChunk(b"abc", complete=False)
        if not self.failed:
            self.failed = True
            raise OSError("simulated interruption")
        return DownloadChunk(
            b"def",
            complete=True,
            expected_checksum=_sha256(b"abcdef"),
        )


class _CorruptOnceConnector:
    def __init__(self) -> None:
        self.calls = 0

    def read(self, partition: DownloadPartition, offset: int) -> DownloadChunk:
        del partition, offset
        self.calls += 1
        payload = b"bad" if self.calls == 1 else b"official"
        return DownloadChunk(
            payload,
            complete=True,
            expected_checksum=_sha256(b"official"),
        )


class _StaticConnector:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self, partition: DownloadPartition, offset: int) -> DownloadChunk:
        del partition
        payload = self.payload[offset:]
        return DownloadChunk(
            payload,
            complete=True,
            expected_checksum=_sha256(self.payload),
        )


def _sha256(payload: bytes) -> str:
    from hashlib import sha256

    return sha256(payload).hexdigest()
