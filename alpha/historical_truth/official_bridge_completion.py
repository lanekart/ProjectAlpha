"""End-to-end completion orchestration for HTR-010B1F."""

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
from alpha.historical_truth.official_bridge_evidence_discovery import (
    build_discovery_registry,
    export_discovery_registry,
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
from alpha.historical_truth.official_bridge_evidence_population import (
    OfficialBridgeEvidenceDiscoveryPopulationEngine,
)

HTR010B1F_COMPLETION_CONTRACT_VERSION = "HTR-010B1F-COMPLETE-v1.0.0"


@dataclass(frozen=True)
class CompletionPaths:
    root: Path
    manifest: Path
    dossiers: Path
    discovery: Path
    population: Path
    downloads: Path
    raw_documents: Path
    acquisition: Path
    materialization: Path
    certification: Path

    @classmethod
    def under(cls, root: Path) -> CompletionPaths:
        return cls(
            root=root,
            manifest=root / "01_manifest",
            dossiers=root / "02_dossiers",
            discovery=root / "03_discovery_registry",
            population=root / "04_discovery_population",
            downloads=root / "05_downloads",
            raw_documents=root / "raw_documents",
            acquisition=root / "06_acquisition",
            materialization=root / "07_materialization",
            certification=root / "08_certification",
        )


class OfficialBridgeCompletionEngine:
    """Run the complete B1F evidence and certification pipeline."""

    def run(
        self,
        *,
        htr010b1d2_output: Path,
        reviewed_findings_path: Path | None,
        output: Path,
        start_date: date,
        end_date: date,
        download_documents: bool,
    ) -> dict[str, Any]:
        paths = CompletionPaths.under(output)
        output.mkdir(parents=True, exist_ok=True)

        manifest_builder = OfficialBridgeEvidenceManifestBuilder()
        manifest = manifest_builder.run(htr010b1d2_output=htr010b1d2_output)
        manifest_builder.export(manifest, paths.manifest)

        dossier_builder = OfficialBridgeEvidenceDossierBuilder()
        dossiers = dossier_builder.run(evidence_manifest_output=paths.manifest)
        dossier_builder.export(dossiers, paths.dossiers)
        dossiers_path = paths.dossiers / "htr010b1f_evidence_dossiers.json"

        discovery = build_discovery_registry(dossiers_path=dossiers_path)
        export_discovery_registry(discovery, paths.discovery)
        discovery_path = paths.discovery / "htr010b1f_discovery_registry.json"

        population_engine = OfficialBridgeEvidenceDiscoveryPopulationEngine()
        population = population_engine.run(
            discovery_registry_path=discovery_path,
            reviewed_findings_path=reviewed_findings_path,
        )
        population_engine.export(population, paths.population)
        populated_path = paths.population / "htr010b1f_populated_discoveries.json"

        downloader = OfficialBridgeDocumentDownloader()
        if download_documents:
            downloads = downloader.run(
                discoveries_path=populated_path,
                output_root=paths.raw_documents,
            )
        else:
            downloads = _downloads_disabled(population)
        downloader.export(downloads, paths.downloads)

        acquisition_discoveries = _merge_downloads_into_discoveries(
            population.get("discoveries", []),
            downloads.get("downloads", []),
        )
        acquisition_discoveries_path = output / "acquisition_discoveries.json"
        acquisition_discoveries_path.write_text(
            json.dumps(acquisition_discoveries, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        acquisition_engine = OfficialBridgeEvidenceAcquisitionEngine()
        acquisition = acquisition_engine.run(
            dossiers_path=dossiers_path,
            discoveries_path=acquisition_discoveries_path,
            downloaded_documents_root=(paths.raw_documents if download_documents else None),
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

        report = _completion_report(
            manifest=manifest,
            dossiers=dossiers,
            discovery=discovery,
            population=population,
            downloads=downloads,
            acquisition=acquisition,
            materialization=materialization,
            certification=certification,
            download_documents=download_documents,
        )
        self.export(report, output)
        return report

    @staticmethod
    def export(report: dict[str, Any], output: Path) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        report_path = output / "htr010b1f_completion_report.json"
        markdown_path = output / "htr010b1f_completion_report.md"
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        markdown_path.write_text(_markdown(report), encoding="utf-8")
        return report_path, markdown_path


def _downloads_disabled(population: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for row in population.get("discoveries", []):
        rows.append(
            {
                "dossier_id": row.get("dossier_id"),
                "source_url": row.get("source_url") or "",
                "final_url": None,
                "relative_path": None,
                "source_sha256": None,
                "file_size_bytes": None,
                "content_type": None,
                "download_state": "DOWNLOAD_DISABLED",
                "error": None,
            }
        )
    report = {
        "contract_version": "HTR-010B1F-DOWNLOAD-v1.0.0",
        "input_discovery_count": len(rows),
        "downloaded_document_count": 0,
        "rejected_source_count": 0,
        "failed_download_count": 0,
        "pending_url_count": sum(not row["source_url"] for row in rows),
        "benchmark_replay_count": 0,
        "production_influence": False,
        "downloads": rows,
    }
    report["report_sha256"] = _digest(report)
    return report


def _merge_downloads_into_discoveries(
    discoveries: list[dict[str, Any]],
    downloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    keyed: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in downloads:
        key = (
            str(row.get("dossier_id") or ""),
            str(row.get("source_url") or ""),
        )
        keyed.setdefault(key, []).append(row)

    merged: list[dict[str, Any]] = []
    for discovery in discoveries:
        key = (
            str(discovery.get("dossier_id") or ""),
            str(discovery.get("source_url") or ""),
        )
        matches = keyed.get(key, [])
        download = matches.pop(0) if matches else {}
        merged.append(
            {
                **discovery,
                "source_url": download.get("final_url")
                or discovery.get("source_url"),
                "relative_path": download.get("relative_path"),
                "source_sha256": download.get("source_sha256"),
                "download_state": download.get("download_state"),
                "download_error": download.get("error"),
                "production_influence": False,
            }
        )
    return merged


def _completion_report(
    *,
    manifest: dict[str, Any],
    dossiers: dict[str, Any],
    discovery: dict[str, Any],
    population: dict[str, Any],
    downloads: dict[str, Any],
    acquisition: dict[str, Any],
    materialization: dict[str, Any],
    certification: dict[str, Any],
    download_documents: bool,
) -> dict[str, Any]:
    stage_defects = {
        "manifest": manifest.get("implementation_defect_count", 0),
        "dossiers": dossiers.get("implementation_defect_count", 0),
        "discovery": discovery.get("implementation_defect_count", 0),
        "population": population.get("implementation_defect_count", 0),
        "acquisition": acquisition.get("implementation_defect_count", 0),
        "materialization": materialization.get("implementation_defect_count", 0),
        "certification": certification.get("implementation_defect_count", 0),
    }
    blockers = []
    if certification.get("insufficient_official_evidence_count", 0):
        blockers.append("INSUFFICIENT_OFFICIAL_BRIDGE_EVIDENCE")
    if certification.get("conflicting_official_evidence_count", 0):
        blockers.append("CONFLICTING_OFFICIAL_BRIDGE_EVIDENCE")
    if certification.get("certified_noncontinuous_identity_count", 0):
        blockers.append("CERTIFIED_NONCONTINUOUS_IDENTITY_BOUNDARIES")
    if materialization.get("covered_bridge_case_count", 0) < 24:
        blockers.append("INCOMPLETE_CASE_LEVEL_EVIDENCE_COVERAGE")
    if any(stage_defects.values()):
        blockers.append("IMPLEMENTATION_DEFECTS_REMAIN")

    ready = (
        not blockers
        and certification.get("adjusted_replay_certified_case_count", 0) == 24
    )
    report = {
        "contract_version": HTR010B1F_COMPLETION_CONTRACT_VERSION,
        "input_bridge_case_count": manifest.get("input_bridge_case_count", 0),
        "unique_dossier_count": dossiers.get("unique_dossier_count", 0),
        "populated_official_source_count": population.get(
            "populated_official_source_count", 0
        ),
        "pending_official_source_count": population.get(
            "pending_official_source_count", 0
        ),
        "download_documents_enabled": download_documents,
        "downloaded_document_count": downloads.get("downloaded_document_count", 0),
        "verified_official_document_count": acquisition.get(
            "verified_official_document_count", 0
        ),
        "materialized_case_evidence_count": materialization.get(
            "materialized_case_evidence_count", 0
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
        "conflicting_official_evidence_count": certification.get(
            "conflicting_official_evidence_count", 0
        ),
        "adjusted_replay_certified_case_count": certification.get(
            "adjusted_replay_certified_case_count", 0
        ),
        "stage_implementation_defect_counts": stage_defects,
        "implementation_defect_count": sum(int(value) for value in stage_defects.values()),
        "replay_readiness": (
            "READY_FOR_B1G_RECONCILIATION"
            if ready
            else "NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION"
        ),
        "readiness_blockers": blockers,
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
    lines = ["# HTR-010B1F Completion Report", ""]
    for key, value in report.items():
        lines.append(f"- {key.replace('_', ' ').title()}: {value}")
    lines.extend(["", "PRODUCTION_INFLUENCE=false", ""])
    return "\n".join(lines)


__all__ = [
    "CompletionPaths",
    "HTR010B1F_COMPLETION_CONTRACT_VERSION",
    "OfficialBridgeCompletionEngine",
]
