"""Deterministic HTR-009A JSON, CSV, and Markdown artifact exports."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

from alpha.historical_truth.point_in_time_identity_models import (
    IdentityState,
    PointInTimeIdentityReport,
    SourceStatus,
)


class PointInTimeIdentityArtifactExporter:
    """Write the complete stable HTR-009A evidence surface."""

    _PAIRS = (
        ("htr009a_source_inventory", "sources"),
        ("htr009a_security_identities", "identities"),
        ("htr009a_identity_intervals", "identity_intervals"),
        ("htr009a_symbol_history", "symbol_history"),
        ("htr009a_symbol_reuse", "symbol_reuse"),
        ("htr009a_symbol_changes", "symbol_changes"),
        ("htr009a_listing_delisting", "listing_delisting"),
        ("htr009a_suspensions", "suspensions"),
        ("htr009a_membership_intervals", "membership_intervals"),
        ("htr009a_candle_identity_reconciliation", "candle_reconciliation"),
        ("htr009a_candidate_exposure", "candidate_exposure"),
        ("htr009a_survivorship_audit", "survivorship"),
        ("htr009a_rejected_evidence", "rejected_evidence"),
    )

    def export(
        self,
        report: PointInTimeIdentityReport,
        output_directory: Path,
    ) -> tuple[Path, ...]:
        output_directory.mkdir(parents=True, exist_ok=True)
        files: list[Path] = [
            self._json(
                output_directory / "htr009a_executive_report.json",
                report.payload(),
            ),
            self._text(
                output_directory / "htr009a_executive_report.md",
                self._render_executive(report),
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
            "time_boundaries": self._jsonable(asdict(report.time_boundaries)),
            "ytd_summary": self._jsonable(asdict(report.ytd_summary)),
            "source_summary": self._jsonable(asdict(report.source_summary)),
            "identity_summary": self._jsonable(asdict(report.identity_summary)),
            "membership_summary": self._jsonable(asdict(report.membership_summary)),
            "certification": self._jsonable(asdict(report.certification)),
            "report_sha256": report.report_sha256,
        }
        files.extend(
            (
                self._json(
                    output_directory / "htr009a_certification.json",
                    certification,
                ),
                self._text(
                    output_directory / "htr009a_certification.md",
                    self._render_certification(report),
                ),
            )
        )
        return tuple(files)

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
    def _render_executive(report: PointInTimeIdentityReport) -> str:
        identity_counts = {
            state: sum(item.identity_state is state for item in report.identities)
            for state in IdentityState
        }
        source_counts = {
            status: sum(item.status is status for item in report.sources)
            for status in SourceStatus
        }
        candle_rows = sum(item.candle_rows for item in report.candle_reconciliation)
        active_days = sum(
            item.identity_days
            for item in report.membership_intervals
            if item.membership_state.value == "ACTIVE_TRADABLE"
        )
        boundary = report.time_boundaries
        unavailable = "unavailable"
        latest_calendar = boundary.latest_calendar_date or unavailable
        latest_canonical = boundary.latest_canonical_date or unavailable
        latest_snapshot = boundary.latest_snapshot_date or unavailable
        latest_master = boundary.latest_official_master_date or unavailable
        latest_identity = boundary.latest_identity_supported_date or unavailable
        final_common = boundary.final_common_as_of_date or unavailable
        governed = identity_counts[IdentityState.GOVERNED_IDENTITY]
        provisional = identity_counts[IdentityState.PROVISIONAL_IDENTITY]
        ytd_latest = report.ytd_summary.latest_canonical_date or unavailable
        ytd_included = report.ytd_summary.included_in_certified_window
        ytd_exclusion = report.ytd_summary.exclusion_reason or "none"
        ytd_isins = report.ytd_summary.observed_isin_identities
        master_covered = report.source_summary.security_master_dates_covered
        master_uncovered = report.source_summary.security_master_dates_uncovered
        expected_days = report.membership_summary.identity_days_expected
        unresolved_days = report.membership_summary.unresolved_membership_days
        lines = [
            "# HTR-009A Point-in-Time Security Universe and Identity",
            "",
            f"Window: `{report.start_date}` to `{report.end_date}`",
            f"Certification: `{report.certification.primary_state.value}`",
            f"Report SHA-256: `{report.report_sha256}`",
            "",
            "## Time Boundaries",
            "",
            f"- Latest official calendar: `{latest_calendar}`",
            f"- Latest canonical candle: `{latest_canonical}`",
            f"- Latest immutable snapshot: `{latest_snapshot}`",
            f"- Latest official security master: `{latest_master}`",
            f"- Latest identity-supported date: `{latest_identity}`",
            f"- Final common certified date: `{final_common}`",
            "",
            "## Source Evidence",
            "",
            f"- Acquired: {source_counts[SourceStatus.ACQUIRED]}",
            f"- Reused: {source_counts[SourceStatus.REUSED]}",
            f"- Failed: {source_counts[SourceStatus.FAILED]}",
            f"- Rejected: {source_counts[SourceStatus.REJECTED]}",
            f"- Rejected records: {len(report.rejected_evidence)}",
            f"- Security-master dates covered: {master_covered}",
            f"- Security-master dates uncovered: {master_uncovered}",
            "",
            "## Identity and Membership",
            "",
            f"- Observed identities: {len(report.identities)}",
            f"- Governed identities: {governed}",
            f"- Provisional identities: {provisional}",
            f"- Symbol reuse cases: {len(report.symbol_reuse)}",
            f"- Symbol changes observed: {len(report.symbol_changes)}",
            f"- Canonical rows classified: {candle_rows}",
            f"- Observed active-trading identity-days: {active_days}",
            f"- Expected identity-days: {expected_days}",
            f"- Unresolved membership-days: {unresolved_days}",
            "",
            "## Interpretation",
            "",
            report.certification.rationale,
            "",
            "A bhavcopy row proves that a named security traded on that date. "
            "It does not prove silent daily membership, a listing boundary, a "
            "delisting boundary, or a suspension interval. Those claims remain "
            "unresolved unless a date-specific official source supports them.",
            "",
            "## 2026 YTD",
            "",
            f"- Latest canonical date: `{ytd_latest}`",
            f"- Included in certified window: {ytd_included}",
            f"- Exclusion reason: `{ytd_exclusion}`",
            f"- Canonical rows: {report.ytd_summary.canonical_rows}",
            f"- Observed ISIN identities: {ytd_isins}",
            "- Membership, listing, delisting, suspension, and candidate "
            "exposure: unavailable until source coverage is certified.",
            "",
            "`PRODUCTION_INFLUENCE=false`",
        ]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _render_certification(report: PointInTimeIdentityReport) -> str:
        lines = [
            "# HTR-009A Certification",
            "",
            f"Primary state: `{report.certification.primary_state.value}`",
            "",
            report.certification.rationale,
            "",
            "## Explicit Thresholds",
            "",
        ]
        lines.extend(f"- {item}" for item in report.certification.thresholds)
        lines.extend(["", "## Secondary Blockers", ""])
        if report.certification.secondary_blockers:
            lines.extend(
                f"- `{item.value}`" for item in report.certification.secondary_blockers
            )
        else:
            lines.append("- None")
        lines.extend(
            [
                "",
                "No present-day universe was backfilled, no symbol-only identity "
                "join was admitted, and no candle value was changed.",
                "",
                "`PRODUCTION_INFLUENCE=false`",
            ]
        )
        return "\n".join(lines) + "\n"


__all__ = ["PointInTimeIdentityArtifactExporter"]
