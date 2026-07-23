"""Schema-tolerant NSE corporate-action evidence matching for HTR-010B1F."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

HTR010B1F_ACTION_EVIDENCE_CONTRACT_VERSION = (
    "HTR-010B1F-ACTION-EVIDENCE-v1.0.0"
)

_ACTION_TERMS = (
    "stock split",
    "face value split",
    "sub-division",
    "subdivision",
    "split",
    "bonus",
    "consolidation",
    "change in face value",
    "series",
)
_SYMBOL_KEYS = ("symbol", "sm_symbol", "securitysymbol")
_DATE_KEYS = (
    "exdate",
    "ex_date",
    "recorddate",
    "record_date",
    "bcstartdate",
    "effective_date",
    "effectiveDate",
)
_PURPOSE_KEYS = ("purpose", "subject", "description", "remarks", "action")


@dataclass(frozen=True)
class CorporateActionMatch:
    proved: bool
    state: str
    candidate_row_count: int
    symbol_match_count: int
    date_match_count: int
    action_term_match_count: int
    matched_row_count: int
    matched_rows: tuple[dict[str, Any], ...]
    schema_keys: tuple[str, ...]
    payload_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "proved": self.proved,
            "state": self.state,
            "candidate_row_count": self.candidate_row_count,
            "symbol_match_count": self.symbol_match_count,
            "date_match_count": self.date_match_count,
            "action_term_match_count": self.action_term_match_count,
            "matched_row_count": self.matched_row_count,
            "matched_rows": list(self.matched_rows),
            "schema_keys": list(self.schema_keys),
            "payload_sha256": self.payload_sha256,
        }


def match_corporate_action_payload(
    *,
    payload: bytes,
    symbol: str,
    effective_date: str,
) -> CorporateActionMatch:
    """Match one official NSE API payload to a governed bridge action."""

    digest = sha256(payload).hexdigest()
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return CorporateActionMatch(
            proved=False,
            state="ACTION_PAYLOAD_NOT_VALID_JSON",
            candidate_row_count=0,
            symbol_match_count=0,
            date_match_count=0,
            action_term_match_count=0,
            matched_row_count=0,
            matched_rows=(),
            schema_keys=(),
            payload_sha256=digest,
        )

    rows = tuple(_extract_rows(decoded))
    if not rows:
        return CorporateActionMatch(
            proved=False,
            state="ACTION_API_RETURNED_NO_ROWS",
            candidate_row_count=0,
            symbol_match_count=0,
            date_match_count=0,
            action_term_match_count=0,
            matched_row_count=0,
            matched_rows=(),
            schema_keys=(),
            payload_sha256=digest,
        )

    target_symbol = symbol.strip().upper()
    target_date = _parse_date(effective_date)
    schema_keys = tuple(sorted({str(key) for row in rows for key in row}))

    symbol_rows = tuple(row for row in rows if _row_symbol(row) == target_symbol)
    date_rows = tuple(
        row for row in symbol_rows if target_date is not None and target_date in _row_dates(row)
    )
    action_rows = tuple(row for row in date_rows if _row_has_action_term(row))

    if len(action_rows) == 1:
        state = "ACTION_ROW_VERIFIED"
    elif len(action_rows) > 1:
        state = "ACTION_ROWS_CONFLICTING_OR_DUPLICATE"
    elif not symbol_rows:
        state = "ACTION_SYMBOL_NOT_FOUND"
    elif not date_rows:
        state = "ACTION_EFFECTIVE_DATE_NOT_FOUND"
    else:
        state = "ACTION_PURPOSE_NOT_SUPPORTED"

    return CorporateActionMatch(
        proved=len(action_rows) == 1,
        state=state,
        candidate_row_count=len(rows),
        symbol_match_count=len(symbol_rows),
        date_match_count=len(date_rows),
        action_term_match_count=len(action_rows),
        matched_row_count=len(action_rows),
        matched_rows=tuple(_stable_row(row) for row in action_rows[:5]),
        schema_keys=schema_keys,
        payload_sha256=digest,
    )


def match_corporate_action_file(
    *,
    path: Path,
    symbol: str,
    effective_date: str,
) -> CorporateActionMatch:
    return match_corporate_action_payload(
        payload=path.read_bytes(),
        symbol=symbol,
        effective_date=effective_date,
    )


def _extract_rows(value: object) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                rows.append(item)
            else:
                rows.extend(_extract_rows(item))
        return rows
    if isinstance(value, dict):
        if _looks_like_action_row(value):
            rows.append(value)
        for child in value.values():
            if isinstance(child, (dict, list)):
                rows.extend(_extract_rows(child))
    return rows


def _looks_like_action_row(row: dict[str, Any]) -> bool:
    lowered = {str(key).lower() for key in row}
    return bool(
        lowered.intersection(key.lower() for key in _SYMBOL_KEYS)
        and lowered.intersection(key.lower() for key in _DATE_KEYS)
    )


def _row_symbol(row: dict[str, Any]) -> str:
    for key, value in row.items():
        if str(key).lower() in {candidate.lower() for candidate in _SYMBOL_KEYS}:
            return str(value or "").strip().upper()
    return ""


def _row_dates(row: dict[str, Any]) -> set[date]:
    parsed: set[date] = set()
    accepted = {candidate.lower() for candidate in _DATE_KEYS}
    for key, value in row.items():
        if str(key).lower() not in accepted:
            continue
        resolved = _parse_date(value)
        if resolved is not None:
            parsed.add(resolved)
    return parsed


def _row_has_action_term(row: dict[str, Any]) -> bool:
    accepted = {candidate.lower() for candidate in _PURPOSE_KEYS}
    values = [
        str(value or "").lower()
        for key, value in row.items()
        if str(key).lower() in accepted
    ]
    if not values:
        values = [json.dumps(row, sort_keys=True, default=str).lower()]
    return any(term in text for text in values for term in _ACTION_TERMS)


def _parse_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in (
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d-%b-%Y",
        "%d %b %Y",
        "%d-%B-%Y",
        "%d %B %Y",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _stable_row(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): row[key] for key in sorted(row, key=str)}


__all__ = [
    "CorporateActionMatch",
    "HTR010B1F_ACTION_EVIDENCE_CONTRACT_VERSION",
    "match_corporate_action_file",
    "match_corporate_action_payload",
]
