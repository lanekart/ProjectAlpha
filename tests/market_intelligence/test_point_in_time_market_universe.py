from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
)
from alpha.candidate_learning.repository import LearningLedgerRepository
from alpha.cli import app
from alpha.market_intelligence import (
    BreadthCoverageStatus,
    DiagnosticMarketStateV3Engine,
    DiagnosticV2ValidationEngine,
    HistoricalMembershipStatus,
    HistoricalSectorIngestionEngine,
    HistoricalSectorRepository,
    HistoricalSectorStatus,
    PointInTimeAnalyticalRepository,
    PointInTimeBuildStatus,
    PointInTimeMarketBreadthBuilder,
    PointInTimeMaterializationEngine,
    PointInTimeMaterializationRepository,
    PointInTimeStatus,
    PointInTimeUniverseBuilder,
    PointInTimeUniverseDataset,
    PointInTimeUniverseRepository,
    SectorHistoryReadiness,
    SectorSourceAuthority,
    UniverseQualityGrade,
    build_diagnostic_v2_report,
    build_historical_sector_readiness,
    build_historical_source_inventory,
    build_listing_delisting_audit,
    build_sector_coverage_audit,
    build_sector_incremental_value_report,
    build_sector_state_report,
    build_security_identity_audit,
    build_survivorship_bias_audit,
    build_universe_coverage_report,
    build_v1_v2_comparison,
    build_v2_outcome_comparison,
    default_sector_taxonomies,
    export_diagnostic_v2_csv,
    export_diagnostic_v2_json,
    export_historical_sector_csv,
    export_historical_sector_json,
    export_point_in_time_csv,
    export_point_in_time_json,
    point_in_time_dataset_fingerprint,
    render_breadth_snapshots,
    render_diagnostic_v2_build,
    render_diagnostic_v2_integrity,
    render_diagnostic_v2_outcomes,
    render_diagnostic_v2_readiness,
    render_diagnostic_v3_build,
    render_historical_sector_build,
    render_historical_sector_coverage,
    render_historical_sector_decision_readiness,
    render_historical_sector_state,
    render_historical_sector_validation,
    render_listing_delisting_audit,
    render_point_in_time_history_readiness,
    render_point_in_time_store_equivalence,
    render_point_in_time_store_import,
    render_point_in_time_store_profile,
    render_point_in_time_store_status,
    render_point_in_time_store_validation,
    render_sector_coverage,
    render_sector_incremental_value,
    render_sector_source_audit,
    render_sector_state,
    render_sector_taxonomies,
    render_security_identity_audit,
    render_source_inventory,
    render_survivorship_bias,
    render_universe_build,
    render_universe_coverage,
    render_universe_show,
    render_v1_v2_comparison,
    render_v2_outcome_comparison,
    render_v2_v3_comparison,
    validate_historical_sector_store,
    validate_point_in_time_materialization,
)


def test_universe_does_not_include_security_before_listing_or_after_delisting() -> None:
    dataset = _dataset()

    aaa_by_date = {row.market_date: row for row in dataset.rows if row.symbol == "AAA"}

    assert date(2026, 1, 1) not in aaa_by_date
    assert aaa_by_date[date(2026, 1, 2)].membership_status is (
        HistoricalMembershipStatus.ELIGIBLE
    )
    assert date(2026, 1, 4) not in aaa_by_date


def test_point_in_time_fingerprint_is_stable_and_version_sensitive() -> None:
    first = _dataset(dataset_version="pit-v1")
    second = _dataset(dataset_version="pit-v1")
    third = _dataset(dataset_version="pit-v2")

    assert point_in_time_dataset_fingerprint(first) == (
        point_in_time_dataset_fingerprint(second)
    )
    assert point_in_time_dataset_fingerprint(first) != (
        point_in_time_dataset_fingerprint(third)
    )


def test_point_in_time_persistence_is_dry_run_and_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "point_in_time.json"
    dry_run = PointInTimeUniverseRepository(path).save_dataset(_dataset(dry_run=True))

    assert dry_run.dry_run is True
    assert dry_run.inserted_rows > 0
    assert not path.exists()

    repository = PointInTimeUniverseRepository(path)
    dataset = _dataset(dry_run=False)
    first = repository.save_dataset(dataset)
    second = repository.save_dataset(dataset)

    assert first.inserted_rows == len(dataset.rows)
    assert second.inserted_rows == 0
    assert len(repository.load_dataset().rows) == len(dataset.rows)


def test_breadth_uses_only_point_in_time_eligible_symbols() -> None:
    dataset = _dataset()
    snapshot = PointInTimeMarketBreadthBuilder().build(
        market_date=date(2026, 1, 2),
        universe_rows=dataset.rows,
        price_repository=_PriceRepository(),
    )

    assert snapshot.eligible_universe_size == 3
    assert snapshot.advancers == 1
    assert snapshot.decliners == 1
    assert snapshot.unchanged == 1
    assert snapshot.breadth_ratio == Decimal("0.5000")
    assert snapshot.breadth_completeness is BreadthCoverageStatus.HIGH_COVERAGE


def test_current_sector_mapping_is_not_treated_as_historical_sector_truth() -> None:
    dataset = _dataset()
    classifications = dataset.sector_classifications
    coverage = build_sector_coverage_audit(dataset)

    assert all(
        row.point_in_time_status is PointInTimeStatus.CURRENT_MAPPING_DIAGNOSTIC
        for row in classifications
    )
    assert coverage.readiness is SectorHistoryReadiness.CURRENT_MAPPING_ONLY
    assert coverage.dates_with_point_in_time_sector_coverage == 0
    assert coverage.dates_with_current_mapping_only_coverage > 0


def test_coverage_reports_keep_point_in_time_limitations_explicit() -> None:
    dataset = _dataset()
    coverage = build_universe_coverage_report(dataset)
    identity = build_security_identity_audit(dataset)
    listing = build_listing_delisting_audit(dataset)
    source_inventory = build_historical_source_inventory(
        price_repository=_PriceRepository(),
        records=_records(),
    )

    assert coverage.identity_quality is UniverseQualityGrade.LOW
    assert coverage.overall_point_in_time_quality is UniverseQualityGrade.LOW
    assert identity.securities_with_isin == 0
    assert listing.inferred_listing_dates == len(dataset.security_records)
    assert any(item.source == "daily_prices" for item in source_inventory)
    assert "official listing date" in " ".join(source_inventory[0].limitations)


def test_sector_state_is_stock_aggregated_and_rendered() -> None:
    dataset = _dataset()
    report = build_sector_state_report(
        dataset=dataset,
        price_repository=_PriceRepository(),
        market_date=date(2026, 1, 2),
    )

    rendered = "\n".join(render_sector_state(report))

    assert report.leading_sector is not None
    assert "stock-aggregated sector state; not sector index" in rendered


def test_survivorship_bias_audit_reports_current_universe_difference() -> None:
    dataset = _dataset()
    report = build_survivorship_bias_audit(
        dataset=dataset,
        price_repository=_PriceRepository(),
    )

    assert len(report.rows) == 4
    assert report.dates_materially_affected >= 0
    assert "Survivorship-Bias Audit" in "\n".join(render_survivorship_bias(report))


def test_diagnostic_v2_build_is_diagnostic_and_not_persisted() -> None:
    dataset = _dataset()
    report = build_diagnostic_v2_report(
        dataset=dataset,
        classifier_version="classifier-v1",
        classifier_fingerprint="abc123",
        dry_run=False,
    )

    rendered = "\n".join(render_diagnostic_v2_build(report))

    assert report.persistence_status == "PERSISTENCE_BLOCKED_PENDING_FULL_INTEGRITY"
    assert report.blocked_reason is not None
    assert point_in_time_dataset_fingerprint(dataset) in rendered


def test_v1_v2_and_sector_value_reports_are_insufficient_until_history_exists() -> None:
    dataset = _dataset()
    coverage = build_sector_coverage_audit(dataset)
    comparison = build_v1_v2_comparison(v1_regimes=("NEUTRAL",), v2_regimes=())
    outcomes = build_v2_outcome_comparison()
    sector_value = build_sector_incremental_value_report(coverage)

    assert comparison.conclusion == "INSUFFICIENT_COVERAGE"
    assert outcomes.comparison == "INSUFFICIENT_COVERAGE"
    assert sector_value.conclusion == "INSUFFICIENT_COVERAGE"
    assert "INSUFFICIENT_COVERAGE" in "\n".join(
        render_sector_incremental_value(sector_value)
    )
    assert "Diagnostic Market-State V1/V2 Comparison" in "\n".join(
        render_v1_v2_comparison(comparison)
    )
    assert "Diagnostic Market-State V2 Outcome Comparison" in "\n".join(
        render_v2_outcome_comparison(outcomes)
    )


def test_renderers_and_exports_are_investor_readable(tmp_path: Path) -> None:
    dataset = _dataset()
    coverage = build_universe_coverage_report(dataset)
    sector = build_sector_coverage_audit(dataset)
    survivorship = build_survivorship_bias_audit(
        dataset=dataset,
        price_repository=_PriceRepository(),
    )
    breadth = PointInTimeMarketBreadthBuilder().build(
        market_date=date(2026, 1, 2),
        universe_rows=dataset.rows,
        price_repository=_PriceRepository(),
    )
    repository_result = PointInTimeUniverseRepository(
        tmp_path / "pit.json"
    ).save_dataset(dataset)

    lines = "\n".join(
        (
            *render_universe_build(repository_result),
            *render_universe_coverage(coverage),
            *render_universe_show(dataset.rows, date(2026, 1, 2)),
            *render_sector_coverage(sector),
            *render_breadth_snapshots((breadth,)),
            *render_security_identity_audit(build_security_identity_audit(dataset)),
            *render_listing_delisting_audit(build_listing_delisting_audit(dataset)),
            *render_source_inventory(
                build_historical_source_inventory(
                    price_repository=_PriceRepository(),
                    records=_records(),
                )
            ),
            *render_point_in_time_history_readiness(
                coverage,
                sector,
                survivorship,
            ),
        )
    )

    assert "Point-in-Time Universe Coverage" in lines
    assert "security-master" in lines.lower()
    assert "Explicitly Prohibited Next Action" in lines

    json_path = export_point_in_time_json(dataset, tmp_path / "pit.json")
    csv_path = export_point_in_time_csv(dataset.rows, tmp_path / "pit.csv")

    assert json_path.exists()
    assert csv_path.read_text(encoding="utf-8").startswith("market_date,")


def test_incremental_materialization_creates_manifest_and_checkpoints(
    tmp_path: Path,
) -> None:
    repository = PointInTimeMaterializationRepository(
        tmp_path / "pit-materialized.json"
    )

    result = PointInTimeMaterializationEngine().build(
        records=_records(),
        price_repository=_PriceRepository(),
        from_date=date(2026, 1, 1),
        to_date=date(2026, 1, 4),
        batch_size=2,
        persist=True,
        repository=repository,
    )

    loaded = repository.load()

    assert loaded is not None
    assert result.materialization.manifest.status is PointInTimeBuildStatus.COMPLETED
    assert len(result.materialization.manifest.checkpoints) == 2
    assert result.materialization.profile.database_queries_executed < 30
    assert result.validation.status.value == "VALID_WITH_LIMITATIONS"
    assert loaded.manifest.build_id == result.materialization.manifest.build_id


def test_incremental_materialization_is_idempotent_on_rerun(tmp_path: Path) -> None:
    repository = PointInTimeMaterializationRepository(
        tmp_path / "pit-materialized.json"
    )
    engine = PointInTimeMaterializationEngine()

    first = engine.build(
        records=_records(),
        price_repository=_PriceRepository(),
        from_date=None,
        to_date=None,
        batch_size=2,
        persist=True,
        repository=repository,
    )
    second = engine.build(
        records=_records(),
        price_repository=_PriceRepository(),
        from_date=None,
        to_date=None,
        batch_size=2,
        persist=True,
        resume=True,
        repository=repository,
    )

    assert second.materialization.manifest.rows_written == (
        first.materialization.manifest.rows_written
    )
    assert second.materialization.profile.batch_count == 0
    assert (
        validate_point_in_time_materialization(second.materialization).duplicate_rows
        == 0
    )


def test_materialized_breadth_matches_reference_builder(tmp_path: Path) -> None:
    repository = PointInTimeMaterializationRepository(
        tmp_path / "pit-materialized.json"
    )
    result = PointInTimeMaterializationEngine().build(
        records=_records(),
        price_repository=_PriceRepository(),
        from_date=None,
        to_date=None,
        batch_size=4,
        persist=False,
        repository=repository,
    )
    reference = PointInTimeMarketBreadthBuilder().build(
        market_date=date(2026, 1, 2),
        universe_rows=result.materialization.universe.rows,
        price_repository=_PriceRepository(),
    )
    optimized = next(
        item
        for item in result.materialization.breadth_snapshots
        if item.market_date == date(2026, 1, 2)
    )

    assert optimized == reference


def test_materialized_sector_state_preserves_current_mapping_label(
    tmp_path: Path,
) -> None:
    repository = PointInTimeMaterializationRepository(
        tmp_path / "pit-materialized.json"
    )
    result = PointInTimeMaterializationEngine().build(
        records=_records(),
        price_repository=_PriceRepository(),
        from_date=None,
        to_date=None,
        batch_size=4,
        persist=False,
        repository=repository,
    )
    report = next(
        item
        for item in result.materialization.sector_state_reports
        if item.market_date == date(2026, 1, 2)
    )

    assert report.sector_states
    assert all(
        item.label == "stock-aggregated sector state; not sector index"
        for item in report.sector_states
    )


def test_analytical_store_import_is_idempotent_and_equivalent(
    tmp_path: Path,
) -> None:
    materialization = (
        PointInTimeMaterializationEngine()
        .build(
            records=_records(),
            price_repository=_PriceRepository(),
            from_date=None,
            to_date=None,
            batch_size=4,
            persist=False,
        )
        .materialization
    )
    repository = PointInTimeAnalyticalRepository(tmp_path / "pit.duckdb")

    first = repository.import_materialization(
        build_id=materialization.manifest.build_id,
        materialization=materialization,
    )
    second = repository.import_materialization(
        build_id=materialization.manifest.build_id,
        materialization=materialization,
    )
    equivalence = repository.equivalence(
        build_id=materialization.manifest.build_id,
        materialization=materialization,
    )
    validation = repository.validate()
    status = repository.status()

    assert first.rows_imported == len(materialization.universe.rows)
    assert second.rows_imported == first.rows_imported
    assert first.source_json_unchanged is True
    assert equivalence.status.value == "MATCH_WITH_LIMITATIONS"
    assert validation.duplicate_universe_rows == 0
    assert status.universe_rows == len(materialization.universe.rows)
    assert status.breadth_rows == len(materialization.breadth_snapshots)
    assert "Universe Fingerprint Match: yes" in "\n".join(
        render_point_in_time_store_equivalence(equivalence)
    )
    assert "Source JSON Unchanged: yes" in "\n".join(
        render_point_in_time_store_import(first)
    )
    assert "Point-in-Time Analytical Store Status" in "\n".join(
        render_point_in_time_store_status(status)
    )
    assert "Point-in-Time Analytical Store Validation" in "\n".join(
        render_point_in_time_store_validation(validation)
    )


def test_analytical_store_reads_without_full_json_deserialization(
    tmp_path: Path,
) -> None:
    materialization = (
        PointInTimeMaterializationEngine()
        .build(
            records=_records(),
            price_repository=_PriceRepository(),
            from_date=None,
            to_date=None,
            batch_size=4,
            persist=False,
        )
        .materialization
    )
    repository = PointInTimeAnalyticalRepository(tmp_path / "pit.duckdb")
    repository.import_materialization(
        build_id=materialization.manifest.build_id,
        materialization=materialization,
    )

    rows = repository.universe_rows(market_date=date(2026, 1, 2))
    profile = repository.last_profile()

    assert rows
    assert profile.source == "analytical_store"
    assert profile.full_json_deserialization is False
    assert "Full JSON Deserialization: no" in "\n".join(
        render_point_in_time_store_profile(profile)
    )


def test_diagnostic_v2_store_links_candidate_records_not_universe_rows(
    tmp_path: Path,
) -> None:
    materialization = (
        PointInTimeMaterializationEngine()
        .build(
            records=_records(),
            price_repository=_PriceRepository(),
            from_date=None,
            to_date=None,
            batch_size=4,
            persist=False,
        )
        .materialization
    )
    repository = PointInTimeAnalyticalRepository(tmp_path / "pit.duckdb")
    repository.import_materialization(
        build_id=materialization.manifest.build_id,
        materialization=materialization,
    )
    candidate = _candidate_record(date(2026, 1, 2))

    result = repository.build_diagnostic_v2(
        records=(candidate,),
        classifier_version="classifier-v1",
        classifier_fingerprint="fingerprint",
        dry_run=False,
        persist=True,
    )

    assert result.report.reconstructions_would_create == len(
        materialization.breadth_snapshots
    )
    assert result.report.candidate_links_would_create == 1
    assert result.candidate_links_created == 1
    assert result.universe_rows_treated_as_candidate_links == 0
    assert result.report.candidate_links_would_create < len(
        materialization.universe.rows
    )


def test_diagnostic_v2_validation_freezes_identity_and_link_integrity(
    tmp_path: Path,
) -> None:
    store_path, ledger_path = _diagnostic_v2_store_and_ledger(tmp_path)
    ledger = LearningLedgerRepository(ledger_path)
    engine = DiagnosticV2ValidationEngine(store_path=store_path)
    report = engine.build(
        v1_reconstructions=(),
        records=ledger.load_records(),
        outcomes=ledger.load_outcomes(),
    )
    repeated = engine.build(
        v1_reconstructions=(),
        records=ledger.load_records(),
        outcomes=ledger.load_outcomes(),
    )

    assert report.identity.dataset_fingerprint == repeated.identity.dataset_fingerprint
    assert report.integrity.reconstruction_count == 4
    assert report.integrity.candidate_link_count == 1
    assert report.integrity.duplicate_candidate_links == 0
    assert report.integrity.orphan_links == 0
    assert report.integrity.universe_only_links == 0
    assert report.integrity.future_source_violations == 0
    assert report.integrity.passed is True
    assert "Passed: yes" in "\n".join(render_diagnostic_v2_integrity(report))


def test_diagnostic_v2_validation_joins_outcomes_and_reports_readiness(
    tmp_path: Path,
) -> None:
    report = _diagnostic_v2_validation_report(tmp_path)
    rendered_outcomes = "\n".join(render_diagnostic_v2_outcomes(report))
    rendered_readiness = "\n".join(render_diagnostic_v2_readiness(report))

    assert report.outcome_join.linked_candidates == 1
    assert report.outcome_join.completed_outcomes == 1
    assert report.outcome_join.outcome_unavailable == 0
    assert "Completed Outcomes: 1" in rendered_outcomes
    assert "Explicitly Prohibited Next Action" in rendered_readiness
    assert "Do not tune market-regime thresholds" in rendered_readiness


def test_diagnostic_v2_validation_exports_json_and_csv(tmp_path: Path) -> None:
    report = _diagnostic_v2_validation_report(tmp_path)

    json_path = export_diagnostic_v2_json(report, tmp_path / "v2.json")
    csv_path = export_diagnostic_v2_csv(report.alignment_rows, tmp_path / "v2.csv")

    assert "dataset_fingerprint" in json_path.read_text(encoding="utf-8")
    assert csv_path.read_text(encoding="utf-8").startswith("market_date,")


def test_diagnostic_v2_cli_reads_indexed_store_and_candidate_ledger(
    tmp_path: Path,
) -> None:
    store_path, ledger_path = _diagnostic_v2_store_and_ledger(tmp_path)

    result = CliRunner().invoke(
        app,
        ["replay", "diagnostic-market-state-v2-integrity"],
        env={
            "_TYPER_FORCE_DISABLE_TERMINAL": "1",
            "TERMINAL_WIDTH": "200",
            "ALPHA_POINT_IN_TIME_ANALYTICAL_STORE": str(store_path),
            "ALPHA_CANDIDATE_LEARNING_LEDGER": str(ledger_path),
            "ALPHA_DIAGNOSTIC_MARKET_STATE_LEDGER": str(tmp_path / "v1.json"),
        },
    )

    assert result.exit_code == 0
    assert "Diagnostic V2 Integrity" in result.output
    assert "Candidate Links: 1" in result.output
    assert "Universe-only Links: 0" in result.output


def test_historical_sector_source_audit_and_taxonomy_are_explicit(
    tmp_path: Path,
) -> None:
    store_path, _ledger_path = _diagnostic_v2_store_and_ledger(tmp_path)
    engine = HistoricalSectorIngestionEngine(store_path=store_path)

    sources = engine.source_inventory()
    taxonomies = default_sector_taxonomies()
    rendered_sources = "\n".join(render_sector_source_audit(sources))
    rendered_taxonomies = "\n".join(render_sector_taxonomies(taxonomies))

    daily_prices = next(
        row for row in sources if row.source_id == "daily_prices.sector"
    )
    bhavcopy = next(row for row in sources if row.source_id == "nse_bhavcopy_archives")

    assert daily_prices.authority is SectorSourceAuthority.CURRENT_STATE_ONLY
    assert daily_prices.effective_date_support is False
    assert bhavcopy.authority is SectorSourceAuthority.UNUSABLE
    assert "index membership must not be substituted" in " ".join(
        bhavcopy.known_limitations
    )
    assert any(row.taxonomy_id == "alpha-current-sector-v1" for row in taxonomies)
    assert "Historical Sector Source Audit" in rendered_sources
    assert "Sector Taxonomy Registry" in rendered_taxonomies


def test_historical_sector_build_dry_run_then_persist_without_backfill(
    tmp_path: Path,
) -> None:
    store_path, _ledger_path = _diagnostic_v2_store_and_ledger(tmp_path)
    engine = HistoricalSectorIngestionEngine(store_path=store_path)
    repository = HistoricalSectorRepository(store_path)

    dry_run = engine.build(persist=False)
    assert dry_run.dry_run is True
    assert dry_run.persisted is False
    assert repository.latest_manifest() is None

    persisted = engine.build(persist=True)
    manifest = repository.latest_manifest()
    classifications = repository.load_classifications()
    validation = validate_historical_sector_store(store_path)
    rendered_build = "\n".join(render_historical_sector_build(persisted))
    rendered_validation = "\n".join(render_historical_sector_validation(validation))

    assert manifest is not None
    assert manifest.build_id == persisted.manifest.build_id
    assert persisted.manifest.current_only_rows == len(persisted.classifications)
    assert persisted.manifest.effective_dated_rows == 0
    assert all(
        row.point_in_time_status is HistoricalSectorStatus.CURRENT_MAPPING_ONLY
        for row in classifications
    )
    assert (
        repository.get_classification_as_of(
            security_id=classifications[0].security_id,
            market_date=date(2026, 1, 2),
        )
        is None
    )
    assert validation.effective_dated_classifications == 0
    assert validation.current_only_classifications == len(classifications)
    assert "Effective-Dated Rows: 0" in rendered_build
    assert "Current-Only Classifications:" in rendered_validation


def test_historical_sector_coverage_state_exports_and_readiness(
    tmp_path: Path,
) -> None:
    store_path, _ledger_path = _diagnostic_v2_store_and_ledger(tmp_path)
    HistoricalSectorIngestionEngine(store_path=store_path).build(persist=True)
    repository = HistoricalSectorRepository(store_path)

    coverage = repository.get_sector_coverage()
    sector_state = repository.get_sector_state(market_date=date(2026, 1, 2))
    readiness = build_historical_sector_readiness(store_path=store_path)
    coverage_text = "\n".join(render_historical_sector_coverage(coverage))
    state_text = "\n".join(
        render_historical_sector_state(
            sector_state,
            market_date=date(2026, 1, 2),
        )
    )
    readiness_text = "\n".join(render_historical_sector_decision_readiness(readiness))
    json_path = export_historical_sector_json(readiness, tmp_path / "sector.json")
    csv_path = export_historical_sector_csv(coverage, tmp_path / "sector.csv")

    assert coverage
    assert all(row.authoritative_classification_count == 0 for row in coverage)
    assert all(row.current_only_classification_count >= 0 for row in coverage)
    assert sector_state == ()
    assert "no authoritative effective-dated sector state" in state_text
    assert "current_only=" in coverage_text
    assert "BUILD_OFFICIAL_SECTOR_HISTORY_SOURCE" in readiness_text
    assert "SECTOR_SOURCE_AUTHORITY_IS_PRIMARY_LIMITATION" in readiness_text
    assert "primary_conclusion" in json_path.read_text(encoding="utf-8")
    assert csv_path.read_text(encoding="utf-8").startswith("market_date,")


def test_diagnostic_v3_is_blocked_and_leaves_v2_counts_unchanged(
    tmp_path: Path,
) -> None:
    store_path, ledger_path = _diagnostic_v2_store_and_ledger(tmp_path)
    ledger = LearningLedgerRepository(ledger_path)
    before = DiagnosticV2ValidationEngine(store_path=store_path).build(
        v1_reconstructions=(),
        records=ledger.load_records(),
        outcomes=ledger.load_outcomes(),
    )
    HistoricalSectorIngestionEngine(store_path=store_path).build(persist=True)

    v3 = DiagnosticMarketStateV3Engine(store_path=store_path).build(
        classifier_version="classifier-v1",
        classifier_fingerprint="fingerprint",
        persist=True,
    )
    comparison = DiagnosticMarketStateV3Engine(store_path=store_path).compare_v2_v3()
    after = DiagnosticV2ValidationEngine(store_path=store_path).build(
        v1_reconstructions=(),
        records=ledger.load_records(),
        outcomes=ledger.load_outcomes(),
    )
    rendered_v3 = "\n".join(render_diagnostic_v3_build(v3))
    rendered_comparison = "\n".join(render_v2_v3_comparison(comparison))

    assert v3.persistence_status == "BLOCKED_INSUFFICIENT_SECTOR_HISTORY"
    assert v3.reconstructions_created == 0
    assert v3.candidate_links_created == 0
    assert comparison.classification == "INSUFFICIENT_SECTOR_COVERAGE"
    assert after.integrity.reconstruction_count == before.integrity.reconstruction_count
    assert after.integrity.candidate_link_count == before.integrity.candidate_link_count
    assert "Blocked Reason:" in rendered_v3
    assert "INSUFFICIENT_SECTOR_COVERAGE" in rendered_comparison


def test_historical_sector_cli_commands_use_indexed_store(
    tmp_path: Path,
) -> None:
    store_path, ledger_path = _diagnostic_v2_store_and_ledger(tmp_path)
    env = {
        "ALPHA_POINT_IN_TIME_ANALYTICAL_STORE": str(store_path),
        "ALPHA_CANDIDATE_LEARNING_LEDGER": str(ledger_path),
        "ALPHA_DIAGNOSTIC_MARKET_STATE_LEDGER": str(tmp_path / "v1.json"),
    }
    runner = CliRunner()

    source = runner.invoke(app, ["replay", "sector-source-audit"], env=env)
    build = runner.invoke(
        app,
        ["replay", "historical-sector-build", "--persist-diagnostic"],
        env=env,
    )
    v3 = runner.invoke(app, ["replay", "diagnostic-market-state-v3-build"], env=env)
    state = runner.invoke(
        app,
        ["replay", "historical-sector-state", "--date", "2026-01-02"],
        env=env,
    )

    assert source.exit_code == 0
    assert "daily_prices.sector" in source.output
    assert build.exit_code == 0
    assert "Current-Only Rows:" in build.output
    assert v3.exit_code == 0
    assert "BLOCKED_INSUFFICIENT_SECTOR_HISTORY" in v3.output
    assert state.exit_code == 0
    assert "no authoritative effective-dated sector state" in state.output


def test_reporting_command_does_not_hidden_build_without_materialization(
    tmp_path: Path,
) -> None:
    result = CliRunner().invoke(
        app,
        ["replay", "point-in-time-universe-coverage"],
        env={
            "ALPHA_POINT_IN_TIME_ANALYTICAL_STORE": str(tmp_path / "pit.duckdb"),
            "ALPHA_POINT_IN_TIME_MATERIALIZATION_LEDGER": str(tmp_path / "pit.json"),
        },
    )

    assert result.exit_code != 0
    assert "Reporting commands do not silently trigger full historical rebuilds" in (
        result.output
    )


def _diagnostic_v2_validation_report(tmp_path: Path):
    store_path, ledger_path = _diagnostic_v2_store_and_ledger(tmp_path)
    ledger = LearningLedgerRepository(ledger_path)
    return DiagnosticV2ValidationEngine(store_path=store_path).build(
        v1_reconstructions=(),
        records=ledger.load_records(),
        outcomes=ledger.load_outcomes(),
    )


def _diagnostic_v2_store_and_ledger(tmp_path: Path) -> tuple[Path, Path]:
    materialization = (
        PointInTimeMaterializationEngine()
        .build(
            records=_records(),
            price_repository=_PriceRepository(),
            from_date=None,
            to_date=None,
            batch_size=4,
            persist=False,
        )
        .materialization
    )
    store_path = tmp_path / "pit.duckdb"
    repository = PointInTimeAnalyticalRepository(store_path)
    repository.import_materialization(
        build_id=materialization.manifest.build_id,
        materialization=materialization,
    )
    candidate = _candidate_record(date(2026, 1, 2))
    repository.build_diagnostic_v2(
        records=(candidate,),
        classifier_version="classifier-v1",
        classifier_fingerprint="fingerprint",
        dry_run=False,
        persist=True,
    )
    ledger_path = tmp_path / "candidate-learning.json"
    ledger = LearningLedgerRepository(ledger_path)
    ledger.save_records((candidate,))
    ledger.upsert_outcomes((_outcome(candidate.candidate_id, Decimal("5.00")),))
    return store_path, ledger_path


def _outcome(candidate_id: str, forward_return: Decimal) -> CandidateForwardOutcome:
    return CandidateForwardOutcome(
        candidate_id=candidate_id,
        symbol="AAA",
        evaluated_at=datetime(2026, 1, 31, tzinfo=UTC),
        windows=(
            CandidateForwardWindowOutcome(
                window="20d",
                forward_open=None,
                forward_high=None,
                forward_low=None,
                forward_close=None,
                forward_return_pct_from_close=forward_return,
                forward_return_pct_from_entry=forward_return,
                max_favourable_excursion_pct=max(forward_return, Decimal("0")),
                max_adverse_excursion_pct=min(forward_return, Decimal("0")),
                target_1_touched=forward_return > Decimal("0"),
                risk_stop_touched=forward_return < Decimal("0"),
                outcome_label=CandidateOutcomeLabel.WOULD_HAVE_WON
                if forward_return > Decimal("0")
                else CandidateOutcomeLabel.WOULD_HAVE_LOST,
            ),
        ),
    )


class _Candidate:
    def __init__(self, evaluation_date: date) -> None:
        self.candidate_id = f"candidate-{evaluation_date.isoformat()}"
        self.evaluation_date = evaluation_date
        self.symbol = "AAA"

    def as_dict(self) -> dict[str, str]:
        return {
            "candidate_id": self.candidate_id,
            "symbol": self.symbol,
        }


class _PriceRepository:
    def __init__(self) -> None:
        self.rows = _price_rows()

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        return pd.DataFrame(
            [row for row in self.rows if row["trade_date"] == trade_date],
            columns=(
                "symbol",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "sector",
                "exchange",
            ),
        )

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        symbol_set = {symbol.upper() for symbol in symbols}
        rows = [
            row
            for row in self.rows
            if row["symbol"].upper() in symbol_set and row["trade_date"] <= end_date
        ]
        rows = sorted(rows, key=lambda item: item["trade_date"])[-limit:]
        return pd.DataFrame(rows)


def _dataset(
    *,
    dataset_version: str = "pit-test-v1",
    dry_run: bool = True,
) -> PointInTimeUniverseDataset:
    return PointInTimeUniverseBuilder(
        dataset_version=dataset_version,
        created_at=datetime(2026, 1, 5, tzinfo=UTC),
    ).build(
        records=_records(),
        price_repository=_PriceRepository(),
        dry_run=dry_run,
    )


def _records() -> tuple[_Candidate, ...]:
    return tuple(_Candidate(date(2026, 1, day)) for day in range(1, 5))


def _candidate_record(evaluation_date: date) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        candidate_id=f"decision-{evaluation_date.isoformat()}",
        run_id="run-1",
        evaluation_date=evaluation_date,
        symbol="AAA",
        final_verdict="BUY",
        capital_action="BUY",
        approved_for_deployment=True,
        rejection_reasons=(),
        setup_type="BREAKOUT",
        market_regime="BULLISH",
        long_trade_permission=True,
        strategy_score=Decimal("75"),
        confidence="HIGH",
        data_quality="HIGH",
        entry_zone_low=Decimal("10"),
        entry_zone_high=Decimal("11"),
        confirmation_entry=Decimal("11"),
        risk_stop=Decimal("9"),
        target_1=Decimal("13"),
        target_2=Decimal("15"),
        target_3=Decimal("17"),
        trailing_stop_plan="2 ATR trail",
        expected_holding_period="20 days",
        indicators_active=("price-volume",),
        indicator_scores={"price": "0.80"},
        evidence_layers=("price-volume",),
        explanation="Synthetic candidate for point-in-time store test.",
        created_at=datetime(2026, 1, 2, 15, 30, tzinfo=UTC),
    )


def _price_rows() -> list[dict[str, object]]:
    return [
        _row("BBB", date(2026, 1, 1), "10", "10", "FINANCIALS"),
        _row("CCC", date(2026, 1, 1), "10", "10", "METALS"),
        _row("AAA", date(2026, 1, 2), "10", "11", "TECH"),
        _row("BBB", date(2026, 1, 2), "10", "9", "FINANCIALS"),
        _row("CCC", date(2026, 1, 2), "10", "10", "METALS"),
        _row("AAA", date(2026, 1, 3), "11", "12", "TECH"),
        _row("BBB", date(2026, 1, 3), "9", "8", "FINANCIALS"),
        _row("CCC", date(2026, 1, 3), "10", "11", "METALS"),
        _row("BBB", date(2026, 1, 4), "8", "8", "FINANCIALS"),
        _row("CCC", date(2026, 1, 4), "11", "12", "METALS"),
    ]


def _row(
    symbol: str,
    trade_date: date,
    opening: str,
    close: str,
    sector: str,
) -> dict[str, object]:
    close_value = Decimal(close)
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "open": Decimal(opening),
        "high": close_value + Decimal("1"),
        "low": close_value - Decimal("1"),
        "close": close_value,
        "volume": Decimal("1000"),
        "sector": sector,
        "exchange": "NSE",
    }
