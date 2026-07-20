"""Recover and apply point-in-time corporate actions for historical replay."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import cast

from .base import CanonicalRecoveryEngine
from .evidence_graph import EvidenceGraph
from .models import (
    CanonicalPreviewRow,
    EvidenceGraphSnapshot,
    EvidenceKind,
    EvidenceNode,
    RecoveryContext,
    RecoveryIssue,
    RecoveryResult,
    RecoverySeverity,
)

_ZERO = Decimal("0")
_ONE = Decimal("1")


class CorporateActionType(StrEnum):
    """Governed corporate action categories supported by HTR-003."""

    SPLIT = "SPLIT"
    BONUS = "BONUS"
    RIGHTS = "RIGHTS"
    CASH_DIVIDEND = "CASH_DIVIDEND"
    MERGER = "MERGER"
    DEMERGER = "DEMERGER"
    SYMBOL_CHANGE = "SYMBOL_CHANGE"


class CorporateActionStatus(StrEnum):
    """Whether an action can safely participate in replay adjustment."""

    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class CorporateActionEvent:
    """Canonical immutable corporate action event."""

    event_id: str
    security_id: str
    symbol: str
    action_type: CorporateActionType
    effective_date: date
    announced_at: date
    price_factor: Decimal | None
    volume_factor: Decimal | None
    old_symbol: str | None
    new_symbol: str | None
    cash_amount: Decimal | None
    ratio_numerator: Decimal | None
    ratio_denominator: Decimal | None
    status: CorporateActionStatus
    confidence: Decimal
    evidence_ids: tuple[str, ...]
    source: str

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id must not be empty")
        if not self.security_id.strip():
            raise ValueError("security_id must not be empty")
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        if self.announced_at > self.effective_date:
            raise ValueError("announced_at cannot be after effective_date")
        if not _ZERO <= self.confidence <= _ONE:
            raise ValueError("confidence must be between 0 and 1")
        if self.status is CorporateActionStatus.RESOLVED:
            if self.action_type is not CorporateActionType.SYMBOL_CHANGE:
                if self.price_factor is None or self.volume_factor is None:
                    raise ValueError("resolved price actions require both factors")
                if self.price_factor <= _ZERO or self.volume_factor <= _ZERO:
                    raise ValueError("adjustment factors must be positive")


@dataclass(frozen=True, slots=True)
class CorporateActionBar:
    """Minimal OHLCV bar used by the deterministic adjustment engine."""

    security_id: str
    symbol: str
    trading_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True, slots=True)
class AdjustedCorporateActionBar:
    """Adjusted OHLCV bar with complete action lineage."""

    original: CorporateActionBar
    symbol: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    cumulative_price_factor: Decimal
    cumulative_volume_factor: Decimal
    applied_event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CorporateActionReplayAudit:
    """Summary of adjustment coverage and replay impact."""

    bars_examined: int
    bars_adjusted: int
    events_available: int
    events_applied: int
    unresolved_events: int
    affected_securities: tuple[str, ...]
    maximum_price_change_percent: Decimal
    passed: bool


class CorporateActionTimeline:
    """Immutable point-in-time index of canonical corporate actions."""

    def __init__(self, events: Iterable[CorporateActionEvent]) -> None:
        ordered = tuple(
            sorted(
                events,
                key=lambda item: (
                    item.security_id,
                    item.effective_date,
                    item.action_type.value,
                    item.event_id,
                ),
            )
        )
        seen: set[str] = set()
        for event in ordered:
            if event.event_id in seen:
                raise ValueError(
                    f"duplicate corporate action event_id {event.event_id!r}"
                )
            seen.add(event.event_id)
        self._events = ordered
        by_security: dict[str, list[CorporateActionEvent]] = defaultdict(list)
        for event in ordered:
            by_security[event.security_id].append(event)
        self._by_security = {
            key: tuple(value) for key, value in sorted(by_security.items())
        }

    @property
    def events(self) -> tuple[CorporateActionEvent, ...]:
        return self._events

    def for_security(
        self,
        security_id: str,
        *,
        as_of: date | None = None,
    ) -> tuple[CorporateActionEvent, ...]:
        events = self._by_security.get(security_id, ())
        if as_of is None:
            return events
        return tuple(
            event
            for event in events
            if event.announced_at <= as_of and event.effective_date <= as_of
        )

    @classmethod
    def from_recovery_result(cls, result: RecoveryResult) -> CorporateActionTimeline:
        events = tuple(
            _event_from_mapping(row.values) for row in result.canonical_preview
        )
        return cls(events)


class CorporateActionAdjustmentEngine:
    """Apply backward adjustments without point-in-time lookahead."""

    def __init__(self, timeline: CorporateActionTimeline) -> None:
        self.timeline = timeline

    def adjust_bar(
        self,
        bar: CorporateActionBar,
        *,
        as_of: date,
    ) -> AdjustedCorporateActionBar:
        price_factor = _ONE
        volume_factor = _ONE
        symbol = bar.symbol
        applied: list[str] = []
        for event in self.timeline.for_security(bar.security_id, as_of=as_of):
            if event.status is not CorporateActionStatus.RESOLVED:
                continue
            if bar.trading_date >= event.effective_date:
                continue
            if event.action_type is CorporateActionType.SYMBOL_CHANGE:
                if event.old_symbol and symbol == event.old_symbol and event.new_symbol:
                    symbol = event.new_symbol
                    applied.append(event.event_id)
                continue
            if event.price_factor is None or event.volume_factor is None:
                continue
            price_factor *= event.price_factor
            volume_factor *= event.volume_factor
            applied.append(event.event_id)
        return AdjustedCorporateActionBar(
            original=bar,
            symbol=symbol,
            open=_quantize(bar.open * price_factor),
            high=_quantize(bar.high * price_factor),
            low=_quantize(bar.low * price_factor),
            close=_quantize(bar.close * price_factor),
            volume=_quantize(bar.volume * volume_factor),
            cumulative_price_factor=_quantize(price_factor),
            cumulative_volume_factor=_quantize(volume_factor),
            applied_event_ids=tuple(applied),
        )

    def adjust_bars(
        self,
        bars: Iterable[CorporateActionBar],
        *,
        as_of: date,
    ) -> tuple[AdjustedCorporateActionBar, ...]:
        return tuple(self.adjust_bar(bar, as_of=as_of) for bar in bars)

    def audit(
        self,
        bars: Iterable[CorporateActionBar],
        *,
        as_of: date,
    ) -> CorporateActionReplayAudit:
        source = tuple(bars)
        adjusted = self.adjust_bars(source, as_of=as_of)
        changed = tuple(item for item in adjusted if item.applied_event_ids)
        event_ids = {
            event_id for item in changed for event_id in item.applied_event_ids
        }
        affected = tuple(sorted({item.original.security_id for item in changed}))
        price_changes = tuple(
            abs((item.close / item.original.close - _ONE) * Decimal("100"))
            for item in changed
            if item.original.close != _ZERO
        )
        available = self.timeline.events
        unresolved = sum(
            event.status is CorporateActionStatus.UNRESOLVED for event in available
        )
        return CorporateActionReplayAudit(
            bars_examined=len(source),
            bars_adjusted=len(changed),
            events_available=len(available),
            events_applied=len(event_ids),
            unresolved_events=unresolved,
            affected_securities=affected,
            maximum_price_change_percent=max(price_changes, default=_ZERO).quantize(
                Decimal("0.0001")
            ),
            passed=unresolved == 0,
        )


class CorporateActionRecoveryEngine(CanonicalRecoveryEngine):
    """Recover a governed corporate action timeline from CSV or JSON evidence."""

    engine_key = "corporate-action-recovery"
    engine_version = "1.0.0"

    def discover(self, context: RecoveryContext) -> Mapping[str, object]:
        source_path = _required_path(context.parameters, "corporate_actions")
        return {
            "source_path": source_path,
            "rows": _read_records(source_path),
            "source_name": str(
                context.parameters.get("source_name", "corporate_actions")
            ),
        }

    def build_evidence_graph(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
    ) -> EvidenceGraph:
        del context
        graph = EvidenceGraph()
        source_path = cast(Path, discovery["source_path"])
        source_name = str(discovery["source_name"])
        for index, row in enumerate(_rows(discovery)):
            graph.add_node(
                EvidenceNode(
                    node_id=f"corporate_action:{index}",
                    kind=EvidenceKind.RAW_FILE,
                    source=source_name,
                    locator=f"{source_path}#row={index}",
                    attributes=row,
                )
            )
        return graph

    def validate(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
        graph: EvidenceGraphSnapshot,
    ) -> tuple[RecoveryIssue, ...]:
        del context, graph
        rows = _rows(discovery)
        if not rows:
            return (
                RecoveryIssue(
                    issue_key="empty-corporate-actions",
                    severity=RecoverySeverity.CRITICAL,
                    summary="Corporate action source contains no records.",
                ),
            )
        issues: list[RecoveryIssue] = []
        seen: set[str] = set()
        for index, row in enumerate(rows):
            evidence_id = f"corporate_action:{index}"
            event_id = _text(row, "event_id") or _derived_event_id(row, index)
            if event_id in seen:
                issues.append(
                    RecoveryIssue(
                        issue_key=f"duplicate-event:{event_id}",
                        severity=RecoverySeverity.HIGH,
                        summary="Corporate action event identifier is duplicated.",
                        evidence_ids=(evidence_id,),
                    )
                )
            seen.add(event_id)
            for field in ("security_id", "symbol", "action_type", "effective_date"):
                if not _text(row, field):
                    issues.append(
                        RecoveryIssue(
                            issue_key=f"missing-{field}:{index}",
                            severity=RecoverySeverity.HIGH,
                            summary=(
                                f"Corporate action is missing required field {field}."
                            ),
                            evidence_ids=(evidence_id,),
                        )
                    )
            try:
                action_type = CorporateActionType(_text(row, "action_type").upper())
            except ValueError:
                issues.append(
                    RecoveryIssue(
                        issue_key=f"unsupported-action:{index}",
                        severity=RecoverySeverity.HIGH,
                        summary="Corporate action type is not governed by HTR-003.",
                        evidence_ids=(evidence_id,),
                    )
                )
                continue
            if action_type in {CorporateActionType.SPLIT, CorporateActionType.BONUS}:
                if (
                    _decimal(row, "ratio_numerator") is None
                    or _decimal(row, "ratio_denominator") is None
                ):
                    issues.append(
                        RecoveryIssue(
                            issue_key=f"missing-ratio:{index}",
                            severity=RecoverySeverity.MEDIUM,
                            summary="Share action is missing its governed ratio.",
                            evidence_ids=(evidence_id,),
                        )
                    )
        return tuple(issues)

    def normalize(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
        graph: EvidenceGraphSnapshot,
        validation_issues: tuple[RecoveryIssue, ...],
    ) -> tuple[Mapping[str, object], ...]:
        del context, graph, validation_issues
        source_name = str(discovery["source_name"])
        normalized: list[Mapping[str, object]] = []
        for index, row in enumerate(_rows(discovery)):
            try:
                normalized.append(_normalize_event(row, index, source_name))
            except (ValueError, InvalidOperation):
                normalized.append(_unresolved_event(row, index, source_name))
        return tuple(normalized)

    def recover(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
        graph: EvidenceGraphSnapshot,
        validation_issues: tuple[RecoveryIssue, ...],
        normalized: tuple[Mapping[str, object], ...],
    ) -> tuple[CanonicalPreviewRow, ...]:
        del context, discovery, graph, validation_issues
        return tuple(
            CanonicalPreviewRow(
                record_key=str(row["event_id"]),
                values=row,
                evidence_ids=tuple(cast(Sequence[str], row["evidence_ids"])),
            )
            for row in sorted(normalized, key=lambda item: str(item["event_id"]))
        )

    def verify(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
        graph: EvidenceGraphSnapshot,
        validation_issues: tuple[RecoveryIssue, ...],
        normalized: tuple[Mapping[str, object], ...],
        preview: tuple[CanonicalPreviewRow, ...],
    ) -> tuple[RecoveryIssue, ...]:
        del context, discovery, validation_issues, normalized
        node_ids = {node.node_id for node in graph.nodes}
        issues: list[RecoveryIssue] = []
        seen: set[str] = set()
        for row in preview:
            if row.record_key in seen:
                issues.append(
                    RecoveryIssue(
                        issue_key=f"duplicate-preview-key:{row.record_key}",
                        severity=RecoverySeverity.HIGH,
                        summary="Canonical corporate action key is duplicated.",
                        evidence_ids=row.evidence_ids,
                    )
                )
            seen.add(row.record_key)
            missing = tuple(sorted(set(row.evidence_ids) - node_ids))
            if missing:
                issues.append(
                    RecoveryIssue(
                        issue_key=f"missing-provenance:{row.record_key}",
                        severity=RecoverySeverity.CRITICAL,
                        summary="Corporate action preview references missing evidence.",
                        evidence_ids=missing,
                    )
                )
            if row.values.get("status") == CorporateActionStatus.UNRESOLVED.value:
                issues.append(
                    RecoveryIssue(
                        issue_key=f"unresolved-action:{row.record_key}",
                        severity=RecoverySeverity.MEDIUM,
                        summary="Corporate action lacks safe replay adjustment inputs.",
                        evidence_ids=row.evidence_ids,
                    )
                )
        return tuple(issues)

    def metadata(
        self,
        context: RecoveryContext,
        discovery: Mapping[str, object],
        graph: EvidenceGraphSnapshot,
        preview: tuple[CanonicalPreviewRow, ...],
    ) -> Mapping[str, object]:
        base = dict(super().metadata(context, discovery, graph, preview))
        base.update(
            {
                "resolved_event_count": sum(
                    row.values.get("status") == CorporateActionStatus.RESOLVED.value
                    for row in preview
                ),
                "unresolved_event_count": sum(
                    row.values.get("status") == CorporateActionStatus.UNRESOLVED.value
                    for row in preview
                ),
                "recovery_version": "HTR-003-v1.0.0",
            }
        )
        return base


def export_corporate_action_recovery(
    result: RecoveryResult,
    output: Path,
) -> tuple[Path, ...]:
    """Export deterministic HTR-003 recovery and governance artifacts."""

    output.mkdir(parents=True, exist_ok=True)
    timeline_path = output / "canonical_timeline.csv"
    unresolved_path = output / "unresolved_events.csv"
    verification_path = output / "verification.json"
    provenance_path = output / "provenance.json"
    report_path = output / "report.md"

    rows = [dict(row.values) for row in result.canonical_preview]
    _write_mapping_csv(timeline_path, rows)
    _write_mapping_csv(
        unresolved_path,
        [
            row
            for row in rows
            if row.get("status") == CorporateActionStatus.UNRESOLVED.value
        ],
    )
    verification_path.write_text(
        json.dumps(
            {
                "classification": result.classification,
                "validation_issues": [
                    asdict(item) for item in result.validation_issues
                ],
                "verification_issues": [
                    asdict(item) for item in result.verification_issues
                ],
                "metadata": dict(result.metadata),
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    provenance_path.write_text(
        json.dumps(
            [
                {
                    "event_id": row.record_key,
                    "evidence_ids": row.evidence_ids,
                    "source": row.values.get("source"),
                    "confidence": row.values.get("confidence"),
                }
                for row in result.canonical_preview
            ],
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    report_path.write_text(_render_recovery_report(result), encoding="utf-8")
    return (
        timeline_path,
        unresolved_path,
        verification_path,
        provenance_path,
        report_path,
    )


def export_corporate_action_replay_audit(
    audit: CorporateActionReplayAudit,
    output: Path,
) -> tuple[Path, ...]:
    """Export deterministic replay impact diagnostics."""

    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "replay_audit.json"
    csv_path = output / "replay_audit.csv"
    report_path = output / "replay_audit.md"
    payload = asdict(audit)
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    _write_mapping_csv(csv_path, [payload])
    report_path.write_text(
        "# Corporate Action Replay Audit\n\n"
        f"- Bars Examined: `{audit.bars_examined}`\n"
        f"- Bars Adjusted: `{audit.bars_adjusted}`\n"
        f"- Events Available: `{audit.events_available}`\n"
        f"- Events Applied: `{audit.events_applied}`\n"
        f"- Unresolved Events: `{audit.unresolved_events}`\n"
        f"- Maximum Price Change: `{audit.maximum_price_change_percent}%`\n"
        f"- Result: `{'PASS' if audit.passed else 'FAIL'}`\n",
        encoding="utf-8",
    )
    return json_path, csv_path, report_path


def _normalize_event(
    row: Mapping[str, object],
    index: int,
    source_name: str,
) -> Mapping[str, object]:
    action_type = CorporateActionType(_text(row, "action_type").upper())
    effective = _parse_date(_text(row, "effective_date"))
    announced = _parse_date(_text(row, "announced_at") or effective.isoformat())
    numerator = _decimal(row, "ratio_numerator")
    denominator = _decimal(row, "ratio_denominator")
    cash_amount = _decimal(row, "cash_amount")
    reference_price = _decimal(row, "reference_price")
    rights_price = _decimal(row, "rights_price")
    manual_price_factor = _decimal(row, "price_factor")
    manual_volume_factor = _decimal(row, "volume_factor")
    price_factor, volume_factor = _derive_factors(
        action_type,
        numerator=numerator,
        denominator=denominator,
        cash_amount=cash_amount,
        reference_price=reference_price,
        rights_price=rights_price,
        manual_price_factor=manual_price_factor,
        manual_volume_factor=manual_volume_factor,
    )
    resolved = action_type is CorporateActionType.SYMBOL_CHANGE or (
        price_factor is not None and volume_factor is not None
    )
    evidence_id = f"corporate_action:{index}"
    confidence = _decimal(row, "confidence") or Decimal("0.80")
    confidence = min(max(confidence, _ZERO), _ONE)
    event_id = _text(row, "event_id") or _derived_event_id(row, index)
    return {
        "event_id": event_id,
        "security_id": _text(row, "security_id"),
        "symbol": _text(row, "symbol").upper(),
        "action_type": action_type.value,
        "effective_date": effective.isoformat(),
        "announced_at": announced.isoformat(),
        "price_factor": str(price_factor) if price_factor is not None else None,
        "volume_factor": str(volume_factor) if volume_factor is not None else None,
        "old_symbol": _optional_text(row, "old_symbol"),
        "new_symbol": _optional_text(row, "new_symbol"),
        "cash_amount": str(cash_amount) if cash_amount is not None else None,
        "ratio_numerator": str(numerator) if numerator is not None else None,
        "ratio_denominator": str(denominator) if denominator is not None else None,
        "status": (
            CorporateActionStatus.RESOLVED.value
            if resolved
            else CorporateActionStatus.UNRESOLVED.value
        ),
        "confidence": str(confidence),
        "evidence_ids": (evidence_id,),
        "source": source_name,
        "recovery_version": "HTR-003-v1.0.0",
    }


def _unresolved_event(
    row: Mapping[str, object],
    index: int,
    source_name: str,
) -> Mapping[str, object]:
    effective_text = _text(row, "effective_date") or "1970-01-01"
    announced_text = _text(row, "announced_at") or effective_text
    return {
        "event_id": _text(row, "event_id") or _derived_event_id(row, index),
        "security_id": _text(row, "security_id") or f"UNKNOWN-{index}",
        "symbol": (_text(row, "symbol") or "UNKNOWN").upper(),
        "action_type": (_text(row, "action_type") or "UNKNOWN").upper(),
        "effective_date": effective_text,
        "announced_at": announced_text,
        "price_factor": None,
        "volume_factor": None,
        "old_symbol": _optional_text(row, "old_symbol"),
        "new_symbol": _optional_text(row, "new_symbol"),
        "cash_amount": None,
        "ratio_numerator": None,
        "ratio_denominator": None,
        "status": CorporateActionStatus.UNRESOLVED.value,
        "confidence": "0",
        "evidence_ids": (f"corporate_action:{index}",),
        "source": source_name,
        "recovery_version": "HTR-003-v1.0.0",
    }


def _derive_factors(
    action_type: CorporateActionType,
    *,
    numerator: Decimal | None,
    denominator: Decimal | None,
    cash_amount: Decimal | None,
    reference_price: Decimal | None,
    rights_price: Decimal | None,
    manual_price_factor: Decimal | None,
    manual_volume_factor: Decimal | None,
) -> tuple[Decimal | None, Decimal | None]:
    if action_type is CorporateActionType.SYMBOL_CHANGE:
        return None, None
    if manual_price_factor is not None:
        volume = manual_volume_factor or (_ONE / manual_price_factor)
        return _quantize(manual_price_factor), _quantize(volume)
    if action_type is CorporateActionType.SPLIT:
        if (
            not numerator
            or not denominator
            or numerator <= _ZERO
            or denominator <= _ZERO
        ):
            return None, None
        return _quantize(denominator / numerator), _quantize(numerator / denominator)
    if action_type is CorporateActionType.BONUS:
        if numerator is None or denominator is None or denominator <= _ZERO:
            return None, None
        share_multiplier = (denominator + numerator) / denominator
        return _quantize(_ONE / share_multiplier), _quantize(share_multiplier)
    if action_type is CorporateActionType.RIGHTS:
        if (
            numerator is None
            or denominator is None
            or denominator <= _ZERO
            or reference_price is None
            or reference_price <= _ZERO
            or rights_price is None
        ):
            return None, None
        theoretical = (denominator * reference_price + numerator * rights_price) / (
            denominator + numerator
        )
        share_multiplier = (denominator + numerator) / denominator
        return _quantize(theoretical / reference_price), _quantize(share_multiplier)
    if action_type is CorporateActionType.CASH_DIVIDEND:
        if (
            cash_amount is None
            or reference_price is None
            or reference_price <= _ZERO
            or cash_amount < _ZERO
            or cash_amount >= reference_price
        ):
            return None, None
        return _quantize((reference_price - cash_amount) / reference_price), _ONE
    return None, None


def _event_from_mapping(row: Mapping[str, object]) -> CorporateActionEvent:
    action_type = CorporateActionType(str(row["action_type"]))
    return CorporateActionEvent(
        event_id=str(row["event_id"]),
        security_id=str(row["security_id"]),
        symbol=str(row["symbol"]),
        action_type=action_type,
        effective_date=_parse_date(str(row["effective_date"])),
        announced_at=_parse_date(str(row["announced_at"])),
        price_factor=_optional_decimal_value(row.get("price_factor")),
        volume_factor=_optional_decimal_value(row.get("volume_factor")),
        old_symbol=_optional_string_value(row.get("old_symbol")),
        new_symbol=_optional_string_value(row.get("new_symbol")),
        cash_amount=_optional_decimal_value(row.get("cash_amount")),
        ratio_numerator=_optional_decimal_value(row.get("ratio_numerator")),
        ratio_denominator=_optional_decimal_value(row.get("ratio_denominator")),
        status=CorporateActionStatus(str(row["status"])),
        confidence=Decimal(str(row["confidence"])),
        evidence_ids=tuple(cast(Sequence[str], row["evidence_ids"])),
        source=str(row["source"]),
    )


def _read_records(path: Path) -> tuple[Mapping[str, object], ...]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload = payload.get("records", payload.get("data", []))
        if not isinstance(payload, list):
            raise ValueError("corporate action JSON must contain a list of records")
        return tuple(cast(Mapping[str, object], item) for item in payload)
    with path.open(encoding="utf-8", newline="") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


def _rows(discovery: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    return cast(tuple[Mapping[str, object], ...], discovery["rows"])


def _required_path(parameters: Mapping[str, object], key: str) -> Path:
    value = parameters.get(key)
    if value is None:
        raise ValueError(f"missing required recovery parameter {key!r}")
    path = Path(str(value))
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def _text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    return "" if value is None else str(value).strip()


def _optional_text(row: Mapping[str, object], key: str) -> str | None:
    value = _text(row, key)
    return value or None


def _decimal(row: Mapping[str, object], key: str) -> Decimal | None:
    value = _text(row, key)
    return Decimal(value) if value else None


def _parse_date(value: str) -> date:
    return date.fromisoformat(value[:10])


def _derived_event_id(row: Mapping[str, object], index: int) -> str:
    return ":".join(
        (
            _text(row, "security_id") or "UNKNOWN",
            (_text(row, "action_type") or "UNKNOWN").upper(),
            _text(row, "effective_date") or "UNKNOWN",
            str(index),
        )
    )


def _optional_decimal_value(value: object) -> Decimal | None:
    return None if value in (None, "") else Decimal(str(value))


def _optional_string_value(value: object) -> str | None:
    return None if value in (None, "") else str(value)


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"))


def _write_mapping_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    fieldnames = tuple(sorted({str(key) for row in rows for key in row}))
    if not fieldnames:
        fieldnames = ("event_id",)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, sort_keys=True, default=str)
                    if isinstance(value, (dict, list, tuple))
                    else value
                    for key, value in row.items()
                }
            )


def _render_recovery_report(result: RecoveryResult) -> str:
    resolved = result.metadata.get("resolved_event_count", 0)
    unresolved = result.metadata.get("unresolved_event_count", 0)
    return (
        "# HTR-003 Corporate Action Recovery\n\n"
        f"- Classification: `{result.classification}`\n"
        f"- Events Recovered: `{len(result.canonical_preview)}`\n"
        f"- Resolved Events: `{resolved}`\n"
        f"- Unresolved Events: `{unresolved}`\n"
        f"- Validation Issues: `{len(result.validation_issues)}`\n"
        f"- Verification Issues: `{len(result.verification_issues)}`\n"
        "- Canonical Writes: `False`\n"
    )


__all__ = [
    "AdjustedCorporateActionBar",
    "CorporateActionAdjustmentEngine",
    "CorporateActionBar",
    "CorporateActionEvent",
    "CorporateActionRecoveryEngine",
    "CorporateActionReplayAudit",
    "CorporateActionStatus",
    "CorporateActionTimeline",
    "CorporateActionType",
    "export_corporate_action_recovery",
    "export_corporate_action_replay_audit",
]
