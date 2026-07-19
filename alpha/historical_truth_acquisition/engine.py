from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from alpha.data_platform import build_default_platform
from alpha.historical_truth_acquisition.acquisition import (
    AcquisitionOptions,
    HistoricalTruthAcquirer,
)
from alpha.historical_truth_acquisition.certification import CertificationEngine
from alpha.historical_truth_acquisition.exports import (
    REQUIRED_ARTIFACT_NAMES,
    HistoricalTruthExporter,
)
from alpha.historical_truth_acquisition.models import (
    DEFAULT_HTA_OUTPUT,
    HTA_VERSION,
    AcquisitionManifest,
    HTAResult,
    StageRunResult,
    StageStatus,
    stable_hash,
)
from alpha.historical_truth_acquisition.reconciliation import (
    HistoricalTruthReconciler,
)
from alpha.historical_truth_acquisition.scorecard import (
    build_scorecard,
    build_warehouse_candidate,
)
from alpha.historical_truth_acquisition.stages import STAGES


class HistoricalTruthAcquisitionEngine:
    """End-to-end HTA orchestration with no publication or production mutation."""

    def execute(
        self,
        *,
        output_directory: Path = DEFAULT_HTA_OUTPUT,
        source_directory: Path | None = None,
        lawfully_obtained: bool = False,
        dataset: str | None = None,
        resume: bool = False,
        verify: bool = False,
        force: bool = False,
        parallelism: int = 4,
        since: date | None = None,
        until: date | None = None,
        acquire: bool = True,
        observed_at: datetime | None = None,
    ) -> HTAResult:
        timestamp = observed_at or datetime.now(tz=UTC)
        options = AcquisitionOptions(
            output_directory=output_directory,
            source_directory=source_directory,
            lawfully_obtained=lawfully_obtained,
            selected_dataset=dataset,
            start=since,
            end=until,
            resume=resume,
            verify=verify,
            force=force,
            parallelism=parallelism,
            observed_at=timestamp,
        )
        acquirer = HistoricalTruthAcquirer(options)
        stage_results = (
            acquirer.acquire() if acquire else _existing_stage_results(acquirer)
        )
        reconciliation = HistoricalTruthReconciler(acquirer.warehouse).reconcile()
        certifications = CertificationEngine(acquirer.evidence, reconciliation).certify(
            start=since, end=until
        )
        scorecard = build_scorecard(certifications)
        candidate = build_warehouse_candidate(certifications, scorecard)
        platform = build_default_platform()
        manifest = AcquisitionManifest(
            hta_version=HTA_VERSION,
            platform_version=platform.manifest.platform_version,
            platform_manifest_hash=stable_hash(platform.manifest),
            generated_at=timestamp,
            requested_start=since,
            requested_end=until,
            selected_dataset=dataset,
            resume_requested=resume,
            verification_requested=verify,
            force_requested=force,
            parallelism=parallelism,
            source_mode=(
                "MANUAL_OFFICIAL_FILES"
                if source_directory is not None
                else "NO_AUTHORISED_SOURCE_CONFIGURED"
            ),
            source_rights_basis=(
                "USER_LAWFUL_SOURCE_ATTESTATION"
                if source_directory is not None and lawfully_obtained
                else "LICENCE_OR_LAWFUL_SOURCE_ATTESTATION_REQUIRED"
            ),
            stage_results=stage_results,
        )
        provisional = HTAResult(
            manifest=manifest,
            certifications=certifications,
            reconciliation=reconciliation,
            scorecard=scorecard,
            warehouse_candidate=candidate,
            artifacts=(),
        )
        existing_artifacts = tuple(
            output_directory / name for name in REQUIRED_ARTIFACT_NAMES
        )
        if acquire or not all(path.exists() for path in existing_artifacts):
            artifacts, final_manifest = HistoricalTruthExporter(
                output_directory=output_directory,
                warehouse=acquirer.warehouse,
                memberships=acquirer.memberships,
            ).export(result=provisional, write_manifest=acquire)
        else:
            artifacts = existing_artifacts
            final_manifest = manifest
        return HTAResult(
            manifest=final_manifest,
            certifications=certifications,
            reconciliation=reconciliation,
            scorecard=scorecard,
            warehouse_candidate=candidate,
            artifacts=artifacts,
        )


def _existing_stage_results(
    acquirer: HistoricalTruthAcquirer,
) -> tuple[StageRunResult, ...]:
    all_ids = tuple(dataset_id for stage in STAGES for dataset_id in stage.dataset_ids)
    evidence = {
        item.dataset_id: item for item in acquirer.evidence.dataset_evidence(all_ids)
    }
    return tuple(
        StageRunResult(
            stage=stage.stage,
            status=(
                StageStatus.COMPLETE
                if any(evidence[item].source_files for item in stage.dataset_ids)
                else StageStatus.BLOCKED_SOURCE_UNAVAILABLE
            ),
            attempted_datasets=stage.dataset_ids,
            imported_files=sum(
                evidence[item].source_files for item in stage.dataset_ids
            ),
            duplicate_files=sum(
                evidence[item].duplicate_records for item in stage.dataset_ids
            ),
            rejected_records=sum(
                evidence[item].rejected_records for item in stage.dataset_ids
            ),
            reasons=(),
        )
        for stage in STAGES
    )


__all__ = ["HistoricalTruthAcquisitionEngine"]
