"""Evidence-only purchase justification policy for WDA."""

from __future__ import annotations

from decimal import Decimal

from alpha.warehouse_delta_audit.models import (
    AuditStatus,
    ConfidenceLevel,
    DecisionDeltaRecord,
    DecisionSeverity,
    PersonalDecision,
    PriceDeltaRecord,
    PurchaseRecommendation,
    ReplayDeltaRecord,
    SourceLineage,
)


def purchase_decision(
    *,
    source_lineage: SourceLineage,
    prices: tuple[PriceDeltaRecord, ...],
    decisions: tuple[DecisionDeltaRecord, ...],
    replay: tuple[ReplayDeltaRecord, ...],
    corporate_actions_available: bool,
    spans_five_years: bool,
) -> tuple[
    PurchaseRecommendation,
    PersonalDecision,
    ConfidenceLevel,
    AuditStatus,
    str,
    str,
]:
    """Return a procurement conclusion without treating difference as improvement."""

    independent = source_lineage is SourceLineage.INDEPENDENT_OFFICIAL
    paired = sum(item.matched_observations for item in prices)
    material = sum(
        item.severity in {DecisionSeverity.MATERIAL, DecisionSeverity.CRITICAL}
        for item in decisions
    )
    critical = sum(item.severity is DecisionSeverity.CRITICAL for item in decisions)
    expectancy = _metric(replay, "expectancy")
    drawdown = _metric(replay, "maximum_drawdown")
    capture = _metric(replay, "opportunity_capture")
    if not independent:
        reason = (
            "The paired run is a same-lineage ingestion control, not an independent "
            "Warehouse v2 experiment. Agreement can validate loading integrity but "
            "cannot measure the incremental value of a paid NSE/BSE source."
        )
        return (
            PurchaseRecommendation.PURCHASE_NOT_JUSTIFIED,
            PersonalDecision.NOT_YET,
            ConfidenceLevel.LOW if paired else ConfidenceLevel.INSUFFICIENT,
            (
                AuditStatus.COMPLETE_SAME_LINEAGE_CONTROL
                if paired
                else AuditStatus.INSUFFICIENT_PAIRED_EVIDENCE
            ),
            "Independent Alpha improvement remains UNKNOWN; only same-lineage "
            "deltas were observed.",
            reason,
        )
    if paired == 0 or not spans_five_years:
        return (
            PurchaseRecommendation.PURCHASE_NOT_JUSTIFIED,
            PersonalDecision.NOT_YET,
            ConfidenceLevel.INSUFFICIENT,
            AuditStatus.INSUFFICIENT_PAIRED_EVIDENCE,
            "Alpha improvement is not estimable from the supplied paired population.",
            "The independent sample lacks sufficient paired observations or "
            "five-year depth.",
        )
    positive_replay = (
        expectancy is not None
        and expectancy > 0
        and (drawdown is None or drawdown <= 0)
        and (capture is None or capture >= 0)
    )
    decision_rate = material / max(len(decisions), 1)
    critical_rate = critical / max(len(decisions), 1)
    if corporate_actions_available and positive_replay and critical_rate >= 0.01:
        return (
            PurchaseRecommendation.PURCHASE_HIGH_PRIORITY,
            PersonalDecision.YES,
            ConfidenceLevel.HIGH,
            AuditStatus.COMPLETE,
            "Independent official data improved replay and changed at least 1% "
            "of decisions critically.",
            "The measured decision and replay deltas justify high-priority "
            "procurement.",
        )
    if positive_replay and decision_rate >= 0.01:
        return (
            PurchaseRecommendation.PURCHASE_JUSTIFIED,
            PersonalDecision.YES,
            ConfidenceLevel.MEDIUM,
            AuditStatus.COMPLETE,
            "Independent official data produced positive replay deltas and "
            "material decision changes.",
            "Procurement is justified, subject to rights and full-sample confirmation.",
        )
    return (
        PurchaseRecommendation.PURCHASE_NOT_JUSTIFIED,
        PersonalDecision.NO,
        ConfidenceLevel.MEDIUM,
        AuditStatus.COMPLETE,
        "No measured risk-adjusted replay improvement justified the data cost.",
        "The independent sample did not show enough decision or replay improvement "
        "to purchase.",
    )


def _metric(
    rows: tuple[ReplayDeltaRecord, ...],
    name: str,
) -> Decimal | None:
    row = next((item for item in rows if item.metric == name), None)
    return None if row is None else row.delta


__all__ = ["purchase_decision"]
