from __future__ import annotations

from decimal import Decimal

from alpha.historical_truth_acquisition.models import (
    WAREHOUSE_CANDIDATE_VERSION,
    CertificationStatus,
    ConfidenceGrade,
    HistoricalTruthScorecard,
    LogicalDatasetScore,
    StageCertification,
    WarehouseCandidateStatus,
    WarehouseV2Candidate,
)
from alpha.historical_truth_acquisition.stages import STAGES

SCORECARD_VERSION = "hta-historical-truth-scorecard-v1"
TARGET_SCORE = Decimal("97.00")


def build_scorecard(
    certifications: tuple[StageCertification, ...],
) -> HistoricalTruthScorecard:
    weight = Decimal("1") / Decimal(len(certifications))
    logical = []
    for stage in certifications:
        scores = tuple(item.overall_score for item in stage.dataset_certifications)
        score = (
            sum(scores, Decimal("0")) / Decimal(len(scores)) if scores else Decimal("0")
        ).quantize(Decimal("0.01"))
        logical.append(
            LogicalDatasetScore(
                stage=stage.stage,
                score=score,
                weight=weight,
                certification=stage.status,
                explanation=(
                    "All mandatory datasets passed certification."
                    if stage.status is CertificationStatus.PASS
                    else "Stage is not eligible for ACTIVE status."
                ),
            )
        )
    overall = sum(
        (item.score * item.weight for item in logical), Decimal("0")
    ).quantize(Decimal("0.01"))
    expected_stages = {item.stage for item in STAGES}
    actual_stages = {item.stage for item in certifications}
    expected_datasets = {
        dataset_id for item in STAGES for dataset_id in item.dataset_ids
    }
    passing_datasets = {
        item.dataset_id
        for stage in certifications
        for item in stage.dataset_certifications
        if item.active
    }
    target_met = (
        overall >= TARGET_SCORE
        and actual_stages == expected_stages
        and passing_datasets == expected_datasets
        and all(item.certification is CertificationStatus.PASS for item in logical)
    )
    confidence = (
        ConfidenceGrade.HIGH
        if target_met
        else ConfidenceGrade.MEDIUM
        if overall >= Decimal("80")
        else ConfidenceGrade.LOW
    )
    return HistoricalTruthScorecard(
        scorecard_version=SCORECARD_VERSION,
        logical_datasets=tuple(logical),
        overall_score=overall,
        target_score=TARGET_SCORE,
        target_met=target_met,
        confidence=confidence,
        unknown_dataset_count=len(expected_datasets - passing_datasets),
    )


def build_warehouse_candidate(
    certifications: tuple[StageCertification, ...],
    scorecard: HistoricalTruthScorecard,
) -> WarehouseV2Candidate:
    dataset_certifications = tuple(
        item for stage in certifications for item in stage.dataset_certifications
    )
    active = tuple(
        sorted(item.dataset_id for item in dataset_certifications if item.active)
    )
    blocked = tuple(
        sorted(item.dataset_id for item in dataset_certifications if not item.active)
    )
    ready = scorecard.target_met and not blocked
    reasons = (
        (
            "All mandatory datasets passed; explicit activation review is still "
            "required.",
        )
        if ready
        else (
            "Candidate remains isolated because one or more mandatory datasets "
            "are not PASS-certified.",
            "Warehouse v1 and all replay consumers remain unchanged.",
        )
    )
    return WarehouseV2Candidate(
        version=WAREHOUSE_CANDIDATE_VERSION,
        status=(
            WarehouseCandidateStatus.READY_FOR_ACTIVATION_REVIEW
            if ready
            else WarehouseCandidateStatus.NOT_READY
        ),
        active_dataset_ids=active,
        blocked_dataset_ids=blocked,
        historical_truth_score=scorecard.overall_score,
        activation_performed=False,
        replay_migrated=False,
        production_influence=False,
        reasons=reasons,
    )


__all__ = [
    "SCORECARD_VERSION",
    "TARGET_SCORE",
    "build_scorecard",
    "build_warehouse_candidate",
]
