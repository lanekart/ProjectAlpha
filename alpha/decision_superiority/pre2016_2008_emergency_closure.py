"""Governed composite evidence for the 27-Nov-2008 NSE emergency closure."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol

import duckdb
import requests

from .pre2016_calendar_sources import (
    build_reviewed_official_calendar_source,
    validate_hash_bound_official_calendar_source,
)
from .pre2016_external_validation_models import Pre2016ExternalValidationError

EMERGENCY_DATE = date(2008, 11, 27)
SOURCE_ID = "NSE_COMPOSITE_11688_11689_2008_EMERGENCY_CLOSURE"
CAPITAL_MARKET_URL = "https://nsearchives.nseindia.com/content/circulars/cmpt11689.htm"
FUTURES_OPTIONS_URL = "https://nsearchives.nseindia.com/content/circulars/faop11688.htm"
CIRCULAR_API_URL = (
    "https://www.nseindia.com/api/circulars?fromDate=25-11-2008&toDate=30-11-2008"
)
CAPITAL_MARKET_EXPECTED_SHA256 = (
    "adde2a6b3ced2c03e28c2239d12f72cfa250f8733ea5b60746712a6082d3a0d9"
)
FUTURES_OPTIONS_EXPECTED_SHA256 = (
    "7285988018a0324efd2af3ba29273db2cf59cf83e87405fd73eb241e8015774b"
)
_EVIDENCE_RULE = "CROSS_SEGMENT_EVIDENCE_REQUIRES_CM_API_AND_CM_CANDLES"
_BUNDLE_MEMBERS = (
    "api_evidence.json",
    "capital_market_clearing.html",
    "capital_market_clearing.txt",
    "evidence_rule.json",
    "futures_options_holiday.html",
    "futures_options_holiday.txt",
)


class _HttpResponse(Protocol):
    status_code: int
    content: bytes
    headers: Mapping[str, str]
    url: str


class _HttpSession(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> _HttpResponse: ...


class _RequestsResponseAdapter:
    def __init__(self, response: requests.Response) -> None:
        self.status_code = response.status_code
        self.content = response.content
        self.headers: Mapping[str, str] = dict(response.headers)
        self.url = response.url


class _RequestsSessionAdapter:
    def __init__(self) -> None:
        self._session = requests.Session()

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> _HttpResponse:
        return _RequestsResponseAdapter(
            self._session.get(url, headers=headers, timeout=timeout)
        )


class _VisibleHtmlTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._suppressed_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag.casefold() in {"script", "style"}:
            self._suppressed_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style"} and self._suppressed_depth:
            self._suppressed_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._suppressed_depth:
            return
        normalized = re.sub(r"\s+", " ", data).strip()
        if normalized:
            self.parts.append(normalized)


@dataclass(frozen=True, slots=True)
class EmergencyClosureBuildResult:
    source_path: Path
    evidence_bundle: Path
    review_csv: Path
    validation_path: Path
    capital_market_document_sha256: str
    futures_options_document_sha256: str
    api_evidence_sha256: str
    capital_market_candle_count: int
    production_influence: bool = False


def build_2008_emergency_closure_source(
    *,
    database: Path,
    output_root: Path,
    session: _HttpSession | None = None,
    timeout_seconds: float = 45.0,
) -> EmergencyClosureBuildResult:
    """Build one hash-bound Capital Market holiday from a governed evidence chain."""

    if not database.is_file():
        raise Pre2016ExternalValidationError("DSI010_2008_EMERGENCY_DATABASE_MISSING")
    output_root.mkdir(parents=True, exist_ok=True)
    client: _HttpSession = session or _RequestsSessionAdapter()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/resources/exchange-communication-circulars",
    }
    warmup = client.get("https://www.nseindia.com/", headers=headers, timeout=30.0)
    if warmup.status_code >= 500:
        raise Pre2016ExternalValidationError("DSI010_2008_EMERGENCY_NSE_WARMUP_FAILED")

    cm_response = client.get(
        CAPITAL_MARKET_URL,
        headers={**headers, "Accept": "text/html,*/*"},
        timeout=timeout_seconds,
    )
    fo_response = client.get(
        FUTURES_OPTIONS_URL,
        headers={**headers, "Accept": "text/html,*/*"},
        timeout=timeout_seconds,
    )
    api_response = client.get(
        CIRCULAR_API_URL,
        headers={**headers, "Accept": "application/json,text/plain,*/*"},
        timeout=timeout_seconds,
    )
    _require_success(cm_response, "CAPITAL_MARKET_DOCUMENT")
    _require_success(fo_response, "FUTURES_OPTIONS_DOCUMENT")
    _require_success(api_response, "CIRCULAR_API")

    cm_hash = _sha256_bytes(cm_response.content)
    fo_hash = _sha256_bytes(fo_response.content)
    if cm_hash != CAPITAL_MARKET_EXPECTED_SHA256:
        raise Pre2016ExternalValidationError(
            "DSI010_2008_EMERGENCY_CM_DOCUMENT_HASH_MISMATCH"
        )
    if fo_hash != FUTURES_OPTIONS_EXPECTED_SHA256:
        raise Pre2016ExternalValidationError(
            "DSI010_2008_EMERGENCY_FO_DOCUMENT_HASH_MISMATCH"
        )

    cm_text = _extract_html_text(cm_response.content)
    fo_text = _extract_html_text(fo_response.content)
    _validate_capital_market_text(cm_text)
    _validate_futures_options_text(fo_text)
    api_evidence = _validated_api_evidence(api_response.content)
    candle_count = _capital_market_candle_count(database)
    if candle_count != 0:
        raise Pre2016ExternalValidationError("DSI010_2008_EMERGENCY_CM_CANDLES_PRESENT")

    cm_document = output_root / "cmpt11689.html"
    fo_document = output_root / "faop11688.html"
    cm_text_path = output_root / "cmpt11689_extracted_text.txt"
    fo_text_path = output_root / "faop11688_extracted_text.txt"
    api_path = output_root / "nse_api_evidence.json"
    cm_document.write_bytes(cm_response.content)
    fo_document.write_bytes(fo_response.content)
    cm_text_path.write_text(cm_text.rstrip() + "\n", encoding="utf-8")
    fo_text_path.write_text(fo_text.rstrip() + "\n", encoding="utf-8")
    api_path.write_text(
        json.dumps(api_evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    evidence_rule = {
        "evidence_rule": _EVIDENCE_RULE,
        "classification_origin": "OFFICIAL_DOCUMENTS_AND_CM_API",
        "capital_market_api_scope_verified": True,
        "capital_market_settlement_calendar_verified": True,
        "futures_options_trading_holiday_verified": True,
        "capital_market_candle_absence_checked": True,
        "capital_market_candle_absence_used_as_corroboration_only": True,
        "classification_inferred_from_archive_status": False,
        "classification_inferred_from_observed_candles": False,
        "production_influence": False,
        "trading_date": EMERGENCY_DATE.isoformat(),
    }
    evidence_rule_path = output_root / "evidence_rule.json"
    evidence_rule_path.write_text(
        json.dumps(evidence_rule, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    bundle_path = output_root / "nse_2008_emergency_closure_evidence.zip"
    _write_deterministic_bundle(
        bundle_path,
        {
            "api_evidence.json": api_path.read_bytes(),
            "capital_market_clearing.html": cm_document.read_bytes(),
            "capital_market_clearing.txt": cm_text_path.read_bytes(),
            "evidence_rule.json": evidence_rule_path.read_bytes(),
            "futures_options_holiday.html": fo_document.read_bytes(),
            "futures_options_holiday.txt": fo_text_path.read_bytes(),
        },
    )

    review_csv = output_root / "reviewed_emergency_holiday.csv"
    with review_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "trading_date",
                "classification",
                "description",
                "review_state",
                "segment_scope",
                "source_id",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "trading_date": EMERGENCY_DATE.isoformat(),
                "classification": "HOLIDAY",
                "description": (
                    "Emergency trading holiday - Mumbai attacks; "
                    "CM clearing calendar and F&O holiday corroboration"
                ),
                "review_state": "VERIFIED_OFFICIAL_EVIDENCE",
                "segment_scope": "CAPITAL_MARKET",
                "source_id": SOURCE_ID,
            }
        )

    combined_text = output_root / "combined_extracted_text.txt"
    combined_text.write_text(
        "===== CAPITAL MARKET CLEARING EVIDENCE =====\n"
        + cm_text.rstrip()
        + "\n\n===== FUTURES AND OPTIONS HOLIDAY EVIDENCE =====\n"
        + fo_text.rstrip()
        + "\n",
        encoding="utf-8",
    )
    validation_path = output_root / "content_validation.json"
    validation_payload = {
        **evidence_rule,
        "source_id": SOURCE_ID,
        "capital_market_document_url": CAPITAL_MARKET_URL,
        "capital_market_document_sha256": cm_hash,
        "capital_market_expected_sha256": CAPITAL_MARKET_EXPECTED_SHA256,
        "futures_options_document_url": FUTURES_OPTIONS_URL,
        "futures_options_document_sha256": fo_hash,
        "futures_options_expected_sha256": FUTURES_OPTIONS_EXPECTED_SHA256,
        "api_url": CIRCULAR_API_URL,
        "api_evidence_sha256": _sha256(api_path),
        "capital_market_candle_count": candle_count,
        "cross_segment_evidence_rule_satisfied": True,
        "content_validation_passed": True,
        "manual_review_completed": True,
    }
    validation_path.write_text(
        json.dumps(validation_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    source_path = output_root / "nse_2008_emergency_closure.json"
    build_reviewed_official_calendar_source(
        review_csv=review_csv,
        source_document=bundle_path,
        source_url=CAPITAL_MARKET_URL,
        source_id=SOURCE_ID,
        covered_years=(2008,),
        output=source_path,
        segment_scope="CAPITAL_MARKET",
        extracted_text=combined_text,
        content_validation=validation_path,
    )
    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    source_payload.update(
        {
            "evidence_rule": _EVIDENCE_RULE,
            "cross_segment_evidence_rule_satisfied": True,
            "capital_market_api_scope_verified": True,
            "capital_market_settlement_calendar_verified": True,
            "futures_options_trading_holiday_verified": True,
            "capital_market_candle_absence_checked": True,
            "capital_market_candle_absence_used_as_corroboration_only": True,
            "composite_bundle_members": list(_BUNDLE_MEMBERS),
        }
    )
    source_path.write_text(
        json.dumps(source_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    validate_2008_emergency_closure_source(source_path, database=database)
    return EmergencyClosureBuildResult(
        source_path=source_path,
        evidence_bundle=bundle_path,
        review_csv=review_csv,
        validation_path=validation_path,
        capital_market_document_sha256=cm_hash,
        futures_options_document_sha256=fo_hash,
        api_evidence_sha256=_sha256(api_path),
        capital_market_candle_count=candle_count,
    )


def validate_2008_emergency_closure_source(
    source_path: Path,
    *,
    database: Path | None = None,
) -> dict[str, object]:
    """Validate the composite bundle and the non-inference boundary."""

    payload = validate_hash_bound_official_calendar_source(
        source_path,
        require_capital_market_scope=True,
    )
    if payload.get("source_id") != SOURCE_ID:
        raise Pre2016ExternalValidationError("DSI010_2008_EMERGENCY_SOURCE_ID_INVALID")
    if payload.get("evidence_rule") != _EVIDENCE_RULE:
        raise Pre2016ExternalValidationError(
            "DSI010_2008_EMERGENCY_EVIDENCE_RULE_INVALID"
        )
    required_true = (
        "cross_segment_evidence_rule_satisfied",
        "capital_market_api_scope_verified",
        "capital_market_settlement_calendar_verified",
        "futures_options_trading_holiday_verified",
        "capital_market_candle_absence_checked",
        "capital_market_candle_absence_used_as_corroboration_only",
    )
    if any(payload.get(key) is not True for key in required_true):
        raise Pre2016ExternalValidationError(
            "DSI010_2008_EMERGENCY_GOVERNANCE_FLAG_INVALID"
        )
    holidays = payload.get("holidays")
    if not isinstance(holidays, list) or holidays != [
        {
            "description": (
                "Emergency trading holiday - Mumbai attacks; "
                "CM clearing calendar and F&O holiday corroboration"
            ),
            "trading_date": EMERGENCY_DATE.isoformat(),
        }
    ]:
        raise Pre2016ExternalValidationError(
            "DSI010_2008_EMERGENCY_HOLIDAY_ROW_INVALID"
        )

    bundle_path = Path(str(payload.get("source_document_path") or ""))
    with zipfile.ZipFile(bundle_path) as bundle:
        if tuple(sorted(bundle.namelist())) != _BUNDLE_MEMBERS:
            raise Pre2016ExternalValidationError(
                "DSI010_2008_EMERGENCY_BUNDLE_MEMBERS_INVALID"
            )
        cm_raw = bundle.read("capital_market_clearing.html")
        fo_raw = bundle.read("futures_options_holiday.html")
        if _sha256_bytes(cm_raw) != CAPITAL_MARKET_EXPECTED_SHA256:
            raise Pre2016ExternalValidationError(
                "DSI010_2008_EMERGENCY_BUNDLE_CM_HASH_MISMATCH"
            )
        if _sha256_bytes(fo_raw) != FUTURES_OPTIONS_EXPECTED_SHA256:
            raise Pre2016ExternalValidationError(
                "DSI010_2008_EMERGENCY_BUNDLE_FO_HASH_MISMATCH"
            )
        _validate_capital_market_text(
            bundle.read("capital_market_clearing.txt").decode("utf-8")
        )
        _validate_futures_options_text(
            bundle.read("futures_options_holiday.txt").decode("utf-8")
        )
        _validate_normalized_api_evidence(json.loads(bundle.read("api_evidence.json")))
        rule = json.loads(bundle.read("evidence_rule.json"))
        if rule.get("evidence_rule") != _EVIDENCE_RULE:
            raise Pre2016ExternalValidationError(
                "DSI010_2008_EMERGENCY_BUNDLE_RULE_INVALID"
            )
    if database is not None and _capital_market_candle_count(database) != 0:
        raise Pre2016ExternalValidationError("DSI010_2008_EMERGENCY_CM_CANDLES_PRESENT")
    return payload


def _require_success(response: _HttpResponse, label: str) -> None:
    if response.status_code != 200 or not response.content:
        raise Pre2016ExternalValidationError(
            f"DSI010_2008_EMERGENCY_{label}_FETCH_FAILED"
        )


def _extract_html_text(raw: bytes) -> str:
    parser = _VisibleHtmlTextParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    rendered = "\n".join(parser.parts)
    if not rendered:
        raise Pre2016ExternalValidationError("DSI010_2008_EMERGENCY_HTML_TEXT_EMPTY")
    return rendered


def _validate_capital_market_text(text: str) -> None:
    normalized = re.sub(r"\s+", " ", text).casefold()
    required = (
        "national securities clearing corporation limited",
        "nse/cmpt/11689",
        "november 27, 2008",
        "change in settlement schedule on account of postponement of settlement",
        "settlement calendar normal segment",
    )
    if any(token not in normalized for token in required):
        raise Pre2016ExternalValidationError("DSI010_2008_EMERGENCY_CM_CONTENT_INVALID")
    patterns = (
        r"n\s+2008224\s+26-nov-08\s+26-nov-08\s+28-nov-08\s+01-dec-08",
        r"n\s+2008225\s+28-nov-08\s+28-nov-08\s+01-dec-08\s+02-dec-08",
    )
    if any(re.search(pattern, normalized) is None for pattern in patterns):
        raise Pre2016ExternalValidationError(
            "DSI010_2008_EMERGENCY_CM_TRADE_CALENDAR_INVALID"
        )


def _validate_futures_options_text(text: str) -> None:
    normalized = re.sub(r"\s+", " ", text).casefold()
    required = (
        "national stock exchange of india limited",
        "nse/faop/11688",
        "trading holiday & change of expiry date for derivatives contracts",
        "november 27, 2008 being declared as a trading holiday",
    )
    if any(token not in normalized for token in required):
        raise Pre2016ExternalValidationError("DSI010_2008_EMERGENCY_FO_CONTENT_INVALID")


def _validated_api_evidence(raw: bytes) -> dict[str, object]:
    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Pre2016ExternalValidationError(
            "DSI010_2008_EMERGENCY_API_JSON_INVALID"
        ) from exc
    rows = _rows_from_payload(payload)
    selected = [
        _normalized_api_row(row)
        for row in rows
        if str(row.get("circNumber") or "") in {"11688", "11689"}
    ]
    evidence: dict[str, object] = {
        "api_url": CIRCULAR_API_URL,
        "rows": sorted(selected, key=lambda row: str(row["circNumber"])),
    }
    _validate_normalized_api_evidence(evidence)
    return evidence


def _validate_normalized_api_evidence(payload: object) -> None:
    if not isinstance(payload, dict):
        raise Pre2016ExternalValidationError(
            "DSI010_2008_EMERGENCY_API_EVIDENCE_INVALID"
        )
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise Pre2016ExternalValidationError("DSI010_2008_EMERGENCY_API_ROWS_INVALID")
    by_number = {
        str(row.get("circNumber") or ""): row for row in rows if isinstance(row, dict)
    }
    cm_row = by_number.get("11689")
    fo_row = by_number.get("11688")
    if not isinstance(cm_row, dict) or not isinstance(fo_row, dict):
        raise Pre2016ExternalValidationError(
            "DSI010_2008_EMERGENCY_API_REQUIRED_ROWS_MISSING"
        )
    if (
        cm_row.get("cirDate") != "20081127"
        or cm_row.get("circDepartment") != "NSE Clearing - Capital Market"
        or cm_row.get("circFilelink") != CAPITAL_MARKET_URL
        or "postponement of settlement on november 27, 2008"
        not in str(cm_row.get("sub") or "").casefold()
    ):
        raise Pre2016ExternalValidationError(
            "DSI010_2008_EMERGENCY_API_CM_SCOPE_INVALID"
        )
    if (
        fo_row.get("cirDate") != "20081127"
        or fo_row.get("circDepartment") != "Futures & Options"
        or fo_row.get("circFilelink") != FUTURES_OPTIONS_URL
        or "trading holiday" not in str(fo_row.get("sub") or "").casefold()
    ):
        raise Pre2016ExternalValidationError(
            "DSI010_2008_EMERGENCY_API_FO_SCOPE_INVALID"
        )


def _normalized_api_row(row: Mapping[str, object]) -> dict[str, str]:
    fields = (
        "cirDate",
        "cirDisplayDate",
        "circCategory",
        "circCompany",
        "circDepartment",
        "circDisplayNo",
        "circFilelink",
        "circFilename",
        "circNumber",
        "fileDept",
        "fileExt",
        "sub",
    )
    return {field: str(row.get(field) or "") for field in fields}


def _rows_from_payload(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "Table", "table", "records", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        for value in payload.values():
            if isinstance(value, list) and all(isinstance(row, dict) for row in value):
                return value
    return []


def _capital_market_candle_count(database: Path) -> int:
    with duckdb.connect(str(database), read_only=True) as connection:
        table = connection.execute(
            """
            SELECT count(*)
            FROM information_schema.tables
            WHERE table_schema = 'main' AND table_name = 'daily_candle'
            """
        ).fetchone()
        if table is None or int(table[0]) != 1:
            raise Pre2016ExternalValidationError(
                "DSI010_2008_EMERGENCY_DAILY_CANDLE_TABLE_MISSING"
            )
        result = connection.execute(
            """
            SELECT count(*)
            FROM daily_candle
            WHERE exchange = 'nse' AND trading_date = DATE '2008-11-27'
            """
        ).fetchone()
    if result is None:
        raise Pre2016ExternalValidationError("DSI010_2008_EMERGENCY_CANDLE_QUERY_EMPTY")
    return int(result[0])


def _write_deterministic_bundle(path: Path, members: Mapping[str, bytes]) -> None:
    if tuple(sorted(members)) != _BUNDLE_MEMBERS:
        raise Pre2016ExternalValidationError(
            "DSI010_2008_EMERGENCY_BUNDLE_INPUT_INVALID"
        )
    with zipfile.ZipFile(path, "w") as bundle:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.create_system = 3
            bundle.writestr(info, members[name])


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "CAPITAL_MARKET_EXPECTED_SHA256",
    "CAPITAL_MARKET_URL",
    "CIRCULAR_API_URL",
    "EMERGENCY_DATE",
    "EmergencyClosureBuildResult",
    "FUTURES_OPTIONS_EXPECTED_SHA256",
    "FUTURES_OPTIONS_URL",
    "SOURCE_ID",
    "build_2008_emergency_closure_source",
    "validate_2008_emergency_closure_source",
]
