from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable

import requests

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse

HTR007_SESSION_CALENDAR_CONTRACT_VERSION = "1.0"
NSE_TRADING_HOLIDAY_API = "https://www.nseindia.com/api/holiday-master?type=trading"
NSE_HOLIDAY_PAGE = "https://www.nseindia.com/resources/exchange-communication-holidays"


class SessionClassification(StrEnum):
    REGULAR_SESSION = "regular_session"
    SPECIAL_SESSION = "special_session"
    HOLIDAY = "holiday"
    WEEKEND = "weekend"
    UNRESOLVED_WEEKDAY = "unresolved_weekday"


class CalendarCertificationState(StrEnum):
    CERTIFIED = "certified"
    INCOMPLETE_OFFICIAL_EVIDENCE = "incomplete_official_evidence"


@dataclass(frozen=True, slots=True)
class OfficialHoliday:
    trading_date: date
    description: str
    source_id: str


@dataclass(frozen=True, slots=True)
class OfficialSpecialSession:
    trading_date: date
    description: str
    source_id: str


@dataclass(frozen=True, slots=True)
class OfficialCalendarSource:
    source_id: str
    source_path: str
    source_url: str | None
    source_sha256: str
    covered_years: tuple[int, ...]
    holidays: tuple[OfficialHoliday, ...]
    special_sessions: tuple[OfficialSpecialSession, ...]


@dataclass(frozen=True, slots=True)
class SessionCalendarRecord:
    trading_date: date
    classification: SessionClassification
    observed_candles: bool
    description: str | None
    source_ids: tuple[str, ...]
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnnualSessionSummary:
    year: int
    official_source_covered: bool
    weekday_candidates: int
    official_weekday_holidays: int
    official_special_sessions: int
    expected_sessions: int
    observed_sessions: int
    unresolved_weekdays: int
    unconfirmed_special_sessions: int
    missing_special_sessions: int
    conflicts: int


@dataclass(frozen=True, slots=True)
class SessionCalendarReport:
    contract_version: str
    start_date: date
    end_date: date
    exchange: str
    certification_state: CalendarCertificationState
    sources: tuple[OfficialCalendarSource, ...]
    annual_summaries: tuple[AnnualSessionSummary, ...]
    records: tuple[SessionCalendarRecord, ...]
    official_holiday_count: int
    official_special_session_count: int
    expected_session_count: int
    observed_session_count: int
    unresolved_weekday_count: int
    unconfirmed_special_session_count: int
    missing_special_session_count: int
    conflict_count: int
    report_sha256: str


class OfficialSessionCalendarEngine:
    """Reconcile official NSE CM session evidence with canonical candles."""

    def __init__(self, canonical: CanonicalPointInTimeWarehouse) -> None:
        self.canonical = canonical

    @staticmethod
    def fetch_current_official_source(
        source_dir: Path,
        *,
        timeout_seconds: float = 30.0,
        session: requests.Session | None = None,
    ) -> Path:
        """Fetch and immutably persist the official NSE trading-holiday payload."""

        client = session or requests.Session()
        headers = {
            "User-Agent": "ProjectAlpha-HistoricalTruth/1.0",
            "Accept": "application/json,text/plain,*/*",
            "Referer": NSE_HOLIDAY_PAGE,
        }
        client.get(NSE_HOLIDAY_PAGE, headers=headers, timeout=timeout_seconds)
        response = client.get(
            NSE_TRADING_HOLIDAY_API,
            headers=headers,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("CM"), list):
            raise ValueError("official NSE holiday payload does not contain a CM list")
        rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        dates = tuple(
            OfficialSessionCalendarEngine._parse_date(str(item["tradingDate"]))
            for item in payload["CM"]
            if isinstance(item, dict) and item.get("tradingDate")
        )
        years = sorted({item.year for item in dates})
        year_token = (
            f"{years[0]}-{years[-1]}" if years else "unknown-year"
        )
        source_dir.mkdir(parents=True, exist_ok=True)
        destination = source_dir / f"nse_cm_holidays_{year_token}_{digest[:12]}.json"
        if destination.exists():
            if destination.read_text(encoding="utf-8") != rendered:
                raise FileExistsError(
                    f"immutable official calendar source differs: {destination}"
                )
            return destination
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(destination)
        return destination

    @classmethod
    def load_source(cls, source_path: Path) -> OfficialCalendarSource:
        raw = source_path.read_bytes()
        source_sha256 = hashlib.sha256(raw).hexdigest()
        payload = json.loads(raw.decode("utf-8"))
        source_id = f"nse-calendar:{source_sha256}"
        source_url: str | None = None
        covered_years: set[int] = set()

        if isinstance(payload, dict) and isinstance(payload.get("CM"), list):
            holiday_payload = payload["CM"]
            special_payload: list[object] = []
            source_url = NSE_TRADING_HOLIDAY_API
        elif isinstance(payload, dict):
            holiday_payload = payload.get("holidays", [])
            special_payload = payload.get("special_sessions", [])
            source_url_value = payload.get("source_url")
            source_url = str(source_url_value) if source_url_value else None
            declared_years = payload.get("covered_years", [])
            if isinstance(declared_years, list):
                covered_years.update(int(year) for year in declared_years)
        elif isinstance(payload, list):
            holiday_payload = payload
            special_payload = []
        else:
            raise ValueError(f"unsupported official calendar source: {source_path}")

        if not isinstance(holiday_payload, list) or not isinstance(
            special_payload, list
        ):
            raise ValueError("holidays and special_sessions must be JSON lists")

        holidays = tuple(
            cls._holiday(item, source_id)
            for item in holiday_payload
            if isinstance(item, dict)
        )
        specials = tuple(
            cls._special_session(item, source_id)
            for item in special_payload
            if isinstance(item, dict)
        )
        covered_years.update(item.trading_date.year for item in holidays)
        covered_years.update(item.trading_date.year for item in specials)
        if not covered_years:
            raise ValueError(f"official calendar source has no covered years: {source_path}")

        return OfficialCalendarSource(
            source_id=source_id,
            source_path=str(source_path),
            source_url=source_url,
            source_sha256=source_sha256,
            covered_years=tuple(sorted(covered_years)),
            holidays=tuple(sorted(holidays, key=lambda item: item.trading_date)),
            special_sessions=tuple(
                sorted(specials, key=lambda item: item.trading_date)
            ),
        )

    def reconcile(
        self,
        start_date: date,
        end_date: date,
        sources: Iterable[OfficialCalendarSource],
        *,
        exchange: str = "nse",
    ) -> SessionCalendarReport:
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        exchange = exchange.lower()
        ordered_sources = tuple(sorted(sources, key=lambda item: item.source_id))
        holiday_map = self._holiday_map(ordered_sources, start_date, end_date)
        special_map = self._special_map(ordered_sources, start_date, end_date)
        covered_years = {
            year for source in ordered_sources for year in source.covered_years
        }
        observed = self._observed_dates(start_date, end_date, exchange)
        records = tuple(
            self._classify(
                current,
                observed=current in observed,
                holidays=holiday_map.get(current, ()),
                specials=special_map.get(current, ()),
            )
            for current in self._date_range(start_date, end_date)
        )
        annual = tuple(
            self._annual_summary(
                year,
                records,
                covered=year in covered_years,
                holiday_map=holiday_map,
                special_map=special_map,
            )
            for year in range(start_date.year, end_date.year + 1)
        )
        unresolved = sum(
            record.classification is SessionClassification.UNRESOLVED_WEEKDAY
            for record in records
        )
        unconfirmed = sum(
            "UNCONFIRMED_SPECIAL_SESSION" in record.issue_codes
            for record in records
        )
        missing_special = sum(
            "MISSING_OFFICIAL_SPECIAL_SESSION" in record.issue_codes
            for record in records
        )
        conflicts = sum(bool(record.issue_codes) for record in records) - unconfirmed - missing_special
        all_years_covered = all(item.official_source_covered for item in annual)
        state = (
            CalendarCertificationState.CERTIFIED
            if all_years_covered
            and unresolved == 0
            and unconfirmed == 0
            and missing_special == 0
            and conflicts == 0
            else CalendarCertificationState.INCOMPLETE_OFFICIAL_EVIDENCE
        )
        provisional = SessionCalendarReport(
            contract_version=HTR007_SESSION_CALENDAR_CONTRACT_VERSION,
            start_date=start_date,
            end_date=end_date,
            exchange=exchange,
            certification_state=state,
            sources=ordered_sources,
            annual_summaries=annual,
            records=records,
            official_holiday_count=len(holiday_map),
            official_special_session_count=len(special_map),
            expected_session_count=sum(item.expected_sessions for item in annual),
            observed_session_count=len(observed),
            unresolved_weekday_count=unresolved,
            unconfirmed_special_session_count=unconfirmed,
            missing_special_session_count=missing_special,
            conflict_count=conflicts,
            report_sha256="",
        )
        digest = hashlib.sha256(
            json.dumps(
                self._report_payload(provisional, include_hash=False),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return SessionCalendarReport(
            **{**asdict(provisional), "report_sha256": digest}
        )

    def export(
        self,
        report: SessionCalendarReport,
        output_dir: Path,
    ) -> tuple[Path, Path, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "htr007_session_calendar.json"
        csv_path = output_dir / "htr007_session_calendar.csv"
        markdown_path = output_dir / "htr007_session_calendar.md"
        payload = self._report_payload(report, include_hash=True)
        json_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=(
                    "trading_date",
                    "classification",
                    "observed_candles",
                    "description",
                    "source_ids",
                    "issue_codes",
                ),
            )
            writer.writeheader()
            for record in report.records:
                writer.writerow(
                    {
                        "trading_date": record.trading_date.isoformat(),
                        "classification": record.classification.value,
                        "observed_candles": record.observed_candles,
                        "description": record.description or "",
                        "source_ids": ";".join(record.source_ids),
                        "issue_codes": ";".join(record.issue_codes),
                    }
                )
        markdown_path.write_text(self._markdown(report), encoding="utf-8")
        return json_path, csv_path, markdown_path

    def _observed_dates(
        self,
        start_date: date,
        end_date: date,
        exchange: str,
    ) -> frozenset[date]:
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
        return frozenset(row[0] for row in rows)

    @staticmethod
    def _classify(
        trading_date: date,
        *,
        observed: bool,
        holidays: tuple[OfficialHoliday, ...],
        specials: tuple[OfficialSpecialSession, ...],
    ) -> SessionCalendarRecord:
        descriptions = tuple(
            dict.fromkeys(
                item.description for item in (*holidays, *specials) if item.description
            )
        )
        source_ids = tuple(
            sorted({item.source_id for item in (*holidays, *specials)})
        )
        issues: list[str] = []
        if specials:
            classification = SessionClassification.SPECIAL_SESSION
            if not observed:
                issues.append("MISSING_OFFICIAL_SPECIAL_SESSION")
        elif holidays:
            classification = SessionClassification.HOLIDAY
            if observed:
                issues.append("HOLIDAY_HAS_OBSERVED_CANDLES")
        elif trading_date.weekday() < 5:
            classification = (
                SessionClassification.REGULAR_SESSION
                if observed
                else SessionClassification.UNRESOLVED_WEEKDAY
            )
        elif observed:
            classification = SessionClassification.SPECIAL_SESSION
            issues.append("UNCONFIRMED_SPECIAL_SESSION")
        else:
            classification = SessionClassification.WEEKEND
        return SessionCalendarRecord(
            trading_date=trading_date,
            classification=classification,
            observed_candles=observed,
            description="; ".join(descriptions) if descriptions else None,
            source_ids=source_ids,
            issue_codes=tuple(issues),
        )

    @staticmethod
    def _annual_summary(
        year: int,
        records: tuple[SessionCalendarRecord, ...],
        *,
        covered: bool,
        holiday_map: dict[date, tuple[OfficialHoliday, ...]],
        special_map: dict[date, tuple[OfficialSpecialSession, ...]],
    ) -> AnnualSessionSummary:
        yearly = tuple(record for record in records if record.trading_date.year == year)
        weekday_candidates = sum(
            record.trading_date.weekday() < 5 for record in yearly
        )
        weekday_holidays = sum(
            day.year == year and day.weekday() < 5 for day in holiday_map
        )
        special_dates = tuple(day for day in special_map if day.year == year)
        expected = weekday_candidates - weekday_holidays + sum(
            day.weekday() >= 5 or day in holiday_map for day in special_dates
        )
        return AnnualSessionSummary(
            year=year,
            official_source_covered=covered,
            weekday_candidates=weekday_candidates,
            official_weekday_holidays=weekday_holidays,
            official_special_sessions=len(special_dates),
            expected_sessions=expected,
            observed_sessions=sum(record.observed_candles for record in yearly),
            unresolved_weekdays=sum(
                record.classification is SessionClassification.UNRESOLVED_WEEKDAY
                for record in yearly
            ),
            unconfirmed_special_sessions=sum(
                "UNCONFIRMED_SPECIAL_SESSION" in record.issue_codes
                for record in yearly
            ),
            missing_special_sessions=sum(
                "MISSING_OFFICIAL_SPECIAL_SESSION" in record.issue_codes
                for record in yearly
            ),
            conflicts=sum(
                "HOLIDAY_HAS_OBSERVED_CANDLES" in record.issue_codes
                for record in yearly
            ),
        )

    @staticmethod
    def _holiday_map(
        sources: tuple[OfficialCalendarSource, ...],
        start_date: date,
        end_date: date,
    ) -> dict[date, tuple[OfficialHoliday, ...]]:
        grouped: dict[date, list[OfficialHoliday]] = {}
        for source in sources:
            for item in source.holidays:
                if start_date <= item.trading_date <= end_date:
                    grouped.setdefault(item.trading_date, []).append(item)
        return {
            day: tuple(sorted(items, key=lambda item: item.source_id))
            for day, items in grouped.items()
        }

    @staticmethod
    def _special_map(
        sources: tuple[OfficialCalendarSource, ...],
        start_date: date,
        end_date: date,
    ) -> dict[date, tuple[OfficialSpecialSession, ...]]:
        grouped: dict[date, list[OfficialSpecialSession]] = {}
        for source in sources:
            for item in source.special_sessions:
                if start_date <= item.trading_date <= end_date:
                    grouped.setdefault(item.trading_date, []).append(item)
        return {
            day: tuple(sorted(items, key=lambda item: item.source_id))
            for day, items in grouped.items()
        }

    @classmethod
    def _holiday(cls, item: dict[str, Any], source_id: str) -> OfficialHoliday:
        return OfficialHoliday(
            trading_date=cls._item_date(item),
            description=str(item.get("description") or "official NSE holiday"),
            source_id=source_id,
        )

    @classmethod
    def _special_session(
        cls,
        item: dict[str, Any],
        source_id: str,
    ) -> OfficialSpecialSession:
        return OfficialSpecialSession(
            trading_date=cls._item_date(item),
            description=str(
                item.get("description") or "official NSE special trading session"
            ),
            source_id=source_id,
        )

    @classmethod
    def _item_date(cls, item: dict[str, Any]) -> date:
        value = item.get("tradingDate", item.get("trading_date", item.get("date")))
        if value is None:
            raise ValueError("official calendar record is missing a trading date")
        return cls._parse_date(str(value))

    @staticmethod
    def _parse_date(value: str) -> date:
        for format_ in ("%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                from datetime import datetime

                return datetime.strptime(value, format_).date()
            except ValueError:
                pass
        return date.fromisoformat(value)

    @staticmethod
    def _date_range(start_date: date, end_date: date) -> tuple[date, ...]:
        return tuple(
            start_date + timedelta(days=offset)
            for offset in range((end_date - start_date).days + 1)
        )

    @staticmethod
    def _report_payload(
        report: SessionCalendarReport,
        *,
        include_hash: bool,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "contract_version": report.contract_version,
            "start_date": report.start_date.isoformat(),
            "end_date": report.end_date.isoformat(),
            "exchange": report.exchange,
            "certification_state": report.certification_state.value,
            "official_holiday_count": report.official_holiday_count,
            "official_special_session_count": report.official_special_session_count,
            "expected_session_count": report.expected_session_count,
            "observed_session_count": report.observed_session_count,
            "unresolved_weekday_count": report.unresolved_weekday_count,
            "unconfirmed_special_session_count": (
                report.unconfirmed_special_session_count
            ),
            "missing_special_session_count": report.missing_special_session_count,
            "conflict_count": report.conflict_count,
            "sources": [
                {
                    "source_id": source.source_id,
                    "source_path": source.source_path,
                    "source_url": source.source_url,
                    "source_sha256": source.source_sha256,
                    "covered_years": list(source.covered_years),
                    "holiday_count": len(source.holidays),
                    "special_session_count": len(source.special_sessions),
                }
                for source in report.sources
            ],
            "annual_summaries": [asdict(item) for item in report.annual_summaries],
            "records": [
                {
                    "trading_date": record.trading_date.isoformat(),
                    "classification": record.classification.value,
                    "observed_candles": record.observed_candles,
                    "description": record.description,
                    "source_ids": list(record.source_ids),
                    "issue_codes": list(record.issue_codes),
                }
                for record in report.records
            ],
        }
        if include_hash:
            payload["report_sha256"] = report.report_sha256
        return payload

    @staticmethod
    def _markdown(report: SessionCalendarReport) -> str:
        lines = [
            "# HTR-007 Official Session Calendar Reconciliation",
            "",
            f"Certification state: `{report.certification_state.value}`",
            f"Window: `{report.start_date}` to `{report.end_date}`",
            f"Observed sessions: {report.observed_session_count}",
            f"Expected sessions: {report.expected_session_count}",
            f"Official holidays: {report.official_holiday_count}",
            f"Official special sessions: {report.official_special_session_count}",
            f"Unresolved weekdays: {report.unresolved_weekday_count}",
            (
                "Unconfirmed observed special sessions: "
                f"{report.unconfirmed_special_session_count}"
            ),
            f"Missing official special sessions: {report.missing_special_session_count}",
            f"Conflicts: {report.conflict_count}",
            f"Report SHA-256: `{report.report_sha256}`",
            "",
            "| Year | Official source | Expected | Observed | Unresolved | "
            "Unconfirmed special | Missing special | Conflicts |",
            "|---:|:---:|---:|---:|---:|---:|---:|---:|",
        ]
        for item in report.annual_summaries:
            lines.append(
                f"| {item.year} | {item.official_source_covered} | "
                f"{item.expected_sessions} | {item.observed_sessions} | "
                f"{item.unresolved_weekdays} | "
                f"{item.unconfirmed_special_sessions} | "
                f"{item.missing_special_sessions} | {item.conflicts} |"
            )
        lines.append("")
        lines.append(
            "A missing bhavcopy is never classified as a holiday without official evidence."
        )
        return "\n".join(lines) + "\n"
