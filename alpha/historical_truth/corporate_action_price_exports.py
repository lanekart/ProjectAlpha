"""Deterministic HTR-009B corporate-action certification artifacts."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

from alpha.historical_truth.corporate_action_price_models import (
    CorporateActionPriceReport,
)


class CorporateActionPriceArtifactExporter:
    """Export the complete stable HTR-009B diagnostic evidence surface."""

    _PAIRS = (
        ("htr009b_source_inventory", "sources"),
        ("htr009b_corporate_actions", "actions"),
        ("htr009b_adjustment_factors", "factors"),
        ("htr009b_price_basis_intervals", "price_basis_intervals"),
        ("htr009b_adjusted_candle_summary", "adjusted_candle_summary"),
        ("htr009b_price_discontinuities", "price_discontinuities"),
        ("htr009b_indicator_contamination", "indicator_contamination"),
        ("htr009b_stop_contamination", "stop_contamination"),
        ("htr009b_identity_transitions", "identity_transitions"),
        ("htr009b_candidate_exposure", "candidate_exposure"),
        ("htr009b_rejected_evidence", "rejected_evidence"),
    )

    def export(
        self,
        report: CorporateActionPriceReport,
        output_directory: Path,
    ) -> tuple[Path, ...]:
        output_directory.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = [
            self._json(
                output_directory / "htr009b_executive_report.json",
                self._executive_payload(report),
            ),
            self._text(
                output_directory / "htr009b_executive_report.md",
                self._executive_markdown(report),
            ),
        ]
        for stem, attribute in self._PAIRS:
            rows = [self._jsonable(asdict(item)) for item in getattr(report, attribute)]
            paths.extend(
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
            "cutoffs": self._jsonable(asdict(report.cutoffs)),
            "source_summary": self._jsonable(asdict(report.source_summary)),
            "event_summary": self._jsonable(asdict(report.event_summary)),
            "factor_summary": self._jsonable(asdict(report.factor_summary)),
            "price_basis_summary": self._jsonable(asdict(report.price_basis_summary)),
            "continuity_summary": self._jsonable(asdict(report.continuity_summary)),
            "identity_transition_summary": self._jsonable(
                asdict(report.identity_transition_summary)
            ),
            "candidate_exposure_summary": self._jsonable(
                asdict(report.candidate_exposure_summary)
            ),
            "certification": self._jsonable(asdict(report.certification)),
            "report_sha256": report.report_sha256,
        }
        paths.extend(
            (
                self._json(
                    output_directory / "htr009b_certification.json",
                    certification,
                ),
                self._text(
                    output_directory / "htr009b_certification.md",
                    self._certification_markdown(report),
                ),
            )
        )
        return tuple(paths)

    @classmethod
    def _executive_payload(
        cls,
        report: CorporateActionPriceReport,
    ) -> dict[str, Any]:
        return {
            "contract_version": report.contract_version,
            "production_influence": report.production_influence,
            "database_path": report.database_path,
            "start_date": report.start_date.isoformat(),
            "end_date": report.end_date.isoformat(),
            "cutoffs": cls._jsonable(asdict(report.cutoffs)),
            "source_summary": cls._jsonable(asdict(report.source_summary)),
            "event_summary": cls._jsonable(asdict(report.event_summary)),
            "factor_summary": cls._jsonable(asdict(report.factor_summary)),
            "price_basis_summary": cls._jsonable(asdict(report.price_basis_summary)),
            "continuity_summary": cls._jsonable(asdict(report.continuity_summary)),
            "identity_transition_summary": cls._jsonable(
                asdict(report.identity_transition_summary)
            ),
            "candidate_exposure_summary": cls._jsonable(
                asdict(report.candidate_exposure_summary)
            ),
            "certification": cls._jsonable(asdict(report.certification)),
            "report_sha256": report.report_sha256,
        }

    @staticmethod
    def _executive_markdown(report: CorporateActionPriceReport) -> str:
        counts = dict(report.event_summary.counts_by_type)
        lines = [
            "# HTR-009B Corporate Actions and Price-Basis Continuity",
            "",
            f"Window: `{report.start_date}` to `{report.end_date}`",
            f"Certification: `{report.certification.primary_state.value}`",
            f"Report SHA-256: `{report.report_sha256}`",
            "",
            "## Coverage",
            "",
            f"- Calendar cutoff: {report.cutoffs.calendar_date}",
            f"- Canonical candle cutoff: {report.cutoffs.canonical_candle_date}",
            f"- Snapshot cutoff: {report.cutoffs.snapshot_date}",
            "- Corporate-action evidence cutoff: "
            f"{report.cutoffs.corporate_action_evidence_date}",
            "- Identity-transition evidence cutoff: "
            f"{report.cutoffs.identity_transition_evidence_date}",
            f"- Final common audit date: {report.cutoffs.final_common_audit_date}",
            f"- 2026 YTD events observed: {report.cutoffs.ytd_2026_events}",
            f"- 2026 YTD events admitted: {report.cutoffs.ytd_2026_admitted_events}",
            f"- 2026 YTD certified: {report.cutoffs.ytd_2026_certified}",
            "",
            "## Official Evidence",
            "",
            f"- Sources attempted: {report.source_summary.attempted}",
            f"- Sources acquired: {report.source_summary.acquired}",
            f"- Sources reused: {report.source_summary.reused}",
            f"- Sources failed: {report.source_summary.failed}",
            f"- Events admitted: {report.event_summary.admitted}",
            f"- Events rejected: {report.event_summary.rejected}",
            f"- Splits: {counts.get('SPLIT', 0)}",
            f"- Bonuses: {counts.get('BONUS', 0)}",
            f"- Rights: {counts.get('RIGHTS', 0)}",
            f"- Dividends: {counts.get('DIVIDEND', 0)}",
            "",
            "## Price Basis",
            "",
            f"- Raw candle rows: {report.price_basis_summary.raw_candle_rows}",
            "- Derived adjusted candle rows: "
            f"{report.price_basis_summary.adjusted_candle_rows}",
            "- Fully adjusted identities: "
            f"{report.price_basis_summary.identities_fully_adjusted}",
            "- Mixed-basis identities: "
            f"{report.price_basis_summary.mixed_basis_identities}",
            "- Unresolved action intervals: "
            f"{report.price_basis_summary.unresolved_action_intervals}",
            "",
            "## Continuity and Exposure",
            "",
            f"- Raw discontinuities: {report.continuity_summary.raw_discontinuities}",
            "- Adjusted discontinuities: "
            f"{report.continuity_summary.adjusted_discontinuities}",
            "- False-breakdown risks: "
            f"{report.continuity_summary.false_breakdown_risks}",
            f"- False-breakout risks: {report.continuity_summary.false_breakout_risks}",
            f"- Technical candidates: {report.candidate_exposure_summary.technical}",
            f"- BUY: {report.candidate_exposure_summary.buy}",
            f"- STRONG BUY: {report.candidate_exposure_summary.strong_buy}",
            "- Candidate-level linkage available: "
            f"{report.candidate_exposure_summary.linkage_available}",
            "",
            "## Governance",
            "",
            "- Raw canonical candles were not mutated.",
            "- Dividend events do not alter technical price series.",
            "- Reorganisation factors are not guessed.",
            "- Saved aggregate candidates are not presented as row-level attribution.",
            "- `PRODUCTION_INFLUENCE=false`",
            "",
        ]
        return "\n".join(lines)

    @staticmethod
    def _certification_markdown(report: CorporateActionPriceReport) -> str:
        lines = [
            "# HTR-009B Certification",
            "",
            f"Primary state: `{report.certification.primary_state.value}`",
            "",
            report.certification.rationale,
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
                "## Certification Thresholds",
                "",
                *(f"- {item}" for item in report.certification.thresholds),
                "",
                "`PRODUCTION_INFLUENCE=false`",
                "",
            ]
        )
        return "\n".join(lines)

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


__all__ = ["CorporateActionPriceArtifactExporter"]
