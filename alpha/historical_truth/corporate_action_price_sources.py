"""Official NSE corporate-action acquisition and normalization for HTR-009B."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlencode, urlparse

import requests

from alpha.historical_truth.corporate_action_price_models import (
    ActionAdmissionState,
    AdjustmentFactorState,
    CorporateActionEvent,
    CorporateActionLineage,
    CorporateActionRejection,
    CorporateActionSourceRecord,
    CorporateActionSourceSpec,
    CorporateActionType,
    EvidenceConfidence,
    FailureCode,
    SourceStatus,
    stable_id,
)

OFFICIAL_NSE_HOSTS = frozenset(
    {"nseindia.com", "www.nseindia.com", "nsearchives.nseindia.com"}
)
SOURCE_HEADERS = {
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-actions",
    "User-Agent": "ProjectAlpha-HistoricalTruth/1.0",
}


class HttpResponse(Protocol):
    status_code: int
    content: bytes
    headers: Mapping[str, str]
    url: str
    history: Sequence[Any]

    def raise_for_status(self) -> None: ...


class HttpSession(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        allow_redirects: bool,
    ) -> HttpResponse: ...


@dataclass(frozen=True, slots=True)
class ParsedCorporateActionSource:
    inventory: CorporateActionSourceRecord
    actions: tuple[CorporateActionEvent, ...]
    lineage: tuple[CorporateActionLineage, ...]
    rejected: tuple[CorporateActionRejection, ...]


def default_corporate_action_sources(
    start_date: date,
    end_date: date,
) -> tuple[CorporateActionSourceSpec, ...]:
    """Return deterministic yearly slices of the official NSE actions API."""

    specs: list[CorporateActionSourceSpec] = []
    for year in range(start_date.year, end_date.year + 1):
        lower = max(start_date, date(year, 1, 1))
        upper = min(end_date, date(year, 12, 31))
        query = urlencode(
            {
                "index": "equities",
                "from_date": lower.strftime("%d-%m-%Y"),
                "to_date": upper.strftime("%d-%m-%Y"),
            }
        )
        specs.append(
            CorporateActionSourceSpec(
                source_id=f"nse_equity_corporate_actions_{year}",
                source_family="NSE_EQUITY_CORPORATE_ACTIONS",
                url=(
                    f"https://www.nseindia.com/api/corporates-corporateActions?{query}"
                ),
                covered_start=lower,
                covered_end=upper,
            )
        )
    return tuple(specs)


class OfficialCorporateActionStore:
    """Retain official response bytes immutably with checksum-backed reuse."""

    def __init__(
        self,
        root: Path,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = root / "raw" / "nse" / "corporate_actions" / "historical"
        self._now = now or (lambda: datetime.now(UTC))

    def acquire(
        self,
        specs: Sequence[CorporateActionSourceSpec],
        *,
        session: HttpSession | None = None,
        timeout_seconds: float = 45.0,
    ) -> tuple[ParsedCorporateActionSource, ...]:
        client = (
            session if session is not None else cast(HttpSession, requests.Session())
        )
        return tuple(self._acquire_one(spec, client, timeout_seconds) for spec in specs)

    def verify_or_missing(
        self,
        specs: Sequence[CorporateActionSourceSpec],
    ) -> tuple[ParsedCorporateActionSource, ...]:
        return tuple(self._reuse_one(spec) for spec in specs)

    def _acquire_one(
        self,
        spec: CorporateActionSourceSpec,
        session: HttpSession,
        timeout_seconds: float,
    ) -> ParsedCorporateActionSource:
        if not _official_url(spec.url):
            return self._terminal(
                spec,
                SourceStatus.REJECTED,
                FailureCode.OFFICIAL_SOURCE_NOT_FOUND,
                "source host is not an approved NSE host",
            )
        try:
            response = session.get(
                spec.url,
                headers=SOURCE_HEADERS,
                timeout=timeout_seconds,
                allow_redirects=True,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            code = _http_failure(status)
            return self._terminal(
                spec,
                SourceStatus.FAILED,
                code,
                f"official NSE request failed with HTTP status {status or 'unknown'}",
                http_status=status,
            )
        except Exception as exc:
            return self._terminal(
                spec,
                SourceStatus.FAILED,
                FailureCode.NETWORK_ERROR,
                type(exc).__name__,
            )
        redirects = tuple(str(item.url) for item in response.history) + (
            str(response.url),
        )
        if not all(_official_url(item) for item in redirects):
            return self._terminal(
                spec,
                SourceStatus.REJECTED,
                FailureCode.OFFICIAL_SOURCE_NOT_FOUND,
                "response redirected outside approved NSE hosts",
                http_status=response.status_code,
                redirects=redirects,
            )
        raw = response.content
        content_type = response.headers.get("Content-Type")
        validation = _validate_source(raw, content_type)
        if validation is not None:
            return self._terminal(
                spec,
                SourceStatus.REJECTED,
                validation,
                "official response failed content validation",
                http_status=response.status_code,
                content_type=content_type,
                redirects=redirects,
                byte_size=len(raw),
            )
        digest = sha256(raw).hexdigest()
        directory = self.root / str(spec.covered_start.year)
        directory.mkdir(parents=True, exist_ok=True)
        source_path = directory / f"{spec.source_id}_{digest}.json"
        if source_path.exists() and source_path.read_bytes() != raw:
            return self._terminal(
                spec,
                SourceStatus.REJECTED,
                FailureCode.CHECKSUM_MISMATCH,
                "immutable path exists with different bytes",
            )
        if not source_path.exists():
            source_path.write_bytes(raw)
        parsed = parse_corporate_action_source(spec, raw, digest)
        manifest_path = source_path.with_suffix(".json.manifest.json")
        existing = _read_json(manifest_path)
        retrieved = self._now().astimezone(UTC).isoformat()
        if existing is not None:
            retrieved = str(existing.get("retrieval_timestamp") or retrieved)
        inventory = CorporateActionSourceRecord(
            spec.source_id,
            spec.source_family,
            spec.url,
            True,
            f"NSE_CA_{spec.covered_start.year}",
            retrieved,
            response.status_code,
            content_type,
            redirects,
            len(raw),
            digest,
            spec.covered_start,
            spec.covered_end,
            spec.parser,
            str(source_path),
            parsed[0],
            len(parsed[1]),
            sum(
                item.admission_state is ActionAdmissionState.ADMITTED
                for item in parsed[1]
            ),
            len(parsed[3]),
            SourceStatus.ACQUIRED,
            "NEW_DOWNLOAD" if existing is None else "IMMUTABLE_BYTES_REUSED",
        )
        if existing is None:
            manifest_path.write_text(
                json.dumps(_jsonable(asdict(inventory)), indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
        return ParsedCorporateActionSource(inventory, parsed[1], parsed[2], parsed[3])

    def _reuse_one(
        self,
        spec: CorporateActionSourceSpec,
    ) -> ParsedCorporateActionSource:
        manifest = self._latest_manifest(spec.source_id)
        if manifest is None:
            return self._terminal(
                spec,
                SourceStatus.FAILED,
                FailureCode.OFFICIAL_SOURCE_NOT_FOUND,
                "verification-only mode cannot acquire missing evidence",
            )
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            recorded_path = Path(str(payload["immutable_path"]))
            adjacent_path = Path(str(manifest).removesuffix(".manifest.json"))
            source_path = recorded_path if recorded_path.exists() else adjacent_path
            raw = source_path.read_bytes()
            actual = sha256(raw).hexdigest()
            expected = str(payload["sha256"])
            if actual != expected:
                return self._terminal(
                    spec,
                    SourceStatus.REJECTED,
                    FailureCode.CHECKSUM_MISMATCH,
                    f"expected {expected}; observed {actual}",
                )
            parsed = parse_corporate_action_source(spec, raw, actual)
            inventory = CorporateActionSourceRecord(
                spec.source_id,
                spec.source_family,
                spec.url,
                True,
                str(payload.get("document_id") or f"NSE_CA_{spec.covered_start.year}"),
                str(payload.get("retrieval_timestamp") or "") or None,
                _optional_int(payload.get("http_status")),
                _optional_str(payload.get("content_type")),
                tuple(str(item) for item in payload.get("redirects", ())),
                len(raw),
                actual,
                spec.covered_start,
                spec.covered_end,
                spec.parser,
                str(source_path),
                parsed[0],
                len(parsed[1]),
                sum(
                    item.admission_state is ActionAdmissionState.ADMITTED
                    for item in parsed[1]
                ),
                len(parsed[3]),
                SourceStatus.REUSED,
                "CHECKSUM_VERIFIED",
            )
            return ParsedCorporateActionSource(
                inventory, parsed[1], parsed[2], parsed[3]
            )
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
            return self._terminal(
                spec,
                SourceStatus.REJECTED,
                FailureCode.PARSER_FAILED,
                type(exc).__name__,
            )

    def _latest_manifest(self, source_id: str) -> Path | None:
        paths = tuple(sorted(self.root.glob(f"**/{source_id}_*.manifest.json")))
        if not paths:
            return None
        return max(
            paths,
            key=lambda path: (
                str((_read_json(path) or {}).get("retrieval_timestamp", "")),
                str(path),
            ),
        )

    def _terminal(
        self,
        spec: CorporateActionSourceSpec,
        status: SourceStatus,
        code: FailureCode,
        detail: str,
        *,
        http_status: int | None = None,
        content_type: str | None = None,
        redirects: tuple[str, ...] = (),
        byte_size: int = 0,
    ) -> ParsedCorporateActionSource:
        inventory = CorporateActionSourceRecord(
            spec.source_id,
            spec.source_family,
            spec.url,
            _official_url(spec.url),
            f"NSE_CA_{spec.covered_start.year}",
            self._now().astimezone(UTC).isoformat(),
            http_status,
            content_type,
            redirects,
            byte_size,
            None,
            spec.covered_start,
            spec.covered_end,
            spec.parser,
            None,
            0,
            0,
            0,
            1,
            status,
            "NOT_REUSED",
            code,
            detail,
        )
        rejection = CorporateActionRejection(
            spec.source_id,
            spec.url,
            code,
            detail,
        )
        return ParsedCorporateActionSource(inventory, (), (), (rejection,))


def parse_corporate_action_source(
    spec: CorporateActionSourceSpec,
    raw: bytes,
    digest: str,
) -> tuple[
    int,
    tuple[CorporateActionEvent, ...],
    tuple[CorporateActionLineage, ...],
    tuple[CorporateActionRejection, ...],
]:
    """Parse one immutable official NSE JSON response."""

    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        rejection = CorporateActionRejection(
            spec.source_id,
            spec.url,
            FailureCode.PARSER_FAILED,
            "response is not valid JSON",
        )
        return 0, (), (), (rejection,)
    if not isinstance(payload, list):
        rejection = CorporateActionRejection(
            spec.source_id,
            spec.url,
            FailureCode.UNSUPPORTED_FORMAT,
            "expected a JSON list",
        )
        return 0, (), (), (rejection,)
    actions: list[CorporateActionEvent] = []
    lineage: list[CorporateActionLineage] = []
    rejected: list[CorporateActionRejection] = []
    seen: set[str] = set()
    for row_number, raw_row in enumerate(payload, 1):
        if not isinstance(raw_row, dict):
            rejected.append(
                CorporateActionRejection(
                    spec.source_id,
                    spec.url,
                    FailureCode.UNSUPPORTED_FORMAT,
                    "event row is not an object",
                    row_number,
                )
            )
            continue
        event_or_rejection = _event_from_row(spec, raw_row, row_number)
        if isinstance(event_or_rejection, CorporateActionRejection):
            rejected.append(event_or_rejection)
            continue
        event = event_or_rejection
        if event.action_id in seen:
            rejected.append(
                CorporateActionRejection(
                    spec.source_id,
                    spec.url,
                    FailureCode.DUPLICATE_EVENT,
                    "duplicate deterministic action",
                    row_number,
                    event.action_id,
                )
            )
            continue
        seen.add(event.action_id)
        actions.append(event)
        lineage.append(
            CorporateActionLineage(
                event.action_id,
                spec.source_id,
                digest,
                spec.url,
                spec.parser,
                row_number,
            )
        )
    ordered = tuple(sorted(actions, key=lambda item: (item.ex_date, item.action_id)))
    return len(payload), ordered, tuple(lineage), tuple(rejected)


def reject_conflicting_actions(
    actions: Sequence[CorporateActionEvent],
) -> tuple[tuple[CorporateActionEvent, ...], tuple[CorporateActionRejection, ...]]:
    """Fail closed when official rows disagree for one security/date/type."""

    groups: dict[tuple[str, date, CorporateActionType], list[CorporateActionEvent]] = {}
    for action in actions:
        identity = action.isin or action.symbol
        groups.setdefault((identity, action.ex_date, action.action_type), []).append(
            action
        )
    conflicts: set[str] = set()
    rejected: list[CorporateActionRejection] = []
    for key, group in groups.items():
        terms = {
            (
                item.old_face_value,
                item.new_face_value,
                item.ratio_numerator,
                item.ratio_denominator,
                item.rights_price,
                item.cash_amount,
            )
            for item in group
        }
        if len(group) > 1 and len(terms) > 1:
            conflicts.update(item.action_id for item in group)
            rejected.append(
                CorporateActionRejection(
                    "official_event_stream",
                    "internal:corporate-action-conflict",
                    FailureCode.CONFLICTING_EVENT,
                    f"conflicting official terms for {key}",
                )
            )
    return (
        tuple(
            replace(
                item,
                admission_state=ActionAdmissionState.CONFLICTING,
                adjustment_factor_state=AdjustmentFactorState.CONFLICTING,
                adjustment_factor=None,
                confidence_state=EvidenceConfidence.LOW,
            )
            if item.action_id in conflicts
            else item
            for item in actions
        ),
        tuple(rejected),
    )


def _event_from_row(
    spec: CorporateActionSourceSpec,
    row: Mapping[str, Any],
    row_number: int,
) -> CorporateActionEvent | CorporateActionRejection:
    symbol = str(row.get("symbol") or "").strip().upper()
    series = str(row.get("series") or "").strip().upper()
    isin = str(row.get("isin") or "").strip().upper() or None
    purpose = str(row.get("subject") or "").strip()
    ex_date = _parse_date(row.get("exDate"))
    if series not in {"EQ", "BE", "BZ", "SM", "ST"}:
        return _rejection(
            spec,
            FailureCode.WRONG_MARKET_SEGMENT,
            f"unsupported series {series or 'missing'}",
            row_number,
            symbol,
        )
    if not symbol or ex_date is None:
        return _rejection(
            spec,
            FailureCode.WRONG_SECURITY,
            "symbol or ex-date is missing",
            row_number,
            symbol or None,
        )
    if not spec.covered_start <= ex_date <= spec.covered_end:
        return _rejection(
            spec,
            FailureCode.WRONG_DATE_RANGE,
            f"event date {ex_date} outside source range",
            row_number,
            symbol,
        )
    if isin is not None and not re.fullmatch(r"IN[A-Z0-9]{10}", isin):
        return _rejection(
            spec,
            FailureCode.IDENTITY_UNRESOLVED,
            "malformed ISIN",
            row_number,
            symbol,
        )
    action_type = classify_action_type(purpose)
    terms = _parse_terms(action_type, purpose, _number(row.get("faceVal")))
    required = action_type in {
        CorporateActionType.SPLIT,
        CorporateActionType.BONUS,
        CorporateActionType.RIGHTS,
        CorporateActionType.FACE_VALUE_CHANGE,
        CorporateActionType.CAPITAL_REDUCTION,
    }
    factor_state, factor = _initial_factor(action_type, terms, purpose)
    admission = ActionAdmissionState.ADMITTED
    confidence = EvidenceConfidence.HIGH
    if action_type is CorporateActionType.UNKNOWN_ACTION:
        admission = ActionAdmissionState.REJECTED
        confidence = EvidenceConfidence.LOW
        factor_state = AdjustmentFactorState.UNKNOWN
    elif isin is None:
        admission = ActionAdmissionState.PROVISIONAL
        confidence = EvidenceConfidence.MEDIUM
    action_id = stable_id(
        "NSE",
        isin,
        symbol,
        series,
        action_type.value,
        ex_date,
        purpose,
    )
    identity = f"nse:isin:{isin}" if isin else None
    return CorporateActionEvent(
        action_id,
        "NSE",
        identity,
        symbol,
        series,
        isin,
        action_type,
        purpose,
        _parse_date(row.get("caBroadcastDate")),
        _parse_date(row.get("recDate")),
        ex_date,
        ex_date,
        terms["old_face_value"],
        terms["new_face_value"],
        terms["ratio_numerator"],
        terms["ratio_denominator"],
        terms["cash_amount"],
        terms["rights_price"],
        terms["old_quantity"],
        terms["new_quantity"],
        identity if action_type in _TRANSITION_ACTIONS else None,
        None,
        required,
        factor_state,
        factor,
        spec.source_id,
        spec.url,
        admission,
        confidence,
    )


_TRANSITION_ACTIONS = frozenset(
    {
        CorporateActionType.MERGER,
        CorporateActionType.DEMERGER,
        CorporateActionType.AMALGAMATION,
        CorporateActionType.SCHEME_OF_ARRANGEMENT,
        CorporateActionType.SPIN_OFF,
        CorporateActionType.SECURITY_REPLACEMENT,
        CorporateActionType.ISIN_CHANGE,
        CorporateActionType.SYMBOL_CHANGE,
        CorporateActionType.RELISTING,
    }
)


def classify_action_type(purpose: str) -> CorporateActionType:
    value = purpose.upper()
    checks = (
        (CorporateActionType.DEMERGER, ("DEMERGER", "DE-MERGER")),
        (CorporateActionType.AMALGAMATION, ("AMALGAMATION",)),
        (CorporateActionType.MERGER, ("MERGER", "MERGED")),
        (CorporateActionType.SCHEME_OF_ARRANGEMENT, ("SCHEME",)),
        (CorporateActionType.SPIN_OFF, ("SPIN OFF", "SPIN-OFF")),
        (CorporateActionType.CAPITAL_REDUCTION, ("CAPITAL REDUCTION",)),
        (CorporateActionType.SHARE_CANCELLATION, ("CANCELLATION",)),
        (CorporateActionType.RELISTING, ("RELIST",)),
        (CorporateActionType.ISIN_CHANGE, ("ISIN CHANGE", "CHANGE IN ISIN")),
        (CorporateActionType.SYMBOL_CHANGE, ("SYMBOL CHANGE",)),
        (CorporateActionType.SECURITY_REPLACEMENT, ("REPLACEMENT",)),
        (CorporateActionType.RIGHTS, ("RIGHT",)),
        (CorporateActionType.BONUS, ("BONUS",)),
        (CorporateActionType.SPLIT, ("SPLIT", "SUB-DIVISION", "SUB DIVISION")),
        (CorporateActionType.FACE_VALUE_CHANGE, ("FACE VALUE", "CONSOLIDATION")),
        (CorporateActionType.DIVIDEND, ("DIVIDEND",)),
    )
    for action_type, needles in checks:
        if any(needle in value for needle in needles):
            return action_type
    return CorporateActionType.UNKNOWN_ACTION


def _parse_terms(
    action_type: CorporateActionType,
    purpose: str,
    face_value: float | None,
) -> dict[str, float | None]:
    old_face, new_face = _face_values(purpose)
    if new_face is None:
        new_face = face_value
    ratio = _ratio_for_action(action_type, purpose)
    cash = (
        _money_amount(purpose) if action_type is CorporateActionType.DIVIDEND else None
    )
    rights_price = (
        _rights_price(purpose, face_value)
        if action_type is CorporateActionType.RIGHTS
        else None
    )
    return {
        "old_face_value": old_face,
        "new_face_value": new_face,
        "ratio_numerator": ratio[0] if ratio else None,
        "ratio_denominator": ratio[1] if ratio else None,
        "cash_amount": cash,
        "rights_price": rights_price,
        "old_quantity": ratio[1] if ratio else None,
        "new_quantity": ratio[0] if ratio else None,
    }


def _initial_factor(
    action_type: CorporateActionType,
    terms: Mapping[str, float | None],
    purpose: str = "",
) -> tuple[AdjustmentFactorState, float | None]:
    numerator = terms["ratio_numerator"]
    denominator = terms["ratio_denominator"]
    old_face = terms["old_face_value"]
    new_face = terms["new_face_value"]
    if action_type in {
        CorporateActionType.SPLIT,
        CorporateActionType.FACE_VALUE_CHANGE,
    }:
        if old_face is None or new_face is None:
            return AdjustmentFactorState.AMBIGUOUS, None
        if old_face <= 0 or new_face <= 0:
            return AdjustmentFactorState.INVALID, None
        return AdjustmentFactorState.DERIVED_FROM_OFFICIAL_TERMS, new_face / old_face
    if action_type is CorporateActionType.BONUS:
        if _is_separate_security_distribution(purpose):
            return AdjustmentFactorState.NOT_REQUIRED, None
        if numerator is None or denominator is None:
            return AdjustmentFactorState.AMBIGUOUS, None
        if numerator <= 0 or denominator <= 0:
            return AdjustmentFactorState.INVALID, None
        factor = denominator / (denominator + numerator)
        if old_face is not None:
            if new_face is None:
                return AdjustmentFactorState.AMBIGUOUS, None
            if old_face <= 0 or new_face <= 0:
                return AdjustmentFactorState.INVALID, None
            factor *= new_face / old_face
        return AdjustmentFactorState.DERIVED_FROM_OFFICIAL_TERMS, factor
    if action_type is CorporateActionType.RIGHTS:
        if _is_separate_security_distribution(purpose):
            return (
                AdjustmentFactorState.NOT_REQUIRED
                if not _is_mixed_separate_security_distribution(purpose)
                else AdjustmentFactorState.UNKNOWN,
                None,
            )
        if numerator is None or denominator is None or terms["rights_price"] is None:
            return AdjustmentFactorState.UNKNOWN, None
        return AdjustmentFactorState.UNKNOWN, None
    if action_type is CorporateActionType.DIVIDEND:
        return AdjustmentFactorState.NOT_REQUIRED, None
    if action_type in _TRANSITION_ACTIONS:
        return AdjustmentFactorState.NOT_REQUIRED, None
    if action_type is CorporateActionType.CAPITAL_REDUCTION:
        return AdjustmentFactorState.NOT_REQUIRED, None
    if action_type is CorporateActionType.UNKNOWN_ACTION:
        return AdjustmentFactorState.UNKNOWN, None
    return AdjustmentFactorState.AMBIGUOUS, None


def _face_values(value: str) -> tuple[float | None, float | None]:
    normalized = value.replace(",", " ")
    patterns = (
        (
            r"FROM\s+(?:RS\.?|RE\.?)?\s*([0-9]+(?:\.[0-9]+)?)"
            r".*?TO\s*(?:RS\.?|RE\.?)?\s*([0-9]+(?:\.[0-9]+)?)"
        ),
        (
            r"(?:SPLIT|SUB-DIVISION|SUB DIVISION).*?"
            r"(?:RS\.?|RE\.?)?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:/-)?"
            r".*?TO\s*(?:RS\.?|RE\.?)?\s*"
            r"([0-9]+(?:\.[0-9]+)?)"
        ),
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match is not None:
            return float(match.group(1)), float(match.group(2))
    return None, None


def _ratio_for_action(
    action_type: CorporateActionType,
    value: str,
) -> tuple[float, float] | None:
    if action_type is CorporateActionType.RIGHTS:
        patterns = (
            r"\bRIGHTS?\b(?:\s+ISSUE)?\s*(?:[-/]\s*)?"
            r"(?:EQ(?:UITY)?\s*)?:?\s*(\d+(?:\.\d+)?)\s*:\s*"
            r"(\d+(?:\.\d+)?)",
            r"\bRIGHTS?\b\s+AT\s+(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)",
            r"\bRATIO\s+OF\s+(?:THE\s+)?RIGHTS?\s+(?:IS|AT)\s+"
            r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)",
        )
        return _first_ratio(value, patterns)
    if action_type is CorporateActionType.BONUS:
        return _first_ratio(
            value,
            (
                r"\bBONUS(?:\b|(?=\d))\s*(?:[-/]\s*)?"
                r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)",
                r"\bBONUS\s+(?:ISSUE|SHARES?\s+IN\s+THE\s+RATIO\s+OF)\s+"
                r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)",
            ),
        )
    return _ratio(value)


def _first_ratio(
    value: str,
    patterns: Sequence[str],
) -> tuple[float, float] | None:
    for pattern in patterns:
        match = re.search(pattern, value, re.IGNORECASE)
        if match is not None:
            return float(match.group(1)), float(match.group(2))
    return None


def _ratio(value: str) -> tuple[float, float] | None:
    match = re.search(
        r"(?:BONUS|RIGHTS?)?\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)",
        value,
        re.IGNORECASE,
    )
    if match is None:
        return None
    return float(match.group(1)), float(match.group(2))


def _money_amount(value: str) -> float | None:
    matches = re.findall(
        r"(?:RS\.?|RE\.?)\s*([0-9]+(?:\.[0-9]+)?)",
        value,
        flags=re.IGNORECASE,
    )
    return float(matches[-1]) if matches else None


def _rights_price(value: str, face_value: float | None) -> float | None:
    normalized = value.replace(",", " ")
    if re.search(r"(?:\bAT\s+PAR\b|@\s*PAR\b)", normalized, re.IGNORECASE):
        return face_value if face_value is not None and face_value > 0 else None

    premium_matches = re.findall(
        r"(?:AT\s+A\s+)?(?:PREMIUM|PREM|PRM)(?:\s+OF)?\s*@?\s*"
        r"(?:RS\.?|RE\.?|₹)?\s*"
        r"([0-9]+(?:\.[0-9]+)?)",
        normalized,
        flags=re.IGNORECASE,
    )
    if premium_matches:
        if face_value is None or face_value <= 0:
            return None
        return face_value + float(premium_matches[-1])

    matches = re.findall(
        r"(?:AT|@|PRICE(?:\s+OF)?|ISSUE\s+PRICE(?:\s+PER\s+EQUITY\s+SHARE)?"
        r"(?:\s+IS)?)\s*(?:RS\.?|RE\.?|₹)?\s*"
        r"([0-9]+(?:\.[0-9]+)?)",
        normalized,
        flags=re.IGNORECASE,
    )
    return float(matches[-1]) if matches else None


def _is_separate_security_distribution(value: str) -> bool:
    normalized = f" {value.upper()} "
    return any(
        marker in normalized
        for marker in (
            " NCRPS ",
            " DEBENTURE ",
            " DEBENTURES ",
            " WARRANT ",
            " WARRANTS ",
            " PREFERENCE SHARE ",
            " PREFERENCE SHARES ",
        )
    )


def _is_mixed_separate_security_distribution(value: str) -> bool:
    normalized = f" {value.upper()} "
    families = (
        any(
            marker in normalized for marker in (" NCD ", " DEBENTURE ", " DEBENTURES ")
        ),
        any(marker in normalized for marker in (" WARRANT ", " WARRANTS ")),
        any(
            marker in normalized
            for marker in (
                " NCRPS ",
                " PREFERENCE SHARE ",
                " PREFERENCE SHARES ",
            )
        ),
    )
    return sum(families) > 1


def _parse_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text or text == "-":
        return None
    for pattern in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    return None


def _number(value: object) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _rejection(
    spec: CorporateActionSourceSpec,
    code: FailureCode,
    detail: str,
    row_number: int,
    identifier: str | None,
) -> CorporateActionRejection:
    return CorporateActionRejection(
        spec.source_id,
        spec.url,
        code,
        detail,
        row_number,
        identifier,
    )


def _official_url(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in OFFICIAL_NSE_HOSTS


def _validate_source(raw: bytes, content_type: str | None) -> FailureCode | None:
    if not raw.strip():
        return FailureCode.EMPTY_RESPONSE
    if content_type and not any(
        item in content_type.lower()
        for item in ("json", "text/plain", "application/octet-stream")
    ):
        return FailureCode.INVALID_CONTENT_TYPE
    stripped = raw.lstrip()
    if not stripped.startswith(b"["):
        return FailureCode.UNSUPPORTED_FORMAT
    return None


def _http_failure(status: int | None) -> FailureCode:
    if status in {401, 403}:
        return FailureCode.HTTP_ACCESS_DENIED
    if status == 404:
        return FailureCode.OFFICIAL_SOURCE_NOT_FOUND
    if status == 429:
        return FailureCode.HTTP_RATE_LIMITED
    return FailureCode.NETWORK_ERROR


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _optional_int(value: object) -> int | None:
    return int(value) if isinstance(value, (int, float)) else None


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None


def _jsonable(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return getattr(value, "value")
    return value


__all__ = [
    "OFFICIAL_NSE_HOSTS",
    "OfficialCorporateActionStore",
    "ParsedCorporateActionSource",
    "classify_action_type",
    "default_corporate_action_sources",
    "parse_corporate_action_source",
    "reject_conflicting_actions",
]
