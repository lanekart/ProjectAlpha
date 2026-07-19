from __future__ import annotations

import csv
import io
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.application.research_cli import ResearchCLIService
from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
)
from alpha.cli import app
from alpha.research.metric_truth_audit import (
    MetricTruthAuditEngine,
    MetricTruthAuditReport,
    RegimeMetricConclusion,
    StrictApprovalZeroConclusion,
    metric_truth_csv,
    metric_truth_experiment,
    metric_truth_json,
)
from alpha.research.models import (
    BottleneckStatus,
    DiagnosticEvidence,
    DiagnosticState,
    EvidenceQuality,
    ExperimentStatus,
    MetricAvailability,
    MetricProvenance,
    ResearchConfidence,
    ResearchMaturity,
    ResearchMetric,
    ResearchSubsystem,
)
from alpha.research.research_registry import ResearchExperimentRegistry

runner = CliRunner()


@pytest.fixture(scope="module")
def audit_inputs() -> tuple[
    tuple[CandidateDecisionRecord, ...],
    tuple[CandidateForwardOutcome, ...],
]:
    records: list[CandidateDecisionRecord] = []
    outcomes: list[CandidateForwardOutcome] = []
    index = 0
    for is_earlier, count, wins in ((True, 41, 13), (False, 29, 11)):
        for offset in range(count):
            index += 1
            record = _record(
                index,
                evaluation_date=(date(2016, 12, 1) if is_earlier else date(2017, 1, 3)),
                market_regime="NEGATIVE" if index == 1 else "NEUTRAL",
            )
            records.append(record)
            outcomes.append(_outcome(record, profitable=offset < wins))
    for is_earlier, count in ((True, 4), (False, 1)):
        for _ in range(count):
            index += 1
            records.append(
                _record(
                    index,
                    evaluation_date=(
                        date(2016, 12, 1) if is_earlier else date(2017, 1, 3)
                    ),
                )
            )
    return tuple(records), tuple(outcomes)


@pytest.fixture(scope="module")
def report(
    audit_inputs: tuple[
        tuple[CandidateDecisionRecord, ...],
        tuple[CandidateForwardOutcome, ...],
    ],
) -> MetricTruthAuditReport:
    records, outcomes = audit_inputs
    return MetricTruthAuditEngine().audit(
        records=records,
        outcomes=outcomes,
        diagnostics=_diagnostics(),
    )


def test_approval_definitions_remain_separate(report: MetricTruthAuditReport) -> None:
    names = tuple(item.canonical_name for item in report.approval_definitions)

    assert names == (
        "RAW_APPROVAL",
        "STRICT_INSTITUTIONAL_APPROVAL",
        "RECOMMENDATION_BUY",
        "ACTIONABLE_CANDIDATE",
        "ENTRY_TIMING_APPROVAL",
        "GATEKEEPER_APPROVAL",
        "LEGACY_LONG_TRADE_PERMISSION",
    )
    raw = report.approval_definitions[0]
    strict = report.approval_definitions[1]
    assert raw.approval_count == 75
    assert raw.eligible_approval_count == 70
    assert strict.approval_count == 0
    assert strict.precision_status is MetricAvailability.NOT_ESTIMABLE


def test_exact_precision_and_population_reconciliation(
    report: MetricTruthAuditReport,
) -> None:
    item = report.reconciliation

    assert item.earlier_precision == Decimal("0.3171")
    assert item.earlier_successful_approvals == 13
    assert item.earlier_approval_count == 41
    assert item.earlier_incomplete_approvals == 4
    assert item.current_precision == Decimal("0.3429")
    assert item.current_successful_approvals == 24
    assert item.current_approval_count == 70
    assert item.current_incomplete_approvals == 5
    assert len(item.candidates_in_both) == 41
    assert item.earlier_only_candidates == ()
    assert len(item.current_only_candidates) == 29
    assert item.outcome_classification_differences == ()
    assert item.added_successes == 11
    assert item.added_failures == 18
    assert item.precision_delta == Decimal("0.0258")
    assert item.unexplained_remainder == Decimal("0")


def test_canonical_contract_and_wilson_interval(
    report: MetricTruthAuditReport,
) -> None:
    raw = report.raw_approval_contract
    strict = report.strict_approval_contract

    assert raw.numerator == 24
    assert raw.denominator == 70
    assert raw.precision == Decimal("0.3429")
    assert raw.confidence_interval_low == Decimal("0.2425")
    assert raw.confidence_interval_high == Decimal("0.4596")
    assert strict.denominator == 0
    assert strict.precision is None
    assert strict.precision_status is MetricAvailability.NOT_ESTIMABLE


def test_not_estimable_is_distinct_from_numeric_zero() -> None:
    metric = ResearchMetric(
        metric_id="strict.precision",
        label="Strict precision",
        value=None,
        unit="ratio",
        numerator=0,
        denominator=0,
        availability=MetricAvailability.NOT_ESTIMABLE,
        provenance=_provenance(),
    )

    assert metric.value is None
    assert metric.availability_status is MetricAvailability.NOT_ESTIMABLE
    assert not metric.available


def test_percentage_as_fraction_protection() -> None:
    with pytest.raises(ValueError, match="between zero and one"):
        ResearchMetric(
            metric_id="bad.percentage",
            label="Bad percentage",
            value=Decimal("34.29"),
            unit="ratio",
            provenance=_provenance(),
        )


def test_strict_zero_count_has_gate_level_attribution(
    report: MetricTruthAuditReport,
) -> None:
    item = report.strict_attribution

    assert item.strict_approvals == 0
    assert item.implementation_matches_predicate
    assert item.conclusion is (
        StrictApprovalZeroConclusion.VALID_BUT_OVERRESTRICTIVE_POLICY
    )
    assert item.profitable_rejected_candidates == 24
    assert item.gate_survival[0].gate_id == "RAW_RECORDED_APPROVAL"
    assert item.gate_survival[0].survived == 75
    assert item.gate_survival[-1].survived == 0
    assert sum(row.count for row in item.mutually_exclusive_primary_failures) == 75
    assert item.overlapping_failures
    assert item.extended_diagnostic_failures


def test_regime_confusion_matrix_and_balanced_accuracy(
    report: MetricTruthAuditReport,
) -> None:
    item = report.regime_truth
    matrix = {
        (cell.actual_label, cell.predicted_label): cell.count
        for cell in item.confusion_matrix
    }

    assert item.class_labels == (
        "BULLISH_TREND",
        "BEARISH_TREND",
        "SIDEWAYS",
        "CORRECTION",
        "HIGH_VOLATILITY",
        "RECOVERY",
    )
    assert matrix[("BEARISH_TREND", "BEARISH_TREND")] == 1
    assert matrix[("BEARISH_TREND", "SIDEWAYS")] == 74
    assert item.independently_recomputed_balanced_accuracy == Decimal("0.0133")
    assert item.source_reported_balanced_accuracy == Decimal("0.0133")
    assert item.majority_class_baseline == Decimal("1.0000")
    assert item.coverage == Decimal("1.0000")
    assert item.conclusion is RegimeMetricConclusion.SCALE_OR_RENDERING_DEFECT
    assert not item.metric_valid_for_decision


def test_missing_and_unknown_regime_labels_are_excluded(
    audit_inputs: tuple[
        tuple[CandidateDecisionRecord, ...],
        tuple[CandidateForwardOutcome, ...],
    ],
) -> None:
    records, outcomes = audit_inputs
    changed = (replace(records[0], market_regime=None),) + records[1:]

    result = MetricTruthAuditEngine().audit(records=changed, outcomes=outcomes)

    assert result.regime_truth.observations == 74
    assert result.regime_truth.excluded_observations == 1
    assert result.regime_truth.unknown_predicted_labels == 1
    assert result.regime_truth.excluded_reasons == (
        ("PREDICTION_UNKNOWN_OR_UNAVAILABLE", 1),
    )


def test_all_eight_ird_adapters_preserve_metric_contracts(
    report: MetricTruthAuditReport,
) -> None:
    assert len(report.adapter_validations) == 8
    assert all(item.provenance_complete for item in report.adapter_validations)
    assert all(item.units_valid for item in report.adapter_validations)
    assert all(
        item.fraction_percentage_semantics_valid for item in report.adapter_validations
    )
    assert all(item.numerator_denominator_valid for item in report.adapter_validations)
    assert all(item.safe_for_prioritization for item in report.adapter_validations)
    assert "market-regime-audit" not in " ".join(report.roadmap_after)


def test_json_and_csv_exports_are_deterministic(
    report: MetricTruthAuditReport,
) -> None:
    json_text = metric_truth_json(report)
    csv_text = metric_truth_csv(report)
    payload = json.loads(json_text)
    rows = tuple(csv.DictReader(io.StringIO(csv_text)))

    assert json_text == metric_truth_json(report)
    assert payload["production_influence"] is False
    assert payload["raw_approval_contract"]["numerator"] == 24
    assert rows[0]["section"] == "approval_definition"
    assert any(row["section"] == "strict_gate" for row in rows)
    assert any(row["section"] == "regime_class" for row in rows)
    assert any(row["section"] == "ird_adapter" for row in rows)


def test_completed_audit_persists_idempotently_in_registry(
    report: MetricTruthAuditReport,
    tmp_path: Path,
) -> None:
    registry = ResearchExperimentRegistry(tmp_path / "registry.json")
    experiment = metric_truth_experiment(report)

    assert registry.record(experiment)
    assert not registry.record(experiment)
    stored = registry.load()[0]
    assert stored.status is ExperimentStatus.COMPLETED
    assert stored.findings
    assert stored.lessons_learned
    assert stored.production_influence is False


def test_metric_truth_cli_commands_and_rendering(
    report: MetricTruthAuditReport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ResearchCLIService,
        "metric_truth_report",
        lambda self: report,
    )

    precision = runner.invoke(app, ["research", "approval-precision-truth"])
    reconciliation = runner.invoke(
        app,
        ["research", "approval-population-reconciliation"],
    )
    regime = runner.invoke(app, ["research", "regime-metric-truth"])
    summary = runner.invoke(app, ["research", "metric-truth-summary"])

    assert precision.exit_code == 0
    assert "Approval Definition Inventory" in precision.stdout
    assert "STRICT_INSTITUTIONAL_APPROVAL_PRECISION" in precision.stdout
    assert "Mutually Exclusive Primary Failures" in precision.stdout
    assert "Overlapping Strict Predicate Failures" in precision.stdout
    assert "Extended Diagnostic Failures" in precision.stdout
    assert reconciliation.exit_code == 0
    assert "Unexplained Remainder: 0" in reconciliation.stdout
    assert regime.exit_code == 0
    assert "Confusion Matrix" in regime.stdout
    assert "SCALE_OR_RENDERING_DEFECT" in regime.stdout
    assert summary.exit_code == 0
    assert "Authoritative Raw Approval Precision: 34.29% (24/70)" in summary.stdout
    assert "Strict Institutional Approval Precision: NOT_ESTIMABLE" in summary.stdout
    for result in (precision, reconciliation, regime, summary):
        assert "PRODUCTION_INFLUENCE=false" in result.stdout


def test_metric_truth_cli_supports_json_csv_and_export(
    report: MetricTruthAuditReport,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ResearchCLIService,
        "metric_truth_report",
        lambda self: report,
    )
    destination = tmp_path / "truth.csv"

    json_result = runner.invoke(
        app,
        ["research", "metric-truth-summary", "--format", "json"],
    )
    export_result = runner.invoke(
        app,
        [
            "research",
            "regime-metric-truth",
            "--format",
            "csv",
            "--output",
            str(destination),
        ],
    )

    assert json_result.exit_code == 0
    assert '"production_influence": false' in json_result.stdout
    assert export_result.exit_code == 0
    assert destination.read_text(encoding="utf-8").startswith("section,key,label")


def test_documentation_and_policy_isolation(report: MetricTruthAuditReport) -> None:
    path = Path("docs/APPROVAL_PRECISION_AND_REGIME_METRIC_TRUTH.md")
    text = path.read_text(encoding="utf-8")

    assert "PRODUCTION_INFLUENCE=false" in text
    assert "NOT_ESTIMABLE" in text
    assert "SCALE_OR_RENDERING_DEFECT" in text
    assert report.production_influence is False
    assert all(not item.production_influence for item in _diagnostics())


def _record(
    index: int,
    *,
    evaluation_date: date,
    market_regime: str = "NEUTRAL",
) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        candidate_id=f"candidate-{index:03d}",
        run_id="metric-truth-fixture",
        evaluation_date=evaluation_date,
        symbol=f"STOCK{index:03d}",
        final_verdict="BUY",
        capital_action="BUY",
        approved_for_deployment=True,
        rejection_reasons=(),
        setup_type="BREAKOUT",
        market_regime=market_regime,
        long_trade_permission=True,
        strategy_score=Decimal("80"),
        confidence="HIGH",
        data_quality="MISSING",
        entry_zone_low=Decimal("90"),
        entry_zone_high=Decimal("100"),
        confirmation_entry=Decimal("101"),
        risk_stop=Decimal("90"),
        target_1=Decimal("112"),
        target_2=Decimal("123"),
        target_3=Decimal("134"),
        trailing_stop_plan="2 x ATR",
        expected_holding_period="20 days",
        indicators_active=("price",),
        indicator_scores={"price": "0.5"},
        evidence_layers=("price",),
        explanation="Deterministic metric truth fixture.",
        created_at=datetime(2026, 7, 18, tzinfo=UTC),
    )


def _outcome(
    record: CandidateDecisionRecord,
    *,
    profitable: bool,
) -> CandidateForwardOutcome:
    change = Decimal("1") if profitable else Decimal("-1")
    return CandidateForwardOutcome(
        candidate_id=record.candidate_id,
        symbol=record.symbol,
        evaluated_at=datetime(2026, 7, 18, tzinfo=UTC),
        windows=(
            CandidateForwardWindowOutcome(
                window="20d",
                forward_open=Decimal("100"),
                forward_high=Decimal("102"),
                forward_low=Decimal("98"),
                forward_close=Decimal("100") + change,
                forward_return_pct_from_close=change,
                forward_return_pct_from_entry=change,
                max_favourable_excursion_pct=Decimal("2"),
                max_adverse_excursion_pct=Decimal("-2"),
                target_1_touched=False,
                risk_stop_touched=False,
                outcome_label=(
                    CandidateOutcomeLabel.WOULD_HAVE_WON
                    if profitable
                    else CandidateOutcomeLabel.WOULD_HAVE_LOST
                ),
            ),
        ),
    )


def _diagnostics() -> tuple[DiagnosticEvidence, ...]:
    ids = (
        "approval-diagnostics",
        "corporate-action-coverage",
        "directional-signal-audit",
        "entry-timing-audit",
        "identity-coverage",
        "market-regime-audit",
        "point-in-time-audit",
        "replay-readiness",
    )
    result = []
    for diagnostic_id in ids:
        invalid_regime = diagnostic_id == "market-regime-audit"
        metric_id = (
            "market_regime.balanced_accuracy"
            if invalid_regime
            else f"{diagnostic_id}.coverage"
        )
        metric = ResearchMetric(
            metric_id=metric_id,
            label=metric_id,
            value=None if invalid_regime else Decimal("0.5000"),
            unit="ratio",
            numerator=None if invalid_regime else 1,
            denominator=None if invalid_regime else 2,
            availability=(
                MetricAvailability.INVALID
                if invalid_regime
                else MetricAvailability.AVAILABLE
            ),
            provenance=_provenance(),
        )
        result.append(
            DiagnosticEvidence(
                diagnostic_id=diagnostic_id,
                title=diagnostic_id,
                subsystem=(
                    ResearchSubsystem.MARKET_REGIME
                    if invalid_regime
                    else ResearchSubsystem.RESEARCH_GOVERNANCE
                ),
                source_module=f"tests.{diagnostic_id}",
                source_version="test-v1",
                state=DiagnosticState.PARTIAL,
                maturity=ResearchMaturity.UNKNOWN,
                evidence_quality=EvidenceQuality.HIGH,
                confidence=ResearchConfidence.HIGH,
                bottleneck_status=(
                    BottleneckStatus.UNKNOWN
                    if invalid_regime
                    else BottleneckStatus.PROVEN
                ),
                metrics=(metric,),
                finding="Deterministic fixture evidence.",
                recommended_action="Keep the evidence contract explicit.",
            )
        )
    return tuple(result)


def _provenance() -> MetricProvenance:
    return MetricProvenance(
        source="deterministic fixture",
        definition="direct fraction",
        population="fixture candidates",
        version="test-v1",
    )
