from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.models import ManifestRecord, ManifestStatus
from alpha.historical_truth.resumable import HistoricalTruthWarehouse
from alpha.historical_truth.snapshots import PointInTimeSnapshotEngine


class UnavailableClassification(StrEnum):
    HOLIDAY = "holiday"
    ARCHIVE_MISSING = "archive_missing"
    URL_ERROR = "url_error"
    DATA_NOT_RELEASED = "data_not_released"


@dataclass(frozen=True, slots=True)
class MissingDateFinding:
    trading_date: date
    classification: str
    source_url: str | None
    evidence: str


@dataclass(frozen=True, slots=True)
class SecurityFinding:
    trading_date: date
    code: str
    severity: str
    symbol: str
    series: str
    isin: str | None
    evidence: str


@dataclass(frozen=True, slots=True)
class SnapshotFinding:
    trading_date: date
    exists: bool
    checksum_valid: bool
    metadata_valid: bool
    evidence: str


@dataclass(frozen=True, slots=True)
class IntegritySummary:
    start_date: date
    end_date: date
    weekday_candidates: int
    explicit_holidays: int
    expected_trading_days: int
    observed_trading_days: int
    coverage_ratio: float
    missing_dates: int
    duplicate_securities: int
    duplicate_isins: int
    invalid_ohlc: int
    negative_prices: int
    zero_volume_anomalies: int
    validation_errors: int
    validation_warnings: int
    snapshots_expected: int
    snapshots_valid: int
    candle_replay_ready: bool
    full_evidence_replay_ready: bool


@dataclass(frozen=True, slots=True)
class IntegrityAuditReport:
    summary: IntegritySummary
    missing_dates: tuple[MissingDateFinding, ...]
    security_findings: tuple[SecurityFinding, ...]
    snapshot_findings: tuple[SnapshotFinding, ...]
    replay_blockers: tuple[str, ...]


class HistoricalTruthIntegrityAudit:
    """Deterministic, diagnostic-only integrity audit for historical truth."""

    def __init__(
        self,
        archive: HistoricalTruthWarehouse,
        canonical: CanonicalPointInTimeWarehouse,
        snapshots: PointInTimeSnapshotEngine,
        *,
        holiday_dates: frozenset[date] = frozenset(),
    ) -> None:
        self.archive = archive
        self.canonical = canonical
        self.snapshots = snapshots
        self.holiday_dates = holiday_dates

    def audit(
        self,
        start_date: date,
        end_date: date,
        *,
        as_of_date: date,
        exchange: str = "nse",
    ) -> IntegrityAuditReport:
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        exchange = exchange.lower()
        weekdays = self._weekdays(start_date, end_date)
        holidays = frozenset(day for day in weekdays if day in self.holiday_dates)
        expected = tuple(day for day in weekdays if day not in holidays)
        observed = self._observed_dates(start_date, end_date, exchange)
        observed_set = set(observed)
        manifest = {
            record.trading_date: record
            for record in self.archive.records()
            if record.exchange.lower() == exchange
            and start_date <= record.trading_date <= end_date
        }
        missing = tuple(
            self._missing_finding(
                day,
                manifest.get(day),
                as_of_date=as_of_date,
                holiday=day in holidays,
            )
            for day in weekdays
            if day not in observed_set
        )
        security_findings = self._security_findings(
            start_date,
            end_date,
            exchange,
        ) + self._staged_validation_findings(start_date, end_date)
        security_findings = tuple(
            sorted(
                security_findings,
                key=lambda item: (
                    item.trading_date,
                    item.code,
                    item.symbol,
                    item.series,
                    item.evidence,
                ),
            )
        )
        snapshots = tuple(
            self._snapshot_finding(day, exchange) for day in observed
        )
        counts = self._finding_counts(security_findings)
        coverage = len(observed_set.intersection(expected)) / len(expected) if expected else 1.0
        snapshots_valid = sum(
            finding.exists
            and finding.checksum_valid
            and finding.metadata_valid
            for finding in snapshots
        )
        candle_ready = (
            coverage == 1.0
            and not any(
                counts.get(code, 0)
                for code in (
                    "DUPLICATE_SECURITY",
                    "INVALID_OHLC",
                    "NEGATIVE_PRICE",
                    "VALIDATION_ERROR",
                )
            )
            and snapshots_valid == len(observed)
        )
        blockers: list[str] = []
        if coverage < 1.0:
            blockers.append("MISSING_EXPECTED_TRADING_DAYS")
        if counts.get("DUPLICATE_SECURITY", 0):
            blockers.append("DUPLICATE_SECURITIES")
        if counts.get("INVALID_OHLC", 0):
            blockers.append("INVALID_OHLC_RELATIONSHIPS")
        if counts.get("NEGATIVE_PRICE", 0):
            blockers.append("NEGATIVE_PRICES")
        if counts.get("VALIDATION_ERROR", 0):
            blockers.append("SOURCE_VALIDATION_ERRORS")
        if snapshots_valid != len(observed):
            blockers.append("SNAPSHOT_INTEGRITY_FAILURES")
        blockers.append("NON_CANDLE_EVIDENCE_NOT_AUDITED")
        summary = IntegritySummary(
            start_date=start_date,
            end_date=end_date,
            weekday_candidates=len(weekdays),
            explicit_holidays=len(holidays),
            expected_trading_days=len(expected),
            observed_trading_days=len(observed_set.intersection(expected)),
            coverage_ratio=round(coverage, 6),
            missing_dates=len(missing),
            duplicate_securities=counts.get("DUPLICATE_SECURITY", 0),
            duplicate_isins=counts.get("DUPLICATE_ISIN", 0),
            invalid_ohlc=counts.get("INVALID_OHLC", 0),
            negative_prices=counts.get("NEGATIVE_PRICE", 0),
            zero_volume_anomalies=counts.get("ZERO_VOLUME", 0),
            validation_errors=counts.get("VALIDATION_ERROR", 0),
            validation_warnings=counts.get("VALIDATION_WARNING", 0),
            snapshots_expected=len(observed),
            snapshots_valid=snapshots_valid,
            candle_replay_ready=candle_ready,
            full_evidence_replay_ready=False,
        )
        return IntegrityAuditReport(
            summary=summary,
            missing_dates=missing,
            security_findings=security_findings,
            snapshot_findings=snapshots,
            replay_blockers=tuple(dict.fromkeys(blockers)),
        )

    def export(
        self,
        report: IntegrityAuditReport,
        output_dir: Path,
    ) -> tuple[Path, Path, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "historical_truth_integrity.json"
        csv_path = output_dir / "historical_truth_integrity.csv"
        markdown_path = output_dir / "historical_truth_integrity.md"
        payload = self._report_payload(report)
        json_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        rows = self._csv_rows(report)
        fieldnames = (
            "finding_type",
            "trading_date",
            "code",
            "severity",
            "symbol",
            "series",
            "isin",
            "evidence",
        )
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        markdown_path.write_text(
            self._markdown(report),
            encoding="utf-8",
        )
        return json_path, csv_path, markdown_path

    def _missing_finding(
        self,
        trading_date: date,
        record: ManifestRecord | None,
        *,
        as_of_date: date,
        holiday: bool,
    ) -> MissingDateFinding:
        if holiday:
            classification = UnavailableClassification.HOLIDAY
            evidence = "date is present in the explicitly supplied holiday set"
        elif record is not None and record.status is ManifestStatus.FAILED:
            return MissingDateFinding(
                trading_date=trading_date,
                classification="retrieval_failed",
                source_url=record.source_url,
                evidence=record.error or "manifest reports FAILED",
            )
        elif record is not None and record.status is not ManifestStatus.UNAVAILABLE:
            return MissingDateFinding(
                trading_date=trading_date,
                classification="validation_or_ingestion_failed",
                source_url=record.source_url,
                evidence=f"manifest status is {record.status.value}; no canonical candles",
            )
        elif trading_date >= as_of_date:
            classification = UnavailableClassification.DATA_NOT_RELEASED
            evidence = "date is on or after the audit as-of date"
        else:
            expected_url = self.archive._nse_bhavcopy_request(trading_date).source_url
            if record is not None and record.source_url != expected_url:
                classification = UnavailableClassification.URL_ERROR
                evidence = (
                    f"manifest URL differs from deterministic canonical URL: {expected_url}"
                )
            else:
                classification = UnavailableClassification.ARCHIVE_MISSING
                evidence = (
                    record.error
                    if record is not None and record.error
                    else "past expected session has no canonical candles"
                )
        return MissingDateFinding(
            trading_date=trading_date,
            classification=classification.value,
            source_url=record.source_url if record is not None else None,
            evidence=evidence,
        )

    def _security_findings(
        self,
        start_date: date,
        end_date: date,
        exchange: str,
    ) -> tuple[SecurityFinding, ...]:
        self.canonical.initialise()
        with self.canonical._connect() as connection:
            rows = connection.execute(
                """
                SELECT trading_date, symbol, series, isin,
                       open_price, high_price, low_price, close_price, volume
                FROM daily_candle
                WHERE exchange = ? AND trading_date BETWEEN ? AND ?
                ORDER BY trading_date, symbol, series
                """,
                [exchange, start_date, end_date],
            ).fetchall()
        findings: list[SecurityFinding] = []
        seen_security: set[tuple[date, str, str]] = set()
        isin_symbols: dict[tuple[date, str], set[tuple[str, str]]] = {}
        for row in rows:
            trading_date = row[0]
            symbol, series = str(row[1]), str(row[2])
            isin = str(row[3]) if row[3] is not None else None
            open_, high, low, close = (float(value) for value in row[4:8])
            volume = int(row[8])
            key = (trading_date, symbol, series)
            if key in seen_security:
                findings.append(
                    self._finding(
                        trading_date,
                        "DUPLICATE_SECURITY",
                        "error",
                        symbol,
                        series,
                        isin,
                        "duplicate trading_date/exchange/symbol/series row",
                    )
                )
            seen_security.add(key)
            if isin:
                isin_symbols.setdefault((trading_date, isin), set()).add(
                    (symbol, series)
                )
            violations = self._ohlc_violations(open_, high, low, close)
            if violations:
                findings.append(
                    self._finding(
                        trading_date,
                        "INVALID_OHLC",
                        "error",
                        symbol,
                        series,
                        isin,
                        (
                            f"open={open_}; high={high}; low={low}; close={close}; "
                            f"violations={','.join(violations)}"
                        ),
                    )
                )
            if min(open_, high, low, close) < 0:
                findings.append(
                    self._finding(
                        trading_date,
                        "NEGATIVE_PRICE",
                        "error",
                        symbol,
                        series,
                        isin,
                        f"open={open_}; high={high}; low={low}; close={close}",
                    )
                )
            if volume == 0:
                findings.append(
                    self._finding(
                        trading_date,
                        "ZERO_VOLUME",
                        "warning",
                        symbol,
                        series,
                        isin,
                        "official candle reports zero traded volume",
                    )
                )
        for (trading_date, isin), securities in isin_symbols.items():
            if len(securities) > 1:
                rendered = ",".join(f"{symbol}/{series}" for symbol, series in sorted(securities))
                symbol, series = sorted(securities)[0]
                findings.append(
                    self._finding(
                        trading_date,
                        "DUPLICATE_ISIN",
                        "warning",
                        symbol,
                        series,
                        isin,
                        f"ISIN maps to multiple securities on one date: {rendered}",
                    )
                )
        return tuple(findings)

    def _staged_validation_findings(
        self,
        start_date: date,
        end_date: date,
    ) -> tuple[SecurityFinding, ...]:
        root = self.archive.root / "staging" / "population"
        if not root.exists():
            return ()
        findings: list[SecurityFinding] = []
        for csv_path in sorted(root.rglob("*.csv")):
            try:
                trading_date = date.fromisoformat(csv_path.parent.name)
            except ValueError:
                continue
            if not start_date <= trading_date <= end_date:
                continue
            for issue in self.archive.validate_bhavcopy_csv(csv_path):
                severity = issue.severity.value
                code = (
                    "VALIDATION_ERROR"
                    if severity == "error"
                    else "VALIDATION_WARNING"
                )
                findings.append(
                    self._finding(
                        trading_date,
                        code,
                        severity,
                        "",
                        "",
                        None,
                        f"{issue.code}; row={issue.row_number}; {issue.message}",
                    )
                )
        return tuple(findings)

    def _snapshot_finding(
        self,
        trading_date: date,
        exchange: str,
    ) -> SnapshotFinding:
        path = self.snapshots.path_for(trading_date, exchange=exchange)
        if not path.exists():
            return SnapshotFinding(
                trading_date=trading_date,
                exists=False,
                checksum_valid=False,
                metadata_valid=False,
                evidence="snapshot file is missing",
            )
        try:
            snapshot = self.snapshots.load(trading_date, exchange=exchange)
            verification = self.snapshots.verify(snapshot)
            market = self.canonical.snapshot(trading_date, exchange=exchange)
            metadata_valid = (
                snapshot.metadata.trading_date == trading_date
                and snapshot.metadata.exchange == exchange
                and snapshot.metadata.symbol_count == market.symbol_count
                and snapshot.metadata.total_volume == market.total_volume
            )
            evidence = (
                "checksum and canonical metadata match"
                if verification.valid and metadata_valid
                else (
                    f"checksum_valid={verification.valid}; "
                    f"metadata_valid={metadata_valid}"
                )
            )
            return SnapshotFinding(
                trading_date=trading_date,
                exists=True,
                checksum_valid=verification.valid,
                metadata_valid=metadata_valid,
                evidence=evidence,
            )
        except (KeyError, OSError, TypeError, ValueError) as exc:
            return SnapshotFinding(
                trading_date=trading_date,
                exists=True,
                checksum_valid=False,
                metadata_valid=False,
                evidence=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _weekdays(start_date: date, end_date: date) -> tuple[date, ...]:
        count = (end_date - start_date).days
        return tuple(
            candidate
            for offset in range(count + 1)
            if (candidate := start_date + timedelta(days=offset)).weekday() < 5
        )

    def _observed_dates(
        self,
        start_date: date,
        end_date: date,
        exchange: str,
    ) -> tuple[date, ...]:
        self.canonical.initialise()
        with self.canonical._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT trading_date
                FROM daily_candle
                WHERE exchange = ? AND trading_date BETWEEN ? AND ?
                ORDER BY trading_date
                """,
                [exchange, start_date, end_date],
            ).fetchall()
        return tuple(row[0] for row in rows)

    @staticmethod
    def _ohlc_violations(
        open_: float,
        high: float,
        low: float,
        close: float,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        if high < open_:
            violations.append("high<open")
        if high < close:
            violations.append("high<close")
        if high < low:
            violations.append("high<low")
        if low > open_:
            violations.append("low>open")
        if low > close:
            violations.append("low>close")
        return tuple(violations)

    @staticmethod
    def _finding(
        trading_date: date,
        code: str,
        severity: str,
        symbol: str,
        series: str,
        isin: str | None,
        evidence: str,
    ) -> SecurityFinding:
        return SecurityFinding(
            trading_date=trading_date,
            code=code,
            severity=severity,
            symbol=symbol,
            series=series,
            isin=isin,
            evidence=evidence,
        )

    @staticmethod
    def _finding_counts(
        findings: tuple[SecurityFinding, ...],
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in findings:
            counts[finding.code] = counts.get(finding.code, 0) + 1
        return counts

    @staticmethod
    def _report_payload(report: IntegrityAuditReport) -> dict[str, Any]:
        summary = asdict(report.summary)
        summary["start_date"] = report.summary.start_date.isoformat()
        summary["end_date"] = report.summary.end_date.isoformat()
        return {
            "summary": summary,
            "missing_dates": [
                {
                    **asdict(item),
                    "trading_date": item.trading_date.isoformat(),
                }
                for item in report.missing_dates
            ],
            "security_findings": [
                {
                    **asdict(item),
                    "trading_date": item.trading_date.isoformat(),
                }
                for item in report.security_findings
            ],
            "snapshot_findings": [
                {
                    **asdict(item),
                    "trading_date": item.trading_date.isoformat(),
                }
                for item in report.snapshot_findings
            ],
            "replay_blockers": list(report.replay_blockers),
        }

    @staticmethod
    def _csv_rows(report: IntegrityAuditReport) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for item in report.missing_dates:
            rows.append(
                {
                    "finding_type": "missing_date",
                    "trading_date": item.trading_date.isoformat(),
                    "code": item.classification,
                    "severity": "error",
                    "symbol": "",
                    "series": "",
                    "isin": "",
                    "evidence": item.evidence,
                }
            )
        for item in report.security_findings:
            rows.append(
                {
                    "finding_type": "security",
                    "trading_date": item.trading_date.isoformat(),
                    "code": item.code,
                    "severity": item.severity,
                    "symbol": item.symbol,
                    "series": item.series,
                    "isin": item.isin or "",
                    "evidence": item.evidence,
                }
            )
        for item in report.snapshot_findings:
            if item.exists and item.checksum_valid and item.metadata_valid:
                continue
            rows.append(
                {
                    "finding_type": "snapshot",
                    "trading_date": item.trading_date.isoformat(),
                    "code": "SNAPSHOT_INTEGRITY",
                    "severity": "error",
                    "symbol": "",
                    "series": "",
                    "isin": "",
                    "evidence": item.evidence,
                }
            )
        return rows

    @staticmethod
    def _markdown(report: IntegrityAuditReport) -> str:
        summary = report.summary
        lines = [
            "# Historical Truth Integrity Audit",
            "",
            f"Period: {summary.start_date.isoformat()} to {summary.end_date.isoformat()}",
            f"Expected trading days: {summary.expected_trading_days}",
            f"Observed trading days: {summary.observed_trading_days}",
            f"Coverage: {summary.coverage_ratio:.2%}",
            f"Candle replay ready: {summary.candle_replay_ready}",
            f"Full-evidence replay ready: {summary.full_evidence_replay_ready}",
            "",
            "## Validation statistics",
            "",
            f"- Missing dates: {summary.missing_dates}",
            f"- Duplicate securities: {summary.duplicate_securities}",
            f"- Duplicate ISINs: {summary.duplicate_isins}",
            f"- Invalid OHLC relationships: {summary.invalid_ohlc}",
            f"- Negative prices: {summary.negative_prices}",
            f"- Zero-volume anomalies: {summary.zero_volume_anomalies}",
            f"- Source validation errors: {summary.validation_errors}",
            f"- Source validation warnings: {summary.validation_warnings}",
            f"- Valid snapshots: {summary.snapshots_valid}/{summary.snapshots_expected}",
            "",
            "## Missing dates",
            "",
            "| Date | Classification | Evidence |",
            "|---|---|---|",
        ]
        for item in report.missing_dates:
            lines.append(
                f"| {item.trading_date.isoformat()} | {item.classification} | "
                f"{item.evidence.replace('|', '/')} |"
            )
        lines.extend(
            [
                "",
                "## Security findings",
                "",
                "| Date | Code | Severity | Security | Evidence |",
                "|---|---|---|---|---|",
            ]
        )
        for item in report.security_findings:
            lines.append(
                f"| {item.trading_date.isoformat()} | {item.code} | "
                f"{item.severity} | {item.symbol}/{item.series} | "
                f"{item.evidence.replace('|', '/')} |"
            )
        lines.extend(
            [
                "",
                "## Replay blockers",
                "",
                *[f"- {blocker}" for blocker in report.replay_blockers],
                "",
                "Full-evidence readiness remains false until the separately governed "
                "evidence layers are present and audited.",
                "",
            ]
        )
        return "\n".join(lines)
