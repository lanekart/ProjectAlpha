from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from alpha.application.setup_discovery_cli import setup_discovery_app
from alpha.setup_discovery.analysis_engine import (
    SetupVocabularyEngine,
    render_symbol_deep_dive,
)
from alpha.setup_discovery.clustering import UnsupportedSetupClusterEngine
from alpha.setup_discovery.exports import SetupDiscoveryExporter
from alpha.setup_discovery.lookback_engine import _evaluate_case
from alpha.setup_discovery.models import (
    ChartBar,
    EvidenceChart,
    EvidencePartition,
    GeometryState,
    LookbackEvidence,
    LookbackProofStatus,
    RawMissedSetupCase,
    ResearchRecommendation,
    SetupCluster,
    SetupDiscoveryManifest,
    SetupDiscoveryReport,
    SetupDiscoverySummary,
    SetupFeatureRecord,
    SetupRecommendationRecord,
    TopMissedOpportunity,
)
from alpha.setup_discovery.research_integration import research_diagnostic_plugins


def test_cluster_vector_and_labels_ignore_future_outcomes() -> None:
    records = _feature_population()
    changed = tuple(
        replace(
            item,
            forward_return=Decimal("-0.95") + Decimal(index) / Decimal("100"),
            net_return_60=Decimal("-0.80"),
            holding_period=999,
        )
        for index, item in enumerate(records)
    )

    assert [item.cluster_vector() for item in records] == [
        item.cluster_vector() for item in changed
    ]
    first = UnsupportedSetupClusterEngine().cluster(records)
    second = UnsupportedSetupClusterEngine().cluster(changed)

    assert 8 <= first.selected_k <= 15
    assert first.case_cluster == second.case_cluster
    assert sum(item.occurrences for item in first.clusters) == len(records)


def test_cluster_shares_use_full_unsupported_population() -> None:
    records = _feature_population()

    result = UnsupportedSetupClusterEngine().cluster(
        records, unsupported_population=len(records) + 10
    )

    assert sum(
        (item.unsupported_case_share for item in result.clusters), Decimal("0")
    ) == Decimal(len(records)) / Decimal(len(records) + 10)


def test_expanded_lookback_requires_causal_proof() -> None:
    history = _pullback_history()
    case = _case(
        case_id="lookback-proof",
        onset=history.iloc[-1]["trade_date"],
        family="PULLBACK_CONTINUATION",
        failure="LOOKBACK_MISMATCH",
    )

    result = _evaluate_case(case, history)

    assert result.status is LookbackProofStatus.CONFIRMED
    assert result.canonical_setup_detected is False
    assert result.minimum_visible_lookback == 120
    assert result.additional_bars_required == 60
    assert result.classification_retained is True
    assert result.first_detectable_date is not None
    assert result.window_results["60"] == "NOT_DETECTED"
    assert result.window_results["120"] == "DETECTED"


def test_lookback_claim_rejected_when_canonical_breakout_is_visible() -> None:
    history = _breakout_history()
    case = _case(
        case_id="canonical-visible",
        onset=history.iloc[-1]["trade_date"],
        family="VOLUME_BREAKOUT",
        failure="LOOKBACK_MISMATCH",
    )

    result = _evaluate_case(case, history)

    assert result.status is LookbackProofStatus.REJECTED_CANONICAL_WINDOW_SUFFICIENT
    assert result.classification_retained is False
    assert "not supported" in result.difference_explained


def test_chart_rejects_post_onset_bars() -> None:
    onset = date(2024, 1, 5)
    with pytest.raises(ValueError, match="post-onset"):
        EvidenceChart(
            case_id="future-leak",
            symbol="TEST",
            onset_date=onset,
            bars=(
                ChartBar(
                    observed_on=onset + timedelta(days=1),
                    close=Decimal("100"),
                    volume=Decimal("1000"),
                    ema_20=Decimal("99"),
                    ema_50=Decimal("95"),
                ),
            ),
        )


def test_vocabulary_discards_negative_holdout_family() -> None:
    cluster = replace(
        _cluster(),
        average_net_return_60=Decimal("0.05"),
        holdout_expectancy=Decimal("-0.02"),
    )

    catalog = SetupVocabularyEngine().catalog((cluster,))
    recommendations = SetupVocabularyEngine().recommendations(catalog)

    assert catalog[0].classification.value == "DISCARD"
    assert recommendations[0].recommendation is ResearchRecommendation.DO_NOT_INTRODUCE
    assert recommendations[0].production_eligible is False


def test_exporter_writes_required_evidence_artifacts_and_valid_pdf(
    tmp_path: Path,
) -> None:
    report = _report()

    paths = SetupDiscoveryExporter().export(report, output_directory=tmp_path)

    expected = {
        "setup_clusters.csv",
        "lookback_evidence.csv",
        "top100_missed_opportunities.pdf",
        "setup_family_catalog.json",
        "setup_recommendations.md",
        "kalyan_deep_dive.md",
        "pcjeweller_deep_dive.md",
    }
    assert expected.issubset({item.name for item in paths})
    pdf = (tmp_path / "top100_missed_opportunities.pdf").read_bytes()
    assert pdf.startswith(b"%PDF-1.4")
    assert b"Point-in-time chart" in pdf
    assert b"PRODUCTION_INFLUENCE=false" in pdf


def test_cli_summary_and_deep_dive_render_exported_evidence(tmp_path: Path) -> None:
    SetupDiscoveryExporter().export(_report(), output_directory=tmp_path)
    runner = CliRunner()

    summary = runner.invoke(setup_discovery_app, ["summary", "--output", str(tmp_path)])
    deep_dive = runner.invoke(
        setup_discovery_app,
        ["deep-dive", "--symbol", "KALYANKJIL", "--output", str(tmp_path)],
    )

    assert summary.exit_code == 0
    assert '"production_influence": false' in summary.stdout
    assert deep_dive.exit_code == 0
    assert "KALYANKJIL Setup and Lookback Deep Dive" in deep_dive.stdout


def test_ird_plugin_remains_diagnostic_only() -> None:
    plugin = research_diagnostic_plugins()[0]
    evidence = plugin.collect()

    assert plugin.diagnostic_id == "setup-discovery-evidence"
    assert evidence.production_influence is False


def test_deep_dive_states_when_modest_lookback_change_is_not_supported() -> None:
    result = replace(
        _lookback(),
        status=LookbackProofStatus.REJECTED_NO_EXPANDED_LOOKBACK_PROOF,
        classification_retained=False,
    )

    rendered = render_symbol_deep_dive(
        symbol="PCJEWELLER", timeline=(), lookbacks=(result,)
    )

    assert "None of the claimed mismatches survives causal proof" in rendered
    assert "PRODUCTION_INFLUENCE=false" in rendered


def _feature_population() -> tuple[SetupFeatureRecord, ...]:
    rows = []
    geometries = tuple(GeometryState)
    for index in range(40):
        group = index % 10
        geometry = geometries[group % len(geometries)]
        rows.append(
            SetupFeatureRecord(
                case_id=f"case-{index:03d}",
                event_id=f"event-{index:03d}",
                onset_id=f"onset-{index:03d}",
                symbol=f"SYM{index:03d}",
                onset_date=date(2020, 1, 1) + timedelta(days=index),
                event_family=("EMA_RECLAIM" if group < 5 else "EARLY_ACCUMULATION"),
                failure_reason="SETUP_FAMILY_NOT_SUPPORTED",
                base_duration=10 + group * 7,
                base_depth=Decimal(group + 1) / Decimal("100"),
                volatility_contraction=Decimal("0.50") + Decimal(group) / 10,
                moving_average_alignment=Decimal(group - 4) / Decimal("100"),
                relative_strength_trend=None,
                breakout_angle=Decimal(group) / Decimal("1000"),
                breakout_volume=Decimal("0.8") + Decimal(group) / 5,
                atr_expansion=Decimal("0.7") + Decimal(group) / 10,
                trend_slope=Decimal(group - 3) / Decimal("1000"),
                consolidation_geometry=geometry,
                liquidity_profile=Decimal("6") + Decimal(group) / 10,
                prospective_rr=Decimal("2.0"),
                onset_confidence=Decimal("0.70"),
                forward_return=Decimal("0.20"),
                holding_period=20,
                net_return_60=Decimal("0.05"),
                partition=(
                    EvidencePartition.DEVELOPMENT
                    if index < 24
                    else (
                        EvidencePartition.VALIDATION
                        if index < 32
                        else EvidencePartition.HOLDOUT
                    )
                ),
                feature_hash=f"hash-{index}",
            )
        )
    return tuple(rows)


def _case(
    *, case_id: str, onset: object, family: str, failure: str
) -> RawMissedSetupCase:
    observed_on = onset if isinstance(onset, date) else pd.Timestamp(onset).date()
    return RawMissedSetupCase(
        case_id=case_id,
        event_id=case_id,
        onset_id=f"onset-{case_id}",
        symbol="TEST",
        onset_date=observed_on,
        onset_sequence=1,
        event_family=family,
        failure_reason=failure,
        entry_trigger=Decimal("110"),
        prospective_stop=Decimal("100"),
        prospective_target=Decimal("130"),
        prospective_rr=Decimal("2"),
        onset_confidence=Decimal("0.80"),
        point_in_time_inputs={},
        forward_return=Decimal("0.25"),
        event_holding_period=30,
        event_start_date=observed_on,
        event_peak_date=observed_on + timedelta(days=30),
    )


def _pullback_history() -> pd.DataFrame:
    dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(120)]
    first = [80 + index * (20 / 29) for index in range(30)]
    second = [100 + index * (10 / 89) for index in range(90)]
    return _history(dates, first + second, final_volume=120)


def _breakout_history() -> pd.DataFrame:
    dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(80)]
    closes = [100 + (index % 5) * 0.05 for index in range(79)] + [102.0]
    return _history(dates, closes, final_volume=300)


def _history(
    dates: list[date], closes: list[float], *, final_volume: int
) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "trade_date": dates,
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
            "volume": [100] * (len(closes) - 1) + [final_volume],
        }
    )
    frame["ema_20"] = frame["close"].ewm(span=20, adjust=False).mean()
    frame["ema_50"] = frame["close"].ewm(span=50, adjust=False).mean()
    return frame


def _cluster() -> SetupCluster:
    return SetupCluster(
        cluster_id="SDE-FAMILY-01",
        family_name="Ascending Early Accumulation",
        occurrences=100,
        unsupported_case_share=Decimal("0.10"),
        dominant_event_family="EARLY_ACCUMULATION",
        family_purity=Decimal("0.80"),
        representative_symbols=("TEST",),
        representative_case_ids=("case-001",),
        representative_chart_pages=(2,),
        average_reward_risk=Decimal("2.10"),
        median_holding_period=Decimal("25"),
        average_forward_outcome=Decimal("0.25"),
        average_net_return_60=Decimal("0.04"),
        distinct_archetype_confidence=Decimal("0.70"),
        development_expectancy=Decimal("0.04"),
        validation_expectancy=Decimal("0.03"),
        holdout_expectancy=Decimal("0.02"),
        cross_partition_stability="STABLE",
        candidate_explosion_risk="MODERATE",
        feature_centroid={"base_duration": "30"},
    )


def _lookback() -> LookbackEvidence:
    return LookbackEvidence(
        case_id="case-001",
        event_id="event-001",
        onset_id="onset-001",
        symbol="PCJEWELLER",
        event_family="VOLUME_BREAKOUT",
        onset_date=date(2022, 6, 10),
        canonical_lookback=60,
        canonical_setup_detected=False,
        minimum_visible_lookback=None,
        first_detectable_date=None,
        expanded_candidate_date=None,
        additional_bars_required=None,
        entry_extension=None,
        extension_acceptable=None,
        window_results={
            "60": "NOT_DETECTED",
            "90": "NOT_DETECTED",
            "120": "NOT_DETECTED",
            "160": "NOT_DETECTED",
            "200": "NOT_DETECTED",
        },
        status=LookbackProofStatus.REJECTED_NO_EXPANDED_LOOKBACK_PROOF,
        classification_retained=False,
        difference_explained="No expanded proof.",
        evidence_hash="proof-hash",
    )


def _report() -> SetupDiscoveryReport:
    feature = _feature_population()[0]
    cluster = _cluster()
    catalog = SetupVocabularyEngine().catalog((cluster,))
    recommendation = SetupRecommendationRecord(
        cluster_id=cluster.cluster_id,
        family_name=cluster.family_name,
        recommendation=ResearchRecommendation.INTRODUCE_AS_RESEARCH_SETUP,
        evidence_strength="HIGH",
        risk="MODERATE",
        reason="Isolated research only.",
    )
    top = TopMissedOpportunity(
        rank=1,
        case_id=feature.case_id,
        symbol=feature.symbol,
        onset_date=feature.onset_date,
        event_family=feature.event_family,
        cluster_id=cluster.cluster_id,
        cluster_name=cluster.family_name,
        canonical_detection_state="UNSUPPORTED_SETUP_FAMILY",
        unsupported_pattern_description="An unsupported causal setup pattern.",
        canonical_lookback=60,
        required_lookback=None,
        prospective_rr=Decimal("2"),
        candidate_blocker="SETUP_FAMILY_NOT_SUPPORTED",
        classification_confidence=Decimal("0.70"),
        forward_outcome=Decimal("0.20"),
        evidence_book_page=2,
    )
    chart = EvidenceChart(
        case_id=feature.case_id,
        symbol=feature.symbol,
        onset_date=feature.onset_date,
        bars=tuple(
            ChartBar(
                observed_on=feature.onset_date - timedelta(days=10 - index),
                close=Decimal(100 + index),
                volume=Decimal(1000 + index * 100),
                ema_20=Decimal(99 + index),
                ema_50=Decimal(95 + index),
            )
            for index in range(10)
        ),
    )
    manifest = SetupDiscoveryManifest(
        policy_id="SDE_RESEARCH_v1.0",
        parent_policy_id="ALPHA_CANONICAL_v1.0",
        source_audit_id="TEST",
        dataset_version="TEST",
        feature_version="TEST",
        clustering_version="TEST",
        lookback_version="TEST",
        canonical_lookback=60,
        expanded_lookbacks=(90, 120, 160, 200),
        cluster_bounds=(8, 15),
        outcomes_excluded_from_clustering=True,
    )
    summary = SetupDiscoverySummary(
        unsupported_cases=100,
        unsupported_cases_clustered=90,
        unsupported_cases_unclustered=10,
        lookback_cases_claimed=1,
        lookback_cases_confirmed=0,
        lookback_cases_rejected=1,
        lookback_cases_data_insufficient=0,
        clusters_selected=8,
        top_three_clusters=(cluster.family_name,),
        top_three_case_share=Decimal("0.10"),
        strongest_research_family=cluster.family_name,
        families_not_to_add=(),
        overall_evidence_confidence="MODERATE",
    )
    deep_dive = (
        "# KALYANKJIL Setup and Lookback Deep Dive\n\nPRODUCTION_INFLUENCE=false\n"
    )
    return SetupDiscoveryReport(
        report_id="SDE-TEST",
        generated_at=datetime(2024, 1, 1, tzinfo=UTC),
        manifest=manifest,
        features=(feature,),
        clusters=(cluster,),
        lookback_evidence=(_lookback(),),
        top_opportunities=(top,),
        charts=(chart,),
        catalog=catalog,
        recommendations=(recommendation,),
        kalyan_deep_dive=deep_dive,
        pcjeweller_deep_dive=deep_dive.replace("KALYANKJIL", "PCJEWELLER"),
        summary=summary,
    )
