from __future__ import annotations

from pathlib import Path

import duckdb
from typer.testing import CliRunner

from alpha.cli import app
from alpha.market_intelligence import (
    AcquisitionDecisionStatus,
    AcquisitionNextMilestone,
    AcquisitionPrimaryConclusion,
    CostValueTier,
    HistoricalSectorCoverageStatus,
    HistoricalSectorSourceAuthority,
    HistoricalSectorSourceFeasibilityEngine,
    IdentityJoinability,
    OperationalStatus,
    SectorNecessityClassification,
    SourceCombinationFinding,
    TaxonomyStability,
    TemporalSuitability,
    export_sector_source_csv,
    export_sector_source_json,
    render_sector_acquisition_decision,
    render_sector_source_candidates,
    render_sector_source_coverage,
)


def test_source_inventory_covers_required_source_categories(tmp_path: Path) -> None:
    engine = HistoricalSectorSourceFeasibilityEngine(store_path=_store(tmp_path))
    sources = {row.source_id: row for row in engine.source_candidates()}
    rendered = "\n".join(render_sector_source_candidates(tuple(sources.values())))

    assert sources["nse_industry_classification_structure"].authority is (
        HistoricalSectorSourceAuthority.OFFICIAL_WITH_LIMITATIONS
    )
    assert sources["commercial_historical_security_master_vendor"].authority is (
        HistoricalSectorSourceAuthority.STRONG_COMMERCIAL
    )
    assert sources["nse_securities_available_for_trading"].authority is (
        HistoricalSectorSourceAuthority.CURRENT_STATE_ONLY
    )
    assert sources["nse_index_constituent_archives"].authority is (
        HistoricalSectorSourceAuthority.INDEX_MEMBERSHIP_ONLY
    )
    assert sources["local_nse_bhavcopy_archives"].authority is (
        HistoricalSectorSourceAuthority.UNUSABLE
    )
    assert "Historical Sector Source Candidates" in rendered


def test_temporal_suitability_and_taxonomy_statuses_are_explicit(
    tmp_path: Path,
) -> None:
    engine = HistoricalSectorSourceFeasibilityEngine(store_path=_store(tmp_path))
    by_id = {row.source_id: row for row in engine.source_candidates()}
    taxonomy = {row.source_id: row for row in engine.taxonomy_audit()}

    assert by_id["nse_index_constituent_archives"].temporal_suitability is (
        TemporalSuitability.CHANGE_EVENT_DATED
    )
    assert by_id["local_nse_bhavcopy_archives"].temporal_suitability is (
        TemporalSuitability.ARCHIVED_SNAPSHOT_DATED
    )
    assert by_id["nse_sector_index_history"].temporal_suitability is (
        TemporalSuitability.PUBLICATION_DATE_ONLY
    )
    assert by_id["nse_securities_available_for_trading"].temporal_suitability is (
        TemporalSuitability.CURRENT_ONLY
    )
    assert (
        by_id["commercial_historical_security_master_vendor"].temporal_suitability
        is TemporalSuitability.TEMPORAL_STATUS_UNKNOWN
    )
    assert taxonomy["nse_industry_classification_structure"].stability is (
        TaxonomyStability.CURRENT_TAXONOMY_ONLY
    )
    assert taxonomy["commercial_historical_security_master_vendor"].stability is (
        TaxonomyStability.VERSIONED_WITHOUT_MAPPING
    )
    assert taxonomy["nse_sector_index_history"].stability is (
        TaxonomyStability.UNVERSIONED_TAXONOMY
    )


def test_local_sample_and_symbol_identity_join_are_diagnostic_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store_path = _store(tmp_path)
    _write_local_bhavcopy(tmp_path)
    monkeypatch.chdir(tmp_path)
    engine = HistoricalSectorSourceFeasibilityEngine(store_path=store_path)

    sample = engine.sample_source("local_nse_bhavcopy_archives")
    identity = engine.identity_test("local_nse_bhavcopy_archives")

    assert sample.sample_attempted is True
    assert sample.sample_records_parsed == 3
    assert "SYMBOL" in sample.fields_observed
    assert sample.sector_fields == ()
    assert identity.records_sampled == 3
    assert identity.symbol_lineage_matches == 2
    assert identity.ambiguous_matches == 1
    assert identity.unmatched_records == 0
    assert identity.joinability is IdentityJoinability.LOW_CONFIDENCE


def test_external_identity_joinability_is_estimated_without_fake_sample(
    tmp_path: Path,
) -> None:
    engine = HistoricalSectorSourceFeasibilityEngine(store_path=_store(tmp_path))

    isin_source = engine.identity_test("nse_securities_available_for_trading")
    symbol_source = engine.identity_test(
        "nse_indices_industry_classification_subscription"
    )
    no_identity = engine.identity_test("nse_sector_index_history")

    assert isin_source.records_sampled == 0
    assert isin_source.joinability is IdentityJoinability.HIGH_CONFIDENCE
    assert symbol_source.joinability is IdentityJoinability.MODERATE_CONFIDENCE
    assert no_identity.joinability is IdentityJoinability.UNUSABLE


def test_coverage_estimates_include_partial_none_and_unknown(tmp_path: Path) -> None:
    engine = HistoricalSectorSourceFeasibilityEngine(store_path=_store(tmp_path))
    coverage = {row.source_id: row for row in engine.coverage_estimates()}
    rendered = "\n".join(render_sector_source_coverage(tuple(coverage.values())))

    assert coverage["sebi_company_filings_and_annual_reports"].coverage_status is (
        HistoricalSectorCoverageStatus.PARTIAL
    )
    assert coverage["local_nse_bhavcopy_archives"].coverage_status is (
        HistoricalSectorCoverageStatus.NONE
    )
    assert (
        coverage["commercial_historical_security_master_vendor"].coverage_status
        is HistoricalSectorCoverageStatus.UNKNOWN
    )
    assert (
        coverage[
            "sebi_company_filings_and_annual_reports"
        ].candidate_dates_potentially_covered
        == 2
    )
    assert "Historical Sector Source Coverage Estimate" in rendered


def test_source_combinations_and_value_sensitivity_are_conservative(
    tmp_path: Path,
) -> None:
    engine = HistoricalSectorSourceFeasibilityEngine(store_path=_store(tmp_path))
    combinations = {row.combination_id: row for row in engine.source_combinations()}
    value = engine.sector_necessity()

    assert combinations["nse-indices-plus-security-master"].finding is (
        SourceCombinationFinding.MULTI_SOURCE_RECONSTRUCTION_HIGH_RISK
    )
    assert combinations["index-constituents-as-sector-proxy"].finding is (
        SourceCombinationFinding.NO_SAFE_SOURCE_COMBINATION
    )
    assert value.classification is (
        SectorNecessityClassification.SECTOR_UNUSED_BY_CURRENT_CLASSIFIER
    )
    assert value.candidate_dates_potentially_affected_by_sector == 0


def test_licensing_value_and_decision_matrix_do_not_recommend_ingestion(
    tmp_path: Path,
) -> None:
    engine = HistoricalSectorSourceFeasibilityEngine(store_path=_store(tmp_path))
    licensing = {row.source_id: row for row in engine.licensing_audit()}
    matrix = {row.source_id: row for row in engine.decision_matrix()}
    decision = engine.acquisition_decision()
    rendered = "\n".join(render_sector_acquisition_decision(decision))

    assert (
        licensing["commercial_historical_security_master_vendor"].operational_status
        is OperationalStatus.PAID_VENDOR_REQUIRED
    )
    assert matrix["local_nse_bhavcopy_archives"].decision is (
        AcquisitionDecisionStatus.REJECTED
    )
    assert matrix["nse_index_constituent_archives"].decision is (
        AcquisitionDecisionStatus.REJECTED
    )
    assert matrix["commercial_historical_security_master_vendor"].decision is (
        AcquisitionDecisionStatus.RESEARCH_ONLY
    )
    assert decision.expected_value is CostValueTier.UNKNOWN
    assert decision.primary_conclusion is (
        AcquisitionPrimaryConclusion.INSUFFICIENT_EVIDENCE_FOR_SECTOR_SOURCE_DECISION
    )
    assert decision.recommended_next_milestone is (
        AcquisitionNextMilestone.COLLECT_MORE_SOURCE_EVIDENCE
    )
    assert "Do not build diagnostic v3" in rendered


def test_source_cli_and_exports_are_deterministic(tmp_path: Path, monkeypatch) -> None:
    store_path = _store(tmp_path)
    _write_local_bhavcopy(tmp_path)
    monkeypatch.chdir(tmp_path)
    env = {"ALPHA_POINT_IN_TIME_ANALYTICAL_STORE": str(store_path)}
    runner = CliRunner()

    source_list = runner.invoke(
        app,
        ["replay", "historical-sector-source-list"],
        env=env,
    )
    sample = runner.invoke(
        app,
        [
            "replay",
            "historical-sector-source-sample",
            "--source",
            "local_nse_bhavcopy_archives",
        ],
        env=env,
    )
    decision = runner.invoke(
        app,
        ["replay", "historical-sector-acquisition-decision"],
        env=env,
    )

    assert source_list.exit_code == 0
    assert "nse_industry_classification_structure" in source_list.output
    assert sample.exit_code == 0
    assert "Sample Records Parsed: 3" in sample.output
    assert decision.exit_code == 0
    assert "INSUFFICIENT_EVIDENCE_FOR_SECTOR_SOURCE_DECISION" in decision.output

    engine = HistoricalSectorSourceFeasibilityEngine(store_path=store_path)
    json_path = export_sector_source_json(
        engine.acquisition_decision(),
        tmp_path / "decision.json",
    )
    csv_path = export_sector_source_csv(
        engine.decision_matrix(),
        tmp_path / "decision.csv",
    )

    assert "primary_conclusion" in json_path.read_text(encoding="utf-8")
    assert csv_path.read_text(encoding="utf-8").startswith("source_id,")


def _store(tmp_path: Path) -> Path:
    path = tmp_path / "pit.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute(
            """
            CREATE TABLE diagnostic_pit_security_master (
                security_id VARCHAR,
                symbol VARCHAR,
                isin VARCHAR
            )
            """
        )
        con.executemany(
            "INSERT INTO diagnostic_pit_security_master VALUES (?, ?, ?)",
            (
                ("sec-aaa", "AAA", "INE000A01001"),
                ("sec-bbb-1", "BBB", "INE000B01001"),
                ("sec-bbb-2", "BBB", "INE000B01002"),
                ("sec-ccc", "CCC", None),
            ),
        )
        con.execute(
            """
            CREATE TABLE diagnostic_market_state_v2_candidate_links (
                candidate_decision_timestamp TIMESTAMP
            )
            """
        )
        con.executemany(
            "INSERT INTO diagnostic_market_state_v2_candidate_links VALUES (?)",
            (
                ("2026-01-01 00:00:00",),
                ("2026-01-01 00:00:00",),
                ("2026-01-02 00:00:00",),
                ("2026-01-03 00:00:00",),
                ("2026-01-04 00:00:00",),
            ),
        )
        con.execute(
            """
            CREATE TABLE diagnostic_market_state_v2_reconstructions (
                sector_availability VARCHAR
            )
            """
        )
        con.executemany(
            "INSERT INTO diagnostic_market_state_v2_reconstructions VALUES (?)",
            (("SECTOR_STATE_UNAVAILABLE",), ("SECTOR_STATE_UNAVAILABLE",)),
        )
    return path


def _write_local_bhavcopy(tmp_path: Path) -> None:
    extracted = tmp_path / "data" / "extracted"
    extracted.mkdir(parents=True)
    (extracted / "cm01JAN2026bhav.csv").write_text(
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,VOLUME\n"
        "AAA,EQ,10,11,9,10,1000\n"
        "BBB,EQ,20,21,19,20,2000\n"
        "CCC,EQ,30,31,29,30,3000\n",
        encoding="utf-8",
    )
