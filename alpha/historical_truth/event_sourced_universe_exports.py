"""Deterministic artifacts for HTR-009A2 event-sourced certification."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

from alpha.historical_truth.event_sourced_universe_models import (
    EventSourcedUniverseReport,
    EventSourceStatus,
)


class EventSourcedUniverseArtifactExporter:
    """Write the complete stable HTR-009A2 evidence surface."""

    _PAIRS = (
        ("htr009a2_source_inventory", "sources"),
        ("htr009a2_security_events", "events"),
        ("htr009a2_identity_relationships", "identity_relationships"),
        ("htr009a2_symbol_intervals", "symbol_intervals"),
        ("htr009a2_membership_intervals", "membership_intervals"),
        ("htr009a2_tradability_intervals", "tradability_intervals"),
        ("htr009a2_symbol_reuse", "symbol_reuse"),
        ("htr009a2_symbol_changes", "symbol_changes"),
        ("htr009a2_suspensions", "suspensions"),
        ("htr009a2_delistings", "delistings"),
        ("htr009a2_checkpoint_reconciliation", "checkpoints"),
        ("htr009a2_candle_interval_conflicts", "candle_conflicts"),
        ("htr009a2_candidate_exposure", "candidate_exposure"),
        ("htr009a2_rejected_evidence", "rejected_evidence"),
    )

    def export(
        self,
        report: EventSourcedUniverseReport,
        output_directory: Path,
    ) -> tuple[Path, ...]:
        output_directory.mkdir(parents=True, exist_ok=True)
        files: list[Path] = [
            self._json(
                output_directory / "htr009a2_executive_report.json",
                self._executive_payload(report),
            ),
            self._text(
                output_directory / "htr009a2_executive_report.md",
                self._executive_markdown(report),
            ),
        ]
        for stem, attribute in self._PAIRS:
            rows = [self._jsonable(asdict(item)) for item in getattr(report, attribute)]
            files.extend(
                (
                    self._csv(output_directory / f"{stem}.csv", rows),
                    self._json(
                        output_directory / f"{stem}.json",
                        {"records": rows},
                    ),
                )
            )
        certification = {
            "contract_version": report.contract_version,
            "production_influence": report.production_influence,
            "start_date": report.start_date.isoformat(),
            "end_date": report.end_date.isoformat(),
            "event_summary": self._jsonable(asdict(report.event_summary)),
            "identity_summary": self._jsonable(asdict(report.identity_summary)),
            "membership_summary": self._jsonable(asdict(report.membership_summary)),
            "ytd_summary": self._jsonable(asdict(report.ytd_summary)),
            "certification": self._jsonable(asdict(report.certification)),
            "report_sha256": report.report_sha256,
        }
        files.extend(
            (
                self._json(
                    output_directory / "htr009a2_certification.json",
                    certification,
                ),
                self._text(
                    output_directory / "htr009a2_certification.md",
                    self._certification_markdown(report),
                ),
            )
        )
        files.extend(self._baseline(report.baseline, output_directory / "baseline"))
        return tuple(files)

    @classmethod
    def _executive_payload(
        cls,
        report: EventSourcedUniverseReport,
    ) -> dict[str, Any]:
        return {
            "contract_version": report.contract_version,
            "production_influence": report.production_influence,
            "database_path": report.database_path,
            "start_date": report.start_date.isoformat(),
            "end_date": report.end_date.isoformat(),
            "baseline": cls._jsonable(report.baseline),
            "event_summary": cls._jsonable(asdict(report.event_summary)),
            "identity_summary": cls._jsonable(asdict(report.identity_summary)),
            "membership_summary": cls._jsonable(asdict(report.membership_summary)),
            "ytd_summary": cls._jsonable(asdict(report.ytd_summary)),
            "certification": cls._jsonable(asdict(report.certification)),
            "source_count": len(report.sources),
            "checkpoint_count": len(report.checkpoints),
            "candidate_exposure_count": len(report.candidate_exposure),
            "report_sha256": report.report_sha256,
        }

    def _baseline(
        self,
        baseline: dict[str, Any],
        directory: Path,
    ) -> tuple[Path, ...]:
        directory.mkdir(parents=True, exist_ok=True)
        compact = {
            key: value
            for key, value in baseline.items()
            if key
            not in {
                "identities",
                "boundaries",
                "symbol_reuse",
                "symbol_changes",
                "candidate_exposure",
            }
        }
        return (
            self._json(directory / "htr009a_baseline.json", compact),
            self._csv(
                directory / "htr009a_baseline.csv",
                [
                    {"metric": key, "value": self._jsonable(value)}
                    for key, value in compact.items()
                ],
            ),
        )

    @staticmethod
    def _json(path: Path, payload: object) -> Path:
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    @staticmethod
    def _csv(path: Path, rows: list[dict[str, Any]]) -> Path:
        fields = tuple(rows[0]) if rows else ("record",)
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        key: (
                            json.dumps(value, sort_keys=True, separators=(",", ":"))
                            if isinstance(value, (list, dict))
                            else value
                        )
                        for key, value in row.items()
                    }
                )
        return path

    @staticmethod
    def _text(path: Path, content: str) -> Path:
        path.write_text(content, encoding="utf-8")
        return path

    @classmethod
    def _jsonable(cls, value: object) -> Any:
        if isinstance(value, StrEnum):
            return value.value
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(key): cls._jsonable(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [cls._jsonable(item) for item in value]
        return value

    @staticmethod
    def _executive_markdown(report: EventSourcedUniverseReport) -> str:
        source_counts = {
            status: sum(item.status is status for item in report.sources)
            for status in EventSourceStatus
        }
        lines = [
            "# HTR-009A2 Event-Sourced Point-in-Time Universe",
            "",
            f"Window: `{report.start_date}` to `{report.end_date}`",
            f"Certification: `{report.certification.primary_state.value}`",
            f"Report SHA-256: `{report.report_sha256}`",
            "",
            "## Source Evidence",
            "",
            f"- Sources acquired: {source_counts[EventSourceStatus.ACQUIRED]}",
            f"- Sources reused: {source_counts[EventSourceStatus.REUSED]}",
            f"- Sources failed: {source_counts[EventSourceStatus.FAILED]}",
            f"- Sources rejected: {source_counts[EventSourceStatus.REJECTED]}",
            f"- Events admitted: {report.event_summary.events_admitted}",
            f"- Events rejected: {report.event_summary.events_rejected}",
            "",
            "## Identity and Intervals",
            "",
            f"- Governed identities: {report.identity_summary.governed_identities}",
            "- Provisional identities: "
            f"{report.identity_summary.provisional_identities}",
            f"- Unresolved identities: {report.identity_summary.unresolved_identities}",
            f"- Membership intervals: {len(report.membership_intervals)}",
            f"- Tradability intervals: {len(report.tradability_intervals)}",
            "- Certified identity-days: "
            f"{report.membership_summary.certified_identity_days}",
            "- Unresolved identity-days: "
            f"{report.membership_summary.unresolved_identity_days}",
            "",
            "## Checkpoint and Candle Boundary",
            "",
            f"- Checkpoint dates: {len(report.checkpoints)}",
            "- Checkpoints with mismatches: "
            f"{sum(bool(item.issue_codes) for item in report.checkpoints)}",
            "- Candle rows outside certified intervals: "
            f"{report.membership_summary.candle_rows_outside_certified_intervals}",
            "",
            "## Interpretation",
            "",
            report.certification.rationale,
            "",
            "Official checkpoint masters corroborate reconstructed intervals; "
            "they are not required for every session. Candle presence is "
            "diagnostic only and never opens or closes membership.",
            "",
            "## 2026 YTD",
            "",
            "- Canonical cutoff: "
            f"`{report.ytd_summary.canonical_cutoff or 'unavailable'}`",
            "- Calendar cutoff: "
            f"`{report.ytd_summary.calendar_cutoff or 'unavailable'}`",
            "- Event evidence cutoff: "
            f"`{report.ytd_summary.event_evidence_cutoff or 'unavailable'}`",
            f"- Certified: {report.ytd_summary.certified}",
            f"- Blocker: `{report.ytd_summary.blocker or 'none'}`",
            "",
            "`PRODUCTION_INFLUENCE=false`",
        ]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _certification_markdown(report: EventSourcedUniverseReport) -> str:
        lines = [
            "# HTR-009A2 Certification",
            "",
            f"Primary state: `{report.certification.primary_state.value}`",
            "",
            report.certification.rationale,
            "",
            "## Thresholds",
            "",
            *(f"- {item}" for item in report.certification.thresholds),
            "",
            "## Secondary Blockers",
            "",
        ]
        lines.extend(
            f"- `{item.value}`" for item in report.certification.secondary_blockers
        )
        if not report.certification.secondary_blockers:
            lines.append("- None")
        lines.extend(
            [
                "",
                "No current universe was applied backward, no candle established "
                "membership, and no production policy changed.",
                "",
                "`PRODUCTION_INFLUENCE=false`",
            ]
        )
        return "\n".join(lines) + "\n"


__all__ = ["EventSourcedUniverseArtifactExporter"]
