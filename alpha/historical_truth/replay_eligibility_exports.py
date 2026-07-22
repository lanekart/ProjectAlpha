"""Deterministic HTR-008 JSON, CSV, and Markdown artifact exports."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

from alpha.historical_truth.replay_eligibility_models import (
    ReplayEligibilityIntegrityReport,
)


class ReplayEligibilityArtifactExporter:
    """Export stable summary and evidence views for HTR-008."""

    def export(
        self,
        report: ReplayEligibilityIntegrityReport,
        output_directory: Path,
    ) -> tuple[Path, ...]:
        output_directory.mkdir(parents=True, exist_ok=True)
        baseline_directory = output_directory / "baseline"
        baseline_directory.mkdir(parents=True, exist_ok=True)
        records = [self._record(row) for row in report.records]
        identity = [
            self._select(
                row,
                "identity_key",
                "exchange",
                "symbols",
                "series",
                "isins",
                "identity_governed",
                "active_identity_candidates_max",
                "primary_classification",
                "secondary_issue_codes",
            )
            for row in records
        ]
        history = [
            self._select(
                row,
                "identity_key",
                "first_observed_session",
                "last_observed_session",
                "total_candle_rows",
                "valid_candle_sessions",
                "invalid_candle_sessions",
                "first_20_session_date",
                "first_50_session_date",
                "first_100_session_date",
                "first_150_session_date",
                "first_200_session_date",
                "first_500_session_date",
                "first_1000_session_date",
                "replay_eligible_start_date",
                "replay_eligible_security_days",
            )
            for row in records
        ]
        continuity = [
            self._select(
                row,
                "identity_key",
                "expected_sessions",
                "observed_sessions",
                "explained_missing_sessions",
                "unexplained_missing_sessions",
                "coverage_ratio",
                "longest_continuous_valid_session_streak",
                "longest_unexplained_internal_gap",
                "unexplained_internal_gap_count",
            )
            for row in records
        ]
        lineage = [
            self._select(
                row,
                "identity_key",
                "total_candle_rows",
                "source_hash_rows",
                "detailed_lineage_rows",
                "snapshot_evidence_valid",
                "primary_classification",
                "secondary_issue_codes",
            )
            for row in records
        ]
        survivorship = [
            self._select(
                row,
                "identity_key",
                "symbols",
                "isins",
                "identity_governed",
                "first_observed_session",
                "last_observed_session",
                "survivorship_risk",
                "secondary_issue_codes",
            )
            for row in records
        ]
        point_in_time = [self._record(row) for row in report.funnel]
        candidates = [self._record(row) for row in report.candidate_exposure]
        actions = [self._record(row) for row in report.corporate_actions]
        quality = self._metric_rows(asdict(report.candle_quality))
        blockers = self._blocker_rows(records)
        certification = {
            "contract_version": report.contract_version,
            "production_influence": report.production_influence,
            "policy": self._record(report.policy),
            "certification": self._record(report.certification),
            "reconciliation": self._record(report.reconciliation),
            "report_sha256": report.report_sha256,
        }
        baseline = self._record(report.baseline)
        files: list[Path] = []
        files.extend(
            [
                self._json(
                    output_directory / "htr008_replay_eligibility_integrity.json",
                    report.payload(),
                ),
                self._csv(
                    output_directory / "htr008_replay_eligibility_integrity.csv",
                    records,
                ),
                self._text(
                    output_directory / "htr008_replay_eligibility_integrity.md",
                    self._render_report(report),
                ),
            ]
        )
        files.extend(
            self._json_csv(output_directory, "htr008_identity_integrity", identity)
        )
        files.extend(self._json_csv(output_directory, "htr008_history_depth", history))
        files.extend(
            self._json_csv(output_directory, "htr008_continuity_gaps", continuity)
        )
        files.extend(self._json_csv(output_directory, "htr008_candle_quality", quality))
        files.extend(self._json_csv(output_directory, "htr008_source_lineage", lineage))
        files.extend(
            self._json_csv(output_directory, "htr008_corporate_action_risk", actions)
        )
        files.extend(
            self._json_csv(output_directory, "htr008_survivorship_risk", survivorship)
        )
        files.extend(
            self._json_csv(
                output_directory,
                "htr008_point_in_time_eligibility",
                point_in_time,
            )
        )
        files.extend(
            self._json_csv(output_directory, "htr008_candidate_exposure", candidates)
        )
        files.extend(
            [
                self._json(
                    output_directory / "htr008_certification.json",
                    certification,
                ),
                self._text(
                    output_directory / "htr008_certification.md",
                    self._render_certification(report),
                ),
            ]
        )
        files.extend(
            self._json_csv(output_directory, "htr008_blocker_summary", blockers)
        )
        files.extend(
            [
                self._json(baseline_directory / "htr008_baseline.json", baseline),
                self._text(
                    baseline_directory / "htr008_baseline.md",
                    self._render_baseline(report),
                ),
            ]
        )
        return tuple(files)

    def _json_csv(
        self,
        output: Path,
        stem: str,
        rows: list[dict[str, Any]],
    ) -> tuple[Path, Path]:
        return (
            self._json(output / f"{stem}.json", {"records": rows}),
            self._csv(output / f"{stem}.csv", rows),
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
        fields = tuple(rows[0]) if rows else ("identity_key",)
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
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        return path

    @staticmethod
    def _record(value: Any) -> dict[str, Any]:
        raw: dict[str, Any] = asdict(value)
        normalized = ReplayEligibilityArtifactExporter._normalize(raw)
        if not isinstance(normalized, dict):
            raise TypeError("artifact record must serialize to an object")
        return normalized

    @classmethod
    def _normalize(cls, value: object) -> Any:
        if isinstance(value, dict):
            return {str(key): cls._normalize(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [cls._normalize(item) for item in value]
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, StrEnum):
            return value.value
        return value

    @staticmethod
    def _select(row: dict[str, Any], *keys: str) -> dict[str, Any]:
        return {key: row[key] for key in keys}

    @staticmethod
    def _metric_rows(payload: dict[str, object]) -> list[dict[str, Any]]:
        return [
            {"metric": key, "value": value} for key, value in sorted(payload.items())
        ]

    @staticmethod
    def _blocker_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for row in records:
            primary = str(row["primary_classification"])
            counts[primary] = counts.get(primary, 0) + 1
            for issue in row["secondary_issue_codes"]:
                code = str(issue)
                counts[code] = counts.get(code, 0) + 1
        return [
            {"blocker": code, "affected_identities": count}
            for code, count in sorted(
                counts.items(), key=lambda item: (-item[1], item[0])
            )
        ]

    @staticmethod
    def _render_report(report: ReplayEligibilityIntegrityReport) -> str:
        population = report.population
        reconciliation = report.reconciliation
        return "\n".join(
            [
                "# HTR-008 Replay Eligibility Integrity",
                "",
                f"- Window: {report.start_date} to {report.end_date}",
                f"- Raw symbols: {population.distinct_raw_symbols:,}",
                f"- Distinct ISINs: {population.distinct_isins:,}",
                f"- Observed identities: {report.depth.identity_count:,}",
                f"- Governed identities: {population.governed_identities:,}",
                f"- Identities with 200 valid sessions: {report.depth.at_least_200:,}",
                (
                    "- Final replay-ready identities: "
                    f"{reconciliation.final_replay_ready_identities:,}"
                ),
                (
                    "- Final replay-ready security-days: "
                    f"{reconciliation.final_replay_ready_security_days:,}"
                ),
                f"- Certification: {report.certification.primary_state.value}",
                f"- Report SHA-256: `{report.report_sha256}`",
                "",
                "## Interpretation",
                "",
                report.certification.rationale,
                "",
                "Observed candle depth is not treated as authoritative identity, "
                "listing, "
                "corporate-action, or point-in-time universe evidence.",
                "",
                "**PRODUCTION_INFLUENCE=false**",
            ]
        )

    @staticmethod
    def _render_certification(report: ReplayEligibilityIntegrityReport) -> str:
        blockers = (
            ", ".join(
                blocker.value for blocker in report.certification.secondary_blockers
            )
            or "none"
        )
        return "\n".join(
            [
                "# HTR-008 Certification",
                "",
                f"- Primary state: {report.certification.primary_state.value}",
                f"- Secondary blockers: {blockers}",
                f"- Missing snapshots: {len(report.snapshots.missing_dates)}",
                f"- Invalid snapshots: {len(report.snapshots.invalid_dates)}",
                (
                    "- Benchmark eligible securities: "
                    f"{report.baseline.eligible_securities:,}"
                ),
                (
                    "- HTR-008 replay-ready identities: "
                    f"{report.reconciliation.final_replay_ready_identities:,}"
                ),
                "",
                report.certification.rationale,
                "",
                "**PRODUCTION_INFLUENCE=false**",
            ]
        )

    @staticmethod
    def _render_baseline(report: ReplayEligibilityIntegrityReport) -> str:
        baseline = report.baseline
        reasons = "\n".join(
            f"- {reason}: {count:,}" for reason, count in baseline.rejection_reasons
        )
        return "\n".join(
            [
                "# HTR-008 Frozen Baseline",
                "",
                f"- Run: {baseline.run_id}",
                f"- Repository commit: `{baseline.repository_commit}`",
                f"- Database SHA-256: `{baseline.database_sha256}`",
                f"- Snapshot inventory SHA-256: `{baseline.snapshot_inventory_sha256}`",
                f"- Sessions: {baseline.sessions:,}",
                f"- Eligible securities: {baseline.eligible_securities:,}",
                f"- Eligible security-days: {baseline.eligible_security_days:,}",
                f"- Technical candidates: {baseline.technical_candidates:,}",
                f"- BUY candidates: {baseline.buy_candidates:,}",
                f"- STRONG BUY candidates: {baseline.strong_buy_candidates:,}",
                f"- Institutional approvals: {baseline.institutional_approvals:,}",
                f"- Trades: {baseline.trades:,}",
                "",
                "## Rejection Reasons",
                "",
                reasons,
                "",
                "**PRODUCTION_INFLUENCE=false**",
            ]
        )


__all__ = ["ReplayEligibilityArtifactExporter"]
