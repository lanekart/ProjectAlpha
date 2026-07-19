from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from alpha.historical_truth_acquisition.evidence import EvidenceStore
from alpha.historical_truth_acquisition.models import (
    CertificationStatus,
    ConfidenceGrade,
    DatasetCertification,
    DatasetEvidence,
    DiscrepancyType,
    HTAStage,
    ReconciliationSummary,
    StageCertification,
)
from alpha.historical_truth_acquisition.stages import STAGES

CERTIFICATION_POLICY_VERSION = "hta-certification-policy-v1"
PASS_THRESHOLD = Decimal("97")
WARNING_THRESHOLD = Decimal("80")


class CertificationEngine:
    def __init__(
        self,
        evidence_store: EvidenceStore,
        reconciliation: ReconciliationSummary,
    ) -> None:
        self.evidence_store = evidence_store
        self.reconciliation = reconciliation

    def certify(
        self, *, start: date | None, end: date | None
    ) -> tuple[StageCertification, ...]:
        expected_sessions = _weekday_sessions(start, end)
        all_ids = tuple(item for stage in STAGES for item in stage.dataset_ids)
        expected = {}
        for dataset_id in all_ids:
            definition = next(
                stage for stage in STAGES if dataset_id in stage.dataset_ids
            )
            expected[dataset_id] = expected_sessions if definition.time_series else None
        evidence = {
            item.dataset_id: item
            for item in self.evidence_store.dataset_evidence(
                all_ids, expected_sessions=expected
            )
        }
        stages: list[StageCertification] = []
        status_by_stage: dict[HTAStage, CertificationStatus] = {}
        for definition in STAGES:
            datasets = tuple(
                self._certify_dataset(
                    evidence[dataset_id],
                    stage=definition.stage,
                    time_series=definition.time_series,
                    requested_start=start,
                    requested_end=end,
                )
                for dataset_id in definition.dataset_ids
            )
            reasons: list[str] = []
            dependencies_pass = all(
                status_by_stage.get(dependency) is CertificationStatus.PASS
                for dependency in definition.dependencies
            )
            if not dependencies_pass:
                reasons.append(
                    "One or more prerequisite stages are not PASS-certified."
                )
            if dependencies_pass and all(
                item.status is CertificationStatus.PASS for item in datasets
            ):
                status = CertificationStatus.PASS
            elif dependencies_pass and all(
                item.status is not CertificationStatus.FAIL for item in datasets
            ):
                status = CertificationStatus.PASS_WITH_WARNINGS
            else:
                status = CertificationStatus.FAIL
            status_by_stage[definition.stage] = status
            stages.append(
                StageCertification(
                    stage=definition.stage,
                    version=definition.version,
                    status=status,
                    dataset_certifications=datasets,
                    reasons=tuple(reasons),
                )
            )
        return tuple(stages)

    def _certify_dataset(
        self,
        evidence: DatasetEvidence,
        *,
        stage: HTAStage,
        time_series: bool,
        requested_start: date | None,
        requested_end: date | None,
    ) -> DatasetCertification:
        reasons: list[str] = []
        checksum = _percent(evidence.checksum_rate)
        acceptance = _percent(evidence.parse_acceptance)
        if evidence.source_files and evidence.total_parsed_records == 0:
            acceptance = Decimal("100")
        completeness_ratio = evidence.completeness
        completeness = (
            _percent(completeness_ratio)
            if time_series
            else Decimal("100")
            if evidence.source_files
            else Decimal("0")
        )
        consistency = (
            Decimal("100")
            if len(evidence.schema_fingerprints) <= 1 and evidence.source_files
            else Decimal("80")
            if evidence.source_files
            else Decimal("0")
        )
        reconciliation = self._reconciliation_score(stage)
        if evidence.source_files == 0:
            reasons.append("No verified official source file is available.")
        if evidence.checksum_rate != Decimal("1"):
            reasons.append("Not every source file passed SHA-256 verification.")
        if time_series and (requested_start is None or requested_end is None):
            reasons.append("Time-series coverage bounds are unspecified.")
        elif time_series and completeness_ratio is not None:
            if completeness_ratio < Decimal("0.97"):
                reasons.append("Observed session coverage is below 97 percent.")
        if evidence.unresolved_identity_records:
            reasons.append(
                f"{evidence.unresolved_identity_records} records have "
                "unresolved identity."
            )
            consistency = min(consistency, Decimal("50"))
        if len(evidence.schema_fingerprints) > 1:
            reasons.append("Multiple source schemas require explicit reconciliation.")
        if evidence.rejected_records:
            reasons.append(
                f"{evidence.rejected_records} source records were rejected "
                "or quarantined."
            )
        overall = (
            checksum * Decimal("0.20")
            + acceptance * Decimal("0.20")
            + completeness * Decimal("0.25")
            + consistency * Decimal("0.15")
            + reconciliation * Decimal("0.20")
        ).quantize(Decimal("0.01"))
        if evidence.source_files == 0:
            overall = Decimal("0.00")
        hard_failure = (
            evidence.source_files == 0
            or evidence.checksum_rate != Decimal("1")
            or evidence.unresolved_identity_records > 0
            or (evidence.total_parsed_records > 0 and evidence.accepted_records == 0)
        )
        if not hard_failure and overall >= PASS_THRESHOLD and not reasons:
            status = CertificationStatus.PASS
        elif not hard_failure and overall >= WARNING_THRESHOLD:
            status = CertificationStatus.PASS_WITH_WARNINGS
        else:
            status = CertificationStatus.FAIL
        confidence = (
            ConfidenceGrade.HIGH
            if status is CertificationStatus.PASS
            else ConfidenceGrade.MEDIUM
            if status is CertificationStatus.PASS_WITH_WARNINGS
            else ConfidenceGrade.LOW
        )
        return DatasetCertification(
            dataset_id=evidence.dataset_id,
            stage=stage,
            status=status,
            active=status is CertificationStatus.PASS,
            checksum_score=checksum,
            parse_acceptance_score=acceptance,
            completeness_score=completeness,
            consistency_score=consistency,
            reconciliation_score=reconciliation,
            overall_score=overall,
            confidence=confidence,
            reasons=tuple(reasons),
            evidence=evidence,
        )

    def _reconciliation_score(self, stage: HTAStage) -> Decimal:
        relevant_types = {
            HTAStage.DAILY_EQUITY_HISTORY: {
                DiscrepancyType.PRICE_MISMATCH,
                DiscrepancyType.VOLUME_MISMATCH,
                DiscrepancyType.MISSING_DAY,
                DiscrepancyType.MISSING_OBSERVATION,
                DiscrepancyType.SOURCE_UNAVAILABLE,
            },
            HTAStage.SECURITY_IDENTITY: {
                DiscrepancyType.IDENTITY_MISMATCH,
                DiscrepancyType.SYMBOL_MISMATCH,
            },
            HTAStage.CORPORATE_ACTIONS: {
                DiscrepancyType.CORPORATE_ACTION_MISMATCH,
            },
        }.get(stage, set())
        findings = tuple(
            item
            for item in self.reconciliation.findings
            if item.discrepancy_type in relevant_types
        )
        if any(item.severity == "ERROR" and not item.resolved for item in findings):
            return Decimal("0")
        if findings:
            return Decimal("90")
        return Decimal("100")


def _percent(value: Decimal | None) -> Decimal:
    if value is None:
        return Decimal("0")
    return (value * Decimal("100")).quantize(Decimal("0.01"))


def _weekday_sessions(start: date | None, end: date | None) -> int | None:
    if start is None or end is None:
        return None
    cursor = start
    count = 0
    while cursor <= end:
        count += int(cursor.weekday() < 5)
        cursor += timedelta(days=1)
    return count


__all__ = [
    "CERTIFICATION_POLICY_VERSION",
    "CertificationEngine",
    "PASS_THRESHOLD",
    "WARNING_THRESHOLD",
]
