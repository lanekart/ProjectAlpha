from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from alpha.market_truth.warehouse.archive_vault import source_payload
from alpha.market_truth.warehouse.models import (
    AdjustmentStatus,
    CanonicalDailyRecord,
    CorporateActionKind,
    CorporateActionRecord,
    DeliverableRecord,
    Exchange,
    IdentityRecord,
    IndexDailyRecord,
    ReconciliationStatus,
    SessionInventoryRecord,
    SessionState,
    SourceFileRecord,
    WarehouseDataset,
    WarehouseQualityState,
    stable_hash,
)


@dataclass(frozen=True, slots=True)
class ParseIssue:
    row_number: int
    record_key: str
    raw_payload: str
    reason: str


type ParsedRecord = (
    CanonicalDailyRecord
    | IdentityRecord
    | CorporateActionRecord
    | SessionInventoryRecord
    | IndexDailyRecord
    | DeliverableRecord
)


@dataclass(frozen=True, slots=True)
class ParsedWarehouseFile:
    records: tuple[ParsedRecord, ...]
    issues: tuple[ParseIssue, ...]
    schema_fingerprint: str


class WarehouseFileParser:
    def parse(self, path: Path, source: SourceFileRecord) -> ParsedWarehouseFile:
        filename, raw = source_payload(path)
        if not filename.lower().endswith((".csv", ".txt")):
            raise ValueError(f"unsupported warehouse source payload: {filename}")
        text = raw.decode("utf-8-sig", errors="strict")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise ValueError("source file has no header")
        fields = tuple(_column(item) for item in reader.fieldnames)
        rows = tuple(
            {
                _column(key): value.strip()
                for key, value in row.items()
                if key is not None
            }
            for row in reader
        )
        fingerprint = stable_hash(fields)
        if source.dataset_type is WarehouseDataset.BHAVCOPY:
            return self._daily(rows, source, fingerprint)
        if source.dataset_type is WarehouseDataset.SECURITIES:
            return self._identities(rows, source, fingerprint)
        if source.dataset_type is WarehouseDataset.CORPORATE_ACTIONS:
            return self._corporate_actions(rows, source, fingerprint)
        if source.dataset_type is WarehouseDataset.CALENDAR:
            return self._calendar(rows, source, fingerprint)
        if source.dataset_type is WarehouseDataset.INDICES:
            return self._indices(rows, source, fingerprint)
        if source.dataset_type is WarehouseDataset.DELIVERABLES:
            return self._deliverables(rows, source, fingerprint)
        raise ValueError(
            f"parser for {source.dataset_type.value} is not implemented; "
            "file remains archived"
        )

    def _calendar(
        self,
        rows: tuple[dict[str, str], ...],
        source: SourceFileRecord,
        fingerprint: str,
    ) -> ParsedWarehouseFile:
        records: list[SessionInventoryRecord] = []
        issues: list[ParseIssue] = []
        for row_number, row in enumerate(rows, start=2):
            try:
                session_date = _date_value(
                    _value(row, "sessiondate", "date", "tradingdate")
                    or (
                        None
                        if source.trading_date is None
                        else source.trading_date.isoformat()
                    )
                )
                if session_date is None:
                    raise ValueError("calendar session date is required")
                status = _value(row, "state", "status", "sessiontype").upper()
                state = {
                    "HOLIDAY": SessionState.HOLIDAY,
                    "SPECIAL_SESSION": SessionState.SPECIAL_SESSION,
                    "SPECIAL": SessionState.SPECIAL_SESSION,
                    "FULL": SessionState.EXPECTED,
                    "TRADING": SessionState.EXPECTED,
                    "OPEN": SessionState.EXPECTED,
                    "EXPECTED": SessionState.EXPECTED,
                }.get(status)
                if state is None:
                    raise ValueError(f"unsupported exchange calendar state: {status}")
                records.append(
                    SessionInventoryRecord(
                        exchange=source.exchange,
                        session_date=session_date,
                        state=state,
                        source_file_id=source.source_file_id,
                        reason="Authoritative exchange calendar source.",
                    )
                )
            except ValueError as exc:
                issues.append(
                    ParseIssue(
                        row_number,
                        f"calendar-row-{row_number}",
                        _safe_row(row),
                        str(exc),
                    )
                )
        return ParsedWarehouseFile(tuple(records), tuple(issues), fingerprint)

    def _indices(
        self,
        rows: tuple[dict[str, str], ...],
        source: SourceFileRecord,
        fingerprint: str,
    ) -> ParsedWarehouseFile:
        records: list[IndexDailyRecord] = []
        issues: list[ParseIssue] = []
        for row_number, row in enumerate(rows, start=2):
            index_name = _value(row, "indexname", "index", "name")
            try:
                trading_date = _date_value(
                    _value(row, "tradingdate", "date", "indexdate")
                    or (
                        None
                        if source.trading_date is None
                        else source.trading_date.isoformat()
                    )
                )
                if not index_name or trading_date is None:
                    raise ValueError("index name and trading date are required")
                index_id = _value(row, "indexid", "indexcode") or (
                    f"{source.exchange.value}:INDEX:{_column(index_name).upper()}"
                )
                records.append(
                    IndexDailyRecord(
                        exchange=source.exchange,
                        index_id=index_id,
                        index_name=index_name,
                        trading_date=trading_date,
                        open=_decimal(row, "open", "openindexvalue"),
                        high=_decimal(row, "high", "highindexvalue"),
                        low=_decimal(row, "low", "lowindexvalue"),
                        close=_required_decimal(
                            row, "close", "closingindexvalue", "value"
                        ),
                        source_file_id=source.source_file_id,
                        dataset_version="WAREHOUSE_UNPUBLISHED",
                        volume=_decimal(
                            row,
                            "volume",
                            "totaltradedquantity",
                            "tottrdqty",
                        ),
                    )
                )
            except (InvalidOperation, ValueError) as exc:
                issues.append(
                    ParseIssue(
                        row_number,
                        index_name or f"index-row-{row_number}",
                        _safe_row(row),
                        str(exc),
                    )
                )
        return ParsedWarehouseFile(tuple(records), tuple(issues), fingerprint)

    def _deliverables(
        self,
        rows: tuple[dict[str, str], ...],
        source: SourceFileRecord,
        fingerprint: str,
    ) -> ParsedWarehouseFile:
        records: list[DeliverableRecord] = []
        issues: list[ParseIssue] = []
        for row_number, row in enumerate(rows, start=2):
            symbol = _value(row, "symbol", "tckrsymb", "sccode")
            try:
                trading_date = _date_value(
                    _value(row, "tradingdate", "date", "traddt")
                    or (
                        None
                        if source.trading_date is None
                        else source.trading_date.isoformat()
                    )
                )
                if not symbol or trading_date is None:
                    raise ValueError("deliverable symbol and trading date are required")
                series = _optional(_value(row, "series", "sctysrs"))
                isin = _optional(_value(row, "isin"))
                quantity = _decimal(
                    row, "deliverablequantity", "deliveryqty", "delivqty"
                )
                percentage = _decimal(
                    row, "deliverablepercentage", "deliverypercentage", "delivper"
                )
                if quantity is None and percentage is None:
                    raise ValueError("deliverable quantity or percentage is required")
                records.append(
                    DeliverableRecord(
                        exchange=source.exchange,
                        trading_date=trading_date,
                        security_id=_security_id(source.exchange, symbol, series, isin),
                        symbol=symbol,
                        series=series,
                        deliverable_quantity=quantity,
                        deliverable_percentage=percentage,
                        source_file_id=source.source_file_id,
                    )
                )
            except (InvalidOperation, ValueError) as exc:
                issues.append(
                    ParseIssue(
                        row_number,
                        symbol or f"deliverable-row-{row_number}",
                        _safe_row(row),
                        str(exc),
                    )
                )
        return ParsedWarehouseFile(tuple(records), tuple(issues), fingerprint)

    def _daily(
        self,
        rows: tuple[dict[str, str], ...],
        source: SourceFileRecord,
        fingerprint: str,
    ) -> ParsedWarehouseFile:
        records: list[CanonicalDailyRecord] = []
        issues: list[ParseIssue] = []
        seen: set[tuple[date, str]] = set()
        for row_number, row in enumerate(rows, start=2):
            symbol = _value(row, "symbol", "tckrsymb", "sccode", "scname", "scripname")
            try:
                trading_date = _date_value(
                    _value(row, "tradedate", "timestamp", "traddt", "bizdt")
                    or (
                        None
                        if source.trading_date is None
                        else source.trading_date.isoformat()
                    )
                )
                if not symbol or trading_date is None:
                    raise ValueError("symbol and trading date are required")
                series = _optional(_value(row, "series", "sctysrs", "scgroup"))
                isin = _optional(_value(row, "isin", "isinno"))
                security_id = _security_id(source.exchange, symbol, series, isin)
                key = (trading_date, security_id)
                if key in seen:
                    raise ValueError("duplicate security within source session")
                seen.add(key)
                record = CanonicalDailyRecord(
                    exchange=source.exchange,
                    trading_date=trading_date,
                    security_id=security_id,
                    symbol_as_traded=symbol,
                    series=series,
                    isin=isin,
                    open=_required_decimal(row, "open", "openprice", "opnpric"),
                    high=_required_decimal(row, "high", "highprice", "hghpric"),
                    low=_required_decimal(row, "low", "lowprice", "lwpric"),
                    close=_required_decimal(row, "close", "closeprice", "clspric"),
                    last_price=_decimal(row, "last", "lastprice", "lastpric"),
                    previous_close=_decimal(
                        row, "prevclose", "previousclose", "prvsclsgpric"
                    ),
                    volume=_required_decimal(
                        row,
                        "volume",
                        "tottrdqty",
                        "totaltradedquantity",
                        "ttltradgvol",
                        "noofshares",
                        "noofshrs",
                    ),
                    turnover=_decimal(
                        row,
                        "turnover",
                        "tottrdval",
                        "ttltrfval",
                        "netturovr",
                        "netturnov",
                    ),
                    trade_count=_integer(
                        row, "trades", "tradecount", "ttlnboftxsexctd", "notrades"
                    ),
                    vwap=_decimal(row, "vwap", "wghtdavgpr"),
                    deliverable_quantity=_decimal(
                        row, "deliverablequantity", "deliveryqty", "delivqty"
                    ),
                    deliverable_percentage=_decimal(
                        row, "deliverablepercentage", "deliverypercentage", "delivper"
                    ),
                    upper_price_band=_decimal(row, "upperpriceband", "upperband"),
                    lower_price_band=_decimal(row, "lowerpriceband", "lowerband"),
                    source_file_id=source.source_file_id,
                    quality_state=WarehouseQualityState.COMPLETE,
                    confidence=Decimal("90"),
                    dataset_version="WAREHOUSE_UNPUBLISHED",
                )
                records.append(record)
            except (InvalidOperation, ValueError) as exc:
                issues.append(
                    ParseIssue(
                        row_number=row_number,
                        record_key=symbol or f"row-{row_number}",
                        raw_payload=_safe_row(row),
                        reason=str(exc),
                    )
                )
        return ParsedWarehouseFile(tuple(records), tuple(issues), fingerprint)

    def _identities(
        self,
        rows: tuple[dict[str, str], ...],
        source: SourceFileRecord,
        fingerprint: str,
    ) -> ParsedWarehouseFile:
        records: list[IdentityRecord] = []
        issues: list[ParseIssue] = []
        for row_number, row in enumerate(rows, start=2):
            symbol = _value(row, "symbol", "tckrsymb", "scripid", "scripcode")
            try:
                if not symbol:
                    raise ValueError("identity symbol is required")
                series = _optional(_value(row, "series", "sctysrs", "group"))
                isin = _optional(_value(row, "isin", "isinno"))
                valid_from = _date_value(
                    _value(row, "symbolvalidfrom", "validfrom", "listingdate")
                    or (
                        None
                        if source.trading_date is None
                        else source.trading_date.isoformat()
                    )
                )
                if valid_from is None:
                    raise ValueError("identity valid-from date is required")
                series_from = _date_value(
                    _value(row, "seriesvalidfrom") or valid_from.isoformat()
                )
                assert series_from is not None
                records.append(
                    IdentityRecord(
                        exchange=source.exchange,
                        security_id=_value(row, "securityid", "scripcode")
                        or _security_id(source.exchange, symbol, series, isin),
                        symbol=symbol,
                        series=series,
                        isin=isin,
                        company_name=_optional(
                            _value(row, "companyname", "name", "scname")
                        ),
                        instrument_type=_optional(
                            _value(row, "instrumenttype", "instrument")
                        ),
                        listing_date=_date_value(_value(row, "listingdate")),
                        delisting_date=_date_value(_value(row, "delistingdate")),
                        suspension_intervals=_single_interval(
                            _date_value(_value(row, "suspensionfrom")),
                            _date_value(_value(row, "suspensionto")),
                        ),
                        relisting_intervals=_single_interval(
                            _date_value(_value(row, "relistingfrom")),
                            _date_value(_value(row, "relistingto")),
                        ),
                        symbol_valid_from=valid_from,
                        symbol_valid_to=_date_value(
                            _value(row, "symbolvalidto", "validto")
                        ),
                        series_valid_from=series_from,
                        series_valid_to=_date_value(_value(row, "seriesvalidto")),
                        identity_authority=f"{source.exchange.value}_SOURCE_FILE",
                        identity_confidence=Decimal("90"),
                        source_file_id=source.source_file_id,
                    )
                )
            except (InvalidOperation, ValueError) as exc:
                issues.append(
                    ParseIssue(
                        row_number,
                        symbol or f"row-{row_number}",
                        _safe_row(row),
                        str(exc),
                    )
                )
        return ParsedWarehouseFile(tuple(records), tuple(issues), fingerprint)

    def _corporate_actions(
        self,
        rows: tuple[dict[str, str], ...],
        source: SourceFileRecord,
        fingerprint: str,
    ) -> ParsedWarehouseFile:
        records: list[CorporateActionRecord] = []
        issues: list[ParseIssue] = []
        for row_number, row in enumerate(rows, start=2):
            symbol = _value(row, "symbol", "tckrsymb", "scripcode")
            raw_terms = _value(row, "rawterms", "subject", "purpose", "details")
            try:
                announcement = _date_value(
                    _value(row, "announcementdate", "anndate", "broadcastdate")
                )
                if not symbol or announcement is None:
                    raise ValueError("action symbol and announcement date are required")
                series = _optional(_value(row, "series"))
                isin = _optional(_value(row, "isin", "oldisin"))
                security_id = _value(row, "securityid") or _security_id(
                    source.exchange, symbol, series, isin
                )
                action_type = _action_kind(
                    _value(row, "actiontype", "purpose", "subject")
                )
                numerator, denominator = _ratio(row, raw_terms)
                action_id = _value(row, "corporateactionid", "actionid") or (
                    "action-"
                    + stable_hash(
                        {
                            "exchange": source.exchange.value,
                            "security_id": security_id,
                            "action": action_type.value,
                            "announcement": announcement,
                            "ex_date": _value(row, "exdate"),
                            "terms": raw_terms,
                        }
                    )[:24]
                )
                status = (
                    AdjustmentStatus.INCOMPLETE
                    if action_type
                    in {
                        CorporateActionKind.MERGER,
                        CorporateActionKind.DEMERGER,
                        CorporateActionKind.AMALGAMATION,
                        CorporateActionKind.SCHEME_OF_ARRANGEMENT,
                    }
                    else AdjustmentStatus.NOT_REQUIRED
                )
                reconciliation = _reconciliation_status(
                    action_type=action_type,
                    numerator=numerator,
                    denominator=denominator,
                    cash_amount=_decimal(row, "cashamount", "dividendamount", "amount"),
                    new_symbol=_optional(_value(row, "newsymbol")),
                )
                records.append(
                    CorporateActionRecord(
                        corporate_action_id=action_id,
                        security_id=security_id,
                        exchange=source.exchange,
                        action_type=action_type,
                        announcement_date=announcement,
                        ex_date=_date_value(_value(row, "exdate")),
                        record_date=_date_value(_value(row, "recorddate")),
                        effective_date=_date_value(_value(row, "effectivedate")),
                        payment_date=_date_value(_value(row, "paymentdate")),
                        ratio_numerator=numerator,
                        ratio_denominator=denominator,
                        cash_amount=_decimal(
                            row, "cashamount", "dividendamount", "amount"
                        ),
                        currency=_optional(_value(row, "currency")) or "INR",
                        old_symbol=_optional(_value(row, "oldsymbol")),
                        new_symbol=_optional(_value(row, "newsymbol")),
                        old_isin=_optional(_value(row, "oldisin")),
                        new_isin=_optional(_value(row, "newisin")),
                        source_file_id=source.source_file_id,
                        raw_terms=raw_terms,
                        normalised_terms=_normalised_terms(
                            action_type, numerator, denominator
                        ),
                        evidence_class="AUTHORITATIVE_SOURCE_FILE",
                        confidence=Decimal("90"),
                        reconciliation_status=reconciliation,
                        adjustment_status=status,
                        version="CORPORATE_ACTIONS_UNPUBLISHED",
                    )
                )
            except (InvalidOperation, ValueError) as exc:
                issues.append(
                    ParseIssue(
                        row_number,
                        symbol or f"row-{row_number}",
                        _safe_row(row),
                        str(exc),
                    )
                )
        return ParsedWarehouseFile(tuple(records), tuple(issues), fingerprint)


def _column(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.strip().lower())


def _value(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = row.get(_column(name), "").strip()
        if value and value.upper() not in {"NA", "N/A", "NULL", "NONE", "-"}:
            return value
    return ""


def _optional(value: str) -> str | None:
    return value.strip().upper() or None


def _decimal(row: dict[str, str], *names: str) -> Decimal | None:
    value = _value(row, *names).replace(",", "")
    return None if not value else Decimal(value)


def _required_decimal(row: dict[str, str], *names: str) -> Decimal:
    value = _decimal(row, *names)
    if value is None:
        raise ValueError(f"required numeric field {names[0]} is missing")
    return value


def _integer(row: dict[str, str], *names: str) -> int | None:
    value = _decimal(row, *names)
    return None if value is None else int(value)


def _date_value(value: str | None) -> date | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    for date_format in (
        "%Y-%m-%d",
        "%d-%b-%Y",
        "%d-%b-%y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y%m%d",
    ):
        try:
            return datetime.strptime(cleaned, date_format).date()
        except ValueError:
            continue
    raise ValueError(f"unsupported date value: {cleaned}")


def _security_id(
    exchange: Exchange, symbol: str, series: str | None, isin: str | None
) -> str:
    if isin:
        return f"{exchange.value}:ISIN:{isin.upper()}"
    return f"{exchange.value}:SYMBOL:{symbol.upper()}:{series or 'NA'}"


def _action_kind(value: str) -> CorporateActionKind:
    normalized = value.upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "SPLIT": CorporateActionKind.STOCK_SPLIT,
        "STOCK_SPLIT": CorporateActionKind.STOCK_SPLIT,
        "REVERSE_SPLIT": CorporateActionKind.REVERSE_SPLIT,
        "BONUS": CorporateActionKind.BONUS,
        "RIGHT": CorporateActionKind.RIGHTS,
        "RIGHTS": CorporateActionKind.RIGHTS,
        "DIVIDEND": CorporateActionKind.DIVIDEND,
        "INTERIM_DIVIDEND": CorporateActionKind.INTERIM_DIVIDEND,
        "FINAL_DIVIDEND": CorporateActionKind.FINAL_DIVIDEND,
        "SPECIAL_DIVIDEND": CorporateActionKind.SPECIAL_DIVIDEND,
        "BUYBACK": CorporateActionKind.BUYBACK,
        "MERGER": CorporateActionKind.MERGER,
        "DEMERGER": CorporateActionKind.DEMERGER,
        "AMALGAMATION": CorporateActionKind.AMALGAMATION,
        "SYMBOL_CHANGE": CorporateActionKind.SYMBOL_CHANGE,
        "NAME_CHANGE": CorporateActionKind.NAME_CHANGE,
        "LISTING": CorporateActionKind.LISTING,
        "DELISTING": CorporateActionKind.DELISTING,
        "SUSPENSION": CorporateActionKind.SUSPENSION,
        "RELISTING": CorporateActionKind.RELISTING,
    }
    for key, result in aliases.items():
        if key in normalized:
            return result
    return CorporateActionKind.OTHER


def _ratio(row: dict[str, str], terms: str) -> tuple[Decimal | None, Decimal | None]:
    numerator = _decimal(row, "rationumerator", "numerator")
    denominator = _decimal(row, "ratiodenominator", "denominator")
    if numerator is not None or denominator is not None:
        if numerator is None or denominator is None or denominator <= 0:
            raise ValueError("corporate action ratio is incomplete or invalid")
        return numerator, denominator
    match = re.search(r"(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)", terms)
    if match:
        return Decimal(match.group(1)), Decimal(match.group(2))
    return None, None


def _normalised_terms(
    action: CorporateActionKind,
    numerator: Decimal | None,
    denominator: Decimal | None,
) -> str:
    ratio = "unavailable" if numerator is None else f"{numerator}:{denominator}"
    return f"{action.value}; ratio={ratio}"


def _reconciliation_status(
    *,
    action_type: CorporateActionKind,
    numerator: Decimal | None,
    denominator: Decimal | None,
    cash_amount: Decimal | None,
    new_symbol: str | None,
) -> ReconciliationStatus:
    ratio_actions = {
        CorporateActionKind.STOCK_SPLIT,
        CorporateActionKind.REVERSE_SPLIT,
        CorporateActionKind.BONUS,
        CorporateActionKind.RIGHTS,
    }
    dividend_actions = {
        CorporateActionKind.DIVIDEND,
        CorporateActionKind.INTERIM_DIVIDEND,
        CorporateActionKind.FINAL_DIVIDEND,
        CorporateActionKind.SPECIAL_DIVIDEND,
    }
    if action_type in ratio_actions:
        complete = numerator is not None and denominator is not None
        if action_type is CorporateActionKind.RIGHTS:
            complete = complete and cash_amount is not None
        return (
            ReconciliationStatus.CONFIRMED
            if complete
            else ReconciliationStatus.INCOMPLETE
        )
    if action_type in dividend_actions:
        return (
            ReconciliationStatus.CONFIRMED
            if cash_amount is not None
            else ReconciliationStatus.INCOMPLETE
        )
    if action_type is CorporateActionKind.SYMBOL_CHANGE:
        return (
            ReconciliationStatus.CONFIRMED
            if new_symbol is not None
            else ReconciliationStatus.INCOMPLETE
        )
    if action_type in {
        CorporateActionKind.MERGER,
        CorporateActionKind.DEMERGER,
        CorporateActionKind.AMALGAMATION,
        CorporateActionKind.SCHEME_OF_ARRANGEMENT,
    }:
        return ReconciliationStatus.INCOMPLETE
    return ReconciliationStatus.CONFIRMED


def _safe_row(row: dict[str, str]) -> str:
    return ";".join(f"{key}={value}" for key, value in sorted(row.items()))[:4000]


def _single_interval(
    start: date | None, end: date | None
) -> tuple[tuple[date, date | None], ...]:
    if start is None:
        return ()
    if end is not None and end < start:
        raise ValueError("identity interval end cannot precede start")
    return ((start, end),)


__all__ = [
    "ParseIssue",
    "ParsedRecord",
    "ParsedWarehouseFile",
    "WarehouseFileParser",
]
