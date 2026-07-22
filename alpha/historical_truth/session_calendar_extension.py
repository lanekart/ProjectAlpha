"""HTR-007C governed NSE session-calendar extension."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.session_calendar import (
    OfficialCalendarSource,
    OfficialSessionCalendarEngine,
    SessionCalendarReport,
)

HTR007C_CONTRACT_VERSION = "HTR-007C-v1.0.0"


@dataclass(frozen=True, slots=True)
class SessionCalendarExtensionAudit:
    contract_version: str
    existing_calendar_report: str
    existing_calendar_report_sha256: str
    existing_window_start: date
    existing_window_end: date
    extended_window_end: date
    appended_years: tuple[int, ...]
    appended_source_path: str
    appended_source_sha256: str
    historical_record_count: int
    historical_parity_mismatch_count: int
    historical_parity_mismatches: tuple[str, ...]
    historical_parity_state: str
    existing_source_count: int
    extended_source_count: int
    extended_certification_state: str
    expected_session_count: int
    observed_session_count: int
    unresolved_weekday_count: int
    unconfirmed_special_session_count: int
    missing_special_session_count: int
    conflict_count: int
    production_influence: bool


class GovernedSessionCalendarExtensionEngine:
    """Append official calendar evidence without rewriting historical truth."""

    def extend(
        self,
        *,
        existing_calendar_report: Path,
        database_path: Path,
        source_dir: Path,
        through_date: date,
        current_source_path: Path | None = None,
        refresh: bool = True,
        timeout_seconds: float = 30.0,
    ) -> tuple[SessionCalendarReport, SessionCalendarExtensionAudit]:
        payload = _verified_report_payload(existing_calendar_report)
        existing_start = _required_date(payload, "start_date")
        existing_end = _required_date(payload, "end_date")
        if through_date <= existing_end:
            raise ValueError(
                "through_date must be after the existing governed calendar end"
            )

        existing_sources = _verified_existing_sources(payload)
        target_years = tuple(range(existing_end.year + 1, through_date.year + 1))
        if not target_years:
            target_years = (through_date.year,)

        source_path = current_source_path
        if source_path is None:
            if not refresh:
                raise ValueError(
                    "current_source_path is required when source refresh is disabled"
                )
            source_path = OfficialSessionCalendarEngine.fetch_current_official_source(
                source_dir,
                timeout_seconds=timeout_seconds,
            )

        loaded_source = OfficialSessionCalendarEngine.load_source(source_path)
        scoped_source = _scope_source(loaded_source, target_years)
        if set(target_years) - set(scoped_source.covered_years):
            missing = sorted(set(target_years) - set(scoped_source.covered_years))
            raise ValueError(
                "official calendar source does not cover required years: "
                + ", ".join(str(year) for year in missing)
            )

        source_ids = {item.source_id for item in existing_sources}
        extended_sources = existing_sources
        if scoped_source.source_id not in source_ids:
            extended_sources = (*existing_sources, scoped_source)

        canonical = CanonicalPointInTimeWarehouse(database_path)
        engine = OfficialSessionCalendarEngine(canonical)
        extended = engine.reconcile(
            existing_start,
            through_date,
            extended_sources,
        )
        parity_mismatches = _historical_parity_mismatches(
            payload,
            extended,
            existing_end,
        )
        audit = SessionCalendarExtensionAudit(
            contract_version=HTR007C_CONTRACT_VERSION,
            existing_calendar_report=str(existing_calendar_report),
            existing_calendar_report_sha256=str(payload["report_sha256"]),
            existing_window_start=existing_start,
            existing_window_end=existing_end,
            extended_window_end=through_date,
            appended_years=target_years,
            appended_source_path=str(source_path),
            appended_source_sha256=scoped_source.source_sha256,
            historical_record_count=sum(
                record.trading_date <= existing_end for record in extended.records
            ),
            historical_parity_mismatch_count=len(parity_mismatches),
            historical_parity_mismatches=parity_mismatches,
            historical_parity_state=(
                "HISTORICAL_CALENDAR_PARITY_PRESERVED"
                if not parity_mismatches
                else "HISTORICAL_CALENDAR_PARITY_VIOLATED"
            ),
            existing_source_count=len(existing_sources),
            extended_source_count=len(extended.sources),
            extended_certification_state=extended.certification_state.value,
            expected_session_count=extended.expected_session_count,
            observed_session_count=extended.observed_session_count,
            unresolved_weekday_count=extended.unresolved_weekday_count,
            unconfirmed_special_session_count=(
                extended.unconfirmed_special_session_count
            ),
            missing_special_session_count=extended.missing_special_session_count,
            conflict_count=extended.conflict_count,
            production_influence=False,
        )
        return extended, audit

    @staticmethod
    def export(
        report: SessionCalendarReport,
        audit: SessionCalendarExtensionAudit,
        output: Path,
        *,
        database_path: Path,
    ) -> tuple[Path, ...]:
        canonical = CanonicalPointInTimeWarehouse(database_path)
        engine = OfficialSessionCalendarEngine(canonical)
        paths = list(engine.export(report, output))
        audit_payload = _jsonable(asdict(audit))
        json_path = output / "htr007c_session_calendar_extension.json"
        markdown_path = output / "htr007c_session_calendar_extension.md"
        json_path.write_text(
            json.dumps(audit_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        markdown_path.write_text(_audit_markdown(audit), encoding="utf-8")
        paths.extend((json_path, markdown_path))
        return tuple(paths)


def _verified_report_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"existing governed calendar report is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("existing governed calendar report must be an object")
    expected = payload.get("report_sha256")
    if not isinstance(expected, str) or not expected:
        raise ValueError("existing governed calendar report has no checksum")
    without_hash = dict(payload)
    without_hash.pop("report_sha256", None)
    observed = hashlib.sha256(
        json.dumps(
            without_hash,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if observed != expected:
        raise ValueError("existing governed calendar report checksum mismatch")
    return payload


def _verified_existing_sources(
    payload: dict[str, Any],
) -> tuple[OfficialCalendarSource, ...]:
    registry = payload.get("sources")
    if not isinstance(registry, list) or not registry:
        raise ValueError("existing governed calendar source registry is empty")
    sources: list[OfficialCalendarSource] = []
    for row in registry:
        if not isinstance(row, dict):
            raise ValueError("existing governed calendar source registry is malformed")
        source_path = Path(str(row.get("source_path") or ""))
        if not source_path.exists():
            raise ValueError(f"governed calendar source is missing: {source_path}")
        expected = str(row.get("source_sha256") or "")
        observed = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if expected != observed:
            raise ValueError(
                f"governed calendar source checksum mismatch: {source_path}"
            )
        sources.append(OfficialSessionCalendarEngine.load_source(source_path))
    return tuple(sorted(sources, key=lambda item: item.source_id))


def _scope_source(
    source: OfficialCalendarSource,
    target_years: tuple[int, ...],
) -> OfficialCalendarSource:
    year_set = set(target_years)
    holidays = tuple(
        item for item in source.holidays if item.trading_date.year in year_set
    )
    specials = tuple(
        item for item in source.special_sessions if item.trading_date.year in year_set
    )
    covered = tuple(year for year in source.covered_years if year in year_set)
    return OfficialCalendarSource(
        source_id=source.source_id,
        source_path=source.source_path,
        source_url=source.source_url,
        source_sha256=source.source_sha256,
        covered_years=covered,
        holidays=holidays,
        special_sessions=specials,
    )


def _historical_parity_mismatches(
    existing_payload: dict[str, Any],
    extended: SessionCalendarReport,
    existing_end: date,
) -> tuple[str, ...]:
    existing_records = existing_payload.get("records")
    if not isinstance(existing_records, list):
        raise ValueError("existing governed calendar records are missing")
    old = {
        str(row.get("trading_date")): _record_signature_from_payload(row)
        for row in existing_records
        if isinstance(row, dict)
        and (_as_date(row.get("trading_date")) or date.max) <= existing_end
    }
    new = {
        record.trading_date.isoformat(): (
            record.classification.value,
            record.observed_candles,
            record.description,
            tuple(record.issue_codes),
        )
        for record in extended.records
        if record.trading_date <= existing_end
    }
    keys = sorted(set(old) | set(new))
    return tuple(key for key in keys if old.get(key) != new.get(key))


def _record_signature_from_payload(row: dict[str, Any]) -> tuple[Any, ...]:
    issue_codes = row.get("issue_codes")
    return (
        str(row.get("classification") or ""),
        bool(row.get("observed_candles")),
        row.get("description"),
        tuple(issue_codes) if isinstance(issue_codes, list) else (),
    )


def _required_date(payload: dict[str, Any], key: str) -> date:
    value = _as_date(payload.get(key))
    if value is None:
        raise ValueError(f"existing governed calendar report has invalid {key}")
    return value


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


def _audit_markdown(audit: SessionCalendarExtensionAudit) -> str:
    return "\n".join(
        (
            "# HTR-007C Governed Session Calendar Extension",
            "",
            (
                f"- Existing window: {audit.existing_window_start} "
                f"to {audit.existing_window_end}"
            ),
            f"- Extended window end: {audit.extended_window_end}",
            f"- Appended years: {list(audit.appended_years)}",
            f"- Historical parity: {audit.historical_parity_state}",
            f"- Historical mismatches: {audit.historical_parity_mismatch_count}",
            f"- Certification state: {audit.extended_certification_state}",
            f"- Expected sessions: {audit.expected_session_count}",
            f"- Observed sessions: {audit.observed_session_count}",
            f"- Unresolved weekdays: {audit.unresolved_weekday_count}",
            (
                "- Unconfirmed special sessions: "
                f"{audit.unconfirmed_special_session_count}"
            ),
            f"- Missing special sessions: {audit.missing_special_session_count}",
            f"- Conflicts: {audit.conflict_count}",
            "- Production influence: false",
            "",
            (
                "Existing governed sources remain immutable; "
                "the new source is appended and year-scoped."
            ),
            "",
        )
    )


__all__ = [
    "GovernedSessionCalendarExtensionEngine",
    "HTR007C_CONTRACT_VERSION",
    "SessionCalendarExtensionAudit",
]
