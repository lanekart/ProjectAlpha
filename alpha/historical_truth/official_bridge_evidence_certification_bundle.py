"""Official-source acquisition and certification bundle for HTR-010B1F."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

from alpha.historical_truth.official_bridge_certification import (
    OfficialBridgeCertificationEngine,
)
from alpha.historical_truth.official_bridge_document_downloader import (
    OfficialBridgeDocumentDownloader,
)
from alpha.historical_truth.official_bridge_evidence_acquisition import (
    OfficialBridgeEvidenceAcquisitionEngine,
)
from alpha.historical_truth.official_bridge_evidence_dossier import (
    OfficialBridgeEvidenceDossierBuilder,
)
from alpha.historical_truth.official_bridge_evidence_manifest import (
    OfficialBridgeEvidenceManifestBuilder,
)
from alpha.historical_truth.official_bridge_evidence_materialization import (
    OfficialBridgeEvidenceMaterializationEngine,
)
from alpha.historical_truth.official_bridge_evidence_package import (
    OfficialBridgeEvidencePackageEngine,
)

HTR010B1F_EVIDENCE_CERTIFICATION_BUNDLE_VERSION = (
    "HTR-010B1F-EVIDENCE-CERTIFICATION-v1.0.0"
)


@dataclass(frozen=True)
class EvidenceCertificationPaths:
    root: Path
    manifest: Path
    dossiers: Path
    package_build: Path
    downloads: Path
    raw_documents: Path
    semantic_review: Path
    acquisition: Path
    materialization: Path
    certification: Path

    @classmethod
    def under(cls, root: Path) -> EvidenceCertificationPaths:
        return cls(
            root=root,
            manifest=root / "01_manifest",
            dossiers=root / "02_dossiers",
            package_build=root / "03_package_build",
            downloads=root / "04_downloads",
            raw_documents=root / "raw_documents",
            semantic_review=root / "05_semantic_review",
            acquisition=root / "06_acquisition",
            materialization=root / "07_materialization",
            certification=root / "08_certification",
        )


class OfficialBridgeEvidenceCertificationBundle:
    """Acquire, semantically verify, and certify all governed bridge dossiers."""

    def run(
        self,
        *,
        htr010b1d2_output: Path,
        source_catalog_path: Path,
        output: Path,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        paths = EvidenceCertificationPaths.under(output)
        output.mkdir(parents=True, exist_ok=True)

        manifest_builder = OfficialBridgeEvidenceManifestBuilder()
        manifest = manifest_builder.run(htr010b1d2_output=htr010b1d2_output)
        manifest_builder.export(manifest, paths.manifest)

        dossier_builder = OfficialBridgeEvidenceDossierBuilder()
        dossiers = dossier_builder.run(evidence_manifest_output=paths.manifest)
        dossier_builder.export(dossiers, paths.dossiers)
        dossiers_path = paths.dossiers / "htr010b1f_evidence_dossiers.json"

        package_engine = OfficialBridgeEvidencePackageEngine()
        package_build = package_engine.build_findings(
            dossiers_path=dossiers_path,
            source_catalog_path=source_catalog_path,
        )
        package_engine.export_build(package_build, paths.package_build)
        findings_path = paths.package_build / "htr010b1f_reviewed_source_findings.json"

        downloader = OfficialBridgeDocumentDownloader()
        downloads = downloader.run(
            discoveries_path=findings_path,
            output_root=paths.raw_documents,
        )
        downloader.export(downloads, paths.downloads)

        merged = _merge_downloads(
            package_build.get("findings", []), downloads.get("downloads", [])
        )
        merged_path = output / "downloaded_package_discoveries.json"
        merged_path.write_text(
            json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        semantic_review = package_engine.review_downloaded_packages(
            dossiers_path=dossiers_path,
            acquisition_discoveries_path=merged_path,
            downloaded_documents_root=paths.raw_documents,
        )
        package_engine.export_review(semantic_review, paths.semantic_review)
        reviewed_path = (
            paths.semantic_review / "htr010b1f_semantically_reviewed_discoveries.json"
        )

        acquisition_engine = OfficialBridgeEvidenceAcquisitionEngine()
        acquisition = acquisition_engine.run(
            dossiers_path=dossiers_path,
            discoveries_path=reviewed_path,
            downloaded_documents_root=paths.raw_documents,
        )
        acquisition_engine.export(acquisition, paths.acquisition)
        admissible_path = (
            paths.acquisition / "htr010b1f_admissible_official_evidence.json"
        )

        materialization_engine = OfficialBridgeEvidenceMaterializationEngine()
        materialization = materialization_engine.run(
            dossiers_path=dossiers_path,
            admissible_documents_path=admissible_path,
        )
        materialization_engine.export(materialization, paths.materialization)
        case_evidence_path = (
            paths.materialization / "htr010b1f_case_level_official_evidence.json"
        )

        certification_engine = OfficialBridgeCertificationEngine()
        certification = certification_engine.run(
            htr010b1d2_output=htr010b1d2_output,
            official_evidence_path=case_evidence_path,
            start_date=start_date,
            end_date=end_date,
        )
        certification_engine.export(certification, paths.certification)

        report = _report(
            manifest=manifest,
            dossiers=dossiers,
            package_build=package_build,
            downloads=downloads,
            semantic_review=semantic_review,
            acquisition=acquisition,
            materialization=materialization,
            certification=certification,
        )
        self.export(report, output)
        return report

    @staticmethod
    def export(report: dict[str, Any], output: Path) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        report_path = output / "htr010b1f_evidence_certification_report.json"
        markdown_path = output / "htr010b1f_evidence_certification_report.md"
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        markdown_path.write_text(_markdown(report), encoding="utf-8")
        return report_path, markdown_path


def _merge_downloads(
    findings: list[dict[str, Any]], downloads: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    keyed = {
        (str(row.get("dossier_id") or ""), str(row.get("source_url") or "")): row
        for row in downloads
    }
    merged = []
    for finding in findings:
        key = (
            str(finding.get("dossier_id") or ""),
            str(finding.get("source_url") or ""),
        )
        download = keyed.get(key, {})
        merged.append(
            {
                **finding,
                "source_url": download.get("final_url") or finding.get("source_url"),
                "relative_path": download.get("relative_path"),
                "source_sha256": download.get("source_sha256"),
                "download_state": download.get("download_state"),
                "download_error": download.get("error"),
                "production_influence": False,
            }
        )
    return sorted(
        merged,
        key=lambda row: (
            str(row.get("dossier_id") or ""),
            str(row.get("evidence_role") or ""),
        ),
    )


def _report(
    *,
    manifest: dict[str, Any],
    dossiers: dict[str, Any],
    package_build: dict[str, Any],
    downloads: dict[str, Any],
    semantic_review: dict[str, Any],
    acquisition: dict[str, Any],
    materialization: dict[str, Any],
    certification: dict[str, Any],
) -> dict[str, Any]:
    stage_defects = {
        "manifest": manifest.get("implementation_defect_count", 0),
        "dossiers": dossiers.get("implementation_defect_count", 0),
        "package_build": package_build.get("implementation_defect_count", 0),
        "semantic_review": semantic_review.get("implementation_defect_count", 0),
        "acquisition": acquisition.get("implementation_defect_count", 0),
        "materialization": materialization.get("implementation_defect_count", 0),
        "certification": certification.get("implementation_defect_count", 0),
    }
    blockers = []
    if package_build.get("incomplete_source_package_count", 0):
        blockers.append("INCOMPLETE_OFFICIAL_SOURCE_PACKAGES")
    if downloads.get("failed_download_count", 0):
        blockers.append("OFFICIAL_DOCUMENT_DOWNLOAD_FAILURES")
    if semantic_review.get("insufficient_semantic_package_count", 0):
        blockers.append("INSUFFICIENT_SEMANTIC_PACKAGE_EVIDENCE")
    if certification.get("insufficient_official_evidence_count", 0):
        blockers.append("INSUFFICIENT_OFFICIAL_BRIDGE_EVIDENCE")
    if materialization.get("covered_bridge_case_count", 0) < 24:
        blockers.append("INCOMPLETE_CASE_LEVEL_EVIDENCE_COVERAGE")
    if any(stage_defects.values()):
        blockers.append("IMPLEMENTATION_DEFECTS_REMAIN")

    report = {
        "contract_version": HTR010B1F_EVIDENCE_CERTIFICATION_BUNDLE_VERSION,
        "input_bridge_case_count": manifest.get("input_bridge_case_count", 0),
        "unique_dossier_count": dossiers.get("unique_dossier_count", 0),
        "complete_source_package_count": package_build.get(
            "complete_source_package_count", 0
        ),
        "incomplete_source_package_count": package_build.get(
            "incomplete_source_package_count", 0
        ),
        "requested_document_count": package_build.get(
            "generated_document_request_count", 0
        ),
        "downloaded_document_count": downloads.get("downloaded_document_count", 0),
        "failed_download_count": downloads.get("failed_download_count", 0),
        "semantically_verified_package_count": semantic_review.get(
            "semantically_verified_package_count", 0
        ),
        "insufficient_semantic_package_count": semantic_review.get(
            "insufficient_semantic_package_count", 0
        ),
        "verified_official_document_count": acquisition.get(
            "verified_official_document_count", 0
        ),
        "covered_bridge_case_count": materialization.get(
            "covered_bridge_case_count", 0
        ),
        "certified_continuous_identity_count": certification.get(
            "certified_continuous_identity_count", 0
        ),
        "certified_noncontinuous_identity_count": certification.get(
            "certified_noncontinuous_identity_count", 0
        ),
        "insufficient_official_evidence_count": certification.get(
            "insufficient_official_evidence_count", 0
        ),
        "stage_implementation_defect_counts": stage_defects,
        "implementation_defect_count": sum(
            int(value) for value in stage_defects.values()
        ),
        "readiness_blockers": blockers,
        "milestone_status": (
            "EVIDENCE_CERTIFICATION_COMPLETE"
            if not blockers
            else "EVIDENCE_GAPS_REMAIN"
        ),
        "benchmark_replay_count": 0,
        "adjusted_replay_integration_enabled": False,
        "production_influence": False,
    }
    report["report_sha256"] = _digest(report)
    return report


def _digest(report: dict[str, Any]) -> str:
    payload = {**report, "report_sha256": ""}
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _markdown(report: dict[str, Any]) -> str:
    lines = ["# HTR-010B1F Evidence Certification Bundle", ""]
    lines.extend(
        f"- {key.replace('_', ' ').title()}: {value}" for key, value in report.items()
    )
    lines.extend(["", "PRODUCTION_INFLUENCE=false", ""])
    return "\n".join(lines)


__all__ = [
    "EvidenceCertificationPaths",
    "HTR010B1F_EVIDENCE_CERTIFICATION_BUNDLE_VERSION",
    "OfficialBridgeEvidenceCertificationBundle",
]
