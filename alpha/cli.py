from __future__ import annotations

import asyncio
import csv
import os
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from datetime import date as dt_date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import typer

from alpha.application.acu_cli import acu_app
from alpha.application.adaptive_weights_cli import adaptive_weights_app
from alpha.application.autonomous_loop_cli import autonomous_app
from alpha.application.backtest import BacktestApplicationService, BacktestSummary
from alpha.application.backtest_export import BacktestExportService
from alpha.application.benchmark_cli import benchmark_app
from alpha.application.candidate_research_cli import candidate_research_app
from alpha.application.continuous_learning_cli import (
    continuous_learning_report_lines,
    register_continuous_learning_commands,
)
from alpha.application.data_platform_cli import data_app
from alpha.application.data_value_cli import data_value_app
from alpha.application.feature_attribution_cli import feature_attribution_app
from alpha.application.forward_cli import forward_app
from alpha.application.gate_dependency_cli import gate_dependency_app
from alpha.application.gate_truth_cli import gate_app
from alpha.application.historical_ingestion import HistoricalIngestionService
from alpha.application.integrity_audit_cli import integrity_audit_app
from alpha.application.intelligence import (
    IntelligenceRun,
    _allocation_reason,
    _allocation_status,
    _capital_deployment_dashboard_lines,
    _execution_status,
    _recommendation_detail_lines,
    _sector_metadata_notice,
    _verdict_label,
)
from alpha.application.intelligence_export import IntelligenceExportService
from alpha.application.market_dna_cli import market_dna_app
from alpha.application.market_opportunity_cli import market_opportunity_app
from alpha.application.market_truth_cli import market_truth_app
from alpha.application.pine_cli import pine_app
from alpha.application.point_in_time_universe_cli import universe_app
from alpha.application.research_cli import research_app
from alpha.application.runtime import ProjectAlphaRuntime
from alpha.application.runtime_models import RuntimeResult
from alpha.application.setup_discovery_cli import setup_discovery_app
from alpha.application.strategy_discovery_cli import strategy_app
from alpha.application.strategy_lab_cli import strategy_lab_app
from alpha.application.trl_cli import trl_app
from alpha.application.warehouse_cli import warehouse_app
from alpha.application.warehouse_delta_cli import warehouse_delta_app
from alpha.backtest.backtest_report import BacktestReportRenderer
from alpha.candidate_learning import (
    ApprovalBaselineAuditEngine,
    ApprovalBaselineComparison,
    ApprovalDiagnosticsConfig,
    ApprovalDiagnosticsEngine,
    ApprovalDiagnosticSummary,
    ApprovalOutcomeAnalysisEngine,
    ApprovalOutcomeReport,
    CandidateMarketStateContext,
    DirectionalSignalAuditReport,
    DirectionalSignalQualityAuditEngine,
    EntryTimingReplayReport,
    EntryTimingValidationEngine,
    EntryTimingValidationReport,
    GateAttributionReport,
    MarketRegimeAuditEngine,
    MarketRegimeAuditReport,
    MarketStatePersistenceAuditEngine,
    MarketStatePersistenceAuditReport,
    NightlyLearningLoop,
    NonEntryGateAttributionEngine,
    build_entry_timing_replay_report,
    export_approval_baseline_csv,
    export_approval_baseline_json,
    export_approval_diagnostics_csv,
    export_approval_diagnostics_json,
    export_approval_outcomes_csv,
    export_approval_outcomes_json,
    export_directional_signal_audit_csv,
    export_directional_signal_audit_json,
    export_entry_opportunities_csv,
    export_entry_opportunities_json,
    export_entry_timing_csv,
    export_entry_timing_failures_csv,
    export_entry_timing_failures_json,
    export_entry_timing_json,
    export_entry_timing_validation_csv,
    export_entry_timing_validation_json,
    export_gate_attribution_csv,
    export_gate_attribution_json,
    export_gate_candidate_audit_csv,
    export_gate_candidate_audit_json,
    export_market_regime_audit_csv,
    export_market_regime_audit_json,
    export_market_state_persistence_audit_csv,
    export_market_state_persistence_audit_json,
    export_profitable_rejections_csv,
    export_profitable_rejections_json,
    filter_diagnostics,
    filter_entry_timing_rows,
    filter_profitable_rejections,
    group_approval_outcomes,
    group_diagnostics,
    group_directional_signal_audit,
    group_entry_timing_report,
    group_entry_timing_validation_report,
    group_gate_attribution_report,
    group_market_regime_audit,
    group_market_state_persistence_audit,
    render_approval_baseline_audit,
    render_approval_diagnostics,
    render_approval_failures,
    render_approval_outcomes,
    render_directional_signal_audit,
    render_entry_opportunities,
    render_entry_timing_failures,
    render_entry_timing_report,
    render_entry_timing_validation_report,
    render_gate_attribution_report,
    render_market_regime_audit,
    render_market_state_persistence_audit,
    render_profitable_rejections,
    render_raw_universe_summary,
)
from alpha.candidate_learning.regime_influence import (
    RegimeProductionInfluenceAuditEngine,
    export_regime_influence_csv,
    export_regime_influence_json,
    render_recorded_vs_v2_regime_influence,
    render_regime_allocation_influence,
    render_regime_approval_influence,
    render_regime_asymmetry,
    render_regime_context_only,
    render_regime_production_dependency,
    render_regime_ranking_influence,
    render_regime_safe_deactivation_readiness,
    render_regime_score_influence,
    render_regime_selection_influence,
    render_regime_setup_influence,
    render_regime_verdict_influence,
)
from alpha.candidate_learning.regime_shadow import (
    RegimeShadowEngine,
    export_regime_shadow_csv,
    export_regime_shadow_json,
    render_regime_shadow_approval_comparison,
    render_regime_shadow_bearish_protection,
    render_regime_shadow_build,
    render_regime_shadow_bullish_promotion,
    render_regime_shadow_integrity,
    render_regime_shadow_outcomes,
    render_regime_shadow_quality,
    render_regime_shadow_readiness,
    render_regime_shadow_score_comparison,
    render_regime_shadow_setup_attribution,
    render_regime_shadow_status,
    render_regime_shadow_temporal_stability,
    render_regime_shadow_verdict_comparison,
)
from alpha.candidate_learning.regime_shadow_live import (
    AlphaLiveShadowRuntimeService,
    LiveRegimeShadowCaptureConfig,
    LiveRegimeShadowCaptureService,
    LiveRegimeShadowEvidenceEngine,
    LiveShadowSourceMode,
    export_live_regime_shadow_csv,
    export_live_regime_shadow_json,
    frozen_input_from_candidate,
    render_alpha_live_wiring,
    render_live_shadow_status,
)
from alpha.candidate_learning.regime_shadow_live import (
    render_bearish_protection as render_live_regime_shadow_bearish_protection,
)
from alpha.candidate_learning.regime_shadow_live import (
    render_capture_failures as render_live_regime_shadow_capture_failures,
)
from alpha.candidate_learning.regime_shadow_live import (
    render_capture_health as render_live_regime_shadow_capture_health,
)
from alpha.candidate_learning.regime_shadow_live import (
    render_capture_manifests as render_live_regime_shadow_capture_manifests,
)
from alpha.candidate_learning.regime_shadow_live import (
    render_capture_result as render_live_regime_shadow_capture_result,
)
from alpha.candidate_learning.regime_shadow_live import (
    render_context_harm as render_live_regime_shadow_context_harm,
)
from alpha.candidate_learning.regime_shadow_live import (
    render_coverage as render_live_regime_shadow_coverage,
)
from alpha.candidate_learning.regime_shadow_live import (
    render_drift as render_live_regime_shadow_drift,
)
from alpha.candidate_learning.regime_shadow_live import (
    render_guardrails as render_live_regime_shadow_guardrails,
)
from alpha.candidate_learning.regime_shadow_live import (
    render_input_parity as render_live_regime_shadow_input_parity,
)
from alpha.candidate_learning.regime_shadow_live import (
    render_operational_readiness as render_live_regime_shadow_operational_readiness,
)
from alpha.candidate_learning.regime_shadow_live import (
    render_outcome_maturity as render_live_regime_shadow_outcome_maturity,
)
from alpha.candidate_learning.regime_shadow_live import (
    render_policy_differences as render_live_regime_shadow_policy_differences,
)
from alpha.candidate_learning.regime_shadow_live import (
    render_readiness as render_live_regime_shadow_readiness,
)
from alpha.candidate_learning.regime_shadow_live import (
    render_refresh as render_live_regime_shadow_refresh,
)
from alpha.candidate_learning.regime_shadow_live import (
    render_repair as render_live_regime_shadow_repair,
)
from alpha.candidate_learning.regime_shadow_live import (
    render_review as render_live_regime_shadow_review,
)
from alpha.candidate_learning.regime_shadow_live import (
    render_runtime_coverage as render_live_regime_shadow_runtime_coverage,
)
from alpha.candidate_learning.regime_shadow_live import (
    render_setup as render_live_regime_shadow_setup,
)
from alpha.candidate_learning.regime_shadow_live import (
    render_temporal as render_live_regime_shadow_temporal,
)
from alpha.decision_intelligence import (
    DecisionEvidenceCardBuilder,
    InstitutionalDecisionService,
    TradeSetupDisqualificationReporter,
    render_decision_audit,
    render_decision_evidence_cards,
    render_decision_report,
    render_default_opportunities,
    render_trade_plan_audit,
    render_trade_setup_disqualification_report,
)
from alpha.exceptions import BhavcopyNotFoundError, ProjectAlphaError
from alpha.forward_validation.forward_validation_engine import ForwardValidationEngine
from alpha.forward_validation.validation_registry import ForwardValidationRegistry
from alpha.historical_replay import (
    BayesianWeightUpdater,
    BestSetupPlaybookBuilder,
    BreakoutGapCause,
    BreakoutGapRecoveryClass,
    BreakoutReferenceMethod,
    DirectionalObservation,
    DirectionalOutcomeDefinition,
    DirectionalOutcomeFamily,
    DirectionalPolicyDirection,
    EvidenceCubeBuilder,
    FeatureImportanceEngine,
    FrontierPoint,
    HistoricalCredentialStatus,
    HistoricalDataCoverageAnalyzer,
    HistoricalEvidenceService,
    HistoricalObservationFactory,
    HistoricalReplayEngine,
    HistoricalReplayRepository,
    HistoricalReplaySampler,
    HistoricalSourceRecommendationReport,
    PrecisionCoverageReport,
    ReplaySampleFrequency,
    ReplaySamplePlan,
    SimilarPatternScanner,
    SimulationLab,
    SimulationParameters,
    WalkForwardEngine,
    WalkForwardSplit,
    audit_breakout_reference_integrity,
    build_breakout_historical_readiness_report,
    build_breakout_intelligence_report,
    build_buy_signal_reconstruction_report,
    build_confirmation_intelligence_report,
    build_directional_calibration_report,
    build_opportunity_evolution_report,
    build_policy_audit_report,
    build_policy_candidate_report,
    build_precision_coverage_report,
    build_project_breakout_source_gap_audit,
    build_project_historical_source_evaluation,
    count_filtered_replay_candidates,
    coverage_csv_rows,
    export_breakout_gap_csv,
    export_breakout_gap_json,
    export_breakout_intelligence_csv,
    export_breakout_intelligence_json,
    export_breakout_reference_csv,
    export_breakout_reference_json,
    export_buy_model_results_csv,
    export_buy_reconstruction_json,
    export_calibration_csv,
    export_calibration_json,
    export_confirmation_intelligence_csv,
    export_confirmation_intelligence_json,
    export_frontier_csv,
    export_historical_source_csv,
    export_historical_source_json,
    export_opportunity_evolution_csv,
    export_opportunity_evolution_json,
    export_policy_audit_json,
    export_policy_candidates_json,
    export_precision_coverage_json,
    filter_buy_model_results,
    group_breakout_report,
    group_buy_report,
    group_confirmation_report,
    group_opportunity_report,
    historical_source_requirements,
    license_csv_rows,
    load_filtered_breakout_reference_records,
    manifest_csv_rows,
    parse_breakout_gap_cause,
    parse_breakout_recovery_class,
    parse_breakout_reference_method,
    parse_historical_credential_status,
    reconstruct_breakout_references_from_project_sources,
    render_best_setup_playbook,
    render_breakout_class_frontier,
    render_breakout_classification_audit,
    render_breakout_gap_groups,
    render_breakout_gap_sample,
    render_breakout_intelligence_report,
    render_breakout_lineage_audit,
    render_breakout_opportunity_paths,
    render_breakout_recovery_readiness,
    render_breakout_reference_integrity,
    render_breakout_reference_provenance,
    render_breakout_reference_readiness,
    render_breakout_reference_reconstruction,
    render_breakout_reference_sample,
    render_breakout_rs_independence,
    render_breakout_selection_bias,
    render_breakout_source_coverage,
    render_breakout_source_gap_audit,
    render_breakout_stability_audit,
    render_breakout_transition_audit,
    render_buy_false_negative_audit,
    render_buy_false_positive_audit,
    render_buy_feature_ablation,
    render_buy_minimal_models,
    render_buy_precision_frontier,
    render_buy_signal_reconstruction_report,
    render_calibration_report,
    render_confirmation_delay_audit,
    render_confirmation_frontier,
    render_confirmation_intelligence_report,
    render_data_coverage_report,
    render_early_entry_failures,
    render_entry_trigger_discovery,
    render_entry_trigger_frontier,
    render_evidence_report,
    render_false_breakout_analysis,
    render_false_breakout_audit,
    render_feature_importance,
    render_historical_evidence_snapshot,
    render_historical_source_coverage,
    render_historical_source_evaluation,
    render_historical_source_license_audit,
    render_historical_source_manifest,
    render_historical_source_recommendation,
    render_historical_source_requirements,
    render_lifecycle_audit,
    render_opportunity_evolution_report,
    render_opportunity_paths,
    render_participation_confirmation,
    render_policy_audit_report,
    render_policy_candidate_report,
    render_precision_coverage_report,
    render_replay_run,
    render_replay_sample_plan,
    render_replay_summary,
    render_retest_quality_audit,
    render_similar_pattern_report,
    render_simulation_result,
    render_trigger_cancellation_audit,
    render_trigger_failure_attribution,
    render_trigger_persistence_audit,
    render_walk_forward,
    render_weight_suggestions,
    requirement_csv_rows,
)
from alpha.historical_replay.historical_identity_bridge import (
    EffectiveDatedIdentityRecord,
    HistoricalIdentityAuditBundle,
    ProjectHistoricalIdentityAuditService,
    export_identity_json,
    export_identity_records_csv,
    export_identity_summary_csv,
    filter_identity_records,
    render_historical_identity_bridge_audit,
    render_historical_identity_provisional,
    render_historical_identity_readiness,
    render_historical_identity_source_coverage,
    render_historical_identity_unresolved,
    render_upstox_duplicate_origin_audit,
    render_upstox_identity_metadata_audit,
)
from alpha.historical_replay.nse_archive_proof import (
    NSE_TRIAL_DATE_FROM,
    NSE_TRIAL_DATE_TO,
    NseArchiveProofBundle,
    NseArchiveSourceType,
    NseCorporateActionProofRecord,
    NseIdentityProofEngine,
    NseIdentityProofRecord,
    export_nse_proof_csv,
    export_nse_proof_json,
    render_nse_archive_coverage,
    render_nse_archive_readiness,
    render_nse_archive_source_discovery,
    render_nse_corporate_action_proof,
    render_nse_identity_proof,
    render_nse_security_file_inspect,
)
from alpha.historical_replay.nse_archive_proof_service import (
    ProjectNseArchiveProofService,
)
from alpha.historical_replay.upstox_full_population_utility import (
    UpstoxFullPopulationUtilityEngine,
    render_upstox_full_population_utility,
)
from alpha.historical_replay.upstox_historical_probe import (
    DEFAULT_UPSTOX_HISTORICAL_EVIDENCE_PATH,
    UpstoxHistoricalCandidateEvidence,
    UpstoxHistoricalEvidenceRepository,
    export_upstox_evidence_csv,
    export_upstox_evidence_json,
    render_upstox_adjustment_audit,
    render_upstox_auth_probe,
    render_upstox_evidence_report,
    render_upstox_historical_coverage,
    render_upstox_historical_sample,
    render_upstox_identity_coverage,
)
from alpha.historical_replay.upstox_historical_probe_service import (
    UpstoxHistoricalProbeRun,
    UpstoxHistoricalProbeService,
)
from alpha.historical_replay.upstox_series_integrity import (
    UpstoxSeriesIntegrityEngine,
    UpstoxSeriesIntegrityReport,
    export_upstox_series_integrity_csv,
    filter_upstox_series_records,
    render_upstox_series_integrity,
)
from alpha.learning_intelligence import AdaptiveLearningService
from alpha.live import (
    RECORDED_UPSTOX_FIXTURE_NAME,
    InstrumentSubscription,
    RecordedUpstoxReadinessAuditEngine,
    UpstoxAuthService,
    UpstoxLiveAcceptanceHarness,
    UpstoxLiveMarketDataProvider,
    UpstoxProviderPreflight,
    build_protocol_audit_report,
    export_protocol_audit_json,
    export_upstox_live_acceptance_json,
    export_upstox_readiness_audit_json,
    prompt_authorization_code,
    render_protocol_audit,
    render_upstox_live_acceptance,
    render_upstox_readiness_audit,
    render_upstox_status,
    run_live_monitor,
)
from alpha.market_intelligence import (
    DIAGNOSTIC_MARKET_STATE_DATASET_VERSION,
    MARKET_STATE_CLASSIFIER_VERSION,
    BenchmarkCoverageReport,
    BenchmarkStateBuilder,
    DiagnosticMarketStateCoverageReport,
    DiagnosticMarketStateDataset,
    DiagnosticMarketStateReconstructionEngine,
    DiagnosticMarketStateRepository,
    DiagnosticMarketStateV3Engine,
    DiagnosticRegimeComparisonReport,
    DiagnosticRegimeOutcomeValidationEngine,
    DiagnosticThresholdReadinessReport,
    DiagnosticV2ValidationEngine,
    DiagnosticV2ValidationReport,
    HistoricalMarketStateBackfillReadinessEngine,
    HistoricalMarketStateBackfillReadinessReport,
    HistoricalSectorIngestionEngine,
    HistoricalSectorRepository,
    HistoricalSectorSourceFeasibilityEngine,
    MarketStatePersistenceResult,
    MarketStatePersistenceStatus,
    MarketStateSnapshot,
    MarketStateSnapshotRepository,
    PointInTimeAnalyticalRepository,
    PointInTimeBuildStatus,
    PointInTimeMaterializationEngine,
    PointInTimeMaterializationRepository,
    PointInTimeMaterializedDataset,
    PointInTimeUniverseBuilder,
    PointInTimeUniverseDataset,
    PointInTimeValidationStatus,
    RegimeSimplificationAuditEngine,
    benchmark_coverage_report,
    benchmark_history_audit,
    build_diagnostic_market_state_coverage_report,
    build_diagnostic_v2_report,
    build_historical_sector_readiness,
    build_historical_source_inventory,
    build_listing_delisting_audit,
    build_market_state_backfill_plan,
    build_materialized_survivorship_bias_audit,
    build_no_lookahead_report,
    build_regime_comparison_report,
    build_sector_conflicts,
    build_sector_coverage_audit,
    build_sector_incremental_value_report,
    build_sector_state_report,
    build_security_identity_audit,
    build_universe_coverage_report,
    canonical_benchmark_configuration,
    default_sector_taxonomies,
    export_backfill_readiness_csv,
    export_backfill_readiness_json,
    export_benchmark_coverage_csv,
    export_benchmark_coverage_json,
    export_diagnostic_json,
    export_diagnostic_outcome_json,
    export_diagnostic_rows_csv,
    export_diagnostic_v2_csv,
    export_diagnostic_v2_json,
    export_historical_sector_csv,
    export_historical_sector_json,
    export_point_in_time_csv,
    export_point_in_time_json,
    export_reconstructions_csv,
    export_regime_simplification_csv,
    export_regime_simplification_json,
    export_sector_source_csv,
    export_sector_source_json,
    render_backfill_readiness_report,
    render_benchmark_completeness,
    render_benchmark_configuration,
    render_benchmark_coverage,
    render_benchmark_date_reconciliation,
    render_benchmark_history,
    render_benchmark_lookback_gaps,
    render_benchmark_proxy_suitability,
    render_benchmark_source_integrity,
    render_breadth_sensitivity,
    render_breadth_snapshots,
    render_classifier_version_readiness,
    render_diagnostic_build_result,
    render_diagnostic_coverage,
    render_diagnostic_history,
    render_diagnostic_lineage,
    render_diagnostic_quality,
    render_diagnostic_show,
    render_diagnostic_v2_alignment,
    render_diagnostic_v2_breadth_value,
    render_diagnostic_v2_build,
    render_diagnostic_v2_coherence,
    render_diagnostic_v2_integrity,
    render_diagnostic_v2_intervention,
    render_diagnostic_v2_outcomes,
    render_diagnostic_v2_quality,
    render_diagnostic_v2_readiness,
    render_diagnostic_v2_retracement_regime,
    render_diagnostic_v2_sector_materiality,
    render_diagnostic_v2_selection_effect,
    render_diagnostic_v2_setup_regime,
    render_diagnostic_v2_store_build,
    render_diagnostic_v2_threshold_stability,
    render_diagnostic_v3_build,
    render_historical_breadth_readiness,
    render_historical_sector_build,
    render_historical_sector_changes,
    render_historical_sector_conflicts,
    render_historical_sector_coverage,
    render_historical_sector_decision_readiness,
    render_historical_sector_readiness,
    render_historical_sector_show,
    render_historical_sector_state,
    render_historical_sector_status,
    render_historical_sector_validation,
    render_listing_delisting_audit,
    render_market_input_inventory,
    render_market_state_backfill_plan,
    render_market_state_backfill_simulation,
    render_market_state_coverage,
    render_market_state_history,
    render_market_state_lineage,
    render_market_state_persistence_result,
    render_market_state_snapshot,
    render_neutral_collapse,
    render_no_lookahead,
    render_point_in_time_build_history,
    render_point_in_time_build_profile,
    render_point_in_time_build_result,
    render_point_in_time_build_status,
    render_point_in_time_history_readiness,
    render_point_in_time_store_equivalence,
    render_point_in_time_store_import,
    render_point_in_time_store_profile,
    render_point_in_time_store_status,
    render_point_in_time_store_validation,
    render_point_in_time_validation,
    render_regime_coherence,
    render_regime_comparison,
    render_regime_episodes,
    render_regime_input_dependency,
    render_regime_interactions,
    render_regime_intervention,
    render_regime_outcomes,
    render_regime_parsimony_decision,
    render_retracement_regime,
    render_sector_acquisition_decision,
    render_sector_conflicts,
    render_sector_coverage,
    render_sector_incremental_value,
    render_sector_maximum_impact,
    render_sector_sensitivity,
    render_sector_source_audit,
    render_sector_source_candidates,
    render_sector_source_combinations,
    render_sector_source_coverage,
    render_sector_source_identity,
    render_sector_source_licensing,
    render_sector_source_sample,
    render_sector_source_show,
    render_sector_source_taxonomy,
    render_sector_source_value,
    render_sector_state,
    render_sector_taxonomies,
    render_security_identity_audit,
    render_selection_effect,
    render_setup_regime,
    render_simplified_regime_distribution,
    render_simplified_regime_incremental_value,
    render_simplified_regime_interpretability,
    render_simplified_regime_intervention,
    render_simplified_regime_models,
    render_simplified_regime_outcomes,
    render_simplified_regime_quality,
    render_simplified_regime_selection_effect,
    render_simplified_regime_threshold_stability,
    render_source_inventory,
    render_survivorship_bias,
    render_threshold_density,
    render_threshold_readiness,
    render_threshold_stability,
    render_universe_coverage,
    render_universe_show,
    render_v2_v3_comparison,
    validate_historical_sector_store,
    validate_point_in_time_materialization,
)
from alpha.market_truth.consumer_repository import MarketTruthPriceRepository
from alpha.performance_intelligence import (
    PerformanceIntelligenceService,
    RecommendationLedgerRepository,
    RecommendationPerformanceRecorder,
    render_tracking_summary,
    render_update_summary,
    resolve_ledger_path,
)
from alpha.provenance import (
    DecisionProvenance,
    DecisionProvenanceRepository,
    HistoricalManifestAuditReport,
    VersionDriftReport,
    VersionLineageAuditReport,
    build_historical_manifest_audit,
    build_version_drift_report,
    build_version_lineage_audit,
    capture_current_provenance,
    current_component_registry,
    current_market_classifier_fingerprint,
    export_historical_manifest_assignments_csv,
    export_historical_manifest_report_json,
    export_version_lineage_csv,
    export_version_lineage_json,
    render_analytical_release_manifest,
    render_analytical_release_manifest_entry,
    render_backfill_version_eligibility,
    render_component_registry,
    render_current_provenance,
    render_historical_analytical_eras,
    render_historical_backfill_manifest_eligibility,
    render_historical_era_assignments,
    render_historical_manifest_coverage,
    render_historical_release_evidence,
    render_manifest_validation,
    render_provenance_coverage,
    render_provenance_history,
    render_version_compatibility,
    render_version_drift,
    render_version_evidence,
    render_version_lineage_report,
)
from alpha.release import current_release
from alpha.strategy_regime import (
    HoldingPeriod,
    MarketRegime,
    StrategyRegimeBacktestEngine,
    StrategyRegimeBacktestRepository,
    render_backtest_run,
    render_strategy_regime_report,
)
from alpha.trade_review import (
    LiveTradeReviewEngine,
    UserTradeJournalRepository,
    render_live_trade_review,
    render_user_trade_journal,
    render_user_trade_journal_summary,
)
from alpha.version import __version__

app = typer.Typer()
performance_app = typer.Typer()
outcomes_app = typer.Typer()
learning_app = typer.Typer()
register_continuous_learning_commands(learning_app)
decision_app = typer.Typer()
tradeplan_app = typer.Typer()
strategy_regime_app = typer.Typer()
replay_app = typer.Typer()
evidence_app = typer.Typer()
simulate_app = typer.Typer()
trades_app = typer.Typer()
playbook_app = typer.Typer()
market_state_app = typer.Typer()
provenance_app = typer.Typer()
provenance_manifest_app = typer.Typer(invoke_without_command=True)
provider_app = typer.Typer()
upstox_app = typer.Typer()
app.add_typer(research_app, name="research")
app.add_typer(benchmark_app, name="benchmark")
app.add_typer(gate_app, name="gate")
app.add_typer(gate_dependency_app, name="gate-dependency")
app.add_typer(acu_app, name="acu")
app.add_typer(integrity_audit_app, name="integrity-audit")
app.add_typer(candidate_research_app, name="candidate-research")
app.add_typer(setup_discovery_app, name="setup-discovery")
app.add_typer(feature_attribution_app, name="feature-attribution")
app.add_typer(universe_app, name="universe")
app.add_typer(adaptive_weights_app, name="adaptive-weights")
app.add_typer(autonomous_app, name="autonomous")
app.add_typer(forward_app, name="forward")
app.add_typer(performance_app, name="performance")
app.add_typer(outcomes_app, name="outcomes")
app.add_typer(learning_app, name="learning")
app.add_typer(decision_app, name="decision")
app.add_typer(tradeplan_app, name="tradeplan")
app.add_typer(strategy_regime_app, name="strategy-regime")
app.add_typer(strategy_app, name="strategy")
app.add_typer(strategy_lab_app, name="strategy-lab")
app.add_typer(market_dna_app, name="market-dna")
app.add_typer(market_opportunity_app, name="market-opportunity")
app.add_typer(data_app, name="data")
app.add_typer(data_value_app, name="data-value")
app.add_typer(market_truth_app, name="market-truth")
app.add_typer(pine_app, name="pine")
app.add_typer(trl_app, name="trl")
app.add_typer(warehouse_app, name="warehouse")
app.add_typer(warehouse_delta_app, name="warehouse-delta")
app.add_typer(replay_app, name="replay")
app.add_typer(evidence_app, name="evidence")
app.add_typer(simulate_app, name="simulate")
app.add_typer(trades_app, name="trades")
app.add_typer(playbook_app, name="playbook")
app.add_typer(market_state_app, name="market-state")
app.add_typer(provenance_app, name="provenance")
app.add_typer(provider_app, name="provider")
provenance_app.add_typer(provenance_manifest_app, name="manifest")
provider_app.add_typer(upstox_app, name="upstox")


@app.command()
def version() -> None:
    print(__version__)


@app.command()
def doctor() -> None:
    """
    Print Project Alpha release and quality gate metadata.
    """

    release = current_release()
    print("\n".join(release.as_lines()))


@upstox_app.command(name="status")
def provider_upstox_status(
    symbol: str | None = typer.Option(None, "--symbol"),
    validate_remote: bool = typer.Option(False, "--validate-remote"),
    authorize_feed: bool = typer.Option(False, "--authorize-feed"),
) -> None:
    """
    Report Upstox auth, token, V3 feed, and instrument readiness.
    """

    report = UpstoxProviderPreflight().status(
        symbol=symbol,
        validate_remote=validate_remote,
        authorize_feed=authorize_feed,
    )
    print()
    for line in render_upstox_status(report):
        print(line)


@upstox_app.command(name="readiness-audit")
def provider_upstox_readiness_audit(
    fixture: str = typer.Option(
        RECORDED_UPSTOX_FIXTURE_NAME,
        "--fixture",
        help="Recorded diagnostic fixture name.",
    ),
    account_segment_state: str = typer.Option(
        "NO_ACTIVE_TRADING_SEGMENTS",
        "--account-segment-state",
        help="Known account segment state for diagnostic classification.",
    ),
    output_format: str = typer.Option(
        "text",
        "--format",
        help="Output format: text or json.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Optional JSON output path.",
    ),
) -> None:
    """
    Run provider-independent Upstox downstream readiness diagnostics.
    """

    report = RecordedUpstoxReadinessAuditEngine().run(
        fixture_name=fixture,
        account_segment_state=account_segment_state,
    )
    if output is not None:
        export_upstox_readiness_audit_json(report, output)
    normalized_format = output_format.strip().lower()
    if normalized_format == "json":
        import json

        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
        return
    if normalized_format != "text":
        raise typer.BadParameter("--format must be text or json")
    print()
    for line in render_upstox_readiness_audit(report):
        print(line)
    if output is not None:
        print(f"JSON Export: {output}")


@upstox_app.command(name="live-acceptance")
def provider_upstox_live_acceptance(
    instrument_key: str = typer.Option(
        ...,
        "--instrument-key",
        help="Exact registry-resolved Upstox cash-equity instrument key.",
    ),
    max_events: int = typer.Option(
        25,
        "--max-events",
        min=1,
        max=500,
        help="Finite maximum number of live events to accept.",
    ),
    timeout_seconds: int = typer.Option(
        60,
        "--timeout-seconds",
        min=1,
        max=600,
        help="Finite live acceptance timeout.",
    ),
    output_format: str = typer.Option(
        "text",
        "--format",
        help="Output format: text or json.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Optional JSON evidence output path.",
    ),
) -> None:
    """
    Run a bounded diagnostic-only Upstox Feed V3 live acceptance test.
    """

    report = UpstoxLiveAcceptanceHarness().run(
        instrument_key=instrument_key,
        max_events=max_events,
        timeout_seconds=timeout_seconds,
    )
    if output is not None:
        export_upstox_live_acceptance_json(report, output)
    normalized_format = output_format.strip().lower()
    if normalized_format == "json":
        import json

        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
        return
    if normalized_format != "text":
        raise typer.BadParameter("--format must be text or json")
    print()
    for line in render_upstox_live_acceptance(report):
        print(line)
    if output is not None:
        print(f"JSON Export: {output}")


@upstox_app.command(name="protocol-audit")
def provider_upstox_protocol_audit(
    output_format: str = typer.Option(
        "text",
        "--format",
        help="Output format: text or json.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Optional JSON protocol audit output path.",
    ),
) -> None:
    """
    Report Upstox Feed V3 protocol adapter conformance readiness.
    """

    report = build_protocol_audit_report()
    if output is not None:
        export_protocol_audit_json(report, output)
    normalized_format = output_format.strip().lower()
    if normalized_format == "json":
        import json

        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
        return
    if normalized_format != "text":
        raise typer.BadParameter("--format must be text or json")
    print()
    for line in render_protocol_audit(report):
        print(line)
    if output is not None:
        print(f"JSON Export: {output}")


@upstox_app.command(name="login-url")
def provider_upstox_login_url(
    state: str | None = typer.Option(None, "--state"),
) -> None:
    """
    Print the Upstox authorization URL without exposing secrets.
    """

    try:
        print(UpstoxAuthService().authorization_url(state=state))
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


@upstox_app.command(name="exchange-code")
def provider_upstox_exchange_code(
    code: str | None = typer.Option(
        None,
        "--code",
        help="Authorization code. Warning: shell history may retain this value.",
    ),
) -> None:
    """
    Exchange a one-use Upstox authorization code and store safe token metadata.
    """

    authorization_code = code or prompt_authorization_code()
    try:
        metadata = UpstoxAuthService().exchange_code(authorization_code)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    print("Upstox token metadata stored.")
    print(f"Token Fingerprint: {metadata.token_fingerprint}")
    print(f"Expected Expiry: {metadata.expected_expiry.isoformat()}")
    print("Raw token value was not written to Alpha metadata.")


@upstox_app.command(name="validate-token")
def provider_upstox_validate_token(
    remote: bool = typer.Option(True, "--remote/--local-only"),
) -> None:
    """
    Validate the configured Upstox access token.
    """

    validation = UpstoxAuthService().validate_token(remote=remote)
    print("Upstox Token Validation")
    print(f"Status: {validation.status.value}")
    print(f"Token Configured: {validation.token_configured}")
    print(f"Expected Expiry: {validation.expected_expiry or 'unavailable'}")
    print(f"Last Validation: {validation.last_validation_at or 'unavailable'}")
    print(f"Token Fingerprint: {validation.token_fingerprint or 'unavailable'}")
    print(f"Reason: {validation.reason}")


@upstox_app.command(name="logout")
def provider_upstox_logout() -> None:
    """
    Clear local safe Upstox token metadata.
    """

    removed = UpstoxAuthService().clear_metadata()
    print("Upstox local token metadata cleared." if removed else "No metadata found.")


@app.command()
def live(
    symbols: list[str] | None = typer.Option(
        None,
        "--symbols",
        help="Comma-separated NSE symbols to monitor.",
    ),
    symbol: list[str] | None = typer.Option(
        None,
        "--symbol",
        help="Repeatable NSE symbol to monitor.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Print live feed diagnostics and latency details.",
    ),
    shadow_diagnostics: bool = typer.Option(
        False,
        "--shadow-diagnostics",
        help="Print live regime-shadow wiring diagnostics when capture is enabled.",
    ),
) -> None:
    """
    Monitor live market data without fabricating fallback prices.
    """

    provider = UpstoxLiveMarketDataProvider.from_environment()
    parsed_symbols = _parse_live_symbols(symbols=symbols, repeated_symbols=symbol)
    subscriptions = tuple(
        InstrumentSubscription(symbol=symbol, instrument_key=f"NSE_EQ|{symbol}")
        for symbol in parsed_symbols
    )
    if not provider.configured():
        print("Live feed unavailable.")
        print("Reason: Upstox credentials are not configured.")
        print("Required env vars: UPSTOX_ACCESS_TOKEN")
        print("No live recommendations generated.")
        return
    print("Live Market Monitor")
    print(f"Provider: Upstox ({provider.websocket_url})")
    print("Subscriptions:")
    for subscription in subscriptions:
        print(f"- {subscription.symbol}: {subscription.instrument_key}")
    snapshots = asyncio.run(
        run_live_monitor(
            provider=provider,
            subscriptions=subscriptions,
            max_ticks=1,
        )
    )
    for snapshot in snapshots:
        _print_live_snapshot(snapshot, verbose=verbose)
        if _live_shadow_capture_requested():
            report = AlphaLiveShadowRuntimeService().process_snapshot(
                snapshot,
                provider_name=provider.__class__.__name__,
                persist_shadow=True,
            )
            if shadow_diagnostics or verbose:
                print()
                for line in render_alpha_live_wiring(report):
                    print(line)


@app.command(name="live-shadow-smoke-test")
def live_shadow_smoke_test(
    symbol: str = typer.Option(..., "--symbol"),
    persist_diagnostic: bool = typer.Option(False, "--persist-diagnostic"),
    shadow_dry_run: bool = typer.Option(True, "--shadow-dry-run/--no-shadow-dry-run"),
) -> None:
    """
    Run a non-executable diagnostic smoke test for live regime shadow capture.
    """

    repository = NightlyLearningLoop.from_path().repository
    candidate = next(
        (
            record
            for record in reversed(repository.load_records())
            if record.symbol == symbol.strip().upper()
        ),
        None,
    )
    if candidate is None:
        print("Live Regime Shadow Capture Smoke Test")
        print(f"Status: provider/candidate unavailable for {symbol.strip().upper()}")
        print("Executable: false")
        print("Capital Effect: none")
        print("No live observation persisted.")
        return
    config = LiveRegimeShadowCaptureConfig.from_environment(dry_run=shadow_dry_run)
    service = LiveRegimeShadowCaptureService(
        learning_repository=repository,
        config=config,
    )
    frozen = frozen_input_from_candidate(
        candidate=candidate,
        runtime_path="live-shadow-smoke-test",
        source_mode=LiveShadowSourceMode.PAPER_RUNTIME,
        smoke_test=True,
    )
    result = service.capture(frozen, persist=persist_diagnostic)
    print()
    for line in render_live_regime_shadow_capture_result(result):
        print(line)


def _parse_live_symbols(
    *,
    symbols: list[str] | None,
    repeated_symbols: list[str] | None,
) -> tuple[str, ...]:
    raw_values: list[str] = []
    for value in symbols or []:
        raw_values.extend(value.split(","))
    raw_values.extend(repeated_symbols or [])
    parsed = tuple(
        dict.fromkeys(value.strip().upper() for value in raw_values if value.strip())
    )
    if not parsed:
        raise typer.BadParameter(
            "Provide at least one symbol via --symbols A,B or repeated --symbol A."
        )
    return parsed


def _live_shadow_capture_requested() -> bool:
    return os.environ.get("ALPHA_REGIME_SHADOW_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _print_live_snapshot(snapshot: object, *, verbose: bool) -> None:
    health = getattr(snapshot, "feed_health", None)
    latency = getattr(snapshot, "latency", None)
    warnings = tuple(getattr(snapshot, "warnings", ()))
    tick_quality = getattr(snapshot, "tick_quality", None)
    feed_status = (
        health.status.value if health is not None else getattr(snapshot, "feed_status")
    )
    feed_quality = (
        f"{health.feed_quality_score}/100" if health is not None else "unavailable"
    )
    latency_text = (
        str(latency.rolling_average_seconds)
        if latency is not None and latency.rolling_average_seconds is not None
        else "unavailable"
    )

    print("\nProvider")
    print(f"Status: {feed_status}")
    print(f"Latency: {latency_text}")
    print(f"Feed Quality: {feed_quality}")
    print("Active Symbols: 1")
    print(f"Last Tick: {getattr(snapshot, 'bar_started_at').isoformat()}")
    print(
        "Warnings: "
        + (", ".join(warning.warning_type.value for warning in warnings) or "none")
    )

    print(f"\n{getattr(snapshot, 'symbol')}")
    print(f"Price: ₹{getattr(snapshot, 'price')}")
    print("Change: unavailable")
    print(f"Volume: {getattr(snapshot, 'volume')}")
    print(f"VWAP: {getattr(snapshot, 'vwap') or 'unavailable'}")
    print(f"Current Bar: {getattr(snapshot, 'bar_started_at').isoformat()}")
    print(f"Feed Age: {'stale' if getattr(snapshot, 'stale') else 'fresh'}")
    print(f"Tick Count: {getattr(snapshot, 'tick_count', 0)}")
    print(f"Recommendation: {getattr(snapshot, 'action_now')}")
    print(
        "Risk Flags: " + (", ".join(warning.message for warning in warnings) or "none")
    )

    if not verbose:
        return

    print("\nTick Diagnostics")
    if tick_quality is None:
        print("Status: unavailable")
    else:
        print(f"Status: {tick_quality.status.value}")
        print(f"Reasons: {', '.join(tick_quality.reasons) or 'none'}")

    print("\nLatency Breakdown")
    if latency is None or latency.sample_count == 0:
        print("Latency samples: unavailable")
    else:
        print(f"Samples: {latency.sample_count}")
        print(f"Rolling Average: {latency.rolling_average_seconds}")
        print(f"Rolling Max: {latency.rolling_max_seconds}")
        print(f"Rolling P95: {latency.rolling_p95_seconds}")
        print(f"Rolling P99: {latency.rolling_p99_seconds}")

    print("\nRejected Ticks")
    print("Invalid ticks are rejected before bar building.")

    print("\nSession State")
    if health is None:
        print("Health: unavailable")
    else:
        print(f"Health: {health.status.value}")
        print(f"Heartbeat Age: {health.heartbeat_age_seconds or 'unavailable'}")
        print(f"Reconnect Attempts: {health.reconnect_attempts}")

    print("\nHealth History")
    if health is None or not health.reasons:
        print("No health warnings.")
    else:
        for reason in health.reasons:
            print(f"- {reason}")


@app.command()
def download(date: str = "today") -> None:
    """
    Download NSE bhavcopy.
    """

    service = HistoricalIngestionService()
    try:
        count = service.download_only(date)
    except BhavcopyNotFoundError as exc:
        _exit_with_error("Data download failed", exc)
    except ProjectAlphaError as exc:
        _exit_with_error("Project Alpha command failed", exc)

    print(f"Downloaded records: {count}")


@app.command(name="backfill-archive")
def backfill_archive(
    from_date: str = typer.Option(..., "--from-date", help="Start date YYYY-MM-DD."),
    to_date: str = typer.Option(..., "--to-date", help="End date YYYY-MM-DD."),
) -> None:
    """
    Backfill historical NSE archive bhavcopies through the archive-only path.
    """

    service = HistoricalIngestionService()
    result = service.backfill_legacy_archive(
        start=_parse_date(from_date),
        end=_parse_date(to_date),
    )
    print()
    print("Historical Archive Backfill")
    print(f"Requested Window: {result.requested_start} to {result.requested_end}")
    print(f"Attempted Trading Days: {result.attempted_days}")
    print(f"Processed Archives: {result.processed_archives}")
    print(f"Skipped Non-Trading Days: {result.skipped_non_trading_days}")
    print(f"Failed Dates: {len(result.failed_dates)}")
    if result.failed_dates:
        print("Recent Failures:")
        for failure in result.failed_dates[:10]:
            print(f"- {failure}")


@app.command()
def report(date: str = "today") -> None:
    """
    Generate daily report.
    """

    service = HistoricalIngestionService()
    try:
        report_data = service.generate_report(date)
    except BhavcopyNotFoundError as exc:
        _exit_with_error("Report generation failed", exc)
    except ProjectAlphaError as exc:
        _exit_with_error("Project Alpha command failed", exc)

    print("\n📊 NSE DAILY REPORT\n")
    print(f"Observed On: {report_data['observed_on']}")

    print("\n🔥 Top Gainers:")
    print(
        report_data["top_gainers"]
        .loc[:, ["symbol", "momentum_score"]]
        .to_string(index=False)
    )

    print("\n📉 Top Losers:")
    print(
        report_data["top_losers"]
        .loc[:, ["symbol", "momentum_score"]]
        .to_string(index=False)
    )

    print("\n📈 Market Regime:", report_data["regime"])


@app.command(name="run")
def run_daily(
    date: str = "today",
    demo: bool = typer.Option(
        False,
        "--demo",
        help="Use deterministic demo inputs instead of live analysis.",
    ),
    export_json: Path | None = typer.Option(
        None,
        "--export-json",
        help="Write deterministic daily intelligence JSON to this path.",
    ),
    export_text: Path | None = typer.Option(
        None,
        "--export-text",
        help="Write deterministic daily intelligence text to this path.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Render full strategy, evidence, and portfolio details.",
    ),
) -> None:
    """
    Run the daily Project Alpha investment workflow.
    """

    _validate_command_export_paths(export_json=export_json, export_text=export_text)

    try:
        runtime_result = _run_daily_runtime(date=date, demo=demo)
    except BhavcopyNotFoundError as exc:
        _exit_with_error("Daily run failed", exc)
    except ProjectAlphaError as exc:
        _exit_with_error("Project Alpha command failed", exc)

    _print_daily_runtime_result(runtime_result, verbose=verbose)
    provenance = _persist_decision_provenance(
        runtime_result,
        runtime_command="run",
    )
    market_state_result = _persist_market_state_snapshot(
        runtime_result,
        provenance=provenance,
    )
    print()
    for line in render_market_state_persistence_result(market_state_result):
        print(line)
    tracking_lines = _record_recommendation_performance(runtime_result)
    print()
    for line in tracking_lines:
        print(line)
    _record_forward_validation(runtime_result)
    learning_lines = _record_candidate_learning(
        runtime_result,
        market_state_result=market_state_result,
    )
    print()
    for line in learning_lines:
        print(line)
    print()
    for line in _historical_evidence_lines():
        print(line)
    _print_live_trade_checkin()
    _export_intelligence_run(
        run=runtime_result.intelligence_run,
        export_json=export_json,
        export_text=export_text,
    )


@app.command()
def intelligence(
    date: str = "today",
    demo: bool = typer.Option(
        False,
        "--demo",
        help="Use deterministic demo intelligence inputs instead of live analysis.",
    ),
    export_json: Path | None = typer.Option(
        None,
        "--export-json",
        help="Write deterministic recommendation intelligence JSON to this path.",
    ),
    export_text: Path | None = typer.Option(
        None,
        "--export-text",
        help="Write deterministic recommendation intelligence text to this path.",
    ),
) -> None:
    """
    Run the intelligence orchestration report.
    """

    _validate_command_export_paths(export_json=export_json, export_text=export_text)

    try:
        runtime_result = _run_intelligence_runtime(date=date, demo=demo)
    except BhavcopyNotFoundError as exc:
        _exit_with_error("Intelligence generation failed", exc)
    except ProjectAlphaError as exc:
        _exit_with_error("Project Alpha command failed", exc)

    print()
    for line in runtime_result.summary_lines:
        print(line)

    provenance = _persist_decision_provenance(
        runtime_result,
        runtime_command="intelligence",
    )
    market_state_result = _persist_market_state_snapshot(
        runtime_result,
        provenance=provenance,
    )
    print()
    for line in render_market_state_persistence_result(market_state_result):
        print(line)

    tracking_lines = _record_recommendation_performance(runtime_result)
    print()
    for line in tracking_lines:
        print(line)
    _record_forward_validation(runtime_result)
    learning_lines = _record_candidate_learning(
        runtime_result,
        market_state_result=market_state_result,
    )
    print()
    for line in learning_lines:
        print(line)
    print()
    for line in _historical_evidence_lines():
        print(line)
    _print_live_trade_checkin()
    _export_intelligence_run(
        run=runtime_result.intelligence_run,
        export_json=export_json,
        export_text=export_text,
    )


@performance_app.command(name="update")
def performance_update(
    ledger: Path | None = typer.Option(
        None,
        "--ledger",
        help="Recommendation ledger path.",
    ),
) -> None:
    """
    Update recommendation outcomes from available later bars.
    """

    service = PerformanceIntelligenceService.from_path(ledger)
    summary = service.update()
    print()
    for line in render_update_summary(summary):
        print(line)


@performance_app.command(name="report")
def performance_report(
    ledger: Path | None = typer.Option(
        None,
        "--ledger",
        help="Recommendation ledger path.",
    ),
    period: str = typer.Option(
        "lifetime",
        "--period",
        help="Summary period: daily, weekly, monthly, yearly, lifetime.",
    ),
) -> None:
    """
    Print recommendation performance statistics from the ledger.
    """

    service = PerformanceIntelligenceService.from_path(ledger)
    print()
    for line in service.report_lines(period=period):
        print(line)


@outcomes_app.command(name="update")
def outcomes_update(
    ledger: Path | None = typer.Option(
        None,
        "--ledger",
        help="Recommendation ledger path.",
    ),
) -> None:
    """
    Update recommendation outcomes from available later bars.
    """

    performance_update(ledger=ledger)


@outcomes_app.command(name="summary")
def outcomes_summary(
    ledger: Path | None = typer.Option(
        None,
        "--ledger",
        help="Recommendation ledger path.",
    ),
    period: str = typer.Option(
        "lifetime",
        "--period",
        help="Summary period: daily, weekly, monthly, yearly, lifetime.",
    ),
) -> None:
    """
    Print recommendation outcome performance summary.
    """

    service = PerformanceIntelligenceService.from_path(ledger)
    print()
    for line in service.report_lines(period=period):
        print(line)


@outcomes_app.command(name="open")
def outcomes_open(
    ledger: Path | None = typer.Option(
        None,
        "--ledger",
        help="Recommendation ledger path.",
    ),
) -> None:
    """
    Show open recommendation ledger rows.
    """

    service = PerformanceIntelligenceService.from_path(ledger)
    print()
    for line in service.open_lines():
        print(line)


@outcomes_app.command(name="symbol")
def outcomes_symbol(
    symbol: str = typer.Option(..., "--symbol", help="NSE symbol to inspect."),
    ledger: Path | None = typer.Option(
        None,
        "--ledger",
        help="Recommendation ledger path.",
    ),
) -> None:
    """
    Show symbol-level recommendation outcome history.
    """

    service = PerformanceIntelligenceService.from_path(ledger)
    print()
    for line in service.symbol_lines(symbol=symbol):
        print(line)


@learning_app.command(name="report")
def learning_report(
    ledger: Path | None = typer.Option(
        None,
        "--ledger",
        help="Recommendation ledger path.",
    ),
    forward_registry: Path | None = typer.Option(None, "--forward-registry"),
    learning_registry: Path | None = typer.Option(None, "--learning-registry"),
) -> None:
    """
    Print adaptive learning calibration from completed outcomes.
    """

    print()
    for line in continuous_learning_report_lines(
        ledger=ledger,
        forward_registry=forward_registry,
        learning_registry=learning_registry,
    ):
        print(line)
    print()
    print("Historical Adaptive Evidence")
    for line in AdaptiveLearningService.from_path(ledger).report_lines():
        print(line)


@learning_app.command(name="explain")
def learning_explain(
    symbol: str = typer.Option(..., "--symbol", help="NSE symbol to explain."),
    ledger: Path | None = typer.Option(
        None,
        "--ledger",
        help="Recommendation ledger path.",
    ),
) -> None:
    """
    Explain adaptive evidence for one recommendation symbol.
    """

    service = AdaptiveLearningService.from_path(ledger)
    print()
    for line in service.explain_lines(symbol=symbol):
        print(line)


@learning_app.command(name="nightly")
def learning_nightly(
    from_date: str | None = typer.Option(None, "--from-date"),
    to_date: str | None = typer.Option(None, "--to-date"),
    refresh_backtests: bool = typer.Option(False, "--refresh-backtests"),
    skip_download: bool = typer.Option(False, "--skip-download"),
    min_sample_size: int = typer.Option(30, "--min-sample-size"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """
    Run the nightly candidate learning loop.
    """

    del skip_download, verbose
    start = _parse_date(from_date) if from_date is not None else None
    end = _parse_date(to_date) if to_date is not None else None
    lines = NightlyLearningLoop.from_path().nightly(
        from_date=start,
        to_date=end,
        refresh_backtests=refresh_backtests,
        min_sample_size=min_sample_size,
    )
    print()
    for line in lines:
        print(line)


@learning_app.command(name="summary")
def learning_summary(
    period: str = typer.Option(
        "lifetime",
        "--period",
        help="daily|weekly|monthly|yearly|lifetime.",
    ),
    regime: str = typer.Option("ALL", "--regime"),
    top: int = typer.Option(10, "--top"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """
    Print candidate outcome learning summary.
    """

    del regime, top, verbose
    print()
    for line in NightlyLearningLoop.from_path().summary_lines(period=period):
        print(line)


@learning_app.command(name="raw-summary")
def learning_raw_summary(
    period: str = typer.Option("lifetime", "--period"),
    stage: str = typer.Option("ALL", "--stage"),
    top: int = typer.Option(10, "--top"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """
    Print raw universe filter-quality learning summary.
    """

    del top, verbose
    summary = NightlyLearningLoop.from_path().raw_summary(
        period=period,
        stage=stage,
    )
    print()
    for line in render_raw_universe_summary(summary):
        print(line)


@learning_app.command(name="combinations")
def learning_combinations(
    period: str = typer.Option("lifetime", "--period"),
    min_sample_size: int = typer.Option(30, "--min-sample-size"),
    max_combination_size: int = typer.Option(4, "--max-combination-size"),
    min_indicator_count: int = typer.Option(
        1,
        "--min-indicator-count",
        help="Minimum indicators in a tested set. Use 1 for baseline edge.",
    ),
    source: str = typer.Option(
        "historical",
        "--source",
        help="historical/raw replay evidence or live recommendation outcomes.",
    ),
    refresh_replay: bool = typer.Option(
        False,
        "--refresh-replay",
        help="Build historical replay observations before ranking combinations.",
    ),
    from_date: str | None = typer.Option(None, "--from-date"),
    to_date: str | None = typer.Option(None, "--to-date"),
) -> None:
    """
    Rank indicator combinations by realized forward outcomes and market regime.
    """

    if refresh_replay:
        if from_date is None or to_date is None:
            raise typer.BadParameter(
                "--refresh-replay requires --from-date and --to-date."
            )
        start = _parse_date(from_date)
        end = _parse_date(to_date)
        learning_repository = NightlyLearningLoop.from_path().repository
        build = HistoricalObservationFactory(
            price_repository=MarketTruthPriceRepository()
        ).build(from_date=start, to_date=end)
        HistoricalReplayEngine(
            replay_repository=HistoricalReplayRepository(),
            learning_repository=learning_repository,
        ).run(from_date=start, to_date=end, observations=build.observations)
        print()
        print(f"Historical Replay Refreshed: {len(build.observations)} observations")
        if build.skipped_dates:
            print(f"Skipped Dates: {len(build.skipped_dates)}")

    print()
    for line in NightlyLearningLoop.from_path().indicator_combination_lines(
        period=period,
        minimum_sample_size=min_sample_size,
        max_combination_size=max_combination_size,
        min_combination_size=min_indicator_count,
        source=source,
    ):
        print(line)


@replay_app.command(name="run")
def replay_run(
    from_date: str = typer.Option(..., "--from-date"),
    to_date: str = typer.Option(..., "--to-date"),
) -> None:
    """
    Run historical replay from locally persisted price history.
    """

    start = _parse_date(from_date)
    end = _parse_date(to_date)
    learning_repository = NightlyLearningLoop.from_path().repository
    build = HistoricalObservationFactory(
        price_repository=MarketTruthPriceRepository()
    ).build(from_date=start, to_date=end)
    engine = HistoricalReplayEngine(
        replay_repository=HistoricalReplayRepository(),
        learning_repository=learning_repository,
    )
    runs = engine.run(
        from_date=start,
        to_date=end,
        observations=build.observations,
    )
    print()
    for line in render_replay_run(runs):
        print(line)
    if build.skipped_dates:
        print("Skipped Replay Dates:")
        for item in build.skipped_dates[:10]:
            print(f"- {item}")


@replay_app.command(name="sample-plan")
def replay_sample_plan(
    from_date: str = typer.Option(..., "--from-date"),
    to_date: str = typer.Option(..., "--to-date"),
    frequency: str = typer.Option("monthly", "--frequency"),
    max_dates: int | None = typer.Option(None, "--max-dates"),
) -> None:
    """
    Preview evenly sampled replay dates from persisted market history.
    """

    plan = _replay_sample_plan(
        from_date=from_date,
        to_date=to_date,
        frequency=frequency,
        max_dates=max_dates,
    )
    print()
    for line in render_replay_sample_plan(plan):
        print(line)


@replay_app.command(name="accumulate")
def replay_accumulate(
    from_date: str = typer.Option(..., "--from-date"),
    to_date: str = typer.Option(..., "--to-date"),
    frequency: str = typer.Option("monthly", "--frequency"),
    max_dates: int | None = typer.Option(None, "--max-dates"),
) -> None:
    """
    Build replay outcomes from evenly sampled dates, sequentially with progress.
    """

    plan = _replay_sample_plan(
        from_date=from_date,
        to_date=to_date,
        frequency=frequency,
        max_dates=max_dates,
    )
    print()
    for line in render_replay_sample_plan(plan):
        print(line)
    if not plan.selected_dates:
        return

    price_repository = MarketTruthPriceRepository()
    learning_repository = NightlyLearningLoop.from_path().repository
    replay_repository = HistoricalReplayRepository()
    factory = HistoricalObservationFactory(price_repository=price_repository)
    engine = HistoricalReplayEngine(
        replay_repository=replay_repository,
        learning_repository=learning_repository,
    )
    processed = 0
    skipped: list[str] = []
    total_raw = 0
    total_emitted = 0
    total_approved = 0
    total_gaps = 0
    print()
    print("Replay Accumulation Progress")
    for replay_date in plan.selected_dates:
        build = factory.build(from_date=replay_date, to_date=replay_date)
        if build.skipped_dates:
            skipped.extend(build.skipped_dates)
            print(f"- {replay_date}: skipped ({build.skipped_dates[0]})")
            continue
        runs = engine.run(
            from_date=replay_date,
            to_date=replay_date,
            observations=build.observations,
        )
        if not runs:
            print(f"- {replay_date}: no observations")
            continue
        run = runs[0]
        processed += 1
        total_raw += run.candidates_stored
        total_emitted += run.emitted_decisions
        total_approved += run.approved_recommendations
        total_gaps += run.data_gaps
        print(
            "- "
            f"{replay_date}: raw {run.candidates_stored}, "
            f"emitted {run.emitted_decisions}, "
            f"approved {run.approved_recommendations}, "
            f"gaps {run.data_gaps}"
        )

    print()
    print("Replay Accumulation Summary")
    print(f"Replay Dates Processed: {processed}")
    print(f"Replay Dates Skipped: {len(skipped)}")
    print(f"Raw Candidates Stored: {total_raw}")
    print(f"Emitted Decisions Stored: {total_emitted}")
    print(f"Approved Recommendations Stored: {total_approved}")
    print(f"Data Gaps: {total_gaps}")
    if skipped:
        print("Skipped Dates:")
        for item in skipped[:10]:
            print(f"- {item}")


@replay_app.command(name="summary")
def replay_summary() -> None:
    """
    Print historical replay ledger summary.
    """

    print()
    for line in render_replay_summary(HistoricalReplayRepository().summary()):
        print(line)


@replay_app.command(name="approval-diagnostics")
def replay_approval_diagnostics(
    nearest: int = typer.Option(10, "--nearest"),
    group_by: str | None = typer.Option(None, "--group-by"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Explain why replay candidates did or did not satisfy institutional approval.
    """

    summary = _approval_diagnostic_summary(nearest=nearest)
    diagnostics = summary.diagnostics
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_approval_diagnostics_json(diagnostics, output)
        print(f"Approval diagnostics written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_approval_diagnostics_csv(diagnostics, output)
        print(f"Approval diagnostics written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in render_approval_diagnostics(summary):
        print(line)
    if group_by is not None:
        print()
        print(f"Grouped By {group_by}:")
        for line in group_diagnostics(diagnostics, group_by=group_by):
            print(line)


@replay_app.command(name="approval-failures")
def replay_approval_failures(
    criterion: str | None = typer.Option(None, "--criterion"),
    reason: str | None = typer.Option(None, "--reason"),
    readiness: str | None = typer.Option(None, "--readiness"),
    symbol: str | None = typer.Option(None, "--symbol"),
    from_date: str | None = typer.Option(None, "--from-date"),
    to_date: str | None = typer.Option(None, "--to-date"),
    single_failure_only: bool = typer.Option(False, "--single-failure-only"),
    near_approval_only: bool = typer.Option(False, "--near-approval-only"),
    data_gaps_only: bool = typer.Option(False, "--data-gaps-only"),
    incomplete_plan_only: bool = typer.Option(False, "--incomplete-plan-only"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Show candidate-level institutional rejection details.
    """

    diagnostics = filter_diagnostics(
        _approval_diagnostic_summary().diagnostics,
        criterion=criterion,
        reason=reason,
        readiness=readiness,
        symbol=symbol,
        from_date=_parse_date(from_date) if from_date else None,
        to_date=_parse_date(to_date) if to_date else None,
        single_failure_only=single_failure_only,
        near_approval_only=near_approval_only,
        data_gaps_only=data_gaps_only,
        incomplete_plan_only=incomplete_plan_only,
    )
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_approval_diagnostics_json(diagnostics, output)
        print(f"Approval failures written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_approval_diagnostics_csv(diagnostics, output)
        print(f"Approval failures written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in render_approval_failures(diagnostics):
        print(line)


@replay_app.command(name="approval-outcomes")
def replay_approval_outcomes(
    group_by: str | None = typer.Option(None, "--group-by"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Analyze whether rejected replay candidates later performed well or poorly.
    """

    report = _approval_outcome_report()
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_approval_outcomes_json(report, output)
        print(f"Approval outcome analysis written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_approval_outcomes_csv(report, output)
        print(f"Approval outcome analysis written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in render_approval_outcomes(report):
        print(line)
    if group_by is not None:
        print()
        print(f"Grouped By {group_by}:")
        for line in group_approval_outcomes(report, group_by=group_by):
            print(line)


@replay_app.command(name="profitable-rejections")
def replay_profitable_rejections(
    criterion: str | None = typer.Option(None, "--criterion"),
    reason: str | None = typer.Option(None, "--reason"),
    setup_type: str | None = typer.Option(None, "--setup-type"),
    market_regime: str | None = typer.Option(None, "--market-regime"),
    entry_state: str | None = typer.Option(None, "--entry-state"),
    symbol: str | None = typer.Option(None, "--symbol"),
    from_date: str | None = typer.Option(None, "--from-date"),
    to_date: str | None = typer.Option(None, "--to-date"),
    target_1_hit: bool | None = typer.Option(None, "--target-1-hit"),
    target_2_hit: bool | None = typer.Option(None, "--target-2-hit"),
    minimum_return: str | None = typer.Option(None, "--minimum-return"),
    minimum_mfe: str | None = typer.Option(None, "--minimum-mfe"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Show rejected candidates that subsequently produced profitable outcomes.
    """

    report = _approval_outcome_report()
    candidates = filter_profitable_rejections(
        report.profitable_rejections,
        criterion=criterion,
        reason=reason,
        setup_type=setup_type,
        market_regime=market_regime,
        entry_state=entry_state,
        symbol=symbol,
        from_date=_parse_date(from_date) if from_date else None,
        to_date=_parse_date(to_date) if to_date else None,
        target_1_hit=target_1_hit,
        target_2_hit=target_2_hit,
        minimum_return=_parse_decimal(minimum_return)
        if minimum_return is not None
        else None,
        minimum_mfe=_parse_decimal(minimum_mfe) if minimum_mfe is not None else None,
    )
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_profitable_rejections_json(candidates, output)
        print(f"Profitable rejections written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_profitable_rejections_csv(candidates, output)
        print(f"Profitable rejections written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in render_profitable_rejections(candidates):
        print(line)


@replay_app.command(name="entry-opportunities")
def replay_entry_opportunities(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Report rejected candidates that later produced independent valid entries.
    """

    opportunities = _approval_outcome_report().delayed_entry_opportunities
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_entry_opportunities_json(opportunities, output)
        print(f"Entry opportunities written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_entry_opportunities_csv(opportunities, output)
        print(f"Entry opportunities written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in render_entry_opportunities(opportunities):
        print(line)


@replay_app.command(name="entry-timing")
def replay_entry_timing(
    group_by: str | None = typer.Option(None, "--group-by"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Analyze replay outcomes by deterministic entry-timing state.
    """

    report = _entry_timing_report()
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_entry_timing_json(report, output)
        print(f"Entry timing analysis written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_entry_timing_csv(report, output)
        print(f"Entry timing analysis written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in render_entry_timing_report(report):
        print(line)
    if group_by is not None:
        print()
        print(f"Grouped By {group_by}:")
        for line in group_entry_timing_report(report, group_by=group_by):
            print(line)


@replay_app.command(name="entry-timing-audit")
def replay_entry_timing_audit(
    group_by: str | None = typer.Option(None, "--group-by"),
    profitable_rejections: bool = typer.Option(False, "--profitable-rejections"),
    winner_loser: bool = typer.Option(False, "--winner-loser"),
    incremental_value: bool = typer.Option(False, "--incremental-value"),
    boundaries: bool = typer.Option(False, "--boundaries"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Validate entry-timing outcomes and attribute rejected winners to gates.
    """

    report = _entry_timing_validation_report()
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_entry_timing_validation_json(report, output)
        print(f"Entry timing validation audit written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_entry_timing_validation_csv(report, output)
        print(f"Entry timing validation audit written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in render_entry_timing_validation_report(report):
        print(line)
    groups = []
    if group_by is not None:
        groups.append(group_by)
    if profitable_rejections:
        groups.append("profitable-rejections")
    if winner_loser:
        groups.append("winner-loser")
    if incremental_value:
        groups.append("incremental-value")
    if boundaries:
        groups.append("boundaries")
    for grouping in dict.fromkeys(groups):
        print()
        print(f"Grouped By {grouping}:")
        for line in group_entry_timing_validation_report(report, group_by=grouping):
            print(line)


@replay_app.command(name="approval-baseline-audit")
def replay_approval_baseline_audit(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Reconcile approval counts from strict gates and raw replay flags.
    """

    comparison = _approval_baseline_comparison()
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_approval_baseline_json(comparison, output)
        print(f"Approval baseline audit written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_approval_baseline_csv(comparison, output)
        print(f"Approval baseline audit written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in render_approval_baseline_audit(comparison):
        print(line)


@replay_app.command(name="gate-attribution")
def replay_gate_attribution(
    group_by: str | None = typer.Option(None, "--group-by"),
    primary_entry_states_only: bool = typer.Option(
        False,
        "--primary-entry-states-only",
    ),
    candidate_export: bool = typer.Option(False, "--candidate-export"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Attribute non-entry institutional gates against completed replay outcomes.
    """

    report = _gate_attribution_report()
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        if candidate_export:
            export_gate_candidate_audit_json(report.candidate_rows, output)
        else:
            export_gate_attribution_json(report, output)
        print(f"Gate attribution audit written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        if candidate_export:
            export_gate_candidate_audit_csv(report.candidate_rows, output)
        else:
            export_gate_attribution_csv(report, output)
        print(f"Gate attribution audit written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    if group_by is None:
        for line in render_gate_attribution_report(report):
            print(line)
    else:
        print(f"Gate Attribution Grouped By {group_by}:")
        for line in group_gate_attribution_report(report, group_by=group_by):
            print(line)
    if primary_entry_states_only:
        print()
        print("Primary Universe: AGGRESSIVE_ENTRY, PREFERRED_ENTRY, CONFIRMATION_ENTRY")


@replay_app.command(name="gate-opportunity-cost")
def replay_gate_opportunity_cost() -> None:
    report = _gate_attribution_report()
    print()
    for line in group_gate_attribution_report(report, group_by="opportunity-cost"):
        print(line)


@replay_app.command(name="gate-downside-protection")
def replay_gate_downside_protection() -> None:
    report = _gate_attribution_report()
    print()
    for line in group_gate_attribution_report(report, group_by="downside-protection"):
        print(line)


@replay_app.command(name="gate-overlap")
def replay_gate_overlap() -> None:
    report = _gate_attribution_report()
    print()
    for line in group_gate_attribution_report(report, group_by="overlap"):
        print(line)


@replay_app.command(name="gate-interactions")
def replay_gate_interactions() -> None:
    report = _gate_attribution_report()
    print()
    for line in group_gate_attribution_report(report, group_by="interactions"):
        print(line)


@replay_app.command(name="gate-ranking")
def replay_gate_ranking() -> None:
    report = _gate_attribution_report()
    print()
    for line in group_gate_attribution_report(report, group_by="ranking"):
        print(line)


@replay_app.command(name="gate-economic-impact")
def replay_gate_economic_impact() -> None:
    report = _gate_attribution_report()
    print()
    for line in group_gate_attribution_report(report, group_by="economic-impact"):
        print(line)


@replay_app.command(name="directional-signal-audit")
def replay_directional_signal_audit(
    group_by: str | None = typer.Option(None, "--group-by"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Audit whether recorded directional signals separate future winners and losers.
    """

    report = _directional_signal_audit_report()
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_directional_signal_audit_json(report, output)
        print(f"Directional signal audit written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_directional_signal_audit_csv(report, output)
        print(f"Directional signal audit written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    if group_by is None:
        for line in render_directional_signal_audit(report):
            print(line)
    else:
        print(f"Directional Signal Audit Grouped By {group_by}:")
        for line in group_directional_signal_audit(report, group_by=group_by):
            print(line)


@replay_app.command(name="signal-ranking")
def replay_signal_ranking() -> None:
    report = _directional_signal_audit_report()
    print()
    for line in group_directional_signal_audit(report, group_by="ranking"):
        print(line)


@replay_app.command(name="signal-calibration")
def replay_signal_calibration() -> None:
    report = _directional_signal_audit_report()
    print()
    for line in group_directional_signal_audit(report, group_by="calibration"):
        print(line)


@replay_app.command(name="signal-components")
def replay_signal_components() -> None:
    report = _directional_signal_audit_report()
    print()
    for line in group_directional_signal_audit(report, group_by="components"):
        print(line)


@replay_app.command(name="signal-lineage")
def replay_signal_lineage() -> None:
    report = _directional_signal_audit_report()
    print()
    for line in group_directional_signal_audit(report, group_by="lineage"):
        print(line)


@replay_app.command(name="signal-outcome-quality")
def replay_signal_outcome_quality() -> None:
    report = _directional_signal_audit_report()
    print()
    for line in group_directional_signal_audit(report, group_by="outcome-quality"):
        print(line)


@replay_app.command(name="precision-coverage-frontier")
def replay_precision_coverage_frontier(
    direction: str = typer.Option("both", "--direction"),
    group_by: str | None = typer.Option(None, "--group-by"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Build a research-only BUY/SELL precision-coverage frontier.
    """

    observations, data_source = _directional_frontier_observations()
    report = build_precision_coverage_report(
        observations=observations,
        direction=_parse_directional_frontier_direction(direction),
        definition=_directional_frontier_default_definition(),
        data_source=data_source,
    )
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_precision_coverage_json(report, output)
        print(f"Precision-coverage frontier written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_frontier_csv(report.frontier, output)
        print(f"Precision-coverage frontier written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    lines = (
        _render_precision_frontier_group(report, group_by)
        if group_by is not None
        else render_precision_coverage_report(report)
    )
    for line in lines:
        print(line)


@replay_app.command(name="bidirectional-policy-audit")
def replay_bidirectional_policy_audit(
    min_precision: float = typer.Option(0.70, "--min-precision"),
    min_signals: int = typer.Option(100, "--min-signals"),
    group_by: str | None = typer.Option(None, "--group-by"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Audit whether transparent BUY and SELL policies meet research constraints.
    """

    observations, data_source = _directional_frontier_observations()
    report = build_policy_audit_report(
        observations=observations,
        minimum_precision=min_precision,
        minimum_signals=min_signals,
        definition=_directional_frontier_default_definition(),
        data_source=data_source,
    )
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_policy_audit_json(report, output)
        print(f"Bidirectional policy audit written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        rows = tuple(
            point for point in (report.buy_best, report.sell_best) if point is not None
        )
        export_frontier_csv(rows, output)
        print(f"Bidirectional policy audit written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    if group_by is not None:
        print(f"Bidirectional Policy Audit Grouped By {group_by}:")
        frontier_rows = tuple(
            point for point in (report.buy_best, report.sell_best) if point is not None
        )
        grouped = _group_frontier_points(frontier_rows, group_by)
        for line in grouped:
            print(line)
        return
    for line in render_policy_audit_report(report):
        print(line)


@replay_app.command(name="directional-calibration")
def replay_directional_calibration(
    group_by: str | None = typer.Option(None, "--group-by"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Report directional probability calibration without production influence.
    """

    observations, _ = _directional_frontier_observations()
    report = build_directional_calibration_report(
        observations=observations,
        definition=_directional_frontier_default_definition(),
    )
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_calibration_json(report, output)
        print(f"Directional calibration written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_calibration_csv(report, output)
        print(f"Directional calibration written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    if group_by is not None:
        print(f"Directional Calibration Grouped By {group_by}:")
    for line in render_calibration_report(report):
        print(line)


@replay_app.command(name="directional-policy-candidates")
def replay_directional_policy_candidates(
    group_by: str | None = typer.Option(None, "--group-by"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    List transparent candidate policies for future research review.
    """

    observations, data_source = _directional_frontier_observations()
    report = build_policy_candidate_report(
        observations=observations,
        definition=_directional_frontier_default_definition(),
        data_source=data_source,
    )
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_policy_candidates_json(report, output)
        print(f"Directional policy candidates written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_frontier_csv(report.candidates, output)
        print(f"Directional policy candidates written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    if group_by is not None:
        print(f"Directional Policy Candidates Grouped By {group_by}:")
        for line in _group_frontier_points(report.candidates, group_by):
            print(line)
        return
    for line in render_policy_candidate_report(report):
        print(line)


@replay_app.command(name="buy-signal-reconstruction")
def replay_buy_signal_reconstruction(
    group_by: str | None = typer.Option(None, "--group-by"),
    model: str | None = typer.Option(None, "--model"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Reconstruct BUY-only directional signal quality with transparent models.
    """

    report = _buy_signal_reconstruction_report()
    _emit_buy_reconstruction_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        model=model,
        renderer=render_buy_signal_reconstruction_report,
        label="BUY signal reconstruction",
    )


@replay_app.command(name="buy-feature-ablation")
def replay_buy_feature_ablation(
    group_by: str | None = typer.Option(None, "--group-by"),
    model: str | None = typer.Option(None, "--model"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _buy_signal_reconstruction_report()
    _emit_buy_reconstruction_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        model=model,
        renderer=render_buy_feature_ablation,
        label="BUY feature ablation",
    )


@replay_app.command(name="buy-false-positive-audit")
def replay_buy_false_positive_audit(
    group_by: str | None = typer.Option(None, "--group-by"),
    model: str | None = typer.Option(None, "--model"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _buy_signal_reconstruction_report()
    _emit_buy_reconstruction_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        model=model,
        renderer=render_buy_false_positive_audit,
        label="BUY false positive audit",
    )


@replay_app.command(name="buy-false-negative-audit")
def replay_buy_false_negative_audit(
    group_by: str | None = typer.Option(None, "--group-by"),
    model: str | None = typer.Option(None, "--model"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _buy_signal_reconstruction_report()
    _emit_buy_reconstruction_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        model=model,
        renderer=render_buy_false_negative_audit,
        label="BUY false negative audit",
    )


@replay_app.command(name="buy-minimal-models")
def replay_buy_minimal_models(
    group_by: str | None = typer.Option(None, "--group-by"),
    model: str | None = typer.Option(None, "--model"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _buy_signal_reconstruction_report()
    _emit_buy_reconstruction_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        model=model,
        renderer=render_buy_minimal_models,
        label="BUY minimal models",
    )


@replay_app.command(name="buy-precision-frontier")
def replay_buy_precision_frontier(
    group_by: str | None = typer.Option(None, "--group-by"),
    model: str | None = typer.Option(None, "--model"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _buy_signal_reconstruction_report()
    _emit_buy_reconstruction_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        model=model,
        renderer=render_buy_precision_frontier,
        label="BUY precision frontier",
    )


@replay_app.command(name="opportunity-evolution")
def replay_opportunity_evolution(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    trigger: str | None = typer.Option(None, "--trigger"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Reconstruct BUY opportunity lifecycles and entry-trigger alternatives.
    """

    report = _opportunity_evolution_report(symbol, opportunity_id, trigger)
    _emit_opportunity_evolution_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_opportunity_evolution_report,
        label="opportunity evolution",
    )


@replay_app.command(name="opportunity-lifecycle-audit")
def replay_opportunity_lifecycle_audit(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    trigger: str | None = typer.Option(None, "--trigger"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _opportunity_evolution_report(symbol, opportunity_id, trigger)
    _emit_opportunity_evolution_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_lifecycle_audit,
        label="opportunity lifecycle audit",
    )


@replay_app.command(name="entry-trigger-discovery")
def replay_entry_trigger_discovery(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    trigger: str | None = typer.Option(None, "--trigger"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _opportunity_evolution_report(symbol, opportunity_id, trigger)
    _emit_opportunity_evolution_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_entry_trigger_discovery,
        label="entry trigger discovery",
    )


@replay_app.command(name="entry-trigger-frontier")
def replay_entry_trigger_frontier(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    trigger: str | None = typer.Option(None, "--trigger"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _opportunity_evolution_report(symbol, opportunity_id, trigger)
    _emit_opportunity_evolution_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_entry_trigger_frontier,
        label="entry trigger frontier",
    )


@replay_app.command(name="early-entry-failures")
def replay_early_entry_failures(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    trigger: str | None = typer.Option(None, "--trigger"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _opportunity_evolution_report(symbol, opportunity_id, trigger)
    _emit_opportunity_evolution_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_early_entry_failures,
        label="early entry failures",
    )


@replay_app.command(name="confirmation-delay-audit")
def replay_confirmation_delay_audit(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    trigger: str | None = typer.Option(None, "--trigger"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _opportunity_evolution_report(symbol, opportunity_id, trigger)
    _emit_opportunity_evolution_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_confirmation_delay_audit,
        label="confirmation delay audit",
    )


@replay_app.command(name="opportunity-paths")
def replay_opportunity_paths(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    trigger: str | None = typer.Option(None, "--trigger"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _opportunity_evolution_report(symbol, opportunity_id, trigger)
    _emit_opportunity_evolution_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_opportunity_paths,
        label="opportunity paths",
    )


@replay_app.command(name="trigger-failure-attribution")
def replay_trigger_failure_attribution(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _confirmation_intelligence_report(symbol, opportunity_id)
    _emit_confirmation_intelligence_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_trigger_failure_attribution,
        label="trigger failure attribution",
    )


@replay_app.command(name="confirmation-intelligence")
def replay_confirmation_intelligence(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _confirmation_intelligence_report(symbol, opportunity_id)
    _emit_confirmation_intelligence_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_confirmation_intelligence_report,
        label="confirmation intelligence",
    )


@replay_app.command(name="participation-confirmation")
def replay_participation_confirmation(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _confirmation_intelligence_report(symbol, opportunity_id)
    _emit_confirmation_intelligence_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_participation_confirmation,
        label="participation confirmation",
    )


@replay_app.command(name="false-breakout-audit")
def replay_false_breakout_audit(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _confirmation_intelligence_report(symbol, opportunity_id)
    _emit_confirmation_intelligence_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_false_breakout_audit,
        label="false breakout audit",
    )


@replay_app.command(name="retest-quality-audit")
def replay_retest_quality_audit(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _confirmation_intelligence_report(symbol, opportunity_id)
    _emit_confirmation_intelligence_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_retest_quality_audit,
        label="retest quality audit",
    )


@replay_app.command(name="trigger-persistence-audit")
def replay_trigger_persistence_audit(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _confirmation_intelligence_report(symbol, opportunity_id)
    _emit_confirmation_intelligence_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_trigger_persistence_audit,
        label="trigger persistence audit",
    )


@replay_app.command(name="trigger-cancellation-audit")
def replay_trigger_cancellation_audit(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _confirmation_intelligence_report(symbol, opportunity_id)
    _emit_confirmation_intelligence_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_trigger_cancellation_audit,
        label="trigger cancellation audit",
    )


@replay_app.command(name="confirmation-frontier")
def replay_confirmation_frontier(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _confirmation_intelligence_report(symbol, opportunity_id)
    _emit_confirmation_intelligence_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_confirmation_frontier,
        label="confirmation frontier",
    )


@replay_app.command(name="breakout-reference-reconstruct")
def replay_breakout_reference_reconstruct(
    from_date: str | None = typer.Option(None, "--from-date"),
    to_date: str | None = typer.Option(None, "--to-date"),
    symbol: str | None = typer.Option(None, "--symbol"),
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    replay_run_id: str | None = typer.Option(None, "--replay-run-id"),
    reference_method: str = typer.Option("prior-swing-high", "--reference-method"),
    minimum_lookback: int = typer.Option(60, "--minimum-lookback", min=5),
    limit: int | None = typer.Option(None, "--limit", min=1),
    force: bool = typer.Option(False, "--force"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    method = _breakout_reference_method(reference_method)
    start = _optional_breakout_reference_date(from_date)
    end = _optional_breakout_reference_date(to_date)
    try:
        run = reconstruct_breakout_references_from_project_sources(
            from_date=start,
            to_date=end,
            symbol=symbol,
            candidate_id=candidate_id,
            replay_run_id=replay_run_id,
            reference_method=method,
            minimum_lookback=minimum_lookback,
            limit=limit,
            force=force,
            dry_run=dry_run,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    _emit_breakout_reference_output(
        records=run.records,
        payload=run,
        lines=render_breakout_reference_reconstruction(run.persistence),
        output_format=output_format,
        output=output,
        label="breakout reference reconstruction",
    )


@replay_app.command(name="breakout-reference-readiness")
def replay_breakout_reference_readiness(
    from_date: str | None = typer.Option(None, "--from-date"),
    to_date: str | None = typer.Option(None, "--to-date"),
    symbol: str | None = typer.Option(None, "--symbol"),
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    replay_run_id: str | None = typer.Option(None, "--replay-run-id"),
    reference_method: str | None = typer.Option(None, "--reference-method"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    method = _optional_breakout_reference_method(reference_method)
    start = _optional_breakout_reference_date(from_date)
    end = _optional_breakout_reference_date(to_date)
    records = _breakout_reference_records(
        from_date=start,
        to_date=end,
        symbol=symbol,
        candidate_id=candidate_id,
        replay_run_id=replay_run_id,
        reference_method=method,
    )
    total = count_filtered_replay_candidates(
        from_date=start,
        to_date=end,
        symbol=symbol,
        candidate_id=candidate_id,
        replay_run_id=replay_run_id,
    )
    report = build_breakout_historical_readiness_report(
        records=records,
        total_replay_candidates=total,
    )
    _emit_breakout_reference_output(
        records=records,
        payload=report,
        lines=render_breakout_reference_readiness(report),
        output_format=output_format,
        output=output,
        label="breakout reference readiness",
    )


@replay_app.command(name="breakout-reference-integrity")
def replay_breakout_reference_integrity(
    from_date: str | None = typer.Option(None, "--from-date"),
    to_date: str | None = typer.Option(None, "--to-date"),
    symbol: str | None = typer.Option(None, "--symbol"),
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    replay_run_id: str | None = typer.Option(None, "--replay-run-id"),
    reference_method: str | None = typer.Option(None, "--reference-method"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    start = _optional_breakout_reference_date(from_date)
    end = _optional_breakout_reference_date(to_date)
    records = _breakout_reference_records(
        from_date=start,
        to_date=end,
        symbol=symbol,
        candidate_id=candidate_id,
        replay_run_id=replay_run_id,
        reference_method=_optional_breakout_reference_method(reference_method),
    )
    audit = audit_breakout_reference_integrity(records)
    _emit_breakout_reference_output(
        records=records,
        payload=audit,
        lines=render_breakout_reference_integrity(audit),
        output_format=output_format,
        output=output,
        label="breakout reference integrity",
    )


@replay_app.command(name="breakout-reference-provenance")
def replay_breakout_reference_provenance(
    from_date: str | None = typer.Option(None, "--from-date"),
    to_date: str | None = typer.Option(None, "--to-date"),
    symbol: str | None = typer.Option(None, "--symbol"),
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    replay_run_id: str | None = typer.Option(None, "--replay-run-id"),
    reference_method: str | None = typer.Option(None, "--reference-method"),
    limit: int = typer.Option(20, "--limit", min=1),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    start = _optional_breakout_reference_date(from_date)
    end = _optional_breakout_reference_date(to_date)
    records = _breakout_reference_records(
        from_date=start,
        to_date=end,
        symbol=symbol,
        candidate_id=candidate_id,
        replay_run_id=replay_run_id,
        reference_method=_optional_breakout_reference_method(reference_method),
    )
    _emit_breakout_reference_output(
        records=records,
        payload=records,
        lines=render_breakout_reference_provenance(records, limit=limit),
        output_format=output_format,
        output=output,
        label="breakout reference provenance",
    )


@replay_app.command(name="breakout-reference-sample")
def replay_breakout_reference_sample(
    from_date: str | None = typer.Option(None, "--from-date"),
    to_date: str | None = typer.Option(None, "--to-date"),
    symbol: str | None = typer.Option(None, "--symbol"),
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    replay_run_id: str | None = typer.Option(None, "--replay-run-id"),
    reference_method: str | None = typer.Option(None, "--reference-method"),
    limit: int = typer.Option(20, "--limit", min=1),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    start = _optional_breakout_reference_date(from_date)
    end = _optional_breakout_reference_date(to_date)
    records = _breakout_reference_records(
        from_date=start,
        to_date=end,
        symbol=symbol,
        candidate_id=candidate_id,
        replay_run_id=replay_run_id,
        reference_method=_optional_breakout_reference_method(reference_method),
    )
    selected = records[:limit]
    _emit_breakout_reference_output(
        records=selected,
        payload=selected,
        lines=render_breakout_reference_sample(selected, limit=limit),
        output_format=output_format,
        output=output,
        label="breakout reference sample",
    )


@replay_app.command(name="breakout-source-gap-audit")
def replay_breakout_source_gap_audit(
    group_by: str | None = typer.Option(None, "--group-by"),
    cause: str | None = typer.Option(None, "--cause"),
    recovery_class: str | None = typer.Option(None, "--recovery-class"),
    provider: str | None = typer.Option(None, "--provider"),
    symbol: str | None = typer.Option(None, "--symbol"),
    from_date: str | None = typer.Option(None, "--from-date"),
    to_date: str | None = typer.Option(None, "--to-date"),
    year: int | None = typer.Option(None, "--year"),
    minimum_sample: int = typer.Option(10, "--minimum-sample", min=2),
    limit: int | None = typer.Option(None, "--limit", min=1),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _breakout_gap_report(
        cause=cause,
        recovery_class=recovery_class,
        provider=provider,
        symbol=symbol,
        from_date=from_date,
        to_date=to_date,
        year=year,
        minimum_sample=minimum_sample,
        limit=limit,
    )
    lines = (
        (
            "Breakout Source-Gap Attribution Audit",
            f"Grouped By: {group_by}",
            *_breakout_gap_group_lines(report.coverage.records, group_by),
            "PRODUCTION_INFLUENCE=false",
        )
        if group_by is not None
        else render_breakout_source_gap_audit(report)
    )
    _emit_breakout_gap_output(
        records=report.coverage.records,
        payload=report,
        lines=lines,
        output_format=output_format,
        output=output,
        label="breakout source-gap audit",
    )


@replay_app.command(name="breakout-selection-bias")
def replay_breakout_selection_bias(
    group_by: str | None = typer.Option(None, "--group-by"),
    cause: str | None = typer.Option(None, "--cause"),
    recovery_class: str | None = typer.Option(None, "--recovery-class"),
    provider: str | None = typer.Option(None, "--provider"),
    symbol: str | None = typer.Option(None, "--symbol"),
    from_date: str | None = typer.Option(None, "--from-date"),
    to_date: str | None = typer.Option(None, "--to-date"),
    year: int | None = typer.Option(None, "--year"),
    minimum_sample: int = typer.Option(10, "--minimum-sample", min=2),
    limit: int | None = typer.Option(None, "--limit", min=1),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _breakout_gap_report(
        cause=cause,
        recovery_class=recovery_class,
        provider=provider,
        symbol=symbol,
        from_date=from_date,
        to_date=to_date,
        year=year,
        minimum_sample=minimum_sample,
        limit=limit,
    )
    lines = (
        (
            "Breakout Selection-Bias Audit",
            f"Grouped By: {group_by}",
            *_breakout_gap_group_lines(report.coverage.records, group_by),
            "PRODUCTION_INFLUENCE=false",
        )
        if group_by is not None
        else render_breakout_selection_bias(report.selection_bias)
    )
    _emit_breakout_gap_output(
        records=report.coverage.records,
        payload=report.selection_bias,
        lines=lines,
        output_format=output_format,
        output=output,
        label="breakout selection-bias audit",
    )


@replay_app.command(name="breakout-source-coverage")
def replay_breakout_source_coverage(
    group_by: str = typer.Option("provider", "--group-by"),
    cause: str | None = typer.Option(None, "--cause"),
    recovery_class: str | None = typer.Option(None, "--recovery-class"),
    provider: str | None = typer.Option(None, "--provider"),
    symbol: str | None = typer.Option(None, "--symbol"),
    from_date: str | None = typer.Option(None, "--from-date"),
    to_date: str | None = typer.Option(None, "--to-date"),
    year: int | None = typer.Option(None, "--year"),
    minimum_sample: int = typer.Option(10, "--minimum-sample", min=2),
    limit: int | None = typer.Option(None, "--limit", min=1),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _breakout_gap_report(
        cause=cause,
        recovery_class=recovery_class,
        provider=provider,
        symbol=symbol,
        from_date=from_date,
        to_date=to_date,
        year=year,
        minimum_sample=minimum_sample,
        limit=limit,
    )
    try:
        lines = render_breakout_source_coverage(
            report.coverage,
            group_by=group_by,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    _emit_breakout_gap_output(
        records=report.coverage.records,
        payload=report.coverage,
        lines=lines,
        output_format=output_format,
        output=output,
        label="breakout source coverage",
    )


@replay_app.command(name="breakout-recovery-readiness")
def replay_breakout_recovery_readiness(
    group_by: str | None = typer.Option(None, "--group-by"),
    cause: str | None = typer.Option(None, "--cause"),
    recovery_class: str | None = typer.Option(None, "--recovery-class"),
    provider: str | None = typer.Option(None, "--provider"),
    symbol: str | None = typer.Option(None, "--symbol"),
    from_date: str | None = typer.Option(None, "--from-date"),
    to_date: str | None = typer.Option(None, "--to-date"),
    year: int | None = typer.Option(None, "--year"),
    minimum_sample: int = typer.Option(10, "--minimum-sample", min=2),
    limit: int | None = typer.Option(None, "--limit", min=1),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _breakout_gap_report(
        cause=cause,
        recovery_class=recovery_class,
        provider=provider,
        symbol=symbol,
        from_date=from_date,
        to_date=to_date,
        year=year,
        minimum_sample=minimum_sample,
        limit=limit,
    )
    lines = (
        (
            "Breakout Recovery Readiness Audit",
            f"Grouped By: {group_by}",
            *_breakout_gap_group_lines(report.coverage.records, group_by),
            "PRODUCTION_INFLUENCE=false",
        )
        if group_by is not None
        else render_breakout_recovery_readiness(report.recovery)
    )
    _emit_breakout_gap_output(
        records=report.coverage.records,
        payload=report.recovery,
        lines=lines,
        output_format=output_format,
        output=output,
        label="breakout recovery readiness",
    )


@replay_app.command(name="breakout-gap-sample")
def replay_breakout_gap_sample(
    group_by: str | None = typer.Option(None, "--group-by"),
    cause: str | None = typer.Option(None, "--cause"),
    recovery_class: str | None = typer.Option(None, "--recovery-class"),
    provider: str | None = typer.Option(None, "--provider"),
    symbol: str | None = typer.Option(None, "--symbol"),
    from_date: str | None = typer.Option(None, "--from-date"),
    to_date: str | None = typer.Option(None, "--to-date"),
    year: int | None = typer.Option(None, "--year"),
    minimum_sample: int = typer.Option(10, "--minimum-sample", min=2),
    limit: int = typer.Option(30, "--limit", min=1),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _breakout_gap_report(
        cause=cause,
        recovery_class=recovery_class,
        provider=provider,
        symbol=symbol,
        from_date=from_date,
        to_date=to_date,
        year=year,
        minimum_sample=minimum_sample,
        limit=None,
    )
    unavailable = tuple(item for item in report.coverage.records if not item.ready)[
        :limit
    ]
    lines = (
        (
            "Breakout Gap Attribution Sample",
            f"Grouped By: {group_by}",
            *_breakout_gap_group_lines(unavailable, group_by),
            "PRODUCTION_INFLUENCE=false",
        )
        if group_by is not None
        else render_breakout_gap_sample(unavailable)
    )
    _emit_breakout_gap_output(
        records=unavailable,
        payload=unavailable,
        lines=lines,
        output_format=output_format,
        output=output,
        label="breakout gap sample",
    )


@replay_app.command(name="historical-source-requirements")
def replay_historical_source_requirements(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Print the formal data and permitted-use requirements."""
    requirements = historical_source_requirements()
    _emit_historical_source_output(
        payload=requirements,
        rows=requirement_csv_rows(requirements),
        lines=render_historical_source_requirements(requirements),
        output_format=output_format,
        output=output,
        label="historical source requirements",
    )


@replay_app.command(name="historical-source-manifest")
def replay_historical_source_manifest(
    sample: bool = typer.Option(False, "--sample"),
    full_population: bool = typer.Option(False, "--full-population"),
    symbol: str | None = typer.Option(None, "--symbol"),
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    year: int | None = typer.Option(None, "--year"),
    gap_cause: str | None = typer.Option(None, "--gap-cause"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    refresh: bool = typer.Option(False, "--refresh"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Print or export the immutable missing-population evaluation manifest."""
    report = _historical_source_report(
        sample=sample,
        full_population=full_population,
        symbol=symbol,
        candidate_id=candidate_id,
        year=year,
        gap_cause=gap_cause,
        dry_run=dry_run,
        refresh=refresh,
    )
    records = report.sample.records if sample else report.manifest.records
    _emit_historical_source_output(
        payload=records,
        rows=manifest_csv_rows(records),
        lines=render_historical_source_manifest(report.manifest, report.sample),
        output_format=output_format,
        output=output,
        label="historical source manifest",
    )


@replay_app.command(name="historical-source-evaluate")
def replay_historical_source_evaluate(
    provider: str | None = typer.Option(None, "--provider"),
    sample: bool = typer.Option(False, "--sample"),
    full_population: bool = typer.Option(False, "--full-population"),
    symbol: str | None = typer.Option(None, "--symbol"),
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    year: int | None = typer.Option(None, "--year"),
    gap_cause: str | None = typer.Option(None, "--gap-cause"),
    credentials_status: str = typer.Option("auto", "--credentials-status"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    refresh: bool = typer.Option(False, "--refresh"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Compare documented capabilities and any supplied observed evidence."""
    report = _historical_source_report(
        provider=provider,
        sample=sample,
        full_population=full_population,
        symbol=symbol,
        candidate_id=candidate_id,
        year=year,
        gap_cause=gap_cause,
        credentials_status=credentials_status,
        dry_run=dry_run,
        refresh=refresh,
    )
    _emit_historical_source_output(
        payload=report,
        rows=coverage_csv_rows(report.coverage_results),
        lines=render_historical_source_evaluation(report),
        output_format=output_format,
        output=output,
        label="historical source evaluation",
    )


@replay_app.command(name="historical-source-coverage")
def replay_historical_source_coverage(
    provider: str | None = typer.Option(None, "--provider"),
    sample: bool = typer.Option(False, "--sample"),
    full_population: bool = typer.Option(False, "--full-population"),
    symbol: str | None = typer.Option(None, "--symbol"),
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    year: int | None = typer.Option(None, "--year"),
    gap_cause: str | None = typer.Option(None, "--gap-cause"),
    credentials_status: str = typer.Option("auto", "--credentials-status"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    refresh: bool = typer.Option(False, "--refresh"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Show documented versus observed candidate coverage proof."""
    report = _historical_source_report(
        provider=provider,
        sample=sample,
        full_population=full_population,
        symbol=symbol,
        candidate_id=candidate_id,
        year=year,
        gap_cause=gap_cause,
        credentials_status=credentials_status,
        dry_run=dry_run,
        refresh=refresh,
    )
    _emit_historical_source_output(
        payload=report.coverage_results,
        rows=coverage_csv_rows(report.coverage_results),
        lines=render_historical_source_coverage(report),
        output_format=output_format,
        output=output,
        label="historical source coverage",
    )


@replay_app.command(name="historical-source-license-audit")
def replay_historical_source_license_audit(
    provider: str | None = typer.Option(None, "--provider"),
    credentials_status: str = typer.Option("auto", "--credentials-status"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    refresh: bool = typer.Option(False, "--refresh"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Show terms, storage, caching, and derived-use classifications."""
    report = _historical_source_report(
        provider=provider,
        sample=False,
        full_population=False,
        credentials_status=credentials_status,
        dry_run=dry_run,
        refresh=refresh,
    )
    _emit_historical_source_output(
        payload=report.providers,
        rows=license_csv_rows(report.providers),
        lines=render_historical_source_license_audit(report),
        output_format=output_format,
        output=output,
        label="historical source license audit",
    )


@replay_app.command(name="historical-source-recommendation")
def replay_historical_source_recommendation(
    provider: str | None = typer.Option(None, "--provider"),
    sample: bool = typer.Option(False, "--sample"),
    full_population: bool = typer.Option(False, "--full-population"),
    symbol: str | None = typer.Option(None, "--symbol"),
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    year: int | None = typer.Option(None, "--year"),
    gap_cause: str | None = typer.Option(None, "--gap-cause"),
    credentials_status: str = typer.Option("auto", "--credentials-status"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    refresh: bool = typer.Option(False, "--refresh"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Recommend the next source-evaluation step without integrating a provider."""
    report = _historical_source_report(
        provider=provider,
        sample=sample,
        full_population=full_population,
        symbol=symbol,
        candidate_id=candidate_id,
        year=year,
        gap_cause=gap_cause,
        credentials_status=credentials_status,
        dry_run=dry_run,
        refresh=refresh,
    )
    _emit_historical_source_output(
        payload=report,
        rows=coverage_csv_rows(report.coverage_results),
        lines=render_historical_source_recommendation(report),
        output_format=output_format,
        output=output,
        label="historical source recommendation",
    )


@replay_app.command(name="upstox-auth-probe")
def replay_upstox_auth_probe(
    live: bool = typer.Option(False, "--live"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Probe only documented read-only Upstox market-data endpoints."""
    service = _upstox_historical_probe_service()
    result = service.authentication_probe(live=live and not dry_run)
    _emit_upstox_probe_output(
        payload=result,
        records=(),
        lines=render_upstox_auth_probe(result),
        output_format=output_format,
        output=output,
        label="Upstox authentication probe",
    )


@replay_app.command(name="upstox-historical-sample")
def replay_upstox_historical_sample(
    live: bool = typer.Option(False, "--live"),
    sample: bool = typer.Option(False, "--sample"),
    full_population: bool = typer.Option(False, "--full-population"),
    confirm_full_population: bool = typer.Option(False, "--confirm-full-population"),
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    symbol: str | None = typer.Option(None, "--symbol"),
    year: int | None = typer.Option(None, "--year"),
    gap_cause: str | None = typer.Option(None, "--gap-cause"),
    limit: int | None = typer.Option(None, "--limit"),
    resume: bool = typer.Option(False, "--resume"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Run or preview the deterministic historical evidence trial."""
    run = _run_upstox_historical_probe(
        live=live,
        sample=sample or not full_population,
        full_population=full_population,
        confirm_full_population=confirm_full_population,
        candidate_id=candidate_id,
        symbol=symbol,
        year=year,
        gap_cause=gap_cause,
        limit=limit,
        resume=resume,
        dry_run=dry_run,
    )
    lines = (
        *render_upstox_historical_sample(run.plan.sample, run.dataset),
        f"Attempted This Run: {run.attempted_candidates}",
        f"Resumed Candidates: {run.resumed_candidates}",
        f"Stopped Early: {'yes' if run.stopped_early else 'no'}",
    )
    _emit_upstox_probe_output(
        payload=run.dataset or run.plan,
        records=_upstox_records(run),
        lines=lines,
        output_format=output_format,
        output=output,
        label="Upstox historical sample",
    )


@replay_app.command(name="upstox-historical-coverage")
def replay_upstox_historical_coverage(
    live: bool = typer.Option(False, "--live"),
    sample: bool = typer.Option(False, "--sample"),
    full_population: bool = typer.Option(False, "--full-population"),
    confirm_full_population: bool = typer.Option(False, "--confirm-full-population"),
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    symbol: str | None = typer.Option(None, "--symbol"),
    year: int | None = typer.Option(None, "--year"),
    gap_cause: str | None = typer.Option(None, "--gap-cause"),
    limit: int | None = typer.Option(None, "--limit"),
    resume: bool = typer.Option(False, "--resume"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Report price coverage separately from reconstruction readiness."""
    run = _run_upstox_historical_probe(
        live=live,
        sample=sample or not full_population,
        full_population=full_population,
        confirm_full_population=confirm_full_population,
        candidate_id=candidate_id,
        symbol=symbol,
        year=year,
        gap_cause=gap_cause,
        limit=limit,
        resume=resume,
        dry_run=dry_run,
    )
    records = _upstox_records(run)
    metrics = run.operational_metrics
    lines = (
        *render_upstox_historical_coverage(records),
        f"Attempted This Run: {run.attempted_candidates}",
        f"Completed Candidates: {len(records)}",
        f"Resumed Candidates: {run.resumed_candidates}",
        f"Stopped Early: {'yes' if run.stopped_early else 'no'}",
        f"Stop Reason: {run.stop_reason or 'none'}",
        f"Network Requests: {metrics.total_network_requests}",
        f"Successful Requests: {metrics.successful_requests}",
        f"Authentication Failures: {metrics.authentication_failures}",
        f"Rate-Limit Responses: {metrics.rate_limit_responses}",
        f"Transient Failures: {metrics.transient_failures}",
        f"Permanent Failures: {metrics.permanent_failures}",
        f"Retries: {metrics.retries}",
        f"Elapsed Seconds: {metrics.elapsed_seconds}",
        f"Request Rate per Second: {metrics.request_rate_per_second or 'unavailable'}",
        f"Account Endpoint Calls: {metrics.account_endpoint_calls}",
        f"Order Endpoint Calls: {metrics.order_endpoint_calls}",
        f"Token Exposure Incidents: {metrics.token_exposure_incidents}",
    )
    _emit_upstox_probe_output(
        payload=records,
        records=records,
        lines=lines,
        output_format=output_format,
        output=output,
        label="Upstox historical coverage",
    )


@replay_app.command(name="upstox-identity-coverage")
def replay_upstox_identity_coverage(
    live: bool = typer.Option(False, "--live"),
    sample: bool = typer.Option(False, "--sample"),
    full_population: bool = typer.Option(False, "--full-population"),
    confirm_full_population: bool = typer.Option(False, "--confirm-full-population"),
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    symbol: str | None = typer.Option(None, "--symbol"),
    year: int | None = typer.Option(None, "--year"),
    gap_cause: str | None = typer.Option(None, "--gap-cause"),
    limit: int | None = typer.Option(None, "--limit"),
    resume: bool = typer.Option(False, "--resume"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Report authoritative and provisional identity coverage."""
    run = _run_upstox_historical_probe(
        live=live,
        sample=sample or not full_population,
        full_population=full_population,
        confirm_full_population=confirm_full_population,
        candidate_id=candidate_id,
        symbol=symbol,
        year=year,
        gap_cause=gap_cause,
        limit=limit,
        resume=resume,
        dry_run=dry_run,
    )
    records = _upstox_records(run)
    _emit_upstox_probe_output(
        payload=records,
        records=records,
        lines=render_upstox_identity_coverage(records),
        output_format=output_format,
        output=output,
        label="Upstox identity coverage",
    )


@replay_app.command(name="upstox-adjustment-audit")
def replay_upstox_adjustment_audit(
    live: bool = typer.Option(False, "--live"),
    sample: bool = typer.Option(False, "--sample"),
    full_population: bool = typer.Option(False, "--full-population"),
    confirm_full_population: bool = typer.Option(False, "--confirm-full-population"),
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    symbol: str | None = typer.Option(None, "--symbol"),
    year: int | None = typer.Option(None, "--year"),
    gap_cause: str | None = typer.Option(None, "--gap-cause"),
    limit: int | None = typer.Option(None, "--limit"),
    resume: bool = typer.Option(False, "--resume"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Audit observed adjustment semantics without assuming smoothness is proof."""
    run = _run_upstox_historical_probe(
        live=live,
        sample=sample or not full_population,
        full_population=full_population,
        confirm_full_population=confirm_full_population,
        candidate_id=candidate_id,
        symbol=symbol,
        year=year,
        gap_cause=gap_cause,
        limit=limit,
        resume=resume,
        dry_run=dry_run,
    )
    records = _upstox_records(run)
    _emit_upstox_probe_output(
        payload=records,
        records=records,
        lines=render_upstox_adjustment_audit(records),
        output_format=output_format,
        output=output,
        label="Upstox adjustment audit",
    )


@replay_app.command(name="upstox-series-integrity")
def replay_upstox_series_integrity(
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    symbol: str | None = typer.Option(None, "--symbol"),
    year: int | None = typer.Option(None, "--year"),
    limit: int | None = typer.Option(None, "--limit"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Reconcile persisted Upstox bar counts and invalid-series causes."""
    dataset = _upstox_historical_probe_service().repository.load()
    records = dataset.records if dataset is not None else ()
    try:
        selected = filter_upstox_series_records(
            records,
            candidate_id=candidate_id,
            symbol=symbol,
            year=year,
            limit=limit,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    report = UpstoxSeriesIntegrityEngine().build(selected)
    _emit_upstox_series_integrity_output(
        report,
        lines=render_upstox_series_integrity(report),
        output_format=output_format,
        output=output,
    )


@replay_app.command(name="upstox-evidence-report")
def replay_upstox_evidence_report(
    live: bool = typer.Option(False, "--live"),
    sample: bool = typer.Option(False, "--sample"),
    full_population: bool = typer.Option(False, "--full-population"),
    confirm_full_population: bool = typer.Option(False, "--confirm-full-population"),
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    symbol: str | None = typer.Option(None, "--symbol"),
    year: int | None = typer.Option(None, "--year"),
    gap_cause: str | None = typer.Option(None, "--gap-cause"),
    limit: int | None = typer.Option(None, "--limit"),
    resume: bool = typer.Option(False, "--resume"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Render the empirical Upstox source-readiness conclusion."""
    run = _run_upstox_historical_probe(
        live=live,
        sample=sample or not full_population,
        full_population=full_population,
        confirm_full_population=confirm_full_population,
        candidate_id=candidate_id,
        symbol=symbol,
        year=year,
        gap_cause=gap_cause,
        limit=limit,
        resume=resume,
        dry_run=dry_run,
    )
    _emit_upstox_probe_output(
        payload=run.report,
        records=_upstox_records(run),
        lines=render_upstox_evidence_report(run.report),
        output_format=output_format,
        output=output,
        label="Upstox evidence report",
    )


@replay_app.command(name="upstox-full-population-utility")
def replay_upstox_full_population_utility(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Audit persisted Upstox price utility without changing reconstruction."""
    service = _upstox_historical_probe_service()
    dataset = service.repository.load()
    baseline = build_project_historical_source_evaluation(dry_run=True)
    breakout_audit = build_project_breakout_source_gap_audit()
    report = UpstoxFullPopulationUtilityEngine().build(
        manifest=baseline.manifest,
        dataset=dataset,
        breakout_audit=breakout_audit,
    )
    _emit_upstox_probe_output(
        payload=report,
        records=(),
        lines=render_upstox_full_population_utility(report),
        output_format=output_format,
        output=output,
        label="Upstox full-population utility report",
    )


@replay_app.command(name="nse-archive-source-discovery")
def replay_nse_archive_source_discovery(
    market_date: str | None = typer.Option(None, "--date"),
    date_from: str | None = typer.Option(None, "--date-from"),
    date_to: str | None = typer.Option(None, "--date-to"),
    source_type: str | None = typer.Option(None, "--source-type"),
    live: bool = typer.Option(False, "--live"),
    authorization_reference: str | None = typer.Option(
        None,
        "--authorization-reference",
        help="Non-secret reference proving authorized automated NSE use.",
    ),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Discover bounded official NSE archive evidence with fail-closed access."""
    bundle = _nse_archive_proof_bundle(
        market_date=market_date,
        date_from=date_from,
        date_to=date_to,
        live=live,
        authorization_reference=authorization_reference,
    )
    parsed_source = _parse_nse_source_type(source_type)
    files = tuple(
        item
        for item in bundle.discovery.files
        if parsed_source is None or item.source_type is parsed_source
    )
    report = replace(bundle.discovery, files=files)
    _emit_nse_proof_output(
        payload=report,
        rows=files,
        lines=render_nse_archive_source_discovery(report),
        output_format=output_format,
        output=output,
        label="NSE archive source discovery",
    )


@replay_app.command(name="nse-security-file-inspect")
def replay_nse_security_file_inspect(
    market_date: str | None = typer.Option(None, "--date"),
    date_from: str | None = typer.Option(None, "--date-from"),
    date_to: str | None = typer.Option(None, "--date-to"),
    source_type: str | None = typer.Option(None, "--source-type"),
    live: bool = typer.Option(False, "--live"),
    authorization_reference: str | None = typer.Option(
        None, "--authorization-reference"
    ),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Inspect fields actually present in bounded dated NSE security artifacts."""
    bundle = _nse_archive_proof_bundle(
        market_date=market_date,
        date_from=date_from,
        date_to=date_to,
        live=live,
        authorization_reference=authorization_reference,
    )
    parsed_source = _parse_nse_source_type(source_type)
    inspections = tuple(
        item
        for item in bundle.security.inspections
        if parsed_source is None or item.file_evidence.source_type is parsed_source
    )
    report = replace(bundle.security, inspections=inspections)
    _emit_nse_proof_output(
        payload=report,
        rows=inspections,
        lines=render_nse_security_file_inspect(report),
        output_format=output_format,
        output=output,
        label="NSE security-file inspection",
    )


@replay_app.command(name="nse-identity-proof")
def replay_nse_identity_proof(
    market_date: str | None = typer.Option(None, "--date"),
    date_from: str | None = typer.Option(None, "--date-from"),
    date_to: str | None = typer.Option(None, "--date-to"),
    symbol: str | None = typer.Option(None, "--symbol"),
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    source_type: str | None = typer.Option(None, "--source-type"),
    live: bool = typer.Option(False, "--live"),
    authorization_reference: str | None = typer.Option(
        None, "--authorization-reference"
    ),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Prove candidate-date identity using official dated NSE evidence."""
    bundle = _nse_archive_proof_bundle(
        market_date=market_date,
        date_from=date_from,
        date_to=date_to,
        live=live,
        authorization_reference=authorization_reference,
    )
    _require_bhavcopy_source(source_type)
    records = _filter_nse_identity_records(
        bundle.identity.records,
        market_date=market_date,
        date_from=date_from,
        date_to=date_to,
        symbol=symbol,
        candidate_id=candidate_id,
    )
    report = NseIdentityProofEngine().build_report(records)
    _emit_nse_proof_output(
        payload=report,
        rows=records,
        lines=render_nse_identity_proof(report),
        output_format=output_format,
        output=output,
        label="NSE identity proof",
    )


@replay_app.command(name="nse-corporate-action-proof")
def replay_nse_corporate_action_proof(
    market_date: str | None = typer.Option(None, "--date"),
    date_from: str | None = typer.Option(None, "--date-from"),
    date_to: str | None = typer.Option(None, "--date-to"),
    symbol: str | None = typer.Option(None, "--symbol"),
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    source_type: str | None = typer.Option(None, "--source-type"),
    live: bool = typer.Option(False, "--live"),
    authorization_reference: str | None = typer.Option(
        None, "--authorization-reference"
    ),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Audit NSE corporate-action evidence without clearing identity by proxy."""
    bundle = _nse_archive_proof_bundle(
        market_date=market_date,
        date_from=date_from,
        date_to=date_to,
        live=live,
        authorization_reference=authorization_reference,
    )
    parsed_source = _parse_nse_source_type(source_type)
    if parsed_source not in {None, NseArchiveSourceType.CORPORATE_ACTIONS}:
        raise typer.BadParameter(
            "--source-type for this command must be CORPORATE_ACTIONS"
        )
    records = _filter_nse_corporate_action_records(
        bundle.corporate_actions.records,
        market_date=market_date,
        date_from=date_from,
        date_to=date_to,
        symbol=symbol,
        candidate_id=candidate_id,
    )
    report = _selected_nse_corporate_action_report(bundle, records)
    _emit_nse_proof_output(
        payload=report,
        rows=records,
        lines=render_nse_corporate_action_proof(report),
        output_format=output_format,
        output=output,
        label="NSE corporate-action proof",
    )


@replay_app.command(name="nse-archive-coverage")
def replay_nse_archive_coverage(
    market_date: str | None = typer.Option(None, "--date"),
    date_from: str | None = typer.Option(None, "--date-from"),
    date_to: str | None = typer.Option(None, "--date-to"),
    symbol: str | None = typer.Option(None, "--symbol"),
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    source_type: str | None = typer.Option(None, "--source-type"),
    live: bool = typer.Option(False, "--live"),
    authorization_reference: str | None = typer.Option(
        None, "--authorization-reference"
    ),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Report empirical trial and 657-candidate NSE archive coverage."""
    bundle = _nse_archive_proof_bundle(
        market_date=market_date,
        date_from=date_from,
        date_to=date_to,
        live=live,
        authorization_reference=authorization_reference,
    )
    _require_bhavcopy_source(source_type)
    if symbol is not None or candidate_id is not None:
        selected = _filter_nse_identity_records(
            bundle.population_identity_records,
            market_date=market_date,
            date_from=date_from,
            date_to=date_to,
            symbol=symbol,
            candidate_id=candidate_id,
        )
    else:
        selected = bundle.population_identity_records
    _emit_nse_proof_output(
        payload=bundle.coverage,
        rows=selected,
        lines=render_nse_archive_coverage(bundle.coverage),
        output_format=output_format,
        output=output,
        label="NSE archive coverage",
    )


@replay_app.command(name="nse-archive-readiness")
def replay_nse_archive_readiness(
    market_date: str | None = typer.Option(None, "--date"),
    date_from: str | None = typer.Option(None, "--date-from"),
    date_to: str | None = typer.Option(None, "--date-to"),
    symbol: str | None = typer.Option(None, "--symbol"),
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    source_type: str | None = typer.Option(None, "--source-type"),
    live: bool = typer.Option(False, "--live"),
    authorization_reference: str | None = typer.Option(
        None, "--authorization-reference"
    ),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Simulate readiness without mutating reconstruction or production policy."""
    bundle = _nse_archive_proof_bundle(
        market_date=market_date,
        date_from=date_from,
        date_to=date_to,
        live=live,
        authorization_reference=authorization_reference,
    )
    _require_bhavcopy_source(source_type)
    if symbol is not None or candidate_id is not None:
        _filter_nse_identity_records(
            bundle.population_identity_records,
            market_date=market_date,
            date_from=date_from,
            date_to=date_to,
            symbol=symbol,
            candidate_id=candidate_id,
        )
    _emit_nse_proof_output(
        payload=bundle.readiness,
        rows=(bundle.readiness,),
        lines=render_nse_archive_readiness(bundle.readiness),
        output_format=output_format,
        output=output,
        label="NSE archive readiness simulation",
    )


@replay_app.command(name="historical-identity-bridge-audit")
def replay_historical_identity_bridge_audit(
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    symbol: str | None = typer.Option(None, "--symbol"),
    status: str | None = typer.Option(None, "--status"),
    source: str | None = typer.Option(None, "--source"),
    year: int | None = typer.Option(None, "--year"),
    inactive: bool = typer.Option(False, "--inactive"),
    renamed: bool = typer.Option(False, "--renamed"),
    limit: int | None = typer.Option(None, "--limit"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Audit effective-dated identity authority without changing reconstruction."""
    bundle = _historical_identity_audit_bundle()
    records = _filtered_historical_identity_records(
        bundle,
        candidate_id=candidate_id,
        symbol=symbol,
        status=status,
        source=source,
        year=year,
        inactive=inactive,
        renamed=renamed,
        limit=limit,
    )
    lines = (*render_historical_identity_bridge_audit(bundle.bridge),)
    if len(records) != len(bundle.bridge.records):
        lines = (*lines[:-1], f"Selected Records: {len(records)}", lines[-1])
    _emit_historical_identity_output(
        payload=bundle.bridge,
        records=records,
        lines=lines,
        output_format=output_format,
        output=output,
        label="historical identity bridge audit",
    )


@replay_app.command(name="historical-identity-unresolved")
def replay_historical_identity_unresolved(
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    symbol: str | None = typer.Option(None, "--symbol"),
    status: str | None = typer.Option(None, "--status"),
    source: str | None = typer.Option(None, "--source"),
    year: int | None = typer.Option(None, "--year"),
    inactive: bool = typer.Option(False, "--inactive"),
    renamed: bool = typer.Option(False, "--renamed"),
    limit: int | None = typer.Option(None, "--limit"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Cluster unresolved historical identities by deterministic root cause."""
    bundle = _historical_identity_audit_bundle()
    records = _filtered_historical_identity_records(
        bundle,
        candidate_id=candidate_id,
        symbol=symbol,
        status=status,
        source=source,
        year=year,
        inactive=inactive,
        renamed=renamed,
        limit=limit,
    )
    unresolved = tuple(
        item
        for item in records
        if not item.authoritative
        and item.final_identity_status.value != "PROVISIONAL_PROVIDER_SYMBOL_MATCH"
    )
    _emit_historical_identity_output(
        payload=unresolved,
        records=unresolved,
        lines=render_historical_identity_unresolved(bundle.bridge, unresolved),
        output_format=output_format,
        output=output,
        label="historical identity unresolved audit",
    )


@replay_app.command(name="historical-identity-provisional")
def replay_historical_identity_provisional(
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    symbol: str | None = typer.Option(None, "--symbol"),
    status: str | None = typer.Option(None, "--status"),
    source: str | None = typer.Option(None, "--source"),
    year: int | None = typer.Option(None, "--year"),
    inactive: bool = typer.Option(False, "--inactive"),
    renamed: bool = typer.Option(False, "--renamed"),
    limit: int | None = typer.Option(None, "--limit"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Audit provisional provider matches without upgrading identity authority."""
    bundle = _historical_identity_audit_bundle()
    records = _filtered_historical_identity_records(
        bundle,
        candidate_id=candidate_id,
        symbol=symbol,
        status=status,
        source=source,
        year=year,
        inactive=inactive,
        renamed=renamed,
        limit=limit,
    )
    provisional = tuple(
        item
        for item in records
        if item.final_identity_status.value == "PROVISIONAL_PROVIDER_SYMBOL_MATCH"
    )
    _emit_historical_identity_output(
        payload=provisional,
        records=provisional,
        lines=render_historical_identity_provisional(provisional),
        output_format=output_format,
        output=output,
        label="historical identity provisional audit",
    )


@replay_app.command(name="historical-identity-source-coverage")
def replay_historical_identity_source_coverage(
    source: str | None = typer.Option(None, "--source"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Show fields, authority, and gaps for each local identity evidence source."""
    bundle = _historical_identity_audit_bundle()
    coverage = tuple(
        item
        for item in bundle.bridge.source_coverage
        if source is None or item.source.upper() == source.upper()
    )
    report = replace(bundle.bridge, source_coverage=coverage)
    _emit_historical_identity_output(
        payload=coverage,
        records=(),
        lines=render_historical_identity_source_coverage(report),
        output_format=output_format,
        output=output,
        label="historical identity source coverage",
    )


@replay_app.command(name="upstox-identity-metadata-audit")
def replay_upstox_identity_metadata_audit(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Audit retained non-secret Upstox instrument identity metadata."""
    report = _historical_identity_audit_bundle().metadata
    _emit_historical_identity_output(
        payload=report,
        records=(),
        lines=render_upstox_identity_metadata_audit(report),
        output_format=output_format,
        output=output,
        label="Upstox identity metadata audit",
    )


@replay_app.command(name="upstox-duplicate-origin-audit")
def replay_upstox_duplicate_origin_audit(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Attribute duplicate sessions only when retained row lineage supports it."""
    report = _historical_identity_audit_bundle().duplicates
    _emit_historical_identity_output(
        payload=report,
        records=(),
        lines=render_upstox_duplicate_origin_audit(report),
        output_format=output_format,
        output=output,
        label="Upstox duplicate origin audit",
    )


@replay_app.command(name="historical-identity-readiness")
def replay_historical_identity_readiness(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Report actual and scenario identity readiness without applying evidence."""
    report = _historical_identity_audit_bundle().bridge
    _emit_historical_identity_output(
        payload=report,
        records=(),
        lines=render_historical_identity_readiness(report),
        output_format=output_format,
        output=output,
        label="historical identity readiness",
    )


@replay_app.command(name="breakout-intelligence")
def replay_breakout_intelligence(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    breakout_class: str | None = typer.Option(None, "--breakout-class"),
    policy: str | None = typer.Option(None, "--policy"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _breakout_intelligence_report(
        symbol, opportunity_id, breakout_class, policy
    )
    _emit_breakout_intelligence_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_breakout_intelligence_report,
        label="breakout intelligence",
    )


@replay_app.command(name="breakout-classification-audit")
def replay_breakout_classification_audit(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    breakout_class: str | None = typer.Option(None, "--breakout-class"),
    policy: str | None = typer.Option(None, "--policy"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _breakout_intelligence_report(
        symbol, opportunity_id, breakout_class, policy
    )
    _emit_breakout_intelligence_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_breakout_classification_audit,
        label="breakout classification audit",
    )


@replay_app.command(name="breakout-transition-audit")
def replay_breakout_transition_audit(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    breakout_class: str | None = typer.Option(None, "--breakout-class"),
    policy: str | None = typer.Option(None, "--policy"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _breakout_intelligence_report(
        symbol, opportunity_id, breakout_class, policy
    )
    _emit_breakout_intelligence_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_breakout_transition_audit,
        label="breakout transition audit",
    )


@replay_app.command(name="breakout-rs-independence")
def replay_breakout_rs_independence(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    breakout_class: str | None = typer.Option(None, "--breakout-class"),
    policy: str | None = typer.Option(None, "--policy"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _breakout_intelligence_report(
        symbol, opportunity_id, breakout_class, policy
    )
    _emit_breakout_intelligence_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_breakout_rs_independence,
        label="breakout rs independence",
    )


@replay_app.command(name="false-breakout-analysis")
def replay_false_breakout_analysis(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    breakout_class: str | None = typer.Option(None, "--breakout-class"),
    policy: str | None = typer.Option(None, "--policy"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _breakout_intelligence_report(
        symbol, opportunity_id, breakout_class, policy
    )
    _emit_breakout_intelligence_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_false_breakout_analysis,
        label="false breakout analysis",
    )


@replay_app.command(name="breakout-lineage-audit")
def replay_breakout_lineage_audit(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    breakout_class: str | None = typer.Option(None, "--breakout-class"),
    policy: str | None = typer.Option(None, "--policy"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _breakout_intelligence_report(
        symbol, opportunity_id, breakout_class, policy
    )
    _emit_breakout_intelligence_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_breakout_lineage_audit,
        label="breakout lineage audit",
    )


@replay_app.command(name="breakout-stability-audit")
def replay_breakout_stability_audit(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    breakout_class: str | None = typer.Option(None, "--breakout-class"),
    policy: str | None = typer.Option(None, "--policy"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _breakout_intelligence_report(
        symbol, opportunity_id, breakout_class, policy
    )
    _emit_breakout_intelligence_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_breakout_stability_audit,
        label="breakout stability audit",
    )


@replay_app.command(name="breakout-class-frontier")
def replay_breakout_class_frontier(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    breakout_class: str | None = typer.Option(None, "--breakout-class"),
    policy: str | None = typer.Option(None, "--policy"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _breakout_intelligence_report(
        symbol, opportunity_id, breakout_class, policy
    )
    _emit_breakout_intelligence_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_breakout_class_frontier,
        label="breakout class frontier",
    )


@replay_app.command(name="breakout-opportunity-paths")
def replay_breakout_opportunity_paths(
    group_by: str | None = typer.Option(None, "--group-by"),
    symbol: str | None = typer.Option(None, "--symbol"),
    opportunity_id: str | None = typer.Option(None, "--opportunity-id"),
    breakout_class: str | None = typer.Option(None, "--breakout-class"),
    policy: str | None = typer.Option(None, "--policy"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _breakout_intelligence_report(
        symbol, opportunity_id, breakout_class, policy
    )
    _emit_breakout_intelligence_report(
        report,
        output_format=output_format,
        output=output,
        group_by=group_by,
        renderer=render_breakout_opportunity_paths,
        label="breakout opportunity paths",
    )


@replay_app.command(name="market-regime-audit")
def replay_market_regime_audit(
    group_by: str | None = typer.Option(None, "--group-by"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Audit market-regime classification, timestamp joins, and intervention value.
    """

    report = _market_regime_audit_report()
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_market_regime_audit_json(report, output)
        print(f"Market regime audit written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_market_regime_audit_csv(report, output)
        print(f"Market regime audit written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    if group_by is None:
        for line in render_market_regime_audit(report):
            print(line)
    else:
        for line in group_market_regime_audit(report, group_by=group_by):
            print(line)


@replay_app.command(name="regime-lineage")
def replay_regime_lineage() -> None:
    report = _market_regime_audit_report()
    print()
    for line in group_market_regime_audit(report, group_by="lineage"):
        print(line)


@replay_app.command(name="regime-transitions")
def replay_regime_transitions() -> None:
    report = _market_regime_audit_report()
    print()
    for line in group_market_regime_audit(report, group_by="transitions"):
        print(line)


@replay_app.command(name="regime-reference-comparison")
def replay_regime_reference_comparison() -> None:
    report = _market_regime_audit_report()
    print()
    for line in group_market_regime_audit(report, group_by="reference"):
        print(line)


@replay_app.command(name="regime-intervention")
def replay_regime_intervention() -> None:
    report = _market_regime_audit_report()
    print()
    for line in group_market_regime_audit(report, group_by="intervention"):
        print(line)


@replay_app.command(name="regime-episodes")
def replay_regime_episodes() -> None:
    report = _market_regime_audit_report()
    print()
    for line in group_market_regime_audit(report, group_by="episodes"):
        print(line)


@replay_app.command(name="regime-retracement-interaction")
def replay_regime_retracement_interaction() -> None:
    report = _market_regime_audit_report()
    print()
    for line in group_market_regime_audit(report, group_by="retracement"):
        print(line)


@replay_app.command(name="market-state-persistence-audit")
def replay_market_state_persistence_audit(
    group_by: str | None = typer.Option(None, "--group-by"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Audit historical market-state persistence, reconstruction, and attachments.
    """

    report = _market_state_persistence_audit_report()
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_market_state_persistence_audit_json(report, output)
        print(f"Market state persistence audit written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_market_state_persistence_audit_csv(report, output)
        print(f"Market state persistence audit written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    if group_by is None:
        for line in render_market_state_persistence_audit(report):
            print(line)
    else:
        for line in group_market_state_persistence_audit(report, group_by=group_by):
            print(line)


@replay_app.command(name="market-state-inventory")
def replay_market_state_inventory() -> None:
    print()
    for line in group_market_state_persistence_audit(
        _market_state_persistence_audit_report(),
        group_by="inventory",
    ):
        print(line)


@replay_app.command(name="market-state-timestamps")
def replay_market_state_timestamps() -> None:
    print()
    for line in group_market_state_persistence_audit(
        _market_state_persistence_audit_report(),
        group_by="timestamps",
    ):
        print(line)


@replay_app.command(name="market-state-reconstruction")
def replay_market_state_reconstruction() -> None:
    print()
    for line in group_market_state_persistence_audit(
        _market_state_persistence_audit_report(),
        group_by="reconstruction",
    ):
        print(line)


@replay_app.command(name="market-state-comparison")
def replay_market_state_comparison() -> None:
    print()
    for line in group_market_state_persistence_audit(
        _market_state_persistence_audit_report(),
        group_by="comparison",
    ):
        print(line)


@replay_app.command(name="market-state-fallbacks")
def replay_market_state_fallbacks() -> None:
    print()
    for line in group_market_state_persistence_audit(
        _market_state_persistence_audit_report(),
        group_by="fallback",
    ):
        print(line)


@replay_app.command(name="market-state-episodes")
def replay_market_state_episodes() -> None:
    print()
    for line in group_market_state_persistence_audit(
        _market_state_persistence_audit_report(),
        group_by="episodes",
    ):
        print(line)


@replay_app.command(name="market-state-selection-effect")
def replay_market_state_selection_effect() -> None:
    print()
    for line in group_market_state_persistence_audit(
        _market_state_persistence_audit_report(),
        group_by="selection-effect",
    ):
        print(line)


@replay_app.command(name="market-state-classifier-replay")
def replay_market_state_classifier_replay() -> None:
    print()
    for line in group_market_state_persistence_audit(
        _market_state_persistence_audit_report(),
        group_by="classifier-replay",
    ):
        print(line)


@replay_app.command(name="market-state-counterfactuals")
def replay_market_state_counterfactuals() -> None:
    print()
    for line in group_market_state_persistence_audit(
        _market_state_persistence_audit_report(),
        group_by="counterfactuals",
    ):
        print(line)


@replay_app.command(name="market-state-backfill-plan")
def replay_market_state_backfill_plan() -> None:
    """
    Dry-run the historical market-state snapshot backfill plan.
    """

    repository = NightlyLearningLoop.from_path().repository
    snapshot_repository = MarketStateSnapshotRepository()
    report = build_market_state_backfill_plan(
        records=repository.load_records(),
        snapshots=snapshot_repository.load_all(),
    )
    print()
    for line in render_market_state_backfill_plan(report):
        print(line)


@replay_app.command(name="benchmark-state-audit")
def replay_benchmark_state_audit(
    group_by: str | None = typer.Option(None, "--group-by"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Audit canonical benchmark coverage and snapshot completeness.
    """

    report = _benchmark_coverage_report()
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_benchmark_coverage_json(report, output)
        print(f"Benchmark state audit written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_benchmark_coverage_csv(report, output)
        print(f"Benchmark state audit written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    if group_by in {None, "date", "completeness", "fallback"}:
        for line in render_benchmark_coverage(report):
            print(line)
        return
    raise typer.BadParameter("group-by must be date, completeness, or fallback.")


@replay_app.command(name="market-state-backfill-readiness")
def replay_market_state_backfill_readiness(
    group_by: str | None = typer.Option(None, "--group-by"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Diagnose whether historical market-state backfill is source-ready.
    """

    if group_by not in {None, "date", "year"}:
        raise typer.BadParameter("group-by must be date or year.")
    report = _market_state_backfill_readiness_report(group_by=group_by)
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_backfill_readiness_json(report, output)
        print(f"Historical backfill readiness written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_backfill_readiness_csv(report, output)
        print(f"Historical backfill readiness written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in render_backfill_readiness_report(report, group_by=group_by):
        print(line)


@replay_app.command(name="market-state-source-inventory")
def replay_market_state_source_inventory() -> None:
    """
    Print historical market-state input availability and source safety.
    """

    report = _market_state_backfill_readiness_report()
    print()
    for line in render_market_input_inventory(report.input_inventory):
        print(line)


@replay_app.command(name="benchmark-date-reconciliation")
def replay_benchmark_date_reconciliation() -> None:
    """
    Reconcile candidate dates against available benchmark bars.
    """

    report = _market_state_backfill_readiness_report()
    print()
    for line in render_benchmark_date_reconciliation(report.date_reconciliation):
        print(line)


@replay_app.command(name="benchmark-lookback-gaps")
def replay_benchmark_lookback_gaps() -> None:
    """
    Attribute benchmark 200-DMA gaps without changing classifier behavior.
    """

    report = _market_state_backfill_readiness_report()
    print()
    for line in render_benchmark_lookback_gaps(report.lookback_gaps):
        print(line)


@replay_app.command(name="benchmark-source-integrity")
def replay_benchmark_source_integrity() -> None:
    """
    Audit benchmark OHLC source integrity for historical reconstruction.
    """

    report = _market_state_backfill_readiness_report()
    print()
    for line in render_benchmark_source_integrity(report.source_integrity):
        print(line)


@replay_app.command(name="benchmark-proxy-suitability")
def replay_benchmark_proxy_suitability() -> None:
    """
    Explain whether the configured benchmark proxy is fit for backfill use.
    """

    report = _market_state_backfill_readiness_report()
    print()
    for line in render_benchmark_proxy_suitability(report.proxy_suitability):
        print(line)


@replay_app.command(name="historical-breadth-readiness")
def replay_historical_breadth_readiness() -> None:
    """
    Diagnose whether historical breadth can be rebuilt point-in-time.
    """

    report = _market_state_backfill_readiness_report()
    print()
    for line in render_historical_breadth_readiness(report.breadth_readiness):
        print(line)


@replay_app.command(name="historical-sector-readiness")
def replay_historical_sector_readiness() -> None:
    """
    Diagnose whether historical sector state can be rebuilt point-in-time.
    """

    report = _market_state_backfill_readiness_report()
    print()
    for line in render_historical_sector_readiness(report.sector_readiness):
        print(line)


@replay_app.command(name="classifier-version-readiness")
def replay_classifier_version_readiness() -> None:
    """
    Diagnose whether historical candidate rows carry classifier lineage.
    """

    report = _market_state_backfill_readiness_report()
    print()
    for line in render_classifier_version_readiness(
        report.classifier_version_readiness
    ):
        print(line)


@replay_app.command(name="market-state-backfill-simulate")
def replay_market_state_backfill_simulate() -> None:
    """
    Dry-run historical snapshot rows without writing authoritative snapshots.
    """

    report = _market_state_backfill_readiness_report()
    print()
    for line in render_market_state_backfill_simulation(report.simulation_plan):
        print(line)


@replay_app.command(name="classifier-version-lineage")
def replay_classifier_version_lineage(
    group_by: str | None = typer.Option(None, "--group-by"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Audit historical candidate classifier-version lineage without mutation.
    """

    if group_by not in {None, "status"}:
        raise typer.BadParameter("group-by must be status.")
    report = _version_lineage_report()
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_version_lineage_json(report, output)
        print(f"Classifier version lineage written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_version_lineage_csv(report, output)
        print(f"Classifier version lineage written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in render_version_lineage_report(report, group_by=group_by):
        print(line)


@replay_app.command(name="classifier-version-evidence")
def replay_classifier_version_evidence() -> None:
    """
    Inventory evidence sources for historical classifier-version recovery.
    """

    report = _version_lineage_report()
    print()
    for line in render_version_evidence(report.evidence_sources):
        print(line)


@replay_app.command(name="classifier-version-compatibility")
def replay_classifier_version_compatibility() -> None:
    """
    Show historical candidate compatibility with current classifier lineage.
    """

    report = _version_lineage_report()
    print()
    for line in render_version_compatibility(report.recoveries):
        print(line)


@replay_app.command(name="analytical-version-drift")
def replay_analytical_version_drift() -> None:
    """
    Compare persisted provenance with the currently installed component registry.
    """

    print()
    for line in render_version_drift(_version_drift_report()):
        print(line)


@replay_app.command(name="historical-backfill-version-eligibility")
def replay_historical_backfill_version_eligibility() -> None:
    """
    Audit backfill eligibility using classifier version lineage.
    """

    report = _version_lineage_report()
    print()
    for line in render_backfill_version_eligibility(report.eligibility):
        print(line)


@replay_app.command(name="historical-release-evidence")
def replay_historical_release_evidence(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Inventory historical analytical release evidence without mutation.
    """

    report = _historical_manifest_audit_report()
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_historical_manifest_report_json(report, output)
        print(f"Historical release evidence written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_historical_manifest_assignments_csv(report, output)
        print(f"Historical release evidence written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in render_historical_release_evidence(report.evidence):
        print(line)


@replay_app.command(name="historical-analytical-eras")
def replay_historical_analytical_eras() -> None:
    """
    Show historical analytical era reconstruction.
    """

    report = _historical_manifest_audit_report()
    print()
    for line in render_historical_analytical_eras(report.eras):
        print(line)


@replay_app.command(name="historical-manifest-coverage")
def replay_historical_manifest_coverage(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Audit manifest lineage coverage and coverage attribution.
    """

    report = _historical_manifest_audit_report()
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_historical_manifest_report_json(report, output)
        print(f"Historical manifest coverage written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_historical_manifest_assignments_csv(report, output)
        print(f"Historical manifest coverage written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in render_historical_manifest_coverage(report):
        print(line)


@replay_app.command(name="historical-era-assignment")
def replay_historical_era_assignment(
    group_by: str | None = typer.Option(None, "--group-by"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Assign candidate rows to the strongest supported historical era status.
    """

    if group_by not in {None, "status"}:
        raise typer.BadParameter("group-by must be status.")
    report = _historical_manifest_audit_report()
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_historical_manifest_report_json(report, output)
        print(f"Historical era assignment written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_historical_manifest_assignments_csv(report, output)
        print(f"Historical era assignment written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in render_historical_era_assignments(
        report.assignments,
        group_by=group_by,
    ):
        print(line)


@replay_app.command(name="historical-backfill-manifest-eligibility")
def replay_historical_backfill_manifest_eligibility() -> None:
    """
    Audit backfill eligibility using release-manifest evidence.
    """

    report = _historical_manifest_audit_report()
    print()
    for line in render_historical_backfill_manifest_eligibility(report.eligibility):
        print(line)


@replay_app.command(name="diagnostic-market-state-build")
def replay_diagnostic_market_state_build(
    from_date: str | None = typer.Option(None, "--from"),
    to_date: str | None = typer.Option(None, "--to"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    persist_diagnostic: bool = typer.Option(False, "--persist-diagnostic"),
    replace_dataset_version: bool = typer.Option(False, "--replace-dataset-version"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Build the separate non-authoritative diagnostic market-state dataset.
    """

    dataset = _diagnostic_market_state_dataset(
        from_date=None if from_date is None else _parse_date(from_date),
        to_date=None if to_date is None else _parse_date(to_date),
        dry_run=dry_run or not persist_diagnostic,
    )
    repository = DiagnosticMarketStateRepository()
    result = repository.save_dataset(
        dataset,
        replace_dataset_version=replace_dataset_version,
    )
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_diagnostic_json(dataset, output)
        print(f"Diagnostic market-state dataset written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_reconstructions_csv(dataset.reconstructions, output)
        print(f"Diagnostic market-state reconstructions written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in render_diagnostic_build_result(result, dataset=dataset):
        print(line)


@replay_app.command(name="diagnostic-market-state-coverage")
def replay_diagnostic_market_state_coverage(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Report coverage for the persisted diagnostic market-state dataset.
    """

    repository = DiagnosticMarketStateRepository()
    report = build_diagnostic_market_state_coverage_report(
        reconstructions=repository.load_reconstructions(
            dataset_version=DIAGNOSTIC_MARKET_STATE_DATASET_VERSION
        ),
        links=repository.load_links(),
    )
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_diagnostic_json(report, output)
        print(f"Diagnostic market-state coverage written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_reconstructions_csv(
            repository.load_reconstructions(
                dataset_version=DIAGNOSTIC_MARKET_STATE_DATASET_VERSION
            ),
            output,
        )
        print(f"Diagnostic market-state coverage written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in render_diagnostic_coverage(report):
        print(line)


@replay_app.command(name="diagnostic-market-state-history")
def replay_diagnostic_market_state_history() -> None:
    """
    List persisted diagnostic market-state reconstructions.
    """

    rows = DiagnosticMarketStateRepository().load_reconstructions(
        dataset_version=DIAGNOSTIC_MARKET_STATE_DATASET_VERSION
    )
    print()
    for line in render_diagnostic_history(rows):
        print(line)


@replay_app.command(name="diagnostic-market-state-show")
def replay_diagnostic_market_state_show(
    reconstruction_id: str = typer.Option(..., "--reconstruction-id"),
) -> None:
    """
    Show one diagnostic market-state reconstruction.
    """

    row = DiagnosticMarketStateRepository().get(reconstruction_id)
    if row is None:
        raise typer.BadParameter(f"Unknown reconstruction id: {reconstruction_id}")
    print()
    for line in render_diagnostic_show(row):
        print(line)


@replay_app.command(name="diagnostic-market-state-lineage")
def replay_diagnostic_market_state_lineage(
    reconstruction_id: str = typer.Option(..., "--reconstruction-id"),
) -> None:
    """
    Show diagnostic reconstruction lineage and classifier compatibility.
    """

    row = DiagnosticMarketStateRepository().get(reconstruction_id)
    if row is None:
        raise typer.BadParameter(f"Unknown reconstruction id: {reconstruction_id}")
    print()
    for line in render_diagnostic_lineage(row):
        print(line)


@replay_app.command(name="diagnostic-market-state-quality")
def replay_diagnostic_market_state_quality() -> None:
    """
    Summarize diagnostic reconstruction quality dimensions.
    """

    rows = DiagnosticMarketStateRepository().load_reconstructions(
        dataset_version=DIAGNOSTIC_MARKET_STATE_DATASET_VERSION
    )
    print()
    for line in render_diagnostic_quality(rows):
        print(line)


@replay_app.command(name="diagnostic-market-state-no-look-ahead")
def replay_diagnostic_market_state_no_look_ahead() -> None:
    """
    Audit persisted diagnostic reconstructions for no-look-ahead violations.
    """

    rows = DiagnosticMarketStateRepository().load_reconstructions(
        dataset_version=DIAGNOSTIC_MARKET_STATE_DATASET_VERSION
    )
    print()
    for line in render_no_lookahead(build_no_lookahead_report(rows)):
        print(line)


@replay_app.command(name="reconstructed-regime-comparison")
def replay_reconstructed_regime_comparison() -> None:
    """
    Compare recorded regimes to diagnostic current-classifier replay regimes.
    """

    report = _diagnostic_regime_comparison_report()
    print()
    for line in render_regime_comparison(report):
        print(line)


@replay_app.command(name="reconstructed-neutral-collapse")
def replay_reconstructed_neutral_collapse() -> None:
    """
    Reassess recorded neutral collapse using the diagnostic reconstruction dataset.
    """

    report = _diagnostic_regime_comparison_report()
    print()
    for line in render_neutral_collapse(report):
        print(line)


@replay_app.command(name="security-master-source-audit")
def replay_security_master_source_audit(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Audit local sources for security-master and classification evidence.
    """

    records = NightlyLearningLoop.from_path().repository.load_records()
    report = build_historical_source_inventory(
        price_repository=MarketTruthPriceRepository(),
        records=records,
    )
    _emit_point_in_time_report(
        report,
        output_format=output_format,
        output=output,
        rows=report,
        renderer=render_source_inventory,
        label="Security master source audit",
    )


@replay_app.command(name="security-identity-audit")
def replay_security_identity_audit(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Audit stable security identity coverage and conflicts.
    """

    dataset = _point_in_time_universe_dataset(dry_run=True)
    report = build_security_identity_audit(dataset)
    _emit_point_in_time_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_security_identity_audit,
        label="Security identity audit",
    )


@replay_app.command(name="listing-delisting-audit")
def replay_listing_delisting_audit(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Audit listing and delisting evidence quality.
    """

    dataset = _point_in_time_universe_dataset(dry_run=True)
    report = build_listing_delisting_audit(dataset)
    _emit_point_in_time_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_listing_delisting_audit,
        label="Listing-delisting audit",
    )


@replay_app.command(name="point-in-time-universe-build")
def replay_point_in_time_universe_build(
    dry_run: bool = typer.Option(False, "--dry-run"),
    persist_diagnostic: bool = typer.Option(False, "--persist-diagnostic"),
    resume: bool = typer.Option(False, "--resume"),
    batch_size: int = typer.Option(60, "--batch-size"),
    from_date: str | None = typer.Option(None, "--from"),
    to_date: str | None = typer.Option(None, "--to"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Incrementally materialize the diagnostic point-in-time dataset.
    """

    records = NightlyLearningLoop.from_path().repository.load_records()
    result = PointInTimeMaterializationEngine().build(
        records=records,
        price_repository=MarketTruthPriceRepository(),
        from_date=_parse_date(from_date) if from_date else None,
        to_date=_parse_date(to_date) if to_date else None,
        batch_size=batch_size,
        persist=persist_diagnostic and not dry_run,
        resume=resume,
    )
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_point_in_time_json(result.materialization, output)
        print(f"Point-in-time build result written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_point_in_time_csv(result.materialization.universe.rows, output)
        print(f"Point-in-time universe rows written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in render_point_in_time_build_result(result):
        print(line)


@replay_app.command(name="point-in-time-build-resume")
def replay_point_in_time_build_resume(
    batch_size: int = typer.Option(60, "--batch-size"),
    from_date: str | None = typer.Option(None, "--from"),
    to_date: str | None = typer.Option(None, "--to"),
) -> None:
    """
    Resume a compatible partial point-in-time materialization.
    """

    records = NightlyLearningLoop.from_path().repository.load_records()
    result = PointInTimeMaterializationEngine().build(
        records=records,
        price_repository=MarketTruthPriceRepository(),
        from_date=_parse_date(from_date) if from_date else None,
        to_date=_parse_date(to_date) if to_date else None,
        batch_size=batch_size,
        persist=True,
        resume=True,
    )
    print()
    for line in render_point_in_time_build_result(result):
        print(line)


@replay_app.command(name="point-in-time-build-status")
def replay_point_in_time_build_status() -> None:
    """
    Show persisted point-in-time materialization status.
    """

    print()
    materialization = _load_point_in_time_materialization()
    for line in render_point_in_time_build_status(materialization):
        print(line)


@replay_app.command(name="point-in-time-build-history")
def replay_point_in_time_build_history() -> None:
    """
    Show persisted point-in-time materialization checkpoints.
    """

    print()
    materialization = _load_point_in_time_materialization()
    for line in render_point_in_time_build_history(materialization):
        print(line)


@replay_app.command(name="point-in-time-build-profile")
def replay_point_in_time_build_profile() -> None:
    """
    Show point-in-time build performance profile.
    """

    materialization = _load_point_in_time_materialization()
    if materialization is None:
        print()
        print("Point-in-Time Build Profile")
        print("Status: NOT MATERIALIZED")
        print("Dominant Stage: unavailable")
        return
    print()
    for line in render_point_in_time_build_profile(materialization.profile):
        print(line)


@replay_app.command(name="point-in-time-dataset-validate")
def replay_point_in_time_dataset_validate(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Validate the persisted point-in-time materialization.
    """

    materialization = _load_point_in_time_materialization()
    report = validate_point_in_time_materialization(materialization)
    _emit_point_in_time_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_point_in_time_validation,
        label="Point-in-time dataset validation",
    )


@replay_app.command(name="point-in-time-store-import")
def replay_point_in_time_store_import(
    build_id: str = typer.Option(..., "--build-id"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Import the validated JSON materialization into the indexed analytical store.
    """

    result = PointInTimeAnalyticalRepository().import_materialization(build_id=build_id)
    _emit_point_in_time_report(
        result,
        output_format=output_format,
        output=output,
        rows=(result,),
        renderer=render_point_in_time_store_import,
        label="Point-in-time analytical store import",
    )


@replay_app.command(name="point-in-time-store-status")
def replay_point_in_time_store_status(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Show the indexed analytical store status.
    """

    report = PointInTimeAnalyticalRepository().status()
    _emit_point_in_time_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_point_in_time_store_status,
        label="Point-in-time analytical store status",
    )


@replay_app.command(name="point-in-time-store-validate")
def replay_point_in_time_store_validate(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Validate the indexed analytical store without reparsing the full JSON artifact.
    """

    report = PointInTimeAnalyticalRepository().validate()
    _emit_point_in_time_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_point_in_time_store_validation,
        label="Point-in-time analytical store validation",
    )


@replay_app.command(name="point-in-time-store-equivalence")
def replay_point_in_time_store_equivalence(
    build_id: str = typer.Option(..., "--build-id"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Validate analytical-store equivalence against the JSON materialization.
    """

    report = PointInTimeAnalyticalRepository().equivalence(build_id=build_id)
    _emit_point_in_time_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_point_in_time_store_equivalence,
        label="Point-in-time store equivalence",
    )


@replay_app.command(name="point-in-time-store-profile")
def replay_point_in_time_store_profile(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Profile the latest indexed analytical-store read path.
    """

    repository = PointInTimeAnalyticalRepository()
    snapshots = repository.breadth_snapshots()
    report = repository.last_profile()
    _emit_point_in_time_report(
        report,
        output_format=output_format,
        output=output,
        rows=tuple(snapshots),
        renderer=render_point_in_time_store_profile,
        label="Point-in-time analytical store profile",
    )


@replay_app.command(name="point-in-time-read-profile")
def replay_point_in_time_read_profile(
    market_date: str | None = typer.Option(None, "--date"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Profile a point-in-time read without full JSON deserialization.
    """

    repository = PointInTimeAnalyticalRepository()
    if market_date is None:
        profile_rows: tuple[object, ...] = repository.breadth_snapshots()
    else:
        profile_rows = repository.universe_rows(market_date=_parse_date(market_date))
    report = repository.last_profile()
    _emit_point_in_time_report(
        report,
        output_format=output_format,
        output=output,
        rows=profile_rows,
        renderer=render_point_in_time_store_profile,
        label="Point-in-time read profile",
    )


@replay_app.command(name="point-in-time-universe-coverage")
def replay_point_in_time_universe_coverage(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Report diagnostic point-in-time universe coverage.
    """

    store = PointInTimeAnalyticalRepository()
    report = (
        store.universe_coverage()
        if store.status().exists
        else build_universe_coverage_report(
            _load_completed_point_in_time_materialization().universe
        )
    )
    _emit_point_in_time_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_universe_coverage,
        label="Point-in-time universe coverage",
    )


@replay_app.command(name="point-in-time-universe-show")
def replay_point_in_time_universe_show(
    market_date: str = typer.Option(..., "--date"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Show point-in-time universe rows for one date.
    """

    target = _parse_date(market_date)
    store = PointInTimeAnalyticalRepository()
    rows = (
        store.universe_rows(market_date=target)
        if store.status().exists
        else tuple(
            row
            for row in _load_completed_point_in_time_materialization().universe.rows
            if row.market_date == target
        )
    )
    _emit_point_in_time_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=lambda _: render_universe_show(rows, target),
        label="Point-in-time universe rows",
    )


@replay_app.command(name="point-in-time-sector-build")
def replay_point_in_time_sector_build(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Build diagnostic current-mapping sector classifications without persistence.
    """

    dataset = _load_completed_point_in_time_universe()
    rows = dataset.sector_classifications
    _emit_point_in_time_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=lambda _: (
            "Point-in-Time Sector Build",
            f"Classifications: {len(rows)}",
            "Persistence: dry-run only",
            (
                "Warning: current sector classification is not historical sector "
                "classification."
            ),
        ),
        label="Point-in-time sector build",
    )


@replay_app.command(name="point-in-time-sector-coverage")
def replay_point_in_time_sector_coverage(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Report sector classification coverage and readiness.
    """

    dataset = _load_completed_point_in_time_universe()
    report = build_sector_coverage_audit(dataset)
    _emit_point_in_time_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_sector_coverage,
        label="Point-in-time sector coverage",
    )


@replay_app.command(name="sector-classification-conflicts")
def replay_sector_classification_conflicts(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Report sector classification conflicts.
    """

    dataset = _load_completed_point_in_time_universe()
    conflicts = build_sector_conflicts(dataset)
    _emit_point_in_time_report(
        conflicts,
        output_format=output_format,
        output=output,
        rows=conflicts,
        renderer=render_sector_conflicts,
        label="Sector classification conflicts",
    )


@replay_app.command(name="point-in-time-breadth")
def replay_point_in_time_breadth(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Calculate point-in-time breadth from the diagnostic universe.
    """

    store = PointInTimeAnalyticalRepository()
    snapshots = (
        store.breadth_snapshots()
        if store.status().exists
        else _load_completed_point_in_time_materialization().breadth_snapshots
    )
    _emit_point_in_time_report(
        snapshots,
        output_format=output_format,
        output=output,
        rows=snapshots,
        renderer=render_breadth_snapshots,
        label="Point-in-time breadth",
    )


@replay_app.command(name="point-in-time-sector-state")
def replay_point_in_time_sector_state(
    market_date: str | None = typer.Option(None, "--date"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Build stock-aggregated sector state for one diagnostic date.
    """

    materialization = _load_completed_point_in_time_materialization()
    dataset = materialization.universe
    target = (
        _parse_date(market_date)
        if market_date is not None
        else min((row.market_date for row in dataset.rows), default=dt_date.today())
    )
    report = next(
        (
            item
            for item in materialization.sector_state_reports
            if item.market_date == target
        ),
        build_sector_state_report(
            dataset=dataset,
            price_repository=MarketTruthPriceRepository(),
            market_date=target,
        ),
    )
    _emit_point_in_time_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.sector_states,
        renderer=render_sector_state,
        label="Point-in-time sector state",
    )


@replay_app.command(name="survivorship-bias-audit")
def replay_survivorship_bias_audit(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Compare current-universe breadth with diagnostic point-in-time breadth.
    """

    store = PointInTimeAnalyticalRepository()
    report = (
        store.survivorship_audit()
        if store.status().exists
        else build_materialized_survivorship_bias_audit(
            materialization=_load_completed_point_in_time_materialization(),
            price_repository=MarketTruthPriceRepository(),
        )
    )
    _emit_point_in_time_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.rows,
        renderer=render_survivorship_bias,
        label="Survivorship-bias audit",
    )


@replay_app.command(name="diagnostic-market-state-v2-build")
def replay_diagnostic_market_state_v2_build(
    dry_run: bool = typer.Option(False, "--dry-run"),
    persist_diagnostic: bool = typer.Option(False, "--persist-diagnostic"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Prepare diagnostic market-state v2 lineage without modifying v1.
    """

    store = PointInTimeAnalyticalRepository()
    if store.status().exists:
        store_report = store.build_diagnostic_v2(
            records=NightlyLearningLoop.from_path().repository.load_records(),
            classifier_version=MARKET_STATE_CLASSIFIER_VERSION,
            classifier_fingerprint=current_market_classifier_fingerprint(),
            dry_run=dry_run,
            persist=persist_diagnostic,
        )
        _emit_point_in_time_report(
            store_report,
            output_format=output_format,
            output=output,
            rows=(store_report.report,),
            renderer=render_diagnostic_v2_store_build,
            label="Diagnostic market-state v2 build",
        )
        return
    materialization = _load_completed_point_in_time_materialization()
    dataset = materialization.universe
    report = build_diagnostic_v2_report(
        dataset=dataset,
        classifier_version=MARKET_STATE_CLASSIFIER_VERSION,
        classifier_fingerprint=current_market_classifier_fingerprint(),
        dry_run=dry_run or not persist_diagnostic,
    )
    _emit_point_in_time_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_diagnostic_v2_build,
        label="Diagnostic market-state v2 build",
    )


@replay_app.command(name="diagnostic-market-state-v1-v2-comparison")
def replay_diagnostic_market_state_v1_v2_comparison(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Compare diagnostic v1 and indexed diagnostic v2 market-state regimes.
    """

    report = _load_diagnostic_v2_validation_report()
    _emit_diagnostic_v2_validation_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.alignment_rows,
        renderer=render_diagnostic_v2_alignment,
        label="Diagnostic market-state v1 v2 comparison",
    )


@replay_app.command(name="diagnostic-market-state-v2-integrity")
def replay_diagnostic_market_state_v2_integrity(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Validate the frozen diagnostic v2 dataset identity and link integrity.
    """

    report = _load_diagnostic_v2_validation_report()
    _emit_diagnostic_v2_validation_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report.integrity,),
        renderer=render_diagnostic_v2_integrity,
        label="Diagnostic market-state v2 integrity",
    )


@replay_app.command(name="diagnostic-market-state-v2-outcomes")
def replay_diagnostic_market_state_v2_outcomes(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
    date_weighted: bool = typer.Option(False, "--date-weighted"),
) -> None:
    """
    Join diagnostic v2 market-state regimes to candidate outcomes.
    """

    report = _load_diagnostic_v2_validation_report()
    _emit_diagnostic_v2_validation_report(
        report,
        output_format=output_format,
        output=output,
        rows=(
            report.date_weighted_outcomes
            if date_weighted
            else report.candidate_weighted_outcomes
        ),
        renderer=lambda payload: render_diagnostic_v2_outcomes(
            payload,
            date_weighted=date_weighted,
        ),
        label="Diagnostic market-state v2 outcomes",
    )


@replay_app.command(name="diagnostic-market-state-v2-quality")
def replay_diagnostic_market_state_v2_quality(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Validate v2 regime outcomes by diagnostic quality slice.
    """

    _emit_diagnostic_v2_command(
        output_format=output_format,
        output=output,
        rows_attr="quality_conditioned_outcomes",
        renderer=render_diagnostic_v2_quality,
        label="Diagnostic market-state v2 quality",
    )


@replay_app.command(name="diagnostic-market-state-v2-intervention")
def replay_diagnostic_market_state_v2_intervention(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Compare diagnostic-only regime intervention variants.
    """

    _emit_diagnostic_v2_command(
        output_format=output_format,
        output=output,
        rows_attr="intervention_comparisons",
        renderer=render_diagnostic_v2_intervention,
        label="Diagnostic market-state v2 intervention",
    )


@replay_app.command(name="diagnostic-market-state-v2-threshold-stability")
def replay_diagnostic_market_state_v2_threshold_stability(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Audit diagnostic v2 threshold stability without changing thresholds.
    """

    _emit_diagnostic_v2_command(
        output_format=output_format,
        output=output,
        rows_attr="alignment_rows",
        renderer=render_diagnostic_v2_threshold_stability,
        label="Diagnostic market-state v2 threshold stability",
    )


@replay_app.command(name="diagnostic-market-state-v2-coherence")
def replay_diagnostic_market_state_v2_coherence(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Audit v2 market-state coherence and remaining limitations.
    """

    _emit_diagnostic_v2_command(
        output_format=output_format,
        output=output,
        rows_attr="alignment_rows",
        renderer=render_diagnostic_v2_coherence,
        label="Diagnostic market-state v2 coherence",
    )


@replay_app.command(name="diagnostic-market-state-v2-setup-regime")
def replay_diagnostic_market_state_v2_setup_regime(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Validate setup outcomes by v2 regime.
    """

    _emit_diagnostic_v2_command(
        output_format=output_format,
        output=output,
        rows_attr="setup_regime_findings",
        renderer=render_diagnostic_v2_setup_regime,
        label="Diagnostic market-state v2 setup regime",
    )


@replay_app.command(name="diagnostic-market-state-v2-retracement-regime")
def replay_diagnostic_market_state_v2_retracement_regime(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Validate retracement evidence behavior by v2 regime.
    """

    _emit_diagnostic_v2_command(
        output_format=output_format,
        output=output,
        rows_attr="candidate_weighted_outcomes",
        renderer=render_diagnostic_v2_retracement_regime,
        label="Diagnostic market-state v2 retracement regime",
    )


@replay_app.command(name="diagnostic-market-state-v2-selection-effect")
def replay_diagnostic_market_state_v2_selection_effect(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Show how candidate selection changes the observed v2 regime mix.
    """

    _emit_diagnostic_v2_command(
        output_format=output_format,
        output=output,
        rows_attr="candidate_selection_effect",
        renderer=render_diagnostic_v2_selection_effect,
        label="Diagnostic market-state v2 selection effect",
    )


@replay_app.command(name="diagnostic-market-state-v2-breadth-value")
def replay_diagnostic_market_state_v2_breadth_value(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Evaluate whether point-in-time breadth adds decision value in v2.
    """

    _emit_diagnostic_v2_command(
        output_format=output_format,
        output=output,
        rows_attr="comparison",
        renderer=render_diagnostic_v2_breadth_value,
        label="Diagnostic market-state v2 breadth value",
    )


@replay_app.command(name="diagnostic-market-state-v2-sector-materiality")
def replay_diagnostic_market_state_v2_sector_materiality(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Evaluate whether sector history is material to v2 decision readiness.
    """

    _emit_diagnostic_v2_command(
        output_format=output_format,
        output=output,
        rows_attr="readiness_scorecard",
        renderer=render_diagnostic_v2_sector_materiality,
        label="Diagnostic market-state v2 sector materiality",
    )


@replay_app.command(name="diagnostic-market-state-v2-readiness")
def replay_diagnostic_market_state_v2_readiness(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Produce the deterministic v2 decision-readiness conclusion.
    """

    _emit_diagnostic_v2_command(
        output_format=output_format,
        output=output,
        rows_attr="readiness_scorecard",
        renderer=render_diagnostic_v2_readiness,
        label="Diagnostic market-state v2 readiness",
    )


@replay_app.command(name="sector-incremental-value")
def replay_sector_incremental_value(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Audit sector incremental value after point-in-time sector coverage.
    """

    store = PointInTimeAnalyticalRepository()
    report = build_sector_incremental_value_report(
        store.sector_coverage()
        if store.status().exists
        else build_sector_coverage_audit(_load_completed_point_in_time_universe())
    )
    _emit_point_in_time_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_sector_incremental_value,
        label="Sector incremental value",
    )


@replay_app.command(name="sector-source-audit")
def replay_sector_source_audit(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Inventory local historical sector-classification evidence sources.
    """

    rows = HistoricalSectorIngestionEngine().source_inventory()
    _emit_historical_sector_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_sector_source_audit,
        label="Sector source audit",
    )


@replay_app.command(name="historical-sector-source-audit")
def replay_historical_sector_source_audit(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Audit external historical sector source acquisition feasibility.
    """

    report = HistoricalSectorSourceFeasibilityEngine().acquisition_decision()
    _emit_sector_source_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.matrix,
        renderer=render_sector_acquisition_decision,
        label="Historical sector source audit",
    )


@replay_app.command(name="regime-input-dependency-audit")
def replay_regime_input_dependency_audit(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeSimplificationAuditEngine()
    rows = engine.dependency_audit()
    _emit_regime_simplification_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_regime_input_dependency,
        label="Regime input dependency audit",
    )


@replay_app.command(name="simplified-regime-models")
def replay_simplified_regime_models(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeSimplificationAuditEngine()
    rows = engine.models()
    _emit_regime_simplification_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_simplified_regime_models,
        label="Simplified regime models",
    )


@replay_app.command(name="simplified-regime-distribution")
def replay_simplified_regime_distribution(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeSimplificationAuditEngine()
    rows = engine.distributions()
    _emit_regime_simplification_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_simplified_regime_distribution,
        label="Simplified regime distribution",
    )


@replay_app.command(name="simplified-regime-outcomes")
def replay_simplified_regime_outcomes(
    date_weighted: bool = typer.Option(False, "--date-weighted"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeSimplificationAuditEngine()
    rows = engine.outcomes(date_weighted=date_weighted)
    _emit_regime_simplification_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_simplified_regime_outcomes,
        label="Simplified regime outcomes",
    )


@replay_app.command(name="simplified-regime-quality")
def replay_simplified_regime_quality(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeSimplificationAuditEngine()
    rows = engine.quality()
    _emit_regime_simplification_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_simplified_regime_quality,
        label="Simplified regime quality",
    )


@replay_app.command(name="simplified-regime-threshold-stability")
def replay_simplified_regime_threshold_stability(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeSimplificationAuditEngine()
    rows = engine.threshold_stability()
    _emit_regime_simplification_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_simplified_regime_threshold_stability,
        label="Simplified regime threshold stability",
    )


@replay_app.command(name="simplified-regime-incremental-value")
def replay_simplified_regime_incremental_value(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeSimplificationAuditEngine()
    rows = engine.incremental_value()
    _emit_regime_simplification_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_simplified_regime_incremental_value,
        label="Simplified regime incremental value",
    )


@replay_app.command(name="simplified-regime-intervention")
def replay_simplified_regime_intervention(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeSimplificationAuditEngine()
    rows = engine.intervention()
    _emit_regime_simplification_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_simplified_regime_intervention,
        label="Simplified regime intervention",
    )


@replay_app.command(name="simplified-regime-setup-interaction")
def replay_simplified_regime_setup_interaction(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeSimplificationAuditEngine()
    rows = engine.setup_interaction()
    _emit_regime_simplification_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=lambda payload: render_regime_interactions(
            payload,
            "Simplified Regime Setup Interaction",
        ),
        label="Simplified regime setup interaction",
    )


@replay_app.command(name="simplified-regime-retracement-interaction")
def replay_simplified_regime_retracement_interaction(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeSimplificationAuditEngine()
    rows = engine.retracement_interaction()
    _emit_regime_simplification_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=lambda payload: render_regime_interactions(
            payload,
            "Simplified Regime Retracement Interaction",
        ),
        label="Simplified regime retracement interaction",
    )


@replay_app.command(name="simplified-regime-selection-effect")
def replay_simplified_regime_selection_effect(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeSimplificationAuditEngine()
    rows = engine.selection_effect()
    _emit_regime_simplification_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_simplified_regime_selection_effect,
        label="Simplified regime selection effect",
    )


@replay_app.command(name="simplified-regime-interpretability")
def replay_simplified_regime_interpretability(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeSimplificationAuditEngine()
    rows = engine.interpretability()
    _emit_regime_simplification_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_simplified_regime_interpretability,
        label="Simplified regime interpretability",
    )


@replay_app.command(name="sector-maximum-impact")
def replay_sector_maximum_impact(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeSimplificationAuditEngine()
    report = engine.sector_maximum_impact()
    _emit_regime_simplification_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_sector_maximum_impact,
        label="Sector maximum impact",
    )


@replay_app.command(name="regime-parsimony-decision")
def replay_regime_parsimony_decision(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeSimplificationAuditEngine()
    report = engine.parsimony_decision()
    _emit_regime_simplification_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.rows,
        renderer=render_regime_parsimony_decision,
        label="Regime parsimony decision",
    )


@replay_app.command(name="regime-production-dependency")
def replay_regime_production_dependency(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeProductionInfluenceAuditEngine()
    rows = engine.dependency_map()
    _emit_regime_influence_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_regime_production_dependency,
        label="Regime production dependency",
    )


@replay_app.command(name="regime-score-influence")
def replay_regime_score_influence(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeProductionInfluenceAuditEngine()
    rows = engine.score_influence()
    _emit_regime_influence_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_regime_score_influence,
        label="Regime score influence",
    )


@replay_app.command(name="regime-verdict-influence")
def replay_regime_verdict_influence(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeProductionInfluenceAuditEngine()
    rows = engine.verdict_influence()
    _emit_regime_influence_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_regime_verdict_influence,
        label="Regime verdict influence",
    )


@replay_app.command(name="regime-ranking-influence")
def replay_regime_ranking_influence(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeProductionInfluenceAuditEngine()
    rows = engine.ranking_influence()
    _emit_regime_influence_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_regime_ranking_influence,
        label="Regime ranking influence",
    )


@replay_app.command(name="regime-selection-influence")
def replay_regime_selection_influence(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeProductionInfluenceAuditEngine()
    rows = engine.selection_influence()
    _emit_regime_influence_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_regime_selection_influence,
        label="Regime selection influence",
    )


@replay_app.command(name="regime-approval-influence")
def replay_regime_approval_influence(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeProductionInfluenceAuditEngine()
    report = engine.approval_influence()
    _emit_regime_influence_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_regime_approval_influence,
        label="Regime approval influence",
    )


@replay_app.command(name="regime-allocation-influence")
def replay_regime_allocation_influence(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeProductionInfluenceAuditEngine()
    report = engine.allocation_influence()
    _emit_regime_influence_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_regime_allocation_influence,
        label="Regime allocation influence",
    )


@replay_app.command(name="regime-setup-influence")
def replay_regime_setup_influence(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeProductionInfluenceAuditEngine()
    rows = engine.setup_influence()
    _emit_regime_influence_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_regime_setup_influence,
        label="Regime setup influence",
    )


@replay_app.command(name="regime-asymmetry")
def replay_regime_asymmetry(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeProductionInfluenceAuditEngine()
    report = engine.asymmetry()
    _emit_regime_influence_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_regime_asymmetry,
        label="Regime asymmetry",
    )


@replay_app.command(name="recorded-vs-v2-regime-influence")
def replay_recorded_vs_v2_regime_influence(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeProductionInfluenceAuditEngine()
    report = engine.recorded_vs_v2()
    _emit_regime_influence_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_recorded_vs_v2_regime_influence,
        label="Recorded vs V2 regime influence",
    )


@replay_app.command(name="regime-context-only")
def replay_regime_context_only(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeProductionInfluenceAuditEngine()
    report = engine.context_only()
    _emit_regime_influence_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_regime_context_only,
        label="Regime context-only",
    )


@replay_app.command(name="regime-safe-deactivation-readiness")
def replay_regime_safe_deactivation_readiness(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeProductionInfluenceAuditEngine()
    report = engine.safe_deactivation_readiness()
    _emit_regime_influence_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_regime_safe_deactivation_readiness,
        label="Regime safe deactivation readiness",
    )


@replay_app.command(name="regime-shadow-build")
def replay_regime_shadow_build(
    persist_diagnostic: bool = typer.Option(False, "--persist-diagnostic"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeShadowEngine()
    result = engine.build(persist=persist_diagnostic)
    _emit_regime_shadow_report(
        result,
        output_format=output_format,
        output=output,
        rows=result.decisions,
        renderer=render_regime_shadow_build,
        label="Regime shadow build",
    )


@replay_app.command(name="regime-shadow-status")
def replay_regime_shadow_status(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeShadowEngine()
    report = engine.status()
    _emit_regime_shadow_report(
        report,
        output_format=output_format,
        output=output,
        rows=engine.shadow.load_decisions(),
        renderer=render_regime_shadow_status,
        label="Regime shadow status",
    )


@replay_app.command(name="regime-shadow-integrity")
def replay_regime_shadow_integrity(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeShadowEngine()
    report = engine.integrity()
    _emit_regime_shadow_report(
        report,
        output_format=output_format,
        output=output,
        rows=engine.shadow.load_decisions(),
        renderer=render_regime_shadow_integrity,
        label="Regime shadow integrity",
    )


@replay_app.command(name="regime-shadow-score-comparison")
def replay_regime_shadow_score_comparison(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeShadowEngine()
    rows = engine.score_comparison()
    _emit_regime_shadow_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_regime_shadow_score_comparison,
        label="Regime shadow score comparison",
    )


@replay_app.command(name="regime-shadow-verdict-comparison")
def replay_regime_shadow_verdict_comparison(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeShadowEngine()
    rows = engine.verdict_comparison()
    _emit_regime_shadow_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_regime_shadow_verdict_comparison,
        label="Regime shadow verdict comparison",
    )


@replay_app.command(name="regime-shadow-approval-comparison")
def replay_regime_shadow_approval_comparison(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeShadowEngine()
    rows = engine.approval_comparison()
    _emit_regime_shadow_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_regime_shadow_approval_comparison,
        label="Regime shadow approval comparison",
    )


@replay_app.command(name="regime-shadow-allocation-comparison")
def replay_regime_shadow_allocation_comparison(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeShadowEngine()
    rows = engine.allocation_comparison()
    _emit_regime_shadow_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_regime_shadow_approval_comparison,
        label="Regime shadow allocation comparison",
    )


@replay_app.command(name="regime-shadow-outcomes")
def replay_regime_shadow_outcomes(
    date_weighted: bool = typer.Option(False, "--date-weighted"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeShadowEngine()
    rows = engine.outcomes(date_weighted=date_weighted)
    _emit_regime_shadow_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_regime_shadow_outcomes,
        label="Regime shadow outcomes",
    )


@replay_app.command(name="regime-shadow-bearish-protection")
def replay_regime_shadow_bearish_protection(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeShadowEngine()
    report = engine.bearish_protection()
    _emit_regime_shadow_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_regime_shadow_bearish_protection,
        label="Regime shadow bearish protection",
    )


@replay_app.command(name="regime-shadow-bullish-promotion")
def replay_regime_shadow_bullish_promotion(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeShadowEngine()
    report = engine.bullish_promotion()
    _emit_regime_shadow_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_regime_shadow_bullish_promotion,
        label="Regime shadow bullish promotion",
    )


@replay_app.command(name="regime-shadow-setup-attribution")
def replay_regime_shadow_setup_attribution(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeShadowEngine()
    rows = engine.setup_attribution()
    _emit_regime_shadow_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_regime_shadow_setup_attribution,
        label="Regime shadow setup attribution",
    )


@replay_app.command(name="regime-shadow-quality")
def replay_regime_shadow_quality(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeShadowEngine()
    rows = engine.quality()
    _emit_regime_shadow_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_regime_shadow_quality,
        label="Regime shadow quality",
    )


@replay_app.command(name="regime-shadow-temporal-stability")
def replay_regime_shadow_temporal_stability(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeShadowEngine()
    rows = engine.temporal_stability()
    _emit_regime_shadow_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_regime_shadow_temporal_stability,
        label="Regime shadow temporal stability",
    )


@replay_app.command(name="regime-shadow-readiness")
def replay_regime_shadow_readiness(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = RegimeShadowEngine()
    report = engine.readiness()
    _emit_regime_shadow_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.decision_matrix,
        renderer=render_regime_shadow_readiness,
        label="Regime shadow readiness",
    )


@replay_app.command(name="regime-shadow-live-status")
def replay_regime_shadow_live_status(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    report = engine.status()
    _emit_live_regime_shadow_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_live_shadow_status,
        label="Live regime shadow status",
    )


@replay_app.command(name="regime-shadow-observation-coverage")
def replay_regime_shadow_observation_coverage(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    rows = engine.coverage()
    _emit_live_regime_shadow_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_live_regime_shadow_coverage,
        label="Live regime shadow observation coverage",
    )


@replay_app.command(name="regime-shadow-outcome-maturity")
def replay_regime_shadow_outcome_maturity(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    rows = engine.outcome_maturity()
    _emit_live_regime_shadow_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_live_regime_shadow_outcome_maturity,
        label="Live regime shadow outcome maturity",
    )


@replay_app.command(name="regime-shadow-outcome-refresh")
def replay_regime_shadow_outcome_refresh(
    persist_diagnostic: bool = typer.Option(False, "--persist-diagnostic"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    report = engine.refresh_outcomes(persist=persist_diagnostic)
    _emit_live_regime_shadow_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_live_regime_shadow_refresh,
        label="Live regime shadow outcome refresh",
    )


@replay_app.command(name="regime-shadow-policy-differences")
def replay_regime_shadow_policy_differences(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    rows = engine.policy_differences()
    _emit_live_regime_shadow_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_live_regime_shadow_policy_differences,
        label="Live regime shadow policy differences",
    )


@replay_app.command(name="regime-shadow-live-bearish-protection")
def replay_regime_shadow_live_bearish_protection(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    report = engine.bearish_protection()
    _emit_live_regime_shadow_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_live_regime_shadow_bearish_protection,
        label="Live regime shadow bearish protection",
    )


@replay_app.command(name="regime-shadow-live-context-harm")
def replay_regime_shadow_live_context_harm(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    report = engine.context_harm()
    _emit_live_regime_shadow_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_live_regime_shadow_context_harm,
        label="Live regime shadow context harm",
    )


@replay_app.command(name="regime-shadow-live-downstream-guardrails")
def replay_regime_shadow_live_downstream_guardrails(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    report = engine.downstream_guardrails()
    _emit_live_regime_shadow_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_live_regime_shadow_guardrails,
        label="Live regime shadow downstream guardrails",
    )


@replay_app.command(name="regime-shadow-live-quality")
def replay_regime_shadow_live_quality(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    rows = engine.quality()
    _emit_live_regime_shadow_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_live_regime_shadow_coverage,
        label="Live regime shadow quality",
    )


@replay_app.command(name="regime-shadow-live-temporal")
def replay_regime_shadow_live_temporal(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    rows = engine.temporal()
    _emit_live_regime_shadow_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_live_regime_shadow_temporal,
        label="Live regime shadow temporal",
    )


@replay_app.command(name="regime-shadow-live-setup")
def replay_regime_shadow_live_setup(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    rows = engine.setup()
    _emit_live_regime_shadow_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_live_regime_shadow_setup,
        label="Live regime shadow setup",
    )


@replay_app.command(name="regime-shadow-live-drift")
def replay_regime_shadow_live_drift(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    report = engine.drift()
    _emit_live_regime_shadow_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_live_regime_shadow_drift,
        label="Live regime shadow drift",
    )


@replay_app.command(name="regime-shadow-review-checkpoint")
def replay_regime_shadow_review_checkpoint(
    persist_diagnostic: bool = typer.Option(False, "--persist-diagnostic"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    report = engine.review_checkpoint(persist=persist_diagnostic)
    _emit_live_regime_shadow_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_live_regime_shadow_review,
        label="Live regime shadow review checkpoint",
    )


@replay_app.command(name="regime-shadow-live-readiness")
def replay_regime_shadow_live_readiness(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    report = engine.readiness()
    _emit_live_regime_shadow_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.coverage,
        renderer=render_live_regime_shadow_readiness,
        label="Live regime shadow readiness",
    )


@replay_app.command(name="regime-shadow-runtime-coverage")
def replay_regime_shadow_runtime_coverage(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    rows = engine.runtime_coverage()
    _emit_live_regime_shadow_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_live_regime_shadow_runtime_coverage,
        label="Live regime shadow runtime coverage",
    )


@replay_app.command(name="regime-shadow-alpha-live-wiring")
def replay_regime_shadow_alpha_live_wiring(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    alpha_live = next(
        row for row in engine.runtime_coverage() if row.runtime_path == "alpha live"
    )
    health = engine.capture_health()
    conclusion = (
        "ALPHA_LIVE_SHADOW_WIRING_COMPLETE"
        if alpha_live.status.value == "WIRED_AND_TESTED"
        else "ALPHA_LIVE_SHADOW_WIRING_INCOMPLETE"
    )
    payload = {
        "runtime_path": alpha_live.runtime_path,
        "status": alpha_live.status.value,
        "implementation_wired": alpha_live.implementation_wired,
        "provider_validated": alpha_live.provider_validated,
        "candidate_path_validated": alpha_live.candidate_path_validated,
        "shadow_capture_validated": alpha_live.shadow_capture_validated,
        "authoritative_decision_created": alpha_live.authoritative_decision_created,
        "candidate_persisted": alpha_live.candidate_persisted,
        "market_state_snapshot_available": (alpha_live.market_state_snapshot_available),
        "shadow_capture_invoked": alpha_live.shadow_capture_invoked,
        "eligible_for_live_observation": alpha_live.eligible_for_live_observation,
        "eligible_live_decisions": health.eligible_authoritative_decisions,
        "complete_observations": health.captured_observations,
        "duplicate_attempts": health.duplicate_attempts,
        "input_parity_failures": health.input_parity_failures,
        "evaluation_failures": health.evaluation_failures,
        "persistence_failures": health.persistence_failures,
        "primary_conclusion": conclusion,
    }

    def _render_alpha_live_wiring(report: dict[str, object]) -> tuple[str, ...]:
        return (
            "Live Regime Shadow Alpha Live Wiring",
            f"Runtime Path: {report['runtime_path']}",
            f"Status: {report['status']}",
            f"Implementation Wired: {report['implementation_wired']}",
            f"Provider Validated: {report['provider_validated']}",
            f"Candidate Path Validated: {report['candidate_path_validated']}",
            f"Shadow Capture Validated: {report['shadow_capture_validated']}",
            "Authoritative Candidate Created: "
            f"{report['authoritative_decision_created']}",
            f"Candidate Persisted: {report['candidate_persisted']}",
            "Market-State Snapshot Available: "
            f"{report['market_state_snapshot_available']}",
            f"Shadow Capture Invoked: {report['shadow_capture_invoked']}",
            f"Eligible Live Decisions: {report['eligible_live_decisions']}",
            f"Complete Observations: {report['complete_observations']}",
            f"Duplicate Attempts: {report['duplicate_attempts']}",
            f"Input Parity Failures: {report['input_parity_failures']}",
            f"Evaluation Failures: {report['evaluation_failures']}",
            f"Persistence Failures: {report['persistence_failures']}",
            f"Primary Conclusion: {report['primary_conclusion']}",
        )

    _emit_live_regime_shadow_report(
        payload,
        output_format=output_format,
        output=output,
        rows=(payload,),
        renderer=_render_alpha_live_wiring,
        label="Live regime shadow alpha live wiring",
    )


@replay_app.command(name="regime-shadow-capture-health")
def replay_regime_shadow_capture_health(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    report = engine.capture_health()
    _emit_live_regime_shadow_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_live_regime_shadow_capture_health,
        label="Live regime shadow capture health",
    )


@replay_app.command(name="regime-shadow-capture-failures")
def replay_regime_shadow_capture_failures(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    rows = engine.capture_failures()
    _emit_live_regime_shadow_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_live_regime_shadow_capture_failures,
        label="Live regime shadow capture failures",
    )


@replay_app.command(name="regime-shadow-capture-manifests")
def replay_regime_shadow_capture_manifests(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    rows = engine.capture_manifests()
    _emit_live_regime_shadow_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_live_regime_shadow_capture_manifests,
        label="Live regime shadow capture manifests",
    )


@replay_app.command(name="regime-shadow-live-repair")
def replay_regime_shadow_live_repair(
    persist_diagnostic: bool = typer.Option(False, "--persist-diagnostic"),
    candidate_id: str | None = typer.Option(None, "--candidate-id"),
    failure_category: str | None = typer.Option(None, "--failure-category"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    report = engine.repair(
        persist=persist_diagnostic,
        candidate_id=candidate_id,
        failure_category=failure_category,
    )
    _emit_live_regime_shadow_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_live_regime_shadow_repair,
        label="Live regime shadow repair",
    )


@replay_app.command(name="regime-shadow-input-parity")
def replay_regime_shadow_input_parity(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    report = engine.input_parity()
    _emit_live_regime_shadow_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_live_regime_shadow_input_parity,
        label="Live regime shadow input parity",
    )


@replay_app.command(name="regime-shadow-operational-readiness")
def replay_regime_shadow_operational_readiness(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    engine = LiveRegimeShadowEvidenceEngine()
    report = engine.operational_readiness()
    _emit_live_regime_shadow_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.matrix,
        renderer=render_live_regime_shadow_operational_readiness,
        label="Live regime shadow operational readiness",
    )


@replay_app.command(name="historical-sector-source-list")
def replay_historical_sector_source_list(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    List historical sector source candidates.
    """

    rows = HistoricalSectorSourceFeasibilityEngine().source_candidates()
    _emit_sector_source_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_sector_source_candidates,
        label="Historical sector source list",
    )


@replay_app.command(name="historical-sector-source-show")
def replay_historical_sector_source_show(
    source: str = typer.Option(..., "--source"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Show one historical sector source candidate.
    """

    candidate = HistoricalSectorSourceFeasibilityEngine().get_source(source)
    _emit_sector_source_report(
        candidate,
        output_format=output_format,
        output=output,
        rows=(candidate,),
        renderer=render_sector_source_show,
        label="Historical sector source show",
    )


@replay_app.command(name="historical-sector-source-sample")
def replay_historical_sector_source_sample(
    source: str = typer.Option(..., "--source"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Parse a permitted sample for one source without persisting classifications.
    """

    report = HistoricalSectorSourceFeasibilityEngine().sample_source(source)
    _emit_sector_source_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_sector_source_sample,
        label="Historical sector source sample",
    )


@replay_app.command(name="historical-sector-source-identity-test")
def replay_historical_sector_source_identity_test(
    source: str = typer.Option(..., "--source"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Test representative identity joinability for one source.
    """

    report = HistoricalSectorSourceFeasibilityEngine().identity_test(source)
    _emit_sector_source_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_sector_source_identity,
        label="Historical sector source identity test",
    )


@replay_app.command(name="historical-sector-source-coverage")
def replay_historical_sector_source_coverage(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Estimate candidate-date coverage from source metadata.
    """

    rows = HistoricalSectorSourceFeasibilityEngine().coverage_estimates()
    _emit_sector_source_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_sector_source_coverage,
        label="Historical sector source coverage",
    )


@replay_app.command(name="historical-sector-source-taxonomy")
def replay_historical_sector_source_taxonomy(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Audit taxonomy stability for source candidates.
    """

    rows = HistoricalSectorSourceFeasibilityEngine().taxonomy_audit()
    _emit_sector_source_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_sector_source_taxonomy,
        label="Historical sector source taxonomy",
    )


@replay_app.command(name="historical-sector-source-licensing")
def replay_historical_sector_source_licensing(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Audit licensing and operational feasibility for source candidates.
    """

    rows = HistoricalSectorSourceFeasibilityEngine().licensing_audit()
    _emit_sector_source_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_sector_source_licensing,
        label="Historical sector source licensing",
    )


@replay_app.command(name="historical-sector-source-value")
def replay_historical_sector_source_value(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Estimate structural sensitivity to sector-state availability.
    """

    report = HistoricalSectorSourceFeasibilityEngine().sector_necessity()
    _emit_sector_source_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_sector_source_value,
        label="Historical sector source value",
    )


@replay_app.command(name="historical-sector-source-combinations")
def replay_historical_sector_source_combinations(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Evaluate safe and unsafe multi-source reconstruction combinations.
    """

    rows = HistoricalSectorSourceFeasibilityEngine().source_combinations()
    _emit_sector_source_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_sector_source_combinations,
        label="Historical sector source combinations",
    )


@replay_app.command(name="historical-sector-acquisition-decision")
def replay_historical_sector_acquisition_decision(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Render the deterministic historical sector acquisition decision matrix.
    """

    report = HistoricalSectorSourceFeasibilityEngine().acquisition_decision()
    _emit_sector_source_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.matrix,
        renderer=render_sector_acquisition_decision,
        label="Historical sector acquisition decision",
    )


@replay_app.command(name="sector-taxonomy-list")
def replay_sector_taxonomy_list(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    List explicit sector taxonomies known to Alpha.
    """

    rows = default_sector_taxonomies()
    _emit_historical_sector_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_sector_taxonomies,
        label="Sector taxonomy list",
    )


@replay_app.command(name="historical-sector-build")
def replay_historical_sector_build(
    persist_diagnostic: bool = typer.Option(False, "--persist-diagnostic"),
    resume: bool = typer.Option(False, "--resume"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Build the diagnostic historical-sector dataset; dry-run by default.
    """

    report = HistoricalSectorIngestionEngine().build(
        persist=persist_diagnostic,
        resume=resume,
    )
    _emit_historical_sector_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.classifications,
        renderer=render_historical_sector_build,
        label="Historical sector build",
    )


@replay_app.command(name="historical-sector-build-status")
def replay_historical_sector_build_status(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Show the latest historical-sector build manifest.
    """

    manifest = HistoricalSectorRepository().latest_manifest()
    _emit_historical_sector_report(
        manifest,
        output_format=output_format,
        output=output,
        rows=() if manifest is None else (manifest,),
        renderer=render_historical_sector_status,
        label="Historical sector build status",
    )


@replay_app.command(name="historical-sector-store-validate")
def replay_historical_sector_store_validate(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Validate historical-sector store integrity and no-look-ahead readiness.
    """

    report = validate_historical_sector_store()
    _emit_historical_sector_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_historical_sector_validation,
        label="Historical sector store validation",
    )


@replay_app.command(name="historical-sector-coverage")
def replay_historical_sector_coverage(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Report candidate-date sector coverage by authority class.
    """

    rows = HistoricalSectorRepository().get_sector_coverage()
    _emit_historical_sector_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_historical_sector_coverage,
        label="Historical sector coverage",
    )


@replay_app.command(name="historical-sector-conflicts")
def replay_historical_sector_conflicts(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Show preserved historical-sector classification conflicts.
    """

    rows = HistoricalSectorRepository().get_conflicts()
    _emit_historical_sector_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_historical_sector_conflicts,
        label="Historical sector conflicts",
    )


@replay_app.command(name="historical-sector-changes")
def replay_historical_sector_changes(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Show detected sector classification changes.
    """

    rows = HistoricalSectorRepository().get_changes()
    _emit_historical_sector_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=render_historical_sector_changes,
        label="Historical sector changes",
    )


@replay_app.command(name="historical-sector-show")
def replay_historical_sector_show(
    symbol: str = typer.Option(..., "--symbol"),
    date_value: str = typer.Option(..., "--date"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Show sector classification history for a symbol as of a date.
    """

    market_date = _parse_date(date_value)
    rows = HistoricalSectorRepository().load_classifications()
    _emit_historical_sector_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=lambda payload: render_historical_sector_show(
            payload,
            symbol=symbol,
            market_date=market_date,
        ),
        label="Historical sector show",
    )


@replay_app.command(name="historical-sector-state")
def replay_historical_sector_state(
    date_value: str = typer.Option(..., "--date"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Show historical sector state for a date when effective-dated evidence exists.
    """

    market_date = _parse_date(date_value)
    rows = HistoricalSectorRepository().get_sector_state(market_date=market_date)
    _emit_historical_sector_report(
        rows,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=lambda payload: render_historical_sector_state(
            payload,
            market_date=market_date,
        ),
        label="Historical sector state",
    )


@replay_app.command(name="diagnostic-market-state-v3-build")
def replay_diagnostic_market_state_v3_build(
    persist_diagnostic: bool = typer.Option(False, "--persist-diagnostic"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Prepare diagnostic market-state v3 without modifying v2.
    """

    report = DiagnosticMarketStateV3Engine().build(
        classifier_version=MARKET_STATE_CLASSIFIER_VERSION,
        classifier_fingerprint=current_market_classifier_fingerprint(),
        persist=persist_diagnostic,
    )
    _emit_historical_sector_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_diagnostic_v3_build,
        label="Diagnostic market-state v3 build",
    )


@replay_app.command(name="diagnostic-market-state-v2-v3-comparison")
def replay_diagnostic_market_state_v2_v3_comparison(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Compare diagnostic v2 with sector-aware diagnostic v3 readiness.
    """

    report = DiagnosticMarketStateV3Engine().compare_v2_v3()
    _emit_historical_sector_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report,),
        renderer=render_v2_v3_comparison,
        label="Diagnostic market-state v2 v3 comparison",
    )


@replay_app.command(name="diagnostic-market-state-v3-readiness")
def replay_diagnostic_market_state_v3_readiness(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Produce the sector-aware v3 decision-readiness scorecard.
    """

    report = build_historical_sector_readiness()
    _emit_historical_sector_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.scorecard,
        renderer=render_historical_sector_decision_readiness,
        label="Diagnostic market-state v3 readiness",
    )


@replay_app.command(name="point-in-time-history-readiness")
def replay_point_in_time_history_readiness(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Print overall point-in-time history readiness.
    """

    store = PointInTimeAnalyticalRepository()
    if store.status().exists:
        coverage = store.universe_coverage()
        sector = store.sector_coverage()
        survivorship = store.survivorship_audit()
    else:
        materialization = _load_completed_point_in_time_materialization()
        dataset = materialization.universe
        coverage = build_universe_coverage_report(dataset)
        sector = build_sector_coverage_audit(dataset)
        survivorship = build_materialized_survivorship_bias_audit(
            materialization=materialization,
            price_repository=MarketTruthPriceRepository(),
        )
    payload = {
        "coverage": coverage,
        "sector": sector,
        "survivorship": survivorship,
    }
    _emit_point_in_time_report(
        payload,
        output_format=output_format,
        output=output,
        rows=(coverage, sector),
        renderer=lambda _: render_point_in_time_history_readiness(
            coverage,
            sector,
            survivorship,
        ),
        label="Point-in-time history readiness",
    )


@replay_app.command(name="reconstructed-regime-outcomes")
def replay_reconstructed_regime_outcomes(
    group_by: str | None = typer.Option(None, "--group-by"),
    date_weighted: bool = typer.Option(False, "--date-weighted"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Research-only reconstructed regime outcome separation audit.
    """

    if group_by not in {None, "regime", "quality"}:
        raise typer.BadParameter("group-by must be regime or quality.")
    report = _diagnostic_threshold_readiness_report()
    _emit_diagnostic_outcome_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.quality_conditioned_outcomes
        if group_by == "quality"
        else report.date_weighted_regime_outcomes
        if date_weighted
        else report.candidate_weighted_regime_outcomes,
        renderer=lambda item: render_regime_outcomes(
            item,
            group_by=group_by,
            date_weighted=date_weighted,
        ),
        label="Reconstructed regime outcomes",
    )


@replay_app.command(name="reconstructed-regime-intervention")
def replay_reconstructed_regime_intervention(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Research-only regime intervention counterfactual audit.
    """

    report = _diagnostic_threshold_readiness_report()
    _emit_diagnostic_outcome_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.intervention_comparisons,
        renderer=render_regime_intervention,
        label="Reconstructed regime intervention",
    )


@replay_app.command(name="reconstructed-regime-threshold-density")
def replay_reconstructed_regime_threshold_density(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Research-only threshold boundary density audit.
    """

    report = _diagnostic_threshold_readiness_report()
    _emit_diagnostic_outcome_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.threshold_density,
        renderer=render_threshold_density,
        label="Reconstructed regime threshold density",
    )


@replay_app.command(name="reconstructed-regime-threshold-stability")
def replay_reconstructed_regime_threshold_stability(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Research-only threshold perturbation stability audit.
    """

    report = _diagnostic_threshold_readiness_report()
    _emit_diagnostic_outcome_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.threshold_perturbations,
        renderer=render_threshold_stability,
        label="Reconstructed regime threshold stability",
    )


@replay_app.command(name="reconstructed-regime-coherence")
def replay_reconstructed_regime_coherence(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Research-only reconstructed regime label coherence audit.
    """

    report = _diagnostic_threshold_readiness_report()
    _emit_diagnostic_outcome_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.coherence_exceptions,
        renderer=render_regime_coherence,
        label="Reconstructed regime coherence",
    )


@replay_app.command(name="reconstructed-regime-episodes")
def replay_reconstructed_regime_episodes(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Research-only reconstructed regime episode audit.
    """

    report = _diagnostic_threshold_readiness_report()
    _emit_diagnostic_outcome_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.regime_episodes,
        renderer=render_regime_episodes,
        label="Reconstructed regime episodes",
    )


@replay_app.command(name="reconstructed-setup-regime")
def replay_reconstructed_setup_regime(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Research-only setup and reconstructed-regime interaction audit.
    """

    report = _diagnostic_threshold_readiness_report()
    _emit_diagnostic_outcome_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.setup_regime_interactions,
        renderer=render_setup_regime,
        label="Reconstructed setup-regime interaction",
    )


@replay_app.command(name="reconstructed-retracement-regime")
def replay_reconstructed_retracement_regime(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Research-only retracement and reconstructed-regime interaction audit.
    """

    report = _diagnostic_threshold_readiness_report()
    _emit_diagnostic_outcome_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.retracement_regime_interactions,
        renderer=render_retracement_regime,
        label="Reconstructed retracement-regime interaction",
    )


@replay_app.command(name="reconstructed-selection-effect")
def replay_reconstructed_selection_effect(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Research-only candidate-selection distribution by reconstructed market state.
    """

    report = _diagnostic_threshold_readiness_report()
    _emit_diagnostic_outcome_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.selection_effects,
        renderer=render_selection_effect,
        label="Reconstructed selection effect",
    )


@replay_app.command(name="reconstructed-breadth-sensitivity")
def replay_reconstructed_breadth_sensitivity(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Research-only breadth-bias sensitivity audit.
    """

    report = _diagnostic_threshold_readiness_report()
    _emit_diagnostic_outcome_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.breadth_sensitivity,
        renderer=render_breadth_sensitivity,
        label="Reconstructed breadth sensitivity",
    )


@replay_app.command(name="reconstructed-sector-sensitivity")
def replay_reconstructed_sector_sensitivity(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Research-only missing sector sensitivity audit.
    """

    report = _diagnostic_threshold_readiness_report()
    _emit_diagnostic_outcome_report(
        report,
        output_format=output_format,
        output=output,
        rows=(report.sector_sensitivity,),
        renderer=render_sector_sensitivity,
        label="Reconstructed sector sensitivity",
    )


@replay_app.command(name="regime-threshold-readiness")
def replay_regime_threshold_readiness(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Conservative threshold-audit readiness scorecard.
    """

    report = _diagnostic_threshold_readiness_report()
    _emit_diagnostic_outcome_report(
        report,
        output_format=output_format,
        output=output,
        rows=report.readiness_scorecard,
        renderer=render_threshold_readiness,
        label="Regime threshold readiness",
    )


@replay_app.command(name="entry-timing-failures")
def replay_entry_timing_failures(
    entry_state: str | None = typer.Option(None, "--entry-state"),
    setup_type: str | None = typer.Option(None, "--setup-type"),
    market_regime: str | None = typer.Option(None, "--market-regime"),
    profitable_only: bool = typer.Option(False, "--profitable-only"),
    unprofitable_only: bool = typer.Option(False, "--unprofitable-only"),
    extended_only: bool = typer.Option(False, "--extended-only"),
    late_only: bool = typer.Option(False, "--late-only"),
    preferred_only: bool = typer.Option(False, "--preferred-only"),
    confirmation_only: bool = typer.Option(False, "--confirmation-only"),
    symbol: str | None = typer.Option(None, "--symbol"),
    from_date: str | None = typer.Option(None, "--from-date"),
    to_date: str | None = typer.Option(None, "--to-date"),
    minimum_return: str | None = typer.Option(None, "--minimum-return"),
    minimum_mfe: str | None = typer.Option(None, "--minimum-mfe"),
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """
    Inspect candidate-level entry timing assessments and outcomes.
    """

    rows = filter_entry_timing_rows(
        _entry_timing_report().rows,
        entry_state=entry_state,
        setup_type=setup_type,
        market_regime=market_regime,
        profitable_only=profitable_only,
        unprofitable_only=unprofitable_only,
        extended_only=extended_only,
        late_only=late_only,
        preferred_only=preferred_only,
        confirmation_only=confirmation_only,
        symbol=symbol,
        from_date=_parse_date(from_date) if from_date else None,
        to_date=_parse_date(to_date) if to_date else None,
        minimum_return=_parse_decimal(minimum_return)
        if minimum_return is not None
        else None,
        minimum_mfe=_parse_decimal(minimum_mfe) if minimum_mfe is not None else None,
    )
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_entry_timing_failures_json(rows, output)
        print(f"Entry timing candidates written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_entry_timing_failures_csv(rows, output)
        print(f"Entry timing candidates written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in render_entry_timing_failures(rows):
        print(line)


@market_state_app.command(name="benchmark")
def market_state_benchmark() -> None:
    print()
    for line in render_benchmark_configuration(canonical_benchmark_configuration()):
        print(line)


@market_state_app.command(name="benchmark-history")
def market_state_benchmark_history() -> None:
    report = benchmark_history_audit(
        repository=MarketTruthPriceRepository(),
        configuration=canonical_benchmark_configuration(),
    )
    print()
    for line in render_benchmark_history(report):
        print(line)


@market_state_app.command(name="benchmark-coverage")
def market_state_benchmark_coverage(
    output_format: str = typer.Option("text", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    report = _benchmark_coverage_report()
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_benchmark_coverage_json(report, output)
        print(f"Benchmark coverage written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_benchmark_coverage_csv(report, output)
        print(f"Benchmark coverage written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in render_benchmark_coverage(report):
        print(line)


@market_state_app.command(name="completeness")
def market_state_completeness() -> None:
    snapshots = MarketStateSnapshotRepository().load_all()
    print()
    for line in render_benchmark_completeness(snapshots):
        print(line)


@market_state_app.command(name="latest")
def market_state_latest() -> None:
    snapshot = MarketStateSnapshotRepository().latest()
    if snapshot is None:
        _exit_with_error(
            "Market state unavailable",
            ProjectAlphaError(
                "No authoritative market-state snapshots have been stored."
            ),
        )
        raise typer.Exit(code=1)
    print()
    for line in render_market_state_snapshot(snapshot):
        print(line)


@market_state_app.command(name="show")
def market_state_show(snapshot_id: str = typer.Option(..., "--snapshot-id")) -> None:
    snapshot = MarketStateSnapshotRepository().get(snapshot_id)
    if snapshot is None:
        _exit_with_error(
            "Market state unavailable",
            ProjectAlphaError(f"Snapshot not found: {snapshot_id}"),
        )
        raise typer.Exit(code=1)
    print()
    for line in render_market_state_snapshot(snapshot):
        print(line)


@market_state_app.command(name="history")
def market_state_history(
    from_date: str | None = typer.Option(None, "--from"),
    to_date: str | None = typer.Option(None, "--to"),
) -> None:
    repository = MarketStateSnapshotRepository()
    snapshots = repository.find_range(
        from_date=None if from_date is None else dt_date.fromisoformat(from_date),
        to_date=None if to_date is None else dt_date.fromisoformat(to_date),
    )
    print()
    for line in render_market_state_history(snapshots):
        print(line)


@market_state_app.command(name="coverage")
def market_state_coverage() -> None:
    print()
    coverage = MarketStateSnapshotRepository().coverage()
    for line in render_market_state_coverage(coverage):
        print(line)


@market_state_app.command(name="lineage")
def market_state_lineage(snapshot_id: str = typer.Option(..., "--snapshot-id")) -> None:
    snapshot = MarketStateSnapshotRepository().get(snapshot_id)
    if snapshot is None:
        _exit_with_error(
            "Market state unavailable",
            ProjectAlphaError(f"Snapshot not found: {snapshot_id}"),
        )
        raise typer.Exit(code=1)
    print()
    for line in render_market_state_lineage(snapshot):
        print(line)


@provenance_app.command(name="current")
def provenance_current() -> None:
    """
    Print current runtime analytical provenance without writing it.
    """

    provenance = capture_current_provenance(
        created_at=datetime.now(UTC),
        runtime_command="provenance current",
        runtime_mode=None,
        source="alpha-cli-diagnostic",
    )
    print()
    for line in render_current_provenance(provenance):
        print(line)


@provenance_app.command(name="show")
def provenance_show(
    provenance_id: str = typer.Option(..., "--provenance-id"),
) -> None:
    """
    Show one persisted decision-provenance record.
    """

    provenance = DecisionProvenanceRepository().get(provenance_id)
    if provenance is None:
        raise typer.BadParameter(f"Unknown provenance id: {provenance_id}")
    print()
    for line in render_current_provenance(provenance):
        print(line)


@provenance_app.command(name="history")
def provenance_history() -> None:
    """
    Print persisted decision-provenance history.
    """

    print()
    for line in render_provenance_history(DecisionProvenanceRepository().load_all()):
        print(line)


@provenance_app.command(name="components")
def provenance_components() -> None:
    """
    Print centralized analytical component versions and fingerprints.
    """

    print()
    for line in render_component_registry(current_component_registry()):
        print(line)


@provenance_app.command(name="coverage")
def provenance_coverage() -> None:
    """
    Print provenance coverage across candidates and market-state snapshots.
    """

    repository = NightlyLearningLoop.from_path().repository
    print()
    for line in render_provenance_coverage(
        records=repository.load_records(),
        snapshots=MarketStateSnapshotRepository().load_all(),
        provenances=DecisionProvenanceRepository().load_all(),
    ):
        print(line)


@provenance_manifest_app.callback()
def provenance_manifest(ctx: typer.Context) -> None:
    """
    Print the reviewed analytical release manifest.
    """

    if ctx.invoked_subcommand is not None:
        return
    report = _historical_manifest_audit_report()
    print()
    for line in render_analytical_release_manifest(report.manifest):
        print(line)


@provenance_manifest_app.command(name="show")
def provenance_manifest_show(
    era_id: str = typer.Option(..., "--era-id"),
) -> None:
    """
    Show one analytical release manifest entry.
    """

    report = _historical_manifest_audit_report()
    entry = next(
        (
            item
            for item in report.manifest.entries
            if item.manifest_entry_id == era_id.strip()
        ),
        None,
    )
    if entry is None:
        raise typer.BadParameter(f"Unknown manifest era id: {era_id}")
    print()
    for line in render_analytical_release_manifest_entry(entry):
        print(line)


@provenance_manifest_app.command(name="validate")
def provenance_manifest_validate() -> None:
    """
    Validate analytical release manifest evidence and exactness rules.
    """

    report = _historical_manifest_audit_report()
    print()
    for line in render_manifest_validation(report.manifest):
        print(line)


@provenance_app.command(name="eras")
def provenance_eras() -> None:
    """
    Print reviewed historical analytical eras.
    """

    report = _historical_manifest_audit_report()
    print()
    for line in render_historical_analytical_eras(report.eras):
        print(line)


@provenance_app.command(name="evidence")
def provenance_evidence() -> None:
    """
    Print reviewed historical release evidence.
    """

    report = _historical_manifest_audit_report()
    print()
    for line in render_historical_release_evidence(report.evidence):
        print(line)


@replay_app.command(name="similar-patterns")
def replay_similar_patterns(
    symbol: str = typer.Option(..., "--symbol"),
    years: int = typer.Option(10, "--years"),
    as_of: str = typer.Option("today", "--as-of"),
    min_similarity: str = typer.Option("70", "--min-similarity"),
    top: int = typer.Option(10, "--top"),
) -> None:
    """
    Scan local price history for technically similar past patterns.
    """

    target_date = dt_date.today() if as_of == "today" else _parse_date(as_of)
    try:
        similarity_threshold = Decimal(min_similarity)
    except InvalidOperation as exc:
        raise typer.BadParameter("min-similarity must be numeric") from exc
    report = SimilarPatternScanner(
        price_repository=MarketTruthPriceRepository(),
    ).scan(
        symbol=symbol,
        as_of=target_date,
        years=years,
        minimum_similarity=similarity_threshold,
        top=top,
    )
    print()
    for line in render_similar_pattern_report(report):
        print(line)


@replay_app.command(name="coverage")
def replay_coverage(
    symbol: list[str] = typer.Option(..., "--symbol"),
    years: int = typer.Option(10, "--years"),
    as_of: str = typer.Option("today", "--as-of"),
) -> None:
    """
    Explain local historical data depth before relying on replay evidence.
    """

    target_date = dt_date.today() if as_of == "today" else _parse_date(as_of)
    report = HistoricalDataCoverageAnalyzer(
        price_repository=MarketTruthPriceRepository(),
    ).analyze(symbols=tuple(symbol), as_of=target_date, years=years)
    print()
    for line in render_data_coverage_report(report):
        print(line)


@replay_app.command(name="walk-forward")
def replay_walk_forward(
    train_start: str = typer.Option(..., "--train-start"),
    train_end: str = typer.Option(..., "--train-end"),
    validate_start: str = typer.Option(..., "--validate-start"),
    validate_end: str = typer.Option(..., "--validate-end"),
    step: str = typer.Option("yearly", "--step"),
    min_sample_size: int = typer.Option(30, "--min-sample-size"),
) -> None:
    """
    Run deterministic walk-forward validation from stored replay outcomes.
    """

    del step
    split = WalkForwardSplit(
        train_start=_parse_date(train_start),
        train_end=_parse_date(train_end),
        validate_start=_parse_date(validate_start),
        validate_end=_parse_date(validate_end),
    )
    result = WalkForwardEngine(
        learning_repository=NightlyLearningLoop.from_path().repository
    ).run(split=split, minimum_sample_size=min_sample_size)
    print()
    for line in render_walk_forward(result):
        print(line)


@evidence_app.command(name="report")
def evidence_report(
    regime: str = typer.Option("ALL", "--regime"),
    setup: str = typer.Option("ALL", "--setup"),
    indicator: str = typer.Option("ALL", "--indicator"),
    holding_period: str = typer.Option("ALL", "--holding-period"),
    min_sample_size: int = typer.Option(30, "--min-sample-size"),
    top: int = typer.Option(10, "--top"),
) -> None:
    """
    Print evidence cube report from stored replay observations.
    """

    del regime, setup, indicator, holding_period
    cube = EvidenceCubeBuilder(
        repository=NightlyLearningLoop.from_path().repository
    ).build(minimum_sample_size=min_sample_size)
    print()
    for line in render_evidence_report(cube, top=top):
        print(line)


@evidence_app.command(name="features")
def evidence_features(
    min_sample_size: int = typer.Option(30, "--min-sample-size"),
) -> None:
    """
    Print deterministic feature importance from replay outcomes.
    """

    repository = NightlyLearningLoop.from_path().repository
    report = FeatureImportanceEngine(repository=repository).rank(
        minimum_sample_size=min_sample_size
    )
    suggestions = BayesianWeightUpdater().suggestions(
        report=report,
        minimum_sample_size=min_sample_size,
    )
    print()
    for line in render_feature_importance(report):
        print(line)
    print()
    for line in render_weight_suggestions(suggestions):
        print(line)


@simulate_app.command(name="strategy")
def simulate_strategy(
    from_date: str = typer.Option(..., "--from-date"),
    to_date: str = typer.Option(..., "--to-date"),
    setup: str = typer.Option("all", "--setup"),
    regime: str = typer.Option("ALL", "--regime"),
    holding_period: str = typer.Option("20d", "--holding-period"),
    stop_atr: str = typer.Option("2.0", "--stop-atr"),
    min_volume_ratio: float = typer.Option(0.0, "--min-volume-ratio"),
    min_relative_strength: float = typer.Option(0.0, "--min-relative-strength"),
    require_sector_strength: bool = typer.Option(
        False,
        "--require-sector-strength",
    ),
    require_volume_confirmation: bool = typer.Option(
        False,
        "--require-volume-confirmation",
    ),
    top: int = typer.Option(10, "--top"),
) -> None:
    """
    Compare deterministic strategy-rule variants on replay observations.
    """

    parameters = SimulationParameters(
        from_date=_parse_date(from_date),
        to_date=_parse_date(to_date),
        setup=setup,
        regime=regime,
        holding_period=holding_period,
        stop_atr=_parse_decimal(stop_atr),
        min_volume_ratio=Decimal(str(min_volume_ratio)),
        min_relative_strength=Decimal(str(min_relative_strength)),
        require_sector_strength=require_sector_strength,
        require_volume_confirmation=require_volume_confirmation,
        top=top,
    )
    result = SimulationLab(
        repository=NightlyLearningLoop.from_path().repository
    ).run_strategy(parameters=parameters)
    print()
    for line in render_simulation_result(result):
        print(line)


@trades_app.command(name="review")
def trades_review(
    symbol: str = typer.Option(..., "--symbol"),
    entry: str = typer.Option(..., "--entry"),
    stop: str = typer.Option(..., "--stop"),
    target: str = typer.Option(..., "--target"),
    quantity: str | None = typer.Option(None, "--quantity"),
    thesis: str | None = typer.Option(None, "--thesis"),
    alpha_entry: str | None = typer.Option(None, "--alpha-entry"),
    alpha_stop: str | None = typer.Option(None, "--alpha-stop"),
    alpha_target: str | None = typer.Option(None, "--alpha-target"),
    invalidation_respected: bool | None = typer.Option(
        None,
        "--invalidation-respected/--invalidation-not-respected",
    ),
    journal: Path | None = typer.Option(None, "--journal"),
) -> None:
    """
    Review and journal a live trade entered by the user.
    """

    engine = LiveTradeReviewEngine()
    record = engine.journal_record(
        symbol=symbol,
        entry=_parse_decimal(entry),
        stop=_parse_decimal(stop),
        target=_parse_decimal(target),
        quantity=_parse_decimal(quantity) if quantity is not None else None,
        thesis=thesis,
        alpha_entry=_parse_decimal(alpha_entry) if alpha_entry is not None else None,
        alpha_stop=_parse_decimal(alpha_stop) if alpha_stop is not None else None,
        alpha_target=_parse_decimal(alpha_target) if alpha_target is not None else None,
        invalidation_respected=invalidation_respected,
    )
    UserTradeJournalRepository(journal).save(record)
    print()
    for line in render_live_trade_review(record.review):
        print(line)
    print(f"Journaled Trade ID: {record.trade_id}")


@trades_app.command(name="journal")
def trades_journal(
    journal: Path | None = typer.Option(None, "--journal"),
) -> None:
    """
    Show user-entered trades reviewed by Alpha.
    """

    records = UserTradeJournalRepository(journal).load()
    print()
    for line in render_user_trade_journal(records):
        print(line)


@trades_app.command(name="summary")
def trades_summary(
    journal: Path | None = typer.Option(None, "--journal"),
) -> None:
    """
    Summarize user-entered trade quality.
    """

    records = UserTradeJournalRepository(journal).load()
    print()
    for line in render_user_trade_journal_summary(records):
        print(line)


@decision_app.command(name="report")
def decision_report(
    date: str = "today",
    demo: bool = typer.Option(
        False,
        "--demo",
        help="Use deterministic demo inputs instead of live analysis.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Include rejected candidates, gates, and score breakdowns.",
    ),
) -> None:
    """
    Print the institutional decision-layer report.
    """

    try:
        runtime_result = _run_daily_runtime(date=date, demo=demo)
    except BhavcopyNotFoundError as exc:
        _exit_with_error("Decision report failed", exc)
    except ProjectAlphaError as exc:
        _exit_with_error("Project Alpha command failed", exc)

    report = InstitutionalDecisionService().evaluate_runtime_result(runtime_result)
    print()
    for line in render_decision_report(report, verbose=verbose):
        print(line)


@decision_app.command(name="disqualifications")
def decision_disqualifications(
    date: str = "today",
    demo: bool = typer.Option(
        False,
        "--demo",
        help="Use deterministic demo inputs instead of live analysis.",
    ),
) -> None:
    """
    Explain why every non-deployable trade setup failed.
    """

    try:
        runtime_result = _run_daily_runtime(date=date, demo=demo)
    except BhavcopyNotFoundError as exc:
        _exit_with_error("Disqualification report failed", exc)
    except ProjectAlphaError as exc:
        _exit_with_error("Project Alpha command failed", exc)

    decision_report_result = InstitutionalDecisionService().evaluate_runtime_result(
        runtime_result
    )
    report = TradeSetupDisqualificationReporter().build(decision_report_result)
    print()
    for line in render_trade_setup_disqualification_report(report):
        print(line)


@decision_app.command(name="cards")
def decision_cards(
    date: str = "today",
    demo: bool = typer.Option(
        False,
        "--demo",
        help="Use deterministic demo inputs instead of live analysis.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Show full gate, stress-test, and historical-case evidence.",
    ),
) -> None:
    """
    Print unified decision cards for every scanned candidate.
    """

    try:
        runtime_result = _run_daily_runtime(date=date, demo=demo)
    except BhavcopyNotFoundError as exc:
        _exit_with_error("Decision cards failed", exc)
    except ProjectAlphaError as exc:
        _exit_with_error("Project Alpha command failed", exc)

    decision_report_result = InstitutionalDecisionService().evaluate_runtime_result(
        runtime_result
    )
    cards = DecisionEvidenceCardBuilder.from_path().build_many(
        decision_report_result.decisions
    )
    print()
    for line in render_decision_evidence_cards(cards, verbose=verbose):
        print(line)


@decision_app.command(name="audit")
def decision_audit(
    date: str = "today",
    demo: bool = typer.Option(
        False,
        "--demo",
        help="Use deterministic demo inputs instead of live analysis.",
    ),
) -> None:
    """
    Print decision stress-test and hardening audit.
    """

    try:
        runtime_result = _run_daily_runtime(date=date, demo=demo)
    except BhavcopyNotFoundError as exc:
        _exit_with_error("Decision audit failed", exc)
    except ProjectAlphaError as exc:
        _exit_with_error("Project Alpha command failed", exc)

    decision_report_result = InstitutionalDecisionService().evaluate_runtime_result(
        runtime_result
    )
    audit = InstitutionalDecisionService().engine.stress_engine.audit(
        decision_report_result.decisions
    )
    print()
    for line in render_decision_audit(audit):
        print(line)


@tradeplan_app.command(name="audit")
def tradeplan_audit(
    date: str = "today",
    demo: bool = typer.Option(
        False,
        "--demo",
        help="Use deterministic demo inputs instead of live analysis.",
    ),
) -> None:
    """
    Print trade-plan optimization audit for accepted opportunities.
    """

    try:
        runtime_result = _run_daily_runtime(date=date, demo=demo)
    except BhavcopyNotFoundError as exc:
        _exit_with_error("Trade plan audit failed", exc)
    except ProjectAlphaError as exc:
        _exit_with_error("Project Alpha command failed", exc)

    service = InstitutionalDecisionService()
    decision_report_result = service.evaluate_runtime_result(runtime_result)
    audit = service.engine.trade_plan_optimizer.audit(decision_report_result.decisions)
    print()
    for line in render_trade_plan_audit(audit):
        print(line)


@playbook_app.command(name="report")
def playbook_report(
    min_sample_size: int = typer.Option(30, "--min-sample-size"),
) -> None:
    """
    Print learned setup, regime, holding-period, and structure playbook.
    """

    playbook = BestSetupPlaybookBuilder(
        repository=NightlyLearningLoop.from_path().repository
    ).build(minimum_sample_size=min_sample_size)
    print()
    for line in render_best_setup_playbook(playbook):
        print(line)


@strategy_regime_app.command(name="backtest")
def strategy_regime_backtest(
    from_date: str = typer.Option(..., "--from-date", help="Start date YYYY-MM-DD."),
    to_date: str = typer.Option(..., "--to-date", help="End date YYYY-MM-DD."),
    regime: str = typer.Option(
        "ALL",
        "--regime",
        help="BULLISH|BEARISH|SIDEWAYS|NEUTRAL|RISK_OFF|ALL.",
    ),
    strategy: str = typer.Option(
        "all",
        "--strategy",
        help="breakout|pullback|relative-strength|volume-expansion|all.",
    ),
    holding_period: str = typer.Option(
        "all",
        "--holding-period",
        help="1d|3d|5d|10d|20d|60d|all.",
    ),
    min_sample_size: int = typer.Option(30, "--min-sample-size"),
    top: int = typer.Option(10, "--top"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """
    Run deterministic strategy-regime backtest over available observations.
    """

    del verbose
    start = _parse_date(from_date)
    end = _parse_date(to_date)
    regimes = _parse_regime_filter(regime)
    strategies = _parse_strategy_filter(strategy)
    holding_periods = _parse_holding_period_filter(holding_period)
    run = StrategyRegimeBacktestEngine().run(
        observations=(),
        from_date=start,
        to_date=end,
        regimes=regimes,
        strategies=strategies,
        holding_periods=holding_periods,
        minimum_sample_size=min_sample_size,
    )
    StrategyRegimeBacktestRepository().save_run(run)
    print()
    for line in render_backtest_run(run, top=top):
        print(line)
    if not run.results:
        print("No historical signal observations were available; no edge was computed.")


@strategy_regime_app.command(name="report")
def strategy_regime_report(
    top: int = typer.Option(10, "--top"),
) -> None:
    """
    Print latest stored strategy-regime backtest report.
    """

    run = StrategyRegimeBacktestRepository().latest_run()
    print()
    for line in render_strategy_regime_report(run, top=top):
        print(line)


@app.command()
def backtest(
    strategy: str = typer.Option(..., help="Strategy name"),
    start: str = typer.Option(..., help="Start date (YYYY-MM-DD)"),
    end: str = typer.Option(..., help="End date (YYYY-MM-DD)"),
    cash: str = typer.Option("1000000", help="Starting cash"),
    export_json: Path | None = typer.Option(
        None,
        "--export-json",
        help="Write unified backtest report JSON to this path.",
    ),
    export_text: Path | None = typer.Option(
        None,
        "--export-text",
        help="Write unified backtest report text to this path.",
    ),
) -> None:
    """
    Run a deterministic backtest.
    """

    start_date = _parse_date(start)
    end_date = _parse_date(end)

    if end_date < start_date:
        raise typer.BadParameter("End date must be on or after start date.")

    starting_cash = _parse_decimal(cash)
    if starting_cash <= Decimal("0"):
        raise typer.BadParameter("Starting cash must be greater than zero.")

    _validate_command_export_paths(export_json=export_json, export_text=export_text)

    service = BacktestApplicationService()
    try:
        run = service.run(
            strategy=strategy,
            start=start_date,
            end=end_date,
            starting_cash=starting_cash,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error

    _print_backtest_summary(run.summary)
    _export_backtest_summary(
        summary=run.summary,
        export_json=export_json,
        export_text=export_text,
    )


def _run_daily_runtime(*, date: str, demo: bool) -> RuntimeResult:
    runtime = ProjectAlphaRuntime()
    return runtime.run_daily(date_str=date, demo=demo)


def _run_intelligence_runtime(*, date: str, demo: bool) -> RuntimeResult:
    runtime = ProjectAlphaRuntime()
    return runtime.run_intelligence(date_str=date, demo=demo)


def _print_daily_runtime_result(
    runtime_result: RuntimeResult,
    *,
    verbose: bool = True,
) -> None:
    run = runtime_result.intelligence_run
    allocation = run.allocation_plan
    market_analysis = runtime_result.market_analysis

    print("\nProject Alpha Daily Run")
    print(f"Status       : {runtime_result.status.value}")
    print(f"Mode         : {runtime_result.mode.value}")
    print(f"Requested On : {runtime_result.requested_on.isoformat()}")
    print(f"Observed On  : {runtime_result.observed_on.isoformat()}")
    print(f"Duration     : {runtime_result.metadata.duration_seconds}s")

    if market_analysis is not None:
        print(f"Rows Analyzed: {len(market_analysis.analysis)}")

    print("\nMarket")
    print(f"Symbol       : {run.market_report.symbol}")
    print(f"Bias         : {run.market_report.bias.value}")
    print(f"Score        : {run.market_report.composite_score}")
    top_sector = run.market_report.sector_rotation.top_sector.sector
    print(f"Top Sector   : {top_sector}")
    metadata_notice = _sector_metadata_notice(top_sector)
    if metadata_notice is not None:
        print(metadata_notice)

    print("\nCapital Deployment Dashboard:")
    for line in _capital_deployment_dashboard_lines(
        recommendations=run.recommendations,
        allocation_plan=allocation,
    ):
        print(line)

    if not verbose:
        decision_report = InstitutionalDecisionService().evaluate_runtime_result(
            runtime_result
        )
        print()
        for line in render_default_opportunities(decision_report):
            print(line)
        print("\nUse --verbose for rejected candidates and full evidence.")
        return

    print("\nRecommendations")
    for index, recommendation in enumerate(run.recommendations[:10], start=1):
        for line in _recommendation_detail_lines(index, recommendation):
            print(line)

    decision_report = InstitutionalDecisionService().evaluate_runtime_result(
        runtime_result
    )
    print("\nInstitutional Decision Layer")
    for line in render_decision_report(decision_report, verbose=True):
        print(line)

    print("\nPortfolio Allocation")
    print(f"- Approved Capital: ₹{allocation.total_allocated_amount}")
    print(f"- Remaining Cash: ₹{allocation.remaining_cash}")
    deployment_count = len(
        tuple(report for report in allocation.reports if report.target_weight > 0)
    )
    print(f"- Deployment Count: {deployment_count}")

    print("\nPortfolio Summary")
    for line in _portfolio_summary_lines(run):
        print(line)

    if allocation.reports:
        print("\nPositions")
        recommendation_by_symbol = {
            recommendation.symbol: recommendation
            for recommendation in run.recommendations
        }
        for index, report in enumerate(allocation.reports[:10], start=1):
            allocation_recommendation = recommendation_by_symbol.get(report.symbol)
            capital_action = _allocation_capital_action(report.reasons)
            investment_verdict = (
                _verdict_label(allocation_recommendation)
                if allocation_recommendation is not None
                else "UNKNOWN"
            )
            execution_status = (
                _execution_status(allocation_recommendation)
                if allocation_recommendation is not None
                else "DO NOTHING"
            )
            print(f"{index}. {report.symbol}")
            print(f"   Investment Verdict: {investment_verdict}")
            print(f"   Execution Status: {execution_status}")
            print(f"   Allocation Status: {_allocation_status(report, capital_action)}")
            print(f"   Approved Capital: ₹{report.target_amount}")
            print(f"   Target Weight: {(report.target_weight * Decimal('100'))}%")
            print(f"   Reason: {_allocation_reason(capital_action, execution_status)}")

    if market_analysis is not None:
        signals = market_analysis.report["signals"]
        buy_count = int((signals["signal"] == "BUY").sum())
        sell_count = int((signals["signal"] == "SELL").sum())
        hold_count = int((signals["signal"] == "HOLD").sum())

        print("\nTrading Signals")
        print(f"BUY  : {buy_count}")
        print(f"SELL : {sell_count}")
        print(f"HOLD : {hold_count}")


def _print_backtest_summary(summary: BacktestSummary) -> None:
    renderer = BacktestReportRenderer()

    print()
    for line in renderer.render(summary.report):
        print(line)


def _allocation_capital_action(reasons: tuple[str, ...]) -> str:
    prefix = "capital action: "
    for reason in reasons:
        if reason.startswith(prefix):
            return reason.removeprefix(prefix)
    return "unknown"


def _approved_deployment_summary(reasons: tuple[str, ...]) -> str:
    prefix = "approved capital deployments: "
    for reason in reasons:
        if reason.startswith(prefix):
            return reason
    return "approved capital deployments: 0"


def _portfolio_summary_lines(run: IntelligenceRun) -> tuple[str, ...]:
    allocation = run.allocation_plan
    approved_reports = tuple(
        report for report in allocation.reports if report.target_weight > Decimal("0")
    )

    highest_conviction = min(
        run.recommendations,
        key=lambda recommendation: (
            -recommendation.score,
            recommendation.symbol,
        ),
        default=None,
    )
    largest_position = min(
        approved_reports,
        key=lambda report: (
            -report.target_weight,
            report.symbol,
        ),
        default=None,
    )

    highest_conviction_symbol = (
        highest_conviction.symbol
        if highest_conviction is not None and approved_reports
        else "NONE"
    )
    largest_position_text = "NONE"
    if largest_position is not None:
        largest_position_text = (
            f"{largest_position.symbol} "
            f"{_weight_percent(largest_position.target_weight)}"
        )

    return (
        f"Approved Deployments : {len(approved_reports)}",
        f"Approved Capital     : {allocation.total_allocated_amount}",
        f"Cash Remaining       : {allocation.remaining_cash}",
        f"Highest Conviction   : {highest_conviction_symbol}",
        f"Largest Position     : {largest_position_text}",
    )


def _data_quality_text(recommendation: object) -> str:
    unavailable = getattr(recommendation, "unavailable_reasons", ())
    return "Partial" if unavailable else "Complete"


def _weight_percent(value: Decimal) -> str:
    return f"{(value * Decimal('100')).quantize(Decimal('0.01'))}%"


def _export_backtest_summary(
    *,
    summary: BacktestSummary,
    export_json: Path | None,
    export_text: Path | None,
) -> None:
    service = BacktestExportService()
    try:
        result = service.export(
            summary,
            json_path=export_json,
            text_path=export_text,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error

    if result.json_path is not None:
        print(f"\nJSON report written: {result.json_path}")

    if result.text_path is not None:
        print(f"\nText report written: {result.text_path}")


def _export_intelligence_run(
    *,
    run: IntelligenceRun,
    export_json: Path | None,
    export_text: Path | None,
) -> None:
    service = IntelligenceExportService()
    try:
        result = service.export(
            run,
            json_path=export_json,
            text_path=export_text,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error

    if result.json_path is not None:
        print(f"\nJSON report written: {result.json_path}")

    if result.text_path is not None:
        print(f"\nText report written: {result.text_path}")


def _record_recommendation_performance(
    runtime_result: RuntimeResult,
) -> tuple[str, ...]:
    repository = RecommendationLedgerRepository(resolve_ledger_path())
    recorder = RecommendationPerformanceRecorder(repository)
    stored = recorder.record_runtime(runtime_result)
    return render_tracking_summary(
        stored_recommendations=stored,
        repository=repository,
    )


def _record_forward_validation(runtime_result: RuntimeResult) -> None:
    """Freeze CLI recommendations without influencing production policy."""

    engine = ForwardValidationEngine(registry=ForwardValidationRegistry())
    engine.capture_runtime(runtime_result)


def _persist_decision_provenance(
    runtime_result: RuntimeResult,
    *,
    runtime_command: str,
) -> DecisionProvenance:
    repository = DecisionProvenanceRepository()
    provenance = capture_current_provenance(
        created_at=runtime_result.metadata.completed_at,
        runtime_command=runtime_command,
        runtime_mode=runtime_result.metadata.mode.value,
        source="alpha-cli",
    )
    result = repository.upsert(provenance)
    status = "persisted" if result.inserted else "reused"
    print()
    print(f"Decision Provenance: {status} {result.provenance.provenance_id}")
    return result.provenance


def _persist_market_state_snapshot(
    runtime_result: RuntimeResult,
    *,
    provenance: DecisionProvenance | None = None,
) -> MarketStatePersistenceResult:
    repository = MarketStateSnapshotRepository()
    try:
        benchmark_config = canonical_benchmark_configuration()
        benchmark_history = MarketTruthPriceRepository().find_history_by_symbols(
            symbols=(benchmark_config.provider_symbol,),
            end_date=runtime_result.observed_on,
            limit=benchmark_config.minimum_history_bars,
        )
        benchmark_state = BenchmarkStateBuilder(
            configuration=benchmark_config,
        ).build(
            bars=benchmark_history,
            decision_as_of=runtime_result.metadata.completed_at,
        )
        snapshot = MarketStateSnapshot.from_market_report(
            runtime_result.intelligence_run.market_report,
            as_of_timestamp=runtime_result.metadata.completed_at,
            created_at=runtime_result.metadata.completed_at,
            benchmark_state=benchmark_state,
            provenance=provenance,
        )
        return repository.save(snapshot)
    except Exception as error:
        return MarketStatePersistenceResult(
            status=MarketStatePersistenceStatus.SNAPSHOT_PERSISTENCE_FAILED,
            snapshot=None,
            path=repository.path,
            message=f"Market-state snapshot capture failed: {error}",
        )


def _market_state_context(
    result: MarketStatePersistenceResult,
) -> CandidateMarketStateContext | None:
    snapshot = result.snapshot
    if snapshot is None:
        return None
    if result.status not in {
        MarketStatePersistenceStatus.SNAPSHOT_PERSISTED,
        MarketStatePersistenceStatus.SNAPSHOT_ALREADY_EXISTS,
    }:
        return None
    return CandidateMarketStateContext(
        snapshot_id=snapshot.snapshot_id,
        as_of=snapshot.as_of_timestamp,
        fallback_applied=snapshot.fallback_applied,
        completeness=snapshot.input_completeness.value,
        classifier_version=snapshot.classifier_version,
        decision_provenance_id=snapshot.provenance_id,
    )


def _record_candidate_learning(
    runtime_result: RuntimeResult,
    *,
    market_state_result: MarketStatePersistenceResult | None = None,
) -> tuple[str, ...]:
    loop = NightlyLearningLoop.from_path()
    evaluated, stored = loop.record_runtime(
        runtime_result,
        market_state_context=(
            None
            if market_state_result is None
            else _market_state_context(market_state_result)
        ),
    )
    return (
        *loop.runtime_ledger_lines(
            stored_today=stored,
            evaluated_today=evaluated,
        ),
        "",
        *loop.raw_runtime_lines(),
    )


def _print_live_trade_checkin() -> None:
    print()
    print("Live Trades Check-In:")
    print("- Please share any live trades you entered today.")
    print(
        "- I can review trade quality, entry discipline, target, stop loss, "
        "risk/reward, and invalidation."
    )


def _historical_evidence_lines() -> tuple[str, ...]:
    snapshot = HistoricalEvidenceService.from_path().snapshot()
    return render_historical_evidence_snapshot(snapshot)


def _validate_command_export_paths(
    *,
    export_json: Path | None,
    export_text: Path | None,
) -> None:
    try:
        _validate_export_paths(export_json=export_json, export_text=export_text)
    except typer.BadParameter as error:
        typer.echo(str(error))
        raise typer.Exit(code=2) from error


def _validate_export_paths(
    *,
    export_json: Path | None,
    export_text: Path | None,
) -> None:
    if export_json is not None and export_json.suffix.lower() != ".json":
        raise typer.BadParameter("Expected --export-json path to end with .json.")

    if export_text is not None and export_text.suffix.lower() != ".txt":
        raise typer.BadParameter("Expected --export-text path to end with .txt.")


def _parse_date(date_str: str) -> dt_date:
    if date_str == "today":
        return dt_date.today()

    return dt_date.fromisoformat(date_str)


def _parse_decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise typer.BadParameter("Expected a decimal value.") from error


def _replay_sample_plan(
    *,
    from_date: str,
    to_date: str,
    frequency: str,
    max_dates: int | None,
) -> ReplaySamplePlan:
    try:
        parsed_frequency = ReplaySampleFrequency(frequency.strip().lower())
    except ValueError as error:
        raise typer.BadParameter(
            "frequency must be weekly, monthly, or quarterly"
        ) from error
    return HistoricalReplaySampler(repository=MarketTruthPriceRepository()).plan(
        start=_parse_date(from_date),
        end=_parse_date(to_date),
        frequency=parsed_frequency,
        max_dates=max_dates,
    )


def _approval_diagnostic_summary(
    *,
    nearest: int = 10,
) -> ApprovalDiagnosticSummary:
    repository = NightlyLearningLoop.from_path().repository
    return ApprovalDiagnosticsEngine(
        config=ApprovalDiagnosticsConfig(nearest_candidate_limit=nearest)
    ).build(
        records=repository.load_records(),
        outcomes=repository.load_outcomes(),
    )


def _approval_outcome_report() -> ApprovalOutcomeReport:
    repository = NightlyLearningLoop.from_path().repository
    return ApprovalOutcomeAnalysisEngine().analyze(
        records=repository.load_records(),
        outcomes=repository.load_outcomes(),
    )


def _entry_timing_report() -> EntryTimingReplayReport:
    repository = NightlyLearningLoop.from_path().repository
    return build_entry_timing_replay_report(
        records=repository.load_records(),
        outcomes=repository.load_outcomes(),
    )


def _entry_timing_validation_report() -> EntryTimingValidationReport:
    repository = NightlyLearningLoop.from_path().repository
    return EntryTimingValidationEngine().audit(
        records=repository.load_records(),
        outcomes=repository.load_outcomes(),
    )


def _approval_baseline_comparison() -> ApprovalBaselineComparison:
    repository = NightlyLearningLoop.from_path().repository
    records = repository.load_records()
    outcomes = repository.load_outcomes()
    timing_report = build_entry_timing_replay_report(
        records=records,
        outcomes=outcomes,
    )
    return ApprovalBaselineAuditEngine().compare(
        records=records,
        outcomes=outcomes,
        timing_report=timing_report,
    )


def _gate_attribution_report() -> GateAttributionReport:
    repository = NightlyLearningLoop.from_path().repository
    return NonEntryGateAttributionEngine().analyze(
        records=repository.load_records(),
        outcomes=repository.load_outcomes(),
    )


def _directional_signal_audit_report() -> DirectionalSignalAuditReport:
    repository = NightlyLearningLoop.from_path().repository
    return DirectionalSignalQualityAuditEngine().analyze(
        records=repository.load_records(),
        outcomes=repository.load_outcomes(),
    )


def _market_regime_audit_report() -> MarketRegimeAuditReport:
    repository = NightlyLearningLoop.from_path().repository
    return MarketRegimeAuditEngine().analyze(
        records=repository.load_records(),
        outcomes=repository.load_outcomes(),
    )


def _market_state_persistence_audit_report() -> MarketStatePersistenceAuditReport:
    repository = NightlyLearningLoop.from_path().repository
    return MarketStatePersistenceAuditEngine().analyze(
        records=repository.load_records(),
        outcomes=repository.load_outcomes(),
        authoritative_snapshots=MarketStateSnapshotRepository().load_all(),
    )


def _benchmark_coverage_report() -> BenchmarkCoverageReport:
    learning_repository = NightlyLearningLoop.from_path().repository
    records = learning_repository.load_records()
    return benchmark_coverage_report(
        repository=MarketTruthPriceRepository(),
        snapshots=MarketStateSnapshotRepository().load_all(),
        candidate_dates=tuple(record.evaluation_date for record in records),
        configuration=canonical_benchmark_configuration(),
    )


def _market_state_backfill_readiness_report(
    *,
    group_by: str | None = None,
) -> HistoricalMarketStateBackfillReadinessReport:
    learning_repository = NightlyLearningLoop.from_path().repository
    return HistoricalMarketStateBackfillReadinessEngine(
        configuration=canonical_benchmark_configuration(),
    ).analyze(
        records=learning_repository.load_records(),
        price_repository=MarketTruthPriceRepository(),
        group_by=group_by,
    )


def _version_lineage_report() -> VersionLineageAuditReport:
    learning_repository = NightlyLearningLoop.from_path().repository
    return build_version_lineage_audit(
        records=learning_repository.load_records(),
        snapshots=MarketStateSnapshotRepository().load_all(),
        provenances=DecisionProvenanceRepository().load_all(),
    )


def _version_drift_report() -> VersionDriftReport:
    learning_repository = NightlyLearningLoop.from_path().repository
    return build_version_drift_report(
        records=learning_repository.load_records(),
        snapshots=MarketStateSnapshotRepository().load_all(),
        provenances=DecisionProvenanceRepository().load_all(),
    )


def _historical_manifest_audit_report() -> HistoricalManifestAuditReport:
    learning_repository = NightlyLearningLoop.from_path().repository
    return build_historical_manifest_audit(
        records=learning_repository.load_records(),
        snapshots=MarketStateSnapshotRepository().load_all(),
        provenances=DecisionProvenanceRepository().load_all(),
    )


def _diagnostic_market_state_dataset(
    *,
    from_date: dt_date | None,
    to_date: dt_date | None,
    dry_run: bool,
) -> DiagnosticMarketStateDataset:
    learning_repository = NightlyLearningLoop.from_path().repository
    return DiagnosticMarketStateReconstructionEngine().build(
        records=learning_repository.load_records(),
        outcomes=learning_repository.load_outcomes(),
        price_repository=MarketTruthPriceRepository(),
        provenances=DecisionProvenanceRepository().load_all(),
        snapshots=MarketStateSnapshotRepository().load_all(),
        from_date=from_date,
        to_date=to_date,
        dry_run=dry_run,
    )


def _diagnostic_market_state_coverage_report() -> DiagnosticMarketStateCoverageReport:
    repository = DiagnosticMarketStateRepository()
    return build_diagnostic_market_state_coverage_report(
        reconstructions=repository.load_reconstructions(
            dataset_version=DIAGNOSTIC_MARKET_STATE_DATASET_VERSION
        ),
        links=repository.load_links(),
    )


def _diagnostic_regime_comparison_report() -> DiagnosticRegimeComparisonReport:
    repository = DiagnosticMarketStateRepository()
    learning_repository = NightlyLearningLoop.from_path().repository
    return build_regime_comparison_report(
        reconstructions=repository.load_reconstructions(
            dataset_version=DIAGNOSTIC_MARKET_STATE_DATASET_VERSION
        ),
        links=repository.load_links(),
        records=learning_repository.load_records(),
        outcomes=learning_repository.load_outcomes(),
    )


def _diagnostic_threshold_readiness_report() -> DiagnosticThresholdReadinessReport:
    repository = DiagnosticMarketStateRepository()
    learning_repository = NightlyLearningLoop.from_path().repository
    return DiagnosticRegimeOutcomeValidationEngine().build(
        reconstructions=repository.load_reconstructions(
            dataset_version=DIAGNOSTIC_MARKET_STATE_DATASET_VERSION
        ),
        links=repository.load_links(),
        records=learning_repository.load_records(),
        outcomes=learning_repository.load_outcomes(),
    )


def _point_in_time_universe_dataset(*, dry_run: bool) -> PointInTimeUniverseDataset:
    learning_repository = NightlyLearningLoop.from_path().repository
    return PointInTimeUniverseBuilder().build(
        records=learning_repository.load_records(),
        price_repository=MarketTruthPriceRepository(),
        dry_run=dry_run,
    )


def _load_point_in_time_materialization() -> PointInTimeMaterializedDataset | None:
    return PointInTimeMaterializationRepository().load()


def _load_completed_point_in_time_materialization() -> PointInTimeMaterializedDataset:
    materialization = _load_point_in_time_materialization()
    if materialization is None:
        raise typer.BadParameter(
            "No completed point-in-time dataset exists. Run "
            "`poetry run python -m alpha replay point-in-time-universe-build "
            "--persist-diagnostic` first. Reporting commands do not silently "
            "trigger full historical rebuilds."
        )
    if materialization.manifest.status is not PointInTimeBuildStatus.COMPLETED:
        raise typer.BadParameter(
            "Point-in-time dataset is not complete. Resume the build or run "
            "point-in-time-dataset-validate before reporting."
        )
    validation = validate_point_in_time_materialization(materialization)
    if validation.status is PointInTimeValidationStatus.INVALID:
        raise typer.BadParameter(
            "Point-in-time dataset validation failed; reporting is blocked."
        )
    return materialization


def _load_completed_point_in_time_universe() -> PointInTimeUniverseDataset:
    return _load_completed_point_in_time_materialization().universe


def _load_diagnostic_v2_validation_report() -> DiagnosticV2ValidationReport:
    loop = NightlyLearningLoop.from_path()
    v1_reconstructions = DiagnosticMarketStateRepository().load_reconstructions(
        dataset_version=DIAGNOSTIC_MARKET_STATE_DATASET_VERSION
    )
    return DiagnosticV2ValidationEngine().build(
        v1_reconstructions=v1_reconstructions,
        records=loop.repository.load_records(),
        outcomes=loop.repository.load_outcomes(),
    )


def _emit_diagnostic_v2_command(
    *,
    output_format: str,
    output: Path | None,
    rows_attr: str,
    renderer: Callable[[DiagnosticV2ValidationReport], tuple[str, ...]],
    label: str,
) -> None:
    report = _load_diagnostic_v2_validation_report()
    rows = getattr(report, rows_attr)
    if not isinstance(rows, tuple):
        rows = (rows,)
    _emit_diagnostic_v2_validation_report(
        report,
        output_format=output_format,
        output=output,
        rows=rows,
        renderer=renderer,
        label=label,
    )


def _emit_diagnostic_v2_validation_report(
    report: DiagnosticV2ValidationReport,
    *,
    output_format: str,
    output: Path | None,
    rows: tuple[object, ...],
    renderer: Callable[[DiagnosticV2ValidationReport], tuple[str, ...]],
    label: str,
) -> None:
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_diagnostic_v2_json(report, output)
        print(f"{label} written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_diagnostic_v2_csv(rows, output)
        print(f"{label} written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in renderer(report):
        print(line)


def _emit_historical_sector_report(
    payload: object,
    *,
    output_format: str,
    output: Path | None,
    rows: tuple[object, ...],
    renderer: Callable[[Any], tuple[str, ...]],
    label: str,
) -> None:
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_historical_sector_json(payload, output)
        print(f"{label} written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_historical_sector_csv(rows, output)
        print(f"{label} written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in renderer(payload):
        print(line)


def _emit_sector_source_report(
    payload: object,
    *,
    output_format: str,
    output: Path | None,
    rows: tuple[object, ...],
    renderer: Callable[[Any], tuple[str, ...]],
    label: str,
) -> None:
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_sector_source_json(payload, output)
        print(f"{label} written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_sector_source_csv(rows, output)
        print(f"{label} written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in renderer(payload):
        print(line)


def _emit_regime_simplification_report(
    payload: object,
    *,
    output_format: str,
    output: Path | None,
    rows: tuple[object, ...],
    renderer: Callable[[Any], tuple[str, ...]],
    label: str,
) -> None:
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_regime_simplification_json(payload, output)
        print(f"{label} written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_regime_simplification_csv(rows, output)
        print(f"{label} written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in renderer(payload):
        print(line)


def _emit_regime_influence_report(
    payload: object,
    *,
    output_format: str,
    output: Path | None,
    rows: tuple[object, ...],
    renderer: Callable[[Any], tuple[str, ...]],
    label: str,
) -> None:
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_regime_influence_json(payload, output)
        print(f"{label} written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_regime_influence_csv(rows, output)
        print(f"{label} written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in renderer(payload):
        print(line)


def _emit_regime_shadow_report(
    payload: object,
    *,
    output_format: str,
    output: Path | None,
    rows: tuple[object, ...],
    renderer: Callable[[Any], tuple[str, ...]],
    label: str,
) -> None:
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_regime_shadow_json(payload, output)
        print(f"{label} written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_regime_shadow_csv(rows, output)
        print(f"{label} written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in renderer(payload):
        print(line)


def _emit_live_regime_shadow_report(
    payload: object,
    *,
    output_format: str,
    output: Path | None,
    rows: tuple[object, ...],
    renderer: Callable[[Any], tuple[str, ...]],
    label: str,
) -> None:
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_live_regime_shadow_json(payload, output)
        print(f"{label} written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_live_regime_shadow_csv(rows, output)
        print(f"{label} written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in renderer(payload):
        print(line)


def _emit_diagnostic_outcome_report(
    report: DiagnosticThresholdReadinessReport,
    *,
    output_format: str,
    output: Path | None,
    rows: tuple[object, ...],
    renderer: Callable[[DiagnosticThresholdReadinessReport], tuple[str, ...]],
    label: str,
) -> None:
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_diagnostic_outcome_json(report, output)
        print(f"{label} written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_diagnostic_rows_csv(rows, output)
        print(f"{label} written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in renderer(report):
        print(line)


def _emit_point_in_time_report(
    payload: object,
    *,
    output_format: str,
    output: Path | None,
    rows: tuple[object, ...],
    renderer: Callable[[Any], tuple[str, ...]],
    label: str,
) -> None:
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_point_in_time_json(payload, output)
        print(f"{label} written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_point_in_time_csv(rows, output)
        print(f"{label} written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    for line in renderer(payload):
        print(line)


def _parse_directional_frontier_direction(
    value: str,
) -> DirectionalPolicyDirection | None:
    normalized = value.strip().upper()
    if normalized in {"BOTH", "ALL"}:
        return None
    try:
        return DirectionalPolicyDirection(normalized)
    except ValueError as error:
        raise typer.BadParameter("direction must be buy, sell, or both.") from error


def _directional_frontier_default_definition() -> DirectionalOutcomeDefinition:
    return DirectionalOutcomeDefinition(
        family=DirectionalOutcomeFamily.TERMINAL_RETURN,
        horizon_days=20,
        positive_return_threshold=0.02,
        negative_return_threshold=-0.02,
    )


def _directional_frontier_observations() -> tuple[
    tuple[DirectionalObservation, ...] | None,
    str,
]:
    audit = _directional_signal_audit_report()
    observations = tuple(
        _directional_observation_from_audit_row(row)
        for row in audit.candidate_rows
        if row.forward_return is not None
    )
    if not observations:
        return None, "DETERMINISTIC_RESEARCH_FIXTURE"
    return observations, "CANDIDATE_LEARNING_DIRECTIONAL_AUDIT"


def _buy_signal_reconstruction_report() -> Any:
    observations, data_source = _directional_frontier_observations()
    return build_buy_signal_reconstruction_report(
        observations=observations,
        definition=_directional_frontier_default_definition(),
        data_source=data_source,
    )


def _opportunity_evolution_report(
    symbol: str | None,
    opportunity_id: str | None,
    trigger: str | None,
) -> Any:
    observations, _ = _directional_frontier_observations()
    return build_opportunity_evolution_report(
        observations=observations,
        definition=_directional_frontier_default_definition(),
        symbol=symbol,
        opportunity_id=opportunity_id,
        trigger=trigger,
    )


def _confirmation_intelligence_report(
    symbol: str | None,
    opportunity_id: str | None,
) -> Any:
    observations, _ = _directional_frontier_observations()
    return build_confirmation_intelligence_report(
        observations=observations,
        definition=_directional_frontier_default_definition(),
        symbol=symbol,
        opportunity_id=opportunity_id,
    )


def _breakout_reference_method(value: str) -> BreakoutReferenceMethod:
    try:
        return parse_breakout_reference_method(value)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


def _optional_breakout_reference_method(
    value: str | None,
) -> BreakoutReferenceMethod | None:
    return None if value is None else _breakout_reference_method(value)


def _optional_breakout_gap_cause(value: str | None) -> BreakoutGapCause | None:
    if value is None:
        return None
    try:
        return parse_breakout_gap_cause(value)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


def _optional_breakout_recovery_class(
    value: str | None,
) -> BreakoutGapRecoveryClass | None:
    if value is None:
        return None
    try:
        return parse_breakout_recovery_class(value)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


def _optional_breakout_reference_date(value: str | None) -> dt_date | None:
    if value is None:
        return None
    try:
        return dt_date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter("dates must use YYYY-MM-DD format") from error


def _breakout_reference_records(
    *,
    from_date: dt_date | None,
    to_date: dt_date | None,
    symbol: str | None,
    candidate_id: str | None,
    replay_run_id: str | None,
    reference_method: BreakoutReferenceMethod | None,
) -> tuple[Any, ...]:
    try:
        records = load_filtered_breakout_reference_records(
            from_date=from_date,
            to_date=to_date,
            symbol=symbol,
            candidate_id=candidate_id,
            replay_run_id=replay_run_id,
            reference_method=reference_method,
        )
        if (
            candidate_id is not None
            and count_filtered_replay_candidates(candidate_id=candidate_id) == 0
        ):
            raise ValueError(f"candidate id not found: {candidate_id}")
        return records
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


def _breakout_gap_report(
    *,
    cause: str | None,
    recovery_class: str | None,
    provider: str | None,
    symbol: str | None,
    from_date: str | None,
    to_date: str | None,
    year: int | None,
    minimum_sample: int,
    limit: int | None,
) -> Any:
    try:
        return build_project_breakout_source_gap_audit(
            group_cause=_optional_breakout_gap_cause(cause),
            recovery_class=_optional_breakout_recovery_class(recovery_class),
            provider=provider,
            symbol=symbol,
            from_date=_optional_breakout_reference_date(from_date),
            to_date=_optional_breakout_reference_date(to_date),
            year=year,
            minimum_sample=minimum_sample,
            limit=limit,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


def _breakout_gap_group_lines(
    records: tuple[Any, ...],
    group_by: str,
) -> tuple[str, ...]:
    try:
        return render_breakout_gap_groups(records, group_by)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


def _breakout_intelligence_report(
    symbol: str | None,
    opportunity_id: str | None,
    breakout_class: str | None,
    policy: str | None,
) -> Any:
    observations, _ = _directional_frontier_observations()
    reference_records = load_filtered_breakout_reference_records(
        symbol=symbol,
        reference_method=BreakoutReferenceMethod.PRIOR_SWING_HIGH,
    )
    return build_breakout_intelligence_report(
        observations=observations,
        definition=_directional_frontier_default_definition(),
        symbol=symbol,
        opportunity_id=opportunity_id,
        breakout_class=breakout_class,
        policy=policy,
        reference_records=reference_records,
        reference_method=BreakoutReferenceMethod.PRIOR_SWING_HIGH,
    )


def _emit_confirmation_intelligence_report(
    report: Any,
    *,
    output_format: str,
    output: Path | None,
    group_by: str | None,
    renderer: Callable[[Any], tuple[str, ...]],
    label: str,
) -> None:
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_confirmation_intelligence_json(report, output)
        print(f"{label} written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_confirmation_intelligence_csv(report, output)
        print(f"{label} written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    if group_by is not None:
        print(f"{label.title()} Grouped By {group_by}:")
        for line in group_confirmation_report(report, group_by):
            print(line)
        return
    for line in renderer(report):
        print(line)


def _emit_breakout_intelligence_report(
    report: Any,
    *,
    output_format: str,
    output: Path | None,
    group_by: str | None,
    renderer: Callable[[Any], tuple[str, ...]],
    label: str,
) -> None:
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_breakout_intelligence_json(report, output)
        print(f"{label} written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_breakout_intelligence_csv(report, output)
        print(f"{label} written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    if group_by is not None:
        print(f"{label.title()} Grouped By {group_by}:")
        for line in group_breakout_report(report, group_by):
            print(line)
        return
    for line in renderer(report):
        print(line)


def _emit_breakout_reference_output(
    *,
    records: tuple[Any, ...],
    payload: object,
    lines: tuple[str, ...],
    output_format: str,
    output: Path | None,
    label: str,
) -> None:
    normalized = output_format.strip().lower()
    if normalized == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_breakout_reference_json(payload, output)
        print(f"{label} written: {output}")
        return
    if normalized == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_breakout_reference_csv(records, output)
        print(f"{label} written: {output}")
        return
    if normalized != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{label} written: {output}")
        return
    print()
    for line in lines:
        print(line)


def _emit_breakout_gap_output(
    *,
    records: tuple[Any, ...],
    payload: object,
    lines: tuple[str, ...],
    output_format: str,
    output: Path | None,
    label: str,
) -> None:
    normalized = output_format.strip().lower()
    if normalized == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_breakout_gap_json(payload, output)
        print(f"{label} written: {output}")
        return
    if normalized == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_breakout_gap_csv(records, output)
        print(f"{label} written: {output}")
        return
    if normalized != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{label} written: {output}")
        return
    print()
    for line in lines:
        print(line)


def _historical_source_report(
    *,
    sample: bool,
    full_population: bool,
    provider: str | None = None,
    symbol: str | None = None,
    candidate_id: str | None = None,
    year: int | None = None,
    gap_cause: str | None = None,
    credentials_status: str = "auto",
    dry_run: bool = False,
    refresh: bool = False,
) -> HistoricalSourceRecommendationReport:
    if sample and full_population:
        raise typer.BadParameter(
            "--sample and --full-population are mutually exclusive."
        )
    if refresh:
        raise typer.BadParameter(
            "--refresh is unsupported: no lawful read-only live evaluation "
            "adapter is configured."
        )
    try:
        parsed_cause = (
            parse_breakout_gap_cause(gap_cause) if gap_cause is not None else None
        )
        parsed_credentials: HistoricalCredentialStatus | None = (
            parse_historical_credential_status(credentials_status)
        )
        return build_project_historical_source_evaluation(
            provider=provider,
            full_population=full_population,
            symbol=symbol,
            candidate_id=candidate_id,
            year=year,
            gap_cause=parsed_cause,
            credential_status=parsed_credentials,
            dry_run=dry_run,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


def _emit_historical_source_output(
    *,
    payload: object,
    rows: tuple[dict[str, object], ...],
    lines: tuple[str, ...],
    output_format: str,
    output: Path | None,
    label: str,
) -> None:
    normalized = output_format.strip().lower()
    if normalized == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_historical_source_json(payload, output)
        print(f"{label} written: {output}")
        return
    if normalized == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_historical_source_csv(rows, output)
        print(f"{label} written: {output}")
        return
    if normalized != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{label} written: {output}")
        return
    print()
    for line in lines:
        print(line)


def _upstox_historical_probe_service() -> UpstoxHistoricalProbeService:
    evidence_path = Path(
        os.environ.get(
            "ALPHA_UPSTOX_HISTORICAL_EVIDENCE_PATH",
            str(DEFAULT_UPSTOX_HISTORICAL_EVIDENCE_PATH),
        )
    )
    return UpstoxHistoricalProbeService(
        repository=UpstoxHistoricalEvidenceRepository(evidence_path)
    )


def _historical_identity_audit_bundle() -> HistoricalIdentityAuditBundle:
    return ProjectHistoricalIdentityAuditService().build()


def _filtered_historical_identity_records(
    bundle: HistoricalIdentityAuditBundle,
    *,
    candidate_id: str | None,
    symbol: str | None,
    status: str | None,
    source: str | None,
    year: int | None,
    inactive: bool,
    renamed: bool,
    limit: int | None,
) -> tuple[EffectiveDatedIdentityRecord, ...]:
    try:
        return filter_identity_records(
            bundle.bridge.records,
            candidate_id=candidate_id,
            symbol=symbol,
            status=status,
            source=source,
            year=year,
            inactive=inactive,
            renamed=renamed,
            limit=limit,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None


def _emit_historical_identity_output(
    *,
    payload: Any,
    records: tuple[EffectiveDatedIdentityRecord, ...],
    lines: tuple[str, ...],
    output_format: str,
    output: Path | None,
    label: str,
) -> None:
    normalized = output_format.strip().lower()
    if normalized not in {"text", "json", "csv"}:
        raise typer.BadParameter("--format must be text, json, or csv")
    if normalized == "text":
        rendered = "\n".join(lines) + "\n"
        if output is None:
            print(rendered, end="")
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered, encoding="utf-8")
            print(f"Wrote {label}: {output}")
        return
    if output is None:
        raise typer.BadParameter(f"--output is required for --format {normalized}")
    if normalized == "json":
        export_identity_json(payload, output)
    elif records:
        export_identity_records_csv(records, output)
    else:
        export_identity_summary_csv(payload, output)
    print(f"Wrote {label}: {output}")


def _nse_archive_proof_bundle(
    *,
    market_date: str | None,
    date_from: str | None,
    date_to: str | None,
    live: bool,
    authorization_reference: str | None,
) -> NseArchiveProofBundle:
    start, end = _nse_date_scope(
        market_date=market_date,
        date_from=date_from,
        date_to=date_to,
    )
    try:
        return ProjectNseArchiveProofService().build(
            date_from=start,
            date_to=end,
            live=live,
            authorization_reference=authorization_reference,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None


def _nse_date_scope(
    *,
    market_date: str | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[dt_date, dt_date]:
    if market_date is not None and (date_from is not None or date_to is not None):
        raise typer.BadParameter("--date cannot be combined with --date-from/--date-to")
    if market_date is not None:
        parsed = _parse_iso_date(market_date, "--date")
        return parsed, parsed
    start = (
        _parse_iso_date(date_from, "--date-from")
        if date_from is not None
        else NSE_TRIAL_DATE_FROM
    )
    end = (
        _parse_iso_date(date_to, "--date-to")
        if date_to is not None
        else NSE_TRIAL_DATE_TO
    )
    if end < start:
        raise typer.BadParameter("--date-to cannot precede --date-from")
    return start, end


def _parse_iso_date(value: str, option: str) -> dt_date:
    try:
        return dt_date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(f"{option} must use YYYY-MM-DD") from exc


def _parse_nse_source_type(value: str | None) -> NseArchiveSourceType | None:
    if value is None:
        return None
    try:
        return NseArchiveSourceType(value.strip().upper())
    except ValueError as exc:
        choices = ", ".join(item.value for item in NseArchiveSourceType)
        raise typer.BadParameter(f"--source-type must be one of: {choices}") from exc


def _require_bhavcopy_source(value: str | None) -> None:
    parsed = _parse_nse_source_type(value)
    if parsed not in {None, NseArchiveSourceType.CM_BHAVCOPY}:
        raise typer.BadParameter(
            "this proof currently has candidate-date rows only from CM_BHAVCOPY"
        )


def _filter_nse_identity_records(
    records: tuple[NseIdentityProofRecord, ...],
    *,
    market_date: str | None,
    date_from: str | None,
    date_to: str | None,
    symbol: str | None,
    candidate_id: str | None,
) -> tuple[NseIdentityProofRecord, ...]:
    normalized_symbol = symbol.strip().upper() if symbol else None
    exact_date = _parse_iso_date(market_date, "--date") if market_date else None
    start = _parse_iso_date(date_from, "--date-from") if date_from else None
    end = _parse_iso_date(date_to, "--date-to") if date_to else None
    selected = tuple(
        item
        for item in records
        if candidate_id is None or item.candidate_id == candidate_id
        if normalized_symbol is None or item.historical_symbol == normalized_symbol
        if exact_date is None or item.candidate_date == exact_date
        if start is None or item.candidate_date >= start
        if end is None or item.candidate_date <= end
    )
    if candidate_id is not None and not selected:
        raise typer.BadParameter(f"candidate id not found: {candidate_id}")
    return selected


def _filter_nse_corporate_action_records(
    records: tuple[NseCorporateActionProofRecord, ...],
    *,
    market_date: str | None,
    date_from: str | None,
    date_to: str | None,
    symbol: str | None,
    candidate_id: str | None,
) -> tuple[NseCorporateActionProofRecord, ...]:
    normalized_symbol = symbol.strip().upper() if symbol else None
    exact_date = _parse_iso_date(market_date, "--date") if market_date else None
    start = _parse_iso_date(date_from, "--date-from") if date_from else None
    end = _parse_iso_date(date_to, "--date-to") if date_to else None
    selected = tuple(
        item
        for item in records
        if candidate_id is None or item.candidate_id == candidate_id
        if normalized_symbol is None or item.symbol.upper() == normalized_symbol
        if exact_date is None or item.candidate_date == exact_date
        if start is None or item.candidate_date >= start
        if end is None or item.candidate_date <= end
    )
    if candidate_id is not None and not selected:
        raise typer.BadParameter(f"candidate id not found: {candidate_id}")
    return selected


def _selected_nse_corporate_action_report(
    bundle: NseArchiveProofBundle,
    records: tuple[NseCorporateActionProofRecord, ...],
) -> Any:
    status_values = [item.status.value for item in records]
    return replace(
        bundle.corporate_actions,
        cases_evaluated=len(records),
        events_found=sum(value != "NSE_CA_NOT_FOUND" for value in status_values),
        complete_cases=status_values.count("NSE_CA_EVIDENCE_COMPLETE"),
        partial_cases=status_values.count("NSE_CA_EVENT_FOUND_FIELDS_PARTIAL"),
        circular_only_cases=status_values.count("NSE_CA_CIRCULAR_ONLY"),
        conflicts=status_values.count("NSE_CA_CONFLICT"),
        not_found=status_values.count("NSE_CA_NOT_FOUND"),
        records=records,
    )


def _emit_nse_proof_output(
    *,
    payload: Any,
    rows: tuple[Any, ...],
    lines: tuple[str, ...],
    output_format: str,
    output: Path | None,
    label: str,
) -> None:
    normalized = output_format.strip().lower()
    if normalized not in {"text", "json", "csv"}:
        raise typer.BadParameter("--format must be text, json, or csv")
    if normalized == "text":
        rendered = "\n".join(lines) + "\n"
        if output is None:
            print(rendered, end="")
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered, encoding="utf-8")
            print(f"Wrote {label}: {output}")
        return
    if output is None:
        raise typer.BadParameter(f"--output is required for --format {normalized}")
    if normalized == "json":
        export_nse_proof_json(payload, output)
    else:
        export_nse_proof_csv(rows or (payload,), output)
    print(f"Wrote {label}: {output}")


def _run_upstox_historical_probe(
    *,
    live: bool,
    sample: bool,
    full_population: bool,
    confirm_full_population: bool,
    candidate_id: str | None,
    symbol: str | None,
    year: int | None,
    gap_cause: str | None,
    limit: int | None,
    resume: bool,
    dry_run: bool,
) -> UpstoxHistoricalProbeRun:
    try:
        parsed_cause = (
            parse_breakout_gap_cause(gap_cause) if gap_cause is not None else None
        )
        return _upstox_historical_probe_service().run(
            live=live,
            sample=sample,
            full_population=full_population,
            confirm_full_population=confirm_full_population,
            candidate_id=candidate_id,
            symbol=symbol,
            year=year,
            gap_cause=parsed_cause,
            limit=limit,
            resume=resume,
            dry_run=dry_run,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


def _upstox_records(
    run: UpstoxHistoricalProbeRun,
) -> tuple[UpstoxHistoricalCandidateEvidence, ...]:
    return run.dataset.records if run.dataset is not None else ()


def _emit_upstox_probe_output(
    *,
    payload: object,
    records: tuple[UpstoxHistoricalCandidateEvidence, ...],
    lines: tuple[str, ...],
    output_format: str,
    output: Path | None,
    label: str,
) -> None:
    normalized = output_format.strip().lower()
    if normalized in {"json", "csv"} and output is None:
        raise typer.BadParameter(f"--output is required for {normalized} export.")
    if normalized == "json":
        assert output is not None
        output.parent.mkdir(parents=True, exist_ok=True)
        export_upstox_evidence_json(payload, output)
        print(f"{label} written: {output}")
        return
    if normalized == "csv":
        assert output is not None
        output.parent.mkdir(parents=True, exist_ok=True)
        if records:
            export_upstox_evidence_csv(records, output)
        else:
            with output.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(("field", "value"))
                for line in lines:
                    field, separator, value = line.partition(":")
                    writer.writerow((field, value.strip() if separator else ""))
        print(f"{label} written: {output}")
        return
    if normalized != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{label} written: {output}")
        return
    print()
    for line in lines:
        print(line)


def _emit_upstox_series_integrity_output(
    report: UpstoxSeriesIntegrityReport,
    *,
    lines: tuple[str, ...],
    output_format: str,
    output: Path | None,
) -> None:
    normalized = output_format.strip().lower()
    if normalized in {"json", "csv"} and output is None:
        raise typer.BadParameter(f"--output is required for {normalized} export.")
    if normalized == "json":
        assert output is not None
        output.parent.mkdir(parents=True, exist_ok=True)
        export_upstox_evidence_json(report, output)
        print(f"Upstox series integrity written: {output}")
        return
    if normalized == "csv":
        assert output is not None
        export_upstox_series_integrity_csv(report, output)
        print(f"Upstox series integrity written: {output}")
        return
    if normalized != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Upstox series integrity written: {output}")
        return
    print()
    for line in lines:
        print(line)


def _emit_opportunity_evolution_report(
    report: Any,
    *,
    output_format: str,
    output: Path | None,
    group_by: str | None,
    renderer: Callable[[Any], tuple[str, ...]],
    label: str,
) -> None:
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_opportunity_evolution_json(report, output)
        print(f"{label} written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_opportunity_evolution_csv(report, output)
        print(f"{label} written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    if group_by is not None:
        print(f"{label.title()} Grouped By {group_by}:")
        for line in group_opportunity_report(report, group_by):
            print(line)
        return
    for line in renderer(report):
        print(line)


def _emit_buy_reconstruction_report(
    report: Any,
    *,
    output_format: str,
    output: Path | None,
    group_by: str | None,
    model: str | None,
    renderer: Callable[[Any], tuple[str, ...]],
    label: str,
) -> None:
    if output_format == "json":
        if output is None:
            raise typer.BadParameter("--output is required for json export.")
        export_buy_reconstruction_json(report, output)
        print(f"{label} written: {output}")
        return
    if output_format == "csv":
        if output is None:
            raise typer.BadParameter("--output is required for csv export.")
        export_buy_model_results_csv(filter_buy_model_results(report, model), output)
        print(f"{label} written: {output}")
        return
    if output_format != "text":
        raise typer.BadParameter("format must be text, json, or csv.")
    print()
    if group_by is not None:
        print(f"{label.title()} Grouped By {group_by}:")
        for line in group_buy_report(report, group_by):
            print(line)
        return
    if model is not None:
        for line in render_buy_minimal_models(
            replace(report, comparison_table=filter_buy_model_results(report, model))
        ):
            print(line)
        return
    for line in renderer(report):
        print(line)


def _directional_observation_from_audit_row(
    row: Any,
) -> DirectionalObservation:
    forward_return = _decimal_to_ratio(row.forward_return)
    mfe = _decimal_to_ratio(row.mfe)
    mae = _decimal_to_ratio(row.mae)
    target_day = 1 if row.target_before_stop or row.target_hit else None
    stop_day = 1 if row.stop_before_target or row.stop_hit else None
    if target_day is not None and stop_day is not None:
        if row.target_before_stop:
            stop_day = 2
        elif row.stop_before_target:
            target_day = 2
    return DirectionalObservation(
        symbol=row.symbol,
        observed_at=dt_date.fromisoformat(row.replay_date),
        horizon_days=20,
        forward_return=forward_return,
        max_favorable_excursion=mfe,
        max_adverse_excursion=mae,
        recommendation_score=_decimal_score(row.recommendation_score) or 0.0,
        posterior_probability=_decimal_score(row.posterior_probability),
        price_component=_decimal_score(row.indicator_scores.get("price_volume")),
        setup_quality=_decimal_score(row.indicator_scores.get("setup_quality")),
        retracement_score=_decimal_score(row.indicator_scores.get("retracement")),
        entry_timing=row.entry_state.value,
        regime=row.market_regime or "UNAVAILABLE",
        setup_type=row.setup_type or "UNAVAILABLE",
        trade_plan_quality=_decimal_score(row.indicator_scores.get("trade_plan")),
        stop_distance_pct=None,
        expected_value=_decimal_to_ratio(row.expectancy),
        confidence=_confidence_score(row.confidence),
        completed=True,
        upside_barrier_day=target_day,
        downside_barrier_day=stop_day,
        sector=row.sector or "UNAVAILABLE",
        source="candidate_learning_directional_audit",
        feature_values=tuple(
            sorted(
                (
                    key,
                    _decimal_score(value) or 0.0,
                )
                for key, value in row.indicator_scores.items()
            )
        ),
    )


def _decimal_to_ratio(value: Decimal | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number / 100 if abs(number) > 1 else number


def _decimal_score(value: Decimal | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    if number > 1:
        number /= 100
    return min(max(number, 0.0), 1.0)


def _confidence_score(value: str) -> float | None:
    return {
        "LOW": 0.35,
        "MEDIUM": 0.55,
        "HIGH": 0.75,
        "VERY_HIGH": 0.90,
    }.get(value.strip().upper())


def _render_precision_frontier_group(
    report: PrecisionCoverageReport,
    group_by: str,
) -> tuple[str, ...]:
    lines = [
        f"Precision-Coverage Frontier Grouped By {group_by}",
        "PRODUCTION_INFLUENCE=false",
    ]
    lines.extend(_group_frontier_points(report.frontier, group_by))
    return tuple(lines)


def _group_frontier_points(
    points: tuple[FrontierPoint, ...],
    group_by: str,
) -> tuple[str, ...]:
    normalized = group_by.strip().lower()
    if normalized == "policy":
        return tuple(
            f"- {point.policy.policy_id}: precision "
            f"{_percentage(point.metrics.precision)}, "
            f"signals {point.metrics.accepted_signals}, "
            f"constraints {'PASS' if point.constraints.passed else 'FAIL'}"
            for point in points
        )
    if normalized == "horizon":
        return ("- horizon=20 trading days: diagnostic fixture default",)
    if normalized in {"year", "regime", "setup", "timing"}:
        counter: dict[str, int] = {}
        for point in points:
            source = _point_distribution(point, normalized)
            for key, value in source:
                counter[key] = counter.get(key, 0) + value
        if not counter:
            return ("- unavailable",)
        sorted_items = sorted(
            counter.items(),
            key=lambda item: (-item[1], item[0]),
        )
        return tuple(f"- {key}: {value}" for key, value in sorted_items)
    raise typer.BadParameter(
        "group-by must be year, regime, setup, timing, horizon, or policy."
    )


def _point_distribution(
    point: FrontierPoint,
    group_by: str,
) -> tuple[tuple[str, int], ...]:
    if group_by == "regime":
        return point.regime_distribution
    if group_by == "setup":
        return point.setup_distribution
    if group_by == "timing":
        return point.timing_distribution
    if group_by == "year":
        return (("all-years", point.metrics.accepted_signals),)
    return ()


def _percentage(value: float | None) -> str:
    return "unavailable" if value is None else f"{value * 100:.2f}%"


def _parse_regime_filter(value: str) -> tuple[MarketRegime, ...] | None:
    normalized = value.strip().upper()
    if normalized == "ALL":
        return None
    try:
        return (MarketRegime(normalized),)
    except ValueError as error:
        raise typer.BadParameter(f"Unsupported regime: {value}") from error


def _parse_strategy_filter(value: str) -> tuple[str, ...] | None:
    normalized = value.strip().lower()
    if normalized == "all":
        return None
    return tuple(item.strip() for item in normalized.split(",") if item.strip())


def _parse_holding_period_filter(value: str) -> tuple[HoldingPeriod, ...] | None:
    normalized = value.strip().lower()
    if normalized == "all":
        return None
    periods = []
    for item in normalized.split(","):
        try:
            periods.append(HoldingPeriod(item.strip()))
        except ValueError as error:
            raise typer.BadParameter(f"Unsupported holding period: {item}") from error
    return tuple(periods)


def _exit_with_error(title: str, exc: ProjectAlphaError) -> None:
    typer.echo(f"{title}: {exc}", err=True)
    raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()
